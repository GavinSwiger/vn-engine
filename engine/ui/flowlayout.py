"""The Flowchart page's grid and edge routes, without drawing (F20 ``04-technical.md`` §7.7,
§11, C5; ``03-ui.md`` "Chart grid"; ``06`` AC-F20-58; TR-F20-07, TR-F20-10).

Why this module exists: the page draws only what meets its viewport, so every cell, edge
point, and label place must be known before the first frame, without measuring any text (a
title or choice the player hasn't earned must never be sized: SEC-F20-14(a)). ``LayoutJob``
turns one page open's masked ``ChartRecords`` into a ``ChartLayout`` in caller-given slices;
``FlowService`` (s6) caches one per (records key, metrics) and prewarms it.

**Units.** Every length is an ``int`` layout unit already multiplied by F16's text scale
``s`` (``ChartMetrics.scale``): a node cell is ``W·s`` × ``84·s``. The page draws Normal at one
canvas unit per layout unit and Overview at ``0.4 / s``.

**Steps** (04 §7.7):

1. *Visible graph*: ``records.shape.nodes`` (shown nodes and gates, story order) and
   ``shape.edges`` (shown ends; open gates already contracted). An edge is *labelled* when it
   holds choices; its tag place is the widest tag (``168·s`` + 16·s), so no text is measured
   and an untaken tag (``???``) needs no other size.
2. *Cycles*: an iterative DFS from the start node, then from every unvisited node in story
   order, children in edge order; an edge into a node on the DFS stack is a **back edge**.
3. *Columns*: longest path from sources over the other (forward) edges, with two
   refinements. A node taking two or more edges, one of them a tagged edge of one column,
   moves one column right, so every hop into it comes from a dummy and no tag shares a run
   with another edge. A node the start doesn't lead to (W150's unreachable nodes) sits as far
   right as its successors allow instead of from column 0, so its edges stay short.
4. *Dummies*: a forward edge spanning ``k > 1`` columns gets ``k − 1`` dummy cells, shortest
   edges first, while the total stays ≤ ``FLOW_DUMMIES_MAX`` (read at run time); the rest are
   **detours**.
5. *Order*: DFS preorder (a dummy right after its edge's source), then 4 barycenter sweeps
   (right, left, right, left), ties by the previous position.
6. *Lanes*: per column in order, ``lane = max(previous lane + 1, lane of the first
   predecessor in story order)``: main lines run straight, later choices go below.
7. *Sizes*: a lane is as tall as its tallest cell (node ``84·s``; gate ``16·s + p_t × (1 +
   min(k, 3))`` for ``k`` until-endings); cells sit centred in their lane. A lane gap is
   ``max(42·s, t + 18)`` (the "You are here" tab, ``t + 10``, plus 8), or, when loop rows run
   in it, ``8·s`` + the rows' bands + the tab + ``4·s``. A column gap is ``24·s`` (the stub to
   the first bus track) + ``8·s`` per track beyond the first + ``32·s``, or, when it holds a
   tag, ``8·s`` + the tag + ``8·s`` (56 and 224 at 100%).
8. *Routing*. A **hop** (one column) leaves its source's right-mid, runs to the source's bus
   track in the gap, along it to the target's lane centre, and into the target's left-mid; a
   hop between equal lanes is one straight line. Dummy chains run straight through their
   columns. In each gap a source's stub must end left of every other source's track that
   enters its lane: these constraints order the tracks (greedy interval colouring in
   topological order). A gap whose constraints form a cycle (crossing hops that swap lanes)
   reroutes its latest edge as a detour, and so would a tagged hop sharing its target's run
   (step 3 prevents that), so the rules always hold. **Back edges and detours** leave at
   bottom-mid, run in a row of the lane gap below, up or down a vertical track in a column gap (left of the target for a back
   edge, left of the source for a detour), along a row of the lane gap below the target, and
   up into its bottom-mid; a back edge within one lane needs only one row. A cell that both
   sends and receives such edges (a self-loop included) sends from ``16·s`` left of its middle
   and receives ``16·s`` right of it. Rows are interval-coloured in story order; a row with a
   tag is ``t + 14`` tall, others ``8·s``.
9. *Tags*: a hop's on its first run after the bus, ``8·s`` right of the gap's last track; a
   loop's on its first row, inside the column gap left of its source. Tags lie in column gaps,
   never over a node's x range, so they never meet the "You are here" tab.
10. *Output*: ``ChartLayout`` with ``cells``, ``edges`` (indexed like ``shape.edges``),
    ``bounds``, ``reading`` (column, then lane: Tab, Home, End), and a bucket index for
    culling (``visible``).

Segments run only in column gaps, lane centres, and lane-gap rows, and meet at right angles;
two edges overlap only where they share a source or a target (TR-F20-10, tested over seeded
random graphs). Results never depend on slicing. No pygame, file, clock, or randomness; the
records types are read structurally (imported for type checking only).
"""

import heapq
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from engine.runtime.flowchart import ChartRecords

FLOW_DUMMIES_MAX = 20_000               # dummy cells per layout (04 §4); read at run time
LAYOUT_STEP_UNITS: Final = 400          # work units between yields (a slice checks its clock)
INDEX_BUCKET: Final = 512               # culling index bucket side, layout units

Rect = tuple[int, int, int, int]        # x, y, w, h
Point = tuple[int, int]


@dataclass(frozen=True, slots=True)
class ChartMetrics:
    """The page's sizes at one text scale (03 "Scale", "Chart grid"). ``scale`` is F16's
    ``s``; ``node_width`` is ``flowchart.node.width``; ``text_size`` is
    ``flowchart.text_size``. Every derived length is an ``int`` layout unit."""

    scale: float = 1.0
    node_width: int = 240
    text_size: int = 24

    def u(self, n: float) -> int:
        """``n`` layout units at this scale."""
        return round(n * self.scale)

    @property
    def t(self) -> int:
        return round(self.text_size * self.scale)

    @property
    def pitch(self) -> int:                       # p_t
        return round(1.4 * self.t)

    @property
    def cell_w(self) -> int:
        return round(self.node_width * self.scale)

    @property
    def cell_h(self) -> int:
        return self.u(84)

    @property
    def tag_h(self) -> int:                       # F11 tag, "You are here" tab: t + 10
        return self.t + 10

    @property
    def tag_w(self) -> int:                       # the widest tag: 168·s of text + 16·s
        return self.u(184)

    @property
    def lane_gap(self) -> int:
        return max(self.u(42), self.tag_h + 8)

    @property
    def bus(self) -> int:
        return self.u(24)

    @property
    def track(self) -> int:
        return self.u(8)

    @property
    def shift(self) -> int:                       # a loop port's offset from the middle
        return self.u(16)

    def gate_h(self, until: int) -> int:
        return max(self.cell_h, self.u(16) + self.pitch * (1 + min(until, 3)))

    def gap_w(self, tracks: int, tagged: bool) -> int:
        """A column gap with ``tracks`` bus/vertical tracks, holding a tag or not."""
        base = self.bus + self.track * (max(tracks, 1) - 1)
        if tagged:
            return base + self.track + self.tag_w + self.track
        return base + self.u(56) - self.bus


@dataclass(frozen=True, slots=True)
class LaidCell:
    """One shown node or gate: its graph node index, rectangle, column, and lane."""

    node: int
    rect: Rect
    column: int
    lane: int


@dataclass(frozen=True, slots=True)
class LaidEdge:
    """One ``shape.edges`` entry: ``points`` (a right-angled polyline from the source's port
    to the target's; the last segment points into the target), ``label`` (the tag place, or
    None for a non-choice edge), ``back`` (a cycle's back edge), ``detour`` (a forward edge
    routed like a back edge: bottom-mid to bottom-mid)."""

    edge: int
    points: tuple[Point, ...]
    label: Rect | None
    back: bool
    detour: bool

    @property
    def loop(self) -> bool:
        return self.back or self.detour


class _Index:
    """Buckets of ``INDEX_BUCKET`` units holding the cells, segments, and tags meeting them."""

    __slots__ = ("cells", "edges")

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[int]] = {}
        self.edges: dict[tuple[int, int], list[int]] = {}

    @staticmethod
    def _keys(x0: int, y0: int, x1: int, y1: int) -> Iterator[tuple[int, int]]:
        b = INDEX_BUCKET
        for bx in range(x0 // b, x1 // b + 1):
            for by in range(y0 // b, y1 // b + 1):
                yield bx, by

    def add(self, table: dict[tuple[int, int], list[int]], item: int,
            x0: int, y0: int, x1: int, y1: int) -> int:
        count = 0
        for key in self._keys(x0, y0, x1, y1):
            bucket = table.setdefault(key, [])
            if not bucket or bucket[-1] != item:
                bucket.append(item)
            count += 1
        return count

    def query(self, rect: Rect) -> tuple[set[int], set[int]]:
        x, y, w, h = rect
        cells: set[int] = set()
        edges: set[int] = set()
        for key in self._keys(x, y, x + max(w, 0), y + max(h, 0)):
            cells.update(self.cells.get(key, ()))
            edges.update(self.edges.get(key, ()))
        return cells, edges


@dataclass(frozen=True, slots=True)
class ChartLayout:
    """One laid-out chart (04 §7.7 step 10). ``cells`` in ``shape.nodes`` order; ``edges``
    indexed like ``shape.edges``; ``bounds`` from (0, 0); ``reading`` the node indexes by
    column, then lane. ``visible(rect)`` culls; ``cell(node)`` finds a node's cell."""

    cells: tuple[LaidCell, ...]
    edges: tuple[LaidEdge, ...]
    bounds: Rect
    reading: tuple[int, ...]
    columns: int
    lanes: int
    metrics: ChartMetrics
    _by_node: Mapping[int, LaidCell] = field(compare=False, repr=False)
    _index: _Index = field(compare=False, repr=False)

    def cell(self, node: int) -> LaidCell | None:
        return self._by_node.get(node)

    def visible(self, rect: Rect) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """The node indexes whose cells, and the edge indexes whose segments or tags, may meet
        ``rect`` (a superset by at most one bucket; sorted). Work grows with what is near
        ``rect``, not with the chart."""
        cells, edges = self._index.query(rect)
        x, y, w, h = rect
        near = sorted(n for n in cells if _meets(self._by_node[n].rect, x, y, w, h))
        return tuple(near), tuple(sorted(edges))


def _meets(r: Rect, x: int, y: int, w: int, h: int) -> bool:
    return r[0] <= x + w and x <= r[0] + r[2] and r[1] <= y + h and y <= r[1] + r[3]


def _never() -> float:
    return 0.0


class LayoutJob:
    """04 §7.7: ``LayoutJob(records, metrics)``. ``step(deadline, clock)`` works until
    ``clock() >= deadline`` (at least ``units`` work units) and returns True when done;
    ``run()`` finishes at once. ``result`` is the ``ChartLayout``; it never depends on
    ``units`` or the slices. ``work`` counts the units done."""

    def __init__(self, records: "ChartRecords", metrics: ChartMetrics, *,
                 units: int = LAYOUT_STEP_UNITS) -> None:
        self.records = records
        self.metrics = metrics
        self.units = max(1, units)
        self.result: ChartLayout | None = None
        self.done = False
        self.work = 0
        self._left = self.units
        self._gen: Iterator[None] | None = self._run()

    def step(self, deadline: float, clock: Callable[[], float]) -> bool:
        while not self.done:
            try:
                next(self._gen)                               # type: ignore[arg-type]
            except StopIteration:
                self.done = True
                self._gen = None
                break
            if clock() >= deadline:
                break
        return self.done

    def run(self) -> ChartLayout:
        while not self.step(1.0, _never):
            pass
        assert self.result is not None
        return self.result

    def _spend(self, n: int = 1) -> bool:
        """Count ``n`` work units; True when a yield is due."""
        self.work += n
        self._left -= n
        if self._left <= 0:
            self._left = self.units
            return True
        return False

    # The layout ---------------------------------------------------------------------------

    def _run(self) -> Iterator[None]:
        m = self.metrics
        records = self.records
        shape = records.shape
        nodes = tuple(shape.nodes)
        count = len(nodes)
        local = {node: k for k, node in enumerate(nodes)}     # story order = local index
        n_edges = len(shape.edges)
        esrc = [-1] * n_edges
        edst = [-1] * n_edges
        etag = [False] * n_edges
        out: list[list[int]] = [[] for _ in range(count)]
        into: list[list[int]] = [[] for _ in range(count)]
        for e, chart_edge in enumerate(shape.edges):
            s, d = local.get(chart_edge.src), local.get(chart_edge.dst)
            if s is None or d is None:
                continue
            esrc[e], edst[e], etag[e] = s, d, bool(chart_edge.choices)
            out[s].append(e)
            into[d].append(e)
            if self._spend():
                yield
        live = [e for e in range(n_edges) if esrc[e] >= 0]

        # 2. Cycles: iterative DFS from the start, then unvisited nodes in story order.
        back = [False] * n_edges
        pre = [0] * count
        seen = [0] * count                                    # 0 new, 1 on stack, 2 done
        kinds = shape.kinds
        roots = [k for k in range(count) if kinds[nodes[k]] == "start"][:1]
        roots += range(count)
        counter = 0
        for root in roots:
            if seen[root]:
                continue
            seen[root] = 1
            pre[root] = counter
            counter += 1
            stack = [(root, 0)]
            while stack:
                v, i = stack[-1]
                if i < len(out[v]):
                    stack[-1] = (v, i + 1)
                    e = out[v][i]
                    w = edst[e]
                    if seen[w] == 1:
                        back[e] = True
                    elif seen[w] == 0:
                        seen[w] = 1
                        pre[w] = counter
                        counter += 1
                        stack.append((w, 0))
                else:
                    seen[v] = 2
                    stack.pop()
                if self._spend():
                    yield

        # 3. Columns: longest path over forward edges (Kahn; the forward graph is acyclic).
        # A node taking two or more edges, one of them a tagged edge of one column, moves one
        # column right: every hop into it then comes from a dummy, so no tag shares its run.
        indeg = [0] * count
        for e in live:
            if not back[e]:
                indeg[edst[e]] += 1
        many = [n > 1 for n in indeg]
        push = [False] * count
        col = [0] * count
        queue = deque(k for k in range(count) if indeg[k] == 0)
        topo: list[int] = []
        while queue:
            v = queue.popleft()
            topo.append(v)
            for e in out[v]:
                if back[e]:
                    continue
                w = edst[e]
                col[w] = max(col[w], col[v] + 1)
                indeg[w] -= 1
                if indeg[w] == 0:
                    push[w] = many[w] and any(etag[f] and col[esrc[f]] + 1 == col[w]
                                              for f in into[w] if not back[f])
                    col[w] += push[w]
                    queue.append(w)
            if self._spend():
                yield
        # Nodes the first root doesn't lead to (unreachable from the start) sit as far right
        # as their successors allow rather than from column 0, so their edges stay short.
        reached = [False] * count
        if roots:
            reached[roots[0]] = True
        for v in topo:
            if reached[v]:
                for e in out[v]:
                    if not back[e]:
                        reached[edst[e]] = True
        for v in reversed(topo):
            if not reached[v]:
                nearest = [col[edst[e]] - 1 - (push[edst[e]] or (etag[e] and many[edst[e]]))
                           for e in out[v] if not back[e]]
                if nearest:
                    col[v] = max(col[v], min(nearest))
            if self._spend():
                yield
        columns = max(col, default=-1) + 1

        # 4. Dummies, shortest edges first, within FLOW_DUMMIES_MAX; the rest are detours.
        detour = [False] * n_edges
        cell_col = list(col)
        cell_edge = [-1] * count                              # a dummy's edge
        cell_origin = list(range(count))                      # story key: the source's index
        chains: dict[int, list[int]] = {}
        long_edges = []
        for e in live:
            if back[e]:
                continue
            span = col[edst[e]] - col[esrc[e]]
            if span == 1:
                chains[e] = [esrc[e], edst[e]]
            else:
                long_edges.append((span, e))
        long_edges.sort()
        cap = FLOW_DUMMIES_MAX
        total = 0
        for span, e in long_edges:
            if total + span - 1 > cap:
                detour[e] = True
                continue
            total += span - 1
            chain = [esrc[e]]
            for c in range(col[esrc[e]] + 1, col[edst[e]]):
                chain.append(len(cell_col))
                cell_col.append(c)
                cell_edge.append(e)
                cell_origin.append(esrc[e])
            chain.append(edst[e])
            chains[e] = chain
            if self._spend(span):
                yield
        cells_n = len(cell_col)

        # Hops: (gap, source cell, target cell, edge, first hop of its edge).
        hsrc: list[int] = []
        hdst: list[int] = []
        hedge: list[int] = []
        hfirst: list[bool] = []
        preds: list[list[int]] = [[] for _ in range(cells_n)]
        succs: list[list[int]] = [[] for _ in range(cells_n)]
        gap_hops: list[list[int]] = [[] for _ in range(max(columns - 1, 0))]
        edge_hops: dict[int, list[int]] = {}
        for e in sorted(chains):
            chain = chains[e]
            for k in range(len(chain) - 1):
                p, q = chain[k], chain[k + 1]
                h = len(hsrc)
                hsrc.append(p)
                hdst.append(q)
                hedge.append(e)
                hfirst.append(k == 0)
                preds[q].append(p)
                succs[p].append(q)
                gap_hops[cell_col[p]].append(h)
                edge_hops.setdefault(e, []).append(h)
            if self._spend(len(chain)):
                yield

        # 5. Order: DFS preorder, then 4 barycenter sweeps.
        by_col: list[list[int]] = [[] for _ in range(columns)]
        for cell in range(cells_n):
            by_col[cell_col[cell]].append(cell)

        def first_key(cell: int) -> tuple[int, int, int]:
            if cell < count:
                return (pre[cell], 0, 0)
            return (pre[cell_origin[cell]], 1, cell_edge[cell])

        pos = [0] * cells_n
        for c in range(columns):
            by_col[c].sort(key=first_key)
            for i, cell in enumerate(by_col[c]):
                pos[cell] = i
            if self._spend(len(by_col[c])):
                yield
        for sweep in range(4):
            right = sweep % 2 == 0
            near = preds if right else succs
            order = range(1, columns) if right else range(columns - 2, -1, -1)
            for c in order:
                keyed = []                                    # a cell with no neighbour there
                slots = []                                    # keeps its place
                for i, cell in enumerate(by_col[c]):
                    around = near[cell]
                    if around:
                        keyed.append((sum(pos[x] for x in around) / len(around), i, cell))
                        slots.append(i)
                keyed.sort()
                placed = list(by_col[c])
                for i, (_, _, cell) in zip(slots, keyed):
                    placed[i] = cell
                by_col[c] = placed
                for i, cell in enumerate(by_col[c]):
                    pos[cell] = i
                if self._spend(len(keyed)):
                    yield

        # 6. Lanes.
        def story_key(cell: int) -> tuple[int, int, int]:
            return (cell_origin[cell], 0 if cell < count else 1, cell_edge[cell])

        lane = [0] * cells_n
        for c in range(columns):
            prev = -1
            for cell in by_col[c]:
                want = prev + 1
                if preds[cell]:
                    first = min(preds[cell], key=story_key)
                    want = max(want, lane[first])
                lane[cell] = want
                prev = want
            if self._spend(len(by_col[c])):
                yield
        lanes = max(lane, default=-1) + 1

        # 8a. Hops per gap: reroute until no gap has a tag sharing a run or a track cycle.
        def edge_key(e: int) -> tuple[int, int]:
            return (esrc[e], e)

        dirty = deque(range(len(gap_hops)))
        queued = set(dirty)
        plans: dict[int, tuple[list[int], dict[int, list[int]]]] = {}
        while dirty:
            g = dirty.popleft()
            queued.discard(g)
            hops = [h for h in gap_hops[g] if not detour[hedge[h]]]
            reroute, plan = self._gap_plan(hops, hsrc, hdst, hedge, hfirst, etag, lane,
                                           edge_key)
            if self._spend(len(hops) + 1):
                yield
            if plan is not None:
                plans[g] = plan
                continue
            for e in reroute:
                detour[e] = True
                for h in edge_hops[e]:
                    other = cell_col[hsrc[h]]
                    if other not in queued:
                        queued.add(other)
                        dirty.append(other)

        # Loops (back edges and detours): ports, the gap of the vertical, rows.
        loops = sorted((e for e in live if back[e] or detour[e]), key=edge_key)
        sends = [False] * count
        takes = [False] * count
        for e in loops:
            sends[esrc[e]] = True
            takes[edst[e]] = True
        shifted = [sends[k] and takes[k] for k in range(count)]
        loop_gap: dict[int, int] = {}                         # edge → column gap of its track
        for e in loops:
            s, d = esrc[e], edst[e]
            if back[e] and s != d and lane[s] == lane[d]:
                continue                                      # one row, no vertical
            loop_gap[e] = (col[d] if back[e] else col[s]) - 1

        # 8b. Tracks per gap (-1 is the margin left of column 0).
        track_of: dict[tuple[int, int], int] = {}             # (gap, source cell) → track
        loop_track: dict[int, int] = {}
        gap_tracks: dict[int, int] = {}
        verticals: dict[int, list[int]] = {}
        for e in loops:
            if e in loop_gap:
                verticals.setdefault(loop_gap[e], []).append(e)
        for g in range(-1, max(columns - 1, 0)):
            tracks: list[list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = []

            def place(lo: tuple[int, int, int], hi: tuple[int, int, int], least: int) -> int:
                t = least
                while t < len(tracks) and any(a <= hi and lo <= b for a, b in tracks[t]):
                    t += 1
                if t == len(tracks):
                    tracks.append([])
                tracks[t].append((lo, hi))
                return t

            placing, before = plans.get(g, ([], {}))
            for cell in placing:
                spans = [lane[cell]] + [lane[hdst[h]] for h in gap_hops[g]
                                        if hsrc[h] == cell and not detour[hedge[h]]]
                least = 0
                for first in before.get(cell, ()):
                    least = max(least, track_of[(g, first)] + 1)
                track_of[(g, cell)] = place((min(spans), 0, 0), (max(spans), 0, 0), least)
            for e in verticals.get(g, ()):
                i, j = lane[esrc[e]], lane[edst[e]]
                loop_track[e] = place((min(i, j), 1, 0), (max(i, j), 1, 1), 0)
            gap_tracks[g] = len(tracks)
            if self._spend(len(tracks) + 1):
                yield

        # 9a. Which gaps hold tags.
        tagged_gap: set[int] = set()
        for g, hops in enumerate(gap_hops):
            if any(hfirst[h] and etag[hedge[h]] and not detour[hedge[h]] for h in hops):
                tagged_gap.add(g)
        for e in loops:
            if etag[e]:
                tagged_gap.add(col[esrc[e]] - 1)

        # 8c. Rows in lane gaps (symbolic x: (column, 0, port) or (gap, 1, track)).
        def port(cell: int, entering: bool) -> tuple[int, int, int]:
            return (col[cell], 0, (1 if entering else -1) if shifted[cell] else 0)

        rows: list[list[list[tuple[tuple[int, int, int], tuple[int, int, int]]]]] = [
            [] for _ in range(lanes)]
        row_tagged: list[list[bool]] = [[] for _ in range(lanes)]
        loop_rows: dict[int, tuple[int, int]] = {}            # edge → (exit row, entry row)

        def put(gap_lane: int, lo: tuple[int, int, int], hi: tuple[int, int, int],
                least: int, tag: bool) -> int:
            band = rows[gap_lane]
            r = least
            while r < len(band) and any(a <= hi and lo <= b for a, b in band[r]):
                r += 1
            if r == len(band):
                band.append([])
                row_tagged[gap_lane].append(False)
            band[r].append((lo, hi))
            row_tagged[gap_lane][r] = row_tagged[gap_lane][r] or tag
            return r

        for e in loops:
            s, d = esrc[e], edst[e]
            a, b = port(s, False), port(d, True)
            if e not in loop_gap:
                r = put(lane[s], min(a, b), max(a, b), 0, etag[e])
                loop_rows[e] = (r, r)
            else:
                x = (loop_gap[e], 1, loop_track[e])
                r1 = put(lane[s], min(a, x), max(a, x), 0, etag[e])
                least = r1 + 1 if lane[s] == lane[d] else 0
                r2 = put(lane[d], min(b, x), max(b, x), least, False)
                loop_rows[e] = (r1, r2)
            if self._spend():
                yield

        # 7. Sizes and coordinates.
        gate_rows = {view.node: len(view.rows) for view in records.gates}
        height = [0] * cells_n
        for k in range(count):
            node = nodes[k]
            height[k] = (m.gate_h(gate_rows.get(node, 0)) if kinds[node] == "gate"
                         else m.cell_h)
        lane_h = [m.cell_h] * lanes
        for cell in range(cells_n):
            lane_h[lane[cell]] = max(lane_h[lane[cell]], height[cell])
        pad = m.u(8)
        loop_band, tag_band = m.u(8), m.t + 14

        def bands(i: int) -> list[int]:
            return [tag_band if tagged else loop_band for tagged in row_tagged[i]]

        gap_h = []
        for i in range(lanes):
            used = sum(bands(i))
            gap_h.append(max(m.lane_gap, pad + used + m.tag_h + m.u(4)) if used
                         else m.lane_gap)
        lane_top = []
        y = m.lane_gap
        for i in range(lanes):
            lane_top.append(y)
            y += lane_h[i] + gap_h[i]
        bottom = y
        row_y: list[list[int]] = []
        for i in range(lanes):
            ys = []
            at = lane_top[i] + lane_h[i] + pad
            for band in bands(i):
                ys.append(at + band // 2)
                at += band
            row_y.append(ys)
        centre = [lane_top[i] + lane_h[i] // 2 for i in range(lanes)]

        width_w = m.cell_w
        left_w = (m.gap_w(gap_tracks.get(-1, 0), -1 in tagged_gap)
                  if gap_tracks.get(-1, 0) or -1 in tagged_gap else 0)
        col_x = []
        x = left_w
        for c in range(columns):
            col_x.append(x)
            x += width_w
            if c < columns - 1:
                x += m.gap_w(gap_tracks.get(c, 0), c in tagged_gap)
        right = x if columns else 0

        def gap_left(g: int) -> int:
            return 0 if g < 0 else col_x[g] + width_w

        def track_x(g: int, t: int) -> int:
            return gap_left(g) + m.bus + m.track * t

        def tag_x(g: int) -> int:
            return gap_left(g) + m.bus + m.track * (max(gap_tracks.get(g, 0), 1) - 1) + m.track

        cell_rect: list[Rect] = []
        for cell in range(cells_n):
            h = height[cell]
            cell_rect.append((col_x[cell_col[cell]], centre[lane[cell]] - h // 2, width_w, h))
        if self._spend(cells_n):
            yield

        # 8d. Points.
        laid: list[LaidEdge] = []
        for e in range(n_edges):
            if esrc[e] < 0:
                laid.append(LaidEdge(e, (), None, False, False))
                continue
            s, d = esrc[e], edst[e]
            label: Rect | None = None
            if e in chains and not detour[e]:
                rs = cell_rect[s]
                pts: list[Point] = [(rs[0] + rs[2], centre[lane[s]])]
                for h in edge_hops[e]:
                    p, q = hsrc[h], hdst[h]
                    g = cell_col[p]
                    yq = centre[lane[q]]
                    if lane[p] != lane[q]:
                        tx = track_x(g, track_of[(g, p)])
                        pts += [(tx, centre[lane[p]]), (tx, yq)]
                    pts.append((col_x[cell_col[q]], yq))
                    if q >= count:                            # a dummy: straight through
                        pts.append((col_x[cell_col[q]] + width_w, yq))
                    if hfirst[h] and etag[e]:
                        label = (tag_x(g), yq - m.tag_h // 2, m.tag_w, m.tag_h)
            else:
                rs, rd = cell_rect[s], cell_rect[d]
                ux = rs[0] + rs[2] // 2 - (m.shift if shifted[s] else 0)
                vx = rd[0] + rd[2] // 2 + (m.shift if shifted[d] else 0)
                r1, r2 = loop_rows[e]
                y1, y2 = row_y[lane[s]][r1], row_y[lane[d]][r2]
                pts = [(ux, rs[1] + rs[3]), (ux, y1)]
                if e in loop_gap:
                    xx = track_x(loop_gap[e], loop_track[e])
                    pts += [(xx, y1), (xx, y2)]
                pts += [(vx, y2), (vx, rd[1] + rd[3])]
                if etag[e]:
                    label = (tag_x(col[s] - 1), y1 - m.tag_h // 2, m.tag_w, m.tag_h)
            laid.append(LaidEdge(e, _simplify(pts), label, back[e], detour[e]))
            if self._spend():
                yield

        # 10. Cells, reading order, the culling index.
        cells = tuple(LaidCell(nodes[k], cell_rect[k], col[k], lane[k]) for k in range(count))
        by_node = {cell.node: cell for cell in cells}
        reading = tuple(nodes[k] for k in sorted(range(count), key=lambda k: (col[k], lane[k])))
        index = _Index()
        for cell in cells:
            x0, y0, w, h = cell.rect
            if self._spend(index.add(index.cells, cell.node, x0, y0, x0 + w, y0 + h)):
                yield
        for edge in laid:
            spent = 0
            for (ax, ay), (bx, by) in zip(edge.points, edge.points[1:]):
                spent += index.add(index.edges, edge.edge, min(ax, bx), min(ay, by),
                                   max(ax, bx), max(ay, by))
            if edge.label is not None:
                x0, y0, w, h = edge.label
                spent += index.add(index.edges, edge.edge, x0, y0, x0 + w, y0 + h)
            if self._spend(spent + 1):
                yield
        self.result = ChartLayout(cells=cells, edges=tuple(laid), bounds=(0, 0, right, bottom),
                                  reading=reading, columns=columns, lanes=lanes, metrics=m,
                                  _by_node=MappingProxyType(by_node), _index=index)

    # A gap's hops ---------------------------------------------------------------------------

    def _gap_plan(self, hops: list[int], hsrc: list[int], hdst: list[int], hedge: list[int],
                  hfirst: list[bool], etag: list[bool], lane: list[int],
                  edge_key: Callable[[int], tuple[int, int]]
                  ) -> tuple[list[int], tuple[list[int], dict[int, list[int]]] | None]:
        """One gap's hops: (edges to reroute, None), or ([], (the sources needing a track in
        placing order, each source's sources whose track must lie left of its own))."""
        by_dst: dict[int, list[int]] = {}
        for h in hops:
            by_dst.setdefault(hdst[h], []).append(h)
        reroute: list[int] = []
        for target_hops in by_dst.values():
            if len(target_hops) < 2:
                continue
            tagged = [h for h in target_hops if hfirst[h] and etag[hedge[h]]]
            if not tagged:
                continue
            if len(tagged) < len(target_hops):
                reroute += [hedge[h] for h in tagged]
            else:
                tagged.sort(key=lambda h: edge_key(hedge[h]))
                reroute += [hedge[h] for h in tagged[1:]]
        if reroute:
            return sorted(set(reroute), key=edge_key), None

        src_hops: dict[int, list[int]] = {}
        for h in hops:
            src_hops.setdefault(hsrc[h], []).append(h)
        needs = {s for s, hs in src_hops.items() if any(lane[hdst[h]] != lane[s] for h in hs)}
        at_lane = {lane[s]: s for s in src_hops}
        after: dict[int, list[tuple[int, int]]] = {s: [] for s in needs}   # s → (x, hop)
        indeg = dict.fromkeys(needs, 0)
        for h in hops:
            x, i = hsrc[h], lane[hdst[h]]
            first = at_lane.get(i)
            if first is None or first == x or first not in needs:
                continue
            after[first].append((x, h))
            indeg[x] += 1
        heap = [(lane[s], s) for s in needs if indeg[s] == 0]
        heapq.heapify(heap)
        placed: list[int] = []
        left = dict(indeg)
        while heap:
            _, s = heapq.heappop(heap)
            placed.append(s)
            for x, _ in after[s]:
                left[x] -= 1
                if left[x] == 0:
                    heapq.heappush(heap, (lane[x], x))
        if len(placed) < len(needs):
            # A cycle of "my stub ends before your track": walk back along it and reroute
            # its latest edge.
            rest = {s for s in needs if left[s] > 0}
            back_to: dict[int, list[tuple[int, int]]] = {}
            for s in sorted(rest, key=lambda c: (lane[c], c)):
                for x, h in after.get(s, ()):
                    if x in rest:
                        back_to.setdefault(x, []).append((s, h))
            v = min(rest, key=lambda c: (lane[c], c))
            trail: list[tuple[int, int]] = []
            met: dict[int, int] = {}
            while v not in met:
                met[v] = len(trail)
                s, h = back_to[v][0]
                trail.append((v, h))
                v = s
            cycle = trail[met[v]:]
            worst = max((hedge[h] for _, h in cycle), key=edge_key)
            return [worst], None
        before: dict[int, list[int]] = {}
        for s in placed:
            for x, _ in after[s]:
                before.setdefault(x, []).append(s)
        return [], (placed, before)


def _simplify(points: list[Point]) -> tuple[Point, ...]:
    """Drop repeated points and merge collinear runs."""
    kept: list[Point] = []
    for p in points:
        if kept and kept[-1] == p:
            continue
        if len(kept) >= 2 and ((kept[-2][0] == kept[-1][0] == p[0])
                               or (kept[-2][1] == kept[-1][1] == p[1])):
            kept[-1] = p
        else:
            kept.append(p)
    return tuple(kept)


__all__ = ["ChartLayout", "ChartMetrics", "FLOW_DUMMIES_MAX", "INDEX_BUCKET",
           "LAYOUT_STEP_UNITS", "LaidCell", "LaidEdge", "LayoutJob", "Point", "Rect"]
