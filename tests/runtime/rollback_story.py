"""Helpers for F14's runtime tests (F14 ``06-acceptance.md`` §0 notation, §5 fixtures).

- **Run K** (``steps/``, seed 42): ``run_k("D2")`` plays the "Wade in" path live to the named
  step and returns the interpreter and the snapshots ``take_checkpoint`` built on the way
  (``k["A"]`` … , the spy of 06 §0). Steps: ``K_PATH`` = A B C M D1 D2 S F.
- ``load_form(program, state)``: the burst ``restore(state)`` releases in a fresh interpreter
  launched from the same program; ``lands_on`` checks 06's "lands on X".
- ``walls/``, ``loop/``, ``diverge/``: the other fixtures, played the same way with
  ``play_to``.
- ``forward(interp, n)``: post ``StepForward(n)`` and run the chain to its landing (``busy``);
  ``restore_spy``: TR-F14-06's check that a landing never restores a state after ``cursor``.
"""

from pathlib import Path

from engine.runtime.commands import Advance, Choose, Command, StepBack, StepForward
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, RestoreResult, Status
from engine.runtime.launch import run_launch
from engine.runtime.state import GameState
from engine.script.menu import Menu
from engine.script.program import Program
from tests.runtime.effects_story import load_game, take_all

F14 = Path(__file__).resolve().parents[1] / "fixtures" / "F14"
IMG14 = ("images/river.png", "images/hana/happy.png", "images/hana/worried.png")
K_PATH = ("A", "B", "C", "M", "D1", "D2", "S", "F")

_programs: dict[str, Program] = {}


def fixture(name: str) -> Program:
    """``tests/fixtures/F14/<name>/``, loaded once per test session (a ``Program`` is
    immutable)."""
    program = _programs.get(name)
    if program is None:
        program = _programs[name] = load_game(F14 / name)
    return program


def launched(program: Program, **kwargs) -> Interpreter:
    launch = run_launch(program, images=ImageSource.from_files(IMG14))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, **kwargs)


def step(interp: Interpreter, choice: int = 1) -> None:
    """One live input at the waiting step: ``Advance`` at a line, ``choose choice`` at a
    menu; then run to the next wait."""
    current = interp.current
    assert interp.status is Status.WAITING and current is not None, interp.status
    if type(current) is Menu:
        interp.post(Choose(current.sid, interp.choices.waiting.pickable[choice - 1]))
    else:
        interp.post(Advance(current.sid))
    interp.run(10_000)


def start(program: Program, *, seed: int = 42, **kwargs) -> Interpreter:
    interp = launched(program, **kwargs)
    interp.new_game(seed)
    interp.run(10_000)
    return interp


def play_to(interp: Interpreter, text: str, *, choice: int = 1) -> None:
    """Step live until the waiting step's line (or question) starts with ``text``."""
    for _ in range(200):
        if shown_text(interp).startswith(text):
            return
        step(interp, choice)
    raise AssertionError(f"never reached {text!r}")


def shown_text(interp: Interpreter) -> str:
    current = interp.current
    if type(current) is Menu:
        return current.question.text if current.question is not None else ""
    return getattr(current, "text", "")


def run_k(stop: str = "F", *, depth: int = 100, seed: int = 42
          ) -> tuple[Interpreter, dict[str, GameState]]:
    """Run K to ``stop`` (06 §0: K@X), with each step's first-pass snapshot."""
    interp = start(fixture("steps"), rollback_steps=depth, seed=seed)
    k = {"A": interp.checkpoint()}
    for name in K_PATH[1:K_PATH.index(stop) + 1]:
        step(interp)
        k[name] = interp.checkpoint()
    take_all(interp)
    return interp, k


def load_form(program: Program, state: GameState) -> list[Command]:
    """The commands ``restore(state)`` releases in a fresh interpreter (06 §0)."""
    fresh = launched(program)
    assert fresh.restore(state).result is RestoreResult.OK
    return take_all(fresh)


def lands_on(interp: Interpreter, released: list[Command], state: GameState) -> bool:
    """06 §0 "lands on X": the released commands are the load-form burst of ``state``, the
    story waits, and ``checkpoint() == state``."""
    return (released == load_form(interp.program, state) and interp.status is Status.WAITING
            and interp.checkpoint() == state)


def back(interp: Interpreter, n: int = 1) -> list[Command]:
    interp.post(StepBack(n))
    return take_all(interp)


def forward(interp: Interpreter, n: int = 1, *, chunk: int = 10_000) -> list[Command]:
    """``StepForward(n)``, then ``run(chunk)`` while the interpreter is ``busy`` (the
    driver's loop), and every command released."""
    interp.post(StepForward(n))
    while interp.busy:
        interp.run(chunk)
    return take_all(interp)


def restore_spy(calls: list[bool]):
    """A stand-in for ``Interpreter.restore`` that records, for each landing, whether the
    restored state is at an index ≤ ``cursor`` (TR-F14-06)."""
    real = Interpreter.restore

    def spy(self, state, **kwargs):
        if kwargs.get("landing"):
            t = self.timeline
            index = next(i for i, s in enumerate(t.states) if s is state)
            calls.append(index <= t.cursor)
        return real(self, state, **kwargs)
    return spy


def where(interp: Interpreter, k: dict[str, GameState]) -> str:
    """The name of the step ``interp`` waits at (by position and call stack)."""
    state = interp.checkpoint()
    return next(name for name, s in k.items()
                if s.position == state.position and s.call_stack == state.call_stack)
