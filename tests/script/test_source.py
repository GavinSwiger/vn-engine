"""Decoding and physical lines (F02 checklist step 3; 04-technical.md §7.2).

AC-F02-08 (encodings), AC-F02-09 (line endings, line numbers, columns), and AC-F02-10
(control and line-separator characters), through ``decode_script``, ``LineCursor``, and a
single-file parse. The include-level parts (E99 after E01b/E02, salvaged names feeding the
whole-game checks) are the loader's and checks' (steps 6–7).
"""

import re

import pytest

from engine.script.diagnostics import Diagnostic, DiagnosticSink
from engine.script.nodes import ScriptFile
from engine.script.parser import parse_file
from engine.script.source import LineCursor, decode_script, normalize_line_ends
from engine.script.statements import ParseContext
from tests.script.helpers import FIXTURES, dumps, message_at, parse_text, template

ENCODINGS = FIXTURES / "encodings"
REF = "script/chapter1.vns"
UTF8_FIX = ("Save it as UTF-8 in your editor (in Notepad: File > Save as > Encoding: UTF-8) "
            "and launch again.")


def decode(name: str):
    return decode_script(REF, (ENCODINGS / name).read_bytes())


# --- AC-F02-08 ---------------------------------------------------------------------------

def test_bom_is_removed_and_gives_the_same_program():
    with_bom = (ENCODINGS / "bom.vns").read_bytes()
    assert with_bom.startswith(b"\xef\xbb\xbf")
    decoded = decode("bom.vns")
    assert decoded.problem is None
    plain = decode_script(REF, with_bom[3:])
    assert decoded.text == plain.text
    assert dumps(parse_text(with_bom, REF).nodes) == dumps(parse_text(with_bom[3:], REF).nodes)


def test_bom_does_not_shift_columns():
    body = 'label chapter1:\n    "a\\qb"\n'.encode()
    with_bom = parse_text(b"\xef\xbb\xbf" + body, REF)
    without = parse_text(body, REF)
    assert message_at(with_bom.errors[0]) == message_at(without.errors[0]) == (
        "2:7", '"\\q" is not a special sequence. Write \\\\ for a backslash, \\" for a quote, '
        "or \\n for a new line.")


@pytest.mark.parametrize("name,encoding", [
    ("utf16le.vns", "UTF-16"), ("utf16be.vns", "UTF-16"),
    ("utf32le.vns", "UTF-32"), ("utf32be.vns", "UTF-32"),
])
def test_utf16_and_utf32_are_e01b(name, encoding):
    decoded = decode(name)
    assert decoded.text is None
    code, args, line = decoded.problem
    assert (code, line) == ("E01b", None)
    error = _whole_file_error(code, args)
    assert error == f"script/chapter1.vns is saved as {encoding}. {UTF8_FIX}"


@pytest.mark.parametrize("name,line", [
    ("cp1252_line3.vns", 3), ("cesu_line2.vns", 2), ("overlong_line4.vns", 4),
    ("mixed_endings_ff_line4.vns", 4),
])
def test_invalid_utf8_is_e01a_at_the_line_of_the_first_bad_byte(name, line):
    decoded = decode(name)
    assert decoded.problem == ("E01a", (), line)
    error = _line_error("E01a", (), line)
    assert error == f"script/chapter1.vns, line {line}: this file isn't saved as UTF-8. {UTF8_FIX}"
    # The replacement decode is kept for name salvage only (SR-F02-06).
    assert "�" in decoded.text


def test_e01a_keeps_text_for_name_salvage():
    decoded = decode("salvage/chapter1.vns")
    assert decoded.problem == ("E01a", (), 5)
    assert re.search(r"^label[ \t]+(\w+)[ \t]*:", decoded.text, re.M).group(1) == "chapter1"
    assert re.search(r"^define[ \t]+(\w+)[ \t]*=", decoded.text, re.M).group(1) == "kaito"


@pytest.mark.parametrize("name", [
    "nul_line6.vns", "real.png", "sig_png.vns", "sig_jpeg.vns", "sig_gif87a.vns",
    "sig_gif89a.vns", "sig_zip.vns", "sig_pdf.vns", "sig_gzip.vns", "sig_riff.vns",
    "sig_ogg.vns", "sig_id3.vns", "sig_flac.vns", "sig_7z.vns", "sig_rar.vns", "sig_elf.vns",
])
def test_binary_files_are_e02(name):
    decoded = decode(name)
    assert decoded.text is None
    code, args, line = decoded.problem
    assert (code, line) == ("E02", None)
    assert _whole_file_error(code, args) == (
        "script/chapter1.vns doesn't look like a text file. Script files must be plain text.")


def test_signature_fixtures_are_16_bytes():
    for path in ENCODINGS.glob("sig_*.vns"):
        assert len(path.read_bytes()) == 16, path.name


def test_each_encoding_problem_ends_the_file_in_the_sink():
    sink = DiagnosticSink()
    ctx = ParseContext(sink=sink)
    file = ScriptFile(REF, "chapter1.vns", 1)
    assert sink.add(Diagnostic("E01a", file, 3, None, ()))
    assert not sink.add(Diagnostic("E30a", file, 7, None, ("x", "y")))
    assert sink.error_count == 1
    assert ctx.sink is sink


def _whole_file_error(code, args) -> str:
    return Diagnostic(code, ScriptFile(REF, "chapter1.vns", 1), None, None, args,
                      whole_file=True).to_error().format()


def _line_error(code, args, line) -> str:
    return Diagnostic(code, ScriptFile(REF, "chapter1.vns", 1), line, None,
                      args).to_error().format()


# --- AC-F02-09 ---------------------------------------------------------------------------

VARIANTS = ("lf", "crlf", "cr", "mixed")


def _endings(variant: str) -> bytes:
    return (FIXTURES / "endings" / variant / "main.vns").read_bytes()


def test_endings_fixtures_use_their_line_ends():
    assert b"\r" not in _endings("lf")
    assert _endings("crlf").count(b"\r\n") == 40
    assert b"\n" not in _endings("cr")
    mixed = _endings("mixed")
    assert b"\r\n" in mixed and b"\r" in mixed.replace(b"\r\n", b"") and b"\n" in mixed


def test_all_line_endings_give_the_same_program():
    dumps_by_variant = set()
    for variant in VARIANTS:
        parsed = parse_text(_endings(variant))
        assert parsed.errors == [], (variant, parsed.messages)
        dumps_by_variant.add(dumps(parsed.nodes))
    assert len(dumps_by_variant) == 1
    parsed = parse_text(_endings("lf"))
    narration = parsed.labels["start"].block[4]
    assert (narration.line, narration.end_line) == (12, 13)
    items = parsed.labels["start"].block[3]
    assert (items.line, items.end_line) == (8, 11)


@pytest.mark.parametrize("variant", VARIANTS)
def test_line_numbers_are_the_same_for_every_line_ending(variant):
    data = _endings(variant).replace(b"call stall", b"jmup bridge")
    parsed = parse_text(data)
    assert parsed.messages[0].startswith("script/main.vns, line 23: ")
    assert parsed.codes == ["E30a"]


def test_emoji_counts_one_column():
    error = parse_text(template(S='"😀\\q"')).errors[0]
    assert (error.code, error.line, error.column) == ("E52", 5, 7)
    tabbed = template(S='"😀\\q"').replace("    ", "\t")
    error = parse_text(tabbed).errors[0]
    assert (error.code, error.line, error.column) == ("E52", 5, 4)


def test_normalize_line_ends():
    assert normalize_line_ends("a\r\nb\rc\nd") == "a\nb\nc\nd"
    assert normalize_line_ends("a\r\r\nb") == "a\n\nb"


# --- AC-F02-10 ---------------------------------------------------------------------------

E03 = ("this line contains an invisible character ({cp}). Delete it; it probably came from "
       "copied text.")
E04 = ("this line contains a hidden line-separator character ({cp}). Delete it, and press "
       "Enter if you want a new line there.")


@pytest.mark.parametrize("edit,where,cp", [
    ({"S": '"Hi{U+0007}"'}, "5:8", "U+0007"),
    ({"T": "# note{U+FEFF}"}, "9:7", "U+FEFF"),
    ({"T": "# a{U+200B}b"}, "9:4", "U+200B"),
])
def test_e03(edit, where, cp):
    parsed = parse_text(template(**edit))
    assert [message_at(e) for e in parsed.errors] == [(where, E03.format(cp=cp))]


def test_e03_for_a_second_bom():
    data = b"\xef\xbb\xbf" + "﻿".encode() + template().encode()
    parsed = parse_text(data)
    assert [message_at(e) for e in parsed.errors] == [("1:1", E03.format(cp="U+FEFF"))]


@pytest.mark.parametrize("char", [" ", " ", "\u0085"])
def test_e04(char):
    parsed = parse_text(template(S=f'"one{char}two"'))
    cp = f"U+{ord(char):04X}"
    assert [message_at(e) for e in parsed.errors] == [("5:9", E04.format(cp=cp))]


def test_zero_width_and_tab_are_kept_inside_text():
    parsed = parse_text(template(S='"a{U+FEFF}b{U+200B}c"'))
    assert parsed.errors == []
    assert parsed.labels["start"].block[1].text == "a﻿b​c"
    parsed = parse_text(template(S='"tab{TAB}inside"'))
    assert parsed.errors == []
    assert parsed.labels["start"].block[1].text == "tab\tinside"


def test_control_characters_in_blank_lines_are_reported():
    parsed = parse_text(template(S="\x1f"))
    assert [message_at(e) for e in parsed.errors] == [("5:5", E03.format(cp="U+001F"))]


# --- LineCursor ----------------------------------------------------------------------------

def test_line_cursor_peeks_and_numbers_lines():
    cursor = LineCursor("a\n\nb\x07c\n")
    assert cursor.peek().text == "a"
    first = cursor.next()
    assert (first.number, first.text, first.control) == (1, "a", None)
    assert cursor.next().text == ""
    third = cursor.next()
    assert (third.number, third.text, third.control) == (3, "b\x07c", (2, "\x07"))
    assert cursor.next() is None
    assert cursor.peek() is None


def test_line_cursor_reports_the_first_control_per_line():
    cursor = LineCursor("\x01\x02\nok\n\x03")
    assert cursor.next().control == (1, "\x01")
    assert cursor.next().control is None
    assert cursor.next().control == (1, "\x03")


def test_line_cursor_is_lazy_for_many_empty_lines():
    text = "\n" * 1_000_000
    cursor = LineCursor(text)
    count = 0
    while cursor.next() is not None:
        count += 1
    assert count == 1_000_000


def test_parse_file_of_empty_lines_produces_nothing():
    ctx = ParseContext(sink=DiagnosticSink())
    assert parse_file(ScriptFile("script/main.vns", "main.vns", 0), "\n\n\n", ctx) == []
    assert ctx.sink.error_count == 0
