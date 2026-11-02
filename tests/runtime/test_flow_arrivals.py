"""F20 s3 — arrivals and records (F20 ``06-acceptance.md`` AC-F20-14, 16, 20, 67; the run-loop
row of AC-F20-05 and the store rows of AC-F20-11; ``04`` §7.2, §10, §11; ``07`` I-8, I-13).

Harnesses (06 §0.3): **Driver D** is ``RuntimeStoryDriver`` over a launched interpreter with a
fake clock; ``idle`` pumps before each input stand for clicking (1), skip (0), and auto (5).
**Run H** is ``flow_story.play`` on an interpreter we keep (the recorder lives on it).
**Records R** is ``flow_story.store_r``/``records_r``. The store spy logs each ``unlock`` and
``relock`` of ``"flowchart"`` and ``"flowchart_edge"`` with the line the story is at.

F20 s4 adds AC-F20-14's "headless ``jump stall``" row and AC-F20-20's jump half (``run_headless``
with a ``FlowStates`` holder: the call-stack row jumps to the node).
AC-F20-14's ``StepForward`` row follows ``07`` I-8: a re-arrival reorders (relock, then a
quiet unlock) only when the key isn't already last, so the row puts another key last first."""

import json
import logging

from engine.app.story import RuntimeStoryDriver
from engine.persist.fileformat import ReadJob, encode_bytes
from engine.runtime import interpreter
from engine.runtime.commands import Advance, Choose, StepBack, StepForward, WaitDone
from engine.runtime.flowchart import EDGE_KIND, FLOW_KIND, NO_ANCHORS, START_KEY, FlowStates
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.persistent import PersistentStore
from engine.runtime.state import GameState
from engine.script.menu import Menu
from tests.runtime.flow_story import (RUN_1, at_line, ids, key, launched, load_l, node, play,
                                      record, records_r, store_r, visited_ids)
from tests.script.helpers import template_l

FLOW_KINDS = (FLOW_KIND, EDGE_KIND)
RUN_1_INPUTS = ["advance"] * 3 + ["choose 1", "advance", "choose 1"]   # Run H's run 1


# --- Spies and Driver D ----------------------------------------------------------------------

def spy(interp, log: list) -> None:
    """Log ``(op, kind, name, line)`` for every F20 store change, ``op`` one of ``unlock``,
    ``quiet`` (a quiet unlock), ``relock``; only calls that change something."""
    store = interp.persistent
    real_unlock, real_relock = store.unlock, store.relock

    def line() -> int | None:
        current = interp.current
        return None if current is None else current.line

    def unlock(kind, name, *, quiet=False, migrating=False):
        done = real_unlock(kind, name, quiet=quiet, migrating=migrating)
        if done and kind in FLOW_KINDS:
            log.append(("quiet" if quiet else "unlock", kind, name, line()))
        return done

    def relock(kind, name):
        done = real_relock(kind, name)
        if done and kind in FLOW_KINDS:
            log.append(("relock", kind, name, line()))
        return done

    store.unlock, store.relock = unlock, relock


class Driver:
    """Driver D: inputs posted to ``RuntimeStoryDriver`` after ``idle`` pumps; story waits
    answered with ``WaitDone`` after the same pumps."""

    def __init__(self, program, store=None, *, idle: int = 1) -> None:
        self.interp = launched(program, store)
        self.log: list = []
        spy(self.interp, self.log)
        self.driver = RuntimeStoryDriver(self.interp, clock=lambda: 0.0, fixed_seed=42)
        self.idle = idle
        self.driver.new_game()
        self.settle()

    def settle(self) -> None:
        for _ in range(10_000):
            self.driver.pump(1 << 30)
            interp = self.interp
            if interp.busy or interp.released:
                continue
            if interp.status is Status.WAITING and interp.waiting_for is not None:
                for _ in range(self.idle):
                    self.driver.pump(1 << 30)
                self.driver.post(WaitDone(interp.waiting_for))
                continue
            return
        raise AssertionError("the story never settled")

    def post(self, event) -> None:
        for _ in range(self.idle):
            self.driver.pump(1 << 30)
        self.driver.post(event)
        self.settle()

    @property
    def line(self) -> int | None:
        current = self.interp.current
        return None if current is None else current.line

    def to(self, line: int, picks=()) -> None:
        picks = list(picks)
        while self.interp.status is Status.WAITING and self.line != line:
            current = self.interp.current
            if type(current) is Menu:
                text = picks.pop(0)
                self.post(Choose(current.sid, next(c.key for c in current.choices
                                                   if c.text == text)))
            else:
                self.post(Advance(current.sid))


def names(log: list) -> list[tuple[str, str, str]]:
    return [entry[:3] for entry in log]


# --- AC-F20-14 — what reaches a node -----------------------------------------------------------

def test_ac_f20_14_what_reaches_a_node(tmp_path):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    k = lambda name: key(graph, name)                               # noqa: E731

    # Clicking from the start to line 12: festival at line 8's checkpoint, stall at 12's.
    d = Driver(program)
    d.to(12)
    assert d.log == [
        ("unlock", FLOW_KIND, k("festival"), 8),
        ("unlock", EDGE_KIND, record(graph, "start", "festival"), 8),
        ("unlock", FLOW_KIND, k("stall"), 12),
        ("unlock", EDGE_KIND, record(graph, "festival", "stall"), 12)]
    first = d.interp.flowchart.state("scene:stall")
    assert first is d.interp.checkpoint()

    # Skip and auto: the same names in the same order, to the end of run 1.
    runs = []
    for idle in (1, 0, 5):
        run = Driver(program, idle=idle)
        run.to(None, RUN_1)
        runs.append(names(run.log))
    assert runs[0] == runs[1] == runs[2] and len(runs[0]) == 9     # river: no edge

    # StepBack from line 12 to line 8 records nothing.
    d.log.clear()
    d.post(StepBack(1))
    assert d.line == 8 and d.log == []
    # StepForward re-runs to line 12: stall again, already last, so nothing moves (07 I-8);
    # its state equals the first arrival's.
    d.post(StepForward(1))
    assert d.line == 12 and d.log == []
    again = d.interp.flowchart.state("scene:stall")
    assert again is d.interp.checkpoint() and again is not first and again == first
    # With another key last, the re-run moves stall last: relock, then a quiet unlock.
    d.post(StepBack(1))
    d.interp.persistent.unlock(FLOW_KIND, k("sad"))
    d.log.clear()
    d.post(StepForward(1))
    assert d.log == [("relock", FLOW_KIND, k("stall"), 12), ("quiet", FLOW_KIND, k("stall"), 12)]
    assert d.interp.persistent.last_unlocked(FLOW_KIND) == k("stall")
    assert d.interp.persistent.take_new_unlocks()[-1] == (FLOW_KIND, k("sad"))

    # Loading a save made at line 19, and a non-landing restore of k_12, record nothing.
    k12 = d.interp.checkpoint()
    d.to(19, ["Buy the red one"])
    k19 = GameState.from_json(json.loads(json.dumps(d.interp.checkpoint().to_json())))
    d.log.clear()
    assert d.driver.restore(k19).result is RestoreResult.OK
    d.settle()
    assert d.driver.restore(k12).result is RestoreResult.OK
    d.settle()
    assert d.log == [] and d.line == 12
    # A headless ``jump stall`` (Run H, run 1's holder) records nothing either.
    store, holder = PersistentStore(identity_scheme=program.identity_scheme), FlowStates()
    run_headless(program, seed=42, persistent=store, flow=holder, inputs=RUN_1_INPUTS)
    version, reached = store.version, list(holder.reached)
    commands = run_headless(program, seed=42, persistent=store, flow=holder,
                            inputs=["jump scene:stall"])
    assert type(commands[-1]).__name__ == "ShowMenu"    # M13, after line 12
    assert store.version == version and holder.reached == reached

    # "By the river": river at line 30's checkpoint; M21 → river is a choice mark only.
    d.to(30, ["Buy the red one", "By the river"])
    assert ("unlock", FLOW_KIND, k("river"), 30) in d.log
    assert not any(name.endswith(k("river")) for op, kind, name, _ in d.log
                   if kind == EDGE_KIND)
    menu = program.get(graph.nodes[node(graph, "M21")].anchor)
    river = next(c.key for c in menu.choices if c.text == "By the river")
    assert d.interp.persistent.was_chosen(menu.sid, river)
    # ``ending sad`` runs: F19 records it, F20 the edge river → sad and sad's key moved last.
    d.log.clear()
    d.post(Advance(d.interp.current.sid))
    assert d.interp.status is Status.ENDED
    assert d.interp.persistent.is_unlocked("ending", "sad")
    assert ("unlock", EDGE_KIND, record(graph, "river", "sad"), 31) in d.log
    assert d.interp.persistent.last_unlocked(FLOW_KIND) == k("sad")
    assert d.interp.flowchart.state("ending:sad") is None

    # An arrival whose snapshot fails (E85e) records nothing.
    bad = load_l(tmp_path / "bad", template_l(
        S='$ bad = lambda: 0⏎[4]"Daichi waves from the stall."'))
    interp = launched(bad)
    log: list = []
    spy(interp, log)
    play(interp)
    assert interp.status is Status.FAILED
    assert [n for _, kind, n, _ in log if kind == FLOW_KIND] == [key(bad.flowgraph, "festival")]
    assert interp.flowchart.state("scene:stall") is None

    # 17 scene labels that only jump onward, then one line: 16 recorded, the 17th dropped.
    lines = ["label start:", "    jump s1"]
    for i in range(1, 18):
        lines += [f"label s{i}:", f'    flowchart scene "S{i}"', f"    jump s{i + 1}"]
    lines += ["label s18:", '    "Done."']
    hops = load_l(tmp_path / "hops", "\n".join(lines) + "\n")
    interp = launched(hops)
    play(interp, until=at_line(len(lines)))
    assert interp.status is Status.WAITING and interp.flow_pending == []
    assert ids(hops.flowgraph, interp.flow.path) == [f"scene:s{i}" for i in range(1, 17)]
    assert not interp.persistent.is_unlocked(FLOW_KIND, key(hops.flowgraph, "s17"))


# --- AC-F20-16 — visited records last --------------------------------------------------------------

def test_ac_f20_16_visited_records_last(tmp_path):
    program = load_l(tmp_path / "l")
    store = PersistentStore(identity_scheme=program.identity_scheme)
    interp = launched(program, store)
    play(interp, RUN_1, until=at_line(19))
    k19 = interp.checkpoint()
    play(interp, RUN_1[1:], new=False)

    def stall_visited(s=store) -> bool:
        return "scene:stall" in visited_ids(program, s)

    assert stall_visited()
    play(interp, (), until=at_line(8))                   # New Game, before line 12
    assert stall_visited()
    del interp                                           # back to the title: a new run
    again = launched(program, store)
    play(again, (), until=at_line(8))
    early = again.checkpoint()
    play(again, ["Buy the red one"], new=False, until=at_line(19))
    assert again.restore(early).result is RestoreResult.OK     # a load from before line 12
    assert stall_visited()
    play(again, ["Buy the red one"], new=False, until=at_line(19))
    again.post(StepBack(4))                              # back past line 12
    again.run(10_000)
    assert again.current.line < 12 and stall_visited()
    store.clear()                                        # persistent._clear()
    store.clear(progress=True)                           # persistent._clear(progress=True)
    assert stall_visited()
    # A relaunch with a new store read from persistent.json (Harness Y's read).
    data = encode_bytes(store, program)
    fresh = PersistentStore(identity_scheme=program.identity_scheme)
    job = ReadJob(data, fresh, program)
    while not job.step():
        pass
    launched(program, fresh)                             # registers the kinds
    assert stall_visited(fresh)
    # F12's reset() (F16's Delete progress) removes it; flowchart forget stall: AC-F20-21.
    assert again.restore(k19).result is RestoreResult.OK and stall_visited()
    store.reset()
    assert not stall_visited()


# --- AC-F20-20 — what a node keeps ---------------------------------------------------------------

HUB = '''label start:
    "Hi."
    jump hub
label hub:
    flowchart scene "Hub"
    "At the hub."
    menu:
        "Again":
            "Round we go."
            jump hub
        "Leave":
            ending gone "Gone"
'''

PAIR = '''label start:
    "Hi."
    jump h
label h:
    flowchart scene "H"
    flowchart "Q"
    menu:
        "One":
            "1."
        "Two":
            "2."
'''

CALLED = '''label start:
    "Hi."
    call side
    "Back in start."
label side:
    flowchart scene "Side"
    "In the side label."
    return
'''


def test_ac_f20_20_what_a_node_keeps(tmp_path):
    program = load_l(tmp_path / "l")
    interp = launched(program)
    play(interp, RUN_1, until=at_line(12))
    k12 = interp.checkpoint()
    held = interp.flowchart.state("scene:stall")
    assert held is k12                                   # the checkpoint's object
    assert ids(program.flowgraph, held.flow.path)[-1] == "scene:stall"
    assert held.stage == interp.stage and held.audio == interp.audio
    assert held.history == interp.history and held.nvl == interp.nvl       # (F13), (F17)
    assert held.items == interp.codex.state() and held.points == interp.points.state()
    play(interp, RUN_1, new=False)                       # (F21), (F22): held as checkpointed
    assert interp.flowchart.state("scene:stall") is held
    assert interp.flowchart.state("start") is None
    assert interp.flowchart.state("ending:sad") is None
    assert interp.flowchart.state("menu:" + program.flowgraph.nodes[3].name).choices \
        .waiting is not None

    # A hub loop: the second arrival replaces the state.
    hub = load_l(tmp_path / "hub", HUB)
    interp = launched(hub)
    play(interp, ["Again"], until=at_line(6))
    first = interp.flowchart.state("scene:hub")
    play(interp, ["Again"], new=False, until=lambda i: i.checkpoint() is not first
         and i.current.line == 6)
    second = interp.flowchart.state("scene:hub")
    assert second is interp.checkpoint() and second is not first
    assert list(interp.flowchart.states)[-1] == "scene:hub"     # replaced, moved last

    # A scene whose first statement is a node menu: both hold the same snapshot object.
    pair = load_l(tmp_path / "pair", PAIR)
    interp = launched(pair)
    play(interp, until=at_line(7))
    states = interp.flowchart.states
    menu = next(n for n in pair.flowgraph.nodes if n.kind == "choice")
    assert set(states) == {"scene:h", menu.id}
    assert len({id(s) for s in states.values()}) == 1

    # A scene reached by ``call``: the state holds the call stack; after a jump to it the
    # story returns to that caller.
    called = load_l(tmp_path / "called", CALLED)
    holder = FlowStates()
    run_headless(called, seed=42, flow=holder)
    state = holder["scene:side"]
    assert len(state.call_stack) == 1
    commands = run_headless(called, seed=42, flow=holder,
                            inputs=["jump scene:side", "advance"])
    said = [c for c in commands if type(c).__name__ == "Say"]
    assert said[-2].restored and said[-1].body.plain()[0].text == "Back in start."


# --- AC-F20-67 — runtime cost ------------------------------------------------------------------------

class CountingAnchors(dict):
    gets = 0

    def get(self, sid, default=None):
        CountingAnchors.gets += 1
        return super().get(sid, default)


def test_ac_f20_67_runtime_cost(tmp_path, monkeypatch):
    program = load_l(tmp_path / "hub", HUB)
    interp = launched(program)
    runs = [0]
    for node_type, run in list(interpreter.EXECUTORS.items()):
        def counted(i, stmt, run=run):
            runs[0] += 1
            return run(i, stmt)
        monkeypatch.setitem(interpreter.EXECUTORS, node_type, counted)
    interp.flow_anchors = CountingAnchors(program.flowgraph.anchors)
    CountingAnchors.gets = 0
    interp.new_game(42)
    interp.run(10_000)
    while runs[0] < 10_000:
        play(interp, ["Again"] * 100, new=False)
    assert interp.status is Status.WAITING
    assert CountingAnchors.gets == runs[0]               # one lookup per executed statement
    # Without a graph the lookup is on an empty mapping.
    plain = launched(load_l(tmp_path / "off", HUB, enabled=False))
    assert plain.flow_anchors is NO_ANCHORS and len(NO_ANCHORS) == 0
    assert not any(kind in FLOW_KINDS for kind, _ in plain.persistent.kind_items())

    # An arrival makes at most 6 store operations; a node's state is the snapshot itself.
    lanterns = load_l(tmp_path / "l")
    interp = launched(lanterns)
    store = interp.persistent
    ops = [0]
    real_unlock, real_relock = store.unlock, store.relock

    def unlock(*args, **kwargs):
        ops[0] += 1
        return real_unlock(*args, **kwargs)

    def relock(*args, **kwargs):
        ops[0] += 1
        return real_relock(*args, **kwargs)

    store.unlock, store.relock = unlock, relock
    per_arrival: list[int] = []
    real_record, real_ending = interp.flowchart.record, interp.flowchart._reach_ending

    def record_spy(arrived, state):
        before = ops[0]
        real_record(arrived, state)
        per_arrival.append((ops[0] - before) / max(1, len(arrived[0])))
        assert all(interp.flowchart.states.get(lanterns.flowgraph.nodes[n].id) is state
                   for n in arrived[0] if lanterns.flowgraph.nodes[n].kind != "ending")

    def ending_spy(prev, n):
        before = ops[0]
        real_ending(prev, n)
        per_arrival.append(ops[0] - before)

    interp.flowchart.record, interp.flowchart._reach_ending = record_spy, ending_spy
    for _ in range(2):                                   # first arrivals, then re-arrivals
        play(interp, RUN_1)
        store.unlock(FLOW_KIND, key(lanterns.flowgraph, "shrine"))   # nothing is last
    assert len(per_arrival) == 10 and max(per_arrival) <= 6


# --- AC-F20-05 (run-loop row) and AC-F20-11 (store rows) ------------------------------------------

def test_ac_f20_05_run_loop_records_nothing_when_off(tmp_path):
    program = load_l(tmp_path / "off", enabled=False)
    assert program.flowgraph is None
    interp = launched(program)
    paths = []
    play(interp, RUN_1, until=lambda i: paths.append(i.flow.path) and False)
    assert interp.status is Status.ENDED and set(paths) == {()}
    assert interp.flow_pending == [] and interp.flowchart.graph is None
    assert not any(kind in FLOW_KINDS for kind, _ in interp.persistent.kind_items())
    interp.flowchart.forget(None)                        # 07 I-13: forget does nothing
    assert interp.flowchart.take_forgotten() == ()


def test_ac_f20_11_records_across_patches(tmp_path, caplog):
    base = load_l(tmp_path / "base")
    store = PersistentStore(identity_scheme=base.identity_scheme)
    play(launched(base, store), RUN_1)
    run1 = {"chapter:festival", "scene:stall", "chapter:river", "ending:sad", "start"}
    m21 = f"menu:{base.flowgraph.nodes[3].name}"
    assert visited_ids(base, store) == run1 | {m21}

    def reload(name: str, **patch):
        program = load_l(tmp_path / name, template_l(**patch), dev=True)
        store_r(program, store=store)                    # the launch registers the kinds
        return program

    for name, patch in (("retitle", {20: '    flowchart "Elsewhere?" hidden no jump'}),
                        ("remove", {20: "    # no mark"}),
                        ("flag", {20: '    flowchart "Where should we watch the lanterns?"'
                                      " hidden"})):
        program = reload(name, replace=patch)
        assert m21 in visited_ids(program, store), name
    question = reload("question", replace={21: '    menu:⏎[8]hana "Where now?"'})
    graph = question.flowgraph
    new_m21 = next(i for i, n in enumerate(graph.nodes) if n.kind == "choice")
    assert graph.nodes[new_m21].id != m21
    recs = records_r(question, store)
    assert recs.titles[new_m21] is None and not recs.visited[new_m21]
    old_key = base.flowgraph.nodes[3].key
    assert store.is_unlocked(FLOW_KIND, old_key) and old_key not in graph.by_key
    # Renaming label stall: scene:booth is unvisited (the menu's sid names its label, so its
    # id is new too); the others are unchanged.
    renamed = reload("renamed", replace={9: "    jump booth", 10: "label booth:"})
    assert "scene:booth" in renamed.flowgraph.by_id
    assert visited_ids(renamed, store) == run1 - {"scene:stall"}
    caplog.clear()
    gone = reload("gone", replace={23: "            jump sad_end", 28: "label sad_end:",
                                   29: "    # gone", 30: "    # gone"})
    assert "chapter:river" not in gone.flowgraph.by_id
    assert store.is_unlocked(FLOW_KIND, key(base.flowgraph, "river"))   # kept, ignored
    path = tuple(key(base.flowgraph, n) for n in ("festival", "stall", "M21", "river"))
    recs = records_r(gone, store, path=path)
    assert visited_ids(gone, store) == run1 - {"chapter:river"} | {m21}
    assert gone.flowgraph.nodes[recs.here].id == m21     # river's key: drawn nowhere
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    inserted = reload("inserted", S='"Daichi waves from the stall."⏎[4]"A new line."')
    assert "scene:stall" in visited_ids(inserted, store)
    assert key(inserted.flowgraph, "stall") == key(base.flowgraph, "stall")
    assert START_KEY == key(base.flowgraph, "start")
