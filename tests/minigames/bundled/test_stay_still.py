"""F53 step P2: Stay still (``stay_still``): AC-F53-17 (what counts and what never does), 18
(held keys and joined presses), 19 (the ready step and the grace), 20 (the clock and
``strict``), 21 (the flinch line and the countdown) and 22 (pointer travel)."""

import pygame
import pytest

from engine.minigames.api import PluginEvent
from engine.minigames.bundled import still_rules as rules
from engine.minigames.bundled.stay_still import WORDS, StayStill, touch_of
from engine.minigames.bundled.still_rules import COUNT, JOIN, PASS, SWALLOW, Touch, Watch
from engine.ui.input import UiEvent
from engine.ui.nav import Nav
from tests.minigames.bundled.quick_host import H, done_after, open_game, pad, tap, world

DT = 1 / 60


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def watching(**args) -> Watch:
    """A Watch already past its grace."""
    w = Watch(rules.parse({**args, "ready": False}))
    w.advance(rules.GRACE_START)
    assert w.state == rules.WATCHING
    return w


def ev(raw_type: int, nav=None, pos=None, **attrs) -> PluginEvent:
    raw = pygame.event.Event(raw_type, **attrs)
    return PluginEvent(UiEvent(raw, pos, pos is not None), nav)


# --- AC-F53-17 ---------------------------------------------------------------------------------

def test_ac_f53_17_what_counts(game):
    counts = [
        ev(pygame.KEYDOWN, key=pygame.K_a, mod=0),
        ev(pygame.KEYDOWN, key=pygame.K_SPACE, mod=0, nav=Nav.ACTIVATE),
        ev(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0, nav=Nav.BACK),
        ev(pygame.MOUSEBUTTONDOWN, pos=(9, 9), button=1),
        ev(pygame.MOUSEBUTTONDOWN, pos=(9, 9), button=2),
        ev(pygame.MOUSEBUTTONDOWN, pos=(9, 9), button=6),
        ev(pygame.MOUSEWHEEL, pos=(9, 9), x=0, y=1),
        ev(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_A),
        ev(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_Y),
        ev(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_DPAD_UP, nav=Nav.UP),
        ev(pygame.CONTROLLERAXISMOTION, nav=Nav.LEFT, axis=0, value=-30000, instance_id=0),
    ]
    for e in counts:
        w = watching()
        assert w.touch(touch_of(e)) == COUNT and w.count == 1, e.ui.raw
    never = [
        ev(pygame.MOUSEBUTTONDOWN, pos=(9, 9), button=3, nav=Nav.BACK),
        ev(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_B, nav=Nav.BACK),
        ev(pygame.KEYUP, key=pygame.K_a, mod=0),
        ev(pygame.MOUSEBUTTONUP, pos=(9, 9), button=1),
        ev(pygame.CONTROLLERBUTTONUP, button=pygame.CONTROLLER_BUTTON_A),
        ev(pygame.CONTROLLERAXISMOTION, axis=0, value=200, instance_id=0),
        ev(pygame.MOUSEMOTION, pos=(400, 400), rel=(300, 300), buttons=(0, 0, 0)),
        ev(pygame.WINDOWFOCUSLOST),
        ev(pygame.WINDOWFOCUSGAINED),
        ev(pygame.WINDOWLEAVE),
    ] + [ev(pygame.KEYDOWN, key=k, mod=0) for k in (     # C1: a modifier alone
        pygame.K_LSHIFT, pygame.K_RSHIFT, pygame.K_LCTRL, pygame.K_RCTRL, pygame.K_LALT,
        pygame.K_RALT, pygame.K_LGUI, pygame.K_RGUI)]
    for e in never:
        w = watching()
        assert w.touch(touch_of(e)) in (PASS, SWALLOW) and w.count == 0, e.ui.raw
    # The wheel echo on buttons 4/5 is swallowed (the wheel event counts).
    w = watching()
    assert w.touch(Touch("button", 4)) == SWALLOW and w.count == 0
    # Away, and just after coming back (the refocusing click), nothing counts.
    w = watching()
    w.touch(Touch("focus_lost"))
    assert w.touch(Touch("button", 1)) == SWALLOW
    w.touch(Touch("focus_gained"))
    assert w.touch(Touch("button", 1)) == SWALLOW
    w.advance(0.3)
    assert w.touch(Touch("button", 1)) == COUNT
    # In play: right click and gamepad B pass on (they open the game menu); a key is used.
    world_ = world(game, StayStill)
    g = open_game(world_, "stay_still", {**rules.DEFAULTS, "ready": False})
    world_.frames(70)
    assert g.watch.state == rules.WATCHING
    screen = world_.screen
    assert screen.handle_event(H.down((640, 400), 3)) is False
    assert screen.handle_event(H.pad(pygame.CONTROLLER_BUTTON_B)) is False
    assert screen.handle_event(H.key(pygame.K_ESCAPE)) is False
    assert g.watch.count == 0
    world_.frame(*tap(pygame.K_x))
    assert g.watch.count == 1 and len(world_.used()) == 1


# --- AC-F53-18 ---------------------------------------------------------------------------------

def test_ac_f53_18_held_keys_and_joined_presses():
    w = watching()
    a = Touch("key_down", pygame.K_a)
    assert w.touch(a) == COUNT
    w.advance(1.0)
    assert w.touch(a) == SWALLOW and w.count == 1             # still held: no new flinch
    assert w.touch(Touch("key_up", pygame.K_a)) == PASS
    assert w.touch(a) == COUNT and w.count == 2               # pressed again
    w.advance(0.1)
    assert w.touch(Touch("button", 1)) == JOIN                # within 0.25 s: joins it
    w.advance(0.1)
    assert w.touch(Touch("wheel")) == JOIN and w.count == 2
    w.advance(0.06)
    assert w.touch(Touch("wheel")) == COUNT and w.count == 3


# --- AC-F53-19 ---------------------------------------------------------------------------------

def test_ac_f53_19_ready_and_grace(game):
    w = world(game, StayStill)
    g = open_game(w, "stay_still", dict(rules.DEFAULTS))
    w.frame()
    assert w.session.hint_text == WORDS["hint_ready"]
    assert w.session.scope.focused is g.ready_button           # keys: first focus
    w.frames(120)
    assert g.countdown() == 10                                 # the clock waits for ready
    w.frame(*tap(pygame.K_x))
    assert g.watch.count == 0
    w.frame(*tap(pygame.K_RETURN))                             # I'm ready
    assert g.watch.state == rules.GRACE and w.session.hint_text == WORDS["hint"]
    assert w.session.scope.widgets() == []
    w.frames(25)                                               # inside the 0.5 s grace
    w.frame(*tap(pygame.K_x))
    assert g.watch.count == 0 and g.watch.state == rules.GRACE
    w.frames(10)
    assert g.watch.state == rules.WATCHING
    w.frame(*tap(pygame.K_y))
    assert g.watch.count == 1
    # Mouse and gamepad reach I'm ready too.
    g = open_game(w, "stay_still", dict(rules.DEFAULTS))
    w.frame()
    w.ui.click(g.ready_button.box.center)
    assert g.watch.state == rules.GRACE
    g = open_game(w, "stay_still", dict(rules.DEFAULTS))
    w.frame()
    w.frame(*pad(pygame.CONTROLLER_BUTTON_A))                  # after the mouse: focuses it
    w.frame(*pad(pygame.CONTROLLER_BUTTON_A))
    assert g.watch.state == rules.GRACE
    # ready=False: 1.0 s from the start.
    g = open_game(w, "stay_still", {**rules.DEFAULTS, "ready": False})
    assert w.session.hint_text == WORDS["hint"] and w.session.scope.widgets() == []
    w.frames(55)
    w.frame(*tap(pygame.K_x))
    assert g.watch.count == 0
    w.frames(6)
    w.frame(*tap(pygame.K_x))
    assert g.watch.count == 1


# --- AC-F53-20 ---------------------------------------------------------------------------------

def test_ac_f53_20_clock_and_strict(game):
    spec = rules.parse({"seconds": 3, "ready": False})
    watch = Watch(spec)
    watch.advance(rules.GRACE_START)
    for _ in range(2):
        watch.touch(Touch("key_down", pygame.K_a))
        watch.touch(Touch("key_up", pygame.K_a))
        watch.advance(1.0)
    assert not watch.done
    watch.advance(1.0 - 1e-12)
    assert watch.done and watch.result == 2
    strict = Watch(rules.parse({"seconds": 3, "ready": False, "strict": True}))
    strict.advance(1.5)
    assert strict.touch(Touch("wheel")) == COUNT and strict.done and strict.result == 1
    # In play: the clock is update(dt) only; under the game menu it waits.
    w = world(game, StayStill)
    g = open_game(w, "stay_still", {**rules.DEFAULTS, "seconds": 3, "ready": False})
    w.frames(60 + 60)
    from tests.fakes.ui_shell import SolidScreen
    w.shell.stack.push(SolidScreen((1, 1, 1)))
    w.frames(600)
    assert g.countdown() == 2 and not g.finishes
    w.shell.stack.pop()
    w.focused = False                                          # the window is away
    w.frames(600)
    assert g.countdown() == 2 and not g.finishes
    w.focused = True
    assert done_after(w).result == 0
    g = open_game(w, "stay_still", {**rules.DEFAULTS, "ready": False, "strict": True})
    w.frames(70)
    w.frame(*tap(pygame.K_q))
    assert g.finishes == [1]


# --- AC-F53-21 ---------------------------------------------------------------------------------

def test_ac_f53_21_flinch_line_and_countdown(game):
    assert [rules.countdown(t) for t in (10.0, 9.99, 9.0, 0.01, 0.0)] == [10, 10, 9, 1, 0]
    assert rules.bar_fraction(9.5, 10, reduce=False) == pytest.approx(0.95)
    assert rules.bar_fraction(9.5, 10, reduce=True) == pytest.approx(1.0)  # steps a second
    w = world(game, StayStill)
    g = open_game(w, "stay_still", {**rules.DEFAULTS, "ready": False, "seconds": 20,
                                    "line": "Don't touch anything. I'll know.",
                                    "speaker": "Monika"})
    w.frames(70)
    assert g.shown_line() == "Don't touch anything. I'll know."
    w.frame(*tap(pygame.K_q))
    assert g.shown_line() == WORDS["flinch_line"]
    w.frames(118)
    assert g.shown_line() == WORDS["flinch_line"]
    w.frames(3)
    assert g.shown_line() == "Don't touch anything. I'll know."
    g = open_game(w, "stay_still", {**rules.DEFAULTS, "ready": False, "flinch_line": "Stop."})
    w.frames(70)
    w.frame(*tap(pygame.K_q))
    assert g.shown_line() == "Stop."


# --- AC-F53-22 ---------------------------------------------------------------------------------

def test_ac_f53_22_pointer_travel():
    w = watching(mouse=True)
    assert w.touch(Touch("motion", pos=(100, 100))) == PASS
    assert w.touch(Touch("motion", pos=(110, 100))) == PASS
    assert w.touch(Touch("motion", pos=(123, 100))) == PASS and w.count == 0   # 23 units
    assert w.touch(Touch("motion", pos=(124, 100))) == COUNT and w.count == 1  # 24
    w.advance(1.0)
    w.touch(Touch("motion", pos=(124, 120)))
    w.touch(Touch("motion", pos=None))                        # left the canvas
    assert w.touch(Touch("motion", pos=(800, 600))) == PASS and w.count == 1
    off = watching(mouse=False)
    off.touch(Touch("motion", pos=(0, 0)))
    assert off.touch(Touch("motion", pos=(500, 500))) == PASS and off.count == 0
