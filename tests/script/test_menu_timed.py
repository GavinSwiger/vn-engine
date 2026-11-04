"""F51 step S1, the script side of timed menus (``01-design.md`` §5, ``04-technical.md``
§7.1; 07 I-3): AC-F51-01 (the header and the marker), 02 (identity), 03 (E368), 04 (E369,
E370), 05 (the words stay free), 06 (W257).

Rows use F07's template M (``tests/script/helpers.template_m``): the menu is on line 6, its
choices on lines 7 onward.
"""

import pytest

from engine.script.messages import format_message
from tests.runtime.menu_story import load_m, load_m_result, menu_at

BODY = '⏎[8]"Go":⏎[12]$ pass⏎[8]"..." timeout:⏎[12]$ pass'


def _errors(tmp_path, M):
    result = load_m_result(tmp_path, M=M)
    return [(e.code, e.line, e.message) for e in result.errors]


# --- AC-F51-01 — menu time N: and the timeout marker --------------------------------------------

@pytest.mark.parametrize("head,time,text", [
    ("menu time 5:", 5.0, "5"), ("menu time 2.5:", 2.5, "2.5"), ("menu time 1:", 1.0, "1"),
    ("menu time 60:", 60.0, "60"), ("menu time 5:  # a comment", 5.0, "5"),
])
def test_ac01_time_and_marker_parse(tmp_path, head, time, text):
    menu = menu_at(load_m(tmp_path, M=head + BODY), 6)
    assert (menu.time, menu.time_text) == (time, text)
    assert [(c.text, c.timeout) for c in menu.choices] == [("Go", False), ("...", True)]
    plain = menu_at(load_m(tmp_path / "plain"), 6)
    assert plain.time is None and not any(c.timeout for c in plain.choices)


# --- AC-F51-02 — time and timeout are not part of the identity -----------------------------------

def test_ac02_sid_and_keys_ignore_time_and_timeout(tmp_path):
    timed = menu_at(load_m(tmp_path / "a", M='menu time 5:⏎[8]hana "Hi."' + BODY), 6)
    plain = menu_at(load_m(tmp_path / "b", M='menu:⏎[8]hana "Hi."⏎[8]"Go":⏎[12]$ pass⏎'
                                             '[8]"...":⏎[12]$ pass'), 6)
    assert timed.sid == plain.sid and timed.identity_key() == plain.identity_key()
    assert [c.key for c in timed.choices] == [c.key for c in plain.choices]


# --- AC-F51-03 — E368's three forms ------------------------------------------------------------

@pytest.mark.parametrize("head,args", [
    ("menu time:", (1,)),
    ("menu time 0:", (2, "0")), ("menu time 61:", (2, "61")), ("menu time five:", (2, "five")),
    ("menu time -3:", (2, "-3")), ("menu time x+1:", (2, "x+1")),
    ("menu time " + "x" * 40 + ":", (2, "x" * 30)),
    ("menu time 5 now:", (3, "5")),
])
def test_ac03_e368_forms(tmp_path, head, args):
    assert _errors(tmp_path, head + '⏎[8]"Go":⏎[12]$ pass') == [
        ("E368", 6, format_message("E368", args))]


def test_ac03_e368_exact_texts():
    assert format_message("E368", (1,)) == (
        "menu time needs a number of seconds after it, e.g. menu time 5:")
    assert format_message("E368", (2, "five")) == (
        "menu time takes a number of seconds from 1 to 60, but found five. Write e.g. "
        "menu time 5:")
    assert format_message("E368", (3, "5")) == (
        'menu time 5 takes nothing else on its line. Put the question on the first line '
        'inside the menu, e.g. hana "Where to?"')


# --- AC-F51-04 — E369's three forms and E370 ----------------------------------------------------

E369_1 = ("this choice is marked timeout, but its menu has no time limit. Write menu time 5: to "
          "give the player 5 seconds, or remove timeout.")
E369_2 = ("this menu has a time limit but no choice marked timeout, so nothing could happen "
          'when time runs out. Write timeout after one choice\'s text, e.g. "Say nothing" '
          "timeout:")
E369_3 = ("this menu has 2 choices marked timeout, but time running out picks only one. Remove "
          "timeout from all but one.")
E370 = ("the timeout choice can't have an if: when time runs out, it must be there to pick. "
        "Remove the if, or mark a choice without one as timeout.")


@pytest.mark.parametrize("M,expected", [
    ('menu:⏎[8]"Go":⏎[12]$ pass⏎[8]"..." timeout:⏎[12]$ pass', ("E369", 9, E369_1)),
    ('menu time 5:⏎[8]"Go":⏎[12]$ pass⏎[8]"...":⏎[12]$ pass', ("E369", 6, E369_2)),
    ('menu time 5:⏎[8]"Go" timeout:⏎[12]$ pass⏎[8]"..." timeout:⏎[12]$ pass',
     ("E369", 9, E369_3)),
    ('menu time 5:⏎[8]"Go":⏎[12]$ pass⏎[8]"..." timeout if coins > 1:⏎[12]$ pass',
     ("E370", 9, E370)),
])
def test_ac04_e369_and_e370(tmp_path, M, expected):
    assert _errors(tmp_path, M) == [expected]


# --- AC-F51-05 — time and timeout stay free as names --------------------------------------------

def test_ac05_words_stay_free_and_capitals_are_e53(tmp_path):
    program = load_m(tmp_path / "a", S="$ timeout = 3",
                     T="label clock:⏎[4]$ time = timeout⏎[4]return",
                     replace={2: "default time = 0"})
    assert program is not None
    errors = _errors(tmp_path / "b", 'menu time 5:⏎[8]"Go":⏎[12]$ pass⏎[8]"..." Timeout:⏎'
                                     '[12]$ pass')
    assert [(code, line) for code, line, _ in errors] == [("E53", 9)]
    assert errors[0][2] == format_message("E53", ("Timeout:",))


# --- AC-F51-06 — W257 -----------------------------------------------------------------------------

def _choices(total: int) -> str:
    """Two choices, ``total`` shown characters between them (the second is ``...``)."""
    return f'⏎[8]"{"a" * (total - 3)}":⏎[12]$ pass⏎[8]"..." timeout:⏎[12]$ pass'


@pytest.mark.parametrize("M,expected", [
    ("menu time 3:" + _choices(112), ("3", 112, 8)),
    ("menu time 8:" + _choices(112), None),
    ("menu time 7.5:" + _choices(112), ("7.5", 112, 8)),
    # Tags aren't counted, {var=x} counts as its name: 10 + 6 ("coins ") + 3 = 19 → 2 s.
    ('menu time 1:⏎[8]"{b}aaaaaaaaaa{/b} {var=coins}":⏎[12]$ pass⏎[8]"..." timeout:⏎'
     "[12]$ pass", ("1", 19, 2)),
    ('menu time 2:⏎[8]"{b}aaaaaaaaaa{/b} {var=coins}":⏎[12]$ pass⏎[8]"..." timeout:⏎'
     "[12]$ pass", None),
])
def test_ac06_w257(tmp_path, M, expected):
    result = load_m_result(tmp_path, M=M)
    assert result.errors == ()
    found = [(w.code, w.line, w.message) for w in result.warnings]
    assert found == ([] if expected is None else
                     [("W257", 6, format_message("W257", expected))])
    if expected is not None:
        assert found[0][2] == (
            f"this menu gives the player {expected[0]} seconds, but its choices are "
            f"{expected[1]} characters long, about {expected[2]} seconds of reading. Raise the "
            f"time, e.g. menu time {expected[2]}:, or shorten the choices.")


def test_ac06_w257_reaches_lint(tmp_path, monkeypatch):
    """The check child (Studio's Problems) and ``lint`` print W257 like any script check."""
    from tests.tools.test_lint_cli import _clean, _lint

    game = _clean(tmp_path)
    (game / "script" / "main.vns").write_text(
        'label start:\n    menu time 3:\n        "' + "a" * 109 + '":\n            "A."\n'
        '        "..." timeout:\n            "B."\n', encoding="utf-8")
    code, data = _lint(monkeypatch, str(game))
    lines = data.decode("utf-8").splitlines()
    assert ("script/main.vns:2: warning W257: " + format_message("W257", ("3", 112, 8))
            ) in lines, lines
