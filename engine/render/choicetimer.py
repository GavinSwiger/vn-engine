"""A timed menu's countdown panel: its geometry and its drawing (F51 ``01-design.md`` §6.1,
``04-technical.md`` §7.4; 07 I-4).

Why this module exists: the panel is the first item of F07's choice stack (a header in
``ChoiceLayout``) but is never a button, so its boxes and its drawing live apart from the
buttons'. ``timer_geometry`` is pure arithmetic in canvas units, so the design's numbers are
unit-tested without pygame; ``TimerPanelView`` draws one panel per frame for a few blits.

- **Panel**: ``choice.width`` wide, centered (the header rect ``ChoiceLayout`` places);
  ``t + 12`` tall, ``t`` the number's size, ``half_up(24 × the player's text scale)``
  clamped to 20–36 (36 tall at 100 %, 48 at 150 %).
- **Number**: right-aligned ``TIMER_INSET`` inside the right edge, in a slot as wide as
  "60" in ``choice.text_font`` at ``t``, vertically centered.
- **Bar**: ``TIMER_BAR_HEIGHT`` tall, vertically centered, from ``TIMER_INSET`` inside the
  left edge to ``TIMER_INSET`` left of the number slot. The fill is ``track width ×
  fraction`` wide from the left, at least 0.
- **Frame**: ``choice.fill_color`` at ``choice.fill_opacity``, ``choice.border_color``
  ``choice.border_width``, radius ``min(choice.corner_radius, height / 2)``; no frame image.
  Built with ``frames.build_frame`` and cached (≤ ``TIMER_SHAPE_ENTRIES``, view-owned,
  outside the asset budget, as the buttons' shapes).
- **Fade** (F07 I-13): at alpha < 1 the panel draws into one kept panel-sized per-pixel
  alpha scratch blitted with ``set_alpha``; the scratch is freed at alpha 1.

The colors (``timer_colors``: fill follows ``choice.marker.fill_color``, track follows
``choice.focused.fill_color``, C1) are passed in by the caller.
"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pygame

from engine.render.canvas import RGB, Canvas, RenderQuality
from engine.render.choices import half_up
from engine.render.frames import FrameSpec, build_frame
from engine.render.textlayout import FaceSet, render_safe

if TYPE_CHECKING:
    from engine.core.config_schema import ChoiceTheme

TIMER_NUMBER_BASE: Final = 24            # the number's size at 100 % text
TIMER_NUMBER_MIN: Final = 20
TIMER_NUMBER_MAX: Final = 36
TIMER_PAD: Final = 12                    # panel height = t + 12
TIMER_INSET: Final = 16                  # bar start and number end, from the panel's edges
TIMER_BAR_HEIGHT: Final = 8
TIMER_SLOT_TEXT: Final = "60"            # the number slot is as wide as this
TIMER_SHAPE_ENTRIES: Final = 2

Rect = tuple[float, float, float, float]


def number_size(text_scale: float) -> int:
    """``t``: ``half_up(24 × text_scale)``, 20–36."""
    return max(TIMER_NUMBER_MIN, min(TIMER_NUMBER_MAX, half_up(TIMER_NUMBER_BASE * text_scale)))


def panel_height(text_scale: float) -> int:
    """The panel's height at ``text_scale``: ``t + 12``."""
    return number_size(text_scale) + TIMER_PAD


@dataclass(frozen=True, slots=True)
class TimerGeometry:
    """The panel's boxes in canvas units: ``panel`` (the header rect), ``track`` (the whole
    bar), ``slot`` (the number's slot: the number is right-aligned in it), and ``size``
    (``t``, the number's text size)."""

    panel: Rect
    track: Rect
    slot: Rect
    size: int

    def fill(self, fraction: float) -> Rect:
        """The bar's filled part for ``fraction`` (0–1) of the time left."""
        x, y, w, h = self.track
        return (x, y, max(0.0, w * max(0.0, min(1.0, fraction))), h)


def timer_geometry(panel: Rect, size: int, slot_width: float) -> TimerGeometry:
    """The boxes of a panel at ``panel`` whose number is ``size`` tall and whose slot (the
    width of "60" at that size) is ``slot_width`` wide (01 §6.1)."""
    x, y, w, h = panel
    slot_right = x + w - TIMER_INSET
    slot_left = slot_right - slot_width
    track_left = x + TIMER_INSET
    track_w = max(0.0, slot_left - TIMER_INSET - track_left)
    track = (track_left, y + (h - TIMER_BAR_HEIGHT) / 2, track_w, float(TIMER_BAR_HEIGHT))
    return TimerGeometry(panel, track, (slot_left, y, slot_width, h), size)


class TimerPanelView:
    """Draws the panel: frame (cached), track, fill, then the number's raster
    (``assets.text_line``). ``faces`` is the choice faces (``choice.text_font`` as the
    regular face when usable)."""

    def __init__(self, assets: Any, theme: "ChoiceTheme", faces: FaceSet) -> None:
        self.assets = assets
        self.theme = theme
        self.faces = faces
        self._shapes: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._scratch: pygame.Surface | None = None

    @property
    def shape_count(self) -> int:
        return len(self._shapes)

    @property
    def scratch(self) -> pygame.Surface | None:
        """The fade scratch while one is kept (freed at alpha 1)."""
        return self._scratch

    def _font(self, size_px: int) -> Any:
        face = self.faces.for_style(False, False)
        return self.assets.font(face.ref, max(1, size_px), bundled=face.bundled,
                                synth=face.synth)

    def slot_width(self, size: int) -> float:
        """The width of "60" at text size ``size``, in canvas units."""
        return float(self._font(size).font.size(TIMER_SLOT_TEXT)[0])

    def geometry(self, panel: Rect, size: int) -> TimerGeometry:
        return timer_geometry(panel, size, self.slot_width(size))

    def draw(self, canvas: Canvas, geometry: TimerGeometry, fraction: float, number: int,
             colors: tuple[RGB, RGB], *, alpha: float = 1.0) -> None:
        """The panel at ``alpha`` with the bar at ``fraction`` and ``number`` shown;
        ``colors`` is (fill, track)."""
        surface = canvas.surface
        assert surface is not None
        if alpha <= 0.0:
            return
        box = canvas.rect_to_px(geometry.panel)
        if box.width <= 0 or box.height <= 0:
            return
        if alpha >= 1.0:
            self._scratch = None
            self._paint(canvas, surface, geometry, fraction, number, colors, (0, 0))
            return
        scratch = self._scratch
        if scratch is None or scratch.get_size() != box.size:
            scratch = self._scratch = None
            scratch = self._scratch = pygame.Surface(box.size, pygame.SRCALPHA, 32)
        scratch.fill((0, 0, 0, 0))
        scratch.set_alpha(None)
        self._paint(canvas, scratch, geometry, fraction, number, colors, box.topleft)
        scratch.set_alpha(max(0, min(255, round(alpha * 255))))
        surface.blit(scratch, box.topleft)

    def _paint(self, canvas: Canvas, target: pygame.Surface, geometry: TimerGeometry,
               fraction: float, number: int, colors: tuple[RGB, RGB],
               origin: tuple[int, int]) -> None:
        ox, oy = origin
        box = canvas.rect_to_px(geometry.panel)
        target.blit(self._shape(canvas, geometry.panel), (box.x - ox, box.y - oy))
        fill_color, track_color = colors
        track = canvas.rect_to_px(geometry.track).move(-ox, -oy)
        if track.width > 0 and track.height > 0:
            target.fill(track_color, track)
        fill = canvas.rect_to_px(geometry.fill(fraction)).move(-ox, -oy)
        if fill.width > 0 and fill.height > 0:
            target.fill(fill_color, fill)
        font = self._font(round(geometry.size * canvas.scale))
        raster = self.assets.text_line(font, render_safe(str(number)), self.theme.text_color)
        sx, sy, sw, sh = geometry.slot
        right = canvas.px(sx + sw, 0)[0]
        middle = canvas.px(0, sy + sh / 2)[1]
        target.blit(raster, (right - raster.get_width() - ox,
                             middle - raster.get_height() // 2 - oy))

    def _shape(self, canvas: Canvas, panel: Rect) -> pygame.Surface:
        _x, _y, w, h = panel
        scale = canvas.scale
        key = (w, h, scale)
        shape = self._shapes.get(key)
        if shape is not None:
            self._shapes.move_to_end(key)
            return shape
        theme = self.theme
        spec = FrameSpec(theme.fill_color, theme.fill_opacity, theme.border_color,
                         theme.border_width, int(min(theme.corner_radius, h / 2)),
                         theme.frame_slice_width)
        shape = build_frame(spec, (max(1, round(w * scale)), max(1, round(h * scale))), scale)
        if canvas.quality is RenderQuality.FINAL:
            self._shapes[key] = shape
            if len(self._shapes) > TIMER_SHAPE_ENTRIES:
                self._shapes.popitem(last=False)
        return shape


__all__ = ["TIMER_BAR_HEIGHT", "TIMER_INSET", "TIMER_NUMBER_MAX", "TIMER_NUMBER_MIN",
           "TIMER_PAD", "TimerGeometry", "TimerPanelView", "number_size", "panel_height",
           "timer_geometry"]
