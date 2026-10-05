"""lib/pyrelease.py on a real built package, and against a package index on localhost.

``verify-install`` installs the fixture package's wheel and sdist into fresh virtual
environments (the sdist needs a build backend, so that part reaches PyPI for hatchling).
``verify-published`` is exercised against ``fakeindex.FakeIndex``, which speaks the same
protocols as PyPI and can misbehave on purpose, so every way the check refuses is real.
"""

import os
import shutil
import zipfile
from pathlib import Path

import pyrelease
import pytest
from fakeindex import FakeIndex

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def install(dist: Path, root: Path, **overrides: object) -> None:
    options: dict[str, object] = {
        "package_dir": None,
        "import_name": None,
        "allow_extra": [],
        "expect_py_typed": True,
        "smoke_file": None,
        "dependency_index": "https://pypi.org/simple/",
    }
    pyrelease.verify_install(dist, root, **{**options, **overrides})  # type: ignore[arg-type]


def published(dist: Path, index: FakeIndex, **overrides: object) -> None:
    options: dict[str, object] = {
        "index": index.url,
        "dependency_index": f"{index.url}/simple/",
        "expect_provenance": False,
        "attempts": 4,
        "delay": 0,
        "import_name": None,
        "expect_py_typed": True,
        "smoke_file": None,
    }
    pyrelease.verify_published(dist, **{**options, **overrides})  # type: ignore[arg-type]


def refused(dist: Path, match: str, *, index: dict[str, object] | None = None, **overrides: object):
    """Serve ``dist`` (misbehaving as ``index`` says), read it back, and expect a refusal."""
    with FakeIndex(dist, **(index or {})) as served:  # type: ignore[arg-type]
        with pytest.raises(pyrelease.ReleaseError, match=match):
            published(dist, served, **overrides)
        return served


def drop_from_wheel(dist: Path, member: str) -> None:
    wheel = next(dist.glob("*.whl"))
    rewritten = wheel.with_suffix(".new")
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(rewritten, "w") as target:
        for item in source.infolist():
            if item.filename != member:
                target.writestr(item, source.read(item.filename))
    shutil.move(rewritten, wheel)


@pytest.mark.skipif(os.name == "nt", reason="Windows environments copy their interpreter")
def test_a_real_venv_holds_a_symlink_to_the_interpreter(tmp_path):
    python = pyrelease.make_venv(tmp_path, "environment")
    assert python.is_symlink()
    assert pyrelease.run([python, "-c", "import pip"]).returncode == 0


# --- the built fixture ---------------------------------------------------------------------------


def test_the_fixture_builds_with_an_underscored_wheel_and_sdist(built):
    names = sorted(path.name for path in (built / "dist").iterdir())
    assert names == ["sample_pkg-0.3.0-py3-none-any.whl", "sample_pkg-0.3.0.tar.gz"]


# --- verify-install ------------------------------------------------------------------------------


def test_a_good_build_installs_and_passes_the_smoke_test(built, capsys):
    install(built / "dist", built)
    out = capsys.readouterr().out
    assert "contents: the wheel and the sdist hold all of src/sample_pkg" in out
    assert out.count("sample-pkg 0.3.0") == 2 or out.count("sample_pkg 0.3.0") == 2
    assert "wheel:" in out and "sdist:" in out


def test_a_caller_smoke_test_runs_in_each_install(built, capsys):
    install(built / "dist", built, smoke_file=FIXTURES / "smoke_greets.py")
    assert capsys.readouterr().out.count("greet works") == 2


def test_a_failing_caller_smoke_test_fails_the_stage(built):
    with pytest.raises(pyrelease.ReleaseError, match=r"smoke_fails\.py failed on the installed"):
        install(built / "dist", built, smoke_file=FIXTURES / "smoke_fails.py")


def test_a_wheel_without_a_module_never_reaches_an_install(built, dist):
    drop_from_wheel(dist, "sample_pkg/extras.py")
    with pytest.raises(pyrelease.ReleaseError, match=r"the wheel is missing sample_pkg/extras\.py"):
        install(dist, built)


def test_py_typed_can_be_required_or_not(built, dist):
    drop_from_wheel(dist, "sample_pkg/py.typed")
    with pytest.raises(pyrelease.ReleaseError, match=r"the wheel is missing sample_pkg/py\.typed"):
        install(dist, built)  # the source tree has it, so the contents check is first to say so
    # ...and a build that is *meant* to differ is accepted when the difference is declared.
    shutil.copy(built / "dist" / "sample_pkg-0.3.0-py3-none-any.whl", dist)
    install(dist, built, expect_py_typed=False)


def test_a_wrong_import_name_fails_the_smoke_test_not_the_contents_check(built):
    with pytest.raises(pyrelease.ReleaseError, match="No module named 'not_this'"):
        install(built / "dist", built, import_name="not_this", package_dir="src/sample_pkg")


# --- verify-published ----------------------------------------------------------------------------


def test_a_release_the_index_serves_faithfully_passes(dist, capsys):
    with FakeIndex(dist) as index:
        published(dist, index)
    out = capsys.readouterr().out
    assert "listing:" in out and "download:" in out and "install:" in out
    assert any(path.endswith("sample-pkg/") for path in index.requests)  # pip resolved it


def test_a_release_that_takes_a_while_to_appear_is_waited_for(dist, capsys):
    with FakeIndex(dist, lag=2) as index:
        published(dist, index, attempts=5)
    assert "lists no sample-pkg 0.3.0 yet (attempt 2 of 5)" in capsys.readouterr().out


def test_a_release_that_never_appears_is_an_error_naming_what_is_missing(dist):
    refused(dist, r"listing: still not there after 3 attempts", index={"lag": 99}, attempts=3)


def test_a_file_the_index_has_not_listed_is_waited_for_then_refused(dist):
    refused(
        dist,
        r"sample_pkg-0\.3\.0\.tar\.gz is not listed yet",
        index={"unlisted": ["sample_pkg-0.3.0.tar.gz"]},
        attempts=2,
    )


def test_a_listed_hash_that_is_not_what_was_built_is_refused_at_once(dist):
    served = refused(
        dist,
        r"is not the file that was built",
        index={"wrong_listed_hash": ["sample_pkg-0.3.0-py3-none-any.whl"]},
        attempts=5,
    )
    assert sum(path.endswith("/json") for path in served.requests) == 1  # no retry on a mismatch


def test_bytes_that_differ_from_what_the_index_lists_are_refused(dist):
    refused(
        dist,
        r"users download is not the one built",
        index={"tampered_bytes": ["sample_pkg-0.3.0.tar.gz"]},
    )


def test_a_failing_caller_smoke_test_fails_the_read_back(dist):
    refused(dist, r"smoke_fails\.py failed", smoke_file=FIXTURES / "smoke_fails.py")


def test_provenance_is_only_checked_when_asked(dist):
    with FakeIndex(dist, provenance="missing") as index:
        published(dist, index)  # not asked: fine
    refused(
        dist,
        r"no attestation for .* yet",
        index={"provenance": "missing"},
        expect_provenance=True,
        attempts=2,
    )


def test_provenance_that_is_present_passes_and_an_empty_record_does_not(dist, capsys):
    with FakeIndex(dist, provenance="ok") as index:
        published(dist, index, expect_provenance=True)
    assert "provenance: every file is attested" in capsys.readouterr().out
    refused(
        dist,
        r"has an empty provenance record",
        index={"provenance": "empty"},
        expect_provenance=True,
    )


def test_the_command_line_reads_a_release_back(dist, capsys):
    with FakeIndex(dist) as index:
        status = pyrelease.main(
            ["verify-published", str(dist), "--index", index.url + "/", "--attempts", "2",
             "--delay", "0", "--dependency-index", f"{index.url}/simple/", "--expect-py-typed"]
        )  # fmt: skip
    assert status == 0
    assert "install:" in capsys.readouterr().out


def test_a_real_stage_and_a_real_read_back_leave_a_summary(built, dist, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    install(dist, built)
    with FakeIndex(dist) as index:
        published(dist, index, expect_provenance=True)
    text = summary.read_text(encoding="utf-8")
    assert "### Stage: sample-pkg 0.3.0 on Python " in text
    assert "- ✅ The wheel and the sdist hold all of `src/sample_pkg`" in text
    assert "- ✅ the wheel installs, and its smoke tests pass" in text
    assert "### Read back from http://127.0.0.1:" in text
    assert "- ✅ provenance: every file is attested" in text
