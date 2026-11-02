"""Helpers for F09's headless tests (F09 ``06-acceptance.md`` §0.2, §0.4, §5).

- **Run H** (§0.2): ``run_headless(program, seed=42, image_files=IMG9)``, which advances at
  every line and ends every wait itself (C3).
- **Template F** (§0.4) and the fixtures of §5 under ``tests/fixtures/F09/``.
- ``bursts``: the released commands split at each burst's end (a checkpoint command with its
  ``PrefetchImages``, a ``StoryWait``, or the story's end).
"""

from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import (Advance, Command, PrefetchImages, Say, ShowMenu,
                                     StoryEnded, StoryFailed, StoryWait)
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import LaunchResult, run_launch
from engine.script.loader import load_story
from engine.script.program import Program
from tests.script.helpers import template_f

F09 = Path(__file__).resolve().parents[1] / "fixtures" / "F09"

# 06 §0.4 IMG9 (refs only: headless runs read no image).
IMG9 = ("images/bg/ember.png", "images/bg/sea.png", "images/bg/river.png",
        "images/hana/happy.png", "images/hana/sad.png", "images/daichi/grin.png")


def write_game(root: Path, text: str) -> Path:
    script = root / "script"
    script.mkdir(parents=True, exist_ok=True)
    (script / "main.vns").write_bytes(text.encode("utf-8"))
    return root


def load_game(root: Path) -> Program:
    result = load_story(GamePaths(root.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def template_game(root: Path, *, S: str | None = None, T: str | None = None,
                  replace: dict[int, str] | None = None) -> Program:
    """Template F with the row's edit, loaded."""
    return load_game(write_game(root, template_f(S=S, T=T, replace=replace)))


def story_game(root: Path, lines: list[str], *, top: str = "", after: str = "") -> Program:
    """``label start:`` holding ``lines`` (each after 4 more spaces), after ``define hana``
    and ``top``; ``after`` (more labels) follows."""
    body = "".join("    " + line + "\n" for line in lines)
    return load_game(write_game(root, f'define hana = Character("Hana")\n{top}label start:\n'
                                      + body + after))


def fixture(name: str) -> Program:
    return load_game(F09 / name)


def run_h(program: Program, **kwargs) -> list[Command]:
    return run_headless(program, seed=42, image_files=IMG9, **kwargs)


def launch_h(program: Program) -> LaunchResult:
    """The launch run H does (phase 5 with the IMG9 stand-in)."""
    return run_launch(program, images=ImageSource.from_files(IMG9))


def launched(program: Program, **kwargs) -> Interpreter:
    launch = launch_h(program)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, **kwargs)


def take_all(interp: Interpreter) -> list[Command]:
    return interp.take_commands(1 << 30)


def started(program: Program, **kwargs) -> tuple[Interpreter, list[Command]]:
    interp = launched(program, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    return interp, take_all(interp)


def run_to_wait(interp: Interpreter) -> list[Command]:
    """Run until the story waits at a ``StoryWait`` (lines advanced), and return what was
    released on the way."""
    out: list[Command] = []
    while interp.waiting_for is None:
        assert interp.status is Status.WAITING, interp.status
        interp.post(Advance(interp.current.sid))  # type: ignore[union-attr]
        interp.run(10_000)
        out += take_all(interp)
    return out


_ENDS = (Say, ShowMenu, StoryWait, StoryEnded, StoryFailed)


def bursts(commands: list[Command]) -> list[list[Command]]:
    """``commands`` split after each burst's last command: a ``StoryWait``, the story's end,
    or a checkpoint command (``Say`` not followed by ``ShowMenu``, ``ShowMenu``) with its
    ``PrefetchImages``."""
    out: list[list[Command]] = [[]]
    for i, c in enumerate(commands):
        out[-1].append(c)
        nxt = commands[i + 1] if i + 1 < len(commands) else None
        if type(c) is Say and type(nxt) is ShowMenu:
            continue
        if type(c) in _ENDS:
            if type(nxt) is PrefetchImages:
                continue
            out.append([])
        elif type(c) is PrefetchImages:
            out.append([])
    return [b for b in out if b]


def of_type(commands: list[Command], *types: type) -> list[Command]:
    return [c for c in commands if type(c) in types]


# --- The step 1 headless golden (06 §9 Step 1 milestone) ----------------------------------------

GOLDEN = F09 / "goldens" / "all_headless.json"


def golden_text() -> str:
    """``all/`` played by run H, as F03's canonical JSON (``tests.runtime.corpus``): every
    command with its non-default fields, waits included."""
    from tests.runtime.corpus import canon, dumps
    commands = run_h(fixture("all"))
    return dumps({"fixture": "all", "seed": 42, "image_files": list(IMG9),
                  "commands": canon(commands)})


def main(argv: list[str]) -> int:
    """``python -m tests.runtime.effects_story --write-golden``: (re)write ``GOLDEN``, only
    when a change to ``all/`` or to a command is meant to change it."""
    text = golden_text()
    if "--write-golden" in argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(text.encode("ascii"))
        print(f"wrote {GOLDEN}")
        return 0
    same = GOLDEN.exists() and GOLDEN.read_bytes() == text.encode("ascii")
    print("the golden is up to date" if same else "the golden differs (use --write-golden)")
    return 0 if same else 1


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
