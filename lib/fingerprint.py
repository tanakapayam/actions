#!/usr/bin/env python3
"""Fingerprint a set of files, and check later that they are still the same (stdlib only).

    fingerprint.py digest PATH             print sha256-<hex> for a directory (or one file)
    fingerprint.py check PATH EXPECTED     exit 1 unless PATH has exactly that fingerprint

The fingerprint covers every regular file under PATH, by relative path and content: it
changes if any byte, any name, or the set of files does. It is the sha256 of a manifest of
``<sha256>  <relative path>`` lines, sorted by path -- for a flat directory the same lines
``sha256sum`` prints, so a manifest can always be rebuilt and inspected by hand.
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
    """Nothing to fingerprint, or the files are not the ones that were fingerprinted."""


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


def manifest(path: Path) -> list[tuple[str, str]]:
    """``(sha256, relative path)`` for every file under ``path``, sorted by path."""
    if not path.exists():
        raise FingerprintError(f"{path} does not exist.")
    if path.is_file():
        return [(sha256_file(path), path.name)]
    entries = []
    for item in sorted(path.rglob("*")):
        if item.is_symlink():
            raise FingerprintError(f"{item} is a symbolic link; a fingerprint covers real files.")
        if item.is_file():
            entries.append((sha256_file(item), item.relative_to(path).as_posix()))
    if not entries:
        raise FingerprintError(f"{path} holds no files, so there is nothing to fingerprint.")
    return sorted(entries, key=lambda entry: entry[1])


def digest(path: Path) -> str:
    text = "".join(f"{sha}  {name}\n" for sha, name in manifest(path))
    return "sha256-" + hashlib.sha256(text.encode()).hexdigest()


def check(path: Path, expected: str) -> str:
    expected = expected.strip()
    if not FINGERPRINT.fullmatch(expected):
        # An output that was never set arrives here as an empty string: that must not pass.
        raise FingerprintError(
            f"'{expected}' is not a fingerprint (expected sha256- and 64 hex digits); "
            "was the step that produces it skipped?"
        )
    actual = digest(path)
    if actual != expected:
        raise FingerprintError(
            f"The files are not the ones that were fingerprinted (expected {expected}, "
            f"here {actual})."
        )
    return f"fingerprint: {path} is exactly what was fingerprinted ({expected})"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    digest_parser = commands.add_parser(
        "digest",
        help="print the fingerprint of a directory (or one file)",
        description="Print sha256-<hex>: one digest over the name and content of every file.",
    )
    digest_parser.add_argument("path", type=Path, help="the directory or file to fingerprint")
    verify = commands.add_parser(
        "check",
        help="exit 1 unless a directory has exactly the given fingerprint",
        description="Fail unless the files have exactly the given fingerprint. An empty or "
        "malformed fingerprint always fails, so a missing value cannot pass the check.",
    )
    verify.add_argument("path", type=Path, help="the directory or file to check")
    verify.add_argument("expected", help="the fingerprint it must have: sha256- and 64 hex digits")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "digest":
            print(digest(args.path))
        else:
            confirmation = check(args.path, args.expected)
            print(confirmation)
            summarize("### ✅ Fingerprint verified", "", confirmation.removeprefix("fingerprint: "))
    except FingerprintError as error:
        print(f"::error::{error}", file=sys.stderr)
        if args.command == "check":
            summarize("### ❌ Fingerprint check failed", "", str(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
