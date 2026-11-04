"""Studio's build runner: starts the build child, reads its report lines, keeps the progress
the dialog shows, and cancels (F42 ``04-technical.md`` §2, §3.2, §7.3; PR-F42-11, -16;
``07`` I-7). Also ``InstallRunner``, **Install build tool**'s pip child (D2, SEC-F42-05).

Pure Python, no Tk, no pygame: the dialog (W2) calls ``poll()`` from the Tk loop and draws
``progress``. Never blocks the Tk thread.

- ``BuildRunner.start(save_to, folder, zip=, replace=, serial=)`` spawns ``python -E -B -m
  engine build … --report-to-editor`` (``buildmodel.build_argv``) through ``procs.spawn``
  (argument list, ``cwd = engine_root()``, ``PYTHON*`` removed). One daemon thread reads
  stdout with F44's reader (``preview.read_child_output``) and ``decode_build_line``.
- ``poll()`` → ``BuildEvent``\\ s: ``STEP`` (``build_step``; ``progress`` updated), ``CHECK``
  (the relayed check's ``done``: a ``CheckResult`` for ``checkwiring`` to apply as a check
  run), ``DONE`` (``build_done``), ``FAILED`` (``build_failed``), ``CRASHED`` (the child ended
  without either, or didn't start), ``CANCELLED``.
- ``cancel()`` (I-7): a worker thread kills the child's whole tree (``procs.kill_tree``:
  ``taskkill /T /F``, which also waits), and only once the child has exited deletes the
  staging folder named in the last ``build_step``, and only if that name is a bare
  ``tree.STAGING_RE`` name for this build's folder, joined to Studio's own *Save to*, a real
  folder (not a link) directly in it, holding the staging marker (``cancel_target``). The
  delete is ``tree.remove_tree`` (no link followed). Then ``CANCELLED`` (``left`` names a
  staging folder that couldn't be removed; the next build's ``sweep_stale`` takes it).
  Every other failure is cleaned up by the child itself.
- ``BuildProgress``: rows (``waiting``/``running``/``done``/``failed``), ``Step N of M``,
  the running step's elapsed text (``0:41``), the bar's fraction, and whether ``SLOW`` shows.

``popen``, ``clock``, ``kill_tree``, ``remove_tree`` and ``argv`` are for tests.

Imports ``core``, the shared ``tools.build`` modules (``procs``, ``texts``, ``tree``) and its
own package.
"""

import collections
import enum
import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

from engine.core import safefile
from engine.core.editorreport import (
    BUILD_MAX_DETAILS,
    BUILD_MAX_KEYS,
    BUILD_MAX_LEFT_OUT,
    BUILD_MAX_VALUES,
    BUILD_NAME_MAX_CHARS,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.logsetup import redaction_roots
from engine.core.paths import engine_root
from engine.core.redact import RedactRoot
from engine.tools.build import procs, texts, tree
from engine.tools.editor import buildmodel
from engine.tools.editor.checker import CheckResult, PendingCheck, decode_check_line
from engine.tools.editor.preview import EOF, read_child_output

TAIL_LINES: Final = 200
_CANCELLED: Final = "cancelled"
_STEP_KEYS: Final = tuple(texts.STEPS)


# --- Events (core/editorreport BUILD_EVENTS) --------------------------------------------------

@dataclass(frozen=True, slots=True)
class StepInfo:
    i: int
    m: int
    key: str
    files: int | None = None
    bytes: int | None = None
    staging: str | None = None


@dataclass(frozen=True, slots=True)
class BuildDone:
    folder: str
    exe: str
    files: int
    bytes: int
    zip: str | None
    zip_bytes: int | None
    warnings: int
    left_out: tuple[tuple[str, str], ...]
    left_out_total: int
    long_paths: int
    long_path_example: str | None
    keys: tuple[tuple[str, int], ...] = ()      # F48: key-shaped text at (ref, line)


@dataclass(frozen=True, slots=True)
class BuildFailure:
    code: str
    values: Mapping[str, str | int] = field(default_factory=dict)
    details: tuple[str, ...] = ()

    def texts(self) -> tuple[str, str, tuple[str, ...]]:
        return buildmodel.failed_texts(self)


def _name(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= BUILD_NAME_MAX_CHARS


def _text(value: object) -> bool:
    return isinstance(value, str) and len(value) <= REPORT_TEXT_MAX_CHARS


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


def _opt(check: Callable[[object], bool], value: object) -> bool:
    return value is None or check(value)


def _step(data: dict) -> StepInfo | None:
    i, m, key = data.get("i"), data.get("m"), data.get("key")
    if type(i) is not int or type(m) is not int or not 1 <= i <= m <= len(_STEP_KEYS) \
            or key not in _STEP_KEYS:
        return None
    files, size, staging = data.get("files"), data.get("bytes"), data.get("staging")
    if not _opt(_count, files) or not _opt(_count, size) or not _opt(_name, staging):
        return None
    return StepInfo(i, m, key, files, size, staging)


def _keys(value: object) -> tuple[tuple[str, int], ...] | None:
    """``build_done.keys`` (F48 PR-F48-32): missing is none; anything malformed is None."""
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > BUILD_MAX_KEYS or not all(
            isinstance(row, list) and len(row) == 2 and _text(row[0]) and row[0]
            and type(row[1]) is int and row[1] >= 1 for row in value):
        return None
    return tuple((ref, line) for ref, line in value)


def _done(data: dict) -> BuildDone | None:
    left = data.get("left_out")
    keys = _keys(data.get("keys"))
    if keys is None:
        return None
    if not isinstance(left, list) or len(left) > BUILD_MAX_LEFT_OUT or not all(
            isinstance(row, list) and len(row) == 2 and _text(row[0]) and _text(row[1])
            for row in left):
        return None
    if not (_name(data.get("folder")) and _name(data.get("exe"))
            and all(_count(data.get(k)) for k in ("files", "bytes", "warnings",
                                                  "left_out_total", "long_paths"))
            and _opt(_name, data.get("zip")) and _opt(_count, data.get("zip_bytes"))
            and _opt(_text, data.get("long_path_example"))):
        return None
    return BuildDone(data["folder"], data["exe"], data["files"], data["bytes"], data["zip"],
                     data["zip_bytes"], data["warnings"],
                     tuple((ref, reason) for ref, reason in left),
                     max(data["left_out_total"], len(left)), data["long_paths"],
                     data["long_path_example"], keys)


def _failed(data: dict) -> BuildFailure | None:
    code, values, details = data.get("code"), data.get("values"), data.get("details")
    if code not in texts.FAILURES or not isinstance(values, dict) \
            or len(values) > BUILD_MAX_VALUES or not isinstance(details, list) \
            or len(details) > BUILD_MAX_DETAILS or not all(_text(d) for d in details):
        return None
    if not all(isinstance(k, str) and len(k) <= 32
               and (_name(v) or v == "" or type(v) is int) for k, v in values.items()):
        return None
    return BuildFailure(code, MappingProxyType(dict(values)), tuple(details))


_DECODERS: Final = {"build_step": _step, "build_done": _done, "build_failed": _failed}


def decode_build_line(body: bytes) -> tuple[str, object] | None:
    """One stdout line (no line break) → ``(event, payload)``: a build event
    (``StepInfo``/``BuildDone``/``BuildFailure``) or a relayed check line
    (``checker.decode_check_line``'s payloads). None for anything malformed; never raises."""
    if not isinstance(body, bytes) or not body.startswith(REPORT_MARKER) \
            or len(body) > REPORT_MAX_BYTES:
        return None
    try:
        data = json.loads(body[len(REPORT_MARKER):].decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or type(data.get("v")) is not int \
            or data["v"] != REPORT_VERSION:
        return None
    decoder = _DECODERS.get(data.get("event"))            # type: ignore[arg-type]
    if decoder is None:
        return decode_check_line(body)
    payload = decoder(data)
    return None if payload is None else (data["event"], payload)


# --- Progress (01 §6.1 Progress view; PR-F42-16) ---------------------------------------------

WAITING, RUNNING, DONE, FAILED = "waiting", "running", "done", "failed"


@dataclass(frozen=True, slots=True)
class StepRow:
    key: str
    text: str
    status: str


class BuildProgress:
    """The Progress view's state for one build."""

    def __init__(self, with_zip: bool) -> None:
        self.keys = texts.steps(with_zip)
        self.m = len(self.keys)
        self.current = 0                      # 1-based running step; 0 before the first
        self.failed = False
        self.finished = False
        self.started_at: float | None = None
        self._counts: tuple[int | None, int | None] = (None, None)

    def on_step(self, step: StepInfo, now: float) -> None:
        if step.key in self.keys:
            self.current = self.keys.index(step.key) + 1
        self.started_at = now
        if step.key == texts.STEP_COPY:
            self._counts = (step.files, step.bytes)

    def on_end(self, *, ok: bool) -> None:
        self.finished = ok
        self.failed = not ok

    def rows(self) -> list[StepRow]:
        out = []
        for index, key in enumerate(self.keys, start=1):
            if self.finished or index < self.current:
                status = DONE
            elif index == self.current:
                status = FAILED if self.failed else RUNNING
            else:
                status = WAITING
            files, size = self._counts if key == texts.STEP_COPY else (None, None)
            out.append(StepRow(key, texts.step_text(key, files=files, size=size), status))
        return out

    def counter_text(self) -> str:
        return texts.STEP_OF.format(i=max(self.current, 1), m=self.m)

    @property
    def fraction(self) -> float:
        done = self.m if self.finished else max(self.current - 1, 0)
        return done / self.m

    @property
    def slow(self) -> bool:
        """``SLOW`` shows under the running pack step."""
        return (not self.finished and not self.failed and self.current > 0
                and self.keys[self.current - 1] == texts.STEP_PACK)

    def elapsed_text(self, now: float) -> str:
        """The running step's time, ``0:41`` (``1:02:03`` past an hour); empty when no step
        runs."""
        if self.started_at is None or self.finished or self.failed:
            return ""
        seconds = max(int(now - self.started_at), 0)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


# --- The runner ------------------------------------------------------------------------------

class BuildState(enum.Enum):
    STARTED = "started"
    STEP = "step"
    CHECK = "check"
    DONE = "done"
    FAILED = "failed"
    CRASHED = "crashed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BuildEvent:
    state: BuildState
    step: StepInfo | None = None
    done: BuildDone | None = None
    failure: BuildFailure | None = None
    check: CheckResult | None = None
    exit_code: int | None = None
    reason: str | None = None
    left: Path | None = None                # CANCELLED: a staging folder that stayed


def cancel_target(save_to: Path, folder: str, staging: str | None) -> Path | None:
    """The staging folder Cancel may delete (I-7), or None: ``staging`` (from the last
    ``build_step``) must be a bare name matching ``tree.STAGING_RE`` for ``folder``; joined to
    Studio's own ``save_to`` it must be a real folder directly in it holding the staging
    marker. Call only after the build's processes exited."""
    if not isinstance(staging, str) or os.path.basename(staging) != staging \
            or "/" in staging or "\\" in staging or staging in (".", ".."):
        return None
    match = tree.STAGING_RE.fullmatch(staging)
    if match is None or match.group("folder") != folder:
        return None
    path = Path(save_to) / staging
    if not tree.is_real_dir(path) or not tree.real_inside(path, Path(save_to)) \
            or os.path.normcase(os.path.realpath(path.parent)) \
            != os.path.normcase(os.path.realpath(save_to)):
        return None
    if not safefile.is_regular_at(path / tree.STAGING_MARKER):
        return None
    return path


def _cancel_work(proc: subprocess.Popen | None, target: Callable[[], Path | None],
                 kill_tree: Callable[[object], None],
                 remove_tree: Callable[[Path], Path | None],
                 reader: threading.Thread | None,
                 put: Callable[[tuple[str, object]], None]) -> None:
    """Cancel's worker thread: kill the tree (waits), then remove staging if the child has
    exited."""
    left: Path | None = None
    try:
        if proc is not None:
            kill_tree(proc)
        exited = proc is None or proc.poll() is not None
        if reader is not None:
            reader.join(procs.KILL_WAIT_S)
        path = target() if exited else None
        if path is not None:
            left = remove_tree(path)
    except Exception:                                   # never let the thread die silently
        pass
    put((_CANCELLED, left))


class BuildRunner:
    """One build at a time for one game folder; see the module docstring."""

    def __init__(self, game_root: Path, *,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic,
                 kill_tree: Callable[[object], None] = procs.kill_tree,
                 remove_tree: Callable[[Path], Path | None] = tree.remove_tree,
                 argv: Callable[..., list[str]] = buildmodel.build_argv) -> None:
        self.game_root = Path(game_root)
        self._popen = popen
        self._clock = clock
        self._kill_tree = kill_tree
        self._remove_tree = remove_tree
        self._argv = argv
        self._reset()

    def _reset(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._messages: "queue.SimpleQueue[tuple[str, object]]" = queue.SimpleQueue()
        self._reader: threading.Thread | None = None
        self._canceller: threading.Thread | None = None
        self._tail: collections.deque[str] = collections.deque(maxlen=TAIL_LINES)
        self._pending = PendingCheck()
        self._save_to: Path | None = None
        self._folder = ""
        self._serial = 0
        self._staging: str | None = None
        self._running = False
        self._stopping = False
        self._ended = False
        self._eof = False
        self.progress: BuildProgress | None = None

    # State -----------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        """A build (or its cancel) is under way: the menu entry is off."""
        return self._running

    @property
    def stopping(self) -> bool:
        """Cancel was asked and isn't finished (the dialog shows "Stopping…")."""
        return self._stopping

    @property
    def process(self) -> subprocess.Popen | None:
        return self._proc

    # Commands ----------------------------------------------------------------------------
    def start(self, save_to: Path, folder: str, *, zip: bool, replace: bool,
              serial: int = 0) -> list[BuildEvent]:
        """Start a build into ``save_to`` (the computed ``folder`` is kept for Cancel's
        check). Returns ``[STARTED]`` or ``[CRASHED]`` (it didn't spawn)."""
        if self._running:
            raise RuntimeError("a build is already running")
        self._reset()
        self._save_to = Path(save_to)
        self._folder = folder
        self._serial = serial
        self.progress = BuildProgress(zip)
        argv = self._argv(self.game_root, self._save_to, zip=zip, replace=replace)
        try:
            self._proc = procs.spawn(argv, popen=self._popen, stderr=subprocess.STDOUT)
        except (OSError, ValueError) as exc:
            self.progress.on_end(ok=False)
            reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            return [BuildEvent(BuildState.CRASHED, reason=reason)]
        self._running = True
        self._reader = threading.Thread(
            target=read_child_output, name="vn-build-child", daemon=True,
            args=(self._proc.stdout, self._messages.put, self._keep_tail, decode_build_line))
        self._reader.start()
        return [BuildEvent(BuildState.STARTED)]

    def cancel(self) -> None:
        """**Cancel build** / **Stop build** (I-7); returns at once. ``poll`` gives
        ``CANCELLED`` when the tree is gone and staging removed."""
        if not self._running or self._stopping:
            return
        self._stopping = True
        save_to, folder, staging = self._save_to, self._folder, self._staging
        self._canceller = threading.Thread(
            target=_cancel_work, name="vn-build-cancel", daemon=True,
            args=(self._proc, lambda: cancel_target(save_to, folder, staging),
                  self._kill_tree, self._remove_tree, self._reader, self._messages.put))
        self._canceller.start()

    def stop(self, timeout_s: float = 3 * procs.KILL_WAIT_S) -> None:
        """Cancel and wait (Studio closing, ``CLOSE_WHILE_BUILDING``'s **Stop and
        close**)."""
        self.cancel()
        if self._canceller is not None:
            self._canceller.join(timeout_s)

    def poll(self) -> list[BuildEvent]:
        """Every event since the last call, oldest first. Never blocks."""
        events: list[BuildEvent] = []
        if not self._running:
            return events
        while True:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                break
            self._handle(kind, payload, events)
            if not self._running:
                return events
        if self._eof and not self._stopping and not self._ended and self._proc is not None:
            code = self._proc.poll()
            if code is not None:
                self._finish(ok=False)
                events.append(BuildEvent(BuildState.CRASHED, exit_code=code,
                                         reason="\n".join(self._redacted_tail())))
        return events

    # Internals ---------------------------------------------------------------------------
    def _keep_tail(self, line: bytes) -> None:
        self._tail.append(line.decode("utf-8", "replace").rstrip("\r\n"))

    def _redacted_tail(self) -> list[str]:
        roots = redaction_roots(game_root=self.game_root, game_dir_as_given=self.game_root,
                                engine_root=engine_root())
        if self._save_to is not None:
            roots.append(RedactRoot(procs.SAVE_TO_TOKEN, str(self._save_to)))
        return procs.redacted_tail(list(self._tail), roots)

    def _finish(self, *, ok: bool) -> None:
        self._ended = True
        if self.progress is not None:
            self.progress.on_end(ok=ok)
        if self._eof:
            self._running = False

    def _handle(self, kind: str, payload: object, events: list[BuildEvent]) -> None:
        if kind == _CANCELLED:
            self._running = self._stopping = False
            if self.progress is not None and not self._ended:
                self.progress.on_end(ok=False)
            self._ended = True
            events.append(BuildEvent(BuildState.CANCELLED, left=payload))   # type: ignore[arg-type]
            return
        if kind == EOF:
            self._eof = True
            if self._ended and not self._stopping:
                self._running = False
            return
        if self._stopping or self._ended:
            return                                      # nothing after the end counts
        if kind == "build_step":
            step: StepInfo = payload                    # type: ignore[assignment]
            if step.staging is not None:
                self._staging = step.staging
            if self.progress is not None:
                self.progress.on_step(step, self._clock())
            events.append(BuildEvent(BuildState.STEP, step=step))
        elif kind == "build_done":
            self._finish(ok=True)
            events.append(BuildEvent(BuildState.DONE, done=payload))        # type: ignore[arg-type]
        elif kind == "build_failed":
            self._finish(ok=False)
            events.append(BuildEvent(BuildState.FAILED, failure=payload))   # type: ignore[arg-type]
        elif kind == "done":
            result = self._pending.result(payload, self._serial)           # type: ignore[arg-type]
            self._pending = PendingCheck()
            events.append(BuildEvent(BuildState.CHECK, check=result))
        elif kind in ("problems", "names", "graph"):
            self._pending.add(kind, payload)


# --- Install build tool (D2; SEC-F42-05) --------------------------------------------------------

@dataclass(frozen=True)
class InstallEvent:
    lines: tuple[str, ...] = ()             # new output lines, redacted
    finished: bool = False
    exit_code: int | None = None
    reason: str | None = None               # it didn't start


def _read_plain(stream, put: Callable[[str], None]) -> None:
    try:
        for line in iter(stream.readline, b""):
            put(line.decode("utf-8", "replace").rstrip("\r\n"))
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass
        put(None)                                       # type: ignore[arg-type]


class InstallRunner:
    """Runs ``procs.install_argv()`` (pinned, hashed, never elevated) as a child; ``poll``
    gives its output redacted (``procs.redacted_tail``) and, last, its exit code."""

    def __init__(self, game_root: Path, *,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 kill_tree: Callable[[object], None] = procs.kill_tree) -> None:
        self.game_root = Path(game_root)
        self._popen = popen
        self._kill_tree = kill_tree
        self._proc: subprocess.Popen | None = None
        self._lines: "queue.SimpleQueue[str | None]" = queue.SimpleQueue()
        self._running = False
        self._eof = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> InstallEvent | None:
        """None when started; an ``InstallEvent`` with ``reason`` when it couldn't start."""
        if self._running:
            return None
        self._lines = queue.SimpleQueue()
        self._eof = False
        try:
            self._proc = procs.spawn(procs.install_argv(), popen=self._popen)
        except (OSError, ValueError) as exc:
            reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            return InstallEvent(finished=True, reason=reason)
        self._running = True
        threading.Thread(target=_read_plain, name="vn-build-install", daemon=True,
                         args=(self._proc.stdout, self._lines.put)).start()
        return None

    def cancel(self) -> None:
        if self._running and self._proc is not None:
            threading.Thread(target=self._kill_tree, args=(self._proc,), daemon=True).start()

    def poll(self) -> list[InstallEvent]:
        if not self._running:
            return []
        raw: list[str] = []
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                break
            if line is None:
                self._eof = True
            else:
                raw.append(line)
        events: list[InstallEvent] = []
        if raw:
            roots = redaction_roots(game_root=self.game_root, game_dir_as_given=self.game_root,
                                    engine_root=engine_root())
            events.append(InstallEvent(tuple(procs.redacted_tail(raw, roots, len(raw)))))
        if self._eof and self._proc is not None:
            code = self._proc.poll()
            if code is not None:
                self._running = False
                events.append(InstallEvent(finished=True, exit_code=code))
        return events


__all__ = ["BuildDone", "BuildEvent", "BuildFailure", "BuildProgress", "BuildRunner",
           "BuildState", "InstallEvent", "InstallRunner", "StepInfo", "StepRow",
           "cancel_target", "decode_build_line"]
