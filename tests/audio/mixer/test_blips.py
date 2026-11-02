"""AC-F06-08 on the real mixer (F06 ``SPEC.md`` §5; ``07`` I-3, I-5): the loader's worker
builds a blip's five variants as real Sounds whose samples are ``pitch.resample`` of the
decoded ones, in stereo and, after ``set_mono``, in mono (2-byte frames); a pitched file over
0.5 s is one Sound. SDL's dummy driver (``conftest.py``'s ``dummy``)."""

import pytest

from engine.audio.limits import BLIP_CHANNEL
from engine.audio.pitch import BLIP_STEPS, resample, speed
from tests.audio.mixer.conftest import add, settle
from tests.fixtures.F08.make_audio import tone_wav

pytestmark = pytest.mark.mixer

TONE, LONG = "blips/tone.wav", "blips/long.wav"


def test_ac_f06_08_variants_are_resampled_real_sounds_in_stereo_and_mono(dummy):
    add(dummy.root, TONE, tone_wav(0.1))
    add(dummy.root, LONG, tone_wav(0.6))
    service, _ = dummy()
    for mono, frame_bytes in ((False, 4), (True, 2)):
        service.set_mono(mono)
        service.play_blip(TONE, spread=0.2, step=2)
        settle(service)
        entry = service.cache.get(("blip", TONE, 0.2), 0)
        raw = entry.pick(0).get_raw()
        assert len(raw) == round(0.1 * 48_000) * frame_bytes
        assert [one.get_raw() for one in entry.sounds] == [
            resample(raw, speed(0.2, step), frame_bytes) for step in BLIP_STEPS]
        assert service.blip.playing == ("blip", TONE, 0.2)
        assert service.backend.channel_busy(BLIP_CHANNEL)
    service.play_blip(LONG, spread=0.2, step=2)
    settle(service)
    assert service.cache.get(("blip", LONG, 0.2), 0).too_long
