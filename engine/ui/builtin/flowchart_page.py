"""``FlowchartPage``: the flowchart's game-menu and title page (F20 ``03-ui.md``;
``04-technical.md`` §5, §7.3, §7.8, §7.9; ``06`` AC-F20-24, 51, 56 to 66; ``07`` I-14).

Why this module exists: the player reads the story's map, finds where they are, and jumps
back to a point they reached. The page reads the story only through a ``FlowPort``
(``app/flowchart_ui.py``'s ``AppFlowPort`` over F20 s6's ``FlowService``), which gives masked
``ChartRecords`` and a ``LayoutJob`` (``ui/flowlayout.py``), so a title or choice the player hasn't earned never
reaches a draw call, a font measure, or the panel (SEC-F20-14(a)); ``ui`` never imports
``persist`` or ``app``.

- **Geometry** (03 "Flowchart page"; ``page_geometry``): in the body slot (416, 112, 808×552) a
  chart viewport 808 × H_c above a detail panel 808 × H_d ending at y 664, where H_d = 24 +
  p_t + 4 + p_h + 4 + p_b (150 / 208) and H_c = 552 − 12 − H_d; the panel body (an F13
  variable-row ``ScrollList``, 568 wide) and the Jump button (``confirm.button_width`` × H_b,
  bottom-right at (1212, 652)). The counts tag, the toolbar (zoom out, zoom in, "go to"), and
  the scrollbars lie over the viewport.
- **Chart** (``ChartView``, one F10 widget, one focus stop; 03 "Interaction"). The selection is
  the focus: arrows use F10's ``move_target`` over shown cell centres, Tab / Shift+Tab follow
  ``layout.reading`` and leave to the sidebar past its ends, Home and End (and "go to", gamepad
  west) select the first node and "You are here" (in game) or the most recent node (title),
  centred. Left with nothing that way goes to the sidebar (the game menu's edge rule); Up,
  Down, or Right with nothing shows the limit bar. Activate (and a double-click) is Jump when
  enabled, and nothing, silently, otherwise. Hover gives only the fill cue.
- **View** (float layout units, ``view``; zoom Normal 1, Overview 0.4 / s). A selection
  outside the safe zone pans by the smallest offset over 200 ms ``ease_in_out`` (a cut under
  reduced motion); more than one view away, or by Home, End, or "go to", it centres. The view
  never passes the chart's bounds by more than 64 (or what the safe zone needs), and an axis
  where the chart fits is centred. Drag (past 8 units), the wheel (120 × s per notch, Shift or
  a horizontal wheel for x), the right stick (past 0.25, up to 1,200 × s units/s), and the
  scrollbars pan freely and stop a pan. Zoom is a cut anchored on the selected node (keys) or
  the pointer (Ctrl+wheel).
- **Drawing** (03 "Layers"), clipped to the viewport: fill, back edges and detours, edges
  (path edges last), labels, cells, the focus ring and marker, the "You are here" tab, the
  limit bar, then the counts tag, toolbar, and scrollbars. Only what ``layout.visible`` gives
  for the viewport plus one cell is drawn (UI-F20-16); the dash phase comes from layout
  coordinates; title lines are cut once per (node, size) and kept (at most 512, I-14).
  Overview draws no text but the here tab, lines at least 2 wide and arrowheads at least 6.
- **Panel** (``panel_model``; 03 "Detail panel", 04 §2, 06 D2/D3): the meta row (kind word ·
  chapter), the title (heading style, wrapped, never cut), then a reason row, the choices
  (taken: bar and text; untaken: outlined bar and ``???``), an ending's title, or a gate's
  ``until`` rows. Jump is enabled iff ``port.can_jump(id)``; disabled with ``port.reason(id)``;
  absent for start, endings, gates, unvisited and ``no jump`` nodes, and with ``[flowchart]
  jump = false``. The body and Jump are never focus stops: Page Up/Down and the shoulders
  (``nav_extras``) scroll the body by view − p_b, the wheel over the panel by 3 × p_b, and a
  click on Jump jumps.
- **Raw input** the F10 reader doesn't map (``+``, ``=``, ``-`` and the keypad's, gamepad
  north and west, the right stick, Ctrl/Shift/horizontal wheel over the chart) reaches the
  page through ``MenuPageBase.on_event`` (the game menu calls it first).

Additions to 04's ``FlowPort`` (records carry no node ids): ``node_id(node)`` gives a graph
node's id for ``can_jump``, ``reason``, and ``jump`` (``app/flowchart_ui.py``'s ``AppFlowPort``
asks the confirm in game). A gate holds the title and 3 lines; over 3 ``until`` endings, the
third line reads "+N" (N = the endings not shown). ``reason`` gives a ``[words]`` key
(``flowchart_changed`` or ``flowchart_no_state``) or None. An ending's panel splits its box
text ``Heading: Title`` at the first ``": "`` (records hold the joined text only).

Theme: ``[theme.flowchart]`` (``flow_color`` resolves the following tokens); ``panel.*``,
``button.*``, ``list.*``, ``save.badge.*``, ``confirm.button_width``. Words: ``flowchart`` (the
heading) and the ``flowchart_*`` words.
"""

import dataclasses
import math
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

import pygame

from engine.render.effects import ease_in_out
from engine.render.frames import FrameSpec
from engine.runtime.flowchart import ChartRecords, show_text
from engine.ui.flowlayout import ChartLayout, ChartMetrics, LayoutJob
from engine.ui.focus import Box, FocusGroup, move_target
from engine.ui.layouts import (
    PAGE_BODY,
    SCROLLBAR_LANE,
    SCROLLBAR_MIN_THUMB,
    button_height,
    cut_to_width,
    pitch,
    scaled,
    wrap_text,
)
from engine.ui.menus import MenuPageBase
from engine.ui.nav import DIRECTIONS, InputKind, Nav
from engine.ui.theme import measure_with
from engine.ui.widgets import SCROLL_RADIUS, SCROLL_TRACK, Button, ListRow, Look, ScrollList, \
    Widget, clipped

if TYPE_CHECKING:
    from engine.core.config_schema import ThemeConfig
    from engine.render.canvas import Canvas
    from engine.render.text import FontSpec
    from engine.ui.input import UiEvent
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter

RGB = tuple[int, int, int]
HEADING: Final = "flowchart"          # the [words] key of the heading and both entries
OVERVIEW: Final = 0.4                 # canvas units per unit of the 100% chart
PAN_S: Final = 0.2                    # the pan to the selection
DRAG: Final = 8                       # a press moved further is a drag (pan), not a click
DOUBLE_S: Final = 0.4                 # a second click this soon (and ≤ DRAG away) is Jump
WHEEL_STEP: Final = 120               # × s per wheel notch
STICK_DEAD: Final = 0.25
STICK_SPEED: Final = 1200             # × s units per second at full tilt
STICK_MAX: Final = 32767
LIMIT_HOLD: Final = 0.4               # F14's limit cue: 400 ms hold, 100 ms fade
LIMIT_FADE: Final = 0.1
LIMIT_BAR: Final = 6
PRESS_S: Final = 0.1                  # the pressed look after a click or activation
VIEW_MARGIN: Final = 64               # the view may pass the chart's bounds by this much
RING_GAP: Final = 6                   # the focus ring lies 6 outside the cell, radius 12
RING_RADIUS: Final = 12
MARKER: Final = (12, 16)              # F10's marker, 8 left of the ring
MARKER_GAP: Final = 8
DASH: Final = (8, 6)                  # unvisited borders and untaken edges, on / off
ARROW: Final = (12, 10)               # an arrowhead's length and width (layout units at 100%)
ARROW_MIN: Final = 6
LINE_MIN: Final = 2
TITLE_INSET: Final = 32               # a title's area is W − 64 wide, 2 lines
TITLE_LINES: Final = 2
TITLE_CACHE: Final = 512              # cut title lines kept (07 I-14)
TAG_PAD: Final = 16                   # an F11 tag: text + 16 wide, t + 10 tall
TAG_TEXT_MAX: Final = 168             # a label's text fits 168 × s
TOOL_GAP: Final = 4
OVERLAY_INSET: Final = 8
ZONE_INSET: Final = 16
PANEL_GAP: Final = 12                 # viewport → panel
PANEL_PAD: Final = 12
PANEL_BODY_W: Final = 568
ROW_GAP: Final = 4                    # after the meta row and after the title
CHOICE_BAR: Final = 4
CHOICE_TEXT_X: Final = 16
GATE_BOX: Final = 16
GATE_LINES: Final = 3                 # until lines under a gate's title (then "+N")
LOCK: Final = (16, 20)
DIAMOND: Final = 10
SEPARATOR: Final = " · "
FRAME_SLICE: Final = 12               # a kind's frame_image corner size
VIEW_BORDER: Final = 2                # the viewport's border (panel.border_color), radius 12
VIEW_RADIUS: Final = 12

Zoom = Literal["normal", "overview"]
JumpState = Literal["enabled", "disabled", "absent"]

KIND_WORDS: Final[dict[str, str]] = {
    "start": "flowchart_start", "chapter": "flowchart_chapter", "choice": "flowchart_choice",
    "scene": "flowchart_scene", "ending": "flowchart_ending", "gate": "flowchart_route"}

# 03 "Theme tokens": a ``None`` token follows another (``flow_color``).
FOLLOWS: Final[dict[str, str]] = {
    "flowchart.node.text_color": "panel.text_color",
    "flowchart.gate.fill_color": "flowchart.fill_color",
    "flowchart.unknown.text_color": "button.disabled.text_color",
    "flowchart.path.line_color": "button.marker.fill_color",
    "flowchart.here.fill_color": "save.newest.fill_color",
    "flowchart.here.text_color": "save.newest.text_color",
}


def flow_color(cfg: "ThemeConfig", path: str) -> RGB:
    """The color at token ``path`` under ``[theme]``, following ``FOLLOWS`` while it is None."""
    node: object = cfg
    for part in path.split("."):
        node = getattr(node, part)
    if node is None:
        return flow_color(cfg, FOLLOWS[path])
    return tuple(node)                                          # type: ignore[return-value]


# --- Seams ---------------------------------------------------------------------------------------

class FlowPort(Protocol):
    """What the page reads (04 §5, plus ``node_id``; module docstring). ``in_game``: opened
    from the game menu ("You are here", the confirm); ``jump_enabled``: ``[flowchart] jump``."""

    in_game: bool
    jump_enabled: bool

    def records(self) -> ChartRecords: ...

    def node_id(self, node: int) -> str: ...

    def can_jump(self, node_id: str) -> bool: ...

    def reason(self, node_id: str) -> str | None: ...

    def jump(self, node_id: str, by: InputKind) -> None: ...

    def layout(self, metrics: ChartMetrics) -> LayoutJob: ...


# --- Geometry ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PageGeometry:
    """03's layout table at one text scale (canvas units)."""

    scale: float
    t: int                    # flowchart.text_size × s
    p_t: int
    p_h: int                  # panel heading pitch
    p_b: int                  # panel body pitch
    viewport: Box
    panel: Box
    body: Box
    jump: Box
    tool: int                 # a toolbar button's side, t + 16
    toolbar: tuple[Box, Box, Box]     # zoom out, zoom in, go to

    @property
    def tag_h(self) -> int:
        return self.t + 10


def page_geometry(cfg: "ThemeConfig", scale: float, slot: Box = PAGE_BODY) -> PageGeometry:
    t = scaled(cfg.flowchart.text_size, scale)
    p_t = pitch(t)
    p_h = pitch(scaled(cfg.panel.heading.text_size, scale))
    p_b = pitch(scaled(cfg.panel.text_size, scale))
    h_d = 2 * PANEL_PAD + p_t + ROW_GAP + p_h + ROW_GAP + p_b
    h_c = slot.h - PANEL_GAP - h_d
    viewport = Box(slot.x, slot.y, slot.w, h_c)
    panel = Box(slot.x, slot.y + h_c + PANEL_GAP, slot.w, h_d)
    body = Box(panel.x + PANEL_PAD, panel.y + PANEL_PAD, PANEL_BODY_W, h_d - 2 * PANEL_PAD)
    h_b = button_height(cfg.button.text_size, scale=scale, minimum=cfg.button.height)
    w_b = cfg.confirm.button_width
    jump = Box(panel.right - PANEL_PAD - w_b, panel.bottom - PANEL_PAD - h_b, w_b, h_b)
    tool = t + 16
    right = viewport.right - OVERLAY_INSET
    top = viewport.y + OVERLAY_INSET
    boxes = tuple(Box(right - (3 - i) * tool - (2 - i) * TOOL_GAP, top, tool, tool)
                  for i in range(3))
    return PageGeometry(scale, t, p_t, p_h, p_b, viewport, panel, body, jump, tool,
                        boxes)                                   # type: ignore[arg-type]


# --- The panel model -----------------------------------------------------------------------------

@dataclass(frozen=True)
class PanelRow:
    """One panel row: ``kind`` ``meta``, ``title``, ``heading`` (an ending's heading),
    ``body``, ``reason``, ``choice``, or ``gate``; ``unknown``: shown as ``???``; ``mark``: a
    taken choice or a reached ``until`` ending."""

    kind: str
    text: str
    unknown: bool = False
    mark: bool = False


@dataclass(frozen=True)
class PanelModel:
    node: int | None
    rows: tuple[PanelRow, ...]
    jump: JumpState
    node_id: str | None = None


def _text(records: ChartRecords, node: int, word: Callable[[str], str]) -> str | None:
    """A node's shown title: None for ``???``; ``()`` is the kind word."""
    title = records.titles[node]
    if title is None:
        return None
    kind = records.shape.kinds[node]
    return show_text(title, var=word("flowchart_var"), empty=word(KIND_WORDS[kind]))


def panel_model(records: ChartRecords, node: int | None, port: FlowPort,
                word: Callable[[str], str]) -> PanelModel:
    """03's "Detail panel" table for ``node`` (06 D2, D3; module docstring)."""
    if node is None:
        return PanelModel(None, (), "absent")
    shape = records.shape
    kind = shape.kinds[node]
    unknown = word("flowchart_unknown")
    kind_word = word(KIND_WORDS[kind])
    rows: list[PanelRow] = []
    if kind == "gate":
        view = next((g for g in records.gates if g.node == node), None)
        title = show_text(view.title, var=word("flowchart_var")) \
            if view is not None and view.title is not None else None
        rows.append(PanelRow("meta", kind_word))
        rows.append(PanelRow("title", title if title is not None else unknown, title is None))
        for row in (view.rows if view is not None else ()):
            text = show_text(row.text, var=word("flowchart_var")) if row.text is not None \
                else None
            rows.append(PanelRow("gate", text if text is not None else unknown,
                                 text is None, row.reached))
        return PanelModel(node, tuple(rows), "absent")
    if kind == "start":
        return PanelModel(node, (PanelRow("meta", kind_word), PanelRow("title", kind_word)),
                          "absent")
    if not records.visited[node]:
        return PanelModel(node, (PanelRow("meta", kind_word), PanelRow("title", unknown, True)),
                          "absent")
    chapter = shape.chapter[node]
    meta = kind_word
    if chapter is not None:
        name = _text(records, chapter, word) if 0 <= chapter < len(records.titles) else None
        meta += SEPARATOR + (name if name is not None else unknown)
    rows.append(PanelRow("meta", meta))
    title = _text(records, node, word) or unknown
    if kind == "ending":
        heading, sep, rest = title.partition(": ")
        rows.append(PanelRow("heading", heading))
        if sep:
            rows.append(PanelRow("body", rest))
        return PanelModel(node, tuple(rows), "absent")
    rows.append(PanelRow("title", title))
    node_id = port.node_id(node)
    jump: JumpState = "absent"
    if port.jump_enabled:
        if shape.no_jump[node]:
            rows.append(PanelRow("reason", word("flowchart_no_jump")))
        elif port.can_jump(node_id):
            jump = "enabled"
        else:
            jump = "disabled"
            rows.append(PanelRow("reason", word(port.reason(node_id) or "flowchart_no_state")))
    if kind == "choice":
        for k, edge in enumerate(shape.edges):
            if edge.src != node:
                continue
            for text in records.edge_texts[k]:
                shown = show_text(text, var=word("flowchart_var")) if text is not None else None
                rows.append(PanelRow("choice", shown if shown is not None else unknown,
                                     shown is None, shown is not None))
    return PanelModel(node, tuple(rows), jump, node_id)


# --- The chart -----------------------------------------------------------------------------------

@dataclass
class _Press:
    """A button-1 press in the viewport: on a toolbar button, a scrollbar, or the chart."""

    what: str                       # "tool", "vthumb", "hthumb", "chart", "none"
    pos: tuple[float, float]
    view: tuple[float, float]
    index: int = -1
    dragged: bool = False


class ChartView(Widget):
    """The chart viewport (module docstring): one focus stop whose selection is the focus."""

    repeatable = True

    def __init__(self, page: "FlowchartPage") -> None:
        super().__init__()
        self.page = page
        self.records: ChartRecords | None = None
        self.layout: ChartLayout | None = None
        self.geometry: PageGeometry | None = None
        self.zoom: Zoom = "normal"
        self.view = [0.0, 0.0]          # the layout point at the viewport's top-left
        self.selected: int | None = None
        self.hover: int | None = None
        self.clicked = False            # the selection was clicked (drawn focused)
        self.pan: tuple[tuple[float, float], tuple[float, float], float] | None = None
        self.limit: tuple[Nav, float] | None = None
        self.stick = [0.0, 0.0]
        self.press: _Press | None = None
        self.pressed_left = 0.0
        self.tool_pressed: tuple[int, float] | None = None
        self.last_click: tuple[float, tuple[float, float], int] | None = None
        self.now = 0.0
        self.drawn_cells = 0            # this frame's work (UI-F20-16, AC-F20-64)
        self.drawn_edges = 0
        self.queries = 0
        self._cells: list[int] = []
        self._centres: list[Box] = []
        self._titles: OrderedDict[tuple, tuple[str, ...]] = OrderedDict()

    # -- set up --

    def setup(self, records: ChartRecords, layout: ChartLayout, geometry: PageGeometry) -> None:
        self.records, self.layout, self.geometry = records, layout, geometry
        self.box = geometry.viewport
        self._cells = [c.node for c in layout.cells]
        self._centres = [Box(*c.rect) for c in layout.cells]

    @property
    def k(self) -> float:
        """Canvas units per layout unit."""
        assert self.geometry is not None
        return 1.0 if self.zoom == "normal" else OVERVIEW / self.geometry.scale

    def view_size(self) -> tuple[float, float]:
        vp = self.box
        return vp.w / self.k, vp.h / self.k

    def overflow(self) -> tuple[bool, bool]:
        """Whether the chart overflows the view across and down (a scrollbar shows)."""
        assert self.layout is not None
        _x, _y, w, h = self.layout.bounds
        vw, vh = self.view_size()
        return w > vw, h > vh

    def safe_zone(self) -> Box:
        """03 "Safe zone" (canvas units)."""
        g = self.geometry
        assert g is not None
        vp = self.box
        across, down = self.overflow()
        top = OVERLAY_INSET + g.tool + OVERLAY_INSET
        right = ZONE_INSET + (SCROLLBAR_LANE if down else 0)
        bottom = ZONE_INSET + (SCROLLBAR_LANE if across else 0)
        return Box(vp.x + ZONE_INSET, vp.y + top, vp.w - ZONE_INSET - right,
                   vp.h - top - bottom)

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        k = self.k
        return self.box.x + (x - self.view[0]) * k, self.box.y + (y - self.view[1]) * k

    def to_layout(self, pos: tuple[float, float]) -> tuple[float, float]:
        k = self.k
        return self.view[0] + (pos[0] - self.box.x) / k, self.view[1] + (pos[1] - self.box.y) / k

    def cell_box(self, node: int) -> Box | None:
        """``node``'s cell on the canvas at the current view."""
        assert self.layout is not None
        cell = self.layout.cell(node)
        if cell is None:
            return None
        x, y, w, h = cell.rect
        cx, cy = self.to_canvas(x, y)
        return Box(cx, cy, w * self.k, h * self.k)

    def here(self) -> int | None:
        """The "You are here" node (in game, shown and laid out), or None."""
        records = self.records
        if records is None or not self.page.port.in_game or records.here is None:
            return None
        return records.here if self.layout is not None and self.layout.cell(records.here) \
            else None

    def goto_target(self) -> int | None:
        """End / west / "go to": here in game, the most recent node from the title."""
        records = self.records
        if records is None or self.layout is None:
            return None
        target = self.here() if self.page.port.in_game else records.recent
        return target if target is not None and self.layout.cell(target) is not None else None

    # -- the view --

    def _margins(self) -> tuple[float, float, float, float]:
        """How far (layout units) the view may pass the bounds: left, top, right, bottom."""
        g = self.geometry
        assert g is not None
        zone, vp, k = self.safe_zone(), self.box, self.k
        ring = RING_GAP + 4
        left = max(VIEW_MARGIN, zone.x - vp.x + ring) / k
        top = max(VIEW_MARGIN, zone.y - vp.y + ring + g.tag_h) / k
        right = max(VIEW_MARGIN, vp.right - zone.right + ring) / k
        bottom = max(VIEW_MARGIN, vp.bottom - zone.bottom + ring) / k
        return left, top, right, bottom

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        """03 "Keeping the selection in view": within the bounds plus the margin; an axis
        where the chart fits is centred."""
        assert self.layout is not None
        bx, by, bw, bh = self.layout.bounds
        vw, vh = self.view_size()
        left, top, right, bottom = self._margins()

        def axis(v: float, b0: float, size: float, view: float, lo: float, hi: float) -> float:
            if size <= view:
                return b0 + (size - view) / 2
            return min(max(v, b0 - lo), b0 + size + hi - view)

        return axis(x, bx, bw, vw, left, right), axis(y, by, bh, vh, top, bottom)

    def set_view(self, x: float, y: float) -> None:
        self.view = list(self.clamp(x, y))

    def stop_pan(self) -> None:
        self.pan = None

    def _target_for(self, node: int, centre: bool) -> tuple[float, float]:
        assert self.layout is not None and self.geometry is not None
        cell = self.layout.cell(node)
        assert cell is not None
        k = self.k
        x, y, w, h = cell.rect
        vw, vh = self.view_size()
        if centre:
            return self.clamp(x + w / 2 - vw / 2, y + h / 2 - vh / 2)
        ring = (RING_GAP + 4) / k
        tab = self.geometry.tag_h / k if node == self.here() else 0.0
        need = (x - ring, y - ring - tab, x + w + ring, y + h + ring)
        zone = self.safe_zone()
        zx0, zy0 = self.to_layout((zone.x, zone.y))
        zx1, zy1 = self.to_layout((zone.right, zone.bottom))
        vx, vy = self.view

        def shift(lo: float, hi: float, z0: float, z1: float) -> float:
            if hi - lo > z1 - z0:
                return lo - z0                              # larger than the zone: top-left
            if lo < z0:
                return lo - z0
            if hi > z1:
                return hi - z1
            return 0.0

        dx = shift(need[0], need[2], zx0, zx1)
        dy = shift(need[1], need[3], zy0, zy1)
        if abs(dx) > vw or abs(dy) > vh:
            return self.clamp(x + w / 2 - vw / 2, y + h / 2 - vh / 2)
        return self.clamp(vx + dx, vy + dy)

    def reveal(self, node: int, *, centre: bool = False) -> None:
        """Bring ``node`` into the safe zone: a 200 ms ``ease_in_out`` pan from where the view
        is now, or a cut under reduced motion."""
        target = self._target_for(node, centre)
        here = (self.view[0], self.view[1])
        if abs(target[0] - here[0]) < 1e-6 and abs(target[1] - here[1]) < 1e-6:
            self.pan = None
            return
        if self.page.reduce_motion():
            self.view = list(target)
            self.pan = None
            return
        self.pan = (here, target, 0.0)

    def centre_on(self, node: int) -> None:
        self.pan = None
        self.view = list(self._target_for(node, True))

    def set_zoom(self, zoom: Zoom, anchor: tuple[float, float] | None = None) -> bool:
        """Normal or Overview, a cut anchored on canvas point ``anchor`` (default: the
        selected cell's centre)."""
        if zoom == self.zoom or self.layout is None:
            return False
        if anchor is None:
            box = self.cell_box(self.selected) if self.selected is not None else None
            anchor = box.center if box is not None else self.box.center
        lx, ly = self.to_layout(anchor)
        self.zoom = zoom
        self.pan = None
        k = self.k
        self.set_view(lx - (anchor[0] - self.box.x) / k, ly - (anchor[1] - self.box.y) / k)
        return True

    def pan_by(self, dx: float, dy: float) -> None:
        """Free pan by (dx, dy) layout units; stops a pan to the selection."""
        self.pan = None
        self.set_view(self.view[0] + dx, self.view[1] + dy)

    # -- selection --

    def select(self, node: int, *, centre: bool = False, by_click: bool = False) -> None:
        if self.layout is None or self.layout.cell(node) is None:
            return
        self.selected = node
        self.clicked = by_click
        self.page.selection_changed()
        self.reveal(node, centre=centre)

    def _direction(self, d: Nav) -> int | None:
        assert self.layout is not None
        cur = self.layout.cell(self.selected) if self.selected is not None else None
        if cur is None:
            return None
        cands = [(n, box) for n, box in zip(self._cells, self._centres) if n != self.selected]
        found = move_target(Box(*cur.rect), [box for _n, box in cands], d)
        return None if found is None else cands[found][0]

    def show_limit(self, d: Nav) -> None:
        """The limit bar on that edge; a repeat restarts its hold (at most ~2.5 a second)."""
        self.limit = (d, 0.0)

    def go_to(self) -> bool:
        target = self.goto_target()
        if target is None:
            return False
        self.select(target, centre=True)
        return True

    # -- Widget --

    def on_nav(self, d: Nav) -> bool:
        layout = self.layout
        if layout is None or not layout.reading:
            return False
        if self.selected is None:
            self.select(layout.reading[0], centre=True)
            return True
        if d in DIRECTIONS:
            target = self._direction(d)
            if target is None:
                if d is Nav.LEFT:
                    return False                        # the game menu's edge: the sidebar
                self.show_limit(d)
                return True
            self.select(target)
            return True
        reading = layout.reading
        if d in (Nav.NEXT, Nav.PREV):
            at = reading.index(self.selected) if self.selected in reading else -1
            at += 1 if d is Nav.NEXT else -1
            if not 0 <= at < len(reading):
                return False                            # Tab on to the sidebar
            self.select(reading[at])
            return True
        if d is Nav.HOME:
            self.select(reading[0], centre=True)
            return True
        if d is Nav.END:
            return self.go_to()
        return False

    def tab_entered(self, forward: bool) -> None:
        """Tab from the sidebar enters at the selected node (nothing to do)."""

    def activate(self) -> None:
        if self.page.jump_state() == "enabled":
            self.pressed_left = PRESS_S
            self.page.jump(self.page.input_kind())

    def accepts_click(self, pos: tuple[float, float]) -> bool:
        return False                                    # clicks act in ``on_mouse("up")``

    def node_at(self, pos: tuple[float, float]) -> int | None:
        """The shown node or gate drawn under canvas point ``pos`` this frame."""
        if self.layout is None or not self.box.contains(pos):
            return None
        x, y = self.to_layout(pos)
        cells, _edges = self.layout.visible((math.floor(x), math.floor(y), 1, 1))
        for node in cells:
            cell = self.layout.cell(node)
            assert cell is not None
            cx, cy, w, h = cell.rect
            if cx <= x < cx + w and cy <= y < cy + h:
                return node
        return None

    def _scrollbars(self) -> tuple[tuple[Box, Box] | None, tuple[Box, Box] | None]:
        """(lane, thumb) across (bottom) and down (right), each None when it fits."""
        assert self.layout is not None
        vp = self.box
        across, down = self.overflow()
        bx, by, bw, bh = self.layout.bounds
        vw, vh = self.view_size()
        h_bar = v_bar = None
        if across:
            lane = Box(vp.x, vp.bottom - SCROLLBAR_LANE,
                       vp.w - (SCROLLBAR_LANE if down else 0), SCROLLBAR_LANE)
            size = max(SCROLLBAR_MIN_THUMB, min(lane.w, vw / bw * lane.w))
            lo, hi = self._range(0)
            share = 0.0 if hi <= lo else (self.view[0] - lo) / (hi - lo)
            h_bar = (lane, Box(lane.x + max(0.0, min(1.0, share)) * (lane.w - size), lane.y,
                               size, lane.h))
        if down:
            lane = Box(vp.right - SCROLLBAR_LANE, vp.y, SCROLLBAR_LANE,
                       vp.h - (SCROLLBAR_LANE if across else 0))
            size = max(SCROLLBAR_MIN_THUMB, min(lane.h, vh / bh * lane.h))
            lo, hi = self._range(1)
            share = 0.0 if hi <= lo else (self.view[1] - lo) / (hi - lo)
            v_bar = (lane, Box(lane.x, lane.y + max(0.0, min(1.0, share)) * (lane.h - size),
                               lane.w, size))
        return h_bar, v_bar

    def _range(self, axis: int) -> tuple[float, float]:
        """The view's lowest and highest position on ``axis``."""
        assert self.layout is not None
        b0, size = self.layout.bounds[axis], self.layout.bounds[axis + 2]
        view = self.view_size()[axis]
        margins = self._margins()
        return b0 - margins[axis], b0 + size + margins[axis + 2] - view

    def tool_enabled(self, index: int) -> bool:
        if index == 0:
            return self.zoom == "normal"
        if index == 1:
            return self.zoom == "overview"
        return self.goto_target() is not None

    def use_tool(self, index: int) -> None:
        if not self.tool_enabled(index):
            return
        self.tool_pressed = (index, PRESS_S)
        if index == 0:
            self.set_zoom("overview")
        elif index == 1:
            self.set_zoom("normal")
        else:
            self.go_to()

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        if self.layout is None or self.geometry is None:
            return False
        if kind == "hover":
            self.hover = self.node_at(pos)
            return False
        if kind == "down":
            self.press = self._press_at(pos)
            return True
        press = self.press
        if press is None:
            return False
        if kind == "drag":
            dx, dy = pos[0] - press.pos[0], pos[1] - press.pos[1]
            if press.what == "chart":
                if not press.dragged and math.hypot(dx, dy) > DRAG:
                    press.dragged = True
                if press.dragged:
                    self.pan = None
                    k = self.k
                    self.set_view(press.view[0] - dx / k, press.view[1] - dy / k)
                return True
            if press.what in ("hthumb", "vthumb"):
                axis = 0 if press.what == "hthumb" else 1
                h_bar, v_bar = self._scrollbars()
                bar = h_bar if axis == 0 else v_bar
                if bar is not None:
                    lane, thumb = bar
                    free = (lane.w - thumb.w) if axis == 0 else (lane.h - thumb.h)
                    lo, hi = self._range(axis)
                    if free > 0:
                        moved = (dx if axis == 0 else dy) / free * (hi - lo)
                        view = list(press.view)
                        view[axis] += moved
                        self.pan = None
                        self.set_view(view[0], view[1])
                return True
            return False
        if kind == "up":
            self.press = None
            if press.what == "tool":
                if self.geometry.toolbar[press.index].contains(pos):
                    self.use_tool(press.index)
                return True
            if press.what == "chart" and not press.dragged:
                node = self.node_at(pos)
                if node is not None:
                    self._click(node, pos)
                return True
            return True
        return False

    def _press_at(self, pos: tuple[float, float]) -> _Press:
        view = (self.view[0], self.view[1])
        for index, box in enumerate(self.geometry.toolbar if self.geometry else ()):
            if box.contains(pos):
                return _Press("tool" if self.tool_enabled(index) else "none", pos, view, index)
        h_bar, v_bar = self._scrollbars()
        vw, vh = self.view_size()
        for axis, bar in ((0, h_bar), (1, v_bar)):
            if bar is None or not bar[0].contains(pos):
                continue
            lane, thumb = bar
            if thumb.contains(pos):
                return _Press("hthumb" if axis == 0 else "vthumb", pos, view)
            before = pos[axis] < (thumb.x if axis == 0 else thumb.y)
            step = (vw if axis == 0 else vh) * (-1 if before else 1)
            self.pan_by(step if axis == 0 else 0.0, step if axis == 1 else 0.0)
            return _Press("none", pos, view)
        return _Press("chart", pos, view)

    def _click(self, node: int, pos: tuple[float, float]) -> None:
        last = self.last_click
        double = (last is not None and last[2] == node and self.now - last[0] <= DOUBLE_S
                  and math.hypot(pos[0] - last[1][0], pos[1] - last[1][1]) <= DRAG)
        self.select(node, by_click=True)
        self.pressed_left = PRESS_S
        if double:
            self.last_click = None
            if self.page.jump_state() == "enabled":
                self.page.jump(InputKind.MOUSE)
            return
        self.last_click = (self.now, pos, node)

    def wheel(self, pos: tuple[float, float], x: int, y: int, mods: int) -> bool:
        """The wheel over the viewport (``on_event``: the F10 path loses its modifiers and
        its x)."""
        if self.geometry is None or not self.box.contains(pos):
            return False
        if mods & pygame.KMOD_CTRL:
            if y:
                self.set_zoom("normal" if y > 0 else "overview", anchor=pos)
            return True
        step = WHEEL_STEP * self.geometry.scale / self.k
        if mods & pygame.KMOD_SHIFT:
            self.pan_by(-y * step, 0.0)
        elif x:
            self.pan_by(x * step, -y * step)
        else:
            self.pan_by(0.0, -y * step)
        return True

    # -- frames --

    def update(self, dt: float) -> None:
        self.now += dt
        if self.pan is not None:
            start, end, t = self.pan
            t += dt
            w = ease_in_out(t / PAN_S)
            self.view = [start[0] + (end[0] - start[0]) * w, start[1] + (end[1] - start[1]) * w]
            self.pan = None if t >= PAN_S - 1e-9 else (start, end, t)
        if self.geometry is not None and any(abs(v) > STICK_DEAD for v in self.stick):
            speed = STICK_SPEED * self.geometry.scale / self.k
            move = [0.0, 0.0]
            for axis, v in enumerate(self.stick):
                if abs(v) > STICK_DEAD:
                    move[axis] = math.copysign((abs(v) - STICK_DEAD) / (1 - STICK_DEAD), v) \
                        * speed * dt
            self.pan_by(move[0], move[1])
        if self.limit is not None:
            d, age = self.limit
            age += dt
            end = LIMIT_HOLD if self.page.reduce_motion() else LIMIT_HOLD + LIMIT_FADE
            self.limit = None if age >= end - 1e-9 else (d, age)
        self.pressed_left = max(0.0, self.pressed_left - dt)
        if self.tool_pressed is not None:
            index, left = self.tool_pressed
            left -= dt
            self.tool_pressed = None if left <= 1e-9 else (index, left)

    # -- drawing --

    def draw(self, p: "Painter", look: Look) -> None:
        layout, records, g = self.layout, self.records, self.geometry
        if layout is None or records is None or g is None:
            return
        cfg = self.page.cfg
        canvas = p.canvas
        vp = self.box
        focused = look.state in ("focused", "pressed") and self.page.keyed(self)
        surface = canvas.surface
        assert surface is not None
        canvas.fill(flow_color(cfg, "flowchart.fill_color"), (vp.x, vp.y, vp.w, vp.h))
        with clipped(p, vp):
            k = self.k
            margin = max(layout.metrics.cell_w, layout.metrics.cell_h)
            lx, ly = self.view
            vw, vh = self.view_size()
            rect = (math.floor(lx - margin), math.floor(ly - margin),
                    math.ceil(vw + 2 * margin), math.ceil(vh + 2 * margin))
            cells, edges = layout.visible(rect)
            self.queries = 1
            self.drawn_cells, self.drawn_edges = len(cells), len(edges)
            normal = self.zoom == "normal"
            order = sorted(edges, key=lambda e: (not layout.edges[e].loop,
                                                 e in records.path_edges))
            for e in order:
                self._draw_edge(canvas, e)
            if normal:
                for e in edges:
                    if layout.edges[e].label is not None:
                        self._draw_label(canvas, e)
            for node in cells:
                self._draw_cell(p, node, focused, normal)
            if self.selected is not None and self.selected in cells:
                self._draw_ring(p, self.selected, focused)
            here = self.here()
            if here is not None:
                self._draw_here(canvas, here)
            self._draw_limit(canvas)
            self._draw_overlays(p)
        pygame.draw.rect(surface, cfg.panel.border_color,
                         canvas.rect_to_px((vp.x, vp.y, vp.w, vp.h)),
                         max(1, round(VIEW_BORDER * canvas.scale)),
                         border_radius=round(VIEW_RADIUS * canvas.scale))

    def _width(self, w: float) -> float:
        """A line ``w`` wide at 100% at this zoom (scaled by s; at least 2)."""
        assert self.geometry is not None
        return max(LINE_MIN, round(w * self.geometry.scale * self.k))

    def _segment(self, canvas: "Canvas", a: tuple[float, float], b: tuple[float, float],
                 color: RGB, width: float, dashed: bool) -> None:
        """An axis-aligned line from layout point ``a`` to ``b`` as filled rectangles, cut to
        the viewport; dashes keep their place on the chart (phase from layout 0)."""
        k = self.k
        vp = self.box
        half = width / 2
        if a[1] == b[1]:
            lo, hi = sorted((a[0], b[0]))
            axis, fixed = 0, a[1]
        else:
            lo, hi = sorted((a[1], b[1]))
            axis, fixed = 1, a[0]
        start = self.view[axis]
        # Cut to the viewport (plus a line width) before any drawing.
        view_lo = start - width / k
        view_hi = start + (vp.w if axis == 0 else vp.h) / k + width / k
        lo, hi = max(lo, view_lo), min(hi, view_hi)
        if hi < lo:
            return
        pieces: list[tuple[float, float]]
        if dashed:
            on, off = DASH[0] / k, DASH[1] / k
            period = on + off
            pieces = []
            at = math.floor(lo / period) * period
            while at < hi:
                s0, s1 = max(at, lo), min(at + on, hi)
                if s1 > s0:
                    pieces.append((s0, s1))
                at += period
        else:
            pieces = [(lo, hi)]
        for s0, s1 in pieces:
            if axis == 0:
                x0, y0 = self.to_canvas(s0, fixed)
                x1, _ = self.to_canvas(s1, fixed)
                canvas.fill(color, (x0 - (0 if dashed else half), y0 - half,
                                    x1 - x0 + (0 if dashed else width), width))
            else:
                x0, y0 = self.to_canvas(fixed, s0)
                _, y1 = self.to_canvas(fixed, s1)
                canvas.fill(color, (x0 - half, y0 - (0 if dashed else half), width,
                                    y1 - y0 + (0 if dashed else width)))

    def _draw_edge(self, canvas: "Canvas", e: int) -> None:
        records, layout = self.records, self.layout
        assert records is not None and layout is not None and self.geometry is not None
        cfg = self.page.cfg
        laid = layout.edges[e]
        on_path = e in records.path_edges
        taken = records.taken[e]
        if on_path:
            color = flow_color(cfg, "flowchart.path.line_color")
            width = self._width(cfg.flowchart.path.line_width)
        else:
            color = flow_color(cfg, "flowchart.edge.line_color")
            line = cfg.flowchart.edge.line_width
            width = self._width(line if taken else max(2, line - 1))
        dashed = not taken and not on_path
        points = laid.points
        for a, b in zip(points, points[1:]):
            self._segment(canvas, a, b, color, width, dashed)
        if len(points) >= 2:
            self._arrow(canvas, points[-2], points[-1], color)

    def _arrow(self, canvas: "Canvas", a: tuple[int, int], b: tuple[int, int],
               color: RGB) -> None:
        """A 12 × 10 arrowhead (at least 6) on the last segment, its tip at ``b``."""
        assert self.geometry is not None
        k, s = self.k, self.geometry.scale
        length = max(ARROW_MIN, ARROW[0] * s * k)
        half = max(ARROW_MIN, ARROW[1] * s * k) / 2
        tx, ty = self.to_canvas(*b)
        vp = self.box
        if not (vp.x - length <= tx <= vp.right + length
                and vp.y - length <= ty <= vp.bottom + length):
            return
        dx, dy = b[0] - a[0], b[1] - a[1]
        ux, uy = (math.copysign(1, dx), 0.0) if abs(dx) >= abs(dy) else (0.0, math.copysign(1, dy))
        bx, by = tx - ux * length, ty - uy * length
        points = [(tx, ty), (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)]
        surface = canvas.surface
        assert surface is not None
        pygame.draw.polygon(surface, color, [canvas.px(x, y) for x, y in points])

    def _font(self, size: int, *, bold: bool = False, italic: bool = False) -> "FontSpec":
        return self.page.theme.font(size, bold=bold, italic=italic)

    def _draw_label(self, canvas: "Canvas", e: int) -> None:
        """An F11 tag on the label place: the choice texts joined " / " (``???`` for an
        untaken one), fitted to 168 × s with "…", backed by ``flowchart.fill_color``."""
        records, layout, g = self.records, self.layout, self.geometry
        assert records is not None and layout is not None and g is not None
        cfg = self.page.cfg
        word = self.page.words.get
        label = layout.edges[e].label
        assert label is not None
        texts = records.edge_texts[e]
        unknown = word("flowchart_unknown")
        parts = [show_text(t, var=word("flowchart_var")) if t is not None else unknown
                 for t in texts] or [unknown]
        text = " / ".join(parts)
        known = all(t is not None for t in texts) and bool(texts)
        color = flow_color(cfg, "flowchart.node.text_color") if known \
            else flow_color(cfg, "flowchart.unknown.text_color")
        size = g.t
        measure = self.page.measure
        fitted = self._fit(("label", e, size), text, TAG_TEXT_MAX * g.scale, size, measure)
        x, y, w, h = label
        cx, cy = self.to_canvas(x + w / 2, y + h / 2)
        tag_w = min(w, measure(fitted, size) + TAG_PAD * g.scale)
        canvas.fill(flow_color(cfg, "flowchart.fill_color"),
                    (cx - tag_w / 2, cy - g.tag_h / 2, tag_w, g.tag_h))
        canvas.draw_text(fitted, self._font(size), color, (cx, cy), anchor="center")

    def _fit(self, key: tuple, text: str, width: float, size: int, measure) -> str:
        found = self._titles.get(key + (text,))
        if found is None:
            found = (cut_to_width(text, width, size, measure),)
            self._remember(key + (text,), found)
        return found[0]

    def _remember(self, key: tuple, value: tuple[str, ...]) -> None:
        self._titles[key] = value
        self._titles.move_to_end(key)
        while len(self._titles) > TITLE_CACHE:
            self._titles.popitem(last=False)

    def _title_lines(self, node: int, text: str, width: float, size: int) -> tuple[str, ...]:
        """The box's title: 2 lines at ``size`` in ``width``, the last cut with "…"; once per
        (node, size, text), at most 512 kept (07 I-14)."""
        key = ("title", node, size, text)
        found = self._titles.get(key)
        if found is not None:
            self._titles.move_to_end(key)
            return found
        measure = self.page.measure
        lines = wrap_text(text, width, size, measure) or [text]
        if len(lines) > TITLE_LINES:
            rest = " ".join(lines[TITLE_LINES - 1:])
            lines = [*lines[:TITLE_LINES - 1], cut_to_width(rest, width, size, measure)]
        found = tuple(cut_to_width(line, width, size, measure) for line in lines)
        self._remember(key, found)
        return found

    def _shape_points(self, kind: str, box: Box) -> list[tuple[float, float]] | None:
        """The polygon of a choice (hexagon) or ending (V-notch), else None (a rectangle)."""
        assert self.geometry is not None
        inset = 20 * self.geometry.scale * self.k
        x, y, r, b = box.x, box.y, box.right, box.bottom
        cy = y + box.h / 2
        if kind == "choice":
            return [(x + inset, y), (r - inset, y), (r, cy), (r - inset, b), (x + inset, b),
                    (x, cy)]
        if kind == "ending":
            return [(x, y), (r, y), (r - inset, cy), (r, b), (x, b)]
        return None

    def _radius(self, kind: str, box: Box) -> float:
        assert self.geometry is not None
        if kind == "start":
            return box.h / 2
        if kind == "scene":
            return 16 * self.geometry.scale * self.k
        return 0.0

    def _draw_cell(self, p: "Painter", node: int, focused: bool, normal: bool) -> None:
        records = self.records
        assert records is not None and self.geometry is not None
        canvas = p.canvas
        cfg = self.page.cfg
        box = self.cell_box(node)
        assert box is not None
        kind = records.shape.kinds[node]
        visited = records.visited[node] or kind == "gate"
        selected = node == self.selected
        if selected and self.pressed_left > 0:
            fill: RGB | None = cfg.button.pressed.fill_color
        elif (selected and focused) or node == self.hover:
            fill = cfg.button.focused.fill_color
        elif kind == "gate":
            fill = flow_color(cfg, "flowchart.gate.fill_color")
        elif visited:
            fill = cfg.flowchart.node.fill_color
        else:
            fill = None
        border = cfg.flowchart.node.border_color
        on_path = node in records.path_nodes
        width = self._width(4 if on_path else 2)
        border_color = flow_color(cfg, "flowchart.path.line_color") if on_path else border
        image = self.page.theme.frames.get(f"flowchart.{kind}") if visited else None
        surface = canvas.surface
        assert surface is not None
        points = self._shape_points(kind, box)
        px_points = [canvas.px(x, y) for x, y in points] if points is not None else None
        rect = canvas.rect_to_px((box.x, box.y, box.w, box.h))
        radius = round(self._radius(kind, box) * canvas.scale)
        if image is not None:                       # replaces the fill and border
            p.shape(box, FrameSpec(fill or border, 1.0, slice_width=FRAME_SLICE), image=image)
        elif fill is not None:
            if px_points is not None:
                pygame.draw.polygon(surface, fill, px_points)
            else:
                pygame.draw.rect(surface, fill, rect, border_radius=radius)
        line_px = max(1, round(width * canvas.scale))
        if not visited:
            outline = points if points is not None else \
                [(box.x, box.y), (box.right, box.y), (box.right, box.bottom), (box.x, box.bottom)]
            self._dashed_outline(canvas, outline, border, width)
        elif image is None or on_path:
            if px_points is not None:
                pygame.draw.polygon(surface, border_color, px_points, line_px)
            else:
                pygame.draw.rect(surface, border_color, rect, line_px, border_radius=radius)
            if kind == "chapter" and image is None:
                inner = rect.inflate(-2 * round(5 * canvas.scale * self.k * self.geometry.scale),
                                     -2 * round(5 * canvas.scale * self.k * self.geometry.scale))
                pygame.draw.rect(surface, border, inner, max(1, round(2 * canvas.scale)))
        if not normal:
            return
        if kind == "gate":
            self._draw_gate(canvas, node, box)
            return
        g = self.geometry
        text = _text(records, node, self.page.words.get)
        color = flow_color(cfg, "flowchart.node.text_color")
        if text is None:
            text, color = self.page.words.get("flowchart_unknown"), \
                flow_color(cfg, "flowchart.unknown.text_color")
        width_t = max(1.0, box.w - 2 * TITLE_INSET * g.scale)
        lines = self._title_lines(node, text, width_t, g.t)
        top = box.y + box.h / 2 - len(lines) * g.p_t / 2
        font = self._font(g.t)
        for i, line in enumerate(lines):
            canvas.draw_text(line, font, color, (box.x + box.w / 2, top + (i + 0.5) * g.p_t),
                             anchor="center")

    def _dashed_outline(self, canvas: "Canvas", points: Sequence[tuple[float, float]],
                        color: RGB, width: float) -> None:
        """A closed outline dashed 8 / 6 (canvas units) along each side."""
        surface = canvas.surface
        assert surface is not None
        px_w = max(1, round(width * canvas.scale))
        on, off = DASH
        for a, b in zip(points, [*points[1:], points[0]]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length <= 0:
                continue
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            at = 0.0
            while at < length:
                end = min(at + on, length)
                p0 = canvas.px(a[0] + ux * at, a[1] + uy * at)
                p1 = canvas.px(a[0] + ux * end, a[1] + uy * end)
                pygame.draw.line(surface, color, p0, p1, px_w)
                at += on + off

    def _draw_gate(self, canvas: "Canvas", node: int, box: Box) -> None:
        """Padlock and route title, then up to 3 ``until`` lines (box, tick when reached,
        title or ``???``); over 3, the third line reads "+N" (the cell has 4 lines)."""
        records, g = self.records, self.geometry
        assert records is not None and g is not None
        cfg = self.page.cfg
        word = self.page.words.get
        view = next((v for v in records.gates if v.node == node), None)
        s = g.scale
        surface = canvas.surface
        assert surface is not None
        font = self._font(g.t)
        text_color = flow_color(cfg, "flowchart.node.text_color")
        unknown_color = flow_color(cfg, "flowchart.unknown.text_color")
        border = cfg.flowchart.node.border_color
        x = box.x + 16 * s
        width = box.w - 32 * s - (LOCK[0] + 8) * s
        y = box.y + 8 * s
        # The padlock: a shackle over a body.
        lw, lh = LOCK[0] * s, LOCK[1] * s
        ly = y + (g.p_t - lh) / 2
        canvas.fill(border, (x, ly + lh * 0.45, lw, lh * 0.55))
        shackle = canvas.rect_to_px((x + lw * 0.2, ly, lw * 0.6, lh * 0.6))
        pygame.draw.rect(surface, border, shackle, max(1, round(2 * s * canvas.scale)),
                         border_radius=max(1, round(lw * 0.3 * canvas.scale)))
        title = show_text(view.title, var=word("flowchart_var")) \
            if view is not None and view.title is not None else None
        line = self._fit(("gate", node, g.t), title if title is not None else word(
            "flowchart_unknown"), width, g.t, self.page.measure)
        canvas.draw_text(line, font, text_color if title is not None else unknown_color,
                         (x + lw + 8 * s, y + g.p_t / 2), anchor="midleft")
        rows = view.rows if view is not None else ()
        # The cell holds 3 lines under the title (03): over 3 endings, line 4 reads "+N".
        shown = rows if len(rows) <= GATE_LINES else rows[:GATE_LINES - 1]
        for i, row in enumerate(shown):
            ry = y + (i + 1) * g.p_t
            bs = GATE_BOX * s
            by = ry + (g.p_t - bs) / 2
            rect = canvas.rect_to_px((x, by, bs, bs))
            pygame.draw.rect(surface, border, rect, max(1, round(2 * s * canvas.scale)))
            if row.reached:
                tick = [canvas.px(x + bs * 0.2, by + bs * 0.5), canvas.px(x + bs * 0.42,
                                                                          by + bs * 0.75),
                        canvas.px(x + bs * 0.82, by + bs * 0.25)]
                pygame.draw.lines(surface, border, False, tick, max(1, round(2 * s)))
            text = show_text(row.text, var=word("flowchart_var")) if row.text is not None \
                else None
            label = self._fit(("until", node, i, g.t), text if text is not None else word(
                "flowchart_unknown"), box.w - 32 * s - bs - 8 * s, g.t, self.page.measure)
            canvas.draw_text(label, font, text_color if text is not None else unknown_color,
                             (x + bs + 8 * s, ry + g.p_t / 2), anchor="midleft")
        if len(rows) > GATE_LINES:
            canvas.draw_text(f"+{len(rows) - len(shown)}", font, text_color,
                             (x, y + GATE_LINES * g.p_t + g.p_t / 2), anchor="midleft")

    def _draw_ring(self, p: "Painter", node: int, focused: bool) -> None:
        """Selected: a ring 6 outside the cell, radius 12, 4 wide with F10's marker 8 left of
        it when focused, else 2 wide."""
        box = self.cell_box(node)
        assert box is not None
        canvas = p.canvas
        cfg = self.page.cfg
        surface = canvas.surface
        assert surface is not None
        ring = Box(box.x - RING_GAP, box.y - RING_GAP, box.w + 2 * RING_GAP,
                   box.h + 2 * RING_GAP)
        width = 4 if focused else 2
        rect = canvas.rect_to_px((ring.x, ring.y, ring.w, ring.h))
        pygame.draw.rect(surface, cfg.button.focused.border_color, rect,
                         max(1, round(width * canvas.scale)),
                         border_radius=round(RING_RADIUS * canvas.scale))
        if focused:
            mw, mh = MARKER
            p.triangle(Box(ring.x - MARKER_GAP - mw, ring.y + ring.h / 2 - mh / 2, mw, mh),
                       cfg.button.marker.fill_color)

    def _draw_here(self, canvas: "Canvas", node: int) -> None:
        """The "You are here" tab: bottom-left at (node left + 12, node top), t + 10 tall, top
        corners radius 8; a 10 × 10 diamond 8 in, 6, the word, 10 (full size in Overview)."""
        g = self.geometry
        assert g is not None
        cfg = self.page.cfg
        box = self.cell_box(node)
        assert box is not None
        s = g.scale
        text = self.page.words.get("flowchart_here")
        width = (8 + DIAMOND + 6 + 10) * s + self.page.measure(text, g.t)
        tab = Box(box.x + 12 * s, box.y - g.tag_h, width, g.tag_h)
        surface = canvas.surface
        assert surface is not None
        fill = flow_color(cfg, "flowchart.here.fill_color")
        r = round(8 * canvas.scale)
        pygame.draw.rect(surface, fill, canvas.rect_to_px((tab.x, tab.y, tab.w, tab.h)),
                         border_top_left_radius=r, border_top_right_radius=r)
        color = flow_color(cfg, "flowchart.here.text_color")
        d = DIAMOND * s
        cx, cy = tab.x + 8 * s + d / 2, tab.y + tab.h / 2
        pygame.draw.polygon(surface, color, [canvas.px(cx, cy - d / 2), canvas.px(cx + d / 2, cy),
                                             canvas.px(cx, cy + d / 2), canvas.px(cx - d / 2, cy)])
        canvas.draw_text(text, self._font(g.t), color, (tab.x + (8 + DIAMOND + 6) * s, cy),
                         anchor="midleft")

    def _draw_limit(self, canvas: "Canvas") -> None:
        if self.limit is None:
            return
        d, age = self.limit
        alpha = 1.0 if age < LIMIT_HOLD else max(0.0, 1.0 - (age - LIMIT_HOLD) / LIMIT_FADE)
        if alpha <= 0:
            return
        vp = self.box
        color = self.page.cfg.button.marker.fill_color
        rect = {Nav.UP: (vp.x, vp.y, vp.w, LIMIT_BAR),
                Nav.DOWN: (vp.x, vp.bottom - LIMIT_BAR, vp.w, LIMIT_BAR),
                Nav.RIGHT: (vp.right - LIMIT_BAR, vp.y, LIMIT_BAR, vp.h),
                Nav.LEFT: (vp.x, vp.y, LIMIT_BAR, vp.h)}[d]
        canvas.fill((*color, round(255 * alpha)) if alpha < 1 else color, rect)

    def _draw_overlays(self, p: "Painter") -> None:
        """The counts tag, the toolbar, and the scrollbars (never focus stops)."""
        records, g = self.records, self.geometry
        assert records is not None and g is not None
        canvas = p.canvas
        cfg = self.page.cfg
        word = self.page.words.get
        ev, en, nv, nn = records.counts
        text = f"{word('flowchart_endings')} {ev} / {en}{SEPARATOR}" \
               f"{word('flowchart_nodes')} {nv} / {nn}"
        vp = self.box
        badge = cfg.save.badge
        if self.zoom == "normal":                       # Overview: no text but the here tab
            tag = Box(vp.x + OVERLAY_INSET, vp.y + OVERLAY_INSET,
                      self.page.measure(text, g.t) + TAG_PAD, g.tag_h)
            p.shape(tag, FrameSpec(badge.fill_color, badge.fill_opacity, corner_radius=4))
            canvas.draw_text(text, self._font(g.t), badge.text_color, tag.center,
                             anchor="center")
        surface = canvas.surface
        assert surface is not None
        for index, box in enumerate(g.toolbar):
            enabled = self.tool_enabled(index)
            pressed = self.tool_pressed is not None and self.tool_pressed[0] == index
            state = "disabled" if not enabled else "pressed" if pressed else "normal"
            p.widget_frame(box, "button", Look(state), marker=False)
            color = cfg.button.text_color if enabled else cfg.button.disabled.text_color
            cx, cy = box.center
            arm = box.w * 0.3
            bar = max(2.0, 3 * g.scale)
            canvas.fill(color, (cx - arm, cy - bar / 2, 2 * arm, bar))
            if index == 1:
                canvas.fill(color, (cx - bar / 2, cy - arm, bar, 2 * arm))
            elif index == 2:
                canvas.fill(cfg.button.fill_color, (cx - arm, cy - bar / 2, 2 * arm, bar))
                pygame.draw.circle(surface, color, canvas.px(cx, cy),
                                   max(2, round(arm * canvas.scale)),
                                   max(1, round(bar * canvas.scale)))
                pygame.draw.circle(surface, color, canvas.px(cx, cy),
                                   max(1, round(bar * canvas.scale)))
        h_bar, v_bar = self._scrollbars()
        style = p.style("list", "normal")
        for bar, axis in ((h_bar, 0), (v_bar, 1)):
            if bar is None:
                continue
            lane, thumb = bar
            if axis == 0:
                y = lane.y + (lane.h - SCROLL_TRACK) / 2
                track, knob = Box(lane.x, y, lane.w, SCROLL_TRACK), \
                    Box(thumb.x, y, thumb.w, SCROLL_TRACK)
            else:
                x = lane.x + (lane.w - SCROLL_TRACK) / 2
                track, knob = Box(x, lane.y, SCROLL_TRACK, lane.h), \
                    Box(x, thumb.y, SCROLL_TRACK, thumb.h)
            p.shape(track, FrameSpec(style.color("scrollbar_track"), 1.0,
                                     corner_radius=SCROLL_RADIUS))
            p.shape(knob, FrameSpec(style.color("scrollbar"), 1.0, corner_radius=SCROLL_RADIUS))


# --- The panel -----------------------------------------------------------------------------------

class DetailPanel:
    """The detail panel (03 "Detail panel"): rows in an F13 variable-row ``ScrollList``
    (never a focus stop; drawn here) and the Jump button (drawn here; a click jumps)."""

    def __init__(self, page: "FlowchartPage") -> None:
        self.page = page
        self.model = PanelModel(None, (), "absent")
        self.lines: list[tuple[str, ...]] = []
        self.heights: list[float] = []
        self.geometry: PageGeometry | None = None
        self.body = ScrollList(lambda: self._rows, lambda _i: None,
                               heights=lambda i: self.heights[i],
                               pitch=lambda: self.geometry.p_b if self.geometry else 1,
                               focusable=False)
        self._rows: list[ListRow] = []
        self.jump_button = Button(lambda: page.words.get("flowchart_jump"), lambda: None,
                                  enabled=lambda: self.model.jump == "enabled", focusable=False)
        self.jump_pressed = False
        self.jump_left = 0.0

    def place(self, geometry: PageGeometry) -> None:
        self.geometry = geometry
        self.body.box = geometry.body
        self.jump_button.box = geometry.jump

    def show(self, model: PanelModel) -> None:
        """Lay out ``model``'s rows (scroll back to the top when the node changed)."""
        g = self.geometry
        assert g is not None
        changed = model.node != self.model.node
        self.model = model
        measure, heading = self.page.measure, self.page.heading_measure
        width = PANEL_BODY_W - SCROLLBAR_LANE
        size_t = g.t
        size_h = scaled(self.page.cfg.panel.heading.text_size, g.scale)
        size_b = scaled(self.page.cfg.panel.text_size, g.scale)
        self.lines, self.heights = [], []
        for i, row in enumerate(model.rows):
            if row.kind == "meta":
                lines = (cut_to_width(row.text, width, size_t, measure),)
                height = g.p_t + ROW_GAP
            elif row.kind in ("title", "heading"):
                lines = tuple(wrap_text(row.text, width, size_h, heading) or [row.text])
                height = len(lines) * g.p_h + (ROW_GAP if row.kind == "title" else 0)
            else:
                inset = CHOICE_TEXT_X if row.kind in ("choice", "gate") else 0
                if row.kind == "gate":
                    inset = GATE_BOX + 8
                lines = tuple(wrap_text(row.text, width - inset, size_b, measure) or [row.text])
                height = len(lines) * g.p_b
            self.lines.append(lines)
            self.heights.append(float(height))
        self._rows = [ListRow("") for _ in model.rows]
        self.body.heights_changed()
        if changed:
            self.body.scroll = 0.0
        self.body._clamp_scroll()

    def page_key(self, down: bool) -> bool:
        """Page Up / Down, the shoulders: the body by view − p_b; nothing when it fits."""
        body = self.body
        if not body.overflows():
            return False
        body.scroll += body.page_step() if down else -body.page_step()
        body._clamp_scroll()
        return True

    def wheel(self, notches: int) -> bool:
        g = self.geometry
        body = self.body
        if g is None or not body.overflows():
            return False
        body.scroll -= notches * 3 * g.p_b
        body._clamp_scroll()
        return True

    def update(self, dt: float) -> None:
        self.jump_left = max(0.0, self.jump_left - dt)

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        g = self.geometry
        if g is None:
            return
        cfg = self.page.cfg
        p.panel(g.panel)
        body = self.body
        theme = self.page.theme
        size_t = g.t
        size_h = scaled(cfg.panel.heading.text_size, g.scale)
        size_b = scaled(cfg.panel.text_size, g.scale)
        unknown = flow_color(cfg, "flowchart.unknown.text_color")
        with clipped(p, body.box):
            for index in body.visible_range():
                row = self.model.rows[index]
                box = body.row_box(index)
                lines = self.lines[index]
                if row.kind == "meta":
                    canvas.draw_text(lines[0], theme.font(size_t), cfg.panel.text_color,
                                     (box.x, box.y + g.p_t / 2), anchor="midleft")
                    continue
                if row.kind in ("title", "heading"):
                    color = unknown if row.unknown else cfg.panel.heading.text_color
                    font = theme.font(size_h, bold=True)
                    for i, line in enumerate(lines):
                        canvas.draw_text(line, font, color, (box.x, box.y + (i + 0.5) * g.p_h),
                                         anchor="midleft")
                    continue
                x, color = box.x, cfg.panel.text_color
                font = theme.font(size_b)
                if row.kind == "reason":
                    font = theme.font(size_b, italic=True)
                    color = cfg.button.disabled.text_color
                elif row.kind == "choice":
                    bar = Box(box.x, box.y + 6, CHOICE_BAR, box.h - 12)
                    if row.mark:
                        p.rect(bar, cfg.button.marker.fill_color)
                        color = cfg.panel.heading.text_color
                    else:
                        surface = canvas.surface
                        assert surface is not None
                        pygame.draw.rect(surface, cfg.button.marker.fill_color,
                                         canvas.rect_to_px((bar.x, bar.y, bar.w, bar.h)),
                                         max(1, round(canvas.scale)))
                        color = unknown
                    x += CHOICE_TEXT_X
                elif row.kind == "gate":
                    surface = canvas.surface
                    assert surface is not None
                    bs = GATE_BOX
                    by = box.y + (g.p_b - bs) / 2
                    border = cfg.flowchart.node.border_color
                    pygame.draw.rect(surface, border, canvas.rect_to_px((box.x, by, bs, bs)),
                                     max(1, round(2 * canvas.scale)))
                    if row.mark:
                        pygame.draw.lines(surface, border, False, [
                            canvas.px(box.x + bs * 0.2, by + bs * 0.5),
                            canvas.px(box.x + bs * 0.42, by + bs * 0.75),
                            canvas.px(box.x + bs * 0.82, by + bs * 0.25)],
                            max(1, round(2 * canvas.scale)))
                    color = unknown if row.unknown else cfg.panel.text_color
                    x += GATE_BOX + 8
                elif row.unknown:
                    color = unknown
                for i, line in enumerate(lines):
                    canvas.draw_text(line, font, color, (x, box.y + (i + 0.5) * g.p_b),
                                     anchor="midleft")
            lane, thumb = body.lane_box(), body.thumb_box()
            if lane is not None and thumb is not None:
                style = p.style("list", "normal")
                x = lane.x + (lane.w - SCROLL_TRACK) / 2
                p.shape(Box(x, lane.y, SCROLL_TRACK, lane.h),
                        FrameSpec(style.color("scrollbar_track"), 1.0,
                                  corner_radius=SCROLL_RADIUS))
                p.shape(Box(x, thumb.y, SCROLL_TRACK, thumb.h),
                        FrameSpec(style.color("scrollbar"), 1.0, corner_radius=SCROLL_RADIUS))
        if self.model.jump == "absent":
            return                                       # its area stays empty
        state = "disabled" if self.model.jump == "disabled" else \
            "pressed" if (self.jump_pressed or self.jump_left > 0) else "normal"
        self.jump_button.draw(p, Look(state))


# --- The page ------------------------------------------------------------------------------------

class FlowchartPage(MenuPageBase):
    """The ``flowchart`` page (``MenuPage``; module docstring). ``from_title``: opened from the
    title (no "You are here"; the selection opens on the most recent node)."""

    heading = HEADING
    nav_extras = frozenset({"shoulders"})

    def __init__(self, port: FlowPort, *, from_title: bool = False) -> None:
        self.port = port
        self.from_title = from_title
        self.host: "PageHost | None" = None
        self.chart = ChartView(self)
        self.panel = DetailPanel(self)
        self.records: ChartRecords | None = None
        self.layout: ChartLayout | None = None
        self.metrics: ChartMetrics | None = None
        self.geometry: PageGeometry | None = None
        self._opened = False
        self._signature: tuple | None = None

    # -- what the page draws with --

    @property
    def shell(self):
        assert self.host is not None
        return self.host.shell

    @property
    def theme(self):
        return self.shell.theme

    @property
    def cfg(self) -> "ThemeConfig":
        return self.shell.theme.cfg

    @property
    def words(self):
        return self.shell.words

    def reduce_motion(self) -> bool:
        return bool(getattr(self.shell, "reduce_motion", False))

    def keyed(self, chart: ChartView) -> bool:
        """The chart is drawn focused: focused by keys, or its selection clicked."""
        scope = self.host.scope if self.host is not None else None
        return scope is not None and (scope.source is InputKind.KEYS or chart.clicked)

    def input_kind(self) -> InputKind:
        scope = self.host.scope if self.host is not None else None
        return scope.source if scope is not None and scope.source is not None \
            else InputKind.KEYS

    # -- building --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        cfg = self.cfg
        scale = host.painter.text_scale()
        self.geometry = page_geometry(cfg, scale, body)
        font = self.theme.font(cfg.flowchart.text_size)
        self.measure = measure_with(self.shell.assets, font)
        self.heading_measure = measure_with(self.shell.assets, self.theme.font(
            cfg.panel.heading.text_size, bold=True))
        if self.records is None:
            self.records = self.port.records()
        metrics = ChartMetrics(scale=scale, node_width=cfg.flowchart.node.width,
                               text_size=cfg.flowchart.text_size)
        if metrics != self.metrics or self.layout is None:
            self.metrics = metrics
            self.layout = self.port.layout(metrics).run()   # the remainder, at once (A7)
        chart = self.chart
        chart.setup(self.records, self.layout, self.geometry)
        self.panel.place(self.geometry)
        if chart.selected is None or self.layout.cell(chart.selected) is None:
            chart.selected = self._opening_node()
            chart.zoom = "normal"
        if chart.selected is not None:
            chart.centre_on(chart.selected)
        else:
            chart.set_view(0.0, 0.0)
        self._signature = None
        self.selection_changed()
        return [FocusGroup([chart])]

    def _opening_node(self) -> int | None:
        """In game "You are here", from the title the most recent node; else the first in
        reading order (07 §3.5 G4)."""
        records, layout = self.records, self.layout
        assert records is not None and layout is not None
        first = records.here if self.port.in_game else records.recent
        if first is not None and layout.cell(first) is not None:
            return first
        return layout.reading[0] if layout.reading else None

    # -- the panel --

    def selection_changed(self) -> None:
        """The panel follows the selection in the same frame."""
        if self.records is None or self.geometry is None:
            return
        node = self.chart.selected
        model = panel_model(self.records, node, self.port, self.words.get)
        self._signature = (node, model.jump, model.rows)
        self.panel.show(model)

    def jump_state(self) -> JumpState:
        return self.panel.model.jump

    def jump(self, by: InputKind) -> None:
        model = self.panel.model
        if model.jump == "enabled" and model.node_id is not None:
            self.panel.jump_left = PRESS_S
            self.port.jump(model.node_id, by)

    # -- MenuPage --

    def update(self, dt: float) -> None:
        host = self.host
        if host is None:
            return
        scope = host.scope
        if not self._opened:
            self._opened = True
            # Opened by key or button: the node has focus (F11 C1); by mouse, selected only.
            if scope.focused is not None and scope.focused is not self.chart and \
                    scope.source is InputKind.KEYS and scope.visible and \
                    scope.can_focus(self.chart):
                scope.focus(self.chart, InputKind.KEYS, sound=False)
        if scope.focused is not self.chart:
            self.chart.clicked = False
        self.chart.update(dt)
        self.panel.update(dt)
        if self.records is not None and self.chart.selected is not None:
            model = panel_model(self.records, self.chart.selected, self.port, self.words.get)
            if (model.node, model.jump, model.rows) != self._signature:
                self._signature = (model.node, model.jump, model.rows)
                self.panel.show(model)                  # a refused jump changed its reason

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        self.panel.draw(canvas, p)

    def on_nav(self, d: Nav) -> bool:
        if d in (Nav.PAGE_UP, Nav.PAGE_DOWN):
            return self.panel.page_key(d is Nav.PAGE_DOWN)
        return False

    def on_mouse(self, kind: str, pos: tuple[float, float], *, notches: int = 0) -> bool:
        """The panel: the wheel scrolls its body; a click on Jump jumps."""
        g = self.geometry
        if g is None:
            return False
        if kind == "wheel":
            return g.panel.contains(pos) and self.panel.wheel(notches)
        if kind == "down":
            if g.jump.contains(pos) and self.jump_state() == "enabled":
                self.panel.jump_pressed = True
                return True
            return False
        if kind == "up":
            pressed, self.panel.jump_pressed = self.panel.jump_pressed, False
            if pressed and g.jump.contains(pos):
                self.jump(InputKind.MOUSE)
            return pressed
        return False

    def on_event(self, event: "UiEvent") -> bool:
        """Inputs F10's reader doesn't map (module docstring). True: used."""
        raw = event.raw
        kind = raw.type
        chart = self.chart
        if chart.layout is None:
            return False
        if kind == pygame.KEYDOWN:
            mods = getattr(raw, "mod", 0)
            if mods & (pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META):
                return False
            if raw.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                chart.set_zoom("normal")
                return True
            if raw.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                chart.set_zoom("overview")
                return True
            if raw.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                return self._quiet_activate()
            return False
        if kind == pygame.CONTROLLERBUTTONDOWN:
            if raw.button == pygame.CONTROLLER_BUTTON_Y:          # north: toggle the zoom
                chart.set_zoom("overview" if chart.zoom == "normal" else "normal")
                return True
            if raw.button == pygame.CONTROLLER_BUTTON_X:          # west: go to
                chart.go_to()
                return True
            if raw.button == pygame.CONTROLLER_BUTTON_A:
                return self._quiet_activate()
            return False
        if kind == pygame.CONTROLLERAXISMOTION:
            axis = {pygame.CONTROLLER_AXIS_RIGHTX: 0, pygame.CONTROLLER_AXIS_RIGHTY: 1}.get(
                raw.axis)
            if axis is None:
                return False
            chart.stick[axis] = max(-1.0, min(1.0, raw.value / STICK_MAX))
            return True
        if kind == pygame.MOUSEMOTION and event.canvas_pos is not None:
            pos = event.canvas_pos
            chart.hover = chart.node_at(pos) if event.in_canvas else None
            return False
        if kind == pygame.MOUSEWHEEL:
            pos = event.canvas_pos if event.in_canvas else None
            if pos is None:
                return False
            return chart.wheel(pos, int(getattr(raw, "x", 0)), int(getattr(raw, "y", 0)),
                               pygame.key.get_mods())
        return False

    def _quiet_activate(self) -> bool:
        """Activate on the focused chart with Jump not enabled: nothing, and no sound (03)."""
        scope = self.host.scope if self.host is not None else None
        return (scope is not None and scope.focused is self.chart and scope.visible
                and self.jump_state() != "enabled")

    def default_widget(self) -> "Widget | None":
        return self.chart


__all__ = ["ChartView", "DetailPanel", "FOLLOWS", "FlowPort", "FlowchartPage", "HEADING",
           "KIND_WORDS", "PageGeometry", "PanelModel", "PanelRow", "flow_color",
           "page_geometry", "panel_model"]
