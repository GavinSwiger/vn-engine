"""AC-F08-49 — audio keeps playing in the background, on the real mixer (disk driver; F08
``04`` §7.8, §7.10; PR-F08-25), and AC-F08-50's pause on the device (PR-F08-26).

While minimized the App draws no frames and wakes at most 10 times a second
(``MINIMIZED_WAIT_MS``), calling ``audio.update`` on each wake; here a frame runs every 0.1 s
of audio time. Music is DC (a constant sample value per track), so where one track ends and
the next begins is read straight off the output. The App half (100 resizes and fullscreen
toggles cause no backend call) is ``tests/app/test_audio_background_app.py``.

The ramp and the resume are measured against the audio clock read where things happened
(the effect's ``channel_play``, each wake, around the resume), so a test thread the loaded
machine stalls can't fail them; the AC's bounds hold whenever the wakes keep their 0.1 s."""

import time

import pygame
import pytest

from engine.runtime.commands import PlayMusic, PlaySound, QueueMusic
from tests.audio.mixer.conftest import RATE, add
from tests.fixtures.F08.make_audio import dc_wav

pytestmark = pytest.mark.mixer

OMEN, SHRINE, RAIN = "bgm/omen.wav", "bgm/shrine_steps.wav", "sfx/rain.wav"
OMEN_S = 1.0
WAKE_S = 0.1                                   # MINIMIZED_WAIT_MS


def recorded(disk, *names: str) -> list[tuple[float, str, tuple]]:
    """Wrap the backend's ``names`` so each call is noted with the audio clock."""
    calls: list[tuple[float, str, tuple]] = []
    for name in names:
        real = getattr(disk.backend, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            calls.append((disk.clock(), _name, args))
            return _real(*args, **kwargs)

        setattr(disk.backend, name, spy)
    return calls


def minimized_wakes(disk, audio_s: float) -> list[float]:
    """``audio_s`` seconds of audio time with one App wake (events, then ``update``) every
    ``WAKE_S``; the audio time of each wake."""
    end = disk.clock() + audio_s
    last = disk.clock()
    wakes = []
    wall = time.perf_counter() + 10.0
    while disk.clock() < end:
        assert time.perf_counter() < wall, "the mixer stopped advancing"
        if disk.clock() - last >= WAKE_S:
            last = disk.clock()
            wakes.append(last)
            disk.frame()
        time.sleep(0.0005)
    return wakes


def test_ac_f08_49_minimized_the_queue_advances_and_ramps_end_on_time(disk_session):
    disk = disk_session(delay=1)
    add(disk.root, OMEN, dc_wav(OMEN_S, value=10_000))
    add(disk.root, SHRINE, dc_wav(1.0, value=5_000))
    add(disk.root, RAIN, dc_wav(1.0, value=0))
    calls = recorded(disk, "pause_all", "resume_all", "music_stop", "music_start",
                     "channel_play", "channel_volume")
    service = disk.service
    disk.feed(PlayMusic(OMEN, False, 100, None, None, False, None, False),
              QueueMusic(SHRINE, True, 100, None), PlaySound(RAIN, True, 100, 2.0))
    (ramp_t0,) = [t for t, name, _ in calls if name == "channel_play"]   # the ramp's start
    for kind in (pygame.WINDOWFOCUSLOST, pygame.WINDOWMINIMIZED):
        assert service.handle_event(pygame.event.Event(kind)) is False
    wakes = minimized_wakes(disk, OMEN_S + 1.6)
    assert not [c for c in calls if c[1] in ("pause_all", "resume_all")]
    assert [c[1] for c in calls if c[1].startswith("music_")] == ["music_start"]   # omen only
    full = [t for t, name, args in calls if name == "channel_volume" and args[1] == 1.0]
    # 2.0 s ± 0.15 at a wake every 0.1 s. A wake the loaded machine delayed past that
    # cadence widens the upper bound by exactly the delay (the harness's, not the ramp's).
    first_wake = min(w for w in wakes if w >= ramp_t0 + 2.0)
    stall = max(0.0, first_wake - (ramp_t0 + 2.0) - WAKE_S)
    assert full and 2.0 - 0.15 <= full[0] - ramp_t0 <= 2.0 + 0.15 + stall, (full, ramp_t0,
                                                                              stall)
    assert service.music.current is not None and service.music.current.file == SHRINE
    left = disk.frames()[0::2]
    omen_last = max(i for i, v in enumerate(left) if v == 10_000)
    shrine_first = next(i for i, v in enumerate(left) if v == 5_000)
    assert 0 <= (shrine_first - omen_last) / RATE <= 0.2


def test_ac_f08_50_pausing_on_the_device_keeps_the_position(disk_session):
    disk = disk_session(delay=1)
    add(disk.root, SHRINE, dc_wav(4.0, value=5_000))
    service = disk.service
    service.set_background(unfocused=False, minimized=True)
    disk.feed(PlayMusic(SHRINE, True, 100, None, None, False, None, False))
    disk.run(0.5)
    # Both positions are SDL's own (read while the stream is busy), each bracketed by the
    # audio clock: under load the device may mix several buffers between these lines.
    before_pause = disk.clock()
    at_pause = service.music.position(service.now())
    service.handle_event(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    late = disk.clock() - before_pause
    assert not pygame.mixer.music.get_busy()
    disk.run(0.5)
    resumed = disk.clock()
    service.handle_event(pygame.event.Event(pygame.WINDOWFOCUSGAINED))
    position = service.music.position(service.now())
    since = disk.clock() - resumed
    # It goes on from where it paused (not 0.5 s later), plus what was mixed in between.
    assert at_pause - 0.05 <= position <= at_pause + late + since + 0.05, (
        at_pause, position, late, since)
    disk.run(0.3)
    assert pygame.mixer.music.get_busy()
    left = disk.frames()[0::2]
    loud = [v == 5_000 for v in left]
    # The output has a stretch of silence (the pause) between two stretches of shrine.
    first_quiet = loud.index(False, loud.index(True))
    assert any(loud[first_quiet:])
