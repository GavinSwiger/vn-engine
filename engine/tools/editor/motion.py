"""Studio's motion budget: every short motion on one clock (Studio UX idea 4.1).

Why this module exists: Studio's rule was "nothing animates" (F45 ``08`` §2), with F58's
glow as the one exception. Motion now may answer an action and show what changed, if it
is short, never loops, never blocks input, and stops under Reduce motion. The motions live
here so they share one timer, one easing and one off switch, and so they can be counted:

- ``Motion.tween(key, ms, step)`` calls ``step(p)`` with ``p`` eased from 0 to 1 over
  ``ms`` (at most ``MAX_MS``), one ``after`` timer for every tween of the window. A new
  tween with the same key finishes the old one first. ``step(1.0)`` always ends a tween:
  on time, on ``finish``/``stop``, when ``visible()`` says the widget is hidden (no work
  for what can't be seen), and at once under Reduce motion (``reduce()``).
- ``Motion.hold(key, ms, on, off)``: a state cue (a colour that says "this changed")
  shown for ``ms`` then taken away by ``off(p)``, a short fade under motion and a cut under
  Reduce motion.
- ``ease_out`` and ``fade``: the curve and a colour blend on it (``theme.blend``).

The budget itself (which motions exist) is written in F45 ``08-visual-refresh.md`` §10.
Tk only through ``after``/``after_cancel`` on the widget given; tests pass a fake.
"""

from __future__ import annotations

import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from engine.tools.editor.theme import blend

FRAME_MS: Final = 16                    # about 60 steps a second
MAX_MS: Final = 250                     # the budget: no motion is longer than this
FADE_MS: Final = 200                    # a fade in or out
HOLD_MS: Final = 700                    # how long a "this changed" colour stays


def ease_out(p: float) -> float:
    """Cubic ease-out: fast start, gentle stop (0 → 0, 1 → 1)."""
    p = min(1.0, max(0.0, p))
    return 1.0 - (1.0 - p) ** 3


def fade(start: str, end: str, p: float) -> str:
    """``#RRGGBB`` ``p`` of the way from ``start`` to ``end``."""
    return blend(end, start, min(1.0, max(0.0, p)))


@dataclass
class _Tween:
    start: float
    ms: float
    step: Callable[[float], None]
    visible: Callable[[], bool] | None
    done: Callable[[], None] | None


class Motion:
    """One window's motions on one ``after`` clock. ``widget`` owns the timer; ``reduce``
    answers Reduce motion (read when a motion starts and on every step); ``now`` is in ms."""

    def __init__(self, widget: tk.Misc, *, reduce: Callable[[], bool] = lambda: False,
                 now: Callable[[], float] | None = None) -> None:
        self.widget = widget
        self.reduce = reduce
        self.now = now or (lambda: time.perf_counter() * 1000)
        self._tweens: dict[object, _Tween] = {}
        self._holds: dict[object, tuple[object, Callable[[float], None]]] = {}  # → (id, off)
        self._timer: object | None = None
        self.stopped = False

    # -- Tweens -------------------------------------------------------------------------------

    def tween(self, key: object, ms: float, step: Callable[[float], None], *,
              visible: Callable[[], bool] | None = None,
              done: Callable[[], None] | None = None, cap: float = MAX_MS) -> None:
        """Run ``step`` from 0 to 1 over ``ms`` (capped at ``cap``, ``MAX_MS`` unless a
        celebration says otherwise); see the module doc."""
        self.finish(key)
        if self.stopped or self._reduced() or (visible is not None and not _ask(visible)):
            _end(step, done)
            return
        self._tweens[key] = _Tween(self.now(), max(1.0, min(float(ms), cap)), step,
                                   visible, done)
        _call(step, 0.0)
        self._arm()

    def running(self, key: object | None = None) -> bool:
        return bool(self._tweens) if key is None else key in self._tweens

    def finish(self, key: object) -> None:
        """End ``key``'s tween now, at its last step."""
        found = self._tweens.pop(key, None)
        if found is not None:
            _end(found.step, found.done)
        hold = self._holds.pop(key, None)
        if hold is not None:
            self._cancel(hold[0])
            _call(hold[1], 1.0)

    def stop(self) -> None:
        """The window closes: every motion ends at its last step and the timer stops."""
        self.stopped = True
        for key in list(self._tweens) + list(self._holds):
            self.finish(key)
        if self._timer is not None:
            self._cancel(self._timer)
            self._timer = None

    def _reduced(self) -> bool:
        return _ask(self.reduce)

    def _arm(self) -> None:
        if self._timer is None and self._tweens and not self.stopped:
            try:
                self._timer = self.widget.after(FRAME_MS, self._tick)
            except (tk.TclError, RuntimeError):
                self._timer = None
                self.stop()

    def _tick(self) -> None:
        self._timer = None
        now, reduced = self.now(), self._reduced()
        for key, found in list(self._tweens.items()):
            if self._tweens.get(key) is not found:
                continue                        # a step finished or replaced it
            p = (now - found.start) / found.ms
            if p >= 1.0 or reduced or (found.visible is not None and not _ask(found.visible)):
                del self._tweens[key]
                _end(found.step, found.done)
            else:
                _call(found.step, ease_out(p))
        self._arm()

    # -- State cues ---------------------------------------------------------------------------

    def hold(self, key: object, ms: float, on: Callable[[], None],
             off: Callable[[float], None]) -> None:
        """``on()`` now; after ``ms``, ``off(p)`` from 0 to 1 (a fade, or ``off(1.0)``
        alone under Reduce motion). Another hold with the same key restarts it; ``finish``
        and ``stop`` call ``off(1.0)`` at once."""
        self.finish(key)
        _call0(on)
        if self.stopped:
            _call(off, 1.0)
            return

        def release() -> None:
            self._holds.pop(key, None)
            self.tween(key, FADE_MS, off)

        try:
            self._holds[key] = (self.widget.after(max(1, round(ms)), release), off)
        except (tk.TclError, RuntimeError):
            _call(off, 1.0)

    def _cancel(self, after_id: object) -> None:
        try:
            self.widget.after_cancel(after_id)          # type: ignore[arg-type]
        except (tk.TclError, RuntimeError, ValueError):
            pass


def _ask(question: Callable[[], bool]) -> bool:
    try:
        return bool(question())
    except (tk.TclError, RuntimeError):
        return False


def _call(step: Callable[[float], None], p: float) -> None:
    try:
        step(p)
    except tk.TclError:                         # the widget went away mid-motion
        pass


def _call0(fn: Callable[[], None]) -> None:
    try:
        fn()
    except tk.TclError:
        pass


def _end(step: Callable[[float], None], done: Callable[[], None] | None) -> None:
    _call(step, 1.0)
    if done is not None:
        _call0(done)


__all__ = ["FADE_MS", "FRAME_MS", "HOLD_MS", "MAX_MS", "Motion", "ease_out", "fade"]
