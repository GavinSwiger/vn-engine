"""F19 step 6 — the cost of endings and routes (``04-technical.md`` §9 invariant 10, §11;
``06-acceptance.md`` AC-F19-33; ``07-architecture-review.md`` I-4).

The bench story is written under ``tmp_path`` and loaded once per module: 1,000 ``ending``
lines and 1,000 ``lock route`` declarations of 32 ``until`` endings each (the limits, E246
and E243), installed through ``endings.register`` on a store (``with_data``) that holds every
ending, so every route is open through its ``until`` list.

**Default tier (CI guards: a count and a ratio).**
- Count: the first ``persistent.routes`` read after a change to the unlock names makes
  ≤ 32,000 ``is_unlocked`` calls and the next read none; the first ``persistent.endings``
  read after a change makes ≤ 1,000 ``EndingIndex.has`` calls and the next none.
- Ratio: the median of 5 ``merge_kind`` runs on 10,000 names (half of them new, half of the
  store's gone from the file) is ≤ 20 × the median on 1,000 names.

**``perf``: the reference-machine run (owner).** ADR-0005: Intel Core i5-8250U, Windows 11,
mains power, "Balanced" plan; or a stand-in with a PassMark single-thread score of at most
2,000. No window opens (about 5 s). From the project root, in cmd::

    set VN_PERF=1
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_endings_perf.py

(In PowerShell: ``$env:VN_PERF = "1"``, then the same command.) Each row is the median of
21 runs after 3 warm-up runs, ``gc`` on; attach the printed ``AC-F19-33`` line and the
machine's PassMark single-thread score to the test report (06 §7):

- a cache-missing ``persistent.routes`` read at the limits ≤ 1.5 ms;
- ``merge_kind`` on 10,000 names ≤ 4 ms;
- after ``relock`` of a 10,000-name kind on a warm ``PieceEncoder``, the sync's
  ``encoder.warm(store, clock() + ENCODE_SLICE_S, clock)`` calls until one returns True
  (the frame loop's slices; the ``relock`` counts in the first): the longest call
  ≤ 2.5 ms, and the ``encode`` after them ≤ 0.5 ms (04 §11 as amended by the F12
  architect: a cold ``encode`` never runs in a frame).
"""

import statistics
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.paths import GamePaths
from engine.persist.fileformat import PieceEncoder
from engine.persist.limits import ENCODE_SLICE_S
from engine.runtime import endings
from engine.runtime.endings import ENDING_KIND, ROUTE_KIND, EndingIndex
from engine.runtime.limits import UNLOCK_NAMES_MAX
from engine.runtime.persistent import PersistentStore
from engine.script import load_story
from engine.script.program import Program
from engine.script.routes import ENDINGS_MAX, ROUTES_MAX, UNTIL_MAX

_program: Program | None = None


def bench_program(root: Path) -> Program:
    """The bench story (module docstring), loaded once."""
    global _program
    if _program is None:
        lines = ["label start:"]
        lines += [f'    ending e{i} "Ending {i}"' for i in range(ENDINGS_MAX)]
        for r in range(ROUTES_MAX):
            until = ", ".join(f"e{(r + k) % ENDINGS_MAX}" for k in range(UNTIL_MAX))
            lines += [f"label r{r}:", "    return", f'lock route r{r} "Route {r}" until {until}']
        script = root / "script"
        script.mkdir(parents=True)
        (script / "main.vns").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        result = load_story(GamePaths(root.resolve()))
        assert result.program is not None, [e.format() for e in result.errors[:3]]
        _program = result.program
    return _program


def installed(program: Program) -> PersistentStore:
    """A store holding every ending, with F19's kinds and views registered on it."""
    store = PersistentStore.with_data(
        unlocks={ENDING_KIND: [e.name for e in program.endings]},
        identity_scheme=program.identity_scheme)
    endings.register(SimpleNamespace(program=program, persistent=store))  # type: ignore[arg-type]
    return store


def change(store: PersistentStore) -> None:
    """A change to the unlock names that leaves every route open: ``unlock route r0`` or
    ``lock route r0``, in turn."""
    if not store.unlock(ROUTE_KIND, "r0"):
        store.relock(ROUTE_KIND, "r0")


def merge_store(n: int) -> tuple[PersistentStore, list[str]]:
    """A store holding ``n`` names of a revocable kind, and a file list of ``n`` names: half
    the store's, half new (so the merge removes n/2 and adds n/2)."""
    store = PersistentStore.with_data(unlocks={"bench": [f"a{i}" for i in range(n)]})
    store.register_kind("bench", revocable=True)
    disk = [f"a{i}" for i in range(0, n, 2)] + [f"b{i}" for i in range(n // 2)]
    return store, disk


def time_merge(n: int) -> float:
    store, disk = merge_store(n)
    start = time.perf_counter()
    store.merge_kind("bench", disk)
    return time.perf_counter() - start


def test_ac33_ci_guards(tmp_path, monkeypatch):
    program = bench_program(tmp_path / "bench")
    assert (len(program.endings), len(program.routes)) == (ENDINGS_MAX, ROUTES_MAX)
    assert all(len(r.until) == UNTIL_MAX for r in program.routes)
    store = installed(program)
    calls = {"is_unlocked": 0, "has": 0}
    is_unlocked, has = store.is_unlocked, EndingIndex.has

    def counted_is_unlocked(kind, name):
        calls["is_unlocked"] += 1
        return is_unlocked(kind, name)

    def counted_has(self, name):
        calls["has"] += 1
        return has(self, name)

    monkeypatch.setattr(store, "is_unlocked", counted_is_unlocked)
    monkeypatch.setattr(EndingIndex, "has", counted_has)

    def reads(view: str) -> tuple[int, int]:
        """(calls of the first read, calls of the second) after a change."""
        change(store)
        calls.update(is_unlocked=0, has=0)
        first = store.get(view)
        counted = calls["is_unlocked" if view == "routes" else "has"]
        calls.update(is_unlocked=0, has=0)
        assert store.get(view) == first
        return counted, calls["is_unlocked"] + calls["has"]

    first, again = reads("routes")
    assert store.get("routes") == [r.name for r in program.routes]   # every route open
    assert first <= ROUTES_MAX * UNTIL_MAX and again == 0, (first, again)
    first, again = reads("endings")
    assert len(store.get("endings")) == ENDINGS_MAX
    assert first <= ENDINGS_MAX and again == 0, (first, again)

    small = statistics.median(time_merge(1_000) for _ in range(5))
    large = statistics.median(time_merge(UNLOCK_NAMES_MAX) for _ in range(5))
    assert large <= 20 * small, (large, small)


def _median_ms(run, setup=lambda: None, *, warm: int = 3, runs: int = 21) -> float:
    times = []
    for i in range(warm + runs):
        state = setup()
        start = time.perf_counter()
        run(state)
        if i >= warm:
            times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


@pytest.mark.perf
def test_ac33_reference_machine(tmp_path):
    program = bench_program(tmp_path / "bench")
    store = installed(program)

    routes_ms = _median_ms(lambda _: store.get("routes"), lambda: change(store))  # a miss
    merge_ms = _median_ms(lambda state: state[0].merge_kind("bench", state[1]),
                          lambda: merge_store(UNLOCK_NAMES_MAX))

    def encoded():
        kind = PersistentStore.with_data(unlocks={"bench": [f"a{i}" for i in
                                                            range(UNLOCK_NAMES_MAX)]})
        kind.register_kind("bench", revocable=True)
        encoder = PieceEncoder()
        encoder.encode(kind)                                 # warm: the kind's piece cached
        return kind, encoder

    clock = time.perf_counter
    slices, encodes = [], []
    for i in range(3 + 21):
        kind, encoder = encoded()
        longest = 0.0
        start = clock()
        kind.relock("bench", "a5000")                        # O(1); counted in slice 1
        while True:
            done = encoder.warm(kind, clock() + ENCODE_SLICE_S, clock)
            longest = max(longest, clock() - start)
            if done:
                break
            start = clock()
        start = clock()
        encoder.encode(kind)
        if i >= 3:
            slices.append(longest * 1000)
            encodes.append((clock() - start) * 1000)
    slice_ms, encode_ms = statistics.median(slices), statistics.median(encodes)
    print(f"\nAC-F19-33: routes read (miss) {routes_ms:.3f} ms (<= 1.5); merge_kind "
          f"10,000 {merge_ms:.3f} ms (<= 4); relock, then the longest warm slice "
          f"{slice_ms:.3f} ms (<= 2.5) and the encode after it {encode_ms:.3f} ms (<= 0.5)")
    assert routes_ms <= 1.5 and merge_ms <= 4.0
    assert slice_ms <= 2.5 and encode_ms <= 0.5
