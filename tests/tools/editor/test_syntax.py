"""Syntax coloring, the start label above the cursor, and the indent unit, headless
(F44 ``04`` §7.6, ``03`` §1.2, PR-F44-05, 07, 09). The ``color_spans`` rows of AC-F44-22,
the buffer-B rows of AC-F44-25, the syntax colors of AC-F44-21, indent units for AC-F44-23."""

import random

import pytest

from engine.tools.editor.syntax import (
    DEFAULT_INDENT,
    LABEL_LINE,
    PLAIN_COLOR,
    SYNTAX_TAGS,
    TAG_COLORS,
    TAG_COMMENT,
    TAG_KEYWORD,
    TAG_LABEL,
    TAG_PYTHON,
    TAG_QUOTE,
    TAG_SPEAKER,
    TAG_TEXT_TAG,
    color_spans,
    indent_unit,
    label_above,
)

C, K, L, S, Q, T, P = (TAG_COMMENT, TAG_KEYWORD, TAG_LABEL, TAG_SPEAKER, TAG_QUOTE,
                       TAG_TEXT_TAG, TAG_PYTHON)


def pieces(line: str) -> list[tuple[str, str]]:
    return [(line[start:end], tag) for start, end, tag in color_spans(line)]


def check_well_formed(line: str) -> None:
    spans = color_spans(line)
    previous_end = 0
    for start, end, tag in spans:
        assert 0 <= previous_end <= start < end <= len(line), (line, spans)
        assert tag in SYNTAX_TAGS
        previous_end = end


# --- AC-F44-22 ------------------------------------------------------------------------------

SPAN_ROWS = [
    ("# TODO", [("# TODO", C)]),
    ("label club_poem:", [("label", K), ("club_poem", L)]),
    ("    jump club_poem  # go", [("jump", K), ("club_poem", L), ("# go", C)]),
    ('sayori "It\'s {b}nice{/b}." # TODO',
     [("sayori", S), ('"It\'s ', Q), ("{b}", T), ("nice", Q), ("{/b}", T), ('."', Q),
      ("# TODO", C)]),
    ('hana pout "Hi"', [("hana pout", S), ('"Hi"', Q)]),
    ("    if sayo_points >= 1:", [("if", K)]),
    ("    $ sayo_points += 1  # note", [("$ sayo_points += 1", P), ("# note", C)]),
    ('$ s = "a # b"', [('$ s = "a # b"', P)]),
    ('"He said \\"#1\\""', [('"He said \\"#1\\""', Q)]),
    ('"Unclosed {b}text', [('"Unclosed ', Q), ("{b}", T), ("text", Q)]),
    ("", []),
    ("    ", []),
    ('    "Opening line."', [('"Opening line."', Q)]),
    ("    call aside", [("call", K), ("aside", L)]),
    ("labels = 3", []),                                   # not a statement word
    ("show eileen happy", [("show", K)]),
    ('    $ x = \'it\'\'s # not\'  # yes', [("$ x = 'it''s # not'", P), ("# yes", C)]),
    ('"a {{b}} c"', [('"a {{b}} c"', Q)]),                 # {{ is a literal brace
    ('"# not a comment" # comment', [('"# not a comment"', Q), ("# comment", C)]),
    ('# "quoted {b}" in a comment', [('# "quoted {b}" in a comment', C)]),
    ("x = 1 # c", [("# c", C)]),                          # no quote: no speaker
    ('"tail \\', [('"tail \\', Q)]),
    # AC-F45-59 (2026-11-02): value tags, marks, and closing tags color whole.
    ('hana "{color=#9a1c14}red{/color}"',
     [("hana", S), ('"', Q), ("{color=#9a1c14}", T), ("red", Q), ("{/color}", T), ('"', Q)]),
    ('"{speed=instant}a{/speed}{pause=0.6}b{pause}c{var=name}{next}"',
     [('"', Q), ("{speed=instant}", T), ("a", Q), ("{/speed}", T), ("{pause=0.6}", T),
      ("b", Q), ("{pause}", T), ("c", Q), ("{var=name}", T), ("{next}", T), ('"', Q)]),
    ('"{size=1.5}{i}x{/i}{/size}"',
     [('"', Q), ("{size=1.5}", T), ("{i}", T), ("x", Q), ("{/i}", T), ("{/size}", T),
      ('"', Q)]),
]


def test_color_spans_table():
    for line, expected in SPAN_ROWS:
        assert pieces(line) == expected, line
        check_well_formed(line)


def test_random_lines_never_raise():
    rng = random.Random(44)
    alphabet = 'abc xyz_09 \t"\'#{}$\\:=.()é😀'
    words = ["label ", "jump ", "call ", "$ ", "if ", "{b}", "{/b}", '\\"', "{{", "}}"]
    for _ in range(10_000):
        parts = [rng.choice(words) if rng.random() < 0.2 else rng.choice(alphabet)
                 for _ in range(rng.randint(0, 40))]
        check_well_formed("".join(parts))


# --- Colors (03 §1.2; AC-F44-21's syntax colors) ---------------------------------------------

def luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_seven_tags_use_the_ui_colors():
    """03 §1.2 as amended 2026-11-02 (VS Code Dark+; comments nudged from ``#6A9955``)."""
    assert TAG_COLORS == {
        C: "#74A160", K: "#569CD6", L: "#DCDCAA", S: "#4EC9B0", Q: "#CE9178",
        T: "#C586C0", P: "#9CDCFE"}
    assert set(SYNTAX_TAGS) == set(TAG_COLORS) and len(SYNTAX_TAGS) == 7
    assert PLAIN_COLOR == "#D4D4D4"


# The editor, the current-line highlight, and the jump highlight. Selected text is drawn in
# PLAIN_COLOR, so the selection is checked with the window's colors (AC-F44-21).
def test_syntax_colors_are_readable_on_every_background():
    for background in ["#1E1E1E", "#2A2D2E", "#322E16"]:
        for color in [PLAIN_COLOR, *TAG_COLORS.values()]:
            assert contrast(color, background) >= 4.5, (color, background)


# --- AC-F44-25 buffer B: the start label above the cursor ------------------------------------

BUFFER_B = ["# label fake:", "default x = 0", "label club_poem:", '    "A."',
            "    label inner:", '"label quoted:"', "label\tafter_tab:", '    "B."']


def test_label_above_buffer_b():
    found = [label_above(BUFFER_B, line) for line in range(1, 9)]
    assert found == [None, None, "club_poem", "club_poem", "club_poem", "club_poem",
                     "after_tab", "after_tab"]


def test_label_above_stops_at_the_nearest_label_line():
    lines = ["label good:", "label 9bad:", '    "x"']
    assert label_above(lines, 3) is None          # same rule as the window's Text.search
    assert label_above([], 1) is None
    assert label_above(["label a:"], 5) == "a"


def test_label_line_matches_at_column_zero_only():
    assert LABEL_LINE.match("label club_poem:").group(1) == "club_poem"
    assert LABEL_LINE.match("label\tafter_tab:").group(1) == "after_tab"
    assert LABEL_LINE.match("    label inner:") is None
    assert LABEL_LINE.match("label 1st:") is None


# --- Indent unit (PR-F44-07, AC-F44-23) ------------------------------------------------------

INDENT_ROWS = [
    ("", DEFAULT_INDENT),
    ('label a:\n"x"\n', "    "),
    ("label a:\n    if x:\n        'y'\n", "    "),
    ("label a:\n  'x'\n", "  "),
    ("label a:\n\tif x:\n\t\t'y'\n", "\t"),
    ("label a:\n        # an indented comment\n\n   \n  'x'\n", "  "),
    ("label a:\r\n   'x'\r\n", "   "),
    ("label a:\n" + " " * 12 + "'x'\n", " " * 8),
]


def test_indent_unit():
    assert DEFAULT_INDENT == "    "
    for text, unit in INDENT_ROWS:
        assert indent_unit(text) == unit, text
