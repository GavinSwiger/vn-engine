"""F07 step 3 — restore at a menu (``04-technical.md`` §7.5, §10; ``06-acceptance.md`` §1.3):
AC-F07-17 (the restore burst; conditions not evaluated), 18 (restore after a script edit),
19 (rollback offers the menu again and undoes the pick), and the restore half of the
``choices`` fuzz (every result but OK leaves the fingerprint unchanged).

The restored voice (F08 step 7's presentation half) isn't built: the runtime half,
``PlayVoice(…, restored=True)`` before the question, is asserted here.
"""

import json
import time

import pytest

from engine.runtime.commands import (AudioRestore, Choose, NvlPage, PlayVoice, PrefetchImages,
                                     Say, ShowMenu, ShowStage)
from engine.runtime.interpreter import Interpreter, RestoreOutcome, RestoreResult, Status
from engine.runtime.menu import Pick
from engine.runtime.state import GameState, StateInvalid
from engine.script.menu import Menu
from tests.runtime import fuzz_state
from tests.runtime.menu_story import (ALL, F07, K, go, launched, lines, load_m, menus, play,
                                      shown, sid_at)
from tests.runtime.story import fingerprint

OK = RestoreResult.OK
NOT_FOUND = RestoreResult.POSITION_NOT_FOUND
CROSS = ("The red one", "The paper crane (2 coins)", "Not this year")
QUESTION = "Will you buy a lantern?"
MENU = ('menu:⏎[8]hana "Will you buy a lantern?"⏎[8]"The red one":⏎[12]$ lantern = "red"⏎'
        '[8]"The paper crane (2 coins)" if coins >= 2:⏎[12]$ coins -= 2⏎'
        '[12]$ lantern = "crane"⏎[8]"Not this year":⏎[12]jump walk_home')
GO = 'menu:⏎[8]"Go":⏎[12]$ pass'


def read_save(name: str) -> dict:
    return json.loads((F07 / "saves" / name).read_text(encoding="ascii"))


def bm() -> GameState:
    return GameState.from_json(read_save("bm.json"))


def at_menu(program, text: str = "a", **kwargs) -> GameState:
    interp, commands = play(program, text, **kwargs)
    assert type(interp.current) is Menu
    return interp.checkpoint()


def restored(program, state: GameState) -> tuple[Interpreter, list]:
    """A fresh interpreter restored to ``state``, and its burst."""
    interp = launched(program)
    outcome = interp.restore(state)
    assert outcome.result is OK, outcome
    return interp, interp.take_commands(ALL)


def kinds(burst) -> list[type]:
    return [type(c) for c in burst if type(c) is not PrefetchImages]


# --- AC-F07-17 — restore at a menu ---------------------------------------------------------------------

def test_ac17_the_restore_burst(tmp_path, monkeypatch):
    program = load_m(tmp_path)
    _, live = play(program, "a")
    (live_menu,) = menus(live)
    calls = []
    real = Interpreter._test
    monkeypatch.setattr(Interpreter, "_test",
                        lambda self, code: calls.append(code) or real(self, code))
    interp, burst = restored(program, bm())
    assert calls == []                                       # no condition evaluated
    assert kinds(burst) == [AudioRestore, NvlPage, ShowStage, Say, ShowMenu]   # F17 I-3
    say, menu = burst[3], burst[4]
    assert say.sid == sid_at(program, 6) and say.restored and say.name == "Hana"
    assert lines([say]) == [QUESTION] and say.voice is None
    assert menu.restored and menu.line == "question" and menu.sid == sid_at(program, 6)
    assert menu.choices == live_menu.choices
    assert interp.menu_open == (menu, QUESTION) and interp.kept_line == sid_at(program, 6)
    assert interp.status is Status.WAITING and interp.checkpoint() == bm()
    go(interp, "c2")                                         # line 11 runs
    assert interp.G["coins"] == 0 and interp.G["lantern"] == "crane"
    assert interp.choices.picks == (
        Pick(sid_at(program, 6), K(CROSS[1]), CROSS[1], QUESTION),)


def test_ac17_the_saved_choices_are_shown_whatever_the_values_now(tmp_path):
    program = load_m(tmp_path)
    data = read_save("bm.json")
    data["variables"]["coins"] = 0
    interp, burst = restored(program, GameState.from_json(data))
    assert [key for key, _, _ in shown(menus(burst)[0])] == [K(t) for t in CROSS]
    go(interp, "c2")
    assert interp.G["coins"] == -2 and interp.G["lantern"] == "crane"


def test_ac17_a_voiced_question(tmp_path):
    program = load_m(tmp_path, M='menu:⏎[8]voice "v/q.ogg"⏎[8]hana "Will you buy a lantern?"⏎'
                                 '[8]"The red one":⏎[12]$ lantern = "red"')
    _, burst = restored(program, at_menu(program))
    sid = sid_at(program, 6)
    assert kinds(burst) == [AudioRestore, NvlPage, ShowStage, PlayVoice, Say, ShowMenu]
    assert burst[3] == PlayVoice(sid, "v/q.ogg", True)
    assert burst[4].sid == sid and burst[4].restored


def test_ac17_a_question_less_menu_keeps_the_line_before_it_never_voiced(tmp_path):
    program = load_m(tmp_path, S='voice "v/b.ogg"⏎"Before."', M=GO)
    before = sid_at(program, 6)
    _, burst = restored(program, at_menu(program))
    assert kinds(burst) == [AudioRestore, NvlPage, ShowStage, Say, ShowMenu]
    say, menu = burst[3], burst[4]
    assert say.sid == before and say.restored and say.voice is None
    assert lines([say]) == ["Before."]
    assert menu.line == "kept" and menu.restored
    assert not any(type(c) is PlayVoice for c in burst)


def test_ac17_a_question_less_menu_after_a_question_menus_pick(tmp_path):
    program = load_m(tmp_path, M='menu:⏎[8]hana "Will you buy a lantern?"⏎[8]"Yes":⏎'
                                 '[12]menu:⏎[16]"Red":⏎[20]$ lantern = "red"⏎'
                                 '[16]"Blue":⏎[20]$ lantern = "blue"')
    state = at_menu(program, "a c1")
    assert state.choices.waiting.kept == sid_at(program, 6)
    interp, burst = restored(program, state)
    say, menu = burst[-2], burst[-1]
    assert type(say) is Say and say.sid == sid_at(program, 6) and say.restored
    assert lines([say]) == [QUESTION] and say.name == "Hana"
    assert menu.line == "kept" and menu.sid == sid_at(program, 9)
    assert interp.menu_open == (menu, None) and interp.kept_line == sid_at(program, 6)


def test_ac17_a_question_less_menu_with_nothing_kept(tmp_path):
    program = load_m(tmp_path, S="$ pass", M=GO)
    state = at_menu(program, "")
    assert state.choices.waiting.kept is None
    interp, burst = restored(program, state)
    assert kinds(burst) == [AudioRestore, NvlPage, ShowStage, ShowMenu]
    assert burst[-1].line == "none" and interp.kept_line is None


def test_ac17_r3_the_kept_line_shows_the_values_as_of_the_menu(tmp_path):
    program = load_m(tmp_path, S='"Coins: {var=coins}"', M="$ coins = 5⏎" + GO)
    _, live = play(program, "a")
    assert lines(live) == ["Coins: 2"]
    _, burst = restored(program, at_menu(program))
    assert lines(burst) == ["Coins: 5"] and menus(burst)[0].line == "kept"


DICE = ('menu:⏎[8]"Heads" if dice.roll(1, 2) == 1:⏎[12]$ lantern = str(dice.roll(1, 100))⏎'
        '[8]"Tails" if dice.roll(1, 3) == 2:⏎[12]$ lantern = str(dice.roll(1, 100))⏎'
        '[8]"Walk away":⏎[12]$ lantern = str(dice.roll(1, 100))')


def test_ac17_dice_in_a_condition_never_rolls_again(tmp_path):
    program = load_m(tmp_path, M=DICE)
    seen = set()
    for seed in range(1, 21):
        interp, commands = play(program, "a", seed=seed)
        state = interp.checkpoint()
        live_menu = menus(commands)[-1]
        live_after = go(interp, "c1 a")
        again, burst = restored(program, state)
        assert menus(burst)[0].choices == live_menu.choices, seed
        assert go(again, "c1 a") == live_after, seed
        assert again.core.state == interp.core.state, seed
        seen.add(tuple(c.key for c in live_menu.choices))
    assert len(seen) > 1                                     # the rolls did differ


# --- AC-F07-18 — restore after a script edit ----------------------------------------------------------

def waiting_story(program) -> Interpreter:
    interp, _ = play(program, "", to_end=False)
    interp.take_commands(ALL)
    return interp


def test_ac18_a_reworded_choice_drops_out(tmp_path):
    program = load_m(tmp_path, replace={8: '"The blue one":'})
    interp = waiting_story(program)
    assert interp.restore(bm()).result is OK
    burst = interp.take_commands(ALL)
    assert [key for key, _, _ in shown(menus(burst)[0])] == [K(CROSS[1]), K(CROSS[2])]
    assert interp.choices.waiting.pickable == (K(CROSS[1]), K(CROSS[2]))
    go(interp, "c1")
    assert interp.G["lantern"] == "crane"


def test_ac18_a_new_choice_is_not_offered(tmp_path):
    program = load_m(tmp_path, M=MENU + '⏎[8]"A fourth":⏎[12]$ pass')
    assert len(program.get(bm().position).choices) == 4
    interp = waiting_story(program)
    assert interp.restore(bm()).result is OK
    menu = menus(interp.take_commands(ALL))[0]
    assert [key for key, _, _ in shown(menu)] == [K(t) for t in CROSS]


@pytest.mark.parametrize("edit", [
    {"M": MENU.replace("The red one", "Red").replace("The paper crane", "Crane")
     .replace("Not this year", "No")},
    {"replace": {7: 'hana "Will you buy a paper lantern?"'}},
])
def test_ac18_not_found_after_an_edit(tmp_path, edit):
    program = load_m(tmp_path, **edit)
    interp = waiting_story(program)
    before = fingerprint(interp)
    assert interp.restore(bm()).result is NOT_FOUND
    assert interp.restore(bm(), check_only=True).result is NOT_FOUND
    assert fingerprint(interp) == before


def test_ac18_a_menu_state_without_waiting_is_not_found(tmp_path):
    program = load_m(tmp_path)
    data = read_save("bm.json")
    data["choices"]["waiting"] = None
    interp = waiting_story(program)
    before = fingerprint(interp)
    assert interp.restore(GameState.from_json(data)).result is NOT_FOUND
    assert fingerprint(interp) == before


def test_ac18_waiting_at_a_line_is_dropped(tmp_path):
    program = load_m(tmp_path)
    data = read_save("line15.json")
    data["choices"]["waiting"] = read_save("bm.json")["choices"]["waiting"]
    interp, burst = restored(program, GameState.from_json(data))
    assert interp.choices.waiting is None and interp.checkpoint().choices.waiting is None
    assert interp.choices.picks == GameState.from_json(data).choices.picks
    assert lines(burst) == ["After: crane."] and interp.menu_open is None


# --- AC-F07-19 — rollback offers the menu again and undoes the pick -----------------------------------

def snapshots(program, text: str, monkeypatch) -> tuple[Interpreter, list[GameState]]:
    taken: list[GameState] = []
    real = Interpreter.take_checkpoint

    def spy(self, stmt, cmd, **kwargs):
        real(self, stmt, cmd, **kwargs)
        taken.append(self.last_checkpoint)

    with monkeypatch.context() as mp:
        mp.setattr(Interpreter, "take_checkpoint", spy)
        interp, _ = play(program, text)
    return interp, taken


def test_ac19_back_to_the_menu_and_another_pick(tmp_path, monkeypatch):
    program = load_m(tmp_path)
    interp, taken = snapshots(program, "a c1", monkeypatch)
    assert [s.position for s in taken] == [sid_at(program, n) for n in (5, 6, 15)]
    assert interp.restore(taken[1]).result is OK
    interp.take_commands(ALL)
    assert interp.choices.picks == ()
    after = go(interp, "c3")
    assert interp.choices.picks == (
        Pick(sid_at(program, 6), K(CROSS[2]), CROSS[2], QUESTION),)
    assert lines(after) == ["Home."]
    assert interp.restore(taken[2]).result is OK
    assert interp.choices.picks == (
        Pick(sid_at(program, 6), K(CROSS[0]), CROSS[0], QUESTION),)


NESTED = ('menu:⏎[8]"Ask about the fox":⏎[12]menu:⏎[16]"Where is it?":⏎[20]"Up the hill."⏎'
          '[16]"Never mind":⏎[20]$ pass⏎[12]"Fox done."⏎[8]"Leave":⏎[12]$ pass')


def test_ac19_nested_menus(tmp_path, monkeypatch):
    program = load_m(tmp_path, M=NESTED)
    interp, taken = snapshots(program, "a c1 c1 a a", monkeypatch)
    inner = next(s for s in taken if s.position == sid_at(program, 8))
    outer_pick = Pick(sid_at(program, 6), K("Ask about the fox"), "Ask about the fox", None)
    assert interp.restore(inner).result is OK
    assert interp.choices.picks == (outer_pick,)
    go(interp, "c2")
    assert interp.choices.picks == (
        outer_pick, Pick(sid_at(program, 8), K("Never mind"), "Never mind", None))


# --- The restore half of the choices fuzz (AC-F07-16 rows on a real story) -------------------------

def restore_fuzz(tmp_path, count: int, seed: int, inflate: bool) -> dict[str, int]:
    """Mutated ``choices`` in Bm and the line-15 state, restored into a waiting Template M:
    ``StateInvalid``, OK, or POSITION_NOT_FOUND with the fingerprint unchanged."""
    program = load_m(tmp_path)
    base = bm()
    interp = launched(program)
    assert interp.restore(base).result is OK
    tally: dict[str, int] = {}
    for name in ("bm.json", "line15.json"):
        data = read_save(name)
        bases = [data["choices"], {"picks": read_save("line15.json")["choices"]["picks"],
                                   "waiting": read_save("bm.json")["choices"]["waiting"]}]
        for choices in fuzz_state.mutations(bases, count // 2, seed, inflate):
            try:
                state = GameState.from_json(dict(data, choices=choices))
            except StateInvalid:
                tally["invalid"] = tally.get("invalid", 0) + 1
                continue
            interp.take_commands(ALL)
            before = fingerprint(interp)
            outcome = interp.restore(state)
            assert type(outcome) is RestoreOutcome
            tally[outcome.result.name] = tally.get(outcome.result.name, 0) + 1
            if outcome.result is OK:
                assert interp.status is Status.WAITING
                assert interp.restore(base).result is OK
            else:
                assert outcome.result is NOT_FOUND and fingerprint(interp) == before
    return tally


def test_restore_fuzz_ci(tmp_path):
    tally = restore_fuzz(tmp_path, 300, seed=717, inflate=False)
    assert tally.get("OK", 0) > 0 and tally.get("invalid", 0) > 0


@pytest.mark.slow
def test_restore_fuzz_full(tmp_path):
    began = time.perf_counter()
    tally = restore_fuzz(tmp_path, 10_000, seed=71_700, inflate=True)
    assert time.perf_counter() - began < 600
    assert tally.get("POSITION_NOT_FOUND", 0) > 0


def test_a_stale_choose_after_a_restore_is_ignored(tmp_path):
    """A ``Choose`` for the menu shown before a restore elsewhere changes nothing."""
    program = load_m(tmp_path)
    interp, _ = restored(program, bm())
    assert interp.restore(GameState.from_json(read_save("line15.json"))).result is OK
    interp.take_commands(ALL)
    before = fingerprint(interp)
    interp.post(Choose(sid_at(program, 6), K(CROSS[0])))
    assert fingerprint(interp) == before
