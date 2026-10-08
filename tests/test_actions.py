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
