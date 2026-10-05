#!/usr/bin/env python3
"""Keep the input and output tables in docs/reference.md identical to the action.yml files.

    uv run python scripts/render_reference.py          rewrite the tables in place
    uv run python scripts/render_reference.py --check  exit 1 if they are out of date

A table sits between ``<!-- generated:<action path> -->`` and ``<!-- /generated -->`` markers;
everything outside the markers is hand-written. tests/test_repo.py runs the check, so a changed
input cannot be merged without its documentation.
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "docs" / "reference.md"
BLOCK = re.compile(
    r"(<!-- generated:(?P<path>[\w/-]+) -->\n)(?P<body>.*?)(<!-- /generated -->)", re.S
)


def cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def default_cell(spec: dict[str, object]) -> str:
    if "default" not in spec:
        return "none"
    value = str(spec["default"])
    return f"`{value}`" if value else "empty"


def table(path: str) -> str:
    document = yaml.safe_load((ROOT / path / "action.yml").read_text(encoding="utf-8"))
    lines = ["| Input | Required | Default | Description |", "| --- | --- | --- | --- |"]
    for name, spec in (document.get("inputs") or {}).items():
        required = "yes" if spec.get("required") else "no"
        row = [f"`{name}`", required, default_cell(spec), cell(spec["description"])]
        lines.append("| " + " | ".join(row) + " |")
    outputs = document.get("outputs") or {}
    if outputs:
        lines += ["", "| Output | Description |", "| --- | --- |"]
        lines += [f"| `{name}` | {cell(spec['description'])} |" for name, spec in outputs.items()]
    return "\n".join(lines) + "\n"


def render(text: str) -> str:
    return BLOCK.sub(
        lambda match: f"{match.group(1)}{table(match.group('path'))}{match.group(4)}", text
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    current = REFERENCE.read_text(encoding="utf-8")
    rendered = render(current)
    if args.check:
        if rendered != current:
            print(
                "docs/reference.md is out of date: run scripts/render_reference.py", file=sys.stderr
            )
            return 1
        return 0
    REFERENCE.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
