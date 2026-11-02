"""Quoted text, comments, and hidden characters (F02 checklist step 4; 04-technical.md
§7.3).

AC-F02-11 (text-direction controls), AC-F02-12 (invisible characters in names), AC-F02-13
(any Unicode reaches the engine exactly), AC-F02-14 (comments), AC-F02-15 (blank lines and
whitespace), AC-F02-18 (escapes, joining, continued text), AC-F02-19 (text errors), and
AC-F02-20 (curly and single quotes), through a single-file parse of template T.
"""

import pytest

from engine.script.diagnostics import DiagnosticSink
from engine.script.nodes import If, PythonLine, Say
from engine.script.statements import ParseContext
from tests.script.helpers import FIXTURES, dumps, message_at, parse_text, template

RAW_BIDI = [chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))]


def say(parsed, index: int = 1) -> Say:
    node = parsed.labels["start"].block[index]
    assert isinstance(node, Say)
    return node


# --- AC-F02-11 ---------------------------------------------------------------------------

E03B = ("this line contains a hidden text-direction character ({cp}), which can make code "
        "look different from what runs. Delete it; it is allowed only inside dialogue and "
        "narration.")
STR = " In a Python string, write \\u{hex} instead."


@pytest.mark.parametrize("edit,where,cp,in_string", [
    ({"T": "# note {U+202E}"}, "9:8", "202E", False),
    ({"T": 'include "a{U+202E}.vns"'}, "9:11", "202E", False),
    ({"S": '$ x = "a{U+202E}b"'}, "5:13", "202E", True),
    ({"S": "$ x = 1  # {U+2066}"}, "5:16", "2066", False),
    ({"S": 'if flag == "{U+202E}":⏎[8]"A."'}, "5:17", "202E", True),
    ({"T": 'define title = "{U+2067}"'}, "9:17", "2067", True),
])
def test_bidi_controls_outside_text_are_e03b(edit, where, cp, in_string):
    parsed = parse_text(template(**edit))
    expected = E03B.format(cp=f"U+{cp}") + (STR.format(hex=cp.lower()) if in_string else "")
    assert [message_at(e) for e in parsed.errors] == [(where, expected)]
    for message in parsed.messages:
        assert not any(char in message for char in RAW_BIDI)


@pytest.mark.parametrize("row,text", [
    ('hana "{U+202B}שלום{U+202C}"', "‫שלום‬"),
    ('"{U+2067}مرحبا{U+2069}"', "⁧مرحبا⁩"),
    ('"abc{U+200F}"', "abc‏"),
])
def test_bidi_controls_inside_text_are_kept(row, text):
    parsed = parse_text(template(S=row))
    assert parsed.errors == []
    assert say(parsed).text == text


# --- AC-F02-12 ---------------------------------------------------------------------------

E64B = ('the name "{name}" contains an invisible character ({cp}), so it looks like a '
        "different name. Retype the name without it.")


@pytest.mark.parametrize("edit,where,name,cp", [
    ({"T": 'define hana{U+3164} = Character("H")'}, "9:12", "hana\\u3164", "U+3164"),
    ({"T": "label a{U+FE0E}:⏎[4]return"}, "9:8", "a\\ufe0e", "U+FE0E"),
    ({"S": "$ x{U+034F} = 1"}, "5:8", "x\\u034f", "U+034F"),
    ({"S": 'hana{U+180B} "Hi"'}, "5:9", "hana\\u180b", "U+180B"),
    ({"S": 'hana sad{U+FE0F} "Hi"'}, "5:13", "sad\\ufe0f", "U+FE0F"),
])
def test_invisible_characters_in_names_are_e64b(edit, where, name, cp):
    parsed = parse_text(template(**edit))
    assert [message_at(e) for e in parsed.errors] == [(where, E64B.format(name=name, cp=cp))]


def test_invisible_supplementary_selector_names_its_code_point():
    parsed = parse_text(template(T="label b{U+E0100}:⏎[4]return"))
    assert len(parsed.errors) == 1
    where, message = message_at(parsed.errors[0])
    assert where == "9:8" and "(U+E0100)" in message
    assert "\U000e0100" not in message


@pytest.mark.parametrize("cp", [0x115F, 0x1160, 0x17B4, 0x17B5, *range(0x180C, 0x1810), 0xFFA0,
                                *range(0xFE00, 0xFE0E)])
def test_every_listed_invisible_character_is_e64b(cp):
    parsed = parse_text(template(T=f"define kai{chr(cp)} = 1"))
    assert len(parsed.errors) == 1, parsed.messages
    error = parsed.errors[0]
    assert (error.code, error.line, error.column) == ("E64b", 9, 11)
    assert f"(U+{cp:04X})" in error.message


@pytest.mark.parametrize("row", ['$ s = "❤{U+FE0F}"', 'hana "❤{U+FE0F}"'])
def test_variation_selectors_inside_strings_are_fine(row):
    assert parse_text(template(S=row)).errors == []


# --- AC-F02-13 ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Café — “quoted” ‘single’ … naïve", "Привет, мир", "日本語のテキスト、です。",
    "مرحبا بالعالم", "שלום", "👨‍👩‍👧 ❤️ 🏳️‍🌈", "é", "می‌خواهم",
])
def test_any_unicode_is_kept_exactly(text):
    parsed = parse_text(template(S=f'"{text}"'))
    assert parsed.errors == []
    assert say(parsed).text == text


def test_bidi_in_dialogue_is_kept_exactly():
    parsed = parse_text(template(S='hana "{U+202B}שלום{U+202C} — ok"'))
    assert parsed.errors == []
    assert say(parsed).text == "‫שלום‬ — ok"
    assert len("é") == 2


# --- AC-F02-14 ---------------------------------------------------------------------------

def test_hash_inside_text_is_text():
    parsed = parse_text(template(S='hana "I\'m #1!"  # note'))
    assert parsed.errors == []
    assert say(parsed).text == "I'm #1!"


@pytest.mark.parametrize("line5", ["# commented out", "[12]# deeper", "[2]# shallower"])
def test_comment_lines_are_ignored_at_any_indentation(line5):
    parsed = parse_text(template(replace={5: line5}))
    assert parsed.errors == []
    kinds = [type(s).__name__ for s in parsed.labels["start"].block]
    assert kinds == ["Say", "Jump"]


def test_comment_line_does_not_open_or_close_a_block():
    parsed = parse_text(template(S='if trust > 0:⏎[2]# odd comment⏎[8]"A."'))
    assert parsed.errors == []
    node = parsed.labels["start"].block[1]
    assert isinstance(node, If) and [s.text for s in node.branches[0].block] == ["A."]


def test_comment_and_blank_lines_between_branches():
    parsed = parse_text(template(S='if trust > 0:⏎[8]"A."⏎# between⏎⏎[4]else:⏎[8]"B."'))
    assert parsed.errors == []
    node = parsed.labels["start"].block[1]
    assert isinstance(node, If) and [b.keyword for b in node.branches] == ["if", "else"]


def test_comment_lines_continue_python_brackets():
    parsed = parse_text(template(S="$ x = (1,⏎# at column 1⏎⏎[8]2)"))
    assert parsed.errors == []
    node = parsed.labels["start"].block[1]
    assert isinstance(node, PythonLine) and len(node.py.source.split("\n")) == 4


def test_deeper_hash_line_inside_open_quote_is_text():
    parsed = parse_text(template(S='"one⏎[8]# not a comment"'))
    assert parsed.errors == []
    assert say(parsed).text == "one # not a comment"


def test_tab_comment_in_space_file_is_not_e10():
    parsed = parse_text(template(replace={5: "[t]# tab comment"}))
    assert parsed.errors == []


def test_todo_comments_are_collected_when_asked():
    ctx = ParseContext(sink=DiagnosticSink(), collect_todos=True)
    text = template(S="# TODO: write this⏎[4]# todo⏎[4]# Todoist is not one⏎[4]hana \"Hi\"  # TODO-2")
    parse_text(text, ctx=ctx)
    assert [(line, body) for _, line, body in ctx.collected.todos] == [
        (5, "TODO: write this"), (6, "todo"), (8, "TODO-2")]


# --- AC-F02-15 (with the example story standing in for the compat corpus) ------------------

def _lanterns() -> str:
    return (FIXTURES / "lanterns" / "chapter1.vns").read_text(encoding="utf-8")


@pytest.mark.parametrize("variant", [
    lambda t: "\n\n".join(t.split("\n")),
    lambda t: "\n".join(line + " \t " for line in t.split("\n")),
    lambda t: "\n".join(line + "\n  \t　" for line in t.split("\n")),
    lambda t: t.rstrip("\n"),
    lambda t: t + "\n" * 5,
], ids=["blank-after-each", "trailing-space", "whitespace-lines", "no-final-break", "extra-breaks"])
def test_whitespace_never_changes_the_program(variant):
    original = parse_text(_lanterns(), "script/chapter1.vns")
    assert original.errors == []
    changed = parse_text(variant(_lanterns()), "script/chapter1.vns")
    assert changed.errors == [], changed.messages
    assert dumps(changed.nodes, positions=False) == dumps(original.nodes, positions=False)


def test_empty_file_gives_nothing():
    parsed = parse_text("", "script/empty.vns")
    assert parsed.nodes == [] and parsed.errors == []


# --- AC-F02-18 ---------------------------------------------------------------------------

@pytest.mark.parametrize("row,speaker,attributes,text,lines", [
    ('"She said \\"hi\\"."', None, (), 'She said "hi".', (5, 5)),
    ('"a\\\\b"', None, (), "a\\b", (5, 5)),
    ('"one\\ntwo"', None, (), "one\ntwo", (5, 5)),
    ('"joined\\⏎[8]here"', None, (), "joinedhere", (5, 6)),
    ('"Paper lanterns drifted past us one by one, each carrying⏎[8]somebody\'s wish '
     'downstream."', None, (),
     "Paper lanterns drifted past us one by one, each carrying somebody's wish downstream.",
     (5, 6)),
    ('"a   ⏎⏎[12]b"', None, (), "a b", (5, 7)),
    ('""', None, (), "", (5, 5)),
    ('"  spaced  "', None, (), "  spaced  ", (5, 5)),
    ('"{b}bold{/b} {{x [not a var]"', None, (), "{b}bold{/b} {{x [not a var]", (5, 5)),
    ('"It\'s Hana\'s — “really”"', None, (), "It's Hana's — “really”", (5, 5)),
    ('hana"Hi"', "hana", (), "Hi", (5, 5)),
    ('hana   worried   "Hm?"', "hana", ("worried",), "Hm?", (5, 5)),
    ('hana a b c 2b "Hi"', "hana", ("a", "b", "c", "2b"), "Hi", (5, 5)),
])
def test_escapes_joining_and_continued_text(row, speaker, attributes, text, lines):
    parsed = parse_text(template(S=row))
    assert parsed.errors == [], parsed.messages
    node = say(parsed)
    assert (node.speaker, node.attributes, node.text) == (speaker, attributes, text)
    assert (node.line, node.end_line) == lines


# --- AC-F02-19 ---------------------------------------------------------------------------

E52 = ('"\\{seq}" is not a special sequence. Write \\\\ for a backslash, \\" for a quote, or '
       "\\n for a new line.")


@pytest.mark.parametrize("edit,where,message", [
    ({"S": '"a\\qb"'}, "5:7", E52.format(seq="q")),
    ({"S": '"a\\{b"'}, "5:7", E52.format(seq="{") + " To show a {, write {{."),
    ({"S": 'hana "Say "hi" to me."'}, "5:16",
     'this line has more after the closing quote: hi" to me." Write a quote inside the text '
     'as \\".'),
    ({"S": '"never closed'}, "5:5", 'this quote is never closed. Add " at the end of the text.'),
    ({"T": 'label x:⏎[4]"open'}, "10:5",
     'this quote is never closed. Add " at the end of the text.'),
    ({"S": '"Hi”'}, "5:5", "this quote is never closed: the text ends with a curly quote ”. "
                           'End it with a straight quote " instead.'),
    ({"S": '"Go left":'}, "5", "this line of text ends with :, which only menu choices do. "
                               "Remove the :, or put the choice in a menu: block."),
])
def test_text_errors(edit, where, message):
    parsed = parse_text(template(**edit))
    assert [message_at(e) for e in parsed.errors] == [(where, message)]


def test_unclosed_quote_resumes_at_the_next_line():
    parsed = parse_text(template(S='"never closed'))
    assert parsed.codes == ["E54"]
    assert [type(s).__name__ for s in parsed.labels["start"].block] == ["Say", "Jump"]


def test_leftmost_error_wins_on_a_line():
    parsed = parse_text(template(S='"a\\q" b "c'))
    assert parsed.codes == ["E52"]


# --- AC-F02-20 ---------------------------------------------------------------------------

E50 = ("this line uses curly quotes {pair} around the text. Put the text between straight "
       'quotes "like this". Curly quotes inside the text are fine.')
E51 = ('text goes between double quotes, not single quotes. Write "like this"; apostrophes '
       "inside need no change.")


@pytest.mark.parametrize("row,where,pair", [
    ("hana “Hi”", "5:10", "“ ”"), ("“Hi”", "5:5", "“ ”"), ("„Hi“", "5:5", "„ “"),
    ("‟Hi”", "5:5", "‟ ”"),
])
def test_curly_quotes_are_e50(row, where, pair):
    parsed = parse_text(template(S=row))
    assert [message_at(e) for e in parsed.errors] == [(where, E50.format(pair=pair))]


@pytest.mark.parametrize("row,pair", [
    ("″Hi″", "″ ″"), ("＂Hi＂", "＂ ＂"), ("«Hi»", "« »"), ("「Hi」", "「 」"), ("『Hi』", "『 』"),
])
def test_other_quote_marks_are_e50_naming_the_pair(row, pair):
    parsed = parse_text(template(S=row))
    assert len(parsed.errors) == 1
    where, message = message_at(parsed.errors[0])
    assert parsed.codes == ["E50"] and where == "5:5"
    assert pair in message and f"Quote marks such as {pair} inside are fine." in message


@pytest.mark.parametrize("row,where", [("hana 'Hi'", "5:10"), ("‘Hi’", "5:5"), ("’Hi’", "5:5")])
def test_single_quotes_are_e51(row, where):
    parsed = parse_text(template(S=row))
    assert [message_at(e) for e in parsed.errors] == [(where, E51)]


def test_quote_marks_inside_straight_quotes_are_text():
    parsed = parse_text(template(S='hana "He said “hi” and «bye»"'))
    assert parsed.errors == []
    assert say(parsed).text == "He said “hi” and «bye»"
