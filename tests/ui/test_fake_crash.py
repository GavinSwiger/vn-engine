"""F30 step 4 — AC-F30-18: the fake crash page's fixed look (``04`` §6.2 draw, §6.5;
UI-F30-01; SEC-F30-10(a)). ``FakeCrashScreen`` drawn on a bound ``Canvas`` (1280×720 unless
a row says otherwise) with the Draw spy. The 2560×1080 and 1920×1080 rows are ``slow`` in
``06`` and not built here; the in-app rows (input, fade, quit, saves) are in
``tests/app/test_fourthwall_app.py``."""

import pygame
import pytest

from engine.core.config_schema import WordsConfig
from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.ui.builtin import error_look
from engine.ui.builtin.fake_crash import FakeCrashScreen, crash_text
from engine.ui.screen import Screen, ScreenStack
from engine.ui.theme import Words
from tests.fakes.draw_spy import spy_draw_text
from tests.render.conftest import make_assets

pytestmark = pytest.mark.display

TRACEBACK = ('Traceback (most recent call last):\n  File "lantern.vns", line 7\n'
             "LanternError: Hana is not responding")
BG = (0x14, 0x14, 0x14)
WHITE, MESSAGE, DETAIL = (0xFF, 0xFF, 0xFF), (0xF0, 0xF0, 0xF0), (0xC8, 0xC8, 0xC8)
WORDS = Words(WordsConfig())


def crash(message: str, *, hint: str | None = None, stack: ScreenStack | None = None
          ) -> FakeCrashScreen:
    return FakeCrashScreen(message=message, game_title="Paper Test", game_version="1.0",
                           hint=hint if hint is not None else WORDS.get("fake_crash_hint"),
                           label=None, fade=False, on_continue=lambda: None,
                           waiting=lambda: True, stack=stack or ScreenStack())


def canvas_of(size=(1280, 720)) -> Canvas:
    canvas = Canvas(make_assets(None))
    canvas.bind(pygame.Surface(size), Viewport.compute(CANVAS_SIZE, size), RenderQuality.FINAL)
    return canvas


def drawn(monkeypatch, screen: FakeCrashScreen, size=(1280, 720)):
    canvas = canvas_of(size)
    with monkeypatch.context() as patch, spy_draw_text(patch) as calls:
        screen.draw(canvas)
    return calls, canvas


def contrast(a, b) -> float:
    def lum(rgb):
        c = [v / 255 for v in rgb]
        c = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_ac_f30_18_the_crash_screens_fixed_look(monkeypatch):
    # The page at frame c: heading, the message, the details line, the hint; nothing else.
    calls, canvas = drawn(monkeypatch, crash(TRACEBACK))
    got = [(c.text, c.font.size, c.color, c.pos) for c in calls]
    assert got == [("The game ran into a problem", 40, WHITE, (80, 96)),
                   (TRACEBACK, 28, MESSAGE, (80, 168)),
                   ('"Paper Test" version 1.0', 28, DETAIL, (80, 540)),
                   ("Press Esc or Enter to continue", 28, WHITE, (80, 640))]
    assert len(canvas.layout_lines(TRACEBACK, error_look.TEXT_FONT, 1120, None)) == 3
    assert all(c.pos[1] != 580 for c in calls)                 # no log line
    assert not [c for c in calls for word in ("Log", "log file", "copy") if word in c.text]
    for x, y in ((10, 10), (1270, 710)):
        assert tuple(canvas.surface.get_at((x, y)))[:3] == BG, (x, y)
    assert contrast(MESSAGE, BG) >= 16.0 and contrast(DETAIL, BG) >= 11.0
    # A bare `effect crash`: the default word.
    assert crash_text(None, None, WORDS.get("fake_crash_message")) == "Something went wrong."
    # 2,000 characters of words ; 1,000 line breaks: cut above y 520 with "…", no notice.
    words = ("lantern " * 250)[:2000]
    for message in (words, "\n" * 1000):
        calls, _ = drawn(monkeypatch, crash(message))
        block = calls[1]
        lines = block.text.split("\n")
        x, y, w, h = block.bounds
        assert x >= 80 and x + w <= 1200 and y + h <= 520, block.bounds
        assert lines[-1].endswith("…") and "log file" not in block.text
        assert calls[-1].pos == (80, 640) and len(calls) == 4
    # U+202E and U+2028 are shown as F01's escape forms.
    calls, _ = drawn(monkeypatch, crash("a‮b c"))
    assert calls[1].text == "a\\u202eb\\u2028c"
    # A message dressed as the OS's own changes nothing else; the hint follows [words].
    calls, _ = drawn(monkeypatch, crash("Your PC ran into a problem and needs to restart"))
    assert [c.text for c in calls[::2]] == ["The game ran into a problem",
                                            '"Paper Test" version 1.0']
    assert calls[-1].text == "Press Esc or Enter to continue"
    calls, _ = drawn(monkeypatch, crash("x", hint="Press any key"))
    assert (calls[-1].text, calls[-1].pos) == ("Press any key", (80, 640))

    # `effect static on` before the crash: while the page is opaque the stage isn't drawn.
    class Stage(Screen):
        drawn = 0

        def draw(self, canvas):
            Stage.drawn += 1

    stack = ScreenStack()
    stack.push(Stage())
    stack.push(crash("x", stack=stack))
    stack.draw(canvas_of())
    assert Stage.drawn == 0

    # 640×360: the 28-unit text rasters at 14 px.
    sizes = []
    real = Canvas.font_handle
    monkeypatch.setattr(Canvas, "font_handle",
                        lambda self, font, size_px: sizes.append((font.size, size_px))
                        or real(self, font, size_px))
    drawn(monkeypatch, crash("x"), size=(640, 360))
    assert (28, 14) in sizes and not [s for f, s in sizes if f == 28 and s not in (14, 28)]


# --- F30 step 5: AC-F30-36 ---------------------------------------------------------------------

def test_ac_f30_36_label_fake_error_screens(monkeypatch):
    from types import SimpleNamespace

    from engine.app.settings import SettingsService
    from engine.core.config_schema import Config
    from engine.persist.settings_file import LoadedSettings, Outcome
    from engine.ui.builtin.settings_page import SettingsPage

    def labelled(label):
        screen = FakeCrashScreen(message="x", game_title="Paper Test", game_version="1.0",
                                 hint=WORDS.get("fake_crash_hint"), label=label, fade=False,
                                 on_continue=lambda: None, waiting=lambda: True,
                                 stack=ScreenStack())
        calls, _ = drawn(monkeypatch, screen)
        return [(c.text, c.font.size, c.color, c.pos) for c in calls if c.pos[1] == 680]

    assert labelled(WORDS.get("fake_crash_label")) == [
        ("This is part of the story.", 28, DETAIL, (80, 680))]
    story = Words(WordsConfig(fake_crash_label="Story event."))
    assert labelled(story.get("fake_crash_label"))[0][0] == "Story event."
    assert labelled(None) == []
    # The row: in the Data group iff the story has an `effect crash`; default off; Reset.
    host = SimpleNamespace(shell=SimpleNamespace(words=WORDS))
    for crash in (True, False):
        settings = SettingsService(LoadedSettings({}, Outcome.OK), Config())
        settings.row_rules["settings_crash_label"] = lambda crash=crash: crash
        widgets = SettingsPage(host, settings, title=False).widgets
        assert ("settings_crash_label" in widgets) is crash
    settings.row_rules["settings_crash_label"] = lambda: True
    row = SettingsPage(host, settings, title=False).widgets["settings_crash_label"]
    assert row.get() is False
    row.set(True)
    assert settings.value("crash_label") is True
    settings.reset()
    assert row.get() is False
