"""F08 step 6 in the App: voice from the script (``04`` §6.3, §7.2 voice; AC-F08-28's pause
menu bullet). Launches use ``scripted_app``, whose session gives every launch a ``FakeMixer``
(no test opens a sound device)."""

from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.app.story import install_audio
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from engine.runtime.commands import PlayVoice
from tests.app.test_music_app import Overlay
from tests.fakes.fake_mixer import FakeMixer, ogg_bytes
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def channel_0(mixer: FakeMixer) -> list[tuple]:
    """The channel-0 stops and plays, as ``(name, *args)``."""
    return [(name, *args) for _, name, args in mixer.actions("channel_stop", "channel_play")
            if args[0] == 0]


def test_ac_f08_28_a_screen_pushed_over_the_story_doesnt_stop_the_voice(tmp_path):
    voice = tmp_path / "audio" / "voice" / "hana_014.ogg"
    voice.parent.mkdir(parents=True)
    voice.write_bytes(ogg_bytes(30.0))
    app, limiter = make_app(FakeWindow())
    mixer = FakeMixer(clock=app.clock)
    mixer.register(voice.read_bytes(), "voice/hana_014.ogg", 30.0)
    app.audio = AudioService(GamePaths(tmp_path.resolve()), SizedLru(1 << 20), AudioConfig(),
                             backend=mixer, clock=app.clock)
    install_audio(app)
    app.router.dispatch(PlayVoice("s1", "voice/hana_014.ogg", False))
    limiter.quit_at(2)
    app.run()
    before = mixer.actions()
    overlay = Overlay()
    app.screens.push(overlay)                  # a pause menu stand-in
    app.screens.remove(overlay)
    assert mixer.actions() == before
    assert channel_0(mixer) == [("channel_stop", 0), ("channel_play", 0, "voice/hana_014.ogg", 0)]


def make_game(root: Path) -> Path:
    (root / "script").mkdir(parents=True)
    (root / "config.toml").write_text('[game]\nid = "f08-step6"\n\n[title]\nenabled = false\n'
                                      '\n[textbox]\ncps = 0\n', encoding="utf-8")
    (root / "script" / "main.vns").write_text(
        'label start:\n'
        '    voice "voice/one.ogg"\n'
        '    "One."\n'
        '    voice "voice/two.ogg"\n'
        '    "Two."\n'
        '    return\n', encoding="utf-8")
    for file in ("voice/one.ogg", "voice/two.ogg"):
        path = root / "audio" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(ogg_bytes(30.0, salt=file.encode()))
    return root


def test_a_launch_plays_each_lines_voice_and_an_advance_stops_it(tmp_path, scripted_app,
                                                               user_roots):
    """``voice`` above a line: its voice starts when the line appears (``PlayVoice``), the
    player's advance stops it (``EndVoice``), and the next line's voice plays."""
    game = make_game(tmp_path / "game")
    seen: list[tuple[bool, bool]] = []
    scripted_app.at(8, lambda app: seen.append((app.audio.voice_playing(),
                                                app.audio.voice.sid is not None)))
    scripted_app.at(10, lambda app: post_key(pygame.K_SPACE))
    scripted_app.at(13, lambda app: seen.append((app.audio.voice_playing(),
                                                 app.audio.voice.sid is not None)))
    scripted_app.quit_frame = 15
    assert bootstrap.launch(game, release=True, bench_seconds=None, log_level_override=None,
                            pygame_warning=None) == 0
    mixer = scripted_app.mixers[-1]
    calls = channel_0(mixer)
    assert [c[0] for c in calls] == ["channel_stop", "channel_play", "channel_stop",
                                     "channel_stop", "channel_play"], calls
    first, second = calls[1], calls[4]
    assert first[3] == second[3] == 0 and first[2] != second[2]
    assert seen == [(True, True), (True, True)]
    assert mixer.closed
