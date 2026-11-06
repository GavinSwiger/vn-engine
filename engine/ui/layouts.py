"""Pure layout and fit rules for F10's screens (F10 ``04`` §3.1, §7.7.3, §7.8, §7.9; ``03``).

Why this module exists: the title column, the game-menu sidebar, the confirm dialog, and
the quick-menu pill each have a fit rule (what gives way when text grows to 150 % or an
author adds entries). Keeping them as plain functions of numbers, with text measured through
an injected ``measure(text, size) -> width`` (reference metrics, canvas units), lets every
worked number in ``03-ui`` be checked without a display or a font (``06`` §0.3: M20).
The title column and the sidebar share one column fit (``fit_column``, F23 ``07`` C3 with
I-3); F23's minigame frame is ``minigame_frame`` (F23 ``04`` §7.11).

Sizes passed in are theme token values (unscaled); ``scale`` is F16's text scale. Row
heights shared with the widgets live here too: pitch = round(1.4 × size) (UI-F05-02),
button height H_b = max(``button.height``, pitch + 16), list row max(48, pitch + 8), slider
row 16 + pitch + 36.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

from engine.core.constants import CANVAS_SIZE
from engine.core.graphemes import graphemes
from engine.render.text import ELLIPSIS
from engine.render.textlayout import LINE_PITCH
from engine.ui.focus import Box

Measure = Callable[[str, int], float]        # (text, size) → width in canvas units

CANVAS_W, CANVAS_H = CANVAS_SIZE

# --- Widgets (03 widget table) -----------------------------------------------------------
BUTTON_HEIGHT = 56          # button.height default
BUTTON_GAP = 12             # button.gap default
BUTTON_TEXT_SIZE = 28       # button.text_size default
FIT_GAP = 4                 # the gap every column falls back to when it does not fit
LIST_ROW_HEIGHT = 48        # list.row_height default
SCROLLBAR_LANE = 20         # lane width at the list's right, only when rows overflow
SCROLLBAR_MIN_THUMB = 32
SLIDER_BAR_LEFT = 32        # bar x range: [box.x + 32, box.right − 104]
SLIDER_BAR_RIGHT = 104

# --- Title (UI-F10-07) -------------------------------------------------------------------
TITLE_LEFT = 80
TITLE_LOGO = Box(TITLE_LEFT, 48, 560, 200)
TITLE_COLUMN_TOP = 288
TITLE_COLUMN_LIMIT = 688    # the column must end by this y; else anchored bottom-left here
TITLE_LOGO_GAP = 24         # a shrunk logo box ends this far above the column
TITLE_LOGO_MIN_H = 80
TITLE_BUTTON_WIDTH = 320    # title.button_width default

# --- Game menu (UI-F10-09) ---------------------------------------------------------------
MENU_MARGIN = 24
SIDEBAR = Box(MENU_MARGIN, MENU_MARGIN, 336, CANVAS_H - 2 * MENU_MARGIN)
SIDEBAR_PADDING = 16        # the column may use the sidebar's height minus this each side
MENU_BUTTON_WIDTH = 288     # menu.button_width default
CONTENT_PANEL = Box(384, MENU_MARGIN, CANVAS_W - 384 - MENU_MARGIN, CANVAS_H - 2 * MENU_MARGIN)
PAGE_HEADING = (416, 56)
PAGE_BODY = Box(416, 112, 808, 552)

# --- Confirm (UI-F10-11) -----------------------------------------------------------------
CONFIRM_WIDTH = 640         # confirm.width default
CONFIRM_PAD_Y = 40          # above the message and below the buttons
CONFIRM_MESSAGE_INSET = 48  # the message wraps at width − 96
CONFIRM_ROW_GAP = 32        # message → buttons, and between Yes and No
CONFIRM_BUTTON_WIDTH = 200  # confirm.button_width default
CONFIRM_BUTTON_MAX = 280
CONFIRM_LABEL_PAD = 64      # a button is at least label + 64 wide
CONFIRM_MAX_LINES = 6       # the message: at most 6 lines, then smaller text, then "…"
PANEL_TEXT_SIZE = 28        # panel.text_size default
TEXT_MIN_SIZE = 24          # fit rules step text down by 2, not below 24 (UI-F10-02, 11)
TEXT_STEP = 2

# --- Quick menu (UI-F10-10, 04 §7.8, I-4) ------------------------------------------------
QM_TEXT_SIZE = 20           # quick_menu.text_size default
QM_SIZE_RANGE = (20, 24)
QM_SIDE_PADDING = 12        # quick_menu.side_padding default
QM_TIGHT_PADDING = 4
QM_BOTTOM_GAP = 2           # quick_menu.bottom_gap default: pill bottom at 718
QM_STRIP = 32               # textbox.bottom_gap default: the strip below the box
QM_END = 4                  # the end items each own 4 units of the pill
QM_MAX_WIDTH = CANVAS_W - 40


def pitch(size: float) -> int:
    """Line pitch: round(1.4 × size)."""
    return round(LINE_PITCH * size)


def scaled(size: float, scale: float = 1.0) -> int:
    """A token size at F16's text scale (0.5 rounds up)."""
    return math.floor(size * scale + 0.5)


def button_height(text_size: int = BUTTON_TEXT_SIZE, *, scale: float = 1.0,
                  minimum: int = BUTTON_HEIGHT) -> int:
    """H_b = max(``button.height``, pitch + 16)."""
    return max(minimum, pitch(scaled(text_size, scale)) + 16)


def toggle_row_height(text_size: int = PANEL_TEXT_SIZE, *, scale: float = 1.0,
                      minimum: int = BUTTON_HEIGHT) -> int:
    return button_height(text_size, scale=scale, minimum=minimum)


def slider_row_height(text_size: int = PANEL_TEXT_SIZE, *, scale: float = 1.0) -> int:
    """16 + pitch + 36: the label line above a 28-tall bar band."""
    return 16 + pitch(scaled(text_size, scale)) + 36


def list_row_height(text_size: int = PANEL_TEXT_SIZE, *, scale: float = 1.0,
                    minimum: int = LIST_ROW_HEIGHT) -> int:
    return max(minimum, pitch(scaled(text_size, scale)) + 8)


def column(n: int, x: float, top: float, w: float, h: float, gap: float) -> tuple[Box, ...]:
    """``n`` boxes ``w`` × ``h`` stacked from ``top``, ``gap`` apart."""
    return tuple(Box(x, top + i * (h + gap), w, h) for i in range(n))


def column_height(n: int, h: float, gap: float) -> float:
    return 0 if n <= 0 else n * h + (n - 1) * gap


def cut_to_width(text: str, width: float, size: int, measure: Measure) -> str:
    """``text`` if it fits ``width``; else its longest grapheme prefix + "…" that fits (never
    splitting a cluster). Binary search: O(log n) measurements."""
    if measure(text, size) <= width:
        return text
    parts = graphemes(text)
    return "".join(parts[:_longest_prefix(parts, width, size, measure, ELLIPSIS)]) + ELLIPSIS


def _longest_prefix(parts: list[str], width: float, size: int, measure: Measure,
                    suffix: str = "") -> int:
    """The most leading graphemes of ``parts`` that fit ``width`` with ``suffix`` (0 if
    none). Binary search."""
    low, high = 0, len(parts)
    while low < high:
        mid = (low + high + 1) // 2
        if measure("".join(parts[:mid]) + suffix, size) <= width:
            low = mid
        else:
            high = mid - 1
    return low


def _wrap(text: str, width: float, size: int, measure: Measure) -> list[tuple[str, int]]:
    """Greedy word wrap at spaces; a newline is a hard break; a word wider than ``width``
    breaks between graphemes (at least one per line), never inside a cluster. Each line comes
    with the index in ``text`` where it starts."""
    out: list[tuple[str, int]] = []
    offset = 0
    for paragraph in text.split("\n"):
        line, line_start, pos = "", offset, offset
        for word in paragraph.split(" "):
            word_start = pos
            pos += len(word) + 1
            candidate = word if not line else f"{line} {word}"
            if measure(candidate, size) <= width:
                if not line:
                    line_start = word_start
                line = candidate
                continue
            if line:
                out.append((line, line_start))
            line, line_start = word, word_start
            while measure(line, size) > width:
                parts = graphemes(line)
                if len(parts) <= 1:
                    break
                k = max(1, min(len(parts) - 1, _longest_prefix(parts, width, size, measure)))
                head = "".join(parts[:k])
                out.append((head, line_start))
                line_start += len(head)
                line = line[len(head):]
        out.append((line, line_start))
        offset += len(paragraph) + 1
    return out


def wrap_text(text: str, width: float, size: int, measure: Measure) -> list[str]:
    """``text`` broken into lines no wider than ``width`` (see ``_wrap``)."""
    return [line for line, _ in _wrap(text, width, size, measure)]


@dataclass(frozen=True)
class MessageFit:
    lines: tuple[str, ...]
    size: int
    truncated: bool         # the last line ends in "…" (W68's condition)


def fit_message(text: str, width: float, size: int, measure: Measure, *,
                max_lines: int = CONFIRM_MAX_LINES, min_size: int = TEXT_MIN_SIZE,
                step: int = TEXT_STEP) -> MessageFit:
    """The confirm message's fit (03 "Confirm dialog", UI-F10-11): wrapped at ``width`` in at
    most ``max_lines`` lines; else the size steps down by ``step`` (not below ``min_size``);
    else the last line is cut with "…" at the smallest size."""
    sizes = [size]
    while sizes[-1] - step >= min(min_size, size):
        sizes.append(sizes[-1] - step)
    for candidate in sizes:
        wrapped = _wrap(text, width, candidate, measure)
        if len(wrapped) <= max_lines:
            return MessageFit(tuple(line for line, _ in wrapped), candidate, False)
    smallest = sizes[-1]
    wrapped = _wrap(text, width, smallest, measure)
    kept = [line for line, _ in wrapped[:max_lines - 1]]
    rest = text[wrapped[max_lines - 1][1]:].replace("\n", " ")
    kept.append(cut_to_width(rest, width, smallest, measure))
    return MessageFit(tuple(kept), smallest, True)


# --- Column fit (F23 07 C3 with I-3: one rule for the title column and the sidebar) -------

FIT_ROW_MIN = 48            # step 2's button height floor: max(48, pitch + 8)
FIT_ROW_PAD = 8


class FitStep(IntEnum):
    """The last column-fit step a layout needed. ``ANCHOR`` is the title's step 1b; the
    sidebar never uses it. Values keep F10's title numbering (0, 1, 2)."""
    DESIGNED = 0            # as designed
    GAPS = 1                # (1) gaps become 4
    ANCHOR = 2              # (1b) title only: bottom-anchored, logo box ≥ 80, 24 above
    HEIGHT = 3              # (2) button height max(48, pitch + 8)
    LABEL = 4               # (3) the label size steps down by 2, not below 24


@dataclass(frozen=True)
class ColumnFit:
    step: FitStep
    button_height: int
    gap: int
    text_size: int          # the label size to draw at (already at the text scale)

    def height(self, n: int) -> float:
        return column_height(n, self.button_height, self.gap)


def fit_column(n: int, room: float, *, scale: float = 1.0, text_size: int = BUTTON_TEXT_SIZE,
               height: int = BUTTON_HEIGHT, gap: int = BUTTON_GAP,
               anchored_room: float | None = None) -> ColumnFit:
    """The shared column fit (F23 ``07`` §2.1 C3, I-3; ``03`` "Sidebar fit"): ``n`` buttons
    must fit ``room`` canvas units. Each step applies only if still needed: (1) gaps become 4;
    (1b) only with ``anchored_room`` (the title's bottom anchor), the room becomes that;
    (2) button height becomes max(48, pitch + 8); (3) the label size steps down by 2, not
    below 24. When nothing fits, the last step's numbers are returned (the column overflows).
    """
    size = scaled(text_size, scale)
    h = button_height(text_size, scale=scale, minimum=height)
    g = gap

    def fits() -> bool:
        return column_height(n, h, g) <= room

    if fits():
        return ColumnFit(FitStep.DESIGNED, h, g, size)
    g = min(gap, FIT_GAP)
    if fits():
        return ColumnFit(FitStep.GAPS, h, g, size)
    if anchored_room is not None:
        room = anchored_room
        if fits():
            return ColumnFit(FitStep.ANCHOR, h, g, size)
    h = min(h, max(FIT_ROW_MIN, pitch(size) + FIT_ROW_PAD))
    step = FitStep.HEIGHT
    while not fits() and size - TEXT_STEP >= TEXT_MIN_SIZE:
        size -= TEXT_STEP
        h = min(h, max(FIT_ROW_MIN, pitch(size) + FIT_ROW_PAD))
        step = FitStep.LABEL
    return ColumnFit(step, h, g, size)


# --- Title -------------------------------------------------------------------------------

TITLE_ANCHORED_ROOM = TITLE_COLUMN_LIMIT - (TITLE_LOGO.y + TITLE_LOGO_MIN_H + TITLE_LOGO_GAP)


@dataclass(frozen=True)
class TitleLayout:
    buttons: tuple[Box, ...]
    logo: Box
    button_height: int
    gap: int
    step: FitStep           # 0 as designed, 1 gaps 4, 2 anchored, 3 height, 4 label size
    text_size: int          # the label size (at the text scale) the column's labels use


def title_layout(n: int, *, scale: float = 1.0, text_size: int = BUTTON_TEXT_SIZE,
                 height: int = BUTTON_HEIGHT, width: int = TITLE_BUTTON_WIDTH,
                 gap: int = BUTTON_GAP) -> TitleLayout:
    """The title column of ``n`` entries at (80, 288), fitted by ``fit_column``: from step 1b
    on, the column anchors bottom-left at (80, 688) and the logo box ends 24 above it (at
    least 80 tall), so the anchored room is 688 − (48 + 80 + 24) = 536."""
    fit = fit_column(n, TITLE_COLUMN_LIMIT - TITLE_COLUMN_TOP, scale=scale,
                     text_size=text_size, height=height, gap=gap,
                     anchored_room=TITLE_ANCHORED_ROOM)
    h, g = fit.button_height, fit.gap
    if fit.step < FitStep.ANCHOR:
        return TitleLayout(column(n, TITLE_LEFT, TITLE_COLUMN_TOP, width, h, g),
                           TITLE_LOGO, h, g, fit.step, fit.text_size)
    top = TITLE_COLUMN_LIMIT - fit.height(n)
    logo_h = max(TITLE_LOGO_MIN_H, min(TITLE_LOGO.h, top - TITLE_LOGO_GAP - TITLE_LOGO.y))
    logo = Box(TITLE_LOGO.x, TITLE_LOGO.y, TITLE_LOGO.w, logo_h)
    return TitleLayout(column(n, TITLE_LEFT, top, width, h, g), logo, h, g, fit.step,
                       fit.text_size)


# --- Game-menu sidebar -------------------------------------------------------------------

@dataclass(frozen=True)
class SidebarLayout:
    buttons: tuple[Box, ...]
    button_height: int
    gap: int
    step: FitStep           # 0 as designed, 1 gaps 4, 3 height, 4 label size (never 2)
    text_size: int          # the label size (at the text scale) the column's labels use
    panel: Box = SIDEBAR
    content: Box = CONTENT_PANEL
    heading: tuple[int, int] = PAGE_HEADING
    body: Box = PAGE_BODY


def sidebar_layout(n: int, *, scale: float = 1.0, text_size: int = BUTTON_TEXT_SIZE,
                   height: int = BUTTON_HEIGHT, width: int = MENU_BUTTON_WIDTH,
                   gap: int = BUTTON_GAP) -> SidebarLayout:
    """The navigation column centred in the sidebar, fitted by ``fit_column`` into the
    sidebar's height minus 16 each side (640)."""
    fit = fit_column(n, SIDEBAR.h - 2 * SIDEBAR_PADDING, scale=scale, text_size=text_size,
                     height=height, gap=gap)
    h, g = fit.button_height, fit.gap
    cx, cy = SIDEBAR.center
    top = cy - fit.height(n) / 2
    return SidebarLayout(column(n, cx - width / 2, top, width, h, g), h, g, fit.step,
                         fit.text_size)


# --- Confirm -----------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfirmLayout:
    panel: Box
    message: Box            # the message's lines: midtop at panel top + 40, wrap width 544
    yes: Box
    no: Box
    message_pitch: int


def confirm_button_width(label_width: float, *, minimum: int = CONFIRM_BUTTON_WIDTH) -> float:
    """max(``confirm.button_width``, label + 64), at most 280."""
    return min(CONFIRM_BUTTON_MAX, max(minimum, label_width + CONFIRM_LABEL_PAD))


def confirm_message_width(width: int = CONFIRM_WIDTH) -> int:
    return width - 2 * CONFIRM_MESSAGE_INSET


def confirm_layout(message_lines: int, *, message_size: int | None = None,
                   scale: float = 1.0, text_size: int = BUTTON_TEXT_SIZE,
                   height: int = BUTTON_HEIGHT, width: int = CONFIRM_WIDTH,
                   yes_label_width: float = 0, no_label_width: float = 0,
                   button_width: int = CONFIRM_BUTTON_WIDTH) -> ConfirmLayout:
    """Panel ``width`` × (40 + lines × pitch + 32 + H_b + 40), centred on the canvas.
    ``message_size`` is the size the message is drawn at after its fit (default: the panel
    text size at ``scale``)."""
    size = message_size if message_size is not None else scaled(PANEL_TEXT_SIZE, scale)
    line_pitch = pitch(size)
    message_h = max(0, message_lines) * line_pitch
    h = button_height(text_size, scale=scale, minimum=height)
    panel_h = CONFIRM_PAD_Y + message_h + CONFIRM_ROW_GAP + h + CONFIRM_PAD_Y
    cx, cy = CANVAS_W / 2, CANVAS_H / 2
    panel = Box(cx - width / 2, cy - panel_h / 2, width, panel_h)
    message = Box(panel.x + CONFIRM_MESSAGE_INSET, panel.y + CONFIRM_PAD_Y,
                  confirm_message_width(width), message_h)
    yes_w = confirm_button_width(yes_label_width, minimum=button_width)
    no_w = confirm_button_width(no_label_width, minimum=button_width)
    row_y = message.bottom + CONFIRM_ROW_GAP
    left = cx - (yes_w + CONFIRM_ROW_GAP + no_w) / 2
    yes = Box(left, row_y, yes_w, h)
    no = Box(left + yes_w + CONFIRM_ROW_GAP, row_y, no_w, h)
    return ConfirmLayout(panel, message, yes, no, line_pitch)


# --- Quick menu --------------------------------------------------------------------------

@dataclass(frozen=True)
class QuickItem:
    label: str              # as drawn (cut with "…" when the pill could not fit)
    box: Box                # the hit box; the end items include the pill's 4-unit ends
    label_box: Box          # the label itself, centred in the item


@dataclass(frozen=True)
class QuickMenuLayout:
    text_size: int          # q
    pill: Box
    items: tuple[QuickItem, ...]
    side_padding: int

    def pill_top(self) -> float:
        return self.pill.y


def quick_menu_layout(labels: Sequence[str], measure: Measure, *, scale: float = 1.0,
                      text_size: int = QM_TEXT_SIZE, side_padding: int = QM_SIDE_PADDING,
                      bottom_gap: int = QM_BOTTOM_GAP, strip: int = QM_STRIP) -> QuickMenuLayout:
    """The pill (``04`` §7.8 with I-4). q = clamp(round(size × scale), 20, 24); pill height
    q + 8, bottom at 720 − min(``bottom_gap``, max(0, ``strip`` − height)), centred at
    x 640. Items are label + 2 × padding and tile the pill (the end items own its 4-unit
    ends). Wider than 1,240: padding 4; still wider: each label is cut to 1232 / n − 8."""
    q = min(QM_SIZE_RANGE[1], max(QM_SIZE_RANGE[0], scaled(text_size, scale)))
    pill_h = q + 2 * QM_END
    bottom = CANVAS_H - min(bottom_gap, max(0, strip - pill_h))
    texts = list(labels)
    widths = [measure(t, q) for t in texts]
    pad = side_padding

    def total(pad_: int) -> float:
        return sum(w + 2 * pad_ for w in widths) + 2 * QM_END

    if texts and total(pad) > QM_MAX_WIDTH:
        pad = min(pad, QM_TIGHT_PADDING)
        if total(pad) > QM_MAX_WIDTH:
            limit = (QM_MAX_WIDTH - 2 * QM_END) / len(texts) - 2 * pad
            texts = [cut_to_width(t, limit, q, measure) for t in texts]
            widths = [measure(t, q) for t in texts]
    pill_w = total(pad) if texts else 2 * QM_END
    pill = Box(CANVAS_W / 2 - pill_w / 2, bottom - pill_h, pill_w, pill_h)
    items: list[QuickItem] = []
    x = pill.x + QM_END
    last = len(texts) - 1
    for i, (text, w) in enumerate(zip(texts, widths, strict=True)):
        inner = w + 2 * pad
        left = x - (QM_END if i == 0 else 0)
        right = x + inner + (QM_END if i == last else 0)
        box = Box(left, pill.y, right - left, pill_h)
        label_box = Box(x + pad, pill.y + QM_END, w, q)
        items.append(QuickItem(text, box, label_box))
        x += inner
    return QuickMenuLayout(q, pill, tuple(items), pad)


# --- Save and Load pages (F11 03-ui "Save and Load pages", Fit table; 04 §7.7) -------------

SAVE_TEXT_SIZE = 24         # save.text_size default
SAVE_COLUMNS = 3
SAVE_ROWS = 2
SAVE_CELL_WIDTH = 256
SAVE_COLUMN_GAP = 20        # cells at x 416, 692, 968
SAVE_CELL_INSET = 8         # picture box and placeholder inset; padding below the lines
SAVE_LINE_GAP = 6           # picture box → date line
SAVE_THUMB_MAX = 135        # T at 100% (240 × 135, 3/4 of the stored 320 × 180)
SAVE_THUMB_TIGHT = 108      # T below this: the row gap becomes 8
SAVE_THUMB_MIN = 90         # T below this: the description line is dropped
SAVE_ROW_GAP = 16
SAVE_ROW_GAP_TIGHT = 8
SAVE_TAG_PAD_Y = 10         # tag height = text size + 10
SAVE_TAG_PAD_X = 16         # tag width = text + 16
SAVE_TAG_INSET = 4          # label tag topleft (box x + 4, y + 4); Newest bottomleft
SAVE_TAG_RESERVE = 52       # a label tag is at most box width − 52 wide (room for the ×)
SAVE_DELETE_OFFSET = 20     # × center at (box right − 20, box y + 20)
SAVE_DELETE_DIAMETER = 32
SAVE_DELETE_HIT = 40
PAGE_ROW_BOTTOM = (820, 664)   # the page row's midbottom
PAGE_ROW_GAP = 4
PAGE_ROW_LABEL_PAD = 32     # a page button is max(H_b, label + 32) wide
PAGE_MESSAGE_WRAP = 760     # "No saves yet." / F32's reason wrap width


@dataclass(frozen=True)
class SaveCell:
    """One grid cell of the Save/Load page (canvas units)."""
    box: Box                        # the cell (a grid button)
    picture: Box                    # thumbnail box, midtop at cell top + 8
    date: tuple[float, float]       # date line topleft
    description: tuple[float, float] | None   # None when the Fit table drops it
    placeholder: Box                # inner area (inset 8) for Empty, Loading, Damaged, …
    label_tag: tuple[float, float]  # label tag topleft
    newest_tag: tuple[float, float]  # "Newest" tag bottomleft
    delete_center: tuple[float, float]
    delete_hit: Box


@dataclass(frozen=True)
class SaveLayout:
    """``save_layout``'s numbers: AC-F11-39's columns plus every cell's parts."""
    text_size: int                  # save.text_size at the text scale
    pitch: int
    button_height: int              # H_b
    gap: int                        # g, the row gap
    thumb: tuple[int, int]          # picture box (w, h): round(T × 16 / 9) × T
    cell_height: int                # C
    lines: int                      # 2 (date, description) or 1 (date)
    tag_height: int
    tag_max_width: int              # label tags wider than this are cut with "…"
    line_width: int                 # date and description width (240)
    cells: tuple[SaveCell, ...]     # 6, reading order
    grid: Box                       # the grid area (page message centered in it)
    row_bottom: tuple[int, int]     # the page row's midbottom

    @property
    def thumb_height(self) -> int:
        return self.thumb[1]

    @property
    def row2_y(self) -> float:
        return self.cells[SAVE_COLUMNS].box.y


def _save_thumb(h_b: int, gap: int, lines: int, line_pitch: int) -> int:
    room = int(PAGE_BODY.h - h_b - 2 * gap) // 2
    return min(SAVE_THUMB_MAX, room - (2 * SAVE_CELL_INSET + SAVE_LINE_GAP) - lines * line_pitch)


def save_layout(text_scale: float = 1.0, *, text_size: int = SAVE_TEXT_SIZE,
                button_text_size: int = BUTTON_TEXT_SIZE,
                button_min_height: int = BUTTON_HEIGHT) -> SaveLayout:
    """03-ui's Fit table: g = 16 and T = min(135, ⌊(552 − H_b − 2g) / 2⌋ − 22 − 2 × pitch);
    T < 108 → g = 8 and T again; T < 90 → one text line (no description) and T again. Cells
    are 256 × C, C = 8 + T + 6 + lines × pitch + 8, at x 416, 692, 968 from y 112, rows g
    apart; the picture box is round(T × 16 / 9) × T, centered 8 below the cell top."""
    size = scaled(text_size, text_scale)
    line_pitch = pitch(size)
    h_b = button_height(button_text_size, scale=text_scale, minimum=button_min_height)
    gap, lines = SAVE_ROW_GAP, 2
    thumb_h = _save_thumb(h_b, gap, lines, line_pitch)
    if thumb_h < SAVE_THUMB_TIGHT:
        gap = SAVE_ROW_GAP_TIGHT
        thumb_h = _save_thumb(h_b, gap, lines, line_pitch)
    if thumb_h < SAVE_THUMB_MIN:
        lines = 1
        thumb_h = _save_thumb(h_b, gap, lines, line_pitch)
    thumb_h = max(1, thumb_h)
    thumb_w = round(thumb_h * 16 / 9)
    cell_h = SAVE_CELL_INSET + thumb_h + SAVE_LINE_GAP + lines * line_pitch + SAVE_CELL_INSET
    tag_h = size + SAVE_TAG_PAD_Y
    line_w = SAVE_CELL_WIDTH - 2 * SAVE_CELL_INSET
    half = SAVE_DELETE_HIT / 2
    cells: list[SaveCell] = []
    for row in range(SAVE_ROWS):
        for col in range(SAVE_COLUMNS):
            box = Box(PAGE_BODY.x + col * (SAVE_CELL_WIDTH + SAVE_COLUMN_GAP),
                      PAGE_BODY.y + row * (cell_h + gap), SAVE_CELL_WIDTH, cell_h)
            pic = Box(box.x + (SAVE_CELL_WIDTH - thumb_w) / 2, box.y + SAVE_CELL_INSET,
                      thumb_w, thumb_h)
            date = (box.x + SAVE_CELL_INSET, pic.bottom + SAVE_LINE_GAP)
            desc = (date[0], date[1] + line_pitch) if lines == 2 else None
            center = (pic.right - SAVE_DELETE_OFFSET, pic.y + SAVE_DELETE_OFFSET)
            cells.append(SaveCell(
                box, pic, date, desc,
                Box(box.x + SAVE_CELL_INSET, box.y + SAVE_CELL_INSET, line_w,
                    cell_h - 2 * SAVE_CELL_INSET),
                (pic.x + SAVE_TAG_INSET, pic.y + SAVE_TAG_INSET),
                (pic.x + SAVE_TAG_INSET, pic.bottom - SAVE_TAG_INSET),
                center,
                Box(center[0] - half, center[1] - half, SAVE_DELETE_HIT, SAVE_DELETE_HIT)))
    grid = Box(PAGE_BODY.x, PAGE_BODY.y, PAGE_BODY.w, SAVE_ROWS * cell_h + gap)
    return SaveLayout(size, line_pitch, h_b, gap, (thumb_w, thumb_h), cell_h, lines, tag_h,
                      thumb_w - SAVE_TAG_RESERVE, line_w, tuple(cells), grid, PAGE_ROW_BOTTOM)


@dataclass(frozen=True)
class PageButton:
    """One button of the page row: a page (``page`` is its index in the labels) or an
    arrow (``"prev"`` for ◀, ``"next"`` for ▶; ``page`` None)."""
    kind: str                       # "page", "prev", "next"
    page: int | None
    label: str
    box: Box


RowAnchor = Literal["midbottom", "midtop", "topleft", "bottomleft"]


@dataclass(frozen=True)
class RowPlacement:
    """Where a page row sits: its ``anchor`` point at ``point`` (canvas units). F11's row is
    the default, midbottom at (820, 664); F21's tab row is topleft in its box (F21 ``07``
    I-1)."""
    anchor: RowAnchor = "midbottom"
    point: tuple[float, float] = PAGE_ROW_BOTTOM


PAGE_ROW_PLACEMENT = RowPlacement()


@dataclass(frozen=True)
class PageRowLayout:
    buttons: tuple[PageButton, ...]
    arrows: bool
    prev_enabled: bool              # ◀ / ▶ are disabled on the first / last page
    next_enabled: bool
    width: float

    @property
    def pages(self) -> tuple[int, ...]:
        """The page indices shown, in row order."""
        return tuple(b.page for b in self.buttons if b.page is not None)

    @property
    def bounds(self) -> Box:
        """The row's box: from its first button's left to its last button's right."""
        if not self.buttons:
            return Box(0, 0, 0, 0)
        first, last = self.buttons[0].box, self.buttons[-1].box
        return Box(first.x, first.y, last.right - first.x, first.h)


def page_row_layout(labels: Sequence[str], current: int, measure: Measure, *,
                    fixed: int = 0, scale: float = 1.0, text_size: int = BUTTON_TEXT_SIZE,
                    height: int = BUTTON_HEIGHT, width: float = PAGE_BODY.w,
                    placement: RowPlacement = PAGE_ROW_PLACEMENT) -> PageRowLayout:
    """03-ui "Page row contents": ``labels`` are every page in order (Load: "Auto", "Quick",
    then "1"…"N", with ``fixed`` = 2; Save: "1"…"N", ``fixed`` = 0). Buttons are H_b tall,
    max(H_b, label + 32) wide, 4 apart, the row placed by ``placement`` (default: its
    midbottom at (820, 664)). When all fit in ``width`` (808) the row shows them all with no
    arrows; otherwise ◀ first and ▶ last (H_b square), the fixed pages always, and a window
    of numbered pages, as many as fit, grown from the current page alternately right and
    left (from page 1 when a fixed page is current). The arrows never wrap: disabled on the
    first and last page."""
    h_b = button_height(text_size, scale=scale, minimum=height)
    size = scaled(text_size, scale)
    widths = [max(float(h_b), measure(label, size) + PAGE_ROW_LABEL_PAD) for label in labels]
    n = len(labels)
    current = max(0, min(current, n - 1)) if n else 0
    fixed = max(0, min(fixed, n))

    def total(indices: Sequence[int], arrows: bool) -> float:
        count = len(indices) + (2 if arrows else 0)
        return (sum(widths[i] for i in indices) + (2 * h_b if arrows else 0)
                + PAGE_ROW_GAP * max(0, count - 1))

    shown = list(range(n))
    arrows = n > 0 and total(shown, False) > width
    if arrows:
        shown = list(range(fixed))
        if fixed < n:
            lo = hi = current if current >= fixed else fixed
            right_first = True
            while True:
                grown = False
                for side in (("right", "left") if right_first else ("left", "right")):
                    if side == "right" and hi + 1 < n \
                            and total([*shown, *range(lo, hi + 2)], True) <= width:
                        hi += 1
                        grown = True
                        break
                    if side == "left" and lo - 1 >= fixed \
                            and total([*shown, *range(lo - 1, hi + 1)], True) <= width:
                        lo -= 1
                        grown = True
                        break
                if not grown:
                    break
                right_first = not right_first
            shown = [*shown, *range(lo, hi + 1)]
    row_w = total(shown, arrows)
    px, py = placement.point
    x = px - row_w / 2 if placement.anchor in ("midbottom", "midtop") else px
    y = py - h_b if placement.anchor in ("midbottom", "bottomleft") else py
    buttons: list[PageButton] = []
    for kind, page, label, w in (
            ([("prev", None, "◀", float(h_b))] if arrows else [])
            + [("page", i, labels[i], widths[i]) for i in shown]
            + ([("next", None, "▶", float(h_b))] if arrows else [])):
        buttons.append(PageButton(kind, page, label, Box(x, y, w, h_b)))
        x += w + PAGE_ROW_GAP
    return PageRowLayout(tuple(buttons), arrows, current > 0, n > 0 and current < n - 1, row_w)


# --- Codex page (F21 01 §6 UI-F21-01, 05; 04 §7.10 "Layout"; 07 I-9) ---------------------

CODEX_MIN_BOX = (640, 400)          # a CodexView host smaller than this is a programming error
CODEX_LIST_SHARE = (300, 808)       # list width = round(w × 300 / 808)
CODEX_GAP = 12                      # tab row → content; picture, title, body, pick apart
CODEX_PURSE_SHARE = (3, 10)     # F64: the purse's share of the top row's width
CODEX_PANEL_GAP = 20                # list → detail panel
CODEX_PANEL_PAD = 20                # the detail panel's padding
CODEX_ROW_PAD = 16                  # list rows: max(list.row_height, pitch + 16)
CODEX_TITLE_X = 16                  # a row's title starts 16 inside the row
CODEX_TITLE_RESERVE = 64            # a row's title fits lw − 64 (the dot's lane)
CODEX_DOT = 10                      # the unread dot's diameter
CODEX_DOT_INSET = 24                # its centre from the row's right edge
CODEX_TITLE_LINES = 2               # the detail title wraps to 2 lines, then "…"
CODEX_BODY_MIN_LINES = 2            # 07 I-9: the body keeps at least 2 text lines
CODEX_PICTURE_MIN = 80              # 07 I-9: a shorter picture box is no box
CODEX_IMAGE_HEIGHT = 200            # [theme.codex] image_height default
HEADING_TEXT_SIZE = 32              # panel.heading.text_size default


@dataclass(frozen=True)
class CodexLayout:
    """``codex_layout``'s boxes (canvas units). ``tab_row`` is None with one tab or none;
    ``picture`` None when the entry has no picture, ``image_height`` is 0, or the room is
    under 80 (07 I-9); ``pick`` None without a pick action. ``inner`` is the panel inside its
    padding; ``title`` is ``title_lines`` heading lines; ``body`` the rest."""
    box: Box
    tab_row: Box | None
    list: Box
    panel: Box
    inner: Box
    picture: Box | None
    title: Box
    body: Box
    pick: Box | None
    button_height: int              # H_b: the tab row's and the pick button's height
    row_height: int                 # list rows: max(list.row_height, pitch + 16)
    title_width: float              # a row title's room: lw − 64
    tab_label_width: float          # a tab label's room: w − 2·H_b − 8 (07 I-12)
    purse: Box | None = None        # F64: the money's strip, top right (None: no purse)


def codex_picture_height(inner_h: float, *, scale: float = 1.0,
                         image_height: int = CODEX_IMAGE_HEIGHT,
                         heading_size: int = HEADING_TEXT_SIZE,
                         text_size: int = PANEL_TEXT_SIZE, pick: float = 0) -> int:
    """07 I-9: min(``image_height``, inner height − a 2-line title − a 2-line body − the
    gaps − the pick button ``pick`` (0: none)); 0 when that is under 80 (no picture box)."""
    if image_height <= 0:
        return 0
    gaps = 2 * CODEX_GAP + (CODEX_GAP + pick if pick else 0)
    room = (inner_h - CODEX_TITLE_LINES * pitch(scaled(heading_size, scale))
            - CODEX_BODY_MIN_LINES * pitch(scaled(text_size, scale)) - gaps)
    height = int(min(image_height, room))
    return height if height >= CODEX_PICTURE_MIN else 0


def codex_layout(box: Box, text_scale: float = 1.0, *, tabs: int, pick: bool,
                 picture: bool = True, purse: bool = False,
                 title_lines: int = CODEX_TITLE_LINES,
                 image_height: int = CODEX_IMAGE_HEIGHT,
                 button_text_size: int = BUTTON_TEXT_SIZE,
                 button_min_height: int = BUTTON_HEIGHT,
                 heading_size: int = HEADING_TEXT_SIZE, text_size: int = PANEL_TEXT_SIZE,
                 list_row_min: int = LIST_ROW_HEIGHT) -> CodexLayout:
    """F21 04 §7.10 "Layout" with 07 I-9 (pure). With more than one tab the tab row is
    (x, y, w, H_b) and the content starts 12 below it. The list is round(w × 300 / 808)
    wide; the detail panel starts 20 to its right, padding 20. Inside the panel, from the
    top: the picture box (``codex_picture_height``; only for an entry declared with a
    picture, so a missing file keeps its empty box), the title (``title_lines`` heading
    lines), the body (the rest), and the pick button ((panel w − 40) × H_b at the panel's
    bottom inside the padding), 12 apart. For the 808×552 slot this gives 01 §6.

    F64: with ``purse``, the money's strip is the right ``CODEX_PURSE_SHARE`` of the top
    row (H_b high); the tab row, if any, takes the rest less 12, and the content starts 12
    below that row even with one tab."""
    x, y, w, h = box.x, box.y, box.w, box.h
    h_b = button_height(button_text_size, scale=text_scale, minimum=button_min_height)
    pw = round(w * CODEX_PURSE_SHARE[0] / CODEX_PURSE_SHARE[1]) if purse else 0
    purse_box = Box(x + w - pw, y, pw, h_b) if purse else None
    tab_row = Box(x, y, w - pw - CODEX_GAP if purse else w, h_b) if tabs > 1 else None
    top = y + h_b + CODEX_GAP if tab_row is not None or purse else y
    content_h = y + h - top
    lw = round(w * CODEX_LIST_SHARE[0] / CODEX_LIST_SHARE[1])
    lst = Box(x, top, lw, content_h)
    panel = Box(x + lw + CODEX_PANEL_GAP, top, w - lw - CODEX_PANEL_GAP, content_h)
    pad = CODEX_PANEL_PAD
    inner = Box(panel.x + pad, panel.y + pad, panel.w - 2 * pad, panel.h - 2 * pad)
    pick_box = Box(inner.x, inner.bottom - h_b, inner.w, h_b) if pick else None
    pic_h = codex_picture_height(inner.h, scale=text_scale, image_height=image_height,
                                 heading_size=heading_size, text_size=text_size,
                                 pick=h_b if pick else 0) if picture else 0
    picture_box = Box(inner.x, inner.y, inner.w, pic_h) if pic_h else None
    title_top = picture_box.bottom + CODEX_GAP if picture_box is not None else inner.y
    lines = max(1, min(CODEX_TITLE_LINES, title_lines))
    title = Box(inner.x, title_top, inner.w, lines * pitch(scaled(heading_size, text_scale)))
    body_top = title.bottom + CODEX_GAP
    body_bottom = pick_box.y - CODEX_GAP if pick_box is not None else inner.bottom
    body = Box(inner.x, body_top, inner.w, max(0.0, body_bottom - body_top))
    row_h = max(list_row_min, pitch(scaled(button_text_size, text_scale)) + CODEX_ROW_PAD)
    row_w = tab_row.w if tab_row is not None else w
    return CodexLayout(box, tab_row, lst, panel, inner, picture_box, title, body, pick_box,
                       h_b, row_h, lw - CODEX_TITLE_RESERVE, row_w - 2 * h_b - 8, purse_box)


# --- Minigame frame (F23 03-ui layout table, "Fit checks"; 04 §7.11) ---------------------

MG_MARGIN = 24              # heading topleft (24, 24); content x 24–1256, top 24, bottom 696
MG_GAP = 16                 # heading bottom → content; content → hint top
MG_HEADING_SIZE = 32        # panel.heading.text_size default
MG_HEADING_PAD_X = 20       # heading width = text + 40, from 160 to 560
MG_HEADING_PAD_Y = 8        # heading height = pitch + 16
MG_HEADING_WIDTH = (160, 560)
MG_HINT_SIZE = 24           # minigame.hint.text_size default
MG_HINT_BOTTOM = (640, 696)  # the hint bar's midbottom
MG_HINT_PAD_X = 24          # text wraps at width − 48
MG_HINT_PAD_Y = 12          # height = lines × pitch + 24
MG_HINT_WIDTH = (320, 1000)
MG_HINT_MAX_LINES = 2
MG_CUE_INSET = 52           # the cue sits on the hint's top edge, 52 in from its right end
MG_CUE_DEFAULT = (1088, 668)


@dataclass(frozen=True)
class Frame:
    """``minigame_frame``'s numbers (canvas units). ``heading``/``hint`` are None when off."""
    heading: Box | None
    hint: Box | None
    hint_lines: tuple[str, ...]     # as drawn, centered in ``hint``; the last may end "…"
    content: Box                    # the rectangle the plugin is told
    cue: tuple[float, float]        # the limit cue's center
    heading_text: str = ""          # as drawn (cut with "…" only at 24)
    heading_size: int = 0           # after the heading's fit
    hint_size: int = 0


def _fit_line(text: str, width: float, size: int, measure: Measure) -> tuple[str, int]:
    """One line of ``text`` into ``width``: the size steps down by 2, not below 24, then the
    text is cut with "…" (ui-system §7)."""
    while measure(text, size) > width and size - TEXT_STEP >= TEXT_MIN_SIZE:
        size -= TEXT_STEP
    return cut_to_width(text, width, size, measure), size


def minigame_frame(text_scale: float = 1.0, *, heading: str | None, hint: str | None,
                   measure: Measure, heading_measure: Measure | None = None,
                   heading_size: int = MG_HEADING_SIZE, hint_size: int = MG_HINT_SIZE,
                   cue_point: tuple[float, float] | None = None) -> Frame:
    """The minigame screen's frame (F23 ``03`` layout table; ``04`` §7.11). ``heading`` and
    ``hint`` are None (or "") when off. ``measure`` measures the hint's font,
    ``heading_measure`` the heading's bold font (default ``measure``); sizes are unscaled
    tokens.

    Heading: topleft (24, 24), pitch + 16 tall at its token size, text + 40 wide within
    160–560; one line, fitted by stepping down by 2 (not below 24), then "…". Hint: midbottom
    (640, 696), min(1000, max(320, widest line + 48)) wide, lines × pitch + 24 tall, wrapped at
    952, at most 2 lines with "…". Content: x 24–1256, from 24 (or heading bottom + 16) to 696
    (or hint top − 16). Cue: ``cue_point``, else the hint's top edge 52 in from its right,
    else (1088, 668). Re-run after every text-size change and every heading/hint call."""
    left, right = MG_MARGIN, CANVAS_W - MG_MARGIN
    top, bottom = MG_MARGIN, CANVAS_H - MG_MARGIN
    head_box: Box | None = None
    head_text, head_size = "", 0
    if heading:
        size = scaled(heading_size, text_scale)
        lo, hi = MG_HEADING_WIDTH
        hm = heading_measure or measure
        head_text, head_size = _fit_line(heading, hi - 2 * MG_HEADING_PAD_X, size, hm)
        w = min(hi, max(lo, hm(head_text, head_size) + 2 * MG_HEADING_PAD_X))
        head_box = Box(MG_MARGIN, MG_MARGIN, w, pitch(size) + 2 * MG_HEADING_PAD_Y)
        top = head_box.bottom + MG_GAP
    hint_box: Box | None = None
    lines: tuple[str, ...] = ()
    size = 0
    if hint:
        size = scaled(hint_size, text_scale)
        lo, hi = MG_HINT_WIDTH
        lines = fit_message(hint, hi - 2 * MG_HINT_PAD_X, size, measure,
                            max_lines=MG_HINT_MAX_LINES, min_size=size).lines
        widest = max(measure(line, size) for line in lines)
        w = min(hi, max(lo, widest + 2 * MG_HINT_PAD_X))
        h = len(lines) * pitch(size) + 2 * MG_HINT_PAD_Y
        cx, by = MG_HINT_BOTTOM
        hint_box = Box(cx - w / 2, by - h, w, h)
        bottom = hint_box.y - MG_GAP
    if cue_point is not None:
        cue = cue_point
    elif hint_box is not None:
        cue = (hint_box.right - MG_CUE_INSET, hint_box.y)
    else:
        cue = MG_CUE_DEFAULT
    return Frame(head_box, hint_box, lines, Box(left, top, right - left, bottom - top), cue,
                 head_text, head_size, size)
