"""F32 s3 — ``ui`` lines at run time (F32 ``06-acceptance.md`` AC-F32-09, AC-F32-10; ``04``
§4.3, §5.2, §9; 07 I-1, G1), Run H on Template U and ``walk/`` (``ui_story.py``), and the step 3
headless golden (06 §9 Step 3 milestone)."""

import ast
import json
import logging

from engine.persist import saves
from engine.runtime import ui as runtime_ui
from engine.runtime.commands import (Advance, AudioRestore, DeleteSaves, NvlPage, Say,
                                     ShowStage, StepBack, StepForward, UiBlocks, UiStyle)
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, RestoreResult
from engine.runtime.launch import run_launch
from engine.runtime.ui import EMPTY_UI, UiState
from engine.script import ui as script_ui
from engine.script.messages import format_message
from tests.persist.save_support import make_save
from tests.runtime import corpus, fourthwall_story, glitch_story
from tests.runtime.effects_story import of_type, take_all, write_game
from tests.runtime.ui_story import (F32, GOLDEN, R, golden_text, launched, load, run_h,
                                    template_u, walk)

UI_COMMANDS = (UiStyle, UiBlocks, DeleteSaves)


def _before_l6(commands) -> list:
    """What Run H released after "Hello." up to L6's ``Say``."""
    says = [i for i, c in enumerate(commands) if type(c) is Say]
    return commands[says[0] + 1:says[1] + 1]


def test_ac_f32_09_commands_holding_and_headless_wipes(tmp_path, caplog):
    rows = [
        ("ui style ashes", [UiStyle("ashes")]),
        ("ui style off", [UiStyle(None)]),
        ("ui style ashes⏎ui style calm", [UiStyle("ashes"), UiStyle("calm")]),
        ('ui saving off "R"', [UiBlocks(True, "R", False, None)]),
        ("ui saving off⏎ui loading off", [UiBlocks(True, None, False, None),
                                          UiBlocks(True, None, True, None)]),
        ("ui saving on", [UiBlocks(False, None, False, None)]),
    ]
    plain = run_h(template_u(tmp_path / "plain"))
    for n, (S, held) in enumerate(rows):
        commands = run_h(template_u(tmp_path / str(n), S=S))
        burst = _before_l6(commands)
        assert burst[:-1] == held and type(burst[-1]) is Say, S
        assert len(of_type(commands, Say)) == len(of_type(plain, Say))    # no checkpoint added
    game = tmp_path / "wipe"
    program = template_u(game, S="ui delete saves")
    files = sorted(game.rglob("*"))
    with caplog.at_level(logging.INFO, logger="vn"):
        burst = _before_l6(run_h(program))
    assert burst[:-1] == [DeleteSaves()]
    assert [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("ui delete saves:")] == [runtime_ui.DELETE_PREVIEW_TEXT]
    assert sorted(game.rglob("*")) == files

    # L6's checkpoint holds the new ui; New Game starts empty and holds no Ui* command.
    interp = launched(template_u(tmp_path / "cp", S='ui style ashes⏎ui saving off "R"'))
    interp.new_game(42)
    interp.run(10_000)
    assert interp.checkpoint().ui is EMPTY_UI
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.checkpoint().ui == UiState("ashes", True, "R") == interp.ui
    take_all(interp)
    interp.new_game(42)
    interp.run(10_000)
    assert interp.checkpoint().ui is EMPTY_UI and not of_type(take_all(interp), *UI_COMMANDS)

    # The older corpora release none of the three.
    example = corpus.example_program()
    assert not of_type(run_headless(example, seed=42, image_files=corpus.example_images()),
                       *UI_COMMANDS)
    assert not of_type(glitch_story.run_h(glitch_story.walk()), *UI_COMMANDS)
    assert not of_type(fourthwall_story.run_h(fourthwall_story.walk()), *UI_COMMANDS)
    assert not of_type(plain, *UI_COMMANDS)
    for module in (script_ui, runtime_ui):
        tree = ast.parse(open(module.__file__, encoding="utf-8").read())
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not {m for m in names if m and (m.split(".")[0] in ("pygame", "time", "random")
                                               or m.startswith("engine.app"))}, module.__name__


def test_the_headless_golden_with_all_three_commands():
    assert GOLDEN.read_bytes() == golden_text().encode("ascii")
    kinds = [c["type"] for c in json.loads(GOLDEN.read_text(encoding="ascii"))["commands"]]
    assert {"UiStyle", "UiBlocks", "DeleteSaves"} <= set(kinds)


def _advance(interp) -> list:
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    return take_all(interp)


def _step(interp, event) -> list:
    interp.post(event)
    interp.run(10_000)
    while interp.busy:
        interp.run(10_000)
    return take_all(interp)


def _loaded(program, state, interp=None) -> list:
    interp = launched(program) if interp is None else interp
    assert interp.restore(state).result is RestoreResult.OK
    return take_all(interp)


def _ui(commands) -> list:
    return of_type(commands, UiStyle, UiBlocks)


def test_ac_f32_10_restore_rollback_and_forward(tmp_path, caplog):
    program = walk()
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    take_all(interp)
    u = [interp.checkpoint()]
    for _ in range(4):
        _advance(interp)
        u.append(interp.checkpoint())
    u1, u2, u3, u4, u5 = u
    assert [s.ui for s in (u1, u2, u3, u4)] == [
        EMPTY_UI, UiState("ashes", True, R), UiState("ashes", True, R, True, None), EMPTY_UI]

    # Save at U3, load from the title (a fresh interpreter: nothing shown).
    read = saves.parse_full(make_save(u3), game_id=None)
    burst = _loaded(program, read.state)
    assert [type(c) for c in burst[:6]] == [AudioRestore, NvlPage, ShowStage, UiStyle,
                                            UiBlocks, Say]
    assert burst[3:5] == [UiStyle("ashes"), UiBlocks(True, R, True, None)] and burst[2].restored
    assert burst[5].text == "Don't look back."
    # A U1 save: with U3 shown, both reset; from the title, neither.
    live = launched(program)
    _loaded(program, u3, live)
    assert _ui(_loaded(program, u1, live)) == [UiStyle(None), UiBlocks(False, None, False, None)]
    assert not _ui(_loaded(program, u1))

    # Rollback U5 → U4, forward to U5: the forward chain deletes nothing; a live advance does.
    assert not of_type(_step(interp, StepBack(1)), DeleteSaves)
    assert not of_type(_step(interp, StepForward(1)), DeleteSaves)
    assert interp.checkpoint() == u5
    _step(interp, StepBack(1))
    assert of_type(_advance(interp), DeleteSaves) == [DeleteSaves()]
    # Rollback U5 → U4 → U3 → U2 → U1: each landing by 04 §4.3's rule.
    wants = [[],                                                         # U4: none shown
             [UiStyle("ashes"), UiBlocks(True, R, True, None)],          # U3
             [UiStyle("ashes"), UiBlocks(True, R, False, None)],         # U2
             [UiStyle(None), UiBlocks(False, None, False, None)]]        # U1
    for want in wants:
        landing = _step(interp, StepBack(1))
        assert _ui(landing) == want and not of_type(landing, DeleteSaves)
    assert interp.ui is EMPTY_UI
    # Forward U1 → U3 quietly: the landing sends U3's style and blocks.
    assert _ui(_step(interp, StepForward(2))) == [UiStyle("ashes"),
                                                  UiBlocks(True, R, True, None)]
    # Forward U3 → U4 (the re-run turns everything off): the landing still resets the shown.
    assert _ui(_step(interp, StepForward(1))) == [UiStyle(None),
                                                  UiBlocks(False, None, False, None)]

    # The U3 save after a patch removed [style.ashes] and its lines: W205 once, blocks kept.
    text = (F32 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")
    patched = load(write_game(tmp_path / "patched", text.replace("    ui style ashes\n", "")),
                   frozenset(("calm",)))
    with caplog.at_level(logging.WARNING, logger="vn"):
        burst = _loaded(patched, read.state)
    w205 = format_message("W205", ("ashes",))
    assert w205 == ('this save uses the UI style "ashes", which config.toml no longer has, so '
                    "the normal look is used.")
    assert [r.getMessage() for r in caplog.records if w205 in r.getMessage()] == [w205]
    assert of_type(burst, UiStyle) == [] and of_type(burst, UiBlocks) == [
        UiBlocks(True, R, True, None)]

    # New Game after U3: nothing held, the first checkpoint empty.
    after = launched(program)
    _loaded(program, u3, after)
    after.new_game(42)
    after.run(10_000)
    assert after.checkpoint().ui is EMPTY_UI and not _ui(take_all(after))
    # An F39-style restore against a reloaded Program is a load.
    assert _loaded(walk(), read.state) == _loaded(program, read.state)

    # F11's pre-F32 saves (the example's): EMPTY_UI, nothing held.
    example = corpus.example_program()
    for path in sorted((F32.parent / "F11" / "example_saves").glob("*.vnsave"))[:2]:
        old = saves.parse_full(path.read_bytes(), game_id=None)
        assert old.status is saves.SlotStatus.OK and old.state.ui is EMPTY_UI
        loader = Interpreter(example, run_launch(
            example, images=ImageSource.from_files(corpus.example_images())).namespace)
        assert not of_type(_loaded(example, old.state, loader), *UI_COMMANDS)
