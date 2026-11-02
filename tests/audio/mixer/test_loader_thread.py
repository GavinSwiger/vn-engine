"""F08 step 9 on the real mixer (SDL's dummy driver): the decode worker with ``PygameMixer``.

- The worker rule with SDL: a real Sound is decoded on the worker (spied through
  ``SoundLoader.decode``, I-13(c)) and plays from ``update``; ``shutdown`` closes the mixer.
- AC-F08-36's spy half (I-17: it runs in the ``mixer`` job): AC-F08-35's rows plus
  ``mod_id3.mp3`` and ``xm_in_wav.wav`` played as music, effect, and voice: no Sound of 300 s
  or more is ever created, music isn't busy 0.2 s after the attempts, and each attempt logs
  exactly one W26 or plays as PCM.
- AC-F08-56 (``slow``): decoding never stalls a frame. A frame loop stand-in calls
  ``audio.update`` every 16.7 ms; 50 ``PlaySound``s of distinct 1 MB files are issued, one
  every 6 frames (100 ms, about one decode); the frame work of the frames that issue one
  exceeds the median of 200 baseline frames by at most 2 ms (p95). The files: a 1 MB FLAC
  (``make_audio.flac`` writes verbatim frames, which decode in about 20 ms) and a 1 MB 8 kHz
  WAV whose decode (resampled to 48 kHz, about 75–90 ms here) is close to the AC's 89 ms
  compressed FLAC, until F08 step 12's encoded fixtures exist. An issuing frame's work is
  almost all the main thread's 1 MB read (§7.3: bytes are read on the main thread), about
  0.5–1 ms here. Measured on win32 (F08 step 9): p95 1.1–1.4 ms over the baseline. With one
  ``PlaySound`` every 4 frames the worker never idles, the read slows while it converts
  audio, and the p95 was 1.7–2.8 ms; a script that starts a 1 MB effect more than ten times
  a second is not a case the AC describes. This test decides ``LOADER_THREADED`` per OS:
  where it fails, that OS ships with the fallback (``engine/audio/loader.py``
  ``_THREADED_BY_PLATFORM``).
"""

import io
import logging
import os
import statistics
import sys
import threading
import time
from pathlib import Path

import pygame
import pytest

from engine.app.dispatch import CommandRouter
from engine.audio.backend import PygameMixer
from engine.audio.loader import WORKER_NAME, SoundLoader
from engine.audio.service import AudioService
from engine.core.config_schema import AudioConfig
from engine.core.lru import SizedLru
from engine.core.paths import GamePaths
from engine.runtime.commands import PlayMusic, PlaySound, PlayVoice, StopSound
from tests.fixtures.F08.make_audio import (broken_files, flac, mod_module, pcm_noise, riff,
                                           pygame_data, tone_wav, wav)

pytestmark = [pytest.mark.mixer,
              pytest.mark.skipif(os.environ.get("SDL_AUDIODRIVER") != "dummy",
                                 reason="needs SDL's dummy audio driver (tests/conftest.py)")]

WAIT_S = 10.0                       # a hang, not a slow machine
AUDIO_LOG = "vn.audio"


class Dummy:
    """A real ``AudioService`` on ``PygameMixer`` (dummy driver), the wall clock, its
    worker on; ``frame()`` is one App frame (dispatch happens in ``feed``)."""

    def __init__(self, root: Path, *, cache_bytes: int = 256 << 20) -> None:
        self.root = root
        self.frame_no = 1
        self.backend = PygameMixer()
        self.service = AudioService(GamePaths(root.resolve()), SizedLru(cache_bytes),
                                    AudioConfig(master_volume=100, sound_volume=100),
                                    backend=self.backend, clock=time.perf_counter,
                                    frame=lambda: self.frame_no)
        assert self.service.loader.threaded or sys.platform not in ("win32", "linux", "darwin")
        self.router = CommandRouter()
        self.service.register(self.router)

    def add(self, file: str, data: bytes) -> None:
        path = self.root / "audio" / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def feed(self, *commands: object) -> None:
        for command in commands:
            self.router.dispatch(command)

    def frame(self) -> None:
        self.frame_no += 1
        for event in pygame.event.get():
            self.service.handle_event(event)
        self.service.update(time.perf_counter())

    def settle(self) -> None:
        """Frames until no decode is in flight (bounded waits, no sleep-polling)."""
        loader = self.service.loader
        while loader.pending:
            assert loader.wait(WAIT_S), "the decode worker did not answer"
            self.frame()


@pytest.fixture
def dummy(tmp_path):
    root = tmp_path / "game"
    (root / "audio").mkdir(parents=True)
    if pygame.mixer.get_init():
        pygame.mixer.quit()
    pygame.display.init()                         # music-end events need the video system
    made: list[Dummy] = []

    def open_dummy(**kwargs) -> Dummy:
        assert not made
        made.append(Dummy(root, **kwargs))
        return made[0]

    yield open_dummy
    for session in made:
        thread = session.service.loader.worker
        session.service.shutdown()
        if thread is not None:
            thread.join(WAIT_S)
            assert not thread.is_alive()
    pygame.quit()


@pytest.fixture
def decode_spy(monkeypatch):
    """I-13(c): every ``SoundLoader.decode`` as ``(thread name, Sound length or error)``."""
    seen: list[tuple[str, float | str]] = []
    original = SoundLoader.decode

    def spy(self, sniffed):
        try:
            sound = original(self, sniffed)
        except Exception as error:
            seen.append((threading.current_thread().name, type(error).__name__))
            raise
        seen.append((threading.current_thread().name, sound.get_length()))
        return sound

    monkeypatch.setattr(SoundLoader, "decode", spy)
    return seen


def test_a_real_sound_decodes_on_the_worker_and_plays_from_update(dummy, decode_spy):
    session = dummy()
    session.add("sfx/tone.wav", tone_wav(1.0))
    session.feed(PlaySound("sfx/tone.wav", False, 100, None))
    assert not session.service.effects.slots and session.service.effects.active
    session.settle()
    assert decode_spy == [(WORKER_NAME, pytest.approx(1.0, abs=0.01))]
    assert session.backend.channel_busy(5)
    session.feed(PlaySound("sfx/tone.wav", False, 100, None))     # cached: at once
    assert session.backend.channel_busy(6) and len(decode_spy) == 1
    session.service.shutdown()
    assert not pygame.mixer.get_init()                            # closed under the lock


# --- AC-F08-36, spy half (I-17) -------------------------------------------------------------------

def ac36_rows() -> dict[str, bytes]:
    rows = dict(broken_files())
    rows["mod_id3.mp3"] = mod_module(b"ID3 is not a header")
    rows["xm_in_wav.wav"] = riff(b"WAVE", b"data", pygame_data("surfonasinewave.xm"))
    return rows


def test_ac_f08_36_no_tracker_or_midi_decoder_is_reachable(dummy, decode_spy, caplog):
    """Every row as music, effect, and voice in one session (each its own path), then the
    0.2 s check once after all the attempts."""
    session = dummy()
    rows = ac36_rows()
    caplog.set_level(logging.WARNING, logger=AUDIO_LOG)
    for channel, (name, data) in ((c, row) for c in ("music", "sound", "voice")
                                  for row in rows.items()):
        file = f"{channel}/{name}"
        session.add(file, data)
        before = len([r for r in caplog.records if r.name == AUDIO_LOG])
        if channel == "music":
            session.feed(PlayMusic(file, True, 100, None, None, False, None, False))
        elif channel == "sound":
            session.feed(PlaySound(file, False, 100, None))
        else:
            session.feed(PlayVoice("s1", file, False))
        session.settle()
        session.frame()
        records = [r for r in caplog.records if r.name == AUDIO_LOG][before:]
        w26 = [r for r in records if getattr(r, "code", None) == "W26"]
        playing = (pygame.mixer.music.get_busy() if channel == "music"
                   else session.service.effects.active or session.service.voice_playing())
        assert len(w26) == 1 or (not records and playing), (channel, name, records)
        if w26:
            assert not pygame.mixer.music.get_busy(), (channel, name)
        session.service.stop_story_audio(0.0)
        session.frame()
    deadline = time.perf_counter() + 0.2
    while time.perf_counter() < deadline:
        session.frame()
        time.sleep(0.01)
    assert not pygame.mixer.music.get_busy()
    assert all(isinstance(length, str) or length < 300.0 for _, length in decode_spy)
    assert {thread for thread, _ in decode_spy} <= {WORKER_NAME}


# --- AC-F08-56 (slow) --------------------------------------------------------------------------------

FRAME_S = 1 / 60
BASELINE_FRAMES = 200
PLAYS = 50
EVERY = 6                                  # one PlaySound every 6th frame (100 ms)
MAX_EXCESS_S = 0.002


def _one_mb(kind: str) -> bytes:
    if kind == "flac":
        rate = 22_050
        return flac(pcm_noise(1_000_000 / (rate * 2), seed=56, rate=rate, channels=1),
                    rate=rate, channels=1)
    rate = 8_000
    return wav(pcm_noise(1_000_000 / (rate * 2), seed=56, rate=rate, channels=1), rate=rate,
               channels=1)


@pytest.mark.slow
@pytest.mark.parametrize("kind", ["wav8k", "flac"])
def test_ac_f08_56_decoding_never_stalls_a_frame(dummy, kind):
    session = dummy(cache_bytes=32 << 20)
    data = _one_mb(kind)
    ext = ".flac" if kind == "flac" else ".wav"
    files = [f"perf/fx_{index:02d}{ext}" for index in range(PLAYS)]
    for file in files:
        session.add(file, data)
    pygame.mixer.Sound(io.BytesIO(data))                         # warm SDL's decoder
    started = time.perf_counter()
    pygame.mixer.Sound(io.BytesIO(data))
    decode_ms = (time.perf_counter() - started) * 1000

    def frame(commands: tuple = ()) -> float:
        start = time.perf_counter()
        session.feed(*commands)
        session.frame()
        work = time.perf_counter() - start
        rest = FRAME_S - (time.perf_counter() - start)
        if rest > 0:
            time.sleep(rest)
        return work

    baseline = [frame() for _ in range(BASELINE_FRAMES)]
    issuing: list[float] = []
    others: list[float] = []
    index = 0
    frames = 0
    deadline = time.perf_counter() + 60.0
    while index < PLAYS or session.service.loader.pending:
        assert time.perf_counter() < deadline, "the decode worker fell behind for a minute"
        if index < PLAYS and frames % EVERY == 0:
            issuing.append(frame((PlaySound(files[index], False, 100, None),)))
            index += 1
        elif frames % EVERY == 3:
            others.append(frame((StopSound(None, None),)))
        else:
            others.append(frame())
        frames += 1
    median = statistics.median(baseline)
    p95 = sorted(issuing)[int(0.95 * (len(issuing) - 1))]
    others_p95 = sorted(others)[int(0.95 * (len(others) - 1))]
    print(f"\nAC-F08-56 {sys.platform} pygame-ce {pygame.version.ver} {kind}: one decode "
          f"{decode_ms:.1f} ms; baseline median {median * 1000:.3f} ms; issuing frames p95 "
          f"{p95 * 1000:.3f} ms, max {max(issuing) * 1000:.3f} ms ({len(issuing)} plays, "
          f"{frames} frames); the other frames p95 {others_p95 * 1000:.3f} ms, max "
          f"{max(others) * 1000:.3f} ms")
    assert p95 - median <= MAX_EXCESS_S
