"""lib/supported_versions.py: the Python versions a package claims, as a test matrix."""

from pathlib import Path

import pytest
import supported_versions as sv


def pyproject(tmp_path: Path, classifiers=(), requires: str | None = None, extra: str = "") -> Path:
    lines = ["[project]", 'name = "x"']
    if requires is not None:
        lines.append(f'requires-python = "{requires}"')
    shown = ", ".join(f'"Programming Language :: Python :: {c}"' for c in classifiers)
    lines.append(f"classifiers = [{shown}]")
    path = tmp_path / "pyproject.toml"
    path.write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
    return path


def write(tmp: Path, name: str, text: str) -> Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_classifiers_become_the_versions_oldest_first(tmp_path):
    versions, notes = sv.supported(pyproject(tmp_path, ["3.13", "3.11", "3.12"], ">=3.11"))
    assert versions == ["3.11", "3.12", "3.13"] and notes == []


def test_versions_sort_by_number_not_by_text(tmp_path):
    versions, _ = sv.supported(pyproject(tmp_path, ["3.9", "3.10", "3.11"], ">=3.9"))
    assert versions == ["3.9", "3.10", "3.11"]


def test_other_classifiers_are_ignored(tmp_path):
    path = pyproject(tmp_path, ["3", "3 :: Only", "3.12", "Implementation :: CPython"], ">=3.12")
    assert sv.supported(path)[0] == ["3.12"]


def test_duplicates_collapse(tmp_path):
    assert sv.supported(pyproject(tmp_path, ["3.12", "3.12"], ">=3.12"))[0] == ["3.12"]


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda tmp: tmp / "nope.toml", "does not exist"),
        (lambda tmp: write(tmp, "bad.toml", "[project\n"), "not valid TOML"),
        (lambda tmp: write(tmp, "t.toml", "[tool.x]\na = 1\n"), r"has no \[project\] table"),
        (lambda tmp: pyproject(tmp, []), "lists no 'Programming Language :: Python :: 3.x'"),
    ],
)
def test_a_file_that_cannot_give_a_matrix_says_why(tmp_path, make, message):
    with pytest.raises(sv.VersionsError, match=message):
        sv.supported(make(tmp_path))


def test_a_classifier_outside_requires_python_is_an_error(tmp_path):
    with pytest.raises(
        sv.VersionsError, match=r"classifier Python 3\.10 is outside requires-python '>=3\.11'"
    ):
        sv.supported(pyproject(tmp_path, ["3.10", "3.11"], ">=3.11"))


def test_requires_python_admitting_an_untested_version_is_an_error(tmp_path):
    with pytest.raises(sv.VersionsError) as caught:
        sv.supported(pyproject(tmp_path, ["3.11", "3.12"], ">=3.9"))
    assert "admits Python 3.9, 3.10, which no classifier lists" in str(caught.value)


def test_an_upper_bound_is_honoured(tmp_path):
    assert sv.supported(pyproject(tmp_path, ["3.11", "3.12"], ">=3.11,<3.13"))[0] == [
        "3.11",
        "3.12",
    ]
    with pytest.raises(sv.VersionsError, match="outside requires-python"):
        sv.supported(pyproject(tmp_path, ["3.11", "3.12", "3.13"], ">=3.11,<3.13"))


@pytest.mark.parametrize(
    ("spec", "version", "expected"),
    [
        (">=3.11", "3.11", True), (">=3.11", "3.10", False), (">3.11", "3.11", False),
        ("<4", "3.99", True), ("<=3.12", "3.12", True), ("<=3.12", "3.13", False),
        ("==3.12", "3.12", True), ("==3.12", "3.11", False), ("==3.*", "3.9", True),
        ("!=3.12", "3.12", False), ("!=3.12.*", "3.12", False), ("!=3.12.*", "3.13", True),
        (">=3.11, <3.14", "3.13", True), (">=3.11.2", "3.11", True),
    ],
)  # fmt: skip
def test_requires_python_specifiers_are_read_by_major_and_minor(spec, version, expected):
    assert sv.allows(sv.parse_specifiers(spec), version) is expected


@pytest.mark.parametrize("spec", ["~=3.11", ">=3.11 || <3", "python>=3", ">=", ""])
def test_a_specifier_that_is_not_simple_is_a_warning_not_a_guess(tmp_path, spec):
    versions, notes = sv.supported(pyproject(tmp_path, ["3.12"], spec))
    assert versions == ["3.12"]
    assert len(notes) == 1 and "was not understood" in notes[0]


def test_no_requires_python_means_nothing_to_check(tmp_path):
    assert sv.supported(pyproject(tmp_path, ["3.11", "3.12"], None)) == (["3.11", "3.12"], [])


def test_the_check_can_be_turned_off(tmp_path):
    path = pyproject(tmp_path, ["3.10", "3.11"], ">=3.11")
    assert sv.supported(path, check_requires=False)[0] == ["3.10", "3.11"]


def test_the_command_line_prints_matrix_oldest_and_latest(tmp_path, capsys):
    path = pyproject(tmp_path, ["3.11", "3.12", "3.13"], ">=3.11")
    assert sv.main([str(path)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        'matrix=["3.11","3.12","3.13"]',
        "oldest=3.11",
        "latest=3.13",
    ]


def test_the_command_line_fails_with_an_annotation_and_prints_no_outputs(tmp_path, capsys):
    path = pyproject(tmp_path, ["3.10", "3.11"], ">=3.11")
    assert sv.main([str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("::error::classifier Python 3.10")


def test_a_note_is_a_github_warning_and_does_not_fail(tmp_path, capsys):
    path = pyproject(tmp_path, ["3.12"], "~=3.12")
    assert sv.main([str(path)]) == 0
    assert "::warning::requires-python '~=3.12' was not understood" in capsys.readouterr().err


def test_the_summary_page_lists_the_versions_or_the_reason_for_failing(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    good = pyproject(tmp_path, ["3.11", "3.12"], ">=3.11")
    assert sv.main([str(good)]) == 0
    assert "3.11, 3.12 (from the classifiers; oldest 3.11, latest 3.12)" in summary.read_text()
    bad = tmp_path / "other"
    bad.mkdir()
    assert sv.main([str(pyproject(bad, ["3.9", "3.11"], ">=3.11"))]) == 1
    assert "### ❌ Supported Python versions" in summary.read_text()


def test_the_real_pyproject_of_a_package_works(tmp_path):
    real = Path(__file__).resolve().parent / "fixtures" / "sample-pkg" / "pyproject.toml"
    versions, notes = sv.supported(real)
    assert versions == ["3.11", "3.12", "3.13"] and notes == []
