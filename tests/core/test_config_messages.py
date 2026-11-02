"""Exact config error messages: phrases, value descriptions, and the quotes hint.

AC-F01-11 (one bad value, exact ``format()``), AC-F01-135 (short messages, safe hints),
TR-F01-58 (every §7.2.4 phrase).
"""

import datetime

import pytest

from engine.core.config import describe
from engine.core.config_schema import (
    AppId,
    Bool,
    Choice,
    HexColor,
    IconRef,
    IntRange,
    Text,
    ValueProblem,
)
from tests.core.conftest import value_bytes

WIDTH = "config.toml, line 2: [window] width must be a whole number from 640 to 7680, but found "
HEIGHT = "config.toml, line 2: [window] height must be a whole number from 360 to 4320, but found "
FPS = "config.toml, line 2: [engine] fps must be a whole number from 30 to 240, but found "
CACHE = "config.toml, line 2: [engine] cache_mb must be a whole number from 64 to 8192, but found "
FULLSCREEN = "config.toml, line 2: [window] fullscreen must be true or false, but found "
LETTERBOX = ('config.toml, line 2: [window] letterbox_color must be a color written as '
             '"#RRGGBB", for example "#000000", but found ')
SCALE_FILTER = ('config.toml, line 2: [window] scale_filter must be one of "smooth", "pixel", '
                "but found ")
LOG_LEVEL = ('config.toml, line 2: [engine] log_level must be one of "debug", "info", '
             '"warning", "error", but found ')
TITLE = ("config.toml, line 2: [game] title must be text with at least one visible "
         "character, but found ")
VERSION = "config.toml, line 2: [game] version must be text, but found "
ICON = ('config.toml, line 2: [window] icon must be text: a path to a .png file in the game '
        'folder, for example "gui/icon.png", but found ')

# AC-F01-11: fixture → exact format()
BAD_VALUES = [
    ("bad_width_text.toml", WIDTH + 'the text "big"'),
    ("bad_width_quoted_number.toml", WIDTH + 'the text "1920". Remove the quotes.'),
    ("bad_width_bool.toml", WIDTH + "true"),
    ("bad_width_float.toml", WIDTH + "1280.0"),
    ("bad_width_639.toml", WIDTH + "639"),
    ("bad_width_7681.toml", WIDTH + "7681"),
    ("bad_height_359.toml", HEIGHT + "359"),
    ("bad_height_4321.toml", HEIGHT + "4321"),
    ("bad_fps_29.toml", FPS + "29"),
    ("bad_fps_241.toml", FPS + "241"),
    ("bad_fps_quoted.toml", FPS + 'the text "60". Remove the quotes.'),
    ("bad_cache_mb_63.toml", CACHE + "63"),
    ("bad_cache_mb_8193.toml", CACHE + "8193"),
    ("bad_width_list.toml", WIDTH + "a list"),
    ("bad_width_table.toml", WIDTH + "a section"),
    ("bad_width_date.toml", WIDTH + "a date or time"),
    ("bad_fullscreen_quoted.toml", FULLSCREEN + 'the text "true". Remove the quotes.'),
    ("bad_fullscreen_yes.toml", FULLSCREEN + 'the text "yes"'),
    ("bad_fullscreen_1.toml", FULLSCREEN + "1"),
    ("bad_letterbox_red.toml", LETTERBOX + 'the text "red"'),
    ("bad_letterbox_short.toml", LETTERBOX + 'the text "#12345"'),
    ("bad_letterbox_nonhex.toml", LETTERBOX + 'the text "#GGGGGG"'),
    ("bad_scale_filter.toml", SCALE_FILTER + 'the text "nearest"'),
    ("bad_log_level_verbose.toml", LOG_LEVEL + 'the text "verbose"'),
    ("bad_log_level_upper.toml", LOG_LEVEL + 'the text "INFO"'),
    ("bad_title_empty.toml", TITLE + 'the text ""'),
    ("bad_title_blank.toml", TITLE + 'the text "   "'),
    ("bad_title_int.toml", TITLE + "5"),
    ("bad_version_float.toml", VERSION + "1.0"),
    ("bad_icon_int.toml", ICON + "5"),
    ("bad_icon_bool.toml", ICON + "true"),
    ("bad_scale_filter_long.toml", SCALE_FILTER + 'the text "' + "x" * 39 + '…"'),
    ("bad_width_quoted_key.toml", WIDTH + 'the text "big"'),
]


@pytest.mark.parametrize("name, expected", BAD_VALUES)
def test_one_bad_value_gives_the_exact_message(load, name, expected):
    result = load(value_bytes(name))
    assert len(result.errors) == 1
    error = result.errors[0]
    assert error.format() == expected
    assert (error.file, error.line, error.column) == ("config.toml", 2, None)
    assert result.warnings == []
    assert result.loaded is False


# --- AC-F01-135 ---------------------------------------------------------------------------

SHORT_MESSAGES = [
    ("long_quoted_number.toml", WIDTH + 'the text "' + "9" * 39 + '…"'),
    ("long_number.toml", WIDTH + "9" * 39 + "…"),
    ("fps_inf.toml", FPS + "inf"),
    ("fps_nan.toml", FPS + "nan"),
    ("fps_1e400.toml", FPS + "inf"),
    ("width_minus_zero.toml", WIDTH + "0"),
    ("width_quoted_20.toml", WIDTH + 'the text "00000000000000001920". Remove the quotes.'),
    ("width_quoted_21.toml", WIDTH + 'the text "000000000000000001920"'),
    ("width_quoted_out_of_range.toml", WIDTH + 'the text "99999"'),
]


@pytest.mark.parametrize("name, expected", SHORT_MESSAGES)
def test_messages_stay_short_and_hints_stay_safe(load, name, expected):
    result = load(value_bytes(name))
    assert [e.format() for e in result.errors] == [expected]


# --- TR-F01-58: every phrase, produced by its validator -----------------------------------

@pytest.mark.parametrize("validator, phrase", [
    (IntRange(640, 7680), "a whole number from 640 to 7680"),
    (Bool(), "true or false"),
    (Choice("smooth", "pixel"), 'one of "smooth", "pixel"'),
    (Choice("debug", "info", "warning", "error"), 'one of "debug", "info", "warning", "error"'),
    (HexColor(), 'a color written as "#RRGGBB", for example "#000000"'),
    (Text(non_empty=True), "text with at least one visible character"),
    (Text(), "text"),
    (IconRef(), 'text: a path to a .png file in the game folder, for example "gui/icon.png"'),
    (AppId(), '1 to 40 characters, each a lower-case letter a-z, a digit 0-9, or "-", '
              'starting with a letter or digit, and not a reserved name such as "con"'),
])
def test_phrases(validator, phrase):
    assert validator.expected == phrase


@pytest.mark.parametrize("validator, good, bad", [
    (IntRange(30, 240), [30, 240, 60], [29, 241, True, 60.0, "60", None]),
    (Bool(), [True, False], [1, 0, "true", None]),
    (Choice("smooth", "pixel"), ["smooth", "pixel"], ["Smooth", "", 1]),
    (HexColor(), ["#000000", "#aBcDeF"], ["#00000", "000000", "#0000000", "#GGGGGG", 0,
                                         "#00000\n", "#１２３４５６"]),
    (Text(non_empty=True), ["x", " x "], ["", "  ", "\t\n", 5]),
    (Text(), ["", "x"], [5, None, 1.0]),
    (IconRef(), ["", "gui/icon.png", "../x.jpg"], [5, True, None]),
    (AppId(), ["my-vn"], ["My-VN", "", 5, "con"]),
])
def test_validators_accept_and_reject(validator, good, bad):
    for value in good:
        validator.check(value)
    for value in bad:
        with pytest.raises(ValueProblem):
            validator.check(value)


def test_hex_color_converts_to_rgb():
    assert HexColor().check("#1a2B3c") == (26, 43, 60)


@pytest.mark.parametrize("value, shown", [
    (True, "true"), (False, "false"), (5, "5"), (-0, "0"), (1.5, "1.5"),
    (float("inf"), "inf"), (float("nan"), "nan"), ([1], "a list"), ({"a": 1}, "a section"),
    (datetime.date(1979, 5, 27), "a date or time"), (datetime.time(7, 32), "a date or time"),
    (datetime.datetime(1979, 5, 27, 7, 32), "a date or time"),
    ("big", 'the text "big"'), ("a\nb", 'the text "a\\nb"'), ("", 'the text ""'),
    ("x" * 41, 'the text "' + "x" * 39 + '…"'), (10 ** 60, "9" * 0 + str(10 ** 60)[:39] + "…"),
])
def test_describe(value, shown):
    assert describe(value) == shown
