"""F23 step 7 — frames with a minigame open (``06-acceptance.md`` AC-F23-64; invariant 10,
ADR-0005).

**``perf``** (the reference machine or a recorded stand-in; ``VN_PERF=1``). From the project
root, in cmd::

    set VN_PERF=1
    set SDL_VIDEODRIVER=dummy
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_lantern_perf.py

Attach the printed ``AC-F23-64`` line to the test report.

The stand-in for AC-F23-64's 600 s ``--bench`` run of the example game: Host U (F23 ``06``
§0.3) running the example's ``game/minigames/lantern_memory.py`` (``pairs=6, hints=True``)
for 600 s of 1/60 s frames, with a scripted move every 0.5 s (arrows and Enter, so the board
is cleared and a new run starts now and then; the restart is outside the timing). Each frame
is the whole ``UiHarness.frame``: the host's routing, the frame elements (heading, hint bar),
the plugin's ``update`` and ``draw``, and the widget pass. Frame work p99 ≤ 16.0 ms and long
frames (over 1/60 s) ≤ 0.5%; the host's own work (the frame minus the plugin's ``update``,
``draw``, its card buttons' ``draw``, and the harness's own frame with no minigame open,
measured first) has a median ≤ 0.5 ms. The open frame (the first frame of each run, its fade
start) is printed. The save's smoothscale is AC-F23-63's and F11's row, not timed here.
The real-window ``--bench`` run is the manual playtest's (``docs/process/manual-F23.md``).
"""

import gc
import itertools
import statistics
import time
from pathlib import Path

import pygame
import pytest

from engine.app.app import GC_FULL_AFTER
from tests.fakes.ui_shell import UiHarness as H
from tests.minigames.conftest import game, import_sandbox, load, write  # noqa: F401
from tests.minigames.host_u import HostU

PLUGIN = Path(__file__).resolve().parents[2] / "game" / "minigames" / "lantern_memory.py"
SECONDS = 600
FPS = 60
MOVE_EVERY = 30                          # frames: one move each 0.5 s
MOVES = (pygame.K_RIGHT, pygame.K_RETURN, pygame.K_DOWN, pygame.K_RETURN, pygame.K_RIGHT,
         pygame.K_RIGHT, pygame.K_RETURN, pygame.K_UP, pygame.K_LEFT, pygame.K_RETURN,
         pygame.K_DOWN, pygame.K_DOWN, pygame.K_RETURN, pygame.K_LEFT, pygame.K_RETURN)


@pytest.fixture
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def _p99(times: list[float]) -> float:
    ordered = sorted(times)
    return ordered[max(0, int(len(ordered) * 0.99) - 1)]


@pytest.mark.perf
def test_ac_f23_64_frames_with_a_minigame_open(game, load, pygame_ready):  # noqa: F811
    write(game, "minigames/lantern_memory.py", PLUGIN.read_bytes())
    loaded = load(game)
    w = HostU(game, registry=loaded.result.registry)
    plugin_ms = [0.0]

    def timed(fn):
        def run(*args):
            start = time.perf_counter()
            try:
                return fn(*args)
            finally:
                plugin_ms[0] += (time.perf_counter() - start) * 1000
        return run

    def open_run(run: int) -> float:
        w.start("lantern_memory", {"pairs": 6, "hints": True}, restored=False, run=run)
        p = w.session.plugin
        p.update, p.draw = timed(p.update), timed(p.draw)
        for button in p.buttons:                 # the plugin's cards, drawn in the host's pass
            button.draw = timed(button.draw)
        start = time.perf_counter()
        w.frame()
        return (time.perf_counter() - start) * 1000

    baseline = []                                # the harness alone: the fake in-game screen
    for _ in range(300):
        start = time.perf_counter()
        w.frame()
        baseline.append((time.perf_counter() - start) * 1000)
    harness = statistics.median(baseline)
    runs = 1
    opens = [open_run(runs)]
    moves = itertools.cycle(MOVES)
    frames, host = [], []
    gc.collect()
    thresholds = gc.get_threshold()
    gc.set_threshold(thresholds[0], thresholds[1], max(thresholds[2], GC_FULL_AFTER))
    try:
        for n in range(SECONDS * FPS):
            if w.session is None:                        # cleared: the next run
                runs += 1
                opens.append(open_run(runs))
            events = (H.key(next(moves)),) if n % MOVE_EVERY == 0 else ()
            plugin_ms[0] = 0.0
            start = time.perf_counter()
            w.frame(*events)
            ms = (time.perf_counter() - start) * 1000
            frames.append(ms)
            host.append(ms - plugin_ms[0] - harness)
    finally:
        gc.set_threshold(*thresholds)
    assert w.fatal == []
    p99 = _p99(frames)
    long = sum(ms > 1000 / FPS for ms in frames) / len(frames)
    host_median = statistics.median(host)
    print(f"\nAC-F23-64 lantern_memory {SECONDS} s: frame p50 {statistics.median(frames):.3f} ms, "
          f"p99 {p99:.3f} ms, long {long:.3%}; host median {host_median:.3f} ms "
          f"(harness {harness:.3f} ms taken off); "
          f"open frame max {max(opens):.3f} ms over {runs} runs ({len(w.done())} cleared)")
    assert p99 <= 16.0
    assert long <= 0.005
    assert host_median <= 0.5
