"""F17 ``[theme.nvl]``: its tokens, ranges, textbox fallbacks, and default contrast
(``06-acceptance.md`` AC-F17-31)."""

import pytest

from engine.app.text_check import box_contrast, composite, contrast_ratio
from engine.core.config_schema import NvlTheme, Opacity
from engine.render.nvllayout import nvl_look

FILL = (0xFF, 0xF4, 0xF8)

# key (as written), low end, high end, values out of range
RANGES = [
    ("fill_opacity", "0.5", "1.0", ("0.49", "1.01")),
    ("width", "640", "1200", ("639", "1201")),
    ("top_gap", "24", "200", ("23", "201")),
    ("bottom_gap", "40", "200", ("39", "201")),
    ("line_gap", "0", "80", ("-1", "81")),
    ("text_size", "20", "48", ("19", "49")),
]
BAD_COLORS = [("", "text_color", '"#12345"'), (".name", "text_color", '"red"'),
              (".indicator", "fill_color", '"#GGGGGG"')]


def _attr(theme: NvlTheme, key: str):
    return getattr(theme, key)


def test_ac_f17_31_tokens_and_default_contrast(load):
    # Defaults: the textbox's where [theme.nvl] says nothing.
    result = load("")
    assert result.errors == [] and result.warnings == []
    got = nvl_look(result.config.theme)
    assert (got.fill_color, got.fill_opacity, got.width, got.top_gap, got.bottom_gap,
            got.line_gap, got.text_size) == (FILL, 0.85, 920, 64, 72, 20, 28)
    assert got.text_color == (0x3D, 0x2B, 0x36) and got.name_color == (0xA0, 0x28, 0x60)
    assert got.indicator_color == result.config.theme.textbox.indicator.fill_color
    # Fallbacks follow the textbox; a [theme.nvl] value wins.
    box = load('[theme.textbox]\nfill_color = "#202020"\ntext_size = 32\n').config.theme
    assert (nvl_look(box).fill_color, nvl_look(box).text_size) == ((0x20, 0x20, 0x20), 32)
    both = load('[theme.textbox]\nfill_color = "#202020"\ntext_size = 32\n'
                '[theme.nvl]\nfill_color = "#101010"\ntext_size = 24\n'
                '[theme.nvl.name]\ntext_color = "#205080"\n'
                '[theme.nvl.indicator]\nfill_color = "#204020"\n').config.theme
    look = nvl_look(both)
    assert (look.fill_color, look.text_size) == ((0x10, 0x10, 0x10), 24)
    assert look.name_color == (0x20, 0x50, 0x80) and look.indicator_color == (0x20, 0x40, 0x20)
    # Range ends pass; one ConfigError per bad value, naming the key, the default kept.
    default = NvlTheme()
    for key, low, high, bad in RANGES:
        for value in (low, high):
            result = load(f"[theme.nvl]\n{key} = {value}\n")
            assert result.errors == [], (key, value)
            assert _attr(result.config.theme.nvl, key) == float(value)
        for value in bad:
            result = load(f"[theme.nvl]\n{key} = {value}\n")
            assert len(result.errors) == 1, (key, value)
            assert f"[theme.nvl] {key} must be" in result.errors[0].format()
            assert _attr(result.config.theme.nvl, key) == _attr(default, key)
    for table, key, value in BAD_COLORS:
        result = load(f"[theme.nvl{table}]\n{key} = {value}\n")
        assert len(result.errors) == 1
        assert f"[theme.nvl{table}] {key} must be" in result.errors[0].format()
    assert load("[theme.nvl]\nfill_opacity = 0.49\n").errors[0].format().endswith(
        "must be a number from 0.5 to 1.0, such as 0.85 for 85%, but found 0.49")
    # No [nvl] section: F01's unknown-key warning.
    result = load("[nvl]\nwidth = 900\n")
    assert result.errors == [] and len(result.warnings) == 1
    assert "[nvl]" in result.warnings[0].format()
    # [theme.textbox] fill_opacity keeps 0.0–1.0 (AC-F05-09's rows).
    assert Opacity().expected == "a number from 0.0 to 1.0, such as 0.85 for 85%"
    for value in ("0.0", "1.0"):
        assert load(f"[theme.textbox]\nfill_opacity = {value}\n").errors == []
    assert len(load("[theme.textbox]\nfill_opacity = 1.01\n").errors) == 1
    # Default contrast with F05's function (over black / white).
    def ratios(color):
        black = box_contrast(color, FILL, 0.85)
        assert black[1] == "black"
        white = contrast_ratio(color, composite(FILL, 0.85, (255, 255, 255)))
        return black[0], white

    body, name = ratios(got.text_color), ratios(got.name_color)
    assert body == (pytest.approx(8.65, abs=0.01), pytest.approx(12.40, abs=0.01))
    assert name == (pytest.approx(4.66, abs=0.01), pytest.approx(6.67, abs=0.01))
    assert ratios(got.indicator_color) == name
    for tag in ((0x9A, 0x1C, 0x14), (0x1E, 0x4A, 0x9C)):       # F05's tag colors
        assert min(ratios(tag)) >= 4.5
