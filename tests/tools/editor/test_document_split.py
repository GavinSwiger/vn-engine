"""F58 P0 follow-up: ``document._split_lines`` takes C-level string calls when a file has one
line-ending kind, and gives exactly what the per-line read gives."""

import random

from engine.tools.editor.document import _split_lines, _split_lines_slow

PIECES = ("a", "bc", " ", "é", "\t", "\n", "\r\n", "\r", "\n\n", "\r\n\r\n")


def test_fast_split_matches_the_per_line_read():
    rng = random.Random(58)
    cases = ["", "\n", "\r\n", "\r", "a", "a\n", "a\r\n", "a\n\n", "a\r\n\r\n", "\r\r\n",
             "a\nb", "a\r\nb\r\n", "a\rb\r", "a\nb\r\n"]
    for _ in range(5000):
        cases.append("".join(rng.choice(PIECES) for _ in range(rng.randint(0, 12))))
    for text in cases:
        assert _split_lines(text) == _split_lines_slow(text), repr(text)


def test_one_ending_kind_takes_no_line_lists():
    assert _split_lines("a\nb\n") == ("\n", True, "a\nb", None, None)
    assert _split_lines("a\r\nb") == ("\r\n", False, "a\nb", None, None)
    newline, _final, _body, lines, endings = _split_lines("a\nb\r\n")
    assert lines == ["a", "b"] and endings == ["\n", "\r\n"]
