"""F20 s3 — the persistent kinds (F20 ``06-acceptance.md`` AC-F20-48, group H, and AC-F20-55;
``04`` §4 "Kind names", §7.1 step 10, §7.2; ``05`` SEC-F20-11; ``07`` A9, I-8).

Harness Y (F12's ``sync_support``): copies of one game on a real ``persistent`` folder with a
synchronous writer; "each writes after its own change" is ``flush_now()``. The two-copy
interleavings with reorder and forget operations are AC-F19-28's
(``tests/persist/test_merge_relock.py``, which gained them, TR-F19-01)."""

import random
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.persist import fileformat
from engine.persist.location import FILE_NAME
from engine.runtime import limits as runtime_limits
from engine.runtime import persistent as persistent_mod
from engine.runtime.flowchart import EDGE_KIND, FLOW_KIND, TOMBSTONE, FlowRecorder
from engine.runtime.persistent import PersistentStore
from engine.script import limits as script_limits
from engine.script import load_story
from engine.script.flowgraph import FlowOptions
from engine.script.loader import LoadOptions
from engine.script.messages import format_message
from tests.persist.sync_support import Harness
from tests.persist.writer_support import base, game  # noqa: F401
from tests.runtime.flow_story import (RUN_1, key, launched, load_l, node, play, records_r,
                                      store_r, visited_ids)

BUILT_KINDS = {"chapter", "ending", "route", "tip", "codex_read", FLOW_KIND, EDGE_KIND,
               "gallery", "replay", "achievement"}          # F34 W2, F36 W2, F37 S2


def gate_script(width: int, *, scenes: bool = False) -> str:
    """A route gate with ``width`` predecessors and ``width`` successors (chapters, or
    scenes), chosen by ``v`` (5): start → p5 → gate → s5."""
    lines = ['lock route r "R" until e1', "default v = 5", "label start:", '    "Hi."']
    for word, target in (("start", "p"), ("r", "s")):
        if word == "r":
            lines += ["label r:", '    "In the route."']
        for i in range(1, width + 1):
            lines += [f"    {'if' if i == 1 else 'elif'} v == {i}:", f"        jump {target}{i}"]
    for i in range(1, width + 1):
        mark = "flowchart scene" if scenes else "chapter"
        lines += [f"label p{i}:", f'    {mark} {"" if scenes else f"p{i} "}"P{i}"',
                  "    jump r", f"label s{i}:", f'    {mark} {"" if scenes else f"s{i} "}"S{i}"',
                  f'    "End {i}."']
    lines += ["label fin:", '    ending e1 "E1"']
    return "\n".join(lines) + "\n"


def chain_script(count: int) -> str:
    lines = ["label start:"] + [f'    chapter c{i} "C{i}"' for i in range(1, count + 1)]
    return "\n".join(lines + ['    "End."']) + "\n"


def try_load(root: Path, text: str):
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_bytes(text.encode("utf-8"))
    return load_story(GamePaths(root.resolve()), LoadOptions(flowchart=FlowOptions()))


def known_of(store: PersistentStore, kind: str):
    return dict(store.kind_items())[kind].known


# --- AC-F20-48 — group H: the persistent kinds stay usable --------------------------------------------

def test_ac_f20_48_kinds_stay_usable(tmp_path, monkeypatch, game):    # noqa: F811
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    festival = key(graph, "festival")

    # 10,000 junk names in each kind: arrivals still record (junk gives way).
    store = PersistentStore(identity_scheme=program.identity_scheme)
    for kind in (FLOW_KIND, EDGE_KIND):
        store.load_kind(kind, [f"junk{i}" for i in range(runtime_limits.UNLOCK_NAMES_MAX)])
    play(launched(program, store), RUN_1)
    assert store.is_unlocked(FLOW_KIND, festival)
    assert store.is_unlocked(EDGE_KIND, key(graph, "start") + festival)
    assert len(store.unlocked(FLOW_KIND)) == runtime_limits.UNLOCK_NAMES_MAX

    # 32 junk kinds in the file: F20's two kinds register; arrivals record.
    store = PersistentStore(identity_scheme=program.identity_scheme)
    for i in range(runtime_limits.UNLOCK_KINDS_MAX):
        assert store.load_kind(f"junk{i}", ["a"]) == 0
    play(launched(program, store), RUN_1)
    assert store.is_unlocked(FLOW_KIND, festival)
    registered = {kind for kind, entry in store.kind_items() if entry.registered}
    assert registered == BUILT_KINDS

    # Tombstones for every chapter: unvisited until reached again.
    chapters = ("festival", "river", "shrine")
    store = store_r(program, ch=chapters, tomb=chapters)
    assert not visited_ids(program, store) & {f"chapter:{c}" for c in chapters}
    play(launched(program, store), RUN_1)
    assert visited_ids(program, store) & {f"chapter:{c}" for c in chapters} == {
        "chapter:festival", "chapter:river"}

    # A hostile unlock order (shuffled, duplicates, junk, tombstones): recent is the last
    # current key; no error.
    names = [key(graph, n) for n in ("festival", "stall", "M21", "river")]
    for seed in range(5):
        rng = random.Random(seed)
        pairs = [(FLOW_KIND, name) for name in names * 2 + ["junk", TOMBSTONE + festival,
                                                           "0" * 16]]
        rng.shuffle(pairs)
        store = store_r(program, store=PersistentStore.with_data(unlocks=pairs))
        last = [n for n in dict.fromkeys(name for _, name in pairs) if n in names][-1]
        assert records_r(program, store).recent == graph.by_key[last]

    # A gate with 120 predecessors and 120 successors: 240 records (P + S); it loads, and an
    # arrival through it records its pair.
    gated = load_l(tmp_path / "gate", gate_script(120))
    g = gated.flowgraph
    gate = next(i for i, n in enumerate(g.nodes) if n.kind == "gate")
    through = [e for e in g.edges if gate in (e.src, e.dst)]
    assert len(through) == 240 and all(e.record in g.records for e in through)
    store = PersistentStore(identity_scheme=gated.identity_scheme)
    play(launched(gated, store))
    gate_key = g.nodes[gate].key
    assert store.is_unlocked(EDGE_KIND, key(g, "p5") + gate_key)
    assert store.is_unlocked(EDGE_KIND, gate_key + key(g, "s5"))
    assert sum(1 for name in store.unlocked(EDGE_KIND) if gate_key in name) == 2

    # The name cap mirrors F12's per-kind cap; patched to 50 (both), too many records or
    # node keys plus tombstones are E265's name form.
    assert script_limits.FLOW_NAMES_MAX == runtime_limits.UNLOCK_NAMES_MAX
    with monkeypatch.context() as patch:
        patch.setattr(script_limits, "FLOW_NAMES_MAX", 50)
        patch.setattr(runtime_limits, "UNLOCK_NAMES_MAX", 50)
        patch.setattr(persistent_mod, "UNLOCK_NAMES_MAX", 50)
        for name, text, count in (("records", gate_script(30, scenes=True), 90),
                                  ("keys", chain_script(26), 26 + 26)):
            result = try_load(tmp_path / f"cap-{name}", text)
            assert [e.code for e in result.errors] == ["E265"], name
            assert result.errors[0].message == format_message("E265", ("names", count, 50))
        assert try_load(tmp_path / "cap-fits", chain_script(25)).errors == ()   # 50

    # ``known``: only current node keys, ``x`` + a current chapter key, and current records.
    store = launched(program).persistent
    known, known_edge = known_of(store, FLOW_KIND), known_of(store, EDGE_KIND)
    assert known(festival) and known(TOMBSTONE + festival) and known(key(graph, "sad"))
    for name in (TOMBSTONE + key(graph, "stall"), "0" * 16, TOMBSTONE + "0" * 16, "x", 3,
                 festival.upper(), festival + "0"):
        assert not known(name), name
    assert known_edge(key(graph, "start") + festival)
    assert not known_edge(festival + key(graph, "start")) and not known_edge(festival)
    stranger = PersistentStore.with_data(unlocks={FLOW_KIND: ["0" * 16, TOMBSTONE + "1" * 16]})
    assert visited_ids(program, store_r(program, store=stranger)) == {"start"}

    # The reorder racing a merge: relock and the quiet unlock in one step, nothing between;
    # a merge of another copy's write after it loses no name.
    folder = game / "persistent"
    launch_file(folder, program, ("stall", "river"))
    a, b = copy(folder, game, program), copy(folder, game, program)
    events: list = []
    real = {name: getattr(a.store, name) for name in ("unlock", "relock", "merge_kind")}
    for name, fn in real.items():
        def spy(*args, _fn=fn, _name=name, **kwargs):
            events.append((_name, args[:2], kwargs.get("quiet", False)))
            return _fn(*args, **kwargs)
        setattr(a.store, name, spy)
    b.store.relock(FLOW_KIND, key(graph, "river"))
    write(b)
    arrive(a, graph, "stall")
    stall = key(graph, "stall")
    i = events.index(("relock", (FLOW_KIND, stall), False))
    assert events[i + 1] == ("unlock", (FLOW_KIND, stall), True)
    write(a)
    assert any(e[0] == "merge_kind" for e in events[i + 2:])
    converge(a, b)
    for h in (a, b):
        assert h.store.unlocked(FLOW_KIND) == (stall,)
    assert fileformat.parse(fileformat.decode(a.path.read_bytes()))["unlocks"][FLOW_KIND] == [
        stall]

    # Copy A forgets stall, copy B reaches it: the last copy to write its change wins.
    for order, held in (("AB", True), ("BA", False)):
        sub = game / f"order-{order}"
        launch_file(sub / "persistent", program, ("stall", "river"))
        a = copy(sub / "persistent", sub, program)
        b = copy(sub / "persistent", sub, program)
        for who in order:
            if who == "A":
                FlowRecorder(graph, a.store).forget("stall")
                write(a)
            else:
                arrive(b, graph, "stall")
                write(b)
        converge(a, b)
        for h in (a, b):
            assert h.store.is_unlocked(FLOW_KIND, stall) is held, order


def launch_file(folder: Path, program, visited) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    store = store_r(program, v=visited)
    (folder / FILE_NAME).write_bytes(fileformat.encode_bytes(store))


def copy(folder: Path, game_root: Path, program) -> Harness:
    h = Harness(folder, game=game_root)
    store_r(program, store=h.store)                      # the kinds, as a launch registers
    return h


def arrive(h: Harness, graph, name: str) -> None:
    """Step 4d's store half for one arrival at ``name`` (a re-arrival reorders)."""
    FlowRecorder(graph, h.store).record(((node(graph, name),), ()), object())


def write(h: Harness) -> None:
    assert h.sync.flush_now(), h.sync.mode


def converge(*hs: Harness) -> None:
    for h in hs + hs[:1]:
        h.store.version += 1
        write(h)


# --- AC-F20-55 — unlock kinds stay ≤ 32 -----------------------------------------------------------

def test_ac_f20_55_unlock_kinds_stay_within_32(tmp_path):
    program = load_l(tmp_path / "l")
    store = launched(program).persistent                 # every built feature registers
    registered = {kind for kind, entry in store.kind_items() if entry.registered}
    assert registered == BUILT_KINDS
    assert len(registered) <= runtime_limits.UNLOCK_KINDS_MAX == 32
    assert all(store.is_revocable(kind) for kind in (FLOW_KIND, EDGE_KIND))


@pytest.fixture(autouse=True)
def _no_fsync(monkeypatch):
    """Speed only (as F19's merge tests)."""
    from engine.core import safefile
    monkeypatch.setattr(safefile, "_fsync_file", lambda fd: None)
    monkeypatch.setattr(safefile, "_fsync_folder", lambda folder: None)
