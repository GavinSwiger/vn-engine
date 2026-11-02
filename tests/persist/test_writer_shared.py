"""One writer, several owners (ADR-0007 amendment; F16 ``07`` §3, I-2; SEC-F12-07,
SEC-F11-10; F12 checklist step 4): registration, jobs outside an owner's folder or names,
FIFO across owners, per-owner results and "in flight", one write at a time, and quit with
one shared deadline (a hung write abandoned at ``CLOSE_WAIT_S``).

AC-F12-35's quit rows (the W52 for the skipped final write) run through ``PersistentSync``
and the App at steps 5–6. Here the writer side of that contract is checked: after
``wait(until)`` the owner still sees its job in flight, so it skips its final write, and
``stop(until)`` abandons the thread at the shared deadline."""

import os
import re
import threading
import time
from pathlib import Path

import pytest

from engine.core import safefile
from engine.persist import limits
from engine.persist.writer import (COULDNT_WRITE, OUTSIDE_DETAIL, PERSIST, SAVE, SETTINGS,
                                   STOPPED_DETAIL, Failed, FileWrite, FileWritten, Writer,
                                   WriteRequest, Written)
from tests.persist.writer_support import (NEW, OLD, FakeClock, FakeSleep, Gate, HungFsync,  # noqa: F401
                                          WriteSpy, base, game, outside, root, temps, tree,
                                          writers)

NAME = "persistent.json"
SLOT_RE = re.compile(r"slot-\d{3}\.json")
FAR_S = 10.0


@pytest.fixture(params=[False, True], ids=["sync", "threaded"])
def threaded(request) -> bool:
    return request.param


def owners(writer: Writer, game: Path):
    """The three owners, each on its own root under ``game``."""
    return (writer.client(PERSIST, root=game / "persistent", names=frozenset({NAME})),
            writer.client(SETTINGS, root=game / "settings", names=frozenset({"settings.json"})),
            writer.client(SAVE, root=game / "saves", names=SLOT_RE))


def unchecked(folder: Path, data: bytes, version: int) -> WriteRequest:
    return WriteRequest(folder, (data,), None, False, version)


# --- Registration -----------------------------------------------------------------------------

def test_each_owner_registers_once(writers, game):
    writer = writers(threaded=False)
    persist, settings, save = owners(writer, game)
    assert (persist.owner, settings.owner, save.owner) == (PERSIST, SETTINGS, SAVE)
    for owner in (PERSIST, SETTINGS, SAVE):
        with pytest.raises(ValueError):
            writer.client(owner, root=game / "x", names=frozenset({"x.json"}))
    assert not writer.started and not (game / "persistent").exists()


@pytest.mark.parametrize("owner, root, names", [
    ("music", "abs", frozenset({"m.json"})),
    (PERSIST, "relative", frozenset({NAME})),
    (PERSIST, "abs", frozenset()),
    (PERSIST, "abs", frozenset({"../persistent.json"})),
    (PERSIST, "abs", frozenset({"sub/persistent.json"})),
    (PERSIST, "abs", frozenset({"sub\\persistent.json"})),
    (PERSIST, "abs", frozenset({"persistent.json:stream"})),
    (PERSIST, "abs", frozenset({".."})),
    (SAVE, "abs", re.compile(rb"slot")),
], ids=["unknown-owner", "relative-root", "no-names", "dotdot", "slash", "backslash",
        "stream", "dotdot-only", "bytes-pattern"])
def test_bad_registrations_raise(writers, game, owner, root, names):
    folder = game / "persistent" if root == "abs" else Path("persistent")
    with pytest.raises(ValueError):
        writers(threaded=False).client(owner, root=folder, names=names)


# --- Jobs outside an owner's folder or names touch nothing -------------------------------------

FS_CALLS = ("lstat", "stat", "open", "mkdir", "makedirs", "replace", "rename", "unlink",
            "scandir", "listdir", "rmdir", "read", "write", "fsync")


def _outside_jobs(game: Path):
    persistent, settings, saves = game / "persistent", game / "settings", game / "saves"
    return [
        ("settings-sibling-folder", SETTINGS, FileWrite(persistent, "settings.json", (NEW,), token=4)),
        ("settings-subfolder", SETTINGS, FileWrite(settings / "sub", "settings.json", (NEW,), token=4)),
        ("settings-unnormalized", SETTINGS,
         FileWrite(settings / ".." / "settings", "settings.json", (NEW,), token=4)),
        ("settings-other-name", SETTINGS, FileWrite(settings, "other.json", (NEW,), token=4)),
        ("settings-dotdot-name", SETTINGS,
         FileWrite(settings, "../persistent/persistent.json", (NEW,), token=4)),
        ("settings-WriteRequest", SETTINGS, WriteRequest(settings, (NEW,), None, False, 1,
                                                          name="settings.json")),
        ("persist-other-name", PERSIST, WriteRequest(persistent, (NEW,), None, False, 1,
                                                      name="persistent.bad.json")),
        ("persist-FileWrite-temp-name", PERSIST,
         FileWrite(persistent, ".persistent.json.deadbeef.tmp", (NEW,), token=4)),
        ("save-partial-match", SAVE, FileWrite(saves, "slot-001.json.bak", (NEW,), token=4)),
        ("save-short-name", SAVE, FileWrite(saves, "slot-01.json", (NEW,), token=4)),
        ("save-separator", SAVE, FileWrite(saves, "x/slot-001.json", (NEW,), token=4)),
    ]


_OUTSIDE_IDS = [row[0] for row in _outside_jobs(Path("/g"))]


@pytest.mark.parametrize("index", range(len(_OUTSIDE_IDS)), ids=_OUTSIDE_IDS)
def test_a_job_outside_its_owner_fails_without_touching_the_disk(writers, game, threaded,
                                                                 monkeypatch, index):
    _, owner, job = _outside_jobs(game)[index]
    writer = writers(threaded=threaded, sleep=FakeSleep())
    clients = dict(zip((PERSIST, SETTINGS, SAVE), owners(writer, game)))
    before = tree(game)
    calls: list[str] = []
    with monkeypatch.context() as patch:
        for name in FS_CALLS:
            real = getattr(os, name)

            def spy(*args, _name=name, _real=real, **kwargs):
                if threading.current_thread() is not threading.main_thread() or not threaded:
                    calls.append(_name)
                return _real(*args, **kwargs)
            patch.setattr(safefile.os, name, spy)
        clients[owner].submit(job)
        results = clients[owner].wait(time.monotonic() + FAR_S)
    assert results == [Failed(COULDNT_WRITE, OUTSIDE_DETAIL, getattr(job, "token", 0))]
    assert calls == []
    assert tree(game) == before
    for other, client in clients.items():
        if other != owner:
            assert client.pending == 0 and client.take() == []


# --- FIFO across owners; results and "in flight" per owner -------------------------------------

def test_jobs_run_first_in_first_out_and_results_go_only_to_their_owner(writers, game,
                                                                        monkeypatch):
    writer = writers(threaded=True, sleep=FakeSleep())
    persist, settings, save = owners(writer, game)
    gate, spy = Gate(), WriteSpy()
    gate.hold(b"A")
    writers.release(gate.release)
    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_all", gate)
        patch.setattr(safefile, "write_atomic", spy)
        persist.submit(unchecked(game / "persistent", b"A", 1))
        assert gate.entered[b"A"].wait(FAR_S)
        assert persist.in_flight == 1 and settings.in_flight == 0 and save.in_flight == 0
        settings.submit(FileWrite(game / "settings", "settings.json", (b"B",), token=11))
        save.submit(FileWrite(game / "saves", "slot-001.json", (b"C",), token=12))
        persist.submit(unchecked(game / "persistent", b"D", 2))
        assert (persist.in_flight, settings.in_flight, save.in_flight) == (2, 1, 1)
        assert persist.take() == [] and settings.take() == [] and save.take() == []
        gate.release()
        until = time.monotonic() + FAR_S
        got = {c.owner: c.wait(until) for c in (persist, settings, save)}
    assert gate.order == [b"A", b"B", b"C", b"D"]
    assert spy.names == [NAME, "settings.json", "slot-001.json", NAME]
    assert spy.max_active == 1
    assert [type(r) for r in got[PERSIST]] == [Written, Written]
    assert [r.version for r in got[PERSIST]] == [1, 2]
    assert [(type(r), r.token) for r in got[SETTINGS]] == [(FileWritten, 11)]
    assert [(type(r), r.token) for r in got[SAVE]] == [(FileWritten, 12)]
    for client in (persist, settings, save):
        assert client.pending == 0 and client.in_flight == 0 and client.take() == []
    assert (game / "persistent" / NAME).read_bytes() == b"D"
    assert (game / "settings" / "settings.json").read_bytes() == b"B"
    assert (game / "saves" / "slot-001.json").read_bytes() == b"C"


def test_pending_counts_until_taken(writers, game, threaded):
    writer = writers(threaded=threaded, sleep=FakeSleep())
    persist, settings, _ = owners(writer, game)
    persist.submit(unchecked(game / "persistent", NEW, 1))
    persist.submit(unchecked(game / "persistent", NEW, 2))
    persist.wait(time.monotonic() + FAR_S)  # takes both
    settings.submit(FileWrite(game / "settings", "settings.json", (NEW,), token=1))
    deadline = time.monotonic() + FAR_S
    while settings.in_flight and time.monotonic() < deadline:
        time.sleep(0.005)
    assert settings.in_flight == 0 and settings.pending == 1 and persist.pending == 0
    assert [r.token for r in settings.take()] == [1]
    assert settings.pending == 0


def test_never_two_writes_at_once_across_owners(writers, game, monkeypatch):
    writer = writers(threaded=True, sleep=FakeSleep())
    persist, settings, save = owners(writer, game)
    spy = WriteSpy()
    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_atomic", spy)
        for i in range(10):
            persist.submit(unchecked(game / "persistent", b"p%d" % i, i))
            settings.submit(FileWrite(game / "settings", "settings.json", (b"s%d" % i,), token=i))
            save.submit(FileWrite(game / "saves", f"slot-{i:03d}.json", (b"v%d" % i,), token=i))
        until = time.monotonic() + FAR_S
        got = {c.owner: c.wait(until) for c in (persist, settings, save)}
    assert spy.max_active == 1
    assert set(spy.threads) == {writer._thread.ident}
    assert spy.names == [n for i in range(10)
                         for n in (NAME, "settings.json", f"slot-{i:03d}.json")]
    assert [r.version for r in got[PERSIST]] == list(range(10))
    assert [r.token for r in got[SETTINGS]] == list(range(10))
    assert [r.token for r in got[SAVE]] == list(range(10))
    assert (game / "persistent" / NAME).read_bytes() == b"p9"
    assert len(os.listdir(game / "saves")) == 10
    assert temps(game / "persistent") == [] and temps(game / "settings") == []


def test_wait_returns_at_its_deadline_and_the_job_stays_in_flight(writers, game, monkeypatch):
    clock = FakeClock(step=0.25)
    writer = writers(threaded=True, sleep=FakeSleep(), clock=clock)
    persist, _, _ = owners(writer, game)
    gate = Gate()
    gate.hold(NEW)
    writers.release(gate.release)
    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_all", gate)
        persist.submit(unchecked(game / "persistent", NEW, 1))
        assert gate.entered[NEW].wait(FAR_S)
        started = time.monotonic()
        assert persist.wait(clock.now + 1.0) == []
        assert time.monotonic() - started < 2.0
        assert persist.in_flight == 1 and persist.pending == 1
        gate.release()
        clock.step = 0.0                    # the clock stands still; the job ends on its own
        deadline = time.monotonic() + FAR_S
        while persist.in_flight and time.monotonic() < deadline:
            time.sleep(0.005)
    [result] = persist.take()
    assert isinstance(result, Written) and result.version == 1


# --- Quit: one shared deadline, then the thread is abandoned (SEC-F12-07, SEC-F11-10) ----------

def test_a_hung_write_at_quit_hits_the_shared_deadline_and_the_thread_is_abandoned(
        writers, game, monkeypatch):
    clock = FakeClock(step=0.5)
    writer = writers(threaded=True, sleep=FakeSleep(), clock=clock)
    persist, settings, _ = owners(writer, game)
    folder = game / "persistent"
    folder.mkdir()
    (folder / NAME).write_bytes(OLD)
    hung = HungFsync()
    writers.release(hung.go.set)
    real_start = time.monotonic()
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fsync", hung)
        persist.submit(WriteRequest(folder, (NEW,), Stamp_of(folder / NAME), True, 7))
        assert hung.entered.wait(FAR_S)
        # App.run()'s finally: one deadline for every owner.
        t0 = clock.now
        until = writer.quit_deadline()
        assert until == t0 + limits.CLOSE_WAIT_S
        settings.submit(FileWrite(game / "settings", "settings.json", (NEW,), token=5))
        assert settings.wait(until) == []
        assert persist.wait(until) == []
        # The persist owner still has its write in flight at the deadline, so it skips its
        # final write (W52, PersistentSync.close at step 5) and never starts a second one.
        assert persist.in_flight == 1 and settings.in_flight == 1
        assert writer.stop(until) is False
        assert clock.now - t0 >= limits.CLOSE_WAIT_S
        assert time.monotonic() - real_start < 3.0
        assert writer.abandoned and writer.alive
        # The queued settings job never starts; its owner hears so.
        assert settings.take() == [Failed(COULDNT_WRITE, STOPPED_DETAIL, 5)]
        assert settings.in_flight == 0
        with pytest.raises(RuntimeError):
            persist.submit(WriteRequest(folder, (b"final",), None, False, 8))
        assert (folder / NAME).read_bytes() == OLD
        # The abandoned thread can only finish its own write: whole OLD or NEW, never both.
        hung.go.set()
        writer._thread.join(FAR_S)
    assert not writer.alive
    assert (folder / NAME).read_bytes() in (OLD, NEW)
    assert not (game / "settings" / "settings.json").exists()
    assert temps(folder) == []


def test_quit_with_a_hung_fsync_returns_within_close_wait(writers, game, monkeypatch):
    """Real clock, ``CLOSE_WAIT_S`` patched to 0.2 s (06 §0.3: quit ≤ 0.7 s)."""
    writer = writers(threaded=True, sleep=FakeSleep())
    persist, settings, save = owners(writer, game)
    hung = HungFsync()
    writers.release(hung.go.set)
    with monkeypatch.context() as patch:
        patch.setattr(limits, "CLOSE_WAIT_S", 0.2)
        patch.setattr(safefile.os, "fsync", hung)
        save.submit(FileWrite(game / "saves", "slot-001.json", (NEW,), token=1))
        assert hung.entered.wait(FAR_S)
        start = time.monotonic()
        until = writer.quit_deadline()
        for client in (save, settings, persist):
            client.wait(until)
        ended = writer.stop(until)
        elapsed = time.monotonic() - start
    assert ended is False and elapsed <= 0.7
    assert save.in_flight == 1
    hung.go.set()
    writer._thread.join(FAR_S)
    assert not writer.alive


def test_stop_when_idle_ends_the_thread(writers, game):
    writer = writers(threaded=True, sleep=FakeSleep())
    persist, settings, _ = owners(writer, game)
    persist.submit(unchecked(game / "persistent", NEW, 1))
    settings.submit(FileWrite(game / "settings", "settings.json", (NEW,), token=2))
    until = time.monotonic() + FAR_S
    assert writer.stop(until) is True
    assert not writer.alive and not writer.abandoned
    # stop lets the queue drain: both results arrived.
    assert [type(r) for r in persist.take()] == [Written]
    assert [r.token for r in settings.take()] == [2]
    with pytest.raises(RuntimeError):
        settings.submit(FileWrite(game / "settings", "settings.json", (NEW,)))


def test_a_writer_that_never_wrote_has_no_thread(writers, game, threaded):
    writer = writers(threaded=threaded)
    owners(writer, game)
    assert writer.stop(writer.quit_deadline()) is True
    assert not writer.started and not writer.alive
    assert os.listdir(game) == []


def test_sync_mode_routes_results_per_owner_too(writers, game):
    writer = writers(threaded=False, sleep=FakeSleep())
    persist, settings, save = owners(writer, game)
    save.submit(FileWrite(game / "saves", "slot-002.json", (NEW,), token=9))
    persist.submit(unchecked(game / "persistent", NEW, 3))
    assert settings.take() == []
    assert [r.version for r in persist.take()] == [3]
    assert [r.token for r in save.take()] == [9]
    assert not writer.started


def Stamp_of(path: Path):
    return safefile.Stamp.of(os.stat(path))
