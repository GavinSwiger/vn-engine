"""The painter: panels, widget states, markers, and labels, with every shape cached.

Why this module exists: every widget draws through one ``Painter`` so the States table of
F10 ``03-ui`` (normal, focused, pressed, disabled, on/off, selected) looks the same on every
screen, and so shapes are built once per (area, state, device size) instead of every frame.
F10 ``04`` §11 measured rebuilding shapes every frame at 7.8 ms p50 / 11 ms p99 at 1080p
(about 29 ms on the reference machine), so caching is required: shapes are ``SizedLru``
entries in the shared asset budget, keyed ``("ui-shape", area, state, w_px, h_px, …)``.

The painter knows the *drawing rules* (where the marker, pip, and bar go; which state a
``Look`` draws; the label fit rule of UI-F10-02). The *values* come from a ``StyleSource``:
F10's resolved theme (step 4) implements it from the ``[theme.*]`` tokens; ``StyleTable`` is
a plain mapping for tests and tools. Frame images arrive as ``ImageRef``s; a placeholder
(missing or unusable file) draws the state's fill and border instead, never the
checkerboard (ui-system §3, UI-F10-01).

One ``Painter`` per launch, bound to the canvas at each draw (``bind``). It never keeps
``canvas.surface``, which is only valid during its frame (S0 note 2). At FAST quality (while a
resize settles) shapes come from the cache at the last FINAL scale and are
``transform.scale``d, uncached (F01's rule), so a resize builds nothing per frame.
"""

import dataclasses
import itertools
import math
from collections import OrderedDict
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal, Protocol

import pygame

from engine.core.constants import ENTRY_OVERHEAD
from engine.render.canvas import Anchor, RenderQuality
from engine.render.frames import (
    FrameSpec,
    build_ellipse,
    build_frame,
    build_triangle,
    surface_cost,
)
from engine.render.text import FontSpec, text_width
from engine.ui.layouts import TEXT_MIN_SIZE, TEXT_STEP, cut_to_width

if TYPE_CHECKING:
    from engine.render.assets import ImageRef
    from engine.render.canvas import Canvas

RGB = tuple[int, int, int]
State = Literal["normal", "focused", "pressed", "disabled"]

SHAPE_KEY: Final = "ui-shape"
HEADING_AREA: Final = "panel.heading"
LABEL_MIN_SIZE: Final = TEXT_MIN_SIZE   # UI-F10-02: step down by 2, not below 24, then "…"
LABEL_STEP: Final = TEXT_STEP
FIT_CACHE_ENTRIES: Final = 512

# Marker, pip, and bar geometry in canvas units (F10 03-ui widget table).
MARKER_SIZE: Final = (12, 16)       # right-pointing triangle
MARKER_INSET: Final = 12            # from the left edge
PIP_DIAMETER: Final = 12
PIP_INSET: Final = 24               # pip center from the right edge
PIP_RING: Final = 2                 # "off" ring width
BAR_WIDTH: Final = 6
BAR_INSET: Final = 4                # from the left edge
BAR_MARGIN: Final = 24              # bar height = box height − 24

_generations = itertools.count(1)


class BoxLike(Protocol):
    """A rectangle in canvas units (``ui.focus.Box``)."""
    x: float
    y: float
    w: float
    h: float


class LookLike(Protocol):
    """How a widget looks this frame (``ui.widgets.Look``)."""
    state: State
    on: bool | None
    selected: bool


@dataclass(frozen=True)
class PaintStyle:
    """One area in one state, resolved from theme tokens.

    ``frame`` None draws no fill or border (row widgets at rest sit on a panel). ``image``
    is that state's ``frame_image``; it replaces ``frame`` unless it is a placeholder.
    ``font.size`` is the size at 100% text; the painter applies ``text_scale``. ``colors``
    holds an area's other parts by name (a toggle's ``"track"``, a list's ``"divider"``),
    so widgets read every color through the painter (``color``)."""

    frame: FrameSpec | None = None
    image: "ImageRef | None" = None
    font: FontSpec = FontSpec(None, 28)
    text_color: RGB = (0x3D, 0x2B, 0x36)
    marker_color: RGB = (0xA0, 0x28, 0x60)
    side_padding: int = 32
    colors: Mapping[str, RGB] = field(default_factory=dict)

    def color(self, name: str, default: RGB = (0, 0, 0)) -> RGB:
        """The color of part ``name`` (``default`` when the style has none)."""
        return self.colors.get(name, default)


class StyleSource(Protocol):
    def style(self, area: str, state: str) -> PaintStyle:
        """The style of ``area`` (``"panel"``, ``"button"``, ``"panel.heading"``, …) in
        ``state`` (``"normal"``, ``"focused"``, ``"pressed"``, ``"disabled"``,
        ``"selected"``). Must return the same value for the same arguments for the
        painter's lifetime (shapes are cached by area and state); call
        ``Painter.invalidate`` after a change."""
        ...


class StyleTable:
    """A ``StyleSource`` from a mapping: ``(area, state)``, else ``(area, "normal")``, else
    ``default``."""

    def __init__(self, styles: dict[tuple[str, str], PaintStyle], *,
                 default: PaintStyle = PaintStyle()) -> None:
        self._styles = dict(styles)
        self._default = default

    def style(self, area: str, state: str) -> PaintStyle:
        found = self._styles.get((area, state))
        if found is None:
            found = self._styles.get((area, "normal"), self._default)
        return found


@dataclass(frozen=True)
class Fit:
    """A label after the fit rule: the text drawn, its size, and whether "…" was needed
    (W68's condition)."""
    text: str
    size: int
    truncated: bool


def fit_label(text: str, font_at: Callable[[int], "pygame.font.Font"], size: int,
              width: float, *, min_size: int = LABEL_MIN_SIZE, step: int = LABEL_STEP) -> Fit:
    """UI-F10-02: ``text`` at ``size`` if it fits in ``width`` (canvas units, reference
    metrics); else the size steps down by ``step`` while it is at least ``min_size``; if no
    size fits, the smallest is shortened with "…". A ``size`` below ``min_size`` is tried
    alone. ``font_at(size)`` gives the reference font at that size. The cut is
    ``layouts.cut_to_width``'s, so it never splits a grapheme cluster."""
    sizes = [size]
    while sizes[-1] - step >= min_size:
        sizes.append(sizes[-1] - step)
    for candidate in sizes:
        if text_width(font_at(candidate), text) <= width:
            return Fit(text, candidate, False)
    smallest = sizes[-1]

    def measure(part: str, at: int) -> float:
        return text_width(font_at(at), part)

    return Fit(cut_to_width(text, max(0.0, width), smallest, measure), smallest, True)


def frame_state(look: LookLike) -> str:
    """The style state a ``Look`` draws (F10 03-ui States): disabled wins; focused and
    pressed keep their look when selected too (the bar is added); else selected; else
    normal."""
    if look.state == "disabled":
        return "disabled"
    if look.state in ("focused", "pressed"):
        return look.state
    return "selected" if look.selected else "normal"


class Painter:
    """Draws panels and widgets in canvas units on the bound canvas, with cached shapes."""

    def __init__(self, styles: StyleSource, *,
                 text_scale: Callable[[], float] | None = None) -> None:
        """``text_scale`` returns F16's text size ÷ ``textbox.text_size`` (1.0 until F16)."""
        self.styles = styles
        self._text_scale = text_scale
        self._canvas: "Canvas | None" = None
        self._gen = next(_generations)
        self._fits: OrderedDict[tuple, Fit] = OrderedDict()
        self.builds = 0              # shapes built so far (tests, TR-F10-04)

    # -- binding ------------------------------------------------------------------------

    def bind(self, canvas: "Canvas") -> None:
        """Draw on ``canvas`` from now on. Call at the start of each draw."""
        self._canvas = canvas

    @property
    def canvas(self) -> "Canvas":
        assert self._canvas is not None, "Painter.bind() has not been called"
        return self._canvas

    def text_scale(self) -> float:
        """F16's text size ÷ ``textbox.text_size``; 1.0 without F16."""
        return 1.0 if self._text_scale is None else self._text_scale()

    def set_text_scale(self, text_scale: Callable[[], float] | None) -> None:
        """Where ``text_scale()`` comes from from now on (F16's ``install_settings_ui`` on
        the shell's painter; None: 1.0). Menus lay out again at their next update."""
        self._text_scale = text_scale

    def style(self, area: str, state: str = "normal") -> PaintStyle:
        return self.styles.style(area, state)

    def invalidate(self) -> None:
        """Forget every shape and fit (theme reload, F39): this painter's cached shapes are
        discarded and the next draws build new ones."""
        if self._canvas is not None:
            cache = self._canvas.assets.cache
            for key in cache.keys():
                if key and key[0] == SHAPE_KEY and key[-1] == self._gen:
                    cache.discard(key)
        self._gen = next(_generations)
        self._fits.clear()

    # -- panels and widgets -------------------------------------------------------------

    def panel(self, box: BoxLike, area: str = "panel", *, alpha: float = 1.0) -> None:
        """``area``'s normal fill and border (or frame image) filling ``box``."""
        self._frame(box, area, "normal", alpha)

    def widget_frame(self, box: BoxLike, area: str, look: LookLike, *,
                     marker: bool = True) -> None:
        """The States table for a button-like widget: the state's frame, then the focus
        marker (focused or pressed, unless ``marker`` is False: grid cells whose contents
        need the corner), the on/off pip (``look.on`` not None), and the selected bar."""
        state = frame_state(look)
        self._frame(box, area, state, 1.0)
        color = self.style(area, state).marker_color
        cy = box.y + box.h / 2
        if look.selected and state != "disabled":
            bar_h = max(0.0, box.h - BAR_MARGIN)
            self.rect(_Box(box.x + BAR_INSET, cy - bar_h / 2, BAR_WIDTH, bar_h), color)
        if marker and look.state in ("focused", "pressed"):
            mw, mh = MARKER_SIZE
            self.triangle(_Box(box.x + MARKER_INSET, cy - mh / 2, mw, mh), color)
        if look.on is not None:
            r = PIP_DIAMETER / 2
            self.ellipse(_Box(box.x + box.w - PIP_INSET - r, cy - r, PIP_DIAMETER,
                              PIP_DIAMETER), color, ring=0 if look.on else PIP_RING)

    def label(self, text: str, box: BoxLike, *, area: str, look: LookLike,
              align: Literal["left", "center", "right"] = "center") -> Fit:
        """``text`` in the state's font and color, vertically centered in ``box``, inside
        ``side_padding`` on each side, fitted by UI-F10-02 (``fit``). Returns the fit."""
        state = frame_state(look)
        style = self.style(area, state)
        width = box.w - 2 * style.side_padding
        fit = self.fit(text, area, width, state)
        cy = box.y + box.h / 2
        if align == "left":
            pos, anchor = (box.x + style.side_padding, cy), "midleft"
        elif align == "right":
            pos, anchor = (box.x + box.w - style.side_padding, cy), "midright"
        else:
            pos, anchor = (box.x + box.w / 2, cy), "center"
        if fit.text:
            self.canvas.draw_text(fit.text, dataclasses.replace(style.font, size=fit.size),
                                  style.text_color, pos, anchor=anchor)
        return fit

    def heading(self, text: str, pos: tuple[float, float], *,
                anchor: Anchor = "topleft") -> tuple[float, float, float, float]:
        """A panel heading (``panel.heading`` style) at ``pos``. Returns its bounds."""
        return self.text(text, pos, area=HEADING_AREA, anchor=anchor)

    def text(self, text: str, pos: tuple[float, float], *, area: str = "panel",
             state: str = "normal", anchor: Anchor = "topleft", color: RGB | None = None,
             max_width: float | None = None) -> tuple[float, float, float, float]:
        """One line of ``area``'s text at the current text scale (row labels, "On"/"Off",
        slider values). Returns the drawn bounds in canvas units."""
        style = self.style(area, state)
        font = dataclasses.replace(style.font, size=self.scaled_size(style.font.size))
        return self.canvas.draw_text(text, font, color or style.text_color, pos,
                                     anchor=anchor, max_width=max_width,
                                     max_lines=None if max_width is None else 1)

    def scaled_size(self, size: int) -> int:
        """``size`` at the current text scale."""
        return max(1, round(size * self.text_scale()))

    def fit(self, text: str, area: str, width: float, state: str = "normal") -> Fit:
        """UI-F10-02's fit of ``text`` into ``width`` canvas units with ``area``'s font at the
        current text scale; laid out once per (text, font, size, width)."""
        style = self.style(area, state)
        size = self.scaled_size(style.font.size)
        key = (text, dataclasses.replace(style.font, size=0), size, round(width, 3))
        found = self._fits.get(key)
        if found is not None:
            self._fits.move_to_end(key)
            return found
        canvas = self.canvas
        found = fit_label(text, lambda s: canvas.font_handle(style.font, s).font, size, width,
                          min_size=min(LABEL_MIN_SIZE, size))
        self._fits[key] = found
        if len(self._fits) > FIT_CACHE_ENTRIES:
            self._fits.popitem(last=False)
        return found

    # -- primitives (cached) --------------------------------------------------------------

    def shape(self, box: BoxLike, spec: FrameSpec, *, image: "ImageRef | None" = None,
              alpha: float = 1.0) -> None:
        """Any ``FrameSpec`` filling ``box`` (toggle tracks, slider thumbs, scrollbars,
        quick-menu chips), cached by the spec itself."""
        image = image if image is not None and not image.is_placeholder else None
        state = (spec, None if image is None else image.ref)
        self._blit("shape", state, box, alpha,
                   lambda size, scale: build_frame(spec, size, scale, self._image(image)))

    def triangle(self, box: BoxLike, color: RGB, *,
                 direction: Literal["right", "left", "up", "down"] = "right") -> None:
        """A triangle filling ``box``, pointing ``direction`` (the focus marker)."""
        self._blit("triangle", (tuple(color), direction), box, 1.0,
                   lambda size, _scale: build_triangle(size, color, direction=direction))

    def ellipse(self, box: BoxLike, color: RGB, *, ring: float = 0.0) -> None:
        """The ellipse inscribed in ``box``; a ring ``ring`` canvas units wide if > 0."""
        self._blit("ellipse", (tuple(color), ring), box, 1.0,
                   lambda size, scale: build_ellipse(size, color, ring_px=ring * scale))

    def rect(self, box: BoxLike, color: RGB) -> None:
        """An opaque rectangle (dividers, the selected bar): a plain fill, nothing cached."""
        self.canvas.fill(tuple(color), (box.x, box.y, box.w, box.h))

    # -- internals ----------------------------------------------------------------------

    def _frame(self, box: BoxLike, area: str, state: str, alpha: float) -> None:
        style = self.style(area, state)
        image = style.image if style.image is not None and not style.image.is_placeholder \
            else None
        if style.frame is None and image is None:
            return
        spec = style.frame if style.frame is not None else FrameSpec((0, 0, 0))
        self._blit(area, state, box, alpha,
                   lambda size, scale: build_frame(spec, size, scale, self._image(image)))

    def _image(self, image: "ImageRef | None") -> pygame.Surface | None:
        return None if image is None else self.canvas.assets.surface(image)

    def _blit(self, area: str, state: Hashable, box: BoxLike, alpha: float,
              build: Callable[[tuple[int, int], float], pygame.Surface]) -> None:
        if alpha <= 0.0:
            return
        canvas = self.canvas
        target = canvas.rect_to_px((box.x, box.y, box.w, box.h))
        if target.width <= 0 or target.height <= 0:
            return
        final = canvas.final_scale
        if canvas.quality is RenderQuality.FAST and final is not None \
                and final != canvas.scale:
            size = (max(1, math.floor(box.w * final + 0.5)),
                    max(1, math.floor(box.h * final + 0.5)))
            surface = self._cached(area, state, size, final, build)
            surface = pygame.transform.scale(surface, target.size)     # uncached (F01)
        else:
            surface = self._cached(area, state, target.size, canvas.scale, build)
        dest = canvas.surface
        assert dest is not None
        if alpha >= 1.0:
            dest.blit(surface, target.topleft)
            return
        previous = surface.get_alpha()
        surface.set_alpha(round(255 * alpha))
        try:
            dest.blit(surface, target.topleft)
        finally:
            surface.set_alpha(previous)

    def _cached(self, area: str, state: Hashable, size: tuple[int, int], scale: float,
                build: Callable[[tuple[int, int], float], pygame.Surface]) -> pygame.Surface:
        assets = self.canvas.assets
        frame = assets.time.frame
        key = (SHAPE_KEY, area, state, size[0], size[1], round(scale * 10000), self._gen)
        surface = assets.cache.get(key, frame)
        if surface is None:
            surface = build(size, scale)
            self.builds += 1
            assets.cache.put(key, surface, surface_cost(surface) + ENTRY_OVERHEAD, frame)
        return surface


@dataclass(frozen=True)
class _Box:
    x: float
    y: float
    w: float
    h: float
