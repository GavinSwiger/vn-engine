"""In-process ``launch()`` helpers: an App whose loop is driven frame by frame.

``scripted_session(monkeypatch)`` replaces ``bootstrap.App`` with an App on a fake clock
that quits after ``session.quit_frame`` frames (an in-process launch would otherwise run
forever), and ``pygame.Window`` with ``SpyWindow`` so the window stays hidden on a real
display, and gives F08's ``AudioService`` a ``FakeMixer`` (``session.mixers``). The
``scripted_app`` fixture in ``tests/conftest.py`` wraps it."""

import contextlib
from collections.abc import Callable

from engine.app import bootstrap
from engine.app.app import App
from engine.audio import backend as audio_backend
from tests.fakes.fake_mixer import FakeMixer
from tests.fakes.loop import FakeClock, ScriptedLimiter
from tests.fakes.spy_window import SpyWindow


class ScriptedSession:
    """What the next ``launch()``'s App should do: run until ``quit_frame``, running
    ``actions[frame](app)`` at the start of each scripted frame."""

    def __init__(self) -> None:
        self.quit_frame = 3
        self.actions: list[tuple[int, Callable[[App], None]]] = []
        self.apps: list[App] = []
        self.limiters: list[ScriptedLimiter] = []
        self.mixers: list[FakeMixer] = []        # F08: one per launch's AudioService

    def at(self, frame: int, action: Callable[[App], None]) -> None:
        self.actions.append((frame, action))


@contextlib.contextmanager
def scripted_session(monkeypatch):
    session = ScriptedSession()

    class ScriptedApp(App):
        def __init__(self, **kwargs):
            clock = FakeClock()
            limiter = ScriptedLimiter(clock)
            super().__init__(**kwargs, clock=clock, limiter=limiter)
            for frame, action in session.actions:
                limiter.at(frame, lambda action=action: action(self))
            limiter.quit_at(session.quit_frame)
            session.apps.append(self)
            session.limiters.append(limiter)

    def fake_backend(**kwargs):
        mixer = FakeMixer()
        session.mixers.append(mixer)
        return mixer

    monkeypatch.setattr(bootstrap, "App", ScriptedApp)
    # F08: every launch's AudioService gets a FakeMixer (no test opens a sound device).
    monkeypatch.setattr(audio_backend, "open_backend", fake_backend)
    with SpyWindow.installed(monkeypatch):
        yield session
