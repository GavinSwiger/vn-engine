"""F62 round 2 at run time: ``show meter`` / ``hide meter`` change ``GameState.points``'s
shown list, so saves, loads, rollback and New Game restore it exactly."""

import pytest

from engine.runtime.commands import Advance, StepBack, StepForward
from engine.runtime.points import SHOWN_MAX, MeterSpec, Points, PointsState, UnknownMeter
from engine.runtime.state import StateInvalid
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

TOP = "points hana 0 to 10\npoints sanity 0 to 100 start 100\n"


def _start(program):
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    return interp


def _advance(interp):
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    take_all(interp)


def test_points_show_and_hide():
    points = Points((MeterSpec("a"), MeterSpec("b"), MeterSpec("c")))
    points.show("b", "a")
    points.show("a", "c")                               # a shown one keeps its place
    assert points.shown() == ("b", "a", "c") and points.state().shown == ("b", "a", "c")
    points.hide("a")
    assert points.shown() == ("b", "c")
    with pytest.raises(UnknownMeter):
        points.show("d")
    points.reset()
    assert points.shown() == ()


def test_the_state_json():
    state = PointsState({"a": 1, "b": 2}, ("b",))
    assert state.to_json() == {"values": {"a": 1, "b": 2}, "shown": ["b"]}
    assert PointsState.from_json(state.to_json()) == state
    assert PointsState({"a": 1}).to_json() == {"values": {"a": 1}}         # as before
    assert state != PointsState({"a": 1, "b": 2})
    for bad in ({"values": {"a": 1}, "shown": ["z"]}, {"values": {"a": 1}, "shown": "a"},
                {"values": {"a": 1}, "shown": ["a", "a"]},
                {"values": {"a": 1}, "shown": [], "x": 1},
                {"values": {f"m{i}": 0 for i in range(40)},
                 "shown": [f"m{i}" for i in range(SHOWN_MAX + 1)]}):
        with pytest.raises(StateInvalid):
            PointsState.from_json(bad)


def test_merge_drops_a_meter_no_longer_declared():
    points = Points((MeterSpec("a"),))
    merged = points.merge(PointsState({"a": 1, "gone": 2}, ("gone", "a")))
    assert merged.shown == ("a",)
    points.install(merged)
    assert points.shown() == ("a",)


def test_lines_save_load_and_roll_back(tmp_path):
    lines = ['"One."', "show meter hana sanity", '"Two."', "hide meter sanity",
             "points hana += 3", '"Three."']
    interp = _start(story_game(tmp_path, lines, top=TOP))
    assert interp.points.shown() == ()
    _advance(interp)
    two = interp.checkpoint()
    assert two.points.shown == ("hana", "sanity") and round_trip(two) == two
    _advance(interp)
    three = interp.checkpoint()
    assert three.points.shown == ("hana",) and dict(three.points)["hana"] == 3
    # back: both shown again; forward: sanity hidden again
    interp.post(StepBack(1))
    interp.run(10_000)
    take_all(interp)
    assert interp.points.shown() == ("hana", "sanity")
    interp.post(StepForward(1))
    while interp.busy:
        interp.run(10_000)
    take_all(interp)
    assert interp.points.shown() == ("hana",)
    # a load restores exactly; New Game shows none
    interp.restore(round_trip(two))
    interp.run(10_000)
    take_all(interp)
    assert interp.points.shown() == ("hana", "sanity")
    interp.new_game(1)
    interp.run(10_000)
    assert interp.points.shown() == ()
