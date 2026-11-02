"""F07 step 4 — ``[theme.choice]`` (F07 ``04`` §13; design §6.4): every token is read with
its range, and a bad value stops the launch with F01's config error shape (AC-F01-11)
naming the key. AC-F07-37's invalid rows; its on-screen rows are in
``tests/app/test_choice_install.py``."""

import pytest

from engine.core.config_schema import (
    ChoiceFocusedTheme,
    ChoiceLockedTheme,
    ChoiceMarkerTheme,
    ChoiceTheme,
    Config,
    IntRange,
    Table,
    ThemeConfig,
    config_fields,
)

LINE2 = "config.toml, line 2: "
AUDIO = 'must be a file inside audio/ with its extension, e.g. "bgm/festival.ogg"'


def messages(result) -> list[str]:
    return [error.format() for error in result.errors]


def leaf_keys(cls: type, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, f in config_fields(cls).items():
        validator = f.metadata["validator"]
        if isinstance(validator, Table):
            out.update(leaf_keys(validator.cls, f"{prefix}{key}."))
        else:
            out[prefix + key] = validator
    return out


def test_every_design_token_is_a_config_key():
    """Design §6.4's 26 tokens (the paddings as two), no more."""
    assert set(leaf_keys(ChoiceTheme)) == {
        "text_font", "text_size", "text_color", "fill_color", "fill_opacity", "border_color",
        "border_width", "corner_radius", "frame_image", "frame_slice_width", "width", "gap",
        "side_padding", "top_padding", "bottom_padding", "focused.fill_color",
        "focused.border_color", "focused.border_width", "focused.frame_image",
        "marker.fill_color", "locked.text_color", "locked.fill_opacity", "focus_sound",
        "pick_sound", "fade_in_ms"}
    assert isinstance(config_fields(ThemeConfig)["choice"].metadata["validator"], Table)


def test_04_13_ranges():
    tokens = leaf_keys(ChoiceTheme)
    for key, lo, hi in [
        ("text_size", 20, 48), ("border_width", 0, 16), ("focused.border_width", 0, 16),
        ("corner_radius", 0, 64), ("gap", 0, 64), ("top_padding", 0, 64),
        ("bottom_padding", 0, 64), ("side_padding", 0, 200), ("frame_slice_width", 1, 128),
        ("width", 400, 1200), ("fade_in_ms", 0, 1000),
    ]:
        validator = tokens[key]
        assert isinstance(validator, IntRange) and (validator.lo, validator.hi) == (lo, hi), key


def test_defaults_are_unchanged_by_opening_the_tokens():
    theme = Config().theme.choice
    assert theme == ChoiceTheme(focused=ChoiceFocusedTheme(), marker=ChoiceMarkerTheme(),
                                locked=ChoiceLockedTheme())
    assert (theme.fill_opacity, theme.locked.fill_opacity, theme.fade_in_ms) == (0.9, 0.9, 120)
    assert theme.focus_sound is None and theme.pick_sound is None
    assert ThemeConfig().choice == theme                    # design §6.4 and 07 I-3
    assert (theme.width, theme.gap, theme.side_padding, theme.top_padding) == (800, 12, 40, 10)
    assert theme.text_size is None and theme.text_font is None


INVALID = [
    ("[theme.choice]", "width = 1300",
     "[theme.choice] width must be a whole number from 400 to 1200, but found 1300"),
    ("[theme.choice]", "text_size = 19",
     "[theme.choice] text_size must be a whole number from 20 to 48, but found 19"),
    ("[theme.choice]", "fade_in_ms = 1001",
     "[theme.choice] fade_in_ms must be a whole number from 0 to 1000, but found 1001"),
    ("[theme.choice]", "gap = 65",
     "[theme.choice] gap must be a whole number from 0 to 64, but found 65"),
    ("[theme.choice]", "side_padding = 201",
     "[theme.choice] side_padding must be a whole number from 0 to 200, but found 201"),
    ("[theme.choice]", "frame_slice_width = 0",
     "[theme.choice] frame_slice_width must be a whole number from 1 to 128, but found 0"),
    ("[theme.choice]", "border_width = 17",
     "[theme.choice] border_width must be a whole number from 0 to 16, but found 17"),
    ("[theme.choice]", "fill_opacity = 1.5",
     "[theme.choice] fill_opacity must be a number from 0.0 to 1.0, such as 0.85 for 85%, "
     "but found 1.5"),
    ("[theme.choice]", 'text_color = "pink"',
     '[theme.choice] text_color must be a color like "#RRGGBB", but found the text "pink"'),
    ("[theme.choice]", 'focus_sound = "/x.ogg"',
     f'[theme.choice] focus_sound {AUDIO}, but found the text "/x.ogg"'),
    ("[theme.choice]", 'focus_sound = "../x.ogg"',
     f'[theme.choice] focus_sound {AUDIO}, but found the text "../x.ogg"'),
    ("[theme.choice]", 'focus_sound = "pick"',
     f'[theme.choice] focus_sound {AUDIO}, but found the text "pick"'),
    ("[theme.choice.focused]", "border_width = 17",
     "[theme.choice.focused] border_width must be a whole number from 0 to 16, but found 17"),
    ("[theme.choice.locked]", "fill_opacity = -0.1",
     "[theme.choice.locked] fill_opacity must be a number from 0.0 to 1.0, such as 0.85 for "
     "85%, but found -0.1"),
    ("[theme.choice]", 'frame_image = "images/b.png"',
     '[theme.choice] frame_image must be an image in gui/, e.g. "gui/textbox.png", but found '
     'the text "images/b.png"'),
]


@pytest.mark.parametrize("header, line, message", INVALID,
                         ids=[f"{row[0]} {row[1]}" for row in INVALID])
def test_ac37_invalid_values_stop_the_launch(load, header, line, message):
    result = load(f"{header}\n{line}\n")
    assert messages(result) == [LINE2 + message]
    assert result.loaded is False


def test_ac37_valid_values_are_read(load):
    result = load('[theme.choice]\nfill_color = "#000000"\nfill_opacity = 1.0\nwidth = 400\n'
                  'gap = 0\ntext_size = 20\nfocus_sound = "sfx/focus.ogg"\n'
                  'frame_image = "gui/choice.png"\n'
                  '[theme.choice.focused]\nborder_width = 8\n'
                  '[theme.choice.locked]\ntext_color = "#101010"\n')
    assert result.errors == [] and result.warnings == [] and result.loaded
    theme = result.config.theme.choice
    assert theme.fill_color == (0, 0, 0) and theme.fill_opacity == 1.0
    assert (theme.width, theme.gap, theme.text_size) == (400, 0, 20)
    assert theme.focus_sound == "sfx/focus.ogg" and theme.frame_image == "gui/choice.png"
    assert theme.focused.border_width == 8 and theme.locked.text_color == (16, 16, 16)
    assert theme.focused.fill_color == ChoiceFocusedTheme().fill_color


def test_unknown_choice_keys_still_warn(load):
    result = load('[theme.choice]\ntext_colour = "#000000"\n')
    assert result.errors == [] and result.loaded
    assert result.warnings == [LINE2 + 'unknown key [theme.choice] text_colour — did you mean '
                               '"text_color"?']
