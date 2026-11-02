"""The launch read (F12 checklist step 6; ``04`` §7.4; SEC-F12-03, -06, -09, -13):
``app/persistence.py``'s ``open_for_launch`` and ``install_persistence`` on a real
``<game>/persistent`` folder. AC-F12-28 (group D), AC-F12-29, the launch rows of AC-F12-36
(group F) and AC-F12-41 (W50–W55 texts at launch), and the launch part of AC-F12-42.

A session is the launch read, then ``PersistentSync`` on a synchronous ``Writer``
(Harness Y's), with changes made on the store directly: ``$ persistent.x = 1`` needs the
story namespace (F12 step 3a), so ``store.set("x", 1)`` stands in for it. Faults are
injected in ``engine.core.safefile``'s ``os`` calls inside ``MonkeyPatch.context()``."""

import errno
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.app.persistence import install_persistence, open_for_launch
from engine.core import safefile
from engine.persist import limits
from engine.persist.fileformat import Outcome
from engine.persist.location import BAD_NAME, FILE_NAME
from engine.persist.sync import MEMORY, READ_ONLY, WRITABLE
from engine.persist.texts import (NO_ID_TEXT, OFF_TEXT, bad_file_text, newer_file_text,
                                  save_failed_text)
from engine.persist.writer import FOLDER_IS_LINK, NO_PERMISSION, Writer
from engine.runtime.persistent import Missing, dropped_text, scheme_text
from tests.persist.helpers import FakeProgram
from tests.persist.sync_support import dumps, sid
from tests.persist.writer_support import (base, game, link_dir, outside,  # noqa: F401
                                          temps, tree, writers)

FILE = "<game>/persistent/persistent.json"
GOOD = {"format": 1, "identity_scheme": 1, "values": {"festivals": 2}, "seen": {},
        "chosen": {}, "unlocks": {}}


@pytest.fixture
def folder(game) -> Path:
    return game / "persistent"


def setup(folder: Path, data: bytes | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    if data is not None:
        (folder / FILE_NAME).write_bytes(data)
    return folder / FILE_NAME


class Session:
    """One launch and its sync (synchronous writer)."""

    def __init__(self, game: Path, *, program=None, release: bool = False,
                 app_id: str | None = None, off: bool = False) -> None:
        self.program = program if program is not None else FakeProgram()
        self.launch = open_for_launch(self.program, game_root=game, release=release,
                                      app_id=app_id, off=off).run()
        self.app = SimpleNamespace(writer=Writer(threaded=False), persist=None)
        self.sync = install_persistence(self.app, self.launch)
        self.store = self.sync.store

    def play(self, **values) -> None:
        """Changes, then quit (``close``)."""
        for name, value in values.items():
            self.store.set(name, value)
        self.sync.close(until=self.app.writer.quit_deadline())


def disk(path: Path) -> dict:
    return json.loads(path.read_bytes())


# --- The modes ------------------------------------------------------------------------------

def test_a_missing_file_gives_fresh_writable_data(game, folder, warnings):
    s = Session(game)
    assert s.launch.mode is WRITABLE and s.launch.stamp is None and s.launch.done
    assert s.app.persist is s.sync and s.store.display == FILE
    assert folder.is_dir() and list(folder.iterdir()) == []      # nothing written yet
    s.play(x=1)
    assert disk(folder / FILE_NAME)["values"] == {"x": 1}
    assert warnings == []


def test_a_good_file_is_read_and_kept_writable(game, folder, warnings):
    path = setup(folder, dumps(GOOD))
    s = Session(game)
    assert s.launch.mode is WRITABLE and s.launch.outcome.kind is Outcome.OK
    assert s.launch.stamp == safefile.current_stamp(path)
    assert s.store.peek("festivals") == 2
    s.play(x=1)
    assert disk(path)["values"] == {"festivals": 2, "x": 1}
    assert warnings == []


def test_the_read_is_stepped_and_not_done_before_its_steps(game, folder):
    """``open_for_launch`` only opens the read; the ``ReadJob`` runs in the load screen's
    slices (AC-F12-31's count part: a 120,000-sid file takes ≥ 3 seen steps)."""
    seen = {f"l{i}": " ".join(f"{i * 1000 + k:012x}" for k in range(1000)) for i in range(120)}
    setup(folder, dumps({**GOOD, "seen": seen}))
    launch = open_for_launch(FakeProgram(), game_root=game, release=False, app_id=None)
    assert not launch.done and launch.job is not None
    job = launch.job
    clock = iter(range(10_000)).__next__
    assert launch.run_for(0, clock, at_least_one=True) is False   # one step, then out of time
    assert job.steps == 1
    assert launch.run_for(0, clock, at_least_one=False) is False and job.steps == 1
    launch.run()
    assert launch.done and launch.mode is WRITABLE
    assert job.max_step_items <= limits.READ_STEP_KEYS and job.steps >= 3
    assert launch.store.record_total("seen") == 120_000


def test_no_persistent_touches_no_file(game, folder, warnings, caplog, monkeypatch):
    setup(folder, dumps(GOOD))
    before = tree(game)
    calls = []
    for name in ("open", "lstat", "mkdir", "scandir", "stat"):
        real = getattr(safefile.os, name)
        monkeypatch.setattr(safefile.os, name,
                            lambda *a, _n=name, _r=real, **k: calls.append(_n) or _r(*a, **k))
    s = Session(game, off=True)
    s.play(x=1)
    assert calls == []
    assert s.launch.mode is MEMORY and s.sync.mode is MEMORY
    assert s.store.peek("festivals") is Missing
    assert tree(game) == before
    assert [m for c, m in warnings if m == OFF_TEXT] == [OFF_TEXT]


def test_release_without_an_id_is_w53_and_touches_nothing(game, user_roots, warnings,
                                                          monkeypatch):
    calls = []
    for name in ("open", "lstat", "mkdir", "makedirs", "scandir"):
        real = getattr(safefile.os, name)
        monkeypatch.setattr(safefile.os, name,
                            lambda *a, _n=name, _r=real, **k: calls.append(_n) or _r(*a, **k))
    s = Session(game, release=True, app_id=None)
    s.play(x=1)
    assert calls == []
    assert s.launch.mode is MEMORY and s.store.get("x") == 1
    assert warnings.of("W53") == [NO_ID_TEXT]
    assert not (game / "persistent").exists()
    assert list(user_roots.appdata.iterdir()) == []


def test_release_with_an_id_uses_the_user_data_folder(game, user_roots, warnings):
    s = Session(game, release=True, app_id="paper-lanterns")
    s.play(x=1)
    from engine.core.paths import user_data_dir
    path = user_data_dir("paper-lanterns") / "persistent" / FILE_NAME
    assert disk(path)["values"] == {"x": 1}
    assert not (game / "persistent").exists() and warnings == []
    if sys.platform == "win32":
        assert s.store.display == ("%APPDATA%\\vn-engine\\paper-lanterns\\persistent\\"
                                   "persistent.json")


# --- AC-F12-28 — group D: a damaged file is never lost ----------------------------------------

W50_KEPT = bad_file_text(FILE, "not valid JSON", kept=True)


def test_ac28_bad_json_is_kept_and_a_new_file_written(game, folder, warnings):
    path = setup(folder, b"{")
    s = Session(game)
    assert warnings.of("W50") == [W50_KEPT]
    assert W50_KEPT == ("persistent data in <game>/persistent/persistent.json couldn't be used "
                        "(not valid JSON), so this game starts with fresh persistent data. The "
                        "old file was kept as persistent.bad.json.")
    assert (folder / BAD_NAME).read_bytes() == b"{" and not path.exists()
    s.play(x=1)
    assert disk(path)["values"] == {"x": 1}
    assert sorted(os.listdir(folder)) == [BAD_NAME, FILE_NAME]
    assert [n.code for n in s.sync.take_notices()] == ["W50"]


def test_ac28_an_older_bad_file_is_replaced(game, folder, warnings):
    setup(folder, b"{")
    (folder / BAD_NAME).write_bytes(b"old")
    Session(game).play(x=1)
    assert (folder / BAD_NAME).read_bytes() == b"{"
    assert sorted(os.listdir(folder)) == [BAD_NAME, FILE_NAME]


def _read_only_row(game, folder, warnings, reason="not valid JSON"):
    s = Session(game)
    assert s.launch.mode is READ_ONLY
    s.play(x=1)
    w50 = warnings.of("W50")
    assert w50 == [bad_file_text(FILE, reason, kept=False)]
    assert BAD_NAME not in w50[0]                       # G10: no copy claimed
    assert s.store.get("x") == 1                        # the game goes on in memory
    return s


def test_ac28_a_bad_file_that_cant_be_moved_is_never_overwritten(game, folder, warnings):
    path = setup(folder, b"{")
    (folder / BAD_NAME).mkdir()
    _read_only_row(game, folder, warnings)
    assert path.read_bytes() == b"{" and (folder / BAD_NAME).is_dir()
    assert temps(folder) == []


def test_ac28_a_bad_file_link_is_replaced_not_followed(game, folder, outside, warnings):
    setup(folder, b"{")
    target = outside / "b"
    target.write_bytes(b"outside")
    try:
        os.symlink(target, folder / BAD_NAME)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not permitted here: {exc}")
    Session(game).play(x=1)
    assert (folder / BAD_NAME).read_bytes() == b"{" and not (folder / BAD_NAME).is_symlink()
    assert target.read_bytes() == b"outside"


@pytest.mark.skipif(sys.platform != "win32", reason="share modes are Windows-only")
def test_ac28_a_file_held_without_share_delete_is_never_overwritten(game, folder, warnings):
    import ctypes
    from ctypes import wintypes

    path = setup(folder, b"{")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.HANDLE]
    generic_read, share_read_write, open_existing = 0x80000000, 0x1 | 0x2, 3
    handle = kernel32.CreateFileW(str(path), generic_read, share_read_write, None,
                                  open_existing, 0x80, None)
    assert handle not in (None, wintypes.HANDLE(-1).value)
    try:
        _read_only_row(game, folder, warnings)
    finally:
        kernel32.CloseHandle(handle)
    assert path.read_bytes() == b"{" and not (folder / BAD_NAME).exists()


def test_ac28_a_read_error_is_unreadable_with_no_rename(game, folder, warnings):
    path = setup(folder, dumps(GOOD))
    real_read = safefile.os.read

    def failing_read(fd, n):
        raise OSError(errno.EIO, "I/O error")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(safefile.os, "read", failing_read)
        s = Session(game)
    assert safefile.os.read is real_read
    assert s.launch.mode is READ_ONLY and s.store.peek("festivals") is Missing
    s.play(x=1)
    text = warnings.of("W50")
    assert text == [bad_file_text(FILE, "couldn't be read", kept=False)]
    assert text[0].startswith(f"persistent data in {FILE} couldn't be used (couldn't be read)")
    assert BAD_NAME not in text[0]
    assert path.read_bytes() == dumps(GOOD) and not (folder / BAD_NAME).exists()


def test_ac28_a_directory_in_the_files_place_is_moved_aside(game, folder, warnings):
    path = folder / FILE_NAME
    (path / "inner").mkdir(parents=True)
    s = Session(game)
    assert warnings.of("W50") == [bad_file_text(FILE, "not a regular file", kept=True)]
    s.play(x=1)
    assert (folder / BAD_NAME / "inner").is_dir()
    assert path.is_file() and disk(path)["values"] == {"x": 1}


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_ac28_a_fifo_in_the_files_place_is_moved_aside(game, folder, warnings):
    setup(folder)
    os.mkfifo(folder / FILE_NAME)
    s = Session(game)
    assert warnings.of("W50") == [bad_file_text(FILE, "not a regular file", kept=True)]
    s.play(x=1)
    assert (folder / FILE_NAME).is_file()


def test_ac28_the_bad_file_is_never_opened(game, folder, warnings, monkeypatch):
    setup(folder, b"{")
    (folder / BAD_NAME).write_bytes(dumps({**GOOD, "values": {"secret": 7}}))
    opened = []
    real = safefile.read_regular
    monkeypatch.setattr(safefile, "read_regular",
                        lambda path, n: opened.append(Path(path).name) or real(path, n))
    real_open = safefile.os.open
    monkeypatch.setattr(safefile.os, "open",
                        lambda p, *a, **k: opened.append(Path(p).name) or real_open(p, *a, **k))
    s = Session(game)
    s.play(x=1)
    assert BAD_NAME not in opened
    assert s.store.peek("secret") is Missing and "secret" not in disk(folder / FILE_NAME)["values"]


# --- AC-F12-29 — newer files are never changed ------------------------------------------------

@pytest.mark.parametrize("extra", [False, True], ids=["format-2", "format-2-extra-key"])
def test_ac29_a_newer_file_is_never_changed(game, folder, warnings, monkeypatch, extra):
    newer = {**GOOD, "format": 2}
    if extra:
        newer["checksums"] = {"a": 1}
    data = dumps(newer)
    path = setup(folder, data)
    excl = []
    real_open = safefile.os.open
    monkeypatch.setattr(safefile.os, "open", lambda p, flags, *a, **k: (
        excl.append(p) if flags & os.O_EXCL else None) or real_open(p, flags, *a, **k))
    s = Session(game)
    assert s.launch.mode is READ_ONLY
    s.store.set("x", 1)
    s.store.clear()
    s.store.set("x", 1)
    s.sync.flush_soon()
    s.sync.update(10.0)
    assert s.sync.flush_now() is False
    s.sync.close()
    assert s.store.get("x") == 1 and s.store.peek("festivals") is Missing
    assert warnings.of("W51") == [newer_file_text(FILE)]
    assert newer_file_text(FILE) == (
        "persistent data in <game>/persistent/persistent.json was made by a newer engine "
        "version, so it isn't used or changed this session. The game runs with fresh "
        "persistent data that won't be saved.")
    assert path.read_bytes() == data and excl == [] and temps(folder) == []
    assert not (folder / BAD_NAME).exists()


# --- AC-F12-36 — group F, the launch rows -------------------------------------------------

def test_ac36_a_file_link_is_moved_aside_and_its_target_untouched(game, folder, outside,
                                                                  warnings):
    setup(folder)
    target = outside / "x.json"
    target.write_bytes(dumps(GOOD))
    try:
        os.symlink(target, folder / FILE_NAME)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not permitted here: {exc}")
    s = Session(game)
    assert warnings.of("W50") == [bad_file_text(FILE, "not a regular file", kept=True)]
    s.play(x=1)
    assert (folder / BAD_NAME).is_symlink() and target.read_bytes() == dumps(GOOD)
    assert not (folder / FILE_NAME).is_symlink() and disk(folder / FILE_NAME)["values"] == {"x": 1}


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_ac36_a_junction_in_the_files_place_is_moved_aside(game, folder, outside, warnings):
    setup(folder)
    target = outside / "d"
    target.mkdir()
    (target / "keep.txt").write_bytes(b"keep")
    link_dir(folder / FILE_NAME, target)
    s = Session(game)
    assert warnings.of("W50") == [bad_file_text(FILE, "not a regular file", kept=True)]
    s.play(x=1)
    assert os.path.isjunction(folder / BAD_NAME)
    assert tree(target) == {"keep.txt": b"keep"}
    assert disk(folder / FILE_NAME)["values"] == {"x": 1}


def test_ac36_a_linked_dev_folder_is_w52_and_memory(game, folder, outside, warnings):
    target = outside / "p"
    target.mkdir()
    link_dir(folder, target)
    s = Session(game)
    assert s.launch.mode is MEMORY and s.launch.folder is None
    s.play(x=1)
    assert warnings.of("W52") == [save_failed_text(FILE, FOLDER_IS_LINK)]
    assert list(target.iterdir()) == []
    assert [n.code for n in s.sync.take_notices()] == ["W52"]


def test_a_file_in_the_folders_place_is_w52(game, warnings):
    (game / "persistent").write_bytes(b"a file")          # a file in the folder's place
    s = Session(game)
    assert s.launch.mode is MEMORY
    assert warnings.of("W52") == [save_failed_text(FILE, FOLDER_IS_LINK)]


def test_a_folder_that_cant_be_made_is_w52_no_permission(game, warnings, monkeypatch):
    def refuse(path, *args, **kwargs):
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(safefile.os, "mkdir", refuse)
    s = Session(game)
    assert s.launch.mode is MEMORY
    assert warnings.of("W52") == [save_failed_text(FILE, NO_PERMISSION)]


def test_ac36_stale_temps_are_bounded(game, folder, monkeypatch):
    """1,001 old temp-named regular files: ≤ 16 removed, ≤ 1,000 entries examined."""
    setup(folder)
    old = 1_000_000_000
    for i in range(1_001):
        temp = folder / f".persistent.json.{i:08x}.tmp"
        temp.write_bytes(b"")
        os.utime(temp, (old, old))
    examined = []
    real_scandir = safefile.os.scandir

    class Spy:
        def __init__(self, path):
            self.inner = real_scandir(path)

        def __enter__(self):
            self.it = self.inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self.inner.__exit__(*exc)

        def __iter__(self):
            for entry in self.it:
                examined.append(entry.name)
                yield entry

    monkeypatch.setattr(safefile.os, "scandir", Spy)
    Session(game)
    assert 1_001 - len(temps(folder)) <= limits.TEMP_CLEANUP_MAX
    assert 1_001 - len(temps(folder)) == 16
    assert len(examined) <= limits.TEMP_SCAN_MAX


def test_ac36_only_old_temp_names_are_removed(game, folder):
    setup(folder)
    import time as _time
    now = _time.time()
    for name, age in ((".persistent.json.0000000a.tmp", 61), (".persistent.json.0000000b.tmp", 59),
                      (".persistent.json.XYZ.tmp", 61)):
        (folder / name).write_bytes(b"")
        os.utime(folder / name, (now - age, now - age))
    Session(game)
    assert sorted(os.listdir(folder)) == [".persistent.json.0000000b.tmp",
                                          ".persistent.json.XYZ.tmp"]


def test_ac36_a_full_session_leaves_only_the_file(game, folder):
    s = Session(game)
    for i in range(20):
        s.store.set(f"n{i}", i)
        s.store.mark_seen(sid("start", i))
        s.sync.update(float(i * 2))
    s.sync.close()
    assert os.listdir(folder) == [FILE_NAME]
    if os.name == "posix":
        assert os.stat(folder / FILE_NAME).st_mode & 0o777 == 0o600


# --- AC-F12-41 — the launch's warning texts --------------------------------------------------

def _sparse(path: Path, size: int) -> None:
    with open(path, "wb") as f:
        f.truncate(size)


@pytest.mark.parametrize("make, code, text", [
    (lambda p: _sparse(p, limits.FILE_MAX_BYTES + 1), "W50",
     bad_file_text(FILE, "over 32 MB", kept=True)),
    (lambda p: p.write_bytes(b"[]"), "W50", bad_file_text(FILE, "not persistent data", kept=True)),
    (lambda p: p.write_bytes(dumps({**GOOD, "values": {"_a": 1, "b c": 2, "class": 3, "ok": 1}})),
     "W54", dropped_text(FILE, 3)),
    (lambda p: p.write_bytes(dumps({**GOOD, "identity_scheme": 2,
                                    "seen": {"start": "0123456789ab"}})),
     "W55", scheme_text(FILE)),
], ids=["over-cap", "not-persistent", "w54", "w55"])
def test_ac41_launch_texts(game, folder, warnings, make, code, text):
    setup(folder)
    make(folder / FILE_NAME)
    s = Session(game)
    assert warnings.of(code) == [text]
    assert [c for c, _ in warnings if c] == [code]
    s.play(x=1)


def test_ac41_exact_w54_and_w55_wording():
    assert dropped_text(FILE, 3) == (
        "persistent data in <game>/persistent/persistent.json had 3 entries that couldn't be "
        "used (bad names or values). They were dropped and the rest was kept.")
    assert NO_ID_TEXT == (
        "persistent data won't be saved, because config.toml has no [game] id. Set a unique id "
        'under [game], e.g. id = "paper-lanterns", before releasing.')


# --- AC-F12-42 (launch part) — no identity or player data --------------------------------------

def test_ac42_launch_messages_hold_no_content_or_home(game, folder, warnings, user_roots):
    """ZZMARK in file content and names; the game folder under the sentinel home. Every
    launch message gives ``<game>/…`` and fixed words only."""
    home_game = user_roots.home / "games" / "lanterns"
    home_game.mkdir(parents=True)
    rows = [b'{"ZZMARK":', dumps({**GOOD, "values": {"ZZMARK x": "ZZMARK", "ok": "ZZMARK"}}),
            dumps({**GOOD, "format": 2, "ZZMARK": 1})]
    for data in rows:
        setup(home_game / "persistent", data)
        s = Session(home_game)
        s.play(x="ZZMARK")
        assert "ZZMARK" not in repr(s.store) and "ZZMARK" not in repr(s.sync)
    assert warnings
    for code, message in warnings:
        assert "ZZMARK" not in message and "qauser7" not in message, message
        assert str(home_game) not in message


# --- AC-F12-45 — the writer thread starts in the launch, not on the first write's frame -----

@pytest.mark.parametrize("data, off, started", [
    (None, False, True), (json.dumps(GOOD).encode(), False, True),
    (None, True, False), (b'{"format":2}', False, False),
], ids=["fresh", "read", "off", "newer"])
def test_install_starts_the_writer_thread_when_data_can_be_written(game, folder, writers, data,
                                                                    off, started):
    """``Writer.start`` runs in ``install_persistence`` (the load slice) for WRITABLE data
    only; MEMORY and READ_ONLY sessions never write, so they start no thread."""
    if data is not None:
        setup(folder, data)
    writer = writers(threaded=True)
    launch = open_for_launch(FakeProgram(), game_root=game, release=False, app_id=None,
                             off=off).run()
    install_persistence(SimpleNamespace(writer=writer, persist=None), launch)
    assert writer.started is started and writer.alive is started
    assert writer.start() is True and writer.started   # idempotent; lazy start stays
