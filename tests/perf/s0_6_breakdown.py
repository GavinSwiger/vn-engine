"""S0-6 diagnostic: per-blit cost of the typical frame at 1920x1080 (option B) and of the
option A whole-frame scale. Offscreen, no flip, no limiter; median of N repetitions.

    .venv/Scripts/python tests/perf/s0_6_breakdown.py
"""

from __future__ import annotations

import os
import sys
import time

sys.argv = [sys.argv[0], "--option", "B"]  # satisfy s0_6's argparse on import
os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")

import pygame  # noqa: E402

import s0_6_typical_frame as tf  # noqa: E402

N = 300


def med(fn) -> float:
    xs = []
    for _ in range(N):
        t = time.perf_counter()
        fn()
        xs.append(time.perf_counter() - t)
    xs.sort()
    return xs[len(xs) // 2] * 1000


def main() -> None:
    pygame.init()
    win = pygame.Window("s0-6 breakdown", size=(320, 180))
    fb0 = win.get_surface()
    scene = tf.load_scene(fb0)
    target = pygame.Surface((1920, 1080)).convert(fb0)
    prep = tf.Prepared(scene, 1.5)
    names = ["bg (opaque copy)", "sprite_a (alpha)", "sprite_b (alpha)", "sprite_c (alpha)",
             "textbox (alpha 200)", "name text", "dialogue 1", "dialogue 2", "dialogue 3"]
    total = 0.0
    for name, (s, pos) in zip(names, prep.blits):
        ms = med(lambda s=s, pos=pos: target.blit(s, pos))
        total += ms
        print(f"B 1080p  {name:22s} {s.get_width()}x{s.get_height()}  {ms:6.3f} ms")
    print(f"B 1080p  sum of blits {total:.3f} ms; whole draw() {med(lambda: prep.draw(target)):.3f} ms")
    sub = target.subsurface((0, 0, 1920, 1080))
    print(f"B 1080p  draw() into a full-size subsurface {med(lambda: prep.draw(sub)):.3f} ms")
    mid = pygame.Surface((1280, 720)).convert(fb0)
    p1 = tf.Prepared(scene, 1.0)
    print(f"A        compose at 1280x720 {med(lambda: p1.draw(mid)):.3f} ms")
    print(f"A        smoothscale 1280x720 -> 1920x1080 {med(lambda: pygame.transform.smoothscale(mid, (1920, 1080), target)):.3f} ms")
    print(f"A        scale (nearest) 1280x720 -> 1920x1080 {med(lambda: pygame.transform.scale(mid, (1920, 1080), target)):.3f} ms")
    print(f"         target.fill 1920x1080 {med(lambda: target.fill((0, 0, 0))):.3f} ms")
    print(f"         SIMD: avx2={pygame.version.ver} has_avx2? "
          f"{getattr(pygame.system, 'get_cpu_instruction_sets', lambda: {})().get('AVX2')}")
    win.destroy()
    pygame.quit()


if __name__ == "__main__":
    main()
