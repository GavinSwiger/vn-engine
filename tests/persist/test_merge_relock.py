"""How two copies merge F19's revocable unlock kinds (F19 ``06-acceptance.md`` AC-F19-27,
AC-F19-28; checklist step 2; ``04`` §7.5; ``07`` I-3; TR-F19-01).

Harness Y (``sync_support``) as in F12's ``test_sync_merge.py``: one real folder, fake
clocks, a synchronous writer. "Each writes after its own change" is ``flush_now()``.
``"ending"`` and ``"route"`` are registered revocable, ``"cg"`` plain.

F20 s3 (its AC-F20-48 row, ``07`` A9, I-8): the interleavings gain F20's two operations on a
revocable kind: a **reorder** (a re-arrival: ``relock``, then a quiet ``unlock`` of the same
name) and a **forget** (``relock`` of a name and a quiet ``unlock`` of its tombstone
``x<name>``)."""

import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

from engine.core import safefile
from engine.persist import fileformat
from engine.persist.location import FILE_NAME
from engine.persist.sync import PersistentSync
from engine.persist.writer import WriterClient, Written
from engine.runtime.persistent import PersistentStore
from tests.persist.sync_support import Harness, disk_unlocks, plant, sid, store_unlocks
from tests.persist.writer_support import base, game, temps  # noqa: F401

MAIN = Path(__file__).resolve()
REVOCABLE = ("ending", "route")


@pytest.fixture
def folder(game) -> Path:
    return game / "persistent"


def copy(folder: Path, game: Path, **kwargs) -> Harness:
    h = Harness(folder, game=game, **kwargs)
    for kind in REVOCABLE:
        h.store.register_kind(kind, revocable=True)
    h.store.register_kind("cg")
    return h


def launch_file(folder: Path, endings: list[str]) -> None:
    """The file both copies read at launch: e=(endings)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE_NAME).write_bytes(fileformat.encode_bytes(
        PersistentStore.with_data(unlocks={"ending": endings})))


def write(h: Harness) -> None:
    assert h.sync.flush_now(), h.sync.mode


def converge(*hs: Harness) -> None:
    for h in hs + hs[:1]:
        h.store.version += 1               # a change that changes nothing
        write(h)


def everywhere(a: Harness, b: Harness) -> list[set[tuple[str, str]]]:
    """The unlocks in the file and in both stores."""
    return [disk_unlocks(a.disk()), store_unlocks(a.store), store_unlocks(b.store)]


# --- AC-F19-27 — merge rules for revocable kinds ---------------------------------------------

def _row_relock_wins(a, b):
    a.store.relock("ending", "sad")
    write(a)
    b.store.set("n", 1)
    write(b)
    return set()


def _row_last_change_wins(a, b):
    a.store.relock("ending", "sad")
    write(a)
    b.store.relock("ending", "sad")
    b.store.unlock("ending", "sad")
    write(b)
    return {("ending", "sad")}


def _row_both_kept(a, b):
    a.store.unlock("ending", "good")
    write(a)
    b.store.unlock("ending", "true")
    write(b)
    return {("ending", "good"), ("ending", "true")}


def _row_one_write(a, b):
    a.store.relock("ending", "sad")
    a.store.unlock("ending", "good")
    write(a)
    return {("ending", "good")}


def _row_plain_union(a, b):
    a.store.unlock("cg", "a")
    write(a)
    b.store.unlock("cg", "b")
    write(b)
    return {("cg", "a"), ("cg", "b")}


def _row_reset(a, b):
    b.store.unlock("ending", "good")
    write(b)
    a.store.reset()
    write(a)
    return set()


ROWS = {"relock": (["sad"], _row_relock_wins), "relock-unlock": (["sad"], _row_last_change_wins),
        "both": ([], _row_both_kept), "one-write": (["sad"], _row_one_write),
        "cg": ([], _row_plain_union), "reset": ([], _row_reset), "forced": (["sad"], None)}


def _forced_row(folder, game, monkeypatch) -> None:
    """07 I-3: three merges in a row, a fourth with values off, then the unchecked write. The
    files planted by another copy hold ``sad``; A's relock (its own last change) stays."""
    a = copy(folder, game)
    a.store.relock("ending", "sad")
    requests = []
    plants = [fileformat.encode_bytes(PersistentStore.with_data(
        unlocks={"ending": ["sad"]}, seen=[sid("o", n)])) for n in range(4)]
    real = PersistentSync._submit

    def submit(sync, now):
        if plants:
            plant(a.path, plants.pop(0))
        real(sync, now)
        requests.append(sync.last_request)

    monkeypatch.setattr(PersistentSync, "_submit", submit)
    write(a)
    assert [r.check for r in requests] == [True, True, True, True, False]
    assert disk_unlocks(a.disk()) == set() and store_unlocks(a.store) == set()


@pytest.mark.parametrize("row", ROWS)
def test_ac27_merge_rules_for_revocable_kinds(folder, game, monkeypatch, row):
    endings, play = ROWS[row]
    launch_file(folder, endings)
    if play is None:
        _forced_row(folder, game, monkeypatch)
        return
    a, b = copy(folder, game), copy(folder, game)
    expected = play(a, b)
    converge(b, a)
    for unlocks in everywhere(a, b):
        assert unlocks == expected, row


# --- AC-F19-28 — random interleavings with relock (TR-F19-01) -------------------------------

class Oracle:
    """Per revocable ``(kind, name)``, the state set by the last copy whose write carried a
    change to it; ``"cg"`` is the union. Built only from the operations performed."""

    def __init__(self) -> None:
        self.state: dict[tuple[str, str], bool] = {}
        self.pending: dict[str, dict[tuple[str, str], bool]] = {"A": {}, "B": {}}
        self.cg: set[tuple[str, str]] = set()

    def written(self, me: str) -> None:
        self.state.update(self.pending[me])
        self.pending[me] = {}

    def expected(self) -> set[tuple[str, str]]:
        return {key for key, held in self.state.items() if held} | self.cg


def _watch_writes(monkeypatch, hs: dict, oracle: Oracle) -> None:
    real = WriterClient.submit

    def submit(client, job):
        me = next(me for me, h in hs.items() if h.sync._client is client)
        real(client, job)
        if isinstance(client._results[-1], Written):
            oracle.written(me)

    monkeypatch.setattr(WriterClient, "submit", submit)


def _random_op(rng: random.Random, h: Harness, me: str, oracle: Oracle, serial: list) -> None:
    store = h.store
    roll = rng.random()
    if roll < 0.55:
        key = (rng.choice(REVOCABLE), f"n{rng.randrange(6)}")
        if roll < 0.3:
            if store.unlock(*key):
                oracle.pending[me][key] = True
        elif roll < 0.45:
            if store.relock(*key):
                oracle.pending[me][key] = False
        elif roll < 0.5:                                  # F20's reorder (07 I-8)
            if store.is_unlocked(*key) and store.last_unlocked(key[0]) != key[1]:
                assert store.relock(*key) and store.unlock(*key, quiet=True)
                oracle.pending[me][key] = True
        else:                                             # F20's forget
            if store.relock(*key):
                oracle.pending[me][key] = False
            tomb = (key[0], "x" + key[1])
            if store.unlock(*tomb, quiet=True):
                oracle.pending[me][tomb] = True
    elif roll < 0.62:
        key = ("cg", f"c{rng.randrange(6)}")
        store.unlock(*key)
        oracle.cg.add(key)
    elif roll < 0.75:
        serial[0] += 1
        store.set(rng.choice(("a", "b")), serial[0])
    else:
        h.tick(h.now + rng.choice((0.05, 0.3, 0.7, 1.2, 2.0)))


def run_interleaving(folder: Path, game: Path, seed: str, ops: int, monkeypatch) -> None:
    rng = random.Random(seed)
    oracle = Oracle()
    hs = {me: copy(folder, game) for me in "AB"}
    serial = [0]
    with monkeypatch.context() as patch:
        _watch_writes(patch, hs, oracle)
        patch.setattr(safefile, "_fsync_file", lambda fd: None)      # speed only
        patch.setattr(safefile, "_fsync_folder", lambda folder: None)
        for _ in range(ops):
            me = rng.choice("AB")
            _random_op(rng, hs[me], me, oracle, serial)
        for me in "ABAB":                    # the end: each copy writes after the other's
            hs[me].store.version += 1
            write(hs[me])
    for unlocks in everywhere(hs["A"], hs["B"]):
        assert unlocks == oracle.expected(), seed
    assert temps(folder) == []


@pytest.mark.parametrize("chunk", [*range(10), *(pytest.param(c, marks=pytest.mark.slow)
                                                 for c in ("slow", "pair"))])
def test_ac28_random_interleavings_with_relock(folder, game, monkeypatch, tmp_path, chunk):
    """Default: 100 interleavings × 50 operations in 10 chunks. ``slow``: 1,000 × 1,000, and
    one real pair of ``python -I copy_worker.py … relock`` processes."""
    if chunk == "pair":
        _real_pair(folder, tmp_path)
        return
    runs, ops = (1_000, 1_000) if chunk == "slow" else (10, 50)
    for i in range(runs):
        sub = folder.parent / f"run{i}" / "persistent"
        run_interleaving(sub, game, f"ac-f19-28:{chunk}:{i}", ops, monkeypatch)


def _real_pair(folder: Path, tmp_path: Path) -> None:
    """Copy i touches only ``e<i>_*`` in ``"ending"``; the file holds each copy's last state
    of its own names."""
    worker = MAIN.parent / "copy_worker.py"
    folder.mkdir(parents=True)
    outs = [tmp_path / f"out{i}.json" for i in range(2)]
    procs = [subprocess.Popen([sys.executable, "-I", str(worker), str(folder), str(i),
                               "1000", str(outs[i]), "relock"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for i in range(2)]
    for proc in procs:
        _, err = proc.communicate(timeout=240)
        assert proc.returncode == 0, err.decode(errors="replace")
    made = [json.loads(o.read_text()) for o in outs]
    obj = fileformat.parse(fileformat.decode((folder / FILE_NAME).read_bytes()))
    assert set(obj["unlocks"].get("ending", [])) == set(made[0]["endings"] + made[1]["endings"])
    assert temps(folder) == []
