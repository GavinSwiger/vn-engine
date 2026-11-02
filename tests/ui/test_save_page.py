"""F11 step 9 — the Save and Load pages on a real ``GameShell`` (test_game_menu's ``Game``
rig, no frame loop) over a fake ``SlotsPort``: cells by state and their probes (AC-F11-41),
labels and tags, text scale and contrast (AC-F11-49), the page row and page keys
(AC-F11-40), keys and focus (AC-F11-44, C1), delete controls (AC-F11-43's page half), the
page messages (AC-F11-46's page half), quick-menu Save and the title page (AC-F11-47),
render-safe text (AC-F11-48), and the import rules (AC-F11-57). The real port over
``SaveService`` is ``tests/app/test_save_pages_app.py``.

Cell coordinates at 100% (06 §0.4): cell 1 at (416, 112), 256 × 225; picture box (424, 120)
240 × 135; label tag (428, 124), 34 tall; Newest tag bottom-left at (428, 251); × center
(644, 140); date line (424, 261); placeholder area (424, 120) 240 × 209.
"""

import ast
from pathlib import Path

import pygame
import pytest

from engine.app.saves import shown_text
from engine.app.text_check import contrast_ratio
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.save_page import SavePage, SlotView, open_save_from_quick, \
    register_save_pages
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.nav import InputKind, Nav
from engine.ui.page_row import PageRow
from engine.ui.theme import plain_theme
from tests.fakes.draw_spy import spy_draw_text
from tests.ui.test_game_menu import FADE, Game, H
from tests.ui.test_title import Rig

REPO = Path(__file__).resolve().parents[2]
GREY = (200, 200, 200)
PLACEHOLDER = (240, 208, 222)
BERRY = (160, 40, 96)
BADGE = (0xFF, 0xF4, 0xF8)
DATE = "2026-11-01 21:04"


def close(a, b, tol: int = 2) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def over(fg, alpha, bg) -> tuple:
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))


def thumb(color=GREY) -> pygame.Surface:
    surface = pygame.Surface((320, 180), 0, 24)
    surface.fill(color)
    return surface


def label_of(page, n: int) -> str:
    return {"auto": "Auto", "quick": "Quick"}.get(page, "Slot") + f" {n}"


def filled(page="auto", n=1, **kw) -> SlotView:
    kw.setdefault("date", DATE)
    kw.setdefault("description", "Hana: Hey, have you ever written a poem?")
    kw.setdefault("thumb", thumb())
    kw.setdefault("deletable", True)
    return SlotView(label_of(page, n), "filled", **kw)


class FakePort:
    """A ``SlotsPort`` with fixed views per page; records what the page asks."""

    def __init__(self, pages: int = 10) -> None:
        self.n = pages
        self.data: dict = {}
        self.calls: list = []
        self.reason = {"save": None, "load": None}
        self.none = False
        self.loading = False
        self.default = 0
        self.last: dict = {}

    def pages(self, mode):
        return (["auto", "quick"] if mode == "load" else []) + list(range(1, self.n + 1))

    def page_label(self, page):
        return {"auto": "Auto", "quick": "Quick"}.get(page, str(page))

    def initial_page(self, mode):
        return self.last.get(mode, "auto" if mode == "load" else 1)

    def views(self, page):
        found = self.data.get(page)
        if found is not None:
            return list(found)
        return [SlotView(label_of(page, i + 1), "empty") for i in range(6)]

    def default_cell(self, page):
        return self.default

    def blocked(self, mode):
        return self.reason[mode]

    def no_saves(self):
        return self.none

    def busy(self):
        return self.loading

    def load_indicator(self):
        return getattr(self, "big", False)

    def remember(self, mode, page):
        self.calls.append(("remember", mode, page))
        self.last[mode] = page

    def choose(self, page, i, mode, by):
        self.calls.append(("choose", page, i, mode, by))

    def delete(self, page, i, by):
        self.calls.append(("delete", page, i, by))

    def acts(self) -> list:
        return [c for c in self.calls if c[0] != "remember"]


class Pages:
    """A game in progress with F11's page entries over a fake port."""

    def __init__(self, tmp_path, *, port: FakePort | None = None, pages: int = 10) -> None:
        self.g = Game(tmp_path)
        self.port = port if port is not None else FakePort(pages)
        register_save_pages(self.g.shell, self.port, can_save=lambda: True,
                            visible=lambda: True)

    def open(self, mode: str = "load", *, by_keys: bool = True) -> tuple[GameMenuScreen, SavePage]:
        g = self.g
        menu = g.open(H.key(pygame.K_ESCAPE) if by_keys else H.down((640, 360), 3))
        menu.open_page(mode)
        page = menu.page
        assert isinstance(page, SavePage)
        g.frame()
        return menu, page

    def focus_grid(self, menu, page, cell: int = 0) -> None:
        menu.scope.focus(page.grid, InputKind.KEYS)
        page.grid.focus_cell = cell
        self.g.frame()


@pytest.fixture
def pages(tmp_path) -> Pages:
    return Pages(tmp_path)


def cell1_texts(calls) -> list:
    return [c for c in calls if 416 <= c.pos[0] < 672 and 112 <= c.pos[1] < 337]


# --- AC-F11-41: cell states on screen ---------------------------------------------------------

def test_ac41_filled_newest_cell(pages, monkeypatch):
    pages.port.data["auto"] = [filled(newest=True)] + [SlotView(f"Auto {n}", "empty")
                                                       for n in range(2, 7)]
    menu, page = pages.open()
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    g = pages.g
    assert close(g.px((544, 187)), GREY)
    assert close(g.px((431, 141)), over(BADGE, 0.90, GREY), 3)
    assert close(g.px((431, 234)), BERRY)
    texts = {c.text: c for c in cell1_texts(calls)}
    assert {"Auto 1", "Newest", DATE} <= set(texts)
    assert texts[DATE].pos == (424, 261)
    description = next(c for c in texts.values() if c.pos == (424, 295))
    assert description.text.endswith("…")                    # cut to 240 wide
    assert "Hana: Hey, have you ever written a poem?".startswith(description.text[:-1])


def test_ac41_filled_without_a_picture(pages, monkeypatch):
    pages.port.data["auto"] = [filled(thumb=None)] + [SlotView(f"Auto {n}", "empty")
                                                      for n in range(2, 7)]
    pages.open()
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    assert close(pages.g.px((544, 187)), PLACEHOLDER)
    texts = [c.text for c in cell1_texts(calls)]
    assert "No picture" in texts and DATE in texts


@pytest.mark.parametrize("state, words", [
    ("empty", ["Empty slot"]), ("damaged", ["Damaged save"]),
    ("newer", ["Made by a newer version", "of the game."]),
    ("other_game", ["This save is from a", "different game."]),
    ("loading", ["Loading…"]),
])
def test_ac41_placeholder_states(pages, monkeypatch, state, words):
    pages.port.data["auto"] = [SlotView("Auto 1", state, deletable=state != "empty")] + [
        SlotView(f"Auto {n}", "empty") for n in range(2, 7)]
    pages.open()
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    assert close(pages.g.px((432, 320)), PLACEHOLDER)
    texts = cell1_texts(calls)
    assert "Auto 1" in [c.text for c in texts]               # every state draws its label
    drawn = [c.text for c in texts if c.text != "Auto 1"]
    assert " ".join(drawn) == " ".join(words)                # wrapped as needed
    assert not [c for c in texts if c.pos[1] == 261]         # no date line


def test_ac41_load_in_progress_tag_and_the_delete_mark(pages, monkeypatch):
    pages.port.data["auto"] = [filled(busy=True, deletable=False)] + [
        SlotView(f"Auto {n}", "empty") for n in range(2, 7)]
    menu, page = pages.open()
    pages.focus_grid(menu, page)
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    loading = next(c for c in calls if c.text == "Loading…")
    assert loading.pos == (544, 187.5)                        # centered on the box
    assert close(pages.g.px((644, 128)), GREY)                # busy: no ×
    pages.port.data["auto"][0] = filled()
    pages.g.frame()
    assert close(pages.g.px((644, 128)), over(BADGE, 0.90, GREY), 3)   # the × circle
    marker = plain_theme().cfg.button.marker.fill_color
    assert close(pages.g.px((644, 140)), marker, 3)           # its strokes cross here
    menu.scope.focus(menu.button("return"), InputKind.KEYS)
    pages.g.frame()
    assert close(pages.g.px((644, 128)), GREY)                # unfocused: none


def test_ac41_a_long_label_ends_before_the_delete_mark(pages, monkeypatch):
    pages.port.data["auto"] = [SlotView("Speicherstand Nummer 1", "filled", DATE, "x",
                                        thumb(), deletable=True)] + [
        SlotView(f"Auto {n}", "empty") for n in range(2, 7)]
    pages.open()
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    label = next(c for c in calls if c.text.startswith("Speicher"))
    assert label.text.endswith("…")
    left, _top, width, _h = label.bounds
    assert left + width + 8 <= 424 + 192                      # the tag's right edge


# --- AC-F11-49: text scale and contrast ---------------------------------------------------------

def test_ac49_150_percent_keeps_every_part_inside_the_cell(pages, monkeypatch):
    pages.port.data["auto"] = [filled(newest=True)] + [SlotView(f"Auto {n}", "empty")
                                                       for n in range(2, 7)]
    pages.g.shell.painter._text_scale = lambda: 1.5
    menu, page = pages.open()
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    cell = page.layout.cells[0].box
    parts = [c for c in calls if c.text in ("Auto 1", "Newest", DATE)
             or c.text.startswith("Hana")]
    assert {c.text for c in parts} >= {"Auto 1", "Newest", DATE}
    assert any(c.text.startswith("Hana") for c in parts)
    for c in parts:
        x, y, w, h = c.bounds
        assert cell.x <= x and x + w <= cell.right and cell.y <= y and y + h <= cell.bottom, c
    date = next(c for c in parts if c.text == DATE)
    assert date.font.size <= 28                               # complete, stepped down


def _ratio(fg, bg_color, alpha, base) -> float:
    return contrast_ratio(tuple(fg), over(bg_color, alpha, base))


@pytest.mark.parametrize("pair, black, white", [
    ("tag", 9.8, 12.3), ("newest", 7.1, 7.1), ("placeholder", 9.3, 9.3),
    ("x_circle", 5.3, 6.6), ("x_hover", 3.8, 4.9),
])
def test_ac49_default_contrast(pair, black, white):
    cfg = plain_theme().cfg
    save, button = cfg.save, cfg.button
    fg, bg, alpha = {
        "tag": (save.badge.text_color, save.badge.fill_color, save.badge.fill_opacity),
        "newest": (save.newest.text_color, save.newest.fill_color, 1.0),
        "placeholder": (save.placeholder.text_color, save.placeholder.fill_color, 1.0),
        "x_circle": (button.marker.fill_color, save.badge.fill_color,
                     save.badge.fill_opacity),
        "x_hover": (button.marker.fill_color, button.pressed.fill_color, button.fill_opacity),
    }[pair]
    on_black = _ratio(fg, bg, alpha, (0, 0, 0))
    on_white = _ratio(fg, bg, alpha, (255, 255, 255))
    assert abs(on_black - black) <= 0.1 and abs(on_white - white) <= 0.1
    assert min(on_black, on_white) >= (3 if pair.startswith("x_") else 4.5)


# --- AC-F11-40: the page row and page keys -------------------------------------------------------

def test_ac40_rows_and_selected_page(pages):
    """The labels in order; the current page selected. (With M20 metrics ten pages need
    arrows; AC-F11-39's bundled-font row is test_save_layout's and the App's.)"""
    menu, page = pages.open("load")
    assert list(page.row.labels()) == ["Auto", "Quick", *(str(n) for n in range(1, 11))]
    assert page.row.current() == 0
    selected = [b for b in page.row.layout().buttons
                if b.kind == "page" and b.page == page.row.current()]
    assert len(selected) == 1 and selected[0].label == "Auto"
    menu.close_page()
    menu.open_page("save")
    page = menu.page
    assert list(page.row.labels()) == [str(n) for n in range(1, 11)]
    assert page.page == 1                                       # never Auto or Quick


@pytest.mark.parametrize("down, up", [
    (H.key(pygame.K_PAGEDOWN), H.key(pygame.K_PAGEUP)),
    (H.pad(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER), H.pad(pygame.CONTROLLER_BUTTON_LEFTSHOULDER)),
], ids=["keys", "bumpers"])
def test_ac40_page_keys_step_without_wrapping(pages, down, up):
    menu, page = pages.open("load")
    g = pages.g
    g.frame(up)
    assert page.page == "auto"                                  # no wrap at the start
    g.frame(down)
    assert page.page == "quick"
    g.frame(down)
    assert page.page == 1
    for _ in range(12):
        g.frame(down)
    assert page.page == 10                                      # no wrap at the end
    assert ("remember", "load", "quick") in pages.port.calls


def test_ac40_holding_page_down_repeats_after_30_frames_then_every_5(pages):
    menu, page = pages.open("load")
    g = pages.g
    g.frame(H.key(pygame.K_PAGEDOWN))
    shown = [page.page]
    for _ in range(45):
        g.frame()
        shown.append(page.page)
    first = shown.index("quick")
    assert first == 0
    changes = [i for i in range(1, len(shown)) if shown[i] != shown[i - 1]]
    # The press frame counts (as F10's held directions): the first repeat is the 30th
    # frame of the hold, then one every 4.8 frames (80 ms).
    assert changes[0] == 29 and all(b - a in (4, 5) for a, b in zip(changes, changes[1:]))
    g.frame(H.key(pygame.K_PAGEDOWN, up=True))
    held = page.page
    g.frames(40)
    assert page.page == held                                    # the release stops it


def test_ac40_clicking_a_page_button_and_the_arrows_with_100_pages(tmp_path):
    p = Pages(tmp_path, pages=100)
    menu, page = p.open("load", by_keys=False)
    row = page.row
    layout = row.layout()
    assert layout.arrows and layout.pages[:2] == (0, 1)        # Auto and Quick always
    target = next(b for b in layout.buttons if b.kind == "page" and b.page == 4)
    p.g.frame(H.motion(target.box.center))
    p.g.h.click(target.box.center)
    assert page.page == 3                                       # "3" is index 4
    nxt = row.layout().buttons[-1]
    p.g.frame(H.motion(nxt.box.center))
    p.g.h.click(nxt.box.center)
    assert page.page == 4 and 5 in row.layout().pages
    page._go(len(page.pages) - 1)
    assert not row.layout().next_enabled and page.page == 100
    assert 101 in row.layout().pages
    prev = row.layout().buttons[0]
    p.g.frame(H.motion(prev.box.center))
    p.g.h.click(prev.box.center)
    assert page.page == 99


def test_ac40_the_wheel_does_nothing(pages):
    pages.port.data["auto"] = [filled()] * 6
    menu, page = pages.open("load")
    pages.g.frame(H.wheel((544, 187), -1), H.wheel((544, 187), 1))
    assert page.page == "auto" and page.grid.scroll == 0 and pages.port.acts() == []


# --- AC-F11-44: keys and focus ------------------------------------------------------------------

def test_ac44_tab_order_home_end_and_left_to_the_sidebar(tmp_path):
    pages = Pages(tmp_path, pages=3)                            # M20: no arrows with 3 pages
    menu, page = pages.open("load")
    g = pages.g
    scope = menu.scope
    menu.scope.focus(menu.buttons[-1], InputKind.KEYS)        # the sidebar's last (Quit)
    order = []
    for _ in range(6 + 5 + 1):
        g.frame(H.key(pygame.K_TAB))
        w = scope.focused
        if w is page.grid:
            order.append(("cell", page.grid.focus_cell))
        elif w is page.row:
            order.append(("row", page.row.focused_button().label))
        else:
            order.append(("sidebar", w.label()))
    assert order[:6] == [("cell", i) for i in range(6)]
    assert order[6:11] == [("row", b) for b in ["Auto", "Quick", "1", "2", "3"]]
    assert order[11][0] == "sidebar"
    scope.focus(page.grid, InputKind.KEYS)
    g.frame(H.key(pygame.K_END))
    assert page.grid.focus_cell == 5
    g.frame(H.key(pygame.K_HOME))
    assert page.grid.focus_cell == 0
    g.frame(H.key(pygame.K_LEFT))
    assert scope.focused is menu.button("load")                 # back to the sidebar
    g.frame(H.key(pygame.K_RIGHT))
    assert scope.focused is page.grid and page.grid.focus_cell == 0   # last focused
    g.frame(H.key(pygame.K_DOWN))
    assert page.grid.focus_cell == 3
    g.frame(H.key(pygame.K_DOWN))
    assert scope.focused is page.row


def test_ac44_default_cell_page_change_keeps_position_and_row_follows(tmp_path):
    port = FakePort()
    port.default = 4
    p = Pages(tmp_path, port=port)
    menu, page = p.open("load")
    g = p.g
    menu.scope.focus(menu.button("load"), InputKind.KEYS)
    g.frame(H.key(pygame.K_RIGHT))                             # no last focus: the default
    assert menu.scope.focused is page.grid and page.grid.focus_cell == 4
    g.frame(H.key(pygame.K_PAGEDOWN))
    assert page.page == "quick" and page.grid.focus_cell == 4  # same cell position
    menu.scope.focus(page.row, InputKind.KEYS)
    page.row.focus_button(("page", 1))
    g.frame(H.key(pygame.K_PAGEDOWN))
    assert page.page == 1 and page.row.focused_button().page == 2   # the new current's


def test_ac44_choose_by_keys_and_mouse(pages):
    pages.port.data["auto"] = [filled()] + [SlotView(f"Auto {n}", "empty")
                                            for n in range(2, 7)]
    menu, page = pages.open("load")
    pages.focus_grid(menu, page, 0)
    pages.g.frame(H.key(pygame.K_RETURN))
    pages.g.frame(H.pad(pygame.CONTROLLER_BUTTON_A))
    cell = page.grid.cell_box(1)
    pages.g.frame(H.motion(cell.center))
    pages.g.h.click(cell.center)
    assert pages.port.acts() == [("choose", "auto", 0, "load", InputKind.KEYS),
                                 ("choose", "auto", 0, "load", InputKind.KEYS),
                                 ("choose", "auto", 1, "load", InputKind.MOUSE)]


def test_ac44_a_busy_page_takes_no_input(pages):
    pages.port.data["auto"] = [filled()] * 6
    menu, page = pages.open("load")
    pages.focus_grid(menu, page, 0)
    pages.port.loading = True
    for event in (H.key(pygame.K_RETURN), H.key(pygame.K_RIGHT), H.key(pygame.K_DELETE),
                  H.key(pygame.K_PAGEDOWN), H.key(pygame.K_ESCAPE)):
        pages.g.frame(event)
    assert pages.port.acts() == [] and page.page == "auto"
    assert page.grid.focus_cell == 0 and menu.page is page


# --- AC-F11-43 (page half): the delete controls ------------------------------------------------

@pytest.mark.parametrize("event", [
    H.key(pygame.K_DELETE), H.key(pygame.K_BACKSPACE), H.pad(pygame.CONTROLLER_BUTTON_X),
], ids=["delete", "backspace", "west"])
def test_ac43_delete_keys(pages, event):
    pages.port.data[1] = [filled(1, 1), SlotView("Slot 2", "empty")] + [
        SlotView(f"Slot {n}", "damaged", deletable=True) for n in range(3, 7)]
    menu, page = pages.open("save")
    pages.focus_grid(menu, page, 0)
    pages.g.frame(event)
    page.grid.focus_cell = 1                                    # empty: nothing
    pages.g.frame(event)
    page.grid.focus_cell = 2                                    # damaged: deletable
    pages.g.frame(event)
    assert pages.port.acts() == [("delete", 1, 0, InputKind.KEYS),
                                 ("delete", 1, 2, InputKind.KEYS)]


def test_ac43_the_x_hover_ring_and_click(pages):
    pages.port.data["auto"] = [filled()] + [SlotView(f"Auto {n}", "empty")
                                            for n in range(2, 7)]
    menu, page = pages.open("load")
    g = pages.g
    g.frame(H.motion((544, 187)))                               # hover focuses the cell
    assert menu.scope.focused is page.grid and page.grid.focus_cell == 0
    g.frame(H.motion((644, 140)))
    assert page.grid.delete_hover and menu.scope.focused is page.grid
    cfg = plain_theme().cfg
    ring = g.px((644 - 15, 140))                                # inside the 2-unit ring
    assert close(ring, cfg.button.focused.border_color, 3)
    g.h.click((644, 140))
    assert pages.port.acts() == [("delete", "auto", 0, InputKind.MOUSE)]
    g.frame(H.motion((544, 187)))
    assert not page.grid.delete_hover
    g.h.click((544, 187))                                       # the cell: choose
    assert pages.port.acts()[-1] == ("choose", "auto", 0, "load", InputKind.MOUSE)


# --- AC-F11-46 (page half): "No saves yet." and F32's reason ------------------------------------

def test_ac46_no_saves_replaces_the_grid_and_keeps_the_row(pages, monkeypatch):
    pages.port.none = True
    menu, page = pages.open("load")
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    message = next(c for c in calls if c.text == "No saves yet.")
    assert message.pos == (820, page.layout.grid.center[1])
    assert page.grid not in menu.scope.widgets() and page.row in menu.scope.widgets()
    assert page.default_widget() is page.row
    pages.port.none = False
    pages.g.frame()
    assert page.grid in menu.scope.widgets()                    # a save came: the grid


def test_blocked_page_shows_the_reason_without_grid_or_row(pages, monkeypatch):
    pages.port.reason["save"] = "Saving is off in this scene."
    menu, page = pages.open("save")
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    assert any(c.text == "Saving is off in this scene." for c in calls)
    assert menu.page_groups == [] and page.default_widget() is None


# --- AC-F11-47: quick-menu Save and the title page ------------------------------------------------

def test_ac47_quick_menu_save_back_closes_the_menu(pages):
    g = pages.g
    open_save_from_quick(g.shell, InputKind.KEYS)
    menu = g.menu
    assert isinstance(menu.page, SavePage) and menu.page.mode == "save"
    assert menu.scope.focused is menu.page.grid
    g.frames(FADE + 1)
    g.frame(H.key(pygame.K_ESCAPE))
    g.frames(FADE + 1)
    assert g.stack == [g.textbox]


def test_ac47_after_switching_to_load_back_closes_only_the_page(pages):
    g = pages.g
    open_save_from_quick(g.shell, InputKind.MOUSE)
    menu = g.menu
    g.frames(FADE + 1)
    menu.open_page("load")
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_B))
    assert menu.page is None and g.top is menu


def test_ac47_title_page_focus_start_and_return(tmp_path):
    rig = Rig(tmp_path)
    port = FakePort()
    port.default = 2
    register_save_pages(rig.shell, port, can_save=lambda: False, visible=lambda: True)
    rig.app.screens.replace_all(rig.shell.initial_screens())
    rig.frames(31)
    title = rig.title
    assert [b.label() for b in title.buttons] == ["New Game", "Load", "Quit"]
    rig.frame(H.key(pygame.K_DOWN))
    rig.frame(H.key(pygame.K_DOWN))
    rig.frame(H.key(pygame.K_RETURN))
    screen = rig.app.screens.top
    assert isinstance(screen, GameMenuScreen) and screen.from_title
    assert [b.label() for b in screen.buttons] == ["Return", "Load"]
    page = screen.page
    assert screen.scope.focused is page.grid and page.grid.focus_cell == 2   # not Return
    assert screen.scope.visible
    rig.frames(FADE + 1)
    rig.frame(H.pad(pygame.CONTROLLER_BUTTON_START))
    assert rig.app.screens.top is screen                        # Start: nothing
    rig.frame(H.key(pygame.K_ESCAPE))
    rig.frames(FADE + 1)
    assert rig.stack == [title] and title.scope.focused is title.buttons[1]
    assert ("remember", "load", "auto") in port.calls


def test_ac47_title_page_by_click_focuses_the_default_quietly(tmp_path):
    rig = Rig(tmp_path)
    register_save_pages(rig.shell, FakePort(), can_save=lambda: False, visible=lambda: True)
    rig.app.screens.replace_all(rig.shell.initial_screens())
    rig.frames(31)
    load = rig.title.buttons[1]
    rig.frame(H.motion(load.box.center))
    rig.h.click(load.box.center)
    screen = rig.app.screens.top
    assert isinstance(screen, GameMenuScreen)
    assert screen.scope.focused is screen.page.grid and not screen.scope.visible


def test_in_game_start_closes_the_game_menu_on_a_page(pages):
    menu, page = pages.open("save")
    pages.g.frame(H.pad(pygame.CONTROLLER_BUTTON_START))
    pages.g.frames(FADE + 1)
    assert [type(s) for s in pages.g.stack] == [TextboxScreen]


# --- AC-F11-48: text from a save is plain ---------------------------------------------------------

@pytest.mark.parametrize("raw, shown", [
    ("a\ud800b", "a�b"), ("\udfff", "�"),
    ("\U0001f338", "\U0001f338"),
    ("x‮y z\x00w\x1bv", "xyzwv"),
    ("\U0001f469‍\U0001f4bb", "\U0001f469‍\U0001f4bb"),
    ("a" + "́" * 200, "a" + "́" * 99 + "…"),
    ("{player}", "{player}"), ("{b}x{/b}", "{b}x{/b}"),
    ("雨の日に、灯籠を流した。", "雨の日に、灯籠を流した。"), ("مرحبا بك", "مرحبا بك"),
])
def test_ac48_render_safe_text(pages, monkeypatch, raw, shown):
    assert shown_text(raw) == shown
    pages.port.data["auto"] = [filled(description=shown_text(raw))] + [
        SlotView(f"Auto {n}", "empty") for n in range(2, 7)]
    pages.open()
    with spy_draw_text(monkeypatch) as calls:
        pages.g.frame()
    drawn = next(c for c in calls if c.pos == (424, 295))
    assert type(drawn.text) is str
    expected = shown_text(raw)
    assert drawn.text == expected or (drawn.text.endswith("…")
                                      and expected.startswith(drawn.text[:-1]))


# --- AC-F11-57: no code from saves; import rules ---------------------------------------------------

SCANNED = ["engine/persist/saves.py", "engine/persist/writer.py", "engine/render/thumbnail.py",
           "engine/app/saves.py", "engine/ui/notice.py", "engine/ui/builtin/save_page.py",
           "engine/ui/page_row.py"]
BANNED_MODULES = {"pickle", "marshal", "shelve", "importlib", "ctypes"}
BANNED_CALLS = {"eval", "exec", "compile", "__import__"}


def _imports(tree: ast.AST) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_ac57_no_code_loading_and_ui_never_imports_persist():
    bad = []
    for rel in SCANNED:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        bad += [f"{rel}: {n}" for n in _imports(tree) if n.split(".")[0] in BANNED_MODULES]
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name in BANNED_CALLS and not (name == "compile" and isinstance(
                        func, ast.Attribute) and ast.unparse(func.value) == "re"):
                    bad.append(f"{rel}:{node.lineno}: {name}")
    for path in sorted((REPO / "engine" / "ui").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad += [f"{path.name}: {n}" for n in _imports(tree) if n.startswith("engine.persist")]
    assert bad == []


def test_page_row_is_a_widget_the_page_reuses(pages):
    menu, page = pages.open("load")
    assert isinstance(page.row, PageRow) and page.nav_extras == {"shoulders", "delete"}
    assert menu.reader.extras == {"shoulders", "delete"}
    menu.close_page()
    assert menu.reader.extras == frozenset()
    assert Nav.DELETE.value == "delete"
