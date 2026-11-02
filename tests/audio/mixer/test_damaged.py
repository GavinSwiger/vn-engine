"""AC-F08-38 — a file damaged partway (W27; PR-F08-16; ``04`` §12), on the disk driver.

Played as music with a track queued after it, the damaged file ends where its data ends, the
output is silent until the next track's first frame, which comes within 0.6 s, W27 names the
time it stopped (m:ss, rounded down), and nothing hangs; played as an effect it ends at the
cut and its channel frees. Stand-ins until F08 step 12's fixtures: ``broken/truncated.wav`` is
seeded noise whose header declares 4.0 s but holds 1.2 s (its known length comes from the
header); ``truncated.ogg``/``.mp3`` are pygame-ce's ``house_lo`` files cut at 60 %, the Ogg
keeping its last page so it still declares the full length. MP3 has no known length, so it
gets no W27."""

import logging
from pathlib import Path

import pygame
import pytest

from engine.runtime.commands import PlayMusic, PlaySound, QueueMusic
from tests.audio.mixer.conftest import RATE, add, find_all
from tests.fixtures.F08.make_audio import noise_wav, pcm_noise, truncated_wav

pytestmark = pytest.mark.mixer

PYGAME_DATA = Path(pygame.__file__).parent / "examples" / "data"
NEXT = pcm_noise(0.5, seed=5)


def cut(name: str, keep_last_page: bool) -> bytes:
    data = (PYGAME_DATA / name).read_bytes()
    head = data[:int(len(data) * 0.6)]
    return head + data[data.rfind(b"OggS"):] if keep_last_page else head


def play_with_next(disk, file: str) -> tuple[bytes, float]:
    """``play music file`` then ``queue music "bgm/next.wav"``; the output and the audio
    time the next track started."""
    add(disk.root, "bgm/next.wav", noise_wav(0.5, seed=5))
    disk.feed(PlayMusic(file, False, 100, None, None, False, None, False),
              QueueMusic("bgm/next.wav", True, 100, None))
    player = disk.service.music
    started = disk.clock()
    disk.run_until(lambda: player.current is not None and player.current.file == "bgm/next.wav",
                   audio_s=8.0)
    assert player.current is not None and player.current.file == "bgm/next.wav"
    disk.run(0.6)
    return disk.frames().tobytes(), started


def test_ac_f08_38_a_truncated_wav_is_w27_and_the_queue_goes_on(disk_session, caplog):
    disk = disk_session()
    data = truncated_wav(4.0, 1.2)
    add(disk.root, "broken/truncated.wav", data)
    pcm = data[44:]
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        out, _ = play_with_next(disk, "broken/truncated.wav")
    (start,) = find_all(out, pcm[:4096])
    last = start + len(pcm) // 4                      # the frame after its last decoded one
    assert out[start * 4:last * 4] == pcm
    (nxt, *_) = find_all(out, NEXT[:4096])
    assert set(out[last * 4:nxt * 4]) <= {0}          # silence until the next track
    assert (nxt - last) / RATE <= 0.6
    assert caplog.messages == ["audio/broken/truncated.wav is damaged 0:01 in, so it stopped "
                               "there. Export it again as .wav."]
    assert caplog.records[0].code == "W27"


@pytest.mark.parametrize("name, w27", [("house_lo.ogg", True), ("house_lo.mp3", False)])
def test_ac_f08_38_cut_ogg_and_mp3_end_and_the_queue_goes_on(disk_session, caplog, name, w27):
    disk = disk_session()                 # W27's time needs frames at delay=1, not 0
    ext = name[-4:]
    add(disk.root, f"broken/truncated{ext}", cut(name, keep_last_page=ext == ".ogg"))
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        out, _ = play_with_next(disk, f"broken/truncated{ext}")
    assert find_all(out, NEXT[:4096])
    damaged = [m for m in caplog.messages if " is damaged " in m]
    assert bool(damaged) == w27, caplog.messages
    if w27:
        assert damaged[0].startswith("audio/broken/truncated.ogg is damaged 0:0")
        assert damaged[0].endswith(" in, so it stopped there. Export it again as .ogg.")


@pytest.mark.parametrize("file, data", [
    ("broken/truncated.wav", truncated_wav(4.0, 1.2)),
    ("broken/truncated.ogg", cut("house_lo.ogg", keep_last_page=False))])
def test_ac_f08_38_as_an_effect_it_ends_at_the_cut_and_frees_its_channel(disk_session, file,
                                                                          data):
    disk = disk_session(delay=0)                     # nothing timed: play and wait
    add(disk.root, file, data)
    disk.feed(PlaySound(file, False, 100, None))
    assert disk.service.effects.active                     # it plays
    disk.run_until(lambda: not disk.service.effects.active, audio_s=6.0)
    assert not disk.service.effects.active
