"""Voice on the real mixer (F08 ``04`` §7.2 voice; AC-F08-28, 29's device half), on the disk
driver: a voice line plays once on channel 0 at its full level, ``voice_playing`` turns false
when its sound ends, the line's advance (``EndVoice``) cuts it, and with voice sustain it plays
to its end. Voice lines are ``make_audio.voice_wav`` tones (600 Hz, −6 dBFS: peak 16,384).
Times are audio time (``conftest.py``); the device's buffer adds up to about 25 ms.

Under load the device can mix many buffers between two lines of this test, so the cut is
checked against the clock read around ``EndVoice`` (not against when the test meant to send
it), and the voices that are cut or sustained are long enough that the advance always
lands while they play."""

from array import array

import pytest

from engine.runtime.commands import EndVoice, PlayVoice
from tests.audio.mixer.conftest import RATE, add, regions
from tests.fixtures.F08.make_audio import voice_wav

pytestmark = pytest.mark.mixer

PEAK = 16_384
TOLERANCE_S = 0.06


def lengths(disk) -> tuple[list[tuple[int, int]], array]:
    """The ``(first, last)`` frame of each loud stretch of the output, and its left channel."""
    left = disk.frames()[0::2]
    return regions(left, threshold=1_000), left


def test_a_voice_plays_once_at_full_level_and_its_advance_cuts_the_next(disk_session):
    disk = disk_session()
    add(disk.root, "voice/hana_014.wav", voice_wav(0.6))
    add(disk.root, "voice/hana_015.wav", voice_wav(4.0, freq=500.0))
    service = disk.service
    disk.feed(PlayVoice("s1", "voice/hana_014.wav", False))
    assert service.voice_playing("s1")
    disk.run_until(lambda: not service.voice_playing("s1"), audio_s=3.0)
    assert not service.voice_playing()
    disk.run(0.4)                                              # a gap between the lines
    disk.feed(PlayVoice("s2", "voice/hana_015.wav", False))
    started = disk.clock()
    disk.run_until(lambda: disk.clock() >= started + 0.5, audio_s=1.0)
    assert service.voice_playing("s2")
    before = disk.clock()
    disk.feed(EndVoice("s2"))                                  # the player advances
    after = disk.clock()
    assert not service.voice_playing()
    disk.run(0.4)
    found, left = lengths(disk)
    assert len(found) == 2, found                              # once: the voice never loops
    assert (found[0][1] - found[0][0]) / RATE == pytest.approx(0.6, abs=TOLERANCE_S)
    cut = found[1][1] / RATE                                   # its last loud frame
    assert before - TOLERANCE_S <= cut <= after + TOLERANCE_S, (before, cut, after)
    assert (found[1][1] - found[1][0]) / RATE < 4.0 - TOLERANCE_S   # cut, not played out
    first = found[0]
    assert PEAK - 200 <= max(left[first[0]:first[1]]) <= PEAK  # amp(100, 100, 100) = 1.0


def test_with_sustain_the_voice_plays_past_its_advance(disk_session):
    disk = disk_session()
    add(disk.root, "voice/hana_041.wav", voice_wav(1.0))
    service = disk.service
    service.set_voice_sustain(True)
    disk.feed(PlayVoice("s1", "voice/hana_041.wav", False))
    disk.feed(EndVoice("s1"))                     # the advance, straight after it starts
    assert service.voice_playing("s1")
    disk.run_until(lambda: not service.voice_playing(), audio_s=3.0)
    disk.run(0.2)
    found, _ = lengths(disk)
    assert len(found) == 1 and (found[0][1] - found[0][0]) / RATE == pytest.approx(
        1.0, abs=TOLERANCE_S)
