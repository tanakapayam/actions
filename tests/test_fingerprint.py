"""lib/fingerprint.py: one digest for a set of files, and a check that they are unchanged."""

import hashlib
import os
from pathlib import Path

import fingerprint
import pytest


def make(root: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def test_the_fingerprint_is_a_digest_of_a_sorted_manifest(tmp_path):
    make(tmp_path, {"b.txt": b"two", "a.txt": b"one"})
    manifest = (
        f"{hashlib.sha256(b'one').hexdigest()}  a.txt\n"
        f"{hashlib.sha256(b'two').hexdigest()}  b.txt\n"
    )
    assert fingerprint.digest(tmp_path) == "sha256-" + hashlib.sha256(manifest.encode()).hexdigest()


def test_it_is_stable_and_does_not_depend_on_creation_order(tmp_path):
    one = make(tmp_path / "one", {"a": b"1", "b": b"2", "c/d": b"3"})
    two = make(tmp_path / "two", {"c/d": b"3", "b": b"2", "a": b"1"})
    assert fingerprint.digest(one) == fingerprint.digest(two) == fingerprint.digest(one)


@pytest.mark.parametrize(
    "change",
    [
        lambda root: (root / "a").write_bytes(b"changed"),
        lambda root: (root / "a").rename(root / "renamed"),
        lambda root: make(root, {"extra": b""}),
        lambda root: (root / "c" / "d").unlink(),
        lambda root: (root / "c" / "d").rename(root / "c" / "e"),
    ],
    ids=["content", "name", "added file", "removed file", "moved within a directory"],
)
def test_any_change_to_the_files_changes_the_fingerprint(tmp_path, change):
    root = make(tmp_path, {"a": b"1", "b": b"2", "c/d": b"3"})
    before = fingerprint.digest(root)
    change(root)
    assert fingerprint.digest(root) != before


def test_a_flat_directory_matches_what_sha256sum_would_list(tmp_path):
    root = make(tmp_path, {"x.whl": b"wheel", "x.tar.gz": b"sdist"})
    lines = sorted(f"{fingerprint.sha256_file(p)}  {p.name}\n" for p in root.iterdir())
    expected = "sha256-" + hashlib.sha256("".join(lines).encode()).hexdigest()
    assert fingerprint.digest(root) == expected


def test_a_single_file_can_be_fingerprinted(tmp_path):
    path = make(tmp_path, {"only.txt": b"x"}) / "only.txt"
    assert fingerprint.digest(path).startswith("sha256-")


def test_nothing_to_fingerprint_is_an_error_not_a_digest_of_nothing(tmp_path):
    with pytest.raises(fingerprint.FingerprintError, match="no files"):
        fingerprint.digest(tmp_path)
    with pytest.raises(fingerprint.FingerprintError, match="does not exist"):
        fingerprint.digest(tmp_path / "missing")


def test_a_symlink_is_refused(tmp_path):
    root = make(tmp_path, {"a": b"1"})
    os.symlink(root / "a", root / "link")
    with pytest.raises(fingerprint.FingerprintError, match="symbolic link"):
        fingerprint.digest(root)


def test_check_accepts_the_same_files_and_refuses_changed_ones(tmp_path):
    root = make(tmp_path, {"a": b"1"})
    expected = fingerprint.digest(root)
    assert expected in fingerprint.check(root, expected)
    (root / "a").write_bytes(b"2")
    with pytest.raises(fingerprint.FingerprintError, match="not the ones that were fingerprinted"):
        fingerprint.check(root, expected)


@pytest.mark.parametrize("bad", ["", "   ", "sha256-", "sha256-xyz", "abc", "sha256-" + "A" * 64])
def test_check_refuses_anything_that_is_not_a_fingerprint(tmp_path, bad):
    # An output that was never produced reaches the check as "": it must not pass vacuously.
    root = make(tmp_path, {"a": b"1"})
    with pytest.raises(fingerprint.FingerprintError, match="is not a fingerprint"):
        fingerprint.check(root, bad)


def test_the_command_line(tmp_path, capsys):
    root = make(tmp_path, {"a": b"1"})
    assert fingerprint.main(["digest", str(root)]) == 0
    printed = capsys.readouterr().out.strip()
    assert printed == fingerprint.digest(root)
    assert fingerprint.main(["check", str(root), printed]) == 0
    assert fingerprint.main(["check", str(root), "sha256-" + "0" * 64]) == 1
    assert capsys.readouterr().err.startswith("::error::")
