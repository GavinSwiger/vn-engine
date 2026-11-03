"""F32 s3 — ``GameState.ui`` as saved state (F32 ``06-acceptance.md`` AC-F32-08; ``04`` §3,
§7 item 3, §9; TR-F32-01). States are real ``walk/`` checkpoints (``ui_story.py``)."""

import json
from dataclasses import replace

import pytest

from engine.runtime.commands import Advance
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import STATE_FORMAT, GameState, StateInvalid
from engine.runtime.ui import EMPTY_UI, UiState
from tests.runtime.effects_story import take_all
from tests.runtime.ui_story import R, launched, walk

KEYS = ("ui_style", "save_block", "load_block")


def _back(data: dict) -> GameState:
    return GameState.from_json(json.loads(json.dumps(data, ensure_ascii=True)))


def _u1() -> GameState:
    interp = launched(walk())
    interp.new_game(42)
    interp.run(10_000)
    return interp.checkpoint()


def _refused(data: dict) -> str:
    with pytest.raises(StateInvalid) as refused:
        _back(data)
    assert "ZZMARK" not in str(refused.value)
    return refused.value.reason


def test_ac_f32_08_game_state_ui_round_trips_and_refuses_hostile_values():
    assert STATE_FORMAT == 1
    u1 = _u1()
    base = u1.to_json()
    assert u1.ui is EMPTY_UI and not set(KEYS) & base.keys() and _back(base) == u1
    rows = [
        (UiState(style="ashes"), {"ui_style": "ashes"}),
        (UiState(save_block=True), {"save_block": True}),
        (UiState(save_block=True, save_reason="R"), {"save_block": "R"}),
        (UiState(load_block=True), {"load_block": True}),
        (UiState(load_block=True, load_reason="R"), {"load_block": "R"}),
        (UiState("ashes", True, R, True, None),
         {"ui_style": "ashes", "save_block": R, "load_block": True}),
    ]
    for ui, keys in rows:
        state = replace(u1, ui=ui)
        data = state.to_json()
        assert {k: data[k] for k in KEYS if k in data} == keys
        assert _back(data) == state and state.save_problem() is None

    # Hostile values: refused with the key's name only, never echoed.
    for bad in (5, "", "Ashes", "../x", "a" * 33, "ZZMARK x", None):
        assert _refused({**base, "ui_style": bad}) == "ui_style"
    for key in ("save_block", "load_block"):
        for bad in (False, 0, None, [], {}, 1):
            assert _refused({**base, key: bad}) == key
    # A reason the parser would refuse is the game's own words; tags are kept as written.
    for reason in ("", "é" * 201):
        ui = _back({**base, "save_block": reason, "load_block": reason}).ui
        assert ui == UiState(save_block=True, load_block=True)
    assert _back({**base, "save_block": "{b}x"}).ui.save_reason == "{b}x"
    # A hand-built style from_json would refuse is a save problem.
    assert replace(u1, ui=UiState(style="Ashes")).save_problem() == "ui_style"

    # A pre-F32 save holding a variable named ui: it loads, and restore drops the name.
    old = _back({**base, "variables": {**base["variables"], "ui": 1, "kept": 2}})
    assert old.ui is EMPTY_UI and old.variables["ui"] == 1
    interp = launched(walk())
    assert interp.restore(old).result is RestoreResult.OK
    take_all(interp)
    assert "ui" not in interp.G and interp.G["kept"] == 2
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert "ui" not in interp.checkpoint().variables
