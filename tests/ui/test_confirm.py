"""``ConfirmScreen`` with the test shell (F10 ``03`` "Confirm dialog", UI-F10-11, ``04``
§7.9): layout at the probes of ``06`` §0.4, default No, Left/Right without wrap, Back = No,
callbacks after removal, clicks outside the panel, one dialog at a time, and the message fit.
AC-F10-55 and 56 (the Main Menu and Quit flows) wait for the shell (steps 6, 7).

Related checks share one test, each on a fresh dialog: every ``tests/ui`` test pays for
``pygame.init()``/``quit()`` (test-review-F10.md)."""

import pygame
import pytest

from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.focus import Box
from engine.ui.nav import InputKind
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import SolidScreen, TestShell, UiHarness

pytestmark = pytest.mark.display

H = UiHarness
TWO_LINES = "Return to the title screen? Unsaved progress will be lost."


def open_confirm(message=TWO_LINES, *, by=InputKind.KEYS, fade=False, shell=None):
    shell = shell or TestShell()
    h = UiHarness(shell)
    shell.stack.push(SolidScreen())
    answers = []
    confirm = ConfirmScreen(shell, message, lambda: answers.append(("yes", shell.stack.top)),
                            lambda: answers.append(("no", shell.stack.top)), by=by, fade=fade)
    shell.stack.push(confirm)
    h.frame()
    return shell, h, confirm, answers


def test_layout_matches_the_probes_and_lines_are_drawn_centred(monkeypatch):
    shell, h, confirm, _ = open_confirm()
    assert len(confirm.fit.lines) == 2 and confirm.fit.size == 28
    assert confirm.layout.panel == Box(320, 237, 640, 246)
    assert confirm.yes_button.box == Box(424, 387, 200, 56)
    assert confirm.no_button.box == Box(656, 387, 200, 56)
    with spy_draw_text(monkeypatch) as calls:
        h.frame()
    lines = [c for c in calls if c.text in confirm.fit.lines]
    assert [c.text for c in lines] == list(confirm.fit.lines)
    assert [c.pos for c in lines] == [(640, 277), (640, 316)]
    assert {c.text for c in calls} >= {"Yes", "No"}


def test_default_is_no_left_right_do_not_wrap_and_yes_runs_after_removal():
    shell, h, confirm, _ = open_confirm()
    assert confirm.scope.focused is confirm.no_button
    h.frame(H.key(pygame.K_RIGHT))
    assert confirm.scope.focused is confirm.no_button
    h.frame(H.key(pygame.K_LEFT))
    assert confirm.scope.focused is confirm.yes_button
    h.frame(H.key(pygame.K_LEFT))
    h.frame(H.key(pygame.K_UP))
    assert confirm.scope.focused is confirm.yes_button
    shell, h, confirm, answers = open_confirm()
    h.frame(H.key(pygame.K_LEFT))
    h.frame(H.key(pygame.K_RETURN))
    assert answers == [("yes", shell.stack.top)] and not isinstance(shell.stack.top,
                                                                     ConfirmScreen)


def test_back_and_enter_mean_no_start_and_clicks_outside_do_nothing_click_yes():
    for event in (H.key(pygame.K_ESCAPE), H.pad(pygame.CONTROLLER_BUTTON_B),
                  H.down((100, 100), 3), H.key(pygame.K_RETURN)):
        shell, h, confirm, answers = open_confirm()
        h.frame(event)
        assert [a[0] for a in answers] == ["no"], event
    shell, h, confirm, answers = open_confirm(by=InputKind.MOUSE)
    h.click((100, 100))
    h.click((330, 250))                           # inside the panel, on no button
    h.frame(H.pad(pygame.CONTROLLER_BUTTON_START))
    assert answers == [] and shell.stack.top is confirm
    h.click(confirm.yes_button.box.center)
    assert [a[0] for a in answers] == ["yes"]


def test_yes_waits_for_the_closing_fade_and_one_confirm_at_a_time():
    shell, h, confirm, answers = open_confirm(fade=True)
    h.frames(10)
    h.frame(H.key(pygame.K_LEFT), H.key(pygame.K_RETURN))
    assert answers == []
    h.frames(10)
    assert [a[0] for a in answers] == ["yes"]
    shell, h, confirm, _ = open_confirm()
    with pytest.raises(AssertionError):
        shell.stack.push(ConfirmScreen(shell, "Again?", lambda: None, by=InputKind.KEYS))


def test_long_messages_step_down_then_cut_and_labels_come_from_words():
    shell = TestShell()
    _, _, confirm, _ = open_confirm("word " * 400, shell=shell)
    assert confirm.fit.truncated and confirm.fit.size == 24
    assert len(confirm.fit.lines) == 6 and confirm.fit.lines[-1].endswith("…")
    assert confirm.layout.panel.bottom <= 720 and confirm.layout.panel.y >= 0
    shell = TestShell()
    shell.words = type(shell.words)(type(shell.config.words)(yes="Leave", no="Stay"))
    _, _, confirm, _ = open_confirm(shell=shell)
    assert confirm.yes_button.label() == "Leave" and confirm.no_button.label() == "Stay"
