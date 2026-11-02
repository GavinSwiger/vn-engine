"""User-perceived characters: a simplified extended grapheme cluster split (F05 §7.1).

Why this module exists: text is typed, counted, cut, and measured per grapheme, never per
code point (PR-F05-07), so ``e`` + U+0301, a skin-toned emoji, or a flag appears as one
step. It is a general text primitive needed by ``runtime`` (the ``{var}`` cut), ``render``
(layout and typing), and later ``script`` checks (F41, F43), so it lives in ``core``.

The rules, from ``unicodedata`` (Unicode 15): a base code point takes the marks that follow
it (Mn, Me, Mc), variation selectors, emoji modifiers, tag characters, and U+200D together
with the code point after it; regional indicators pair; Hangul L/V/T jamo join. A control
character (``\\n`` among them) is always a cluster of its own. A cluster is cut at
``MAX_CLUSTER_CODE_POINTS`` so hostile mark runs stay bounded. Full UAX #29, CJK rules, and
shaping are F43's.

Standard library only, and no tables built at import (F05 I-14).
"""

import unicodedata
from collections.abc import Iterator

MAX_CLUSTER_CODE_POINTS = 32

_ZWJ = 0x200D
_MARK_CATEGORIES = ("Mn", "Me", "Mc")
_OWN_CLUSTER_CATEGORIES = ("Cc", "Zl", "Zp")      # never extended, never extend

# Hangul syllable types (UAX #29 GB6-GB8): which type may follow which.
_L, _V, _T, _LV, _LVT = "L", "V", "T", "LV", "LVT"
_HANGUL_FOLLOWERS = {
    _L: (_L, _V, _LV, _LVT),
    _V: (_V, _T),
    _LV: (_V, _T),
    _T: (_T,),
    _LVT: (_T,),
}


def graphemes(text: str) -> list[str]:
    """``text`` split into clusters; ``"".join(graphemes(text)) == text``."""
    return list(iter_graphemes(text))


def iter_graphemes(text: str) -> Iterator[str]:
    """The clusters of ``text`` one at a time, so a caller that needs only the first few
    (the 200-grapheme ``{var}`` cut) never scans the rest."""
    n = len(text)
    i = 0
    while i < n:
        start = i
        base = text[i]
        i += 1
        if _is_own_cluster(base):
            yield base
            continue
        hangul = _hangul_type(base)
        open_indicator = _is_regional_indicator(base)
        after_zwj = ord(base) == _ZWJ
        while i < n and i - start < MAX_CLUSTER_CODE_POINTS:
            char = text[i]
            if _is_own_cluster(char):
                break
            if after_zwj:                       # U+200D joins the next code point
                after_zwj = ord(char) == _ZWJ
                hangul = _hangul_type(char)
                open_indicator = _is_regional_indicator(char)
                i += 1
                continue
            if _is_extender(char):
                after_zwj = ord(char) == _ZWJ
                hangul = None
                open_indicator = False
                i += 1
                continue
            if open_indicator and _is_regional_indicator(char):
                open_indicator = False
                hangul = None
                i += 1
                continue
            if hangul is not None:
                follower = _hangul_type(char)
                if follower is not None and follower in _HANGUL_FOLLOWERS[hangul]:
                    hangul = follower
                    i += 1
                    continue
            break
        yield text[start:i]


def _is_own_cluster(char: str) -> bool:
    return char == "\n" or unicodedata.category(char) in _OWN_CLUSTER_CATEGORIES


def _is_extender(char: str) -> bool:
    """A code point that attaches to the cluster before it (U+200D included)."""
    code = ord(char)
    if code < 0x0300:                           # nothing below the combining marks extends
        return False
    return (code == _ZWJ
            or 0xFE00 <= code <= 0xFE0F         # variation selectors (also Mn)
            or 0x1F3FB <= code <= 0x1F3FF       # emoji modifiers (Sk)
            or 0xE0020 <= code <= 0xE007F       # tag characters (Cf)
            or unicodedata.category(char) in _MARK_CATEGORIES)


def _is_regional_indicator(char: str) -> bool:
    return 0x1F1E6 <= ord(char) <= 0x1F1FF


def _hangul_type(char: str) -> str | None:
    code = ord(char)
    if 0x1100 <= code <= 0x115F or 0xA960 <= code <= 0xA97C:
        return _L
    if 0x1160 <= code <= 0x11A7 or 0xD7B0 <= code <= 0xD7C6:
        return _V
    if 0x11A8 <= code <= 0x11FF or 0xD7CB <= code <= 0xD7FB:
        return _T
    if 0xAC00 <= code <= 0xD7A3:
        return _LV if (code - 0xAC00) % 28 == 0 else _LVT
    return None
