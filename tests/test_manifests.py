"""The policy for what an action in this repository may be, enforced on every action.yml.

The rules are not style. They keep each action small enough to read in a minute, keep its
supply chain at zero (no action uses another action), and keep an input from ever becoming
shell code: an input reaches a script only as an environment variable.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = sorted(path.parent for path in ROOT.glob("*/*/action.yml"))
EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
ALLOWED = [
    re.compile(r"inputs\.([\w-]+)"),
    re.compile(r"github\.[\w.]+"),
    re.compile(r"runner\.\w+"),
    re.compile(r"steps\.([\w-]+)\.outputs\.[\w-]+"),
]
SCRIPT = re.compile(r"\$ACTION_PATH/\.\./\.\./(lib/[\w.-]+\.py)")


def load(action: Path) -> dict[str, Any]:
    return yaml.safe_load((action / "action.yml").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def expressions(document: dict[str, Any]) -> list[str]:
    """Every ``${{ ... }}`` in the document, wherever it appears."""
    return EXPRESSION.findall(yaml.safe_dump(document))


ids = [str(action.relative_to(ROOT)) for action in ACTIONS]
every_action = pytest.mark.parametrize("action", ACTIONS, ids=ids)


def test_there_are_actions_to_check():
    assert len(ACTIONS) >= 6


@every_action
def test_an_action_is_named_and_described_and_composite(action):
    document = load(action)
    assert document["name"].strip() and document["description"].strip()
    assert document["runs"]["using"] == "composite"


@every_action
def test_every_input_and_output_is_described_and_defaults_are_strings(action):
    document = load(action)
    for name, spec in (document.get("inputs") or {}).items():
        assert re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", name), f"{name}: use kebab-case"
        assert spec.get("description", "").strip(), f"input {name} has no description"
        if "default" in spec:
            # Inputs are strings. A bare `default: false` is a YAML boolean, which is not.
            assert isinstance(spec["default"], str), f"input {name}: quote the default"
    for name, spec in (document.get("outputs") or {}).items():
        assert spec.get("description", "").strip(), f"output {name} has no description"
        assert spec.get("value"), f"output {name} has no value"


@every_action
def test_an_action_has_only_bash_run_steps_and_no_other_actions(action):
    steps = load(action)["runs"]["steps"]
    assert steps
    for number, step in enumerate(steps, 1):
        where = f"{action.name} step {number}"
        assert "uses" not in step, f"{where}: an action here may not use another action"
        assert "if" not in step, f"{where}: a step condition belongs in the calling workflow"
        assert step.get("shell") == "bash", f"{where}: needs `shell: bash`"
        assert step.get("name"), f"{where}: needs a name"


@every_action
def test_every_step_runs_from_the_workspace_root(action):
    # A job's `defaults.run.working-directory` must not decide where an action runs: its paths are
    # documented as relative to the workspace, so the action says so itself.
    for number, step in enumerate(load(action)["runs"]["steps"], 1):
        assert step.get("working-directory") == "${{ github.workspace }}", (
            f"{action.name} step {number}: set `working-directory: ${{{{ github.workspace }}}}`"
        )


@every_action
def test_no_expression_is_inside_a_script(action):
    for number, step in enumerate(load(action)["runs"]["steps"], 1):
        assert not EXPRESSION.search(step["run"]), (
            f"{action.name} step {number}: an expression inside `run:` can inject shell code; "
            "pass the value through `env:` and read the variable"
        )


@every_action
def test_only_a_few_kinds_of_expression_are_used_and_they_all_resolve(action):
    document = load(action)
    declared = set(document.get("inputs") or {})
    step_ids = {step["id"] for step in document["runs"]["steps"] if "id" in step}
    for expression in expressions(document):
        matches = [pattern.fullmatch(expression) for pattern in ALLOWED]
        match = next((m for m in matches if m), None)
        assert match, f"{action.name}: unsupported expression ${{{{ {expression} }}}}"
        if expression.startswith("inputs."):
            assert match.group(1) in declared, f"{action.name}: {expression} is not declared"
        if expression.startswith("steps."):
            assert match.group(1) in step_ids, f"{action.name}: {expression} has no such step"


@every_action
def test_every_input_is_used(action):
    document = load(action)
    used = {e.removeprefix("inputs.") for e in expressions(document) if e.startswith("inputs.")}
    for name in document.get("inputs") or {}:
        assert name in used, f"{action.name}: input {name} is declared and never used"


@every_action
def test_inputs_reach_scripts_as_environment_variables_only(action):
    for step in load(action)["runs"]["steps"]:
        for key, value in (step.get("env") or {}).items():
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", key), f"{key}: environment names are UPPER_CASE"
            assert EXPRESSION.search(str(value)), f"{key} is not set from an expression"
        names = set(step.get("env") or {})
        quoted = set(re.findall(r'"\$([A-Z][A-Z0-9_]*)"', step["run"]))
        unquoted_ok = {"PYTHON"}  # a command with arguments, deliberately word-split
        for name in quoted - {"GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"}:
            assert name in names, f"{action.name}: ${name} is used but never set in env"
        for name in unquoted_ok & names:
            assert f"${name} " in step["run"], f"{action.name}: {name} should be used unquoted"


@every_action
def test_the_scripts_an_action_runs_exist_and_its_action_path_is_set(action):
    for step in load(action)["runs"]["steps"]:
        scripts = SCRIPT.findall(step["run"])
        if "ACTION_PATH" in step["run"]:
            assert step["env"]["ACTION_PATH"] == "${{ github.action_path }}"
            assert scripts, f"{action.name}: ACTION_PATH is used for something other than lib/"
        for script in scripts:
            assert (ROOT / script).is_file(), f"{action.name}: {script} does not exist"


@every_action
def test_a_boolean_looking_input_is_compared_as_the_string_true(action):
    document = load(action)
    for step in document["runs"]["steps"]:
        for match in re.finditer(r'\[ "\$([A-Z_]+)" = "([^"]*)" \]', step["run"]):
            assert match.group(2) in {"true", ""}, f"{action.name}: compare to the string 'true'"


def test_every_script_in_lib_is_used_by_an_action():
    used = {
        script
        for action in ACTIONS
        for step in load(action)["runs"]["steps"]
        for script in SCRIPT.findall(step["run"])
    }
    shipped = {f"lib/{path.name}" for path in (ROOT / "lib").glob("*.py")}
    assert shipped == used, f"unused scripts: {shipped - used}; missing: {used - shipped}"
