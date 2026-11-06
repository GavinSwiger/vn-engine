"""Milestone celebrations and Studio's small motions (Studio UX ideas 4.1, 4.2, 9.2), as
the ``CelebrationWiring`` mixin of ``window.EditorWindow``.

Why this module exists: a few moments in making a first game deserve a small "well done",
and a few changes deserve a moment of motion so you see them land. Both must stay calm on
hour three, so they are few, short, silent, never take the keyboard, and Reduce motion
turns every motion into an instant change.

- **Milestones** (``Milestones``, pure): five, each shown once per game and remembered in
  ``studio.json``'s ``celebrated`` (``studiostate``): the first Play that reaches the game
  window (``play``), a first choice (``choice``), a first ending of the author's own
  (``ending``), every Guide step ticked (``guide``) and a first finished build
  (``build``). Choices, endings and the Guide count only when they change while Studio is
  open (the first check of a session is the baseline), so opening an old game never
  celebrates what was already there. A game made from the sample story counts a choice
  past the sample's own, and only its own endings (``guide.SAMPLE_BASELINE``). When the
  Guide finishes on the same step as another milestone, only the Guide's toast shows.
- **Toast** (``Toasts``): one small card in the window's bottom-right corner, above the
  status bar: a tick, a title and one line. It slides up 10 px and a brief burst of
  confetti rises from the tick (``CONFETTI_MS``); under Reduce motion it simply appears.
  It waits while a dialog holds the window or Studio isn't the active app (so the first
  Play's toast shows when you come back from the game), never takes focus, goes on a
  click or after ``TOAST_MS`` (the pointer over it keeps it), and makes no sound.
- **Motions** (``motion.Motion``, one clock per window, also given to the story map): the
  status bar's problem counts turn green for a moment when they go down (a fix landed),
  and an Assistant card's border flashes green once when it is applied.

Tk; imports only the standard library and the editor's own modules (ADR-0008).
"""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from tkinter import font as tkfont
from typing import Any, Final

from engine.tools.editor import guide, icons, studiostate
from engine.tools.editor.guide import GuideFacts
from engine.tools.editor.motion import FADE_MS, HOLD_MS, Motion, fade
from engine.tools.editor.theme import THEME

PLAY: Final = "play"
CHOICE: Final = "choice"
ENDING: Final = "ending"
GUIDE: Final = "guide"
BUILD: Final = "build"
MILESTONES: Final = (PLAY, CHOICE, ENDING, GUIDE, BUILD)

# Title and line for each milestone ({name}: the ending's name).
TEXTS: Final = {
    PLAY: ("First play", "Your story ran in its own window."),
    CHOICE: ("First choice", "Players can now take different paths."),
    ENDING: ("First ending: {name}", "Your story can finish now."),
    GUIDE: ("Your first game is done", "Every step of the Guide is ticked."),
    BUILD: ("First build", "Your game is ready to share."),
}

TOAST_W, TOAST_H = 320, 60              # px at 100 %
TOAST_INSET = 16                        # from the window's right edge and the status bar
TOAST_MS: Final = 6000                  # shown this long
TOAST_LINGER_MS: Final = 2500           # after the pointer leaves it
TOAST_GAP_MS: Final = 600               # between two toasts
TOAST_WAIT_MS: Final = 400              # how often a waiting toast asks again
SLIDE_PX: Final = 10
CONFETTI_MS: Final = 900                # the celebration's one exception to motion.MAX_MS
CONFETTI_COUNT: Final = 16
CONFETTI_COLORS: Final = (THEME["success"], THEME["info"], THEME["marker.warning"],
                          THEME["map.ending"], THEME["map.minigame"])

CARD: Final = THEME["card.background"]
CARD_BORDER: Final = THEME["widget.border"]
SUCCESS: Final = THEME["success"]


@dataclass(frozen=True, slots=True)
class Celebration:
    """One milestone to show: its key and, for an ending, the ending's name."""

    key: str
    name: str = ""

    def texts(self) -> tuple[str, str]:
        title, line = TEXTS[self.key]
        return title.format(name=self.name or "?"), line


class Milestones:
    """Which milestones a moment brings (pure). ``celebrated``: the game's shown ones;
    ``sample``: the game came from the sample story."""

    def __init__(self, celebrated: Iterable[str] = (), *, sample: bool = False) -> None:
        self.celebrated: set[str] = set(celebrated)
        self.sample = sample
        self._base: GuideFacts | None = None
        self._guide_done: bool | None = None

    def _own_endings(self, facts: GuideFacts) -> frozenset[str]:
        return facts.endings - (guide.SAMPLE_BASELINE.endings if self.sample else frozenset())

    def after_check(self, facts: GuideFacts, guide_done: bool) -> list[Celebration]:
        """A check that loaded: the first is the session's baseline; later ones bring a
        first choice, a first ending and the Guide finished."""
        if self._base is None:
            self._base, self._guide_done = facts, guide_done
            return []
        base, found = self._base, []
        if facts.choices > base.choices and (base.choices == 0 or self.sample):
            found.append(Celebration(CHOICE))
        new_endings = self._own_endings(facts) - self._own_endings(base)
        if new_endings and not self._own_endings(base):
            found.append(Celebration(ENDING, min(new_endings)))
        found += self._guide(guide_done)
        return self._fresh(found)

    def played(self, guide_done: bool) -> list[Celebration]:
        """A Play reached the game window for the first time in this game."""
        return self._fresh([Celebration(PLAY), *self._guide(guide_done)])

    def built(self) -> list[Celebration]:
        """A build finished."""
        return self._fresh([Celebration(BUILD)])

    def _guide(self, done: bool) -> list[Celebration]:
        was, known = self._guide_done, self._guide_done is not None
        if known:
            self._guide_done = bool(was) or done
        return [Celebration(GUIDE)] if known and done and not was else []

    def _fresh(self, found: list[Celebration]) -> list[Celebration]:
        """The ones not shown before in this game, marked as shown; the Guide's alone when
        it is among them."""
        fresh = [c for c in found if c.key not in self.celebrated]
        self.celebrated.update(c.key for c in fresh)
        if any(c.key == GUIDE for c in fresh):
            fresh = [c for c in fresh if c.key == GUIDE]
        return fresh


# --- The toast ----------------------------------------------------------------------------

class Toast:
    """One celebration card, placed in ``root``'s bottom-right corner (see the module doc)."""

    def __init__(self, root: tk.Misc, celebration: Celebration, *, fonts: dict, scale: float,
                 motion: Motion, bottom: int, on_close: Callable[[], None]) -> None:
        self.root, self.celebration, self.motion = root, celebration, motion
        self.on_close = on_close
        self.scale = scale
        px = self.px
        self.width, self.height = px(TOAST_W), px(TOAST_H)
        self.title, self.line = celebration.texts()
        canvas = self.canvas = tk.Canvas(root, width=self.width, height=self.height,
                                         background=CARD, highlightthickness=0,
                                         borderwidth=0, takefocus=0, cursor="hand2")
        canvas.create_rectangle(0, 0, self.width - 1, self.height - 1, outline=CARD_BORDER)
        canvas.create_rectangle(1, 1, 1 + max(2, px(3)), self.height - 1, fill=SUCCESS,
                                outline="")
        icon = px(20)
        self.icon_at = (px(14) + icon / 2, self.height / 2)
        self._image = icons.photo(canvas, "success", icon, SUCCESS)
        self.icon = canvas.create_image(*self.icon_at, image=self._image)
        left, room = px(44), self.width - px(44) - px(28)
        strong: tkfont.Font = fonts.get("bodyStrong") or fonts["body"]
        small: tkfont.Font = fonts.get("small") or fonts["body"]
        self.title_item = canvas.create_text(left, px(11), anchor="nw", font=strong,
                                             fill=THEME["strongForeground"],
                                             text=_fit(self.title, room, strong))
        canvas.create_text(left, px(32), anchor="nw", font=small, fill=THEME["muted"],
                           text=_fit(self.line, room, small))
        self.close_item = canvas.create_text(self.width - px(12), px(9), anchor="ne",
                                             text="✕", font=small, fill=THEME["muted"])
        canvas.tag_bind(self.close_item, "<Enter>", lambda _e: canvas.itemconfigure(
            self.close_item, fill=THEME["foreground"]))
        canvas.tag_bind(self.close_item, "<Leave>", lambda _e: canvas.itemconfigure(
            self.close_item, fill=THEME["muted"]))
        canvas.bind("<Button-1>", lambda _e: self.close())
        canvas.bind("<Enter>", lambda _e: self._hold())
        canvas.bind("<Leave>", lambda _e: self._arm(TOAST_LINGER_MS))
        self.closed = False
        self._timer: str | None = None
        self.particles: list[tuple[int, float, float, float, float, str]] = []
        self._x, self._y = -px(TOAST_INSET), -(bottom + px(12))
        canvas.place(in_=root, relx=1.0, rely=1.0, anchor="se", x=self._x, y=self._y)
        canvas.tk.call("raise", canvas._w)          # Canvas.lift raises items, not the widget
        motion.tween(("toast", "slide"), FADE_MS, self._slide)
        if not motion.reduce():
            self._confetti()
        self._arm(TOAST_MS)

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def _slide(self, p: float) -> None:
        if not self.closed:
            self.canvas.place_configure(y=self._y + round(self.px(SLIDE_PX) * (1.0 - p)))

    def _confetti(self) -> None:
        """A small burst around the tick: pieces fly out, slow down and sink a little,
        fading into the card (deterministic; drawn under the texts, kept on the card)."""
        canvas, px = self.canvas, self.px
        cx, cy = self.icon_at
        size = max(2, px(4))
        for i in range(CONFETTI_COUNT):
            angle = math.radians(-90 + 360 * i / CONFETTI_COUNT + 7 * (i % 3))
            speed = px(32 + 26 * ((i * 7) % 5) / 4)
            color = CONFETTI_COLORS[i % len(CONFETTI_COLORS)]
            item = canvas.create_rectangle(cx, cy, cx + size, cy + size - (i % 2),
                                           fill=color, outline="")
            canvas.tag_lower(item, self.title_item)
            canvas.tag_lower(item, self.icon)
            self.particles.append((item, cx, cy, math.cos(angle) * speed,
                                   math.sin(angle) * speed, color))
        self.motion.tween(("toast", "confetti"), CONFETTI_MS, self._burst,
                          cap=CONFETTI_MS)

    def _burst(self, p: float) -> None:
        if self.closed:
            return
        canvas, size = self.canvas, max(2, self.px(4))
        t = p * CONFETTI_MS / 1000              # p is eased: quick out, slow settle
        gravity = self.px(45)
        for item, x, y, vx, vy, color in self.particles:
            if p >= 1.0:
                canvas.delete(item)
                continue
            nx, ny = x + vx * t, y + vy * t + gravity * t * t / 2
            canvas.coords(item, nx, ny, nx + size, ny + size)
            if p > 0.55:
                canvas.itemconfigure(item, fill=fade(color, CARD, (p - 0.55) / 0.45))
        if p >= 1.0:
            self.particles = []

    def _hold(self) -> None:
        if self._timer is not None:
            try:
                self.canvas.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None

    def _arm(self, ms: int) -> None:
        self._hold()
        if not self.closed:
            self._timer = self.canvas.after(ms, self.close)

    def close(self) -> None:
        """Gone at once (a click, the timer, the window closing)."""
        if self.closed:
            return
        self._hold()
        self.closed = True
        self.motion.finish(("toast", "slide"))
        self.motion.finish(("toast", "confetti"))
        try:
            self.canvas.destroy()
        except tk.TclError:
            pass
        self.on_close()


def _fit(text: str, width: int, font: tkfont.Font) -> str:
    if font.measure(text) <= width:
        return text
    while text and font.measure(text + "…") > width:
        text = text[:-1]
    return text.rstrip() + "…"


class Toasts:
    """Celebrations waiting to show, one at a time. ``ready()`` says the window may show
    one now; ``bottom()`` is the status bar's height; ``on_shown(c)`` runs as each shows."""

    def __init__(self, root: tk.Misc, *, fonts: dict, scale: float, motion: Motion,
                 bottom: Callable[[], int], ready: Callable[[], bool],
                 on_shown: Callable[[Celebration], None]) -> None:
        self.root, self.fonts, self.scale, self.motion = root, fonts, scale, motion
        self.bottom, self.ready, self.on_shown = bottom, ready, on_shown
        self.waiting: list[Celebration] = []
        self.toast: Toast | None = None
        self._timer: str | None = None
        self.stopped = False

    def add(self, celebrations: Iterable[Celebration]) -> None:
        for celebration in celebrations:
            if celebration.key == GUIDE:            # the Guide's toast says it all
                self.waiting = []
            self.waiting.append(celebration)
        self._pump()

    def _pump(self) -> None:
        if self.stopped or self.toast is not None or not self.waiting or self._timer:
            return
        if not self.ready():
            self._later(TOAST_WAIT_MS)
            return
        celebration = self.waiting.pop(0)
        self.toast = Toast(self.root, celebration, fonts=self.fonts, scale=self.scale,
                           motion=self.motion, bottom=self.bottom(), on_close=self._closed)
        self.on_shown(celebration)

    def _later(self, ms: int) -> None:
        def again() -> None:
            self._timer = None
            self._pump()
        try:
            self._timer = self.root.after(ms, again)
        except tk.TclError:
            self._timer = None

    def _closed(self) -> None:
        self.toast = None
        if self.waiting and not self.stopped:
            self._later(TOAST_GAP_MS)

    def stop(self) -> None:
        self.stopped = True
        self.waiting = []
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        if self.toast is not None:
            self.toast.close()


def flash(motion: Motion, key: object, widget: tk.Misc, option: str, color: str,
          rest: str) -> None:
    """A "this changed" colour on ``widget``'s ``option``: ``color`` for ``HOLD_MS``, then
    back to ``rest`` (a short fade; a cut under Reduce motion)."""
    def off(p: float) -> None:
        widget.configure(**{option: fade(color, rest, p)})

    motion.hold(key, HOLD_MS, lambda: widget.configure(**{option: color}), off)


# --- The window's wiring ------------------------------------------------------------------

class CelebrationWiring:
    """``EditorWindow``'s milestones, toasts and motions (see the module doc)."""

    root: tk.Tk
    motion: Motion
    milestones: Milestones
    toasts: Toasts
    _problem_total: int | None = None

    def _build_celebrations(self) -> None:
        """After the panes, the map and the status bar exist."""
        win: Any = self
        self.motion = Motion(self.root, reduce=self._motion_reduced)
        win.story_map.motion = self.motion
        state = studiostate.read_state(win.paths.root)
        known = state if isinstance(state, studiostate.StudioState) else None
        self.milestones = Milestones(known.celebrated if known else (),
                                     sample=bool(known and known.sample))
        self.toasts = Toasts(self.root, fonts=win.fonts, scale=win.scale, motion=self.motion,
                             bottom=self._toast_bottom, ready=self._toast_ready,
                             on_shown=self._celebrated)
        self._problem_total = None
        win.on_check_done.append(self._celebration_check)

    def stop_celebrations(self) -> None:
        """The window closes."""
        if hasattr(self, "toasts"):
            self.toasts.stop()
            self.motion.stop()

    def _motion_reduced(self) -> bool:
        var = getattr(self, "reduce_motion", None)
        return bool(var.get()) if var is not None else False

    def _toast_bottom(self) -> int:
        bar = getattr(self, "status_bar", None)
        if bar is None:
            return 0
        return bar.frame.winfo_height() + bar.divider.winfo_height()

    def _toast_ready(self) -> bool:
        """No dialog holds the window, it is shown, and Studio is the active app."""
        root = self.root
        try:
            if root.grab_current() is not None or not root.winfo_viewable():
                return False
            return root.focus_displayof() is not None
        except (tk.TclError, KeyError):
            return False

    def _celebrated(self, celebration: Celebration) -> None:
        """A toast showed: remember every milestone marked so far for this game."""
        win: Any = self
        state = studiostate.read_state(win.paths.root)
        stored = state.celebrated if isinstance(state, studiostate.StudioState) else ()
        win.save_studio_state(celebrated=tuple(sorted(set(stored)
                                                      | self.milestones.celebrated)))

    # -- Moments ------------------------------------------------------------------------------

    def _celebration_check(self, result: Any) -> None:
        """After each applied check: the counts' flash, then the check's milestones."""
        win: Any = self
        if win.closed:
            return
        from engine.tools.editor.checkwiring import check_counts
        errors, warnings = check_counts(result)
        total, before = errors + warnings, self._problem_total
        self._problem_total = total
        if before is not None and total < before:
            label = win.check_counts.label
            flash(self.motion, "counts", label, "foreground", SUCCESS,
                  win.status_bar.foreground)
        facts = getattr(win, "_guide_facts", None)
        if not getattr(result, "loaded", False) or facts is None:
            return
        self.toasts.add(self.milestones.after_check(facts, guide.all_done(win.guide_rows())))

    def guide_played(self) -> None:
        """A Play reached the game window for the first time (``runwiring``)."""
        win: Any = self
        super().guide_played()                  # type: ignore[misc]
        self.toasts.add(self.milestones.played(guide.all_done(win.guide_rows())))

    def build_finished(self) -> None:
        """A build ended well (``builddialog``)."""
        self.toasts.add(self.milestones.built())

    def card_applied(self, frame: tk.Misc) -> None:
        """An Assistant card was applied: its border flashes green once."""
        flash(self.motion, ("card", str(frame)), frame, "highlightbackground", SUCCESS,
              THEME["border"])


__all__ = ["BUILD", "CHOICE", "CONFETTI_MS", "Celebration", "CelebrationWiring", "ENDING",
           "GUIDE", "MILESTONES", "Milestones", "PLAY", "TEXTS", "TOAST_MS", "Toast", "Toasts",
           "flash"]
