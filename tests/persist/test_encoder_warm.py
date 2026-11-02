"""The encoder's caches and warm-up (F12 checklist step 5; ``04`` §7.5 encoder, invariant 10):
a write never costs a full encode on a frame.

- The cached output always equals a fresh encode of the same store, whatever the store did
  in between (random operations, partial warm-ups, small blocks and segments).
- The first build is done in slices: a cold encode of a hostile store of 400,000 one-key
  labels takes seconds, so ``PieceEncoder.warm`` builds it in slices that end at a deadline,
  and the sync writes only once it is warm. Default tier: the smallest store whose cold
  encode is over a frame (20,000 labels), with work counted on an injected clock. ``slow``:
  the real 400,000 labels in real time.
- The store's record journal says which runs changed (``RecordJournal``)."""

import gc
import random
import time

import pytest

from engine.persist import fileformat, limits
from engine.persist.fileformat import PieceEncoder, encode_bytes
from engine.runtime.persistent import CHOSEN, SEEN, PersistentStore
from tests.persist.helpers import FakeProgram
from tests.persist.sync_support import Harness, sid
from tests.persist.writer_support import base, game  # noqa: F401


def hostile_store(labels: int) -> PersistentStore:
    store = PersistentStore(identity_scheme=1)
    for i in range(labels):
        store.load_keys(SEEN, f"l{i}", [f"{i:012x}"])
    return store


class Counter:
    """A clock that moves 0.1 ms per read (each read stands for a bit of work)."""

    def __init__(self) -> None:
        self.now = 0.0
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        self.now += 0.0001
        return self.now


# --- The cache follows the store ---------------------------------------------------------------

def _random_change(rng: random.Random, store: PersistentStore, serial: list) -> None:
    roll = rng.random()
    serial[0] += 1
    if roll < 0.4:
        store.mark_seen(sid(f"l{rng.randrange(30)}", rng.randrange(60)))
    elif roll < 0.5:
        store.mark_chosen(sid(f"m{rng.randrange(6)}", 1), f"{rng.randrange(20):012x}")
    elif roll < 0.58:
        store.load_keys(SEEN, f"l{rng.randrange(40)}",
                        [f"{rng.randrange(200):012x}" for _ in range(rng.randrange(1, 12))])
    elif roll < 0.64:
        runs = list(store.records(SEEN))
        if runs:
            store.drop_record(SEEN, rng.choice(runs))
    elif roll < 0.70:
        runs = list(store.records(SEEN).items())
        if runs:
            group, run = rng.choice(runs)
            store.remove_keys(SEEN, group, run.order[: rng.randrange(1, 4)])
    elif roll < 0.72:
        store.clear(progress=True)
    elif roll < 0.73:
        store.reset()
    elif roll < 0.85:
        kind = rng.choice(("cg", "end", "music"))
        if kind not in dict(store.kind_items()) or not dict(store.kind_items())[kind].registered:
            store.register_kind(kind)
        store.unlock(kind, f"n{rng.randrange(50)}")
    elif roll < 0.88:
        kinds = [k for k, _ in store.kind_items()]
        if kinds:
            store.drop_unlocks(rng.choice(kinds), rng.randrange(1, 4))
    else:
        store.set(f"v{rng.randrange(8)}", serial[0])


@pytest.mark.parametrize("seed", range(12))
def test_cached_output_equals_a_fresh_encode(seed, monkeypatch, warnings):
    monkeypatch.setattr(limits, "BLOCK_KEYS", 3)
    monkeypatch.setattr(fileformat, "SEGMENT_GROUPS", 4)
    monkeypatch.setattr(fileformat, "WARM_CHECK", 2)
    rng = random.Random(f"warm:{seed}")
    store = PersistentStore(identity_scheme=1)
    serial = [0]
    for _ in range(40):
        _random_change(rng, store, serial)
    encoder = PieceEncoder(FakeProgram())
    clock = Counter()
    for _ in range(300):
        for _ in range(rng.randrange(4)):
            _random_change(rng, store, serial)
        if rng.random() < 0.6:
            encoder.warm(store, clock() + rng.choice((0.0, 0.0002, 0.001)), clock)
        if rng.random() < 0.3:
            assert b"".join(encoder.encode(store)) == encode_bytes(store), seed
    assert b"".join(encoder.encode(store)) == encode_bytes(store), seed
    encoder.detach()
    assert store._journals == []


def test_a_trim_keeps_the_cache_right(monkeypatch, warnings):
    store = PersistentStore(identity_scheme=1)
    for g in range(100):
        store.mark_seen(sid(f"l{g}", 1))
    encoder = PieceEncoder(FakeProgram(labels=[f"l{g}" for g in range(50, 100)]))
    full = fileformat.count_structure(b"".join(encoder.encode(store)))
    monkeypatch.setattr(limits, "PRESCAN_MAX", full - 20)
    data = b"".join(encoder.encode(store))
    assert data == encode_bytes(store)
    assert sorted(set(f"l{g}" for g in range(100)) - set(store.records(SEEN))) == \
        sorted(f"l{g}" for g in range(10))
    store.mark_seen(sid("l99", 2))
    store.mark_seen(sid("new", 1))
    assert b"".join(encoder.encode(store)) == encode_bytes(store)


def test_a_detached_encoder_leaves_no_journal():
    store = hostile_store(10)
    encoder = PieceEncoder()
    encoder.encode(store)
    assert len(store._journals) == 1
    encode_bytes(store)
    assert len(store._journals) == 1
    encoder.detach()
    assert store._journals == []


# --- The journal ----------------------------------------------------------------------------------

def test_the_journal_records_created_grown_and_dropped_runs():
    store = PersistentStore(identity_scheme=1)
    store.mark_seen(sid("old", 1))
    journal = store.open_journal()
    store.mark_seen(sid("a", 1))
    store.mark_seen(sid("old", 2))
    store.drop_record(SEEN, "a")
    store.mark_seen(sid("b", 1))
    store.mark_seen(sid("a", 2))                 # re-created: moved to the end
    store.mark_chosen(sid("m", 1), "000000000003")
    assert store.take_journal(journal, SEEN) == (False, {"old": False, "b": True, "a": True})
    assert store.take_journal(journal, SEEN) == (False, {})
    assert store.take_journal(journal, CHOSEN) == (False, {sid("m", 1): True})
    store.mark_seen(sid("b", 2))
    store.clear(progress=True)
    store.mark_seen(sid("c", 1))
    assert store.take_journal(journal, SEEN) == (True, {"c": True})
    store.close_journal(journal)
    store.mark_seen(sid("d", 1))
    assert journal.touched[SEEN] == {}


# --- Warm-up in slices (frame budget) -------------------------------------------------------------

def test_warm_up_is_sliced_and_encode_then_costs_only_the_changes(monkeypatch):
    """20,000 one-key labels (a cold encode is several frames long): with each clock read
    standing for 0.1 ms of work, a 0.5 ms slice builds at most ``WARM_CHECK`` runs, so the
    warm-up takes many slices; once warm, an encode builds only the changed runs' blocks."""
    store = hostile_store(20_000)
    encoder = PieceEncoder()
    clock = Counter()
    blocks = []
    real_block = fileformat._block
    monkeypatch.setattr(fileformat, "_block", lambda keys: blocks.append(1) or real_block(keys))
    slices = 0
    worst = 0
    while True:
        slices += 1
        before = len(blocks)
        done = encoder.warm(store, clock() + limits.ENCODE_SLICE_S, clock)
        worst = max(worst, len(blocks) - before)
        if done:
            break
    assert slices >= 20_000 // fileformat.WARM_CHECK // 6
    assert worst <= 6 * fileformat.WARM_CHECK
    assert encoder.is_warm
    blocks.clear()
    store.mark_seen(sid("l7", 99))
    store.mark_seen(sid("brand_new", 1))
    data = b"".join(encoder.encode(store))
    assert len(blocks) == 2 and data == encode_bytes(store)


def test_the_sync_writes_only_once_the_encoder_is_warm(game, monkeypatch):
    """Harness Y with an injected clock: a change made at launch is written only after the
    warm-up slices, and no update builds more than a slice's worth of runs."""
    clock = Counter()
    h = Harness(game / "persistent", game=game, store=hostile_store(5_000), clock=clock)
    blocks = []
    real_block = fileformat._block
    monkeypatch.setattr(fileformat, "_block", lambda keys: blocks.append(1) or real_block(keys))
    h.store.set("x", 1)
    ticks = 0
    while not h.path.exists():
        before = len(blocks)
        h.tick()
        ticks += 1
        assert len(blocks) - before <= 6 * fileformat.WARM_CHECK + 2
    assert ticks >= 5
    h.tick()
    assert h.disk()["values"] == {"x": 1} and len(h.disk()["seen"]) == 5_000


@pytest.mark.slow
def test_warm_up_of_a_hostile_store_never_blocks_a_frame():
    """400,000 one-key labels, real time: the cold encode takes seconds; warm-up slices of
    ``ENCODE_SLICE_S`` stay far below a frame (≤ 25 ms, the worst being a dict resize of
    the cache), and a write's encode once warm is ≤ 10 ms."""
    store = hostile_store(400_000)
    gc.disable()
    try:
        start = time.perf_counter()
        cold = encode_bytes(store)
        cold_s = time.perf_counter() - start
        encoder = PieceEncoder()
        slices, worst, total = 0, 0.0, 0.0
        while True:
            start = time.perf_counter()
            done = encoder.warm(store, start + limits.ENCODE_SLICE_S, time.perf_counter)
            took = time.perf_counter() - start
            slices, worst, total = slices + 1, max(worst, took), total + took
            if done:
                break
        store.mark_seen(sid("l5", 77))
        store.mark_seen(sid("fresh", 1))
        start = time.perf_counter()
        pieces = encoder.encode(store)
        encode_s = time.perf_counter() - start
    finally:
        gc.enable()
    print(f"400k labels: cold encode {cold_s:.2f} s; warm-up {total:.2f} s in {slices} slices, "
          f"worst {worst * 1000:.1f} ms; encode once warm {encode_s * 1000:.2f} ms")
    assert cold_s > 0.5 and slices > 100
    assert worst <= 0.025 and encode_s <= 0.010
    assert b"".join(pieces) == encode_bytes(store) and len(cold) > 9_000_000
