"""The Kit page's card grid (F60; specs/F60-genre-kits/SPEC.md).

Why this module exists: an author picks a genre kit by looking at it. Each card
(``kitmodel.cards()``) draws a small stage in the kit's scheme colors: a text box at the
bottom, and a mock meter in the kit's look (bar, number, hearts, pips or dial) in its
corner, labelled with the kit's first meter. Under it, the kit's name and, on the kit in
use, "In use".

Selection, the arrow keys, Enter and a double-click work as on the Color scheme page:
``KitCards`` is ``schemecards.SchemeCards`` with bigger cards and its own drawing. Chrome
colors come from ``editor/theme.py``; the preview's colors are the kit's scheme's.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import math
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Sequence

from engine.tools.editor.kitmodel import IN_USE, KitCard
from engine.tools.editor.schemecards import PAD, SchemeCards, fit_text
from engine.tools.editor.theme import ROLES, THEME

# Sizes (px at 100 %, times the window's scale).
CARD_WIDTH = 176
PREVIEW_HEIGHT = 84             # the drawn stage, as wide as the card's inside
CARD_HEIGHT = PAD + PREVIEW_HEIGHT + 6 + 38 + PAD
TEXTBOX_HEIGHT = 24
METER_WIDTH = 66
INSET = 5                       # the meter's distance from the stage's edges
SHOWN = 0.6                     # how full the mock meter is
STEPS = 5                       # hearts and pips


class KitCards(SchemeCards):
    """The grid of kit ``cards`` (``kitmodel.KitCard``); otherwise as ``SchemeCards``."""

    card_width = CARD_WIDTH
    card_height = CARD_HEIGHT

    def __init__(self, parent: tk.Misc, cards: Sequence[KitCard], **kwargs) -> None:
        small = kwargs["fonts"]["small"]
        scale = kwargs["scale"]
        self.tiny = tkfont.Font(root=parent, family=small.actual("family"),
                                size=-max(8, round(10 * scale)))
        self.tiny_bold = tkfont.Font(root=parent, family=small.actual("family"),
                                     size=-max(8, round(10 * scale)), weight="bold")
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

    # --- The drawn preview ----------------------------------------------------------------------

    def _draw_preview(self, card: KitCard, tag: str, x0: int, y0: int, x1: int, y1: int
                      ) -> None:
        """The small stage: the scheme's soft color behind, its text box at the bottom (a
        name tab, two lines of text), and the mock meter in its corner."""
        canvas, px = self.canvas, self._px
        fill, text, border, accent, soft, track = card.colors
        tags = (tag, "preview")
        canvas.create_rectangle(x0, y0, x1, y1, fill=soft, outline=THEME["border"], width=1,
                                tags=tags)
        box_top = y1 - px(TEXTBOX_HEIGHT)
        canvas.create_rectangle(x0 + px(4), box_top, x1 - px(4), y1 - px(4), fill=fill,
                                outline=border, width=1, tags=tags)
        canvas.create_rectangle(x0 + px(10), box_top - px(5), x0 + px(36), box_top + px(2),
                                fill=accent, outline="", tags=tags)
        for n, share in enumerate((0.72, 0.48)):
            ly = box_top + px(7 + 6 * n)
            canvas.create_rectangle(x0 + px(10), ly, x0 + px(10) + round(
                (x1 - x0 - px(24)) * share), ly + px(2), fill=text, outline="", tags=tags)
        self._draw_meter(card, tags, x0, y0, x1, box_top - px(4))

    def _draw_meter(self, card: KitCard, tags: tuple[str, ...], x0: int, y0: int, x1: int,
                    y1: int) -> None:
        """The mock meter's box in ``card.place`` inside ``(x0, y0)``–``(x1, y1)``."""
        canvas, px = self.canvas, self._px
        fill, text, border, accent, _soft, track = card.colors
        line = self.tiny.metrics("linespace")
        row = px(10)
        height = px(4) + (line if card.label else 0) + row + px(4)
        width = px(METER_WIDTH)
        left = x0 + px(INSET) if card.place.endswith("left") else x1 - px(INSET) - width
        top = y0 + px(INSET) if card.place.startswith("top") else y1 - height
        tags = (*tags, "meter", f"look:{card.look}", f"place:{card.place}")
        canvas.create_rectangle(left, top, left + width, top + height, fill=fill,
                                outline=border, width=1, tags=tags)
        inner_left, inner_right = left + px(5), left + width - px(5)
        y = top + px(4)
        if card.label:
            canvas.create_text(inner_left, y, anchor="nw", fill=text, font=self.tiny,
                               text=fit_text(card.label, inner_right - inner_left,
                                             self.tiny.measure), tags=(*tags, "label"))
            y += line
        self._draw_look(card.look, tags, inner_left, y, inner_right, y + row, accent, track)

    def _draw_look(self, look: str, tags: tuple[str, ...], x0: int, y0: int, x1: int,
                   y1: int, accent: str, track: str) -> None:
        canvas, px = self.canvas, self._px
        mid = (y0 + y1) // 2
        if look == "bar":
            canvas.create_rectangle(x0, mid - px(2), x1, mid + px(2), fill=track, outline="",
                                    tags=tags)
            canvas.create_rectangle(x0, mid - px(2), x0 + round((x1 - x0) * SHOWN),
                                    mid + px(2), fill=accent, outline="", tags=tags)
        elif look == "number":
            canvas.create_text(x0, mid, anchor="w", fill=accent, font=self.tiny_bold,
                               text="6", tags=tags)
            canvas.create_text(x0 + self.tiny_bold.measure("6 "), mid, anchor="w",
                               fill=track, font=self.tiny, text="/ 10", tags=tags)
        elif look in ("hearts", "pips"):
            step = (x1 - x0) // STEPS
            size = min(step - px(2), y1 - y0)
            for n in range(STEPS):
                color = accent if n < round(STEPS * SHOWN) else track
                cx = x0 + n * step + size // 2
                if look == "pips":
                    r = size // 2 - px(1)
                    canvas.create_oval(cx - r, mid - r, cx + r, mid + r, fill=color,
                                       outline="", tags=tags)
                else:
                    canvas.create_polygon(_heart(cx, mid, size), fill=color, outline="",
                                          smooth=True, tags=tags)
        else:                                                            # dial
            r = y1 - y0
            cx, cy = x0 + r, y1
            box = (cx - r, cy - r, cx + r, cy + r)
            canvas.create_arc(*box, start=0, extent=180, style="arc", outline=track,
                              width=px(3), tags=tags)
            canvas.create_arc(*box, start=180, extent=-180 * SHOWN, style="arc",
                              outline=accent, width=px(3), tags=tags)
            angle = math.pi * (1 - SHOWN)
            canvas.create_line(cx, cy, cx + round(r * 0.8 * math.cos(angle)),
                               cy - round(r * 0.8 * math.sin(angle)), fill=accent,
                               width=max(1, px(1)), tags=tags)
            canvas.create_text(cx + r + px(6), mid, anchor="w", fill=accent,
                               font=self.tiny_bold, text="60%", tags=tags)


def _heart(cx: int, cy: int, size: int) -> list[int]:
    """A heart's points (drawn smooth) of about ``size`` px, centred on ``(cx, cy)``."""
    h = size / 2
    points = ((0, -0.35), (0.35, -0.9), (1, -0.55), (0.75, 0.15), (0, 0.9), (-0.75, 0.15),
              (-1, -0.55), (-0.35, -0.9))
    return [round(v) for x, y in points for v in (cx + x * h, cy + y * h)]


__all__ = ["CARD_HEIGHT", "CARD_WIDTH", "KitCards"]
