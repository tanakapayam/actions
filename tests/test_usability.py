"""What a person using these scripts, or reading a run page, actually sees.

The scripts are documented as things you can run by hand, and their output is the first thing
anyone reads when a release fails. These tests treat that as part of the contract: every option
explains itself, messages read like sentences, and a failure is on the run's summary page as
well as in the log.
"""

import argparse
import urllib.error
from pathlib import Path

import fingerprint
import guard
import pyrelease
import pytest
from test_pyrelease import make_dist, make_source

SCRIPTS = {"guard": guard, "fingerprint": fingerprint, "pyrelease": pyrelease}


def walk(parser: argparse.ArgumentParser, name: str):
    """Every (command name, action) in a parser and, recursively, its subcommands."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for command, sub in action.choices.items():
                yield from walk(sub, f"{name} {command}")
        else:
            yield name, action


# --- help text -----------------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS)
def test_every_option_and_argument_has_help_text(script):
    for command, action in walk(SCRIPTS[script].build_parser(), script):
        if isinstance(action, argparse._HelpAction):
            continue
        assert action.help, f"{command}: {action.option_strings or action.dest} has no help"


@pytest.mark.parametrize("script", SCRIPTS)
def test_every_subcommand_says_what_it_is_for(script):
    parser = SCRIPTS[script].build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            listed = {choice.dest: choice.help for choice in action._choices_actions}
            for command, sub in action.choices.items():
                assert listed.get(command), f"{script} {command} is not described in the list"
                assert sub.description, f"{script} {command} has no description of its own"


# --- messages ------------------------------------------------------------------------------------


def test_the_stage_reads_like_a_sentence_and_does_not_repeat_the_package_name(
    tmp_path, monkeypatch, capsys
):
    source = make_source(tmp_path / "s")
    dist = make_dist(tmp_path / "d")
    monkeypatch.setattr(pyrelease, "make_venv", lambda parent, name: Path("/nonexistent/python"))
    monkeypatch.setattr(
        pyrelease, "pip", lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "stop here"})()
    )
    with pytest.raises(pyrelease.ReleaseError, match="pip could not install the wheel"):
        pyrelease.verify_install(
            dist,
            source,
            package_dir=None,
            import_name=None,
            allow_extra=[],
            expect_py_typed=False,
            smoke_file=None,
            dependency_index="https://pypi.org/simple/",
        )
    out = capsys.readouterr().out
    assert out.startswith("contents: the wheel and the sdist hold all of src/sample_pkg")
    assert "sample_pkg and sample_pkg" not in out


def test_a_wheel_only_release_says_the_wheel_alone_holds_the_package(tmp_path, monkeypatch, capsys):
    source = make_source(tmp_path / "s")
    dist = make_dist(tmp_path / "d", with_sdist=False)
    monkeypatch.setattr(pyrelease, "make_venv", lambda parent, name: Path("/nonexistent/python"))
    monkeypatch.setattr(
        pyrelease, "pip", lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "stop"})()
    )
    with pytest.raises(pyrelease.ReleaseError):
        pyrelease.verify_install(
            dist,
            source,
            package_dir=None,
            import_name=None,
            allow_extra=[],
            expect_py_typed=False,
            smoke_file=None,
            dependency_index="x",
        )
    assert capsys.readouterr().out.startswith("contents: the wheel hold all of")


def test_a_wrong_source_root_points_at_source_root_first(tmp_path):
    with pytest.raises(pyrelease.ReleaseError) as caught:
        pyrelease.locate_package(tmp_path, "sample_pkg", None)
    message = str(caught.value)
    assert "Is source-root the project root" in message and "package-dir" in message
    assert str(tmp_path.resolve()) in message


def test_a_dist_that_is_not_a_directory_says_so(tmp_path):
    with pytest.raises(pyrelease.ReleaseError, match="is not a directory"):
        pyrelease.find_dists(tmp_path / "nope")


# --- an index that is out of reach is "not yet", never a traceback -------------------------------


def test_a_failed_connection_is_reported_not_raised(monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(pyrelease.urllib.request, "urlopen", refuse)
    status, body = pyrelease.fetch("https://index.example/pypi/x/1/json")
    assert status == pyrelease.UNREACHABLE
    assert b"cannot reach https://index.example/pypi/x/1/json" in body
    assert b"Connection refused" in body


def test_a_timeout_is_reported_not_raised(monkeypatch):
    def slow(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(pyrelease.urllib.request, "urlopen", slow)
    assert pyrelease.fetch("https://index.example/x")[0] == pyrelease.UNREACHABLE


def test_the_index_listing_distinguishes_unreachable_from_not_yet(monkeypatch):
    monkeypatch.setattr(pyrelease, "fetch", lambda url: (pyrelease.UNREACHABLE, b"cannot reach x"))
    with pytest.raises(pyrelease.Unreachable, match="cannot reach x"):
        pyrelease.published_files("https://pypi.org", "p", "1")


def test_an_index_that_never_answers_is_a_clear_failure_after_the_attempts(tmp_path, capsys):
    dist = make_dist(tmp_path)
    with pytest.raises(pyrelease.ReleaseError) as caught:
        pyrelease.verify_published(
            dist,
            index="http://127.0.0.1:9",  # nothing listens on the discard port: refused at once
            dependency_index="http://127.0.0.1:9/simple/",
            expect_provenance=False,
            attempts=2,
            delay=0,
            import_name=None,
            expect_py_typed=False,
            smoke_file=None,
        )
    assert "listing: still not there after 2 attempts: cannot reach" in str(caught.value)
    assert "attempt 1 of 2" in capsys.readouterr().out


def test_an_index_that_comes_back_is_waited_for(tmp_path, monkeypatch, capsys):
    dist = make_dist(tmp_path)
    dists = pyrelease.find_dists(dist)
    answers = [
        (pyrelease.UNREACHABLE, b"cannot reach the index: Connection reset"),
        (404, b""),
    ]
    monkeypatch.setattr(pyrelease, "fetch", lambda url: answers.pop(0) if answers else (404, b""))
    monkeypatch.setattr(pyrelease.time, "sleep", lambda seconds: None)
    with pytest.raises(pyrelease.ReleaseError):
        pyrelease.verify_published(
            dist,
            index="https://pypi.org",
            dependency_index="https://pypi.org/simple/",
            expect_provenance=False,
            attempts=3,
            delay=0,
            import_name=None,
            expect_py_typed=False,
            smoke_file=None,
        )
    out = capsys.readouterr().out
    assert "cannot reach the index: Connection reset (attempt 1 of 3)" in out
    assert f"lists no {dists.project} {dists.version} yet (attempt 2 of 3)" in out


# --- the run's summary page ----------------------------------------------------------------------


@pytest.fixture
def summary(tmp_path, monkeypatch):
    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    return path


def test_the_scripts_write_nothing_without_a_summary_file(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    for module in (guard, fingerprint, pyrelease):
        module.summarize("anything")  # no error, nowhere to write


def test_a_failed_check_is_on_the_summary_page_with_its_reason(tmp_path, summary):
    assert pyrelease.main(["verify-install", str(tmp_path / "nope")]) == 1
    text = summary.read_text(encoding="utf-8")
    assert "### ❌ verify-install failed" in text and "is not a directory" in text


def test_the_guard_reports_on_the_summary_page_both_ways(tmp_path, summary):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## [1.0.0] - 2026-01-01\n", encoding="utf-8")
    base = ["--prefix", "v", "--changelog", str(changelog)]
    assert guard.main(["--tag", "v1.0.0", "--version", "1.0.0", *base]) == 0
    assert guard.main(["--tag", "v1.0.1", "--version", "1.0.1", *base]) == 1
    text = summary.read_text(encoding="utf-8")
    assert "### ✅ Release guard" in text and "### ❌ Release guard" in text
    assert "no entry for 1.0.1" in text


def test_the_fingerprint_check_reports_on_the_summary_page_both_ways(tmp_path, summary):
    (tmp_path / "f").write_text("x", encoding="utf-8")
    good = fingerprint.digest(tmp_path)
    assert fingerprint.main(["check", str(tmp_path), good]) == 0
    assert fingerprint.main(["check", str(tmp_path), "sha256-" + "0" * 64]) == 1
    text = summary.read_text(encoding="utf-8")
    assert "### ✅ Fingerprint verified" in text and "### ❌ Fingerprint check failed" in text


def test_summarize_appends_separated_markdown(tmp_path, summary):
    pyrelease.summarize("### one", "", "- a")
    pyrelease.summarize("### two")
    assert summary.read_text(encoding="utf-8") == "### one\n\n- a\n\n### two\n\n"
