"""The dev widget sampler with the test shell (F10 SPEC step 4): every widget's inputs and
looks through real events, AC-F10-10 to 16, and the unit parts of AC-F10-09 (Tab order,
public widget classes only, backdrop toggle, 150% text). AC-F10-09's App F rows (Shift+F3 on
the title and game menu, ``--dev``) are in ``tests/app/test_ui_flow.py``.

Tables are loops in one test, each row on a fresh sampler (``make()``), not ``parametrize``:
every ``tests/ui`` test pays for ``pygame.init()``/``quit()`` (test-review-F10.md)."""

import ast
from pathlib import Path

import pygame
import pytest

from engine.core.config_schema import ThemeConfig
from engine.ui.builtin import sampler as sampler_module
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.sampler import SamplerScreen
from engine.ui.focus import Box
from engine.ui.nav import InputKind
from engine.ui.widgets import Button, Grid, GridCell, ListRow, ScrollList, Slider, Toggle
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import ColumnMenu, TestShell, UiHarness

pytestmark = pytest.mark.display

H = UiHarness
CFG = ThemeConfig()
WHITE = (255, 255, 255)


def over(color, opacity, base=WHITE):
    """A color at ``opacity`` composited over ``base``, as drawn (06 §0.3)."""
    return tuple(round(c * opacity + b * (1 - opacity)) for c, b in zip(color, base))


def near(actual, expected, tol=2):
    return all(abs(a - e) <= tol for a, e in zip(actual, expected))


def make():
    """A fresh sampler, opened by mouse, after one frame."""
    shell = TestShell()
    h = UiHarness(shell)
    screen = SamplerScreen(shell, by=InputKind.MOUSE)
    shell.stack.push(screen)
    h.frame()
    return shell, h, screen


@pytest.fixture
def sampler():
    return make()


def record(widget_set):
    calls = []

    def setter(value):
        calls.append(value)
        widget_set(value)
    return calls, setter


def focus(h, s, widget):
    s.scope.focus(widget, InputKind.KEYS)
    h.frame()


# --- AC-F10-09 (unit parts) ------------------------------------------------------------------

def test_ac09_tab_order_classes_header_first_input_and_back(sampler, monkeypatch):
    shell, h, s = sampler
    order = s.scope.tab_order()
    assert order == [s.live_button, s.open_confirm, s.text_toggle, s.black_toggle, s.slider,
                     s.list, s.grid]
    assert [w.label() for w in order[:5]] == ["Live button", "Open confirm", "Text 150%",
                                              "Black backdrop", "Live slider"]
    for w in s.scope.widgets():
        assert type(w) in (Button, Toggle, Slider, ScrollList, Grid)
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    by_text = {c.text: c for c in calls}
    assert by_text["Widget sampler (dev)"].pos == (40, 24)
    hint = by_text["Esc / B: back"]
    assert hint.pos == (1240, 24) and hint.options["anchor"] == "topright"
    h.frame(H.key(pygame.K_TAB))
    assert s.scope.focused is s.live_button and s.live_presses == 0
    h.frame(H.down((640, 690), 3))                         # right click: Back closes it
    assert shell.stack.top is None
    with pytest.raises(AssertionError):                    # the sampler needs a dev run
        SamplerScreen(TestShell(dev=False), by=InputKind.KEYS)
    tree = ast.parse(Path(sampler_module.__file__).read_text(encoding="utf-8"))
    private = [node.attr for node in ast.walk(tree)
               if isinstance(node, ast.Attribute) and node.attr.startswith("_")
               and not node.attr.startswith("__")]
    assert private == []


def test_ac09_open_confirm_pushes_a_confirm_and_back_returns_focus(sampler):
    shell, h, s = sampler
    h.frame(H.key(pygame.K_DOWN))
    h.frame(H.key(pygame.K_DOWN))
    h.frame(H.key(pygame.K_RETURN))
    assert isinstance(shell.stack.top, ConfirmScreen)
    h.frames(10)
    h.frame(H.key(pygame.K_ESCAPE))
    h.frames(10)
    assert shell.stack.top is s and s.scope.focused is s.open_confirm and s.scope.visible
    assert s.confirm_answers == ["no"]


def test_ac09_black_backdrop_and_text_150(sampler):
    shell, h, s = sampler
    assert h.px(20, 700) == WHITE
    h.click(s.black_toggle.box.center)
    assert s.black and h.px(20, 700) == (0, 0, 0)
    h.click(s.text_toggle.box.center)
    assert s.scale == 1.5 and s.live_button.box.h == 75
    h.frame(H.key(pygame.K_TAB))
    for _ in range(10):
        h.frame(H.key(pygame.K_TAB))
        box = s.scope.focused.box
        assert 72 <= box.y and box.bottom <= 712
    assert s.list.row_height == 67


# --- AC-F10-10 Toggle --------------------------------------------------------------------------

def test_ac10_toggle_inputs():
    for name, event in (("enter", H.key(pygame.K_RETURN)), ("space", H.key(pygame.K_SPACE)),
                        ("south", H.pad(pygame.CONTROLLER_BUTTON_A))):
        shell, h, s = make()
        calls, s.black_toggle.set = record(s.black_toggle.set)
        focus(h, s, s.black_toggle)
        h.frame(event)
        assert calls == [True], name
    shell, h, s = make()                                   # a click flips once
    calls, s.black_toggle.set = record(s.black_toggle.set)
    h.click(s.black_toggle.box.center)
    assert calls == [True]
    shell, h, s = make()                                   # RIGHT/LEFT set, focus stays
    calls, s.black_toggle.set = record(s.black_toggle.set)
    focus(h, s, s.black_toggle)
    h.frame(H.key(pygame.K_RIGHT))
    h.frame(H.key(pygame.K_RIGHT))
    assert calls == [True] and s.scope.focused is s.black_toggle
    h.frame(H.key(pygame.K_LEFT))
    h.frame(H.key(pygame.K_LEFT))
    assert calls == [True, False] and s.scope.focused is s.black_toggle
    shell, h, s = make()                                   # the disabled toggle
    calls, s.toggle_disabled.set = record(s.toggle_disabled.set)
    h.click(s.toggle_disabled.box.center)
    h.frame(H.key(pygame.K_RETURN))
    assert calls == []
    assert s.toggle_disabled not in s.scope.tab_order()


def test_ac10_toggle_state_word_left_of_the_track(sampler, monkeypatch):
    shell, h, s = sampler
    toggles = [s.toggle_off, s.toggle_on, s.toggle_disabled, s.text_toggle, s.black_toggle]
    with spy_draw_text(monkeypatch) as calls:
        h.frame()

    def words():
        found = []
        for t in toggles:
            track = t.track_box()
            found += [c.text for c in calls if c.pos == (track.x - 12, track.y + 14)
                      and c.options.get("anchor") == "midright"]
        return found

    assert words() == ["Off", "On", "Off", "Off", "Off"]
    with spy_draw_text(monkeypatch) as calls:
        h.click(s.black_toggle.box.center)
    assert words() == ["Off", "On", "Off", "Off", "On"]


# --- AC-F10-11 Slider --------------------------------------------------------------------------

def test_ac11_slider_keys_and_steps():
    for keys, value in (([pygame.K_RIGHT], 55), ([pygame.K_LEFT, pygame.K_LEFT], 40),
                        ([pygame.K_HOME, pygame.K_LEFT], 0),
                        ([pygame.K_END, pygame.K_RIGHT], 100)):
        shell, h, s = make()
        calls, s.slider.set = record(s.slider.set)
        focus(h, s, s.slider)
        for key in keys:
            h.frame(H.key(key))
        assert s.value == value, keys
        assert len(calls) == len(set(calls)) and calls[-1] == value, keys
    assert (s.slider.box.x, s.slider.box.right) == (400, 880)
    assert s.slider.bar_span() == (432, 776)
    for lo, hi, step in ((0, 100, 5), (0, 10, 1), (0, 30, 2), (0, 1000, 50), (-50, 50, 5)):
        assert Slider(lambda: "", lo, hi, lambda: lo, lambda v: None).step == step, (lo, hi)


def test_ac11_slider_pointer_and_disabled(sampler):
    shell, h, s = sampler
    calls, s.slider.set = record(s.slider.set)
    by = s.slider.bar_center_y(28)
    for x, value in ((604, 50), (518, 25), (450, 5), (420, 0)):
        h.click((x, by))
        assert s.value == value, x
    assert calls == [25, 5, 0]
    h.frame(H.down((518, by)))                             # drag
    assert s.value == 25
    h.frame(H.motion((690, by)))
    assert s.value == 75
    h.frame(H.up((690, by)))
    h.frame(H.down((518, by)))
    h.frame(H.motion((900, by)))
    assert s.value == 100
    h.frame(H.up((900, by)))
    calls, s.slider_disabled.set = record(s.slider_disabled.set)
    dby = s.slider_disabled.bar_center_y(28)
    h.click((518, dby))
    h.frame(H.down((518, dby)), H.motion((700, dby)), H.up((700, dby)))
    h.frame(H.key(pygame.K_HOME))
    assert calls == []


def test_ac11_slider_value_is_drawn_in_the_frame_it_changes(sampler, monkeypatch):
    shell, h, s = sampler
    focus(h, s, s.slider)
    with spy_draw_text(monkeypatch) as calls:
        h.frame(H.key(pygame.K_RIGHT))
    by = s.slider.bar_center_y(28)
    assert [c.text for c in calls if c.pos == (848, by)] == ["55"]


# --- AC-F10-12 Scroll list by keys --------------------------------------------------------------

def test_ac12_list_keys():
    for keys, row, scroll in (
        ([pygame.K_DOWN] * 6, 7, 16),
        ([pygame.K_DOWN] * 6 + [pygame.K_UP] * 6, 1, 0),
        ([pygame.K_PAGEDOWN], 6, 0),
        ([pygame.K_PAGEDOWN] * 2, 11, 208),
        ([pygame.K_END], 100, 4480),
        ([pygame.K_END, pygame.K_HOME], 1, 0),
        ([pygame.K_UP], 1, 0),
    ):
        shell, h, s = make()
        focus(h, s, s.list)
        for key in keys:
            h.frame(H.key(key))
        assert s.scope.focused is s.list, keys
        assert (s.list.focus_row + 1, s.list.scroll) == (row, scroll), keys
    h.frame(H.key(pygame.K_END))                           # DOWN at Row 100 leaves to the grid
    h.frame(H.key(pygame.K_DOWN))
    assert s.scope.focused is s.grid and s.list.scroll == 4480


def test_ac12_list_activate_and_draws_only_the_rows_in_view(sampler, monkeypatch):
    shell, h, s = sampler
    focus(h, s, s.list)
    h.frame(H.key(pygame.K_DOWN))
    h.frame(H.key(pygame.K_DOWN))
    h.frame(H.key(pygame.K_RETURN))
    assert s.list_picks == [2]
    for _ in range(4):
        h.frame(H.key(pygame.K_DOWN))                      # Row 7, scroll 16
    assert s.list.scroll == 16
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    rows = [c.text for c in calls if c.text.startswith("Row ")]
    assert rows == [f"Row {i}" for i in range(1, 8)]


# --- AC-F10-13 Scroll list by mouse --------------------------------------------------------------

LIST_POINT = (1000, 240)


def row_center(s, index):
    return s.list.row_box(index).center


def test_ac13_list_wheel():
    for notches, scroll in (([-1], 144), ([-2], 288), ([1], 0), ([-40], 4480)):
        shell, h, s = make()
        for y in notches:
            h.frame(H.motion(LIST_POINT), H.wheel(LIST_POINT, y))
        assert s.list.scroll == scroll, notches
    shell, h, s = make()                                   # over the slider: nothing
    point = s.slider.box.center
    h.frame(H.motion(point), H.wheel(point, -1))
    assert s.list.scroll == 0 and s.value == 50


def test_ac13_list_click_scrollbar_and_thumb(sampler):
    shell, h, s = sampler
    lane, thumb = s.list.lane_box(), s.list.thumb_box()
    assert (lane.x, lane.right) == (1220, 1240) and thumb.h == 32
    h.frame(H.down((1230, 90)))                            # thumb dragged down 144
    h.frame(H.motion((1230, 234)))
    h.frame(H.up((1230, 234)))
    assert abs(s.list.scroll - 2240) <= 48
    shell, h, s = make()
    h.frame(H.down(row_center(s, 2)))
    assert s.list_picks == []
    h.frame(H.up(row_center(s, 2)))
    assert s.list_picks == [2] and s.list.focus_row == 2
    assert s.scope.focused is s.list and s.scope.source is InputKind.MOUSE
    h.frame(H.down(row_center(s, 2)), H.up(row_center(s, 3)))
    assert s.list_picks == [2]
    row = s.list.focus_row
    h.click((1230, 300))                                   # the track below the thumb
    assert s.list.scroll == 240 and s.list.focus_row == row


def test_ac13_short_and_empty_lists(monkeypatch):
    shell = TestShell()
    h = UiHarness(shell)
    menu = ColumnMenu(shell, by=InputKind.MOUSE, fade=False)
    shell.stack.push(menu)
    short = ScrollList(lambda: [ListRow(f"r{i}") for i in range(6)], lambda i: None,
                       box=Box(500, 100, 320, 320))
    empty = ScrollList(lambda: [], lambda i: None, box=Box(500, 100, 320, 320),
                       empty=lambda: shell.words.get("list_empty"))
    assert short.lane_box() is None and short.row_box(0).w == 320
    painter = shell.painter
    h.frame()
    painter.bind(h.canvas)
    with spy_draw_text(monkeypatch) as calls:
        empty.draw(painter, empty.look(focused=False))
    assert [c.text for c in calls] == ["Nothing here yet."]
    assert calls[0].color == CFG.list.empty.text_color
    assert calls[0].pos == (660, 260) and calls[0].options["anchor"] == "center"


# --- AC-F10-14 Grid ----------------------------------------------------------------------------

def test_ac14_grid_moves_and_activation(sampler):
    shell, h, s = sampler
    focus(h, s, s.grid)
    for start, key, end in (
        (1, pygame.K_RIGHT, 2), (2, pygame.K_RIGHT, 3), (3, pygame.K_RIGHT, 3),
        (1, pygame.K_DOWN, 4), (4, pygame.K_UP, 1), (4, pygame.K_DOWN, 4),
        (3, pygame.K_HOME, 1), (1, pygame.K_END, 6),
        (2, pygame.K_DOWN, 4), (4, pygame.K_RIGHT, 6), (6, pygame.K_LEFT, 4),  # I-17 / I-22
    ):
        s.grid.focus_index(start - 1)
        h.frame(H.key(key))
        assert s.scope.focused is s.grid and s.grid.focus_cell + 1 == end, (start, key)
    s.grid.focus_index(1)
    h.frame(H.key(pygame.K_RETURN))
    assert s.grid_picks == [1]
    h.frame(H.down(s.grid.cell_box(5).center))
    assert s.grid_picks == [1]
    h.frame(H.up(s.grid.cell_box(5).center))
    assert s.grid_picks == [1, 5]
    h.click(s.grid.cell_box(4).center)
    h.frame(H.motion(s.grid.cell_box(4).center))
    assert s.grid_picks == [1, 5] and s.grid.focus_cell != 4


def test_ac14_unit_grid_scrolls_and_wheels():
    shell = TestShell()
    h = UiHarness(shell)
    menu = ColumnMenu(shell, by=InputKind.MOUSE, fade=False, n=1)
    grid = Grid(lambda: [GridCell(str(i)) for i in range(1, 13)], 3, (96, 80), 16,
                lambda i: None, box=Box(600, 100, 320, 176))
    menu.scope.set_groups([menu.scope.groups[0], type(menu.scope.groups[0])([grid])])
    shell.stack.push(menu)
    h.frame()
    menu.scope.focus(grid, InputKind.KEYS)
    grid.focus_index(3)
    h.frame(H.key(pygame.K_DOWN))
    assert grid.focus_cell == 6
    cell = grid.cell_box(6)
    assert cell.y >= grid.box.y and cell.bottom <= grid.box.bottom
    before = grid.scroll
    h.frame(H.motion((100, 600)), H.wheel((100, 600), 1))
    assert grid.scroll == before
    h.frame(H.motion(grid.box.center), H.wheel(grid.box.center, 1))
    assert grid.scroll < before


# --- AC-F10-15 Button states on screen ----------------------------------------------------------

def expected_button(state):
    b = CFG.button
    fill = over(b.fill_color, b.fill_opacity)
    focus_fill = over(b.focused.fill_color, b.fill_opacity)
    press_fill = over(b.pressed.fill_color, b.fill_opacity)
    marker = b.marker.fill_color
    rows = {
        "Normal": (b.border_color, fill, fill, fill, None, None),
        "Focused": (b.focused.border_color, b.focused.border_color, focus_fill, marker, None,
                    None),
        "Pressed": (b.focused.border_color, b.focused.border_color, press_fill, marker, None,
                    None),
        "Disabled": (fill, fill, fill, fill, None, None),
        "On": (b.border_color, fill, fill, fill, marker, marker),
        "Off": (b.border_color, fill, fill, fill, fill, marker),
    }
    return rows[state]


def test_ac15_button_state_probes_and_disabled_label(sampler, monkeypatch):
    shell, h, s = sampler
    widgets = {"Normal": s.static_normal, "Focused": s.static_focused,
               "Pressed": s.static_pressed, "Disabled": s.static_disabled,
               "On": s.static_on, "Off": s.static_off}
    for state, widget in widgets.items():
        x, y, w, hh = widget.box.x, widget.box.y, widget.box.w, widget.box.h
        cy = y + hh / 2
        inset1, inset3, inset6, mark, pip, ring = expected_button(state)
        assert near(h.px(x + 1, cy), inset1), state
        assert near(h.px(x + 3, cy), inset3), state
        assert near(h.px(x + 6, cy), inset6), state
        assert near(h.px(x + 15, cy), mark), state
        if pip is not None:
            assert near(h.px(x + w - 24, cy), pip), state
            assert near(h.px(x + w - 19, cy), ring, tol=12), state   # anti-aliased ring
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    (call,) = [c for c in calls if c.text == "Disabled"]
    assert call.color == CFG.button.disabled.text_color


def test_ac15_pressed_fill_for_six_frames_and_while_held(sampler):
    shell, h, s = sampler
    h.frame(H.key(pygame.K_DOWN))                          # focuses Live button
    box = s.live_button.box
    probe = (box.x + 6, box.y + box.h / 2)
    press = over(CFG.button.pressed.fill_color, CFG.button.fill_opacity)
    focused = over(CFG.button.focused.fill_color, CFG.button.fill_opacity)
    seen = []
    h.frame(H.key(pygame.K_RETURN))
    seen.append(h.px(*probe))
    for _ in range(7):
        h.frame()
        seen.append(h.px(*probe))
    assert [near(c, press) for c in seen] == [True] * 6 + [False] * 2
    assert near(seen[-1], focused)
    assert s.live_presses == 1
    h.frame(H.motion(box.center), H.down(box.center))      # a held mouse press
    h.frames(30)
    assert near(h.px(*probe), press)
    h.frame(H.up(box.center))
    assert not near(h.px(*probe), press)


# --- AC-F10-16 Row widgets on screen ------------------------------------------------------------

def test_ac16_toggle_slider_and_list_row_probes(sampler):
    shell, h, s = sampler
    t = CFG.toggle
    off = s.toggle_off.track_box()
    assert near(h.px(off.x + 14, off.y + 14), t.track_color)
    on = s.toggle_on.track_box()
    assert near(h.px(on.x + 42, on.y + 14), (255, 255, 255))
    assert near(h.px(on.x + 14, on.y + 14), t.on.track_color)
    dis = s.toggle_disabled.track_box()
    for x in (dis.x + 14, dis.x + 42):
        color = h.px(x, dis.y + 14)
        assert not near(color, t.track_color, 8) and not near(color, (255, 255, 255), 8)
    sl = CFG.slider
    by = s.slider.bar_center_y(28)
    for dy in (-3, 3):
        assert near(h.px(500, by + dy), sl.fill_color)
        assert near(h.px(700, by + dy), WHITE)
    for dy in (-1, 1):
        assert near(h.px(700, by + dy), sl.track_color)
    assert near(h.px(604, by), sl.thumb_color)
    dby = s.slider_disabled.bar_center_y(28)
    assert not near(h.px(604, dby), sl.thumb_color, 20)
    focus(h, s, s.list)
    row = s.list.row_box(0)
    cy = row.y + row.h / 2
    b = CFG.button
    assert near(h.px(row.x + 1, cy), b.focused.border_color)
    assert near(h.px(row.x + 3, cy), b.focused.border_color)
    assert near(h.px(row.x + 6, cy), over(b.focused.fill_color, b.fill_opacity))
