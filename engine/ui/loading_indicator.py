"""F10's loading indicator (C10, UI-F10-08): the ``loading`` word and three dots at the
bottom right (1264, 708).

Why this module exists: the story load (``app/loading.py``'s ``StoryLoadScreen``) and F11's
load of a save over 1 MiB (G3: drawn once in the cell's "Loading…" badge frame, because the
read is one step) draw the same indicator, so it is drawn in one place (F11 ``07`` I-5:
reuse, not copies). ``ui`` holds it because the Load page can't import ``engine.app``.

The word is drawn with the bundled Noto Sans Regular at 20 (theme fonts are checked only at
``install_ui``) in ``[theme.title.loading] text_color``; three 6×6 dots, 8 after the text,
6 apart. One dot (``bright``) is at full opacity and the others at 30%; ``bright`` None (under
``[effects] reduce``) draws all three full.
"""

from typing import TYPE_CHECKING, Final

from engine.render.frames import build_ellipse
from engine.render.text import FontSpec

if TYPE_CHECKING:
    from engine.render.canvas import Canvas

LOADING_DOT_S: Final = 0.3                     # each dot is the bright one for 300 ms
LOADING_DIM: Final = 0.3                       # the other dots' opacity
LOADING_FONT: Final = FontSpec(None, 20)       # bundled Noto Sans Regular
LOADING_RIGHT, LOADING_BOTTOM = 1264, 708
LOADING_DOT: Final = 6                         # three 6×6 dots, 8 after the text, 6 apart
LOADING_DOT_GAP: Final = 6
LOADING_TEXT_GAP: Final = 8


def draw_loading_indicator(canvas: "Canvas", word: str, color: tuple[int, int, int], *,
                           bright: int | None) -> None:
    """The ``word`` and three dots, right-aligned to x 1264 above y 708; dot ``bright``
    (0–2) at full opacity, or all three when None."""
    dots_w = 3 * LOADING_DOT + 2 * LOADING_DOT_GAP
    _, top, _, height = canvas.draw_text(
        word, LOADING_FONT, color,
        (LOADING_RIGHT - dots_w - LOADING_TEXT_GAP, LOADING_BOTTOM), anchor="bottomright")
    surface = canvas.surface
    assert surface is not None
    y = top + height / 2 - LOADING_DOT / 2
    for k in range(3):
        x = LOADING_RIGHT - dots_w + k * (LOADING_DOT + LOADING_DOT_GAP)
        rect = canvas.rect_to_px((x, y, LOADING_DOT, LOADING_DOT))
        dot = build_ellipse(rect.size, color)
        if bright is not None and k != bright:
            dot.set_alpha(round(255 * LOADING_DIM))
        surface.blit(dot, rect.topleft)


__all__ = ["LOADING_BOTTOM", "LOADING_DIM", "LOADING_DOT", "LOADING_DOT_GAP", "LOADING_DOT_S",
           "LOADING_FONT", "LOADING_RIGHT", "LOADING_TEXT_GAP", "draw_loading_indicator"]
