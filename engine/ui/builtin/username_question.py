"""F30's first-launch question about the player's name (F30 ``01`` PR-F30-06, UI-F30-05;
``04`` §6.7; ``05`` SEC-F30-08, Q6).

Why this module exists: an author who offers ``{username}`` must get the player's consent
before the name ever shows, and the consent must be a real choice, never a click carried
over from F33's content warning. The shell's pre-title slot (``GameShell._next_pre_title``,
after the warning, before the title) shows two screens:

- ``GroundScreen``: an opaque fill in the title's ground (its plain gradient), so nothing of
  the game or the title shows under the question.
- ``UsernameQuestion``: F10's ``ConfirmScreen`` in the game's theme with ``[words]``
  ``ask_username``, ``ask_username_yes`` ("Allow"), and ``ask_username_no`` ("Don't
  allow"), "Don't allow" focused. "Don't allow" and Back (Esc) store the answer at once
  (``on_answer(False)``); "Allow" stores ``on_answer(True)`` only when the press that
  activates it began after the question's first drawn frame (KEYDOWN, MOUSEBUTTONDOWN, or
  CONTROLLERBUTTONDOWN; a mouse click's press is its button-down) and ``CRASH_GUARD_S`` of
  drawn, focused time has passed; otherwise the press is ignored. After an answer the dialog
  closes and ``then`` runs (the shell's next pre-title step, else the title). Closing the
  window is "Don't allow" (``answer_on_quit``, called by ``install_fourthwall``'s quit
  guard before F16's settings are written).

Nothing here reads, stores, or shows the name itself.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

import pygame

from engine.core.constants import CRASH_GUARD_S
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.title_screen import draw_title_gradient
from engine.ui.input import UiEvent
from engine.ui.menu_screen import MenuShell
from engine.ui.nav import InputKind
from engine.ui.screen import Screen

if TYPE_CHECKING:
    from engine.render.canvas import Canvas

_PRESSES: Final = frozenset({pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN,
                             pygame.CONTROLLERBUTTONDOWN})
_EPSILON: Final = 1e-9


class GroundScreen(Screen):
    """The opaque title ground under the question (04 §6.7)."""

    opaque = True
    holds_notices = True

    def __init__(self, shell: MenuShell) -> None:
        self.shell = shell

    def handle_event(self, event: UiEvent) -> bool:
        return True

    def draw(self, canvas: "Canvas") -> None:
        draw_title_gradient(canvas, self.shell.theme.cfg.title)


class UsernameQuestion(ConfirmScreen):
    """The question. ``on_answer(allow)`` stores the choice (``UsernameGate.answer``);
    ``then`` runs once the dialog has left the stack."""

    holds_notices = True

    def __init__(self, shell: MenuShell, *, on_answer: Callable[[bool], None],
                 then: Callable[[], None]) -> None:
        self.on_answer = on_answer
        self.then = then
        self.answered: bool | None = None       # the stored answer, once given
        self._drawn = False                     # the first frame has been drawn
        self.drawn_s = 0.0                      # drawn, focused seconds since then
        self._focused = True
        self._press_fresh = False               # the activating press began after a draw
        self._mouse_fresh = False               # the button-1 press this click began with
        super().__init__(shell, shell.words.get("ask_username"), self._allow, self._deny,
                         yes="ask_username_yes", no="ask_username_no", by=InputKind.KEYS)

    # -- the guard (SEC-F30-08) --

    def handle_event(self, event: UiEvent) -> bool:
        kind = event.type
        if kind == pygame.WINDOWFOCUSLOST:
            self._focused = False
        elif kind == pygame.WINDOWFOCUSGAINED:
            self._focused = True
        if kind in _PRESSES:
            self._press_fresh = self._drawn
            if kind == pygame.MOUSEBUTTONDOWN:
                self._mouse_fresh = self._drawn
        elif kind == pygame.MOUSEBUTTONUP:
            self._press_fresh = self._mouse_fresh
            self._mouse_fresh = False
        return super().handle_event(event)

    @property
    def allow_ready(self) -> bool:
        """"Allow" may answer now (the press is fresh and the guard time has passed)."""
        return self._press_fresh and self.drawn_s >= CRASH_GUARD_S - _EPSILON

    def _choose_yes(self) -> None:
        if self.answered is not None or not self.allow_ready:
            return                              # ignored: no sound of an answer, no close
        self._answer(True)
        super()._choose_yes()

    def _choose_no(self) -> None:
        if self.answered is None:
            self._answer(False)
        super()._choose_no()

    def _answer(self, allow: bool) -> None:
        self.answered = allow
        self.on_answer(allow)

    def answer_on_quit(self) -> None:
        """The window closes while the question is open: "Don't allow" (Q6), unless the
        player already answered."""
        if self.answered is None:
            self._answer(False)

    def _allow(self) -> None:
        self.then()

    def _deny(self) -> None:
        self.then()

    # -- frame --

    def update(self, dt: float, *, is_top: bool) -> None:
        if self._drawn and self._focused and is_top:
            self.drawn_s += dt
        super().update(dt, is_top=is_top)

    def draw(self, canvas: "Canvas") -> None:
        super().draw(canvas)
        self._drawn = True


__all__ = ["GroundScreen", "UsernameQuestion"]
