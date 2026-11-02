"""``NvlPresenter``: the NVL page on screen, owned by ``TextboxScreen`` (F17
``04-technical.md`` §5.4, §7.2, §7.3; ``07`` I-5, I-9; ``06`` AC-F17-13, 17, 18).

Why this module exists: the runtime keeps the page record (``GameState.nvl``) but sends it
only on a restore; live, ``NvlPage`` carries no lines and the presentation appends each
``Say`` it receives. The presenter holds those **entries** (at most ``NVL_PAGE_MAX``, built
by the runtime's own ``line_of``, I-5) and the **plan** (which entries the visible page
shows, and where), folded with ``render/nvllayout``'s ``plan_add`` on both paths, so a
restored page equals the live one (TR-F17-03).

- ``set(on, lines, m)`` is ``NvlPage``: the mode, and the entries replaced (a restore's
  record; live: none). ``plan_from`` at the metrics ``m``.
- ``arrive(cmd, m)`` is a ``Say`` in NVL: the plan is made again from every entry when the
  effective size changed (PR-F17-17); a restored line whose sid is the last entry's *is*
  that entry (a changed body replaces it, I-9), else the line is appended (the oldest drops
  past ``NVL_PAGE_MAX``) and placed with ``plan_add``. The entry becomes ``current``.
- ``settle(layout)``: the current line is drawn settled (F09's ``clear``).
- ``choice_area(fits)`` (F07's NVL area, ``04`` §7.4, ``07`` §3.2): ``(T, B)`` from
  ``CHOICE_GAP`` under the page to the text area's bottom. When the choices don't fit there,
  a **view plan** of only the last row's line (the question or the kept line; a line of
  several pages keeps its last page) replaces the page on screen (``rows``) until the next
  ``set`` or ``arrive``; it is computed from (record, choices, size) only, so a restore at
  the menu gives the same picture.
- ``settled_page(row)``: a settled row's page with glyph positions, kept while the entry and
  metrics last: the typing layout of the line that just settled (``arrive``/``settle`` hand
  it over: marks and speed take no room, so its breaks are the record's, TR-F17-02), else a
  ``LineLayout`` of the record's ``TaggedText(spans)`` (a restore, a size change). So a
  line's arrival lays out only the new line (AC-F17-34 b).

Presentation-only: nothing here reaches the runtime (PR-F17-13). Imports ``core``,
``runtime`` and ``render``.
"""

from collections.abc import Callable
from typing import Final

from engine.render.nvllayout import (NvlLook, NvlMetrics, PagePlan, Row, empty_plan, heights,
                                     line_context, nvl_metrics, plan_add, plan_from)
from engine.render.textlayout import FaceSet, LayoutContext, LineLayout, Page
from engine.runtime.commands import NvlLine, Say, TaggedText
from engine.runtime.nvl import NVL_PAGE_MAX, line_of

CHOICE_GAP: Final = 24                  # the choices start 24 under the page's last line


class NvlPresenter:
    """The mode, the entries, and the plan of the NVL page (module docstring)."""

    def __init__(self, assets: object, faces: FaceSet, look: NvlLook) -> None:
        self.assets = assets
        self.faces = faces
        self.look = look
        self.on = False
        self.entries: list[NvlLine] = []
        self.metrics: NvlMetrics = nvl_metrics(look, 1.0)
        self.plan: PagePlan = empty_plan(self.metrics)
        self.current: int | None = None       # the entry the typewriter shows
        self.view: PagePlan | None = None     # a menu's view plan, drawn instead of plan
        self._view_of: tuple[PagePlan, PagePlan] | None = None   # (plan, its view plan)
        self.version = 0                      # bumped on every change of plan or entries
        self._layouts: dict[int, tuple[NvlLine, NvlMetrics, LineLayout]] = {}

    # -- geometry --

    def metrics_at(self, text_scale: float) -> NvlMetrics:
        return nvl_metrics(self.look, text_scale)

    def ctx_for(self, line: NvlLine, m: NvlMetrics | None = None) -> LayoutContext:
        """``line``'s layout context at ``m`` (default: the plan's): a name takes a row."""
        return line_context(self.assets, self.faces, self.look,
                            self.metrics if m is None else m, bool(line.name))

    def rows(self) -> tuple[Row, ...]:
        """The rows on screen: a menu's view plan while one is set, else the page."""
        return (self.plan if self.view is None else self.view).rows

    # -- menus --

    def choice_area(self, fits: Callable[[float, float], bool]) -> tuple[float, float]:
        """F07's NVL choice area (module docstring); sets or drops the view plan."""
        m, plan = self.metrics, self.plan
        bottom = m.top + m.height
        top = m.top + plan.used + (CHOICE_GAP if plan.rows else 0)
        view = None
        if plan.rows and not fits(top, bottom):
            view = self._view_plan()
            top = m.top + view.used + CHOICE_GAP
            if view == plan:
                view = None                       # the page already is that one line
        if view != self.view:
            self.view = view
            self.version += 1
        return top, bottom

    def _view_plan(self) -> PagePlan:
        """The plan of only the page's last line, at the plan's metrics (memoized per
        plan: F07 asks again every frame while the menu is open)."""
        plan = self.plan
        memo = self._view_of
        if memo is not None and memo[0] is plan:
            return memo[1]
        m = self.metrics
        i = plan.rows[-1].entry
        line = self.entries[i]
        view = plan_add(empty_plan(m), i, heights(line, m, self.ctx_for(line, m)),
                        bool(line.name), m)
        self._view_of = (plan, view)
        return view

    # -- commands --

    def set(self, on: bool, lines: tuple[NvlLine, ...], m: NvlMetrics) -> None:
        """``NvlPage(on, lines)``: the mode and the entries (``lines`` only when ``on``)."""
        assert on or not lines, "NvlPage(False) with lines"
        self.on = bool(on)
        self.entries = list(lines[-NVL_PAGE_MAX:])
        self.current = None
        self._layouts.clear()
        self._replan(m)

    def arrive(self, cmd: Say, m: NvlMetrics, previous: LineLayout | None = None
               ) -> NvlLine:
        """A ``Say`` in NVL (module docstring); returns the current entry. ``previous`` is
        the typing layout of the line shown until now (kept for its settled row)."""
        line = line_of(cmd)
        entries = self.entries
        self.view = None
        self._keep(previous)
        if m != self.metrics:
            self._replan(m)
        if cmd.restored and entries and entries[-1].sid == cmd.sid:
            if entries[-1] != line:                # I-9: the body shown is the one kept
                entries[-1] = line
                self._layouts.pop(len(entries) - 1, None)
                self._replan(m)
        else:
            entries.append(line)
            if len(entries) > NVL_PAGE_MAX:
                self._drop_oldest()
            i = len(entries) - 1
            self.plan = plan_add(self.plan, i, heights(line, m, self.ctx_for(line, m)),
                                 bool(line.name), m)
        self.current = len(entries) - 1
        self.version += 1
        return entries[-1]

    def settle(self, layout: LineLayout | None = None) -> None:
        """The current line is drawn settled from now on (its entry stays on the page);
        ``layout`` is its typing layout."""
        if self.current is not None:
            self._keep(layout)
            self.current = None
            self.version += 1

    # -- drawing --

    def settled_page(self, row: Row) -> Page:
        """``row``'s page with positions, from its entry's record spans (``Row.page`` −1: the
        last page)."""
        line = self.entries[row.entry]
        m = self.metrics
        kept = self._layouts.get(row.entry)
        if kept is None or kept[0] is not line or kept[1] != m:
            layout = LineLayout(TaggedText(line.spans), self.ctx_for(line, m))
            kept = self._layouts[row.entry] = (line, m, layout)
        layout = kept[2]
        k = row.page if row.page >= 0 else layout.all_pages() - 1
        return layout.page(k)

    # -- internals --

    def _keep(self, layout: LineLayout | None) -> None:
        """The current entry's typing layout serves its settled row (same metrics only)."""
        i = self.current
        if layout is not None and i is not None and i < len(self.entries) \
                and layout.ctx == self.ctx_for(self.entries[i]):
            self._layouts[i] = (self.entries[i], self.metrics, layout)

    def _replan(self, m: NvlMetrics) -> None:
        self.metrics = m
        self.view = None
        self.plan = plan_from(self.entries, m, lambda line: self.ctx_for(line, m)) \
            if self.entries else empty_plan(m)
        self.version += 1

    def _drop_oldest(self) -> None:
        """Past ``NVL_PAGE_MAX``: entry 0 goes, row indices shift (a live page never shows
        it: the visible page holds at most 23 lines, 04 §7.3)."""
        del self.entries[0]
        plan = self.plan
        rows = tuple(Row(r.entry - 1, r.page, r.y) for r in plan.rows if r.entry > 0)
        self.plan = PagePlan(rows, plan.used, plan.size)
        self._layouts = {i - 1: v for i, v in self._layouts.items() if i > 0}
        if self.current is not None:
            self.current = self.current - 1 if self.current > 0 else None


__all__ = ["CHOICE_GAP", "NvlPresenter"]
