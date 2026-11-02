"""F07 step 1, menus at run time (``04-technical.md`` §5.1–5.2, §7.1–7.4; ``06-acceptance.md``
§1.2): AC-F07-06 (a pick runs its block), 07 (conditions once), 08 (E178), 09 (what a menu
sends), 10 (the pick record), 11 (one checkpoint per menu), 12 (only a valid pick moves on),
14 (locked choices and ``[choice] show_locked``; its app half, 07 I-2, is
``tests/app/test_menu_agree.py``'s AC-F07-35 windowed run).
"""

import dataclasses
import logging
import shutil

import pytest

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime import limits
from engine.runtime.commands import (Advance, AudioRestore, Choose, EndVoice, PlayVoice,
                                     PrefetchImages, Say, ShowMenu, ShowStage, StoryEnded,
                                     StoryFailed, VarMark)
from engine.runtime.interpreter import (CHECKPOINT_TYPES, Interpreter, RestoreResult, Status)
from engine.runtime.menu import ChoiceState, MenuWait, Pick, plain_text
from engine.script.menu import Menu
from engine.script.messages import format_message
from tests.runtime.menu_story import (ALL, K, go, launched, lines, load_fixture, load_m,
                                      load_text, menu_at, menus, play, run_m, shown, sid_at)
from tests.runtime.stage_story import no_audio
from tests.runtime.story import fingerprint
from tests.script import message_cases

CROSS = ("The red one", "The paper crane (2 coins)", "Not this year")
LOOP = {10: '        "Again":\n            jump talk'}         # 06 §5: talk/'s loop variant


def at_menu(program, **kwargs) -> Interpreter:
    interp, _ = play(program, "a", **kwargs)
    assert type(interp.current) is Menu and interp.status is Status.WAITING
    return interp


# --- AC-F07-06 — a pick runs its block and the story continues --------------------------------------

NESTED = ('menu:⏎[8]"Ask about the fox":⏎[12]menu:⏎[16]"Where is it?":⏎[20]"Up the hill."⏎'
          '[16]"Never mind":⏎[20]$ pass⏎[12]"Fox done."⏎[8]"Leave":⏎[12]$ pass')


@pytest.mark.parametrize("edit,text,expected", [
    ({}, "a c1", ["Before.", "Will you buy a lantern?", "After: red."]),
    ({}, "a c2", ["Before.", "Will you buy a lantern?", "After: crane."]),
    ({}, "a c3", ["Before.", "Will you buy a lantern?", "Home."]),
    ({"M": NESTED}, "a c1 c1 a a", ["Before.", "Up the hill.", "Fox done.", "After: none."]),
    ({"M": NESTED}, "a c1 c2 a", ["Before.", "Fox done.", "After: none."]),
    ({"S": "call shop", "T": 'label shop:⏎[4]menu:⏎[8]"Buy":⏎[12]"Bought."⏎'
                             '[4]"Shop closes."⏎[4]return'},
     "c1 a a c1", ["Bought.", "Shop closes.", "Will you buy a lantern?", "After: red."]),
])
def test_ac06_a_pick_runs_its_block(tmp_path, edit, text, expected):
    interp, commands = play(load_m(tmp_path, **edit), text)
    assert lines(commands) == expected
    assert type(commands[-1]) is StoryEnded


def test_ac06_the_crane_costs_two_coins(tmp_path):
    interp, _ = play(load_m(tmp_path), "a c2")
    assert interp.G["coins"] == 0 and interp.G["lantern"] == "crane"


# --- AC-F07-07 — conditions are checked once, when the menu is reached ------------------------------

def test_ac07_once_before_the_menu_is_released(tmp_path):
    program = load_m(tmp_path)
    crane = menu_at(program, 6).choices[1].condition.code
    calls = []
    real = Interpreter._test

    def spy(self, code):
        calls.append((code, self.menu_open, self.status))
        return real(self, code)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Interpreter, "_test", spy)
        interp, commands = play(program, "a c1")
    assert [(code, open_) for code, open_, _ in calls] == [(crane, None)]
    assert lines(commands)[-1] == "After: red."


def test_ac07_a_false_condition_hides_the_choice(tmp_path):
    program = load_m(tmp_path, replace={2: "default coins = 1"})
    interp, commands = play(program, "a c2")
    (menu,) = menus(commands)
    assert [c.key for c in menu.choices] == [K(CROSS[0]), K(CROSS[2])]
    assert lines(commands)[-1] == "Home."


def test_ac07_top_to_bottom_once_each(tmp_path):
    program = load_m(tmp_path, M='menu:⏎[8]"a" if A():⏎[12]$ pass⏎[8]"b" if B():⏎[12]$ pass⏎'
                                 '[8]"c":⏎[12]$ pass',
                     T='define calls = []⏎define A = lambda: calls.append("A") is None⏎'
                       'define B = lambda: calls.append("B") is None')
    interp, commands = play(program, "a c3")
    assert interp.G["calls"] == ["A", "B"]


def test_ac07_an_unknown_name_fails_at_the_choice(tmp_path):
    program = load_m(tmp_path, replace={10: '"The paper crane (2 coins)" if coisn >= 2:'})
    commands = run_m(program, "a")
    assert not menus(commands)
    failed = commands[-1]
    assert type(failed) is StoryFailed and failed.error.code == "E85b"
    assert failed.error.line == 10 and failed.error.message == (
        'there is no variable named "coisn". Did you mean "coins"?')
    assert failed.error.source_line == '"The paper crane (2 coins)" if coisn >= 2:'


# --- AC-F07-08 — nothing to pick (E178) -----------------------------------------------------------

def test_ac08_talk_menus_shrink(tmp_path):
    commands = run_m(load_fixture(tmp_path, "talk"), "a c1 c1 c1")
    assert [len(m.choices) for m in menus(commands)] == [3, 2, 1]
    assert type(commands[-1]) is StoryEnded


@pytest.mark.parametrize("show_locked,start", [
    (False, "every choice in this menu is hidden, because all their conditions are false, so "
            "the player can't pick anything. Add a choice without if, such as \"That's "
            "all\":."),
    (True, "every choice in this menu is locked, "),
])
def test_ac08_e178(tmp_path, show_locked, start):
    program = load_fixture(tmp_path, "talk", drop=(16, 17))
    taken = []
    real = Interpreter.take_checkpoint

    def spy(self, stmt, cmd, **kwargs):
        taken.append(stmt.line)
        return real(self, stmt, cmd, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Interpreter, "take_checkpoint", spy)
        interp, commands = play(program, "a c1 c1", show_locked=show_locked)
    failed = commands[-1]
    assert type(failed) is StoryFailed and failed.error.code == "E178"
    assert failed.error.line == 8 and failed.error.message.startswith(start)
    assert len(menus(commands)) == 2 and taken == [5, 8, 8]
    assert interp.checkpoint() is None


F07_RUN_ROWS = [c for c in message_cases.load_cases() if c.feature == "F07" and c.time == "run"]


@pytest.mark.parametrize("case", F07_RUN_ROWS, ids=lambda case: case.id)
def test_ac08_run_rows_of_cases(tmp_path, case):
    """The F07 ``time = "run"`` rows of ``cases.toml`` (Run M ``a``)."""
    result = load_text(tmp_path, message_cases.main_text(case))
    assert result.program is not None
    failed = run_m(result.program, "a")[-1]
    assert type(failed) is StoryFailed and failed.error.code == case.code
    where = message_cases.parse_where(case.where)
    assert (failed.error.file, failed.error.line) == where[:2]
    assert failed.error.message == case.expect["exact"]


# --- AC-F07-09 — what a menu sends --------------------------------------------------------------------

def menu_burst(program, **kwargs) -> tuple[Interpreter, list]:
    """The burst that ends with the first ``ShowMenu`` (Run M ``a`` when a line comes
    first), without F08's audio commands."""
    interp = launched(program, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    burst = interp.take_commands(ALL)
    if type(interp.current) is not Menu:
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        burst = interp.take_commands(ALL)
    assert type(burst[-1]) is ShowMenu
    return interp, burst


def test_ac09_template_m(tmp_path):
    program = load_m(tmp_path)
    interp, burst = menu_burst(program)
    assert [type(c) for c in burst] == [Say, ShowMenu]
    say, cmd = burst
    assert say.sid == sid_at(program, 6) and say.text == "Will you buy a lantern?"
    assert not say.restored and say.name == "Hana"
    assert cmd.sid == sid_at(program, 6) and not cmd.restored and cmd.line == "question"
    assert shown(cmd) == [(K(t), t, False) for t in CROSS]


def test_ac09_stage_changes_come_with_the_question(tmp_path):
    program = load_m(tmp_path, replace={5: "scene red"}, T='image red = "#FF0000"')
    interp, burst = menu_burst(program)
    assert [type(c) for c in no_audio(burst)] == [ShowStage, Say, ShowMenu]
    assert type(burst[0]) is AudioRestore


def test_ac09_a_voiced_question(tmp_path):
    program = load_m(tmp_path, M='menu:⏎[8]voice "v/q.ogg"⏎[8]hana "Will you buy a lantern?"⏎'
                                 '[8]"The red one":⏎[12]$ lantern = "red"')
    interp, burst = menu_burst(program)
    sid = sid_at(program, 6)
    assert burst[0] == PlayVoice(sid, "v/q.ogg", False)
    assert [type(c) for c in burst] == [PlayVoice, Say, ShowMenu]
    after = go(interp, "c1")
    assert after[0] == EndVoice(sid) and lines(after) == ["After: red."]


def test_ac09_no_question(tmp_path):
    program = load_m(tmp_path, M='menu:⏎[8]"Go":⏎[12]$ pass')
    interp, burst = menu_burst(program)
    assert [type(c) for c in burst] == [ShowMenu]
    assert burst[0].line == "kept"


def test_ac09_bodies_are_resolved_when_the_menu_is_reached(tmp_path):
    program = load_m(tmp_path, M='menu:⏎[8]"Buy for {var=coins}":⏎[12]$ coins = 9')
    interp, burst = menu_burst(program)
    (choice,) = burst[-1].choices
    assert not any(type(p) is VarMark for p in choice.body.pieces)
    assert plain_text(choice.body) == "Buy for 2"
    go(interp, "c1")
    assert interp.G["coins"] == 9 and interp.choices.picks[0].text == "Buy for 2"


def test_ac09_lookahead_reaches_the_choices(tmp_path):
    """04 §7.3 step 7: F04's look-ahead walks the choice blocks (``blocks()``), first."""
    program = load_m(tmp_path, M='menu:⏎[8]"Go":⏎[12]scene red⏎[8]"Stay":⏎[12]show blue',
                     replace={5: "$ pass", 15: "scene green"},
                     T='image red = "#FF0000"⏎image blue = "#0000FF"⏎image green = "#00FF00"')
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    burst = interp.take_commands(ALL)
    assert [type(c) for c in no_audio(burst)] == [ShowStage, ShowMenu, PrefetchImages]
    assert burst[-1] == PrefetchImages(("red", "green"), ("blue",))


NO_Q = '[4]menu:⏎[8]"Go":⏎[12]$ pass'


@pytest.mark.parametrize("edit,text,line,kept_line", [
    ({"M": NO_Q}, "a", "kept", 5),
    ({"M": NO_Q, "replace": {5: "$ pass"}}, "", "none", None),
    ({"M": NO_Q, "S": '"Before."⏎[4]scene red', "T": 'image red = "#FF0000"'}, "a", "none",
     None),
    ({"M": NO_Q, "S": '"Before."⏎[4]$ coins = 3⏎[4]show red', "T": 'image red = "#FF0000"'},
     "a", "kept", 5),
    ({"M": 'menu:⏎[8]hana "Q?"⏎[8]"Go":⏎[12]menu:⏎[16]"In":⏎[20]$ pass'}, "a c1", "kept", 6),
    ({}, "a", "question", None),
])
def test_ac09_line_and_kept(tmp_path, edit, text, line, kept_line):
    program = load_m(tmp_path, **edit)
    interp, commands = play(program, text)
    cmd = menus(commands)[-1]
    assert cmd.line == line
    want = None if kept_line is None else sid_at(program, kept_line)
    assert interp.choices.waiting.kept == want
    assert interp.checkpoint().choices.waiting.kept == want


# --- AC-F07-10 — the pick record ------------------------------------------------------------------------

def test_ac10_at_the_menu_and_after_a_pick(tmp_path):
    program = load_m(tmp_path)
    interp = at_menu(program)
    assert interp.choices == ChoiceState((), MenuWait(tuple(K(t) for t in CROSS), (), None))
    assert interp.checkpoint().choices == interp.choices
    interp, _ = play(program, "a c2", to_end=False)
    assert interp.current.line == 15
    assert interp.checkpoint().choices == ChoiceState(
        (Pick(sid_at(program, 6), K(CROSS[1]), CROSS[1], "Will you buy a lantern?"),), None)


@pytest.mark.parametrize("M,text,check", [
    ('menu:⏎[8]"{b}Buy{/b} for {var=coins}":⏎[12]$ pass', "a c1",
     lambda picks: picks[0].text == "Buy for 2" and picks[0].question is None),
    (NESTED, "a c1 c1", lambda picks: [p.choice for p in picks] == [
        K("Ask about the fox"), K("Where is it?")]),
    ('menu:⏎[8]"' + "x" * 1_500 + '":⏎[12]$ pass', "a c1",
     lambda picks: len(picks[0].text) == 1_000 and picks[0].text.endswith("…")),
    ('menu:⏎[8]"' + "q" * 2_500 + '"⏎[8]"Go":⏎[12]$ pass', "a c1",
     lambda picks: len(picks[0].question) == 2_000 and picks[0].question.endswith("…")),
])
def test_ac10_rows(tmp_path, M, text, check):
    interp, _ = play(load_m(tmp_path, M=M), text)
    assert check(interp.choices.picks)


def test_ac10_ten_thousand_picks_keep_the_newest(tmp_path, caplog):
    program = load_fixture(tmp_path, "talk", add=LOOP)
    state = at_menu(program).checkpoint()
    old = tuple(Pick("talk/x", f"{i:012x}", f"pick {i}", None) for i in range(10_000))
    full = dataclasses.replace(state, choices=ChoiceState(old, state.choices.waiting))
    interp = launched(program)
    assert interp.restore(full).result is RestoreResult.OK
    interp.take_commands(ALL)
    with caplog.at_level(logging.WARNING, logger="vn.choice"):
        go(interp, " ".join(["c1"] * 10))
    picks = interp.choices.picks
    assert len(picks) == 10_000 and picks[:9_990] == old[10:]
    assert [p.text for p in picks[-10:]] == ["Again"] * 10
    warnings = [r for r in caplog.records if r.name == "vn.choice"]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING


# --- AC-F07-11 — one checkpoint per menu ------------------------------------------------------------

def test_ac11_checkpoint_positions(tmp_path):
    program = load_m(tmp_path)
    taken = []
    real = Interpreter.take_checkpoint

    def spy(self, stmt, cmd, **kwargs):
        real(self, stmt, cmd, **kwargs)
        taken.append((stmt.sid, self.steps, self.last_checkpoint))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Interpreter, "take_checkpoint", spy)
        play(program, "a c2")
    assert [sid for sid, _, _ in taken] == [sid_at(program, n) for n in (5, 6, 15)]
    _, steps, state = taken[1]
    assert steps == 0 and state.choices.waiting is not None and state.choices.picks == ()
    assert Menu in CHECKPOINT_TYPES


def test_ac11_a_loop_through_a_menu_never_counts_toward_e45(tmp_path):
    program = load_fixture(tmp_path, "talk", add=LOOP)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(limits, "STEP_LIMIT", 10)
        commands = run_m(program, "a " + " ".join(["c1"] * 2_000))
    assert len(menus(commands)) == 2_001 and type(commands[-1]) is ShowMenu


# --- AC-F07-12 — only a valid pick moves past a menu ----------------------------------------------------

def test_ac12_stale_and_forged_events(tmp_path, caplog):
    def check(interp, event, debug):
        before = (fingerprint(interp), interp.checkpoint())
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="vn.choice"):
            interp.post(event)
        assert (fingerprint(interp), interp.checkpoint()) == before
        records = [r for r in caplog.records if r.name == "vn.choice"]
        assert len(records) == debug and all(r.levelno == logging.DEBUG for r in records)

    program = load_m(tmp_path / "m")
    menu_sid, line_sid = sid_at(program, 6), sid_at(program, 5)
    interp = at_menu(program)
    for event, debug in ((Advance(menu_sid), 0), (Advance(line_sid), 0),
                         (Choose(line_sid, K(CROSS[0])), 1),
                         (Choose(menu_sid, "000000000000"), 1),
                         (Choose(menu_sid, 1), 1), (Choose(menu_sid, None), 1)):
        check(interp, event, debug)
    poor = load_m(tmp_path / "poor", replace={2: "default coins = 1"})
    for show_locked in (False, True):
        other = at_menu(poor, show_locked=show_locked)
        check(other, Choose(menu_sid, K(CROSS[1])), 1)
    interp.post(Choose(menu_sid, K(CROSS[0])))
    assert interp.status is Status.RUNNING
    check(interp, Choose(menu_sid, K(CROSS[0])), 1)
    interp.run(10_000)
    assert lines(interp.take_commands(ALL)) == ["After: red."]
    assert len(interp.choices.picks) == 1


# --- AC-F07-14 — locked choices and [choice] show_locked ------------------------------------------------

def test_ac14_show_locked(tmp_path):
    program = load_m(tmp_path, replace={2: "default coins = 1"})
    interp, commands = play(program, "a", show_locked=True)
    (cmd,) = menus(commands)
    assert [(key, locked) for key, _, locked in shown(cmd)] == [
        (K(CROSS[0]), False), (K(CROSS[1]), True), (K(CROSS[2]), False)]
    assert interp.choices.waiting.locked == (K(CROSS[1]),)
    assert interp.choices.waiting.pickable == (K(CROSS[0]), K(CROSS[2]))
    interp, commands = play(program, "a c2", show_locked=True)
    assert lines(commands)[-1] == "Home."
    assert interp.choices.picks[0].text == "Not this year"
    _, commands = play(program, "a")
    assert [key for key, _, _ in shown(menus(commands)[0])] == [K(CROSS[0]), K(CROSS[2])]


def test_ac14_config_text(tmp_path):
    (tmp_path / "config.toml").write_text('[choice]\nshow_locked = "yes"\n', encoding="utf-8")
    result = load_config(GamePaths(tmp_path.resolve()))
    assert [e.format() for e in result.errors] == [
        'config.toml, line 2: [choice] show_locked must be true or false, but found the text '
        '"yes"']
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    assert load_config(GamePaths(tmp_path.resolve())).config.choice.show_locked is False


# The app half (07 I-2: the windowed ShowMenu carries show_locked from config.toml) is
# tests/app/test_menu_agree.py::test_ac35_windowed_commands_equal_headless (show_locked = true,
# windowed commands == headless) and tests/ui/test_choice_screen.py::test_ac22_a_locked_choice.


def test_ac14_the_template_folder_is_clean(tmp_path):
    shutil.copytree(message_cases.FIXTURES.parent / "F07" / "template", tmp_path / "g")
    result = load_config(GamePaths((tmp_path / "g").resolve()))
    assert not result.errors and not result.warnings
    assert format_message("E178", (True,)).startswith("every choice in this menu is locked, ")
