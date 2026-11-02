"""``HistoryPage``: the history log, a page of the game menu (F13 ``SPEC.md`` §4, §5;
``07-architecture-review.md`` I-5, I-6).

Why this module exists: the player rereads the lines read so far and the choices picked,
oldest at the top, and replays a voiced line. The record is ``GameState.history``
(``runtime/history.py``); this page only shows it, through ``HistoryPorts`` that
``app/history.py`` builds (``ui`` never imports ``engine.app``).

- **Layout** (§4). One ``ScrollList`` with variable rows fills the body slot (416, 112,
  808×552). Rows are 788 wide (the list minus the 20-unit scrollbar lane). Text size ``s`` is
  ``panel.text_size`` × text scale and pitch ``p`` = round(1.4 s): a row is 12 + (name line +
  text lines) × p + 12 tall, the name at (32, 12) in the bold face and the heading color, the
  text at x 32 wrapped at 696 (788 − 64 − 28 for the voice icon). A choice row has a
  4 × (h − 24) bar at (32, 12) and its text at x 48 wrapped at 680, in the heading color. A
  voiced line shows a drawn 20×20 speaker 32 inside the right edge, on its first line.
  Every glyph band is ``p`` tall and centred. The page opens scrolled to the bottom.
- **Wrapping** is greedy and cheap: F05's per-font ``word_cache`` for word widths, a
  ``render_safe`` pass (controls and lone surrogates draw as U+FFFD), ``\\n`` breaks, and a
  word wider than the line splits between graphemes. The wraps live in the ports'
  ``HistoryWraps``, keyed by (kind, text, font, size), so a reopen wraps only new entries
  and a text-size change re-wraps everything once. Only rows in view are drawn, line by
  line through ``Canvas.draw_text`` (raster in the shared ``text_line`` cache).
- **Input** (UI-F13-02) is the ``ScrollList``'s: wheel 3 × (p + 8), page keys view − p,
  Home/End, tall rows stepped. The newest row is the list's focused row, so entering the
  page by keys focuses it; by mouse nothing is focused until a row is hovered. Activating a
  voiced row calls ``audio.replay_voice(file)``; any other row does nothing.
- **Back.** From the game menu ``back()`` is False (the menu closes the page). Opened from
  the quick menu (``open_from_quick``) Back closes the whole menu. ``closed()`` stops a
  replay (I-5) when F08's ``stop_replay`` exists.
- **Text size** (UI-F13-03): ``build`` again (``PageHost.rebuild``) re-wraps and keeps the
  bottom row in view anchored at the same distance from the view's bottom.

``draw_history_row`` is the row drawing itself, kept free of the page so another list
(F21) can draw the same rows.
"""

import dataclasses
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass, field
from itertools import accumulate, repeat
from operator import add
from typing import TYPE_CHECKING, Any, Final

from engine.core.graphemes import graphemes
from engine.render.text import Face, FontSpec, Synth, text_width
from engine.render.textlayout import WORD_CACHE_ENTRIES, WORD_CACHE_MAX_CHARS, render_safe, \
    word_cache
from engine.ui.focus import Box, FocusGroup
from engine.ui.layouts import cut_to_width, pitch
from engine.ui.menus import EntryContext, MenuEntry, MenuPageBase
from engine.ui.nav import InputKind
from engine.ui.paint import HEADING_AREA, MARKER_INSET, MARKER_SIZE
from engine.ui.widgets import ListRow, Look, ScrollList

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.runtime.history import HistoryEntry
    from engine.ui.menus import PageHost
    from engine.ui.paint import Painter
    from engine.ui.shell import GameShell

HEADING: Final = "history"            # the [words] key of the heading and both entries
ROW_WIDTH: Final = 788                # the list (808) minus the scrollbar lane
PAD: Final = 12                       # row padding, top and bottom
TEXT_X: Final = 32
CHOICE_TEXT_X: Final = 48
ICON: Final = 20                      # the voice icon, 32 inside the right edge
ICON_INSET: Final = 32
TEXT_WIDTH: Final = ROW_WIDTH - 2 * TEXT_X - 28        # 696: the icon lane kept free
CHOICE_WIDTH: Final = TEXT_WIDTH - (CHOICE_TEXT_X - TEXT_X)   # 680
BAR_WIDTH: Final = 4


def slack(words: int) -> float:
    """How much wider than the sum of its word and space widths a line of ``words`` words
    may draw (each width is rounded; measured at most 4 over 20 words), with a margin. A
    line whose sum is closer to the limit than this is measured whole."""
    return 2 + words / 2


# --- Ports ---------------------------------------------------------------------------------------

class HistoryWraps:
    """The wrapped text of the entries last laid out, kept between openings of the page
    (one per launch, in ``HistoryPorts``), for one row style at a time (a text-size change
    starts afresh). ``wraps`` counts the texts and names wrapped so far."""

    def __init__(self) -> None:
        self._store: dict[Hashable, Any] = {}
        self._next: dict[Hashable, Any] | None = None
        self._style: Hashable = None
        self.wraps = 0

    def begin(self, style: Hashable) -> None:
        """Start a pass for ``style`` (the fonts and sizes the wraps were made with)."""
        if style != self._style:
            self._store, self._style = {}, style
        self._next = {}

    def get(self, key: Hashable, make: Callable[[], Any]) -> Any:
        """The value of ``key``, made (and counted) only if the last pass didn't have it."""
        assert self._next is not None, "begin() first"
        found = self._next.get(key)
        if found is None:
            found = self._store.get(key)
            if found is None:
                found = make()
                self.wraps += 1
            self._next[key] = found
        return found

    def end(self) -> None:
        """Keep only what this pass used (at most the 250 entries' texts and names)."""
        assert self._next is not None
        self._store, self._next = self._next, None


@dataclass
class HistoryPorts:
    """What the page reads (built by ``app/history.py``). ``entries`` is the live
    ``interp.history.entries``; ``voice_for(sid)`` the voice file of a line or menu (None
    when it has none or no longer resolves); ``audio`` F08's service (``replay_voice``,
    ``stop_replay``) or None (no icons, no replay)."""

    entries: "Callable[[], Sequence[HistoryEntry]]"
    voice_for: Callable[[str], str | None]
    audio: Any = None
    wraps: HistoryWraps = field(default_factory=HistoryWraps)


# --- Wrapping ------------------------------------------------------------------------------------

def _measure(font: Any, cache: "OrderedDict[str, int]", text: str) -> int:
    """A word's width through F05's per-font cache (as ``textlayout``'s, without the LRU
    touch on a hit: the history wraps a few hundred words per open)."""
    width = cache.get(text)
    if width is not None:
        return width
    width = font.size(text)[0] if text else 0
    if len(text) <= WORD_CACHE_MAX_CHARS:
        cache[text] = width
        if len(cache) > WORD_CACHE_ENTRIES:
            cache.popitem(last=False)
    return width


def _longest_piece(font: Any, parts: list[str], start: int, width: float) -> int:
    """How many graphemes from ``parts[start]`` fit ``width`` (at least one): galloping,
    then a binary search, so a 2,000-character word costs a few measurements per line."""
    n = len(parts) - start

    def fits(k: int) -> bool:
        return text_width(font, "".join(parts[start:start + k])) <= width

    low, probe = 0, 16
    while probe < n and fits(probe):
        low, probe = probe, probe * 2
    high = min(probe, n)
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return max(1, low)


def _split_word(font: Any, word: str, width: float) -> list[str]:
    """``word`` cut between graphemes into pieces no wider than ``width`` (at least one
    grapheme each)."""
    parts = graphemes(word)
    pieces: list[str] = []
    start = 0
    while start < len(parts):
        k = _longest_piece(font, parts, start, width)
        pieces.append("".join(parts[start:start + k]))
        start += k
    return pieces


def wrap_history_text(font: Any, text: str, width: float) -> tuple[str, ...]:
    """``text`` (made ``render_safe``) in lines no wider than ``width``, measured with the
    reference ``font``: greedy at spaces (a space where a line breaks is dropped), ``\\n`` a
    hard break (an empty paragraph is an empty line), a word wider than ``width`` split
    between graphemes. Word widths come from F05's ``word_cache``, and a line's width is
    their sum with the spaces; a line whose sum is within ``slack`` of the limit is measured
    whole. Kerning makes a line narrower than its sum, so a break may come a few units
    early, never late."""
    cache = word_cache(font)
    space = _measure(font, cache, " ")
    lines: list[str] = []
    for paragraph in render_safe(text).split("\n"):
        _wrap_paragraph(font, cache, space, paragraph, width, lines)
    return tuple(lines)


def _wrap_paragraph(font: Any, cache: "OrderedDict[str, int]", space: int, paragraph: str,
                    width: float, lines: list[str]) -> None:
    """One paragraph's lines onto ``lines``. Each break is a binary search over the words'
    running widths, so the cost is about one cache look-up per word."""
    words = paragraph.split(" ")
    get = cache.get
    widths = [get(word) or _measure(font, cache, word) for word in words]
    ends = list(accumulate(map(add, widths, repeat(space))))   # words 0..j, a space each
    n = len(words)
    if ends[-1] - space + slack(n) <= width:
        lines.append(paragraph)                           # one line: no search
        return
    if max(widths) > width:
        _wrap_long_words(font, space, words, widths, width, lines)
        return
    limit = space + width
    i = 0
    while i < n:
        base = ends[i - 1] if i else 0
        j = max(i, bisect_right(ends, base + limit, i) - 1)   # the last word the sum fits
        while j > i and ends[j] - base - space + slack(j - i + 1) > width \
                and text_width(font, " ".join(words[i:j + 1])) > width:
            j -= 1                                        # a close call, measured whole
        lines.append(" ".join(words[i:j + 1]))
        i = j + 1


def _wrap_long_words(font: Any, space: int, words: list[str], widths: list[int],
                     width: float, lines: list[str]) -> None:
    """A paragraph with a word wider than the line, word by word: a wide word splits
    between graphemes and its last piece starts the next line."""
    line: list[str] = []
    x = 0.0
    for word, w in zip(words, widths):
        if line:
            nx = x + space + w
            if nx + slack(len(line) + 1) <= width or (nx <= width and text_width(
                    font, " ".join(line) + " " + word) <= width):
                line.append(word)
                x = nx
                continue
            lines.append(" ".join(line))
            line, x = [], 0.0
        if w <= width:
            line, x = [word], float(w)
            continue
        pieces = _split_word(font, word, width)
        lines.extend(pieces[:-1])
        line, x = [pieces[-1]], float(text_width(font, pieces[-1]))
    lines.append(" ".join(line))


# --- Rows ----------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class HistoryRow:
    """One laid-out entry: ``name`` already fitted ("" none), the wrapped ``lines``, the
    voice file (None: no icon), and the height in canvas units."""

    kind: str
    name: str
    lines: tuple[str, ...]
    voice: str | None
    height: float


@dataclass(frozen=True)
class RowStyle:
    """The fonts, colors, and pitch the rows draw with (resolved once per layout)."""

    text_font: FontSpec
    name_font: FontSpec
    text_color: tuple[int, int, int]
    name_color: tuple[int, int, int]
    mark_color: tuple[int, int, int]
    pitch: int

    @staticmethod
    def of(p: "Painter") -> "RowStyle":
        """F10's tokens at the painter's text scale: ``panel`` text, the ``panel.heading``
        color and bold face at the text size, and ``button.marker.fill_color``."""
        panel = p.style("panel")
        heading = p.style(HEADING_AREA)
        size = p.scaled_size(panel.font.size)
        return RowStyle(dataclasses.replace(panel.font, size=size),
                        dataclasses.replace(heading.font, size=size),
                        tuple(panel.text_color), tuple(heading.text_color),  # type: ignore
                        tuple(panel.marker_color), pitch(size))              # type: ignore


def _font(assets: Any, spec: FontSpec) -> Any:
    """The reference font of ``spec`` (as ``Canvas.font_handle``)."""
    if spec.bundled is Face.REGULAR and spec.synth is Synth.NONE:
        return assets.font(spec.ref, spec.size).font
    return assets.font(spec.ref, spec.size, bundled=spec.bundled, synth=spec.synth).font


def layout_rows(entries: "Sequence[HistoryEntry]", style: RowStyle, assets: Any,
                wraps: HistoryWraps, voice_of: Callable[[str], str | None] | None
                ) -> list[HistoryRow]:
    """Every entry as a ``HistoryRow``; texts and names come from ``wraps`` when the last
    pass had them. ``voice_of`` None: no voice icons (no audio)."""
    text_font = _font(assets, style.text_font)
    name_font = _font(assets, style.name_font)
    p = style.pitch
    rows: list[HistoryRow] = []
    wraps.begin((style.text_font, style.name_font))
    try:
        for entry in entries:
            choice = entry.kind == "choice"
            width = CHOICE_WIDTH if choice else TEXT_WIDTH
            text = entry.text
            lines = wraps.get((entry.kind, text),
                              lambda: wrap_history_text(text_font, text, width))
            name = ""
            if not choice and entry.name:
                raw = entry.name
                name = wraps.get(("name", raw), lambda: cut_to_width(
                    render_safe(raw), TEXT_WIDTH, 0,
                    lambda part, _size: text_width(name_font, part)))
            voice = None
            if not choice and voice_of is not None:
                voice = voice_of(entry.sid)
            bands = len(lines) + (1 if name else 0)
            rows.append(HistoryRow(entry.kind, name, lines, voice, 2 * PAD + bands * p))
    finally:
        wraps.end()
    return rows


def draw_speaker(p: "Painter", box: Box, color: tuple[int, int, int]) -> None:
    """The voice icon in ``box`` (20×20): a body, a cone, and one wave, all drawn."""
    x, y = box.x, box.y
    p.rect(Box(x + 1, y + 7, 5, 6), color)
    p.triangle(Box(x + 3, y + 2, 9, 16), color, direction="left")
    p.rect(Box(x + 15, y + 5, 2, 10), color)


def draw_history_row(p: "Painter", row: HistoryRow, box: Box, look: Look,
                     style: RowStyle) -> None:
    """One row's contents over the list's frame and divider: the focus marker (focused or
    pressed) on the first line, then the name, text, choice bar, and voice icon."""
    canvas = p.canvas
    pt = style.pitch
    top = box.y + PAD
    if look.state in ("focused", "pressed"):
        mw, mh = MARKER_SIZE
        p.triangle(Box(box.x + MARKER_INSET, top + (pt - mh) / 2, mw, mh),
                   p.style("list", look.state).marker_color)
    if row.kind == "choice":
        p.rect(Box(box.x + TEXT_X, top, BAR_WIDTH, box.h - 2 * PAD), style.mark_color)
        x, color, band = box.x + CHOICE_TEXT_X, style.name_color, 0
    else:
        x, color, band = box.x + TEXT_X, style.text_color, 0
        if row.name:
            canvas.draw_text(row.name, style.name_font, style.name_color,
                             (x, top + pt / 2), anchor="midleft")
            band = 1
        if row.voice is not None:
            draw_speaker(p, Box(box.right - ICON_INSET - ICON, top + (pt - ICON) / 2, ICON,
                                ICON), style.mark_color)
    for index, line in enumerate(row.lines):
        if line:
            canvas.draw_text(line, style.text_font, color,
                             (x, top + (band + index) * pt + pt / 2), anchor="midleft")


# --- The page ------------------------------------------------------------------------------------

class HistoryPage(MenuPageBase):
    """The ``history`` page (``MenuPage``). ``close_menu_on_back``: opened from the quick
    menu, so Back closes the whole menu."""

    heading = HEADING

    def __init__(self, host: "PageHost", ports: HistoryPorts, *,
                 close_menu_on_back: bool = False) -> None:
        self.host = host
        self.ports = ports
        self.close_menu_on_back = close_menu_on_back
        self.rows: list[HistoryRow] = []
        self.style: RowStyle | None = None
        self._entries: object = None
        self._list_rows: list[ListRow] = []
        self.list = ScrollList(lambda: self._list_rows, self._activate,
                               heights=lambda i: self.rows[i].height,
                               pitch=lambda: self.style.pitch if self.style else 1.0,
                               draw_row=self._draw_row, enabled=lambda: bool(self.rows),
                               empty=lambda: host.shell.words.get("list_empty"))
        self._built = False

    # -- MenuPage --

    def build(self, host: "PageHost", body: Box) -> list[FocusGroup]:
        self.host = host
        self.list.box = body
        self._layout(host.painter, first=not self._built)
        self._built = True
        return [FocusGroup([self.list], column=True)]

    def update(self, dt: float) -> None:
        entries = self.ports.entries()
        if entries is not self._entries and self.style is not None:
            self._layout(self.host.painter, first=False)  # a new entry (story held: rare)

    def draw(self, canvas: "Canvas", p: "Painter") -> None:
        pass                                              # the list is a scope widget

    def back(self) -> bool:
        if self.close_menu_on_back:
            self.host.close_menu()
            return True
        return False

    def closed(self) -> None:
        stop = getattr(self.ports.audio, "stop_replay", None)
        if stop is not None:
            stop()                                        # I-5: leaving stops a replay

    # -- layout --

    def _layout(self, p: "Painter", *, first: bool) -> None:
        lst = self.list
        anchor: tuple[int, float] | None = None          # (row, its bottom below the view's)
        if not first and self.rows:
            shown = lst.visible_range()
            if len(shown):
                last = shown[-1]
                anchor = (last, lst.row_box(last).bottom - lst.box.bottom)
        entries = self.ports.entries()
        self._entries = entries
        audio = self.ports.audio
        self.style = RowStyle.of(p)
        self.rows = layout_rows(entries, self.style, self.host.shell.assets,
                                self.ports.wraps,
                                self.ports.voice_for if audio is not None else None)
        n = len(self.rows)
        if len(self._list_rows) != n:
            self._list_rows = [ListRow("")] * n
        lst.heights_changed()
        if first or anchor is None:
            lst.focus_row = max(0, n - 1)                 # newest row; opened at the bottom
            lst.scroll = lst.max_scroll()
            return
        index, below = anchor
        lst.scroll = 0.0
        if 0 <= (index := min(index, n - 1)):
            bottom = lst.row_box(index).bottom - lst.box.y      # in content units
            lst.scroll = bottom - below - lst.box.h
        lst.scroll = min(lst.max_scroll(), max(0.0, lst.scroll))

    # -- rows --

    def _draw_row(self, p: "Painter", index: int, box: Box, look: Look) -> None:
        assert self.style is not None
        draw_history_row(p, self.rows[index], box, look, self.style)

    def _activate(self, index: int) -> None:
        voice = self.rows[index].voice if 0 <= index < len(self.rows) else None
        audio = self.ports.audio
        if voice is not None and audio is not None:
            audio.replay_voice(voice)


# --- Entries ------------------------------------------------------------------------------------

def open_from_quick(shell: "GameShell", by: InputKind) -> None:
    """The quick menu's History: the game menu opens on the page, and Back from it closes
    the whole menu. By keys the newest row is focused."""
    if shell.game_menu() is not None:
        return                                            # a menu is open: nothing more
    shell.open_game_menu(by)
    menu = shell.game_menu()
    if menu is None:
        return                                            # not in game, or another menu
    if not any(e.id == HEADING and e.page is not None for e in menu.entries):
        return                                            # hidden from the game menu (F32)
    menu.open_page(HEADING)
    page = menu.page
    if isinstance(page, HistoryPage):
        page.close_menu_on_back = True
        if by is InputKind.KEYS and menu.scope.can_focus(page.list):
            menu.scope.focus(page.list, by, sound=False)


def register_history(shell: "GameShell", ports: HistoryPorts) -> None:
    """``game``: the History page; ``quick``: History, opening the game menu on it. No
    title entry (PR-F13-05)."""
    shell.menus.add("game", MenuEntry(HEADING, page=lambda host: HistoryPage(host, ports)))
    shell.menus.add("quick", MenuEntry(HEADING, action=lambda ctx: _quick(ctx)))


def _quick(ctx: EntryContext) -> None:
    open_from_quick(ctx.shell, ctx.by)


__all__ = ["CHOICE_WIDTH", "HistoryPage", "HistoryPorts", "HistoryRow", "HistoryWraps",
           "RowStyle", "TEXT_WIDTH", "draw_history_row", "layout_rows", "open_from_quick",
           "register_history", "wrap_history_text"]
