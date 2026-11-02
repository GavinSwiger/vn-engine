"""Widget state and behaviour (F10 ``04`` §7.4), headless: the unit rows of AC-F10-10 to 14
on widgets placed as in the sampler. Drawing (and the draw-spy rows) comes with the painter
in step 4."""

import pygame
import pytest

from engine.ui.focus import Box, FocusGroup, FocusScope
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button, Grid, GridCell, ListRow, Look, ScrollList, Slider, Toggle


class Value:
    """A get/set pair that records ``set`` calls."""

    def __init__(self, value):
        self.value = value
        self.calls = []

    def get(self):
        return self.value

    def set(self, value):
        self.calls.append(value)
        self.value = value


def flag(value: bool = True):
    state = {"on": value}
    return state, (lambda: state["on"])


# --- Button and Look ---------------------------------------------------------------------

def test_button_activates_only_when_enabled():
    hits = []
    state, enabled = flag()
    button = Button(lambda: "Go", lambda: hits.append(1), enabled=enabled)
    button.activate()
    state["on"] = False
    button.activate()
    assert hits == [1]
    assert not button.on_nav(Nav.LEFT) and not button.repeatable


@pytest.mark.parametrize(("enabled", "focused", "pressed", "state"), [
    (True, False, False, "normal"), (True, True, False, "focused"),
    (True, True, True, "pressed"), (True, False, True, "pressed"),
    (False, True, True, "disabled"),
])
def test_look_states(enabled, focused, pressed, state):
    button = Button(lambda: "B", lambda: None, enabled=lambda: enabled)
    assert button.look(focused=focused, pressed=pressed) == Look(state, None, False)


def test_on_off_and_selected_looks():
    on = Button(lambda: "Skip", lambda: None, on=lambda: True, selected=lambda: True)
    off = Button(lambda: "Skip", lambda: None, on=lambda: False)
    assert on.look(focused=False) == Look("normal", True, True)
    assert off.look(focused=True) == Look("focused", False, False)


def test_click_lands_inside_the_box_only():
    button = Button(lambda: "B", lambda: None, box=Box(40, 80, 320, 56))
    assert button.accepts_click((50, 100))
    assert not button.accepts_click((400, 100))
    button.enabled = lambda: False
    assert not button.accepts_click((50, 100))


# --- Toggle (AC-F10-10) ------------------------------------------------------------------

def toggle(on: bool = False, enabled: bool = True):
    value = Value(on)
    return Toggle(lambda: "Black backdrop", value.get, value.set,
                  enabled=lambda: enabled, box=Box(400, 300, 480, 56)), value


def test_toggle_activate_flips():
    widget, value = toggle()
    widget.activate()
    widget.activate()
    assert value.calls == [True, False]
    assert widget.look(focused=True).on is False


@pytest.mark.parametrize(("start", "d", "calls"), [
    (False, Nav.RIGHT, [True]), (True, Nav.RIGHT, []),
    (True, Nav.LEFT, [False]), (False, Nav.LEFT, []),
])
def test_toggle_left_right_consumed(start, d, calls):
    widget, value = toggle(start)
    assert widget.on_nav(d) is True            # focus never leaves a focused toggle
    assert value.calls == calls


def test_toggle_up_down_not_consumed():
    widget, _ = toggle()
    assert not widget.on_nav(Nav.UP) and not widget.on_nav(Nav.DOWN)


def test_disabled_toggle_never_sets_nor_takes_focus():
    widget, value = toggle(enabled=False)
    widget.activate()
    widget.on_nav(Nav.RIGHT)
    assert value.calls == []
    assert not widget.accepts_click((500, 320))
    other = Button(lambda: "x", lambda: None, box=Box(400, 200, 480, 56))
    scope = FocusScope([FocusGroup([other, widget])])
    scope.focus(other, InputKind.KEYS)
    assert not scope.tab(True) and scope.focused is other


# --- Slider (AC-F10-11) ------------------------------------------------------------------

def slider(start: int = 50, enabled: bool = True):
    value = Value(start)
    widget = Slider(lambda: "Live slider", 0, 100, value.get, value.set,
                    enabled=lambda: enabled, box=Box(400, 400, 480, 91))
    return widget, value


def test_slider_bar_span():
    widget, _ = slider()
    assert widget.bar_span() == (432, 776)
    assert widget.thumb_x() == 604


@pytest.mark.parametrize(("start", "keys", "value", "calls"), [
    (50, [Nav.RIGHT], 55, [55]),
    (50, [Nav.LEFT, Nav.LEFT], 40, [45, 40]),
    (50, [Nav.HOME, Nav.LEFT], 0, [0]),
    (50, [Nav.END, Nav.RIGHT], 100, [100]),
])
def test_slider_keys(start, keys, value, calls):
    widget, val = slider(start)
    for d in keys:
        assert widget.on_nav(d) is True
    assert val.value == value and val.calls == calls


def test_slider_up_down_move_focus():
    widget, _ = slider()
    assert not widget.on_nav(Nav.UP) and not widget.on_nav(Nav.DOWN)
    assert widget.repeatable


@pytest.mark.parametrize(("x", "value", "calls"), [
    (604, 50, []), (518, 25, [25]), (450, 5, [5]), (420, 0, [0]),
])
def test_slider_press_jumps(x, value, calls):
    widget, val = slider()
    assert widget.on_mouse("down", (x, 450))
    assert val.value == value and val.calls == calls
    assert not widget.accepts_click((x, 450))  # a release never activates a slider


def test_slider_drag():
    widget, val = slider()
    widget.on_mouse("down", (518, 450))
    assert val.value == 25
    widget.on_mouse("drag", (690, 450))
    assert val.value == 75
    widget.on_mouse("up", (690, 450))
    widget.on_mouse("drag", (518, 450))        # no longer pressed
    assert val.calls == [25, 75]
    widget.on_mouse("down", (518, 450))
    widget.on_mouse("drag", (900, 450))
    assert val.value == 100


def test_disabled_slider_unchanged():
    widget, val = slider(enabled=False)
    for d in (Nav.RIGHT, Nav.LEFT, Nav.HOME, Nav.END):
        widget.on_nav(d)
    widget.on_mouse("down", (518, 450))
    widget.on_mouse("drag", (690, 450))
    assert val.calls == [] and val.value == 50


@pytest.mark.parametrize(("lo", "hi", "step"), [
    (0, 100, 5), (0, 10, 1), (0, 30, 2), (0, 1000, 50), (-50, 50, 5),
])
def test_slider_step(lo, hi, step):
    assert Slider(lambda: "s", lo, hi, lambda: lo, lambda v: None).step == step


def test_slider_rejects_empty_range():
    with pytest.raises(ValueError):
        Slider(lambda: "s", 5, 4, lambda: 5, lambda v: None)


# --- ScrollList (AC-F10-12, 13) ----------------------------------------------------------

LIST_BOX = Box(920, 80, 320, 320)


def scroll_list(n: int = 100):
    activated = []
    rows = [ListRow(f"Row {i + 1}") for i in range(n)]
    widget = ScrollList(lambda: rows, activated.append, box=LIST_BOX)
    return widget, activated


def press(widget, *keys):
    for d in keys:
        widget.on_nav(d)


@pytest.mark.parametrize(("keys", "row", "scroll"), [
    ([Nav.DOWN] * 6, 7, 16),
    ([Nav.DOWN] * 6 + [Nav.UP] * 6, 1, 0),
    ([Nav.PAGE_DOWN], 6, 0),
    ([Nav.PAGE_DOWN] * 2, 11, 208),
    ([Nav.END], 100, 4480),
    ([Nav.END, Nav.HOME], 1, 0),
    ([Nav.PAGE_DOWN] * 2 + [Nav.PAGE_UP], 6, 208),
])
def test_list_keys(keys, row, scroll):
    widget, _ = scroll_list()
    press(widget, *keys)
    assert widget.focus_row + 1 == row
    assert widget.scroll == scroll


def test_list_visible_rows_are_fully_visible_rows():
    widget, _ = scroll_list()
    assert widget.visible_rows == 6


def test_list_ends_return_false():
    widget, _ = scroll_list()
    assert widget.on_nav(Nav.UP) is False and widget.focus_row == 0 and widget.scroll == 0
    press(widget, Nav.END)
    assert widget.on_nav(Nav.DOWN) is False and widget.focus_row == 99
    assert widget.scroll == 4480


def test_list_down_at_the_end_leaves_to_the_widget_below():
    widget, _ = scroll_list()
    grid = Grid(lambda: [GridCell()] * 6, 3, (96, 80), 16, lambda i: None,
                box=Box(920, 432, 320, 176))
    scope = FocusScope([FocusGroup([widget, grid])])
    scope.focus(widget, InputKind.KEYS)
    press(widget, Nav.END)
    assert scope.move(Nav.DOWN) and scope.focused is grid
    assert widget.scroll == 4480


def test_list_activate():
    widget, activated = scroll_list()
    press(widget, Nav.DOWN, Nav.DOWN)
    widget.activate()
    assert activated == [2]


def test_list_draws_only_rows_in_view():
    widget, _ = scroll_list()
    press(widget, *[Nav.DOWN] * 6)
    assert widget.scroll == 16
    assert list(widget.visible_range()) == list(range(7))     # Row 1 .. Row 7
    assert widget.row_box(6) == Box(920, 80 + 6 * 48 - 16, 300, 48)


@pytest.mark.parametrize(("notches", "scroll"), [(-1, 144), (-2, 288), (1, 0), (-40, 4480)])
def test_list_wheel(notches, scroll):
    widget, _ = scroll_list()
    widget.on_mouse("wheel", (1000, 200), notches=notches)
    assert widget.scroll == scroll
    assert widget.focus_row == 0


def test_list_click_activates_at_the_up_on_the_same_row():
    widget, activated = scroll_list()
    row3 = (1000, 80 + 2 * 48 + 10)
    row4 = (1000, 80 + 3 * 48 + 10)
    assert widget.on_mouse("down", row3)
    assert widget.focus_row == 2 and activated == []
    assert widget.accepts_click(row3)
    widget.activate()
    assert activated == [2]
    widget.on_mouse("down", row3)
    assert not widget.accepts_click(row4)
    assert not widget.accepts_click(row3)      # the press was used up


def test_list_scrollbar_geometry():
    widget, _ = scroll_list()
    assert widget.lane_box() == Box(1220, 80, 20, 320)
    assert widget.thumb_box().h == 32
    assert widget.rows_width() == 300


def test_list_track_click_scrolls_one_page():
    widget, _ = scroll_list()
    assert widget.on_mouse("down", (1230, 300))
    assert widget.scroll == 240 and widget.focus_row == 0
    assert not widget.accepts_click((1230, 300))
    widget.on_mouse("down", (1230, 81))        # above the thumb
    assert widget.scroll == 0


def test_list_thumb_drag_is_proportional():
    widget, _ = scroll_list()
    thumb = widget.thumb_box()
    y = thumb.y + 10
    widget.on_mouse("down", (1230, y))
    widget.on_mouse("drag", (1230, y + 144))
    assert widget.scroll == pytest.approx(2240, abs=48)
    widget.on_mouse("up", (1230, y + 144))
    widget.on_mouse("drag", (1230, y))
    assert widget.scroll == pytest.approx(2240, abs=48)


def test_short_list_has_no_lane_and_empty_list_is_safe():
    widget, activated = scroll_list(6)
    assert widget.lane_box() is None and widget.rows_width() == 320
    empty, activated = scroll_list(0)
    assert empty.on_nav(Nav.DOWN) is False
    empty.activate()
    empty.on_mouse("down", (1000, 100))
    assert activated == [] and list(empty.visible_range()) == []


def test_list_skips_disabled_rows_and_follows_shrinking_rows():
    activated = []
    rows = [ListRow("a"), ListRow("b", enabled=False), ListRow("c")]
    widget = ScrollList(lambda: rows, activated.append, box=LIST_BOX)
    assert widget.on_nav(Nav.DOWN) and widget.focus_row == 2
    del rows[1:]
    widget.activate()
    assert activated == [0]


def test_list_hover_focuses_a_row():
    widget, _ = scroll_list()
    assert widget.on_mouse("hover", (1000, 80 + 48 * 4 + 1))
    assert widget.focus_row == 4


# --- Grid (AC-F10-14, I-17) ----------------------------------------------------------------

def sampler_grid():
    activated = []
    cells = [GridCell(str(i + 1), enabled=i != 4) for i in range(6)]
    grid = Grid(lambda: cells, 3, (96, 80), 16, activated.append, box=Box(920, 432, 320, 176))
    return grid, activated


def cell_center(grid, number):
    return grid.cell_box(number - 1).center


@pytest.mark.parametrize(("start", "d", "end", "used"), [
    (1, Nav.RIGHT, 2, True), (2, Nav.RIGHT, 3, True), (3, Nav.RIGHT, 3, False),
    (1, Nav.DOWN, 4, True), (4, Nav.UP, 1, True), (4, Nav.DOWN, 4, False),
    (6, Nav.HOME, 1, True), (1, Nav.END, 6, True),
    (2, Nav.DOWN, 4, True), (4, Nav.RIGHT, 6, True), (6, Nav.LEFT, 4, True),   # I-17
])
def test_grid_moves(start, d, end, used):
    grid, _ = sampler_grid()
    grid.focus_cell = start - 1
    assert grid.on_nav(d) is used
    assert grid.focus_cell + 1 == end


def test_grid_activate_and_clicks():
    grid, activated = sampler_grid()
    grid.focus_cell = 1
    grid.activate()
    assert activated == [1]
    six = cell_center(grid, 6)
    assert grid.on_mouse("down", six) and activated == [1]
    assert grid.accepts_click(six)
    grid.activate()
    assert activated == [1, 5]
    five = cell_center(grid, 5)
    assert not grid.on_mouse("down", five)
    assert not grid.accepts_click(five)
    assert grid.focus_cell == 5


def test_grid_cell5_never_focused():
    grid, _ = sampler_grid()
    grid.on_mouse("hover", cell_center(grid, 5))
    grid.on_mouse("down", cell_center(grid, 5))
    assert grid.focus_cell != 4
    for start in range(6):
        if start == 4:
            continue
        for d in (Nav.UP, Nav.DOWN, Nav.LEFT, Nav.RIGHT, Nav.HOME, Nav.END,
                  Nav.PAGE_UP, Nav.PAGE_DOWN):
            grid.focus_cell = start
            grid.on_nav(d)
            assert grid.focus_cell != 4


def test_grid_hover_and_gap():
    grid, _ = sampler_grid()
    assert grid.on_mouse("hover", cell_center(grid, 3)) and grid.focus_cell == 2
    assert grid.cell_at((920 + 100, 440)) is None          # in the gap between 1 and 2


def scrolling_grid():
    cells = [GridCell(str(i + 1)) for i in range(12)]
    return Grid(lambda: cells, 3, (96, 80), 16, lambda i: None, box=Box(920, 100, 320, 176))


def test_grid_scrolls_focus_into_view():
    grid = scrolling_grid()
    grid.focus_cell = 3
    assert grid.on_nav(Nav.DOWN) and grid.focus_cell == 6
    box = grid.cell_box(6)
    assert box.y >= grid.box.y and box.bottom <= grid.box.bottom
    assert grid.scroll == 96
    assert 6 in grid.visible_cells() and 0 not in grid.visible_cells()


def test_grid_wheel():
    grid = scrolling_grid()
    assert grid.on_mouse("wheel", grid.box.center, notches=-1)
    assert grid.scroll == grid.max_scroll() == 2 * 96
    assert grid.on_mouse("wheel", grid.box.center, notches=1)
    assert grid.scroll == 0


def test_grid_with_no_enabled_cell():
    cells = [GridCell(enabled=False)] * 3
    hits = []
    grid = Grid(lambda: cells, 3, (96, 80), 16, hits.append, box=Box(0, 0, 320, 80))
    assert not grid.on_nav(Nav.RIGHT)
    grid.activate()
    assert hits == []
    with pytest.raises(ValueError):
        Grid(lambda: cells, 0, (96, 80), 16, hits.append)


# --- Variable-height ScrollList (AC-F13-08; F13 architecture review I-1) -------------------

HIST_BOX = Box(416, 112, 808, 552)        # F13's page: view 552, rows 788 wide
P = 39                                    # pitch at text 28: page and tall-row step 513


class Heights:
    """``heights`` and ``pitch`` getters that count the ``heights`` calls."""

    def __init__(self, heights, p=P):
        self.values = list(heights)
        self.p = p
        self.calls = 0

    def height(self, index):
        self.calls += 1
        return self.values[index]

    def pitch(self):
        return self.p


def var_list(heights, *, disabled=(), p=P, draw_row=None):
    h = Heights(heights, p)
    activated = []
    widget = ScrollList(lambda: [ListRow("", enabled=i not in disabled)
                                 for i in range(len(h.values))],
                        activated.append, heights=h.height, pitch=h.pitch, draw_row=draw_row,
                        box=HIST_BOX)
    return widget, h, activated


def test_variable_range_thumb_and_rows_in_view():
    """Range Σh − view, thumb ``max(32, view/total × track)``, rows in view and under the
    pointer. One test with loops: each case in ``tests/ui`` pays ``pygame.init()``."""
    for heights, total, max_scroll, lane in (
            ([100] * 10, 1000, 448, True), ([100] * 3, 300, 0, False),
            ([87, 1500, 63], 1650, 1098, True), ([552], 552, 0, False), ([], 0, 0, False)):
        widget, _, _ = var_list(heights)
        assert (widget._content_height(), widget.max_scroll()) == (total, max_scroll), heights
        assert (widget.lane_box() is not None) is lane, heights
        assert widget.rows_width() == (788 if lane else 808), heights
    for heights, thumb_h in (([100] * 10, 552 / 1000 * 552), ([100] * 20, 552 / 2000 * 552),
                             ([100] * 200, 32),                # 15.2 → the 32 minimum
                             ([552, 1], 552 / 553 * 552)):
        widget, _, _ = var_list(heights)
        assert widget.thumb_box().h == pytest.approx(thumb_h), len(heights)
    for scroll, visible, probes in (
            (0, range(0, 2), {112: 0, 112 + 86: 0, 112 + 87: 1, 663: 1}),
            (500, range(1, 2), {112: 1, 663: 1}),
            (1218, range(1, 4), {112: 1, 112 + 368: 1, 112 + 369: 2, 112 + 432: 3, 663: 3})):
        widget, _, _ = var_list([87, 1500, 63, 120])      # total 1770, range 1218
        widget.scroll = scroll
        assert widget.visible_range() == visible, scroll
        assert {y: widget.row_at((500, y)) for y in probes} == probes, scroll
        assert widget.row_box(1) == Box(416, 112 + 87 - scroll, 788, 1500)
        assert widget.row_at((1210, 300)) is None            # the scrollbar lane


def test_variable_wheel_track_click_and_thumb_drag():
    """Wheel 3 × (p + 8) per notch; a track click scrolls view − p, as a page key (F10's
    rule; I-1), not a whole view; the thumb drag is proportional."""
    for notches, scroll in ((-1, 141), (-2, 282), (1, 0), (-40, 1448)):
        widget, _, _ = var_list([100] * 20)                 # range 1448
        assert widget.on_mouse("wheel", (800, 300), notches=notches) is (scroll != 0)
        assert (widget.scroll, widget.focus_row) == (scroll, 0), notches
    for ys, scroll in (([600], 513), ([600, 650], 1026), ([600, 650, 650], 1448),
                       ([600, 650, 650, 113], 1448 - 513)):
        widget, _, _ = var_list([100] * 20)
        for y in ys:
            assert widget.on_mouse("down", (1214, y))
            assert not widget.accepts_click((1214, y))
        assert (widget.scroll, widget.focus_row) == (scroll, 0), ys
    widget, _, _ = var_list([100] * 20)
    thumb = widget.thumb_box()
    free = 552 - thumb.h
    widget.on_mouse("down", (1214, thumb.y + 5))
    widget.on_mouse("drag", (1214, thumb.y + 105))
    assert widget.scroll == pytest.approx(100 / free * 1448)
    widget.on_mouse("drag", (1214, thumb.y + 5 + free))
    assert widget.scroll == 1448
    widget.on_mouse("up", (1214, thumb.y + 5 + free))
    widget.on_mouse("drag", (1214, thumb.y))
    assert widget.scroll == 1448
    # The pointer never scrolls a tall row.
    widget, _, _ = var_list([100, 1500, 100])
    assert widget.on_mouse("hover", (800, 112 + 300)) and widget.focus_row == 1
    assert widget.scroll == 0
    assert widget.on_mouse("down", (800, 112 + 50)) and widget.focus_row == 0
    assert widget.accepts_click((800, 112 + 50))
    widget.scroll = 1148
    assert widget.on_mouse("hover", (800, 112 + 300)) and widget.focus_row == 1
    assert widget.scroll == 1148
    widget.scroll = 1100                                   # row 2 half in view
    assert widget.on_mouse("down", (800, 112 + 530)) and widget.focus_row == 2
    assert widget.scroll == 1148                           # scrolled just into view


# Rows [100, 1500, 100]: range 1148; row 1 spans 100..1600, its bottom shows at 1048.
UP_DOWN_ROWS = (
    ([Nav.DOWN], [True], 1, 100),                          # tall row: near (top) edge
    ([Nav.DOWN] * 2, [True] * 2, 1, 613),                  # then view − p = 513 per Down
    ([Nav.DOWN] * 3, [True] * 3, 1, 1048),                 # ... until its bottom shows
    ([Nav.DOWN] * 4, [True] * 4, 2, 1148),
    ([Nav.DOWN] * 5, [True] * 4 + [False], 2, 1148),       # the end leaves the list
    ([Nav.END, Nav.UP], [True] * 2, 1, 1048),              # tall row from below: bottom edge
    ([Nav.END] + [Nav.UP] * 2, [True] * 3, 1, 535),
    ([Nav.END] + [Nav.UP] * 3, [True] * 4, 1, 100),
    ([Nav.END] + [Nav.UP] * 4, [True] * 5, 0, 0),
    ([Nav.END] + [Nav.UP] * 5, [True] * 5 + [False], 0, 0),
    ([Nav.UP], [False], 0, 0),
)
PAGE_ROWS = (
    ([100] * 20, [Nav.PAGE_DOWN], 5, 513),                 # row 0 left the view: nearest in it
    ([100] * 20, [Nav.PAGE_DOWN] * 2, 10, 1026),           # row 10 still in view: kept
    ([100] * 20, [Nav.PAGE_DOWN] * 3, 14, 1448),
    ([100] * 20, [Nav.PAGE_DOWN] * 4, 19, 1448),           # at the end: the last row in view
    ([100] * 20, [Nav.PAGE_DOWN] * 4 + [Nav.PAGE_UP], 14, 935),
    ([100] * 20, [Nav.PAGE_UP], 0, 0),
    ([100] * 3, [Nav.PAGE_DOWN], 2, 0),                    # no overflow: the last row
    ([100, 1500, 100], [Nav.DOWN, Nav.PAGE_DOWN], 1, 613),
    ([100, 1500, 100], [Nav.DOWN] + [Nav.PAGE_DOWN] * 3, 1, 1148),
    ([100, 1500, 100], [Nav.DOWN] + [Nav.PAGE_DOWN] * 4, 2, 1148),
    ([100, 1500, 100], [Nav.END], 2, 1148),
    ([100, 100, 1500], [Nav.END], 2, 1148),                # a tall last row: its bottom
    ([100, 100, 1500], [Nav.END, Nav.HOME], 0, 0),
    ([1500, 100], [Nav.END, Nav.HOME], 0, 0),              # a tall first row: its top
)


def test_variable_keys_tall_rows_and_disabled_rows():
    for keys, used, row, scroll in UP_DOWN_ROWS:
        widget, _, _ = var_list([100, 1500, 100])
        assert [widget.on_nav(d) for d in keys] == used, keys
        assert (widget.focus_row, widget.scroll) == (row, scroll), keys
    for heights, keys, row, scroll in PAGE_ROWS:
        widget, _, _ = var_list(heights)
        assert all(widget.on_nav(d) is True for d in keys), (heights, keys)
        assert (widget.focus_row, widget.scroll) == (row, scroll), (heights, keys)
        box = widget.row_box(row)
        assert box.y < HIST_BOX.bottom and box.bottom > HIST_BOX.y   # focus in the view
    # A short row scrolls just into view; disabled rows are skipped.
    widget, _, activated = var_list([300, 200, 100, 150], disabled={2})
    assert widget.on_nav(Nav.DOWN) and (widget.focus_row, widget.scroll) == (1, 0)
    assert widget.on_nav(Nav.DOWN) and (widget.focus_row, widget.scroll) == (3, 198)
    widget.activate()
    assert activated == [3]
    assert widget.on_nav(Nav.UP) and (widget.focus_row, widget.scroll) == (1, 198)


def test_variable_prefix_sums_rebuild_on_count_or_pitch_only():
    widget, h, _ = var_list([100] * 10)
    widget.max_scroll()
    assert h.calls == 10
    for _ in range(3):
        widget.visible_range()
        widget.row_at((500, 300))
        widget.on_nav(Nav.DOWN)
        widget.on_mouse("wheel", (500, 300), notches=-1)
    assert h.calls == 10
    h.values.append(1500)                                   # a new entry
    assert widget.max_scroll() == 2500 - 552 and h.calls == 21
    h.p = 59                                                # 150% text
    assert widget.max_scroll() == 2500 - 552 and h.calls == 32
    assert widget.page_step() == 552 - 59
    # The steps follow the pitch; fixed lists ignore it.
    widget, _, _ = var_list([100] * 20, p=59)
    assert widget.wheel_step() == 3 * (59 + 8) and widget.page_step() == 552 - 59
    fixed = ScrollList(lambda: [ListRow("r")] * 100, lambda i: None, pitch=lambda: 59,
                       box=LIST_BOX)
    assert fixed.wheel_step() == 144 and fixed.page_step() == 240


class SpyPainter:
    """Records widget-level drawing; ``clipped`` works on an offscreen surface."""

    class _Canvas:
        def __init__(self):
            self.surface = pygame.Surface((1280, 720))
            self.clips = []

        def rect_to_px(self, rect):
            self.clips.append(tuple(rect))
            return pygame.Rect(*rect)

    class _Style:
        def color(self, name):
            return (1, 2, 3)

    def __init__(self):
        self.canvas = self._Canvas()
        self.calls = []

    def style(self, area, state="normal"):
        return self._Style()

    def widget_frame(self, box, area, look, *, marker=True):
        self.calls.append(("frame", box, look.state, marker))

    def text(self, text, pos, **kw):
        self.calls.append(("text", text))
        return (0, 0, 0, 0)

    def rect(self, box, color):
        self.calls.append(("rect", box))

    def shape(self, box, spec):
        self.calls.append(("shape", box))


def test_variable_draw_row_draws_only_rows_in_view_clipped():
    drawn = []
    widget, _, _ = var_list([87, 1500, 63, 120],
                            draw_row=lambda p, i, box, look: drawn.append((i, box, look.state)))
    widget.scroll = 1218
    widget.focus_row = 3
    painter = SpyPainter()
    widget.draw(painter, Look("focused"))
    assert [i for i, _, _ in drawn] == [1, 2, 3]
    assert drawn[0][1] == Box(416, 112 + 87 - 1218, 788, 1500)
    assert [state for _, _, state in drawn] == ["normal", "normal", "focused"]
    frames = [c for c in painter.calls if c[0] == "frame"]
    assert len(frames) == 3 and all(c[3] is False for c in frames)     # no marker
    assert not [c for c in painter.calls if c[0] == "text"]            # labels unused
    assert painter.canvas.clips == [(416, 112, 808, 552)]
    # A fixed list with ``draw_row`` keeps its fixed geometry.
    drawn = []
    rows = [ListRow(f"Row {i}") for i in range(100)]
    widget = ScrollList(lambda: rows, lambda i: None, box=LIST_BOX,
                        draw_row=lambda p, i, box, look: drawn.append((i, box)))
    widget.on_nav(Nav.PAGE_DOWN)
    assert widget.focus_row == 5 and widget.scroll == 0
    widget.draw(SpyPainter(), Look("normal"))
    assert drawn[1] == (1, Box(920, 128, 300, 48)) and len(drawn) == 7
