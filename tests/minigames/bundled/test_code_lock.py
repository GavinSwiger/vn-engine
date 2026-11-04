"""F53 step P1: Lock (``code_lock``) on Host U: AC-F53-09 (keypad entry), 10 (the right
code), 11 (the dial), 12 (letter codes ignore case), 13 (wrong-code messages and running out
of tries), 14 (the hint bar), 15 (Step back) and 16 (W280)."""

import logging

import pygame
import pytest

from engine.minigames.bundled import code_lock as cl
from engine.minigames.bundled import lock_rules as rules
from engine.minigames.bundled.code_lock import WORDS, CodeLock
from tests.minigames.bundled.quick_host import H, done_after, open_game, pad, tap, typed, world

BACKSPACE = tap(pygame.K_BACKSPACE)
ENTER = tap(pygame.K_RETURN)
UP, DOWN = tap(pygame.K_UP), tap(pygame.K_DOWN)
LEFT, RIGHT = tap(pygame.K_LEFT), tap(pygame.K_RIGHT)


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture
def w(game):
    return world(game, CodeLock)


def lock(w, **args):
    g = open_game(w, "code_lock", {**rules.DEFAULTS, **args})
    w.frame()
    return g


def click(w, widget):
    w.ui.click(widget.box.center)


def keys_in(w, g, code: str):
    for ch in code:
        w.frame(*typed(ch))


# --- AC-F53-09 ---------------------------------------------------------------------------------

def test_ac_f53_09_keypad_entry(w):
    g = lock(w, code="0417")
    assert [b.label() for b in g.keys] == [*"123456789", "Clear", "0", "Enter"]
    w.frame(*typed("0"))
    w.frame(*tap(pygame.K_KP4, text="4"))                     # the number pad
    w.frame(*tap(pygame.K_AMPERSAND, text="1"))               # AZERTY's top row: its text
    assert g.entered == "041"
    click(w, g.keys[0])                                       # the "1" button
    assert g.entered == "0411"
    w.frame(*BACKSPACE)
    assert g.entered == "041" and not g.enter.enabled()       # Enter waits for a full display
    click(w, g.clear)
    assert g.entered == ""
    w.frame(*BACKSPACE)                                       # nothing to delete: not used
    assert g.entered == "" and not g.finishes
    # Full by mouse: focus stays on the clicked key; a fifth digit is ignored.
    for d in "9999":
        click(w, g.keys[8])
    assert g.entered == "9999" and g.enter.enabled()
    assert w.session.scope.focused is g.keys[8]
    click(w, g.keys[8])
    w.frame(*typed("5"))
    assert g.entered == "9999"
    # Full by keys: focus moves to Enter; by the gamepad too.
    click(w, g.clear)
    keys_in(w, g, "123")
    w.frame(*typed("4"))
    assert w.session.scope.focused is g.enter
    click(w, g.clear)
    w.frame(H.motion((4, 4)))                                 # the pointer leaves: no focus
    w.frame(*DOWN)                                            # first focus: the "1" key
    for _ in range(4):
        w.frame(*pad(pygame.CONTROLLER_BUTTON_A))
    assert g.entered == "1111" and w.session.scope.focused is g.enter
    assert g.state == cl.ENTERING and not g.finishes


# --- AC-F53-10 ---------------------------------------------------------------------------------

def test_ac_f53_10_right_code_opens(w):
    g = lock(w, code="0417")
    keys_in(w, g, "0417")
    w.frame(*ENTER)
    assert g.state == cl.OPENED
    assert not any(b.enabled() for b in g.keys) and not g.leave_button.enabled()
    frames = 0
    while not g.finishes:
        w.frame()
        frames += 1
    assert frames * (1 / 60) == pytest.approx(0.7, abs=0.03)
    assert g.finishes == [True]
    assert done_after(w).result is True


# --- AC-F53-11 ---------------------------------------------------------------------------------

def test_ac_f53_11_dial(w):
    g = lock(w, code="123", kind="dial")
    assert g.wheels == ["0", "0", "0"]
    scope = w.session.scope
    assert scope.focused is g.wheel_widgets[0]                # keys: F23's first focus
    w.frame(*UP)
    w.frame(*DOWN)
    w.frame(*DOWN)
    assert g.wheels[0] == "9"                                 # 0 → 9 wraps
    w.frame(*UP)
    assert g.wheels[0] == "0"                                 # 9 → 0 wraps
    w.frame(*RIGHT)
    assert scope.focused is g.wheel_widgets[1]
    wheel = g.wheel_widgets[1].box
    up_zone = (wheel.center[0], wheel.y + 10)
    down_zone = (wheel.center[0], wheel.bottom - 10)
    w.ui.click(up_zone)
    w.ui.click(up_zone)
    w.ui.click(down_zone)
    assert g.wheels[1] == "1" and not g.finishes              # a click never opens
    w.frame(H.wheel(g.wheel_widgets[2].box.center, 2))        # the mouse wheel over a wheel
    assert g.wheels[2] == "2"
    # A typed digit sets the focused wheel and moves right; at the end, to Open.
    w.frame(*LEFT)
    w.frame(*LEFT)
    for ch in "123":
        w.frame(*typed(ch))
    assert g.wheels == ["1", "2", "3"] and scope.focused is g.open_button
    w.frame(*LEFT)                                            # back to the last wheel
    assert scope.focused is g.wheel_widgets[2]
    w.frame(*pad(pygame.CONTROLLER_BUTTON_A))                 # A on a wheel is Open
    assert g.state == cl.OPENED
    # Letters: Z ↔ A wraps.
    g = lock(w, code="ABC", kind="dial")
    w.frame(*DOWN)
    assert g.wheels[0] == "Z"
    w.frame(*UP)
    assert g.wheels[0] == "A"


# --- AC-F53-12 ---------------------------------------------------------------------------------

def test_ac_f53_12_letter_codes_ignore_case(w):
    assert rules.matches("LOVE", "love") and rules.matches("love", "LoVe")
    assert not rules.matches("LOVE", "lover")
    assert rules.alphabet("dial", "love") == rules.LETTERS
    assert rules.alphabet("dial", "0417") == rules.DIGITS
    assert rules.alphabet("keypad", "0417") == rules.DIGITS
    g = lock(w, code="love", kind="dial")
    for ch in "love":
        w.frame(*typed(ch))
    assert g.wheels == list("LOVE")
    w.frame(*ENTER)
    assert g.state == cl.OPENED


# --- AC-F53-13 ---------------------------------------------------------------------------------

def test_ac_f53_13_wrong_codes_and_out_of_tries(w):
    word = WORDS.__getitem__
    assert rules.wrong_message(1, 0, word) == "Wrong code."
    assert rules.wrong_message(5, 0, word) == "Wrong code."
    assert rules.wrong_message(1, 3, word) == "Wrong code. 2 tries left."
    assert rules.wrong_message(2, 3, word) == "Wrong code. 1 try left."
    assert rules.wrong_message(1, 2, word) == "Wrong code. 1 try left."
    assert rules.wrong_message(2, 2, word) == "No tries left. The lock stays shut."
    g = lock(w, code="0417", tries=2)
    keys_in(w, g, "1234")
    assert w.session.scope.focused is g.enter
    w.frame(*ENTER)
    assert g.message == "Wrong code. 1 try left." and g.entered == ""
    assert w.session.scope.focused is g.clear                 # not Step back
    keys_in(w, g, "1234")
    w.frame(*ENTER)
    assert g.message == WORDS["locked_out"] and g.state == cl.OUT
    assert w.session.scope.widgets() == [g.continue_button]
    assert w.session.scope.focused is g.continue_button       # keys: focused at once
    w.frame(*ENTER)
    assert g.finishes == [False]
    # The dial keeps its wheels after a wrong code; focus stays on Open.
    g = lock(w, code="123", kind="dial", tries=3)
    w.frame(*UP)
    for _ in range(3):
        w.frame(*RIGHT)
    assert w.session.scope.focused is g.open_button
    w.frame(*ENTER)
    assert g.wheels == ["1", "0", "0"] and g.message == "Wrong code. 2 tries left."
    assert w.session.scope.focused is g.open_button


# --- AC-F53-14 ---------------------------------------------------------------------------------

def test_ac_f53_14_hint_bar(w):
    g = lock(w, code="0417", hint="The date on the diary.", hint_after=2)
    assert w.session.hint_text == WORDS["hint_keypad"]
    for n in range(2):
        keys_in(w, g, "1111")
        w.frame(*ENTER)
        assert w.session.hint_text == (WORDS["hint_keypad"] if n == 0
                                       else "Hint: The date on the diary.")
    lock(w, code="0417", hint="Diary.", hint_after=0)
    assert w.session.hint_text == "Hint: Diary."
    lock(w, code="123", kind="dial")
    assert w.session.hint_text == WORDS["hint_dial"]


# --- AC-F53-15 ---------------------------------------------------------------------------------

def test_ac_f53_15_step_back(w):
    g = lock(w, code="0417")
    assert g.leave_button.label() == "Step back"
    click(w, g.leave_button)
    assert g.finishes == [False]
    assert done_after(w).result is False
    g = lock(w, code="0417", leave=False)
    assert g.leave_button not in w.session.scope.widgets()
    g = lock(w, code="123", kind="dial", leave=False)
    assert w.session.scope.widgets()[-1] is g.open_button


# --- AC-F53-16 ---------------------------------------------------------------------------------

W280 = ("code_lock can't be left: leave=False, tries=0 and no hint, so a player who missed "
        "the code can only skip or load. Add a hint, a try limit, or leave=True.")


def test_ac_f53_16_w280(game, caplog):
    caplog.set_level(logging.DEBUG)
    cl._WARNED.clear()
    assert rules.w280_text(rules.parse({"code": "1", "leave": False})) == W280
    for more in ({"tries": 3}, {"hint": "x"}, {"leave": True}):
        assert rules.w280_text(rules.parse({"code": "1", "leave": False, **more})) is None

    def records():
        return [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W280"]

    w = world(game, CodeLock)
    lock(w, code="0417", leave=False)
    lock(w, code="0417", leave=False)
    assert records() == [W280]                                # once per text
    cl._WARNED.clear()
    caplog.clear()
    w = world(game, CodeLock, dev=False)
    lock(w, code="0417", leave=False)
    assert records() == []                                    # dev only
