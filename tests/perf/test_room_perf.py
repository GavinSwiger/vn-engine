"""F27-3 — the puzzle room's frame time (``06-acceptance.md`` AC-F27-26, TR-F27-04).

**``perf``** (the ADR-0005 reference machine or a recorded stand-in; ``VN_PERF=1``)::

    set VN_PERF=1
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_room_perf.py

At 150% text, with 40 shown hotspots that have images and one focused, the plugin's ``draw``
plus the host's hotspot widget draws (the focused one's ring and tag) over 600 frames
≤ 1.0 ms p99 (after 30 warm-up frames). The printed ``AC-F27-26`` line goes in the test
report.
"""

import gc
import statistics
import time

import pygame
import pytest

from engine.app.app import GC_FULL_AFTER
from engine.ui.nav import InputKind


def _room() -> dict:
    """40 hotspots in a 10 × 4 grid, each with an image; the last is the exit."""
    spots = {}
    for i in range(40):
        x, y = 40 + (i % 10) * 120, 120 + (i // 10) * 130
        spots[f"s{i}"] = {"rect": [x, y, 96, 96], "label": f"Thing {i}",
                          "image": "attic key" if i % 2 else "attic magnet"}
    spots["s39"]["exit"] = True
    return {"background": "bg attic", "hotspots": spots}


@pytest.fixture
def host():
    pygame.init()
    from tests.minigames.bundled.room_host import HostR
    yield HostR()
    pygame.quit()


@pytest.mark.perf
def test_ac_f27_26_frame_time(host):
    w = host
    w.shell.painter.set_text_scale(lambda: 1.5)
    g = w.open({"room": _room(), "state": None}, by=InputKind.MOUSE)
    assert len(g.spots) == 40 and len(g.imgs) == 40
    target = g.spots[13]
    w.frame(w.ui.motion(target.box.center))
    w.frames(30)
    screen = w.session.screen
    canvas, painter = w.ui.canvas, w.shell.painter
    times = []
    gc.collect()
    thresholds = gc.get_threshold()
    gc.set_threshold(thresholds[0], thresholds[1], max(thresholds[2], GC_FULL_AFTER))
    try:
        for _ in range(600):
            canvas.bind(w.ui.framebuffer, w.ui.viewport, w.ui.quality)
            painter.bind(canvas)
            start = time.perf_counter()
            g.draw(canvas)
            for spot in g.spots:
                spot.draw(painter, screen.look_for(spot))
            times.append((time.perf_counter() - start) * 1000)
    finally:
        gc.set_threshold(*thresholds)
    times.sort()
    p99 = times[int(len(times) * 0.99) - 1]
    print(f"\nAC-F27-26 draw p50 {statistics.median(times):.3f} ms, p99 {p99:.3f} ms "
          "(150%, 40 hotspots with images, one focused, 600 frames)")
    assert p99 <= 1.0
