"""F39 P2 — ``Timeline.carry`` (``specs/F39-hot-reload/SPEC.md`` PR-F39-08, §5.1 step 5):
AC-F39-08. Run K's earlier steps are carried into a fresh interpreter that resumed at a later
step, as a hot-reload child does."""

import dataclasses
import logging
from pathlib import Path

from engine.app.story import RuntimeStoryDriver
from engine.runtime.interpreter import Interpreter, RestoreResult
from engine.runtime.rollback import ROLLBACK_OFF
from engine.script.messages import format_message
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import load_game, take_all
from tests.runtime.rollback_story import F14, back, fixture, launched, run_k, shown_text


def _resumed(program, at, older, *, depth: int = 100) -> Interpreter:
    """A fresh child of ``program`` that resumed at ``at`` (a committing restore) and
    carried ``older`` (newest first)."""
    interp = launched(program, rollback_steps=depth)
    driver = RuntimeStoryDriver(interp)
    assert driver.restore(at, fresh_menu=True).result is RestoreResult.OK
    interp.run(10_000)
    take_all(interp)
    interp.timeline.carry(older)
    return interp


def _gone_line(root: Path):
    """Run K's script with the line "Wade one." removed."""
    text = (F14 / "steps" / "script" / "main.vns").read_text(encoding="utf-8")
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(
        text.replace('            "Wade one."\n', "", 1), encoding="utf-8")
    return load_game(root)


def test_ac_f39_08_carry(tmp_path, caplog):
    _, k = run_k("S")
    order = ["D2", "D1", "M", "C", "B", "A"]                   # newest first, as carried
    older = [round_trip(k[name]) for name in order]

    # Back lands on the carried steps in order.
    interp = _resumed(fixture("steps"), round_trip(k["S"]), older)
    t = interp.timeline
    assert t.cursor == 6 and len(t.states) == 7 and t.states[:6] == older[::-1]
    landed = []
    for _ in order:
        back(interp)
        landed.append(interp.checkpoint().position)
    assert landed == [k[name].position for name in order]
    assert t.view(interp).back_room == 0

    # A gone line stays carried; Back stops there with W90 and drops it and older steps.
    interp = _resumed(_gone_line(tmp_path), round_trip(k["S"]),
                      [round_trip(k[name]) for name in order])
    t = interp.timeline
    assert len(t.states) == 7                                   # carried, gone line included
    back(interp)
    assert shown_text(interp) == "Wade two."
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert back(interp) == []                              # D1's line is gone
    assert shown_text(interp) == "Wade two."
    assert len(t.states) == 2 and t.cursor == 0                 # D1, M, C, B, A dropped
    assert t.view(interp).back_room == 0
    w90 = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W90"]
    assert w90 == [format_message("W90", ("start", "position"))]

    # Rollback off at the resumed step, or depth 0: nothing is carried.
    off = dataclasses.replace(round_trip(k["S"]), rollback=ROLLBACK_OFF)
    interp = _resumed(fixture("steps"), off, older)
    assert len(interp.timeline.states) == 1 and interp.timeline.cursor == 0
    interp = _resumed(fixture("steps"), round_trip(k["S"]), older, depth=0)
    assert interp.timeline.states == [] and interp.timeline.carry(older) == 0

    # Trimmed to depth: only the newest carried steps fit before the current one.
    interp = _resumed(fixture("steps"), round_trip(k["S"]), older, depth=3)
    t = interp.timeline
    assert len(t.states) == 4 and t.cursor == 3
    assert t.states[:3] == [older[2], older[1], older[0]]      # M, D1, D2
