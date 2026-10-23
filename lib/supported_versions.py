#!/usr/bin/env python3
"""The Python versions a package claims, as a test matrix (standard library only).

    supported_versions.py [PYPROJECT]

Reads the ``Programming Language :: Python :: 3.x`` classifiers of a ``pyproject.toml`` and
prints ``matrix=``, ``oldest=`` and ``latest=`` lines, which the action turns into outputs. A job
matrix built from them can never drift from what the package says it supports, so there is no
second list to keep in step and no test to police one. The classifiers are checked against
``requires-python`` too: a classifier outside it, or a version it admits that no classifier
lists, is an error, because either one means the package claims something it does not test.
"""

import argparse
import json
import os
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

CLASSIFIER = re.compile(r"Programming Language :: Python :: (3\.\d+)")
SPECIFIER = re.compile(r"\s*(>=|<=|==|!=|>|<)\s*(\d+(?:\.\d+)*)(\.\*)?\s*")
OLDEST_MINOR_CONSIDERED = 6  # versions of Python 3 older than this are not worth reporting


class VersionsError(Exception):
    """The classifiers cannot give a matrix, or contradict requires-python."""


def summarize(*lines: str) -> None:
    """Append Markdown to the job summary on GitHub (``$GITHUB_STEP_SUMMARY``), else do nothing."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def minor(version: str) -> int:
    return int(version.split(".")[1])


def read_project(pyproject: Path) -> dict[str, object]:
    if not pyproject.is_file():
        raise VersionsError(f"{pyproject} does not exist.")
    try:
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise VersionsError(f"{pyproject} is not valid TOML ({error}).") from None
    project = document.get("project")
    if not isinstance(project, dict):
        raise VersionsError(f"{pyproject} has no [project] table.")
    return project


def classifier_versions(project: dict[str, object], pyproject: Path) -> list[str]:
    classifiers = project.get("classifiers", [])
    found = {
        match.group(1)
        for item in classifiers  # type: ignore[attr-defined]
        if isinstance(item, str) and (match := CLASSIFIER.fullmatch(item))
    }
    if not found:
        raise VersionsError(
            f"{pyproject} lists no 'Programming Language :: Python :: 3.x' classifiers, so there "
            "is no list of versions to test: add one for each version you support."
        )
    return sorted(found, key=minor)


def parse_specifiers(text: str) -> list[tuple[str, tuple[int, ...], bool]] | None:
    """``[(operator, version, wildcard)]`` for a requires-python, or None if it is not simple."""
    parsed = []
    for part in text.split(","):
        match = SPECIFIER.fullmatch(part)
        if match is None:
            return None
        parsed.append(
            (match.group(1), tuple(int(n) for n in match.group(2).split(".")), bool(match.group(3)))
        )
    return parsed


def allows(specifiers: list[tuple[str, tuple[int, ...], bool]], version: str) -> bool:
    """Whether Python ``version`` (3.x) satisfies the specifiers, judged by major and minor."""
    value = (3, minor(version))
    for operator, spec, wildcard in specifiers:
        padded = (*spec, 0, 0)[:2]
        if operator == "==" and wildcard:
            ok = value[: len(spec)] == spec
        elif operator == "!=" and wildcard:
            ok = value[: len(spec)] != spec
        else:
            ok = {
                ">=": value >= padded,
                ">": value > padded,
                "<=": value <= padded,
                "<": value < padded,
                "==": value == padded,
                "!=": value != padded,
            }[operator]
        if not ok:
            return False
    return True


def check_requires_python(project: dict[str, object], versions: list[str]) -> list[str]:
    """Notes (warnings) for what could not be checked; raises VersionsError on a contradiction."""
    spec = project.get("requires-python")
    if not isinstance(spec, str):
        return []
    parsed = parse_specifiers(spec)
    if parsed is None:
        return [
            f"requires-python '{spec}' was not understood, so it is not checked "
            "against the classifiers"
        ]
    outside = [v for v in versions if not allows(parsed, v)]
    if outside:
        raise VersionsError(
            f"classifier Python {', '.join(outside)} is outside requires-python '{spec}': "
            "remove the classifier, or widen requires-python."
        )
    below = [
        f"3.{m}"
        for m in range(OLDEST_MINOR_CONSIDERED, minor(versions[0]))
        if allows(parsed, f"3.{m}")
    ]
    if below:
        raise VersionsError(
            f"requires-python '{spec}' admits Python {', '.join(below)}, which no classifier "
            "lists: raise requires-python, or add the classifiers and test them."
        )
    return []


def supported(pyproject: Path, check_requires: bool = True) -> tuple[list[str], list[str]]:
    """``(versions, notes)``: the claimed versions, oldest first, and anything not checked."""
    project = read_project(pyproject)
    versions = classifier_versions(project, pyproject)
    notes = check_requires_python(project, versions) if check_requires else []
    return versions, notes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "pyproject",
        nargs="?",
        type=Path,
        default=Path("pyproject.toml"),
        help="the pyproject.toml to read (default: %(default)s)",
    )
    parser.add_argument(
        "--no-check-requires-python",
        action="store_true",
        help="do not compare the classifiers with requires-python",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        versions, notes = supported(args.pyproject, not args.no_check_requires_python)
    except VersionsError as error:
        print(f"::error::{error}", file=sys.stderr)
        summarize("### ❌ Supported Python versions", "", str(error))
        return 1
    for note in notes:
        print(f"::warning::{note}", file=sys.stderr)
    print(f"matrix={json.dumps(versions, separators=(',', ':'))}")
    print(f"oldest={versions[0]}")
    print(f"latest={versions[-1]}")
    summarize(
        f"### Python versions of `{args.pyproject}`",
        "",
        f"{', '.join(versions)} (from the classifiers; oldest {versions[0]}, "
        f"latest {versions[-1]})",
        *[f"\n⚠️ {note}" for note in notes],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
