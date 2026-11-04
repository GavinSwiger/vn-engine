"""Studio's check runner: the check child's argv, the stdin overlay, the report decoding, and
``CheckRunner`` (F45 ``04-technical.md`` §4.2, §4.3, §5, §7.2 steps 2-5; ``07`` I-1, I-2).

Pure Python, no Tk. A check runs ``python -B -m engine check <game> --report-to-editor
[--stdin-overlay] [--no-launch]`` (``tools/check.py``), which writes ``problems``, ``names``,
``graph``, then ``done`` lines in F44's framing. Studio applies a run only on ``done``, in one
step: until then the runner's ``result`` is the previous one.

- **Never blocks.** ``request`` only records what to run; ``poll`` (every 100 ms) spawns,
  reads, and times out. Each child has one daemon thread that spawns it, writes the
  overlay, closes stdin, and then reads stdout with F44's reader (``read_child_output`` with
  ``decode=decode_check_line``), touching only the pipes and a queue.
- **One child.** A newer ``request`` marks the live child superseded and terminates it (a
  kill follows after ``KILL_AFTER_S``); the newest request spawns once it is gone. A
  superseded child's lines are never applied.
- **Failures keep the old result.** No ``done`` before EOF, or a nonzero exit, is
  ``CRASHED``; still running after ``CHECK_TIMEOUT_S`` is ``TIMEOUT`` (terminate, then kill).
- **Bounded.** ``decode_check_line`` checks every line's shape and limits and returns None
  for a bad one (never raises). ``PendingCheck`` keeps at most the §4.3 totals and counts
  the rest.
- **Arming** (``07`` I-1). ``request(…, launch=False)`` adds ``--no-launch``, so no author
  code runs; the window passes ``launch=True`` once the author has previewed, saved, or
  checked in it.

``EditorWindow(…, check_runner=)`` takes anything with ``request(overlay, serial, *,
launch)``, ``poll()``, and ``stop()`` (``CheckRunnerLike``), so Tk tests pass a fake (I-2).

Imports ``engine.core``, ``engine.script``, its own package, and the standard library; never
``engine.tools.check`` or ``engine.runtime``.
"""

import enum
import json
import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from engine.core.constants import CONFIG_FILENAME, CONFIG_MAX_BYTES
from engine.core.editorreport import (
    CHECK_CODE_MAX_CHARS,
    CHECK_EVENT_MAX_ITEMS,
    CHECK_KIND_RE,
    CHECK_LINK_KINDS,
    CHECK_MAX_LINKS,
    CHECK_MAX_NAMES,
    CHECK_MAX_PROBLEMS,
    CHECK_SEVERITIES,
    CHECK_TIMEOUT_S,
    OVERLAY_HEADER_MAX,
    OVERLAY_MAX_BYTES,
    OVERLAY_MAX_FILES,
    OVERLAY_MAX_NEW,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.paths import engine_root
from engine.core.redact import echo
from engine.script.labelgraph import LabelLink
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.tools.build.procs import without_keys
from engine.tools.editor.preview import CHILD_ENCODING, EOF, KILL_AFTER_S, read_child_output

_IS_WINDOWS = os.name == "nt"
_KIND = re.compile(CHECK_KIND_RE)
_MAX_NAME_KINDS = 64                    # kinds a done line may total (later features add rows)


# --- Results (04 §4.2) -----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CheckItem:
    """One problem (PR-F45-08's one item shape; F41 reuses it). ``code`` is ``""`` for
    config texts; ``source`` is ``config``, ``load``, ``launch``, ``lint``, or a later word."""

    severity: Literal["error", "warning", "info"]
    code: str
    source: str
    text: str
    file: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class NameEntry:
    """One name of a kind, with where it is declared when it has a place."""

    name: str
    file: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class CheckDone:
    """A decoded ``done`` line: the run's true totals."""

    loaded: bool
    problems: int
    seconds: float
    name_totals: Mapping[str, int] = field(default_factory=dict)
    link_total: int = 0


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One finished check. ``names`` holds only the kinds this run sent; ``links`` is None
    when the script didn't load. ``problem_total`` counts every problem, sent or not;
    ``name_totals`` and ``link_total`` likewise. ``serial`` is the request's edit serial."""

    problems: tuple[CheckItem, ...]
    problem_total: int
    names: Mapping[str, tuple[NameEntry, ...]]
    links: tuple[LabelLink, ...] | None
    loaded: bool
    serial: int
    seconds: float
    name_totals: Mapping[str, int] = field(default_factory=dict)
    link_total: int = 0


# --- Argv and overlay (04 §4.3, §5, §7.2 step 2; 07 I-1, I-2) --------------------------------

def check_argv(game_dir: Path, *, overlay: bool = True, launch: bool = True) -> list[str]:
    """The check child's command line. ``--stdin-overlay`` only when an overlay is sent
    (stdin is a pipe), ``--no-launch`` until the window is armed (07 I-1, I-2)."""
    return [sys.executable, "-B", "-m", "engine", "check", str(game_dir), "--report-to-editor",
            *(["--stdin-overlay"] if overlay else []), *([] if launch else ["--no-launch"])]


def encode_overlay(files: Sequence[tuple[str, bytes]],
                   added: Collection[str] = ()) -> bytes | None:
    """The overlay for ``files`` (``(ref, encoded bytes)`` of each dirty document): a header
    line, then the bytes in header order. None when it passes a cap (more than 64 files, a
    file over its reader's cap, more than 64 MiB in all, or a header over 64 KiB): Studio
    then checks the saved files (C-4).

    ``added`` (F48 04 §7.3): refs of ``files`` that are new files, marked ``"new": true`` in
    the header (``v`` stays 1). None past ``OVERLAY_MAX_NEW``; a ref not among ``files`` is
    a ``ValueError``. Without ``added`` the header is exactly as before F48."""
    refs = {ref for ref, _ in files}
    if not set(added) <= refs:
        raise ValueError("every added ref must be one of the overlay's files")
    if len(files) > OVERLAY_MAX_FILES or len(set(added)) > OVERLAY_MAX_NEW:
        return None
    total = 0
    for ref, data in files:
        cap = CONFIG_MAX_BYTES if ref == CONFIG_FILENAME else SCRIPT_FILE_MAX_BYTES
        if len(data) > cap:
            return None
        total += len(data)
    if total > OVERLAY_MAX_BYTES:
        return None
    entries = [{"ref": ref, "size": len(data), **({"new": True} if ref in added else {})}
               for ref, data in files]
    header = json.dumps({"v": REPORT_VERSION, "files": entries},
                        ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(header) > OVERLAY_HEADER_MAX:
        return None
    return b"".join([header, b"\n", *(data for _, data in files)])


# --- Decoding (04 §4.3, §8.3, §8.6) ----------------------------------------------------------

def _text(value: object) -> bool:
    return isinstance(value, str) and len(value) <= REPORT_TEXT_MAX_CHARS


def _place(value: object) -> bool:
    return value is None or _text(value)


def _position(value: object) -> bool:
    return value is None or (type(value) is int and value >= 1)


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


def _items(data: dict, key: str) -> list | None:
    items = data.get(key)
    if not isinstance(items, list) or not 1 <= len(items) <= CHECK_EVENT_MAX_ITEMS:
        return None
    return items


def _problem(item: object) -> CheckItem | None:
    if not isinstance(item, dict):
        return None
    severity, code, source = item.get("severity"), item.get("code"), item.get("source")
    text, file = item.get("text"), item.get("file")
    line, column = item.get("line"), item.get("column")
    if severity not in CHECK_SEVERITIES or not isinstance(code, str) \
            or len(code) > CHECK_CODE_MAX_CHARS or not isinstance(source, str) \
            or _KIND.fullmatch(source) is None or not _text(text) or not _place(file) \
            or not _position(line) or not _position(column):
        return None
    return CheckItem(severity, code, source, text, file, line, column)


def _name(item: object) -> NameEntry | None:
    if not isinstance(item, list) or len(item) != 3:
        return None
    name, file, line = item
    if not _text(name) or not _place(file) or not _position(line):
        return None
    return NameEntry(name, file, line)


def _link(item: object) -> LabelLink | None:
    if not isinstance(item, list) or len(item) not in (5, 7):
        return None
    src, dst, kind, file, line, choice, cond = item if len(item) == 7 else (*item, None, False)
    if not _text(src) or not _text(dst) or kind not in CHECK_LINK_KINDS or not _text(file) \
            or type(line) is not int or line < 1 or not _place(choice) or type(cond) is not bool:
        return None
    return LabelLink(src, dst, kind, file, line, choice, cond)


def _all(items: list, check: Callable[[object], object | None]) -> tuple | None:
    out = []
    for item in items:
        checked = check(item)
        if checked is None:
            return None
        out.append(checked)
    return tuple(out)


def _done(data: dict) -> CheckDone | None:
    loaded, problems, seconds = data.get("loaded"), data.get("problems"), data.get("seconds")
    if type(loaded) is not bool or not _count(problems):
        return None
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        return None
    totals = data.get("name_totals", {})
    if not isinstance(totals, dict) or len(totals) > _MAX_NAME_KINDS or not all(
            isinstance(kind, str) and _KIND.fullmatch(kind) and _count(count)
            for kind, count in totals.items()):
        return None
    link_total = data.get("link_total", 0)
    if not _count(link_total):
        return None
    return CheckDone(loaded, problems, float(seconds), MappingProxyType(dict(totals)),
                     link_total)


def decode_check_line(body: bytes) -> tuple[str, object] | None:
    """One stdout line without its line break → ``(event, payload)``, or None when it isn't
    a check report line or breaks a rule (ASCII JSON of at most 1 MiB with the marker, ``v``
    1, a known event, 1 to 5,000 items, every string within ``REPORT_TEXT_MAX_CHARS``, kinds
    ``CHECK_KIND_RE``, lines and columns ints ≥ 1). Never raises. Payloads:

    - ``problems``: ``tuple[CheckItem, ...]``;
    - ``names``: ``(kind, tuple[NameEntry, ...])``;
    - ``graph``: ``tuple[LabelLink, ...]``. A link row is ``[src, dst, kind, file, line,
      choice, cond]`` (F46 ``04`` §3.5; ``v`` stays 1): ``choice`` a string or null, ``cond``
      a bool. A 5-item row (before F46) still decodes, as None and False; any other length,
      or a ``cond`` that isn't a bool, breaks the line;
    - ``done``: ``CheckDone``.
    """
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
    event = data.get("event")
    payload: object | None = None
    if event == "problems":
        items = _items(data, "items")
        payload = None if items is None else _all(items, _problem)
    elif event == "names":
        kind, items = data.get("kind"), _items(data, "items")
        if isinstance(kind, str) and _KIND.fullmatch(kind) and items is not None:
            names = _all(items, _name)
            payload = None if names is None else (kind, names)
    elif event == "graph":
        items = _items(data, "links")
        payload = None if items is None else _all(items, _link)
    elif event == "done":
        payload = _done(data)
    return None if payload is None else (event, payload)


# --- One run's lines (04 §7.2 step 5) --------------------------------------------------------

class PendingCheck:
    """The lines of one run so far. Keeps at most the §4.3 totals (patched constants are
    read at each call); anything past them is counted in ``dropped``."""

    def __init__(self) -> None:
        self.problems: list[CheckItem] = []
        self.names: dict[str, list[NameEntry]] = {}
        self.links: list[LabelLink] = []
        self.dropped = 0

    def add(self, event: str, payload: object) -> None:
        if event == "problems":
            room = CHECK_MAX_PROBLEMS - len(self.problems)
            self._keep(self.problems, payload, room)       # type: ignore[arg-type]
        elif event == "names":
            kind, entries = payload                        # type: ignore[misc]
            kept = self.names.setdefault(kind, [])
            self._keep(kept, entries, CHECK_MAX_NAMES - len(kept))
        elif event == "graph":
            self._keep(self.links, payload, CHECK_MAX_LINKS - len(self.links))  # type: ignore[arg-type]

    def _keep(self, kept: list, items: Sequence, room: int) -> None:
        room = max(room, 0)
        kept.extend(items[:room])
        self.dropped += max(len(items) - room, 0)

    def result(self, done: CheckDone, serial: int) -> CheckResult:
        names = MappingProxyType({kind: tuple(entries) for kind, entries in self.names.items()})
        return CheckResult(
            problems=tuple(self.problems),
            problem_total=max(done.problems, len(self.problems)),
            names=names,
            links=tuple(self.links) if done.loaded else None,
            loaded=done.loaded, serial=serial, seconds=done.seconds,
            name_totals=done.name_totals,
            link_total=max(done.link_total, len(self.links)))


# --- The runner (04 §7.2 steps 3-5; 07 I-2) --------------------------------------------------

class CheckState(enum.Enum):
    STARTED = "started"                 # a child was spawned for ``serial``
    DONE = "done"                       # ``result`` is the new CheckResult
    TIMEOUT = "timeout"                 # stopped after CHECK_TIMEOUT_S; old result kept
    CRASHED = "crashed"                 # no done (EOF, nonzero exit, or no spawn); old kept


@dataclass(frozen=True)
class CheckEvent:
    """A runner event for the request with ``serial``. ``result`` is set for ``DONE``;
    ``exit_code`` for ``CRASHED`` when the child exited; ``reason`` when it didn't spawn."""

    state: CheckState
    serial: int
    result: CheckResult | None = None
    exit_code: int | None = None
    reason: str | None = None


class CheckRunnerLike(Protocol):
    """What ``EditorWindow(…, check_runner=)`` needs (07 I-2); Tk tests pass a fake."""

    def request(self, overlay: bytes | None, serial: int, *, launch: bool) -> None: ...

    def poll(self) -> list[CheckEvent]: ...

    def stop(self) -> None: ...


_SPAWNED = "spawned"
_SPAWN_FAILED = "spawn failed"


def _drop(line: bytes) -> None:
    """The check child's other stdout lines go nowhere (its stdout is the null device)."""


def _run_child(popen: Callable[..., subprocess.Popen], argv: list[str], kwargs: dict,
               overlay: bytes | None, put: Callable[[tuple[str, object]], None]) -> None:
    """The child's thread: spawn, write the overlay and close stdin, then read stdout to
    EOF. Touches only the pipes and ``put``."""
    try:
        proc = popen(argv, **kwargs)
    except (OSError, ValueError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
        put((_SPAWN_FAILED, echo(reason)))
        put((EOF, None))
        return
    put((_SPAWNED, proc))
    if proc.stdin is not None:
        try:
            if overlay:
                proc.stdin.write(overlay)
        except (OSError, ValueError):
            pass                                    # the child ended or never reads stdin
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass
    read_child_output(proc.stdout, put, _drop, decode_check_line)


class _Child:
    """One check child and what the runner knows about it."""

    def __init__(self, serial: int, started_at: float,
                 messages: "queue.SimpleQueue[tuple[str, object]]",
                 thread: threading.Thread) -> None:
        self.serial = serial
        self.started_at = started_at
        self.messages = messages
        self.thread = thread
        self.proc: subprocess.Popen | None = None
        self.spawn_failed: str | None = None
        self.pending = PendingCheck()
        self.superseded = False         # a newer request waits for it to end
        self.abandoned = False          # timed out, or lingering after its done
        self.finished = False           # its done was applied
        self.finished_at: float | None = None
        self.kill_at: float | None = None
        self.killed = False
        self.eof = False
        self.exited_at: float | None = None

    @property
    def stopping(self) -> bool:
        return self.superseded or self.abandoned


class CheckRunner:
    """Runs check children for one game folder and turns them into ``CheckEvent``s.

    ``request(overlay, serial, launch=…)`` asks for a check; ``poll()`` (every 100 ms from
    the Tk loop) does the work and returns the events since the last call; ``stop()`` ends
    any child (the window closing). ``result`` is the newest applied ``CheckResult``.
    ``popen``, ``clock``, and ``argv`` are for tests."""

    def __init__(self, game_dir: Path, *,
                 popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic,
                 argv: Callable[..., list[str]] = check_argv) -> None:
        self.game_dir = Path(game_dir)
        self._popen = popen
        self._clock = clock
        self._argv = argv
        self._child: _Child | None = None
        self._pending: tuple[bytes | None, int, bool] | None = None
        self._result: CheckResult | None = None

    @property
    def result(self) -> CheckResult | None:
        return self._result

    @property
    def running(self) -> bool:
        """A check is asked for or under way (the status line's ``Checking…``)."""
        child = self._child
        return self._pending is not None or (
            child is not None and not child.stopping and not child.finished)

    @property
    def process(self) -> subprocess.Popen | None:
        """The current child process, once spawned (tests)."""
        return self._child.proc if self._child is not None else None

    def request(self, overlay: bytes | None, serial: int, *, launch: bool = True) -> None:
        """Ask for a check of the saved files plus ``overlay`` (None: no overlay, stdin is
        the null device). Supersedes any live child; the newest request spawns in ``poll``
        once the old child is gone. Never blocks."""
        self._pending = (overlay, serial, launch)
        child = self._child
        if child is not None and not child.superseded:
            child.superseded = True
            child.kill_at = self._clock() + KILL_AFTER_S
            if child.proc is not None:
                _terminate(child.proc)

    def poll(self) -> list[CheckEvent]:
        """Every event since the last call, oldest first. Never blocks."""
        events: list[CheckEvent] = []
        child = self._child
        if child is not None:
            self._drain(child, events)
            self._watch(child, events)
        if self._child is None and self._pending is not None:
            overlay, serial, launch = self._pending
            self._pending = None
            self._spawn(overlay, serial, launch, events)
        return events

    def stop(self, timeout_s: float | None = None) -> None:
        """End any child (the window closing): terminate, wait up to ``timeout_s``, then
        kill. Blocks for at most about three times ``timeout_s``."""
        timeout_s = KILL_AFTER_S if timeout_s is None else timeout_s
        self._pending = None
        child, self._child = self._child, None
        if child is None:
            return
        proc = child.proc
        if proc is None and child.spawn_failed is None:
            end = self._clock() + timeout_s
            while proc is None:
                try:
                    kind, payload = child.messages.get(timeout=max(0.0, end - self._clock()))
                except queue.Empty:
                    break
                if kind == _SPAWNED:
                    proc = payload                  # type: ignore[assignment]
                elif kind in (_SPAWN_FAILED, EOF):
                    break
        if proc is not None and proc.poll() is None:
            _terminate(proc)
            try:
                proc.wait(timeout_s)
            except subprocess.TimeoutExpired:
                _kill(proc)
                try:
                    proc.wait(timeout_s)
                except subprocess.TimeoutExpired:
                    pass
        child.thread.join(timeout_s)

    # --- Internals ----------------------------------------------------------------------

    def _spawn(self, overlay: bytes | None, serial: int, launch: bool,
               events: list[CheckEvent]) -> None:
        argv = self._argv(self.game_dir, overlay=overlay is not None, launch=launch)
        env = without_keys()             # F48 SEC-F48-22
        env["PYTHONIOENCODING"] = CHILD_ENCODING
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        kwargs: dict = {"cwd": str(engine_root()),
                        "stdin": subprocess.PIPE if overlay is not None else subprocess.DEVNULL,
                        "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL, "env": env}
        if _IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        messages: "queue.SimpleQueue[tuple[str, object]]" = queue.SimpleQueue()
        thread = threading.Thread(target=_run_child, name="vn-check-child", daemon=True,
                                  args=(self._popen, argv, kwargs, overlay, messages.put))
        self._child = _Child(serial, self._clock(), messages, thread)
        thread.start()
        events.append(CheckEvent(CheckState.STARTED, serial))

    def _drain(self, child: _Child, events: list[CheckEvent]) -> None:
        while True:
            try:
                kind, payload = child.messages.get_nowait()
            except queue.Empty:
                return
            if kind == _SPAWNED:
                child.proc = payload                # type: ignore[assignment]
                if child.stopping:
                    _terminate(child.proc)          # stopped before it was spawned
            elif kind == _SPAWN_FAILED:
                child.spawn_failed = str(payload)
            elif kind == EOF:
                child.eof = True
            elif child.stopping or child.finished:
                continue                            # never applied
            elif kind == "done":
                result = child.pending.result(payload, child.serial)   # type: ignore[arg-type]
                self._result = result
                child.finished = True
                child.finished_at = self._clock()
                events.append(CheckEvent(CheckState.DONE, child.serial, result))
            else:
                child.pending.add(kind, payload)

    def _watch(self, child: _Child, events: list[CheckEvent]) -> None:
        now = self._clock()
        proc = child.proc
        if child.spawn_failed is not None:
            self._child = None
            if not child.stopping:
                events.append(CheckEvent(CheckState.CRASHED, child.serial,
                                         reason=child.spawn_failed))
            return
        code = proc.poll() if proc is not None else None
        if code is not None and child.exited_at is None:
            child.exited_at = now
        # A child that exited ends here once its output is read; a pipe still held open by
        # something it started can't keep Studio waiting.
        ended = code is not None and (
            child.eof or now - (child.exited_at or now) >= KILL_AFTER_S)
        if child.stopping:
            if proc is not None and code is None and not child.killed and \
                    child.kill_at is not None and now >= child.kill_at:
                _kill(proc)
                child.killed = True
            if ended:
                self._child = None
            return
        if ended:
            self._child = None
            if not child.finished:
                events.append(CheckEvent(CheckState.CRASHED, child.serial, exit_code=code))
            return
        if code is None:
            if not child.finished and now - child.started_at >= CHECK_TIMEOUT_S:
                self._abandon(child, now)
                events.append(CheckEvent(CheckState.TIMEOUT, child.serial))
            elif child.finished and now - (child.finished_at or now) >= KILL_AFTER_S:
                self._abandon(child, now)           # done, but it doesn't exit

    def _abandon(self, child: _Child, now: float) -> None:
        child.abandoned = True
        child.kill_at = now + KILL_AFTER_S
        if child.proc is not None:
            _terminate(child.proc)


def _terminate(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
    except OSError:
        pass                                        # already gone


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass


__all__ = ["CheckDone", "CheckEvent", "CheckItem", "CheckResult", "CheckRunner",
           "CheckRunnerLike", "CheckState", "NameEntry", "PendingCheck", "check_argv",
           "decode_check_line", "encode_overlay"]
