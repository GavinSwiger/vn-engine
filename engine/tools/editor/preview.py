"""The preview runner: start values to argv, the game child process, its reader thread, and
the report decoding (F44 ``04-technical.md`` §3 "Report line", §4, §6 item 3, §7.5;
TR-F44-08; ``07`` I-4, I-5).

Pure Python, no Tk. Preview runs the real game as a child process,
``python -m engine run <game> --report-to-editor [--start L] [--set n=v]…``, which writes
one ASCII stdout line per event: ``VN-EDITOR-REPORT `` + JSON, either ``started`` or the
fatal error with the same paragraphs as its error screen. A daemon reader thread per child
touches only the pipe and a queue: it checks the shape of every report line (a bad one is
dropped) and forwards every other line to the editor's stdout, never storing it. The window
calls ``PreviewRunner.poll`` every 100 ms; it never blocks. At most one child is alive: a
second ``start`` terminates the old child, kills it if it is still alive after 2 s, and only
then spawns the new one.

Start values are checked here, before any child starts (I-5): ``start_value_args`` runs
``core/startvalues.parse_set_list`` on the box's lines, and its problems go to the panel,
so bad start values never end a preview as "Stopped unexpectedly".

Imports only ``engine.core`` and the standard library; never pygame or ``engine.app``.
"""

import enum
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from engine.core.editorreport import (
    PHASES,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_MAX_ITEMS,
    REPORT_MAX_TAIL,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.paths import engine_root
from engine.core.redact import echo
from engine.core.startvalues import parse_set_list

# --- Protocol (04 §3 "Report line", §6 item 3; I-4) -----------------------------------------
# The marker and limits live in ``core/editorreport.py``, which the child side
# (``app/editor_link.py``) imports too, so both sides keep to the same limits.

# --- Runner (04 §7.5) -----------------------------------------------------------------------

POLL_INTERVAL_MS = 100                  # the window polls the runner this often
KILL_AFTER_S = 2.0                      # a terminated child still alive after this is killed
WINDOWS_COMMAND_MAX_CHARS = 32_000      # list2cmdline(argv) limit on Windows
CHILD_ENCODING = "utf-8:backslashreplace"
_IS_WINDOWS = os.name == "nt"

# --- Texts (03 §2.2, 04 §7.3, §7.5; I-14) ---------------------------------------------------

COULDNT_START = "Couldn't start the preview: {reason}"
TOO_LONG = ("The start values are too long to pass to the game (more than 32,000 "
            "characters).")
_MORE_PROBLEMS = re.compile(r"…and ([\d,]+) more problem")


def _plural(count: int, word: str) -> str:
    return f"{count:,} {word}" if count == 1 else f"{count:,} {word}s"


def _sentence(text: str) -> str:
    return text if text.endswith((".", "?", "!", "…")) else text + "."


# --- Reports --------------------------------------------------------------------------------

@dataclass(frozen=True)
class ReportItem:
    """One paragraph of a report. ``file``, ``line``, and ``column`` locate a line error."""

    text: str
    file: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class Report:
    """A fatal error as the panel shows it: ``head``, one paragraph per item, ``tail``.
    ``phase`` is ``"start"`` or ``"run"`` for a child's report, ``"editor"`` for a problem
    found in the editor (start values, a child that can't be spawned)."""

    phase: str
    head: str | None
    items: tuple[ReportItem, ...]
    tail: tuple[str, ...] = ()

    def paragraphs(self) -> list[str]:
        """The error screen's paragraphs, in order: head, items, tail (PR-F44-12)."""
        head = [self.head] if self.head is not None else []
        return [*head, *(item.text for item in self.items), *self.tail]

    @property
    def problem_count(self) -> int:
        """Every problem the report stands for: its items plus the ``…and N more
        problems.`` lines of its tail (F02 reports at most 50 errors)."""
        count = len(self.items)
        for line in self.tail:
            match = _MORE_PROBLEMS.match(line)
            if match is not None:
                count += int(match.group(1).replace(",", ""))
        return count


def editor_report(*paragraphs: str, head: str | None = None) -> Report:
    """A report made by the editor itself (no file, no line: nothing to click)."""
    return Report("editor", head, tuple(ReportItem(text) for text in paragraphs))


STARTED = "started"                     # a decoded ``started`` line


def decode_report(line: bytes) -> "Report | str | None":
    """One stdout line without its line break → ``STARTED``, a ``Report``, or None when it
    isn't a report line or its shape is wrong (§6 item 3: ASCII, at most 1 MiB, ``v`` 1, a
    known event, at most 60 items, every text at most 10,000 characters)."""
    if not line.startswith(REPORT_MARKER) or len(line) > REPORT_MAX_BYTES:
        return None
    try:
        data = json.loads(line[len(REPORT_MARKER):].decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return _checked(data)


def _checked(data: object) -> "Report | str | None":
    if not isinstance(data, dict):
        return None
    version = data.get("v")
    if type(version) is not int or version != REPORT_VERSION:
        return None
    event = data.get("event")
    if event == "started":
        return STARTED
    if event != "error" or data.get("phase") not in PHASES:
        return None
    if not {"head", "items", "tail"} <= data.keys():
        return None
    head, items, tail = data["head"], data["items"], data["tail"]
    if not (head is None or _text(head)):
        return None
    if not isinstance(items, list) or not 1 <= len(items) <= REPORT_MAX_ITEMS:
        return None
    if not isinstance(tail, list) or len(tail) > REPORT_MAX_TAIL or \
            not all(_text(line) for line in tail):
        return None
    checked = []
    for item in items:
        if not isinstance(item, dict) or not _text(item.get("text")):
            return None
        file, number, column = item.get("file"), item.get("line"), item.get("column")
        if not (file is None or _text(file)) or not _position(number) or \
                not _position(column):
            return None
        checked.append(ReportItem(item["text"], file, number, column))
    return Report(data["phase"], head, tuple(checked), tuple(tail))


def _text(value: object) -> bool:
    return isinstance(value, str) and len(value) <= REPORT_TEXT_MAX_CHARS


def _position(value: object) -> bool:
    return value is None or (type(value) is int and value >= 1)


# --- Reader thread (04 §7.5 "Reader thread") ------------------------------------------------

EOF = "eof"


def read_child_output(stream: BinaryIO, put: Callable[[tuple[str, object]], None],
                      forward: Callable[[bytes], None],
                      decode: Callable[[bytes], object] = decode_report) -> None:
    """Read the child's stdout to its end. Touches only ``stream``, ``put``, ``forward``,
    and ``decode``, so it may run on any thread.

    Each line is read with a limit just over 1 MiB; a line cut off by the limit is
    discarded up to its newline. A report line is decoded and its shape checked: a good one
    is ``put`` as ``(STARTED, None)`` or ``("error", Report)``, a bad one is dropped. Any
    other line is passed to ``forward`` as it was read. ``(EOF, None)`` comes last, always.

    F45 (``04`` §7.2 step 4): ``decode`` is the report decoder; one that returns a
    ``(kind, payload)`` tuple (Studio's ``decode_check_line``) has that tuple ``put``.
    """
    limit = REPORT_MAX_BYTES + 2                    # room for "\r\n"
    try:
        while True:
            line = stream.readline(limit)
            if not line:
                break
            if len(line) >= limit and not line.endswith(b"\n"):
                while True:                         # too long: skip the rest of it
                    rest = stream.readline(limit)
                    if not rest or rest.endswith(b"\n"):
                        break
                continue
            body = line[:-1] if line.endswith(b"\n") else line
            body = body[:-1] if body.endswith(b"\r") else body
            if body.startswith(REPORT_MARKER):
                decoded = decode(body)
                if decoded is None:
                    pass                            # a bad report line is dropped
                elif isinstance(decoded, tuple):
                    put(decoded)
                elif decoded == STARTED:
                    put((STARTED, None))
                else:
                    put(("error", decoded))
            else:
                forward(line)
    except (OSError, ValueError):
        pass                                        # the pipe broke or was closed
    finally:
        try:
            stream.close()
        except (OSError, ValueError):
            pass
        put((EOF, None))


def forward_to_stdout(line: bytes) -> None:
    """The editor's stdout gets the child's other lines unchanged (the author's
    ``print``s). Nothing is written when there is no stdout (``pythonw``)."""
    stream = sys.stdout
    if stream is None:
        return
    try:
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            stream.flush()
            buffer.write(line)
            buffer.flush()
        else:
            stream.write(line.decode("utf-8", "backslashreplace"))
            stream.flush()
    except (OSError, ValueError):
        pass


# --- Start values and argv (04 §4, §7.3, §7.5; I-5) -----------------------------------------

def start_values_head(count: int) -> str:
    """The panel's first line for start-value problems (04 §7.3, I-14)."""
    return f"The start values have {_plural(count, 'problem')}:"


def start_value_args(box_text: str) -> tuple[list[str], list[str]]:
    """Box lines → (['--set', 'n=v', …], problem paragraphs). Blank and # lines are skipped.

    Every problem of ``parse_set_list`` becomes ``Start values, line N: <reason>.``, where N
    counts every line of the box (I-14); more than 100 values is one ``Start values:
    <reason>.``. Any problem gives no arguments."""
    kept: list[tuple[int, str]] = []
    for number, line in enumerate(box_text.split("\n"), start=1):
        text = line.strip()
        if text and not text.startswith("#"):
            kept.append((number, text))
    _values, problems = parse_set_list([text for _, text in kept])
    if problems:
        paragraphs = []
        for problem in problems:
            if problem.index is None:
                paragraphs.append(f"Start values: {problem.reason}.")
            else:
                paragraphs.append(f"Start values, line {kept[problem.index][0]}: "
                                  f"{problem.reason}.")
        return [], paragraphs
    args: list[str] = []
    for _, text in kept:
        args += ["--set", text]
    return args, []


def start_values_report(paragraphs: Sequence[str]) -> Report:
    """The panel's report for ``start_value_args``'s problems (none clickable)."""
    return editor_report(*paragraphs, head=start_values_head(len(paragraphs)))


def preview_argv(game_dir: Path, label: str | None, set_args: list[str]) -> list[str]:
    """The child's command line (04 §7.5). No ``--start`` means the game's ``start``."""
    return [sys.executable, "-m", "engine", "run", str(game_dir), "--report-to-editor",
            *(["--start", label] if label else []), *set_args]


# --- The runner (04 §7.5) -------------------------------------------------------------------

class PreviewState(enum.Enum):
    """The six states of UI §2.2, plus the start state, one to one."""

    NOT_RUNNING = "not running"
    STARTING = "starting"
    RUNNING = "running"
    DIDNT_START = "didn't start"
    CLOSED = "closed"
    STOPPED_ERROR = "stopped with an error"
    STOPPED_UNEXPECTED = "stopped unexpectedly"


@dataclass(frozen=True)
class PreviewEvent:
    """A state change. ``report`` is what the panel shows for ``DIDNT_START`` and
    ``STOPPED_ERROR``; it is None otherwise."""

    state: PreviewState
    report: Report | None = None


class _Child:
    """One child process and what the runner knows about it."""

    def __init__(self, proc: subprocess.Popen, thread: threading.Thread,
                 messages: "queue.SimpleQueue[tuple[str, object]]") -> None:
        self.proc = proc
        self.thread = thread
        self.messages = messages
        self.superseded = False         # a newer start() is waiting for it to end
        self.kill_at: float | None = None
        self.killed = False
        self.eof = False
        self.exited_at: float | None = None
        self.kept: Report | None = None  # an error/start report, shown when it exits


class PreviewRunner:
    """Starts the preview child, reads it, and turns what it does into ``PreviewEvent``s.

    Call ``poll()`` every ``POLL_INTERVAL_MS`` from the Tk main loop; it never blocks.
    ``popen``, ``forward``, ``kill_after_s``, and ``clock`` are for tests."""

    def __init__(self, *, popen: Callable[..., subprocess.Popen] = subprocess.Popen,
                 forward: Callable[[bytes], None] = forward_to_stdout,
                 kill_after_s: float = KILL_AFTER_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._popen = popen
        self._forward = forward
        self.kill_after_s = kill_after_s
        self._clock = clock
        self._state = PreviewState.NOT_RUNNING
        self._child: _Child | None = None
        self._pending: list[str] | None = None
        self._events: list[PreviewEvent] = []

    @property
    def state(self) -> PreviewState:
        return self._state

    @property
    def process(self) -> subprocess.Popen | None:
        """The current child process (alive or not), or None."""
        return self._child.proc if self._child is not None else None

    def alive(self) -> bool:
        """Whether a child process is running now."""
        return self._child is not None and self._child.proc.poll() is None

    def start(self, argv: Sequence[str]) -> None:
        """Start a preview with ``argv`` (PR-F44-11). A child that is still alive is
        terminated first, and the new one spawns once it is gone (``poll``)."""
        argv = list(argv)
        child = self._child
        if child is not None and child.proc.poll() is None:
            self._pending = argv
            if not child.superseded:
                child.superseded = True
                child.kill_at = self._clock() + self.kill_after_s
                _terminate(child.proc)
            self._emit(PreviewState.STARTING)
            return
        self._spawn(argv)

    def poll(self) -> list[PreviewEvent]:
        """Every state change since the last call, oldest first. Never blocks."""
        child = self._child
        if child is not None:
            self._drain(child)
            code = child.proc.poll()
            now = self._clock()
            if code is not None and child.exited_at is None:
                child.exited_at = now
            # A child that exited ends here once its output is read. A pipe still held open
            # by something the child started can't keep the editor waiting forever.
            ended = code is not None and (
                child.eof or now - (child.exited_at or now) >= self.kill_after_s)
            if child.superseded:
                if code is None and not child.killed and child.kill_at is not None and \
                        now >= child.kill_at:
                    _kill(child.proc)
                    child.killed = True
                if ended:
                    self._child = None
                    pending, self._pending = self._pending, None
                    if pending is not None:
                        self._spawn(pending)
            elif ended:
                self._child = None
                self._finish(child, code)
        events, self._events = self._events, []
        return events

    def stop(self, timeout_s: float = KILL_AFTER_S) -> None:
        """End the preview (editor close, PR-F44-14): terminate, wait up to ``timeout_s``,
        then kill. Blocks for at most about twice ``timeout_s``."""
        self._pending = None
        child, self._child = self._child, None
        if child is None:
            return
        proc = child.proc
        if proc.poll() is None:
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
        if self._state in (PreviewState.STARTING, PreviewState.RUNNING):
            self._state = PreviewState.CLOSED

    # --- Internals ------------------------------------------------------------------------

    def _emit(self, state: PreviewState, report: Report | None = None) -> None:
        if state is PreviewState.STARTING and self._state is PreviewState.STARTING:
            return                                  # still starting (a restart, F5 twice)
        self._state = state
        self._events.append(PreviewEvent(state, report))

    def _spawn(self, argv: list[str]) -> None:
        self._pending = None
        self._child = None                          # an older child that already exited
        if _IS_WINDOWS and len(subprocess.list2cmdline(argv)) > WINDOWS_COMMAND_MAX_CHARS:
            self._emit(PreviewState.DIDNT_START, editor_report(TOO_LONG))
            return
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = CHILD_ENCODING
        try:
            proc = self._popen(argv, cwd=str(engine_root()), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, env=env)
        except (OSError, ValueError) as exc:
            reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            self._emit(PreviewState.DIDNT_START,
                       editor_report(COULDNT_START.format(reason=_sentence(echo(reason)))))
            return
        messages: "queue.SimpleQueue[tuple[str, object]]" = queue.SimpleQueue()
        thread = threading.Thread(target=read_child_output, name="vn-preview-reader",
                                  args=(proc.stdout, messages.put, self._forward),
                                  daemon=True)
        thread.start()
        self._child = _Child(proc, thread, messages)
        self._emit(PreviewState.STARTING)

    def _drain(self, child: _Child) -> None:
        while True:
            try:
                kind, payload = child.messages.get_nowait()
            except queue.Empty:
                return
            if kind == EOF:
                child.eof = True
            elif child.superseded:
                continue                            # an old child's news doesn't count
            elif kind == STARTED:
                if self._state is PreviewState.STARTING:
                    self._emit(PreviewState.RUNNING)
            elif isinstance(payload, Report):
                if payload.phase == "start":
                    child.kept = payload
                else:
                    self._emit(PreviewState.STOPPED_ERROR, payload)

    def _finish(self, child: _Child, code: int | None) -> None:
        if self._state is PreviewState.STOPPED_ERROR:
            return                                  # stays, with its error in the panel
        if child.kept is not None:
            self._emit(PreviewState.DIDNT_START, child.kept)
        elif code == 0:
            self._emit(PreviewState.CLOSED)
        else:
            self._emit(PreviewState.STOPPED_UNEXPECTED)


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
