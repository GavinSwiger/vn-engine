"""Studio's sizes, colors and Tk tag names, shared by ``window`` and its wiring modules
(``fileactions``, ``checkwiring``, ``runwiring``, ``mapwiring``, ``studiomenus``,
``editorkeys``); ``window`` re-exports them. Sizes are px at 100 % scaling (03 §1.1,
UI-F44-01); colors all come from ``theme.THEME`` (03 §1.2, §2.1, VS Code Dark+).

Imports only ``theme``; no Tk call at import time.
"""

from engine.tools.editor.theme import THEME

# --- Sizes in pixels at 100 % scaling (03 §1.1, UI-F44-01) --------------------------------

# The editor window's own default size as a Tk geometry string. It is not the game canvas
# (AC-F01-48 keeps the canvas size in core/constants.py; its test looks for int literals).
WINDOW_GEOMETRY = "1100x720"
WINDOW_SIZE = tuple(int(part) for part in WINDOW_GEOMETRY.split("x"))
WINDOW_MIN_SIZE = (760, 480)
LEFT_WIDTH = 240
LEFT_MIN_WIDTH = 160
COLUMN_PAD = 8
PANEL_INSET = 12                        # a panel's text inset (08 §5)
EDITOR_MIN_HEIGHT = 160
PROBLEMS_HEIGHT = 160
PROBLEMS_SHARE = 0.6                    # Problems 60 %, Help 40 % (F45 01 §6.1)
BOTTOM_MIN_WIDTH = 120
PROBLEMS_MIN_HEIGHT = 80
TEXT_PAD = 4
SASH_WIDTH = 4
SIDE_SHARE = 0.45                       # the Story map's side editor at first (2026-11-02)
SIDE_MIN_WIDTH = 240
MAP_MIN_WIDTH = 200
CURSOR_WIDTH = 2
FONT_PX = 14                            # editor text, zoomable (03 §4, §7)
FONT_MIN_PX = 10
FONT_MAX_PX = 32
FONT_STEP_PX = 2
START_VALUES_PX = 13                    # 08 §4 codeSmall
START_VALUES_ROWS = 6
TAB_SPACES = 4
COMPLETION_PAGE = 10                    # rows Page Up / Page Down move in the list

# --- Colors (03 §1.2, §2.1, amended 2026-11-02: VS Code Dark+, all from theme.THEME) -------

BACKGROUND = THEME["editor.background"]
SIDE_BACKGROUND = THEME["sideBar.background"]
PANEL_BACKGROUND = THEME["panel.background"]   # Problems and Help
INPUT_BORDER = THEME["input.border"]
INPUT_BACKGROUND = THEME["input.background"]
GUTTER_BACKGROUND = THEME["gutter.background"]
GUTTER_FOREGROUND = THEME["gutter.foreground"]
GUTTER_CURRENT = THEME["gutter.activeForeground"]   # the cursor line's number
MESSAGE_FOREGROUND = THEME["muted"]     # read-only messages, the empty row, hints
JUMP_BACKGROUND = THEME["editor.jumpHighlight"]
LINE_BACKGROUND = THEME["editor.lineHighlight"]     # the cursor's line
CURSOR_COLOR = THEME["editor.cursor"]
FOCUS_BORDER = THEME["focusBorder"]
MARKER_COLORS = {"error": THEME["marker.error"],    # on GUTTER_BACKGROUND (UI-F45-03)
                 "warning": THEME["marker.warning"]}
MARKER_LETTERS = {"error": "E", "warning": "W"}             # info has no marker
MARKER_CHARS = 2                        # the gutter's marker column, in characters
MARK_PREFIX = "chk"                     # Tk marks chk0, chk1, … on each checked line
TAG_MARKER = "marker"                   # gutter canvas items that are markers
SELECTION_BACKGROUND = THEME["editor.selection"]
INACTIVE_SELECTION = THEME["editor.inactiveSelection"]
CHOSEN_BACKGROUND = THEME["list.activeSelection"]   # the problems panel's chosen row
LINK_FOREGROUND = THEME["link"]         # problems panel links (03 §3)
TAG_LINE = "current_line"               # the cursor's line, under jump and sel
TAG_JUMP = "jump"
TAG_HINT = "hint"
TAG_LINK = "link"                       # the location before the first ":" of a link
TAG_GAP = "gap"                         # 8 px above every paragraph but the first
TAG_CHOSEN = "chosen"                   # the selected paragraph while the panel has focus
TAG_CLICK = "clickable"                 # every clickable paragraph: the pointer is a hand
PARAGRAPH_PREFIX = "para"               # one tag per paragraph: para0, para1, …
TAG_ICON_ROW = "iconrow"                # a row with a severity icon: wrapped lines indent
SEVERITY_ICON_PX = 14                   # Problems' severity icons (08 §7)
SEVERITY_ICON_GAP = 8                   # around an icon, half either side
PARAGRAPH_GAP = 8


def plural(count: int, word: str) -> str:
    """``1 file``, ``2 files`` (I-14)."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def line_of(index: str) -> int:
    return int(str(index).split(".")[0])
