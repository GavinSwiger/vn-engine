"""F65 trigger core at run time (``runtime/triggers.py``, ADR-0011): the saved state, the
evaluation points (``ClockChanged``, scene entry, ``pick``), first fit in declaration order,
once and repeat, ``after`` days and scenes, and saves, loads, going back and the quiet forward
re-run ending where the first run did. No statement declares triggers yet, so each test
registers kinds of its own."""

from dataclasses import replace

import pytest

from engine.core.storyclock import Calendar
from engine.runtime import triggers as triggers_mod
from engine.runtime.commands import Advance, Say, StepBack, StepForward, StoryFailed
from engine.runtime.errors import AuthorRefusal
from engine.runtime.interpreter import Status
from engine.runtime.state import GameState, StateInvalid
from engine.runtime.triggers import EMPTY_TRIGGERS, Armed, TriggerState
from engine.script.nodes import PyCode
from engine.script.triggers import Timing, Trigger
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

CAL = Calendar(day_card=False, last_day=30)


def cond(source: str) -> PyCode:
    return PyCode(source=source, line=1, column=0, mode="eval",
                  code=compile(source, "<script/main.vns>", "eval"))


class Kinds:
    """Test kinds: ``note`` is pushed (``on_fire`` logs, counts in the story variable
    ``fired``, and arms what a trigger's payload names), ``event`` is picked."""

    def __init__(self) -> None:
        self.specs: dict[str, list[dict]] = {"note": [], "event": []}
        self.log: list[tuple[str, object, bool]] = []
        for word in self.specs:
            triggers_mod.register_kind(word, collect=self._collect(word),
                                       on_fire=self._on_fire if word == "note" else None)

    def add(self, kind: str, name: str, when: str | None = None, **kw) -> None:
        self.specs[kind].append(dict(name=name, when=when, **kw))

    def _collect(self, word):
        def collect(program):
            at = program.labels["start"]
            return [Trigger(word, s["name"], at, cond(s["when"]) if s["when"] else None,
                            **{k: v for k, v in s.items() if k not in ("name", "when")})
                    for s in self.specs[word]]
        return collect

    def _on_fire(self, interp, fired):
        self.log.append((fired.trigger.name, fired.data, interp.timeline.replaying))
        interp.G["fired"] = interp.G.get("fired", 0) + 1        # story state it changes
        then = fired.trigger.payload
        if then is not None:
            triggers_mod.arm(interp, then, {"by": fired.trigger.name})

    def close(self) -> None:
        for word in self.specs:
            triggers_mod.unregister_kind(word)


@pytest.fixture
def kinds():
    found = Kinds()
    yield found
    found.close()


def _start(program, calendar=CAL):
    interp = launched(replace(program, calendar=calendar))
    interp.new_game(42)
    interp.run(10_000)
    return interp


def _texts(commands):
    return ["".join(span.text for span in c.body.plain()) for c in commands
            if isinstance(c, Say)]


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def _names(kinds):
    return [name for name, _, _ in kinds.log]


# --- The state ---------------------------------------------------------------------------------

def test_the_state_json_and_old_saves():
    assert triggers_mod.triggers_json(EMPTY_TRIGGERS) == {}
    state = TriggerState((Armed("message:invite", 4, None, {"to": ["hana", 2]}),
                          Armed("thought:hollow", None, 3)), frozenset({"event:a", "event:b"}))
    assert state.to_json() == {"armed": [{"id": "message:invite", "day": 4,
                                          "data": {"to": ["hana", 2]}},
                                         {"id": "thought:hollow", "scenes": 3}],
                               "retired": ["event:a", "event:b"]}
    assert TriggerState.from_json(state.to_json()) == state
    assert TriggerState.from_json({}) is EMPTY_TRIGGERS
    parts = TriggerState((Armed("message:late", 4, None, None, 2),))      # after N parts
    assert parts.to_json() == {"armed": [{"id": "message:late", "day": 4, "part": 2}]}
    assert TriggerState.from_json(parts.to_json()) == parts
    for bad in ({"armed": [{"id": "a:b", "part": 1}]},
                {"armed": [{"id": "a:b", "day": 2, "part": 100}]}):
        with pytest.raises(StateInvalid):
            TriggerState.from_json(bad)
    for bad in ([], {"x": []}, {"armed": [{"day": 1}]}, {"armed": [{"id": "nokind"}]},
                {"armed": [{"id": "a:b", "day": 0}]}, {"armed": [{"id": "a:b", "scenes": 0}]},
                {"armed": [{"id": "a:b", "data": None}]}, {"armed": [{"id": "a:b", "data": 1.5}]},
                {"armed": [{"id": "a:b"}, {"id": "a:b"}]}, {"retired": ["a:b", "a:b"]},
                {"retired": ["Bad:x"]}, {"armed": [{"id": "a:b", "day": True}]}):
        with pytest.raises(StateInvalid) as caught:
            TriggerState.from_json(bad)
        assert caught.value.reason == "triggers"


def test_data_problem():
    ok = {"from": "hana", "n": 3, "flags": [True, None], "deep": {"a": {"b": ["c"]}}}
    assert triggers_mod.data_problem(ok) is None
    assert triggers_mod.data_problem(1.5) == "kind"
    assert triggers_mod.data_problem(("t",)) == "kind"
    assert triggers_mod.data_problem({1: "x"}) == "key"
    assert triggers_mod.data_problem("x" * 1001) == "text"
    assert triggers_mod.data_problem(list(range(101))) == "too_many"
    assert triggers_mod.data_problem([[[[["too deep"]]]]]) == "too_deep"
    assert triggers_mod.data_problem(2**60) == "int"


def test_a_game_with_no_triggers_saves_as_before(tmp_path):
    interp = _start(story_game(tmp_path, ['"One."', "jump two"], after='label two:\n    "Two."\n'))
    take_all(interp)
    state = interp.checkpoint()
    assert state.triggers == EMPTY_TRIGGERS and "triggers" not in state.to_json()
    old = state.to_json()
    assert GameState.from_json(old).triggers == EMPTY_TRIGGERS


# --- Pushed: the clock and scene entry -------------------------------------------------------

def test_clock_changes_fire_in_declaration_order_once_and_repeat(tmp_path, kinds):
    kinds.add("note", "day2", timing=Timing(day=2), once=True)
    kinds.add("note", "evening", 'clock.part == "Evening"')        # repeats
    kinds.add("note", "never", "False")
    lines = ['"One."', "clock next", "clock next", '"Two."', "clock next day", "clock next",
             "clock next", '"Three."']
    interp = _start(story_game(tmp_path, lines))
    take_all(interp)
    assert kinds.log == []
    _advance(interp)
    assert _names(kinds) == ["evening"]
    _advance(interp)
    # day 2 morning: day2 once; evening again
    assert _names(kinds) == ["evening", "day2", "evening"]
    assert interp.triggers.retired == {"note:day2"} and interp.G["fired"] == 3


def test_scene_entry_arms_and_after_days_and_scenes_deliver(tmp_path, kinds):
    kinds.add("note", "send", "send_now", once=True, payload="note:letter")
    kinds.add("note", "letter", live=False, once=True, timing=Timing(after_days=1))
    kinds.add("note", "think", "think_now", once=True, payload="note:settled")
    kinds.add("note", "settled", live=False, once=True, timing=Timing(after_scenes=2))
    lines = ["$ send_now = True", "$ think_now = True", '"Home."', "jump a"]
    after = ('label a:\n    "In a."\n    clock next\n    "Still day one."\n'
             '    clock next day\n    "Day two."\n    jump b\n'
             'label b:\n    "In b."\n    jump c\n'
             'label c:\n    "In c."\n')
    interp = _start(story_game(tmp_path, lines, after=after,
                               top="default send_now = False\ndefault think_now = False\n"))
    take_all(interp)
    assert kinds.log == []                       # $ lines alone are no evaluation point
    _advance(interp)                             # entering a: both arm
    assert [(n, d) for n, d, _ in kinds.log] == [("send", None), ("think", None)]
    assert [a.to_json() for a in interp.triggers.armed] == [
        {"id": "note:letter", "day": 2, "data": {"by": "send"}},
        {"id": "note:settled", "scenes": 2, "data": {"by": "think"}}]
    _advance(interp)                             # clock next: same day, nothing
    assert len(kinds.log) == 2
    _advance(interp)                             # clock next day: the letter
    assert kinds.log[-1] == ("letter", {"by": "send"}, False)
    _advance(interp)                             # entering b: one scene left
    assert len(kinds.log) == 3 and interp.triggers.armed[0].scenes == 1
    _advance(interp)                             # entering c: settled
    assert kinds.log[-1][0] == "settled" and interp.triggers == EMPTY_TRIGGERS.__class__(
        (), frozenset({"note:send", "note:think"}))


# --- Picked: first fit -------------------------------------------------------------------------

def test_pick_is_first_fit_by_place_and_once_retires(tmp_path, kinds):
    kinds.add("event", "chat", "met", once=True, where="library")
    kinds.add("event", "quiet", where="library")
    kinds.add("event", "park", where="park", timing=Timing(part=2))
    kinds.add("event", "anywhere")
    interp = _start(story_game(tmp_path, ['"Wait."'], top="default met = False\n"))
    take_all(interp)
    pick = triggers_mod.pick
    assert pick(interp, "event", "library").trigger.name == "quiet"
    interp.G["met"] = True
    assert pick(interp, "event", "library").trigger.name == "chat"
    assert pick(interp, "event", "library").trigger.name == "quiet"   # chat retired
    assert pick(interp, "event", "park") is None                      # not Evening
    assert pick(interp, "event").trigger.name == "anywhere"
    assert [f.trigger.name for f in triggers_mod.due(interp, "event", "library")] == ["quiet"]
    assert interp.triggers.retired == {"event:chat"}
    triggers_mod.arm(interp, "event:chat")                            # arming un-retires
    assert pick(interp, "event", "library", take_it=False).armed
    assert kinds.log == []                                            # picked: no on_fire


def test_first_fit_stops_at_the_first(tmp_path, kinds):
    kinds.add("event", "a", "True", where="x")
    kinds.add("event", "b", "1/0", where="x")                         # never reached
    interp = _start(story_game(tmp_path, ['"Wait."']))
    assert triggers_mod.pick(interp, "event", "x").trigger.name == "a"


# --- Saves, loads, going back, the forward re-run --------------------------------------------

def test_load_back_and_forward_replay_exactly(tmp_path, kinds):
    kinds.add("note", "send", "send_now", once=True, payload="note:letter")
    kinds.add("note", "letter", live=False, once=True, timing=Timing(after_days=1))
    lines = ['"One."', "$ send_now = True", "jump a"]
    after = ('label a:\n    "Two."\n    clock next day\n    "Three."\n')
    interp = _start(story_game(tmp_path, lines, after=after, top="default send_now = False\n"))
    take_all(interp)
    _advance(interp)
    two = interp.checkpoint()
    assert [a.id for a in two.triggers.armed] == ["note:letter"]
    assert round_trip(two) == two
    _advance(interp)
    three = interp.checkpoint()
    assert three.triggers.armed == () and three.variables["fired"] == 2
    heard = len(kinds.log)
    # going back puts the armed letter back and fires nothing
    interp.post(StepBack(1))
    interp.run(10_000)
    take_all(interp)
    assert interp.triggers == two.triggers and len(kinds.log) == heard
    # the quiet forward re-run fires the letter again, replaying, and ends where we were
    interp.post(StepForward(1))
    while interp.busy:
        interp.run(10_000)
    take_all(interp)
    assert kinds.log[-1] == ("letter", {"by": "send"}, True)
    assert interp.checkpoint() == three
    # a load restores exactly and fires nothing
    interp.restore(round_trip(two))
    interp.run(10_000)
    take_all(interp)
    assert interp.triggers == two.triggers and len(kinds.log) == heard + 1
    _advance(interp)
    assert interp.checkpoint() == three
    # New Game empties it
    interp.new_game(42)
    assert interp.triggers == EMPTY_TRIGGERS


def test_saved_ids_the_script_no_longer_declares_are_kept_and_ignored(tmp_path, kinds):
    kinds.add("note", "here", "fire_it", once=True)
    interp = _start(story_game(tmp_path, ['"One."', "$ fire_it = True", "jump a"],
                               after='label a:\n    "Two."\n', top="default fire_it = False\n"))
    take_all(interp)
    saved = interp.checkpoint().to_json()
    saved["triggers"] = {"armed": [{"id": "note:gone", "day": 1}], "retired": ["event:old"]}
    interp.restore(GameState.from_json(saved))
    interp.run(10_000)
    take_all(interp)
    _advance(interp)
    assert _names(kinds) == ["here"]
    state = interp.checkpoint().triggers
    assert [a.id for a in state.armed] == ["note:gone"]
    assert state.retired == {"event:old", "note:here"}


# --- Errors ------------------------------------------------------------------------------------

@pytest.mark.parametrize("where", ["clock", "scene"])
def test_a_failing_condition_is_a_story_error_at_its_line(tmp_path, kinds, where):
    kinds.add("note", "bad", "go and " + ("1/0" if where == "clock" else "missing_name > 2"))
    lines = ['"One."', "$ go = True", "clock next" if where == "clock" else "jump a",
             '"Two."']
    interp = _start(story_game(tmp_path, lines, after='label a:\n    "In a."\n',
                               top="default go = False\n"))
    take_all(interp)
    assert interp.status is Status.WAITING          # the start's entry tested it: False
    commands = _advance(interp)
    assert interp.status is Status.FAILED
    error = next(c for c in commands if isinstance(c, StoryFailed)).error
    assert error.code == ("E85g" if where == "clock" else "E85b")
    assert error.line == interp.program.labels["start"].line


def test_too_many_armed_is_e457(tmp_path, kinds, monkeypatch):
    monkeypatch.setattr(triggers_mod, "ARMED_MAX", 2)
    for name in "abc":
        kinds.add("note", name, live=False)
    interp = _start(story_game(tmp_path, ['"Wait."']))
    triggers_mod.arm(interp, "note:a")
    triggers_mod.arm(interp, "note:b")
    triggers_mod.arm(interp, "note:a")                  # again: starts it again, still two
    with pytest.raises(AuthorRefusal) as caught:
        triggers_mod.arm(interp, "note:c")
    assert caught.value.code == "E457" and "over 2 notes" in caught.value.message
    with pytest.raises(ValueError):
        triggers_mod.arm(interp, "note:nope")
    with pytest.raises(ValueError):
        triggers_mod.arm(interp, "note:a", 1.5)
    assert triggers_mod.disarm(interp, "note:a") and not triggers_mod.is_armed(interp, "note:a")
