"""F34 P1 — tile grid, thumbnails, Gallery page and viewer over fake ports: AC-F34-18 to 27.

The page runs in F10's real ``GameMenuScreen`` opened from the title (its sidebar is Return
plus the page's entry; F34-W3 adds the ``extras`` menu, so here the page sits on the title's
``load`` id). Pictures are real PNG files in a temporary game folder; a ``FakePrefetcher``
"decodes" by loading through the asset manager one per pump and can refuse refs. Caption
cuts use F05's M20 metrics."""

import math
from dataclasses import dataclass
from types import SimpleNamespace

import pygame

from engine.app.text_check import contrast_ratio
from engine.core.config_schema import ThemeConfig
from engine.core.paths import GamePaths
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.gallery_page import GalleryPage, gallery_model
from engine.ui.builtin.gallery_viewer import CROSSFADE_S, GalleryViewer, fill_color, fit_box
from engine.ui.builtin.tile_grid import PER_PAGE, Tile, TileGrid, tile_grid_layout
from engine.ui.focus import Box
from engine.ui.layouts import PAGE_BODY
from engine.ui.menu_screen import Phase
from engine.ui.menus import MenuEntry, MenuRegistry, UiOverrides
from engine.ui.nav import InputKind
from engine.ui.theme import Words, plain_theme
from engine.ui.thumbs import ThumbCache
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fixed_font import FixedFontAssets
from tests.fakes.ui_shell import TestShell, UiHarness
from tests.fixtures.F04 import gen_images as gen
from tests.render.conftest import make_assets

K = pygame
RED, GREEN, BLUE, GOLD = (200, 30, 30), (30, 200, 30), (30, 30, 200), (220, 180, 40)


@dataclass(frozen=True)
class Entry:
    picture: str
    title: str
    versions: tuple[str, ...] = ()


def ref(name: str) -> str:
    return "images/" + name.replace(" ", "/") + ".png"


class FakePrefetcher:
    """``request`` replaces the queue; ``pump`` "decodes" the head by loading it (one per
    pump); refs in ``refuse`` are dropped as ``ImagePrefetcher`` drops an over-size one."""

    def __init__(self, assets, refuse=()) -> None:
        self.assets = assets
        self.refuse = set(refuse)
        self.queue: list[str] = []
        self.requests: list[list[str]] = []
        self.pumps = 0

    @property
    def pending(self) -> bool:
        return bool(self.queue)

    def request(self, wanted) -> None:
        self.queue = [w.ref for w in wanted if not self.assets.is_cached(w.ref)]
        self.requests.append(list(self.queue))

    def pump(self) -> None:
        self.pumps += 1
        if self.queue:
            head = self.queue.pop(0)
            if head not in self.refuse:
                self.assets.image(head)


class Port:
    def __init__(self, entries, unlocked=(), *, show_locked=True, thumbs=None, pictures=None):
        self._entries = tuple(entries)
        self.names = set(unlocked)
        self.show_locked = show_locked
        self.thumbs = thumbs
        self.pictures = dict(pictures or {})

    def entries(self):
        return self._entries

    def unlocked(self):
        return self.names

    def picture(self, name):
        return self.pictures.get(name, ref(name))


class Shell(TestShell):
    __test__ = False

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.overrides = UiOverrides()
        self.menus = MenuRegistry(overrides=self.overrides)
        self.words.override = {"gallery": "Gallery"}.get        # F34-W3 adds the word


class Rig:
    """A game folder, a shell, a thumbnail cache, and the page in F10's title-page menu."""

    def __init__(self, tmp_path, entries, unlocked, *, colors=None, reduce=True,
                 show_locked=True, refuse=(), prefetch=True, scale=1.0) -> None:
        root = tmp_path / "g"
        root.mkdir(parents=True, exist_ok=True)
        colors = colors or {}
        names = {n for e in entries for n in (e.picture, *e.versions)}
        gen.write(root, {ref(n): colors.get(n, gen.block(320, 180, RED)) for n in names})
        self.assets = make_assets(GamePaths.for_game(root))
        self.decodes: list[str] = []
        real = self.assets._load_image

        def load(r, **kwargs):
            self.decodes.append(r)
            return real(r, **kwargs)

        self.assets._load_image = load
        self.prefetcher = FakePrefetcher(self.assets, refuse) if prefetch else None
        self.thumbs = ThumbCache(self.assets, self.prefetcher)
        self.port = Port(entries, unlocked, show_locked=show_locked, thumbs=self.thumbs)
        self.shell = Shell(assets=self.assets, reduce_motion=reduce)
        if scale != 1.0:
            self.shell.painter.set_text_scale(lambda: scale)
        self.shell.menus.add("title", MenuEntry("load", page=lambda host: GalleryPage(self.port)))
        self.ui = UiHarness(self.shell)
        self.menu: GameMenuScreen | None = None

    def open(self, by=InputKind.KEYS) -> GameMenuScreen:
        self.menu = GameMenuScreen(self.shell, by=by, title_page="load")
        self.shell.stack.push(self.menu)
        self.ui.frame()
        return self.menu

    @property
    def page(self) -> GalleryPage:
        assert self.menu is not None and isinstance(self.menu.page, GalleryPage)
        return self.menu.page

    @property
    def grid(self) -> TileGrid:
        assert self.page.grid is not None
        return self.page.grid

    def key(self, key: int, n: int = 1) -> None:
        for _ in range(n):
            self.ui.frame(self.ui.key(key), self.ui.key(key, up=True))

    def focused_key(self):
        scope = self.menu.scope
        if scope.focused is self.grid.cells_widget:
            return self.grid.page_tiles()[self.grid.cells_widget.focus_cell].key
        if scope.focused is self.grid.row:
            return "row"
        return next((e.id for e, b in zip(self.menu.entries, self.menu.buttons)
                     if b is scope.focused), None)

    @property
    def viewer(self) -> GalleryViewer | None:
        top = self.shell.stack.top
        return top if isinstance(top, GalleryViewer) else None

    def settle(self, n: int = 40) -> None:
        self.ui.frames(n)


def entries(n: int, *, versions=None) -> list[Entry]:
    versions = versions or {}
    return [Entry(f"cg e{i}", f"Picture {i}", tuple(versions.get(i, ()))) for i in range(n)]


def names(n: int) -> set[str]:
    return {f"cg e{i}" for i in range(n)}


# --- AC-F34-18 ------------------------------------------------------------------------------

def test_ac_f34_18_grid_geometry_and_page_row(tmp_path):
    layout = tile_grid_layout(PAGE_BODY)
    assert layout.tiles[0] == Box(420, 112, 188, 138)
    assert layout.pictures[0] == Box(420, 112, 188, 106)
    assert layout.captions[0] == Box(420, 226, 188, 24)
    assert [b.x for b in layout.tiles[:4]] == [420, 624, 828, 1032]       # 188 + 16 apart
    assert [layout.tiles[i].y for i in (0, 4, 8)] == [112, 266, 420]      # pitch 154
    assert layout.row.point == (820, 664)                                 # (416, 608) 808×56
    rows = [(1, False, 1), (12, False, 1), (13, True, 2), (25, True, 3)]
    for n, row_shown, pages in rows:
        rig = Rig(tmp_path / str(n), entries(n), names(n))
        rig.open()
        grid = rig.grid
        assert (rig.menu.scope.contains(grid.row), grid.pages) == (row_shown, pages), n
        cells = grid.cells_widget
        assert [cells.cell_box(i) for i in range(min(n, PER_PAGE))] == \
            list(layout.tiles[:min(n, PER_PAGE)])
        if row_shown:
            bounds = grid.row.box
            assert (bounds.x + bounds.w / 2, bounds.bottom) == (820, 664)
            assert bounds.w <= 808 and bounds.y >= 558                     # under the tiles
        rig.shell.stack.pop()


# --- AC-F34-19 ------------------------------------------------------------------------------

def test_ac_f34_19_locked_tiles(tmp_path, monkeypatch):
    six = entries(6, versions={4: ("cg e4b",)})
    unlocked = {"cg e0", "cg e2", "cg e4b"}                               # e4: a version only
    rows = [
        (True, ["cg e0", "cg e1", "cg e2", "cg e3", "cg e4", "cg e5"],
         ["cg e1", "cg e3", "cg e5"]),
        (False, ["cg e0", "cg e2", "cg e4"], []),
    ]
    for show_locked, keys, locked in rows:
        rig = Rig(tmp_path / str(show_locked), six, unlocked, show_locked=show_locked)
        rig.open()
        tiles = rig.grid.tiles
        assert [t.key for t in tiles] == keys
        assert [t.key for t in tiles if t.locked] == locked
        assert all(t.caption == "" and t.picture is None for t in tiles if t.locked)
        assert next(t for t in tiles if t.key == "cg e4").picture == ref("cg e4b")
        visited = [rig.focused_key()]
        for _ in range(len(keys)):
            rig.key(K.K_RIGHT)
            visited.append(rig.focused_key())
        assert set(visited) == {"cg e0", "cg e2", "cg e4"}                  # never a locked one
        with spy_draw_text(monkeypatch) as calls:
            rig.ui.frame()
        marks = [c for c in calls if c.text == "???"]
        assert len(marks) == len(locked)
        cfg = rig.shell.theme.cfg
        assert all(c.color == tuple(cfg.button.disabled.text_color) for c in marks)
        lay = tile_grid_layout()
        assert sorted(c.pos for c in marks) == sorted(
            lay.pictures[keys.index(k)].center for k in locked)
        monkeypatch.undo()


# --- AC-F34-20 ------------------------------------------------------------------------------

def test_ac_f34_20_keys_pages_wheel_and_click(tmp_path):
    rig = Rig(tmp_path, entries(14), names(14) - {"cg e1", "cg e13"})
    rig.open(InputKind.KEYS)
    grid = rig.grid
    shoulder = rig.ui.pad(K.CONTROLLER_BUTTON_RIGHTSHOULDER)
    shoulder_up = rig.ui.pad(K.CONTROLLER_BUTTON_LEFTSHOULDER)
    steps = [
        (None, "cg e0", 0),                       # by keys: the first unlocked tile
        (K.K_RIGHT, "cg e2", 0),                  # e1 is locked: skipped
        (K.K_DOWN, "cg e6", 0),
        (K.K_PAGEDOWN, "cg e12", 1),              # same position (6) → nearest unlocked (12)
        (K.K_PAGEUP, "cg e0", 0),                 # position 0 again
        (K.K_UP, "row", 0),                       # Up from the top row: the page row
        (K.K_UP, "cg e0", 0),                     # and back into the tiles
        (K.K_LEFT, "load", 0),                    # Left from the first column: the sidebar
        (K.K_RIGHT, "cg e0", 0),
        ("shoulder", "cg e12", 1),                # the bumpers turn pages (nav_extras)
        ("shoulder_up", "cg e0", 0),
    ]
    for key, focused, page in steps:
        if key == "shoulder":
            rig.ui.frame(shoulder)
        elif key == "shoulder_up":
            rig.ui.frame(shoulder_up)
        elif key is not None:
            rig.key(key)
        assert (rig.focused_key(), grid.page) == (focused, page), key
    assert rig.page.nav_extras == frozenset({"shoulders"})
    center = tile_grid_layout().pictures[5].center
    rig.ui.frame(rig.ui.wheel(center, -1))
    assert grid.page == 1                                                 # wheel down: next
    rig.ui.frame(rig.ui.wheel(center, 1))
    assert grid.page == 0
    rig.ui.frame(rig.ui.motion(center), rig.ui.down(center), rig.ui.up(center))
    assert rig.viewer is not None and rig.viewer.current.key == "cg e5"   # a click opens
    rig.ui.frame(rig.ui.key(K.K_ESCAPE))
    locked = tile_grid_layout().pictures[1].center
    rig.ui.frame(rig.ui.motion(locked), rig.ui.down(locked), rig.ui.up(locked))
    assert rig.viewer is None                                             # a locked tile: no
    mouse = Rig(tmp_path / "mouse", entries(3), names(3))
    mouse.open(InputKind.MOUSE)
    assert not mouse.menu.scope.visible                                   # by mouse: nothing


# --- AC-F34-21 ------------------------------------------------------------------------------

def test_ac_f34_21_viewer_fits_and_centres(tmp_path):
    cases = [  # (picture size, a point inside it, a point on the fill)
        ((400, 100), (640, 360), (640, 100)),     # wide: 1280×320 at y 200
        ((100, 400), (640, 360), (300, 360)),     # tall: 180×720 at x 550
        ((16, 9), (20, 20), None),                # tiny: scaled up to the whole canvas
        ((1280, 720), (1, 1), None),
    ]
    for size, inside, outside in cases:
        tag = f"{size[0]}x{size[1]}"
        rig = Rig(tmp_path / tag, [Entry("cg a", "A")], {"cg a"},
                  colors={"cg a": gen.block(*size, GREEN)})
        rig.open()
        rig.key(K.K_RETURN)
        assert rig.viewer is not None
        rig.ui.frame()
        box = fit_box(size)
        assert math.isclose(box.w / box.h, size[0] / size[1])
        assert (box.x + box.w / 2, box.y + box.h / 2) == (640, 360)
        assert box.w == 1280 or box.h == 720
        assert rig.ui.px(*inside) == GREEN, tag
        if outside is not None:
            assert rig.ui.px(*outside) == (0, 0, 0), tag
    assert fill_color(ThemeConfig()) == (0, 0, 0)                         # the default
    themed = SimpleNamespace(gallery=SimpleNamespace(viewer=SimpleNamespace(
        fill_color=(10, 20, 30))))
    assert fill_color(themed) == (10, 20, 30)
    solid = Rig(tmp_path / "solid", [Entry("cg a", "A")], {"cg a"})
    solid.port.pictures["cg a"] = GOLD
    solid.open()
    solid.key(K.K_RETURN)
    assert solid.ui.px(5, 5) == GOLD and solid.ui.px(1275, 715) == GOLD


# --- AC-F34-22 ------------------------------------------------------------------------------

def test_ac_f34_22_viewer_order_and_return_focus(tmp_path):
    many = entries(15, versions={0: ("cg e0b", "cg e0c")})
    unlocked = (names(15) | {"cg e0c"}) - {"cg e1", "cg e13"}             # e0b stays locked
    rig = Rig(tmp_path, many, unlocked)
    rig.open()
    model = gallery_model(rig.port)
    order = [name for _key, name in model.pictures]
    assert order[:3] == ["cg e0", "cg e0c", "cg e2"]                      # versions, next tile
    assert "cg e1" not in order and "cg e0b" not in order
    rig.key(K.K_RETURN)
    viewer = rig.viewer
    steps = [(K.K_LEFT, "cg e0"),                  # nothing before the first
             (K.K_RIGHT, "cg e0c"), (K.K_SPACE, "cg e2"), (K.K_PAGEUP, "cg e0c"),
             (K.K_PAGEDOWN, "cg e2")]
    for key, shown in steps:
        rig.key(key)
        assert order[viewer.index] == shown, key
    rig.ui.frame(rig.ui.wheel((640, 360), -1))
    assert order[viewer.index] == "cg e3"
    rig.ui.frame(rig.ui.wheel((640, 360), 1))
    assert order[viewer.index] == "cg e2"
    rig.ui.frame(rig.ui.down((640, 360)), rig.ui.up((640, 360)))           # a click: next
    assert order[viewer.index] == "cg e3"
    while order[viewer.index] != "cg e14":
        rig.key(K.K_RIGHT)
    rig.key(K.K_RIGHT)                                                    # past the last
    assert rig.viewer is None
    assert (rig.grid.page, rig.focused_key(), rig.menu.scope.visible) == (1, "cg e14", True)
    rig.key(K.K_PAGEUP)                                                   # position 2: e2
    rig.key(K.K_RETURN)
    assert order[rig.viewer.index] == "cg e2"
    rig.key(K.K_RIGHT, 3)                                                 # e3, e4, e5
    rig.ui.frame(rig.ui.key(K.K_ESCAPE))                                  # Back closes
    assert rig.viewer is None and rig.focused_key() == "cg e5"
    rig.key(K.K_RETURN)
    rig.ui.frame(rig.ui.down((5, 5), button=3))                           # right click: Back
    assert rig.viewer is None and not rig.menu.scope.visible              # by mouse: hidden
    rig.key(K.K_RETURN, 2)                                                # reveal, then open
    rig.ui.frame(rig.ui.pad(K.CONTROLLER_BUTTON_A))                       # gamepad A: next
    assert order[rig.viewer.index] == "cg e6"
    rig.ui.frame(rig.ui.pad(K.CONTROLLER_BUTTON_B))                       # gamepad B: Back
    assert rig.viewer is None and rig.focused_key() == "cg e6"


# --- AC-F34-23 ------------------------------------------------------------------------------

def test_ac_f34_23_fades_and_crossfade(tmp_path):
    rows = [(False, True), (True, False)]                                 # (reduce, fades)
    for reduce, fades in rows:
        rig = Rig(tmp_path / str(reduce), entries(3), names(3), reduce=reduce)
        rig.open()
        rig.key(K.K_RETURN)
        viewer = rig.viewer
        fade_s = rig.shell.theme.cfg.ui.fade_ms / 1000
        assert math.isclose(viewer.fade_s, fade_s if fades else 0.0)
        assert (viewer.phase is Phase.OPENING) == fades
        rig.settle(30)
        assert viewer.phase is Phase.OPEN and viewer.opaque
        rig.key(K.K_RIGHT)
        assert viewer.crossfading == fades
        if fades:
            frames = round(CROSSFADE_S * 60)
            rig.ui.frames(frames // 2)
            assert 0.3 < viewer.cross < 0.7
            rig.ui.frames(frames // 2 + 1)
            assert not viewer.crossfading                                 # 200 ms
            rig.key(K.K_RIGHT)
            rig.ui.frames(3)
            assert viewer.crossfading
            rig.ui.frame(rig.ui.key(K.K_LEFT))                            # input finishes it,
            assert viewer.index == 1 and viewer._old is not None          # then acts
            rig.ui.frame(rig.ui.key(K.K_UP))                              # any input finishes
            assert not viewer.crossfading and viewer.index == 1
        rig.ui.frame(rig.ui.key(K.K_ESCAPE))
        assert (viewer.phase is Phase.CLOSING and rig.viewer is viewer) == fades
        rig.settle(30)
        assert rig.viewer is None


# --- AC-F34-24 ------------------------------------------------------------------------------

def test_ac_f34_24_lazy_thumbnails(tmp_path):
    rig = Rig(tmp_path, entries(14), names(14))
    rig.menu = GameMenuScreen(rig.shell, by=InputKind.KEYS, title_page="load")
    rig.shell.stack.push(rig.menu)
    rig.ui.frame()                                                        # the opening frame
    assert (rig.decodes, rig.thumbs.made) == ([], 0)
    first = tile_grid_layout().pictures[0].center
    assert rig.ui.px(*first) == tuple(rig.shell.theme.cfg.panel.fill_color)  # not ready yet
    made = [rig.thumbs.made]
    for _ in range(40):
        rig.ui.frame()
        made.append(rig.thumbs.made)
    assert all(b - a <= 1 for a, b in zip(made, made[1:]))                # one per frame
    assert rig.thumbs.made == PER_PAGE and rig.thumbs.main_loads == 0
    assert all(abs(a - b) <= 4 for a, b in zip(rig.ui.px(*first), RED))   # the thumbnail
    assert set(rig.decodes) == {ref(f"cg e{i}") for i in range(PER_PAGE)}  # by the prefetcher
    rig.key(K.K_PAGEDOWN)                                                 # the turning frame
    assert rig.thumbs.made == PER_PAGE
    rig.settle(10)
    assert rig.thumbs.made == 14
    rig.ui.frame(rig.ui.key(K.K_ESCAPE))
    rig.settle(30)
    rig.open()                                                            # opened again
    assert rig.thumbs.made == 14 and len(rig.decodes) == 14               # the cache, reused
    refused = Rig(tmp_path / "refused", entries(3), names(3), refuse={ref("cg e1")})
    refused.open()
    refused.settle(20)
    assert (refused.thumbs.made, refused.thumbs.main_loads) == (3, 1)     # I-2: once
    off = Rig(tmp_path / "off", entries(3), names(3), prefetch=False)
    off.open()
    assert off.thumbs.made == 0
    off.ui.frame()
    off.ui.frame()
    assert (off.thumbs.made, off.thumbs.main_loads) == (2, 2)             # one per frame


# --- AC-F34-25 ------------------------------------------------------------------------------

def test_ac_f34_25_count_badge(tmp_path, monkeypatch):
    many = entries(3, versions={0: ("cg e0b",), 1: ("cg e1b", "cg e1c")})
    rows = [
        ({"cg e0", "cg e1", "cg e2"}, []),                                # one picture each
        ({"cg e0", "cg e0b", "cg e1b", "cg e1c", "cg e2"}, ["2", "2"]),
        ({"cg e0", "cg e0b", "cg e1", "cg e1b", "cg e1c"}, ["2", "3"]),
    ]
    for unlocked, badges in rows:
        rig = Rig(tmp_path / str(len(unlocked)) / str(len(badges)), many, unlocked)
        rig.open()
        with spy_draw_text(monkeypatch) as calls:
            rig.ui.frame()
        drawn = [c for c in calls if c.text.isdigit()]
        assert [c.text for c in drawn] == badges
        assert all(c.font.size == 18 for c in drawn)
        monkeypatch.undo()


# --- AC-F34-26 ------------------------------------------------------------------------------

def test_ac_f34_26_captions_at_150_percent():
    m20 = SimpleNamespace(theme=plain_theme(), words=Words(), assets=FixedFontAssets())
    grid = TileGrid(ui=m20, thumbs=ThumbCache(SimpleNamespace()), on_activate=lambda t: None)
    grid.set_tiles([Tile("a", (1, 2, 3), "By the River")])
    rows = [(1.0, "By the River"),                     # 12 × 14 = 168 ≤ 188
            (1.5, "By the …")]                         # 30 px: 21 per grapheme, 8 fit
    for scale, shown in rows:
        grid.build(PAGE_BODY, scale)
        cut = grid.caption("By the River")
        assert cut == shown
        size = round(20 * scale)
        assert len(cut) * round(20 * size / 28) <= 188


# --- AC-F34-27 ------------------------------------------------------------------------------

def test_ac_f34_27_contrast_on_defaults():
    cfg = ThemeConfig()
    rows = [(cfg.button.disabled.text_color, 4.5),     # ??? (5.64:1)
            (cfg.panel.text_color, 4.5)]               # captions
    for color, least in rows:
        assert contrast_ratio(tuple(color), tuple(cfg.panel.fill_color)) >= least
    assert tuple(cfg.button.disabled.text_color) == (0x6E, 0x5E, 0x68)
    assert tuple(cfg.panel.fill_color) == (0xFF, 0xF4, 0xF8)
