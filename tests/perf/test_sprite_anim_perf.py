"""F38 step 2 — what a blink or mouth change costs (AC-F38-08; ADR-0007's F38 amendment;
ADR-0005's 16 ms frame): at 1920×1080, a 675×1080 talking, blinking sprite over a
background with a second sprite, a frame change repaints only that sprite's rect, against
the 10–15 ms of a full compose.

**Reference run (``perf``, never CI)**, on the ADR-0005 machine or a recorded stand-in::

    set VN_PERF=1
    .venv/Scripts/python -m pytest tests/perf/test_sprite_anim_perf.py -m perf -s -v

It times 120 draws with a frame change (flip-flopping between the look and a talking
frame), 120 draws of the still stage (one blit), and 20 full composes of the same stage, and
prints the medians and 95th percentiles. The pass rule: a draw with a change has a 95th
percentile under ``CHANGE_MAX_MS`` (half a frame).

**Manual (AC-F38-08):** a 600 s ``--bench`` run at 1920×1080 of a game with two talking,
blinking sprites (Hana's sample frames, ``blink_every = 1``) meets invariant 10 (no frame
over budget); recorded in the F38 handoff.

Measured 2026-11-02 (dev machine, Windows 11, pygame-ce 2.5.8, surfaces in memory, dummy
driver, other test runs sharing the machine): a draw with a change, median 2.6–3.4 ms and
p95 4.3–7.3 ms, of which the still blit is 0.5–0.8 ms; a full compose of the same 1:1 art
(nothing scaled, both alpha sprites blitted whole) 2.7–3.1 ms. Blits are 98% of a change's
time (cProfile): the repaint is the clipped background plus the two sprites' alpha blits.
"""

import statistics
import time

import pygame
import pytest

from engine.core.constants import BUILTIN_POSITIONS
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.render.canvas import Canvas, RenderQuality
from engine.render.prefetch import ImagePrefetcher
from engine.render.stage import StageView
from engine.runtime.commands import ShowStage
from engine.runtime.images import ImageFile, ImageIndex, look_frames
from engine.runtime.stage import SpriteState, StageState
from tests.render.conftest import make_assets

pytestmark = [pytest.mark.perf, pytest.mark.display]

SIZE = (1920, 1080)
SPRITE = (675, 1080)
CHANGE_MAX_MS = 8.0
CHANGES = 120
COMPOSES = 20


def _write(root, ref, surface) -> None:
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surface, str(path))


def _figure(color) -> pygame.Surface:
    s = pygame.Surface(SPRITE, pygame.SRCALPHA)
    s.fill((*color, 0))
    pygame.draw.ellipse(s, (*color, 255), (60, 80, 555, 1000))
    pygame.draw.ellipse(s, (40, 40, 40, 200), (250, 300, 175, 60))
    return s


def test_ac_f38_08_frame_change_cost(tmp_path):
    pygame.init()
    files = {"bg room": "images/bg/room.png", "a talk": "images/a/talk.png",
             "a talk_talk1": "images/a/talk_talk1.png", "b x": "images/b/x.png"}
    bg = pygame.Surface(SIZE)
    for y in range(0, SIZE[1], 4):
        bg.fill((y % 256, 90, (y * 7) % 256), (0, y, SIZE[0], 4))
    _write(tmp_path, files["bg room"], bg)
    _write(tmp_path, files["a talk"], _figure((240, 200, 180)))
    _write(tmp_path, files["a talk_talk1"], _figure((230, 190, 170)))
    _write(tmp_path, files["b x"], _figure((120, 160, 220)))
    framebuffer = pygame.Surface(SIZE)
    assets = make_assets(GamePaths.for_game(tmp_path), format_source=lambda: framebuffer)
    index = ImageIndex({name: ImageFile(ref) for name, ref in files.items()})
    view = StageView(assets, index, art_height=1080, positions=BUILTIN_POSITIONS,
                     empty_color=(0, 0, 0), prefetcher=ImagePrefetcher(assets, threaded=False),
                     frames_of=look_frames(index))
    canvas = Canvas(assets)
    canvas.bind(framebuffer, Viewport(1920, 1080, *SIZE, 0, 0, *SIZE), RenderQuality.FINAL)
    stage = StageState("bg room", (SpriteState("b", "b x", (700.0,), 0, 1.0, False),
                                   SpriteState("a", "a talk", (1000.0,), 0, 1.0, False)))
    view.show(ShowStage(stage))
    for _ in range(10):
        view.update()
        view.show_frames({"a": "a talk_talk1"})
        view.draw(canvas)
    assert view.shown_frames == {"a": "a talk_talk1"}
    changes, still = [], []
    for k in range(CHANGES):
        view.show_frames({} if k % 2 == 0 else {"a": "a talk_talk1"})
        start = time.perf_counter()
        view.draw(canvas)
        changes.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        view.draw(canvas)
        still.append((time.perf_counter() - start) * 1000)
    composes = []
    for _ in range(COMPOSES):
        view.show(ShowStage(stage))
        start = time.perf_counter()
        view.draw(canvas)
        composes.append((time.perf_counter() - start) * 1000)
    p95 = statistics.quantiles(changes, n=20)[-1]
    print(f"\nF38 draw with a frame change: median {statistics.median(changes):.2f} ms, "
          f"p95 {p95:.2f} ms; still draw median {statistics.median(still):.2f} ms; "
          f"full compose median {statistics.median(composes):.2f} ms")
    assert p95 < CHANGE_MAX_MS
