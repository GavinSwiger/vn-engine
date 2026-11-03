"""``TextboxView``: the ADV box, its name tab, the typed glyphs, and the continue indicator
(F05 ``04-technical.md`` §7.7; ``03-ui.md`` UI-F05-01 to 14).

Why this module exists: the textbox draws every frame of a game, so all it may do per frame
is a few blits of things built earlier: one box surface (rebuilt only when its pixel size or
the render scale changes), one name-tab surface, one blit of the glyphs typed so far (the
typed layer, below) plus the few revealed this frame, and one small indicator shape.
``TextboxScreen`` (``ui/builtin/textbox_screen``) owns the line, the typewriter, and input;
this view owns the look and its caches.

- **Geometry** (``box_geometry``, UI-F05-01/02): the box is ``width`` wide, anchored
  ``midbottom`` at (640, 720 − ``bottom_gap``), H = min(216, max(``height``, top + bottom
  padding + 3 × pitch)) tall, pitch = round(1.4 × text size). The text area starts at
  (left + ``side_padding``, top + ``top_padding``).
- **Box surface**: ``frames.build_frame`` at FINAL quality, owned by the view and outside the
  asset budget (``07`` §3.3: one box surface, ≤ 6.6 MB at 4K, and ≤ 4 name-tab surfaces). A
  ``frame_image`` draws nine-slice; one that is (or turns into) a placeholder draws the fill
  (UI-F05-12). FAST quality scales the last FINAL surface, uncached. It is drawn with one
  plain alpha blit (about 0.2 ms at 1080p, memory-bound). Measured and dropped (F05 step 9,
  pygame-ce 2.5.8): ``convert_alpha()`` (``build_frame`` already returns the display's
  ARGB8888, same bytes); ``premul_alpha()`` + ``BLEND_PREMULTIPLIED`` (±1 per channel on
  245k bytes over noise, and no faster once the stage's blit has cooled the cache); a
  bounding-rect blit (the border reaches every edge, so it is the whole box).
- **Name tab** (UI-F05-04): name + 2 × ``side_padding`` wide, clamped to ``min_width``–500
  (a cut name takes the full 500), (name size + 16) tall, bottom edge at box top +
  ``border_width`` so it covers the box border beneath it, top corners rounded. The tab is
  built one border taller and drawn without its bottom border row, so its fill meets the box.
  The name is drawn with ``Canvas.draw_text`` (cut with "…" when wider than 460).
- **Glyphs** (§7.7, UI-F05-13): per page and FINAL scale, one draw list of each visible
  grapheme's cached raster (``assets.text_line``) at ``(px(area_x + x), px(baseline) −
  ascent)``, so glyphs never move as typing goes on and device hinting never moves a break.
  ``draw_glyphs`` blits the first ``k`` entries (``bisect`` on ``shown``) in one ``blits``
  call; ``build_glyphs`` builds the list. F17's NVL rows use both, without the box.
- **Typed layer** (``draw_typed``, the say window's path; F05 step 9's fix for AC-F05-45):
  the glyphs already drawn on the page are kept in one transparent surface the size of the
  box, so a frame blits that layer once (cut to the part holding glyphs) after appending only
  the glyphs revealed since the last frame. The box is not in the layer: over the translucent
  fill (``fill_opacity`` 0.80) a surface holding box and glyphs blends a glyph's
  anti-aliased edge differently from the box-then-glyph blits (up to 12 levels per channel
  at 1080p), and the output stays pixel-identical. A glyph copied onto transparent layer
  pixels blends onto the canvas exactly as when blitted itself, so the layer takes a glyph
  only when it lies inside the layer with no inked (alpha > 0) pixel over an earlier
  glyph's. Any other glyph (a "spill": rare, about 1 in 400 glyphs of the bench prose, more
  in italic or tightly kerned runs) is blitted on its own after the layer each frame, in
  order; a later glyph that inks over a spill spills too. The layer follows the page's draw
  list: a new line, page, restore, skip, ``clear()``, scale, text area, or box size starts it
  again; FAST quality draws uncached (F01 rule). The layer holds only glyphs without a text
  effect, and nothing changes a glyph once drawn inside it: ``{b}``, ``{i}``, ``{color}``,
  ``{size}`` are baked into its raster.
- **Text effects** (F29 ``04`` §7.2, §7.3, §7.5; ``07`` I-3, I-4, I-8): ``build_glyphs`` puts a
  glyph whose span has ``{shake}``, ``{wave}``, or ``{glitch}`` in ``_PageDraw.fx`` (an
  ``FxGlyph``: rest position, amplitude in device px or glitch share, and for glitch the 20
  ``textfx.SUBSTITUTES`` rasters, fetched once per (face, size, color) through
  ``assets.text_line`` when the list is built and centred on the glyph's advance), never in
  ``entries``, so never in the typed layer or its ink mask. ``draw_glyphs``/``draw_typed``
  take ``fx`` (``FxTime``: the effect time and reduce motion) and ``seed`` (the line's
  ``textfx.line_seed``), and after the static glyphs pose the shown effect glyphs with
  ``fx_blits`` into one extra ``blits`` (they draw above static neighbours, R1). A line
  without effects costs one empty-list check. ``fx=None`` draws them at rest as real
  glyphs; under reduce motion shake and wave rest and glitch freezes on its step-0 pattern,
  plus I-4's one symbol per glitch run that would show none (found once per draw list and
  seed, ``_PageDraw.prepare_still``). At FAST quality (a live resize) effect glyphs are
  ordinary static entries: at rest, no substitute fetched.
- **Indicator** (UI-F05-07/08/09): a down triangle 16×12 (line) or two 16×10 with a 2-unit
  gap (page), or the token image, ``bottomleft`` at (area_x + min(pen x, area width) + 8,
  baseline + bob); on an empty page at the area's left edge on the first baseline (G14).
  ``bob(t)`` = 4 × (1 − cos(2πt / 1.2)) / 2.
"""

import math
from bisect import bisect_left
from collections import OrderedDict
from weakref import WeakKeyDictionary
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import pygame

from engine.core.config_schema import TextboxTheme
from engine.core.constants import CANVAS_SIZE
from engine.render.canvas import RGB, Canvas, RenderQuality
from engine.render.frames import (
    ALL_CORNERS,
    TOP_CORNERS,
    FrameSpec,
    build_frame,
    build_triangle,
)
from engine.render.text import FontSpec, fit_line, text_width
from engine.render.textfx import (
    GLITCH,
    GLITCH_STEP_S,
    KINDS,
    SALT_GLITCH_PHASE,
    SALT_GLITCH_PICK,
    SALT_SHAKE,
    SEED_BITS,
    SHAKE,
    SHAKE_STEP_S,
    SUBSTITUTES,
    WAVE_PERIOD_S,
    WAVE_PHASE,
    FxTime,
    amplitude,
    h,
    index_key,
    still_minimum,
    u,
)
from engine.render.textlayout import LINE_PITCH, FaceSource, Page, render_safe

if TYPE_CHECKING:
    from collections.abc import Sequence

    from engine.render.assets import AssetManager, ImageRef

Blit = tuple[pygame.Surface, tuple[int, int]]
_M: Final = 0xFFFFFFFF

MAX_BOX_HEIGHT: Final = 216              # UI-F05-01: the box never grows past this
LINES_FOR_HEIGHT: Final = 3              # H fits three lines of the text size
TAB_MAX_WIDTH: Final = 500               # half the default box (UI-F05-04)
TAB_EXTRA_HEIGHT: Final = 16             # tab height = name size + 16
TAB_CACHE_ENTRIES: Final = 4             # ≤ 4 name-tab surfaces (07 §3.3)
INDICATOR_GAP: Final = 8                 # pen x + 8
LINE_SHAPE: Final = (16, 12)             # UI-F05-07
PAGE_SHAPE: Final = (16, 10)             # each of the two page triangles (UI-F05-08)
PAGE_SHAPE_GAP: Final = 2
BOB_UNITS: Final = 4.0                   # UI-F05-09: rest → 4 units down → rest
BOB_PERIOD_S: Final = 1.2
INDICATOR_CACHE_ENTRIES: Final = 8


def bob_offset(t: float) -> float:
    """The indicator's offset below rest ``t`` seconds after it appeared (ease in-out)."""
    return BOB_UNITS * (1.0 - math.cos(2.0 * math.pi * t / BOB_PERIOD_S)) / 2.0


def hex_rgb(color: str) -> RGB:
    """``"#rrggbb"`` as a tuple (layout colors are strings, theme colors tuples)."""
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def rgb_hex(color: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*color)


# --- Geometry (UI-F05-01, 02, 04) --------------------------------------------------------------

@dataclass(frozen=True)
class BoxGeometry:
    """Canvas units. ``box`` and ``area`` are (x, y, w, h); ``pitch`` the base line pitch."""

    text_size: int
    pitch: int
    box: tuple[float, float, float, float]
    area: tuple[float, float, float, float]

    @property
    def top(self) -> float:
        return self.box[1]


def box_geometry(theme: TextboxTheme, text_size: int) -> BoxGeometry:
    """UI-F05-01/02 at ``text_size`` (the size the line arrived with)."""
    pitch = round(LINE_PITCH * text_size)
    padding = theme.top_padding + theme.bottom_padding
    height = min(MAX_BOX_HEIGHT, max(theme.height, padding + LINES_FOR_HEIGHT * pitch))
    width = theme.width
    left = (CANVAS_SIZE[0] - width) / 2
    bottom = CANVAS_SIZE[1] - theme.bottom_gap
    top = bottom - height
    area = (left + theme.side_padding, top + theme.top_padding,
            width - 2 * theme.side_padding, height - padding)
    return BoxGeometry(text_size, pitch, (left, top, width, height), area)


@dataclass(frozen=True)
class NameTab:
    """The tab of one name: the drawn text (cut with "…" when too wide) and the tab rect."""

    text: str
    rect: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.rect
        return x + w / 2, y + h / 2


# --- The view -------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Stop:
    """Where the indicator goes after glyph ``index`` (its pen x and its line's baseline)."""

    index: int
    pen: float
    baseline: float


@dataclass(slots=True)
class FxGlyph:
    """One drawn glyph with a text effect (F29 ``04`` §4): its grapheme ``index`` in the line,
    ``kind`` (``textfx.SHAKE``/``WAVE``/``GLITCH``), the real raster at its rest ``dest``
    (device px), and ``amp``: the shake/wave amplitude in device px, or glitch's share p.
    ``subs``: glitch's 20 ``(raster, dest)`` substitutes in ``SUBSTITUTES`` order, centred on
    the glyph's advance. ``still_sub``: the substitute it shows under reduce motion when its
    glitch run would show none (07 I-4; −1: none), set by ``_PageDraw.prepare_still``.
    ``key`` (``textfx.index_key(index)``), ``phase`` and ``phase_seed`` (glitch's step offset
    for that seed) are ``fx_blits``' precomputed parts of the hash."""

    index: int
    kind: int
    surface: pygame.Surface
    dest: tuple[int, int]
    amp: float
    subs: tuple[Blit, ...] = ()
    still_sub: int = -1
    key: int = 0
    phase: float = 0.0
    phase_seed: int = -1

    def __post_init__(self) -> None:
        self.key = index_key(self.index)


class _PageDraw:
    """One page's glyph list at one scale: ``(surface, dest)`` pairs in glyph order for the
    glyphs without effect (``entries``/``indices``, F05's list), and the effect glyphs
    (``fx``/``fx_indices``, F29). ``runs`` are the glitch runs (07 I-4) as positions in
    ``fx``; ``still_seed`` the seed ``prepare_still`` last ran for."""

    def __init__(self, entries: list[Blit], indices: list[int],
                 fx: "list[FxGlyph] | None" = None, fx_indices: list[int] | None = None,
                 runs: list[list[int]] | None = None) -> None:
        self.entries = entries
        self.indices = indices
        self.fx: list[FxGlyph] = fx if fx is not None else []
        self.fx_indices: list[int] = fx_indices if fx_indices is not None else []
        self.runs: list[list[int]] = runs if runs is not None else []
        self.still_seed: int | None = None

    def prepare_still(self, seed: int) -> None:
        """Reduce motion's minimum (07 I-4) for ``seed``: per glitch run that shows no symbol
        at step 0, its min-``u`` glyph's ``still_sub``. Once per draw list and seed (the
        first still frame), never per frame."""
        if self.still_seed == seed:
            return
        self.still_seed = seed
        fx = self.fx
        for run in self.runs:
            for position in run:
                fx[position].still_sub = -1
            chosen = still_minimum(((fx[k].index, fx[k].amp) for k in run), seed)
            if chosen is not None:
                index, sub = chosen
                for position in run:
                    if fx[position].index == index:
                        fx[position].still_sub = sub
                        break


def fx_blits(glyphs: "Sequence[FxGlyph]", fx: FxTime | None, seed: int,
             out: list[Blit]) -> None:
    """Append each glyph's posed ``(surface, dest)`` to ``out`` (F29 ``04`` §7.3). ``fx``
    None: every glyph at rest, real. ``fx.still``: shake and wave at rest, glitch at its
    step-0 pick or its ``still_sub`` (call ``_PageDraw.prepare_still`` first).

    The poses are exactly ``textfx.shake_unit``, ``wave_unit``, and ``glitch_pick``
    (AC-F29-10, 13 compare them). For speed (04 §11: a full page ≤ 1.5 ms) the hash's last
    two ``mix32`` rounds are inlined here: ``h(i, step, salt, seed)`` is ``mix32(mix32(key
    + step) + (salt << 20 | seed))`` with ``key = index_key(i)`` kept on the glyph, and a
    glitch glyph's phase is kept per seed. Per glyph: two rounds or one ``sin``, a tuple."""
    append = out.append
    if fx is None:
        for g in glyphs:
            append((g.surface, g.dest))
        return
    t, still = fx.t, fx.still
    floor = math.floor
    wave = 2.0 * math.pi * t / WAVE_PERIOD_S
    shake_step = floor(t / SHAKE_STEP_S)
    shake_salt = SALT_SHAKE << SEED_BITS | seed
    pick_salt = SALT_GLITCH_PICK << SEED_BITS | seed
    count = len(SUBSTITUTES)
    for g in glyphs:
        kind = g.kind
        if kind == GLITCH:
            assert len(g.subs) == count
            if still:
                step = 0
            else:
                if g.phase_seed != seed:
                    g.phase = GLITCH_STEP_S * u(h(g.index, 0, SALT_GLITCH_PHASE, seed))
                    g.phase_seed = seed
                step = floor((t + g.phase) / GLITCH_STEP_S)
            x = (g.key + step) & _M                # mix32, inlined (textfx.mix32)
            x ^= x >> 16
            x = (x * 0x7FEB352D) & _M
            x ^= x >> 15
            x = (x * 0x846CA68B) & _M
            x ^= x >> 16
            x = (x + pick_salt) & _M
            x ^= x >> 16
            x = (x * 0x7FEB352D) & _M
            x ^= x >> 15
            x = (x * 0x846CA68B) & _M
            x ^= x >> 16
            if (x & 0xFFFF) / 65536 < g.amp:
                append(g.subs[int((x >> 16) / 65536 * count)])
            elif still and g.still_sub >= 0:
                append(g.subs[g.still_sub])
            else:
                append((g.surface, g.dest))
        elif still:
            append((g.surface, g.dest))
        elif kind == SHAKE:
            x = (g.key + shake_step) & _M          # mix32, inlined (textfx.mix32)
            x ^= x >> 16
            x = (x * 0x7FEB352D) & _M
            x ^= x >> 15
            x = (x * 0x846CA68B) & _M
            x ^= x >> 16
            x = (x + shake_salt) & _M
            x ^= x >> 16
            x = (x * 0x7FEB352D) & _M
            x ^= x >> 15
            x = (x * 0x846CA68B) & _M
            x ^= x >> 16
            amp = g.amp
            dx, dy = g.dest
            append((g.surface, (dx + round(amp * (2 * ((x & 0xFFFF) / 65536) - 1)),
                                dy + round(amp * (2 * ((x >> 16) / 65536) - 1)))))
        else:                                      # wave: raised = up (textfx.wave_unit)
            dx, dy = g.dest
            append((g.surface, (dx, dy + round(-g.amp * math.sin(wave + WAVE_PHASE * g.index)))))


class _TypedLayer:
    """The first ``count`` entries of ``draw`` (one page's draw list), composed into one
    transparent surface over the box rect ``rect`` (device pixels), or in ``spills``.
    ``bounds`` is the part of the surface holding glyphs; ``inked`` marks every pixel an
    entry so far inked (alpha > 0), layer and spills alike. A new layer reuses the surface
    and mask of ``reuse`` when the size matches, and its ``masks``: each raster's inked
    pixels, kept while the raster lives (rasters are shared through ``assets.text_line``)."""

    def __init__(self, draw: _PageDraw, rect: pygame.Rect,
                 reuse: "_TypedLayer | None" = None) -> None:
        self.masks: WeakKeyDictionary[pygame.Surface, pygame.mask.Mask] = \
            WeakKeyDictionary() if reuse is None else reuse.masks
        if reuse is not None and reuse.rect.size == rect.size:
            surface, inked = reuse.surface, reuse.inked
            if reuse.bounds is not None:
                surface.fill((0, 0, 0, 0), reuse.bounds)
            if reuse.count:
                inked.clear()
        else:
            surface = pygame.Surface(rect.size, pygame.SRCALPHA)
            inked = pygame.mask.Mask(rect.size)
        self.draw: _PageDraw | None = draw
        self.rect = rect
        self.surface = surface
        self.inked = inked
        self.count = 0
        self.bounds: pygame.Rect | None = None
        self.spills: list[tuple[pygame.Surface, tuple[int, int]]] = []

    def add(self, k: int) -> None:
        """Take entries ``count``..``k`` − 1, in order."""
        assert self.draw is not None
        rx, ry, rw, rh = self.rect
        inked, masks = self.inked, self.masks
        batch: list[tuple[pygame.Surface, tuple[int, int]]] = []
        for surface, (x, y) in self.draw.entries[self.count:k]:
            lx, ly = x - rx, y - ry
            w, h = surface.get_size()
            mask = masks.get(surface)
            if mask is None:
                mask = masks[surface] = pygame.mask.from_surface(surface, 0)   # alpha > 0
            if (lx >= 0 and ly >= 0 and lx + w <= rw and ly + h <= rh
                    and surface.get_flags() & pygame.SRCALPHA
                    and inked.overlap(mask, (lx, ly)) is None):
                batch.append((surface, (lx, ly)))
            else:
                self.spills.append((surface, (x, y)))
            inked.draw(mask, (lx, ly))
        self.count = k
        if batch:
            drawn = self.surface.blits(batch)
            bounds = drawn[0].unionall(drawn[1:])
            self.bounds = bounds if self.bounds is None else self.bounds.union(bounds)

    def blit(self, target: pygame.Surface) -> None:
        bounds = self.bounds
        if bounds is not None:
            target.blit(self.surface, (self.rect.x + bounds.x, self.rect.y + bounds.y), bounds)
        if self.spills:
            target.blits(self.spills, doreturn=False)


class TextboxView:
    """Draws the textbox from what ``TextboxScreen`` passes in; owns the drawing caches.

    ``name_face`` is the tab's face (the resolved Bold, or ``name_tab.text_font``). ``frame``,
    ``tab_frame``, ``line_image``, ``page_image`` are refs already checked at install (None:
    the drawn look)."""

    def __init__(self, assets: "AssetManager", theme: TextboxTheme, name_face: FaceSource, *,
                 frame: str | None = None, tab_frame: str | None = None,
                 line_image: str | None = None, page_image: str | None = None) -> None:
        self.assets = assets
        self.theme = theme
        self.name_face = name_face
        self.frame = frame
        self.tab_frame = tab_frame
        self.line_image = line_image
        self.page_image = page_image
        self._box_key: tuple | None = None
        self._box_surface: pygame.Surface | None = None
        self._tabs: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._names: OrderedDict[tuple, NameTab] = OrderedDict()
        self._shapes: OrderedDict[tuple, pygame.Surface] = OrderedDict()
        self._page_key: tuple | None = None
        self._page_draw: _PageDraw | None = None
        self._layer: _TypedLayer | None = None
        self._stops_key: tuple | None = None
        self._stops: tuple[list[int], list[_Stop]] = ([], [])

    def restyle(self, theme: TextboxTheme, name_face: FaceSource, *, frame: str | None,
                tab_frame: str | None, line_image: str | None,
                page_image: str | None) -> None:
        """F32 (04 §4.3, §6.5): draw in another look from now on. The box, tab, name, and
        shape caches go; the shown line's glyph lists and typed layer stay (its glyphs keep
        their look until the next line, D1)."""
        self.theme = theme
        self.name_face = name_face
        self.frame = frame
        self.tab_frame = tab_frame
        self.line_image = line_image
        self.page_image = page_image
        self._box_key = None
        self._box_surface = None
        self._tabs.clear()
        self._names.clear()
        self._shapes.clear()

    # -- geometry helpers --

    def name_spec(self) -> FontSpec:
        face = self.name_face
        return FontSpec(face.ref, self.theme.name_tab.text_size, face.bundled, face.synth)

    def tab_top(self, geometry: BoxGeometry) -> float:
        """The top y of any name tab over the box of ``geometry`` (it overlaps the border;
        the same for every name, F07's choice floor)."""
        return geometry.top + self.theme.border_width - (self.theme.name_tab.text_size
                                                         + TAB_EXTRA_HEIGHT)

    def name_tab(self, name: str, geometry: BoxGeometry) -> NameTab:
        """UI-F05-04 for ``name`` over the box of ``geometry`` (cached per name)."""
        key = (name, geometry.top)
        tab = self._names.get(key)
        if tab is not None:
            self._names.move_to_end(key)
            return tab
        nt = self.theme.name_tab
        spec = self.name_spec()
        font = self.assets.font(spec.ref, spec.size, bundled=spec.bundled,
                                synth=spec.synth).font
        limit = TAB_MAX_WIDTH - 2 * nt.side_padding
        safe = render_safe(name)
        shown = fit_line(font, safe, limit)
        if shown != safe:
            width = TAB_MAX_WIDTH                  # a cut name takes the whole tab
        else:
            width = min(TAB_MAX_WIDTH, max(nt.min_width,
                                           text_width(font, shown) + 2 * nt.side_padding))
        height = nt.text_size + TAB_EXTRA_HEIGHT
        left = geometry.box[0] + nt.left_gap
        tab = NameTab(shown, (left, self.tab_top(geometry), width, height))
        self._names[key] = tab
        if len(self._names) > TAB_CACHE_ENTRIES:
            self._names.popitem(last=False)
        return tab

    # -- drawing --

    def draw_box(self, canvas: Canvas, geometry: BoxGeometry) -> None:
        rect = canvas.rect_to_px(geometry.box)
        if rect.width <= 0 or rect.height <= 0:
            return
        surface = self._box(canvas, rect.size)
        canvas.surface.blit(surface, rect.topleft)

    def draw_tab(self, canvas: Canvas, tab: NameTab, color: RGB) -> None:
        rect = canvas.rect_to_px(tab.rect)
        if rect.width > 0 and rect.height > 0:
            surface, clip = self._tab(canvas, rect.size)
            canvas.surface.blit(surface, rect.topleft, clip)
        canvas.draw_text(tab.text, self.name_spec(), color, tab.center, anchor="center")

    def draw_glyphs(self, canvas: Canvas, page: Page, line_id: int, shown: int,
                    geometry: BoxGeometry, *, fx: FxTime | None = None, seed: int = 0) -> None:
        """The page's graphemes with index < ``shown``: the static ones in one ``blits``
        call, then the effect ones posed at ``fx`` with ``seed`` in one more (none: no
        call). ``fx`` None: effect glyphs at rest."""
        draw = self._glyphs(canvas, page, line_id, geometry)
        k = bisect_left(draw.indices, shown)
        if k > 0:
            canvas.surface.blits(draw.entries[:k], doreturn=False)
        if draw.fx:
            self._draw_fx(canvas, draw, shown, fx, seed)

    def draw_typed(self, canvas: Canvas, page: Page, line_id: int, shown: int,
                   geometry: BoxGeometry, *, fx: FxTime | None = None, seed: int = 0) -> None:
        """The pixels of ``draw_glyphs``, through the typed layer (module docstring): one
        blit of the static glyphs drawn before, after appending the ones revealed since,
        then the effect glyphs posed in one ``blits``."""
        rect = canvas.rect_to_px(geometry.box)
        if self._fast(canvas) or rect.width <= 0 or rect.height <= 0:
            self.draw_glyphs(canvas, page, line_id, shown, geometry, fx=fx, seed=seed)
            return
        draw = self._glyphs(canvas, page, line_id, geometry)
        k = bisect_left(draw.indices, shown)
        layer = self._layer
        if layer is None or layer.draw is not draw or layer.rect != rect or k < layer.count:
            layer = self._layer = _TypedLayer(draw, rect, layer)
        if k > layer.count:
            layer.add(k)
        layer.blit(canvas.surface)
        if draw.fx:
            self._draw_fx(canvas, draw, shown, fx, seed)

    @staticmethod
    def _draw_fx(canvas: Canvas, draw: _PageDraw, shown: int, fx: FxTime | None,
                 seed: int) -> None:
        """The effect glyphs with index < ``shown``, posed, in one ``blits`` (04 §7.5)."""
        k = bisect_left(draw.fx_indices, shown)
        if k <= 0:
            return
        if fx is not None and fx.still and draw.runs:
            draw.prepare_still(seed)
        out: list[Blit] = []
        fx_blits(draw.fx if k == len(draw.fx) else draw.fx[:k], fx, seed, out)
        canvas.surface.blits(out, doreturn=False)

    def draw_indicator(self, canvas: Canvas, page: Page, line_id: int, shown: int,
                       geometry: BoxGeometry, *, page_kind: bool, bob: float) -> None:
        x, baseline = self.indicator_anchor(page, line_id, shown, geometry)
        y = baseline + bob
        image = self.page_image if page_kind else self.line_image
        if image is not None:
            ref = self.assets.image(image)
            if not ref.is_placeholder:
                canvas.draw_image(ref, (x, y), anchor="bottomleft")
                return
        color = self.theme.indicator.fill_color
        if page_kind:
            w, h = PAGE_SHAPE
            self._triangle(canvas, (x, y - h - PAGE_SHAPE_GAP - h), (w, h), color)
            self._triangle(canvas, (x, y - h), (w, h), color)
        else:
            w, h = LINE_SHAPE
            self._triangle(canvas, (x, y - h), (w, h), color)

    def indicator_anchor(self, page: Page, line_id: int, shown: int,
                         geometry: BoxGeometry) -> tuple[float, float]:
        """The indicator's rest ``bottomleft`` in canvas units (§7.7, G14)."""
        ax, ay, aw, _ = geometry.area
        indices, stops = self._page_stops(page, line_id)
        k = bisect_left(indices, shown) - 1
        if k < 0:
            first = page.lines[0].baseline if page.lines else geometry.pitch
            return ax, ay + first                              # empty page: the left edge
        stop = stops[k]
        return ax + min(stop.pen, aw) + INDICATOR_GAP, ay + stop.baseline

    def forget_line(self) -> None:
        """A new line arrived (or none is shown): its pages get new glyph lists, and the
        typed layer starts again."""
        self._page_key = None
        self._page_draw = None
        if self._layer is not None:
            self._layer.draw = None                # its surface serves the next page
        self._stops_key = None
        self._stops = ([], [])

    # -- caches --

    def _box(self, canvas: Canvas, size: tuple[int, int]) -> pygame.Surface:
        if canvas.quality is RenderQuality.FAST and self._box_surface is not None:
            if self._box_surface.get_size() == size:
                return self._box_surface
            return pygame.transform.scale(self._box_surface, size)     # uncached (F01 rule)
        key = (size, canvas.scale)
        if key != self._box_key or self._box_surface is None:
            theme = self.theme
            spec = FrameSpec(theme.fill_color, theme.fill_opacity, theme.border_color,
                             theme.border_width, theme.corner_radius, theme.frame_slice_width,
                             ALL_CORNERS)
            self._box_surface = build_frame(spec, size, canvas.scale, self._image(self.frame))
            self._box_key = key
        return self._box_surface

    def _tab(self, canvas: Canvas, size: tuple[int, int]
             ) -> tuple[pygame.Surface, pygame.Rect]:
        """The tab surface and the part of it to draw (all but the bottom border rows)."""
        theme = self.theme
        nt = theme.name_tab
        image = self._image(self.tab_frame)
        border = 0
        if image is None and theme.border_width > 0:
            border = max(1, round(theme.border_width * canvas.scale))
        key = (size, canvas.scale, border, image is None)
        surface = self._tabs.get(key)
        if surface is None:
            spec = FrameSpec(nt.fill_color, nt.fill_opacity, theme.border_color,
                             theme.border_width, nt.corner_radius, theme.frame_slice_width,
                             TOP_CORNERS)
            surface = build_frame(spec, (size[0], size[1] + border), canvas.scale, image)
            if canvas.quality is RenderQuality.FINAL:
                self._tabs[key] = surface
                if len(self._tabs) > TAB_CACHE_ENTRIES:
                    self._tabs.popitem(last=False)
        else:
            self._tabs.move_to_end(key)
        return surface, pygame.Rect(0, 0, size[0], size[1])

    def _image(self, ref: str | None) -> pygame.Surface | None:
        """The frame image's source, or None for the drawn look (none set, or a placeholder:
        a file that went missing after the launch check, UI-F05-12)."""
        if ref is None:
            return None
        image = self.assets.image(ref)
        if image.is_placeholder:
            return None
        return self.assets.surface(image)

    def _triangle(self, canvas: Canvas, topleft: tuple[float, float], size: tuple[int, int],
                  color: RGB) -> None:
        rect = canvas.rect_to_px((topleft[0], topleft[1], size[0], size[1]))
        if rect.width <= 0 or rect.height <= 0:
            return
        key = (rect.size, color)
        shape = self._shapes.get(key)
        if shape is None:
            shape = build_triangle(rect.size, color, direction="down")
            self._shapes[key] = shape
            if len(self._shapes) > INDICATOR_CACHE_ENTRIES:
                self._shapes.popitem(last=False)
        canvas.surface.blit(shape, rect.topleft)

    @staticmethod
    def _fast(canvas: Canvas) -> bool:
        """FAST quality away from the last FINAL scale: glyphs are scaled from the FINAL
        rasters, uncached."""
        return canvas.quality is RenderQuality.FAST and canvas.final_scale is not None \
            and canvas.final_scale != canvas.scale

    def _glyphs(self, canvas: Canvas, page: Page, line_id: int,
                geometry: BoxGeometry) -> _PageDraw:
        if self._fast(canvas):
            return self.build_glyphs(canvas, page, geometry, canvas.final_scale)  # uncached
        key = (line_id, page.index, canvas.scale, geometry.area[:2])
        if key != self._page_key or self._page_draw is None:
            self._page_draw = self.build_glyphs(canvas, page, geometry, canvas.scale)
            self._page_key = key
        return self._page_draw

    def build_glyphs(self, canvas: Canvas, page: Page, geometry: BoxGeometry,
                     raster_scale: float) -> _PageDraw:
        """``page``'s draw list with the text area at ``geometry.area``, from rasters at
        ``raster_scale`` (scaled to ``canvas.scale`` when they differ). Uncached and
        separate from the typed layer (F17's NVL rows call it too).

        F29 (04 §7.2): a glyph with an effect becomes an ``FxGlyph`` in ``fx`` instead (shake
        and wave amplitudes in device px; glitch's 20 substitutes fetched once per (face,
        size, color) through ``assets.text_line`` and centred on the advance). From scaled
        FINAL rasters (FAST quality) every glyph is a static entry: effects at rest, no
        substitute fetched."""
        assets = self.assets
        ax, ay = geometry.area[0], geometry.area[1]
        scale = canvas.scale
        ratio = scale / raster_scale
        fast = ratio != 1.0
        entries: list[Blit] = []
        indices: list[int] = []
        fx: list[FxGlyph] = []
        fx_indices: list[int] = []
        runs: list[list[int]] = []
        run: list[int] = []                        # the open glitch run (positions in fx)
        fonts: dict[tuple[FaceSource, int], object] = {}
        colors: dict[str, RGB] = {}
        symbols: dict[tuple, tuple[tuple[pygame.Surface, int], ...]] = {}
        for line in page.lines:
            base_y = canvas.px(0, ay + line.baseline)[1]
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
                    color = colors[glyph.color] = hex_rgb(glyph.color)
                surface = assets.text_line(raster, glyph.text, color)
                ascent = raster.font.get_ascent()
                if fast:                           # FAST: scale the FINAL raster, uncached
                    surface = pygame.transform.scale(
                        surface, (max(1, round(surface.get_width() * ratio)),
                                  max(1, round(surface.get_height() * ratio))))
                    ascent = round(ascent * ratio)
                x = canvas.px(ax + glyph.x, 0)[0]
                dest = (x, base_y - ascent)
                effect = glyph.effect
                if effect is None or fast:
                    entries.append((surface, dest))
                    indices.append(glyph.index)
                    if run:                        # any other drawn glyph ends a run (I-4)
                        runs.append(run)
                        run = []
                    continue
                kind = KINDS[effect.kind]
                subs: tuple[Blit, ...] = ()
                if kind == GLITCH:
                    key = (font_key, glyph.color)
                    made = symbols.get(key)
                    if made is None:
                        made = symbols[key] = tuple(
                            (image, image.get_width()) for image in
                            (assets.text_line(raster, ch, color) for ch in SUBSTITUTES))
                    centre = canvas.px(ax + glyph.x + glyph.advance / 2, 0)[0]
                    y = dest[1]
                    subs = tuple((image, (centre - w // 2, y)) for image, w in made)
                    amp = amplitude(effect, glyph.size)
                    run.append(len(fx))
                else:
                    amp = amplitude(effect, glyph.size) * scale
                    if run:
                        runs.append(run)
                        run = []
                fx.append(FxGlyph(glyph.index, kind, surface, dest, amp, subs))
                fx_indices.append(glyph.index)
        if run:
            runs.append(run)
        return _PageDraw(entries, indices, fx, fx_indices, runs)

    def _page_stops(self, page: Page, line_id: int) -> tuple[list[int], list[_Stop]]:
        key = (line_id, page.index)
        if key != self._stops_key:
            stops = [_Stop(glyph.index, glyph.right, line.baseline)
                     for line in page.lines for glyph in line.glyphs]
            self._stops = ([stop.index for stop in stops], stops)
            self._stops_key = key
        return self._stops


__all__ = ["BOB_PERIOD_S", "BOB_UNITS", "Blit", "BoxGeometry", "FxGlyph", "NameTab", "TextboxView",
           "bob_offset", "box_geometry", "fx_blits", "hex_rgb", "rgb_hex"]
