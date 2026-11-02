"""``LoadFadeScreen``: a loaded game fades in from black (F11 ``04`` §7.6 "LoadFadeScreen";
PR-F11-34, UI-F11-15, C7).

Why this module exists: a load cuts the menus away at once (C8), and the restored scene
should not pop in under them; it fades in from black over ``[theme.save] load_fade_ms``
(300 by default) instead. ``GameShell.show_loaded_game`` puts this screen on top of the
in-game screens, except under reduce motion or with ``load_fade_ms = 0``, where the first
frame after the load is the full scene.

- **The burst under it.** ``in_game`` is True through the frame it was pushed in, so the
  next frame's pump releases the restore burst and the stage and textbox take it under the
  black; from that frame's ``update`` on it is False until the fade ends, so the story waits
  at the restored line (it would anyway) and the line types only once this screen is gone
  (the textbox isn't top).
- **The fade.** It draws ``to_black(surface, 1 − t)``; ``t`` is 0 in the push frame and in
  the burst frame (both black), then grows by ``dt / seconds``. At ``t = 1`` it removes
  itself in ``update``, so that frame draws the full scene.
- **Input.** It consumes every event (none reaches the textbox); any one ends the fade at
  the next ``update`` (after the burst frame, if it came before it).
- **Notices** wait while it is top (``holds_notices``, C7).
"""

from typing import Final

from engine.render.canvas import Canvas
from engine.render.frames import to_black
from engine.ui.input import UiEvent
from engine.ui.screen import Screen, ScreenStack

_EPSILON: Final = 1e-9


class LoadFadeScreen(Screen):
    """Fades the loaded game in from black over ``seconds`` (> 0), then leaves ``stack``."""

    opaque = False
    holds_notices = True                   # F11 C7: notices wait for the faded-in game

    def __init__(self, seconds: float, stack: ScreenStack) -> None:
        if seconds <= 0:
            raise ValueError("LoadFadeScreen needs a fade longer than 0 s")
        self.seconds = float(seconds)
        self.stack = stack
        self.in_game = True                # until the burst frame (see the module docstring)
        self.t = 0.0
        self.done = False
        self._updates = 0
        self._finish = False

    def handle_event(self, event: UiEvent) -> bool:
        self._finish = True                # any input ends the fade at the next update
        return True

    def update(self, dt: float, *, is_top: bool) -> None:
        if self.done:
            return
        self._updates += 1
        if self._updates == 1:
            return                         # the push frame: the burst is pumped next frame
        if self._updates == 2:
            self.in_game = False           # the burst was pumped this frame; t stays 0
        else:
            self.t = min(1.0, self.t + dt / self.seconds)
        if self._finish and self._updates >= 2:
            self.t = 1.0
        if self.t >= 1.0 - _EPSILON:
            self.t = 1.0
            self.done = True
            self.in_game = False
            self.stack.remove(self)

    def draw(self, canvas: Canvas) -> None:
        surface = canvas.surface
        assert surface is not None
        to_black(surface, 1.0 - self.t)


__all__ = ["LoadFadeScreen"]
