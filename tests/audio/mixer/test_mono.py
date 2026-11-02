"""AC-F08-54 — mono on the real mixer (F08 ``04-technical.md`` §7.9; PR-F08-32): with festival
playing at 4.0 s and rain looping, ``set_mono(True)`` reopens SDL_mixer with one output
channel, the music resumes at 4.0 s ± 0.1 and the loop restarts; ``set_mono(False)`` gives two
channels again.

SDL's **dummy** driver (AC-54's Given; ``conftest.py``'s ``dummy``): the disk driver writes a
new output file on each open, so its audio clock would start again at the reopen. The dummy
driver consumes audio in real time, so the service runs on the wall clock and festival starts
``from 4.0`` instead of playing for 4 s."""

import pygame
import pytest

from engine.audio.limits import EFFECT_CHANNELS
from engine.runtime.commands import PlayMusic, PlaySound
from tests.audio.mixer.conftest import add, settle
from tests.fixtures.F08.make_audio import dc_wav

pytestmark = pytest.mark.mixer

FESTIVAL, RAIN = "bgm/festival.wav", "sfx/rain.wav"


def test_ac_f08_54_mono_reopens_with_one_channel_and_plays_on(dummy):
    add(dummy.root, FESTIVAL, dc_wav(10.0, value=8_000))
    add(dummy.root, RAIN, dc_wav(1.0, value=2_000))
    service, router = dummy()
    router.dispatch(PlayMusic(FESTIVAL, True, 100, 0.0, None, False, 4.0, False))
    router.dispatch(PlaySound(RAIN, True, 100, 0.0))
    settle(service)
    assert pygame.mixer.get_init() == (48_000, -16, 2)
    rain = EFFECT_CHANNELS[0]
    assert service.backend.channel_busy(rain)
    before = service.music.position(service.now())
    assert before == pytest.approx(4.0, abs=0.1)
    old_rain = service.cache.get(("snd", RAIN), 0)

    service.set_mono(True)
    assert pygame.mixer.get_init() == (48_000, -16, 1)
    assert service.music.current is not None and service.music.current.file == FESTIVAL
    assert service.music.position(service.now()) == pytest.approx(4.0, abs=0.1)
    assert pygame.mixer.music.get_busy()
    settle(service)
    assert service.backend.channel_busy(rain)                    # the loop restarted
    assert service.cache.get(("snd", RAIN), 0) is not old_rain   # decoded for the new mixer

    service.set_mono(False)
    assert pygame.mixer.get_init() == (48_000, -16, 2)
    settle(service)
    assert pygame.mixer.music.get_busy() and service.backend.channel_busy(rain)
    assert service.music.position(service.now()) == pytest.approx(4.0, abs=0.2)
