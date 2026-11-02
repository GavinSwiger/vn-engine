"""Global hotkeys and raw pygame event → ``UiEvent`` translation (§7.8 steps 3–4).

Why this module exists: a few keys belong to the App, not to any screen, and must work on
every screen including the error screen: F11, Alt+Enter, and Alt+keypad-Enter (and
Ctrl+Cmd+F on macOS) toggle fullscreen (PR-F01-27), and F3 toggles the dev overlay
(PR-F01-51). Esc is deliberately not one of them (PR-F01-33, F10 owns it), and no hotkey is
a bare letter, so text input stays safe. Everything else reaches the top screen as a
``UiEvent`` whose mouse position is in canvas units (PR-F01-24).

Game controllers (F05 ``04`` §3.2 and R2, added by F10 per I-14): SDL reports a pad only
after it is opened, so ``Controllers`` opens each one on ``CONTROLLERDEVICEADDED`` (pads
plugged in before the launch arrive that way too) and lets it go on removal. The module is
``pygame._sdl2.controller`` (experimental in pygame-ce 2.5): if it is missing or fails to
start, gamepads are off with one log line and keyboard and mouse work as before.
"""

import sys

import pygame

from engine.core.geometry import Viewport
from engine.core.logsetup import get_logger
from engine.render.window import WindowPort
from engine.ui.input import UiEvent

_log = get_logger("app")

_MODIFIERS = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_SHIFT | pygame.KMOD_GUI
MOUSE_EVENTS = (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                pygame.MOUSEWHEEL)


def is_fullscreen_hotkey(event: pygame.event.Event) -> bool:
    """F11 alone; Alt+Enter or Alt+keypad-Enter; Ctrl+Cmd+F on macOS (PR-F01-27)."""
    if event.type != pygame.KEYDOWN:
        return False
    key = event.key
    mods = getattr(event, "mod", 0)
    if key == pygame.K_F11:
        return not mods & _MODIFIERS
    if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
        return bool(mods & pygame.KMOD_ALT)
    if key == pygame.K_f and sys.platform == "darwin":
        return bool(mods & pygame.KMOD_CTRL) and bool(mods & pygame.KMOD_META)
    return False


def is_overlay_hotkey(event: pygame.event.Event) -> bool:
    """F3 with no modifier (the App also requires dev mode)."""
    return (event.type == pygame.KEYDOWN and event.key == pygame.K_F3
            and not getattr(event, "mod", 0) & _MODIFIERS)


def translate(event: pygame.event.Event, viewport: Viewport | None,
              window: WindowPort) -> UiEvent:
    """Mouse events get their position in canvas units; ``in_canvas`` is False in the
    letterbox bars and before any viewport is bound. Other events carry no position."""
    if event.type not in MOUSE_EVENTS or viewport is None:
        return UiEvent(event, None, False)
    pos = getattr(event, "pos", None)
    if pos is None:                       # MOUSEWHEEL has no position of its own
        try:
            pos = pygame.mouse.get_pos()
        except pygame.error:
            return UiEvent(event, None, False)
    canvas_pos, inside = viewport.window_to_canvas(*window.points_to_pixels(pos))
    return UiEvent(event, canvas_pos, inside)


class Controllers:
    """The open game controllers of one session."""

    def __init__(self) -> None:
        self._module = None
        self._failed = False
        self._open: list = []

    @property
    def count(self) -> int:
        return len(self._open)

    def start(self) -> bool:
        """Start SDL's game-controller support once; False (and one INFO line) when it is
        unavailable, after which nothing is tried again."""
        if self._module is not None:
            return True
        if self._failed:
            return False
        try:
            from pygame._sdl2 import controller

            if not controller.get_init():
                controller.init()
        except Exception as exc:                          # missing module, SDL failure
            self._failed = True
            _log.info("Gamepads are off: game controller support didn't start (%s)",
                      type(exc).__name__)
            return False
        self._module = controller
        return True

    def handle(self, event: pygame.event.Event) -> None:
        """Open the pad of a ``CONTROLLERDEVICEADDED``; close every detached pad on a
        ``CONTROLLERDEVICEREMOVED``."""
        if event.type == pygame.CONTROLLERDEVICEADDED:
            index = getattr(event, "device_index", None)
            if index is None or not self.start():
                return
            try:
                pad = self._module.Controller(index)       # type: ignore[union-attr]
            except Exception:
                _log.debug("Gamepad %s could not be opened", index)
                return
            if all(pad is not other for other in self._open):
                self._open.append(pad)
        elif event.type == pygame.CONTROLLERDEVICEREMOVED:
            for pad in list(self._open):
                try:
                    attached = pad.attached()
                except Exception:
                    attached = False
                if not attached:
                    self._open.remove(pad)
                    try:
                        pad.quit()
                    except Exception:
                        _log.debug("A removed gamepad could not be closed", exc_info=True)
