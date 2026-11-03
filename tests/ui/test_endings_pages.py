"""F36 P2 — the Endings and Scenes pages over fake ports: AC-F36-10, 12, 13, 28.

Each page runs in F10's real ``GameMenuScreen`` opened from the title (F36-W3 adds the
Extras rows, so here the page sits on the title's ``load`` id), as F34-P1's gallery tests do.
Scene pictures are solid colours (``port.picture``), so no files are needed."""

from dataclasses import dataclass

import pygame

from engine.ui.builtin.endings_page import EndingsPage, endings_layout
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.scenes_page import ScenesPage
from engine.ui.builtin.tile_grid import TileGrid, tile_grid_layout
from engine.ui.focus import Box
from engine.ui.layouts import pitch
from engine.ui.menus import MenuEntry, MenuRegistry, UiOverrides
from engine.ui.nav import InputKind
from engine.ui.thumbs import ThumbCache
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import TestShell, UiHarness

K = pygame
RED, GREEN, BLUE = (200, 30, 30), (30, 200, 30), (30, 30, 200)


@dataclass(frozen=True)
class Ending:
    name: str
    heading: str | None
    title: str


@dataclass(frozen=True)
class Replay:
    label: str
    title: str
    image: str | None = None
    tile_picture: str | None = None


class EndingsFake:
    def __init__(self, endings, reached, *, replay_on=True) -> None:
        self._endings = tuple(endings)
        self.names = set(reached)
        self.replay_on = replay_on
        self.started: list[tuple[str, InputKind]] = []

    def endings(self):
        return self._endings

    def reached(self):
        return self.names

    def start(self, name, by):
        self.started.append((name, by))


class ScenesFake:
    def __init__(self, replays, unlocked, *, thumbs, pictures) -> None:
        self._replays = tuple(replays)
        self.names = set(unlocked)
        self.thumbs = thumbs
        self.pictures = dict(pictures)
        self.started: list[tuple[str, InputKind]] = []

    def replays(self):
        return self._replays

    def unlocked(self):
        return self.names

    def picture(self, name):
        return self.pictures[name]

    def start(self, label, by):
        self.started.append((label, by))


class Shell(TestShell):
    __test__ = False

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.overrides = UiOverrides()
        self.menus = MenuRegistry(overrides=self.overrides)
        self.words.override = {"endings": "Endings", "replays": "Scenes"}.get   # W3's words


class Rig:
    """A shell and one page in F10's title-page menu."""

    def __init__(self, make_page, *, scale=1.0) -> None:
        self.shell = Shell(reduce_motion=True)
        if scale != 1.0:
            self.shell.painter.set_text_scale(lambda: scale)
        self.shell.menus.add("title", MenuEntry("load", page=lambda host: make_page()))
        self.ui = UiHarness(self.shell)
        self.menu: GameMenuScreen | None = None

    def open(self, by=InputKind.KEYS) -> GameMenuScreen:
        self.menu = GameMenuScreen(self.shell, by=by, title_page="load")
        self.shell.stack.push(self.menu)
        self.ui.frame()
        return self.menu

    @property
    def page(self):
        assert self.menu is not None
        return self.menu.page

    def key(self, key: int, n: int = 1) -> None:
        for _ in range(n):
            self.ui.frame(self.ui.key(key), self.ui.key(key, up=True))

    def click(self, pos) -> None:
        self.ui.frame(self.ui.motion(pos), self.ui.down(pos), self.ui.up(pos))

    def texts(self, monkeypatch):
        with spy_draw_text(monkeypatch) as calls:
            self.ui.frame()
        monkeypatch.undo()
        return calls


def endings_rig(endings, reached, *, replay_on=True, scale=1.0):
    port = EndingsFake(endings, reached, replay_on=replay_on)
    return port, Rig(lambda: EndingsPage(port), scale=scale)


FIVE = [Ending("sad", "Sad End", "Paper Ashes"), Ending("lost", "Lost End", "Alone"),
        Ending("good", "Good End", "The Lantern Festival"), Ending("bare", None, "No Heading"),
        Ending("true", "True End", "Morning")]


def focused_row(rig) -> str | None:
    page = rig.page
    if rig.menu.scope.focused is not page.list:
        return None
    return page.rows[page.list.focus_row].name


# --- AC-F36-10 ------------------------------------------------------------------------------

def test_ac_f36_10_endings_list_rows_count_and_geometry(monkeypatch):
    long_heading = "An Extremely Long Ending Heading Indeed"
    endings = [*FIVE[:3], Ending("bare", None, "No Heading"),
               Ending("true", long_heading, "Morning")]
    port, rig = endings_rig(endings, {"sad", "good", "bare", "true", "not-an-ending"})
    rig.open()
    page = rig.page
    cfg = rig.shell.theme.cfg
    assert [r.name for r in page.rows] == ["sad", "lost", "good", "bare", "true"]
    assert [r.reached for r in page.rows] == [True, False, True, True, True]
    lay = page.layout
    assert (lay.count, lay.list) == (Box(416, 112, 808, 40), Box(416, 164, 808, 500))
    assert lay.row_height == max(cfg.list.row_height, pitch(cfg.button.text_size) + 16) == 55
    assert page.list.box == lay.list and page.list.row_height == 55
    calls = rig.texts(monkeypatch)
    by_text = {c.text: c for c in calls}
    count = by_text["Endings reached: 4 / 5"]                        # names not in the index
    assert (count.pos, count.options["anchor"], count.color) == (
        (416, 132), "midleft", tuple(cfg.panel.text_color))
    assert count.font.size == cfg.panel.text_size
    cy = [164 + 55 * i + 27.5 for i in range(5)]
    head = by_text["Sad End"]
    assert (head.pos, head.color) == ((432, cy[0]), tuple(cfg.panel.heading.text_color))
    title = by_text["Paper Ashes"]
    assert (title.pos, title.color) == ((680, cy[0]), tuple(cfg.button.text_color))
    assert by_text["No Heading"].pos == (432, cy[3])                  # no heading: x + 16
    locked = [c for c in calls if c.text == "???"]
    assert [(c.pos, c.color) for c in locked] == [((432, cy[1]),
                                                   tuple(cfg.button.disabled.text_color))]
    cut = next(c for c in calls if c.pos == (432, cy[4]))
    assert cut.text.endswith("…") and long_heading.startswith(cut.text[:-1])
    assert cut.bounds[2] <= 232
    replays = [c for c in calls if c.text == "Replay"]
    assert len(replays) == 4
    assert all((c.pos[0], c.options["anchor"], c.color) ==
               (1208, "midright", tuple(cfg.button.marker.fill_color)) for c in replays)
    assert by_text["The Lantern Festival"].bounds[0] + by_text["The Lantern Festival"].bounds[2] \
        <= 1208 - replays[0].bounds[2]                               # the title stops before
    assert all(c.font.size == cfg.button.text_size for c in (head, title, locked[0]))
    visited = [focused_row(rig)]                                     # by keys: the first
    for _ in range(5):
        rig.key(K.K_DOWN)
        visited.append(focused_row(rig))
    assert visited[0] == "sad" and "lost" not in visited             # never a locked row
    assert set(visited) == {"sad", "good", "bare", "true"}
    # Many rows overflow: "Replay" moves left of the scrollbar lane.
    many = [Ending(f"e{i}", f"H{i}", f"T{i}") for i in range(12)]
    _port, big = endings_rig(many, {e.name for e in many})
    big.open()
    shown = [c for c in big.texts(monkeypatch) if c.text == "Replay"]
    assert shown and all(c.pos[0] == 1208 - 20 for c in shown)
    assert endings_layout().list == Box(416, 164, 808, 500)


# --- AC-F36-12 ------------------------------------------------------------------------------

def test_ac_f36_12_activating_a_reached_ending_replays_it(monkeypatch):
    port, rig = endings_rig(FIVE, {"sad", "good"})
    rig.open()
    rig.key(K.K_RETURN)
    assert port.started == [("sad", InputKind.KEYS)]
    rig.key(K.K_DOWN)
    rig.key(K.K_RETURN)
    assert port.started[-1] == ("good", InputKind.KEYS)
    row = lambda i: rig.page.list.row_box(i).center                 # noqa: E731
    rig.click(row(1))                                                # a locked row: nothing
    assert len(port.started) == 2
    rig.click(row(0))
    assert port.started[-1] == ("sad", InputKind.MOUSE)
    assert rig.page.widget_for("good") is rig.page.list and rig.page.list.focus_row == 2
    assert rig.page.widget_for("lost") is None and rig.page.widget_for("nope") is None
    off, rig_off = endings_rig(FIVE, {"sad", "good"}, replay_on=False)
    rig_off.open()
    assert not [c for c in rig_off.texts(monkeypatch) if c.text == "Replay"]
    rig_off.key(K.K_RETURN)
    rig_off.click(rig_off.page.list.row_box(2).center)
    assert off.started == []
    assert focused_row(rig_off) == "good"                            # still readable


# --- AC-F36-13 ------------------------------------------------------------------------------

def test_ac_f36_13_scenes_tiles_and_activate(monkeypatch):
    replays = [Replay("festival", "The Festival", image="cg fest"),
               Replay("river", "By the River", image="cg river", tile_picture="bg river"),
               Replay("promise", "The Promise", tile_picture="bg roof"),
               Replay("bare", "Bare Scene"),
               Replay("hidden", "Hidden")]
    pictures = {"cg fest": RED, "cg river": GREEN, "bg river": BLUE, "bg roof": BLUE}
    shell_holder = {}

    def make():
        port = ScenesFake(replays, {"festival", "river", "promise", "bare"},
                          thumbs=ThumbCache(shell_holder["rig"].shell.assets),
                          pictures=pictures)
        shell_holder["port"] = port
        return ScenesPage(port)

    rig = shell_holder["rig"] = Rig(make)
    rig.open()
    port = shell_holder["port"]
    grid: TileGrid = rig.page.grid
    tiles = grid.tiles
    assert [t.key for t in tiles] == ["festival", "river", "promise", "bare", "hidden"]
    assert [t.picture for t in tiles] == [RED, GREEN, BLUE, None, None]  # image, then scene
    assert [t.caption for t in tiles] == ["The Festival", "By the River", "The Promise",
                                          "Bare Scene", ""]
    assert [t.locked for t in tiles] == [False] * 4 + [True]
    assert rig.page.nav_extras == frozenset({"shoulders"})
    lay = tile_grid_layout()
    cfg = rig.shell.theme.cfg
    assert rig.ui.px(*lay.pictures[0].center) == RED
    assert rig.ui.px(*lay.pictures[3].center) == tuple(cfg.panel.fill_color)  # empty look
    calls = rig.texts(monkeypatch)
    assert [c.pos for c in calls if c.text == "???"] == [lay.pictures[4].center]
    assert {c.text for c in calls} >= {"The Festival", "By the River", "Bare Scene"}
    rig.key(K.K_RIGHT)
    rig.key(K.K_RETURN)                                              # Enter: river
    assert port.started == [("river", InputKind.KEYS)]
    rig.click(lay.pictures[4].center)                                # locked: nothing
    assert len(port.started) == 1
    rig.click(lay.pictures[2].center)
    assert port.started[-1] == ("promise", InputKind.MOUSE)
    assert rig.page.widget_for("bare") is grid.cells_widget
    assert rig.page.widget_for("hidden") is None
    port.names.add("hidden")                                         # unlocked meanwhile
    rig.ui.frame()
    assert not rig.page.grid.tiles[4].locked and rig.page.grid.tiles[4].caption == "Hidden"


# --- AC-F36-28 ------------------------------------------------------------------------------

def test_ac_f36_28_endings_at_150_percent_text(monkeypatch):
    many = [Ending(f"e{i}", f"Heading {i}", f"Title number {i}") for i in range(20)]
    scale = [1.0]
    port = EndingsFake(many, {e.name for e in many})
    rig = Rig(lambda: EndingsPage(port))
    rig.shell.painter.set_text_scale(lambda: scale[0])
    rig.open()
    page = rig.page
    rig.key(K.K_DOWN, 8)
    assert focused_row(rig) == "e8"
    small = page.layout.row_height
    scale[0] = 1.5
    rig.menu.rebuild()
    rig.ui.frame()
    size = round(28 * 1.5)
    assert page.layout.row_height == max(48, pitch(size) + 16) > small    # re-pitched
    assert page.layout.text_size == size
    assert page.layout.count.h >= pitch(size) and page.layout.list.bottom == 664
    lst = page.list
    assert focused_row(rig) == "e8"
    box = lst.row_box(lst.focus_row)
    assert lst.box.y <= box.y and box.bottom <= lst.box.bottom      # still in view
    calls = rig.texts(monkeypatch)
    heads = [c for c in calls if c.text.startswith("Heading")]
    assert heads and all(c.font.size == size and c.bounds[2] <= 232 for c in heads)
    rig.key(K.K_END)
    box = lst.row_box(lst.focus_row)
    assert focused_row(rig) == "e19" and box.bottom <= lst.box.bottom
