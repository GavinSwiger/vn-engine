"""``PlaceholderScreen``: what F01 shows instead of a game (PR-F01-52).

Why this module exists: until F03/F04/F10 provide a title menu and the story, the first
launch must still show that the engine works: the game's title in the middle of the
canvas and the engine version in the corner, readable and with high contrast (§7.16).
``engine/app/bootstrap.py: build_initial_screens`` is the one place that later replaces it.
"""

from engine.core.constants import CANVAS_SIZE
from engine.core.redact import escape_controls
from engine.render.canvas import Canvas
from engine.render.text import FontSpec
from engine.ui.screen import Screen

BACKGROUND = (0x20, 0x20, 0x20)          # #202020
TITLE_COLOR = (0xE0, 0xE0, 0xE0)         # #E0E0E0, about 12.6:1 on the background
VERSION_COLOR = (0xA0, 0xA0, 0xA0)       # #A0A0A0, about 6.2:1 on the background
TITLE_FONT = FontSpec(None, 48)
VERSION_FONT = FontSpec(None, 20)
SIDE_MARGIN = 80                         # canvas units; the title spans at most 1120
CORNER_MARGIN = 16                       # the version sits 16 units from the right and bottom
TITLE_MAX_LINES = 2


class PlaceholderScreen(Screen):
    opaque = True

    def __init__(self, *, title: str, engine_version: str) -> None:
        self.title = escape_controls(title)
        self.engine_version = engine_version

    def draw(self, canvas: Canvas) -> None:
        width, height = CANVAS_SIZE
        canvas.fill(BACKGROUND)
        canvas.draw_text(self.title, TITLE_FONT, TITLE_COLOR, (width / 2, height / 2),
                         anchor="center", max_width=width - 2 * SIDE_MARGIN, align="center",
                         max_lines=TITLE_MAX_LINES)
        canvas.draw_text(f"vn-engine {self.engine_version}", VERSION_FONT, VERSION_COLOR,
                         (width - CORNER_MARGIN, height - CORNER_MARGIN), anchor="bottomright")
