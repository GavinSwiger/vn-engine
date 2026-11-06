"""``HotbarItem``: the hotbar's quick slots in the status corner (F64 round 2).

Why this module exists: ``show hotbar`` puts a row of 4 to 8 slots in a corner; each holds a
usable item the player presses its number key (or clicks, or picks with a gamepad) to use.
The item follows F61's ``CornerItem`` protocol (``statuscorner``): it measures and draws
itself from the ``HotbarSlot`` tuple it reads each frame, so counts update live as ``lock
item`` / ``unlock item`` lines run. ``app/hotbar.py`` decides what the slots hold, places
the item and takes the input; this module only draws.

**Layout** (canvas units, from the corner text size ``s``). Slots sit in one row, ``gap``
(0.75 s) apart. Each slot is a square picture well (2.2 s) with a strip under it (one line at
the small size, 0.65 s, at least ``SMALL_MIN``): the number key at its left, the count
("×3") at its right for a counted item. Text is never drawn over a picture, so it is always
on the corner's own fill.

- A held item shows its picture (``picture(name)``: a file ref, an RGB box, or None) fitted
  into the well, else its first letters (``initials``) in the corner text color.
- An empty slot (no item, or one the player doesn't hold) is an outline with its key only.
- The gamepad's chosen slot (``focus()``) gets a ring twice as thick and an inner ring.

**Colors** come from ``[theme.corner]`` only: text in ``text_color``, outlines and rings in
``accent_color``. So the two W67 pairs the corner already checks (text 4.5:1, accent 3:1 on
the fill) cover everything the hotbar draws, in every scheme, as for meters.

``boxes`` holds each slot's box (canvas units) as last drawn, for the app's mouse hits.
"""

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.ui.focus import Box
from engine.ui.layouts import pitch
from engine.ui.statuscorner import draw_line

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.statuscorner import CornerContext

WELL: Final = 2.2               # a slot's picture well, in corner text sizes
GAP: Final = 0.75               # between slots (keeps "×3" and the next key apart)
SMALL: Final = 0.65             # the key and count text
SMALL_MIN: Final = 14           # canvas units: the smallest key and count text


@dataclass(frozen=True)
class HotbarSlot:
    """One slot as shown: its ``key`` ("1"…"8"); the item ``name`` (None: empty), ``title``,
    ``count`` (None: not counted), ``picture`` (a file ref, an RGB, or None)."""

    key: str
    name: str | None = None
    title: str = ""
    count: int | None = None
    picture: "str | tuple[int, int, int] | None" = None


def initials(title: str) -> str:
    """Up to two letters standing in for a picture: the first letters of the first two
    words ("Jasmine Tea" → "JT"), or the first two of one word ("Matches" → "Ma")."""
    words = [w for w in title.split() if w[:1].isalnum()]
    if not words:
        return title[:2]
    if len(words) == 1:
        return words[0][:2]
    return (words[0][0] + words[1][0]).upper()


class HotbarItem:
    """A ``CornerItem`` for the hotbar (module docstring). ``read`` gives the slots now;
    ``focus`` the gamepad's chosen slot index (None: none)."""

    def __init__(self, read: Callable[[], tuple[HotbarSlot, ...]], *,
                 focus: Callable[[], int | None] | None = None) -> None:
        self._read = read
        self._focus = focus
        self.boxes: tuple[Box, ...] = ()

    def slots(self) -> tuple[HotbarSlot, ...]:
        return self._read()

    def focus(self) -> int | None:
        return self._focus() if self._focus is not None else None

    @property
    def revision(self) -> int:
        """Changes when the size might: the number of slots (counts never change it)."""
        return len(self._read())

    # -- layout --

    @staticmethod
    def metrics(size: int) -> tuple[float, float, int, float]:
        """(well, gap, small text size, strip height) at corner text size ``size``."""
        small = max(SMALL_MIN, round(size * SMALL))
        return float(round(size * WELL)), float(round(size * GAP)), small, float(pitch(small))

    def slot_boxes(self, box: Box, size: int) -> tuple[Box, ...]:
        """Each slot's box (well and strip) inside the content ``box``."""
        well, gap, _, strip = self.metrics(size)
        return tuple(Box(box.x + i * (well + gap), box.y, well, well + strip)
                     for i in range(len(self._read())))

    def measure(self, ctx: "CornerContext") -> tuple[float, float]:
        n = len(self._read())
        if n == 0:
            return 0.0, 0.0
        well, gap, _, strip = self.metrics(ctx.size)
        return n * well + (n - 1) * gap, well + strip

    # -- drawing --

    def draw(self, canvas: "Canvas", box: Box, ctx: "CornerContext") -> None:
        slots = self._read()
        boxes = self.slot_boxes(box, ctx.size)
        self.boxes = boxes
        well, _, small, _ = self.metrics(ctx.size)
        line = max(1.0, round(ctx.size / 12))
        font = dataclasses.replace(ctx.style.font, size=small)
        focused = self.focus()
        for i, (slot, sbox) in enumerate(zip(slots, boxes)):
            well_box = Box(sbox.x, sbox.y, well, well)
            _outline(ctx, canvas, well_box, line * (2 if i == focused else 1))
            if i == focused:
                _outline(ctx, canvas, Box(well_box.x + 3 * line, well_box.y + 3 * line,
                                          well - 6 * line, well - 6 * line), line)
            inner = Box(well_box.x + 4 * line, well_box.y + 4 * line, well - 8 * line,
                        well - 8 * line)
            if slot.name is not None:
                if not _picture(canvas, ctx, slot.picture, inner):
                    mark = initials(slot.title)
                    w = ctx.measure(mark, ctx.size)
                    ctx.text(canvas, mark, (inner.x + (inner.w - w) / 2,
                                            inner.y + (inner.h - ctx.pitch) / 2))
            y = sbox.y + well
            draw_line(canvas, slot.key, font, ctx.style.text_color, (sbox.x, y), ctx.opacity)
            if slot.name is not None and slot.count is not None:
                text = f"×{slot.count:,}"
                w = ctx.measure(text, small)
                draw_line(canvas, text, font, ctx.style.text_color, (sbox.right - w, y),
                          ctx.opacity)


def _outline(ctx: "CornerContext", canvas: "Canvas", box: Box, line: float) -> None:
    ctx.fill(canvas, Box(box.x, box.y, box.w, line))
    ctx.fill(canvas, Box(box.x, box.bottom - line, box.w, line))
    ctx.fill(canvas, Box(box.x, box.y + line, line, box.h - 2 * line))
    ctx.fill(canvas, Box(box.right - line, box.y + line, line, box.h - 2 * line))


def _picture(canvas: "Canvas", ctx: "CornerContext",
             found: "str | tuple[int, int, int] | None", box: Box) -> bool:
    """Draw the slot's picture fitted into ``box``; False when there is none to draw."""
    if found is None or box.w <= 0 or box.h <= 0:
        return False
    if not isinstance(found, str):
        ctx.fill(canvas, box, tuple(found)[:3])           # type: ignore[arg-type]
        return True
    assets = canvas.assets
    ref = assets.image(found)
    if ref.is_placeholder:
        return False
    w, h = ref.size
    if w <= 0 or h <= 0:
        return False
    s = min(box.w / w, box.h / h)
    tw, th = w * s, h * s
    rect = canvas.rect_to_px((box.x + (box.w - tw) / 2, box.y + (box.h - th) / 2, tw, th))
    if rect.width <= 0 or rect.height <= 0 or canvas.surface is None:
        return False
    surface, _offset = assets.variant(ref, rect.size, canvas.quality)
    if ctx.opacity < 1.0:
        surface = surface.copy()
        surface.set_alpha(round(255 * max(0.0, ctx.opacity)))
    canvas.surface.blit(surface, rect.topleft)
    return True


__all__ = ["GAP", "HotbarItem", "HotbarSlot", "SMALL", "WELL", "initials"]
