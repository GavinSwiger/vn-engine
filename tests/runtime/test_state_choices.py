"""F07 step 3 — ``GameState.choices`` saved (``04-technical.md`` §4, §8 items 3–4, §10;
``06-acceptance.md`` §1.3): AC-F07-15 (the JSON round-trips; old saves load) and AC-F07-16
(hostile ``choices`` is ``StateInvalid`` only), with ``fuzz_state.py``'s F07 rows.

``tests/fixtures/F07/saves/`` holds this build's Bm (Run M ``a``), the line-15 state of Run M
``a c2``, and ``pre_f07.json`` (the line-5 state as a build before F07 wrote it: no
``choices`` key). Regenerate only on a ``STATE_FORMAT`` change:
``python -m tests.runtime.test_state_choices``.
"""

import copy
import dataclasses
import json
import logging
import re
import time
from pathlib import Path

import pytest

from engine.runtime.commands import Say, ShowMenu
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.menu import EMPTY_CHOICES, ChoiceState, MenuWait, Pick
from engine.runtime.state import STATE_FORMAT, GameState, StateInvalid
from engine.script import words
from tests.runtime import fuzz_state
from tests.runtime.conftest import round_trip
from tests.runtime.menu_story import (ALL, F07, K, launched, load_m, play, sid_at)

SAVES = F07 / "saves"
CROSS = ("The red one", "The paper crane (2 coins)", "Not this year")
QUESTION = "Will you buy a lantern?"
REASON = re.compile(r"^[a-z_]{1,40}$")


def bm_state(program) -> GameState:
    interp, _ = play(program, "a")
    return interp.checkpoint()


def line15_state(program) -> GameState:
    interp, _ = play(program, "a c2", to_end=False)
    assert interp.current.line == 15
    return interp.checkpoint()


# Keys added after F07 (one per later feature): the committed saves are as F07's build wrote
# them, so they are also saves from before each of these features.
LATER_KEYS = ("history", "chapter", "points", "rollback", "nvl",   # F13, F18, F22, F14, F17
              "items", "minigame", "flow", "glitch")              # F21, F23, F20, F28


def written_by_f07(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in LATER_KEYS}


def saves(root: Path) -> dict[str, dict]:
    """The three committed saves, as this build writes them without ``LATER_KEYS``."""
    program = load_m(root)
    interp, _ = play(program, "", to_end=False)
    assert interp.current.line == 5
    pre = interp.checkpoint().to_json()
    del pre["choices"]
    return {"bm.json": written_by_f07(bm_state(program).to_json()),
            "line15.json": written_by_f07(line15_state(program).to_json()),
            "pre_f07.json": written_by_f07(pre)}


def read_save(name: str) -> dict:
    return json.loads((SAVES / name).read_text(encoding="ascii"))


def combined_choices() -> dict:
    """A ``choices`` object with one pick and a waiting menu (line 15's pick, Bm's wait)."""
    return {"picks": read_save("line15.json")["choices"]["picks"],
            "waiting": read_save("bm.json")["choices"]["waiting"]}


# --- AC-F07-15 — the choice state round-trips; old saves load ----------------------------------

def test_ac15_the_json_at_the_menu_and_after_a_pick(tmp_path):
    program = load_m(tmp_path)
    assert bm_state(program).to_json()["choices"] == {
        "picks": [],
        "waiting": {"pickable": [K(t) for t in CROSS], "locked": [], "kept": None}}
    assert line15_state(program).to_json()["choices"] == {
        "picks": [{"menu": sid_at(program, 6), "choice": K(CROSS[1]), "text": CROSS[1],
                   "question": QUESTION}],
        "waiting": None}


def test_ac15_round_trips(tmp_path):
    program = load_m(tmp_path)
    bm, line15 = bm_state(program), line15_state(program)
    menu = sid_at(program, 6)
    question_less = dataclasses.replace(line15, choices=ChoiceState(
        (Pick(menu, K(CROSS[0]), CROSS[0], None),), None))
    locked = dataclasses.replace(bm, choices=ChoiceState(
        line15.choices.picks,
        MenuWait((K(CROSS[0]), K(CROSS[2])), (K(CROSS[1]),), sid_at(program, 5))))
    for state in (bm, line15, question_less, locked):
        data = state.to_json()
        assert data["format"] == STATE_FORMAT == 1
        assert GameState.from_json(data) == state
        assert round_trip(state) == state
        assert state.save_problem() is None
    assert question_less.to_json()["choices"]["picks"][0]["question"] is None
    assert locked.to_json()["choices"]["waiting"] == {
        "pickable": [K(CROSS[0]), K(CROSS[2])], "locked": [K(CROSS[1])],
        "kept": sid_at(program, 5)}


def test_ac15_the_committed_saves_are_this_builds(tmp_path):
    for name, data in saves(tmp_path).items():
        assert read_save(name) == data, name


def test_ac15_a_save_from_before_f07_loads_and_restores(tmp_path):
    data = read_save("pre_f07.json")
    assert "choices" not in data and data["format"] == 1
    state = GameState.from_json(data)
    assert state.choices is EMPTY_CHOICES
    program = load_m(tmp_path)
    interp = launched(program)
    assert interp.restore(state).result is RestoreResult.OK
    burst = interp.take_commands(ALL)
    say = next(c for c in burst if type(c) is Say)
    assert say.sid == sid_at(program, 5) and say.restored
    assert interp.choices is EMPTY_CHOICES and interp.kept_line == sid_at(program, 5)
    assert interp.checkpoint().to_json()["choices"] == {"picks": [], "waiting": None}


def test_ac15_older_saves_of_earlier_features_load_with_no_picks():
    data = json.loads((F07.parent / "F04" / "saves" / "pre_f04.json").read_text("utf-8"))
    assert not {"stage", "audio", "choices"} & data.keys()
    assert GameState.from_json(data).choices is EMPTY_CHOICES


def test_a_name_reserved_later_never_makes_an_old_save_unreadable(monkeypatch):
    """docs/architecture.md "Names reserved later and older saves" (F22 I-9, F14 I-1):
    ``from_json`` refuses only F03's six engine names, never the live set."""
    data = read_save("bm.json")
    data["variables"]["points"] = 3
    monkeypatch.setattr(words, "ENGINE_NAMES", words.ENGINE_NAMES | {"points"})
    assert GameState.from_json(data).variables["points"] == 3
    for name in ("Character", "dice", "module", "persistent", "engine", "narrator"):
        bad = read_save("bm.json")
        bad["variables"][name] = 1
        with pytest.raises(StateInvalid):
            GameState.from_json(bad)


def test_save_problem_of_choices(tmp_path):
    state = GameState.from_json(read_save("line15.json"))
    pick = state.choices.picks[0]
    pair = dataclasses.replace(pick, text="a" + chr(0xD800) + chr(0xDC00) + "b")
    assert dataclasses.replace(state, choices=ChoiceState((pair,), None)).save_problem() \
        == "lone_surrogate"
    lone = dataclasses.replace(pick, question="a" + chr(0xD800) + "b")
    assert dataclasses.replace(state, choices=ChoiceState((lone,), None)).save_problem() \
        is None
    for bad in (dataclasses.replace(pick, menu="ZZMARK"),
                dataclasses.replace(pick, text="t" * 1_001),
                dataclasses.replace(pick, choice=5)):
        assert dataclasses.replace(state, choices=ChoiceState((bad,), None)).save_problem() \
            == "choices"


# --- AC-F07-16 — hostile choice state is rejected ---------------------------------------------

def check_rejected(name: str, caplog) -> None:
    data = read_save("bm.json")
    data["choices"] = fuzz_state.choice_row(name, combined_choices())
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json(data)
    assert type(caught.value) is StateInvalid and caught.value.reason == "choices"
    assert "ZZMARK" not in str(caught.value) and "ZZMARK" not in repr(caught.value)
    assert not any("ZZMARK" in r.getMessage() for r in caplog.records)


def test_ac16_the_base_is_accepted():
    data = read_save("bm.json")
    data["choices"] = combined_choices()
    assert GameState.from_json(data).choices.waiting is not None


def test_ac16_rows(caplog):
    """One default row per kind, in one loop (the rows are cheap; test-review-F07.md)."""
    for name in fuzz_state.choice_rows(everything=False):
        try:
            check_rejected(name, caplog)
        except (AssertionError, pytest.fail.Exception) as error:
            raise AssertionError(f"row {name!r}") from error


@pytest.mark.slow
@pytest.mark.parametrize("name", [n for n in fuzz_state.choice_rows(everything=True)
                                  if n not in fuzz_state.choice_rows(everything=False)])
def test_ac16_rows_slow(name, caplog):
    check_rejected(name, caplog)


def test_ac16_every_kind_has_a_default_row():
    names = fuzz_state.choice_rows(everything=False)
    assert [fuzz_state.CHOICE_ROWS[n][0] for n in names] == list(fuzz_state.CHOICE_KINDS)


def run_choice_fuzz(count: int, seed: int, inflate: bool = False) -> int:
    """Mutated ``choices`` values in Bm: ``StateInvalid`` (no input in its text) or a state
    that round-trips."""
    base = read_save("bm.json")
    bases = [combined_choices(), base["choices"], read_save("line15.json")["choices"]]
    accepted = 0
    for choices in fuzz_state.mutations(bases, count, seed, inflate):
        data = dict(copy.deepcopy(base), choices=choices)
        try:
            state = GameState.from_json(data)
        except StateInvalid as error:
            assert REASON.match(error.reason) and "ZZMARK" not in str(error)
            continue
        accepted += 1
        assert round_trip(state) == state
    return accepted


def test_ac16_fuzz_ci():
    accepted = run_choice_fuzz(300, seed=716)
    assert 0 < accepted < 300


@pytest.mark.slow
def test_ac16_fuzz_full():
    began = time.perf_counter()
    run_choice_fuzz(10_000, seed=71_600, inflate=True)
    assert time.perf_counter() - began < 600


def test_a_menu_state_restores_from_its_json(tmp_path):
    """Step 1's gap: a saved state at a menu restores (it was POSITION_NOT_FOUND while
    ``choices`` was in memory only)."""
    program = load_m(tmp_path)
    interp = launched(program)
    assert interp.restore(GameState.from_json(read_save("bm.json"))).result \
        is RestoreResult.OK
    assert interp.status is Status.WAITING
    assert type(interp.take_commands(ALL)[-1]) is ShowMenu


if __name__ == "__main__":                       # write tests/fixtures/F07/saves/ once
    import tempfile
    SAVES.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for file, document in saves(Path(tmp) / "game").items():
            (SAVES / file).write_text(json.dumps(document, ensure_ascii=True, indent=1) + "\n",
                                      encoding="ascii", newline="\n")
