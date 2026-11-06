"""The device looks in the game: their colors from the theme, the arrival notice's skins, and
the marks both the notice and the Inbox draw (F65 round 3, "Phone and letter skins" and
"Radio, terminal and mind skins").

Why this module exists: a message is drawn the way its device would show it (a phone's
bubble, a letter's paper, a pigeon's note with its wax seal, a radio transcript with static,
a terminal's green screen, a thought with no frame at all). The colors are
``core/devicelooks.device_palette`` over this game's resolved ``[theme]``, so every color
scheme dresses every look and its text stays readable; the shapes are drawn here.

- ``theme_token(cfg)`` / ``palette(cfg, look)``: the look's ``DevicePalette`` for a
  ``ThemeConfig`` (kept per config and look).
- ``notice_skin(cfg, look)``: the arrival notice's ``notice.NoticeSkin``: the same panel,
  layout and text as any notice, in the look's colors, with its marks: a phone's bubble and
  tail, a letter's stamp, a pigeon's ribbon and wax seal, a radio's static rule, a
  terminal's screen and cursor block, a thought's soft glow and no border (and its text in
  italics, ``italic``). Nothing in a notice moves.
- ``static_rule``, ``seal`` and ``cursor``: the marks, shared with the Inbox
  (``builtin/inbox_view``). ``static_rule``'s ``frame`` picks the noise; under reduced
  motion the callers pass 0, so it holds still.

Imports ``core``, ``render`` and ``ui`` only.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.devicelooks import DevicePalette, device_palette
from engine.core.palette import rgb_of
from engine.render.frames import FrameSpec
from engine.ui.focus import Box

if TYPE_CHECKING:
    from engine.core.config_schema import ThemeConfig
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter

RGB = tuple[int, int, int]
SEAL: Final = 26                       # the wax seal's size
TICK: Final = 4                        # the static rule's step
_cache: dict[tuple[int, str], tuple["ThemeConfig", DevicePalette]] = {}


def _hex(value: Sequence[int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*tuple(value)[:3])


def theme_token(cfg: "ThemeConfig"):
    """A ``core/devicelooks.Token`` over ``cfg``: a dotted color token as ``"#RRGGBB"``."""
    def token(path: str) -> str:
        node: object = cfg
        for part in path.split("."):
            node = getattr(node, part)
        assert isinstance(node, tuple), path
        return _hex(node)
    return token


def palette(cfg: "ThemeConfig", look: str) -> DevicePalette:
    """``look``'s colors in ``cfg`` (kept per config and look)."""
    key = (id(cfg), look)
    found = _cache.get(key)
    if found is None or found[0] is not cfg:
        if len(_cache) > 64:
            _cache.clear()
        found = _cache[key] = (cfg, device_palette(look, theme_token(cfg)))
    return found[1]


def rgb(color: str) -> RGB:
    return rgb_of(color)


# --- Marks ---------------------------------------------------------------------------------

def _noise(i: int, frame: int) -> int:
    """A deterministic height 1..7 for tick ``i`` of noise ``frame``."""
    n = (i * 374761393 + frame * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return 1 + (n >> 8) % 7


def static_rule(canvas: "Canvas", x: float, y: float, w: float, color: RGB, frame: int,
                alpha: float = 1.0) -> None:
    """A rule of radio static centred on ``y``: short ticks of noise heights every 4."""
    if alpha <= 0.0:
        return
    fill = color if alpha >= 1.0 else (*color, round(255 * alpha))
    for i in range(int(w // TICK)):
        h = _noise(i, frame)
        canvas.fill(fill, (x + i * TICK, y - h / 2, 2, h))


def seal(p: "Painter", cx: float, cy: float, wax: RGB, ribbon: RGB, *,
         size: float = SEAL, ring: RGB | None = None) -> None:
    """A wax seal centred at (``cx``, ``cy``) with two ribbon tails under it and a pressed
    ring (``ring``: its color, else the ribbon's)."""
    ring_color = ribbon if ring is None else ring
    tail = size * 0.42
    p.triangle(Box(cx - size * 0.45, cy + size * 0.18, tail, tail * 1.3), ribbon,
               direction="down")
    p.triangle(Box(cx + size * 0.45 - tail, cy + size * 0.18, tail, tail * 1.3), ribbon,
               direction="down")
    p.ellipse(Box(cx - size / 2, cy - size / 2, size, size), wax)
    inner = size * 0.56
    p.ellipse(Box(cx - inner / 2, cy - inner / 2, inner, inner), ring_color, ring=1.5)


def cursor(canvas: "Canvas", x: float, top: float, w: float, h: float, color: RGB) -> None:
    """A terminal's block cursor."""
    canvas.fill(color, (x, top, w, h))


# --- The arrival notice ----------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceNoticeSkin:
    """A ``notice.NoticeSkin`` for one look (module docstring)."""

    look: str
    colors: DevicePalette

    @property
    def text_color(self) -> RGB:
        return rgb(self.colors.text)

    @property
    def italic(self) -> bool:
        """A thought's notice reads in italics, as it does in the Inbox."""
        return self.look == "mind"

    def frame(self, base: FrameSpec) -> FrameSpec:
        c, look = self.colors, self.look
        if look == "phone":
            return FrameSpec(rgb(c.card or c.page), 1.0, rgb(c.card or c.page), 0, 20)
        if look in ("letter", "pigeon"):
            return FrameSpec(rgb(c.card or c.page), 1.0, rgb(c.edge), 1, 3)
        if look == "terminal":
            return FrameSpec(rgb(c.card or c.page), 1.0, rgb(c.edge), 2, 4)
        if look == "mind":
            return FrameSpec(rgb(c.page), 0.0, rgb(c.page), 0, 28)        # drawn by decorate
        return FrameSpec(rgb(c.page), base.fill_opacity, rgb(c.edge), 1, 6)       # radio

    def decorate(self, canvas: "Canvas", p: "Painter", box: Box, opacity: float) -> None:
        c, look = self.colors, self.look
        if look == "mind":
            for grow, alpha in ((14, 0.10), (8, 0.16), (3, 0.24)):
                p.shape(Box(box.x - grow, box.y - grow, box.w + 2 * grow, box.h + 2 * grow),
                        FrameSpec(rgb(c.accent), alpha, rgb(c.accent), 0, 28 + grow),
                        alpha=opacity)
            p.shape(box, FrameSpec(rgb(c.page), 0.92, rgb(c.page), 0, 28), alpha=opacity)
            return
        if opacity < 0.6:
            return                                  # marks join once the notice is in
        if look == "phone":
            p.triangle(Box(box.x + 22, box.bottom - 1, 14, 9), rgb(c.card or c.page),
                       direction="down")
        elif look == "letter":
            stamp = Box(box.right - 18, box.y - 8, 20, 24)
            canvas.fill(rgb(c.edge), (stamp.x - 1, stamp.y - 1, stamp.w + 2, stamp.h + 2))
            canvas.fill(rgb(c.card or c.page), (stamp.x, stamp.y, stamp.w, stamp.h))
            canvas.fill(rgb(c.accent), (stamp.x + 3, stamp.y + 3, stamp.w - 6, stamp.h - 6))
        elif look == "pigeon":
            canvas.fill(rgb(c.mark), (box.x + 6, box.y, 3, box.h))
            seal(p, box.x + 7.5, box.y + box.h / 2, rgb(c.accent), rgb(c.mark), size=14,
                 ring=rgb(c.card or c.page))
        elif look == "radio":
            static_rule(canvas, box.x + 12, box.bottom - 6, box.w - 24, rgb(c.mark), 0)
        elif look == "terminal":
            cursor(canvas, box.right - 20, box.bottom - 9, 10, 5, rgb(c.text))


def notice_skin(cfg: "ThemeConfig", look: str) -> DeviceNoticeSkin:
    """The arrival notice's skin for ``look`` in ``cfg`` (module docstring)."""
    return DeviceNoticeSkin(look, palette(cfg, look))


__all__ = ["DeviceNoticeSkin", "cursor", "notice_skin", "palette", "rgb", "seal",
           "static_rule", "theme_token"]
