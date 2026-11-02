"""``FakeWindow``: a ``WindowPort`` whose framebuffer size the test controls (04-technical §14.3).

Headless tests that need size changes inject this instead of resizing a real dummy-driver
window. ``framebuffer()`` returns a plain ``pygame.Surface`` (a new object after every
``resize``), a 0×0 surface after ``resize(0, 0)``, or ``None`` after ``set_unavailable()``.
``flip()`` records the frame and lets the test probe pixels at that moment;
``set_fullscreen`` / ``toggle_fullscreen`` / ``maximize`` / ``restore`` record calls and
change the size the way a window manager would. ``windowed_size`` follows ``GameWindow``'s
rule (F16 Conflict 7): ``user_resize`` is a resize the player made (it reports
WINDOWSIZECHANGED). Plain surfaces work under the dummy driver with no display mode.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pygame


@dataclass
class FlipRecord:
    index: int                                   # 1-based flip count
    size: tuple[int, int]                        # framebuffer size at the flip
    title: str
    probes: dict[tuple[int, int], tuple[int, int, int]] = field(default_factory=dict)


class FakeWindow:
    """Implements ``engine.render.window.WindowPort``."""

    def __init__(self, size: tuple[int, int] = (1280, 720), *,
                 desktop: tuple[int, int] = (1920, 1080),
                 probe_points: Sequence[tuple[int, int]] = (),
                 on_flip: Callable[["FakeWindow"], None] | None = None,
                 start_fullscreen: bool = False,
                 initial_size_for_restore: tuple[int, int] | None = None) -> None:
        self.title = ""
        self._size = tuple(size)
        self._surface: pygame.Surface | None = pygame.Surface(self._size)
        self._available = True
        self.desktop = tuple(desktop)
        self.probe_points = list(probe_points)
        self.on_flip = on_flip
        self.flips: list[FlipRecord] = []
        self.calls: list[str] = []
        self.icons: list[pygame.Surface] = []
        self.window_events: list[int] = []
        self.destroyed = False
        self._fullscreen = False
        self._restore_size: tuple[int, int] | None = None
        self._restore_maximized = False
        self.maximized = False
        # F16: GameWindow's windowed-size rule (``windowed_size``).
        self._initial_size_for_restore = tuple(initial_size_for_restore or self._size)
        self._last_windowed = self._size
        if start_fullscreen:
            self._last_windowed = self._initial_size_for_restore
            self._fullscreen = True
            self.resize(*self.desktop)

    # -- test controls --

    def resize(self, width: int, height: int) -> None:
        """New framebuffer size (a new Surface object, like a real resize would give)."""
        self._size = (width, height)
        self._available = True
        self._surface = pygame.Surface((max(width, 0), max(height, 0)))

    def user_resize(self, width: int, height: int) -> None:
        """The player resized the window (``resize``, then WINDOWSIZECHANGED)."""
        self.resize(width, height)
        self.note_window_event(pygame.WINDOWSIZECHANGED)

    def set_unavailable(self) -> None:
        """``framebuffer()`` returns None from now on (until the next ``resize``)."""
        self._available = False

    # -- WindowPort --

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    @property
    def fullscreen(self) -> bool:
        return self._fullscreen

    def framebuffer(self) -> pygame.Surface | None:
        return self._surface if self._available else None

    def flip(self) -> None:
        self.calls.append("flip")
        surface = self._surface
        probes = {}
        for x, y in self.probe_points:
            if surface is not None and 0 <= x < surface.get_width() and 0 <= y < surface.get_height():
                probes[(x, y)] = tuple(surface.get_at((x, y)))[:3]
        self.flips.append(FlipRecord(len(self.flips) + 1, self._size, self.title, probes))
        if self.on_flip is not None:
            self.on_flip(self)

    def toggle_fullscreen(self) -> None:
        self.set_fullscreen(not self._fullscreen)

    def set_fullscreen(self, on: bool) -> None:
        if on == self._fullscreen:
            return
        if on:
            self.calls.append("set_fullscreen")
            if not self.maximized:
                self._last_windowed = self._size
            self._restore_size = self._size
            self._restore_maximized = self.maximized
            self._fullscreen = True
            self.resize(*self.desktop)
        else:
            self.calls.append("set_windowed")
            self._fullscreen = False
            restore = self._restore_size
            self._restore_size = None
            self.resize(*(restore or self._initial_size_for_restore))

    def maximize(self) -> None:
        self.calls.append("maximize")
        self.maximized = True
        self.resize(*self.desktop)

    def restore(self) -> None:
        """Leave the maximized state (WINDOWRESTORED): back to the last windowed size."""
        self.calls.append("restore")
        self.maximized = False
        self.resize(*self._last_windowed)

    def windowed_size(self) -> tuple[int, int] | None:
        if self._fullscreen:
            return None if self._restore_maximized and self._restore_size else self._last_windowed
        return None if self.maximized else self._last_windowed

    def set_icon(self, surface: pygame.Surface) -> None:
        self.calls.append("set_icon")
        self.icons.append(surface)

    def points_to_pixels(self, pos: tuple[float, float]) -> tuple[float, float]:
        return pos

    def note_window_event(self, event_type: int) -> None:
        self.window_events.append(event_type)
        if event_type == pygame.WINDOWMAXIMIZED:
            self.maximized = True
        elif event_type == pygame.WINDOWRESTORED:
            self.maximized = False
        elif (event_type == pygame.WINDOWSIZECHANGED and not self._fullscreen
              and not self.maximized):
            self._last_windowed = self._size

    def destroy(self) -> None:
        self.calls.append("destroy")
        self.destroyed = True
