"""F11 C10 and C12 (F11 ``04`` §7.6, §19.2; ``07`` I-1, I-8): ``restore(..., check_only=True)``
and DEFAULT_FAILED as a load sees it.

TR-F11-06: a ``check_only`` restore changes nothing observable on the interpreter, whatever
its result. It runs restore steps 1-2 only (the identity scheme, the positions, and every
registered position check), so its result is the full restore's for those rows and OK for a
state whose ``default`` or line would fail (advisory; the commit is the transaction).
"""

import copy
import logging

import pytest

from engine.runtime import interpreter as interp_mod
from engine.runtime.interpreter import POSITION_CHECKS, RestoreResult, Status, register_executor
from engine.script import nodes
from tests.runtime.story import advance, fingerprint, launched, load_files, start, texts
from tests.runtime.test_restore import (AC60_T, AC61_ROWS, STATUSES, _edit, _flow, at_text,
                                        from_json, play_out, state_b)

OK = RestoreResult.OK
NOT_FOUND = RestoreResult.POSITION_NOT_FOUND
DEFAULT_FAILED = RestoreResult.DEFAULT_FAILED


def observed(interp) -> tuple:
    """06 §0.5's fingerprint plus what else a restore may touch: the ``$``/default ring, the
    W46 notes, the call stack object, the running piece, the dice core object, and the
    sent-words record."""
    running = interp.running
    return (fingerprint(interp), list(interp.recent_py), list(interp._restore_warnings),
            id(interp.call_stack), running.file, running.piece, id(interp.core),
            set(interp._words_logged), interp.current)


def check(interp, state, *, use_hints=False, caplog=None):
    """``check_only`` must change nothing and log nothing; its outcome."""
    before = observed(interp)
    variables = copy.deepcopy(dict(state.variables))
    if caplog is not None:
        caplog.clear()
    outcome = interp.restore(state, use_hints=use_hints, check_only=True)
    assert observed(interp) == before
    assert dict(state.variables) == variables
    if caplog is not None:
        assert caplog.records == []
    assert outcome.error is None and outcome.result is not DEFAULT_FAILED
    return outcome


# --- TR-F11-06: AC-F03-61's position rows, with check_only -------------------------------------

@pytest.mark.parametrize("edit, use_hints, result", AC61_ROWS.values(), ids=AC61_ROWS.keys())
def test_check_only_gives_the_restore_result_and_changes_nothing(tmp_path, caplog, edit,
                                                                  use_hints, result):
    program, data = state_b(tmp_path)
    interp = start(program)
    interp.take_commands(10)
    state = from_json(edit(data, program))
    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert check(interp, state, use_hints=use_hints, caplog=caplog).result is result
    assert interp.restore(state, use_hints=use_hints).result is result     # the same verdict


def test_check_only_ok_then_the_commit(tmp_path):
    """The load path: check, then commit (F11 §7.6 steps 4-5)."""
    program, data = state_b(tmp_path)
    interp = start(program)
    interp.take_commands(10)
    state = from_json(data)
    assert check(interp, state).result is OK
    assert interp.take_commands(10) == []
    assert interp.restore(state).result is OK
    assert texts(interp.take_commands(10)) == ["End."]
    assert interp.checkpoint() == state


@pytest.mark.parametrize("reach", STATUSES.values(), ids=STATUSES.keys())
def test_check_only_in_every_status(tmp_path, monkeypatch, reach):
    program = _flow(tmp_path)
    six = at_text(start(program), "6")
    interp = launched(program)
    reach(interp, monkeypatch)
    status = interp.status
    assert check(interp, six).result is OK
    data = six.to_json()
    data["position"]["sid"] = "start/000000000000"
    assert check(interp, from_json(data)).result is NOT_FOUND
    data = six.to_json()
    data["identity_scheme"] = 2
    assert check(interp, from_json(data)).result is RestoreResult.SCHEME_MISMATCH
    assert interp.status is status


# --- Advisory: no author code, no presenter ----------------------------------------------------

def test_check_only_runs_no_default(tmp_path, caplog):
    """A failing default is the commit's to find (I-1); a spying one never runs here."""
    T = AC60_T + "⏎define calls = []⏎define spy = lambda: calls.append(1) or 0⏎default probe = spy()"
    program, data = state_b(tmp_path, T=T)
    interp = start(program)
    interp.take_commands(10)
    calls = interp.G["calls"]
    count = len(calls)
    failing = from_json(_edit(("c", "probe"), trust="x")(data))
    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert check(interp, failing, caplog=caplog).result is OK
    assert len(calls) == count
    before = fingerprint(interp)
    outcome = interp.restore(failing)
    assert outcome.result is DEFAULT_FAILED and outcome.error.code == "E85d"
    assert fingerprint(interp) == before


def test_check_only_never_presents_the_line(tmp_path, caplog):
    """No E75h (a line that can't be shown) and no W46 note: the presenter doesn't run."""
    program, data = state_b(tmp_path)
    interp = start(program)
    interp.take_commands(10)
    data["position"] = {"sid": program.at("start", (0,)).sid, "at": ["start", [0]]}
    data["variables"]["hana_name"] = 3
    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert check(interp, from_json(data), caplog=caplog).result is OK
    assert interp.restore(from_json(data)).error.code == "E75h"


def test_check_only_notes_no_w46(tmp_path, caplog):
    program = load_files(tmp_path, {"main.vns": 'label start:\n    $ note = "x"\n'
                                                '    "Say {var=note}."\n    "End."\n'})
    interp = start(program)
    data = interp.checkpoint().to_json()
    del data["variables"]["note"]
    state = from_json(data)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert check(interp, state, caplog=caplog).result is OK
        caplog.clear()
        assert interp.restore(state).result is OK
    assert [r.levelno for r in caplog.records] == [logging.WARNING]       # W46, at the commit


# --- Every feature's position check (F11 I-1; F07's pickable keys) -----------------------------

def test_a_position_check_refuses_in_both_modes(tmp_path, monkeypatch, caplog):
    program, data = state_b(tmp_path)
    interp = start(program)
    interp.take_commands(10)
    state = from_json(data)
    seen = []

    def refuse(at_interp, stmt, at_state):
        seen.append((at_interp, stmt.sid, at_state))
        return False

    monkeypatch.setitem(POSITION_CHECKS, nodes.Say, refuse)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert check(interp, state, caplog=caplog).result is NOT_FOUND
    before = fingerprint(interp)
    assert interp.restore(state).result is NOT_FOUND
    assert fingerprint(interp) == before
    assert seen == [(interp, state.position, state)] * 2
    monkeypatch.setitem(POSITION_CHECKS, nodes.Say, lambda *args: True)
    assert check(interp, state).result is OK
    assert interp.restore(state).result is OK


def test_a_position_check_needs_a_presenter():
    class Probe(nodes.Statement):
        pass

    with pytest.raises(ValueError, match="needs a presenter"):
        register_executor(Probe, lambda i, s: None, check=lambda i, s, st: True)
    assert Probe not in interp_mod.EXECUTORS and Probe not in POSITION_CHECKS


# --- C12: DEFAULT_FAILED carries what F11 needs, logged once -----------------------------------

LONG = "Z" * 5_000


@pytest.mark.parametrize("T, variables", [
    (AC60_T, {"trust": "x"}),                               # trust + 1 fails
    ("define pick = lambda v: 1 if v == 0 else {}[v]⏎default c = pick(trust)",
     {"trust": LONG}),                                      # the exception text holds it
], ids=["failing default", "long saved text"])
def test_default_failed_is_logged_once_and_echoed(tmp_path, caplog, T, variables):
    """``error.code`` for W82, ``error.logged`` so nobody logs it again, one ERROR record
    whose saved text is echoed (SEC-F11-09b: never the 5,000 characters)."""
    program, data = state_b(tmp_path, T=T)
    interp = start(program)
    advance(interp)
    interp.take_commands(10)
    bad = from_json(_edit(("c",), **variables)(data))
    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert check(interp, bad).result is OK
        caplog.clear()
        outcome = interp.restore(bad)
    assert outcome.result is DEFAULT_FAILED and outcome.error.code.startswith("E85")
    assert outcome.error.logged is True
    errors = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [(r.name, r.levelno) for r in errors] == [("vn.runtime", logging.ERROR)]
    text = errors[0].getMessage() + (errors[0].exc_text or "")
    assert "Z" * 121 not in text and "Z" * 121 not in outcome.error.format()
    assert ("ZZZ" in text) is (variables["trust"] == LONG)     # echoed, and cut
    assert interp.status is Status.WAITING
    play_out(interp)                                        # the story goes on unchanged


def test_default_failed_never_fails_the_story(tmp_path):
    """No ``StoryFailed`` is released: the caller shows a notice, not the error screen."""
    program, data = state_b(tmp_path, T=AC60_T)
    interp = start(program)
    interp.take_commands(10)
    outcome = interp.restore(from_json(_edit(("c",), trust="x")(data)))
    assert outcome.result is DEFAULT_FAILED
    assert interp.take_commands(10) == [] and interp.status is Status.WAITING
    assert interp.checkpoint() is not None


def test_the_docstrings_say_notice_not_error_screen():
    """I-8: the outcome and restore docstrings name the notice; no error-screen promise."""
    doc = interp_mod.RestoreOutcome.__doc__
    assert "notice" in doc and "never the error screen" in doc
    assert "check_only" in interp_mod.Interpreter.restore.__doc__
