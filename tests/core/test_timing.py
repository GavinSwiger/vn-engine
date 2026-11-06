"""Frame limiter, game time, overlay stats, and the ADR-0005 bench metrics.

AC-F01-84 (frame-rate cap), 85 (no catch-up burst), 86 (timing follows real time), 87
(stalls advance game time by at most 0.1 s); the unit part of AC-F01-158 (bench metrics).
"""

import math
import random
import re

import pytest

from engine.core.constants import LIMITER_SPIN_S, MAX_FRAME_DT
from engine.core.timing import BenchRecorder, FrameLimiter, GameTime, RecentFrames


class FakeClock:
    """A fake ``perf_counter``/``sleep`` pair. Each read advances time by ``tick`` so the
    limiter's spin loop ends; ``sleep`` advances by exactly the requested time."""

    def __init__(self, start: float = 100.0, tick: float = 1e-5) -> None:
        self.t = start
        self.tick = tick
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        self.t += self.tick
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.t += seconds

    def work(self, seconds: float) -> None:
        self.t += seconds


def _limiter(fps: int, clock: FakeClock) -> FrameLimiter:
    return FrameLimiter(fps, clock=clock, sleep=clock.sleep)


# --- AC-F01-84: frame-rate cap ---------------------------------------------------------------

@pytest.mark.parametrize("fps", [30, 60, 144, 240])
def test_frame_rate_cap(fps):
    clock = FakeClock()
    limiter = _limiter(fps, clock)
    first = limiter.wait()
    frames = 1
    while True:
        clock.work(0.001)
        start = limiter.wait()
        if start - first >= 10.0:
            break
        frames += 1
    assert frames <= 10 * fps + 1
    assert frames >= 10 * fps - 1           # and the cap is actually reached


def test_limiter_period_follows_the_fps():
    assert FrameLimiter(144).period == pytest.approx(1 / 144)
    limiter = FrameLimiter(60)
    limiter.set_fps(30)
    assert limiter.period == pytest.approx(1 / 30)


def test_limiter_sleeps_then_spins_the_last_half_ms():
    clock = FakeClock(tick=0.0)
    calls = {"n": 0}

    def ticking_clock() -> float:
        calls["n"] += 1
        clock.t += 1e-6
        return clock.t

    limiter = FrameLimiter(60, clock=ticking_clock, sleep=clock.sleep)
    limiter.wait()
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx(1 / 60 - LIMITER_SPIN_S, abs=1e-4)
    assert LIMITER_SPIN_S == 0.0005


# --- AC-F01-85: no catch-up burst ------------------------------------------------------------

def test_no_catch_up_burst_after_a_late_frame():
    clock = FakeClock()
    limiter = _limiter(60, clock)
    starts = [limiter.wait()]
    clock.work(0.050)                        # one long frame
    starts.append(limiter.wait())
    for _ in range(3):
        clock.work(0.001)
        starts.append(limiter.wait())
    intervals = [b - a for a, b in zip(starts, starts[1:])]
    assert intervals[0] >= 0.050
    assert all(interval >= 0.0166 for interval in intervals[1:]), intervals


def test_reset_restarts_the_schedule():
    clock = FakeClock()
    limiter = _limiter(60, clock)
    limiter.wait()
    clock.work(5.0)                          # e.g. minimized
    limiter.reset()
    start = limiter.wait()
    clock.work(0.001)
    assert limiter.wait() - start >= 0.0166


# --- AC-F01-86, 87: game time ------------------------------------------------------------------

def _run_frames(fps: int, seconds: float, work, clock: FakeClock) -> GameTime:
    limiter = _limiter(fps, clock)
    game_time = GameTime()
    first = last = None
    while True:
        start = limiter.wait()
        if first is None:
            first = start
        if start - first > seconds:
            break
        game_time.advance(None if last is None else start - last)
        last = start
        clock.work(work())
    return game_time


@pytest.mark.parametrize("fps", [30, 60, 144])
def test_game_time_follows_real_time(fps):
    rng = random.Random(7)
    game_time = _run_frames(fps, 1.0, lambda: rng.uniform(0.0, 0.005), FakeClock())
    assert game_time.now == pytest.approx(1.0, abs=0.05)


def test_first_frame_has_no_delta():
    game_time = GameTime()
    assert game_time.advance(None) == 0.0
    assert (game_time.now, game_time.dt, game_time.frame) == (0.0, 0.0, 1)


def test_stall_advances_game_time_by_at_most_0_1_s():
    clock = FakeClock()
    limiter = _limiter(60, clock)
    game_time = GameTime()
    last = limiter.wait()
    game_time.advance(None)
    for _ in range(5):
        clock.work(0.001)
        start = limiter.wait()
        game_time.advance(start - last)
        last = start
    before = game_time.now
    clock.work(5.0)                          # a 5 s stall
    start = limiter.wait()
    assert game_time.advance(start - last) == MAX_FRAME_DT == 0.1
    assert game_time.now - before == pytest.approx(0.1, abs=1e-12)
    last = start
    for _ in range(5):
        clock.work(0.001)
        start = limiter.wait()
        assert game_time.advance(start - last) <= 1 / 60 + 0.001
        last = start


def test_short_stall_is_kept():
    game_time = GameTime()
    game_time.advance(None)
    assert game_time.advance(0.09) == 0.09
    assert game_time.advance(-1.0) == 0.0     # a clock that went backwards


# --- RecentFrames (dev overlay) ------------------------------------------------------------------

def test_recent_frames():
    recent = RecentFrames(size=120)
    assert recent.fps() == 0.0 and recent.last_work_ms() == 0.0
    recent.record(0.0, 0.004)                 # first frame: no interval
    for _ in range(200):
        recent.record(1 / 60, 0.003)
    assert recent.fps() == pytest.approx(60.0, rel=0.01)
    assert recent.last_work_ms() == pytest.approx(3.0)
    assert len(recent._frames) == 120


# --- AC-F01-158 (unit part): bench metrics ---------------------------------------------------------

LINE_PATTERNS = [
    r"^Bench result: window \d+x\d+ (windowed|fullscreen) \| framebuffer \d+x\d+ px \| fps cap \d+ \| measured \d+\.\d{2} s \| warm-up 5\.00 s excluded \| frames \d+$",
    r"^Bench frame interval ms: p50 \d+\.\d{2} \| p95 \d+\.\d{2} \| p99 \d+\.\d{2} \| max \d+\.\d{2}$",
    r"^Bench frame work ms: p50 \d+\.\d{2} \| p95 \d+\.\d{2} \| p99 \d+\.\d{2} \| max \d+\.\d{2}$",
    r"^Bench long frames \(> \d+\.\d{2} ms\): \d+ of \d+ \(\d+\.\d{2}%\) \| cap: \d+ <= \d+ (holds|FAILS)$",
    r"^Bench rule \(ADR-0005\): (PASS|FAIL) \(.+\)$",
]
WINDOW = "1280x720 windowed | framebuffer 1280x720 px"


def _feed(recorder: BenchRecorder, starts_and_work, previous: float | None = None) -> None:
    for start, work in starts_and_work:
        interval = None if previous is None else start - previous
        if not recorder.done(start):
            recorder.record(start, interval, work)
        previous = start


def test_warm_up_frames_are_not_counted():
    recorder = BenchRecorder(fps=60, seconds=10, start=0.0)
    warm = [i / 60 for i in range(120)] + [2.1 + i / 60 for i in range(174)]
    assert warm[-1] < 5.0 and 2.1 - warm[119] > 0.1          # one 100+ ms interval
    _feed(recorder, [(start, 0.002) for start in warm])
    assert recorder.frames == 0 and recorder.long_frames == 0
    # The frame starting at 5.0 s counts, its interval measured from the warm-up frame.
    _feed(recorder, [(5.0, 0.002)], previous=warm[-1])
    result = recorder.result()
    assert result.frames == 1 and result.long_frames == 0
    assert result.interval_ms[0] == pytest.approx((5.0 - warm[-1]) * 1000)


def _measured_lines(work_times: list[float]) -> list[str]:
    recorder = BenchRecorder(fps=60, seconds=10, start=0.0)
    for i, work in enumerate(work_times):
        recorder.record(5.0 + i / 60, 1 / 60, work)
    return recorder.log_lines(recorder.result(), WINDOW)


def test_nearest_rank_p99():
    six = [0.002] * 594 + [0.020] * 6
    seven = [0.002] * 593 + [0.020] * 7
    assert "p99 2.00 |" in _measured_lines(six)[2]
    assert "p99 20.00 |" in _measured_lines(seven)[2]


def test_long_frame_threshold():
    recorder = BenchRecorder(fps=60, seconds=10, start=0.0)
    recorder.record(5.0, 0.02501, 0.002)
    recorder.record(5.1, 0.02500, 0.002)
    result = recorder.result()
    assert result.long_frames == 1
    assert result.long_threshold_ms == pytest.approx(25.0)
    assert "(> 25.00 ms): 1 of 2 (50.00%)" in recorder.log_lines(result, WINDOW)[3]


def test_storage_overflow_is_counted_and_fails_the_cap():
    recorder = BenchRecorder(fps=60, seconds=10, start=0.0)
    total = math.ceil(60 * 10) + 2 + 5
    for i in range(total):
        recorder.record(5.0 + i * (9.99 / total), 1 / 60, 0.002)
    result = recorder.result()
    assert result.frames == total
    assert result.samples_dropped == 5
    lines = recorder.log_lines(result, WINDOW)
    assert lines[3].endswith(f"cap: {total} <= 601 FAILS")
    assert lines[4].startswith("Bench rule (ADR-0005): FAIL (")


def test_no_measured_frames():
    recorder = BenchRecorder(fps=60, seconds=10, start=0.0)
    lines = recorder.log_lines(recorder.result(), WINDOW)
    assert lines[1] == "Bench frame interval ms: p50 n/a | p95 n/a | p99 n/a | max n/a"
    assert lines[2] == "Bench frame work ms: p50 n/a | p95 n/a | p99 n/a | max n/a"
    assert lines[4] == "Bench rule (ADR-0005): FAIL (no frames measured)"


def test_a_full_run_gives_the_five_lines():
    clock = FakeClock(start=0.0)
    limiter = _limiter(60, clock)
    start = limiter.wait()
    recorder = BenchRecorder(fps=60, seconds=3, start=start)
    previous = None
    while True:
        frame_start = limiter.wait() if previous is not None else start
        if recorder.done(frame_start):
            break
        interval = None if previous is None else frame_start - previous
        clock.work(0.001)
        recorder.record(frame_start, interval, clock.t - frame_start)
        previous = frame_start
    result = recorder.result()
    lines = recorder.log_lines(result, WINDOW)
    assert len(lines) == 5
    for line, pattern in zip(lines, LINE_PATTERNS):
        assert re.match(pattern, line), line
    assert 2.95 <= result.measured_s <= 3.05
    assert result.frames <= 181
    assert "(> 25.00 ms)" in lines[3] and lines[3].endswith("holds")
    assert lines[4].startswith("Bench rule (ADR-0005): PASS (work p99 1.0")
    assert result.work_ms[2] == pytest.approx(1.0, abs=0.05)     # the wait is excluded


def test_frames_after_the_window_are_ignored_and_measured_time_ends_at_done():
    recorder = BenchRecorder(fps=60, seconds=1, start=0.0, warmup_s=5.0)
    recorder.record(5.5, 1 / 60, 0.001)
    assert recorder.done(6.01)
    recorder.record(6.5, 1 / 60, 0.001)
    result = recorder.result()
    assert result.frames == 1
    assert result.measured_s == pytest.approx(1.01)
    assert recorder.capacity == 62
