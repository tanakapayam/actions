#!/usr/bin/env python3
"""The release guard: is this GitHub Release ready to be published? (standard library only)

    guard.py --tag python-v1.1.0 --prefix python-v --version 1.1.0 --changelog CHANGELOG.md

It checks that the release tag is the prefix plus the version the code says it is, and that
the changelog has an entry for that version which is not still marked "Unreleased" (and,
with --require-date, carries an ISO date). Each failure is a GitHub `::error::` annotation
and exit status 1; success prints one line and exits 0.
"""

import argparse
import datetime
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path


class GuardError(Exception):
    """The release is not ready; the message says why."""


def summarize(*lines: str) -> None:
    """Append Markdown to the job summary on GitHub (``$GITHUB_STEP_SUMMARY``), else do nothing."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def heading_rest(changelog: str, version: str) -> str | None:
    """What follows ``## [<version>]`` on its heading line, or None if there is no entry."""
    pattern = re.compile(rf"^## \[{re.escape(version)}\](.*)$", re.MULTILINE)
    match = pattern.search(changelog)
    return None if match is None else match.group(1).strip()


def check(
    *, tag: str, prefix: str, version: str, changelog: Path, require_date: bool = False
) -> str:
    """Raise GuardError unless the release is ready; return a one-line confirmation."""
    if not tag:
        raise GuardError("There is no release tag: this check is for a published GitHub Release.")
    if not version:
        raise GuardError("No version was given: the step that reads it from the code found none.")
    if tag != prefix + version:
        raise GuardError(
            f"The release tag {tag} does not match the package version ({prefix}{version})."
        )
    if not changelog.is_file():
        raise GuardError(f"{changelog} does not exist.")
    rest = heading_rest(changelog.read_text(encoding="utf-8"), version)
    if rest is None:
        raise GuardError(f"{changelog} has no entry for {version}.")
    if re.fullmatch(r"-?\s*unreleased", rest, re.IGNORECASE):
        raise GuardError(f"{changelog} still marks {version} as Unreleased; put the date on it.")
    if require_date:
        match = re.fullmatch(r"- (\d{4}-\d{2}-\d{2})", rest)
        try:
            if match is None:
                raise ValueError(rest)
            datetime.date.fromisoformat(match.group(1))
        except ValueError:
            raise GuardError(
                f"{changelog} must head {version} as '## [{version}] - YYYY-MM-DD', "
                f"found '## [{version}] {rest}'."
            ) from None
    return f"release guard: {tag} matches the version, and {changelog} has an entry for {version}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", required=True, help="the release tag, e.g. python-v1.1.0")
    parser.add_argument("--prefix", required=True, help="the tag prefix, e.g. python-v")
    parser.add_argument("--version", required=True, help="the version the code declares")
    parser.add_argument(
        "--changelog",
        type=Path,
        default=Path("CHANGELOG.md"),
        help="the changelog to look in (default: %(default)s)",
    )
    parser.add_argument(
        "--require-date",
        action="store_true",
        help="require the heading to carry an ISO date: ## [1.2.3] - 2026-10-04",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        confirmation = check(
            tag=args.tag,
            prefix=args.prefix,
            version=args.version,
            changelog=args.changelog,
            require_date=args.require_date,
        )
    except GuardError as error:
        print(f"::error::{error}", file=sys.stderr)
        summarize("### ❌ Release guard", "", str(error))
        return 1
    print(confirmation)
    summarize("### ✅ Release guard", "", confirmation.removeprefix("release guard: "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
