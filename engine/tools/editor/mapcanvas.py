"""The story map's canvas painter (F58 ``04-technical.md`` §7.8, §7.9, §7.10; ``01`` PR-F58-06,
08, 11, 14; UI-F58-01, 02; ``07`` I-8, I-10). Tk, but its own file: ``views.StoryMapView``
draws through it (F58 W1).

Why this module exists: the map used to ``delete("all")`` and draw every box, arrow and
chip again on any change (348 ms at 300 scenes, 1.7 s at 1,000). ``MapPainter`` keeps a
**registry** of the canvas items it drew, keyed by label name and by ``EdgeKey`` ``(src,
dst, kind)``, with stored item ids and an owner map from id back to key, so an update
touches only what ``storymap.relayout``'s ``LayoutDiff`` names:

- ``draw(layout)``: a full draw (first draw, zoom, file filter, Tidy up, scale change, or a
  diff over ``FULL_REDRAW_OVER`` boxes and arrows). ``apply(layout, diff)``: removes and
  adds items by stored id, redraws a restyled or moved box's few items, ``coords`` for
  rerouted arrows, moves chips. No ``delete("all")``, no tag shared by many items is
  restyled, no index tag (``box{i}``) exists (I-10).
- **Layers**: hidden marker items give the stacking order, bottom to top: arrows < preview
  < boxes < glow < chips < ring. A new item is ``tag_lower``-ed under its layer's marker.
- **Chips** sit where ``storymap.chip_center`` says (the estimated chip's slot along the
  curve, or the row gap); the measured chip is drawn there and never re-slotted (I-8).
- **``file:line`` texts** (Q4, main-session ruling on P0): a box whose only change is its
  line gets its new text at most ``LINES_PER_PAINT`` at a time, boxes in view first; the
  rest drain in ``LINE_SLICE_MS`` idle slices (``drain_lines``; the view also drains what
  scrolls into view).
- **Glow** (``glow``): ``livemap.GlowSet`` changes become a 3 px ``map.changed`` outline in
  the glow layer (blended into the border on fade steps), or the arrow's own line recoloured
  (a selected arrow is left alone); ghosts are dashed outlines of what was removed.
- **Preview** (``preview``): a card's proposed boxes and arrows dashed in ``map.preview``
  ("proposed"), what it removes dashed in ``map.previewRemove`` with a strike line
  ("removed"); in the preview layer, never in the owner map, so ``box_at``/``edge_at``,
  hover, click and drag ignore them.
- The **scroll region only grows** (``extent``); ``items_of(name)`` replaces the ``box{i}``
  tags in tests (R4).
- **Pictures** (Studio UX 3.1, ``set_pictures``): the same layout drawn stretched by
  ``mapsketch.PICTURE_STRETCH``; each box is a sketch of its opening shot over its name and a
  short line, and ``sketcher`` (``mapsketch.SketchPainter``) draws the sketches of the boxes
  in view on idle.
"""

import time
import tkinter as tk
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from tkinter import font as tkfont
from typing import Final

from engine.tools.editor.livemap import MARK_PROPOSED, MARK_REMOVED, GlowKey, Preview
from engine.tools.editor.mapsketch import (
    PICTURE_STRETCH, PLACEHOLDER, TEXT_GAP, SketchPainter, detail_text, thumb_rect)
from engine.tools.editor.storymap import (
    BOX_HEIGHT, BOX_WIDTH, MARK_BLOCKED, MARK_DELETES_SAVES, MARK_ENDING, MARK_START, Box,
    EdgeKey, LayoutDiff, MapLayout, chip_center, chip_text, curve_points, relayout)
from engine.tools.editor.syntax import PLAIN_COLOR
from engine.tools.editor.theme import THEME, blend

# The map's look (views.py's F45/F46 values; views imports them from here after W1).
MAP_MARGIN: Final = 16
MAP_NAME_PX: Final = 13
MAP_DETAIL_PX: Final = 11
MAP_PAD: Final = 8
BOX_FILL: Final = THEME["map.box"]
BOX_OUTLINE: Final = THEME["map.boxBorder"]
START_COLOR: Final = THEME["map.start"]
START_BAR: Final = 3
RING_COLOR: Final = THEME["map.ring"]
RING_GAP: Final = 3
LINK_COLOR: Final = THEME["map.link"]
ENDING_COLOR: Final = THEME["map.ending"]
CHAPTER_COLOR: Final = THEME["map.chapter"]
MINIGAME_COLOR: Final = THEME["map.minigame"]
WARNING_COLOR: Final = THEME["marker.warning"]
MUTED: Final = THEME["muted"]
CHIP_FILL: Final = THEME["map.chip"]
CHIP_BORDER: Final = THEME["map.chipBorder"]
CHIP_TEXT: Final = THEME["map.chipText"]
CHIP_IF: Final = THEME["map.chipIf"]
CHIP_IF_TEXT: Final = "if"
CHIP_RADIUS: Final = 4
CHIP_PAD_X: Final = 6
CHIP_PAD_Y: Final = 1
CHIP_FONT_PX: Final = 12
ARROW_SHAPE: Final = (8, 10, 4)
EDGE_STYLES: Final[Mapping[str, tuple[tuple[int, ...], str]]] = {
    "jump": ((), LINK_COLOR), "call": ((6, 4), LINK_COLOR), "menu": ((2, 4), LINK_COLOR)}
GLOW_COLOR: Final = THEME["map.changed"]
PREVIEW_COLOR: Final = THEME["map.preview"]
PREVIEW_REMOVE: Final = THEME["map.previewRemove"]
GLOW_PX: Final = 3                              # PR-11: a glow is 3 px, a border 1
DASH: Final = (4, 3)
ELLIPSIS: Final = "…"
LAYERS: Final = ("arrows", "preview", "boxes", "glow", "chips", "ring")
LINES_PER_PAINT: Final = 50                     # main-session ruling on P0's paint row
LINE_SLICE_MS: Final = 4
FULL_REDRAW_OVER: Final = 200                   # PR-06: a bigger diff redraws everything
TAG_BOX: Final = "box"                          # every box item (box_at's test); not styled
TAG_EDGE: Final = "edge"
TAG_CHIP: Final = "chip"


def round_rect(x0: float, y0: float, x1: float, y1: float, r: float) -> list[float]:
    """A rounded rectangle's points for ``create_polygon(smooth=True)`` (08 §2 radii)."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


def elide(text: str, width: int, measure: Callable[[str], int]) -> str:
    """``text`` cut at the end with ``…`` so ``measure`` of it is at most ``width``; ``""``
    when not even ``…`` fits."""
    if measure(text) <= width:
        return text
    if measure(ELLIPSIS) > width:
        return ""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + ELLIPSIS) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + ELLIPSIS


@dataclass(slots=True)
class BoxItems:
    """One box's canvas items by role (``rect`` first; ``name``, ``where`` and ``marks``
    are what ``stick_names`` moves)."""

    rect: int
    items: list[int] = field(default_factory=list)
    name: int | None = None
    where: int | None = None
    marks: int | None = None
    thumb: int | None = None                    # Pictures: the sketch's ground


class MapPainter:
    """Draws a ``MapLayout`` on ``canvas`` and keeps it in step (see the module doc).
    ``scale`` is zoom × screen scale, ``dpi`` the screen scale; the fonts are the view's,
    sized for the zoom by the caller (``set_scale``). ``idle(fn)`` schedules ``fn`` when Tk
    is idle (default ``canvas.after_idle``); ``clock()`` is seconds."""

    def __init__(self, canvas: tk.Canvas, *, name_font: tkfont.Font, detail_font: tkfont.Font,
                 chip_font: tkfont.Font, scale: float = 1.0, dpi: float = 1.0,
                 idle: Callable[[Callable[[], None]], object] | None = None,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self.canvas = canvas
        self.name_font, self.detail_font, self.chip_font = name_font, detail_font, chip_font
        self.scale, self.dpi = scale, dpi
        self._idle = idle or (lambda fn: canvas.after_idle(fn))
        self._clock = clock
        self.layout: MapLayout | None = None
        self.boxes: dict[str, BoxItems] = {}
        self.edges: dict[EdgeKey, int] = {}
        self.chips: dict[EdgeKey, list[int]] = {}
        self.owner: dict[int, tuple[str, object]] = {}   # item → ("box", name) | ("edge", key)
        self.markers: dict[str, int] = {}
        self.glows: dict[GlowKey, int] = {}              # glow outlines and ghosts
        self.lit: dict[EdgeKey, float] = {}              # arrows recoloured by a glow
        self.selected_edge: EdgeKey | None = None
        self.preview_items: list[int] = []
        self.extent = (0.0, 0.0)
        self.pending_lines: dict[str, None] = {}
        self._draining = False
        self._measures: dict[tuple[str, str], int] = {}
        self._old: dict[str, tuple[float, float]] = {}   # removed boxes' corners (ghosts)
        self._old_edges: dict[EdgeKey, list[float]] = {}
        self.pictures = False                            # Studio UX 3.1: picture boxes
        self.stretch = (1.0, 1.0)
        self.sketcher = SketchPainter(self, clock=clock)

    # -- Geometry ------------------------------------------------------------------------------

    def set_scale(self, scale: float, dpi: float | None = None) -> None:
        """A new zoom (the caller resizes the fonts and then calls ``draw``)."""
        self.scale = scale
        if dpi is not None:
            self.dpi = dpi
        self._measures.clear()

    def set_pictures(self, on: bool) -> None:
        """Picture boxes (3.1) or Compact; the caller draws again."""
        self.pictures = bool(on)
        self.stretch = PICTURE_STRETCH if on else (1.0, 1.0)

    def corner(self, x: float, y: float) -> tuple[float, float]:
        m, s = MAP_MARGIN * self.dpi, self.scale
        kx, ky = self.stretch
        return m + x * s * kx, m + y * s * ky

    def box_size(self) -> tuple[float, float]:
        """A box's size on the canvas now (Pictures: stretched)."""
        return (BOX_WIDTH * self.scale * self.stretch[0],
                BOX_HEIGHT * self.scale * self.stretch[1])

    def rect_of(self, box: Box) -> tuple[float, float, float, float]:
        x0, y0 = self.corner(box.x, box.y)
        w, h = self.box_size()
        return x0, y0, x0 + w, y0 + h

    def box_rect(self, name: str) -> tuple[float, float, float, float] | None:
        """Box ``name``'s rectangle on the canvas, or None when it isn't shown."""
        if self.layout is None or (i := self.layout.index_of(name)) is None:
            return None
        return self.rect_of(self.layout.boxes[i])

    def edge_points(self, layout: MapLayout, index: int) -> list[float]:
        edge = layout.edges[index]
        k, n = layout.ports[index]
        a, b = layout.boxes[edge.src], layout.boxes[edge.dst]
        assert layout.ends is not None
        return curve_points(self.rect_of(a), self.rect_of(b), (k + 1) / (n + 1),
                            bend=20 * self.scale * self.stretch[0],
                            loop=edge.src == edge.dst, end=layout.ends.get(index))

    def measure(self, font: tkfont.Font, text: str) -> int:
        key = (str(font), text)
        found = self._measures.get(key)
        if found is None:
            found = self._measures[key] = font.measure(text)
        return found

    # -- Registry ------------------------------------------------------------------------------

    def items_of(self, name: str) -> tuple[int, ...]:
        """Box ``name``'s canvas items (tests' replacement for the ``box{i}`` tags)."""
        found = self.boxes.get(name)
        return () if found is None else tuple(found.items)

    def edge_item(self, key: EdgeKey) -> int | None:
        return self.edges.get(key)

    def chip_items(self, key: EdgeKey) -> tuple[int, ...]:
        return tuple(self.chips.get(key, ()))

    def box_at(self, cx: float, cy: float) -> str | None:
        """The box under canvas point (cx, cy), topmost first; previews and ghosts never."""
        for item in reversed(self.canvas.find_overlapping(cx, cy, cx, cy)):
            owner = self.owner.get(item)
            if owner is not None and owner[0] == "box":
                return owner[1]                          # type: ignore[return-value]
        return None

    def edge_at(self, cx: float, cy: float, r: float) -> EdgeKey | None:
        """The arrow (or its chip) within ``r`` of canvas point (cx, cy)."""
        for item in reversed(self.canvas.find_overlapping(cx - r, cy - r, cx + r, cy + r)):
            owner = self.owner.get(item)
            if owner is not None and owner[0] in ("edge", "chip"):
                return owner[1]                          # type: ignore[return-value]
        return None

    # -- Layers --------------------------------------------------------------------------------

    def put(self, item: int, layer: str) -> int:
        """``item`` at the top of ``layer`` (one of ``LAYERS``; the view's ring and drag
        line use this too)."""
        self.canvas.tag_lower(item, self.markers[layer])
        return item

    # -- Full draw -----------------------------------------------------------------------------

    def clear(self) -> None:
        """Every item this painter drew goes (the view's empty states use this)."""
        canvas = self.canvas
        for found in self.boxes.values():
            for item in found.items:
                canvas.delete(item)
        for item in (*self.edges.values(), *(i for g in self.chips.values() for i in g),
                     *self.glows.values(), *self.preview_items, *self.markers.values()):
            canvas.delete(item)
        self.boxes, self.edges, self.chips, self.owner = {}, {}, {}, {}
        self.glows, self.lit, self.preview_items, self.markers = {}, {}, [], {}
        self.pending_lines.clear()
        self.sketcher.clear()
        self.layout = None

    def draw(self, layout: MapLayout) -> None:
        """Everything again, in layer order (markers created between the layers)."""
        self.clear()
        canvas = self.canvas
        self.layout = layout
        for index in range(len(layout.edges)):
            self._draw_edge(layout, index)
        self.markers["arrows"] = canvas.create_line(0, 0, 0, 0, state="hidden")
        self.markers["preview"] = canvas.create_line(0, 0, 0, 0, state="hidden")
        for box in layout.boxes:
            self._draw_box(box)
        self.markers["boxes"] = canvas.create_line(0, 0, 0, 0, state="hidden")
        self.markers["glow"] = canvas.create_line(0, 0, 0, 0, state="hidden")
        for index, edge in enumerate(layout.edges):
            if edge.choice:
                self._draw_chip(layout, index)
        self.markers["chips"] = canvas.create_line(0, 0, 0, 0, state="hidden")
        self.markers["ring"] = canvas.create_line(0, 0, 0, 0, state="hidden")
        self._grow(layout)
        self.sketcher.schedule()

    # -- Incremental ---------------------------------------------------------------------------

    def apply(self, layout: MapLayout, diff: LayoutDiff) -> bool:
        """Bring the canvas from ``self.layout`` to ``layout``. False (nothing done) when it
        needs a full ``draw`` instead: no previous draw, ``diff.full``, or a diff over
        ``FULL_REDRAW_OVER``."""
        old = self.layout
        if old is None or diff.full or diff.size > FULL_REDRAW_OVER or not self.markers:
            return False
        canvas = self.canvas
        self.layout = layout
        self._old, self._old_edges = {}, {}             # this update's ghosts only
        for name in diff.removed:
            gone = self.boxes.pop(name, None)
            if gone is not None:
                j = old.index_of(name)
                if j is not None:
                    self._old[name] = (old.boxes[j].x, old.boxes[j].y)
                for item in gone.items:
                    canvas.delete(item)
                    self.owner.pop(item, None)
            self.pending_lines.pop(name, None)
        for key in diff.edges_removed:
            item = self.edges.pop(key, None)
            if item is not None:
                self._old_edges[key] = canvas.coords(item)
                canvas.delete(item)
                self.owner.pop(item, None)
            self._drop_chip(key)
        redraw = dict.fromkeys((*diff.added, *diff.moved, *diff.restyled))
        for name in redraw:
            j = layout.index_of(name)
            if j is None:
                continue
            gone = self.boxes.pop(name, None)
            for item in gone.items if gone is not None else ():
                canvas.delete(item)
                self.owner.pop(item, None)
            self._draw_box(layout.boxes[j], layer=True)
            self.pending_lines.pop(name, None)
        keys = layout.edge_keys or {}
        for key in diff.edges_added:
            i = keys.get(key)
            if i is not None:
                self._draw_edge(layout, i, layer=True)
        for key in diff.edges_rerouted:
            i, item = keys.get(key), self.edges.get(key)
            if i is not None and item is not None:
                canvas.coords(item, *self.edge_points(layout, i))
        for key in dict.fromkeys((*diff.edges_added, *diff.edges_restyled,
                                  *diff.edges_rerouted, *diff.chips_moved)):
            i = keys.get(key)
            if i is None:
                continue
            self._drop_chip(key)
            if layout.edges[i].choice:
                self._draw_chip(layout, i, layer=True)
        for name in diff.lines:
            if name not in redraw and name in self.boxes:
                self.pending_lines[name] = None
        self._paint_lines(LINES_PER_PAINT)
        self._grow(layout)
        self.sketcher.schedule()
        return True

    # -- Boxes ---------------------------------------------------------------------------------

    def _where(self, box: Box, room: int) -> str:
        where = f"{box.file}:{box.line}" if box.file is not None else ""
        if box.chapter is not None:
            where = elide(where, room, lambda t: self.measure(self.detail_font, t))
        return where

    def _draw_box(self, box: Box, *, layer: bool = False) -> BoxItems:
        if self.pictures:
            return self._draw_picture_box(box, layer=layer)
        canvas, s, name = self.canvas, self.scale, box.name
        x0, y0, x1, y1 = self.rect_of(box)
        line = max(1, round(self.dpi))
        pad = MAP_PAD * s
        tags = (TAG_BOX,)
        ending = MARK_ENDING in box.marks
        rect = canvas.create_rectangle(x0, y0, x1, y1, fill=BOX_FILL, width=line, tags=tags,
                                       outline=ENDING_COLOR if ending else BOX_OUTLINE)
        found = BoxItems(rect, [rect])
        items = found.items
        if ending:
            inset = 3 * s
            items.append(canvas.create_rectangle(x0 + inset, y0 + inset, x1 - inset,
                                                 y1 - inset, outline=ENDING_COLOR,
                                                 width=line, tags=tags))
        if MARK_START in box.marks:
            items.append(canvas.create_rectangle(
                x0 + line, y0 + line, x0 + line + max(2, round(START_BAR * s)), y1,
                fill=START_COLOR, outline="", tags=tags))
        tag_x = x0
        tags_under = []
        if MARK_BLOCKED in box.marks:
            tags_under.append((f"⚠ {MARK_BLOCKED}", WARNING_COLOR))
        if MARK_DELETES_SAVES in box.marks:
            tags_under.append((f"⚠ {MARK_DELETES_SAVES}", WARNING_COLOR))
        tags_under += [(f"▶ {game}", MINIGAME_COLOR) for game in box.minigames[:2]]
        for text, color in tags_under:               # small tags under the box (row gap)
            item = canvas.create_text(tag_x + 4 * s, y1 + 3 * s, anchor="nw", text=text,
                                      font=self.detail_font, fill=color, tags=tags)
            width = self.measure(self.detail_font, text)
            height = self.detail_font.metrics("linespace")
            items.append(item)
            items.append(canvas.create_rectangle(tag_x + 4 * s - 3 * s, y1 + 3 * s - 1,
                                                 tag_x + 4 * s + width + 3 * s,
                                                 y1 + 3 * s + height + 1, outline=color,
                                                 tags=tags))
            tag_x = tag_x + 4 * s + width + 6 * s
        found.name = canvas.create_text(x0 + pad, y0 + 4 * s, anchor="nw", text=name,
                                        font=self.name_font, fill=PLAIN_COLOR, tags=tags)
        items.append(found.name)
        box_marks = tuple(m for m in box.marks if m not in (MARK_DELETES_SAVES, MARK_BLOCKED))
        name_px = self.measure(self.name_font, name)
        if box.scene is not None:
            left = x0 + 2 * pad + name_px
            marks_px = (self.measure(self.detail_font, ", ".join(box_marks)) + pad
                        if box_marks else 0)
            shown = elide(f"“{box.scene}”", int(x1 - pad - marks_px - left),
                          lambda t: self.measure(self.detail_font, t))
            if shown:
                items.append(canvas.create_text(left, y0 + 4 * s, anchor="nw", text=shown,
                                                font=self.detail_font, fill=MUTED,
                                                tags=tags))
        room = int(x1 - x0 - 3 * pad - self.measure(self.detail_font, box.chapter or ""))
        if box.chapter is not None:
            items.append(canvas.create_text(x1 - pad, y1 - 4 * s, anchor="se",
                                            text=box.chapter, font=self.detail_font,
                                            fill=CHAPTER_COLOR, tags=tags))
        found.where = canvas.create_text(x0 + pad, y1 - 4 * s, anchor="sw",
                                         text=self._where(box, room), font=self.detail_font,
                                         fill=MUTED, tags=tags)
        items.append(found.where)
        room = int(x1 - x0 - 3 * pad - name_px)
        marks = elide(", ".join(box_marks), room,
                      lambda t: self.measure(self.detail_font, t)) \
            if box_marks and box.scene is None else ", ".join(box_marks)
        if marks:
            found.marks = canvas.create_text(x1 - pad, y0 + 4 * s, anchor="ne", text=marks,
                                             font=self.detail_font, fill=MUTED, tags=tags)
            items.append(found.marks)
        for item in items:
            self.owner[item] = ("box", name)
            if layer:
                self.put(item, "boxes")
        self.boxes[name] = found
        return found

    def _frame(self, box: Box, rect: tuple[float, float, float, float]) -> BoxItems:
        """A box's rectangle, an ending's inner border and the start bar."""
        canvas, s = self.canvas, self.scale
        x0, y0, x1, y1 = rect
        line = max(1, round(self.dpi))
        tags = (TAG_BOX,)
        ending = MARK_ENDING in box.marks
        item = canvas.create_rectangle(x0, y0, x1, y1, fill=BOX_FILL, width=line, tags=tags,
                                       outline=ENDING_COLOR if ending else BOX_OUTLINE)
        found = BoxItems(item, [item])
        if ending:
            inset = 3 * s
            found.items.append(canvas.create_rectangle(x0 + inset, y0 + inset, x1 - inset,
                                                       y1 - inset, outline=ENDING_COLOR,
                                                       width=line, tags=tags))
        if MARK_START in box.marks:
            found.items.append(canvas.create_rectangle(
                x0 + line, y0 + line, x0 + line + max(2, round(START_BAR * s)), y1,
                fill=START_COLOR, outline="", tags=tags))
        return found

    def detail_line(self, box: Box, sketch: object = None) -> str:
        """A picture box's second line ("Chapter 2 · 62 lines"), cut to fit."""
        room = int(self.box_size()[0] - 2 * MAP_PAD * self.scale)
        return elide(detail_text(box.chapter, sketch), room,  # type: ignore[arg-type]
                     lambda t: self.measure(self.detail_font, t))

    def _draw_picture_box(self, box: Box, *, layer: bool = False) -> BoxItems:
        """Studio UX 3.1: the sketch's ground (the sketch itself is ``sketcher``'s), the
        name with its marks (or Flowchart title) beside it, then the short line; the
        minigame and warning tags stay under the box. File and line are the tooltip's."""
        canvas, s, name = self.canvas, self.scale, box.name
        rect = self.rect_of(box)
        x0, y0, x1, y1 = rect
        pad = MAP_PAD * s
        tags = (TAG_BOX,)
        found = self._frame(box, rect)
        items = found.items
        tx0, ty0, tx1, ty1 = thumb_rect(rect, s)
        found.thumb = canvas.create_rectangle(tx0, ty0, tx1, ty1, fill=PLACEHOLDER,
                                              outline="", tags=tags)
        items.append(found.thumb)
        top = ty1 + TEXT_GAP * s
        found.name = canvas.create_text(x0 + pad, top, anchor="nw", text=name,
                                        font=self.name_font, fill=PLAIN_COLOR, tags=tags)
        items.append(found.name)
        box_marks = tuple(m for m in box.marks if m not in (MARK_DELETES_SAVES, MARK_BLOCKED))
        room = int(x1 - x0 - 3 * pad - self.measure(self.name_font, name))
        side = ", ".join(box_marks) if box_marks else (
            f"“{box.scene}”" if box.scene is not None else "")
        side = elide(side, room, lambda t: self.measure(self.detail_font, t)) if side else ""
        if side:
            item = canvas.create_text(x1 - pad, top, anchor="ne", text=side,
                                      font=self.detail_font, fill=MUTED, tags=tags)
            items.append(item)
            if box_marks:
                found.marks = item
        found.where = canvas.create_text(x0 + pad, y1 - 4 * s, anchor="sw",
                                         text=self.detail_line(box), font=self.detail_font,
                                         fill=MUTED, tags=tags)
        items.append(found.where)
        self._tags_under(box, x0, y1, items)
        for item in items:
            self.owner[item] = ("box", name)
            if layer:
                self.put(item, "boxes")
        self.boxes[name] = found
        self.sketcher.put_known(box, found, layer=layer)
        return found

    def _tags_under(self, box: Box, x0: float, y1: float, items: list[int]) -> None:
        """The small warning and minigame tags under a picture box (the row gap)."""
        canvas, s, tags = self.canvas, self.scale, (TAG_BOX,)
        tag_x = x0
        under = []
        if MARK_BLOCKED in box.marks:
            under.append((f"⚠ {MARK_BLOCKED}", WARNING_COLOR))
        if MARK_DELETES_SAVES in box.marks:
            under.append((f"⚠ {MARK_DELETES_SAVES}", WARNING_COLOR))
        under += [(f"▶ {game}", MINIGAME_COLOR) for game in box.minigames[:2]]
        for text, color in under:
            item = canvas.create_text(tag_x + 4 * s, y1 + 3 * s, anchor="nw", text=text,
                                      font=self.detail_font, fill=color, tags=tags)
            width = self.measure(self.detail_font, text)
            height = self.detail_font.metrics("linespace")
            items.append(item)
            items.append(canvas.create_rectangle(tag_x + s, y1 + 3 * s - 1,
                                                 tag_x + 7 * s + width,
                                                 y1 + 3 * s + height + 1, outline=color,
                                                 tags=tags))
            tag_x = tag_x + 10 * s + width

    def outline(self, name: str, color: str, width: int) -> None:
        """Box ``name``'s border (selection, hover, drop target), by stored id."""
        found = self.boxes.get(name)
        if found is not None:
            self.canvas.itemconfigure(found.rect, outline=color, width=width)

    # -- Arrows and chips ----------------------------------------------------------------------

    def _draw_edge(self, layout: MapLayout, index: int, *, layer: bool = False) -> int:
        edge = layout.edges[index]
        key = layout.edge_key(index)
        s = self.scale
        dash, color = EDGE_STYLES.get(edge.kind, ((), LINK_COLOR))
        options: dict = {"fill": color, "arrow": "last", "width": max(1, round(self.dpi)),
                         "arrowshape": tuple(max(1, round(n * s)) for n in ARROW_SHAPE),
                         "smooth": True, "tags": (TAG_EDGE, f"edge-{edge.kind}")}
        if dash:
            options["dash"] = dash
        item = self.canvas.create_line(*self.edge_points(layout, index), **options)
        self.edges[key] = item
        self.owner[item] = ("edge", key)
        if layer:
            self.put(item, "arrows")
        return item

    def edge_style(self, key: EdgeKey, chosen: bool) -> None:
        """An arrow drawn selected (2 px accent) or plain, by stored id; a selected arrow
        rises within the arrows layer."""
        item = self.edges.get(key)
        if item is None:
            return
        kind = key[2]
        if chosen:
            self.selected_edge = key
            self.canvas.itemconfigure(item, fill=THEME["map.selected"],
                                      width=max(2, round(2 * self.dpi)))
            self.put(item, "arrows")
        else:
            if self.selected_edge == key:
                self.selected_edge = None
            self.canvas.itemconfigure(item, fill=EDGE_STYLES.get(kind, ((), LINK_COLOR))[1],
                                      width=max(1, round(self.dpi)))
            if key in self.lit:
                self._light(key, self.lit[key])

    def chip_box(self, layout: MapLayout, index: int) -> tuple[float, float, float, float]:
        """Edge ``index``'s measured chip rectangle on the canvas, centred where storymap
        put the estimated chip (never re-slotted, I-8)."""
        edge = layout.edges[index]
        s = self.scale
        text = chip_text(edge.choice)
        pad_x, pad_y, gap = CHIP_PAD_X * s, CHIP_PAD_Y * s, 4 * s
        mark = self.measure(self.chip_font, CHIP_IF_TEXT) + gap if edge.conditional else 0
        w = 2 * pad_x + mark + self.measure(self.chip_font, text)
        h = self.chip_font.metrics("linespace") + 2 * pad_y
        centre = chip_center(layout, index)
        assert centre is not None
        cx, cy = self.corner(*centre)
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    def _draw_chip(self, layout: MapLayout, index: int, *, layer: bool = False) -> list[int]:
        edge = layout.edges[index]
        key = layout.edge_key(index)
        canvas, s = self.canvas, self.scale
        x0, y0, x1, y1 = self.chip_box(layout, index)
        cy = (y0 + y1) / 2
        pad_x, gap = CHIP_PAD_X * s, 4 * s
        mark = self.measure(self.chip_font, CHIP_IF_TEXT) + gap if edge.conditional else 0
        items = [canvas.create_polygon(*round_rect(x0, y0, x1, y1, CHIP_RADIUS * s),
                                       smooth=True, fill=CHIP_FILL, outline=CHIP_BORDER,
                                       width=max(1, round(self.dpi)), tags=(TAG_CHIP,))]
        if edge.conditional:
            items.append(canvas.create_text(x0 + pad_x, cy, anchor="w", text=CHIP_IF_TEXT,
                                            font=self.chip_font, fill=CHIP_IF,
                                            tags=(TAG_CHIP,)))
        items.append(canvas.create_text(x0 + pad_x + mark, cy, anchor="w",
                                        text=chip_text(edge.choice), font=self.chip_font,
                                        fill=CHIP_TEXT, tags=(TAG_CHIP,)))
        for item in items:
            self.owner[item] = ("chip", key)
            if layer:
                self.put(item, "chips")
        self.chips[key] = items
        return items

    def _drop_chip(self, key: EdgeKey) -> None:
        for item in self.chips.pop(key, ()):
            self.canvas.delete(item)
            self.owner.pop(item, None)

    # -- file:line texts (Q4) ------------------------------------------------------------------

    def visible(self) -> tuple[float, float, float, float]:
        c = self.canvas
        return (c.canvasx(0), c.canvasy(0), c.canvasx(c.winfo_width()),
                c.canvasy(c.winfo_height()))

    def _paint_lines(self, limit: int) -> None:
        """Up to ``limit`` pending ``file:line`` texts, boxes in view first; the rest are
        drained on idle."""
        if not self.pending_lines or self.layout is None:
            return
        left, top, right, bottom = self.visible()
        first: list[str] = []
        for name in self.pending_lines:
            r = self.box_rect(name)
            if r is not None and r[2] > left and r[0] < right and r[3] > top and r[1] < bottom:
                first.append(name)
                if len(first) >= limit:
                    break
        for name in first:
            self._paint_line(name)
        if self.pending_lines and not self._draining:
            self._draining = True
            self._idle(self.drain_lines)

    def _paint_line(self, name: str) -> None:
        self.pending_lines.pop(name, None)
        found = self.boxes.get(name)
        if found is None or found.where is None or self.layout is None or self.pictures:
            return                                      # Pictures: file:line is the tip's
        j = self.layout.index_of(name)
        if j is None:
            return
        box = self.layout.boxes[j]
        s = self.scale
        room = int((BOX_WIDTH - 3 * MAP_PAD) * s
                   - self.measure(self.detail_font, box.chapter or ""))
        self.canvas.itemconfigure(found.where, text=self._where(box, room))

    def drain_lines(self, budget_ms: float = LINE_SLICE_MS) -> None:
        """One idle slice: pending texts for ``budget_ms``, boxes in view first; schedules
        the next slice while any are left."""
        self._draining = False
        start = self._clock()
        self._paint_lines(LINES_PER_PAINT)
        while self.pending_lines and (self._clock() - start) * 1000 < budget_ms:
            self._paint_line(next(iter(self.pending_lines)))
        if self.pending_lines and not self._draining:
            self._draining = True
            self._idle(self.drain_lines)

    def drain_visible(self) -> None:
        """What scrolled into view gets its text now (the view calls this on scroll)."""
        self._paint_lines(len(self.pending_lines))

    # -- Scroll region -------------------------------------------------------------------------

    def _grow(self, layout: MapLayout) -> None:
        """The scroll region covers the drawing and never shrinks (PR-08)."""
        margin = MAP_MARGIN * self.dpi
        width = 2 * margin + layout.width * self.scale * self.stretch[0]
        height = 2 * margin + layout.height * self.scale * self.stretch[1]
        chips = self.canvas.bbox(TAG_CHIP)
        if chips:
            width, height = max(width, chips[2] + margin), max(height, chips[3] + margin)
        grown = (max(self.extent[0], width), max(self.extent[1], height))
        if grown != self.extent:
            self.extent = grown
            self.canvas.configure(scrollregion=(0, 0, *grown))

    def reset_extent(self) -> None:
        """Zoom and the file filter may shrink the region (a full draw follows)."""
        self.extent = (0.0, 0.0)

    # -- Glow (§7.9) ---------------------------------------------------------------------------

    def glow(self, changes: Iterable[tuple[GlowKey, float | None]]) -> None:
        """``GlowSet.start``/``tick`` changes: a level is the glow colour's share (1.0 on,
        fade steps below), None removes the glow or ghost."""
        for key, level in changes:
            kind, what = key
            if kind == "edge":
                self._light(what, level)                # type: ignore[arg-type]
            elif kind in ("box", "ghost", "ghost_edge"):
                self._outline_glow(key, level)

    def _light(self, key: EdgeKey, level: float | None) -> None:
        item = self.edges.get(key)
        if level is None:
            self.lit.pop(key, None)
        else:
            self.lit[key] = level
        if item is None or key == self.selected_edge:
            return                                      # a selected arrow keeps its accent
        plain = EDGE_STYLES.get(key[2], ((), LINK_COLOR))[1]
        if level is None:
            self.canvas.itemconfigure(item, fill=plain, width=max(1, round(self.dpi)))
        else:
            self.canvas.itemconfigure(item, fill=blend(GLOW_COLOR, plain, level),
                                      width=max(2, round(2 * self.dpi)))

    def _outline_glow(self, key: GlowKey, level: float | None) -> None:
        canvas = self.canvas
        item = self.glows.get(key)
        if level is None:
            if item is not None:
                canvas.delete(item)
                del self.glows[key]
            return
        kind, what = key
        color = blend(GLOW_COLOR, BOX_OUTLINE, level)
        if item is not None:
            canvas.itemconfigure(item, outline=color) if kind != "ghost_edge" else \
                canvas.itemconfigure(item, fill=color)
            return
        width = max(GLOW_PX, round(GLOW_PX * self.dpi))
        if kind == "box":
            r = self.box_rect(what)                     # type: ignore[arg-type]
            if r is None:
                return
            g = width / 2
            item = canvas.create_rectangle(r[0] - g, r[1] - g, r[2] + g, r[3] + g,
                                           outline=color, width=width)
        elif kind == "ghost":
            spot = self._old.get(what)                  # type: ignore[arg-type]
            if spot is None:
                return
            x0, y0 = self.corner(*spot)
            w, h = self.box_size()
            item = canvas.create_rectangle(x0, y0, x0 + w, y0 + h, outline=color,
                                           width=max(1, round(self.dpi)), dash=DASH)
        else:
            points = self._old_edges.get(what)          # type: ignore[arg-type]
            if not points:
                return
            item = canvas.create_line(*points, fill=color, smooth=True, dash=DASH,
                                      width=max(1, round(self.dpi)))
        self.glows[key] = self.put(item, "glow")

    # -- Preview (§7.10) -----------------------------------------------------------------------

    def clear_preview(self) -> None:
        for item in self.preview_items:
            self.canvas.delete(item)
        self.preview_items = []

    def preview(self, found: Preview, links: Sequence[object], labels: Sequence[object], *,
                pins: Mapping[str, tuple[int, int]], places: Mapping[str, tuple[int, int]],
                file: str | None = None) -> MapLayout | None:
        """Draw ``found`` (``livemap.preview_rows``) over the map: its new boxes placed by a
        dry-run ``relayout`` of ``labels``/``links`` (the card's rows swapped in) on a copy
        of the pins, so nothing real moves. Returns the dry-run layout (Apply seeds the pins
        from it), or None when there is no map."""
        self.clear_preview()
        if self.layout is None:
            return None
        trial, _ = relayout(self.layout, links, labels, pins=dict(pins), places=places,
                            file=file, keep=True)
        canvas, s = self.canvas, self.scale
        line = max(1, round(self.dpi))
        pad = MAP_PAD * s
        drawn: list[int] = []

        def text_at(x: float, y: float, text: str, color: str, anchor: str) -> None:
            drawn.append(canvas.create_text(x, y, anchor=anchor, text=text, fill=color,
                                            font=self.detail_font))

        for name in found.boxes_added:
            j = trial.index_of(name)
            if j is None:
                continue
            x0, y0, x1, y1 = self.rect_of(trial.boxes[j])
            drawn.append(canvas.create_rectangle(x0, y0, x1, y1, outline=PREVIEW_COLOR,
                                                 width=line, dash=DASH, fill=""))
            text_at(x0 + pad, y0 + 4 * s, found.texts.get(name, ""), PREVIEW_COLOR, "nw")
            text_at(x1 - pad, y1 - 4 * s, MARK_PROPOSED, MUTED, "se")
        for name in found.boxes_removed:
            r = self.box_rect(name)
            if r is None:
                continue
            x0, y0, x1, y1 = r
            drawn.append(canvas.create_rectangle(x0, y0, x1, y1, outline=PREVIEW_REMOVE,
                                                 width=line, dash=DASH, fill=""))
            drawn.append(canvas.create_line(x0, (y0 + y1) / 2, x1, (y0 + y1) / 2,
                                            fill=PREVIEW_REMOVE, width=line))
            text_at(x1 - pad, y1 - 4 * s, MARK_REMOVED, MUTED, "se")
        for keys, color, source in ((found.edges_added, PREVIEW_COLOR, trial),
                                    (found.edges_removed, PREVIEW_REMOVE, self.layout)):
            index = source.edge_keys or {}
            for key in keys:
                i = index.get(key)
                if i is None:
                    continue
                drawn.append(canvas.create_line(*self.edge_points(source, i), fill=color,
                                                width=line, dash=DASH, smooth=True,
                                                arrow="last"))
                chip = found.texts.get(key, "")
                if chip:
                    cx, cy = self.corner(*(chip_center(source, i) or (0, 0)))
                    w = self.measure(self.chip_font, chip) + 2 * CHIP_PAD_X * s
                    h = self.chip_font.metrics("linespace") + 2 * CHIP_PAD_Y * s
                    drawn.append(canvas.create_polygon(
                        *round_rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2,
                                    CHIP_RADIUS * s), smooth=True, fill=CHIP_FILL,
                        outline=color, dash=DASH))
                    drawn.append(canvas.create_text(cx, cy, text=chip, fill=CHIP_TEXT,
                                                    font=self.chip_font))
        for item in drawn:
            self.put(item, "preview")
        self.preview_items = drawn
        return trial


__all__ = ["ARROW_SHAPE", "BOX_FILL", "BOX_OUTLINE", "BoxItems", "CHIP_BORDER", "CHIP_FILL",
           "CHIP_FONT_PX", "CHIP_IF", "CHIP_IF_TEXT", "CHIP_PAD_X", "CHIP_PAD_Y",
           "CHIP_RADIUS", "CHIP_TEXT", "EDGE_STYLES", "FULL_REDRAW_OVER", "GLOW_COLOR",
           "GLOW_PX", "LAYERS", "LINES_PER_PAINT", "LINE_SLICE_MS", "MAP_DETAIL_PX",
           "MAP_MARGIN", "MAP_NAME_PX", "MAP_PAD", "MapPainter", "PREVIEW_COLOR",
           "PREVIEW_REMOVE", "elide", "round_rect"]
