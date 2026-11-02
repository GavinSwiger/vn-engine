"""F21 step 3 — ``CodexView`` and ``CodexPage`` over Port P (06 §0.3): AC-F21-22 to 29.

Port P is a fake ``CodexPort`` over 06's seven entries with a ``mark_read`` spy. Logic rows
use F05's M20 metrics (``FixedFontAssets``: 20 units per grapheme at 28) and a bare
``FocusScope`` as the host; drawing rows use a ``TestShell`` (real assets, default theme) on
a 1280×720 canvas with a draw recorder. The tab-overflow row of AC-26 is in
``tests/ui/test_page_row.py`` (D6)."""

import dataclasses
from types import SimpleNamespace

import pygame

from engine.app.text_check import contrast_ratio
from engine.core.config_schema import ThemeConfig
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.render.canvas import Canvas, RenderQuality
from engine.render.text import Face
from engine.runtime.codex import CodexCategory, CodexEntry
from engine.ui.builtin.codex_page import (CodexFilter, CodexPage, CodexView, PickAction,
                                          fit_picture, locked_color, new_dot_color)
from engine.ui.focus import Box, FocusScope
from engine.ui.nav import InputKind, Nav
from engine.ui.paint import Painter
from engine.ui.theme import Words, plain_theme
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fixed_font import FixedFontAssets, tagged
from tests.fakes.ui_shell import TestShell
from tests.fixtures.F04 import gen_images as gen
from tests.render.conftest import make_assets

SLOT = Box(416, 112, 808, 552)
FESTIVAL = CodexCategory("tip", "Festival", None)
LEGENDS = CodexCategory("tip", "Legends", None)
TIPS = CodexCategory("tip", None, "codex_tips")
THINGS = CodexCategory("item", "Things", None)
ITEMS = CodexCategory("item", None, "codex_items")
CATEGORIES = (FESTIVAL, LEGENDS, TIPS, THINGS, ITEMS)
BERRY, MAUVE, PINK_WHITE = (0xA0, 0x28, 0x60), (0x6E, 0x5E, 0x68), (0xFF, 0xF4, 0xF8)


def entry(name, kind, title, category, *paragraphs, image=None) -> CodexEntry:
    return CodexEntry(name, kind, title, category, image,
                      tuple(tagged(p) for p in paragraphs), "codex:" + name, "main.vns", 1)


ENTRIES = (entry("lanterns", "tip", "Paper Lanterns", FESTIVAL,
                 "Lanterns are folded from washi paper.", "Each carries one {i}wish{/i}."),
           entry("fireworks", "tip", "Fireworks", FESTIVAL),
           entry("river_god", "tip", "The River God", LEGENDS),
           entry("moon", "tip", "The Moon", TIPS),
           entry("red_lantern", "item", "Red Lantern", THINGS),
           entry("coin", "item", "Old Coin", THINGS),
           entry("brass_key", "item", "Brass Key", ITEMS))


class PortP:
    """06 §0.3's Port P: ``t`` and ``i`` per row; ``marks`` spies ``mark_read``."""

    def __init__(self, t=(), i=(), *, read=(), show_locked=False, entries=ENTRIES,
                 pictures=None) -> None:
        self.t, self.i = tuple(t), tuple(i)
        self.read = set(read)
        self.marks: list[str] = []
        self.show_locked = show_locked
        self._entries = tuple(entries)
        self.pictures = dict(pictures or {})

    def entries(self):
        return self._entries

    def categories(self):
        return CATEGORIES

    def tips(self):
        return self.t

    def items(self):
        return self.i

    def is_read(self, name):
        return name in self.read

    def mark_read(self, name):
        self.marks.append(name)
        self.read.add(name)

    def picture(self, image):
        return self.pictures.get(image)


M20 = SimpleNamespace(theme=plain_theme(), words=Words(), assets=FixedFontAssets())


class Host:
    """A view in a bare ``FocusScope`` (the host's side: set_groups, keys, clicks)."""

    def __init__(self, port: PortP, *, ui=M20, box: Box = SLOT, scale: float = 1.0,
                 **kwargs) -> None:
        self.port = port
        self.scope = FocusScope()
        self.view = CodexView(port, ui=ui, scope=lambda: self.scope, **kwargs)
        self.build(box, scale)

    def build(self, box: Box = SLOT, scale: float = 1.0) -> None:
        self.scope.set_groups(self.view.build(box, scale))

    def key(self, nav: Nav) -> bool:
        """A key as the game menu sends it: the scope's press (the widgets route)."""
        return self.scope.press(nav)

    def click(self, w, pos) -> None:
        """A button-1 click as ``MenuScreen`` does it."""
        self.scope.focus(w, InputKind.MOUSE)
        w.on_mouse("down", pos)
        w.on_mouse("up", pos)
        if w.accepts_click(pos):
            w.activate()

    def focus(self, w) -> None:
        assert self.scope.focus(w, InputKind.KEYS)

    @property
    def tabs(self) -> list[str]:
        return [tab.label for tab in self.view.tabs]

    def rows(self, tab: int | None = None) -> list[str]:
        view = self.view
        rows = view.tabs[view.tab if tab is None else tab].rows if view.tabs else ()
        return ["???" if r.locked else r.entry.title for r in rows]

    def row_center(self, index: int) -> tuple[float, float]:
        return self.view.list.row_box(index).center


def draw(view: CodexView, shell: TestShell, scope: FocusScope | None = None) -> Canvas:
    """One frame of ``view`` as the game menu draws a page: ``draw``, then the widgets."""
    canvas = Canvas(shell.assets)
    canvas.bind(pygame.Surface((1280, 720)), Viewport.compute((1280, 720), (1280, 720)),
                RenderQuality.FINAL)
    p = shell.painter
    p.bind(canvas)
    view.draw(canvas, p)
    for w in (view.tab_row, view.list, view.body, view.pick_button):
        if w is not None and (scope is None or scope.contains(w)):
            focused = scope is not None and scope.focused is w
            w.draw(p, w.look(focused=focused))
    return canvas


# --- AC-F21-22 ------------------------------------------------------------------------------

def test_ac22_what_the_view_lists(monkeypatch):
    moved = tuple(dataclasses.replace(e, category=LEGENDS) if e.name == "lanterns" else e
                  for e in ENTRIES)
    rows = [
        (PortP(), {}, [], []),
        (PortP(("fireworks", "lanterns")), {}, ["Festival"], ["Paper Lanterns", "Fireworks"]),
        (PortP(("moon", "lanterns"), ("coin", "brass_key", "red_lantern")), {},
         ["Festival", "Tips", "Things", "Items"], ["Paper Lanterns"]),
        (PortP(("lanterns",), ("coin",)), dict(filter=CodexFilter(kinds=frozenset({"item"}))),
         ["Things"], ["Old Coin"]),
        (PortP(("lanterns", "moon"), ("coin",)),
         dict(filter=CodexFilter(categories=frozenset({"Things", "codex_tips"}))),
         ["Tips", "Things"], ["The Moon"]),
        (PortP(("lanterns",)), dict(filter=CodexFilter(categories=frozenset({"Legends"}))),
         [], []),
        (PortP(("lanterns",)), dict(title=True), ["Festival"], ["Paper Lanterns"]),
        (PortP(("lanterns",), entries=moved), {}, ["Legends"], ["Paper Lanterns"]),
    ]
    for port, kwargs, tabs, first in rows:
        host = Host(port, **kwargs)
        assert (host.tabs, host.rows()) == (tabs, first), (port.t, port.i, kwargs)
    things = Host(PortP(("moon", "lanterns"), ("coin", "brass_key", "red_lantern")))
    assert things.rows(2) == ["Old Coin", "Red Lantern"]               # order obtained
    # The title's page lists tips only (CodexPage(from_title=True)).
    page_host = SimpleNamespace(shell=M20, scope=FocusScope(),
                                painter=SimpleNamespace(text_scale=lambda: 1.0))
    page = CodexPage(PortP(("lanterns",), ("coin",)), from_title=True)
    page.build(page_host, SLOT)
    assert [t.label for t in page.view.tabs] == ["Festival"] and page.heading == "codex"
    # Empty: "Nothing here yet." centred in the box in list.empty.text_color, no widgets.
    shell = TestShell()
    empty = CodexView(PortP(), ui=shell)
    assert empty.build(SLOT, 1.0) == []
    with spy_draw_text(monkeypatch) as calls:
        draw(empty, shell)
    assert [(c.text, c.color) for c in calls] == [("Nothing here yet.", MAUVE)]
    x, y, w, h = calls[0].bounds
    assert abs(x + w / 2 - 820) <= 1 and abs(y + h / 2 - 388) <= 1


# --- AC-F21-23 ------------------------------------------------------------------------------

def test_ac23_show_locked():
    host = Host(PortP(("lanterns",), show_locked=True))
    assert host.tabs == ["Festival", "Legends", "Tips"]
    assert [host.rows(i) for i in range(3)] == [["Paper Lanterns", "???"], ["???"], ["???"]]
    view = host.view
    host.focus(view.list)
    host.key(Nav.DOWN)                                               # focus skips ??? rows
    assert view.list.focus_row == 0 and host.scope.focused is not view.list
    assert not view.list.on_mouse("down", host.row_center(1))       # a click does nothing
    assert view.selected == "lanterns" and host.port.marks == ["lanterns"]
    view._select_tab(1)                                              # only ??? rows
    assert view.selected is None and view._detail.title == () and view.body_rows == []
    none = Host(PortP(show_locked=True))
    assert none.tabs == ["Festival", "Legends", "Tips"]
    assert all(r == "???" for i in range(3) for r in none.rows(i))
    assert none.view.selected is None and none.port.marks == []
    items = Host(PortP(("lanterns",), ("coin",), show_locked=True))
    assert items.tabs == ["Festival", "Legends", "Tips", "Things"]
    assert items.rows(3) == ["Old Coin"]                             # no ??? items
    assert Host(PortP(("lanterns",))).tabs == ["Festival"]          # show_locked off


# --- AC-F21-24 ------------------------------------------------------------------------------

def test_ac24_selection():
    port = PortP(("lanterns", "fireworks", "river_god"))
    host = Host(port)
    view = host.view
    assert view.selected == "lanterns" and view.default_widget() is view.list
    assert view.list.focus_row == 0
    host.focus(view.list)
    assert host.key(Nav.DOWN) and view.selected == "fireworks"      # in the same press
    host.key(Nav.UP)
    host.click(view.list, host.row_center(1))
    assert view.selected == "fireworks" and host.scope.focused is view.list
    view.tab_row.on_select(1)                                        # the Legends tab
    assert view.selected == "river_god"
    view.tab_row.on_select(0)
    host.click(view.list, host.row_center(1))
    host.build()
    assert view.selected == "fireworks" and view.list.focus_row == 1
    port.t = ("lanterns", "river_god")
    host.build()
    assert view.selected == "lanterns"


# --- AC-F21-25 ------------------------------------------------------------------------------

def test_ac25_new_marks(monkeypatch):
    port = PortP(("lanterns", "fireworks"))
    shell = TestShell()
    view = CodexView(port, ui=shell)
    view.build(SLOT, 1.0)
    assert port.marks == ["lanterns"]
    dots = []
    monkeypatch.setattr(Painter, "ellipse", lambda self, box, color, **k: dots.append(box))
    draw(view, shell)
    assert [round(b.y + 5 - view.list.box.y) for b in dots] == [55 + 27]   # row 1 only
    scope = FocusScope(view.build(SLOT, 1.0))
    view._scope = lambda: scope
    scope.focus(view.list, InputKind.KEYS)
    scope.press(Nav.DOWN)
    assert port.marks == ["lanterns", "fireworks"]
    scope.press(Nav.UP)
    assert port.marks == ["lanterns", "fireworks"]                  # already read
    read = PortP(("lanterns", "fireworks"), read=("lanterns", "fireworks"))
    view = CodexView(read, ui=shell)
    view.build(SLOT, 1.0)
    dots.clear()
    draw(view, shell)
    assert read.marks == [] and dots == []


# --- AC-F21-26 ------------------------------------------------------------------------------

def test_ac26_navigation_and_the_pick_action():
    long = "Lanterns float down the river all night long, one after another."
    tall = dataclasses.replace(ENTRIES[0], paragraphs=tuple(tagged(" ".join([long] * 6))
                                                            for _ in range(3)))
    port = PortP(("lanterns", "fireworks", "river_god"), ("coin",),
                 entries=(tall, *ENTRIES[1:]))
    host = Host(port)
    view, scope = host.view, host.scope
    host.focus(view.list)
    assert host.key(Nav.UP) and scope.focused is view.tab_row       # first row: the tabs
    assert view.tab_row.focused_button().page == 0
    host.focus(view.list)
    assert host.key(Nav.RIGHT) and scope.focused is view.body
    assert host.key(Nav.LEFT) and scope.focused is view.list and view.list.focus_row == 0
    host.key(Nav.RIGHT)
    body = view.body
    step = body.box.h - 39                                           # F13: view − p
    host.key(Nav.DOWN)
    assert body.scroll == step
    host.key(Nav.PAGE_DOWN)
    assert body.scroll == 2 * step
    host.key(Nav.PAGE_UP)
    assert body.scroll == step
    host.focus(view.list)
    assert host.key(Nav.ACTIVATE) and scope.focused is view.body
    # Wheel: the list by 3 rows, the body by F13's notch.
    many = Host(PortP(tuple(f"t{i}" for i in range(30)), entries=tuple(
        entry(f"t{i}", "tip", f"Tip {i}", FESTIVAL) for i in range(30))))
    many.view.list.on_mouse("wheel", many.row_center(0), notches=-1)
    assert many.view.list.scroll == 3 * 55
    body.scroll = 0.0
    body.on_mouse("wheel", body.box.center, notches=-1)
    assert body.scroll == 3 * (39 + 8)
    # Pick mode.
    picks: list[str] = []
    pick = Host(PortP(("lanterns",), ("coin",)),
                filter=CodexFilter(kinds=frozenset({"item"})),
                pick=PickAction("Present", picks.append))
    pv = pick.view
    assert pv.pick_button.label() == "Present" and pv.selected == "coin"
    pick.focus(pv.list)
    pick.key(Nav.ACTIVATE)
    assert pick.scope.focused is pv.pick_button and picks == []
    pick.key(Nav.ACTIVATE)
    assert picks == ["coin"] and pv.selected == "coin" and pick.scope.focused is pv.pick_button
    assert pv.on_nav(Nav.ACTIVATE) and picks == ["coin", "coin"]    # a host's on_nav first
    # A tab button activates another tab (AC-24's tab row).
    host.focus(view.tab_row)
    view.tab_row.focus_button(("page", 1))
    host.key(Nav.ACTIVATE)
    assert view.selected == "river_god"


# --- AC-F21-27 ------------------------------------------------------------------------------

def test_ac27_text_size_150():
    entries = tuple(entry(f"t{i}", "tip", f"Tip {i}", FESTIVAL, "One short paragraph.",
                          "Another one.") for i in range(40))
    port = PortP(tuple(e.name for e in entries), entries=entries)
    host = Host(port)
    view = host.view
    host.click(view.list, host.row_center(0))
    view.list.focus_index(20)
    view._select_row(20)
    made = view.layouts_made
    host.build(SLOT, 1.5)
    layout = view.layout
    assert (layout.tab_row, layout.list) == (None, Box(416, 112, 300, 552))
    assert view.list.row_height == 75 and view.selected == "t20"
    assert view.layouts_made == made + 2                             # one per paragraph
    row = view.list.row_box(20)
    assert row.y >= view.list.box.y and row.bottom <= view.list.box.bottom
    three = Host(PortP(("lanterns", "river_god", "moon")), scale=1.5)
    assert (three.view.layout.list, three.view.layout.panel) == (
        Box(416, 199, 300, 465), Box(736, 199, 488, 465))


# --- AC-F21-28 ------------------------------------------------------------------------------

def test_ac28_the_page_on_screen(monkeypatch):
    long_title = "The Very Long Story of the Lantern Maker of the Upper River"
    assert len(long_title) <= 60
    body = entry("lanterns", "tip", "Paper Lanterns", FESTIVAL,
                 "Lanterns are folded.",
                 "Each carries one {i}wish{/i}, {b}bold{/b} {color=#a02860}red{/color} it.")
    entries = (body, entry("fireworks", "tip", long_title, FESTIVAL), *ENTRIES[2:])
    port = PortP(("lanterns", "fireworks", "river_god"), entries=entries, show_locked=True)
    shell = TestShell()
    scope = FocusScope()
    view = CodexView(port, ui=shell, scope=lambda: scope)
    scope.set_groups(view.build(SLOT, 1.0))
    frames, dots = [], []
    real_frame = Painter.widget_frame
    monkeypatch.setattr(Painter, "widget_frame", lambda self, box, area, look, **k: (
        frames.append((box, area, look)), real_frame(self, box, area, look, **k))[1])
    monkeypatch.setattr(Painter, "ellipse",
                        lambda self, box, color, **k: dots.append((box, tuple(color))))
    with spy_draw_text(monkeypatch) as calls:
        draw(view, shell, scope)
    tab_boxes = [b.box for b in view.tab_row.layout().buttons]
    assert any(f[2].selected and f[0] == tab_boxes[0] for f in frames)  # the current tab
    row0 = view.list.row_box(0)
    assert any(f[1] == "list" and f[2].selected and f[0] == row0 for f in frames)
    rows = view.list.row_box(1)
    assert dots == [(Box(rows.right - 24 - 5, rows.y + rows.h / 2 - 5, 10, 10), BERRY)]
    def call(text):
        return next(c for c in calls if c.text == text)

    fitted = next(c for c in calls if c.text.startswith("The Very"))
    assert fitted.text.endswith("…") and fitted.bounds[2] <= 236
    assert fitted.color == shell.theme.cfg.button.text_color and fitted.pos[0] == 416 + 16
    lanterns = call("Lanterns are folded.")
    assert lanterns.color == shell.theme.cfg.panel.text_color and lanterns.font.size == 28
    assert call("wish").font.bundled is Face.ITALIC
    assert call("bold").font.bundled is Face.BOLD and call("red").color == BERRY
    heading = next(c for c in calls if c.text == "Paper Lanterns" and c.font.size == 32)
    assert heading.font.bundled is Face.BOLD and heading.color == BERRY
    assert heading.pos[0] == 756                                    # the title box's left
    # Paragraphs 12 apart: the second starts one line (39) + 12 below the first.
    second = next(c for c in calls if c.text.startswith("Each carries"))
    assert round(second.pos[1] - lanterns.pos[1]) == 39 + 12
    # The ??? row (the Tips tab: moon) in codex.locked.text_color.
    view._select_tab(2)
    with spy_draw_text(monkeypatch) as calls:
        draw(view, shell, scope)
    assert ("???", MAUVE) in [(c.text, c.color) for c in calls]
    # The detail title wraps to 2 lines, then "…".
    port.t = ("lanterns", "fireworks", "river_god")
    view._select_tab(0)
    view._select_row(1)
    title = view._detail.title
    assert len(title) == 2 and title[-1].endswith("…") and view.layout.title.h == 2 * 45
    # Default colors follow their tokens (an author's change too); contrast on #FFF4F8.
    # 01 §6 claims 7.0:1 and 5.7:1; F10's function gives 6.59:1 and 5.64:1 (reported).
    cfg = ThemeConfig()
    assert (new_dot_color(cfg), locked_color(cfg)) == (BERRY, MAUVE)
    assert contrast_ratio(BERRY, PINK_WHITE) >= 6.5 and contrast_ratio(MAUVE, PINK_WHITE) >= 5.6


# --- AC-F21-29 ------------------------------------------------------------------------------

def test_ac29_pictures(tmp_path, monkeypatch, caplog):
    box = Box(756, 200, 448, 200)
    assert fit_picture((1600, 900), box) == Box(802, 200, 356, 200)
    assert fit_picture((100, 50), box) == Box(930, 275, 100, 50)        # never scaled up
    assert fit_picture((16, 9), box, upscale=True) == Box(802, 200, 356, 200)
    gen.write(tmp_path, {"images/items/big.png": gen.block(1600, 900, (10, 200, 10)),
                         "images/items/small.png": gen.block(100, 50, (200, 10, 10))})
    shell = TestShell(assets=make_assets(GamePaths(tmp_path.resolve())))
    pictures = {"big": "images/items/big.png", "small": "images/items/small.png",
                "gone": "images/items/gone.png", "solid": (200, 40, 80)}
    lanterns = dataclasses.replace(ENTRIES[0], image="big")
    port = PortP(("lanterns", "river_god"), entries=(lanterns, *ENTRIES[1:]),
                 pictures=pictures)
    view = CodexView(port, ui=shell)
    view.build(SLOT, 1.0)
    assert view.layout.picture == box
    loads = []
    real_load = type(shell.assets)._load_image
    monkeypatch.setattr(type(shell.assets), "_load_image",
                        lambda self, ref: (loads.append(ref), real_load(self, ref))[1])

    def shown(image):
        port._entries = (dataclasses.replace(ENTRIES[0], image=image), *ENTRIES[1:])
        view.selected = None
        view.build(SLOT, 1.0)
        return draw(view, shell).surface

    def near(surface, at, color) -> bool:
        return all(abs(a - b) <= 4 for a, b in zip(surface.get_at(at)[:3], color))

    surface = shown("big")                                             # 356×200 at x 802
    assert near(surface, (803, 300), (10, 200, 10)) and near(surface, (1157, 300), (10, 200, 10))
    assert not near(surface, (800, 300), (10, 200, 10))
    assert not near(surface, (1160, 300), (10, 200, 10))
    shown("big")
    assert loads == ["images/items/big.png"]                           # then a cache hit
    surface = shown("small")                                           # 100×50 at (930, 275)
    assert near(surface, (931, 276), (200, 10, 10)) and near(surface, (1029, 324), (200, 10, 10))
    assert not near(surface, (928, 276), (200, 10, 10))
    assert not near(surface, (1032, 276), (200, 10, 10))
    blank = shown("nothing").get_at((980, 300))                        # None: nothing
    caplog.clear()
    surface = shown("gone")                                            # a placeholder
    first = [r for r in caplog.records if r.name == "vn.assets"]
    shown("gone")
    assert len(first) == 1 and len([r for r in caplog.records if r.name == "vn.assets"]) == 1
    assert surface.get_at((980, 300)) == blank
    surface = shown("solid")                                           # a 16:9 box
    assert near(surface, (803, 300), (200, 40, 80)) and near(surface, (1157, 300), (200, 40, 80))
    assert not near(surface, (800, 300), (200, 40, 80))
