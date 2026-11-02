"""F08 step 9 — the decode worker (``SoundLoader``; ``04`` §7.3 with ``07`` I-5; ADR-0007):
AC-F08-27 (an in-flight decode never plays after ``stop sound``), AC-F08-44 (decoded effects
in the cache), AC-F08-51's shutdown and worker-exception halves, and the worker rule: only
``decode`` runs on the worker, everything else in ``update`` on the main thread.

Thread tests never sleep-poll: a decode is held on a ``threading.Event`` (bounded waits) and
results are awaited with ``SoundLoader.wait`` (bounded). Every threaded service is shut down
by the ``threaded`` fixture, so no worker outlives its test.
"""

import logging
import threading
import time

import pygame
import pytest

import engine.audio.loader as loader_mod
from engine.audio.backend import NullMixer
from engine.audio.limits import EFFECT_CHANNELS, VOICE_CHANNEL
from engine.audio.loader import WORKER_NAME, SoundLoader, sound_key
from engine.audio.reading import AudioLog, AudioReader
from engine.core.constants import ENTRY_OVERHEAD, MB
from engine.core.lru import SizedLru
from engine.runtime.audio import AudioState, SoundLoop
from engine.runtime.commands import (AudioRestore, EndVoice, PlayMusic, PlaySound, PlayVoice,
                                     StopSound, StopVoice)
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import FakeMixer, ogg_bytes

AUDIO_LOG = "vn.audio"
WAIT_S = 5.0                       # the longest any bounded wait here may take (a hang)
DOOR, RAIN, CROWD = "sfx/door.ogg", "sfx/rain.ogg", "sfx/crowd.ogg"
V14 = "voice/hana_014.ogg"


def one_shot(file: str, volume: int = 100, fadein: float | None = None) -> PlaySound:
    return PlaySound(file, False, volume, fadein)


def loop(file: str, volume: int = 100, fadein: float | None = None) -> PlaySound:
    return PlaySound(file, True, volume, fadein)


def plays(s, channel: int | None = None) -> list[tuple[int, str]]:
    return [(c[2][0], c[2][1]) for c in s.mixer.actions("channel_play")
            if channel is None or c[2][0] == channel]


def audio_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == AUDIO_LOG]


class Gate:
    """Holds the decode of the named files on the worker until ``open()`` (bounded)."""

    def __init__(self, *names: str) -> None:
        self.names = set(names)
        self.entered = threading.Event()
        self.released = threading.Event()

    def __call__(self, name: str) -> None:
        if name in self.names:
            self.entered.set()
            assert self.released.wait(WAIT_S), "the test never opened the gate"

    def open(self) -> None:
        self.released.set()


@pytest.fixture
def threaded(tmp_path):
    """``threaded()``: a Service S whose loader has its worker; shut down afterwards."""
    made = []

    def build(**kwargs):
        s = make_service(tmp_path, threaded=True, **kwargs)
        s.threads = []                                    # every worker the loader started
        submit = s.service.loader._submit

        def tracked(job):
            submit(job)
            worker = s.service.loader.worker
            if worker is not None and worker not in s.threads:
                s.threads.append(worker)

        s.service.loader._submit = tracked
        made.append(s)
        return s

    yield build
    for s in made:
        hook = s.mixer.decode_hook
        if isinstance(hook, Gate):
            hook.open()
        s.service.shutdown()
    for s in made:
        for thread in s.threads:
            thread.join(WAIT_S)
            assert not thread.is_alive()


# --- The worker rule (ADR-0007, I-5) ---------------------------------------------------------

def test_only_decode_runs_on_the_worker(threaded):
    s = threaded()
    s.feed(loop(RAIN, fadein=1.0), one_shot(DOOR), PlayVoice("s1", V14, False))
    s.service.play_ui(CROWD)
    worker = s.service.loader.worker
    assert worker is not None and worker.daemon and worker.name == WORKER_NAME
    s.decoded()
    s.run(0.5)
    by_thread = {(name, thread) for name, thread in s.mixer.threads}
    assert {name for name, thread in by_thread if thread == WORKER_NAME} == {"decode"}
    assert {thread for name, thread in by_thread if name == "decode"} == {WORKER_NAME}
    main = threading.main_thread().name
    assert {thread for name, thread in by_thread if name != "decode"} == {main}
    assert sorted(plays(s)) == [(VOICE_CHANNEL, V14), (2, CROWD), (5, RAIN), (6, DOOR)]


def test_an_uncached_effect_plays_at_the_update_after_its_decode(threaded):
    """§7.3: nothing plays at dispatch; the ``update`` after the decode sets the ramp's
    start (0 for a fade-in), plays, and the ramp's ``t0`` is that moment."""
    s = threaded()
    s.feed(loop(RAIN, volume=100, fadein=1.0))
    assert plays(s) == [] and s.service.effects.active
    s.clock.now += 0.25                                       # the decode took a while
    s.decoded()
    assert plays(s) == [(5, RAIN)]
    slot = s.service.effects.slots[5]
    assert slot.t0 == s.service.now() and slot.gain(s.service.now()) == 0.0
    volume_then_play = [c[1] for c in s.mixer.actions("channel_volume", "channel_play")]
    assert volume_then_play == ["channel_volume", "channel_play"]
    assert s.mixer.volumes[5] == 0.0


def test_a_cache_hit_plays_at_once_without_the_worker(threaded):
    s = threaded()
    s.feed(one_shot(DOOR))
    s.decoded()
    s.feed(one_shot(DOOR))
    assert plays(s) == [(5, DOOR), (6, DOOR)]               # the second in the same call
    assert s.mixer.decoded == [DOOR]


def test_duplicate_files_in_flight_share_one_decode(threaded):
    s = threaded()
    s.feed(one_shot(DOOR), one_shot(DOOR))
    s.service.play_ui(DOOR)
    s.decoded()
    assert s.mixer.decoded == [DOOR]
    assert sorted(plays(s)) == [(2, DOOR), (5, DOOR), (6, DOOR)]
    assert s.cache._holds[sound_key(DOOR)] == 3


def test_a_loop_asked_for_again_while_decoding_starts_once_at_the_last_volume(threaded):
    s = threaded()
    s.feed(loop(RAIN, volume=100), loop(RAIN, volume=50))
    s.decoded()
    assert plays(s) == [(5, RAIN)]
    assert s.service.effects.slots[5].volume == 50


def test_a_sound_that_starts_while_paused_is_paused_again(threaded):
    s = threaded()
    s.service.set_background(unfocused=False, minimized=False)    # pause when unfocused
    s.service.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    assert s.service.paused
    s.feed(one_shot(DOOR))
    s.decoded()
    names = [c[1] for c in s.mixer.actions("channel_play", "pause_all")]
    assert names[-2:] == ["channel_play", "pause_all"]


# --- AC-F08-27 ---------------------------------------------------------------------------------

def test_ac_f08_27_an_in_flight_crowd_never_plays_after_stop_sound(threaded):
    """Crowd loops, a crowd one-shot plays, rain loops, and a crowd decode is in flight
    (the cached crowd was dropped, so the next crowd is decoded again). ``StopSound(crowd,
    1.5)`` ramps both crowd channels to 0 over 1.5 s then stops them (I-13(a)), leaves rain
    alone, and the in-flight crowd never plays."""
    s = threaded()
    s.feed(loop(CROWD), one_shot(CROWD), loop(RAIN))
    s.decoded()
    assert sorted(plays(s)) == [(5, CROWD), (6, CROWD), (7, RAIN)]
    s.cache.discard(sound_key(CROWD))
    gate = Gate(CROWD)
    s.mixer.decode_hook = gate
    s.feed(one_shot(CROWD))
    assert gate.entered.wait(WAIT_S)                          # decoding on the worker now
    before = len(s.mixer.calls)
    s.feed(StopSound(CROWD, 1.5))
    gate.open()
    s.decoded()
    s.run(1.5, step=0.05)
    after = [c for c in s.mixer.calls[before:]
             if c[1] not in ("decode", "channel_busy", "sound_seconds")]
    assert [c for c in after if c[1] == "channel_play"] == []
    assert sorted(c[2][0] for c in after if c[1] == "channel_stop") == [5, 6]
    assert all(c[2][0] in (5, 6) for c in after if c[1] in ("channel_volume", "channel_stop"))
    stops = [c[0] for c in after if c[1] == "channel_stop"]
    assert stops and all(abs(t - (100.0 + 1.5)) <= 0.05 + 1e-9 for t in stops)
    assert s.mixer.name_on(7) == RAIN
    s.feed(StopSound("sfx/door.ogg", None))
    assert s.mixer.calls[-1][1] != "channel_stop"


def test_stop_sound_cancels_a_decode_that_has_not_started(threaded):
    s = threaded()
    gate = Gate(DOOR)
    s.mixer.decode_hook = gate
    s.feed(one_shot(DOOR), loop(RAIN))
    assert gate.entered.wait(WAIT_S)
    s.feed(StopSound(None, None))
    assert not s.service.effects.active
    gate.open()
    s.decoded()
    assert plays(s) == [] and s.mixer.actions("channel_stop") == []
    assert sound_key(RAIN) in s.cache and sound_key(DOOR) in s.cache    # still cached
    assert not s.cache._holds


def test_a_restore_keeps_a_decoding_target_loop_and_cancels_the_rest(threaded):
    s = threaded()
    gate = Gate(RAIN, DOOR, CROWD)
    s.mixer.decode_hook = gate
    s.feed(loop(RAIN, volume=40), one_shot(DOOR), loop(CROWD))
    assert gate.entered.wait(WAIT_S)
    state = AudioState(sounds=(SoundLoop(RAIN, 80),))
    s.feed(AudioRestore(state, "restore"))
    gate.open()
    s.decoded()
    assert plays(s) == [(5, RAIN)]
    slot = s.service.effects.slots[5]
    assert slot.volume == 80 and slot.dur == s.service.cfg.restore_fadein


# --- Voice ----------------------------------------------------------------------------------

def test_a_decoding_voice_counts_as_playing_and_end_voice_cancels_it(threaded):
    s = threaded()
    gate = Gate(V14)
    s.mixer.decode_hook = gate
    s.feed(PlayVoice("s1", V14, False))
    assert s.service.voice_playing("s1") and s.service.voice_playing()
    assert not s.service.voice_playing("s2")
    s.feed(EndVoice("s1"))
    assert not s.service.voice_playing()
    gate.open()
    s.decoded()
    assert plays(s, VOICE_CHANNEL) == []
    assert s.mixer.actions("channel_stop") == [(100.0, "channel_stop", (VOICE_CHANNEL,))]


@pytest.mark.parametrize("stop", ["stop_voice", "stop_story_audio", "next_voice"])
def test_a_decoding_voice_never_plays_once_stopped(threaded, stop):
    s = threaded()
    s.add("voice/other.ogg", ogg_bytes(1.0, salt=b"o"), 1.0)
    gate = Gate(V14)
    s.mixer.decode_hook = gate
    s.feed(PlayVoice("s1", V14, False))
    assert gate.entered.wait(WAIT_S)
    if stop == "stop_voice":
        s.feed(StopVoice(0.5))
    elif stop == "stop_story_audio":
        s.service.stop_story_audio(0.5)
    else:
        s.feed(PlayVoice("s2", "voice/other.ogg", False))
    gate.open()
    s.decoded()
    expected = [(VOICE_CHANNEL, "voice/other.ogg")] if stop == "next_voice" else []
    assert plays(s, VOICE_CHANNEL) == expected


# --- AC-F08-44 ----------------------------------------------------------------------------------

def test_ac_f08_44_decoded_effects_in_the_cache(tmp_path):
    s = make_service(tmp_path, cache_bytes=64 * MB)
    door = "sfx/door2.ogg"
    s.add(door, ogg_bytes(2.0, salt=b"door2"), 2.0)
    s.feed(one_shot(door))
    assert s.cache.cost(sound_key(door)) == int(2.0 * 192_000) + ENTRY_OVERHEAD
    s.advance(2.5)
    s.feed(one_shot(door))
    assert s.mixer.decoded == [door]                          # playing it again decodes nothing
    s.feed(StopSound(None, None))
    # Three effects playing, then 80 MB of other entries: none of the three is evicted
    # until its channel frees.
    s.feed(loop(RAIN), loop(CROWD), one_shot(door))
    s.frame += 10
    for index in range(80):
        s.cache.put(("img", index), object(), MB, s.frame)
    assert all(sound_key(f) in s.cache for f in (RAIN, CROWD, door))
    s.feed(StopSound(None, None))
    s.frame += 10
    s.cache.put(("img", "last"), object(), MB, s.frame)
    assert not any(sound_key(f) in s.cache for f in (RAIN, CROWD, door))
    # Music bytes are never in the LRU.
    s.feed(PlayMusic("bgm/festival.ogg", True, 100, None, None, False, None, False))
    s.advance(0.5)
    assert all(key[0] != "snd" or not key[1].startswith("bgm/") for key in s.cache.keys())
    assert [key for key in s.cache.keys() if "bgm/festival.ogg" in str(key)] == []


# --- Failures (W26), stale results, the fallback ------------------------------------------------

def test_a_decode_error_on_the_worker_is_one_w26_and_silence(threaded, caplog):
    s = threaded()
    s.mixer.fail_decode.add(DOOR)
    caplog.set_level(logging.WARNING, logger=AUDIO_LOG)
    s.feed(one_shot(DOOR), one_shot(DOOR))
    s.decoded()
    s.feed(one_shot(DOOR))                                    # not read again
    records = audio_records(caplog)
    assert len(records) == 1 and records[0].code == "W26"
    assert "can't be played: it is damaged" in records[0].getMessage()
    assert plays(s) == [] and s.mixer.decoded == [] and not s.service.effects.active


def test_ac_f08_51_a_worker_exception_is_one_w26_never_raised(threaded, caplog):
    s = threaded()

    def explode(name: str) -> None:
        raise RuntimeError("a bug in the decoder")

    s.mixer.decode_hook = explode
    caplog.set_level(logging.WARNING, logger=AUDIO_LOG)
    s.feed(one_shot(DOOR), PlayVoice("s1", DOOR, False))
    s.decoded()
    records = audio_records(caplog)
    assert len(records) == 1 and records[0].code == "W26"
    assert plays(s) == [] and not s.service.voice_playing()
    worker = s.service.loader.worker
    assert worker is not None and worker.is_alive()           # the worker goes on
    s.mixer.decode_hook = None
    s.feed(one_shot(RAIN))
    s.decoded()
    assert plays(s) == [(5, RAIN)]


def test_ac_f08_51_shutdown_does_not_wait_for_a_blocked_decode(threaded):
    """The worker join times out (here 0.1 s; 1 s by default, the ``slow`` twin below), the
    mixer is not closed under the decode, and the later result never plays."""
    s = threaded()
    gate = Gate(DOOR)
    s.mixer.decode_hook = gate
    s.feed(one_shot(DOOR))
    assert gate.entered.wait(WAIT_S)
    started = time.perf_counter()
    s.service.shutdown(timeout=0.1)
    assert time.perf_counter() - started < 0.5
    assert not s.mixer.closed                                 # the lock was still held
    assert s.service.loader.worker is None
    gate.open()
    s.service.update(s.clock())
    assert plays(s) == []


@pytest.mark.slow
def test_ac_f08_51_shutdown_with_a_3_s_decode_ends_within_1_s(threaded):
    s = threaded()
    entered = threading.Event()
    release = threading.Event()

    def block(name: str) -> None:
        entered.set()
        release.wait(3.0)

    s.mixer.decode_hook = block
    s.feed(one_shot(DOOR))
    assert entered.wait(WAIT_S)
    thread = s.service.loader._thread
    started = time.perf_counter()
    s.service.shutdown()
    elapsed = time.perf_counter() - started
    assert 0.9 <= elapsed <= 1.2
    release.set()
    thread.join(WAIT_S)
    assert not thread.is_alive()


def test_a_result_for_an_older_mixer_is_dropped(threaded):
    """Step 11's reopen bumps ``mixer_gen``: what was decoded for the old mixer neither
    plays nor is cached."""
    s = threaded()
    gate = Gate(DOOR)
    s.mixer.decode_hook = gate
    s.feed(one_shot(DOOR))
    assert gate.entered.wait(WAIT_S)
    s.service.loader.bump_gen()
    gate.open()
    assert s.service.loader.wait(WAIT_S)
    s.service.update(s.clock())
    assert plays(s) == [] and sound_key(DOOR) not in s.cache
    assert not s.service.effects.active


def test_shutdown_cancels_what_is_decoding(threaded):
    s = threaded()
    gate = Gate(DOOR)
    s.mixer.decode_hook = gate
    s.feed(one_shot(DOOR), PlayVoice("s1", V14, False))
    assert gate.entered.wait(WAIT_S)
    gate.open()
    s.service.shutdown()
    assert s.mixer.closed and not s.cache._holds
    s.service.update(s.clock())
    assert plays(s) == []


def test_the_fallback_decodes_in_the_call(tmp_path):
    """Without the worker (``LOADER_THREADED = False``) the same steps run in the call: the
    sound plays when its command arrives, and no thread is started."""
    s = make_service(tmp_path, threaded=False)
    s.feed(one_shot(DOOR), PlayVoice("s1", V14, False))
    assert plays(s) == [(5, DOOR), (VOICE_CHANNEL, V14)]
    assert s.service.loader.worker is None and not s.service.loader.pending
    assert {thread for _, thread in s.mixer.threads} == {threading.main_thread().name}


def test_which_backends_get_a_thread(monkeypatch):
    reader = AudioReader(None, AudioLog())
    cache = SizedLru(MB)
    monkeypatch.setattr(loader_mod, "LOADER_THREADED", True)
    assert SoundLoader(FakeMixer(threaded_decode=True), reader, cache).threaded
    assert not SoundLoader(FakeMixer(), reader, cache).threaded
    assert not SoundLoader(NullMixer(), reader, cache).threaded
    assert SoundLoader(FakeMixer(), reader, cache, threaded=True).threaded
    monkeypatch.setattr(loader_mod, "LOADER_THREADED", False)
    assert not SoundLoader(FakeMixer(threaded_decode=True), reader, cache).threaded


def test_sixteen_effect_channels_still_hold_with_the_worker(threaded):
    s = threaded()
    files = []
    for index in range(17):
        file = f"sfx/s{index:02d}.ogg"
        s.add(file, ogg_bytes(30.0, salt=b"s" + bytes([index])), 30.0)
        files.append(file)
    s.feed(*(one_shot(f) for f in files))
    s.decoded()
    channels = [c for c, _ in plays(s)]
    assert sorted(set(channels)) == list(EFFECT_CHANNELS)
    assert len(channels) == 17                                 # the 17th took the oldest's
