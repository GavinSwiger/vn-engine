"""F20 s9 — the flowchart's reference-machine performance (``06-acceptance.md`` AC-F20-68,
and AC-F20-64's ``perf`` row; TR-F20-07, TR-F20-08, UI-F20-16; ADR-0005).

**``perf``** (the ADR-0005 reference machine or a recorded stand-in; ``VN_PERF=1``). From the
project root, in cmd::

    set VN_PERF=1
    set SDL_VIDEODRIVER=dummy
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_flowchart_perf.py

(In PowerShell: ``$env:VN_PERF = "1"; $env:SDL_VIDEODRIVER = "dummy"``. The page draws to an
offscreen 1280×720 canvas, so the video driver doesn't change the numbers.) Attach the printed
``AC-F20-68`` lines to the test report.

- **Charts** (``gen_flowchart.chart_story``): 1,000 and 3,000 nodes, every node visited and
  every edge taken (titles and labels all drawn), records from ``chart_records``.
- **Layout:** ``LayoutJob.run()`` at 100%, median of 5 after a warm-up: ≤ 150 ms at 1,000.
- **Page open:** the page built in a bare host (Page P, ``TestShell`` with real fonts) with
  the layout prewarmed (04 §7.7: the page finishes any remainder at once), plus its first
  frame and draw: ≤ 250 ms at 1,000. The cold open (layout included) is printed too.
- **Pan and select:** 300 frames each of ``pan_by`` (60 units a frame, turning at the edges)
  and of selecting the next node in reading order (the pan animation runs), each frame the
  page's ``update`` and the chart's and panel's draw: p99 ≤ 16 ms at 1,000 and 3,000.
- **3,000 nodes, invariant 10:** the layout prewarmed in 2 ms slices (the service's slice):
  no slice over 16 ms; the frames as above.
- **Graph build** (``flowgraph_gen.statements(50_000)``): ``FlowGraphJob`` in its own steps
  with the collector paused per step (as the loader runs it): ≤ 300 ms in total, no step over
  50 ms.
- **Jump vs load** (the example game's state at the bridge's titled menu, seed 1, from a
  headless run's ``flow`` holder; ``SaveService.load_state`` behind a real
  ``RuntimeStoryDriver``): a jump is ``read_node`` + ``load_state(fresh_menu=True)``, a load
  ``read_slot_full`` + ``load_state``, of the same state written as a node file and a slot
  file; interleaved, 20 each after 3 warm-ups: median jump ≤ 1.1 × median load, with the
  node folder in release mode as players run it. A jump's read also checks the saves root
  (SEC-F20-01(a)), a fixed cost a load doesn't pay (F11 checks its root at launch): about
  0.09 ms in release and 0.26 ms in dev runs, which resolve the real path (stand-in
  machine). The dev ratio is printed, not asserted.
"""

import gc
import statistics
import time
from pathlib import Path

import pygame
import pytest

from engine.app.app import GC_FULL_AFTER
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.persist.nodestates import NodeEncoder, NodeFolder, node_file, read_node
from engine.persist.saves import SaveEncoder, SlotId, read_slot_full
from engine.render.canvas import Canvas, RenderQuality
from engine.runtime import flowchart
from engine.script import load_story
from engine.script.flowgraph import FlowOptions
from engine.script.loader import LoadOptions
from engine.ui.flowlayout import ChartMetrics, LayoutJob
from engine.ui.nav import InputKind
from tests.perf.gen_flowchart import chart_story, statements
from tests.runtime.flow_story import records_r, store_r


@pytest.fixture
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


def _p99(times: list[float]) -> float:
    ordered = sorted(times)
    return ordered[max(0, int(len(ordered) * 0.99) - 1)]


class _FullGcLater:
    """The frame loop's collector setting (``GC_FULL_AFTER``), as in ``test_poem_perf``."""

    def __enter__(self):
        gc.collect()
        self.thresholds = gc.get_threshold()
        t = self.thresholds
        gc.set_threshold(t[0], t[1], max(t[2], GC_FULL_AFTER))

    def __exit__(self, *exc):
        gc.set_threshold(*self.thresholds)


def _program(root: Path, text: str):
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_bytes(text.encode("utf-8"))
    result = load_story(GamePaths(root.resolve()), LoadOptions(flowchart=FlowOptions()))
    assert result.program is not None and not result.errors
    return result.program


def _records(program) -> flowchart.ChartRecords:
    """Every node visited and every edge taken: the most a chart ever draws."""
    graph = program.flowgraph
    store = store_r(program)
    for n in graph.nodes:
        if n.kind not in ("start", "gate"):
            store.unlock(flowchart.FLOW_KIND, n.key)
    for e in graph.edges:
        if e.record is not None:
            store.unlock(flowchart.EDGE_KIND, e.record)
    return records_r(program, store)


def _chart(tmp_path: Path, nodes: int):
    from tests.ui.test_flowchart_page import PortP

    program = _program(tmp_path / f"n{nodes}", chart_story(nodes))
    assert len(program.flowgraph.nodes) == nodes
    return program, PortP(program, _records(program), states=())


class _Prewarmed:
    """The port with its layout already finished (the service's prewarm, 04 §7.7)."""

    def __init__(self, port, layout) -> None:
        self.port, self.done = port, layout

    def __getattr__(self, name):
        return getattr(self.port, name)

    def layout(self, metrics):
        job = LayoutJob(self.port.records(), metrics)
        job.result, job.done, job._gen = self.done, True, None
        return job


def _frames(host, step, count: int = 300) -> list[float]:
    """``count`` frames of ``step()``, the page's update, and the chart's and panel's draw
    on one 1280×720 canvas, in ms."""
    surface = pygame.Surface((1280, 720))
    canvas = Canvas(host.shell.assets)
    times = []
    with _FullGcLater():
        for i in range(count):
            canvas.bind(surface, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
            p = host.shell.painter
            p.bind(canvas)
            start = time.perf_counter()
            step(i)
            host.frames(1)
            host.page.draw(canvas, p)
            host.chart.draw(p, host.chart.look(focused=True))
            times.append((time.perf_counter() - start) * 1000)
    return times


def _pan_and_select(host, nodes: int) -> tuple[list[float], list[float]]:
    chart = host.chart
    direction = [60.0]

    def pan(i: int) -> None:
        if i % 100 == 0:
            direction[0] = -direction[0]
        chart.pan_by(direction[0], 15.0 if i % 2 else -15.0)

    reading = chart.layout.reading
    start = reading.index(chart.selected) if chart.selected in reading else 0

    def select(i: int) -> None:
        chart.select(reading[(start + i + 1) % len(reading)])

    host.frames(30)
    panned = _frames(host, pan)
    selected = _frames(host, select)
    for name, times in (("pan", panned), ("select", selected)):
        print(f"AC-F20-68 {nodes:,} nodes {name} frame p50 {statistics.median(times):.2f} ms, "
              f"p99 {_p99(times):.2f} ms (300 frames)")
    return panned, selected


@pytest.mark.perf
def test_ac_f20_68_1000_nodes(tmp_path, pygame_ready):
    from tests.ui.test_flowchart_page import Host

    program, port = _chart(tmp_path, 1_000)
    records, metrics = port.records(), ChartMetrics(scale=1.0)
    LayoutJob(records, metrics).run()                                   # warm-up
    layouts = []
    for _ in range(5):
        start = time.perf_counter()
        layout = LayoutJob(records, metrics).run()
        layouts.append((time.perf_counter() - start) * 1000)
    print(f"\nAC-F20-68 1,000 nodes layout median {statistics.median(layouts):.1f} ms, "
          f"max {max(layouts):.1f} ms ({len(program.flowgraph.edges):,} edges)")

    start = time.perf_counter()
    cold = Host(port)
    cold.frames(1)
    cold.draw()
    cold_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    host = Host(_Prewarmed(port, layout))
    host.frames(1)
    host.draw()
    open_ms = (time.perf_counter() - start) * 1000
    print(f"AC-F20-68 1,000 nodes page open {open_ms:.1f} ms prewarmed, {cold_ms:.1f} ms cold")
    host.focus_chart()
    panned, selected = _pan_and_select(host, 1_000)
    assert statistics.median(layouts) <= 150
    assert open_ms <= 250
    assert _p99(panned) <= 16 and _p99(selected) <= 16


@pytest.mark.perf
def test_ac_f20_68_3000_nodes_within_invariant_10(tmp_path, pygame_ready):
    from tests.ui.test_flowchart_page import Host

    _program_3k, port = _chart(tmp_path, 3_000)
    records = port.records()
    job, slices = LayoutJob(records, ChartMetrics(scale=1.0)), []
    clock = time.perf_counter
    with _FullGcLater():
        while True:
            start = clock()
            done = job.step(start + 0.002, clock)
            slices.append((clock() - start) * 1000)
            if done:
                break
    print(f"\nAC-F20-68 3,000 nodes layout prewarm {len(slices)} slices, "
          f"{sum(slices):.0f} ms in all, longest {max(slices):.2f} ms")
    start = time.perf_counter()
    host = Host(_Prewarmed(port, job.result))
    host.frames(1)
    host.draw()
    print(f"AC-F20-68 3,000 nodes page open {(time.perf_counter() - start) * 1000:.1f} ms "
          "prewarmed")
    host.focus_chart()
    panned, selected = _pan_and_select(host, 3_000)
    assert max(slices) <= 16
    assert _p99(panned) <= 16 and _p99(selected) <= 16


@pytest.mark.perf
def test_ac_f20_68_graph_build_50000_statements(tmp_path):
    from tests.script.test_flowgraph_bounds import program_of, run

    program = program_of(tmp_path / "story", statements(50_000))
    run(program)                                                        # warm-up
    totals, worsts = [], []
    for _ in range(3):
        start = time.perf_counter()
        _job, sink, worst = run(program, timed=True)
        totals.append((time.perf_counter() - start) * 1000)
        worsts.append(worst * 1000)
        assert sink.error_count == 0
    print(f"\nAC-F20-68 graph build (50,000 statements) total median "
          f"{statistics.median(totals):.0f} ms, longest step {max(worsts):.1f} ms")
    assert statistics.median(totals) <= 300 and max(worsts) <= 50


@pytest.mark.perf
def test_ac_f20_68_jump_vs_load(tmp_path):
    from types import SimpleNamespace

    from engine.app.saves import SaveService
    from engine.app.story import RuntimeStoryDriver
    from engine.core.config_schema import Config
    from engine.runtime.flowchart import FlowStates
    from engine.runtime.headless import run_headless
    from tests.app.test_flow_jump import GAME_ID, Shell
    from tests.runtime import corpus
    from tests.runtime.stage_story import EXAMPLE, example_minigames, position_names

    result = load_story(GamePaths(EXAMPLE.resolve()),
                        LoadOptions(position_names=position_names(EXAMPLE),
                                    minigames=example_minigames(), flowchart=FlowOptions()))
    program, images = result.program, corpus.example_images()
    holder = FlowStates()
    run_headless(program, seed=1, image_files=images, flow=holder,
                 inputs=corpus.example_inputs(1, corpus.EXAMPLE_PICKS[1]),
                 minigames=example_minigames())
    m21 = next(n.id for n in program.flowgraph.nodes if n.kind == "choice")
    state = holder[m21]
    assert state is not None
    root = tmp_path / "saves"
    root.mkdir()
    (root / node_file(m21)).write_bytes(b"".join(
        NodeEncoder(state, node_id=m21, game=GAME_ID).run()))
    slot = SlotId("quick", 1)
    (root / slot.file_name()).write_bytes(b"".join(SaveEncoder(
        state, seq=1, saved_at=0, description="perf", chapter=None, game=GAME_ID,
        game_version="1", jpeg=None).run()))
    driver = RuntimeStoryDriver(corpus.launched(program, images))
    saves = SaveService(SimpleNamespace(config=Config(), story=driver, error_mode=False),
                        Shell(), folder=None, folder_ok=False, client=None, release=False)

    def jump(folder: NodeFolder) -> None:
        read = read_node(folder, m21, game_id=GAME_ID)
        assert saves.load_state(read.state, origin="title", by=InputKind.KEYS,
                                fresh_menu=True)

    def load() -> None:
        read = read_slot_full(root, slot, game_id=GAME_ID)
        assert saves.load_state(read.state, origin="title", by=InputKind.KEYS)

    ratios = {}
    print()
    for mode in ("release", "dev"):
        folder = NodeFolder(root, release=mode == "release")
        jumps, loads = [], []
        for n in range(23):
            for fn, out in ((lambda: jump(folder), jumps), (load, loads)):
                start = time.perf_counter()
                fn()
                if n >= 3:
                    out.append((time.perf_counter() - start) * 1000)
        ratios[mode] = statistics.median(jumps) / statistics.median(loads)
        print(f"AC-F20-68 jump ({mode}) median {statistics.median(jumps):.3f} ms, load "
              f"median {statistics.median(loads):.3f} ms, ratio {ratios[mode]:.2f} (20 each)")
    assert ratios["release"] <= 1.1
