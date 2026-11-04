"""``ChoiceClock``: a timed menu's countdown (F51 ``04-technical.md`` §7.3; 07 I-2, C5).

Why this module exists: the runtime never reads a clock (invariant 7), so a timed menu's
time is counted on the presentation side, by the choice screen, and only while the player
can use the menu. This is the pure counter the screen ticks each frame: no pygame, no
screens, so the rules are unit-tested alone.

- **Limit**: F50's ``timing_limit(seconds, level)``, with the Timing assist level read every
  frame by the caller: Normal N s, Slower 2N s, No time limits ``None`` (no panel, no
  timeout).
- **Fraction kept** (C5, 07 I-2): the clock holds ``used`` in [0, 1] and adds
  ``dt / limit`` while counting, so a level change keeps the fraction of time left (Normal →
  Slower at 4 of 5 s leaves 2 s of 10) and never expires the menu on the first frame back.
  Under No time limits ``used`` is frozen.
- **Expiry**: ``tick`` returns True exactly once, the frame the time left reaches 0 (within
  ``CLOCK_EPS``, so float drift can't skip or delay it); after that the clock stays fired
  (07 I-6: no retry each frame).
- **Shown**: the whole seconds left, rounded up (``ceil(left − 1e-9)``: 5 at 5.0 and at
  4.01, 4 at 4.0, 1 at 0.2). The bar is ``1 − used``; under reduce motion it moves only
  with the number, ``min(limit, shown) / limit``.

Imports only ``core.settings_schema.timing_limit`` (07 §2).
"""

import math
from typing import Final

from engine.core.settings_schema import timing_limit

CLOCK_EPS: Final = 1e-9                  # 04 §17: float drift never skips or delays expiry


class ChoiceClock:
    """One open menu's countdown. ``seconds`` is ``ShowMenu.seconds`` (None: untimed, and
    then every query is None and ``tick`` never fires)."""

    __slots__ = ("seconds", "used", "fired")

    def __init__(self, seconds: float | None) -> None:
        self.seconds = seconds
        self.used = 0.0
        self.fired = False

    def limit(self, level: int | str) -> float | None:
        """The time limit at Timing assist ``level`` (None: untimed or No time limits)."""
        if self.seconds is None:
            return None
        return timing_limit(self.seconds, level)

    def tick(self, dt: float, level: int | str, *, counting: bool) -> bool:
        """Count ``dt`` seconds when ``counting`` (the menu is usable and the window has
        focus) under ``level``'s limit. True only on the frame the time runs out."""
        limit = self.limit(level)
        if limit is None or self.fired:
            return False
        if counting and dt > 0:
            self.used = min(1.0, self.used + dt / limit)
        if (1.0 - self.used) * limit <= CLOCK_EPS:
            self.fired = True
            return True
        return False

    def left(self, level: int | str) -> float | None:
        """Seconds left at ``level`` (None: no limit)."""
        limit = self.limit(level)
        if limit is None:
            return None
        return max(0.0, (1.0 - self.used) * limit)

    def shown(self, level: int | str) -> int | None:
        """The number on the panel: whole seconds left, rounded up."""
        left = self.left(level)
        if left is None:
            return None
        return max(0, math.ceil(left - CLOCK_EPS))

    def fraction(self, level: int | str, *, reduce_motion: bool = False) -> float | None:
        """The bar's filled part, 0–1. Under reduce motion it changes only at whole
        seconds, with the number."""
        limit = self.limit(level)
        if limit is None:
            return None
        if reduce_motion:
            shown = self.shown(level) or 0
            return min(limit, shown) / limit
        return max(0.0, 1.0 - self.used)


__all__ = ["CLOCK_EPS", "ChoiceClock"]
