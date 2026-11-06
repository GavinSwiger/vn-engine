"""``InboxView``: the Inbox page's ``CodexView``, which draws each message the way its device
shows it (F65 round 3, "Phone and letter skins" and "Radio, terminal and mind skins").

Why this module exists: a thread on the Inbox page holds every delivery from one contact,
and each came by a device look (``send … on pigeon``, the contact's ``on``, the kit's
default). The text is the same for every look (the entry's paragraphs, so History, a screen
reader and a test read the same words); this view only places and dresses it:

- **phone**: chat bubbles. The sender's on the left in the focused-button fill, the
  player's on the right in the accent with the panel's fill as text; the line above each
  message and the time dividers centred and small.
- **letters**: one paper card per delivery, the heading line centred over a short rule
  with a dot, the signature ("— Hana") at the right.
- **pigeon**: a smaller note of kraft paper, inset from both sides, with a wax seal and
  ribbon on its top edge.
- **radio**: a transcript with no card: the heading line, "[signal]" at the right, a rule
  of static under them, and a margin line beside the messages.
- **terminal**: a dark screen per delivery in the scheme's darkest text-or-fill color,
  green text drawn in fixed-width cells in the bundled Noto Sans Mono, and a block cursor
  after the last line.
- **mind**: no frame. The text in italics (the port sets the style), centred in a soft
  glow.

A letter's and a pigeon note's heading line and signature are set in the bundled Noto Serif
(Italic). Both bundled faces stand in only for the bundled Noto Sans: a game with its own
text font keeps it everywhere (``_own_font``), so its characters still show.

The colors come from ``ui/devicelook.palette`` (``core/devicelooks``), checked for every
scheme. Under reduced motion (``ui.reduce_motion``) the static and the cursor hold still.

The port says how each paragraph is dressed with ``paragraph_looks(name)`` (optional): a
``ParaLook`` per paragraph of the entry, or None for an entry drawn as the plain codex
body. Paragraph heights add each look's padding, and a wider gap after the last paragraph
of a delivery; the lazy layout (``CodexView``) works as before. A terminal paragraph is
laid out in cells (``_MonoPage``) instead of by ``LineLayout``.
"""

import dataclasses
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from engine.render.frames import FrameSpec
from engine.render.text import Face, FontSpec
from engine.render.textlayout import FaceSet, FaceSource, LayoutContext, LineLayout
from engine.ui.builtin.codex_page import (
    BODY_LAYOUT_CACHE,
    LAZY_ESTIMATE,
    CodexView,
    _Body,
    _hex,
    _rgb,
)
from engine.ui.devicelook import cursor, palette, rgb, seal, static_rule
from engine.ui.focus import Box
from engine.ui.layouts import pitch, scaled
from engine.ui.widgets import clipped
from engine.ui.theme import font_spec, measure_with

if TYPE_CHECKING:
    from engine.core.devicelooks import DevicePalette
    from engine.runtime.codex import CodexEntry
    from engine.ui.paint import Painter

GAP_IN: Final = 8                     # between paragraphs of one delivery
GAP_OUT: Final = 28                   # after a delivery's last paragraph
SIGNAL: Final = "[signal]"
CELL: Final = 0.6                     # a terminal cell, × the text size (Noto Sans Mono's)
SERIF_FACES: Final = FaceSet({Face.REGULAR: FaceSource(None, Face.SERIF),
                              Face.BOLD: FaceSource(None, Face.SERIF),
                              Face.ITALIC: FaceSource(None, Face.SERIF_ITALIC),
                              Face.BOLD_ITALIC: FaceSource(None, Face.SERIF_ITALIC)})
SERIF_LOOKS: Final = ("letters", "pigeon")
SERIF_ROLES: Final = ("via", "sign")
BLINK_S: Final = 0.55
CARD_INSET: Final = {"letters": 14.0, "pigeon": 30.0, "terminal": 12.0, "mind": 26.0}


@dataclass(frozen=True, slots=True)
class ParaLook:
    """How one paragraph of an Inbox entry is dressed: its device ``look``, its ``role``
    ("via": the line above a message, "time", "them", "me" or "sign"), and whether it is the
    ``first`` / ``last`` paragraph of its delivery."""

    look: str
    role: str
    first: bool = False
    last: bool = False


@dataclass(frozen=True, slots=True)
class _Spec:
    """A paragraph's place: text insets from the row's left and right, padding above and
    below, the gap after it, and how its lines align ("left", "center", "right")."""

    left: float
    right: float
    top: float
    bottom: float
    gap: float
    align: str = "left"
    mono: bool = False


@dataclass(frozen=True, slots=True)
class _MonoLine:
    cells: tuple[tuple[str, bool], ...]      # (grapheme, bold)
    pitch: int


@dataclass(frozen=True, slots=True)
class _MonoPage:
    lines: tuple[_MonoLine, ...]


@dataclass
class _InboxBody(_Body):
    """``_Body`` with each paragraph's ``_Spec`` and look, and a layout per text width."""

    specs: tuple[_Spec, ...] = ()
    looks: tuple[ParaLook, ...] = ()
    contexts: dict[tuple[float, bool], Any] = field(default_factory=dict)

    def gap(self, index: int) -> int:
        base = round(self.specs[index].gap) if index < len(self.pages) - 1 else 0
        return base + self.extra.get(index, 0)


def spec_for(look: ParaLook, width: float) -> _Spec:
    """``look``'s place in a body ``width`` wide (module docstring)."""
    gap = GAP_OUT if look.last else GAP_IN
    top_pad = 0.0
    bottom_pad = 0.0
    role, kind = look.role, look.look
    if kind in ("letters", "pigeon", "terminal"):
        side = {"letters": 36.0, "pigeon": 52.0, "terminal": 30.0}[kind]
        top_pad = 18.0 if look.first else 0.0
        bottom_pad = 18.0 if look.last else 0.0
        gap = (GAP_OUT if look.last else 10.0)
        align = "left"
        if role == "via" and kind == "letters":
            align, bottom_pad = "center", bottom_pad + 14.0
        elif role == "sign":
            align = "right"
        seal_room = 44.0 if kind == "pigeon" else 0.0
        return _Spec(side, side + seal_room, top_pad, bottom_pad, gap, align,
                     mono=kind == "terminal")
    if kind == "radio":
        if role == "via":
            return _Spec(16.0, 16.0 + 110.0, 2.0, 16.0, 10.0)
        return _Spec(34.0, 16.0, 0.0, 0.0, gap if look.last else 10.0)
    if kind == "mind":
        bottom_pad = 10.0 if look.last else 0.0
        top_pad = 10.0 if look.first else 0.0
        align = "right" if role == "sign" else "center" if role in ("via", "time") else "left"
        return _Spec(56.0, 56.0, top_pad, bottom_pad, gap if look.last else 10.0, align)
    # phone (and anything else)
    if role in ("via", "time"):
        return _Spec(16.0, 16.0, 0.0, 0.0, gap if look.last else 10.0, "center")
    wide = round(width * 0.24)
    if role == "me":
        return _Spec(wide, 28.0, 8.0, 8.0, gap if look.last else 14.0, "end")
    if role == "sign":
        return _Spec(28.0, 28.0, 0.0, 0.0, gap, "right")
    return _Spec(28.0, wide, 8.0, 8.0, gap if look.last else 14.0)


def _extent(line) -> float:
    return max((g.right for g in line.glyphs if not g.hangs), default=0.0)


class InboxView(CodexView):
    """The Inbox's ``CodexView`` (module docstring)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.clock = 0.0

    @property
    def reduce_motion(self) -> bool:
        return bool(getattr(self.ui, "reduce_motion", False))

    def update(self, dt: float) -> None:
        self.clock += dt
        super().update(dt)

    def _own_font(self) -> bool:
        """The game sets its own text font (the device looks keep it then)."""
        faces = getattr(self.ui.theme, "faces", None)
        return faces is not None and any(src.ref is not None
                                         for src in faces.faces.values())

    def _serif(self, look: ParaLook) -> bool:
        return (look.look in SERIF_LOOKS and look.role in SERIF_ROLES
                and not self._own_font())

    def _mono_font(self, size: int, bold: bool = False) -> FontSpec:
        if self._own_font():
            return self.ui.theme.font(size, bold=bold)
        return FontSpec(None, size, Face.MONO)

    # -- layout --

    def _looks(self, entry: "CodexEntry") -> tuple[ParaLook, ...] | None:
        get = getattr(self.port, "paragraph_looks", None)
        found = get(entry.name) if get is not None else None
        if found is None or len(found) != len(entry.paragraphs):
            return None
        return tuple(found)

    def _paragraphs(self, entry: "CodexEntry", width: float) -> _Body:
        looks = self._looks(entry)
        if looks is None:
            return super()._paragraphs(entry, width)
        cfg = self.cfg
        size = scaled(cfg.panel.text_size, self.scale)
        p = pitch(size)
        key = (entry.name, entry.paragraphs, looks, round(width, 3), size)
        layouts = self._cache.layouts
        found = layouts.get(key)
        if found is None:
            ctx = LayoutContext(self.ui.assets, self.ui.theme.faces, size,
                                _hex(cfg.panel.text_color), width, 1.0e9)
            specs = tuple(spec_for(look, width) for look in looks)
            found = _InboxBody(entry.paragraphs, ctx, [None] * len(looks), [], p,
                               specs=specs, looks=looks)
            for i, paragraph in enumerate(entry.paragraphs):
                spec = specs[i]
                room = max(1.0, width - spec.left - spec.right)
                plain = "".join(span.text for span in paragraph.plain())
                lines = math.ceil(LAZY_ESTIMATE * self._measure(plain, size) / room)
                found.heights.append(spec.top + max(p, lines * p) + spec.bottom + found.gap(i))
            layouts[key] = found
            while len(layouts) > BODY_LAYOUT_CACHE:
                del layouts[next(iter(layouts))]
        return found

    def _context(self, body: _InboxBody, width: float, serif: bool = False) -> Any:
        found = body.contexts.get((width, serif))
        if found is None:
            ctx = body.ctx
            found = body.contexts[(width, serif)] = dataclasses.replace(
                ctx, width=width, **({"faces": SERIF_FACES} if serif else {}))
        return found

    def _mono(self, body: _InboxBody, index: int, width: float) -> _MonoPage:
        """Paragraph ``index`` in fixed cells, wrapped at word ends."""
        size = body.ctx.text_size
        cols = max(8, int(width // (CELL * size)))
        cells: list[tuple[str, bool]] = []
        for span in body.paragraphs[index].plain():
            cells.extend((ch, span.style.bold) for ch in span.text.replace("\n", " "))
        lines: list[tuple[tuple[str, bool], ...]] = []
        while cells:
            if len(cells) <= cols:
                lines.append(tuple(cells))
                break
            cut = next((i for i in range(cols, 0, -1) if cells[i][0] == " "), cols)
            lines.append(tuple(cells[:cut]))
            cells = cells[cut + 1:] if cut < len(cells) and cells[cut][0] == " " else cells[cut:]
        return _MonoPage(tuple(_MonoLine(line, body.pitch) for line in lines))

    def _ensure(self, index: int) -> bool:
        body = self._detail.body
        if not isinstance(body, _InboxBody):
            return super()._ensure(index)
        if not 0 <= index < len(body.pages) or body.pages[index] is not None:
            return False
        spec = body.specs[index]
        width = max(1.0, body.ctx.width - spec.left - spec.right)
        if spec.mono:
            page: Any = self._mono(body, index, width)
        else:
            page = LineLayout(body.paragraphs[index],
                              self._context(body, width, self._serif(body.looks[index]))
                              ).page(0)
        self.layouts_made += 1
        scroll = self.body
        first = scroll.visible_range().start if self.body_rows else 0
        before = body.heights[index]
        body.pages[index] = page
        body.heights[index] = (spec.top + max(body.pitch, sum(line.pitch for line in page.lines))
                               + spec.bottom + body.gap(index))
        scroll.heights_changed()
        if index < first:
            scroll.scroll += body.heights[index] - before
            scroll._clamp_scroll()
        return True

    # -- drawing --

    def _frame(self) -> int:
        return 0 if self.reduce_motion else int(self.clock * 10)

    def _draw_paragraph(self, p: "Painter", index: int, box: Box) -> None:
        body = self._detail.body
        if not isinstance(body, _InboxBody) or not 0 <= index < len(body.specs):
            super()._draw_paragraph(p, index, box)
            return
        look, spec = body.looks[index], body.specs[index]
        colors = palette(self.cfg, look.look)
        page = body.pages[index]
        text_h = (sum(line.pitch for line in page.lines) if page is not None
                  else box.h - spec.top - spec.bottom - body.gap(index))
        text_h = max(body.pitch, text_h)
        width = max(1.0, box.w - spec.left - spec.right)
        self._backdrop(p, index, look, spec, colors, box, text_h, page, width,
                       body.gap(index))
        if page is None:
            return                                      # laid out next frame
        color = self._text_color(look, colors)
        x0, y0 = box.x + spec.left, box.y + spec.top
        if isinstance(page, _MonoPage):
            self._draw_mono(p, page, x0, y0, rgb(color), body.ctx.text_size, look, colors)
            return
        canvas = p.canvas
        block = width - max((_extent(line) for line in page.lines), default=0.0)
        for line in page.lines:
            shift = block if spec.align == "end" else 0.0
            if spec.align in ("center", "right"):
                room = width - _extent(line)
                shift = room / 2 if spec.align == "center" else room
            baseline = y0 + line.baseline
            run: list[str] = []
            run_key: tuple | None = None
            run_x = 0.0
            for glyph in line.glyphs:
                if glyph.hangs:
                    continue
                key = (glyph.face, glyph.size, color)
                if key != run_key:
                    if run and run_key is not None:
                        self._draw_run(canvas, "".join(run), run_key, x0 + shift + run_x,
                                       baseline)
                    run, run_key, run_x = [], key, glyph.x
                run.append(glyph.text)
            if run and run_key is not None:
                self._draw_run(canvas, "".join(run), run_key, x0 + shift + run_x, baseline)

    @staticmethod
    def _text_color(look: ParaLook, c: "DevicePalette") -> str:
        if look.role in ("via", "time"):
            return c.heading
        if look.role == "me" and look.look == "phone":
            return c.me_text
        return c.text

    def _draw_mono(self, p: "Painter", page: _MonoPage, x0: float, y0: float, color,
                   size: int, look: ParaLook, c: "DevicePalette") -> None:
        canvas = p.canvas
        cell = CELL * size
        regular = self._mono_font(size)
        bold = self._mono_font(size, bold=True)
        measure = measure_with(self.ui.assets, regular)
        if look.role in ("via", "time"):
            color = rgb(c.heading)
        y = y0
        end = (x0, y0)
        for line in page.lines:
            for i, (ch, strong) in enumerate(line.cells):
                if ch != " ":
                    font = bold if strong else regular
                    w = measure(ch, size)
                    canvas.draw_text(ch, font, color, (x0 + i * cell + (cell - w) / 2,
                                                       y + (line.pitch - size * 1.36) / 2))
            end = (x0 + len(line.cells) * cell, y)
            y += line.pitch
        if look.last and (self.reduce_motion or int(self.clock / BLINK_S) % 2 == 0):
            cursor(canvas, end[0] + cell * 0.3, end[1] + page.lines[-1].pitch * 0.18
                   if page.lines else y0, cell * 0.8, (page.lines[-1].pitch if page.lines
                                                        else size) * 0.66, rgb(c.text))

    def _block(self, body: _InboxBody, index: int, box: Box) -> tuple[float, float]:
        """The top and bottom of the delivery paragraph ``index`` (in ``box``) belongs to,
        on the canvas (unlaid paragraphs at their estimated height)."""
        looks, heights = body.looks, body.heights
        first = index
        while first > 0 and not looks[first].first:
            first -= 1
        last = index
        while last < len(looks) - 1 and not looks[last].last:
            last += 1
        top = box.y - sum(heights[first:index])
        bottom = box.y + sum(heights[index:last + 1]) - body.gap(last)
        return top, bottom

    def _backdrop(self, p: "Painter", index: int, look: ParaLook, spec: _Spec,
                  c: "DevicePalette", box: Box, text_h: float, page: Any, width: float,
                  gap: float) -> None:
        """What a paragraph sits on: the delivery's card (drawn whole, clipped to this
        paragraph's row, so it is one card at any scroll), its bubble, its marks."""
        kind, role = look.look, look.role
        canvas = p.canvas
        top = box.y + spec.top
        body = self._detail.body
        assert isinstance(body, _InboxBody)
        if kind in ("letters", "pigeon", "terminal", "mind"):
            y0, y1 = self._block(body, index, box)
            inset = CARD_INSET[kind]
            card = Box(box.x + inset, y0 + 2, box.w - 2 * inset, max(1.0, y1 - y0 - 4))
            with clipped(p, Box(box.x, box.y, box.w, box.h)):
                if kind == "mind":
                    breath = 1.0 if self.reduce_motion else \
                        0.85 + 0.15 * math.sin(self.clock * 1.6)
                    self._glow(p, card, c, breath)
                elif kind == "terminal":
                    p.shape(card, FrameSpec(rgb(c.card or c.page), 1.0, rgb(c.edge), 2, 6))
                else:
                    edge = rgb(c.edge)
                    p.shape(Box(card.x + 3, card.y + 3, card.w, card.h),
                            FrameSpec(edge, 0.35, edge, 0, 6))            # a little shadow
                    p.shape(card, FrameSpec(rgb(c.card or c.page), 1.0, edge, 1, 6))
                    if kind == "pigeon":                    # tied with twine, sealed
                        canvas.fill(rgb(c.mark), (card.right - 32, card.y, 3, card.h))
                        seal(p, card.right - 30.5, card.y + 26, rgb(c.accent),
                             rgb(c.mark), ring=rgb(c.card or c.page))
            if kind == "letters" and role == "via":
                mid = card.x + card.w / 2
                y = top + text_h + 8
                canvas.fill(rgb(c.heading), (mid - 48, y, 96, 1))
                p.ellipse(Box(mid - 3, y - 2.5, 6, 6), rgb(c.accent))
            return
        if kind == "radio":
            if role == "via":
                canvas.draw_text(SIGNAL, self.ui.theme.font(scaled(self.cfg.panel.text_size,
                                                                   self.scale)),
                                 rgb(c.me_text), (box.right - 16, top), anchor="topright")
                static_rule(canvas, box.x + 16, top + text_h + 8, box.w - 32, rgb(c.mark),
                            self._frame() + 31 * index)
            else:
                y_top = box.y if not look.first else box.y + 2
                y_end = box.y + spec.top + text_h + (0 if look.last else gap)
                canvas.fill(rgb(c.mark), (box.x + 18, y_top, 2, y_end - y_top))
            return
        # phone
        if role not in ("them", "me") or page is None:
            return
        reach = max((_extent(line) for line in page.lines), default=0.0)
        pad = 12.0
        bx = box.x + spec.left - pad
        if role == "me":
            bx = box.x + spec.left + width - reach - pad
        bubble = Box(bx, top - spec.top + 1, reach + 2 * pad, spec.top + text_h + spec.bottom - 2)
        fill = rgb(c.me_card if role == "me" else (c.card or c.page))
        p.shape(bubble, FrameSpec(fill, 1.0, fill, 0, 14))

    @staticmethod
    def _glow(p: "Painter", box: Box, c: "DevicePalette", breath: float) -> None:
        """A thought's soft glow: nested rounded hazes of the accent, widest faintest."""
        for grow, alpha in ((0, 0.035), (-6, 0.04), (-12, 0.045), (-18, 0.05), (-24, 0.05)):
            inner = Box(box.x - grow, box.y - grow, box.w + 2 * grow, box.h + 2 * grow)
            if inner.w > 0 and inner.h > 0:
                p.shape(inner, FrameSpec(rgb(c.accent), alpha, rgb(c.accent), 0,
                                         max(8, 36 + grow)), alpha=breath)


__all__ = ["InboxView", "ParaLook", "spec_for"]
