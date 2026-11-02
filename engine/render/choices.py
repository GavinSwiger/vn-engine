"""Choice buttons: their layout (the fit rule, the 2-line cut, centering) and their drawing
(F07 ``04-technical.md`` §7.8; design UI-F07-01, 02; 07 I-3, I-4, I-8, I-13).

Why this module exists: a menu shows 1–6 stacked buttons that must all fit above the
textbox without scrolling, at any text size, and must draw every frame for a few blits.
``ChoiceLayout`` decides sizes and places once per menu (and again only when the text size
or the area changes); ``ChoiceStackView`` owns the button shapes and glyph lists.

**Area** (F17 ``07`` I-2). ``ChoiceArea``: fit steps 0–2 use ``top``..``bottom`` (B) and
``align`` (``"center"``, or ``"top"``); step 3, the last resort, always uses F07's own area,
y 16..``last_bottom``, centered. F07 passes y 16 to ``tab_top − 16`` (a shown or kept line)
or to the floor (no line), with the floor as ``last_bottom`` (F10 C6: the quick menu's pill
top − 4 while it can show, else 704). The defaults are F07's. ``fits(top, bottom)`` says,
without drawing, whether steps 0–2 fit another area (F17 decides its NVL area with it), and
``relaid(area)`` places the same choices in another area without measuring them again. F17's
NVL area is ``(T, B)`` from ``TextboxScreen.choice_area`` with ``align="top"`` (D1: stack
top = T); step 3 stays F17 ``07`` §3.2's F07 last resort.

**Fit rule** (UI-F07-01, ``04`` §7.8). Inner text width ``max(100, width − 2 ×
side_padding)`` (I-4). A button is ``min(2, lines) × round(1.4 × s) + top + bottom padding``
tall, lines counted by F05's ``LineLayout`` at that width. Steps, the first whose stack fits
winning: 0 ``gap`` at s0; 1 gap 4 at s0; 2 gap 4 at s0 − 2, s0 − 4, … ≥ 20; 3 gap 4 at 20 in
16..``last_bottom`` (an overflow there runs off the bottom). Centered: stack top =
``top + floor((area − stack) / 2 + 0.5)`` (half up, I-8). Text over 2 lines keeps line 1;
line 2 is the rest (hard breaks as spaces) cut with "…" like F05's ``fit_line``. Every line
is centered in the text width.

**Drawing** (UI-F07-02). Shapes per state (normal, focused, locked) built with
``frames.build_frame`` (opaque border, fill at its opacity, I-8; or the state's nine-slice
``frame_image`` × its fill opacity) with the focus marker or the padlock drawn in, cached by
``(state, height, scale)``: at most 6, view-owned and outside the asset budget (I-13).
Glyphs: one draw list per layout and scale of each grapheme's cached raster
(``assets.text_line``), drawn with one ``blits``. Focus only swaps the shape: text never
re-rasters, and no shared glyph surface gets an alpha. A locked choice's text is laid out in
the locked color (its ``{color}`` spans keep theirs). The fade-in draws one temporary
composite with an alpha instead (``ChoiceStackView``), freed when the fade ends.
"""

import copy
import math
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.core.graphemes import iter_graphemes
from engine.render.canvas import RGB, Canvas, RenderQuality
from engine.render.frames import FrameSpec, build_frame, build_triangle
from engine.render.text import ELLIPSIS
from engine.render.textlayout import (
    LINE_PITCH,
    FaceSet,
    LayoutContext,
    LineLayout,
    PlacedGlyph,
    is_break_space,
    render_safe,
)
from engine.runtime.commands import Span, Style, TaggedText

if TYPE_CHECKING:
    from engine.core.config_schema import ChoiceTheme

AREA_TOP: Final = 16                     # the choice area starts 16 below the canvas top
AREA_MARGIN: Final = 16                  # B = the name tab's top − 16
LAST_BOTTOM: Final = 704                 # fit step 3 without F10's floor (720 − 16)
MIN_SIZE: Final = 20                     # text never below 20 (UI-F07-01)
MAX_SIZE: Final = 48
TIGHT_GAP: Final = 4                     # steps 1–3
SIZE_STEP: Final = 2
MAX_LINES: Final = 2
MIN_TEXT_WIDTH: Final = 100              # 07 I-4
MARKER_SIZE: Final = (12, 16)            # right-pointing triangle (design §6.2)
LOCK_SIZE: Final = (14, 18)              # padlock at the marker's place
MARK_INSET: Final = 16                   # from the button's left edge
SHAPE_CACHE_ENTRIES: Final = 6           # 3 states × 2 heights (04 §7.8)
_WIDE: Final = 1e9                       # one line, never wrapped

State = Literal["normal", "focused", "locked"]
Align = Literal["center", "top"]


def half_up(value: float) -> int:
    """``floor(value + 0.5)`` (07 I-8: stack centering rounds half up)."""
    return math.floor(value + 0.5)


@dataclass(frozen=True)
class ChoiceArea:
    """Where the stack goes, in canvas units: ``top``, ``bottom``, ``align`` for fit steps
    0–2; ``last_bottom`` ends step 3's 16..``last_bottom`` (see the module docstring)."""

    top: float = AREA_TOP
    bottom: float = LAST_BOTTOM
    last_bottom: float = LAST_BOTTOM
    align: Align = "center"


@dataclass(frozen=True, slots=True)
class TextLine:
    """One drawn line: ``x`` its left edge and ``baseline`` in canvas units; glyph x are
    relative to ``x``; ``width`` its ink advance (hanging spaces excluded)."""

    x: float
    baseline: float
    width: float
    glyphs: tuple[PlacedGlyph, ...]


@dataclass(frozen=True, slots=True)
class ChoiceButton:
    """One button: ``rect`` (x, y, w, h) in canvas units, its 1–2 lines, and whether the
    text was cut (more than 2 lines)."""

    rect: tuple[float, float, float, float]
    lines: tuple[TextLine, ...]
    cut: bool

    def contains(self, pos: tuple[float, float]) -> bool:
        x, y, w, h = self.rect
        return x <= pos[0] < x + w and y <= pos[1] < y + h


@dataclass
class _Fit:
    """One choice laid out at one size: its first ``LineLayout`` page (≤ 2 lines) and
    whether lines follow it."""

    layout: LineLayout
    count: int
    more: bool
    lines: tuple[TextLine, ...] | None = field(default=None)


class ChoiceLayout:
    """The fit rule for ``bodies`` (resolved choice bodies, script order) in ``area``.

    ``assets`` is the layout fonts' source (``AssetManager``, or the M20 fake); ``colors``
    each choice's base text color (``"#rrggbb"``: the text color, or the locked one);
    ``text_size`` is s0 (the choice size × the player's text scale, clamped to 20–48)."""

    def __init__(self, bodies: Sequence[TaggedText], *, assets: Any, faces: FaceSet,
                 theme: "ChoiceTheme", text_size: int, area: ChoiceArea,
                 colors: Sequence[str]) -> None:
        if not 1 <= len(bodies) == len(colors):
            raise AssertionError(f"{len(bodies)} choices, {len(colors)} colors")
        self.bodies = tuple(bodies)
        self.colors = tuple(colors)
        self.assets = assets
        self.faces = faces
        self.theme = theme
        self.s0 = max(MIN_SIZE, min(MAX_SIZE, int(text_size)))
        self.text_width = max(MIN_TEXT_WIDTH, theme.width - 2 * theme.side_padding)
        self._fits: dict[int, list[_Fit]] = {}
        self._place(area)

    def relaid(self, area: ChoiceArea) -> "ChoiceLayout":
        """A new layout of the same choices placed in ``area`` (F17's NVL area), sharing
        this one's per-size measurements, so no choice is measured twice."""
        out = copy.copy(self)
        out._place(area)
        return out

    def _place(self, area: ChoiceArea) -> None:
        """The fit rule in ``area``: the step, size, stack top, and each button."""
        theme = self.theme
        self.area = area
        step, gap, size = self._step(area.top, area.bottom)
        if step == 3:                                 # the last resort: F07's own area
            area_top, area_bottom, align = AREA_TOP, area.last_bottom, "center"
        else:
            area_top, area_bottom, align = area.top, area.bottom, area.align
        self.step = step
        self.gap = gap
        self.size = size
        self.pitch = round(LINE_PITCH * size)
        heights = self._heights(size)
        stack = sum(heights) + gap * (len(heights) - 1)
        if align == "top":
            top = area_top
        else:
            top = max(area_top, area_top + half_up((area_bottom - area_top - stack) / 2))
        self.top = top
        self.bottom = top + stack
        width = theme.width
        x = (CANVAS_SIZE[0] - width) / 2
        text_left = x + (width - self.text_width) / 2
        buttons: list[ChoiceButton] = []
        y = top
        for index, height in enumerate(heights):
            fit = self._fits[size][index]
            lines = tuple(TextLine(text_left + (self.text_width - line.width) / 2,
                                   y + theme.top_padding + line.baseline, line.width,
                                   line.glyphs)
                          for line in self._lines(index, fit))
            buttons.append(ChoiceButton((x, y, width, height), lines, fit.more))
            y += height + gap
        self.buttons = tuple(buttons)

    # -- queries --

    def hit(self, pos: tuple[float, float]) -> int | None:
        """The index of the button under ``pos`` (canvas units), or None."""
        for index, button in enumerate(self.buttons):
            if button.contains(pos):
                return index
        return None

    @property
    def heights(self) -> tuple[float, ...]:
        return tuple(b.rect[3] for b in self.buttons)

    @property
    def tops(self) -> tuple[float, ...]:
        return tuple(b.rect[1] for b in self.buttons)

    # -- the fit rule --

    def fits(self, top: float, bottom: float) -> bool:
        """Whether one of fit steps 0–2 fits these choices in ``top``..``bottom`` (pure: no
        drawing, nothing of this layout changes; F17 I-2)."""
        return self._step(top, bottom)[0] < 3

    def _step(self, top: float, bottom: float) -> tuple[int, int, int]:
        """(step, gap, size) of the first of steps 0–2 whose stack fits ``top``..``bottom``,
        else step 3's."""
        s0 = self.s0
        candidates = [(0, self.theme.gap, s0), (1, TIGHT_GAP, s0)]
        size = s0 - SIZE_STEP
        while size >= MIN_SIZE:
            candidates.append((2, TIGHT_GAP, size))
            size -= SIZE_STEP
        for step, gap, size in candidates:
            heights = self._heights(size)
            if sum(heights) + gap * (len(heights) - 1) <= bottom - top:
                return step, gap, size
        return 3, TIGHT_GAP, MIN_SIZE

    def _heights(self, size: int) -> list[float]:
        theme = self.theme
        pitch = round(LINE_PITCH * size)
        return [min(MAX_LINES, fit.count) * pitch + theme.top_padding + theme.bottom_padding
                for fit in self._fit(size)]

    def _fit(self, size: int) -> list[_Fit]:
        fits = self._fits.get(size)
        if fits is None:
            fits = self._fits[size] = [self._fit_one(body, color, size)
                                       for body, color in zip(self.bodies, self.colors)]
        return fits

    def _ctx(self, size: int, color: str, width: float, lines: int) -> LayoutContext:
        return LayoutContext(self.assets, self.faces, size, color, width,
                             lines * round(LINE_PITCH * size))

    def _fit_one(self, body: TaggedText, color: str, size: int) -> _Fit:
        layout = LineLayout(_spans_only(body), self._ctx(size, color, self.text_width,
                                                         MAX_LINES))
        page = layout.page(0)
        return _Fit(layout, max(1, len(page.lines)), not page.last)

    # -- lines (the winning size only) --

    def _lines(self, index: int, fit: _Fit) -> tuple[TextLine, ...]:
        if fit.lines is not None:
            return fit.lines
        page = fit.layout.page(0)                     # always ≥ 1 line (an empty body too)
        out = [_text_line(line.glyphs, line.baseline) for line in page.lines[:MAX_LINES]]
        if fit.more and len(page.lines) == MAX_LINES:
            second = page.lines[1]
            rest = _rest(self.bodies[index], second.first_glyph)
            cut = self._cut(rest, self.size)
            one = LineLayout(cut, self._ctx(self.size, self.colors[index], _WIDE, 1))
            laid = one.page(0).lines[0]                # its top is 0
            out[1] = _text_line(laid.glyphs, second.top + laid.baseline)
        fit.lines = tuple(out)
        return fit.lines

    def _cut(self, rest: list[tuple[str, Style]], size: int) -> TaggedText:
        """The longest prefix of ``rest`` that fits the text width with "…" after it (F05's
        ``fit_line``, per grapheme, styles kept): galloping, then a binary search."""
        limit = self.text_width

        def fits(k: int) -> bool:
            return self._width(_with_ellipsis(rest, k), size) <= limit

        if self._width(_join(rest), size) <= limit:
            return _join(rest)
        low, probe = 0, 16
        while probe < len(rest) and fits(probe):
            low, probe = probe, probe * 2
        high = min(probe, len(rest))
        while low < high:
            mid = (low + high + 1) // 2
            if fits(mid):
                low = mid
            else:
                high = mid - 1
        return _with_ellipsis(rest, low)

    def _width(self, text: TaggedText, size: int) -> float:
        """The advance of ``text`` on one line (style runs measured whole)."""
        total = 0.0
        for span in text.pieces:
            if not isinstance(span, Span):
                continue
            face = self.faces.for_style(span.style.bold, span.style.italic)
            font = self.assets.font(face.ref, max(1, round(size * span.style.size)),
                                    bundled=face.bundled, synth=face.synth).font
            total += font.size(render_safe(span.text))[0]
        return total


def _spans_only(body: TaggedText) -> TaggedText:
    """``body`` without timing marks or ``{next}`` (a choice's body has none; a defensive
    copy so layout never sees one)."""
    if all(isinstance(p, Span) for p in body.pieces) and not body.auto_next:
        return body
    return TaggedText(tuple(p for p in body.pieces if isinstance(p, Span)))


def _text_line(glyphs: Sequence[PlacedGlyph], baseline: float) -> TextLine:
    drawn = [g for g in glyphs if not g.hangs]
    width = max((g.right for g in drawn), default=0.0)
    return TextLine(0.0, baseline, width, tuple(glyphs))


def _rest(body: TaggedText, first: int) -> list[tuple[str, Style]]:
    """The graphemes of ``body`` from layout glyph ``first`` on, with their styles; hard
    breaks become spaces, and break spaces at the start are dropped."""
    out: list[tuple[str, Style]] = []
    index = 0
    for span in _spans_only(body).pieces:
        assert isinstance(span, Span)
        for grapheme in iter_graphemes(render_safe(span.text)):
            if grapheme == "\n":
                if index >= first and out:
                    out.append((" ", span.style))
                continue
            if index >= first and (out or not is_break_space(grapheme)):
                out.append((grapheme, span.style))
            index += 1
    return out


def _join(items: Sequence[tuple[str, Style]]) -> TaggedText:
    spans: list[Span] = []
    for text, style in items:
        if spans and spans[-1].style == style:
            spans[-1] = Span(spans[-1].text + text, style)
        else:
            spans.append(Span(text, style))
    return TaggedText(tuple(spans))


def _with_ellipsis(items: Sequence[tuple[str, Style]], k: int) -> TaggedText:
    kept = list(items[:k])
    style = kept[-1][1] if kept else (items[0][1] if items else Style())
    return _join(kept + [(ELLIPSIS, style)])


# --- Drawing ----------------------------------------------------------------------------------

class ChoiceStackView:
    """Draws a ``ChoiceLayout``: shapes (≤ 6 cached), then each button's glyph list.

    ``frame`` and ``focused_frame`` are ``[theme.choice] frame_image`` and
    ``focused.frame_image`` as ``install_choices`` checked them (None: the drawn look; W43
    was logged for an unusable one). ``frame`` serves the normal and locked states.

    **Fade** (UI-F07-03, ``04`` §7.8): ``draw`` with ``alpha`` < 1 composes the whole stack
    into one temporary stack-sized per-pixel-alpha surface (kept while the states, layout,
    and scale stay; rebuilt on a focus change) and blits it with ``set_alpha``. The shared
    shapes and glyph rasters never get an alpha. The composite is dropped in the first
    ``draw`` at alpha 1, so it lives at most for the fade (I-13)."""

    def __init__(self, assets: Any, theme: "ChoiceTheme", *, frame: str | None = None,
                 focused_frame: str | None = None) -> None:
        self.assets = assets
        self.theme = theme
        self.frame = frame
        self.focused_frame = focused_frame
        self._shapes: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._glyph_key: tuple | None = None
        self._glyph_layout: ChoiceLayout | None = None
        self._glyphs: list[list[tuple[pygame.Surface, tuple[int, int]]]] = []
        self._fade_key: tuple | None = None
        self._fade: tuple[pygame.Surface, tuple[int, int]] | None = None

    @property
    def shape_count(self) -> int:
        return len(self._shapes)

    @property
    def fade_surface(self) -> pygame.Surface | None:
        """The fade composite while one is kept (tests: it is freed once alpha reaches 1)."""
        return None if self._fade is None else self._fade[0]

    def draw(self, canvas: Canvas, layout: ChoiceLayout, states: Sequence[State], *,
             alpha: float = 1.0) -> None:
        """Every button of ``layout`` in its state (``states[i]``), then its text, at
        ``alpha`` (the fade; 1 draws directly)."""
        glyphs = self._glyph_lists(canvas, layout)
        surface = canvas.surface
        assert surface is not None
        if alpha >= 1.0:
            self._fade = self._fade_key = None
            for button, state, entries in zip(layout.buttons, states, glyphs, strict=True):
                rect = canvas.rect_to_px(button.rect)
                if rect.width > 0 and rect.height > 0:
                    surface.blit(self._shape(canvas, state, button.rect), rect.topleft)
                if entries:
                    surface.blits(entries, doreturn=False)
            return
        if alpha <= 0.0:
            return
        key = (id(layout), tuple(states), canvas.scale_x, canvas.scale_y, canvas.quality,
               id(glyphs))
        if self._fade is None or key != self._fade_key:
            self._fade = None                         # the old composite goes first
            self._fade = self._compose(canvas, layout, states, glyphs)
            self._fade_key = key
        if self._fade is None:
            return
        composite, origin = self._fade
        composite.set_alpha(max(0, min(255, round(alpha * 255))))
        surface.blit(composite, origin)

    def _compose(self, canvas: Canvas, layout: ChoiceLayout, states: Sequence[State],
                 glyphs: list[list[tuple[pygame.Surface, tuple[int, int]]]]
                 ) -> tuple[pygame.Surface, tuple[int, int]] | None:
        """The fade composite: the stack drawn into one new transparent surface."""
        rects = [canvas.rect_to_px(button.rect) for button in layout.buttons]
        drawn = [r for r in rects if r.width > 0 and r.height > 0]
        if not drawn:
            return None
        box = drawn[0].unionall(drawn[1:])
        ox, oy = box.topleft
        composite = pygame.Surface(box.size, pygame.SRCALPHA, 32)
        composite.fill((0, 0, 0, 0))
        for button, rect, state, entries in zip(layout.buttons, rects, states, glyphs,
                                                strict=True):
            if rect.width > 0 and rect.height > 0:
                # Onto alpha 0 a blit copies the shape exactly (pygame's ALPHA_BLEND).
                composite.blit(self._shape(canvas, state, button.rect), (rect.x - ox,
                                                                         rect.y - oy))
            if entries:
                composite.blits([(g, (x - ox, y - oy)) for g, (x, y) in entries],
                                doreturn=False)
        return composite, (ox, oy)

    # -- shapes --

    def prerender(self, scale: float, height: float) -> None:
        """``install_choices``: build and cache the normal and focused shapes of a button
        ``height`` tall at ``scale``, so the first menu's open frame doesn't (``04`` §7.8)."""
        for state in ("normal", "focused"):
            self._cached_shape(state, self.theme.width, height, scale, cache=True)

    def _shape(self, canvas: Canvas, state: State, rect: tuple[float, ...]) -> pygame.Surface:
        _x, _y, w, h = rect
        return self._cached_shape(state, w, h, canvas.scale,
                                  cache=canvas.quality is RenderQuality.FINAL)

    def _cached_shape(self, state: State, w: float, h: float, scale: float, *,
                      cache: bool) -> pygame.Surface:
        key = (state, h, w, scale)
        shape = self._shapes.get(key)
        if shape is not None:
            self._shapes.move_to_end(key)
            return shape
        shape = self.build_shape(state, (max(1, round(w * scale)), max(1, round(h * scale))),
                                 scale)
        if cache:
            self._shapes[key] = shape
            if len(self._shapes) > SHAPE_CACHE_ENTRIES:
                self._shapes.popitem(last=False)
        return shape

    def build_shape(self, state: State, size_px: tuple[int, int], scale: float
                    ) -> pygame.Surface:
        """A new button surface of ``size_px``: fill and border (or that state's nine-slice
        frame × its fill opacity), plus the marker (focused) or the padlock (locked), at the
        marker's place, vertically centered. Border and marks are opaque (07 I-8)."""
        theme = self.theme
        if state == "focused":
            f = theme.focused
            spec = FrameSpec(f.fill_color, theme.fill_opacity, f.border_color, f.border_width,
                             theme.corner_radius, theme.frame_slice_width)
            ref = self.focused_frame
        elif state == "locked":
            spec = FrameSpec(theme.fill_color, theme.locked.fill_opacity, theme.border_color,
                             theme.border_width, theme.corner_radius,
                             theme.frame_slice_width)
            ref = self.frame
        else:
            spec = FrameSpec(theme.fill_color, theme.fill_opacity, theme.border_color,
                             theme.border_width, theme.corner_radius,
                             theme.frame_slice_width)
            ref = self.frame
        shape = build_frame(spec, size_px, scale, self._image(ref))
        if state == "focused":
            mark = build_triangle(_px(MARKER_SIZE, scale), theme.marker.fill_color,
                                  direction="right")
        elif state == "locked":
            mark = build_padlock(_px(LOCK_SIZE, scale), theme.locked.text_color)
        else:
            return shape
        x = round(MARK_INSET * scale)
        y = round((size_px[1] - mark.get_height()) / 2)
        shape.blit(mark, (x, y))
        return shape

    def _image(self, ref: str | None) -> pygame.Surface | None:
        """A frame image's source, or None for the drawn look (none set, or a placeholder:
        a file that went missing after the launch check, as F05's box)."""
        if ref is None or self.assets is None:
            return None
        image = self.assets.image(ref)
        if image.is_placeholder:
            return None
        return self.assets.surface(image)

    # -- glyphs --

    def _glyph_lists(self, canvas: Canvas, layout: ChoiceLayout
                     ) -> list[list[tuple[pygame.Surface, tuple[int, int]]]]:
        fast = canvas.quality is RenderQuality.FAST and canvas.final_scale is not None \
            and canvas.final_scale != canvas.scale
        if fast:                                          # a resize settling: uncached
            return self._build_glyphs(canvas, layout, canvas.final_scale)
        key = (canvas.scale_x, canvas.scale_y)
        if layout is not self._glyph_layout or key != self._glyph_key:
            self._glyphs = self._build_glyphs(canvas, layout, canvas.scale)
            self._glyph_layout = layout
            self._glyph_key = key
        return self._glyphs

    def _build_glyphs(self, canvas: Canvas, layout: ChoiceLayout, raster_scale: float
                      ) -> list[list[tuple[pygame.Surface, tuple[int, int]]]]:
        assets = self.assets
        ratio = canvas.scale / raster_scale
        fonts: dict[tuple, Any] = {}
        colors: dict[str, RGB] = {}
        out: list[list[tuple[pygame.Surface, tuple[int, int]]]] = []
        for button in layout.buttons:
            entries: list[tuple[pygame.Surface, tuple[int, int]]] = []
            for line in button.lines:
                base_y = canvas.px(0, line.baseline)[1]
                for glyph in line.glyphs:
                    if glyph.hangs or glyph.text.isspace():
                        continue
                    face = glyph.face
                    font_key = (face, glyph.size)
                    raster = fonts.get(font_key)
                    if raster is None:
                        raster = fonts[font_key] = assets.font(
                            face.ref, max(1, round(glyph.size * raster_scale)),
                            bundled=face.bundled, synth=face.synth)
                    color = colors.get(glyph.color)
                    if color is None:
                        color = colors[glyph.color] = _hex_rgb(glyph.color)
                    surface = assets.text_line(raster, glyph.text, color)
                    ascent = raster.font.get_ascent()
                    if ratio != 1.0:
                        surface = pygame.transform.scale(
                            surface, (max(1, round(surface.get_width() * ratio)),
                                      max(1, round(surface.get_height() * ratio))))
                        ascent = round(ascent * ratio)
                    x = canvas.px(line.x + glyph.x, 0)[0]
                    entries.append((surface, (x, base_y - ascent)))
            out.append(entries)
        return out


def build_padlock(size_px: tuple[int, int], color: RGB) -> pygame.Surface:
    """A new per-pixel-alpha padlock filling ``size_px`` (design §6.2: 14 × 18): a body in
    the lower 10/18 and a shackle ring above it, drawn at 4× and ``smoothscale``d."""
    width, height = max(1, int(size_px[0])), max(1, int(size_px[1]))
    k = 4
    w, h = width * k, height * k
    big = pygame.Surface((w, h), pygame.SRCALPHA, 32)
    big.fill((*color, 0))
    ring = max(k, round(w * 2 / 14))
    shackle = pygame.Rect(round(w * 2 / 14), 0, round(w * 10 / 14), round(h * 14 / 18))
    pygame.draw.ellipse(big, (*color, 255), shackle, ring)
    body_top = round(h * 8 / 18)
    pygame.draw.rect(big, (*color, 255), pygame.Rect(0, body_top, w, h - body_top), 0,
                     round(w * 2 / 14))
    return pygame.transform.smoothscale(big, (width, height))


def _px(size: tuple[int, int], scale: float) -> tuple[int, int]:
    return max(1, round(size[0] * scale)), max(1, round(size[1] * scale))


def _hex_rgb(color: str) -> RGB:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def rgb_hex(color: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


__all__ = ["AREA_MARGIN", "AREA_TOP", "LAST_BOTTOM", "MIN_TEXT_WIDTH", "SHAPE_CACHE_ENTRIES",
           "ChoiceArea", "ChoiceButton", "ChoiceLayout", "ChoiceStackView", "TextLine",
           "build_padlock", "half_up", "rgb_hex"]
