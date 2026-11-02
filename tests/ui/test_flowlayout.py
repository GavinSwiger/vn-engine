"""F20 s7: the chart grid and edge routes (``04-technical.md`` §7.7; ``03-ui.md`` "Chart grid";
``06`` AC-F20-58; TR-F20-10). Records are built straight from a graph (every node shown) or
from seeded random shapes; the rules are checked by ``check_rules``, which knows nothing of
how the layout routes."""

import bisect
import random
from collections import defaultdict
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.runtime.flowchart import ChartEdge, ChartRecords, ChartShape, GateRow, GateView
from engine.script import load_story
from engine.script.flowgraph import FlowGraph, FlowOptions
from engine.script.loader import LoadOptions
from engine.ui import flowlayout
from engine.ui.flowlayout import ChartLayout, ChartMetrics, LayoutJob
from tests.script.helpers import F20_TEMPLATE

KINDS = ("scene", "chapter", "choice", "ending", "gate")


def records_of(kinds: list[str], edges: list[tuple[int, int, int]], *,
               gates: dict[int, int] | None = None,
               shown: list[int] | None = None) -> ChartRecords:
    """Records for a chart shape: ``kinds`` per node (story order = index), ``edges`` as
    (src, dst, choices), ``gates`` node → until-ending count, ``shown`` the shown nodes."""
    count = len(kinds)
    shown = list(range(count)) if shown is None else shown
    keep = set(shown)
    chart_edges = tuple(ChartEdge(s, d, (e,), tuple(f"c{e}_{k}" for k in range(n)))
                        for e, (s, d, n) in enumerate(edges) if s in keep and d in keep)
    views = tuple(GateView(node, None, tuple(GateRow(None, False, None) for _ in range(k)))
                  for node, k in sorted((gates or {}).items()) if node in keep)
    shape = ChartShape(kinds=tuple(kinds), no_jump=(False,) * count, chapter=(None,) * count,
                       order=tuple(range(count)), nodes=tuple(shown), edges=chart_edges)
    return ChartRecords(shape=shape, titles=(None,) * count,
                        edge_texts=tuple(() for _ in chart_edges), shown=(True,) * count,
                        visited=(False,) * count, taken=(False,) * len(chart_edges),
                        gates=views, here=None, path_nodes=frozenset(), path_edges=frozenset(),
                        recent=None, counts=(0, 0, 0, 0))


def graph_records(graph: FlowGraph) -> ChartRecords:
    """Every node of ``graph`` shown, in story order; gates kept (locked)."""
    order = sorted(range(len(graph.nodes)), key=lambda i: graph.nodes[i].order)
    kinds = [node.kind for node in graph.nodes]
    edges = tuple(ChartEdge(e.src, e.dst, (k,), e.choices) for k, e in enumerate(graph.edges))
    views = tuple(GateView(i, None, (GateRow(None, False, None),) * 2)
                  for i, node in enumerate(graph.nodes) if node.kind == "gate")
    shape = ChartShape(kinds=tuple(kinds), no_jump=(False,) * len(kinds),
                       chapter=(None,) * len(kinds),
                       order=tuple(node.order for node in graph.nodes), nodes=tuple(order),
                       edges=edges)
    n = len(kinds)
    return ChartRecords(shape=shape, titles=(None,) * n, edge_texts=tuple(() for _ in edges),
                        shown=(True,) * n, visited=(False,) * n, taken=(False,) * len(edges),
                        gates=views, here=None, path_nodes=frozenset(),
                        path_edges=frozenset(), recent=None, counts=(0, 0, 0, 0))


def random_records(rng: random.Random, most: int) -> ChartRecords:
    """A seeded random chart: a start, then nodes of random kinds; forward, long, back,
    self, and repeated edges; choice nodes' edges carry 1–2 choices; some nodes unshown."""
    count = rng.randint(2, most)
    kinds = ["start"] + [rng.choice(KINDS) for _ in range(count - 1)]
    edges: list[tuple[int, int, int]] = []
    for i in range(count):
        if kinds[i] == "ending" and rng.random() < 0.8:
            continue
        for _ in range(rng.choice((1, 1, 1, 2, 2, 3))):
            roll = rng.random()
            if roll < 0.6 and i + 1 < count:
                dst = rng.randint(i + 1, min(count - 1, i + 3))
            elif roll < 0.75 and i + 1 < count:
                dst = rng.randint(i + 1, count - 1)
            elif roll < 0.8:
                dst = i
            else:
                dst = rng.randint(0, count - 1)
            choices = rng.randint(1, 2) if kinds[i] == "choice" else 0
            edges.append((i, dst, choices))
            if rng.random() < 0.05:
                edges.append((i, dst, choices))
    gates = {i: rng.randint(0, 5) for i in range(count) if kinds[i] == "gate"}
    shown = [i for i in range(count) if i == 0 or rng.random() < 0.92]
    return records_of(kinds, edges, gates=gates, shown=shown)


# --- The checker (TR-F20-10) ----------------------------------------------------------------

def _segments(points):
    return list(zip(points, points[1:]))


def _seg_meets_rect(a, b, rect) -> list[tuple[int, int]] | None:
    """The part of axis-parallel segment ab inside the closed rect (endpoints), or None."""
    x, y, w, h = rect
    (ax, ay), (bx, by) = a, b
    x0, x1 = sorted((ax, bx))
    y0, y1 = sorted((ay, by))
    lo_x, hi_x = max(x0, x), min(x1, x + w)
    lo_y, hi_y = max(y0, y), min(y1, y + h)
    if lo_x > hi_x or lo_y > hi_y:
        return None
    return [(lo_x, lo_y), (hi_x, hi_y)]


def _overlap(r, q) -> bool:
    return r[0] < q[0] + q[2] and q[0] < r[0] + r[2] and r[1] < q[1] + q[3] and q[1] < r[1] + r[3]


def check_rules(records: ChartRecords, layout: ChartLayout) -> list[str]:
    """TR-F20-10 and AC-F20-58's rows: int coordinates; no two cells overlap; a segment
    meets a cell only at its own edge's ends, and no other edge's tag; tags don't overlap
    cells or tags; segments are axis-parallel and turn at right angles; two edges meet only
    in proper crossings unless they share a source or a target; forward edges run
    right-mid → left-mid, loops bottom-mid (±16·s) → bottom-mid (±16·s), into the target."""
    bad: list[str] = []
    m = layout.metrics
    shape = records.shape
    cells = {cell.node: cell.rect for cell in layout.cells}
    rects = list(cells.items())
    for k, (n, r) in enumerate(rects):
        if not all(isinstance(v, int) for v in r):
            bad.append(f"cell {n} not int")
        for n2, r2 in rects[k + 1:]:
            if _overlap(r, r2):
                bad.append(f"cells {n} and {n2} overlap")
    tags = [(edge.edge, edge.label) for edge in layout.edges if edge.label is not None]
    for k, (e, tag) in enumerate(tags):
        for n, r in rects:
            if _overlap(tag, r):
                bad.append(f"tag of {e} over cell {n}")
        for e2, tag2 in tags[k + 1:]:
            if _overlap(tag, tag2):
                bad.append(f"tags of {e} and {e2} overlap")

    horizontal: dict[int, list] = defaultdict(list)          # y → (x0, x1, edge)
    vertical: dict[int, list] = defaultdict(list)            # x → (y0, y1, edge)
    for edge in layout.edges:
        e = edge.edge
        chart_edge = shape.edges[e]
        pts = edge.points
        if len(pts) < 2:
            bad.append(f"edge {e} has no route")
            continue
        if not all(isinstance(v, int) for p in pts for v in p):
            bad.append(f"edge {e} not int")
        src, dst = cells[chart_edge.src], cells[chart_edge.dst]
        segs = _segments(pts)
        for k, (a, b) in enumerate(segs):
            if a[0] != b[0] and a[1] != b[1]:
                bad.append(f"edge {e} segment {k} is slanted")
            if a == b:
                bad.append(f"edge {e} segment {k} is empty")
            if k and (segs[k - 1][0][0] == a[0]) == (a[0] == b[0]):
                bad.append(f"edge {e} doesn't turn at a right angle at {a}")
        # Ports.
        (sx, sy, sw, sh), (dx, dy, dw, dh) = src, dst
        if edge.loop:
            ok_out = pts[0][1] == sy + sh and abs(pts[0][0] - (sx + sw // 2)) in (0, m.shift)
            ok_in = pts[-1][1] == dy + dh and abs(pts[-1][0] - (dx + dw // 2)) in (0, m.shift)
            if not (ok_out and ok_in and pts[1][1] > pts[0][1] and pts[-2][1] > pts[-1][1]):
                bad.append(f"loop {e} doesn't leave and enter at bottom-mid")
        elif not (pts[0] == (sx + sw, sy + sh // 2) and pts[-1] == (dx, dy + dh // 2)
                  and pts[-2][0] < pts[-1][0]):
            bad.append(f"edge {e} doesn't run right-mid to left-mid")
        # Cells.
        for n, r in rects:
            for k, (a, b) in enumerate(segs):
                part = _seg_meets_rect(a, b, r)
                if part is None:
                    continue
                if n == chart_edge.src and k == 0 and part == [a, a]:
                    continue
                if n == chart_edge.dst and k == len(segs) - 1 and part == [b, b]:
                    continue
                bad.append(f"edge {e} segment {k} meets cell {n}")
        for e2, tag in tags:
            if e2 == e:
                continue
            if any(_seg_meets_rect(a, b, tag) is not None for a, b in segs):
                bad.append(f"edge {e} meets the tag of {e2}")
        for k, (a, b) in enumerate(segs):
            for k2 in range(k + 2, len(segs)):
                c, d = segs[k2]
                if _touch(a, b, c, d):
                    bad.append(f"edge {e} meets itself")
            if a[1] == b[1]:
                horizontal[a[1]].append((min(a[0], b[0]), max(a[0], b[0]), e))
            else:
                vertical[a[0]].append((min(a[1], b[1]), max(a[1], b[1]), e))

    def related(e1: int, e2: int) -> bool:
        x, y = shape.edges[e1], shape.edges[e2]
        return x.src == y.src or x.dst == y.dst

    for table in (horizontal, vertical):
        for runs in table.values():
            runs.sort()
            for k, (lo, hi, e) in enumerate(runs):
                for lo2, hi2, e2 in runs[k + 1:]:
                    if lo2 > hi:
                        break
                    if e2 != e and not related(e, e2):
                        bad.append(f"edges {e} and {e2} overlap")
    ys = sorted(horizontal)
    for x, runs in vertical.items():
        for y0, y1, e in runs:
            for y in ys[bisect.bisect_left(ys, y0):bisect.bisect_right(ys, y1)]:
                for x0, x1, e2 in horizontal[y]:
                    if e2 == e or not x0 <= x <= x1 or related(e, e2):
                        continue
                    if not (x0 < x < x1 and y0 < y < y1):
                        bad.append(f"edges {e} and {e2} touch at ({x}, {y})")
    return bad


def _touch(a, b, c, d) -> bool:
    """Whether two axis-parallel segments share a point."""
    ax0, ax1 = sorted((a[0], b[0]))
    ay0, ay1 = sorted((a[1], b[1]))
    cx0, cx1 = sorted((c[0], d[0]))
    cy0, cy1 = sorted((c[1], d[1]))
    return max(ax0, cx0) <= min(ax1, cx1) and max(ay0, cy0) <= min(ay1, cy1)


def lay(records: ChartRecords, metrics: ChartMetrics = ChartMetrics(), **kw) -> ChartLayout:
    return LayoutJob(records, metrics, **kw).run()


def lanterns(tmp_path: Path) -> FlowGraph:
    (tmp_path / "script").mkdir()
    (tmp_path / "script" / "main.vns").write_bytes(F20_TEMPLATE.read_bytes())
    result = load_story(GamePaths(tmp_path.resolve()), LoadOptions(flowchart=FlowOptions()))
    assert result.program is not None and result.program.flowgraph is not None
    return result.program.flowgraph


# --- AC-F20-58 -------------------------------------------------------------------------------

def test_ac_f20_58_grid_and_routing(tmp_path, monkeypatch):
    # Template L at 100%.
    graph = lanterns(tmp_path)
    records = graph_records(graph)
    layout = lay(records)
    at = {node.id: layout.cell(i) for i, node in enumerate(graph.nodes)}
    menu = next(node.id for node in graph.nodes if node.kind == "choice")
    columns = {"start": 0, "chapter:festival": 1, "scene:stall": 2, menu: 3, "chapter:river": 4,
               "chapter:shrine": 4, "gate:promise": 4, "ending:sad": 5, "ending:good": 5,
               "scene:promise": 5, "ending:true": 6}
    assert {name: at[name].column for name in columns} == columns
    assert at["chapter:river"].lane < at["chapter:shrine"].lane < at["gate:promise"].lane
    assert at["start"].rect[2:] == (240, 84)
    left = {at[name].column: at[name].rect[0] for name in columns}
    gaps = [left[c + 1] - (left[c] + 240) for c in range(6)]
    assert gaps == [56, 56, 56, 224, 56, 56]
    tops = sorted({cell.rect[1] for cell in layout.cells if cell.rect[3] == 84})
    assert at["chapter:shrine"].rect[1] - at["chapter:river"].rect[1] == 126
    assert tops[:2] == [at["chapter:river"].rect[1], at["chapter:shrine"].rect[1]]
    gate = at["gate:promise"].rect
    assert gate[3] == 16 + 34 * 3                            # two until endings
    assert check_rules(records, layout) == []
    labels = [edge.label for edge in layout.edges if edge.label is not None]
    assert len(labels) == 3 and all(lab[2:] == (184, 34) for lab in labels)
    assert all(left[3] + 240 < lab[0] and lab[0] + lab[2] < left[4] for lab in labels)
    assert layout.reading == tuple(sorted(
        (cell.node for cell in layout.cells), key=lambda n: (layout.cell(n).column,
                                                            layout.cell(n).lane)))
    big = lay(records, ChartMetrics(scale=1.5))
    assert big.cell(0).rect[2:] == (360, 126) and check_rules(records, big) == []

    # TR-F20-10: 20 seeded random graphs of ≤ 60 nodes.
    for seed in range(20):
        records = random_records(random.Random(seed), 60)
        assert check_rules(records, lay(records)) == [], seed

    # A 1,000-column chain (and a loop over all of it): int coordinates over 100,000.
    count = 1_000
    chain = records_of(["start"] + ["scene"] * (count - 1),
                       [(i, i + 1, 0) for i in range(count - 1)] + [(count - 1, 1, 0)])
    layout = lay(chain)
    assert layout.columns == count and layout.bounds[2] > 100_000
    assert check_rules(chain, layout) == []
    assert layout.edges[-1].back and max(x for x, _ in layout.edges[-1].points) > 100_000

    # Any slicing gives an equal layout; reading is column, then lane.
    records = random_records(random.Random(99), 60)
    whole = lay(records)
    for units in (1, 7, 123):
        job = LayoutJob(records, ChartMetrics(), units=units)
        ticks = iter(range(10**9))
        steps = 0
        while not job.step(0, lambda: next(ticks)):
            steps += 1
        assert job.result == whole and steps > 0
    tick = iter(range(10**9))
    job = LayoutJob(records, ChartMetrics(), units=5)
    while not job.step(next(tick) + 3, lambda: next(tick)):
        pass
    assert job.result == whole
    keys = [(whole.cell(n).column, whole.cell(n).lane) for n in whole.reading]
    assert keys == sorted(keys) and len(whole.reading) == len(records.shape.nodes)
    # Culling: what meets a rect, and nothing far away.
    x, y, w, h = whole.cell(whole.reading[-1]).rect
    near, edges = whole.visible((x, y, w, h))
    assert whole.reading[-1] in near
    assert whole.visible((-10_000, -10_000, 10, 10)) == ((), ())

    # FLOW_DUMMIES_MAX 5: the extra long edges are detours, tags left of their source.
    monkeypatch.setattr(flowlayout, "FLOW_DUMMIES_MAX", 5)
    kinds = ["start", "choice"] + ["scene"] * 5
    edges = [(i, i + 1, 0) for i in range(6)] + [(1, 4, 1), (1, 5, 1), (1, 6, 1)]
    records = records_of(kinds, edges)
    layout = lay(records)
    detours = [edge for edge in layout.edges if edge.detour]
    assert [records.shape.edges[edge.edge].dst for edge in detours] == [6]
    col0, col1 = layout.cell(0).rect, layout.cell(1).rect
    tag = detours[0].label
    assert tag is not None and col0[0] + col0[2] < tag[0] and tag[0] + tag[2] < col1[0]
    assert sum(1 for edge in layout.edges if edge.label and not edge.detour) == 2
    assert check_rules(records, layout) == []


@pytest.mark.slow
def test_ac_f20_58_random_graphs_slow():
    for seed in range(200):
        rng = random.Random(10_000 + seed)
        records = random_records(rng, 300)
        metrics = ChartMetrics(scale=rng.choice((1.0, 1.5)), text_size=rng.choice((24, 36)))
        assert check_rules(records, lay(records, metrics)) == [], seed
