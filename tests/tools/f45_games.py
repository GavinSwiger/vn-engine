"""F45's fixture game S and helpers to run ``CheckJob`` in process (F45 ``06-acceptance.md``
§0.3, §5). ``studio(tmp_path)`` copies ``tests/fixtures/F45/games/studio/`` to
``<tmp>/my_game``; ``check(paths)`` runs a job and returns its decoded result."""

import shutil
from dataclasses import replace
from pathlib import Path

from engine.core.paths import GamePaths
from engine.tools.check import CheckJob, encode_event
from engine.tools.editor.checker import CheckResult, PendingCheck, decode_check_line

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "F45"
STUDIO = FIXTURES / "games" / "studio"
CHILDREN = FIXTURES / "children"


def studio(tmp_path: Path, name: str = "my_game") -> Path:
    """A fresh copy of S."""
    game = tmp_path / name
    shutil.copytree(STUDIO, game)
    return game


def edit_line(path: Path, number: int, text: str) -> None:
    """Replace line ``number`` (1-based) of a UTF-8, LF file."""
    lines = path.read_text(encoding="utf-8").split("\n")
    lines[number - 1] = text
    path.write_bytes("\n".join(lines).encode("utf-8"))


def run_job(paths: GamePaths, *, launch: bool = True) -> list[dict]:
    """Every event of one in-process ``CheckJob`` run, as emitted."""
    events: list[dict] = []
    CheckJob(paths, events.append, launch=launch).run()
    return events


def decoded(events: list[dict]) -> list[tuple[str, object]]:
    """Each event through the wire: encoded, then ``decode_check_line`` (never None)."""
    out = []
    for event in events:
        line = decode_check_line(encode_event(event))
        assert line is not None, event
        out.append(line)
    return out


def result_of(events: list[dict], serial: int = 0) -> CheckResult:
    """The ``CheckResult`` Studio would apply for these events."""
    pending = PendingCheck()
    for kind, payload in decoded(events):
        if kind == "done":
            return pending.result(payload, serial)
        pending.add(kind, payload)
    raise AssertionError("no done event")


def check(game: Path, *, launch: bool = True) -> CheckResult:
    return result_of(run_job(GamePaths.for_game(game), launch=launch))


def without_seconds(result: CheckResult) -> CheckResult:
    return replace(result, seconds=0.0)


def tree(folder: Path) -> dict[str, bytes | None]:
    """Every entry under ``folder`` (links not followed): path → bytes, None for folders."""
    found: dict[str, bytes | None] = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        found[rel] = path.read_bytes() if path.is_file() and not path.is_symlink() else None
    return found
