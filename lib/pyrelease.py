#!/usr/bin/env python3
"""Release checks for a pure-Python package's built distributions (standard library only).

    pyrelease.py verify-install DIST        the wheel and sdist hold the whole package, and
                                            install and run from fresh virtual environments
    pyrelease.py rehearsal-version ...      the throwaway version a rehearsal builds under
    pyrelease.py verify-published DIST      after an upload: wait for the index to list the
                                            files, compare its hashes with DIST's, download
                                            them again, and install the package back from it

DIST is the directory a build left: exactly one wheel and at most one sdist. These are the
checks that stand in for a "staging registry" on ecosystems that do not have one (PyPI does
not): they run on the exact files that will be uploaded, and then on what the index serves.

Scope: pure-Python packages with a single universal wheel. Packages with extension modules
or several platform wheels need a different install check.
"""

import argparse
import fnmatch
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import venv
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_INDEX = "https://pypi.org"
DEFAULT_VERSION_PATTERN = r'^__version__ = "([^"]+)"$'

# What every install is checked with, inside the fresh environment, run with `-I` (isolated:
# no PYTHON* variables and no current directory on sys.path) so it can only be looking at what
# pip installed there. argv: distribution name, import name, expected version, py.typed?
DEFAULT_SMOKE = """
import importlib
import importlib.metadata
import pathlib
import sys

dist_name, import_name, expected, expect_typed = sys.argv[1:5]
installed = importlib.metadata.version(dist_name)
assert installed == expected, f"installed version is {installed}, expected {expected}"
module = importlib.import_module(import_name)
locations = list(getattr(module, "__path__", [])) or [str(pathlib.Path(module.__file__).parent)]
here = pathlib.Path(locations[0]).resolve()
assert "site-packages" in here.parts, f"{import_name} was imported from {here}, not the install"
if expect_typed == "true":
    assert (here / "py.typed").exists(), "py.typed is missing"
print(f"{dist_name} {installed} from {here}: ok")
"""


class ReleaseError(Exception):
    """A check failed; the message says what to look at."""


class Unreachable(Exception):
    """The index could not be reached at all; the caller treats it as "not yet"."""


def summarize(*lines: str) -> None:
    """Append Markdown to the job summary on GitHub (``$GITHUB_STEP_SUMMARY``); otherwise a no-op.
    The run's page then says what was checked and why it failed without opening the log."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n\n")


def normalize(name: str) -> str:
    """PEP 503: the one spelling an index knows a project by."""
    return re.sub(r"[-_.]+", "-", name).lower()


# --- the distributions ----------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Dists:
    wheel: Path
    sdist: Path | None
    name: str  # as the wheel spells it (underscores)
    version: str

    @property
    def project(self) -> str:
        return normalize(self.name)

    @property
    def files(self) -> list[Path]:
        return [self.wheel] if self.sdist is None else [self.wheel, self.sdist]

    def digests(self) -> dict[str, str]:
        return {path.name: sha256_file(path) for path in self.files}


def find_dists(dist: Path) -> Dists:
    """The wheel and the sdist a build left in ``dist``, which must agree on name and version."""
    if not dist.is_dir():
        raise ReleaseError(f"{dist} is not a directory: dist is where the build left its files.")
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) > 1:
        found = [path.name for path in (*wheels, *sdists)] or "nothing"
        raise ReleaseError(
            f"{dist} should hold exactly one wheel and at most one sdist, found {found}"
        )
    parts = wheels[0].name.split("-")
    if len(parts) < 5:
        raise ReleaseError(f"{wheels[0].name} is not a wheel file name")
    name, version = parts[0], parts[1]
    sdist = sdists[0] if sdists else None
    if sdist is not None:
        sdist_name, _, sdist_version = sdist.name.removesuffix(".tar.gz").rpartition("-")
        if normalize(sdist_name) != normalize(name):
            raise ReleaseError(f"the wheel is for {name} but the sdist is for {sdist_name}")
        if sdist_version != version:
            raise ReleaseError(f"the wheel is {version} but the sdist is {sdist_version}")
    return Dists(wheel=wheels[0], sdist=sdist, name=name, version=version)


# --- contents -------------------------------------------------------------------------------


def import_name_for(name: str) -> str:
    return normalize(name).replace("-", "_")


def locate_package(source_root: Path, import_name: str, package_dir: str | None) -> str:
    """The package directory relative to ``source_root``: given, ``src/<name>`` or ``<name>``."""
    candidates = [package_dir] if package_dir else [f"src/{import_name}", import_name]
    for candidate in candidates:
        if candidate and (source_root / candidate).is_dir():
            return candidate.strip("/")
    raise ReleaseError(
        f"cannot find the package under {source_root.resolve()}: tried "
        f"{', '.join(map(str, candidates))}. Is source-root the project root (where "
        "pyproject.toml is)? If the package is somewhere else, say where with package-dir."
    )


def source_files(source_root: Path, package_dir: str) -> set[str]:
    """Every file of the package in the source tree, relative to the package directory."""
    package = source_root / package_dir
    return {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def archive_files(path: Path, root: str) -> set[str]:
    """The package's files inside a wheel (``root`` is the import name) or an sdist."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    else:
        with tarfile.open(path) as archive:
            names = [name.split("/", 1)[1] for name in archive.getnames() if "/" in name]
    prefix = root.strip("/") + "/"
    return {
        name[len(prefix) :] for name in names if name.startswith(prefix) and not name.endswith("/")
    }


def check_contents(
    dists: Dists,
    source_root: Path,
    package_dir: str,
    allow_extra: Sequence[str] = (),
) -> list[str]:
    """Problems with what the wheel and the sdist hold, compared with the source tree.

    The case this exists for is a build that leaves out a module that is new in the source:
    it imports fine from a checkout and breaks for everyone else. ``allow_extra`` names files
    a build adds on purpose (a generated ``_version.py``, say), as globs relative to the
    package directory."""
    wanted = source_files(source_root, package_dir)
    archives = [("wheel", dists.wheel, Path(package_dir).name)]
    if dists.sdist is not None:
        archives.append(("sdist", dists.sdist, package_dir))
    problems = []
    for kind, path, root in archives:
        have = archive_files(path, root)
        label = Path(package_dir).name
        for name in sorted(wanted - have):
            problems.append(f"the {kind} is missing {label}/{name}")
        for name in sorted(have - wanted):
            if not any(fnmatch.fnmatch(name, pattern) for pattern in allow_extra):
                problems.append(f"the {kind} has {label}/{name}, which is not in the source tree")
    return problems


# --- virtual environments -------------------------------------------------------------------


def run(command: Sequence[str | Path], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        check=False,
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def make_venv(parent: Path, name: str) -> Path:
    """A fresh environment with pip; returns its interpreter.

    The interpreter is *symlinked* into the environment off Windows, which is what
    ``python -m venv`` does but ``venv.EnvBuilder`` does not (its default is to copy). A copied
    interpreter cannot find the libpython it was built to load when the Python is relocatable
    (uv's managed Pythons, python-build-standalone), and the environment's own ``ensurepip`` then
    fails: first seen on macOS (https://github.com/python/cpython/issues/129382).
    """
    target = parent / name
    builder = venv.EnvBuilder(with_pip=True, clear=True, symlinks=os.name != "nt")
    try:
        builder.create(target)
    except subprocess.CalledProcessError as error:
        output = error.output
        shown = output.decode(errors="replace") if isinstance(output, bytes) else str(output or "")
        raise ReleaseError(
            f"cannot create a virtual environment with {sys.executable}:\n{shown.strip()}"
        ) from error
    return target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def pip(python: Path, *arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return run([python, "-m", "pip", "--disable-pip-version-check", *arguments])


def last_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[-1] if lines else "pip failed"


def smoke(
    python: Path,
    dists: Dists,
    scratch: Path,
    *,
    import_name: str,
    expect_py_typed: bool,
    smoke_file: Path | None,
) -> str:
    """Run the default smoke test, then the caller's, in the environment ``python`` belongs to."""
    arguments = [dists.name, import_name, dists.version]
    result = run(
        [python, "-I", "-c", DEFAULT_SMOKE, *arguments, str(expect_py_typed).lower()],
        cwd=scratch,
    )
    if result.returncode != 0:
        raise ReleaseError(f"the installed package failed its smoke test:\n{result.stderr.strip()}")
    report = result.stdout.strip()
    if smoke_file is not None:
        result = run([python, "-I", smoke_file.resolve(), *arguments], cwd=scratch)
        if result.returncode != 0:
            raise ReleaseError(f"{smoke_file} failed on the installed package:\n{result.stderr}")
        report += "\n" + result.stdout.strip() if result.stdout.strip() else ""
    return report


def verify_install(
    dist: Path,
    source_root: Path,
    *,
    package_dir: str | None,
    import_name: str | None,
    allow_extra: Sequence[str],
    expect_py_typed: bool,
    smoke_file: Path | None,
    dependency_index: str,
) -> None:
    dists = find_dists(dist)
    name = import_name or import_name_for(dists.name)
    where = locate_package(source_root, name, package_dir)
    problems = check_contents(dists, source_root, where, allow_extra)
    if problems:
        raise ReleaseError("the distributions do not hold the package:\n  " + "\n  ".join(problems))
    holders = "the wheel and the sdist" if dists.sdist is not None else "the wheel"
    print(f"contents: {holders} hold all of {where}")
    passed = [f"{holders[0].upper()}{holders[1:]} hold all of `{where}`"]

    with tempfile.TemporaryDirectory(prefix="release-check-") as scratch_name:
        scratch = Path(scratch_name)
        targets = [("wheel", dists.wheel)]
        if dists.sdist is not None:
            targets.append(("sdist", dists.sdist))
        for kind, path in targets:
            # Installed from the file itself: the index is only ever asked for dependencies
            # (and, for an sdist, for the build backend).
            python = make_venv(scratch, f"venv-{kind}")
            installed = pip(
                python,
                "install",
                "--no-cache-dir",
                "--index-url",
                dependency_index,
                path,
            )
            if installed.returncode != 0:
                raise ReleaseError(f"pip could not install the {kind}:\n{installed.stderr.strip()}")
            report = smoke(
                python,
                dists,
                scratch,
                import_name=name,
                expect_py_typed=expect_py_typed,
                smoke_file=smoke_file,
            )
            print(f"{kind}: {report}")
            passed.append(f"the {kind} installs, and its smoke tests pass")
    summarize(
        f"### Stage: {dists.project} {dists.version} on Python {platform.python_version()}",
        "",
        *[f"- ✅ {line}" for line in passed],
    )


# --- rehearsal versions ---------------------------------------------------------------------


def read_version(file: Path, pattern: str = DEFAULT_VERSION_PATTERN) -> str:
    match = re.compile(pattern, re.MULTILINE).search(file.read_text(encoding="utf-8"))
    if not match:
        raise ReleaseError(f"{file} has no line matching {pattern!r}")
    return match.group(1)


def rehearsal_version(base: str, run_number: int, run_attempt: int) -> str:
    """``1.1.0`` -> ``1.1.0.dev10001``: below the real release, so it never stands in for it,
    and different for every run and every re-run, so an index that refuses to take a file
    twice (TestPyPI never does, even after a delete) is never asked to."""
    if ".dev" in base:
        raise ReleaseError(f"{base} is already a development version")
    if not 1 <= run_attempt <= 99:
        raise ReleaseError(f"run attempt {run_attempt} is outside 1..99")
    return f"{base}.dev{run_number * 100 + run_attempt}"


def write_version(file: Path, version: str, pattern: str = DEFAULT_VERSION_PATTERN) -> None:
    text = file.read_text(encoding="utf-8")
    match = re.compile(pattern, re.MULTILINE).search(text)
    if not match:
        raise ReleaseError(f"{file} has no line matching {pattern!r}")
    file.write_text(text[: match.start(1)] + version + text[match.end(1) :], encoding="utf-8")


# --- after the upload -----------------------------------------------------------------------


UNREACHABLE = 0  # what fetch() reports when there was no HTTP answer at all


def fetch(url: str) -> tuple[int, bytes]:
    """``(status, body)``. A connection that fails (DNS, refused, reset, timed out) is
    ``(UNREACHABLE, <the reason>)``: the index being briefly out of reach after an upload is a
    reason to wait and look again, not to crash."""
    request = urllib.request.Request(url, headers={"User-Agent": "tanakapayam-actions"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except (urllib.error.URLError, OSError) as error:
        reason = getattr(error, "reason", error)
        return UNREACHABLE, f"cannot reach {url}: {reason}".encode()


def retrying(
    description: str, attempt: Callable[[], str | None], attempts: int, delay: float
) -> None:
    """Call ``attempt`` until it returns ``None`` (done). A string is "not yet, because ...":
    a fresh upload takes a while to show up on the index and its CDN, so that is retried;
    a ``ReleaseError`` raised from inside is final."""
    reason = "not tried"
    for number in range(1, attempts + 1):
        outcome = attempt()
        if outcome is None:
            return
        reason = outcome
        print(f"{description}: {reason} (attempt {number} of {attempts})")
        if number < attempts:
            time.sleep(delay)
    raise ReleaseError(f"{description}: still not there after {attempts} attempts: {reason}")


def published_files(index: str, project: str, version: str) -> dict[str, dict[str, str]] | None:
    """``{filename: {"sha256": ..., "url": ...}}`` the index lists, or None if nothing yet."""
    status, body = fetch(f"{index}/pypi/{project}/{version}/json")
    if status == UNREACHABLE:
        raise Unreachable(body.decode())
    if status == 404:
        return None
    if status != 200:
        raise ReleaseError(f"{index} answered {status} for {project} {version}")
    return {
        item["filename"]: {"sha256": item["digests"]["sha256"], "url": item["url"]}
        for item in json.loads(body)["urls"]
    }


def verify_published(
    dist: Path,
    *,
    index: str,
    dependency_index: str,
    expect_provenance: bool,
    attempts: int,
    delay: float,
    import_name: str | None,
    expect_py_typed: bool,
    smoke_file: Path | None,
) -> None:
    dists = find_dists(dist)
    local = dists.digests()
    name = import_name or import_name_for(dists.name)

    remote: dict[str, dict[str, str]] = {}

    def listed() -> str | None:
        try:
            found = published_files(index, dists.project, dists.version)
        except Unreachable as error:
            return str(error)
        if found is None:
            return f"{index} lists no {dists.project} {dists.version} yet"
        for filename, digest in local.items():
            if filename not in found:
                return f"{filename} is not listed yet"
            if found[filename]["sha256"] != digest:
                raise ReleaseError(
                    f"{filename} on {index} is not the file that was built "
                    f"(built {digest}, listed {found[filename]['sha256']})"
                )
        remote.update(found)
        return None

    retrying("listing", listed, attempts, delay)
    print(f"listing: {index} has {', '.join(sorted(local))}, with the hashes that were built")
    passed = [f"listing: {len(local)} file(s), with the hashes that were built"]

    with tempfile.TemporaryDirectory(prefix="release-published-") as scratch_name:
        scratch = Path(scratch_name)

        def downloaded() -> str | None:
            # What a user's browser or mirror gets from each listed URL.
            for filename, digest in local.items():
                status, body = fetch(remote[filename]["url"])
                if status == UNREACHABLE:
                    return body.decode()
                if status != 200:
                    return f"{remote[filename]['url']} answered {status}"
                if hashlib.sha256(body).hexdigest() != digest:
                    raise ReleaseError(f"the {filename} that users download is not the one built")
            # What pip resolves for the exact version, as `pip install` would.
            python = make_venv(scratch, "venv-download")
            target = scratch / "resolved"
            result = pip(
                python, "download", "--no-deps", "--no-cache-dir", "--only-binary=:all:",
                "--index-url", f"{index}/simple/", "--dest", target,
                f"{dists.project}=={dists.version}",
            )  # fmt: skip
            if result.returncode != 0:
                return last_line(result.stderr)
            for path in target.iterdir():
                if path.name not in local:
                    raise ReleaseError(f"pip resolved {path.name}, which was not built here")
                if sha256_file(path) != local[path.name]:
                    raise ReleaseError(f"the {path.name} that pip resolves is not the one built")
            return None

        retrying("download", downloaded, attempts, delay)
        print("download: every listed file matches, and pip resolves the built wheel")
        passed.append("download: every listed file matches, and pip resolves the built wheel")

        # Install the bytes just verified; the index only supplies dependencies.
        fresh = make_venv(scratch, "venv-installed")
        wheel = scratch / "resolved" / dists.wheel.name
        installed = pip(fresh, "install", "--no-cache-dir", "--index-url", dependency_index, wheel)
        if installed.returncode != 0:
            raise ReleaseError(f"pip could not install what the index serves:\n{installed.stderr}")
        report = smoke(
            fresh,
            dists,
            scratch,
            import_name=name,
            expect_py_typed=expect_py_typed,
            smoke_file=smoke_file,
        )
        print(f"install: {report}")
        passed.append("install: the index's wheel installs, and its smoke tests pass")

    if expect_provenance:
        for filename in sorted(local):
            url = f"{index}/integrity/{dists.project}/{dists.version}/{filename}/provenance"

            def attested(url: str = url, filename: str = filename) -> str | None:
                status, body = fetch(url)
                if status == UNREACHABLE:
                    return body.decode()
                if status == 404:
                    return f"no attestation for {filename} yet"
                if status != 200:
                    raise ReleaseError(
                        f"{index} answered {status} for the provenance of {filename}"
                    )
                if not json.loads(body).get("attestation_bundles"):
                    raise ReleaseError(f"{filename} has an empty provenance record")
                return None

            retrying(f"provenance of {filename}", attested, attempts, delay)
        print("provenance: every file is attested")
        passed.append("provenance: every file is attested")
    summarize(
        f"### Read back from {index}: {dists.project} {dists.version}",
        "",
        *[f"- ✅ {line}" for line in passed],
    )


# --- the command line -----------------------------------------------------------------------


def add_package_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--import-name",
        metavar="NAME",
        help="what the package is imported as (default: the distribution name, with underscores)",
    )
    parser.add_argument(
        "--expect-py-typed", action="store_true", help="fail unless py.typed is in the install"
    )
    parser.add_argument(
        "--smoke",
        type=Path,
        metavar="SCRIPT",
        help="a Python script to run inside each install, after the built-in checks, with "
        "<distribution name> <import name> <version> as its arguments; a non-zero exit fails",
    )
    parser.add_argument(
        "--dependency-index",
        default="https://pypi.org/simple/",
        metavar="URL",
        help="where dependencies (and an sdist's build backend) are installed from "
        "(default: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    install = commands.add_parser(
        "verify-install",
        help="check the built files hold the whole package, then install and run them",
        description="Check that the wheel and the sdist hold every file of the package in the "
        "source tree, then install each into a fresh virtual environment and smoke-test it.",
    )
    install.add_argument(
        "dist", type=Path, help="the directory the build left: one wheel, at most one sdist"
    )
    install.add_argument(
        "--source-root",
        type=Path,
        default=Path("."),
        metavar="DIR",
        help="the project root, where pyproject.toml is (default: the current directory)",
    )
    install.add_argument(
        "--package-dir",
        metavar="DIR",
        help="the package's directory relative to the root (default: src/<name>, then <name>)",
    )
    install.add_argument(
        "--allow-extra",
        action="append",
        default=[],
        metavar="GLOB",
        help="a file the build adds on purpose and the source tree does not have, such as a "
        "generated _version.py, as a glob relative to the package directory (repeatable)",
    )
    add_package_options(install)

    rehearsal = commands.add_parser(
        "rehearsal-version",
        help="print (and optionally write) the throwaway version a rehearsal builds under",
        description="Turn 1.1.0 into 1.1.0.dev<run number x 100 + attempt>: below the real "
        "release, and new for every run and re-run.",
    )
    rehearsal.add_argument(
        "--file", type=Path, required=True, help="the file that holds the version"
    )
    rehearsal.add_argument(
        "--pattern",
        default=DEFAULT_VERSION_PATTERN,
        help="a regular expression, matched per line, with one group around the version "
        "(default: %(default)s)",
    )
    rehearsal.add_argument("--run-number", type=int, required=True, help="the workflow run number")
    rehearsal.add_argument(
        "--run-attempt", type=int, required=True, help="the attempt of that run, 1 to 99"
    )
    rehearsal.add_argument(
        "--write", action="store_true", help="also rewrite the version in --file"
    )

    published = commands.add_parser(
        "verify-published",
        help="after an upload, read the release back from the index and check it",
        description="Wait for the index to list the release, compare its hashes with the files "
        "that were built, download them again, install what the index serves and smoke-test it.",
    )
    published.add_argument(
        "dist", type=Path, help="the directory that was uploaded: one wheel, at most one sdist"
    )
    published.add_argument(
        "--index",
        default=DEFAULT_INDEX,
        metavar="URL",
        help="the index's root, without a trailing slash (default: %(default)s; "
        "https://test.pypi.org for TestPyPI)",
    )
    published.add_argument(
        "--expect-provenance",
        action="store_true",
        help="fail unless every file has a provenance record (PyPI trusted publishing)",
    )
    published.add_argument(
        "--attempts",
        type=int,
        default=20,
        help="how many times to look before giving up; a fresh upload takes a while to appear "
        "(default: %(default)s)",
    )
    published.add_argument(
        "--delay",
        type=float,
        default=15,
        metavar="SECONDS",
        help="seconds between attempts (default: %(default)s)",
    )
    add_package_options(published)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-install":
            verify_install(
                args.dist,
                args.source_root,
                package_dir=args.package_dir,
                import_name=args.import_name,
                allow_extra=args.allow_extra,
                expect_py_typed=args.expect_py_typed,
                smoke_file=args.smoke,
                dependency_index=args.dependency_index,
            )
        elif args.command == "rehearsal-version":
            version = rehearsal_version(
                read_version(args.file, args.pattern), args.run_number, args.run_attempt
            )
            if args.write:
                write_version(args.file, version, args.pattern)
            print(version)
        else:
            verify_published(
                args.dist,
                index=args.index.rstrip("/"),
                dependency_index=args.dependency_index,
                expect_provenance=args.expect_provenance,
                attempts=args.attempts,
                delay=args.delay,
                import_name=args.import_name,
                expect_py_typed=args.expect_py_typed,
                smoke_file=args.smoke,
            )
    except ReleaseError as error:
        print(f"::error::{error}", file=sys.stderr)
        summarize(f"### ❌ {args.command} failed", "", "```", str(error), "```")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
