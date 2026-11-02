"""Story effects and voice on Service S (AC-F08-26, 28, 29; F08 ``04`` §7.2, G1, I-10,
I-13(a))."""

import logging

import pytest

from engine.audio.limits import EFFECT_CHANNELS
from engine.audio.volume import amp, curve, quantize
from engine.runtime.commands import EndVoice, PlaySound, PlayVoice, StopSound, StopVoice
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import QUERIES, ogg_bytes

AUDIO_LOG = "vn.audio"


def one_shot(file: str, volume: int = 100, fadein: float | None = None) -> PlaySound:
    return PlaySound(file, False, volume, fadein)


def loop(file: str, volume: int = 100, fadein: float | None = None) -> PlaySound:
    return PlaySound(file, True, volume, fadein)


def add_loops(s, count: int) -> list[str]:
    files = []
    for index in range(count):
        file = f"sfx/l{index:02d}.ogg"
        s.add(file, ogg_bytes(2.0, salt=b"loop" + bytes([index])), 2.0)
        files.append(file)
    return files


def add_shots(s, count: int, seconds: float = 30.0) -> list[str]:
    files = []
    for index in range(count):
        file = f"sfx/s{index:02d}.ogg"
        s.add(file, ogg_bytes(seconds, salt=b"shot" + bytes([index])), seconds)
        files.append(file)
    return files


def audio_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == AUDIO_LOG]


# --- AC-F08-26 ------------------------------------------------------------------------------

def test_ac_f08_26_sixteen_one_shots_in_one_burst(service_s):
    s = service_s
    files = add_shots(s, 16)
    s.feed(*(one_shot(f) for f in files))
    busy = s.mixer.busy_channels()
    assert busy == set(EFFECT_CHANNELS)
    assert {s.mixer.name_on(c) for c in busy} == set(files)
    touched = {call[2][0] for call in s.mixer.actions() if call[1].startswith("channel_")}
    assert touched.isdisjoint({0, 1, 2, 3, 4})


def test_ac_f08_26_the_17th_one_shot_reuses_the_oldest(service_s):
    s = service_s
    files = add_shots(s, 17)
    for file in files[:16]:
        s.feed(one_shot(file))
        s.clock.now += 0.01
    oldest = next(c for c in EFFECT_CHANNELS if s.mixer.name_on(c) == files[0])
    before = len(s.mixer.calls)
    s.feed(one_shot(files[16]))
    new = [c[1:] for c in s.mixer.calls[before:] if c[1] in ("channel_stop", "channel_play")]
    assert new == [("channel_stop", (oldest,)), ("channel_play", (oldest, files[16], 0))]
    assert s.mixer.name_on(oldest) == files[16]
    assert len(s.mixer.busy_channels()) == 16


def test_ac_f08_26_fifteen_loops_and_a_one_shot(service_s):
    s = service_s
    loops = add_loops(s, 15)
    shots = add_shots(s, 2)
    s.feed(*(loop(f) for f in loops), one_shot(shots[0]))
    shot_channel = next(c for c in EFFECT_CHANNELS if s.mixer.name_on(c) == shots[0])
    before = len(s.mixer.calls)
    s.feed(one_shot(shots[1]))
    assert s.mixer.name_on(shot_channel) == shots[1]
    assert [c[1:] for c in s.mixer.actions("channel_stop", "channel_play")
            if c in s.mixer.calls[before:]] == [
        ("channel_stop", (shot_channel,)), ("channel_play", (shot_channel, shots[1], 0))]
    assert {s.mixer.name_on(c) for c in s.mixer.busy_channels()} == set(loops) | {shots[1]}


def test_ac_f08_26_sixteen_loops_drop_the_next_one_shot(service_s, caplog):
    s = service_s
    loops = add_loops(s, 16)
    s.feed(*(loop(f) for f in loops))
    before = len(s.mixer.calls)
    with caplog.at_level(logging.WARNING, logger=AUDIO_LOG):
        s.feed(one_shot("sfx/door.ogg"))
    assert not [c for c in s.mixer.actions() if c in s.mixer.calls[before:]
                and c[1] in ("channel_play", "channel_stop")]
    records = audio_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert "audio/sfx/door.ogg wasn't played" in records[0].getMessage()
    assert {s.mixer.name_on(c) for c in s.mixer.busy_channels()} == set(loops)


def test_ac_f08_26_a_playing_loop_only_ramps_its_volume(service_s):
    s = service_s
    s.feed(loop("sfx/rain.ogg"))
    rain = next(iter(s.mixer.busy_channels()))
    assert s.mixer.volumes[rain] == quantize(amp(100, 80, 100))
    before = len(s.mixer.calls)
    s.feed(loop("sfx/rain.ogg", volume=80, fadein=2.0))
    assert not [c for c in s.mixer.calls[before:] if c[1] == "channel_play"]
    s.advance(1.0)
    middle = s.mixer.volumes[rain]
    assert quantize(amp(100, 80, 80)) < middle < quantize(amp(100, 80, 100))
    assert middle == quantize(curve(100) * curve(80) * (curve(100) + curve(80)) / 2)
    s.advance(1.0)
    assert s.mixer.volumes[rain] == quantize(amp(100, 80, 80))
    assert s.mixer.busy_channels() == {rain}


def test_ac_f08_26_a_loop_and_a_one_shot_of_the_same_file(service_s):
    s = service_s
    s.feed(loop("sfx/rain.ogg"), one_shot("sfx/rain.ogg"))
    plays = s.mixer.actions("channel_play")
    assert [(c[2][1], c[2][2]) for c in plays] == [("sfx/rain.ogg", -1), ("sfx/rain.ogg", 0)]
    assert plays[0][2][0] != plays[1][2][0]


def three_effects_with_voice_and_pool(s) -> set[int]:
    """Three story effects, and stand-ins on the voice channel and a pool channel (steps 6
    and 7 play them; music has no channel, step 5). Returns the story channels."""
    s.add("sfx/bell.ogg", ogg_bytes(30.0, salt=b"bell"), 30.0)
    s.add("sfx/gong.ogg", ogg_bytes(30.0, salt=b"gong"), 30.0)       # for a later burst
    s.feed(loop("sfx/rain.ogg"), loop("sfx/crowd.ogg"), one_shot("sfx/bell.ogg"))
    story = set(s.mixer.busy_channels())
    s.mixer.occupy(0, "voice/hana_014.ogg")
    s.mixer.occupy(2, "ui/click.ogg")
    return story


def test_ac_f08_26_stop_every_effect_at_once(service_s):
    s = service_s
    story = three_effects_with_voice_and_pool(s)
    before = len(s.mixer.calls)
    s.feed(StopSound(None, None))                                     # sound_fadeout 0
    stops = [c[2][0] for c in s.mixer.calls[before:] if c[1] == "channel_stop"]
    assert sorted(stops) == sorted(story)
    assert s.mixer.busy_channels() == {0, 2}


def test_ac_f08_26_stop_every_effect_with_a_fade(service_s):
    """I-13(a): ``channel_fadeout(c, 1000)`` is an engine ramp to 0 over 1 s, then
    ``channel_stop(c)``; an effect played in the next burst plays normally."""
    s = service_s
    story = three_effects_with_voice_and_pool(s)
    s.clock.now += 0.1
    before = len(s.mixer.calls)
    s.feed(StopSound(None, 1.0))
    assert not [c for c in s.mixer.calls[before:] if c[1] != "channel_busy"]
    start = dict(s.mixer.volumes)
    s.advance(0.5)
    for channel in story:
        assert 0.0 < s.mixer.volumes[channel] < start[channel]
    s.feed(one_shot("sfx/gong.ogg"))                                  # the next burst
    door = next(c for c in s.mixer.busy_channels() if s.mixer.name_on(c) == "sfx/gong.ogg")
    assert door not in story
    assert s.mixer.volumes[door] == quantize(amp(100, 80, 100))
    s.advance(0.49)
    assert s.mixer.busy_channels() >= story
    s.advance(0.02)                                                   # 1.01 s after the stop
    stopped = {c[2][0] for c in s.mixer.calls if c[1] == "channel_stop"}
    assert stopped == story
    assert s.mixer.busy_channels() == {door, 0, 2}


def test_ac_f08_26_stop_when_quiet_calls_nothing(service_s):
    s = service_s
    s.feed(StopSound(None, 1.0))
    s.feed(StopSound("sfx/door.ogg", None))
    assert s.mixer.calls == []


# --- More of §7.2 ------------------------------------------------------------------------------

def test_stop_one_file_leaves_the_others(service_s):
    s = service_s
    s.feed(loop("sfx/crowd.ogg"), one_shot("sfx/crowd.ogg"), loop("sfx/rain.ogg"))
    rain = next(c for c in s.mixer.busy_channels() if s.mixer.name_on(c) == "sfx/rain.ogg")
    s.feed(StopSound("sfx/crowd.ogg", 1.5))
    s.advance(1.5)
    assert s.mixer.busy_channels() == {rain}


def test_a_fade_in_starts_at_zero_and_ramps_up(service_s):
    s = service_s
    s.feed(one_shot("sfx/rain.ogg", volume=50, fadein=1.0))
    channel = next(iter(s.mixer.busy_channels()))
    first = [c[1:] for c in s.mixer.actions("channel_volume", "channel_play")][:2]
    assert first == [("channel_volume", (channel, 0.0)),
                     ("channel_play", (channel, "sfx/rain.ogg", 0))]
    s.advance(0.5)
    assert s.mixer.volumes[channel] == quantize(curve(80) * curve(50) * 0.5)
    s.advance(0.5)
    assert s.mixer.volumes[channel] == quantize(amp(100, 80, 50))


def test_default_sound_fadein_comes_from_config(tmp_path):
    from engine.core.config_schema import AudioConfig

    s = make_service(tmp_path, AudioConfig(sound_fadein=2.0, sound_fadeout=1.0))
    s.feed(loop("sfx/rain.ogg"))
    channel = next(iter(s.mixer.busy_channels()))
    assert s.mixer.volumes[channel] == 0.0
    s.advance(2.0)
    assert s.mixer.volumes[channel] == quantize(amp(100, 80, 100))
    s.feed(StopSound(None, None))                                     # sound_fadeout 1.0
    assert channel in s.mixer.busy_channels()
    s.advance(1.0)
    assert not s.mixer.busy_channels()


def test_g1_a_volume_change_mid_ramp_applies_at_the_next_update(service_s):
    s = service_s
    s.feed(loop("sfx/rain.ogg", fadein=2.0))
    channel = next(iter(s.mixer.busy_channels()))
    s.advance(0.5)
    s.service.set_volumes(100, 70, 20, 100)                       # applies in this call
    assert s.mixer.volumes[channel] == quantize(curve(20) * 0.25)
    s.advance(1.5)
    assert s.mixer.volumes[channel] == quantize(amp(100, 20, 100))
    s.service.set_volumes(0, 70, 20, 100)
    assert s.mixer.volumes[channel] == 0.0


def test_ended_effects_free_their_channel_and_cache_hold(service_s):
    s = service_s
    s.feed(one_shot("sfx/door.ogg"))
    key = ("snd", "sfx/door.ogg")
    assert s.cache._holds.get(key) == 1
    s.advance(0.4)
    assert s.service.effects.slots
    s.advance(0.2)                                                 # door is 0.5 s long
    assert not s.service.effects.slots
    assert key not in s.cache._holds
    assert key in s.cache                                          # still cached


def test_decoded_sounds_are_cached_and_charged(service_s):
    s = service_s
    s.feed(one_shot("sfx/door.ogg"))
    s.advance(1.0)
    s.feed(one_shot("sfx/door.ogg"))
    assert s.mixer.decoded == ["sfx/door.ogg"]
    assert s.cache.cost(("snd", "sfx/door.ogg")) == int(0.5 * 192_000) + 256


def test_an_effect_that_ended_frees_its_slot_for_the_17th(service_s):
    """A one-shot that ended before the next update is reused without a stop."""
    s = service_s
    files = add_shots(s, 16, seconds=0.2)
    s.feed(*(one_shot(f) for f in files))
    s.clock.now += 0.3                                                 # no update yet
    before = len(s.mixer.calls)
    s.feed(one_shot("sfx/rain.ogg"))
    assert not [c for c in s.mixer.calls[before:] if c[1] == "channel_stop"]
    assert "sfx/rain.ogg" in {s.mixer.name_on(c) for c in s.mixer.busy_channels()}


def test_stop_story_audio_fades_the_effects(service_s):
    s = service_s
    s.feed(loop("sfx/rain.ogg"))
    s.service.stop_story_audio(0.5)
    s.advance(0.25)
    assert s.mixer.busy_channels()
    s.advance(0.25)
    assert not s.mixer.busy_channels()


def test_shutdown_closes_the_backend_and_ignores_later_calls(service_s):
    s = service_s
    s.feed(loop("sfx/rain.ogg"))
    s.service.shutdown()
    s.service.shutdown()
    assert s.mixer.closed and not s.cache._holds
    calls = len(s.mixer.calls)
    s.feed(loop("sfx/crowd.ogg"), StopSound(None, None))
    s.service.update(200.0)
    s.service.stop_story_audio()
    assert len(s.mixer.calls) == calls


@pytest.mark.parametrize("seconds", [0.25, 30.0])
def test_one_shots_play_once_and_loops_forever(service_s, seconds):
    s = service_s
    s.add("sfx/x.ogg", ogg_bytes(seconds, salt=b"x"), seconds)
    s.feed(one_shot("sfx/x.ogg"), loop("sfx/door.ogg"))
    assert [c[2][2] for c in s.mixer.actions("channel_play")] == [0, -1]


# --- Voice: AC-F08-28, AC-F08-29 (04 §7.2 voice; I-13(a)) -----------------------------------

HANA_014, HANA_015, HANA_041 = "voice/hana_014.ogg", "voice/hana_015.ogg", "voice/hana_041.ogg"
VOICE_CALLS = ("channel_stop", "channel_play")


def voice_calls(s, since: int = 0) -> list[tuple]:
    """The channel-0 stops and plays in ``s.mixer.calls[since:]``, as ``(name, *args)``."""
    return [(c[1], *c[2]) for c in s.mixer.calls[since:]
            if c[1] in VOICE_CALLS and c[2][0] == 0]


def test_ac_f08_28_play_voice_stops_channel_0_then_plays_once(service_s):
    s = service_s
    s.feed(PlayVoice("s1", HANA_014, False))
    assert voice_calls(s) == [("channel_stop", 0), ("channel_play", 0, HANA_014, 0)]
    names = [c[1] for c in s.mixer.actions()]
    assert names.index("channel_volume") < names.index("channel_play")
    assert s.mixer.actions("channel_volume") == [
        (100.0, "channel_volume", (0, quantize(amp(100, 100, 100))))]
    assert s.mixer.name_on(0) == HANA_014


def test_ac_f08_28_the_next_voice_replaces_the_one_playing(service_s):
    s = service_s
    s.feed(PlayVoice("s1", HANA_014, False))
    s.advance(0.5)
    before = len(s.mixer.calls)
    s.feed(PlayVoice("s2", HANA_015, False))
    assert voice_calls(s, before) == [("channel_stop", 0), ("channel_play", 0, HANA_015, 0)]
    assert s.mixer.name_on(0) == HANA_015
    assert not s.service.voice_playing("s1") and s.service.voice_playing("s2")


def test_ac_f08_28_end_voice_stops_only_its_own_line(service_s):
    s = service_s
    s.feed(PlayVoice("s1", HANA_014, False), PlayVoice("s2", HANA_015, False))
    before = len(s.mixer.calls)
    s.feed(EndVoice("s1"))
    assert [c for c in s.mixer.calls[before:] if c[1] not in QUERIES] == []
    assert s.service.voice_playing("s2")
    s.feed(EndVoice("s2"))
    assert voice_calls(s, before) == [("channel_stop", 0)]
    assert not s.service.voice_playing()
    s.feed(EndVoice("s2"))                                   # already stopped: nothing
    assert voice_calls(s, before) == [("channel_stop", 0)]


def test_ac_f08_28_stop_voice_at_once_by_default(service_s):
    s = service_s
    s.feed(PlayVoice("s1", HANA_014, False))
    before = len(s.mixer.calls)
    s.feed(StopVoice(None))
    assert voice_calls(s, before) == [("channel_stop", 0)]
    assert not s.service.voice_playing()
    s.feed(StopVoice(None), StopVoice(0.5))                  # silent: no call
    assert voice_calls(s, before) == [("channel_stop", 0)]


def test_ac_f08_28_stop_voice_with_a_fade_ramps_then_stops(service_s):
    """I-13(a): ``channel_fadeout(0, 500)`` is an engine ramp to 0 over 0.5 s, then
    ``channel_stop(0)``."""
    s = service_s
    s.add("voice/long.ogg", ogg_bytes(10.0, salt=b"long"), 10.0)
    s.feed(PlayVoice("s1", "voice/long.ogg", False))
    before = len(s.mixer.calls)
    s.feed(StopVoice(0.5))
    assert voice_calls(s, before) == []
    s.advance(0.25)
    assert s.mixer.volumes[0] == quantize(0.5)
    assert s.service.voice_playing("s1")
    s.advance(0.24)
    assert 0.0 < s.mixer.volumes[0] < 0.05 and voice_calls(s, before) == []
    s.advance(0.02)
    assert voice_calls(s, before) == [("channel_stop", 0)]
    assert not s.service.voice_playing() and not s.cache._holds


def test_ac_f08_28_voice_playing_follows_the_channel(service_s):
    s = service_s
    assert not s.service.voice_playing() and not s.service.voice_playing("s1")
    s.feed(PlayVoice("s2", HANA_015, False))
    assert s.service.voice_playing() and s.service.voice_playing("s2")
    assert not s.service.voice_playing("s1")
    s.clock.now += 1.49
    assert s.service.voice_playing("s2")
    s.clock.now += 0.02                                      # hana_015 is 1.5 s: it ended
    assert not s.service.voice_playing("s2") and not s.service.voice_playing()
    s.advance(0.0)
    assert s.service.voice.slot is None and not s.cache._holds
    before = len(s.mixer.calls)
    s.feed(EndVoice("s2"))                                   # its line advanced afterwards
    assert voice_calls(s, before) == []


def test_ac_f08_28_voice_never_loops_and_effects_never_take_channel_0(service_s):
    s = service_s
    files = add_shots(s, 17)
    s.feed(PlayVoice("s1", HANA_014, False), PlayVoice("s2", HANA_015, False),
           PlayVoice("s3", HANA_041, False))
    s.feed(*(one_shot(f) for f in files))
    assert {c[2][2] for c in s.mixer.actions("channel_play") if c[2][0] == 0} == {0}
    assert s.mixer.name_on(0) == HANA_041
    others = {c[2][0] for c in s.mixer.actions() if c[1].startswith("channel_")} - {0}
    assert others <= set(EFFECT_CHANNELS)


def test_voice_volume_is_amp_master_voice_and_follows_the_settings(tmp_path):
    from engine.core.config_schema import AudioConfig

    s = make_service(tmp_path, AudioConfig(master_volume=80, voice_volume=60))
    s.feed(PlayVoice("s1", HANA_014, False))
    assert s.mixer.volumes[0] == quantize(amp(80, 60, 100))
    s.service.set_volumes(40, 70, 80, 90)
    assert s.mixer.volumes[0] == quantize(amp(40, 90, 100))      # in the same call
    s.service.set_volumes(0, 70, 80, 90)
    assert s.mixer.volumes[0] == 0.0


def test_a_volume_change_mid_stop_ramp_applies_at_once(service_s):
    s = service_s
    s.add("voice/long.ogg", ogg_bytes(10.0, salt=b"long"), 10.0)
    s.feed(PlayVoice("s1", "voice/long.ogg", False), StopVoice(1.0))
    s.advance(0.5)
    assert s.mixer.volumes[0] == quantize(0.5)
    s.service.set_volumes(100, 70, 80, 50)
    assert s.mixer.volumes[0] == quantize(curve(50) * 0.5)


def test_a_missing_voice_is_silent_w26_and_a_restored_one_w29(service_s, caplog):
    s = service_s
    with caplog.at_level(logging.WARNING, logger=AUDIO_LOG):
        s.feed(PlayVoice("s1", "voice/zzqx.ogg", False), PlayVoice("s1", "voice/zzqx.ogg", False),
               PlayVoice("s2", "voice/gone.ogg", True))
    assert [c[1] for c in s.mixer.actions()] == ["channel_stop"] * 3
    records = audio_records(caplog)
    assert [r.getMessage() for r in records] == [
        "audio/voice/zzqx.ogg is missing, so it plays as silence.",
        "A restored game plays audio/voice/gone.ogg, which is missing, so the voice is silent."]
    assert [r.code for r in records] == ["W26", "W29"]
    assert not s.service.voice_playing()


def test_a_blocked_voice_path_says_voice(service_s, caplog):
    with caplog.at_level(logging.WARNING, logger=AUDIO_LOG):
        service_s.feed(PlayVoice("s1", "../../ZZMARK.ogg", False))
    (record,) = audio_records(caplog)
    assert record.levelno == logging.ERROR and record.code == "W29"
    assert record.getMessage().endswith(", so the voice is silent.")


def test_voice_is_ignored_while_skipping_unless_restored(service_s):
    """04 §7.2 (PR-F08-24); step 7's ``set_skipping`` sets ``voice.skipping``."""
    s = service_s
    s.service.voice.skipping = True
    s.feed(PlayVoice("s1", HANA_014, False))
    assert s.mixer.calls == []
    s.feed(PlayVoice("s2", HANA_015, True))
    assert voice_calls(s) == [("channel_stop", 0), ("channel_play", 0, HANA_015, 0)]


def test_a_voice_line_is_decoded_once_and_held_while_it_plays(service_s):
    s = service_s
    s.feed(PlayVoice("s1", HANA_014, False))
    assert s.cache._holds
    s.feed(EndVoice("s1"))
    assert not s.cache._holds
    s.feed(PlayVoice("s9", HANA_014, False))
    assert s.mixer.actions("decode") == [(100.0, "decode", (HANA_014,))]
    assert s.mixer.name_on(0) == HANA_014


def test_stop_story_audio_fades_the_voice_and_shutdown_releases_it(service_s):
    s = service_s
    s.add("voice/long.ogg", ogg_bytes(10.0, salt=b"long"), 10.0)
    s.feed(PlayVoice("s1", "voice/long.ogg", False))
    s.service.stop_story_audio(0.5)
    s.advance(0.25)
    assert s.service.voice_playing()
    s.advance(0.26)
    assert not s.service.voice_playing() and 0 not in s.mixer.busy_channels()
    s.feed(PlayVoice("s2", HANA_014, False))
    s.service.shutdown()
    assert not s.cache._holds and not s.service.voice_playing()
    calls = len(s.mixer.calls)
    s.feed(PlayVoice("s3", HANA_015, False), EndVoice("s3"), StopVoice(None))
    s.service.set_voice_sustain(True)
    assert len(s.mixer.calls) == calls


def test_ac_f08_29_sustain_lets_the_voice_play_to_its_end(service_s):
    s = service_s
    s.service.set_voice_sustain(True)
    s.feed(PlayVoice("s1", HANA_014, False))
    before = len(s.mixer.calls)
    s.advance(0.5)
    s.feed(EndVoice("s1"))
    assert voice_calls(s, before) == []
    s.advance(0.99)
    assert s.service.voice_playing("s1")
    s.advance(0.02)                                          # 1.51 s: it ended by itself
    assert not s.service.voice_playing() and voice_calls(s, before) == []


def test_ac_f08_29_with_sustain_the_next_voice_and_stop_voice_still_stop_it(service_s):
    s = service_s
    s.service.set_voice_sustain(True)
    s.feed(PlayVoice("s1", HANA_014, False), EndVoice("s1"))
    before = len(s.mixer.calls)
    s.feed(PlayVoice("s2", HANA_015, False))
    assert voice_calls(s, before) == [("channel_stop", 0), ("channel_play", 0, HANA_015, 0)]
    s.feed(EndVoice("s2"))
    assert s.service.voice_playing("s2")
    before = len(s.mixer.calls)
    s.feed(StopVoice(None))
    assert voice_calls(s, before) == [("channel_stop", 0)]
    assert not s.service.voice_playing()


def test_ac_f08_29_sustain_is_off_by_default_and_can_be_turned_off(service_s):
    s = service_s
    s.feed(PlayVoice("s1", HANA_014, False), EndVoice("s1"))
    assert not s.service.voice_playing()
    s.service.set_voice_sustain(True)
    s.service.set_voice_sustain(False)
    before = len(s.mixer.calls)
    s.feed(PlayVoice("s2", HANA_015, False), EndVoice("s2"))
    assert voice_calls(s, before) == [("channel_stop", 0), ("channel_play", 0, HANA_015, 0),
                                      ("channel_stop", 0)]
