"""F28 s3 — ``effect`` at run time (F28 ``06-acceptance.md`` AC-F28-10, 11, 12; ``04`` §4.2,
§6.1–§6.3; TR-F28-02), Run H on template G and ``walk/`` (``glitch_story.py``), and the step 3
headless golden (06 §9 Step 3 milestone). AC-F28-11's W184 texts are the ``time = "run"`` rows
of ``cases.toml``, played here."""

import json
import logging

from engine.persist import saves
from engine.runtime.commands import (Advance, AudioRestore, Flash, Glitch, GlitchBurst, NvlPage,
                                     Say, Shake, ShowMenu, ShowStage, StepBack, StepForward,
                                     StoryFailed, StoryWait, WaitDone)
from engine.runtime.glitch import ALL_STOPS, EMPTY_GLITCH, GlitchEntry, GlitchState
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from tests.persist.save_support import make_save
from tests.runtime import effects_story, glitch_story
from tests.runtime.corpus import example_images, example_program
from tests.runtime.effects_story import bursts, of_type, take_all
from tests.runtime.glitch_story import launched, run_h, template_g, walk
from tests.runtime.menu_story import sid_at
from tests.script import message_cases

W184_ROWS = [c for c in message_cases.load_cases() if c.code == "W184"]


def _set(*entries: GlitchEntry) -> GlitchState:
    state = EMPTY_GLITCH
    for entry in entries:
        state = state.with_entry(entry)
    return state


def _glitches(commands) -> list[Glitch]:
    return of_type(commands, Glitch)


def _burst_of(commands, text: str) -> list:
    return next(b for b in bursts(commands) if any(type(c) is Say and c.text == text
                                                    for c in b))


def _w184(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "nothing jitters" in r.getMessage()]


# --- AC-F28-10 ---------------------------------------------------------------------------

def test_ac_f28_10_one_glitch_per_moment_after_flash(tmp_path):
    def B(program, line, kind, size, seconds, tag=None):
        return GlitchBurst(kind, tag, size, seconds, sid_at(program, line))
    menu = 'effect static on⏎menu:⏎[8]"One":⏎[12]$ x = 1⏎[8]"Two":⏎[12]$ x = 2'
    loop = ("label spin:⏎[4]$ n = 0⏎[4]jump spin_loop⏎label spin_loop:⏎[4]effect tear 0.2⏎"
            "[4]effect jitter hana "
            "0.2⏎[4]$ n += 1⏎[4]if n < 10000:⏎[8]jump spin_loop⏎[4]return")
    rows = [
        # S (T), the check on the run's commands (cmds) and "A."'s burst (a)
        (None, None, lambda p, cmds, a: _glitches(cmds) == []),
        ("effect tear 0.4", None, lambda p, cmds, a: _glitches(a) == [
            Glitch(EMPTY_GLITCH, (), (B(p, 5, "tear", None, 0.4),))]),
        ("effect tear⏎effect tear large 0.3", None, lambda p, cmds, a: _glitches(a) == [
            Glitch(EMPTY_GLITCH, (), (B(p, 6, "tear", "large", 0.3),))]),
        ("effect static small on⏎effect colorshift on", None, lambda p, cmds, a: _glitches(a) == [
            Glitch(_set(GlitchEntry("colorshift", None), GlitchEntry("static", "small")),
                   (("static", None), ("colorshift", None)), ())]),
        ("effect tear 0.4⏎effect tear off", None, lambda p, cmds, a: _glitches(a) == [
            Glitch(EMPTY_GLITCH, (("tear", None),), ())]),
        ("effect static on⏎effect tear 0.4⏎effect off", None, lambda p, cmds, a:
            _glitches(a) == [Glitch(EMPTY_GLITCH, ALL_STOPS, ())]
            and ALL_STOPS == (("tear", None), ("colorshift", None), ("static", None),
                              ("jitter", None))),
        ("effect jitter hana 0.5⏎effect static 0.5", None, lambda p, cmds, a: _glitches(a) == [
            Glitch(EMPTY_GLITCH, (), (B(p, 5, "jitter", None, 0.5, "hana"),
                                      B(p, 6, "static", None, 0.5)))]),
        ("shake⏎flash⏎effect tear⏎show hana sad", None, lambda p, cmds, a:
            [type(c) for c in a if type(c) in (ShowStage, Shake, Flash, Glitch, Say)]
            == [ShowStage, Shake, Flash, Glitch, Say]),
        ("effect tear⏎scene bg sea with fade", None, lambda p, cmds, a:
            [type(c) for c in bursts(cmds)[0][-3:]] == [ShowStage, Glitch, StoryWait]
            and _glitches(a) == []),
        ("pause 0.1⏎effect tear⏎show hana happy with dissolve", None, lambda p, cmds, a:
            len(of_type(cmds, StoryWait)) == 1 and _glitches(bursts(cmds)[0]) == []
            and len(_glitches(a)) == 1),                    # the picture is unchanged
        ("effect tear⏎pause 1.0", None, lambda p, cmds, a:
            [type(c) for c in bursts(cmds)[0][-2:]] == [Glitch, StoryWait]
            and bursts(cmds)[0][-1].seconds == 1.0),
        (menu, None, lambda p, cmds, a:
            [type(c) for c in cmds if type(c) in (Glitch, ShowMenu)] == [Glitch, ShowMenu]),
        ("call spin", loop, lambda p, cmds, a: _glitches(a) == [
            Glitch(EMPTY_GLITCH, (), (B(p, 13, "tear", None, 0.2),
                                      B(p, 14, "jitter", None, 0.2, "hana")))]),
    ]
    for n, (S, T, check) in enumerate(rows):
        program = template_g(tmp_path / str(n), S=S, T=T)
        cmds = run_h(program)
        assert not of_type(cmds, StoryFailed), (S, cmds[-1])
        has_a = any(type(c) is Say and c.text == "A." for c in cmds)
        a = _burst_of(cmds, "A.") if has_a else []
        assert check(program, cmds, a), (S, _glitches(cmds))
        assert all(len(_glitches(b)) <= 1 for b in bursts(cmds)), S
        if has_a:
            assert _glitches(_burst_of(cmds, "B.")) == [], S
    # F09's all/ fixture (no effect) releases no Glitch; F03's goldens: test_determinism.
    assert _glitches(effects_story.run_h(effects_story.fixture("all"))) == []


def test_the_headless_golden_with_glitch():
    """06 §9 Step 3 milestone: ``walk/`` by Run H, ``Glitch`` commands included."""
    assert glitch_story.GOLDEN.read_bytes() == glitch_story.golden_text().encode("ascii"), (
        "regenerate with: .venv/Scripts/python -m tests.runtime.glitch_story --write-golden")


# --- AC-F28-11 ---------------------------------------------------------------------------

def test_ac_f28_11_jitter_targets_w184_and_prunes(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    # The W184 rows of cases.toml (dev), under a folder named like an account (check P).
    assert len(W184_ROWS) == 3
    for case in W184_ROWS:
        root = tmp_path / "qauser7" / case.id
        program = glitch_story.load_game(effects_story.write_game(
            root, message_cases.main_text(case)))
        caplog.clear()
        cmds = run_h(program, dev=True)
        line = message_cases.parse_where(case.where)[1]
        assert _w184(caplog) == [f"script/main.vns, line {line}: {case.expect['exact']}"]
        assert _glitches(cmds) == []
        for text in _w184(caplog):
            assert "qauser7" not in text.lower() and str(tmp_path).lower() not in text.lower()
    # Once per statement, and dev only (the commands are the same).
    caplog.clear()
    looped = template_g(tmp_path / "loop", S="call w⏎call w⏎call w",
                        T="label w:⏎[4]effect jitter daichi⏎[4]return")
    run_h(looped, dev=True)
    assert len(_w184(caplog)) == 1
    row1 = template_g(tmp_path / "row1", S="effect jitter daichi")
    caplog.clear()
    assert run_h(row1, dev=False) == run_h(row1, dev=True)
    assert len(_w184(caplog)) == 1                          # the dev run's only
    caplog.clear()
    interp = launched(row1, dev=True)
    interp.glitch_warned.update(f"s{i}" for i in range(1_000))
    interp.new_game(42)
    interp.run(10_000)
    assert _w184(caplog) == [] and len(interp.glitch_warned) == 1_000
    # An absent tag turned off is silent (D6).
    caplog.clear()
    assert _glitches(run_h(template_g(tmp_path / "off", S="effect jitter daichi off"),
                           dev=True)) == []
    assert _w184(caplog) == []

    def at_lines(name, S, replace=None):
        interp = launched(template_g(tmp_path / name, S=S, replace=replace))
        interp.new_game(42)
        interp.run(10_000)
        first, at_a = take_all(interp), interp.checkpoint()
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        return interp, first, take_all(interp), at_a
    hana_large = _set(GlitchEntry("jitter", "large", "hana"))
    interp, a, _, at_a = at_lines("on", "effect jitter hana large on⏎show hana sad at left")
    assert _glitches(a)[0].lasting == hana_large and at_a.glitch == hana_large
    interp, a, b, _ = at_lines("hide", "effect jitter hana large on",
                            {7: '[4]hide hana⏎[4]hana "B."'})
    assert _glitches(b) == [Glitch(EMPTY_GLITCH, (), ())]
    assert interp.checkpoint().glitch == EMPTY_GLITCH
    assert _glitches(run_h(template_g(tmp_path / "gone", S="effect jitter hana 1.0⏎hide hana"))
                     ) == []
    interp, a, b, _ = at_lines("scene", "effect jitter hana on⏎effect static on",
                            {7: '[4]scene bg sea⏎[4]show hana happy⏎[4]hana "B."'})
    assert interp.checkpoint().glitch == _set(GlitchEntry("static", None))
    assert _glitches(b)[0].lasting == _set(GlitchEntry("static", None))


# --- AC-F28-12 ---------------------------------------------------------------------------

def _advance(interp) -> list:
    """Past the line or the wait the story waits at, to the next line."""
    if interp.waiting_for is not None:
        interp.post(WaitDone(interp.waiting_for))
    else:
        interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def _loaded(program, state: GameState) -> list:
    interp = launched(program)
    assert interp.restore(state).result is RestoreResult.OK
    return take_all(interp)


def _no_burst(commands) -> bool:
    return all(g.bursts == () and g.stops == () for g in _glitches(commands))


def test_ac_f28_12_checkpoints_saves_restore_and_rollback(caplog):
    program = walk()
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    w1 = interp.checkpoint()
    _advance(interp)                                        # to the with glitch wait
    assert interp.waiting_for is not None and interp.checkpoint() == w1
    assert interp.glitch.on and w1.glitch == EMPTY_GLITCH
    _advance(interp)
    w2 = interp.checkpoint()
    w2_set = _set(GlitchEntry("colorshift", None), GlitchEntry("static", "small"))
    assert w2.glitch == w2_set
    # A quick-save at W2 (its tear burst still running), then a load: Glitch(restored) right
    # after ShowStage(restored), no burst; a W1 load holds none; a hot reload is a load.
    read = saves.parse_full(make_save(w2), game_id=None)
    assert read.status is saves.SlotStatus.OK and read.state == w2
    burst = _loaded(program, read.state)
    kinds = [type(c) for c in burst]
    assert kinds[:5] == [AudioRestore, NvlPage, ShowStage, Glitch, Say]
    assert burst[3] == Glitch(w2_set, restored=True) and burst[2].restored
    assert _loaded(walk(), read.state) == burst
    assert _glitches(_loaded(program, w1)) == []
    # Rollback W4 → W3 → W2 → W1, then forward to W4.
    _advance(interp)
    w3 = interp.checkpoint()
    _advance(interp)
    assert interp.checkpoint().glitch == EMPTY_GLITCH and w3.glitch == w2_set
    for want in (w2_set, w2_set, EMPTY_GLITCH):             # W3, W2, W1
        interp.post(StepBack(1))
        interp.run(10_000)
        landing = take_all(interp)
        expected = [Glitch(want, restored=True)] if want.on else []
        assert _glitches(landing) == expected
    interp.post(StepForward(3))
    while interp.busy:
        interp.run(10_000)
    forward = take_all(interp)
    assert _glitches(forward) == [] and interp.current.line == 14
    # New game after W2: nothing glitched.
    interp.new_game(42)
    interp.run(10_000)
    assert _glitches(take_all(interp)) == [] and interp.checkpoint().glitch == EMPTY_GLITCH
    # A W2 save edited so the stage lacks hana but the set has jitter hana: loads without
    # the jitter, with no W184.
    data = w2.to_json()
    data["stage"]["sprites"] = []
    data["glitch"]["on"].append({"kind": "jitter", "tag": "hana", "size": None})
    edited = GameState.from_json(json.loads(json.dumps(data)))
    assert edited.glitch == w2_set
    caplog.set_level(logging.INFO)
    caplog.clear()
    loaded = launched(program, dev=True)
    assert loaded.restore(edited).result is RestoreResult.OK and _w184(caplog) == []
    # A hostile "glitch": F11's invalid-state path (DAMAGED), and the game keeps running.
    for value in ({"on": {}}, {"on": [{"kind": "ZZMARK", "size": None}]}):
        line = json.dumps({**w2.to_json(), "glitch": value}).encode("ascii") + b"\n"
        verdict = saves.parse_state_line(line, (0, len(line)))
        assert verdict.status is saves.SlotStatus.DAMAGED
        assert verdict.reason == "story state (glitch)"
    assert interp.status is Status.WAITING
    # F11's example saves in their pre-F28 form (no "glitch" key), and with variables named
    # glitch and static: EMPTY_GLITCH, the variables intact, and the same restore burst.
    example = example_program()
    for path in sorted(glitch_story.F28.parent.joinpath("F11", "example_saves").glob("*.vnsave")):
        read = saves.parse_full(path.read_bytes(), game_id=None)
        assert read.status is saves.SlotStatus.OK, path.name
        data = read.state.to_json()
        del data["glitch"]
        named = dict(data, variables={**data["variables"], "glitch": 1, "static": "on"})
        for old in (data, named):
            line = json.dumps(old).encode("ascii") + b"\n"
            verdict = saves.parse_state_line(line, (0, len(line)))
            assert verdict.status is saves.SlotStatus.OK, path.name
            assert verdict.state.glitch == EMPTY_GLITCH
        assert (verdict.state.variables["glitch"], verdict.state.variables["static"]) == (1, "on")
        pre = GameState.from_json(data)
        assert pre == read.state
        bursts_ = []
        for state in (pre, read.state):
            interp = Interpreter(example, run_launch(
                example, images=ImageSource.from_files(example_images())).namespace)
            assert interp.restore(state).result is RestoreResult.OK, path.name
            bursts_.append(take_all(interp))
        assert bursts_[0] == bursts_[1] and _glitches(bursts_[0]) == []
