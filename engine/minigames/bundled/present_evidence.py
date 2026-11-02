"""Present evidence (F25): a bundled cross-examination. A witness's testimony shows one
statement at a time; the player presses the witness or presents an item from F21's
``CodexView``, and a wrong present lowers an F22 meter.

Step F25-1 built the declarations and the three API 1.1 hooks; every rule they use is in
``present_rules``. Step F25-3 adds the playable session (F25 ``04`` §6):

- **Testimony mode.** ``start`` parses the checked arguments and puts the buttons
  (‹ Previous, Press, Present, Next ›; absent ones close up) in one ``FocusGroup`` in
  ``ctx.scope``, with Press (or Present) as the default, so F23's host gives first focus
  by the input that reached the minigame. Previous, Next, Page Up/Down, and the shoulders
  step the statements, wrapping; Press finishes at once.
- **Picker mode.** Present opens ``ctx.codex_view`` (items only, ``evidence``'s categories,
  the pick word ``present``) in a backing panel, with a Back button; the view's groups and
  Back replace the buttons in the scope, and the host draws and routes them (F23 A4). The
  codex widgets call the view's own routes from their ``on_nav``, so the session handles
  only Back (the input) itself. Back (the button or the input) returns to the statement.
- **Judging.** A pick is judged (``present_rules.judge``). A wrong pick with ``penalty``
  and ``cost > 0`` requests ``ctx.points.add(penalty, -cost)`` once and shows the bar's
  loss: the lost span hatched for 500 ms, then shrinking over 300 ms (``ease_in_out``) and a
  200 ms hold; under reduced motion (read every frame) the hatch shows for 500 ms, then the
  bar cuts and holds 500 ms. The run finishes at 1 s (``t ≥ 1 − EPSILON``); the frame of
  the pick shows ``t = 0``. During the loss every offered input is consumed, so only F23's
  global keys act. When nothing visible is lost (the meter at 0, or above ``penalty_max``),
  the span is ``[v1, min(v1 + cost, penalty_max)]`` (F25 ``07`` G7/I-6).
- **Drawing.** Lazy, as F24: ``layout``, ``settings_changed``, and statement or mode
  changes only set flags; ``draw`` lays out (``present_rules`` geometry from F10 pitches)
  and fits the statement (``fit_message``) once per change. The host draws the scope's
  widgets after ``draw``; the opening picture is drawn before first focus, so it shows no
  marker.
- **Sounds** (F25-4, Could): ``press_sound`` on Press, ``present_sound`` on a pick, through
  ``ctx.play_ui``; both none by default.
- **Warm-up.** The first draw (F23's untimed opening picture) also builds the picker's
  backing and detail-panel frames, clipped to nothing, so the frame that opens the picker
  stays under W162.
- **W173** (dev): at ``start``, once per distinct text per process (``_WARNED``, at most
  100), on ``ctx.log`` with the coded-record form.

Presentation-only: nothing here is saved; a restore restarts at ``at`` with the accepted
meter. A pending penalty is dropped with an abandoned or skipped run (F23's ledger, G2).

Imports (AC-F25-01): ``present_rules``, ``rule_text``, ``engine.minigames.api``, and F10's
public widget kit only (``ui.focus``, ``ui.widgets``, ``ui.paint``, ``ui.nav``,
``ui.layouts``).
"""

import dataclasses
from math import floor
from typing import TYPE_CHECKING, Final

from engine.minigames.api import (
    Arg,
    CodexFilter,
    Minigame,
    Outcome,
    PickAction,
    PluginEvent,
    StoryNames,
)
from engine.minigames.bundled import present_rules
from engine.minigames.bundled.present_rules import EPSILON, LOSS_HATCH_S, LOSS_S, LOSS_SHRINK_S
from engine.minigames.bundled.rule_text import cut
from engine.ui.layouts import (
    MessageFit,
    button_height,
    codex_layout,
    fit_message,
    pitch,
    scaled,
)
from engine.ui.focus import Box, FocusGroup
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import fit_label
from engine.ui.widgets import Button

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas

# [theme.plugin.present_evidence.<element>] (F25 04 §12; text_size is clamped to 24–40 in
# start). press_sound and present_sound (Could, F25-4): none by default; ctx.play_ui plays
# one on Press and the other on a pick, right or wrong, besides the button's own sound.
TOKENS = {
    "statement.text_size": 28,
    "statement.text_color": "#1E6B34",
    "speaker.text_color": "panel.heading.text_color",
    "bar.fill_color": "#A02860",
    "bar.track_color": "#F0D0DE",
    "bar.loss_color": "#C62828",
    "press_sound": "",
    "present_sound": "",
}

# [words.plugin.present_evidence] (F25 01 §6.5).
WORDS = {
    "title": "Cross-Examination",
    "hint": "Press the witness, or present evidence.",
    "hint_no_press": "Present evidence that contradicts the statement.",
    "hint_picker": "Present evidence against: “{statement}”",
    "previous": "‹ Previous",
    "next": "Next ›",
    "press": "Press",
    "present": "Present",
    "back": "Back",
    "bar_label": "Credibility",
}

STATEMENT_SIZE_RANGE: Final = (24, 40)
STATEMENT_MIN_SIZE, STATEMENT_STEP, STATEMENT_LINES = 24, 2, 3
LABEL_SIZE: Final = 24             # the bar label and its number (01 §6.1: 98-unit panel)
SPEAKER_MAX_W: Final = 600
BAR_BORDER: Final = 2
_PICKER_TOKEN: Final = "{statement}"
OWN: Final = "plugin.present_evidence."    # ctx.theme / ctx.play_ui's prefix for TOKENS
_WARNED: set[str] = set()          # W173 texts logged in this process (≤ 100)
WARNED_MAX: Final = 100

RGB = tuple[int, int, int]


def _rgb(value: object, default: RGB) -> RGB:
    """A color token: an RGB triple (typed config) or ``#RRGGBB``; else ``default``."""
    if isinstance(value, (tuple, list)) and len(value) >= 3             and all(type(c) is int and 0 <= c <= 255 for c in value[:3]):
        return int(value[0]), int(value[1]), int(value[2])
    if type(value) is str and len(value) in (7, 9) and value[0] == "#":
        try:
            return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
        except ValueError:
            pass
    return default


def _hex(text: str) -> RGB:
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)


def _size(value: object, lo: int, hi: int, default: int) -> int:
    return min(max(value, lo), hi) if type(value) is int else default


@dataclasses.dataclass(slots=True)
class Loss:
    """The bar's loss display (04 §6.4): values clamped to 0–``penalty_max``."""
    v0: int
    v1: int
    lo: int                        # the hatched span, in meter units
    hi: int
    result: dict
    t: float = 0.0
    fresh: bool = True             # the pick's own frame shows t = 0


class PresentEvidence(Minigame):
    name = "present_evidence"
    title = "Cross-Examination"
    api = "1.1"
    over_stage = True
    args = {"testimony": Arg(), "answer": Arg(),
            **{key: Arg(default=value) for key, value in present_rules.DEFAULTS.items()}}
    # The static outcomes gate skippable (E271) and E279; outcome_for gives the real ones.
    test_outcome = Outcome(None)
    skipped_outcome = Outcome(None)
    tokens = TOKENS
    words = WORDS

    # -- API 1.1 hooks (fresh, never-started instances) --

    def check_args(self, args: dict) -> str | None:
        return present_rules.problem(args)

    def check_story(self, args: dict, story: StoryNames) -> str | None:
        return present_rules.story_problem(args, story)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        if kind not in ("test", "skipped"):
            raise ValueError(f"unknown outcome kind {kind!r}")
        return present_rules.fixed_outcome(present_rules.parse(args))

    # -- the session (04 §6.1) --

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        t = self.t = present_rules.parse(ctx.args)
        self.stmt = t.start
        self.mode = "testimony"
        self.done = False
        self.loss: Loss | None = None
        self.last_kind = InputKind.MOUSE
        mine = ctx.words.mine
        self.word = {key: mine(key) for key in WORDS if key != "title"}
        many = len(t.keys) >= 2
        self.previous = Button(lambda: self.word["previous"], self._previous) if many else None
        self.press = Button(lambda: self.word["press"], self._press) if t.press else None
        self.present = Button(lambda: self.word["present"], self._open)
        self.next = Button(lambda: self.word["next"], self._next) if many else None
        self.buttons = [b for b in (self.previous, self.press, self.present, self.next)
                        if b is not None]
        self.back = Button(lambda: self.word["back"], self._close)
        self.view = None
        self._set_testimony_groups()
        ctx.heading(False)
        ctx.hint(self._testimony_hint())
        self._read_tokens()
        settings = ctx.settings
        self.scale = float(settings.text_scale)
        self.reduce = bool(settings.reduce_motion)
        self.area = ctx.area
        self.tlay: present_rules.TestimonyLayout | None = None
        self.play: present_rules.PickerLayout | None = None
        self.t_dirty = True             # the testimony layout
        self.p_dirty = True             # the picker layout (and the view's build)
        self.fit_dirty = True           # the statement and speaker fits
        self.fit: MessageFit | None = None
        self.speaker_fit = None
        self.fits_made = 0              # statement fits so far (AC-F25-17, 23)
        self.builds = 0                 # view.build calls (AC-F25-17)
        self._hatch: tuple | None = None    # ((span, scale), blocks, device rects)
        self._drawn: dict = {}              # boxes, font specs, and text calls (by _settle)
        self.hatch_drawn: tuple = ()        # the hatch blocks of the last draw (canvas units)
        self.warmed = False                 # the picker's large frames are built (_warm)
        if ctx.dev:
            self._w173()

    def _read_tokens(self) -> None:
        mine = self.ctx.theme.mine
        painter = self.ctx.painter
        panel, heading = painter.style("panel"), painter.style("panel.heading")
        self.statement_size = _size(mine("statement.text_size"), *STATEMENT_SIZE_RANGE,
                                    TOKENS["statement.text_size"])
        self.colors = {key: _rgb(mine(key), _hex(TOKENS[key])) for key in
                       ("statement.text_color", "bar.fill_color", "bar.track_color",
                        "bar.loss_color")}
        self.colors["speaker.text_color"] = _rgb(mine("speaker.text_color"),
                                                 heading.text_color)
        self.panel_spec = panel.font
        self.heading_spec = heading.font
        self.text_color = panel.text_color
        self.border_color = panel.frame.border_color if panel.frame is not None             and panel.frame.border_color is not None else panel.text_color

    def _w173(self) -> None:
        ctx = self.ctx
        text = present_rules.w173_text(self.t, ctx.codex.items(), ctx.story)
        if text is None or text in _WARNED or len(_WARNED) >= WARNED_MAX:
            return
        _WARNED.add(text)
        ctx.log.warning("%s", text, extra={"code": "W173"})

    # -- modes and buttons (04 §6.2, §6.3) --

    def _testimony_hint(self) -> str:
        return self.word["hint" if self.t.press else "hint_no_press"]

    def _default_button(self) -> Button:
        return self.press if self.press is not None else self.present

    def _set_testimony_groups(self) -> None:
        scope = self.ctx.scope
        scope.set_groups([FocusGroup(list(self.buttons))])
        scope.set_default(self._default_button())

    def _step(self, by: int) -> None:
        if self.loss is not None or self.done:
            return
        self.stmt = (self.stmt + by) % len(self.t.keys)
        self.fit_dirty = True

    def _previous(self) -> None:
        self._step(-1)

    def _next(self) -> None:
        self._step(1)

    def _press(self) -> None:
        if self.loss is None and not self.done:
            self.ctx.play_ui(f"{OWN}press_sound")
            self._finish(present_rules.result_of(self.t, self.stmt, None))

    def _open(self) -> None:
        """Present: the picker (04 §6.3)."""
        if self.loss is not None or self.done or self.mode == "picker":
            return
        ctx = self.ctx
        if self.view is None:
            t = self.t
            self.view = ctx.codex_view(
                filter=CodexFilter(kinds=frozenset({"item"}),
                                   categories=None if t.evidence is None
                                   else frozenset(t.evidence)),
                pick=PickAction(self.word["present"], self._picked))
        self.mode = "picker"
        ctx.hint(self.word["hint_picker"].replace(_PICKER_TOKEN,
                                                  cut(self.t.texts[self.stmt])))
        self._build_picker(opening=True)

    def _build_picker(self, *, opening: bool = False) -> None:
        """Lay the picker out in the current area, build the view, and set the groups. On
        opening (and on a relayout by keys) focus goes to the view's default widget by keys,
        or nowhere by mouse; a relayout by mouse keeps whatever the pointer focused."""
        ctx = self.ctx
        button_h = button_height(scale=self.scale)
        lay = self.play = present_rules.picker_layout(self.area, button_h=button_h)
        self.p_dirty = False
        self.back.box = Box(*lay.back)
        groups = self.view.build(Box(*lay.view), self.scale)
        self.builds += 1
        scope = ctx.scope
        listed = self.view.default_widget()
        # Back joins the entry list's group, so Left from any row and Down from the last
        # row reach it before F10's move looks at the tab row above-left (04 §6.3; at 100%
        # the tab row's centre is left of the list's, so a plain move picked it).
        joined = [FocusGroup([*group.widgets, self.back], column=group.column)
                  if listed is not None and listed in group.widgets else group
                  for group in groups]
        if listed is None:
            joined.append(FocusGroup([self.back]))
        scope.set_groups(joined)
        target = listed or self.back
        scope.set_default(target)
        if self.last_kind is InputKind.KEYS:
            scope.focus(target, InputKind.KEYS, sound=False)
        elif opening:
            scope.clear()

    def _close(self) -> None:
        """Back: testimony mode on the same statement; nothing in the story changes."""
        if self.mode != "picker":
            return
        self.mode = "testimony"
        self._set_testimony_groups()
        scope = self.ctx.scope
        if self.last_kind is InputKind.KEYS and self.loss is None:
            scope.focus(self.present, InputKind.KEYS, sound=False)
        elif self.loss is None:
            scope.clear()
        self.ctx.hint(self._testimony_hint())

    def _picked(self, name: str) -> None:
        """``on_pick``, inside the ``_call`` that delivered the input."""
        if self.done or self.loss is not None:
            return
        self.ctx.play_ui(f"{OWN}present_sound")
        t = self.t
        result = present_rules.result_of(t, self.stmt, name)
        if result["correct"] or t.penalty is None or t.cost <= 0:
            self._finish(result)
            return
        points = self.ctx.points
        v0 = self._clamp(points.get(t.penalty))
        points.add(t.penalty, -t.cost)           # the session's only ledger request
        v1 = self._clamp(points.get(t.penalty))
        lo, hi = (v1, v0) if v0 != v1 else (v1, min(v1 + t.cost, t.penalty_max))
        self.loss = Loss(v0, v1, lo, hi, result)
        self._close()

    def _clamp(self, value: object) -> int:
        top = self.t.penalty_max
        return min(max(value, 0), top) if type(value) is int else 0

    def _finish(self, result: dict) -> None:
        assert not self.done, "a present_evidence run finished twice"
        self.done = True
        self.ctx.finish(result)

    # -- input (04 §6.5) --

    def handle_event(self, ev: PluginEvent) -> bool:
        ui = ev.ui
        self.last_kind = InputKind.MOUSE if ui.canvas_pos is not None else InputKind.KEYS
        if self.loss is not None or self.done:
            return True                          # only F23's global keys act
        nav = ev.nav
        if self.mode == "picker":
            if nav is Nav.BACK:
                self._close()
                return True
            return False                         # the codex widgets route themselves
        if nav in (Nav.PAGE_UP, Nav.PAGE_DOWN) and len(self.t.keys) >= 2:
            self._step(-1 if nav is Nav.PAGE_UP else 1)
            return True
        return False

    def update(self, dt: float) -> None:
        if self.mode == "picker" and self.view is not None:
            # The view's update lists ledger changes. This run changes no item, so the
            # shown widgets don't change while the picker is open; if they ever do, the
            # view's read-only ``groups_changed`` (through ``bind``) asks for a rebuild,
            # which the next draw makes (F23's host doesn't rebuild a plugin's groups).
            self.view.update(dt)
            if self.view.groups_changed:
                self.p_dirty = True
        loss = self.loss
        if loss is None or self.done:
            return
        if loss.fresh:
            loss.fresh = False
        else:
            loss.t += dt
        if loss.t >= LOSS_S - EPSILON:
            self._finish(loss.result)

    def layout(self, area) -> None:
        self.area = area
        self.t_dirty = self.p_dirty = self.fit_dirty = True

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.reduce = bool(s.reduce_motion)
        scale = float(s.text_scale)
        if scale != self.scale:
            self.scale = scale
            self.t_dirty = self.p_dirty = self.fit_dirty = True

    # -- the loss timeline (04 §6.4) --

    def loss_view(self) -> tuple[tuple[float, float] | None, int]:
        """The hatched span (meter units) or None, and the number shown."""
        loss = self.loss
        if loss is None:
            return None, self._value()
        t = loss.t
        span = (loss.lo, loss.hi) if loss.hi > loss.lo else None
        if t < LOSS_HATCH_S:
            return span, loss.v0
        if self.reduce or span is None:
            return None, loss.v1
        k = (t - LOSS_HATCH_S) / LOSS_SHRINK_S
        if k >= 1.0:
            return None, loss.v1
        right = loss.hi + (loss.lo - loss.hi) * present_rules.ease_in_out(k)
        return ((loss.lo, right) if right > loss.lo else None), loss.v1

    def _value(self) -> int:
        penalty = self.t.penalty
        return self._clamp(self.ctx.points.get(penalty)) if penalty is not None else 0

    # -- layout and drawing (04 §6.6) --

    def _font_at(self, canvas: "Canvas", spec):
        return lambda size: canvas.font_handle(spec, size).font

    def _settle(self, canvas: "Canvas") -> None:
        if self.mode == "picker":
            if self.p_dirty:
                self._build_picker()
            return
        scale = self.scale
        if self.t_dirty:
            self.t_dirty = False
            self.fit_dirty = True
            lay = self.tlay = present_rules.testimony_layout(
                self.area,
                label_pitch=pitch(scaled(LABEL_SIZE, scale)),
                name_pitch=pitch(scaled(self.heading_spec.size, scale)),
                statement_pitch=pitch(scaled(self.statement_size, scale)),
                button_h=button_height(scale=scale), n_buttons=len(self.buttons),
                penalty=self.t.penalty is not None)
            for button, rect in zip(self.buttons, lay.buttons):
                button.box = Box(*rect)
            self._drawn.update(
                box=Box(*lay.box), panel=Box(*lay.panel) if lay.panel is not None else None,
                label_spec=dataclasses.replace(self.panel_spec, size=scaled(LABEL_SIZE, scale)),
                count_spec=dataclasses.replace(self.panel_spec,
                                               size=scaled(self.panel_spec.size, scale)))
        if not self.fit_dirty:
            return
        self.fit_dirty = False
        lay = self.tlay
        assert lay is not None
        font = self._font_at(canvas, self.panel_spec)

        def measure(text: str, size: int) -> float:
            return font(size).size(text)[0] if text else 0

        self.fit = fit_message(
            self.t.texts[self.stmt], lay.statement[2], scaled(self.statement_size, scale),
            measure, max_lines=STATEMENT_LINES, min_size=STATEMENT_MIN_SIZE,
            step=STATEMENT_STEP)
        self.fits_made += 1
        speaker = self.t.speaker
        self.speaker_fit = None if speaker is None else fit_label(
            speaker, self._font_at(canvas, self.heading_spec),
            scaled(self.heading_spec.size, scale), SPEAKER_MAX_W)
        # The draw calls, made once per change (AC-F25-23: nothing rebuilt per frame).
        sfit = self.speaker_fit
        self._drawn["speaker"] = None if sfit is None or not sfit.text else (
            sfit.text, dataclasses.replace(self.heading_spec, size=sfit.size),
            self.colors["speaker.text_color"], lay.name_at)
        spec = dataclasses.replace(self.panel_spec, size=self.fit.size)
        x, y = lay.statement[0], lay.statement[1]
        step = pitch(self.fit.size)
        color = self.colors["statement.text_color"]
        self._drawn["lines"] = tuple((line, spec, color, (x, y + i * step))
                                     for i, line in enumerate(self.fit.lines))

    def draw(self, canvas: "Canvas") -> None:
        self._settle(canvas)
        painter = self.ctx.painter
        if self.mode == "picker":
            lay = self.play
            assert lay is not None and self.view is not None
            painter.panel(Box(*lay.backing))
            self.view.draw(canvas, painter)
            return
        lay = self.tlay
        assert lay is not None
        drawn = self._drawn
        if lay.panel is not None:
            self._draw_bar(canvas, painter, lay)
        painter.panel(drawn["box"])
        if drawn["speaker"] is not None:
            canvas.draw_text(*drawn["speaker"])
        count = len(self.t.keys)
        if count >= 2:
            canvas.draw_text(f"{self.stmt + 1} / {count}", drawn["count_spec"],
                             self.text_color, lay.count_at, anchor="topright")
        for args in drawn["lines"]:
            canvas.draw_text(*args)
        if not self.warmed:
            self._warm(canvas)

    def _warm(self, canvas: "Canvas") -> None:
        """Build the picker's two large frames into the painter's cache now, drawn with the
        surface clipped to nothing: the backing panel and the view's detail panel (F21's
        ``codex_layout`` for the tabs the held items give). The first draw is the opening
        picture, which F23 doesn't time. Built in the frame that opens the picker instead,
        they took it over W162's 8 ms (about 7 ms at 100%, 19 ms on a 1920 × 1080 window)."""
        self.warmed = True
        ctx = self.ctx
        lay = present_rules.picker_layout(self.area, button_h=button_height(scale=self.scale))
        listed = present_rules.presentable(self.t, ctx.codex.items(), ctx.story)
        home = {name: key for key, names in ctx.story.item_categories for name in names}
        size, height = ctx.theme.get("button.text_size"), ctx.theme.get("button.height")
        detail = codex_layout(Box(*lay.view), self.scale, pick=True,
                              tabs=len({home.get(name) for name in listed}),
                              button_text_size=size, button_min_height=height).panel
        surface = canvas.surface
        clip = surface.get_clip()
        surface.set_clip((0, 0, 0, 0))
        try:
            for box in (Box(*lay.backing), detail):
                ctx.painter.panel(box)
        finally:
            surface.set_clip(clip)

    def _draw_hatch(self, canvas: "Canvas", seg: tuple) -> None:
        """The loss hatch over ``seg`` (drawn after the track and fill, before the notches):
        up to ~420 small blocks, so they go straight to the canvas surface in device pixels,
        rounded as ``Canvas.fill`` rounds (both corners, floor(v·s + 0.5)). While the span
        and the scale stay the same (the whole 500 ms hatch phase), the second frame keeps a
        copy of the span's pixels, and later frames blit it: one blit instead of ~420 fills
        (TR-F25-04). The shrink phase changes the span every frame, so it fills."""
        sx, sy = canvas.scale_x, canvas.scale_y
        key = (seg, sx, sy)
        cached = self._hatch
        surface = canvas.surface
        if cached is not None and cached[0] == key:
            _, rects, pixels, area, snap = cached
            if snap is not None:
                surface.blit(snap, area[:2])
                self.hatch_drawn = rects
                return
        else:
            rects = present_rules.hatch_rects(seg)
            pixels = tuple(self._device(x, y, w, h, sx, sy) for x, y, w, h in rects)
            area = self._device(*seg, sx, sy)
            snap = None
        fill = surface.fill
        color = self.colors["bar.loss_color"]
        for rect in pixels:
            fill(color, rect)
        if cached is not None and cached[0] == key and area[2] > 0 and area[3] > 0:
            snap = surface.subsurface(area).copy()    # stable: keep the span's pixels
        self._hatch = (key, rects, pixels, area, snap)
        self.hatch_drawn = rects

    @staticmethod
    def _device(x: float, y: float, w: float, h: float, sx: float,
                sy: float) -> tuple[int, int, int, int]:
        left, top = floor(x * sx + 0.5), floor(y * sy + 0.5)
        return left, top, floor((x + w) * sx + 0.5) - left, floor((y + h) * sy + 0.5) - top

    def _draw_bar(self, canvas: "Canvas", painter, lay) -> None:
        t = self.t
        painter.panel(self._drawn["panel"])
        label = self._drawn["label_spec"]
        span, shown = self.loss_view()
        canvas.draw_text(self.word["bar_label"], label, self.text_color, lay.label_at)
        canvas.draw_text(f"{shown} / {t.penalty_max}", label, self.text_color, lay.value_at,
                         anchor="topright")
        bx, by, bw, bh = lay.bar
        canvas.fill(self.border_color, (bx - BAR_BORDER, by - BAR_BORDER, bw + 2 * BAR_BORDER,
                                        bh + 2 * BAR_BORDER))
        canvas.fill(self.colors["bar.track_color"], lay.bar)
        fill, notches = present_rules.bar_geometry(lay.bar, self._value(), t.penalty_max)
        if fill[2] > 0:
            canvas.fill(self.colors["bar.fill_color"], fill)
        self.hatch_drawn = ()
        if span is not None:
            unit = bw / t.penalty_max
            lo, hi = span
            self._draw_hatch(canvas, (bx + lo * unit, by, (hi - lo) * unit, bh))
        for notch in notches:
            canvas.fill(self.colors["bar.track_color"], notch)


__all__ = ["TOKENS", "WORDS", "Loss", "PresentEvidence"]
