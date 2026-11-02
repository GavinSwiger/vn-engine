"""F11 steps 5–6 config: ``[theme.save]``, ``[theme.notice]`` (03-ui "Theme tokens"; 04 §13)
and the 32 F11 ``[words]`` keys (03-ui's 22 and 04 §13's 10). Notice colors and opacity
default to None, meaning "follow ``panel.*``" (``ui/notice.notice_style``)."""

import pytest

from engine.core.config_schema import (
    F11_THEME_AREAS,
    AudioRef,
    Config,
    GuiImageRef,
    HexColor,
    IntRange,
    Opacity,
    ThemeConfig,
    WordsConfig,
    config_fields,
)

LINE2 = "config.toml, line 2: "

TOKENS = [
    # key, validator kind, default, min, max
    ("save.text_size", IntRange, 24, 24, 36),
    ("save.badge.fill_color", HexColor, (0xFF, 0xF4, 0xF8), None, None),
    ("save.badge.fill_opacity", Opacity, 0.90, None, None),
    ("save.badge.text_color", HexColor, (0x3D, 0x2B, 0x36), None, None),
    ("save.newest.fill_color", HexColor, (0xA0, 0x28, 0x60), None, None),
    ("save.newest.text_color", HexColor, (0xFF, 0xFF, 0xFF), None, None),
    ("save.placeholder.fill_color", HexColor, (0xF0, 0xD0, 0xDE), None, None),
    ("save.placeholder.text_color", HexColor, (0x3D, 0x2B, 0x36), None, None),
    ("save.no_picture_image", GuiImageRef, None, None, None),
    ("save.load_fade_ms", IntRange, 300, 0, 2000),
    ("notice.fill_color", HexColor, None, None, None),
    ("notice.fill_opacity", Opacity, None, None, None),
    ("notice.border_color", HexColor, None, None, None),
    ("notice.border_width", IntRange, 2, 0, 8),
    ("notice.corner_radius", IntRange, 12, 0, 28),
    ("notice.frame_image", GuiImageRef, None, None, None),
    ("notice.frame_slice_width", IntRange, 24, 0, 96),
    ("notice.text_size", IntRange, 24, 24, 36),
    ("notice.text_color", HexColor, None, None, None),
    ("notice.marker.fill_color", HexColor, None, None, None),
    ("notice.max_width", IntRange, 560, 320, 800),
    ("notice.duration_ms", IntRange, 1500, 1000, 10000),
    ("notice.fade_ms", IntRange, 200, 0, 1000),
    ("notice.sound", AudioRef, None, None, None),
]
NUMERIC = [row for row in TOKENS if row[1] is IntRange]


def lookup(obj: object, dotted: str) -> object:
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def leaf_keys(cls: type, prefix: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, f in config_fields(cls).items():
        validator = f.metadata["validator"]
        cls_ = getattr(validator, "cls", None)
        if cls_ is not None:
            out.update(leaf_keys(cls_, f"{prefix}{key}."))
        else:
            out[prefix + key] = validator
    return out


def f11_fields() -> dict[str, object]:
    areas = config_fields(ThemeConfig)
    out: dict[str, object] = {}
    for area in F11_THEME_AREAS:
        out.update(leaf_keys(areas[area].metadata["validator"].cls, area + "."))
    return out


def toml_for(dotted: str, value: str) -> str:
    *tables, key = dotted.split(".")
    return f"[theme.{'.'.join(tables)}]\n{key} = {value}\n"


def test_the_two_areas_have_exactly_03_ui_tokens():
    assert F11_THEME_AREAS == ("save", "notice")
    assert set(f11_fields()) == {row[0] for row in TOKENS}


@pytest.mark.parametrize("key, kind, default, lo, hi", TOKENS, ids=[r[0] for r in TOKENS])
def test_defaults_and_validators(load, key, kind, default, lo, hi):
    result = load("")
    assert result.errors == [] and result.warnings == []
    assert lookup(result.config.theme, key) == default
    validator = f11_fields()[key]
    assert type(validator) is kind
    if kind is IntRange:
        assert (validator.lo, validator.hi) == (lo, hi)


@pytest.mark.parametrize("key, kind, default, lo, hi", NUMERIC, ids=[r[0] for r in NUMERIC])
def test_ranges(load, key, kind, default, lo, hi):
    *tables, name = key.split(".")
    for value in (lo, hi):
        result = load(toml_for(key, str(value)))
        assert result.errors == [] and lookup(result.config.theme, key) == value
    for value in (lo - 1, hi + 1):
        result = load(toml_for(key, str(value)))
        assert [e.format() for e in result.errors] == [
            f"{LINE2}[theme.{'.'.join(tables)}] {name} must be a whole number from {lo} to "
            f"{hi}, but found {value}"]


@pytest.mark.parametrize("key, text, stored", [
    ("notice.fill_color", '"#102030"', (16, 32, 48)),
    ("notice.fill_opacity", "0.5", 0.5),
    ("notice.border_color", '"#000000"', (0, 0, 0)),
    ("notice.text_color", '"#FFFFFF"', (255, 255, 255)),
    ("notice.marker.fill_color", '"#00FF00"', (0, 255, 0)),
    ("notice.frame_image", '"gui/notice.png"', "gui/notice.png"),
    ("notice.sound", '"sfx/notice.ogg"', "sfx/notice.ogg"),
    ("save.no_picture_image", '"gui/no_picture.png"', "gui/no_picture.png"),
    ("save.badge.fill_opacity", "1", 1.0),
], ids=repr)
def test_values_load(load, key, text, stored):
    result = load(toml_for(key, text))
    assert result.errors == [] and result.warnings == []
    assert lookup(result.config.theme, key) == stored


@pytest.mark.parametrize("key, text, phrase", [
    ("notice.fill_color", '"red"', 'must be a color like "#RRGGBB"'),
    ("notice.fill_opacity", "1.5", "must be a number from 0.0 to 1.0, such as 0.85 for 85%"),
    ("notice.frame_image", '"notice.png"', 'must be an image in gui/, e.g. "gui/textbox.png"'),
    ("notice.sound", '"audio/x.ogg"',
     'must be a file inside audio/ with its extension, e.g. "bgm/festival.ogg"'),
], ids=repr)
def test_bad_values(load, key, text, phrase):
    *tables, name = key.split(".")
    [error] = load(toml_for(key, text)).errors
    assert error.format().startswith(f"{LINE2}[theme.{'.'.join(tables)}] {name} {phrase}, ")


def test_unknown_notice_key_warns(load):
    result = load('[theme.notice]\nduration = 3000\n')
    assert result.errors == []
    assert result.warnings == [LINE2 + 'unknown key [theme.notice] duration — did you mean '
                               '"duration_ms"?']


# --- [words] -------------------------------------------------------------------------------

F11_WORDS = {
    "q_save": "Q.Save", "q_load": "Q.Load", "save_page_auto": "Auto",
    "save_page_quick": "Quick", "save_slot": "Slot", "save_newest": "Newest",
    "save_empty": "Empty slot", "save_loading": "Loading…", "save_no_picture": "No picture",
    "save_none": "No saves yet.", "save_damaged": "Damaged save",
    "save_newer": "Made by a newer version of the game.",
    "save_other_game": "This save is from a different game.",
    "confirm_overwrite": "Overwrite this save?", "confirm_delete": "Delete this save?",
    "confirm_load": "Load this save? Unsaved progress will be lost.",
    "confirm_nearest": "The story has changed since this save. Continue from the nearest "
                       "point?",
    "confirm_main_menu_autosave": "Return to the title screen?",
    "confirm_quit_autosave": "Quit the game?",
    "notice_quick_saved": "Quick saved.", "notice_no_quick_save": "No quick save yet.",
    "notice_cant_save": "Can't save right now.",
    # 04 §13
    "notice_save_failed": "Couldn't save:", "save_reason_disk_full": "the disk is full.",
    "save_reason_folder": "the save folder can't be written.",
    "save_reason_other": "the file couldn't be written.",
    "save_reason_slots": "every slot on that page holds a save this version can't replace.",
    "notice_too_large": "This save is too large.",
    "notice_load_damaged": "This save is damaged and can't be loaded.",
    "notice_load_no_fit": "This save no longer fits the story and can't be loaded.",
    "notice_load_failed": "This save couldn't be loaded.",
    "notice_delete_failed": "Couldn't delete this save.",
}


def test_f11_words_follow_f10s_with_english_defaults():
    keys = list(config_fields(WordsConfig))
    assert keys[20:20 + len(F11_WORDS)] == list(F11_WORDS) and len(F11_WORDS) == 32
    words = Config().words
    assert {key: getattr(words, key) for key in F11_WORDS} == F11_WORDS


@pytest.mark.parametrize("key", list(F11_WORDS))
def test_each_f11_word_has_its_limit(load, key):
    limit = 1000 if key.startswith("confirm_") else 200
    result = load(f'[words]\n{key} = "{"é" * limit}"\n')
    assert result.errors == []
    result = load(f'[words]\n{key} = "{"é" * (limit + 1)}"\n')
    assert [e.format() for e in result.errors] == [
        f"{LINE2}[words] {key} must be text of at most {limit} characters, but found the text "
        f'"{"é" * 39}…"']
