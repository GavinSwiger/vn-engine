"""F11 step 7 — ``GameShell.capture_scene`` and the kept thumbnail (C3, ``04`` §7.3), and I-10's
notice forwarding (``GameShell.forward_notices``, ``app/menus.forward_launch_notices``).

Unit form on F10's game rig (``tests/ui/test_game_menu.py``: a real ``GameShell`` from
``install_ui`` over a fake App, the game on F05's ``TextboxScreen``). Frames run in ``App``'s
order with the layer calls (events, ``update``, ``update_layer``, draw, ``draw_layer``). The
scene probe is the textbox band (1000, 600), #CCC3C6 over black, which is (250, 150) in a
320×180 thumbnail at 1280×720. AC-F11-16 itself (App S, real saves) is proved at step 9 in
``tests/app/test_thumbnail_capture.py``; these are its shell rows.
"""

import pygame
import pytest

from engine.app import menus as app_menus
from engine.app.menus import forward_launch_notices
from engine.render.thumbnail import THUMB_SIZE, encode_jpeg
from engine.runtime.commands import StoryEnded
from engine.ui import shell as shell_module
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.nav import InputKind
from engine.ui.shell import Mode
from tests.fakes.ui_shell import DT, UiHarness
from tests.ui.test_game_menu import BAND, DIM, FADE, GREY, game
from tests.ui.test_title import Rig, close, over

H = UiHarness
THUMB_BAND = (250, 150)               # BAND in a 320×180 thumbnail


def frame(g, *events) -> None:
    """One frame as ``App`` runs it, with the shell's layer calls."""
    shell, h = g.shell, g.h
    for event in events:
        shell.stack.handle_event(event)
    shell.assets.time.advance(DT if shell.assets.time.frame else None)
    shell.stack.update(DT)
    shell.update_layer(DT, focused=True)
    h.framebuffer.fill((0, 0, 0))
    h.canvas.bind(h.framebuffer, h.viewport, h.quality)
    shell.stack.draw(h.canvas)
    shell.draw_layer(h.canvas)


def frames(g, n: int) -> None:
    for _ in range(n):
        frame(g)


def probe(picture: pygame.Surface) -> tuple[int, int, int]:
    return tuple(picture.get_at(THUMB_BAND))[:3]


class Shrinks:
    """Counts ``make_thumbnail`` calls made by the shell (the Cost spy's smoothscale)."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, scene):
        self.calls += 1
        return self.real(scene)

    real = staticmethod(shell_module.make_thumbnail)


def open_menu(g) -> GameMenuScreen:
    frame(g, H.key(pygame.K_ESCAPE))
    frames(g, FADE + 1)
    menu = g.shell.game_menu()
    assert menu is not None
    return menu


# --- In game: the frame as drawn, once per frame ---------------------------------------------

def test_in_game_requests_wait_for_draw_layer_and_share_one_shrink(tmp_path):
    g = game(tmp_path)
    got: list = []
    shrinks = Shrinks()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(shell_module, "make_thumbnail", shrinks)
        for _ in range(3):
            g.shell.capture_scene(got.append)
        assert got == []                                   # served after this frame's draw
        frame(g)
    assert shrinks.calls == 1 and len(got) == 3
    assert got[0] is got[1] is got[2]
    assert got[0].get_size() == THUMB_SIZE
    assert close(probe(got[0]), GREY, tol=8)
    assert encode_jpeg(got[0]) is not None
    frame(g)
    assert len(got) == 3                                   # served once


def test_notices_are_never_in_the_thumbnail(tmp_path):
    g = game(tmp_path)
    plain: list = []
    g.shell.capture_scene(plain.append)
    frame(g)
    g.shell.notify("Quick saved.")
    frames(g, 15)                                          # faded in (200 ms)
    assert g.h.px(1250, 53) != (0, 0, 0)                   # the notice is drawn
    with_notice: list = []
    g.shell.capture_scene(with_notice.append)
    frame(g)
    # Where the notice is (the textbox's own indicator may change between the two frames).
    area = (240, 0, 80, 40)
    assert pygame.image.tobytes(with_notice[0].subsurface(area), "RGB") == \
        pygame.image.tobytes(plain[0].subsurface(area), "RGB")


# --- Under a menu: the kept thumbnail --------------------------------------------------------

def test_the_game_menu_keeps_the_undimmed_scene_once_per_open(tmp_path):
    g = game(tmp_path)
    shrinks = Shrinks()
    got: list = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(shell_module, "make_thumbnail", shrinks)
        open_menu(g)
        frames(g, 30)
        assert shrinks.calls == 1                          # at the open's capture only
        kept = g.shell.kept_thumbnail
        assert kept is not None and kept.get_size() == THUMB_SIZE
        assert close(probe(kept), GREY, tol=8)             # not the dimmed scene
        assert not close(probe(kept), over(DIM, 0.55, GREY), tol=8)
        for _ in range(3):
            g.shell.capture_scene(got.append)
        assert got == [kept, kept, kept]                   # at once, no new shrink
        assert shrinks.calls == 1
    assert encode_jpeg(kept) is not None


def test_a_confirm_over_the_game_menu_keeps_the_game_menus(tmp_path):
    g = game(tmp_path)
    open_menu(g)
    kept = g.shell.kept_thumbnail
    g.shell.ask_main_menu(InputKind.KEYS)
    frames(g, FADE + 1)
    assert isinstance(g.top, ConfirmScreen) and g.top.backdrop.captures == 1
    assert g.shell.kept_thumbnail is kept
    got: list = []
    g.shell.capture_scene(got.append)
    assert got == [kept]


def test_the_quit_question_over_the_game_is_saved_through_yes(tmp_path):
    g = game(tmp_path)
    got: list = []
    g.app.add_quit_guard(lambda: g.shell.capture_scene(got.append) or True)
    g.app.request_quit()                                   # the question, over the game
    confirm = g.top
    assert isinstance(confirm, ConfirmScreen)
    frames(g, FADE + 1)
    kept = g.shell.kept_thumbnail
    assert kept is not None and close(probe(kept), GREY, tol=8)
    frame(g, H.key(pygame.K_LEFT))
    frame(g, H.key(pygame.K_RETURN))                       # Yes: the question goes first
    assert g.app.quits == 1 and confirm not in g.stack
    assert got == [kept]                                   # no dim, no dialog


def test_the_kept_thumbnail_goes_with_the_last_menu(tmp_path):
    g = game(tmp_path)
    open_menu(g)
    assert g.shell.kept_thumbnail is not None
    frame(g, H.key(pygame.K_ESCAPE))
    frames(g, FADE + 2)
    assert g.shell.game_menu() is None and g.shell.kept_thumbnail is None
    got: list = []
    g.shell.capture_scene(got.append)
    assert got == []
    frame(g)
    assert len(got) == 1 and close(probe(got[0]), GREY, tol=8)


def test_a_menu_opened_after_the_request_serves_the_kept_thumbnail(tmp_path):
    g = game(tmp_path)
    g.shell.reduce_motion = True                           # the menu is dimmed at once
    got: list = []
    g.shell.capture_scene(got.append)
    frame(g, H.key(pygame.K_ESCAPE))
    assert g.shell.game_menu() is not None
    assert len(got) == 1 and got[0] is g.shell.kept_thumbnail
    assert close(probe(got[0]), GREY, tol=8)
    assert not close(g.h.px(*BAND), GREY, tol=8)           # the frame itself is dimmed


def test_a_resize_under_the_menu_recaptures_the_kept_thumbnail(tmp_path):
    g = game(tmp_path)
    menu = open_menu(g)
    first = g.shell.kept_thumbnail
    g.h.resize((1920, 1080))
    frames(g, 3)
    assert menu.backdrop.captures == 2
    kept = g.shell.kept_thumbnail
    assert kept is not None and kept is not first and kept.get_size() == THUMB_SIZE
    assert close(probe(kept), GREY, tol=8)


def test_the_title_drops_the_kept_thumbnail(tmp_path):
    g = game(tmp_path)
    open_menu(g)
    g.shell.return_to_title()
    assert g.shell.mode is Mode.ENDING
    got: list = []
    g.shell.capture_scene(got.append)
    assert got == [None]                                   # during the fade: none
    frames(g, FADE + 2)
    assert g.shell.mode is Mode.TITLE and g.shell.kept_thumbnail is None


# --- No picture: the title and the fades -----------------------------------------------------

def test_title_and_story_end_give_no_picture(tmp_path):
    rig = Rig(tmp_path)
    got: list = []
    rig.shell.capture_scene(got.append)
    assert got == [None]
    g = game(tmp_path / "b")
    g.shell.story_ended(StoryEnded())
    g.shell.capture_scene(got.append)
    assert got == [None, None]


def test_a_request_pending_into_the_title_gets_none(tmp_path):
    g = game(tmp_path)
    g.shell.reduce_motion = True                           # the title cuts in at once
    got: list = []
    g.shell.capture_scene(got.append)
    g.shell.return_to_title()
    frame(g)
    assert g.shell.mode is Mode.TITLE and got == [None]


# --- I-10: forwarding a service's take_notices() ---------------------------------------------

class NoticeSource:
    def __init__(self, items) -> None:
        self.items = list(items)
        self.takes = 0

    def take_notices(self) -> list:
        self.takes += 1
        items, self.items = self.items, []
        return items


def test_forward_notices_drains_into_one_notice(tmp_path):
    g = game(tmp_path)
    source = NoticeSource(["W70 a", "W70 b"])
    assert g.shell.forward_notices(source.take_notices, "notice_cant_save")
    assert g.shell.notices.waiting() + tuple(v.text for v in g.shell.notices.views()) == (
        "Can't save right now.",)
    assert not g.shell.forward_notices(source.take_notices, "notice_cant_save")   # drained
    frames(g, 15)
    view = g.shell.notices.views()[0]
    assert view.kind == "problem"


def test_forward_notices_waits_for_its_word(tmp_path):
    g = game(tmp_path)
    source = NoticeSource(["W70"])
    assert not g.shell.forward_notices(source.take_notices, "notice_not_a_word_yet")
    assert source.takes == 0 and source.items == ["W70"]   # left for a later call


def test_install_ui_forwards_the_built_services(tmp_path):
    g = game(tmp_path)
    assert not hasattr(g.app, "settings")                  # F16 not built: nothing to do
    g.app.settings = NoticeSource(["W70"])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(app_menus, "NOTICE_SOURCES", (("settings", "notice_not_a_word_yet"),))
        forward_launch_notices(g.app, g.shell)             # its word isn't there yet
    assert g.app.settings.items == ["W70"]
    forward_launch_notices(g.app, g.shell)                 # F16 step 4: the word exists
    assert g.app.settings.items == []
    assert "Your settings couldn't be read, so the defaults are used." in (
        g.shell.notices.waiting() + tuple(v.text for v in g.shell.notices.views()))
