"""Helpers for F17's headless tests (F17 ``06-acceptance.md`` §0.3, §0.4).

- **Template N** (``tests/fixtures/F17/template/``) with its row edits (``replace`` for Rn,
  ``T``, ``drop``): ``load_n`` loads it from a game folder under ``tmp_path``.
- **Run N**: ``bursts(program, "a a a a a a c1 a")`` plays it on an interpreter with 06's
  input notation and returns the interpreter, the commands of each burst (the new game's
  first), and the checkpoint after each burst. ``RUN_N_FULL`` is "Run N full".
- ``sid(program, n)``: the sid of the statement on line n (the menu's for 15–16).
"""

from pathlib import Path

from engine.runtime.commands import Command, NvlPage, Say, ShowMenu
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.state import GameState
from engine.script.program import Program
from tests.runtime.menu_story import ALL, inputs, launched, load_text, step
from tests.runtime.story import end_waits
from tests.script.helpers import F17_TEMPLATE_DIR, template_n

F17 = F17_TEMPLATE_DIR.parent
RUN_N_FULL = "a a a a a a c1 a"            # line 6 to line 23
# The line each checkpoint of Run N full waits at, in order.
RUN_N_LINES = (6, 8, 9, 10, 12, 14, 15, 21, 23)


def load_n(root: Path, **edit) -> Program:
    """Template N with ``edit`` (``replace``, ``T``, ``drop``); the load must be clean."""
    result = load_text(root, template_n(**edit))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def sid(program: Program, line: int) -> str:
    """The sid of the statement on ``line`` of main.vns (a question's is its menu's)."""
    if line == 16:
        line = 15
    found = [s for s in program.iter_statements() if s.line == line]
    assert len(found) == 1, (line, found)
    return found[0].sid


def bursts(program: Program, text: str = RUN_N_FULL, *, interp: Interpreter | None = None,
           seed: int = 42, **kwargs) -> tuple[Interpreter, list[list[Command]], list[GameState]]:
    """Run N: a new game, then each input of ``text``. Returns the interpreter, the commands
    of each burst (the new game's first, then one per input), and the checkpoint after
    each burst. Story waits are ended with ``end_waits``."""
    if interp is None:
        interp = launched(program, **kwargs)
    interp.new_game(seed)
    interp.run(10_000)
    end_waits(interp)
    out = [interp.take_commands(ALL)]
    states = [interp.checkpoint()]
    for answer in inputs(text):
        assert interp.status is Status.WAITING
        step(interp, answer)
        interp.run(10_000)
        end_waits(interp)
        out.append(interp.take_commands(ALL))
        states.append(interp.checkpoint())
    return interp, out, states


def replay(interp: Interpreter, text: str) -> tuple[list[list[Command]], list[GameState]]:
    """Each input of ``text`` on a waiting interpreter: the bursts and checkpoints."""
    out, states = [], []
    for answer in inputs(text):
        step(interp, answer)
        interp.run(10_000)
        end_waits(interp)
        out.append(interp.take_commands(ALL))
        states.append(interp.checkpoint())
    return out, states


def shown(burst: list[Command], program: Program) -> list[tuple]:
    """A burst's ``NvlPage``, ``Say`` and ``ShowMenu`` commands in AC-F17-03's notation:
    ``("nvl", on, lines)``, ``("say", line)``, ``("menu",)``."""
    lines = {s.sid: s.line for s in program.iter_statements()}
    out: list[tuple] = []
    for c in burst:
        if type(c) is NvlPage:
            out.append(("nvl", c.on, c.lines))
        elif type(c) is Say:
            out.append(("say", lines[c.sid]))
        elif type(c) is ShowMenu:
            out.append(("menu",))
    return out


__all__ = ["F17", "RUN_N_FULL", "RUN_N_LINES", "bursts", "load_n", "replay", "shown", "sid"]
