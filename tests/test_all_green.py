"""lib/all_green.py: the one check to require."""

import json

import all_green
import pytest


def needs(**results: str) -> str:
    return json.dumps({name: {"result": result, "outputs": {}} for name, result in results.items()})


def test_every_job_succeeding_passes_and_names_the_jobs():
    confirmation, results = all_green.check(needs(test="success", lint="success"))
    assert confirmation == "all 2 job(s) succeeded: test, lint"
    assert results == {"test": "success", "lint": "success"}


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "something-new"])
def test_anything_but_success_fails_by_default(result):
    with pytest.raises(all_green.GateError, match=f"not every job succeeded: lint {result}"):
        all_green.check(needs(test="success", lint=result))


def test_every_job_that_is_not_green_is_named_in_the_one_line_message():
    with pytest.raises(all_green.GateError) as caught:
        all_green.check(needs(a="failure", b="success", c="cancelled", d="skipped"))
    assert str(caught.value) == "not every job succeeded: a failure, c cancelled, d skipped"
    assert "\n" not in str(caught.value)


def test_a_skipped_job_passes_only_when_it_is_allowed():
    assert all_green.check(needs(test="success", deploy="skipped"), ["deploy"])
    with pytest.raises(all_green.GateError, match="deploy skipped"):
        all_green.check(needs(test="success", deploy="skipped"), ["test"])  # a different job


def test_allowing_a_skip_does_not_allow_a_failure():
    with pytest.raises(all_green.GateError, match="deploy failure"):
        all_green.check(needs(deploy="failure"), ["deploy"])


def test_an_allowed_name_that_is_not_a_job_is_a_typo_not_a_pass():
    with pytest.raises(all_green.GateError, match=r"allow-skipped names depoly, which is not one"):
        all_green.check(needs(deploy="skipped"), ["depoly"])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "needs is not JSON"),
        ("{not json", "needs is not JSON"),
        ("[]", "needs must be the JSON of the needs context"),
        ('"success"', "needs must be the JSON of the needs context"),
        ('{"a": "success"}', "needs must be the JSON of the needs context"),
        ('{"a": {"outputs": {}}}', "needs must be the JSON of the needs context"),
        ('{"a": {"result": true}}', "needs must be the JSON of the needs context"),
        ("{}", "needs is empty"),
    ],
)
def test_a_gate_that_is_set_up_wrongly_fails_rather_than_passing(text, message):
    # An empty `needs` would pass a naive check forever: the job would be waiting for nothing.
    with pytest.raises(all_green.GateError, match=message):
        all_green.check(text)


def test_the_command_line_passes_and_fails_with_an_annotation(capsys):
    assert all_green.main(["--needs", needs(a="success")]) == 0
    assert capsys.readouterr().out.startswith("all 1 job(s) succeeded")
    assert all_green.main(["--needs", needs(a="failure")]) == 1
    assert capsys.readouterr().err.startswith("::error::not every job succeeded: a failure")


def test_the_command_line_takes_allow_skipped_more_than_once(capsys):
    argv = ["--needs", needs(a="skipped", b="skipped", c="success")]
    assert all_green.main([*argv, "--allow-skipped", "a", "--allow-skipped", "b"]) == 0
    assert all_green.main([*argv, "--allow-skipped", "a"]) == 1


def test_the_summary_page_shows_each_job_whether_it_passed_or_not(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert all_green.main(["--needs", needs(test="success", lint="success")]) == 0
    text = summary.read_text(encoding="utf-8")
    assert "### ✅ CI passed" in text and "| `test` | success |" in text
    assert all_green.main(["--needs", needs(test="success", lint="failure")]) == 1
    text = summary.read_text(encoding="utf-8")
    assert "### ❌ CI did not pass" in text and "| `lint` | failure |" in text


def test_a_wrongly_set_up_gate_says_so_on_the_summary_page(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert all_green.main(["--needs", "{}"]) == 1
    assert "### ❌ CI gate is set up wrongly" in summary.read_text(encoding="utf-8")
    assert "needs is empty" in capsys.readouterr().err
