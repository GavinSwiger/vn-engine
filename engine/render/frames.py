"""Frames, fills, and fades: the drawing helpers every panel, button, and textbox shares.

Why this module exists: the textbox (F05), choices (F07), and every menu widget (F10) draw
the same two looks from ``docs/ui-system.md`` §3 "Frames and fills": a filled rounded
rectangle with an inside border, or a nine-slice ``frame_image`` multiplied by
``fill_opacity`` (UI-F05-12, UI-F10-01). One implementation keeps them identical, so F05 and
F07 call ``build_frame`` instead of private copies (F10 ``04`` §3.1).

Every builder returns a **new** surface for the caller to cache (``SizedLru``, F10 ``04``
§11): building a shape costs 0.1–0.3 ms, and rebuilding shapes every frame was measured at
7.8 ms p50 / 11 ms p99 at 1080p, so nothing here is meant to run per frame except ``dim``
and ``to_black``, which are two constant fills (a full-viewport ``set_alpha`` composite was
rejected at 16.6 ms p99).

pygame-ce notes from spike S0 (``tests/perf/S0-results.md``):

- ``pygame.draw.*`` on a per-pixel-alpha surface writes RGBA as-is and does not blend (note 8).
  The drawn frame relies on that: the border is drawn opaque, then the fill is drawn *over*
  it with the fill's alpha, which replaces the border's pixels instead of mixing with them.
  Shapes are drawn without anti-aliasing at 2× (frames) or 4× (markers) and
  ``smoothscale``d down, on a background of the shape's own color at alpha 0, so the
  smoothed edge has no dark fringe.
- Results are 32-bit ARGB with ``SRCALPHA`` set, the framebuffer's layout (note 10), made
  without ``convert_alpha()`` so they work before a window exists (note 3).
- Callers pass ``canvas.surface`` to ``dim``/``to_black`` during the frame only: it is a
  subsurface that is invalid after a resize (note 2). Nothing here keeps a surface.

Imports ``core`` only (F10 ``04`` §3.3), so ``render`` and ``ui`` can both use it.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

import pygame

RGB = tuple[int, int, int]
Size = tuple[int, int]
Corners = tuple[bool, bool, bool, bool]       # top-left, top-right, bottom-left, bottom-right

ALL_CORNERS: Final[Corners] = (True, True, True, True)
TOP_CORNERS: Final[Corners] = (True, True, False, False)     # F05's name tab
FRAME_SUPERSAMPLE: Final = 2      # drawn frames: 2× then smoothscale (F05 §7.7)
MARKER_SUPERSAMPLE: Final = 4     # small shapes: 4× then smoothscale (F05 §7.7 indicator)

Direction = Literal["right", "left", "up", "down"]


@dataclass(frozen=True)
class FrameSpec:
    """The look of one element in one state, in canvas units (ui-system §3).

    ``fill_opacity`` multiplies the fill, or the whole frame image; the border is opaque.
    ``border_width`` is drawn inside the rectangle. ``slice_width`` is
    ``frame_slice_width``: the nine-slice corner size, in source pixels and canvas units
    (an image's canvas size equals its pixel size). ``corners`` picks which corners are
    rounded (the name tab rounds only the top ones)."""

    fill_color: RGB
    fill_opacity: float = 1.0
    border_color: RGB = (0, 0, 0)
    border_width: int = 0
    corner_radius: int = 0
    slice_width: int = 24
    corners: Corners = ALL_CORNERS


def build_frame(spec: FrameSpec, size_px: Size, scale: float,
                image: pygame.Surface | None = None) -> pygame.Surface:
    """A new ``size_px`` per-pixel-alpha surface with ``spec``'s look at ``scale`` device
    pixels per canvas unit.

    ``image`` None: the rounded fill at ``round(255 × fill_opacity)`` with its opaque inside
    border, drawn at 2× and ``smoothscale``d. Radius and border are whole device pixels
    (``round(value × scale)``; a border of at least 1 px when ``border_width > 0``), so a
    border is equally thick on every side.

    ``image`` given (the caller resolved the ``frame_image`` and checked it is not a
    placeholder; a missing frame means passing None, UI-F05-12): nine-slice. The corners,
    ``slice_width`` source pixels square, are drawn at ``round(slice_width × scale)`` device
    pixels, i.e. unscaled in canvas units; the edges stretch along their length and the
    center both ways (``smoothscale``). ``slice_width`` is capped so the image keeps at
    least 1 px of edge and center, and corners shrink to fit when the element is smaller
    than two of them. Then the alpha of every pixel is multiplied by ``fill_opacity``.
    """
    width, height = max(1, int(size_px[0])), max(1, int(size_px[1]))
    if image is None:
        return _drawn_frame(spec, width, height, scale)
    surface = _nine_slice(_rgba(image), width, height, spec.slice_width, scale)
    _multiply_alpha(surface, spec.fill_opacity)
    return surface


def build_triangle(size_px: Size, color: RGB, *, direction: Direction = "right"
                   ) -> pygame.Surface:
    """A new ``size_px`` per-pixel-alpha surface holding a triangle that fills it, pointing
    ``direction`` (F10's focus marker is a right-pointing 12×16 one), drawn at 4× and
    ``smoothscale``d."""
    width, height = max(1, int(size_px[0])), max(1, int(size_px[1]))
    k = MARKER_SUPERSAMPLE
    w, h = width * k, height * k
    points = {
        "right": [(0, 0), (w, h / 2), (0, h)],
        "left": [(w, 0), (0, h / 2), (w, h)],
        "down": [(0, 0), (w, 0), (w / 2, h)],
        "up": [(0, h), (w / 2, 0), (w, h)],
    }[direction]
    big = _blank((w, h), color)
    pygame.draw.polygon(big, (*color, 255), points)
    return pygame.transform.smoothscale(big, (width, height))


def build_ellipse(size_px: Size, color: RGB, *, ring_px: float = 0) -> pygame.Surface:
    """A new ``size_px`` per-pixel-alpha surface holding the ellipse inscribed in it (a
    circle when square): filled when ``ring_px`` is 0, else a ring that many device pixels
    thick (F10's on/off pip, toggle knob). Drawn at 4× and ``smoothscale``d."""
    width, height = max(1, int(size_px[0])), max(1, int(size_px[1]))
    k = MARKER_SUPERSAMPLE
    big = _blank((width * k, height * k), color)
    ring = 0 if ring_px <= 0 else max(1, round(ring_px * k))
    if ring * 2 >= min(width, height) * k:
        ring = 0                                      # thicker than the radius: filled
    pygame.draw.ellipse(big, (*color, 255), big.get_rect(), ring)
    return pygame.transform.smoothscale(big, (width, height))


def vertical_gradient(size_px: Size, top: RGB, bottom: RGB) -> pygame.Surface:
    """A new opaque 32-bit ``size_px`` surface fading from ``top`` (first row) to ``bottom``
    (last row), each row one color rounded from the linear sRGB mix (ui-system §3: colors
    blend as drawn). Built as one column and widened with a nearest-neighbor scale."""
    width, height = max(1, int(size_px[0])), max(1, int(size_px[1]))
    column = pygame.Surface((1, height), 0, 32)
    last = max(1, height - 1)
    for y in range(height):
        t = y / last
        column.set_at((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return pygame.transform.scale(column, (width, height))


def dim(surface: pygame.Surface, color: RGB, opacity: float,
        rect: pygame.Rect | Sequence[int] | None = None) -> None:
    """Blend ``color`` at ``opacity`` over ``surface`` (or ``rect`` of it) in place:
    ``c·(1 − a) + color·a`` per channel, as two constant fills (``BLEND_RGB_MULT`` then
    ``BLEND_RGB_ADD``), never an alpha surface. Alpha channels are left as they are.
    ``opacity`` ≤ 0 does nothing; ≥ 1 fills with ``color``."""
    a = _clamp01(opacity)
    if a <= 0.0:
        return
    if a >= 1.0:
        _fill_rgb(surface, color, rect)
        return
    keep = round(255 * (1.0 - a))
    surface.fill((keep, keep, keep), rect, special_flags=pygame.BLEND_RGB_MULT)
    surface.fill(tuple(round(c * a) for c in color), rect, special_flags=pygame.BLEND_RGB_ADD)


def to_black(surface: pygame.Surface, t: float,
             rect: pygame.Rect | Sequence[int] | None = None) -> None:
    """Fade ``surface`` (or ``rect`` of it) toward black in place: ``t`` 0 leaves it, 1 makes
    it black. One ``BLEND_RGB_MULT`` fill (the title fade-in and ``BlackFadeScreen``, F10
    ``04`` §7.5)."""
    t = _clamp01(t)
    if t <= 0.0:
        return
    if t >= 1.0:
        _fill_rgb(surface, (0, 0, 0), rect)
        return
    keep = round(255 * (1.0 - t))
    surface.fill((keep, keep, keep), rect, special_flags=pygame.BLEND_RGB_MULT)


def surface_cost(surface: pygame.Surface) -> int:
    """Bytes a built surface holds, for ``SizedLru`` costs (callers add their overhead)."""
    width, height = surface.get_size()
    return width * height * surface.get_bytesize()


# --- internals -------------------------------------------------------------------------------

def _drawn_frame(spec: FrameSpec, width: int, height: int, scale: float) -> pygame.Surface:
    k = FRAME_SUPERSAMPLE
    w, h = width * k, height * k
    radius = min(round(max(0, spec.corner_radius) * scale), min(width, height) // 2) * k
    border = 0
    if spec.border_width > 0:
        border = min(max(1, round(spec.border_width * scale)), (min(width, height) + 1) // 2) * k
    fill_alpha = round(255 * _clamp01(spec.fill_opacity))
    big = _blank((w, h), spec.border_color if border else spec.fill_color)
    if border:
        _round_rect(big, (*spec.border_color, 255), pygame.Rect(0, 0, w, h), radius,
                    spec.corners)
        inner = pygame.Rect(border, border, w - 2 * border, h - 2 * border)
        if inner.width > 0 and inner.height > 0:
            # Overwrites the border's pixels (no blending on SRCALPHA, S0 note 8).
            _round_rect(big, (*spec.fill_color, fill_alpha), inner, max(0, radius - border),
                        spec.corners)
    else:
        _round_rect(big, (*spec.fill_color, fill_alpha), pygame.Rect(0, 0, w, h), radius,
                    spec.corners)
    return pygame.transform.smoothscale(big, (width, height))


def _round_rect(surface: pygame.Surface, color: tuple[int, int, int, int], rect: pygame.Rect,
                radius: int, corners: Corners) -> None:
    if radius <= 0:
        surface.fill(color, rect)
        return
    tl, tr, bl, br = (radius if on else 0 for on in corners)
    pygame.draw.rect(surface, color, rect, 0, 0, tl, tr, bl, br)


def _nine_slice(source: pygame.Surface, width: int, height: int, slice_width: int,
                scale: float) -> pygame.Surface:
    sw, sh = source.get_size()
    # Source corner in px (== canvas units), leaving at least 1 px of edge and center.
    s = max(0, min(int(slice_width), (sw - 1) // 2, (sh - 1) // 2))
    d = 0
    if s > 0:
        d = min(max(1, round(s * scale)), width // 2, height // 2)    # device corner, px
    out = pygame.Surface((width, height), pygame.SRCALPHA, 32)
    out.fill((0, 0, 0, 0))
    src_cols = (0, s, sw - s, sw)
    src_rows = (0, s, sh - s, sh)
    dst_cols = (0, d, width - d, width)
    dst_rows = (0, d, height - d, height)
    for row in range(3):
        for col in range(3):
            src = pygame.Rect(src_cols[col], src_rows[row], src_cols[col + 1] - src_cols[col],
                              src_rows[row + 1] - src_rows[row])
            dst = pygame.Rect(dst_cols[col], dst_rows[row], dst_cols[col + 1] - dst_cols[col],
                              dst_rows[row + 1] - dst_rows[row])
            if src.width <= 0 or src.height <= 0 or dst.width <= 0 or dst.height <= 0:
                continue
            piece = source.subsurface(src)
            if piece.get_size() != dst.size:
                piece = pygame.transform.smoothscale(piece, dst.size)
            # The pieces never overlap and ``out`` starts at 0, so ADD is an exact copy.
            out.blit(piece, dst.topleft, special_flags=pygame.BLEND_RGBA_ADD)
    return out


def _rgba(image: pygame.Surface) -> pygame.Surface:
    """``image`` as 32-bit with per-pixel alpha (``smoothscale`` needs 24/32 bits). Converts
    against a 1×1 SRCALPHA surface, which needs no window (S0 note 4)."""
    if image.get_flags() & pygame.SRCALPHA and image.get_bitsize() == 32:
        return image
    return image.convert(pygame.Surface((1, 1), pygame.SRCALPHA, 32))


def _blank(size: Size, color: RGB) -> pygame.Surface:
    surface = pygame.Surface(size, pygame.SRCALPHA, 32)
    surface.fill((*color, 0))
    return surface


def _multiply_alpha(surface: pygame.Surface, opacity: float) -> None:
    a = round(255 * _clamp01(opacity))
    if a < 255:
        surface.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)


def _fill_rgb(surface: pygame.Surface, color: RGB,
              rect: pygame.Rect | Sequence[int] | None) -> None:
    """Set RGB to ``color`` and leave alpha as it is (MULT by 0, then ADD)."""
    surface.fill((0, 0, 0), rect, special_flags=pygame.BLEND_RGB_MULT)
    surface.fill(tuple(color), rect, special_flags=pygame.BLEND_RGB_ADD)


def _clamp01(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else float(value)
