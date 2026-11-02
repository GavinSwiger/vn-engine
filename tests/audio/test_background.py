"""Audio in the background on Service S (F08 ``04`` §7.8; PR-F08-25, 26): AC-F08-50 (pausing
when a background setting is off) and the unit half of AC-F08-49 (by default nothing pauses).

The window events are real pygame events (``pygame.event.Event``; no display needed): the
service only reads their ``type``, through ``backend.window_change``."""

import pygame
import pytest

from engine.audio.music import Phase
from engine.audio.volume import amp, quantize
from engine.core.config_schema import AudioConfig
from engine.runtime.commands import PlayMusic, PlaySound, PlayVoice
from tests.audio.conftest import make_service

FESTIVAL, OMEN = "bgm/festival.ogg", "bgm/omen.ogg"
RAIN, CROWD = "sfx/rain.ogg", "sfx/crowd.ogg"
FOCUS_LOST = pygame.event.Event(pygame.WINDOWFOCUSLOST)
FOCUS_GAINED = pygame.event.Event(pygame.WINDOWFOCUSGAINED)
MINIMIZED = pygame.event.Event(pygame.WINDOWMINIMIZED)
RESTORED = pygame.event.Event(pygame.WINDOWRESTORED)


def PM(file, *, loop=True, fadein=None) -> PlayMusic:
    return PlayMusic(file, loop, 100, fadein, None, False, None, False)


def send(s, event) -> None:
    assert s.service.handle_event(event) is False           # watched, never consumed


def pauses(s) -> list[str]:
    return [name for _, name, _ in s.mixer.actions("pause_all", "resume_all")]


@pytest.fixture
def s(tmp_path):
    return make_service(tmp_path)


# --- AC-F08-49 (unit half) — by default audio keeps playing --------------------------------------

def test_ac_f08_49_defaults_never_pause(s):
    s.feed(PM(OMEN, loop=False), PlaySound(RAIN, True, 100, 2.0))
    for event in (FOCUS_LOST, MINIMIZED, RESTORED, FOCUS_GAINED, MINIMIZED):
        send(s, event)
    assert pauses(s) == [] and not s.service.paused
    s.run(2.0)                                              # minimized wakes go on
    assert s.mixer.volumes[5] == quantize(amp(100, 80, 100))   # the ramp ended on time
    assert s.service.music.position(s.clock()) == pytest.approx(2.0, abs=0.02)


def test_other_events_are_not_window_changes(s):
    for event in (pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a),
                  pygame.event.Event(pygame.WINDOWSIZECHANGED, x=10, y=10), object()):
        assert s.service.handle_event(event) is False
    assert not s.service.unfocused and not s.service.minimized


# --- AC-F08-50 — pausing in the background --------------------------------------------------------

def test_ac_f08_50_focus_lost_pauses_and_focus_gained_resumes(s):
    s.service.set_background(unfocused=False, minimized=True)
    s.feed(PM(FESTIVAL))
    s.run(3.0)
    send(s, FOCUS_LOST)
    assert pauses(s) == ["pause_all"]                       # within that handle_event call
    at_pause = s.service.music.position(s.clock())
    s.run(5.0)
    assert s.service.music.phase is Phase.PLAYING           # no watchdog while paused
    send(s, FOCUS_GAINED)
    assert pauses(s) == ["pause_all", "resume_all"]
    assert s.service.music.position(s.clock()) == pytest.approx(at_pause, abs=0.02)
    s.run(1.0)
    assert s.service.music.position(s.clock()) == pytest.approx(at_pause + 1.0, abs=0.02)


def test_ac_f08_50_a_paused_ramp_ends_as_late_as_the_pause_lasted(s):
    s.service.set_background(unfocused=False, minimized=True)
    s.feed(PlaySound(RAIN, True, 100, 2.0))                 # a 2.0 s fade-in from t = 0
    s.run(1.0)
    send(s, FOCUS_LOST)
    s.run(5.0)
    send(s, FOCUS_GAINED)
    full = quantize(amp(100, 80, 100))
    s.run(0.9)                                              # t = 6.9
    assert s.mixer.volumes[5] < full
    s.run(0.15)                                             # t = 7.05
    assert s.mixer.volumes[5] == full
    assert s.mixer.busy_channels() == {5}                   # a paused loop stays busy


def test_ac_f08_50_minimize_pauses_when_play_minimized_is_off(s):
    s.service.set_background(unfocused=True, minimized=False)
    s.feed(PM(FESTIVAL))
    send(s, FOCUS_LOST)
    assert pauses(s) == []
    send(s, MINIMIZED)
    send(s, RESTORED)
    assert pauses(s) == ["pause_all", "resume_all"]


def test_ac_f08_50_clearing_one_condition_doesnt_resume_while_the_other_holds(s):
    s.service.set_background(unfocused=False, minimized=False)
    send(s, FOCUS_LOST)
    send(s, MINIMIZED)
    send(s, RESTORED)                                       # still unfocused
    assert pauses(s) == ["pause_all"] and s.service.paused
    send(s, FOCUS_GAINED)
    assert pauses(s) == ["pause_all", "resume_all"] and not s.service.paused


def test_ac_f08_50_play_unfocused_false_in_config(tmp_path):
    s = make_service(tmp_path, AudioConfig(play_unfocused=False))
    send(s, FOCUS_LOST)
    send(s, FOCUS_GAINED)
    assert pauses(s) == ["pause_all", "resume_all"]


def test_turning_a_setting_off_while_it_holds_pauses_at_once(s):
    send(s, FOCUS_LOST)
    s.service.set_background(unfocused=False, minimized=True)
    assert pauses(s) == ["pause_all"]
    s.service.set_background(unfocused=True, minimized=True)
    assert pauses(s) == ["pause_all", "resume_all"]


def test_a_sound_started_while_paused_is_paused_too(s):
    s.service.set_background(unfocused=False, minimized=True)
    send(s, FOCUS_LOST)
    s.mixer.calls.clear()
    s.feed(PlaySound(CROWD, False, 100, None), PlayVoice("s1", "voice/hana_014.ogg", False),
           PM(OMEN))
    s.service.play_ui("sfx/door.ogg")
    names = [name for _, name, _ in s.mixer.actions()]
    assert names.count("pause_all") == 4 and names[-1] == "pause_all"
    s.run(10.0)                                             # paused: crowd (2.0 s) never ends
    assert s.service.effects.slots and s.service.voice_playing("s1")
    send(s, FOCUS_GAINED)
    s.run(2.1)
    assert not s.service.effects.slots and not s.service.voice_playing()


def test_set_background_on_a_closed_service_does_nothing(s):
    s.service.shutdown()
    s.service.set_background(False, False)
    send(s, FOCUS_LOST)
    assert pauses(s) == []
