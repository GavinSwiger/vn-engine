"""F52 step W3: text fields in F10 menus and the on-screen keyboard: AC-F52-19, 22, 23, 26, 39."""

import pygame
import pytest

from engine.ui.builtin.sampler import SamplerScreen
from engine.ui.focus import Box, FocusGroup
from engine.ui.input import UiEvent
from engine.ui.menu_screen import MenuScreen
from engine.ui.nav import InputKind
from engine.ui.textfield import TextField
from engine.ui.textrouting import TextServices
from engine.ui.widgets import Button, Look
from tests.fakes.ui_shell import TestShell, UiHarness

H = UiHarness
A, B, X, Y = (pygame.CONTROLLER_BUTTON_A, pygame.CONTROLLER_BUTTON_B,
              pygame.CONTROLLER_BUTTON_X, pygame.CONTROLLER_BUTTON_Y)
LB, RB = pygame.CONTROLLER_BUTTON_LEFTSHOULDER, pygame.CONTROLLER_BUTTON_RIGHTSHOULDER
UP, DOWN, LEFT, RIGHT = (pygame.CONTROLLER_BUTTON_DPAD_UP, pygame.CONTROLLER_BUTTON_DPAD_DOWN,
                         pygame.CONTROLLER_BUTTON_DPAD_LEFT, pygame.CONTROLLER_BUTTON_DPAD_RIGHT)


def typed(text: str) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.TEXTINPUT, text=text), None, False)


def tap(button: int) -> tuple:
    return H.pad(button), H.pad(button, up=True)


class FieldMenu(MenuScreen):
    """A field at (100, 100, 600, 56) (the default), a cell, and an OK button."""

    def __init__(self, shell, *, by=InputKind.KEYS, keep=False, mask=False) -> None:
        self.submitted: list[str] = []
        self.backs = 0
        self.field = TextField(placeholder="Type here", max_length=12, keep_keyboard=keep,
                               mask=mask, on_submit=self.submitted.append)
        self.cell = TextField(cell=True, allowed="ABC")
        self.ok = Button(lambda: "OK", lambda: self.submitted.append("ok"))
        super().__init__(shell, by=by, fade=False)

    def build(self) -> None:
        self.field.box = Box(100, 100, 600, 56)
        self.cell.box = Box(376, 200, 47, 47)
        self.ok.box = Box(100, 300, 200, 56)
        self.scope.set_groups([FocusGroup([self.field, self.cell, self.ok], column=True)])
        self.scope.default_widget = self.field

    def back(self) -> None:
        self.backs += 1
        super().back()


def world(**kwargs):
    shell = TestShell()
    shell.text = TextServices(read_clipboard=lambda: "Pasted")
    h = UiHarness(shell)
    menu = FieldMenu(shell, **kwargs)
    shell.stack.push(menu)
    h.frame()
    return shell, h, menu


# --- AC-F52-19: south opens the keyboard on a field, not a cell; the icon by mouse; never Enter --

def test_ac_f52_19_opening_the_keyboard():
    shell, h, m = world(by=InputKind.MOUSE)
    assert m.scope.focused is m.field and m.scope.visible     # a text default: focused visibly
    h.frame(H.key(pygame.K_RETURN))
    assert not m.keyboard_open() and m.submitted == [""]      # Enter submits, never opens
    h.frame(*tap(A))
    assert m.keyboard_open() and m.text_target() is m.field
    h.frame(*tap(B))
    assert not m.keyboard_open() and shell.stack.top is m     # Back closes the keyboard only
    m.scope.focus(m.cell, InputKind.KEYS)
    h.frame(*tap(A))
    assert not m.keyboard_open()                              # a cell: nothing
    icon = m.field.box.right - 12 - 16, m.field.box.y + 28
    h.click(icon)
    assert m.keyboard_open()                                  # the icon, by mouse
    h.click((20, 700))                                        # outside the panel: closes
    assert not m.keyboard_open() and m.field.text == ""


# --- AC-F52-22: keyboard input per §6.3; keep_keyboard ---------------------------------------------

def test_ac_f52_22_keyboard_input():
    shell, h, m = world()
    h.frame(*tap(A))
    kb = m.keyboard()
    assert kb.focus == ("key", 0) and kb.keys()[0] == "A"     # the first key at open
    rows = [
        (tap(A), "A"),                                         # south presses the key
        (tap(RIGHT) + tap(A), "AB"),                            # D-pad moves between keys
        (tap(Y), "AB "),                                        # north: a space
        (tap(X), "AB"),                                         # west: delete
        ((H.key(pygame.K_DOWN), H.key(pygame.K_RETURN)), "ABL"),   # Enter presses the key
        ((H.key(pygame.K_BACKSPACE),), "AB"),                  # Backspace edits
        ((typed("é"),), "ABé"),                                # physical typing still works
        ((H.key(pygame.K_SPACE),), "ABé"),                     # Space key: text comes as TEXTINPUT
    ]
    for events, text in rows:
        h.frame(*events)
        assert m.field.text == text, events
    h.frame(*tap(RB))
    assert kb.page == 1                                        # RB: the next page (abc)
    h.frame(*tap(LB))
    assert kb.page == 0
    h.frame(H.key(pygame.K_PAGEDOWN))
    assert kb.page == 1
    h.frame(H.key(pygame.K_HOME))
    assert kb.focus == ("key", 0)
    h.frame(H.key(pygame.K_END))
    assert kb.focus[0] == "key" and kb.focus[1] == len(kb.keys()) - 1
    kb.focus = ("left", None)
    h.frame(*tap(A))
    assert m.field.model.caret == 2                            # ◀ moves the caret
    kb.focus = ("done", None)
    h.frame(*tap(A))
    assert m.submitted == ["ABé"] and not m.keyboard_open()    # Done submits and closes
    h.frame(*tap(A))
    h.frame(H.key(pygame.K_ESCAPE))                            # Esc in a menu: closes it
    assert not m.keyboard_open() and shell.stack.top is m and m.backs == 0
    h.frame(*tap(A))
    h.frame(H.down((640, 400), 3))                             # right click: closes it
    assert not m.keyboard_open() and m.field.text == "ABé"
    # keep_keyboard: open after Done; the hold repeats key moves.
    shell, h, m = world(keep=True)
    h.frame(*tap(A))
    m.keyboard().focus = ("done", None)
    h.frame(*tap(A))
    assert m.submitted == [""] and m.keyboard_open()
    m.keyboard().focus = ("key", 0)
    h.frame(H.pad(RIGHT))
    for _ in range(40):                                        # held: 500 ms, then every 80
        h.frame()
    assert m.keyboard().focus[1] >= 3
    h.frame(H.pad(RIGHT, up=True))


# --- AC-F52-23: typing with the keyboard open; the echo row matches the field --------------------

def test_ac_f52_23_echo_row():
    for mask in (False, True):
        shell, h, m = world(mask=mask)
        h.frame(*tap(A))
        h.frame(typed("Sayo"))
        assert m.field.text == "Sayo" and m.keyboard_open()
        kb = m.keyboard()
        p = shell.painter
        p.bind(h.canvas)
        echo = m.field.plan(p, Look("focused"), box=kb.layout().echo, echo=True)
        own = m.field.plan(p, Look("focused"))
        assert echo.text == own.text == ("••••" if mask else "Sayo")
        assert echo.counter == own.counter == "4/12" and echo.icon is None
        h.frame()                                              # drawn without error


# --- AC-F52-26: a MenuScreen with a field: typing; Back closes the keyboard first ----------------

def test_ac_f52_26_menu_screen_with_a_field():
    shell, h, m = world()
    h.frame(typed("Ren"))
    assert m.field.text == "Ren"
    h.frame(H.key(pygame.K_BACKSPACE))
    h.frame(H.key(pygame.K_BACKSPACE))
    h.frame(H.key(pygame.K_BACKSPACE))
    h.frame(H.key(pygame.K_BACKSPACE))                         # on an empty field: not Back
    assert m.field.text == "" and m.backs == 0 and shell.stack.top is m
    h.frame(H.key(pygame.K_v, pygame.KMOD_LCTRL))
    assert m.field.text == "Pasted"
    h.frame(*tap(A))
    h.frame(*tap(B))                                           # Back: the keyboard first
    assert not m.keyboard_open() and m.backs == 0
    h.frame(H.key(pygame.K_DOWN))                              # Up/Down leave the field
    assert m.scope.focused is m.cell
    h.frame(H.key(pygame.K_DOWN))                              # a cell turns on Up/Down
    assert m.cell.text == "A" and m.scope.focused is m.cell
    h.frame(*tap(B))                                           # then the page
    assert m.backs == 1


# --- AC-F52-39: the sampler shows a field, a cell and a bare field in each state ------------------

def test_ac_f52_39_sampler_text_widgets():
    shell = TestShell()
    h = UiHarness(shell)
    s = SamplerScreen(shell, by=InputKind.MOUSE)
    shell.stack.push(s)
    h.frame()
    p = s.painter
    p.bind(h.canvas)
    states = {name: s.look_for(w).state for name, w in (
        ("field", s.field), ("field_disabled", s.field_disabled), ("cell", s.cell_live),
        ("cell_focused", s.cell_focused), ("cell_disabled", s.cell_disabled),
        ("bare", s.bare))}
    assert states == {"field": "normal", "field_disabled": "disabled", "cell": "normal",
                      "cell_focused": "focused", "cell_disabled": "disabled", "bare": "normal"}
    for w in (s.field, s.cell_live, s.bare):
        s.scope.focus(w, InputKind.KEYS)
        h.frame()
        assert s.look_for(w).state == "focused" and s.text_target() is w
    assert s.field.plan(p, Look("focused")).frame == "focused"
    assert s.bare.plan(p, Look("focused")).underline is not None
    assert s.cell_disabled.plan(p, Look("disabled")).bold
    s.scope.focus(s.field, InputKind.KEYS)
    h.frame(typed("Hi"))
    assert s.field.text == "Hi"
    for w in (s.field, s.field_disabled, s.cell_live, s.cell_focused, s.cell_disabled, s.bare):
        assert 72 <= w.box.y and w.box.bottom <= 712 or s.max_scroll() > 0
