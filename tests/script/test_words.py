"""Names and reserved words (F02 checklist step 1; 02-script.md §3.6–3.7).

AC-F02-28 (names): ``check_name`` and the parse-level rows. E47's duplicate is decided by
the whole-game checks (step 7); here the NFKC name lands twice in ``define_defs``.
"""

import keyword

import pytest

from engine.script import limits
from engine.script.words import (
    ENGINE_NAMES,
    MODIFIER_WORDS,
    ROLE_LABEL,
    STATEMENT_WORDS,
    canonical_name,
    check_name,
    is_name,
    is_word_char,
)
from tests.script.helpers import message_at, parse_text, template


def test_canonical_name_is_nfkc_for_non_ascii():
    assert canonical_name("ｈａｎａ") == "hana"
    assert canonical_name("hana") == "hana"
    assert canonical_name("café") == "café"


def test_is_name():
    assert is_name("hana") and is_name("始まり") and is_name("ｈａｎａ") and is_name("_x")
    assert not is_name("2b") and not is_name("chapter-2") and not is_name("")


def test_word_chars_include_digits_and_combining_marks():
    assert is_word_char("2") and is_word_char("_") and is_word_char("́")
    assert not is_word_char("-") and not is_word_char(" ") and not is_word_char('"')


@pytest.mark.parametrize("name,role,expected", [
    ("scene", "a character name", ("E60", ("scene", "a character name"))),
    ("JUMP", ROLE_LABEL, ("E60", ("JUMP", ROLE_LABEL))),
    ("Scene", "a name", ("E60", ("Scene", "a name"))),
    ("class", "a name", ("E61", ("class",))),
    ("narrator", "a name", ("E62", ("narrator",))),
    ("Character", "a name", ("E62", ("Character",))),
    ("persistent", "a name", ("E62", ("persistent",))),
    ("engine", "a name", ("E62", ("engine",))),
    ("_intro", "a name", ("E63", ("_intro",))),
    ("chapter-2", "a name", ("E64", ("chapter-2",))),
    ("hana", "a name", None),
    ("始まり", "a name", None),
])
def test_check_name(name, role, expected):
    assert check_name(name, role) == expected


def test_reserved_words_win_over_python_keywords():
    # "if", "else", "return", "with", "as" are both; E60 is checked first.
    for word in STATEMENT_WORDS & set(keyword.kwlist):
        assert check_name(word)[0] == "E60"


def test_modifier_and_engine_names():
    assert MODIFIER_WORDS == {"at", "as", "behind"} <= STATEMENT_WORDS
    assert {"Character", "persistent", "engine", "narrator"} <= ENGINE_NAMES


@pytest.mark.parametrize("edit,message", [
    ({"T": 'define scene = Character("S")'},
     '"scene" is a statement word, so it can\'t be a character name. Pick another name, such '
     'as "my_scene".'),
    ({"T": "label show:⏎[4]return"},
     '"show" is a statement word, so it can\'t be a label name. Pick another name, such as '
     '"my_show".'),
    ({"T": "define menu = 3"},
     '"menu" is a statement word, so it can\'t be a name. Pick another name, such as '
     '"my_menu".'),
    ({"T": "define class = 1"},
     '"class" is a word Python uses, so it can\'t be a name. Pick another name, such as '
     '"my_class".'),
    ({"T": 'define narrator = Character("N")'},
     '"narrator" is a name the engine uses. Pick another name, such as "my_narrator".'),
    ({"T": "label _intro:⏎[4]return"},
     '"_intro" starts with _, and those names are kept for the engine. Remove the _.'),
    ({"T": "label chapter-2:⏎[4]return"},
     '"chapter-2" can\'t be a name. Names use letters, digits, and _, and can\'t start with a '
     "digit, e.g. chapter_2."),
])
def test_name_messages(edit, message):
    parsed = parse_text(template(**edit))
    assert [message_at(e) for e in parsed.errors] == [("9", message)]


@pytest.mark.parametrize("edit,code", [
    ({"T": "label JUMP:⏎[4]return"}, "E60"), ({"T": "define Scene = 1"}, "E60"),
    ({"T": "define Character = 1"}, "E62"), ({"T": "define persistent = 1"}, "E62"),
    ({"T": "label engine:⏎[4]return"}, "E62"),
])
def test_name_codes(edit, code):
    parsed = parse_text(template(**edit))
    assert parsed.codes == [code] and parsed.errors[0].line == 9


def test_e64_omits_an_example_that_is_still_invalid():
    parsed = parse_text(template(T="label 2-x:⏎[4]return"))
    assert parsed.errors[0].message == ('"2-x" can\'t be a name. Names use letters, digits, '
                                        "and _, and can't start with a digit.")


def test_nfkc_names_are_the_same_name():
    parsed = parse_text(template(T='define ｈａｎａ = Character("H2")'))
    assert parsed.errors == []      # E47 is a whole-game check (step 7)
    places = parsed.ctx.collected.define_defs["hana"]
    assert [line for _, line in places] == [1, 9]


def test_non_ascii_names_load():
    parsed = parse_text(template(S="jump 始まり", T="label 始まり:⏎[4]return⏎define café = 1"))
    assert parsed.errors == []
    assert "始まり" in parsed.labels
    assert "café" in parsed.ctx.collected.define_defs


def test_limits_match_the_spec():
    assert limits.SCRIPT_FILE_MAX_BYTES == 16 * 1_048_576
    assert limits.SCRIPT_TOTAL_MAX_BYTES == 256 * 1_048_576
    assert (limits.SCRIPT_MAX_FILES, limits.SCRIPT_MAX_INCLUDE_DEPTH,
            limits.SCRIPT_MAX_BLOCK_DEPTH, limits.SCRIPT_MAX_LINE_CHARS) == (1000, 50, 50, 10_000)
    assert (limits.SCRIPT_MAX_ERRORS, limits.SCRIPT_MAX_ATTRIBUTES) == (50, 4)
    assert (limits.SCRIPT_PY_PIECE_MAX_CHARS, limits.SCRIPT_PY_MAX_LAMBDAS) == (100_000, 64)
    assert (limits.SCRIPT_MAX_STATEMENTS, limits.SCRIPT_MAX_PY_PIECES,
            limits.SCRIPT_MAX_PY_CHARS) == (1_000_000, 250_000, 4_000_000)
    assert (limits.SCRIPT_W03_LIMIT, limits.SCRIPT_TODO_LOG_LIMIT,
            limits.SCRIPT_REPORT_MAX_RECORDS) == (50, 150, 400)
    assert (limits.SCRIPT_LOAD_SLICE_S, limits.SCRIPT_YIELD_LINES) == (0.05, 512)
