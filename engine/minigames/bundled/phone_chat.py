"""Phone chat (F26): a bundled minigame showing a text conversation on a phone held over
the dimmed scene. Messages arrive after a typing indicator; at each ask the player picks a
reply or ignores it, and the story gets a dictionary of the picks.

Every rule is in ``phone_rules`` (pure); this module is the session F23's host drives
(F26 ``04`` §6):

- **Steps.** ``start`` parses the checked arguments into a queue. ``update`` walks it, one
  wait change per frame (``07`` I-3, G3): a message waits through a 500 ms gap and, unless
  it is the player's, a typing indicator (``typing_s``); then its bubble shows and
  ``_advance`` runs on to the next wait. Time steps show at once. An ask puts its replies
  (plus the ignore row) in the one ``ReplyList`` and waits without limit; the end shows one
  ``close`` row.
- **Input.** A hurry (Enter, Space, south, or a left click in the canvas, during a wait) ends
  one wait and is "used". The wheel over the thread and Page Up/Down (the shoulders too)
  scroll the thread and are used only when it moves. Everything else goes to the host,
  which routes it to the ``ReplyList`` (F23 A4). A pick is ignored until 250 ms after the
  rows appeared (inclusive, ``GUARD_EPSILON``); the guard covers ``close`` too (C3).
- **Results.** A reply shows as the player's bubble and its follow-ups run first; ignore and
  ``close`` call ``ctx.finish(result_of(…))`` once.
- **Drawing.** Lazy: ``layout``, ``settings_changed``, and new items only mark what changed;
  ``_ensure`` (from ``draw``, or from input that needs the geometry) recomputes it with the
  last canvas's fonts. The thread is laid out append-only (one wrap per new bubble), drawn
  bottom-anchored and clipped, items outside the view skipped. The host draws the
  ``ReplyList`` after ``draw``.
- **W176** (dev): on the first draw (the opening picture), each message, reply, and
  follow-up character the message font draws as ``.notdef`` is logged once per distinct text
  per process (``_WARNED``, at most 100), in F25's coded form on ``ctx.log``.

Imports (AC-F26-01): ``phone_rules``, ``engine.minigames.api``, F10's public widget kit with
F25's A7 (``ui.nav``, ``ui.layouts``), and F26's A8 (``pygame`` event types only,
``engine.render.frames``, ``engine.render.text``).
"""

import dataclasses
from collections import deque
from enum import Enum
from typing import TYPE_CHECKING, Final

import pygame

from engine.minigames.api import Arg, Minigame, Outcome, PluginEvent, StoryNames
from engine.minigames.bundled import phone_rules
from engine.minigames.bundled.phone_rules import (
    GAP_S,
    GUARD_EPSILON,
    GUARD_S,
    IGNORE,
    Ask,
    Message,
    Placed,
    TimeMark,
    Typing,
    ease_in_out,
)
from engine.minigames.bundled.phone_rules import p as pitch_of
from engine.render.frames import TOP_CORNERS, FrameSpec
from engine.render.text import Face, Synth, text_width
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import cut_to_width
from engine.ui.nav import Nav
from engine.ui.paint import frame_state
from engine.ui.widgets import ListRow, Look, ScrollList, clipped

if TYPE_CHECKING:
    from engine.minigames.api import Context, PlayerSettings
    from engine.render.canvas import Canvas
    from engine.render.text import FontSpec
    from engine.ui.paint import Painter

# [theme.plugin.phone_chat.<element>] (F26 01 §6.4, 04 §12). phone.body_width (360–600),
# header.text_size (24–40), and message.text_size (24–36) are clamped in start.
TOKENS = {
    "phone.body_color": "#1E1E24",
    "phone.screen_color": "#F7F4F6",
    "phone.body_width": 420,
    "bar.fill_color": "#FFFFFF",
    "bar.text_color": "#3A2E39",
    "bar.line_color": "#E3D9DF",
    "header.text_font": "ui.text_font",
    "header.text_size": 28,
    "message.text_font": "ui.text_font",
    "message.text_size": 24,
    "them.fill_color": "#ECE6EA",
    "them.text_color": "#2A2128",
    "me.fill_color": "#A02860",
    "me.text_color": "#FFFFFF",
    "name.text_color": "#A02860",
    "note.text_color": "#6E5E68",
    "typing.dot_color": "#6E5E68",
}

# [words.plugin.phone_chat] (F26 01 §6.4).
WORDS = {"title": "Phone", "ignore": "Don't reply", "close": "Put the phone away",
         "placeholder": "Message"}

_COLORS: Final = tuple(k for k in TOKENS if k.endswith("_color"))
_UI_FONT: Final = "ui.text_font"         # the token value meaning "the theme's UI font"
SMALL_SIZE: Final = 24                   # names, dividers, and the clock, before scaling
EASE_S: Final = 0.15                     # the thread's scroll to the bottom (01 §6.3)
DOT, DOT_GAP, DOT_LIFT = 10, 8, 4        # typing dots: size, gap, rise (canvas units)
DOT_LOOP_S, DOT_STAGGER_S = 1.2, 0.15
PLACEHOLDER_INSET, PLACEHOLDER_BORDER = 24, 2
HEADER_CUT: Final = 32                   # the contact is cut with "…" at header.w − 32
ROW_MIN, ROW_PAD = 56, 16                # a reply pill: max(56, lines·p(bs) + 16)
ROW_GAP, IGNORE_GAP = 8, 16              # below a row; above the ignore row
WHEEL_ROWS, WHEEL_GAP = 3, 8             # a wheel notch scrolls 3 × (p(s) + 8)
W176_MAX: Final = 100                    # distinct W176 texts per process

# W176 texts already logged this process (dev only; never saved; at most W176_MAX).
_WARNED: set[str] = set()


class Phase(Enum):
    BEGIN = "begin"          # the opening picture, until the first update
    GAP = "gap"              # before a message (and its typing indicator)
    TYPING = "typing"
    ASK = "ask"              # reply rows shown
    END = "end"              # the close row shown
    DONE = "done"            # finished


def _rgb(value: object) -> tuple[int, int, int]:
    """A color token: ``"#RRGGBB"`` (the declared default) or an RGB tuple (typed config)."""
    if type(value) is str and len(value) == 7 and value[0] == "#":
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return int(value[0]), int(value[1]), int(value[2])
    raise ValueError(f"not a color: {value!r}")


def _clamp(value: object, lo: int, hi: int) -> int:
    return min(max(int(value), lo), hi)                     # type: ignore[call-overload]


def _font_ref(value: object) -> str | None:
    return None if value is None or value == _UI_FONT else str(value)


def _tri(x: float) -> float:
    return 2 * x if x < 0.5 else 2 - 2 * x


def _inside(rect: tuple[float, float, float, float], pos: tuple[float, float]) -> bool:
    x, y, w, h = rect
    return x <= pos[0] < x + w and y <= pos[1] < y + h


class ReplyList(ScrollList):
    """The reply rows (one per session; the rows change per ask): F10's ``ScrollList`` with
    variable rows, so scrolling past the cap, focus scrolled into view, the wheel, and the
    lane come from F10. Drawn as pills with wrapped labels (04 §6.5)."""

    def __init__(self, game: "PhoneChat") -> None:
        super().__init__(rows=game._rows, on_activate=game._pick, heights=game._row_height,
                         pitch=game._button_pitch)
        self.game = game

    def pill(self, index: int) -> Box:
        """Row ``index``'s pill: its row box minus the trailing gap."""
        box = self.row_box(index)
        return Box(box.x, box.y, box.w, box.h - self.game._gap(index))

    def on_nav(self, d: Nav) -> bool:
        """F10's list navigation, except Page Up/Down: they scroll only the thread (C2), so
        an unused one stays F14's."""
        if d in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            return False
        return super().on_nav(d)

    def row_at(self, pos: tuple[float, float]) -> int | None:
        """The row under ``pos``; None inside a row's trailing gap."""
        index = super().row_at(pos)
        if index is None or pos[1] >= self.pill(index).bottom:
            return None
        return index

    def draw(self, p: "Painter", look: Look) -> None:
        rows = self._sync()
        game = self.game
        if not rows or not game._ensure():
            return
        bs = game._sizes[3]
        step = pitch_of(bs)
        with clipped(p, self.box):
            for index in self.visible_range():
                pill = self.pill(index)
                state = Look(self.row_state(index, rows[index], look))
                p.widget_frame(pill, "button", state)
                style = p.style("button", frame_state(state))
                font = dataclasses.replace(style.font, size=bs)
                if index == game.ignore_row:
                    font = dataclasses.replace(font, bundled=Face.ITALIC, synth=Synth.ITALIC)
                lines = game._wraps[index]
                top = pill.y + (pill.h - len(lines) * step) / 2
                for k, line in enumerate(lines):
                    p.canvas.draw_text(line, font, style.text_color,
                                       (pill.x + style.side_padding, top + k * step + step / 2),
                                       anchor="midleft")
            lane, thumb = self.lane_box(), self.thumb_box()
            if lane is not None and thumb is not None:
                style = p.style("list", "normal")
                x = lane.x + (lane.w - 8) / 2
                p.shape(Box(x, lane.y, 8, lane.h),
                        FrameSpec(style.color("scrollbar_track"), 1.0, corner_radius=4))
                p.shape(Box(x, thumb.y, 8, thumb.h),
                        FrameSpec(style.color("scrollbar"), 1.0, corner_radius=4))


class PhoneChat(Minigame):
    name = "phone_chat"
    title = "Phone"
    api = "1.1"
    over_stage = True
    args = {"chat": Arg(), "contact": Arg(), "time": Arg(default=None)}
    # The static outcomes gate skippable (E271) and E279; outcome_for gives the real ones
    # (PR-F26-13).
    test_outcome = Outcome(None)
    skipped_outcome = Outcome(None)
    tokens = TOKENS
    words = WORDS

    def check_args(self, args: dict) -> str | None:
        return phone_rules.problem(args)

    def outcome_for(self, kind: str, args: dict, story: StoryNames) -> Outcome | None:
        return phone_rules.fixed_outcome(kind, phone_rules.parse(args))

    # --- The session (04 §6.1) ---------------------------------------------------------------

    def start(self, ctx: "Context") -> None:
        self.ctx = ctx
        self.chat = phone_rules.parse(ctx.args)
        self.queue: deque = deque(self.chat.steps)
        self.picks: dict[str, str] = {}
        self.phase = Phase.BEGIN
        self.t = 0.0
        self.since_buttons = 0.0
        self.anim = 0.0
        self.done = False
        self.items: list[Message | TimeMark] = []
        self.typing: Typing | None = None
        self.clock: str | None = None
        if self.chat.time is not None:
            self.items.append(TimeMark(self.chat.time))
            self.clock = self.chat.time
        self.ask: Ask | None = None
        self.labels: tuple[str, ...] = ()
        self.ignore_row: int | None = None
        self._row_list: tuple[ListRow, ...] = ()
        self.replies = ReplyList(self)
        ctx.scope.set_groups([])
        ctx.heading(False)
        mine = ctx.theme.mine
        self.colors = {key: _rgb(mine(key)) for key in _COLORS}
        self.body_width = _clamp(mine("phone.body_width"), *phone_rules.BODY_WIDTH)
        self.header_size = _clamp(mine("header.text_size"), *phone_rules.HEADER_SIZE)
        self.message_size = _clamp(mine("message.text_size"), *phone_rules.MESSAGE_SIZE)
        self.header_ref = _font_ref(mine("header.text_font"))
        self.message_ref = _font_ref(mine("message.text_font"))
        self.word = {key: ctx.words.mine(key) for key in ("ignore", "close", "placeholder")}
        settings = ctx.settings
        self.reduce = bool(settings.reduce_motion)
        self._scale = settings.text_scale
        self.area = ctx.area
        # Presentation (rebuilt by _ensure).
        self.scroll_back = 0.0              # how far the player scrolled up from the bottom
        self.ease_offset = 0.0              # the scroll-to-bottom ease (canvas units)
        self.ease_from = 0.0
        self.ease_t = 0.0
        self._ease_pending = False
        self._fontsrc: "Canvas | None" = None
        self._sizes: tuple[int, int, int, int] = (0, 0, 0, 0)    # s, small, hs, bs
        self._dirty = True
        self._base = None                   # the phone with the placeholder (widths)
        self.layout_now: phone_rules.PhoneLayout | None = None
        self._placed: tuple[Placed, ...] = ()
        self._laid = 0
        self._typing_key: tuple | None = None
        self._typing_placed: Placed | None = None
        self.view: tuple[Placed, ...] = ()  # the thread's items as drawn
        self.content_h = 0.0
        self._wraps: tuple[tuple[str, ...], ...] | None = None
        self._heights: tuple[float, ...] = ()
        self._header_text = ""
        self._glyphs_checked = False
        self.relayouts = 0                  # full relayouts so far (AC-F26-16)

    # -- the step machine (04 §6.2) --

    def update(self, dt: float) -> None:
        if self.done:
            return
        self.anim += dt
        self.since_buttons += dt
        self._ease(dt)
        phase = self.phase                  # one wait change per update (07 I-3)
        if phase is Phase.BEGIN:
            self._advance()
        elif phase is Phase.GAP:
            head = self.queue[0]
            if self.t + dt >= GAP_S - GUARD_EPSILON:
                if head.sender is None:
                    self._show()
                else:
                    self.phase = Phase.TYPING
                    self.t = 0.0
                    self.typing = Typing(head.sender)
            else:
                self.t += dt
        elif phase is Phase.TYPING:
            if self.t + dt >= phone_rules.typing_s(self.queue[0].text) - GUARD_EPSILON:
                self._show()
            else:
                self.t += dt

    def _advance(self) -> None:
        """Run on until something waits: time steps show at once; an ask shows its rows; a
        message starts its gap; the end shows ``close``."""
        queue = self.queue
        while queue:
            step = queue[0]
            if isinstance(step, TimeMark):
                queue.popleft()
                self.items.append(step)
                self.clock = step.text
                continue
            if isinstance(step, Ask):
                queue.popleft()
                self.ask = step
                labels = [o.text for o in step.options]
                ignore_at = None
                if step.ignore:
                    ignore_at = len(labels)
                    labels.append(step.ignore_label if step.ignore_label is not None
                                  else self.word["ignore"])
                self._buttons(labels, ignore_at)
                self.phase = Phase.ASK
                return
            self.phase = Phase.GAP
            self.t = 0.0
            return
        self.ask = None
        self._buttons([self.word["close"]], None)
        self.phase = Phase.END

    def _buttons(self, labels: list[str], ignore_at: int | None) -> None:
        self.labels = tuple(labels)
        self.ignore_row = ignore_at
        self._row_list = tuple(ListRow(label) for label in labels)
        self._wraps = None
        replies = self.replies
        replies.focus_row = 0
        replies.scroll = 0.0
        replies.heights_changed()
        self.ctx.scope.set_groups([FocusGroup([replies], column=True)])
        self.since_buttons = 0.0

    def _clear_buttons(self) -> None:
        self.ctx.scope.set_groups([])
        self.labels = ()
        self.ignore_row = None
        self._row_list = ()
        self._wraps = None
        self.replies.heights_changed()

    def _show(self) -> None:
        msg = self.queue.popleft()
        assert isinstance(msg, Message), "_show needs a message at the head"
        self.typing = None
        self.items.append(msg)
        self._to_bottom()
        self._advance()

    def _to_bottom(self) -> None:
        self.scroll_back = 0.0
        self._ease_pending = True

    def _hurry(self) -> bool:
        if self.phase in (Phase.GAP, Phase.TYPING):
            self._show()
            return True
        return False

    def _pick(self, index: int) -> None:
        """``ReplyList.on_activate``: a reply, ignore, or close (PR-F26-08–10)."""
        if self.done or self.since_buttons < GUARD_S - GUARD_EPSILON:
            return
        if self.phase is Phase.END:
            self._finish()
            return
        ask = self.ask
        assert ask is not None and 0 <= index < len(self.labels), "_pick out of range"
        if index == len(ask.options):                         # the ignore row
            self.picks[ask.id] = IGNORE
            self._finish()
            return
        option = ask.options[index]
        self.picks[ask.id] = option.key
        self._clear_buttons()
        self.ask = None
        self.items.append(Message(None, option.text))
        self.queue.extendleft(reversed(option.after))
        self._to_bottom()
        self._advance()

    def _finish(self) -> None:
        self.done = True
        self.phase = Phase.DONE
        self.ctx.finish(phone_rules.result_of(self.chat, self.picks))

    def _ease(self, dt: float) -> None:
        if self.ease_offset <= 0.0:
            return
        self.ease_t += dt
        if self.reduce or self.ease_t >= EASE_S - GUARD_EPSILON:
            self.ease_offset = 0.0
        else:
            self.ease_offset = self.ease_from * (1.0 - ease_in_out(self.ease_t / EASE_S))

    # -- input (04 §6.4) --

    def handle_event(self, ev: PluginEvent) -> bool:
        if self.done:
            return False
        ui = ev.ui
        raw = ui.raw
        kind = raw.type
        if self.phase in (Phase.GAP, Phase.TYPING) and (
                ev.nav is Nav.ACTIVATE
                or (kind == pygame.MOUSEBUTTONDOWN and getattr(raw, "button", 0) == 1
                    and ui.in_canvas)):
            return self._hurry()
        if kind == pygame.MOUSEWHEEL:
            pos = ui.canvas_pos if ui.in_canvas else None
            if pos is None or not self._ensure() or not _inside(self.layout_now.thread, pos):
                return False
            notches = int(getattr(raw, "y", 0))
            step = WHEEL_ROWS * (pitch_of(self._sizes[0]) + WHEEL_GAP)
            return self._scroll(notches * step)
        if ev.nav in (Nav.PAGE_UP, Nav.PAGE_DOWN) and self._ensure():
            step = self.layout_now.thread[3] - pitch_of(self._sizes[0])
            return self._scroll(step if ev.nav is Nav.PAGE_UP else -step)
        return False

    def _scroll(self, delta: float) -> bool:
        """Scroll the thread up by ``delta`` (down when negative), clamped. True if it moved."""
        self._ensure()
        assert self.layout_now is not None
        most = max(0.0, self.content_h - self.layout_now.thread[3])
        before = self.scroll_back
        self.scroll_back = min(most, max(0.0, before + delta))
        if self.scroll_back == before:
            return False
        self.ease_offset = 0.0
        return True

    # -- layout (04 §6.5) --

    def layout(self, area: object) -> None:
        self.area = area
        self._dirty = True

    def settings_changed(self, s: "PlayerSettings") -> None:
        self.reduce = bool(s.reduce_motion)
        if self.reduce:
            self.ease_offset = 0.0
        if s.text_scale != self._scale:
            self._scale = s.text_scale
            self._dirty = True

    def _rows(self) -> tuple[ListRow, ...]:
        return self._row_list

    def _gap(self, index: int) -> float:
        """The gap below row ``index``: 16 before the ignore row, 0 after the last, else 8."""
        if index >= len(self.labels) - 1:
            return 0.0
        return IGNORE_GAP if index + 1 == self.ignore_row else ROW_GAP

    def _row_height(self, index: int) -> float:
        if not self._ensure() or index >= len(self._heights):
            return ROW_MIN
        return self._heights[index]

    def _button_pitch(self) -> float:
        return pitch_of(self._sizes[3]) if self._sizes[3] else pitch_of(28)

    def _spec(self, ref: str | None, size: int) -> "FontSpec":
        return self.ctx.font(ref, size)

    def _measure(self, spec: "FontSpec"):
        src = self._fontsrc
        assert src is not None
        fonts: dict[int, object] = {}

        def measure(text: str, size: int) -> float:
            font = fonts.get(size)
            if font is None:
                font = fonts[size] = src.font_handle(dataclasses.replace(spec, size=size),
                                                     size).font
            return text_width(font, text)               # type: ignore[arg-type]

        return measure

    def _ensure(self) -> bool:
        """Recompute whatever changed (sizes, the phone, the rows, the thread). False before
        the first draw (no fonts yet)."""
        if self._fontsrc is None:
            return False
        painter = self.ctx.painter
        button = painter.style("button")
        sizes = (painter.scaled_size(self.message_size), painter.scaled_size(SMALL_SIZE),
                 painter.scaled_size(self.header_size), painter.scaled_size(button.font.size))
        if sizes != self._sizes or self._dirty:
            self._full(sizes, button)
        s, small, hs, bs = sizes
        if self._wraps is None:
            width = self._base.reply[2] - 2 * button.side_padding
            self._wraps = tuple(tuple(phone_rules.wrap_text(label, width, bs, self._bmeasure))
                                for label in self.labels)
            pitch = pitch_of(bs)
            self._heights = tuple(max(ROW_MIN, len(lines) * pitch + ROW_PAD) + self._gap(i)
                                  for i, lines in enumerate(self._wraps))
            self.replies.heights_changed()
            self.layout_now = None
        if self.layout_now is None:
            reply_h = sum(self._heights) if self.labels else None
            self.layout_now = phone_rules.phone_layout(
                self.area, s=s, bar_size=small, header_size=hs, body_width=self.body_width,
                reply_h=reply_h)
            self.replies.box = Box(*self.layout_now.reply)
        self._thread(s, small)
        return True

    def _full(self, sizes: tuple[int, int, int, int], button) -> None:
        """A full relayout (text size, area): fonts, the phone, every thread item; the thread
        returns to the bottom; the ``ReplyList`` (and its focus) is kept."""
        self.relayouts += 1
        self._dirty = False
        self._sizes = sizes
        s, small, hs, bs = sizes
        self.message_font = self._spec(self.message_ref, s)
        self.small_font = dataclasses.replace(self.message_font, size=small)
        self.header_font = self._spec(self.header_ref, hs)
        self.clock_font = self._spec(None, small)
        self.button_font = dataclasses.replace(button.font, size=bs)
        self._mmeasure = self._measure(self.message_font)
        self._bmeasure = self._measure(self.button_font)
        self._base = phone_rules.phone_layout(self.area, s=s, bar_size=small, header_size=hs,
                                              body_width=self.body_width, reply_h=None)
        header = self._base.header
        self._header_text = cut_to_width(self.chat.contact, header[2] - HEADER_CUT, hs,
                                         self._measure(self.header_font))
        self._placed = ()
        self._laid = 0
        self._typing_key = None
        self._wraps = None
        self.layout_now = None
        self.scroll_back = 0.0
        self.ease_offset = 0.0
        self._ease_pending = False
        self.replies.heights_changed()

    def _thread(self, s: int, small: int) -> None:
        width = self._base.thread[2]
        if self._laid < len(self.items):
            self._placed = phone_rules.thread_layout(
                self.items[self._laid:], width, s=s, small=small, group=self.chat.group,
                measure=self._mmeasure, start=self._placed)
            self._laid = len(self.items)
        view = self._placed
        typing = self.typing
        if typing is not None:
            key = (typing, len(self._placed))
            if key != self._typing_key:
                self._typing_key = key
                self._typing_placed = phone_rules.thread_layout(
                    [typing], width, s=s, small=small, group=self.chat.group,
                    measure=self._mmeasure, start=self._placed)[-1]
            view = view + (self._typing_placed,)            # type: ignore[operator]
        height = view[-1].y + view[-1].h if view else 0.0
        if self._ease_pending:
            self._ease_pending = False
            added = height - self.content_h
            if not self.reduce and added > 0:
                self.ease_from = self.ease_offset = added
                self.ease_t = 0.0
        self.view = view
        self.content_h = height

    # -- drawing (04 §6.5) --

    def thread_top(self) -> float:
        """The canvas y of the content's top (bottom-anchored, scroll and ease applied)."""
        assert self.layout_now is not None
        x, y, w, h = self.layout_now.thread
        return y + h - self.content_h + self.scroll_back + self.ease_offset

    def dot_lift(self, k: int) -> float:
        if self.reduce:
            return 0.0
        x = ((self.anim - DOT_STAGGER_S * k) % DOT_LOOP_S) / DOT_LOOP_S
        return DOT_LIFT * ease_in_out(_tri(x))

    def draw(self, canvas: "Canvas") -> None:
        self._fontsrc = canvas
        self._ensure()
        if not self._glyphs_checked:
            self._glyphs_checked = True
            if self.ctx.dev:
                self._check_glyphs(canvas)
        lay = self.layout_now
        assert lay is not None
        painter = self.ctx.painter
        color = self.colors
        s, small, hs, bs = self._sizes
        self._draw_chrome(painter, lay)
        bx, by, bw, bh = lay.bar
        hx, hy, hw, hh = lay.header
        if self.clock is not None:
            canvas.draw_text(self.clock, self.clock_font, color["bar.text_color"],
                             (bx + bw / 2, by + bh / 2), anchor="center")
        canvas.draw_text(self._header_text, self.header_font, color["bar.text_color"],
                         (hx + hw / 2, hy + hh / 2), anchor="center")
        painter.rect(Box(hx, hy + hh, hw, 1), color["bar.line_color"])
        with clipped(painter, Box(*lay.thread)):
            self._draw_thread(canvas, painter, s, small)
        if not self.labels:
            self._draw_placeholder(canvas, painter, lay, s)

    def _draw_chrome(self, painter, lay: phone_rules.PhoneLayout) -> None:
        """The body (radius 40) around the screen (inset 12, so radius 28) as one bordered
        shape, then the white bar and header with the screen's top corners: two cached shapes,
        no full-size fill (a fill measured slower than a shape's blit; TR-F26-02)."""
        color = self.colors
        painter.shape(Box(*lay.body),
                      FrameSpec(color["phone.screen_color"], 1.0,
                                border_color=color["phone.body_color"],
                                border_width=phone_rules.SCREEN_INSET,
                                corner_radius=phone_rules.BODY_RADIUS))
        bx, by, bw, bh = lay.bar
        painter.shape(Box(bx, by, bw, bh + lay.header[3]),
                      FrameSpec(color["bar.fill_color"], 1.0,
                                corner_radius=phone_rules.SCREEN_RADIUS, corners=TOP_CORNERS))

    def _draw_thread(self, canvas: "Canvas", painter, s: int, small: int) -> None:
        lay = self.layout_now
        tx, ty, tw, th = lay.thread
        top = self.thread_top()
        color = self.colors
        pitch, name_room = pitch_of(s), pitch_of(small) + phone_rules.NAME_GAP
        for item in reversed(self.view):                    # newest first; stop above the view
            y = top + item.y
            if y > ty + th:
                continue
            if y + item.h + name_room < ty - name_room:
                break
            x = tx + item.x
            if item.kind == "time":
                canvas.draw_text(item.lines[0], self.small_font, color["note.text_color"],
                                 (tx + tw / 2, y + item.h / 2), anchor="center")
                continue
            if item.name is not None:
                canvas.draw_text(item.name, self.small_font, color["name.text_color"],
                                 (x, y - phone_rules.NAME_GAP - pitch_of(small) / 2),
                                 anchor="midleft")
            mine = item.kind == "me"
            fill = color["me.fill_color" if mine else "them.fill_color"]
            painter.shape(Box(x, y, item.w, item.h),
                          FrameSpec(fill, 1.0, corner_radius=phone_rules.BUBBLE_RADIUS))
            if item.kind == "typing":
                left = x + (item.w - (3 * DOT + 2 * DOT_GAP)) / 2
                cy = y + item.h / 2
                for k in range(3):
                    lift = self.dot_lift(k)
                    painter.ellipse(Box(left + k * (DOT + DOT_GAP), cy - DOT / 2 - lift, DOT,
                                        DOT), color["typing.dot_color"])
                continue
            ink = color["me.text_color" if mine else "them.text_color"]
            for k, line in enumerate(item.lines):
                canvas.draw_text(line, self.message_font, ink,
                                 (x + phone_rules.BUBBLE_PAD_X,
                                  y + phone_rules.BUBBLE_PAD_Y + k * pitch + pitch / 2),
                                 anchor="midleft")

    def _draw_placeholder(self, canvas: "Canvas", painter, lay, s: int) -> None:
        x, y, w, h = lay.reply
        note = self.colors["note.text_color"]
        painter.shape(Box(x, y, w, h),
                      FrameSpec(self.colors["phone.screen_color"], 1.0, border_color=note,
                                border_width=PLACEHOLDER_BORDER, corner_radius=int(h // 2)))
        canvas.draw_text(self.word["placeholder"], self.message_font, note,
                         (x + PLACEHOLDER_INSET, y + h / 2), anchor="midleft")

    # -- W176 (04 §6.7) --

    def _check_glyphs(self, canvas: "Canvas") -> None:
        pairs = phone_rules.glyph_chars(self.chat)
        if not pairs:
            return
        s = self._sizes[0]
        font = canvas.font_handle(self.message_font, s).font
        missing = set(phone_rules.glyph_missing(font, "".join(ch for ch, _ in pairs)))
        for ch, where in pairs:
            if ch not in missing:
                continue
            text = phone_rules.w176_text(ch, where)
            if text in _WARNED or len(_WARNED) >= W176_MAX:
                continue
            _WARNED.add(text)
            self.ctx.log.warning("%s", text, extra={"code": "W176"})


__all__ = ["TOKENS", "WORDS", "Phase", "PhoneChat", "ReplyList"]
