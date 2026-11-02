"""AC-F08-22 — gapless loops and queue transitions (PR-F08-13, 02, 05; TR-F08-03; ``04`` §15
``test_gapless.py``), on the disk driver: a track looping as music and as an effect, and a
queue transition, compared sample by sample with a straight decode.

Measured on pygame-ce 2.5.8 / SDL_mixer 2.8.2: a looping track played with ``loops=-1`` and an
effect loop are sample-exact (0 frames between passes), but a queue transition (pygame's
one-slot ``music.queue``) starts the next track in the next 512-frame buffer, 1–512 frames
later. So ``MusicPlayer`` loops natively and the queue-transition row of AC-22 is an
expected failure until that is decided (see the step report).

Stand-ins (``06`` §5.3's Vorbis loops need the pinned encoder of F08 step 12): 0.500 s of
seeded 48,000 Hz stereo noise as WAV, and the same noise as FLAC (decoded by SDL_mixer's own
FLAC music decoder). Lives with the other mixer tests rather than ``tests/perf/`` (it is a
correctness check that runs in a second)."""

import pytest

from engine.runtime.commands import PlayMusic, PlaySound, QueueMusic, StopMusic, StopSound
from tests.audio.mixer.conftest import add, find_all
from tests.fixtures.F08.make_audio import flac, pcm_noise, wav

pytestmark = pytest.mark.mixer

PASS_S = 0.5
FRAMES = round(PASS_S * 48_000)
HEAD = 1_024 * 4                        # the first 1,024 frames, in bytes
MAX_GAP = 8


def passes(out: bytes, pcm: bytes) -> list[int]:
    """The frame index of each full pass of ``pcm`` in ``out``."""
    found = find_all(out, pcm[:HEAD])
    return [at for at in found if out[at * 4:at * 4 + len(pcm)] == pcm]


def gaps(starts: list[int]) -> list[int]:
    return [b - (a + FRAMES) for a, b in zip(starts, starts[1:])]


@pytest.mark.parametrize("ext", [".wav", ".flac"])
def test_ac_f08_22_music_and_effect_loops_are_gapless(disk_session, ext):
    pcm = pcm_noise(PASS_S, seed=1)
    data = wav(pcm) if ext == ".wav" else flac(pcm, rate=48_000, channels=2)
    disk = disk_session(delay=0)               # both loops are SDL's own: nothing is timed
    add(disk.root, f"loops/noise{ext}", data)
    file = f"loops/noise{ext}"
    disk.feed(PlayMusic(file, True, 100, None, None, False, None, False))
    disk.run(3 * PASS_S + 0.3)
    disk.feed(StopMusic(0))
    switch = disk.clock() * 48_000             # after the stop, before the effect starts
    disk.feed(PlaySound(file, True, 100, None))
    disk.run(3 * PASS_S + 0.3)
    disk.feed(StopSound(None, 0))
    out = disk.frames().tobytes()
    starts = passes(out, pcm)
    music = [s for s in starts if s < switch]
    effect = [s for s in starts if s not in music]
    assert len(music) >= 3 and len(effect) >= 3, (music, effect)
    assert all(0 <= gap <= MAX_GAP for gap in gaps(music)), gaps(music)
    assert all(gap == 0 for gap in gaps(effect)), gaps(effect)


def queue_transition_gap(disk_session) -> int:
    """The frames between a's last frame and b's first, for ``play music a`` then ``queue
    music b`` (a plays once)."""
    a, b = pcm_noise(PASS_S, seed=2), pcm_noise(PASS_S, seed=3)
    disk = disk_session()
    add(disk.root, "loops/a.wav", wav(a))
    add(disk.root, "loops/b.wav", wav(b))
    disk.feed(PlayMusic("loops/a.wav", True, 100, None, None, False, None, False),
              QueueMusic("loops/b.wav", True, 100, None))
    player = disk.service.music
    disk.run_until(lambda: player.current is not None and player.current.file == "loops/b.wav",
                   audio_s=2.0)
    disk.run(PASS_S + 0.2)
    out = disk.frames().tobytes()
    (at_a,) = passes(out, a)                     # once: the queue ended a's loop
    (at_b, *_) = passes(out, b)
    return at_b - (at_a + FRAMES)


def test_ac_f08_22_a_queue_transition_starts_within_one_buffer(disk_session):
    """What pygame-ce 2.5.8 / SDL_mixer 2.8.2 give: the queued track starts in the next
    512-frame buffer, so the silence between is the rest of the buffer a ended in (64
    frames here: 24,000 mod 512 = 448)."""
    gap = queue_transition_gap(disk_session)
    assert 0 < gap <= 512
    assert gap == (-FRAMES) % 512 or gap == 512


@pytest.mark.xfail(strict=True, reason="SDL_mixer 2.8.2 pads a queue transition to the next "
                   "512-frame buffer; AC-F08-22's 8-frame bound is a question for the architect")
def test_ac_f08_22_a_queue_transition_is_gapless(disk_session):
    assert queue_transition_gap(disk_session) <= MAX_GAP
