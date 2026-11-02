"""F14 step 1 — ``GameState.rollback`` and the ``rollback`` statement at run time
(``runtime/rollback.py``, ``runtime/state.py``, the interpreter's new game, checkpoint, and
restore): AC-F14-02 with 07 I-1's older-saves rows, and the executor (04 §6.3)."""

import json
import logging

import pytest

from engine.runtime import images
from engine.runtime.commands import Advance, ShowStage
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.rollback import ROLLBACK_OFF, ROLLBACK_ON, RollbackState
from engine.runtime.state import GameState, StateInvalid, reserved_since_save
from tests.runtime.conftest import make_state
from tests.runtime.effects_story import launched, story_game, take_all


def at_line(program):
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    assert interp.status is Status.WAITING, take_all(interp)
    return interp


def advance(interp) -> None:
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)


# --- AC-F14-02 — the flag round-trips; old and hostile values -------------------------------------

def test_ac02_round_trip_absent_and_hostile_values(tmp_path):
    base = make_state({"n": 1}).to_json()
    assert base["rollback"] == {"enabled": True}                    # always written
    for value, expected in (({"enabled": True}, ROLLBACK_ON), ({"enabled": False}, ROLLBACK_OFF)):
        state = GameState.from_json({**base, "rollback": value})
        assert state.rollback is expected
        text = json.dumps(state.to_json(), ensure_ascii=True)
        assert json.dumps(GameState.from_json(json.loads(text)).to_json(),
                          ensure_ascii=True) == text
    old = {k: v for k, v in base.items() if k != "rollback"}
    assert GameState.from_json(old).rollback is ROLLBACK_ON and base["format"] == 1
    for bad in ({"enabled": 1}, {"enabled": "false"}, {"enabled": None}, {},
                {"enabled": True, "ZZMARK": 1}, [], "ZZMARK", True):
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**base, "rollback": bad})
        assert caught.value.reason == "rollback"
        assert "ZZMARK" not in str(caught.value) and "ZZMARK" not in repr(caught.value)
    with pytest.raises(StateInvalid):
        RollbackState.from_json(None)
    # The flag is saved and restored through the interpreter.
    program = story_game(tmp_path, ['hana "1"', "rollback off", 'hana "2"', "rollback on",
                                    'hana "3"'])
    interp = at_line(program)
    assert interp.checkpoint().rollback is ROLLBACK_ON
    advance(interp)
    saved = interp.checkpoint()
    assert saved.rollback is ROLLBACK_OFF and saved.to_json()["rollback"] == {"enabled": False}
    advance(interp)
    assert interp.rollback_state is ROLLBACK_ON
    data = saved.to_json()
    assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert interp.rollback_state is ROLLBACK_OFF and interp.checkpoint().rollback is ROLLBACK_OFF
    del data["rollback"]                                            # a save from before F14
    assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert interp.rollback_state is ROLLBACK_ON
    interp.rollback_state = ROLLBACK_OFF
    interp.new_game(42)
    assert interp.rollback_state is ROLLBACK_ON


# --- 07 I-1 — a name reserved later never makes an older save unreadable --------------------------

def test_i1_saved_rollback_names_still_load(tmp_path, caplog):
    assert [reserved_since_save(n) for n in ("rollback", "Rollback", "ROLLBACK", "menu",
                                              "rollbacks", "points")] == [
        True, True, True, False, False, True]
    program = story_game(tmp_path / "var", ['hana "1"'])
    interp = at_line(program)
    for name in ("rollback", "Rollback"):
        data = interp.checkpoint().to_json()
        data["variables"].update({name: 3, "kept": 2})
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="vn"):
            assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
        assert dict(interp.checkpoint().variables) == {"kept": 2}
        (record,) = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert record.getMessage() == (f'Restored state: "{name}" is a reserved word in this '
                                       "version of the game, so the saved value was dropped.")
    # Saved stage names ``rollback`` load and resolve to nothing.
    program = story_game(tmp_path / "stage", ["scene bg river", "show hana happy", 'hana "1"'])
    interp = at_line(program)
    data = interp.checkpoint().to_json()
    sprite = data["stage"]["sprites"][0]
    data["stage"] = {"background": "rollback x",
                     "sprites": [{**sprite, "image": "hana rollback", "tag": "rollback",
                                  "at": "rollback"}]}
    state = GameState.from_json(data)
    assert interp.restore(state).result is RestoreResult.OK
    (stage,) = [c.stage for c in take_all(interp) if type(c) is ShowStage]
    assert stage.background == "rollback x" and stage.sprites[0].at == "rollback"
    # The image index never holds a ``rollback`` word, and no position can be named so: the
    # names draw as missing art, and the position falls back with W15.
    assert images.word_problem("rollback") == (images.STATEMENT_WORD, "my_rollback")


# --- 04 §6.3 — the executor -------------------------------------------------------------------------

def test_executor_rows(tmp_path):
    rows = [  # (lines before the line, enabled, block_pending)
        (["rollback block"], True, True),
        (["rollback off"], False, False),
        (["rollback off", "rollback off"], False, False),
        (["rollback on"], True, False),                              # already on: no wall
        (["rollback off", "rollback on"], True, True),               # from off: a wall
        (["rollback fixed", "menu:", '    "Go":', '        "Gone."'], True, False),
    ]
    for number, (lines, enabled, wall) in enumerate(rows):
        program = story_game(tmp_path / str(number), ['hana "0"', *lines, 'hana "1"'])
        interp = at_line(program)
        advance(interp)
        assert interp.status is Status.WAITING
        assert interp.rollback_state.enabled is enabled, lines
        # Step 2: the next checkpoint consumes the wall (record), which drops the past; with
        # rollback off every step is a wall.
        assert not interp.timeline.block_pending, lines
        assert len(interp.timeline.states) == (1 if wall or not enabled else 2), lines
        assert interp.steps == 0
