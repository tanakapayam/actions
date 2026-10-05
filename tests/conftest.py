"""Shared fixtures: the scripts under test are importable, and a built fixture package."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

FIXTURE = ROOT / "tests" / "fixtures" / "sample-pkg"


def build(source: Path, out: Path) -> Path:
    """Build ``source`` into ``out`` with the installed ``build`` and ``hatchling``, offline."""
    result = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(out), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"building {source} failed:\n{result.stdout}\n{result.stderr}")
    return out


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A project root (a copy of the fixture package) and its built ``dist/`` next to it."""
    pytest.importorskip("build")
    pytest.importorskip("hatchling")
    root = tmp_path_factory.mktemp("sample") / "sample-pkg"
    shutil.copytree(FIXTURE, root)
    build(root, root / "dist")
    return root


@pytest.fixture
def dist(built: Path, tmp_path: Path) -> Path:
    """A private copy of the built distributions that a test may damage."""
    target = tmp_path / "dist"
    shutil.copytree(built / "dist", target)
    return target
