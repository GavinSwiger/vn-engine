"""F08 step 7 in the App: the background rules and window changes (F08 ``04`` §7.8, §7.10;
AC-F08-49's App half, AC-F08-50 through the App's event path). A real ``AudioService`` on
``FakeMixer`` sees every raw event first (``handle_raw``); focus and minimize events pass
through it to the App. The device half of AC-49 is ``tests/audio/mixer/test_background.py``."""

import pygame
import pytest

from engine.app.story import install_audio
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from engine.runtime.commands import PlayMusic
from tests.fakes.fake_mixer import FakeMixer, ogg_bytes
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

SIZES = [(1280, 720), (1920, 1080), (1920, 1200), (2560, 1080), (1024, 768), (640, 360)]
CHANGES = ("pause_all", "resume_all", "music_start", "music_stop", "music_fadeout",
           "channel_play", "channel_stop")


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def audio_app(tmp_path, cfg: AudioConfig | None = None):
    (tmp_path / "audio" / "bgm").mkdir(parents=True)
    data = ogg_bytes(600.0)
    (tmp_path / "audio" / "bgm" / "a.ogg").write_bytes(data)
    window = FakeWindow((1280, 720))
    app, limiter = make_app(window)
    mixer = FakeMixer(clock=app.clock)
    mixer.register(data, "bgm/a.ogg", 600.0)
    app.audio = AudioService(GamePaths(tmp_path.resolve()), SizedLru(1 << 20),
                             cfg or AudioConfig(), backend=mixer, clock=app.clock)
    install_audio(app)
    app.router.dispatch(PlayMusic("bgm/a.ogg", True, 100, None, None, False, None, False))
    return app, limiter, window, mixer


def post(kind: int) -> None:
    pygame.event.post(pygame.event.Event(kind))


def test_ac_f08_49_toggles_resizes_and_focus_change_nothing(tmp_path):
    """Minimize with the defaults: ``tests/audio/test_background.py`` and the mixer test."""
    app, limiter, window, mixer = audio_app(tmp_path)
    started = len(mixer.actions())
    frame = 2
    for i in range(100):
        limiter.at(frame, lambda: post_key(pygame.K_F11))
        frame += 1
        limiter.at(frame, lambda s=SIZES[i % 6]: window.resize(*s))
        frame += 1
    limiter.at(frame, lambda: post(pygame.WINDOWFOCUSLOST))
    limiter.at(frame + 2, lambda: post(pygame.WINDOWFOCUSGAINED))
    limiter.quit_at(frame + 4)
    positions = []
    real_update = app.audio.update

    def update(now):
        real_update(now)
        positions.append(app.audio.music.position(app.audio.now()))

    app.audio.update = update
    assert app.run() == 0
    assert window.calls.count("set_fullscreen") == 50
    assert [c for c in mixer.actions()[started:] if c[1] in CHANGES] == []
    assert mixer.music_name() == "bgm/a.ogg"
    assert positions == sorted(positions)                   # never backwards
    assert not app.audio.paused and app.focused


def test_ac_f08_50_play_unfocused_off_pauses_through_the_app(tmp_path):
    app, limiter, window, mixer = audio_app(tmp_path, AudioConfig(play_unfocused=False))
    limiter.at(2, lambda: post(pygame.WINDOWFOCUSLOST))
    limiter.at(4, lambda: post(pygame.WINDOWFOCUSGAINED))
    limiter.quit_at(5)
    seen = []
    limiter.at(3, lambda: seen.append((app.audio.paused, app.focused)))
    assert app.run() == 0
    assert seen == [(True, False)]                          # the App saw the event too
    assert [c[1] for c in mixer.actions("pause_all", "resume_all")] == ["pause_all",
                                                                       "resume_all"]
    assert not app.audio.paused and app.focused
