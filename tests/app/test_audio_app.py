"""F08 step 4 in the App: ``App.audio``, its frame slots, ``install_audio``, and the error
screen (F08 ``04`` §7.10; ``07`` §2.10 item 1, I-4, I-8; ``docs/architecture.md`` frame order).

Unit-level loops use ``make_app`` (FakeWindow, scripted limiter) with an ``AudioService`` on
``FakeMixer``. The launch (``App.audio`` built, the router wired, the shutdown hook) is
``test_music_app.py``'s."""

import pygame
import pytest

from engine.app.dispatch import CommandRouter
from engine.app.story import AUDIO_COMMANDS, install_audio
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.runtime.commands import PlaySound
from engine.ui.screen import Screen
from tests.fakes.fake_mixer import FakeMixer
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


class RecordingAudio(AudioService):
    """A real service on FakeMixer that notes its slot calls in ``order``."""

    def __init__(self, order: list, *, consume: set[int] = frozenset(), **kwargs) -> None:
        super().__init__(None, SizedLru(1 << 20), AudioConfig(), backend=FakeMixer(), **kwargs)
        self.order = order
        self.consume = consume
        self.events: list[int] = []

    def handle_event(self, raw) -> bool:
        self.events.append(raw.type)
        return raw.type in self.consume

    def update(self, now: float) -> None:
        self.order.append("audio.update")
        super().update(now)

    def stop_story_audio(self, fadeout: float = 0.5) -> None:
        self.order.append(("stop_story_audio", fadeout))
        super().stop_story_audio(fadeout)

    def _play_sound(self, cmd) -> None:
        self.order.append("PlaySound")
        super()._play_sound(cmd)


class OrderScreen(Screen):
    in_game = True

    def __init__(self, order: list) -> None:
        self.order = order
        self.events: list = []

    def handle_event(self, event):
        self.events.append(event)
        return False

    def update(self, dt: float, *, is_top: bool) -> None:
        self.order.append("screens.update")

    def draw(self, canvas) -> None:
        pass


class OneCommandStory:
    def __init__(self, order: list, command) -> None:
        self.order = order
        self.command = command

    def post(self, event) -> None:
        pass

    def pump(self, max_commands=256):
        self.order.append("pump")
        command, self.command = self.command, None
        return [command] if command is not None else []


def audio_app(order: list, **kwargs):
    window = FakeWindow()
    app, limiter = make_app(window)
    audio = RecordingAudio(order, clock=app._clock, **kwargs)
    app.audio = audio
    install_audio(app)
    app.screens.push(OrderScreen(order))
    return app, limiter, audio


def test_app_audio_is_none_by_default_and_install_audio_falls_back():
    app, _ = make_app(FakeWindow())
    assert app.audio is None
    install_audio(app)                                  # the nine silent stand-ins
    for command_type in AUDIO_COMMANDS:
        assert command_type in app.router._handlers


def test_install_audio_registers_the_service():
    order: list = []
    app, _, audio = audio_app(order)
    handler = app.router._handlers[PlaySound]
    assert handler.__self__ is audio
    assert set(AUDIO_COMMANDS) <= set(app.router._handlers)


def test_frame_order_dispatch_then_audio_update_then_screens():
    order: list = []
    app, limiter, audio = audio_app(order)
    app.story = OneCommandStory(order, PlaySound("sfx/rain.ogg", True, 100, None))
    limiter.quit_at(3)
    assert app.run() == 0
    assert order[:4] == ["pump", "PlaySound", "audio.update", "screens.update"]
    assert order.count("audio.update") == 3
    frames = [i for i, item in enumerate(order) if item == "pump"]
    for start in frames:
        assert order[start:start + 4] in (["pump", "PlaySound", "audio.update", "screens.update"],
                                          ["pump", "audio.update", "screens.update", "pump"],
                                          ["pump", "audio.update", "screens.update"])


def test_raw_events_reach_audio_first_and_it_may_consume_them():
    order: list = []
    custom = pygame.event.custom_type()
    app, limiter, audio = audio_app(order, consume={custom})
    screen = app.screens.top
    limiter.at(1, lambda: pygame.event.post(pygame.event.Event(custom)))
    limiter.at(1, lambda: pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a,
                                                               mod=0, unicode="a", scancode=0)))
    limiter.quit_at(2)
    assert app.run() == 0
    assert audio.events[:2] == [custom, pygame.KEYDOWN]
    assert pygame.QUIT in audio.events                   # QUIT too, before the App's handling
    seen = [e.type for e in screen.events]
    assert pygame.KEYDOWN in seen and custom not in seen


def test_the_error_screen_stops_story_audio_and_update_keeps_running():
    order: list = []
    app, limiter, audio = audio_app(order)

    def boom():
        raise RuntimeError("frame failure")

    limiter.at(2, lambda: setattr(app.screens.top, "update", lambda dt: boom()))
    limiter.quit_at(5)
    app.run()
    assert ("stop_story_audio", 0.5) in order
    after = order[order.index(("stop_story_audio", 0.5)):]
    assert after.count("audio.update") >= 3              # frames 3–5, in error mode
    assert app.error_mode


def test_show_fatal_error_without_audio_is_fine():
    app, _ = make_app(FakeWindow())
    app.show_fatal_error(RuntimeError("x"))
    assert app.error_mode


def test_minimized_this_frame_and_each_minimized_wake_update_audio(monkeypatch):
    order: list = []
    app, limiter, audio = audio_app(order)
    waits = []

    def wait(timeout=0):
        waits.append(timeout)
        if len(waits) == 4:
            pygame.event.post(pygame.event.Event(pygame.WINDOWRESTORED))
        return pygame.event.poll()

    monkeypatch.setattr(pygame.event, "wait", wait)
    limiter.at(2, lambda: pygame.event.post(pygame.event.Event(pygame.WINDOWMINIMIZED)))
    limiter.quit_at(4)
    assert app.run() == 0
    # Frame 1 (normal), frame 2 (minimized this frame: no screens), 4 wakes, frames 3–4.
    assert order.count("screens.update") == 3
    assert order.count("audio.update") == 1 + 1 + 4 + 2


def test_the_audio_router_type_is_only_a_register_method():
    """I-8: ``audio`` never imports ``app``; any object with ``register`` will do."""
    seen = []

    class Registry:
        def register(self, command_type, handler):
            seen.append(command_type)

    AudioService(None, SizedLru(1 << 20), AudioConfig(), backend=FakeMixer()).register(Registry())
    assert set(seen) == set(AUDIO_COMMANDS)
    router = CommandRouter()
    AudioService(None, SizedLru(1 << 20), AudioConfig(), backend=FakeMixer()).register(router)
