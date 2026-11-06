"""F63 round 2 at run time: the day card (a chapter-like card when a ``clock`` line changes the
day; none with ``day_card = false`` or in F14's quiet re-run), ``show clock`` / ``hide clock``
saved in ``GameState.clock``, and W304 at launch (specs/F63-story-clock/SPEC.md)."""

from dataclasses import replace

import pytest

from engine.core.storyclock import Calendar
from engine.runtime.clock import DAY_CARD_HOLD, EMPTY_CLOCK, ClockState, day_card
from engine.runtime.commands import (Advance, Say, ShowStage, StepBack, StepForward,
                                     StoryWait, TitleCard, WaitDone)
from engine.runtime.images import ImageSource
from engine.runtime.launch import run_launch
from engine.runtime.state import StateInvalid
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import IMG9, launched, story_game, take_all

NIGHTS = Calendar(parts=("Dusk", "Midnight"), day_text="Night {day}")


def _start(program, calendar=NIGHTS):
    interp = launched(replace(program, calendar=calendar))
    interp.new_game(42)
    interp.run(10_000)
    return interp


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def _finish(interp):
    out = []
    while interp.waiting_for is not None:
        interp.post(WaitDone(interp.waiting_for))
        interp.run(10_000)
        out += take_all(interp)
    return out


def _texts(commands):
    return ["".join(span.text for span in c.body.plain()) for c in commands
            if isinstance(c, Say)]


def test_a_new_day_plays_a_card_like_a_chapter_card(tmp_path):
    lines = ['"One."', "clock next", '"Two."', "clock next", '"Three."']
    interp = _start(story_game(tmp_path, lines))
    take_all(interp)
    assert _texts(_advance(interp)) == ["Two."]            # a new part: no card
    out = _advance(interp)                                  # Midnight -> Dusk of night 2
    cards = [c.card for c in out if isinstance(c, ShowStage) and c.card is not None]
    assert cards == [TitleCard("Night 2", None, "Night 2", kind="day")]
    waits = [c for c in out if isinstance(c, StoryWait)]
    assert len(waits) == 1 and waits[0].for_stage and not _texts(out)
    rest = _finish(interp)
    holds = [c.seconds for c in rest if isinstance(c, StoryWait) and c.seconds]
    assert holds == [DAY_CARD_HOLD] and _texts(rest) == ["Three."]
    assert interp.clock == ClockState(2, 0)


def test_day_card_off_and_the_quiet_rerun(tmp_path):
    lines = ['"One."', "clock next day", '"Two."']
    interp = _start(story_game(tmp_path / "off", lines), replace(NIGHTS, day_card=False))
    take_all(interp)
    out = _advance(interp)
    assert _texts(out) == ["Two."] and not [c for c in out if isinstance(c, StoryWait)]
    # with the card: going back and forward re-runs the clock line quietly, with no card
    interp = _start(story_game(tmp_path / "on", lines))
    take_all(interp)
    _advance(interp)
    _finish(interp)
    assert interp.clock == ClockState(2, 0)
    interp.post(StepBack(1))
    interp.run(10_000)
    take_all(interp)
    assert interp.clock == EMPTY_CLOCK
    interp.post(StepForward(1))
    while interp.busy:
        interp.run(10_000)
    out = take_all(interp)
    assert interp.clock == ClockState(2, 0)
    assert not [c for c in out if isinstance(c, ShowStage) and c.card is not None]


def test_day_card_words_follow_the_calendar():
    assert day_card(Calendar(), 4).title == "Day 4"
    cozy = Calendar(seasons=("Spring", "Summer"), day_text="{season}, day {season_day}")
    assert day_card(cozy, 30).title == "Summer, day 2"


def test_show_and_hide_clock_are_saved(tmp_path):
    lines = ['"One."', "show clock", '"Two."', "clock next", '"Three."', "hide clock",
             '"Four."']
    interp = _start(story_game(tmp_path, lines))
    one = take_all(interp) and interp.checkpoint()
    assert not one.clock.shown and "clock" not in one.to_json()
    _advance(interp)
    two = interp.checkpoint()
    assert two.clock == ClockState(0, 0, True) and two.to_json()["clock"] == {
        "day": 0, "part": 0, "shown": True}                  # shown, time never moved
    assert round_trip(two) == two
    _advance(interp)
    three = interp.checkpoint()
    assert three.clock == ClockState(1, 1, True) and round_trip(three) == three
    _advance(interp)
    assert interp.checkpoint().clock == ClockState(1, 1, False)
    # a load puts back what was shown; New Game starts hidden
    interp.restore(round_trip(two))
    interp.run(10_000)
    assert interp.clock.shown
    interp.new_game(1)
    interp.run(10_000)
    assert interp.clock == EMPTY_CLOCK


def test_the_shown_json_is_checked():
    assert ClockState.from_json({"day": 3, "part": 1, "shown": True}) == ClockState(3, 1, True)
    for bad in ({"day": 0, "part": 0}, {"day": 0, "part": 1, "shown": True},
                {"day": 1, "part": 0, "shown": False}, {"day": 1, "part": 0, "shown": 1}):
        with pytest.raises(StateInvalid):
            ClockState.from_json(bad)


def test_w304_when_the_game_has_a_picture_called_clock(tmp_path):
    program = story_game(tmp_path, ["show clock", '"One."', "hide clock", "show clock at left"])
    found = run_launch(program, images=ImageSource.from_files(
        (*IMG9, "images/clock.png"))).warnings
    assert [(w.code, w.line) for w in found if w.code == "W304"] == [
        ("W304", program.at("start", (0,)).line), ("W304", program.at("start", (2,)).line)]
    assert "show clock at center" in [w for w in found if w.code == "W304"][0].message
    quiet = run_launch(program, images=ImageSource.from_files(IMG9)).warnings
    assert not [w for w in quiet if w.code == "W304"]
