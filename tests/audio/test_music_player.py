"""The music stream on Service S (F08 ``06`` §1.3; ``04`` §7.1, §7.6, §7.7, §7.8): AC-F08-16
(changing music, default fades), 17 (the same track), 18 (queues), 19 (stale events, the
watchdog, stuck fades), 20 (fade lengths and the fade clock), the music half of AC-38 (W27),
the takeover (``take_music``, F10's title), ``on_track_started``, and the music half of
``AudioRestore``.

A looping track of known length loops natively (``loops=-1``: SDL_mixer loops it
sample-exact, while a queue transition starts in the next 512-frame buffer); MP3, of unknown
length, loops pass by pass (``PASSY``, the current track re-armed each pass). So where
AC-16/17/18 show ``music_arm(festival)`` for a plain loop, an Ogg festival arms
``SILENT_WAV`` and a queue after it switches at the pass end (§7.7), as for a loop point;
the pass-by-pass rows run on ``PASSY``.

Every command goes through ``feed``, which also checks AC-19's slot rule after each
``PlayMusic`` and ``StopMusic``: the armed item is none, ``SILENT_WAV``, or the new
sequence's next track. FakeMixer itself fails any ``music_start`` while the stream is busy
(two streams)."""

import logging

import pytest

from engine.audio.music import SILENT_WAV, Phase, w27_damaged
from engine.audio.volume import amp, quantize
from engine.core.config_schema import AudioConfig
from engine.runtime.audio import AudioState, MusicEntry
from engine.runtime.commands import AudioRestore, PlayMusic, QueueMusic, StopMusic
from tests.audio.conftest import make_service
from tests.fakes.fake_mixer import mp3_bytes, ogg_bytes

FESTIVAL, OMEN, SHRINE = "bgm/festival.ogg", "bgm/omen.ogg", "bgm/shrine_steps.ogg"
PASSY = "bgm/festival.mp3"                    # 12.0 s, unknown length: pass by pass
LOOP = -1                                     # music_start/music_arm loops of a native loop
MUSIC_CALLS = ("music_start", "music_arm", "music_fadeout", "music_stop")
T0 = 100.0                                    # FakeClock's start


def PM(file, *, loop=True, volume=100, fadein=None, fadeout=None, restart=False, start=None,
       from_current=False) -> PlayMusic:
    return PlayMusic(file, loop, volume, fadein, fadeout,
                     restart or start is not None or from_current, start, from_current)


def QM(file, *, loop=True, volume=100, fadein=None) -> QueueMusic:
    return QueueMusic(file, loop, volume, fadein)


def feed(s, *commands) -> None:
    for command in commands:
        s.feed(command)
        if isinstance(command, (PlayMusic, StopMusic)) and not s.service.music_taken():
            allowed = {None, "SILENT_WAV"}
            if isinstance(command, PlayMusic):
                allowed.add(command.file)
            assert s.mixer.armed_name() in allowed, (command, s.mixer.armed_name())


def music(s, since: float | None = None) -> list[tuple]:
    """The music actions as ``(t - T0, name, *args)``, from ``since`` on."""
    return [(round(t - T0, 3), name, *args) for t, name, args in s.mixer.actions(*MUSIC_CALLS)
            if since is None or t >= since]


def same(actual: list[tuple], expected: list[tuple], tol: float = 0.015) -> None:
    """The calls match, their times within ``tol`` (a fade's end event and the 1-sample
    ``SILENT_WAV`` after it can land one 10 ms frame apart)."""
    assert [a[1:] for a in actual] == [e[1:] for e in expected], actual
    assert all(abs(a[0] - e[0]) <= tol for a, e in zip(actual, expected)), actual


def starts(s) -> list[tuple]:
    return [c for c in music(s) if c[1] == "music_start"]


def level(music_volume: int = 70, relative: int = 100) -> float:
    return quantize(amp(100, music_volume, relative))


@pytest.fixture
def s(tmp_path):
    service = make_service(tmp_path)
    service.add(PASSY, mp3_bytes(b"festival"), 12.0)
    return service


def playing(s, file=FESTIVAL, seconds=5.0, **kwargs):
    """``file`` playing for ``seconds`` (the calls so far forgotten)."""
    feed(s, PM(file, **kwargs))
    s.run(seconds)
    s.mixer.calls.clear()
    return s


# --- AC-F08-16 — Changing music and the default fades ----------------------------------------

def test_ac_f08_16_silent_play_starts_now_and_arms_the_next_pass(s):
    feed(s, PM(PASSY))
    assert music(s) == [(0.0, "music_start", PASSY, 0, 0.0, 0),
                        (0.0, "music_arm", PASSY, 0)]             # pass by pass
    assert s.mixer.music_level == level()
    s.mixer.calls.clear()
    feed(s, PM(FESTIVAL, fadeout=0))
    assert music(s)[1:] == [(0.0, "music_start", FESTIVAL, LOOP, 0.0, 0),
                            (0.0, "music_arm", "SILENT_WAV", 0)]  # a native loop


def test_ac_f08_16_fadein_is_native(s):
    feed(s, PM(FESTIVAL, fadein=2.0))
    same(starts(s), [(0.0, "music_start", FESTIVAL, LOOP, 0.0, 2000)])


def test_ac_f08_16_a_new_track_waits_for_the_fade_out(s):
    playing(s)
    feed(s, PM(OMEN))
    assert music(s) == [(5.0, "music_fadeout", 500), (5.0, "music_arm", "SILENT_WAV", 0)]
    s.run(0.49)
    assert starts(s) == []
    s.run(0.03)
    same(starts(s), [(5.5, "music_start", OMEN, LOOP, 0.0, 0)])
    assert s.mixer.music_name() == OMEN


def test_ac_f08_16_fadeout_zero_cuts_in_the_same_call(s):
    playing(s)
    feed(s, PM(OMEN, fadeout=0))
    assert [c[1:3] for c in music(s)][:2] == [("music_stop",), ("music_start", OMEN)]
    assert s.mixer.music_name() == OMEN


def test_ac_f08_16_a_once_track_arms_silence_and_ends_quiet(s):
    playing(s)
    feed(s, PM(OMEN, loop=False, fadeout=0))
    assert music(s)[-1][1:] == ("music_arm", "SILENT_WAV", 0)
    s.run(2.9)
    assert s.mixer.music_name() == OMEN
    s.run(0.2)
    assert s.mixer.music_name() is None and s.service.music.phase is Phase.SILENT


def test_ac_f08_16_config_default_fades(tmp_path):
    s = make_service(tmp_path, AudioConfig(music_fadeout=1.5, music_fadein=0.25))
    playing(s)
    feed(s, PM(OMEN))
    assert music(s)[0] == (5.0, "music_fadeout", 1500)
    s.run(1.6)
    same(starts(s), [(6.5, "music_start", OMEN, LOOP, 0.0, 250)])


def test_ac_f08_16_a_shorter_fadeout_cuts_the_running_fade(s):
    playing(s, seconds=0.0)
    feed(s, StopMusic(3.0))
    s.run(1.0)
    feed(s, PM(OMEN, fadeout=0.5))
    fades = [c for c in music(s) if c[1] == "music_fadeout"]
    assert fades == [(0.0, "music_fadeout", 3000), (1.0, "music_fadeout", 500)]
    s.run(1.0)
    (start,) = starts(s)
    assert start[2] == OMEN and 1.3 <= start[0] <= 1.55        # on that fade's end event


def test_ac_f08_16_a_longer_fadeout_keeps_the_running_fade(s):
    playing(s, seconds=0.0)
    feed(s, StopMusic(3.0))
    s.run(1.0)
    feed(s, PM(OMEN, fadeout=5.0))
    assert [c for c in music(s) if c[1] == "music_fadeout"] == [(0.0, "music_fadeout", 3000)]
    s.run(1.95)
    assert starts(s) == []
    s.run(0.1)
    same(starts(s), [(3.0, "music_start", OMEN, LOOP, 0.0, 0)])


# --- AC-F08-17 — The same track continues -------------------------------------------------------

def test_ac_f08_17_same_track_continues_and_its_volume_applies_at_once(s):
    playing(s)
    pos = s.service.music.position(s.clock())
    feed(s, PM(FESTIVAL))
    assert [c[1] for c in music(s)] == ["music_arm"]
    s.run(1.0)
    assert s.service.music.position(s.clock()) == pytest.approx(pos + 1.0, abs=0.02)
    feed(s, PM(FESTIVAL, volume=50))
    assert s.mixer.music_level == level(relative=50)
    assert not s.mixer.actions("music_start", "music_stop")


def test_ac_f08_17_volume_ramps_over_fadein(s):
    playing(s)
    feed(s, PM(FESTIVAL, volume=50, fadein=2.0))
    target = level(relative=50)
    seen = []
    for _ in range(220):
        s.advance(0.01)
        seen.append((round(s.clock() - T0 - 5.0, 3), s.mixer.music_level))
    values = [v for _, v in seen]
    assert values == sorted(values, reverse=True)                  # monotonic
    reached = next(t for t, v in seen if v == target)
    assert 1.95 <= reached <= 2.05


def test_ac_f08_17_once_restarts_from_the_beginning(s):
    playing(s)
    feed(s, PM(FESTIVAL, loop=False))                 # SR-F08-06: fade out, then start
    s.run(0.6)
    same(starts(s), [(5.5, "music_start", FESTIVAL, 0, 0.0, 0)])
    s.mixer.calls.clear()
    feed(s, PM(FESTIVAL, loop=True, fadeout=0))
    assert [c[1:] for c in music(s)][:2] == [("music_stop",),
                                             ("music_start", FESTIVAL, LOOP, 0.0, 0)]


def test_ac_f08_17_restart_starts_from_zero(s):
    playing(s)
    feed(s, PM(FESTIVAL, restart=True, fadeout=0))
    assert [c[1:] for c in music(s)][:2] == [("music_stop",),
                                             ("music_start", FESTIVAL, LOOP, 0.0, 0)]
    assert s.service.music.position(s.clock()) == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize("track", [PASSY, FESTIVAL])
def test_ac_f08_17_the_queue_is_cleared(s, track):
    playing(s, track)
    feed(s, QM(SHRINE))
    assert s.mixer.armed_name() == (SHRINE if track == PASSY else "SILENT_WAV")
    assert (s.service.music.switch_at is None) == (track == PASSY)
    feed(s, PM(track))
    assert s.mixer.armed_name() == (PASSY if track == PASSY else "SILENT_WAV")
    assert s.service.music.switch_at is None
    s.run(7.5)
    assert s.mixer.music_name() == track and not s.service.music.queue
    assert starts(s) == [] and not s.mixer.actions("music_fadeout")


def test_ac_f08_17_same_track_during_its_fade_out_restarts_where_it_is(s):
    playing(s)
    feed(s, StopMusic(3.0))
    s.run(1.0)
    feed(s, PM(FESTIVAL))
    calls = [c for c in music(s) if c[0] >= 6.0]
    assert [c[1] for c in calls[:2]] == ["music_stop", "music_start"]
    _, _, file, loops, start, fade_ms = calls[1]
    assert (file, loops, fade_ms) == (FESTIVAL, LOOP, 50)
    assert start == pytest.approx(6.0, abs=0.05)
    assert s.mixer.music_level == level()
    assert s.service.music.phase is Phase.PLAYING
    s.run(3.0)
    assert s.mixer.music_name() == FESTIVAL                   # the old fade is gone


# --- AC-F08-18 — Queues -----------------------------------------------------------------------

def test_ac_f08_18_queue_on_silence_starts_now(s):
    feed(s, QM(SHRINE, fadein=1.0))
    same(starts(s), [(0.0, "music_start", SHRINE, LOOP, 0.0, 1000)])


def test_ac_f08_18_queued_after_a_once_track(s):
    feed(s, PM(OMEN, loop=False), QM(SHRINE))
    assert music(s)[-1][1:] == ("music_arm", SHRINE, LOOP)     # it loops once it starts
    s.run(3.05)
    assert s.mixer.music_name() == SHRINE
    assert s.service.music.current.file == SHRINE
    assert music(s)[-1][1:] == ("music_arm", "SILENT_WAV", 0)
    assert len(starts(s)) == 1                                 # an SDL queue transition
    s.run(10.0)
    assert s.mixer.music_name() == SHRINE


def test_ac_f08_18_queued_after_a_pass_by_pass_loop(s):
    playing(s, PASSY)
    feed(s, QM(SHRINE))
    assert music(s) == [(5.0, "music_arm", SHRINE, LOOP)]
    s.run(6.9)
    assert s.mixer.music_name() == PASSY                       # finishes its pass
    s.run(0.2)
    assert s.mixer.music_name() == SHRINE and s.service.music.current.file == SHRINE


def test_ac_f08_18_queued_after_a_native_loop_switches_at_the_pass_end(s):
    playing(s)
    feed(s, QM(SHRINE))
    assert music(s) == [] and s.service.music.switch_at == pytest.approx(12.0)
    s.run(6.8)
    assert s.mixer.music_name() == FESTIVAL
    s.run(0.1)
    (fade,) = [c for c in music(s) if c[1] == "music_fadeout"]
    assert 11.84 <= fade[0] <= 11.87 and 140 <= fade[2] <= 160
    s.run(0.3)
    assert starts(s)[-1][:3] == (pytest.approx(12.0, abs=0.02), "music_start", SHRINE)


def loop_point(s, file=FESTIVAL, at=4.0):
    s.service.music.loop_point = lambda f, data: (data, at) if f == file else None


def test_ac_f08_18_queued_after_a_loop_point_switches_at_the_pass_end(s):
    loop_point(s)
    feed(s, PM(FESTIVAL))
    same(starts(s), [(0.0, "music_start", FESTIVAL, -1, 0.0, 0)])
    s.run(5.0)
    feed(s, QM(SHRINE))
    s.run(6.8)
    assert not [c for c in music(s) if c[1] == "music_fadeout"]
    s.run(0.1)                                               # pos reaches 12.0 − 0.15
    (fade,) = [c for c in music(s) if c[1] == "music_fadeout"]
    assert 11.84 <= fade[0] <= 11.87 and 140 <= fade[2] <= 160
    s.run(0.3)
    assert starts(s)[-1][:3] == (pytest.approx(12.0, abs=0.02), "music_start", SHRINE)


def test_ac_f08_18_a_late_switch_check_fades_over_50_ms(s):
    loop_point(s)
    feed(s, PM(FESTIVAL))
    s.run(5.0)
    feed(s, QM(SHRINE))
    s.advance(8.0)                                           # the clock jumps past 12.0
    (fade,) = [c for c in music(s) if c[1] == "music_fadeout"]
    assert fade[2] == 50
    s.run(0.1)
    assert starts(s)[-1][2] == SHRINE


def test_ac_f08_18_a_loop_point_track_queued_in_its_own_burst_restarts_once(s):
    loop_point(s)
    feed(s, PM(FESTIVAL), QM(SHRINE))
    assert [c[1:] for c in music(s)] == [
        ("music_start", FESTIVAL, -1, 0.0, 0), ("music_arm", "SILENT_WAV", 0),
        ("music_stop",), ("music_start", FESTIVAL, 0, 0.0, 0), ("music_arm", SHRINE, LOOP)]
    s.run(12.05)
    assert s.mixer.music_name() == SHRINE


def test_ac_f08_18_queue_during_a_stop_fade_starts_on_its_end_event(s):
    playing(s)
    feed(s, StopMusic(1.0), QM(SHRINE))
    s.run(0.98)
    assert starts(s) == []
    s.run(0.05)
    same(starts(s), [(6.0, "music_start", SHRINE, LOOP, 0.0, 0)])


def test_ac_f08_18_queue_after_a_pending_track(s):
    playing(s)
    feed(s, PM(OMEN), QM(SHRINE))
    s.run(0.52)
    assert [c[2] for c in starts(s)] == [OMEN]
    assert s.mixer.armed_name() == SHRINE
    s.run(3.0)
    assert s.mixer.music_name() == SHRINE


@pytest.mark.parametrize("track", [PASSY, FESTIVAL])
def test_ac_f08_18_queuing_the_playing_file_plays_it_again(s, track):
    started = []
    s.service.on_track_started = started.append
    playing(s, track)
    feed(s, QM(track))
    s.run(7.3)
    assert s.mixer.music_name() == track
    assert started == [track, track]                         # a new track, not a pass
    assert s.service.music.current.loop and not s.service.music.queue
    s.run(12.0)
    assert started == [track, track]


def test_ac_f08_18_only_the_last_queued_track_loops(s):
    feed(s, QM(OMEN, loop=False), QM(SHRINE, loop=False), QM(FESTIVAL))
    heard = []
    for _ in range(3000):                                     # 30 s
        s.advance(0.01)
        name = s.mixer.music_name()
        if not heard or heard[-1] != name:
            heard.append(name)
    assert heard == [OMEN, SHRINE, FESTIVAL]
    assert len(starts(s)) == 1


def test_ac_f08_18_stop_clears_the_queue(s):
    playing(s)
    feed(s, QM(OMEN), QM(SHRINE), StopMusic(1.0))
    assert not s.service.music.queue and s.service.music.pending is None
    s.run(1.05)
    assert s.mixer.music_name() is None and s.service.music.phase is Phase.SILENT
    s.run(10.0)
    assert starts(s) == []


def test_ac_f08_18_a_missing_queued_track_is_skipped(s, caplog):
    playing(s)
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        feed(s, QM("bgm/missing.ogg"), QM(SHRINE))
        s.run(7.1)
    assert "audio/bgm/missing.ogg is missing, so it plays as silence." in caplog.messages
    assert s.mixer.music_name() == SHRINE


def test_a_missing_track_is_silence_and_the_queue_goes_on(s, caplog):
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        feed(s, PM("bgm/zzqx.ogg"))
        assert s.service.music.phase is Phase.SILENT and s.mixer.calls == []
        playing(s, OMEN, seconds=1.0, loop=False)
        feed(s, QM("bgm/zzqx.ogg"), QM(SHRINE))
        s.run(2.1)
    assert s.mixer.music_name() == SHRINE
    assert caplog.messages.count("audio/bgm/zzqx.ogg is missing, so it plays as silence.") == 1


def test_a_track_sdl_refuses_is_w26_and_never_read_again(s, caplog):
    s.mixer.fail_decode.add(OMEN)
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        feed(s, PM(OMEN))
        feed(s, PM(OMEN))
    assert s.service.music.phase is Phase.SILENT
    assert caplog.messages == ["audio/bgm/omen.ogg can't be played: it is damaged or isn't "
                               "really an Ogg Vorbis file. Export it again as .ogg."]
    assert s.service.reader.failed(OMEN)


# --- AC-F08-19 — Stale end events, the watchdog, and stuck fades --------------------------------

def test_ac_f08_19_a_stale_end_event_changes_nothing(s):
    playing(s)
    s.mixer.fake_music_end()                       # posted before the start …
    stale = s.mixer.take_events()
    feed(s, PM(OMEN, fadeout=0))
    music_before = (s.service.music.phase, s.service.music.current, s.service.music.armed)
    for event in stale:                            # … and delivered after it
        assert s.service.handle_event(event)
    assert (s.service.music.phase, s.service.music.current,
            s.service.music.armed) == music_before
    assert s.service.music.current.file == OMEN
    s.run(2.0)
    assert s.mixer.music_name() == OMEN


def test_ac_f08_19_a_stale_event_during_a_fade_out_changes_nothing(s):
    playing(s)
    feed(s, PM(OMEN))
    s.mixer.fake_music_end()
    s.advance(0.01)
    assert s.service.music.phase is Phase.FADING_OUT and starts(s) == []


def test_ac_f08_19_the_watchdog_ends_a_track_whose_event_was_lost(s):
    s.mixer.drop_events = True
    feed(s, PM(OMEN, loop=False))
    s.run(3.0)
    assert s.service.music.phase is Phase.PLAYING          # ended at 3.0, no event
    s.run(0.48)
    assert s.service.music.phase is Phase.PLAYING
    s.run(0.04)
    assert s.service.music.phase is Phase.SILENT


def test_ac_f08_19_the_watchdog_starts_the_next_queued_track(s):
    s.mixer.drop_events = True
    feed(s, PM(OMEN, loop=False), QM(SHRINE))
    s.run(1.0)
    s.mixer.armed = None                                   # SDL lost the slot too
    s.run(2.0)
    s.run(0.48)
    assert len(starts(s)) == 1
    s.run(0.04)
    (_, second) = starts(s)
    assert second[2] == SHRINE and second[0] == pytest.approx(3.5, abs=0.02)


def test_ac_f08_19_the_watchdog_never_fires_while_paused(s):
    s.mixer.drop_events = True
    playing(s, OMEN, seconds=1.0, loop=False)
    s.mixer.pause_all()
    s.service.music.paused = True
    s.run(3.0)
    assert s.service.music.phase is Phase.PLAYING and starts(s) == []


def test_ac_f08_19_a_stuck_fade_is_stopped_after_fade_plus_one_second(s):
    s.mixer.stuck_fades = True
    playing(s, seconds=0.0)
    feed(s, StopMusic(1.0))
    s.run(1.98)
    assert not s.mixer.actions("music_stop")
    s.run(0.04)
    (stop,) = s.mixer.actions("music_stop")
    assert stop[0] - T0 == pytest.approx(2.0, abs=0.02)
    assert s.service.music.phase is Phase.SILENT


def test_ac_f08_19_a_stuck_fade_then_starts_the_pending_track(s):
    s.mixer.stuck_fades = True
    playing(s, seconds=0.0)
    feed(s, PM(OMEN, fadeout=1.0))
    s.run(2.05)
    assert [c[1:3] for c in music(s)][-3:-1] == [("music_stop",), ("music_start", OMEN)]


def test_ac_f08_19_the_slot_rule_over_a_mixed_sequence(s):
    """After every PlayMusic and StopMusic the armed item is none, SILENT_WAV, or the new
    sequence's next track (``feed`` checks); FakeMixer refuses two streams."""
    feed(s, PM(FESTIVAL), QM(OMEN), QM(SHRINE))
    s.run(1.0)
    feed(s, PM(OMEN, loop=False), StopMusic(0.5), PM(SHRINE, fadeout=0))
    s.run(0.6)
    feed(s, PM(FESTIVAL, fadein=1.0), StopMusic(0))
    s.run(1.0)
    feed(s, QM(OMEN), PM(OMEN))
    s.run(3.0)


# --- AC-F08-20 — Fade lengths and the fade clock --------------------------------------------------

def test_ac_f08_20_fade_lengths(s):
    feed(s, PM(FESTIVAL, fadein=60))
    same(starts(s), [(0.0, "music_start", FESTIVAL, LOOP, 0.0, 60000)])
    feed(s, StopMusic(0), PM(OMEN, fadein=0))
    assert starts(s)[-1][-1] == 0


def test_ac_f08_20_a_60_s_volume_ramp_ends_on_time(s):
    playing(s, seconds=0.0)
    feed(s, PM(FESTIVAL, volume=50, fadein=60))
    player = s.service.music
    target = 0.25                                          # curve(50), before quantizing
    s.run(59.95, step=0.05)
    assert player._gain(s.clock()) > target
    s.run(0.1, step=0.05)
    assert player._gain(s.clock()) == target
    assert s.mixer.music_level == level(relative=50)


def test_ac_f08_20_ramps_follow_the_clock_not_frames(s):
    playing(s, seconds=0.0)
    feed(s, PM(FESTIVAL, volume=50, fadein=2.0))
    s.advance(2.0)                                         # no frames in between
    assert s.mixer.music_level == level(relative=50)
    feed(s, PM(FESTIVAL, volume=100, fadein=2.0))
    s.advance(0.5)
    s.advance(1.0)                                         # one 1.0 s frame stall
    assert s.mixer.music_level != level()
    s.advance(0.5)
    assert s.mixer.music_level == level()


# --- AC-F08-38, music half (W27) ------------------------------------------------------------------

def test_ac_f08_38_a_track_damaged_partway_is_w27_and_the_queue_goes_on(s, caplog):
    s.add("broken/truncated.ogg", ogg_bytes(12.0, salt=b"cut"), 7.2)   # decodes 7.2 of 12.0 s
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        feed(s, PM("broken/truncated.ogg"), QM(OMEN))
        s.run(7.3)
    assert s.mixer.music_name() == OMEN
    assert caplog.messages == ["audio/broken/truncated.ogg is damaged 0:07 in, so it stopped "
                               "there. Export it again as .ogg."]
    assert [r.code for r in caplog.records] == ["W27"]


def test_w27_rounds_down_to_m_ss():
    assert w27_damaged("bgm/festival.ogg", 83.9) == (
        "audio/bgm/festival.ogg is damaged 1:23 in, so it stopped there. Export it again as "
        ".ogg.")


def test_a_full_length_pass_is_not_damaged(s, caplog):
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        feed(s, PM(OMEN))
        s.run(10.0)
    assert caplog.messages == []


# --- Takeover (take_music; F10's title), on_track_started -----------------------------------------

def test_take_music_fades_the_story_out_and_plays_the_holder(s):
    playing(s)
    handle = s.service.take_music("title")
    assert music(s) == [(5.0, "music_fadeout", 500), (5.0, "music_arm", "SILENT_WAV", 0)]
    handle.play(SHRINE, loop=True, fadein=0.0)
    s.run(0.6)
    assert s.mixer.music_name() == SHRINE
    assert handle.position() == pytest.approx(0.1, abs=0.03)


def test_story_commands_while_taken_only_change_the_model(s):
    handle = s.service.take_music("title")
    handle.play(SHRINE)
    s.mixer.calls.clear()
    feed(s, PM(FESTIVAL), QM(OMEN), QM(FESTIVAL, volume=40), StopMusic(None),
         PM(OMEN, loop=False), QM(FESTIVAL, volume=60))
    assert music(s) == []
    assert s.service.story_music == (MusicEntry(OMEN, False, 100),
                                     MusicEntry(FESTIVAL, True, 60))


def test_release_brings_the_story_music_back_with_the_restore_fades(s):
    handle = s.service.take_music("title")
    handle.play(SHRINE)
    feed(s, PM(OMEN, loop=False), QM(FESTIVAL, volume=60))
    s.mixer.calls.clear()
    handle.release()
    assert music(s)[0] == (0.0, "music_fadeout", 500)
    s.run(0.55)
    same(starts(s), [(0.5, "music_start", FESTIVAL, LOOP, 0.0, 1000)])
    assert s.mixer.music_level == level(relative=60)
    handle.play(OMEN)                                       # inert once released
    handle.stop()
    assert handle.position() is None
    assert [c[1] for c in music(s)][-1] == "music_arm"


def test_release_with_a_silent_story_fades_the_holder_out(s):
    handle = s.service.take_music("title")
    handle.play(SHRINE)
    s.run(1.0)
    handle.stop(fadeout=0.5)                                # the title's New Game
    s.run(0.2)
    handle.release()                                        # the cut, mid-fade
    feed(s, AudioRestore(AudioState(), "new_game"), PM(FESTIVAL, fadein=2.0))
    s.run(0.4)
    assert starts(s)[-1][2:] == (FESTIVAL, LOOP, 0.0, 2000)


def test_a_second_take_replaces_the_holder(s):
    first = s.service.take_music("title")
    first.play(SHRINE)
    second = s.service.take_music("music_room")
    assert not first.active and second.active
    first.stop(fadeout=0)
    assert s.service.music.phase is Phase.PLAYING
    first.release()
    assert s.service.music_taken()
    second.play(OMEN, fadeout=0)
    assert s.mixer.music_name() == OMEN


def test_on_track_started_reports_story_tracks_only(s):
    started = []
    s.service.on_track_started = started.append
    handle = s.service.take_music("title")
    handle.play(SHRINE)
    handle.release()
    feed(s, PM(OMEN, loop=False), QM(FESTIVAL))
    s.run(3.1)
    s.run(12.5)                                             # a new pass: not reported
    assert started == [OMEN, FESTIVAL]


def test_stop_story_audio_fades_the_music_out(s):
    playing(s)
    s.service.stop_story_audio(0.5)
    assert music(s)[0] == (5.0, "music_fadeout", 500)
    s.run(0.6)
    assert s.mixer.music_name() is None and s.service.story_music == ()


def test_stop_story_audio_leaves_a_holders_music(s):
    handle = s.service.take_music("title")
    handle.play(SHRINE)
    s.service.stop_story_audio(0.5)
    s.run(1.0)
    assert s.mixer.music_name() == SHRINE


def test_volume_settings_apply_to_the_music_at_once(s):
    playing(s)
    s.service.set_volumes(100, 40, 80, 100)
    assert s.mixer.music_level == quantize(amp(100, 40, 100))


# --- AudioRestore, the music half (§7.6 steps 1–2) ----------------------------------------------

def restore(*entries, reason="restore") -> AudioRestore:
    return AudioRestore(AudioState(tuple(MusicEntry(*e) for e in entries)), reason)


def test_restore_plays_the_looping_track_with_the_restore_fadein(s):
    feed(s, restore((OMEN, False, 100), (SHRINE, True, 80)))
    same(starts(s), [(0.0, "music_start", SHRINE, LOOP, 0.0, 1000)])
    assert s.mixer.music_level == level(relative=80)


def test_restore_keeps_the_same_track_and_ramps_its_volume(s):
    playing(s)
    feed(s, restore((FESTIVAL, True, 50)))
    assert not s.mixer.actions("music_start", "music_stop", "music_fadeout")
    s.run(0.5)
    assert level(relative=50) < s.mixer.music_level < level()
    s.run(0.55)
    assert s.mixer.music_level == level(relative=50)


def test_restore_switches_with_the_restore_fades(s):
    playing(s)
    feed(s, restore((OMEN, True, 100)))
    assert music(s)[0] == (5.0, "music_fadeout", 500)
    s.run(0.55)
    same(starts(s), [(5.5, "music_start", OMEN, LOOP, 0.0, 1000)])


def test_restore_with_no_looping_track_stops(s):
    playing(s)
    feed(s, restore((OMEN, False, 100)))
    s.run(0.6)
    assert s.mixer.music_name() is None and starts(s) == []


def test_a_sync_uses_the_play_defaults(s):
    feed(s, restore((OMEN, True, 100), reason="sync"))
    same(starts(s), [(0.0, "music_start", OMEN, LOOP, 0.0, 0)])


def test_a_restored_missing_track_is_w29(s, caplog):
    with caplog.at_level(logging.WARNING, logger="vn.audio"):
        feed(s, restore(("bgm/old_theme.ogg", True, 100)))
    assert caplog.messages == ["A restored game plays audio/bgm/old_theme.ogg, which is "
                               "missing, so the music is silent."]
    assert caplog.records[0].code == "W29"


def test_from_current_starts_at_the_old_position(s):
    playing(s)
    feed(s, PM(OMEN, from_current=True, fadeout=0))
    assert starts(s)[-1][2:4] == (OMEN, LOOP)
    assert starts(s)[-1][4] == 0.0                           # 5.0 is past omen's 3.0 s
    s.mixer.calls.clear()
    feed(s, PM(FESTIVAL, fadeout=0))
    s.run(1.0)
    feed(s, PM(SHRINE, from_current=True))
    s.run(0.6)
    assert starts(s)[-1][2] == SHRINE
    assert starts(s)[-1][4] == pytest.approx(1.5, abs=0.03)
    feed(s, StopMusic(0), PM(OMEN, start=2.5))
    assert starts(s)[-1][2:5] == (OMEN, LOOP, 2.5)


def test_silent_wav_is_one_silent_frame():
    assert SILENT_WAV.ext == ".wav" and SILENT_WAV.data[-4:] == b"\0\0\0\0"
    assert len(SILENT_WAV.data) == 48


def test_positions_of_a_native_loop_wrap(s):
    playing(s, seconds=14.0)                                 # festival: 12.0 s, then 2.0 s
    assert s.service.music.position(s.clock()) == pytest.approx(2.0, abs=0.02)
    feed(s, PM(OMEN, from_current=True, fadeout=0))
    assert starts(s)[-1][2:5] == (OMEN, LOOP, pytest.approx(2.0, abs=0.02))


# --- AC-F08-25 — ``from`` and ``from current`` (F08 step 10; SR-F08-12) -------------------------

MUFFLED = "bgm/festival_muffled.ogg"           # 12.0 s


def test_ac_f08_25_from_past_the_end_starts_at_0_and_from_5_at_5(s):
    feed(s, PM(MUFFLED, start=12.5))
    assert starts(s)[-1][2:5] == (MUFFLED, LOOP, 0.0)
    feed(s, StopMusic(0), PM(MUFFLED, start=5.0))
    assert starts(s)[-1][2:5] == (MUFFLED, LOOP, 5.0)
    s.run(1.0)
    assert s.service.music.position(s.clock()) == pytest.approx(6.0, abs=0.02)


def test_ac_f08_25_from_current_with_nothing_playing_starts_at_0(s):
    feed(s, PM(MUFFLED, from_current=True))
    assert starts(s) == [(0.0, "music_start", MUFFLED, LOOP, 0.0, 0)]


def test_ac_f08_25_from_current_starts_at_the_old_position_and_restored_at_0(s, tmp_path):
    playing(s, seconds=7.3)
    feed(s, PM(MUFFLED, from_current=True, fadeout=0))
    assert starts(s)[-1][2:4] == (MUFFLED, LOOP)
    assert starts(s)[-1][4] == pytest.approx(7.3, abs=0.05)
    state = AudioState((MusicEntry(MUFFLED, True, 100),))     # positions aren't saved
    (tmp_path / "fresh").mkdir()
    fresh = make_service(tmp_path / "fresh")
    feed(fresh, AudioRestore(state, "restore"))
    assert starts(fresh) == [(0.0, "music_start", MUFFLED, LOOP, 0.0, 1000)]


def test_from_restarts_the_same_track_after_its_fade_out(s):
    """``from`` implies ``restart`` (SR-F08-12): the playing track fades out over the
    default 0.5 s, then the same file starts at the position (SR-F08-06)."""
    playing(s)
    feed(s, PM(FESTIVAL, start=2.0))
    assert music(s) == [(5.0, "music_fadeout", 500), (5.0, "music_arm", "SILENT_WAV", 0)]
    s.run(0.52)
    same(starts(s), [(5.5, "music_start", FESTIVAL, LOOP, 2.0, 0)])


def test_from_current_after_a_fade_out_takes_the_position_at_its_end(s):
    playing(s, seconds=7.3)
    feed(s, PM(MUFFLED, from_current=True))                  # the default 0.5 s fade-out
    s.run(0.52)
    assert starts(s)[-1][2] == MUFFLED
    assert starts(s)[-1][4] == pytest.approx(7.8, abs=0.05)


def test_from_current_of_a_loop_point_track_is_its_wrapped_position(s):
    loop_point(s)                                            # festival loops from 4.0
    playing(s, seconds=14.0)                                 # 12.0, then 2.0 from 4.0
    assert s.service.music.position(s.clock()) == pytest.approx(6.0, abs=0.02)
    feed(s, PM(MUFFLED, from_current=True, fadeout=0))
    assert starts(s)[-1][4] == pytest.approx(6.0, abs=0.05)
