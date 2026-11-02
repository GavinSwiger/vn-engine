"""``ErrorScreen``: the in-window error screen (PR-F01-41 to 45, §7.12).

Why this module exists: when startup or the game fails, the player and the author must see
what went wrong in the game window, in plain words, with the game's name and version and
where the log file is, and be able to quit with one key or copy the details to send them
(PR-F01-45). Everything shown or copied may contain content and paths, so every string is
redacted and escaped here, whatever the caller did (SEC-F01-11), and the message is cut to
``ERROR_MESSAGE_MAX_CHARS`` before any layout (SEC-F01-21).

This is the **only** module in ``engine/`` that writes the clipboard, and it never reads it
(SEC-F01-19). There is no ``pygame.scrap.init()``: it raises with ``pygame.Window``, and
``put_text`` works without it (S0 note 5).

F30 (``04`` §6.5): the page's constants and drawing are in ``error_look.py``, shared with the
fake crash; this screen keeps its redaction, cut notice, hint, input, and the clipboard.
"""

import sys
from collections.abc import Callable, Sequence

import pygame

from engine.core.constants import CLIPBOARD_MAX_BYTES, ERROR_MESSAGE_MAX_CHARS
from engine.core.logsetup import get_logger
from engine.core.redact import escape_controls, redact, truncate
from engine.render.canvas import Canvas
from engine.ui.builtin import error_look
from engine.ui.builtin.error_look import (  # noqa: F401  (re-exported: F01's names)
    BACKGROUND,
    DETAIL_COLOR,
    HEADING,
    HEADING_COLOR,
    HEADING_FONT,
    HEADING_Y,
    HINT_COLOR,
    HINT_Y,
    LEFT,
    LOG_Y,
    MESSAGE_BOTTOM,
    MESSAGE_COLOR,
    MESSAGE_Y,
    TEXT_FONT,
    TEXT_WIDTH,
    TITLE_Y,
)
from engine.ui.input import UiEvent
from engine.ui.screen import Screen

COPIED_SECONDS = 2.0

CUT_NOTICE = "… (the full message is in the log file)"
HINT_QUIT = "Press Esc or Enter to quit"
HINT_COPY = "Press C to copy the details"
HINT_COPIED = "Copied"
HINT_COPY_FAILED = "Copy failed — please send the log file"
HINT_SEPARATOR = "   ·   "

_QUIT_KEYS = (pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER)
_NO_COPY_MODS = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_GUI

_log = get_logger("ui")


def _clean(text: str) -> str:
    return escape_controls(redact(text))


class ErrorScreen(Screen):
    opaque = True

    def __init__(self, *, message: str, game_title: str, game_version: str,
                 log_display_path: str, tail: Callable[[], Sequence[str]],
                 on_quit: Callable[[], None], engine_version: str) -> None:
        """Every string argument is passed through redact() and escape_controls() here,
        whatever the caller did (SEC-F01-11). message is cut to ERROR_MESSAGE_MAX_CHARS
        before wrapping (SEC-F01-21)."""
        self.message = truncate(escape_controls(redact(message), allow_newline=True),
                                ERROR_MESSAGE_MAX_CHARS)
        self.game_title = _clean(game_title)
        self.game_version = _clean(game_version)
        self.log_display_path = _clean(log_display_path)
        self.engine_version = _clean(engine_version)
        self._tail = tail
        self._on_quit = on_quit
        self._copy_state: str | None = None       # None, "copied", or "failed"
        self._copied_left = 0.0
        self._message_blocks: list[str] | None = None

    # -- text --

    @property
    def title_line(self) -> str:
        return error_look.title_line(self.game_title, self.game_version)

    @property
    def log_line(self) -> str:
        return f"Log file: {self.log_display_path}"

    @property
    def hint_line(self) -> str:
        if self._copy_state == "copied":
            second = HINT_COPIED
        elif self._copy_state == "failed":
            second = HINT_COPY_FAILED
        else:
            second = HINT_COPY
        return HINT_QUIT + HINT_SEPARATOR + second

    # -- input and time --

    def handle_event(self, event: UiEvent) -> bool:
        raw = event.raw
        if raw.type != pygame.KEYDOWN:
            return False            # mouse input never copies
        if raw.key in _QUIT_KEYS:
            self._on_quit()
            return True
        if raw.key == pygame.K_c and not getattr(raw, "mod", 0) & _NO_COPY_MODS:
            self.copy_details()
            return True
        return False

    def update(self, dt: float, *, is_top: bool) -> None:
        if self._copy_state == "copied":
            self._copied_left -= dt
            if self._copied_left <= 1e-9:
                self._copy_state = None

    # -- clipboard (PR-F01-45, SEC-F01-19) --

    def details_text(self) -> str:
        """The redacted copy text, at most CLIPBOARD_MAX_BYTES of UTF-8: the oldest tail
        lines go first, then the message is cut."""
        about = (f'"{self.game_title}" version {self.game_version} | '
                 f"vn-engine {self.engine_version} | Python {_python_version()} | "
                 f"pygame-ce {_pygame_version()}")
        tail = list(self._tail())
        message = self.message

        def build() -> str:
            return redact(message + "\n\n" + about + "\nLog file: " + self.log_display_path
                          + "\n\n" + "\n".join(tail))

        text = build()
        while len(text.encode("utf-8")) > CLIPBOARD_MAX_BYTES and tail:
            tail.pop(0)
            text = build()
        while len(text.encode("utf-8")) > CLIPBOARD_MAX_BYTES and message:
            excess = len(text.encode("utf-8")) - CLIPBOARD_MAX_BYTES
            message = truncate(message, max(0, len(message) - max(excess, 2)))
            text = build()
        return text

    def copy_details(self) -> None:
        try:
            text = self.details_text()
            pygame.scrap.put_text(text)
        except Exception:
            _log.debug("Copying the error details failed", exc_info=True)
            self._copy_state = "failed"
            return
        self._copy_state = "copied"
        self._copied_left = COPIED_SECONDS

    # -- drawing (§7.12 step 4) --

    def draw(self, canvas: Canvas) -> None:
        if self._message_blocks is None:
            self._message_blocks = error_look.fit_message(canvas, self.message,
                                                          cut_notice=CUT_NOTICE)
        error_look.draw_page(canvas, lines=self._message_blocks, title_line=self.title_line,
                             log_line=self.log_line, hint=self.hint_line, label=None)


def _python_version() -> str:
    return ".".join(str(part) for part in sys.version_info[:3])


def _pygame_version() -> str:
    try:
        return str(pygame.version.ver)
    except AttributeError:
        return "unknown"
