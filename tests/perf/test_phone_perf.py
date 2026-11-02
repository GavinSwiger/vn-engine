"""F26-3 — the phone chat's costs (``06-acceptance.md`` AC-F26-24's ``slow`` rows, AC-F26-25).

**``slow``** (``VN_SLOW=1`` or ``-m slow``; loose CI limits):
- ``problem`` on a chat at the bounds (1,000 steps counting follow-ups, every text 300 code
  points) ≤ 100 ms;
- a full relayout of 1,000 thread items of 300 code points (``thread_layout`` with the
  bundled font's measure, 150% text) ≤ 600 ms (one-time, on a resize or a text-size
  change; F26-4's known decision).

**``perf``** (the ADR-0005 reference machine or a recorded stand-in; ``VN_PERF=1``)::

    set VN_PERF=1
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_phone_perf.py

TR-F26-02: at 150% text, with 200 bubbles in the thread and 4 replies plus ignore shown, the
plugin's ``update`` plus ``draw`` and the host's ``ReplyList`` draw over 600 frames ≤ 1.0 ms
p99 (after 30 warm-up frames). The printed ``AC-F26-25`` line goes in the test report.
"""

import gc
import statistics
import time

import pygame
import pytest

from engine.app.app import GC_FULL_AFTER
from engine.minigames.bundled import phone_rules
from engine.minigames.bundled.phone_chat import Phase
from engine.ui.widgets import Look
from tests.fixtures.F26 import chats

TEXT = "word " * 59 + "end!!"                     # 300 code points


def _bound_chat() -> list:
    """180 messages and 20 asks of 2 replies with 20 follow-ups each: 1,000 steps."""
    chat: list = [TEXT] * 180
    for n in range(20):
        chat.append({"ask": f"a{n}", "x": [TEXT[:80].rstrip()] + [TEXT] * 20,
                     "y": [TEXT[:80].rstrip()] + [TEXT] * 20})
    return chat


@pytest.fixture
def host(tmp_path):
    pygame.init()
    from tests.minigames.host_u import HostU
    game = tmp_path / "game"
    game.mkdir()
    yield HostU(game.resolve())
    pygame.quit()


def _median_ms(fn, runs: int = 5) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


@pytest.mark.slow
def test_ac_f26_24_slow_rows(host):
    args = chats.args(_bound_chat())
    assert phone_rules._total(args["chat"]) == 1000
    assert phone_rules.problem(args) is None
    assert _median_ms(lambda: phone_rules.problem(args)) <= 100
    font = host.shell.assets.font(None, 36).font

    def measure(text: str, size: int) -> float:
        return font.size(text)[0] if text else 0

    items = [phone_rules.Message("Sayori", TEXT)] * 1000
    placed = phone_rules.thread_layout(items, 460, s=36, small=36, group=False, measure=measure)
    assert len(placed) == 1000
    assert _median_ms(lambda: phone_rules.thread_layout(items, 460, s=36, small=36,
                                                        group=False, measure=measure),
                      runs=3) <= 600


def _frames(w, g, canvas, painter, look) -> list[float]:
    times = []
    for _ in range(600):
        canvas.bind(w.ui.framebuffer, w.ui.viewport, w.ui.quality)
        painter.bind(canvas)
        start = time.perf_counter()
        g.update(1 / 60)
        g.draw(canvas)
        g.replies.draw(painter, look)
        times.append((time.perf_counter() - start) * 1000)
    return times


@pytest.mark.perf
def test_ac_f26_25_frame_time(host):
    w = host
    w.shell.painter.set_text_scale(lambda: 1.5)
    chat = [f"message number {n} in a long thread" for n in range(199)]
    chat.append({"ask": "q", "a": "A first reply", "b": "A second reply",
                 "c": "A third reply", "d": "A fourth reply", "ignore": True})
    w.start("phone_chat", chats.args(chat))
    g = w.session.plugin
    while g.phase is not Phase.ASK:
        w.host.call(g.update if g.phase is Phase.BEGIN else g._hurry,
                    *((0.0,) if g.phase is Phase.BEGIN else ()))
    w.frames(30)
    assert len(g.view) >= 200 and len(g.labels) == 5
    canvas = w.ui.canvas
    painter = w.shell.painter
    look = Look("focused")
    times = []
    gc.collect()
    thresholds = gc.get_threshold()                    # the frame loop's collector setting
    gc.set_threshold(thresholds[0], thresholds[1], max(thresholds[2], GC_FULL_AFTER))
    try:
        times = _frames(w, g, canvas, painter, look)
    finally:
        gc.set_threshold(*thresholds)
    times.sort()
    p99 = times[int(len(times) * 0.99) - 1]
    print(f"\nAC-F26-25 update+draw p50 {statistics.median(times):.3f} ms, p99 {p99:.3f} ms "
          "(150%, 200 bubbles, 4 replies + ignore, 600 frames)")
    assert p99 <= 1.0


