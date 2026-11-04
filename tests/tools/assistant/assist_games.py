"""Helpers for the F48 tool-layer tests: a copy of F45's fixture game S, a scripted check
runner, and workspaces over them."""

from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType

from engine.core.paths import GamePaths
from engine.tools.assistant.workspace import (
    CheckService, DiskWorkspace, Snapshot, SnapshotWorkspace)
from engine.tools.editor import document
from engine.tools.editor.checker import CheckEvent, CheckItem, CheckResult, CheckState
from tests.tools.f45_games import studio, tree  # noqa: F401  (re-exported)


def result(*problems: CheckItem, names: dict | None = None, links=(),
           loaded: bool = True) -> CheckResult:
    """A finished check with ``problems``."""
    found = MappingProxyType({kind: tuple(rows) for kind, rows in (names or {}).items()})
    return CheckResult(problems=tuple(problems), problem_total=len(problems), names=found,
                       links=tuple(links) if loaded else None, loaded=loaded, serial=0,
                       seconds=0.1)


def item(code: str, file: str | None, line: int | None, text: str,
         severity: str = "error") -> CheckItem:
    return CheckItem(severity, code, "load", text, file, line)       # type: ignore[arg-type]


class FakeRunner:
    """A ``CheckRunnerLike`` whose every request finishes at the next poll: ``answer(overlay,
    launch)`` gives the ``CheckResult`` (``state`` other than DONE: that event instead).
    ``requests`` records ``(overlay, launch)``."""

    def __init__(self, answer: Callable[[bytes | None, bool], CheckResult] | CheckResult
                 | None = None, *, state: CheckState = CheckState.DONE,
                 exit_code: int | None = None) -> None:
        self.answer = answer if answer is not None else result()
        self.state = state
        self.exit_code = exit_code
        self.requests: list[tuple[bytes | None, bool]] = []
        self.stopped = 0
        self._pending: tuple[bytes | None, int, bool] | None = None

    def request(self, overlay: bytes | None, serial: int, *, launch: bool) -> None:
        self.requests.append((overlay, launch))
        self._pending = (overlay, serial, launch)

    def poll(self) -> list[CheckEvent]:
        if self._pending is None:
            return []
        overlay, serial, launch = self._pending
        self._pending = None
        if self.state is not CheckState.DONE:
            return [CheckEvent(self.state, serial, exit_code=self.exit_code)]
        found = self.answer(overlay, launch) if callable(self.answer) else self.answer
        return [CheckEvent(CheckState.DONE, serial, found)]

    def stop(self) -> None:
        self.stopped += 1


def service(game: Path, runner=None) -> CheckService:
    return CheckService(game, runner=runner if runner is not None else FakeRunner(),
                        sleep=lambda _s: None)


def disk(game: Path, runner=None, *, launch: bool = True) -> DiskWorkspace:
    """The MCP workspace; ``runner`` None: a fake that always finds no problems; the string
    ``"real"``: a real check child."""
    paths = GamePaths.for_game(game)
    if runner == "real":
        return DiskWorkspace(paths, launch=launch)
    return DiskWorkspace(paths, launch=launch, checks=service(game, runner))


def pane(game: Path, texts: dict[str, str] | None = None, *, armed: bool = False,
         runner=None, check: CheckResult | None = None) -> SnapshotWorkspace:
    """The pane's workspace with ``texts`` as unsaved editor text."""
    paths = GamePaths.for_game(game)
    docs = {ref: document.open_document(paths, ref) for ref in (texts or {})}
    snap = Snapshot(texts=dict(texts or {}), docs=docs, armed=armed, check=check)
    checks = None if runner == "real" else service(game, runner)
    return SnapshotWorkspace(paths, snap, checks=checks)
