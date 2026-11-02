"""F31 step 1 — ``MetaFolder``, the meta files sandbox helper (``06`` AC-F31-04, AC-F31-05;
SEC-F31-04; TR-F31-08 (16 KiB, ``st_nlink``); ``04`` §6.1).

Link rows run where the OS allows: symlinks need a privilege on Windows (skipped without
it), junctions are Windows only, FIFOs POSIX only (``06`` §0.3)."""

import builtins
import os
import sys
from pathlib import Path

import pytest

from engine.core import safefile
from engine.core.constants import META_READ_MAX_BYTES
from engine.core.safefile import EntryKind, ReadKind
from engine.meta.files import MetaFolder, RootState

WINDOWS = sys.platform == "win32"
NAME = "answer.txt"


class StatProxy:
    """A stat result with some fields replaced (a seam for ``st_nlink``)."""

    def __init__(self, st, **fields) -> None:
        self._st = st
        self._fields = fields

    def __getattr__(self, name):
        return self._fields[name] if name in self._fields else getattr(self._st, name)


def _symlink(link: Path, target: Path, *, folder: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=folder)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks are not permitted here: {exc}")


def _junction(link: Path, target: Path) -> None:
    if not WINDOWS:
        pytest.skip("junctions are Windows only")
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


def _record(monkeypatch, *names: str) -> list[str]:
    """Paths passed to the named ``os`` calls (and ``open``), recorded, calls kept."""
    seen: list[str] = []
    for name in names:
        real = getattr(os, name)

        def spy(path, *args, _real=real, **kwargs):
            if isinstance(path, (str, Path)):
                seen.append(os.path.abspath(path))
            return _real(path, *args, **kwargs)

        monkeypatch.setattr(os, name, spy)
    real_open = builtins.open

    def open_spy(path, *args, **kwargs):
        if isinstance(path, (str, Path)):
            seen.append(os.path.abspath(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_spy)
    return seen


# (row id, expected exists, read kind, entry kind)
ENTRY_ROWS = [
    ("none", False, ReadKind.MISSING, EntryKind.MISSING),
    ("regular_16384", True, ReadKind.OK, EntryKind.REGULAR),
    ("regular_16385", True, ReadKind.TOO_LARGE, EntryKind.REGULAR),
    pytest.param("sparse_2gib", True, ReadKind.TOO_LARGE, EntryKind.REGULAR,
                 marks=[pytest.mark.slow,
                        pytest.mark.skipif(WINDOWS, reason="sparse file row is POSIX")]),
    ("folder", False, ReadKind.NOT_REGULAR, EntryKind.OTHER),
    ("file_symlink", False, ReadKind.NOT_REGULAR, EntryKind.OTHER),
    ("dir_symlink", False, ReadKind.NOT_REGULAR, EntryKind.OTHER),
    ("junction", False, ReadKind.NOT_REGULAR, EntryKind.OTHER),
    ("hard_link", True, ReadKind.LINKED, EntryKind.REGULAR),
    ("fstat_nlink_0", True, ReadKind.LINKED, EntryKind.REGULAR),
    ("fstat_nlink_2", True, ReadKind.LINKED, EntryKind.REGULAR),
    ("lstat_nlink_2", True, ReadKind.OK, EntryKind.REGULAR),
    pytest.param("fifo", False, ReadKind.NOT_REGULAR, EntryKind.OTHER,
                 marks=pytest.mark.skipif(WINDOWS, reason="FIFOs are POSIX only")),
    ("lstat_permission", False, ReadKind.UNREADABLE, EntryKind.OTHER),
]


@pytest.mark.parametrize("row, exists, read_kind, kind", ENTRY_ROWS)
def test_ac_f31_04_what_meta_folder_sees_at_a_name(row, exists, read_kind, kind, tmp_path,
                                                   monkeypatch):
    root = tmp_path / "game" / "characters"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_bytes(b"secret")
    entry = root / NAME
    data = None
    if row in ("regular_16384", "fstat_nlink_0", "fstat_nlink_2", "lstat_nlink_2",
               "lstat_permission"):
        data = b"y" * (META_READ_MAX_BYTES if row == "regular_16384" else 3)
        entry.write_bytes(data)
    elif row == "regular_16385":
        entry.write_bytes(b"y" * (META_READ_MAX_BYTES + 1))
    elif row == "sparse_2gib":
        with open(entry, "wb") as f:
            f.truncate(2 * 1024 ** 3)
    elif row == "folder":
        entry.mkdir()
    elif row == "file_symlink":
        _symlink(entry, secret)
    elif row == "dir_symlink":
        _symlink(entry, outside, folder=True)
    elif row == "junction":
        _junction(entry, outside)
    elif row == "hard_link":
        os.link(secret, entry)
    elif row == "fifo":
        os.mkfifo(entry)
    folder = MetaFolder(root, frozenset({NAME}))

    if row.startswith("fstat_nlink_"):
        real_fstat = os.fstat
        count = int(row[-1])
        monkeypatch.setattr(os, "fstat", lambda fd: StatProxy(real_fstat(fd), st_nlink=count))
    if row in ("lstat_nlink_2", "lstat_permission"):
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            if os.path.abspath(path) == os.path.abspath(entry):
                if row == "lstat_permission":
                    raise PermissionError(13, "denied")
                return StatProxy(real_lstat(path, *args, **kwargs), st_nlink=2)
            return real_lstat(path, *args, **kwargs)

        monkeypatch.setattr(os, "lstat", lstat)
    reads: list[int] = []
    if row in ("regular_16385", "sparse_2gib"):
        real_read = os.read
        monkeypatch.setattr(os, "read", lambda fd, n: reads.append(n) or real_read(fd, n))
    opened = _record(monkeypatch, "open")

    assert folder.exists(NAME) is exists
    result = folder.read(NAME)
    assert result.kind is read_kind
    assert folder.entry_kind(NAME) is kind
    if read_kind is ReadKind.OK:
        assert result.data == data
    else:
        assert result.data is None
    assert reads == []                                   # refused by size, never read
    assert os.path.abspath(secret) not in opened         # a link's target is never opened
    if row == "hard_link":                               # other callers are unchanged
        monkeypatch.undo()
        assert safefile.read_regular(entry, META_READ_MAX_BYTES).kind is ReadKind.OK


ROOT_ROWS = [
    ("missing", RootState.MISSING),
    ("real", RootState.OK),
    ("file", RootState.BAD),
    ("file_symlink", RootState.BAD),
    ("dir_symlink", RootState.BAD),
    ("junction", RootState.BAD),
    ("via_link", RootState.BAD),
    ("lstat_permission", RootState.UNREADABLE),
]


@pytest.mark.parametrize("row, state", ROOT_ROWS)
def test_ac_f31_05_the_root_check(row, state, tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    documents = tmp_path / "outside" / "Documents"
    documents.mkdir(parents=True)
    (documents / "private.txt").write_bytes(b"private")
    root = game / "characters"
    if row == "real" or row == "lstat_permission":
        root.mkdir()
    elif row == "file":
        root.write_bytes(b"not a folder")
    elif row == "file_symlink":
        _symlink(root, documents / "private.txt")
    elif row == "dir_symlink":
        _symlink(root, documents, folder=True)
    elif row == "junction":
        _junction(root, documents)
    elif row == "via_link":
        root.mkdir()
        link = tmp_path / "linked_game"
        if WINDOWS:
            _junction(link, game)
        else:
            _symlink(link, game, folder=True)
        root = link / "characters"                       # reached through the link
    if row == "lstat_permission":
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            if os.path.abspath(path) == os.path.abspath(root):
                raise PermissionError(13, "denied")
            return real_lstat(path, *args, **kwargs)

        monkeypatch.setattr(os, "lstat", lstat)
    calls: list[dict] = []
    real_ensure = safefile.ensure_real_dir

    def ensure(folder, **kwargs):
        calls.append(kwargs)
        return real_ensure(folder, **kwargs)

    monkeypatch.setattr(safefile, "ensure_real_dir", ensure)
    seen = _record(monkeypatch, "scandir", "listdir", "open")

    assert MetaFolder(root, frozenset({NAME})).root_state() is state
    assert all(c == {"release": False, "create": False} for c in calls)
    assert bool(calls) is (state in (RootState.OK, RootState.BAD))
    assert not any(Path(p).is_relative_to(documents.parent) for p in seen)
    if row == "missing":
        assert not root.exists()                         # nothing created
