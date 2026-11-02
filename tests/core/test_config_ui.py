"""F10 step 1: the ten UI theme areas, the opened ``textbox.*`` tokens, ``[words]``,
``[title]``, ``[quick_menu]``, and the validators ``AudioRef``, ``NameList``, and
``Text(max_chars=)`` (F10 04 §4, §13; 07 C11, I-5, I-19).

AC-F10-20, read with I-19: ``music = "title.ogg"`` loads and ``"audio/title.ogg"`` is an
error (audio refs are relative to ``audio/``). ``tests/fixtures/F10/tokens.csv`` holds the
89 rows of 03-ui "Theme tokens", transcribed once.
"""

import csv
import dataclasses
from pathlib import Path

import pytest

from engine.core import constants
from engine.core.config_schema import (
    SECTIONS,
    UI_THEME_AREAS,
    AudioFileKey,
    AudioRef,
    Config,
    FontRef,
    GuiImageRef,
    HexColor,
    IntRange,
    NameList,
    Opacity,
    QuickMenuConfig,
    Table,
    Text,
    ThemeConfig,
    TitleConfig,
    ValueProblem,
    WordsConfig,
    config_fields,
    is_audio_ref,
)

TOKENS_CSV = Path(__file__).parents[1] / "fixtures" / "F10" / "tokens.csv"
LINE2 = "config.toml, line 2: "
COLOR = 'must be a color like "#RRGGBB"'
AUDIO = 'must be a file inside audio/ with its extension, e.g. "bgm/festival.ogg"'
OPACITY = "must be a number from 0.0 to 1.0, such as 0.85 for 85%"
NAMES = ('must be a list of at most 16 different names, each 1 to 20 of a-z and _, '
         'e.g. ["new_game", "quit"]')


def messages(result) -> list[str]:
    return [error.format() for error in result.errors]


def read_tokens() -> list[dict[str, str]]:
    with TOKENS_CSV.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


TOKENS = read_tokens()
NUMERIC = [row for row in TOKENS if row["type"] in ("length", "size", "duration")]
OPACITIES = [row for row in TOKENS if row["type"] == "opacity"]


def lookup(obj: object, dotted: str) -> object:
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def leaf_fields(cls: type, prefix: str) -> dict[str, dataclasses.Field]:
    """Every config key under ``cls`` as ``area.state.key`` → its field (Tables walked)."""
    out: dict[str, dataclasses.Field] = {}
    for key, f in config_fields(cls).items():
        validator = f.metadata["validator"]
        if isinstance(validator, Table):
            out.update(leaf_fields(validator.cls, f"{prefix}{key}."))
        else:
            out[prefix + key] = f
    return out


def ui_leaf_fields() -> dict[str, dataclasses.Field]:
    areas = config_fields(ThemeConfig)
    out: dict[str, dataclasses.Field] = {}
    for area in UI_THEME_AREAS:
        out.update(leaf_fields(areas[area].metadata["validator"].cls, area + "."))
    return out


def toml_for(dotted: str, value: str) -> str:
    """``[theme.<area>.<state>]`` then ``key = value`` on line 2."""
    *tables, key = dotted.split(".")
    return f"[theme.{'.'.join(tables)}]\n{key} = {value}\n"


def label(dotted: str) -> str:
    *tables, key = dotted.split(".")
    return f"[theme.{'.'.join(tables)}] {key}"


def expected_default(row: dict[str, str]) -> object:
    default = row["default"]
    if row["type"] == "color":
        return (int(default[1:3], 16), int(default[3:5], 16), int(default[5:7], 16))
    if row["type"] == "opacity":
        return float(default)
    if row["type"] in ("length", "size", "duration"):
        return int(default)
    # Refs: "none", or another token to fall back on (ui.text_font → textbox.text_font).
    return None


# --- The tokens file: one field per row, its default and its kind (AC-F10-20) --------------

def test_tokens_file_has_the_89_rows_of_03_ui():
    assert len(TOKENS) == 89
    assert len({row["key"] for row in TOKENS}) == 89
    assert {row["key"].split(".")[0] for row in TOKENS} == set(UI_THEME_AREAS)


def test_each_row_is_exactly_one_field_and_no_other_field_exists():
    assert set(ui_leaf_fields()) == {row["key"] for row in TOKENS}


# The 89-row tables are loops, each assert naming its row: 89 pytest items cost more than the
# checks (test-review-F10.md).

def test_empty_config_gives_each_default(load):
    result = load("")
    assert result.errors == [] and result.warnings == []
    for row in TOKENS:
        value = lookup(result.config.theme, row["key"])
        assert value == expected_default(row), row["key"]
        assert type(value) is type(expected_default(row)), row["key"]


_KINDS = {
    "color": HexColor, "opacity": Opacity, "font": FontRef, "image": GuiImageRef,
    "image (nine-slice)": GuiImageRef, "sound": AudioRef, "music": AudioRef,
    "length": IntRange, "size": IntRange, "duration": IntRange,
}


def test_each_field_has_the_validator_of_its_type():
    fields = ui_leaf_fields()
    for row in TOKENS:
        validator = fields[row["key"]].metadata["validator"]
        assert type(validator) is _KINDS[row["type"]], row["key"]
        if isinstance(validator, IntRange):
            assert (validator.lo, validator.hi) == (int(row["min"]), int(row["max"])), row["key"]
        if isinstance(validator, HexColor):
            assert validator.expected == 'a color like "#RRGGBB"', row["key"]


def test_whole_number_range_ends_load_and_one_past_is_an_error(load):
    for row in NUMERIC:
        key = row["key"]
        lo, hi = int(row["min"]), int(row["max"])
        for value in (lo, hi):
            result = load(toml_for(key, str(value)))
            assert result.errors == [] and lookup(result.config.theme, key) == value, key
        for value in (lo - 1, hi + 1):
            result = load(toml_for(key, str(value)))
            assert messages(result) == [
                f"{LINE2}{label(key)} must be a whole number from {lo} to {hi}, "
                f"but found {value}"], key
            assert result.config == Config(), key


def test_opacity_range_ends_load_and_one_step_past_is_an_error(load):
    for row in OPACITIES:
        key = row["key"]
        for value in ("0.0", "1.0"):
            result = load(toml_for(key, value))
            assert result.errors == [] and lookup(result.config.theme, key) == float(value), key
        for value in ("-0.01", "1.01"):
            result = load(toml_for(key, value))
            assert messages(result) == [f"{LINE2}{label(key)} {OPACITY}, but found {value}"], key


# --- AC-F10-20's table (with I-19) ----------------------------------------------------------

@pytest.mark.parametrize("text, path, stored", [
    ('[theme.button]\nfill_color = "#2A1E2E"', "button.fill_color", (42, 30, 46)),
    ("[theme.ui]\nfade_ms = 0", "ui.fade_ms", 0),
    ("[theme.ui]\nfade_ms = 1000", "ui.fade_ms", 1000),
    ('[theme.title]\nmusic = "title.ogg"', "title.music", "title.ogg"),
    ('[theme.title]\nmusic = "bgm/Title Theme.OGG"', "title.music", "bgm/Title Theme.OGG"),
    ('[theme.ui]\nback_sound = "sfx/back.wav"', "ui.back_sound", "sfx/back.wav"),
    ('[theme.button]\nfocus_sound = "f.ogg"', "button.focus_sound", "f.ogg"),
    ('[theme.button]\nactivate_sound = "a.ogg"', "button.activate_sound", "a.ogg"),
    ('[theme.quick_menu]\nactivate_sound = "q.ogg"', "quick_menu.activate_sound", "q.ogg"),
    ('[theme.ui]\ntext_font = "fonts/t.ttf"', "ui.text_font", "fonts/t.ttf"),
    ('[theme.ui]\nbold_font = "fonts/b.otf"', "ui.bold_font", "fonts/b.otf"),
    ('[theme.button]\nframe_image = "gui/button.png"', "button.frame_image", "gui/button.png"),
    ('[theme.title]\nbackground_image = "gui/title_bg.png"', "title.background_image",
     "gui/title_bg.png"),
    ('[theme.button.focused]\nframe_image = "gui/f.png"', "button.focused.frame_image",
     "gui/f.png"),
    ('[theme]\nbutton = { focused = { border_width = 8 } }', "button.focused.border_width", 8),
    ('[theme.button]\nfocused = { border_width = 2 }', "button.focused.border_width", 2),
    ("[theme.menu]\ndim_opacity = 1", "menu.dim_opacity", 1.0),
], ids=repr)
def test_accepted_values(load, text, path, stored):
    result = load(text + "\n")
    assert result.errors == [] and result.warnings == [] and result.loaded
    value = lookup(result.config.theme, path)
    assert value == stored and type(value) is type(stored)


ERROR_ROWS = [
    ("[theme.button]", 'fill_color = "2A1E2E"',
     f'[theme.button] fill_color {COLOR}, but found the text "2A1E2E"'),
    ("[theme.ui]", "fade_ms = 1001",
     "[theme.ui] fade_ms must be a whole number from 0 to 1000, but found 1001"),
    ("[theme.quick_menu]", "text_size = 25",
     "[theme.quick_menu] text_size must be a whole number from 20 to 24, but found 25"),
    ("[theme.title]", 'music = "audio/title.ogg"',
     f'[theme.title] music {AUDIO}, but found the text "audio/title.ogg"'),     # I-5, I-19
    ("[theme.title]", 'music = "AUDIO/title.ogg"',
     f'[theme.title] music {AUDIO}, but found the text "AUDIO/title.ogg"'),
    ("[theme.title]", 'music = "title"',
     f'[theme.title] music {AUDIO}, but found the text "title"'),
    ("[theme.title]", 'music = "../x.ogg"',
     f'[theme.title] music {AUDIO}, but found the text "../x.ogg"'),
    ("[theme.title]", "music = 3", f"[theme.title] music {AUDIO}, but found 3"),
    ("[theme.button.focused]", "border_width = 9",
     "[theme.button.focused] border_width must be a whole number from 2 to 8, but found 9"),
    # Edge cases.
    ("[theme.ui]", 'fade_ms = "150"',
     '[theme.ui] fade_ms must be a whole number from 0 to 1000, but found the text "150". '
     "Remove the quotes."),
    ("[theme.ui]", "fade_ms = 150.0",
     "[theme.ui] fade_ms must be a whole number from 0 to 1000, but found 150.0"),
    ("[theme.panel]", "fill_opacity = true",
     f"[theme.panel] fill_opacity {OPACITY}, but found true"),
    ("[theme.panel]", 'fill_color = "#FFF"',
     f'[theme.panel] fill_color {COLOR}, but found the text "#FFF"'),
    ("[theme.ui]", 'back_sound = ""', f'[theme.ui] back_sound {AUDIO}, but found the text ""'),
    ("[theme.ui]", 'back_sound = "C:/x.ogg"',
     f'[theme.ui] back_sound {AUDIO}, but found the text "C:/x.ogg"'),
    ("[theme.ui]", 'back_sound = "sfx\\\\x.ogg"',
     f'[theme.ui] back_sound {AUDIO}, but found the text "sfx\\x.ogg"'),
    ("[theme.button]", 'focus_sound = "sfx/"',
     f'[theme.button] focus_sound {AUDIO}, but found the text "sfx/"'),
    ("[theme.ui]", 'text_font = "fonts/x.woff"',
     '[theme.ui] text_font must be a .ttf or .otf file inside the game folder, written with /, '
     'but found the text "fonts/x.woff"'),
    ("[theme.title]", 'logo_image = "images/logo.png"',
     '[theme.title] logo_image must be an image in gui/, e.g. "gui/textbox.png", '
     'but found the text "images/logo.png"'),
    ("[theme.button]", "focused = 5", "[theme.button] focused must be a section, but found 5"),
    ("[theme]", "ui = []", "[theme] ui must be a section, but found a list"),
]


@pytest.mark.parametrize("header, line, message", ERROR_ROWS,
                         ids=[f"{row[0]} {row[1]}" for row in ERROR_ROWS])
def test_errors_in_f01_shape(load, header, line, message):
    result = load(f"{header}\n{line}\n")
    assert messages(result) == [LINE2 + message]
    assert result.loaded is False
    assert result.config == Config()


@pytest.mark.parametrize("text, warning", [
    ('[theme.button]\ntext_colour = "#F6E8F0"',
     LINE2 + 'unknown key [theme.button] text_colour — did you mean "text_color"?'),
    ("[theme.nope]\nx = 1", "config.toml, line 1: unknown key [theme] nope"),
    ("[theme.button.focussed]\nborder_width = 3",
     'config.toml, line 1: unknown key [theme.button] focussed — did you mean "focused"?'),
    ('[theme.title]\nmusik = "title.ogg"',
     LINE2 + 'unknown key [theme.title] musik — did you mean "music"?'),
], ids=repr)
def test_unknown_keys_warn_and_keep_defaults(load, text, warning):
    result = load(text + "\n")
    assert result.errors == [] and result.loaded
    assert result.warnings == [warning]
    assert result.config == Config()


def test_every_bad_value_is_reported_on_its_own_line_and_good_ones_kept(load):
    result = load('[theme.button]\nfill_color = "#2A1E2E"\ntext_color = "nope"\n'
                  "[theme.button.focused]\nborder_width = 9\nfill_color = \"#010203\"\n"
                  '[theme.title]\nmusic = "audio/title.ogg"\n')
    assert [error.line for error in result.errors] == [3, 5, 8]
    button = result.config.theme.button
    assert button.fill_color == (42, 30, 46) and button.text_color == (0x3D, 0x2B, 0x36)
    assert button.focused.border_width == 4 and button.focused.fill_color == (1, 2, 3)
    assert result.config.theme.title.music is None


# --- Opened textbox tokens (PR-F10-16; F05 03-ui ranges) -----------------------------------

TEXTBOX_RANGES = [
    ("textbox.border_width", 0, 8), ("textbox.corner_radius", 0, 48),
    ("textbox.frame_slice_width", 0, 96), ("textbox.width", 640, 1280),
    ("textbox.height", 120, 216), ("textbox.bottom_gap", 0, 120),
    ("textbox.side_padding", 24, 120), ("textbox.top_padding", 8, 80),
    ("textbox.bottom_padding", 8, 80), ("textbox.text_size", 20, 48),
    ("textbox.name_tab.text_size", 20, 48), ("textbox.name_tab.corner_radius", 0, 24),
    ("textbox.name_tab.left_gap", 0, 200), ("textbox.name_tab.side_padding", 8, 40),
    ("textbox.name_tab.min_width", 40, 500),
]


@pytest.mark.parametrize("path, lo, hi", TEXTBOX_RANGES, ids=[row[0] for row in TEXTBOX_RANGES])
def test_textbox_range_ends(load, path, lo, hi):
    for value in (lo, hi):
        result = load(toml_for(path, str(value)))
        assert result.errors == [] and result.warnings == []
        assert lookup(result.config.theme, path) == value
    for value in (lo - 1, hi + 1):
        assert messages(load(toml_for(path, str(value)))) == [
            f"{LINE2}{label(path)} must be a whole number from {lo} to {hi}, but found {value}"]


@pytest.mark.parametrize("path, text, stored", [
    ("textbox.border_color", '"#000000"', (0, 0, 0)),
    ("textbox.name_tab.text_font", '"fonts/n.otf"', "fonts/n.otf"),
    ("textbox.name_tab.fill_color", '"#B03070"', (0xB0, 0x30, 0x70)),
    ("textbox.name_tab.fill_opacity", "0.5", 0.5),
    ("textbox.name_tab.frame_image", '"gui/tab.png"', "gui/tab.png"),
    ("textbox.indicator.fill_color", '"#FFFFFF"', (255, 255, 255)),
    ("textbox.indicator.line_image", '"gui/line.png"', "gui/line.png"),
    ("textbox.indicator.page_image", '"gui/page.png"', "gui/page.png"),
], ids=repr)
def test_textbox_refs_and_colors_load(load, path, text, stored):
    result = load(toml_for(path, text))
    assert result.errors == [] and result.warnings == []
    assert lookup(result.config.theme, path) == stored


@pytest.mark.parametrize("path, text, phrase", [
    ("textbox.border_color", '"red"', 'must be a color "#RRGGBB"'),
    ("textbox.name_tab.fill_opacity", "1.5", OPACITY),
    ("textbox.indicator.line_image", '"images/x.png"',
     'must be an image in gui/, e.g. "gui/textbox.png"'),
    ("textbox.name_tab.text_font", '"x.woff"',
     "must be a .ttf or .otf file inside the game folder, written with /"),
], ids=repr)
def test_textbox_bad_values(load, path, text, phrase):
    [message] = messages(load(toml_for(path, text)))
    assert message.startswith(f"{LINE2}{label(path)} {phrase}, but found ")


# --- [words] -------------------------------------------------------------------------------

WORDS = {
    "new_game": "New Game", "load": "Load", "settings": "Settings", "extras": "Extras",
    "help": "Help", "quit": "Quit", "return": "Return", "history": "History", "save": "Save",
    "main_menu": "Main Menu", "yes": "Yes", "no": "No", "hide": "Hide", "menu": "Menu",
    "on": "On", "off": "Off", "loading": "Loading", "list_empty": "Nothing here yet.",
    "confirm_main_menu": "Return to the title screen? Unsaved progress will be lost.",
    "confirm_quit": "Quit the game? Unsaved progress will be lost.",
}
MESSAGE_WORDS = ("confirm_main_menu", "confirm_quit")


def word(words: WordsConfig, key: str) -> str:
    return getattr(words, config_fields(WordsConfig)[key].name)


def test_words_are_the_20_keys_of_03_ui_with_english_defaults():
    # F10's 20 keys come first; later features add theirs after (F11: test_config_f11.py).
    assert list(config_fields(WordsConfig))[:len(WORDS)] == list(WORDS)
    words = Config().words
    assert {key: word(words, key) for key in WORDS} == WORDS
    assert words.return_ == "Return"


@pytest.mark.parametrize("key", list(WORDS))
def test_each_word_loads_up_to_its_limit_and_not_past_it(load, key):
    limit = 1000 if key in MESSAGE_WORDS else 200
    text = "é" * limit                                     # characters, not bytes
    result = load(f'[words]\n{key} = "{text}"\n')
    assert result.errors == [] and word(result.config.words, key) == text
    result = load(f'[words]\n{key} = "{text}x"\n')
    assert messages(result) == [
        f"{LINE2}[words] {key} must be text of at most {limit} characters, but found the text "
        f'"{"é" * 39}…"']
    assert word(result.config.words, key) == WORDS[key]


@pytest.mark.parametrize("text, key, stored", [
    ('new_game = "Begin"', "new_game", "Begin"),
    ('return = "Back"', "return", "Back"),
    ('"return" = "Back"', "return", "Back"),
    ('quit = ""', "quit", ""),                              # W65 at install time, not here
    ('yes = "   "', "yes", "   "),
    ('on = "オン"', "on", "オン"),
], ids=repr)
def test_word_values(load, text, key, stored):
    result = load(f"[words]\n{text}\n")
    assert result.errors == [] and result.warnings == []
    assert word(result.config.words, key) == stored


@pytest.mark.parametrize("text, message", [
    ("new_game = 5", "[words] new_game must be text of at most 200 characters, but found 5"),
    ("return = true", "[words] return must be text of at most 200 characters, but found true"),
    ('no = ["No"]', "[words] no must be text of at most 200 characters, but found a list"),
    ("confirm_quit = 1",
     "[words] confirm_quit must be text of at most 1000 characters, but found 1"),
], ids=repr)
def test_word_errors(load, text, message):
    assert messages(load(f"[words]\n{text}\n")) == [LINE2 + message]


@pytest.mark.parametrize("text, warning", [
    ('new_gam = "x"', 'unknown key [words] new_gam — did you mean "new_game"?'),
    ('return_ = "x"', 'unknown key [words] return_ — did you mean "return"?'),
    ('continue = "x"', "unknown key [words] continue"),
], ids=repr)
def test_unknown_words_warn(load, text, warning):
    result = load(f"[words]\n{text}\n")
    assert result.errors == [] and result.warnings == [LINE2 + warning]
    assert result.config.words == WordsConfig()


# --- [title] and [quick_menu] --------------------------------------------------------------

def test_title_and_quick_menu_defaults():
    config = Config()
    assert config.title == TitleConfig(enabled=True, show_version=True, entries=None)
    assert config.quick_menu == QuickMenuConfig(enabled=True, entries=None)
    assert SECTIONS["words"] is WordsConfig and SECTIONS["title"] is TitleConfig
    assert SECTIONS["quick_menu"] is QuickMenuConfig


@pytest.mark.parametrize("text, path, stored", [
    ("[title]\nenabled = false", "title.enabled", False),
    ("[title]\nshow_version = false", "title.show_version", False),
    ('[title]\nentries = ["new_game", "load", "quit"]', "title.entries",
     ("new_game", "load", "quit")),
    ('[title]\nentries = ["quit", "new_game"]', "title.entries", ("quit", "new_game")),
    ("[title]\nentries = []", "title.entries", ()),         # W66 at install time
    ('[title]\nentries = ["nope"]', "title.entries", ("nope",)),   # W66 at install time
    ("[title]\nentries = [" + ", ".join(f'"{chr(97 + i)}"' for i in range(16)) + "]",
     "title.entries", tuple(chr(97 + i) for i in range(16))),
    ('[title]\nentries = ["' + "a" * 20 + '", "_"]', "title.entries", ("a" * 20, "_")),
    ("[quick_menu]\nenabled = false", "quick_menu.enabled", False),
    ('[quick_menu]\nentries = ["hide", "menu"]', "quick_menu.entries", ("hide", "menu")),
    ('[quick_menu]\nentries = [\n  "hide",\n  "menu",\n]', "quick_menu.entries",
     ("hide", "menu")),
], ids=repr)
def test_menu_values(load, text, path, stored):
    result = load(text + "\n")
    assert result.errors == [] and result.warnings == []
    value = lookup(result.config, path)
    assert value == stored and type(value) is type(stored)


@pytest.mark.parametrize("section, text, found", [
    ("title", 'entries = ["new_game", "new_game"]', "a list"),
    ("title", "entries = [" + ", ".join(f'"{chr(97 + i)}"' for i in range(17)) + "]", "a list"),
    ("title", 'entries = ["New_Game"]', "a list"),
    ("title", 'entries = ["load2"]', "a list"),
    ("title", 'entries = ["new-game"]', "a list"),
    ("title", 'entries = [""]', "a list"),
    ("title", 'entries = ["' + "a" * 21 + '"]', "a list"),
    ("title", 'entries = ["ñ"]', "a list"),
    ("title", "entries = [1]", "a list"),
    ("title", 'entries = [["load"]]', "a list"),
    ("title", 'entries = "new_game"', 'the text "new_game"'),
    ("quick_menu", 'entries = ["hide", " menu"]', "a list"),
    ("quick_menu", "entries = { hide = 1 }", "a section"),
], ids=repr)
def test_name_list_errors(load, section, text, found):
    result = load(f"[{section}]\n{text}\n")
    assert messages(result) == [f"{LINE2}[{section}] entries {NAMES}, but found {found}"]
    assert lookup(result.config, f"{section}.entries") is None


@pytest.mark.parametrize("text, message", [
    ('[title]\nenabled = "false"',
     '[title] enabled must be true or false, but found the text "false". Remove the quotes.'),
    ("[quick_menu]\nenabled = 0", "[quick_menu] enabled must be true or false, but found 0"),
], ids=repr)
def test_menu_bool_errors(load, text, message):
    assert messages(load(text + "\n")) == [LINE2 + message]


def test_title_section_and_game_title_are_separate(load):
    result = load('[game]\ntitle = "Hana"\n[title]\nenabled = false\n')
    assert result.errors == []
    assert result.config.game.title == "Hana" and result.config.title.enabled is False


# --- The validators, outside config loading (07 "overrides") -------------------------------

def test_audio_ref_is_audio_file_keys_check():
    good = ["title.ogg", "bgm/title.ogg", "a b/Ü.OPUS", "x.wav", "f.ogg", "a.b.c"]
    bad = ["audio/title.ogg", "Audio/x.ogg", "title", "bgm/", "../x.ogg", "/x.ogg", "C:/x.ogg",
           "a\\b.ogg", "", "bgm/con.ogg", ".ogg", "x.ogg ", None, 3, True, ["x.ogg"], b"x.ogg"]
    for value in good:
        assert is_audio_ref(value)
        assert AudioRef().check(value) == value
        assert AudioFileKey().check(value) == value
    for value in bad:
        assert not is_audio_ref(value)
        for validator in (AudioRef(), AudioFileKey()):
            with pytest.raises(ValueProblem):
                validator.check(value)
    assert issubclass(AudioFileKey, AudioRef)
    assert AudioFileKey.expected == AudioRef.expected


def test_gui_image_ref_works_outside_loading():
    assert GuiImageRef().check("gui/logo.png") == "gui/logo.png"
    with pytest.raises(ValueProblem):
        GuiImageRef().check("logo.png")


@pytest.mark.parametrize("validator, good, bad", [
    (Text(max_chars=3), ["", "abc", "  ", "é" * 3], ["abcd", 3, None, ["a"]]),
    (Text(non_empty=True, max_chars=3), ["a", " a "], ["", "   ", "abcd"]),
    (Text(), ["", "x" * 10_000], [1, False]),
    (NameList(), [[], ["a"], ["a_b", "c"]],
     [["a", "a"], ["A"], [""], ("a",), "a", None, [None]]),
])
def test_text_and_name_list_validators(validator, good, bad):
    for value in good:
        validator.check(value)
    for value in bad:
        with pytest.raises(ValueProblem):
            validator.check(value)


def test_name_list_stores_a_tuple():
    value = NameList().check(["quit", "load"])
    assert value == ("quit", "load") and type(value) is tuple


def test_validator_phrases():
    assert Text().expected == "text"
    assert Text(non_empty=True).expected == "text with at least one visible character"
    assert Text(max_chars=200).expected == "text of at most 200 characters"
    assert Text(non_empty=True, max_chars=9).expected == (
        "text with at least one visible character and at most 9 characters")
    assert NameList.expected == NAMES.removeprefix("must be ")
    assert AudioRef.expected == AUDIO.removeprefix("must be ")


def test_config_fields_maps_toml_keys_to_fields():
    fields = config_fields(WordsConfig)
    assert fields["return"].name == "return_" and "return_" not in fields
    assert list(config_fields(TitleConfig)) == ["enabled", "show_version", "entries"]


def test_menu_constants():
    assert constants.WORD_MAX_CHARS == 200
    assert constants.MESSAGE_WORD_MAX_CHARS == 1000
    assert constants.MENU_ENTRIES_MAX == 16
    assert constants.MENU_ENTRY_NAME_MAX_CHARS == 20


def test_theme_tables_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ThemeConfig().button.focused.border_width = 3      # type: ignore[misc]
