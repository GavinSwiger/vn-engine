"""Stay still (F53): a bundled minigame where a character tells the player not to touch
anything for some seconds. The result is the number of flinches (with ``strict``, 1 at the
first flinch).

Every rule is in ``still_rules``; this module is the session (F53 ``01`` §4.2, ``04`` §3.3):

- ``start`` shows the line (and the speaker's name), the countdown and the bar; with
  ``ready`` an "I'm ready" button (focused by keys) starts a 0.5 s grace, without it the
  grace is 1.0 s from the start. No heading.
- ``handle_event`` maps each input to a ``still_rules.Touch`` and asks the ``Watch``: every
  verdict but PASS is consumed (so a press posts F23's "used"), and a flinch shows the flinch
  line for 2 s and plays ``flinch_sound``. Right click and gamepad B pass on, so they open
  the game menu; Esc, Start, F5 and F9 never reach the game.
- ``update(dt)`` is the only clock. F23 calls it only while the game is on top and the window
  has focus, so time waits under the game menu or while the window is away. At 0 s, or at the
  first flinch with ``strict``, ``ctx.finish``.
- **Look.** Colors from ``panel.*`` and ``slider.*`` only; the bar drains every frame, or
  steps once a second under Reduce motion. The countdown falls from 96 to 64 and the line
  steps down by 2 (not below 24) to fit; a line still too long ends in "…" after 3 lines.

The game never reads the user name, the window title, the cursor or any file (PR-F30-10,
PR-F30-14); the story does that around it. Presentation-only: a restore starts it again.
"""

import dataclasses
from typing import TYPE_CHECKING, Any, Final

import pygame

from engine.minigames.api import Arg, Minigame, Outcome, PluginEvent
from engine.minigames.bundled import still_rules as rules
from engine.minigames.bundled.still_rules import Touch
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, pitch, scaled
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter

OWN: Final = "plugin.stay_still."

# [theme.plugin.stay_still] (01 §4.4).
TOKENS = {
    "line.text_size": rules.LINE_TEXT[0],
    "flinch_sound": "",
}

# [words.plugin.stay_still] (01 §4.5).
WORDS = {
    "title": "Stay Still",
    "hint_ready": "Press I'm ready, then don't touch anything.",
    "hint": "Don't press anything until the time is up.",
    "ready": "I'm ready",
    "line": "Don't touch anything.",
    "flinch_line": "Don't move.",
}

MODIFIERS: Final = frozenset({
    pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_LALT,
    pygame.K_RALT, pygame.K_LGUI, pygame.K_RGUI, pygame.K_LMETA, pygame.K_RMETA,
    pygame.K_MODE})


def touch_of(ev: PluginEvent) -> Touch:
    """An input as Stay still sees it (``still_rules.Touch``)."""
    raw = ev.ui.raw
    kind = raw.type
    if kind == pygame.KEYDOWN:
        key = int(getattr(raw, "key", -1))
        return Touch("key_down", key, modifier=key in MODIFIERS)
    if kind == pygame.KEYUP:
        return Touch("key_up", int(getattr(raw, "key", -1)))
    if kind == pygame.MOUSEBUTTONDOWN:
        return Touch("button", int(getattr(raw, "button", 0)))
    if kind == pygame.MOUSEWHEEL:
        return Touch("wheel")
    if kind == pygame.CONTROLLERBUTTONDOWN:
        button = int(getattr(raw, "button", -1))
        return Touch("pad", button, east=button == pygame.CONTROLLER_BUTTON_B)
    if kind == pygame.CONTROLLERAXISMOTION and ev.nav is not None:
        return Touch("stick")
    if kind == pygame.MOUSEMOTION:
        return Touch("motion", pos=ev.ui.canvas_pos if ev.ui.in_canvas else None)
    if kind == pygame.WINDOWLEAVE:
        return Touch("motion", pos=None)
    if kind == pygame.WINDOWFOCUSLOST:
        return Touch("focus_lost")
    if kind == pygame.WINDOWFOCUSGAINED:
        return Touch("focus_gained")
    return Touch("other")


class StayStill(Minigame):
    name = "stay_still"
    title = "Stay Still"
    api = "1.1"
    over_stage = True
    args = {key: Arg(default=value) for key, value in rules.DEFAULTS.items()}
    test_outcome = Outcome(0)
    skipped_outcome = Outcome(0)
    tokens = TOKENS
    words = WORDS

    def check_args(self, args: dict) -> str | None:
        return rules.problem(args)

    # -- the session --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        spec = self.spec = rules.parse(dict(ctx.args))
        word = ctx.words.mine
        self.line = spec.line if spec.line is not None else word("line")
        self.flinch_line = spec.flinch_line if spec.flinch_line is not None \
            else word("flinch_line")
        self.hints = {"hint_ready": word("hint_ready"), "hint": word("hint")}
        self.watch = rules.Watch(spec)
        self.done = False
        mine = ctx.theme.mine
        self.line_size = rules.clamp_size(mine("line.text_size"), *rules.LINE_TEXT)
        self.flinch_sound = mine("flinch_sound")
        self.reduce = bool(ctx.settings.reduce_motion)
        self.area = ctx.area
        self.lay: Any = None
        self._lay_key: tuple | None = None
        self.ready_button = Button(lambda: word("ready"), self._ready)
        ctx.heading(False)
        if spec.ready:
            ctx.scope.set_groups([FocusGroup([self.ready_button])])
            ctx.scope.set_default(self.ready_button)
            ctx.hint(self.hints["hint_ready"])
        else:
            ctx.hint(self.hints["hint"])

    def _ready(self) -> None:
        if self.watch.state != rules.READY:
            return
        self.watch.begin()
        self.ctx.scope.set_groups([])
        self.ctx.hint(self.hints["hint"])
        self._lay_key = None

    # -- input and the clock --

    def handle_event(self, ev: PluginEvent) -> bool:
        if self.done:
            return False
        verdict = self.watch.touch(touch_of(ev))
        if verdict == rules.COUNT:
            if type(self.flinch_sound) is str and self.flinch_sound:
                self.ctx.play_ui(OWN + "flinch_sound")
            self._check_done()
        return verdict != rules.PASS

    def update(self, dt: float) -> None:
        if self.done:
            return
        self.watch.advance(dt)
        self._check_done()

    def _check_done(self) -> None:
        if self.watch.done and not self.done:
            self.done = True
            self.ctx.finish(self.watch.result)

    # -- what shows --

    def shown_line(self) -> str:
        """The flinch line for 2 s after a flinch, else the line."""
        return self.flinch_line if self.watch.flinch_left > rules.EPSILON else self.line

    def countdown(self) -> int:
        return rules.countdown(self.watch.remaining)

    def bar(self) -> float:
        return rules.bar_fraction(self.watch.remaining, self.spec.seconds, reduce=self.reduce)

    # -- settings and layout --

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.reduce = bool(s.reduce_motion)
        self._lay_key = None

    def layout(self, area) -> None:
        self.area = area
        self._lay_key = None

    def settle(self, canvas: "Canvas") -> Any:
        """The layout and the fitted sizes (recomputed only when something changed)."""
        p = self.ctx.painter
        scale = p.text_scale()
        a = self.area
        key = (a.x, a.y, a.w, a.h, scale, self.watch.state == rules.READY)
        if key == self._lay_key and self.lay is not None:
            return self.lay
        heading = p.style("panel.heading").font
        panel = p.style("panel").font
        name_px = p.scaled_size(heading.size)
        width = rules.SPEECH_W - 2 * rules.PAD
        line_px = scaled(self.line_size, scale)
        fonts = {self.line: line_px, self.flinch_line: line_px}

        def lines_at(text: str, px: int) -> int:
            font = dataclasses.replace(panel, size=px)
            return len(canvas.layout_lines(text, font, width, None))

        sizes = {}
        for text in (self.line, self.flinch_line):
            px = fonts[text]
            while lines_at(text, px) > rules.LINES_MAX and px - 2 >= rules.LINE_MIN:
                px -= 2
            sizes[text] = px
        rows = max(min(rules.LINES_MAX, lines_at(t, s)) * pitch(s) for t, s in sizes.items())
        name_h = pitch(name_px) if self.spec.speaker is not None else 0
        speech_h = 2 * rules.PAD + name_h + rows
        bh = button_height(scale=scale)
        ready = self.watch.state == rules.READY
        for count in rules.COUNT_TEXT:
            count_px = scaled(count, scale)
            count_h = max(rules.COUNT_PANEL[1], pitch(count_px) + 16)
            lay = rules.still_layout((a.x, a.y, a.w, a.h), speech_h=speech_h, count_h=count_h,
                                     button_h=bh, ready=ready)
            bottom = lay.ready[1] + lay.ready[3] if ready else lay.bar[1] + lay.bar[3]
            if bottom <= a.y + a.h:
                break
        self.ready_button.box = Box(*lay.ready)
        self.lay = lay
        self.fit = {"name_px": name_px, "name_h": name_h, "sizes": sizes, "count_px": count_px}
        self._lay_key = key
        return lay

    def draw(self, canvas: "Canvas") -> None:
        lay = self.settle(canvas)
        p = self.ctx.painter
        fit = self.fit
        speech = Box(*lay.speech)
        p.panel(speech)
        x, y = speech.x + rules.PAD, speech.y + rules.PAD
        heading = p.style("panel.heading")
        panel = p.style("panel")
        if self.spec.speaker is not None:
            canvas.draw_text(self.spec.speaker,
                             dataclasses.replace(heading.font, size=fit["name_px"]),
                             heading.text_color, (x, y), max_width=speech.w - 2 * rules.PAD,
                             max_lines=1)
            y += fit["name_h"]
        text = self.shown_line()
        px = fit["sizes"][text]
        canvas.draw_text(text, dataclasses.replace(panel.font, size=px), panel.text_color,
                         (x, y), max_width=speech.w - 2 * rules.PAD,
                         max_lines=rules.LINES_MAX)
        count = Box(*lay.count)
        p.panel(count)
        canvas.draw_text(str(self.countdown()),
                         dataclasses.replace(heading.font, size=fit["count_px"]),
                         heading.text_color, count.center, anchor="center")
        self._draw_bar(p, Box(*lay.bar))

    def _draw_bar(self, p: "Painter", box: Box) -> None:
        slider = p.style("slider")
        p.rect(box, slider.color("track", slider.text_color))
        filled = round(box.w * self.bar())
        if filled > 0:
            p.rect(Box(box.x, box.y, filled, box.h), slider.color("fill", slider.marker_color))


__all__ = ["MODIFIERS", "StayStill", "TOKENS", "WORDS", "touch_of"]
