"""Where the tools read the game, and how they check it (F48 ``04-technical.md`` §3.1, §7.1
step 6, §7.6, §7.7; ``05-security.md`` SEC-F48-05, SEC-F48-09 (d)).

Why this module exists: the same tools serve two places that see different text. The MCP
server reads the files on disk; Studio's pane reads what the author sees, including unsaved
text. A ``Workspace`` hides that difference, so a tool never asks where text comes from.

- ``DiskWorkspace`` (MCP): every file from disk through ``GamePaths``; no unsaved text;
  checks are full unless the server runs with ``--no-launch`` (01 §8 D3).
- ``SnapshotWorkspace`` (pane): a ``Snapshot`` the Tk thread takes before a request (the
  dirty documents' texts and encodings, cursor, selection, whether the window is armed, and
  its last ``CheckResult``); other files from disk. Checks launch only when ``armed``
  (SEC-F48-05: nothing the model calls arms the window).
- ``Source`` is one file as read: its editor text (lines joined by ``\\n``, no final break),
  its SHA-256 (disk: of the file's bytes, which ``apply`` compares; snapshot: of the text,
  which the pane's ``rebase`` compares), and how to encode new text the same way.
- ``CheckService`` is a second ``CheckRunner`` (Studio's own runner keeps the editor's
  checks). ``run`` blocks until the child is done, polling it off the Tk thread; ``base``
  keeps the last few finished base checks by (launch, overlay SHA-256, files' stamps), so a
  proposal pays for one child on a cache hit.
- ``install_redaction(paths)`` installs F01's redactor with the game's and the user's roots
  (the MCP server has no ``logsetup``), so problem texts relayed from the check child hold
  no absolute path or user name (SEC-F48-09 (d)).

Imports ``engine.core``, ``engine.script``, the pure editor modules ``checker`` and
``document``, and its own package.
"""

import hashlib
import os
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from engine.core import redact as _redact
from engine.core.editorreport import CHECK_TIMEOUT_S
from engine.core.errors import EngineError
from engine.core.logsetup import redaction_roots
from engine.core.paths import GamePaths, engine_root, home_dir
from engine.core.redact import echo
from engine.script.assetgroups import ASSET_GROUPS, CONFIG_REF
from engine.script.diagnostics import ScriptError
from engine.tools.assistant.refs import RefTable, ToolError, one_line
from engine.tools.editor import document
from engine.tools.editor.checker import (
    CheckResult,
    CheckRunner,
    CheckRunnerLike,
    CheckState,
    encode_overlay,
)
from engine.tools.editor.declarations import position_rows
from engine.tools.editor.document import SaveError, ScriptDocument

POLL_S: Final = 0.05                    # how often ``run`` polls its runner
BASE_KEPT: Final = 4                    # finished base checks ``CheckService`` keeps
# A runner that never reports (a broken fake) still can't hold a request for ever.
RUN_DEADLINE_S: Final = CHECK_TIMEOUT_S + 10

# 01 §4.4: "Check child times out or crashes". ``reason`` texts carry no final period.
CHECK_DIDNT_FINISH: Final = "The check didn't finish ({reason}), so problems are unknown."
REASON_TIMEOUT: Final = f"it ran longer than {CHECK_TIMEOUT_S:g} seconds"
REASON_EXIT: Final = "it stopped with exit code {code}"
REASON_ENDED: Final = "it stopped before it was done"
REASON_STOPPED: Final = "the request was stopped"
REASON_TOO_LARGE: Final = "the files are too large to check together"
REASON_SPAWN: Final = "it couldn't start: {reason}"


def text_sha(text: str) -> str:
    """The hex SHA-256 of editor text (the pane's base for ``rebase``)."""
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def bytes_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install_redaction(paths: GamePaths) -> None:
    """Make ``redact()`` (and so every ``one_line``) replace the game folder, the engine,
    the home folder and the other F01 roots, and the user's name (SEC-F48-09 (d))."""
    roots = redaction_roots(game_root=paths.root, game_dir_as_given=paths.root,
                            engine_root=engine_root())
    home = home_dir()
    _redact.install(_redact.Redactor(roots, home_name=home.name if home is not None else None,
                                     case_insensitive=sys.platform in ("win32", "darwin")))


# --- Files ----------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Source:
    """One readable file as a workspace sees it. ``doc`` encodes text back to the file's own
    BOM and line endings (``document.encode``)."""

    ref: str
    text: str
    sha: str
    doc: ScriptDocument = field(repr=False)

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")

    def encode(self, text: str) -> bytes:
        """The file bytes for ``text``. ``ToolError`` for text that can't be saved."""
        try:
            return document.encode(self.doc, text)
        except SaveError as exc:
            raise ToolError(one_line(exc.message)) from None


def read_disk(paths: GamePaths, ref: str) -> tuple[ScriptDocument, bytes]:
    """``ref`` (a listed script or ``config.toml``) opened as Studio opens it, and its exact
    bytes (``encode`` of an unedited text gives them back). ``ToolError`` with the engine's
    text (F02's E05 for a file over ``SCRIPT_FILE_MAX_BYTES``) when it can't be read."""
    doc = document.open_config(paths) if ref == CONFIG_REF else document.open_document(paths, ref)
    if isinstance(doc, ScriptError):
        raise ToolError(one_line(doc.message, 300))
    try:
        data = document.encode(doc, doc.text)
    except SaveError as exc:
        raise ToolError(one_line(exc.message)) from None
    return doc, data


@dataclass(frozen=True, slots=True)
class CheckRun:
    """One check: ``result`` when it finished, else ``reason`` (no final period)."""

    result: CheckResult | None
    reason: str | None = None
    launch: bool = False

    @property
    def ok(self) -> bool:
        return self.result is not None

    @property
    def failure_text(self) -> str:
        """01 §4.4's text for a check that didn't finish."""
        return CHECK_DIDNT_FINISH.format(reason=self.reason or REASON_ENDED)


# --- Checks (04 §7.7: a second runner, polled off the Tk thread) -----------------------------

class CheckService:
    """Runs check children for one game, one at a time, blocking the calling thread.

    ``run(overlay, launch=…)`` requests a check and polls until its ``DONE``, ``TIMEOUT``
    or ``CRASHED`` (the runner enforces ``CHECK_TIMEOUT_S``). ``base(overlay, launch=…,
    stamp=…)`` is ``run`` with a cache of the last ``BASE_KEPT`` finished runs keyed by
    ``(launch, SHA-256 of the overlay, stamp)``. ``cancel`` (a ``threading.Event``) stops
    the child. ``runner``, ``sleep`` and ``clock`` are seams."""

    def __init__(self, game_dir: Path, *, runner: CheckRunnerLike | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.runner: CheckRunnerLike = runner if runner is not None else CheckRunner(game_dir)
        self._sleep = sleep
        self._clock = clock
        self._serial = 0
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple, CheckRun] = OrderedDict()
        self.runs = 0                     # children requested (tests)

    def run(self, overlay: bytes | None, *, launch: bool,
            cancel: threading.Event | None = None) -> CheckRun:
        with self._lock:
            self._serial += 1
            serial = self._serial
            self.runs += 1
            self.runner.request(overlay, serial, launch=launch)
            end = self._clock() + RUN_DEADLINE_S
            while True:
                for event in self.runner.poll():
                    if event.serial != serial:
                        continue
                    if event.state is CheckState.DONE:
                        return CheckRun(event.result, None, launch)
                    if event.state is CheckState.TIMEOUT:
                        return CheckRun(None, REASON_TIMEOUT, launch)
                    if event.state is CheckState.CRASHED:
                        if event.reason is not None:
                            reason = REASON_SPAWN.format(reason=echo(event.reason, 120))
                        elif event.exit_code is not None:
                            reason = REASON_EXIT.format(code=event.exit_code)
                        else:
                            reason = REASON_ENDED
                        return CheckRun(None, reason, launch)
                if cancel is not None and cancel.is_set():
                    self.runner.stop()
                    return CheckRun(None, REASON_STOPPED, launch)
                if self._clock() >= end:
                    self.runner.stop()
                    return CheckRun(None, REASON_TIMEOUT, launch)
                self._sleep(POLL_S)

    def base(self, overlay: bytes | None, *, launch: bool, stamp: object = None,
             cancel: threading.Event | None = None) -> CheckRun:
        key = (launch, bytes_sha(overlay) if overlay is not None else None, stamp)
        found = self._cache.get(key)
        if found is not None:
            self._cache.move_to_end(key)
            return found
        done = self.run(overlay, launch=launch, cancel=cancel)
        if done.ok:
            self._cache[key] = done
            while len(self._cache) > BASE_KEPT:
                self._cache.popitem(last=False)
        return done

    def forget(self) -> None:
        """Drop the cached base results (after a write the stamps change anyway)."""
        self._cache.clear()

    def stop(self) -> None:
        self.runner.stop()


# --- The seam -------------------------------------------------------------------------------

class Workspace:
    """What every tool reads. Subclasses give ``read``, ``dirty``, ``launch_allowed`` and
    ``last_check``; the rest is shared."""

    paths: GamePaths
    checks: CheckService
    pane: bool = False

    @property
    def launch_allowed(self) -> bool:
        raise NotImplementedError

    def read(self, ref: str) -> Source:
        """A listed script or ``config.toml`` (the caller selected it). ``ToolError`` when
        it can't be read."""
        raise NotImplementedError

    def dirty(self) -> Mapping[str, Source]:
        """The unsaved files, which every check overlays (MCP: none)."""
        return {}

    def last_check(self) -> CheckRun:
        """The check the names, the story map and the summary come from."""
        raise NotImplementedError

    # -- shared --------------------------------------------------------------------------------

    def table(self, *, names: bool = False) -> RefTable:
        """A fresh table of the game's members (listings re-read); with ``names``, the name
        kinds of ``last_check`` (which may run one)."""
        self.paths.invalidate_listings()
        found = None
        if names:
            run = self.last_check()
            found = run.result.names if run.result is not None else None
        return RefTable.build(self.paths, names=found)

    def dirty_files(self) -> list[tuple[str, bytes]]:
        """The overlay entries for the unsaved files."""
        return [(ref, source.encode(source.text)) for ref, source in self.dirty().items()]

    def stamp(self) -> tuple:
        """What identifies the saved game for the base-check cache: each listed script's
        and ``config.toml``'s size and change time, and each group folder's change time."""
        self.paths.invalidate_listings()
        found: list[tuple] = []
        refs = [*document.list_scripts(self.paths), CONFIG_REF,
                *(group.folder for group in ASSET_GROUPS)]
        for ref in refs:
            try:
                st = os.stat(self.paths.resolve(ref))
            except (OSError, ValueError, EngineError):   # missing, escaping, unreadable
                found.append((ref, None))
                continue
            found.append((ref, st.st_size, st.st_mtime_ns))
        return tuple(found)

    def base_check(self, *, launch: bool | None = None,
                   cancel: threading.Event | None = None) -> CheckRun:
        """The saved files plus the unsaved ones, checked (cached)."""
        launch = self.launch_allowed if launch is None else launch
        files = self.dirty_files()
        overlay = encode_overlay(files) if files else None
        if files and overlay is None:
            return CheckRun(None, REASON_TOO_LARGE, launch)
        return self.checks.base(overlay, launch=launch, stamp=self.stamp(), cancel=cancel)

    def check_with(self, changed: Sequence[tuple[str, bytes]], added: Sequence[str], *,
                   launch: bool, cancel: threading.Event | None = None) -> CheckRun:
        """The base files with ``changed`` put over them (``added``: the new files among
        them), checked. Never touches disk."""
        merged = dict(self.dirty_files())
        merged.update(changed)
        overlay = encode_overlay(list(merged.items()), added=added)
        if overlay is None:
            return CheckRun(None, REASON_TOO_LARGE, launch)
        return self.checks.run(overlay, launch=launch, cancel=cancel)

    def position_names(self) -> frozenset[str]:
        """The stage positions ``show … at`` may name (built-ins and ``config.toml``'s), for
        parsing a proposal as the loader would."""
        try:
            text = self.read(CONFIG_REF).text
        except ToolError:
            text = ""
        rows = position_rows(text) or position_rows("") or ()
        return frozenset(row.name for row in rows)


class DiskWorkspace(Workspace):
    """The files on disk (MCP). ``launch``: False with ``--no-launch``."""

    def __init__(self, paths: GamePaths, *, launch: bool = True,
                 checks: CheckService | None = None) -> None:
        self.paths = paths
        self._launch = launch
        self.checks = checks if checks is not None else CheckService(paths.root)

    @property
    def launch_allowed(self) -> bool:
        return self._launch

    def read(self, ref: str) -> Source:
        doc, data = read_disk(self.paths, ref)
        return Source(ref, doc.text, bytes_sha(data), doc)

    def last_check(self) -> CheckRun:
        """A full check (``--no-launch``: name-only) of the files on disk, run on first use
        and again whenever a file changed (the cache's stamp)."""
        return self.base_check()


@dataclass(frozen=True)
class Snapshot:
    """What the pane's worker may read, taken on the Tk thread before a request (≤ 20 ms):
    ``texts`` and ``docs`` of each unsaved document (same keys), the open file, the cursor
    ``(line, column)``, the selection ``(line, column, line, column)``, whether the window is
    ``armed`` (07 I-1), and the window's last ``CheckResult``."""

    texts: Mapping[str, str]
    docs: Mapping[str, ScriptDocument]
    armed: bool = False
    check: CheckResult | None = None
    open_file: str | None = None
    cursor: tuple[int, int] | None = None
    selection: tuple[int, int, int, int] | None = None


class SnapshotWorkspace(Workspace):
    """The pane's view: unsaved texts from the ``Snapshot``, other files from disk."""

    pane = True

    def __init__(self, paths: GamePaths, snapshot: Snapshot, *,
                 checks: CheckService | None = None) -> None:
        self.paths = paths
        self.snapshot = snapshot
        self.checks = checks if checks is not None else CheckService(paths.root)

    @property
    def launch_allowed(self) -> bool:
        return self.snapshot.armed

    def read(self, ref: str) -> Source:
        text = self.snapshot.texts.get(ref)
        doc = self.snapshot.docs.get(ref)
        if text is not None and doc is not None:
            return Source(ref, text, text_sha(text), doc)
        doc, _ = read_disk(self.paths, ref)
        return Source(ref, doc.text, text_sha(doc.text), doc)

    def dirty(self) -> Mapping[str, Source]:
        return {ref: Source(ref, text, text_sha(text), self.snapshot.docs[ref])
                for ref, text in self.snapshot.texts.items() if ref in self.snapshot.docs}

    def last_check(self) -> CheckRun:
        """The window's last check, else one run now (launching only when armed)."""
        if self.snapshot.check is not None:
            return CheckRun(self.snapshot.check, None, self.snapshot.armed)
        return self.base_check()


__all__ = ["BASE_KEPT", "CHECK_DIDNT_FINISH", "CheckRun", "CheckService", "DiskWorkspace",
           "POLL_S", "REASON_ENDED", "REASON_EXIT", "REASON_SPAWN", "REASON_STOPPED",
           "REASON_TIMEOUT", "REASON_TOO_LARGE", "Snapshot", "SnapshotWorkspace", "Source",
           "Workspace", "bytes_sha", "install_redaction", "read_disk", "text_sha"]
