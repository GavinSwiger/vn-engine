"""Helpers for F31's headless tests (F31 ``06-acceptance.md`` §0.3, §5).

- **Run H**: ``run_headless(program, seed=42, files=MemoryFolder(...), inputs=...)`` on
  ``tests/fixtures/F31/walk/`` unless stated.
- **Port spy**: ``SpyFolder``, a ``MemoryFolder`` that records ``exists``, ``read``, ``write``,
  and ``delete`` calls as ``(verb, name)``.
- ``walk/`` differs from 06 §5's listing in one way: ``{var=}`` shows only text and numbers
  (F05 E171), so W1, W3, and W4's ``other`` row show ``hana_here`` and ``answer`` through
  ``$ shown = str(...)`` (lines 9, 16, 22) and ``default shown = ""`` at the end. Lines 1–8
  are as listed (E312/E313 rows in ``tests/script/test_metafiles_checks.py``).
- **The step 3 headless golden** (06 §9 Step 3 milestone): ``walk/`` played by Run H with
  ``MemoryFolder(originals={"hana.chr": <files/hana.chr>})``, as F03's canonical JSON.
  Regenerate only when a change to ``walk/`` or to a command is meant to change it::

      .venv/Scripts/python -m tests.runtime.metafiles_story --write-golden
"""

from pathlib import Path

from engine.runtime.commands import Command
from engine.runtime.headless import run_headless
from engine.runtime.images import ImageSource
from engine.runtime.interpreter import Interpreter
from engine.runtime.launch import run_launch
from engine.runtime.metafiles import MemoryFolder, MetaFiles, ReadAnswer, attach
from engine.script.program import Program
from tests.runtime.effects_story import load_game

F31 = Path(__file__).resolve().parents[1] / "fixtures" / "F31"
GOLDEN = F31 / "goldens" / "headless.json"
HANA = (F31 / "walk" / "files" / "hana.chr").read_bytes()

_programs: dict[str, Program] = {}


def fixture(name: str) -> Program:
    """``tests/fixtures/F31/<name>/``, loaded once per session (a ``Program`` is immutable)."""
    program = _programs.get(name)
    if program is None:
        program = _programs[name] = load_game(F31 / name)
    return program


class SpyFolder(MemoryFolder):
    """The port spy (06 §0.3)."""

    __slots__ = ("calls",)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[tuple[str, str]] = []

    def exists(self, name: str) -> bool:
        self.calls.append(("exists", name))
        return super().exists(name)

    def read(self, name: str) -> ReadAnswer:
        self.calls.append(("read", name))
        return super().read(name)

    def write(self, name: str, text: bytes | None) -> None:
        self.calls.append(("write", name))
        super().write(name, text)

    def delete(self, name: str) -> None:
        self.calls.append(("delete", name))
        super().delete(name)

    def changes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] in ("write", "delete")]


def spy(**kwargs) -> SpyFolder:
    kwargs.setdefault("originals", {"hana.chr": HANA})
    return SpyFolder(**kwargs)


def run_h(program: Program | None = None, **kwargs) -> list[Command]:
    return run_headless(fixture("walk") if program is None else program, seed=42, **kwargs)


def started(program: Program, folder: MemoryFolder, **kwargs) -> Interpreter:
    """A launched interpreter with ``folder`` attached, at its first wait."""
    launch = run_launch(program, images=ImageSource.from_files(()))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    interp = Interpreter(program, launch.namespace, **kwargs)
    attach(interp, MetaFiles(folder))
    interp.new_game(42)
    interp.run(10_000)
    return interp


def golden_text() -> str:
    from tests.runtime.corpus import canon, dumps
    commands = run_h(files=MemoryFolder(originals={"hana.chr": HANA}))
    return dumps({"fixture": "walk", "seed": 42, "originals": ["hana.chr"],
                  "commands": canon(commands)})


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
