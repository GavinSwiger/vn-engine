"""The Kit page's card grid (F60; specs/F60-genre-kits/SPEC.md).

Why this module exists: an author picks a genre kit by looking at it. Each card
(``kitmodel.cards()``) draws a small stage in the kit's scheme colors: a text box at the
bottom, and a mock meter in the kit's look (bar, number, hearts, pips or dial) in its
corner, labelled with the kit's first meter (drawn by ``meterdraw``, shared with Database ▸
Meters' preview). Under it, the kit's name and, on the kit in
use, "In use".

Selection, the arrow keys, Enter and a double-click work as on the Color scheme page:
``KitCards`` is ``schemecards.SchemeCards`` with bigger cards and its own drawing. Chrome
colors come from ``editor/theme.py``; the preview's colors are the kit's scheme's.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Sequence

from engine.tools.editor import meterdraw
from engine.tools.editor.kitmodel import IN_USE, KitCard
from engine.tools.editor.schemecards import PAD, SchemeCards, fit_text
from engine.tools.editor.theme import ROLES, THEME

# Sizes (px at 100 %, times the window's scale).
CARD_WIDTH = 176
PREVIEW_HEIGHT = 84             # the drawn stage, as wide as the card's inside
CARD_HEIGHT = PAD + PREVIEW_HEIGHT + 6 + 38 + PAD
METER_WIDTH = 66


class KitCards(SchemeCards):
    """The grid of kit ``cards`` (``kitmodel.KitCard``); otherwise as ``SchemeCards``."""

    card_width = CARD_WIDTH
    card_height = CARD_HEIGHT

    def __init__(self, parent: tk.Misc, cards: Sequence[KitCard], **kwargs) -> None:
        self.tiny, self.tiny_bold = meterdraw.fonts(parent, kwargs["fonts"]["small"],
                                                    kwargs["scale"])
        self.painter: meterdraw.MeterPainter | None = None
        super().__init__(parent, cards, **kwargs)                     # type: ignore[arg-type]

    def _draw_card(self, index: int, card: KitCard,                   # type: ignore[override]
                   focused: bool) -> None:
        canvas, px = self.canvas, self._px
        x0, y0, x1, y1 = self.card_box(index)
        chosen = card.id == self.selected
        tag = f"card:{card.id}"
        if chosen and focused:
            out = 3
            canvas.create_rectangle(x0 - out, y0 - out, x1 + out - 1, y1 + out - 1,
                                    outline=THEME["focusBorder"], width=1, tags=(tag, "focus"))
        canvas.create_rectangle(x0, y0, x1 - 1, y1 - 1, fill=THEME["card.background"],
                                outline=ROLES["accent"] if chosen else THEME["border"],
                                width=2 if chosen else 1, tags=(tag,))
        left, top = x0 + px(PAD), y0 + px(PAD)
        right = x1 - px(PAD)
        self._draw_preview(card, tag, left, top, right, top + px(PREVIEW_HEIGHT))
        name_top = top + px(PREVIEW_HEIGHT + 6)
        canvas.create_text(left, name_top, anchor="nw", fill=THEME["foreground"],
                           font=self.name_font, tags=(tag, "name"),
                           text=fit_text(card.name, right - left, self.name_font.measure))
        if card.id == self.in_use:
            canvas.create_text(left, name_top + self.name_font.metrics("linespace"),
                               anchor="nw", fill=THEME["muted"], font=self.caption_font,
                               text=IN_USE, tags=(tag, "in_use"))

    # --- The drawn preview (meterdraw) ---------------------------------------------------------

    def _draw_preview(self, card: KitCard, tag: str, x0: int, y0: int, x1: int, y1: int
                      ) -> None:
        if self.painter is None:
            self.painter = meterdraw.MeterPainter(self.canvas, self._px, self.tiny,
                                                  self.tiny_bold, meter_width=METER_WIDTH)
        self.painter.stage((tag,), x0, y0, x1, y1, card.colors, card.look, card.place,
                           card.label)


__all__ = ["CARD_HEIGHT", "CARD_WIDTH", "KitCards"]
