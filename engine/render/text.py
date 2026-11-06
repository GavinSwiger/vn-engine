"""Font handles and line layout: word wrap and shortening a line with "…".

Why this module exists: text is laid out in canvas units with a font whose size equals the
canvas size in pixels, so line breaks never depend on the window size (PR-F01-21,
ADR-0001 decision 3). Only the rasterization happens at device size (``Canvas.draw_text``).
F05, F13, F17, F29, and F43 lay out their text with these same functions.

Both functions measure with ``font.size()`` only, and both stay fast on very long input:
a word longer than the line is split with a binary search per line, and ``fit_line`` uses a
binary search over the prefix length (O(log n) measurements).
"""

from dataclasses import dataclass
from enum import Enum

import pygame

ELLIPSIS = "…"


class Face(Enum):
    """A bundled Noto Sans face (ADR-0004 and its F05 amendment). Defined here so
    ``FontSpec`` can name one; ``engine.render.assets`` re-exports it. F65 round 3 adds the
    device looks' own faces: Noto Sans Mono (the terminal) and Noto Serif Regular and
    Italic (letter and pigeon headings and signatures); text styles never pick them."""
    REGULAR = "regular"
    BOLD = "bold"
    ITALIC = "italic"
    BOLD_ITALIC = "bold-italic"
    MONO = "mono"
    SERIF = "serif"
    SERIF_ITALIC = "serif-italic"


class Synth(Enum):
    """A style pygame synthesizes on an author's font (F05 §7.6, W45)."""
    NONE = "none"
    BOLD = "bold"
    ITALIC = "italic"
    BOLD_ITALIC = "bold-italic"


@dataclass(frozen=True)
class FontSpec:
    """A font as ``Canvas.draw_text`` asks ``AssetManager.font`` for it. ``bundled`` is the
    bundled face used when ``ref`` is None (and as its fallback); ``synth`` the style pygame
    makes on an author's font (F05 ``FaceSource``). The defaults are the plain Regular face,
    so ``FontSpec(ref, size)`` means what it always did."""
    ref: str | None    # game-relative path (e.g. "fonts/Lora.ttf"); None = bundled Noto Sans
    size: int          # canvas pixels
    bundled: Face = Face.REGULAR
    synth: Synth = Synth.NONE


@dataclass(frozen=True, eq=False)
class FontHandle:
    font: "pygame.font.Font"
    key: tuple          # ("font", ref_or_DEFAULT, size_px); used in text-line cache keys
    size_px: int


def text_width(font: "pygame.font.Font", text: str) -> int:
    return font.size(text)[0] if text else 0


def wrap_lines(font: "pygame.font.Font", text: str, max_width: float | None) -> list[str]:
    """Greedy word wrap with reference metrics (font size == canvas px). Honors '\\n'.
    Breaks a word longer than max_width by characters."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if max_width is None:
            lines.append(paragraph)
            continue
        line = ""
        for word in paragraph.split(" "):
            candidate = word if not line else f"{line} {word}"
            if text_width(font, candidate) <= max_width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = word
            while text_width(font, line) > max_width and len(line) > 1:
                cut = _longest_fitting_prefix(font, line, max_width, "")
                cut = max(cut, 1)                   # at least one character per line
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line)
    return lines


def fit_line(font: "pygame.font.Font", text: str, max_width: float,
             suffix: str = ELLIPSIS) -> str:
    """text if it fits; else the longest prefix + suffix that fits (binary search over
    the prefix length: O(log n) width measurements)."""
    if text_width(font, text) <= max_width:
        return text
    return text[:_longest_fitting_prefix(font, text, max_width, suffix)] + suffix


def _longest_fitting_prefix(font: "pygame.font.Font", text: str, max_width: float,
                            suffix: str) -> int:
    """The largest k such that text[:k] + suffix fits in max_width (0 if none does).

    Galloping first (16, 32, 64, … characters), then a binary search, so each measurement
    is at most about twice as long as the answer, even for a 5,000-character word."""
    def fits(k: int) -> bool:
        return text_width(font, text[:k] + suffix) <= max_width

    low, probe = 0, 16
    while probe < len(text) and fits(probe):
        low, probe = probe, probe * 2
    high = min(probe, len(text))
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return low


# --- Missing glyphs (F26 TR-F26-03, lifted by F52 04 §3 for F52, F55 and F56) ---------------

NOT_A_CHAR = "￿"                 # a code point no font maps: its glyph is .notdef


def _same_picture(a: "pygame.Surface", b: "pygame.Surface") -> bool:
    return a.get_size() == b.get_size() and a.get_buffer().raw == b.get_buffer().raw


def missing_glyphs(font: "pygame.font.Font", chars: str) -> list[str]:
    """The characters of ``chars`` that ``font`` draws as ``.notdef``: metrics equal to
    U+FFFF's (one ``metrics`` call for all) **and** the same pixels. pygame-ce's
    ``Font.metrics`` gives ``.notdef``'s metrics for a missing glyph, not None, so the pixels
    decide. ``font`` is a ``pygame.font.Font`` or F43's ``ChainFont`` (duck-typed)."""
    if not chars:
        return []
    ref = font.metrics(NOT_A_CHAR)[0]
    white = (255, 255, 255)
    ref_px = font.render(NOT_A_CHAR, False, white)
    missing = []
    for ch, metric in zip(chars, font.metrics(chars)):
        if metric == ref and _same_picture(font.render(ch, False, white), ref_px):
            missing.append(ch)
    return missing
