"""Small anti-aliased marks for shown meters (F62 round 2): hearts, pips and dial arcs.

Why this module exists: ``Canvas`` draws rectangles, pictures and text; a meter's hearts,
pips and dial need curved shapes. Each builder returns a new per-pixel-alpha surface in
device pixels, drawn at ``MARKER_SUPERSAMPLE``× and smoothscaled like F10's markers
(``frames.build_ellipse``). ``mark`` caches them (the same few shapes every frame); callers
blit them and must restore any alpha they set.

- ``heart(size_px, color, ring_px)``: a heart filling ``size_px``; with ``ring_px`` > 0 only
  its outline, that many device pixels thick (an empty heart).
- ``pip``: a circle (``frames.build_ellipse``), filled or a ring.
- ``arc(diameter_px, color, start, sweep, thickness_px)``: a ring segment from ``start``
  degrees (counter-clockwise from 3 o'clock) going ``sweep`` degrees clockwise.
"""

import math
from functools import lru_cache

import pygame

from engine.render.frames import MARKER_SUPERSAMPLE, build_ellipse

RGB = tuple[int, int, int]
Size = tuple[int, int]

_HEART_STEPS = 72


def _heart_points(w: float, h: float, inset: float = 0.0) -> list[tuple[float, float]]:
    """The classic heart curve fitted to ``w`` × ``h``, shrunk by ``inset`` on each side."""
    raw = []
    for i in range(_HEART_STEPS):
        t = 2 * math.pi * i / _HEART_STEPS
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        raw.append((x, -y))
    xs, ys = [p[0] for p in raw], [p[1] for p in raw]
    x0, y0 = min(xs), min(ys)
    sw, sh = max(xs) - x0, max(ys) - y0
    iw, ih = max(1.0, w - 2 * inset), max(1.0, h - 2 * inset)
    return [(inset + (x - x0) / sw * iw, inset + (y - y0) / sh * ih) for x, y in raw]


def heart(size_px: Size, color: RGB, ring_px: float = 0.0) -> pygame.Surface:
    w, h = max(1, int(size_px[0])), max(1, int(size_px[1]))
    k = MARKER_SUPERSAMPLE
    big = pygame.Surface((w * k, h * k), pygame.SRCALPHA)
    big.fill((*color, 0))
    pygame.draw.polygon(big, (*color, 255), _heart_points(w * k, h * k))
    if ring_px > 0:
        ring = ring_px * k
        if ring * 3 < min(w, h) * k:
            pygame.draw.polygon(big, (*color, 0), _heart_points(w * k, h * k, ring * 1.25))
    return pygame.transform.smoothscale(big, (w, h))


def arc(diameter_px: int, color: RGB, start: float, sweep: float,
        thickness_px: float) -> pygame.Surface:
    d = max(1, int(diameter_px))
    k = MARKER_SUPERSAMPLE
    big = pygame.Surface((d * k, d * k), pygame.SRCALPHA)
    big.fill((*color, 0))
    if sweep > 0:
        r_out = d * k / 2
        r_in = max(0.0, r_out - thickness_px * k)
        c = r_out
        steps = max(2, int(abs(sweep) / 3) + 1)
        angles = [math.radians(start - sweep * i / (steps - 1)) for i in range(steps)]
        outer = [(c + r_out * math.cos(a), c - r_out * math.sin(a)) for a in angles]
        inner = [(c + r_in * math.cos(a), c - r_in * math.sin(a)) for a in reversed(angles)]
        pygame.draw.polygon(big, (*color, 255), outer + inner)
        # round caps
        for a in (angles[0], angles[-1]):
            mid = (r_out + r_in) / 2
            pygame.draw.circle(big, (*color, 255),
                               (c + mid * math.cos(a), c - mid * math.sin(a)),
                               (r_out - r_in) / 2)
    return pygame.transform.smoothscale(big, (d, d))


@lru_cache(maxsize=256)
def mark(kind: str, size_px: Size, color: RGB, ring_px: float = 0.0, start: float = 0.0,
         sweep: float = 0.0) -> pygame.Surface:
    """A cached ``heart``, ``pip`` or ``arc`` (``size_px[0]`` is the arc's diameter)."""
    if kind == "heart":
        return heart(size_px, color, ring_px)
    if kind == "pip":
        return build_ellipse(size_px, color, ring_px=ring_px)
    return arc(size_px[0], color, start, sweep, ring_px)


__all__ = ["arc", "heart", "mark"]
