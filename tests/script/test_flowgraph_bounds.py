"""F20 s2 — AC-F20-49 (05 group I; SEC-F20-12, TR-F20-08): the graph build is bounded.

Generated scripts (``tests/script/flowgraph_gen.py``) are loaded without a graph, then
``FlowGraphJob`` runs on the ``Program`` in its own steps. The default tier uses the smaller
inputs and a lowered recursion limit; the ``slow`` rows use the full sizes, time each step
with the collector paused (as ``StoryLoader.step`` runs it), and measure memory with
``tracemalloc``. The layout DFS half of the last row comes with F20 s7 (``ui/flowlayout.py``).
"""

import gc
import random
import sys
import time
import tracemalloc
from contextlib import contextmanager
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.script import limits, load_story
from engine.script.diagnostics import DiagnosticSink
from engine.script.flowgraph import FlowGraphJob, FlowOptions, plain_title, show_text
from engine.script.loader import LoadOptions
from engine.script.program import Program
from engine.script.texttags import BASE_STYLE, Span, TaggedText, VarMark
from tests.script import flowgraph_gen as gen


def program_of(root: Path, text: str) -> Program:
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_bytes(text.encode("utf-8"))
    result = load_story(GamePaths(root.resolve()), LoadOptions(dev=False))
    assert result.program is not None, [e.format() for e in result.errors][:3]
    return result.program


def run(program: Program, *, units: int = limits.FLOW_STEP_UNITS, schedule=None,
        timed: bool = False) -> tuple[FlowGraphJob, DiagnosticSink, float]:
    """Run the job to the end; every step's work is ≤ ``units``. ``schedule`` picks each
    step's units; ``timed`` returns the slowest step (collector paused per step)."""
    sink = DiagnosticSink()
    job = FlowGraphJob(program, FlowOptions(), sink, units=units)
    worst = 0.0
    steps = 0
    while True:
        if schedule is not None:
            job.units = schedule()
        if timed:
            gc.disable()
        began = time.perf_counter()
        try:
            done = job.step()
        finally:
            if timed:
                gc.enable()
        worst = max(worst, time.perf_counter() - began)
        assert job.last_units <= job.units, (steps, job.last_units)
        steps += 1
        assert steps < 1_000_000                              # never a hang
        if done:
            return job, sink, worst


def _depth() -> int:
    frame, depth = sys._getframe(), 0
    while frame is not None:
        frame, depth = frame.f_back, depth + 1
    return depth


@contextmanager
def recursion_limit(limit: int):
    assert _depth() < limit - 40, _depth()       # room for the job's own fixed-depth frames
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(limit)
    try:
        yield
    finally:
        sys.setrecursionlimit(old)


def test_ac_f20_49_graph_build_is_bounded(tmp_path, monkeypatch):
    # Chains of 2,000 labels at recursion limit 200: the graph builds.
    calls = program_of(tmp_path / "calls", gen.call_chain(2_000))
    jumps = program_of(tmp_path / "jumps", gen.jump_chain(2_000))
    with recursion_limit(200):
        job, sink, _ = run(calls)
        assert sink.error_count == 0 and job.result is not None
        graph = job.result
        assert [(graph.nodes[e.src].id, graph.nodes[e.dst].id) for e in graph.edges] == [
            ("start", "chapter:deep"), ("chapter:deep", "chapter:done")]
        job, sink, _ = run(jumps)
        assert sink.error_count == 0 and len(job.result.nodes) == 21
        # plain_title on a 2,000-part text.
        body = TaggedText(tuple(Span("a", BASE_STYLE) if i % 2 else VarMark("v", BASE_STYLE)
                                for i in range(2_000)))
        assert show_text(plain_title(body), var="") == "a" * 1_000
    # Mutual recursion terminates, with equal results over 5 slice schedules.
    mutual = program_of(tmp_path / "mutual", gen.mutual_recursion())
    first, _, _ = run(mutual)
    edges = {(first.result.nodes[e.src].id, first.result.nodes[e.dst].id)
             for e in first.result.edges}
    assert edges == {("chapter:c1", "chapter:mid"), ("chapter:c1", "chapter:c2"),
                     ("chapter:mid", "chapter:mid"), ("chapter:mid", "chapter:c2")}
    rng = random.Random(49)
    for _ in range(5):
        job, _, _ = run(mutual, units=10**9, schedule=lambda: rng.choice((1, 3, 40, 2_000)))
        assert job.result == first.result
    # A ladder and many calls with the work cap patched: a graph or E265's "too complex"
    # form, never a hang; every step stays within its units (``run`` checks).
    monkeypatch.setattr(limits, "FLOW_WORK_MAX", 50_000)
    job, sink, _ = run(program_of(tmp_path / "ladder", gen.ladder(300)))
    assert sink.error_count == 0 and len(job.result.nodes) == 301
    job, sink, _ = run(program_of(tmp_path / "many", gen.many_calls(200, 50)))
    assert job.result is None and [d.code for d in sink.kept()] == ["E265"]
    assert sink.kept()[0].args[0] == "complex"


@pytest.mark.slow
def test_ac_f20_49_full_size_bounds(tmp_path):
    """The full fixtures: 10,000- and 5,000-label chains at the normal limit, a 2,999-scene
    ladder, 2,000 labels each calling 50 others, and the 50,000-line story: no step over
    50 ms and ≤ 64 MiB of new memory above the Program."""
    for name, text in (("calls", gen.call_chain(10_000)), ("jumps", gen.jump_chain(5_000)),
                       ("ladder", gen.ladder(2_999)), ("many", gen.many_calls(2_000, 50)),
                       ("story", gen.statements(50_000))):
        program = program_of(tmp_path / name, text)
        _, sink, worst = run(program, timed=True)
        assert sink.error_count == 0, name
        assert worst <= 0.050, (name, worst)
        tracemalloc.start()
        try:
            run(program)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert peak <= limits.FLOW_BUILD_MEM, (name, peak)
