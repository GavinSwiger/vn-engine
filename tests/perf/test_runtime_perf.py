"""F03 performance (checklist step 15; ``04-technical.md`` §10, §14; 06-acceptance §1.13,
§5.7): AC-F03-77, 78, 79 on the reference machine (``perf``), with their CI guards.

AC-F03-76 (the snapshot) is in ``tests/runtime/test_snapshot_perf.py``. Fixtures:
``tests/fixtures/F03/perf/gap1000/`` (AC-77) and ``perf/defines200/`` (AC-79); AC-78 uses
``runaway/shop.vns``.

**CI guards (default tier).** Each is a count or a loose limit: the gap fixture has exactly
1,000 steps between lines and the AC's mix of statements; 1,000 steps and a line take at most
one 16 ms frame headless (median of 20 gaps; about 1 ms here); the defines fixture has 150
``Character`` defines and 50 others, and launches in at most 1 s in process. AC-78's CI form
is AC-F03-13 (``tests/runtime/test_interpreter_flow.py``: every pump ≤ 50 ms, E45 on the
error screen within 10 s).

**Reference-machine run (owner).** ADR-0005: Intel Core i5-8250U, Windows 11, mains power,
"Balanced" plan; or a stand-in with integrated graphics and a PassMark single-thread score of
at most 2,000. AC-77 and AC-78 launch the game in process (``bootstrap.launch``, real
``GameWindow`` and frame limiter, a dev run, 60 fps, 1280×720, ``[textbox] cps = 0`` so
every Space press is an advance). Set a real video driver, or ``tests/conftest.py`` picks
SDL's dummy driver and the window (and the cost of ``flip``) isn't real::

    set VN_PERF=1
    set SDL_VIDEODRIVER=windows
    .venv/Scripts/python -m pytest -m perf -s tests/perf/test_runtime_perf.py ^
        tests/runtime/test_snapshot_perf.py

(``set`` and ``^`` are cmd's; in PowerShell use ``$env:VN_PERF = "1"`` and one line.) Attach the printed ``AC-F03-7x`` lines and the machine's PassMark single-thread score to the
test report (06 §0.3, §7). AC-77 plays for about 35 s and AC-78 for about 2 s. Don't touch
the window while they run. The 10,000-case state fuzz (AC-F03-64) is ``slow``:
``.venv/Scripts/python -m pytest -m slow tests/runtime/test_state_json.py
tests/runtime/test_restore.py -k fuzz``.

**Manual (owner).** AC-F03-82: ``.venv/Scripts/python -m tests.perf.ac82_game DEST`` makes
the game copy and prints the steps (docstring of ``tests/perf/ac82_game.py``). The rest of
the 06 §6 playtest (about 10 minutes) is run by hand on Windows 11, with steps 1, 6, and 9
repeated on macOS and Linux X11.
"""

import os
import shutil
import statistics
import time
from collections import Counter
from pathlib import Path

import pygame
import pytest

from engine.core.paths import GamePaths
from engine.runtime import limits
from engine.runtime.commands import Advance, Say, StoryEnded, StoryFailed
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import EXECUTORS, Interpreter, Status
from engine.runtime.launch import run_launch
from engine.script import load_story
from engine.script.nodes import Call, If, Jump, PythonLine, Return
from tests.perf.launch_process import measure
from tests.script.load_process import cpu_name

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F03"
GAP = FIXTURES / "perf" / "gap1000"
DEFINES = FIXTURES / "perf" / "defines200"
CONFIG = ('[game]\ntitle = "Perf"\nversion = "0.1.0"\n[title]\nenabled = false\n'
          "[textbox]\ncps = 0\n")
GAP_LINES = 200                  # advances from "Start." that each lead to a line
FRAME_WORK_MAX_S = 0.016         # ADR-0005: frame-work p99 ≤ 16.0 ms


def _program(root: Path, fixture: Path):
    shutil.copytree(fixture, root / "script")
    result = load_story(GamePaths(root.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    assert not result.warnings, [w.format() for w in result.warnings]
    return result.program


def _game(parent: Path, script: Path | str) -> Path:
    """A game folder: the perf ``config.toml`` and ``script/`` (a fixture folder or the
    text of ``main.vns``)."""
    root = parent / "game"
    root.mkdir()
    (root / "config.toml").write_text(CONFIG, encoding="utf-8")
    if isinstance(script, Path):
        shutil.copytree(script, root / "script")
    else:
        (root / "script").mkdir()
        (root / "script" / "main.vns").write_text(script, encoding="utf-8")
    return root


def _p99(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, -(-len(ordered) * 99 // 100) - 1)]


def _says(commands) -> int:
    return sum(type(c) is Say for c in commands)


# --- AC-F03-77: fixture shape and CI guard -------------------------------------------------

def test_ac77_gap_fixture_has_exactly_1000_steps_between_lines(tmp_path, monkeypatch):
    program = _program(tmp_path, GAP)
    monkeypatch.setattr(limits, "STEP_LIMIT", 1000)
    commands = run_headless(program, seed=1, max_lines=6)       # "Start." and 5 gaps
    assert _says(commands) == 6 and not any(type(c) is StoryFailed for c in commands)
    monkeypatch.setattr(limits, "STEP_LIMIT", 999)
    commands = run_headless(program, seed=1)
    assert _says(commands) == 1 and commands[-1].error.code == "E45"


def test_ac77_gap_fixture_mix_of_one_gap(tmp_path, monkeypatch):
    """One gap runs 600 ``$`` lines, 200 conditions, 100 jumps, and 50 call/return pairs."""
    program = _program(tmp_path, GAP)
    interp = Interpreter(program, run_launch(program).namespace)
    interp.new_game(1)
    interp.run(10_000)
    assert interp.status is Status.WAITING
    ran: Counter = Counter()
    for kind in (PythonLine, If, Jump, Call, Return):
        run = EXECUTORS[kind]
        monkeypatch.setitem(EXECUTORS, kind,
                            lambda i, s, run=run, kind=kind: (ran.update([kind]), run(i, s))[1])
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.status is Status.WAITING and interp.current.text == "Line."
    assert ran == {PythonLine: 600, If: 200, Jump: 100, Call: 50, Return: 50}


def test_ac77_ci_guard_1000_steps_and_a_line_within_one_frame(tmp_path):
    program = _program(tmp_path, GAP)
    interp = Interpreter(program, run_launch(program).namespace)
    interp.new_game(1)
    interp.run(10_000)
    gaps = []
    for _ in range(20):
        began = time.perf_counter()
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        gaps.append(time.perf_counter() - began)
        assert interp.status is Status.WAITING
    median = statistics.median(gaps)
    print(f"AC-F03-77 headless gap median: {median * 1000:.3f} ms")
    assert median <= FRAME_WORK_MAX_S


# --- AC-F03-79: fixture shape and CI guard -------------------------------------------------

def test_ac79_defines_fixture_shape_and_ci_guard(tmp_path):
    program = _program(tmp_path, DEFINES)
    kinds = Counter("Character" if d.value.source.startswith("Character(") else "other"
                    for d in program.defines)
    assert kinds == {"Character": 150, "other": 50}
    assert len(program.speakers) == 150
    times = []
    for _ in range(3):
        began = time.perf_counter()
        result = run_launch(program)
        times.append(time.perf_counter() - began)
        assert result.namespace is not None and not result.errors and not result.warnings
    assert statistics.median(times) <= 1.0


@pytest.mark.perf
def test_ac79_200_defines_launch_in_a_tenth_of_a_second(tmp_path):
    root = _game(tmp_path, DEFINES)
    median, runs = measure(root)
    times = ", ".join(f"{r['seconds'] * 1000:.2f}" for r in runs)
    print(f"\nAC-F03-79 on {cpu_name()}: launch median {median * 1000:.2f} ms ({times} ms)")
    for run in runs:
        assert run["launched"] and run["defines"] == 200
        assert run["errors"] == [] and run["warnings"] == []
    assert median <= 0.1


# --- The app in process (AC-F03-77, 78) ------------------------------------------------------

class Probe:
    """What one in-process launch did, frame by frame. ``frames``: (frame, start, interval,
    work) as ``App.run`` measures them (ADR-0005); ``advances``: (frame, time) of each
    ``Advance`` the driver received; ``commands``: (frame, type, command) of each ``Say``,
    ``StoryEnded``, and ``StoryFailed`` the router dispatched."""

    def __init__(self, on_frame, limit_s: float) -> None:
        self.on_frame = on_frame
        self.limit_s = limit_s
        self.app = None
        self.frame = 0
        self.start = 0.0
        self.began = time.perf_counter()
        self.frames: list[tuple[int, float, float, float]] = []
        self.advances: list[tuple[int, float]] = []
        self.commands: list[tuple[int, type, object]] = []
        self.presses = 0
        self.next_press: int | None = None
        self.stop_frame: int | None = None

    def line_ready(self) -> bool:
        from engine.ui.builtin.textbox_screen import TextboxScreen

        app = self.app
        story = app.story
        return (story is not None and story.status is Status.WAITING
                and isinstance(app.screens.top, TextboxScreen)
                and app.screens.top.indicator_kind() == "line")

    def frame_started(self) -> None:
        from tests.fakes.loop import post_quit

        if self.stop_frame is not None and self.frame >= self.stop_frame:
            post_quit()
            post_quit()             # F10: the first close may ask in game, the second quits
            return
        if time.perf_counter() - self.began > self.limit_s:
            self.stop_frame = self.frame                            # never hang the suite
            return
        self.on_frame(self)

    def press_every(self, frames: int) -> None:
        """A Space press once the line is ready, then every ``frames`` frames."""
        from tests.fakes.loop import post_key

        if self.next_press is None:
            if not self.line_ready():
                return
            self.next_press = self.frame
        if self.frame >= self.next_press:
            post_key(pygame.K_SPACE)
            self.presses += 1
            self.next_press = self.frame + frames

    def window(self, first: int, last: int) -> list[tuple[int, float, float, float]]:
        return [f for f in self.frames if first <= f[0] <= last]


def run_game(game: Path, on_frame, *, limit_s: float) -> tuple[int, Probe]:
    """``bootstrap.launch`` of ``game`` (dev run, real clock, limiter, and window), with
    ``on_frame(probe)`` called at each frame start, before the frame's events are read."""
    from engine.app import bootstrap
    from engine.app.app import App
    from engine.app.dispatch import CommandRouter
    from engine.app.story import RuntimeStoryDriver

    probe = Probe(on_frame, limit_s)

    class ProbeApp(App):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            probe.app = self
            real_wait = self._limiter.wait
            real_record = self.recent.record

            def wait():
                start = real_wait()
                probe.frame += 1
                probe.start = start
                probe.frame_started()
                return start

            def record(interval, work):
                probe.frames.append((probe.frame, probe.start, interval, work))
                real_record(interval, work)

            self._limiter.wait = wait
            self.recent.record = record

    real_post = RuntimeStoryDriver.post
    real_dispatch = CommandRouter.dispatch

    def post(self, event):
        if type(event) is Advance:
            probe.advances.append((probe.frame, time.perf_counter()))
        return real_post(self, event)

    def dispatch(self, command):
        if type(command) in (Say, StoryEnded, StoryFailed):
            probe.commands.append((probe.frame, type(command), command))
        return real_dispatch(self, command)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(bootstrap, "App", ProbeApp)
        mp.setattr(RuntimeStoryDriver, "post", post)
        mp.setattr(CommandRouter, "dispatch", dispatch)
        code = bootstrap.launch(game, release=False, bench_seconds=None,
                                log_level_override=None, pygame_warning=None)
    return code, probe


def _video() -> str:
    return os.environ.get("SDL_VIDEODRIVER", "")


# --- AC-F03-77: the next line comes in the same frame ---------------------------------------

def _gap_frame(probe: Probe) -> None:
    if any(kind is not Say for _, kind, _ in probe.commands):
        probe.stop_frame = probe.frame + 3                      # ended (or failed)
        return
    probe.press_every(10)


@pytest.mark.perf
def test_ac77_next_line_in_the_same_frame(tmp_path):
    code, probe = run_game(_game(tmp_path, GAP), _gap_frame, limit_s=120)
    says = [(frame, cmd) for frame, kind, cmd in probe.commands if kind is Say]
    kinds = [kind for _, kind, _ in probe.commands]
    assert code == 0
    assert StoryFailed not in kinds and kinds[-1] is StoryEnded
    assert len(says) == GAP_LINES + 1 and len(probe.advances) == GAP_LINES + 1
    late = [(k + 1, adv, say) for k, ((adv, _), (say, _)) in
            enumerate(zip(probe.advances, says[1:])) if adv != say]
    first, last = probe.advances[0][0], says[-1][0]
    work = [w for _, _, _, w in probe.window(first, last)]
    p99 = _p99(work)
    print(f"\nAC-F03-77 on {cpu_name()} (video {_video() or 'default'}): "
          f"{GAP_LINES} advances, {len(late)} lines in a later frame; frame work over "
          f"{len(work)} frames: p99 {p99 * 1000:.2f} ms, median "
          f"{statistics.median(work) * 1000:.2f} ms, max {max(work) * 1000:.2f} ms")
    assert late == [], late[:5]
    assert p99 <= FRAME_WORK_MAX_S


# --- AC-F03-78: a runaway loop costs a bounded slice -----------------------------------------

def _runaway_frame(probe: Probe) -> None:
    if any(kind is StoryFailed for _, kind, _ in probe.commands):
        probe.stop_frame = probe.frame + 3
        return
    if probe.presses == 0:
        probe.press_every(10_000)


@pytest.mark.perf
def test_ac78_runaway_loop_costs_a_bounded_slice(tmp_path):
    shop = (FIXTURES / "runaway" / "shop.vns").read_text(encoding="utf-8")
    code, probe = run_game(_game(tmp_path, shop), _runaway_frame, limit_s=30)
    failed = [(frame, cmd) for frame, kind, cmd in probe.commands if kind is StoryFailed]
    assert code == 1 and len(probe.advances) == 1 and len(failed) == 1
    (adv_frame, adv_time), (fail_frame, cmd) = probe.advances[0], failed[0]
    assert cmd.error.code == "E45"
    loop = probe.window(adv_frame, fail_frame)
    (_, start, _, work) = loop[-1]
    shown_after = start + work - adv_time          # the error screen's flip, after the Advance
    works = [w for _, _, _, w in loop]
    intervals = [i for _, _, i, _ in loop[1:]]
    fps = probe.app.config.engine.fps
    long_frames = sum(i > 1.5 / fps for i in intervals)
    p99 = _p99(works)
    print(f"\nAC-F03-78 on {cpu_name()} (video {_video() or 'default'}): E45 shown "
          f"{shown_after:.3f} s after the Advance, {len(loop)} frames; frame work p99 "
          f"{p99 * 1000:.2f} ms, max {max(works) * 1000:.2f} ms; long frames {long_frames} "
          f"({100 * long_frames / max(1, len(intervals)):.2f}%)")
    assert shown_after <= 2.0
    assert p99 <= FRAME_WORK_MAX_S
    assert long_frames <= 0.005 * len(intervals)


# --- AC-F03-82 (manual): the game copy ----------------------------------------------------

def test_ac82_game_copy_has_the_stuck_line_after_the_first_line(tmp_path):
    from tests.perf.ac82_game import ROOT, STUCK, _load, first_line, make

    dest = tmp_path / "ac82"
    path, line = make(dest)
    assert path.read_text(encoding="utf-8").splitlines()[line - 1].strip() == STUCK
    program = _load(dest).program
    assert first_line(program).end_line == line - 1        # right after the first line
    shipped = ROOT / "game" / path.relative_to(dest)
    assert STUCK not in shipped.read_text(encoding="utf-8")     # game/ is untouched
