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

The budget's five motions (Studio UX 4.1) are the functions below, so every one is here:

- ``pop_in``: a new story-map box grows from 90 % to full size and fades in (``POP_MS``).
- ``draw_on``: a new arrow draws itself from its tail to its head (``DRAW_MS``).
- ``fade_rows``: rows removed from a list (the Events list) fade where they were, then the
  rows below close the gap (``ROW_FADE_MS``).
- ``count_to``: the problem count ticks through the numbers to its new value (``COUNT_MS``).
- ``clean_chip``: a clean check turns the status chip green with a tick for one second
  (``CLEAN_MS``), then it fades back (``FADE_MS``).

Each answers an action, never loops, takes no focus or input, does no work while hidden,
and is the final state at once under Reduce motion. The budget itself is written in F45
``08-visual-refresh.md`` §10. Tk only through the widgets given; tests pass a fake clock.
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from engine.tools.editor.theme import blend

FRAME_MS: Final = 16                    # about 60 steps a second
MAX_MS: Final = 250                     # the budget: no motion is longer than this
FADE_MS: Final = 200                    # a fade in or out
HOLD_MS: Final = 700                    # how long a "this changed" colour stays
POP_MS: Final = 200                     # a new map box
POP_FROM: Final = 0.9                   # ... grows from this share of its size
DRAW_MS: Final = 220                    # a new arrow, tail to head
ROW_FADE_MS: Final = 220                # a removed row: fade, then the gap closes
COUNT_MS: Final = 240                   # the problem count ticking to its new value
CLEAN_MS: Final = 1000                  # a clean check's green chip stays this long
SPLINE_STEPS: Final = 12                # samples per curve segment of a drawn arrow


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


# --- The budget's five motions ----------------------------------------------------------------

def pop_in(motion: Motion, canvas: tk.Canvas, key: object, items: Sequence[int], *,
           alive: Callable[[], bool], surface: str) -> None:
    """A new box (``items``, its rectangle first) grows from ``POP_FROM`` of its size about
    its centre while its fills fade in from ``surface``. An item someone else moves or
    recolours meanwhile (selection, names stuck to the edge) is left to them; ``alive()``
    false (the box was redrawn or removed) stops touching it."""
    if not items or len(box := canvas.coords(items[0])) < 4:
        return
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    shapes: list[list] = []
    for item in items:
        fill = str(canvas.itemcget(item, "fill")) if canvas.type(item) in (
            "rectangle", "text", "polygon", "oval") else ""
        at = canvas.coords(item)
        shapes.append([item, at, at, fill if _is_hex(fill) else "", fill])

    def step(p: float) -> None:
        if not alive():
            return
        s = POP_FROM + (1.0 - POP_FROM) * p
        for shape in shapes:
            item, at, last, fill, shown = shape
            if _near(canvas.coords(item), last):
                new = [c + (v - c) * s for v, c in zip(at, _centres(cx, cy, len(at)))]
                canvas.coords(item, *new)
                shape[2] = canvas.coords(item)
            if fill and str(canvas.itemcget(item, "fill")).lower() == shown.lower():
                shape[4] = fade(surface, fill, p)
                canvas.itemconfigure(item, fill=shape[4])

    motion.tween(key, POP_MS, step, visible=canvas.winfo_viewable)


def draw_on(motion: Motion, canvas: tk.Canvas, key: object, item: int, *,
            alive: Callable[[], bool]) -> None:
    """A new arrow (a line with its head at the end) draws itself from its tail to its head:
    the curve Tk would draw is followed as a polyline, then the line is given back its own
    points and ``smooth``. Rerouted meanwhile: it keeps the new route."""
    points = canvas.coords(item)
    if len(points) < 4:
        return
    smooth = str(canvas.itemcget(item, "smooth"))
    path = spline(points) if smooth not in ("0", "false", "no", "raw", "") else points
    lengths = _lengths(path)
    last = [points]

    def step(p: float) -> None:
        if not alive():
            return
        same = _near(canvas.coords(item), last[0])
        if p >= 1.0:
            canvas.itemconfigure(item, smooth=smooth)
            if same:
                canvas.coords(item, *points)
            return
        if not same:
            return
        if last[0] is points:
            canvas.itemconfigure(item, smooth=False)
        canvas.coords(item, *_prefix(path, lengths, max(1.0, lengths[-1] * p)))
        last[0] = canvas.coords(item)

    motion.tween(key, DRAW_MS, step, visible=canvas.winfo_viewable)


def spline(points: Sequence[float]) -> list[float]:
    """The curve Tk draws for a ``smooth`` line through ``points`` (x, y, ...), as a
    polyline: quadratic pieces from the first point through the midpoints to the last, each
    bent towards its control point (``TkMakeBezierCurve`` for an open line)."""
    pts = [(points[i], points[i + 1]) for i in range(0, len(points) - 1, 2)]
    if len(pts) < 3:
        return list(points)
    out = [*pts[0]]
    n = len(pts)
    for i in range(1, n - 1):
        a = pts[0] if i == 1 else _mid(pts[i - 1], pts[i])
        b = pts[-1] if i == n - 2 else _mid(pts[i], pts[i + 1])
        c = pts[i]
        for k in range(1, SPLINE_STEPS + 1):
            t = k / SPLINE_STEPS
            u = 1.0 - t
            out += [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0],
                    u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]]
    return out


@dataclass(frozen=True)
class Ghost:
    """Text lines as they were drawn: runs of (x, y from the top, text, colour, font)."""

    parts: tuple[tuple[float, float, str, str, str], ...]
    height: int


def text_ghost(text: tk.Text, first: int, last: int) -> Ghost | None:
    """Lines ``first``..``last`` of ``text`` as drawn now, to fade once they are gone; None
    when they aren't on screen."""
    try:
        top, bottom = text.dlineinfo(f"{first}.0"), text.dlineinfo(f"{last}.end")
    except tk.TclError:
        return None
    if top is None or bottom is None:
        return None
    y0 = top[1]
    order = {name: i for i, name in enumerate(text.tag_names())}  # lowest priority first
    default_fg, default_font = str(text.cget("foreground")), str(text.cget("font"))
    parts = []
    for line in range(first, last + 1):
        for kind, value, index in text.dump(f"{line}.0", f"{line}.end", text=True, tag=True):
            if kind != "text" or not value.strip():
                continue
            box = text.bbox(index)
            if box is None:
                continue
            tags = sorted(text.tag_names(index), key=lambda name: order.get(name, -1))
            fg = next((str(text.tag_cget(t, "foreground")) for t in reversed(tags)
                       if text.tag_cget(t, "foreground")), default_fg)
            font = next((str(text.tag_cget(t, "font")) for t in reversed(tags)
                         if text.tag_cget(t, "font")), default_font)
            parts.append((float(box[0]), float(box[1] - y0), value.rstrip("\n"), fg, font))
    return Ghost(tuple(parts), int(bottom[1] + bottom[3] - y0))


GAP_TAG: Final = "motion-gap"


def fade_rows(motion: Motion, key: object, text: tk.Text, ghost: Ghost,
              below: int | None) -> None:
    """Rows just deleted from ``text`` (``ghost``: how they looked) fade where they were, then
    the rows below close the gap. ``below``: the line now in their place (None: they were the
    last). A gap above that line (a tag's ``spacing1``) keeps the rows still, and a canvas in
    the gap shows the ghost; no line is added, so row numbers stay true."""
    if motion.stopped or _ask(motion.reduce) or not ghost.parts:
        return
    motion.finish(key)
    try:
        if not text.winfo_viewable():
            return
        if below is not None:
            text.tag_configure(GAP_TAG, spacing1=ghost.height)
            text.tag_add(GAP_TAG, f"{below}.0", f"{below}.end")
            text.tag_raise(GAP_TAG)
            info = text.dlineinfo(f"{below}.0")
            y = None if info is None else info[1]
        else:
            info = text.dlineinfo("end-1c")
            y = None if info is None else info[1] + info[3]
        if y is None:
            text.tag_delete(GAP_TAG)
            return
        background = str(text.cget("background"))
        overlay = tk.Canvas(text, background=background, highlightthickness=0, borderwidth=0,
                            takefocus=0, height=ghost.height)
        width = text.winfo_width()
        items = [(overlay.create_text(x, top, anchor="nw", text=words, fill=fg, font=font,
                                      width=max(1, width - x)), fg)
                 for x, top, words, fg, font in ghost.parts]
        overlay.place(in_=text, x=0, y=y, relwidth=1.0, height=ghost.height,
                      bordermode="outside")
    except tk.TclError:
        return

    def step(p: float) -> None:
        if p >= 1.0:
            try:
                overlay.destroy()
                text.tag_delete(GAP_TAG)
            except tk.TclError:
                pass
            return
        for item, fg in items:
            overlay.itemconfigure(item, fill=fade(fg, background, min(1.0, p / 0.6)))
        if p > 0.4:
            room = max(0, round(ghost.height * (1.0 - (p - 0.4) / 0.6)))
            overlay.place_configure(height=max(1, room))
            if below is not None:
                text.tag_configure(GAP_TAG, spacing1=room)

    motion.tween(key, ROW_FADE_MS, step, visible=text.winfo_viewable)


def count_to(motion: Motion, key: object, start: Sequence[int], end: Sequence[int],
             show: Callable[[tuple[int, ...] | None], None]) -> None:
    """Numbers tick from ``start`` to ``end`` together: ``show(values)`` on each step, and
    ``show(None)`` (the real text again) at the end."""
    if tuple(start) == tuple(end) or len(start) != len(end):
        show(None)
        return

    def step(p: float) -> None:
        show(None if p >= 1.0 else tuple(round(a + (b - a) * p)
                                          for a, b in zip(start, end)))

    motion.tween(key, COUNT_MS, step)


def clean_chip(motion: Motion, key: object, label: tk.Label, *, image: object, color: str,
               tint: str, rest: tuple[str, str]) -> None:
    """A clean check: ``label`` turns ``color`` on ``tint`` with ``image`` (a tick) at its
    left for ``CLEAN_MS``, then fades back to ``rest`` (foreground, background)."""
    def on() -> None:
        label.configure(image=image, compound="left", foreground=color, background=tint)

    def off(p: float) -> None:
        label.configure(foreground=fade(color, rest[0], p), background=fade(tint, rest[1], p))
        if p >= 1.0:
            label.configure(image="")

    motion.hold(key, CLEAN_MS, on, off)


def _is_hex(color: str) -> bool:
    return len(color) == 7 and color[0] == "#"


def _near(a: Sequence[float], b: Sequence[float]) -> bool:
    return len(a) == len(b) and all(abs(x - y) < 0.05 for x, y in zip(a, b))


def _centres(cx: float, cy: float, n: int) -> list[float]:
    return [cx if i % 2 == 0 else cy for i in range(n)]


def _mid(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def _lengths(path: Sequence[float]) -> list[float]:
    total, found = 0.0, [0.0]
    for i in range(2, len(path) - 1, 2):
        total += math.hypot(path[i] - path[i - 2], path[i + 1] - path[i - 1])
        found.append(total)
    return found


def _prefix(path: Sequence[float], lengths: Sequence[float], length: float) -> list[float]:
    """The first ``length`` of polyline ``path`` (at least two points)."""
    out = [path[0], path[1]]
    for j in range(1, len(lengths)):
        x, y = path[2 * j], path[2 * j + 1]
        if lengths[j] >= length:
            span = lengths[j] - lengths[j - 1]
            t = 1.0 if span <= 0 else (length - lengths[j - 1]) / span
            px, py = path[2 * j - 2], path[2 * j - 1]
            out += [px + (x - px) * t, py + (y - py) * t]
            return out
        out += [x, y]
    return out


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


__all__ = ["CLEAN_MS", "COUNT_MS", "DRAW_MS", "FADE_MS", "FRAME_MS", "Ghost", "HOLD_MS",
           "MAX_MS", "Motion", "POP_FROM", "POP_MS", "ROW_FADE_MS", "clean_chip", "count_to",
           "draw_on", "ease_out", "fade", "fade_rows", "pop_in", "spline", "text_ghost"]
