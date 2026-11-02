"""F24-2: the poem game headless (F24 ``06``: AC-F24-03, 06; AC-F24-17 is F23 s2's
``tests/runtime/test_minigame_headless.py``).

**Run P**: F23's Run H on **Template P** (``tests/fixtures/F24/template``; steps A 15, P 16,
B 17), seed 42, with the signatures from ``load_plugins`` (the bundled ones, ``poem_game``
included) passed to both the load and ``run_headless``. Template P's ``define w8`` closes its
``}`` indented, because a continued line must be indented more than the ``define``. The extra
``define``s live in ``extra.vns``, included after line 18, so ``main.vns``'s numbers hold.
"""

import functools
import json
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from engine.minigames.bundled import poem_rules
from engine.minigames.bundled.poem_game import PoemGame
from engine.minigames.loader import load_plugins
from engine.runtime import headless
from engine.runtime.commands import StartMinigame, StoryEnded, StoryFailed
from engine.runtime.interpreter import Interpreter, RestoreResult
from engine.runtime.state import GameState
from engine.script import load_story
from engine.script.loader import LoadOptions
from engine.script.program import Program
from tests.runtime.minigame_story import ALL, at_a, said, start_of, to_line
from tests.runtime.story import fingerprint

TEMPLATE = Path(__file__).resolve().parents[2] / "fixtures" / "F24" / "template"
LINE_A, LINE_P, LINE_B = 15, 16, 17
D = ("sayori", "natsuki", "yuri", "monika")
W8 = ["sunshine", "candy", "melancholy", "whisper", "blank", "zero", "ribbon", "lantern"]
P16 = "minigame poem_game words=w8 rounds=2 page_words=3 into poem_for"


@functools.cache
def sigs():
    """The loader's signatures for a game with no plugins: the bundled minigames."""
    result = load_plugins(GamePaths(TEMPLATE), dev=False)
    assert result.ok and "poem_game" in result.signatures()
    return result.signatures()


def load_p(root: Path, *, line16: str | None = None,
           replace: dict[int, str] | None = None) -> Program:
    """Template P with line 16 (after 4 spaces) and whole lines (``replace``) changed."""
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    lines = (TEMPLATE / "script" / "main.vns").read_text(encoding="utf-8").splitlines()
    if line16 is not None:
        lines[LINE_P - 1] = "    " + line16
    for number, text in (replace or {}).items():
        lines[number - 1] = text
    lines.append('include "extra.vns"')
    (script / "main.vns").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    (script / "extra.vns").write_bytes((TEMPLATE / "script" / "extra.vns").read_bytes())
    result = load_story(GamePaths(root.resolve()), LoadOptions(dev=False, minigames=sigs()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


class Spy:
    """Class spy on ``PoemGame``: the session methods (never called headless) and the
    ``outcome_for`` hook's calls (kind, meters)."""

    def __init__(self, monkeypatch) -> None:
        self.session: list[str] = []
        self.outcomes: list[tuple[str, tuple[str, ...]]] = []
        real = PoemGame.outcome_for

        def outcome_for(game, kind, args, story):
            self.outcomes.append((kind, story.meters))
            return real(game, kind, args, story)

        monkeypatch.setattr(PoemGame, "outcome_for", outcome_for)
        for name in ("start", "handle_event", "update", "draw"):
            monkeypatch.setattr(PoemGame, name,
                                lambda game, *a, _n=name: self.session.append(_n))


def run_p(program: Program, inputs, monkeypatch, *, seed: int = 42):
    """Run P; the commands and the run's interpreter (for the meters and variables at B)."""
    made: list[Interpreter] = []

    class Spied(Interpreter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    with monkeypatch.context() as patch:
        patch.setattr(headless, "Interpreter", Spied)
        commands = headless.run_headless(program, seed=seed, minigames=sigs(), inputs=inputs)
    return commands, made[0]


# --- AC-F24-03 — Refusals at the line and on restore -------------------------------------------

def test_ac_f24_03_refusals_at_the_line_and_on_restore(tmp_path, monkeypatch):
    def refused(line16: str) -> tuple[str, list]:
        commands, _ = run_p(load_p(tmp_path / str(abs(hash(line16))), line16=line16),
                            ["advance"], monkeypatch)
        failed = commands[-1]
        assert type(failed) is StoryFailed and failed.error.code == "E272", failed
        assert failed.error.line == LINE_P
        assert said(commands) == ["Before."]                 # shown; nothing released after
        assert not any(type(c) is StartMinigame for c in commands)
        return failed.error.message, commands

    spy = Spy(monkeypatch)
    typo = {"sunshine": {"sayory": 3}, "x": "yuri"}
    r13 = poem_rules.meter_problem({"words": typo}, D)
    assert r13 is not None and 'Did you mean "sayori"?' in r13
    for line16, message in (
            ("minigame poem_game words=bad1",
             'poem_game can\'t use words=bad1: "sunshine" gives sayori 1.5; a score is a '
             "whole number from 0 to 99."),
            ("minigame poem_game words=w8 rounds=0",
             "poem_game can't use these arguments: rounds must be a whole number from 1 to "
             "50, but it is 0."),
            ("minigame poem_game words=typo rounds=1 page_words=2",
             "poem_game can't use these arguments: " + r13)):
        assert refused(line16)[0] == message, line16
    assert spy.session == []                                 # no session ever existed
    # The template's line: StartMinigame with the args and the story's names.
    program = load_p(tmp_path / "p")
    live = at_a(program, sigs=sigs())
    cmd = start_of(to_line(live, LINE_P))
    assert dict(cmd.args) == {"words": cmd.args["words"], "rounds": 2, "page_words": 3,
                              "to_points": True, "result": "winner"}
    assert list(cmd.args["words"]) == W8 and cmd.names.meters == D and not cmd.restored
    saved = json.dumps(live.checkpoint().to_json())

    def restore(story: Program, edit=None):
        data = json.loads(saved)
        if edit is not None:
            edit(data["minigame"]["waiting"]["args"])
        interp = at_a(story, sigs=sigs())
        before = fingerprint(interp)
        outcome = interp.restore(GameState.from_json(data))
        return interp, outcome.result, before, data

    # Unchanged story; then a patch that drops a word from w8: the save keeps its own list.
    edited_w8 = load_p(tmp_path / "w7", replace={12: ""})        # "lantern" removed
    seven = start_of(to_line(at_a(edited_w8, sigs=sigs()), LINE_P))
    assert list(seven.args["words"]) == W8[:7]
    for story in (program, edited_w8):
        interp, result, _, _ = restore(story)
        assert result is RestoreResult.OK
        again = start_of(interp.take_commands(ALL))
        assert again.restored and again.seed == cmd.seed and list(again.args["words"]) == W8
        assert again.names.meters == D
    # Refused restores: POSITION_NOT_FOUND; F11's nearest point (the hinted retry) refuses
    # too, nothing changes, and no StartMinigame is released.
    no_monika = load_p(tmp_path / "nm", replace={2: "# monika is gone"})

    def hidden_word(args):
        args["words"] = {"a‮b": "yuri", **args["words"]}

    def score(args):
        args["words"]["sunshine"]["sayori"] = 1.5

    for story, edit in ((no_monika, None), (program, hidden_word),
                        (program, lambda args: args.update(rounds=0)), (program, score)):
        interp, result, before, data = restore(story, edit)
        assert result is RestoreResult.POSITION_NOT_FOUND, edit
        hinted = interp.restore(GameState.from_json(data), use_hints=True)
        assert hinted.result is RestoreResult.POSITION_NOT_FOUND
        assert fingerprint(interp) == before
        assert not any(type(c) is StartMinigame for c in interp.take_commands(ALL))
    assert spy.session == []


# --- AC-F24-06 — A headless poem ----------------------------------------------------------------

AFTER_ROW_1 = ("natsuki", (3, 4, 0, 0))
TOTALS = {"sayori": 3, "natsuki": 4, "yuri": 0, "monika": 0}


@pytest.mark.parametrize(("change", "inputs", "seed", "expected"), [
    ("", ["advance", "advance"], 42, AFTER_ROW_1),
    ('result="totals"', ["advance", "advance"], 42, (TOTALS, (3, 4, 0, 0))),
    ('result="words"', ["advance", "advance"], 42, (["sunshine", "candy"], (3, 4, 0, 0))),
    ("rounds=3", ["advance", "advance"], 42, ("sayori", (4, 4, 3, 0))),
    ("to_points=False", ["advance", "advance"], 42, ("natsuki", (0, 0, 0, 0))),
    ('words={"blank": {}, "zero": {"monika": 0}, "x": "yuri"} page_words=2',
     ["advance", "advance"], 42, (None, (0, 0, 0, 0))),
    ("", ["advance", 'finish "yuri"; points yuri += 20'], 42, ("yuri", (0, 0, 20, 0))),
    ("skippable", ["advance", "advance"], 42, AFTER_ROW_1),
    ("", ["advance", "advance"], 1, AFTER_ROW_1),
    ("", ["advance", "advance"], 2, AFTER_ROW_1),
])
def test_ac_f24_06_a_headless_poem(tmp_path, monkeypatch, change, inputs, seed, expected):
    line = P16
    if change == "skippable":
        line = line.replace("poem_game ", "poem_game skippable ")
    elif change.startswith("words="):
        line = line.replace("words=w8", change.split(" page_words")[0]).replace(
            "page_words=3", "page_words=2")
    elif change.startswith("rounds="):
        line = line.replace("rounds=2", change)
    elif change:
        line = line.replace(" into", f" {change} into")
    result, meters = expected
    # {var=} shows only text or a number, so a row whose result is None, a dict, or a list
    # writes B as "After." (Template P's line 17 would stop the story there).
    shown = {} if type(result) is str else {LINE_B: '    "After."'}
    spy = Spy(monkeypatch)
    commands, interp = run_p(load_p(tmp_path / "p", line16=line, replace=shown), inputs,
                             monkeypatch, seed=seed)
    assert type(commands[-1]) is StoryEnded, commands[-1]
    poem_for = interp.checkpoint().variables["poem_for"]
    assert poem_for == result and type(poem_for) is type(result)
    if type(result) is dict:
        assert list(poem_for) == list(result)                # key order (D's)
    assert tuple(interp.points.get(m) for m in D) == meters
    assert said(commands) == ["Before.", f"After {result}." if shown == {} else "After."]
    assert spy.session == []
    finished = any(i.startswith("finish") for i in inputs)
    assert spy.outcomes == ([] if finished else [("test", D)])
