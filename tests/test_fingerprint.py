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


# --- hidden files: what an upload and a download leave behind ------------------------------------


def test_hidden_files_are_not_counted_by_default(tmp_path):
    # `uv build` leaves a `.gitignore` in its output directory, and actions/upload-artifact leaves
    # hidden files out: a fingerprint that counted it could never survive the trip between jobs.
    plain = make(tmp_path / "plain", {"a.whl": b"wheel", "a.tar.gz": b"sdist"})
    built = make(
        tmp_path / "built", {"a.whl": b"wheel", "a.tar.gz": b"sdist", ".gitignore": b"*\n"}
    )
    assert fingerprint.digest(built) == fingerprint.digest(plain)


def test_hidden_directories_and_everything_in_them_are_not_counted_either(tmp_path):
    plain = make(tmp_path / "plain", {"site/index.html": b"x"})
    hidden = make(
        tmp_path / "hidden",
        {"site/index.html": b"x", ".well-known/security.txt": b"y", "site/.nojekyll": b""},
    )
    assert fingerprint.digest(hidden) == fingerprint.digest(plain)


def test_include_hidden_counts_them(tmp_path):
    plain = make(tmp_path / "plain", {"a": b"1"})
    built = make(tmp_path / "built", {"a": b"1", ".gitignore": b"*\n", ".d/b": b"2"})
    assert fingerprint.digest(built, include_hidden=True) != fingerprint.digest(plain)
    names = [name for _, name in fingerprint.manifest(built, include_hidden=True)]
    assert names == [".d/b", ".gitignore", "a"]
    assert [name for _, name in fingerprint.manifest(built)] == ["a"]


def test_a_directory_of_only_hidden_files_has_nothing_to_fingerprint_by_default(tmp_path):
    only = make(tmp_path, {".gitignore": b"*\n"})
    with pytest.raises(fingerprint.FingerprintError, match="nothing to fingerprint"):
        fingerprint.digest(only)
    assert fingerprint.digest(only, include_hidden=True).startswith("sha256-")


def test_only_the_parts_below_the_directory_count_as_hidden(tmp_path):
    # A fingerprint of ".cache/out" must not skip everything because ".cache" starts with a dot.
    inside = make(tmp_path / ".cache" / "out", {"a": b"1"})
    assert [name for _, name in fingerprint.manifest(inside)] == ["a"]


def test_a_single_file_is_counted_whatever_its_name(tmp_path):
    path = make(tmp_path, {".env.example": b"x"}) / ".env.example"
    assert fingerprint.manifest(path) == [(fingerprint.sha256_file(path), ".env.example")]


def test_a_fingerprint_made_with_and_checked_without_hidden_files_is_a_mismatch(tmp_path):
    root = make(tmp_path, {"a": b"1", ".h": b"2"})
    counted = fingerprint.digest(root, include_hidden=True)
    with pytest.raises(fingerprint.FingerprintError):
        fingerprint.check(root, counted)  # the two sides must agree
    assert fingerprint.check(root, counted, include_hidden=True)


def test_the_listing_names_every_counted_file_and_every_hidden_one_left_out(tmp_path):
    root = make(tmp_path, {"a.whl": b"w", "b.tar.gz": b"s", ".gitignore": b"*\n"})
    text = fingerprint.listing(root)
    assert "2 file(s) counted" in text and "a.whl" in text and "b.tar.gz" in text
    assert "1 hidden file(s) not counted" in text and ".gitignore" in text
    assert "hidden file(s) not counted" not in fingerprint.listing(root, include_hidden=True)


def test_a_mismatch_explains_itself_with_the_list_of_files_and_how_to_compare_it(tmp_path):
    root = make(tmp_path, {"a": b"1", ".gitignore": b"*\n"})
    with pytest.raises(fingerprint.FingerprintError) as caught:
        fingerprint.check(root, "sha256-" + "0" * 64)
    assert str(caught.value).startswith("The files are not the ones that were fingerprinted")
    details = caught.value.details
    assert "1 file(s) counted" in details and "1 hidden file(s) not counted" in details
    assert "include-hidden" in details and "include-hidden-files: true" in details


def test_the_command_line_prints_the_list_of_files_and_honours_the_flag(tmp_path, capsys):
    root = make(tmp_path, {"a": b"1", ".gitignore": b"*\n"})
    assert fingerprint.main(["digest", str(root)]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == fingerprint.digest(
        root
    )  # standard output stays the digest alone
    assert "1 file(s) counted" in captured.err
    assert fingerprint.main(["digest", str(root), "--include-hidden"]) == 0
    assert capsys.readouterr().out.strip() == fingerprint.digest(root, include_hidden=True)


def test_a_failed_check_prints_the_list_after_the_one_line_annotation(tmp_path, capsys):
    root = make(tmp_path, {"a": b"1"})
    assert fingerprint.main(["check", str(root), "sha256-" + "0" * 64]) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines[0].startswith("::error::The files are not the ones")
    assert "\n" not in lines[0] and any("1 file(s) counted" in line for line in lines[1:])


def test_the_summary_page_lists_the_files_so_two_jobs_can_be_compared(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    root = make(tmp_path / "out", {"a.whl": b"w", ".gitignore": b"*\n"})
    assert fingerprint.main(["digest", str(root)]) == 0
    text = summary.read_text(encoding="utf-8")
    assert (
        "<details><summary>Files counted in the fingerprint</summary>" in text and "a.whl" in text
    )
    assert fingerprint.main(["check", str(root), "sha256-" + "0" * 64]) == 1
    assert "### ❌ Fingerprint check failed" in summary.read_text(encoding="utf-8")
    assert "1 hidden file(s) not counted" in summary.read_text(encoding="utf-8")
