"""F03 step 5 — the headless story: AC-F03-01, 03, 04, 06, 14, 15, 22, 54, 68 (06-acceptance
§1.1–1.3, §1.9, §1.10), plus F44 C1's TR-F44-07 (start options). F03 step 13: the
SR-F03-28 log lines, AC-F03-05 and AC-F03-74 (headless; the window's are in
``tests/app/test_story_driver.py``)."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine.core.startvalues import StartOptions
from engine.runtime.audio import EMPTY_AUDIO
from engine.runtime.commands import AudioRestore, ShowStage
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Status
from engine.runtime.stage import EMPTY_STAGE
from engine.script.words import ENGINE_NAMES
from tests.runtime.story import (Say, StoryEnded, advance, checkpoints, lines, load_files,
                                 load_fixture, load_r, run_r, start, texts)

ROOT = Path(__file__).resolve().parents[2]
SEED_42_DICE = "977afd8015414a94"


# --- AC-F03-01 — a new game starts at start with a fresh state -------------------------

def test_ac_f03_01_new_game(tmp_path):
    program = load_r(tmp_path)
    interp = start(program)
    state = interp.checkpoint()
    assert state.position == program.at("start", (0,)).sid           # line 7
    assert dict(state.variables) == {"trust": 0, "hana_name": "???"}
    assert state.call_stack == ()
    assert state.to_json()["dice"] == SEED_42_DICE
    assert "voice" not in state.to_json()                             # I-1, I-2
    for name in ("hana", "daichi", "fortunes", *ENGINE_NAMES, "__builtins__"):
        assert name not in state.variables


def test_ac_f03_01_commands(tmp_path):
    cmds = run_r(tmp_path)
    assert lines(cmds) == [("???", "Start."), (None, "End.")]
    assert len(cmds) == 5 and cmds[-1] == StoryEnded()
    assert cmds[0] == AudioRestore(EMPTY_AUDIO, "new_game")   # F08: before any other command
    assert cmds[1] == ShowStage(EMPTY_STAGE)            # F04: the first line's stage


# --- AC-F03-03 — jump, call, return, and the end of a label ----------------------------

def test_ac_f03_03_flow(tmp_path):
    cmds = run_headless(load_fixture(tmp_path, "flow"), seed=42)
    assert texts(cmds) == ["1", "2", "3", "4", "5", "6", "7"]
    assert cmds[-1] == StoryEnded() and len(cmds) == 10  # F04: + the first ShowStage; F08: + AudioRestore


@pytest.mark.parametrize("story, expected", [
    ('label start:\n    "1"\n    return\n    "never"\n', ["1"]),
    ("label start:\n    return\n", []),
], ids=["return-mid-label", "return-only"])
def test_ac_f03_03_return(tmp_path, story, expected):
    cmds = run_headless(load_files(tmp_path, {"main.vns": story}), seed=1)
    assert texts(cmds) == expected
    stage = [ShowStage(EMPTY_STAGE)] if expected else []   # F04: with the first line
    stage = [AudioRestore(EMPTY_AUDIO, "new_game"), *stage]  # F08: first of a new game
    assert cmds[-1] == StoryEnded() and len(cmds) == len(stage) + len(expected) + 1
    assert cmds[:len(stage)] == stage


# --- AC-F03-05 — the log line at the end of a label that wasn't called -----------------

def runtime_info(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == "vn.runtime" and r.levelno == logging.INFO]


def uncalled(caplog) -> list[str]:
    return [m for m in runtime_info(caplog) if "which wasn't called" in m]


def test_ac_f03_05_flow_in_a_dev_run(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="vn.runtime")
    cmds = run_headless(load_fixture(tmp_path, "flow"), seed=42, dev=True)
    assert cmds[-1] == StoryEnded()
    # The ends of a2 (jumped to inside a call) and of called c return: no record for them.
    assert uncalled(caplog) == [
        'script/main.vns, line 14: the story ended at the end of label "b", which '
        "wasn't called."]


def test_ac_f03_05_flow_in_a_release_run(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    run_headless(load_fixture(tmp_path, "flow"), seed=42, dev=False)
    assert not [r for r in caplog.records if "wasn't called" in r.getMessage()]


@pytest.mark.parametrize("story", ['label start:\n    "1"\n    return\n    "never"\n',
                                   "label start:\n    return\n"],
                         ids=["return-mid-label", "return-only"])
def test_ac_f03_05_return_logs_nothing(tmp_path, caplog, story):
    caplog.set_level(logging.DEBUG)
    run_headless(load_files(tmp_path, {"main.vns": story}), seed=1, dev=True)
    assert not [r for r in caplog.records if "wasn't called" in r.getMessage()]


@pytest.mark.parametrize("x, shown, line", [("1", "b", 5), ("0", "c", 7)],
                         ids=["if-branch", "else-branch"])
def test_ac_f03_05_the_line_is_the_last_statement_run(tmp_path, caplog, x, shown, line):
    """The last statement of ``start`` is an ``if`` (whose own ``end_line`` is its header's,
    4): the record names the ``end_line`` of the last statement run in the branch taken."""
    caplog.set_level(logging.INFO, logger="vn.runtime")
    story = (f'label start:\n    "a"\n    $ x = {x}\n    if x:\n        "b"\n    else:\n'
             '        "c"\n')
    program = load_files(tmp_path, {"main.vns": story})
    assert texts(run_headless(program, seed=1, dev=True)) == ["a", shown]
    assert uncalled(caplog) == [
        f'script/main.vns, line {line}: the story ended at the end of label "start", which '
        "wasn't called."]


def test_ac_f03_05_a_multi_line_statement_names_its_last_line(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="vn.runtime")
    story = 'label start:\n    "a"\n    $ x = (1,\n         2)\n'
    run_headless(load_files(tmp_path, {"main.vns": story}), seed=1, dev=True)
    assert uncalled(caplog) == [
        'script/main.vns, line 4: the story ended at the end of label "start", which '
        "wasn't called."]


# --- AC-F03-74 — the new-game log line ---------------------------------------------------

def test_ac_f03_74_dev_run_logs_the_seed(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="vn.runtime")
    run_headless(load_r(tmp_path), seed=3141592653, dev=True)
    assert [m for m in runtime_info(caplog) if m.startswith("New game")] == [
        "New game: seed 3141592653, 2 defaults."]


def test_ac_f03_74_release_run_logs_no_seed(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    run_headless(load_r(tmp_path), seed=3141592653, dev=False)
    assert [m for m in runtime_info(caplog) if m.startswith("New game")] == [
        "New game: 2 defaults."]
    assert not [r for r in caplog.records if "3141592653" in r.getMessage()]


def test_ac_f03_74_each_new_game_logs_one_line(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="vn.runtime")
    interp = start(load_r(tmp_path), seed=7, dev=True)
    interp.new_game(8)
    assert [r.levelno for r in caplog.records if r.getMessage().startswith("New game")] == [
        logging.INFO, logging.INFO]
    assert [m for m in runtime_info(caplog) if m.startswith("New game")] == [
        "New game: seed 7, 2 defaults.", "New game: seed 8, 2 defaults."]


def test_ac_f03_74_a_failing_default_logs_its_error_not_the_line(tmp_path, caplog):
    """§7.5: the line is logged at step 4, once every default is set."""
    caplog.set_level(logging.INFO, logger="vn.runtime")
    interp = start(load_r(tmp_path, T="default boom = 1 / 0"), dev=True)
    assert interp.status is Status.FAILED
    assert not [m for m in runtime_info(caplog) if m.startswith("New game")]


@pytest.mark.parametrize("options, tail", [
    (StartOptions(label="hana_route"), ', starting at "hana_route", 0 start values.'),
    (StartOptions(values=(("trust", 3),)), ', starting at "start", 1 start value.'),
], ids=["label", "values"])
def test_f44_c1_the_new_game_line_names_the_start_options(tmp_path, caplog, options, tail):
    """F44 C1 (step 13): with start options the line adds ``, starting at "<label>", <n>
    start values`` (the label is ``start`` when only ``--set`` is used)."""
    caplog.set_level(logging.INFO, logger="vn.runtime")
    program = load_r(tmp_path, T='label hana_route:⏎[4]"Hana route."')
    run_headless(program, seed=5, dev=True, start=options)
    assert [m for m in runtime_info(caplog) if m.startswith("New game")] == [
        "New game: seed 5, 2 defaults" + tail]


@pytest.mark.parametrize("defaults, text", [
    ("", "0 defaults"), ("default a = 1⏎", "1 default"), ("default a = 1⏎default b = 2⏎",
                                                          "2 defaults")])
def test_the_new_game_line_counts_in_english(tmp_path, caplog, defaults, text):
    """F03 step 14: ``1 default`` (and ``1 start value``), not ``1 defaults``."""
    caplog.set_level(logging.INFO, logger="vn.runtime")
    source = (defaults + 'label start:⏎    "A."⏎').replace("⏎", "\n")
    run_headless(load_files(tmp_path, {"main.vns": source}), seed=5)
    assert [m for m in runtime_info(caplog) if m.startswith("New game")] == [
        f"New game: {text}."]


# --- AC-F03-04 — if, elif, else --------------------------------------------------------

IF_CHAIN = '$ v = {x}⏎[4]if v == 1:⏎[8]"A"⏎[4]elif v:⏎[8]"B"⏎[4]else:⏎[8]"C"⏎[4]"after"'


@pytest.mark.parametrize("x, branch", [
    ("1", "A"), ("True", "A"), ("2", "B"), ('"0"', "B"), ("[0]", "B"),
    ("0", "C"), ('""', "C"), ("[]", "C"), ("None", "C"),
])
def test_ac_f03_04_branches(tmp_path, x, branch):
    cmds = run_r(tmp_path, S=IF_CHAIN.format(x=x))
    assert texts(cmds) == ["Start.", branch, "after", "End."]


def test_ac_f03_04_conditions_stop_at_first_true(tmp_path):
    program = load_r(tmp_path, S='if t(1):⏎[8]"A"⏎[4]elif t(2):⏎[8]"B"⏎[4]elif t(3):⏎[8]"C"',
                     T="define seen = []⏎define t = lambda n: seen.append(n) or n == 2")
    interp = start(program)
    seen = [cp.position for cp in checkpoints(interp)]
    assert [program.get(sid).text for sid in seen] == ["Start.", "B", "End."]
    assert interp.G["seen"] == [1, 2]


def test_ac_f03_04_nested(tmp_path):
    cmds = run_r(tmp_path, S='if True:⏎[8]if False:⏎[12]"x"⏎[8]"inner"⏎[4]"outer"')
    assert texts(cmds) == ["Start.", "inner", "outer", "End."]


# --- AC-F03-06 — what each line carries ------------------------------------------------

def test_ac_f03_06_say_fields(tmp_path):
    cmds = run_r(tmp_path, S='daichi happy wave "Yo {b}there{/b}."⏎[4]"日本語 😀 مرحبا"⏎[4]nobody "Hm."',
                 T='define nobody = Character("")')
    says = [c for c in cmds if type(c) is Say]
    got = [(c.speaker, c.name, c.name_color, c.attributes, c.text) for c in says[:4]]
    assert got == [
        ("hana", "???", "#e8a0b4", (), "Start."),
        ("daichi", "Daichi", "#8fb3d9", ("happy", "wave"), "Yo {b}there{/b}."),
        (None, None, None, (), "日本語 😀 مرحبا"),
        ("nobody", "", None, (), "Hm."),
    ]
    for c in says:
        assert c.voice is None and c.restored is False
        assert c.speaker_tag == c.speaker               # F04 I-3: the define name (no image_tag)


# --- AC-F03-14 — story variables are global --------------------------------------------

def test_ac_f03_14_vars(tmp_path):
    interp = start(load_fixture(tmp_path, "vars"))
    states = checkpoints(interp)
    assert interp.status is Status.ENDED
    shown = [interp.program.get(s.position).text for s in states]
    assert shown == ["Go.", "W.", "Yes."]
    final = states[-1].variables
    for name, value in {"met": True, "total": 3, "k": 2, "seen": 5, "round": 1, "x": 1}.items():
        assert final[name] == value and type(final[name]) is type(value)


# --- AC-F03-15 — defaults at a new game ------------------------------------------------

DEFAULTS_T = ("default b = a + 1⏎default a = 1⏎define base = [1, 2]⏎default inv = base⏎"
              "default rate = len(fortunes)")


def test_ac_f03_15_defaults(tmp_path):
    program = load_r(tmp_path, S="$ inv.append(3)", T=DEFAULTS_T)
    interp = start(program)
    first = interp.checkpoint()
    assert list(first.variables.items()) == [
        ("trust", 0), ("hana_name", "???"), ("a", 1), ("b", 2), ("inv", [1, 2]), ("rate", 3)]
    checkpoints(interp)
    assert interp.G["base"] == [1, 2] and interp.G["inv"] == [1, 2, 3]
    interp.new_game(42)
    interp.run(10_000)
    assert interp.checkpoint().variables["inv"] == [1, 2]


def test_ac_f03_15_default_uses_dice(tmp_path):
    program = load_r(tmp_path, T="default roll1 = dice.roll(1, 6)")
    rolls = [start(program, seed).checkpoint().variables["roll1"] for seed in (42, 42, 7, 8)]
    assert all(1 <= r <= 6 for r in rolls)
    assert rolls[0] == rolls[1]


# --- AC-F03-22 — the story namespace ---------------------------------------------------

def test_ac_f03_22_names(tmp_path):
    interp = start(load_r(tmp_path, S="$ names = sorted(globals())"))
    advance(interp)
    assert interp.checkpoint().variables["names"] == [
        "Character", "Dissolve", "Fade", "Mask", "__builtins__", "codex",   # F09, F21
        "daichi", "dice", "fortunes", "hana", "hana_name", "items", "module", "persistent",
        "points", "trust"]                                                  # F22, F64


@pytest.mark.parametrize("S, T, name, expected", [
    ('$ same = globals()["__builtins__"] is __import__("builtins").__dict__', None, "same", False),
    ("$ x = [len([1, 2]), abs(-2), math.floor(2.5), sorted(fortunes)[0], dice.roll(1, 1)]",
     'define math = module("math")', "x", [2, 2, 2, "bad luck", 1]),
], ids=["builtins-copy", "builtins-and-module"])
def test_ac_f03_22_values(tmp_path, S, T, name, expected):
    interp = start(load_r(tmp_path, S=S, T=T))
    advance(interp)
    assert interp.status is Status.WAITING
    assert interp.checkpoint().variables[name] == expected


def test_ac_f03_22_private_names_not_saved(tmp_path):
    interp = start(load_r(tmp_path, S='$ globals()["_x"] = 1'))
    advance(interp)
    assert "_x" in interp.G and "_x" not in interp.checkpoint().variables


# --- AC-F03-54 — the state's JSON shape ------------------------------------------------

def test_ac_f03_54_json(tmp_path):
    program = load_r(tmp_path)
    data = start(program).checkpoint().to_json()
    assert data == {
        "format": 1, "identity_scheme": 1,
        "position": {"sid": program.at("start", (0,)).sid, "at": ["start", [0]]},
        "call_stack": [], "variables": {"trust": 0, "hana_name": "???"},
        "dice": SEED_42_DICE,
        "stage": {"background": None, "sprites": []},           # F04
        "audio": {"music": [], "sounds": []},                   # F08
        "choices": {"picks": [], "waiting": None},    # F07: always written
        "history": {"entries": [{"kind": "line", "sid": program.at("start", (0,)).sid,
                                 "name": "???", "text": "Start."}]},       # F13
        "chapter": {"current": None},                           # F18
        "points": {"values": {}},                               # F22
        "rollback": {"enabled": True},                          # F14
        "nvl": {"on": False, "page": []},                       # F17
        "items": {"held": []},                                  # F21
        "minigame": {"waiting": None},                          # F23
        "flow": {"path": []},                                   # F20
        "glitch": {"on": []},                                   # F28
    }
    assert json.dumps(data, ensure_ascii=True).isascii()


def test_ac_f03_54_call_stack(tmp_path):
    program = load_fixture(tmp_path, "flow")
    interp = start(program)
    states = checkpoints(interp)
    six = next(s for s in states if program.get(s.position).text == "6")
    call_c = program.at("b", (1,))
    assert call_c.line == 13
    assert six.to_json()["call_stack"] == [{"sid": call_c.sid, "at": ["b", [1]]}]
    for s in states:
        dice = s.to_json()["dice"]
        assert len(dice) == 16 and dice == dice.lower()


# --- AC-F03-68 — headless without pygame -----------------------------------------------

def test_ac_f03_68_no_pygame():
    # F07 step 5: the example stops at its first menu without inputs, so the run gets the
    # picks the other headless example tests use (computed here, outside the no-pygame run).
    # F24-4: seed 4's picks ("Not this year") skip the lantern and its poem: the bundled
    # minigames are built from F10's widgets, which import pygame, so a run that reaches the
    # poem loads them with pygame (``load_plugins``); the story runtime itself needs none.
    # F25-4: every run crosses the bridge's cross-examination, so the run gets a stand-in
    # signature with the real one's arguments and its won result as a plain test outcome.
    # F26-4: seed 4 walks Hana home, so it reaches her phone chat too: the same kind of
    # stand-in, with the first reply of each ask.
    # F23 s6: every run plays the lantern stall's lantern_memory (game/minigames/, built
    # from F10's widgets too): a stand-in with its test outcome. F27-4's shed puzzle room
    # likewise: a stand-in that leaves by the door at once.
    from tests.runtime.corpus import EXAMPLE_PICKS, example_inputs
    from tests.runtime.stage_story import example_minigames

    inputs = example_inputs(4, EXAMPLE_PICKS[4])
    present = example_minigames()["present_evidence"]
    phone = example_minigames()["phone_chat"]
    memory = example_minigames()["lantern_memory"]
    room = example_minigames()["puzzle_room"]
    left = {"action": "exit", "hotspot": "door", "item": None, "gone": []}
    won = {"action": "present", "statement": "train", "evidence": "festival_map",
           "correct": True}
    replied = {"frame": "keep", "train": "station"}
    code = (
        "import sys; sys.modules['pygame'] = None\n"
        "from pathlib import Path\n"
        "from engine.core.config import load_config\n"
        "from engine.core.paths import GamePaths\n"
        "from engine.core.minigame_types import REQUIRED, ArgSpec, MeterChange, MinigameSig, "
        "Outcome\n"
        "from engine.script import LoadOptions, load_story\n"
        "from engine.runtime.headless import run_headless\n"
        "from engine.runtime.commands import StoryEnded\n"
        f"sig = MinigameSig('present_evidence', 'Cross-Examination', 'engine', "
        f"{present.args!r}, Outcome({won!r}), Outcome({won!r}), None)\n"
        f"phone = MinigameSig('phone_chat', 'Phone', 'engine', "
        f"{phone.args!r}, Outcome({replied!r}), Outcome({replied!r}), None)\n"
        f"memory = MinigameSig('lantern_memory', 'Lantern Memory', 'game', {memory.args!r}, "
        "Outcome(9, (MeterChange('hana', '+=', 1),)), None, None)\n"
        "paths = GamePaths(Path('game').resolve())\n"
        # F04 step 8: the example's config.toml names a position its story uses.
        "positions = load_config(paths).config.stage.positions.keys()\n"
        f"room = MinigameSig('puzzle_room', 'Puzzle Room', 'engine', {room.args!r}, "
        f"Outcome({left!r}), Outcome({left!r}), None)\n"
        "games = {'present_evidence': sig, 'phone_chat': phone, 'lantern_memory': memory,\n"
        "         'puzzle_room': room}\n"
        "result = load_story(paths, LoadOptions(position_names=positions))\n"
        f"cmds = run_headless(result.program, seed=4, inputs={inputs!r},\n"
        "                    minigames=games)\n"
        "assert cmds[-1] == StoryEnded(), cmds[-1]\n"
        "assert 'pygame' not in {m.split('.')[0] for m in sys.modules if sys.modules[m]}\n"
        "print('ok')\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


# --- F44 C1 / TR-F44-07 — start options --------------------------------------------------

START_STORY = """define calls = []
default deck = calls.append(1) or [1, 2]
default trust = 0
label start:
    "Start."
label other:
    "Other."
"""


def test_tr_f44_07_start_options(tmp_path):
    program = load_files(tmp_path, {"main.vns": START_STORY})
    options = StartOptions(label="other", values=(("deck", [9]), ("trust", 5)))
    interp = start(program, start=options)
    assert interp.G["calls"] == [1]                              # each default once
    state = interp.checkpoint()
    assert program.get(state.position).text == "Other."          # the label's first line
    assert dict(state.variables) == {"deck": [9], "trust": 5}
    first = interp.G["deck"]
    first.append(10)
    interp.new_game(1)
    interp.run(10_000)
    assert interp.G["deck"] == [9] and interp.G["deck"] is not first
    assert options.values[0][1] == [9]                           # the options are not shared
