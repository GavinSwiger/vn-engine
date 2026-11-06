"""``ClockItem``: the story clock in the status corner (F63 round 2, "Clock in the corner").

Why this module exists: ``show clock`` puts the day and the part of the day on screen so the
player always knows when it is. The item follows F61's ``CornerItem`` protocol
(``statuscorner``): it reads a ``ClockReading`` each frame, so it changes as soon as a
``clock`` line moves time, with no bookkeeping. ``app/clockcorner.py`` adds, places and
removes it; this module only draws.

**Layout** (canvas units, from the corner text size and its line pitch): two rows, the date
as the calendar words it ("Day 4", "Night 3", "Spring, day 4") over the part of the day
("Evening"). A right corner right-aligns both rows. A row wider than the room (the corner's
``max_width``, or the NVL column's ``narrow`` width) is cut with "…".

**Colors**: both rows in ``[theme.corner] text_color``, the pair W67 already checks at 4.5:1
on the corner's fill, so every scheme reads.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.ui.focus import Box
    from engine.ui.statuscorner import CornerContext

ELLIPSIS: Final = "…"


@dataclass(frozen=True)
class ClockReading:
    """What the clock shows now: the ``date`` in words and the ``part`` of the day."""

    date: str
    part: str


def fit(text: str, width: float, measure: Callable[[str], float]) -> str:
    """``text``, or as much of it as fits ``width`` with "…" after it."""
    if measure(text) <= width:
        return text
    low, high = 0, len(text)
    while low < high:                                   # the longest cut that fits
        mid = (low + high + 1) // 2
        if measure(text[:mid].rstrip() + ELLIPSIS) <= width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + ELLIPSIS if low else ELLIPSIS


class ClockItem:
    """A ``CornerItem`` for the story clock (module docstring). ``read`` gives the current
    ``ClockReading`` (None: nothing to show); ``narrow`` the column width in NVL, or None."""

    def __init__(self, read: Callable[[], ClockReading | None], *,
                 narrow: Callable[[], float | None] | None = None) -> None:
        self._read = read
        self._narrow = narrow

    def reading(self) -> ClockReading | None:
        return self._read()

    def narrow(self) -> float | None:
        return self._narrow() if self._narrow is not None else None

    @property
    def revision(self) -> int:
        """Changes whenever the size might: the words, the column width."""
        return hash((self._read(), self.narrow()))

    def rows(self, ctx: "CornerContext") -> tuple[tuple[str, float], ...]:
        """The rows to draw, each ``(text, width)``, cut to fit."""
        reading = self._read()
        if reading is None:
            return ()
        room = ctx.max_width
        narrow = self.narrow()
        if narrow is not None:
            room = min(room, max(float(ctx.size), narrow))

        def measure(text: str) -> float:
            return ctx.measure(text, ctx.size)

        out = []
        for text in (reading.date, reading.part):
            shown = fit(text, room, measure) if text else ""
            out.append((shown, measure(shown) if shown else 0.0))
        return tuple(out)

    def measure(self, ctx: "CornerContext") -> tuple[float, float]:
        rows = self.rows(ctx)
        if not rows:
            return 0.0, 0.0
        return max(w for _, w in rows), float(ctx.pitch * len(rows))

    def draw(self, canvas: "Canvas", box: "Box", ctx: "CornerContext") -> None:
        right = ctx.place.endswith("right")
        for n, (text, width) in enumerate(self.rows(ctx)):
            if text:
                x = box.x + box.w - width if right else box.x
                ctx.text(canvas, text, (x, box.y + n * ctx.pitch))


__all__ = ["ClockItem", "ClockReading", "ELLIPSIS", "fit"]
