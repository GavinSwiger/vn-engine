"""Unknown keys and sections, "did you mean", and line numbers for every key.

The unit part of AC-F01-17, AC-F01-136 (linear-time key scan), the line-number fixtures of
AC-F01-11, and the one-line long-key warning of AC-F01-137 (c). TR-F01-09, TR-F01-57.
"""

import time

import pytest

from engine.core.config import KeyLocator
from tests.core.conftest import fixture_bytes
from tests.fixtures.F01 import config_fixtures as cf

WIDTH_5 = ("config.toml, line {}: [window] width must be a whole number from 640 to 7680, "
           "but found 5")


# --- AC-F01-17 (unit) ---------------------------------------------------------------------

@pytest.mark.parametrize("name, warnings", [
    ("walkthrough_step2.toml",
     ['config.toml, line 6: unknown key [window] fulscreen — did you mean "fullscreen"?']),
    ("unknown_section.toml",
     ["config.toml, line 1: unknown section [windw] — did you mean [window]?"]),
    ("unknown_key_nomatch.toml", ["config.toml, line 2: unknown key [engine] zzzz"]),
    ("toplevel_key.toml",
     ['config.toml, line 1: "title" must be inside a section such as [game]']),
    ("dev_key.toml", ["config.toml, line 2: unknown key [engine] dev"]),
])
def test_unknown_keys_and_sections_warn_and_still_load(load, name, warnings):
    result = load(fixture_bytes(name))
    assert result.errors == []
    assert result.warnings == warnings
    assert result.loaded is True


def test_misspelled_key_does_not_apply(load):
    result = load(fixture_bytes("walkthrough_step2.toml"))
    assert result.config.window.fullscreen is False
    assert result.config.window.icon == "gui/lantern.png"


def test_warnings_come_in_line_order(load):
    result = load("[windw]\nx = 1\n[game]\ntitl = 1\n[engine]\nfpss = 60\n")
    assert result.warnings == [
        "config.toml, line 1: unknown section [windw] — did you mean [window]?",
        'config.toml, line 4: unknown key [game] titl — did you mean "title"?',
        'config.toml, line 6: unknown key [engine] fpss — did you mean "fps"?',
    ]


# --- Line numbers for every way of writing a key (AC-F01-11) ------------------------------

@pytest.mark.parametrize("name, line", [
    ("dotted_key.toml", 2), ("inline_table.toml", 2), ("multiline_then_key.toml", 6)])
def test_line_numbers_for_dotted_inline_and_after_multiline_strings(load, name, line):
    result = load(fixture_bytes(name))
    assert [e.format() for e in result.errors] == [WIDTH_5.format(line)]


def test_multiline_string_containing_a_header_is_not_a_header(load):
    result = load(fixture_bytes("multiline_then_key.toml"))
    assert result.config.game.title == "Paper\n[window]\nLanterns"


def test_array_of_tables_line(load):
    result = load(fixture_bytes("array_of_tables.toml"))
    assert result.errors == []
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("config.toml, line 4: unknown key [window] extra")


# --- AC-F01-136 and AC-F01-137 (c) --------------------------------------------------------

def test_key_scan_runs_in_linear_time(load):
    start = time.perf_counter()
    result = load(cf.generated_longline_multistring())
    assert time.perf_counter() - start < 1.0
    assert result.errors == []
    assert result.warnings == ["config.toml, line 2: unknown key [game] note",
                               "config.toml, line 5: unknown key [engine] zzzz"]


def test_long_unknown_key_is_one_short_line(load):
    result = load(cf.generated_long_unknown_key())
    assert result.warnings == ["config.toml, line 2: unknown key [game] " + "k" * 119 + "…"]


def test_many_unknown_keys_load(load):
    start = time.perf_counter()
    result = load(cf.generated_many_unknown_keys())
    assert time.perf_counter() - start < 10.0
    assert result.errors == []
    assert len(result.warnings) == 60_000
    assert result.warnings[0] == "config.toml, line 2: unknown key [game] k00001"
    assert result.warnings[-1] == "config.toml, line 60001: unknown key [game] k60000"


def test_forged_title_stays_on_one_line_in_messages(load):
    result = load('[game]\ntitle = 5\n"bad\\nkey" = 1\n')
    assert all("\n" not in m for m in result.warnings)
    assert result.warnings == ['config.toml, line 3: unknown key [game] bad\\nkey']


# --- KeyLocator directly ------------------------------------------------------------------

def test_locator_tables_and_keys():
    text = ('# comment [fake]\n'                       # 1
            '[game]\n'                                 # 2
            'title = "x # not a comment"  # comment\n'  # 3
            '"quoted key" = 1\n'                       # 4
            "'literal.key' = 2\n"                      # 5
            '"esc\\u0061ped" = 3\n'                    # 6
            '[ window . sub ]\n'                       # 7
            'a.b.c = 4\n'                              # 8
            'inline = { x = 1, y = { z = 2 } }\n'      # 9
            'arr = [\n'                                # 10
            '  "[not.a.header]",\n'                    # 11
            '  { k = 1 },\n'                           # 12
            ']\n'                                      # 13
            '[["array".tables]]\n'                     # 14
            "ml = '''\n"                               # 15
            'fake = 1\n'                               # 16
            "''''\n"                                   # 17 (content ends with a quote)
            'after = 1\n')                             # 18
    locator = KeyLocator(text)
    assert locator.line_of("fake") is None
    assert locator.line_of("game") == 2
    assert locator.line_of("game", "title") == 3
    assert locator.line_of("game", "quoted key") == 4
    assert locator.line_of("game", "literal.key") == 5
    assert locator.line_of("game", "escaped") == 6
    assert locator.line_of("window") == 7
    assert locator.line_of("window", "sub") == 7
    assert locator.line_of("window", "sub", "a", "b", "c") == 8
    assert locator.line_of("window", "sub", "inline", "x") == 9
    assert locator.line_of("window", "sub", "inline", "y", "z") == 9
    assert locator.line_of("not", "a", "header") is None
    assert locator.line_of("array", "tables") == 14
    assert locator.line_of("array", "tables", "ml") == 15
    assert locator.line_of("array", "tables", "fake") is None
    assert locator.line_of("array", "tables", "after") == 18


def test_locator_multiline_basic_string_with_escapes():
    text = ('[game]\n'
            'title = """a \\"""\n'                     # 2: escaped quotes do not close
            '[window]\n'                               # 3: inside the string
            'b\\\n'                                    # 4: escaped line ending
            'c"""\n'                                   # 5
            'version = "1"\n')                         # 6
    locator = KeyLocator(text)
    assert locator.line_of("window") is None
    assert locator.line_of("game", "version") == 6


def test_locator_crlf_counts_lines_like_lf():
    locator = KeyLocator("[game]\r\ntitle = 1\r\n\r\n[window]\r\nwidth = 2\r\n")
    assert locator.line_of("game", "title") == 2
    assert locator.line_of("window", "width") == 5


def test_locator_ignores_keys_past_4096_characters_but_tracks_strings():
    text = "[game]\n" + "a = 1" + " " * 5000 + '# "\nb = 2\n'
    locator = KeyLocator(text)
    assert locator.line_of("game", "a") == 2
    assert locator.line_of("game", "b") == 3
