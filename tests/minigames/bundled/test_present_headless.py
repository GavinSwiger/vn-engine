"""F25-2: present evidence headless (F25 ``06``: AC-F25-03, 05, and 18's Template E rows; its
Template M rows and the ``StoryNames`` unit row are F23 s2's and the A5/A7 task's).

**Run E**: F23's Run H on **Template E** (``tests/fixtures/F25/template``; steps A 18, M 19,
B 20), seed 42, with the signatures from ``load_plugins`` (the bundled ones,
``present_evidence`` included) passed to both the load and ``run_headless``. **Template L** is
``template/loop.vns`` (01 §5.2's loop). Both close ``define daichi_says``'s ``}`` indented,
because a continued line must be indented more than the ``define``.

F11's nearest-point confirm after POSITION_NOT_FOUND is App-level; the restore rows assert the
runtime half (the plain and the hinted restore both refuse, the interpreter is unchanged, and
no ``StartMinigame`` is released).
"""

import functools
import json
from pathlib import Path

import pytest

from engine.core.minigame_types import StoryNames
from engine.core.paths import GamePaths
from engine.minigames.bundled import present_rules
from engine.minigames.bundled.present_evidence import PresentEvidence
from engine.minigames.loader import load_plugins
from engine.runtime import headless
from engine.runtime.commands import Advance, StartMinigame, StoryEnded, StoryFailed
from engine.runtime.interpreter import Interpreter, RestoreResult
from engine.runtime.minigame import story_names
from engine.runtime.state import GameState
from engine.script import load_story
from engine.script.loader import LoadOptions
from engine.script.program import Program
from tests.runtime.minigame_story import ALL, at_a, said, start_of, to_line
from tests.runtime.story import fingerprint

TEMPLATE = Path(__file__).resolve().parents[2] / "fixtures" / "F25" / "template"
LINE_A, LINE_M, LINE_B = 18, 19, 20
M19 = ('minigame present_evidence skippable testimony=daichi_says answer=daichi_answer '
       'speaker="Daichi" penalty="credibility" at=stmt into shown')
STORY_S = StoryNames(meters=("credibility",), items=("brass_key", "festival_map",
                                                     "shrine_photo"),
                     tips=("lanterns",),
                     item_categories=(("Evidence", ("brass_key", "festival_map")),
                                      ("codex_items", ("shrine_photo",))))
WIN = {"action": "present", "statement": "gate", "evidence": "brass_key", "correct": True}
WRONG = {"action": "present", "statement": "gate", "evidence": "festival_map",
         "correct": False}
PRESS = {"action": "press", "statement": "after_dark", "evidence": None, "correct": False}
FINISH_WRONG = ('finish {"action": "present", "statement": "gate", "evidence": '
                '"festival_map", "correct": False}; points credibility -= 1')
FINISH_PRESS = ('finish {"action": "press", "statement": "after_dark", "evidence": None, '
                '"correct": False}')


@functools.cache
def sigs():
    """The loader's signatures for a game with no plugins: the bundled minigames."""
    result = load_plugins(GamePaths(TEMPLATE), dev=False)
    assert result.ok and "present_evidence" in result.signatures()
    return result.signatures()


def load_e(root: Path, *, line19: str | None = None, replace: dict[int, str] | None = None,
           source: str = "script/main.vns") -> Program:
    """Template E (or ``source``) with line 19 (after 4 spaces) and whole lines changed."""
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    lines = (TEMPLATE / source).read_text(encoding="utf-8").splitlines()
    if line19 is not None:
        lines[LINE_M - 1] = "    " + line19
    for number, text in (replace or {}).items():
        lines[number - 1] = text
    (script / "main.vns").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    result = load_story(GamePaths(root.resolve()), LoadOptions(dev=False, minigames=sigs()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


class Spy:
    """Class spy on ``PresentEvidence``: the session methods (never called headless) and
    the ``outcome_for`` hook's kinds."""

    def __init__(self, monkeypatch) -> None:
        self.session: list[str] = []
        self.outcomes: list[str] = []
        real = PresentEvidence.outcome_for

        def outcome_for(game, kind, args, story):
            self.outcomes.append(kind)
            return real(game, kind, args, story)

        monkeypatch.setattr(PresentEvidence, "outcome_for", outcome_for)
        for name in ("start", "handle_event", "update", "draw"):
            monkeypatch.setattr(PresentEvidence, name,
                                lambda game, *a, _n=name: self.session.append(_n))


def run_e(program: Program, inputs, monkeypatch, *, seed: int = 42):
    """Run E; the commands and the run's interpreter (for the meter and variables at B)."""
    made: list[Interpreter] = []

    class Spied(Interpreter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    with monkeypatch.context() as patch:
        patch.setattr(headless, "Interpreter", Spied)
        commands = headless.run_headless(program, seed=seed, minigames=sigs(), inputs=inputs)
    return commands, made[0]


def _with(arg: str) -> str:
    """M19 with one more written argument."""
    return M19.replace(" into", f" {arg} into")


# --- AC-F25-03 — Refusals at the line and on restore -------------------------------------------

def test_ac_f25_03_refusals_at_the_line_and_on_restore(tmp_path, monkeypatch):
    spy = Spy(monkeypatch)
    r14 = present_rules.story_problem({"testimony": {"gate": "x"},
                                       "answer": {"gate": "brass_key"},
                                       "evidence": ["Evidnce"]}, STORY_S)
    assert r14 is not None and 'Did you mean "Evidence"?' in r14
    for row, (line19, message) in enumerate((
            (M19.replace("answer=daichi_answer", 'answer={"gate": "brass_kye"}'),
             "present_evidence can't use these arguments: the answer for \"gate\" is "
             "\"brass_kye\", but there is no item named \"brass_kye\". Did you mean "
             "\"brass_key\"?"),
            (_with('evidence=["Evidnce"]'),
             "present_evidence can't use these arguments: " + r14))):
        commands, _ = run_e(load_e(tmp_path / f"r{row}", line19=line19), ["advance"],
                            monkeypatch)
        failed = commands[-1]
        assert type(failed) is StoryFailed and failed.error.code == "E272", failed
        assert failed.error.line == LINE_M and failed.error.message == message
        assert said(commands) == ["Before."]
        assert not any(type(c) is StartMinigame for c in commands)
    assert spy.session == []                                 # no session ever existed
    # The template's line: StartMinigame with the args and the story's names.
    program = load_e(tmp_path / "e")
    live = at_a(program, sigs=sigs())
    cmd = start_of(to_line(live, LINE_M))
    assert list(cmd.args) == ["testimony", "answer", "at", "speaker", "press", "evidence",
                              "penalty", "penalty_max", "cost"]
    assert list(cmd.args["testimony"]) == ["after_dark", "gate", "priest"]
    assert cmd.args["answer"] == {"gate": "brass_key"} and cmd.args["speaker"] == "Daichi"
    assert cmd.names is story_names(live) and cmd.names == STORY_S and not cmd.restored
    saved = json.dumps(live.checkpoint().to_json())
    evidence = load_e(tmp_path / "ev", line19=_with('evidence=["Evidence"]'))
    live = at_a(evidence, sigs=sigs())
    to_line(live, LINE_M)
    saved_ev = json.dumps(live.checkpoint().to_json())

    def restore(story: Program, edit=None, *, text: str = saved):
        data = json.loads(text)
        if edit is not None:
            edit(data["minigame"]["waiting"]["args"])
        interp = at_a(story, sigs=sigs())
        before = fingerprint(interp)
        outcome = interp.restore(GameState.from_json(data))
        return interp, outcome.result, before, data

    # Unchanged; then a patch that drops "gate" from daichi_says: the save keeps its own
    # (the patched story's own line now refuses, because the answer names "gate").
    no_gate = load_e(tmp_path / "ng", replace={10: ""})
    fresh = at_a(no_gate, sigs=sigs())
    fresh.post(Advance(fresh.current.sid))
    fresh.run(10_000)
    assert 'answer names the statement "gate"' in fresh.take_commands(ALL)[-1].error.message
    for story in (program, no_gate):
        interp, result, _, _ = restore(story)
        assert result is RestoreResult.OK
        again = start_of(interp.take_commands(ALL))
        assert again.restored and again.seed == cmd.seed and dict(again.args) == dict(cmd.args)
        assert list(again.args["testimony"]) == ["after_dark", "gate", "priest"]
    # Refused: R12 (brass_key gone; renamed so the unlock line keeps its shape), R13, R14,
    # and edited saves (R7, R3, R11).
    no_key = load_e(tmp_path / "nk", replace={
        4: 'lock item brass_kee "Brass Key" in "Evidence"', 15: "    unlock item brass_kee"})
    no_meter = load_e(tmp_path / "nm", replace={1: "# credibility is gone"})
    renamed = load_e(tmp_path / "rn", line19=_with('evidence=["Evidence"]'), replace={
        4: 'lock item brass_key "Brass Key" in "Clues"',
        5: 'lock item festival_map "Festival Map" in "Clues"'})

    def hidden_text(args):
        args["testimony"]["gate"] = "The gate‮ was locked."

    for story, edit, text in (
            (no_key, None, saved), (no_meter, None, saved), (renamed, None, saved_ev),
            (program, lambda args: args.update(at="gat"), saved),
            (program, hidden_text, saved), (program, lambda args: args.update(cost=9), saved)):
        interp, result, before, data = restore(story, edit, text=text)
        assert result is RestoreResult.POSITION_NOT_FOUND, (story, edit)
        hinted = interp.restore(GameState.from_json(data), use_hints=True)
        assert hinted.result is RestoreResult.POSITION_NOT_FOUND
        assert fingerprint(interp) == before
        assert not any(type(c) is StartMinigame for c in interp.take_commands(ALL))
    # The renamed category restores fine without evidence (the control for R14's row).
    assert restore(renamed)[1] is RestoreResult.OK
    assert spy.session == []


# --- AC-F25-05 — A headless cross-examination ---------------------------------------------------

@pytest.mark.parametrize(("inputs", "seed", "shown", "credibility"), [
    (["advance", "advance"], 42, WIN, 5),
    (["advance", FINISH_WRONG], 42, WRONG, 4),
    (["advance", FINISH_PRESS], 42, PRESS, 5),
    (["advance", "advance"], 1, WIN, 5),
    (["advance", "advance"], 2, WIN, 5),
    ("loop", 42, WIN, 4),
])
def test_ac_f25_05_a_headless_cross_examination(tmp_path, monkeypatch, inputs, seed, shown,
                                                credibility):
    spy = Spy(monkeypatch)
    loop = inputs == "loop"
    if loop:                                                 # Template L: press, wrong, win
        program = load_e(tmp_path / "l", source="loop.vns")
        inputs = [FINISH_PRESS, "advance", FINISH_WRONG, "advance"]
    else:
        program = load_e(tmp_path / "e")
    commands, interp = run_e(program, inputs, monkeypatch, seed=seed)
    assert type(commands[-1]) is StoryEnded, commands[-1]
    variables = interp.checkpoint().variables
    assert variables["shown"] == shown and list(variables["shown"]) == list(shown)
    assert interp.points.get("credibility") == credibility
    assert spy.session == []
    if loop:
        assert said(commands) == ["I said what I said!", "And how does that prove anything?",
                                  "Breakthrough."]
        assert variables["stmt"] == "gate" and spy.outcomes == ["test"]
    else:
        assert said(commands) == ["Before.", "After."]
        finished = any(i.startswith("finish") for i in inputs)
        assert spy.outcomes == ([] if finished else ["test"])


# --- AC-F25-18 — A5: item categories (Template E) -----------------------------------------------

def test_ac_f25_18_item_categories_on_template_e(tmp_path):
    program = load_e(tmp_path / "e")
    interp = at_a(program, sigs=sigs())
    names = story_names(interp)
    assert names == STORY_S and story_names(interp) is names   # built once per interpreter
    photo_first = load_e(tmp_path / "p", replace={
        4: 'lock item shrine_photo "Shrine Photo"',
        5: 'lock item brass_key "Brass Key" in "Evidence"',
        6: 'lock item festival_map "Festival Map" in "Evidence"'})
    first = story_names(at_a(photo_first, sigs=sigs()))
    assert first.item_categories == (("codex_items", ("shrine_photo",)),
                                     ("Evidence", ("brass_key", "festival_map")))
    assert first.items == ("shrine_photo", "brass_key", "festival_map")
    assert StoryNames((), (), ()).item_categories == ()
    cmd = start_of(to_line(interp, LINE_M))
    assert cmd.names is names
    interp.restore(GameState.from_json(interp.checkpoint().to_json()))
    assert start_of(interp.take_commands(ALL)).names is names
