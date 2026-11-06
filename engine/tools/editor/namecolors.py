"""A new character's name color that reads on the game's name plate (first-game fix,
2026-11-06).

Why this module exists: Database ▸ Characters ▸ + New gave each new character the next of a
few fixed colors, and most of them are under W41's 3:1 on the default name plate (Sakura's
``#ffe6f0``: ``#e0a040`` is 1.9:1), so the game's log warned about a color Studio had picked.

``readable(color, fill, opacity)`` keeps the color when it reaches ``NAME_MIN_RATIO`` (3:1)
on the plate drawn over pure black and pure white (the game's W41 rule,
``runtime/textcontrast.box_contrast``), else moves it toward black (a light plate) or white
(a dark one) just far enough, so the hue stays. ``plate_of(root, config_text)`` is the name
plate's fill and opacity in the game's color scheme, from config.toml's open text (unsaved
changes included) or the saved file.

Pure: ``core`` only (no Tk, no pygame).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core.config import load_config
from engine.core.config_schema import NameTabTheme
from engine.core.constants import CONFIG_FILENAME
from engine.core.errors import AssetTooLarge
from engine.core.palette import contrast, ensure

NAME_MIN_RATIO: Final = 3.0         # W41's names rule (runtime/textcontrast.NAME_MIN_RATIO)
_BLACK: Final = "#000000"
_WHITE: Final = "#ffffff"

RGB = tuple[int, int, int]


def _hex(rgb: Sequence[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _rgb(color: str) -> RGB:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _over(fill: RGB, opacity: float, back: RGB) -> str:
    """``fill`` at ``opacity`` over ``back``, per channel as the game draws it."""
    return _hex([round(f * opacity + b * (1 - opacity)) for f, b in zip(fill, back)])


def backdrops(fill: RGB, opacity: float) -> tuple[str, str]:
    """The plate as drawn over pure black and over pure white."""
    return _over(fill, opacity, (0, 0, 0)), _over(fill, opacity, (255, 255, 255))


def ratio(color: str, fill: RGB, opacity: float) -> float:
    """``color``'s worse contrast on the plate (W41's number)."""
    return min(contrast(color, back) for back in backdrops(fill, opacity))


def readable(color: str, fill: RGB, opacity: float) -> str:
    """``color`` (``#rrggbb``), or the nearest shade of it that reaches 3:1 on the plate."""
    if ratio(color, fill, opacity) >= NAME_MIN_RATIO:
        return color.lower()
    backs = backdrops(fill, opacity)
    tries = [ensure(color, backs, NAME_MIN_RATIO, toward).lower() for toward in (_BLACK, _WHITE)]
    passing = [c for c in tries if ratio(c, fill, opacity) >= NAME_MIN_RATIO]
    if passing:          # the least change: the shade nearer the color it started from
        return min(passing, key=lambda c: sum(abs(a - b) for a, b in zip(_rgb(c), _rgb(color))))
    return max(tries, key=lambda c: ratio(c, fill, opacity))


@dataclass(frozen=True)
class _ConfigText:
    """A ``GamePaths`` stand-in for ``load_config``: config.toml's open text."""

    data: bytes

    def read_file(self, ref: str, *, max_bytes: int, regular: bool = False) -> bytes:
        if ref != CONFIG_FILENAME:
            raise FileNotFoundError(ref)
        if len(self.data) > max_bytes:
            raise AssetTooLarge(ref, max_bytes)
        return self.data


def plate_of(root: Path, config_text: bytes | None) -> tuple[RGB, float]:
    """The name plate's fill and opacity in the game's color scheme (defaults when
    config.toml can't be read)."""
    try:
        if config_text is not None:
            loaded = load_config(_ConfigText(config_text))   # type: ignore[arg-type]
        else:
            from engine.core.paths import GamePaths
            loaded = load_config(GamePaths.for_game(root))
        tab = loaded.config.theme.textbox.name_tab
    except Exception:  # noqa: BLE001  (a config that can't load: the default plate)
        tab = NameTabTheme()
    return tab.fill_color, tab.fill_opacity


__all__ = ["NAME_MIN_RATIO", "backdrops", "plate_of", "ratio", "readable"]
