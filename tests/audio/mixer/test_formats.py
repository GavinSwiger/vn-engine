"""AC-F08-33 (Ogg Vorbis, MP3, WAV at the right pitch) and AC-F08-34 (Opus, FLAC), on the disk
driver: a 2.000 s 1,000 Hz tone at −6 dBFS plays once as music and once as an effect; the
output's zero-crossing frequency over its middle 1.0 s is 1,000 Hz ± 1 %, its non-silent
length 2.000 s ± 30 ms, and both output channels carry the tone.

Rows built here: WAV (16-bit PCM) and FLAC at 22,050, 44,100, 48,000 Hz, mono and stereo
(``make_audio.py``); four of the twelve run by default, the rest are ``slow``. The Ogg
Vorbis, MP3, and Opus rows need ``06`` §5.2's encoded tones (a pinned encoder, F08 step 12);
until then pygame-ce's own ``house_lo.ogg``/``.mp3``/``.opus``
check that each format plays as music and as an effect for about its length. Nothing here
times anything in Python, so the device runs at ``SDL_DISKAUDIODELAY=0``."""

from array import array
from pathlib import Path

import pygame
import pytest

from engine.audio.sniff import sniff
from engine.runtime.commands import PlayMusic, PlaySound
from tests.audio.mixer.conftest import RATE, add, regions
from tests.fixtures.F08.make_audio import flac, pcm_tone, wav

pytestmark = pytest.mark.mixer

PYGAME_DATA = Path(pygame.__file__).parent / "examples" / "data"
THRESHOLD = 300                         # a −6 dBFS tone's samples near zero are below this


def frequency(samples: array) -> float:
    """Zero crossings (− to +) per second."""
    crossings = sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)
    return crossings / (len(samples) / RATE)


def play_both(disk, file: str, seconds: float) -> array:
    """``file`` once as music, then once as an effect; the output frames."""
    disk.feed(PlayMusic(file, False, 100, None, None, False, None, False))
    disk.run_until(lambda: not disk.service.music.is_playing(), audio_s=seconds + 1.0)
    disk.run(0.3)
    disk.feed(PlaySound(file, False, 100, None))
    disk.run_until(lambda: not disk.service.effects.active, audio_s=seconds + 1.0)
    disk.run(0.1)
    return disk.frames()


# The default run keeps four rows: each format at a resampled rate in mono and in stereo, and
# FLAC at the device rate (WAV at 48 kHz stereo is every other disk test's input). The other
# eight rows (most of the time is the pure-Python FLAC writer) are ``slow``.
DEFAULT_ROWS = {(".wav", 44_100, 1), (".wav", 22_050, 2), (".flac", 48_000, 1),
                (".flac", 22_050, 2)}
ROWS = [pytest.param(ext, rate, channels, id=f"{ext}-{rate}-{channels}",
                     marks=() if (ext, rate, channels) in DEFAULT_ROWS else pytest.mark.slow)
        for ext in (".wav", ".flac") for rate in (22_050, 44_100, 48_000) for channels in (1, 2)]


@pytest.mark.parametrize("ext, rate, channels", ROWS)
def test_ac_f08_33_34_a_tone_plays_at_the_right_pitch(disk_session, ext, rate, channels):
    pcm = pcm_tone(2.0, rate=rate, channels=channels)
    data = (wav(pcm, rate=rate, channels=channels) if ext == ".wav"
            else flac(pcm, rate=rate, channels=channels))
    disk = disk_session(delay=0)
    file = f"formats/tone_1k_{rate}_{channels}{ext}"
    add(disk.root, file, data)
    out = play_both(disk, file, 2.0)
    left, right = out[0::2], out[1::2]
    found = regions(left, threshold=THRESHOLD)
    assert len(found) == 2, found                        # music, then the effect
    for first, last in found:
        assert abs((last - first + 1) / RATE - 2.0) <= 0.030
        middle = slice(first + RATE // 2, first + RATE // 2 + RATE)
        assert frequency(left[middle]) == pytest.approx(1000, rel=0.01)
        assert frequency(right[middle]) == pytest.approx(1000, rel=0.01)


@pytest.mark.parametrize("name", ["house_lo.ogg", "house_lo.mp3", "house_lo.opus"])
def test_ac_f08_33_34_pygame_example_files_play_as_music_and_effect(disk_session, name):
    disk = disk_session(delay=0)
    reference = disk.backend.decode(sniff((PYGAME_DATA / "house_lo.wav").read_bytes(), ".wav"))
    seconds = disk.backend.sound_seconds(reference)
    file = f"formats/{name}"
    add(disk.root, file, (PYGAME_DATA / name).read_bytes())
    out = play_both(disk, file, seconds)
    found = regions(out[0::2], threshold=THRESHOLD, gap_s=0.25)
    assert len(found) == 2, found
    for first, last in found:
        assert (last - first) / RATE == pytest.approx(seconds, abs=0.25)
