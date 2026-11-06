"""Milestone celebrations and Studio's small motions (Studio UX ideas 4.1, 4.2, 9.2), as
the ``CelebrationWiring`` mixin of ``window.EditorWindow``.

Why this module exists: a few moments in making a first game deserve a small "well done",
and a few changes deserve a moment of motion so you see them land. Both must stay calm on
hour three, so they are few, short, silent, never take the keyboard, and Reduce motion
turns every motion into an instant change.

- **Milestones** (``Milestones``, pure): five, each shown once per game and remembered in
  ``studio.json``'s ``celebrated`` (``studiostate``): the first Play that reaches the game
  window (``play``), a first choice in the author's own scene (``choice``), the first
  ending a Play reaches (``ending``, from the game's line reports: ``runwiring``'s
  ``on_game_event``), every Guide step ticked (``guide``) and a first finished build
  (``build``). Choices and the Guide count only when they change while Studio is open (the
  first check of a session is the baseline), so opening an old game never celebrates what
  was already there; a game made from the sample story counts a choice past the sample's
  own (``guide.SAMPLE_BASELINE``). When the Guide finishes on the same step as another
  milestone, only the Guide's shows.
- **Lanterns** (``Lanterns``): paper lanterns, drawn as polygons with a warm glow, float up
  for ``LANTERN_MS`` (about two seconds): across the story map when it is showing, else in
  a small evening sky over Studio's lower right corner, just above the toast. They are the
  budget's one longer motion (at most five per game, ever); they never take input.
- **Toast** (``Toast``): one line on a small card in the window's bottom-right corner,
  above the status bar, e.g. "First ending reached: Lantern End." with a still lantern at
  its left. It slides up 10 px; under Reduce motion there are no lanterns and the card is a
  still banner. It waits while a dialog holds the window or Studio isn't the active app (so
  the first Play's toast shows when you come back from the game), never takes focus, goes
  on a click or after ``TOAST_MS`` (the pointer over it keeps it), and makes no sound.
- **Motions** (``motion``, one clock per window, also given to the story map and the
  Events list): the status bar's problem count ticks to its new value after a check, and a
  check that comes back clean turns that chip green with a tick for a second.

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
from engine.tools.editor.motion import FADE_MS, Motion, clean_chip, count_to, fade
from engine.tools.editor.theme import THEME, blend

PLAY: Final = "play"
CHOICE: Final = "choice"
ENDING: Final = "ending"
GUIDE: Final = "guide"
BUILD: Final = "build"
MILESTONES: Final = (PLAY, CHOICE, ENDING, GUIDE, BUILD)

# Each milestone's one line, as a bold head and the rest ({name}: the ending's title).
TEXTS: Final = {
    PLAY: ("First Play:", "your story ran in its own window."),
    CHOICE: ("First choice:", "players can take different paths now."),
    ENDING: ("First ending reached:", "{name}."),
    GUIDE: ("Guide finished:", "your first game is done."),
    BUILD: ("First build:", "your game is ready to share."),
}
NAME_MAX: Final = 60                    # an ending's title is cut to this many characters

TOAST_MIN_W, TOAST_MAX_W, TOAST_H = 240, 460, 40     # px at 100 %
TOAST_INSET = 16                        # from the window's right edge and the status bar
TOAST_MS: Final = 6000                  # shown this long
TOAST_LINGER_MS: Final = 2500           # after the pointer leaves it
TOAST_GAP_MS: Final = 600               # between two toasts
TOAST_WAIT_MS: Final = 400              # how often a waiting toast asks again
SLIDE_PX: Final = 10

LANTERN_MS: Final = 2000                # the celebration's one exception to motion.MAX_MS
LANTERN_COUNT: Final = 7
SKY_W, SKY_H = 300, 170                 # px at 100 %: the sky when the map isn't showing
# The sample game's lanterns at dusk: warm paper, a darker frame, a bright flame.
LANTERN_PAPER: Final = "#F2A45A"
LANTERN_SHADE: Final = "#D9803E"
LANTERN_FRAME: Final = "#9C4F22"
LANTERN_FLAME: Final = "#FFE7A8"
LANTERN_GLOW: Final = "#F7B866"
SKY: Final = "#1C2236"                  # the small sky's evening blue

CARD: Final = THEME["card.background"]
CARD_BORDER: Final = THEME["widget.border"]
SUCCESS: Final = THEME["success"]


@dataclass(frozen=True, slots=True)
class Celebration:
    """One milestone to show: its key and, for an ending, the ending's title."""

    key: str
    name: str = ""

    def texts(self) -> tuple[str, str]:
        """The line's bold head and its rest."""
        head, rest = TEXTS[self.key]
        name = " ".join(self.name.split())[:NAME_MAX] or "?"
        return head, rest.format(name=name)

    def line(self) -> str:
        return " ".join(self.texts())


class Milestones:
    """Which milestones a moment brings (pure). ``celebrated``: the game's shown ones;
    ``sample``: the game came from the sample story."""

    def __init__(self, celebrated: Iterable[str] = (), *, sample: bool = False) -> None:
        self.celebrated: set[str] = set(celebrated)
        self.sample = sample
        self._base: GuideFacts | None = None
        self._guide_done: bool | None = None

    def after_check(self, facts: GuideFacts, guide_done: bool) -> list[Celebration]:
        """A check that loaded: the first is the session's baseline; later ones bring a
        first choice and the Guide finished."""
        if self._base is None:
            self._base, self._guide_done = facts, guide_done
            return []
        base, found = self._base, []
        if facts.choices > base.choices and (base.choices == 0 or self.sample):
            found.append(Celebration(CHOICE))
        found += self._guide(guide_done)
        return self._fresh(found)

    def reached(self, title: str) -> list[Celebration]:
        """A Play ran an ``ending`` line (``title``: the ending's title, or its name)."""
        return self._fresh([Celebration(ENDING, title)])

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


# --- Lanterns -------------------------------------------------------------------------------

# A sky lantern's outline around its centre, in units of its height: a paper body a little
# wider at the shoulders than at the open bottom (drawn ``smooth``, so the corners round).
LANTERN_SHAPE: Final = ((-0.30, -0.50), (0.30, -0.50), (0.38, -0.30), (0.34, 0.32),
                        (0.24, 0.50), (-0.24, 0.50), (-0.34, 0.32), (-0.38, -0.30))
# Where each lantern starts (share of the width), how tall it is (px at 100 %), when it
# sets off and how long it rises (shares of LANTERN_MS), and its sway.
FLIGHTS: Final = ((0.16, 34, 0.00, 0.82, 0.0), (0.42, 42, 0.06, 0.88, 1.7),
                  (0.72, 32, 0.03, 0.80, 3.1), (0.88, 26, 0.16, 0.78, 0.9),
                  (0.30, 24, 0.22, 0.76, 2.4), (0.58, 30, 0.12, 0.82, 4.0),
                  (0.05, 22, 0.26, 0.72, 5.2))
# The warm glow: soft ovals around each lantern, (half width, half height, share of glow).
HALOS: Final = (("halo0", 0.78, 0.92, 0.10), ("halo1", 0.62, 0.76, 0.18),
                ("halo2", 0.50, 0.64, 0.30))


def lantern_points(cx: float, cy: float, h: float, tilt: float) -> list[float]:
    """The lantern body's polygon at (cx, cy), ``h`` tall, turned by ``tilt`` radians."""
    c, s = math.cos(tilt), math.sin(tilt)
    out: list[float] = []
    for x, y in LANTERN_SHAPE:
        out += [cx + (x * c - y * s) * h, cy + (x * s + y * c) * h]
    return out


class Lanterns:
    """Paper lanterns floating up over ``canvas``'s visible part for ``LANTERN_MS``, then
    gone. ``surface`` is what they fade into; ``scale`` the screen scale. The items are
    tagged ``TAG``, sit on top, are ``disabled`` (no hover, no clicks) and are deleted at the
    end, when the canvas is hidden, and on ``stop``."""

    TAG: Final = "celebration-lantern"

    def __init__(self, canvas: tk.Canvas, motion: Motion, *, surface: str, scale: float,
                 key: object = ("celebration", "lanterns"),
                 on_done: Callable[[], None] | None = None) -> None:
        self.canvas, self.motion, self.surface, self.scale = canvas, motion, surface, scale
        self.key = key
        self.flying: list[dict] = []
        line = max(1, round(scale))
        colors = {name: blend(LANTERN_GLOW, surface, share) for name, _w, _h, share in HALOS}
        colors |= {"body": LANTERN_PAPER, "lit": blend(LANTERN_FLAME, LANTERN_PAPER, 0.45),
                   "rib": LANTERN_SHADE, "band": LANTERN_FRAME, "flame": LANTERN_FLAME}
        for x, size, start, life, phase in FLIGHTS[:LANTERN_COUNT]:
            items = {name: canvas.create_oval(0, 0, 0, 0, fill=colors[name], outline="")
                     for name, *_rest in HALOS}
            items["body"] = canvas.create_polygon(0, 0, 0, 0, 0, 0, smooth=True,
                                                  fill=LANTERN_PAPER, outline=LANTERN_FRAME,
                                                  width=line)
            items["lit"] = canvas.create_polygon(0, 0, 0, 0, 0, 0, smooth=True,
                                                 fill=colors["lit"], outline="")
            items["rib"] = canvas.create_line(0, 0, 0, 0, fill=LANTERN_SHADE, width=line)
            items["band"] = canvas.create_line(0, 0, 0, 0, fill=LANTERN_FRAME,
                                               width=max(2, 2 * line))
            items["flame"] = canvas.create_oval(0, 0, 0, 0, fill=LANTERN_FLAME, outline="")
            for item in items.values():
                canvas.itemconfigure(item, state="hidden", tags=(self.TAG,))
            self.flying.append({"x": x, "h": size * scale, "start": start, "life": life,
                                "phase": phase, "items": items})
        self.colors = colors
        canvas.tag_raise(self.TAG)
        self.done = False
        self._on_done = on_done
        motion.tween(key, LANTERN_MS, self._step, visible=canvas.winfo_viewable,
                     cap=LANTERN_MS)

    def _view(self) -> tuple[float, float, float, float]:
        canvas = self.canvas
        return (canvas.canvasx(0), canvas.canvasy(0), max(1, canvas.winfo_width()),
                max(1, canvas.winfo_height()))

    def _step(self, p: float) -> None:
        if self.done:
            return
        if p >= 1.0:
            self._end()
            return
        t = 1.0 - (1.0 - p) ** (1.0 / 3.0)      # the tween eases; the lanterns rise evenly
        canvas = self.canvas
        left, top, width, height = self._view()
        for lantern in self.flying:
            items, h = lantern["items"], lantern["h"]
            q = (t - lantern["start"]) / lantern["life"]
            if q <= 0.0 or q >= 1.0:
                for item in items.values():
                    canvas.itemconfigure(item, state="hidden")
                continue
            rise = q * (height + 3 * h)          # from under the bottom edge to over the top
            cy = top + height + 1.5 * h - rise
            wave = lantern["phase"] + q * 5.0
            cx = left + lantern["x"] * width + math.sin(wave) * 0.6 * h
            tilt = 0.10 * math.sin(wave + 0.6)
            c, s = math.cos(tilt), math.sin(tilt)
            flicker = 0.11 + 0.025 * math.sin(q * 40.0 + lantern["phase"])
            for name, w, hh, _share in HALOS:
                r = 1.0 + 0.6 * flicker
                canvas.coords(items[name], cx - w * h * r, cy - hh * h * r,
                              cx + w * h * r, cy + hh * h * r)
            canvas.coords(items["body"], *lantern_points(cx, cy, h, tilt))
            lx, ly = cx - 0.12 * h * s, cy + 0.12 * h * c     # the light, low in the body
            canvas.coords(items["lit"], *lantern_points(lx, ly, 0.62 * h, tilt))
            canvas.coords(items["rib"], cx + 0.45 * h * s, cy - 0.45 * h * c,
                          cx - 0.45 * h * s, cy + 0.45 * h * c)
            bx, by = cx - 0.44 * h * s, cy + 0.44 * h * c
            canvas.coords(items["band"], bx - 0.24 * h * c, by - 0.24 * h * s,
                          bx + 0.24 * h * c, by + 0.24 * h * s)
            fx, fy = cx - 0.30 * h * s, cy + 0.30 * h * c
            canvas.coords(items["flame"], fx - flicker * h, fy - 1.4 * flicker * h,
                          fx + flicker * h, fy + 1.4 * flicker * h)
            dim = max(0.0, (q - 0.65) / 0.35)    # fades out over the last third of its rise
            for name, item in items.items():
                canvas.itemconfigure(item, state="disabled",
                                     fill=fade(self.colors[name], self.surface, dim))
            canvas.itemconfigure(items["body"], outline=fade(LANTERN_FRAME, self.surface, dim))

    def _end(self) -> None:
        self.done = True
        try:
            for lantern in self.flying:
                for item in lantern["items"].values():
                    self.canvas.delete(item)
        except tk.TclError:
            pass
        self.flying = []
        if self._on_done is not None:
            self._on_done()

    def stop(self) -> None:
        if not self.done:
            self.motion.finish(self.key)
            if not self.done:
                self._end()


def still_lantern(canvas: tk.Canvas, cx: float, cy: float, h: float, scale: float) -> None:
    """The toast's small lantern, still."""
    line = max(1, round(scale))
    canvas.create_oval(cx - 0.9 * h, cy - 0.9 * h, cx + 0.9 * h, cy + 0.9 * h,
                       fill=blend(LANTERN_GLOW, CARD, 0.22), outline="")
    canvas.create_polygon(*lantern_points(cx, cy, h, 0.0), smooth=True, fill=LANTERN_PAPER,
                          outline=LANTERN_FRAME, width=line)
    canvas.create_line(cx, cy - 0.45 * h, cx, cy + 0.45 * h, fill=LANTERN_SHADE, width=line)
    canvas.create_line(cx - 0.24 * h, cy + 0.42 * h, cx + 0.24 * h, cy + 0.42 * h,
                       fill=LANTERN_FRAME, width=max(2, 2 * line))
    canvas.create_oval(cx - 0.12 * h, cy + 0.13 * h, cx + 0.12 * h, cy + 0.47 * h,
                       fill=LANTERN_FLAME, outline="")


# --- The toast ----------------------------------------------------------------------------

class Toast:
    """One celebration card, placed in ``root``'s bottom-right corner (see the module doc).
    ``sky_over``: the canvas the lanterns fly over (the story map), or None for the small
    sky above the card; never used under Reduce motion."""

    def __init__(self, root: tk.Misc, celebration: Celebration, *, fonts: dict, scale: float,
                 motion: Motion, bottom: int, on_close: Callable[[], None],
                 sky_over: tk.Canvas | None = None) -> None:
        self.root, self.celebration, self.motion = root, celebration, motion
        self.on_close = on_close
        self.scale = scale
        px = self.px
        strong: tkfont.Font = fonts.get("bodyStrong") or fonts["body"]
        body: tkfont.Font = fonts.get("body") or strong
        small: tkfont.Font = fonts.get("small") or body
        head, rest = celebration.texts()
        left, gap, right = px(40), strong.measure(" "), px(32)
        natural = left + strong.measure(head) + gap + body.measure(rest) + right
        self.width = max(px(TOAST_MIN_W), min(px(TOAST_MAX_W), natural))
        self.height = px(TOAST_H)
        canvas = self.canvas = tk.Canvas(root, width=self.width, height=self.height,
                                         background=CARD, highlightthickness=0,
                                         borderwidth=0, takefocus=0, cursor="hand2")
        canvas.create_rectangle(0, 0, self.width - 1, self.height - 1, outline=CARD_BORDER)
        still_lantern(canvas, px(20), self.height / 2, px(20), scale)
        mid = self.height / 2
        self.head_item = canvas.create_text(left, mid, anchor="w", font=strong, text=head,
                                            fill=THEME["strongForeground"])
        room = self.width - left - strong.measure(head) - gap - right
        self.rest_item = canvas.create_text(left + strong.measure(head) + gap, mid,
                                            anchor="w", font=body, fill=THEME["foreground"],
                                            text=_fit(rest, room, body))
        self.close_item = canvas.create_text(self.width - px(12), mid, anchor="e",
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
        self._x, self._y = -px(TOAST_INSET), -(bottom + px(12))
        canvas.place(in_=root, relx=1.0, rely=1.0, anchor="se", x=self._x, y=self._y)
        canvas.tk.call("raise", canvas._w)          # Canvas.lift raises items, not the widget
        self.sky: tk.Canvas | None = None
        self.lanterns: Lanterns | None = None
        motion.tween(("toast", "slide"), FADE_MS, self._slide)
        if not motion.reduce():
            self._fly(sky_over)
        self._arm(TOAST_MS)

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def line(self) -> str:
        """The card's one line, as shown."""
        canvas = self.canvas
        return f"{canvas.itemcget(self.head_item, 'text')} " \
               f"{canvas.itemcget(self.rest_item, 'text')}"

    def _slide(self, p: float) -> None:
        if not self.closed:
            self.canvas.place_configure(y=self._y + round(self.px(SLIDE_PX) * (1.0 - p)))

    def _fly(self, over: tk.Canvas | None) -> None:
        """The lanterns: over the story map, or in a small sky just above the card."""
        if over is not None:
            surface = str(over.cget("background"))
            self.lanterns = Lanterns(over, self.motion, surface=surface, scale=self.scale)
            return
        px = self.px
        sky = self.sky = tk.Canvas(self.root, width=max(self.width, px(SKY_W)),
                                   height=px(SKY_H), background=SKY, highlightthickness=1,
                                   highlightbackground=CARD_BORDER, borderwidth=0,
                                   takefocus=0)
        sky.place(in_=self.root, relx=1.0, rely=1.0, anchor="se", x=self._x,
                  y=self._y - self.height - px(6))
        sky.tk.call("raise", sky._w)
        sky.update_idletasks()
        self.lanterns = Lanterns(sky, self.motion, surface=SKY, scale=self.scale,
                                 on_done=self._sky_gone)

    def _sky_gone(self) -> None:
        sky, self.sky = self.sky, None
        if sky is not None:
            try:
                sky.destroy()
            except tk.TclError:
                pass

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
        if self.lanterns is not None:
            self.lanterns.stop()
        self._sky_gone()
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
    one now; ``bottom()`` is the status bar's height; ``sky_over()`` the canvas the lanterns
    fly over (None: the small sky); ``on_shown(c)`` runs as each shows."""

    def __init__(self, root: tk.Misc, *, fonts: dict, scale: float, motion: Motion,
                 bottom: Callable[[], int], ready: Callable[[], bool],
                 on_shown: Callable[[Celebration], None],
                 sky_over: Callable[[], tk.Canvas | None] = lambda: None) -> None:
        self.root, self.fonts, self.scale, self.motion = root, fonts, scale, motion
        self.bottom, self.ready, self.on_shown = bottom, ready, on_shown
        self.sky_over = sky_over
        self.waiting: list[Celebration] = []
        self.toast: Toast | None = None
        self._timer: str | None = None
        self.stopped = False

    def add(self, celebrations: Iterable[Celebration]) -> None:
        for celebration in celebrations:
            if celebration.key == GUIDE:            # the Guide's line says it all
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
                           motion=self.motion, bottom=self.bottom(), on_close=self._closed,
                           sky_over=self.sky_over())
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


def counts_line(errors: int, warnings: int) -> str:
    """The status bar's counts, as ``checkwiring.counts_text`` writes them."""
    from engine.tools.editor.checkwiring import ERROR_GLYPH, WARNING_GLYPH
    return f"{ERROR_GLYPH} {errors}  {WARNING_GLYPH} {warnings}"


# --- The window's wiring ------------------------------------------------------------------

class CelebrationWiring:
    """``EditorWindow``'s milestones, toasts and motions (see the module doc)."""

    root: tk.Tk
    motion: Motion
    milestones: Milestones
    toasts: Toasts
    _counts: tuple[int, int] | None = None
    _unsubscribe: Callable[[], None] | None = None

    def _build_celebrations(self) -> None:
        """After the panes, the map, the Events list and the status bar exist."""
        win: Any = self
        self.motion = Motion(self.root, reduce=self._motion_reduced)
        win.story_map.motion = self.motion
        events = getattr(win, "events_view", None)
        if events is not None:
            events.motion = self.motion
        state = studiostate.read_state(win.paths.root)
        known = state if isinstance(state, studiostate.StudioState) else None
        self.milestones = Milestones(known.celebrated if known else (),
                                     sample=bool(known and known.sample))
        self.toasts = Toasts(self.root, fonts=win.fonts, scale=win.scale, motion=self.motion,
                             bottom=self._toast_bottom, ready=self._toast_ready,
                             on_shown=self._celebrated, sky_over=self._lantern_sky)
        self._counts = None
        self._tick = icons.photo(self.root, "success", max(10, round(12 * win.scale)),
                                 SUCCESS, gap=max(2, round(4 * win.scale)))
        win.on_check_done.append(self._celebration_check)
        subscribe = getattr(win, "on_game_event", None)     # the game's line reports
        self._unsubscribe = subscribe(self._game_event) if subscribe is not None else None

    def stop_celebrations(self) -> None:
        """The window closes."""
        if hasattr(self, "toasts"):
            if self._unsubscribe is not None:
                self._unsubscribe()
                self._unsubscribe = None
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

    def _lantern_sky(self) -> tk.Canvas | None:
        """The story map's canvas while it is showing (the lanterns fly over it)."""
        story_map = getattr(self, "story_map", None)
        canvas = getattr(story_map, "canvas", None)
        try:
            return canvas if canvas is not None and canvas.winfo_viewable() else None
        except tk.TclError:
            return None

    def _celebrated(self, celebration: Celebration) -> None:
        """A toast showed: remember every milestone marked so far for this game."""
        win: Any = self
        state = studiostate.read_state(win.paths.root)
        stored = state.celebrated if isinstance(state, studiostate.StudioState) else ()
        win.save_studio_state(celebrated=tuple(sorted(set(stored)
                                                      | self.milestones.celebrated)))

    # -- Moments ------------------------------------------------------------------------------

    def _celebration_check(self, result: Any) -> None:
        """After each applied check: the count ticks to its new value, a check that came
        back clean turns the chip green, then the check's milestones."""
        win: Any = self
        if win.closed:
            return
        from engine.tools.editor.checkwiring import check_counts
        counts, before = check_counts(result), self._counts
        self._counts = counts
        item = win.check_counts
        loaded = getattr(result, "loaded", False)
        if before is not None and counts != before:
            count_to(self.motion, "counts", before, counts,
                     lambda now: item.show_for_now(None if now is None else counts_line(*now)))
        if before is not None and loaded and sum(before) > 0 and sum(counts) == 0:
            bar = win.status_bar
            clean_chip(self.motion, "clean", item.label, image=self._tick, color=SUCCESS,
                       tint=blend(SUCCESS, bar.background, 0.16),
                       rest=(bar.foreground, bar.background))
        facts = getattr(win, "_guide_facts", None)
        if not loaded or facts is None:
            return
        self.toasts.add(self.milestones.after_check(facts, guide.all_done(win.guide_rows())))

    def _game_event(self, kind: str, data: dict) -> None:
        """A line report from the running game: the first ending reached is a milestone."""
        if kind != "ending" or getattr(self, "closed", False):
            return
        title = data.get("title") or data.get("id")
        if isinstance(title, str) and title.strip():
            self.toasts.add(self.milestones.reached(title))

    def guide_played(self) -> None:
        """A Play reached the game window for the first time (``runwiring``)."""
        win: Any = self
        super().guide_played()                  # type: ignore[misc]
        self.toasts.add(self.milestones.played(guide.all_done(win.guide_rows())))

    def build_finished(self) -> None:
        """A build ended well (``builddialog``)."""
        self.toasts.add(self.milestones.built())


__all__ = ["BUILD", "CHOICE", "Celebration", "CelebrationWiring", "ENDING", "GUIDE",
           "LANTERN_MS", "Lanterns", "MILESTONES", "Milestones", "PLAY", "TEXTS", "TOAST_MS",
           "Toast", "Toasts", "counts_line", "lantern_points"]
