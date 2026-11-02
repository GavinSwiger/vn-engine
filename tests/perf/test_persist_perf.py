"""F12 performance (checklist step 6; ``04`` §11; 06 §1.10): AC-F12-46 (launch read and
checks at the caps) and the sync half of AC-F12-45 (frames while saving), on the ADR-0005
reference machine or a recorded stand-in (``perf``; never CI). AC-F12-37 is the CI guard
(``tests/persist/test_sync.py``).

Run (cmd; in PowerShell use ``$env:VN_PERF = "1"``)::

    set VN_PERF=1
    .venv/Scripts/python -m pytest -m perf -s tests/perf/test_persist_perf.py

``VN_PERSIST_BENCH_S`` shortens AC-F12-45's 600 s run for a try-out (the report needs 600).
Attach the printed ``AC-F12-4x`` lines, the PassMark single-thread score, and the disk type
(NVMe, SATA SSD, or HDD) to the test report.

**AC-F12-45 coverage.** This bench runs the frame loop's persistent half for real: one
``PersistentSync`` on the threaded writer and the real disk, ``update`` once per 1/60 s
frame, a new seen line every frame (auto-advance) and a value change every second, so a
write starts every second. It measures every ``update``, every encode, and the main
thread's wait on the writer (``submit``). Long frames and work p99 of F03's bench scene on
auto-advance need F15's auto mode in the window; until then they are the window bench's
(``tests/perf/test_runtime_perf.py``) plus these per-frame costs.
"""

import gc
import json
import os
import time
import tracemalloc
from types import SimpleNamespace

import pytest

from engine.app.persistence import install_persistence, open_for_launch
from engine.persist.fileformat import PieceEncoder, encode_bytes
from engine.persist.location import FILE_NAME
from engine.persist.writer import Writer, WriterClient
from engine.runtime.persistent import CHOSEN, PersistentStore

pytestmark = pytest.mark.perf

MIB = 1 << 20


def _sid(label: int, key: int) -> str:
    return f"l{label}/{key:012x}"


def cap_store() -> PersistentStore:
    """AC-F12-46's store: 1,000,000 sids, about 1 MiB of values, 100,000 choice marks, and
    32 kinds × 100 unlocks."""
    store = PersistentStore(identity_scheme=1)
    for label in range(1_000):
        for key in range(1_000):
            store.mark_seen(_sid(label, key))
    for i in range(1_000):
        store.set(f"v{i}", {"text": "x" * 1_000, "n": i})
    for menu in range(10_000):
        for key in range(10):
            store.mark_chosen(f"m{menu}/{menu:012x}", f"{key:012x}")
    for kind in range(32):
        store.register_kind(f"k{kind}")
        for name in range(100):
            store.unlock(f"k{kind}", f"n{name}")
    return store


def seen_cap_store() -> PersistentStore:
    """AC-F12-45's store at the seen cap: 1,000,000 sids and about 10 KB of values."""
    store = PersistentStore(identity_scheme=1)
    for label in range(1_000):
        for key in range(1_000):
            store.mark_seen(_sid(label, key))
    for i in range(100):
        store.set(f"v{i}", "x" * 90)
    return store


def typical_store() -> PersistentStore:
    """50,000 sids and about 10 KB of values (AC-F12-45's typical store)."""
    store = PersistentStore(identity_scheme=1)
    for label in range(500):
        for key in range(100):
            store.mark_seen(_sid(label, key))
    for i in range(100):
        store.set(f"v{i}", "x" * 90)
    return store


# --- AC-F12-46 — launch and checks at the caps ------------------------------------------------

def test_ac46_launch_read_at_the_caps(tmp_path):
    game = tmp_path / "game"
    (game / "persistent").mkdir(parents=True)
    data = encode_bytes(cap_store())
    (game / "persistent" / FILE_NAME).write_bytes(data)
    size_mb = len(data) / 1e6
    del data
    gc.collect()
    launch = open_for_launch(None, game_root=game, release=False, app_id=None)
    times = []
    total_start = time.perf_counter()
    while not launch.done:
        start = time.perf_counter()
        launch.step()
        times.append(time.perf_counter() - start)
    total = time.perf_counter() - total_start
    store = launch.store
    # The memory of the store, from a second read under tracemalloc (which slows it).
    (game / "persistent" / FILE_NAME).write_bytes(encode_bytes(cap_store()))
    gc.collect()
    tracemalloc.start()
    try:
        traced = open_for_launch(None, game_root=game, release=False, app_id=None).run()
        gc.collect()
        memory = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    del traced
    # Above 0.9 × a cap the read trims to it (04 §7.4 step 5.7; W57): no program here.
    assert store.record_total("seen") >= 900_000 and store.record_total(CHOSEN) >= 90_000
    # The parse is the second step (after the pre-scan).
    parse = times[1]
    others = times[:1] + times[2:]
    print(f"\nAC-F12-46 file {size_mb:.1f} MB: {len(times)} steps, parse {parse * 1e3:.1f} ms, "
          f"longest other step {max(others) * 1e3:.1f} ms, total {total:.3f} s, store "
          f"{memory / MIB:.1f} MiB")
    assert parse <= 0.100
    assert max(others) <= 0.060
    assert total <= 0.8
    assert memory <= 65 * MIB


def test_ac46_check_in_place_with_one_mib_of_watched_values():
    store = PersistentStore(identity_scheme=1)
    for i in range(100):
        store.set(f"d{i}", {f"k{j}": "x" * 90 for j in range(100)})
    assert 0.9 * MIB <= store.values_bytes <= 1.05 * MIB
    for i in range(100):
        store.get(f"d{i}")                            # read by author code: watched
    store.get("d0")["k0"] = "y" * 90                  # one change in place
    gc.disable()
    try:
        runs = []
        for _ in range(5):
            start = time.perf_counter()
            store.check_in_place()
            runs.append(time.perf_counter() - start)
    finally:
        gc.enable()
    print(f"\nAC-F12-46 check_in_place, 1 MiB watched: max {max(runs) * 1e3:.2f} ms")
    assert max(runs) <= 0.016


# --- AC-F12-45 — frames while saving (the sync half) ------------------------------------------

@pytest.mark.parametrize("which", ["typical", "seen-cap"])
def test_ac45_frames_while_saving(tmp_path, monkeypatch, which):
    seconds = float(os.environ.get("VN_PERSIST_BENCH_S", "600"))
    game = tmp_path / "game"
    (game / "persistent").mkdir(parents=True)
    store = typical_store() if which == "typical" else seen_cap_store()
    (game / "persistent" / FILE_NAME).write_bytes(encode_bytes(store))
    del store
    launch = open_for_launch(None, game_root=game, release=False, app_id=None).run()
    writer = Writer(threaded=True)
    sync = install_persistence(SimpleNamespace(writer=writer, persist=None), launch)
    while not sync.warm(sync.clock() + 0.05):
        pass
    encodes, submits = [], []
    real_encode = PieceEncoder.encode
    real_submit = WriterClient.submit

    def encode(self, s):
        start = time.perf_counter()
        out = real_encode(self, s)
        encodes.append(time.perf_counter() - start)
        return out

    def submit(self, job):
        start = time.perf_counter()
        real_submit(self, job)
        submits.append(time.perf_counter() - start)

    monkeypatch.setattr(PieceEncoder, "encode", encode)
    monkeypatch.setattr(WriterClient, "submit", submit)
    updates = []
    frames = int(seconds * 60)
    store = sync.store
    try:
        gc.disable()
        next_frame = time.perf_counter()
        for k in range(frames):
            store.mark_seen(_sid(5_000 + k // 100, k % 100))      # auto-advance: a line a frame
            if k % 60 == 0:
                store.set("v0", k)
            start = time.perf_counter()
            sync.update(start)
            updates.append(time.perf_counter() - start)
            next_frame += 1 / 60
            delay = next_frame - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
    finally:
        gc.enable()
        sync.close(until=writer.quit_deadline())
        writer.stop(writer.quit_deadline())
    written = json.loads((game / "persistent" / FILE_NAME).read_bytes())
    assert written["values"]["v0"] == (frames - 1) // 60 * 60
    print(f"\nAC-F12-45 {which}: {frames} frames, {sync.requests} writes; update max "
          f"{max(updates) * 1e3:.3f} ms, p99 {sorted(updates)[int(len(updates) * 0.99)] * 1e3:.3f}"
          f" ms; encode max {max(encodes) * 1e3:.3f} ms; writer wait max "
          f"{max(submits) * 1e3:.3f} ms")
    assert sync.requests >= seconds * 0.9
    assert max(submits) <= 0.001
    if which == "typical":
        assert max(updates) <= 0.001
    else:
        assert max(encodes) <= 0.002
