"""AC-F11-53 — the shared writer, from the ``save`` owner's side (C14 as F16 ``07`` §3; read
``SaveWrite``/``SaveFailed``/``pending(owner)`` as ``FileWrite``/``Failed``/
``client.pending``, I-15). FIFO across owners, results per owner, one write at a time, and
the general owner checks are ``test_writer_shared.py``'s; here the ``save`` client is
registered exactly as ``install_saves`` does (its root and ``SLOT_NAME_RE``)."""

import errno
import threading
import time

import pytest

from engine.core import safefile
from engine.persist.saves import SLOT_NAME_RE
from engine.persist.writer import (COULDNT_WRITE, DISK_FULL, PERSIST, SAVE, Failed, FileWrite,
                                   FileWritten, Writer, WriteRequest, Written)
from tests.persist.writer_support import (FakeSleep, base, game, tree,  # noqa: F401
                                          writers)

FAR_S = 10.0


@pytest.mark.parametrize("threaded", [False, True], ids=["sync", "threaded"])
def test_persist_save_persist_in_order_and_disk_full_only_fails_the_save(
        writers, game, monkeypatch, threaded):
    writer: Writer = writers(threaded=threaded, sleep=FakeSleep())
    persist = writer.client(PERSIST, root=game / "persistent",
                            names=frozenset({"persistent.json"}))
    save = writer.client(SAVE, root=game / "saves", names=SLOT_NAME_RE)
    order: list[str] = []
    active = {"now": 0, "max": 0}
    lock = threading.Lock()
    real = safefile.write_atomic

    def write_atomic(target, pieces, **kw):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        try:
            order.append(target.name)
            if target.name == "quick-1.vnsave":
                raise OSError(errno.ENOSPC, "injected")
            return real(target, pieces, **kw)
        finally:
            with lock:
                active["now"] -= 1

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)
    persist.submit(WriteRequest(game / "persistent", (b"j1",), None, False, 1))
    save.submit(FileWrite(game / "saves", "quick-1.vnsave", (b"j2",), token=2))
    persist.submit(WriteRequest(game / "persistent", (b"j3",), None, False, 3))
    until = time.monotonic() + FAR_S
    saved = save.wait(until)
    kept = persist.wait(until)
    assert order == ["persistent.json", "quick-1.vnsave", "persistent.json"]
    assert [(type(r), r.reason, r.token) for r in saved] == [(Failed, DISK_FULL, 2)]
    assert [(type(r), r.version) for r in kept] == [(Written, 1), (Written, 3)]
    assert (game / "persistent" / "persistent.json").read_bytes() == b"j3"
    assert not (game / "saves" / "quick-1.vnsave").exists()
    assert active["max"] == 1
    assert save.pending == 0 and persist.pending == 0


@pytest.mark.parametrize("folder, name", [
    ("saves", "../x.vnsave"),
    ("saves", "persistent.json"),
    ("saves", "QUICK-1.vnsave"),
    ("other", "quick-1.vnsave"),
], ids=["dotdot", "persistent-name", "case", "other-folder"])
def test_a_save_job_outside_the_saves_root_or_names_writes_nothing(writers, game, folder, name):
    writer: Writer = writers(threaded=False, sleep=FakeSleep())
    save = writer.client(SAVE, root=game / "saves", names=SLOT_NAME_RE)
    before = tree(game)
    save.submit(FileWrite(game / folder, name, (b"x",), token=7))
    results = save.take()
    assert [(type(r), r.reason, r.token) for r in results] == [(Failed, COULDNT_WRITE, 7)]
    assert tree(game) == before


def test_a_slot_name_writes(writers, game):
    writer: Writer = writers(threaded=False, sleep=FakeSleep())
    save = writer.client(SAVE, root=game / "saves", names=SLOT_NAME_RE)
    save.submit(FileWrite(game / "saves", "page100-6.vnsave", (b"a", b"b"), token=1))
    assert [type(r) for r in save.take()] == [FileWritten]
    assert (game / "saves" / "page100-6.vnsave").read_bytes() == b"ab"
