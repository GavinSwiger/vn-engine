"""``ContentWarningScreen``: F33's content warning before the title (F33 ``SPEC.md`` §4,
UI-F33-01, UI-F33-02; ``07-architecture-review.md`` I-1, I-2, I-5, I-9).

Why this module exists: an author's warning ("not suitable for children…") must be read,
or at least passed by an explicit choice, before anything else of the game shows. It is a
``MenuScreen`` (one focus for mouse, keys, and gamepad) that paints the whole canvas:

- **Backdrop**: the title's plain gradient (``title.fill_top_color`` → ``fill_bottom_color``;
  no art, logo, or music).
- **Layout** (``warning_layout``, the one pure function the screen, W193's dev check in
  ``app/content_warning.py``, and the tests share): a ``panel.*`` panel x 120–1160, as tall
  as its contents up to 624 (y 48–672), centred on y 360; padding 48 at the sides, 40 above
  and below; the ``[words] warning_heading`` in ``panel.heading`` tokens, centred; 24 below
  it the body, ``panel.text_size`` in ``ui.text_font``, wrapped at 924 (the scrollbar lane is
  always kept, so lines never rewrap), paragraphs ½ pitch apart; 32 below it the buttons
  Continue (``warning_continue``) and Quit (``quit``), each at least 200 wide, centred as a
  row ``button.gap`` apart.
- **Body**: a ``ScrollList`` with variable rows (F13's form), one row per paragraph, no
  divider, focusable only when it overflows. Focus starts on the body, else on Continue.
- **Continue** looks disabled (``button.disabled.*``) and does nothing (no sound) until
  ``min_seconds`` of the screen's own time after the panel has faded in. Back, Start, and
  Shift+F3 do nothing; the screen never closes by itself. Continue calls ``on_continue``
  (the shell acknowledges, so a "once" warning is stored), fades the whole screen to black
  over ``ui.fade_ms`` taking no input (as the title's ``leave``), then calls ``then``. Quit
  calls ``on_quit`` (``request_quit``; nothing asks first in mode TITLE).
- **Motion**: the panel fades in over the gradient over ``ui.fade_ms``; under reduced
  motion both fades are cuts. New notices wait while it shows (``holds_notices``).

The text is drawn as written: ``{b}`` and ``[`` are plain characters (config's validator
already refused every control character except ``\\n``).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.render.frames import FrameSpec, to_black
from engine.ui.builtin.title_screen import draw_title_gradient
from engine.ui.focus import Box, FocusGroup
from engine.ui.input import UiEvent
from engine.ui.layouts import (
    CANVAS_H,
    CANVAS_W,
    SCROLLBAR_LANE,
    Measure,
    button_height,
    pitch,
    scaled,
    wrap_text,
)
from engine.ui.menu_screen import MenuScreen, MenuShell, Phase
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import HEADING_AREA
from engine.ui.theme import measure_with
from engine.ui.widgets import SCROLL_RADIUS, SCROLL_TRACK, Button, ListRow, Look, ScrollList, \
    clipped

if TYPE_CHECKING:
    from engine.core.config_schema import ThemeConfig
    from engine.render.canvas import Canvas
    from engine.ui.paint import Painter
    from engine.ui.theme import UiTheme, Words

PANEL_W: Final = 1040
PANEL_X: Final = (CANVAS_W - PANEL_W) // 2          # 120
PANEL_MAX_H: Final = 624                             # y 48–672 at most
PAD_X: Final = 48
PAD_Y: Final = 40
HEADING_GAP: Final = 24                              # heading → body
BUTTONS_GAP: Final = 32                              # body → buttons
BUTTON_MIN_W: Final = 200
WRAP_WIDTH: Final = PANEL_W - 2 * PAD_X - SCROLLBAR_LANE      # 924
LARGE_TEXT_PCT: Final = 150                          # W193 checks the largest text size
_EPSILON: Final = 1e-9


def warning_paragraphs(text: str) -> tuple[str, ...]:
    """SR-F33-01: one or more blank lines (empty or only spaces) separate paragraphs; a
    single ``\\n`` breaks a line inside one; leading and trailing blank lines are dropped."""
    paragraphs: list[str] = []
    lines: list[str] = []
    for line in text.split("\n"):
        if line.strip():
            lines.append(line)
        elif lines:
            paragraphs.append("\n".join(lines))
            lines = []
    if lines:
        paragraphs.append("\n".join(lines))
    return tuple(paragraphs)


@dataclass(frozen=True)
class WarningLayout:
    """``warning_layout``'s result, in canvas units. ``rows`` are the wrapped lines of each
    paragraph and ``heights`` each paragraph row's height (its lines × ``pitch``, plus
    ``gap`` below every row but the last). ``body`` is the list's box (the 924 text width
    and the 20-wide lane); its height is the content height, or ``room`` when the content
    overflows. ``lines_needed`` = ⌈content ÷ pitch⌉, ``lines_fit`` = ⌊room ÷ pitch⌋."""

    panel: Box
    heading_y: float                 # the heading's midtop y (x: the panel's centre)
    heading_size: int
    body: Box
    body_size: int
    pitch: int
    gap: int
    rows: tuple[tuple[str, ...], ...]
    heights: tuple[int, ...]
    content_h: int
    room: int
    overflow: bool
    continue_: Box
    quit: Box
    lines_needed: int
    lines_fit: int
    chars: int                       # the paragraphs' characters (line breaks not counted)

    @property
    def chars_fit(self) -> int:
        """About how many characters fit without scrolling (W193), rounded down to tens."""
        if self.lines_needed <= 0:
            return 0
        return self.chars * self.lines_fit // self.lines_needed // 10 * 10


def warning_layout(text: str, measure: Measure, *, scale: float = 1.0,
                   panel_text_size: int = 28, heading_text_size: int = 32,
                   button_text_size: int = 28, button_min_height: int = 56,
                   button_gap: int = 12, button_side_padding: int = 32,
                   continue_label_width: float = 0.0,
                   quit_label_width: float = 0.0) -> WarningLayout:
    """UI-F33-01 for ``text`` at F16's text ``scale``. Sizes are theme token values
    (unscaled); ``measure(text, size)`` gives the body face's width; the label widths are
    the two buttons' labels at their scaled size."""
    body_size = scaled(panel_text_size, scale)
    p = pitch(body_size)
    gap = round(p / 2)
    heading_size = scaled(heading_text_size, scale)
    heading_h = pitch(heading_size)
    h_b = button_height(button_text_size, scale=scale, minimum=button_min_height)
    rows = tuple(tuple(wrap_text(paragraph, WRAP_WIDTH, body_size, measure))
                 for paragraph in warning_paragraphs(text))
    heights = tuple(len(lines) * p + (gap if i < len(rows) - 1 else 0)
                    for i, lines in enumerate(rows))
    content_h = sum(heights)
    fixed = PAD_Y + heading_h + HEADING_GAP + BUTTONS_GAP + h_b + PAD_Y
    room = max(0, PANEL_MAX_H - fixed)
    overflow = content_h > room
    body_h = room if overflow else content_h
    panel_h = fixed + body_h
    panel = Box(PANEL_X, CANVAS_H / 2 - panel_h / 2, PANEL_W, panel_h)
    heading_y = panel.y + PAD_Y
    body = Box(panel.x + PAD_X, heading_y + heading_h + HEADING_GAP,
               PANEL_W - 2 * PAD_X, body_h)
    inner = PANEL_W - 2 * PAD_X
    widest = (inner - button_gap) / 2
    widths = [min(widest, max(BUTTON_MIN_W, label + 2 * button_side_padding))
              for label in (continue_label_width, quit_label_width)]
    row_y = body.bottom + BUTTONS_GAP
    left = panel.x + PANEL_W / 2 - (widths[0] + button_gap + widths[1]) / 2
    continue_ = Box(left, row_y, widths[0], h_b)
    quit_ = Box(left + widths[0] + button_gap, row_y, widths[1], h_b)
    return WarningLayout(
        panel=panel, heading_y=heading_y, heading_size=heading_size, body=body,
        body_size=body_size, pitch=p, gap=gap, rows=rows, heights=heights,
        content_h=content_h, room=room, overflow=overflow, continue_=continue_, quit=quit_,
        lines_needed=math.ceil(content_h / p - _EPSILON) if p else 0,
        lines_fit=room // p if p else 0,
        chars=sum(len(line) for lines in rows for line in lines))


def themed_warning_layout(text: str, theme: "UiTheme", words: "Words", assets, *,
                          scale: float) -> WarningLayout:
    """``warning_layout`` with the theme's tokens and fonts and the two button words (the
    screen's ``build`` and W193)."""
    cfg: ThemeConfig = theme.cfg
    body_size = scaled(cfg.panel.text_size, scale)
    label_size = scaled(cfg.button.text_size, scale)
    label = measure_with(assets, theme.font(label_size))
    return warning_layout(
        text, measure_with(assets, theme.font(body_size)), scale=scale,
        panel_text_size=cfg.panel.text_size, heading_text_size=cfg.panel.heading.text_size,
        button_text_size=cfg.button.text_size, button_min_height=cfg.button.height,
        button_gap=cfg.button.gap, button_side_padding=cfg.button.side_padding,
        continue_label_width=label(words.get("warning_continue"), label_size),
        quit_label_width=label(words.get("quit"), label_size))


class WarningBody(ScrollList):
    """The body: F13's variable-row ``ScrollList`` drawn without dividers (UI-F33-02)."""

    def draw(self, p: "Painter", look: Look) -> None:
        rows = self._sync()
        draw_row = self.draw_row
        with clipped(p, self.box):
            for index in self.visible_range():
                box = self.row_box(index)
                state = self.row_state(index, rows[index], look)
                p.widget_frame(box, "list", Look(state), marker=False)
                if draw_row is not None:
                    draw_row(p, index, box, Look(state))
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


class WaitButton(Button):
    """Continue: focusable at once (so focus can rest on it), but drawn disabled and doing
    nothing, with no sound, until ``ready()``."""

    def __init__(self, label: Callable[[], str], action: Callable[[], None], *,
                 ready: Callable[[], bool]) -> None:
        super().__init__(label, action)
        self.ready = ready

    def look(self, *, focused: bool, pressed: bool = False) -> Look:
        if not self.ready():
            return Look("disabled")
        return super().look(focused=focused, pressed=pressed)

    def activate(self) -> None:
        if self.ready():
            super().activate()

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        return self.ready() and super().accepts_click(pos)


class ContentWarningScreen(MenuScreen):
    """The warning. Opaque (it paints the gradient); never ``in_game``, so the story holds;
    ``holds_notices`` while it shows. ``then`` runs once the screen has faded to black after
    Continue (the shell's next pre-title step, then the title or the game)."""

    holds_notices = True

    def __init__(self, shell: MenuShell, *, text: str, min_seconds: float,
                 on_continue: Callable[[], None], on_quit: Callable[[], None],
                 then: Callable[[], None]) -> None:
        self.text = text
        self.min_seconds = max(0.0, float(min_seconds))
        self.wait_left = self.min_seconds
        self.on_continue = on_continue
        self.on_quit = on_quit
        self.then = then
        self.layout: WarningLayout | None = None
        self._rows: list[ListRow] = []
        self.body = WarningBody(lambda: self._rows, lambda index: None,
                                heights=self._row_height,
                                pitch=lambda: float(self.layout.pitch if self.layout else 1),
                                draw_row=self._draw_row)
        words = shell.words
        self.continue_button = WaitButton(lambda: words.get("warning_continue"),
                                          self._continue, ready=lambda: self.ready)
        self.quit_button = Button(lambda: words.get("quit"), self._quit)
        self.leaving = False
        self.out_s = 0.0
        self.out_t = 0.0
        self._out_fresh = False
        super().__init__(shell, by=InputKind.KEYS, fade=True)

    # -- state --

    @property
    def opaque(self) -> bool:                                     # type: ignore[override]
        return True

    @property
    def ready(self) -> bool:
        """Continue works: the panel is fully in and ``min_seconds`` have passed since."""
        return self.phase is Phase.OPEN and self.wait_left <= _EPSILON and not self.leaving

    # -- layout --

    def build(self) -> None:
        shell = self.shell
        layout = themed_warning_layout(self.text, shell.theme, shell.words, shell.assets,
                                       scale=self.painter.text_scale())
        self.layout = layout
        body = self.body
        body.box = layout.body
        body.focusable = layout.overflow
        if len(self._rows) != len(layout.rows):
            self._rows = [ListRow("")] * len(layout.rows)
        body.heights_changed()
        body.scroll = min(body.scroll, body.max_scroll())
        self.continue_button.box = layout.continue_
        self.quit_button.box = layout.quit
        self.scope.set_groups([FocusGroup([body]),
                               FocusGroup([self.continue_button, self.quit_button])])
        self.scope.default_widget = body if layout.overflow else self.continue_button
        self.scope.on_edge = self._edge
        if self.built and not self.scope.can_focus(self.scope.focused):
            self.scope.focus(self.scope.default_widget, InputKind.KEYS, sound=False,
                             visible=self.scope.visible)
        self.revision += 1

    def _edge(self, d: Nav, group: FocusGroup) -> bool:
        """Down at the body's end goes to Continue; Up from a button goes to the body."""
        if self.body in group:
            target = self.continue_button if d is Nav.DOWN else None
        else:
            target = self.body if d is Nav.UP else None
        if target is None or not self.scope.can_focus(target):
            return False
        return self.scope.focus(target, InputKind.KEYS)

    def _row_height(self, index: int) -> float:
        layout = self.layout
        return float(layout.heights[index]) if layout is not None else 0.0

    def layer_box(self) -> Box:
        assert self.layout is not None
        return self.layout.panel

    # -- actions --

    def _continue(self) -> None:
        if self.leaving or not self.ready:
            return
        self.on_continue()
        self.leaving = True
        self.repeat.stop()
        self.pressed = None
        seconds = 0.0 if self.shell.reduce_motion else self.shell.theme.cfg.ui.fade_ms / 1000.0
        self.out_s = seconds
        self._out_fresh = True
        if seconds <= 0:
            self._finish_leave()

    def _finish_leave(self) -> None:
        self.out_t = 1.0
        then, self.then = self.then, None                        # type: ignore[assignment]
        if then is not None:
            then()

    def _quit(self) -> None:
        if not self.leaving:
            self.on_quit()

    def back(self) -> None:
        """Back does nothing: only a button leaves (PR-F33-04)."""

    # -- input --

    def handle_event(self, event: UiEvent) -> bool:
        if self.leaving:
            return True                                  # no input while it fades out
        return super().handle_event(event)

    def _on_nav(self, nav: Nav) -> None:
        if nav in (Nav.BACK, Nav.START, Nav.SAMPLER):
            return                                       # nothing, and no Back sound
        if (nav is Nav.ACTIVATE and self.scope.focused is self.continue_button
                and not self.ready):
            return                                       # a press before it is ready: nothing
        super()._on_nav(nav)

    # -- frame --

    def update(self, dt: float, *, is_top: bool) -> None:
        if self.leaving:
            fresh, self._out_fresh = self._out_fresh, False
            if not fresh and self.then is not None and self.out_s > 0:
                self.out_t = min(1.0, self.out_t + dt / self.out_s)
                if self.out_t >= 1.0 - _EPSILON:
                    self._finish_leave()
            return
        was_open = self.phase is Phase.OPEN
        super().update(dt, is_top=is_top)
        if is_top and was_open and self.wait_left > 0:
            self.wait_left = max(0.0, self.wait_left - dt)

    def draw(self, canvas: "Canvas") -> None:
        assert self.built and self.layout is not None
        p = self.painter
        p.bind(canvas)
        draw_title_gradient(canvas, self.shell.theme.cfg.title)
        surface = canvas.surface
        assert surface is not None
        a = self.alpha
        if a >= 1.0:
            self._layer = None
            self.draw_content(p)
        else:
            rect = self._compose(canvas, p, surface, False)
            if rect is not None and self._layer is not None:
                self._layer.set_alpha(round(255 * a))
                surface.blit(self._layer, rect.topleft)
        if self.out_t > 0:
            to_black(surface, self.out_t)

    def draw_content(self, p: "Painter") -> None:
        layout = self.layout
        assert layout is not None
        p.panel(layout.panel)
        p.text(self.shell.words.get("warning_heading"),
               (layout.panel.x + layout.panel.w / 2, layout.heading_y), area=HEADING_AREA,
               anchor="midtop", max_width=layout.panel.w - 2 * PAD_X)
        self.draw_widgets(p)

    def _draw_row(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        layout = self.layout
        assert layout is not None
        theme = self.shell.theme
        font = theme.font(layout.body_size)
        color = theme.cfg.panel.text_color
        pt = layout.pitch
        for i, line in enumerate(layout.rows[index]):
            if line:
                p.canvas.draw_text(line, font, color, (box.x, box.y + i * pt + pt / 2),
                                   anchor="midleft")


__all__ = ["BUTTONS_GAP", "BUTTON_MIN_W", "ContentWarningScreen", "HEADING_GAP",
           "LARGE_TEXT_PCT", "PAD_X", "PAD_Y", "PANEL_MAX_H", "PANEL_W", "PANEL_X",
           "WRAP_WIDTH", "WaitButton", "WarningBody", "WarningLayout",
           "themed_warning_layout", "warning_layout", "warning_paragraphs"]
