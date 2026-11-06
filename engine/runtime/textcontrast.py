"""Text contrast without pygame (UI-F05-05, W41, W44; moved here from ``app/text_check`` by
the first-game fixes, 2026-11-06).

Why this module exists: W41 (a character's name color hard to read on the name plate, or
its ``text_color`` on the text box) was worked out only by the game's dev launch
(``app/text_check.TextLaunchCheck``), so it reached the game log and never Studio's Problems
or ``engine check``. Studio's check child (``tools/check.py``) has no pygame and can't import
``app``; it can import ``runtime``. So the WCAG math and ``character_warnings`` live here,
and both the game and the check child use them: one rule, two places it is reported.

The contrast (WCAG 2.x, I-6): colors are blended in sRGB as drawn, per channel
``round(fg × a + bg × (1 − a))``, and pure black and pure white bound every backdrop.

Pure Python: ``core`` for the theme types, ``runtime`` for ``Character`` and messages.
"""

from typing import TYPE_CHECKING, Final

from engine.runtime.character import Character
from engine.runtime.errors import format_message

if TYPE_CHECKING:
    from engine.core.config_schema import TextboxTheme

RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)
WHITE: RGB = (255, 255, 255)

NAME_MIN_RATIO: Final = 3.0               # SR-F05-24: names (24 units and up)
TEXT_MIN_RATIO: Final = 4.5               # SR-F05-24, 27: body text


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def relative_luminance(color: RGB) -> float:
    r, g, b = color
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG 2.x contrast of two opaque colors (1.0 to 21.0)."""
    high, low = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def composite(fg: RGB, opacity: float, bg: RGB) -> RGB:
    """``fg`` at ``opacity`` over ``bg``, per channel in sRGB as drawn."""
    return tuple(round(f * opacity + b * (1 - opacity)) for f, b in zip(fg, bg))  # type: ignore


def box_contrast(text: RGB, fill: RGB, opacity: float) -> tuple[float, str]:
    """The worse contrast of ``text`` on the box composited over pure black and over pure
    white, and that backdrop's word (``"black"`` or ``"white"``)."""
    over_black = contrast_ratio(text, composite(fill, opacity, BLACK))
    over_white = contrast_ratio(text, composite(fill, opacity, WHITE))
    return (over_black, "black") if over_black <= over_white else (over_white, "white")


def hex_rgb(color: str) -> RGB:
    """``"#rrggbb"`` as a tuple."""
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def rgb_hex(color: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


def character_warnings(who: str, c: Character, theme: "TextboxTheme") -> list[str]:
    """W41 for one ``Character``, without the place: its name color on the plate (only when
    it has a plate: a name, or ``name_from``) and its ``text_color`` on the box."""
    out = []
    color = c.color
    if type(color) is str and (c.name_from is not None or c.name):
        tab = theme.name_tab
        ratio, _ = box_contrast(hex_rgb(color), tab.fill_color, tab.fill_opacity)
        if ratio < NAME_MIN_RATIO:
            out.append(format_message("W41", ("name", who, color, ratio,
                                              rgb_hex(tab.fill_color))))
    text_color = c.options.get("text_color")
    if type(text_color) is str:
        ratio, backdrop = box_contrast(hex_rgb(text_color), theme.fill_color,
                                       theme.fill_opacity)
        if ratio < TEXT_MIN_RATIO:
            out.append(format_message("W41", ("text", who, text_color, ratio, backdrop,
                                              rgb_hex(theme.fill_color))))
    return out


__all__ = ["BLACK", "NAME_MIN_RATIO", "RGB", "TEXT_MIN_RATIO", "WHITE", "box_contrast",
           "character_warnings", "composite", "contrast_ratio", "hex_rgb",
           "relative_luminance", "rgb_hex"]
