"""F59 retry (white) checks and the roll at run time: a failed retry check comes back once its
meter changes, a success retires it; the value at the try is saved on the pick, so a load
and going back replay it exactly; the roll is a story wait (``CheckRolled``) and a line in
History."""

import pytest

from engine.runtime.commands import (Advance, CheckRolled, Choose, Say, ShowMenu, StoryWait,
                                     WaitDone)
from engine.runtime.dice import Pcg32
from engine.runtime.interpreter import Interpreter
from engine.runtime.menu import ChoiceState, Pick, Roll
from engine.runtime.state import StateInvalid
from engine.script.choicecheck import passes, roll_text
from engine.script.menu import Menu
from tests.runtime.conftest import round_trip
from tests.runtime.menu_story import ALL, launched, load_text

STORY = '''define hana = Character("Hana")
points empathy 0 to 10 start 3
label start:
    menu:
        hana "Talk to me."
        "You're scared." check empathy medium retry:
            success:
                hana "Of the river."
            failure:
                hana "I'm fine."
        "Listen.":
            points empathy += 1
        "Wait.":
            $ pass
    hana "Again."
    jump start
'''
SCARED, LISTEN, WAIT = "You're scared.", "Listen.", "Wait."


def _program(tmp_path):
    result = load_text(tmp_path, STORY)
    assert not result.errors, [e.format() for e in result.errors]
    return result.program


def _roll(interp: Interpreter, value: int) -> tuple[int, int, bool]:
    core = Pcg32(interp.core.state, ready=True)
    a, b = 1 + core.below(6), 1 + core.below(6)
    return a, b, passes(a, b, value, 10)


def _to_menu(interp: Interpreter) -> list:
    """Advance through lines (and end the roll's wait) until the menu waits again."""
    seen = []
    for _ in range(20):
        interp.run(10_000)
        commands = interp.take_commands(ALL)
        seen += commands
        if type(interp.current) is Menu and interp.waiting_for is None:
            return seen
        if interp.waiting_for is not None:
            interp.post(WaitDone(interp.waiting_for))
        else:
            interp.post(Advance(interp.current.sid))
    raise AssertionError("the menu never came back")


def _start(program, seed: int, **kwargs) -> Interpreter:
    interp = launched(program, **kwargs)
    interp.new_game(seed)
    _to_menu(interp)
    return interp


def _choose(interp: Interpreter, text: str) -> list:
    menu = interp.current
    key = next(c.key for c in menu.choices if c.text == text)
    interp.post(Choose(menu.sid, key))
    return _to_menu(interp)


def _offered(interp: Interpreter) -> tuple[list[str], list[str]]:
    waiting = interp.choices.waiting
    texts = {c.key: c.text for c in interp.current.choices}
    return [texts[k] for k in waiting.pickable], [texts[k] for k in waiting.locked]


def _seed(program, ok: bool) -> int:
    """A seed whose first roll at empathy 3 gives ``ok``."""
    for seed in range(200):
        if _roll(_start(program, seed), 3)[2] is ok:
            return seed
    raise AssertionError("no seed")


def test_a_failed_retry_check_comes_back_once_the_meter_changes(tmp_path):
    program = _program(tmp_path)
    interp = _start(program, _seed(program, False), show_locked=True)
    seen = _choose(interp, SCARED)
    assert "I'm fine." in [''.join(s.text for s in c.body.plain()) for c in seen
                           if type(c) is Say]
    assert interp.choices.picks[-1].roll == Roll(3, False)
    assert _offered(interp) == ([LISTEN, WAIT], [SCARED])
    menu = [c for c in seen if type(c) is ShowMenu][-1]
    assert [c.check for c in menu.choices if c.locked] == [
        "[Empathy · Medium · Retry once Empathy changes]"]
    _choose(interp, WAIT)                                # nothing changed: still out
    assert _offered(interp) == ([LISTEN, WAIT], [SCARED])
    _choose(interp, LISTEN)                              # empathy 4: back, with its odds
    assert _offered(interp) == ([SCARED, LISTEN, WAIT], [])
    hidden = _start(program, _seed(program, False))      # without show_locked: hidden
    _choose(hidden, SCARED)
    assert _offered(hidden) == ([LISTEN, WAIT], [])


def test_a_success_retires_a_retry_check(tmp_path):
    program = _program(tmp_path)
    interp = _start(program, _seed(program, True), show_locked=True)
    _choose(interp, SCARED)
    assert interp.choices.picks[-1].roll == Roll(3, True)
    _choose(interp, LISTEN)
    assert _offered(interp) == ([LISTEN, WAIT], [SCARED])


def test_retry_state_replays_exactly_after_a_load_and_going_back(tmp_path):
    program = _program(tmp_path)
    for seed in range(8):
        interp = _start(program, seed, show_locked=True)
        before = interp.checkpoint()
        a, b, ok = _roll(interp, 3)
        _choose(interp, SCARED)
        after = interp.checkpoint()                       # the menu again, the try kept
        assert after.choices.picks[-1].roll == Roll(3, ok)
        offered = _offered(interp)
        back = launched(program, show_locked=True)        # a load: a JSON round trip
        assert back.restore(round_trip(after)).result.name == "OK"
        assert back.choices.picks == after.choices.picks
        assert _offered(back) == offered
        shown = [c for c in back.take_commands(ALL) if type(c) is ShowMenu][-1]
        assert [c.check for c in shown.choices if c.locked] == (
            [] if not offered[1] else ["[Empathy · Medium · Retry once Empathy changes]"]
            if not ok else ["[Empathy · Medium · 58%]"])
        assert interp.restore(before).result.name == "OK"  # going back: as never tried
        interp.take_commands(ALL)
        assert _offered(interp) == ([SCARED, LISTEN, WAIT], [])
        _choose(interp, SCARED)                            # the same roll again
        assert interp.choices.picks[-1].roll == Roll(3, ok)
        texts = [e.text for e in interp.history.entries]
        assert texts.count(roll_text("empathy", a, b, 3, 10)) == 1


def test_the_roll_is_a_story_wait_and_a_history_line(tmp_path):
    program = _program(tmp_path)
    interp = _start(program, 3)
    a, b, ok = _roll(interp, 3)
    menu = interp.current
    interp.post(Choose(menu.sid, menu.choices[0].key))
    interp.run(10_000)
    rolled = [c for c in interp.take_commands(ALL) if isinstance(c, StoryWait)]
    assert len(rolled) == 1 and type(rolled[0]) is CheckRolled
    cmd = rolled[0]
    assert (cmd.meter, cmd.dice, cmd.value, cmd.difficulty, cmd.ok) == (
        "Empathy", (a, b), 3, 10, ok)
    assert cmd.seconds == pytest.approx(1.3) and cmd.wait_id == interp.waiting_for
    kinds = [(e.kind, e.text) for e in interp.history.entries[-2:]]
    assert kinds == [("choice", SCARED),
                     ("line", f"Empathy check: {a + b + 3} vs 10, "
                              f"{'success' if ok else 'failure'}"
                              + (" (double six)" if a == b == 6 else
                                 " (double one)" if a == b == 1 else ""))]
    interp.post(WaitDone(cmd.wait_id))
    interp.run(10_000)
    said = [c for c in interp.take_commands(ALL) if type(c) is Say]
    assert ''.join(s.text for s in said[0].body.plain()) == (
        "Of the river." if ok else "I'm fine.")


def test_roll_text_names_the_doubles():
    assert roll_text("logic", 3, 3, 3, 12) == "Logic check: 9 vs 12, failure"
    assert roll_text("logic", 6, 6, 0, 99) == "Logic check: 12 vs 99, success (double six)"
    assert roll_text("logic", 1, 1, 50, 2) == "Logic check: 52 vs 2, failure (double one)"


def test_saved_rolls_read_back_and_old_saves_still_load():
    old = {"picks": [{"menu": "start/0123456789ab", "choice": "0123456789ab", "text": "A",
                      "question": None}], "waiting": None}
    assert ChoiceState.from_json(old).picks[0].roll is None
    state = ChoiceState((Pick("start/0123456789ab", "0123456789ab", "A", None, Roll(-4, False)),
                         Pick("start/0123456789ab", "0123456789ab", "A", None)))
    data = state.to_json()
    assert "roll" not in data["picks"][1] and data["picks"][0]["roll"] == {"value": -4,
                                                                           "ok": False}
    assert ChoiceState.from_json(data) == state and state.save_problem() is None
    for bad in ({"value": True, "ok": False}, {"value": 1, "ok": 1}, {"value": 1},
                {"value": 10 ** 12, "ok": True}, [1, True]):
        broken = {"picks": [dict(data["picks"][0], roll=bad)], "waiting": None}
        with pytest.raises(StateInvalid):
            ChoiceState.from_json(broken)


def test_going_back_and_forward_never_shows_the_roll_again(tmp_path):
    from tests.runtime.rollback_story import back, forward
    program = _program(tmp_path)
    interp = launched(program, rollback_steps=50)
    interp.new_game(3)
    _to_menu(interp)
    menu = interp.current
    interp.post(Choose(menu.sid, menu.choices[0].key))
    interp.run(10_000)
    interp.post(WaitDone(interp.waiting_for))
    interp.run(10_000)
    interp.take_commands(ALL)
    reply = interp.current.sid                           # the success or failure line
    notes = [e.text for e in interp.history.entries if "check:" in e.text]
    released = back(interp)
    assert type(interp.current) is Menu
    assert not [c for c in released if isinstance(c, CheckRolled)]
    released = forward(interp)                           # the quiet re-run: no dice
    assert interp.current.sid == reply
    assert not [c for c in released if isinstance(c, CheckRolled)]
    assert [e.text for e in interp.history.entries if "check:" in e.text] == notes
