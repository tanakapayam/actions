"""lib/guard.py: is a GitHub Release ready to publish?"""

import datetime
from pathlib import Path

import guard
import pytest

CHANGELOG = """\
# Changelog

## [Unreleased]

## [1.2.0] - 2026-10-04

- the thing

## [1.1.0] - Unreleased

## [1.0.0]

## [0.9.0] - 2026-13-45
"""


@pytest.fixture
def changelog(tmp_path: Path) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")
    return path


def ready(changelog: Path, **overrides: object) -> str:
    arguments: dict[str, object] = {
        "tag": "python-v1.2.0",
        "prefix": "python-v",
        "version": "1.2.0",
        "changelog": changelog,
    }
    return guard.check(**{**arguments, **overrides})  # type: ignore[arg-type]


def test_a_dated_entry_for_the_tagged_version_passes(changelog):
    assert "python-v1.2.0 matches" in ready(changelog)


def test_an_entry_without_a_date_passes_unless_a_date_is_required(changelog):
    assert ready(changelog, tag="python-v1.0.0", version="1.0.0")
    with pytest.raises(guard.GuardError, match=r"must head 1\.0\.0 as"):
        ready(changelog, tag="python-v1.0.0", version="1.0.0", require_date=True)


def test_a_required_date_must_be_a_real_one(changelog):
    with pytest.raises(guard.GuardError, match="YYYY-MM-DD"):
        ready(changelog, tag="python-v0.9.0", version="0.9.0", require_date=True)
    assert ready(changelog, require_date=True)


def test_an_unreleased_entry_is_refused(changelog):
    with pytest.raises(guard.GuardError, match=r"still marks 1\.1\.0 as Unreleased"):
        ready(changelog, tag="python-v1.1.0", version="1.1.0")


@pytest.mark.parametrize("heading", ["## [2.0.0] - unreleased", "## [2.0.0] - UNRELEASED"])
def test_unreleased_is_recognized_in_any_case(tmp_path, heading):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(heading + "\n", encoding="utf-8")
    with pytest.raises(guard.GuardError, match="Unreleased"):
        ready(path, tag="python-v2.0.0", version="2.0.0")


def test_a_tag_that_is_not_the_prefix_and_the_version_is_refused(changelog):
    with pytest.raises(guard.GuardError, match=r"does not match the package version"):
        ready(changelog, tag="python-v1.2.1")
    with pytest.raises(guard.GuardError, match="does not match"):
        ready(changelog, tag="node-v1.2.0")  # another package's release


def test_a_missing_entry_is_refused(changelog):
    with pytest.raises(guard.GuardError, match=r"no entry for 3\.0\.0"):
        ready(changelog, tag="python-v3.0.0", version="3.0.0")


def test_a_version_is_matched_exactly_not_as_a_pattern(changelog):
    # "1.2.0" must not be satisfied by a heading for "1x2y0", or by a longer version.
    other = changelog.parent / "other.md"
    other.write_text("## [1x2y0] - 2026-01-01\n## [1.2.0.1] - 2026-01-01\n", encoding="utf-8")
    with pytest.raises(guard.GuardError, match=r"no entry for 1\.2\.0"):
        ready(other)


def test_no_tag_and_no_version_are_refused_with_their_own_messages(changelog):
    with pytest.raises(guard.GuardError, match="no release tag"):
        ready(changelog, tag="")
    with pytest.raises(guard.GuardError, match="No version was given"):
        ready(changelog, version="", tag="python-v")


def test_a_missing_changelog_is_refused(tmp_path):
    with pytest.raises(guard.GuardError, match="does not exist"):
        ready(tmp_path / "nope.md")


def test_the_command_line_annotates_a_failure_and_exits_1(changelog, capsys):
    status = guard.main(
        ["--tag", "python-v9.9.9", "--prefix", "python-v", "--version", "9.9.9",
         "--changelog", str(changelog)]
    )  # fmt: skip
    assert status == 1
    assert capsys.readouterr().err.startswith("::error::")
    assert guard.main(
        ["--tag", "python-v1.2.0", "--prefix", "python-v", "--version", "1.2.0",
         "--changelog", str(changelog), "--require-date"]
    ) == 0  # fmt: skip


def test_dates_in_the_fixture_are_what_the_tests_assume():
    assert datetime.date.fromisoformat("2026-10-04")
    with pytest.raises(ValueError, match="month"):
        datetime.date.fromisoformat("2026-13-45")
