"""Navigation input: raw keyboard, mouse, and gamepad events → ``Nav`` (F10 ``04`` §7.2).

Why this module exists: every F10-based screen reads the same inputs the same way
(ui-system §6 "Menu navigation"). Arrows, the D-pad, and the left stick move focus; Tab walks
it; Enter / Space / south activate; Esc, right click, and east go back (C1: Esc is not a
global key, each screen handles it); Start is reserved for the game menu. One reader turns
those into ``Nav`` values, so screens never test key codes themselves.

``NavReader`` is a small state machine fed with ``UiEvent``s. Its only state is the left-stick
arming per ``(controller instance, axis)``: one step when the value crosses ±16,384 outward,
then nothing until it comes back inside ±8,192 (that return is the "release" of the
direction). The state is kept per controller, so two controllers drive the one focus.
``RepeatClock`` is the hold-to-repeat timer (PR-F10-08), driven by ``GameTime`` dt.

Extras (F11 ``03-ui`` "Interaction"; ui-system §6): a reader's ``extras`` turn on inputs only
some pages use. ``"shoulders"``: the gamepad left / right bumper are Page Up / Page Down (F11's
Save and Load pages only; elsewhere they stay F14's). ``"delete"``: Delete, Backspace, and
gamepad west are ``Nav.DELETE`` (delete the focused slot). The game menu sets them from the
open page (``MenuPageBase.nav_extras``). Page Up / Page Down holds end on their release, so a
page can repeat them.

Pygame constants only; no display, no clock, no controller opening (that is
``app/input.py``'s, F05 step 8 / F10 I-14).
"""

import math
from enum import Enum

import pygame

from engine.ui.input import UiEvent

# Stick thresholds (F07's, kept per controller): a step past ±16,384, re-armed inside ±8,192.
STICK_PRESS = 16_384
STICK_REARM = 8_192

REPEAT_DELAY = 0.5        # s from the press to the first repeat
REPEAT_INTERVAL = 0.08    # s between later repeats
REPEAT_MAX_PER_TICK = 2   # at most this many repeats in one frame; the rest are dropped
_EPSILON = 1e-6           # float dt sums: 30 × (1/60) must count as 0.5 s


class Nav(Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    NEXT = "next"
    PREV = "prev"
    ACTIVATE = "activate"
    BACK = "back"
    START = "start"
    HOME = "home"
    END = "end"
    PAGE_UP = "page_up"
    PAGE_DOWN = "page_down"
    SAMPLER = "sampler"
    DELETE = "delete"         # only with the "delete" extra (F11's slots)


class InputKind(Enum):
    MOUSE = "mouse"
    KEYS = "keys"         # keyboard or gamepad


DIRECTIONS = frozenset({Nav.UP, Nav.DOWN, Nav.LEFT, Nav.RIGHT})
PAGE_KEYS = frozenset({Nav.PAGE_UP, Nav.PAGE_DOWN})
_HELD = DIRECTIONS | PAGE_KEYS            # navs whose release ends a hold
EXTRAS = frozenset({"shoulders", "delete"})

# Keys held with any of these map to nothing, so F11, Alt+Enter, and console keys never
# navigate. Shift is allowed (Shift+Tab, Shift+F3).
_BLOCKING_MODS = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI

_KEYS: dict[int, Nav] = {
    pygame.K_UP: Nav.UP,
    pygame.K_DOWN: Nav.DOWN,
    pygame.K_LEFT: Nav.LEFT,
    pygame.K_RIGHT: Nav.RIGHT,
    pygame.K_RETURN: Nav.ACTIVATE,
    pygame.K_KP_ENTER: Nav.ACTIVATE,
    pygame.K_SPACE: Nav.ACTIVATE,
    pygame.K_ESCAPE: Nav.BACK,
    pygame.K_HOME: Nav.HOME,
    pygame.K_END: Nav.END,
    pygame.K_PAGEUP: Nav.PAGE_UP,
    pygame.K_PAGEDOWN: Nav.PAGE_DOWN,
}

_BUTTONS: dict[int, Nav] = {
    pygame.CONTROLLER_BUTTON_DPAD_UP: Nav.UP,
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: Nav.DOWN,
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: Nav.LEFT,
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: Nav.RIGHT,
    pygame.CONTROLLER_BUTTON_A: Nav.ACTIVATE,       # south
    pygame.CONTROLLER_BUTTON_B: Nav.BACK,           # east
    pygame.CONTROLLER_BUTTON_START: Nav.START,
}

# Left stick axis → (direction for a negative value, direction for a positive value).
_STICK_AXES: dict[int, tuple[Nav, Nav]] = {
    pygame.CONTROLLER_AXIS_LEFTX: (Nav.LEFT, Nav.RIGHT),
    pygame.CONTROLLER_AXIS_LEFTY: (Nav.UP, Nav.DOWN),
}

_SHOULDERS: dict[int, Nav] = {
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: Nav.PAGE_UP,
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: Nav.PAGE_DOWN,
}
_DELETE_KEYS = frozenset({pygame.K_DELETE, pygame.K_BACKSPACE})
_DELETE_BUTTON = pygame.CONTROLLER_BUTTON_X                 # west

_MOUSE_BACK_BUTTON = 3


class NavReader:
    """Event → ``Nav``. ``read`` gives presses, ``released`` the end of a held direction.

    Each event is interpreted once, whichever of the two methods is called first, so a
    screen may call both for one event in any order. ``extras`` (a subset of ``EXTRAS``)
    may change between events."""

    def __init__(self, extras: frozenset[str] = frozenset()) -> None:
        assert extras <= EXTRAS, extras
        self.extras = extras
        # (instance_id, axis) → the direction held (disarmed); absent = armed.
        self._held: dict[tuple[int, int], Nav] = {}
        self._last_event: UiEvent | None = None
        self._last_result: tuple[Nav | None, Nav | None] = (None, None)

    def read(self, ev: UiEvent, *, dev: bool) -> Nav | None:
        """The ``Nav`` this press means, or None. ``SAMPLER`` only when ``dev``."""
        press = self._interpret(ev)[0]
        if press is Nav.SAMPLER and not dev:
            return None
        return press

    def released(self, ev: UiEvent) -> Nav | None:
        """The direction whose hold ``ev`` ends (``KEYUP``, D-pad up, stick re-arm), or None."""
        return self._interpret(ev)[1]

    def reset(self, instance_id: int | None = None) -> None:
        """Re-arm every stick axis of one controller (removed), or of all (screen left)."""
        if instance_id is None:
            self._held.clear()
            return
        for key in [key for key in self._held if key[0] == instance_id]:
            del self._held[key]

    # -- interpretation (once per event) --

    def _interpret(self, ev: UiEvent) -> tuple[Nav | None, Nav | None]:
        if ev is self._last_event:
            return self._last_result
        result = self._classify(ev)
        self._last_event, self._last_result = ev, result
        return result

    def _classify(self, ev: UiEvent) -> tuple[Nav | None, Nav | None]:
        raw = ev.raw
        kind = raw.type
        if kind == pygame.KEYDOWN:
            mods = getattr(raw, "mod", 0)
            if (raw.key in _DELETE_KEYS and "delete" in self.extras
                    and not mods & _BLOCKING_MODS):
                return Nav.DELETE, None
            return _key_press(raw.key, mods), None
        if kind == pygame.KEYUP:
            nav = _KEYS.get(raw.key)
            return None, nav if nav in _HELD else None
        if kind == pygame.MOUSEBUTTONDOWN:
            back = getattr(raw, "button", 0) == _MOUSE_BACK_BUTTON and ev.in_canvas
            return (Nav.BACK if back else None), None
        if kind == pygame.CONTROLLERBUTTONDOWN:
            return self._button(raw.button), None
        if kind == pygame.CONTROLLERBUTTONUP:
            nav = self._button(raw.button)
            return None, nav if nav in _HELD else None
        if kind == pygame.CONTROLLERAXISMOTION:
            return self._stick(raw.instance_id, raw.axis, raw.value)
        if kind == pygame.CONTROLLERDEVICEREMOVED:
            self.reset(raw.instance_id)
        return None, None

    def _button(self, button: int) -> Nav | None:
        if "shoulders" in self.extras and button in _SHOULDERS:
            return _SHOULDERS[button]
        if "delete" in self.extras and button == _DELETE_BUTTON:
            return Nav.DELETE
        return _BUTTONS.get(button)

    def _stick(self, instance_id: int, axis: int, value: int) -> tuple[Nav | None, Nav | None]:
        dirs = _STICK_AXES.get(axis)
        if dirs is None:                       # right stick, triggers
            return None, None
        key = (instance_id, axis)
        held = self._held.get(key)
        if value > STICK_PRESS:
            pushed: Nav | None = dirs[1]
        elif value < -STICK_PRESS:
            pushed = dirs[0]
        else:
            pushed = None
        if held is None:                       # armed
            if pushed is not None:
                self._held[key] = pushed
            return pushed, None
        if abs(value) < STICK_REARM:           # back inside: re-armed, the hold ends
            del self._held[key]
            return None, held
        if pushed is not None and pushed is not held:   # flipped past the centre unseen
            self._held[key] = pushed
            return pushed, held
        return None, None


def _key_press(key: int, mods: int) -> Nav | None:
    if mods & _BLOCKING_MODS:
        return None
    shift = bool(mods & pygame.KMOD_SHIFT)
    if key == pygame.K_TAB:
        return Nav.PREV if shift else Nav.NEXT
    if key == pygame.K_F3:
        return Nav.SAMPLER if shift else None
    return _KEYS.get(key)


class RepeatClock:
    """Hold to repeat (PR-F10-08): after ``start(d)``, ``tick(dt)`` returns how many repeats
    of ``d`` are due: the first at 0.5 s, then one every 0.08 s, at most 2 per tick (a long
    frame drops the excess instead of bursting later)."""

    def __init__(self) -> None:
        self._nav: Nav | None = None
        self._elapsed = 0.0
        self._fired = 0

    @property
    def nav(self) -> Nav | None:
        """The direction being repeated, or None when stopped."""
        return self._nav

    def start(self, nav: Nav) -> None:
        self._nav = nav
        self._elapsed = 0.0
        self._fired = 0

    def stop(self) -> None:
        self._nav = None

    def tick(self, dt: float) -> int:
        if self._nav is None:
            return 0
        self._elapsed += max(0.0, dt)
        if self._elapsed + _EPSILON < REPEAT_DELAY:
            return 0
        due = 1 + math.floor((self._elapsed - REPEAT_DELAY) / REPEAT_INTERVAL + _EPSILON)
        count = min(REPEAT_MAX_PER_TICK, due - self._fired)
        self._fired = due
        return max(0, count)
