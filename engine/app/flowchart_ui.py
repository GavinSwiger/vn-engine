"""``install_flowchart_page``: the Flowchart page wired into one windowed launch (F20
``04-technical.md`` §5, §7.3, §7.7, §7.9; ``03-ui.md`` "Entries", "Jump"; ``06`` AC-F20-30,
56, 64; ``07`` A7, A10, I-14).

Why this module exists: the page (``ui/builtin/flowchart_page.py``) reads the story only through
a ``FlowPort`` and ``ui`` never imports ``app``, while ``App.flow`` (``FlowService``, F20 s6)
holds the node states and makes the jumps. This module joins them, once per windowed launch,
right after ``install_flowchart`` (none without ``App.flow``: no graph, or headless):

- ``FlowPages`` keeps one ``ChartRecords`` (``chart_records`` over the live interpreter's
  graph, store, chapter, ending, and route indexes, and ``[flowchart]``), keyed on (in game,
  ``unlocks_gen``, ``reset_count``, ``recorder.gen``, the path) as 04 §7.3 says, and one
  ``LayoutJob`` per (records, metrics), at most ``LAYOUTS_KEPT``. ``update(now)`` (App's F20
  slot, after ``FlowService.update``) prewarms the layout for the page that would open, in
  slices of at most ``FLOW_STEP_S`` (2 ms), only while the top screen is a menu (07 A7); a page
  open finishes any remainder at once (``LayoutJob.run``).
- ``AppFlowPort`` is one page open's port: masked records, the graph's node ids, and
  ``FlowService.can_jump`` / ``reason``. ``jump`` in game asks F10's confirm first
  (``flowchart_confirm_autosave`` when ``FlowService.jump_autosaves()``, else
  ``flowchart_confirm``; No focused; No or Back returns focus to the node), then
  ``FlowService.jump(origin="game")``; from the title it jumps at once.
- Two menu entries (§7.9; not ``OPT_IN``): ``game`` ``flowchart`` while the graph has at least
  2 nodes and one is shown; ``title`` ``flowchart`` with ``[flowchart] jump`` and some shown,
  visited node without ``no jump`` that ``can_jump`` (index and memory states only: no file
  is read, TR-F20-09).

Not built here: F10's "Loading" indicator for a node read over 1 MiB taking over 1,000 ms
(``FlowService.jump`` reads synchronously, one step of F11's load class).

This module imports ``engine.script`` only through ``runtime.flowchart`` (07 I-1).
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from engine.persist import limits
from engine.runtime.flowchart import ChartRecords, FlowOptions, chart_records
from engine.ui.builtin.flowchart_page import HEADING, FlowchartPage
from engine.ui.flowlayout import ChartMetrics, LayoutJob
from engine.ui.menu_screen import MenuScreen
from engine.ui.menus import MenuEntry
from engine.ui.nav import InputKind

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.app.flowchart import FlowService
    from engine.runtime.interpreter import Interpreter

LAYOUTS_KEPT: Final = 4                 # (records, metrics) layouts cached


class FlowPages:
    """The records and layout cache of one launch, and the prewarm (module docstring)."""

    def __init__(self, app: "App", interp: "Interpreter", service: "FlowService",
                 options: FlowOptions, *, clock: Callable[[], float]) -> None:
        self.app = app
        self._interp = interp
        self.service = service
        self.options = options
        self.clock = clock
        self._records: dict[bool, tuple[tuple, ChartRecords]] = {}
        self._layouts: OrderedDict[tuple, LayoutJob] = OrderedDict()
        self.built = 0                   # chart_records calls (tests)
        self.prewarm_steps = 0

    @property
    def interp(self) -> "Interpreter":
        story = getattr(self.app, "story", None)
        live = getattr(story, "interp", None)
        return live if live is not None else self._interp

    def _key(self, in_game: bool) -> tuple:
        interp = self.interp
        store = interp.persistent
        rec = interp.flowchart
        path = interp.flow.path if in_game else None
        return (in_game, store.unlocks_gen, store.reset_count, getattr(rec, "gen", 0), path,
                id(getattr(rec, "graph", None)))

    def records(self, in_game: bool) -> ChartRecords | None:
        """The masked records for a page opened in game (with this playthrough's path) or
        from the title; None without a graph."""
        interp = self.interp
        graph = getattr(interp.flowchart, "graph", None)
        if graph is None:
            return None
        key = self._key(in_game)
        found = self._records.get(in_game)
        if found is not None and found[0] == key:
            return found[1]
        records = chart_records(graph, interp.persistent, interp.chapters, interp.endings,
                                interp.routes, self.options,
                                interp.flow.path if in_game else None)
        self.built += 1
        self._records[in_game] = (key, records)
        return records

    def job(self, records: ChartRecords, metrics: ChartMetrics) -> LayoutJob:
        """The cached ``LayoutJob`` for ``records`` at ``metrics`` (new when none)."""
        key = (id(records), metrics)
        found = self._layouts.get(key)
        if found is not None and found.records is records:
            self._layouts.move_to_end(key)
            return found
        job = LayoutJob(records, metrics)
        self._layouts[key] = job
        while len(self._layouts) > LAYOUTS_KEPT:
            self._layouts.popitem(last=False)
        return job

    def metrics(self) -> ChartMetrics | None:
        shell = getattr(self.app, "shell", None)
        if shell is None:
            return None
        cfg = shell.theme.cfg.flowchart
        return ChartMetrics(scale=shell.painter.text_scale(), node_width=cfg.node.width,
                            text_size=cfg.text_size)

    def update(self, now: float) -> None:
        """07 A7: while a menu is on top, the layout of the page that would open is stepped in
        one ``FLOW_STEP_S`` slice."""
        shell = getattr(self.app, "shell", None)
        screens = getattr(self.app, "screens", None)
        top = getattr(screens, "top", None)
        if shell is None or not isinstance(top, MenuScreen):
            return
        from engine.ui.shell import Mode
        records = self.records(shell.mode is Mode.GAME)
        metrics = self.metrics()
        if records is None or metrics is None:
            return
        job = self.job(records, metrics)
        if not job.done:
            clock = self.clock
            job.step(clock() + limits.FLOW_STEP_S, clock)
            self.prewarm_steps += 1

    # -- entries --

    def game_visible(self) -> bool:
        records = self.records(True)
        if records is None or not self.options.enabled:
            return False
        graph = self.interp.flowchart.graph
        nodes = sum(1 for n in graph.nodes if n.kind != "gate")
        return nodes >= 2 and any(records.shape.kinds[i] != "gate"
                                  for i in records.shape.nodes)

    def title_visible(self) -> bool:
        if not (self.options.enabled and self.options.jump):
            return False
        records = self.records(False)
        if records is None:
            return False
        graph = self.interp.flowchart.graph
        shape = records.shape
        return any(shape.kinds[i] not in ("gate", "start", "ending") and records.visited[i]
                   and not shape.no_jump[i] and self.service.can_jump(graph.nodes[i].id)
                   for i in shape.nodes)

    def port(self, *, in_game: bool) -> "AppFlowPort":
        return AppFlowPort(self, in_game=in_game)


class AppFlowPort:
    """One page open's ``FlowPort`` (module docstring)."""

    def __init__(self, pages: FlowPages, *, in_game: bool) -> None:
        self.pages = pages
        self.in_game = in_game
        self.jump_enabled = pages.options.jump
        self._records: ChartRecords | None = None

    def records(self) -> ChartRecords:
        records = self.pages.records(self.in_game)
        assert records is not None, "the flowchart page opened without a graph"
        self._records = records
        return records

    def node_id(self, node: int) -> str:
        return self.pages.interp.flowchart.graph.nodes[node].id

    def can_jump(self, node_id: str) -> bool:
        return self.pages.service.can_jump(node_id)

    def reason(self, node_id: str) -> str | None:
        return self.pages.service.reason(node_id)

    def layout(self, metrics: ChartMetrics) -> LayoutJob:
        records = self._records if self._records is not None else self.records()
        return self.pages.job(records, metrics)

    def jump(self, node_id: str, by: InputKind) -> None:
        """In game: F10's confirm first (No focused), then the service's jump; from the title
        at once (03 "Jump")."""
        service = self.pages.service
        if not self.in_game:
            service.jump(node_id, origin="title", by=by)
            return
        shell = self.pages.app.shell
        key = "flowchart_confirm_autosave" if service.jump_autosaves() else "flowchart_confirm"
        shell.confirm(shell.words.get(key),
                      lambda: service.jump(node_id, origin="game", by=by), by=by)


def install_flowchart_page(app: "App", interp: "Interpreter") -> FlowPages | None:
    """After ``install_flowchart``: the page's cache and the two entries (module docstring).
    None (and no entry) without ``App.flow`` or a shell."""
    service = getattr(app, "flow", None)
    shell = getattr(app, "shell", None)
    if service is None or shell is None:
        app.flow_pages = None
        return None
    options = FlowOptions.from_config(app.config.flowchart)
    clock = getattr(app, "clock", None) or time.perf_counter
    pages = FlowPages(app, interp, service, options, clock=clock)
    shell.menus.add("game", MenuEntry(
        HEADING, page=lambda host: FlowchartPage(pages.port(in_game=True)),
        visible=pages.game_visible))
    shell.menus.add("title", MenuEntry(
        HEADING, page=lambda host: FlowchartPage(pages.port(in_game=False), from_title=True),
        visible=pages.title_visible))
    app.flow_pages = pages
    return pages


__all__ = ["AppFlowPort", "FlowPages", "LAYOUTS_KEPT", "install_flowchart_page"]
