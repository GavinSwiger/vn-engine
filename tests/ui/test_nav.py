"""``NavReader`` and ``RepeatClock`` (F10 ``04`` §7.2): AC-F10-01, AC-F10-02, and the unit
rows of AC-F10-08. Synthetic events, no display.

Tables are loops in one test each, not ``parametrize``: every ``tests/ui`` test pays for
``pygame.init()``/``quit()`` (test-review-F10.md). Each assert names its row."""

import pygame

from engine.ui.input import UiEvent
from engine.ui.nav import Nav, NavReader, RepeatClock

K = pygame
C = pygame


def key(k: int, mod: int = 0, *, up: bool = False) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.KEYUP if up else pygame.KEYDOWN, key=k, mod=mod),
                   None, False)


def mouse(button: int, *, in_canvas: bool = True) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=(10, 10)),
                   (10, 10), in_canvas)


def wheel(y: int) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=y), (10, 10), True)


def pad(button: int, *, up: bool = False, instance: int = 1) -> UiEvent:
    kind = pygame.CONTROLLERBUTTONUP if up else pygame.CONTROLLERBUTTONDOWN
    return UiEvent(pygame.event.Event(kind, instance_id=instance, button=button), None, False)


def axis(value: int, which: int = C.CONTROLLER_AXIS_LEFTX, instance: int = 1) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=instance,
                                      axis=which, value=value), None, False)


def removed(instance: int) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.CONTROLLERDEVICEREMOVED, instance_id=instance),
                   None, False)


# AC-F10-01: raw event → Nav with dev=True.
PRESSES = [
    (key(K.K_UP), Nav.UP), (key(K.K_DOWN), Nav.DOWN),
    (key(K.K_LEFT), Nav.LEFT), (key(K.K_RIGHT), Nav.RIGHT),
    (pad(C.CONTROLLER_BUTTON_DPAD_UP), Nav.UP), (pad(C.CONTROLLER_BUTTON_DPAD_DOWN), Nav.DOWN),
    (pad(C.CONTROLLER_BUTTON_DPAD_LEFT), Nav.LEFT),
    (pad(C.CONTROLLER_BUTTON_DPAD_RIGHT), Nav.RIGHT),
    (key(K.K_TAB), Nav.NEXT), (key(K.K_TAB, K.KMOD_LSHIFT), Nav.PREV),
    (key(K.K_RETURN), Nav.ACTIVATE), (key(K.K_KP_ENTER), Nav.ACTIVATE),
    (key(K.K_SPACE), Nav.ACTIVATE), (pad(C.CONTROLLER_BUTTON_A), Nav.ACTIVATE),
    (key(K.K_ESCAPE), Nav.BACK), (mouse(3), Nav.BACK), (pad(C.CONTROLLER_BUTTON_B), Nav.BACK),
    (pad(C.CONTROLLER_BUTTON_START), Nav.START),
    (key(K.K_HOME), Nav.HOME), (key(K.K_END), Nav.END),
    (key(K.K_PAGEUP), Nav.PAGE_UP), (key(K.K_PAGEDOWN), Nav.PAGE_DOWN),
    (key(K.K_F3, K.KMOD_LSHIFT), Nav.SAMPLER), (key(K.K_F3, K.KMOD_RSHIFT), Nav.SAMPLER),
    (key(K.K_DOWN, K.KMOD_SHIFT), Nav.DOWN),
]

NOTHING = [
    key(K.K_F3), key(K.K_F3, K.KMOD_LSHIFT | K.KMOD_LCTRL), key(K.K_F11),
    key(K.K_RETURN, K.KMOD_LALT), key(K.K_h),
    pad(C.CONTROLLER_BUTTON_X), pad(C.CONTROLLER_BUTTON_Y), pad(C.CONTROLLER_BUTTON_BACK),
    pad(C.CONTROLLER_BUTTON_GUIDE),
    key(K.K_ESCAPE, K.KMOD_LCTRL), key(K.K_RETURN, K.KMOD_RALT), key(K.K_UP, K.KMOD_LMETA),
    key(K.K_TAB, K.KMOD_RCTRL), key(K.K_SPACE, K.KMOD_LGUI),
    mouse(3, in_canvas=False), mouse(1), mouse(2), wheel(1), wheel(-1),
    UiEvent(pygame.event.Event(pygame.WINDOWFOCUSLOST), None, False),
]

RELEASES = [
    (key(K.K_DOWN, up=True), Nav.DOWN), (key(K.K_LEFT, up=True), Nav.LEFT),
    (pad(C.CONTROLLER_BUTTON_DPAD_DOWN, up=True), Nav.DOWN),
    (pad(C.CONTROLLER_BUTTON_DPAD_UP, up=True), Nav.UP),
    (key(K.K_RETURN, up=True), None), (key(K.K_ESCAPE, up=True), None),
    (pad(C.CONTROLLER_BUTTON_A, up=True), None),
]


def test_ac01_presses_and_nothing():
    for ev, nav in PRESSES:
        reader = NavReader()
        assert reader.read(ev, dev=True) is nav, ev
        assert reader.released(ev) is None, ev
    for ev in NOTHING:
        reader = NavReader()
        assert reader.read(ev, dev=True) is None, ev
        assert reader.released(ev) is None, ev
    assert NavReader().read(key(K.K_F3, K.KMOD_LSHIFT), dev=False) is None   # sampler: dev only


def test_ac01_releases():
    for ev, nav in RELEASES:
        reader = NavReader()
        assert reader.read(ev, dev=True) is None, ev
        assert reader.released(ev) is nav, ev


# AC-F10-02: stick arming per controller.

def test_ac02_stick_sequence_steps_once_per_push():
    reader = NavReader()
    values = [0, 16_000, 16_385, 30_000, 16_385, 9_000, 16_385, 8_191, 20_000]
    presses, releases = [], []
    for v in values:
        ev = axis(v)
        presses.append(reader.read(ev, dev=True))
        releases.append(reader.released(ev))
    assert presses == [None, None, Nav.RIGHT, None, None, None, None, None, Nav.RIGHT]
    assert releases == [None] * 7 + [Nav.RIGHT, None]
    # ``released`` first, then ``read``, gives the same answers.
    reader = NavReader()
    ev = axis(20_000)
    assert reader.released(ev) is None
    assert reader.read(ev, dev=True) is Nav.RIGHT
    back = axis(0)
    assert reader.read(back, dev=True) is None
    assert reader.released(back) is Nav.RIGHT


def test_ac02_stick_axes():
    for which, value, nav in [
        (C.CONTROLLER_AXIS_LEFTX, -16_385, Nav.LEFT),
        (C.CONTROLLER_AXIS_LEFTX, 16_385, Nav.RIGHT),
        (C.CONTROLLER_AXIS_LEFTY, 16_385, Nav.DOWN),
        (C.CONTROLLER_AXIS_LEFTY, -16_385, Nav.UP),
        (C.CONTROLLER_AXIS_LEFTX, 16_384, None),          # not past the threshold
        (C.CONTROLLER_AXIS_RIGHTX, 30_000, None),
        (C.CONTROLLER_AXIS_RIGHTY, -30_000, None),
        (C.CONTROLLER_AXIS_TRIGGERLEFT, 32_767, None),
        (C.CONTROLLER_AXIS_TRIGGERRIGHT, 32_767, None),
    ]:
        assert NavReader().read(axis(value, which), dev=True) is nav, (which, value)
    # The two axes of one stick arm independently.
    reader = NavReader()
    assert reader.read(axis(20_000, C.CONTROLLER_AXIS_LEFTX), dev=True) is Nav.RIGHT
    assert reader.read(axis(20_000, C.CONTROLLER_AXIS_LEFTY), dev=True) is Nav.DOWN
    # Flipped past the centre between two events: a step and a release.
    reader = NavReader()
    assert reader.read(axis(20_000), dev=True) is Nav.RIGHT
    ev = axis(-20_000)
    assert reader.read(ev, dev=True) is Nav.LEFT
    assert reader.released(ev) is Nav.RIGHT


def test_ac02_controllers_arm_separately_and_reset():
    reader = NavReader()
    assert reader.read(axis(20_000, instance=1), dev=True) is Nav.RIGHT
    assert reader.read(axis(25_000, instance=1), dev=True) is None      # disarmed
    assert reader.read(axis(16_385, instance=2), dev=True) is Nav.RIGHT
    # CONTROLLERDEVICEREMOVED re-arms only that controller.
    assert reader.read(removed(1), dev=True) is None
    assert reader.read(axis(20_000, instance=1), dev=True) is Nav.RIGHT  # re-armed
    assert reader.read(axis(20_000, instance=2), dev=True) is None       # unchanged
    # reset() re-arms all of them.
    reader.reset()
    assert reader.read(axis(20_000, instance=1), dev=True) is Nav.RIGHT
    assert reader.read(axis(20_000, instance=2), dev=True) is Nav.RIGHT


# AC-F10-08 (unit rows): 0.5 s, then every 0.08 s, at most 2 per tick.

def test_ac08_repeat_clock_cumulative_at_60_fps():
    clock = RepeatClock()
    clock.start(Nav.DOWN)
    total, seen = 0, {}
    for frame in range(1, 79):                 # 78 frames = 1.30 s
        total += clock.tick(1 / 60)
        seen[frame] = total
    assert seen[29] == 0                       # 0.483 s (< 0.49)
    assert seen[30] == 1                       # 0.50 s
    assert seen[35] == 2                       # 0.583 s (≥ 0.58)
    assert seen[40] == 3                       # 0.667 s (≥ 0.66)
    assert seen[78] == 11                      # 1.30 s


def test_ac08_repeat_clock_cap_stop_and_restart():
    clock = RepeatClock()
    clock.start(Nav.RIGHT)
    assert clock.tick(0.5) == 1
    assert clock.tick(0.3) == 2                # 3 due, capped at 2, excess dropped
    assert clock.tick(0.0) == 0
    assert clock.tick(0.08) == 1
    clock = RepeatClock()
    assert clock.tick(1.0) == 0                # never started
    clock.start(Nav.UP)
    assert clock.nav is Nav.UP
    clock.tick(0.4)
    clock.stop()
    assert clock.nav is None
    assert clock.tick(1.0) == 0
    clock.start(Nav.UP)                        # a new press starts from zero
    assert clock.tick(0.49) == 0
    assert clock.tick(0.01) == 1
