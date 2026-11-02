"""The shared page row (F11 step 9; F21 ``07`` I-1): ``ui/page_row.PageRow`` over
``layouts.page_row_layout`` with its placement parameter. AC-F11-39's numbers stay
``test_save_layout``'s; here: the placement, the widget's keys, mouse, Tab parts, look, and
AC-F21-26's tab-overflow row (D6). M20 metrics: 20 units per character at 28."""

import pygame
import pytest

from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.ui.focus import Box, FocusGroup, FocusScope
from engine.ui.layouts import (PAGE_ROW_BOTTOM, PAGE_ROW_PLACEMENT, RowPlacement,
                               page_row_layout)
from engine.ui.nav import InputKind, Nav
from engine.ui.page_row import PageRow
from engine.ui.paint import Painter
from engine.ui.theme import plain_theme
from engine.ui.widgets import Look
from tests.render.conftest import make_assets
from tests.ui.test_save_layout import load_labels, m20, save_labels


class Pages:
    """An owner: the labels, the current index, and the selections it got."""

    def __init__(self, labels, current: int = 0, *, fixed: int = 0, **kwargs) -> None:
        self.labels = list(labels)
        self.current = current
        self.selected: list[int] = []
        self.row = PageRow(lambda: self.labels, lambda: self.current, self.select,
                           fixed=fixed, measure=m20, **kwargs)

    def select(self, index: int) -> None:
        self.selected.append(index)
        self.current = index

    def kinds(self) -> list[tuple]:
        return [(b.kind, b.page) for b in self.row.layout().buttons]

    def focused(self) -> tuple:
        b = self.row.focused_button()
        return (b.kind, b.page)


# --- Placement (F21 07 I-1): F11's midbottom stays the default -------------------------------

def test_default_placement_is_f11s_midbottom():
    assert PAGE_ROW_PLACEMENT == RowPlacement("midbottom", PAGE_ROW_BOTTOM)
    default = page_row_layout(load_labels(10), 0, m20)
    same = page_row_layout(load_labels(10), 0, m20, placement=RowPlacement())
    assert default == same
    bounds = default.bounds
    assert (bounds.x + bounds.w / 2, bounds.bottom) == PAGE_ROW_BOTTOM
    assert Pages(load_labels(10), fixed=2).row.box == bounds


@pytest.mark.parametrize("anchor, point, topleft", [
    ("topleft", (416, 112), (416, 112)),
    ("bottomleft", (416, 664), (416, 608)),
    ("midtop", (820, 112), None),
])
def test_other_placements(anchor, point, topleft):
    layout = page_row_layout(save_labels(3), 0, m20, placement=RowPlacement(anchor, point))
    bounds = layout.bounds
    if topleft is not None:
        assert (bounds.x, bounds.y) == topleft
    else:
        assert (bounds.x + bounds.w / 2, bounds.y) == point
    assert bounds.h == 56


# --- AC-F21-26 D6: tab overflow ---------------------------------------------------------------

def test_d6_tab_overflow_arrows_window_and_disabled_first_arrow():
    labels = ["W" * 24 for _ in range(24)]
    pages = Pages(labels, width=808)
    layout = pages.row.layout()
    assert layout.arrows and layout.buttons[0].kind == "prev" and layout.buttons[-1].kind == "next"
    for current in (0, 7, 23):
        pages.current = current
        assert current in pages.row.layout().pages
    pages.current = 0
    assert not pages.row.layout().prev_enabled
    assert pages.focused() == ("page", 0)
    assert pages.row.on_nav(Nav.LEFT) is False              # ◀ is skipped: focus leaves
    assert pages.row.on_nav(Nav.RIGHT) and pages.focused() == ("next", None)
    pages.row.tab_entered(True)
    assert pages.focused() == ("page", 0)                   # Tab never lands on ◀ either


# --- Keys ---------------------------------------------------------------------------------------

def test_left_right_move_and_stop_at_the_ends():
    pages = Pages(save_labels(3))
    assert pages.focused() == ("page", 0)
    assert pages.row.on_nav(Nav.RIGHT) and pages.focused() == ("page", 1)
    assert pages.row.on_nav(Nav.RIGHT) and pages.focused() == ("page", 2)
    assert pages.row.on_nav(Nav.RIGHT) is False
    assert pages.row.on_nav(Nav.UP) is False and pages.row.on_nav(Nav.HOME) is False
    pages.row.activate()
    assert pages.selected == [2] and pages.focused() == ("page", 2)


def test_activating_an_arrow_steps_one_page_and_keeps_focus_until_disabled():
    pages = Pages(load_labels(100), 2, fixed=2)
    assert pages.kinds()[0] == ("prev", None) and pages.kinds()[1:3] == [("page", 0), ("page", 1)]
    pages.row.focus_button(("next", None))
    pages.row.activate()
    assert pages.selected == [3] and pages.focused() == ("next", None)
    assert 3 in pages.row.layout().pages
    pages.current = 101                                     # the last page: ▶ disabled
    pages.row.focus_button(("next", None))
    assert pages.focused() == ("page", 101)                 # focus never rests on it
    assert pages.row.on_nav(Nav.RIGHT) is False
    pages.row.focus_button(("prev", None))
    pages.current = 1
    pages.row.activate()
    assert pages.selected[-1] == 0                          # Quick → Auto, never wraps
    assert pages.focused() == ("page", 0)                   # ◀ is disabled on the first page


def test_current_changed_moves_a_focused_page_button_only():
    pages = Pages(save_labels(10), 2)
    pages.row.focus_button(("page", 2))
    pages.current = 3
    pages.row.current_changed()
    assert pages.focused() == ("page", 3)


def test_tab_parts_in_a_scope():
    pages = Pages(save_labels(3))
    other = PageRow(lambda: ["a"], lambda: 0, lambda i: None, measure=m20,
                    placement=RowPlacement("topleft", (0, 0)))
    scope = FocusScope([FocusGroup([other, pages.row])])
    scope.focus(other, InputKind.KEYS)
    assert scope.press(Nav.NEXT) and scope.focused is pages.row
    assert pages.focused() == ("page", 0)
    assert scope.press(Nav.NEXT) and pages.focused() == ("page", 1)
    assert scope.press(Nav.NEXT) and pages.focused() == ("page", 2)
    assert scope.press(Nav.NEXT) and scope.focused is other
    assert scope.press(Nav.PREV) and scope.focused is pages.row
    assert pages.focused() == ("page", 2)


# --- Mouse ---------------------------------------------------------------------------------------

def test_hover_focuses_and_a_click_acts_on_the_pressed_button():
    pages = Pages(save_labels(3))
    b1, b2 = pages.row.layout().buttons[1], pages.row.layout().buttons[2]
    assert pages.row.on_mouse("hover", b1.box.center) and pages.focused() == ("page", 1)
    assert pages.row.on_mouse("down", b2.box.center)
    assert pages.row.accepts_click(b1.box.center) is False   # released elsewhere
    assert pages.selected == []
    pages.row.on_mouse("down", b2.box.center)
    assert pages.row.accepts_click(b2.box.center)
    pages.row.activate()
    assert pages.selected == [2]


def test_a_disabled_arrow_takes_no_hover_or_press():
    pages = Pages(load_labels(100), 0, fixed=2)
    prev = pages.row.layout().buttons[0]
    assert prev.kind == "prev"
    assert pages.row.on_mouse("hover", prev.box.center) is False
    assert pages.row.on_mouse("down", prev.box.center) is False
    assert pages.row.accepts_click(prev.box.center) is False


# --- Look ----------------------------------------------------------------------------------------

def _draw(pages: Pages, look: Look) -> pygame.Surface:
    theme = plain_theme()
    canvas = Canvas(make_assets(None))
    surface = pygame.Surface((1280, 720))
    surface.fill((0, 0, 0))
    canvas.bind(surface, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
    painter = Painter(theme)
    painter.bind(canvas)
    pages.row.draw(painter, look)
    return surface


def test_states_bar_on_the_current_page_and_disabled_arrow():
    pygame.init()
    pages = Pages(load_labels(100), 0, fixed=2)
    cfg = plain_theme().cfg
    row = pages.row
    assert row.button_state(row.layout().buttons[0], Look("focused")) == "disabled"
    assert row.button_state(row.layout().buttons[1], Look("focused")) == "focused"
    assert row.button_state(row.layout().buttons[1], Look("pressed")) == "pressed"
    assert row.button_state(row.layout().buttons[2], Look("focused")) == "normal"
    surface = _draw(pages, Look("normal"))
    auto = row.layout().buttons[1].box
    bar = tuple(surface.get_at((int(auto.x) + 6, int(auto.center[1]))))[:3]
    assert bar == tuple(cfg.button.marker.fill_color)        # the selected page's bar
    quick = row.layout().buttons[2].box
    assert tuple(surface.get_at((int(quick.x) + 6, int(quick.center[1]))))[:3] != bar
    marker_x = int(auto.x) + 14                              # no focus marker when focused
    surface = _draw(pages, Look("focused"))
    assert tuple(surface.get_at((marker_x, int(auto.center[1]))))[:3] != \
        tuple(cfg.button.marker.fill_color)
    assert row.box == Box(row.layout().bounds.x, 608, row.layout().width, 56)
