"""AC-F03-82 (manual, Windows 11 reference machine): a copy of the example game with a stuck
``$`` line. Stdlib and ``engine`` only; it never changes ``game/``.

    .venv/Scripts/python -m tests.perf.ac82_game DEST

copies ``game/`` (without ``logs/``) to ``DEST``, adds ``$ while True: pass`` after the first
line of label ``start`` (06-acceptance AC-F03-82: "after the first line of the example
game"), checks that the copy still loads clean, and prints the steps. ``python main.py``
always runs ``<repo>/game``; ``python -m engine run DEST`` is the same launcher on another
folder (``engine/app/cli.py``), so the game folder stays untouched.

The check, once in a dev run and once with ``--release`` (06 AC-F03-82, §6 step 10):
1. ``.venv\\Scripts\\python -m engine run DEST`` (then ``... run DEST --release``).
2. Start the game from the title and advance past the first line; then don't touch the
   mouse or the keyboard.
3. Expect: the error screen with E85m after about 5 s (``… ran for 5 seconds without
   finishing, so it is probably stuck in a loop``). Note whether the title bar showed
   "(Not Responding)" at any moment (a brief flash is accepted, 04 §7.7, G12).
4. Press Esc on the error screen: the game closes. ``echo %ERRORLEVEL%`` (cmd) prints 1.
5. Record for each run: the seconds to the error screen, "Not Responding" yes/no/flash,
   the exit code, and the CPU model and PassMark single-thread score.
"""

import shutil
import sys
from pathlib import Path

STUCK = "$ while True: pass"
ROOT = Path(__file__).resolve().parents[2]


def first_line(program):
    """The first ``Say`` of label ``start``'s own block (the example game's first line)."""
    from engine.script import nodes

    for stmt in program.labels["start"].block:
        if isinstance(stmt, nodes.Say):
            return stmt
    raise SystemExit("label start has no line of its own")


def _load(game: Path):
    """``load_story`` as the game loads it (the config's stage positions)."""
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.script import LoadOptions, load_story

    paths = GamePaths(game.resolve())
    positions = frozenset(load_config(paths).config.stage.positions)
    return load_story(paths, LoadOptions(position_names=positions))


def make(dest: Path) -> tuple[Path, int]:
    """Copy ``game/`` to ``dest`` and add the stuck line; returns (file, line number)."""
    if dest.exists():
        raise SystemExit(f"{dest} already exists; give a new folder")
    shutil.copytree(ROOT / "game", dest, ignore=shutil.ignore_patterns("logs", "characters", "persistent", "saves", "settings"))
    result = _load(dest)
    if result.program is None:
        raise SystemExit("the example game doesn't load: " + "; ".join(
            e.format() for e in result.errors))
    say = first_line(result.program)
    path = dest / say.file.ref
    lines = path.read_text(encoding="utf-8").split("\n")
    source = lines[say.line - 1]
    indent = source[:len(source) - len(source.lstrip())]
    lines.insert(say.end_line, indent + STUCK)
    path.write_bytes("\n".join(lines).encode("utf-8"))
    again = _load(dest)
    if again.program is None or again.warnings:
        raise SystemExit("the changed copy doesn't load clean")
    return path, say.end_line + 1


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m tests.perf.ac82_game DEST", file=sys.stderr)
        return 2
    dest = Path(argv[0]).absolute()
    path, line = make(dest)
    print(f"Added '{STUCK}' at {path}, line {line}.")
    print("AC-F03-82, run each and follow tests/perf/ac82_game.py's steps:")
    print(f"  .venv\\Scripts\\python -m engine run \"{dest}\"")
    print(f"  .venv\\Scripts\\python -m engine run \"{dest}\" --release")
    print("  echo %ERRORLEVEL%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
