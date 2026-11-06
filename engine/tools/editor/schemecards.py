"""The Color scheme page's card grid (F49 SPEC §4; PR-F49-06; AC-F49-11).

Why this module exists: an author picks a color scheme by looking at it. Each built-in
scheme (``schememodel.cards()``) is a card with four swatches (fill, border, accent, text),
its name and, on the scheme in use, the muted caption "In use". The cards are drawn on one
canvas and wrap to its width (at least one per row).

- A click or Space selects a card; the arrow keys move the selection through the grid;
  Enter or a double-click applies it (``on_apply``). Selecting only calls ``on_select``:
  nothing is written until the page applies.
- The selected card has a 2 px accent border; while the grid has keyboard focus, Studio's
  focus outline goes round it. Every chrome color comes from ``editor/theme.py``.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable, Sequence

from engine.tools.editor.schememodel import IN_USE, Card
from engine.tools.editor.theme import ROLES, THEME

# Sizes (px at 100 %, times the window's scale; SPEC §4).
CARD_WIDTH = 150                # 2026-11-05: two a row in a narrow pane
CARD_HEIGHT = 80
GAP = 8
SWATCH_WIDTH = 24
SWATCH_HEIGHT = 20
PAD = 10                        # inside a card
FOCUS_OUT = 3                   # the focus outline, outside the card's edge
ELLIPSIS = "…"


def fit_text(text: str, width: int, measure: Callable[[str], int]) -> str:
    """``text`` cut with "…" to fit ``width`` px (as ``measure`` measures it)."""
    if measure(text) <= width:
        return text
    while text and measure(text + ELLIPSIS) > width:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


class SchemeCards:
    """The grid of ``cards`` in ``parent``; ``widget`` is its canvas. ``selected`` is the
    picked card's id, ``in_use`` the id whose card says "In use" (None: none). A subclass
    (F60's ``kitcards``) changes the card size and draws its own ``_draw_card``."""

    card_width = CARD_WIDTH
    card_height = CARD_HEIGHT

    def __init__(self, parent: tk.Misc, cards: Sequence[Card], *, scale: float,
                 fonts: dict[str, tkfont.Font], selected: str | None, in_use: str | None,
                 on_select: Callable[[str], object], on_apply: Callable[[str], object]
                 ) -> None:
        self.cards = tuple(cards)
        self.scale = scale
        self.name_font = fonts["bodyStrong"]
        self.caption_font = fonts["small"]
        self.selected = selected
        self.in_use = in_use
        self.on_select = on_select
        self.on_apply = on_apply
        self.columns = 1
        background = THEME["editor.background"]
        self.widget = self.canvas = tk.Canvas(
            parent, background=background, highlightthickness=0, borderwidth=0,
            takefocus=1, height=self._px(self.card_height), width=self._px(self.card_width))
        canvas = self.canvas
        canvas.bind("<Configure>", lambda e: self._fit(e.width), add="+")
        canvas.bind("<Button-1>", self._click, add="+")
        canvas.bind("<Double-Button-1>", self._double, add="+")
        canvas.bind("<FocusIn>", lambda _e: self.draw(), add="+")
        canvas.bind("<FocusOut>", lambda _e: self.draw(), add="+")
        for key, (dx, dy) in {"<Left>": (-1, 0), "<Right>": (1, 0), "<Up>": (0, -1),
                              "<Down>": (0, 1)}.items():
            canvas.bind(key, lambda _e, dx=dx, dy=dy: (self.move(dx, dy), "break")[1])
        canvas.bind("<space>", lambda _e: (self._select_current(), "break")[1])
        for key in ("<Return>", "<KP_Enter>"):
            canvas.bind(key, lambda _e: (self._apply_current(), "break")[1])
        self.draw()

    def _px(self, value: float) -> int:
        return round(value * self.scale)

    # --- Layout -------------------------------------------------------------------------------

    def _fit(self, width: int) -> None:
        """Wrap the cards to ``width`` px (at least one a row)."""
        step = self._px(self.card_width + GAP)
        columns = max(1, (width - 2 * FOCUS_OUT + self._px(GAP)) // step)
        if columns != self.columns:
            self.columns = columns
            self.draw()

    @property
    def rows(self) -> int:
        return -(-len(self.cards) // self.columns)

    def card_box(self, index: int) -> tuple[int, int, int, int]:
        """Card ``index``'s ``(x0, y0, x1, y1)`` on the canvas."""
        row, column = divmod(index, self.columns)
        x0 = FOCUS_OUT + column * self._px(self.card_width + GAP)
        y0 = FOCUS_OUT + row * self._px(self.card_height + GAP)
        return x0, y0, x0 + self._px(self.card_width), y0 + self._px(self.card_height)

    def index_at(self, x: int, y: int) -> int | None:
        """The card under canvas point ``(x, y)``, or None (a gap, or past the last)."""
        for index in range(len(self.cards)):
            x0, y0, x1, y1 = self.card_box(index)
            if x0 <= x < x1 and y0 <= y < y1:
                return index
        return None

    def index_of(self, id_: str | None) -> int | None:
        return next((i for i, card in enumerate(self.cards) if card.id == id_), None)

    # --- Drawing ------------------------------------------------------------------------------

    def draw(self) -> None:
        """Draw every card (selection, "In use" and the focus outline as they are now)."""
        canvas = self.canvas
        canvas.delete("all")
        height = self.rows * self._px(self.card_height + GAP) - self._px(GAP) + 2 * FOCUS_OUT
        if int(canvas.cget("height")) != height:
            canvas.configure(height=height)
        try:
            focused = canvas.focus_get() is canvas
        except (KeyError, tk.TclError):           # a focused widget Tk can't name
            focused = False
        for index, card in enumerate(self.cards):
            self._draw_card(index, card, focused)

    def _draw_card(self, index: int, card: Card, focused: bool) -> None:
        canvas, px = self.canvas, self._px
        x0, y0, x1, y1 = self.card_box(index)
        chosen = card.id == self.selected
        tag = f"card:{card.id}"
        if chosen and focused:
            canvas.create_rectangle(x0 - FOCUS_OUT, y0 - FOCUS_OUT, x1 + FOCUS_OUT - 1,
                                    y1 + FOCUS_OUT - 1, outline=THEME["focusBorder"],
                                    width=1, tags=(tag, "focus"))
        edge = 2 if chosen else 1
        canvas.create_rectangle(x0, y0, x1 - 1, y1 - 1, fill=THEME["card.background"],
                                outline=ROLES["accent"] if chosen else THEME["border"],
                                width=edge, tags=(tag,))
        left, top = x0 + px(PAD), y0 + px(PAD)
        for n, color in enumerate(card.swatches):
            sx = left + n * px(SWATCH_WIDTH + GAP)
            canvas.create_rectangle(sx, top, sx + px(SWATCH_WIDTH), top + px(SWATCH_HEIGHT),
                                    fill=color, outline=THEME["border"], width=1,
                                    tags=(tag, "swatch"))
        room = px(CARD_WIDTH - 2 * PAD)
        name_top = top + px(SWATCH_HEIGHT + 6)
        canvas.create_text(left, name_top, anchor="nw", fill=THEME["foreground"],
                           font=self.name_font, tags=(tag, "name"),
                           text=fit_text(card.name, room, self.name_font.measure))
        if card.id == self.in_use:
            canvas.create_text(left, name_top + self.name_font.metrics("linespace"),
                               anchor="nw", fill=THEME["muted"], font=self.caption_font,
                               text=IN_USE, tags=(tag, "in_use"))

    # --- Input --------------------------------------------------------------------------------

    def set_cards(self, cards: Sequence[Card]) -> None:
        """New cards (an imported palette's card came or went, or changed): redrawn."""
        cards = tuple(cards)
        if cards != self.cards:
            self.cards = cards
            self._fit(self.canvas.winfo_width())
            self.draw()

    def set_state(self, selected: str | None, in_use: str | None) -> None:
        """Show ``selected`` and ``in_use`` (no callbacks)."""
        if (selected, in_use) != (self.selected, self.in_use):
            self.selected, self.in_use = selected, in_use
            self.draw()

    def select(self, id_: str) -> None:
        """Select card ``id_`` as a click would."""
        if id_ != self.selected:
            self.selected = id_
            self.draw()
            self.on_select(id_)

    def move(self, dx: int, dy: int) -> None:
        """An arrow key: the selection moves ``dx`` cards along a row or ``dy`` rows (it
        stays at the grid's edge)."""
        at = self.index_of(self.selected)
        if at is None:
            self.select(self.cards[0].id)
            return
        if dx:
            to = at + dx
        else:
            to = at + dy * self.columns
        if 0 <= to < len(self.cards):
            self.select(self.cards[to].id)

    def _click(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        index = self.index_at(event.x, event.y)
        if index is not None:
            self.select(self.cards[index].id)

    def _double(self, event: tk.Event) -> None:
        index = self.index_at(event.x, event.y)
        if index is not None:
            self.select(self.cards[index].id)
            self.on_apply(self.cards[index].id)

    def _select_current(self) -> None:
        if self.selected is None:
            self.move(0, 0)
        else:
            self.on_select(self.selected)

    def _apply_current(self) -> None:
        if self.selected is not None:
            self.on_apply(self.selected)


__all__ = ["CARD_HEIGHT", "CARD_WIDTH", "GAP", "SchemeCards", "fit_text"]
