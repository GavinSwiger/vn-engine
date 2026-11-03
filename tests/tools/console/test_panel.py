"""F40 P5: the console panel's input and drawing (``04`` §7.6; ``01`` §6.1). AC-F40-25.

Display test: pygame under SDL's dummy driver (``tests/conftest.py``), real SDL text input
and real ``TEXTINPUT`` events through the event queue. The clipboard read is stubbed at
``pygame.scrap.get_text``, so the test never touches the real clipboard."""

import pygame
import pytest

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.tools.console import panel as panel_mod
from engine.tools.console.model import INPUT_MAX, Close, RunCode, SetValue, Tab, where_now
from engine.tools.console.panel import ConsolePanel
from engine.ui.input import UiEvent
from tests.render.conftest import make_assets
from tests.runtime.flow_story import load_l
from tests.tools.console.test_model import STORY, FakeRunner, model_for, started

pytestmark = pytest.mark.display


@pytest.fixture(scope="module")
def program(tmp_path_factory):
    return load_l(tmp_path_factory.mktemp("console_panel"), STORY)


@pytest.fixture
def window():
    pygame.init()
    window = pygame.Window("console", (320, 180))
    pygame.event.clear()
    yield window
    panel_mod.stop_typing()
    window.destroy()
    pygame.quit()


def typed(panel: ConsolePanel, text: str) -> None:
    """``text`` through SDL's queue as the keyboard (or an IME) delivers it."""
    pygame.event.post(pygame.event.Event(pygame.TEXTINPUT, text=text, window=None))
    for event in pygame.event.get(pygame.TEXTINPUT):
        assert panel.handle(UiEvent(event, None, False)) is None


def key(panel: ConsolePanel, k: int, mod: int = 0):
    return panel.handle(UiEvent(pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod), None, False))


def drawn(panel: ConsolePanel) -> pygame.Surface:
    canvas = Canvas(make_assets(None))
    framebuffer = pygame.Surface(CANVAS_SIZE)
    canvas.bind(framebuffer, Viewport.compute(CANVAS_SIZE, CANVAS_SIZE), RenderQuality.FINAL)
    panel.draw(canvas)
    return framebuffer


# --- AC-F40-25 — typed text (non-Latin too) and Ctrl+V reach the field -------------------------

def test_ac25_text_input_and_paste_reach_the_field(program, window, monkeypatch):
    interp = started(program)
    runner = FakeRunner(interp)
    model = model_for(program, runner)
    model.opened(where_now(interp), interp)
    panel = ConsolePanel(model)
    panel_mod.start_typing()                                 # SDL text input on

    # Variables: typing filters (case-insensitive, non-Latin kept as typed).
    typed(panel, "Co")
    assert model.filters[Tab.VARIABLES].text == "Co"
    assert [r.name for r in model.visible() if r.selectable] == ["coins"]
    key(panel, pygame.K_BACKSPACE)
    key(panel, pygame.K_BACKSPACE)
    assert key(panel, pygame.K_RETURN) is None and model.editing == "mood"
    key(panel, pygame.K_END)
    for _ in "'calm'":
        key(panel, pygame.K_BACKSPACE)
    typed(panel, "\"Мир 日本 é\"")          # Мир 日本 é
    assert model.value.text == "\"Мир 日本 é\""
    action = key(panel, pygame.K_RETURN)
    assert action == SetValue("mood", model.value.text)
    assert model.apply(action, where_now(interp), interp).ok
    assert interp.G["mood"] == "Мир 日本 é"

    # Code: Ctrl+3, IME composition shown, then the committed text and a paste.
    key(panel, pygame.K_3, pygame.KMOD_LCTRL)
    assert model.tab is Tab.CODE
    pygame.event.post(pygame.event.Event(pygame.TEXTEDITING, text="にほ", start=0,
                                         length=2, window=None))
    for event in pygame.event.get(pygame.TEXTEDITING):
        panel.handle(UiEvent(event, None, False))
    assert panel.composing == "にほ"
    drawn(panel)                                             # composition drawn at the caret
    typed(panel, "coins = len('日本')")
    assert panel.composing == "" and model.code.text == "coins = len('日本')"

    clipboard = ["  + 1\x00\x1b\x07\x9b # café \U0001F600\nsecond line\n"]
    monkeypatch.setattr(pygame.scrap, "get_text", lambda: clipboard[0])
    key(panel, pygame.K_v, pygame.KMOD_LCTRL)
    assert model.code.text == "coins = len('日本')  + 1 # café \U0001F600"
    action = key(panel, pygame.K_RETURN)
    assert action == RunCode("coins = len('日本')  + 1 # café \U0001F600")
    assert model.apply(action, where_now(interp), interp).ok and interp.G["coins"] == 3

    clipboard[0] = "9" * 5_000                               # a huge paste is cut
    key(panel, pygame.K_v, pygame.KMOD_LCTRL)
    assert model.code.text == "9" * INPUT_MAX

    # Drawn: the fixed look, the focused field, every tab.
    surface = drawn(panel)
    assert tuple(surface.get_at((64, 48)))[:3] == panel_mod.BORDER_COLOR
    fx, fy = panel_mod.CODE_RECT[0] + 2, panel_mod.CODE_RECT[1] + 2
    assert tuple(surface.get_at((fx, fy)))[:3] == panel_mod.SELECTED_COLOR
    for k in (pygame.K_1, pygame.K_2):
        key(panel, k, pygame.KMOD_LCTRL)
        drawn(panel)
    assert key(panel, pygame.K_ESCAPE) == Close()
