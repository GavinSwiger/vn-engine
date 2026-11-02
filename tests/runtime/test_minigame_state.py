"""F23 s2 — the saved field (``06-acceptance.md`` AC-F23-13) and group E: the saved minigame
is hostile until checked (AC-F23-50; rows of ``fuzz_state.MINIGAME_ROWS``).

App M rows of AC-F23-50 (F11's damaged-save notice, the nearest-point confirm) are s4's."""

import copy
import json
import logging
import sys
from types import MappingProxyType

import pytest

from engine.core.minigame_types import REQUIRED, ArgSpec, MinigameSig
from engine.runtime import state as state_mod
from engine.runtime import values
from engine.runtime.commands import StartMinigame, StepBack
from engine.runtime.interpreter import RestoreResult
from engine.runtime.minigame import EMPTY_MINIGAME, MinigameState, MinigameWait
from engine.runtime.state import GameState, StateInvalid
from tests.fixtures.F23.sigs import SIGS
from tests.runtime import corpus, fuzz_state
from tests.runtime.minigame_story import ALL, LINE_B, LINE_M, at_a, finish, load_m, to_line
from tests.runtime.story import fingerprint, launched, load_fixture


def _round(state: GameState) -> GameState:
    return GameState.from_json(json.loads(json.dumps(state.to_json(), ensure_ascii=True)))


# --- AC-F23-13 — The saved field --------------------------------------------------------------

def test_ac_f23_13_the_saved_field(tmp_path, monkeypatch):
    program = load_m(tmp_path / "m")
    interp = at_a(program)
    k_a = interp.checkpoint()
    for seed in (2**64 - 1, 0):
        wait = MinigameWait("probe", MappingProxyType(
            {"pairs": 6, "words": ["a", {"b": [1, None]}]}), seed)
        state = GameState(position=k_a.position, position_at=k_a.position_at, call_stack=(),
                          variables=dict(k_a.variables), dice=k_a.dice,
                          minigame=MinigameState(wait))
        assert _round(state) == state and _round(state).minigame.waiting.seed == seed
        assert state.save_problem() is None
    data = k_a.to_json()
    assert data["minigame"] == {"waiting": None} and data["format"] == 1
    to_line(interp, LINE_M)
    assert interp.checkpoint().to_json()["minigame"]["waiting"]["name"] == "probe"
    # The key absent: F03's committed v1 saves (pre-F23), and a state with the key dropped.
    for saved in json.loads(corpus.GOLDENS.joinpath("patch_v1_saves.json").read_text("ascii")):
        assert "minigame" not in saved
        old = GameState.from_json(saved)
        assert old.minigame is EMPTY_MINIGAME
        v2 = launched(load_fixture(tmp_path / f"v2-{len(saved)}-{id(saved)}", "patch/v2"))
        assert v2.restore(old).result is RestoreResult.OK
    older = k_a.to_json()
    del older["minigame"]
    assert GameState.from_json(older).minigame is EMPTY_MINIGAME
    assert at_a(program).restore(GameState.from_json(older)).result is RestoreResult.OK
    # save_problem counts the args' members in the total (limit patched to 10 members).
    monkeypatch.setattr(state_mod, "STATE_MAX_ITEMS", 10)
    monkeypatch.setattr(values, "STATE_MAX_ITEMS", 10)
    base = dict(k_a.variables, big=list(range(8)))

    def with_args(n: int) -> GameState:
        wait = MinigameWait("probe", MappingProxyType({"pairs": list(range(n))}), 1)
        return GameState(position=k_a.position, position_at=k_a.position_at, call_stack=(),
                         variables=base, dice=k_a.dice, minigame=MinigameState(wait))

    assert with_args(2).save_problem() is None
    assert with_args(3).save_problem() == "too_many_items"     # one over, held only in args
    assert GameState.from_json(with_args(2).to_json()) == with_args(2)
    with pytest.raises(StateInvalid):
        GameState.from_json(with_args(3).to_json())


# --- AC-F23-50 — Group E ------------------------------------------------------------------------

class _Check:
    """A plugin check whose answer each row sets."""

    def __init__(self) -> None:
        self.answer: object = None
        self.calls = 0

    def __call__(self, args: dict, story: object) -> object:
        self.calls += 1
        answer = self.answer
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer()
        return answer


class _Guard:
    def __init__(self) -> None:
        self.entries = 0

    def enter(self) -> None:
        self.entries += 1

    def exit(self) -> None:
        pass

    def consume_fired(self) -> bool:
        return False


def _hostile_rows(names: list[str]) -> None:
    base = GameState(position="start/0123456789ab", position_at=("start", (0,)),
                     call_stack=(), variables={}, dice=1).to_json()
    for name in names:
        data = copy.deepcopy(base)
        data["minigame"] = fuzz_state.minigame_row(name)
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json(data)
        assert caught.value.reason == "minigame", name
        assert "ZZMARK" not in str(caught.value) and "Lantern" not in str(caught.value)


def test_ac_f23_50_the_saved_minigame_is_hostile_until_checked(tmp_path, caplog):
    assert [fuzz_state.MINIGAME_ROWS[n][0] for n in fuzz_state.minigame_rows(
        everything=False)] == list(fuzz_state.MINIGAME_KINDS)
    _hostile_rows(fuzz_state.minigame_rows(everything=False))
    check = _Check()
    checked = MinigameSig(name="checked", title="checked", source="minigames/checked.py",
                          args=(ArgSpec("pairs", REQUIRED), ArgSpec("hints", False)),
                          test=None, skipped=None, check=check)
    sigs = MappingProxyType({**SIGS, "checked": checked})
    program = load_m(tmp_path / "m", S="minigame checked pairs=6 into turns", sigs=sigs)
    live = at_a(program, sigs=sigs)
    to_line(live, LINE_M)
    k_m = live.checkpoint().to_json()
    k_a_json = at_a(program, sigs=sigs).checkpoint().to_json()

    def restore(data: dict, *, check_only: bool = False):
        interp = at_a(program, sigs=sigs)
        before = fingerprint(interp)
        modules = set(sys.modules)
        state = GameState.from_json(data)
        outcome = interp.restore(state, check_only=True)
        assert fingerprint(interp) == before                  # check_only changes nothing
        if not check_only:
            outcome = interp.restore(state)
        assert set(sys.modules) == modules                    # no module loaded
        if outcome.result is not RestoreResult.OK:
            assert fingerprint(interp) == before
        return interp, outcome.result

    def edited(fn) -> dict:
        data = copy.deepcopy(k_m)
        fn(data["minigame"]["waiting"])
        return data

    not_found = RestoreResult.POSITION_NOT_FOUND
    for fn in (lambda w: w.update(name="zzz_gone"), lambda w: w.update(name="probe"),
               lambda w: w["args"].update(colour=1), lambda w: w["args"].pop("pairs")):
        interp, result = restore(edited(fn))
        assert result is not_found
        assert not any(type(c) is StartMinigame for c in interp.take_commands(ALL))
    # An optional argument the save lacks (the plugin gained it): the current default.
    interp, result = restore(edited(lambda w: w["args"].pop("hints")))
    assert result is RestoreResult.OK
    cmd = next(c for c in interp.take_commands(ALL) if type(c) is StartMinigame)
    assert dict(cmd.args) == {"pairs": 6, "hints": False} and cmd.restored
    # The plugin's check refuses, raises, returns 5: POSITION_NOT_FOUND, never fatal.
    for answer in ("no more than 12.", ZeroDivisionError("x"), 5):
        check.answer = answer
        assert restore(k_m)[1] is not_found, answer
    check.answer = KeyboardInterrupt()                       # the watchdog firing

    class Fired(_Guard):
        def consume_fired(self) -> bool:
            return True

    stuck = at_a(program, sigs=sigs, guard=Fired())
    assert stuck.restore(GameState.from_json(k_m)).result is not_found
    check.answer = None
    # One guard entry for a check_only and the full restore of the same state object (I-6).
    guard = _Guard()
    interp = at_a(program, sigs=sigs, guard=guard)
    state = GameState.from_json(k_m)
    entries = guard.entries
    assert interp.restore(state, check_only=True).result is RestoreResult.OK
    assert interp.restore(state).result is RestoreResult.OK
    assert guard.entries == entries + 1
    # waiting set at a Say position: never presented, committed null; null at M: not found.
    data = copy.deepcopy(k_a_json)
    data["minigame"] = copy.deepcopy(k_m["minigame"])
    interp, result = restore(data)
    assert result is RestoreResult.OK and interp.minigame_wait is None
    assert interp.checkpoint().minigame.waiting is None
    assert not any(type(c) is StartMinigame for c in interp.take_commands(ALL))
    data = copy.deepcopy(k_m)
    data["minigame"]["waiting"] = None
    assert restore(data)[1] is not_found
    # A landing whose check now refuses: F14's W90 drop, the player stays on B.
    to_line(live, LINE_M)
    finish(live, 1)
    assert live.current.line == LINE_B
    check.answer = "not any more."
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        live.post(StepBack(1))
    assert live.current.line == LINE_B and live.status.value == "waiting"
    assert any(getattr(r, "code", None) == "W90" for r in caplog.records)
    check.answer = None


@pytest.mark.slow
def test_ac_f23_50_every_row_and_the_member_total():
    _hostile_rows(fuzz_state.minigame_rows(everything=True))
    base = GameState(position="start/0123456789ab", position_at=("start", (0,)),
                     call_stack=(), variables={}, dice=1).to_json()
    base["minigame"] = {"waiting": {"name": "probe", "args": {"pairs": [0] * 2_000_001},
                                    "seed": 1}}
    with pytest.raises(StateInvalid):
        GameState.from_json(base)
