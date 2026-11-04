"""``CardPainter``: the full-screen title card (F18 SPEC §4 UI-F18-01, §5; F19 reuses it for
ending cards through ``TitleCard.kind``).

Why this module exists: the card is not a screen. It is drawn at the top of the stage
composite (F18 07, question 2), so F09's transitions, shake, flash, and reduced effects act
on it with no renderer of their own. ``StageView`` calls ``paint(canvas, card)`` while it
composes, with ``canvas`` bound to the composite buffer, so the card costs nothing outside a
compose (ADR-0005): at most three text renders, inside F04's one long frame.

The look (``CardStyle``, ``[theme.chapter]``; ``app/chapters.py`` builds it from config):

- A full-canvas fill ``fill_color`` at ``fill_opacity``. At 1.0 the card is ``opaque`` and
  the stage under it is not drawn at all; below 1.0 the stage shows through.
- The heading (one line, cut with "…" at ``max_width``) and the title (wrapped at
  ``max_width`` to at most 2 lines, the second cut with "…"), each line centered on x 640.
  Line pitch is round(1.4 × size); the block (heading pitch, ``gap``, title pitches) is
  centered on y 360. One text means the title alone. Sizes are canvas units, never scaled
  by F16's text size; the raster is at device size (``Canvas.draw_text``).
- Layout uses reference metrics only, so it is the same at every scale; the last
  ``CACHE_SIZE`` layouts are kept (a card is composed for its in and out transitions, and
  again on a resize).

W110 (dev runs, once per card name and kind, area ``ui``, 07 I-8): a title that needs more
than 2 lines. Its text is built here (``w110_text``).
"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Final

from engine.core.constants import CANVAS_SIZE
from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.render.canvas import RGB, Canvas
from engine.render.text import Face, FontSpec
from engine.runtime.commands import TitleCard

CACHE_SIZE: Final = 4
TITLE_LINES: Final = 2
LINE_PITCH: Final = 1.4                  # × the text size, rounded (UI-F18-01)
ELLIPSIS: Final = "…"

_log = get_logger("ui")


@dataclass(frozen=True, slots=True)
class CardStyle:
    """The ``[theme.chapter]`` tokens, resolved (fonts as ``FontSpec``s at their sizes).
    The defaults are SPEC §4's, with the bundled faces standing in for ``ui.text_font`` and
    ``ui.bold_font``."""

    fill_color: RGB = (0x2A, 0x1E, 0x26)
    fill_opacity: float = 1.0
    heading_font: FontSpec = FontSpec(None, 32)
    heading_color: RGB = (0xF0, 0xA0, 0xC0)
    title_font: FontSpec = FontSpec(None, 56, Face.BOLD)
    title_color: RGB = (0xFF, 0xF4, 0xF8)
    gap: float = 16
    max_width: float = 1040


@dataclass(frozen=True, slots=True)
class CardLine:
    """One drawn line: its text, font, color, and center in canvas units."""

    text: str
    font: FontSpec
    color: RGB
    center: tuple[float, float]


@dataclass(frozen=True, slots=True)
class CardLayout:
    lines: tuple[CardLine, ...]
    cut: bool                            # the title needed more than ``TITLE_LINES``
    kept: int                            # code points of the title shown (W110's "about")


def pitch(font: FontSpec) -> int:
    return round(LINE_PITCH * font.size)


def w110_text(card: TitleCard, size: int, kept: int) -> str:
    """W110 (SPEC §3): the title is cut; ``kept`` code points fit (shown rounded down to
    tens)."""
    about = max(10, kept // 10 * 10)
    return (f'the title of {card.kind} "{echo(card.name)}" needs more than {TITLE_LINES} '
            f'lines on its card at size {size}, so it is cut with "{ELLIPSIS}". Shorten it '
            f"to about {about} characters.")


class CardPainter:
    """``render/stage.py``'s ``CardPainter``: paints a ``TitleCard`` onto a bound canvas."""

    def __init__(self, style: CardStyle | None = None, *, dev: bool = False,
                 log=_log) -> None:
        self.style = style if style is not None else CardStyle()
        self.dev = dev
        self.log = log
        self._layouts: OrderedDict[tuple, CardLayout] = OrderedDict()
        self._warned: set[tuple[str, str]] = set()

    def restyle(self, style: CardStyle) -> None:
        """F49 (07 I-1): the current look's card style from now on (``app/chapters.py``'s
        look listener, once per look change); the cached layouts hold colors, so they go."""
        if style != self.style:
            self.style = style
            self._layouts.clear()

    @property
    def opaque(self) -> bool:
        """The fill hides the stage, so ``StageView`` does not draw it."""
        return self.style.fill_opacity >= 1.0

    def paint(self, canvas: Canvas, card: TitleCard) -> None:
        """The fill, then each line centered where ``layout`` puts it."""
        style = self.style
        alpha = round(max(0.0, min(1.0, style.fill_opacity)) * 255)
        canvas.fill((*style.fill_color, alpha) if alpha < 255 else style.fill_color)
        for line in self.layout(canvas, card).lines:
            if line.text:
                canvas.draw_text(line.text, line.font, line.color, line.center,
                                 anchor="center")

    def layout(self, canvas: Canvas, card: TitleCard) -> CardLayout:
        """The lines of ``card`` (cached; reference metrics, so any scale)."""
        key = (card.heading, card.title)
        found = self._layouts.get(key)
        if found is not None:
            self._layouts.move_to_end(key)
        else:
            found = self._layout(canvas, card)
            self._layouts[key] = found
            while len(self._layouts) > CACHE_SIZE:
                self._layouts.popitem(last=False)
        if found.cut and self.dev and (card.kind, card.name) not in self._warned:
            self._warned.add((card.kind, card.name))
            self.log.warning("%s", w110_text(card, self.style.title_font.size, found.kept),
                             extra={"code": "W110"})
        return found

    def _layout(self, canvas: Canvas, card: TitleCard) -> CardLayout:
        style = self.style
        width = style.max_width
        titles = canvas.layout_lines(card.title, style.title_font, width, None)
        cut = len(titles) > TITLE_LINES
        if cut:
            titles = canvas.layout_lines(card.title, style.title_font, width, TITLE_LINES)
        kept = sum(len(t) for t in titles) - (len(ELLIPSIS) if cut else 0)
        rows: list[tuple[str, FontSpec, RGB]] = []
        if card.heading is not None:
            heading = canvas.layout_lines(card.heading, style.heading_font, width, 1)
            rows.append((heading[0] if heading else "", style.heading_font,
                         style.heading_color))
        rows += [(t, style.title_font, style.title_color) for t in titles]
        heights = [pitch(font) for _, font, _ in rows]
        gap = style.gap if card.heading is not None else 0.0
        top = CANVAS_SIZE[1] / 2 - (sum(heights) + gap) / 2
        x = CANVAS_SIZE[0] / 2
        lines: list[CardLine] = []
        for index, ((text, font, color), height) in enumerate(zip(rows, heights)):
            lines.append(CardLine(text, font, color, (x, top + height / 2)))
            top += height + (gap if index == 0 and card.heading is not None else 0.0)
        return CardLayout(tuple(lines), cut, kept)


__all__ = ["CACHE_SIZE", "CardLayout", "CardLine", "CardPainter", "CardStyle", "pitch",
           "w110_text"]
