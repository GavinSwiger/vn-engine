"""App: the frame loop with a FakeWindow and a scripted limiter (04-technical §14.3).

Steps 6–7 parts: AC-F01-21 (title at the next flip), 38 (re-bind after a resize, FAST then
FINAL), 57 (100 toggles + 100 resizes), 58 (QUIT quits cleanly, window destroyed), 156
(empty framebuffer), the fullscreen hotkeys, minimized waiting, and game-time continuity.
Step 8 parts: AC-F01-41 (mouse positions), 50 (hotkeys, also on the error screen), 60 (Esc
is not the App's), 61 (quit guards), 80 (error screen keys), 88 (minimized), 89 (unfocused),
91 (story seam order), 92 (unhandled command → error screen), 94 (gamepad events), 96
(game time). Step 9 parts: AC-F01-90 (F3 overlay) and the App part of AC-F01-158.
"""

import dataclasses
import logging
import re
import time

import pygame
import pytest

from engine.app.app import MSG_EMPTY_FRAMEBUFFER
from engine.core.config_schema import Config, WindowConfig
from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.render.canvas import RenderQuality
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import LETTERBOX, make_app
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

PRODUCT_SIZES = [(1280, 720), (1920, 1080), (1920, 1200), (2560, 1080), (1024, 768), (640, 360)]


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def record_viewports(app, window: FakeWindow) -> list:
    seen = []
    window.on_flip = lambda w: seen.append((w.size, app.viewport, app.canvas.quality))
    return seen


# --- AC-F01-58: QUIT quits cleanly -------------------------------------------------------------

def test_quit_returns_zero_and_destroys_the_window_quickly():
    window = FakeWindow()
    app, limiter = make_app(window)
    started = {}

    def post_quit_now():
        started["t0"] = time.perf_counter()
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    destroyed = {}
    real_destroy = window.destroy

    def destroy():
        destroyed["t"] = time.perf_counter()
        real_destroy()

    window.destroy = destroy
    limiter.at(5, post_quit_now)
    assert app.run() == 0
    assert window.destroyed
    assert destroyed["t"] - started["t0"] < 1.0
    assert len(window.flips) == 5                    # the frame with the QUIT still presents


# --- AC-F01-21: title changes apply before the next flip --------------------------------------

def test_set_title_is_visible_at_the_next_flip():
    window = FakeWindow()
    app, limiter = make_app(window)
    limiter.at(3, lambda: app.set_title("Новое имя 🙂")).quit_at(4)
    app.run()
    assert window.flips[2].title == "Новое имя 🙂"
    assert window.title == "Новое имя 🙂"


# --- first frame, bars, and the canvas ----------------------------------------------------------

def test_bars_get_the_letterbox_color_and_the_canvas_is_cleared():
    window = FakeWindow((1920, 1200), probe_points=[(960, 30), (960, 59), (960, 1140),
                                                    (960, 1199), (960, 60), (0, 60),
                                                    (1919, 1139)])
    app, limiter = make_app(window)
    limiter.quit_at(1)
    app.run()
    probes = window.flips[0].probes
    for point in [(960, 30), (960, 59), (960, 1140), (960, 1199)]:
        assert probes[point] == LETTERBOX
    for point in [(960, 60), (0, 60), (1919, 1139)]:
        assert probes[point] == (0, 0, 0)
    assert app.canvas.quality is RenderQuality.FINAL


# --- AC-F01-38: the next frame after a resize uses the new layout ----------------------------------

def test_resize_rebinds_on_the_next_frame_fast_then_final():
    window = FakeWindow((1280, 720), probe_points=[(960, 30)])
    app, limiter = make_app(window, fps=64)        # 0.2 s never falls exactly on a frame
    seen = record_viewports(app, window)
    limiter.at(4, lambda: window.resize(1920, 1200))
    limiter.quit_at(40)
    app.run()
    assert seen[2][1] == Viewport.compute(CANVAS_SIZE, (1280, 720))
    size, viewport, quality = seen[3]
    assert size == (1920, 1200)
    assert (viewport.x, viewport.y, viewport.w, viewport.h) == (0, 60, 1920, 1080)
    assert window.flips[3].probes[(960, 30)] == LETTERBOX
    for frame_size, frame_viewport, _ in seen:
        assert frame_viewport == Viewport.compute(CANVAS_SIZE, frame_size)
    # Frames are 1/64 s apart: frames 4..16 are < 0.2 s after the change, 17 on are not.
    for index, (_, _, frame_quality) in enumerate(seen, start=1):
        elapsed = (index - 4) / 64
        if index < 4:
            assert frame_quality is RenderQuality.FINAL
        elif elapsed < 0.2:
            assert frame_quality is RenderQuality.FAST, index
        else:
            assert frame_quality is RenderQuality.FINAL, index


def test_quality_stays_fast_while_sizes_keep_changing():
    window = FakeWindow((1280, 720))
    app, limiter = make_app(window, fps=64)
    seen = record_viewports(app, window)
    sizes = PRODUCT_SIZES * 4
    for step in range(20):                               # about every 50 ms (3 frames), 1 s
        limiter.at(3 + 3 * step, lambda s=sizes[step + 1]: window.resize(*s))
    last_change = 3 + 3 * 19
    limiter.quit_at(last_change + 20)
    app.run()
    for index, (_, _, quality) in enumerate(seen, start=1):
        if 3 <= index < last_change + 13:              # 0.2 s = 12.8 frames
            assert quality is RenderQuality.FAST, index
        elif index >= last_change + 13:
            assert quality is RenderQuality.FINAL, index


# --- AC-F01-156: an empty framebuffer skips the frame -------------------------------------------

@pytest.mark.parametrize("empty", ["0x0", "0x720", "1280x0", "unavailable"])
def test_empty_framebuffer_skips_frames(empty, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="vn")
    window = FakeWindow((1280, 720))
    app, limiter = make_app(window)
    computes = []
    real_compute = Viewport.compute
    monkeypatch.setattr(Viewport, "compute",
                        staticmethod(lambda *a, **k: computes.append(a) or real_compute(*a, **k)))

    def make_empty():
        computes.clear()
        if empty == "unavailable":
            window.set_unavailable()
        else:
            window.resize(*(int(v) for v in empty.split("x")))

    marks = {}
    limiter.at(3, make_empty)
    limiter.at(13, lambda: marks.update(flips=len(window.flips), computes=len(computes)))
    limiter.at(13, lambda: window.resize(1280, 720))
    limiter.quit_at(13)
    assert app.run() == 0
    assert marks == {"flips": 2, "computes": 0}           # frames 3–12 skipped entirely
    assert len(window.flips) == 3
    assert app.viewport == Viewport(1280, 720, 1280, 720, 0, 0, 1280, 720)
    messages = [r.getMessage() for r in caplog.records]
    assert messages.count(MSG_EMPTY_FRAMEBUFFER) == 1
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# --- fullscreen hotkeys and AC-F01-57 -----------------------------------------------------------

@pytest.mark.parametrize("key, mod, toggles", [
    (pygame.K_F11, 0, True),
    (pygame.K_RETURN, pygame.KMOD_LALT, True),
    (pygame.K_KP_ENTER, pygame.KMOD_RALT, True),
    (pygame.K_F11, pygame.KMOD_LCTRL, False),
    (pygame.K_F11, pygame.KMOD_LSHIFT, False),
    (pygame.K_RETURN, 0, False),
    (pygame.K_f, 0, False),
    (pygame.K_ESCAPE, 0, False),
])
def test_fullscreen_hotkeys(key, mod, toggles):
    window = FakeWindow()
    app, limiter = make_app(window)
    limiter.at(2, lambda: post_key(key, mod)).at(4, lambda: post_key(key, mod)).quit_at(6)
    assert app.run() == 0
    expected = ["set_fullscreen", "set_windowed"] if toggles else []
    assert [c for c in window.calls if c.startswith("set_")] == expected


def test_ctrl_cmd_f_toggles_only_on_macos(monkeypatch):
    import sys
    for platform_name, expected in (("darwin", 1), ("win32", 0)):
        monkeypatch.setattr(sys, "platform", platform_name)
        window = FakeWindow()
        app, limiter = make_app(window)
        limiter.at(2, lambda: post_key(pygame.K_f, pygame.KMOD_LCTRL | pygame.KMOD_LMETA))
        limiter.quit_at(3)
        app.run()
        assert window.calls.count("set_fullscreen") == expected
        pygame.event.clear()


def test_100_toggles_and_100_resizes(caplog):
    caplog.set_level(logging.DEBUG, logger="vn")
    window = FakeWindow((1280, 720))
    app, limiter = make_app(window)
    seen = record_viewports(app, window)
    frame = 2
    for i in range(100):
        limiter.at(frame, lambda: post_key(pygame.K_F11))
        frame += 3
        limiter.at(frame, lambda s=PRODUCT_SIZES[i % 6]: window.resize(*s))
        frame += 3
    limiter.quit_at(frame)
    assert app.run() == 0
    assert window.calls.count("set_fullscreen") == 50
    assert window.calls.count("set_windowed") == 50
    assert len(seen) == frame
    for size, viewport, _ in seen:
        assert viewport == Viewport.compute(CANVAS_SIZE, size)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# --- minimized ----------------------------------------------------------------------------------

def test_minimized_waits_without_drawing(monkeypatch):
    window = FakeWindow()
    app, limiter = make_app(window)
    waits = []
    real_wait = pygame.event.wait

    def wait(timeout=0):
        waits.append(timeout)
        if len(waits) == 5:
            pygame.event.post(pygame.event.Event(pygame.WINDOWRESTORED))
        return real_wait(1)

    monkeypatch.setattr(pygame.event, "wait", wait)
    limiter.at(3, lambda: pygame.event.post(pygame.event.Event(pygame.WINDOWMINIMIZED)))
    limiter.quit_at(5)
    assert app.run() == 0
    assert waits[:5] == [100] * 5
    assert len(window.flips) == 4                 # frames 1, 2, 4, 5; frame 3 saw the event
    assert limiter.resets == 1


# --- game time continuity (part of AC-F01-96) -----------------------------------------------------

def test_game_time_is_continuous_across_toggles_resizes_and_stalls():
    window = FakeWindow()
    app, limiter = make_app(window)
    times = []
    window.on_flip = lambda w: times.append((app.time.now, app.time.dt))
    limiter.at(5, lambda: post_key(pygame.K_F11))
    limiter.at(8, lambda: window.resize(1024, 768))
    limiter.steps[10] = 5.0                             # a 5 s stall
    limiter.quit_at(20)
    app.run()
    nows = [now for now, _ in times]
    assert all(b > a for a, b in zip(nows, nows[1:]))
    assert max(dt for _, dt in times) <= 0.1 + 1e-9
    assert times[9][1] == pytest.approx(0.1)


def test_fps_cap_seam():
    window = FakeWindow()
    app, limiter = make_app(window)
    app.set_fps_cap(30)
    assert limiter.period == pytest.approx(1 / 30)


def test_a_broken_screen_stack_falls_back_and_exits_1(caplog):
    """A stand-in stack that raises and cannot even show the error screen: the fallback
    (log, stderr, system dialog) ends the loop with code 1."""
    window = FakeWindow()
    app, limiter = make_app(window)

    class Broken:
        def __iter__(self):
            return iter(())

        def update(self, dt):
            raise RuntimeError("boom")

        def draw(self, canvas):
            pass

    app.screens = Broken()
    limiter.quit_at(5)
    assert app.run() == 1
    assert window.destroyed
    assert any("RuntimeError: boom" in (r.exc_text or "") or r.exc_info for r in caplog.records)


def test_screens_seam_draws_on_the_bound_canvas():
    window = FakeWindow((2560, 1080), probe_points=[(320, 0), (2239, 1079), (319, 540)])
    app, limiter = make_app(window)

    class Gray:
        opaque = True

        def __iter__(self):
            return iter([self])

        def update(self, dt):
            pass

        def draw(self, canvas):
            canvas.fill((0x20, 0x20, 0x20))

    app.screens = Gray()
    limiter.quit_at(1)
    app.run()
    probes = window.flips[0].probes
    assert probes[(320, 0)] == probes[(2239, 1079)] == (0x20, 0x20, 0x20)
    assert probes[(319, 540)] == LETTERBOX


def test_integer_scale_from_config():
    config = Config(window=dataclasses.replace(WindowConfig(), integer_scale=True))
    window = FakeWindow((1920, 1080))
    app, limiter = make_app(window, config=config)
    limiter.quit_at(1)
    app.run()
    assert (app.viewport.x, app.viewport.y, app.viewport.w, app.viewport.h) == (320, 180, 1280, 720)


# --- S0 notes 1 and 2: a real window keeps its framebuffer object across a resize -----------------

def test_real_window_resize_rebinds_without_a_stale_subsurface(monkeypatch):
    """pygame-ce returns the same framebuffer Surface after a resize; the App must still
    see the change (by size) and never draw into a subsurface from before it (that
    crashes the process, S0 note 2). The window stays hidden (SpyWindow)."""
    from engine.render.window import GameWindow
    from tests.fakes.spy_window import SpyWindow

    with SpyWindow.installed(monkeypatch):
        window = GameWindow(title="resize", size=(1280, 720), resizable=True,
                            start_fullscreen=False, letterbox_color=LETTERBOX,
                            initial_size_for_restore=(1280, 720))
        app, limiter = make_app(window)
        seen = []
        real_flip = window.flip

        def flip():
            framebuffer = window.framebuffer()
            seen.append((id(framebuffer), framebuffer.get_size(), app.viewport,
                         tuple(framebuffer.get_at((960, 30)))[:3]
                         if framebuffer.get_width() > 960 else None))
            real_flip()

        window.flip = flip
        sizes = [(1920, 1200), (1024, 768), (1920, 1200)] * 10
        for index, size in enumerate(sizes):
            limiter.at(2 + 2 * index, lambda s=size: setattr(window._window, "size", s))
        limiter.quit_at(2 + 2 * len(sizes) + 1)
        assert app.run() == 0
    assert len({frame_id for frame_id, *_ in seen}) == 1        # same object throughout
    for _, size, viewport, probe in seen:
        assert viewport == Viewport.compute(CANVAS_SIZE, size)
        if size == (1920, 1200):
            assert probe == LETTERBOX


# === Step 8: screens, input, guards, story seam, error mode ======================================

from engine.app.dispatch import UnhandledCommandError  # noqa: E402
from engine.ui.builtin.error import ErrorScreen  # noqa: E402
from engine.ui.builtin.placeholder import PlaceholderScreen  # noqa: E402
from engine.ui.screen import Screen  # noqa: E402
from tests.fakes.draw_spy import spy_draw_text  # noqa: E402


class SpyScreen(Screen):
    """Records every UiEvent; optionally runs ``on_event`` for each."""

    def __init__(self, on_event=None, *, opaque: bool = True) -> None:
        self.events = []
        self.draws = 0
        self.on_event = on_event
        self.opaque = opaque

    def handle_event(self, event):
        self.events.append(event)
        if self.on_event is not None:
            self.on_event(event)
        return False

    def draw(self, canvas):
        self.draws += 1


def post(kind, **attrs):
    pygame.event.post(pygame.event.Event(kind, **attrs))


def post_quit_event():
    pygame.event.post(pygame.event.Event(pygame.QUIT))


def with_placeholder(app):
    app.screens.push(PlaceholderScreen(title="Test", engine_version="0.1.0"))


# --- AC-F01-41: mouse events carry canvas positions ----------------------------------------------

def test_mouse_events_carry_canvas_positions(monkeypatch):
    window = FakeWindow((2560, 1080))
    app, limiter = make_app(window)
    spy = SpyScreen()
    app.screens.push(spy)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (1280, 540))

    def many():
        post(pygame.MOUSEMOTION, pos=(1280, 540), rel=(0, 0), buttons=(0, 0, 0))
        post(pygame.MOUSEBUTTONUP, pos=(1280, 540), button=1)
        post(pygame.MOUSEWHEEL, x=0, y=1, flipped=False)
        post_key(pygame.K_a)

    limiter.at(2, lambda: post(pygame.MOUSEBUTTONDOWN, pos=(100, 540), button=1))
    limiter.at(3, lambda: post(pygame.MOUSEBUTTONDOWN, pos=(1280, 540), button=1))
    limiter.at(4, many)
    limiter.quit_at(5)
    app.run()
    by_type = {}
    for event in spy.events:
        by_type.setdefault(event.raw.type, []).append(event)
    down = by_type[pygame.MOUSEBUTTONDOWN]
    assert down[0].in_canvas is False
    assert down[1].canvas_pos == (640, 360) and down[1].in_canvas is True
    for kind in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP, pygame.MOUSEWHEEL):
        assert by_type[kind][0].canvas_pos == (640, 360), kind
    key_event = by_type[pygame.KEYDOWN][0]
    assert key_event.canvas_pos is None and key_event.in_canvas is False


# --- AC-F01-50: fullscreen hotkeys on a real (hidden) window, also on the error screen ------------

@pytest.mark.parametrize("error_mode", [False, True])
def test_fullscreen_hotkeys_on_a_real_window(monkeypatch, caplog, error_mode):
    from engine.render.window import GameWindow
    from tests.fakes.spy_window import SpyWindow

    caplog.set_level(logging.INFO, logger="vn")
    with SpyWindow.installed(monkeypatch):
        window = GameWindow(title="keys", size=(1280, 720), resizable=True,
                            start_fullscreen=False, letterbox_color=LETTERBOX,
                            initial_size_for_restore=(1280, 720))
        app, limiter = make_app(window)
        with_placeholder(app)
        if error_mode:
            app.show_fatal_error(RuntimeError("boom"))
        presses = [(pygame.K_F11, 0), (pygame.K_RETURN, pygame.KMOD_LALT),
                   (pygame.K_KP_ENTER, pygame.KMOD_RALT)]
        ignored = [(pygame.K_F11, pygame.KMOD_LCTRL), (pygame.K_F11, pygame.KMOD_LSHIFT),
                   (pygame.K_f, 0)]
        if not error_mode:
            ignored.append((pygame.K_RETURN, 0))           # on the error screen Enter quits
        frame = 2
        for key, mod in presses:
            for _ in range(2):
                limiter.at(frame, lambda k=key, m=mod: post_key(k, m))
                frame += 2
        for key, mod in ignored:
            limiter.at(frame, lambda k=key, m=mod: post_key(k, m))
            frame += 2
        limiter.quit_at(frame)
        app.run()
    calls = [entry[0] for entry in SpyWindow.log
             if entry[0] in ("set_fullscreen", "set_windowed")]
    assert calls == ["set_fullscreen", "set_windowed"] * 3
    assert all(entry[1] is True for entry in SpyWindow.log if entry[0] == "set_fullscreen")
    toggles = [r for r in caplog.records if r.name == "vn.window" and r.levelno == logging.INFO
               and r.getMessage().startswith("Fullscreen")]
    assert len(toggles) == 6
    assert all(re.search(r"\(\d+x\d+\)$", r.getMessage()) for r in toggles)
    if error_mode:
        assert isinstance(app.screens.top, ErrorScreen)


# --- AC-F01-60: Esc does nothing in normal play ----------------------------------------------------

def test_esc_is_left_to_the_screens(caplog):
    caplog.set_level(logging.INFO, logger="vn")
    window = FakeWindow()
    app, limiter = make_app(window)
    with_placeholder(app)
    spy = SpyScreen()
    app.screens.push(spy)

    def esc():
        post_key(pygame.K_ESCAPE)
        post(pygame.KEYUP, key=pygame.K_ESCAPE, mod=0, unicode="", scancode=0)

    for frame in (2, 5, 8):
        limiter.at(frame, esc)
    seen = {}
    limiter.at(10, lambda: seen.update(running=app.running, top=app.screens.top,
                                       calls=list(window.calls)))
    limiter.quit_at(11)
    count_before = len([r for r in caplog.records if r.levelno >= logging.INFO])
    assert app.run() == 0
    assert seen["running"] is True and seen["top"] is spy
    assert not [c for c in seen["calls"] if c in ("set_fullscreen", "set_windowed", "destroy")]
    assert len([r for r in caplog.records if r.levelno >= logging.INFO]) == count_before
    escapes = [e for e in spy.events if getattr(e.raw, "key", None) == pygame.K_ESCAPE]
    assert len(escapes) == 6


# --- AC-F01-61: quit guards ---------------------------------------------------------------------------

def test_a_vetoing_guard_keeps_the_game_running(caplog):
    caplog.set_level(logging.DEBUG, logger="vn")
    window = FakeWindow()
    app, limiter = make_app(window)
    assert app.quit_guards == ()
    calls = []

    def veto():
        calls.append(1)
        return False

    app.add_quit_guard(veto)
    limiter.at(2, post_quit_event)
    state = {}
    limiter.at(12, lambda: state.update(running=app.running))
    limiter.at(13, lambda: app.request_quit(force=True))
    assert app.run() == 0
    assert state == {"running": True}
    assert calls == [1]                                         # force skipped the guard
    assert "Quit vetoed by veto" in [r.getMessage() for r in caplog.records]


def test_allowing_and_removed_guards_let_quit_exit_0():
    window = FakeWindow()
    app, limiter = make_app(window)
    app.add_quit_guard(lambda: True)
    limiter.quit_at(2)
    assert app.run() == 0

    window = FakeWindow()
    app, limiter = make_app(window)

    def veto():
        return False

    app.add_quit_guard(veto)
    app.remove_quit_guard(veto)
    limiter.quit_at(2)
    assert app.run() == 0


def test_guards_are_bypassed_in_error_mode():
    window = FakeWindow()
    app, limiter = make_app(window)
    calls = []
    app.add_quit_guard(lambda: calls.append(1) or False)
    app.show_fatal_error(RuntimeError("boom"))
    limiter.quit_at(2)
    assert app.run() == 1
    assert calls == []


# --- AC-F01-80 (App part): error screen keys --------------------------------------------------------

@pytest.mark.parametrize("action", ["escape", "enter", "kp_enter", "quit"])
def test_error_screen_quit_keys_exit_1(action):
    window = FakeWindow()
    app, limiter = make_app(window)
    app.show_fatal_error(RuntimeError("boom"))
    keys = {"escape": pygame.K_ESCAPE, "enter": pygame.K_RETURN, "kp_enter": pygame.K_KP_ENTER}
    limiter.at(3, (lambda: post_key(keys[action])) if action != "quit" else post_quit_event)
    limiter.max_frames = 50
    assert app.run() == 1
    assert limiter.frame == 3


def test_other_keys_leave_the_error_screen_up():
    window = FakeWindow()
    app, limiter = make_app(window)
    app.show_fatal_error(RuntimeError("boom"))

    def keys():
        for key in (pygame.K_SPACE, pygame.K_a, pygame.K_F1):
            post_key(key)

    limiter.at(2, keys)
    limiter.at(4, lambda: post_key(pygame.K_F11))
    state = {}
    limiter.at(13, lambda: state.update(running=app.running, top=type(app.screens.top)))
    limiter.quit_at(14)
    assert app.run() == 1
    assert state == {"running": True, "top": ErrorScreen}
    assert window.calls.count("set_fullscreen") == 1


# --- AC-F01-76 (App part): an exception in update or draw shows the error screen ---------------------

@pytest.mark.parametrize("where", ["update", "draw"])
def test_an_exception_switches_to_the_error_screen(caplog, where):
    window = FakeWindow()
    app, limiter = make_app(window)

    class Boom(Screen):
        frames = 0

        def update(self, dt, *, is_top):
            self.frames += 1
            if where == "update" and self.frames == 3:
                raise RuntimeError("boom")

        def draw(self, canvas):
            if where == "draw" and self.frames == 3:
                raise RuntimeError("boom")

    app.screens.push(Boom())
    tops = {}
    window.on_flip = lambda w: tops.setdefault(len(w.flips), type(app.screens.top))
    limiter.quit_at(10)
    assert app.run() == 1
    assert len(app.screens) == 1 and isinstance(app.screens.top, ErrorScreen)
    assert sorted(tops) == list(range(1, 10))                # frame 3 did not flip
    assert all(tops[n] is ErrorScreen for n in range(3, 10))
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and errors[0].exc_info[0] is RuntimeError


# --- AC-F01-88 / 89: minimized and unfocused ---------------------------------------------------------

class FakeStory:
    def __init__(self) -> None:
        self.calls = []
        self.queue = []

    def post(self, event):
        self.calls.append("post")
        self.queue.append(("echo", event))

    def pump(self, max_commands=256):
        self.calls.append("pump")
        out, self.queue = self.queue, []
        return out


def test_minimized_for_one_second_draws_nothing(monkeypatch):
    window = FakeWindow()
    app, limiter = make_app(window)
    spy = SpyScreen()
    spy.in_game = True                     # the story runs under it (F10 C3)
    app.screens.push(spy)
    story = FakeStory()
    app.story = story
    presents = []
    real_present = app.present

    def present():
        presents.append(1)
        return real_present()

    monkeypatch.setattr(app, "present", present)
    waits = []
    marks = {}

    def snapshot(suffix):
        return {"presents" + suffix: len(presents), "draws" + suffix: spy.draws,
                "flips" + suffix: len(window.flips),
                "pumps" + suffix: story.calls.count("pump")}

    def wait(timeout=0):
        """A fake ``event.wait``: each call "sleeps" its timeout on a fake clock (a real
        second of waiting would only test SDL), then returns the next queued event."""
        if not waits:
            marks.update(start=0.0, **snapshot(""))
        now = sum(t if t > 0 else 1000 for t in waits) / 1000     # wait() = block "1 s"
        waits.append(timeout)
        if now - marks["start"] >= 1.0 and "waits" not in marks:
            marks.update(waits=len(waits) - 1, **snapshot("_end"))
            pygame.event.post(pygame.event.Event(pygame.WINDOWRESTORED))
        return pygame.event.poll()

    monkeypatch.setattr(pygame.event, "wait", wait)
    limiter.at(3, lambda: post(pygame.WINDOWMINIMIZED))
    after = {}
    limiter.at(4, lambda: after.update(presents=len(presents)))
    limiter.quit_at(5)
    assert app.run() == 0
    for name in ("presents", "draws", "flips", "pumps"):
        assert marks[name + "_end"] == marks[name], name
    assert 8 <= marks["waits"] <= 12
    assert set(waits) == {100}
    assert limiter.resets == 1
    assert len(presents) == after["presents"] + 2             # frames 4 and 5 present


def test_unfocused_window_keeps_drawing():
    window = FakeWindow()
    app, limiter = make_app(window)
    spy = SpyScreen()
    app.screens.push(spy)
    limiter.at(2, lambda: post(pygame.WINDOWFOCUSLOST))
    limiter.quit_at(62)
    app.run()
    assert spy.draws == 62


# --- AC-F01-91 / 92: story seam --------------------------------------------------------------------

def test_story_seam_order():
    window = FakeWindow()
    app, limiter = make_app(window)
    story = FakeStory()
    order = []

    class Recording(SpyScreen):
        in_game = True                     # the story runs under it (F10 C3)

        def update(self, dt, *, is_top):
            order.append("update")

    def on_event(event):
        order.append("event")
        story.post(event.raw.type)

    app.screens.push(Recording(on_event))
    app.story = story
    real_pump = story.pump

    def pump(max_commands=256):
        order.append("pump")
        return real_pump(max_commands)

    story.pump = pump
    app.router.register(tuple, lambda c: order.append(("dispatch", c[1])))
    for frame in range(1, 5):
        limiter.at(frame, lambda n=frame: order.append(("frame", n)))
    limiter.at(3, lambda: post_key(pygame.K_a))
    limiter.quit_at(4)
    app.run()
    frames = {}
    current = None
    for item in order:
        if isinstance(item, tuple) and item[0] == "frame":
            current = frames.setdefault(item[1], [])
        else:
            current.append(item)
    assert frames[1] == frames[2] == ["pump", "update"]
    assert frames[3] == ["event", "pump", ("dispatch", pygame.KEYDOWN), "update"]
    assert frames[4] == ["pump", "update"]                    # the QUIT frame still runs


def test_the_story_is_pumped_only_while_the_top_screen_is_in_game():
    """F10 C3 (AC-F10-30's App part): no pump under a menu; the empty stack pumps."""
    window = FakeWindow()
    app, limiter = make_app(window)
    story = FakeStory()
    app.story = story
    game = SpyScreen()
    game.in_game = True
    menu = SpyScreen()
    pumps = {}

    def mark(frame):
        pumps[frame] = story.calls.count("pump")

    limiter.at(2, lambda: app.screens.push(game))
    limiter.at(4, lambda: app.screens.push(menu))
    limiter.at(7, lambda: app.screens.pop())
    limiter.at(9, lambda: app.screens.replace_all([SpyScreen()]))
    for frame in range(1, 12):
        limiter.at(frame, lambda n=frame: mark(n))
    limiter.quit_at(11)
    app.run()
    per_frame = {n: pumps[n + 1] - pumps[n] for n in range(1, 11)}
    # Frame 1: empty stack pumps. 2–3: in-game top. 4–6: menu top. 7–8: in-game again.
    # 9–10: a non-in-game screen alone (as after the story ends).
    assert per_frame == {1: 1, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0, 7: 1, 8: 1, 9: 0, 10: 0}


def test_commands_are_dispatched_in_order():
    window = FakeWindow()
    app, limiter = make_app(window)
    story = FakeStory()
    story.queue = [("a", 1), ("b", 2), ("c", 3)]
    app.story = story
    seen = []
    app.router.register(tuple, lambda c: seen.append(c[0]))
    limiter.quit_at(2)
    app.run()
    assert seen == ["a", "b", "c"]


def test_an_unhandled_command_shows_the_error_screen(caplog):
    window = FakeWindow()
    app, limiter = make_app(window)
    story = FakeStory()

    class Unknown:
        pass

    story.queue = [Unknown()]
    app.story = story
    limiter.quit_at(3)
    assert app.run() == 1
    assert isinstance(app.screens.top, ErrorScreen)
    assert "UnhandledCommandError" in app.screens.top.message
    assert app.story is None                                  # not pumped in error mode
    assert story.calls.count("pump") == 1
    assert any(r.exc_info and r.exc_info[0] is UnhandledCommandError for r in caplog.records)


# --- AC-F01-94: gamepad hot-plug ------------------------------------------------------------------

GAMEPAD_EVENTS = [
    (pygame.JOYDEVICEADDED, {"device_index": 0}),
    (pygame.JOYDEVICEREMOVED, {"instance_id": 0}),
    (pygame.CONTROLLERDEVICEADDED, {"device_index": 0}),
    (pygame.CONTROLLERDEVICEREMOVED, {"instance_id": 0}),
]


@pytest.mark.parametrize("error_mode", [False, True])
def test_gamepad_events_reach_the_top_screen(caplog, error_mode):
    caplog.set_level(logging.DEBUG, logger="vn")
    window = FakeWindow()
    app, limiter = make_app(window)
    spy = SpyScreen()
    app.screens.push(spy)
    received = spy.events
    if error_mode:
        app.show_fatal_error(RuntimeError("boom"))
        received = []
        top = app.screens.top
        real = top.handle_event
        top.handle_event = lambda e: received.append(e) or real(e)

    def plug():
        for kind, attrs in GAMEPAD_EVENTS:
            post(kind, **attrs)

    for repeat in range(10):
        limiter.at(2 + repeat, plug)
    limiter.quit_at(14)
    warnings_before = len([r for r in caplog.records if r.levelno >= logging.WARNING])
    app.run()
    kinds = dict(GAMEPAD_EVENTS)
    pad = [e for e in received if e.raw.type in kinds]
    assert len(pad) == 40
    assert all(e.canvas_pos is None for e in pad)
    assert app.error_mode is error_mode
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING]) == warnings_before


# --- AC-F01-96: resizing and toggling do not disturb game time -------------------------------------

def test_game_time_with_resizes_toggles_maximize_and_a_stall():
    window = FakeWindow()
    app, limiter = make_app(window)

    class Timer(Screen):
        def __init__(self):
            self.elapsed = 0.0
            self.started_at = None
            self.finished_at = None

        def update(self, dt, *, is_top):
            if self.started_at is None:
                self.started_at = app.time.now
            self.elapsed += dt
            if self.finished_at is None and self.elapsed >= 1.0:
                self.finished_at = app.time.now

    timer = Timer()
    app.screens.push(timer)
    nows = []
    window.on_flip = lambda w: nows.append((app.time.now, app.time.dt))
    for i in range(10):
        limiter.at(5 + 6 * i, lambda i=i: window.resize(*PRODUCT_SIZES[i % len(PRODUCT_SIZES)]))
    for frame in (12, 24, 36, 48):
        limiter.at(frame, lambda: post_key(pygame.K_F11))
    limiter.at(30, lambda: post(pygame.WINDOWMAXIMIZED))
    limiter.at(31, lambda: post(pygame.WINDOWRESTORED))
    limiter.steps[40] = 2.0                                  # a window drag stalls 2 s
    limiter.quit_at(180)
    app.run()
    values = [now for now, _ in nows]
    assert values[0] == 0.0
    assert all(b > a for a, b in zip(values, values[1:]))
    assert max(dt for _, dt in nows) <= 0.1 + 1e-9
    assert timer.finished_at - timer.started_at == pytest.approx(1.0, abs=0.1)


# === Step 9: overlay and bench ====================================================================

def _overlay_frames(monkeypatch, *, dev: bool, presses) -> dict[int, list]:
    window = FakeWindow()
    app, limiter = make_app(window)
    app.dev = dev
    with_placeholder(app)
    for frame, mod in presses:
        limiter.at(frame, lambda m=mod: post_key(pygame.K_F3, m))
    per_frame: dict[int, list] = {}
    with spy_draw_text(monkeypatch) as calls:
        def on_flip(w):
            per_frame[len(w.flips)] = [c for c in calls if c.pos == (8, 8)]
            calls.clear()

        window.on_flip = on_flip
        limiter.quit_at(8)
        app.run()
    return per_frame


def test_f3_overlay_in_dev_runs_only(monkeypatch):
    dev = _overlay_frames(monkeypatch, dev=True, presses=[(2, 0), (4, pygame.KMOD_LSHIFT),
                                                          (6, 0)])
    assert dev[1] == []
    for frame in (2, 3, 4, 5):
        (call,) = dev[frame]
        assert call.font.size == 20
        assert re.fullmatch(r"\d+ FPS \| \d+\.\d ms", call.text)
    assert dev[6] == dev[7] == []
    release = _overlay_frames(monkeypatch, dev=False, presses=[(2, 0)])
    assert all(found == [] for found in release.values())


def test_bench_work_excludes_the_limiter_wait():
    window = FakeWindow()
    app, limiter = make_app(window)
    app.bench_seconds = 1.0
    limiter.period = 0.015                                   # the limiter "waits" 15 ms

    def work(_window):
        limiter.clock.now += 0.001                           # each frame works 1 ms

    window.on_flip = work
    limiter.max_frames = 1000
    assert app.run() == 0
    result = app.bench.result()
    assert result.frames > 0
    assert all(v == pytest.approx(1.0, abs=0.01) for v in result.work_ms)
    assert result.interval_ms[0] == pytest.approx(16.0, abs=0.01)
