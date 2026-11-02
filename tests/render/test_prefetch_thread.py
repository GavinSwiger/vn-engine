"""F04 step 7 — AC-F04-45: decoding on the worker doesn't stall the frame (``04-technical.md``
R2, ADR-0007, I-14). ``slow``: runs when ``VN_SLOW=1`` is set or ``-m`` names ``slow``
(the rule is in ``tests/conftest.py``).

This test decides ``PREFETCH_THREADED`` per OS: where it fails, that OS ships with the
thread off (``engine/render/prefetch.py`` ``_THREADED_BY_PLATFORM``), and AC-F04-44 (c) is its
configuration. Record each OS's result in the F04 test report.
"""

import io
import random
import sys
import time

import pygame
import pytest

from engine.render.prefetch import DecodeJob, DecodeWorker, decode_image

pytestmark = [pytest.mark.slow, pytest.mark.display]

BUSY_S = 0.001                    # the main thread's work per frame
FRAME_S = 1 / 60
MAX_EXCESS_S = 0.005              # AC-F04-45: no frame more than 5 ms over its busy loop
DECODES = 20
TARGET = (800, 1333)              # 1200×2000 art at art_height 1080 in a 1280×720 window


def sprite_png() -> bytes:
    """A seeded 1200×2000 RGBA PNG, about 45% transparent (06 §5.2), noisy so it decodes
    at a realistic cost."""
    rnd = random.Random(45)
    surface = pygame.image.frombytes(rnd.randbytes(1200 * 2000 * 4), (1200, 2000), "RGBA")
    surface.fill((0, 0, 0, 0), (0, 0, 1200, 900))        # 45% of the area
    out = io.BytesIO()
    pygame.image.save(surface, out, "sprite.png")
    return out.getvalue()


def _frame() -> float:
    """One main-thread frame at 60 fps: a 1 ms busy loop, then a sleep to the end of the
    frame as the frame limiter does; returns how far past 1 ms the busy loop ended.

    The sleep matters: SDL reads the job's ``BytesIO`` through Python callbacks that need
    the GIL, so a main thread that never sleeps slows each decode to seconds (measured: about
    6 s for this image, with the stall still under 1 ms)."""
    start = time.perf_counter()
    while time.perf_counter() - start < BUSY_S:
        pass
    excess = time.perf_counter() - start - BUSY_S
    rest = FRAME_S - (time.perf_counter() - start)
    if rest > 0:
        time.sleep(rest)
    return excess


def test_ac_f04_45_decoding_on_the_worker_does_not_stall_the_frame():
    data = sprite_png()
    started = time.perf_counter()
    alone = decode_image(DecodeJob("s", data, "image.png", TARGET))
    decode_ms = (time.perf_counter() - started) * 1000
    assert alone.source is not None and alone.variant.get_size() == TARGET
    worker = DecodeWorker()
    excess: list[float] = []
    try:
        for _ in range(DECODES):
            worker.submit(DecodeJob("s", data, "image.png", TARGET))
            deadline = time.monotonic() + 10
            while True:
                excess.append(_frame())
                done = worker.poll()
                if done is not None:
                    assert done.source is not None and done.variant is not None
                    break
                assert time.monotonic() < deadline, "the worker did not answer"
    finally:
        assert worker.stop(5.0)
    worst = max(excess)
    print(f"\nAC-F04-45 {sys.platform} pygame-ce {pygame.version.ver}: {DECODES} decodes "
          f"(one alone: {decode_ms:.1f} ms), {len(excess)} frames, worst stall "
          f"{worst * 1000:.2f} ms, p99 {sorted(excess)[int(len(excess) * 0.99)] * 1000:.3f} ms")
    assert worst <= MAX_EXCESS_S, f"worst main-thread stall {worst * 1000:.2f} ms"
