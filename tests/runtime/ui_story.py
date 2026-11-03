"""Helpers for F32's headless tests (F32 ``06-acceptance.md`` §0.3, §5).

- **Run H** on Template U (``tests/fixtures/F32/template``): ``run_headless(program,
  seed=42, image_files=IMAGES)``, advancing at every line.
- The ``walk/`` fixture under ``tests/fixtures/F32/`` (U1 to U5).
- Loads pass ``LoadOptions.style_names`` as the app does (Template U's ``ashes`` and ``calm``).
- ``ui`` registers at import only from F32 s4 (with the app's handlers), so ``ui_word()``
  registers it inside ``scoped_registry()`` (F19 07 I-5) for loads and runs.
- **The step 3 headless golden** (06 §9 Step 3 milestone): ``walk/`` played by Run H, as F03's
  canonical JSON, with ``UiStyle``, ``UiBlocks``, and ``DeleteSaves``. Regenerate only when a
  change to ``walk/`` or to a command is meant to change it::

      .venv/Scripts/python -m tests.runtime.ui_story --write-golden
"""

from contextlib import contextmanager
from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime.commands import Command
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.script import ui
from engine.script.loader import LoadOptions, load_story
from engine.script.program import Program
from engine.script.statements import scoped_registry
from tests.runtime.effects_story import write_game
from tests.script.helpers import template_f32

F32 = Path(__file__).resolve().parents[1] / "fixtures" / "F32"
IMAGES = ("images/bg/room.png",)
STYLES = frozenset(("ashes", "calm"))
GOLDEN = F32 / "goldens" / "headless.json"
R = "There's nothing left to keep."


@contextmanager
def ui_word():
    with scoped_registry():
        ui.register_words()
        yield


def load(root: Path, styles: frozenset[str] | None = STYLES) -> Program:
    with ui_word():
        result = load_story(GamePaths(root.resolve()), LoadOptions(style_names=styles))
    assert result.program is not None, [e.format() for e in result.errors]
    return result.program


def template_u(root: Path, *, S: str | None = None, T: str | None = None) -> Program:
    """Template U with the row's edit, loaded."""
    return load(write_game(root, template_f32(S=S, T=T)))


def walk(styles: frozenset[str] | None = STYLES) -> Program:
    return load(F32 / "walk", styles)


def run_h(program: Program, **kwargs) -> list[Command]:
    return run_headless(program, seed=42, image_files=IMAGES, **kwargs)


def launched(program: Program, **kwargs) -> Interpreter:
    launch = run_launch(program, images=ImageSource.from_files(IMAGES))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, **kwargs)


def golden_text() -> str:
    from tests.runtime.corpus import canon, dumps
    return dumps({"fixture": "walk", "seed": 42, "image_files": list(IMAGES),
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
