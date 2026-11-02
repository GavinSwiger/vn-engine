"""Restore, skip, and the seams on Service S (F08 ``06`` §1.6, §1.7; ``04`` §7.6, §5.2):
AC-F08-45 (reconcile), 47 (the line's voice after a restore), the unit half of 48 (skip),
52 (seams), 53 (track-started notice); and with a live story (``tests/runtime/story.py``),
AC-F08-14 (a rejected state changes nothing) and 46 (load, rollback, roll-forward).

Fades of effects and voice are engine ramps to 0 followed by ``channel_stop`` (I-13(a)), so
AC-45's ``channel_fadeout(c, n)`` reads as: the channel's level falls over n ms, then
``channel_stop(c)``."""

import json
import logging
from pathlib import Path

import pytest

from engine.audio.limits import EFFECT_CHANNELS, UI_CHANNELS, VOICE_CHANNEL
from engine.audio.music import Phase
from engine.audio.volume import amp, quantize
from engine.core.config_schema import AudioConfig
from engine.runtime.audio import AudioState, MusicEntry, SoundLoop
from engine.runtime.commands import (AudioRestore, EndVoice, PlayMusic, PlaySound, PlayVoice,
                                     QueueMusic, Say, StopMusic, StopSound, StopVoice)
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import GameState, StateInvalid
from tests.audio.conftest import make_service
from tests.audio.test_music_player import (FESTIVAL, LOOP, OMEN, PASSY, PM, QM, SHRINE, level,
                                           music, same, starts)
from tests.fakes.fake_mixer import mp3_bytes, ogg_bytes

RAIN, CROWD, DOOR = "sfx/rain.ogg", "sfx/crowd.ogg", "sfx/door.ogg"
FIREWORK = "sfx/firework.ogg"
WIND = "sfx/wind.ogg"
HANA_014, HANA_015 = "voice/hana_014.ogg", "voice/hana_015.ogg"
AUDIO = (AudioRestore, EndVoice, PlayMusic, PlaySound, PlayVoice, QueueMusic, StopMusic,
         StopSound, StopVoice)
F08 = Path(__file__).resolve().parents[1] / "fixtures" / "F08"


@pytest.fixture
def s(tmp_path):
    service = make_service(tmp_path)
    service.add(PASSY, mp3_bytes(b"festival"), 12.0)
    service.add(WIND, ogg_bytes(2.0, salt=b"wind"), 2.0)
    return service


def restore(music=(), sounds=(), reason="restore") -> AudioRestore:
    return AudioRestore(AudioState(tuple(MusicEntry(*e) for e in music),
                                   tuple(SoundLoop(*e) for e in sounds)), reason)


def channel_of(s, name: str) -> int:
    channels = [c for c in sorted(s.mixer.busy_channels()) if s.mixer.name_on(c) == name]
    assert len(channels) == 1, (name, channels)
    return channels[0]


def stops(s, since: float) -> list[tuple[float, int]]:
    return [(round(t - 100.0, 3), args[0]) for t, name, args in s.mixer.actions("channel_stop")
            if t >= since]


def fade_out_of(s, channel: int, t0: float, ms: int) -> None:
    """``channel_fadeout(channel, ms)`` as I-13(a) reads it: the level falls from ``t0`` and
    the channel stops ``ms`` later."""
    levels = [args[1] for t, name, args in s.mixer.actions("channel_volume")
              if args[0] == channel and t > t0]
    assert levels and levels == sorted(levels, reverse=True) and levels[-1] < levels[0]
    stopped = [round(t - t0, 3) for t, name, args in s.mixer.actions("channel_stop")
               if args[0] == channel and t >= t0]
    assert stopped and stopped[0] == pytest.approx(ms / 1000, abs=0.011), stopped


# --- AC-F08-45 — Reconcile, music --------------------------------------------------------------

def test_ac_f08_45_same_track_keeps_playing_and_ramps_to_the_new_volume(s):
    s.feed(PM(FESTIVAL))
    s.run(2.0)
    s.mixer.calls.clear()
    s.feed(restore([(FESTIVAL, True, 60)]))
    assert not s.mixer.actions("music_start", "music_stop", "music_fadeout")
    s.run(1.0)                                               # restore_fadein (G7)
    assert s.mixer.music_level == level(relative=60)


@pytest.mark.parametrize("target", [
    [(SHRINE, True, 100)],
    [(OMEN, False, 100), (SHRINE, True, 100)],
], ids=["shrine", "omen-then-shrine"])
def test_ac_f08_45_another_track_fades_out_then_the_looping_one_fades_in(s, target):
    s.feed(PM(FESTIVAL))
    s.run(2.0)
    t0 = s.clock()
    s.feed(restore(target))
    s.run(1.0)
    same(music(s, since=t0), [(2.0, "music_fadeout", 500), (2.0, "music_arm", "SILENT_WAV", 0),
                              (2.5, "music_start", SHRINE, LOOP, 0.0, 1000),
                              (2.5, "music_arm", "SILENT_WAV", 0)])
    assert OMEN not in [c[2] for c in starts(s)]


def test_ac_f08_45_no_looping_track_fades_to_quiet(s):
    s.feed(PM(FESTIVAL))
    s.run(2.0)
    t0 = s.clock()
    s.feed(restore([(OMEN, False, 100)]))
    s.run(1.0)
    assert music(s, since=t0)[0] == (2.0, "music_fadeout", 500)
    assert s.mixer.music_name() is None and s.service.music.phase is Phase.SILENT
    assert [c[2] for c in starts(s)] == [FESTIVAL]


def test_ac_f08_45_a_once_track_restarts_as_a_loop(s):
    s.feed(PM(FESTIVAL, loop=False))
    s.run(2.0)
    t0 = s.clock()
    s.feed(restore([(FESTIVAL, True, 100)]))
    s.run(1.0)
    found = music(s, since=t0)
    assert found[0] == (2.0, "music_fadeout", 500)
    same([c for c in found if c[1] == "music_start"],
         [(2.5, "music_start", FESTIVAL, LOOP, 0.0, 1000)])


def test_ac_f08_45_from_silence_the_track_starts_now(s):
    s.feed(restore([(FESTIVAL, True, 100)]))
    same(starts(s), [(0.0, "music_start", FESTIVAL, LOOP, 0.0, 1000)])


def test_ac_f08_45_zero_restore_fades_cut_and_start_at_once(tmp_path):
    s = make_service(tmp_path, AudioConfig(restore_fadeout=0.0, restore_fadein=0.0))
    s.feed(PM(FESTIVAL))
    s.run(2.0)
    t0 = s.clock()
    s.feed(restore([(SHRINE, True, 100)]))
    found = music(s, since=t0)
    assert [c[1:] for c in found if c[1] in ("music_stop", "music_start")] == [
        ("music_stop",), ("music_start", SHRINE, LOOP, 0.0, 0)]


def test_ac_f08_45_while_skipping_the_fades_are_200_ms(s):
    s.feed(PM(FESTIVAL), PlaySound(RAIN, True, 40, None))
    s.run(2.0)
    s.service.set_skipping(True)
    t0 = s.clock()
    s.feed(restore([(SHRINE, True, 100)], [(WIND, 100)]))
    s.run(1.0)
    same([c for c in music(s, since=t0) if c[1] != "music_arm"],
         [(2.0, "music_fadeout", 200), (2.2, "music_start", SHRINE, LOOP, 0.0, 200)])
    fade_out_of(s, EFFECT_CHANNELS[0], t0, 200)              # rain
    wind = channel_of(s, WIND)
    assert s.mixer.volumes[wind] == quantize(amp(100, 80, 100))


def test_ac_f08_45_a_sync_uses_the_play_defaults(s):
    s.feed(PM(FESTIVAL))
    s.run(2.0)
    t0 = s.clock()
    s.feed(restore([(OMEN, True, 100)], reason="sync"))
    s.run(1.0)
    same([c for c in music(s, since=t0) if c[1] != "music_arm"],
         [(2.0, "music_fadeout", 500), (2.5, "music_start", OMEN, LOOP, 0.0, 0)])


def test_ac_f08_45_restore_starts_the_track_from_zero_even_if_saved_mid_fade(s):
    """AC-46's last row on the service: a state saved 1.0 s into a 2.0 s fade-in restores
    the track from 0 with the 1.0 s restore fade-in."""
    s.feed(restore([(FESTIVAL, True, 100)]))
    same(starts(s), [(0.0, "music_start", FESTIVAL, LOOP, 0.0, 1000)])


# --- AC-F08-45 — Reconcile, effects and voice -----------------------------------------------------

def test_ac_f08_45_effects_keep_matching_loops_and_fade_the_rest(s):
    s.feed(PlaySound(RAIN, True, 40, None), PlaySound(CROWD, True, 100, None),
           PlaySound(FIREWORK, False, 100, None))                # a one-shot (1.0 s)
    s.run(0.1)
    rain, crowd, shot = channel_of(s, RAIN), channel_of(s, CROWD), channel_of(s, FIREWORK)
    t0 = s.clock()
    s.mixer.calls.clear()
    s.feed(restore(sounds=[(RAIN, 80), (WIND, 100)]))
    wind = channel_of(s, WIND)
    plays = s.mixer.actions("channel_play")
    assert [args[1] for _, _, args in plays] == [WIND]          # rain isn't played again
    assert plays[0][2] == (wind, WIND, -1)
    assert s.mixer.volumes[wind] == 0.0                         # the fade-in starts at 0
    s.run(0.5)
    assert s.mixer.volumes[wind] == quantize(amp(100, 80, 100) * 0.5)
    s.run(0.6)
    fade_out_of(s, crowd, t0, 500)
    fade_out_of(s, shot, t0, 500)
    assert rain not in [ch for _, ch in stops(s, t0)]
    assert s.mixer.volumes[rain] == quantize(amp(100, 80, 80))
    assert s.mixer.volumes[wind] == quantize(amp(100, 80, 100))
    assert s.mixer.busy_channels() == {rain, wind}


def test_ac_f08_45_a_loop_fading_out_is_kept_when_the_target_has_it(s):
    s.feed(PlaySound(RAIN, True, 40, None))
    s.run(0.1)
    s.feed(StopSound(RAIN, 2.0))
    s.run(0.5)
    rain = channel_of(s, RAIN)
    s.feed(restore(sounds=[(RAIN, 40)]))
    s.run(1.5)
    assert s.mixer.busy_channels() == {rain}
    assert s.mixer.volumes[rain] == quantize(amp(100, 80, 40))


def test_ac_f08_45_the_voice_fades_out_over_500_ms(s):
    s.feed(PlayVoice("s1", HANA_014, False))
    s.run(0.1)
    t0 = s.clock()
    s.feed(restore([(FESTIVAL, True, 100)]))
    s.run(0.6)
    fade_out_of(s, VOICE_CHANNEL, t0, 500)
    assert not s.service.voice_playing()


def test_a_new_game_fades_everything_out(s):
    s.feed(PM(FESTIVAL), PlaySound(RAIN, True, 40, None), PlayVoice("s1", HANA_014, False))
    s.run(0.2)
    s.feed(restore(reason="new_game"))
    s.run(0.6)
    assert s.mixer.busy_channels() == set() and s.mixer.music_name() is None


def test_a_sync_keeps_the_bursts_one_shots_and_the_voice(s):
    s.feed(PlaySound(DOOR, False, 100, None), PlaySound(CROWD, True, 100, None),
           PlayVoice("s1", HANA_014, False))
    crowd = channel_of(s, CROWD)
    s.feed(restore(sounds=[(RAIN, 40)], reason="sync"))
    assert {s.mixer.name_on(c) for c in s.mixer.busy_channels()} == {HANA_014, DOOR, RAIN}
    assert channel_of(s, RAIN) == crowd             # sound_fadeout 0: crowd stopped at once
    assert s.service.voice_playing("s1")


def test_restored_missing_and_blocked_effects_are_w29(s, caplog):
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        s.feed(restore(sounds=[("sfx/gone.ogg", 40), (RAIN, 40)]))
    assert caplog.messages == ["A restored game plays audio/sfx/gone.ogg, which is missing, "
                               "so the effect is silent."]
    assert s.mixer.name_on(channel_of(s, RAIN)) == RAIN


# --- AC-F08-47 — The line's voice plays again after a restore -------------------------------------

def test_ac_f08_47_the_restored_lines_voice_plays_while_skipping(s):
    s.service.set_skipping(True)
    s.feed(PlayVoice("s0", HANA_015, True))                     # a restored voice plays
    s.run(0.1)
    s.feed(restore([(FESTIVAL, True, 100)]))
    assert s.service.voice.slot.stopping                        # the 500 ms fade began
    s.mixer.calls.clear()
    s.feed(PlayVoice("s1", HANA_014, True))
    assert [c[1:] for c in s.mixer.actions("channel_stop", "channel_play")] == [
        ("channel_stop", (VOICE_CHANNEL,)), ("channel_play", (VOICE_CHANNEL, HANA_014, 0))]
    assert s.service.voice_playing("s1")


def test_ac_f08_47_the_voice_fade_is_not_capped_by_skipping(s):
    s.service.set_skipping(True)
    s.feed(PlayVoice("s0", HANA_015, True))
    s.run(0.1)
    t0 = s.clock()
    s.feed(restore([(FESTIVAL, True, 100)]))                    # an unvoiced line
    s.run(0.6)
    fade_out_of(s, VOICE_CHANNEL, t0, 500)


def test_ac_f08_47_a_restore_to_an_unvoiced_line_plays_no_voice(s):
    s.feed(restore([(FESTIVAL, True, 100)]))
    assert not [c for c in s.mixer.actions("channel_play") if c[2][0] == VOICE_CHANNEL]


# --- AC-F08-48 — Skip (unit half; the example-game half is F08 step 12) --------------------------

def test_ac_f08_48_skipping_ignores_one_shots_and_unrestored_voices(s):
    s.service.set_skipping(True)
    s.feed(PlaySound(DOOR, False, 100, None), PlayVoice("s1", HANA_014, False))
    assert s.mixer.calls == []


def test_ac_f08_48_skipping_caps_fades_at_200_ms(s):
    s.service.set_skipping(True)
    s.feed(PM(FESTIVAL, fadein=2.0))
    assert starts(s)[0][2:] == (FESTIVAL, LOOP, 0.0, 200)
    s.run(1.0)
    t0 = s.clock()
    s.feed(PM(OMEN))                                            # default fadeout 0.5 → 0.2
    s.feed(PlaySound(RAIN, True, 40, 2.0))
    rain = channel_of(s, RAIN)
    s.run(0.25)
    assert music(s, since=t0)[0][1:] == ("music_fadeout", 200)
    assert s.mixer.volumes[rain] == quantize(amp(100, 80, 40))   # its 2.0 s fade-in: 0.2 s
    t1 = s.clock()
    s.feed(StopSound(None, 3.0))
    s.run(0.3)
    fade_out_of(s, rain, t1, 200)


def test_ac_f08_48_fadeout_zero_stays_zero_and_loops_follow_the_story(s):
    s.service.set_skipping(True)
    s.feed(PM(FESTIVAL))
    s.run(1.0)
    t0 = s.clock()
    s.feed(PM(OMEN, fadeout=0.0), PlaySound(RAIN, True, 40, None))
    assert [c[1] for c in music(s, since=t0)][:2] == ["music_stop", "music_start"]
    assert s.mixer.name_on(channel_of(s, RAIN)) == RAIN
    s.feed(StopSound(RAIN, 0.0))
    assert s.mixer.busy_channels() == set()


def test_ac_f08_48_a_same_track_volume_ramp_is_capped_too(s):
    s.feed(PM(FESTIVAL))
    s.run(1.0)
    s.service.set_skipping(True)
    s.feed(PM(FESTIVAL, volume=50, fadein=2.0))
    s.run(0.21)
    assert s.mixer.music_level == level(relative=50)


def test_starting_to_skip_stops_the_voice_at_once(s):
    s.feed(PlayVoice("s1", HANA_014, False))
    s.run(0.1)
    s.mixer.calls.clear()
    s.service.set_skipping(True)
    assert s.mixer.actions() == [(s.clock(), "channel_stop", (VOICE_CHANNEL,))]
    assert not s.service.voice_playing()
    s.service.set_skipping(True)                                # already skipping: nothing
    s.service.set_skipping(False)
    assert len(s.mixer.actions()) == 1


def test_when_skipping_stops_what_plays_is_the_lines_state(s):
    s.service.set_skipping(True)
    s.feed(PM(FESTIVAL), PlaySound(RAIN, True, 40, None), PlaySound(CROWD, True, 100, None),
           PlaySound(DOOR, False, 100, None), PM(SHRINE), StopSound(CROWD, None),
           QM(OMEN))
    s.run(1.0)
    s.service.set_skipping(False)
    assert s.mixer.music_name() == SHRINE
    assert {s.mixer.name_on(c) for c in s.mixer.busy_channels()} == {RAIN}


# --- AC-F08-52 — Seams for later features ----------------------------------------------------------

def test_ac_f08_52_a_play_ui_uses_the_pool_at_the_sound_volume(s):
    s.feed(PlaySound(RAIN, True, 40, None))
    rain = channel_of(s, RAIN)
    s.mixer.calls.clear()
    s.service.play_ui(DOOR, volume=50)
    play = s.mixer.actions("channel_play")
    assert len(play) == 1 and play[0][2][0] in UI_CHANNELS and play[0][2][2] == 0
    assert s.mixer.volumes[play[0][2][0]] == quantize(amp(100, 80, 50))
    for _ in range(3):
        s.service.play_ui(DOOR, volume=50)
    channels = [args[0] for _, _, args in s.mixer.actions("channel_play")]
    assert len(channels) == 4 and set(channels) == set(UI_CHANNELS)   # never 1 (F06's blips)
    assert channels[3] == channels[0]                           # the oldest gives way
    assert all(args[0] in UI_CHANNELS for _, name, args in s.mixer.actions()
               if name.startswith("channel"))
    assert s.mixer.name_on(rain) == RAIN


def test_ac_f08_52_the_pool_frees_channels_and_ignores_story_audio(s):
    s.service.play_ui(DOOR)
    channel = next(iter(s.mixer.busy_channels()))
    s.service.set_skipping(True)
    s.feed(restore(reason="new_game"), StopSound(None, None))
    s.service.stop_story_audio(0.5)
    s.run(0.3)
    assert s.mixer.name_on(channel) == DOOR
    s.run(0.3)                                                  # door is 0.5 s long
    assert s.service.pool.slots == {} and ("snd", DOOR) not in s.cache._holds


def test_ac_f08_52_a_missing_ui_sound_is_w26_and_silent(s, caplog):
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        s.service.play_ui("sfx/clik.ogg")
        s.service.play_ui("sfx/clik.ogg")
    assert caplog.messages == ["audio/sfx/clik.ogg is missing, so it plays as silence."]
    assert s.mixer.actions("channel_play") == []


def test_ac_f08_52_replay_voice_plays_on_channel_0_for_no_line(s):
    s.feed(PlayVoice("s1", HANA_015, False))
    s.mixer.calls.clear()
    s.service.replay_voice(HANA_014)
    assert [c[1:] for c in s.mixer.actions("channel_stop", "channel_play")] == [
        ("channel_stop", (VOICE_CHANNEL,)), ("channel_play", (VOICE_CHANNEL, HANA_014, 0))]
    assert s.service.voice_playing() and not s.service.voice_playing("s1")
    s.feed(EndVoice("s1"))                                      # not its line
    assert s.service.voice_playing()
    s.service.set_skipping(True)                                # skipping stops it …
    s.service.replay_voice(HANA_014)                            # … but a replay still plays
    assert s.service.voice_playing()


def test_stop_replay_stops_only_a_replay(s):
    """F13 ``07`` I-5: leaving the History page stops a replay at once (``stop_replay``); a
    line's voice, or nothing playing, is left alone."""
    s.service.stop_replay()                                     # nothing plays: nothing
    assert s.mixer.actions("channel_stop") == []
    s.service.replay_voice(HANA_014)
    s.mixer.calls.clear()
    s.service.stop_replay()
    assert [c[1:] for c in s.mixer.actions("channel_stop")] == [
        ("channel_stop", (VOICE_CHANNEL,))]
    assert not s.service.voice_playing()
    s.service.replay_voice(HANA_014)
    s.feed(PlayVoice("s1", HANA_015, False))                    # a line's voice replaces it
    s.mixer.calls.clear()
    s.service.stop_replay()
    assert s.mixer.actions("channel_stop") == [] and s.service.voice_playing("s1")
    s.run(2.0)                                                  # it ends by itself
    s.service.replay_voice(HANA_014)
    s.run(2.0)
    s.mixer.calls.clear()
    s.service.stop_replay()                                     # the replay ended already
    assert s.mixer.actions("channel_stop") == []


def test_ac_f08_52_takeover_and_release(s):
    s.feed(PM(FESTIVAL))
    s.run(2.0)
    t0 = s.clock()
    handle = s.service.take_music("musicroom")
    assert music(s, since=t0)[0] == (2.0, "music_fadeout", 500)
    s.run(0.6)
    handle.play(OMEN)
    assert starts(s)[-1][2] == OMEN
    s.run(0.5)
    t1 = s.clock()
    s.feed(PM(SHRINE), QM(FESTIVAL), StopMusic(None), PM(SHRINE))
    assert music(s, since=t1) == []
    handle.release()
    s.run(1.0)
    assert music(s, since=t1)[0][1:] == ("music_fadeout", 500)
    assert starts(s)[-1][2:] == (SHRINE, LOOP, 0.0, 1000)


# --- AC-F08-52 with a live story; AC-F08-14; AC-F08-46 -------------------------------------------

def story(tmp_path, S: str):
    from tests.runtime.story import load_files, start
    from tests.script.helpers import template_a

    root = tmp_path / "story"
    root.mkdir()
    return start(load_files(root, {"main.vns": template_a(S=S)}))


def pump(s, interp) -> list:
    """The released burst; its audio commands go to Service S, as the App does."""
    burst = interp.take_commands(1 << 30)
    s.feed(*[c for c in burst if type(c) in AUDIO])
    return burst


def test_ac_f08_52_seams_never_change_the_story_state(s, tmp_path):
    from tests.runtime.story import advance

    interp = story(tmp_path, f'play music "{FESTIVAL}"⏎voice "{HANA_014}"⏎"Voiced."')
    pump(s, interp)
    advance(interp)
    burst = pump(s, interp)
    say = next(c for c in burst if type(c) is Say)
    assert say.voice == HANA_014 and s.service.voice_playing(say.sid)          # (d)
    before = json.dumps(interp.checkpoint().to_json(), sort_keys=True)
    s.service.play_ui(DOOR, volume=50)                                          # (a)
    s.service.replay_voice(HANA_014)                                            # (b)
    handle = s.service.take_music("musicroom")                                  # (c)
    handle.play(OMEN)
    handle.release()
    s.service.set_volumes(40, 70, 80, 100)
    s.service.set_skipping(True)
    s.service.set_skipping(False)
    s.service.set_background(False, False)
    s.run(1.0)
    assert json.dumps(interp.checkpoint().to_json(), sort_keys=True) == before


def test_ac_f08_14_a_rejected_state_changes_nothing(s, tmp_path):
    from tests.runtime.story import advance, fingerprint
    from tests.runtime.test_state_audio import REJECTED, _expand

    interp = story(tmp_path, f'play music "{FESTIVAL}"⏎play sound "{RAIN}" loop⏎"One."⏎'
                             f'"Two."')
    pump(s, interp)
    advance(interp)
    pump(s, interp)
    s.run(1.0)
    before = fingerprint(interp)
    calls = len(s.mixer.calls)
    for row in REJECTED:
        data = interp.checkpoint().to_json()
        data["audio"] = _expand(json.loads(row["json"]))
        with pytest.raises(StateInvalid):
            interp.restore(GameState.from_json(data))
        assert interp.take_commands(1 << 30) == []
    assert len(s.mixer.calls) == calls
    assert fingerprint(interp) == before
    advance(interp)
    assert [c.text for c in pump(s, interp) if type(c) is Say] == ["Two."]
    s.run(0.5)
    assert s.mixer.music_name() == FESTIVAL
    assert s.mixer.name_on(channel_of(s, RAIN)) == RAIN


def restore_vns(tmp_path):
    from tests.runtime.story import checkpoints, launched, load_files, start

    root = tmp_path / "restore"
    root.mkdir()
    program = load_files(root, {"main.vns": (F08 / "restore" / "restore.vns").read_text(
        encoding="utf-8")})
    return program, checkpoints(start(program)), launched


def test_ac_f08_46_rollback_and_roll_forward(s, tmp_path):
    program, (a, b, c), launched = restore_vns(tmp_path)
    interp = launched(program)
    assert interp.restore(c).result is RestoreResult.OK
    pump(s, interp)
    bursts = {}
    for name, state in (("b", b), ("a", a), ("b2", b)):
        assert interp.restore(state).result is RestoreResult.OK
        bursts[name] = pump(s, interp)
        s.run(1.2)                                          # hana_014 is 1.5 s long
        if state is a:
            assert s.mixer.music_name() == FESTIVAL
            assert {s.mixer.name_on(ch) for ch in s.mixer.busy_channels()} == \
                {"sfx/rain.ogg", HANA_014}
        else:
            assert s.mixer.music_name() == "bgm/shrine_steps.ogg"
            assert s.mixer.busy_channels() == set()
    kinds = [[type(x).__name__ for x in bursts[k] if type(x) in AUDIO + (Say,)]
             for k in ("b", "a", "b2")]
    assert kinds == [["AudioRestore", "Say"], ["AudioRestore", "PlayVoice", "Say"],
                     ["AudioRestore", "Say"]]
    assert bursts["a"][0] == AudioRestore(a.audio, "restore")
    assert PlayVoice(a.position, HANA_014, True) in bursts["a"]
    assert bursts["b2"] == bursts["b"]
    assert not any(type(x) is PlaySound for burst in bursts.values() for x in burst)
    assert "bgm/omen.ogg" not in [c[2] for c in starts(s)]


def test_ac_f08_46_a_loaded_state_plays_its_looping_track_from_zero(s, tmp_path):
    from tests.runtime.conftest import round_trip

    program, (a, b, _c), launched = restore_vns(tmp_path)
    rollback = launched(program)
    assert rollback.restore(b).result is RestoreResult.OK
    expected = rollback.take_commands(1 << 30)
    fresh = launched(program)
    assert fresh.restore(round_trip(b)).result is RestoreResult.OK
    assert pump(s, fresh) == expected
    same(starts(s), [(0.0, "music_start", "bgm/shrine_steps.ogg", LOOP, 0.0, 1000)])
    again = launched(program)
    assert again.restore(a).result is RestoreResult.OK
    first = again.take_commands(1 << 30)
    assert again.restore(a).result is RestoreResult.OK
    assert again.take_commands(1 << 30) == first
    again.new_game(42)
    again.run(10_000)
    assert again.take_commands(1)[0] == AudioRestore(AudioState(), "new_game")


# --- AC-F08-53 — Track-started notice ---------------------------------------------------------------

def test_ac_f08_53_track_started_is_called_for_real_story_starts_only(s):
    started: list[str] = []
    s.service.on_track_started = started.append
    s.feed(PM(OMEN, loop=False), QM(SHRINE))                    # a start, then a transition
    s.run(3.2)
    assert started == [OMEN, SHRINE]
    s.feed(PM(SHRINE))                                          # same track: continues
    s.run(4.5)                                                  # a native loop's new pass
    s.feed(PM("bgm/missing.ogg", fadeout=0.0))                  # missing: silence
    s.feed(PM(PASSY))
    s.run(12.5)                                                 # a pass-by-pass repeat
    assert started == [OMEN, SHRINE, PASSY]
    s.feed(restore([(FESTIVAL, True, 100)]))
    s.run(0.6)                                                  # a restore start
    assert started[-1] == FESTIVAL
    handle = s.service.take_music("title")
    s.run(0.6)
    handle.play(OMEN)                                           # a takeover track
    s.run(0.2)
    assert started == [OMEN, SHRINE, PASSY, FESTIVAL]
