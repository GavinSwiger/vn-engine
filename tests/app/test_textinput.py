"""F52 step W2: the one owner of SDL text input (``app/textinput.py``): AC-F52-04, 05, 13."""

import re
from pathlib import Path
from types import SimpleNamespace

import pygame

from engine.app.textinput import CLIPBOARD_MAX, TextInputOwner, read_clipboard
from engine.core.geometry import Viewport
from engine.ui.focus import Box
from engine.ui.screen import LEGACY_TEXT, Screen, ScreenStack

REPO = Path(__file__).resolve().parents[2]


class FakeKey:
    def __init__(self) -> None:
        self.calls: list = []

    def start_text_input(self) -> None:
        self.calls.append("start")

    def stop_text_input(self) -> None:
        self.calls.append("stop")

    def set_text_input_rect(self, rect) -> None:
        self.calls.append(("rect", tuple(rect)))


class Field:
    def __init__(self, box=Box(100, 200, 400, 56), caret_x=150.0) -> None:
        self.box = box
        self.caret_x = caret_x
        self.lost = 0

    def ime_rect(self) -> Box:
        return Box(self.caret_x, self.box.y, 2, self.box.h)

    def text_lost(self) -> None:
        self.lost += 1


class Top(Screen):
    def __init__(self, target=None) -> None:
        self.target = target

    def text_target(self):
        return self.target


class Window:
    def __init__(self, points_per_pixel: float = 1.0) -> None:
        self.k = points_per_pixel

    def pixels_to_points(self, pos):
        return pos[0] * self.k, pos[1] * self.k


def make_app(window_px=(1280, 720), points=1.0):
    stack = ScreenStack()
    return SimpleNamespace(focused=True, error_mode=False, dev=True, console=None,
                           screens=stack, viewport=Viewport.compute((1280, 720), window_px),
                           window=Window(points))


# --- AC-F52-04: off at launch; on only while a field is focused on the top screen ----------------

def test_ac_f52_04_text_input_switching(monkeypatch):
    import os

    from engine.app import cli
    monkeypatch.delenv("SDL_IME_SHOW_UI", raising=False)
    cli.prepare_environment()
    assert os.environ["SDL_IME_SHOW_UI"] == "1"                # the IME draws its own windows
    app = make_app()
    key = FakeKey()
    owner = TextInputOwner(app, key=key)
    assert key.calls == ["stop"]                              # off before the first frame
    owner.sync()
    assert key.calls == ["stop"] and not owner.on             # nothing wants typing
    menu = Top()
    app.screens.push(menu)
    owner.sync()
    assert not owner.on
    a = Field()
    menu.target = a                                           # a field is focused
    owner.sync()
    assert owner.on and key.calls[1] == "start"
    key.calls.clear()
    owner.sync()
    assert key.calls == []                                    # no change: SDL isn't called
    cover = Top()                                             # covered by another screen
    app.screens.push(cover)
    owner.sync()
    assert key.calls == ["stop"] and a.lost == 1 and not owner.on
    app.screens.pop()
    owner.sync()
    assert owner.on
    b = Field()
    menu.target = b                                           # field to field: the IME resets
    key.calls.clear()
    owner.sync()
    assert key.calls[:2] == ["stop", "start"] and a.lost == 2
    app.focused = False                                       # the window lost focus
    owner.sync()
    assert not owner.on and b.lost == 1
    app.focused = True
    owner.sync()
    assert owner.on
    app.error_mode = True
    owner.sync()
    assert not owner.on
    app.error_mode = False
    menu.target = None                                        # unfocused or closed
    owner.sync()
    assert not owner.on
    # LEGACY: a plugin below API 1.4 keeps text input on, with no IME rect.
    menu.target = LEGACY_TEXT
    key.calls.clear()
    owner.sync()
    assert key.calls == ["start"] and owner.on
    menu.target = None
    owner.sync()
    # F40's console goes through the same owner.
    console = SimpleNamespace(open=True, ime_rect=lambda: Box(64, 600, 1152, 28))
    app.console = console
    key.calls.clear()
    owner.sync()
    assert key.calls[0] == "start" and key.calls[1][0] == "rect"
    console.open = False
    owner.sync()
    assert not owner.on
    source = (REPO / "engine/tools/console/console.py").read_text(encoding="utf-8")
    assert "start_text_input" not in source and "start_typing" not in source


# --- AC-F52-05: the IME rect follows the caret in window units at two sizes ---------------------

def test_ac_f52_05_ime_rect():
    for window_px, points, expected in (
            ((1280, 720), 1.0, (150, 200, 2, 56)),
            ((1920, 1080), 1.0, (225, 300, 3, 84)),
            ((1920, 1200), 1.0, (225, 360, 3, 84)),           # letterboxed: 60 px bars
            ((2560, 1440), 0.5, (150, 200, 2, 56))):           # a Retina Mac: points
        app = make_app(window_px, points)
        key = FakeKey()
        owner = TextInputOwner(app, key=key)
        top = Top(Field())
        app.screens.push(top)
        owner.sync()
        assert key.calls[-1] == ("rect", expected), window_px
        top.target.caret_x = 300                               # the caret moved
        owner.sync()
        assert key.calls[-1][0] == "rect" and key.calls[-1][1][0] > expected[0]
        calls = len(key.calls)
        owner.sync()
        assert len(key.calls) == calls                         # same rect: not set again


# --- AC-F52-13: one owner of text input and clipboard reads; nothing writes typed text ----------

CALLS = re.compile(r"start_text_input|stop_text_input|set_text_input_rect|scrap\.get_text")


def test_ac_f52_13_one_owner():
    users = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "engine").rglob("*.py")
                   if CALLS.search(p.read_text(encoding="utf-8")))
    assert users == ["engine/app/textinput.py"]
    writers = sorted(p.relative_to(REPO).as_posix() for p in (REPO / "engine").rglob("*.py")
                     if "scrap.put_text" in p.read_text(encoding="utf-8"))
    assert writers == ["engine/ui/builtin/error.py"]          # never F52's code
    # The read: text only, cut to 4,000 at once, "" on failure.
    assert read_clipboard(SimpleNamespace(get_text=lambda: "x" * 9_000)) == "x" * CLIPBOARD_MAX
    assert read_clipboard(SimpleNamespace(get_text=lambda: "é".encode())) == "é"

    def broken():
        raise pygame.error("no clipboard")
    assert read_clipboard(SimpleNamespace(get_text=broken)) == ""
    assert read_clipboard(SimpleNamespace(get_text=lambda: None)) == ""
