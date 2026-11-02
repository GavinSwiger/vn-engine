"""M20: a fixed-width fake font behind a fake ``AssetManager.font`` (F05 ``06`` §0.6).

Every grapheme (spaces and U+FFFD included) advances ``round(20 × size / 28)`` units; ascent
``round(22 × size / 28)``, descent ``round(6 × size / 28)`` (negative, as pygame reports it);
no kerning; every face the same width unless ``advance`` says otherwise. At size 28 the
920-unit text area holds exactly 46 graphemes per line and 3 lines per page.

No real font is opened, so layout and typewriter tests need no ``pygame.font``.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from engine.core.graphemes import graphemes
from engine.render.assets import Face, Synth
from engine.render.textlayout import BUNDLED_FACES, FaceSet, LayoutContext
from engine.script.texttags import TaggedText, parse

TEXT_AREA_WIDTH = 920
BASE_COLOR = "#3d2b36"


class FixedFont:
    """A ``pygame.font.Font`` stand-in. ``calls`` counts ``size()`` calls."""

    def __init__(self, size_px: int, advance_at_28: int = 20) -> None:
        self.size_px = size_px
        self.advance = round(advance_at_28 * size_px / 28)
        self.ascent = round(22 * size_px / 28)
        self.descent = round(6 * size_px / 28)
        self.calls = 0

    def size(self, text: str) -> tuple[int, int]:
        self.calls += 1
        return len(graphemes(text)) * self.advance, self.ascent + self.descent

    def get_ascent(self) -> int:
        return self.ascent

    def get_descent(self) -> int:
        return -self.descent

    def get_height(self) -> int:
        return self.ascent + self.descent


@dataclass(frozen=True, eq=False)
class FixedHandle:
    font: FixedFont
    key: tuple
    size_px: int


class FixedFontAssets:
    """``font(ref, size_px, *, bundled, synth)`` as ``AssetManager``'s, one cached
    ``FixedFont`` per key. ``advance`` gives a face another advance at size 28."""

    def __init__(self, advance: Mapping[Face, int] | None = None) -> None:
        self.advance = dict(advance or {})
        self.requests: list[tuple] = []
        self._fonts: dict[tuple, FixedHandle] = {}

    def font(self, ref: str | None, size_px: int, *, bundled: Face = Face.REGULAR,
             synth: Synth = Synth.NONE) -> FixedHandle:
        key = ("font", ref or f"<{bundled.value}>", size_px, synth)
        self.requests.append(key)
        handle = self._fonts.get(key)
        if handle is None:
            font = FixedFont(size_px, self.advance.get(bundled, 20))
            handle = self._fonts[key] = FixedHandle(font, key, size_px)
        return handle


def area_height(text_size: int) -> int:
    """UI-F05-01/02: the text area height H − top − bottom padding (28 + 28)."""
    pitch = round(1.4 * text_size)
    return min(216, max(184, 56 + 3 * pitch)) - 56


def m20_context(text_size: int = 28, *, assets: FixedFontAssets | None = None,
                faces: FaceSet = BUNDLED_FACES, width: float = TEXT_AREA_WIDTH,
                height: float | None = None) -> LayoutContext:
    return LayoutContext(assets if assets is not None else FixedFontAssets(), faces,
                         text_size, BASE_COLOR, width,
                         area_height(text_size) if height is None else height)


def tagged(text: str) -> TaggedText:
    """``text``'s body via the real tag parser; a tag mistake fails the test."""
    problems: list = []
    body = parse(text, lambda offset: (1, offset + 1), problems.append)
    assert body is not None, [p.message() for p in problems]
    return body
