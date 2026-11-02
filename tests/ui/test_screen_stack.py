"""ScreenStack semantics (§7.15): AC-F01-93; F10 step 5: AC-F10-30 (bubbling through
``in_game`` screens, ``story_may_run``, ``pointer``)."""

import pygame
import pytest

from engine.ui.input import UiEvent
from engine.ui.screen import Screen, ScreenStack
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app

pytestmark = pytest.mark.display


class Recorder(Screen):
    def __init__(self, name: str, log: list, *, opaque: bool = True) -> None:
        self.name = name
        self.log = log
        self.opaque = opaque

    def on_enter(self):
        self.log.append(("enter", self.name))

    def on_exit(self):
        self.log.append(("exit", self.name))

    def handle_event(self, event):
        self.log.append(("event", self.name))
        return True

    def update(self, dt, *, is_top):
        self.log.append(("update", self.name, is_top))

    def draw(self, canvas):
        self.log.append(("draw", self.name))


def key_event() -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0), None, False)


def build(opaque: list[bool]) -> tuple[ScreenStack, list, list[Recorder]]:
    log: list = []
    stack = ScreenStack()
    screens = [Recorder(f"S{i + 1}", log, opaque=o) for i, o in enumerate(opaque)]
    for screen in screens:
        stack.push(screen)
    log.clear()
    return stack, log, screens


def test_events_reach_only_the_top_screen():
    stack, log, _ = build([True, False, False])
    assert stack.handle_event(key_event()) is True
    assert log == [("event", "S3")]


def test_update_reaches_every_screen_bottom_to_top():
    stack, log, _ = build([True, False, False])
    stack.update(0.016)
    assert log == [("update", "S1", False), ("update", "S2", False), ("update", "S3", True)]


def test_draw_starts_at_the_highest_opaque_screen():
    stack, log, _ = build([True, False, False])
    stack.draw(None)
    assert log == [("draw", "S1"), ("draw", "S2"), ("draw", "S3")]
    stack, log, _ = build([True, True, False])
    stack.draw(None)
    assert log == [("draw", "S2"), ("draw", "S3")]


def test_a_screen_pushed_during_update_is_not_updated_in_that_pass():
    stack, log, _ = build([True])
    pushed = Recorder("new", log)

    class Pusher(Screen):
        def update(self, dt, *, is_top):
            stack.push(pushed)

    stack.push(Pusher())
    log.clear()
    stack.update(0.016)
    assert ("update", "new", True) not in log and ("update", "new", False) not in log
    assert stack.top is pushed


def test_enter_and_exit_hooks():
    log: list = []
    stack = ScreenStack()
    a, b, c = (Recorder(n, log) for n in "abc")
    stack.push(a)
    stack.push(b)
    assert stack.pop() is b
    stack.replace_all([c])
    assert log == [("enter", "a"), ("enter", "b"), ("exit", "b"), ("exit", "a"), ("enter", "c")]
    assert list(stack) == [c] and len(stack) == 1 and stack.top is c


def test_safe_replace_survives_a_failing_on_exit():
    stack = ScreenStack()

    class Bad(Screen):
        def on_exit(self):
            raise RuntimeError("bad exit")

    stack.push(Bad())
    with pytest.raises(RuntimeError):
        stack.replace_all([])
    stack.push(Bad())
    replacement = Screen()
    stack.replace_all([replacement], safe_exit=True)
    assert list(stack) == [replacement]


def test_no_opaque_screen_means_the_canvas_is_filled_black_first():
    window = FakeWindow((1280, 720), probe_points=[(640, 360)])
    app, limiter = make_app(window)

    class Clear(Screen):
        opaque = False

    # Paint the framebuffer white before the frame; the App must clear the canvas.
    window.framebuffer().fill((255, 255, 255))
    app.screens.push(Clear())
    limiter.quit_at(1)
    app.run()
    assert window.flips[0].probes[(640, 360)] == (0, 0, 0)


# --- AC-F10-30 — in-game bubbling, the story hold, and the pointer --------------------------------

class Bubble(Screen):
    """A recording test screen: ``in_game`` and the value ``handle_event`` returns."""

    def __init__(self, name: str, log: list, *, in_game: bool, returns: bool = False) -> None:
        self.name = name
        self.log = log
        self.in_game = in_game
        self.returns = returns

    def handle_event(self, event):
        self.log.append(self.name)
        return self.returns


def bubble_stack(spec: str) -> tuple[ScreenStack, list]:
    """``spec`` bottom → top, e.g. ``"S:ig:F T:ig:T M:-:F"``."""
    log: list = []
    stack = ScreenStack()
    for item in spec.split():
        name, ig, returns = item.split(":")
        stack.push(Bubble(name, log, in_game=ig == "ig", returns=returns == "T"))
    return stack, log


@pytest.mark.parametrize("spec, receivers, returns", [
    ("S:ig:F T:ig:F C:ig:F", ["C", "T", "S"], False),
    ("S:ig:F T:ig:T C:ig:F", ["C", "T"], True),
    ("S:ig:F T:ig:F M:-:F", ["M"], False),
    ("S:ig:F M:-:F X:ig:F", ["X"], False),
    ("Title:-:F X:ig:F", ["X"], False),
], ids=["all-in-game", "middle-consumes", "menu-top", "menu-in-between", "over-the-title"])
def test_ac_f10_30_bubbling(spec, receivers, returns):
    stack, log = bubble_stack(spec)
    assert stack.handle_event(key_event()) is returns
    assert log == receivers


def test_ac_f10_30_a_consuming_menu_top_and_an_empty_stack():
    stack, log = bubble_stack("S:ig:F M:-:T")
    assert stack.handle_event(key_event()) is True and log == ["M"]
    assert ScreenStack().handle_event(key_event()) is False


def test_ac_f10_30_bubbling_walks_a_snapshot():
    """A screen that changes the stack while handling keeps this event's receivers."""
    log: list = []
    stack = ScreenStack()
    stack.push(Bubble("S", log, in_game=True))

    class Closer(Bubble):
        def handle_event(self, event):
            stack.pop()
            stack.push(Bubble("new", log, in_game=True))
            return super().handle_event(event)

    stack.push(Closer("C", log, in_game=True))
    assert stack.handle_event(key_event()) is False
    assert log == ["C", "S"]


def test_ac_f10_30_story_may_run():
    stack = ScreenStack()
    assert stack.story_may_run() is True                         # empty stack
    log: list = []
    stack.push(Bubble("S", log, in_game=True))
    assert stack.story_may_run() is True                         # top in_game
    stack.push(Bubble("M", log, in_game=False))
    assert stack.story_may_run() is False                        # a menu on top
    stack.push(Bubble("X", log, in_game=True))
    assert stack.story_may_run() is True
    stack.replace_all([Screen()])
    assert Screen.in_game is False and stack.story_may_run() is False


def test_ac_f10_30_builtin_screens():
    """F05's textbox and F04's stage are in-game (F10 I-1); F01's placeholder and error
    screens are not."""
    from engine.ui.builtin.error import ErrorScreen
    from engine.ui.builtin.placeholder import PlaceholderScreen
    from engine.ui.builtin.stage_screen import StageScreen
    from engine.ui.builtin.textbox_screen import TextboxScreen

    assert TextboxScreen.in_game is True and StageScreen.in_game is True
    assert TextboxScreen.opaque is False
    assert PlaceholderScreen.in_game is False and ErrorScreen.in_game is False


@pytest.mark.parametrize("module, name", [
    ("engine.ui.menu_screen", "MenuScreen"),
    ("engine.ui.builtin.black_fade", "BlackFadeScreen"),
])
def test_ac_f10_30_f10_screens_hold_the_story(module, name):
    """Runs once F10 steps 4 and 6 add these screens."""
    cls = getattr(pytest.importorskip(module), name)
    assert cls.in_game is False


def mouse(kind: int, pos, inside: bool) -> UiEvent:
    attrs = {"pos": (0, 0), "rel": (0, 0), "buttons": (0, 0, 0)} if kind == pygame.MOUSEMOTION         else {"pos": (0, 0), "button": 1}
    return UiEvent(pygame.event.Event(kind, **attrs), pos, inside)


def test_ac_f10_30_pointer():
    stack, log = bubble_stack("S:ig:F M:-:F")
    assert stack.pointer is None                                  # no mouse event yet
    stack.handle_event(mouse(pygame.MOUSEMOTION, (100, 200), True))
    assert stack.pointer == (100, 200)
    stack.handle_event(key_event())                               # keys leave it alone
    assert stack.pointer == (100, 200)
    stack.handle_event(mouse(pygame.MOUSEBUTTONDOWN, (300, 400), True))
    assert stack.pointer == (300, 400)
    stack.handle_event(mouse(pygame.MOUSEMOTION, (-12, 400), False))   # into the letterbox
    assert stack.pointer is None
    stack.handle_event(mouse(pygame.MOUSEMOTION, (5, 6), True))
    assert stack.pointer == (5, 6)
    assert log.count("M") == 5 and "S" not in log                 # the menu still gets all


def test_ac_f10_30_pointer_through_the_app():
    """A real translated motion: the bars of a 1600x720 window are outside the canvas."""
    window = FakeWindow((1600, 720))
    app, limiter = make_app(window)
    app.screens.push(Screen())
    seen = []
    limiter.at(2, lambda: pygame.event.post(pygame.event.Event(
        pygame.MOUSEMOTION, pos=(800, 360), rel=(0, 0), buttons=(0, 0, 0))))
    limiter.at(3, lambda: seen.append(app.screens.pointer))
    limiter.at(3, lambda: pygame.event.post(pygame.event.Event(
        pygame.MOUSEMOTION, pos=(20, 360), rel=(0, 0), buttons=(0, 0, 0))))
    limiter.at(4, lambda: seen.append(app.screens.pointer))
    limiter.quit_at(4)
    assert app.run() == 0
    assert seen == [(640, 360), None]


# --- F10 step 6: ScreenStack.remove (F10 I-8, the quit guard; F07 C6) ---------------------------

def test_remove_takes_a_screen_out_wherever_it_is():
    log: list = []
    stack = ScreenStack()
    a, b, c = (Recorder(name, log) for name in "abc")
    for screen in (a, b, c):
        stack.push(screen)
    log.clear()
    assert stack.remove(b) is True
    assert list(stack) == [a, c] and log == [("exit", "b")]
    assert stack.remove(b) is False and log == [("exit", "b")]    # already gone: nothing
    assert stack.remove(c) is True and stack.top is a


def test_a_menu_below_the_top_closes_with_remove():
    """MenuScreen closes through ``ScreenStack.remove`` (no pop fallback): a menu covered by
    another screen can finish its close."""
    from engine.ui.nav import InputKind
    from tests.fakes.ui_shell import ColumnMenu, TestShell

    shell = TestShell()
    menu = ColumnMenu(shell, by=InputKind.KEYS, fade=False)
    top = Recorder("top", [])
    shell.stack.push(menu)
    shell.stack.push(top)
    menu.close()
    assert list(shell.stack) == [top]
