"""Per-character font fallback: one font object made of several (F43 ``04`` §7.4; PR-F43-13).

Why this module exists: a theme font made for English has no Japanese, and pygame draws a
character its font lacks as an empty box. ``ChainFont`` wraps a list of pygame fonts, each
with the ``Coverage`` of its file (``core/fontcmap``; None = "covers everything"), and draws
each grapheme with the first font that has it. It offers the ``pygame.font.Font`` methods the
engine and the minigame API call (review I-14; a grep test keeps that true), so
``AssetManager.font`` can hand one out wherever a plain font went before (W2). A font
created from ``FontSpec.fixed`` (error screen, dev overlay; ADR-0004) is never chained.

The rules:

- The text is split into graphemes (``core/graphemes``: combining marks, ZWJ sequences,
  variation selectors, emoji modifiers and flags stay with their base). A grapheme goes to
  the first font whose coverage has all of it (``Coverage.covers`` ignores ZWJ, ZWNJ and
  variation selectors); failing that, the first font with its base character; failing that,
  the **last** font (the bundled Noto Sans face in W2's chains), which draws its box.
- Neighbouring graphemes on the same font form a **run**. ``size`` sums the runs' widths with
  the primary's height; ``render`` draws each run with its own font and places them side by
  side on the primary's baseline, on a surface the primary's height (a fallback glyph taller
  than the primary's ascent clips, 04 §17). Kerning across a run boundary is lost (F05 R1).
- One run (all ASCII with a primary that has printable ASCII, or any text one font covers)
  is the primary's (or that font's) own ``size``/``render``/``metrics`` result, unchanged.
- Fallbacks may be **loaders**: a zero-argument callable giving ``(font, coverage)`` (or None
  for an unusable font, skipped from then on). A loader runs the first time a grapheme gets
  past every font before it, so another language's font file is read only when a character
  needs it. The memo of grapheme → font is bounded (``MEMO_ENTRIES``, oldest out first).
- Style setters (``bold``, ``italic``, ``set_point_size``, …) apply to every font of the
  chain, including ones loaded later; getters read the primary. The fonts are the caller's:
  W2 gives a styled chain font objects of its own, as ``AssetManager`` does for ``synth``.

Memory: the chain holds font objects and coverages, never file bytes. W2 keeps each file's
coverage once per file (shared across sizes), next to the file's single cache entry.
"""

import unicodedata
from collections.abc import Callable, Sequence
from typing import Final, TypeAlias

import pygame

from engine.core.fontcmap import Coverage
from engine.core.graphemes import iter_graphemes

MEMO_ENTRIES: Final = 8192           # characters, and graphemes, remembered per chain (04 §7.4)

_ASCII_PRINTABLE: Final = range(0x20, 0x7F)

Link: TypeAlias = "tuple[pygame.font.Font, Coverage | None]"
Loader: TypeAlias = "Callable[[], tuple[pygame.font.Font, Coverage | None] | None]"
_UNLOADED: Final = object()          # a loader not yet run
_UNUSABLE: Final = object()          # a loader that gave None
_JOINS: Final = -1                   # a character that may join a cluster (graphemes path)
_MARKS: Final = ("Mn", "Me", "Mc")


def _joins(char: str) -> bool:
    """Whether ``char`` may join the grapheme before or after it (``core/graphemes``'s
    extenders, regional indicators, Hangul jamo): a superset, so the fast path stays exact."""
    code = ord(char)
    if code < 0x0300:
        return False
    return (code == 0x200D                      # ZWJ
            or 0xFE00 <= code <= 0xFE0F         # variation selectors
            or 0x1F3FB <= code <= 0x1F3FF       # emoji modifiers
            or 0xE0020 <= code <= 0xE007F       # tag characters
            or 0x1F1E6 <= code <= 0x1F1FF       # regional indicators
            or 0x1100 <= code <= 0x11FF         # Hangul jamo
            or 0xA960 <= code <= 0xA97C or 0xD7B0 <= code <= 0xD7FB
            or unicodedata.category(char) in _MARKS)


def _shared(attribute: str) -> property:
    """A style property read from the primary and set on every font of the chain."""
    def get(self: "ChainFont"):
        return getattr(self._fonts[0], attribute)

    def set_(self: "ChainFont", value) -> None:
        self._set_all(attribute, lambda font: setattr(font, attribute, value))
    return property(get, set_, doc=f"The primary's ``{attribute}``; setting it sets every "
                                   "font of the chain.")


class ChainFont:
    """A ``pygame.font.Font`` look-alike drawing each grapheme with the first font that has
    it. ``links[0]`` is the primary ``(font, coverage)`` (its metrics are the chain's); each
    later link is a ``(font, coverage)`` pair or a ``Loader``."""

    __slots__ = ("_fonts", "_coverages", "_loaders", "_memo", "_chars", "_ascii_primary",
                 "_styles", "__weakref__")

    def __init__(self, links: "Sequence[Link | Loader]") -> None:
        if not links or callable(links[0]):
            raise ValueError("a chain's first link is a (font, coverage) pair")
        self._fonts: list = []
        self._coverages: list[Coverage | None] = []
        self._loaders: list[Loader | None] = []
        for link in links:
            if callable(link):
                self._fonts.append(_UNLOADED)
                self._coverages.append(None)
                self._loaders.append(link)
            else:
                font, coverage = link
                self._fonts.append(font)
                self._coverages.append(coverage)
                self._loaders.append(None)
        primary = self._coverages[0]
        self._ascii_primary = primary is None or all(primary.has(cp) for cp in _ASCII_PRINTABLE)
        self._memo: dict[str, int] = {}        # grapheme → font index
        self._chars: dict[str, int] = {}       # character → font index, or _JOINS
        # Style changes made on the chain, replayed on fonts loaded later: name → apply.
        self._styles: dict[str, Callable[[pygame.font.Font], None]] = {}

    # --- the chain ---------------------------------------------------------------------------

    @property
    def primary(self) -> "pygame.font.Font":
        return self._fonts[0]

    @property
    def loaded(self) -> int:
        """How many of the chain's fonts are open (loaders not yet run don't count)."""
        return sum(1 for font in self._fonts if font is not _UNLOADED and font is not _UNUSABLE)

    def runs(self, text: str) -> "list[tuple[pygame.font.Font, str]]":
        """``text`` as (font, piece) runs in order; ``"".join`` of the pieces is ``text``."""
        return [(self._fonts[index], piece) for index, piece in self._runs(text)]

    def _runs(self, text: str) -> list[tuple[int, str]]:
        if not text or (self._ascii_primary and text.isascii()):
            return [(0, text)]
        # Per distinct character first: when none can join a cluster, every character is a
        # grapheme of its own, and one font for all of them is the common case.
        chars = self._chars
        picks: dict[str, int] = {}
        for char in set(text):
            index = chars.get(char)
            if index is None:
                index = _JOINS if _joins(char) else self._pick(char)
                if len(chars) >= MEMO_ENTRIES:
                    del chars[next(iter(chars))]
                chars[char] = index
            if index == _JOINS:
                return self._grapheme_runs(text)
            picks[char] = index
        if len(set(picks.values())) == 1:
            return [(picks[text[0]], text)]
        runs: list[tuple[int, str]] = []
        current, start = picks[text[0]], 0
        for at, char in enumerate(text):
            index = picks[char]
            if index != current:
                runs.append((current, text[start:at]))
                current, start = index, at
        runs.append((current, text[start:]))
        return runs

    def _grapheme_runs(self, text: str) -> list[tuple[int, str]]:
        runs: list[tuple[int, str]] = []
        current, start, at = -1, 0, 0
        memo = self._memo
        for grapheme in iter_graphemes(text):
            index = memo.get(grapheme)
            if index is None:
                index = self._pick(grapheme)
                if len(memo) >= MEMO_ENTRIES:
                    del memo[next(iter(memo))]
                memo[grapheme] = index
            if index != current:
                if at > start:
                    runs.append((current, text[start:at]))
                current, start = index, at
            at += len(grapheme)
        runs.append((current, text[start:at]))
        return runs

    def _pick(self, grapheme: str) -> int:
        """The index of the font that draws ``grapheme`` (see the module docstring)."""
        base = ord(grapheme[0])
        base_font = last = -1
        for index in range(len(self._fonts)):
            if not self._ready(index):
                continue
            coverage = self._coverages[index]
            if coverage is None or coverage.covers(grapheme):
                return index
            if base_font < 0 and coverage.has(base):
                base_font = index
            last = index
        return base_font if base_font >= 0 else last

    def _ready(self, index: int) -> bool:
        """Whether font ``index`` is usable, running its loader the first time."""
        font = self._fonts[index]
        if font is _UNLOADED:
            loaded = self._loaders[index]()          # type: ignore[misc]
            self._loaders[index] = None
            if loaded is None:
                self._fonts[index] = font = _UNUSABLE
            else:
                font, self._coverages[index] = loaded
                for apply in self._styles.values():
                    apply(font)
                self._fonts[index] = font
        return font is not _UNUSABLE

    def _each_font(self) -> list:
        return [font for font in self._fonts if font is not _UNLOADED and font is not _UNUSABLE]

    # --- measuring and drawing ---------------------------------------------------------------

    def size(self, text: str) -> tuple[int, int]:
        """(width, height) of ``text`` as ``render`` draws it."""
        runs = self._runs(text) if isinstance(text, str) else [(0, text)]
        if len(runs) == 1:
            return self._fonts[runs[0][0]].size(runs[0][1])
        width = sum(self._fonts[index].size(piece)[0] for index, piece in runs)
        return width, self._fonts[0].get_height()

    def render(self, text: str, antialias: bool, color, bgcolor=None,
               wraplength: int = 0) -> "pygame.Surface":
        """``text`` drawn as ``pygame.font.Font.render`` would, run by run. With more than one
        run the result is 32-bit (per-pixel alpha without ``bgcolor``) and ``wraplength`` is
        ignored (the engine wraps text itself)."""
        runs = self._runs(text) if isinstance(text, str) else [(0, text)]
        if len(runs) == 1:
            index, piece = runs[0]
            return self._fonts[index].render(piece, antialias, color, bgcolor, wraplength)
        primary = self._fonts[0]
        baseline = primary.get_ascent()
        pieces = []
        for index, piece in runs:
            font = self._fonts[index]
            pieces.append((font.render(piece, antialias, color, bgcolor),
                           baseline - font.get_ascent()))
        size = (sum(surface.get_width() for surface, _ in pieces), primary.get_height())
        if bgcolor is None:
            out = pygame.Surface(size, pygame.SRCALPHA, 32)
            out.fill((*pygame.Color(color)[:3], 0))
        else:
            out = pygame.Surface(size, 0, 32)
            out.fill(bgcolor)
        x = 0
        for surface, y in pieces:
            if surface.get_flags() & pygame.SRCALPHA:
                # Onto the clear surface, unblended: a plain alpha blit would darken the
                # anti-aliased edges against the transparent black.
                out.blit(surface, (x, y), special_flags=pygame.BLEND_RGBA_MAX)
            else:
                out.blit(surface, (x, y))          # colour-keyed or opaque runs
            x += surface.get_width()
        return out

    def metrics(self, text: str) -> list:
        """Per code point ``(minx, maxx, miny, maxy, advance)``, each from the font that
        draws it."""
        runs = self._runs(text) if isinstance(text, str) else [(0, text)]
        if len(runs) == 1:
            return self._fonts[runs[0][0]].metrics(runs[0][1])
        out: list = []
        for index, piece in runs:
            out.extend(self._fonts[index].metrics(piece))
        return out

    # --- the primary's metrics ---------------------------------------------------------------

    def get_ascent(self) -> int:
        return self._fonts[0].get_ascent()

    def get_descent(self) -> int:
        return self._fonts[0].get_descent()

    def get_height(self) -> int:
        return self._fonts[0].get_height()

    def get_linesize(self) -> int:
        return self._fonts[0].get_linesize()

    def get_point_size(self) -> int:
        return self._fonts[0].get_point_size()

    def get_bold(self) -> bool:
        return self._fonts[0].get_bold()

    def get_italic(self) -> bool:
        return self._fonts[0].get_italic()

    def get_underline(self) -> bool:
        return self._fonts[0].get_underline()

    def get_strikethrough(self) -> bool:
        return self._fonts[0].get_strikethrough()

    @property
    def name(self) -> str:
        return self._fonts[0].name

    @property
    def style_name(self) -> str:
        return self._fonts[0].style_name

    # --- styles: set on every font of the chain ----------------------------------------------

    def _set_all(self, key: str, apply: Callable[["pygame.font.Font"], None]) -> None:
        self._styles[key] = apply
        for font in self._each_font():
            apply(font)

    bold = _shared("bold")
    italic = _shared("italic")
    underline = _shared("underline")
    strikethrough = _shared("strikethrough")
    outline = _shared("outline")
    align = _shared("align")
    point_size = _shared("point_size")

    def _call_all(self, method: str, *args) -> None:
        self._set_all(method, lambda font: getattr(font, method)(*args))

    def set_bold(self, value: bool) -> None:
        self.bold = value

    def set_italic(self, value: bool) -> None:
        self.italic = value

    def set_underline(self, value: bool) -> None:
        self.underline = value

    def set_strikethrough(self, value: bool) -> None:
        self.strikethrough = value

    def set_point_size(self, value: int) -> None:
        self.point_size = value

    def set_linesize(self, value: int) -> None:
        self._call_all("set_linesize", value)

    def set_direction(self, value: int) -> None:
        self._call_all("set_direction", value)

    def set_script(self, value: str) -> None:
        self._call_all("set_script", value)
