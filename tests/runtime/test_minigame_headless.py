"""F23 s2 — headless minigames (``06-acceptance.md`` AC-F23-11, 12, 54) and F24's A2
(AC-F24-17: names, E272's shapes, the headless hook). Run H on Template M with SIGS
(``tests/runtime/minigame_story.py``); no plugin is loaded, so no plugin is ever started,
updated, or drawn here (the Probe's call-spy row is s4's)."""

import builtins
import logging
import sys
import tokenize
from types import MappingProxyType

import pytest

from engine.core.minigame_types import (REQUIRED, ArgSpec, CodexChange, MeterChange,
                                        MinigameSig, Outcome, StoryNames)
from engine.runtime import headless
from engine.runtime import minigame as minigame_mod
from engine.runtime.commands import Say, StartMinigame, StoryFailed
from engine.runtime.errors import StoryError
from engine.runtime.headless import HeadlessInputError, parse_finish
from engine.runtime.state import GameState
from engine.script.messages import format_message
from tests.fixtures.F23.sigs import SIGS
from tests.runtime.minigame_story import (ALL, LINE_M, at_a, load_m, run_m, said, start_of,
                                          to_line)


def _error(program, inputs, **kw) -> HeadlessInputError:
    with pytest.raises(HeadlessInputError) as caught:
        run_m(program, inputs, **kw)
    return caught.value


def _turns(commands) -> list[str]:
    return [t for t in said(commands) if t.startswith("After ")]


# --- AC-F23-11 — Headless inputs at a minigame ---------------------------------------------------

def test_ac_f23_11_headless_inputs_at_a_minigame(tmp_path):
    program = load_m(tmp_path / "m")
    assert _turns(run_m(program, ["advance", "finish 4", "advance"])) == ["After 4."]
    commands = run_m(program, ["advance", "advance"])          # the test outcome: 9, hana += 1
    assert _turns(commands) == ["After 9."]
    error = _error(program, ["advance", "advance", "choose 1"])   # advance used at B, not M
    assert str(error) == format_message("H-choose-line", (1, "script/main.vns", 12))
    bare = load_m(tmp_path / "bare", S="minigame bare into turns")
    error = _error(bare, ["advance"])
    assert error.code == "E279"
    assert str(error) == ("script/main.vns, line 9: "
                          + format_message("E279", ("bare",)))
    assert type(error.commands[-1]) is StartMinigame
    starts = [c for c in run_m(program, ["advance", "back", "advance", "finish 1"])
              if type(c) is StartMinigame]
    assert [c.run for c in starts] == [1, 2] and starts[0].seed == starts[1].seed
    assert said(run_m(program, ["advance", "back"]))[1] == "Before."    # lands on A
    assert _turns(run_m(program, ["advance", "forward 2", "finish 3"])) == ["After 3."]
    error = _error(program, ["advance", "choose 1"])              # test outcome at M
    assert str(error) == format_message("H-choose-line", (1, "script/main.vns", 10))
    error = _error(program, ["finish 3"])
    assert str(error) == "finish 3 at the line at script/main.vns, line 8, but there is no " \
                         "minigame there."
    menu = load_m(tmp_path / "menu", S='menu:⏎[8]"Go":⏎[12]$ x = 1')
    error = _error(menu, ["advance", "finish 3"])
    assert str(error) == format_message("H-finish", ("elsewhere", 2, "finish 3", "menu",
                                                     "script/main.vns", 9))
    comment = load_m(tmp_path / "comment", S="# -")
    sids = [[c.sid for c in run_m(p, ["advance"] * 3) if type(c) is Say][1:]
            for p in (program, comment)]
    assert sids[0] == sids[1]                                   # a minigame shifts no input


# --- AC-F23-12 — The finish input, and group I ------------------------------------------------------

def test_ac_f23_12_the_finish_input(tmp_path, monkeypatch, caplog):
    program = load_m(tmp_path / "m")
    interp = at_a(program)
    to_line(interp, LINE_M)
    imported = []
    real_import = builtins.__import__

    def spy(name, *args, **kwargs):
        imported.append(name)
        return real_import(name, *args, **kwargs)

    def parse(text: str):
        monkeypatch.setattr(builtins, "__import__", spy)
        try:
            return parse_finish(interp, text, 4, [])
        finally:
            monkeypatch.setattr(builtins, "__import__", real_import)

    def fails(text: str) -> str:
        with pytest.raises(HeadlessInputError) as caught:
            parse(text)
        return str(caught.value)

    def form(name, text, *args):
        return format_message("H-finish", (name, 4, text, *args))

    caplog.set_level(logging.DEBUG)
    assert parse("finish 9") == Outcome(9, ())
    for text, value in (('finish "red"', "red"), ("finish 'red'", "red"), ("finish True", True),
                        ("finish None", None), ("finish -2.5", -2.5),
                        ('finish ["hana", "daichi"]', ["hana", "daichi"]),
                        ('finish {"a": [1]}', {"a": [1]}), ('finish "a;b"', "a;b")):
        got = parse(text).result
        assert got == value and type(got) is type(value), text
    assert parse("finish 9; points hana += 1").changes == (MeterChange("hana", "+=", 1),)
    assert parse("finish 9;points hana -= 2; points hana = 5").changes == (
        MeterChange("hana", "-=", 2), MeterChange("hana", "=", 5))
    assert [parse(f'finish "k"; {c}').changes for c in (
        "unlock item paper_lantern", "lock item paper_lantern", "unlock tip lanterns")] == [
        (CodexChange("give", "paper_lantern"),), (CodexChange("take", "paper_lantern"),),
        (CodexChange("unlock_tip", "lanterns"),)]
    assert fails("finish") == form("needs", "finish")
    assert str(_error(program, ["advance", "finsh 3"])) == format_message("H-input",
                                                                          (2, "finsh 3"))
    for text in ("finish red", "finish (1, 2)", "finish {1, 2}", 'finish b"x"', "finish x + 1",
                 "finish __import__('os')", "finish f(x)", 'finish "abc'):
        assert fails(text) == form("value", text), text
    assert "os" not in imported                                 # nothing evaluated
    for change in ("give lantern", "points hana += ١٢٣", "points hana += 1_000",
                   "points hana += +1", "points hana += 12345678901", "points ｈａｎａ += 1",
                   "points hana\n += 1", "unlock tip hana\n"):
        text = f"finish 3; {change}"
        assert fails(text) == form("change", text), change
    assert fails("finish 3; points hanna += 1") == form(
        "name", "finish 3; points hanna += 1", format_message("E236", ("unknown", "hanna",
                                                                         "hana")))
    assert fails("finish 3; unlock item paper_lanten") == form(
        "name", "finish 3; unlock item paper_lanten", format_message(
            "E253", ("unknown", "item", "paper_lanten", "paper_lantern")))
    head = 'finish "'
    assert parse(head + "x" * (10_000 - len(head) - 1) + '"').result.startswith("x")
    long = head + "x" * (10_001 - len(head) - 1) + '"'
    assert fails(long) == form("long", long)
    hundred = "finish 1" + "; points hana += 1" * 100
    assert len(parse(hundred).changes) == 100
    assert fails(hundred + "; points hana += 1") == form("many",
                                                         hundred + "; points hana += 1")
    assert parse("finish 1; points hana += 1000000000").changes[0].amount == 10**9
    assert fails("finish 1; points hana += 1000000001") == form(
        "change", "finish 1; points hana += 1000000001")
    deep = "finish " + "[" * 5_000
    assert fails(deep) == form("value", deep)
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        digits = "finish 1" + "0" * 4_400
        assert fails(digits) == form("value", digits)
    finally:
        sys.set_int_max_str_digits(old)
    assert not any(r.exc_info or "Traceback" in r.getMessage() for r in caplog.records)
    # End to end (Run H): the changes apply, then the result, as in the window.
    commands = run_m(program, ["advance", "finish 7; unlock item paper_lantern"])
    assert _turns(commands) == ["After 7."]


# --- AC-F23-54 — Group I: finish parsing is total -----------------------------------------------------

def test_ac_f23_54_finish_parsing_is_total(tmp_path, monkeypatch):
    program = load_m(tmp_path / "m")
    interp = at_a(program)
    to_line(interp, LINE_M)
    errors = (tokenize.TokenError("x"), SyntaxError("x"), RecursionError(), MemoryError(),
              ValueError("x"), OverflowError("x"))
    for where in ("tokenize", "parse_literal", "freeze"):
        for error in errors:
            def boom(*args, _e=error, **kwargs):
                raise _e

            with monkeypatch.context() as patch:
                if where == "tokenize":
                    patch.setattr(headless.tokenize, "generate_tokens", boom)
                else:
                    patch.setattr(headless, where, boom)
                with pytest.raises(HeadlessInputError) as caught:
                    parse_finish(interp, "finish [1]; points hana += 1", 2, [])
            assert str(caught.value) == format_message("H-finish", (
                "value", 2, "finish [1]; points hana += 1")), (where, error)
    assert interp.checkpoint().variables["turns"] == 0         # no input reached a state


# --- AC-F24-17 — A2: names, E272's shapes, and the headless hook -------------------------------------

def _sig(name, *args, check=None, outcome=None, test=None) -> MinigameSig:
    return MinigameSig(name=name, title=name, source=f"minigames/{name}.py", args=args,
                       test=test, skipped=None, check=check, outcome=outcome)


class _Guard:
    def __init__(self, fired: bool = False) -> None:
        self.entries = 0
        self.fired = fired

    def enter(self) -> None:
        self.entries += 1

    def exit(self) -> None:
        pass

    def consume_fired(self) -> bool:
        return self.fired


def test_ac_f24_17_names_e272_shapes_and_the_headless_hook(tmp_path):
    coin = {6: 'lock tip lanterns "Paper Lanterns"⏎lock item coin "Old Coin"'}
    program = load_m(tmp_path / "m", replace=coin)
    interp = at_a(program)
    names = minigame_mod.story_names(interp)
    assert (names.meters, names.items, names.tips) == (("hana",), ("paper_lantern", "coin"),
                                                       ("lanterns",))
    first = start_of(to_line(interp, LINE_M + 1))
    interp.restore(GameState.from_json(interp.checkpoint().to_json()))
    assert first.names == start_of(interp.take_commands(ALL)).names == names

    def failed(S, sigs=SIGS, inputs=("advance",)):
        commands = run_m(load_m(tmp_path / str(abs(hash(S))), S=S, sigs=sigs), list(inputs),
                         sigs=sigs)
        error = commands[-1].error
        assert type(commands[-1]) is StoryFailed and error.line == LINE_M, commands[-1]
        return error

    assert failed("minigame lantern_memory pairs=6 * 7").message == (
        "lantern_memory can't use pairs=6 * 7: it takes 2 to 12 pairs.")
    assert failed("minigame lantern_memory pairs=40 hints=True").message == (
        "lantern_memory can't use these arguments: it takes 2 to 12 pairs.")
    quiet = _sig("quiet", ArgSpec("level", 1), check=lambda args, story: "not today.")
    sigs = MappingProxyType({**SIGS, "quiet": quiet})
    assert failed("minigame quiet", sigs).message == "quiet can't use these arguments: not today."
    # Guard spy: one entry per line check and per restore attempt.
    calls = []
    counted = _sig("counted", ArgSpec("pairs", REQUIRED),
                   check=lambda args, story: calls.append(1))
    sigs = MappingProxyType({**SIGS, "counted": counted})
    counted_program = load_m(tmp_path / "counted", S="minigame counted pairs=6", sigs=sigs)
    guard = _Guard()
    live = at_a(counted_program, sigs=sigs, guard=guard)
    entries = guard.entries
    to_line(live, LINE_M)
    assert guard.entries - entries == 2 and len(calls) == 1   # the argument's value, the check
    state = GameState.from_json(live.checkpoint().to_json())
    entries = guard.entries
    live.restore(state)
    assert guard.entries - entries == 1 and len(calls) == 2
    # oracle: the hook first (no finish input), then the static test outcome, then E279.
    for hook, test, expected in ((lambda k, a, s: Outcome(5), None, "After 5."),
                                 (lambda k, a, s: None, Outcome(9), "After 9.")):
        oracle = _sig("oracle", outcome=hook, test=test)
        sigs = MappingProxyType({**SIGS, "oracle": oracle})
        commands = run_m(load_m(tmp_path / f"o{expected[6]}", S="minigame oracle into turns",
                                sigs=sigs), ["advance"], sigs=sigs)
        assert _turns(commands) == [expected]
    oracle = _sig("oracle", outcome=lambda k, a, s: None)
    sigs = MappingProxyType({**SIGS, "oracle": oracle})
    error = _error(load_m(tmp_path / "o0", S="minigame oracle into turns", sigs=sigs),
                   ["advance"], sigs=sigs)
    assert error.code == "E279"

    def raises(k, a, s):
        raise ZeroDivisionError("x")

    def stuck(k, a, s):
        raise KeyboardInterrupt

    for row, (hook, fired) in enumerate(((raises, False), (stuck, True),
                                         (lambda k, a, s: Outcome({1, 2}), False))):
        oracle = _sig("oracle", outcome=hook)
        sigs = MappingProxyType({**SIGS, "oracle": oracle})
        prog = load_m(tmp_path / f"h{row}", S="minigame oracle into turns",
                      sigs=sigs)
        at_m = at_a(prog, sigs=sigs, guard=_Guard(fired))
        to_line(at_m, LINE_M)
        with pytest.raises(StoryError) as caught:
            minigame_mod.headless_outcome(at_m, at_m.current)
        assert (caught.value.code, caught.value.line) == ("E275", LINE_M), hook
    commands = run_m(prog, ["advance"], sigs=sigs)
    assert type(commands[-1]) is StoryFailed and commands[-1].error.code == "E275"
    assert isinstance(StoryNames((), (), ()), StoryNames)
