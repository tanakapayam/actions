"""The repository as a whole: workflows, templates, docs and the pieces that must agree.

An action that is documented wrongly, a template that passes an input that does not exist, or a
workflow with a floating pin is a bug here, so each is a test.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = sorted(path.parent.relative_to(ROOT).as_posix() for path in ROOT.glob("*/*/action.yml"))
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
TEMPLATES = sorted((ROOT / "templates").glob("*/*.yml"))
TEMPLATE_WORKFLOWS = [
    p for p in TEMPLATES if "jobs" in (yaml.safe_load(p.read_text(encoding="utf-8")) or {})
]
PINNED = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*")
OWN = "tanakapayam/actions/"
MARKDOWN = sorted(
    path
    for path in ROOT.rglob("*.md")
    if ".venv" not in path.parts
    and "fixtures" not in path.parts
    and ".pytest_cache" not in path.parts
)


def load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in document:  # YAML 1.1 reads the key `on` as the boolean True
        document["on"] = document.pop(True)
    return document  # type: ignore[no-any-return]


def jobs(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return document["jobs"]  # type: ignore[no-any-return]


def steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in jobs(document).values() for step in job.get("steps", [])]


# --- workflows -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
class TestWorkflows:
    def test_every_action_used_is_local_or_pinned_to_a_commit_with_its_version(self, path):
        for job in jobs(load(path)).values():
            for step in [{"uses": job["uses"]}] if "uses" in job else job.get("steps", []):
                uses = step.get("uses")
                if uses is None or uses.startswith("./"):
                    continue
                reference = f"{uses}"
                text = path.read_text(encoding="utf-8")
                line = next(line for line in text.splitlines() if reference in line)
                assert PINNED.search(line.split("uses:", 1)[1].strip()), (
                    f"not pinned: {line.strip()}"
                )

    def test_runners_are_pinned_not_latest(self, path):
        for name, job in jobs(load(path)).items():
            runs_on = job.get("runs-on")
            if runs_on is not None:
                assert "latest" not in str(runs_on), f"{name} runs on {runs_on}"

    def test_the_default_token_is_read_only_and_jobs_have_timeouts(self, path):
        document = load(path)
        assert document["permissions"] == {"contents": "read"}
        for name, job in jobs(document).items():
            if "uses" not in job:
                assert "timeout-minutes" in job, f"{name} has no timeout"

    def test_checkouts_do_not_keep_credentials(self, path):
        for step in steps(load(path)):
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False

    def test_no_secrets_and_no_pull_request_target(self, path):
        text = path.read_text(encoding="utf-8")
        assert "secrets." not in text and "secrets:" not in text
        assert "pull_request_target" not in text
        assert "toJSON(github" not in text

    def test_there_is_a_concurrency_group(self, path):
        assert "concurrency" in load(path)


def test_ci_runs_every_job_that_all_green_waits_for():
    ci = load(ROOT / ".github" / "workflows" / "ci.yml")
    others = {name for name in jobs(ci) if name != "all-green"}
    assert set(jobs(ci)["all-green"]["needs"]) == others
    assert jobs(ci)["all-green"]["if"] == "always()"
    assert "workflow_call" in ci["on"] and "pull_request" in ci["on"]


def test_ci_installs_from_the_lockfile_and_pins_both_linters():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert (ROOT / "uv.lock").is_file()
    assert text.count("uv sync --locked") == 2
    # The package `actionlint-py` provides a command named `actionlint`, so `uvx actionlint-py==X`
    # looks for a command that does not exist; `--from` names the package and the command apart.
    assert re.search(r"uvx --from actionlint-py==\d+(\.\d+)+ actionlint", text)
    assert not re.search(r"uvx actionlint-py", text)
    assert re.search(r"uvx zizmor==\d+(\.\d+)+", text)


def test_no_workflow_silences_shellcheck_it_fixes_the_script():
    for path in WORKFLOWS:
        assert "shellcheck disable" not in path.read_text(encoding="utf-8"), path.name


def test_ci_runs_every_action_for_real_in_the_dogfood_job():
    ci = load(ROOT / ".github" / "workflows" / "ci.yml")
    used = {
        step["uses"][2:]
        for step in jobs(ci)["dogfood"]["steps"]
        if step.get("uses", "").startswith("./")
    }
    assert used == set(ACTIONS), (
        f"not dogfooded: {set(ACTIONS) - used}; unknown: {used - set(ACTIONS)}"
    )


def test_dogfood_fingerprints_across_a_real_upload_and_download():
    # A fingerprint that survives only in the job that made it is worthless. This was found by a
    # consumer's first dry run: `uv build` leaves a hidden .gitignore that an upload drops.
    ci = load(ROOT / ".github" / "workflows" / "ci.yml")
    names = [str(step.get("uses", "")).split("@")[0] for step in jobs(ci)["dogfood"]["steps"]]
    fingerprint = names.index("./artifact/fingerprint")
    upload = names.index("actions/upload-artifact")
    download = names.index("actions/download-artifact")
    after = names.index("./artifact/verify-fingerprint", download)
    assert fingerprint < upload < download < after
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Leave a hidden file in the build" in text and "test ! -e" in text


def test_the_release_workflow_checks_the_tag_with_the_guard_it_ships():
    release = load(ROOT / ".github" / "workflows" / "release.yml")
    assert release["on"] == {"release": {"types": ["published"]}}
    guard = next(s for s in steps(release) if s.get("uses") == "./release/guard")
    assert guard["with"]["tag-prefix"] == "v" and guard["with"]["require-date"] == "true"
    assert jobs(release)["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert "needs" in jobs(release)["check"]


# --- templates and workflows that use these actions ----------------------------------------------


def own_uses(document: dict[str, Any]) -> list[tuple[str, dict[str, Any], str]]:
    """(action path, step, step id) for each step that uses an action of this repository."""
    found = []
    for step in steps(document):
        uses = str(step.get("uses", ""))
        if uses.startswith(OWN):
            found.append((uses[len(OWN) :].split("@")[0], step, step.get("id", "")))
        elif uses.startswith("./") and uses[2:] in ACTIONS:
            found.append((uses[2:], step, step.get("id", "")))
    return found


@pytest.mark.parametrize(
    "path", [*TEMPLATE_WORKFLOWS, *WORKFLOWS], ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_every_use_of_an_action_names_real_inputs_and_gives_the_required_ones(path):
    document = load(path)
    outputs_by_id: dict[str, set[str]] = {}
    for action, step, step_id in own_uses(document):
        assert action in ACTIONS, f"{path.name}: there is no action {action}"
        spec = (
            load(ROOT / action / "action.yml")
            if False
            else yaml.safe_load((ROOT / action / "action.yml").read_text())
        )
        declared = set(spec.get("inputs") or {})
        given = set(step.get("with") or {})
        assert given <= declared, f"{path.name}: {action} has no input {given - declared}"
        required = {
            name for name, item in (spec.get("inputs") or {}).items() if item.get("required")
        }
        assert required <= given, f"{path.name}: {action} needs {required - given}"
        if step_id:
            outputs_by_id[step_id] = set(spec.get("outputs") or {})
    text = path.read_text(encoding="utf-8")
    for step_id, outputs in outputs_by_id.items():
        for used in re.findall(rf"steps\.{re.escape(step_id)}\.outputs\.([\w-]+)", text):
            assert used in outputs, f"{path.name}: steps.{step_id}.outputs.{used} does not exist"


def test_the_template_is_the_pipeline_the_docs_describe():
    template = load(ROOT / "templates" / "python-package" / "python-publish.yml")
    assert list(jobs(template)) == ["build", "stage", "publish-testpypi", "publish-pypi"]
    used = {action for action, _, _ in own_uses(template)}
    assert used == {
        "release/guard",
        "python/rehearsal-version",
        "artifact/fingerprint",
        "artifact/verify-fingerprint",
        "python/verify-install",
        "python/verify-published",
    }
    assert template["on"]["workflow_dispatch"]["inputs"]["target"]["default"] == "dry-run"


def test_in_the_template_the_rehearsal_checks_provenance_as_the_real_upload_does():
    template = load(ROOT / "templates" / "python-package" / "python-publish.yml")
    for name in ("publish-testpypi", "publish-pypi"):
        read_back = next(
            step
            for step in jobs(template)[name]["steps"]
            if str(step.get("uses", "")).startswith(f"{OWN}python/verify-published@")
        )
        assert read_back["with"]["expect-provenance"] == "true", name


def test_in_the_template_only_the_publish_jobs_may_mint_an_identity():
    template = load(ROOT / "templates" / "python-package" / "python-publish.yml")
    assert template["permissions"] == {"contents": "read"}
    for name, job in jobs(template).items():
        has_identity = (job.get("permissions") or {}).get("id-token") == "write"
        assert has_identity == name.startswith("publish-"), name
    assert jobs(template)["publish-pypi"]["environment"]["name"] == "pypi"


def test_in_the_template_every_job_that_touches_the_files_verifies_them_first():
    template = load(ROOT / "templates" / "python-package" / "python-publish.yml")
    for name in ["stage", "publish-testpypi", "publish-pypi"]:
        names = [step.get("uses", "").split("@")[0] for step in jobs(template)[name]["steps"]]
        download = names.index("actions/download-artifact")
        verify = names.index(f"{OWN}artifact/verify-fingerprint")
        assert download < verify, name
        if name.startswith("publish-"):
            assert verify < names.index("pypa/gh-action-pypi-publish"), name
            assert names.index("pypa/gh-action-pypi-publish") < names.index(
                f"{OWN}python/verify-published"
            ), name


def test_in_the_template_a_placeholder_pin_is_the_only_thing_that_is_not_pinned():
    text = (ROOT / "templates" / "python-package" / "python-publish.yml").read_text(
        encoding="utf-8"
    )
    for line in re.findall(r"uses: (\S+@\S+ # \S+)", text):
        if line.startswith(OWN):
            assert line.endswith("@COMMIT_SHA # vX.Y.Z"), line
        else:
            assert PINNED.fullmatch(line), line


# --- the libraries -------------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted((ROOT / "lib").glob("*.py")), ids=lambda p: p.name)
def test_a_library_script_uses_only_the_standard_library(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


@pytest.mark.parametrize("path", sorted((ROOT / "lib").glob("*.py")), ids=lambda p: p.name)
def test_a_library_script_runs_on_its_own_and_explains_itself(path):
    result = subprocess.run(
        [sys.executable, str(path), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0 and "usage:" in result.stdout


# --- the docs ------------------------------------------------------------------------------------


def test_the_reference_tables_are_generated_from_the_manifests():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "render_reference.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_reference_has_one_section_and_one_generated_table_per_action():
    text = (ROOT / "docs" / "reference.md").read_text(encoding="utf-8")
    sections = re.findall(r"^## `([\w/-]+)`$", text, re.M)
    tables = re.findall(r"<!-- generated:([\w/-]+) -->", text)
    assert sorted(sections) == ACTIONS and sorted(tables) == ACTIONS  # in teaching order, once each
    assert sections == tables  # each table sits under its own heading


def test_the_readme_lists_every_action_and_every_doc():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for action in ACTIONS:
        assert f"[`{action}`](docs/reference.md#" in readme, action
    for doc in (ROOT / "docs").glob("*.md"):
        assert f"docs/{doc.name}" in readme, doc.name


def test_every_documented_action_is_in_the_changelog_entry_for_the_first_release():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for action in ACTIONS:
        assert f"`{action}`" in changelog, action


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_and_anchors_in_the_docs_resolve(path):
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        file, _, anchor = target.partition("#")
        destination = (path.parent / file).resolve()
        assert destination.exists(), f"{path.name}: {target} does not exist"
        if anchor and destination.suffix == ".md":
            assert anchor in anchors(destination), (
                f"{path.name}: no heading for #{anchor} in {file}"
            )


def anchors(path: Path) -> set[str]:
    """GitHub's heading anchors: lowercase, punctuation dropped, spaces to hyphens."""
    result = set()
    for heading in re.findall(r"^#{1,6} (.+)$", path.read_text(encoding="utf-8"), re.M):
        slug = re.sub(r"[^\w\s-]", "", heading.lower().replace("`", "")).strip()
        result.add(re.sub(r"\s", "-", slug))
    return result


def test_the_changelog_has_the_entry_the_first_release_will_need():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## \[0\.1\.0\] - (Unreleased|\d{4}-\d{2}-\d{2})$", changelog, re.M)


# --- hygiene -------------------------------------------------------------------------------------

TEXT = sorted(
    path
    for path in ROOT.rglob("*")
    if path.is_file()
    and path.suffix in {".py", ".md", ".yml", ".toml", ".json"}
    and not set(path.parts)
    & {".venv", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist"}
)


@pytest.mark.parametrize("path", TEXT, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_text_files_are_utf8_with_unix_endings_one_final_newline_and_no_tabs(path):
    data = path.read_bytes()
    text = data.decode("utf-8")
    assert "\r" not in text and text.endswith("\n") and not text.endswith("\n\n")
    if path.suffix != ".md":
        assert "\t" not in text
    assert "\ufeff" not in text


def test_the_license_is_untouched_mit_and_names_the_owner():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Permission is hereby granted, free of charge" in text and "Payam Tanaka" in text
