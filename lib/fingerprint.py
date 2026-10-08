#!/usr/bin/env python3
"""Fingerprint a set of files, and check later that they are still the same (stdlib only).

    fingerprint.py digest PATH             print sha256-<hex> for a directory (or one file)
    fingerprint.py check PATH EXPECTED     exit 1 unless PATH has exactly that fingerprint

The fingerprint covers every regular file under PATH, by relative path and content: it
changes if any byte, any name, or the set of files does. It is the sha256 of a manifest of
``<sha256>  <relative path>`` lines, sorted by path -- for a flat directory the same lines
``sha256sum`` prints, so a manifest can always be rebuilt and inspected by hand.

Files and directories whose names begin with a dot are not counted unless --include-hidden is
given. That is deliberate: ``actions/upload-artifact`` leaves hidden files out of an artifact
unless told otherwise, and some builders leave one behind (``uv build`` writes a ``.gitignore``
into its output directory), so a fingerprint that counted them would never survive the trip
from the job that builds to the job that checks.
"""

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

FINGERPRINT = re.compile(r"sha256-[0-9a-f]{64}")


class FingerprintError(Exception):
    """Nothing to fingerprint, or the files are not the ones that were fingerprinted.

    ``details`` is a longer explanation, shown in the log and on the summary page but kept out
    of the one-line annotation: what files were counted, and what was left out.
    """

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.details = details


def summarize(*lines: str) -> None:
    """Append Markdown to the job summary on GitHub (``$GITHUB_STEP_SUMMARY``), else do nothing."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_hidden(relative: Path) -> bool:
    """True if any part of the path, below the directory being fingerprinted, starts with a dot."""
    return any(part.startswith(".") for part in relative.parts)


def hidden_files(path: Path) -> list[str]:
    """The hidden files under ``path`` that a default fingerprint does not count."""
    if not path.is_dir():
        return []
    return sorted(
        item.relative_to(path).as_posix()
        for item in path.rglob("*")
        if item.is_file() and is_hidden(item.relative_to(path))
    )


def manifest(path: Path, include_hidden: bool = False) -> list[tuple[str, str]]:
    """``(sha256, relative path)`` for every file under ``path``, sorted by path.

    A single file given as ``path`` is always counted, whatever its name."""
    if not path.exists():
        raise FingerprintError(f"{path} does not exist.")
    if path.is_file():
        return [(sha256_file(path), path.name)]
    entries = []
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path)
        if not include_hidden and is_hidden(relative):
            continue
        if item.is_symlink():
            raise FingerprintError(f"{item} is a symbolic link; a fingerprint covers real files.")
        if item.is_file():
            entries.append((sha256_file(item), relative.as_posix()))
    if not entries:
        raise FingerprintError(f"{path} holds no files, so there is nothing to fingerprint.")
    return sorted(entries, key=lambda entry: entry[1])


def listing(path: Path, include_hidden: bool = False) -> str:
    """What was counted, one ``<sha256 prefix>  <name>`` line per file, and what was left out.
    Printed beside a fingerprint, it is what lets two jobs' views of the files be compared."""
    entries = manifest(path, include_hidden)
    lines = [f"{len(entries)} file(s) counted in {path}:"]
    lines += [f"  {sha[:12]}  {name}" for sha, name in entries]
    left_out = [] if include_hidden else hidden_files(path)
    if left_out:
        lines.append(
            f"{len(left_out)} hidden file(s) not counted (names starting with a dot; "
            f"include-hidden counts them): {', '.join(left_out)}"
        )
    return "\n".join(lines)


def digest(path: Path, include_hidden: bool = False) -> str:
    text = "".join(f"{sha}  {name}\n" for sha, name in manifest(path, include_hidden))
    return "sha256-" + hashlib.sha256(text.encode()).hexdigest()


def check(path: Path, expected: str, include_hidden: bool = False) -> str:
    expected = expected.strip()
    if not FINGERPRINT.fullmatch(expected):
        # An output that was never set arrives here as an empty string: that must not pass.
        raise FingerprintError(
            f"'{expected}' is not a fingerprint (expected sha256- and 64 hex digits); "
            "was the step that produces it skipped?"
        )
    actual = digest(path, include_hidden)
    if actual != expected:
        raise FingerprintError(
            f"The files are not the ones that were fingerprinted (expected {expected}, "
            f"here {actual}).",
            details=f"{listing(path, include_hidden)}\n"
            "Compare this list with the one the fingerprint step printed (and put on its "
            "summary page): a file in one and not the other is the difference. If a hidden "
            "file is the difference, count hidden files on both sides (include-hidden), and "
            "upload them (include-hidden-files: true on actions/upload-artifact).",
        )
    return f"fingerprint: {path} is exactly what was fingerprinted ({expected})"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    hidden = "also count files and directories whose names begin with a dot (default: not counted)"
    digest_parser = commands.add_parser(
        "digest",
        help="print the fingerprint of a directory (or one file)",
        description="Print sha256-<hex>: one digest over the name and content of every file. "
        "The list of files counted goes to standard error.",
    )
    digest_parser.add_argument("path", type=Path, help="the directory or file to fingerprint")
    digest_parser.add_argument("--include-hidden", action="store_true", help=hidden)
    verify = commands.add_parser(
        "check",
        help="exit 1 unless a directory has exactly the given fingerprint",
        description="Fail unless the files have exactly the given fingerprint. An empty or "
        "malformed fingerprint always fails, so a missing value cannot pass the check.",
    )
    verify.add_argument("path", type=Path, help="the directory or file to check")
    verify.add_argument("expected", help="the fingerprint it must have: sha256- and 64 hex digits")
    verify.add_argument("--include-hidden", action="store_true", help=hidden)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "digest":
            found = digest(args.path, args.include_hidden)
            files = listing(args.path, args.include_hidden)
            print(files, file=sys.stderr)
            print(found)
            summarize(
                "<details><summary>Files counted in the fingerprint</summary>", "", "```", files,
                "```", "", "</details>",
            )  # fmt: skip
        else:
            confirmation = check(args.path, args.expected, args.include_hidden)
            print(confirmation)
            summarize("### ✅ Fingerprint verified", "", confirmation.removeprefix("fingerprint: "))
    except FingerprintError as error:
        print(f"::error::{error}", file=sys.stderr)
        if error.details:
            print(error.details, file=sys.stderr)
        if args.command == "check":
            shown = [str(error)]
            if error.details:
                shown += ["", "```", error.details, "```"]
            summarize("### ❌ Fingerprint check failed", "", *shown)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
