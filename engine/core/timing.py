"""Frame pacing and frame-time measurement: limiter, game time, overlay stats, bench.

Why this module exists: the frame cap (PR-F01-46), real-time game timing with clamped
stalls (PR-F01-47, 48, 66), and the ADR-0005 bench metrics (PR-F01-49) are rules every
later feature relies on. The clock and sleep are injected, so all of it is tested with a
fake clock and no pygame.

Metric definitions (ADR-0005, binding): the *frame interval* is the unclamped time between
consecutive frame starts (consecutive returns of ``FrameLimiter.wait()``); the *frame work*
is the time from a frame's start to the return of its ``flip()`` (the limiter's wait is
excluded); a *long frame* has an interval longer than 1.5 frame periods.
"""

import math
import time
from array import array
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from engine.core.constants import (
    BENCH_LONG_FRAMES_MAX_PCT,
    BENCH_WARMUP_S,
    BENCH_WORK_P99_MAX_MS,
    LIMITER_SPIN_S,
    LONG_FRAME_FACTOR,
    MAX_FRAME_DT,
    RECENT_FRAMES,
)


class FrameLimiter:
    """Starts frames no closer than ``1 / fps`` apart on average, with no catch-up burst
    after a late frame (§7.9, PR-F01-46)."""

    def __init__(self, fps: int, *, clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._clock = clock
        self._sleep = sleep
        self.period = 1.0 / fps
        self._next_deadline = clock()

    def set_fps(self, fps: int) -> None:
        """Change the cap (F16 seam). Takes effect from the next frame."""
        self.period = 1.0 / fps

    def wait(self) -> float:
        """Block until the next frame slot; return the frame start (``clock()``).

        Sleeps until 2 ms before the deadline, then spins. If the frame is more than one
        period late, the schedule restarts from now instead of bursting to catch up.
        """
        self._next_deadline += self.period
        remaining = self._next_deadline - self._clock()
        if remaining > LIMITER_SPIN_S:
            self._sleep(remaining - LIMITER_SPIN_S)
        while self._clock() < self._next_deadline:
            pass
        now = self._clock()
        if now - self._next_deadline > self.period:
            self._next_deadline = now
        return self._clock()

    def reset(self) -> None:
        """Restart the schedule from now (after a minimized period or a stall)."""
        self._next_deadline = self._clock()


@dataclass
class GameTime:
    """Game time: the sum of clamped frame deltas, so a stall, a resize drag, or a
    fullscreen toggle advances it by at most ``MAX_FRAME_DT`` and never resets it
    (PR-F01-47, 48, 66)."""

    now: float = 0.0        # seconds of game time since launch (sum of clamped dt)
    dt: float = 0.0         # this frame's clamped delta, seconds
    frame: int = 0          # frame counter (cache recency protection)

    def advance(self, elapsed: float | None) -> float:
        """Start a new frame. ``elapsed`` is the unclamped time since the previous frame
        start, or None for the first frame (dt 0). Returns the clamped ``dt``."""
        self.dt = 0.0 if elapsed is None else min(max(elapsed, 0.0), MAX_FRAME_DT)
        self.now += self.dt
        self.frame += 1
        return self.dt


class RecentFrames:
    """The last ``RECENT_FRAMES`` frames, for the dev overlay only."""

    def __init__(self, size: int = RECENT_FRAMES) -> None:
        self._frames: deque[tuple[float, float]] = deque(maxlen=size)

    def record(self, interval_s: float, work_s: float) -> None:
        self._frames.append((interval_s, work_s))

    def fps(self, window_s: float = 0.5) -> float:
        """Frames per second over the newest frames whose intervals add up to about
        ``window_s`` (all kept frames if they span less). 0.0 with no intervals."""
        total = 0.0
        count = 0
        for interval, _ in reversed(self._frames):
            if interval <= 0.0:
                continue
            total += interval
            count += 1
            if total >= window_s:
                break
        return count / total if total > 0.0 else 0.0

    def last_work_ms(self) -> float:
        return self._frames[-1][1] * 1000.0 if self._frames else 0.0


Percentiles = tuple[float, float, float, float]     # p50, p95, p99, max (ms)


@dataclass(frozen=True)
class BenchResult:
    """The ADR-0005 metrics of one bench run. A percentile tuple is None when no sample
    of that kind was measured (printed as ``n/a``)."""

    fps_cap: int
    measured_s: float
    warmup_s: float
    frames: int
    interval_ms: Percentiles | None
    work_ms: Percentiles | None
    long_frames: int
    long_threshold_ms: float
    samples_dropped: int


class BenchRecorder:
    """Collects frame intervals and work times for ``--bench SECONDS`` (§7.5.3).

    The measurement window is ``[start + warmup_s, start + warmup_s + seconds)``; a frame
    belongs to it if its start does, and its interval is measured from the previous frame
    start even if that frame was in the warm-up.
    """

    def __init__(self, *, fps: int, seconds: float, start: float,
                 warmup_s: float = BENCH_WARMUP_S) -> None:
        """Preallocates array('d') storage for ceil(fps * seconds) + 2 samples."""
        self.fps = fps
        self.seconds = seconds
        self.warmup_s = warmup_s
        self.window_start = start + warmup_s
        self.window_end = self.window_start + seconds
        self.capacity = math.ceil(fps * seconds) + 2
        self._intervals = array("d", bytes(8 * self.capacity))
        self._work = array("d", bytes(8 * self.capacity))
        self._n_intervals = 0
        self._n_work = 0
        self.frames = 0                 # exact counter, also past the storage
        self.long_frames = 0            # exact counter
        self.samples_dropped = 0
        self.long_threshold_s = LONG_FRAME_FACTOR / fps
        self._last_seen: float | None = None

    def record(self, frame_start: float, interval_s: float | None, work_s: float) -> None:
        """One frame. Frames starting outside the measurement window are ignored;
        ``interval_s`` is None when the previous start is unknown (first frame, or after a
        minimized period)."""
        if not self.window_start <= frame_start < self.window_end:
            return
        self._last_seen = frame_start
        self.frames += 1
        if interval_s is not None and interval_s > self.long_threshold_s:
            self.long_frames += 1
        if self._n_work >= self.capacity:
            self.samples_dropped += 1
            return
        self._work[self._n_work] = work_s
        self._n_work += 1
        if interval_s is not None:
            self._intervals[self._n_intervals] = interval_s
            self._n_intervals += 1

    def done(self, frame_start: float) -> bool:
        """True once a frame starts at or after the end of the measurement window."""
        if frame_start >= self.window_end:
            self._last_seen = frame_start
            return True
        return False

    def result(self) -> BenchResult:
        measured = 0.0 if self._last_seen is None else max(0.0, self._last_seen
                                                            - self.window_start)
        return BenchResult(
            fps_cap=self.fps, measured_s=measured, warmup_s=self.warmup_s,
            frames=self.frames,
            interval_ms=_percentiles(self._intervals[:self._n_intervals]),
            work_ms=_percentiles(self._work[:self._n_work]),
            long_frames=self.long_frames, long_threshold_ms=self.long_threshold_s * 1000.0,
            samples_dropped=self.samples_dropped)

    def cap_limit(self) -> int:
        """The most frames the cap allows in the window: floor(fps × SECONDS) + 1."""
        return math.floor(self.fps * self.seconds) + 1

    def log_lines(self, result: BenchResult, window_desc: str) -> list[str]:
        """The five bench lines (§7.5.3). ``window_desc`` is everything after ``window ``
        up to the fps cap, e.g. ``1280x720 windowed | framebuffer 1280x720 px``."""
        n = result.frames
        limit = self.cap_limit()
        cap_holds = n <= limit
        pct = 100.0 * result.long_frames / n if n else 0.0
        lines = [
            f"Bench result: window {window_desc} | fps cap {result.fps_cap} | "
            f"measured {result.measured_s:.2f} s | warm-up {result.warmup_s:.2f} s excluded | "
            f"frames {n}",
            "Bench frame interval ms: " + _format_percentiles(result.interval_ms),
            "Bench frame work ms: " + _format_percentiles(result.work_ms),
            f"Bench long frames (> {result.long_threshold_ms:.2f} ms): {result.long_frames} "
            f"of {n} ({pct:.2f}%) | cap: {n} <= {limit} {'holds' if cap_holds else 'FAILS'}",
        ]
        if n == 0 or result.work_ms is None:
            lines.append("Bench rule (ADR-0005): FAIL (no frames measured)")
            return lines
        # Judged on the printed (2-decimal) values, as QA reads them.
        p99 = round(result.work_ms[2], 2)
        pct2 = round(pct, 2)
        work_ok = p99 <= BENCH_WORK_P99_MAX_MS
        long_ok = pct2 <= BENCH_LONG_FRAMES_MAX_PCT
        verdict = "PASS" if work_ok and long_ok and cap_holds else "FAIL"
        lines.append(
            f"Bench rule (ADR-0005): {verdict} ("
            f"work p99 {p99:.2f} {'<=' if work_ok else '>'} {BENCH_WORK_P99_MAX_MS:.2f} ms; "
            f"long frames {pct2:.2f}% {'<=' if long_ok else '>'} "
            f"{BENCH_LONG_FRAMES_MAX_PCT:.2f}%; cap {'holds' if cap_holds else 'fails'})")
        return lines


def _percentiles(samples: array) -> Percentiles | None:
    """Nearest-rank p50, p95, p99 and the max, in ms: sorted(xs)[ceil(p/100 · n) − 1]."""
    n = len(samples)
    if n == 0:
        return None
    xs = sorted(samples)

    def rank(p: int) -> float:
        return xs[-(-p * n // 100) - 1] * 1000.0      # exact integer ceil(p·n/100)

    return rank(50), rank(95), rank(99), xs[-1] * 1000.0


def _format_percentiles(values: Percentiles | None) -> str:
    if values is None:
        return "p50 n/a | p95 n/a | p99 n/a | max n/a"
    p50, p95, p99, top = values
    return f"p50 {p50:.2f} | p95 {p95:.2f} | p99 {p99:.2f} | max {top:.2f}"
