"""Palettes in, color schemes out (2026-11-05): read a palette from the formats other tools
use, and turn its colors into the eleven scheme roles (``schemes.ROLES``).

Why this module exists: authors find palettes on Lospec, Coolors, Adobe Color or in their
art program, and want their game's menus in those colors without picking 60 colors by hand.
Tools that build a UI theme from a palette (Material's theme builder and the like) take a
few seed colors and compute every role from them, with contrast rules; this does the same,
so an imported palette is always readable.

- ``read_palette(data)``: ``"#RRGGBB"`` colors in file order, without repeats (at most
  ``MAX_COLORS``). It reads Adobe Swatch Exchange (``.ase``, binary), Photoshop color tables
  (``.act``), GIMP (``.gpl``), JASC / Paint Shop Pro (``.pal``), Paint.NET (``.txt``), and
  any text with colors in it: a Lospec ``.hex`` file, a Coolors link
  (``coolors.co/264653-2a9d8f-…``), CSS (``#abc``, ``#aabbcc``, ``rgb(1, 2, 3)``), or a
  pasted list. A ``PaletteError`` says why nothing was found.
- ``derive_roles(colors, dark=None)``: the roles, light or dark (None: whichever gives the
  text more contrast). The background is the palette's lightest (or darkest) color, the
  text its most contrasting, the accents its most colorful; the in-between fills are mixed
  from the background and the accent, and text, accents, muted text and tracks are moved
  toward black or white until they meet W67's minimums (4.5:1 text, 3:1 graphics) on every
  fill they are drawn on (``app/ui_contrast.PAIRS``).
- ``contrast(a, b)``: WCAG 2 contrast of two ``"#RRGGBB"`` colors.

Pure Python, stdlib only.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

MAX_BYTES: Final = 1024 * 1024
MAX_COLORS: Final = 256

NOTHING: Final = ("No colors found. Paste hex colors (#264653), a Coolors link, or open a "
                  ".hex, .gpl, .pal, .ase, .act or .txt palette file.")
TOO_BIG: Final = "That file is too big for a palette (over 1 MB)."
BAD_ASE: Final = "That .ase file couldn't be read."

ROLES: Final = ("fill", "text", "border", "accent", "accent2", "soft", "focus", "pressed",
                "muted", "track", "toggle")
TEXT: Final = 4.5
GRAPHIC: Final = 3.0

RGB = tuple[int, int, int]


class PaletteError(ValueError):
    """Why a palette gave no colors (``text`` is shown to the author)."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


# --- Reading --------------------------------------------------------------------------------

def hex_of(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb[:3])


def rgb_of(color: str) -> RGB:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _unique(colors: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(colors))[:MAX_COLORS]


def read_palette(data: bytes | str) -> tuple[str, ...]:
    """The palette's colors (module docstring); ``PaletteError`` when there are none."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise PaletteError(TOO_BIG)
    if data[:4] == b"ASEF":
        colors = _ase(data)
    elif len(data) in (768, 772) and not _texty(data):
        colors = _act(data)
    else:
        colors = _text(data.decode("utf-8", "replace"))
    found = _unique(colors)
    if not found:
        raise PaletteError(NOTHING)
    return found


def _texty(data: bytes) -> bool:
    return all(b in b"\t\r\n" or 32 <= b < 127 for b in data[:256])


def _act(data: bytes) -> list[str]:
    """Photoshop ``.act``: 256 RGB triples, then (optionally) the count used."""
    count = 256
    if len(data) == 772:
        count = max(1, min(256, struct.unpack(">H", data[768:770])[0] or 256))
    return [hex_of(data[i * 3:i * 3 + 3]) for i in range(count)]


def _ase(data: bytes) -> list[str]:
    """Adobe Swatch Exchange: color blocks (RGB, CMYK, Gray; LAB is skipped)."""
    out: list[str] = []
    try:
        (blocks,) = struct.unpack(">I", data[8:12])
        at = 12
        for _ in range(min(blocks, 65536)):
            kind, length = struct.unpack(">HI", data[at:at + 6])
            body = data[at + 6:at + 6 + length]
            at += 6 + length
            if kind != 0x0001:
                continue
            (chars,) = struct.unpack(">H", body[:2])
            spot = 2 + chars * 2
            model = body[spot:spot + 4]
            values = body[spot + 4:]
            if model == b"RGB ":
                r, g, b = struct.unpack(">3f", values[:12])
                out.append(hex_of((r * 255, g * 255, b * 255)))
            elif model == b"CMYK":
                c, m, y, k = struct.unpack(">4f", values[:16])
                out.append(hex_of(tuple(255 * (1 - v) * (1 - k) for v in (c, m, y))))
            elif model == b"Gray":
                (v,) = struct.unpack(">f", values[:4])
                out.append(hex_of((v * 255,) * 3))
    except struct.error:
        raise PaletteError(BAD_ASE) from None
    return out


_HASH: Final = re.compile(r"#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})(?![0-9A-Za-z])")
_BARE: Final = re.compile(r"(?<![0-9A-Za-z#])([0-9A-Fa-f]{6})(?![0-9A-Za-z])")
_RGB_CALL: Final = re.compile(r"rgba?\(\s*(\d{1,3})\s*[, ]\s*(\d{1,3})\s*[, ]\s*(\d{1,3})")
_TRIPLE: Final = re.compile(r"^\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})(?:\s|$)")


def _text(text: str) -> list[str]:
    lines = text.splitlines()
    head = lines[0].strip() if lines else ""
    if head.startswith(("GIMP Palette", "JASC-PAL")):
        # GIMP: "R G B name" rows after Name:/Columns:; JASC: a version and a count first.
        rows = lines[3:] if head.startswith("JASC-PAL") else lines[1:]
        return [hex_of(tuple(int(n) for n in m.groups())) for row in rows
                if (m := _TRIPLE.match(row)) and all(int(n) <= 255 for n in m.groups())]
    if "paint.net" in text.casefold():
        # Paint.NET: AARRGGBB per line, ";" comments.
        return ["#" + row.strip()[2:].upper() for row in lines
                if re.fullmatch(r"[0-9A-Fa-f]{8}", row.strip())]
    found: list[tuple[int, str]] = []
    for match in _HASH.finditer(text):
        value = match.group(1)
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        found.append((match.start(), "#" + value[:6].upper()))
    for match in _RGB_CALL.finditer(text):
        parts = [int(n) for n in match.groups()]
        if all(n <= 255 for n in parts):
            found.append((match.start(), hex_of(parts)))
    if not found:            # a Coolors link or a .hex file: bare hex, no "#"
        found = [(m.start(), "#" + m.group(1).upper()) for m in _BARE.finditer(text)]
    return [color for _at, color in sorted(found)]


# --- Color math -----------------------------------------------------------------------------

def _channel(c: int) -> float:
    v = c / 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = rgb_of(color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """``a`` moved ``t`` (0–1) of the way to ``b``."""
    ra, rb = rgb_of(a), rgb_of(b)
    return hex_of(tuple(x + (y - x) * t for x, y in zip(ra, rb, strict=True)))


def _chroma(color: str) -> int:
    rgb = rgb_of(color)
    return max(rgb) - min(rgb)


def _hue(color: str) -> float:
    r, g, b = (c / 255 for c in rgb_of(color))
    top, low = max(r, g, b), min(r, g, b)
    if top == low:
        return 0.0
    d = top - low
    if top == r:
        h = ((g - b) / d) % 6
    elif top == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60


SEE_THROUGH: Final = 0.2       # the text box's fill is 80% opaque: its text is checked so
SEE_THROUGH_UI: Final = 0.1    # buttons, choices and the quick menu: 90%


def seen(fill: str, amount: float = SEE_THROUGH) -> tuple[str, str, str]:
    """``fill`` as it can be drawn: solid, and see-through by ``amount`` over black and over
    white (W67 composites a see-through fill over both)."""
    return fill, mix(fill, "#000000", amount), mix(fill, "#FFFFFF", amount)


def ensure(color: str, against: Sequence[str], ratio: float, toward: str) -> str:
    """``color`` moved toward ``toward`` (black or white) just far enough to reach
    ``ratio`` against every color of ``against`` (or all the way)."""
    for step in range(21):
        moved = mix(color, toward, step / 20)
        if all(contrast(moved, other) >= ratio for other in against):
            return moved
    return toward


# --- Roles ----------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Derived:
    """A palette's roles (role → ``"#RRGGBB"``, ``ROLES`` order) and which way it went."""

    roles: dict[str, str]
    dark: bool


def settled(fill: str, dark: bool) -> str:
    """``fill`` darkened (or lightened, for a light scheme) just enough that white (or black)
    text reaches 7:1 on it as drawn over either backdrop; a light one also 15:1 solid, so
    its accents can keep their color (W67 checks them over black too)."""
    far, near = ("#FFFFFF", "#000000") if dark else ("#000000", "#FFFFFF")
    for step in range(21):
        moved = mix(fill, near, step / 20)
        if all(contrast(far, shade) >= 7.0 for shade in seen(moved)) and (
                dark or contrast(far, moved) >= 15.0):
            return moved
    return near


def complete_roles(fill: str, text: str, accent: str, accent2: str | None = None,
                   border: str | None = None, *, dark: bool,
                   tint: str | None = None) -> dict[str, str]:
    """Every role from the five a person picks first; the rest are mixed (the in-between
    fills from ``fill`` toward ``tint``, the accent unless given), and colors that are
    drawn over the fills are moved until they meet W67's minimums."""
    far, near = ("#FFFFFF", "#000000") if dark else ("#000000", "#FFFFFF")
    fill = settled(fill, dark)
    accent2 = accent2 or accent
    tint = tint or accent
    for scale in (1.0, 0.75, 0.5, 0.3, 0.15):
        soft = mix(fill, tint, 0.12 * scale)
        focus = mix(fill, tint, 0.24 * scale)
        pressed = mix(fill, tint, 0.36 * scale)
        fills = [shade for f in (fill, soft, focus, pressed) for shade in seen(f)]
        sure = ensure(text, fills, 7.0 if scale == 1.0 else TEXT, far)
        if all(contrast(sure, f) >= TEXT for f in fills):
            break
    ui = SEE_THROUGH_UI
    base, held = seen(fill, ui), [shade for f in (focus, pressed) for shade in seen(f, ui)]
    roles = {"fill": fill, "text": sure, "soft": soft, "focus": focus, "pressed": pressed}
    roles["accent"] = ensure(ensure(accent, (*base, *seen(soft, ui)), TEXT, far), held,
                             GRAPHIC, far)
    roles["accent2"] = ensure(accent2, held, GRAPHIC, far)
    if border is None or not 1.3 <= contrast(border, fill) <= 6:
        border = mix(fill, roles["accent"], 0.5)
    roles["border"] = border
    # Muted text is also the flowchart's unknown text, drawn on the focus fill.
    roles["muted"] = ensure(mix(roles["text"], fill, 0.35), (*base, focus), TEXT, far)
    roles["track"] = mix(fill, roles["text"], 0.18)
    roles["toggle"] = ensure(mix(roles["accent"], roles["text"], 0.35), (*base, *held),
                             GRAPHIC, far)
    return {role: roles[role] for role in ROLES}


def derive_roles(colors: Sequence[str], dark: bool | None = None) -> Derived:
    """The roles for ``colors`` (module docstring)."""
    if not colors:
        raise PaletteError(NOTHING)
    if dark is None:
        # The way whose background needs the least change; then the most text contrast.
        def cost(way: bool) -> tuple[float, float]:
            fill, text = _pick(colors, way)
            return (abs(luminance(settled(fill, way)) - luminance(fill)),
                    -contrast(fill, text))
        dark = cost(True) < cost(False)
    fill = _pick(colors, dark)[0]
    ground = settled(fill, dark)
    rest = [c for c in colors if c != fill]
    # The accent: colorful and already readable on the background; the text: the most
    # contrasting of the others (white or black when none is near enough).
    accent = max(rest, key=lambda c: _chroma(c) * min(contrast(c, ground) / TEXT, 1.0),
                 default=None)
    others = [c for c in rest if c != accent]
    text = max(others, key=lambda c: contrast(c, ground), default=None)
    if text is None or contrast(text, ground) < GRAPHIC:
        text = "#FFFFFF" if dark else "#000000"
    accent = accent or text
    lively = sorted((c for c in others if c != text), key=_chroma, reverse=True)
    accent2 = next((c for c in lively if _chroma(c) >= 24
                    and min(abs(_hue(c) - _hue(accent)), 360 - abs(_hue(c) - _hue(accent)))
                    >= 30), None)
    border = min(others, key=lambda c: abs(contrast(c, fill) - 2.2)) if others else None
    return Derived(complete_roles(fill, text, accent, accent2, border, dark=dark), dark)


def _pick(colors: Sequence[str], dark: bool) -> tuple[str, str]:
    """(background, text): the darkest or lightest color, and the one farthest from it."""
    fill = (min if dark else max)(colors, key=luminance)
    text = max(colors, key=lambda c: contrast(c, fill))
    if text == fill:
        text = "#FFFFFF" if dark else "#000000"
    return fill, text


__all__ = ["BAD_ASE", "Derived", "GRAPHIC", "MAX_BYTES", "MAX_COLORS", "NOTHING",
           "PaletteError", "ROLES", "TEXT", "SEE_THROUGH", "SEE_THROUGH_UI", "TOO_BIG", "complete_roles", "contrast",
           "derive_roles", "ensure", "hex_of", "luminance", "mix", "read_palette", "rgb_of",
           "seen"]
