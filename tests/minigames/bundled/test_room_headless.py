"""F27-2 — the puzzle room headless (``06-acceptance.md`` AC-F27-03, AC-F27-07).

**Run R**: F23's Run H on Template R (``tests/fixtures/F27/template``), with the signatures
from ``load_plugins`` (the bundled ``PuzzleRoom`` among them) passed both to the load and to
``run_headless``. Seed 42. **Template L** (``template/loop.vns`` as ``main.vns``) is the
design's ``state=x into x`` loop. Driver D (``tests/runtime/minigame_story``) for the restore
rows. A class spy on ``PuzzleRoom`` records every session call and every ``outcome_for``; no
session method may run headless.

Held takes (the project's G6 decision): the session reports ``room_rules.run_gone``.
Headless, ``outcome_for`` sees only the story's declared names (``StoryNames``), never the
held items, so its ``gone`` is ``state``'s known spent keys (``run_gone`` with nothing held).

Not here: F11's nearest-point confirm after POSITION_NOT_FOUND is App-level (F23 s4's App M
rows); these rows assert the runtime half (``check_only`` and ``use_hints`` both refuse, the
interpreter is unchanged, and no ``StartMinigame`` is released).
"""

import copy
import json
import shutil
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.minigames.bundled import room_rules
from engine.minigames.bundled.puzzle_room import PuzzleRoom
from engine.minigames.loader import load_plugins
from engine.runtime import headless
from engine.runtime.commands import StartMinigame, StoryFailed
from engine.runtime.interpreter import Interpreter, RestoreResult
from engine.runtime.minigame import story_names
from engine.runtime.state import GameState
from engine.script import load_story
from engine.script.loader import LoadOptions
from tests.runtime.minigame_story import ALL, at_a, said, start_of, to_line
from tests.runtime.story import fingerprint

TEMPLATE = Path(__file__).resolve().parents[2] / "fixtures" / "F27" / "template"
LINE_P = 10                                     # P; A is 9, B is 11
P = "minigame puzzle_room skippable room=attic state=attic_state into attic_state"
EXIT = {"action": "exit", "hotspot": "out", "item": None, "gone": []}
TAKE = {"action": "take", "hotspot": "hook", "item": "rusty_key", "gone": ["hook"]}
COMBINE = {"action": "combine", "hotspot": None, "item": "magnet_string", "gone": []}
USE = {"action": "use", "hotspot": "drawer", "item": "rusty_key", "gone": ["hook", "drawer"]}


def _game(root: Path, line10: str | None = None, *, main: dict[int, str] | None = None,
          rooms: dict[int, str] | None = None, loop: bool = False):
    """Template R under ``root`` (Template L's ``main.vns`` with ``loop``), line 10 replaced
    (after 4 spaces), ``main``'s and ``rooms``' lines replaced as written; the program and
    the plugins' signatures."""
    shutil.copytree(TEMPLATE, root)
    script = root / "script"
    if loop:
        shutil.copyfile(root / "loop.vns", script / "main.vns")
    for name, edits in (("main.vns", dict(main or {})), ("rooms.vns", rooms or {})):
        if name == "main.vns" and line10 is not None:
            edits[LINE_P] = "    " + line10
        if not edits:
            continue
        path = script / name
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, text in edits.items():
            lines[number - 1] = text
        path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    paths = GamePaths(root.resolve())
    loaded = load_plugins(paths, dev=False)
    assert loaded.ok, [e.format() for e in loaded.errors]
    sigs = loaded.signatures()
    result = load_story(paths, LoadOptions(dev=False, minigames=sigs))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program, sigs


@pytest.fixture
def spy(monkeypatch):
    """Every ``PuzzleRoom`` session call as ``(method, …)``; ``outcome_for`` still answers."""
    calls: list[tuple] = []
    for method in ("start", "handle_event", "update", "draw", "layout", "settings_changed"):
        monkeypatch.setattr(PuzzleRoom, method,
                            lambda self, *a, _m=method: calls.append((_m, *a)))
    real = PuzzleRoom.outcome_for

    def outcome_for(self, kind, args, story):
        outcome = real(self, kind, args, story)
        calls.append(("outcome_for", kind, outcome))
        return outcome

    monkeypatch.setattr(PuzzleRoom, "outcome_for", outcome_for)
    return calls


@pytest.fixture
def made(monkeypatch):
    """The interpreters ``run_headless`` builds."""
    found: list[Interpreter] = []

    class Spied(Interpreter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            found.append(self)

    monkeypatch.setattr(headless, "Interpreter", Spied)
    return found


def _session_calls(spy: list[tuple]) -> list[tuple]:
    return [c for c in spy if c[0] != "outcome_for"]


# --- AC-F27-03 — Refusals at the line and on restore -----------------------------------------

def test_ac_f27_03_refusals_at_the_line_and_on_restore(tmp_path, spy):
    bad_rect, bad_take = (_game(tmp_path / n, line) for n, line in (
        ("rect", "minigame puzzle_room room=bad_rect into attic_state"),
        ("take", P.replace("room=attic", "room=bad_take"))))
    rect_reason = room_rules.problem({"room": {"background": "bg attic", "hotspots": {
        "hook": {"rect": [140, 300], "label": "Coat hook", "take": "rusty_key"},
        "out": {"rect": [40, 120, 180, 420], "label": "Door", "exit": True}}}})
    assert rect_reason.startswith('the rect of "hook" must be ')
    take_reason = ('the take of "hook" is "rusty_kye", but there is no item named "rusty_kye". '
                   'Did you mean "rusty_key"?')
    for (program, sigs), text in (
            (bad_rect, f"puzzle_room can't use room=bad_rect: {rect_reason}"),
            (bad_take, f"puzzle_room can't use these arguments: {take_reason}")):
        commands = headless.run_headless(program, seed=42, minigames=sigs, inputs=["advance"])
        failed = commands[-1]
        assert type(failed) is StoryFailed, commands
        assert (failed.error.code, failed.error.line, failed.error.message) == (
            "E272", LINE_P, text)
        assert said(commands) == ["Before."]
        assert not any(type(c) is StartMinigame for c in commands)
    # The template's line: both args, and names equal to story_names.
    program, sigs = _game(tmp_path / "r")
    live = at_a(program, sigs=sigs)
    start = start_of(to_line(live, LINE_P))
    assert list(start.args) == ["room", "state"] and start.args["state"] is None
    assert list(start.args["room"]["hotspots"])[:2] == ["window", "hook"]
    assert start.names is story_names(live) and start.names.items == (
        "rusty_key", "string", "magnet", "magnet_string", "door_key")
    assert start.skippable and not start.restored
    saved = live.checkpoint().to_json()
    assert json.loads(json.dumps(saved)) == saved

    def restore(program, sigs, data: dict):
        interp = at_a(program, sigs=sigs)
        before = fingerprint(interp)
        state = GameState.from_json(copy.deepcopy(data))
        outcome = interp.restore(state)
        if outcome.result is not RestoreResult.OK:
            assert fingerprint(interp) == before
            assert interp.restore(state, use_hints=True,
                                  check_only=True).result is outcome.result
        return outcome.result, [c for c in interp.take_commands(ALL)
                                if type(c) is StartMinigame]

    # Unchanged: restored, args equal to the saved ones.
    result, starts = restore(program, sigs, saved)
    assert result is RestoreResult.OK and len(starts) == 1 and starts[0].restored
    assert starts[0].args == start.args
    # The define edited (hook renamed peg): the saved room is used, no refusal.
    peg = _game(tmp_path / "peg", rooms={5: '        "peg":    {"rect": [140, 300, 64, 96], '
                                            '"label": "Coat hook", "take": "rusty_key", '
                                            '"image": "attic key"},'})
    result, starts = restore(*peg, saved)
    assert result is RestoreResult.OK and starts[0].args == start.args
    assert "peg" in start_of(to_line(at_a(peg[0], sigs=peg[1]), LINE_P)).args["room"][
        "hotspots"]
    # The rusty_key declaration removed: R14 refuses on restore.
    gone = _game(tmp_path / "gone", main={1: "# (rusty_key's declaration removed)"})
    assert restore(*gone, saved) == (RestoreResult.POSITION_NOT_FOUND, [])

    # Saved args edited: R5 and R13, the same path.
    def bad(fn) -> dict:
        data = copy.deepcopy(saved)
        fn(data["minigame"]["waiting"]["args"])
        return data

    for fn in (lambda a: a["room"]["hotspots"]["hook"].__setitem__("rect", [0, 0, 10, 10]),
               lambda a: a.__setitem__("state", {"gone": "hook"})):
        assert restore(program, sigs, bad(fn)) == (RestoreResult.POSITION_NOT_FOUND, [])
    assert _session_calls(spy) == []                                     # no session


# --- AC-F27-07 — A headless room ---------------------------------------------------------------

def test_ac_f27_07_a_headless_room(tmp_path, spy, made):
    state_line = P.replace("state=attic_state", 'state={"gone": ["hook", "zzz"]}')
    rows = (
        ("exit", None, ["advance", "advance"], 42, EXIT, ()),
        ("take", None, ["advance", f"finish {TAKE!r}; unlock item rusty_key"], 42, TAKE,
         ("rusty_key",)),
        ("combine", None, ["advance", f"finish {COMBINE!r}; unlock item magnet_string"], 42,
         COMBINE, ("magnet_string",)),
        ("state", state_line, ["advance", "advance"], 42, {**EXIT, "gone": ["hook"]}, ()),
        ("seed1", None, ["advance", "advance"], 1, EXIT, ()),
        ("seed2", None, ["advance", "advance"], 2, EXIT, ()),
    )
    programs: dict[str | None, tuple] = {}
    for name, line, inputs, seed, expected, held in rows:
        if line not in programs:
            programs[line] = _game(tmp_path / name, line)
        program, sigs = programs[line]
        spy.clear()
        made.clear()
        commands = headless.run_headless(program, seed=seed, minigames=sigs, inputs=inputs)
        assert said(commands) == ["Before.", "After."], (name, commands[-1])
        result = made[0].checkpoint().variables["attic_state"]
        assert result == expected and type(result) is dict, name
        assert tuple(made[0].codex.items()) == held, name
        oracle = [c for c in spy if c[0] == "outcome_for"]
        if inputs[-1].startswith("finish"):
            assert oracle == [], name
        else:
            assert [c[1] for c in oracle] == ["test"], name          # once, with "test"
            assert oracle[0][2].changes == (), name
        assert _session_calls(spy) == [], name
    # Template L: take, use, then advance; the third run leaves by "out" to the hallway.
    program, sigs = _game(tmp_path / "loop", loop=True)
    spy.clear()
    made.clear()
    commands = headless.run_headless(program, seed=42, minigames=sigs, inputs=[
        f"finish {TAKE!r}; unlock item rusty_key", f"finish {USE!r}", "advance"])
    assert said(commands) == ["The key turns. Inside, a magnet.", "Hallway."], commands[-1]
    interp = made[0]
    assert interp.checkpoint().variables["attic_state"] == {**EXIT, "gone": ["hook", "drawer"]}
    assert "rusty_key" not in tuple(interp.codex.items())
    assert [c[1] for c in spy if c[0] == "outcome_for"] == ["test"]
    assert _session_calls(spy) == []
