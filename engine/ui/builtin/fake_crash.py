"""``FakeCrashScreen``: F30's fake error page, the story's ``effect crash`` (F30
``04-technical.md`` §6.2, §6.5; ``05`` SEC-F30-05, -10; UI-F30-01 to 03).

Why this module exists: a horror story may pretend the game broke. The page must look exactly
like the engine's own error page (it draws with ``error_look``, the real screen's constants
and layout), yet stay honest: it is drawn on the game's canvas (never an OS dialog or a new
window), it has no log path, no copy hint, no clipboard, and no buttons, it always answers
the continue keys after a short guard, and closing the window quits at once. This module
never imports ``ui/builtin/error.py`` or pygame's clipboard module (TR-F30-03).

- **A story wait.** ``app/fourthwall.open_crash`` gives the ``FakeCrash`` wait to
  ``StageScreen`` and pushes this screen; ``on_continue`` presses that wait (the story goes
  on with F09's ``WaitDone``). The screen isn't ``in_game``, so the story, the stage (its
  effects and glitches), skip, auto, and F11's timer all hold under it (G3). When
  ``waiting()`` turns False without a continue (skip's ``finish_now``, a restore, New Game)
  the screen goes at once, with no fade; a real error replaces the whole stack.
- **States.** IN (fade only), GUARD, READY, OUT (fade only), then removed. Times count only
  in frames that were drawn while the window has focus (``focused``): the guard,
  ``CRASH_GUARD_S``, starts with the first update after the first draw, so a key held from
  the line before can't dismiss the page. Under reduced effects the page fades in and out
  over ``CRASH_FADE_S`` (``ease_in_out``) over the frozen story; otherwise it is one cut each
  way and every frame in between is the same.
- **Input.** Every event is consumed (no save, load, rollback, history, skip, auto, menu, or
  quick menu under it). In READY, F10's Activate or Back (Enter, keypad Enter, Space, Esc, pad
  A or B) or a left, middle, or right click inside the canvas continues once (G10: a click on
  the letterbox bars doesn't). The fullscreen hotkey is the App's, before any screen (G11).
- **Drawing.** The page is drawn once per viewport size and render quality into a cached
  surface (an offscreen ``Canvas``), then blitted; the message is laid out once
  (``fit_message`` with no cut notice: the last kept line ends in "…"). A failure while
  drawing reaches F01's fatal path, whose real error page never shows this message.
- **Quit and saves.** ``quits_at_once`` (the shell's quit guard asks nothing) and
  ``private_picture`` (no save picture while it is on the stack; ``can_save()`` is False
  unless quitting). It holds notices.

The message is cleaned here whatever the caller did: ``escape_controls`` (newlines kept),
``render_safe``, and cut to ``ERROR_MESSAGE_MAX_CHARS``. It is never redacted (05 Q2): it is
author text, and the player's own name may be in it.
"""

from collections.abc import Callable
from dataclasses import replace
from typing import Final

import pygame

from engine.core.constants import CRASH_FADE_S, CRASH_GUARD_S, ERROR_MESSAGE_MAX_CHARS
from engine.core.redact import escape_controls, truncate
from engine.render.canvas import Canvas
from engine.render.effects import ease_in_out
from engine.render.textlayout import render_safe
from engine.runtime.commands import TaggedText
from engine.ui.builtin import error_look
from engine.ui.input import UiEvent
from engine.ui.nav import Nav, NavReader
from engine.ui.screen import Screen, ScreenStack

_EPSILON: Final = 1e-6                  # float dt sums: 30 × (1/60) counts as 0.5 s
_CLICK_BUTTONS: Final = frozenset({1, 2, 3})   # left, middle, right (not the wheel's 4/5)
_CONTINUE: Final = frozenset({Nav.ACTIVATE, Nav.BACK})


def crash_text(body: TaggedText | None, name: str | None, default: str) -> str:
    """The page's message: ``default`` (``[words] fake_crash_message``) for a bare
    ``effect crash``, else the resolved message's span texts joined, each ``{username}``
    span drawn as ``name`` when one is given (its fallback word otherwise)."""
    if body is None:
        return default
    return "".join(name if span.style.username and name is not None else span.text
                   for span in body.plain(names=True))


def _clean_line(text: str) -> str:
    return render_safe(escape_controls(text))


class FakeCrashScreen(Screen):
    """The fake error page over the frozen story (see the module docstring)."""

    in_game = False
    holds_notices = True
    quits_at_once = True
    private_picture = True

    def __init__(self, *, message: str, game_title: str, game_version: str, hint: str,
                 label: str | None, fade: bool, on_continue: Callable[[], None],
                 waiting: Callable[[], bool], stack: ScreenStack,
                 focused: Callable[[], bool] = lambda: True) -> None:
        self.message = truncate(render_safe(escape_controls(message, allow_newline=True)),
                                ERROR_MESSAGE_MAX_CHARS)
        self.title_line = _clean_line(error_look.title_line(game_title, game_version))
        self.hint = _clean_line(hint)
        self.label = _clean_line(label) if label is not None else None
        self.fade = fade
        self._on_continue = on_continue
        self._waiting = waiting
        self._stack = stack
        self._focused = focused
        self._nav = NavReader()
        self._drawn = False             # the first draw happened (the guard counts after it)
        self._elapsed = 0.0             # drawn, focused seconds since the first draw
        self._leaving = False           # OUT: continued, fading out
        self._out = 0.0
        self._gone = False
        self._blocks: list[str] | None = None
        self._page: pygame.Surface | None = None
        self._page_key: tuple[object, ...] | None = None

    # -- state --

    @property
    def state(self) -> str:
        """``"in"``, ``"guard"``, ``"ready"``, ``"out"``, or ``"gone"`` (tests, the dev
        overlay)."""
        if self._gone:
            return "gone"
        if self._leaving:
            return "out"
        if self.fade and self._elapsed < CRASH_FADE_S - _EPSILON:
            return "in"
        return "ready" if self._ready() else "guard"

    def _ready(self) -> bool:
        return (self._drawn and not self._leaving and not self._gone
                and self._elapsed >= CRASH_GUARD_S - _EPSILON)

    @property
    def alpha(self) -> float:
        """The page's opacity this frame: 1 without a fade; else eased in from the first
        drawn update, and out after the continue."""
        if not self.fade:
            return 1.0
        if self._leaving:
            return ease_in_out(1.0 - self._out / CRASH_FADE_S)
        return ease_in_out(self._elapsed / CRASH_FADE_S)

    @property
    def opaque(self) -> bool:                                  # type: ignore[override]
        return self.alpha >= 1.0 - _EPSILON

    # -- input and time --

    def handle_event(self, event: UiEvent) -> bool:
        if self._ready() and self._continues(event):
            self._continue()
        return True                                 # every event stops here

    def _continues(self, event: UiEvent) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN:
            return event.in_canvas and getattr(event.raw, "button", 0) in _CLICK_BUTTONS
        return self._nav.read(event, dev=False) in _CONTINUE

    def _continue(self) -> None:
        self._on_continue()                         # presses the stage's wait: WaitDone
        if self.fade:
            self._leaving = True
            self._out = 0.0
        else:
            self._remove()

    def update(self, dt: float, *, is_top: bool) -> None:
        if self._gone:
            return
        if not self._leaving and not self._waiting():
            self._remove()                          # skip, restore, New Game: no fade
            return
        if not self._drawn or not self._focused():
            return
        if self._leaving:
            self._out += dt
            if self._out >= CRASH_FADE_S - _EPSILON:
                self._remove()
            return
        self._elapsed += dt

    def _remove(self) -> None:
        self._gone = True
        self._stack.remove(self)

    # -- drawing --

    def draw(self, canvas: Canvas) -> None:
        surface = canvas.surface
        assert surface is not None, "Canvas.bind() has not been called"
        page = self._page_for(canvas, surface)
        alpha = self.alpha
        if alpha >= 1.0 - _EPSILON:
            surface.blit(page, (0, 0))
        elif alpha > 0.0:
            page.set_alpha(round(255 * alpha))
            try:
                surface.blit(page, (0, 0))
            finally:
                page.set_alpha(None)
        self._drawn = True

    def _page_for(self, canvas: Canvas, surface: pygame.Surface) -> pygame.Surface:
        """The cached page for this viewport size and render quality (I-11)."""
        viewport = canvas.viewport
        assert viewport is not None
        key = (surface.get_size(), canvas.quality)
        if self._page is not None and key == self._page_key:
            return self._page
        page = surface.copy()                       # the display's pixel format
        off = Canvas(canvas.assets)
        off.final_scale = canvas.final_scale        # FAST settle frames raster like the canvas
        w, h = page.get_size()
        off.bind(page, replace(viewport, window_w=w, window_h=h, x=0, y=0), canvas.quality)
        if self._blocks is None:
            self._blocks = error_look.fit_message(off, self.message, cut_notice=None)
        error_look.draw_page(off, lines=self._blocks, title_line=self.title_line,
                             log_line=None, hint=self.hint, label=self.label)
        self._page, self._page_key = page, key
        return page


__all__ = ["FakeCrashScreen", "crash_text"]
