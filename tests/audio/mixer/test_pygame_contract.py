"""AC-F08-21 — the pygame-ce contract (TR-F08-06, TR-F08-02, R2; ``04`` §2, §15): what
``PygameMixer`` and ``MusicPlayer`` rely on, checked on the pinned pygame-ce, and the backend
spied over AC-F08-16..18 replayed on the real mixer: ``music.load`` and ``music.play`` are
never called while the stream is busy (the 1.1 s block during a fade never happens).

Runs on the disk driver with the audio-time clock (``conftest.py``); "0.2 s later" is 0.2 s of
mixed audio."""

import pygame
import pytest

from engine.audio.music import Phase
from engine.core.config_schema import AudioConfig
from engine.runtime.commands import PlayMusic, QueueMusic, StopMusic
from tests.audio.mixer.conftest import add
from tests.fixtures.F08.make_audio import noise_wav, wav, pcm_noise

pytestmark = pytest.mark.mixer


def ends(backend) -> int:
    return sum(backend.is_music_end(e) for e in pygame.event.get())


def wait(disk, seconds: float) -> None:
    end = disk.clock() + seconds
    while disk.clock() < end:
        pass


def sniffed(data: bytes, ext: str = ".wav"):
    from engine.audio.sniff import sniff

    return sniff(data, ext)


def test_ac_f08_21_the_pygame_ce_contract(disk_session):
    disk = disk_session()
    music = pygame.mixer.music
    a = sniffed(noise_wav(1.0, seed=1))
    b = sniffed(noise_wav(1.0, seed=2))
    backend = disk.backend
    pygame.event.clear()
    # load + play post no end event; stop() posts exactly one …
    import io

    music.load(io.BytesIO(a.data), "wav")
    music.play()
    wait(disk, 0.05)
    assert ends(backend) == 0
    # … and clears the queue slot: nothing plays 0.2 s later.
    music.queue(io.BytesIO(b.data), "wav")
    music.stop()
    assert ends(backend) == 1
    wait(disk, 0.2)
    assert not music.get_busy() and ends(backend) == 0
    # get_pos freezes while paused and advances after unpause (get_busy is False paused).
    music.load(io.BytesIO(a.data), "wav")
    music.play()
    wait(disk, 0.1)
    music.pause()
    first = music.get_pos()
    wait(disk, 0.3)
    assert music.get_pos() == first and not music.get_busy()
    music.unpause()
    wait(disk, 0.1)
    assert music.get_pos() > first
    # fadeout drops the queue slot; a queue transition posts one event and restarts get_pos.
    music.queue(io.BytesIO(b.data), "wav")
    music.fadeout(50)
    wait(disk, 0.2)
    assert not music.get_busy()
    pygame.event.clear()
    music.load(io.BytesIO(sniffed(wav(pcm_noise(0.2, seed=3))).data), "wav")
    played = disk.clock()                                # before: a stall only adds
    music.play()
    music.queue(io.BytesIO(b.data), "wav")
    wait(disk, 0.3)
    pos = music.get_pos()
    into_b = (disk.clock() - played - 0.2) * 1000        # 100 ms, more if the test stalled
    assert music.get_busy() and ends(backend) == 1
    assert 50 <= pos <= into_b + 50, (pos, into_b)       # restarted: not 300 ms or more


def test_ac_f08_21_music_start_stops_and_drains_first(disk_session, monkeypatch):
    disk = disk_session()
    backend = disk.backend
    a = sniffed(noise_wav(1.0, seed=1))
    order = []
    real = {name: getattr(pygame.mixer.music, name) for name in ("stop", "load", "play")}
    real_clear = pygame.event.clear

    def spy(name):
        def call(*args, **kwargs):
            order.append(name)
            return real[name](*args, **kwargs)
        return call

    for name in real:
        monkeypatch.setattr(pygame.mixer.music, name, spy(name))
    monkeypatch.setattr(pygame.event, "clear",
                        lambda *a, **k: (order.append("drain"), real_clear(*a, **k))[1])
    backend.music_start(a, loops=0, start=0.0, fade_ms=0)
    backend.music_start(a, loops=0, start=0.0, fade_ms=0)
    assert order == ["stop", "drain", "load", "play"] * 2
    assert ends(backend) == 0                       # the stop()'s event was drained


def PM(file, **kw) -> PlayMusic:
    return PlayMusic(file, kw.get("loop", True), 100, kw.get("fadein"), kw.get("fadeout"),
                     False, None, False)


def test_ac_f08_21_load_and_play_never_run_while_busy(disk_session, monkeypatch):
    """AC-F08-16..18's moves on the real mixer, with ``music.load``/``music.play`` spied."""
    disk = disk_session(AudioConfig(master_volume=100, music_volume=100, music_fadeout=0.2))
    root = disk.root
    for name, seed in (("a", 1), ("b", 2), ("c", 3)):
        add(root, f"bgm/{name}.wav", noise_wav(0.6, seed=seed))
    busy_at_call = []
    for name in ("load", "play"):
        real = getattr(pygame.mixer.music, name)

        def spy(*args, _real=real, **kwargs):
            busy_at_call.append(pygame.mixer.music.get_busy())
            return _real(*args, **kwargs)

        monkeypatch.setattr(pygame.mixer.music, name, spy)
    player = disk.service.music
    disk.feed(PM("bgm/a.wav"))                                  # silent → start
    disk.run(0.3)
    disk.feed(PM("bgm/b.wav"))                                  # fade out, then b
    disk.run_until(lambda: player.current.file == "bgm/b.wav", audio_s=1.0)
    disk.feed(QueueMusic("bgm/c.wav", True, 100, None))         # b's pass, then c
    disk.run_until(lambda: player.current.file == "bgm/c.wav", audio_s=1.5)
    disk.feed(PM("bgm/c.wav"), PM("bgm/a.wav", fadeout=0))      # same track; a hard cut
    disk.run(0.2)
    disk.feed(StopMusic(0.2), QueueMusic("bgm/b.wav", True, 100, None))
    disk.run_until(lambda: player.current is not None and player.current.file == "bgm/b.wav",
                   audio_s=1.0)
    disk.feed(PM("bgm/b.wav", loop=False), StopMusic(0.1))
    disk.run_until(lambda: player.phase is Phase.SILENT, audio_s=1.0)
    assert player.phase is Phase.SILENT
    assert len(busy_at_call) >= 8                               # four starts or more
    assert not any(busy_at_call)
