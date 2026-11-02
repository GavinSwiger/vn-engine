"""F05 step 3: resolving a line's body (``04-technical.md`` §7.2, §7.3, §9; ``02-script.md``
§3.3, §3.4, §5.4) and F03's C2 (a)–(d) edits.

ACs: AC-F05-04 (``{var}`` shows the value as the line starts), AC-F05-05 (the run half: E170,
E171; the W42 half is ``tests/script/test_w42.py``), AC-F05-06 (restored lines keep their
values; W46). Unit rows of AC-F05-07 and AC-F05-08 (whose on-screen clauses are step 6): the
headless bodies, and the E168/E169 message rows of ``cases.toml`` (``time = "launch"``).

Bodies are written in 06 §0.5's notation through ``body()``: ``("text", "b", "i",
"#rrggbb")``.
"""

import json
import logging
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from engine.core.paths import GamePaths
from engine.runtime.character import CHARACTER_OPTIONS
from engine.runtime.commands import (EMPTY_TEXT, PauseMark, Say, Span, StoryFailed, Style,
                                     TaggedText, VarMark, WaitMark)
from engine.runtime.errors import StoryError
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from engine.runtime.text import format_value, resolve_body
from engine.script import load_story
from engine.script.diagnostics import ScriptErrorGroup
from engine.script.program import Program
from tests.runtime.stage_story import load_example
from tests.runtime.story import advance, end_waits, launched, load_files, start
from tests.script import message_cases
from tests.script.helpers import template_x

ROOT = Path(__file__).resolve().parents[2]
F05 = ROOT / "tests" / "fixtures" / "F05"
THOUGHT = "#1e4a9c"
W46_GONE = ("script/main.vns, line 7: this line was restored, but {var=shrine} no longer "
            "exists in this version of the game, so it shows as empty text. Add default "
            "shrine = … at the top level so older saves keep showing it.")


def body(*pieces, auto_next: bool = False) -> TaggedText:
    """06 §0.5: ``"x"`` or ``("x", "b", "i", "#rrggbb")`` is a span; other pieces as is."""
    out = []
    for piece in pieces:
        if isinstance(piece, str):
            piece = (piece,)
        if isinstance(piece, tuple):
            text, *fields = piece
            color = next((f for f in fields if f.startswith("#")), None)
            piece = Span(text, Style(bold="b" in fields, italic="i" in fields, color=color))
        out.append(piece)
    return TaggedText(tuple(out), auto_next)


def load_x(root: Path, **edit) -> Program:
    return load_files(root, {"main.vns": template_x(**edit)})


def says(commands) -> list[Say]:
    return [c for c in commands if type(c) is Say]


def first_body(root: Path, **edit) -> TaggedText:
    """The body of the first line of template X with ``edit``."""
    commands = run_headless(load_x(root, **edit), seed=42)
    assert not [c for c in commands if type(c) is StoryFailed], commands
    return says(commands)[0].body


# --- format_value (§7.3 step 2; I-3) ----------------------------------------------------------

class Loud(str):
    def __str__(self):
        raise AssertionError("an author method ran")


class Big(int):
    def __repr__(self):
        raise AssertionError("an author method ran")

    __str__ = __format__ = __repr__


@pytest.mark.parametrize("value, shown", [
    ("Aiko", "Aiko"), ("", ""), (1200, "1200"), (-7, "-7"), (0.5, "0.5"), (1e20, "1e+20"),
    (1200.0, "1200.0"), ("{b}x{{y}", "{b}x{{y}"), ("a\r\nb c\nd", "a b c d"),
    ("a\rb\x85c d\n\n", "a b c d  "), ("x" * 200, "x" * 200),
    ("x" * 250, "x" * 199 + "…"), ("😀" * 201, "😀" * 199 + "…"),
    ("é" * 201, "é" * 199 + "…"), ("é" * 200, "é" * 200),
])
def test_format_value_text_and_numbers(value, shown):
    assert format_value(value) == shown


@pytest.mark.parametrize("value", [True, False, None, [], {}, (1,), b"x", Loud("hi"), Big(3),
                                   object(), format_value],
                         ids=lambda v: type(v).__name__)
def test_format_value_refuses_everything_else_without_running_author_code(value):
    assert format_value(value) is None


def test_format_value_an_int_too_long_to_print_is_not_shown():
    assert format_value(10 ** 5000) is None


# --- AC-F05-04 — `{var}` shows the value as the line starts -----------------------------------

@pytest.mark.parametrize("edit, shown", [
    ({"T": 'default x = "Aiko"'}, "Aiko"),
    ({"D": '$ x = "Ren"⏎[4]"[{var=x}]"'}, "Ren"),
    ({"T": "default x = 1200"}, "1200"),
    ({"T": "default x = 0.5"}, "0.5"),
    ({"T": "default x = 1e20"}, "1e+20"),
    ({"T": 'define x = "Lanterns"'}, "Lanterns"),
    ({"D": '$ x = "a\\r\\nb\\u2028c\\nd"⏎[4]"[{var=x}]"'}, "a b c d"),
    ({"D": '$ x = "{b}x{{y}"⏎[4]"[{var=x}]"'}, "{b}x{{y}"),
    ({"D": '$ x = "x" * 200⏎[4]"[{var=x}]"'}, "x" * 200),
    ({"D": '$ x = "x" * 250⏎[4]"[{var=x}]"'}, "x" * 199 + "…"),
    ({"D": '$ x = "😀" * 201⏎[4]"[{var=x}]"'}, "😀" * 199 + "…"),
], ids=["text", "dollar", "int", "float", "1e20", "define", "breaks", "braces", "200", "250",
        "emoji"])
def test_ac_f05_04_var_shows_the_value(tmp_path, edit, shown):
    if "D" not in edit:
        edit = {**edit, "S": "[{var=x}]"}
    assert first_body(tmp_path, **edit) == body("[" + shown + "]")


def test_ac_f05_04_the_value_takes_the_styles_around_it(tmp_path):
    assert first_body(tmp_path / "a", S="{b}{var=player_name}{/b}") == body(("Ren", "b"))
    assert first_body(tmp_path / "b", D='thought "{var=player_name}"') == body(
        ("Ren", "i", THOUGHT))
    assert first_body(tmp_path / "c", S="Hi {i}{var=player_name}{/i}{pause} {var=wishes}!") \
        == body("Hi ", ("Ren", "i"), WaitMark(), " 3!")


def test_ac_f05_04_the_value_is_taken_when_the_line_starts(tmp_path):
    program = load_x(tmp_path, S="We have {var=wishes} wishes.",
                     replace={8: '[4]$ wishes = 0⏎[4]"Next."'})
    interp = start(program)
    line7 = says(interp.take_commands(10))[0]
    advance(interp)
    nxt = says(interp.take_commands(10))
    assert [c.text for c in nxt] == ["Next."] and interp.G["wishes"] == 0
    assert line7.body == body("We have 3 wishes.") and line7.text == "We have {var=wishes} wishes."


def test_say_body_is_the_parsed_body_when_nothing_resolves(tmp_path):
    """A line with no ``{var}`` and no text style keeps the node's body object (no copy)."""
    program = load_x(tmp_path, S="{b}Hi{/b}{pause=0.5} there.{next}")
    interp = start(program)
    (line,) = says(interp.take_commands(10))
    node = program.get(line.sid)
    assert line.body is node.body is interp.body_for(node)
    assert line.body == body(("Hi", "b"), PauseMark(0.5), " there.", auto_next=True)


def test_the_resolved_body_holds_no_var_mark_and_keeps_marks_and_auto_next(tmp_path):
    line = first_body(tmp_path, D='thought "{var=wishes}{pause}{b}{var=player_name}{/b}{next}"')
    assert line == body(("3", "i", THOUGHT), WaitMark(), ("Ren", "b", "i", THOUGHT),
                        auto_next=True)
    assert not [p for p in line.pieces if type(p) is VarMark]


def test_an_empty_value_leaves_no_empty_span(tmp_path):
    assert first_body(tmp_path, S="[{b}{var=x}{/b}]", T='default x = ""') == body("[]")


# --- AC-F05-07 / 08 (headless parts; on-screen clauses are step 6) ----------------------------

def test_ac_f05_07_a_characters_text_style(tmp_path):
    program = load_x(tmp_path, D='thought "Do {i}they{/i} {color=#9a1c14}swim{/color}?"⏎[4]'
                                 'hana "Plain."⏎[4]"Told."')
    bodies = [c.body for c in says(run_headless(program, seed=42))]
    assert bodies[:3] == [
        body(("Do they ", "i", THOUGHT), ("swim", "i", "#9a1c14"), ("?", "i", THOUGHT)),
        body("Plain."), body("Told.")]


def test_text_color_is_stored_lower_case(tmp_path):
    line = first_body(tmp_path, D='t "Hi."',
                      T='define t = Character("T", text_color="#ABCDEF", text_italic=False)')
    assert line == body(("Hi.", "#abcdef"))


def test_ac_f05_08_name_from_values_are_shown_as_written(tmp_path):
    program = load_x(tmp_path, D='r "Hi."',
                     T='define r = Character(name_from="nm")⏎default nm = "{b}Ren{/b}"')
    (line,) = says(run_headless(program, seed=42))[:1]
    assert line.name == "{b}Ren{/b}" and line.body == body("Hi.")


def test_ac_f05_08_five_character_options():
    """07 I-2: after F05 step 3, AC-F03-32's E75b rows list F05's options (F06 adds four;
    ``test_character.py`` has the whole list)."""
    assert {"text_color", "text_italic"} <= set(CHARACTER_OPTIONS)


def test_e168_e169_from_a_dollar_line_stop_the_story(tmp_path):
    for i, (D, code) in enumerate([('$ c = Character("A", text_italic="no")', "E168"),
                                   ('$ c = Character("{i}A")', "E169")]):
        commands = run_headless(load_x(tmp_path / str(i), D=D), seed=42)
        assert type(commands[-1]) is StoryFailed and commands[-1].error.code == code


# --- AC-F05-05 and AC-F05-08: the run and launch rows of cases.toml ----------------------------

CASES = [c for c in message_cases.load_cases() if c.feature == "F05" and c.time != "load"]


def play(case) -> tuple[list, message_cases.Outcome]:
    with tempfile.TemporaryDirectory() as tmp:
        text = message_cases.main_text(case)
        assert isinstance(text, str)
        program = load_files(Path(tmp), {"main.vns": text})
        commands = run_headless(program, seed=42)
        if case.time == "launch":
            assert (run_launch(program).namespace is None) == (case.code != "-")
    failed = [c for c in commands if type(c) is StoryFailed]
    if not failed:
        return commands, message_cases.Outcome([], (), 0, False)
    error = failed[-1].error
    if isinstance(error, ScriptErrorGroup):
        return commands, message_cases.Outcome(list(error.errors), (), error.total, False)
    return commands, message_cases.Outcome([error], (), 1, False)


def test_rows_cover_the_run_and_launch_codes():
    assert {c.code for c in CASES if c.time == "run"} >= {"E170", "E171"}
    assert {c.code for c in CASES if c.time == "launch"} >= {"E168", "E169"}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_case(case):
    commands, outcome = play(case)
    message_cases.check_case(case, outcome)
    if case.code == "-":
        if case.time == "run":
            assert [c.body for c in says(commands)][:1] == [body("x")]
        return
    assert type(commands[-1]) is StoryFailed
    assert [type(c) for c in commands].count(StoryFailed) == 1
    if case.time == "run":
        assert not says(commands)                      # line 7 is never shown
        assert type(commands[-1].error) is StoryError
        assert commands[-1].error.format().startswith("script/main.vns, line 7: {var=")


def test_e170_is_logged_once_and_the_story_fails(tmp_path, caplog):
    interp = start(load_x(tmp_path, S="{var=nope}"))
    assert interp.status is Status.FAILED
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and "{var=nope} shows a variable that doesn't exist" in \
        errors[0].getMessage()


# --- AC-F05-06 — Restored lines keep their values ---------------------------------------------

def round_trip(state: GameState) -> GameState:
    return GameState.from_json(json.loads(json.dumps(state.to_json(), ensure_ascii=True)))


def wishes_story(root: Path) -> Program:
    return load_x(root, S="We have {var=wishes} wishes.",
                  replace={8: '[4]$ wishes = 0⏎[4]"Next."'})


@pytest.mark.parametrize("how", ["load", "rollback", "reload"])
def test_ac_f05_06_a_restored_line_keeps_its_value(tmp_path, how):
    program = wishes_story(tmp_path)
    interp = start(program)
    line7 = says(interp.take_commands(10))[0]
    seven = interp.checkpoint()
    advance(interp)                                     # waiting at "Next.", wishes == 0
    interp.take_commands(10)
    if how == "rollback":
        target = interp
    else:
        target = launched(program)
        seven = round_trip(seven) if how == "load" else seven
    assert target.restore(seven).result is RestoreResult.OK
    (again,) = says(target.take_commands(10))
    assert again.restored and again.body == line7.body == body("We have 3 wishes.")
    assert again == replace(line7, restored=True)


def load_patch(root: Path, version: str) -> Program:
    shutil.copytree(F05 / "patch" / version, root)
    result = load_story(GamePaths(root.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def saved_at_line_7(tmp_path: Path) -> tuple[GameState, Say]:
    interp = start(load_patch(tmp_path / "v1", "v1"))
    advance(interp)
    (line,) = says(interp.take_commands(10))[-1:]
    assert line.body == body("At Inari.")
    return interp.checkpoint(), line


def w46_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == logging.WARNING
            and "this line was restored" in r.getMessage()]


@pytest.mark.parametrize("how", ["load", "reload"])
def test_ac_f05_06_a_value_a_patch_removed_shows_as_empty_text(tmp_path, caplog, how):
    state, _ = saved_at_line_7(tmp_path)
    if how == "load":
        state = round_trip(state)
    v2 = load_patch(tmp_path / "v2", "v2")
    interp = launched(v2)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert interp.restore(state).result is RestoreResult.OK
    commands = interp.take_commands(10)
    (line,) = says(commands)
    assert line.restored and line.body == body("At .")
    assert not [c for c in commands if type(c) is StoryFailed]
    records = w46_records(caplog)
    assert [(r.name, r.getMessage()) for r in records] == [("vn.runtime", W46_GONE)]
    advance(interp)
    assert [c.text for c in says(interp.take_commands(10))] == ["Next."]
    assert interp.status is Status.WAITING


def test_ac_f05_06_a_rollback_uses_the_same_w46_text(tmp_path, caplog):
    """G5: one W46 text. A rollback in the same session whose state lacks the value (a
    ``$`` line set it; no default fills it again)."""
    program = load_x(tmp_path, D='$ place = "Inari"⏎[4]"At {var=place}."',
                     replace={8: '[4]"Next."'})
    interp = start(program)
    eight = interp.checkpoint()
    advance(interp)
    interp.take_commands(10)
    state = replace(eight, variables=MappingProxyType(
        {k: v for k, v in eight.variables.items() if k != "place"}))
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert interp.restore(state).result is RestoreResult.OK
    (line,) = says(interp.take_commands(10))
    assert line.body == body("At .")
    (record,) = w46_records(caplog)
    assert record.getMessage() == W46_GONE.replace("line 7", "line 8").replace(
        "shrine", "place")


def test_w46_a_value_no_longer_text_or_a_number(tmp_path, caplog):
    program = load_x(tmp_path, S="At {var=player_name}.")
    interp = start(program)
    state = interp.checkpoint()
    bad = replace(state, variables=MappingProxyType({**state.variables, "player_name": [1]}))
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert launched(program).restore(bad).result is RestoreResult.OK
    (record,) = w46_records(caplog)
    assert "{var=player_name} no longer holds text or a number" in record.getMessage()


def test_w46_is_logged_only_when_the_restore_commits(tmp_path, caplog, monkeypatch):
    state, _ = saved_at_line_7(tmp_path)
    v2 = load_patch(tmp_path / "v2", "v2")
    interp = launched(v2)

    def refuse(*args, **kwargs):
        raise StoryError("refused", code="E85e")

    monkeypatch.setattr(interp, "_snapshot", refuse)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert interp.restore(state).result is RestoreResult.DEFAULT_FAILED
    assert w46_records(caplog) == [] and interp._restore_warnings == []
    monkeypatch.delattr(interp, "_snapshot")
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert interp.restore(state).result is RestoreResult.OK
    assert len(w46_records(caplog)) == 1


def test_resolve_body_restoring_never_raises(tmp_path):
    program = load_x(tmp_path, D='thought "{var=gone} {var=hana}"')
    interp = launched(program)
    interp.new_game(1)
    stmt = program.at("start", (0,))
    with pytest.raises(StoryError) as e:
        resolve_body(interp, stmt, interp.G["thought"])
    assert e.value.code == "E170"
    out = resolve_body(interp, stmt, interp.G["thought"], restoring=True)
    assert out == body((" ", "i", THOUGHT))
    assert [w.code for w in interp._restore_warnings] == ["W46", "W46"]


def test_ac_f05_06_every_line_of_the_example_game_restores_an_equal_body():
    """For each line of ``game/`` (seeds 1..5), restoring its checkpoint re-creates an equal
    ``Say`` (body included). The F05 example game itself is step 7; this runs on the game
    the repository holds now."""
    result = load_example()
    assert result.program is not None
    program = result.program
    images = [p.relative_to(ROOT / "game").as_posix()
              for p in (ROOT / "game" / "images").rglob("*") if p.is_file()]
    from engine.runtime.images import ImageSource
    from engine.runtime.interpreter import Interpreter
    launch = run_launch(program, images=ImageSource.from_files(images))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    other = run_launch(program, images=ImageSource.from_files(images)).namespace
    checked = 0
    for seed in range(1, 6):
        interp = Interpreter(program, launch.namespace)
        target = Interpreter(program, other)
        interp.new_game(seed)
        interp.run(10_000)
        end_waits(interp)          # the prologue's chapter card (F18) waits before line 1
        lines = 0
        while interp.status is Status.WAITING and lines < 500:
            shown = says(interp.take_commands(1 << 20))[-1]
            assert target.restore(round_trip(interp.checkpoint())).result is RestoreResult.OK
            (again,) = says(target.take_commands(1 << 20))
            assert again == replace(shown, restored=True)
            checked += 1
            lines += 1
            advance(interp)
    assert checked > 0


# --- Seams and invariants ---------------------------------------------------------------------

def test_body_is_not_saved_state(tmp_path):
    """No new GameState field; the checkpoint holds the variables the body was made from."""
    interp = start(load_x(tmp_path, S="{var=player_name}"))
    state = interp.checkpoint()
    assert "body" not in json.dumps(state.to_json())
    assert state.variables["player_name"] == "Ren"


def test_say_built_by_hand_defaults_to_the_empty_body():
    assert Say("s/1", None, None, None, (), "Hi.").body is EMPTY_TEXT
