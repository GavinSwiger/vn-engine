"""F23 s2 — saves, loads, and rollback at a minigame (``06-acceptance.md`` AC-F23-14's runtime
rows, 15, 16, 17). Driver D on Template M (``tests/runtime/minigame_story.py``).

Host U rows (the used wheel in one frame, the ledger) and App M rows (F5, the game menu's
Load, Main Menu, Quit) are s4's."""

import json

from engine.runtime.commands import (AudioRestore, MinigameDone, MinigameUsed, NvlPage,
                                     PrefetchImages, Say, ShowStage, StartMinigame, StepBack,
                                     StepForward)
from engine.core.minigame_types import MeterChange
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.state import GameState
from engine.script.minigame import Minigame
from tests.runtime.minigame_story import (ALL, LINE_A, LINE_B, LINE_C, LINE_M, at_a, finish,
                                          load_m, said, start_of, step, to_line)
from tests.runtime.story import end_waits, fingerprint

HANA_UP = (MeterChange("hana", "+=", 1),)


def _view(interp):
    return interp.timeline.view(interp)


def _post(interp, event):
    interp.post(event)
    interp.run(10_000)
    end_waits(interp)
    return interp.take_commands(ALL)


def _rolls(commands):
    return [t for t in said(commands) if t.startswith("Roll ")]


# --- AC-F23-14 — A save during a minigame restarts it (runtime rows) ----------------------------

def test_ac_f23_14_a_save_during_a_minigame_restarts_it(tmp_path):
    program = load_m(tmp_path / "m", S="minigame probe pairs=count() into turns",
                     replace={3: "default found = None⏎define calls = []⏎"
                                 "define count = lambda: (calls.append(1), 6)[1]"})
    interp = at_a(program)
    to_line(interp, LINE_M + 2)
    assert interp.G["calls"] == [1]
    saved = interp.checkpoint().to_json()
    interp.post(MinigameUsed(interp.current.sid, interp.minigame_run))
    fresh = at_a(program)
    assert fresh.restore(GameState.from_json(saved)).result is RestoreResult.OK
    burst = fresh.take_commands(ALL)
    assert fresh.G["calls"] == []                            # count() isn't called again
    kinds = [type(c) for c in burst]
    assert kinds[:3] == [AudioRestore, NvlPage, ShowStage] and Say not in kinds
    assert kinds[3] is StartMinigame and set(kinds[4:]) <= {PrefetchImages}
    cmd = burst[3]
    assert cmd.restored and (cmd.name, dict(cmd.args)) == ("probe", {"pairs": 6, "hints": False,
                                                                    "label": ""})
    assert cmd.seed == saved["minigame"]["waiting"]["seed"]
    assert fresh.points.get("hana") == 0 and fresh.G["turns"] == 0
    assert fresh.minigame_used is False and fresh.status is Status.WAITING
    # Accepted but not yet run (a save made in the fade-out, 07 §2.2(d)): still k_M.
    interp.post(MinigameDone(interp.current.sid, interp.minigame_run, 9, HANA_UP))
    assert interp.checkpoint().to_json() == saved
    interp.run(10_000)
    after = interp.checkpoint().to_json()                    # at B: the outcome, no wait
    assert after["variables"]["turns"] == 9 and after["minigame"] == {"waiting": None}


# --- AC-F23-15 — One rollback step ----------------------------------------------------------------

def test_ac_f23_15_one_rollback_step(tmp_path):
    program = load_m(tmp_path / "m")

    def at_c():
        interp = at_a(program)
        to_line(interp, LINE_M)
        first = interp.checkpoint().minigame.waiting
        finish(interp, 9, HANA_UP)
        to_line(interp, LINE_C)
        return interp, first

    interp, _ = at_c()
    assert said(_post(interp, StepBack(1))) == ["After 9."]
    interp, first = at_c()
    landed = start_of(_post(interp, StepBack(2)))
    assert landed.restored and dict(landed.args) == dict(first.args)
    assert landed.seed == first.seed
    assert interp.G["turns"] == 0 and interp.points.get("hana") == 0
    assert _view(interp).ahead == 2
    commands = finish(interp, 9, HANA_UP)                    # the same outcome keeps the future
    assert said(commands) == ["After 9."] and _view(interp).ahead == 1
    interp, _ = at_c()
    _post(interp, StepBack(2))
    commands = finish(interp, 3)
    assert said(commands) == ["After 3."] and _view(interp).ahead == 0
    whole = at_a(program)
    rolled = to_line(whole, LINE_M)
    finish(whole, 9, HANA_UP)
    rolled = to_line(whole, LINE_C)
    after3 = to_line(interp, LINE_C)
    assert _rolls(after3) == _rolls(rolled)                  # C's r as on the first pass
    interp, _ = at_c()
    _post(interp, StepBack(3))
    assert interp.current.line == LINE_A
    assert start_of(_post(interp, StepForward(1))).restored
    interp, _ = at_c()
    _post(interp, StepBack(3))
    assert _view(interp).ahead == 3
    commands = _post(interp, StepForward(3))                 # the chain stops at M
    assert type(interp.current) is Minigame and start_of(commands).restored
    assert _view(interp).ahead == 2 and not said(commands)
    before, refused = fingerprint(interp), interp.timeline.refused
    _post(interp, StepForward(1))                            # forward at a minigame: nothing
    assert fingerprint(interp) == before and interp.timeline.refused == refused
    interp, _ = at_c()
    _post(interp, StepBack(3))
    step(interp)                                             # Advance at A: M presented live
    cmd = start_of(interp.take_commands(ALL))
    assert not cmd.restored and type(interp.current) is Minigame     # no outcome synthesized
    assert interp.status is Status.WAITING and interp.G["turns"] == 0


# --- AC-F23-16 — Back from inside a minigame --------------------------------------------------------

def test_ac_f23_16_back_from_inside_a_minigame(tmp_path):
    program = load_m(tmp_path / "m")

    def at_m():
        interp = at_a(program)
        to_line(interp, LINE_M)
        return interp

    interp = at_m()
    commands = _post(interp, StepBack(1))
    assert said(commands) == ["Before."] and [c.restored for c in commands
                                              if type(c) is Say] == [True]
    assert interp.points.get("hana") == 0 and interp.G["turns"] == 0
    interp = at_m()
    interp.post(MinigameUsed(interp.current.sid, interp.minigame_run))
    before, refused = fingerprint(interp), interp.timeline.refused
    _post(interp, StepBack(1))
    assert fingerprint(interp) == before and interp.timeline.refused == refused + 1
    assert _view(interp).can_back is False
    _post(interp, StepForward(1))                            # ignored too
    assert fingerprint(interp) == before
    interp = at_m()
    interp.post(MinigameUsed(interp.current.sid, interp.minigame_run - 1))   # stale
    assert interp.current.line == LINE_M
    assert said(_post(interp, StepBack(1))) == ["Before."]
    # Landed on M from C, no used input: back lands on A.
    interp = at_m()
    finish(interp, 9)
    to_line(interp, LINE_C)
    _post(interp, StepBack(2))
    assert interp.current.line == LINE_M
    assert said(_post(interp, StepBack(1))) == ["Before."]


# --- AC-F23-17 — rollback fixed above a minigame ------------------------------------------------------

def test_ac_f23_17_rollback_fixed_above_a_minigame(tmp_path):
    fixed = load_m(tmp_path / "f", S="rollback fixed⏎[4]minigame probe pairs=6 into turns")
    plain = load_m(tmp_path / "p")
    node = fixed.at("start", (2,))
    assert type(node) is Minigame and node.fixed
    assert node.sid == plain.at("start", (1,)).sid
    menu = load_m(tmp_path / "c", S='menu:⏎[8]"Play":⏎[12]rollback fixed⏎[12]'
                                    "minigame probe pairs=6 into turns")
    inner = menu.at("start", (1,)).choices[0].block[1]
    assert type(inner) is Minigame and inner.fixed
    m_line, b_line, c_line = LINE_M + 1, LINE_B + 1, LINE_C + 1
    interp = at_a(fixed)
    to_line(interp, m_line)
    assert said(_post(interp, StepBack(1))) == ["Before."]  # before the outcome: as usual
    interp = at_a(fixed)
    to_line(interp, m_line)
    finish(interp, 9, HANA_UP)
    assert interp.current.line == b_line and _view(interp).back_room == 0
    refused = interp.timeline.refused
    _post(interp, StepBack(1))
    assert interp.current.line == b_line and interp.timeline.refused == refused + 1
    to_line(interp, c_line)
    assert _view(interp).back_room == 1
    for _ in range(3):
        _post(interp, StepBack(1))
        assert interp.current.line == b_line
    assert interp.G["turns"] == 9 and interp.points.get("hana") == 1
