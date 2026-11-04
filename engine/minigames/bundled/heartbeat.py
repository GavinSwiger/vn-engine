"""Heartbeat (F57): a bundled minigame where a ring closes toward a circle on a steady beat
and the player presses as it meets the circle, to keep their composure.

Every rule is in ``heartbeat_rules``; this module is the session (F57 SPEC §4–§6):

- ``start`` builds the plan from the checked arguments and the player's Timing assist
  (``ctx.settings.timed``, minigame API 1.3), and the ``Beats`` state machine.
- ``update(dt)`` (``dt`` clamped to 0.1 s) moves the game clock, plays ``sound`` on each beat
  (or each ring's arrival under No time limits), and judges windows that end with no press.
  The host doesn't call it while the game menu is open or the window is unfocused, so the
  clock pauses then.
- **Input.** Mouse button 1 in the content area, Enter, Space or gamepad A
  (``Nav.ACTIVATE``), key repeats ignored, judged at the game time of the frame it arrives
  in. Everything else passes on (Esc opens the game menu).
- **The end.** "6 of 8" shows for 1.5 s (a press ends it early); then, with ``meter``, one
  ``ctx.points.add(meter, −cost × misses)`` and ``ctx.finish(hits)``.
- **Settings.** ``settings_changed`` reads reduce motion and the text scale at once; a new
  Timing assist applies from the next beat (``Beats.set_plan``).
- **Look.** Every color is a token whose default is a theme token, so the six color schemes
  apply. Only the 128-unit circle's border changes on a hit or miss (no flash).

Presentation-only: nothing here is saved; a restore starts again from the lead-in (F23).
Imports (AC-F25-01's rule): ``heartbeat_rules``, ``engine.minigames.api``, and F10's public
widget kit only.
"""

from typing import TYPE_CHECKING

import pygame

from engine.minigames.api import Arg, Minigame, Outcome, PluginEvent, StoryNames
from engine.minigames.bundled import heartbeat_rules as rules
from engine.ui.focus import Box
from engine.ui.nav import Nav
from engine.ui.paint import FrameSpec, fit_label

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas

RGB = tuple[int, int, int]

# [theme.plugin.heartbeat] (§6): each default is a game theme token.
TOKENS = {
    "target.fill_color": "button.fill_color",
    "target.border_color": "button.border_color",
    "target.text_color": "button.text_color",
    "ring.line_color": "slider.fill_color",
    "hit_color": "button.focused.border_color",
    "miss_color": "button.disabled.text_color",
    "dot.empty_color": "button.border_color",
}

# [words.plugin.heartbeat] (§6).
WORDS = {
    "title": "Heartbeat",
    "hint": "Press when the ring meets the circle: click, Space, Enter, or A.",
    "hint_wait": "Press when the ring reaches the circle. Take your time.",
    "ready": "Ready…",
    "hit": "Steady",
    "miss": "Missed",
    "result": "{hits} of {beats}",
}

TEXT_WIDTH = 116                      # the circle's text fits inside its 128-unit fill
DASH_H = 4                            # a missed beat's dot is a dash
EMPTY_RING = 2                        # a beat to come is a ring this wide
_KEYS = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)


def _rgb(value: object) -> RGB | None:
    """A resolved color token: an RGB triple, or ``#RRGGBB``; else None."""
    if isinstance(value, (tuple, list)) and len(value) >= 3 \
            and all(type(c) is int and 0 <= c <= 255 for c in value[:3]):
        return int(value[0]), int(value[1]), int(value[2])
    if type(value) is str and len(value) in (7, 9) and value[0] == "#":
        try:
            return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
        except ValueError:
            return None
    return None


class Heartbeat(Minigame):
    name = "heartbeat"
    title = "Heartbeat"
    api = "1.3"
    over_stage = False
    args = {key: Arg(default=value) for key, value in rules.DEFAULTS.items()}
    # The static outcomes gate skippable (E271) and E279; outcome_for gives the real ones.
    test_outcome = Outcome(None)
    skipped_outcome = Outcome(None)
    tokens = TOKENS
    words = WORDS

    # -- API 1.1 hooks (fresh, never-started instances) --

    def check_args(self, args: dict) -> str | None:
        return rules.problem(args)

    def check_story(self, args: dict, story: StoryNames) -> str | None:
        return rules.story_problem(args, story)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        return rules.fixed_outcome(args)

    # -- the session --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        self.args = dict(ctx.args)
        settings = ctx.settings
        self.plan = rules.make_plan(self.args, settings.timed)
        self.beats = rules.Beats(self.args["beats"], self.plan)
        self.t = 0.0
        self.reduce = bool(settings.reduce_motion)
        self.scale = float(settings.text_scale)
        self.result_left: float | None = None      # set once every beat is judged
        self.finished = False
        self.held: set[int] = set()                # keys down (a repeat is a held key)
        self.border: tuple[str, float] | None = None   # ("hit" | "miss", seconds left)
        self.word: tuple[str, float] | None = None
        self.area = ctx.area
        self.lay: rules.Layout | None = None
        self.colors = {key: self._color(key) for key in TOKENS}
        self.word_text = {key: ctx.words.mine(key) for key in WORDS if key != "title"}
        ctx.heading(True)
        self._hint()

    def _color(self, key: str) -> RGB:
        found = _rgb(self.ctx.theme.mine(key))
        if found is not None:
            return found
        fallback = _rgb(self.ctx.theme.get(TOKENS[key]))
        return fallback if fallback is not None else (0, 0, 0)

    def _hint(self) -> None:
        self.ctx.hint(self.word_text["hint_wait" if self.plan.wait else "hint"])

    # -- input --

    def handle_event(self, ev: PluginEvent) -> bool:
        raw = ev.ui.raw
        kind = raw.type
        if kind == pygame.KEYUP:
            self.held.discard(getattr(raw, "key", -1))
            return False
        pressed = False
        if kind == pygame.KEYDOWN:
            key = getattr(raw, "key", -1)
            if getattr(raw, "repeat", False) or key in self.held:
                return key in _KEYS                       # a repeat does nothing
            self.held.add(key)
            pressed = ev.nav is Nav.ACTIVATE or key in _KEYS
        elif kind == pygame.MOUSEBUTTONDOWN:
            pos = ev.ui.canvas_pos
            pressed = (getattr(raw, "button", 0) == 1 and ev.ui.in_canvas and pos is not None
                       and Box(*self._area()).contains(pos))
        elif ev.nav is Nav.ACTIVATE:
            pressed = True                                # gamepad A
        if not pressed:
            return False
        self._press()
        return True

    def _area(self) -> tuple[float, float, float, float]:
        a = self.area
        return (a.x, a.y, a.w, a.h)

    def _press(self) -> None:
        if self.finished:
            return
        if self.result_left is not None:
            self._finish()                                # any press ends the result early
            return
        found = self.beats.press(self.t)
        if found is not None:
            self._feedback(found[0])
            self._check_done()

    def _feedback(self, kind: str) -> None:
        self.border = (kind, rules.BORDER_S)
        self.word = (kind, rules.WORD_S)

    # -- the clock --

    def update(self, dt: float) -> None:
        if self.finished:
            return
        dt = min(max(0.0, float(dt)), rules.DT_MAX)
        self.t += dt
        if self.border is not None:
            left = self.border[1] - dt
            self.border = (self.border[0], left) if left > rules.EPSILON else None
        if self.word is not None:
            left = self.word[1] - dt
            self.word = (self.word[0], left) if left > rules.EPSILON else None
        showing = self.result_left is not None
        for kind, _k in self.beats.advance(self.t):    # after the end: a late beat's sound
            if kind == "beat":
                sound = self.args.get("sound")
                if sound:
                    self.ctx.play_sound(sound)
            else:
                self._feedback(kind)
        if showing:
            self.result_left -= dt
            if self.result_left <= rules.EPSILON:
                self._finish()
            return
        self._check_done()

    def _check_done(self) -> None:
        if self.beats.done and self.result_left is None:
            self.result_left = rules.RESULT_S

    def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        meter, cost = self.args.get("meter"), self.args.get("cost", 1)
        misses = self.beats.misses
        if meter is not None and cost and misses:
            self.ctx.points.add(meter, -cost * misses)
        self.ctx.finish(self.beats.hits)

    # -- settings and layout --

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.reduce = bool(s.reduce_motion)
        self.scale = float(s.text_scale)
        plan = rules.make_plan(self.args, s.timed)
        if plan != self.plan:
            self.plan = plan
            self.beats.set_plan(plan, self.t)
            self._hint()

    def layout(self, area) -> None:
        self.area = area
        self.lay = None

    # -- drawing --

    def ring_size(self) -> float:
        """The ring's diameter now (``heartbeat_rules.ring_size``)."""
        lay = self._layout()
        return rules.ring_size(self.t, self.beats.current, reduce=self.reduce, top=lay.top)

    def _layout(self) -> rules.Layout:
        if self.lay is None:
            self.lay = rules.layout(self._area(), self.args["beats"])
        return self.lay

    def circle_text(self) -> str:
        """What the circle says now: the result, a hit or miss word, or "Ready…"."""
        if self.result_left is not None or self.finished:
            return self.word_text["result"].replace("{hits}", str(self.beats.hits)).replace(
                "{beats}", str(self.args["beats"]))
        if self.word is not None:
            return self.word_text[self.word[0]]
        if not self.beats.marks and self.t < self.beats.scheduled[0].start - rules.EPSILON:
            return self.word_text["ready"]
        return ""

    def draw(self, canvas: "Canvas") -> None:
        lay = self._layout()
        painter = self.ctx.painter
        colors = self.colors
        cx, cy = lay.center
        if self.result_left is None and not self.finished:
            size = rules.drawn_size(self.ring_size())
            if size > rules.TARGET:
                painter.ellipse(Box(cx - size / 2, cy - size / 2, size, size),
                                colors["ring.line_color"], ring=rules.RING_LINE)
        border, width = colors["target.border_color"], rules.TARGET_BORDER
        if self.border is not None:
            border = colors["hit_color" if self.border[0] == "hit" else "miss_color"]
            width = rules.FEEDBACK_BORDER
        half = rules.TARGET / 2
        painter.shape(Box(cx - half, cy - half, rules.TARGET, rules.TARGET),
                      FrameSpec(colors["target.fill_color"], 1.0, border, width, int(half)))
        text = self.circle_text()
        if text:
            self._draw_text(canvas, text, (cx, cy))
        self._draw_dots(lay)

    def _draw_text(self, canvas: "Canvas", text: str, at: tuple[float, float]) -> None:
        px = rules.text_px(self.scale)

        def font_at(size: int):
            return canvas.font_handle(self.ctx.font(None, size), size).font

        fit = fit_label(text, font_at, px, TEXT_WIDTH, min_size=min(rules.TEXT_MIN, px))
        if fit.text:
            canvas.draw_text(fit.text, self.ctx.font(None, fit.size),
                             self.colors["target.text_color"], at, anchor="center")

    def _draw_dots(self, lay: rules.Layout) -> None:
        painter = self.ctx.painter
        colors = self.colors
        painter.panel(Box(*lay.strip))
        marks = self.beats.marks
        d = rules.DOT
        for i, (x, y) in enumerate(lay.dots):
            if i < len(marks) and marks[i]:
                painter.ellipse(Box(x - d / 2, y - d / 2, d, d), colors["hit_color"])
            elif i < len(marks):
                painter.rect(Box(x - d / 2, y - DASH_H / 2, d, DASH_H), colors["miss_color"])
            else:
                painter.ellipse(Box(x - d / 2, y - d / 2, d, d), colors["dot.empty_color"],
                                ring=EMPTY_RING)


__all__ = ["Heartbeat", "TOKENS", "WORDS"]
