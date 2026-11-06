"""The six device looks' colors (F65 round 3, "Phone and letter skins" and "Radio, terminal
and mind skins").

Why this module exists: a message that comes by phone, letter, pigeon, radio, terminal or
mind is drawn in the Inbox and in its arrival notice in a look of its own, and Studio's
Game settings ▸ Devices previews the same look. Both read their colors here, from the
game's theme tokens, so all 28 color schemes (and an author's own colors) dress every look
and its text stays readable.

- ``device_palette(look, token)``: the look's ``DevicePalette``; ``token(path)`` gives a
  theme color token (``"panel.fill_color"``) as ``"#RRGGBB"``. The game passes its resolved
  ``[theme]`` (``ui/devicelook``), Studio the scheme's colors with the author's own over
  them (``editor/devicemodel``).
- Every text color is checked against the fill it sits on (4.5:1, WCAG AA, as W67's text
  pairs): a derived fill (the letter's paper, the terminal's screen) moves less far from
  the panel while it would cost the text its contrast, and a text color that still falls
  short becomes the most readable of the panel's text, the panel's fill, black or white.
  Marks (the wax seal, the cursor, the static) are graphics: 3:1.
- ``PAIRS``: each look's (text, fill, minimum) pairs, by ``DevicePalette`` field, for the
  tests that check every scheme.

Pure Python: ``core`` only.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from engine.core.kits import DEVICE_LOOKS
from engine.core.palette import contrast, luminance, mix

TEXT: Final = 4.5
GRAPHIC: Final = 3.0
PARCHMENT: Final = "#F4E8CC"          # a letter's paper, mixed into the panel's fill
KRAFT: Final = "#E6D2A8"              # a pigeon's note
PHOSPHOR: Final = "#3CFF7E"           # a terminal's green, mixed into the panel's light color
BLACK: Final = "#000000"
WHITE: Final = "#FFFFFF"
_STEPS: Final = (0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0)

Token = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class DevicePalette:
    """One look's colors, ``"#RRGGBB"``. ``page``: the panel the Inbox body sits on;
    ``card``: the fill behind a message (the paper, the screen, the sender's bubble; None:
    no frame, the message sits on ``page``); ``text``: the message's text on ``card`` (or
    ``page``); ``heading``: the line above each message; ``edge``: the card's outline;
    ``accent`` and ``mark``: the look's marks (wax seal and ribbon, cursor, static, glow);
    ``me_card``/``me_text``: the player's own bubble and its text (phone)."""

    look: str
    page: str
    card: str | None
    text: str
    heading: str
    edge: str
    accent: str
    mark: str
    me_card: str
    me_text: str


def readable(fg: str, bg: str, minimum: float = TEXT, *others: str) -> str:
    """``fg`` when it meets ``minimum`` on ``bg``; else the first of ``others`` that does;
    else whichever of ``others``, black and white reads best."""
    if contrast(fg, bg) >= minimum:
        return fg
    for other in others:
        if contrast(other, bg) >= minimum:
            return other
    return max((*others, BLACK, WHITE), key=lambda c: contrast(c, bg))


def _paper(page: str, tint: str, texts: tuple[str, ...]) -> str:
    """``page`` moved toward ``tint`` as far as every one of ``texts`` keeps 4.5:1."""
    for t in _STEPS:
        paper = mix(page, tint, t)
        if all(contrast(text, paper) >= TEXT for text in texts):
            return paper
    return page


def device_palette(look: str, token: Token) -> DevicePalette:
    """``look``'s colors from the theme ``token``s (module docstring). A look this engine
    doesn't know is drawn as a phone."""
    page = token("panel.fill_color")
    text = token("panel.text_color")
    border = token("panel.border_color")
    heading = readable(token("panel.heading.text_color"), page, TEXT, text)
    accent = token("button.marker.fill_color")
    accent2 = token("button.focused.border_color")
    muted = token("button.disabled.text_color")
    if look == "letters" or look == "pigeon":
        paper = _paper(page, PARCHMENT if look == "letters" else KRAFT, (text,))
        ink = readable(text, paper, TEXT, page)
        head = readable(heading, paper, TEXT, ink)
        seal = readable(accent, paper, GRAPHIC, ink)
        ribbon = readable(accent2, paper, GRAPHIC, seal)
        edge = readable(border, paper, 1.4, mix(paper, ink, 0.35))
        return DevicePalette(look, page, paper, ink, head, edge, seal, ribbon, paper, ink)
    if look == "terminal":
        dark, light = sorted((page, text), key=luminance)
        screen = dark if luminance(dark) < 0.05 else mix(dark, BLACK, 0.55)
        green = light
        for t in (0.85, 0.7, 0.55, 0.4, 0.25, 0.1, 0.0):
            green = mix(light, PHOSPHOR, t)
            if contrast(green, screen) >= TEXT:
                break
        green = readable(green, screen, TEXT, light)
        edge = mix(screen, green, 0.35)
        dim = readable(mix(screen, green, 0.7), screen, TEXT, green)
        return DevicePalette(look, page, screen, green, dim, edge, green, edge, screen, green)
    if look == "radio":
        static = readable(muted, page, GRAPHIC, text)
        tag = readable(muted, page, TEXT, text)
        return DevicePalette(look, page, None, text, heading, border,
                             readable(accent, page, GRAPHIC, text), static, page, tag)
    if look == "mind":
        glow = mix(page, accent, 0.45)
        return DevicePalette(look, page, None, readable(text, page, TEXT), heading, page,
                             glow, mix(page, accent, 0.25), page, text)
    bubble = token("button.focused.fill_color")
    if contrast(bubble, page) < 1.08:                       # a bubble that can't be seen
        bubble = mix(page, accent, 0.18)
    them = readable(token("button.text_color"), bubble, TEXT, text, page)
    mine = accent
    me_text = readable(page, mine, TEXT, WHITE, BLACK, text)
    return DevicePalette("phone", page, bubble, them, heading, border, accent,
                         muted, mine, me_text)


# Each look's text on its fill, by ``DevicePalette`` field: (text, fill, minimum).
PAIRS: Final[dict[str, tuple[tuple[str, str, float], ...]]] = {
    "phone": (("text", "card", TEXT), ("me_text", "me_card", TEXT), ("heading", "page", TEXT)),
    "letters": (("text", "card", TEXT), ("heading", "card", TEXT), ("accent", "card", GRAPHIC)),
    "pigeon": (("text", "card", TEXT), ("heading", "card", TEXT), ("accent", "card", GRAPHIC),
               ("mark", "card", GRAPHIC)),
    "radio": (("text", "page", TEXT), ("heading", "page", TEXT), ("me_text", "page", TEXT),
              ("mark", "page", GRAPHIC)),
    "terminal": (("text", "card", TEXT), ("heading", "card", TEXT)),
    "mind": (("text", "page", TEXT), ("heading", "page", TEXT)),
}
assert set(PAIRS) == set(DEVICE_LOOKS)


def pair_ratios(found: DevicePalette) -> tuple[tuple[str, float, float], ...]:
    """``found``'s pairs (``PAIRS``) as (name, ratio, minimum)."""
    out = []
    for fg, bg, minimum in PAIRS[found.look]:
        back = getattr(found, bg)
        assert back is not None
        out.append((f"{fg} on {bg}", contrast(getattr(found, fg), back), minimum))
    return tuple(out)


__all__ = ["DevicePalette", "GRAPHIC", "PAIRS", "TEXT", "Token", "device_palette",
           "pair_ratios", "readable"]
