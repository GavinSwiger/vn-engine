"""F08 step 11 — device loss and mono on Service S (``04-technical.md`` §7.9; R3, R5; ``07``
I-5, I-13(e)): AC-F08-42 (the debounced reopen, the rebuild, a stale decode, the reopen that
fails and its retry on ``ADDED``), the unit half of AC-F08-54 (``set_mono``), and AC-F08-40
over the session's run messages W26–W31. The backend half (``device_change``,
``PygameMixer.reopen`` on SDL's dummy driver) is at the end; AC-F08-54 on the real mixer is
``tests/audio/mixer/test_mono.py``.

Device events are real ``pygame.event.Event`` objects; the FakeMixer's ``reopen`` loses
everything it played, as SDL does, and ``fail_reopen`` makes it raise ``DeviceError``.
"""

import getpass
import logging
import os
import threading

import pygame
import pytest

from engine.audio.backend import (W30_NO_DEVICE, W30_STOPPED, DeviceError, NullMixer,
                                  PygameMixer, device_change, open_backend)
from engine.audio.limits import EFFECT_CHANNELS, MIXER_CHANNELS, VOICE_CHANNEL
from engine.audio.loader import sound_key
from engine.audio.music import Phase
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.runtime.audio import AudioState, MusicEntry, SoundLoop
from engine.runtime.commands import (AudioRestore, PlayMusic, PlaySound, PlayVoice, StopMusic,
                                     StopSound)
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import ogg_bytes
from tests.fakes.privacy import check_p
from tests.fixtures.F08 import make_audio as fx

AUDIO_LOG = "vn.audio"
WAIT_S = 5.0                                     # the longest any bounded wait may take
FESTIVAL, OMEN, SHRINE = "bgm/festival.ogg", "bgm/omen.ogg", "bgm/shrine_steps.ogg"
RAIN, CROWD, DOOR = "sfx/rain.ogg", "sfx/crowd.ogg", "sfx/door.ogg"
V14 = "voice/hana_014.ogg"
DEVICE_NAME = "ZZMARK Speakers"


def PM(file: str, *, loop: bool = True, fadeout: float | None = None) -> PlayMusic:
    return PlayMusic(file, loop, 100, None, fadeout, False, None, False)


def loop(file: str, volume: int = 100) -> PlaySound:
    return PlaySound(file, True, volume, None)


def shot(file: str) -> PlaySound:
    return PlaySound(file, False, 100, None)


def removed(*, capture: int = 0) -> pygame.event.Event:
    return pygame.event.Event(pygame.AUDIODEVICEREMOVED, which=1, iscapture=capture,
                              name=DEVICE_NAME)


def added(*, capture: int = 0) -> pygame.event.Event:
    return pygame.event.Event(pygame.AUDIODEVICEADDED, which=2, iscapture=capture,
                              name=DEVICE_NAME)


def reopens(s) -> list[tuple[float, int]]:
    return [(round(t, 6), args[0]) for t, _, args in s.mixer.actions("reopen")]


def after_reopen(s, *names: str) -> list[tuple]:
    """The FakeMixer's actions since its last ``reopen`` (only ``names``, when given)."""
    calls = s.mixer.actions()
    last = max(i for i, call in enumerate(calls) if call[1] == "reopen")
    return [c for c in calls[last + 1:] if not names or c[1] in names]


def plays(calls: list[tuple]) -> list[tuple[int, str, int]]:
    return [args for _, name, args in calls if name == "channel_play"]


def audio_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == AUDIO_LOG]


def scene(tmp_path, **kwargs):
    """AC-42's Given: festival at pos 4.0 s, rain looping, a one-shot (crowd), and a voice."""
    s = make_service(tmp_path, **kwargs)
    s.feed(PM(FESTIVAL))
    s.run(4.0, step=0.5)
    s.feed(loop(RAIN, 70), shot(CROWD), PlayVoice("s1", V14, False))
    assert s.service.music.position(s.service.now()) == pytest.approx(4.0)
    assert s.mixer.name_on(VOICE_CHANNEL) == V14
    return s


# --- AC-F08-42: the debounce ------------------------------------------------------------------

def test_ac_f08_42_the_reopen_comes_0_5_s_after_the_event(tmp_path):
    s = scene(tmp_path)
    t = s.clock()
    assert s.service.handle_event(removed()) is True             # consumed
    s.advance(0.49)
    assert reopens(s) == []
    s.advance(0.01)
    assert reopens(s) == [(round(t + 0.5, 6), 2)]
    s.run(1.0, step=0.1)
    assert len(reopens(s)) == 1


def test_ac_f08_42_a_second_event_moves_the_reopen(tmp_path):
    s = scene(tmp_path)
    t = s.clock()
    s.service.handle_event(removed())
    s.advance(0.3)
    s.service.handle_event(added())
    s.advance(0.4)
    assert reopens(s) == []                                      # t + 0.7
    s.advance(0.1)
    assert reopens(s) == [(round(t + 0.8, 6), 2)]


def test_ac_f08_42_capture_device_events_are_ignored(tmp_path):
    s = scene(tmp_path)
    assert s.service.handle_event(removed(capture=1)) is True
    assert s.service.handle_event(added(capture=1)) is True
    s.run(1.0, step=0.1)
    assert reopens(s) == []
    assert s.mixer.name_on(VOICE_CHANNEL) == V14                  # nothing was touched


def test_other_events_are_not_the_services():
    assert device_change(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a)) is None
    assert device_change(object()) is None
    assert device_change(added()) == ("added", False)
    assert device_change(removed(capture=1)) == ("removed", True)


# --- AC-F08-42: after the reopen --------------------------------------------------------------

def test_ac_f08_42_music_and_loops_restart_one_shots_and_voice_dont(tmp_path):
    s = scene(tmp_path)
    service = s.service
    rain_level = s.mixer.volumes[EFFECT_CHANNELS[0]]
    s.mixer.volumes.clear()
    s.service.handle_event(removed())
    s.advance(0.5)
    calls = after_reopen(s)
    starts = [args for _, name, args in calls if name == "music_start"]
    assert len(starts) == 1
    file, loops, start, fade_ms = starts[0]
    assert (file, loops, fade_ms) == (FESTIVAL, -1, 0)
    assert start == pytest.approx(4.5, abs=0.05)
    assert plays(calls) == [(EFFECT_CHANNELS[0], RAIN, -1)]       # not crowd, not the voice
    assert s.mixer.volumes[EFFECT_CHANNELS[0]] == rain_level             # sent again
    assert not service.voice_playing() and service.voice.slot is None
    assert list(service.effects.slots) == [EFFECT_CHANNELS[0]]
    assert service.loader.mixer_gen == 1
    # The ("snd", …) entries are gone: rain was decoded again for the new mixer.
    assert s.cache.keys() == [sound_key(RAIN)]
    assert s.mixer.decoded.count(RAIN) == 2
    s.advance(1.0)
    assert service.music.position(service.now()) == pytest.approx(5.5, abs=0.05)
    assert s.mixer.music_name() == FESTIVAL


def test_a_fade_out_under_way_ends_at_the_reopen(tmp_path):
    s = make_service(tmp_path)
    s.feed(PM(FESTIVAL))
    s.run(1.0, step=0.5)
    s.feed(PM(OMEN, fadeout=2.0))
    s.service.handle_event(removed())
    s.advance(0.5)
    starts = [args[:3] for _, name, args in after_reopen(s) if name == "music_start"]
    assert starts == [(OMEN, -1, 0.0)]
    assert s.service.music.phase is Phase.PLAYING


def test_a_stopped_track_stays_stopped(tmp_path):
    s = make_service(tmp_path)
    s.feed(PM(FESTIVAL), StopMusic(0.0), loop(RAIN), StopSound(RAIN, 0.0))
    s.service.handle_event(removed())
    s.advance(0.5)
    assert after_reopen(s) == []


def test_a_paused_service_is_paused_again_after_the_reopen(tmp_path):
    s = scene(tmp_path)
    s.service.set_background(False, True)
    s.service.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    assert s.service.paused
    s.service.handle_event(removed())
    s.advance(0.5)
    names = [name for _, name, _ in after_reopen(s)]
    assert "music_start" in names and names[-1] == "pause_all"


def test_ac_f08_42_a_decode_from_before_the_reopen_never_plays(tmp_path):
    """R3 and I-13(e): the reopen waits for the decode holding the loader's lock, and the
    decode's result (the old mixer's generation) is dropped by ``update`` on the main
    thread."""
    s = make_service(tmp_path, threaded=True)
    entered, release = threading.Event(), threading.Event()

    def gate(name: str) -> None:
        if name == CROWD:
            entered.set()
            assert release.wait(WAIT_S), "the test never opened the gate"

    s.mixer.decode_hook = gate
    try:
        s.feed(shot(CROWD))
        assert entered.wait(WAIT_S)
        s.service.handle_event(removed())
        s.advance(0.5)                       # due, but the worker holds the lock (0.1 s wait)
        assert reopens(s) == []
        release.set()
        assert s.service.loader.wait(WAIT_S)                    # decoded for the old mixer
        s.advance(0.01)
        assert len(reopens(s)) == 1
        assert plays(s.mixer.actions()) == []
        assert not s.service.effects.active
        assert sound_key(CROWD) not in s.cache
        main = threading.main_thread().name
        assert {thread for name, thread in s.mixer.threads if name == "reopen"} == {main}
    finally:
        release.set()
        s.service.shutdown()


# --- AC-F08-42: the reopen fails --------------------------------------------------------------

def test_ac_f08_42_a_failed_reopen_is_null_mixer_and_one_w30(tmp_path, caplog):
    s = scene(tmp_path)
    service = s.service
    s.mixer.fail_reopen = True
    with caplog.at_level(logging.DEBUG, logger=AUDIO_LOG):
        service.handle_event(removed())
        s.advance(0.5)
        assert isinstance(service.backend, NullMixer) and service.device_lost
        assert isinstance(service.music.backend, NullMixer)
        # Story commands keep updating the model; nothing plays and nothing is "damaged".
        s.feed(PM(OMEN, loop=False), loop(CROWD, 40), StopSound(RAIN, 0.0),
               PlayVoice("s2", V14, False))
        s.run(4.0, step=0.1)
        s.feed(PM(SHRINE))
        assert service.story_music == (MusicEntry(SHRINE, True, 100),)
        assert service.story_sounds == {CROWD: 40}
        # REMOVED no longer schedules; ADDED retries, and a failed retry logs nothing new.
        service.handle_event(removed())
        s.advance(1.0)
        assert len(reopens(s)) == 1
        service.handle_event(added())
        s.advance(0.5)
        assert len(reopens(s)) == 2 and service.device_lost
    records = audio_records(caplog)
    assert [(r.levelno, r.getMessage(), r.code) for r in records] == [
        (logging.WARNING, W30_STOPPED, "W30")]
    assert W30_STOPPED == ("The sound device stopped working, so the game continues without "
                           "sound.")


def test_ac_f08_42_on_added_the_music_resumes_from_the_model(tmp_path):
    s = scene(tmp_path)
    service = s.service
    s.mixer.fail_reopen = True
    service.handle_event(removed())
    s.advance(0.5)
    s.feed(PM(SHRINE), loop(CROWD, 40))
    s.run(1.0, step=0.1)
    s.mixer.fail_reopen = False
    service.handle_event(added())
    s.advance(0.5)
    assert not service.device_lost and service.backend is s.mixer
    calls = after_reopen(s)
    starts = [args for _, name, args in calls if name == "music_start"]
    assert starts == [(SHRINE, -1, 0.0, round(service.cfg.restore_fadein * 1000))]
    assert sorted(plays(calls)) == [(EFFECT_CHANNELS[0], RAIN, -1),
                                    (EFFECT_CHANNELS[1], CROWD, -1)]
    s.run(1.0, step=0.1)
    assert s.mixer.music_name() == SHRINE


def test_a_holders_looping_track_resumes_after_a_loss(tmp_path):
    s = make_service(tmp_path)
    service = s.service
    s.feed(PM(FESTIVAL))
    handle = service.take_music("title")
    s.run(1.0, step=0.1)
    handle.play(OMEN, fadeout=0.0)
    s.mixer.fail_reopen = True
    service.handle_event(removed())
    s.advance(0.5)
    s.mixer.fail_reopen = False
    service.handle_event(added())
    s.advance(0.5)
    starts = [args[:3] for _, name, args in after_reopen(s) if name == "music_start"]
    assert starts == [(OMEN, -1, 0.0)]


def test_a_restore_while_lost_is_what_comes_back(tmp_path):
    s = scene(tmp_path)
    service = s.service
    s.mixer.fail_reopen = True
    service.handle_event(removed())
    s.advance(0.5)
    s.feed(AudioRestore(AudioState((MusicEntry(OMEN, True, 80),), (SoundLoop(DOOR, 60),)),
                        "restore"))
    s.mixer.fail_reopen = False
    service.handle_event(added())
    s.advance(0.5)
    calls = after_reopen(s)
    assert [args[0] for _, name, args in calls if name == "music_start"] == [OMEN]
    assert plays(calls) == [(EFFECT_CHANNELS[0], DOOR, -1)]


def without_a_device(tmp_path):
    """Service S as a game that started with no device (``NullMixer``, the start's W30):
    ``open_device`` hands out the FakeMixer, or ``DeviceError`` while ``fail_reopen``;
    ``opened`` lists the channel counts it was asked for."""
    from engine.app.dispatch import CommandRouter
    from engine.core.paths import GamePaths

    s = make_service(tmp_path)
    opened: list[int] = []

    def open_device(channels: int):
        opened.append(channels)
        if s.mixer.fail_reopen:
            raise DeviceError("no device")
        return s.mixer

    s.service = AudioService(GamePaths(s.root.resolve()), s.cache, AudioConfig(),
                             backend=NullMixer(), clock=s.clock, frame=lambda: s.frame,
                             open_device=open_device)
    s.router = CommandRouter()
    s.service.register(s.router)
    return s, opened


def test_a_device_plugged_in_later_opens_debounced_and_plays_the_story(tmp_path, caplog):
    """Step 12 (main's decision at step 11): a game that started without a device opens one
    on ``ADDED``, 0.5 s after the last event, and plays the story's looping music (restore
    fade-in) and loops; one-shots and the voice are gone. ``REMOVED`` and capture events
    schedule nothing."""
    s, opened = without_a_device(tmp_path)
    service = s.service
    s.feed(PM(FESTIVAL), loop(RAIN, 70), shot(CROWD), PlayVoice("s1", V14, False))
    s.run(1.0, step=0.1)
    assert s.mixer.actions() == [] and not service.voice_playing()
    with caplog.at_level(logging.DEBUG, logger=AUDIO_LOG):
        service.handle_event(removed())
        service.handle_event(added(capture=1))
        s.advance(1.0)
        assert opened == []
        assert service.handle_event(added()) is True
        s.advance(0.3)
        service.handle_event(added())                       # moves the open to +0.5 again
        s.advance(0.3)
        assert opened == []
        s.advance(0.2)
    assert opened == [2] and service.backend is s.mixer and not service.device_lost
    assert audio_records(caplog) == []
    assert [args for _, name, args in s.mixer.actions("music_start")] == [
        (FESTIVAL, -1, 0.0, round(service.cfg.restore_fadein * 1000))]
    assert plays(s.mixer.actions()) == [(EFFECT_CHANNELS[0], RAIN, -1)]
    assert not service.voice_playing()
    s.feed(shot(CROWD), PlayVoice("s2", V14, False))      # the device plays from now on
    assert s.mixer.name_on(VOICE_CHANNEL) == V14
    service.handle_event(removed())                          # and can be lost like any other
    s.advance(0.5)
    assert reopens(s) == [(round(s.clock(), 6), 2)]


def test_no_device_plugged_in_later_stays_silent_with_no_second_w30(tmp_path, caplog):
    s, opened = without_a_device(tmp_path)
    service = s.service
    s.mixer.fail_reopen = True
    service.set_mono(True)                                   # applies at the open
    s.feed(PM(FESTIVAL))
    with caplog.at_level(logging.DEBUG, logger=AUDIO_LOG):
        service.handle_event(added())
        s.advance(0.5)
        assert opened == [1] and isinstance(service.backend, NullMixer)
        assert not service.device_lost
        service.handle_event(added())                        # each ADDED tries again
        s.advance(0.5)
    assert opened == [1, 1] and audio_records(caplog) == []
    s.mixer.fail_reopen = False
    service.handle_event(added())
    s.advance(0.5)
    assert opened == [1, 1, 1] and service.backend is s.mixer
    assert [args[0] for _, name, args in s.mixer.actions("music_start")] == [FESTIVAL]


def test_after_shutdown_device_events_do_nothing(tmp_path):
    s = scene(tmp_path)
    s.service.shutdown()
    assert s.service.handle_event(removed()) is True
    s.service.update(s.clock() + 1.0)
    s.service.set_mono(True)
    assert reopens(s) == []


# --- AC-F08-54, unit half: set_mono -----------------------------------------------------------

def test_set_mono_reopens_with_one_channel_at_once(tmp_path):
    s = scene(tmp_path)
    service = s.service
    service.set_mono(True)
    assert reopens(s) == [(round(s.clock(), 6), 1)] and s.mixer.channels == 1
    calls = after_reopen(s)
    start = [args for _, name, args in calls if name == "music_start"][0]
    assert start[:2] == (FESTIVAL, -1) and start[2] == pytest.approx(4.0, abs=0.05)
    assert plays(calls) == [(EFFECT_CHANNELS[0], RAIN, -1)]
    service.set_mono(True)                                      # no change: no reopen
    assert len(reopens(s)) == 1
    service.set_mono(False)
    assert reopens(s)[-1][1] == 2 and s.mixer.channels == 2


def test_set_mono_while_lost_applies_at_the_next_reopen(tmp_path):
    s = scene(tmp_path)
    s.mixer.fail_reopen = True
    s.service.handle_event(removed())
    s.advance(0.5)
    s.service.set_mono(True)
    assert len(reopens(s)) == 1
    s.mixer.fail_reopen = False
    s.service.handle_event(added())
    s.advance(0.5)
    assert reopens(s)[-1][1] == 1 and s.mixer.channels == 1


def test_a_device_reopen_keeps_mono(tmp_path):
    s = scene(tmp_path)
    s.service.set_mono(True)
    s.service.handle_event(removed())
    s.advance(0.5)
    assert [channels for _, channels in reopens(s)] == [1, 1]


# --- AC-F08-40: the run messages, once per path, no identity ----------------------------------

def test_ac_f08_40_run_messages_are_in_vn_audio_with_no_identity(tmp_path, monkeypatch,
                                                                  caplog):
    """W26–W31 from one session whose game folder is under a folder named after the user,
    and a device named ``ZZMARK Speakers``: every record is in ``vn.audio``, check P
    passes over them all, and the device name never appears."""
    home = tmp_path / getpass.getuser()
    home.mkdir()
    long_file, full_file = "bgm/long.ogg", "bgm/full.ogg"
    caplog.set_level(logging.DEBUG)
    s = make_service(home, AudioConfig(loop_start={long_file: 95.0, full_file: 0.5}))
    s.add("broken/truncated.ogg", ogg_bytes(12.0, salt=b"cut"), 7.2)
    s.add(long_file, fx.long_72s(), 72.06)
    s.add(full_file, fx.tagfull(), 1.632)
    s.feed(shot("sfx/nothing.ogg"),                                          # W26
           PM(long_file), PM(full_file, fadeout=0.0),                         # W28, W31
           PM("broken/truncated.ogg", loop=False, fadeout=0.0))
    s.run(7.5, step=0.1)                                                       # W27
    s.feed(AudioRestore(AudioState((MusicEntry("bgm/gone.ogg", True, 100),), ()),
                        "restore"))                                            # W29
    s.mixer.fail_reopen = True
    s.service.handle_event(removed())
    s.advance(0.5)                                                             # W30 stopped

    def refuse(*args, **kwargs):
        raise pygame.error(f"{DEVICE_NAME} could not be opened")

    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    monkeypatch.setattr(pygame.mixer, "init", refuse)
    assert isinstance(open_backend(), NullMixer)                               # W30 no device
    codes = {r.code: r.name for r in caplog.records if getattr(r, "code", None)}
    assert {code: codes.get(code) for code in ("W26", "W27", "W28", "W29", "W30", "W31")} \
        == dict.fromkeys(("W26", "W27", "W28", "W29", "W30", "W31"), AUDIO_LOG)
    messages = [r.getMessage() for r in caplog.records]
    assert W30_STOPPED in messages and W30_NO_DEVICE in messages
    check_p(messages, home=home, game=s.root)
    assert not any(DEVICE_NAME in m for m in messages)


# --- The backend: PygameMixer.reopen on SDL's dummy driver --------------------------------------

def test_null_mixer_never_reopens():
    with pytest.raises(DeviceError):
        NullMixer().reopen(2)
    assert NullMixer.silent and not PygameMixer.silent


@pytest.mark.skipif(os.environ.get("SDL_AUDIODRIVER") != "dummy",
                    reason="needs SDL's dummy audio driver (tests/conftest.py)")
def test_pygame_mixer_reopens_and_clears_its_own_device_events():
    """Every open of the mixer posts one ``AUDIODEVICEADDED`` per device (measured, the
    dummy driver too); left in the queue, each reopen would schedule the next."""
    display_was_up = pygame.display.get_init()
    pygame.display.init()
    backend = PygameMixer()
    try:
        assert pygame.event.get((pygame.AUDIODEVICEADDED, pygame.AUDIODEVICEREMOVED)) == []
        backend.reopen(1)
        assert pygame.mixer.get_init() == (48_000, -16, 1)
        assert pygame.mixer.get_num_channels() == MIXER_CHANNELS
        assert pygame.event.get((pygame.AUDIODEVICEADDED, pygame.AUDIODEVICEREMOVED)) == []
        backend.reopen(2)
        assert pygame.mixer.get_init() == (48_000, -16, 2) and backend.channels == 2
        assert not backend.channel_busy(5) and not backend.music_busy()
    finally:
        backend.shutdown()
        if not display_was_up:
            pygame.display.quit()
    assert not pygame.mixer.get_init()


def test_a_pygame_mixer_reopen_that_fails_is_device_error(monkeypatch):
    if os.environ.get("SDL_AUDIODRIVER") != "dummy":
        pytest.skip("needs SDL's dummy audio driver (tests/conftest.py)")
    backend = PygameMixer()
    try:
        def refuse(*args, **kwargs):
            raise pygame.error("No such audio device")

        with monkeypatch.context() as patch:
            patch.setattr(pygame.mixer, "init", refuse)
            with pytest.raises(DeviceError):
                backend.reopen(2)
        backend.shutdown()                                     # closed already: harmless
        backend.reopen(2)                                      # a retry that works
        assert pygame.mixer.get_init() == (48_000, -16, 2)
    finally:
        backend.shutdown()
