"""F52 step W4: text fields in minigames (API 1.4) on Host U: AC-F52-03, 07, 25, 27."""

from pathlib import Path

import pygame
import pytest

from engine.core.paths import GamePaths
from engine.minigames.loader import PluginLoadJob
from engine.runtime.guard import NO_GUARD
from engine.ui.input import UiEvent
from engine.ui.screen import LEGACY_TEXT
from tests.fakes.ui_shell import UiHarness
from tests.minigames.conftest import write
from tests.minigames.host_u import HostU

H = UiHarness
PLUGIN = Path(__file__).resolve().parents[1] / "fixtures" / "F52" / "plugins" / "typer.py"


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture
def world(game):
    write(game, "minigames/typer.py", PLUGIN.read_bytes())
    result = PluginLoadJob(GamePaths.for_game(game), NO_GUARD, dev=True).run()
    assert result.ok, [e.format() for e in result.errors]
    return HostU(game, registry=result.registry)


def typed(text: str) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.TEXTINPUT, text=text), None, False)


def editing(text: str) -> UiEvent:
    return UiEvent(pygame.event.Event(pygame.TEXTEDITING, text=text, start=0,
                                      length=len(text)), None, False)


def opened(w: HostU, name: str = "typer"):
    w.start(name, {})
    w.frame()
    s = w.session
    assert s is not None and not w.fatal
    return s, s.plugin


# --- AC-F52-03: while composing, the IME's keys reach neither field nor screen -------------------

@pytest.mark.parametrize("key", [pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE,
                                 pygame.K_BACKSPACE, pygame.K_DELETE, pygame.K_LEFT,
                                 pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN, pygame.K_HOME,
                                 pygame.K_END, pygame.K_TAB])
def test_ac_f52_03_composing_guard(world, key):
    w = world
    s, g = opened(w)
    w.frame(typed("ab"))
    w.frame(editing("かな"))
    seen = len(g.seen)
    # macOS order: the key-down arrives while composing; it is used, with no action.
    assert w.screen.handle_event(H.key(key)) is True           # Esc: no game menu
    assert w.screen.handle_event(H.key(key, up=True)) is True
    assert g.field.text == "ab" and g.field.model.caret == 2 and g.field.composing
    assert len(g.seen) == seen and s.scope.focused is g.field and not g.ctx is None
    # Windows / IBus order: the commit, then the key in the same frame: still the IME's.
    w.screen.handle_event(typed("仮名"))
    assert w.screen.handle_event(H.key(key)) is True
    assert g.field.text == "ab仮名" and len(g.seen) == seen
    assert w.used()                                            # guard swallows count as used
    w.frame()                                                  # the frame ends: the latch too
    assert not g.field.composing


# --- AC-F52-07: Backspace on an empty focused field is never Back or the game menu ---------------

def test_ac_f52_07_backspace_on_an_empty_field(world):
    w = world
    s, g = opened(w)
    assert g.field.text == "" and s.scope.focused is g.field
    for _ in range(3):
        assert w.screen.handle_event(H.key(pygame.K_BACKSPACE)) is True
        w.frame()
    assert s.scope.focused is g.field and w.session is s and pygame.KEYDOWN not in g.seen
    assert w.shell.stack.top is w.screen


# --- AC-F52-25: raw events go to an API 1.4 plugin's field first; an API 1.3 plugin is unchanged --

def test_ac_f52_25_routing_by_api(world):
    w = world
    s, g = opened(w)
    assert s.text_api and w.screen.text_target() is g.field
    w.frame(typed("Sayo"))
    assert g.field.text == "Sayo" and pygame.TEXTINPUT not in g.seen     # never the plugin's
    assert g.changes == ["Sayo"] and w.used()                 # one commit, one on_change
    w.frame(H.key(pygame.K_LEFT), H.key(pygame.K_BACKSPACE))
    assert g.field.text == "Sao" and pygame.KEYDOWN not in g.seen
    w.frame(H.key(pygame.K_DOWN))                              # Up/Down pass: the scope moves
    assert s.scope.focused is g.ok and pygame.KEYDOWN in g.seen
    assert w.screen.text_target() is None
    s.scope.focus(g.field, s.last_kind)
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_A))                 # south: the host's keyboard
    assert s.keyboard is not None and s.keyboard.is_open
    assert all(not hasattr(x, "press") for x in s.scope.widgets())   # never in ctx.scope
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_B))
    assert not s.keyboard.is_open and w.session is s
    w.frame(H.key(pygame.K_RETURN))                            # Enter submits: on_submit
    assert s.finished and s.result == "Sao"
    # An API 1.3 plugin: no router; it reads TEXTINPUT itself, and text input stays on.
    s, g = opened(w, "oldtyper")
    assert not s.text_api and w.screen.text_target() is LEGACY_TEXT
    w.frame(typed("hi"))
    assert g.text == "hi" and pygame.TEXTINPUT in g.seen


# --- AC-F52-27: Esc with a focused field opens the game menu; the text is kept --------------------

def test_ac_f52_27_esc_opens_the_game_menu(world):
    w = world
    s, g = opened(w)
    w.frame(typed("Hana"))
    assert w.screen.handle_event(H.key(pygame.K_ESCAPE)) is False   # to F10's GameMenuKeys
    assert g.field.text == "Hana" and w.session is s and not s.finished
    w.frame(H.pad(pygame.CONTROLLER_BUTTON_A))
    assert s.keyboard.is_open
    assert w.screen.handle_event(H.key(pygame.K_ESCAPE)) is False   # over the keyboard too
    assert w.screen.handle_event(H.pad(pygame.CONTROLLER_BUTTON_START)) is False
    assert g.field.text == "Hana"
