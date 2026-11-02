"""The mixer backend: W30 and ``NullMixer`` at open, ``PygameMixer`` on SDL's dummy driver,
and the AST half of TR-F08-04 / AC-F08-36 (F08 ``04`` §5.2, §8)."""

import ast
import functools
import logging
import os
from pathlib import Path

import pygame
import pytest

from engine.app.dispatch import CommandRouter
from engine.app.story import AUDIO_COMMANDS
from engine.audio import backend as backend_mod
from engine.audio.backend import (W30_NO_DEVICE, DecodeError, NullMixer, NullSound,
                                  PygameMixer, open_backend)
from engine.audio.limits import MIXER_CHANNELS
from engine.audio.service import AudioService
from engine.audio.sniff import Sniffed, sniff
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from tests.fakes.fake_mixer import FakeMixer, ogg_bytes, wav_bytes

ENGINE = Path(__file__).resolve().parents[2] / "engine"
MIXER_MODULES = {"audio/backend.py", "audio/loader.py"}       # loader: F08 step 9


def no_device(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise pygame.error("No such audio device")

    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    monkeypatch.setattr(pygame.mixer, "init", refuse)


def test_no_device_gives_null_mixer_and_one_w30(monkeypatch, caplog):
    no_device(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        backend = open_backend()
    assert isinstance(backend, NullMixer)
    records = [r for r in caplog.records if r.name == "vn.audio"]
    assert [(r.levelno, r.getMessage(), r.code) for r in records] == [
        (logging.WARNING, W30_NO_DEVICE, "W30")]
    assert W30_NO_DEVICE == "No sound device could be opened, so the game runs without sound."


def test_the_service_opens_the_backend_itself(monkeypatch, caplog):
    no_device(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        service = AudioService(None, SizedLru(1 << 20), AudioConfig())
    assert isinstance(service.backend, NullMixer)
    assert sum(r.name == "vn.audio" for r in caplog.records) == 1


def test_null_mixer_plays_nothing_and_nothing_is_busy():
    null = NullMixer()
    sniffed = sniff(ogg_bytes(1.0), ".ogg")
    sound = null.decode(sniffed)
    assert isinstance(sound, NullSound) and null.sound_seconds(sound) == 0.0
    null.channel_play(5, sound, -1)
    null.channel_volume(5, 0.5)
    assert not any(null.channel_busy(c) for c in range(MIXER_CHANNELS))
    null.pause_all(), null.resume_all(), null.channel_stop(5), null.shutdown()
    with pytest.raises(TypeError):
        null.decode(b"OggS")                                   # only sniffed bytes


def test_a_service_on_null_mixer_runs_the_story_silently(tmp_path):
    from engine.core.paths import GamePaths
    from engine.runtime.commands import PlaySound, StopSound

    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "rain.ogg").write_bytes(ogg_bytes(2.0))
    service = AudioService(GamePaths(tmp_path.resolve()), SizedLru(1 << 20), AudioConfig(),
                           backend=NullMixer())
    router = CommandRouter()
    service.register(router)
    router.dispatch(PlaySound("rain.ogg", True, 100, None))
    service.update(1.0)
    router.dispatch(StopSound(None, 1.0))
    service.stop_story_audio()
    service.shutdown()
    assert not service.effects.slots


def test_register_covers_the_nine_audio_commands():
    router = CommandRouter()
    AudioService(None, SizedLru(1 << 20), AudioConfig(), backend=FakeMixer()).register(router)
    assert set(router._handlers) == set(AUDIO_COMMANDS)
    assert len(AUDIO_COMMANDS) == 9


def test_without_files_music_and_voice_are_silent():
    """No game folder: every file is missing (W26, silence). Music makes no backend call;
    a ``PlayVoice`` only stops channel 0 (AC-F08-28), and ``EndVoice``/``StopVoice`` with
    no voice playing make none."""
    from engine.runtime.audio import AudioState
    from engine.runtime.commands import (AudioRestore, EndVoice, PlayMusic, PlayVoice,
                                         QueueMusic, StopMusic, StopVoice)

    mixer = FakeMixer()
    service = AudioService(None, SizedLru(1 << 20), AudioConfig(), backend=mixer)
    router = CommandRouter()
    service.register(router)
    for command in (PlayMusic("bgm/a.ogg", True, 100, None, None, False, None, False),
                    QueueMusic("bgm/b.ogg", True, 100, None), StopMusic(None),
                    PlayVoice("s1", "voice/a.ogg", False), EndVoice("s1"), StopVoice(None),
                    AudioRestore(AudioState(), "new_game")):
        router.dispatch(command)
    assert mixer.calls == [(0.0, "channel_stop", (0,))]


@pytest.mark.skipif(os.environ.get("SDL_AUDIODRIVER") != "dummy",
                    reason="needs SDL's dummy audio driver (tests/conftest.py)")
def test_pygame_mixer_on_the_dummy_driver():
    backend = PygameMixer()
    try:
        assert pygame.mixer.get_init() == (48_000, -16, 2)
        assert pygame.mixer.get_num_channels() == MIXER_CHANNELS
        sound = backend.decode(sniff(wav_bytes(1.0, rate=48_000), ".wav"))
        assert backend.sound_seconds(sound) == pytest.approx(1.0, abs=0.01)
        backend.channel_volume(7, 0.25)
        backend.channel_play(7, sound, 0)
        assert backend.channel_busy(7)
        assert pygame.mixer.Channel(7).get_volume() == pytest.approx(0.25, abs=1 / 128)
        assert not backend.channel_busy(6)
        backend.channel_stop(7)
        assert not backend.channel_busy(7)
        with pytest.raises(DecodeError):
            backend.decode(sniff(ogg_bytes(1.0), ".ogg"))     # headers only: SDL refuses
    finally:
        backend.shutdown()
    assert not pygame.mixer.get_init()
    backend.shutdown()                                         # twice is harmless


# --- TR-F08-04, AST half -----------------------------------------------------------------------

@functools.cache
def _engine_sources() -> tuple[tuple[str, ast.AST], ...]:
    """Every engine module that mentions ``mixer`` (no other can reach ``pygame.mixer``),
    parsed once for both AST tests."""
    sources = ((path.relative_to(ENGINE).as_posix(), path.read_text(encoding="utf-8"))
               for path in sorted(ENGINE.rglob("*.py")))
    return tuple((rel, ast.parse(text)) for rel, text in sources if "mixer" in text)


def _dotted(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_only_the_backend_touches_pygame_mixer():
    offenders = []
    for rel, tree in _engine_sources():
        if rel in MIXER_MODULES:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and _dotted(node).startswith("pygame.mixer"):
                offenders.append(f"{rel}:{node.lineno}")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names]
                module = getattr(node, "module", None) or ""
                if module.startswith("pygame.mixer") or any(
                        n.startswith("pygame.mixer") or (module == "pygame" and n == "mixer")
                        for n in names):
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == []


def test_sdl_gets_only_bytes_io():
    """Every ``pygame.mixer.Sound(…)`` in the backend takes ``io.BytesIO(…)``, and
    ``decode`` takes a ``Sniffed`` (checked at run time above). The one exception is
    ``sound_tail`` (step 10): ``Sound(buffer=…)`` of samples SDL already decoded, which
    reaches no decoder."""
    calls = []
    for rel, tree in _engine_sources():
        if rel not in MIXER_MODULES:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _dotted(node.func).endswith("mixer.Sound"):
                if not node.args and [k.arg for k in node.keywords] == ["buffer"]:
                    continue                                  # raw samples: no decoder
                calls.append(node)
                assert len(node.args) == 1 and not node.keywords, rel
                arg = node.args[0]
                assert isinstance(arg, ast.Call) and _dotted(arg.func) == "io.BytesIO", rel
    assert calls, "the backend decodes with pygame.mixer.Sound"
    assert backend_mod.PygameMixer.decode.__annotations__["sniffed"] is Sniffed
