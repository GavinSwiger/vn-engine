"""Line layout for the textbox: faces, word wrap, line metrics, pages, glyph positions, and the
typing timeline (F05 ``04-technical.md`` §7.4, §7.6; ``03-ui.md`` UI-F05-02, 03).

Why this module exists: a line's breaks and pages must be fixed before typing starts and must
never depend on the window (ADR-0001), so layout measures with *reference* fonts (pixel size =
canvas size) through a font-metrics object (``LayoutContext.assets``: the ``AssetManager``, or
the M20 fake in tests) and works in canvas units relative to the text area's top-left.

Steps (§7.4):

1. **Flatten** spans into graphemes, each with its face, size ``round(text_size × size)``,
   color, and speed; ``\\n`` is a hard break; marks stay in order. ``render_safe`` turns
   controls and lone surrogates into U+FFFD.
2. **Waits** (SR-F05-13): a ``{pause}`` with no grapheme after it is dropped; of ``{pause}``s
   with no grapheme between them only the first is kept.
3. **Words**: runs of non-space graphemes, possibly crossing styles, measured per font piece
   with ``font.size(text)[0]`` and a per-font LRU word cache.
4. **Lines** (greedy): a word goes on the line if ``x + width ≤ W``; else the line breaks (if
   it has content) and the word starts the next one; a word wider than W splits after the
   last grapheme that fits (at least one). Spaces where a line breaks *hang* (kept on the
   ending line, not drawn, not counted toward W); spaces at the start of the text or after
   ``\\n`` are kept.
5. **Metrics**: ``pitch = round(1.4 × largest size on the line)`` (the base size when the line
   is empty); one baseline from the largest font on the line.
6. **Pages**: lines fill a page while their pitches fit in ``height``; one line always fits.
   Empty lines never start a page after the first (they would show an empty page). A page
   break goes before the first grapheme of the next page; a ``{pause}`` with nothing shown
   between it and the page break merges into it.
7. **Timeline** per page for the typewriter: ``GlyphSlot`` (spaces included),
   ``PauseSlot``, ``WAIT``, ``PAGE_BREAK``, ``END``.

Laziness: the constructor flattens only (no measuring). ``timeline(k)`` breaks pages up to
``k``; ``page(k)`` also computes glyph positions (prefix widths), for that page only, so the
arrival frame lays out page 0 alone. ``count_pages`` and ``all_pages`` never compute
positions. Breaks never depend on when or in which order pages are laid out.

F29 (``04`` §4): a grapheme's ``Style.effect`` rides along to ``PlacedGlyph.effect`` for the
draw pass and changes nothing here: runs are grouped by font, not by look, so a line with and
without effects breaks, places, and times alike (TR-F29-02).
"""

import re
import weakref
from collections import OrderedDict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, NamedTuple, Protocol

from engine.core.graphemes import iter_graphemes
from engine.render.assets import Face, Synth
from engine.render.typewriter import (
    END,
    PAGE_BREAK,
    WAIT,
    GlyphSlot,
    PauseSlot,
    Slot,
)
from engine.runtime.commands import PauseMark, Span, Style, TaggedText, TextEffect, WaitMark

LINE_PITCH: Final = 1.4                  # × the largest size on the line (UI-F05-02)
WORD_CACHE_ENTRIES: Final = 8192         # words per font (§7.4 step 3, checklist 3)
WORD_CACHE_MAX_CHARS: Final = 256        # longer pieces are measured but not cached
REPLACEMENT: Final = "�"

# C0 and C1 controls except "\n", and lone surrogates: SDL_ttf rejects them (§7.4 step 1).
_UNSAFE = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f\ud800-\udfff]")
# Space separators (Zs) a line may break at; the no-break spaces U+00A0, U+2007, U+202F
# are left out and stay inside words.
_BREAK_SPACES = frozenset("           "
                          "  　")


def render_safe(text: str) -> str:
    """``text`` with every control (not ``\\n``) and lone surrogate replaced by U+FFFD."""
    return _UNSAFE.sub(REPLACEMENT, text)


def is_break_space(grapheme: str) -> bool:
    """Whether a grapheme is a space a line may break at (and hang). F43 refines this."""
    return grapheme in _BREAK_SPACES


# --- Faces (§5.3, §7.6) -------------------------------------------------------------------------

def face_for(bold: bool, italic: bool) -> Face:
    if bold:
        return Face.BOLD_ITALIC if italic else Face.BOLD
    return Face.ITALIC if italic else Face.REGULAR


@dataclass(frozen=True)
class FaceSource:
    """Where one style's font comes from: an author ref (None = bundled), the bundled face
    used for it and as its fallback, and the style pygame synthesizes (author fonts only)."""

    ref: str | None
    bundled: Face
    synth: Synth = Synth.NONE


@dataclass(frozen=True)
class FaceSet:
    """The four faces of the textbox, resolved once per launch by ``install_textbox``."""

    faces: Mapping[Face, FaceSource]

    def for_style(self, bold: bool, italic: bool) -> FaceSource:
        return self.faces[face_for(bold, italic)]


BUNDLED_FACES: Final = FaceSet({face: FaceSource(None, face) for face in Face})


# --- Context and output -------------------------------------------------------------------------

class Font(Protocol):
    """The reference font metrics layout uses (``pygame.font.Font`` or a fake)."""

    def size(self, text: str) -> tuple[int, int]: ...

    def get_ascent(self) -> int: ...

    def get_descent(self) -> int: ...      # pygame's is negative; the sign is ignored


@dataclass(frozen=True)
class LayoutContext:
    """``assets.font(ref, size_px, *, bundled=, synth=)`` must return a handle with a
    ``.font`` (``AssetManager``). ``width``/``height`` are the text area's, in canvas units
    (920 and H − top − bottom padding); ``base_color`` colors spans with no color.
    ``name`` (F30 ``04`` §6.4): the player's name drawn for each ``{username}`` span
    (``style.username``), literally; None draws the span's own text (the fallback word). Only
    the textbox and NVL page pass one."""

    assets: Any
    faces: FaceSet
    text_size: int
    base_color: str
    width: float
    height: float
    name: str | None = None


@dataclass(frozen=True, slots=True)
class PlacedGlyph:
    """One grapheme in canvas units relative to the text area's left edge. ``hangs``: a space
    where the line breaks, kept for timing but not drawn. ``effect`` (F29): its span's motion,
    read only by the draw pass."""

    index: int
    text: str
    x: float
    advance: float
    face: FaceSource
    size: int
    color: str
    hangs: bool = False
    effect: TextEffect | None = None

    @property
    def right(self) -> float:
        return self.x + self.advance


@dataclass(frozen=True, slots=True)
class LaidLine:
    """One line: ``top`` and ``baseline`` relative to the text area's top; ``glyphs`` in
    order (``first_glyph`` .. ``end_glyph`` − 1)."""

    top: float
    pitch: int
    baseline: float
    first_glyph: int
    end_glyph: int
    glyphs: tuple[PlacedGlyph, ...]


@dataclass(frozen=True, slots=True)
class Page:
    index: int
    lines: tuple[LaidLine, ...]
    slots: tuple[Slot, ...]
    first_glyph: int
    end_glyph: int
    last: bool


# --- Word-width cache (§7.4 step 3) -------------------------------------------------------------

# Per font object, so a font reloaded or evicted from the asset cache starts afresh.
_word_widths: "weakref.WeakKeyDictionary[Any, OrderedDict[str, int]]" = \
    weakref.WeakKeyDictionary()


def word_cache(font: Font) -> "OrderedDict[str, int]":
    cache = _word_widths.get(font)
    if cache is None:
        cache = _word_widths[font] = OrderedDict()
    return cache


def clear_word_cache() -> None:
    _word_widths.clear()


def _measure(font: Font, cache: "OrderedDict[str, int]", text: str) -> int:
    width = cache.get(text)
    if width is not None:
        cache.move_to_end(text)
        return width
    width = font.size(text)[0]
    if len(text) <= WORD_CACHE_MAX_CHARS:
        cache[text] = width
        if len(cache) > WORD_CACHE_ENTRIES:
            cache.popitem(last=False)
    return width


# --- Layout -------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Look:
    """The layout-relevant style of a grapheme."""

    font: int                    # index into LineLayout._fonts
    face: FaceSource
    size: int
    color: str
    speed: float
    effect: TextEffect | None = None     # F29: carried to PlacedGlyph, never grouped by


class _Line(NamedTuple):
    start: int                   # first grapheme
    content_end: int             # graphemes from here to ``end`` hang
    end: int
    pitch: int
    font: int                    # the line's largest font (baseline)


class _PageRange(NamedTuple):
    lines: tuple[_Line, ...]
    first: int
    end: int
    last: bool


class LineLayout:
    """The layout of one resolved body (no ``VarMark``) in ``ctx``."""

    def __init__(self, body: TaggedText, ctx: LayoutContext) -> None:
        self.ctx = ctx
        self.has_name = False                        # F30: a flagged span drew ``ctx.name``
        self._fonts: list[Font] = []
        self._caches: list[OrderedDict[str, int]] = []
        self._font_index: dict[tuple[FaceSource, int], int] = {}
        self._chars: list[str] = []
        self._looks: list[_Look] = []
        self._space: list[bool] = []
        self._marks: dict[int, list[Slot]] = {}      # marks before grapheme i
        self._breaks: dict[int, int] = {}            # hard breaks before grapheme i
        self._flatten(body)
        self._drop_waits()
        self._base_font = self._font(ctx.faces.for_style(False, False), ctx.text_size)
        self._line_iter: Iterator[_Line] = self._lines()
        self._pending: _Line | None = None
        self._exhausted = False
        self._ranges: list[_PageRange] = []
        self._timelines: dict[int, tuple[Slot, ...]] = {}
        self._pages: dict[int, Page] = {}

    # -- public --

    @property
    def glyph_count(self) -> int:
        """Graphemes in the line (spaces included, ``\\n`` not): the timeline's glyphs."""
        return len(self._chars)

    @property
    def laid_out(self) -> int:
        """Pages broken so far (one page per frame, PR-F05-27)."""
        return len(self._ranges)

    def page(self, k: int) -> Page:
        """Page ``k`` with glyph positions; breaks pages up to ``k``. IndexError past the
        last page."""
        page = self._pages.get(k)
        if page is None:
            page = self._pages[k] = self._place(k)
        return page

    def timeline(self, k: int) -> tuple[Slot, ...]:
        """Page ``k``'s typing slots (no positions computed)."""
        slots = self._timelines.get(k)
        if slots is None:
            slots = self._timelines[k] = self._slots(k)
        return slots

    def all_pages(self) -> int:
        """The number of pages (breaks every page; no positions)."""
        while self._break_next():
            pass
        return len(self._ranges)

    def is_last(self, k: int) -> bool:
        return self._range(k).last

    def page_height(self, k: int) -> int:
        """F17 (07 A4): page ``k``'s height, the sum of its lines' pitches; breaks pages up
        to ``k`` and computes no positions. IndexError past the last page."""
        return sum(line.pitch for line in self._range(k).lines)

    # -- step 1, 2: flatten, waits --

    def _font(self, face: FaceSource, size: int) -> int:
        key = (face, size)
        index = self._font_index.get(key)
        if index is None:
            handle = self.ctx.assets.font(face.ref, size, bundled=face.bundled,
                                          synth=face.synth)
            index = self._font_index[key] = len(self._fonts)
            self._fonts.append(handle.font)
            self._caches.append(word_cache(handle.font))
        return index

    def _look(self, style: Style) -> _Look:
        ctx = self.ctx
        face = ctx.faces.for_style(style.bold, style.italic)
        size = max(1, round(ctx.text_size * style.size))
        return _Look(self._font(face, size), face, size, style.color or ctx.base_color,
                     style.speed, style.effect)

    def _flatten(self, body: TaggedText) -> None:
        chars, looks, space = self._chars, self._looks, self._space
        known: dict[Style, _Look] = {}
        name = self.ctx.name
        for piece in body.pieces:
            if isinstance(piece, Span):
                look = known.get(piece.style)
                if look is None:
                    look = known[piece.style] = self._look(piece.style)
                text = piece.text
                if name is not None and piece.style.username:   # F30: literal, after tags
                    text = name
                    self.has_name = True
                for grapheme in iter_graphemes(render_safe(text)):
                    if grapheme == "\n":
                        at = len(chars)
                        self._breaks[at] = self._breaks.get(at, 0) + 1
                    else:
                        chars.append(grapheme)
                        looks.append(look)
                        space.append(is_break_space(grapheme))
            elif isinstance(piece, PauseMark):
                self._marks.setdefault(len(chars), []).append(PauseSlot(piece.seconds))
            elif isinstance(piece, WaitMark):
                self._marks.setdefault(len(chars), []).append(WAIT)
            else:                                    # §12: a programmer error
                raise AssertionError(f"layout got an unresolved {piece!r}")

    def _drop_waits(self) -> None:
        """SR-F05-13 (§7.4 step 2)."""
        end = len(self._chars)
        for at, marks in self._marks.items():
            kept: list[Slot] = []
            waited = False
            for mark in marks:
                if mark is WAIT:
                    if waited or at == end:
                        continue
                    waited = True
                kept.append(mark)
            self._marks[at] = kept

    # -- step 3, 4, 5: words, lines, metrics --

    def _width(self, a: int, b: int) -> int:
        """Width of graphemes ``a``..``b`` − 1: the sum of their font pieces' widths."""
        looks, chars = self._looks, self._chars
        total = 0
        while a < b:
            font = looks[a].font
            e = a + 1
            while e < b and looks[e].font == font:
                e += 1
            total += _measure(self._fonts[font], self._caches[font], "".join(chars[a:e]))
            a = e
        return total

    def _fit(self, a: int, b: int, limit: float) -> int:
        """The most graphemes from ``a`` (at least 1, at most ``b − a``) whose width fits."""
        low, probe = 1, 16
        while a + probe < b and self._width(a, a + probe) <= limit:
            low, probe = probe, probe * 2
        high = min(probe, b - a)
        while low < high:
            mid = (low + high + 1) // 2
            if self._width(a, a + mid) <= limit:
                low = mid
            else:
                high = mid - 1
        return low

    def _make_line(self, start: int, content_end: int, end: int) -> _Line:
        looks = self._looks
        if start == end:
            return _Line(start, start, end, round(LINE_PITCH * self.ctx.text_size),
                         self._base_font)
        big = looks[start]
        for i in range(start + 1, end):
            if looks[i].size > big.size:
                big = looks[i]
        return _Line(start, content_end, end, round(LINE_PITCH * big.size), big.font)

    def _lines(self) -> Iterator[_Line]:
        """Greedy line breaking (§7.4 step 4), one line at a time."""
        chars, space, breaks = self._chars, self._space, self._breaks
        limit = self.ctx.width
        n = len(chars)
        i = start = 0
        x = 0
        content_end = -1                         # -1: no word on the line yet
        while True:
            for _ in range(breaks.get(i, 0)):    # hard breaks before grapheme i
                yield self._make_line(start, i if content_end < 0 else content_end, i)
                start, x, content_end = i, 0, -1
            if i == n:
                break
            j = i + 1
            if space[i]:
                while j < n and space[j] and j not in breaks:
                    j += 1
                x += self._width(i, j)
                i = j
                continue
            while j < n and not space[j] and j not in breaks:
                j += 1
            width = self._width(i, j)
            if x + width <= limit:
                x += width
                i = content_end = j
                continue
            if i > start:                        # the line has content: break before the word
                yield self._make_line(start, i if content_end < 0 else content_end, i)
                start, x, content_end = i, 0, -1
                if width <= limit:
                    x = width
                    i = content_end = j
                    continue
            while j - i > 0:                     # a word wider than W: split it
                k = self._fit(i, j, limit)
                if i + k == j:
                    x = self._width(i, j)
                    i = content_end = j
                    break
                yield self._make_line(start, i + k, i + k)
                i = start = i + k
                x, content_end = 0, -1
        yield self._make_line(start, n if content_end < 0 else content_end, n)

    def _next_line(self) -> _Line | None:
        if self._pending is not None:
            line, self._pending = self._pending, None
            return line
        if self._exhausted:
            return None
        line = next(self._line_iter, None)
        if line is None:
            self._exhausted = True
        return line

    # -- step 6: pages --

    def _break_next(self) -> bool:
        """Break the next page; False when every page is broken."""
        if self._ranges and self._ranges[-1].last:
            return False
        first_page = not self._ranges
        lines: list[_Line] = []
        used = 0
        while True:
            line = self._next_line()
            if line is None:
                break
            if not lines and not first_page and line.start == line.end:
                continue                         # empty lines never start a later page
            if lines and used + line.pitch > self.ctx.height:
                self._pending = line
                break
            lines.append(line)
            used += line.pitch
        while True:                              # is anything left to show?
            line = self._next_line()
            if line is None or line.start != line.end:
                self._pending = line
                break
        last = self._pending is None
        self._ranges.append(_PageRange(tuple(lines), lines[0].start, lines[-1].end, last))
        return True

    def _range(self, k: int) -> _PageRange:
        if k < 0:
            raise IndexError(k)
        while len(self._ranges) <= k:
            if not self._break_next():
                raise IndexError(f"page {k} of a {len(self._ranges)}-page line")
        return self._ranges[k]

    # -- step 7: timeline --

    def _slots(self, k: int) -> tuple[Slot, ...]:
        page = self._range(k)
        marks, chars, looks = self._marks, self._chars, self._looks
        slots: list[Slot] = []
        if k == 0:
            slots.extend(marks.get(page.first, ()))
        for i in range(page.first, page.end):
            slots.append(GlyphSlot(i, chars[i], looks[i].speed))
            slots.extend(marks.get(i + 1, ()))
        if page.last:
            slots.append(END)
            return tuple(slots)
        cut = len(slots)                         # a {pause} right before a page break merges
        while cut and type(slots[cut - 1]) is not GlyphSlot:
            cut -= 1
        slots[cut:] = [slot for slot in slots[cut:] if slot is not WAIT]
        slots.append(PAGE_BREAK)
        return tuple(slots)

    # -- positions (page drawn only) --

    def _place(self, k: int) -> Page:
        page = self._range(k)
        laid: list[LaidLine] = []
        top = 0
        for line in page.lines:
            font = self._fonts[line.font]
            ascent, descent = font.get_ascent(), abs(font.get_descent())
            baseline = top + (line.pitch - (ascent + descent)) / 2 + ascent
            laid.append(LaidLine(top, line.pitch, baseline, line.start, line.end,
                                 self._place_line(line)))
            top += line.pitch
        return Page(k, tuple(laid), self.timeline(k), page.first, page.end, page.last)

    def _place_line(self, line: _Line) -> tuple[PlacedGlyph, ...]:
        """Glyph x from prefix widths within each word/space run's font pieces, on the same
        pen as breaking measured (so positions never move a break)."""
        chars, looks, space = self._chars, self._looks, self._space
        glyphs: list[PlacedGlyph] = []
        pen = 0
        a, end = line.start, line.end
        while a < end:
            b = a + 1
            while b < end and looks[b].font == looks[a].font and space[b] == space[a]:
                b += 1
            look = looks[a]
            font = self._fonts[look.font]
            text = "".join(chars[a:b])
            width = _measure(font, self._caches[look.font], text)
            offset = 0
            cut = 0                              # code points of text up to grapheme i
            for i in range(a, b):
                cut += len(chars[i])
                right = width if i == b - 1 else font.size(text[:cut])[0]
                own = looks[i]                   # a run shares a font, not a color/effect
                glyphs.append(PlacedGlyph(i, chars[i], pen + offset, right - offset,
                                          look.face, look.size, own.color,
                                          i >= line.content_end, own.effect))
                offset = right
            pen += width
            a = b
        return tuple(glyphs)


def count_pages(body: TaggedText, ctx: LayoutContext) -> int:
    """The page count of ``body``, by the same breaking code as ``LineLayout`` without glyph
    positions (W40, TR-F05-01)."""
    return LineLayout(body, ctx).all_pages()


__all__ = ["BUNDLED_FACES", "LINE_PITCH", "REPLACEMENT", "WORD_CACHE_ENTRIES", "FaceSet",
           "FaceSource", "Font", "LaidLine", "LayoutContext", "LineLayout", "Page",
           "PlacedGlyph", "clear_word_cache", "count_pages", "face_for", "is_break_space",
           "render_safe", "word_cache"]
