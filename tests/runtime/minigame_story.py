"""Helpers for F23's runtime tests (F23 ``06-acceptance.md`` §0.3, §5).

- ``load_m(root, S=, T=, replace=, sigs=)``: Template M (``template_g``) loaded with
  ``LoadOptions(minigames=sigs)`` (a release load; the load must be clean).
- ``run_m(program, inputs, sigs=, **kw)``: **Run H**, ``run_headless(program, seed=42,
  minigames=sigs, inputs=…)``.
- ``at_a(program, sigs=, **kw)``: **Driver D**'s start: an interpreter (``minigames=sigs``)
  waiting at A (line 8). The runtime tests drive the interpreter directly with ``post`` and
  ``run``, which is what ``RuntimeStoryDriver.pump`` does per frame (no App here).
- ``step(interp)``: Advance the waiting line (or pick a menu's first choice) and run on.
- ``to_line(interp, line)``: step until the story waits at script line ``line``; every
  command released on the way.
- ``finish(interp, result, changes=(), *, run=None, sid=None)``: post ``MinigameDone`` for the
  waiting minigame (or the given ``run``/``sid``), run on; the commands released.
- ``said(commands)``: each ``Say``'s shown text (its body's plain text).
"""

from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import (Advance, Choose, Command, MinigameDone, Say,
                                     StartMinigame)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.script import load_story
from engine.script.loader import LoadOptions
from engine.script.menu import Menu
from engine.script.program import Program
from tests.fixtures.F23.sigs import SIGS
from tests.runtime.story import end_waits
from tests.script.helpers import template_g

ALL = 1 << 30
LINE_A, LINE_M, LINE_B, LINE_C = 8, 9, 10, 12


def load_m(root: Path, *, S: str | None = None, T: str | None = None,
           replace: dict[int, str] | None = None, sigs=SIGS) -> Program:
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    (script / "main.vns").write_bytes(template_g(S=S, T=T, replace=replace).encode("utf-8"))
    result = load_story(GamePaths(root.resolve()), LoadOptions(dev=False, minigames=sigs))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def run_m(program: Program, inputs=(), *, sigs=SIGS, **kwargs) -> list[Command]:
    return run_headless(program, seed=kwargs.pop("seed", 42), minigames=sigs, inputs=inputs,
                        **kwargs)


def launched(program: Program, *, sigs=SIGS, store: PersistentStore | None = None,
             **kwargs) -> Interpreter:
    if store is None:
        store = PersistentStore(identity_scheme=program.identity_scheme)
    launch = run_launch(program, persistent=store)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, persistent=store, minigames=sigs, **kwargs)


def at_a(program: Program, *, sigs=SIGS, seed: int = 42, **kwargs) -> Interpreter:
    interp = launched(program, sigs=sigs, **kwargs)
    interp.new_game(seed)
    interp.run(10_000)
    end_waits(interp)
    interp.take_commands(ALL)
    return interp


def step(interp: Interpreter) -> None:
    current = interp.current
    assert interp.status is Status.WAITING and current is not None, interp.status
    if type(current) is Menu:
        interp.post(Choose(current.sid, interp.choices.waiting.pickable[0]))
    else:
        interp.post(Advance(current.sid))
    interp.run(10_000)
    end_waits(interp)


def to_line(interp: Interpreter, line: int) -> list[Command]:
    out = interp.take_commands(ALL)
    for _ in range(50):
        if interp.status is Status.WAITING and interp.current.line == line:
            return out
        step(interp)
        out += interp.take_commands(ALL)
    raise AssertionError(f"never reached line {line}")


def start_of(commands: list[Command]) -> StartMinigame:
    found = [c for c in commands if type(c) is StartMinigame]
    assert len(found) == 1, commands
    return found[0]


def finish(interp: Interpreter, result: object, changes: tuple = (), *, run: int | None = None,
           sid: str | None = None) -> list[Command]:
    interp.post(MinigameDone(interp.current.sid if sid is None else sid,
                             interp.minigame_run if run is None else run, result, changes))
    interp.run(10_000)
    end_waits(interp)
    return interp.take_commands(ALL)


def said(commands: list[Command]) -> list[str]:
    return ["".join(span.text for span in c.body.plain()) for c in commands if type(c) is Say]


__all__ = ["ALL", "LINE_A", "LINE_B", "LINE_C", "LINE_M", "at_a", "finish", "launched",
           "load_m", "run_m", "said", "start_of", "step", "to_line"]
