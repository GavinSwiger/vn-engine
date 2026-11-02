"""``SamplerScreen``: every widget in every state on one screen (dev runs only).

Why this module exists: authors restyling ``[theme.*]`` need to see each widget state at once,
and tests need one place that drives every widget through real input (F10 ``03`` "Dev widget
sampler", UI-F10-12, PR-F10-12, product Q5). It is built only from the public widget classes
(``Button``, ``Toggle``, ``Slider``, ``ScrollList``, ``Grid``) with no private hooks, so what
works here works on every screen. The title and game menu open it with Shift+F3 when the run is
``dev`` (step 6, 7); it is never constructed otherwise.

Layout (canvas units, at 100% text): header at y 24; column A x 40–360 (six static buttons in
the state they name, then "Live button" and "Open confirm"); column B x 400–880 (static
toggles off, on, and disabled, the live toggles "Text 150%" and "Black backdrop", a live
slider 0–100 at 50, a disabled slider); column C x 920–1240 (a 100-row list at y 80–400, a
3×2 grid of 96×80 cells, gap 16, cell 5 disabled). The body (y 72–712) scrolls to keep the
focused widget in view when it is taller (at 150%). The backdrop is white, or black while
"Black backdrop" is on: the contrast worst cases.
"""

from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import button_height, list_row_height, slider_row_height
from engine.ui.input import UiEvent
from engine.ui.menu_screen import MenuScreen, MenuShell
from engine.ui.nav import InputKind
from engine.ui.paint import Painter
from engine.ui.widgets import (
    Button,
    Grid,
    GridCell,
    ListRow,
    Look,
    ScrollList,
    Slider,
    Toggle,
    Widget,
)

TITLE = "Widget sampler (dev)"
HINT = "Esc / B: back"
SAMPLE_MESSAGE = "This is the sample dialog. Yes and No both close it."
HEADER_Y = 24
HEADER_LEFT = 40
HEADER_RIGHT = 1240
BODY_TOP = 72
BODY_BOTTOM = 712
FIRST_ROW = 80
COLUMN_A = (40, 320)
COLUMN_B = (400, 480)
COLUMN_C = (920, 320)
LIST_TOP, LIST_HEIGHT = 80, 320
GRID_TOP = 432
GRID_COLUMNS = 3
GRID_CELL = (96, 80)
GRID_GAP = 16
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


class SamplerScreen(MenuScreen):
    """The dev widget sampler. Opaque; Back closes it; Start and Shift+F3 do nothing (G10)."""

    solid = True

    def __init__(self, shell: MenuShell, *, by: InputKind) -> None:
        assert shell.dev, "the widget sampler exists only in dev runs"
        self.scale = 1.0
        self.black = False
        self.value = 50
        self.live_presses = 0
        self.list_picks: list[int] = []
        self.grid_picks: list[int] = []
        self.confirm_answers: list[str] = []
        self.body_scroll = 0.0
        self.content_bottom = 0.0
        self.base: dict[object, Box] = {}
        self.local_painter = Painter(shell.theme, text_scale=lambda: self.scale)
        words = shell.words

        def state_word(on: bool) -> str:
            return words.get("on" if on else "off")

        def text(label: str):
            return lambda: label

        # Column A: static buttons (drawn in the state they name), then the live ones.
        self.static_normal = Button(text("Normal"), _nothing, focusable=False)
        self.static_focused = Button(text("Focused"), _nothing, focusable=False)
        self.static_pressed = Button(text("Pressed"), _nothing, focusable=False)
        self.static_disabled = Button(text("Disabled"), _nothing, enabled=_never,
                                      focusable=False)
        self.static_on = Button(text("On"), _nothing, on=_always, focusable=False)
        self.static_off = Button(text("Off"), _nothing, on=_never, focusable=False)
        self.live_button = Button(text("Live button"), self.press_live)
        self.open_confirm = Button(text("Open confirm"), self.show_confirm)
        # Column B.
        self.toggle_off = Toggle(text("Toggle off"), _never, _ignore, focusable=False,
                                 state_word=state_word)
        self.toggle_on = Toggle(text("Toggle on"), _always, _ignore, focusable=False,
                                state_word=state_word)
        self.toggle_disabled = Toggle(text("Disabled toggle"), _never, _ignore, enabled=_never,
                                      state_word=state_word)
        self.text_toggle = Toggle(text("Text 150%"), lambda: self.scale > 1.0,
                                  self.set_large_text, state_word=state_word)
        self.black_toggle = Toggle(text("Black backdrop"), lambda: self.black,
                                   self.set_black, state_word=state_word)
        self.slider = Slider(text("Live slider"), 0, 100, lambda: self.value, self.set_value)
        self.slider_disabled = Slider(text("Disabled slider"), 0, 100, lambda: 50, _ignore,
                                      enabled=_never)
        # Column C.
        self.rows = tuple(ListRow(f"Row {i}") for i in range(1, 101))
        self.list = ScrollList(lambda: self.rows, self.list_picks.append,
                               empty=lambda: words.get("list_empty"))
        self.cells = tuple(GridCell(str(i), enabled=i != 5) for i in range(1, 7))
        self.grid = Grid(lambda: self.cells, GRID_COLUMNS, GRID_CELL, GRID_GAP,
                         self.grid_picks.append)
        self.static_looks = {self.static_focused: Look("focused"),
                             self.static_pressed: Look("pressed")}
        super().__init__(shell, by=by, fade=False)

    @property
    def painter(self) -> Painter:
        return self.local_painter

    # -- live widgets --

    def press_live(self) -> None:
        self.live_presses += 1

    def show_confirm(self) -> None:
        self.push_child(ConfirmScreen(
            self.shell, SAMPLE_MESSAGE, lambda: self.confirm_answers.append("yes"),
            lambda: self.confirm_answers.append("no"), by=self.input_kind))

    def set_large_text(self, on: bool) -> None:
        self.scale = 1.5 if on else 1.0
        self.build()

    def set_black(self, on: bool) -> None:
        self.black = on

    def set_value(self, value: int) -> None:
        self.value = value

    # -- layout --

    def build(self) -> None:
        cfg = self.shell.theme.cfg
        s = self.scale
        h = button_height(cfg.button.text_size, scale=s, minimum=cfg.button.height)
        row_h = button_height(cfg.panel.text_size, scale=s, minimum=cfg.button.height)
        slider_h = slider_row_height(cfg.panel.text_size, scale=s)
        gap = cfg.button.gap
        base: dict[object, Box] = {}

        ax, aw = COLUMN_A
        y = FIRST_ROW
        for w in (self.static_normal, self.static_focused, self.static_pressed,
                  self.static_disabled):
            base[w] = Box(ax, y, aw, h)
            y += h + gap
        half = (aw - gap) / 2
        base[self.static_on] = Box(ax, y, half, h)
        base[self.static_off] = Box(ax + half + gap, y, half, h)
        y += h + gap
        for w in (self.live_button, self.open_confirm):
            base[w] = Box(ax, y, aw, h)
            y += h + gap

        bx, bw = COLUMN_B
        y = FIRST_ROW
        for w in (self.toggle_off, self.toggle_on, self.toggle_disabled, self.text_toggle,
                  self.black_toggle):
            base[w] = Box(bx, y, bw, row_h)
            y += row_h + gap
        for w in (self.slider, self.slider_disabled):
            base[w] = Box(bx, y, bw, slider_h)
            y += slider_h + gap

        cx, cw = COLUMN_C
        self.list.row_height = list_row_height(cfg.panel.text_size, scale=s,
                                               minimum=cfg.list.row_height)
        base[self.list] = Box(cx, LIST_TOP, cw, LIST_HEIGHT)
        grid_w = GRID_COLUMNS * GRID_CELL[0] + (GRID_COLUMNS - 1) * GRID_GAP
        grid_h = 2 * GRID_CELL[1] + GRID_GAP
        base[self.grid] = Box(cx, GRID_TOP, grid_w, grid_h)

        self.base = base
        self.content_bottom = max(b.bottom for b in base.values())
        self.scope.set_groups([
            FocusGroup([self.live_button, self.open_confirm], column=True),
            FocusGroup([self.text_toggle, self.black_toggle, self.slider, self.slider_disabled,
                        self.toggle_disabled]),
            FocusGroup([self.list, self.grid]),
            FocusGroup([self.static_normal, self.static_focused, self.static_pressed,
                        self.static_disabled, self.static_on, self.static_off,
                        self.toggle_off, self.toggle_on]),
        ])
        self.scope.default_widget = self.live_button
        self.body_scroll = min(self.body_scroll, self.max_scroll())
        self.place()
        self.list.focus_index(self.list.focus_row)
        self.follow_focus()
        self.revision += 1

    def max_scroll(self) -> float:
        return max(0.0, self.content_bottom - BODY_BOTTOM)

    def place(self) -> None:
        for w, box in self.base.items():
            w.box = box.moved(dy=-self.body_scroll)

    def follow_focus(self) -> None:
        """Scroll the body so the focused widget lies within y 72–712."""
        w = self.scope.focused
        box = self.base.get(w) if w is not None else None
        if box is None:
            return
        scroll = self.body_scroll
        if box.y - scroll < BODY_TOP:
            scroll = box.y - BODY_TOP
        elif box.bottom - scroll > BODY_BOTTOM:
            scroll = box.bottom - BODY_BOTTOM
        scroll = min(self.max_scroll(), max(0.0, scroll))
        if scroll != self.body_scroll:
            self.body_scroll = scroll
            self.place()

    def handle_event(self, event: UiEvent) -> bool:
        consumed = super().handle_event(event)
        if self.shell.stack.top is self:
            self.follow_focus()
        return consumed

    def look_for(self, w: Widget) -> Look:
        forced = self.static_looks.get(w)
        return forced if forced is not None else super().look_for(w)

    # -- drawing --

    def draw_content(self, p: Painter) -> None:
        canvas = p.canvas
        canvas.fill(BLACK if self.black else WHITE)
        p.heading(TITLE, (HEADER_LEFT, HEADER_Y))
        p.text(HINT, (HEADER_RIGHT, HEADER_Y), anchor="topright")
        surface = canvas.surface
        assert surface is not None
        previous = surface.get_clip()
        surface.set_clip(previous.clip(canvas.rect_to_px(
            (0, BODY_TOP, canvas.size[0], BODY_BOTTOM - BODY_TOP))))
        try:
            self.draw_widgets(p)
        finally:
            surface.set_clip(previous)


def _nothing() -> None:
    pass


def _ignore(value: object) -> None:
    pass


def _always() -> bool:
    return True


def _never() -> bool:
    return False


__all__ = ["SamplerScreen"]
