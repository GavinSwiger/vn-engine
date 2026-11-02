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

Imports ``engine.core`` only (``04`` §2); ``engine_error_message`` is imported from
``app.app`` when it is needed.
"""

import json
import os
import re
from typing import BinaryIO

from engine.core.editorreport import (
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

_log = get_logger("app")


class EditorLink:
    """The child side of the report protocol. ``out`` is ``sys.stdout.buffer``, or None
    when there is no stdout (then nothing is written, but ``fatal`` still decides)."""

    def __init__(self, out: BinaryIO | None) -> None:
        self.out = out
        self.started = False

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

    def _write(self, report: dict) -> None:
        if self.out is None:
            return
        try:
            self.out.write(encode_line(report) + b"\n")
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
