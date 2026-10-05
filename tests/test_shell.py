"""ShellCheck on the scripts inside the composite actions.

`actionlint` runs ShellCheck on the `run:` scripts of *workflows*, but it does not read an
`action.yml`, so the scripts of the actions themselves would otherwise never be checked. This
runs ShellCheck on each of them, the way actionlint does for a workflow step.

GitHub's runners have ShellCheck installed, so in CI (``CI=true``) a missing ShellCheck is a
failure, not a skip: this must not quietly stop running. Elsewhere it is skipped with a reason.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = sorted(path.parent for path in ROOT.glob("*/*/action.yml"))
SHELLCHECK = shutil.which("shellcheck")


def scripts() -> list[tuple[str, str]]:
    found = []
    for action in ACTIONS:
        document = yaml.safe_load((action / "action.yml").read_text(encoding="utf-8"))
        for number, step in enumerate(document["runs"]["steps"], 1):
            found.append((f"{action.relative_to(ROOT).as_posix()}#{number}", step["run"]))
    return found


def test_shellcheck_is_there_when_ci_needs_it():
    if os.environ.get("CI") == "true":
        assert SHELLCHECK, "ShellCheck is not installed on this runner, so nothing below would run"


@pytest.mark.skipif(SHELLCHECK is None, reason="shellcheck is not installed (it is, in CI)")
@pytest.mark.parametrize(("where", "script"), scripts(), ids=lambda value: str(value)[:48])
def test_an_actions_script_is_clean_under_shellcheck(where, script):
    result = subprocess.run(
        ["shellcheck", "--shell=bash", "--severity=style", "--format=gcc", "-"],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"{where}:\n{result.stdout}"


@pytest.mark.skipif(SHELLCHECK is None, reason="shellcheck is not installed (it is, in CI)")
def test_shellcheck_does_catch_what_it_is_here_for():
    result = subprocess.run(
        ["shellcheck", "--shell=bash", "--severity=style", "--format=gcc", "-"],
        input='echo "x" >> "$(ls dir | head -n 1)"\nrm $unquoted\n',
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0 and "SC2012" in result.stdout and "SC2086" in result.stdout
