"""``NvlView``: full-screen text (NVL) on screen: the panel, the settled page, the current
line and its indicator (F17 ``04-technical.md`` §5.3, §7.5; ``06`` AC-F17-14, 15, 33, 34).

Why this module exists: in NVL the say window is a panel over the whole stage with the page
of lines since the last reset, and the line being typed under the earlier ones. All of it is
drawn each frame from what ``TextboxScreen`` passes in (the presenter's plan and the current
line's typewriter), with no surface of viewport size:

1. **Panel**: ``frames.dim`` over the viewport, two constant fills (F10's backdrop rule).
2. **Settled rows** (every row of the plan but the current line): one cached draw list of
   name rasters and glyph rasters, blitted with one ``blits`` call. Rebuilt when the plan,
   the current entry, the scale, or the bump changes; uncached at FAST quality away from
   the last FINAL scale (F01 rule). Names are ``fit_line`` at the effective size in the
   name face (cut with "…" at the text width), in the line's color or ``nvl.name_color``.
   **Settled effect glyphs** (F29 ``04`` §7.6; ``07`` I-3, I-13) are built with that list
   under the same key, one ``_RowFx`` per settled row with effects; each frame every such
   row's poses at ``fx`` go into one list, drawn with one more ``blits`` (none when no row
   has effects). Settled rows show every grapheme. ``_RowFx`` is R2's pre-approved cache
   (``07`` §2.3): its blits equal ``textbox.fx_blits(draw.fx, fx, seed)``'s, but shake
   poses are kept per 0.05 s step (the next step's computed a third at a time in the frames
   before it), each glitch glyph's pose until its own step changes, and wave is posed
   every frame.
3. **Current line**: its name, then ``line_view.draw_glyphs`` (one ``blits``, plus one for
   its effect glyphs posed at ``fx``) of the typewriter's page with the text area at the
   row, then the indicator through ``line_view.draw_indicator`` (F05's shapes, bob, reduce
   motion).

F29: a row's pose seed is ``textfx.line_seed(sid) ^ position``, ``position`` its index in
``rows()``. It is constant for the row's life, so a line keeps its exact pose the frame it
settles (TR-F29-05), and the same line twice on one page moves out of step. ``fx`` is page
time (``TextboxScreen``'s clock, K2); None draws effect glyphs at rest.

``line_view`` is a second ``TextboxView`` (``for_textbox``) with the NVL indicator color;
only its glyph and indicator methods are used, so F05's own view and its typed layer are
untouched. F14 A4 (07 §3.4): this view is ``TextboxScreen.nvl_cue`` while NVL is shown;
``cue_anchor`` is the text area's top edge, ``CUE_INSET`` in from its right, and
``set_bump`` moves the panel and its text.

Imports ``core``, ``runtime`` (``NvlLine`` via ``runtime.commands``) and ``render`` only.
"""

from dataclasses import replace
from math import floor
from typing import TYPE_CHECKING, Final, Protocol

import pygame

from engine.core.constants import CANVAS_SIZE
from engine.render.canvas import Canvas, RenderQuality
from engine.render.frames import dim
from engine.render.nvllayout import NvlLook, NvlMetrics, Row
from engine.render.text import fit_line
from engine.render.textbox import BoxGeometry, TextboxView, _PageDraw, fx_blits, hex_rgb
from engine.render.textfx import GLITCH, GLITCH_STEP_S, SHAKE, SHAKE_STEP_S, FxTime, line_seed
from engine.render.textlayout import FaceSet, LineLayout, Page, render_safe
from engine.runtime.commands import NvlLine

if TYPE_CHECKING:
    from engine.render.typewriter import Typewriter

CUE_INSET: Final = 52                   # F14 03: the limit mark, in from the window's right
NAME_FIT_ENTRIES: Final = 64            # fitted names kept (no Font.size in a steady frame)
SEED_ENTRIES: Final = 64                # line seeds kept by sid (computed once, not per frame)

Blit = tuple[pygame.Surface, tuple[int, int]]


class NvlPageSource(Protocol):
    """What the view reads of ``NvlPresenter`` (``ui`` owns it; ``render`` never imports
    ``ui``)."""

    entries: list[NvlLine]
    metrics: NvlMetrics
    version: int
    current: int | None

    def rows(self) -> tuple[Row, ...]: ...

    def settled_page(self, row: Row) -> Page: ...


class _LookPart(Protocol):
    """What ``restyle`` reads of F32's ``TextboxLook`` (``ui`` owns it)."""

    theme: object
    faces: FaceSet
    name_face: object
    line_image: str | None
    page_image: str | None


class NvlView:
    """Draws NVL mode; owns the settled draw list and the fitted names."""

    def __init__(self, assets: object, look: NvlLook, faces: FaceSet,
                 line_view: TextboxView) -> None:
        self.assets = assets
        self.look = look
        self.faces = faces
        self.line_view = line_view
        self.bump = 0.0
        self._settled_key: tuple | None = None
        self._settled: list[Blit] = []
        self._settled_fx: list[_RowFx] = []                  # F29: settled effect rows
        self._names: dict[tuple[str, int], str] = {}
        self._seeds: dict[str, int] = {}

    @classmethod
    def for_textbox(cls, view: TextboxView, look: NvlLook, faces: FaceSet) -> "NvlView":
        """The NVL view beside F05's ``view``: a ``line_view`` with the same theme, name face
        and indicator images, and the indicator in ``look.indicator_color``."""
        theme = view.theme
        theme = replace(theme, indicator=replace(theme.indicator,
                                                 fill_color=look.indicator_color))
        line_view = TextboxView(view.assets, theme, view.name_face,  # type: ignore[arg-type]
                                line_image=view.line_image, page_image=view.page_image)
        return cls(view.assets, look, faces, line_view)

    def restyle(self, look: NvlLook, part: "_LookPart") -> None:
        """F32 (04 §4.3, §6.5): the panel, names and indicator in ``look`` from now on;
        ``line_view`` takes the part's box theme with ``look.indicator_color``. The settled
        draw list and the fitted names are built again."""
        self.look = look
        self.faces = part.faces
        theme = part.theme
        theme = replace(theme, indicator=replace(theme.indicator,
                                                 fill_color=look.indicator_color))
        self.line_view.restyle(theme, part.name_face, frame=None, tab_frame=None,
                               line_image=part.line_image, page_image=part.page_image)
        self._settled_key = None
        self._settled = []
        self._settled_fx = []
        self._names.clear()

    # -- F14 A4 (NVL branch) --

    def cue_anchor(self) -> tuple[float, float]:
        """The limit mark's center: the text area's top edge, ``CUE_INSET`` in from its
        right (canvas units; the same at every text size)."""
        look = self.look
        right = CANVAS_SIZE[0] / 2 + look.width / 2
        return right - CUE_INSET, float(look.top_gap)

    def set_bump(self, dy: float) -> None:
        """Draw the panel and its text ``dy`` units lower (0: at rest)."""
        self.bump = float(dy)

    def forget_line(self) -> None:
        """A new current line (or none): its glyph lists start again."""
        self.line_view.forget_line()

    # -- drawing --

    def draw(self, canvas: Canvas, presenter: NvlPageSource, *, typer: "Typewriter | None",
             line_id: int, indicator: str | None, bob: float,
             fx: FxTime | None = None) -> None:
        dy = self.bump
        look = self.look
        rect = None
        if dy:
            rect = canvas.rect_to_px((0, dy, CANVAS_SIZE[0], CANVAS_SIZE[1]))
        dim(canvas.surface, look.fill_color, look.fill_opacity, rect)
        settled, settled_fx = self._settled_list(canvas, presenter, dy)
        if settled:
            canvas.surface.blits(settled, doreturn=False)
        if settled_fx:
            out: list[Blit] = []
            for row_fx in settled_fx:
                row_fx.pose(fx, out)
            canvas.surface.blits(out, doreturn=False)
        current = presenter.current
        if current is None or typer is None:
            return
        position, row = next(((k, r) for k, r in enumerate(presenter.rows())
                              if r.entry == current), (0, None))
        if row is None:
            return
        m = presenter.metrics
        line = presenter.entries[current]
        y = row.y + dy
        name_h = 0
        if line.name:
            name_h = m.pitch
            surface, dest = self._name(canvas, line, m, y, self._raster_scale(canvas))
            canvas.surface.blit(surface, dest)
        layout: LineLayout = typer.layout                             # type: ignore[assignment]
        page = layout.page(typer.page)
        geometry = _geometry(m, y + name_h, name_h)
        view = self.line_view
        view.draw_glyphs(canvas, page, line_id, typer.shown, geometry, fx=fx,
                         seed=self._seed(line.sid) ^ position)
        if indicator is not None:
            view.draw_indicator(canvas, page, line_id, typer.shown, geometry,
                                page_kind=indicator == "page", bob=bob)

    # -- the settled rows --

    @staticmethod
    def _fast(canvas: Canvas) -> bool:
        return canvas.quality is RenderQuality.FAST and canvas.final_scale is not None \
            and canvas.final_scale != canvas.scale

    def _raster_scale(self, canvas: Canvas) -> float:
        return canvas.final_scale if self._fast(canvas) else canvas.scale  # type: ignore

    def _settled_list(self, canvas: Canvas, presenter: NvlPageSource, dy: float
                      ) -> tuple[list[Blit], "list[_RowFx]"]:
        """The settled static blits and effect rows, cached together under F17's key (F29
        07 I-13: no second key)."""
        fast = self._fast(canvas)
        key = (id(presenter), presenter.version, presenter.current, canvas.scale, dy,
               canvas.surface.get_size())
        if not fast and key == self._settled_key:
            return self._settled, self._settled_fx
        out, out_fx = self._build_settled(canvas, presenter, dy)
        if not fast:
            self._settled_key, self._settled, self._settled_fx = key, out, out_fx
        return out, out_fx

    def _build_settled(self, canvas: Canvas, presenter: NvlPageSource, dy: float
                       ) -> tuple[list[Blit], "list[_RowFx]"]:
        m = presenter.metrics
        raster_scale = self._raster_scale(canvas)
        out: list[Blit] = []
        out_fx: list[_RowFx] = []
        current = presenter.current
        for position, row in enumerate(presenter.rows()):
            if row.entry == current:
                continue
            line = presenter.entries[row.entry]
            y = row.y + dy
            name_h = 0
            if line.name:
                name_h = m.pitch
                out.append(self._name(canvas, line, m, y, raster_scale))
            page = presenter.settled_page(row)
            draw = self.line_view.build_glyphs(canvas, page, _geometry(m, y + name_h, name_h),
                                               raster_scale)
            out.extend(draw.entries)
            if draw.fx:                    # FAST: none (effect glyphs are static entries)
                out_fx.append(_RowFx(self._seed(line.sid) ^ position, draw))
        return out, out_fx

    def _seed(self, sid: str) -> int:
        """``line_seed(sid)``, kept by sid (F29 07 I-3: once per line, not per frame)."""
        seed = self._seeds.get(sid)
        if seed is None:
            if len(self._seeds) >= SEED_ENTRIES:
                self._seeds.clear()
            seed = self._seeds[sid] = line_seed(sid)
        return seed

    def _name(self, canvas: Canvas, line: NvlLine, m: NvlMetrics, y: float,
              raster_scale: float) -> Blit:
        """The name raster of ``line`` and its destination: the row's text baseline as a
        one-row line of the effective size, at the text area's left."""
        face = self.line_view.name_face
        assets = self.assets
        ref = assets.font(face.ref, m.size, bundled=face.bundled,            # type: ignore
                          synth=face.synth).font
        shown = self._fitted(line.name, m, ref)
        ascent, descent = ref.get_ascent(), abs(ref.get_descent())
        baseline = y + (m.pitch - (ascent + descent)) / 2 + ascent
        raster = assets.font(face.ref, max(1, round(m.size * raster_scale)),  # type: ignore
                             bundled=face.bundled, synth=face.synth)
        color = hex_rgb(line.color) if line.color is not None else self.look.name_color
        surface = assets.text_line(raster, shown, color)                    # type: ignore
        dev_ascent = raster.font.get_ascent()
        if raster_scale != canvas.scale:            # FAST: the FINAL raster scaled, uncached
            ratio = canvas.scale / raster_scale
            surface = pygame.transform.scale(
                surface, (max(1, round(surface.get_width() * ratio)),
                          max(1, round(surface.get_height() * ratio))))
            dev_ascent = round(dev_ascent * ratio)
        x, base_y = canvas.px(m.left, baseline)
        return surface, (x, base_y - dev_ascent)

    def _fitted(self, name: str, m: NvlMetrics, font: object) -> str:
        key = (name, m.size)
        shown = self._names.get(key)
        if shown is None:
            if len(self._names) >= NAME_FIT_ENTRIES:
                self._names.clear()
            shown = self._names[key] = fit_line(font, render_safe(name),  # type: ignore
                                                m.width)
        return shown


class _RowFx:
    """One settled row's effect glyphs and R2's pose cache (F29 ``07`` §2.3, pre-approved):
    ``pose(fx, out)`` appends exactly ``fx_blits(draw.fx, fx, seed)``'s blits. Moving, the
    row's posed list is kept and only what changed is posed again: wave every frame, shake
    when its 0.05 s step changes (from ``ahead``, the next step's poses computed a third per
    frame before it), and a glitch glyph when its own step changes. ``fx`` None or ``still``
    is posed once per change of mode. Presentation-only, dropped with the settled list."""

    __slots__ = ("seed", "draw", "blits", "mode", "shake_at", "shake", "shake_step",
                 "ahead", "ahead_step", "wave_at", "wave", "glitch_at", "glitch",
                 "glitch_steps")

    def __init__(self, seed: int, draw: _PageDraw) -> None:
        self.seed = seed
        self.draw = draw
        self.blits: list[Blit] = []
        self.mode: object = ()                 # (): nothing posed; None; True (still); False
        fx = draw.fx
        self.shake_at = [k for k, g in enumerate(fx) if g.kind == SHAKE]
        self.shake = [fx[k] for k in self.shake_at]
        self.glitch_at = [k for k, g in enumerate(fx) if g.kind == GLITCH]
        self.glitch = [fx[k] for k in self.glitch_at]
        self.wave_at = [k for k, g in enumerate(fx) if g.kind not in (SHAKE, GLITCH)]
        self.wave = [fx[k] for k in self.wave_at]
        self.shake_step = 0
        self.ahead: list[Blit] = []
        self.ahead_step: int | None = None
        self.glitch_steps: list[int] = []

    def pose(self, fx: FxTime | None, out: list[Blit]) -> None:
        mode = None if fx is None else fx.still
        if mode is not False or self.mode is not False:
            if mode is not self.mode or mode is False:
                self._full(fx, mode)
            out.extend(self.blits)
            return
        assert fx is not None
        seed, blits = self.seed, self.blits
        if self.wave:
            posed: list[Blit] = []
            fx_blits(self.wave, fx, seed, posed)
            if len(posed) == len(blits):           # a row of wave alone
                self.blits = blits = posed
            else:
                for k, blit in zip(self.wave_at, posed):
                    blits[k] = blit
        if self.shake:
            self._shake(fx, floor(fx.t / SHAKE_STEP_S))
        if self.glitch:
            t = fx.t
            steps = [floor((t + g.phase) / GLITCH_STEP_S) for g in self.glitch]
            if steps != self.glitch_steps:
                changed = [k for k, (a, b) in enumerate(zip(steps, self.glitch_steps))
                           if a != b]
                posed = []
                fx_blits([self.glitch[k] for k in changed], fx, seed, posed)
                at = self.glitch_at
                for k, blit in zip(changed, posed):
                    blits[at[k]] = blit
                self.glitch_steps = steps
        out.extend(blits)

    def _full(self, fx: FxTime | None, mode: object) -> None:
        """Every glyph posed at ``fx`` (and, moving, each kind's cache state set)."""
        draw, seed = self.draw, self.seed
        if mode is True and draw.runs:
            draw.prepare_still(seed)
        blits: list[Blit] = []
        fx_blits(draw.fx, fx, seed, blits)     # also sets each glitch glyph's phase
        self.blits, self.mode = blits, mode
        if mode is False:
            assert fx is not None
            t = fx.t
            self.shake_step = floor(t / SHAKE_STEP_S)
            self.ahead, self.ahead_step = [], None
            self.glitch_steps = [floor((t + g.phase) / GLITCH_STEP_S) for g in self.glitch]
            if self.shake:
                self._shake(fx, self.shake_step)

    def _shake(self, fx: FxTime, step: int) -> None:
        """Shake at ``step``: posed again only when the step changes (from ``ahead``, its
        rest posed now when the step came early), then a third of the next step's poses
        computed ahead (a step is three frames at 60 fps)."""
        shake, blits = self.shake, self.blits
        if step != self.shake_step:
            posed = self.ahead if self.ahead_step == step else []
            if len(posed) < len(shake):
                fx_blits(shake[len(posed):], fx, self.seed, posed)
            for k, blit in zip(self.shake_at, posed):
                blits[k] = blit
            self.shake_step = step
        target = step + 1
        if self.ahead_step != target:
            self.ahead, self.ahead_step = [], target
        done = len(self.ahead)
        if done < len(shake):
            # a time inside step ``target``: a shake pose depends on its step alone
            t = (target + 0.5) * SHAKE_STEP_S
            third = (len(shake) + 2) // 3
            fx_blits(shake[done:done + third], FxTime(t), self.seed, self.ahead)


def _geometry(m: NvlMetrics, text_top: float, name_h: float) -> BoxGeometry:
    """A line's text rectangle at ``text_top`` as F05's ``BoxGeometry`` (box = area): the
    text width, and the area's height less the name row (every page of the line's
    layout)."""
    area = (m.left, text_top, m.width, m.height - name_h)
    return BoxGeometry(m.size, m.pitch, area, area)


__all__ = ["CUE_INSET", "NvlPageSource", "NvlView"]
