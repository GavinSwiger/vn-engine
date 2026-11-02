"""F24-4 — the poem game's frame and pick time (``06-acceptance.md`` AC-F24-22, TR-F24-02).
AC-F24-21's ``slow`` row (2,000 words × 16 names checked, and a save round trip) lives with
the other AC-F24-21 rows in ``tests/minigames/bundled/test_poem_session.py``.

**``perf``** (the ADR-0005 reference machine or a recorded stand-in; ``VN_PERF=1``). From the
project root, in cmd::

    set VN_PERF=1
    set SDL_VIDEODRIVER=dummy
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_poem_perf.py

(In PowerShell: ``$env:VN_PERF = "1"; $env:SDL_VIDEODRIVER = "dummy"``. Both rows draw to an
offscreen canvas, so the video driver doesn't change the numbers.) Attach the printed
``AC-F24-22`` lines to the test report.

- **Frame:** Host P (F24 ``06`` §0.2) at 150% text with 12 words on the page (``rounds=1,
  page_words=12``), slot 0 focused, after 30 warm-up frames: 600 frames of the plugin's
  ``update`` and ``draw`` plus the host's widget pass (every ``WordSlot.draw`` with the
  screen's look, F23 A4). p99 ≤ 1.0 ms.
- **Pick:** a 2,000-word list, ``rounds=50, page_words=12``, at 150%: each of the 50 picks
  is ``WordSlot.activate`` (the totals, one ``shuffle`` of up to 2,000 indices; the last pick
  also the ledger requests and ``ctx.finish``) plus the next ``draw`` (the relayout and up to
  12 ``fit_label`` calls happen there, 04 §6.5). p99 of the 50 ≤ 4.0 ms. The 200 ms guard is
  passed with ``update(0.25)`` between picks, outside the timing.
"""

import gc
import statistics
import time

import pygame
import pytest

from engine.app.app import GC_FULL_AFTER
from tests.fakes.ui_shell import UiHarness as H
from tests.minigames.bundled.test_poem_session import HostP, running

W12 = dict.fromkeys(["alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
                     "india", "juliett", "kilo", "lima"], "yuri")
METERS = ("sayori", "natsuki", "yuri", "monika")
W2000 = {f"word{i:04}": {METERS[i % 4]: 1 + i % 3, METERS[(i + 1) % 4]: 1}
         for i in range(2000)}


@pytest.fixture
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


def _p99(times: list[float]) -> float:
    ordered = sorted(times)
    return ordered[max(0, int(len(ordered) * 0.99) - 1)]


class _FullGcLater:
    """The frame loop's collector setting (``GC_FULL_AFTER``), as in ``test_phone_perf``."""

    def __enter__(self):
        gc.collect()
        self.thresholds = gc.get_threshold()
        t = self.thresholds
        gc.set_threshold(t[0], t[1], max(t[2], GC_FULL_AFTER))

    def __exit__(self, *exc):
        gc.set_threshold(*self.thresholds)


def _world(args: dict) -> HostP:
    w = HostP()
    w.shell.painter.set_text_scale(lambda: 1.5)
    running(w, args)
    return w


@pytest.mark.perf
def test_ac_f24_22_frame_time(pygame_ready):
    w = _world({"words": W12, "rounds": 1, "page_words": 12})
    w.frame(H.key(pygame.K_DOWN))                  # focus visible, on a slot
    w.frames(30)
    g, screen = w.game, w.session.screen
    assert len(g.slots) == 12 and g.word_px == 48 and w.focused() is not None
    canvas, painter = w.ui.canvas, w.shell.painter
    times = []
    with _FullGcLater():
        for _ in range(600):
            canvas.bind(w.ui.framebuffer, w.ui.viewport, w.ui.quality)
            painter.bind(canvas)
            start = time.perf_counter()
            g.update(1 / 60)
            g.draw(canvas)
            for slot in g.slots:
                slot.draw(painter, screen.look_for(slot))
            times.append((time.perf_counter() - start) * 1000)
    p99 = _p99(times)
    print(f"\nAC-F24-22 frame update+draw+slots p50 {statistics.median(times):.3f} ms, "
          f"p99 {p99:.3f} ms (150%, 12 words, 600 frames)")
    assert p99 <= 1.0


@pytest.mark.perf
def test_ac_f24_22_pick_time(pygame_ready):
    w = _world({"words": W2000, "rounds": 50, "page_words": 12})
    w.frames(5)
    g = w.game
    canvas = w.ui.canvas
    times = []
    with _FullGcLater():
        for n in range(50):
            g.update(0.25)                            # past the 200 ms guard
            canvas.bind(w.ui.framebuffer, w.ui.viewport, w.ui.quality)
            start = time.perf_counter()
            g.slots[n % 12].activate()
            g.draw(canvas)
            times.append((time.perf_counter() - start) * 1000)
            assert len(g.picked) == n + 1
    assert g.done
    p99 = _p99(times)
    print(f"\nAC-F24-22 pick (2,000 words) p50 {statistics.median(times):.3f} ms, "
          f"p99 {p99:.3f} ms, max {max(times):.3f} ms (150%, 50 picks of 12)")
    assert p99 <= 4.0
