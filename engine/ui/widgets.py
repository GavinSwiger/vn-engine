"""The six F10 widgets: state and behaviour (F10 ``04`` §5.2, §7.4; ui-system §9).

Why this module exists: every menu, page, and minigame UI is built from the same button,
on/off button, toggle, slider, scroll list, and grid, so they act the same everywhere and
later features (F11 slots, F16 settings, F13 history) only supply data and callbacks.

A widget holds no theme: ``draw(painter, look)`` draws it through the painter, which gives
every color, font, and frame (F10 03-ui widget table and States). The state is pure and fed by
``Nav`` values and mouse calls in canvas units, so it is unit-tested headless:

- ``on_nav(d)`` lets the focused widget use a direction first (slider value, toggle side,
  list row, grid cell). True = used; False = the focus scope moves focus instead.
- ``activate()`` is Enter / south / a completed click.
- ``on_mouse(kind, pos, notches=)``: ``"hover"`` (pointer over it), ``"down"`` (button-1
  press on it), ``"drag"`` (motion while it is pressed), ``"up"`` (button-1 release ending
  its press), ``"wheel"`` (``notches`` = pygame's ``MOUSEWHEEL.y``: positive scrolls toward
  the start). True = the widget changed or used it.
- ``accepts_click(pos)``: whether a button-1 release at ``pos`` completes the click begun by
  the last ``"down"``; the screen then calls ``activate()`` and plays ``activate_sound``.

Values come from the getters every time (``label()``, ``get()``, ``rows()``, ``cells()``),
so a widget never holds a stale copy of game or config state.
"""

import bisect
import contextlib
import dataclasses
import itertools
import math
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from engine.render.frames import FrameSpec
from engine.ui.focus import Box, move_target
from engine.ui.layouts import (
    LIST_ROW_HEIGHT,
    SCROLLBAR_LANE,
    SCROLLBAR_MIN_THUMB,
    SLIDER_BAR_LEFT,
    SLIDER_BAR_RIGHT,
    pitch,
)
from engine.ui.nav import Nav
from engine.ui.paint import frame_state

if TYPE_CHECKING:
    from engine.render.canvas import Anchor
    from engine.ui.paint import Painter

MouseKind = Literal["hover", "down", "drag", "up", "wheel"]
LookState = Literal["normal", "focused", "pressed", "disabled"]

WHEEL_ROWS = 3            # rows per wheel notch (lists and grids)
WHEEL_GAP = 8             # variable rows: a notch is WHEEL_ROWS × (pitch + 8) (UI-F13-02)
SLIDER_STEPS = 20         # step = max(1, round((hi − lo) / 20))

# Drawing geometry in canvas units (F10 03-ui widget table).
ROW_TEXT_X = 32           # row labels start 32 inside the left edge
TRACK_SIZE = (56, 28)     # toggle track, radius 14, 32 inside the right edge
TRACK_INSET = 32
TRACK_RADIUS = 14
TRACK_OUTLINE = 2
KNOB = 20                 # toggle knob diameter, 4 inside the track's end
KNOB_INSET = 4
STATE_WORD_GAP = 12       # "On"/"Off" ends 12 left of the track
LABEL_TOP = 8             # slider label top
BAR_BAND = 28             # slider bar band height, below the label line
BAR_THIN = 4              # unfilled part
BAR_THICK = 8             # filled part
THUMB = (16, 28)          # slider thumb, radius 6, 2-unit border
THUMB_RADIUS = 6
THUMB_BORDER = 2
VALUE_INSET = 32          # the value's right edge from the row's right edge
VALUE_GAP = 24            # F50: between the bar's end and a wide value slot
DIVIDER = 1               # list divider below each row
SCROLL_TRACK = 8          # scrollbar track and thumb width, radius 4, centred in the lane
SCROLL_RADIUS = 4

_EMPTY_BOX = Box(0, 0, 0, 0)


def _always() -> bool:
    return True


def round_half_up(value: float) -> int:
    """Rounding as the specs write it (0.5 goes up), not Python's banker's rounding."""
    return math.floor(value + 0.5)


@dataclass(frozen=True)
class Look:
    """How a widget is drawn this frame."""

    state: LookState
    on: bool | None = None
    selected: bool = False


class Widget:
    """Base widget. ``box`` is set by the screen's layout (canvas units).

    ``focusable`` False makes a widget drawn-only (the sampler's static state buttons);
    ``repeatable`` widgets repeat a held direction (``RepeatClock``)."""

    repeatable: bool = False
    # F52 (07 §3.1): a text widget (``ui.textfield.TextField``) gets raw text and editing
    # keys through ``on_text`` while focused, before navigation (``ui.textrouting``).
    takes_text: bool = False

    def __init__(self, *, enabled: Callable[[], bool] | None = None, box: Box = _EMPTY_BOX,
                 focusable: bool = True) -> None:
        self.enabled: Callable[[], bool] = enabled if enabled is not None else _always
        self.box = box
        self.focusable = focusable

    def on_text(self, event: object) -> bool:
        """F52: a raw ``TEXTINPUT``/``TEXTEDITING`` event for a ``takes_text`` widget."""
        return False

    def on_nav(self, d: Nav) -> bool:
        return False

    def activate(self) -> None:
        pass

    def tab_entered(self, forward: bool) -> None:
        """Tab (``forward``) or Shift+Tab just focused this widget (``FocusScope.tab``): a
        widget with parts in the Tab order starts at its first or last part."""

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        return False

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        return bool(self.enabled()) and self.box.contains(pos)

    def on_state(self) -> bool | None:
        """On/off for the look (pip, toggle), or None when the widget has no such state."""
        return None

    def is_selected(self) -> bool:
        return False

    def look(self, *, focused: bool, pressed: bool = False) -> Look:
        """The look for this frame, given the screen's focus and press state."""
        if not self.enabled():
            state: LookState = "disabled"
        elif pressed:
            state = "pressed"
        elif focused:
            state = "focused"
        else:
            state = "normal"
        return Look(state, self.on_state(), self.is_selected())

    def draw(self, p: "Painter", look: Look) -> None:
        """Draw this widget in ``look`` through the painter (subclasses)."""


def _row_look(look: Look) -> Look:
    """A row widget's frame look: no pip and no bar (the toggle draws its own track)."""
    return Look(look.state)


def fitted_text(p: "Painter", text: str, pos: tuple[float, float], *, area: str, state: str,
                width: float, anchor: "Anchor" = "topleft") -> None:
    """A row label fitted by UI-F10-02 (``Painter.fit``): its size steps down by 2 to fit
    ``width``, not below 24, then it ends in "…" (F16 design §6.5: "Auto-advance waits for
    voices" draws at 40 at 150 %)."""
    style = p.style(area, state)
    fit = p.fit(text, area, max(1.0, width), state)
    if fit.text:
        p.canvas.draw_text(fit.text, dataclasses.replace(style.font, size=fit.size),
                           style.text_color, pos, anchor=anchor)


@contextlib.contextmanager
def clipped(p: "Painter", box: Box) -> Iterator[None]:
    """Clip drawing on the painter's canvas to ``box`` (within any clip already set)."""
    surface = p.canvas.surface
    assert surface is not None
    previous = surface.get_clip()
    surface.set_clip(previous.clip(p.canvas.rect_to_px((box.x, box.y, box.w, box.h))))
    try:
        yield
    finally:
        surface.set_clip(previous)


class Button(Widget):
    """A button; with ``on`` an on/off button (pip); with ``selected`` a sidebar entry."""

    def __init__(self, label: Callable[[], str], action: Callable[[], None], *,
                 enabled: Callable[[], bool] | None = None,
                 on: Callable[[], bool] | None = None,
                 selected: Callable[[], bool] | None = None,
                 area: str = "button", box: Box = _EMPTY_BOX, focusable: bool = True) -> None:
        super().__init__(enabled=enabled, box=box, focusable=focusable)
        self.label = label
        self.action = action
        self.on = on
        self.selected = selected
        self.area = area

    def activate(self) -> None:
        if self.enabled():
            self.action()

    def on_state(self) -> bool | None:
        return None if self.on is None else bool(self.on())

    def is_selected(self) -> bool:
        return self.selected is not None and bool(self.selected())

    def draw(self, p: "Painter", look: Look) -> None:
        """Frame, marker, pip, and bar for the state, then the label fitted by UI-F10-02."""
        p.widget_frame(self.box, self.area, look)
        p.label(self.label(), self.box, area=self.area, look=look)


class Toggle(Widget):
    """A labelled on/off row. Enter flips it; Left sets off, Right sets on (both consumed,
    so Left/Right never move focus off a focused toggle). ``set`` only on change.
    ``state_word(on)`` is the word drawn left of the track (``[words] on``/``off``)."""

    def __init__(self, label: Callable[[], str], get: Callable[[], bool],
                 set: Callable[[bool], None], *,
                 enabled: Callable[[], bool] | None = None, box: Box = _EMPTY_BOX,
                 focusable: bool = True,
                 state_word: Callable[[bool], str] | None = None) -> None:
        super().__init__(enabled=enabled, box=box, focusable=focusable)
        self.label = label
        self.get = get
        self.set = set
        self.state_word = state_word

    def track_box(self) -> Box:
        """The 56×28 track, 32 inside the right edge, vertically centred."""
        w, h = TRACK_SIZE
        return Box(self.box.right - TRACK_INSET - w, self.box.y + self.box.h / 2 - h / 2, w, h)

    def draw(self, p: "Painter", look: Look) -> None:
        """Row frame (focused look only), label at x 32, state word, track and knob: off is
        an outline track with the knob left, on a filled track with the knob right, disabled
        a filled ``disabled_track`` track with no knob (03-ui States)."""
        state = frame_state(look)
        style = p.style("toggle", state)
        p.widget_frame(self.box, "toggle", _row_look(look))
        track = self.track_box()
        cy = self.box.y + self.box.h / 2
        on = bool(self.get())
        word = self.state_word(on) if self.state_word is not None else ""
        word_right = track.x - STATE_WORD_GAP
        word_w = 0.0
        if word:
            bounds = p.text(word, (word_right, cy), area="toggle", state=state,
                            anchor="midright")
            word_w = bounds[2]
        label_w = word_right - word_w - STATE_WORD_GAP - (self.box.x + ROW_TEXT_X)
        fitted_text(p, self.label(), (self.box.x + ROW_TEXT_X, cy), area="toggle",
                    state=state, width=label_w, anchor="midleft")
        knob_y = cy - KNOB / 2
        if state == "disabled":
            p.shape(track, FrameSpec(style.color("disabled_track"), 1.0,
                                     corner_radius=TRACK_RADIUS))
        elif on:
            p.shape(track, FrameSpec(style.color("on_track"), 1.0, corner_radius=TRACK_RADIUS))
            p.ellipse(Box(track.right - KNOB_INSET - KNOB, knob_y, KNOB, KNOB),
                      style.color("on_knob"))
        else:
            p.shape(track, FrameSpec(style.color("track"), 0.0, style.color("track"),
                                     TRACK_OUTLINE, TRACK_RADIUS))
            p.ellipse(Box(track.x + KNOB_INSET, knob_y, KNOB, KNOB), style.color("track"))

    def activate(self) -> None:
        if self.enabled():
            self.set(not self.get())

    def on_nav(self, d: Nav) -> bool:
        if d not in (Nav.LEFT, Nav.RIGHT):
            return False
        want = d is Nav.RIGHT
        if self.enabled() and bool(self.get()) != want:
            self.set(want)
        return True

    def on_state(self) -> bool | None:
        return bool(self.get())


class Slider(Widget):
    """An integer in ``[lo, hi]``. Left/Right ∓ ``step``, Home/End → ``lo``/``hi``; a press
    or drag on the row sets the value under the pointer. ``set`` only on change, at once.

    F16 conflict 3 (``04`` OQ-4): ``step`` given replaces F10's ``(hi − lo) / 20`` rule, and
    a press or drag then snaps to ``lo + k·step`` (clamped to ``hi``), so a drag can't give
    137 %; keys still step from wherever the value is. ``value_text(v)`` is the value drawn
    at the row's right (``str`` when None: F10's). F50: ``value_width`` (canvas units) gives
    a word-valued slider ("No time limits") a wider value slot: the bar then ends
    ``VALUE_GAP`` left of it, and the value is fitted to it (``fitted_text``)."""

    repeatable = True

    def __init__(self, label: Callable[[], str], lo: int, hi: int, get: Callable[[], int],
                 set: Callable[[int], None], *,
                 enabled: Callable[[], bool] | None = None, box: Box = _EMPTY_BOX,
                 focusable: bool = True, step: int | None = None,
                 value_text: Callable[[int], str] | None = None,
                 value_width: float | None = None) -> None:
        super().__init__(enabled=enabled, box=box, focusable=focusable)
        if hi < lo:
            raise ValueError(f"Slider range is empty: {lo} > {hi}")
        if step is not None and step < 1:
            raise ValueError(f"Slider step must be at least 1, not {step}")
        self.label = label
        self.lo = lo
        self.hi = hi
        self.get = get
        self.set = set
        self.snap = step is not None
        self.step = step if step is not None else max(1, round_half_up((hi - lo) / SLIDER_STEPS))
        self.value_text = value_text
        self.value_width = value_width
        self.dragging = False

    @property
    def value(self) -> int:
        return min(self.hi, max(self.lo, int(self.get())))

    def bar_span(self) -> tuple[float, float]:
        """The bar's x range: ``[box.x + 32, box.right − 104]`` (with ``value_width``,
        ``box.right − 32 − value_width − VALUE_GAP``)."""
        right = (SLIDER_BAR_RIGHT if self.value_width is None
                 else VALUE_INSET + self.value_width + VALUE_GAP)
        return self.box.x + SLIDER_BAR_LEFT, self.box.right - right

    def value_at(self, x: float) -> int:
        """The value under the pointer at ``x``: the nearest whole value, or with ``step``
        given the nearest ``lo + k·step`` (clamped to ``hi``)."""
        x0, x1 = self.bar_span()
        if x1 <= x0:
            return self.lo
        t = min(1.0, max(0.0, (x - x0) / (x1 - x0)))
        if self.snap:
            raw = t * (self.hi - self.lo)
            snapped = min(self.hi - self.lo, round_half_up(raw / self.step) * self.step)
            if self.hi - self.lo - raw < abs(snapped - raw):
                snapped = self.hi - self.lo                # ``hi`` off the grid stays reachable
            return self.lo + snapped
        return self.lo + round_half_up(t * (self.hi - self.lo))

    def thumb_x(self) -> float:
        """The thumb centre's x for the current value."""
        x0, x1 = self.bar_span()
        span = self.hi - self.lo
        return x0 if span == 0 else x0 + (self.value - self.lo) / span * (x1 - x0)

    def on_nav(self, d: Nav) -> bool:
        if d is Nav.LEFT:
            self._put(self.value - self.step)
        elif d is Nav.RIGHT:
            self._put(self.value + self.step)
        elif d is Nav.HOME:
            self._put(self.lo)
        elif d is Nav.END:
            self._put(self.hi)
        else:
            return False
        return True

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if not self.enabled():
            self.dragging = False
            return False
        if kind == "down":
            self.dragging = True
            self._put(self.value_at(pos[0]))
            return True
        if kind == "drag" and self.dragging:
            self._put(self.value_at(pos[0]))
            return True
        if kind == "up" and self.dragging:
            self.dragging = False
            return True
        return False

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        return False                           # a press sets the value; a release never acts

    def _put(self, value: int) -> None:
        value = min(self.hi, max(self.lo, value))
        if self.enabled() and value != self.value:
            self.set(value)

    def bar_center_y(self, label_size: int) -> float:
        """The bar band's centre: below the label line (``LABEL_TOP`` + pitch), 28 tall."""
        return self.box.y + LABEL_TOP + pitch(label_size) + BAR_BAND / 2

    def draw(self, p: "Painter", look: Look) -> None:
        """Label top-left at (32, 8); the bar (4 tall unfilled, 8 tall filled up to the
        thumb), the 16×28 thumb, and the value right-aligned 32 inside the right edge. A
        disabled slider draws both parts in ``disabled_track`` and no thumb."""
        state = frame_state(look)
        style = p.style("slider", state)
        p.widget_frame(self.box, "slider", _row_look(look))
        size = p.scaled_size(style.font.size)
        fitted_text(p, self.label(), (self.box.x + ROW_TEXT_X, self.box.y + LABEL_TOP),
                    area="slider", state=state, width=self.box.w - 2 * ROW_TEXT_X)
        by = self.bar_center_y(size)
        x0, x1 = self.bar_span()
        tx = self.thumb_x()
        disabled = state == "disabled"
        track = style.color("disabled_track" if disabled else "track")
        fill = style.color("disabled_track" if disabled else "fill")
        p.rect(Box(x0, by - BAR_THIN / 2, max(0.0, x1 - x0), BAR_THIN), track)
        if tx > x0:
            p.rect(Box(x0, by - BAR_THICK / 2, tx - x0, BAR_THICK), fill)
        if not disabled:
            tw, th = THUMB
            p.shape(Box(tx - tw / 2, by - th / 2, tw, th),
                    FrameSpec(style.color("thumb"), 1.0, style.color("thumb_border"),
                              THUMB_BORDER, THUMB_RADIUS))
        value = self.value
        text = self.value_text(value) if self.value_text is not None else str(value)
        if self.value_width is not None:
            fitted_text(p, text, (self.box.right - VALUE_INSET, by), area="slider",
                        state=state, width=self.value_width, anchor="midright")
        else:
            p.text(text, (self.box.right - VALUE_INSET, by), area="slider", state=state,
                   anchor="midright")


@dataclass(frozen=True)
class ListRow:
    label: str
    enabled: bool = True


@dataclass(frozen=True)
class GridCell:
    label: str = ""
    enabled: bool = True


class _Scroller:
    """Vertical scroll state shared by ``ScrollList`` and ``Grid`` (canvas units)."""

    scroll: float

    def _content_height(self) -> float:
        raise NotImplementedError

    def _view_height(self) -> float:
        raise NotImplementedError

    def max_scroll(self) -> float:
        return max(0.0, self._content_height() - self._view_height())

    def _clamp_scroll(self) -> None:
        self.scroll = min(self.max_scroll(), max(0.0, self.scroll))

    def _scroll_into_view(self, top: float, bottom: float) -> None:
        """Scroll just enough that ``[top, bottom)`` (content units) is in view."""
        if top < self.scroll:
            self.scroll = top
        elif bottom > self.scroll + self._view_height():
            self.scroll = bottom - self._view_height()
        self._clamp_scroll()


class ScrollList(Widget, _Scroller):
    """Rows of ``row_height`` (``layouts.list_row_height``) in ``box``; the view is
    ``box.h``. Up/Down move the focused row and return False at the ends, so focus can
    leave the list. Page keys move ``visible_rows − 1`` rows (fully visible rows, G9), Home /
    End go to the ends, and a newly focused row scrolls just into view. A 20-wide scrollbar
    lane exists only while the rows overflow; a track click scrolls the same distance as a
    page key and a thumb drag scrolls proportionally.

    **Variable rows** (F13 contract change 4, architecture review I-1): with ``heights``,
    row ``i`` is ``heights(i)`` tall and the range is Σh − view. ``pitch()`` is the text
    pitch ``p`` (``row_height`` stands in without it): a wheel notch scrolls 3 × (p + 8),
    and page keys, a track click, and the tall-row steps scroll ``view − p``. Up/Down on a
    row taller than the view first scroll by that step until its far edge shows. A row
    newly focused by keys scrolls just into view or, when taller than the view, aligns its
    near edge (Home its top, End its bottom); the pointer never scrolls a tall row. Page
    keys leave focus on an enabled row intersecting the view: the focused row while it
    still does, the far one in view when the list is already at that end. ``rows()`` still
    gives the ``ListRow``s (``enabled`` honoured; labels drawn only without ``draw_row``).
    The row tops are prefix sums, rebuilt when the row count or ``pitch()`` changes.

    ``draw_row(painter, index, box, look)`` draws a row's contents over its frame and
    divider, as ``Grid.draw_cell`` does (no focus marker is drawn for it). ``pitch`` only
    applies with ``heights``; without the new arguments the list is F10's."""

    repeatable = True

    def __init__(self, rows: Callable[[], Sequence[ListRow]], on_activate: Callable[[int], None],
                 *, row_height: float = LIST_ROW_HEIGHT,
                 heights: Callable[[int], float] | None = None,
                 pitch: Callable[[], float] | None = None,
                 draw_row: "Callable[[Painter, int, Box, Look], None] | None" = None,
                 enabled: Callable[[], bool] | None = None, box: Box = _EMPTY_BOX,
                 focusable: bool = True, empty: Callable[[], str] | None = None) -> None:
        super().__init__(enabled=enabled, box=box, focusable=focusable)
        self.rows = rows
        self.on_activate = on_activate
        self.row_height = row_height
        self.heights = heights
        self.pitch = pitch
        self.draw_row = draw_row
        self.empty = empty                     # the empty-list text (``[words] list_empty``)
        self.focus_row = 0
        self.scroll = 0.0
        self.pressed_row: int | None = None
        self._thumb_grab: tuple[float, float] | None = None    # (pointer y, scroll) at grab
        self._tops: list[float] = [0.0]        # variable rows: prefix sums, count + 1 long
        self._tops_key: tuple[int, float] | None = None

    # -- geometry --

    def _row_tops(self) -> list[float]:
        """Variable rows: each row's top in content units, then the total. Rebuilt when the
        row count or ``pitch()`` changes."""
        assert self.heights is not None
        key = (len(self.rows()), self._p())
        if key != self._tops_key:
            height = self.heights
            self._tops = [0.0, *itertools.accumulate(
                max(0.0, float(height(i))) for i in range(key[0]))]
            self._tops_key = key
        return self._tops

    def heights_changed(self) -> None:
        """Variable rows: forget the prefix sums, for heights that changed while the row
        count and ``pitch()`` stayed the same (F13: a full history gaining an entry)."""
        self._tops_key = None

    def _span(self, index: int) -> tuple[float, float]:
        """Row ``index``'s top and bottom in content units (no scroll)."""
        if self.heights is None:
            top = index * self.row_height
            return top, top + self.row_height
        tops = self._row_tops()
        return tops[index], tops[index + 1]

    def _p(self) -> float:
        """Variable rows' text pitch ``p`` (``row_height`` without ``pitch``)."""
        return float(self.pitch()) if self.pitch is not None else float(self.row_height)

    def page_step(self) -> float:
        """How far a page key (variable rows) and a track click scroll."""
        if self.heights is None:
            return max(1, self.visible_rows - 1) * self.row_height
        return max(1.0, self.box.h - self._p())

    def wheel_step(self) -> float:
        """How far one wheel notch scrolls."""
        if self.heights is None:
            return WHEEL_ROWS * self.row_height
        return WHEEL_ROWS * (self._p() + WHEEL_GAP)

    def _content_height(self) -> float:
        if self.heights is not None:
            return self._row_tops()[-1]
        return len(self.rows()) * self.row_height

    def _view_height(self) -> float:
        return self.box.h

    @property
    def visible_rows(self) -> int:
        """Rows fully visible in the view (at least 1)."""
        return max(1, math.floor(self.box.h / self.row_height + 1e-9))

    def overflows(self) -> bool:
        return self._content_height() > self.box.h

    def rows_width(self) -> float:
        return self.box.w - (SCROLLBAR_LANE if self.overflows() else 0)

    def row_box(self, index: int) -> Box:
        """Row ``index`` on the canvas at the current scroll (may lie outside the view)."""
        top, bottom = self._span(index)
        return Box(self.box.x, self.box.y + top - self.scroll, self.rows_width(), bottom - top)

    def visible_range(self) -> range:
        """Indices of the rows that intersect the view (the only ones drawn)."""
        n = len(self.rows())
        if self.heights is not None:
            tops = self._row_tops()
            first = min(n, max(0, bisect.bisect_right(tops, self.scroll) - 1))
            last = bisect.bisect_left(tops, self.scroll + self.box.h, 0, n)
            return range(first, max(first, last))
        first = max(0, math.floor(self.scroll / self.row_height))
        last = min(n, math.ceil((self.scroll + self.box.h) / self.row_height))
        return range(first, max(first, last))

    def lane_box(self) -> Box | None:
        if not self.overflows():
            return None
        return Box(self.box.right - SCROLLBAR_LANE, self.box.y, SCROLLBAR_LANE, self.box.h)

    def thumb_box(self) -> Box | None:
        lane = self.lane_box()
        if lane is None:
            return None
        track = self.box.h
        height = max(SCROLLBAR_MIN_THUMB, self.box.h / self._content_height() * track)
        height = min(height, track)
        top = 0.0 if self.max_scroll() == 0 else self.scroll / self.max_scroll() * (track - height)
        return Box(lane.x, self.box.y + top, lane.w, height)

    def row_at(self, pos: tuple[float, float]) -> int | None:
        px, py = pos
        if not self.box.contains(pos) or px >= self.box.x + self.rows_width():
            return None
        y = py - self.box.y + self.scroll
        if self.heights is not None:
            index = bisect.bisect_right(self._row_tops(), y) - 1
        else:
            index = math.floor(y / self.row_height)
        return index if 0 <= index < len(self.rows()) else None

    # -- state --

    def _sync(self) -> list[ListRow]:
        rows = list(self.rows())
        self.focus_row = min(max(0, self.focus_row), max(0, len(rows) - 1))
        self._clamp_scroll()
        return rows

    def focus_index(self, index: int) -> None:
        """Focus row ``index`` and scroll it just into view (a variable row taller than the
        view aligns its near edge)."""
        self.focus_row = index
        self._reveal(index, "near")

    def _reveal(self, index: int, edge: Literal["near", "top", "bottom", "pointer"]) -> None:
        """Scroll row ``index`` just into view. A variable row taller than the view aligns
        ``edge`` instead: its top, its bottom, the near one (the top when it starts at or
        below the view's top, the bottom when it ends at or above the view's bottom, else no
        scroll), or, for the pointer, nothing."""
        top, bottom = self._span(index)
        view = self.box.h
        if self.heights is None or bottom - top <= view:
            self._scroll_into_view(top, bottom)
            return
        if edge == "near":
            if top >= self.scroll:
                edge = "top"
            elif bottom <= self.scroll + view:
                edge = "bottom"
        if edge == "top":
            self.scroll = top
        elif edge == "bottom":
            self.scroll = bottom - view
        self._clamp_scroll()

    def _step_through(self, d: Nav) -> bool:
        """Up/Down on a focused variable row taller than the view and in view: scroll
        ``view − p`` toward its far edge while that edge is hidden. True = scrolled."""
        top, bottom = self._span(self.focus_row)
        view = self.box.h
        end = self.scroll + view
        if bottom - top <= view or bottom <= self.scroll or top >= end:
            return False
        before = self.scroll
        if d is Nav.DOWN and bottom > end:
            self.scroll = min(self.scroll + self.page_step(), bottom - view)
        elif d is Nav.UP and top < self.scroll:
            self.scroll = max(self.scroll - self.page_step(), top)
        self._clamp_scroll()
        return self.scroll != before

    def _page(self, enabled: list[int], down: bool) -> None:
        """A variable list's page key: scroll ``view − p``, then keep focus on an enabled
        row intersecting the view."""
        before = self.scroll
        self.scroll += self.page_step() if down else -self.page_step()
        self._clamp_scroll()
        usable = set(enabled)
        in_view = [i for i in self.visible_range() if i in usable]
        if not in_view:                        # only disabled rows in view
            target = _nearest(enabled, self.focus_row)
            assert target is not None
            self.focus_index(target)
        elif self.scroll == before:            # already at that end: the far row in view
            self.focus_row = in_view[-1] if down else in_view[0]
        elif self.focus_row not in in_view:
            nearest = _nearest(in_view, self.focus_row)
            assert nearest is not None
            self.focus_row = nearest

    def _nav_variable(self, d: Nav, enabled: list[int], cur: int) -> bool:
        if d in (Nav.UP, Nav.DOWN) and self._step_through(d):
            return True
        edge: Literal["near", "top", "bottom"] = "near"
        if d is Nav.UP:
            target = max((i for i in enabled if i < cur), default=None)
        elif d is Nav.DOWN:
            target = min((i for i in enabled if i > cur), default=None)
        elif d is Nav.HOME:
            target, edge = enabled[0], "top"
        elif d is Nav.END:
            target, edge = enabled[-1], "bottom"
        elif d in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            self._page(enabled, d is Nav.PAGE_DOWN)
            return True
        else:
            return False
        if target is None:
            return False                       # an end: the scope may move focus away
        self.focus_row = target
        self._reveal(target, edge)
        return True

    def _focus_by_pointer(self, index: int) -> None:
        self.focus_row = index
        self._reveal(index, "pointer")

    def on_nav(self, d: Nav) -> bool:
        rows = self._sync()
        enabled = [i for i, row in enumerate(rows) if row.enabled]
        if not enabled:
            return False
        cur = self.focus_row
        if self.heights is not None:
            return self._nav_variable(d, enabled, cur)
        page = max(1, self.visible_rows - 1)
        if d is Nav.UP:
            target = max((i for i in enabled if i < cur), default=None)
        elif d is Nav.DOWN:
            target = min((i for i in enabled if i > cur), default=None)
        elif d is Nav.HOME:
            target = enabled[0]
        elif d is Nav.END:
            target = enabled[-1]
        elif d is Nav.PAGE_UP:
            target = _nearest(enabled, max(0, cur - page))
        elif d is Nav.PAGE_DOWN:
            target = _nearest(enabled, min(len(rows) - 1, cur + page))
        else:
            return False
        if target is None:
            return False                       # an end: the scope may move focus away
        self.focus_index(target)
        return True

    def activate(self) -> None:
        rows = self._sync()
        if self.enabled() and rows and rows[self.focus_row].enabled:
            self.on_activate(self.focus_row)

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        rows = self._sync()
        if not self.enabled():
            return False
        if kind == "wheel":
            before = self.scroll
            self.scroll -= notches * self.wheel_step()
            self._clamp_scroll()
            return self.scroll != before
        if kind == "hover":
            index = self.row_at(pos)
            if index is None or not rows[index].enabled or index == self.focus_row:
                return False
            self._focus_by_pointer(index)
            return True
        if kind == "down":
            return self._press(rows, pos)
        if kind == "drag":
            if self._thumb_grab is None:
                return False
            grab_y, grab_scroll = self._thumb_grab
            thumb = self.thumb_box()
            free = self.box.h - (thumb.h if thumb is not None else 0)
            if free <= 0:
                return False
            self.scroll = grab_scroll + (pos[1] - grab_y) / free * self.max_scroll()
            self._clamp_scroll()
            return True
        if kind == "up":
            self._thumb_grab = None
            return False
        return False

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        pressed, self.pressed_row = self.pressed_row, None
        return pressed is not None and self.enabled() and self.row_at(pos) == pressed

    def row_state(self, index: int, row: ListRow, look: Look) -> LookState:
        """A row's look: disabled rows; the pressed row (mouse) or the focused row pressed by
        keys; the focused row while the list is focused; else normal."""
        if look.state == "disabled" or not row.enabled:
            return "disabled"
        if look.state == "pressed":
            pressed = self.pressed_row
            if pressed is None and self._thumb_grab is None:
                pressed = self.focus_row
            if index == pressed:
                return "pressed"
        if look.state in ("focused", "pressed") and index == self.focus_row:
            return "focused"
        return "normal"

    def draw(self, p: "Painter", look: Look) -> None:
        """Only the rows intersecting the view, clipped to the box: a 1-unit divider below
        each, the focused row in the button's focused look, labels at x 32 (disabled rows
        italic) or ``draw_row``'s contents. The scrollbar lane when rows overflow;
        ``empty()`` centred with no rows."""
        rows = self._sync()
        with clipped(p, self.box):
            if not rows:
                if self.empty is not None:
                    p.text(self.empty(), self.box.center, area="list.empty", anchor="center")
                return
            divider = p.style("list", "normal").color("divider")
            for index in self.visible_range():
                row = rows[index]
                box = self.row_box(index)
                state = self.row_state(index, row, look)
                p.rect(Box(box.x, box.bottom - DIVIDER, box.w, DIVIDER), divider)
                p.widget_frame(box, "list", Look(state), marker=self.draw_row is None)
                if self.draw_row is not None:
                    self.draw_row(p, index, box, Look(state))
                    continue
                p.text(row.label, (box.x + ROW_TEXT_X, box.y + box.h / 2), area="list",
                       state=state, anchor="midleft",
                       max_width=max(1.0, box.w - 2 * ROW_TEXT_X))
            lane = self.lane_box()
            thumb = self.thumb_box()
            if lane is not None and thumb is not None:
                style = p.style("list", "normal")
                x = lane.x + (lane.w - SCROLL_TRACK) / 2
                p.shape(Box(x, lane.y, SCROLL_TRACK, lane.h),
                        FrameSpec(style.color("scrollbar_track"), 1.0,
                                  corner_radius=SCROLL_RADIUS))
                p.shape(Box(x, thumb.y, SCROLL_TRACK, thumb.h),
                        FrameSpec(style.color("scrollbar"), 1.0, corner_radius=SCROLL_RADIUS))

    def _press(self, rows: list[ListRow], pos: tuple[float, float]) -> bool:
        self.pressed_row = None
        self._thumb_grab = None
        lane = self.lane_box()
        if lane is not None and lane.contains(pos):
            thumb = self.thumb_box()
            assert thumb is not None
            page = self.page_step()
            if pos[1] < thumb.y:
                self.scroll -= page
            elif pos[1] >= thumb.bottom:
                self.scroll += page
            else:
                self._thumb_grab = (pos[1], self.scroll)
            self._clamp_scroll()
            return True
        index = self.row_at(pos)
        if index is None or not rows[index].enabled:
            return False
        self._focus_by_pointer(index)
        self.pressed_row = index
        return True


def _nearest(enabled: list[int], index: int) -> int | None:
    """The enabled row closest to ``index`` (the earlier one on a tie)."""
    return min(enabled, key=lambda i: (abs(i - index), i), default=None)


class Grid(Widget, _Scroller):
    """Cells in rows of ``columns``, each ``cell`` (w, h) with ``gap`` between, drawn as
    buttons. Arrows use ``move_target`` over the enabled cells (I-17) and return False at an
    edge. Home / End go to the first / last enabled cell; page keys move by
    ``visible_rows − 1`` rows. Rows beyond the view (``box.h``) scroll as in the list.
    ``draw_cell(painter, index, box, look)`` lets a feature draw a cell's contents.

    ``row_gap`` (F11: 20 between columns, 16 or 8 between rows) defaults to ``gap``. With
    ``tab_cells`` the cells are in the Tab order one by one (F11 "Tab order: sidebar, cells
    1–6, page row"): Tab and Shift+Tab move through the enabled cells and leave the grid
    after the last or before the first."""

    repeatable = True

    def __init__(self, cells: Callable[[], Sequence[GridCell]], columns: int,
                 cell: tuple[int, int], gap: int, on_activate: Callable[[int], None],
                 draw_cell: "Callable[[Painter, int, Box, Look], None] | None" = None, *,
                 enabled: Callable[[], bool] | None = None, box: Box = _EMPTY_BOX,
                 focusable: bool = True, row_gap: int | None = None,
                 tab_cells: bool = False) -> None:
        super().__init__(enabled=enabled, box=box, focusable=focusable)
        if columns < 1:
            raise ValueError("A grid needs at least one column")
        self.cells = cells
        self.columns = columns
        self.cell = cell
        self.gap = gap
        self.row_gap = gap if row_gap is None else row_gap
        self.tab_cells = tab_cells
        self.on_activate = on_activate
        self.draw_cell = draw_cell
        self.focus_cell = 0
        self.scroll = 0.0
        self.pressed_cell: int | None = None

    # -- geometry --

    @property
    def pitch_y(self) -> float:
        return self.cell[1] + self.row_gap

    def row_count(self) -> int:
        return math.ceil(len(self.cells()) / self.columns)

    def _content_height(self) -> float:
        rows = self.row_count()
        return 0.0 if rows == 0 else rows * self.cell[1] + (rows - 1) * self.row_gap

    def _view_height(self) -> float:
        return self.box.h

    @property
    def visible_rows(self) -> int:
        return max(1, math.floor((self.box.h + self.row_gap) / self.pitch_y + 1e-9))

    def layout_box(self, index: int) -> Box:
        """Cell ``index`` relative to the grid's content origin (no scroll)."""
        row, col = divmod(index, self.columns)
        return Box(col * (self.cell[0] + self.gap), row * self.pitch_y, *self.cell)

    def cell_box(self, index: int) -> Box:
        """Cell ``index`` on the canvas at the current scroll."""
        return self.layout_box(index).moved(self.box.x, self.box.y - self.scroll)

    def visible_cells(self) -> list[int]:
        top, bottom = self.box.y, self.box.bottom
        return [i for i in range(len(self.cells()))
                if self.cell_box(i).bottom > top and self.cell_box(i).y < bottom]

    def cell_at(self, pos: tuple[float, float]) -> int | None:
        if not self.box.contains(pos):
            return None
        for index in range(len(self.cells())):
            if self.cell_box(index).contains(pos):
                return index
        return None

    # -- state --

    def _sync(self) -> list[GridCell]:
        cells = list(self.cells())
        enabled = [i for i, c in enumerate(cells) if c.enabled]
        if not (0 <= self.focus_cell < len(cells)) or not cells[self.focus_cell].enabled:
            self.focus_cell = enabled[0] if enabled else 0
        self._clamp_scroll()
        return cells

    def focus_index(self, index: int) -> None:
        self.focus_cell = index
        box = self.layout_box(index)
        self._scroll_into_view(box.y, box.bottom)

    def on_nav(self, d: Nav) -> bool:
        cells = self._sync()
        enabled = [i for i, c in enumerate(cells) if c.enabled]
        if not enabled:
            return False
        cur = self.focus_cell
        target: int | None
        if d in (Nav.UP, Nav.DOWN, Nav.LEFT, Nav.RIGHT):
            others = [i for i in enabled if i != cur]
            hit = move_target(self.layout_box(cur), [self.layout_box(i) for i in others], d)
            target = None if hit is None else others[hit]
        elif d is Nav.HOME:
            target = enabled[0]
        elif d is Nav.END:
            target = enabled[-1]
        elif d in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            rows = max(1, self.visible_rows - 1) * (-1 if d is Nav.PAGE_UP else 1)
            row = min(self.row_count() - 1, max(0, cur // self.columns + rows))
            target = _nearest(enabled, min(len(cells) - 1, row * self.columns
                                           + cur % self.columns))
        elif d in (Nav.NEXT, Nav.PREV) and self.tab_cells:
            if d is Nav.NEXT:
                target = min((i for i in enabled if i > cur), default=None)
            else:
                target = max((i for i in enabled if i < cur), default=None)
        else:
            return False
        if target is None:
            return False
        self.focus_index(target)
        return True

    def tab_entered(self, forward: bool) -> None:
        if not self.tab_cells:
            return
        enabled = [i for i, c in enumerate(self._sync()) if c.enabled]
        if enabled:
            self.focus_index(enabled[0] if forward else enabled[-1])

    def activate(self) -> None:
        cells = self._sync()
        if self.enabled() and cells and cells[self.focus_cell].enabled:
            self.on_activate(self.focus_cell)

    def on_mouse(self, kind: MouseKind, pos: tuple[float, float], *, notches: int = 0) -> bool:
        cells = self._sync()
        if not self.enabled():
            return False
        if kind == "wheel":
            before = self.scroll
            self.scroll -= notches * WHEEL_ROWS * self.pitch_y
            self._clamp_scroll()
            return self.scroll != before
        index = self.cell_at(pos)
        usable = index is not None and cells[index].enabled
        if kind == "hover":
            if not usable or index == self.focus_cell:
                return False
            self.focus_index(index)
            return True
        if kind == "down":
            self.pressed_cell = index if usable else None
            if usable:
                self.focus_index(index)
            return usable
        return False

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        pressed, self.pressed_cell = self.pressed_cell, None
        return pressed is not None and self.enabled() and self.cell_at(pos) == pressed

    def cell_state(self, index: int, cell: GridCell, look: Look) -> LookState:
        if look.state == "disabled" or not cell.enabled:
            return "disabled"
        if look.state == "pressed":
            pressed = self.pressed_cell if self.pressed_cell is not None else self.focus_cell
            if index == pressed:
                return "pressed"
        if look.state in ("focused", "pressed") and index == self.focus_cell:
            return "focused"
        return "normal"

    def draw(self, p: "Painter", look: Look) -> None:
        """Each cell in view as a button (``button`` area), clipped to the box; contents by
        ``draw_cell`` (which drops the marker, 03-ui States) or the cell's label."""
        cells = self._sync()
        with clipped(p, self.box):
            for index in self.visible_cells():
                cell = cells[index]
                box = self.cell_box(index)
                cell_look = Look(self.cell_state(index, cell, look))
                p.widget_frame(box, "button", cell_look, marker=self.draw_cell is None)
                if self.draw_cell is not None:
                    self.draw_cell(p, index, box, cell_look)
                elif cell.label:
                    p.label(cell.label, box, area="button", look=cell_look)
