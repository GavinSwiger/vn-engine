"""The drawing API: canvas units in, device pixels out.

Why this module exists: every position and size an author or feature gives is in canvas
units on the fixed 1280×720 canvas (PR-F01-21), but drawing happens directly at the
device resolution of the letterboxed viewport, so text and art stay sharp at 1440p and 4K
and nothing scales the whole frame (ADR-0001). ``Canvas`` is the one place where canvas
units become pixels: positions are rounded half up per axis, so adjacent rectangles never
gap or overlap (``rect_to_px``), images come from cached device-size variants
(``AssetManager.scaled``), and text is laid out in canvas units and rasterized at device
size (§7.6.3).

``surface`` is a subsurface of the window framebuffer. Spike S0 found that drawing into a
subsurface taken before a framebuffer resize crashes the process (S0 note 2), so ``App``
calls ``bind`` at the start of every presented frame (about 0.4 µs) and ``surface`` is only
valid during that frame.
"""

import math
from enum import Enum
from typing import TYPE_CHECKING, Literal

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.render.text import (
    Face,
    FontHandle,
    FontSpec,
    Synth,
    fit_line,
    text_width,
    wrap_lines,
)

if TYPE_CHECKING:
    from engine.render.assets import AssetManager, ImageRef

RGB = tuple[int, int, int]
CanvasRect = tuple[float, float, float, float]
Anchor = Literal["topleft", "midtop", "topright", "midleft", "center", "midright",
                 "bottomleft", "midbottom", "bottomright"]

# Fraction of the box width / height to subtract from the anchor point.
_ANCHORS: dict[str, tuple[float, float]] = {
    "topleft": (0.0, 0.0), "midtop": (0.5, 0.0), "topright": (1.0, 0.0),
    "midleft": (0.0, 0.5), "center": (0.5, 0.5), "midright": (1.0, 0.5),
    "bottomleft": (0.0, 1.0), "midbottom": (0.5, 1.0), "bottomright": (1.0, 1.0),
}
_ALIGN = {"left": 0.0, "center": 0.5, "right": 1.0}


class RenderQuality(Enum):
    FINAL = "final"        # smoothscale (or scale for "pixel"); results cached
    FAST = "fast"          # transform.scale; results NOT cached; only while a resize settles


class Canvas:
    """Draws in canvas units onto ``surface`` (device pixels, viewport.w × viewport.h)."""

    def __init__(self, assets: "AssetManager") -> None:
        self.assets = assets
        self.size: tuple[int, int] = CANVAS_SIZE
        self.viewport: Viewport | None = None
        self.surface: pygame.Surface | None = None
        self.quality = RenderQuality.FINAL
        self.final_scale: float | None = None   # canvas.scale at the last FINAL bind

    def bind(self, framebuffer: pygame.Surface, viewport: Viewport,
             quality: RenderQuality) -> None:
        """surface = framebuffer.subsurface(viewport rect). If quality is FINAL,
        final_scale = scale. Asserts the rect lies inside the framebuffer."""
        rect = pygame.Rect(viewport.x, viewport.y, viewport.w, viewport.h)
        assert framebuffer.get_rect().contains(rect), (rect, framebuffer.get_size())
        self.surface = framebuffer.subsurface(rect)
        self.viewport = viewport
        self.quality = quality
        if quality is RenderQuality.FINAL:
            self.final_scale = self.scale

    # -- scale and coordinates --

    @property
    def scale_x(self) -> float:
        return 1.0 if self.viewport is None else self.viewport.scale_x

    @property
    def scale_y(self) -> float:
        return 1.0 if self.viewport is None else self.viewport.scale_y

    @property
    def scale(self) -> float:
        return min(self.scale_x, self.scale_y)

    def px(self, x: float, y: float) -> tuple[int, int]:
        """Canvas units → device pixels inside ``surface``: floor(v·s + 0.5) per axis."""
        return math.floor(x * self.scale_x + 0.5), math.floor(y * self.scale_y + 0.5)

    def rect_to_px(self, rect: CanvasRect) -> pygame.Rect:
        """Both corners rounded with ``px``, so rectangles that touch in canvas units
        touch in pixels too (no gap, no overlap)."""
        x, y, w, h = rect
        left, top = self.px(x, y)
        right, bottom = self.px(x + w, y + h)
        return pygame.Rect(left, top, right - left, bottom - top)

    # -- drawing --

    def fill(self, color: RGB | tuple[int, int, int, int],
             rect: CanvasRect | None = None) -> None:
        """Fill the canvas (or ``rect``) with ``color``; a 4-tuple with alpha < 255
        blends over what is there."""
        surface = self._target()
        area = surface.get_rect() if rect is None else self.rect_to_px(rect)
        if len(color) == 4 and color[3] < 255:
            if area.width <= 0 or area.height <= 0:
                return
            layer = pygame.Surface(area.size, pygame.SRCALPHA)
            layer.fill(color)
            surface.blit(layer, area.topleft)
        else:
            surface.fill(tuple(color[:3]), area)

    def draw_image(self, image: "ImageRef", pos: tuple[float, float], *,
                   anchor: Anchor = "topleft", alpha: int = 255) -> None:
        """Draw ``image`` (canvas size == source pixel size) with its ``anchor`` point at
        ``pos`` (canvas units), using the cached device-size variant."""
        surface = self._target()
        variant = self.assets.scaled(image, self.scale_x, self.scale_y, self.quality)
        fx, fy = _ANCHORS[anchor]
        dest = self.px(pos[0] - image.size[0] * fx, pos[1] - image.size[1] * fy)
        if alpha >= 255:
            surface.blit(variant, dest)
            return
        previous = variant.get_alpha()
        variant.set_alpha(max(0, alpha))
        try:
            surface.blit(variant, dest)
        finally:
            variant.set_alpha(previous)

    def draw_text(self, text: str, font: FontSpec, color: RGB, pos: tuple[float, float], *,
                  anchor: Anchor = "topleft", max_width: float | None = None,
                  align: Literal["left", "center", "right"] = "left",
                  line_spacing: float = 1.0, max_lines: int | None = None
                  ) -> tuple[float, float, float, float]:
        """Layout in canvas units, raster per §7.6.3. With max_lines, the last kept line is
        shortened with fit_line(..., suffix='…'). Returns drawn bounds in canvas units."""
        surface = self._target()
        layout = self.font_handle(font, font.size)
        lines = self.layout_lines(text, font, max_width, max_lines)
        widths = [text_width(layout.font, line) for line in lines]
        line_height = layout.font.get_linesize() * line_spacing
        block_w = float(max(widths, default=0))
        block_h = float(layout.font.get_linesize() + line_height * (len(lines) - 1)) \
            if lines else 0.0
        fx, fy = _ANCHORS[anchor]
        left = pos[0] - block_w * fx
        top = pos[1] - block_h * fy

        s_now = self.scale
        s_raster = s_now if self.quality is RenderQuality.FINAL or self.final_scale is None \
            else self.final_scale
        raster = self.font_handle(font, max(1, round(font.size * s_raster)))
        for index, (line, width) in enumerate(zip(lines, widths)):
            if not line:
                continue
            rendered = self.assets.text_line(raster, line, color)
            if s_raster != s_now:              # FAST: scale the FINAL-size raster, uncached
                ratio = s_now / s_raster
                rendered = pygame.transform.scale(
                    rendered, (max(1, round(rendered.get_width() * ratio)),
                               max(1, round(rendered.get_height() * ratio))))
            x = left + (block_w - width) * _ALIGN[align]
            surface.blit(rendered, self.px(x, top + index * line_height))
        return left, top, block_w, block_h

    def layout_lines(self, text: str, font: FontSpec, max_width: float | None,
                     max_lines: int | None) -> list[str]:
        """The lines ``draw_text`` draws, from reference metrics only (canvas units), so
        they are the same at every window size and quality (ADR-0001 decision 3)."""
        layout = self.font_handle(font, font.size).font
        lines = wrap_lines(layout, text, max_width)
        if max_lines is not None and len(lines) > max_lines:
            kept = lines[:max(max_lines, 1)]
            rest = " ".join(lines[len(kept) - 1:])
            limit = max_width if max_width is not None else text_width(layout, kept[-1])
            kept[-1] = fit_line(layout, rest, limit)
            lines = kept
        return lines

    def font_handle(self, font: FontSpec, size_px: int) -> FontHandle:
        """``assets.font`` for ``font`` at ``size_px``. The face arguments are passed only when
        they differ from the plain Regular face, so font stand-ins with the older
        ``font(ref, size_px)`` signature keep working."""
        if font.bundled is Face.REGULAR and font.synth is Synth.NONE:
            return self.assets.font(font.ref, size_px)
        return self.assets.font(font.ref, size_px, bundled=font.bundled, synth=font.synth)

    def _target(self) -> pygame.Surface:
        assert self.surface is not None, "Canvas.bind() has not been called"
        return self.surface
