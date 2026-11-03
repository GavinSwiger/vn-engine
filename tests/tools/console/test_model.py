"""F40 P4: the console model and its texts (``04`` §3, §7.1, §7.4; ``01`` §4.2, §6.3).
AC-F40-06, -07, -08, -09, -10, -19, -20, -21, -23, -27.

P1's runner is faked here (``FakeRunner``): a Code line is compiled as eval or exec and run
through ``Interpreter.author_call``, as ``runner.run_code`` does, without its checks."""

import logging
from dataclasses import dataclass

import pytest

from engine.app.hot_reload import ConsoleRequest
from engine.runtime.commands import Advance
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.runtime.replay import ReplayRun
from engine.tools.console import texts
from engine.tools.console.model import (HISTORY_MAX, INPUT_MAX, ConsoleModel, JumpTo, Nudge,
                                        RunCode, SetValue, Switch, Tab, Where, where_now)
from engine.tools.console.valuetext import CODE_MAX, ROW_MAX, value_text
from tests.runtime.flow_story import load_l

STORY = '''define hana = Character("Hana")
points trust 0 to 10
points luck
default mood = "calm"
default bag = []
default met = False
default coins = 3
default long = "x" * 300
lock replay garden "The Garden"
label start:
    scene black
    hana "One."
    $ mood = "warm"
    hana "Two."
    "End."
    return
label side:
    hana "Side."
    return
label garden:
    flowchart scene "Garden"
    hana "Garden."
    return
'''

NEEDLE = "zq_needle_81"


@pytest.fixture(scope="module")
def program(tmp_path_factory):
    return load_l(tmp_path_factory.mktemp("console_model"), STORY)


def started(program, *, replay: ReplayRun | None = None) -> Interpreter:
    store = PersistentStore(identity_scheme=program.identity_scheme)
    launch = run_launch(program, persistent=store)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    interp = Interpreter(program, launch.namespace, persistent=store)
    interp.new_game(42, replay=replay)
    interp.run(10_000)
    assert interp.status is Status.WAITING
    return interp


def advance(interp: Interpreter) -> None:
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)


@dataclass
class Outcome:
    lines: tuple
    ok: bool
    undone: str | None = None


class FakeRunner:
    """P1's ``run_code`` and ``guarded`` as the model calls them, plus W1's ``jump``."""

    def __init__(self, interp: Interpreter | None = None, *, long_output: bool = False):
        self.interp = interp
        self.ran: list[str] = []
        self.jumps: list[tuple[str, bool]] = []
        self.long_output = long_output

    def run_code(self, interp: Interpreter, line: str) -> Outcome:
        self.ran.append(line)
        if self.long_output:
            return Outcome(("y" * 5_000,), True)
        try:
            code, mode = compile(line, "<console>", "eval"), "eval"
        except SyntaxError:
            code, mode = compile(line, "<console>", "exec"), "exec"
        out: list[str] = []

        def apply() -> bool:                              # one console_change, as P1's
            try:
                value = interp.author_call(eval, code, interp.G)
            except BaseException as error:                # noqa: BLE001 (as guarded)
                out.append(f"{type(error).__name__}: {error}")
                return False
            out.append(value_text(value, CODE_MAX) if mode == "eval" else "Done.")
            return True

        reason = interp.console_change(apply)
        if reason:
            out.clear()
        return Outcome(tuple(out), reason is None, reason or None)

    def guarded(self, interp: Interpreter, fn) -> None:
        try:
            interp.author_call(fn)
        except BaseException:                             # noqa: BLE001
            pass

    def jump(self, label: str, new_game: bool) -> str | None:
        self.jumps.append((label, new_game))
        if not new_game and self.interp is not None:
            return self.interp.console_jump(label)
        return None


def model_for(program, runner: FakeRunner) -> ConsoleModel:
    return ConsoleModel(program, run_code=runner.run_code, jump=runner.jump,
                        guarded=runner.guarded)


def opened(program, interp: Interpreter, runner: FakeRunner | None = None, **where):
    runner = runner or FakeRunner(interp)
    model = model_for(program, runner)
    model.opened(where_now(interp, **where), interp)
    return model, runner


def row(model: ConsoleModel, name: str):
    return next(r for r in model.visible(Tab.VARIABLES) if r.name == name)


# --- AC-F40-06 — the header names the label, file and line; the title says no story --------

def test_ac06_header_shows_where_the_story_is(program):
    interp = started(program)
    advance(interp)                                         # "Two."
    model, _ = opened(program, interp)
    line = interp.current.line
    assert model.header == f"Console — start, script/main.vns line {line}"
    assert interp.current.text == "Two."

    model.opened(where_now(interp, title=True), interp)
    assert model.header == "Console — no story running"
    assert model.visible(Tab.VARIABLES) == []
    assert model.empty_text == texts.NO_STORY


# --- AC-F40-07 — defaults in order, then meters; values cut to 80; filter by name -----------

def test_ac07_variables_list_and_filter(program):
    interp = started(program)
    model, _ = opened(program, interp)
    rows = model.visible(Tab.VARIABLES)
    assert [(r.kind, r.name) for r in rows] == [
        ("group", "STORY VARIABLES"), ("variable", "mood"), ("variable", "bag"),
        ("variable", "met"), ("variable", "coins"), ("variable", "long"),
        ("group", "METERS"), ("meter", "trust"), ("meter", "luck")]
    assert row(model, "mood").text == "'calm'"
    assert len(row(model, "long").text) == ROW_MAX and row(model, "long").text.endswith("…")
    assert row(model, "trust").text == "0   (0 to 10)"          # a ranged meter
    assert row(model, "luck").text == "0"                       # unranged: no range
    assert model.selected.name == "mood"                        # never a caption

    model.insert("U")                                           # case-insensitive
    assert [r.name for r in model.visible()] == ["METERS", "trust", "luck"]
    model.backspace()
    model.insert("co")
    assert [r.name for r in model.visible()] == ["STORY VARIABLES", "coins"]
    model.insert("zz")
    assert model.visible() == [] and model.empty_text == texts.NOTHING_MATCHES.format(
        filter="cozz")


# --- AC-F40-08 — Set with each literal kind; a bad literal changes nothing ------------------

@pytest.mark.parametrize("text, value", [
    ("12", 12), ("-1.5", -1.5), ("True", True), ("None", None), ('"Hana"', "Hana"),
    ("[1, 'a']", [1, "a"]), ('{"a": [2]}', {"a": [2]})])
def test_ac08_set_each_literal_kind(program, text, value):
    interp = started(program)
    model, _ = opened(program, interp)
    model.select([r.name for r in model.visible()].index("mood"))
    assert model.enter() is None and model.editing == "mood"    # the field opens
    assert model.value.text == "'calm'"                         # prefilled as a literal
    model.value.set(text)
    action = model.enter()
    assert action == SetValue("mood", text)
    result = model.apply(action, where_now(interp), interp)
    assert result.ok and interp.G["mood"] == value and type(interp.G["mood"]) is type(value)
    assert result.text == f"mood is now {value_text(value, ROW_MAX)}."
    assert model.editing is None and interp.checkpoint().variables["mood"] == value

    before = interp.checkpoint()
    bad = model.apply(SetValue("mood", "Hana Sato"), where_now(interp), interp)
    assert not bad.ok and bad.text == texts.BAD_VALUE
    assert interp.G["mood"] == value and interp.checkpoint() is before


# --- AC-F40-09 — a meter takes a whole number, clamped -------------------------------------

def test_ac09_meter_set_is_whole_and_clamped(program):
    interp = started(program)
    model, _ = opened(program, interp)
    where = where_now(interp)
    assert model.apply(SetValue("trust", "4"), where, interp).text == "trust is now 4."
    assert interp.points.get("trust") == 4
    assert model.apply(SetValue("trust", "99"), where, interp).text == "trust is now 10."
    assert interp.points.get("trust") == 10 and interp.checkpoint().points["trust"] == 10
    for text in ("2.5", "True", '"3"'):
        result = model.apply(SetValue("trust", text), where, interp)
        assert not result.ok and result.text == "trust is a meter, so it needs a whole number."
    assert interp.points.get("trust") == 10
    assert row(model, "trust").text == "10   (0 to 10)"


# --- AC-F40-10 — Switch flips a bool; -1 / +1 change a whole number --------------------------

def test_ac10_switch_and_nudge_buttons(program):
    interp = started(program)
    model, _ = opened(program, interp)
    where = where_now(interp)
    assert row(model, "met").buttons == ("Switch",)
    assert row(model, "coins").buttons == ("-1", "+1")
    assert row(model, "trust").buttons == ("-1", "+1")
    assert row(model, "mood").buttons == ()
    assert model.press("met", "Switch") == Switch("met")
    assert model.apply(Switch("met"), where, interp).text == "met is now True."
    assert interp.G["met"] is True
    model.apply(model.press("coins", "+1"), where, interp)
    model.apply(model.press("coins", "+1"), where, interp)
    assert model.apply(Nudge("coins", -1), where, interp).text == "coins is now 4."
    assert model.apply(Nudge("trust", -1), where, interp).text == "trust is now 0."  # clamped
    assert model.apply(Nudge("trust", 1), where, interp).text == "trust is now 1."
    assert row(model, "met").text == "True" and row(model, "coins").text == "4"


# --- AC-F40-19 — a change that can't be saved is undone ---------------------------------------

def test_ac19_unsaveable_change_is_undone(program):
    interp = started(program)
    model, runner = opened(program, interp)
    before = interp.checkpoint()
    model.select_tab(Tab.CODE)
    model.insert("bag.append(lambda: 1)")
    result = model.apply(model.enter(), where_now(interp), interp)
    assert not result.ok
    assert runner.ran == ["bag.append(lambda: 1)"]
    reason_line = result.text.splitlines()[-1]
    assert reason_line.startswith("That change can't go into a save (")
    assert reason_line.endswith("), so it was undone.")
    assert interp.G["bag"] == [] and interp.checkpoint() is before
    entry = model.results[-1]
    assert entry.line == "bag.append(lambda: 1)" and not entry.ok


# --- AC-F40-20 — a replay and a minigame are looking only --------------------------------------

def test_ac20_replay_and_minigame_refuse_changes(program):
    replay = started(program, replay=ReplayRun("garden"))
    runner = FakeRunner(replay)
    model, _ = opened(program, replay, runner)
    assert model.where is Where.REPLAY
    plain = started(program)
    cases = [(replay, {}, texts.REPLAY), (plain, {"minigame_host": True}, texts.MINIGAME)]
    for interp, flags, text in cases:
        where = where_now(interp, **flags)
        model.opened(where, interp)
        assert row(model, "coins").text == "3"                  # Variables still shows values
        before = (dict(interp.G), interp.checkpoint(), interp.status)
        for action in (SetValue("coins", "9"), Switch("met"), Nudge("coins", 1),
                       JumpTo("side"), RunCode("coins = 9")):
            result = model.apply(action, where, interp)
            assert not result.ok and result.text == text, action
        assert (dict(interp.G), interp.checkpoint(), interp.status) == before
    assert runner.ran == [] and runner.jumps == []


# --- AC-F40-21 — Up/Down recall 50 lines; long input cut; long output shortened ---------------

def test_ac21_history_and_limits(program):
    interp = started(program)
    model, runner = opened(program, interp)
    model.select_tab(Tab.CODE)
    where = where_now(interp)
    for n in range(HISTORY_MAX + 5):
        model.insert(f"coins = {n}")
        model.apply(model.enter(), where, interp)
    assert len(model.history) == HISTORY_MAX
    model.insert("draft")
    model.move(-1)
    assert model.code.text == f"coins = {HISTORY_MAX + 4}"
    for _ in range(HISTORY_MAX + 3):
        model.move(-1)
    assert model.code.text == "coins = 5"                       # the oldest kept
    model.move(1)
    assert model.code.text == "coins = 6"
    for _ in range(HISTORY_MAX):
        model.move(1)
    assert model.code.text == "draft"                           # back to what was typed

    model.code.set("")
    model.insert("1 + " * 700 + "1")                            # 2,801 typed
    assert len(model.code.text) == INPUT_MAX
    action = model.enter()
    assert len(action.line) == INPUT_MAX

    noisy = FakeRunner(interp, long_output=True)
    loud = model_for(program, noisy)
    result = loud.apply(RunCode("coins"), where, interp)
    assert all(len(line) <= CODE_MAX for line in loud.results[-1].lines)
    assert len(result.text) <= CODE_MAX


# --- AC-F40-23 — one INFO per action in area console, no code text or value ------------------

def test_ac23_one_info_record_per_action(program, caplog):
    interp = started(program)
    model, _ = opened(program, interp)
    where = where_now(interp)
    actions = [SetValue("mood", f'"{NEEDLE}"'), Switch("met"), Nudge("coins", 1),
               RunCode(f"mood = '{NEEDLE}'"), SetValue("trust", "2.5"),
               JumpTo("side")]
    for action in actions:
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="vn"):
            model.apply(action, where, interp)
        records = [r for r in caplog.records if r.name == "vn.console"]
        assert len(records) == 1 and records[0].levelno == logging.INFO, action
        message = records[0].getMessage()
        assert NEEDLE not in message and "2.5" not in message
        name = getattr(action, "name", getattr(action, "label", None))
        assert name is None or name in message
        where = where_now(interp)
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="vn"):
        model.apply(SetValue(f"no_{NEEDLE}", "1"), where, interp)   # unresolved: not logged
        model.apply(JumpTo(f"no_{NEEDLE}"), where, interp)
    assert not [r for r in caplog.records if r.name == "vn.console"]
    assert all(NEEDLE not in r.getMessage() for r in caplog.records)


# --- AC-F40-27 — Studio's set value is parsed, never evaluated ---------------------------------

def test_ac27_studio_set_is_parsed_not_evaluated(program):
    interp = started(program)
    model, runner = opened(program, interp)
    where = where_now(interp)
    before = (dict(interp.G), interp.checkpoint())
    for value in ("__import__('os')", "coins + 1", "print('x')", "[1, len('a')]"):
        action = model.studio_action(ConsoleRequest("set", name="coins", value=value))
        assert action == SetValue("coins", value)
        result = model.apply(action, where, interp)
        assert not result.ok and result.text == texts.BAD_VALUE
    for name in ("__builtins__", "dice", "hana", "_x", "a b"):
        result = model.apply(SetValue(name, "1"), where, interp)
        assert result.text == texts.NOT_VARIABLE.format(name=name)
    assert (dict(interp.G), interp.checkpoint()) == before and runner.ran == []
    ok = model.apply(model.studio_action(ConsoleRequest("set", name="coins", value="7")),
                     where, interp)
    assert ok.ok and interp.G["coins"] == 7
    assert model.studio_action(ConsoleRequest("values")) is None
