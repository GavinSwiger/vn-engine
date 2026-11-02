"""F03 step 5 — interpreter seams and failure paths: the executor registry and checkpoint
types (I-7), the event table (I-7), hold/release and burst order (I-3, I-4), stale
``Advance``, author failures as one ``StoryFailed`` (PR-F03-22), launch errors, and the
first cut of ``Character`` and ``module`` refusals (step 8 completes them)."""

from dataclasses import dataclass

import pytest

from engine.runtime import interpreter as interp_mod
from engine.runtime.commands import (Advance, AudioRestore, Command, Event, Say, ShowStage,
                                     StoryFailed)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import (CHECKPOINT_TYPES, PRESENTERS, Status, register_event,
                                        register_executor)
from engine.runtime.launch import run_launch
from engine.script import nodes
from engine.script.diagnostics import ScriptErrorGroup
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from tests.runtime.story import load_r, run_r, start, texts


@dataclass(frozen=True, slots=True)
class Extra(Command):
    tag: str


@dataclass(frozen=True, slots=True)
class Poke(Event):
    pass


def test_registry_refuses_duplicates():
    with pytest.raises(ValueError):
        register_executor(nodes.Say, lambda i, s: None)
    with pytest.raises(ValueError):
        register_event(Advance, lambda i, e: None)


def test_checkpoint_types_come_from_presenters():
    # F07 (its 07 I-10, AC-F03-84 amended): Menu is a checkpoint type, through its presenter;
    # F23 (04 §17.1-1): Minigame too.
    assert set(CHECKPOINT_TYPES) == {nodes.Say, Menu, Minigame} == set(PRESENTERS)


def test_unknown_event_is_ignored(tmp_path):
    interp = start(load_r(tmp_path))
    before = interp.checkpoint()
    interp.post(Poke())
    assert interp.status is Status.WAITING and interp.checkpoint() is before


def test_event_table_dispatches(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setitem(interp_mod.EVENT_HANDLERS, Poke, lambda i, e: seen.append(e))
    interp = start(load_r(tmp_path))
    interp.post(Poke())
    assert seen == [Poke()]


def test_stale_advance_is_ignored(tmp_path):
    interp = start(load_r(tmp_path))
    first = interp.current.sid
    assert texts(interp.take_commands(10)) == ["Start."]
    interp.post(Advance("start/000000000000"))
    assert interp.status is Status.WAITING and interp.current.sid == first
    interp.post(Advance(first))
    interp.post(Advance(first))                     # a second click in the same frame
    interp.run(10_000)
    assert texts(interp.take_commands(10)) == ["End."]
    assert interp.status is Status.WAITING


def test_take_checkpoint_burst_order(tmp_path):
    interp = start(load_r(tmp_path))
    interp.take_commands(10)
    stmt = interp.current
    cmd = interp_mod.say_command(interp, stmt)
    interp.take_checkpoint(stmt, cmd, attached=(Extra("voice"),))
    assert interp.take_commands(10) == [Extra("voice"), cmd]


def test_hold_release_and_take_limit(tmp_path):
    interp = start(load_r(tmp_path))
    interp.take_commands(10)
    interp._hold(Extra("a"))
    interp._hold(Extra("b"))
    assert interp.take_commands(10) == []           # held, not yet released
    interp._release()
    assert interp.take_commands(1) == [Extra("a")]
    assert interp.take_commands(1) == [Extra("b")]


# --- Author failures: one StoryFailed, nothing partly shown ------------------------------

@pytest.mark.parametrize("S, T, code, where", [
    ("$ x = 1 / 0", None, "E85g", "script/main.vns, line 8: this divides by zero."),
    ("$ s = {1}", None, "E85e", 'script/main.vns, line 8: "s" holds a set'),
    ("$ y = luck", None, "E85b", 'script/main.vns, line 8: there is no variable named "luck"'),
    ("$ y = trsut", None, "E85b", 'line 8: there is no variable named "trsut". Did you mean "trust"?'),
    ("if 1 / 0:⏎[8]\"x\"", None, "E85g", "script/main.vns, line 8: this divides by zero."),
    ('$ hana_name = 3⏎[4]hana "Hi."', None, "E75h",
     "script/main.vns, line 9: hana's name comes from hana_name, which holds a whole number (3), "
     'not text. Set it to text, e.g. $ hana_name = "Hana".'),
    ("$ exit()", None, "E85f", "line 8: this $ line tried to close the game with exit()."),
    ("$ y = persistent.x", None, "E180", "line 8: persistent.x has no value yet"),   # F12
    ("$ input()", None, "E85n", "line 8: input() can't be used in a game"),
    ("$ hana.color = '#000000'", None, "E85c",
     "line 8: hana's options are fixed when the game starts, so the story can't change color."),
    ("$ x = [][1]", None, "E85", "line 8: this Python stopped with an error: list index out of "
                                 "range. Check the values this line uses"),
], ids=["zero", "set", "unknown", "suggest", "condition", "name-from", "exit", "persistent",
        "input", "character-locked", "other"])
def test_run_failure_is_one_story_failed(tmp_path, S, T, code, where):
    cmds = run_r(tmp_path, S=S, T=T)
    assert texts(cmds) == ["Start."]                # the failing burst shows nothing
    # F04: Start.'s stage; F08: the new game's AudioRestore first
    assert [type(c) for c in cmds] == [AudioRestore, ShowStage, Say, StoryFailed]
    assert cmds[-1].error.code == code
    assert where in cmds[-1].error.format()


def test_failed_has_no_checkpoint(tmp_path):
    interp = start(load_r(tmp_path, S="$ x = 1 / 0"))
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.status is Status.FAILED and interp.checkpoint() is None


def test_failing_default_stops_before_the_first_line(tmp_path):
    cmds = run_r(tmp_path, T="default bad = 1 / 0")
    assert len(cmds) == 1 and type(cmds[0]) is StoryFailed
    assert cmds[0].error.format() == ("script/main.vns, line 11: default bad couldn't be set: "
                                      "this divides by zero. Check the number you divide by "
                                      "first, e.g. if days > 0:.")


# --- Launch ------------------------------------------------------------------------------

@pytest.mark.parametrize("S, T, code, message", [
    ('ghost "Boo."', 'define ghost = "Ghost"', "E75",
     'script/main.vns, line 11: "ghost" speaks in the story (script/main.vns, line 8), but its '
     'define gives text, not a character. Write define ghost = Character("Ghost").'),
    (None, "define bad = 1 / 0", "E85g",
     "script/main.vns, line 11: define bad couldn't be set: this divides by zero."),
    (None, "define opening = dice.roll(1, 6)", "E85k",
     "line 11: define opening couldn't be set: it uses dice"),
    (None, "define bonus = trust + 1", "E85l",
     'line 11: define bonus couldn\'t be set: it uses "trust", which is a story variable'),
    (None, 'define c = Character("A", colour="#000000")', "E75b",
     'line 11: Character has no option "colour". Did you mean "color"? Its options are blip, '
     "blip_every, blip_pitch, blip_volume, color, image_tag, name_from, text_color, and "
     "text_italic."),
    (None, 'define c = Character("A", color="#e8a0b")', "E75c", "isn't a color"),
    (None, "define c = Character()", "E75d", "Character needs the name to show"),
    (None, "define c = Character(3)", "E75e", "but this is a whole number."),
    (None, 'define c = Character(name_from="hana_nmae")', "E75f", 'Did you mean "hana_name"?'),
    (None, "define c = Character(name_from=3)", "E75g", "name_from takes the variable's name"),
    (None, "define m = module(3)", "E89b", "define m couldn't be set: module takes the module's"),
    (None, 'define m = module("engine")', "E89c", '"engine" is the engine\'s own code'),
    (None, 'define m = module("maths")', "E89", 'no Python module named "maths". Did you mean'),
], ids=["speaker", "e85g", "dice", "story-variable", "e75b", "e75c", "e75d", "e75e", "e75f",
        "e75g", "e89b", "e89c", "e89"])
def test_launch_errors(tmp_path, S, T, code, message):
    program = load_r(tmp_path, S=S, T=T)
    result = run_launch(program)
    assert result.namespace is None and result.error_count == 1
    assert result.errors[0].code == code
    assert message in result.errors[0].format()
    cmds = run_headless(program, seed=1)
    assert len(cmds) == 1 and type(cmds[0].error) is ScriptErrorGroup


def test_launch_skips_dependants_of_a_failed_define(tmp_path):
    result = run_launch(load_r(tmp_path, T="define a = 1 / 0⏎define b = a + 1"))
    assert result.error_count == 1


def test_headless_inputs(tmp_path):
    program = load_r(tmp_path)
    assert texts(run_headless(program, seed=1, max_lines=1)) == ["Start."]
    # F07 (its 04 §5.4): choose N away from a menu is a HeadlessInputError, not ValueError.
    from engine.runtime.headless import HeadlessInputError
    with pytest.raises(HeadlessInputError, match="^choose 1 at the line at script/main.vns"):
        run_headless(program, seed=1, inputs=["choose 1"])
