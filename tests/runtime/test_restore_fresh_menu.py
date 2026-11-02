"""F20 s4 — a jump's restore (F20 ``06-acceptance.md`` AC-F20-26, 28, 33's runtime and headless
rows; ``04`` §7.6; ``07`` §3.3, I-2; TR-F20-05).

Harnesses (06 §0.3): **Driver D** is ``RuntimeStoryDriver.restore(..., fresh_menu=True)`` over a
launched interpreter; **Run H** is ``flow_story.play`` (the recorder lives on the interpreter) or
``run_headless`` with a ``FlowStates`` holder. k_21 is Template L's checkpoint at M21 on run 1
with no route open.

Not here (F20 s6, the app's jump through F11's ``load_state``): AC-F20-28's skip-and-auto
**(F15)** and pending chapter auto-save **(F18)** rows, AC-F20-27's call-site scan, and the
windowed rows of AC-F20-33 (F11's nearest-point confirm and ``notice_load_no_fit``)."""

import json
import logging
from dataclasses import fields, replace
from types import MappingProxyType

import pytest

from engine.app.story import RuntimeStoryDriver
from engine.core.minigame_types import MinigameSig
from engine.core.paths import GamePaths
from engine.runtime.commands import (ChapterStarted, Say, ShowMenu, StartMinigame, StepBack,
                                     StepForward, StoryFailed, StoryWait)
from engine.runtime.flowchart import FlowStates
from engine.runtime.headless import HeadlessInputError, run_headless
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.menu import plain_text
from engine.runtime.minigame import MinigameState, MinigameWait
from engine.runtime.persistent import PersistentStore
from engine.runtime.state import GameState
from engine.script import load_story
from engine.script.flowgraph import FlowOptions
from engine.script.loader import LoadOptions
from tests.fixtures.F23.sigs import SIGS
from tests.runtime.flow_story import (RUN_1, at_line, key, launched, load_l, node, play,
                                      released)
from tests.runtime.story import fingerprint
from tests.script.helpers import template_g, template_l

OK, NOT_FOUND = RestoreResult.OK, RestoreResult.POSITION_NOT_FOUND
DEFAULT_FAILED, SCHEME = RestoreResult.DEFAULT_FAILED, RestoreResult.SCHEME_MISMATCH
LONG = "Z" * 10_000 + "\n2026-01-01 ERROR"


def k21(program, store=None, **kwargs) -> GameState:
    interp = launched(program, store, **kwargs)
    play(interp, RUN_1, until=at_line(21))
    return interp.checkpoint()


def offered(commands) -> list[tuple[str, bool]]:
    menu = next(c for c in reversed(commands) if type(c) is ShowMenu)
    return [(plain_text(c.body), c.locked) for c in menu.choices]


def jump(program, state, store=None, **kwargs):
    """Driver D: a fresh interpreter at the first line, then the jump's restore."""
    interp = launched(program, store, **kwargs)
    play(interp, until=at_line(6))
    released(interp)
    driver = RuntimeStoryDriver(interp, clock=lambda: 0.0, fixed_seed=42)
    return interp, driver.restore(state, fresh_menu=True)


def with_vars(state: GameState, **values) -> GameState:
    return replace(state, variables=MappingProxyType({**state.variables, **values}))


class Fired:
    """A guard whose watchdog has fired (F03's form): the interrupt is E85m."""

    def enter(self):
        pass

    def exit(self):
        pass

    def consume_fired(self):
        return True


# Template L's M21 with every choice behind ``allow(mode)``: "ok" offers all, "false" none,
# "raise" raises LONG, "loop" interrupts as the watchdog does (with ``Fired``).
MODES = dict(
    T='default mode = "ok"⏎define allow = lambda m: m == "ok" or (m != "false" and '
      '(_ for _ in ()).throw(KeyboardInterrupt if m == "loop" else ValueError(LONG)))⏎'
      'define LONG = "Z" * 10000 + "\\n2026-01-01 ERROR"',
    replace={22: '[8]"By the river" if allow(mode):',
             24: '[8]"From the shrine steps" if allow(mode):',
             26: '[8]"Wait at the bridge" if allow(mode):'})


# --- AC-F20-26 — menus are offered again ---------------------------------------------------------

def test_ac_f20_26_menus_are_offered_again(tmp_path, caplog):
    program = load_l(tmp_path / "l")
    state = k21(program)
    river, shrine, bridge = "By the river", "From the shrine steps", "Wait at the bridge"

    # Today's routes and show_locked decide what M21 offers.
    interp, outcome = jump(program, state)
    assert outcome.result is OK
    assert offered(released(interp)) == [(river, False), (shrine, False)]
    opened = PersistentStore(identity_scheme=program.identity_scheme)
    launched(program, opened)                           # registers F19's kinds
    opened.unlock("route", "promise")
    interp, outcome = jump(program, state, opened)
    assert offered(released(interp)) == [(river, False), (shrine, False), (bridge, False)]
    interp, outcome = jump(program, state, show_locked=True)
    assert offered(released(interp)) == [(river, False), (shrine, False), (bridge, True)]
    # A node menu whose choice needs coins >= 2, restored with coins = 0: not offered.
    coins = load_l(tmp_path / "coins", template_l(
        S='"Daichi waves from the stall."⏎    flowchart "Buy one?"'))
    interp = launched(coins)
    play(interp, until=at_line(14))
    poor = with_vars(interp.checkpoint(), coins=0)
    interp, outcome = jump(coins, poor)
    assert outcome.result is OK and offered(released(interp)) == [("Just look", False)]

    # Each condition once, top to bottom; check_only runs none.
    modes = load_l(tmp_path / "modes", template_l(**MODES))
    k = k21(modes)
    m21 = modes.get(k.position)
    interp = launched(modes)
    play(interp, until=at_line(6))
    calls = []
    real = interp._test
    interp._test = lambda code: (calls.append(code), real(code))[1]
    assert interp.restore(k, check_only=True, fresh_menu=True).result is OK and calls == []
    assert interp.restore(k, fresh_menu=True).result is OK
    assert calls == [c.condition.code for c in m21.choices]

    # On OK the committed state equals a plain restore's but for choices.waiting.
    plain = launched(program, opened)
    play(plain, until=at_line(6))
    assert plain.restore(state).result is OK
    interp, _ = jump(program, state, opened)
    a, b = plain.checkpoint(), interp.checkpoint()
    for field in fields(GameState):
        if field.name != "choices":
            assert getattr(a, field.name) == getattr(b, field.name), field.name
    assert a.choices.picks == b.choices.picks and a.choices.waiting != b.choices.waiting

    # All false, raising, looping: DEFAULT_FAILED, nothing changed, one echoed ERROR.
    for mode, code in (("false", "E178"), ("raise", "E85"), ("loop", "E85m")):
        interp = launched(modes, guard=Fired())
        play(interp, until=at_line(6))
        released(interp)
        before = fingerprint(interp)
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="vn"):
            outcome = interp.restore(with_vars(k, mode=mode), fresh_menu=True)
        assert outcome.result is DEFAULT_FAILED and outcome.error.code.startswith(code), mode
        assert fingerprint(interp) == before and interp.status is Status.WAITING
        assert not any(type(c) is StoryFailed for c in released(interp))
        errors = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert [(r.name, r.levelno) for r in errors] == [("vn.runtime", logging.ERROR)], mode
        text = errors[0].getMessage()
        assert "Z" * 121 not in text and "\n2026-01-01 ERROR" not in text

    # M21 is question-less: a kept line sid that exists is kept; an unknown sid or a sid of
    # the wrong kind (M13, a menu with no question) is dropped, never presented.
    kept = state.choices.waiting.kept
    assert type(program.get(kept)).__name__ == "Say"
    m13 = program.at("stall", (2,))
    for sid, line in ((kept, "kept"), ("stall/0123456789ab", "none"), (m13.sid, "none")):
        bad = replace(state, choices=replace(state.choices, waiting=replace(
            state.choices.waiting, kept=sid)))
        interp, outcome = jump(program, bad)
        assert outcome.result is OK
        commands = released(interp)
        assert next(c for c in commands if type(c) is ShowMenu).line == line, sid
        assert interp.choices.waiting.kept == (kept if line == "kept" else None)
        assert [c.sid for c in commands if type(c) is Say] == ([kept] if line == "kept"
                                                               else [])

    # Every other check still runs with fresh_menu.
    gone = replace(state, position="stall/0123456789ab", position_at=("nowhere", (0,)))
    interp = launched(program)
    for bad, result in ((replace(state, identity_scheme=state.identity_scheme + 1), SCHEME),
                        (gone, NOT_FOUND)):
        assert interp.restore(bad, fresh_menu=True).result is result
        assert interp.restore(bad, check_only=True, fresh_menu=True).result is result
    with pytest.raises(ValueError):
        interp.restore(state, landing=True, fresh_menu=True)


# --- AC-F20-28 — what a jump changes -----------------------------------------------------------

def test_ac_f20_28_what_a_jump_changes(tmp_path):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    store = PersistentStore(identity_scheme=program.identity_scheme)
    run1 = launched(program, store)
    play(run1, RUN_1)
    m21 = graph.nodes[node(graph, "M21")].id
    held = dict(run1.flowchart.states)
    state = held[m21]
    store.take_new_unlocks()
    before = (store.version, sorted(store.kind_items()), json.dumps(state.to_json()))

    interp = launched(program, store)
    interp.flowchart.states.update(held)                # run 1's states, as the holder
    play(interp, until=at_line(6))
    assert interp.restore(state, fresh_menu=True).result is OK
    commands = released(interp)
    after = interp.checkpoint()
    for field in fields(GameState):                     # history, NVL, items, points too
        if field.name != "choices":
            assert getattr(after, field.name) == getattr(state, field.name), field.name
    # Rollback: nothing before or after the node.
    interp.post(StepBack(1))
    interp.post(StepForward(1))
    interp.run(10_000)
    assert interp.checkpoint() is after and len(interp.timeline.states) == 1
    # The store, the records, and every held state are unchanged.
    assert (store.version, sorted(store.kind_items()), json.dumps(state.to_json())) == before
    assert interp.flowchart.states == held and not store.take_new_unlocks()
    assert offered(commands) == [("By the river", False), ("From the shrine steps", False)]

    # A jump to festival (a chapter node): no chapter card, the line after it shows.
    interp.restore(held["chapter:festival"], fresh_menu=True)
    commands = released(interp)
    assert not any(type(c) in (ChapterStarted, StoryWait) for c in commands)
    assert [c.sid for c in commands if type(c) is Say] == [program.at("start", (2,)).sid]

    # A save made after the jump is an ordinary save; its path ends in M21.
    interp.restore(state, fresh_menu=True)
    saved = GameState.from_json(json.loads(json.dumps(interp.checkpoint().to_json())))
    assert saved.flow.path[-1] == key(graph, "M21")
    other = launched(program)
    assert other.restore(saved).result is OK and other.current.sid == state.position


# --- AC-F20-33 — a jump to a minigame point is a load ----------------------------------------------

GAME = 'jump game⏎label game:⏎    flowchart scene "Game"⏎    minigame probe pairs=6 into turns'


def _probe(check) -> dict[str, MinigameSig]:
    return {**SIGS, "probe": replace(SIGS["probe"], check=check)}


def _loop(args, story):
    raise KeyboardInterrupt


def test_ac_f20_33_a_jump_to_a_minigame_point_is_a_load(tmp_path):
    root = tmp_path / "m"
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(template_g(S=GAME), encoding="utf-8")
    result = load_story(GamePaths(root.resolve()),
                        LoadOptions(minigames=SIGS, flowchart=FlowOptions()))
    program = result.program
    assert program is not None and not result.errors
    holder = FlowStates()
    run_headless(program, seed=42, minigames=SIGS, flow=holder, inputs=["advance"])
    state = holder["scene:game"]
    wait = state.minigame.waiting
    assert wait is not None and wait.name == "probe"

    # A valid state restarts the minigame exactly as a load does.
    load, jumped = launched(program, minigames=SIGS), launched(program, minigames=SIGS)
    assert load.restore(state).result is OK
    assert jumped.restore(state, fresh_menu=True).result is OK
    assert released(load) == released(jumped)
    commands = run_headless(program, seed=42, minigames=SIGS, flow=holder,
                            inputs=["jump scene:game"])
    assert any(type(c) is StartMinigame and c.restored for c in commands)

    # Refused: another name, an undeclared or missing argument, check_args refusing,
    # raising, or (watchdog) looping. Never fatal; no StartMinigame is released.
    def waiting(**change) -> GameState:
        return replace(state, minigame=MinigameState(replace(wait, **change)))

    rows = [
        (waiting(name="bare", args=MappingProxyType({})), SIGS),
        (waiting(args=MappingProxyType({**wait.args, "zzz": 1})), SIGS),
        (waiting(args=MappingProxyType({})), SIGS),
        (state, _probe(lambda args, story: "not today.")),
        (state, _probe(lambda args, story: 1 / 0)),
        (state, _probe(_loop)),
    ]
    for bad, sigs in rows:
        interp = launched(program, minigames=sigs, guard=Fired())
        assert interp.restore(bad, fresh_menu=True).result is NOT_FOUND
        assert interp.restore(bad, use_hints=True, fresh_menu=True).result is NOT_FOUND
        assert interp.status is Status.IDLE and released(interp) == []
        if sigs["probe"].check is _loop:
            continue                                    # headless runs have no watchdog
        holder["scene:game"] = bad
        with pytest.raises(HeadlessInputError) as caught:
            run_headless(program, seed=42, minigames=sigs, flow=holder,
                         inputs=["jump scene:game"])
        assert "position_not_found" in str(caught.value)
        assert not any(type(c) is StartMinigame for c in caught.value.commands)
