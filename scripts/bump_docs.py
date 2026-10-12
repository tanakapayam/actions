#!/usr/bin/env python3
"""Keep the release that the documentation's examples pin in step with the latest release.

    uv run python scripts/bump_docs.py 0.2.0     rewrite the examples to say v0.2.0
    uv run python scripts/bump_docs.py --check   exit 1 unless they name the latest dated release

Only lines that show how to *use* these actions are touched: a line that mentions
``tanakapayam/actions/``, ``git ls-remote`` or ``COMMIT_SHA`` has every ``vX.Y.Z`` on it rewritten,
so a pin comment (``# v0.1.3``) and the tag in the command that looks a commit up always agree.
Placeholders such as ``# vX.Y.Z`` are not versions and stay as they are. RELEASING.md and the
CHANGELOG are history and are never rewritten. tests/test_docs.py runs the check, so a release
cannot go out with examples that pin the one before.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKERS = ("tanakapayam/actions/", "git ls-remote", "COMMIT_SHA")
VERSION = re.compile(r"\bv\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?\b")
RELEASE_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", re.MULTILINE)


def files() -> list[Path]:
    found = [ROOT / "README.md", ROOT / "CONTRIBUTING.md"]
    found += sorted((ROOT / "docs").glob("*.md"))
    found += sorted((ROOT / "templates").glob("*/*.yml"))
    return found


def latest_release() -> str:
    """The newest release the changelog dates; an entry still saying Unreleased is not one."""
    match = RELEASE_HEADING.search((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    if match is None:
        raise SystemExit("CHANGELOG.md has no dated release")
    return match.group(1)


def is_usage_line(line: str) -> bool:
    return any(marker in line for marker in MARKERS)


def rewrite(text: str, version: str) -> str:
    """``text`` with every version on a usage line replaced by ``v<version>``."""
    lines = text.split("\n")
    return "\n".join(
        VERSION.sub(f"v{version}", line) if is_usage_line(line) else line for line in lines
    )


def stale(version: str) -> list[str]:
    """``path:line: text`` for each usage line that names a version other than ``v<version>``."""
    found = []
    for path in files():
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            if is_usage_line(line) and any(v != f"v{version}" for v in VERSION.findall(line)):
                found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", nargs="?", help="the release to name, such as 0.2.0")
    parser.add_argument("--check", action="store_true", help="check against the latest release")
    args = parser.parse_args(argv)
    if args.check == bool(args.version):
        parser.error("give a version to rewrite to, or --check")
    if args.check:
        problems = stale(latest_release())
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print(f"the examples above do not name v{latest_release()}", file=sys.stderr)
        return 1 if problems else 0
    if not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", args.version):
        parser.error(f"{args.version!r} is not a version like 0.2.0")
    changed = []
    for path in files():
        text = path.read_text(encoding="utf-8")
        new = rewrite(text, args.version)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path.relative_to(ROOT).as_posix())
    print(f"v{args.version} in: {', '.join(changed) or 'nothing to change'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
