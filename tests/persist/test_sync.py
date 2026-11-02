"""The sync's seams, write failures, and frame cost (F12 checklist step 5; ``04`` §5.2,
§7.5, §7.7; SEC-F12-07, -09(b), -10): AC-F12-16, AC-F12-34, AC-F12-37 (34 and 37 moved here
from step 4, ``07`` I-8), and the sync half of AC-F12-35's ends (``flush_now`` and ``close``
with a write in flight; the App half is step 6).

Harness Y (``sync_support``). Faults are injected in ``engine.core.safefile``'s ``os`` calls,
as in ``test_writer.py``."""

import errno
import gc
import os
import statistics
import threading
import time

import pytest

from engine.core import safefile
from engine.persist import limits
from engine.persist.location import FILE_NAME
from engine.persist.sync import MEMORY, WRITABLE, PersistentSync
from engine.persist.texts import SAVED_AGAIN_TEXT, final_write_skipped_text, save_failed_text
from engine.persist.writer import COULDNT_WRITE, DISK_FULL, FOLDER_IS_LINK, NO_PERMISSION
from engine.runtime.persistent import Missing, PersistentUnsaveable, PersistentStore
from tests.persist.sync_support import (SEEN, Harness, disk_records, plant, sid)
from tests.persist.writer_support import (FakeClock, HungFsync, WriteSpy, base,  # noqa: F401
                                          fail_when, game, is_temp, link_dir, oserror, outside,
                                          temps, writers)


@pytest.fixture
def folder(game):
    return game / "persistent"


# --- AC-F12-16 — seams for later features -------------------------------------------------------

def test_ac16_peek_returns_a_copy_and_missing(folder, game):
    h = Harness(folder, game=game, defaults={"festivals": [1, 2]})
    version = h.store.version
    got = h.store.peek("festivals")
    got.append(3)
    assert h.store.peek("festivals") == [1, 2] and h.store.version == version
    assert h.store.peek("nope") is Missing


def test_ac16_a_set_as_f40_would_refuses_an_unsaveable_value(folder, game):
    h = Harness(folder, game=game)
    with pytest.raises(PersistentUnsaveable):
        h.store.set("x", {1})
    assert h.store.names() == frozenset()


def test_ac16_flush_now_writes_inside_the_interval_and_merges_first(folder, game):
    a = Harness(folder, game=game)
    b = Harness(folder, game=game)
    a.store.set("x", 1)
    a.tick(0.0)
    b.store.mark_seen(sid("b", 1))
    assert b.sync.flush_now()                   # the stamp changes under A
    a.store.set("x", 2)
    a.tick(0.2)
    assert a.sync.flush_now() is True
    assert a.path.read_bytes() == a.encoded()
    obj = a.disk()
    assert obj["values"] == {"x": 2} and disk_records(obj, SEEN) == {sid("b", 1)}


def test_ac16_unlock_listeners_run_once_on_the_main_thread(folder, game):
    h = Harness(folder, game=game)
    h.store.register_kind("cg")
    calls = []
    h.sync.add_unlock_listener(lambda kind, name: calls.append((kind, name,
                                                                threading.get_ident())))
    h.store.unlock("cg", "a")
    h.tick()
    h.tick()
    assert calls == [("cg", "a", threading.main_thread().ident)]


def test_ac16_listeners_also_run_without_a_file(folder, game):
    h = Harness(folder, game=game, mode=MEMORY)
    h.store.register_kind("cg")
    calls = []
    h.sync.add_unlock_listener(lambda kind, name: calls.append((kind, name)))
    h.store.unlock("cg", "b")
    h.tick()
    assert calls == [("cg", "b")]


def test_ac16_reset_then_flush_now_writes_launch_values_only(folder, game):
    h = Harness(folder, game=game, defaults={"festivals": 0})
    h.store.register_kind("cg")
    h.store.set("festivals", 3)
    h.store.set("extra", 1)
    h.store.mark_seen(sid("a", 1))
    h.store.mark_chosen(sid("m", 1), "000000000002")
    h.store.unlock("cg", "a")
    assert h.sync.flush_now()
    h.store.reset()
    assert h.sync.flush_now()
    assert h.disk() == {"format": 1, "identity_scheme": 1, "values": {"festivals": 0},
                        "seen": {}, "chosen": {}, "unlocks": {"cg": []}}


# --- AC-F12-34 — write failures -------------------------------------------------------------

def _replace_fails():
    return PermissionError(errno.EACCES, "sharing violation")


FAULTS = [
    # id, os call, predicate, exception, reason
    ("ENOSPC-write", "write", lambda *_: True, oserror(errno.ENOSPC), DISK_FULL),
    ("EACCES-temp-open", "open", is_temp, oserror(errno.EACCES), NO_PERMISSION),
    ("EPERM-temp-open", "open", is_temp, oserror(errno.EPERM), NO_PERMISSION),
    ("EROFS-temp-open", "open", is_temp, oserror(errno.EROFS), NO_PERMISSION),
    ("PermissionError-replace-x3", "replace", lambda *_: True, _replace_fails, NO_PERMISSION),
    ("EIO-fsync", "fsync", lambda *_: True, oserror(errno.EIO), COULDNT_WRITE),
    ("RuntimeError-writer", "write", lambda *_: True, lambda: RuntimeError("boom"),
     COULDNT_WRITE),
]


def _written_once(folder, game) -> Harness:
    h = Harness(folder, game=game)
    h.store.set("x", 1)
    assert h.sync.flush_now()
    h.store.set("x", 2)
    return h


def _check_failure(h: Harness, old: bytes, warnings, reason: str) -> None:
    version = h.store.version
    snapshot = h.store.values_snapshot()
    h.tick()
    assert h.path.read_bytes() == old and temps(h.folder) == []
    assert h.store.version == version and h.store.values_snapshot() == snapshot
    assert warnings.of("W52") == [save_failed_text(h.store.display, reason)]
    h.store.set("x", 3)                          # a second failure: no second W52
    h.ticks(1.1)
    assert len(warnings.of("W52")) == 1 and h.path.read_bytes() == old


def _check_recovery(h: Harness, warnings) -> None:
    h.store.set("x", 4)
    h.ticks(1.1)
    h.tick()
    assert h.disk()["values"] == {"x": 4}
    h.store.set("x", 5)
    h.ticks(1.1)
    assert warnings.of(None).count(SAVED_AGAIN_TEXT) == 1


@pytest.mark.parametrize("call, when, exc, reason", [f[1:] for f in FAULTS],
                         ids=[f[0] for f in FAULTS])
def test_ac34_a_fault_gives_w52_with_its_reason(folder, game, warnings, monkeypatch,
                                                call, when, exc, reason):
    h = _written_once(folder, game)
    old = h.path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, call, fail_when(getattr(os, call), when, exc))
        h.tick(10.0)                             # the write fails
        _check_failure(h, old, warnings, reason)
    if reason == COULDNT_WRITE:
        assert any("Traceback" in m for m in warnings.of(None))     # DEBUG, redacted
    _check_recovery(h, warnings)


def test_ac34_a_runtime_error_inside_the_writer(folder, game, warnings, monkeypatch):
    h = _written_once(folder, game)
    old = h.path.read_bytes()

    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    with monkeypatch.context() as patch:
        patch.setattr(safefile, "write_atomic", broken)
        h.tick(10.0)
        _check_failure(h, old, warnings, COULDNT_WRITE)
    assert any("RuntimeError: boom" in m for m in warnings.of(None))
    _check_recovery(h, warnings)


def test_ac34_the_folder_replaced_by_a_link(folder, game, outside, warnings):
    h = _written_once(folder, game)
    old = h.path.read_bytes()
    aside = folder.with_name("aside")
    folder.rename(aside)
    target = outside / "p"
    target.mkdir()
    link_dir(folder, target)
    h.tick(10.0)
    h.tick()
    assert warnings.of("W52") == [save_failed_text(h.store.display, FOLDER_IS_LINK)]
    assert os.listdir(target) == [] and (aside / FILE_NAME).read_bytes() == old
    assert temps(aside) == []
    os.rmdir(folder) if os.name == "nt" else os.unlink(folder)
    aside.rename(folder)
    _check_recovery(h, warnings)


# --- AC-F12-35 (sync half) — flush_now and close with a write in flight --------------------------

def test_flush_now_waits_for_the_write_in_flight_and_never_overlaps(folder, game, writers,
                                                                     monkeypatch):
    spy = WriteSpy()
    hung = HungFsync()
    writers.release(hung.go.set)
    writer = writers(threaded=True)
    h = Harness(folder, game=game, writer=writer)
    monkeypatch.setattr(safefile, "write_atomic", spy)
    monkeypatch.setattr(safefile.os, "fsync", hung)
    h.store.set("x", 1)
    h.tick(0.0)
    assert hung.entered.wait(5)
    h.store.set("x", 2)
    threading.Timer(0.1, hung.go.set).start()
    assert h.sync.flush_now() is True
    assert spy.max_active == 1 and h.disk()["values"] == {"x": 2}
    assert all(t != threading.main_thread().ident for t in spy.threads)


def test_close_skips_a_final_write_that_cant_finish_in_time(folder, game, writers, warnings,
                                                           monkeypatch):
    """SEC-F12-07 with ``CLOSE_WAIT_S`` patched to 0.2 s and the fsync held: close returns
    within the deadline, the file is whole (the old bytes), and W52 says the write was
    skipped."""
    monkeypatch.setattr(limits, "CLOSE_WAIT_S", 0.2)
    hung = HungFsync()
    writers.release(hung.go.set)
    writer = writers(threaded=True)
    h = Harness(folder, game=game, writer=writer)
    h.store.set("x", 1)
    assert h.sync.flush_now()
    old = h.path.read_bytes()
    monkeypatch.setattr(safefile.os, "fsync", hung)
    h.store.set("x", 2)
    h.tick(10.0)
    assert hung.entered.wait(5)
    start = time.monotonic()
    h.sync.close()
    assert time.monotonic() - start <= 0.2 + 0.5
    assert h.path.read_bytes() == old
    assert warnings.of("W52") == [final_write_skipped_text(h.store.display)]
    assert h.sync.closed and h.sync.flush_now() is False


def test_close_writes_what_is_unwritten_and_stops_its_own_writer(folder, game, monkeypatch):
    monkeypatch.setattr("engine.persist.writer.WRITER_THREADED", True)
    folder.mkdir(parents=True)
    store = PersistentStore(identity_scheme=1)
    sync = PersistentSync(store, None, mode=WRITABLE, folder=folder, stamp=None,
                          clock=FakeClock(0.0))
    store.set("x", 1)
    sync.update(0.0)
    store.set("x", 2)
    sync.close()
    assert sync._writer is not None and not sync._writer.alive
    assert b'"x":2' in (folder / FILE_NAME).read_bytes()
    sync.update(5.0)                              # after close: nothing
    sync.close()


def test_take_notices_drains_once(folder, game):
    h = Harness(folder, game=game)
    h.store.set("x", 1)
    assert h.sync.flush_now()
    plant(h.path, b"{")
    h.store.set("x", 2)
    assert h.sync.flush_now()
    notices = h.sync.take_notices()
    assert [n.code for n in notices] == ["W50"] and h.sync.take_notices() == ()


# --- AC-F12-37 — the main thread never waits (CI guard) ----------------------------------------

def _typical_store() -> PersistentStore:
    """50,000 sids (500 labels × 100 keys) and about 10 KB of values."""
    store = PersistentStore(identity_scheme=1)
    for label in range(500):
        for key in range(100):
            store.mark_seen(sid(f"l{label}", key))
    for i in range(100):
        store.set(f"v{i}", "x" * 90)
    return store


def test_ac37_update_never_waits_on_the_writer(folder, game, writers, monkeypatch):
    """Threaded, fsync sleeping 500 ms, 120 ticks at 1/60 s with a change every 10 ticks:
    each ``update`` median ≤ 1.0 ms and max ≤ 3.0 ms (``07`` I-6, CI form; the 1.0 ms max
    is AC-F12-45's under ``perf``), one write in flight at most, and ``write_atomic`` never
    on the main thread. The encoder is warmed first, as the launch does (step 6)."""
    spy = WriteSpy()
    real_fsync = os.fsync
    slow = [True]

    def slow_fsync(fd):
        if slow[0] and threading.current_thread() is not threading.main_thread():
            time.sleep(0.5)
        real_fsync(fd)

    writer = writers(threaded=True)
    h = Harness(folder, game=game, writer=writer, store=_typical_store())
    assert h.sync.warm(float("inf"))
    monkeypatch.setattr(safefile, "write_atomic", spy)
    monkeypatch.setattr(safefile.os, "fsync", slow_fsync)
    durations = []
    gc.disable()
    try:
        for k in range(120):
            if k % 10 == 0:
                h.store.set("v0", k)
                h.store.mark_seen(sid("new", k))
            start = time.perf_counter()
            h.sync.update(k / 60)
            durations.append(time.perf_counter() - start)
    finally:
        gc.enable()
    assert statistics.median(durations) <= 0.001, statistics.median(durations)
    assert max(durations) <= 0.003, max(durations)
    deadline = time.monotonic() + 5
    while not spy.names and time.monotonic() < deadline:
        time.sleep(0.01)
    assert h.sync.in_flight and h.sync.requests == 1      # the one write is still in flight
    slow[0] = False
    h.sync.close()
    assert spy.max_active == 1 and len(spy.names) == 2
    assert threading.main_thread().ident not in spy.threads
