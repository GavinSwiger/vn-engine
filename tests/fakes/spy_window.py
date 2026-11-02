"""``SpyWindow``: stands in for ``pygame.Window`` and records what ``GameWindow`` does.

Calls are forwarded to a real window, except ``show``, ``set_fullscreen``,
``set_windowed``, and ``maximize``: the dummy driver has no real fullscreen, and on a real
display the window stays hidden and never takes over the screen (04-technical §14.2).
"""

import contextlib

import pygame

REAL_WINDOW = pygame.Window


class SpyWindow:
    """Records calls in ``SpyWindow.log`` (class-level, reset per test)."""

    log: list[tuple] = []
    instances: list["SpyWindow"] = []

    def __init__(self, *args, **kwargs):
        object.__setattr__(self, "_real", REAL_WINDOW(*args, **kwargs))
        object.__setattr__(self, "_surface", None)
        SpyWindow.log.append(("create", kwargs))
        SpyWindow.instances.append(self)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        SpyWindow.log.append(("set " + name, value))
        setattr(self._real, name, value)

    def get_surface(self):
        surface = self._real.get_surface()
        object.__setattr__(self, "_surface", surface)
        return surface

    def flip(self):
        surface = self._surface if self._surface is not None else self._real.get_surface()
        SpyWindow.log.append(("flip", tuple(surface.get_at((0, 0)))[:3]))
        self._real.flip()

    def show(self):
        SpyWindow.log.append(("show",))

    def set_fullscreen(self, desktop=False):
        SpyWindow.log.append(("set_fullscreen", desktop))

    def set_windowed(self):
        SpyWindow.log.append(("set_windowed",))

    def maximize(self):
        SpyWindow.log.append(("maximize",))

    def destroy(self):
        SpyWindow.log.append(("destroy",))
        self._real.destroy()



    @classmethod
    @contextlib.contextmanager
    def installed(cls, monkeypatch):
        """Replace ``pygame.Window`` for the duration; destroy every real window after."""
        cls.log = []
        cls.instances = []
        monkeypatch.setattr(pygame, "Window", cls)
        try:
            yield cls
        finally:
            for spy in cls.instances:
                try:
                    spy._real.destroy()
                except pygame.error:
                    pass
