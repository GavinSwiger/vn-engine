"""Helpers for the headless story tests (F03 step 5): write a story folder, load it, launch
it, and run it. ``run_r`` is 06-acceptance §0.5's "Run R"."""

import copy
import logging
import shutil
from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import (Advance, Choose, MinigameDone, Say, StoryEnded,
                                     StoryFailed, WaitDone)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status, story_variables
from engine.runtime.launch import run_launch
from engine.runtime.minigame import headless_outcome
from engine.script import load_story
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.program import Program
from tests.runtime.test_values import type_tree
from tests.script.helpers import template_r

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F03"


def load_files(root: Path, files: dict[str, str]) -> Program:
    """Write ``files`` under ``root/script`` and load them; the load must be clean."""
    script = root / "script"
    for name, text in files.items():
        path = script / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    result = load_story(GamePaths(root.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def load_fixture(root: Path, name: str) -> Program:
    """A ``tests/fixtures/F03/<name>/`` story folder, copied to ``root/script``."""
    shutil.copytree(FIXTURES / name, root / "script")
    result = load_story(GamePaths(root.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def load_r(root: Path, *, S: str | None = None, T: str | None = None) -> Program:
    return load_files(root, {"main.vns": template_r(S=S, T=T)})


def run_r(root: Path, *, S: str | None = None, T: str | None = None, seed: int = 42):
    return run_headless(load_r(root, S=S, T=T), seed=seed)


def sr_f03_28(record: logging.LogRecord) -> bool:
    """True for the INFO records SR-F03-28 adds to every run (F03 step 13): the new-game
    line and, in dev runs, the end of a label that wasn't called. Tests that expect no
    other runtime record leave these out."""
    message = record.getMessage()
    return (record.name == "vn.runtime" and record.levelno == logging.INFO
            and (message.startswith("New game: ") or message.endswith("which wasn't called.")))


def lines(commands) -> list[tuple[str | None, str]]:
    return [(c.name, c.text) for c in commands if type(c) is Say]


def texts(commands) -> list[str]:
    return [c.text for c in commands if type(c) is Say]


def start(program: Program, seed: int = 42, **kwargs) -> Interpreter:
    """Launch, start a new game, and run to the first stop."""
    launch = run_launch(program)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    interp = Interpreter(program, launch.namespace, **kwargs)
    interp.new_game(seed)
    interp.run(10_000)
    return interp


# Story waits (F09 transitions and pauses, F18 cards) ended in a row before a driver gives up:
# far more than any story has between two lines, so a wait nothing answers fails fast.
WAITS_MAX = 1_000


def end_waits(interp: Interpreter, *, limit: int = WAITS_MAX) -> int:
    """End every story wait the story is stopped on, one after another, as headless does
    (``WaitDone`` for ``waiting_for``, then run), until it waits for a line or a menu or
    stops. Returns how many were ended. The one shared answer to story waits for the test
    drivers (``advance``, ``corpus.play``, ``continue_from``); ``AssertionError`` naming the
    wait's statement after ``limit`` waits in a row, so a driver never spins."""
    for count in range(limit + 1):
        if interp.status is not Status.WAITING or interp.waiting_for is None:
            return count
        if count == limit:
            break
        interp.post(WaitDone(interp.waiting_for))
        interp.run(10_000)
    stmt = interp.current
    where = ("an unknown statement" if stmt is None else
             f"{getattr(getattr(stmt, 'file', None), 'ref', '?')}, line "
             f"{getattr(stmt, 'line', '?')} ({stmt.sid})")
    raise AssertionError(f"story stuck on a wait at {where}: {limit:,} story waits in a row "
                         "with no line or menu between them")


def post_test_outcome(interp: Interpreter, current: Minigame) -> None:
    """End the waiting minigame as ``run_headless`` does with no ``finish`` input: post the
    plugin's test outcome (``outcome_for("test", …)``, else its static one) as
    ``MinigameDone``. The interpreter needs the plugin's signature (``minigames=``)."""
    outcome = headless_outcome(interp, current)
    assert outcome is not None, current
    interp.post(MinigameDone(current.sid, interp.minigame_run, outcome.result,
                             outcome.changes))


def advance(interp: Interpreter) -> None:
    """Dismiss the waiting line and run to the next line, menu, or end. At a menu (F07) this
    picks its first pickable choice, as two presses of Space do in the window, so a story
    with menus (the example game since F07 step 5) still plays to its end; at a minigame
    (F23; the example's poem since F24-4) it posts the test outcome (``post_test_outcome``).
    Story waits (F09, F18) before and after are ended by ``end_waits``."""
    end_waits(interp)
    assert interp.status is Status.WAITING
    current = interp.current
    if type(current) is Menu:
        interp.post(Choose(current.sid, interp.choices.waiting.pickable[0]))  # type: ignore
    elif type(current) is Minigame:
        post_test_outcome(interp, current)
    else:
        interp.post(Advance(current.sid))
    interp.run(10_000)
    end_waits(interp)


def checkpoints(interp: Interpreter) -> list:
    """Advance to the end, collecting every checkpoint (the current one first)."""
    out = []
    end_waits(interp)
    while interp.status is Status.WAITING:
        out.append(interp.checkpoint())
        advance(interp)
    return out


def fingerprint(interp: Interpreter) -> tuple:
    """06-acceptance §0.5's fingerprint: ``id(G)``; ``G``'s keys; each story variable's
    value, exact type tree, and ``id()``; the position and call stack; ``dice`` state and
    ``ready``; status, steps, labels entered; held and released commands; the last
    checkpoint; F04's stage and the record of the stage shown; F08's audio; F07's choices,
    kept line, and open menu. "Unchanged" means equal fingerprints before and after."""
    variables = story_variables(interp.G, interp.reserved)
    return (id(interp.G), frozenset(interp.G),
            tuple((k, copy.deepcopy(v), type_tree(v), id(v)) for k, v in variables.items()),
            None if interp.current is None else interp.current.sid,
            [c.sid for c in interp.call_stack], interp.core.state, interp.core.ready,
            interp.status, interp.steps, list(interp.entered), list(interp._held),
            list(interp._released), id(interp.last_checkpoint), interp.last_checkpoint,
            interp.stage, interp._stage_shown, interp._last_prefetch, interp.audio,
            interp.choices, interp.kept_line, interp.menu_open)


def launched(program: Program, **kwargs) -> Interpreter:
    """A launched interpreter with no game started (status IDLE)."""
    launch = run_launch(program)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, **kwargs)


__all__ = ["Advance", "Say", "StoryEnded", "StoryFailed", "advance", "checkpoints",
           "fingerprint", "launched", "lines", "load_files", "load_fixture", "load_r",
           "post_test_outcome", "run_r", "sr_f03_28", "start", "texts"]
