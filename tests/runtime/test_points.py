"""F22 step 2 — meters at run time (``runtime/points.py``; ``GameState.points``; the interpreter's
new game, checkpoint, and restore; the ``points`` engine name): AC-F22-03 to 07 and 09, and the
I-9 restore drop of names reserved later."""

import json
import logging

import pytest

from engine.runtime.commands import Advance, StoryFailed
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.points import (EMPTY_POINTS, SAVED_NAMES_MAX, MeterSpec, Points,
                                   PointsState, UnknownMeter)
from engine.runtime.state import GameState, StateInvalid
from engine.script.points import POINTS_LIMIT
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import launched, story_game, take_all

BIG = POINTS_LIMIT


def at_line(program, **kwargs):
    interp = launched(program, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    assert interp.status is Status.WAITING, take_all(interp)
    return interp


def advance(interp) -> None:
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)


def failure(program):
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    failed = take_all(interp)[-1]
    assert type(failed) is StoryFailed, failed
    return failed.error


# --- AC-F22-03 — the points line and the reads, headless ------------------------------------------

AC03 = ["points a += 3", "$ r = [points.a]", "points a += 20", "$ r.append(points.a)",
        "points a -= 50", '$ r.append(points["a"])', "points a = 2", "points a += bonus",
        "$ r.append(points.a)", "points u += 2000000000", "$ r.append(points.u)",
        '$ h = [points.highest(), points.highest("a", "b"), points.highest("b", "a")]',
        "points u = 0", "$ h.append(points.highest())", "points a = 0",
        "$ h.append(points.highest())", '$ h.append(points.highest("b", "u"))',
        'if points.a == 0 and points["u"] == 0:', "    $ cond = True", 'hana "Done."']


def test_ac03_changes_clamp_and_reads(tmp_path):
    program = story_game(tmp_path, AC03, top="points a 0 to 10\npoints u b\ndefault bonus = 4\n")
    interp = at_line(program)
    variables = interp.checkpoint().variables
    assert variables["r"] == [3, 10, 0, 6, BIG]
    assert variables["h"] == ["u", "a", "a", "a", "a", "b"] and variables["cond"] is True
    assert dict(interp.checkpoint().points) == {"a": 0, "u": 0, "b": 0}


# --- AC-F22-04 — E236 stops the story -------------------------------------------------------------

def test_ac04_e236_forms(tmp_path):
    amount = "the amount for points a must be a whole number, but it is "
    write = "Python can't change points. Use the points statement, e.g. points a = 3."
    rows = [("points a += 1.5", amount + "1.5 (a decimal number)."),
            ("points a = True", amount + "True (True or False)."),
            ('points a -= "2"', amount + "'2' (text)."),
            ('$ x = points["aa"]', 'there is no meter named "aa". Did you mean "a"?'),
            ('$ setattr(points, "a" + "", 1)', write), ('$ points["a"] = 1', write),
            ('$ delattr(points, "a" + "")', write),
            ('$ del points["b"]', write.replace("points a =", "points b ="))]
    for index, (line, message) in enumerate(rows):
        program = story_game(tmp_path / str(index), [line, 'hana "x"'], top="points a b\n")
        error = failure(program)
        assert (error.code, error.message, error.line) == ("E236", message, 4), line
    error = failure(story_game(tmp_path / "f", ["points a += 1 / 0"], top="points a\n"))
    assert error.code == "E85g" and error.source_line == "points a += 1 / 0"
    error = failure(story_game(tmp_path / "n", ["$ x = points.highest()"]))
    assert error.code == "E236" and error.message.startswith("points.highest() needs a meter")
    # a define that reads points, at launch
    program = story_game(tmp_path / "d", ['hana "x"'], top="points a\ndefine bonus = points.a\n")
    (error,) = run_launch(program).errors
    assert (error.code, error.line) == ("E236", 3)
    assert error.message == ("define bonus couldn't be set: it reads points, which exist only "
                             "once a game has started. Use a lambda or a default.")


# --- AC-F22-05 — GameState.points -----------------------------------------------------------------

TOP5 = "points a 0 to 10\npoints affection 0 to 100 start 50\ndefault x = points.affection\n"


def test_ac05_game_state_points(tmp_path):
    # changes at the checkpoint after the line; round-trip; New Game; a default reads points
    program = story_game(tmp_path / "run", ['hana "1"', "points a += 3", 'hana "2"'], top=TOP5)
    interp = at_line(program)
    first = interp.checkpoint()
    assert dict(first.points) == {"a": 0, "affection": 50} and first.variables["x"] == 50
    advance(interp)
    assert interp.checkpoint().points["a"] == 3 and first.points["a"] == 0
    second = interp.checkpoint()
    assert round_trip(second) == second and round_trip(second).points == second.points
    assert second.to_json()["points"] == {"values": {"a": 3, "affection": 50}}
    interp.new_game(1)
    interp.run(10_000)
    assert dict(interp.checkpoint().points) == {"a": 0, "affection": 50}
    # restore merges the saved values with the declared meters
    program = story_game(tmp_path / "merge", ['hana "1"'], top=TOP5)
    interp = at_line(program)
    data = interp.checkpoint().to_json()
    rows = [(None, {"a": 0, "affection": 50}),                      # no key: starts
            ({"a": 4}, {"a": 4, "affection": 50}),                  # missing meter: start
            ({"a": 50, "affection": -3}, {"a": 10, "affection": 0}),  # clamped
            ({"gone": 7, "a": 1}, {"a": 1, "affection": 50, "gone": 7})]   # kept, hidden
    for values, expected in rows:
        edited = dict(data)
        if values is None:
            del edited["points"]
        else:
            edited["points"] = {"values": values}
        assert interp.restore(GameState.from_json(edited)).result is RestoreResult.OK
        assert dict(interp.checkpoint().points) == expected, values
        assert interp.points.names() == ("a", "affection")
    assert interp.checkpoint().to_json()["points"]["values"]["gone"] == 7       # re-saved
    # hostile values: StateInvalid, no echo, interpreter unchanged
    program = story_game(tmp_path / "hostile", ['hana "1"'], top=TOP5)
    interp = at_line(program)
    data, before = interp.checkpoint().to_json(), interp.checkpoint()
    many = {f"m{i}": 0 for i in range(SAVED_NAMES_MAX + 1)}
    for bad in ({"values": {"a": True}}, {"values": {"a": 1.5}}, {"values": {"a": 2 * 10**9}},
                {"values": {"a": [1]}}, {"values": []}, [], {"values": many},
                {"values": {"s" * 65: 1}}, {"values": {"a b": 1}}, {"values": {"_a": 1}},
                {"values": {}, "more": 1}):
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**data, "points": bad})
        assert caught.value.reason == "points" and "a b" not in str(caught.value)
    assert interp.checkpoint() is before and interp.points.get("a") == 0


def test_i9_restore_drops_names_reserved_later(tmp_path, caplog):
    program = story_game(tmp_path, ['hana "1"'], top="points a\n")
    interp = at_line(program)
    data = interp.checkpoint().to_json()
    data["variables"].update({"points": 3, "Dissolve": 1, "kept": 2})
    with caplog.at_level(logging.WARNING, logger="vn"):
        assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert dict(interp.checkpoint().variables) == {"kept": 2}
    (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert record.getMessage() == ('Restored state: "points", "Dissolve" are a name the engine '
                                   "uses in this version of the game, so the saved value was "
                                   "dropped.")


def test_i6_a_failing_default_puts_the_meters_back(tmp_path):
    program = story_game(tmp_path, ['hana "1"'], top="points a 0 to 10 start 1\n"
                                                      "default late = 10 // points.a\n")
    interp = at_line(program)
    data = interp.checkpoint().to_json()
    del data["variables"]["late"]
    data["points"] = {"values": {"a": 0}}
    interp.points.set("a", 5)
    outcome = interp.restore(GameState.from_json(data))
    assert outcome.result is RestoreResult.DEFAULT_FAILED and interp.points.get("a") == 5


# --- AC-F22-06 — rollback through restore ---------------------------------------------------------

def test_ac06_restore_save_and_plugin_add(tmp_path):
    program = story_game(tmp_path, ['hana "1"', "points yuri += 3", 'hana "2"', 'hana "3"'],
                         top="points yuri\n")
    interp = at_line(program)
    one = interp.checkpoint()
    advance(interp)
    two = interp.checkpoint()
    assert interp.restore(one).result is RestoreResult.OK and interp.points.get("yuri") == 0
    advance(interp)
    assert interp.points.get("yuri") == 3
    saved = json.dumps(two.to_json())
    interp.points.add("yuri", 4)                            # a plugin, after the checkpoint
    assert interp.restore(GameState.from_json(json.loads(saved))).result is RestoreResult.OK
    assert interp.points.get("yuri") == 3                   # discarded by restore
    interp.points.add("yuri", 4)
    advance(interp)
    assert interp.checkpoint().points["yuri"] == 7          # captured by the next checkpoint


# --- AC-F22-07 — the Points API -------------------------------------------------------------------

def test_ac07_points_api():
    points = Points((MeterSpec("sayori", 0, 10, 2, True), MeterSpec("yuri")))
    assert points.names() == ("sayori", "yuri") and points.spec("sayori").ranged
    assert (points.get("sayori"), points.add("sayori", 20), points.set("sayori", -4)) == (2, 10, 0)
    assert points.add("yuri", 3) == 3 and points.highest() == "yuri"
    with pytest.raises(UnknownMeter) as caught:
        points.get("sayory")
    assert caught.value.suggestion == "sayori" and isinstance(caught.value, KeyError)
    assert str(caught.value) == 'there is no meter named "sayory". Did you mean "sayori"?'
    for bad in (1.5, True):
        with pytest.raises(TypeError):
            points.add("yuri", bad)
    state = points.state()
    assert points.state() is state and state == PointsState({"yuri": 3, "sayori": 0})
    points.set("yuri", 3)
    assert points.state() is state                          # unchanged: one object (I-7)
    merged = points.merge(PointsState({f"h{i}": 1 for i in range(SAVED_NAMES_MAX)}))
    assert len(merged) == SAVED_NAMES_MAX and list(merged)[:2] == ["sayori", "yuri"]
    assert Points().state() == EMPTY_POINTS


# --- AC-F22-09 — W120 -----------------------------------------------------------------------------

def test_ac09_w120_once_per_line(tmp_path, caplog):
    lines = ["points a += 20", "points a -= 50", "call again", "call again", 'hana "x"']
    program = story_game(tmp_path, lines, top="points a 0 to 10\n",
                         after="label again:\n    points a += 20\n    return\n")
    for dev, expected in ((True, [(4, "points a += 20 went past the top of its range, so a "
                                      "is 10, not 20."),
                                  (5, "points a -= 50 went past the bottom of its range, so a "
                                      "is 0, not -40."),
                                  (10, "points a += 20 went past the top of its range, so a "
                                       "is 10, not 20.")]),
                          (False, [])):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="vn"):
            at_line(program, dev=dev)
        found = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert found == [f"script/main.vns, line {line}: {text}" for line, text in expected]
        assert all(r.name == "vn.runtime" for r in caplog.records)
