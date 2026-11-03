"""``[textbox]``, ``[theme.textbox]``, ``[theme.textbox.name_tab]``,
``[theme.textbox.indicator]`` and the validators ``Opacity``, ``FontRef``, ``GuiImageRef``
(F05 §13, 02 §3.5, §5.3; 07 §2.3, UI Q2 (a)).

AC-F05-09. Values given as text are described the F01 way (``the text "40"``, with the
quotes hint), as for every other key (F04 I-19). F10 step 1 opened the remaining
``textbox.*`` tokens (PR-F10-16); their ranges are tested in ``test_config_ui.py``.
"""

import dataclasses

import pytest

from engine.core.config import load_config
from engine.core.config_schema import (
    Config,
    FontRef,
    GuiImageRef,
    HexColor,
    IndicatorTheme,
    IntRange,
    NameTabTheme,
    Opacity,
    Table,
    TextboxConfig,
    TextboxTheme,
    ThemeConfig,
    ValueProblem,
)

LINE2 = "config.toml, line 2: "
CPS = "[textbox] cps must be a whole number from 0 to 1000 (0 shows text instantly), but found "
SIZE = "[theme.textbox] text_size must be a whole number from 20 to 48, but found "
COLOR = '{} must be a color "#RRGGBB", but found '
OPACITY = ("[theme.textbox] fill_opacity must be a number from 0.0 to 1.0, such as 0.85 for 85%, "
           "but found ")
FONT = ("[theme.textbox] {} must be a .ttf or .otf file inside the game folder, written with /, "
        "but found ")
FRAME = '[theme.textbox] frame_image must be an image in gui/, e.g. "gui/textbox.png", but found '

EXAMPLE = """\
[textbox]
cps = 35                                # typing is behavior, so it stays here

[theme.textbox]
fill_color = "#3a2a3f"
fill_opacity = 0.85
text_color = "#fff4f8"
text_font = "fonts/Lora-Regular.ttf"    # game/fonts/Lora-Regular.ttf
bold_font = "fonts/Lora-Bold.ttf"

[theme.textbox.name_tab]
text_color = "#e8a0b4"                  # names of characters with no color
"""


def messages(result) -> list[str]:
    return [error.format() for error in result.errors]


# --- Defaults (AC-F05-09) -----------------------------------------------------------------

def test_no_config_gives_the_03_ui_defaults(make_game):
    result = load_config(make_game(None))
    config = result.config
    assert config.textbox == TextboxConfig() and config.textbox.cps == 40
    theme = config.theme.textbox
    assert theme == TextboxTheme()
    assert theme.text_size == 28
    assert theme.text_color == (0x3D, 0x2B, 0x36)
    assert theme.fill_color == (0xFF, 0xF4, 0xF8)
    assert theme.fill_opacity == 0.80
    assert theme.name_tab.text_color == (0xA0, 0x28, 0x60)
    assert (theme.text_font, theme.bold_font, theme.italic_font, theme.bold_italic_font,
            theme.frame_image) == (None, None, None, None, None)


@pytest.mark.parametrize("path, value", [
    ("border_color", (0xF0, 0xA0, 0xC0)), ("border_width", 2), ("corner_radius", 16),
    ("frame_slice_width", 24), ("width", 1000), ("height", 184), ("bottom_gap", 32),
    ("side_padding", 40), ("top_padding", 28), ("bottom_padding", 28),
    ("name_tab.text_font", None), ("name_tab.text_size", 28),
    ("name_tab.fill_color", (0xFF, 0xE6, 0xF0)), ("name_tab.fill_opacity", 1.0),
    ("name_tab.frame_image", None), ("name_tab.corner_radius", 12),
    ("name_tab.left_gap", 24), ("name_tab.side_padding", 20), ("name_tab.min_width", 120),
    ("indicator.fill_color", (0xA0, 0x28, 0x60)), ("indicator.line_image", None),
    ("indicator.page_image", None),
])
def test_tokens_opened_by_f10_hold_their_03_ui_defaults(path, value):
    obj: object = TextboxTheme()
    for part in path.split("."):
        obj = getattr(obj, part)
    assert obj == value


def _read_keys(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls) if "validator" in f.metadata}


@pytest.mark.parametrize("cls", [TextboxConfig, TextboxTheme, NameTabTheme, IndicatorTheme])
def test_every_textbox_field_is_read(cls):
    """F10 PR-F10-16: ``spec`` on every ``textbox.*`` field (07 UI Q2 (a) held them until
    then)."""
    assert _read_keys(cls) == {f.name for f in dataclasses.fields(cls)}


def test_theme_areas():
    assert _read_keys(ThemeConfig) == {
        "stage", "textbox", "ui", "panel", "button", "toggle", "slider", "list", "title",
        "menu", "quick_menu", "confirm", "save", "notice",       # F11: save, notice
        "choice",                                                # F07 step 4
        "effects",                                               # F09 step 1
        "chapter",                                               # F18 step 3
        "nvl",                                                   # F17 step 1
        "rollback",                                              # F14 step 4
        "codex",                                                 # F21 step 3
        "flowchart",                                             # F20 s8
        "gallery",                                               # F34 W3
        "minigame", "plugin"}                                    # F23 s5b


def test_theme_tables_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        TextboxTheme().text_size = 30          # type: ignore[misc]


# --- Accepted values ----------------------------------------------------------------------

def test_the_02_script_example_file_is_accepted_with_its_values(load):
    result = load(EXAMPLE)
    assert result.errors == [] and result.warnings == [] and result.loaded
    assert result.config.textbox.cps == 35
    theme = result.config.theme.textbox
    assert theme.fill_color == (0x3A, 0x2A, 0x3F)
    assert theme.fill_opacity == 0.85
    assert theme.text_color == (0xFF, 0xF4, 0xF8)
    assert theme.text_font == "fonts/Lora-Regular.ttf"
    assert theme.bold_font == "fonts/Lora-Bold.ttf"
    assert theme.italic_font is None and theme.bold_italic_font is None
    assert theme.name_tab.text_color == (0xE8, 0xA0, 0xB4)
    assert theme.name_tab.fill_color == NameTabTheme().fill_color      # untouched tokens
    assert theme.border_width == TextboxTheme().border_width


@pytest.mark.parametrize("text, path, stored", [
    ("[textbox]\ncps = 0", "textbox.cps", 0),
    ("[textbox]\ncps = 1000", "textbox.cps", 1000),
    ("[theme.textbox]\ntext_size = 20", "theme.textbox.text_size", 20),
    ("[theme.textbox]\ntext_size = 48", "theme.textbox.text_size", 48),
    ("[theme.textbox]\nfill_opacity = 0.0", "theme.textbox.fill_opacity", 0.0),
    ("[theme.textbox]\nfill_opacity = 1.0", "theme.textbox.fill_opacity", 1.0),
    ("[theme.textbox]\nfill_opacity = 0", "theme.textbox.fill_opacity", 0.0),
    ("[theme.textbox]\nfill_opacity = 1", "theme.textbox.fill_opacity", 1.0),
    ('[theme.textbox]\ntext_color = "#abcDEF"', "theme.textbox.text_color", (0xAB, 0xCD, 0xEF)),
    ('[theme.textbox]\nfill_color = "#000000"', "theme.textbox.fill_color", (0, 0, 0)),
    ('[theme.textbox]\nitalic_font = "x.otf"', "theme.textbox.italic_font", "x.otf"),
    ('[theme.textbox]\nbold_italic_font = "fonts/a b/Ü.TTF"',
     "theme.textbox.bold_italic_font", "fonts/a b/Ü.TTF"),
    ('[theme.textbox]\nframe_image = "gui/textbox.png"',
     "theme.textbox.frame_image", "gui/textbox.png"),
    ('[theme.textbox]\nframe_image = "gui/frames/box.JPEG"',
     "theme.textbox.frame_image", "gui/frames/box.JPEG"),
    ('[theme.textbox]\nframe_image = "gui/box.webp"', "theme.textbox.frame_image", "gui/box.webp"),
    ('[theme.textbox.name_tab]\ntext_color = "#FFFFFF"',
     "theme.textbox.name_tab.text_color", (255, 255, 255)),
    ('[theme]\ntextbox = { name_tab = { text_color = "#010203" } }',
     "theme.textbox.name_tab.text_color", (1, 2, 3)),
    ('[theme.textbox]\nname_tab = { text_color = "#010203" }',
     "theme.textbox.name_tab.text_color", (1, 2, 3)),
], ids=repr)
def test_accepted_values(load, text, path, stored):
    result = load(text + "\n")
    assert result.errors == [] and result.warnings == []
    obj: object = result.config
    for part in path.split("."):
        obj = getattr(obj, part)
    assert obj == stored
    assert type(obj) is type(stored)


# --- Errors (AC-F05-09 rows, then edge cases) ---------------------------------------------

AC_ROWS = [
    ("[textbox]", "cps = 1001", CPS + "1001"),
    ("[textbox]", "cps = -1", CPS + "-1"),
    ("[textbox]", "cps = 40.5", CPS + "40.5"),
    ("[theme.textbox]", "text_size = 19", SIZE + "19"),
    ("[theme.textbox]", "text_size = 49", SIZE + "49"),
    ("[theme.textbox]", 'text_color = "red"',
     COLOR.format("[theme.textbox] text_color") + 'the text "red"'),
    ("[theme.textbox]", 'fill_color = "#fff"',
     COLOR.format("[theme.textbox] fill_color") + 'the text "#fff"'),
    ("[theme.textbox]", "fill_opacity = 85", OPACITY + "85"),
    ("[theme.textbox]", "fill_opacity = -0.1", OPACITY + "-0.1"),
    ("[theme.textbox]", "fill_opacity = 1.01", OPACITY + "1.01"),
    ("[theme.textbox]", 'text_font = "../x.ttf"', FONT.format("text_font") + 'the text "../x.ttf"'),
    ("[theme.textbox]", 'text_font = "C:/f/x.ttf"',
     FONT.format("text_font") + 'the text "C:/f/x.ttf"'),
    ("[theme.textbox]", 'text_font = "fonts/x.woff"',
     FONT.format("text_font") + 'the text "fonts/x.woff"'),
    ("[theme.textbox]", 'text_font = "fonts\\\\x.ttf"',
     FONT.format("text_font") + 'the text "fonts\\x.ttf"'),
    ("[theme.textbox]", 'frame_image = "images/box.png"', FRAME + 'the text "images/box.png"'),
    ("[theme.textbox.name_tab]", 'text_color = "pink"',
     COLOR.format("[theme.textbox.name_tab] text_color") + 'the text "pink"'),
]


@pytest.mark.parametrize("header, line, message", AC_ROWS, ids=[row[1] for row in AC_ROWS])
def test_ac_f05_09_rows_stop_startup_with_exactly_one_message(load, header, line, message):
    result = load(f"{header}\n{line}\n")
    assert messages(result) == [LINE2 + message]
    assert result.loaded is False
    assert result.config == Config()                  # the bad value falls back to its default


EDGE_ROWS = [
    ("[textbox]", 'cps = "40"', CPS + 'the text "40". Remove the quotes.'),
    ("[textbox]", 'cps = "0"', CPS + 'the text "0". Remove the quotes.'),
    ("[textbox]", "cps = true", CPS + "true"),
    ("[textbox]", "cps = 40.0", CPS + "40.0"),
    ("[textbox]", "cps = [40]", CPS + "a list"),
    ("[textbox]", "cps = { a = 1 }", CPS + "a section"),
    ("[textbox]", "cps = 1" + "0" * 300, CPS + "1" + "0" * 38 + "…"),
    ("[theme.textbox]", "text_size = 28.0", SIZE + "28.0"),
    ("[theme.textbox]", 'text_size = "28"', SIZE + 'the text "28". Remove the quotes.'),
    ("[theme.textbox]", 'fill_opacity = "1"', OPACITY + 'the text "1". Remove the quotes.'),
    ("[theme.textbox]", 'fill_opacity = "0.85"',
     OPACITY + 'the text "0.85". Remove the quotes.'),          # F08 step 2: decimals too
    ("[theme.textbox]", 'fill_opacity = "1.5"', OPACITY + 'the text "1.5"'),
    ("[theme.textbox]", "fill_opacity = true", OPACITY + "true"),
    ("[theme.textbox]", "fill_opacity = false", OPACITY + "false"),
    ("[theme.textbox]", "fill_opacity = nan", OPACITY + "nan"),
    ("[theme.textbox]", "fill_opacity = inf", OPACITY + "inf"),
    ("[theme.textbox]", "fill_opacity = 1e400", OPACITY + "inf"),
    ("[theme.textbox]", "fill_opacity = 2", OPACITY + "2"),
    ("[theme.textbox]", "fill_opacity = 1.0000001", OPACITY + "1.0000001"),
    ("[theme.textbox]", "fill_opacity = 1" + "0" * 400, OPACITY + "1" + "0" * 38 + "…"),
    ("[theme.textbox]", 'text_color = "#12345g"',
     COLOR.format("[theme.textbox] text_color") + 'the text "#12345g"'),
    ("[theme.textbox]", 'text_color = "#1234567"',
     COLOR.format("[theme.textbox] text_color") + 'the text "#1234567"'),
    ("[theme.textbox]", 'text_color = " #123456"',
     COLOR.format("[theme.textbox] text_color") + 'the text " #123456"'),
    ("[theme.textbox]", 'text_color = "123456"',
     COLOR.format("[theme.textbox] text_color") + 'the text "123456"'),
    ("[theme.textbox]", "text_color = 0x123456",
     COLOR.format("[theme.textbox] text_color") + "1193046"),
    ("[theme.textbox]", 'text_font = ""', FONT.format("text_font") + 'the text ""'),
    ("[theme.textbox]", "bold_font = 5", FONT.format("bold_font") + "5"),
    ("[theme.textbox]", 'italic_font = "fonts/.ttf"',
     FONT.format("italic_font") + 'the text "fonts/.ttf"'),
    ("[theme.textbox]", 'italic_font = "fonts/x"',
     FONT.format("italic_font") + 'the text "fonts/x"'),
    ("[theme.textbox]", 'bold_italic_font = "/fonts/x.ttf"',
     FONT.format("bold_italic_font") + 'the text "/fonts/x.ttf"'),
    ("[theme.textbox]", 'text_font = "~/x.ttf"', FONT.format("text_font") + 'the text "~/x.ttf"'),
    ("[theme.textbox]", 'text_font = "fonts//x.ttf"',
     FONT.format("text_font") + 'the text "fonts//x.ttf"'),
    ("[theme.textbox]", 'text_font = "./x.ttf"', FONT.format("text_font") + 'the text "./x.ttf"'),
    ("[theme.textbox]", 'text_font = "con.ttf"', FONT.format("text_font") + 'the text "con.ttf"'),
    ("[theme.textbox]", 'text_font = "x.ttf "', FONT.format("text_font") + 'the text "x.ttf "'),
    ("[theme.textbox]", 'text_font = "x.ttf."', FONT.format("text_font") + 'the text "x.ttf."'),
    ("[theme.textbox]", 'text_font = "a\\tb.ttf"',
     FONT.format("text_font") + 'the text "a\\tb.ttf"'),
    ("[theme.textbox]", 'text_font = "' + "f" * 1100 + '.ttf"',
     FONT.format("text_font") + 'the text "' + "f" * 39 + '…"'),
    ("[theme.textbox]", 'frame_image = "gui/x.gif"', FRAME + 'the text "gui/x.gif"'),
    ("[theme.textbox]", 'frame_image = "GUI/x.png"', FRAME + 'the text "GUI/x.png"'),
    ("[theme.textbox]", 'frame_image = "gui/../x.png"', FRAME + 'the text "gui/../x.png"'),
    ("[theme.textbox]", 'frame_image = "./gui/x.png"', FRAME + 'the text "./gui/x.png"'),
    ("[theme.textbox]", 'frame_image = "gui/"', FRAME + 'the text "gui/"'),
    ("[theme.textbox]", 'frame_image = "gui"', FRAME + 'the text "gui"'),
    ("[theme.textbox]", 'frame_image = "gui/box"', FRAME + 'the text "gui/box"'),
    ("[theme.textbox]", 'frame_image = "gui/.png"', FRAME + 'the text "gui/.png"'),
    ("[theme.textbox]", "frame_image = false", FRAME + "false"),
    ("[theme.textbox]", "name_tab = 5", "[theme.textbox] name_tab must be a section, but found 5"),
    ("[theme.textbox]", 'indicator = "x"',
     '[theme.textbox] indicator must be a section, but found the text "x"'),
    ("[theme]", "textbox = []", "[theme] textbox must be a section, but found a list"),
    ("[theme]", 'textbox = { name_tab = { text_color = "pink" } }',
     COLOR.format("[theme.textbox.name_tab] text_color") + 'the text "pink"'),
]


@pytest.mark.parametrize("header, line, message", EDGE_ROWS, ids=[row[1][:40] for row in EDGE_ROWS])
def test_edge_case_errors(load, header, line, message):
    result = load(f"{header}\n{line}\n")
    assert messages(result) == [LINE2 + message]
    assert result.config == Config()


def test_every_bad_key_is_reported_and_good_keys_are_kept(load):
    result = load('[textbox]\ncps = 2000\n[theme.textbox]\ntext_size = 30\nfill_opacity = 9\n'
                  'frame_image = "box.png"\ntext_color = "#102030"\n'
                  '[theme.textbox.name_tab]\ntext_color = "nope"\n')
    assert [error.line for error in result.errors] == [2, 5, 6, 9]
    assert result.config.textbox.cps == 40
    theme = result.config.theme.textbox
    assert (theme.text_size, theme.text_color) == (30, (0x10, 0x20, 0x30))
    assert (theme.fill_opacity, theme.frame_image) == (0.80, None)
    assert theme.name_tab == NameTabTheme()


# --- Warnings (AC-F01-17 form): unknown keys -----------------------------------------------

@pytest.mark.parametrize("text, warning", [
    ('[theme.textbox]\nfill_colour = "#000000"',
     'unknown key [theme.textbox] fill_colour — did you mean "fill_color"?'),
    ("[theme.textbox]\nborder_widht = 4",
     'unknown key [theme.textbox] border_widht — did you mean "border_width"?'),
    ('[textbox]\nfont = "x.ttf"', "unknown key [textbox] font"),
    ("[theme.textbox]\nfill_opacty = 0.5",
     'unknown key [theme.textbox] fill_opacty — did you mean "fill_opacity"?'),
    ("[theme.textbox]\nwidht = 900", 'unknown key [theme.textbox] widht — did you mean "width"?'),
    ("[theme.textbox.name_tab]\ncolor = \"#000000\"", "unknown key [theme.textbox.name_tab] color"),
    ("[theme.textbox.name_tab]\ntext_colour = \"#000000\"",
     'unknown key [theme.textbox.name_tab] text_colour — did you mean "text_color"?'),
    ('[theme.textbox.indicator]\nline = "gui/x.png"', "unknown key [theme.textbox.indicator] line"),
    ("[textbx]\ncps = 1", None),
], ids=repr)
def test_unknown_and_unread_keys_warn_and_start(load, text, warning):
    result = load(text + "\n")
    assert result.errors == [] and result.loaded is True
    if warning is None:                               # an unknown section, on line 1
        assert result.warnings == [
            "config.toml, line 1: unknown section [textbx] — did you mean [textbox]?"]
    else:
        assert result.warnings == [LINE2 + warning]
    assert result.config == Config()


# --- The validators -----------------------------------------------------------------------

@pytest.mark.parametrize("value, stored", [
    (0, 0.0), (1, 1.0), (0.5, 0.5), (0.0, 0.0), (1.0, 1.0), (-0.0, 0.0),
])
def test_opacity_accepts_and_stores_floats(value, stored):
    result = Opacity().check(value)
    assert result == stored and type(result) is float


@pytest.mark.parametrize("value", [
    True, False, -1, 2, 1.5, -0.01, float("nan"), float("inf"), float("-inf"), 10 ** 400,
    "0.5", None, [0.5],
])
def test_opacity_refuses(value):
    with pytest.raises(ValueProblem):
        Opacity().check(value)


@pytest.mark.parametrize("validator, good, bad", [
    (FontRef(), ["a.ttf", "a.otf", "f/a.TTF", "f/a.OtF", "f/b.c.ttf"],
     ["a.ttc", "a.woff2", ".ttf", "a", "a/", "a\\b.ttf", "C:a.ttf", "f/aux.ttf", "f/nul.otf",
      "a\x00.ttf", b"a.ttf", None]),
    (GuiImageRef(), ["gui/a.png", "gui/a.jpg", "gui/a.jpeg", "gui/a.webp", "gui/x/y/z.PNG"],
     ["a.png", "gui/a.bmp", "gui/a.svg", "gui\\a.png", "Gui/a.png", "x/gui/a.png",
      "gui/con.png", "gui/a.png/", " gui/a.png", None, 1]),
])
def test_ref_validators(validator, good, bad):
    for value in good:
        assert validator.check(value) == value
    for value in bad:
        with pytest.raises(ValueProblem):
            validator.check(value)


def test_validator_phrases():
    assert IntRange(0, 1000, note="0 shows text instantly").expected == (
        "a whole number from 0 to 1000 (0 shows text instantly)")
    assert IntRange(20, 48).expected == "a whole number from 20 to 48"
    assert HexColor().expected == 'a color written as "#RRGGBB", for example "#000000"'
    assert HexColor('a color "#RRGGBB"').expected == 'a color "#RRGGBB"'
    assert Opacity.expected == "a number from 0.0 to 1.0, such as 0.85 for 85%"
    assert FontRef.expected == "a .ttf or .otf file inside the game folder, written with /"
    assert GuiImageRef.expected == 'an image in gui/, e.g. "gui/textbox.png"'
    assert isinstance(dataclasses.fields(ThemeConfig)[1].metadata["validator"], Table)
