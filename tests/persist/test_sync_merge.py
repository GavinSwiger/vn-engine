"""When writes happen and how two copies merge (F12 checklist step 5; ``04`` §7.5–7.6;
SEC-F12-03(c), -06(c), -08): AC-F12-33, AC-F12-38, AC-F12-39 (default tier; the real
two-process pair is ``slow``), AC-F12-40.

Harness Y (``sync_support``): a ``PersistentSync`` per copy on one real folder, fake clocks,
and a synchronous writer (results are taken at the copy's next tick). "Each writes after its
own change" is ``flush_now()``."""

import errno
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from engine.core import safefile
from engine.persist import fileformat, limits
from engine.persist.location import BAD_NAME, FILE_NAME
from engine.persist.sync import MEMORY, READ_ONLY, WRITABLE, PersistentSync
from engine.persist.texts import SAVED_AGAIN_TEXT, bad_file_text, newer_file_text
from engine.persist.writer import Changed, WriterClient, Written
from engine.runtime.persistent import PersistentNoValue, PersistentStore
from tests.persist.sync_support import (CHOSEN, SEEN, Harness, disk_records, disk_unlocks,
                                        dumps, plant, records, sid, store_unlocks)
from tests.persist.writer_support import (FakeClock, WriteSpy, base, fail_when,  # noqa: F401
                                          game, oserror, temps)

MAIN = Path(__file__).resolve()


@pytest.fixture
def folder(game) -> Path:
    return game / "persistent"


@pytest.fixture
def spy(monkeypatch) -> WriteSpy:
    s = WriteSpy()
    monkeypatch.setattr(safefile, "write_atomic", s)
    return s


def copies(folder, game, **kwargs):
    a = Harness(folder, game=game, **kwargs)
    b = Harness(folder, game=game, **kwargs)
    for h in (a, b):
        h.store.register_kind("cg")
    return a, b


def write(h: Harness) -> None:
    """The copy writes after its own change (merging first if the file changed)."""
    assert h.sync.flush_now(), h.sync.mode


def converge(*hs: Harness) -> None:
    """Each copy writes once more in turn, so every store has merged the others'."""
    for h in hs + hs[:1]:
        h.store.version += 1               # a change that changes nothing
        write(h)


# --- AC-F12-33 — when writes happen -------------------------------------------------------------

def test_ac33_a_hundred_changes_before_a_tick_are_one_write(folder, game, spy):
    h = Harness(folder, game=game)
    for i in range(100):
        h.store.set("n", i)
    h.tick(0.0)
    assert spy.names == [FILE_NAME]
    h.tick(1 / 60)
    assert h.disk()["values"] == {"n": 99}
    assert h.sync.written == h.store.version and h.store.changed == {}


def test_ac33_a_change_waits_for_the_one_second_interval(folder, game, spy):
    h = Harness(folder, game=game)
    h.store.set("n", 1)
    h.tick(0.0)
    for k in range(1, 61):
        h.tick(k / 60)
        if k == 18:                          # t = 0.3
            h.store.set("n", 2)
        assert len(spy.names) == (2 if k >= 60 else 1), k
    h.tick(61 / 60)
    assert h.disk()["values"] == {"n": 2}


@pytest.mark.parametrize("seed", [0] + [pytest.param(s, marks=pytest.mark.slow) for s in (1, 2)])
def test_ac33_every_change_is_on_disk_within_two_seconds(folder, game, seed):
    """600 ticks with changes at random times (AC-F12-33 asks for one run; seeds 1–2 are
    ``slow``)."""
    rng = random.Random(f"ac33:{seed}")
    h = Harness(folder, game=game)
    changes: list[tuple[float, int]] = []
    value = 0
    for k in range(600):
        t = k / 60
        h.tick(t)
        on_disk = h.disk()["values"].get("n", 0) if h.path.exists() else 0
        due = [v for tc, v in changes if t - tc >= 2.0]
        assert not due or on_disk >= due[-1], (t, on_disk, due[-1])
        if rng.random() < 0.15:
            value += 1
            h.store.set("n", value)
            changes.append((t, value))


def test_ac33_no_change_writes_nothing(folder, game, spy):
    folder.mkdir(parents=True)
    (folder / FILE_NAME).write_bytes(fileformat.encode_bytes(
        PersistentStore.with_data(values={"x": 1}, seen=[sid("a", 1)])))
    h = Harness(folder, game=game, defaults={"x": 0})
    h.ticks(10.0)
    assert spy.names == []


def test_ac33_flush_soon_writes_at_the_next_tick(folder, game, spy):
    h = Harness(folder, game=game)
    h.store.set("n", 1)
    h.tick(0.0)
    h.tick(0.1)
    h.store.set("n", 2)
    h.tick(0.2)
    assert len(spy.names) == 1
    h.sync.flush_soon()
    h.tick(0.2 + 1 / 60)
    assert len(spy.names) == 2 and h.disk()["values"] == {"n": 2}


def test_ac33_after_a_failure_no_retry_until_the_store_changes(folder, game, spy, monkeypatch,
                                                               warnings):
    h = Harness(folder, game=game)
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "write",
                      fail_when(os.write, lambda *_: True, oserror(errno.ENOSPC)))
        h.store.set("n", 1)
        h.tick(0.0)
        failed_at = h.store.version
        h.ticks(5.0)
        assert len(spy.names) == 1 and h.sync.failed_at == failed_at
        h.store.set("n", 2)
        h.ticks(1.1)
        assert len(spy.names) == 2
    assert len(warnings.of("W52")) == 1
    h.store.set("n", 3)
    h.ticks(1.1)
    assert len(spy.names) == 3 and h.disk()["values"] == {"n": 3}
    assert warnings.of(None).count(SAVED_AGAIN_TEXT) == 1


def test_ac33_a_mark_is_a_change(folder, game, spy):
    h = Harness(folder, game=game)
    h.store.mark_seen(sid("intro", 1))
    h.tick(0.0)
    assert spy.names == [FILE_NAME]
    assert h.disk()["seen"] == {"intro": "000000000001"}


@pytest.mark.parametrize("mode", [READ_ONLY, MEMORY], ids=["read_only", "memory"])
def test_ac33_read_only_and_memory_never_write(folder, game, spy, mode):
    folder.mkdir(parents=True)
    (folder / FILE_NAME).write_bytes(b"{")
    h = Harness(folder, game=game, mode=mode)
    for i in range(20):
        h.store.set("n", i)
        h.store.mark_seen(sid("a", i))
        h.ticks(0.5)
    h.sync.flush_soon()
    h.tick()
    assert h.sync.flush_now() is False
    h.sync.close()
    assert spy.names == [] and os.listdir(folder) == [FILE_NAME]
    assert (folder / FILE_NAME).read_bytes() == b"{"


# --- AC-F12-38 — merge rules ----------------------------------------------------------------------

def test_ac38_different_names_are_both_kept(folder, game):
    a, b = copies(folder, game)
    a.store.set("x", 1)
    write(a)
    b.store.set("y", 2)
    write(b)
    converge(a, b)
    for values in (a.disk()["values"], a.store.values_snapshot(), b.store.values_snapshot()):
        assert values == {"x": 1, "y": 2}


def test_ac38_the_last_writer_of_a_name_wins(folder, game):
    a, b = copies(folder, game)
    a.store.set("n", 1)
    write(a)
    b.store.set("n", 2)
    write(b)
    converge(a, b)
    assert a.disk()["values"] == {"n": 2}
    assert a.store.peek("n") == 2 and b.store.peek("n") == 2


def test_ac38_records_and_unlocks_are_united_in_first_seen_order(folder, game):
    a, b = copies(folder, game)
    a.store.mark_seen(sid("l", 1))
    a.store.mark_chosen(sid("m", 9), "00000000000c")
    a.store.unlock("cg", "a")
    write(a)
    b.store.mark_seen(sid("l", 2))
    b.store.mark_chosen(sid("m", 9), "00000000000d")
    b.store.unlock("cg", "b")
    write(b)
    converge(a, b)
    obj = a.disk()
    assert disk_records(obj, SEEN) == {sid("l", 1), sid("l", 2)}
    assert obj["chosen"] == {sid("m", 9): "00000000000c 00000000000d"}
    assert obj["unlocks"] == {"cg": ["a", "b"]}
    assert a.store.unlocked("cg") == ("a", "b") and b.store.unlocked("cg") == ("b", "a")
    assert list(a.store.records(SEEN)["l"].order) == ["000000000001", "000000000002"]
    assert list(b.store.records(SEEN)["l"].order) == ["000000000002", "000000000001"]


def test_ac38_after_clear_the_disk_values_are_ignored_and_records_united(folder, game):
    a, b = copies(folder, game)
    b.store.set("z", 3)
    b.store.mark_seen(sid("b", 1))
    write(b)
    a.store.set("keep", 1)
    a.store.clear()
    write(a)
    obj = a.disk()
    assert "z" not in obj["values"] and "z" not in a.store.names()
    assert disk_records(obj, SEEN) == {sid("b", 1)}
    converge(b, a)
    assert "z" not in b.store.names() and "z" not in a.disk()["values"]


def test_ac38_after_a_progress_clear_records_are_not_united_but_unlocks_are(folder, game):
    a, b = copies(folder, game)
    b.store.mark_seen(sid("s", 2))
    b.store.unlock("cg", "b")
    write(b)
    a.store.mark_seen(sid("s", 1))
    a.store.clear(progress=True)
    write(a)
    obj = a.disk()
    assert obj["seen"] == {} and not a.store.is_seen(sid("s", 2))
    assert obj["unlocks"] == {"cg": ["b"]} and a.store.unlocked("cg") == ("b",)


def test_ac38_after_reset_unlocks_are_not_united(folder, game):
    a, b = copies(folder, game)
    b.store.unlock("cg", "b")
    write(b)
    a.store.reset()
    write(a)
    assert a.disk()["unlocks"] == {"cg": []} and a.store.unlocked("cg") == ()


def test_ac38_a_delete_is_merged(folder, game):
    a, b = copies(folder, game)
    a.store.set("w", 1)
    write(a)
    converge(b, a)
    assert b.store.peek("w") == 1
    b.store.delete("w")
    write(b)
    assert "w" not in a.disk()["values"]
    converge(a, b)
    assert "w" not in a.store.names()
    with pytest.raises(PersistentNoValue):
        a.store.get("w")


def test_ac38_a_launch_default_gives_way_to_the_disk(folder, game):
    a, b = copies(folder, game, defaults={"festivals": 0})
    b.store.set("festivals", 4)
    write(b)
    a.store.mark_seen(sid("a", 1))
    write(a)
    assert a.store.peek("festivals") == 4 and a.disk()["values"]["festivals"] == 4


def test_ac38_a_file_deleted_mid_session_is_written_again_without_a_merge(folder, game,
                                                                          monkeypatch):
    a = Harness(folder, game=game)
    a.store.set("x", 1)
    write(a)
    (folder / FILE_NAME).unlink()
    a.store.set("y", 2)
    merges = []
    real = PersistentSync._merged
    monkeypatch.setattr(PersistentSync, "_merged", lambda self: merges.append(1) or real(self))
    write(a)
    assert merges == [] and a.disk()["values"] == {"x": 1, "y": 2}
    assert (folder / FILE_NAME).read_bytes() == a.encoded()


def test_ac38_a_big_merge_is_sliced(folder, game, monkeypatch):
    """120,000 sids on disk: the merge spans ≥ 3 ticks of ≤ MERGE_SLICE_S each, measured on
    an injected clock that advances 1 ms per ``ReadJob`` step."""
    clock = FakeClock(0.0)
    a, b = copies(folder, game, clock=clock)
    for label in range(120):
        for key in range(1_000):
            b.store.mark_seen(sid(f"l{label}", key))
    write(b)
    real_step = fileformat.ReadJob.step

    def step(self):
        clock.advance(0.001)
        return real_step(self)

    monkeypatch.setattr(fileformat.ReadJob, "step", step)
    a.store.mark_seen(sid("a", 1))
    a.tick(0.0)                               # A's write gets Changed
    spans = []
    while not spans or a.sync.merge is not None:
        start = clock.now
        a.tick()
        spans.append(clock.now - start)
    assert len(spans) >= 3
    assert max(spans) <= limits.MERGE_SLICE_S + 1e-9
    a.tick()
    assert len(disk_records(a.disk(), SEEN)) == 120_001


def _force_merges(monkeypatch, h: Harness, plants: list[bytes]) -> list:
    """Before each of ``h``'s next write cycles (before it encodes and looks at the file),
    another writer replaces the file with the next of ``plants``; returns the requests."""
    requests = []
    real = PersistentSync._submit
    left = list(plants)

    def submit(sync, now):
        if sync is h.sync and left:
            plant(h.path, left.pop(0))
        real(sync, now)
        if sync is h.sync:
            requests.append(sync.last_request)

    monkeypatch.setattr(PersistentSync, "_submit", submit)
    return requests


def _other(n: int) -> bytes:
    return fileformat.encode_bytes(PersistentStore.with_data(values={"o": n},
                                                             seen=[sid("o", n)]))


def test_ac38_after_three_merges_in_a_row_the_request_is_unchecked(folder, game, monkeypatch):
    a = Harness(folder, game=game)
    a.store.set("x", 1)
    write(a)
    requests = _force_merges(monkeypatch, a, [_other(1), _other(2), _other(3)])
    a.store.set("x", 2)
    write(a)
    assert [r.check for r in requests] == [True, True, True, False]
    assert a.sync.merges_in_row == 0                         # Written reset it
    obj = a.disk()
    assert obj["values"]["x"] == 2 and disk_records(obj, SEEN) >= {sid("o", 3)}


# --- AC-F12-39 — random interleavings; group H --------------------------------------------------

DELETED = object()


class Copy:
    """The test's own account of one copy: the values it set since its last successful
    write (``DELETED`` for a delete without a default) and whether it cleared since."""

    def __init__(self) -> None:
        self.pending: dict[str, object] = {}
        self.cleared = False
        self.kept: dict[str, set[str]] = {SEEN: set(), CHOSEN: set()}   # since its clear


class Oracle:
    """The file's values as the writes that reached it define them (per name, the last value
    set by a copy that changed it, applied when that copy's write lands; a write after
    ``_clear()`` replaces them all), every record made, and every unlock. Built only from
    the operations the test performed, never from a store."""

    def __init__(self, defaults: dict) -> None:
        self.defaults = dict(defaults)
        self.values = dict(defaults)
        self.made: dict[str, set[str]] = {SEEN: set(), CHOSEN: set()}
        self.copies = {me: Copy() for me in "AB"}
        self.unlocks: set[tuple[str, str]] = set()
        self.forced = 0

    def written(self, me: str, memory: dict | None = None) -> None:
        """``me``'s write landed. ``memory``: the copy's values, for a write after
        ``MERGES_IN_A_ROW_MAX`` merges in a row, which writes them all (SEC-F12-08)."""
        copy = self.copies[me]
        self.forced += memory is not None
        if memory is not None:
            self.values = self.effective(memory)
        elif copy.cleared:
            self.values = dict(self.defaults)
        for name, value in copy.pending.items():
            if value is DELETED:
                self.values.pop(name, None)
            else:
                self.values[name] = value
        copy.pending = {}
        copy.cleared = False

    def effective(self, values: dict) -> dict:
        return {**self.defaults, **values}


def _watch_writes(monkeypatch, hs: dict, oracle: Oracle) -> None:
    """When a copy's write lands (the synchronous writer's result is ``Written``), apply that
    copy's changes to the oracle, in the order the writes reached the disk. A copy handles a
    ``Changed`` at its next tick, so the other copy may write in between and merges can come
    three in a row; the write after them writes the copy's memory (SEC-F12-08)."""
    real = WriterClient.submit

    def submit(client, job):
        me = next(me for me, h in hs.items() if h.sync._client is client)
        h = hs[me]
        forced = h.sync.merges_in_row >= limits.MERGES_IN_A_ROW_MAX
        memory = h.store.values_snapshot() if forced else None
        real(client, job)
        if isinstance(client._results[-1], Written):
            oracle.written(me, memory)

    monkeypatch.setattr(WriterClient, "submit", submit)


NAMES = ("a", "b", "c", "festivals")
DEFAULTS = {"festivals": 0, "c": "x"}


def _random_op(rng: random.Random, h: Harness, me: str, oracle: Oracle, serial: list) -> None:
    store = h.store
    copy = oracle.copies[me]
    roll = rng.random()
    if roll < 0.25:
        serial[0] += 1
        name = rng.choice(NAMES)
        store.set(name, serial[0])
        copy.pending[name] = serial[0]
    elif roll < 0.33:
        name = rng.choice(NAMES)
        try:
            store.delete(name)
        except PersistentNoValue:
            return
        copy.pending[name] = DEFAULTS.get(name, DELETED)
    elif roll < 0.38:
        progress = roll >= 0.36
        store.clear(progress=progress)
        copy.pending = {}
        copy.cleared = True
        if progress:
            copy.kept = {SEEN: set(), CHOSEN: set()}
    elif roll < 0.55:
        s = sid(rng.choice(("l1", "l2", "l3")), rng.randrange(40))
        store.mark_seen(s)
        oracle.made[SEEN].add(s)
        copy.kept[SEEN].add(s)
    elif roll < 0.62:
        menu, key = sid("m", rng.randrange(3)), f"{rng.randrange(8):012x}"
        store.mark_chosen(menu, key)
        oracle.made[CHOSEN].add(f"{menu}#{key}")
        copy.kept[CHOSEN].add(f"{menu}#{key}")
    elif roll < 0.68:
        pair = (rng.choice(("cg", "end")), f"u{rng.randrange(10)}")
        store.unlock(*pair)
        oracle.unlocks.add(pair)
    else:
        h.tick(h.now + rng.choice((0.05, 0.3, 0.7, 1.2, 2.0)))


def run_interleaving(folder: Path, game: Path, seed: str, ops: int, monkeypatch) -> None:
    rng = random.Random(seed)
    oracle = Oracle(DEFAULTS)
    hs = {}
    for me in "AB":
        h = Harness(folder, game=game, defaults=DEFAULTS)
        for kind in ("cg", "end"):
            h.store.register_kind(kind)
        hs[me] = h
    serial = [0]
    with monkeypatch.context() as patch:
        _watch_writes(patch, hs, oracle)
        patch.setattr(safefile, "_fsync_file", lambda fd: None)      # speed only: the merge
        patch.setattr(safefile, "_fsync_folder", lambda folder: None)  # logic is what's tested
        for _ in range(ops):
            me = rng.choice("AB")
            _random_op(rng, hs[me], me, oracle, serial)
        for me in "ABAB":                    # the end: each copy writes after the other's
            h = hs[me]
            s = sid(f"end{me}", serial[0])
            serial[0] += 1
            h.store.mark_seen(s)
            oracle.made[SEEN].add(s)
            oracle.copies[me].kept[SEEN].add(s)
            write(h)
    obj = hs["A"].disk()
    assert oracle.effective(obj["values"]) == oracle.values, seed
    for form in (SEEN, CHOSEN):
        final = disk_records(obj, form)
        lower = oracle.copies["A"].kept[form] | oracle.copies["B"].kept[form]
        assert lower <= final <= oracle.made[form], (seed, form)
    assert disk_unlocks(obj) == oracle.unlocks, seed
    b = hs["B"]
    assert (folder / FILE_NAME).read_bytes() == b.encoded(), seed
    for form in (SEEN, CHOSEN):
        assert records(b.store, form) == disk_records(obj, form), seed
    assert store_unlocks(b.store) == oracle.unlocks
    assert oracle.effective(b.store.values_snapshot()) == oracle.values, seed
    assert temps(folder) == []


@pytest.mark.parametrize("chunk", range(10))
def test_ac39_random_interleavings(folder, game, monkeypatch, chunk):
    """100 interleavings × 50 operations, in 10 chunks of 10."""
    for i in range(10):
        sub = folder.parent / f"run{i}" / "persistent"
        run_interleaving(sub, game, f"ac39:{chunk}:{i}", 50, monkeypatch)


@pytest.mark.slow
@pytest.mark.parametrize("chunk", range(10))
def test_ac39_random_interleavings_slow(folder, game, monkeypatch, chunk):
    """1,000 interleavings × 1,000 operations, in 10 chunks of 100."""
    for i in range(100):
        sub = folder.parent / f"run{i}" / "persistent"
        run_interleaving(sub, game, f"ac39-slow:{chunk}:{i}", 1_000, monkeypatch)


def test_ac39_a_replace_before_ours_gives_changed_and_we_merge(folder, game, monkeypatch):
    """Group H, SEC-F12-06(c): B replaces the file after A's fsync, before A's replace. A's
    final stamp check catches it: A gets ``Changed``, its temp file is removed, B's bytes stay
    intact, and A merges and writes."""
    a, b = copies(folder, game)
    a.store.set("x", 1)
    write(a)
    b.store.mark_seen(sid("b", 1))
    b.store.set("y", 2)
    a.store.mark_seen(sid("a", 1))
    real_fsync = os.fsync
    state = {"inside": False, "done": False}

    def fsync(fd):
        real_fsync(fd)
        if not state["done"] and not state["inside"]:
            state["inside"] = True
            write(b)                           # B's whole write, inside A's
            state["inside"] = False
            state["done"] = True

    results = []
    real_handle = PersistentSync._handle
    monkeypatch.setattr(PersistentSync, "_handle",
                        lambda self, r: results.append((self, r)) or real_handle(self, r))
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "fsync", fsync)
        a.tick(10.0)
    b_bytes = b.path.read_bytes()
    assert state["done"] and temps(folder) == []
    assert (folder / FILE_NAME).read_bytes() == b_bytes == b.encoded()
    a.tick()
    assert any(s is a.sync and isinstance(r, Changed) for s, r in results)
    a.tick()
    obj = a.disk()
    assert obj["values"] == {"x": 1, "y": 2}
    assert disk_records(obj, SEEN) == {sid("a", 1), sid("b", 1)}
    assert (folder / FILE_NAME).read_bytes() == a.encoded()


@pytest.mark.slow
def test_ac39_a_real_pair_of_processes(folder, game, tmp_path):
    """Two ``python -I tests/persist/copy_worker.py`` processes with threaded writers, 1,000
    random operations each, on one folder."""
    worker = MAIN.parent / "copy_worker.py"
    folder.mkdir(parents=True)
    outs = [tmp_path / f"out{i}.json" for i in range(2)]
    procs = [subprocess.Popen([sys.executable, "-I", str(worker), str(folder), str(i),
                               "1000", str(outs[i])],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for i in range(2)]
    for proc in procs:
        out, err = proc.communicate(timeout=240)
        assert proc.returncode == 0, err.decode(errors="replace")
    made = [json.loads(o.read_text()) for o in outs]
    data = (folder / FILE_NAME).read_bytes()
    store = PersistentStore(identity_scheme=1)
    assert fileformat.ReadJob(data, store, None).run().kind is fileformat.Outcome.OK
    seen = records(store, SEEN)
    unlocks = store_unlocks(store)
    for m in made:
        assert set(m["seen"]) <= seen
        assert {tuple(u) for u in m["unlocks"]} <= unlocks
    print("pair:", [(m["requests"], m["merges"]) for m in made])
    assert all(m["requests"] > 50 for m in made) and sum(m["merges"] for m in made) > 0
    assert temps(folder) == []


# --- AC-F12-40 — bad, unreadable, and newer files found by a merge --------------------------------

NEWER = dumps({"format": 2, "identity_scheme": 1, "values": {}, "seen": {}, "chosen": {},
               "unlocks": {}, "extra": 1})


def _mid_session(folder, game) -> Harness:
    h = Harness(folder, game=game)
    h.store.set("ours", 1)
    h.store.mark_seen(sid("ours", 1))
    write(h)
    h.store.set("ours", 2)
    return h


def test_ac40_a_bad_file_is_moved_aside_and_ours_written(folder, game, warnings):
    h = _mid_session(folder, game)
    plant(h.path, b"{")
    write(h)
    assert (folder / BAD_NAME).read_bytes() == b"{"
    assert h.path.read_bytes() == h.encoded() and h.disk()["values"] == {"ours": 2}
    assert warnings.of("W50") == [bad_file_text(h.store.display, "not valid JSON", kept=True,
                                                mid_session=True)]
    plant(h.path, b"[1, 2")
    h.store.set("ours", 3)
    write(h)
    assert (folder / BAD_NAME).read_bytes() == b"[1, 2"
    assert h.disk()["values"] == {"ours": 3}
    assert len(warnings.of("W50")) == 1 and h.sync.mode is WRITABLE
    assert [n.code for n in h.sync.take_notices()] == ["W50"]


def test_ac40_a_bad_file_that_cant_be_moved_makes_the_session_read_only(folder, game,
                                                                         warnings, spy):
    h = _mid_session(folder, game)
    (folder / BAD_NAME).mkdir()
    plant(h.path, b"{")
    writes = len(spy.names)
    assert h.sync.flush_now() is False
    assert h.sync.mode is READ_ONLY and h.path.read_bytes() == b"{"
    h.store.set("ours", 9)
    h.ticks(3.0)
    h.sync.close()
    assert len(spy.names) == writes and h.path.read_bytes() == b"{"
    assert warnings.of("W50") == [bad_file_text(h.store.display, "not valid JSON", kept=False,
                                                mid_session=True)]


def test_ac40_an_unreadable_file_is_left_alone_and_the_session_read_only(folder, game,
                                                                          warnings, monkeypatch):
    """``07`` I-6 / SEC-F12-03(c): W50 ``couldn't be read`` once, no rename, READ_ONLY, the
    file unchanged (the writer read it ``IO_TRIES`` times)."""
    h = _mid_session(folder, game)
    plant(h.path, b'{"other": 1}')
    with monkeypatch.context() as patch:
        patch.setattr(safefile.os, "read",
                      fail_when(os.read, lambda *_: True, oserror(errno.EIO)))
        assert h.sync.flush_now() is False
    assert h.sync.mode is READ_ONLY
    assert h.path.read_bytes() == b'{"other": 1}' and not (folder / BAD_NAME).exists()
    assert h.sleep == [0.05, 0.05]
    assert warnings.of("W50") == [bad_file_text(h.store.display, "couldn't be read",
                                                kept=False, mid_session=True)]


def test_ac40_a_newer_file_is_never_overwritten(folder, game, warnings, spy):
    h = _mid_session(folder, game)
    plant(h.path, NEWER)
    assert h.sync.flush_now() is False
    assert h.sync.mode is READ_ONLY and h.path.read_bytes() == NEWER
    h.store.set("ours", 5)
    h.ticks(3.0)
    h.sync.close()
    assert h.path.read_bytes() == NEWER
    assert warnings.of("W51") == [newer_file_text(h.store.display, mid_session=True)]
    assert [n.code for n in h.sync.take_notices()] == ["W51"]


def test_ac40_a_newer_file_planted_after_three_forced_merges_is_kept(folder, game, warnings,
                                                                      monkeypatch):
    h = _mid_session(folder, game)
    requests = _force_merges(monkeypatch, h, [_other(1), _other(2), _other(3), NEWER])
    write_ok = h.sync.flush_now()
    assert write_ok is False and h.sync.mode is READ_ONLY
    assert [r.check for r in requests] == [True, True, True, True]
    assert h.path.read_bytes() == NEWER
    assert len(warnings.of("W51")) == 1


def test_ac40_a_bad_file_planted_after_three_forced_merges_is_moved_first(folder, game,
                                                                          warnings, monkeypatch):
    h = _mid_session(folder, game)
    requests = _force_merges(monkeypatch, h, [_other(1), _other(2), _other(3), b"{"])
    write(h)
    assert (folder / BAD_NAME).read_bytes() == b"{"
    assert [r.check for r in requests] == [True, True, True, True, False]
    assert h.path.read_bytes() == h.encoded()
    assert len(warnings.of("W50")) == 1


def test_ac40_after_three_merges_values_are_not_merged(folder, game, monkeypatch):
    """SEC-F12-08: a fourth merge in a row classifies and unites records, but skips values."""
    h = _mid_session(folder, game)
    other = fileformat.encode_bytes(PersistentStore.with_data(values={"theirs": 1},
                                                              seen=[sid("t", 1)]))
    requests = _force_merges(monkeypatch, h, [_other(1), _other(2), _other(3), other])
    write(h)
    assert len(requests) == 5 and requests[-1].check is False
    obj = h.disk()
    assert "theirs" not in obj["values"] and sid("t", 1) in disk_records(obj, SEEN)
