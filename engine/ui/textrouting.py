"""``TextRouter``: raw input to a focused text field and its keyboard, the same in F10 menus
and F23 minigames (F52 ``04`` §4.1; P5).

Why this module exists: text needs raw events (``TEXTINPUT``, ``TEXTEDITING``, editing keys)
before F10's ``NavReader`` turns keys into navigation, and an IME needs the field to ignore
keys it is using. One router decides, per event, whether the field (or the keyboard) used it
(``USED``), whether it belongs to the screen (``PASS``), or whether it opens the game menu
(``MENU``, Esc over a minigame's keyboard). In order:

1. **Composing guard.** While the field composes (and until the frame ends after a commit),
   text events go to the field; every key-down or key-up of Enter, keypad Enter, Esc,
   Backspace, Delete, the arrows, Home, End, Tab and printable keys is USED with no action.
   F-keys pass.
2. **Paste chord** (Ctrl+V, Shift+Insert, Cmd+V): ``field.paste(read_clipboard())``.
3. **Keyboard open** (modal): text, Backspace and Delete go to the field; navigation and the
   mouse to the keyboard; a press outside the panel, east, right click or Back close it and
   keep the text; Esc: MENU in a minigame, close in a menu; west deletes, north types a
   space, LB/RB and Page Up/Down change the page. Everything else is USED.
4. **Keyboard closed:** ``TEXTINPUT`` inserts; Enter submits (not a cell); Backspace and
   Delete edit and are **always** USED, even on an empty field; Space and other printable
   keys without Ctrl, Alt or GUI are USED (text comes as ``TEXTINPUT``); Left, Right, Home,
   End (a field) or Up, Down (a cell) go to the field; south opens the keyboard (not a
   cell). Anything else passes.

Mouse input over a closed keyboard passes (F10's path focuses the field and sets the caret).
``EditRepeat`` is hold-to-repeat (500 ms, then 80 ms) for Backspace, Delete, caret moves,
cell turns and key moves; never for typing or Done. ``TextServices`` is what a shell gives
text widgets: the clipboard, the language, and W267's sink (07 I-3: never the widget).
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final

import pygame

from engine.ui.nav import DIRECTIONS, Nav, RepeatClock

if TYPE_CHECKING:
    from engine.ui.input import UiEvent
    from engine.ui.osk import OnScreenKeyboard
    from engine.ui.textfield import TextField


class Routed(Enum):
    USED = "used"
    PASS = "pass"
    MENU = "menu"


@dataclass
class TextServices:
    """The shell's text services (``MenuShell.text``): ``read_clipboard`` (``app/textinput``'s
    owner, the only clipboard reader), ``language`` (F43's code), ``warn(code, text)`` (dev
    warnings such as W267; None outside dev runs)."""
    read_clipboard: Callable[[], str] = lambda: ""
    language: Callable[[], str] = lambda: "en"
    warn: Callable[[str, str], None] | None = None


_MODS: Final = pygame.KMOD_CTRL | pygame.KMOD_ALT | pygame.KMOD_META | pygame.KMOD_GUI
_ENTER: Final = frozenset({pygame.K_RETURN, pygame.K_KP_ENTER})
_EDIT: Final = frozenset({pygame.K_BACKSPACE, pygame.K_DELETE})
GUARDED_KEYS: Final = frozenset({
    pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_DELETE,
    pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_HOME, pygame.K_END,
    pygame.K_TAB})
_KEYPAD: Final = frozenset({
    pygame.K_KP0, pygame.K_KP1, pygame.K_KP2, pygame.K_KP3, pygame.K_KP4, pygame.K_KP5,
    pygame.K_KP6, pygame.K_KP7, pygame.K_KP8, pygame.K_KP9, pygame.K_KP_PERIOD,
    pygame.K_KP_DIVIDE, pygame.K_KP_MULTIPLY, pygame.K_KP_MINUS, pygame.K_KP_PLUS,
    pygame.K_KP_EQUALS})
_TEXT_EVENTS: Final = frozenset({pygame.TEXTINPUT, pygame.TEXTEDITING})
_WEST: Final = pygame.CONTROLLER_BUTTON_X
_NORTH: Final = pygame.CONTROLLER_BUTTON_Y
_SOUTH: Final = pygame.CONTROLLER_BUTTON_A
_SHOULDERS: Final = {pygame.CONTROLLER_BUTTON_LEFTSHOULDER: -1,
                     pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: 1}
_PAGE_KEYS: Final = {pygame.K_PAGEUP: -1, pygame.K_PAGEDOWN: 1}


def _mods(raw: object) -> int:
    return int(getattr(raw, "mod", 0))


def is_paste_chord(raw: object) -> bool:
    """Ctrl+V, Cmd+V (GUI), or Shift+Insert, as a key-down."""
    if getattr(raw, "type", None) != pygame.KEYDOWN:
        return False
    key, mods = getattr(raw, "key", -1), _mods(raw)
    if key == pygame.K_v:
        return bool(mods & (pygame.KMOD_CTRL | pygame.KMOD_GUI)) and not mods & pygame.KMOD_ALT
    if key == pygame.K_INSERT:
        return bool(mods & pygame.KMOD_SHIFT) and not mods & (pygame.KMOD_CTRL
                                                               | pygame.KMOD_ALT)
    return False


def is_printable_key(raw: object) -> bool:
    """A key that types (its text comes as ``TEXTINPUT``): Space, a printable ASCII key, a
    keypad character, or any key with printable ``unicode``; never with Ctrl, Alt or GUI."""
    if _mods(raw) & _MODS:
        return False
    key = getattr(raw, "key", -1)
    if 0x20 <= key < 0x7F or key in _KEYPAD:
        return True
    text = getattr(raw, "unicode", "")
    return bool(text) and text.isprintable()


_F_KEYS: Final = frozenset(getattr(pygame, f"K_F{n}") for n in range(1, 16))


def is_f_key(raw: object) -> bool:
    """F1 to F15 (SDL's key codes put the keypad between them, so never a range)."""
    return getattr(raw, "key", -1) in _F_KEYS


class EditRepeat:
    """Hold to repeat for editing (01 §6.3): ``start(action, key=… | nav=… | button=…)``;
    the hold ends on that key's release, that nav's release, or that button's release."""

    def __init__(self) -> None:
        self.clock = RepeatClock()
        self._action: Callable[[], object] | None = None
        self._key: int | None = None
        self._nav: Nav | None = None
        self._button: int | None = None

    @property
    def active(self) -> bool:
        return self._action is not None

    def start(self, action: Callable[[], object], *, key: int | None = None,
              nav: Nav | None = None, button: int | None = None) -> None:
        self._action, self._key, self._nav, self._button = action, key, nav, button
        self.clock.start(nav if nav is not None else Nav.DELETE)

    def stop(self) -> None:
        self._action = None
        self.clock.stop()

    def released(self, raw: object, released: Nav | None) -> None:
        if self._action is None:
            return
        kind = getattr(raw, "type", None)
        if kind == pygame.KEYUP and self._key is not None and getattr(raw, "key", -1) == self._key:
            self.stop()
        elif kind == pygame.CONTROLLERBUTTONUP and self._button is not None \
                and getattr(raw, "button", -1) == self._button:
            self.stop()
        elif released is not None and released is self._nav:
            self.stop()
        elif kind in (pygame.WINDOWFOCUSLOST, pygame.CONTROLLERDEVICEREMOVED):
            self.stop()

    def tick(self, dt: float) -> None:
        action = self._action
        if action is None:
            return
        for _ in range(self.clock.tick(dt)):
            if self._action is None:
                return
            action()


class TextRouter:
    """One screen's router (module docstring). ``open_keyboard(field)`` opens the screen's
    keyboard over ``field``."""

    def __init__(self, *, read_clipboard: Callable[[], str],
                 open_keyboard: Callable[["TextField"], None]) -> None:
        self.read_clipboard = read_clipboard
        self.open_keyboard = open_keyboard
        self.repeat = EditRepeat()

    def route(self, event: "UiEvent", nav: Nav | None, field: "TextField",
              keyboard: "OnScreenKeyboard | None", *, minigame: bool,
              released: Nav | None = None) -> Routed:
        raw = event.raw
        kind = raw.type
        self.repeat.released(raw, released)
        # 1. The composing guard.
        if field.composing:
            if kind in _TEXT_EVENTS:
                field.on_text(event)
                return Routed.USED
            if kind in (pygame.KEYDOWN, pygame.KEYUP):
                if is_f_key(raw):
                    return Routed.PASS
                if getattr(raw, "key", -1) in GUARDED_KEYS or is_printable_key(raw):
                    return Routed.USED
        # 2. The paste chord.
        if is_paste_chord(raw):
            field.paste(self.read_clipboard())
            return Routed.USED
        if keyboard is not None and keyboard.is_open:
            return self._open(event, nav, field, keyboard, minigame=minigame)
        return self._closed(event, nav, field)

    # -- 3. keyboard open (modal) --

    def _open(self, event: "UiEvent", nav: Nav | None, field: "TextField",
              keyboard: "OnScreenKeyboard", *, minigame: bool) -> Routed:
        raw = event.raw
        kind = raw.type
        if kind in _TEXT_EVENTS:
            field.on_text(event)
            return Routed.USED
        if kind == pygame.KEYDOWN:
            key = raw.key
            if key in _EDIT:
                self._edit(field, key)
                return Routed.USED
            if key == pygame.K_ESCAPE:
                if minigame:
                    return Routed.MENU
                keyboard.close()
                return Routed.USED
            if key in _PAGE_KEYS:
                keyboard.page_step(_PAGE_KEYS[key])
                return Routed.USED
            if is_printable_key(raw):
                return Routed.USED                   # typed: its text comes as TEXTINPUT
        if kind == pygame.CONTROLLERBUTTONDOWN:
            button = getattr(raw, "button", -1)
            if button == _WEST:
                field.backspace()
                self.repeat.start(field.backspace, button=button)
                return Routed.USED
            if button == _NORTH:
                field.type_text(" ")
                return Routed.USED
            if button in _SHOULDERS:
                keyboard.page_step(_SHOULDERS[button])
                return Routed.USED
        if kind == pygame.MOUSEBUTTONDOWN and getattr(raw, "button", 0) == 1:
            if event.in_canvas and event.canvas_pos is not None:
                if keyboard.on_mouse("down", event.canvas_pos) == "outside":
                    keyboard.close()
            return Routed.USED
        if kind == pygame.MOUSEMOTION and event.canvas_pos is not None and event.in_canvas:
            keyboard.on_mouse("motion", event.canvas_pos)
            return Routed.USED
        if kind == pygame.MOUSEBUTTONUP and getattr(raw, "button", 0) == 1:
            if event.canvas_pos is not None:
                keyboard.on_mouse("up", event.canvas_pos)
            return Routed.USED
        if nav is Nav.BACK:
            keyboard.close()
            return Routed.USED
        if nav is not None and nav not in (Nav.START, Nav.SAMPLER):
            keyboard.on_nav(nav)
            if nav in DIRECTIONS:
                self.repeat.start(lambda n=nav: keyboard.on_nav(n), nav=nav)
            return Routed.USED
        if nav is Nav.START and minigame:
            return Routed.PASS
        return Routed.USED

    # -- 4. keyboard closed --

    def _closed(self, event: "UiEvent", nav: Nav | None, field: "TextField") -> Routed:
        raw = event.raw
        kind = raw.type
        if kind in _TEXT_EVENTS:
            field.on_text(event)
            return Routed.USED
        if kind == pygame.KEYDOWN:
            key = raw.key
            if key in _ENTER and not _mods(raw) & _MODS:
                if field.cell:
                    return Routed.PASS
                field.submit()
                return Routed.USED
            if key in _EDIT and not _mods(raw) & (pygame.KMOD_CTRL | pygame.KMOD_ALT
                                                  | pygame.KMOD_GUI):
                self._edit(field, key)
                return Routed.USED
            if is_printable_key(raw):
                return Routed.USED
        if kind == pygame.CONTROLLERBUTTONDOWN and getattr(raw, "button", -1) == _SOUTH:
            if not field.cell and field.enabled():
                self.open_keyboard(field)
            return Routed.USED
        if nav is not None:
            mine = (Nav.UP, Nav.DOWN) if field.cell else (Nav.LEFT, Nav.RIGHT, Nav.HOME,
                                                          Nav.END)
            if nav in mine and field.on_nav(nav):
                if nav in DIRECTIONS:
                    self.repeat.start(lambda n=nav: field.on_nav(n), nav=nav)
                return Routed.USED
        return Routed.PASS

    def _edit(self, field: "TextField", key: int) -> None:
        action = field.backspace if key == pygame.K_BACKSPACE else field.delete
        action()
        self.repeat.start(action, key=key)

    def tick(self, dt: float) -> None:
        self.repeat.tick(dt)


__all__ = ["GUARDED_KEYS", "EditRepeat", "Routed", "TextRouter", "TextServices",
           "is_f_key", "is_paste_chord", "is_printable_key"]
