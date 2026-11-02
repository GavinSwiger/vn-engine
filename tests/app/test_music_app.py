"""F08 step 5 in the App: music from the script and F10's title music through ``take_music``
(F08 ``04`` §7.1, §7.10; AC-F08-20's last sentence); the script launch also checks step 4's
``App.audio``, ``install_audio``, and the shutdown hook. Launches use ``scripted_app``, whose
session gives every launch a ``FakeMixer`` (no test opens a sound device)."""

from pathlib import Path

import pygame
import pytest

from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from engine.runtime.commands import PlayMusic, PlaySound
from engine.ui.screen import Screen
from tests.fakes.fake_mixer import FakeMixer, ogg_bytes
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


class Overlay(Screen):
    in_game = True

    def handle_event(self, event):
        return False

    def update(self, dt: float, *, is_top: bool) -> None:
        pass

    def draw(self, canvas) -> None:
        pass


def test_ac_f08_20_pushing_and_popping_a_screen_makes_no_backend_call(tmp_path):
    (tmp_path / "audio" / "bgm").mkdir(parents=True)
    (tmp_path / "audio" / "bgm" / "a.ogg").write_bytes(ogg_bytes(12.0))
    app, limiter = make_app(FakeWindow())
    mixer = FakeMixer(clock=app.clock)
    app.audio = AudioService(GamePaths(tmp_path.resolve()), SizedLru(1 << 20), AudioConfig(),
                             backend=mixer, clock=app.clock)
    from engine.app.story import install_audio

    install_audio(app)
    app.router.dispatch(PlayMusic("bgm/a.ogg", True, 100, 2.0, None, False, None, False))
    limiter.quit_at(2)
    app.run()
    before = mixer.actions()
    overlay = Overlay()
    app.screens.push(overlay)                  # a pause menu stand-in
    app.screens.remove(overlay)
    assert mixer.actions() == before


def make_game(root: Path, script: str, config: str = "[title]\nenabled = false\n") -> Path:
    (root / "script").mkdir(parents=True)
    (root / "config.toml").write_text('[game]\nid = "f08-step5"\n\n' + config, encoding="utf-8")
    (root / "script" / "main.vns").write_text(script, encoding="utf-8")
    for file, seconds in (("bgm/theme.ogg", 8.0), ("bgm/title.ogg", 6.0),
                          ("sfx/chime.ogg", 0.8)):
        path = root / "audio" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ogg_bytes(seconds, salt=file.encode()))
    return root


def launch(scripted_app, game: Path, frames: int = 40):
    """Launch; ``scripted_app.seen`` gets the music player's current track and whether the
    music is taken, two frames before the end (the shutdown hook clears both)."""
    from engine.app import bootstrap

    scripted_app.quit_frame = frames
    scripted_app.seen = []
    scripted_app.at(frames - 2, lambda app: scripted_app.seen.append(
        (app.audio.music.current, app.audio.music_taken())))
    assert bootstrap.launch(game, release=True, bench_seconds=None, log_level_override=None,
                            pygame_warning=None) == 0
    return scripted_app.apps[-1], scripted_app.mixers[-1]


def music_starts(mixer: FakeMixer) -> list[tuple]:
    return [args for _, _, args in mixer.actions("music_start")]


def test_a_launch_plays_music_and_effects_from_the_script(tmp_path, scripted_app, user_roots):
    game = make_game(tmp_path / "game", 'label start:\n'
                                        '    play music "bgm/theme.ogg" fadein 1.0\n'
                                        '    play sound "sfx/chime.ogg"\n'
                                        '    "Hi."\n    return\n')
    app, mixer = launch(scripted_app, game)
    assert isinstance(app.audio, AudioService) and isinstance(app.audio.backend, FakeMixer)
    assert app.router._handlers[PlaySound].__self__ is app.audio   # install_audio
    (start,) = music_starts(mixer)
    name, loops, offset, fade_ms = start
    assert name.startswith("sha:") or name == "bgm/theme.ogg"
    assert (loops, offset, fade_ms) == (-1, 0.0, 1000)
    ((current, taken),) = scripted_app.seen
    assert current.file == "bgm/theme.ogg" and current.story and not taken
    (play,) = mixer.actions("channel_play")
    assert play[2][2] == 0                                # the chime plays once
    assert mixer.closed                                   # the shutdown hook ran


def test_title_music_plays_through_take_music(tmp_path, scripted_app, user_roots):
    game = make_game(tmp_path / "game", 'label start:\n    "Hi."\n    return\n',
                     config='[theme.title]\nmusic = "bgm/title.ogg"\n')
    app, mixer = launch(scripted_app, game, frames=20)
    ((current, taken),) = scripted_app.seen
    assert taken and current.file == "bgm/title.ogg" and not current.story
    assert len(music_starts(mixer)) == 1
