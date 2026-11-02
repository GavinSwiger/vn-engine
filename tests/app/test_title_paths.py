"""F30 — the game's own window title on every path outside the story (``04`` §6.1 step 2).

Step 1: AC-F30-06 (a real error restores the game's title, C6). AC-F30-17 (the other
paths: new game, return to title, story end, the ending card) joins in step 4."""

import pygame
import pytest

from engine.app.app import App
from engine.core.config_schema import Config, GameConfig, WindowConfig
from engine.core.errors import UserFacingError
from engine.render.canvas import Canvas
from engine.ui.builtin.error import HEADING, ErrorScreen
from engine.ui.screen import Screen
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import LETTERBOX, make_app
from tests.fakes.username import no_real_username  # noqa: F401  (name guard, AC-F30-07)

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


class _Raiser(Screen):
    opaque = False

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def update(self, dt, *, is_top):
        raise self.error


def test_ac_f30_06_a_real_error_restores_the_game_title(monkeypatch):
    rows = [
        ("engine exception", RuntimeError("boom")),
        ("user-facing error", UserFacingError("Bad file.")),
    ]
    for name, error in rows:
        events: list[tuple[str, str]] = []
        real_set_title, real_draw = App.set_title, Canvas.draw_text

        def set_title(self, title, real_set_title=real_set_title):
            events.append(("title", title))
            real_set_title(self, title)

        def draw_text(self, text, *args, real_draw=real_draw, **kwargs):
            events.append(("draw", text))
            return real_draw(self, text, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(App, "set_title", set_title)
            patch.setattr(Canvas, "draw_text", draw_text)
            config = Config(game=GameConfig(title="Paper Test", version="1.0"),
                            window=WindowConfig(letterbox_color=LETTERBOX))
            window = FakeWindow((1280, 720))
            app, limiter = make_app(window, config=config)
            app.set_title("Scripted")                     # a story renamed the window
            limiter.at(2, lambda: app.screens.push(_Raiser(error)))
            limiter.quit_at(5)
            app.run()

        assert isinstance(app.screens.top, ErrorScreen), name
        first_draw = events.index(("draw", HEADING))
        titles = [text for kind, text in events[:first_draw] if kind == "title"]
        assert titles[-1] == "Paper Test", (name, titles)
        assert window.title == "Paper Test", name
        assert window.flips[-1].title == "Paper Test", name
