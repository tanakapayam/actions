"""lib/pyrelease.py without installing or serving anything: names, contents, versions, retries."""

import io
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pyrelease
import pytest


def make_source(
    root: Path,
    import_name: str = "sample_pkg",
    layout: str = "src",
    files=("__init__.py", "app.py"),
) -> Path:
    package = root / "src" / import_name if layout == "src" else root / import_name
    package.mkdir(parents=True)
    for name in files:
        (package / name).write_text("", encoding="utf-8")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"\0")
    return root


def make_dist(
    root: Path,
    name: str = "sample_pkg",
    version: str = "1.0.0",
    *,
    layout: str = "src",
    wheel_files=("__init__.py", "app.py"),
    sdist_files=("__init__.py", "app.py"),
    sdist_name: str | None = None,
    wheel_version: str | None = None,
    with_sdist: bool = True,
) -> Path:
    dist = root / "dist"
    dist.mkdir(parents=True)
    wheel = dist / f"{name}-{wheel_version or version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for file in wheel_files:
            archive.writestr(f"{name}/{file}", f"wheel {file}")
        archive.writestr(f"{name}-{version}.dist-info/METADATA", "Name: x")
    if with_sdist:
        sdist = dist / f"{sdist_name or name}-{version}.tar.gz"
        base = f"src/{name}" if layout == "src" else name
        with tarfile.open(sdist, "w:gz") as archive:
            for file in [*sdist_files]:
                data = f"sdist {file}".encode()
                info = tarfile.TarInfo(f"{name}-{version}/{base}/{file}")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            info = tarfile.TarInfo(f"{name}-{version}/PKG-INFO")
            info.size = 0
            archive.addfile(info, io.BytesIO(b""))
    return dist


# --- names ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [("My_Package", "my-package"), ("a.b_c-d", "a-b-c-d"), ("x__y", "x-y"), ("plain", "plain")],
)
def test_names_are_normalized_the_way_an_index_spells_them(name, expected):
    assert pyrelease.normalize(name) == expected


def test_a_hyphenated_project_is_imported_with_underscores():
    assert pyrelease.import_name_for("sample_pkg") == "sample_pkg"
    assert pyrelease.import_name_for("Sample-Pkg") == "sample_pkg"


# --- finding the distributions -----------------------------------------------------------------


def test_the_wheel_and_the_sdist_give_the_name_and_version(tmp_path):
    dists = pyrelease.find_dists(make_dist(tmp_path, "sample_pkg", "1.2.3.dev10101"))
    assert (dists.name, dists.project, dists.version) == (
        "sample_pkg",
        "sample-pkg",
        "1.2.3.dev10101",
    )
    assert [path.name for path in dists.files] == [
        "sample_pkg-1.2.3.dev10101-py3-none-any.whl",
        "sample_pkg-1.2.3.dev10101.tar.gz",
    ]


def test_an_sdist_may_spell_the_name_with_hyphens(tmp_path):
    dist = make_dist(tmp_path, "sample_pkg", "1.0.0", sdist_name="sample-pkg")
    assert pyrelease.find_dists(dist).sdist.name == "sample-pkg-1.0.0.tar.gz"


def test_a_wheel_alone_is_enough(tmp_path):
    dists = pyrelease.find_dists(make_dist(tmp_path, with_sdist=False))
    assert dists.sdist is None
    assert len(dists.files) == 1


@pytest.mark.parametrize("problem", ["no wheel", "two wheels", "two sdists"])
def test_a_dist_directory_must_hold_one_wheel_and_at_most_one_sdist(tmp_path, problem):
    dist = make_dist(tmp_path)
    if problem == "no wheel":
        next(dist.glob("*.whl")).unlink()
    elif problem == "two wheels":
        (dist / "sample_pkg-1.0.0-py2-none-any.whl").write_bytes(b"")
    else:
        (dist / "other-1.0.0.tar.gz").write_bytes(b"")
    with pytest.raises(pyrelease.ReleaseError, match="exactly one wheel and at most one sdist"):
        pyrelease.find_dists(dist)


def test_the_wheel_and_the_sdist_must_agree(tmp_path):
    with pytest.raises(pyrelease.ReleaseError, match=r"wheel is 0\.9\.0 but the sdist is 1\.0\.0"):
        pyrelease.find_dists(make_dist(tmp_path / "a", wheel_version="0.9.0"))
    with pytest.raises(
        pyrelease.ReleaseError, match="wheel is for sample_pkg but the sdist is for"
    ):
        pyrelease.find_dists(make_dist(tmp_path / "b", sdist_name="other"))


def test_something_that_is_not_a_wheel_name_is_refused(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "nonsense.whl").write_bytes(b"")
    with pytest.raises(pyrelease.ReleaseError, match="not a wheel file name"):
        pyrelease.find_dists(dist)


# --- contents ----------------------------------------------------------------------------------


def test_the_package_is_found_in_a_src_layout_then_a_flat_one(tmp_path):
    assert (
        pyrelease.locate_package(make_source(tmp_path / "a"), "sample_pkg", None)
        == "src/sample_pkg"
    )
    assert (
        pyrelease.locate_package(make_source(tmp_path / "b", layout="flat"), "sample_pkg", None)
        == "sample_pkg"
    )
    assert (
        pyrelease.locate_package(make_source(tmp_path / "c"), "sample_pkg", "src/sample_pkg/")
        == "src/sample_pkg"
    )


def test_a_package_that_is_nowhere_is_an_error_that_says_where_it_looked(tmp_path):
    with pytest.raises(pyrelease.ReleaseError, match="tried src/sample_pkg, sample_pkg"):
        pyrelease.locate_package(tmp_path, "sample_pkg", None)
    with pytest.raises(pyrelease.ReleaseError, match="tried lib/x"):
        pyrelease.locate_package(tmp_path, "sample_pkg", "lib/x")


def test_source_files_skip_bytecode(tmp_path):
    source = make_source(tmp_path)
    assert pyrelease.source_files(source, "src/sample_pkg") == {"__init__.py", "app.py"}


@pytest.mark.parametrize("layout", ["src", "flat"])
def test_a_complete_build_has_no_problems(tmp_path, layout):
    source = make_source(tmp_path / "s", layout=layout)
    dists = pyrelease.find_dists(make_dist(tmp_path / "d", layout=layout))
    where = "src/sample_pkg" if layout == "src" else "sample_pkg"
    assert pyrelease.check_contents(dists, source, where) == []


def test_a_wheel_missing_a_module_is_caught(tmp_path):
    source = make_source(tmp_path / "s")
    dists = pyrelease.find_dists(make_dist(tmp_path / "d", wheel_files=("__init__.py",)))
    assert pyrelease.check_contents(dists, source, "src/sample_pkg") == [
        "the wheel is missing sample_pkg/app.py"
    ]


def test_an_sdist_missing_a_module_is_caught(tmp_path):
    source = make_source(tmp_path / "s")
    dists = pyrelease.find_dists(make_dist(tmp_path / "d", sdist_files=("app.py",)))
    assert pyrelease.check_contents(dists, source, "src/sample_pkg") == [
        "the sdist is missing sample_pkg/__init__.py"
    ]


def test_a_file_the_source_does_not_have_is_caught_unless_allowed(tmp_path):
    source = make_source(tmp_path / "s")
    dists = pyrelease.find_dists(
        make_dist(tmp_path / "d", wheel_files=("__init__.py", "app.py", "_version.py"))
    )
    assert pyrelease.check_contents(dists, source, "src/sample_pkg") == [
        "the wheel has sample_pkg/_version.py, which is not in the source tree"
    ]
    assert pyrelease.check_contents(dists, source, "src/sample_pkg", ["_version.py"]) == []
    assert pyrelease.check_contents(dists, source, "src/sample_pkg", ["_*.py"]) == []


def test_dist_info_is_not_mistaken_for_package_files(tmp_path):
    dist = make_dist(tmp_path)
    wheel = next(dist.glob("*.whl"))
    assert pyrelease.archive_files(wheel, "sample_pkg") == {"__init__.py", "app.py"}


def test_a_wheel_only_release_is_checked_without_an_sdist(tmp_path):
    source = make_source(tmp_path / "s")
    dists = pyrelease.find_dists(make_dist(tmp_path / "d", with_sdist=False))
    assert pyrelease.check_contents(dists, source, "src/sample_pkg") == []


# --- rehearsal versions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "attempt", "expected"),
    [(101, 1, "1.1.0.dev10101"), (101, 2, "1.1.0.dev10102"), (11, 2, "1.1.0.dev1102")],
)
def test_a_rehearsal_version_is_below_the_release_and_new_for_every_attempt(
    number, attempt, expected
):
    assert pyrelease.rehearsal_version("1.1.0", number, attempt) == expected


def test_rehearsal_versions_never_collide_across_runs_and_attempts():
    seen = {
        pyrelease.rehearsal_version("1.1.0", number, attempt)
        for number in range(1, 300)
        for attempt in range(1, 100)
    }
    assert len(seen) == 299 * 99


def test_a_rehearsal_version_sorts_below_the_real_one():
    packaging = pytest.importorskip("packaging.version")
    rehearsal = packaging.Version(pyrelease.rehearsal_version("1.1.0", 5, 1))
    assert packaging.Version("1.0.2") < rehearsal < packaging.Version("1.1.0")


@pytest.mark.parametrize(("base", "attempt"), [("1.1.0.dev1", 1), ("1.1.0", 0), ("1.1.0", 100)])
def test_a_rehearsal_version_refuses_what_it_cannot_make_unique(base, attempt):
    with pytest.raises(pyrelease.ReleaseError):
        pyrelease.rehearsal_version(base, 5, attempt)


def test_the_version_is_read_and_rewritten_in_place(tmp_path):
    file = tmp_path / "__init__.py"
    file.write_text('"""doc"""\n__version__ = "1.1.0"\nOTHER = "1.1.0"\n', encoding="utf-8")
    assert pyrelease.read_version(file) == "1.1.0"
    pyrelease.write_version(file, "1.1.0.dev10101")
    assert (
        file.read_text(encoding="utf-8")
        == '"""doc"""\n__version__ = "1.1.0.dev10101"\nOTHER = "1.1.0"\n'
    )


def test_a_pyproject_version_can_be_rewritten_with_a_pattern(tmp_path):
    file = tmp_path / "pyproject.toml"
    file.write_text('[project]\nname = "x"\nversion = "2.0.0"\n', encoding="utf-8")
    pattern = r'^version = "([^"]+)"$'
    assert pyrelease.read_version(file, pattern) == "2.0.0"
    pyrelease.write_version(file, "2.0.0.dev7", pattern)
    assert 'version = "2.0.0.dev7"' in file.read_text(encoding="utf-8")


def test_a_file_without_a_version_is_an_error(tmp_path):
    file = tmp_path / "x.py"
    file.write_text("nothing here\n", encoding="utf-8")
    with pytest.raises(pyrelease.ReleaseError, match="no line matching"):
        pyrelease.read_version(file)
    with pytest.raises(pyrelease.ReleaseError, match="no line matching"):
        pyrelease.write_version(file, "1.0.0")


# --- retrying and the index's answers ------------------------------------------------------------


def test_retrying_stops_at_the_first_success_and_waits_between_attempts(monkeypatch):
    outcomes = iter(["not yet", "still not", None])
    sleeps: list[float] = []
    monkeypatch.setattr(pyrelease.time, "sleep", sleeps.append)
    pyrelease.retrying("thing", lambda: next(outcomes), attempts=5, delay=7)
    assert sleeps == [7, 7]


def test_retrying_does_not_sleep_after_the_last_attempt(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(pyrelease.time, "sleep", sleeps.append)
    with pytest.raises(
        pyrelease.ReleaseError, match="thing: still not there after 2 attempts: nope"
    ):
        pyrelease.retrying("thing", lambda: "nope", attempts=2, delay=7)
    assert sleeps == [7]


def test_a_final_error_inside_an_attempt_is_not_retried(monkeypatch):
    calls = []

    def attempt():
        calls.append(1)
        raise pyrelease.ReleaseError("wrong bytes")

    monkeypatch.setattr(pyrelease.time, "sleep", lambda seconds: None)
    with pytest.raises(pyrelease.ReleaseError, match="wrong bytes"):
        pyrelease.retrying("thing", attempt, attempts=5, delay=0)
    assert len(calls) == 1


def test_published_files_maps_names_to_hashes_and_urls_and_none_means_not_yet(monkeypatch):
    body = {"urls": [{"filename": "a.whl", "digests": {"sha256": "aa"}, "url": "https://x/a.whl"}]}
    answers = iter([(404, b""), (200, json.dumps(body).encode())])
    monkeypatch.setattr(pyrelease, "fetch", lambda url: next(answers))
    assert pyrelease.published_files("https://pypi.org", "p", "1") is None
    assert pyrelease.published_files("https://pypi.org", "p", "1") == {
        "a.whl": {"sha256": "aa", "url": "https://x/a.whl"}
    }


def test_an_unexpected_status_from_the_index_is_an_error_not_a_retry(monkeypatch):
    monkeypatch.setattr(pyrelease, "fetch", lambda url: (503, b""))
    with pytest.raises(pyrelease.ReleaseError, match="answered 503"):
        pyrelease.published_files("https://pypi.org", "p", "1")


def test_the_json_url_uses_the_normalized_project_and_the_version(monkeypatch):
    seen = []
    monkeypatch.setattr(pyrelease, "fetch", lambda url: (seen.append(url), (404, b""))[1])
    pyrelease.published_files("https://test.pypi.org", "sample-pkg", "1.1.0.dev10101")
    assert seen == ["https://test.pypi.org/pypi/sample-pkg/1.1.0.dev10101/json"]


# --- the command line ----------------------------------------------------------------------------


def test_rehearsal_version_on_the_command_line_can_write_it(tmp_path, capsys):
    file = tmp_path / "__init__.py"
    file.write_text('__version__ = "1.1.0"\n', encoding="utf-8")
    argv = ["rehearsal-version", "--file", str(file), "--run-number", "7", "--run-attempt", "1"]
    assert pyrelease.main(argv) == 0
    assert capsys.readouterr().out.strip() == "1.1.0.dev701"
    assert pyrelease.read_version(file) == "1.1.0"  # printed, not written
    assert pyrelease.main([*argv, "--write"]) == 0
    assert pyrelease.read_version(file) == "1.1.0.dev701"


def test_a_failed_check_is_exit_status_1_with_a_github_annotation(tmp_path, capsys):
    assert pyrelease.main(["verify-install", str(tmp_path)]) == 1
    assert capsys.readouterr().err.startswith("::error::")


# --- virtual environments ----------------------------------------------------------------------


def test_a_venv_links_the_interpreter_like_python_dash_m_venv_does(tmp_path, monkeypatch):
    # `venv.EnvBuilder` copies by default, which breaks relocatable Pythons (uv's, on macOS):
    # a copied interpreter cannot find its libpython, and ensurepip fails inside the new venv.
    seen: dict[str, object] = {}

    class Recorder:
        def __init__(self, **options: object) -> None:
            seen.update(options)

        def create(self, target: Path) -> None:
            pass

    monkeypatch.setattr(pyrelease.venv, "EnvBuilder", Recorder)
    pyrelease.make_venv(tmp_path, "environment")
    assert seen == {"with_pip": True, "clear": True, "symlinks": os.name != "nt"}


def test_a_venv_that_cannot_be_made_says_why_instead_of_a_bare_traceback(tmp_path, monkeypatch):
    def fail(self: object, target: Path) -> None:
        raise subprocess.CalledProcessError(
            1,
            ["python", "-m", "ensurepip"],
            output=b"dyld: Library not loaded: libpython3.13.dylib\n",
        )

    monkeypatch.setattr(pyrelease.venv.EnvBuilder, "create", fail)
    with pytest.raises(
        pyrelease.ReleaseError, match=r"cannot create a virtual environment"
    ) as caught:
        pyrelease.make_venv(tmp_path, "environment")
    assert "dyld: Library not loaded" in str(caught.value)
