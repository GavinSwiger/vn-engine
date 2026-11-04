"""The game window: hidden-first creation, title, icon, fullscreen and restore, framebuffer.

Why this module exists: the window is where several player promises meet. The first
frame must be the letterbox color, never white (PR-F01-19); the title must show any
script exactly (PR-F01-14, 15); fullscreen is borderless desktop fullscreen with no mode
change, and leaving it restores the previous size, position, and maximized state
(PR-F01-27..31). ``GameWindow`` wraps one ``pygame.Window`` (pygame-ce ≥ 2.5.2) and keeps
those rules in one place. It also remembers the window's last windowed size
(``windowed_size``, F16 Conflict 7), which F16 stores at quit so the next launch opens the
window at the size the player left it. ``App`` depends only on ``WindowPort``, so tests inject
``tests/fakes/fake_window.py: FakeWindow`` to change the framebuffer size deterministically
(04-technical §14.3).

pygame-ce 2.5.8 facts this module relies on (spike S0, ``tests/perf/S0-results.md``):
``Window.get_surface()`` returns the same Surface object after a resize (only its size
changes), and ``convert_alpha()`` works only after ``get_surface()`` has been called once,
which the constructor does before anything is loaded.
"""

import sys
from typing import Protocol, runtime_checkable

import pygame

from engine.core.constants import MIN_WINDOW_SIZE
from engine.core.errors import EngineError
from engine.core.logsetup import get_logger

RGB = tuple[int, int, int]

_log = get_logger("window")

# C0 controls and U+007F would cut the title at a NUL or show as garbage in the title bar.
_TITLE_CONTROLS = {cp: "�" for cp in (*range(0x20), 0x7F)}


def sanitize_title(title: str) -> str:
    """The title with C0 control characters and U+007F replaced by U+FFFD (PR-F01-15)."""
    return title.translate(_TITLE_CONTROLS)


class WindowCreationError(EngineError):
    """The OS window could not be created (no display, graphics failure, …)."""


@runtime_checkable
class WindowPort(Protocol):
    """What App needs from a window. GameWindow implements it; tests inject FakeWindow
    (§14.3)."""

    title: str

    @property
    def size(self) -> tuple[int, int]: ...          # window units (points on macOS)

    @property
    def fullscreen(self) -> bool: ...

    def framebuffer(self) -> pygame.Surface | None: ...

    def flip(self) -> None: ...

    def toggle_fullscreen(self) -> None: ...

    def set_fullscreen(self, on: bool) -> None: ...

    def set_icon(self, surface: pygame.Surface) -> None: ...

    def points_to_pixels(self, pos: tuple[float, float]) -> tuple[float, float]: ...

    def pixels_to_points(self, pos: tuple[float, float]) -> tuple[float, float]: ...

    def note_window_event(self, event_type: int) -> None: ...

    def windowed_size(self) -> tuple[int, int] | None:
        """The size the window has, or returns to, when windowed and not maximized (window
        units). None while that is unknown: maximized, or fullscreen entered from a
        maximized window (F16 ``04`` §5.4, ``07`` G12)."""
        ...

    def destroy(self) -> None: ...


class _Restore:
    """Windowed geometry saved when entering fullscreen."""

    __slots__ = ("position", "size", "maximized")

    def __init__(self, position: tuple[int, int], size: tuple[int, int],
                 maximized: bool) -> None:
        self.position = position
        self.size = size
        self.maximized = maximized


class GameWindow:
    """The single game window (implements ``WindowPort``)."""

    def __init__(self, *, title: str, size: tuple[int, int], resizable: bool,
                 start_fullscreen: bool, letterbox_color: RGB,
                 initial_size_for_restore: tuple[int, int],
                 position: tuple[int, int] | None = None) -> None:
        """pygame.Window(hidden=True, allow_high_dpi=True, resizable=…,
        position=``position`` or WINDOWPOS_CENTERED); minimum_size = MIN_WINDOW_SIZE; optional
        set_fullscreen(desktop=True); fill framebuffer with letterbox_color; flip(); show()
        (PR-F01-19). Raises WindowCreationError (wraps pygame.error).

        ``position`` (F39 PR-F39-09): the window's top-left corner in desktop coordinates,
        where an updated preview reopens the old window; None centers it. Only the windowed
        position: a fullscreen start still covers the display."""
        self._initial_size_for_restore = tuple(initial_size_for_restore)
        self._fullscreen = False
        self._restore: _Restore | None = None
        self._destroyed = False
        self.maximized = False      # tracked from WINDOWMAXIMIZED / WINDOWRESTORED events
        # F16: the last windowed, not maximized size (``windowed_size``). A size change
        # reported just before WINDOWMAXIMIZED (SDL sends it first) is undone by that event.
        self._last_windowed = self._initial_size_for_restore
        self._before_size_change: tuple[int, int] | None = None
        try:
            self._window = pygame.Window(
                title=sanitize_title(title), size=tuple(size),
                position=(pygame.WINDOWPOS_CENTERED if position is None
                          else (int(position[0]), int(position[1]))),
                hidden=True, allow_high_dpi=True,
                resizable=resizable)
        except pygame.error as exc:
            raise WindowCreationError(f"The game window could not be created: {exc}") from exc
        try:
            self._window.minimum_size = MIN_WINDOW_SIZE
            if not start_fullscreen:
                self._last_windowed = tuple(self._window.size)
            if start_fullscreen:
                self._window.set_fullscreen(desktop=True)
                self._fullscreen = True
            # The first get_surface() also sets pygame's convert format (S0 note 3).
            framebuffer = self._window.get_surface()
            framebuffer.fill(letterbox_color)
            self._window.flip()
            self._window.show()
        except pygame.error as exc:
            self.destroy()
            raise WindowCreationError(f"The game window could not be created: {exc}") from exc

    # -- title and icon --

    @property
    def title(self) -> str:
        return self._window.title

    @title.setter
    def title(self, value: str) -> None:
        """Replaces C0 controls and U+007F with U+FFFD, then applies (PR-F01-15, F30)."""
        self._window.title = sanitize_title(value)

    def set_icon(self, surface: pygame.Surface) -> None:
        """Any surface format works; SDL converts window icons itself."""
        self._window.set_icon(surface)

    # -- geometry --

    @property
    def size(self) -> tuple[int, int]:
        """Window size in window units (points on macOS, pixels elsewhere)."""
        return tuple(self._window.size)

    @property
    def position(self) -> tuple[int, int]:
        return tuple(self._window.position)

    @property
    def fullscreen(self) -> bool:
        return self._fullscreen

    def framebuffer(self) -> pygame.Surface | None:
        """window.get_surface(), fetched each frame. pygame.error → None."""
        if self._destroyed:
            return None
        try:
            return self._window.get_surface()
        except pygame.error:
            return None

    def flip(self) -> None:
        self._window.flip()

    def points_to_pixels(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Window units → framebuffer pixels (2× on a Retina Mac; 1× on Windows with
        per-monitor DPI awareness)."""
        framebuffer = self.framebuffer()
        width, height = self._window.size
        if framebuffer is None or width <= 0 or height <= 0:
            return pos
        fw, fh = framebuffer.get_size()
        if (fw, fh) == (width, height):
            return pos
        return pos[0] * fw / width, pos[1] * fh / height

    def pixels_to_points(self, pos: tuple[float, float]) -> tuple[float, float]:
        """F52 (04 §1 OQ-2): framebuffer pixels → window units (``points_to_pixels``'s
        inverse), where ``app/textinput`` places the IME window."""
        framebuffer = self.framebuffer()
        width, height = self._window.size
        if framebuffer is None:
            return pos
        fw, fh = framebuffer.get_size()
        if (fw, fh) == (width, height) or fw <= 0 or fh <= 0:
            return pos
        return pos[0] * width / fw, pos[1] * height / fh

    def note_window_event(self, event_type: int) -> None:
        """Track maximize (pygame.Window has no getter) and, on macOS, the fullscreen state
        set by the green button (R7: inferred from the size on each size change). F16: a
        size change while windowed and not maximized is the new ``windowed_size``."""
        undo, self._before_size_change = self._before_size_change, None
        if event_type == pygame.WINDOWMAXIMIZED:
            self.maximized = True
            if undo is not None:            # that size change was the maximize itself
                self._last_windowed = undo
        elif event_type == pygame.WINDOWRESTORED:
            self.maximized = False
        elif event_type == pygame.WINDOWSIZECHANGED:
            if sys.platform == "darwin":
                self._infer_fullscreen()
            if not self._fullscreen and not self.maximized:
                self._before_size_change = self._last_windowed
                self._last_windowed = self.size

    def windowed_size(self) -> tuple[int, int] | None:
        """The size the window has, or returns to, when windowed and not maximized (window
        units): the created size (``initial_size_for_restore`` when started fullscreen),
        then each windowed size change. None while maximized, and in a fullscreen entered
        from a maximized window (F16 ``04`` §5.4, ``07`` G12)."""
        if self._fullscreen:
            restore = self._restore
            return None if restore is not None and restore.maximized else self._last_windowed
        return None if self.maximized else self._last_windowed

    # -- fullscreen (§7.14) --

    def toggle_fullscreen(self) -> None:
        if self._fullscreen:
            self._leave_fullscreen()
        else:
            self._enter_fullscreen()

    def set_fullscreen(self, on: bool) -> None:
        if on != self._fullscreen:
            self.toggle_fullscreen()

    def _enter_fullscreen(self) -> None:
        if not self.maximized:
            self._last_windowed = self.size
        self._restore = _Restore(self.position, self.size, self.maximized)
        self._window.set_fullscreen(desktop=True)
        self._fullscreen = True
        width, height = self.size
        _log.info("Fullscreen on (%dx%d)", width, height)

    def _leave_fullscreen(self) -> None:
        self._window.set_windowed()
        self._fullscreen = False
        restore = self._restore
        self._restore = None
        if restore is not None and restore.maximized:
            self._window.maximize()
        elif restore is not None:
            self._window.size = restore.size
            self._window.position = restore.position
        else:                                   # started fullscreen (PR-F01-30)
            self._window.size = self._initial_size_for_restore
            self._window.position = pygame.WINDOWPOS_CENTERED
        width, height = self.size
        _log.info("Fullscreen off (%dx%d)", width, height)

    def _infer_fullscreen(self) -> None:
        try:
            desktop = pygame.display.get_desktop_sizes()
        except pygame.error:
            return
        self._fullscreen = self.size in [tuple(size) for size in desktop]

    # -- lifetime --

    def destroy(self) -> None:
        """Close the OS window. Safe to call more than once."""
        if self._destroyed:
            return
        self._destroyed = True
        try:
            self._window.destroy()
        except pygame.error:
            pass
