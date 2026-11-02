"""TOML syntax errors give line, column, and plain language (§7.2.2).

The unit part of AC-F01-15 (its error-screen part needs Step 8), every §5.4 fixture with
its exact ``format()``, and implementation note I-1 (only an unterminated string is
reported as a missing quote).
"""

import pytest

from tests.core.conftest import fixture_bytes

INVALID_VALUE = ('config.toml, line 4, column 9: expected a value after "=". '
                 'Text values need quotes: title = "My Game"')

SYNTAX_FIXTURES = [
    ("syntax_invalid_value.toml", INVALID_VALUE, 4, 9),
    ("crlf_invalid_value.toml", INVALID_VALUE, 4, 9),
    ("syntax_missing_equals.toml",
     'config.toml, line 2, column 7: expected "=" after the key name. '
     "Write settings as key = value", 2, 7),
    ("syntax_unclosed_array.toml",
     'config.toml, line 3, column 1: a "[" or "{" is never closed', 3, 1),
    ("syntax_duplicate_key.toml",
     "config.toml, line 3, column 13: this key or section is written twice", 3, 13),
    ("syntax_duplicate_table.toml",
     "config.toml, line 3, column 8: this key or section is written twice", 3, 8),
    ("syntax_unterminated_string.toml",
     "config.toml, line 2, column 24: text is missing its closing quote", 2, 24),
    ("syntax_invalid_statement.toml",
     "config.toml, line 2, column 1: this line is not a valid setting. "
     "Write settings as key = value", 2, 1),
    ("syntax_other.toml",
     "config.toml, line 1, column 6: Expected ']' at the end of a table declaration", 1, 6),
    ("syntax_eof.toml",
     'config.toml, line 2, column 8: expected a value after "=". '
     'Text values need quotes: title = "My Game"', 2, 8),
    ("nul_in_string.toml",
     "config.toml, line 2, column 11: this text contains a character that is not "
     "allowed (U+0000)", 2, 11),
]


@pytest.mark.parametrize("name, expected, line, column", SYNTAX_FIXTURES)
def test_syntax_fixture(load, name, expected, line, column):
    result = load(fixture_bytes(name))
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.format() == expected
    assert (error.file, error.line, error.column) == ("config.toml", line, column)
    assert result.loaded is False
    assert result.warnings == []


@pytest.mark.parametrize("text, expected", [
    # The three seeded author mistakes of the walkthroughs.
    ('[game]\ntitle = Paper Lanterns\n',
     'config.toml, line 2, column 9: expected a value after "=". '
     'Text values need quotes: title = "My Game"'),
    ('[window]\nwidth = 1280\n[window]\nheight = 720\n',
     "config.toml, line 3, column 8: this key or section is written twice"),
    ('[game]\ntitle = "Paper\n',
     "config.toml, line 2, column 15: text is missing its closing quote"),
    # An unterminated string with CRLF endings is still a missing quote.
    ('[game]\r\ntitle = "abc\r\nx = 1\r\n',
     "config.toml, line 2, column 13: text is missing its closing quote"),
    # An unterminated multi-line string reaches the end of the document.
    ('[game]\ntitle = """abc\n',
     "config.toml, line 2, column 15: text is missing its closing quote"),
    # Other illegal characters name the code point (I-1).
    ('[game]\ntitle = "a\x7fb"\n',
     "config.toml, line 2, column 11: this text contains a character that is not "
     "allowed (U+007F)"),
    ('[game]\ntitle = "a\x1bb"\n',
     "config.toml, line 2, column 11: this text contains a character that is not "
     "allowed (U+001B)"),
    # An error at the end of a one-line file without a newline.
    ("title =", 'config.toml, line 1, column 8: expected a value after "=". '
                'Text values need quotes: title = "My Game"'),
])
def test_other_syntax_errors(load, text, expected):
    result = load(text)
    assert [e.format() for e in result.errors] == [expected]


def test_unmapped_tomllib_messages_are_passed_through_escaped(load):
    result = load("[game]\n# bad \x01 comment\n")
    (error,) = result.errors
    assert error.format().startswith("config.toml, line 2, column 7: ")
    assert "\x01" not in error.format()
