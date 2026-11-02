"""F21 step 2 — held items in ``GameState`` (``ItemsState``): AC-F21-15 (saves, TR-F21-01,
TR-F21-04) and AC-F21-16 (restore and New Game). The older saves are built here from this
build's state JSON with the ``items`` key removed (06 §5's ``saves/``)."""

import dataclasses
import json
import logging

import pytest

from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import EMPTY_ITEMS, GameState, ItemsState, StateInvalid
from tests.runtime.codex_story import load_c, started, step, to_text
from tests.runtime.story import fingerprint

ZZ = "ZZMARK"


def test_ac15_items_in_saves(tmp_path):
    program = load_c(tmp_path / "c", S="unlock item red_lantern⏎[4]unlock item brass_key")
    interp = started(program)
    start = interp.checkpoint()
    assert start.items is EMPTY_ITEMS
    data = start.to_json()
    assert data["items"] == {"held": []} and data["format"] == 1      # always written
    to_text(interp, "Before.")
    state = interp.checkpoint()
    assert state.items.held == ("red_lantern", "brass_key")
    text = json.dumps(state.to_json(), ensure_ascii=True)
    assert GameState.from_json(json.loads(text)) == state                # TR-F21-01
    older = start.to_json()
    del older["items"]
    assert GameState.from_json(older).items is EMPTY_ITEMS
    full = [f"n{i:04}" for i in range(1000)]
    assert GameState.from_json({**data, "items": {"held": full}}).items.held == tuple(full)
    before = fingerprint(interp)
    for value in ([], None, ZZ, {}, {"held": [], ZZ: 1}, {"held": ZZ}, {"held": [1]},
                  {"held": [""]}, {"held": [ZZ + "a" * 59]}, {"held": ["ZZ MARK"]},
                  {"held": [ZZ, ZZ]}, {"held": [f"{ZZ}{i}" for i in range(1001)]}):
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**data, "items": value})
        assert caught.value.reason == "items" and ZZ not in str(caught.value), value
    assert fingerprint(interp) == before
    # TR-F21-04: two checkpoints with no give/take between them share one ItemsState.
    interp = started(load_c(tmp_path / "d", S='unlock item brass_key⏎[4]"Mid."'))
    to_text(interp, "Mid.")
    mid = interp.checkpoint()
    step(interp)
    assert interp.checkpoint().items is mid.items and mid.items.held == ("brass_key",)


def _restored(interp, held: tuple[str, ...]):
    state = dataclasses.replace(interp.checkpoint(), items=ItemsState(held))
    assert interp.restore(state).result is RestoreResult.OK
    return interp.G["codex"].items, interp.codex.state().held


def test_ac16_restore_and_new_game(tmp_path, caplog):
    program = load_c(tmp_path / "c")
    interp = started(program)
    assert _restored(interp, ("red_lantern", "brass_key")) == (
        ["red_lantern", "brass_key"], ("red_lantern", "brass_key"))
    assert _restored(interp, ("gone", "brass_key")) == (["brass_key"], ("gone", "brass_key"))
    to_text(interp, "Before.")
    assert interp.checkpoint().items.held == ("gone", "brass_key")      # the next save
    interp = started(program)
    assert _restored(interp, ("lanterns",)) == ([], ("lanterns",))
    assert not interp.persistent.is_unlocked("tip", "lanterns")
    hidden = tuple(f"h{i:04}" for i in range(1000))
    assert _restored(interp, hidden) == ([], hidden[2:])                 # 1,000 − 2 items
    # Pre-F21 saves: no items key; one holding a variable "codex".
    old = interp.checkpoint().to_json()
    del old["items"]
    interp = started(program)
    interp.codex.give("brass_key")
    assert interp.restore(GameState.from_json(old)).result is RestoreResult.OK
    assert interp.G["codex"].items == [] and interp.codex.state().held == ()
    old["variables"]["codex"] = 1
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert interp.restore(GameState.from_json(old)).result is RestoreResult.OK
    assert any('"codex" is a name the engine uses' in r.getMessage() for r in caplog.records)
    assert interp.G["codex"].items == [] and "codex" not in interp.checkpoint().variables
    # A restore that fails at step 5 leaves the held items as they were.
    # (The default sees the restored items: 1 / 0 with one item held.)
    failing = load_c(tmp_path / "f", T="default boom = 1 / (1 - len(codex.items))")
    interp = started(failing)
    state = dataclasses.replace(interp.checkpoint(), items=ItemsState(("red_lantern",)),
                                variables={})               # boom is filled at step 5
    interp.codex.give("brass_key")
    assert interp.restore(state).result is RestoreResult.DEFAULT_FAILED
    assert interp.G["codex"].items == ["brass_key"]
    # New Game empties the items before the first default.
    interp = started(load_c(tmp_path / "n", T='default had = "brass_key" in codex.items'))
    interp.codex.give("brass_key")
    interp.new_game(42)
    interp.run(10_000)
    assert interp.G["had"] is False and interp.G["codex"].items == []
    # With 1,000 hidden names held, give drops the oldest hidden one.
    interp.codex.install(hidden)
    assert interp.codex.give("red_lantern")
    assert interp.codex.state().held == hidden[1:] + ("red_lantern",)
