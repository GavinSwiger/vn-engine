"""ErrorScreen (§7.12): AC-F01-79 (readability), 83 (copy), 153 (clipboard rules, unit and
integration parts), 154 (bounded layout cost), plus input sanitizing (SEC-F01-11, 21)."""

import logging
import time
from pathlib import Path

import pygame
import pytest

from engine.core.config_schema import Config, GameConfig, WindowConfig
from engine.core.constants import CLIPBOARD_MAX_BYTES, ERROR_MESSAGE_MAX_CHARS
from engine.core.errors import UserFacingError
from engine.ui.builtin.error import (
    CUT_NOTICE,
    DETAIL_COLOR,
    HEADING_COLOR,
    HINT_COLOR,
    HINT_COPIED,
    HINT_COPY,
    HINT_COPY_FAILED,
    MESSAGE_COLOR,
    BACKGROUND,
    ErrorScreen,
)
from engine.ui.input import UiEvent
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import LETTERBOX, make_app
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

TEXT = Path(__file__).resolve().parent.parent / "fixtures" / "F01" / "text"


def error_app(size=(1280, 720), *, title: str = "Paper Lanterns", version: str = "0.1.0",
              error: BaseException | None = None):
    config = Config(game=GameConfig(title=title, version=version),
                    window=WindowConfig(letterbox_color=LETTERBOX))
    window = FakeWindow(size)
    app, limiter = make_app(window, config=config)
    app.show_fatal_error(error if error is not None else RuntimeError("boom"))
    return app, limiter, window


def screen_of(app) -> ErrorScreen:
    screen = app.screens.top
    assert isinstance(screen, ErrorScreen)
    return screen


def key(k: int, mod: int = 0) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod, unicode="", scancode=0),
                   None, False)


def luminance(rgb) -> float:
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# --- AC-F01-79: readability -------------------------------------------------------------------

def test_fonts_are_bundled_and_at_least_28_px(monkeypatch):
    app, limiter, _ = error_app()
    with spy_draw_text(monkeypatch) as calls:
        limiter.quit_at(1)
        app.run()
    assert calls
    for call in calls:
        assert call.font.ref is None
        assert call.font.size >= 28
    heading = next(c for c in calls if c.text == "The game ran into a problem")
    assert heading.font.size == 40 and heading.pos == (80, 96)


def test_text_colors_have_at_least_7_to_1_contrast():
    for color in (HEADING_COLOR, MESSAGE_COLOR, DETAIL_COLOR, HINT_COLOR):
        assert contrast(color, BACKGROUND) >= 7.0


def _message_calls(calls):
    return [c for c in calls if c.color == MESSAGE_COLOR]


@pytest.mark.parametrize("fixture", ["long_message.txt", "long_word.txt"])
def test_long_messages_stay_in_their_area(monkeypatch, caplog, fixture):
    text = (TEXT / fixture).read_text(encoding="utf-8")
    assert len(text) == 5000
    caplog.set_level(logging.ERROR, logger="vn")
    app, limiter, _ = error_app(error=UserFacingError(text))
    with spy_draw_text(monkeypatch) as calls:
        limiter.quit_at(1)
        app.run()
    message = _message_calls(calls)
    assert message[-1].text == CUT_NOTICE
    for call in message:
        x, y, w, h = call.bounds
        assert 80 <= x and x + w <= 1200, call.bounds
        assert y + h <= 520, call.bounds
    assert any(r.getMessage() == text for r in caplog.records)


def test_short_message_is_one_call_with_the_whole_text(monkeypatch):
    app, limiter, _ = error_app(error=UserFacingError("Short problem."))
    with spy_draw_text(monkeypatch) as calls:
        limiter.quit_at(1)
        app.run()
    assert [c.text for c in _message_calls(calls)] == ["Short problem."]


@pytest.mark.parametrize("size, expected", [((640, 360), 14), ((2560, 1440), 56)])
def test_text_is_rasterized_at_device_size(monkeypatch, size, expected):
    app, limiter, _ = error_app(size)
    sizes = []
    real_font = app.assets.font

    def font(ref, size_px):
        sizes.append(size_px)
        return real_font(ref, size_px)

    monkeypatch.setattr(app.assets, "font", font)
    limiter.quit_at(1)
    app.run()
    assert expected in sizes


def test_letterbox_around_the_error_screen():
    app, limiter, window = error_app((2560, 1080))
    window.probe_points = [(100, 540), (1280, 20)]
    limiter.quit_at(1)
    app.run()
    assert window.flips[0].probes[(100, 540)] == LETTERBOX
    assert window.flips[0].probes[(1280, 20)] == BACKGROUND


def test_long_title_and_log_path_are_one_line(monkeypatch):
    title = ("Long title " * 46)[:500]
    app, limiter, _ = error_app(title=title)
    with spy_draw_text(monkeypatch) as calls:
        limiter.quit_at(1)
        app.run()
    details = [c for c in calls if c.color == DETAIL_COLOR]
    assert len(details) == 2
    title_call, log_call = details
    assert title_call.text.startswith('"Long title') and title_call.text.endswith("…")
    assert log_call.text.startswith("Log file: ")
    for call in details:
        assert "\n" not in call.text
        assert call.bounds[2] <= 1120


# --- sanitizing (SEC-F01-11, SEC-F01-21) ---------------------------------------------------------

def test_constructor_escapes_and_cuts():
    screen = ErrorScreen(message="a\x1b[31m" + "x" * 10_000, game_title="T‮\n",
                         game_version="1\r", log_display_path="p\t", tail=lambda: [],
                         on_quit=lambda: None, engine_version="0.1.0")
    assert len(screen.message) == ERROR_MESSAGE_MAX_CHARS and screen.message.endswith("…")
    assert "\x1b" not in screen.message and "\\x1b" in screen.message
    assert screen.game_title == "T\\u202e\\n"
    assert screen.game_version == "1\\r" and screen.log_display_path == "p\\t"


# --- keys (AC-F01-80 unit part; integration in tests/app) ------------------------------------------

@pytest.mark.parametrize("k", [pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER])
def test_quit_keys_call_on_quit(k):
    quits = []
    screen = ErrorScreen(message="m", game_title="t", game_version="v", log_display_path="p",
                         tail=lambda: [], on_quit=lambda: quits.append(1), engine_version="0.1.0")
    assert screen.handle_event(key(k)) is True
    assert quits == [1]


# --- AC-F01-83: copy details ----------------------------------------------------------------------

@pytest.fixture
def put_text(monkeypatch):
    calls = []

    def fake(text):
        calls.append(text)
        if getattr(fake, "error", None) is not None:
            raise fake.error

    monkeypatch.setattr(pygame.scrap, "put_text", fake)
    fake.calls = calls
    return fake


def hints(calls):
    return [c.text for c in calls if c.color == HINT_COLOR and c.text.startswith("Press Esc")]


def test_copy_text_and_copied_hint(monkeypatch, put_text):
    app, limiter, _ = error_app()
    tail = [f"line {n}" for n in range(60)]
    screen_of(app)._tail = lambda: tail[-50:]
    limiter.at(2, lambda: post_key(pygame.K_c))
    limiter.quit_at(2 + 125)
    with spy_draw_text(monkeypatch) as calls:
        assert app.run() == 1
    assert len(put_text.calls) == 1
    text = put_text.calls[0]
    assert text.startswith("Something went wrong inside the engine (RuntimeError: boom).")
    lines = text.split("\n")
    about = next(line for line in lines if line.startswith('"Paper Lanterns" version 0.1.0'))
    assert " | vn-engine 0.1.0 | Python " in about and " | pygame-ce " in about
    assert "Log file: not available yet" in lines
    assert lines[-50:] == tail[-50:]
    shown = hints(calls)
    copied = [i for i, h in enumerate(shown) if h.endswith(HINT_COPIED)]
    assert shown[0].endswith(HINT_COPY)
    # 2.0 s at 60 fps = 120 frames, ±1 frame.
    assert 119 <= len(copied) <= 121
    assert copied == list(range(copied[0], copied[0] + len(copied)))
    assert shown[copied[-1] + 1].endswith(HINT_COPY)


def test_copy_failure_is_shown(monkeypatch, put_text):
    put_text.error = pygame.error("no clipboard")
    app, limiter, _ = error_app()
    limiter.at(2, lambda: post_key(pygame.K_c))
    limiter.quit_at(4)
    with spy_draw_text(monkeypatch) as calls:
        assert app.run() == 1
    assert hints(calls)[-1].endswith(HINT_COPY_FAILED)


# --- AC-F01-153: only C copies; bounded size ----------------------------------------------------

def test_only_the_c_key_copies(put_text):
    screen = ErrorScreen(message="m", game_title="t", game_version="v", log_display_path="p",
                         tail=lambda: [], on_quit=lambda: None, engine_version="0.1.0")
    keys = [k for k in range(pygame.K_a, pygame.K_z + 1) if k != pygame.K_c]
    keys += [pygame.K_SPACE, pygame.K_RETURN] + [getattr(pygame, f"K_F{n}") for n in range(1, 13)]
    for k in keys:
        screen.handle_event(key(k))
    screen.handle_event(key(pygame.K_c, pygame.KMOD_CTRL))
    for button in (1, 2, 3):
        for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            screen.handle_event(UiEvent(pygame.event.Event(kind, pos=(5, 5), button=button),
                                        (5, 5), True))
    assert put_text.calls == []
    screen.handle_event(key(pygame.K_c))
    assert len(put_text.calls) == 1


def test_copy_of_a_huge_message_is_bounded_and_keeps_the_newest_tail(put_text):
    tail = [f"{n:02d} " + "t" * 2000 for n in range(50)]
    screen = ErrorScreen(message="é" * (5 * 1024 * 1024), game_title="t", game_version="v",  # 10 MB
                         log_display_path="p", tail=lambda: tail, on_quit=lambda: None,
                         engine_version="0.1.0")
    screen.handle_event(key(pygame.K_c))
    text = put_text.calls[0]
    assert len(text.encode("utf-8")) <= CLIPBOARD_MAX_BYTES
    assert text.endswith(tail[-1])
    kept = [line for line in text.split("\n") if line.endswith("t" * 2000)]
    assert kept == tail[-len(kept):]


def test_copy_cuts_the_message_when_the_tail_is_gone(put_text):
    screen = ErrorScreen(message="m", game_title="t", game_version="v", log_display_path="p",
                         tail=lambda: [], on_quit=lambda: None, engine_version="0.1.0")
    screen.message = "€" * 30_000          # beyond any real message, to exercise the cut
    screen.handle_event(key(pygame.K_c))
    assert len(put_text.calls[0].encode("utf-8")) <= CLIPBOARD_MAX_BYTES


# --- AC-F01-154: bounded layout cost ----------------------------------------------------------------

def test_a_10_mb_message_lays_out_quickly(monkeypatch):
    import engine.render.canvas as canvas_module

    longest = []
    real_wrap = canvas_module.wrap_lines

    def wrap_lines(font, text, max_width):
        longest.append(len(text))
        return real_wrap(font, text, max_width)

    monkeypatch.setattr(canvas_module, "wrap_lines", wrap_lines)
    window = FakeWindow()
    app, limiter = make_app(window)
    started = time.perf_counter()
    app.show_fatal_error(UserFacingError("word " * (2 * 1024 * 1024)))
    with spy_draw_text(monkeypatch) as calls:
        limiter.quit_at(1)
        app.run()
    assert time.perf_counter() - started < 1.0
    assert window.flips
    assert max(longest) <= ERROR_MESSAGE_MAX_CHARS
    for call in _message_calls(calls):
        x, y, w, h = call.bounds
        assert 80 <= x and x + w <= 1200 and y + h <= 520
