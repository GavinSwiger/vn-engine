"""F03 step 9 — restore (``04-technical.md`` §7.5, §9, §9.1; TR-F03-03, TR-F03-04).

``Interpreter.restore`` is a transaction: it checks the scheme and every position, copies
the variables, fills missing defaults inside ``G`` and rolls them back on failure, and only
then commits and holds the restore burst. ACs: AC-F03-18 (restore half), 28, 34, 37, 42, 59,
60, 61, 63, 64 (restore half), 65, and AC-F03-83's status rows (its watchdog row is step 12).
``driver.restore`` rows run on the app driver with a fake clock and no window.
"""

import json
import logging
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from engine.app.story import RuntimeStoryDriver
from engine.runtime import limits
from engine.runtime.character import Character
from engine.runtime.audio import EMPTY_AUDIO
from engine.runtime.commands import (Advance, AudioRestore, NvlPage, Say, ShowStage, Span, Style,
                                     StoryEnded, StoryFailed, TaggedText)
from engine.runtime.interpreter import Interpreter, RestoreOutcome, RestoreResult, Status
from engine.runtime.stage import EMPTY_STAGE
from engine.runtime.state import GameState, StateInvalid
from engine.runtime.values import same_value
from tests.runtime import fuzz_state
from tests.runtime.conftest import round_trip
from tests.runtime.stage_story import load_example
from tests.runtime.story import (advance, checkpoints, fingerprint, launched, load_files,
                                 load_fixture, load_r, start, texts)
from tests.runtime.test_values import nested, type_tree
from tests.script.helpers import template_r


def plain(text: str) -> TaggedText:
    """F05: the resolved body of a line with no tags and no text style."""
    return TaggedText((Span(text, Style()),))


ROOT = Path(__file__).resolve().parents[2]
OK = RestoreResult.OK
NOT_FOUND = RestoreResult.POSITION_NOT_FOUND
MISMATCH = RestoreResult.SCHEME_MISMATCH
DEFAULT_FAILED = RestoreResult.DEFAULT_FAILED


def from_json(data: dict) -> GameState:
    """The path every outside state takes: JSON text, then ``from_json``."""
    return GameState.from_json(json.loads(json.dumps(data, ensure_ascii=True)))


def at_text(interp: Interpreter, text: str) -> GameState:
    """Advance until the line ``text`` waits; its checkpoint."""
    while interp.current is None or getattr(interp.current, "text", None) != text:
        advance(interp)
    return interp.checkpoint()


def play_out(interp: Interpreter) -> list:
    """Take the pending commands, then advance to the end; every command in order."""
    out = interp.take_commands(1 << 30)
    while interp.status is Status.WAITING:
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        out.extend(interp.take_commands(1 << 30))
    return out


class TickClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1e-6
        return self.now


def state_b(root: Path, T: str | None = None):
    """06 §0.5's state B (R, S unused, waiting at line 9 ``End.``, seed 42) as JSON, with
    its program."""
    program = load_r(root, T=T)
    interp = start(program)
    advance(interp)
    assert interp.current.line == 9
    return program, interp.checkpoint().to_json()


# --- The outcome type -----------------------------------------------------------------------

def test_outcome_shape():
    assert [r.name for r in RestoreResult] == ["OK", "POSITION_NOT_FOUND", "SCHEME_MISMATCH",
                                               "DEFAULT_FAILED"]
    outcome = RestoreOutcome(OK)
    assert outcome.error is None
    with pytest.raises(AttributeError):
        outcome.result = DEFAULT_FAILED  # type: ignore[misc]


# --- AC-F03-18 — values survive a JSON round trip and a restore ----------------------------

VALUE_ROWS = [
    ("None", None), ("True", True), ("False", False), ("0", 0), ("-7", -7), ("1.5", 1.5),
    ("-0.0", -0.0), ("1e308", 1e308), ("5e-324", 5e-324),
    ("10**4300 - 1", 10**4300 - 1), ("-(10**4300 - 1)", -(10**4300 - 1)),
    ('""', ""), ('"日本語 😀 עברית"', "日本語 😀 עברית"), ('"\\ud800"', "\ud800"),
    ("[]", []), ("{}", {}), ('{"": 1}', {"": 1}), ('{"a": [1, {"b": None}]}', {"a": [1, {"b": None}]}),
    ('{f"k{i}": i for i in range(1000)}', {f"k{i}": i for i in range(1000)}),
    ("[" * 99 + "[]" + "]" * 99, nested(100)),
]


@pytest.mark.parametrize("source, value", VALUE_ROWS, ids=[r[0][:24] for r in VALUE_ROWS])
def test_ac_f03_18_values_survive_round_trip_and_restore(tmp_path, source, value):
    """Also AC-F03-55's AC-18 rows: the checkpoint round-trips equal, with its type tree,
    and dumps to the same text (merged from test_headless_example.py, test-review-F03.md)."""
    program = load_r(tmp_path, S=f"$ v = {source}")
    interp = start(program)
    state = at_text(interp, "End.")
    assert same_value(state.variables["v"], value)
    again = round_trip(state)
    assert again == state
    assert type_tree(again.variables["v"]) == type_tree(value)
    text = json.dumps(state.to_json(), ensure_ascii=True)
    assert json.dumps(again.to_json(), ensure_ascii=True) == text
    fresh = launched(program)
    assert fresh.restore(again).result is OK
    assert same_value(fresh.G["v"], value) and type_tree(fresh.G["v"]) == type_tree(value)
    assert fresh.checkpoint() == state


def test_ac_f03_18_shared_lists_are_separate_after_restore(tmp_path):
    program = load_r(tmp_path, S='$ a = [1]⏎[4]$ b = a⏎[4]"Mid."⏎[4]$ a.append(2)')
    interp = start(program)
    mid = round_trip(at_text(interp, "Mid."))
    fresh = launched(program)
    assert fresh.restore(mid).result is OK
    G = fresh.G
    assert G["a"] == G["b"] == [1] and G["a"] is not G["b"]
    advance(fresh)
    assert G["a"] == [1, 2] and G["b"] == [1]
    assert fresh.checkpoint().variables["b"] == [1]


# --- AC-F03-28 — defines run once per launch ------------------------------------------------

def test_ac_f03_28_defines_run_once(tmp_path):
    T = ('define calls = []⏎define note = calls.append("x")⏎define f = lambda: 1⏎'
         'define m = module("math")')
    program = load_r(tmp_path, T=T)
    driver = RuntimeStoryDriver(launched(program), clock=TickClock(), fixed_seed=42)
    G = driver.interp.G
    calls = G["calls"]
    states = []
    for _ in range(3):
        driver.new_game()
        assert driver.pump() and G["calls"] == ["x"]
        states.append(driver.checkpoint())
        driver.post(Advance(driver.interp.current.sid))
        assert driver.pump()
        states.append(driver.checkpoint())
    for state in states:
        assert not set(state.variables) & program.define_names
        assert driver.restore(round_trip(state)).result is OK
        assert G["calls"] is calls and calls == ["x"]
    assert callable(G["f"]) and G["m"].__name__ == "math" and isinstance(G["hana"], Character)


# --- AC-F03-34 — a shown name follows its variable, and rolls back --------------------------

AC34_S = ('hana "Before."⏎[4]$ hana_name = "Hana"⏎[4]hana "After."⏎[4]$ hana_name = ""⏎'
          '[4]hana "Hidden."⏎[4]$ hana_name = "ハナ 😀"⏎[4]hana "Uni."')


def test_ac_f03_34_name_from_and_restore(tmp_path):
    program = load_r(tmp_path, S=AC34_S)
    interp = start(program)
    before = at_text(interp, "Before.")
    commands = [*interp.take_commands(1 << 30)]
    commands += play_out(interp)
    names = [c.name for c in commands if type(c) is Say and c.speaker == "hana"]
    assert names == ["???", "???", "Hana", "", "ハナ 😀"]
    says = [c for c in commands if type(c) is Say]
    assert all(c.name == "???" for c in says[:2])           # earlier lines keep their name
    assert interp.status is Status.ENDED
    assert interp.restore(round_trip(before)).result is OK
    audio, nvl, stage, shown = interp.take_commands(10)
    assert audio == AudioRestore(EMPTY_AUDIO, "restore")    # F08: the saved audio first
    assert nvl == NvlPage(False)                            # F17: the saved text mode
    assert stage == ShowStage(EMPTY_STAGE, restored=True)   # F04: then the saved stage
    assert (shown.text, shown.name, shown.restored) == ("Before.", "???", True)
    assert interp.G["hana_name"] == "???"


# --- AC-F03-37 — modules come back with the defines of a fresh launch -----------------------

def test_ac_f03_37_modules_after_restore(tmp_path):
    T = 'define math = module("math")⏎define osp = module("os.path")⏎define plug = module("pluggy")'
    program = load_r(tmp_path, S='$ x = math.floor(2.5)⏎[4]"Mid."⏎[4]$ y = math.ceil(2.5)', T=T)
    interp = start(program)
    states = checkpoints(interp)
    assert states[-1].variables["x"] == 2
    for state in states:
        assert not {"math", "osp", "plug"} & set(state.variables)
    mid = next(s for s in states if program.get(s.position).text == "Mid.")
    fresh = launched(load_r(tmp_path / "again", S='$ x = math.floor(2.5)⏎[4]"Mid."⏎'
                                                  '[4]$ y = math.ceil(2.5)', T=T))
    assert fresh.restore(round_trip(mid)).result is OK
    advance(fresh)
    assert fresh.G["y"] == 3 and type(fresh.G["y"]) is int


# --- AC-F03-42 — random results replay after a restore --------------------------------------

AC42_S = ('"Before."⏎[4]$ r1 = dice.roll(1, 1000000)⏎[4]$ r2 = dice.pick(fortunes)⏎'
          '[4]$ r3 = dice.decimal()⏎[4]$ r4 = dice.shuffle([1, 2, 3, 4, 5, 6, 7, 8])')
DRAWS = ("r1", "r2", "r3", "r4")


def test_ac_f03_42_draws_replay(tmp_path):
    root = tmp_path / "game"
    root.joinpath("script").mkdir(parents=True)
    text = template_r(S=AC42_S, replace={9: '    "End."⏎[4]$ r5 = dice.roll(1, 1000000)⏎'
                                            '[4]"After."'})
    program = load_files(root, {"main.vns": text})
    interp = start(program)
    before = at_text(interp, "Before.")
    end = at_text(interp, "End.")
    first = {k: end.variables[k] for k in DRAWS}
    after = at_text(interp, "After.").variables["r5"]
    for _ in range(3):
        assert interp.restore(round_trip(before)).result is OK
        assert at_text(interp, "End.").variables["r1"] == first["r1"]
        assert {k: interp.G[k] for k in DRAWS} == first
    assert interp.restore(round_trip(end)).result is OK
    assert at_text(interp, "After.").variables["r5"] == after


# --- AC-F03-59 — a restore shows the line again ---------------------------------------------

def test_ac_f03_59_restore_into_an_ended_story(tmp_path):
    program = load_fixture(tmp_path, "flow")
    interp = start(program)
    six = at_text(interp, "6")
    original = interp.take_commands(1 << 30)[-1]
    assert original.text == "6"
    assert play_out(interp)[-1] == StoryEnded()
    assert interp.status is Status.ENDED
    assert interp.restore(round_trip(six)).result is OK
    assert interp.take_commands(10) == [AudioRestore(six.audio, "restore"),       # F08
                                        NvlPage(False),                            # F17
                                        ShowStage(six.stage, restored=True),       # F04
                                        Say(**{**_fields(original), "restored": True})]
    assert interp.status is Status.WAITING and interp.checkpoint() == six
    assert texts(play_out(interp)) == ["7"]
    assert interp.status is Status.ENDED


def _fields(cmd: Say) -> dict:
    return {name: getattr(cmd, name) for name in Say.__dataclass_fields__}


# --- AC-F03-60 — a restore fills missing defaults -------------------------------------------

AC60_T = "default c = trust + 1⏎default d = c * 2"


def _edit(remove=(), **values):
    def apply(data):
        for name in remove:
            del data["variables"][name]
        data["variables"].update(values)
        return data
    return apply


AC60_FILLED = {
    "remove trust, c, d": (_edit(("trust", "c", "d")), {"trust": 0, "c": 1, "d": 2}),
    "trust 5, remove c, d": (_edit(("c", "d"), trust=5), {"trust": 5, "c": 6, "d": 12}),
    "trust None, c 'x', d 0": (_edit(trust=None, c="x", d=0), {"trust": None, "c": "x", "d": 0}),
    "add old_var": (_edit(old_var=1), {"trust": 0, "c": 1, "d": 2, "old_var": 1}),
}


@pytest.mark.parametrize("edit, expected", AC60_FILLED.values(), ids=AC60_FILLED.keys())
def test_ac_f03_60_defaults_are_filled(tmp_path, edit, expected):
    program, data = state_b(tmp_path, T=AC60_T)
    interp = start(program)
    advance(interp)
    assert interp.restore(from_json(edit(data))).result is OK
    for name, value in expected.items():
        assert same_value(interp.G[name], value), name
    assert interp.take_commands(10)[3].text == "End."    # after AudioRestore, NvlPage, ShowStage
    assert interp.checkpoint().variables["c"] == expected["c"]


def test_ac_f03_60_no_default_runs_for_a_present_name(tmp_path):
    T = AC60_T + "⏎define calls = []⏎define spy = lambda: calls.append(1) or 0⏎default probe = spy()"
    program, data = state_b(tmp_path, T=T)
    interp = start(program)
    calls = interp.G["calls"]
    count = len(calls)
    assert interp.restore(from_json(_edit(trust=None, c="x", d=0)(data))).result is OK
    assert len(calls) == count
    assert interp.restore(from_json(_edit(("probe",))(data))).result is OK
    assert len(calls) == count + 1


def test_ac_f03_60_a_define_name_is_dropped(tmp_path, caplog):
    program, data = state_b(tmp_path, T=AC60_T)
    interp = start(program)
    fortunes = interp.G["fortunes"]
    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert interp.restore(from_json(_edit(fortunes=[])(data))).result is OK
    assert interp.G["fortunes"] is fortunes and len(fortunes) == 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert warnings[0].name == "vn.runtime" and '"fortunes"' in warnings[0].getMessage()
    assert "fortunes" not in interp.checkpoint().variables


def test_ac_f03_60_a_failing_default_changes_nothing(tmp_path, caplog):
    program, data = state_b(tmp_path, T=AC60_T)
    interp = start(program)
    advance(interp)
    interp.take_commands(10)
    before = fingerprint(interp)
    with caplog.at_level(logging.DEBUG, logger="vn"):
        outcome = interp.restore(from_json(_edit(("c",), trust="x")(data)))
    assert outcome.result is DEFAULT_FAILED
    assert outcome.error.format().startswith(
        "script/main.vns, line 11: default c couldn't be set: this adds text and a whole number")
    assert outcome.error.logged
    assert [r.levelno for r in caplog.records if r.levelno >= logging.WARNING] == [logging.ERROR]
    assert fingerprint(interp) == before
    assert interp.take_commands(10) == []
    assert interp.current.line == 9
    assert texts(play_out(interp)) == []
    assert interp.status is Status.ENDED


def test_ac_f03_60_the_driver_does_not_fail_the_story(tmp_path):
    program, data = state_b(tmp_path, T=AC60_T)
    driver = RuntimeStoryDriver(launched(program), clock=TickClock(), fixed_seed=42)
    driver.new_game()
    _, _, line = driver.pump()                  # F08: AudioRestore; F04: ShowStage; the line
    driver.post(Advance(line.sid))
    before = fingerprint(driver.interp)
    outcome = driver.restore(from_json(_edit(("c",), trust="x")(data)))
    assert outcome.result is DEFAULT_FAILED and outcome.error.code == "E85d"
    assert fingerprint(driver.interp) == before and driver.status is Status.WAITING
    assert [c.text for c in driver.pump()] == ["End."]       # the queued Advance still counts


def test_driver_restore_drops_events_queued_for_the_old_position(tmp_path):
    program, data = state_b(tmp_path)
    driver = RuntimeStoryDriver(launched(program), clock=TickClock(), fixed_seed=42)
    driver.new_game()
    _, _, line = driver.pump()                  # F08: AudioRestore; F04: ShowStage; the line
    driver.post(Advance(line.sid))
    state = from_json(data)
    assert driver.restore(state).result is OK
    assert driver.pump() == [AudioRestore(state.audio, "restore"),           # F08
                             NvlPage(False),                                 # F17
                             ShowStage(state.stage, restored=True),
                             Say(state.position, None, None, None, (), "End.", body=plain("End."),
                                 restored=True)]
    assert driver.status is Status.WAITING and driver.checkpoint() == state


# --- AC-F03-61 — a position that isn't there -------------------------------------------------

def _position(sid=None, at=None):
    def apply(data, program):
        if sid is not None:
            data["position"]["sid"] = sid(program) if callable(sid) else sid
        if at is not None:
            data["position"]["at"] = at
        return data
    return apply


def _stack(entry):
    def apply(data, program):
        data["call_stack"] = [entry(program)]
        return data
    return apply


def _scheme(data, program):
    data["identity_scheme"] = 2
    return data


LINE_7 = lambda p: p.at("start", (0,)).sid          # noqa: E731
LINE_9 = lambda p: p.at("start", (1,)).sid          # noqa: E731
UNKNOWN = "start/000000000000"

AC61_ROWS = {
    "unknown sid": (_position(UNKNOWN), False, NOT_FOUND),
    "define:hana": (_position("define:hana"), False, NOT_FOUND),
    "default:trust": (_position("default:trust"), False, NOT_FOUND),
    "a label": (_position("start"), False, NOT_FOUND),
    "the return line": (_position(lambda p: p.at("start", (2,)).sid), False, NOT_FOUND),
    "empty sid": (_position(""), False, NOT_FOUND),
    "lone surrogate": (_position("\ud800"), False, NOT_FOUND),
    "sid ~0": (_position(lambda p: LINE_9(p) + "~0"), False, NOT_FOUND),
    "sid ~02": (_position(lambda p: LINE_9(p) + "~02"), False, NOT_FOUND),
    "sid of 1,024 characters": (_position("s" * 1024), False, NOT_FOUND),
    "call_stack holds a line": (_stack(lambda p: {"sid": LINE_7(p), "at": ["start", [0]]}),
                                False, NOT_FOUND),
    "call_stack unknown sid": (_stack(lambda p: {"sid": UNKNOWN, "at": ["start", [0]]}),
                               False, NOT_FOUND),
    "call_stack hint to a line": (_stack(lambda p: {"sid": UNKNOWN, "at": ["start", [0]]}),
                                  True, NOT_FOUND),
    "identity_scheme 2": (_scheme, False, MISMATCH),
    "identity_scheme 999 with hints": (lambda d, p: {**d, "identity_scheme": 999}, True,
                                       MISMATCH),
    "hint to line 7": (_position(UNKNOWN, ["start", [0]]), True, OK),
    "hint to the return": (_position(UNKNOWN, ["start", [2]]), True, NOT_FOUND),
    "hint -1": (_position(UNKNOWN, ["start", [-1]]), True, NOT_FOUND),
    "hint into a line": (_position(UNKNOWN, ["start", [0, 99, 0]]), True, NOT_FOUND),
    "hint to an unknown label": (_position(UNKNOWN, ["nowhere", [0]]), True, NOT_FOUND),
    "hint of 128 ints": (_position(UNKNOWN, ["start", [0] * 128]), True, NOT_FOUND),
    "valid hint, no use_hints": (_position(UNKNOWN, ["start", [0]]), False, NOT_FOUND),
}


@pytest.mark.parametrize("edit, use_hints, result", AC61_ROWS.values(), ids=AC61_ROWS.keys())
def test_ac_f03_61_positions(tmp_path, edit, use_hints, result):
    program, data = state_b(tmp_path)
    interp = start(program)
    line_7 = interp.current
    interp.take_commands(10)
    before = fingerprint(interp)
    outcome = interp.restore(from_json(edit(data, program)), use_hints=use_hints)
    assert outcome.result is result and outcome.error is None
    if result is OK:
        audio, nvl, stage, shown = interp.take_commands(10)
        assert audio == AudioRestore(EMPTY_AUDIO, "restore")        # F08
        assert nvl == NvlPage(False)                                # F17
        assert stage == ShowStage(EMPTY_STAGE, restored=True)       # F04
        assert shown.sid == line_7.sid and shown.text == "Start." and shown.restored
        return
    assert fingerprint(interp) == before
    assert interp.take_commands(10) == []
    advance(interp)
    assert texts(interp.take_commands(10)) == ["End."]


def test_ac_f03_61_a_line_a_patch_deleted(tmp_path):
    old = load_r(tmp_path / "v1", S='"Extra."')
    interp = start(old)
    extra = at_text(interp, "Extra.")
    new = start(load_r(tmp_path / "v2"))
    new.take_commands(10)
    before = fingerprint(new)
    assert new.restore(round_trip(extra)).result is NOT_FOUND
    assert new.restore(round_trip(extra), use_hints=True).result is OK   # hint: line 8 → End.
    assert new.current.text == "End."
    assert fingerprint(new) != before


def test_hints_never_resolve_a_found_sid_of_the_wrong_type(tmp_path):
    program, data = state_b(tmp_path)
    interp = start(program)
    edit = _position(lambda p: p.at("start", (2,)).sid, ["start", [1]])
    assert interp.restore(from_json(edit(data, program)), use_hints=True).result is NOT_FOUND


# --- AC-F03-83 — restore works in every status (the watchdog row is step 12) -----------------

AC83_T = "default base = 1⏎default c = base + 1"


def _flow(root: Path):
    root.joinpath("script").mkdir(parents=True)
    flow = (Path(__file__).resolve().parents[1] / "fixtures" / "F03" / "flow" / "main.vns")
    return load_files(root, {"main.vns": flow.read_text(encoding="utf-8")
                             + AC83_T.replace("⏎", "\n") + "\n"})


def _status_idle(interp, monkeypatch):
    pass


def _status_waiting(interp, monkeypatch):
    interp.new_game(42)
    interp.run(10_000)
    advance(interp)
    assert interp.current.text == "2"


def _status_running(interp, monkeypatch):
    interp.new_game(42)
    interp.run(10_000)
    interp.post(Advance(interp.current.sid))
    interp.run(1)
    assert interp.status is Status.RUNNING and interp.current.text == "2"


def _status_ended(interp, monkeypatch):
    interp.new_game(42)
    interp.run(10_000)
    play_out(interp)


def _status_failed(interp, monkeypatch):
    with monkeypatch.context() as patched:
        patched.setattr(limits, "STEP_LIMIT", 0)
        interp.new_game(42)
        interp.run(10_000)
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
    assert interp.status is Status.FAILED
    assert interp.take_commands(10)[-1].error.code == "E45"
    interp._released.append(StoryEnded())       # a pending command of the failed run


STATUSES = {"IDLE": _status_idle, "WAITING": _status_waiting, "RUNNING": _status_running,
            "ENDED": _status_ended, "FAILED": _status_failed}


@pytest.mark.parametrize("reach", STATUSES.values(), ids=STATUSES.keys())
def test_ac_f03_83_restore_in_every_status(tmp_path, monkeypatch, reach):
    program = _flow(tmp_path)
    six = round_trip(at_text(start(program), "6"))
    interp = launched(program)
    reach(interp, monkeypatch)
    assert interp.restore(six).result is OK
    assert interp.take_commands(10) == [AudioRestore(six.audio, "restore"),       # F08
                                        NvlPage(False),                            # F17
                                        ShowStage(six.stage, restored=True),       # F04
                                        Say(six.position, None, None, None, (), "6",
                                            body=plain("6"), restored=True)]
    assert interp.status is Status.WAITING and interp.checkpoint() == six
    assert play_out(interp) == [Say(program.at("b", (2,)).sid, None, None, None, (), "7",
                                    body=plain("7")),
                                StoryEnded()]


@pytest.mark.parametrize("reach", STATUSES.values(), ids=STATUSES.keys())
def test_ac_f03_83_a_failing_default_in_every_status(tmp_path, monkeypatch, reach):
    program = _flow(tmp_path)
    data = at_text(start(program), "6").to_json()
    data["variables"] = {"base": "x"}
    bad = from_json(data)
    interp = launched(program)
    reach(interp, monkeypatch)
    failed = interp.status is Status.FAILED
    before = fingerprint(interp)
    outcome = interp.restore(bad)
    assert outcome.result is DEFAULT_FAILED and outcome.error.code == "E85d"
    assert fingerprint(interp) == before
    if failed:
        assert interp.status is Status.FAILED and interp.checkpoint() is None


def test_a_mid_run_restore_drops_the_unfinished_burst(tmp_path):
    program = load_r(tmp_path, S='$ x = 1⏎[4]"Mid."')
    interp = start(program)
    first = interp.checkpoint()
    interp.take_commands(10)
    interp.post(Advance(interp.current.sid))
    interp.run(1)
    interp._hold(StoryEnded())                   # an unreleased command of the burst
    interp._released.append(StoryEnded())        # and a released one nobody took yet
    assert interp.status is Status.RUNNING and interp.steps == 1
    assert interp.restore(first).result is OK
    assert texts(interp.take_commands(10)) == ["Start."]
    assert interp._held == [] and interp.steps == 0 and list(interp.entered) == []
    assert "x" not in interp.G


def test_a_real_ctrl_c_in_a_default_rolls_back_and_is_reraised(tmp_path):
    T = "define boom = lambda: (_ for _ in ()).throw(KeyboardInterrupt)⏎default late = boom()"
    program = load_r(tmp_path, T=T)
    _, data = state_b(tmp_path / "b")
    interp = launched(program)
    interp.core.seed(7)
    interp.core.ready = True
    interp.G["kept"] = [1]
    before = fingerprint(interp)
    with pytest.raises(KeyboardInterrupt):
        interp.restore(from_json(data))
    assert fingerprint(interp) == before


def test_a_fired_guard_in_a_default_is_e85m_and_changes_nothing(tmp_path):
    class Fired:
        def enter(self):
            pass

        def exit(self):
            pass

        def consume_fired(self):
            return True

    T = "define boom = lambda: (_ for _ in ()).throw(KeyboardInterrupt)⏎default late = boom()"
    program = load_r(tmp_path, T=T)
    _, data = state_b(tmp_path / "b")
    interp = launched(program, guard=Fired())
    before = fingerprint(interp)
    outcome = interp.restore(from_json(data))
    assert outcome.result is DEFAULT_FAILED and outcome.error.code == "E85m"
    assert outcome.error.format().startswith("script/main.vns, line 12: default late")
    assert fingerprint(interp) == before


def test_a_line_that_cannot_be_shown_refuses_the_restore(tmp_path):
    """A saved ``hana_name`` that isn't text: the presenter's E75h refuses the restore
    (``DEFAULT_FAILED`` with the error) instead of failing the story half-restored."""
    program, data = state_b(tmp_path)
    interp = start(program)
    interp.take_commands(10)
    data["position"] = {"sid": program.at("start", (0,)).sid, "at": ["start", [0]]}
    data["variables"]["hana_name"] = 3
    before = fingerprint(interp)
    outcome = interp.restore(from_json(data))
    assert outcome.result is DEFAULT_FAILED and outcome.error.code == "E75h"
    assert fingerprint(interp) == before


def test_restore_ignores_start_options(tmp_path):
    from engine.core.startvalues import StartOptions
    program, data = state_b(tmp_path)
    interp = launched(program, start=StartOptions(label=None, values=(("trust", 9),)))
    assert interp.restore(from_json(data)).result is OK
    assert interp.G["trust"] == 0


# --- AC-F03-63 — checks first; a bad state never runs code ----------------------------------

AC63_T = "define calls = []⏎define spy = lambda: calls.append(1) or 0⏎default probe = spy()"

AUDIT = textwrap.dedent(r"""
    import builtins, json, sys
    from pathlib import Path
    from engine.runtime.state import GameState, StateInvalid
    from tests.runtime.story import advance, fingerprint, load_r, start
    from tests.runtime.test_restore import AC61_ROWS, AC63_T
    from tests.runtime.test_state_json import REJECTED

    root = Path(sys.argv[1])
    program = load_r(root / "b", T=AC63_T)
    interp = start(program)
    advance(interp)
    data_b = interp.checkpoint().to_json()
    interp = start(load_r(root / "w", T=AC63_T))
    interp.take_commands(10)
    calls = interp.G["calls"]
    count = len(calls)
    rows = [(build(), False) for build in REJECTED.values()]
    rows += [(edit(json.loads(json.dumps(data_b)), program), hints)
             for edit, hints, result in AC61_ROWS.values() if result.name != "OK"]
    accepted = json.loads(json.dumps(data_b))
    del accepted["variables"]["probe"]
    accepted["variables"]["marker"] = "restored"
    before = fingerprint(interp)
    WATCHED = ("exec", "compile", "import", "open", "os.system", "os.exec", "os.listdir",
               "os.scandir", "subprocess.Popen", "socket.")
    state = {"on": False, "events": [], "probe_seen": None}
    real_eval, real_exec = builtins.eval, builtins.exec
    spied = []

    def spy_eval(*a, **k):
        spied.append("eval")
        return real_eval(*a, **k)

    def spy_exec(*a, **k):
        spied.append("exec")
        return real_exec(*a, **k)

    def hook(event, args):
        if not state["on"] or not event.startswith(WATCHED):
            return
        state["events"].append(event)
        if event == "exec" and state["probe_seen"] is None:
            code = args[0]
            G = interp.G
            state["probe_seen"] = (getattr(code, "co_filename", None),
                                   G.get("marker") == "restored")

    sys.addaudithook(hook)
    builtins.eval, builtins.exec = spy_eval, spy_exec
    results = []
    state["on"] = True
    for obj, hints in rows:
        try:
            st = GameState.from_json(obj)
        except StateInvalid:
            results.append("invalid")
            continue
        results.append(interp.restore(st, use_hints=hints).result.name)
    state["on"] = False
    print(json.dumps({"events": state["events"], "spied": spied, "results": results,
                      "same": fingerprint(interp) == before, "calls": len(calls) == count}))
    state["on"] = True
    outcome = interp.restore(GameState.from_json(accepted))
    state["on"] = False
    builtins.eval, builtins.exec = real_eval, real_exec
    print(json.dumps({"ok": outcome.result.name, "probe": state["probe_seen"],
                      "calls": len(calls) - count, "spied": spied}))
""")


def test_ac_f03_63_rejected_states_run_nothing(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYGAME_HIDE_SUPPORT_PROMPT="1")
    out = subprocess.run([sys.executable, "-c", AUDIT, str(tmp_path.resolve())], cwd=tmp_path,
                         env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    rejected, accepted = (json.loads(line) for line in out.stdout.strip().splitlines()[-2:])
    assert rejected["events"] == [] and rejected["spied"] == []
    assert rejected["same"] and rejected["calls"]
    assert set(rejected["results"]) == {"invalid", "POSITION_NOT_FOUND", "SCHEME_MISMATCH"}
    assert accepted["ok"] == "OK" and accepted["calls"] == 1
    assert accepted["probe"] == ["<script/main.vns>", True]


HOSTILE_TEXT = "__import__('os').system('echo ZZMARK > pwned.txt')"


def test_ac_f03_63_hostile_text_stays_text(tmp_path, monkeypatch):
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    program, data = state_b(tmp_path / "game", T="default note = 'n'")
    for name in ("note", "trust_note", "cmd", "code"):
        data["variables"][name] = HOSTILE_TEXT
    interp = launched(program)
    assert interp.restore(from_json(data)).result is OK
    play_out(interp)
    assert interp.status is Status.ENDED
    assert not (work / "pwned.txt").exists() and not (tmp_path / "pwned.txt").exists()
    for name in ("note", "trust_note", "cmd", "code"):
        assert interp.G[name] == HOSTILE_TEXT


# --- AC-F03-64 — state fuzzing (restore half) ------------------------------------------------

def _example_program():
    result = load_example()
    assert result.program is not None
    return result.program


def _fuzz(tmp_path: Path, count: int, seed: int, inflate: bool) -> dict[str, int]:
    """Each mutated state goes through ``from_json`` and, if accepted, ``restore`` on a
    waiting interpreter of its own story; every result but OK must leave the fingerprint
    unchanged. After an OK the base state is restored again to keep the story waiting."""
    program_r, b = state_b(tmp_path)
    example = _example_program()
    ex_states = [s.to_json() for s in checkpoints(start(example, seed=3))]
    tally: dict[str, int] = {}
    for program, bases, n in ((program_r, [b], count // 2),
                              (example, ex_states, count - count // 2)):
        interp = start(program)
        base = from_json(bases[0])
        assert interp.restore(base).result is OK
        for i, obj in enumerate(fuzz_state.mutations(bases, n, seed, inflate)):
            try:
                state = GameState.from_json(obj)
            except StateInvalid:
                tally["invalid"] = tally.get("invalid", 0) + 1
                continue
            interp.take_commands(1 << 30)
            before = fingerprint(interp)
            outcome = interp.restore(state, use_hints=bool(i % 2))
            assert type(outcome) is RestoreOutcome
            name = outcome.result.name
            tally[name] = tally.get(name, 0) + 1
            if outcome.result is OK:
                assert interp.status is Status.WAITING
                assert interp.restore(base).result is OK
            else:
                assert (outcome.error is not None) == (outcome.result is DEFAULT_FAILED)
                assert fingerprint(interp) == before
    return tally


def test_ac_f03_64_fuzz_ci(tmp_path):
    tally = _fuzz(tmp_path, 200, seed=64, inflate=False)
    assert tally.get("OK", 0) > 0 and tally.get("invalid", 0) > 0


@pytest.mark.slow
def test_ac_f03_64_fuzz_full(tmp_path):
    began = time.perf_counter()
    tally = _fuzz(tmp_path, 10_000, seed=6400, inflate=True)
    assert time.perf_counter() - began < 600
    assert tally.get("OK", 0) > 0 and tally.get("POSITION_NOT_FOUND", 0) > 0


# --- AC-F03-65 — an old save loads after a patch ---------------------------------------------

V2_DEFAULTS = {"gift": "lantern", "petals": 3, "route": ["river", "bridge"],
               "notes": {"seen": False}, "luck": 0.5}


def test_ac_f03_65_an_old_save_loads_after_a_patch(tmp_path, caplog):
    v1 = load_fixture(tmp_path / "v1", "patch/v1")
    saves = [json.dumps(s.to_json(), ensure_ascii=True) for s in checkpoints(start(v1))]
    assert len(saves) == 5
    v2 = load_fixture(tmp_path / "v2", "patch/v2")
    for text in saves:
        interp = launched(v2)
        with caplog.at_level(logging.DEBUG, logger="vn"):
            caplog.clear()
            assert interp.restore(GameState.from_json(json.loads(text))).result is OK
            for name, value in V2_DEFAULTS.items():
                assert same_value(interp.G[name], value), name
            commands = play_out(interp)
        assert commands[-1] == StoryEnded()
        assert texts(commands)[-1] == "Six."
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
