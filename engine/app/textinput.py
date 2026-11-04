"""``TextInputOwner``: the one owner of SDL text input, the IME rect and clipboard reads
(F52 ``04`` §4.3, ``07`` §3.6, I-2, I-10; W2).

Why this module exists: an IME window must never pop up while the player reads, and two
switches (a widget and the console, say) would disagree about whether typing is on. So
nothing else in ``engine/`` calls ``pygame.key.start_text_input``, ``stop_text_input``,
``set_text_input_rect`` or ``pygame.scrap.get_text`` (a grep test, AC-F52-13). Once per
frame (``sync``, after the screens and the notice layer) the owner works out what wants
typing and changes SDL only when that changes:

1. OFF while the window is unfocused or in error mode. Otherwise F40's open console, else
   ``stack.top.text_target()``: a focused text field, ``LEGACY_TEXT`` (a running minigame
   plugin below API 1.4: text input stays on with no IME rect, as before F52), or None.
2. A target that changes from field A calls ``A.text_lost()`` (the composition is dropped);
   between two fields SDL is stopped and started again, which resets the IME.
3. ``start_text_input`` / ``stop_text_input`` only on a change.
4. The target's ``ime_rect()`` (canvas units) → framebuffer pixels (``Viewport``) → window
   units (``WindowPort.pixels_to_points``); ``set_text_input_rect`` only when that changes.

``read_clipboard`` is the player's paste key's only read: text only, cut to 4,000 code
points before anything else, "" on any failure; never logged, echoed or kept. The owner is
made only with a real window (none headless) and stops text input before the first frame
(pygame-ce starts it by default). ``SDL_IME_SHOW_UI=1`` is set by ``cli.prepare_environment``.
"""

from typing import TYPE_CHECKING, Any, Final

import pygame

from engine.ui.screen import LEGACY_TEXT

if TYPE_CHECKING:
    from engine.app.app import App

CLIPBOARD_MAX: Final = 4_000
_OFF: Final = None


def read_clipboard(scrap: Any = None) -> str:
    """The clipboard's text, cut to 4,000 code points at once; "" when there is none or it
    can't be read. Never logged."""
    scrap = scrap if scrap is not None else pygame.scrap
    try:
        text = scrap.get_text()
    except Exception:                       # noqa: BLE001 (pygame.error, no clipboard)
        return ""
    if isinstance(text, bytes):
        text = text[:CLIPBOARD_MAX * 4].decode("utf-8", "replace")
    return text[:CLIPBOARD_MAX] if isinstance(text, str) else ""


class TextInputOwner:
    """The App's text input owner (module docstring). ``key`` and ``scrap`` are
    ``pygame.key`` and ``pygame.scrap`` (fakes in tests)."""

    def __init__(self, app: "App", *, key: Any = None, scrap: Any = None) -> None:
        self.app = app
        self.key = key if key is not None else pygame.key
        self.scrap = scrap if scrap is not None else pygame.scrap
        self.on = False
        self.target: object = _OFF
        self.rect: tuple[int, int, int, int] | None = None
        self.key.stop_text_input()

    # -- the clipboard --

    def read_clipboard(self) -> str:
        return read_clipboard(self.scrap)

    # -- once per frame --

    def wanted(self) -> object:
        """What wants typing now (module docstring step 1)."""
        app = self.app
        if not app.focused or app.error_mode:
            return _OFF
        console = app.console if app.dev else None
        if console is not None and getattr(console, "open", False):
            return console
        top = app.screens.top
        finder = getattr(top, "text_target", None)
        return finder() if callable(finder) else _OFF

    def sync(self) -> None:
        target = self.wanted()
        old = self.target
        if target is not old:
            lost = getattr(old, "text_lost", None)
            if old is not _OFF and old is not LEGACY_TEXT and callable(lost):
                lost()
            if self.on and target is not _OFF:
                self.key.stop_text_input()           # between two fields: reset the IME
                self.on = False
            self.target = target
            self.rect = None
        want_on = target is not _OFF
        if want_on != self.on:
            if want_on:
                self.key.start_text_input()
            else:
                self.key.stop_text_input()
            self.on = want_on
        if not want_on or target is LEGACY_TEXT:
            return
        rect = self._window_rect(target)
        if rect is not None and rect != self.rect:
            self.rect = rect
            self.key.set_text_input_rect(pygame.Rect(rect))

    def _window_rect(self, target: object) -> tuple[int, int, int, int] | None:
        ime = getattr(target, "ime_rect", None)
        viewport = self.app.viewport
        if not callable(ime) or viewport is None:
            return None
        box = ime()
        if box is None:
            return None
        x, y, w, h = viewport.canvas_to_window((box.x, box.y, box.w, box.h))
        window = self.app.window
        left, top = window.pixels_to_points((x, y))
        right, bottom = window.pixels_to_points((x + w, y + h))
        return (round(left), round(top), max(1, round(right - left)),
                max(1, round(bottom - top)))


__all__ = ["CLIPBOARD_MAX", "TextInputOwner", "read_clipboard"]
