"""F26-2 — the phone chat headless (``06-acceptance.md`` AC-F26-03, AC-F26-06).

**Run C**: F23's Run H on Template C (``tests/fixtures/F26/template``), with the signatures
from ``load_plugins`` (the bundled ``PhoneChat`` among them) passed both to the load and to
``run_headless``. Seed 42. Driver D (``tests/runtime/minigame_story``) for the restore rows.
A class spy on ``PhoneChat`` records every session call and every ``outcome_for``; no
session method may run headless.

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
from engine.minigames.bundled import phone_rules
from engine.minigames.bundled.phone_chat import PhoneChat
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

TEMPLATE = Path(__file__).resolve().parents[2] / "fixtures" / "F26" / "template"
LINE_P = 16                                     # P; A is 15, B is 17
P = "minigame phone_chat chat=late_chat contact=\"Sayori\" time=\"11:42 PM\" into night"
FIRSTS = {"awake": "yes", "walk": "sure"}


def _game(root: Path, line16: str | None = None, edit: dict[int, str] | None = None):
    """Template C under ``root`` with line 16 replaced (after 4 spaces) and ``edit``'s lines
    replaced as written; the program and the plugins' signatures."""
    shutil.copytree(TEMPLATE, root)
    main = root / "script" / "main.vns"
    lines = main.read_text(encoding="utf-8").splitlines()
    if line16 is not None:
        lines[LINE_P - 1] = "    " + line16
    for number, text in (edit or {}).items():
        lines[number - 1] = text
    main.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    paths = GamePaths(root.resolve())
    loaded = load_plugins(paths, dev=False)
    assert loaded.ok, [e.format() for e in loaded.errors]
    sigs = loaded.signatures()
    result = load_story(paths, LoadOptions(dev=False, minigames=sigs))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program, sigs


@pytest.fixture
def spy(monkeypatch):
    """Every ``PhoneChat`` session call as ``(method, …)``; ``outcome_for`` still answers."""
    calls: list[tuple] = []
    for method in ("start", "handle_event", "update", "draw", "layout", "settings_changed"):
        monkeypatch.setattr(PhoneChat, method,
                            lambda self, *a, _m=method: calls.append((_m, *a)))
    real = PhoneChat.outcome_for

    def outcome_for(self, kind, args, story):
        outcome = real(self, kind, args, story)
        calls.append(("outcome_for", kind, outcome))
        return outcome

    monkeypatch.setattr(PhoneChat, "outcome_for", outcome_for)
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


# --- AC-F26-03 — Refusals at the line and on restore -----------------------------------------

def test_ac_f26_03_refusals_at_the_line_and_on_restore(tmp_path, spy, monkeypatch):
    head = "phone_chat can't use these arguments: "
    rows = (
        (P.replace("chat=late_chat", "chat=bad1"),
         head + 'chat must be a list of messages and asks, e.g. ["hi!", {"me": "hey"}], but '
                "it is a dictionary."),
        (P.replace('contact="Sayori"', "contact=3"),
         head + phone_rules.problem({"chat": ["hi"], "contact": 3, "time": None})),
    )
    for n, (line, text) in enumerate(rows):
        program, sigs = _game(tmp_path / f"r{n}", line)
        commands = headless.run_headless(program, seed=42, minigames=sigs, inputs=["advance"])
        failed = commands[-1]
        assert type(failed) is StoryFailed, commands
        assert (failed.error.code, failed.error.line, failed.error.message) == (
            "E272", LINE_P, text), line
        assert said(commands) == ["Before."]
        assert not any(type(c) is StartMinigame for c in commands)
    assert "contact must be a name of 1 to 40" in rows[1][1]           # R13's text
    # The template's line: StartMinigame with the three args.
    program, sigs = _game(tmp_path / "c")
    live = at_a(program, sigs=sigs)
    start = start_of(to_line(live, LINE_P))
    assert dict(start.args) == {"chat": start.args["chat"], "contact": "Sayori",
                                "time": "11:42 PM"}
    assert start.args["chat"][0] == "you awake?" and len(start.args["chat"]) == 7
    assert start.names is story_names(live) and not start.restored
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
    # The define edited (step 1's text): the saved chat is used.
    edited, edited_sigs = _game(tmp_path / "e", edit={3: '    "you up?",'})
    result, starts = restore(edited, edited_sigs, saved)
    assert result is RestoreResult.OK and starts[0].args == start.args
    assert to_line(at_a(edited, sigs=edited_sigs), LINE_P)[-1].args["chat"][0] == "you up?"

    # Saved args edited: the check refuses, POSITION_NOT_FOUND, nothing started.
    def bad(fn) -> dict:
        data = copy.deepcopy(saved)
        fn(data["minigame"]["waiting"]["args"])
        return data

    for fn in (lambda a: a["chat"].__setitem__(0, "x" * 301),
               lambda a: a["chat"][2].__setitem__("ask", "a b"),
               lambda a: a.__setitem__("contact", 3)):
        assert restore(program, sigs, bad(fn)) == (RestoreResult.POSITION_NOT_FOUND, [])
    # A tightened bound (MESSAGE_MAX patched to 5): the same refusal path.
    monkeypatch.setattr(phone_rules, "MESSAGE_MAX", 5)
    assert restore(program, sigs, saved) == (RestoreResult.POSITION_NOT_FOUND, [])
    assert not [c for c in spy if c[0] != "outcome_for"]                  # no session


# --- AC-F26-06 — A headless chat ---------------------------------------------------------------

def test_ac_f26_06_a_headless_chat(tmp_path, spy, made):
    rows = (
        ("first", None, ["advance", "advance"], 42, FIRSTS),
        ("busy", None, ["advance", 'finish {"awake": "yes", "walk": "busy"}'], 42,
         {"awake": "yes", "walk": "busy"}),
        ("ignore", None, ["advance", 'finish {"awake": "ignore", "walk": None}'], 42,
         {"awake": "ignore", "walk": None}),
        ("skippable", P.replace("phone_chat", "phone_chat skippable"), ["advance", "advance"], 42,
         FIRSTS),
        ("quiet", P.replace("chat=late_chat", "chat=quiet"), ["advance", "advance"], 42, {}),
        ("seed1", None, ["advance", "advance"], 1, FIRSTS),
        ("seed2", None, ["advance", "advance"], 2, FIRSTS),
    )
    programs: dict[str | None, tuple] = {}
    for name, line, inputs, seed, expected in rows:
        if line not in programs:
            programs[line] = _game(tmp_path / name, line)
        program, sigs = programs[line]
        spy.clear()
        made.clear()
        commands = headless.run_headless(program, seed=seed, minigames=sigs, inputs=inputs)
        assert said(commands) == ["Before.", "After."], (name, commands[-1])
        night = made[0].checkpoint().variables["night"]
        assert night == expected and type(night) is dict, name
        oracle = [c for c in spy if c[0] == "outcome_for"]
        if inputs[-1].startswith("finish"):
            assert oracle == [], name
        else:
            assert [c[1] for c in oracle] == ["test"], name      # once, with "test"
            assert oracle[0][2].changes == (), name               # no meter or codex change
        assert not [c for c in spy if c[0] != "outcome_for"], name   # no session call
        assert made[0].codex.items() == () and made[0].points.names() == (), name
