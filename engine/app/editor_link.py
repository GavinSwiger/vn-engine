"""The game side of the editor report protocol (F44 ``04`` §3 "Report line", §5.3, §7.4;
``07`` I-4, I-7, I-8).

Why this module exists: the editor's Preview runs the real game as a child process with
``--report-to-editor``, and its problems panel must show exactly what the error screen
would, with each line error clickable. So the game itself reports, on its stdout, one
ASCII line per event: ``VN-EDITOR-REPORT `` + JSON (``core/editorreport.py`` holds the
marker and the limits the editor checks):

- ``{"v": 1, "event": "started"}`` once, when the story has started (``story_started``,
  called after ``build_initial_screens``, I-8);
- ``{"v": 1, "event": "error", "phase": "start" | "run", "head", "items", "tail"}`` for a
  fatal error (``fatal``). Before ``started`` the phase is ``"start"`` and the run ends with
  exit code 1 and no error screen; after it the phase is ``"run"`` and the error screen
  shows as usual (PR-F44-13).

A ``ScriptErrorGroup`` is reported from its ``parts()`` (one item per error, with its file,
line, and column), so the panel's paragraphs are the screen's paragraphs by construction
(TR-F44-05); a ``ConfigErrorGroup`` gives one item per config error, with its file and line.
Every string is redacted and cut to ``REPORT_TEXT_MAX_CHARS``. A line that would pass
``REPORT_MAX_BYTES`` loses items from the end, counted in the tail (I-4). Writing never
raises: a closed pipe or a missing stdout just loses the report (and the rest of stdout goes
to the null device, so the exit code stays the game's).

F39 hot reload (``specs/F39-hot-reload/SPEC.md`` §5.1, §5.2): the link also reads Studio's
messages on the child's stdin (``listen``: only with ``--report-to-editor``; a daemon
``StdinReader`` that touches only stdin and a queue). ``update`` runs once per frame in every
mode (error mode and minimized wakes too): ``held`` shows N5 (not on the error screen), and
``reload`` writes the ``state`` event (the place, newest first, and the window spot) on stdout
and quits at once (``request_quit(force=True)``: no quit question and no quit Auto save; the
writers still flush). In error mode the place is the list ``fatal_hook`` kept when the error
screen came up (or the list a resume that hit ``DEFAULT_FAILED`` handed to ``keep``), so the
next update resumes at the last line before the error.

Line reports (dev runs only; ``core/editorreport.py`` "Line reports"): ``update`` also
writes ``ending`` (the ending's id and title, each time an ``ending`` line runs: the
interpreter's ``ending_reached``, set by ``runtime/endings.run_ending``) and ``at`` (the
story's file, line and scene when it changes, coalesced to ``AT_PER_S`` a second, the newest
place winning). Studio reads them through ``RunWiring.on_game_event``.

Imports ``engine.core`` only (``04`` §2); ``engine_error_message`` is imported from
``app.app`` and F39's ``app.hot_reload`` when they are needed.
"""

import json
import os
import re
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, BinaryIO

from engine.core.editorreport import (
    AT_EVENT,
    AT_PER_S,
    ENDING_EVENT,
    GAME_EVENT_TEXT_MAX,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_MAX_ITEMS,
    REPORT_MAX_TAIL,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.core.errors import ConfigErrorGroup, UserFacingError
from engine.core.logsetup import get_logger
from engine.core.redact import redact

# F02's E100 tail line ("…and 3 more problems. Fix these and launch again."): its count is
# raised when items are dropped here, so the panel's problem count stays right.
_MORE_PROBLEMS = re.compile(r"…and ([\d,]+) more problems?")

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.app.hot_reload import ResumeFrame, StdinReader

_log = get_logger("app")


class EditorLink:
    """The child side of the report protocol. ``out`` is ``sys.stdout.buffer``, or None
    when there is no stdout (then nothing is written, but ``fatal`` still decides)."""

    def __init__(self, out: BinaryIO | None) -> None:
        self.out = out
        self.started = False
        # F39: Studio's messages (``listen``), the place an error-mode reload sends
        # (``fatal_hook``/``keep``; None: it can't be carried), and whether a reload is done.
        self.reader: "StdinReader | None" = None
        self.kept: list[bytes] | None = []
        self.reloaded = False
        # Line reports: the last ending run seen, the last place sent, and when the next
        # ``at`` may go (``clock`` is for tests).
        self.clock = time.monotonic
        self._ending_seen: object = None
        self._at_sent: tuple[str, int, str] | None = None
        self._at_next = 0.0

    def story_started(self) -> None:
        """Writes ``started`` once; later calls do nothing."""
        if self.started:
            return
        self.started = True
        self._write({"v": REPORT_VERSION, "event": "started"})

    def fatal(self, error: BaseException) -> bool:
        """Writes the error report. Returns True if the story hasn't started yet, in which
        case the caller exits with code 1 instead of showing the ErrorScreen."""
        try:
            report = build_report(error, phase="run" if self.started else "start")
        except Exception:
            _log.debug("The editor report could not be built", exc_info=True)
        else:
            self._write(report)
        return not self.started

    # -- F39 hot reload --

    def listen(self, stream: BinaryIO | None, *, resume: bool) -> None:
        """Start reading Studio's messages from ``stream`` (``sys.stdin.buffer``) on a
        daemon thread. ``resume`` (``--resume-from-editor``): the first thing on it is the
        resume frame. Without a stream nothing is read (a resume then gets a bad frame:
        N4)."""
        if stream is None:
            return
        from engine.app.hot_reload import StdinReader

        self.reader = StdinReader(stream, expect_resume=resume).start()

    def take_frame(self) -> "ResumeFrame | None":
        """``ResumeScreen``'s frame: the reader's (None until it is read); a bad frame when
        nothing is listening."""
        from engine.app.hot_reload import ResumeFrame

        reader = self.reader
        return ResumeFrame(None) if reader is None else reader.take_frame()

    def keep(self, lines: Sequence[bytes] | None) -> None:
        """The place an error-mode ``reload`` sends (``ResumeScreen`` after DEFAULT_FAILED:
        the states it was handed, so the next update tries the same place)."""
        self.kept = None if lines is None else list(lines)

    def fatal_hook(self, app: "App") -> None:
        """``App.add_fatal_hook``: keeps the failed story's place while ``app.story`` is
        still set (§5.2, PR-F39-05)."""
        from engine.app.hot_reload import fatal_states

        self.kept = fatal_states(app)

    def update(self, app: "App") -> None:
        """Once per frame in every mode: the line reports (dev runs), then the messages
        read since the last frame."""
        if self.reloaded:
            return
        if getattr(app, "dev", False) and not getattr(app, "error_mode", False):
            try:
                self.report_story(app)
            except Exception:
                _log.debug("A line report could not be made", exc_info=True)
        reader = self.reader
        if reader is None:
            return
        messages = reader.poll()
        if not messages:
            return
        from engine.app.hot_reload import handle_messages

        shell = app.shell

        def notify(text: str, kind: str) -> None:
            if shell is not None:
                shell.notify(text, kind=kind)                # type: ignore[arg-type]

        # F40 (04 §7.5, SEC-F40-01): console requests reach the console only in a dev run
        # with the slot filled and not in error mode; otherwise they are dropped.
        console = app.console
        studio = (console.studio if app.dev and console is not None and not app.error_mode
                  else None)
        handle_messages(messages, error_mode=app.error_mode, notify=notify,
                        reload=lambda: self._reload(app), console=studio)

    def report_story(self, app: object) -> None:
        """The line reports for this frame: ``ending`` for an ending run since the last
        frame, then ``at`` when the story's line changed and the last ``at`` is at least
        1/``AT_PER_S`` s old (a skipped place is never sent; the newest one is)."""
        story = getattr(app, "story", None)
        interp = getattr(story, "interp", None) if story is not None else None
        if interp is None:
            return
        reached = getattr(interp, "ending_reached", None)
        if reached is not None and reached is not self._ending_seen:
            self._ending_seen = reached
            _count, name, title = reached
            self._write({"v": REPORT_VERSION, "event": ENDING_EVENT,
                         "id": _short(name), "title": _short(title)})
        stmt = getattr(interp, "current", None)
        file = getattr(getattr(stmt, "file", None), "ref", None)
        line = getattr(stmt, "line", None)
        if not isinstance(file, str) or type(line) is not int or line < 1:
            return
        place = (file, line, str(getattr(stmt, "label", "")))
        now = self.clock()
        if place == self._at_sent or now < self._at_next:
            return
        self._at_sent, self._at_next = place, now + 1.0 / AT_PER_S
        self._write({"v": REPORT_VERSION, "event": AT_EVENT, "file": _short(place[0]),
                     "line": line, "scene": _short(place[2])})

    def send_line(self, data: bytes) -> None:
        """F40: one report line (``data`` without its line break) to Studio, as ``_write``
        does: a closed pipe sends the rest to the null device."""
        self._write_bytes(data + b"\n")

    def _reload(self, app: "App") -> None:
        """§5.1 step 3: the ``state`` event (none when the place can't be carried: Studio
        then starts afresh with N4), then quit at once. Never raises."""
        from engine.app.hot_reload import state_event, story_states, window_at

        self.reloaded = True
        try:
            lines = self.kept if app.error_mode else story_states(app)
            if lines is not None:
                self._write_bytes(state_event(lines, window_at(app.window)))
                _log.debug("Story update: handed %d step(s) to Studio", len(lines))
        except Exception:
            _log.debug("The place couldn't be handed to Studio", exc_info=True)
        app.request_quit(force=True)

    def _write(self, report: dict) -> None:
        self._write_bytes(encode_line(report) + b"\n")

    def _write_bytes(self, data: bytes) -> None:
        if self.out is None:
            return
        try:
            self.out.write(data)
            self.out.flush()
        except Exception:                        # a closed pipe, a stdout that can't write
            _log.debug("The editor report could not be written", exc_info=True)
            self._discard_output()

    def _discard_output(self) -> None:
        """The editor closed the pipe: send the rest of stdout to the null device, so the
        bytes still buffered can't fail the interpreter's flush at exit (which would print
        "Exception ignored" and change the exit code to 120, AC-F44-08)."""
        out, self.out = self.out, None
        try:
            fd = out.fileno()                    # type: ignore[union-attr]
            null = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(null, fd)
            finally:
                os.close(null)
        except Exception:                        # no file descriptor (a test's BytesIO)
            pass


def build_report(error: BaseException, *, phase: str) -> dict:
    """The ``error`` report object for ``error`` (``04`` §7.4 step 1), every string
    redacted and cut, trimmed to fit one line (I-4)."""
    parts = getattr(error, "parts", None)
    if isinstance(error, UserFacingError) and callable(parts):
        head, pairs, tail = parts()                       # ScriptErrorGroup
        items = [_item(text, item_error) for item_error, text in pairs]
        if not items:                       # the editor needs one item: the whole text
            head, tail, items = None, (), [_item(error.format(), None)]
    elif isinstance(error, ConfigErrorGroup) and error.errors:
        # One item per config error, each with its file and line; the screen joins their
        # format() with blank lines, as the panel does (AC-F44-09's config row).
        head, tail = None, ()
        items = [_item(each.format(), each) for each in error.errors]
    elif isinstance(error, UserFacingError):
        head, tail = None, ()
        items = [_item(error.format(), error)]
    else:
        from engine.app.app import engine_error_message

        head, tail = None, ()
        items = [_item(engine_error_message(error), None)]
    report = {"v": REPORT_VERSION, "event": "error", "phase": phase,
              "head": None if head is None else _text(head),
              "items": items, "tail": [_text(line) for line in tail][:REPORT_MAX_TAIL]}
    return _fit(report)


def encode_line(report: dict) -> bytes:
    """The marker and the JSON, ASCII only (``ensure_ascii``), without the line break."""
    return REPORT_MARKER + json.dumps(report, ensure_ascii=True,
                                      separators=(",", ":")).encode("ascii")


def _item(text: str, error: BaseException | None) -> dict:
    def position(name: str) -> int | None:
        value = getattr(error, name, None)
        return value if type(value) is int and value >= 1 else None

    file = getattr(error, "file", None)
    return {"text": _text(text),
            "file": _text(file) if isinstance(file, str) and file else None,
            "line": position("line"), "column": position("column")}


def _text(text: str) -> str:
    """Redacted, then cut to ``REPORT_TEXT_MAX_CHARS`` (redaction always runs first)."""
    text = redact(str(text))
    if len(text) > REPORT_TEXT_MAX_CHARS:
        text = text[:REPORT_TEXT_MAX_CHARS - 1] + "…"
    return text


def _short(text: str) -> str:
    """A line report's string: redacted, then cut to ``GAME_EVENT_TEXT_MAX``."""
    text = redact(str(text))
    if len(text) > GAME_EVENT_TEXT_MAX:
        text = text[:GAME_EVENT_TEXT_MAX - 1] + "…"
    return text


def _fit(report: dict) -> dict:
    """I-4: drop items from the end until there are at most ``REPORT_MAX_ITEMS`` and the
    line fits ``REPORT_MAX_BYTES``, and count them in the tail. One item always stays (then
    tail lines go from the end, which F02's short tails never need)."""
    items: list[dict] = report["items"]
    tail: list[str] = report["tail"]

    def with_items(count: int) -> dict:
        dropped = len(items) - count
        return {**report, "items": items[:count],
                "tail": _more(tail, dropped) if dropped else tail}

    count = min(len(items), REPORT_MAX_ITEMS)
    # Each item adds its JSON and a comma; start from the largest count that can fit.
    base = len(encode_line(with_items(0)))
    sizes = [len(json.dumps(item, ensure_ascii=True, separators=(",", ":"))) + 1
             for item in items[:count]]
    while count > 1 and base + sum(sizes[:count]) > REPORT_MAX_BYTES:
        count -= 1
    fitted = with_items(count)
    while len(encode_line(fitted)) > REPORT_MAX_BYTES:
        if count > 1:
            count -= 1
            fitted = with_items(count)
        elif fitted["tail"]:
            fitted = {**fitted, "tail": fitted["tail"][:-1]}
        else:
            break                       # cannot happen: one item and a head are < 130 KB
    return fitted


def _more(tail: list[str], dropped: int) -> list[str]:
    """``tail`` with ``dropped`` more problems counted in its ``…and N more problems.`` line
    (F02's E100), or with such a line added at the front."""
    tail = list(tail)
    for index, line in enumerate(tail):
        match = _MORE_PROBLEMS.match(line)
        if match is not None:
            count = int(match.group(1).replace(",", "")) + dropped
            tail[index] = f"…and {count:,} more problems" + line[match.end():]
            return tail
    tail.insert(0, f"…and {dropped:,} more problem{'' if dropped == 1 else 's'}.")
    return tail[:REPORT_MAX_TAIL]
