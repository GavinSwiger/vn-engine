"""F63 story clock at run time: ``clock`` lines move ``GameState.clock``; saves, loads,
rollback and New Game restore it exactly; ``clock.<value>`` in conditions and text;
``ClockChanged`` fires once per change (specs/F63-story-clock/SPEC.md)."""

from dataclasses import replace

import pytest

from engine.core.storyclock import Calendar
from engine.runtime import clock as clock_mod
from engine.runtime.clock import EMPTY_CLOCK, ClockState
from engine.runtime.commands import Advance, Say, StepBack, StepForward
from engine.runtime.interpreter import Status
from engine.runtime.state import GameState, StateInvalid
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

CARD = Calendar(parts=("Morning", "After school", "Evening", "Night"), months=(
    ("March", 31), ("April", 30), ("May", 31)), first_year_day=31, last_day=30,
    day_card=False)                     # round 2's day card: tests/runtime/test_clock_round2.py


def _start(program, calendar=None):
    if calendar is not None:
        program = replace(program, calendar=calendar)
    interp = launched(program)
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


@pytest.fixture
def heard():
    events = []

    def listener(interp, event):
        events.append((event.old, event.new, interp.timeline.replaying))
    clock_mod.listen(listener)
    yield events
    clock_mod.unlisten(listener)


def test_the_state_json():
    assert EMPTY_CLOCK.day == 0 and clock_mod.clock_json(EMPTY_CLOCK) == {}
    state = ClockState(9, 2)
    assert ClockState.from_json(state.to_json()) == state
    for bad in ({"day": 0, "part": 0}, {"day": 1}, {"day": True, "part": 0},
                {"day": 1, "part": 0, "x": 1}, {"day": 1, "part": 100}, [1, 0]):
        with pytest.raises(StateInvalid):
            ClockState.from_json(bad)


def test_lines_move_the_clock_and_conditions_read_it(tmp_path, heard):
    lines = ['"{var=clock.date}, {var=clock.part}."', "clock next", "clock next",
             "clock next", "clock next",                       # past Night: the next day
             'if clock.day == 2 and clock.part == "Morning" and clock.weekday == "Tuesday":',
             '    "Day two, {var=clock.weekday}."',
             "clock next day", "clock go to Evening", "clock go to Evening",   # no change
             '"{var=clock.date} {var=clock.part}, {var=clock.month}: '
             '{var=clock.season}."',
             '$ left = clock.days_left()',
             '"{var=left} days left, or {var=clock.day}."',
             'clock go to "31 March" Night',
             '"{var=clock.date}."']
    interp = _start(story_game(tmp_path, lines), CARD)
    seen = _texts(take_all(interp))
    for _ in range(4):
        seen += _texts(_advance(interp))
    assert seen == ["Monday 1 April, Morning.", "Day two, Tuesday.",
                    "Wednesday 3 April Evening, April: .", "27 days left, or 3.",
                    "Monday 31 March."]                     # next year's, as it is past
    assert interp.clock == ClockState(92, 3)              # a 92-day year
    assert [(o.day, o.part, n.day, n.part) for o, n, _ in heard] == [
        (1, 0, 1, 1), (1, 1, 1, 2), (1, 2, 1, 3), (1, 3, 2, 0), (2, 0, 3, 0), (3, 0, 3, 2),
        (3, 2, 92, 3)]
    assert not any(replaying for _, _, replaying in heard)


def test_saves_loads_rollback_and_new_game(tmp_path, heard):
    lines = ['"One."', "clock next", '"Two."', "clock next day", '"Three."']
    interp = _start(story_game(tmp_path, lines), Calendar(day_card=False))
    take_all(interp)
    one = interp.checkpoint()
    assert one.clock == EMPTY_CLOCK and "clock" not in one.to_json()   # as before F63
    _advance(interp)
    two = interp.checkpoint()
    assert two.clock == ClockState(1, 1) and round_trip(two) == two
    _advance(interp)
    assert interp.checkpoint().clock == ClockState(2, 0) and len(heard) == 2
    # going back puts the clock back and announces nothing
    interp.post(StepBack(1))
    interp.run(10_000)
    take_all(interp)
    assert interp.clock == ClockState(1, 1) and len(heard) == 2
    # the quiet forward re-run runs clock next day again, and announces it (replaying)
    interp.post(StepForward(1))
    while interp.busy:
        interp.run(10_000)
    take_all(interp)
    assert interp.clock == ClockState(2, 0)
    assert len(heard) == 3 and heard[-1][2] is True
    # a load restores exactly and announces nothing; an old save (no clock) is the start
    interp.restore(round_trip(two))
    interp.run(10_000)
    take_all(interp)
    assert interp.clock == ClockState(1, 1) and len(heard) == 3
    old = two.to_json()
    del old["clock"]
    interp.restore(GameState.from_json(old))
    interp.run(10_000)
    assert interp.clock == EMPTY_CLOCK and clock_mod.now(interp) == ClockState(1, 0)
    interp.new_game(1)
    interp.run(10_000)
    assert interp.clock == EMPTY_CLOCK and len(heard) == 3


def test_a_save_from_a_calendar_with_more_parts(tmp_path):
    interp = _start(story_game(tmp_path, ['"One."']), Calendar(parts=("Day", "Night")))
    state = replace(interp.checkpoint(), clock=ClockState(4, 3))
    interp.restore(state)
    interp.run(10_000)
    assert interp.clock == ClockState(4, 1)                     # the last part


def test_the_view_refuses_writes_and_a_game_may_own_clock(tmp_path):
    interp = _start(story_game(tmp_path, ['$ setattr(clock, "day", 3)', '"After."']))
    assert interp.status is Status.FAILED
    failed = take_all(interp)[-1]
    assert failed.error.code == "E435" and "clock next" in failed.error.message
    own = _start(story_game(tmp_path, ['"{var=clock}."', "$ clock += 1", '"{var=clock}."'],
                            top="default clock = 5\n"))
    assert _texts(take_all(own)) == ["5."]
    assert _texts(_advance(own)) == ["6."] and own.checkpoint().variables["clock"] == 6


def test_a_story_error_for_a_date_the_calendar_cant_read(tmp_path):
    interp = _start(story_game(tmp_path, ['clock go to "31 Octobre"', '"After."']))
    assert interp.status is Status.FAILED
    assert take_all(interp)[-1].error.code == "E435"
