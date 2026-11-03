"""Where a line may break inside CJK text (F43 ``04`` §7.5; PR-F43-14).

Why this module exists: Japanese and Chinese have no spaces, and Korean lines may break
between syllables, so breaking only at spaces would split such a line at an arbitrary
character (or not at all). Text layout (``textlayout._lines``) and ``text.wrap_lines`` ask this
module for the extra places a line may break. It is pure (no pygame): a list of graphemes in,
break positions out.

The rule: a **soft break** may go before grapheme *i* (0 < *i* < n) when

- grapheme *i − 1* or *i* is **ideographic** (Han, kana, Hangul, CJK symbols and
  punctuation, fullwidth forms), judged by its first code point;
- neither is a space a line already breaks at (spaces keep their own rule), a control, or
  glue (the no-break spaces U+00A0, U+2007, U+202F, the word joiner, U+FEFF);
- *i* isn't **no-start** (kinsoku): closing brackets and quotes (``）」』】〉》`` and every
  Pe/Pf character), ``、。，．・：；！？`` and their ASCII forms, small kana, ``ー``, the
  iteration marks;
- *i − 1* isn't **no-end**: opening brackets and quotes (``（「『【〈《`` and every Ps/Pi
  character);
- they aren't the same inseparable mark (``……``, ``——``).

Latin words get no soft breaks inside them (they still break at spaces only):
``日本Englishです`` may break before ``本``, ``E`` and ``で``, never inside ``English``.
"""

import unicodedata
from collections.abc import Sequence
from typing import Final

from engine.core.graphemes import graphemes

# Ideographic blocks (first code point of a grapheme), as inclusive ranges in order.
_IDEOGRAPHIC: Final = (
    (0x1100, 0x11FF),        # Hangul Jamo
    (0x2E80, 0x2FFF),        # CJK radicals, Kangxi, ideographic description
    (0x3000, 0x303F),        # CJK symbols and punctuation
    (0x3040, 0x30FF),        # Hiragana, Katakana
    (0x3100, 0x31FF),        # Bopomofo, Hangul compatibility jamo, Kanbun, strokes, kana ext.
    (0x3200, 0x33FF),        # enclosed CJK letters, CJK compatibility
    (0x3400, 0x4DBF),        # CJK extension A
    (0x4E00, 0x9FFF),        # CJK unified ideographs
    (0xA960, 0xA97F),        # Hangul jamo extended A
    (0xAC00, 0xD7FF),        # Hangul syllables, jamo extended B
    (0xF900, 0xFAFF),        # CJK compatibility ideographs
    (0xFE10, 0xFE1F),        # vertical forms
    (0xFE30, 0xFE4F),        # CJK compatibility forms
    (0xFF00, 0xFFEF),        # halfwidth and fullwidth forms
    (0x1AFF0, 0x1B16F),      # kana extended, supplement, small kana extension
    (0x20000, 0x3FFFF),      # CJK extensions B and later, compatibility supplement
)

# Never at a line's start besides Pe/Pf (PR-F43-14's list, ASCII forms, small kana).
_NO_START: Final = frozenset(
    "、。，．・：；！？）」』】〉》〕〗〙〛｝］｠｣"
    "ー〜～ゝゞヽヾ々〻"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ"
    "ㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿ"
    "ｧｨｩｪｫｬｭｮｯｰ､｡･ﾞﾟ゛゜"
    ".,:;!?%)]}‼⁇⁈⁉‰′″℃°"
)
# Never at a line's end besides Ps/Pi.
_NO_END: Final = frozenset("（「『【〈《〔〖〘〚｛［｟｢([{¥$£€＄￥￡")
# Glue: no break on either side (no-break spaces, word joiner, zero-width no-break space).
_GLUE: Final = frozenset("   ⁠﻿")
# Two of the same never split.
_INSEPARABLE: Final = frozenset("…‥—―")
# Spaces a line breaks at already: the Zs characters but the no-break ones (U+00A0, U+2007,
# U+202F), as ``textlayout.is_break_space``.
_SPACES: Final = frozenset("         "
                           "    　")


def is_ideographic(grapheme: str) -> bool:
    """Whether the grapheme's first code point is in a CJK block (Han, kana, Hangul, CJK
    symbols, fullwidth forms)."""
    if not grapheme:
        return False
    cp = ord(grapheme[0])
    if cp < 0x1100:
        return False
    for low, high in _IDEOGRAPHIC:
        if cp < low:
            return False
        if cp <= high:
            return True
    return False


def soft_breaks(units: Sequence[str]) -> frozenset[int]:
    """The indexes *i* such that a line may break before ``units[i]`` (graphemes) besides
    at spaces. Empty for text with no CJK, so Latin layout is unchanged."""
    n = len(units)
    if n < 2:
        return frozenset()
    ideo = [is_ideographic(g) for g in units]
    if not any(ideo):
        return frozenset()
    found = []
    for i in range(1, n):
        if not (ideo[i] or ideo[i - 1]):
            continue
        before, after = units[i - 1], units[i]
        if _is_space_or_control(before) or _is_space_or_control(after):
            continue
        if before[0] in _GLUE or after[0] in _GLUE:
            continue
        if _no_start(after) or _no_end(before):
            continue
        if before == after and before[0] in _INSEPARABLE:
            continue
        found.append(i)
    return frozenset(found)


def segments(text: str) -> list[str]:
    """``text`` (one paragraph) cut where a line may break: after each run of spaces and at
    each soft break. Each piece is a word plus its trailing spaces; ``"".join`` gives
    ``text`` back. A wrapper fills a line piece by piece and drops the trailing spaces of
    the piece that ends it."""
    units = graphemes(text)
    soft = soft_breaks(units)
    pieces: list[str] = []
    current: list[str] = []
    in_spaces = False
    for i, unit in enumerate(units):
        space = unit in _SPACES
        if current and ((in_spaces and not space) or i in soft):
            pieces.append("".join(current))
            current = []
        current.append(unit)
        in_spaces = space
    if current:
        pieces.append("".join(current))
    return pieces


def _is_space_or_control(grapheme: str) -> bool:
    return grapheme in _SPACES or unicodedata.category(grapheme[0]) in ("Cc", "Zl", "Zp")


def _no_start(grapheme: str) -> bool:
    first = grapheme[0]
    return first in _NO_START or unicodedata.category(first) in ("Pe", "Pf")


def _no_end(grapheme: str) -> bool:
    first = grapheme[0]
    return first in _NO_END or unicodedata.category(first) in ("Ps", "Pi")
