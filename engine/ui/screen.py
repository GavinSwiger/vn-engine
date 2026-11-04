"""``Screen`` and ``ScreenStack``: the seam every menu and game screen plugs into (F10).

Why this module exists: F01 shows a placeholder screen and an error screen; F10 adds the
title menu, pause menu, and settings; F04/F05 add the game screen. All of them are screens
on one stack, so input, update, and drawing follow one rule (§7.15):

- ``handle_event`` (F10 C2): the top screen receives each event first. If it is
  ``in_game`` and doesn't consume the event, the event passes down through the contiguous
  ``in_game`` screens below it (``ChoiceScreen`` → ``TextboxScreen`` → ``StageScreen``),
  stopping at the first that consumes it or at a screen that isn't ``in_game``. A top that
  isn't ``in_game`` (every F10 menu, the error and placeholder screens) is the only
  receiver. Mouse events also set ``pointer``, and every input sets ``last_input``
  (F10 §7.7.6: the quit confirm opens focused only when no mouse moved since the last key).
- ``story_may_run()`` (F10 C3): ``App`` pumps the story only while the top screen is
  ``in_game`` (or the stack is empty), so every menu holds the story. A screen that must
  let the story run under it, or that shows story lines, is ``in_game``.
- ``update(dt)``: every screen, bottom to top, over a snapshot of the stack; only the top
  one gets ``is_top=True``. A screen pushed during the pass is not updated in it.
- ``draw(canvas)``: from the highest opaque screen upward, so a translucent pause menu
  draws over the game screen while screens hidden behind an opaque one cost nothing.
- ``push`` / ``pop`` / ``remove`` / ``replace_all`` apply immediately and call
  ``on_enter`` / ``on_exit``. ``remove`` takes a screen out wherever it is (a menu closing
  under a confirm, F10's quit guard replacing a confirm, I-8's ``ChoiceScreen``; F07 C6).

``InGameOverlay`` (F10 C5, I-6) is what the in-game line screen hosts: F05's
``TextboxScreen`` (``add_overlay``). Each
overlay gets every event before the host's own handling (also while the box is hidden),
``update(dt, frozen=...)`` (frozen only under a screen that isn't ``in_game``, F14 A6), and
draws after the box. F10's ``GameMenuKeys`` and ``QuickMenu`` are overlays; F11, F14 and F15
add theirs, in that order.
"""

from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Protocol

import pygame

from engine.core.logsetup import get_logger
from engine.ui.input import UiEvent
from engine.ui.nav import InputKind

if TYPE_CHECKING:
    from engine.render.canvas import Canvas

_log = get_logger("ui")

_MOUSE_INPUT = frozenset({pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                          pygame.MOUSEWHEEL})
_KEY_INPUT = frozenset({pygame.KEYDOWN, pygame.CONTROLLERBUTTONDOWN})
# F52 (04 §4.2-§4.3): ``text_target()`` of a minigame screen running a plugin below API 1.4:
# SDL text input stays on for it (no IME rect), as before F52.
LEGACY_TEXT = "legacy-text-input"


class Screen:
    """Base class. ``opaque`` screens cover everything below them."""

    opaque: bool = True
    # F09/F10 C2–C3: True for screens that are part of the game picture: F04's
    # StageScreen, F05's TextboxScreen (without it the story would hold forever), F07's
    # choices, F18's title cards.
    # Unconsumed input passes down through in-game screens, the story is pumped only while
    # the top screen is in-game, and in-game presentation timers run only then (F09).
    in_game: bool = False
    # F11 C7: while the top screen holds notices, a new notice waits (``ui/notice.py``):
    # True for a fade to black (``BlackFadeScreen``), the story load (``StoryLoadScreen``),
    # a ``TitleScreen`` fading in or out, and F11's ``LoadFadeScreen``. Notices already
    # shown stay and keep counting.
    holds_notices: bool = False
    # F30 (07 I-6): a quit while this screen is top asks nothing (``GameShell.quit_guard``;
    # F11's quit save still runs), and no save picture is taken while it is anywhere on the
    # stack (``capture_scene`` gives None; ``can_save()`` is False unless quitting). True for
    # the fake crash (``FakeCrashScreen``).
    quits_at_once: bool = False
    private_picture: bool = False

    def on_enter(self) -> None:
        pass

    def on_exit(self) -> None:
        pass

    def handle_event(self, event: UiEvent) -> bool:
        """Return True if the event was consumed."""
        return False

    def update(self, dt: float, *, is_top: bool) -> None:
        pass

    def draw(self, canvas: "Canvas") -> None:
        pass

    def text_target(self) -> object:
        """F52 (07 §3.1): what wants typing while this screen is top: a focused text field
        (``ime_rect``, ``text_lost``), ``LEGACY_TEXT``, or None (``app/textinput``)."""
        return None


class InGameOverlay(Protocol):
    """Hosted by the in-game line screen (F10 C5): ``handle_event`` returns True to consume
    the event (the host's own handling never sees it); ``box_shown`` is whether the box is
    visible now. ``frozen`` is True while a screen that isn't ``in_game`` is on top (a menu,
    a confirm, a fade: ``not stack.story_may_run()``; F14 A6, F23 C2). It is False under
    F07's choices and F18's title card, so F14's ``RollbackKeys`` steps back over choices;
    an overlay that must stop under choices does so itself (F15 ends skip at
    ``menu_shown``)."""

    def handle_event(self, event: UiEvent, *, box_shown: bool) -> bool: ...

    def update(self, dt: float, *, frozen: bool) -> None: ...

    def draw(self, canvas: "Canvas", *, box_shown: bool) -> None: ...


class ScreenStack:
    """Bottom → top list of screens."""

    def __init__(self) -> None:
        self._screens: list[Screen] = []
        # F10 C4: the last in-canvas mouse position (canvas units); None after a mouse
        # event inside the letterbox bars, and before any mouse event.
        self.pointer: tuple[int, int] | None = None
        # F10 §7.7.6: the kind of the last input (mouse event, or key / gamepad button);
        # None before any input.
        self.last_input: InputKind | None = None

    # -- changes (immediate) --

    def push(self, screen: Screen) -> None:
        self._screens.append(screen)
        screen.on_enter()

    def pop(self) -> Screen:
        screen = self._screens.pop()
        screen.on_exit()
        return screen

    def insert_above_in_game(self, screen: Screen) -> None:
        """F23 (``04`` §7.4 step 6, §17.1-5): put ``screen`` directly above the bottom run of
        ``in_game`` screens (stage, say window, choices), so a screen above that run (F11's
        ``LoadFadeScreen``, a menu) stays above it; then ``on_enter``. Asserts that the
        bottom screen is ``in_game``."""
        screens = self._screens
        assert screens and screens[0].in_game, "insert_above_in_game with no in-game screen"
        index = 1
        while index < len(screens) and screens[index].in_game:
            index += 1
        screens.insert(index, screen)
        screen.on_enter()

    def remove(self, screen: Screen) -> bool:
        """Take ``screen`` out of the stack wherever it is and call its ``on_exit``.
        Returns False (and does nothing) when ``screen`` is not on the stack, e.g. a menu
        that ``replace_all`` already removed."""
        for index in range(len(self._screens) - 1, -1, -1):
            if self._screens[index] is screen:
                del self._screens[index]
                screen.on_exit()
                return True
        return False

    def replace_all(self, screens: Sequence[Screen], *, safe_exit: bool = False) -> None:
        """Exit every current screen (top first), then enter ``screens`` bottom first.

        With ``safe_exit`` (the error mode, §7.12 step 2), an exception in an old screen's
        ``on_exit`` is logged and does not stop the replacement."""
        old = list(self._screens)
        self._screens = []
        for screen in reversed(old):
            if not safe_exit:
                screen.on_exit()
                continue
            try:
                screen.on_exit()
            except Exception:
                _log.debug("A screen failed while closing for the error screen", exc_info=True)
        for screen in screens:
            self.push(screen)

    # -- queries --

    @property
    def top(self) -> Screen | None:
        return self._screens[-1] if self._screens else None

    def __iter__(self) -> Iterator[Screen]:
        return iter(list(self._screens))

    def __len__(self) -> int:
        return len(self._screens)

    def story_may_run(self) -> bool:
        """F10 C3: True when the top screen is ``in_game`` or the stack is empty; ``App``
        pumps the story only then (the story hold under menus)."""
        top = self.top
        return top is None or bool(top.in_game)

    # -- per frame --

    def handle_event(self, event: UiEvent) -> bool:
        """F10 §7.1: offer ``event`` to the top screen, then down through the contiguous
        ``in_game`` screens below an ``in_game`` top, until one consumes it. Returns
        whether any screen consumed it."""
        if event.canvas_pos is not None:
            self.pointer = event.canvas_pos if event.in_canvas else None
        if event.type in _MOUSE_INPUT:
            self.last_input = InputKind.MOUSE
        elif event.type in _KEY_INPUT:
            self.last_input = InputKind.KEYS
        snapshot = list(self._screens)
        for index in range(len(snapshot) - 1, -1, -1):
            screen = snapshot[index]
            if screen.handle_event(event):
                return True
            if not screen.in_game or index == 0 or not snapshot[index - 1].in_game:
                return False
        return False

    def update(self, dt: float) -> None:
        snapshot = list(self._screens)
        last = len(snapshot) - 1
        for index, screen in enumerate(snapshot):
            screen.update(dt, is_top=index == last)

    def draw(self, canvas: "Canvas") -> None:
        snapshot = list(self._screens)
        start = 0
        for index in range(len(snapshot) - 1, -1, -1):
            if snapshot[index].opaque:
                start = index
                break
        for screen in snapshot[start:]:
            screen.draw(canvas)
