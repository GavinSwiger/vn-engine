"""F14 steps 2–4 — back (``on_step_back``, ``restore(landing=)``, the G12 reset): AC-F14-03
(runtime rows, and the driver's New Game; the App's Main Menu → title → New Game row is in
``tests/app/test_rollback_install.py``'s AC-F14-29 run), AC-F14-05, AC-F14-07, AC-F14-26
(runtime rows; App R's at step 5), and AC-F14-28 (bad ``StepBack``/``StepForward`` events;
the driver's view once ENDED or FAILED)."""

import dataclasses
import logging
from pathlib import Path
from types import MappingProxyType

import pytest

from engine.app.story import RuntimeStoryDriver
from engine.runtime.commands import (Advance, AudioRestore, EndVoice, PlayVoice, RollbackView,
                                     Say, ShowMenu, StepBack, StepForward, StoryFailed,
                                     WaitDone)
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from engine.script.messages import format_message
from tests.runtime.conftest import round_trip
from tests.runtime.effects_story import load_game, take_all
from tests.runtime.rollback_story import (F14, back, forward, lands_on, launched, run_k, step,
                                          where)
from tests.runtime.story import fingerprint


def _variant(root: Path, old: str, new: str, **kwargs) -> Interpreter:
    """Run K's script with one edit, started (at A)."""
    text = (F14 / "steps" / "script" / "main.vns").read_text(encoding="utf-8")
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(text.replace(old, new, 1), encoding="utf-8")
    interp = launched(load_game(root), **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    return interp


# --- AC-F14-03 — loads, other restores, and new games reset the timeline --------------------------

def test_ac03_resets():
    for row in ("load", "jump", "check_only", "bad_position", "new_game", "driver_new_game",
                "landing"):
        interp, k = run_k("D2")
        t = interp.timeline
        kept, objects = t.states, list(t.states)
        assert len(kept) == 6
        if row == "load":
            assert interp.restore(round_trip(k["C"])).result is RestoreResult.OK
        elif row == "jump":                                 # an F20-style non-landing restore
            assert RuntimeStoryDriver(interp).restore(k["B"]).result is RestoreResult.OK
        elif row == "check_only":
            assert interp.restore(k["C"], check_only=True).result is RestoreResult.OK
        elif row == "bad_position":
            before = fingerprint(interp)
            bad = dataclasses.replace(k["C"], position="zz")
            assert interp.restore(bad).result is RestoreResult.POSITION_NOT_FOUND
            assert fingerprint(interp) == before
        elif row == "new_game":
            interp.new_game(42)
            assert t.states == [] and t.cursor == -1
            interp.run(10_000)
        elif row == "driver_new_game":                     # the shell's New Game (F10)
            driver = RuntimeStoryDriver(interp, fixed_seed=42)
            driver.new_game()
            assert t.states == [] and t.cursor == -1
            driver.pump()
        else:
            back(interp, 1)
        if row in ("check_only", "bad_position"):
            assert t.states is kept and all(a is b for a, b in zip(t.states, objects)), row
            assert len(t.states) == 6
        elif row == "landing":
            assert len(t.states) == 6 and t.cursor == 4
        else:
            assert t.states == [interp.checkpoint()] and t.states[0] is interp.checkpoint(), row
            assert t.cursor == 0 and where(interp, k) == {"load": "C", "jump": "B",
                                                          "new_game": "A",
                                                          "driver_new_game": "A"}[row]
            view = t.view(interp)
            assert view.ahead == 0 and not view.can_back, row
        if row == "load":                                   # three more lines: three back
            for _ in range(3):                              # M, D1, D2
                step(interp)
            take_all(interp)
            assert t.view(interp).back_room == 3
            released = back(interp, 4)
            assert where(interp, k) == "C" and t.refused == 1
            assert lands_on(interp, released, t.states[0])


# --- AC-F14-05 — back lands on the earlier step like a load -------------------------------------

def _spied_restore(calls: list):
    real = Interpreter.restore

    def spy(self, state, **kwargs):
        if kwargs.get("landing"):
            t = self.timeline
            index = next(i for i, s in enumerate(t.states) if s is state)
            calls.append(index <= t.cursor)                 # TR-F14-06
        return real(self, state, **kwargs)
    return spy


def _mid_run(interp) -> None:                              # sliced: RUNNING before S
    interp.post(Advance(interp.current.sid))
    interp.run(1)
    assert interp.status is Status.RUNNING


def test_ac05_back_lands_like_a_load(tmp_path: Path):
    rows = [("D2", [1], None, "D1", 1), ("D2", [2], None, "M", 2), ("D2", [5], None, "A", 5),
            ("D2", [9], None, "A", 5), ("F", [1], None, "S", 1), ("F", [1, 1], None, "D2", 2),
            ("D2", [1], _mid_run, "D2", 0)]
    calls: list[bool] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Interpreter, "restore", _spied_restore(calls))
        for start_at, counts, before, lands, ahead in rows:
            interp, k = run_k(start_at)
            if before is not None:
                before(interp)
            for n in counts:
                released = back(interp, n)
            row = (start_at, counts, lands)
            assert where(interp, k) == lands, row
            assert lands_on(interp, released, k[lands]), row
            assert interp.history == k[lands].history
            view = interp.timeline.view(interp)
            assert view.ahead == ahead and view.refused == (1 if counts == [9] else 0), row
            if lands == "M":
                said = [c for c in released if type(c) in (Say, ShowMenu)]
                assert [type(c) for c in said] == [Say, ShowMenu]
                assert all(c.restored for c in said) and interp.choices.picks == ()
            if row == ("F", [1], "S"):
                assert interp.checkpoint().call_stack == k["S"].call_stack != ()
            if row == ("F", [1, 1], "D2"):              # then advance x2 gives S, F
                assert interp.checkpoint().call_stack == ()
                step(interp)
                step(interp)
                assert where(interp, k) == "F" and interp.checkpoint() == k["F"]
        # (F09) K9@C during its 1.0 s pause: lands on C; a late WaitDone is ignored.
        interp = _variant(tmp_path / "k9", "    menu:\n", "    pause 1.0\n    menu:\n")
        step(interp)
        step(interp)
        c = interp.checkpoint()
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        wait = interp.waiting_for
        assert wait is not None and interp.timeline.view(interp).back_room == 3
        take_all(interp)
        released = back(interp, 1)
        assert lands_on(interp, released, c) and interp.waiting_for is None
        interp.post(WaitDone(wait))
        assert interp.status is Status.WAITING and interp.checkpoint() == c
    assert calls and all(calls)


# --- AC-F14-07 — the landed line's voice plays again --------------------------------------------

def test_ac07_the_voice_plays_again():
    interp, k = run_k("C")
    released = back(interp, 1)                                  # C → B
    assert lands_on(interp, released, k["B"])
    b = k["B"].position
    voice = released.index(PlayVoice(b, "voice/hana_002.ogg", restored=True))
    said = next(i for i, c in enumerate(released) if type(c) is Say)
    assert voice < said and released[said].restored
    step(interp)                                                # Advance: EndVoice before C
    released = take_all(interp)
    assert released.index(EndVoice(b)) < next(i for i, c in enumerate(released)
                                              if type(c) is Say)
    back(interp, 1)
    released = back(interp, 1)                                  # B → A: AudioRestore first
    assert type(released[0]) is AudioRestore and where(interp, k) == "A"
    released = forward(interp, 2)                               # A → C: nothing of B's
    assert where(interp, k) == "C" and lands_on(interp, released, k["C"])
    assert [c for c in released if type(c) is PlayVoice] == []


# --- AC-F14-28 — bad events are ignored ---------------------------------------------------------

def test_ac28_bad_events_are_ignored(caplog):
    """04 §12: a count that isn't an int from 1 to 1,000 is ignored with one DEBUG record;
    1,000 is clamped; forward when the story isn't live changes nothing."""
    interp, k = run_k("D2")
    before = fingerprint(interp)
    counts = (0, -1, 1001, 2.0, "2", True, None)
    with caplog.at_level(logging.DEBUG, logger="vn.runtime"):
        for event in (StepBack, StepForward):
            for count in counts:
                interp.post(event(count))  # type: ignore[arg-type]
    assert fingerprint(interp) == before and interp.timeline.refused == 0
    debug = [r for r in caplog.records if r.levelno == logging.DEBUG and r.name == "vn.runtime"]
    assert len(debug) == 2 * len(counts)
    back(interp, 1000)                                          # clamped to the room: A
    assert where(interp, k) == "A" and interp.timeline.refused == 1
    forward(interp, 1000)                                       # clamped to ahead: D2
    assert where(interp, k) == "D2" and interp.checkpoint() == k["D2"]
    for _ in range(3):                                          # S, F, then the end
        step(interp)
    assert interp.status is Status.ENDED
    back(interp, 2)
    ended = fingerprint(interp)
    assert forward(interp, 1) == [] and fingerprint(interp) == ended
    # The driver's view (step 4): ENDED has no room but still counts the steps ahead.
    t = interp.timeline
    assert RuntimeStoryDriver(interp).rollback_view() == RollbackView(
        True, False, 0, len(t.states) - 1 - t.cursor, t.refused)
    interp, _ = run_k("D2")                                     # FAILED
    interp.fail_timeout()
    take_all(interp)
    failed = fingerprint(interp)
    assert forward(interp, 1) == [] and fingerprint(interp) == failed
    assert RuntimeStoryDriver(interp).rollback_view() == RollbackView(False, False, 0, 0, 0)


# --- AC-F14-26 — a step that can't be restored ---------------------------------------------------

def test_ac26_a_step_that_cant_be_restored(tmp_path: Path, caplog):
    for dev in (True, False):
        for cause in ("position", "scheme", "default"):
            # AC-F03-60's row: default c = trust + 1 fails once trust is "x".
            interp = _variant(tmp_path / f"{cause}{dev}", 'default path = ""\n',
                              'default path = ""\ndefault trust = 1\ndefault c = trust + 1\n',
                              dev=dev)
            for _ in range(7):
                step(interp)
            take_all(interp)
            t = interp.timeline
            m = t.states[3]
            if cause == "position":
                bad = dataclasses.replace(m, position="zz")
            elif cause == "scheme":
                bad = dataclasses.replace(m, identity_scheme=m.identity_scheme + 1)
            else:
                variables = {k: v for k, v in m.variables.items() if k != "c"}
                bad = dataclasses.replace(m, variables=MappingProxyType({**variables,
                                                                         "trust": "x"}))
            t.states[3] = bad
            kept = t.states[4:]
            before = fingerprint(interp)
            caplog.clear()
            with caplog.at_level(logging.DEBUG):
                released = back(interp, 4)
            assert released == [] and fingerprint(interp) == before, (dev, cause)
            assert not any(type(c) is StoryFailed for c in released)
            assert t.states == kept and all(a is b for a, b in zip(t.states, kept))
            assert t.view(interp).back_room == 3 and t.refused == 1
            w90 = [r for r in caplog.records if getattr(r, "code", None) == "W90"]
            errors = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert len(errors) == (1 if cause == "default" else 0), (dev, cause)
            if dev or cause != "default":
                assert [(r.name, r.levelno, r.getMessage()) for r in w90] == [
                    ("vn.runtime", logging.WARNING, format_message("W90", ("start", cause)))]
            else:
                assert w90 == []
    assert format_message("W90", ("start", "position")) == (
        'Rollback stopped: a step in label "start" no longer matches the script (it was '
        'changed), so it and older steps were dropped.')
