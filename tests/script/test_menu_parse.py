"""F07 step 1, the script side of menus (``04-technical.md`` §6; ``06-acceptance.md`` §1.1):
AC-F07-01 (the statement), 02 (shape errors), 03 (tags in choice text), 04 (conditions, and
``if`` text outside menus), 05 (menu and choice identities).

The message rows of 02–04 are data in ``tests/fixtures/F02/messages/cases.toml``
(``feature = "F07"``); ``test_f07_message_rows`` runs them here too.
"""

import pytest

from engine.script.identity import walk_block
from engine.script.menu import Menu
from engine.script.nodes import Jump, PythonLine, Say
from engine.script.texttags import BASE_STYLE, Span, Style, VarMark
from tests.runtime.menu_story import K, load_m, load_m_result, menu_at, sid_at
from tests.script import message_cases

F07_ROWS = [c for c in message_cases.load_cases() if c.feature == "F07" and c.runnable]


def menus_in(program) -> list[Menu]:
    return [s for s in program.iter_statements() if type(s) is Menu]


# --- AC-F07-01 — the menu statement ------------------------------------------------------------

def test_ac01_template_m(tmp_path):
    program = load_m(tmp_path)
    menu = menu_at(program, 6)
    question = menu.question
    assert type(question) is Say and question.speaker == "hana"
    assert question.text == "Will you buy a lantern?" and question.sid == menu.sid
    assert menu.voice is None
    assert [c.text for c in menu.choices] == ["The red one", "The paper crane (2 coins)",
                                              "Not this year"]
    assert [c.line for c in menu.choices] == [8, 10, 13]
    assert [c.key for c in menu.choices] == [K(c.text) for c in menu.choices]
    assert [c.condition.source if c.condition else None for c in menu.choices] == [
        None, "coins >= 2", None]
    assert [len(c.block) for c in menu.choices] == [1, 2, 1]
    assert [type(s) for c in menu.choices for s in c.block] == [PythonLine] * 3 + [Jump]


@pytest.mark.parametrize("M,check", [
    ('menu:⏎[8]"Go":⏎[12]$ pass', lambda m: m.question is None and len(m.choices) == 1),
    ('menu:⏎[8]"Which way?"⏎[8]"Left":⏎[12]$ pass',
     lambda m: m.question.speaker is None and m.question.text == "Which way?"),
    ('menu:⏎[8]# note⏎⏎[8]hana "Hi."⏎[8]"Go":⏎[12]$ pass',
     lambda m: m.question.text == "Hi." and len(m.choices) == 1),
    ('⏎'.join(['menu:'] + [f'[8]"c{i}":⏎[12]$ pass' for i in range(1, 7)]),
     lambda m: len(m.choices) == 6),
    ('menu:⏎[8]"Out":⏎[12]menu:⏎[16]"In":⏎[20]$ pass',
     lambda m: type(m.choices[0].block[0]) is Menu
     and m.choices[0].block[0].choices[0].text == "In"),
])
def test_ac01_rows_load(tmp_path, M, check):
    result = load_m_result(tmp_path, M=M)
    assert result.program is not None and not result.errors
    assert not [w for w in result.warnings if w.code.startswith("W")], result.warnings
    assert check(menu_at(result.program, 6))


def test_ac01_a_voice_above_the_question_voices_it(tmp_path):
    result = load_m_result(tmp_path, M='menu:⏎[8]voice "v/q.ogg"⏎[8]hana "Hi."⏎[8]"Go":⏎'
                                       '[12]$ pass')
    assert result.program is not None and result.warnings == ()          # no W20
    menu = menu_at(result.program, 6)
    assert menu.voice is not None and menu.voice.audio_file == "v/q.ogg"
    assert menu.question.voice == "v/q.ogg"


def test_ac01_a_voice_above_menu_is_w20(tmp_path):
    result = load_m_result(tmp_path, M='voice "v/q.ogg"⏎[4]menu:⏎[8]"Go":⏎[12]$ pass')
    assert [(w.code, w.line, w.message) for w in result.warnings] == [(
        "W20", 6, "voice goes directly above a line, not above a menu. Put a voice inside "
                  "each branch.")]


def test_ac01_a_voice_with_no_question_is_w20s_first_form(tmp_path):
    result = load_m_result(tmp_path, M='menu:⏎[8]voice "v/q.ogg"⏎[8]"Go":⏎[12]$ pass')
    assert [(w.code, w.line) for w in result.warnings] == [("W20", 7)]
    assert result.warnings[0].message.startswith("this voice has no line of dialogue")


# --- AC-F07-02, 03, 04 — the message rows ------------------------------------------------------

# Every row runs in tests/script/test_messages.py::test_case[F07-*] (and its golden file);
# here, only that AC-F07-02's rows are there.

def test_ac02_every_row_is_in_cases():
    ids = {c.id for c in F07_ROWS}
    for name in ("E12-menu", "E12-choice", "E172", "E173-1", "E173-2",
                 "E174-question-after", "E174-no-colon-1", "E174-no-colon-2",
                 "E174-other-1", "E174-other-2", "E174-other-3", "E176-1", "E176-2", "E177",
                 "E177-E12", "E31b"):
        assert f"F07-02-{name}" in ids


# --- AC-F07-03 — tags in choice text -------------------------------------------------------------

@pytest.mark.parametrize("text,pieces", [
    ("{b}Red{/b} for {var=lantern}",
     (Span("Red", Style(bold=True)), Span(" for ", BASE_STYLE), VarMark("lantern", BASE_STYLE))),
    ("{i}x{/i} {color=#9a1c14}y{/color} {{z",
     (Span("x", Style(italic=True)), Span(" ", BASE_STYLE), Span("y", Style(color="#9a1c14")),
      Span(" {z", BASE_STYLE))),
])
def test_ac03_bodies(tmp_path, text, pieces):
    menu = menu_at(load_m(tmp_path, M=f'menu:⏎[8]"{text}":⏎[12]$ pass'), 6)
    assert menu.choices[0].body.pieces == pieces


def test_ac03_w42_visits_the_question(tmp_path):
    result = load_m_result(tmp_path, M='menu:⏎[8]hana "Hi {var=met_daichi}."⏎[8]"Go":⏎'
                                       '[12]$ pass')
    assert [(w.code, w.line) for w in result.warnings] == [("W42", 7)]


# --- AC-F07-04 — conditions on choices, and if text outside menus --------------------------------

def test_ac04_condition_with_hash_and_colon(tmp_path):
    menu = menu_at(load_m(tmp_path, M='menu:⏎[8]"t" if x in (\'#\', \':\'):⏎[12]$ pass',
                          T='default x = "#"'), 6)
    assert menu.choices[0].condition.source == "x in ('#', ':')"


def test_ac04_condition_over_two_lines(tmp_path):
    menu = menu_at(load_m(tmp_path, M='menu:⏎[8]"t" if (coins >=⏎[12]2):⏎[12]$ pass'), 6)
    choice = menu.choices[0]
    assert choice.condition.line == 7 and choice.condition.source.count("\n") == 1
    assert choice.block[0].line == 9


@pytest.mark.parametrize("condition", ["coins >= ", "coins = 2"])
def test_ac04_python_errors_as_if_gives_them(tmp_path, condition):
    as_if = load_m_result(tmp_path / "if", S=f"if {condition}:⏎[8]$ pass")
    as_choice = load_m_result(tmp_path / "choice",
                              M=f'menu:⏎[8]"t" if {condition}:⏎[12]$ pass')
    (want,) = as_if.errors
    (got,) = as_choice.errors
    assert (got.code, got.message, got.line) == (want.code, want.message, 7)


@pytest.mark.parametrize("S", ['"Fine" if you insist :(', '"Sure" if it\'s late'])
def test_ac04_c8_rows_one_error_and_the_menu_still_parses(tmp_path, S):
    result = load_m_result(tmp_path, S=S)
    assert len(result.errors) == 1 and result.error_count == 1
    assert result.errors[0].line == 5 and result.errors[0].code in ("E53", "E74", "E80",
                                                                     "E81")


def test_ac04_no_row_gives_e32(tmp_path):
    for index, M in enumerate(['menu:⏎[8]"t" iffy:⏎[12]$ pass', 'menu:⏎[8]"Go":⏎[12]$ pass']):
        result = load_m_result(tmp_path / str(index), M=M)
        assert "E32" not in [e.code for e in result.errors]


# --- AC-F07-05 — menu and choice identities ---------------------------------------------------------

BASE_KEYS = [K("The red one"), K("The paper crane (2 coins)"), K("Not this year")]
CHOICES = ['[8]"The red one":⏎[12]$ lantern = "red"',
           '[8]"The paper crane (2 coins)" if coins >= 2:⏎[12]$ coins -= 2⏎'
           '[12]$ lantern = "crane"',
           '[8]"Not this year":⏎[12]jump walk_home']
QUESTION = '[8]hana "Will you buy a lantern?"'


def menu_of(*choices: str, question: str = QUESTION) -> str:
    return "⏎".join(["menu:", question, *choices])


def check_walk(program) -> None:
    """``Program.at`` resolves every path ``walk_block`` yields, in pre-order, and
    ``Program.get`` returns each menu."""
    for label in program.labels.values():
        for stmt, path in walk_block(label.block):
            assert program.at(label.name, path) is stmt
            assert program.get(stmt.sid) is stmt
    for menu in menus_in(program):
        assert program.get(menu.sid) is menu and menu.question in (None,) + menu.inner()


def test_ac05_pre_order(tmp_path):
    program = load_m(tmp_path)
    check_walk(program)
    assert [s.line for s in program.statements_in("start")] == [5, 6, 9, 11, 12, 14, 15, 16]
    assert program.get(sid_at(program, 6)) is menu_at(program, 6)
    assert [s.path for s in program.statements_in("start")][2:6] == [
        (1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 2, 0)]


@pytest.mark.parametrize("M,same_sid,keys", [
    (menu_of(CHOICES[0].replace("red", "blue"), *CHOICES[1:]), True,
     [K("The blue one")] + BASE_KEYS[1:]),
    (menu_of(*CHOICES, '[8]"A fourth":⏎[12]$ pass'), True, BASE_KEYS + [K("A fourth")]),
    (menu_of(*CHOICES[:2]), True, BASE_KEYS[:2]),
    (menu_of(*reversed(CHOICES)), True, BASE_KEYS[::-1]),
    (menu_of(CHOICES[0], CHOICES[1].replace(">= 2", ">= 3"), CHOICES[2]), True, BASE_KEYS),
    (menu_of(CHOICES[0].replace('"red"', '"pink"'), *CHOICES[1:]), True, BASE_KEYS),
    (menu_of(*CHOICES, question='[8]hana "Will you buy one?"'), False, BASE_KEYS),
    (menu_of(*CHOICES, question='[8]"Will you buy a lantern?"'), False, BASE_KEYS),
    (menu_of(CHOICES[0], CHOICES[1].replace("⏎[12]$ coins -= 2", "⏎[12]$ x = 1⏎[12]$ coins -= 2"),
             CHOICES[2]), True, BASE_KEYS),
])
def test_ac05_identities(tmp_path, M, same_sid, keys):
    base = load_m(tmp_path / "base")
    program = load_m(tmp_path / "edit", M=M)
    check_walk(program)
    menu = menu_at(program, 6)
    assert (menu.sid == menu_at(base, 6).sid) is same_sid
    assert [c.key for c in menu.choices] == keys


def test_ac05_an_inserted_statement_follows_adr_0006(tmp_path):
    base = load_m(tmp_path / "base")
    program = load_m(tmp_path / "edit", M=menu_of(
        CHOICES[0], CHOICES[1].replace("⏎[12]$ coins -= 2", "⏎[12]$ x = 1⏎[12]$ coins -= 2"),
        CHOICES[2]))
    before = {(type(s).__name__, s.sid) for s in base.iter_statements()}
    after = {(type(s).__name__, s.sid) for s in program.iter_statements()}
    assert before < after and len(after - before) == 1


def test_ac05_equal_texts_get_tilde_keys(tmp_path):
    menu = menu_at(load_m(tmp_path, M=menu_of('[8]"Go":⏎[12]$ pass', '[8]"Go":⏎[12]$ pass')), 6)
    assert [c.key for c in menu.choices] == [K("Go"), K("Go") + "~2"]


def test_ac05_question_less_menus_in_a_label_share_a_key(tmp_path):
    """ADR-0006 addendum 1: question-less menus are told apart by ``~n``."""
    program = load_m(tmp_path, M='menu:⏎[8]"a":⏎[12]$ pass⏎[4]menu:⏎[8]"b":⏎[12]$ pass')
    first, second = menus_in(program)
    assert second.sid == first.sid + "~2"
    check_walk(program)
