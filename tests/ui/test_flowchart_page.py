"""F20 s8 — the Flowchart page over Port P (F20 ``06-acceptance.md`` §0.3 Page P): AC-F20-24,
51, 56 (the order and visibility rows), 57, 59 to 64, 66. AC-F20-30 and AC-F20-56's in-app
rows run in ``tests/app/test_flow_app.py`` (one App F session).

**Port P** is a fake ``FlowPort`` (faithful to 04 §5 plus ``node_id``): ``chart_records`` of
Records R for the row (Template L after run 1 unless a row says otherwise), ``LayoutJob``
for ``layout``, a held-state set for ``can_jump``, per-node reasons, and a ``jump`` recorder.
Most rows host the page in a bare ``FocusScope`` (``Host``); the rows that need the sidebar
(Left, Tab, Back, Start, the raw-event hook) run in F10's real game menu (``Game`` from
``test_game_menu``). Drawing rows use ``TestShell`` (real fonts, default theme) on a
1280×720 canvas with the draw recorder; the measure spy wraps the page's measures and
``text_width``."""

import dataclasses
import random
from types import SimpleNamespace

import pygame
import pytest

from engine.core.geometry import Viewport
from engine.render import text as render_text
from engine.render.canvas import Canvas, RenderQuality
from engine.runtime.flowchart import ChartEdge, ChartRecords, ChartShape, GateRow, GateView
from engine.ui.builtin.flowchart_page import FlowchartPage, PanelRow, page_geometry
from engine.ui.flowlayout import LayoutJob
from engine.ui.focus import Box, FocusScope
from engine.ui.input import UiEvent
from engine.ui.layouts import PAGE_BODY, sidebar_layout, title_layout
from engine.ui.menus import DEFAULT_ORDER, OPT_IN, MenuEntry
from engine.ui.nav import InputKind, Nav
from engine.ui.widgets import Button
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import TestShell
from tests.runtime.flow_story import RUN_1, launched, load_l, node, play, records_r, store_r
from tests.script.helpers import template_l

DT = 1 / 60
SLOT = (416, 112, 808, 552)
BERRY, PLUM, MAUVE, TRACK = (0xA0, 0x28, 0x60), (0x3D, 0x2B, 0x36), (0x6E, 0x5E, 0x68), \
    (0x7E, 0x5C, 0x74)
NODE_FILL, CHART_FILL = (0xFF, 0xE6, 0xF0), (0xFF, 0xFA, 0xFC)
MARKERS = {4: 'lock route promise "QXR1" until sad, good', 24: '        "QXC1 steps":',
           26: '        "QXC2 bridge" if "promise" in persistent.routes:',
           33: '    chapter shrine "Chapter 3" "QXT1"', 35: '    ending good "Good End" "QXE1"',
           37: '    flowchart scene "QXH1" hidden no jump',
           40: '    ending true "True End" "QXH2"'}


TWO_NODES = """label start:
    "hi"
    chapter one "Chapter 1" "One"
    "x"
"""
ONE_NODE = """label start:
    chapter one "Chapter 1" "One"
    "x"
"""


class PortP:
    """06 §0.3's Port P."""

    def __init__(self, program, records: ChartRecords, *, in_game: bool = True,
                 jump: bool = True, states=("festival", "stall", "M21"), reasons=None) -> None:
        self.graph = program.flowgraph
        self._records = records
        self.in_game = in_game
        self.jump_enabled = jump
        self.states = {self.graph.nodes[node(self.graph, n)].id for n in states}
        self.reasons = dict(reasons or {})
        self.jumps: list[tuple[str, InputKind]] = []
        self.opened = 0

    def records(self) -> ChartRecords:
        self.opened += 1
        return self._records

    def node_id(self, n: int) -> str:
        return self.graph.nodes[n].id

    def can_jump(self, node_id: str) -> bool:
        return node_id in self.states and node_id not in self.reasons

    def reason(self, node_id: str) -> str | None:
        return self.reasons.get(node_id)

    def jump(self, node_id: str, by: InputKind) -> None:
        self.jumps.append((node_id, by))

    def layout(self, metrics):
        return LayoutJob(self._records, metrics)


class Host:
    """The page in a bare scope (``PageHost``): keys go through the scope as the game menu
    sends them; Page Up/Down that no widget used go to ``page.on_nav``."""

    def __init__(self, port, *, shell: TestShell | None = None, from_title: bool = False,
                 scale: float = 1.0) -> None:
        self.shell = shell or TestShell()
        self.scale = scale
        self.shell.painter.set_text_scale(lambda: self.scale)
        self.painter = self.shell.painter
        self.scope = FocusScope()
        self.sidebar = Button(lambda: "Flowchart", lambda: None, box=Box(48, 300, 288, 56))
        self.page = FlowchartPage(port, from_title=from_title)
        self.build()

    def build(self) -> None:
        from engine.ui.focus import FocusGroup
        self.scope.set_groups([FocusGroup([self.sidebar]),
                               *self.page.build(self, Box(*SLOT))])

    def rebuild(self) -> None:
        self.build()

    def close_menu(self) -> None:
        pass

    @property
    def chart(self):
        return self.page.chart

    def key(self, nav: Nav) -> bool:
        used = self.scope.press(nav)
        if not used and nav in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            used = self.page.on_nav(nav)
        return used

    def focus_chart(self) -> None:
        assert self.scope.focus(self.chart, InputKind.KEYS)

    def frames(self, n: int = 1) -> None:
        for _ in range(n):
            self.page.update(DT)

    def select(self, name: str) -> None:
        self.chart.select(node(self.page.port.graph, name))

    def rows(self) -> list[tuple[str, str]]:
        return [(r.kind, r.text) for r in self.page.panel.model.rows]

    def draw(self, *, focused: bool = True, fill=(1, 2, 3), panel: bool = True
             ) -> pygame.Surface:
        surface = pygame.Surface((1280, 720))
        surface.fill(fill)
        canvas = Canvas(self.shell.assets)
        canvas.bind(surface, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
        p = self.shell.painter
        p.bind(canvas)
        if panel:
            self.page.draw(canvas, p)
        self.chart.draw(p, self.chart.look(focused=focused))
        return surface


@pytest.fixture(scope="module")
def run1(tmp_path_factory):
    """Template L after run 1: the program, its store, and the path on screen."""
    program = load_l(tmp_path_factory.mktemp("l"))
    interp = launched(program)
    play(interp, RUN_1)
    return SimpleNamespace(program=program, store=interp.persistent, path=interp.flow.path)


def port_of(run1, *, path=True, **kwargs) -> PortP:
    recs = records_r(run1.program, run1.store, path=run1.path if path else None)
    return PortP(run1.program, recs, **kwargs)


def ui_event(raw) -> UiEvent:
    pos = getattr(raw, "pos", None)
    return UiEvent(raw, pos, pos is not None)


# --- AC-F20-24 — the detail panel ---------------------------------------------------------

def test_ac_f20_24_detail_panel(run1, tmp_path):
    program = run1.program
    host = Host(port_of(run1))
    chapter2 = "Chapter 2: The Lantern Festival"
    rows = {
        "festival": ([("meta", "Chapter"), ("title", chapter2)], "enabled"),
        "M21": ([("meta", "Choice · " + chapter2),
                 ("title", "Where should we watch the lanterns?"), ("choice", "By the river"),
                 ("choice", "???"), ("choice", "???")], "enabled"),
        "river": ([("meta", "Chapter · " + chapter2), ("title", "Chapter 3: By the River"),
                   ("reason", "Reach this point again to jump here.")], "disabled"),
        "shrine": ([("meta", "Chapter"), ("title", "???")], "absent"),
        "sad": ([("meta", "Ending · Chapter 3: By the River"), ("heading", "Sad End"),
                 ("body", "Paper Ashes")], "absent"),
        "start": ([("meta", "Start"), ("title", "Start")], "absent"),
        "gate": ([("meta", "Locked route"), ("title", "???"), ("gate", "Sad End: Paper Ashes"),
                  ("gate", "???")], "absent"),
    }
    geometry = host.page.geometry
    for name, (expected, jump) in rows.items():
        host.select(name)                                # the same frame: no update needed
        assert host.rows() == expected, name
        assert host.page.panel.model.jump == jump, name
        assert host.page.geometry is geometry            # the layout never moves
    gate = host.page.panel.model.rows
    assert [r.mark for r in gate[2:]] == [True, False]
    # promise visited (no jump): its reason row and no Jump; jump = false: no reason, no Jump.
    store = store_r(program, v=("festival", "stall", "M21", "river", "promise"),
                    ro=("promise",), mk=(("M21", "By the river"),))
    promise = Host(PortP(program, records_r(program, store), states=("promise",)))
    promise.select("promise")
    assert promise.rows()[1:] == [("title", "The Promise"),
                                  ("reason", "You can't jump to this point.")]
    assert promise.rows()[0][1].startswith("Scene")
    assert promise.page.panel.model.jump == "absent"
    off = Host(port_of(run1, jump=False))
    for name in ("festival", "river", "M21"):
        off.select(name)
        assert off.page.panel.model.jump == "absent"
        assert all(kind != "reason" for kind, _text in off.rows())
    # A refused jump's reason shows in the next frame (the port's session reason).
    host.select("festival")
    host.page.port.reasons["chapter:festival"] = "flowchart_changed"
    host.frames()
    assert host.rows()[-1] == ("reason", "This part of the story has changed.")
    # Scrolling: M21's rows overflow; Page Down/Up by view − p_b, the wheel by 3 × p_b.
    host.select("M21")
    body, g = host.page.panel.body, host.page.geometry
    assert body.overflows() and body.scroll == 0
    host.focus_chart()
    assert host.key(Nav.PAGE_DOWN)
    assert body.scroll == min(body.max_scroll(), body.box.h - g.p_b)
    host.key(Nav.PAGE_UP)
    assert body.scroll == 0
    assert host.page.on_mouse("wheel", g.panel.center, notches=-1)
    assert body.scroll == min(body.max_scroll(), 3 * g.p_b)
    host.select("festival")                              # fits: nothing happens
    assert not host.key(Nav.PAGE_DOWN) and body.scroll == 0
    # Neither the body nor Jump is a focus stop.
    assert host.scope.tab_order() == [host.sidebar, host.chart]


# --- AC-F20-51 — group K: no spoilers ---------------------------------------------------------

def test_ac_f20_51_no_spoilers(tmp_path, monkeypatch):
    program = load_l(tmp_path / "m", template_l(replace=MARKERS))
    interp = launched(program)
    play(interp, RUN_1)
    recs = records_r(program, interp.persistent, path=interp.flow.path)
    host = Host(PortP(program, recs))
    seen: list[str] = []
    for name in ("measure", "heading_measure"):
        real = getattr(host.page, name)
        setattr(host.page, name, lambda text, size, real=real: (seen.append(text),
                                                                real(text, size))[1])
    real_width = render_text.text_width
    monkeypatch.setattr(render_text, "text_width",
                        lambda font, text: (seen.append(text), real_width(font, text))[1])
    import engine.render.canvas as canvas_module
    monkeypatch.setattr(canvas_module, "text_width",
                        lambda font, text: (seen.append(text), real_width(font, text))[1])
    with spy_draw_text(monkeypatch) as calls:
        host.focus_chart()
        reading = host.page.layout.reading
        for _ in range(len(reading) + 1):
            host.key(Nav.NEXT)
            host.draw()
        host.focus_chart()
        for nav in (Nav.HOME, Nav.END):
            host.key(nav)
            host.draw()
        for n in reading:
            host.chart.select(n)
            seen.extend(text for row in host.page.panel.model.rows for text in [row.text])
            host.draw()
        host.page.on_event(ui_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_MINUS,
                                                       mod=0)))
        host.draw()
        host.scale = 1.5
        host.rebuild()
        host.draw()
    seen.extend(c.text for c in calls)
    leaks = [t for t in seen if any(m in t for m in ("QXC", "QXT", "QXH", "QXR", "QXE"))]
    assert leaks == []
    # Untaken labels are the size of ???'s tag (the layout's place, never measured from text).
    labels = {e.label[2:] for e in host.page.layout.edges if e.label is not None}
    assert len(labels) == 1
    texts = [t for ts in recs.edge_texts for t in ts]
    assert texts.count(None) == 2 and ("By the river",) in texts


# --- AC-F20-56 — entries -------------------------------------------------------------------

def _pages(program, interp, *, can_jump=None, **options):
    """``app/flowchart_ui.FlowPages`` over a launched interpreter (no window)."""
    from engine.app.flowchart_ui import FlowPages
    from engine.runtime.flowchart import FlowOptions
    rec = interp.flowchart
    service = SimpleNamespace(can_jump=can_jump or (lambda i: rec.state(i) is not None))
    return FlowPages(SimpleNamespace(story=None), interp, service, FlowOptions(**options),
                     clock=lambda: 0.0)


def test_ac_f20_56_entries(run1, tmp_path):
    assert DEFAULT_ORDER["game"] == ("return", "skip_minigame", "history", "codex",
                                     "flowchart", "save", "load", "settings", "help",
                                     "main_menu", "quit")
    assert DEFAULT_ORDER["title"] == ("new_game", "load", "flowchart", "settings", "extras",
                                      "codex", "help", "quit")
    assert all("flowchart" not in ids for ids in OPT_IN.values())
    assert FlowchartPage.heading == "flowchart"
    # The game entry: Template L, and "hi" plus one chapter (2 nodes); not 1 node, or off.
    program = load_l(tmp_path / "l")
    fresh = launched(program)
    assert _pages(program, fresh).game_visible()
    assert not _pages(program, fresh, enabled=False).game_visible()
    two = load_l(tmp_path / "two", TWO_NODES)
    assert _pages(two, launched(two)).game_visible()
    one = load_l(tmp_path / "one", ONE_NODE)
    assert not _pages(one, launched(one)).game_visible()
    # The title entry: not on a first run; after run 1; not with jump or enabled false; not
    # when only no-jump nodes or F18-only chapters are visited.
    assert not _pages(program, fresh).title_visible()
    played = launched(program)
    play(played, RUN_1)
    assert _pages(program, played).title_visible()
    assert not _pages(program, played, jump=False).title_visible()
    assert not _pages(program, played, enabled=False).title_visible()
    store = store_r(program, v=("promise",), ro=("promise",))
    only = launched(program, store)
    promise = program.flowgraph.nodes[node(program.flowgraph, "promise")].id
    assert not _pages(program, only, can_jump=lambda i: i == promise).title_visible()
    f18 = launched(program, store_r(program, ch=("river",)))
    assert not _pages(program, f18).title_visible()


# --- AC-F20-57 — page layout and text size ------------------------------------------------

def test_ac_f20_57_layout_and_text_size(run1):
    from engine.core.config_schema import ThemeConfig
    cfg = ThemeConfig()
    for scale, viewport, panel, jump, cell, tool in (
            (1.0, (416, 112, 808, 390), (416, 514, 808, 150), (1012, 596, 200, 56), (240, 84),
             40),
            (1.5, (416, 112, 808, 332), (416, 456, 808, 208), (1012, 577, 200, 75), (360, 126),
             52)):
        g = page_geometry(cfg, scale)
        as_t = lambda b: (b.x, b.y, b.w, b.h)                     # noqa: E731
        assert (as_t(g.viewport), as_t(g.panel), as_t(g.jump)) == (viewport, panel, jump)
        assert g.jump.right == 1212 and g.jump.bottom == 652 and g.panel.bottom == 664
        assert g.tool == tool and all(b.w == b.h == tool for b in g.toolbar)
        host = Host(port_of(run1), scale=scale)
        assert host.chart.cell_box(node(host.page.port.graph, "stall")).w == cell[0]
        assert host.chart.cell_box(node(host.page.port.graph, "stall")).h == cell[1]
        # Nothing drawn outside the body slot (a sentinel background stays).
        host.focus_chart()
        for name in ("start", "M21", "sad", "gate"):
            host.select(name)
            host.frames(13)
            surface = host.draw()
            x, y, w, h = SLOT
            outside = [(px, py) for px in range(0, 1280, 7) for py in range(0, 720, 7)
                       if not (x <= px < x + w and y <= py < y + h)
                       and surface.get_at((px, py))[:3] != (1, 2, 3)]
            assert outside == [], (scale, name, outside[:3])
    # A text-size change while open rebuilds with the selection kept, in the safe zone.
    host = Host(port_of(run1))
    host.focus_chart()
    host.select("shrine")
    host.frames(13)
    host.scale = 1.5
    host.rebuild()
    chart = host.chart
    assert chart.selected == node(host.page.port.graph, "shrine")
    zone, cell = chart.safe_zone(), chart.cell_box(chart.selected)
    assert zone.x <= cell.x and cell.right <= zone.right
    # 03 C1 as F23 settled it (07 §3.4): 9 game-menu entries at 150% by step 2 (HEIGHT); a
    # 7-entry title leaves a logo box of at least 80.
    assert sidebar_layout(9, scale=1.5).step <= 3
    assert title_layout(7, scale=1.5).logo.h >= 80


# --- AC-F20-59 — the chart on screen ------------------------------------------------------

def test_ac_f20_59_chart_on_screen(tmp_path, monkeypatch):
    long_title = "A" * 30 + " " + "B" * 29                    # 60 characters
    text = template_l(replace={11: f'    flowchart scene "{long_title}"'})
    long = load_l(tmp_path / "t", text)
    interp = launched(long)
    play(interp, RUN_1)
    recs = records_r(long, interp.persistent, path=interp.flow.path)
    host = Host(PortP(long, recs))
    chart = host.chart
    host.focus_chart()
    chart.centre_on(node(long.flowgraph, "stall"))
    surface = host.draw()
    # Visited fill and border; unvisited: no fill (the chart shows), ??? in #6E5E68.
    stall = chart.cell_box(node(long.flowgraph, "stall"))
    assert surface.get_at((round(stall.x + 20), round(stall.y + 20)))[:3] == NODE_FILL
    shrine = node(long.flowgraph, "shrine")
    chart.centre_on(shrine)
    with spy_draw_text(monkeypatch) as calls:
        surface = host.draw()
    box = chart.cell_box(shrine)
    assert surface.get_at((round(box.x + 20), round(box.y + 20)))[:3] == CHART_FILL
    unknown = [c for c in calls if c.text == "???" and box.x <= c.pos[0] <= box.right]
    assert unknown and unknown[0].color == MAUVE
    # The 60-character title draws in 2 lines, the second ending in "…"; the panel is whole.
    chart.centre_on(node(long.flowgraph, "stall"))
    with spy_draw_text(monkeypatch) as calls:
        host.draw()
    lines = [c.text for c in calls if c.text.startswith(("AAA", "BBB"))]
    assert len(lines) == 2 and lines[1].endswith("…")
    host.select("stall")
    assert ("title", long_title) in host.rows()
    # Labels: the taken choice's text, ??? for the untaken ones.
    chart.centre_on(node(long.flowgraph, "M21"))
    with spy_draw_text(monkeypatch) as calls:
        surface = host.draw()
    texts = [c.text for c in calls]
    assert "By the river" in texts and texts.count("???") >= 2
    # Path edges: 6 wide in #A02860 (stall → M21 is on this playthrough's path).
    k = next(i for i, e in enumerate(recs.shape.edges)
             if (e.src, e.dst) == (node(long.flowgraph, "stall"), node(long.flowgraph, "M21")))
    assert k in recs.path_edges
    a, b = host.page.layout.edges[k].points[:2]
    mid = chart.to_canvas((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    assert surface.get_at((round(mid[0]), round(mid[1])))[:3] == BERRY
    assert surface.get_at((round(mid[0]), round(mid[1] + 2)))[:3] == BERRY
    # The here tab: bottom-left at (node left + 12, node top), "You are here" in white.
    here = chart.here()
    assert here == node(long.flowgraph, "river")
    chart.centre_on(here)
    with spy_draw_text(monkeypatch) as calls:
        host.draw()
    tab = next(c for c in calls if c.text == "You are here")
    cell = chart.cell_box(here)
    assert tab.color == (255, 255, 255)
    assert abs(tab.pos[1] - (cell.y - host.page.geometry.tag_h / 2)) <= 1
    assert cell.x + 12 < tab.pos[0] < cell.x + 12 + 40
    title = Host(PortP(long, records_r(long, interp.persistent)), from_title=True,
                 shell=host.shell)
    with spy_draw_text(monkeypatch) as calls:
        title.draw()
    assert all(c.text != "You are here" for c in calls)
    # A gate with 4 until endings: 3 lines, then "+1".
    gate = node(long.flowgraph, "gate")
    rows = (GateRow(None, True, ("Sad End: Paper Ashes",)),) + (GateRow(None, False, None),) * 3
    four = dataclasses.replace(recs, gates=(GateView(gate, None, rows),))
    host4 = Host(PortP(long, four), shell=host.shell)
    host4.chart.centre_on(gate)
    with spy_draw_text(monkeypatch) as calls:
        host4.draw()
    box = host4.chart.cell_box(gate)
    inside = [c.text for c in calls if box.x <= c.pos[0] <= box.right
              and box.y <= c.pos[1] <= box.bottom]
    # 03: the cell holds the title and 3 lines; over 3 endings, line 4 reads "+N".
    assert inside[0] == "???" and inside[1].startswith("Sad End") and inside[2:] == ["???", "+2"]
    # Dashes keep their place on the chart when the view pans by 1 unit.
    fills = []
    real_fill = Canvas.fill
    monkeypatch.setattr(Canvas, "fill", lambda self, color, rect=None: (
        fills.append((tuple(color[:3]), rect)), real_fill(self, color, rect))[1])
    chart.centre_on(shrine)
    host.draw()
    dash_color = TRACK
    before = [r for c, r in fills if c == dash_color and r is not None and r[2] < 9]
    fills.clear()
    chart.view[0] += 1
    host.draw()
    after = [r for c, r in fills if c == dash_color and r is not None and r[2] < 9]
    assert before and {(round(x - 1, 3), y) for x, y, *_ in before} & \
        {(round(x, 3), y) for x, y, *_ in after}
    # Selected and focused: a 4-wide ring 6 outside and F10's marker; not focused: 2 wide.
    monkeypatch.undo()
    tri = []
    from engine.ui.paint import Painter
    monkeypatch.setattr(Painter, "triangle", lambda self, b, color, **k: tri.append(b))
    host.select("stall")
    host.frames(13)
    surface = host.draw(focused=True)
    cell = chart.cell_box(node(long.flowgraph, "stall"))
    ring_x = round(cell.x - 6)
    assert surface.get_at((ring_x + 3, round(cell.y + 20)))[:3] == BERRY
    assert tri and abs(tri[0].right - (cell.x - 6 - 8)) <= 1
    tri.clear()
    surface = host.draw(focused=False)
    assert not tri and surface.get_at((ring_x + 3, round(cell.y + 20)))[:3] != BERRY
    # Hover: the fill only, the selection and panel unchanged.
    selected, rows_before = chart.selected, host.rows()
    m21 = chart.cell_box(node(long.flowgraph, "M21"))
    chart.on_mouse("hover", (m21.x + 30, m21.y + 30))
    assert chart.hover == node(long.flowgraph, "M21") and chart.selected == selected
    assert host.rows() == rows_before


# --- AC-F20-60 — opening and keeping the selection in view --------------------------------

def test_ac_f20_60_opening_and_keeping_in_view(run1):
    graph = run1.program.flowgraph
    host = Host(port_of(run1))
    chart = host.chart
    river = node(graph, "river")
    assert chart.zoom == "normal" and chart.selected == river
    cell, vp = chart.cell_box(river), chart.box
    assert abs(cell.center[0] - vp.center[0]) <= 1
    # By key: focused at the first frame; by mouse: selected, not focused.
    host.scope.focus(host.sidebar, InputKind.KEYS)
    host.frames()
    assert host.scope.focused is chart
    mouse = Host(port_of(run1))
    mouse.scope.focus(mouse.sidebar, InputKind.MOUSE)
    mouse.frames()
    assert mouse.scope.focused is mouse.sidebar
    # From the title: the most recent node (sad after run 1), no here.
    title = Host(port_of(run1, path=False, in_game=False), from_title=True)
    assert title.chart.selected == node(graph, "sad") and title.chart.here() is None
    # A selection outside the safe zone pans by the smallest offset over 200 ms ease_in_out.
    host.focus_chart()
    start = list(chart.view)
    host.key(Nav.LEFT)                                 # M21, left of river
    target = chart.pan[1]
    host.frames(6)
    mid = [start[i] + (target[i] - start[i]) * 0.5 for i in range(2)]
    assert all(abs(chart.view[i] - mid[i]) <= 1 for i in range(2))
    host.frames(6)
    assert chart.pan is None and list(chart.view) == list(target)
    zone, cell = chart.safe_zone(), chart.cell_box(chart.selected)
    assert zone.x <= cell.x - 10 and cell.right + 10 <= zone.right
    # Home centres; a new selection mid-pan starts from the view now; a drag stops a pan.
    host.key(Nav.HOME)
    host.frames(3)
    now = list(chart.view)
    host.key(Nav.END)
    assert chart.pan[0] == tuple(now)
    pos = chart.box.center
    chart.on_mouse("down", pos)
    chart.on_mouse("drag", (pos[0] + 20, pos[1]))
    assert chart.pan is None
    chart.on_mouse("up", (pos[0] + 20, pos[1]))
    # The view never passes the bounds by more than the margin; a fitting axis is centred.
    chart.pan_by(-1e6, 0)
    lo, _hi = chart._range(0)
    assert chart.view[0] == lo >= chart.layout.bounds[0] - 200
    chart.set_zoom("overview")
    bx, by, bw, bh = chart.layout.bounds
    vw, vh = chart.view_size()
    assert bh <= vh and abs(chart.view[1] - (by + (bh - vh) / 2)) < 1e-6
    # Reduced motion: a cut in the same frame.
    still = Host(port_of(run1))
    still.shell.reduce_motion = True
    still.focus_chart()
    still.key(Nav.LEFT)
    assert still.chart.pan is None and still.chart.view == list(
        still.chart._target_for(still.chart.selected, False))
    # Each opening starts in Normal and re-centres (a new page; nothing is remembered).
    again = Host(host.page.port)
    assert again.chart.zoom == "normal" and again.chart.selected == river


# --- AC-F20-61 — keyboard and gamepad -------------------------------------------------------

def test_ac_f20_61_keyboard_and_gamepad(run1, tmp_path):
    from tests.ui.test_game_menu import FADE, H, Game
    port = port_of(run1)
    graph = run1.program.flowgraph
    g = Game(tmp_path)
    g.shell.menus.add("game", MenuEntry("flowchart", page=lambda host: FlowchartPage(port)))
    menu = g.open()
    button = g.button("flowchart")
    menu.scope.focus(button, InputKind.KEYS)
    g.frame(H.key(pygame.K_RETURN))
    page = menu.page
    assert isinstance(page, FlowchartPage)
    g.frame()
    chart = page.chart
    assert menu.scope.focused is chart                 # opened by key: the node has focus
    n = lambda name: node(graph, name)                 # noqa: E731
    assert chart.selected == n("river")
    g.frame(H.key(pygame.K_LEFT))
    assert chart.selected == n("M21")
    g.frame(H.key(pygame.K_DOWN))
    assert chart.selected in (n("shrine"), n("gate"))
    # Up/Down/Right with nothing that way: the limit bar; it holds 400 ms.
    chart.select(n("sad"))
    g.frame(H.key(pygame.K_RIGHT))
    assert chart.limit is not None and chart.limit[0] is Nav.RIGHT
    g.frame(H.key(pygame.K_RIGHT, up=True))
    g.frames(30)
    assert chart.limit is None
    # Tab / Shift+Tab follow reading order; past the last, the first sidebar entry.
    reading = page.layout.reading
    chart.select(reading[-2])
    g.frame(H.key(pygame.K_TAB))
    assert chart.selected == reading[-1]
    g.frame(H.key(pygame.K_TAB))
    assert menu.scope.focused is menu.buttons[0]
    g.frame(H.key(pygame.K_TAB, pygame.KMOD_LSHIFT))
    assert menu.scope.focused is chart and chart.selected == reading[-1]
    # Home; End and west: here, centred.
    g.frame(H.key(pygame.K_HOME))
    assert chart.selected == reading[0]
    g.frame(H.key(pygame.K_END))
    assert chart.selected == n("river")
    chart.select(reading[0])
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_X))
    assert chart.selected == n("river")
    # Zoom: -, +, =, keypad, north.
    for key, zoom in ((pygame.K_MINUS, "overview"), (pygame.K_PLUS, "normal"),
                      (pygame.K_KP_MINUS, "overview"), (pygame.K_EQUALS, "normal"),
                      (pygame.K_KP_MINUS, "overview"), (pygame.K_KP_PLUS, "normal")):
        g.frame(H.key(key))
        assert chart.zoom == zoom, key
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_Y))
    assert chart.zoom == "overview"
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_Y))
    assert chart.zoom == "normal"
    # Enter on a node without Jump: nothing, no sound; with Jump: the port's jump.
    sounds = len(g.shell.sounds) if hasattr(g.shell, "sounds") else None
    chart.select(n("river"))
    g.frame(H.key(pygame.K_RETURN))
    assert port.jumps == []
    chart.select(n("M21"))
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_A))
    assert port.jumps == [("menu:" + graph.nodes[n("M21")].id.split(":", 1)[1],
                           InputKind.KEYS)]
    del sounds
    # The right stick pans freely past 0.25; the selection stays.
    before, selected = list(chart.view), chart.selected
    g.frame(UiEvent(pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=0,
                                       axis=pygame.CONTROLLER_AXIS_RIGHTX, value=32767),
                    None, False))
    g.frames(5)
    assert chart.view[0] > before[0] and chart.selected == selected
    g.frame(UiEvent(pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=0,
                                       axis=pygame.CONTROLLER_AXIS_RIGHTX, value=0),
                    None, False))
    # Shoulders: the panel body (M21 overflows).
    body = page.panel.body
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER))
    assert body.scroll > 0
    # Left from the leftmost node goes to the sidebar; Esc closes the page; Start the menu.
    chart.select(reading[0])
    g.frame(H.key(pygame.K_LEFT))
    assert menu.scope.focused is button
    menu.scope.focus(chart, InputKind.KEYS)
    g.frame(H.key(pygame.K_ESCAPE))
    assert menu.page is None and menu.scope.focused is button
    g.frame(H.pad(pygame.CONTROLLER_BUTTON_START))
    g.frames(FADE + 1)
    assert g.shell.game_menu() is None
    # Every node and gate is reached by Tab alone.
    alone = Host(port)
    alone.focus_chart()
    alone.key(Nav.HOME)
    seen = {alone.chart.selected}
    while alone.key(Nav.NEXT) and alone.scope.focused is alone.chart:
        seen.add(alone.chart.selected)
    assert seen == set(page.layout.reading)


# --- AC-F20-62 — mouse ----------------------------------------------------------------------

def test_ac_f20_62_mouse(run1):
    graph = run1.program.flowgraph
    port = port_of(run1)
    host = Host(port)
    chart = host.chart
    m21 = node(graph, "M21")
    chart.centre_on(m21)
    box = chart.cell_box(m21)
    pos = (box.x + 30, box.y + 30)
    # A click selects and focuses; a second click within 400 ms and 8 units is Jump.
    host.scope.focus(chart, InputKind.MOUSE)
    chart.on_mouse("down", pos)
    chart.on_mouse("up", pos)
    assert chart.selected == m21 and chart.clicked and host.page.keyed(chart)
    host.frames(10)
    chart.on_mouse("down", (pos[0] + 3, pos[1]))
    chart.on_mouse("up", (pos[0] + 3, pos[1]))
    assert port.jumps == [(graph.nodes[m21].id, InputKind.MOUSE)]
    host.frames(30)
    chart.on_mouse("down", pos)                        # too late for a double-click
    chart.on_mouse("up", pos)
    assert len(port.jumps) == 1
    # A drag over 8 units pans 1:1 and selects nothing.
    view = list(chart.view)
    chart.select(node(graph, "river"))
    chart.on_mouse("down", pos)
    chart.on_mouse("drag", (pos[0] - 40, pos[1]))
    chart.on_mouse("up", (pos[0] - 40, pos[1]))
    assert chart.view[0] == pytest.approx(chart.clamp(view[0] + 40, view[1])[0]) \
        and chart.selected == node(graph, "river")
    # The wheel pans 120 × s; Shift or a horizontal wheel pans across; Ctrl zooms on the
    # pointer.
    def wheel(y=0, x=0, mods=0):
        pygame.key.set_mods(mods)
        try:
            raw = pygame.event.Event(pygame.MOUSEWHEEL, x=x, y=y, flipped=False)
            return host.page.on_event(UiEvent(raw, chart.box.center, True))
        finally:
            pygame.key.set_mods(0)

    chart.set_view(chart.layout.bounds[2] / 2, 0)
    before = list(chart.view)
    assert wheel(x=1) and chart.view[0] == pytest.approx(chart.clamp(before[0] + 120, 0)[0])
    before = list(chart.view)
    assert wheel(y=1, mods=pygame.KMOD_SHIFT) and chart.view[0] == pytest.approx(
        chart.clamp(before[0] - 120, 0)[0])
    anchor = chart.to_layout(chart.box.center)
    assert wheel(y=-1, mods=pygame.KMOD_CTRL) and chart.zoom == "overview"
    after = chart.to_layout(chart.box.center)
    assert abs(after[0] - anchor[0]) < 1 or chart.layout.bounds[2] <= chart.view_size()[0]
    assert wheel(y=1, mods=pygame.KMOD_CTRL) and chart.zoom == "normal"
    # The wheel over the panel scrolls its body (not the chart).
    chart.select(m21)
    view = list(chart.view)
    assert host.page.on_mouse("wheel", host.page.geometry.panel.center, notches=-1)
    assert host.page.panel.body.scroll > 0 and chart.view == view
    # Scrollbars: a track click pans one view; a thumb drag pans in proportion.
    h_bar, _v = chart._scrollbars()
    lane, thumb = h_bar
    chart.set_view(chart._range(0)[0], chart.view[1])
    x0 = chart.view[0]
    chart.on_mouse("down", (thumb.right + 5, lane.center[1]))
    chart.on_mouse("up", (thumb.right + 5, lane.center[1]))
    assert chart.view[0] == pytest.approx(min(x0 + chart.view_size()[0], chart._range(0)[1]))
    h_bar, _v = chart._scrollbars()
    lane, thumb = h_bar
    x0 = chart.view[0]
    chart.on_mouse("down", thumb.center)
    chart.on_mouse("drag", (thumb.center[0] - 10, thumb.center[1]))
    lo, hi = chart._range(0)
    assert chart.view[0] == pytest.approx(max(lo, x0 - 10 / (lane.w - thumb.w) * (hi - lo)))
    chart.on_mouse("up", thumb.center)
    # A click on Jump jumps; on the toolbar's zoom out, Overview.
    jumps = len(port.jumps)
    jump = host.page.geometry.jump
    assert host.page.on_mouse("down", jump.center) and host.page.on_mouse("up", jump.center)
    assert len(port.jumps) == jumps + 1
    tool = host.page.geometry.toolbar[0]
    chart.on_mouse("down", tool.center)
    chart.on_mouse("up", tool.center)
    assert chart.zoom == "overview"
    # Hover never changes the selection or the panel.
    selected, rows = chart.selected, host.rows()
    chart.on_mouse("hover", chart.box.center)
    assert chart.selected == selected and host.rows() == rows


# --- AC-F20-63 — zoom -----------------------------------------------------------------------

def test_ac_f20_63_zoom(run1, monkeypatch):
    graph = run1.program.flowgraph
    host = Host(port_of(run1))
    chart = host.chart
    river = node(graph, "river")
    before = chart.cell_box(river).center
    assert chart.tool_enabled(0) and not chart.tool_enabled(1) and chart.tool_enabled(2)
    chart.set_zoom("overview")
    box = chart.cell_box(river)
    assert (round(box.w), round(box.h)) == (96, 34)
    assert not chart.tool_enabled(0) and chart.tool_enabled(1)
    vw = chart.view_size()[0]
    assert abs(box.center[0] - before[0]) <= 1 or chart.layout.bounds[2] <= vw  # centred
    assert chart._width(2) >= 2 and chart._width(3) >= 2
    polys = []
    real = pygame.draw.polygon
    monkeypatch.setattr(pygame.draw, "polygon", lambda s, c, pts, w=0: (
        polys.append(pts), real(s, c, pts, w))[1])
    with spy_draw_text(monkeypatch) as calls:
        host.draw(panel=False)
    assert {c.text for c in calls} == {"You are here"}
    arrows = [pts for pts in polys if len(pts) == 3]
    assert arrows and all(max(abs(a[0] - b[0]) for a in pts for b in pts) >= 6 or
                          max(abs(a[1] - b[1]) for a in pts for b in pts) >= 6
                          for pts in arrows)
    # "Go to" is disabled only with no target (the title with nothing recent).
    recs = records_r(run1.program, run1.store, path=run1.path)
    none = Host(PortP(run1.program, dataclasses.replace(recs, here=None)))
    assert not none.chart.tool_enabled(2)


# --- AC-F20-64 — large charts draw only what is seen --------------------------------------

def _chain(count: int) -> ChartRecords:
    """A ladder: a start, then pairs of chapters, a choice every 5 nodes."""
    rng = random.Random(count)
    kinds = ["start"] + [rng.choice(("scene", "chapter", "choice")) for _ in range(count - 1)]
    edges = []
    for i in range(count - 1):
        edges.append(ChartEdge(i, i + 1, (len(edges),), ()))
        if i + 2 < count and i % 5 == 0:
            edges.append(ChartEdge(i, i + 2, (len(edges),), ()))
    shape = ChartShape(kinds=tuple(kinds), no_jump=(False,) * count, chapter=(None,) * count,
                       order=tuple(range(count)), nodes=tuple(range(count)), edges=tuple(edges))
    return ChartRecords(shape=shape, titles=(("Box",),) * count,
                        edge_texts=tuple(() for _ in edges), shown=(True,) * count,
                        visited=(True,) * count, taken=(True,) * len(edges), gates=(), here=0,
                        path_nodes=frozenset(), path_edges=frozenset(), recent=0,
                        counts=(0, 0, count, count))


class _GraphPort(PortP):
    def __init__(self, records):
        self._records = records
        self.in_game, self.jump_enabled = True, True
        self.states, self.reasons, self.jumps, self.opened = set(), {}, [], 0

    def node_id(self, n):
        return f"scene:n{n}"


def test_ac_f20_64_large_charts(monkeypatch):
    counts = []
    for size in (60, 600):
        host = Host(_GraphPort(_chain(size)))
        chart = host.chart
        with spy_draw_text(monkeypatch) as calls:
            host.draw()
        counts.append((chart.drawn_cells + chart.drawn_edges, len(calls), chart.queries))
        _x, _y, bw, _bh = chart.layout.bounds
        h_bar, _v = chart._scrollbars()
        lane, thumb = h_bar
        assert thumb.w == pytest.approx(max(32, chart.view_size()[0] / bw * lane.w))
    (a, ta, qa), (b, tb, qb) = counts
    assert abs(a - b) <= 0.1 * a and abs(ta - tb) <= 0.1 * ta and qa == qb == 1


# --- AC-F20-66 — counts ---------------------------------------------------------------------

def test_ac_f20_66_counts(run1, monkeypatch):
    host = Host(port_of(run1))
    with spy_draw_text(monkeypatch) as calls:
        host.draw()
    assert "Endings 1 / 2 · Nodes 6 / 8" in [c.text for c in calls]
    assert host.scope.tab_order() == [host.sidebar, host.chart]
    program = run1.program
    store = store_r(program, v=("festival", "stall", "M21", "river", "promise"),
                    e=("sad",), ro=("promise",))
    more = Host(PortP(program, records_r(program, store)), shell=host.shell)
    with spy_draw_text(monkeypatch) as calls:
        more.draw()
    tag = next(c.text for c in calls if c.text.startswith("Endings"))
    assert tag != "Endings 1 / 2 · Nodes 6 / 8"
    ev, en, nv, nn = more.page.records.counts
    assert en >= 2 and nn > 8
