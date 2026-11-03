"""F40 W0 — the console's state methods (``Interpreter.author_call``, ``console_change``,
``console_jump``, the ``_hold_scene`` split; ``PersistentStore.revert_in_place``): AC-F40-17
and AC-F40-18 at the interpreter, the failure-restore cases (an in-place list change, a
persistent value that can't be kept, the watchdog), and I-1's "no golden diff"."""

from pathlib import Path

import pytest

from engine.persist import saves
from engine.runtime.commands import (Advance, AudioRestore, NvlPage, Say, ShowStage, StepBack,
                                     StepForward, StoryFailed)
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.runtime.values import same_value
from tests.persist import save_support as ss
from tests.runtime.conftest import round_trip
from tests.runtime.flow_story import load_l
from tests.runtime.story import load_files

STORY = '''define hana = Character("Hana")
points trust 0 to 10
default persistent.visited = []
default persistent.notes = {}
default mood = "calm"
default bag = []
default bloomed = False
lock item lantern "Lantern" in "Things"
lock replay garden "The Garden"
lock achievement bloom "Bloom" when bloomed
label start:
    scene black
    hana "One."
    $ mood = "warm"
    hana "Two."
    call side
    hana "Three."
    "End."
    return
label side:
    hana "Side."
    return
label garden:
    flowchart scene "Garden"
    $ bloomed = True
    hana "Garden."
    ending garden_end "Garden End"
'''


@pytest.fixture(scope="module")
def program(tmp_path_factory):
    return load_l(tmp_path_factory.mktemp("console"), STORY)    # with F20's graph


class FiringGuard:
    """A watchdog stand-in that has fired once its author code raised."""

    def __init__(self) -> None:
        self.fired = False
        self.depth = 0

    def enter(self) -> None:
        self.depth += 1

    def exit(self) -> None:
        self.depth -= 1

    def consume_fired(self) -> bool:
        fired, self.fired = self.fired, False
        return fired


def started(program, *, store: PersistentStore | None = None, **kwargs) -> Interpreter:
    store = PersistentStore(identity_scheme=program.identity_scheme) if store is None else store
    launch = run_launch(program, persistent=store)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    interp = Interpreter(program, launch.namespace, persistent=store, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    return interp


def advance(interp: Interpreter, n: int = 1) -> None:
    for _ in range(n):
        assert interp.status is Status.WAITING, interp.status
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)


def drain(interp: Interpreter) -> list:
    return interp.take_commands(1 << 30)


def shown(interp: Interpreter) -> str:
    return interp.current.text


def set_value(interp: Interpreter, name: str, value: object):
    """A console Set as P4 applies it: a plain value bound in ``G``."""
    def apply() -> bool:
        interp.G[name] = value
        return True
    return apply


def code(interp: Interpreter, source: str):
    """A console Code run as P1's ``guarded`` applies it: ``author_call``, and False on any
    exception (the watchdog's included)."""
    compiled = compile(source, "<console>", "exec")

    def apply() -> bool:
        try:
            interp.author_call(exec, compiled, interp.G)
        except BaseException:                               # noqa: BLE001 (as guarded)
            interp.guard.consume_fired()
            return False
        return True
    return apply


def fingerprint(interp: Interpreter) -> tuple:
    G = interp.G
    story = {k: v for k, v in G.items() if k not in interp.reserved}
    t = interp.timeline
    return (repr(story), interp.core.state, interp.core.ready, interp.points.state(),
            interp.codex.state(), interp.last_checkpoint, list(t.states), t.cursor,
            t.block_pending, interp.status, interp.current)


# --- AC-F40-17 — a Set is in a save and a quick-save, and loads back ------------------------------

def test_ac17_a_set_is_saved_and_loads_back(program, tmp_path):
    interp = started(program)
    advance(interp)                                         # "Two."
    before = interp.checkpoint()
    held = interp.released
    assert interp.console_change(set_value(interp, "mood", "rainy")) is None
    assert interp.console_change(lambda: interp.points.set("trust", 7) is not None) is None
    assert interp.console_change(code(interp, "bag.append(dice.roll(1, 6))")) is None
    assert interp.released == held                          # nothing held or released
    state = interp.checkpoint()
    assert state is interp.last_checkpoint and state is not before
    # Only what author code reaches is re-recorded; the step itself is the same.
    assert (state.position, state.stage, state.audio, state.history) == (
        before.position, before.stage, before.audio, before.history)
    assert state.variables["mood"] == "rainy" and state.points["trust"] == 7
    assert len(state.variables["bag"]) == 1 and state.dice == interp.core.state != before.dice
    folder = tmp_path / "saves"
    data = ss.make_save(state)
    for slot in (saves.SlotId(1, 1), ss.QUICK_1):           # a save and a quick-save
        ss.write_slot(folder, data, slot)
        read = saves.read_slot_full(folder, slot, game_id=ss.GAME_ID).state
        assert read == state
        fresh = started(program)
        assert fresh.restore(read).result is RestoreResult.OK
        assert fresh.G["mood"] == "rainy" and fresh.points.state()["trust"] == 7
        assert fresh.G["bag"] == state.variables["bag"]
        assert shown(fresh) == "Two."


def test_ac17_a_changed_item_and_meter_are_in_the_step(program):
    interp = started(program)
    assert interp.console_change(lambda: interp.codex.install(("lantern",)) is None) is None
    assert interp.checkpoint().items.held == ("lantern",)
    assert round_trip(interp.checkpoint()) == interp.checkpoint()


# --- AC-F40-18 — every change is a wall; looking isn't ---------------------------------------------

def test_ac18_set_jump_and_code_are_walls_and_forward_steps_go(program):
    for kind in ("set", "code", "jump"):
        interp = started(program)
        advance(interp, 2)                                  # One, Two, Side
        interp.post(StepBack(1))                            # back on "Two.": a future kept
        interp.run(10_000)
        drain(interp)
        t = interp.timeline
        assert shown(interp) == "Two." and t.cursor == 1 and len(t.states) == 3
        if kind == "set":
            assert interp.console_change(set_value(interp, "mood", "x")) is None
            assert t.states == [interp.checkpoint()] and t.cursor == t.shown == 0
        elif kind == "code":
            assert interp.console_change(code(interp, "mood = 'y'")) is None
            assert t.states == [interp.checkpoint()] and t.cursor == t.shown == 0
        else:
            assert interp.console_jump("side") is None
            assert t.states == [] and t.cursor == -1
            interp.run(10_000)                              # "Side." again: the first step
            assert shown(interp) == "Side." and len(t.states) == 1
        refused = t.refused
        interp.post(StepBack(1))                            # the limit cue
        interp.run(10_000)
        assert t.refused == refused + 1
        interp.post(StepForward(1))                         # nothing remembered ahead
        interp.run(10_000)
        assert interp.status is Status.WAITING and t.replay == 0
        assert len(t.states) == 1


def test_ac18_looking_leaves_the_timeline(program):
    interp = started(program)
    advance(interp)
    before = fingerprint(interp)
    calls = interp.author_calls
    assert interp.author_call(eval, "repr(bag) + mood", interp.G) == "[]warm"
    assert interp.author_calls == calls + 1                 # counted as a $ line is
    assert fingerprint(interp) == before


def test_change_before_the_first_line_walls_the_next_checkpoint(tmp_path):
    program = load_files(tmp_path, {"main.vns": 'default n = 0\nlabel start:\n    pause 1\n'
                                                '    "A."\n    "B."\n'})
    interp = started(program)
    assert interp.waiting_for is not None and interp.checkpoint() is None
    assert interp.console_change(set_value(interp, "n", 5)) is None
    assert interp.timeline.block_pending
    interp.finish_wait()
    interp.run(10_000)
    assert interp.checkpoint().variables["n"] == 5


# --- Failures put everything back -------------------------------------------------------------

def test_in_place_list_change_that_cant_be_saved_is_undone(program):
    interp = started(program)
    advance(interp)
    G = interp.G
    bag, mood = G["bag"], G["mood"]
    before = fingerprint(interp)
    reason = interp.console_change(code(interp, "bag.append(1); bag.append(lambda: 1); "
                                                "points.trust; mood_two = 2"))
    assert reason and "bag" in reason                       # E85e's message
    assert fingerprint(interp) == before
    assert G["bag"] == [] and G["bag"] is not bag           # a fresh copy: in place undone
    assert G["mood"] is mood and "mood_two" not in G        # untouched: its own object
    advance(interp)                                         # the story goes on
    assert interp.status is Status.WAITING


def test_a_failed_apply_puts_dice_meters_and_items_back(program):
    interp = started(program)
    before = fingerprint(interp)

    def apply() -> bool:
        interp.G["bag"].append(3)
        interp.G["dice"].roll(1, 6)
        interp.points.set("trust", 9)
        interp.codex.install(("lantern",))
        return False
    assert interp.console_change(apply) == ""
    assert fingerprint(interp) == before


def test_persistent_value_broken_in_place_is_put_back(program):
    store = PersistentStore(identity_scheme=program.identity_scheme)
    interp = started(program, store=store)
    visited = store.get("visited")
    version = store.version
    before = fingerprint(interp)
    reason = interp.console_change(code(interp, "persistent.notes['a'] = 1; "
                                                "persistent.visited.append(lambda: 1); "
                                                "mood = 'gone'"))
    assert reason and "visited" in reason                   # E181's message
    assert fingerprint(interp) == before                    # G and the step as they were
    assert store.get("visited") is visited and visited == []    # put back, in place
    snap = store.values_snapshot()
    assert snap["visited"] == [] and snap["notes"] == {"a": 1}     # accepted kept
    assert store.version > version
    advance(interp, 2)                                      # the next lines don't fail
    assert interp.status is Status.WAITING


def test_watchdog_stop_puts_everything_back(program):
    guard = FiringGuard()
    interp = started(program, guard=guard)
    before = fingerprint(interp)

    def endless() -> None:
        interp.G["bag"].append(1)
        interp.G["mood"] = "loop"
        guard.fired = True                                  # the watchdog's SIGINT
        raise KeyboardInterrupt

    def apply() -> bool:
        try:
            interp.author_call(endless)
        except KeyboardInterrupt:
            assert guard.consume_fired()
            return False
        return True
    assert interp.console_change(apply) == ""
    assert guard.depth == 0                                 # exit() ran
    assert fingerprint(interp) == before
    assert not any(type(c) is StoryFailed for c in drain(interp))
    advance(interp)
    assert interp.status is Status.WAITING


def test_an_exception_out_of_apply_is_reraised_after_the_undo(program):
    interp = started(program)
    before = fingerprint(interp)

    def apply() -> bool:
        interp.G["bag"].append(1)
        raise KeyboardInterrupt                             # a real Ctrl+C
    with pytest.raises(KeyboardInterrupt):
        interp.console_change(apply)
    assert fingerprint(interp) == before


def test_change_and_jump_only_while_waiting(program):
    interp = started(program)
    interp.status = Status.RUNNING
    with pytest.raises(ValueError):
        interp.console_change(lambda: True)
    with pytest.raises(ValueError):
        interp.console_jump("garden")
    interp.status = Status.WAITING
    with pytest.raises(ValueError):
        interp.console_jump("nowhere")


# --- console_jump -------------------------------------------------------------------------------

def test_jump_keeps_values_clears_the_call_stack_and_records_arrivals(program):
    store = PersistentStore(identity_scheme=program.identity_scheme)
    interp = started(program, store=store)
    advance(interp, 2)                                      # in "side", called from start
    assert interp.call_stack and shown(interp) == "Side."
    interp.G["mood"] = "kept"
    stage, audio, nvl = interp.stage, interp.audio, interp.nvl
    pre = interp.checkpoint()
    drain(interp)
    assert interp.console_jump("garden") is None
    assert interp.call_stack == [] and interp.status is Status.RUNNING
    assert interp.checkpoint() is pre                       # until the label's first line
    interp.run(10_000)
    burst = drain(interp)
    assert [type(c) for c in burst[:3]] == [AudioRestore, NvlPage, ShowStage]
    assert burst[0].state == audio and burst[2].stage == stage and burst[2].restored
    assert [c.text for c in burst if type(c) is Say] == ["Garden."]
    assert interp.G["mood"] == "kept" and interp.nvl == nvl
    assert store.is_unlocked("replay", "garden")            # F36 arrive
    assert store.is_unlocked("achievement", "bloom")        # F37 at the checkpoint
    assert interp.flow.path                                 # F20's node reached
    advance(interp)                                         # the ending runs as for a jump
    assert store.is_unlocked("ending", "garden_end")


def test_jump_with_a_value_that_cant_be_saved_changes_nothing(program):
    interp = started(program)
    interp.G["mood"] = lambda: 1
    before = fingerprint(interp)
    held = interp.released
    reason = interp.console_jump("garden")
    assert reason and "mood" in reason
    assert fingerprint(interp) == before and interp.released == held


# --- revert_in_place (07 I-2) -----------------------------------------------------------------

def test_revert_in_place_puts_back_only_what_fails():
    store = PersistentStore.with_data(values={"a": [1], "b": {"k": 1}, "c": [2]},
                                      unlocks={"gallery": ["one"]})
    a, b, c = store.get("a"), store.get("b"), store.get("c")
    a.append(lambda: 1)
    b["k"] = 2                                              # a change the check accepts
    c.append(float("nan"))
    unlocks = store.unlocked("gallery")
    assert store.revert_in_place() == ("a", "c")
    assert store.get("a") is a and a == [1]
    assert store.get("c") is c and c == [2]
    assert store.get("b") is b and store.values_snapshot()["b"] == {"k": 2}
    assert store.unlocked("gallery") == unlocks
    store.check_in_place()                                  # nothing left to refuse
    assert same_value(store.values_snapshot(), {"a": [1], "b": {"k": 2}, "c": [2]})


def test_revert_in_place_with_nothing_changed_does_nothing():
    store = PersistentStore.with_data(values={"a": [1]})
    store.get("a")
    version = store.version
    assert store.revert_in_place() == ()
    assert store.version == version


# --- I-1: the _hold_scene split changes no golden -------------------------------------------------

def test_goldens_are_unchanged():
    from tests.runtime import corpus, fourthwall_story, glitch_story
    golden = corpus.GOLDENS / "commands_example.json"
    assert corpus.dumps(corpus.example_document()) == golden.read_bytes().decode("ascii")
    for module in (glitch_story, fourthwall_story):
        assert module.golden_text() == module.GOLDEN.read_bytes().decode("utf-8"), module


def test_restore_burst_order_is_unchanged(program):
    interp = started(program)
    advance(interp)
    state = round_trip(interp.checkpoint())
    fresh = started(program)
    drain(fresh)
    assert fresh.restore(state).result is RestoreResult.OK
    kinds = [type(c).__name__ for c in drain(fresh)]
    assert kinds[:3] == ["AudioRestore", "NvlPage", "ShowStage"] and "Say" in kinds
