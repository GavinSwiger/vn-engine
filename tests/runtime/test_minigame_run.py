"""F23 s2 — running a minigame (``06-acceptance.md`` AC-F23-04 to 09; F25 AC-F25-18).

Driver D (``tests/runtime/minigame_story.py``) and Run H on Template M with SIGS. Host U rows
(the Probe plugin, ``ctx.random``, ``ctx.args``) and AC-F23-08's host path are s4's."""

import logging
from types import MappingProxyType

import pytest

from engine.core.minigame_types import (REQUIRED, ArgSpec, CodexChange, MeterChange,
                                        MinigameSig, Outcome, StoryNames)
from engine.runtime import limits
from engine.runtime.commands import (Advance, Choose, CodexAdded, MeterView, MinigameDone,
                                     PlayVoice, PrefetchImages, Say, ShowMenu, ShowStage,
                                     StartMinigame, StoryFailed)
from engine.runtime.dice import Pcg32
from engine.runtime.errors import StoryError
from engine.runtime.interpreter import Status
from engine.runtime.minigame import story_names
from engine.runtime.points import Points
from engine.runtime.state import GameState
from engine.script.messages import format_message
from tests.fixtures.F23.sigs import SIGS
from tests.runtime.minigame_story import (ALL, LINE_M, at_a, finish, load_m, run_m, said,
                                          start_of, to_line)
from tests.runtime.story import fingerprint


def _failed(commands) -> StoryError:
    failed = [c for c in commands if type(c) is StoryFailed]
    assert len(failed) == 1, commands
    return failed[0].error


def _sigs(*extra: MinigameSig):
    return MappingProxyType({**SIGS, **{sig.name: sig for sig in extra}})


def _sig(name: str, *args: ArgSpec, check=None, outcome=None, test=None) -> MinigameSig:
    return MinigameSig(name=name, title=name, source=f"minigames/{name}.py", args=args,
                       test=test, skipped=None, check=check, outcome=outcome)


# --- AC-F23-04 — Start and wait -------------------------------------------------------------

def test_ac_f23_04_start_and_wait(tmp_path):
    program = load_m(tmp_path / "m")
    interp = at_a(program)
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    burst = interp.take_commands(ALL)
    kinds = [type(c) for c in burst]
    assert kinds.count(StartMinigame) == 1 and not {Say, PlayVoice, ShowMenu} & set(kinds)
    order = [k for k in kinds if k in (ShowStage, StartMinigame, PrefetchImages)]
    assert order == sorted(order, key=[ShowStage, StartMinigame, PrefetchImages].index)
    m = program.at("start", (1,))
    cmd = start_of(burst)
    assert (cmd.sid, cmd.run, cmd.name, cmd.skippable, cmd.restored) == (
        m.sid, 1, "probe", False, False)
    assert dict(cmd.args) == {"pairs": 6, "hints": False, "label": ""}
    assert list(cmd.args) == ["pairs", "hints", "label"]
    assert type(cmd.args) is MappingProxyType
    assert 0 <= cmd.seed < 2**64
    assert cmd.base.meters == (MeterView("hana", 0, 0, 10),)
    assert cmd.base.items == () and cmd.base.tips == ()
    assert interp.status is Status.WAITING and interp.current is m
    state = interp.checkpoint()
    assert state.position == m.sid and state.minigame.waiting.name == "probe"
    before = fingerprint(interp)                          # Advance and Choose change nothing
    interp.post(Advance(m.sid))
    interp.post(Choose(m.sid, "0123456789ab"))
    assert fingerprint(interp) == before
    after = finish(interp, 4)                             # the next burst is B's line
    assert said(after) == ["After 4."]
    assert not interp.persistent.is_seen(m.sid)           # F12: no seen mark for M
    # Placement rows (Run H, finish 4): if/elif/else branches, a choice block, a called label.
    cases = {
        "if": "if True:⏎[8]minigame probe pairs=6 into turns",
        "elif": "if False:⏎[8]$ x = 1⏎[4]elif True:⏎[8]minigame probe pairs=6 into turns",
        "else": "if False:⏎[8]$ x = 1⏎[4]else:⏎[8]minigame probe pairs=6 into turns",
        "choice": 'menu:⏎[8]"Play":⏎[12]minigame probe pairs=6 into turns',
        "call": "call game",
    }
    for name, S in cases.items():
        T = ("label game:⏎[4]minigame probe pairs=6 into turns⏎[4]return" if name == "call"
             else None)
        variant = load_m(tmp_path / name, S=S, T=T)
        inputs = ["advance", "choose 1", "finish 4"] if name == "choice" else ["advance",
                                                                                "finish 4"]
        assert said(run_m(variant, inputs))[:2] == ["Before.", "After 4."], name
    twice = load_m(tmp_path / "twice", S="minigame probe pairs=6⏎[4]minigame probe pairs=7")
    runs = [c.run for c in run_m(twice, ["advance", "finish 1", "finish 2"])
            if type(c) is StartMinigame]
    assert runs == [1, 2]


# --- AC-F23-05 — Arguments --------------------------------------------------------------------

def test_ac_f23_05_arguments(tmp_path):
    def start(S, name, **kw):
        commands = run_m(load_m(tmp_path / name, S=S, **kw), ["advance"])
        return commands

    cmd = start_of(start("minigame probe pairs=n hints=points.hana >= 3",
                         "vars", replace={2: "default turns = 0⏎default n = 4",
                                          4: "points hana 0 to 10 start 3"}))
    assert dict(cmd.args) == {"pairs": 4, "hints": True, "label": ""}
    # Written order: label's roll first, then pairs'; the seed's two draws after both.
    program = load_m(tmp_path / "order", S="minigame probe label=str(dice.roll(1, 10)) "
                                           "pairs=dice.roll(1, 10)")
    cmd = start_of(run_m(program, ["advance"]))
    core = Pcg32()
    core.seed(42)
    first, second = core.below(10) + 1, core.below(10) + 1
    assert (cmd.args["label"], cmd.args["pairs"]) == (str(first), second)
    assert cmd.seed == core.next32() << 32 | core.next32()
    cmd = start_of(start("minigame probe pairs=codex.items", "codex",
                         replace={7: "label start:⏎[4]unlock item paper_lantern"}))
    assert cmd.args["pairs"] == ["paper_lantern"]
    error = _failed(start("minigame probe pairs={1, 2}", "set"))
    assert (error.code, error.line) == ("E272", LINE_M)
    assert error.message == ("the argument pairs holds a set, which can't be saved. Use a list "
                             "instead.")
    commands = start("minigame probe pairs={1, 2}", "set2")
    assert type(commands[-1]) is StoryFailed and not any(type(c) is StartMinigame
                                                         for c in commands)
    error = _failed(start("minigame probe pairs=1/0", "zero"))
    assert (error.code, error.line) == ("E85g", LINE_M)
    error = _failed(start("minigame probe pairs=undefined_name", "name"))
    assert error.code == "E85b"
    error = _failed(start("minigame probe pairs=int('x')", "e85"))
    assert error.code == "E85" and error.message.startswith("the argument pairs stopped")
    # A list argument is frozen: the story's variable and the command never share it.
    program = load_m(tmp_path / "lst", S="minigame probe pairs=lst",
                     replace={2: "default turns = 0⏎default lst = [1]"})
    interp = at_a(program)
    cmd = start_of(to_line(interp, LINE_M + 1))
    assert cmd.args["pairs"] == [1] and cmd.args["pairs"] is not interp.G["lst"]


# --- AC-F23-06 — The plugin's argument check ----------------------------------------------------

def test_ac_f23_06_the_plugins_argument_check(tmp_path, monkeypatch):
    commands = run_m(load_m(tmp_path / "a", S="minigame lantern_memory pairs=40"), ["advance"])
    error = _failed(commands)
    assert (error.code, error.line) == ("E272", LINE_M)
    assert error.message == "lantern_memory can't use pairs=40: it takes 2 to 12 pairs."
    commands = run_m(load_m(tmp_path / "b", S="minigame lantern_memory pairs=6 into turns"),
                     ["advance", "finish 1"])
    assert start_of(commands).name == "lantern_memory"
    seen = []

    def five(args, story):
        return 5

    def boom(args, story):
        return 1 / 0

    def long(args, story):
        return "x" * 300

    def mutate(args, story):
        seen.append(args)
        args["pairs"].append(99)
        return None

    for name, check in (("five", five), ("boom", boom)):
        sigs = _sigs(_sig(name, ArgSpec("pairs", REQUIRED), check=check))
        error = _failed(run_m(load_m(tmp_path / name, S=f"minigame {name} pairs=6", sigs=sigs),
                              ["advance"], sigs=sigs))
        assert (error.code, error.line) == ("E275", LINE_M), name
    assert error.message == format_message("E275", ("raised", "boom", "minigames/boom.py",
                                                    None, "division by zero"))
    sigs = _sigs(_sig("five", ArgSpec("pairs", REQUIRED), check=five))
    error = _failed(run_m(load_m(tmp_path / "five2", S="minigame five pairs=6", sigs=sigs),
                          ["advance"], sigs=sigs))
    assert error.message == format_message("E275", ("value", "five", "check_args",
                                                    "a whole number", "minigames/five.py"))
    sigs = _sigs(_sig("long", ArgSpec("pairs", REQUIRED), check=long))
    error = _failed(run_m(load_m(tmp_path / "long", S="minigame long pairs=6", sigs=sigs),
                          ["advance"], sigs=sigs))
    assert error.message == f"long can't use pairs=6: {'x' * 200}"
    sigs = _sigs(_sig("mutate", ArgSpec("pairs", REQUIRED), check=mutate))
    program = load_m(tmp_path / "mut", S="minigame mutate pairs=[1]", sigs=sigs)
    interp = at_a(program, sigs=sigs)
    cmd = start_of(to_line(interp, LINE_M))
    assert seen[0]["pairs"] == [1, 99] and cmd.args["pairs"] == [1]   # a plain copy
    # A check that loops: the watchdog (patched to 0.1 s) stops it, E275 at the line.
    from engine.app.story import Watchdog

    def loop(args, story):
        while True:
            pass

    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.1)
    watchdog = Watchdog(tick=0.02)
    watchdog.start()
    try:
        sigs = _sigs(_sig("loop", ArgSpec("pairs", REQUIRED), check=loop))
        program = load_m(tmp_path / "loop", S="minigame loop pairs=6", sigs=sigs)
        interp = at_a(program, sigs=sigs, guard=watchdog)
        interp.post(Advance(interp.current.sid))
        interp.run(10_000)
        error = _failed(interp.take_commands(ALL))
    finally:
        watchdog.stop()
    assert (error.code, error.line) == ("E275", LINE_M)
    assert error.message == format_message("E275", ("stuck", "loop", "check_args", 0.1,
                                                    "minigames/loop.py"))


# --- AC-F23-07 — Accepting the result ------------------------------------------------------------

def test_ac_f23_07_accepting_the_result(tmp_path, monkeypatch, caplog):
    program = load_m(tmp_path / "m")
    m = program.at("start", (1,))

    def at_m():
        interp = at_a(program)
        to_line(interp, LINE_M)
        return interp

    interp = at_m()
    store = interp.persistent
    commands = finish(interp, 9, (MeterChange("hana", "+=", 2), CodexChange("give", "paper_lantern"),
                                  CodexChange("unlock_tip", "lanterns")))
    assert interp.G["turns"] == 9 and interp.points.get("hana") == 2
    assert interp.codex.items() == ("paper_lantern",)
    assert store.is_unlocked("tip", "lanterns")
    assert [type(c) for c in commands if type(c) in (CodexAdded, Say)] == [CodexAdded, CodexAdded,
                                                                          Say]
    assert [(c.kind, c.name) for c in commands if type(c) is CodexAdded] == [
        ("item", "paper_lantern"), ("tip", "lanterns")]
    assert said(commands) == ["After 9."]
    for changes, hana in (((MeterChange("hana", "=", 12),), 10),
                          ((MeterChange("hana", "+=", 2), MeterChange("hana", "=", 5),
                            MeterChange("hana", "-=", 1)), 4)):
        interp = at_m()
        finish(interp, 1, changes)
        assert interp.points.get("hana") == hana
    interp = at_m()
    finish(interp, 1, (CodexChange("give", "paper_lantern"), CodexChange("take", "paper_lantern")))
    assert interp.codex.items() == ()
    without = load_m(tmp_path / "no_into", S="minigame probe pairs=6")
    interp = at_a(without)
    to_line(interp, LINE_M)
    finish(interp, 5, (MeterChange("hana", "+=", 1),))
    assert interp.G["turns"] == 0 and interp.points.get("hana") == 1
    # Call order: every change before the variable write.
    interp = at_m()
    order = []
    real = Points.change

    def spy(self, name, op, amount):
        order.append(("change", interp.G["turns"]))
        return real(self, name, op, amount)

    monkeypatch.setattr(Points, "change", spy)
    finish(interp, 7, (MeterChange("hana", "+=", 1), MeterChange("hana", "+=", 1)))
    assert order == [("change", 0), ("change", 0)] and interp.G["turns"] == 7
    monkeypatch.undo()
    # Ignored: a repeat after acceptance, a stale run, another sid, posted at A.
    caplog.set_level(logging.DEBUG, logger="vn.plugin")
    interp = at_m()
    interp.post(MinigameDone(m.sid, interp.minigame_run, 9, ()))
    before = fingerprint(interp)
    interp.post(MinigameDone(m.sid, interp.minigame_run, 9, ()))      # accepted already
    assert fingerprint(interp) == before
    interp = at_m()
    for event in (MinigameDone(m.sid, 0, 9, ()), MinigameDone("start/000000000000",
                                                             interp.minigame_run, 9, ())):
        before = fingerprint(interp)
        caplog.clear()
        interp.post(event)
        assert fingerprint(interp) == before
        assert [r.levelno for r in caplog.records if r.name == "vn.plugin"] == [logging.DEBUG]
    interp = at_a(program)
    before = fingerprint(interp)
    interp.post(MinigameDone(m.sid, 1, 9, ()))                      # posted at A
    assert fingerprint(interp) == before
    # A stale test outcome naming meter "hanna": post returns, the next run() fails (E236).
    interp = at_m()
    interp.post(MinigameDone(m.sid, interp.minigame_run, 9, (MeterChange("hanna", "+=", 1),)))
    assert interp.status is Status.RUNNING
    interp.run(10_000)
    error = _failed(interp.take_commands(ALL))
    assert (error.code, error.line) == ("E236", LINE_M)
    assert error.message == format_message("E236", ("unknown", "hanna", "hana"))
    interp = at_m()
    error = _failed(finish(interp, 9, (CodexChange("give", "paper_lanten"),)))
    assert (error.code, error.message) == ("E253", format_message("E253", (
        "unknown", "item", "paper_lanten", "paper_lantern")))

    class Name(str):
        pass

    for change in (MeterChange("hana", "+=", True), MeterChange("hana", "+=", 1.5),
                   MeterChange("hana", "+=", 10**10), MeterChange(Name("hana"), "+=", 1)):
        interp = at_m()
        error = _failed(finish(interp, 9, (change,)))
        assert (error.code, error.line) == ("E276", LINE_M), change
        assert interp.points.get("hana") == 0
    assert error.message == format_message("E276", ("change", "probe", "name", "", "",
                                                     "minigames/probe.py"))


# --- AC-F23-08 — Results that can be saved (Driver D: the defensive path) -----------------------

def test_ac_f23_08_results_that_can_be_saved(tmp_path):
    program = load_m(tmp_path / "m")
    without = load_m(tmp_path / "w", S="minigame probe pairs=6")

    def at_m(prog=program):
        interp = at_a(prog)
        to_line(interp, LINE_M)
        return interp

    for value in ("text", 0, -1.5, True, None, [1, [2]], {"a": {"b": [None]}}):
        interp = at_m()
        finish(interp, value)
        got = interp.G["turns"]
        assert got == value and type(got) is type(value), value
    deep: list = []
    for _ in range(101):
        deep = [deep]
    rows = [({1, 2}, "kind", "a set"), ((1, 2), "kind", "a tuple"), ({1: "a"}, "key", ""),
            (float("nan"), "nan", ""), (object(), "kind", "an object"), (deep, "too_deep", "")]
    for value, reason, kind in rows:
        interp = at_m()
        error = _failed(finish(interp, value, (MeterChange("hana", "+=", 3),
                                               CodexChange("give", "paper_lantern"))))
        assert (error.code, error.line) == ("E276", LINE_M), value
        assert interp.points.get("hana") == 0 and interp.codex.items() == ()   # nothing applies
        if reason != "kind" or kind == "a set":
            assert error.message == format_message("E276", ("result", "probe", reason, kind,
                                                            "turns", "minigames/probe.py"))
    assert _failed(finish(at_m(), {1, 2})).message == (
        "probe finished with a set, which can't be saved, so it can't go into turns. A result "
        "can be text, a number, True, False, None, a list, or a dictionary with text keys. "
        "Fix minigames/probe.py.")
    assert _failed(finish(at_m(without), {1, 2})).message == (
        "probe finished with a set, which can't be saved. A result can be text, a number, "
        "True, False, None, a list, or a dictionary with text keys. Fix minigames/probe.py.")


# --- AC-F23-09 — Random replays --------------------------------------------------------------------

def test_ac_f23_09_random_replays(tmp_path, monkeypatch):
    program = load_m(tmp_path / "m")
    interp = at_a(program)
    outputs = []
    real = Pcg32.next32

    def spy(self):
        value = real(self)
        outputs.append(value)
        return value

    monkeypatch.setattr(Pcg32, "next32", spy)
    cmd = start_of(to_line(interp, LINE_M))
    monkeypatch.undo()
    assert len(outputs) == 2 and cmd.seed == outputs[0] << 32 | outputs[1]

    def roll(inputs):
        return [t for t in said(run_m(program, inputs)) if t.startswith("Roll ")]

    first = roll(["advance", "finish 1"])
    assert first == roll(["advance", "finish 99; points hana += 1"]) == roll(["advance"])
    assert len(first) == 1
    # The restored StartMinigame after a save/load at M, and after a back landing, has the seed.
    saved = interp.checkpoint().to_json()
    fresh = at_a(program)
    assert fresh.restore(GameState.from_json(saved)).result.value == "ok"
    restored = start_of(fresh.take_commands(ALL))
    assert restored.restored and restored.seed == cmd.seed
    later = at_a(program)
    to_line(later, LINE_M)
    finish(later, 1)
    from engine.runtime.commands import StepBack
    later.post(StepBack(1))
    landed = start_of(later.take_commands(ALL))
    assert landed.restored and landed.seed == cmd.seed


# --- AC-F25-18 — A5: item categories (and F24 A2's names object) ----------------------------------

def test_ac_f25_18_item_categories(tmp_path):
    program = load_m(tmp_path / "m", replace={5: 'lock item paper_lantern "Paper Lantern"⏎'
                                                 'lock item photo "Photo" in "Evidence"⏎'
                                                 'lock item coin "Old Coin"⏎'
                                                 'lock item badge "Badge" in "Evidence"'})
    interp = at_a(program)
    names = story_names(interp)
    assert names == StoryNames(meters=("hana",), items=("paper_lantern", "photo", "coin",
                                                        "badge"), tips=("lanterns",),
                               item_categories=(("codex_items", ("paper_lantern", "coin")),
                                                ("Evidence", ("photo", "badge"))))
    assert story_names(interp) is names                     # built once per interpreter
    first = load_m(tmp_path / "e", replace={5: 'lock item photo "Photo" in "Evidence"⏎'
                                               'lock item paper_lantern "Paper Lantern"'})
    assert [k for k, _ in story_names(at_a(first)).item_categories] == ["Evidence",
                                                                        "codex_items"]
    assert StoryNames((), (), ()).item_categories == ()
    cmd = start_of(to_line(interp, LINE_M + 3))           # three lines added above
    assert cmd.names is names
    saved = GameState.from_json(interp.checkpoint().to_json())
    interp.restore(saved)
    assert start_of(interp.take_commands(ALL)).names is names

