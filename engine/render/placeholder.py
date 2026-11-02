"""The missing-image placeholder: a magenta-and-black checkerboard with the path on it.

Why this module exists: a missing, broken, or blocked image must never stop the game, and
the author must see at a glance which file is wrong, without relying on color alone
(PR-F01-56, accessibility "Not color alone"). The label is the reference as echoed
(escaped, redacted, at most 120 characters), or ``blocked path: <ref>`` for a rejected
reference (PR-F01-55).
"""

from typing import TYPE_CHECKING

import pygame

from engine.render.text import FontSpec, fit_line, wrap_lines

if TYPE_CHECKING:
    from engine.render.canvas import Canvas

PLACEHOLDER_SIZE = (256, 256)          # canvas units == source pixels
SQUARE = 32
MAGENTA = (0xFF, 0x00, 0xFF)
BLACK = (0x00, 0x00, 0x00)
WHITE = (0xFF, 0xFF, 0xFF)
LABEL_WIDTH = 232                      # 12 px margin on each side
LABEL_MAX_LINES = 6
LABEL_FONT_PX = 20
BAND_PADDING = 6
STAGE_BAND_PADDING = 8                 # F04's stage placeholders (06 D2, F04 I-11)
LABEL_FONT = FontSpec(None, LABEL_FONT_PX)


def make_placeholder(label: str, font: "pygame.font.Font") -> pygame.Surface:
    """A new opaque 256×256 surface: 32 px #FF00FF / #000000 squares, and a centered
    black band with ``label`` in white, wrapped to 232 px, at most 6 lines (the last one
    shortened with ``…``). ``font`` is the default font at 20 px."""
    width, height = PLACEHOLDER_SIZE
    surface = pygame.Surface(PLACEHOLDER_SIZE)
    surface.fill(BLACK)
    for row in range(0, height, SQUARE):
        for column in range(0, width, SQUARE):
            if (row // SQUARE + column // SQUARE) % 2 == 0:
                surface.fill(MAGENTA, (column, row, SQUARE, SQUARE))
    lines = wrap_lines(font, label, LABEL_WIDTH)
    if len(lines) > LABEL_MAX_LINES:
        rest = " ".join(lines[LABEL_MAX_LINES - 1:])
        lines = lines[:LABEL_MAX_LINES - 1] + [fit_line(font, rest, LABEL_WIDTH)]
    line_height = font.get_linesize()
    band_height = len(lines) * line_height + 2 * BAND_PADDING
    band_top = (height - band_height) // 2
    surface.fill(BLACK, (0, band_top, width, band_height))
    y = band_top + BAND_PADDING
    for line in lines:
        if line:
            text = font.render(line, True, WHITE, BLACK)
            surface.blit(text, ((width - text.get_width()) // 2, y))
        y += line_height
    return surface


def draw_placeholder(canvas: "Canvas", rect: tuple[float, float, float, float], label: str, *,
                     wrap: float, band_center_y: float) -> None:
    """F04's stage placeholder (``04`` §7.4, UI-F04-09 to 11), drawn through ``canvas`` so it
    is rasterized at device size and clipped to the canvas: ``rect`` (canvas units) filled
    ``#FF00FF`` with ``#000000`` 32-unit squares where row + column is odd, then a black
    band the full width of ``rect``, ``lines × linesize + 16`` units tall and centered on
    ``band_center_y``, with ``label`` in white at 20 units, wrapped at ``wrap`` units, at
    most 6 lines (the last shortened with ``…``), centered in the band."""
    x, y, width, height = rect
    canvas.fill(MAGENTA, rect)
    rows = int(-(-height // SQUARE))
    columns = int(-(-width // SQUARE))
    for row in range(rows):
        for column in range(columns):
            if (row + column) % 2:
                left, top = x + column * SQUARE, y + row * SQUARE
                canvas.fill(BLACK, (left, top, min(SQUARE, x + width - left),
                                    min(SQUARE, y + height - top)))
    lines = canvas.layout_lines(label, LABEL_FONT, wrap, LABEL_MAX_LINES)
    line_size = canvas.font_handle(LABEL_FONT, LABEL_FONT.size).font.get_linesize()
    band_height = len(lines) * line_size + 2 * STAGE_BAND_PADDING
    canvas.fill(BLACK, (x, band_center_y - band_height / 2, width, band_height))
    canvas.draw_text(label, LABEL_FONT, WHITE, (x + width / 2, band_center_y), anchor="center",
                     max_width=wrap, align="center", max_lines=LABEL_MAX_LINES)
