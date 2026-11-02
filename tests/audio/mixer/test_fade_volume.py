"""AC-F08-32 — a volume change during a fade (PR-F08-08 "within 0.1 s"; ``04`` §7.2; ``07``
I-10, I-13(b)), on the disk driver: ``dc_4s.wav`` (every sample 20,000) fades in over 2.0 s
as an effect (a Python ramp, G1) and as music (SDL's native fade), and 0.5 s after the start
the settings lower its level to 10 % (volume 32: c(32) = 0.1024, quantized to 13/128). From
0.1 s after the change on (0.6 s in the AC) no sample exceeds 2,000 × 1.02, and from 2.1 s
on the samples are the quantized level 20,000 × 13/128 = 2,031 ± 50 (I-10). Times are audio
time (``conftest.py``).

The change is measured from when it was made (the clock read just after ``set_volumes``
returns), not from 0.5 s: under load the device can mix many buffers before the test's
thread runs again, so "0.5 s" may really be 0.9 s (it failed with a sample of 9,687 at
"0.6 s"). The AC's own tolerance, 0.1 s after the change, is unchanged; the change must
still land inside the fade."""

import pytest

from engine.runtime.commands import PlayMusic, PlaySound
from tests.audio.mixer.conftest import RATE, add, regions
from tests.fixtures.F08.make_audio import dc_wav

pytestmark = pytest.mark.mixer

LEVEL = round(20_000 * 13 / 128)          # 2,031
FADE_S = 2.0
WITHIN_S = 0.1                            # PR-F08-08


def check(disk, play, lower) -> None:
    add(disk.root, "formats/dc_4s.wav", dc_wav(4.0))
    frames: list[int] = []                         # the output frame after each App frame
    real_frame = disk.frame

    def frame() -> None:
        real_frame()
        frames.append(round(disk.clock() * RATE))

    disk.frame = frame
    disk.feed(play)
    started = disk.clock()
    disk.run_until(lambda: disk.clock() >= started + 0.5, audio_s=1.0)
    lower()
    changed = round(disk.clock() * RATE)                         # the frame it was made by

    def done() -> bool:
        """2.6 s in, and 0.4 s past the first App frame after the fade (normally 2.0 s)."""
        late = [f for f in frames if f >= (started + FADE_S + 0.05) * RATE]
        return disk.clock() >= started + 2.6 and bool(late) and (
            disk.clock() * RATE >= late[0] + 0.4 * RATE)

    disk.run_until(done, audio_s=3.5)
    left = disk.frames()[0::2]
    first = regions(left, threshold=0)[0][0]                       # the sound's first sample
    at = lambda seconds: first + round(seconds * RATE)           # noqa: E731
    assert changed < at(FADE_S - WITHIN_S), (
        f"the change came {(changed - first) / RATE:.2f} s in, after the fade: the machine "
        "stalled this test for over a second")
    end = min(len(left), at(3.9))                                  # dc_4s still plays
    assert max(left[changed + round(WITHIN_S * RATE):end]) <= 2_000 * 1.02
    # The effect's ramp (G1) reaches its end at the first App frame after 2.0 s; the App runs
    # one every 16.7 ms, this loop far more often unless the machine stalls it.
    ramp_end = next(f for f in frames if f >= at(FADE_S))
    window = left[max(at(FADE_S + WITHIN_S), ramp_end + round(WITHIN_S * RATE)):end]
    assert len(window) >= 0.2 * RATE
    assert min(window) >= LEVEL - 50 and max(window) <= LEVEL + 50


def test_ac_f08_32_an_effect_fading_in(disk_session):
    disk = disk_session()
    check(disk, PlaySound("formats/dc_4s.wav", False, 100, 2.0),
          lambda: disk.service.set_volumes(100, 100, 32, 100))


def test_ac_f08_32_music_fading_in(disk_session):
    disk = disk_session()
    check(disk, PlayMusic("formats/dc_4s.wav", False, 100, 2.0, None, False, None, False),
          lambda: disk.service.set_volumes(100, 32, 100, 100))
