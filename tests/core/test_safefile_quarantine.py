"""``safefile.quarantine`` (F16 ``07`` I-9; ADR-0003 §9): the one rename of a damaged data
file to its ``.bad`` name, shared by F12 and F16. It moves the entry itself (a link is
renamed, never followed), replaces an older bad entry, and never raises ``OSError``."""

import errno
import hashlib
import os
from pathlib import Path

import pytest

from engine.core import safefile
from engine.core.safefile import quarantine

BAD = "data.bad.json"


@pytest.fixture
def folder(tmp_path) -> Path:
    path = tmp_path.resolve() / "data"
    path.mkdir()
    return path


@pytest.fixture
def outside(tmp_path) -> Path:
    path = tmp_path.resolve() / "outside"
    path.mkdir()
    (path / "secret.txt").write_bytes(b"secret")
    return path


def tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for root, dirs, names in sorted(os.walk(path)):
        for name in sorted(names):
            h.update(name.encode())
            h.update((Path(root) / name).read_bytes())
    return h.hexdigest()


def link_dir(link: Path, target: Path) -> None:
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory links not permitted here: {exc}")


def test_moves_the_file(folder):
    (folder / "data.json").write_bytes(b"{")
    assert quarantine(folder / "data.json", BAD)
    assert sorted(os.listdir(folder)) == [BAD]
    assert (folder / BAD).read_bytes() == b"{"


def test_replaces_an_older_bad_file(folder):
    (folder / "data.json").write_bytes(b"new")
    (folder / BAD).write_bytes(b"old")
    assert quarantine(folder / "data.json", BAD)
    assert sorted(os.listdir(folder)) == [BAD]
    assert (folder / BAD).read_bytes() == b"new"


def test_a_directory_replaces_an_older_bad_file(folder):
    (folder / "data.json").mkdir()
    (folder / "data.json" / "inner").write_bytes(b"x")
    (folder / BAD).write_bytes(b"old")
    assert quarantine(folder / "data.json", BAD)
    assert sorted(os.listdir(folder)) == [BAD]
    assert (folder / BAD / "inner").read_bytes() == b"x"


def test_a_directory_at_the_bad_name_is_kept(folder):
    (folder / "data.json").write_bytes(b"{")
    (folder / BAD).mkdir()
    (folder / BAD / "inner").write_bytes(b"x")
    assert not quarantine(folder / "data.json", BAD)
    assert (folder / "data.json").read_bytes() == b"{"
    assert (folder / BAD / "inner").read_bytes() == b"x"


def test_missing_target_is_false_and_creates_nothing(folder):
    assert not quarantine(folder / "data.json", BAD)
    assert os.listdir(folder) == []


def test_a_failed_replace_is_false_and_leaves_the_file(folder, monkeypatch):
    (folder / "data.json").write_bytes(b"{")
    (folder / BAD).write_bytes(b"old")

    def refuse(*args, **kwargs):
        raise OSError(errno.EACCES, os.strerror(errno.EACCES))
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "replace", refuse)
        assert not quarantine(folder / "data.json", BAD)
    assert (folder / "data.json").read_bytes() == b"{"


def test_a_file_link_is_renamed_never_followed(folder, outside):
    try:
        os.symlink(outside / "secret.txt", folder / "data.json")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not permitted here: {exc}")
    before = tree_hash(outside)
    assert quarantine(folder / "data.json", BAD)
    assert (folder / BAD).is_symlink()
    assert tree_hash(outside) == before


def test_a_directory_link_is_renamed_never_followed(folder, outside):
    link_dir(folder / "data.json", outside)
    before = tree_hash(outside)
    assert quarantine(folder / "data.json", BAD)
    assert not os.path.lexists(folder / "data.json") and os.path.lexists(folder / BAD)
    assert tree_hash(outside) == before
    assert sorted(os.listdir(outside)) == ["secret.txt"]


def test_a_link_at_the_bad_name_is_never_written_through(folder, outside):
    link_dir(folder / BAD, outside)
    (folder / "data.json").write_bytes(b"{")
    before = tree_hash(outside)
    quarantine(folder / "data.json", BAD)                  # either result; never through
    assert tree_hash(outside) == before
    assert sorted(os.listdir(outside)) == ["secret.txt"]


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\\b", "x\0"])
def test_bad_name_must_be_a_plain_name(folder, name):
    with pytest.raises(ValueError):
        quarantine(folder / "data.json", name)
