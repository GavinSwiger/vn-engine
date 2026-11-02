"""Helpers for F28's headless tests (F28 ``06-acceptance.md`` §0.3, §5).

- **Run H** on **IMG9+** (F09's IMG9 plus ``bg grain``): ``run_headless(program, seed=42,
  image_files=IMG9P)``, which advances at every line and ends every wait itself.
- **Template G** (``template_g``) and the ``walk/`` fixture under ``tests/fixtures/F28/``.
- **The step 3 headless golden** (06 §9 Step 3 milestone): ``walk/`` played by Run H, as
  F03's canonical JSON, with its ``Glitch`` commands. Regenerate only when a change to
  ``walk/`` or to a command is meant to change it::

      .venv/Scripts/python -m tests.runtime.glitch_story --write-golden
"""

from pathlib import Path

from engine.runtime.commands import Command
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.script.program import Program
from tests.runtime.effects_story import IMG9, load_game, write_game
from tests.script.helpers import template_f28

F28 = Path(__file__).resolve().parents[1] / "fixtures" / "F28"
IMG9P = IMG9 + ("images/bg/grain.png",)
GOLDEN = F28 / "goldens" / "walk_headless.json"


def template_g(root: Path, *, S: str | None = None, T: str | None = None,
               replace: dict[int, str] | None = None) -> Program:
    """Template G with the row's edit, loaded."""
    return load_game(write_game(root, template_f28(S=S, T=T, replace=replace)))


def walk() -> Program:
    return load_game(F28 / "walk")


def run_h(program: Program, **kwargs) -> list[Command]:
    return run_headless(program, seed=42, image_files=IMG9P, **kwargs)


def launched(program: Program, **kwargs) -> Interpreter:
    launch = run_launch(program, images=ImageSource.from_files(IMG9P))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, **kwargs)


def golden_text() -> str:
    from tests.runtime.corpus import canon, dumps
    return dumps({"fixture": "walk", "seed": 42, "image_files": list(IMG9P),
                  "commands": canon(run_h(walk()))})


def main(argv: list[str]) -> int:
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
