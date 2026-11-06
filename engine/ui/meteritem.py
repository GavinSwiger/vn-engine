"""``MeterItem``: one shown meter in the status corner (F62 round 2).

Why this module exists: ``show meter hana`` puts a meter on screen in one of five looks
(``skins.METER_LOOKS``). The item follows F61's ``CornerItem`` protocol (``statuscorner``):
it measures and draws itself from a ``MeterReading`` it reads each frame, so values update
live as ``points`` lines run, with no bookkeeping. ``app/meters.py`` creates, places and
removes items; this module only draws.

**Layout** (canvas units, from the corner text size ``s`` and its line pitch ``p``). The
first row is the label, then the gauge; a meter with ranks adds a second row with its rank
(empty below the first rank, so the panel never jumps). In the column form (``narrow``:
NVL, whose side margins are about 130 units wide) the label, the gauge and the rank each
take a row, and a bar or a row of marks shrinks to the column.

- ``bar``: an outlined bar, filled by the meter's share of its range.
- ``number``: the value as text.
- ``hearts`` / ``pips``: one mark per point when the range spans 10 or fewer (``marks``),
  else 5 to 10 marks each worth an equal part (the one in progress is partly filled).
  Empty marks are outlines.
- ``dial``: a 270° arc filled by the share, the value beside it.

A meter whose ``points`` line has no range has no share to draw, so any look but ``number``
falls back to ``number`` (W292 tells the author at load).

**Colors** come from ``[theme.corner]`` (``CornerStyle``): text in ``text_color``, every
mark, outline and fill in ``accent_color``. Empty parts are outlines in the accent, not a
separate track color, so the two W67 pairs the corner already checks (text 4.5:1, accent
3:1 on the fill) cover everything a meter draws, in every scheme.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.skins import METER_LOOKS
from engine.render.meter_marks import mark
from engine.ui.focus import Box

if TYPE_CHECKING:
    import pygame

    from engine.render.canvas import Canvas
    from engine.ui.statuscorner import CornerContext

RANGED_LOOKS: Final = frozenset(("bar", "hearts", "pips", "dial"))
MARKS_MIN: Final = 5
MARKS_MAX: Final = 10
DIAL_START: Final = 225.0                   # degrees, counter-clockwise from 3 o'clock
DIAL_SWEEP: Final = 270.0                   # clockwise, ending at -45° (bottom right)


@dataclass(frozen=True)
class MeterReading:
    """What a meter shows now: ``value``; ``low``/``high`` (None: no range); ``rank`` (None:
    the meter has no ranks; "" below the first)."""

    value: int
    low: int | None = None
    high: int | None = None
    rank: str | None = None

    @property
    def ranged(self) -> bool:
        return self.low is not None and self.high is not None and self.high > self.low

    @property
    def share(self) -> float:
        """The value's place in the range, 0.0 to 1.0 (0.0 with no range)."""
        if not self.ranged:
            return 0.0
        span = self.high - self.low                     # type: ignore[operator]
        return min(1.0, max(0.0, (self.value - self.low) / span))  # type: ignore[operator]


def marks(low: int, high: int) -> int:
    """How many hearts or pips a range gets: one per point up to 10, else the count from
    10 down to 5 that divides the range evenly, else 10."""
    span = high - low
    if span <= MARKS_MAX:
        return max(1, span)
    return next((n for n in range(MARKS_MAX, MARKS_MIN - 1, -1) if span % n == 0), MARKS_MAX)


def shown_look(look: str, reading: MeterReading) -> str:
    """The look actually drawn: ``number`` for a meter with no range (module docstring)."""
    if look not in METER_LOOKS:
        look = "bar"
    return "number" if look in RANGED_LOOKS and not reading.ranged else look


@dataclass(frozen=True)
class _Part:
    kind: str                       # "text", "bar", "marks", "dial"
    x: float
    y: float
    w: float
    h: float
    text: str = ""
    count: int = 0                  # marks
    filled: float = 0.0             # marks: how many are full (fractional); bar/dial: share
    shape: str = ""                 # marks: "heart" or "pip"; dial: diameter in w


class MeterItem:
    """A ``CornerItem`` for one meter (module docstring). ``read`` gives the current
    ``MeterReading`` (None: nothing to show); ``narrow`` the content width of the column
    form (NVL), or None for the normal rows."""

    def __init__(self, look: str, label: str, read: Callable[[], MeterReading | None], *,
                 narrow: Callable[[], float | None] | None = None) -> None:
        self.look = look
        self.label = label
        self._read = read
        self._narrow = narrow

    def reading(self) -> MeterReading | None:
        return self._read()

    def narrow(self) -> float | None:
        return self._narrow() if self._narrow is not None else None

    @property
    def revision(self) -> int:
        """Changes whenever the size might: the value, the rank, the column width."""
        return hash((self._read(), self.narrow()))

    # -- layout --

    def parts(self, ctx: "CornerContext") -> tuple[tuple[_Part, ...], float, float]:
        """What to draw and where, relative to the content's top left, and the size."""
        reading = self._read()
        if reading is None:
            return (), 0.0, 0.0
        s, p = ctx.size, ctx.pitch
        narrow = self.narrow()
        look = shown_look(self.look, reading)
        gap = round(s * 0.4)
        out: list[_Part] = []
        if narrow is None:                                  # label and gauge on one row
            x = ctx.measure(self.label, s) + gap if self.label else 0.0
            texts, gauge = _gauge(look, reading, ctx, x, None)
            if self.label:
                texts.insert(0, (0.0, self.label))
            y = 0.0
        else:                                               # NVL: label, gauge, rank
            y = 0.0
            if self.label:
                out.append(_Part("text", 0, 0, ctx.measure(self.label, s), p, self.label))
                y = float(p)
            texts, gauge = _gauge(look, reading, ctx, 0.0, max(float(s), narrow))
        row = max(float(p) if texts else 0.0, gauge.h if gauge is not None else 0.0)
        out += [_Part("text", tx, y + (row - p) / 2, ctx.measure(text, s), p, text)
                for tx, text in texts]
        if gauge is not None:
            out.append(_Part(gauge.kind, gauge.x, y + (row - gauge.h) / 2, gauge.w, gauge.h,
                             count=gauge.count, filled=gauge.filled, shape=gauge.shape))
        y += row
        if reading.rank is not None:                        # its row stays when empty
            if reading.rank:
                out.append(_Part("text", 0, y, ctx.measure(reading.rank, s), p, reading.rank))
            y += p
        right = max((part.x + part.w for part in out), default=0.0)
        return tuple(out), right, y

    def measure(self, ctx: "CornerContext") -> tuple[float, float]:
        _, w, h = self.parts(ctx)
        return w, h

    # -- drawing --

    def draw(self, canvas: "Canvas", box: Box, ctx: "CornerContext") -> None:
        parts, _, _ = self.parts(ctx)
        style = ctx.style
        for part in parts:
            x, y = box.x + part.x, box.y + part.y
            if part.kind == "text":
                ctx.text(canvas, part.text, (x, y))
            elif part.kind == "bar":
                _bar(canvas, ctx, Box(x, y, part.w, part.h), part.filled)
            elif part.kind == "marks":
                _marks(canvas, ctx, part, x, y, style.accent_color)
            elif part.kind == "dial":
                _dial(canvas, ctx, part, x, y, style.accent_color)


def _gauge(look: str, reading: MeterReading, ctx: "CornerContext", x: float,
           width: float | None) -> tuple[list[tuple[float, str]], _Part | None]:
    """The gauge of ``look`` starting at ``x`` (y 0), and the texts on its row; ``width``
    (the column form) fits a bar or a row of marks into that width."""
    s, p = ctx.size, ctx.pitch
    if look == "number":
        return [(x, f"{reading.value:,}")], None
    if look == "bar":
        w = round(s * 6) if width is None else width
        return [], _Part("bar", x, 0, w, max(8, round(s * 0.7)), filled=reading.share)
    if look in ("hearts", "pips"):
        count = marks(reading.low, reading.high)                # type: ignore[arg-type]
        if look == "hearts":
            m, step = s * 0.9, s * 1.05
        else:
            m, step = s * 0.6, s * 0.85
        natural = step * (count - 1) + m
        if width is not None and natural > width:               # shrink to the column
            m, step = m * width / natural, step * width / natural
            m, step = max(6, math.floor(m)), max(7, math.floor(step))
        else:
            m, step = round(m), round(step)
        h = round(m * 0.9) if look == "hearts" else m
        return [], _Part("marks", x, 0, step * (count - 1) + m, h, count=count,
                         filled=reading.share * count,
                         shape="heart" if look == "hearts" else "pip")
    d = round(s * 2.0) if width is None else p - round(s * 0.2)
    return ([(x + d + round(s * 0.25), f"{reading.value:,}")],
            _Part("dial", x, 0, d, d, filled=reading.share))


def _bar(canvas: "Canvas", ctx: "CornerContext", box: Box, share: float) -> None:
    line = max(1.0, round(ctx.size / 12))
    ctx.fill(canvas, Box(box.x, box.y, box.w, line))
    ctx.fill(canvas, Box(box.x, box.bottom - line, box.w, line))
    ctx.fill(canvas, Box(box.x, box.y + line, line, box.h - 2 * line))
    ctx.fill(canvas, Box(box.right - line, box.y + line, line, box.h - 2 * line))
    inner_w = box.w - 4 * line
    if share > 0 and inner_w > 0:
        ctx.fill(canvas, Box(box.x + 2 * line, box.y + 2 * line, inner_w * share,
                             max(1.0, box.h - 4 * line)))


def _blit(canvas: "Canvas", surf: "pygame.Surface", pos: tuple[float, float], opacity: float,
          width_px: int | None = None) -> None:
    surface = canvas.surface
    if surface is None or opacity <= 0.0:
        return
    previous = surf.get_alpha()
    if opacity < 1.0:
        surf.set_alpha(round(255 * opacity))
    try:
        area = None if width_px is None else (0, 0, width_px, surf.get_height())
        surface.blit(surf, canvas.px(*pos), area)
    finally:
        surf.set_alpha(previous)


def _marks(canvas: "Canvas", ctx: "CornerContext", part: _Part, x: float, y: float,
           color: tuple[int, int, int]) -> None:
    scale = canvas.scale
    w_px = max(1, round(part.h * (1 / 0.9 if part.shape == "heart" else 1.0) * scale))
    h_px = max(1, round(part.h * scale))
    size = (w_px, h_px)
    m = w_px / scale
    step = (part.w - m) / (part.count - 1) if part.count > 1 else 0.0
    ring = max(1.0, round(ctx.size / 12) * scale)
    full = mark(part.shape, size, tuple(color))
    empty = mark(part.shape, size, tuple(color), ring)
    for i in range(part.count):
        pos = (x + i * step, y)
        fill = min(1.0, max(0.0, part.filled - i))
        if fill < 1.0:
            _blit(canvas, empty, pos, ctx.opacity)
        if fill > 0.0:
            _blit(canvas, full, pos, ctx.opacity,
                  None if fill >= 1.0 else max(1, round(w_px * fill)))


def _dial(canvas: "Canvas", ctx: "CornerContext", part: _Part, x: float, y: float,
          color: tuple[int, int, int]) -> None:
    scale = canvas.scale
    d_px = max(4, round(part.w * scale))
    thin = max(1.0, round(ctx.size / 12) * scale)
    thick = max(2.0, round(part.w * 0.18 * scale))
    # the thin track runs along the middle of the thick fill
    inset_px = max(0, round((thick - thin) / 2))
    track_d = max(1, d_px - 2 * inset_px)
    _blit(canvas, mark("arc", (track_d, track_d), tuple(color), thin, DIAL_START, DIAL_SWEEP),
          (x + inset_px / scale, y + inset_px / scale), ctx.opacity)
    sweep = round(DIAL_SWEEP * part.filled)                 # whole degrees: a small cache
    if sweep > 0:
        _blit(canvas, mark("arc", (d_px, d_px), tuple(color), thick, DIAL_START, sweep),
              (x, y), ctx.opacity)


__all__ = ["MARKS_MAX", "MARKS_MIN", "MeterItem", "MeterReading", "RANGED_LOOKS", "marks",
           "shown_look"]
