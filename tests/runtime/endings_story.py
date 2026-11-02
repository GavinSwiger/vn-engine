"""Helpers for F19's runtime tests (F19 ``06-acceptance.md`` §0.3–§0.4, §5).

- ``store_with(e, r)``: 06's "Store with ``e=(…)``, ``r=(…)``".
- ``load_e(root, S=, T=, replace=)``: Template R (``template_e``) loaded clean.
- ``run_e(program, store, …)``: Run R, ``run_headless(program, seed=42, persistent=store)``.
- ``launched(program, store, …)``: an interpreter launched on ``store`` (no game started);
  ``started`` runs it to the first line.
- ``walk()``: the *Paper Lanterns* walkthrough fixture (``walk/``), loaded once.
"""

from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import Command, StoryEnded
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.script import load_story
from engine.script.program import Program
from tests.runtime.story import load_files
from tests.script.helpers import template_e

F19 = Path(__file__).resolve().parents[1] / "fixtures" / "F19"
_programs: dict[str, Program] = {}


def store_with(e=(), r=()) -> PersistentStore:
    return PersistentStore.with_data(unlocks={"ending": list(e), "route": list(r)})


def load_e(root: Path, *, S: str | None = None, T: str | None = None,
           replace: dict[int, str] | None = None) -> Program:
    return load_files(root, {"main.vns": template_e(S=S, T=T, replace=replace)})


def run_e(program: Program, store: PersistentStore | None = None, **kwargs) -> list[Command]:
    if store is None:
        store = PersistentStore(identity_scheme=program.identity_scheme)
    return run_headless(program, seed=42, persistent=store, **kwargs)


def launched(program: Program, store: PersistentStore | None = None, **kwargs) -> Interpreter:
    if store is None:
        store = PersistentStore(identity_scheme=program.identity_scheme)
    launch = run_launch(program, persistent=store, dev=kwargs.get("dev", False))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, persistent=store, **kwargs)


def started(program: Program, store: PersistentStore | None = None, **kwargs) -> Interpreter:
    interp = launched(program, store, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    return interp


def fixture(name: str) -> Program:
    """``tests/fixtures/F19/<name>/``, loaded once per session (a ``Program`` is immutable)."""
    program = _programs.get(name)
    if program is None:
        result = load_story(GamePaths((F19 / name).resolve()))
        assert result.program is not None, [e.format() for e in result.errors]
        program = _programs[name] = result.program
    return program


def walk() -> Program:
    return fixture("walk")


def drive(program: Program, store: PersistentStore | None = None, *, choices=(),
          wait_pumps: int = 0, on_line=None, setup=None, **kwargs):
    """06 §0.3's Driver D: ``RuntimeStoryDriver`` over a launched interpreter, a fake clock
    (one slice runs the story to its next stop), ``Advance`` at each line, ``choose N`` from
    ``choices`` at each menu (the run stops at a menu once they run out), and each story
    wait answered with ``WaitDone`` after ``wait_pumps`` pumps with no event (0: at once,
    finished early; more: answered at its length). ``on_line(interp)`` runs at each line or
    menu before the input; ``setup(interp)`` once, before the new game. Returns
    ``(interp, commands)``."""
    from engine.app.story import RuntimeStoryDriver
    from engine.runtime.commands import Advance, Choose, WaitDone
    from engine.script.menu import Menu

    interp = launched(program, store, **kwargs)
    if setup is not None:
        setup(interp)
    driver = RuntimeStoryDriver(interp, clock=lambda: 0.0, fixed_seed=42)
    driver.new_game()
    out: list[Command] = []
    picks = iter(choices)
    for _ in range(100_000):
        out.extend(driver.pump(1 << 30))
        if interp.busy or interp.released:
            continue
        if interp.status is not Status.WAITING:
            break
        if interp.waiting_for is not None:
            for _ in range(wait_pumps):
                out.extend(driver.pump(1 << 30))
            driver.post(WaitDone(interp.waiting_for))
            continue
        if on_line is not None:
            on_line(interp)
        current = interp.current
        if type(current) is Menu:
            n = next(picks, None)
            if n is None:
                break
            driver.post(Choose(current.sid, interp.choices.waiting.pickable[n - 1]))
        else:
            driver.post(Advance(current.sid))
    return interp, out


def ends(commands: list[Command], interp: Interpreter | None = None) -> bool:
    """06 §0.3's "Ends": ``StoryEnded`` last (and, given the interpreter, ENDED with no
    current statement)."""
    if not commands or type(commands[-1]) is not StoryEnded:
        return False
    return interp is None or (interp.status is Status.ENDED and interp.current is None)


__all__ = ["F19", "drive", "ends", "fixture", "launched", "load_e", "run_e", "started",
           "store_with", "walk"]
