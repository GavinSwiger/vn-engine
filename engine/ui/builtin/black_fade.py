"""``BlackFadeScreen``: the screens below fade to black, then the shell moves on (F10 ``04``
§7.5, §7.7.4, §7.7.5).

Why this module exists: the story end (1,000 ms) and Main Menu → Yes (``ui.fade_ms``) both
take the game picture to black before the title cuts in, and neither may take input while
they run (``03`` "Motion and timing"). This screen sits on top of the in-game screens, is not
opaque (they still draw under it), is not ``in_game`` (so the story holds), consumes every
event, and darkens the canvas with one ``BLEND_RGB_MULT`` fill per frame (``to_black``).
When the fade is done it calls ``then``, which replaces the stack. Under reduced motion the
shell calls ``then`` itself and never pushes this screen, so no black frame is drawn.

Progress runs on game time from the frame after the push, as every F10 fade does.
"""

from collections.abc import Callable
from typing import Final

from engine.render.canvas import Canvas
from engine.render.frames import to_black
from engine.ui.input import UiEvent
from engine.ui.screen import Screen

_EPSILON: Final = 1e-9


class BlackFadeScreen(Screen):
    """Darkens everything below over ``seconds``, then runs ``then`` once."""

    opaque = False
    in_game = False
    holds_notices = True                   # F11 C7: new notices wait for the next screen

    def __init__(self, seconds: float, then: Callable[[], None]) -> None:
        self.seconds = max(0.0, float(seconds))
        self.then = then
        self.t = 0.0 if self.seconds > 0 else 1.0
        self.done = False
        self._fresh = True                 # the push frame does not advance the fade

    def handle_event(self, event: UiEvent) -> bool:
        return True                        # no input while the fade runs (03 Motion)

    def update(self, dt: float, *, is_top: bool) -> None:
        if self.done:
            return
        fresh, self._fresh = self._fresh, False
        if not fresh and self.seconds > 0:
            self.t = min(1.0, self.t + dt / self.seconds)
        if self.t >= 1.0 - _EPSILON:
            self.t = 1.0
            self.done = True
            self.then()

    def draw(self, canvas: Canvas) -> None:
        surface = canvas.surface
        assert surface is not None
        to_black(surface, self.t)


__all__ = ["BlackFadeScreen"]
