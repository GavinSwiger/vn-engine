"""The volume curve and quantization (AC-F08-31; ``07`` I-10), and the levels Service S sends
(AC-F08-30)."""

from engine.audio.volume import VOLUME_STEPS, Volumes, amp, curve, quantize


def test_ac_f08_31_curve_values():
    assert curve(0) == 0.0
    assert curve(50) == 0.25
    assert curve(70) == 0.49
    assert curve(100) == 1.0
    values = [curve(v) for v in range(101)]
    assert all(a < b for a, b in zip(values, values[1:]))       # strictly increasing


def test_ac_f08_31_every_triple_is_at_most_one_and_one_only_at_full():
    """All 101³ (master, channel, relative) triples: the amplitude (before rounding, I-10)
    is ≤ 1.0 and exactly 1.0 only for (100, 100, 100); the quantized level sent to the
    backend keeps both properties."""
    curves = [curve(v) for v in range(101)]
    ones = []
    below_one = 0.0
    for master in range(101):
        cm = curves[master]
        for channel in range(101):
            mc = cm * curves[channel]
            levels = [mc * cr for cr in curves]
            top = max(levels)
            assert top <= 1.0
            if top == 1.0:
                ones.extend((master, channel, r) for r, level in enumerate(levels)
                            if level == 1.0)
            below_one = max(below_one, max((lv for lv in levels if lv < 1.0), default=0.0))
    assert ones == [(100, 100, 100)]
    assert amp(100, 100, 100) == 1.0
    # quantize is monotonic, so the loudest level under 1.0 still rounds below 1.0.
    assert below_one <= 0.9801
    assert quantize(below_one) < 1.0 and quantize(1.0) == 1.0


def test_quantize_rounds_to_sdl_steps_and_keeps_non_zero_audible():
    assert quantize(0.0) == 0.0
    assert quantize(-0.1) == 0.0
    assert quantize(1.0) == 1.0
    assert quantize(0.5) == 64 / VOLUME_STEPS
    assert quantize(0.0064) == 1 / VOLUME_STEPS          # I-10: master 20 × sound 40
    assert amp(20, 40, 100) == 0.0064 or abs(amp(20, 40, 100) - 0.0064) < 1e-12
    assert quantize(amp(20, 40, 100)) == 1 / VOLUME_STEPS
    assert quantize(0.1) == 13 / VOLUME_STEPS              # I-10: 20,000 × 13/128 at 10 %
    assert quantize(1e-9) == 1 / VOLUME_STEPS


def test_volumes_defaults_and_sound_gain():
    volumes = Volumes()
    assert (volumes.master, volumes.music, volumes.sound, volumes.voice) == (100, 70, 80, 100)
    assert volumes.sound_gain() == curve(100) * curve(80)


# --- AC-F08-30 — Volumes combine and apply within 0.1 s (Service S) -------------------------------

def _busy_levels(s) -> dict:
    """Every busy channel's level and the music's."""
    levels = {channel: s.mixer.volumes[channel] for channel in s.mixer.busy_channels()}
    levels["music"] = s.mixer.music_level
    return levels


def _everything_playing(tmp_path, cfg=None):
    from engine.runtime.commands import PlayMusic, PlaySound, PlayVoice
    from tests.audio.conftest import make_service

    s = make_service(tmp_path, cfg)
    s.feed(PlayMusic("bgm/festival.ogg", True, 50, None, None, False, None, False),
           PlaySound("sfx/rain.ogg", True, 40, None), PlaySound("sfx/crowd.ogg", True, 100, None),
           PlaySound("sfx/firework.ogg", False, 70, None),
           PlayVoice("s1", "voice/hana_014.ogg", False))
    s.service.play_ui("sfx/door.ogg", volume=50)
    return s


def test_ac_f08_30_each_level_is_amp_master_channel_relative(tmp_path):
    s = _everything_playing(tmp_path)
    assert s.mixer.music_level == quantize(amp(100, 70, 50))
    assert s.mixer.volumes[5] == quantize(amp(100, 80, 40))          # rain
    assert s.mixer.volumes[0] == quantize(amp(100, 100, 100))        # the voice
    assert s.mixer.volumes[2] == quantize(amp(100, 80, 50))          # play_ui(volume=50)


def test_ac_f08_30_config_volumes(tmp_path):
    from engine.core.config_schema import AudioConfig
    from engine.runtime.commands import PlayMusic
    from tests.audio.conftest import make_service

    s = make_service(tmp_path, AudioConfig(master_volume=50, music_volume=60))
    s.feed(PlayMusic("bgm/festival.ogg", True, 100, None, None, False, None, False))
    assert s.mixer.music_level == quantize(amp(50, 60, 100))


def test_ac_f08_30_set_volumes_reaches_every_busy_channel_in_the_same_call(tmp_path):
    s = _everything_playing(tmp_path)
    busy = s.mixer.busy_channels()
    assert busy == {0, 2, 5, 6, 7}
    s.mixer.calls.clear()
    s.service.set_volumes(40, 70, 80, 100)
    assert {t for t, _, _ in s.mixer.calls} == {s.clock()}            # no frame in between
    assert _busy_levels(s) == {
        "music": quantize(amp(40, 70, 50)), 0: quantize(amp(40, 100, 100)),
        2: quantize(amp(40, 80, 50)), 5: quantize(amp(40, 80, 40)),
        6: quantize(amp(40, 80, 100)), 7: quantize(amp(40, 80, 70))}
    s.service.set_volumes(0, 70, 80, 100)
    assert set(_busy_levels(s).values()) == {0.0}


def test_ac_f08_30_volumes_are_never_story_state(tmp_path):
    import json

    from tests.runtime.story import load_files, start
    from tests.script.helpers import template_a

    root = tmp_path / "story"
    root.mkdir()
    interp = start(load_files(root, {"main.vns": template_a(
        S='play music "bgm/festival.ogg" volume 50⏎"Line."')}))
    s = _everything_playing(tmp_path)
    before = json.dumps(interp.checkpoint().to_json(), sort_keys=True)
    s.service.set_volumes(40, 70, 80, 100)
    s.service.set_volumes(0, 0, 0, 0)
    after = json.dumps(interp.checkpoint().to_json(), sort_keys=True)
    assert after == before
    assert "master" not in after and "voice_volume" not in after
