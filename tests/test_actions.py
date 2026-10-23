"""Every composite action, end to end: its action.yml, its scripts and how they are wired.

Each test runs the action through ``tests/actionrun.py`` the way the runner would. The
scripts' own logic is tested in their own files; what is pinned down here is the contract a
workflow author sees -- inputs, outputs, defaults, and what a failure looks like.
"""

from pathlib import Path

import actionrun
import pytest
from fakeindex import FakeIndex

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
RELEASE = {"event": {"release": {"tag_name": "python-v1.2.0"}}}

CHANGELOG = "# Changelog\n\n## [1.2.0] - 2026-10-04\n\n## [1.3.0] - Unreleased\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    return tmp_path


# --- release/guard -------------------------------------------------------------------------------


def guard(workspace: Path, **inputs: str) -> actionrun.ActionResult:
    base = {"tag-prefix": "python-v", "version": "1.2.0"}
    return actionrun.run_action(
        ROOT / "release" / "guard", {**base, **inputs}, github=RELEASE, cwd=workspace
    )


def test_the_guard_passes_a_ready_release_using_the_tag_of_the_triggering_release(workspace):
    result = guard(workspace)
    assert result.ok, result.stderr
    assert "python-v1.2.0 matches" in result.stdout
    assert "### ✅ Release guard" in result.summary


def test_the_guard_refuses_a_tag_that_is_not_the_version(workspace):
    result = guard(workspace, version="1.2.1")
    assert not result.ok
    assert "::error::The release tag python-v1.2.0 does not match" in result.stderr
    assert "### ❌ Release guard" in result.summary


def test_the_guard_refuses_an_unreleased_entry(workspace):
    result = actionrun.run_action(
        ROOT / "release" / "guard",
        {"tag-prefix": "python-v", "version": "1.3.0"},
        github={"event": {"release": {"tag_name": "python-v1.3.0"}}},
        cwd=workspace,
    )
    assert not result.ok and "still marks 1.3.0 as Unreleased" in result.stderr


def test_the_guard_can_be_given_the_tag_and_a_changelog_path_and_require_a_date(workspace):
    (workspace / "docs").mkdir()
    (workspace / "docs" / "HISTORY.md").write_text("## [1.2.0]\n", encoding="utf-8")
    inputs = {"tag": "python-v1.2.0", "changelog": "docs/HISTORY.md"}
    assert guard(workspace, **inputs).ok
    refused = guard(workspace, **inputs, **{"require-date": "true"})
    assert not refused.ok and "must head 1.2.0 as" in refused.stderr


def test_the_guard_refuses_when_there_is_no_release_tag(workspace):
    result = actionrun.run_action(
        ROOT / "release" / "guard",
        {"tag-prefix": "python-v", "version": "1.2.0"},
        cwd=workspace,  # a manual run: no release event
    )
    assert not result.ok and "There is no release tag" in result.stderr


def test_the_guard_refuses_an_empty_version(workspace):
    result = guard(workspace, version="")
    assert not result.ok and "No version was given" in result.stderr


def test_the_guard_does_not_let_an_input_become_a_shell_command(workspace):
    marker = workspace / "pwned"
    result = guard(workspace, version=f"1.2.0; touch {marker}", **{"tag-prefix": "$(touch x)"})
    assert not result.ok
    assert not marker.exists() and not (workspace / "x").exists()


# --- artifact/fingerprint and artifact/verify-fingerprint ---------------------------------------


@pytest.fixture
def files(workspace: Path) -> Path:
    directory = workspace / "out"
    directory.mkdir()
    (directory / "a.txt").write_text("one", encoding="utf-8")
    (directory / "b.txt").write_text("two", encoding="utf-8")
    return directory


def fingerprint(workspace: Path, path: str = "out") -> actionrun.ActionResult:
    return actionrun.run_action(ROOT / "artifact" / "fingerprint", {"path": path}, cwd=workspace)


def verify(workspace: Path, expected: str, path: str = "out") -> actionrun.ActionResult:
    return actionrun.run_action(
        ROOT / "artifact" / "verify-fingerprint",
        {"path": path, "expected": expected},
        cwd=workspace,
    )


def test_a_fingerprint_is_an_output_and_a_line_in_the_summary(workspace, files):
    result = fingerprint(workspace)
    assert result.ok, result.stderr
    digest = result.outputs["digest"]
    assert digest.startswith("sha256-") and len(digest) == 7 + 64
    assert digest in result.summary and "`out`" in result.summary


def test_the_same_files_verify_and_changed_files_do_not(workspace, files):
    digest = fingerprint(workspace).outputs["digest"]
    assert verify(workspace, digest).ok
    (files / "a.txt").write_text("changed", encoding="utf-8")
    result = verify(workspace, digest)
    assert not result.ok and "not the ones that were fingerprinted" in result.stderr


def test_an_empty_or_missing_expected_fingerprint_never_verifies(workspace, files):
    for expected in ["", " ", "sha256-"]:
        result = verify(workspace, expected)
        assert not result.ok and "is not a fingerprint" in result.stderr, expected


def test_fingerprinting_nothing_fails_the_step_rather_than_emitting_an_empty_output(workspace):
    (workspace / "empty").mkdir()
    result = fingerprint(workspace, "empty")
    assert not result.ok and "nothing to fingerprint" in result.stderr
    assert result.outputs == {}


def test_a_fingerprint_of_a_missing_path_fails(workspace):
    assert not fingerprint(workspace, "nope").ok


# --- python/rehearsal-version ------------------------------------------------------------------


def test_a_rehearsal_version_is_made_from_the_run_and_written_to_the_file(workspace):
    version_file = workspace / "pkg" / "__init__.py"
    version_file.parent.mkdir()
    version_file.write_text('__version__ = "1.1.0"\n', encoding="utf-8")
    result = actionrun.run_action(
        ROOT / "python" / "rehearsal-version",
        {"file": "pkg/__init__.py"},
        github={"run_number": 42, "run_attempt": 3},
        cwd=workspace,
    )
    assert result.ok, result.stderr
    assert result.outputs == {"version": "1.1.0.dev4203"}
    assert version_file.read_text(encoding="utf-8") == '__version__ = "1.1.0.dev4203"\n'
    assert "1.1.0.dev4203" in result.summary


def test_a_rehearsal_version_can_be_computed_without_writing_and_for_another_file(workspace):
    pyproject = workspace / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "2.0.0"\n', encoding="utf-8")
    result = actionrun.run_action(
        ROOT / "python" / "rehearsal-version",
        {
            "file": "pyproject.toml",
            "pattern": '^version = "([^"]+)"$',
            "run-number": "5",
            "run-attempt": "1",
            "write": "false",
        },
        cwd=workspace,
    )
    assert result.outputs == {"version": "2.0.0.dev501"}
    assert 'version = "2.0.0"' in pyproject.read_text(encoding="utf-8")


def test_a_rehearsal_version_fails_without_a_version_in_the_file(workspace):
    (workspace / "x.py").write_text("nothing\n", encoding="utf-8")
    result = actionrun.run_action(
        ROOT / "python" / "rehearsal-version",
        {"file": "x.py", "run-number": "1", "run-attempt": "1"},
        cwd=workspace,
    )
    assert not result.ok and "no line matching" in result.stderr


# --- python/verify-install and python/verify-published -----------------------------------------


@pytest.mark.integration
def test_verify_install_runs_the_stage_on_a_build(built):
    result = actionrun.run_action(
        ROOT / "python" / "verify-install",
        {
            "dist": "dist",
            "expect-py-typed": "true",
            "smoke": str(FIXTURES / "smoke_greets.py"),
        },
        cwd=built,
    )
    assert result.ok, result.stderr
    assert "wheel:" in result.stdout and "sdist:" in result.stdout
    assert result.stdout.count("greet works") == 2
    assert "### Stage: sample-pkg 0.3.0" in result.summary  # what the run's page shows


@pytest.mark.integration
def test_verify_install_passes_allow_extra_one_glob_per_line(built, dist):
    import zipfile

    wheel = next(dist.glob("*.whl"))
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr("sample_pkg/_generated.py", "")
    inputs = {"dist": str(dist), "source-root": str(built)}
    refused = actionrun.run_action(ROOT / "python" / "verify-install", inputs, cwd=built)
    assert not refused.ok and "_generated.py, which is not in the source tree" in refused.stderr
    allowed = actionrun.run_action(
        ROOT / "python" / "verify-install",
        {**inputs, "allow-extra": "_other.py\n_gen*.py\n"},
        cwd=built,
    )
    assert allowed.ok, allowed.stderr


def test_verify_install_fails_a_build_that_leaves_a_module_out(built, dist):
    import zipfile

    wheel = next(dist.glob("*.whl"))
    kept = wheel.with_suffix(".new")
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(kept, "w") as target:
        for item in source.infolist():
            if "extras" not in item.filename:
                target.writestr(item, source.read(item.filename))
    kept.replace(wheel)
    result = actionrun.run_action(
        ROOT / "python" / "verify-install",
        {"dist": str(dist), "source-root": str(built)},
        cwd=built,
    )
    assert not result.ok and "the wheel is missing sample_pkg/extras.py" in result.stderr


def test_verify_install_runs_under_the_interpreter_it_is_told_to(built, dist):
    result = actionrun.run_action(
        ROOT / "python" / "verify-install",
        {"dist": str(dist), "source-root": str(built), "python": "/nonexistent/python"},
        cwd=built,
    )
    assert not result.ok  # the action really uses its `python` input


@pytest.mark.integration
def test_verify_published_reads_a_release_back_from_an_index(dist):
    with FakeIndex(dist) as index:
        result = actionrun.run_action(
            ROOT / "python" / "verify-published",
            {
                "dist": str(dist),
                "index": index.url,
                "dependency-index": f"{index.url}/simple/",
                "attempts": "3",
                "delay": "0",
                "expect-provenance": "true",
                "expect-py-typed": "true",
            },
        )
    assert result.ok, result.stderr
    assert "provenance: every file is attested" in result.stdout


@pytest.mark.integration
def test_verify_published_fails_on_a_tampered_file(dist):
    with FakeIndex(dist, wrong_listed_hash=["sample_pkg-0.3.0.tar.gz"]) as index:
        result = actionrun.run_action(
            ROOT / "python" / "verify-published",
            {"dist": str(dist), "index": index.url, "attempts": "2", "delay": "0"},
        )
    assert not result.ok and "is not the file that was built" in result.stderr


def test_every_action_runs_from_the_workspace_whatever_the_jobs_default_directory_is(
    workspace, files
):
    elsewhere = workspace / "elsewhere"
    elsewhere.mkdir()
    shape = {"cwd": workspace, "default_cwd": elsewhere}
    made = actionrun.run_action(ROOT / "artifact" / "fingerprint", {"path": "out"}, **shape)
    assert made.ok, made.stderr
    checked = actionrun.run_action(
        ROOT / "artifact" / "verify-fingerprint",
        {"path": "out", "expected": made.outputs["digest"]},
        **shape,
    )
    assert checked.ok, checked.stderr
    guarded = actionrun.run_action(
        ROOT / "release" / "guard",
        {"tag-prefix": "python-v", "version": "1.2.0"},
        github=RELEASE,
        **shape,
    )
    assert guarded.ok, guarded.stderr  # CHANGELOG.md is in the workspace, not in `elsewhere`


# --- hidden files across an upload and a download ------------------------------------------------


def test_a_build_with_a_hidden_file_verifies_after_the_hidden_file_is_gone(workspace, files):
    # What upload-artifact then download-artifact do to `uv build`'s output directory.
    (files / ".gitignore").write_text("*\n", encoding="utf-8")
    built = fingerprint(workspace)
    assert built.ok, built.stderr
    (files / ".gitignore").unlink()
    assert verify(workspace, built.outputs["digest"]).ok


def test_the_build_job_lists_the_files_it_counted_in_its_log_and_summary(workspace, files):
    (files / ".gitignore").write_text("*\n", encoding="utf-8")
    result = fingerprint(workspace)
    assert "2 file(s) counted" in result.stderr and "a.txt" in result.stderr
    assert "1 hidden file(s) not counted" in result.stderr and ".gitignore" in result.stderr
    assert "Files counted in the fingerprint" in result.summary


def test_include_hidden_counts_them_on_both_sides_and_must_match(workspace, files):
    (files / ".gitignore").write_text("*\n", encoding="utf-8")
    counted = actionrun.run_action(
        ROOT / "artifact" / "fingerprint",
        {"path": "out", "include-hidden": "true"},
        cwd=workspace,
    )
    assert counted.ok, counted.stderr
    both = actionrun.run_action(
        ROOT / "artifact" / "verify-fingerprint",
        {"path": "out", "expected": counted.outputs["digest"], "include-hidden": "true"},
        cwd=workspace,
    )
    assert both.ok, both.stderr
    one_side = verify(workspace, counted.outputs["digest"])  # the default: hidden not counted
    assert not one_side.ok
    assert "hidden file(s) not counted" in one_side.stderr
    assert "include-hidden-files: true" in one_side.stderr
    assert "### ❌ Fingerprint check failed" in one_side.summary


# --- ci/all-green --------------------------------------------------------------------------------


def all_green(workspace: Path, **inputs: str) -> actionrun.ActionResult:
    return actionrun.run_action(ROOT / "ci" / "all-green", inputs, cwd=workspace)


def needs_of(**results: str) -> str:
    import json

    return json.dumps({name: {"result": result, "outputs": {}} for name, result in results.items()})


def test_all_green_passes_when_every_job_succeeded(workspace):
    result = all_green(workspace, needs=needs_of(test="success", lint="success"))
    assert result.ok, result.stderr
    assert "all 2 job(s) succeeded" in result.stdout
    assert "### ✅" in result.summary


def test_all_green_fails_on_a_failed_and_on_a_skipped_job(workspace):
    failed = all_green(workspace, needs=needs_of(test="success", lint="failure"))
    assert not failed.ok and "::error::not every job succeeded: lint failure" in failed.stderr
    assert "### ❌" in failed.summary
    skipped = all_green(workspace, needs=needs_of(test="success", docs="skipped"))
    assert not skipped.ok and "docs skipped" in skipped.stderr


def test_all_green_allows_a_skip_only_for_a_job_that_is_named_one_per_line_or_comma(workspace):
    needs = needs_of(test="success", docs="skipped", extra="skipped")
    assert all_green(workspace, needs=needs, **{"allow-skipped": "docs\nextra"}).ok
    assert all_green(workspace, needs=needs, **{"allow-skipped": "docs, extra"}).ok
    assert not all_green(workspace, needs=needs, **{"allow-skipped": "docs"}).ok


def test_all_green_refuses_a_typo_in_allow_skipped_an_empty_needs_and_a_wrong_shape(workspace):
    typo = all_green(workspace, needs=needs_of(test="success"), **{"allow-skipped": "tset"})
    assert not typo.ok and "which is not one of the jobs waited for" in typo.stderr
    assert "needs is empty" in all_green(workspace, needs="{}").stderr
    assert "needs is not JSON" in all_green(workspace, needs="test").stderr
    assert "needs must be the JSON" in all_green(workspace, needs='["test"]').stderr
    assert not all_green(workspace, needs="").ok


# --- python/supported-versions -------------------------------------------------------------------


def versions(workspace: Path, **inputs: str) -> actionrun.ActionResult:
    return actionrun.run_action(ROOT / "python" / "supported-versions", inputs, cwd=workspace)


def test_supported_versions_outputs_the_matrix_oldest_and_latest(workspace):
    result = versions(workspace, pyproject=str(FIXTURES / "sample-pkg" / "pyproject.toml"))
    assert result.ok, result.stderr
    assert result.outputs == {
        "matrix": '["3.11","3.12","3.13"]',
        "oldest": "3.11",
        "latest": "3.13",
    }


def test_supported_versions_reads_pyproject_toml_of_the_workspace_by_default(workspace):
    (workspace / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.12"\n'
        'classifiers = ["Programming Language :: Python :: 3.12",'
        ' "Programming Language :: Python :: 3.13"]\n',
        encoding="utf-8",
    )
    result = versions(workspace)
    assert result.ok and result.outputs["matrix"] == '["3.12","3.13"]'


def test_supported_versions_checks_requires_python_unless_told_not_to(workspace):
    (workspace / "pyproject.toml").write_text(
        '[project]\nrequires-python = ">=3.12"\n'
        'classifiers = ["Programming Language :: Python :: 3.11"]\n',
        encoding="utf-8",
    )
    refused = versions(workspace)
    assert not refused.ok and "is outside requires-python" in refused.stderr
    allowed = versions(workspace, **{"check-requires-python": "false"})
    assert allowed.ok and allowed.outputs["matrix"] == '["3.11"]'


def test_supported_versions_fails_on_a_missing_file_and_on_no_classifiers(workspace):
    assert "does not exist" in versions(workspace).stderr
    (workspace / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    assert "lists no" in versions(workspace).stderr


# --- workflow/policy -----------------------------------------------------------------------------

GOOD_WORKFLOW = """\
name: Good
on: push
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
"""


def policy(workspace: Path, **inputs: str) -> actionrun.ActionResult:
    return actionrun.run_action(ROOT / "workflow" / "policy", inputs, cwd=workspace)


@pytest.fixture
def workflows(workspace: Path) -> Path:
    folder = workspace / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "good.yml").write_text(GOOD_WORKFLOW, encoding="utf-8")
    return folder


def test_policy_passes_good_workflows_in_the_default_place(workspace, workflows):
    result = policy(workspace)
    assert result.ok, result.stderr
    assert "1 workflow file(s) pass" in result.stdout


def test_policy_annotates_each_finding_with_its_file_line_and_rule(workspace, workflows):
    (workflows / "bad.yml").write_text(
        GOOD_WORKFLOW.replace("ubuntu-24.04", "ubuntu-latest"), encoding="utf-8"
    )
    result = policy(workspace)
    assert not result.ok
    assert "::error file=.github/workflows/bad.yml,line=7,title=pinned-runners::" in result.stderr


def test_policy_takes_a_path_to_one_file_and_a_choice_of_rules(workspace, workflows):
    bad = workflows / "bad.yml"
    bad.write_text(GOOD_WORKFLOW.replace("    timeout-minutes: 5\n", ""), encoding="utf-8")
    assert not policy(workspace, path=str(bad.relative_to(workspace))).ok
    assert policy(workspace, rules="pinned-actions,pinned-runners").ok
    assert "unknown rule" in policy(workspace, rules="pinned-action").stderr


def test_policy_allows_id_token_only_for_the_jobs_it_is_told_about(workspace, workflows):
    (workflows / "publish.yml").write_text(
        GOOD_WORKFLOW.replace(
            "    timeout-minutes: 5\n",
            "    timeout-minutes: 5\n    permissions:\n      id-token: write\n",
        ).replace("  test:", "  publish-pypi:"),
        encoding="utf-8",
    )
    assert not policy(workspace).ok
    assert policy(workspace, **{"id-token-jobs": "publish-pypi"}).ok


def test_policy_refuses_what_it_cannot_read_and_an_empty_place(workspace, workflows):
    (workflows / "odd.yml").write_text("on: push\njobs: &x {}\n", encoding="utf-8")
    result = policy(workspace)
    assert not result.ok and "cannot be checked, so it is not trusted" in result.stderr
    empty = workspace / "nothing"
    empty.mkdir()
    assert "no workflow files" in policy(workspace, path="nothing").stderr
