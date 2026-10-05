"""A small runner for this repository's composite actions, so their ``action.yml`` is tested.

GitHub does not offer a way to run a composite action on your own machine, and a typo in an
environment variable name or a wrong script path would otherwise only show up in CI. This
runs an action's steps the way the runner does -- ``bash -eo pipefail``, step environment
built from ``env:``, ``$GITHUB_OUTPUT`` and ``$GITHUB_STEP_SUMMARY`` files, action outputs from
step outputs -- and it is *deliberately stricter than GitHub*: it understands only the few
constructs these actions use, and fails loudly on anything else. That strictness is a policy
(see ``tests/test_manifests.py``): an action here has only ``run`` steps with ``shell: bash``,
and an expression such as ``${{ inputs.x }}`` appears in ``env:``, never inside a script.

What it does not do is anything GitHub-side: expression functions, ``uses:`` steps, ``if:``
conditions, and the real runner's environment. The ``dogfood`` job in ``ci.yml`` covers that
by running every action for real.
"""

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
OUTPUT_LINE = re.compile(r"^([A-Za-z_][\w-]*)=(.*)$")
HEREDOC = re.compile(r"^([A-Za-z_][\w-]*)<<(\S+)$")


class HarnessError(Exception):
    """The action uses something the runner here does not model, or was misused."""


@dataclass
class ActionResult:
    returncode: int
    outputs: dict[str, str] = field(default_factory=dict)
    summary: str = ""
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """``{"event": {"release": {"tag_name": "v1"}}}`` -> ``{"event.release.tag_name": "v1"}``."""
    if isinstance(value, dict):
        flat: dict[str, str] = {}
        for key, item in value.items():
            flat.update(flatten(item, f"{prefix}{key}."))
        return flat
    return {prefix.rstrip("."): str(value)}


class Context:
    def __init__(self, github: dict[str, str], runner: dict[str, str]) -> None:
        self.github = github
        self.runner = runner
        self.inputs: dict[str, str] = {}
        self.steps: dict[str, dict[str, str]] = {}

    def evaluate(self, expression: str) -> str:
        scope, _, rest = expression.partition(".")
        if scope == "github" and rest:
            return self.github.get(rest, "")  # GitHub gives "" for a property that is not set
        if scope == "runner" and rest:
            return self.runner.get(rest, "")
        if scope == "inputs" and rest:
            if rest not in self.inputs:
                raise HarnessError(f"inputs.{rest} is not declared")
            return self.inputs[rest]
        if scope == "steps":
            match = re.fullmatch(r"([\w-]+)\.outputs\.([\w-]+)", rest)
            if match:
                return self.steps.get(match.group(1), {}).get(match.group(2), "")
        raise HarnessError(f"unsupported expression: ${{{{ {expression} }}}}")

    def render(self, text: str) -> str:
        return EXPRESSION.sub(lambda match: self.evaluate(match.group(1)), text)


def parse_outputs(text: str) -> dict[str, str]:
    outputs: dict[str, str] = {}
    lines = iter(text.splitlines())
    for line in lines:
        heredoc = HEREDOC.match(line)
        if heredoc:
            body = []
            for inner in lines:
                if inner == heredoc.group(2):
                    break
                body.append(inner)
            outputs[heredoc.group(1)] = "\n".join(body)
            continue
        simple = OUTPUT_LINE.match(line)
        if simple:
            outputs[simple.group(1)] = simple.group(2)
    return outputs


def load(action_dir: Path) -> dict[str, Any]:
    document = yaml.safe_load((action_dir / "action.yml").read_text(encoding="utf-8"))
    if document.get("runs", {}).get("using") != "composite":
        raise HarnessError(f"{action_dir} is not a composite action")
    return document  # type: ignore[no-any-return]


def run_action(
    action_dir: Path,
    inputs: dict[str, str] | None = None,
    *,
    github: dict[str, Any] | None = None,
    cwd: Path | None = None,
    default_cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> ActionResult:
    """Run the steps of the composite action in ``action_dir`` and report what it did.

    ``cwd`` is the workspace. ``default_cwd`` models a job's ``defaults.run.working-directory``:
    where a step with no ``working-directory`` of its own would run."""
    action_dir = action_dir.resolve()
    document = load(action_dir)
    cwd = cwd or Path.cwd()
    given = dict(inputs or {})
    declared = document.get("inputs", {}) or {}
    unknown = set(given) - set(declared)
    if unknown:
        raise HarnessError(f"{action_dir.name} has no input(s) {sorted(unknown)}")

    scratch = Path(tempfile.mkdtemp(prefix="actionrun-"))
    github_context = flatten(github or {})
    github_context.setdefault("action_path", str(action_dir))
    github_context.setdefault("workspace", str(cwd))
    context = Context(github_context, {"temp": str(scratch)})

    for name, spec in declared.items():
        if name in given:
            context.inputs[name] = given[name]
        elif "default" in (spec or {}):
            context.inputs[name] = context.render(str(spec["default"]))
        elif (spec or {}).get("required"):
            raise HarnessError(f"{action_dir.name}: the required input {name} was not given")
        else:
            context.inputs[name] = ""

    output_file, summary_file = scratch / "output", scratch / "summary"
    output_file.touch()
    summary_file.touch()
    base_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GITHUB_", "INPUT_", "RUNNER_"))
    }
    result = ActionResult(returncode=0)
    for number, step in enumerate(document["runs"]["steps"], 1):
        label = f"{action_dir.name} step {number}"
        if "uses" in step or "if" in step:
            raise HarnessError(f"{label}: `uses:` and `if:` are not modelled (and not allowed)")
        if step.get("shell") != "bash":
            raise HarnessError(f"{label}: every run step needs `shell: bash`")
        if EXPRESSION.search(step["run"]):
            raise HarnessError(f"{label}: an expression in a script; put it in `env:` instead")
        step_env = {
            key: context.render(str(value)) for key, value in (step.get("env") or {}).items()
        }
        working = context.render(step["working-directory"]) if "working-directory" in step else None
        output_file.write_text("")
        completed = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            cwd=working or default_cwd or cwd,
            env={
                **base_env,
                "GITHUB_OUTPUT": str(output_file),
                "GITHUB_STEP_SUMMARY": str(summary_file),
                "GITHUB_WORKSPACE": str(cwd),
                "RUNNER_TEMP": str(scratch),
                **(env or {}),
                **step_env,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        result.stdout += completed.stdout
        result.stderr += completed.stderr
        if "id" in step:
            context.steps[step["id"]] = parse_outputs(output_file.read_text(encoding="utf-8"))
        if completed.returncode != 0:
            result.returncode = completed.returncode
            break
    result.summary = summary_file.read_text(encoding="utf-8")
    if result.ok:
        for name, spec in (document.get("outputs") or {}).items():
            result.outputs[name] = context.render(str(spec["value"]))
    return result
