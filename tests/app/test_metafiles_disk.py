"""F31 s4 — the disk files port (``engine/app/metafiles.py``) on a temp game folder (F31
``06-acceptance.md`` AC-F31-18, 19, 20, 21, 25; ``04`` §6.3, §6.4, §6.7; ``05`` groups B, C, E).

**Disk D** (06 §0.3): ``install_metafiles`` on a small stand-in App (router, ``GamePaths``,
F11's ``Writer``: synchronous unless "threaded") with the game copy at
``tmp_path/aiko/game``. Most rows call the port the way ``run_file`` does and ``pump()`` after
each call, as the windowed handler does; AC-F31-21's ``caps/`` row runs the real interpreter.
FS faults are patched ``core.safefile`` calls. Link rows run where the OS allows: symlinks need
the privilege on Windows, junctions are Windows only, FIFOs and ``0o555`` POSIX only. Not here:
the Windows over-260-character temp path and the ``slow`` 10,000-junk-file row (06 §0.5).
"""

import errno
import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.app.dispatch import CommandRouter
from engine.app.metafiles import DiskFolder, install_metafiles
from engine.core import safefile
from engine.core.constants import META_CHANGES_MAX, META_IN_FLIGHT_MAX, META_W198_MAX
from engine.core.logsetup import get_logger
from engine.core.paths import GamePaths
from engine.meta.files import MetaFolder
from engine.persist.writer import Writer
from engine.runtime.commands import Advance, MetaDelete, MetaWrite
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.runtime.images import ImageSource
from engine.runtime.metafiles import ReadAnswer
from engine.script.messages import format_message
from tests.runtime.effects_story import take_all
from tests.runtime.metafiles_story import HANA, fixture

WINDOWS = sys.platform == "win32"
WALK = frozenset({"hana.chr", "read_me.txt", "gone.chr", "answer.txt"})
NOTE = "Line one\nNoteMark7 {b}x{/b} {{".encode("utf-8")


class Disk:
    """Disk D: the port ``install_metafiles`` builds, over ``tmp_path/aiko/game``."""

    def __init__(self, tmp_path: Path, names=WALK, *, threaded: bool = False,
                 originals: dict[str, bytes] | None = None, interp=None) -> None:
        self.game = (tmp_path / "aiko" / "game")
        (self.game / "files").mkdir(parents=True, exist_ok=True)
        for name, data in (originals if originals is not None else {"hana.chr": HANA}).items():
            (self.game / "files" / name).write_bytes(data)
        self.game = self.game.resolve()
        self.root = self.game / "characters"
        self.outside = tmp_path / "outside"
        self.outside.mkdir(exist_ok=True)
        self.writer = Writer(threaded=threaded, sleep=lambda s: None)
        self.jobs: list[object] = []
        real_submit = self.writer._submit

        def submit(client, job):
            self.jobs.append(job)
            real_submit(client, job)
        self.writer._submit = submit                       # type: ignore[method-assign]
        hooks: list = []
        self.app = SimpleNamespace(router=CommandRouter(), paths=GamePaths(self.game),
                                   writer=self.writer, dev=True, metafiles=None, hooks=hooks,
                                   add_shutdown=hooks.append)
        self.interp = interp if interp is not None else SimpleNamespace(
            program=SimpleNamespace(meta_files=frozenset(names)), log=get_logger("runtime"),
            files=None)
        self.port: DiskFolder = install_metafiles(self.app, self.interp)    # type: ignore
        assert self.port is not None and self.interp.files.port is self.port

    # The way run_file calls the port, then the handler's pump().
    def write(self, name: str, text: bytes | None = None) -> None:
        self.port.write(name, text)
        self.app.router.dispatch(MetaWrite(name))

    def delete(self, name: str) -> None:
        self.port.delete(name)
        self.app.router.dispatch(MetaDelete(name))

    def exists(self, name: str) -> bool:
        return self.port.exists(name)

    def read(self, name: str) -> ReadAnswer:
        return self.port.read(name)

    def walk(self) -> list[object]:
        """``walk/``'s file lines 6–21 in order; the checks' answers."""
        self.write("hana.chr")
        self.write("read_me.txt", NOTE)
        out: list[object] = [self.exists("hana.chr"), self.read("read_me.txt")]
        self.delete("hana.chr")
        self.delete("gone.chr")
        out += [self.exists("hana.chr"), self.read("answer.txt"), self.exists("hana.chr")]
        return out

    def drain(self, left: int = 0) -> None:
        """Wait (threaded) until at most ``left`` meta jobs are in flight."""
        until = time.monotonic() + 5
        while self.port.client.in_flight > left:
            assert time.monotonic() < until, "the writer never finished"
            time.sleep(0.002)


def warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def w198(form: str, verb: str, name: str) -> str:
    return format_message("W198", (form, verb, name))


W196 = format_message("W196")
W197 = format_message("W197")


def tree(folder: Path) -> dict[str, bytes | None]:
    """Every entry under ``folder`` (no link followed) with a regular file's bytes."""
    out: dict[str, bytes | None] = {}
    if not folder.exists():
        return out
    for dirpath, dirnames, filenames in os.walk(folder):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            out[path.relative_to(folder).as_posix()] = (
                path.read_bytes() if path.is_file() and not path.is_symlink() else None)
    return out


def symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need a privilege on this machine")


def junction(link: Path, target: Path) -> None:
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


@pytest.fixture
def faults(monkeypatch):
    """F12's FS faults: ``fail[name] = errno`` makes ``write_atomic`` raise for that target
    name; ``gate`` (a semaphore, when set) holds each write until released; ``threads``
    records the thread of every ``write_atomic`` and ``remove_file``."""
    ctl = SimpleNamespace(fail={}, gate=None, threads=[], calls=[])
    real_write, real_remove = safefile.write_atomic, safefile.remove_file

    def write_atomic(target, pieces, **kw):
        ctl.threads.append(threading.get_ident())
        ctl.calls.append(Path(target).name)
        if ctl.gate is not None:
            assert ctl.gate.acquire(timeout=5)
        code = ctl.fail.get(Path(target).name)
        if code is not None:
            raise OSError(code, f"{target} NoteMark7")
        return real_write(target, pieces, **kw)

    def remove_file(path):
        ctl.threads.append(threading.get_ident())
        return real_remove(path)

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)
    monkeypatch.setattr(safefile, "remove_file", remove_file)
    return ctl


# --- AC-F31-18 ----------------------------------------------------------------------------------

def test_ac_f31_18_read_your_own_writes_on_disk(tmp_path, faults, caplog):
    names = {"note.txt", "big.txt", "fail.txt", "twice.txt"}
    disk = Disk(tmp_path, names, threaded=True)
    disk.root.mkdir()
    (disk.root / "fail.txt").write_bytes(b"old")
    faults.gate = threading.Semaphore(0)
    faults.fail["fail.txt"] = errno.ENOSPC
    me = threading.get_ident()
    with caplog.at_level(logging.DEBUG, logger="vn"):
        disk.write("note.txt", b"hi")
        assert disk.exists("note.txt") is True
        assert disk.read("note.txt") == ReadAnswer(b"hi", None)
        assert not (disk.root / "note.txt").exists()                  # nothing on disk yet
        disk.delete("note.txt")
        assert disk.exists("note.txt") is False
        assert disk.read("note.txt") == ReadAnswer(None, None)
        big = ("é" * 8_193).encode("utf-8")
        assert len(big) == 16_386
        disk.write("big.txt", big)
        assert disk.read("big.txt") == ReadAnswer(None, "large")
        disk.write("fail.txt", b"new")
        assert disk.read("fail.txt") == ReadAnswer(b"new", None)
        faults.gate.release(10)
        disk.drain()
        disk.port.pump()
        assert warnings(caplog) == [w198("full", "write", "fail.txt")]
        assert disk.port._pending == {}                               # overlay dropped
        assert disk.read("fail.txt") == ReadAnswer(b"old", None)      # the disk, old intact
        assert disk.exists("note.txt") is False and (disk.root / "big.txt").stat().st_size == 16_386

        disk.write("twice.txt", b"one")
        disk.write("twice.txt", b"two")
        faults.gate.release(1)
        disk.drain(left=1)
        disk.port.pump()                                              # the first result
        assert disk.read("twice.txt") == ReadAnswer(b"two", None)
        faults.gate.release(10)
        disk.drain()
        assert disk.read("twice.txt") == ReadAnswer(b"two", None)
    assert faults.threads and me not in faults.threads               # writer thread only
    disk.writer.stop(disk.writer.now() + 5)


# --- AC-F31-19 ----------------------------------------------------------------------------------

def _b_missing(disk, caplog):
    assert disk.exists("hana.chr") is False and warnings(caplog) == []
    disk.walk()
    assert sorted(p.name for p in disk.game.iterdir()) == ["characters", "files"]
    assert tree(disk.root) == {"read_me.txt": NOTE}
    fresh = Disk(disk.game.parent.parent / "second")
    fresh.delete("hana.chr")
    assert not fresh.root.exists() and fresh.jobs and warnings(caplog) == []


def _b_not_a_folder(make):
    def row(disk, caplog):
        target = disk.outside / "Documents"
        target.mkdir()
        (target / "mine.txt").write_bytes(b"private")
        make(disk, target)
        before = tree(disk.outside)
        answers = disk.walk()
        assert answers == [False, ReadAnswer(None, None), False, ReadAnswer(None, None), False]
        assert warnings(caplog) == [W196] and disk.jobs == []
        assert tree(disk.outside) == before
    return row


def _make_file(disk, target):
    disk.root.write_bytes(b"not a folder")


def _make_file_link(disk, target):
    symlink_or_skip(disk.root, target / "mine.txt")


def _make_dir_link(disk, target):
    symlink_or_skip(disk.root, target, directory=True)


def _make_junction(disk, target):
    junction(disk.root, target)


def _b_swapped(disk, caplog):
    target = disk.outside / "Documents"
    target.mkdir()
    disk.write("hana.chr")
    disk.write("read_me.txt", NOTE)
    jobs = len(disk.jobs)
    (disk.root).rename(disk.game / "old")
    if WINDOWS:
        junction(disk.root, target)
    else:
        symlink_or_skip(disk.root, target, directory=True)
    disk.delete("hana.chr")                                           # line 12
    assert warnings(caplog) == [W196]
    disk.delete("gone.chr")
    assert disk.exists("hana.chr") is False and len(disk.jobs) == jobs
    assert tree(target) == {}


def _b_read_only(disk, caplog, monkeypatch=None):
    disk.root.mkdir()
    (disk.root / "read_me.txt").write_bytes(b"there")

    def refuse(target, make_token):
        raise PermissionError(errno.EACCES, f"{target} NoteMark7")
    disk.mp.setattr(safefile, "_create_temp", refuse)
    disk.write("hana.chr")
    assert warnings(caplog) == [W197]
    jobs = len(disk.jobs)
    disk.write("read_me.txt", NOTE)
    disk.delete("hana.chr")
    assert len(disk.jobs) == jobs and warnings(caplog) == [W197]
    assert disk.exists("read_me.txt") is True


def _b_unreadable_root(disk, caplog):
    disk.root.mkdir()
    real = os.lstat
    root = os.path.normcase(str(disk.root))

    def lstat(path, *a, **kw):
        if os.path.normcase(os.fspath(path)) == root:
            raise PermissionError(errno.EACCES, "denied")
        return real(path, *a, **kw)
    disk.mp.setattr(os, "lstat", lstat)
    assert disk.exists("hana.chr") is False and disk.read("answer.txt") == ReadAnswer(None, None)
    assert warnings(caplog) == []
    disk.write("hana.chr")
    disk.delete("gone.chr")
    assert warnings(caplog) == [w198("other", "write", "hana.chr"),
                                w198("other", "delete", "gone.chr")]


def _b_game_renamed(disk, caplog):
    disk.write("hana.chr")
    disk.write("read_me.txt", NOTE)                                   # line 7
    moved = disk.game.parent / "moved"
    disk.game.rename(moved)
    disk.write("read_me.txt", b"again")
    disk.write("hana.chr", b"x")
    found = warnings(caplog)
    assert found and W197 not in found and all(t.startswith("couldn't write") for t in found)
    assert not disk.game.exists()                                     # nothing created


B_ROWS = {
    "missing": _b_missing,
    "a regular file": _b_not_a_folder(_make_file),
    "a file symlink": _b_not_a_folder(_make_file_link),
    "a directory symlink": _b_not_a_folder(_make_dir_link),
    "a junction": _b_not_a_folder(_make_junction),
    "swapped for a junction before line 12": _b_swapped,
    "read-only (temp create refused)": _b_read_only,
    "lstat(root) refused": _b_unreadable_root,
    "the game folder renamed away": _b_game_renamed,
}


@pytest.mark.parametrize("row", list(B_ROWS))
def test_ac_f31_19_group_b_the_folder(row, tmp_path, caplog, monkeypatch):
    if row == "a junction" and not WINDOWS:
        pytest.skip("junctions are Windows only")
    disk = Disk(tmp_path)
    disk.mp = monkeypatch                                             # type: ignore[attr-defined]
    with caplog.at_level(logging.DEBUG, logger="vn"):
        B_ROWS[row](disk, caplog)
    assert all(job.release is False for job in disk.jobs)            # every run's dev rule


# --- AC-F31-20 ----------------------------------------------------------------------------------

def _c_folder(disk, verb):
    (disk.root / "hana.chr").mkdir()
    (disk.root / "hana.chr" / "keep.txt").write_bytes(b"keep")
    return {"warn": [w198("folder_at_name", verb, "hana.chr")],
            "check": lambda: (disk.root / "hana.chr" / "keep.txt").read_bytes() == b"keep"}


def _c_dir_link(disk, verb):
    target = disk.outside / "inside"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"keep")
    if WINDOWS:
        junction(disk.root / "hana.chr", target)
    else:
        symlink_or_skip(disk.root / "hana.chr", target, directory=True)
    entry = disk.root / "hana.chr"
    if verb == "delete":
        return {"warn": [], "check": lambda: not os.path.lexists(entry)
                and (target / "keep.txt").read_bytes() == b"keep"}
    if WINDOWS:
        return {"warn": [w198("folder_at_name", verb, "hana.chr")],
                "check": lambda: os.path.lexists(entry) and tree(target) == {"keep.txt": b"keep"}}
    return {"warn": [], "check": lambda: entry.is_file() and not entry.is_symlink()
            and tree(target) == {"keep.txt": b"keep"}}                 # POSIX: replaced (G3)


def _c_file_link(disk, verb):
    secret = disk.outside / "secret.txt"
    secret.write_bytes(b"secret")
    symlink_or_skip(disk.root / "hana.chr", secret)
    entry = disk.root / "hana.chr"
    want = ((lambda: entry.read_bytes() == b"t" and not entry.is_symlink()) if verb == "write"
            else (lambda: not os.path.lexists(entry)))
    return {"warn": [], "check": lambda: want() and secret.read_bytes() == b"secret"}


def _c_hard_link(disk, verb):
    secret = disk.outside / "secret.txt"
    secret.write_bytes(b"secret")
    os.link(secret, disk.root / "hana.chr")
    entry = disk.root / "hana.chr"
    want = ((lambda: entry.read_bytes() == b"t") if verb == "write"
            else (lambda: not entry.exists()))
    return {"warn": [], "check": lambda: want() and secret.read_bytes() == b"secret"}


def _c_fifo(disk, verb):
    os.mkfifo(disk.root / "hana.chr")
    entry = disk.root / "hana.chr"
    if verb == "write":
        return {"warn": [], "check": lambda: entry.read_bytes() == b"t"}
    return {"warn": [w198("folder_at_name", verb, "hana.chr")], "check": lambda: True}


def _c_temp_entry(disk, verb):
    planted = disk.root / ".hana.chr.0000abcd.tmp"
    planted.mkdir()
    entry = disk.root / "hana.chr"
    if verb == "delete":
        entry.write_bytes(b"old")
    want = ((lambda: entry.read_bytes() == b"t") if verb == "write"
            else (lambda: not entry.exists()))
    return {"warn": [], "check": lambda: want() and planted.is_dir()}


def _c_locked(disk, verb):
    (disk.root / "hana.chr").write_bytes(b"old")
    tries = []

    def replace(src, dst):
        tries.append(dst)
        raise PermissionError(errno.EACCES, f"{dst} NoteMark7")
    disk.mp.setattr(os, "replace", replace)
    return {"warn": [w198("other", verb, "hana.chr")],
            "check": lambda: len(tries) == 3 and (disk.root / "hana.chr").read_bytes() == b"old"}


def _c_unwritable(disk, verb):
    (disk.root / "hana.chr").write_bytes(b"old")

    def refuse(target, make_token):
        raise PermissionError(errno.EACCES, "denied")
    disk.mp.setattr(safefile, "_create_temp", refuse)
    first = disk.variant == "first"
    want = [W197] if first and not WINDOWS else (
        [w198("other", verb, "hana.chr")] if WINDOWS else [w198("permission", verb, "hana.chr")])
    return {"warn": want, "check": lambda: (disk.root / "hana.chr").read_bytes() == b"old"}


def _c_full(disk, verb):
    (disk.root / "hana.chr").write_bytes(b"old")
    disk.faults.fail["hana.chr"] = errno.ENOSPC
    return {"warn": [w198("full", verb, "hana.chr")],
            "check": lambda: (disk.root / "hana.chr").read_bytes() == b"old"}


C_ROWS = [  # (row, setup, verbs, where)
    ("a real folder", _c_folder, ("write", "delete"), "all"),
    ("a directory link", _c_dir_link, ("write", "delete"), "all"),
    ("a file symlink", _c_file_link, ("write", "delete"), "all"),
    ("a hard link", _c_hard_link, ("write", "delete"), "all"),
    ("a FIFO", _c_fifo, ("write", "delete"), "posix"),
    ("a folder at its temp name", _c_temp_entry, ("write", "delete"), "all"),
    ("locked", _c_locked, ("write",), "windows"),
    ("an unwritable folder", _c_unwritable, ("write",), "all"),
    ("ENOSPC", _c_full, ("write",), "all"),
]
C_CASES = [(row, verb, variant) for row, _, verbs, _ in C_ROWS for verb in verbs
           for variant in ("first", "after")]


@pytest.mark.parametrize("row,verb,variant", C_CASES)
def test_ac_f31_20_group_c_the_entry_at_a_name(row, verb, variant, tmp_path, caplog,
                                                monkeypatch, faults):
    _, setup, _, where = next(r for r in C_ROWS if r[0] == row)
    if where == "windows" and not WINDOWS or where == "posix" and WINDOWS:
        pytest.skip(f"{where} only")
    disk = Disk(tmp_path, {"hana.chr", "read_me.txt"})
    disk.mp, disk.faults, disk.variant = monkeypatch, faults, variant  # type: ignore[attr-defined]
    disk.root.mkdir()
    if variant == "after":
        disk.write("read_me.txt", b"x")
    expect = setup(disk, verb)
    before = tree(disk.outside)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        disk.write("hana.chr", b"t") if verb == "write" else disk.delete("hana.chr")
    assert warnings(caplog) == expect["warn"]
    assert expect["check"]()
    assert tree(disk.outside) == before


def test_ac_f31_20_stale_temps(tmp_path):
    """AC-F31-20's last paragraph: the session's first change cleans at most 16 old temps
    of listed names; a second change cleans none."""
    disk = Disk(tmp_path, {"hana.chr", "read_me.txt"})
    disk.root.mkdir()
    old = time.time() - 120
    temps = [disk.root / f".hana.chr.{n:08x}.tmp" for n in range(20)]
    for path in temps:
        path.write_bytes(b"t")
        os.utime(path, (old, old))
    young = disk.root / ".hana.chr.ffffffff.tmp"
    young.write_bytes(b"y")
    other = disk.root / ".other.chr.00000001.tmp"
    other.write_bytes(b"o")
    os.utime(other, (old, old))
    disk.write("read_me.txt", b"x")
    assert sum(not p.exists() for p in temps) == 16 and young.exists() and other.exists()
    disk.write("read_me.txt", b"y")
    assert sum(not p.exists() for p in temps) == 16


# --- AC-F31-21 ----------------------------------------------------------------------------------

def test_ac_f31_21_volume_on_disk(tmp_path, faults, caplog, monkeypatch):
    # Threaded writer blocked: 9 change lines in a row → 8 jobs, the 9th W198 busy.
    disk = Disk(tmp_path / "busy", threaded=True)
    faults.gate = threading.Semaphore(0)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        for _ in range(META_IN_FLIGHT_MAX + 1):
            disk.write("read_me.txt", b"x")
        assert len(disk.jobs) == META_IN_FLIGHT_MAX
        assert warnings(caplog) == [w198("busy", "write", "read_me.txt")]
        faults.gate.release(100)
        disk.drain()
        disk.write("read_me.txt", b"y")
        disk.drain()
        assert len(disk.jobs) == META_IN_FLIGHT_MAX + 1
    disk.writer.stop(disk.writer.now() + 5)
    faults.gate = None
    caplog.clear()

    # Synchronous: every write fails EACCES after one success → 20 W198, then DEBUG only.
    disk = Disk(tmp_path / "eacces")
    with caplog.at_level(logging.DEBUG, logger="vn"):
        disk.write("hana.chr", b"ok")
        faults.fail["read_me.txt"] = errno.EACCES
        for _ in range(30):
            disk.write("read_me.txt", b"x")
    assert len(warnings(caplog)) == META_W198_MAX
    assert sum(r.levelno == logging.DEBUG and r.getMessage().startswith("couldn't write")
               for r in caplog.records) == 30 - META_W198_MAX
    assert len(disk.jobs) == 31 and not disk.port.read_only
    caplog.clear()

    # caps/: 256 jobs; one W199 (the runtime's cap over the disk port).
    program = fixture("caps")
    launch = run_launch(program, images=ImageSource.from_files(()))
    interp = Interpreter(program, launch.namespace)
    disk = Disk(tmp_path / "caps", interp=interp)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        interp.new_game(42)
        for _ in range(400):
            interp.run(100_000)
            for command in take_all(interp):
                if type(command) in (MetaWrite, MetaDelete):
                    disk.app.router.dispatch(command)
            current = interp.current
            if current is not None and getattr(current, "text", "") == "End":
                break
            if current is not None:
                interp.post(Advance(current.sid))
    assert getattr(interp.current, "text", "") == "End"
    assert len(disk.jobs) == META_CHANGES_MAX
    found = warnings(caplog)
    assert len(found) == 1 and found[0].endswith(format_message("W199")), found
    assert interp.files.port is disk.port and interp.files.changes == META_CHANGES_MAX


# --- AC-F31-25 ----------------------------------------------------------------------------------

def test_ac_f31_25_reload_keeps_the_session_and_never_raises(tmp_path, faults, caplog,
                                                             monkeypatch):
    disk = Disk(tmp_path, {"old.txt"}, threaded=True)
    port = disk.port
    files, client = disk.interp.files, port.client
    faults.gate = threading.Semaphore(0)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        disk.write("old.txt", b"first")                               # a success first
        faults.gate.release(1)
        disk.drain()
        faults.fail["old.txt"] = errno.EACCES
        disk.write("old.txt", b"o")                                   # pending; it will fail
        files.changes += 2
        port.set_folder(MetaFolder(disk.root, frozenset({"new.txt"})))
        faults.gate.release(5)
        disk.drain()
        port.pump()                                                   # raises nothing
        found = warnings(caplog)
        assert len(found) == 1 and found[0].startswith(
            "couldn't write <game>/characters/old.txt"), found
        # A second install (an F39-style reload) keeps the client and the session.
        disk.interp.program = SimpleNamespace(meta_files=frozenset({"new.txt"}))
        disk.interp.files = None
        again = install_metafiles(disk.app, disk.interp)
        assert again is port and port.client is client and disk.interp.files is files
        assert files.changes == 2 and port.usable and not port.read_only
        assert list(disk.writer._clients) == ["meta"]
        caplog.clear()

        # entry_kind raising ValueError: W198 other, nothing raised.
        faults.fail["new.txt"] = errno.EIO
        monkeypatch.setattr(MetaFolder, "entry_kind",
                            lambda self, name: (_ for _ in ()).throw(ValueError("slip")))
        disk.write("new.txt", b"n")
        faults.gate.release(5)
        disk.drain()
        port.pump()
        assert warnings(caplog) == [w198("other", "write", "new.txt")]
    disk.writer.stop(disk.writer.now() + 5)
