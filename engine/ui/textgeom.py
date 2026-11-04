"""Text field and on-screen keyboard geometry (F52 ``01`` §6.1, §6.2; ``04`` §4.5; P3).

Why this module exists: the field's parts (text inset, caret, counter, keyboard icon, note
tag), the letter cell, the horizontal scroll that keeps the caret in view, the click → caret
rule, and the keyboard panel are numbers that must hold at every text size. They are pure
(canvas units, no pygame), so the tests check them as tables.

Keyboard (C1, I-6): ``midbottom`` (640, 696), 1,040 wide, padding 16, gaps 8. Its height is
32 + E + H_b + 5 K + 6 × 8 with E = max(56, pitch(s)), K = max(56, s + 16), H_b F10's button
height and s the scaled ``button.text_size``: 472 at 100 % and 504 at 150 %. The echo row,
the page row (F21's ``PageRow``, 1,008 wide), a 10 × 4 grid, and the bottom row (◀ 1, ▶ 1,
Space 4, Delete 2, Done 2 key widths) fill it. A key is (1,008 − 9 × 8) / 10 = 93.6 wide.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from engine.ui.focus import Box
from engine.ui.layouts import BUTTON_HEIGHT, BUTTON_TEXT_SIZE, button_height, pitch, scaled

FIELD_MIN_W: Final = 160
FIELD_MIN_H: Final = 56
FIELD_PAD: Final = 16             # text from the box's left edge; caret margin; field height
TEXT_INSET: Final = 16
CARET_W: Final = 2
UNDERLINE: Final = 2              # composition, bare field and cell underlines
UNDERLINE_GAP: Final = 2          # below the baseline
ICON_SIZE: Final = (32, 24)
ICON_INSET: Final = 12            # from the field's right edge
COUNTER_GAP: Final = 8            # between the counter and the icon (or the right edge)
COUNTER_MAX_LENGTH: Final = 60    # the counter shows when max_length ≤ 60
COUNTER_MIN_SIZE: Final = 24
NOTE_GAP: Final = 8               # the note tag below the field
NOTE_MS: Final = 2000
CELL_MIN: Final = 40
CELL_PAD: Final = 8
BLINK_S: Final = 0.5              # 500 ms on, 500 ms off

KB_WIDTH: Final = 1040
KB_BOTTOM: Final = (640, 696)
KB_PAD: Final = 16
KB_GAP: Final = 8
KB_COLUMNS: Final = 10
KB_ROWS: Final = 4
KB_KEY_MIN: Final = 56
KB_ECHO_MIN: Final = 56
BOTTOM_KEYS: Final = (("left", 1), ("right", 1), ("space", 4), ("delete", 2), ("done", 2))


def field_height(text_size: int) -> int:
    """A field box's height: max(56, pitch + 16) at the (scaled) text size."""
    return max(FIELD_MIN_H, pitch(text_size) + FIELD_PAD)


def cell_side(text_size: int) -> int:
    """A letter cell's side: max(40, pitch + 8)."""
    return max(CELL_MIN, pitch(text_size) + CELL_PAD)


def counter_size(text_size: int) -> int:
    return max(COUNTER_MIN_SIZE, text_size - 4)


def icon_box(box: Box) -> Box:
    """The keyboard icon: 32 × 24, 12 inside the right edge, vertically centred."""
    w, h = ICON_SIZE
    return Box(box.right - ICON_INSET - w, box.y + (box.h - h) / 2, w, h)


def text_view(box: Box, *, icon: bool, counter_w: float = 0.0) -> tuple[float, float]:
    """The x range the text shows in: from 16 inside the left edge to the counter (or the
    icon, or 16 inside the right edge)."""
    right = icon_box(box).x - COUNTER_GAP if icon else box.right - TEXT_INSET
    if counter_w > 0:
        right -= counter_w + COUNTER_GAP
    left = box.x + TEXT_INSET
    return left, max(left, right)


def scroll_x(caret_x: float, text_w: float, view_w: float, scroll: float) -> float:
    """The text's new left shift so the caret (``caret_x`` from the text's start) stays in
    a view ``view_w`` wide, moving as little as possible and never past the text's ends."""
    if caret_x - scroll > view_w:
        scroll = caret_x - view_w
    if caret_x < scroll:
        scroll = caret_x
    return max(0.0, min(scroll, max(0.0, text_w - view_w)))


def caret_at(x: float, bounds: Sequence[float]) -> int:
    """The grapheme boundary nearest ``x``: ``bounds[i]`` is boundary ``i``'s x (sorted,
    ``bounds[0]`` the text's start). A tie goes left."""
    if not bounds:
        return 0
    best, best_d = 0, abs(x - bounds[0])
    for index, bx in enumerate(bounds):
        d = abs(x - bx)
        if d < best_d:
            best, best_d = index, d
    return best


@dataclass(frozen=True)
class KeyboardLayout:
    """The keyboard panel (module docstring). ``keys`` are the grid in reading order;
    ``bottom`` the bottom row's (name, box)."""
    panel: Box
    echo: Box
    page_row: Box
    keys: tuple[Box, ...]
    bottom: tuple[tuple[str, Box], ...]
    text_size: int
    key_h: int

    def bottom_box(self, name: str) -> Box:
        return dict(self.bottom)[name]


def keyboard_layout(scale: float = 1.0, *, text_size: int = BUTTON_TEXT_SIZE,
                    height: int = BUTTON_HEIGHT) -> KeyboardLayout:
    s = scaled(text_size, scale)
    echo_h = max(KB_ECHO_MIN, pitch(s))
    row_h = button_height(text_size, scale=scale, minimum=height)
    key_h = max(KB_KEY_MIN, s + 16)
    total = 2 * KB_PAD + echo_h + row_h + 5 * key_h + 6 * KB_GAP
    bx, by = KB_BOTTOM
    panel = Box(bx - KB_WIDTH / 2, by - total, KB_WIDTH, total)
    inner_x = panel.x + KB_PAD
    inner_w = KB_WIDTH - 2 * KB_PAD
    unit = (inner_w - (KB_COLUMNS - 1) * KB_GAP) / KB_COLUMNS
    y = panel.y + KB_PAD
    echo = Box(inner_x, y, inner_w, echo_h)
    y += echo_h + KB_GAP
    page_row = Box(inner_x, y, inner_w, row_h)
    y += row_h + KB_GAP
    keys = []
    for _row in range(KB_ROWS):
        for col in range(KB_COLUMNS):
            keys.append(Box(inner_x + col * (unit + KB_GAP), y, unit, key_h))
        y += key_h + KB_GAP
    bottom = []
    x = inner_x
    for name, span in BOTTOM_KEYS:
        w = span * unit + (span - 1) * KB_GAP
        bottom.append((name, Box(x, y, w, key_h)))
        x += w + KB_GAP
    return KeyboardLayout(panel, echo, page_row, tuple(keys), tuple(bottom), s, key_h)


__all__ = ["BLINK_S", "BOTTOM_KEYS", "CARET_W", "CELL_MIN", "COUNTER_MAX_LENGTH",
           "FIELD_MIN_H", "FIELD_MIN_W", "ICON_SIZE", "KB_GAP", "KeyboardLayout", "NOTE_GAP",
           "NOTE_MS", "TEXT_INSET", "UNDERLINE", "UNDERLINE_GAP", "caret_at", "cell_side",
           "counter_size", "field_height", "icon_box", "keyboard_layout", "scroll_x",
           "text_view"]
