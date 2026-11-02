"""F25-3 — present evidence's frame time (``06-acceptance.md`` AC-F25-24, TR-F25-04).

**``perf``** (the ADR-0005 reference machine or a recorded stand-in; ``VN_PERF=1``). From the
project root, in cmd::

    set VN_PERF=1
    set SDL_VIDEODRIVER=dummy
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_present_perf.py

The row draws to an offscreen canvas, so the video driver doesn't change the numbers. Attach
the printed ``AC-F25-24`` line to the test report.

- **Frame:** Host E (F25 ``06`` §0.2) at 150% text, 12 statements of 120 code points,
  ``penalty_max`` 20 at meter 20 with ``cost`` 20, Press focused, after a wrong pick and 10
  warm-up frames: 600 frames of the plugin's ``update`` and ``draw`` plus the host's widget
  pass (every button's ``draw`` with the screen's look, F23 A4), each in the loss's hatch
  phase over the full bar (``loss.t`` held at 0.25 s, so every frame draws the full-width
  hatch). p99 ≤ 1.0 ms.
"""

import gc
import statistics
import time

import pygame
import pytest

from engine.app.app import GC_FULL_AFTER
from tests.fixtures.F25 import args as fx
from tests.minigames.bundled.test_present_session import HostE

pytestmark = pytest.mark.perf


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


def test_ac_f25_24_frame_time(pygame_ready):
    w = HostE(meter=(0, 20))
    w.shell.painter.set_text_scale(lambda: 1.5)
    big = fx.big_args()
    args = fx.args(testimony=big["testimony"], answer={"s0": "brass_key"}, at="s0",
                   penalty_max=20, cost=20)
    g = w.open(args, value=20)
    g.loss = None
    w.host.call(g._picked, "festival_map")
    assert g.loss is not None and (g.loss.lo, g.loss.hi) == (0, 20)
    w.frames(10)
    screen, canvas, painter = w.session.screen, w.ui.canvas, w.shell.painter
    del canvas.draw_text, canvas.fill               # Host E's call spies: the real methods
    times = []
    with _FullGcLater():
        for _ in range(600):
            g.loss.t = 0.25
            canvas.bind(w.ui.framebuffer, w.ui.viewport, w.ui.quality)
            painter.bind(canvas)
            start = time.perf_counter()
            g.update(1 / 60)
            g.draw(canvas)
            for button in g.buttons:
                button.draw(painter, screen.look_for(button))
            times.append((time.perf_counter() - start) * 1000)
    assert not g.finishes
    p99 = _p99(times)
    print(f"\nAC-F25-24 frame update+draw+buttons p50 {statistics.median(times):.3f} ms, "
          f"p99 {p99:.3f} ms (150%, 12 x 120 statements, penalty_max 20, full-width hatch, "
          f"600 frames)")
    assert p99 <= 1.0
