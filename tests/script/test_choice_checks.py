"""F59 checks on choices, the script side (SPEC §2–§4): AC-F59-01 (parse), 02 (E408, E409,
E233), 03 (the odds rule)."""

import pytest

from engine.script.choicecheck import (CheckRoll, badge, odds, parse_difficulty, passes,
                                       success_count, tier)
from engine.script.menu import Menu, choice_key
from engine.script.messages import format_message
from tests.runtime.menu_story import load_text

CHECKED = '''define hana = Character("Hana")
points logic empathy 0 to 10 start 3
default met = True
label start:
    menu:
        hana "Admit it."
        "The gate was locked." check logic hard:
            success:
                hana "How?"
            failure:
                hana "Nice story."
        "You're scared." check empathy 7 if met:
            success:
                hana "...Of the river."
            failure:
                "She looks away."
        "Never mind.":
            $ pass
    hana "End."
'''
GATE = '"The gate was locked." check logic hard:'
BRANCHES = ('            success:\n                hana "How?"\n'
            '            failure:\n                hana "Nice story."\n')


def _menu(program) -> Menu:
    menu = program.labels["start"].block[0]
    assert isinstance(menu, Menu)
    return menu


def _errors(tmp_path, text):
    result = load_text(tmp_path, text)
    return [(e.code, e.line, e.message) for e in result.errors]


# --- AC-F59-01 — the check and its two branches -----------------------------------------------

def test_ac01_checks_parse_with_words_numbers_and_if(tmp_path):
    result = load_text(tmp_path, CHECKED)
    assert not result.errors
    gate, scared, never = _menu(result.program).choices
    assert (gate.check.meter, gate.check.difficulty, gate.check.written) == ("logic", 12, "hard")
    assert gate.condition is None
    assert (scared.check.meter, scared.check.difficulty) == ("empathy", 7)
    assert scared.condition is not None and scared.condition.source == "met"
    assert never.check is None
    roll = gate.block[0]
    assert len(gate.block) == 1 and isinstance(roll, CheckRoll)
    assert [b.keyword for b in roll.branches] == ["success", "failure"]
    assert [s.text for b in roll.blocks() for s in b] == ["How?", "Nice story."]
    assert roll.line == 8 and roll.sid.startswith("start/")
    assert gate.key == choice_key("The gate was locked.")     # the check isn't in the key


def test_ac01_words_stay_free_as_variable_names(tmp_path):
    text = CHECKED.replace('default met = True\n',
                           'default met = True\ndefault check = 1\ndefault success = 2\n'
                           'default failure = 3\n')
    assert not load_text(tmp_path, text).errors


# --- AC-F59-02 — E408, E409, E233 ---------------------------------------------------------------

@pytest.mark.parametrize("line, args", [
    ('"A" check:', ("empty",)),
    ('"A" check logic:', ("missing", "logic")),
    ('"A" check logic tough:', ("bad", "tough")),
    ('"A" check logic 100:', ("bad", "100")),
    ('"A" check logic 0:', ("bad", "0")),
    ('"A" check 9 logic:', ("meter", "9 logic")),
    ('"A" check logic 9 now:', ("left", "logic 9", "now")),
    ('"A" check logic 9 retry:', ("retry",)),
])
def test_ac02_e408_forms(tmp_path, line, args):
    assert _errors(tmp_path, CHECKED.replace(GATE, line)) == [
        ("E408", 7, format_message("E408", args))]


@pytest.mark.parametrize("body, rows", [
    ('            success:\n                hana "y"\n', [("missing", "failure", 7)]),
    ('            hana "y"\n', [("other", "", 8)]),
    ('            failure:\n                hana "x"\n            success:\n                hana "y"\n',
     [("order", "success", 10)]),
    ('            success:\n                hana "y"\n            success:\n                hana "y"\n'
     '            failure:\n                hana "y"\n', [("twice", "success", 10)]),
])
def test_ac02_e409_forms(tmp_path, body, rows):
    assert _errors(tmp_path, CHECKED.replace(BRANCHES, body)) == [
        ("E409", line, format_message("E409", (form, word))) for form, word, line in rows]


def test_ac02_empty_branch_is_e12(tmp_path):
    body = '            success:\n            failure:\n                hana "y"\n'
    assert _errors(tmp_path, CHECKED.replace(BRANCHES, body)) == [
        ("E12", 8, "success: has no lines under it. Indent what happens on a success; to just "
                   "go on, write $ pass.")]


def test_ac02_unknown_meter_is_e233_with_did_you_mean(tmp_path):
    assert _errors(tmp_path, CHECKED.replace(GATE, '"A" check lgoic 9:')) == [
        ("E233", 7, format_message("E233", ("lgoic", "logic")))]


# --- AC-F59-03 — the odds -----------------------------------------------------------------------

def test_ac03_dice_rule_and_odds():
    assert passes(6, 6, 0, 99) and not passes(1, 1, 50, 2)
    assert passes(3, 4, 2, 9) and not passes(3, 4, 1, 9)
    assert success_count(3, 12) == 10 and odds(3, 12) == 28          # needs 9 on two dice
    assert odds(0, 7) == 58 and odds(5, 12) == 58
    assert odds(100, 2) == 97 and odds(-100, 99) == 3                 # never certain
    assert [tier(n) for n in (1, 6, 7, 10, 13, 18, 99)] == [
        "Trivial", "Trivial", "Trivial", "Medium", "Hard", "Impossible", "Impossible"]
    assert badge("street_smarts", 3, 12) == "[Street smarts · Hard · 28%]"
    assert [parse_difficulty(t) for t in ("hard", "HARD", "12", "1", "99", "0", "x")] == [
        12, 12, 12, 1, 99, None, None]
