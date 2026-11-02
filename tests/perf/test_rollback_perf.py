"""F14 step 7 — rollback performance and memory (``04-technical.md`` §11, §15;
``06-acceptance.md`` §1.7, §5; ``07-architecture-review.md`` §3.6, I-2, I-11, I-12):
AC-F14-33, 34, 35, 36. AC-F14-37 (manual) is ``docs/process/manual-F14.md``.

The bench story is ``tests/fixtures/F14/perf/gen_steps.py``'s ``steps100/``: F03's
``gen_vars.py --n 1000 --seed 5`` as 1,000 ``default`` lines (100 KB), then 101 lines, each
after one ``$`` that changes one variable. The tests write it under ``tmp_path``.

**Default tier (CI guards: a count, a ratio, or a loose limit).**
- AC-F14-33 counts: Run K (seed 42) and the example game (seed 1), played live at depth 100
  with no rollback input, walk the variables (``_freeze_variables``) exactly once per
  checkpoint and never call ``same_step``. AC-F14-33 ratio: AC-F03-76's story with the 1,000
  benchmark variables in ``G``; the median of 200 checkpoints with a full depth-100 timeline
  (101 states held) is ≤ 1.10 × the median at depth 0. The two arms run interleaved in one
  process and the depth-100 arm is full before measuring (07 §3.6).
- AC-F14-34: ``steps100`` headless at depth 100, at its last line: 20 single back steps,
  then 20 single forward steps. Back and forward medians ≤ 20 ms each; each back step runs
  exactly one restore and no re-run, each forward step one re-run (``_forward_once``) and no
  restore.
- AC-F14-35: App R (``scripted_app``, fake clock, 60 fps) on a small story of the same shape
  (8 variables, 101 lines): 3 s of wheel notches back at 30 notches/s, then 3 s forward. No
  frame posts more than one ``StepBack``/``StepForward`` or runs more than one restore, and
  the 90 notches each way all move. Then 5 notches in one frame give one ``StepBack(5)`` and
  one restore.

**``slow``** (``VN_SLOW=1`` or ``-m slow``): AC-F14-36, ``steps100`` played through its 101
lines at depth 100 under ``tracemalloc``: the memory the timeline holds (the drop when it is
cut back to the current step) is ≤ 64 MiB (04 §11 measures 19.8 MiB). AC-F14-33's counts
over F03's corpus (the example at seeds 1–5, the realistic part at seed 1).

**``perf``: the reference-machine run (owner).** ADR-0005: Intel Core i5-8250U, Windows 11,
mains power, "Balanced" plan; or a stand-in with integrated graphics and a PassMark
single-thread score of at most 2,000. Close other apps and don't touch the window while it
runs (about 30 s). From the project root, in cmd::

    set VN_PERF=1
    set SDL_VIDEODRIVER=windows
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_rollback_perf.py

(In PowerShell: ``$env:VN_PERF = "1"; $env:SDL_VIDEODRIVER = "windows"``, then the same
command. ``x11`` or ``cocoa`` elsewhere. Without a video driver the run uses SDL's dummy
driver and the ``flip`` cost isn't real: the printed line says which driver ran.) Attach
the printed ``AC-F14-3x`` and ``I-11`` lines and the machine's PassMark single-thread score
to the test report (06 §0, §7).

- AC-F14-33 (I-12, relative): AC-F03-76's measurement (500 checkpoints after warm-up,
  ``gc`` on) with a full depth-100 timeline held gives a p95 ≤ 1.10 × the same run's p95 at
  depth 0. AC-F03-76 owns the absolute 2.0 ms (``tests/runtime/test_snapshot_perf.py``); the
  line prints both p95s.
- AC-F14-34 (I-2): one in-process launch of ``steps100`` (``bootstrap.launch``, real clock,
  limiter, and window; dev run, 60 fps, ``[textbox] cps = 0``, ``[rollback] steps = 100``)
  played to its last line; then 20 Page Up presses and 20 Page Down presses, one every 10
  frames. Every frame of each step (the input frame and the 9 after it: the post, the
  restore or re-run, the compose) has frame work ≤ 16.0 ms.
- AC-F14-35: in the same launch, wheel notches back at 30 notches/s (one every 2 frames)
  for 3 s, then forward for 3 s: frame-work p99 ≤ 16.0 ms and long frames ≤ 0.5%.
- I-11 (bulk release): in the same launch, one load (``driver.restore`` of a state read back
  from JSON, the part of F11's load that frees the timeline) and one New Game
  (``driver.new_game``), each with a full timeline (101 states). The input frame and the 9
  after it each have frame work ≤ 16.0 ms. The line prints each release's time
  (``Timeline.reset``) and every gen-2 garbage collection of the run (frame and time). If a
  frame goes over, 07 I-11's fallback is pre-approved: release dropped states a few per pump.
"""

import gc
import json
import os
import statistics
import time
import tracemalloc
from pathlib import Path

import pygame
import pytest

from engine.app.story import RuntimeStoryDriver
from engine.runtime import rollback as rollback_mod
from engine.runtime.commands import StepBack, StepForward
from engine.runtime.interpreter import Interpreter, Status, say_command
from engine.runtime.rollback import Timeline
from engine.runtime.state import GameState
from tests.app.test_rollback_install import k_game, line, run, started, unthreaded, wheel
from tests.fakes.loop import post_key
from tests.fixtures.F03.perf.gen_vars import generate
from tests.fixtures.F14.perf import gen_steps
from tests.perf.test_runtime_perf import FRAME_WORK_MAX_S, Probe, _p99, run_game
from tests.runtime import corpus
from tests.runtime.conftest import realistic_part  # noqa: F401  (slow: the shared corpus)
from tests.runtime.effects_story import load_game
from tests.runtime.rollback_story import IMG14, back, fixture, forward, launched, step
from tests.runtime.story import load_files, start
from tests.runtime.test_snapshot_perf import RUNS, STORY, WARMUP
from tests.script.load_process import cpu_name

__all__ = ["unthreaded"]                 # the fixture, re-exported for pytest

DEPTH = 100
RATIO_MAX = 1.10                         # AC-F14-33 (CI ratio and I-12's perf bullet)
CI_RUNS = 200                            # AC-F14-33: the median of 200 checkpoint steps
STEP_MEDIAN_MAX_S = 0.020                # AC-F14-34's CI guard
STEPS = 20                               # AC-F14-34: 20 back, then 20 forward
STEP_FRAMES = 10                         # one step every 10 frames
SPIN_NOTCHES = 90                        # AC-F14-35: 30 notches/s for 3 s
SPIN_EVERY = 2                           # at 60 fps: one notch every 2 frames
LONG_SHARE_MAX = 0.005                   # ADR-0005: long frames ≤ 0.5%
MEMORY_MAX = 64 * 1024 * 1024            # AC-F14-36
BENCH_CONFIG = ('[game]\ntitle = "Rollback bench"\nversion = "0.1.0"\n[title]\nenabled = false\n'
                "[textbox]\ncps = 0\n[rollback]\nsteps = 100\n")
LAST = f"Line {gen_steps.LINES}."


@pytest.fixture(scope="module")
def steps100(tmp_path_factory):
    """``steps100/`` (written once per module) and its loaded program."""
    root = gen_steps.write(tmp_path_factory.mktemp("steps100"))
    return root, load_game(root)


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.2f} ms"


# --- AC-F14-33 — rollback adds no per-line cost ------------------------------------------------

def _count_walks(monkeypatch) -> dict[str, int]:
    """Count checkpoints, variable walks, and ``same_step`` calls from now on."""
    counts = {"checkpoints": 0, "walks": 0, "same_step": 0}
    real_cp, real_walk = Interpreter.take_checkpoint, Interpreter._freeze_variables
    real_same = rollback_mod.same_step

    def take_checkpoint(self, *args, **kwargs):
        counts["checkpoints"] += 1
        return real_cp(self, *args, **kwargs)

    def walk(self, *args, **kwargs):
        counts["walks"] += 1
        return real_walk(self, *args, **kwargs)

    def same_step(*args):
        counts["same_step"] += 1
        return real_same(*args)

    monkeypatch.setattr(Interpreter, "take_checkpoint", take_checkpoint)
    monkeypatch.setattr(Interpreter, "_freeze_variables", walk)
    monkeypatch.setattr(rollback_mod, "same_step", same_step)
    return counts


def _check_one_walk_per_checkpoint(name, program, seed, images, monkeypatch) -> None:
    counts = _count_walks(monkeypatch)
    played = corpus.play(program, seed, images)               # live, no rollback input
    interp = played.interp
    assert interp.status is Status.ENDED and interp.timeline.depth == DEPTH, name
    assert interp.timeline.landings == 0, name
    assert counts["checkpoints"] >= len(played.states) > 0, name
    assert counts["walks"] == counts["checkpoints"], (name, counts)
    assert counts["same_step"] == 0, (name, counts)
    print(f"AC-F14-33 {name}: {counts['checkpoints']} checkpoints, {counts['walks']} walks, "
          f"same_step {counts['same_step']}")
    monkeypatch.undo()


def test_ac33_one_walk_per_checkpoint_and_no_match(monkeypatch):
    _check_one_walk_per_checkpoint("Run K", fixture("steps"), 42, IMG14, monkeypatch)
    _check_one_walk_per_checkpoint("example", corpus.example_program(), 1,
                                   corpus.example_images(), monkeypatch)


@pytest.mark.slow
def test_ac33_one_walk_per_checkpoint_over_the_corpus(realistic_part, monkeypatch):  # noqa: F811
    program, images = corpus.example_program(), corpus.example_images()
    for seed in range(1, 6):
        _check_one_walk_per_checkpoint(f"example {seed}", program, seed, images, monkeypatch)
    _check_one_walk_per_checkpoint("realistic", realistic_part, 1, (), monkeypatch)


def _arm(root: Path, depth: int) -> Interpreter:
    """AC-F03-76's story waiting at its line, with the 1,000 benchmark variables in ``G``."""
    interp = start(load_files(root, {"main.vns": STORY}), rollback_steps=depth)
    assert interp.status is Status.WAITING
    interp.G.update(generate(1000, 5))
    interp.take_commands(1 << 30)
    return interp


def interleaved(tmp_path: Path, warmup: int, runs: int) -> tuple[list[float], list[float]]:
    """AC-F03-76's checkpoint, timed at depth 0 and at depth 100 in turn (the first arm
    alternates). The warm-up fills the depth-100 timeline first (07 §3.6)."""
    arms = [_arm(tmp_path / "depth0", 0), _arm(tmp_path / "depth100", DEPTH)]
    calls = [(a, a.current, say_command(a, a.current)) for a in arms]
    times: list[list[float]] = [[], []]
    for n in range(max(warmup, DEPTH + 1) + runs):
        for i in ((0, 1) if n % 2 == 0 else (1, 0)):
            interp, stmt, cmd = calls[i]
            began = time.perf_counter()
            interp.take_checkpoint(stmt, cmd)
            spent = time.perf_counter() - began
            interp.take_commands(1 << 30)
            if n >= max(warmup, DEPTH + 1):
                times[i].append(spent)
    full = arms[1].timeline
    assert len(arms[0].timeline.states) == 0 and len(full.states) == DEPTH + 1
    assert all(a.status is Status.WAITING for a in arms)
    return times[0], times[1]


def test_ac33_full_timeline_costs_at_most_10_percent(tmp_path):
    zero, full = interleaved(tmp_path, 0, CI_RUNS)
    ratio = statistics.median(full) / statistics.median(zero)
    print(f"AC-F14-33 checkpoint median: depth 0 {_ms(statistics.median(zero))}, depth 100 "
          f"{_ms(statistics.median(full))}, ratio {ratio:.3f}")
    assert ratio <= RATIO_MAX


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[int(0.95 * len(ordered)) - 1]


@pytest.mark.perf
def test_ac33_full_timeline_p95_on_the_reference_machine(tmp_path):
    zero, full = interleaved(tmp_path, WARMUP, RUNS)
    p0, p100 = _p95(zero), _p95(full)
    print(f"\nAC-F14-33 on {cpu_name()}: take_checkpoint p95 depth 0 {_ms(p0)}, depth 100 "
          f"(full timeline) {_ms(p100)}, ratio {p100 / p0:.3f}; medians "
          f"{_ms(statistics.median(zero))} / {_ms(statistics.median(full))}")
    assert p100 <= RATIO_MAX * p0


# --- AC-F14-34 — one step fits in a frame (CI guard) ---------------------------------------------

def test_ac34_ci_guard_one_restore_or_one_rerun_per_step(steps100, monkeypatch):
    _, program = steps100
    interp = launched(program, rollback_steps=DEPTH)
    interp.new_game(1)
    interp.run(10_000)
    for _ in range(gen_steps.LINES - 1):
        step(interp)
    interp.take_commands(1 << 30)
    assert interp.current.text == LAST and len(interp.timeline.states) == DEPTH + 1
    calls = {"restore": 0, "rerun": 0}
    real_restore, real_once = Interpreter.restore, Interpreter._forward_once

    def restore(self, *args, **kwargs):
        calls["restore"] += 1
        return real_restore(self, *args, **kwargs)

    def forward_once(self):
        calls["rerun"] += 1
        return real_once(self)

    monkeypatch.setattr(Interpreter, "restore", restore)
    monkeypatch.setattr(Interpreter, "_forward_once", forward_once)
    timed: dict[str, list[float]] = {"back": [], "forward": []}
    for kind, go, expect in (("back", back, {"restore": 1, "rerun": 0}),
                             ("forward", forward, {"restore": 0, "rerun": 1})):
        for _ in range(STEPS):
            calls.update(restore=0, rerun=0)
            began = time.perf_counter()
            go(interp)
            timed[kind].append(time.perf_counter() - began)
            assert calls == expect, kind
        n = gen_steps.LINES - (STEPS if kind == "back" else 0)
        assert interp.status is Status.WAITING and interp.current.text == f"Line {n}."
    back_ms, fwd_ms = (statistics.median(timed[k]) for k in ("back", "forward"))
    print(f"AC-F14-34 headless medians: back {_ms(back_ms)}, forward {_ms(fwd_ms)}")
    assert back_ms <= STEP_MEDIAN_MAX_S and fwd_ms <= STEP_MEDIAN_MAX_S


# --- AC-F14-35 — spinning the wheel (CI count) ---------------------------------------------------

@pytest.mark.display
def test_ac35_ci_count_one_post_and_one_restore_per_frame(tmp_path, scripted_app, unthreaded,
                                                          monkeypatch):
    text = gen_steps.script({f"v{i}": i for i in range(8)})
    game = k_game(tmp_path, "\n[title]\nenabled = false\n", text=text)
    posts: list[tuple[int, object]] = []
    restores: list[int] = []
    out_ref: dict = {}
    real_post, real_restore = RuntimeStoryDriver.post, Interpreter.restore

    def post(self, event):
        if type(event) in (StepBack, StepForward):
            posts.append((out_ref["out"]["frame"], event))
        return real_post(self, event)

    def restore(self, *args, **kwargs):
        restores.append(out_ref["out"]["frame"])
        return real_restore(self, *args, **kwargs)

    monkeypatch.setattr(RuntimeStoryDriver, "post", post)
    monkeypatch.setattr(Interpreter, "restore", restore)

    def to_last(app):
        for _ in range(4 * gen_steps.LINES):
            if line(app) == LAST and app.story.status is Status.WAITING:
                return
            if line(app) is not None and app.story.status is Status.WAITING:
                post_key(pygame.K_SPACE)
            yield
            yield
        raise AssertionError("never reached the last line")

    def script(app, out):
        out_ref["out"] = out
        res: dict = {}
        out["res"] = res
        yield from started(app)
        yield from to_last(app)
        for y in (1, -1):                                  # back, then forward
            since = out["frame"]
            for n in range(SPIN_NOTCHES * SPIN_EVERY):
                if n % SPIN_EVERY == 0:
                    wheel(y)
                yield
            last = out["frame"]                            # the frame after the last notch
            for _ in range(5):
                yield
            res[y] = (since, last, line(app))
        since = out["frame"]
        for _ in range(5):                                 # five notches in one frame
            wheel(1)
        for _ in range(5):
            yield
        res[5] = (since, line(app))

    res = run(scripted_app, game, script, last=3000)["res"]
    per_frame: dict[int, int] = {}
    for frame, _ in posts:
        per_frame[frame] = per_frame.get(frame, 0) + 1
    assert max(per_frame.values()) == 1
    assert max(restores.count(f) for f in set(restores)) == 1
    first, last, shown = res[1]
    spin_back = [e for f, e in posts if first <= f <= last]
    assert spin_back == [StepBack(1)] * SPIN_NOTCHES
    assert shown == f"Line {gen_steps.LINES - SPIN_NOTCHES}."
    first, last, shown = res[-1]
    assert [e for f, e in posts if first <= f <= last] == [StepForward(1)] * SPIN_NOTCHES
    assert shown == LAST
    since, shown = res[5]
    assert [e for f, e in posts if f >= since] == [StepBack(5)]
    assert len([f for f in restores if f >= since]) == 1
    assert shown == f"Line {gen_steps.LINES - 5}."


# --- AC-F14-36 — memory for the default depth (slow) ---------------------------------------------

@pytest.mark.slow
def test_ac36_timeline_memory_at_depth_100(steps100):
    _, program = steps100
    interp = launched(program, rollback_steps=DEPTH)
    gc.collect()
    tracemalloc.start()
    try:
        interp.new_game(1)
        interp.run(10_000)
        interp.take_commands(1 << 30)
        gc.collect()
        first = tracemalloc.get_traced_memory()[0]
        for _ in range(gen_steps.LINES - 1):
            step(interp)
            interp.take_commands(1 << 30)
        gc.collect()
        full = tracemalloc.get_traced_memory()[0]
        timeline = interp.timeline
        assert interp.current.text == LAST and len(timeline.states) == DEPTH + 1
        timeline.reset(interp.checkpoint())               # keep only the current step
        gc.collect()
        cut = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    held = full - cut
    mib = 1024 * 1024
    print(f"AC-F14-36: the depth-100 timeline holds {held / mib:.1f} MiB "
          f"({held / DEPTH / 1024:.0f} KiB per step); growth over 100 lines "
          f"{(full - first) / mib:.1f} MiB")
    assert held <= MEMORY_MAX


# --- AC-F14-34, 35 and I-11 on the reference machine (perf) --------------------------------------

def _press(key: int) -> None:
    """One press: down, then up (a second KEYDOWN while down is a held key)."""
    post_key(key)
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="",
                                         scancode=0))


def _line(app) -> str | None:
    box = getattr(app, "textbox", None)
    return None if box is None or box.line is None else box.line.text


class Bench:
    """What the bench launch recorded: ``steps`` (kind, input frame, line after),
    ``spins`` (direction, first frame, last frame, line after), ``bulk`` (kind, input
    frame), ``resets`` (frame, seconds, states released), ``gen2`` (frame, seconds)."""

    def __init__(self) -> None:
        self.probe: Probe | None = None
        self.code: int | None = None
        self.error: BaseException | None = None
        self.steps: list[tuple[str, int, str | None]] = []
        self.spins: list[tuple[int, int, int, str | None]] = []
        self.bulk: list[tuple[str, int]] = []
        self.resets: list[tuple[int, float, int]] = []
        self.gen2: list[tuple[int, float]] = []

    def window(self, first: int, frames: int = STEP_FRAMES) -> list[float]:
        return [w for _, _, _, w in self.probe.window(first, first + frames - 1)]

    def gen2_in(self, first: int, last: int) -> str:
        """The gen-2 collections that ran in frames ``first`` to ``last``."""
        times = [s for f, s in self.gen2 if first <= f <= last]
        return f"{len(times)}" + (f" (max {_ms(max(times))})" if times else "")


def _bench_script(probe: Probe, bench: Bench):
    """One frame per ``yield`` (called at each frame start, inside the frame's work)."""
    app = probe.app

    def to_line(n: int):
        want = f"Line {n}."
        for _ in range(10 * gen_steps.LINES):
            if probe.line_ready() and _line(app) == want:
                return
            if probe.line_ready():
                _press(pygame.K_SPACE)
            yield
            yield
        raise AssertionError(f"never reached {want}")

    yield from to_line(1)
    saved = json.loads(json.dumps(app.story.checkpoint().to_json()))   # a save of line 1
    loaded = GameState.from_json(saved)
    yield from to_line(gen_steps.LINES)
    for _ in range(30):                                    # settle before measuring
        yield
    for kind, key in (("back", pygame.K_PAGEUP), ("forward", pygame.K_PAGEDOWN)):
        for _ in range(STEPS):
            frame = probe.frame
            _press(key)
            for _ in range(STEP_FRAMES):
                yield
            bench.steps.append((kind, frame, _line(app)))
    for y in (1, -1):
        first = probe.frame
        for n in range(SPIN_NOTCHES * SPIN_EVERY):
            if n % SPIN_EVERY == 0:
                wheel(y)
            yield
        last = probe.frame - 1
        for _ in range(30):
            yield
        bench.spins.append((y, first, last, _line(app)))
    assert len(app.story.interp.timeline.states) == DEPTH + 1
    bench.bulk.append(("load", probe.frame))
    assert app.story.restore(loaded).result.value == "ok"
    for _ in range(STEP_FRAMES + 20):
        yield
    yield from to_line(gen_steps.LINES)
    for _ in range(30):
        yield
    assert len(app.story.interp.timeline.states) == DEPTH + 1
    bench.bulk.append(("new game", probe.frame))
    app.story.new_game()
    for _ in range(STEP_FRAMES + 20):
        yield
    assert _line(app) == "Line 1."


@pytest.fixture(scope="module")
def bench(steps100, tmp_path_factory) -> Bench:
    """One launch of ``steps100`` running ``_bench_script`` (about 30 s)."""
    root, _ = steps100
    game = tmp_path_factory.mktemp("bench") / "game"
    game.mkdir()
    (game / "script").mkdir()
    (game / "script" / "main.vns").write_text(
        (root / "script" / "main.vns").read_text(encoding="utf-8"), encoding="utf-8")
    (game / "config.toml").write_text(BENCH_CONFIG, encoding="utf-8")
    result = Bench()
    state: dict = {}

    def on_frame(probe: Probe) -> None:
        if state.get("done"):
            return
        if "gen" not in state:
            state["gen"] = _bench_script(probe, result)
        try:
            next(state["gen"])
        except StopIteration:
            state["done"] = True
            probe.stop_frame = probe.frame + 3
        except Exception as e:                       # never hang or crash the launch
            result.error = e
            state["done"] = True
            probe.stop_frame = probe.frame + 3

    real_reset = Timeline.reset
    frame_of = {"probe": None}

    def reset(self, state_):
        began = time.perf_counter()
        released = len(self.states)
        real_reset(self, state_)
        probe = frame_of["probe"]
        result.resets.append((probe.frame if probe else -1, time.perf_counter() - began,
                              released))

    gen2_start: list[float] = []

    def on_gc(phase: str, info: dict) -> None:
        if info.get("generation") != 2:
            return
        if phase == "start":
            gen2_start.append(time.perf_counter())
        elif gen2_start:
            probe = frame_of["probe"]
            result.gen2.append((probe.frame if probe else -1,
                                time.perf_counter() - gen2_start.pop()))

    def hook(probe: Probe) -> None:
        frame_of["probe"] = probe
        on_frame(probe)

    gc.callbacks.append(on_gc)
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Timeline, "reset", reset)
            result.code, result.probe = run_game(game, hook, limit_s=180)
    finally:
        gc.callbacks.remove(on_gc)
    return result


def _video() -> str:
    return os.environ.get("SDL_VIDEODRIVER", "") or "default"


def _summary(works: list[float]) -> str:
    return (f"p99 {_ms(_p99(works))}, median {_ms(statistics.median(works))}, "
            f"max {_ms(max(works))} over {len(works)} frames")


@pytest.mark.perf
def test_ac34_every_frame_of_a_step_on_the_reference_machine(bench):
    assert bench.error is None, repr(bench.error)
    assert bench.code == 0
    lines = [shown for _, _, shown in bench.steps]
    assert lines == ([f"Line {gen_steps.LINES - n}." for n in range(1, STEPS + 1)]
                     + [f"Line {gen_steps.LINES - STEPS + n}." for n in range(1, STEPS + 1)])
    worst = {}
    for kind in ("back", "forward"):
        windows = [bench.window(frame) for k, frame, _ in bench.steps if k == kind]
        worst[kind] = [max(w) for w in windows]
        assert all(len(w) == STEP_FRAMES for w in windows)
    print(f"\nAC-F14-34 on {cpu_name()} (video {_video()}): worst frame of each step's "
          f"{STEP_FRAMES} frames: back max {_ms(max(worst['back']))}, median "
          f"{_ms(statistics.median(worst['back']))}; forward max "
          f"{_ms(max(worst['forward']))}, median {_ms(statistics.median(worst['forward']))}; "
          f"gen-2 GC in the steps "
          f"{bench.gen2_in(bench.steps[0][1], bench.steps[-1][1] + STEP_FRAMES - 1)}")
    assert max(worst["back"]) <= FRAME_WORK_MAX_S
    assert max(worst["forward"]) <= FRAME_WORK_MAX_S


@pytest.mark.perf
def test_ac35_wheel_spin_on_the_reference_machine(bench):
    assert bench.error is None, repr(bench.error)
    (y1, first1, last1, shown1), (y2, first2, last2, shown2) = bench.spins
    assert (y1, shown1) == (1, f"Line {gen_steps.LINES - SPIN_NOTCHES}.")
    assert (y2, shown2) == (-1, LAST)
    frames = bench.probe.window(first1, last1 + 1) + bench.probe.window(first2, last2 + 1)
    works = [w for _, _, _, w in frames]
    intervals = [i for _, _, i, _ in frames if i > 0]
    fps = bench.probe.app.config.engine.fps
    long_frames = sum(i > 1.5 / fps for i in intervals)
    share = long_frames / max(1, len(intervals))
    print(f"\nAC-F14-35 on {cpu_name()} (video {_video()}): {SPIN_NOTCHES} notches back and "
          f"{SPIN_NOTCHES} forward at 30/s; frame work {_summary(works)}; long frames "
          f"{long_frames} ({100 * share:.2f}%); gen-2 GC in the spin "
          f"{bench.gen2_in(first1, last2 + 1)}")
    assert _p99(works) <= FRAME_WORK_MAX_S
    assert share <= LONG_SHARE_MAX


@pytest.mark.perf
def test_i11_load_and_new_game_with_a_full_timeline(bench):
    assert bench.error is None, repr(bench.error)
    assert [kind for kind, _ in bench.bulk] == ["load", "new game"]
    parts = []
    worst = []
    for kind, frame in bench.bulk:
        works = bench.window(frame)
        released = [(s, n) for f, s, n in bench.resets if f == frame]
        assert released and released[0][1] == DEPTH + 1, (kind, released)
        gen2 = [s for f, s in bench.gen2 if frame <= f < frame + STEP_FRAMES]
        worst.append(max(works))
        parts.append(f"{kind}: {DEPTH + 1} states released in {_ms(released[0][0])}, worst "
                     f"frame {_ms(max(works))} (input frame {_ms(works[0])}), gen-2 GC in "
                     f"the window {len(gen2)} ({_ms(sum(gen2))})")
    all_gen2 = [s for _, s in bench.gen2]
    print(f"\nI-11 on {cpu_name()} (video {_video()}): " + "; ".join(parts)
          + f"; gen-2 GC over the run: {len(all_gen2)}, max "
          + (_ms(max(all_gen2)) if all_gen2 else "-")
          + ", at frames " + ", ".join(f"{f} ({_ms(s)})" for f, s in bench.gen2))
    assert max(worst) <= FRAME_WORK_MAX_S
