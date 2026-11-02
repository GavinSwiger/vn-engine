"""Helpers for F21's runtime tests (F21 ``06-acceptance.md`` §0.3–§0.4, §5).

- ``store_with(t, rd)``: 06's "Store with ``t=(…)``, ``rd=(…)``".
- ``load_c(root, S=, T=, dev=)``: Template C (``template_c``) loaded; ``load_result`` keeps the
  ``LoadResult`` (a release load by default, so the template's tips give no W142).
- ``run_c(program, store, …)``: Run H, ``run_headless(program, seed=42, persistent=store)``.
- ``launched``/``started``: an interpreter on ``store`` (``started`` runs to "Start.").
- ``to_text(interp, text)``: advance live until the waiting line is ``text``; the commands
  released on the way (each burst's first command after the previous line).
- ``walk()``: the *Paper Lanterns* walkthrough fixture (``walk/``), loaded once.
- ``CA(kind, name, title)``: 06's ``CA``.
"""

from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import Advance, Choose, CodexAdded, Command, Say
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.script import load_story
from engine.script.loader import LoadOptions
from engine.script.menu import Menu
from engine.script.program import Program
from tests.runtime.story import end_waits
from tests.script.helpers import template_c

F21 = Path(__file__).resolve().parents[1] / "fixtures" / "F21"
ALL = 1 << 30
TITLES = {"lanterns": "Paper Lanterns", "river_god": "The River God",
          "red_lantern": "Red Lantern", "brass_key": "Brass Key"}
_programs: dict[str, Program] = {}


def CA(kind: str, name: str, title: str | None = None) -> CodexAdded:
    return CodexAdded(kind, name, TITLES[name] if title is None else title)


def store_with(t=(), rd=()) -> PersistentStore:
    return PersistentStore.with_data(unlocks={"tip": list(t), "codex_read": list(rd)})


def load_result(root: Path, *, S: str | None = None, T: str | None = None,
                dev: bool = False):
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    (script / "main.vns").write_bytes(template_c(S=S, T=T).encode("utf-8"))
    return load_story(GamePaths(root.resolve()), LoadOptions(dev=dev))


def load_c(root: Path, *, S: str | None = None, T: str | None = None,
           dev: bool = False) -> Program:
    result = load_result(root, S=S, T=T, dev=dev)
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def run_c(program: Program, store: PersistentStore | None = None, **kwargs) -> list[Command]:
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
    end_waits(interp)
    return interp


def step(interp: Interpreter, choice: int = 1) -> None:
    current = interp.current
    assert interp.status is Status.WAITING and current is not None, interp.status
    if type(current) is Menu:
        interp.post(Choose(current.sid, interp.choices.waiting.pickable[choice - 1]))
    else:
        interp.post(Advance(current.sid))
    interp.run(10_000)
    end_waits(interp)


def text_of(interp: Interpreter) -> str | None:
    current = interp.current
    return getattr(current, "text", None) if interp.status is Status.WAITING else None


def to_text(interp: Interpreter, text: str, *, choice: int = 1) -> list[Command]:
    """Step live until the waiting line's text is ``text``; every command released."""
    out = interp.take_commands(ALL)
    for _ in range(200):
        if text_of(interp) == text:
            return out
        step(interp, choice)
        out += interp.take_commands(ALL)
    raise AssertionError(f"never reached {text!r}")


def added(commands: list[Command]) -> list[CodexAdded]:
    return [c for c in commands if type(c) is CodexAdded]


def said(commands: list[Command]) -> list[str]:
    return [c.text for c in commands if type(c) is Say]


def fixture(name: str) -> Program:
    """``tests/fixtures/F21/<name>/``, loaded once per session (release load)."""
    program = _programs.get(name)
    if program is None:
        result = load_story(GamePaths((F21 / name).resolve()), LoadOptions(dev=False))
        assert result.program is not None, [e.format() for e in result.errors]
        program = _programs[name] = result.program
    return program


def walk() -> Program:
    return fixture("walk")


# The walkthrough's inputs: three lines, then the bridge menu's first choice.
WALK_INPUTS = ["advance"] * 3 + ["choose 1"]
