"""The example game's audio (F08 step 5 milestone; step 12: PR-F08-33, AC-F08-15, 41, 48, 58).

``game/audio/`` holds exactly the files ``tests/fixtures/F08/make_audio.py`` writes, each a
small playable WAV, plus ``LICENSES.txt``, the license record of every one (AC-F08-58).
Regenerate them with ``.venv/Scripts/python tests/fixtures/F08/make_audio.py``.

The example-game halves of the step 12 ACs (their unit halves are in ``test_reconcile.py``
and ``test_device.py``):

- AC-F08-58: the script uses every PR-F08-33 item, every file has its record, and the headless
  runs of all five seeds log nothing in ``script``, ``runtime``, or ``audio`` (the windowed
  runs: AC-F08-15 below, AC-F03-70 and AC-F08-41's one W30).
- AC-F08-15: ``checkpoint().audio`` at every wait is the same headless (``run_headless``,
  which builds no ``AudioService``; AC-F03-68's subprocess shows it needs no pygame, so no
  mixer) and windowed (the App on SDL's dummy driver, the same seed and picks). The AST half
  is ``tests/runtime/test_audio_exec.py``.
- AC-F08-41: under ``SDL_AUDIODRIVER=f08_none`` the example plays to its end on ``NullMixer``
  with exactly one WARNING, W30.
- AC-F08-48: the example's commands up to line 5, 20, and the last, fed to Service S with
  skipping on, then skipping off: the music and the looping effects heard are the line's
  state.
"""

import functools
import hashlib
import logging
import os
import re
from pathlib import Path

import pytest

from engine.audio import backend as audio_backend
from engine.audio.backend import W30_NO_DEVICE, NullMixer, PygameMixer
from engine.audio.backend import open_backend as REAL_OPEN_BACKEND   # before any session's fake
from engine.audio.limits import EFFECT_CHANNELS
from engine.audio.sniff import declared_seconds, sniff
from engine.core.config_schema import AudioConfig
from engine.runtime.commands import Advance, Choose, PlayMusic, PlaySound
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.script.menu import Menu
from tests.fixtures.F08.make_audio import EXAMPLE, LICENSE_RECORD, license_record

REPO = Path(__file__).resolve().parents[2]
GAME = REPO / "game"
GAME_AUDIO = GAME / "audio"
LENGTHS = {"bgm/lantern_walk.wav": 8.0, "bgm/bridge_night.wav": 8.0, "sfx/chime.wav": 0.8,
           "sfx/river.wav": 4.0, "sfx/firework.wav": 2.0,
           "blips/hana.wav": 0.06, "blips/daichi.wav": 0.08}        # F06 step 3
QUIET_AREAS = ("vn.script", "vn.runtime", "vn.audio")


def test_game_audio_holds_exactly_the_generated_files():
    found = sorted(p.relative_to(GAME_AUDIO).as_posix() for p in GAME_AUDIO.rglob("*")
                   if p.is_file() and not p.name.startswith("."))     # .gitkeep
    assert found == sorted((*EXAMPLE, LICENSE_RECORD))


def test_the_example_files_are_small_playable_wavs():
    lengths = {}
    for name in EXAMPLE:
        data = (GAME_AUDIO / name).read_bytes()
        sniffed = sniff(data, ".wav")
        assert sniffed is not None and len(data) < 400_000
        lengths[name] = declared_seconds(sniffed)
    voices = {name: lengths.pop(name) for name in list(lengths) if name.startswith("voice/")}
    assert lengths == LENGTHS
    assert len(voices) == 3 and all(1.5 <= s <= 5.0 for s in voices.values()), voices


# --- AC-F08-58: the license records and the script --------------------------------------------

def test_ac_f08_58_every_audio_file_has_its_license_record():
    """One entry per file: CC0 or original, naming its author and source, with the file's
    SHA-256; the record is exactly what ``make_audio.py`` writes (LF, UTF-8)."""
    record = (GAME_AUDIO / LICENSE_RECORD).read_bytes()
    assert b"\r" not in record
    text = record.decode("utf-8")
    entries = {m.group(1): m.group(0)
               for m in re.finditer(r"^File: (\S+)\n(?:\w[^\n]*\n?)+", text, re.M)}
    assert sorted(entries) == sorted(EXAMPLE)
    files = {}
    for name, entry in entries.items():
        data = (GAME_AUDIO / name).read_bytes()
        files[name] = data
        assert re.search(r"^License: (CC0 1\.0|original)", entry, re.M), entry
        assert re.search(r"^Author: \S", entry, re.M) and re.search(r"^Source: \S", entry,
                                                                     re.M), entry
        assert f"SHA-256: {hashlib.sha256(data).hexdigest()}" in entry, name
    assert text == license_record({name: files[name] for name in EXAMPLE})


def _script() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted((GAME / "script").rglob("*.vns")))


def test_ac_f08_58_the_script_uses_every_pr_f08_33_item():
    from tests.runtime.corpus import EXAMPLE_SEEDS, example_images, example_program, play

    script = _script()
    for pattern in (r'^\s+play music "[^"]+" .*\bfadein \d', r'^\s+queue music "',
                    r'^\s+stop music fadeout 0\s*$', r'^\s+play sound "[^"]+" .*\bloop\b',
                    r'^\s+voice "voice/[^"]+"\s*$'):
        assert re.search(pattern, script, re.M), pattern
    # A music change (play music while another track plays) and a one-shot over a looping
    # effect, in every seed's run.
    for seed in EXAMPLE_SEEDS:
        played = play(example_program(), seed, example_images())
        music, loops, change, over = (), set(), False, False
        for cmd in played.commands:
            if type(cmd) is PlayMusic:
                change |= bool(music) and music[0] != cmd.file
                music = (cmd.file,)
            elif type(cmd) is PlaySound:
                if cmd.loop:
                    loops.add(cmd.file)
                else:
                    over |= bool(loops)
            elif type(cmd).__name__ == "StopMusic":
                music = ()
        assert change and over, seed


def test_ac_f08_58_headless_runs_log_nothing(caplog):
    """Every seed plays to its end headless with no WARNING or ERROR in ``script``,
    ``runtime``, or ``audio``."""
    from tests.runtime.corpus import (EXAMPLE_PICKS, EXAMPLE_SEEDS, example_images,
                                      example_inputs)
    from tests.runtime.stage_story import example_minigames, load_example

    with caplog.at_level(logging.DEBUG):
        result = load_example()
        assert result.program is not None
        for seed in EXAMPLE_SEEDS:
            commands = run_headless(result.program, seed=seed, image_files=example_images(),
                                    inputs=example_inputs(seed, EXAMPLE_PICKS[seed]),
                                    minigames=example_minigames())
            assert type(commands[-1]).__name__ == "StoryEnded", (seed, commands[-1])
    assert [(r.name, r.getMessage()) for r in caplog.records
            if r.levelno >= logging.WARNING and r.name.startswith(QUIET_AREAS)] == []


# --- AC-F08-15: headless and windowed give the same audio state ---------------------------------

def _recording(states: list) -> object:
    """``Interpreter.run`` that records ``[(sid, steps), checkpoint().audio]`` at each new
    wait for a line or menu (the App calls ``run`` every frame; a wait is recorded once).
    Story waits (F09 transitions and pauses, F18 cards) aren't checkpoints and are left
    out: the window ends them by time or Space, headless at once."""
    real = Interpreter.run

    def run(self, *args, **kwargs):
        out = real(self, *args, **kwargs)
        if self.status is Status.WAITING and self.waiting_for is None:
            key = [self.current.sid, self.steps]
            if not states or states[-1][0] != key:
                states.append([key, self.checkpoint().audio.to_json()])
        return out

    return run


def _windowed(session, game: Path, monkeypatch, *, look=None) -> tuple[int, list, list]:
    """The example in the App with ``--seed 1``, Space pressed until the end (the first
    choice at each menu): (exit code, the waits' audio states, the lines shown). The
    service opens a real device (``open_backend``, not the session's FakeMixer)."""
    from tests.app.test_story_driver import EXAMPLE_FRAMES, _play_example

    states: list = []
    monkeypatch.setattr(Interpreter, "run", _recording(states))
    monkeypatch.setattr(audio_backend, "open_backend", REAL_OPEN_BACKEND)
    if look is not None:
        for frame in range(2, EXAMPLE_FRAMES):
            session.at(frame, look)
    code, shown, _first = _play_example(session, game, argv=["run", str(game), "--seed", "1"])
    return code, states, shown


@functools.cache
def _headless_states() -> list:
    """``run_headless`` (seed 1, the first choice at each menu) with ``_recording``; no
    ``AudioService`` may be built. That a headless run needs no pygame at all (so no mixer)
    is AC-F03-68's subprocess (``tests/runtime/test_story_headless.py``)."""
    from engine.audio.service import AudioService
    from tests.runtime.corpus import example_images, example_inputs
    from tests.runtime.stage_story import example_minigames, load_example

    def refuse(*args, **kwargs):
        raise AssertionError("a headless run built an AudioService")

    states: list = []
    program, inputs, images = load_example().program, example_inputs(1), example_images()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Interpreter, "run", _recording(states))
        patch.setattr(AudioService, "__init__", refuse)
        commands = run_headless(program, seed=1, inputs=inputs, image_files=images,
                                minigames=example_minigames())
    assert type(commands[-1]).__name__ == "StoryEnded", commands[-1]
    return states


@pytest.mark.display
@pytest.mark.skipif(os.environ.get("SDL_AUDIODRIVER") != "dummy",
                    reason="needs SDL's dummy audio driver (tests/conftest.py)")
def test_ac_f08_15_headless_and_windowed_audio_states_are_equal(tmp_path, user_roots,
                                                                 scripted_app, monkeypatch):
    from tests.app.test_story_load_screen import copy_example, records

    headless = _headless_states()          # first: _windowed patches Interpreter.run
    game = copy_example(tmp_path / "game")
    code, windowed, shown = _windowed(scripted_app, game, monkeypatch)
    assert code == 0 and len(shown) == 58          # F17: 7 nvl; F19: 4 at the end; F24-4: 2;
    #                                                F25-4: 6 (the map, the cross-examination);
    #                                                F26-4: 2 (around the phone chat);
    #                                                F27-4: 1 (before the shed's room);
    #                                                F23 s6: 2 (the lantern memory game)
    assert windowed == headless
    # The run is audible: music, the river, and the queue are in the states.
    assert any(state["sounds"] for _key, state in headless)
    assert any(len(state["music"]) == 2 for _key, state in headless)
    app = scripted_app.apps[-1]
    assert isinstance(app.audio.backend, PygameMixer)
    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert problems == []


# --- AC-F08-41: no sound device -----------------------------------------------------------------

@pytest.mark.display
@pytest.mark.mixer
def test_ac_f08_41_no_sound_device(tmp_path, user_roots, scripted_app, monkeypatch):
    from tests.app.test_story_load_screen import copy_example, records

    headless = _headless_states()          # first: _windowed patches Interpreter.run
    game = copy_example(tmp_path / "game")
    monkeypatch.setenv("SDL_AUDIODRIVER", "f08_none")
    seen: list = []

    def look(app):
        audio = app.audio
        if audio is not None and app.story is not None and app.story.status is Status.WAITING:
            audio.set_volumes(50, 60, 70, 80)                # they work with no device
            audio.set_background(False, False)
            audio.set_background(True, True)
            seen.append((type(audio.backend), audio.voice_playing()))

    code, windowed, shown = _windowed(scripted_app, game, monkeypatch, look=look)
    assert code == 0 and len(shown) == 58          # F17: 7 nvl; F19: 4 at the end; F24-4: 2;
    #                                                F25-4: 6 (the map, the cross-examination);
    #                                                F26-4: 2 (around the phone chat);
    #                                                F27-4: 1 (before the shed's room);
    #                                                F23 s6: 2 (the lantern memory game)
    assert windowed == headless
    assert seen and set(seen) == {(NullMixer, False)}
    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert problems == [("WARNING", "audio", W30_NO_DEVICE)]
    app = scripted_app.apps[-1]
    assert app.story.status is Status.ENDED


# --- AC-F08-48: skip --------------------------------------------------------------------------

def _waits() -> list[tuple[bool, list, object]]:
    """The example (seed 1, the first choice at each menu) wait by wait: (is a line, the
    audio commands released before it, ``checkpoint().audio`` there). Story waits (F09,
    F18) and the poem (F24-4) end at once, as headless (``corpus.settle``)."""
    from engine.app.story import AUDIO_COMMANDS
    from tests.runtime.corpus import (example_images, example_program, launched, settle,
                                      take_all)

    interp = launched(example_program(), example_images())
    interp.new_game(1)
    interp.run(10_000)
    out = []
    while True:
        settle(interp)
        audio = [c for c in take_all(interp) if type(c) in AUDIO_COMMANDS]
        if interp.status is not Status.WAITING:
            out.append((False, audio, None))
            return out
        current = interp.current
        out.append((type(current) is not Menu, audio, interp.checkpoint().audio))
        if type(current) is Menu:
            interp.post(Choose(current.sid, interp.choices.waiting.pickable[0]))
        else:
            interp.post(Advance(current.sid))
        interp.run(10_000)


def _example_service(tmp_path):
    from tests.audio.conftest import ServiceS

    s = ServiceS(GAME, AudioConfig())
    for name in EXAMPLE:
        data = (GAME_AUDIO / name).read_bytes()
        s.mixer.register(data, name, declared_seconds(sniff(data, ".wav")))
    return s


@pytest.mark.parametrize("n", [5, 20, -1])
def test_ac_f08_48_skipping_to_line_n_then_stopping_matches_its_state(tmp_path, n):
    waits = _waits()
    lines = [i for i, (is_line, _, _) in enumerate(waits) if is_line]
    stop = lines[n - 1] if n > 0 else lines[-1]
    s = _example_service(tmp_path)
    s.service.set_skipping(True)
    for _is_line, audio, _state in waits[:stop + 1]:
        s.feed(*audio)
        s.run(0.05, step=0.05)                               # one skipped line per frame
    state = waits[stop][2]
    s.run(0.5, step=0.05)
    s.service.set_skipping(False)
    s.run(0.1, step=0.05)
    music = s.mixer.music
    heard = None if music is None else (music.sound.name, music.loops < 0)
    want = None if not state.music else (state.music[0].file, state.music[0].loop)
    assert heard == want, (n, state)
    loops = {p.sound.name for channel, p in s.mixer.playing.items()
             if channel in EFFECT_CHANNELS and p.loops < 0
             and channel in s.mixer.busy_channels()}
    assert loops == {loop.file for loop in state.sounds}
    assert loops == {"sfx/river.wav"}                       # the river runs from line 1
    if n == -1:
        assert want == ("bgm/lantern_walk.wav", False)       # plays once, the queue after
        assert s.mixer.armed_name() == "bgm/bridge_night.wav"
