"""The F04 bench harness (``04-technical.md`` §14 "Perf"; ``06-acceptance.md`` AC-F04-48, 49, D1).

- ``StageBenchHarness``: called at every frame start; once the story runs, it posts
  ``Advance(current sid)`` every ``advance_s`` seconds (None: a static run), or at a menu
  (F07, the example game) ``Choose`` of its first pickable choice, or at a story wait (F09
  transitions and pauses, F18 cards) the stage's ``press`` as Space does, and records each frame
  start, each stage compose (with its time), and the bench lines.
- ``bench_launch``: runs ``bootstrap.launch`` in process with the real clock and frame limiter
  and the harness (the App's ``bootstrap.App`` is swapped for one whose limiter calls the
  harness). The window is the real one: set ``SDL_VIDEODRIVER`` to a real driver.
- ``spy_compose``: wraps ``StageView._compose`` to time it. The engine logs no compose time
  (``04`` §14 says DEBUG); the harness measures it instead.
- ``check_bench_game``: the headless check AC-F04-48 runs before the bench.
- ``long_frames_after`` and ``parse_bench``: the report.

The same ``on_frame`` runs under ``scripted_app`` (fake clock) in the CI guards
(``scripted_play``). F05's typing bench (``test_text_bench.py``) subclasses the harness.
"""

import bisect
import contextlib
import logging
import platform
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app.app import App
from engine.core.config import load_config
from engine.core.imageheader import image_dimensions
from engine.core.paths import GamePaths
from engine.core.timing import FrameLimiter
from engine.minigames.screen import MinigameScreen
from engine.render.stage import StageView
from engine.runtime.commands import Advance, Choose, Say, ShowStage
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Status
from engine.runtime.stage import StageState
from engine.script.menu import Menu

LONG_FRAME_S = 0.025                    # ADR-0005: 1.5 × the 60 fps frame period
AFTER_CHANGE_S = 1.0                    # AC-F04-48 report, AC-F04-49


@dataclass
class Compose:
    frame_start: float                  # the start of the frame that composed
    ms: float
    generation: int
    stage: StageState
    size: tuple[int, int]


@dataclass
class StageBenchHarness:
    advance_s: float | None             # None: static (no Advance)
    frames: list[float] = field(default_factory=list)
    composes: list[Compose] = field(default_factory=list)
    bench_lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    posts: int = 0
    story_started: float | None = None   # the first frame with the story running
    ended_at: float | None = None        # the first frame with the story ENDED
    driver: str | None = None            # SDL's video driver during the run
    window: tuple[int, int] | None = None   # the window size at the first frame
    _next_post: float | None = None
    _frame_start: float = 0.0

    def on_frame(self, app: App, now: float) -> None:
        """At each frame start, before the frame's events and story pump."""
        self.frames.append(now)
        self._frame_start = now
        if self.driver is None:
            self.driver = pygame.display.get_driver()
            self.window = tuple(app.window.size)
        story = app.story
        if story is None or app.loading:
            return
        if self.story_started is None:
            self.story_started = now
            if self.advance_s is not None:
                self._next_post = now + self.advance_s
        status = story.status
        if status is Status.ENDED and self.ended_at is None:
            self.ended_at = now
        if (self._next_post is not None and now >= self._next_post
                and status is Status.WAITING):
            interp = story.interp
            current = interp.current
            if isinstance(app.screens.top, MinigameScreen):   # F24–F26: the dev test outcome,
                pygame.event.post(pygame.event.Event(       # as the headless run plays it
                    pygame.KEYDOWN, key=pygame.K_F8, mod=pygame.KMOD_SHIFT, unicode="",
                    scancode=0))
            elif interp.waiting_for is not None:   # F09/F18: a story wait ends as Space
                app.stage_screen.press()           # ends it (no Advance during a wait)
            elif type(current) is Menu:            # F07: the first pickable choice
                story.post(Choose(current.sid, interp.choices.waiting.pickable[0]))
            else:
                story.post(Advance(current.sid))
            self.posts += 1
            while self._next_post <= now:
                self._next_post += self.advance_s

    # --- the report ------------------------------------------------------------------------

    def changes(self) -> list[Compose]:
        """The composes of a new stage (a new ``generation``): one per presented
        ``ShowStage`` (a resize or quality change recomposes the same generation)."""
        out, last = [], None
        for compose in self.composes:
            if compose.generation != last:
                out.append(compose)
                last = compose.generation
        return out

    def long_after_changes(self) -> list[int]:
        return long_frames_after(self.frames, [c.frame_start for c in self.changes()])


def long_frames_after(frames: list[float], changes: list[float], *,
                      within_s: float = AFTER_CHANGE_S,
                      long_s: float = LONG_FRAME_S) -> list[int]:
    """For each change (the start of the frame that presented it), the number of frame
    intervals longer than ``long_s`` among the frames starting in ``(change, change +
    within_s]``. The interval of frame i is ``frames[i] - frames[i - 1]``, so the frame
    after the change carries the compose."""
    out = []
    for change in changes:
        first = max(1, bisect.bisect_right(frames, change))
        last = bisect.bisect_right(frames, change + within_s)
        out.append(sum(1 for i in range(first, last) if frames[i] - frames[i - 1] > long_s))
    return out


@contextlib.contextmanager
def spy_compose(harness: StageBenchHarness, mp) -> Iterator[None]:
    real = StageView._compose

    def compose(self, canvas):
        started = time.perf_counter()
        real(self, canvas)
        ms = (time.perf_counter() - started) * 1000.0
        harness.composes.append(Compose(harness._frame_start, ms, self.generation,
                                        self.stage, canvas.surface.get_size()))

    mp.setattr(StageView, "_compose", compose)
    yield


class _Records(logging.Handler):
    def __init__(self, harness: StageBenchHarness) -> None:
        super().__init__(logging.DEBUG)
        self.harness = harness

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if record.name == "vn.loop" and message.startswith("Bench "):
            self.harness.bench_lines.append(message)
        elif record.levelno >= logging.WARNING:
            self.harness.warnings.append(f"{record.levelname} {record.name}: {message}")


@contextlib.contextmanager
def capture_logs(harness: StageBenchHarness) -> Iterator[None]:
    handler = _Records(harness)
    root = logging.getLogger("vn")
    root.addHandler(handler)
    try:
        yield
    finally:
        root.removeHandler(handler)


class _HarnessLimiter(FrameLimiter):
    def __init__(self, fps: int, on_start) -> None:
        super().__init__(fps)
        self._on_start = on_start

    def wait(self) -> float:
        now = super().wait()
        self._on_start(now)
        return now


def bench_launch(game: Path, harness: StageBenchHarness, *, seconds: float,
                 seed: int = 1) -> int:
    """``bootstrap.launch(game, --bench seconds, --seed seed)`` in process, with the real
    clock, limiter, and window; ``harness`` sees every frame start. Returns the exit code."""

    class BenchApp(App):
        def __init__(self, **kwargs):
            fps = kwargs["config"].engine.fps
            super().__init__(**kwargs,
                             limiter=_HarnessLimiter(fps, lambda now: harness.on_frame(self, now)))

    with contextlib.ExitStack() as stack:
        mp = stack.enter_context(pytest.MonkeyPatch.context())
        mp.setattr(bootstrap, "App", BenchApp)
        stack.enter_context(spy_compose(harness, mp))
        stack.enter_context(capture_logs(harness))
        return bootstrap.launch(game, release=False, bench_seconds=seconds,
                                log_level_override="info", pygame_warning=None, seed=seed)


def scripted_play(session, game: Path, harness: StageBenchHarness, *, frames: int) -> int:
    """``launch(game)`` in process on the fake clock (the ``scripted_app`` session) for
    ``frames`` frames, ``harness`` called at the start of each (the CI guards)."""
    for frame in range(1, frames):
        session.at(frame, lambda app: harness.on_frame(app, app._clock()))
    session.quit_frame = frames
    with pytest.MonkeyPatch.context() as mp:
        with spy_compose(harness, mp), capture_logs(harness):
            return bootstrap.launch(game, release=False, bench_seconds=None,
                                    log_level_override=None, pygame_warning=None, seed=1)


# --- bench lines (F01 04 §7.5.3) -----------------------------------------------------------

def parse_bench(lines: list[str]) -> dict:
    """The values AC-F04-48 judges, from the five bench lines."""
    text = "\n".join(lines)

    def find(pattern: str) -> re.Match:
        match = re.search(pattern, text)
        assert match is not None, f"no {pattern!r} in the bench lines:\n{text}"
        return match

    result = find(r"Bench result: window (\d+)x(\d+) (\w+) \| framebuffer (\d+)x(\d+) px .*"
                  r"measured ([\d.]+) s .* frames (\d+)")
    work = find(r"Bench frame work ms: p50 ([\d.]+) \| p95 ([\d.]+) \| p99 ([\d.]+) \| "
                r"max ([\d.]+)")
    long = find(r"Bench long frames \(> [\d.]+ ms\): (\d+) of (\d+) \(([\d.]+)%\) \| "
                r"cap: \d+ <= \d+ (\w+)")
    rule = find(r"Bench rule \(ADR-0005\): (\w+)")
    return {
        "window": (int(result[1]), int(result[2])), "mode": result[3],
        "framebuffer": (int(result[4]), int(result[5])),
        "measured_s": float(result[6]), "frames": int(result[7]),
        "work_p50": float(work[1]), "work_p99": float(work[3]), "work_max": float(work[4]),
        "long_frames": int(long[1]), "long_pct": float(long[3]),
        "cap_holds": long[4] == "holds", "verdict": rule[1],
    }


def machine_lines(cpu: str, passmark: str | None, driver: str | None) -> list[str]:
    return [f"CPU: {cpu} | PassMark single-thread: {passmark or 'not given (set VN_PASSMARK_ST)'}",
            f"Python {platform.python_version()} | pygame-ce {pygame.version.ver} | "
            f"SDL {'.'.join(map(str, pygame.get_sdl_version()))} | video driver {driver}"]


def report_lines(harness: StageBenchHarness) -> list[str]:
    """Compose times and the long frames in the 1 s after each change."""
    changes = harness.changes()
    ms = sorted(c.ms for c in harness.composes)
    longs = harness.long_after_changes()
    out = []
    if ms:
        out.append(f"Composes: {len(ms)} ({len(changes)} stage changes) | ms p50 "
                   f"{ms[len(ms) // 2]:.2f} | max {ms[-1]:.2f}")
    out.append("Long frames in the 1 s after each change: "
               + (", ".join(str(n) for n in longs) or "no changes")
               + f" | changes with more than one: {sum(1 for n in longs if n > 1)}")
    return out


# --- AC-F04-48's headless check (06 §5.4) --------------------------------------------------

def bench_stages(root: Path, *, lines: int = 16) -> list[tuple[StageState, Say]]:
    """``(stage, line)`` for the first ``lines`` lines of the game in ``root``, loaded as
    bootstrap does, in a headless run over its real image files."""
    from tests.runtime.stage_story import load_game

    files = sorted(p.relative_to(root).as_posix() for p in (root / "images").rglob("*.png"))
    out, stage = [], None
    for command in run_headless(load_game(root), seed=1, image_files=files, max_lines=lines):
        if type(command) is ShowStage:
            stage = command.stage
        elif type(command) is Say:
            out.append((stage, command))
    return out


def check_bench_game(root: Path, *, sprite_size: tuple[int, int], art_height: int,
                     sprites: int = 6) -> list[str]:
    """What is wrong with the bench game (empty: nothing). Every stage has a background and
    ``sprites`` sprites whose files are ``sprite_size``, ``art_height`` is as given, and the
    script has a dialogue-line expression, a move, and a ``behind``."""
    problems = []
    config = load_config(GamePaths(root.resolve())).config
    if config.stage.art_height != art_height:
        problems.append(f"art_height {config.stage.art_height}, not {art_height}")
    seen = bench_stages(root)
    kinds = set()
    previous = None
    for stage, say in seen:
        if stage is None or stage.background is None or len(stage.sprites) != sprites:
            problems.append(f"line {say.text!r}: stage {stage}")
            continue
        for sprite in stage.sprites:
            ref = root / "images" / (sprite.image.replace(" ", "/") + ".png")
            with ref.open("rb") as f:
                header = image_dimensions(f.read(64))
            if header is None or header[1:] != sprite_size:
                problems.append(f"{sprite.image}: {header}, not {sprite_size}")
        if previous is not None and previous.background == stage.background:
            kinds.add(_change_kind(previous, stage, say))
        previous = stage
    for kind in ("expression on the dialogue line", "move", "behind"):
        if kind not in kinds:
            problems.append(f"no {kind}")
    return problems


def _change_kind(before: StageState, after: StageState, say: Say) -> str | None:
    tags = [s.tag for s in before.sprites]
    if [s.tag for s in after.sprites] != tags:
        return "behind" if sorted(tags) == sorted(s.tag for s in after.sprites) else None
    changed = [(a, b) for a, b in zip(before.sprites, after.sprites) if a != b]
    if len(changed) != 1:
        return None
    a, b = changed[0]
    if a.image != b.image and a.at == b.at and say.attributes and say.speaker == b.tag:
        return "expression on the dialogue line"
    if a.at != b.at and a.image == b.image:
        return "move"
    return None
