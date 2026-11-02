"""F08 step 3 — the story's audio in saved states (F08 ``06-acceptance.md`` §1.2, §5.4;
``04-technical.md`` §4, §6.3 ``from_json``, §10): AC-F08-12 (round trips; saves from before
F08 load silent) and AC-F08-13 (hostile ``audio`` values, as data in
``tests/fixtures/F08/restore/hostile_audio.toml``). Also F11 C11's ``save_problem`` for the
new field, and ``restore.vns`` (§5.4): its checkpoints round-trip and restore with their
audio.

AC-F08-14 (a rejected state changes nothing, with FakeMixer) needs the service: F08 step 7.
Its runtime half holds already: ``from_json`` refuses before ``restore`` can run, and a
restore that returns anything but OK changes nothing (F03's transaction).
"""

import json
import logging
import time
import tomllib
from pathlib import Path

import pytest

from engine.runtime.audio import EMPTY_AUDIO, AudioState, MusicEntry, SoundLoop
from engine.runtime.commands import AudioRestore, NvlPage, PlayVoice, Say, ShowStage
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.state import GameState, StateInvalid
from tests.runtime import fuzz_state
from tests.runtime.conftest import make_state, round_trip, state_b_json
from tests.runtime.stage_story import load_example
from tests.runtime.story import (advance, checkpoints, fingerprint, launched, load_files, start)
from tests.runtime.test_audio_exec import AC08, L, M, ac08_program
from tests.runtime.test_values import type_tree

F08 = Path(__file__).resolve().parents[1] / "fixtures" / "F08"
HOSTILE = tomllib.loads((F08 / "restore" / "hostile_audio.toml").read_text(encoding="utf-8"))


# --- Rows (hostile_audio.toml) ----------------------------------------------------------------

def _expand(value):
    if type(value) is str and value.startswith("@"):
        kind, _, count = value[1:].partition(":")
        n = int(count)
        if kind == "music":
            return [{"file": f"bgm/m{i:03}.ogg", "loop": i == n - 1, "volume": 100}
                    for i in range(n)]
        if kind == "sounds":
            return [{"file": f"sfx/s{i:03}.ogg", "volume": 50} for i in range(n)]
        if kind == "zz":
            return ("ZZMARK" + "a" * n)[:n]
        raise ValueError(value)
    if type(value) is list:
        return [_expand(v) for v in value]
    if type(value) is dict:
        return {k: _expand(v) for k, v in value.items()}
    return value


def state_with(row: dict) -> dict:
    data = state_b_json()
    if row.get("missing"):
        data.pop("audio", None)
    else:
        data["audio"] = _expand(json.loads(row["json"]))
    return data


REJECTED = HOSTILE["rejected"]
ACCEPTED = HOSTILE["accepted"]


def test_the_table_covers_every_row_of_the_ac():
    assert len(REJECTED) == 28 and len(ACCEPTED) == 11
    assert len({r["id"] for r in REJECTED + ACCEPTED}) == 39


# --- AC-F08-13 — hostile audio state is rejected --------------------------------------------

@pytest.mark.parametrize("row", REJECTED, ids=[r["id"] for r in REJECTED])
def test_ac_f08_13_rejected(row):
    data = state_with(row)
    began = time.perf_counter()
    with pytest.raises(StateInvalid) as caught:
        GameState.from_json(data)
    assert time.perf_counter() - began < 1.0
    assert type(caught.value) is StateInvalid and caught.value.reason == "audio"
    assert "ZZMARK" not in str(caught.value) and "ZZMARK" not in repr(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


@pytest.mark.parametrize("row", ACCEPTED, ids=[r["id"] for r in ACCEPTED])
def test_ac_f08_13_accepted(row):
    data = state_with(row)
    state = GameState.from_json(data)
    if row.get("missing"):
        assert state.audio == AudioState()
        return
    assert state.audio.to_json() == data["audio"]
    assert round_trip(state) == state
    assert state.save_problem() is None


def test_ac_f08_13_two_looping_entries_restore_the_first_looping_one():
    """PR-F08-22: the presentation plays the first looping entry; the state keeps both."""
    row = next(r for r in ACCEPTED if r["id"] == "loop-two-true")
    audio = GameState.from_json(state_with(row)).audio
    assert next(e for e in audio.music if e.loop).file == "bgm/a.ogg"


def test_ac_f08_13_fuzzed_values_load_or_raise_state_invalid():
    bases = [_expand(json.loads(r["json"])) for r in ACCEPTED if not r.get("missing")]
    base_state = state_b_json()
    for audio in fuzz_state.mutations(bases, 2_000, seed=8):
        data = dict(base_state, audio=audio)
        try:
            state = GameState.from_json(data)
        except StateInvalid as error:
            assert "ZZMARK" not in str(error)
            continue
        assert round_trip(state) == state


@pytest.mark.slow
def test_ac_f08_13_fuzzed_values_slow():
    bases = [_expand(json.loads(r["json"])) for r in ACCEPTED if not r.get("missing")]
    for audio in fuzz_state.mutations(bases, 20_000, seed=9, inflate=True):
        try:
            GameState.from_json(dict(state_b_json(), audio=audio))
        except StateInvalid:
            pass


def test_a_refused_state_never_reaches_restore(tmp_path):
    """Restore validation is ``from_json``'s, before anything changes: the story keeps going
    with its music."""
    program = ac08_program(tmp_path)
    interp = start(program)
    for _ in range(4):
        advance(interp)
    interp.take_commands(1 << 30)
    before = fingerprint(interp)
    for row in REJECTED:
        data = interp.checkpoint().to_json()
        data["audio"] = _expand(json.loads(row["json"]))
        with pytest.raises(StateInvalid):
            GameState.from_json(data)
    assert fingerprint(interp) == before
    advance(interp)
    assert interp.current.text == "k5."


def test_an_accepted_odd_path_restores_as_written(tmp_path):
    """The path rules aren't checked here: ``../../ZZMARK.ogg`` reaches the presentation,
    which plays it as missing with W29 (PR-F08-15, AC-F08-39)."""
    program = ac08_program(tmp_path)
    interp = start(program)
    data = interp.checkpoint().to_json()
    data["audio"] = {"music": [{"file": "../../ZZMARK.ogg", "loop": True, "volume": 100}],
                     "sounds": []}
    state = GameState.from_json(data)
    assert interp.restore(state).result is RestoreResult.OK
    burst = interp.take_commands(10)
    assert burst[0] == AudioRestore(state.audio, "restore")
    assert interp.checkpoint().audio == state.audio and interp.audio == state.audio


# --- AC-F08-12 — the audio state round-trips; old saves load ---------------------------------

def _same(state: GameState) -> None:
    again = GameState.from_json(json.loads(json.dumps(state.to_json())))
    assert again == state
    assert type_tree(again.to_json()["audio"]) == type_tree(state.to_json()["audio"])
    assert type(again.audio) is AudioState
    assert all(type(e) is MusicEntry for e in again.audio.music)
    assert all(type(e) is SoundLoop for e in again.audio.sounds)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ac_f08_12_example_game_checkpoints_round_trip(seed):
    result = load_example()
    assert result.program is not None
    for state in checkpoints(start(result.program, seed=seed)):
        _same(state)


def test_ac_f08_12_ac08_checkpoints_round_trip(tmp_path):
    states = checkpoints(start(ac08_program(tmp_path)))
    assert len(states) == len(AC08) + 2
    for state in states:
        _same(state)
    assert states[4].to_json()["audio"] == {                # row 4's "k4."
        "music": [M("bgm/festival.ogg", False, 60), M("bgm/shrine_steps.ogg", False, 100),
                  M("bgm/omen.ogg", True, 100)],
        "sounds": []}
    assert json.dumps(states[4].to_json()["audio"]) == (
        '{"music": [{"file": "bgm/festival.ogg", "loop": false, "volume": 60}, {"file": '
        '"bgm/shrine_steps.ogg", "loop": false, "volume": 100}, {"file": "bgm/omen.ogg", '
        '"loop": true, "volume": 100}], "sounds": []}')
    assert states[10].to_json()["audio"]["sounds"] == [L("sfx/rain.ogg", 80),
                                                       L("sfx/crowd.ogg", 100)]


def test_ac_f08_12_a_save_from_before_f08_loads_silent(tmp_path, caplog):
    program = ac08_program(tmp_path)
    interp = start(program)
    for _ in range(4):
        advance(interp)                                     # music plays now
    assert interp.audio.music
    data = interp.checkpoint().to_json()
    del data["audio"]
    old = GameState.from_json(data)
    assert old.audio == AudioState()
    with caplog.at_level(logging.DEBUG, logger="vn"):
        interp.take_commands(1 << 30)
        assert interp.restore(old).result is RestoreResult.OK
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    burst = interp.take_commands(10)
    assert burst[0] == AudioRestore(AudioState(), "restore")      # the music is silent
    assert interp.checkpoint().audio == AudioState()


def test_audio_is_always_written():
    assert make_state().to_json()["audio"] == {"music": [], "sounds": []}
    assert "audio" in GameState.from_json(state_b_json()).to_json()


def test_a_voice_key_is_an_unknown_key():
    """F03 I-2: no ``voice`` in the state; the key is refused as unknown."""
    data = state_b_json()
    data["voice"] = "voice/hana_014.ogg"
    with pytest.raises(StateInvalid) as caught:
        GameState.from_json(data)
    assert caught.value.reason == "unknown_key"


# --- restore.vns (§5.4) ----------------------------------------------------------------------

def test_restore_vns_checkpoints(tmp_path):
    program = load_files(tmp_path, {"main.vns": (F08 / "restore" / "restore.vns").read_text(
        encoding="utf-8")})
    a, b, c = checkpoints(start(program))
    assert a.audio == AudioState((MusicEntry("bgm/festival.ogg", True, 100),),
                                 (SoundLoop("sfx/rain.ogg", 40),))
    assert b.audio == AudioState((MusicEntry("bgm/omen.ogg", False, 100),
                                  MusicEntry("bgm/shrine_steps.ogg", True, 100)), ())
    assert c.audio == AudioState()
    interp = launched(program)
    for state in (c, a, b):
        assert interp.restore(round_trip(state)).result is RestoreResult.OK
        burst = interp.take_commands(10)
        assert burst[0] == AudioRestore(state.audio, "restore")
        kinds = [type(x) for x in burst]
        if state is a:                                      # "A." has a voice
            assert kinds == [AudioRestore, NvlPage, ShowStage, PlayVoice, Say]   # F17 I-3
            assert burst[3] == PlayVoice(a.position, "voice/hana_014.ogg", True)
        else:
            assert kinds == [AudioRestore, NvlPage, ShowStage, Say]
        assert interp.checkpoint() == state and interp.status is Status.WAITING
    # Old save B (no audio key) restores silent.
    data = b.to_json()
    del data["audio"]
    assert interp.restore(GameState.from_json(data)).result is RestoreResult.OK
    assert interp.take_commands(1)[0] == AudioRestore(AudioState(), "restore")


# --- F11 C11 — save_problem covers the new field ---------------------------------------------

def _with_audio(audio: AudioState) -> GameState:
    state = make_state()
    object.__setattr__(state, "audio", audio)
    return state


@pytest.mark.parametrize("audio, problem", [
    (AudioState(), None),
    (AudioState(tuple(MusicEntry(f"m{i}.ogg", False, 1) for i in range(64))), None),
    (AudioState(tuple(MusicEntry(f"m{i}.ogg", False, 1) for i in range(65))), "audio"),
    (AudioState((), tuple(SoundLoop(f"s{i}.ogg", 1) for i in range(17))), "audio"),
    (AudioState((), (SoundLoop("a.ogg", 1), SoundLoop("a.ogg", 2))), "audio"),
    (AudioState((MusicEntry("", True, 1),)), "audio"),
    (AudioState((MusicEntry("x" * 1025, True, 1),)), "audio"),
    (AudioState((MusicEntry("a.ogg", True, 101),)), "audio"),
    (AudioState((MusicEntry("a.ogg", 1, 100),)), "audio"),           # type: ignore[arg-type]
    (AudioState((MusicEntry("a.ogg", True, True),)), "audio"),       # type: ignore[arg-type]
    (AudioState((MusicEntry(5, True, 100),)), "audio"),              # type: ignore[arg-type]
    (AudioState((MusicEntry("a" + chr(0xD800) + chr(0xDC00) + ".ogg", True, 1),)),
     "lone_surrogate"),
    (AudioState((MusicEntry("a\ud800.ogg", True, 1),)), None),       # round-trips as an escape
], ids=["empty", "64", "65", "17-sounds", "same-sound", "empty-file", "1025", "volume-101",
        "loop-int", "volume-bool", "file-int", "surrogate-pair", "lone-surrogate"])
def test_save_problem_covers_audio(audio, problem):
    state = _with_audio(audio)
    assert state.save_problem() == problem
    if problem is None:
        assert round_trip(state) == state
    else:
        if problem == "lone_surrogate":                     # reads back as one character
            assert round_trip(state) != state
        else:
            with pytest.raises(StateInvalid):
                round_trip(state)


def test_every_checkpoint_of_an_audio_story_is_saveable(tmp_path):
    for state in checkpoints(start(ac08_program(tmp_path))):
        assert state.save_problem() is None
    assert EMPTY_AUDIO.save_problem() is None
