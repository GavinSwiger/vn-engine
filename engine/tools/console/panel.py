"""The in-game console's panel: layout, fixed dev look, drawing and raw input (F40 ``04``
§3, §7.6; ``01`` §6.1, §6.2).

Why this module exists: the console must stay readable and usable whatever the game's theme
does, so it has its own fixed look (like the error screen) and its own input handling. It
only draws ``ConsoleModel`` and turns events into calls on it; it never changes the story.

**Layout** (canvas units, ``01`` §6.1): the panel is 1152 × 480 at (64, 48), on a 32-unit
grid: header, tabs, filter, nine list rows, the value field, the output line, the hint. The
Code tab uses the space under the tabs for its last results and puts its input above the
output line. Rows are 32 high; text is the bundled Noto Sans 20 (group captions 16, upper
case), fixed whatever the player's text size.

**Look** (fixed, not theme tokens): panel ``#141414`` at 95 %, a 2-unit ``#3C3C3C`` border,
text ``#F0F0F0``, secondary text ``#A0A0A0``, the selected row and focused field ``#04395E``,
error output ``#F48771``. It appears and goes with a cut (no motion), and the text caret
doesn't blink.

**Input** (``handle``, given ``UiEvent``\\ s while the console is open; W1 passes every
event here and the screens below get none):

- Keyboard: Ctrl+1/2/3, Ctrl+Tab and Tab switch tabs; Up/Down move (Code: history);
  Page Up/Down move a page; Enter acts; Left/Right/Home/End/Backspace/Delete edit the
  focused field; Ctrl+V pastes (``read_clipboard``: first line, controls dropped, 2,000 at
  most; SEC-F40-12); Esc closes an open value field, else the console; F12 closes.
- Text: SDL text input (``TEXTINPUT``), so IME and non-Latin keyboards type normally; the
  IME's unfinished text (``TEXTEDITING``) shows at the caret. ``start_typing`` and
  ``stop_typing`` are W1's calls on open and close.
- Mouse: click a tab, a row (Variables: opens its value field; Jump: a click on the
  selected row jumps), a row's button, or ``F12 / Esc`` (closes); the wheel scrolls.
- Gamepad: D-pad up/down move, A acts (Switch or +1, or jump), X is -1, the shoulders
  switch tabs, B closes (pads don't type).

``handle`` returns an action for W1 to apply once the story rests, ``Close()``, or None.
"""

from collections.abc import Callable

import pygame

from engine.render.canvas import Canvas
from engine.render.text import FontSpec, fit_line, text_width
from engine.tools.console import texts
from engine.tools.console.model import (LIST_ROWS, TABS, TAB_TEXTS, Action, Close,
                                        ConsoleModel, Field, Row, Tab, clean_input)
from engine.ui.input import UiEvent

# --- Look (01 §6.1) --------------------------------------------------------------------------

PANEL_COLOR = (0x14, 0x14, 0x14, 242)    # #141414 at 95 %
BORDER_COLOR = (0x3C, 0x3C, 0x3C)        # #3C3C3C
TEXT_COLOR = (0xF0, 0xF0, 0xF0)          # #F0F0F0: 16.9:1 on the panel
SECONDARY_COLOR = (0xA0, 0xA0, 0xA0)     # #A0A0A0: 7.4:1
SELECTED_COLOR = (0x04, 0x39, 0x5E)      # #04395E: #F0F0F0 on it is 10.6:1
ERROR_COLOR = (0xF4, 0x87, 0x71)         # #F48771: 7.6:1
FIELD_COLOR = (0x1E, 0x1E, 0x1E)         # an unfocused field's inside
FONT = FontSpec(None, 20)
CAPTION_FONT = FontSpec(None, 16)

# --- Layout (canvas units) -------------------------------------------------------------------

PANEL = (64, 48, 1152, 480)
BORDER = 2
ROW_H = 32
LEFT = 80                                 # text column start
RIGHT = 1200                              # text column end
HEADER_Y = 48
TABS_Y = 80
FILTER_Y = 112
LIST_Y = 144                              # LIST_ROWS rows: 144 to 432
VALUE_Y = 432                             # the value field (Variables)
OUTPUT_Y = 464
HINT_Y = 496
CODE_INPUT_Y = 464                        # Code: input above the hint
CODE_TOP = 112                            # Code: results from here to the input
TAB_W = 132
TAB_GAP = 8
NAME_X = 88
NAME_W = 280
VALUE_X = 384
BUTTON_H = 24
BUTTON_GAP = 8
BUTTON_W = {texts.SWITCH: 84, texts.MINUS: 48, texts.PLUS: 48}
BUTTONS_RIGHT = 1184
SCROLL_X = 1192
FIELD_PAD = 8
VALUE_LABEL_W = 112
CARET_W = 2
KEYS_W = 120                              # the clickable "F12 / Esc"

_TAB_KEYS = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2,
             pygame.K_KP_1: 0, pygame.K_KP_2: 1, pygame.K_KP_3: 2}
_FIT_CACHE_MAX = 1024


def read_clipboard() -> str:
    """Ctrl+V's text: the clipboard's text, or "" when there is none or it can't be read.
    The field keeps only its first line, controls dropped, cut (``clean_input``)."""
    try:
        text = pygame.scrap.get_text()
    except (pygame.error, AttributeError, NotImplementedError):
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    return clean_input(text if isinstance(text, str) else "")


def start_typing() -> None:
    """On open (W1): SDL text input on, so typed and IME text arrive as ``TEXTINPUT``."""
    pygame.key.start_text_input()


def stop_typing() -> None:
    """On close (W1)."""
    pygame.key.stop_text_input()


def tab_rect(index: int) -> tuple[int, int, int, int]:
    return (LEFT + index * (TAB_W + TAB_GAP), TABS_Y + 3, TAB_W, ROW_H - 6)


def row_rect(slot: int) -> tuple[int, int, int, int]:
    """The list row drawn ``slot`` rows below the list's top (0 to LIST_ROWS - 1)."""
    return (PANEL[0] + 8, LIST_Y + slot * ROW_H, PANEL[2] - 24, ROW_H)


def button_rects(row: Row, slot: int) -> list[tuple[str, tuple[int, int, int, int]]]:
    """The row's buttons, right-aligned, with their rects."""
    y = LIST_Y + slot * ROW_H + (ROW_H - BUTTON_H) // 2
    out: list[tuple[str, tuple[int, int, int, int]]] = []
    x = BUTTONS_RIGHT
    for label in reversed(row.buttons):
        width = BUTTON_W.get(label, 64)
        x -= width
        out.append((label, (x, y, width, BUTTON_H)))
        x -= BUTTON_GAP
    out.reverse()
    return out


FILTER_RECT = (LEFT, FILTER_Y + 2, RIGHT - LEFT, ROW_H - 4)
VALUE_RECT = (LEFT + VALUE_LABEL_W, VALUE_Y + 2, RIGHT - LEFT - VALUE_LABEL_W, ROW_H - 4)
CODE_RECT = (LEFT + 24, CODE_INPUT_Y + 2, RIGHT - LEFT - 24, ROW_H - 4)
KEYS_RECT = (RIGHT - KEYS_W, HEADER_Y, KEYS_W, ROW_H)


def _inside(pos: tuple[float, float], rect: tuple[int, int, int, int]) -> bool:
    x, y, w, h = rect
    return x <= pos[0] < x + w and y <= pos[1] < y + h


class ConsolePanel:
    """Draws one ``ConsoleModel`` and handles the raw input meant for it (module
    docstring). ``paste`` reads the clipboard (default ``read_clipboard``)."""

    def __init__(self, model: ConsoleModel, *, paste: Callable[[], str] | None = None) -> None:
        self.model = model
        self.composing = ""                       # the IME's unfinished text
        self._paste = paste or read_clipboard
        self._fit: dict[tuple[str, int, int], str] = {}
        self._code_lines: tuple[int, list[tuple[str, tuple[int, int, int]]]] | None = None

    # -- Input -------------------------------------------------------------------------------------

    def handle(self, event: UiEvent) -> Action | Close | None:
        """One event while the console is open (all are consumed)."""
        raw = event.raw
        kind = raw.type
        if kind == pygame.KEYDOWN:
            return self._key(raw)
        if kind == pygame.TEXTINPUT:
            self.composing = ""
            self.model.insert(raw.text)
            return None
        if kind == pygame.TEXTEDITING:
            self.composing = clean_input(getattr(raw, "text", ""), 200)
            return None
        if kind == pygame.MOUSEBUTTONDOWN and getattr(raw, "button", 0) == 1:
            if event.canvas_pos is not None and event.in_canvas:
                return self._click(event.canvas_pos)
            return None
        if kind == pygame.MOUSEWHEEL:
            step = -int(getattr(raw, "y", 0))
            if getattr(raw, "flipped", False):
                step = -step
            if step:
                self.model.scroll(step)
            return None
        if kind == pygame.CONTROLLERBUTTONDOWN:
            return self._pad(raw.button)
        return None

    def _key(self, raw: pygame.event.Event) -> Action | Close | None:
        key = raw.key
        model = self.model
        ctrl = bool(getattr(raw, "mod", 0) & pygame.KMOD_CTRL)
        shift = bool(getattr(raw, "mod", 0) & pygame.KMOD_SHIFT)
        if key == pygame.K_F12:
            return Close()
        if key == pygame.K_ESCAPE:
            return None if model.escape() else Close()
        if key == pygame.K_TAB:
            model.next_tab(-1 if shift else 1)
            return None
        if ctrl:
            if key in _TAB_KEYS:
                model.select_tab(TABS[_TAB_KEYS[key]])
            elif key == pygame.K_v:
                self.paste()
            return None
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return model.enter()
        if key == pygame.K_UP:
            model.move(-1)
        elif key == pygame.K_DOWN:
            model.move(1)
        elif key == pygame.K_PAGEUP:
            model.move(-LIST_ROWS)
        elif key == pygame.K_PAGEDOWN:
            model.move(LIST_ROWS)
        elif key == pygame.K_BACKSPACE:
            model.backspace()
        elif key == pygame.K_DELETE:
            model.delete()
        elif key == pygame.K_LEFT:
            model.cursor("left")
        elif key == pygame.K_RIGHT:
            model.cursor("right")
        elif key == pygame.K_HOME:
            model.cursor("home")
        elif key == pygame.K_END:
            model.cursor("end")
        return None

    def paste(self) -> None:
        """Ctrl+V: the clipboard's first line into the focused field (SEC-F40-12)."""
        try:
            text = self._paste()
        except Exception:                         # noqa: BLE001 (a clipboard can't stop us)
            return
        text = clean_input(text)
        if text:
            self.model.insert(text)

    def _click(self, pos: tuple[float, float]) -> Action | Close | None:
        model = self.model
        if _inside(pos, KEYS_RECT):
            return Close()
        for index, tab in enumerate(TABS):
            if _inside(pos, tab_rect(index)):
                model.select_tab(tab)
                return None
        if model.tab is Tab.CODE:
            return None
        if _inside(pos, FILTER_RECT):
            model.escape()                        # typing goes to the filter again
            return None
        if not LIST_Y <= pos[1] < LIST_Y + LIST_ROWS * ROW_H:
            return None
        slot = int((pos[1] - LIST_Y) // ROW_H)
        rows = model.visible()
        index = model.top + slot
        if not 0 <= index < len(rows) or not rows[index].selectable:
            return None
        row = rows[index]
        for label, rect in button_rects(row, slot):
            if _inside(pos, rect):
                model.select(index)
                return model.press(row.name, label)
        was_selected = model.selected_index == index
        model.select(index)
        if model.tab is Tab.JUMP:
            return model.enter() if was_selected else None
        if model.editing == row.name:
            return None
        return model.enter()                      # a click opens the value field

    def _pad(self, button: int) -> Action | Close | None:
        model = self.model
        if button == pygame.CONTROLLER_BUTTON_DPAD_UP:
            model.move(-1)
        elif button == pygame.CONTROLLER_BUTTON_DPAD_DOWN:
            model.move(1)
        elif button == pygame.CONTROLLER_BUTTON_LEFTSHOULDER:
            model.next_tab(-1)
        elif button == pygame.CONTROLLER_BUTTON_RIGHTSHOULDER:
            model.next_tab(1)
        elif button == pygame.CONTROLLER_BUTTON_A:
            return model.primary()
        elif button == pygame.CONTROLLER_BUTTON_X:
            return model.secondary()
        elif button == pygame.CONTROLLER_BUTTON_B:
            return None if model.escape() else Close()
        return None

    # -- Drawing -----------------------------------------------------------------------------------

    def draw(self, canvas: Canvas) -> None:
        """The whole panel (App.present calls this above the screens, under notices and the
        F3 overlay; never into a thumbnail or a scene picture)."""
        model = self.model
        x, y, w, h = PANEL
        canvas.fill(PANEL_COLOR, PANEL)
        for edge in ((x, y, w, BORDER), (x, y + h - BORDER, w, BORDER),
                     (x, y, BORDER, h), (x + w - BORDER, y, BORDER, h)):
            canvas.fill(BORDER_COLOR, edge)
        self._text(canvas, model.header, TEXT_COLOR, LEFT, HEADER_Y, RIGHT - LEFT - KEYS_W - 16)
        self._text(canvas, texts.HEADER_KEYS, SECONDARY_COLOR, RIGHT, HEADER_Y, KEYS_W,
                   anchor="midright")
        for index, tab in enumerate(TABS):
            rect = tab_rect(index)
            if tab is model.tab:
                canvas.fill(SELECTED_COLOR, rect)
            self._frame(canvas, rect)
            canvas.draw_text(TAB_TEXTS[tab], FONT, TEXT_COLOR,
                             (rect[0] + rect[2] / 2, rect[1] + rect[3] / 2), anchor="center")
        if model.tab is Tab.CODE:
            self._draw_code(canvas)
        else:
            self._draw_list(canvas)
        self._text(canvas, model.hint, SECONDARY_COLOR, LEFT, HINT_Y, RIGHT - LEFT)

    def _draw_list(self, canvas: Canvas) -> None:
        model = self.model
        filt = model.filters[model.tab]
        self._field(canvas, FILTER_RECT, filt, focused=model.editing is None,
                    placeholder=texts.FILTER_PLACEHOLDER)
        rows = model.visible()
        top = model.top
        selected = model.selected_index
        if not rows:
            self._text(canvas, model.empty_text, SECONDARY_COLOR, NAME_X, LIST_Y,
                       RIGHT - NAME_X)
        for slot, row in enumerate(rows[top:top + LIST_ROWS]):
            self._row(canvas, row, slot, top + slot == selected)
        if len(rows) > LIST_ROWS:                 # a scroll bar: where the view is
            track = (SCROLL_X, LIST_Y, 4, LIST_ROWS * ROW_H)
            canvas.fill(BORDER_COLOR, track)
            size = max(int(track[3] * LIST_ROWS / len(rows)), 16)
            offset = int((track[3] - size) * top / max(len(rows) - LIST_ROWS, 1))
            canvas.fill(SECONDARY_COLOR, (SCROLL_X, LIST_Y + offset, 4, size))
        if model.tab is Tab.VARIABLES and model.editing is not None:
            self._text(canvas, texts.VALUE_LABEL, SECONDARY_COLOR, LEFT, VALUE_Y,
                       VALUE_LABEL_W - 8)
            self._field(canvas, VALUE_RECT, model.value, focused=True)
        output = model.output[model.tab]
        if output is not None:
            self._text(canvas, output.text, TEXT_COLOR if output.ok else ERROR_COLOR, LEFT,
                       OUTPUT_Y, RIGHT - LEFT)

    def _row(self, canvas: Canvas, row: Row, slot: int, selected: bool) -> None:
        rect = row_rect(slot)
        middle = rect[1] + ROW_H / 2
        if not row.selectable:
            text = self._fitted(canvas, row.name.upper(), CAPTION_FONT, RIGHT - NAME_X)
            canvas.draw_text(text, CAPTION_FONT, SECONDARY_COLOR, (NAME_X, middle),
                             anchor="midleft")
            return
        if selected:
            canvas.fill(SELECTED_COLOR, rect)
        self._text(canvas, row.name, TEXT_COLOR, NAME_X, rect[1], NAME_W)
        buttons = button_rects(row, slot)
        right = buttons[0][1][0] - 16 if buttons else RIGHT
        color = SECONDARY_COLOR if row.kind == "label" else TEXT_COLOR
        self._text(canvas, row.text, color, VALUE_X, rect[1], right - VALUE_X)
        for label, box in buttons:
            canvas.fill(FIELD_COLOR, box)
            self._frame(canvas, box)
            canvas.draw_text(label, FONT, TEXT_COLOR, (box[0] + box[2] / 2,
                                                       box[1] + box[3] / 2), anchor="center")

    def _draw_code(self, canvas: Canvas) -> None:
        model = self.model
        lines = self._result_lines(canvas)
        room = (CODE_INPUT_Y - CODE_TOP) // ROW_H
        shown = lines[-room:] if room > 0 else []
        if not shown and not model.results:
            self._text(canvas, texts.CODE_EMPTY, SECONDARY_COLOR, LEFT, CODE_TOP, RIGHT - LEFT)
        y = CODE_INPUT_Y - len(shown) * ROW_H
        for text, color in shown:
            canvas.draw_text(text, FONT, color, (LEFT, y + ROW_H / 2), anchor="midleft")
            y += ROW_H
        canvas.draw_text(">", FONT, SECONDARY_COLOR, (LEFT + 4, CODE_INPUT_Y + ROW_H / 2),
                         anchor="midleft")
        self._field(canvas, CODE_RECT, model.code, focused=True)

    def _result_lines(self, canvas: Canvas) -> list[tuple[str, tuple[int, int, int]]]:
        """The Code results as drawn lines (each output wrapped to the panel), cached until
        the model changes."""
        model = self.model
        cached = self._code_lines
        if cached is not None and cached[0] == model.version:
            return cached[1]
        width = RIGHT - LEFT - 24
        out: list[tuple[str, tuple[int, int, int]]] = []
        for entry in model.results:
            out.append((self._fitted(canvas, "> " + entry.line, FONT, width + 24),
                        SECONDARY_COLOR))
            color = TEXT_COLOR if entry.ok else ERROR_COLOR
            for line in entry.lines:
                for part in canvas.layout_lines(line, FONT, width, 4):
                    out.append(("   " + part, color))
        self._code_lines = (model.version, out)
        return out

    def _field(self, canvas: Canvas, rect: tuple[int, int, int, int], field: Field, *,
               focused: bool, placeholder: str = "") -> None:
        canvas.fill(SELECTED_COLOR if focused else FIELD_COLOR, rect)
        self._frame(canvas, rect)
        x, y, w, h = rect
        middle = y + h / 2
        room = w - 2 * FIELD_PAD
        font = canvas.font_handle(FONT, FONT.size).font
        composing = self.composing if focused else ""
        before = field.text[:field.cursor] + composing
        after = field.text[field.cursor:]
        if not field.text and not composing:
            if placeholder:
                canvas.draw_text(placeholder, FONT, SECONDARY_COLOR, (x + FIELD_PAD, middle),
                                 anchor="midleft")
            if focused:
                canvas.fill(TEXT_COLOR, (x + FIELD_PAD, y + 5, CARET_W, h - 10))
            return
        # Keep the caret in view: drop text from the left until what's before it fits.
        start = max(len(before) - 400, 0)
        while start < len(before) and text_width(font, before[start:]) > room - CARET_W:
            start += max((len(before) - start) // 8, 1)
        head = before[start:]
        head_w = text_width(font, head)
        tail = fit_line(font, after, max(room - head_w - CARET_W, 0), "") if after else ""
        canvas.draw_text(head + tail, FONT, TEXT_COLOR, (x + FIELD_PAD, middle),
                         anchor="midleft")
        if composing:                             # the IME's text, underlined
            comp_w = text_width(font, composing)
            canvas.fill(TEXT_COLOR, (x + FIELD_PAD + head_w - comp_w, y + h - 6,
                                     comp_w, 1))
        if focused:
            canvas.fill(TEXT_COLOR, (x + FIELD_PAD + min(head_w, room - CARET_W), y + 5,
                                     CARET_W, h - 10))

    def _frame(self, canvas: Canvas, rect: tuple[int, int, int, int]) -> None:
        x, y, w, h = rect
        for edge in ((x, y, w, 1), (x, y + h - 1, w, 1), (x, y, 1, h), (x + w - 1, y, 1, h)):
            canvas.fill(BORDER_COLOR, edge)

    def _text(self, canvas: Canvas, text: str, color: tuple[int, int, int], x: float,
              row_y: float, width: float, *, anchor: str = "midleft") -> None:
        """One line of 20-unit text centered in the 32-unit row at ``row_y``, cut with
        ``…`` to ``width``."""
        if not text:
            return
        fitted = self._fitted(canvas, text, FONT, width)
        canvas.draw_text(fitted, FONT, color, (x, row_y + ROW_H / 2),
                         anchor=anchor)  # type: ignore[arg-type]

    def _fitted(self, canvas: Canvas, text: str, font: FontSpec, width: float) -> str:
        key = (text, font.size, int(width))
        found = self._fit.get(key)
        if found is None:
            line = text.split("\n", 1)[0]
            found = fit_line(canvas.font_handle(font, font.size).font, line, max(width, 0))
            if line != text and not found.endswith("…"):
                found = fit_line(canvas.font_handle(font, font.size).font, line + " …",
                                 max(width, 0))
            if len(self._fit) >= _FIT_CACHE_MAX:
                self._fit.clear()
            self._fit[key] = found
        return found


__all__ = ["BORDER_COLOR", "CAPTION_FONT", "ConsolePanel", "ERROR_COLOR", "FONT", "PANEL",
           "PANEL_COLOR", "ROW_H", "SECONDARY_COLOR", "SELECTED_COLOR", "TEXT_COLOR",
           "button_rects", "read_clipboard", "row_rect", "start_typing", "stop_typing",
           "tab_rect"]
