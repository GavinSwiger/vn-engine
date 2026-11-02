"""The error page's fixed look, shared by the real ``ErrorScreen`` and F30's fake crash.

Why this module exists: F30's fake crash must look exactly like the engine's own error page
(UI-F30-01), but must never reach the error screen's redaction, copy hint, or clipboard
(SEC-F30-05; ``fake_crash.py`` never imports ``error.py``). So the constants and the page
drawing live here, with no input, no state, and no clipboard; ``ErrorScreen`` keeps its
behavior, its texts, and the engine's only clipboard write (F30 ``04`` §6.5).

The look is engine-fixed (SEC-F30-10 (a)): no theme tokens, images, or buttons. Canvas units
(ADR-0001), always the bundled Noto Sans (ADR-0004).
"""

from collections.abc import Sequence

from engine.core.constants import CANVAS_SIZE
from engine.render.canvas import Canvas
from engine.render.text import ELLIPSIS, FontSpec, fit_line

BACKGROUND = (0x14, 0x14, 0x14)          # #141414
HEADING_COLOR = (0xFF, 0xFF, 0xFF)       # #FFFFFF
MESSAGE_COLOR = (0xF0, 0xF0, 0xF0)       # #F0F0F0, about 16.0:1 (PR-F01-42)
DETAIL_COLOR = (0xC8, 0xC8, 0xC8)        # #C8C8C8, about 11.0:1
HINT_COLOR = (0xFF, 0xFF, 0xFF)
HEADING_FONT = FontSpec(None, 40)
TEXT_FONT = FontSpec(None, 28)

LEFT = 80                                # canvas units
TEXT_WIDTH = CANVAS_SIZE[0] - 2 * LEFT   # 1120
HEADING_Y = 96
MESSAGE_Y = 168
MESSAGE_BOTTOM = 520
TITLE_Y = 540
LOG_Y = 580
HINT_Y = 640
LABEL_Y = 680                            # F30: the fake crash's optional label

HEADING = "The game ran into a problem"


def title_line(title: str, version: str) -> str:
    """The details line: ``"T" version V``."""
    return f'"{title}" version {version}'


def _text_font(canvas: Canvas):
    return canvas.assets.font(None, TEXT_FONT.size).font


def fit_message(canvas: Canvas, text: str, *, cut_notice: str | None) -> list[str]:
    """The message as blocks for ``draw_page``, each drawn below the previous one.

    A message that fits above ``MESSAGE_BOTTOM`` is one block, the whole text. A longer one
    keeps the lines that fit: with ``cut_notice``, all but the last line, then the notice as
    a second block; with ``cut_notice`` None, every line that fits, the last ending in
    "…"."""
    lines = canvas.layout_lines(text, TEXT_FONT, TEXT_WIDTH, None)
    line_height = _text_font(canvas).get_linesize()
    fit_all = max(1, int((MESSAGE_BOTTOM - MESSAGE_Y) // line_height))
    if len(lines) <= fit_all:
        return [text]
    if cut_notice is not None:
        kept = lines[:max(fit_all - 1, 0)]          # leave a line for the notice
        return ["\n".join(kept), cut_notice]
    kept = lines[:fit_all]
    if not kept[-1].endswith(ELLIPSIS):
        kept[-1] = fit_line(_text_font(canvas), kept[-1] + ELLIPSIS, TEXT_WIDTH)
    return ["\n".join(kept)]


def draw_page(canvas: Canvas, *, lines: Sequence[str], title_line: str,
              log_line: str | None, hint: str, label: str | None) -> None:
    """The whole page: fill, heading, the message ``lines`` (blocks from ``fit_message``),
    the details line, the log line (the real screen only), the hint, and the label (the
    fake crash, when the player asked for it). Every one-line text is cut to the width."""
    canvas.fill(BACKGROUND)
    canvas.draw_text(HEADING, HEADING_FONT, HEADING_COLOR, (LEFT, HEADING_Y))
    font = _text_font(canvas)
    line_height = font.get_linesize()
    y = MESSAGE_Y
    for block in lines:
        canvas.draw_text(block, TEXT_FONT, MESSAGE_COLOR, (LEFT, y), max_width=TEXT_WIDTH)
        y += line_height * (block.count("\n") + 1)
    canvas.draw_text(fit_line(font, title_line, TEXT_WIDTH), TEXT_FONT, DETAIL_COLOR,
                     (LEFT, TITLE_Y))
    if log_line is not None:
        canvas.draw_text(fit_line(font, log_line, TEXT_WIDTH), TEXT_FONT, DETAIL_COLOR,
                         (LEFT, LOG_Y))
    canvas.draw_text(fit_line(font, hint, TEXT_WIDTH), TEXT_FONT, HINT_COLOR, (LEFT, HINT_Y))
    if label is not None:
        canvas.draw_text(fit_line(font, label, TEXT_WIDTH), TEXT_FONT, DETAIL_COLOR,
                         (LEFT, LABEL_Y))
