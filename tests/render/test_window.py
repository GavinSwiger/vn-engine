"""GameWindow: hidden-first creation, title, minimum size, fullscreen and restore, pixels.

AC-F01-19 (title, unit part), 21 (title setter), 27, 28 (resizable flag and minimum size),
29 (creation order and first-frame color), 42 (points → pixels), 51 (restore size,
position, maximized), 54 (creation order and restore when started fullscreen).

``pygame.Window`` is replaced by ``SpyWindow``, which records the calls and forwards them to
a real window, except ``show``, ``set_fullscreen``, ``set_windowed``, and ``maximize``: the
dummy driver has no real fullscreen, and on a real display the test window stays hidden and
never takes over the screen (04-technical §14.2).
"""

import pygame
import pytest

from engine.render.window import GameWindow, WindowPort, sanitize_title
from tests.fakes.fake_window import FakeWindow
from tests.fakes.spy_window import SpyWindow

pytestmark = pytest.mark.display

LETTERBOX = (0x12, 0x34, 0x56)


@pytest.fixture(autouse=True)
def spy_window(monkeypatch):
    with SpyWindow.installed(monkeypatch):
        yield SpyWindow


def make_window(**overrides) -> GameWindow:
    options = dict(title="Paper Lanterns", size=(1100, 700), resizable=True,
                   start_fullscreen=False, letterbox_color=LETTERBOX,
                   initial_size_for_restore=(1100, 700))
    options.update(overrides)
    return GameWindow(**options)


def calls(*names: str) -> list[tuple]:
    return [entry for entry in SpyWindow.log if entry[0] in names]


# --- AC-F01-29 / 54: creation order and the first frame ---------------------------------------

def test_created_hidden_then_filled_flipped_and_shown():
    window = make_window()
    names = [entry[0] for entry in SpyWindow.log if not entry[0].startswith("set ")]
    assert names == ["create", "flip", "show"]
    created = SpyWindow.log[0][1]
    assert created["hidden"] is True and created["allow_high_dpi"] is True
    assert created["position"] == pygame.WINDOWPOS_CENTERED
    assert calls("flip")[0][1] == LETTERBOX                  # filled before the first flip
    window.destroy()


def test_started_fullscreen_goes_fullscreen_before_the_first_frame():
    window = make_window(start_fullscreen=True)
    names = [entry[0] for entry in SpyWindow.log if not entry[0].startswith("set ")]
    assert names == ["create", "set_fullscreen", "flip", "show"]
    assert calls("set_fullscreen")[0][1] is True              # desktop=True
    assert calls("flip")[0][1] == LETTERBOX
    assert window.fullscreen is True
    window.destroy()


# --- AC-F01-27 / 28: resizable and minimum size -----------------------------------------------

@pytest.mark.parametrize("resizable", [True, False])
def test_resizable_flag_and_minimum_size(resizable):
    window = make_window(resizable=resizable)
    assert SpyWindow.log[0][1]["resizable"] is resizable
    assert SpyWindow.instances[0]._real.resizable is resizable
    assert tuple(SpyWindow.instances[0]._real.minimum_size) == (640, 360)
    window.destroy()


# --- AC-F01-19 / 21: titles -------------------------------------------------------------------

@pytest.mark.parametrize("title", ["Paper Lanterns", "📖 مرحبا 文芸部", "Новое имя 🙂",
                                   ("Long title " * 46)[:500]])
def test_title_is_applied_exactly(title):
    window = make_window(title=title)
    assert window.title == title
    window.title = "x"
    window.title = title
    assert window.title == title
    window.destroy()


def test_control_characters_in_titles_are_replaced():
    assert sanitize_title("a\x00b\nc\x7fd\te") == "a�b�c�d�e"
    window = make_window(title="Paper\x00Lanterns")
    assert window.title == "Paper�Lanterns"
    window.destroy()


# --- AC-F01-42: window points → framebuffer pixels ---------------------------------------------

class _StubWindow:
    def __init__(self, size, framebuffer_size):
        self.size = size
        self._surface = pygame.Surface(framebuffer_size)

    def get_surface(self):
        return self._surface


def test_points_to_pixels_scales_by_the_framebuffer_ratio():
    window = make_window()
    object.__setattr__(window, "_window", _StubWindow((1280, 720), (2560, 1440)))
    assert window.points_to_pixels((100.5, 50)) == (201.0, 100.0)
    object.__setattr__(window, "_window", _StubWindow((1280, 720), (1280, 720)))
    assert window.points_to_pixels((100.5, 50)) == (100.5, 50)


# --- AC-F01-51 / 54: fullscreen toggles and restore --------------------------------------------

def test_leaving_fullscreen_restores_size_and_position(caplog):
    window = make_window()
    window._window.size = (1100, 700)
    window._window.position = (200, 150)
    SpyWindow.log.clear()
    caplog.set_level("INFO", logger="vn")
    window.toggle_fullscreen()
    window.toggle_fullscreen()
    assert [entry[0] for entry in calls("set_fullscreen", "set_windowed", "maximize")] == \
        ["set_fullscreen", "set_windowed"]
    assert calls("set size") == [("set size", (1100, 700))]
    assert calls("set position") == [("set position", (200, 150))]
    assert window.size == (1100, 700) and window.position == (200, 150)
    window_lines = [r.getMessage() for r in caplog.records if r.name == "vn.window"]
    assert window_lines == ["Fullscreen on (1100x700)", "Fullscreen off (1100x700)"]
    window.destroy()


def test_a_maximized_window_is_maximized_again():
    window = make_window()
    window.note_window_event(pygame.WINDOWMAXIMIZED)
    SpyWindow.log.clear()
    window.toggle_fullscreen()
    window.toggle_fullscreen()
    names = [entry[0] for entry in SpyWindow.log if entry[0] in
             ("set_fullscreen", "set_windowed", "maximize", "set size", "set position")]
    assert names == ["set_fullscreen", "set_windowed", "maximize"]
    window.destroy()


def test_restored_window_is_not_maximized():
    window = make_window()
    window.note_window_event(pygame.WINDOWMAXIMIZED)
    window.note_window_event(pygame.WINDOWRESTORED)
    window.toggle_fullscreen()
    window.toggle_fullscreen()
    assert calls("maximize") == []
    window.destroy()


def test_started_fullscreen_leaves_to_the_initial_size_centered():
    window = make_window(start_fullscreen=True, size=(1164, 655),
                         initial_size_for_restore=(1164, 655))
    SpyWindow.log.clear()
    window.toggle_fullscreen()
    assert calls("set_windowed") == [("set_windowed",)]
    assert calls("set size") == [("set size", (1164, 655))]
    assert calls("set position") == [("set position", pygame.WINDOWPOS_CENTERED)]
    assert window.fullscreen is False
    window.destroy()


def test_set_fullscreen_only_acts_on_a_change():
    window = make_window()
    window.set_fullscreen(False)
    assert calls("set_windowed", "set_fullscreen") == []
    window.set_fullscreen(True)
    window.set_fullscreen(True)
    assert len(calls("set_fullscreen")) == 1
    window.destroy()


# --- framebuffer and icon ---------------------------------------------------------------------

def test_framebuffer_is_none_after_destroy_and_icon_takes_any_format():
    window = make_window()
    framebuffer = window.framebuffer()
    assert framebuffer is not None and framebuffer.get_size() == window.size
    window.set_icon(pygame.Surface((16, 16), pygame.SRCALPHA))
    window.set_icon(pygame.Surface((16, 16), depth=24))
    window.destroy()
    window.destroy()                                       # idempotent
    assert window.framebuffer() is None


def test_game_window_and_fake_window_implement_the_port():
    window = make_window()
    assert isinstance(window, WindowPort)
    assert isinstance(FakeWindow(), WindowPort)
    window.destroy()


# --- F16 AC-F16-19: windowed_size (Conflict 7; 04 §5.4; 07 G12) ---------------------------------

def _resized(window, size):
    """The player resized the window: the size changes, then SDL reports it."""
    window._window.size = size
    window.note_window_event(pygame.WINDOWSIZECHANGED)


def test_windowed_size_follows_windowed_resizes():
    window = make_window(size=(1280, 720), initial_size_for_restore=(1280, 720))
    assert window.windowed_size() == (1280, 720)
    _resized(window, (1600, 900))
    assert window.windowed_size() == (1600, 900)
    window.set_fullscreen(True)
    window.note_window_event(pygame.WINDOWSIZECHANGED)     # the fullscreen size: ignored
    assert window.windowed_size() == (1600, 900)
    window.set_fullscreen(False)
    assert window.windowed_size() == (1600, 900)
    window.destroy()


def test_windowed_size_when_started_fullscreen_is_the_restore_size():
    window = make_window(start_fullscreen=True, size=(1164, 655),
                         initial_size_for_restore=(1164, 655))
    assert window.windowed_size() == (1164, 655)
    window.destroy()


def test_windowed_size_is_none_while_maximized_and_comes_back_after():
    window = make_window(size=(1280, 720), initial_size_for_restore=(1280, 720))
    _resized(window, (1500, 800))
    _resized(window, (1920, 1050))                         # SDL: the size change first,
    window.note_window_event(pygame.WINDOWMAXIMIZED)       # then MAXIMIZED
    assert window.windowed_size() is None
    window.note_window_event(pygame.WINDOWSIZECHANGED)     # still maximized: ignored
    window.note_window_event(pygame.WINDOWRESTORED)
    window._window.size = (1500, 800)
    window.note_window_event(pygame.WINDOWSIZECHANGED)
    assert window.windowed_size() == (1500, 800)
    window.destroy()


def test_windowed_size_is_none_in_fullscreen_entered_from_maximized():
    window = make_window(size=(1280, 720), initial_size_for_restore=(1280, 720))
    window.note_window_event(pygame.WINDOWMAXIMIZED)
    window.set_fullscreen(True)
    assert window.windowed_size() is None                  # G12
    window.destroy()


def test_fake_window_windowed_size_follows_the_same_rule():
    window = FakeWindow((1280, 720))
    assert window.windowed_size() == (1280, 720)
    window.user_resize(1600, 900)
    window.set_fullscreen(True)
    assert window.windowed_size() == (1600, 900) and window.size == window.desktop
    window.set_fullscreen(False)
    window.maximize()
    assert window.windowed_size() is None
    window.restore()
    assert window.windowed_size() == (1600, 900) and window.size == (1600, 900)
    window.maximize()
    window.set_fullscreen(True)
    assert window.windowed_size() is None                  # G12
    started = FakeWindow((1920, 1080), start_fullscreen=True,
                         initial_size_for_restore=(1164, 655))
    assert started.fullscreen and started.windowed_size() == (1164, 655)
    started.set_fullscreen(False)
    assert started.size == (1164, 655)


# --- AC-F39-09: an updated preview reopens at the old window's position ----------------------

def test_ac_f39_09_window_opens_at_the_given_position_and_none_centers():
    window = make_window(position=(140, 90))
    assert SpyWindow.log[0][1]["position"] == (140, 90)
    window.destroy()
    SpyWindow.log.clear()
    window = make_window(position=None)
    assert SpyWindow.log[0][1]["position"] == pygame.WINDOWPOS_CENTERED
    window.destroy()
