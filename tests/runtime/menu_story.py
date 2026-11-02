"""Helpers for F07's tests (F07 ``06-acceptance.md`` §0.4, §5).

- **Template M** (``tests/fixtures/F07/template/``) with its row edits (``M``, ``S``, ``T``,
  ``Rn`` as ``replace``): ``load_m`` loads it from a game folder under ``tmp_path``.
- **Run M**: ``run_m(program, "a c2")`` is ``run_headless(program, seed=42, inputs=…)`` with
  06's input notation (``a`` advance, ``cN`` choose N); ``play`` does the same on an
  ``Interpreter`` it returns, for assertions on ``G`` and ``choices``.
- ``K(t)`` (a choice's key) and ``sid_at(program, n)`` (the sid of the statement on line n).
- ``lines(commands)``: the shown texts of the ``Say`` commands (bodies resolved).
"""

import shutil
from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import Advance, Choose, Command, Say, ShowMenu
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.menu import plain_text
from engine.script import load_story
from engine.script.loader import LoadResult
from engine.script.menu import Menu, choice_key
from engine.script.program import Program
from tests.script.helpers import template_m

F07 = Path(__file__).resolve().parents[1] / "fixtures" / "F07"
ALL = 1 << 30


def write_game(root: Path, text: str, config: str = "") -> GamePaths:
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text(config, encoding="utf-8")
    (script / "main.vns").write_bytes(text.encode("utf-8"))
    return GamePaths(root.resolve())


def load_text(root: Path, text: str) -> LoadResult:
    return load_story(write_game(root, text))


def load_m_result(root: Path, **edit) -> LoadResult:
    return load_text(root, template_m(**edit))


def load_m(root: Path, **edit) -> Program:
    """Template M with ``edit`` (``M``, ``S``, ``T``, ``replace``); the load must be clean."""
    result = load_m_result(root, **edit)
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def load_fixture(root: Path, name: str, *, drop: tuple[int, ...] = (),
                 add: dict[int, str] | None = None) -> Program:
    """``tests/fixtures/F07/<name>/``, with lines ``drop`` removed and ``add`` (line number →
    text) inserted before the given lines."""
    lines = (F07 / name / "script" / "main.vns").read_text(encoding="utf-8").splitlines()
    out = []
    for number, line in enumerate(lines, 1):
        if add and number in add:
            out.extend(add[number].split("\n"))
        if number not in drop:
            out.append(line)
    result = load_text(root, "\n".join(out) + "\n")
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def copy_template(root: Path) -> Path:
    return Path(shutil.copytree(F07 / "template", root))


def inputs(text: str) -> list[str]:
    """06 §0.4's notation: ``a`` → ``advance``, ``cN`` → ``choose N``; anything else as is."""
    out = []
    for word in text.split():
        if word == "a":
            out.append("advance")
        elif word[:1] == "c" and word[1:].isdigit():
            out.append(f"choose {word[1:]}")
        else:
            out.append(word)
    return out


def run_m(program: Program, text: str = "", **kwargs) -> list[Command]:
    return run_headless(program, seed=42, inputs=inputs(text), **kwargs)


def launched(program: Program, **kwargs) -> Interpreter:
    launch = run_launch(program)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, **kwargs)


def play(program: Program, text: str = "", *, seed: int = 42, to_end: bool = True,
         **kwargs) -> tuple[Interpreter, list[Command]]:
    """Run M on an interpreter (as ``run_headless``, valid inputs only): returns it and
    the commands. When the inputs run out it stops at a menu, and also at a line unless
    ``to_end``."""
    interp = launched(program, **kwargs)
    interp.new_game(seed)
    commands: list[Command] = []
    pending = iter(inputs(text))
    while True:
        if interp.status is Status.RUNNING:
            interp.run(10_000)
        commands.extend(interp.take_commands(ALL))
        if interp.status is not Status.WAITING:
            break
        answer = next(pending, None)
        if answer is None and (not to_end or type(interp.current) is Menu):
            break
        step(interp, answer)
    commands.extend(interp.take_commands(ALL))
    return interp, commands


def step(interp: Interpreter, answer: str | None) -> None:
    """Post one input's event (``None``: advance)."""
    current = interp.current
    if type(current) is Menu:
        n = int(answer.removeprefix("choose "))  # type: ignore[union-attr]
        interp.post(Choose(current.sid, interp.choices.waiting.pickable[n - 1]))
    else:
        interp.post(Advance(current.sid))


def go(interp: Interpreter, text: str) -> list[Command]:
    """Post each input of ``text`` and run after each; the commands released."""
    out: list[Command] = []
    for answer in inputs(text):
        step(interp, answer)
        interp.run(10_000)
        out.extend(interp.take_commands(ALL))
    return out


def K(text: str) -> str:
    return choice_key(text)


def sid_at(program: Program, line: int) -> str:
    """The sid of the statement on ``line`` of main.vns."""
    found = [s for s in program.iter_statements() if s.line == line]
    assert len(found) == 1, (line, found)
    return found[0].sid


def menu_at(program: Program, line: int) -> Menu:
    menu = program.get(sid_at(program, line))
    assert type(menu) is Menu
    return menu


def lines(commands) -> list[str]:
    """The shown text of each ``Say`` (its resolved body)."""
    return [plain_text(c.body) for c in commands if type(c) is Say]


def menus(commands) -> list[ShowMenu]:
    return [c for c in commands if type(c) is ShowMenu]


def shown(cmd: ShowMenu) -> list[tuple[str, str, bool]]:
    """A ``ShowMenu``'s choices as (key, text, locked)."""
    return [(c.key, plain_text(c.body), c.locked) for c in cmd.choices]


__all__ = ["ALL", "F07", "K", "copy_template", "go", "inputs", "launched", "lines",
           "load_fixture", "load_m", "load_m_result", "load_text", "menu_at", "menus", "play",
           "run_m", "shown", "sid_at", "step", "write_game"]
