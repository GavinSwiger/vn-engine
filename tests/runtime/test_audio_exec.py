"""F08 step 3 — the story's audio state and commands, headless (F08 ``06-acceptance.md`` §1.2;
``04-technical.md`` §6.3; ``07`` I-1, I-2, I-11): AC-F08-08 (state and commands after each
statement), 09 (caps on state and bursts), 10 (audio lands with the next line), 11 (voice,
restore, and new-game commands).

Every story is Template A (§0.4, ``tests/script/helpers.template_a``) run headless; fades
that the line doesn't give stay None (I-11: the presentation resolves them). The runtime
never opens an audio file, so none exists here. AC-10 and 11 compare relative order: F04's
``ShowStage`` falls where I-2 puts it (I-13 (d)).
"""

import logging

import pytest

from engine.app.story import RuntimeStoryDriver
from engine.runtime.audio import EMPTY_AUDIO, AudioState, MusicEntry, SoundLoop
from engine.runtime.commands import (Advance, AudioRestore, EndVoice, NvlPage, PlayMusic, PlaySound,
                                     PlayVoice, QueueMusic, Say, ShowStage, StopMusic,
                                     StopSound, StopVoice, StoryEnded)
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.state import GameState
from tests.runtime.conftest import round_trip
from tests.runtime.story import advance, launched, load_files, sr_f03_28, start
from tests.script.helpers import template_a

AUDIO = (AudioRestore, EndVoice, PlayMusic, PlaySound, PlayVoice, QueueMusic, StopMusic,
         StopSound, StopVoice)


def load_a(root, S: str | None = None, T: str | None = None):
    return load_files(root, {"main.vns": template_a(S=S, T=T)})


def take_all(interp) -> list:
    return interp.take_commands(1 << 30)


def begin(program):
    """Start a new game and take its first burst (the new game's ``AudioRestore`` and
    "Start."), so later bursts are compared alone."""
    interp = start(program)
    first = take_all(interp)
    assert first[0] == AudioRestore(EMPTY_AUDIO, "new_game")
    assert [c.text for c in first if type(c) is Say] == ["Start."]
    return interp


def audio_of(commands) -> list:
    return [c for c in commands if type(c) in AUDIO]


def M(file: str, loop: bool, volume: int) -> dict:
    return {"file": file, "loop": loop, "volume": volume}


def L(file: str, volume: int) -> dict:
    return {"file": file, "volume": volume}


def state_json(interp) -> dict:
    return interp.checkpoint().audio.to_json()


# --- AC-F08-08 — audio state after each statement ------------------------------------------------

FEST, SHRINE, OMEN = "bgm/festival.ogg", "bgm/shrine_steps.ogg", "bgm/omen.ogg"
RAIN, CROWD, DOOR = "sfx/rain.ogg", "sfx/crowd.ogg", "sfx/door.ogg"
VOICE = "voice/hana_014.ogg"

# (statement, music after, sounds after, commands released with "kN.")
AC08 = [
    (f'play music "{FEST}" fadein 2.0', [M(FEST, True, 100)], [],
     [PlayMusic(FEST, True, 100, 2.0, None, False, None, False)]),
    (f'play music "{FEST}" volume 60', [M(FEST, True, 60)], [],
     [PlayMusic(FEST, True, 60, None, None, False, None, False)]),
    (f'queue music "{SHRINE}" once', [M(FEST, False, 60), M(SHRINE, False, 100)], [],
     [QueueMusic(SHRINE, False, 100, None)]),
    (f'queue music "{OMEN}"', [M(FEST, False, 60), M(SHRINE, False, 100), M(OMEN, True, 100)],
     [], [QueueMusic(OMEN, True, 100, None)]),
    (f'play music "{OMEN}" once', [M(OMEN, False, 100)], [],
     [PlayMusic(OMEN, False, 100, None, None, False, None, False)]),
    ("stop music fadeout 0", [], [], [StopMusic(0.0)]),
    (f'queue music "{OMEN}"', [M(OMEN, True, 100)], [], [QueueMusic(OMEN, True, 100, None)]),
    (f'play sound "{RAIN}" loop volume 40', None, [L(RAIN, 40)],
     [PlaySound(RAIN, True, 40, None)]),
    (f'play sound "{CROWD}" loop', None, [L(RAIN, 40), L(CROWD, 100)],
     [PlaySound(CROWD, True, 100, None)]),
    (f'play sound "{RAIN}" loop volume 80', None, [L(RAIN, 80), L(CROWD, 100)],
     [PlaySound(RAIN, True, 80, None)]),
    (f'play sound "{DOOR}"', None, [L(RAIN, 80), L(CROWD, 100)],
     [PlaySound(DOOR, False, 100, None)]),
    (f'play sound "{RAIN}"', None, [L(RAIN, 80), L(CROWD, 100)],
     [PlaySound(RAIN, False, 100, None)]),
    (f'stop sound "{CROWD}" fadeout 1.5', None, [L(RAIN, 80)], [StopSound(CROWD, 1.5)]),
    ("stop sound", None, [], [StopSound(None, None)]),
    ("stop voice", None, [], [StopVoice(None)]),
    (f'voice "{VOICE}"', None, [], ["voice"]),
]


def ac08_program(root):
    rows = [f'{stmt}⏎"k{n}."' for n, (stmt, *_rest) in enumerate(AC08, 1)]
    return load_a(root, S="⏎".join(rows))


def test_ac_f08_08_state_and_commands_after_each_statement(tmp_path):
    program = ac08_program(tmp_path)
    interp = start(program)
    take_all(interp)                                        # "Start."
    music_now: list = []
    for n, (stmt, music, sounds, expected) in enumerate(AC08, 1):
        assert interp.status is Status.WAITING
        interp.post(Advance(interp.current.sid))
        interp.run(1)                                       # the audio statement only
        assert interp.steps == 1, stmt                      # it counted exactly one step
        interp.run(10_000)
        say = interp.current
        assert say.text == f"k{n}.", stmt
        released = take_all(interp)
        if music is not None:
            music_now = music
        assert state_json(interp) == {"music": music_now, "sounds": sounds}, stmt
        got = audio_of(released)
        if expected == ["voice"]:                           # row 16: PlayVoice only (AC-11)
            assert got == [PlayVoice(say.sid, VOICE, False)]
        else:
            assert got == expected, stmt
        assert type(released[-1]) is Say
    # The state never holds a one-shot, voice, position, fade, volume setting, or loop start.
    data = interp.checkpoint().audio.to_json()
    assert set(data) == {"music", "sounds"}
    advance(interp)
    assert interp.current.text == "End."


def test_ac_f08_08_key_sets_are_exactly_the_documented_ones(tmp_path):
    interp = begin(load_a(tmp_path, S=f'play music "{FEST}"⏎queue music "{OMEN}" volume 50⏎'
                                       f'play sound "{RAIN}" loop volume 40⏎"A."'))
    advance(interp)
    data = state_json(interp)
    assert set(data) == {"music", "sounds"}
    assert all(set(e) == {"file", "loop", "volume"} for e in data["music"])
    assert all(set(e) == {"file", "volume"} for e in data["sounds"])
    assert data == {"music": [M(FEST, False, 100), M(OMEN, True, 50)], "sounds": [L(RAIN, 40)]}


def test_from_and_restart_flags(tmp_path):
    interp = begin(load_a(tmp_path, S=f'play music "{FEST}" restart⏎'
                                       f'play music "{OMEN}" from 12.5⏎'
                                       f'play music "{SHRINE}" from current fadeout 2'))
    advance(interp)
    assert audio_of(take_all(interp)) == [
        PlayMusic(FEST, True, 100, None, None, True, None, False),
        PlayMusic(OMEN, True, 100, None, None, True, 12.5, False),       # from implies restart
        PlayMusic(SHRINE, True, 100, None, 2.0, True, None, True)]
    assert interp.checkpoint().audio == AudioState((MusicEntry(SHRINE, True, 100),))


def test_stop_sound_of_a_file_not_looping_keeps_the_loops(tmp_path):
    interp = begin(load_a(tmp_path, S=f'play sound "{RAIN}" loop⏎stop sound "{DOOR}"'))
    advance(interp)
    assert audio_of(take_all(interp)) == [PlaySound(RAIN, True, 100, None),
                                          StopSound(DOOR, None)]
    assert interp.checkpoint().audio.sounds == (SoundLoop(RAIN, 100),)


# --- AC-F08-09 — caps on state and bursts --------------------------------------------------------

def test_ac_f08_09_the_music_sequence_keeps_its_last_64(tmp_path):
    S = f'play music "bgm/a.ogg"⏎' + "⏎".join(f'queue music "bgm/q{n:02}.ogg"' for n in range(65))
    interp = begin(load_a(tmp_path, S=S))
    advance(interp)
    music = interp.checkpoint().audio.music
    assert [e.file for e in music] == [f"bgm/q{n:02}.ogg" for n in range(1, 65)]
    assert [e.loop for e in music] == [False] * 63 + [True]
    assert next(e for e in music if e.loop).file == "bgm/q64.ogg"     # the restore target


def test_ac_f08_09_a_17th_loop_is_refused(tmp_path, caplog):
    S = "⏎".join(f'play sound "sfx/l{n:02}.ogg" loop' for n in range(17))
    interp = begin(load_a(tmp_path, S=S))
    with caplog.at_level(logging.DEBUG, logger="vn"):
        advance(interp)
    released = take_all(interp)
    assert [s.file for s in interp.checkpoint().audio.sounds] == [
        f"sfx/l{n:02}.ogg" for n in range(16)]
    assert [c.file for c in audio_of(released)] == [f"sfx/l{n:02}.ogg" for n in range(16)]
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [(r.name, r.levelno) for r in warnings] == [("vn.runtime", logging.WARNING)]
    assert warnings[0].getMessage() == (
        'script/main.vns, line 20: "sfx/l16.ogg" doesn\'t play, because 16 sounds are already '
        'looping. Stop one with stop sound first.')
    assert interp.current.text == "End."                   # the story continues


def test_ac_f08_09_one_shots_per_burst(tmp_path, caplog):
    S = "⏎".join(f'play sound "sfx/s{n:02}.ogg"' for n in range(17))
    interp = begin(load_a(tmp_path, S=S))
    with caplog.at_level(logging.DEBUG, logger="vn"):
        advance(interp)
    got = audio_of(take_all(interp))
    assert got == [PlaySound(f"sfx/s{n:02}.ogg", False, 100, None) for n in range(16)]
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG and r.name == "vn.runtime"
             and "one-shot" in r.getMessage()]
    assert len(debug) == 1
    assert interp.checkpoint().audio == EMPTY_AUDIO


def test_one_shots_are_counted_per_burst(tmp_path):
    S = "⏎".join(f'play sound "sfx/s{n:02}.ogg"' for n in range(12)) + '⏎"Mid."⏎' + \
        "⏎".join(f'play sound "sfx/t{n:02}.ogg"' for n in range(12))
    interp = begin(load_a(tmp_path, S=S))
    advance(interp)
    assert len(audio_of(take_all(interp))) == 12
    advance(interp)
    assert len(audio_of(take_all(interp))) == 12


def test_ac_f08_09_a_burst_over_64_audio_commands_ends_with_one_sync(tmp_path):
    S = "⏎".join([f'play music "{OMEN}"⏎stop music'] * 35)
    interp = begin(load_a(tmp_path, S=S))
    advance(interp)
    burst = take_all(interp)
    assert [type(c) for c in burst[:64]] == [PlayMusic, StopMusic] * 32
    assert burst[64] == AudioRestore(interp.checkpoint().audio, "sync")
    assert burst[64].state == EMPTY_AUDIO
    assert [type(c) for c in burst[65:]] == [Say] and burst[65].text == "End."
    assert sum(type(c) is AudioRestore for c in burst) == 1


def test_the_sync_comes_before_the_stage_and_the_voice(tmp_path):
    S = "⏎".join([f'play music "{OMEN}"'] * 70) + f'⏎scene black⏎voice "{VOICE}"⏎hana "Hi."'
    interp = begin(load_a(tmp_path, S=S))
    advance(interp)
    burst = take_all(interp)
    kinds = [type(c) for c in burst]
    assert kinds == [PlayMusic] * 64 + [AudioRestore, ShowStage, PlayVoice, Say]
    assert burst[64] == AudioRestore(AudioState((MusicEntry(OMEN, True, 100),)), "sync")
    # The next burst starts counting again.
    advance(interp)
    assert [type(c) for c in take_all(interp)] == [EndVoice, Say]


def test_a_failed_burst_drops_its_audio_and_the_counts(tmp_path):
    S = "⏎".join([f'play music "{OMEN}"'] * 70) + "⏎$ 1/0"
    interp = begin(load_a(tmp_path, S=S))
    advance(interp)
    burst = take_all(interp)
    assert [type(c).__name__ for c in burst] == ["StoryFailed"]


# --- AC-F08-10 — audio changes land with the next line -------------------------------------------

def test_ac_f08_10_audio_lands_with_the_next_line(tmp_path):
    program = load_a(tmp_path, S='play sound "sfx/firework.ogg"⏎$ a = 1⏎play music "bgm/omen.ogg"')
    driver = RuntimeStoryDriver(launched(program), fixed_seed=42)
    driver.new_game()
    first = driver.pump()
    assert first[-1].text == "Start."
    driver.post(Advance(first[-1].sid))
    burst = driver.pump()
    assert burst == [PlaySound("sfx/firework.ogg", False, 100, None),
                     PlayMusic("bgm/omen.ogg", True, 100, None, None, False, None, False),
                     burst[-1]]
    assert type(burst[-1]) is Say and burst[-1].text == "End."


def test_ac_f08_10_audio_before_the_end_goes_with_story_ended(tmp_path):
    interp = begin(load_a(tmp_path, S='"Mid."⏎play sound "sfx/door.ogg"⏎return'))
    take_all(interp)
    advance(interp)                                         # to "Mid."
    assert audio_of(take_all(interp)) == []
    interp.post(Advance(interp.current.sid))
    assert interp.take_commands(10) == []                   # nothing released on its own
    interp.run(10_000)
    assert take_all(interp) == [PlaySound("sfx/door.ogg", False, 100, None), StoryEnded()]


# --- AC-F08-11 — voice, restore, and new-game commands -------------------------------------------

def voiced(tmp_path):
    program = load_a(tmp_path, S=f'voice "{VOICE}"⏎hana "Hi."')
    interp = start(program)
    take_all(interp)
    advance(interp)
    return program, interp


def test_ac_f08_11_the_voice_comes_just_before_its_line(tmp_path):
    program, interp = voiced(tmp_path)
    burst = take_all(interp)
    hi = burst[-1]
    assert type(hi) is Say and hi.text == "Hi." and hi.voice == VOICE
    assert burst[-2] == PlayVoice(hi.sid, VOICE, False)
    assert sum(type(c) is PlayVoice for c in burst) == 1
    advance(interp)
    after = take_all(interp)
    assert after[0] == EndVoice(hi.sid)
    assert [type(c) for c in after] == [EndVoice, Say] and after[1].text == "End."
    assert after[1].voice is None


def test_ac_f08_11_an_unvoiced_line_ends_no_voice(tmp_path):
    interp = begin(load_a(tmp_path, S='"Mid."'))
    take_all(interp)
    for _ in range(2):
        advance(interp)
        assert not any(type(c) in (EndVoice, PlayVoice) for c in take_all(interp))


def test_ac_f08_11_restore_replays_the_voice(tmp_path):
    program, interp = voiced(tmp_path)
    take_all(interp)
    state = interp.checkpoint()
    advance(interp)
    take_all(interp)
    assert interp.restore(round_trip(state)).result is RestoreResult.OK
    burst = take_all(interp)
    order = [c for c in burst if type(c) not in (ShowStage, NvlPage)]     # F04, F17
    assert order[0] == AudioRestore(state.audio, "restore")
    assert order[1] == PlayVoice(state.position, VOICE, True)
    assert type(order[2]) is Say and order[2].restored and order[2].voice == VOICE
    assert len(order) == 3
    # I-2: [AudioRestore] [NvlPage] [ShowStage] [PlayVoice] <line> (F17 I-3: NvlPage)
    assert [type(c) for c in burst] == [AudioRestore, NvlPage, ShowStage, PlayVoice, Say]


def test_ac_f08_11_new_game_sends_silence_first(tmp_path):
    program = load_a(tmp_path, S=f'play music "{FEST}"⏎play sound "{RAIN}" loop⏎"A."')
    interp = launched(program)
    for _ in range(2):                                      # a second game starts silent too
        interp.new_game(42)
        interp.run(10_000)
        burst = take_all(interp)
        assert burst[0] == AudioRestore(AudioState(), "new_game")
        assert sum(type(c) is AudioRestore for c in burst) == 1
        assert interp.checkpoint().audio == AudioState()
        advance(interp)
        assert interp.checkpoint().audio.music                  # music now plays
        take_all(interp)


def test_ac_f08_11_no_voice_in_the_state(tmp_path):
    program, interp = voiced(tmp_path)
    state = interp.checkpoint()
    assert not hasattr(state, "voice") and not hasattr(state, "pending_voice")
    assert not hasattr(interp, "pending_voice")
    assert "voice" not in state.to_json()


def test_end_voice_is_dropped_when_the_next_burst_fails(tmp_path):
    """F03 07 C5: an ``EndVoice`` held by an ``Advance`` goes with a failing burst; the
    ``StoryFailed`` handler stops story audio (07 I-4, F08 step 4)."""
    program = load_a(tmp_path, S=f'voice "{VOICE}"⏎hana "Hi."⏎$ 1/0')
    interp = start(program)
    take_all(interp)
    advance(interp)
    take_all(interp)
    advance(interp)
    assert [type(c).__name__ for c in take_all(interp)] == ["StoryFailed"]


def test_voice_lines_and_python_between_still_attach(tmp_path):
    program = load_a(tmp_path, S=f'voice "{VOICE}"⏎$ a = 1⏎play sound "{DOOR}"⏎"Hi."')
    interp = start(program)
    take_all(interp)
    advance(interp)
    burst = take_all(interp)
    assert [type(c) for c in burst] == [PlaySound, PlayVoice, Say]


def test_runtime_audio_is_clock_free():
    """AC-F08-15's AST half for this module: no ``pygame``, ``time``, or ``os``."""
    import ast
    import engine.runtime.audio as mod
    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"pygame", "time", "os", "random", "threading"}


def test_records_of_an_audio_run(tmp_path, caplog):
    """An ordinary audio story logs nothing but F03's new-game line."""
    with caplog.at_level(logging.DEBUG, logger="vn"):
        interp = start(ac08_program(tmp_path))
        while interp.status is Status.WAITING:
            advance(interp)
    assert [r.getMessage() for r in caplog.records
            if r.name == "vn.runtime" and not sr_f03_28(r)] == []


def test_checkpoints_keep_the_audio_of_their_line(tmp_path):
    interp = start(ac08_program(tmp_path))
    states: list[GameState] = []
    while interp.status is Status.WAITING:
        states.append(interp.checkpoint())
        advance(interp)
    assert states[1].audio.music == (MusicEntry(FEST, True, 100),)
    assert states[0].audio == EMPTY_AUDIO
    assert all(round_trip(s) == s for s in states)
