"""Safe file core (F12 ``04`` §3, §7.4, §7.5, §8; SEC-F12-06, SEC-F12-13; F44 I-17):
AC-F12-17 (the lift), AC-F12-18 (reading only regular files), AC-F12-19 (atomic writes
under faults, TR-F12-02), and the bounded stale-temp scan.

Faults are injected by patching ``os`` calls inside ``engine.core.safefile`` within a
``monkeypatch.context()``. Link rows skip where symlinks aren't permitted; Windows uses
junctions for directory links."""

import ast
import errno
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from engine.core import safefile
from engine.core.paths import GamePaths
from engine.core.safefile import (
    ReadKind,
    Stamp,
    TargetChanged,
    ensure_real_dir,
    read_regular,
    remove_stale_temps,
    write_atomic,
)
from engine.tools.editor import document

FILE_MAX_BYTES = 33_554_432           # F12's real cap (runtime/limits.py arrives in step 2)
NAME = "persistent.json"
MIB = 1 << 20
SAFEFILE_PATH = Path(safefile.__file__)
DOCUMENT_PATH = Path(document.__file__)


# --- Helpers ---------------------------------------------------------------------------------

@pytest.fixture
def base(tmp_path) -> Path:
    """``tmp_path`` by its real path (macOS reaches temp folders through /var → /private)."""
    return tmp_path.resolve()


@pytest.fixture
def outside(base) -> Path:
    folder = base / "outside"
    folder.mkdir()
    return folder


def link_dir(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows, a symlink elsewhere; skips if not allowed."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory links not permitted here: {exc}")


def symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not permitted here: {exc}")


def temps(folder: Path) -> list[str]:
    return sorted(name for name in os.listdir(folder) if name.endswith(".tmp"))


class Patched:
    """A stat result with some fields replaced."""

    def __init__(self, st, **changes) -> None:
        self._st = st
        self._changes = changes

    def __getattr__(self, name):
        if name in self._changes:
            return self._changes[name]
        return getattr(self._st, name)


def fail_on(real, n: int, code: int, *, close_first: bool = False):
    """A stand-in for ``real`` that raises ``OSError(code)`` on its n-th call."""
    calls = [0]

    def call(*args, **kwargs):
        calls[0] += 1
        if calls[0] == n:
            if close_first:                 # close() reports an error but releases the fd
                real(*args, **kwargs)
            raise OSError(code, os.strerror(code))
        return real(*args, **kwargs)
    return call


# --- AC-F12-17: the lift; the editor unchanged ------------------------------------------------

def test_ac_f12_17_exports_and_imports_only_the_standard_library():
    for name in ("ensure_real_dir", "read_regular", "write_atomic", "remove_stale_temps",
                 "Stamp"):
        assert hasattr(safefile, name), name
    tree = ast.parse(SAFEFILE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            imported.add(node.module.split(".")[0])
    assert imported, "the scan found the imports"
    assert imported <= sys.stdlib_module_names, imported - sys.stdlib_module_names
    # SEC-F12-01(a): no unsafe loaders, no code execution.
    assert not imported & {"pickle", "marshal", "shelve", "importlib", "ctypes"}
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not called & {"eval", "exec", "compile", "__import__"}


def test_ac_f12_17_document_has_no_replace_or_fsync_of_its_own():
    tree = ast.parse(DOCUMENT_PATH.read_text(encoding="utf-8"))
    used = {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "os"}
    assert not used & {"replace", "fsync", "rename"}
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    assert "shutil" not in imported


@pytest.fixture
def game(base) -> GamePaths:
    root = base / "game"
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_bytes(b'label start:\n    "Hi."\n')
    return GamePaths.for_game(root)


def test_ac_f12_17_editor_save_calls_write_atomic(game, monkeypatch):
    calls = []
    real = safefile.write_atomic

    def spy(target, pieces, **kwargs):
        pieces = tuple(pieces)
        calls.append((Path(target), pieces, kwargs))
        return real(target, pieces, **kwargs)

    doc = document.open_document(game, "script/main.vns")
    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_atomic", spy)
        document.save(doc, "label start:\n    \"Bye.\"")
    path = game.root / "script" / "main.vns"
    assert path.read_bytes() == b'label start:\n    "Bye."\n'
    assert len(calls) == 1
    target, pieces, kwargs = calls[0]
    assert os.path.samefile(target, path)
    assert b"".join(pieces) == path.read_bytes()
    assert kwargs["replace_tries"] == 1              # the editor reports a lock at once
    assert temps(path.parent) == []


def test_ac_f12_17_checked_target_and_reason_keep_f44_texts(game):
    doc = document.open_document(game, "script/main.vns")
    assert document._reason(OSError(errno.ENOSPC, "x")) == "the disk is full."
    for code in (errno.EACCES, errno.EPERM, errno.EROFS):
        assert document._reason(OSError(code, "x")) == "the file is read-only or locked."
    assert document._reason(OSError(errno.EIO, "x")) == "the system reported an error."
    assert document._reason(FileExistsError(errno.EEXIST, "x")) == (
        "the system reported an error.")
    (game.root / "script" / "main.vns").unlink()
    with pytest.raises(document.SaveError) as caught:
        document._checked_target(doc)
    assert caught.value.message == (
        "Couldn't save `script/main.vns`: the file was moved or deleted.")


def test_ac_f12_17_every_taken_temp_name_gives_the_system_reason(game, monkeypatch):
    path = game.root / "script" / "main.vns"
    before = path.read_bytes()
    (path.parent / ".main.vns.deadbeef.tmp").write_bytes(b"planted")
    doc = document.open_document(game, "script/main.vns")
    with monkeypatch.context() as patch:
        patch.setattr(document, "_temp_token", lambda: "deadbeef")
        with pytest.raises(document.SaveError) as caught:
            document.save(doc, "changed")
    assert caught.value.message == "Couldn't save `script/main.vns`: the system reported an error."
    assert path.read_bytes() == before
    assert temps(path.parent) == [".main.vns.deadbeef.tmp"]


# --- AC-F12-18: reading only regular files -------------------------------------------------

def test_ac_f12_18_missing_file_in_a_missing_folder(base):
    folder = base / "p"
    assert ensure_real_dir(folder)
    assert folder.is_dir()
    result = read_regular(folder / NAME, FILE_MAX_BYTES)
    assert result.kind is ReadKind.MISSING
    assert result.data is None and result.stamp is None


def test_ac_f12_18_regular_two_bytes(base):
    path = base / NAME
    path.write_bytes(b"{}")
    result = read_regular(path, FILE_MAX_BYTES)
    assert result.ok and result.data == b"{}"
    st = os.stat(path)
    assert result.stamp == Stamp(st.st_ino, st.st_size, st.st_mtime_ns)


def _sparse(path: Path, size: int) -> None:
    with open(path, "wb") as stream:
        stream.truncate(size)


def test_ac_f12_18_exactly_the_cap_is_read_whole(base):
    path = base / NAME
    _sparse(path, FILE_MAX_BYTES)
    result = read_regular(path, FILE_MAX_BYTES)
    assert result.ok
    assert len(result.data) == FILE_MAX_BYTES


def _read_spy(patch) -> list[int]:
    got: list[int] = []
    real = os.read

    def spy(fd, n):
        data = real(fd, n)
        got.append(len(data))
        return data
    patch.setattr(safefile.os, "read", spy)
    return got


def test_ac_f12_18_over_the_cap_reads_at_most_cap_plus_one(base, monkeypatch):
    path = base / NAME
    _sparse(path, FILE_MAX_BYTES + 1)
    with monkeypatch.context() as patch:
        got = _read_spy(patch)
        result = read_regular(path, FILE_MAX_BYTES)
    assert result.kind is ReadKind.TOO_LARGE
    assert sum(got) <= FILE_MAX_BYTES + 1


def test_ac_f12_18_a_file_that_grows_after_stat_is_read_to_cap_plus_one(base, monkeypatch):
    path = base / NAME
    path.write_bytes(b"x" * 50)
    real_lstat, real_fstat = os.lstat, os.fstat
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "lstat", lambda p: Patched(real_lstat(p), st_size=3))
        patch.setattr(safefile.os, "fstat", lambda fd: Patched(real_fstat(fd), st_size=3))
        got = _read_spy(patch)
        result = read_regular(path, 10)
    assert result.kind is ReadKind.TOO_LARGE
    assert sum(got) == 11


def test_ac_f12_18_fstat_differing_from_lstat_is_refused(base, monkeypatch):
    path = base / NAME
    path.write_bytes(b"{}")
    real = os.fstat
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fstat",
                      lambda fd: Patched(real(fd), st_ino=real(fd).st_ino + 1))
        result = read_regular(path, FILE_MAX_BYTES)
    assert result.kind is ReadKind.NOT_REGULAR
    assert result.data is None


def test_ac_f12_18_symlink_target_is_never_opened(base, outside, monkeypatch):
    secret = outside / "secret.json"
    secret.write_bytes(b"{}")
    path = base / NAME
    symlink(path, secret)
    opened = []
    real = os.open
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "open",
                      lambda p, *a, **k: opened.append(p) or real(p, *a, **k))
        result = read_regular(path, FILE_MAX_BYTES)
    assert result.kind is ReadKind.NOT_REGULAR
    assert opened == []


def test_ac_f12_18_directory_is_not_regular(base):
    (base / NAME).mkdir()
    assert read_regular(base / NAME, FILE_MAX_BYTES).kind is ReadKind.NOT_REGULAR


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_ac_f12_18_fifo_is_not_regular_and_returns_at_once(base):
    os.mkfifo(base / NAME)
    started = time.monotonic()
    result = read_regular(base / NAME, FILE_MAX_BYTES)
    assert result.kind is ReadKind.NOT_REGULAR
    assert time.monotonic() - started < 1.0


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_ac_f12_18_junction_is_not_regular(base, outside):
    link_dir(base / NAME, outside)
    assert read_regular(base / NAME, FILE_MAX_BYTES).kind is ReadKind.NOT_REGULAR
    assert os.listdir(outside) == []


def test_ac_f12_18_eio_on_read_is_unreadable(base, monkeypatch):
    path = base / NAME
    path.write_bytes(b"{}")
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "read", fail_on(os.read, 1, errno.EIO))
        result = read_regular(path, FILE_MAX_BYTES)
    assert result.kind is ReadKind.UNREADABLE


def test_ac_f12_18_dev_folder_that_is_a_symlink_is_refused(base, outside):
    game = base / "game"
    game.mkdir()
    symlink(game / "persistent", outside, directory=True)
    assert not ensure_real_dir(game / "persistent")


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-only")
def test_ac_f12_18_dev_folder_that_is_a_junction_is_refused(base, outside):
    game = base / "game"
    game.mkdir()
    link_dir(game / "persistent", outside)
    assert not ensure_real_dir(game / "persistent")
    assert not ensure_real_dir(game / "persistent", release=True)   # links inside a root


def test_ac_f12_18_dev_folder_whose_realpath_differs_is_refused(base):
    real_game = base / "real_game"
    real_game.mkdir()
    link_dir(base / "game", real_game)
    assert not ensure_real_dir(base / "game" / "persistent")


def test_ac_f12_18_release_root_under_a_linked_parent_is_used(base):
    real_home = base / "real_home"
    real_home.mkdir()
    link_dir(base / "home", real_home)
    folder = base / "home" / "vn-engine" / "my-game" / "persistent"
    assert ensure_real_dir(folder, release=True)
    assert (real_home / "vn-engine" / "my-game" / "persistent").is_dir()


def test_ensure_real_dir_refuses_a_file_and_a_missing_folder_without_create(base):
    (base / "p").write_bytes(b"")
    assert not ensure_real_dir(base / "p")
    assert not ensure_real_dir(base / "q", create=False)
    assert not (base / "q").exists()


# --- AC-F12-19: atomic writes under faults (TR-F12-02, SEC-F12-06a) -----------------------

OLD = b'{"format":1}'
NEW = bytes(range(256)) * (5 * MIB // 512)        # 2.5 MiB: three write joins


@pytest.fixture
def folder(base) -> Path:
    path = base / "persistent"
    path.mkdir()
    (path / NAME).write_bytes(OLD)
    return path


def _sleeps() -> tuple[list[float], object]:
    slept: list[float] = []
    return slept, slept.append


def test_ac_f12_19_new_is_written_in_three_joins_and_the_stamp_matches(folder, monkeypatch):
    sizes = []
    real = os.write
    slept, sleep = _sleeps()
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "write",
                      lambda fd, data: sizes.append(len(data)) or real(fd, data))
        stamp = write_atomic(folder / NAME, (NEW[:100], NEW[100:]), sleep=sleep)
    assert (folder / NAME).read_bytes() == NEW
    assert sizes == [MIB, MIB, len(NEW) - 2 * MIB]
    assert stamp == Stamp.of(os.stat(folder / NAME))
    assert temps(folder) == [] and slept == []


_BEFORE_REPLACE = [("open", 1, errno.EACCES), ("write", 1, errno.ENOSPC),
                   ("write", 2, errno.ENOSPC), ("write", 3, errno.ENOSPC),
                   ("fsync", 1, errno.EIO), ("fstat", 1, errno.EIO), ("close", 1, errno.EIO),
                   ("replace", 1, errno.EIO)]
_FOLDER_SYNC = [("open", 2, errno.EACCES), ("fsync", 2, errno.EIO), ("close", 2, errno.EIO)]


@pytest.mark.parametrize("call, n, code", _BEFORE_REPLACE,
                         ids=[f"{c}-{n}" for c, n, _ in _BEFORE_REPLACE])
def test_ac_f12_19_a_fault_before_the_replace_keeps_old(folder, monkeypatch, call, n, code):
    real = getattr(os, call)
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, call, fail_on(real, n, code, close_first=call == "close"))
        with pytest.raises(OSError) as caught:
            write_atomic(folder / NAME, (NEW,), sleep=lambda _s: None)
    assert caught.value.errno == code
    assert (folder / NAME).read_bytes() == OLD
    assert temps(folder) == []


@pytest.mark.skipif(os.name != "posix", reason="the folder is fsynced on POSIX only")
@pytest.mark.parametrize("call, n, code", _FOLDER_SYNC,
                         ids=[f"{c}-{n}" for c, n, _ in _FOLDER_SYNC])
def test_ac_f12_19_a_fault_in_the_folder_fsync_keeps_new(folder, monkeypatch, call, n, code):
    real = getattr(os, call)
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, call, fail_on(real, n, code, close_first=call == "close"))
        write_atomic(folder / NAME, (NEW,), sleep=lambda _s: None)
    assert (folder / NAME).read_bytes() == NEW
    assert temps(folder) == []


def test_ac_f12_19_temp_is_exclusive_private_and_randomly_named(folder, monkeypatch):
    opened = []
    tokens = []
    real_open, real_token = os.open, safefile.secrets.token_hex

    def open_spy(path, flags, mode=0o777, *args, **kwargs):
        opened.append((Path(path).name, flags, mode))
        return real_open(path, flags, mode, *args, **kwargs)

    def token_spy(n):
        tokens.append(n)
        return "0123abcd"

    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "open", open_spy)
        patch.setattr(safefile.secrets, "token_hex", token_spy)
        write_atomic(folder / NAME, (NEW,))
    assert tokens == [4]
    name, flags, mode = opened[0]
    assert name == ".persistent.json.0123abcd.tmp"
    assert flags & os.O_CREAT and flags & os.O_EXCL and flags & os.O_WRONLY
    assert mode == 0o600
    assert (folder / NAME).read_bytes() == NEW


def test_ac_f12_19_replace_is_retried_twice_on_permission_error(folder, monkeypatch):
    slept, sleep = _sleeps()
    real = os.replace
    failures = [0]

    def locked_twice(src, dst):
        if failures[0] < 2:
            failures[0] += 1
            raise PermissionError(errno.EACCES, "locked")
        return real(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "replace", locked_twice)
        stamp = write_atomic(folder / NAME, (NEW,), sleep=sleep)
    assert (folder / NAME).read_bytes() == NEW
    assert slept == [0.05, 0.05]
    assert stamp == Stamp.of(os.stat(folder / NAME))
    assert temps(folder) == []


def test_ac_f12_19_replace_locked_three_times_fails(folder, monkeypatch):
    slept, sleep = _sleeps()

    def locked(_src, _dst):
        raise PermissionError(errno.EACCES, "locked")

    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "replace", locked)
        with pytest.raises(PermissionError):
            write_atomic(folder / NAME, (NEW,), sleep=sleep)
    assert slept == [0.05, 0.05]
    assert (folder / NAME).read_bytes() == OLD
    assert temps(folder) == []


class Killed(BaseException):
    """The process dying mid-write (nothing is cleaned up)."""


def test_ac_f12_19_a_kill_leaves_the_temp_for_the_next_launch(folder, monkeypatch):
    def kill(_fd):
        raise Killed

    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fsync", kill)
        with pytest.raises(Killed):
            write_atomic(folder / NAME, (NEW,))
    assert (folder / NAME).read_bytes() == OLD
    [left] = temps(folder)
    assert safefile.re.fullmatch(r"\.persistent\.json\.[0-9a-f]{8}\.tmp", left)
    st = os.stat(folder / left)
    if os.name == "posix":
        assert stat.S_IMODE(st.st_mode) == 0o600
    assert remove_stale_temps(folder, NAME, now=st.st_mtime + 59) == 0
    assert temps(folder) == [left]
    assert remove_stale_temps(folder, NAME, now=st.st_mtime + 61) == 1
    assert temps(folder) == []
    assert (folder / NAME).read_bytes() == OLD


# --- SEC-F12-06: links and the stamp re-check ----------------------------------------------

@pytest.mark.parametrize("kind", ["file", "dir"])
def test_a_planted_link_at_the_temp_name_is_never_followed(folder, outside, monkeypatch, kind):
    planted = folder / ".persistent.json.deadbeef.tmp"
    if kind == "file":
        symlink(planted, outside / "t")
    else:
        link_dir(planted, outside)
    with monkeypatch.context() as patch:
        patch.setattr(safefile.secrets, "token_hex", lambda _n: "deadbeef")
        # FileExistsError; Windows reports an existing directory entry as access denied.
        with pytest.raises(OSError):
            write_atomic(folder / NAME, (NEW,))
    assert os.listdir(outside) == []
    assert (folder / NAME).read_bytes() == OLD


def test_a_taken_temp_name_is_retried_and_the_other_entry_is_kept(folder):
    planted = folder / ".persistent.json.deadbeef.tmp"
    planted.write_bytes(b"planted")
    tokens = iter(["deadbeef", "deadbeef", "0badf00d"])
    write_atomic(folder / NAME, (NEW,), token=lambda: next(tokens))
    assert (folder / NAME).read_bytes() == NEW
    assert planted.read_bytes() == b"planted"
    assert temps(folder) == [planted.name]


def test_the_stamp_is_checked_again_right_before_the_replace(folder, monkeypatch):
    target = folder / NAME
    expected = Stamp.of(os.lstat(target))
    real_fsync = os.fsync

    def other_copy_writes(fd):
        real_fsync(fd)
        other = folder / "other.tmp"
        other.write_bytes(b'{"format":1,"other":1}')
        os.replace(other, target)

    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fsync", other_copy_writes)
        with pytest.raises(TargetChanged) as caught:
            write_atomic(target, (NEW,), check=True, expected=expected)
    assert target.read_bytes() == b'{"format":1,"other":1}'
    assert caught.value.stamp == Stamp.of(os.lstat(target))
    assert temps(folder) == []


def test_the_stamp_check_passes_and_a_missing_target_is_written(folder):
    target = folder / NAME
    stamp = write_atomic(target, (NEW,), check=True, expected=Stamp.of(os.lstat(target)))
    assert target.read_bytes() == NEW
    target.unlink()
    with pytest.raises(TargetChanged):
        write_atomic(target, (OLD,), check=True, expected=stamp)
    assert not target.exists() and temps(folder) == []
    write_atomic(target, (OLD,), check=True, expected=None)
    assert target.read_bytes() == OLD


def test_mode_is_applied_on_posix(folder):
    if not hasattr(os, "fchmod"):
        pytest.skip("fchmod is POSIX-only")
    write_atomic(folder / NAME, (NEW,), mode=0o640)
    assert stat.S_IMODE(os.stat(folder / NAME).st_mode) == 0o640


# --- SEC-F12-13: the bounded stale-temp scan -----------------------------------------------

class FakeEntry:
    def __init__(self, name: str) -> None:
        self.name = name
        self.path = name

    def stat(self, follow_symlinks=True):
        raise AssertionError("non-matching entries are never examined further")


class FakeScandir:
    """``os.scandir`` over 5,000 entries, counting how many are taken."""

    def __init__(self, _folder) -> None:
        self.taken = 0
        FakeScandir.last = self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def __iter__(self):
        for i in range(5000):
            self.taken += 1
            yield FakeEntry(f"entry{i}.txt")


def test_sec_f12_13_at_most_1000_entries_are_examined(base, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "scandir", FakeScandir)
        assert remove_stale_temps(base, NAME) == 0
    assert FakeScandir.last.taken == 1000


def _old(path: Path, when: float) -> None:
    os.utime(path, (when, when))


def test_sec_f12_13_at_most_16_are_removed(base):
    when = time.time() - 3600
    for i in range(20):
        path = base / f".persistent.json.{i:08x}.tmp"
        path.write_bytes(b"x")
        _old(path, when)
    assert remove_stale_temps(base, NAME) == 16
    assert len(temps(base)) == 4


def test_only_old_regular_files_with_the_exact_name_are_removed(base, outside):
    when = time.time() - 3600
    kept = [".persistent.json.ABCDEF01.tmp", ".persistent.json.abc.tmp",
            ".other.json.deadbeef.tmp", "persistent.json", ".persistent.json.deadbeef.tmp.x"]
    for name in kept:
        (base / name).write_bytes(b"x")
        _old(base / name, when)
    (base / ".persistent.json.0000000d.tmp").mkdir()
    link_target = outside / "keep"
    link_target.write_bytes(b"x")
    old = base / ".persistent.json.0000000a.tmp"
    old.write_bytes(b"x")
    _old(old, when)
    young = base / ".persistent.json.0000000b.tmp"
    young.write_bytes(b"x")
    assert remove_stale_temps(base, NAME) == 1
    assert not old.exists() and young.exists()
    for name in kept:
        assert (base / name).exists(), name
    assert (base / ".persistent.json.0000000d.tmp").is_dir()
    assert link_target.exists()


def test_a_matching_link_is_never_removed_or_followed(base, outside):
    (outside / "f").write_bytes(b"x")
    link = base / ".persistent.json.0000000c.tmp"
    link_dir(link, outside)
    assert remove_stale_temps(base, NAME, now=time.time() + 3600) == 0
    assert os.path.lexists(link)
    assert os.listdir(outside) == ["f"]


def test_a_missing_folder_removes_nothing(base):
    assert remove_stale_temps(base / "nope", NAME) == 0
