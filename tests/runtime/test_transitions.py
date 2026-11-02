"""F09 step 1 — transitions in the runtime (``engine/runtime/transitions.py``; F09
``04-technical.md`` §5.2, §5.3): the constructors and E199 (AC-F09-04), the launch check
E190, E191, E194 (AC-F09-05), W60 (AC-F09-06), names and reserved words (AC-F09-07), and the
mask path and identity rules (AC-F09-39). The launch rows of ``cases.toml`` (``feature =
"F09"``, ``time = "launch"``) are played here as run H's launch."""

import shutil
from pathlib import Path

import pytest

from engine.runtime import transitions as tr
from engine.runtime.commands import ShowStage, StoryEnded, StoryFailed, StoryWait
from engine.runtime.errors import StoryError
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.runtime.transitions import (Dissolve, Fade, Mask, TransitionArgError,
                                        TransitionDef, TransitionSpec, check_transitions,
                                        spec_for)
from engine.script.diagnostics import ScriptErrorGroup, ScriptWarning
from engine.script.effects import WithClause
from engine.script.messages import format_message
from engine.script.words import ENGINE_NAMES
from tests.runtime import stage_story
from tests.runtime.effects_story import (IMG9, launch_h, launched, of_type, run_h,
                                         story_game, template_game, write_game)
from tests.script import message_cases
from tests.script.helpers import template_f

LAUNCH_ROWS = [c for c in message_cases.load_cases()
               if c.feature == "F09" and c.time == "launch"]


def errors_of(result) -> list[str]:
    return [e.format() for e in result.errors]


# --- cases.toml launch rows (AC-F09-04, 05, 39) -------------------------------------------------

def test_launch_rows(tmp_path):
    assert {c.code for c in LAUNCH_ROWS} == {"E190", "E191", "E194", "E199"}
    assert all(not c.runnable for c in LAUNCH_ROWS)
    for case in LAUNCH_ROWS:
        program = template_game(tmp_path / case.id, **{k: v for k, v in {
            "S": case.edit.get("S"), "T": case.edit.get("T"),
            "replace": {int(k): v for k, v in case.edit.get("R", {}).items()} or None}.items()})
        result = launch_h(program)
        assert result.namespace is None, case.id
        message_cases.check_case(case, message_cases.Outcome(list(result.errors), (),
                                                             result.error_count, False))
        commands = run_h(program)
        assert len(commands) == 1 and type(commands[0]) is StoryFailed, case.id
        assert isinstance(commands[0].error, ScriptErrorGroup), case.id


RUN_ROWS = [c for c in message_cases.load_cases() if c.feature == "F09" and c.time == "run"]


def test_presentation_rows(tmp_path):
    """W61, W62 (AC-F09-36, 30): the text ``render`` logs for the row's statement, through
    the same ``transitions`` functions (a flash refused, a short fade, a kind that fails)."""
    assert {c.code for c in RUN_ROWS} == {"W61", "W62"}
    for case in RUN_ROWS:
        stmt = template_game(tmp_path / case.id, S=case.edit["S"]).at("start", (1,))
        if case.code == "W62":
            text = tr.transition_failed_text(stmt.with_clause.name, "MemoryError")
        else:
            text = (tr.flash_refused_text() if case.edit["S"] == "flash"
                    else tr.fade_refused_text())
        warning = ScriptWarning(text, code=case.code, file=stmt.file.ref, line=stmt.line)
        message_cases.check_case(case, message_cases.Outcome([], (warning,), 0, False))


# --- AC-F09-04 — defined transitions and E199 ---------------------------------------------------

DEFINES = [
    ("Dissolve()", TransitionDef("dissolve", None)),
    ('Fade(0.6, color="#ffffff")', TransitionDef("fade", 0.6, color="#FFFFFF")),
    ('Fade(color="red")', TransitionDef("fade", None, color="#FF0000")),
    ('Mask("masks/iris.png")', TransitionDef("mask", None, mask="masks/iris.png", soft=0.1,
                                              reverse=False)),
    ('Mask("masks/iris.png", 1.2, reverse=True)',
     TransitionDef("mask", 1.2, mask="masks/iris.png", reverse=True)),
    ('Mask("masks/iris.png", 0, soft=0.5)', TransitionDef("mask", 0.0, mask="masks/iris.png",
                                                           soft=0.5)),
]


def test_ac04_defines(tmp_path):
    for number, (define, value) in enumerate(DEFINES):
        program = template_game(tmp_path / str(number), T=f"define a = {define}",
                                S="show hana sad with a")
        result = launch_h(program)
        assert result.errors == (), errors_of(result)
        assert result.namespace["a"] == value, define
        assert type(run_h(program)[-1]) is StoryEnded, define
    program = template_game(tmp_path / "unused", T="define n = 3")   # no with uses it: fine
    assert launch_h(program).errors == ()
    assert type(run_h(program)[-1]) is StoryEnded


REFUSALS = [
    (lambda: Dissolve(31), "Dissolve takes seconds from 0 to 30, but this has 31."),
    (lambda: Dissolve(-0.1), "Dissolve takes seconds from 0 to 30, but this has -0.1."),
    (lambda: Dissolve("1"), 'Dissolve takes seconds from 0 to 30, but this has "1".'),
    (lambda: Dissolve(True), "Dissolve takes seconds from 0 to 30, but this has True."),
    (lambda: Dissolve(float("nan")), "Dissolve takes seconds from 0 to 30, but this has nan."),
    (lambda: Fade(31), "Fade takes seconds from 0 to 30, but this has 31."),
    (lambda: Fade(color="#fff"), 'but this has "#fff".'),
    (lambda: Fade(color=1), "but this has 1."),
    (lambda: Mask(), 'Mask needs an image file in quotes, e.g. Mask("masks/iris.png", 1.0).'),
    (lambda: Mask(1.0), 'Mask needs an image file in quotes, e.g. Mask("masks/iris.png", 1.0).'),
    (lambda: Mask("masks/iris.png", soft=-0.1), "Mask's soft takes a number from 0 to 0.5, "
                                                "but this has -0.1."),
    (lambda: Mask("masks/iris.png", soft=float("inf")), "but this has inf."),
    (lambda: Mask("masks/iris.png", reverse="yes"), "Mask's reverse takes True or False, but "
                                                    'this has "yes".'),
    (lambda: Mask("masks/iris.png", 31), "Mask takes seconds from 0 to 30, but this has 31."),
    (lambda: Mask("masks/iris.gif"), "but \"masks/iris.gif\" isn't one. Convert it to .png."),
    (lambda: Mask("masks\\iris.png"), "Mask can't use \"masks\\iris.png\": paths start in the "
                                      "game folder"),
    (lambda: Mask(""), "Mask can't use \"\": paths can't be empty."),
]


def test_ac04_constructor_refusals():
    for call, text in REFUSALS:
        with pytest.raises(TransitionArgError) as caught:
            call()
        assert caught.value.code == "E199" and not caught.value.prefixed, text
        message = caught.value.message
        assert message == text or message.endswith(text) or message.startswith(text), message


def test_ac04_e199_at_the_define_line_with_no_prefix(tmp_path):
    program = template_game(tmp_path, T="define d = Dissolve(-1)")
    (error,) = launch_h(program).errors
    assert (error.code, error.file, error.line) == ("E199", "script/main.vns", 8)
    assert error.message == "Dissolve takes seconds from 0 to 30, but this has -1."


# --- AC-F09-05 — launch errors E190, E191, E194 --------------------------------------------------

def test_ac05_errors_in_reading_order(tmp_path):
    program = template_game(tmp_path, S="show hana with swirl⏎show hana with twirl⏎"
                                        "hide hana with whirl")
    result = launch_h(program)
    assert [(e.code, e.line) for e in result.errors] == [("E190", 6), ("E190", 7), ("E190", 8)]
    assert result.error_count == 3


def test_ac05_a_unicode_define_launches(tmp_path):
    program = template_game(tmp_path, T="define 灯 = Dissolve(1.0)", S="show hana sad with 灯")
    assert launch_h(program).errors == ()
    (show,) = [c for c in of_type(run_h(program), ShowStage) if c.transition is not None]
    assert show.transition.name == "灯" and show.transition.seconds == 1.0


def test_ac05_the_list_shows_ten_define_names_then_a_count():
    defined = [f"t{i:02}" for i in range(12)]
    text = format_message("E190", ("swirl", None, tuple(defined[:10]), 2))
    assert text.endswith("the ones this game defines: t00, t01, t02, t03, t04, t05, t06, t07, "
                         "t08, t09, …and 2 more transitions.")


def test_ac05_a_define_kind_with_a_color(tmp_path):
    program = template_game(tmp_path, S="show hana sad with lantern white")
    (error,) = launch_h(program).errors
    assert error.message == ("with lantern: lantern is a Mask, so it takes a length but no color; "
                             "only fade goes through a color.")


def test_ac05_e191_kinds(tmp_path):
    program = template_game(tmp_path, T="define n = 3", S="show hana sad with n")
    (error,) = launch_h(program).errors
    assert error.message.startswith("with n: n is a whole number, not a transition.")


# --- AC-F09-06 — W60: a missing mask image -------------------------------------------------------

def _locate(present: set[str]):
    def locate(ref: str) -> tuple[bool, str | None]:
        if ref in present:
            return True, None
        stem = ref.rsplit(".", 1)[0]
        near = sorted(p for p in present if p.rsplit(".", 1)[0] == stem)
        return False, near[0] if near else None
    return locate


def _w60(tmp_path, present: set[str], S: str | None = None):
    program = template_game(tmp_path, S=S)
    launch = launch_h(program)
    assert launch.namespace is not None
    errors, warnings = check_transitions(program, launch.namespace, locate=_locate(present))
    assert errors == []
    return warnings


def test_ac06_w60(tmp_path):
    (w60,) = _w60(tmp_path / "a", {"masks/iris.webp"})
    assert (w60.code, w60.file, w60.line) == ("W60", "script/main.vns", 3)
    assert w60.message == ('Mask uses "masks/iris.png", which doesn\'t exist, so lantern plays '
                           'as a dissolve. Did you mean "masks/iris.webp"?')
    # without a suggestion, and once per file
    (w60,) = _w60(tmp_path / "b", set(), S="show hana with lantern⏎hide hana with lantern")
    assert w60.message.endswith("so lantern plays as a dissolve.")
    assert _w60(tmp_path / "c", {"masks/iris.png"}) == []          # none when present


def test_ac06_w60_in_the_launch_only_with_the_game_folder(tmp_path):
    program = template_game(tmp_path, S="show hana with lantern")
    assert launch_h(program).warnings == ()                    # run H: no locate
    source = ImageSource.from_files(IMG9)
    folder = ImageSource(source.list_dir, _locate(set()))        # the app's: game_folder
    result = run_launch(program, images=folder)
    assert result.namespace is not None                          # a warning stops nothing
    assert [(w.code, w.line) for w in result.warnings] == [("W60", 3)]


# --- AC-F09-07 — names, reserved words, and W14 retired -----------------------------------------

def test_ac07_argument_words_are_names(tmp_path):
    program = template_game(tmp_path, T="default small = 1⏎default white = 2⏎"
                                        "default horizontal = 3",
                            S="$ small += white + horizontal⏎shake small")
    commands = run_h(program)
    assert type(commands[-1]) is StoryEnded


def test_ac07_engine_names():
    assert {"Dissolve", "Fade", "Mask", "Transition"} <= ENGINE_NAMES


def test_ac07_transition_is_reserved_and_unbound(tmp_path):
    program = template_game(tmp_path, S="$ x = Transition")
    failed = run_h(program)[-1]
    assert type(failed) is StoryFailed and failed.error.code == "E85b"
    assert "Transition" in failed.error.message


def test_ac07_the_effects_are_voice_transparent(tmp_path):
    root = write_game(tmp_path, template_f(
        S='voice "voice/a.ogg"⏎shake⏎flash⏎pause 0.5⏎hana "A."'))
    from engine.core.paths import GamePaths
    from engine.script.loader import load_story
    result = load_story(GamePaths(root.resolve()))
    assert result.errors == () and result.warnings == ()
    (say,) = [s for s in result.program.iter_statements() if getattr(s, "voice", None)]
    assert say.voice == "voice/a.ogg" and say.text == "A."


def _lanterns_with(root: Path, *, move: bool) -> object:
    shutil.copytree(stage_story.F04 / "lanterns", root)
    chapter = root / "script" / "chapter1.vns"
    text = chapter.read_text(encoding="utf-8")
    text = text.replace("    scene bg river_night\n", "    scene bg river_night with dissolve\n")
    text = text.replace("    hide daichi\n", "    hide daichi with fade 0.5\n")
    if move:
        text = text.replace("    show lantern_girl as girl_b at 1100\n",
                            "    show lantern_girl as girl_b at 1100 with move\n")
    chapter.write_bytes(text.encode("utf-8"))
    return stage_story.load_game(root)


def test_ac07_f04_18_fixture_now_stops_with_e190(tmp_path):
    program = _lanterns_with(tmp_path / "g", move=True)
    result = run_launch(program, images=ImageSource.from_files(stage_story.IMG_L))
    (error,) = result.errors
    assert (error.code, error.file) == ("E190", "script/chapter1.vns")
    assert error.message == ('there is no transition "move". The transitions are cut, dissolve, '
                             "fade, and the ones this game defines: none yet.")


def test_ac07_f04_18_fixture_plays_its_transitions(tmp_path):
    """Without ``with move`` it launches with no warning, every line's picture is AC-F04-06's,
    and the two ``with`` statements each add their moment (F09 grouping: a ``with`` ends a
    moment, so the river is shown alone through the dissolve, and the picture after
    ``hide daichi`` through the fade, before the next line's cut)."""
    program = _lanterns_with(tmp_path / "g", move=False)
    launch = run_launch(program, images=ImageSource.from_files(stage_story.IMG_L))
    assert launch.errors == () and launch.warnings == ()
    commands = stage_story.run_h(program, stage_story.IMG_L)
    plain = stage_story.run_h(stage_story.lanterns(tmp_path / "plain"), stage_story.IMG_L)
    shows = of_type(commands, ShowStage)
    with_moments = [s for s in shows if s.transition is not None]
    assert [(s.transition.kind, s.transition.seconds) for s in with_moments] == [
        ("dissolve", None), ("fade", 0.5)]
    assert [s for s in shows if s.transition is None] == of_type(plain, ShowStage)
    assert len(of_type(commands, StoryWait)) == 2
    assert with_moments[0].stage == stage_story.stage("bg river_night")


# --- AC-F09-39 — mask paths, saved values, and identity -----------------------------------------

def test_ac39_a_transition_in_a_saved_value_is_e85e(tmp_path):
    for name, edit in (("default", {"T": "default t = Dissolve(1.0)"}),
                       ("dollar", {"S": "$ t = Fade()"})):
        failed = run_h(template_game(tmp_path / name, **edit))[-1]
        assert type(failed) is StoryFailed and failed.error.code == "E85e", name


def test_ac39_bad_mask_refs_are_e199_at_the_define(tmp_path):
    for number, ref in enumerate(["../outside.png", "/tmp/x.png", "C:/x.png",
                                  "masks/iris.txt"]):
        program = template_game(tmp_path / str(number), T=f'define g = Mask("{ref}")')
        (error,) = launch_h(program).errors
        assert (error.code, error.line) == ("E199", 8), ref


PRIVACY_ROWS = [  # (S, T): every E190–E199 form and W60, from a game under qauser7/
    ("show hana with disolve", None), ("show hana with swirl", None),
    ("show hana with hana", None), ("show hana with lantern white", None),
    ("show hana with dissolve 90", None), ("show hana with dissolve 0.5s", None),
    ('scene bg sea with fade "#e0505"', None), ("show hana with cut 1", None),
    ("shake huge", None), ("flash 5", None), ("pause 45", None),
    (None, "define dissolve = 1"), (None, "define d = Dissolve(-1)"),
    (None, 'define g = Mask("../outside.png")'), (None, 'define g = Mask("/tmp/x.png")'),
    (None, 'define g = Mask("masks/iris.txt")'),
]


_CODE_STARTS = {"E190": "there is no transition", "E191": "with hana:", "E192": "length",
                "E193": "isn't a color", "E194": "takes a length but no color",
                "E195": "shake takes", "E196": "flash takes", "E197": "pause takes",
                "E198": "is a built-in transition", "E199": "Mask", "W60": "Mask uses"}


def _has_code(text: str, code: str) -> bool:
    return _CODE_STARTS[code] in text


def test_ac39_messages_pass_privacy_check_p(tmp_path):
    """The texts hold script text and game-relative refs only, never the game folder's
    path or the account name (check P's text rules, without the pygame channels)."""
    from engine.core.paths import GamePaths
    from engine.script.loader import load_story
    texts = []
    for number, (S, T) in enumerate(PRIVACY_ROWS):
        root = write_game(tmp_path / "qauser7" / "vn" / f"game{number}", template_f(S=S, T=T))
        loaded = load_story(GamePaths(root.resolve()))
        texts += [e.format() for e in loaded.errors]
        if loaded.program is not None:
            source = ImageSource.from_files(IMG9)
            result = run_launch(loaded.program,
                                images=ImageSource(source.list_dir, _locate(set())))
            texts += [e.format() for e in result.errors] + [w.format() for w in result.warnings]
    assert len(texts) >= len(PRIVACY_ROWS)
    for code in ("E190", "E191", "E192", "E193", "E194", "E195", "E196", "E197", "E198",
                 "E199", "W60"):
        assert any(_has_code(text, code) for text in texts), code
    game_forms = {str(tmp_path), str(tmp_path).replace("\\", "/"), str(tmp_path.resolve())}
    for text in texts:
        assert "qauser7" not in text.lower(), text
        assert not any(form.lower() in text.lower() for form in game_forms), text


def test_constructors_are_bound_and_transition_is_not(tmp_path):
    program = template_game(tmp_path)
    G = launch_h(program).namespace
    assert G["Dissolve"] is Dissolve and G["Fade"] is Fade and G["Mask"] is Mask
    assert "Transition" not in G


# --- spec_for (04 §5.3) ---------------------------------------------------------------------------

SPEC_ROWS = [
    (("cut", None, None), None),
    (("dissolve", 0, None), None),
    (("dissolve", None, None), ("dissolve", None, None)),
    (("fade", 2.0, "#FFFFFF"), ("fade", 2.0, "#FFFFFF")),
    (("slow_dissolve", None, None), ("dissolve", 1.5, None)),
    (("slow_dissolve", 0.4, None), ("dissolve", 0.4, None)),
    (("slow_dissolve", 0, None), None),
    (("lantern", None, None), ("mask", 1.2, None)),
]


def test_spec_for(tmp_path):
    program = template_game(tmp_path)
    sid = program.labels["start"].block[0].sid
    for clause, expected in SPEC_ROWS:
        interp = launched(program)                       # a fresh memo per row
        spec = spec_for(interp, WithClause(*clause, 1, 1), sid)
        if expected is None:
            assert spec is None, clause
            continue
        assert isinstance(spec, TransitionSpec)
        assert (spec.kind, spec.seconds, spec.color) == expected, clause
        assert (spec.name, spec.sid, spec.calm, spec.flashes) == (clause[0], sid, True, False)
        assert spec_for(interp, WithClause(*clause, 1, 1), sid) is spec    # memoized per sid


def test_spec_for_refuses_at_run_time_what_the_launch_would(tmp_path):
    """Without phase 5 (a launch with no image source), a bad name fails the story at the
    ``with`` with the launch's own error."""
    program = template_game(tmp_path, S="show hana sad with swirl")
    launch = run_launch(program)
    interp = Interpreter(program, launch.namespace)
    interp.new_game(42)
    interp.run(10_000)
    (failed,) = [c for c in interp.take_commands(100) if type(c) is StoryFailed]
    assert isinstance(failed.error, StoryError) and failed.error.code == "E190"
    assert failed.error.line == 6


def test_kind_words():
    from engine.runtime.values import kind_words
    assert kind_words(Dissolve()) == "a transition"
    assert tr.BUILTIN_TRANSITIONS["cut"] is None
