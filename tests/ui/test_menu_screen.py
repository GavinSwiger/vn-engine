"""``MenuScreen`` with the test shell (F10 SPEC step 4): AC-F10-05 (one focus for mouse and
keys), AC-F10-06 (activation), the fades and mid-fade input of ``04`` §7.5, UI sounds
(UI-F10-14), the cursor (PR-F10-13, I-13), and back-to-the-opener (the unit form of
AC-F10-07)."""

import dataclasses

import pygame
import pytest

from engine.core.config_schema import ButtonTheme, ThemeConfig, UiAreaTheme
from engine.ui.menu_screen import Phase
from engine.ui.nav import InputKind
from tests.fakes.ui_shell import ColumnMenu, SolidScreen, TestShell, UiHarness

pytestmark = pytest.mark.display

H = UiHarness


def sound_theme() -> ThemeConfig:
    cfg = ThemeConfig()
    return dataclasses.replace(
        cfg, ui=dataclasses.replace(UiAreaTheme(), back_sound="b.ogg"),
        button=dataclasses.replace(ButtonTheme(), focus_sound="f.ogg", activate_sound="a.ogg"))


def open_menu(*, by=InputKind.MOUSE, shell=None, fade=False, **kw):
    shell = shell or TestShell()
    harness = UiHarness(shell)
    menu = ColumnMenu(shell, by=by, fade=fade, **kw)
    shell.stack.push(menu)
    harness.frame()
    return shell, harness, menu


def focus_of(menu):
    scope = menu.scope
    if scope.focused is None:
        return None
    return menu.buttons.index(scope.focused), scope.source


# --- AC-F10-05 --------------------------------------------------------------------------------

def test_mouse_and_keys_share_one_focus():
    shell, h, menu = open_menu()
    b2, b3, empty = menu.center(1), menu.center(2), (900, 600)
    assert focus_of(menu) is None                                    # opened by mouse
    h.frame(H.motion(b2))
    assert focus_of(menu) == (1, InputKind.MOUSE)
    h.frame(H.motion(empty))
    assert focus_of(menu) is None
    h.frame(H.key(pygame.K_DOWN))
    assert focus_of(menu) == (0, InputKind.KEYS)                     # default, no move
    assert menu.counts == [0, 0, 0]
    h.frame(H.key(pygame.K_DOWN))
    assert focus_of(menu) == (1, InputKind.KEYS)
    h.frame(H.motion(empty))
    assert focus_of(menu) == (1, InputKind.KEYS)                     # key focus survives
    h.frame(H.motion(b3))
    assert focus_of(menu) == (2, InputKind.MOUSE)
    h.frame(H.key(pygame.K_UP))
    assert focus_of(menu) == (1, InputKind.KEYS)


def test_a_screen_opened_by_keys_focuses_the_default_without_a_sound():
    shell = TestShell(cfg=sound_theme())
    _, _, menu = open_menu(by=InputKind.KEYS, shell=shell)
    assert focus_of(menu) == (0, InputKind.KEYS) and menu.scope.visible
    assert [s for s in shell.sounds if s] == []


def test_hover_and_key_focus_draw_the_same_pixels():
    _, h, menu = open_menu()
    h.frame(H.motion(menu.center(1)))
    by_hover = pygame.image.tobytes(h.framebuffer, "RGB")
    _, h2, menu2 = open_menu()
    h2.frame(H.key(pygame.K_DOWN))
    h2.frame(H.key(pygame.K_DOWN))
    h2.frame(H.motion((1000, 650)))                 # pointer away; key focus stays on B2
    assert focus_of(menu2) == (1, InputKind.KEYS)
    assert pygame.image.tobytes(h2.framebuffer, "RGB") == by_hover


# --- AC-F10-06 --------------------------------------------------------------------------------

def test_click_activates_at_the_up_on_the_same_button():
    _, h, menu = open_menu()
    b1, b2 = menu.center(0), menu.center(1)
    h.frame(H.down(b1))
    assert menu.counts == [0, 0, 0]
    h.frame(H.up(b1))
    assert menu.counts == [1, 0, 0]
    h.frame(H.down(b1), H.motion(b2), H.up(b2))
    assert menu.counts == [1, 0, 0]
    h.frame(H.down(b1), H.motion((900, 600)), H.motion(b1), H.up(b1))
    assert menu.counts == [2, 0, 0]


def test_an_up_without_a_press_in_this_screen_does_nothing():
    _, h, menu = open_menu()
    h.frame(H.up(menu.center(0)))                    # the click that opened the screen
    assert menu.counts == [0, 0, 0]


def test_letterbox_clicks_do_nothing():
    shell = TestShell()
    h = UiHarness(shell, window=(1600, 720))
    menu = ColumnMenu(shell, by=InputKind.MOUSE, fade=False)
    shell.stack.push(menu)
    h.frame()
    # B1's window position, but the window is 1600 wide: x 100..420 is the left bar.
    pos = (menu.center(0)[0] - 1000, menu.center(0)[1])
    h.frame(H.down(pos, in_canvas=False), H.up(pos, in_canvas=False))
    assert menu.counts == [0, 0, 0] and menu.scope.focused is None


def test_disabled_and_middle_button_never_activate():
    _, h, menu = open_menu(disabled=(2,))
    h.click(menu.center(2))
    h.frame(H.down(menu.center(0), button=2), H.up(menu.center(0), button=2))
    assert menu.counts == [0, 0, 0]
    assert menu.scope.focused is None


def test_enter_activates_the_focused_button_in_that_frame():
    _, h, menu = open_menu(by=InputKind.KEYS)
    h.frame(H.key(pygame.K_RETURN))
    assert menu.counts == [1, 0, 0]


def test_a_screen_pushed_during_an_event_never_receives_it():
    shell, h, menu = open_menu(by=InputKind.KEYS)
    pushed = []

    def push():
        child = ColumnMenu(shell, by=InputKind.KEYS, fade=False)
        pushed.append(child)
        shell.stack.push(child)

    menu.on_activate[0] = push
    h.frame(H.key(pygame.K_RETURN))
    assert shell.stack.top is pushed[0]
    assert pushed[0].received == [] and pushed[0].counts == [0, 0, 0]


def test_menus_consume_everything():
    shell = TestShell()
    h = UiHarness(shell)
    scene = SolidScreen()
    shell.stack.push(scene)
    shell.stack.push(ColumnMenu(shell, by=InputKind.MOUSE, fade=False))
    h.frame(H.key(pygame.K_h), H.wheel((500, 500), -1), H.down((900, 600), 3))
    assert scene.received == []


# --- Pressed look, sounds, Back -------------------------------------------------------------------

def test_key_activation_shows_the_pressed_look_for_six_frames():
    shell, h, menu = open_menu(by=InputKind.KEYS)
    looks = []
    h.frame(H.key(pygame.K_RETURN))
    looks.append(menu.look_for(menu.buttons[0]).state)
    for _ in range(8):
        h.frame()
        looks.append(menu.look_for(menu.buttons[0]).state)
    assert looks == ["pressed"] * 6 + ["focused"] * 3


def test_held_mouse_press_looks_pressed_until_the_up():
    _, h, menu = open_menu()
    h.frame(H.motion(menu.center(0)), H.down(menu.center(0)))
    h.frames(20)
    assert menu.look_for(menu.buttons[0]).state == "pressed"
    h.frame(H.motion((900, 600)))
    assert menu.look_for(menu.buttons[0]).state != "pressed"     # held, but not over it
    h.frame(H.motion(menu.center(0)), H.up(menu.center(0)))
    assert menu.look_for(menu.buttons[0]).state == "focused" and menu.counts[0] == 1


def test_ui_sounds():
    shell = TestShell(cfg=sound_theme())
    _, h, menu = open_menu(shell=shell)
    h.frame(H.motion(menu.center(1)))                 # focus change by hover
    h.frame(H.motion((900, 600)))                     # clearing: no sound
    h.frame(H.key(pygame.K_DOWN))                     # first nav: focuses the default
    h.frame(H.key(pygame.K_DOWN))                     # move
    h.frame(H.key(pygame.K_RETURN))                   # activate
    h.click(menu.center(2))                           # hover focus + click activation
    h.frame(H.key(pygame.K_ESCAPE))                   # back
    assert [s for s in shell.sounds if s] == ["f.ogg", "f.ogg", "f.ogg", "a.ogg", "f.ogg",
                                              "a.ogg", "b.ogg"]


@pytest.mark.parametrize("event", [H.key(pygame.K_ESCAPE),
                                   H.pad(pygame.CONTROLLER_BUTTON_B),
                                   H.down((900, 600), 3)])
def test_back_closes(event):
    shell, h, menu = open_menu()
    h.frame(event)
    assert shell.stack.top is None and menu.counts == [0, 0, 0]


def test_start_and_bare_f3_do_nothing_by_default():
    shell, h, menu = open_menu()
    h.frame(H.pad(pygame.CONTROLLER_BUTTON_START), H.key(pygame.K_F3),
            H.key(pygame.K_F3, pygame.KMOD_SHIFT))
    assert shell.stack.top is menu


# --- Back to the opener (unit form of AC-F10-07) ------------------------------------------------

@pytest.mark.parametrize(("event", "visible"), [
    (H.key(pygame.K_ESCAPE), True),
    (H.pad(pygame.CONTROLLER_BUTTON_B), True),
    (H.down((900, 650), 3), False),
])
def test_back_returns_focus_to_the_opener(event, visible):
    shell, h, parent = open_menu(by=InputKind.KEYS, fade=True)
    h.frames(10)
    children = []

    def open_child():
        child = ColumnMenu(shell, by=InputKind.KEYS)
        children.append(child)
        parent.push_child(child)

    parent.on_activate[1] = open_child
    h.frame(H.key(pygame.K_DOWN))
    h.frame(H.key(pygame.K_RETURN))
    child = children[0]
    h.frames(10)
    assert child.phase is Phase.OPEN
    h.frame(event)
    assert shell.stack.top is child and child.phase is Phase.CLOSING
    h.frames(10)
    assert shell.stack.top is parent
    assert parent.scope.focused is parent.buttons[1]
    assert parent.scope.visible is visible
    assert parent.look_for(parent.buttons[1]).state == ("focused" if visible else "normal")


# --- Fades (04 §7.5) ------------------------------------------------------------------------------

def test_opening_fade_runs_nine_frames_from_the_frame_after_the_input():
    shell, h, menu = open_menu(fade=True)
    alphas = [menu.alpha]
    for _ in range(9):
        h.frame()
        alphas.append(menu.alpha)
    assert alphas[0] == 0.0 and 0 < alphas[1] < 0.2
    assert menu.phase is Phase.OPEN and alphas[-1] == 1.0
    assert all(a < b for a, b in zip(alphas, alphas[1:]))


def test_input_while_opening_finishes_the_fade_then_acts():
    shell, h, menu = open_menu(fade=True, by=InputKind.KEYS)
    h.frame(H.key(pygame.K_RETURN))
    assert menu.phase is Phase.OPEN and menu.counts == [1, 0, 0]


def test_input_while_closing_finishes_it_and_goes_to_the_screen_below():
    shell = TestShell()
    h = UiHarness(shell)
    below = ColumnMenu(shell, by=InputKind.KEYS, fade=False)
    shell.stack.push(below)
    top = ColumnMenu(shell, by=InputKind.KEYS)
    shell.stack.push(top)
    h.frames(10)
    h.frame(H.key(pygame.K_ESCAPE))
    assert top.phase is Phase.CLOSING and shell.stack.top is top
    h.frame()
    h.frame(H.key(pygame.K_RETURN))
    assert shell.stack.top is below
    assert top.counts == [0, 0, 0] and below.counts == [1, 0, 0]


def test_close_runs_then_after_removal():
    shell, h, menu = open_menu(fade=True)
    h.frames(10)
    seen = []
    menu.close(then=lambda: seen.append(shell.stack.top))
    h.frames(8)
    assert seen == [] and shell.stack.top is menu
    h.frames(2)
    assert seen == [None]


def test_reduced_motion_cuts():
    shell = TestShell(reduce_motion=True)
    _, h, menu = open_menu(shell=shell, fade=True)
    assert menu.phase is Phase.OPEN
    seen = []
    menu.close(then=lambda: seen.append(1))
    assert shell.stack.top is None and seen == [1]


def test_fade_layer_is_panel_sized():
    shell = TestShell()
    h = UiHarness(shell)
    shell.stack.push(SolidScreen())
    menu = ColumnMenu(shell, by=InputKind.MOUSE)
    shell.stack.push(menu)
    h.frames(3)
    assert menu.phase is Phase.OPENING
    layer = menu._layer
    assert layer is not None and layer.get_size() == (320, 56 * 3 + 12 * 2)
    h.frames(8)
    assert menu.phase is Phase.OPEN and menu._layer is None


def test_fade_draws_the_widgets_at_partial_opacity():
    shell = TestShell()
    h = UiHarness(shell)
    shell.stack.push(SolidScreen((0, 0, 0)))
    menu = ColumnMenu(shell, by=InputKind.MOUSE)
    shell.stack.push(menu)
    inside = (menu.box(0).x + 6, menu.center(0)[1])
    values = []
    for _ in range(11):
        h.frame()
        values.append(h.px(*inside)[0])
    assert values[0] == 0 and values[-1] == round(0xFF * 0.9)
    assert values == sorted(values)


# --- Cursor (PR-F10-13, I-13) ---------------------------------------------------------------------

def test_cursor_hides_on_keys_and_shows_on_motion_and_exit():
    shell, h, menu = open_menu()
    h.frame(H.key(pygame.K_DOWN))
    h.frame(H.key(pygame.K_DOWN))
    h.frame(H.motion((900, 600)))
    h.frame(H.key(pygame.K_UP))
    assert shell.cursor_calls == [False, True, False]
    h.frame(H.key(pygame.K_ESCAPE))
    assert shell.stack.top is None and shell.cursor_calls[-1] is True


def test_replacing_the_stack_shows_the_cursor():
    shell, h, menu = open_menu()
    h.frame(H.key(pygame.K_DOWN))
    shell.stack.replace_all([SolidScreen()])
    assert shell.cursor_calls == [False, True]


def test_drawing_before_build_is_an_error():
    shell, h, menu = open_menu()
    menu.built = False
    with pytest.raises(AssertionError):
        h.frame()
