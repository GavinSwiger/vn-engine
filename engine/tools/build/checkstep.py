"""The build's first step: the full check of the game, in a grandchild (F42 ``04-technical.md``
§2, §3.1, §7.1 step 1; PR-F42-11; architect decision 2).

Why this module exists: a build must not ship a game with errors, and the check runs the
game's ``define``/``default`` code, which may only run in a child (ADR-0008 Amendment 1 §5).
So the build child starts ``python -E -B -m engine check GAME --report-to-editor`` (F45's
check child, full launch: a Build arms it) and reads its report lines:

- **Report mode** (Studio): each valid ``problems`` and ``done`` line is relayed unchanged
  (``relay``), so Studio's Problems fill exactly as **Check now** fills them. ``names`` and
  ``graph`` lines are read and dropped.
- **CLI**: each problem is printed as ``file:line: severity code text`` (``plain_line``).

``run_check`` counts errors and warnings from the problem items (``config`` errors apart, for
``B_CONFIG``) and returns a ``CheckOutcome``; ``done`` missing (the check child crashed) is
``outcome.done is False``, with the child's last non-report lines (``tail``) for details.

Lines are decoded under ``core/editorreport``'s caps (``decode_line``): the marker, at most
``REPORT_MAX_BYTES``, ASCII JSON, ``v`` 1, 1 to ``CHECK_EVENT_MAX_ITEMS`` items of the problem
shape. A line breaking a rule is dropped, never relayed.

Child-only; imports ``core``, ``tools.build.procs`` and the standard library (never
``tools.check`` or ``tools.editor``: ``04`` §3.4).
"""

import collections
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Final

from engine.core.editorreport import (
    CHECK_CODE_MAX_CHARS,
    CHECK_EVENT_MAX_ITEMS,
    CHECK_KIND_RE,
    CHECK_SEVERITIES,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
    REPORT_VERSION,
)
from engine.tools.build import procs

RELAYED: Final = ("problems", "done")
TAIL_LINES: Final = 200
_KIND: Final = re.compile(CHECK_KIND_RE)


def check_argv(game_root: Path) -> list[str]:
    """The check grandchild's command (full check: no ``--no-launch``)."""
    return [sys.executable, "-E", "-B", "-m", "engine", "check", str(game_root),
            "--report-to-editor"]


@dataclass
class CheckOutcome:
    """What the check found. ``errors`` counts error items (``config_errors`` of them came
    from ``config.toml``); ``warnings`` warning items; ``problems`` is ``done``'s total."""
    errors: int = 0
    config_errors: int = 0
    warnings: int = 0
    problems: int = 0
    loaded: bool = False
    done: bool = False
    exit_code: int | None = None
    tail: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """The game can't be built: an error, or the script didn't load."""
        return self.errors > 0 or (self.done and not self.loaded)


# --- Decoding (F45 04 §4.3 shapes) -------------------------------------------------------------

def _text(value: object) -> bool:
    return isinstance(value, str) and len(value) <= REPORT_TEXT_MAX_CHARS


def _position(value: object) -> bool:
    return value is None or (type(value) is int and value >= 1)


def _problem_ok(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    code, source = item.get("code"), item.get("source")
    return (item.get("severity") in CHECK_SEVERITIES and isinstance(code, str)
            and len(code) <= CHECK_CODE_MAX_CHARS and isinstance(source, str)
            and _KIND.fullmatch(source) is not None and _text(item.get("text"))
            and (item.get("file") is None or _text(item.get("file")))
            and _position(item.get("line")) and _position(item.get("column")))


def _done_ok(data: dict) -> bool:
    seconds = data.get("seconds")
    problems = data.get("problems")
    return (type(data.get("loaded")) is bool and type(problems) is int and problems >= 0
            and type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0)


def decode_line(body: bytes) -> tuple[str, dict] | None:
    """A check report line (no line break) → ``(event, data)`` for a valid ``problems`` or
    ``done`` line, ``("other", {})`` for another valid-looking report event, else None.
    Never raises."""
    if not body.startswith(REPORT_MARKER) or len(body) > REPORT_MAX_BYTES:
        return None
    try:
        data = json.loads(body[len(REPORT_MARKER):].decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or type(data.get("v")) is not int \
            or data["v"] != REPORT_VERSION:
        return None
    event = data.get("event")
    if event == "problems":
        items = data.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= CHECK_EVENT_MAX_ITEMS \
                or not all(_problem_ok(item) for item in items):
            return None
        return event, data
    if event == "done":
        return (event, data) if _done_ok(data) else None
    return ("other", {}) if isinstance(event, str) else None


def plain_line(item: dict) -> str:
    """The CLI's problem line: ``file:line: severity code text`` (parts that are missing are
    left out)."""
    where = item.get("file") or ""
    if where and item.get("line") is not None:
        where += f":{item['line']}"
    head = " ".join(part for part in (item["severity"], item["code"]) if part)
    return f"{where}: {head} {item['text']}" if where else f"{head} {item['text']}"


# --- Running -----------------------------------------------------------------------------------

def read_lines(stream: BinaryIO) -> "collections.abc.Iterator[bytes]":
    """``stream``'s lines without line breaks, each at most just over ``REPORT_MAX_BYTES``; a
    longer line is skipped to its end."""
    limit = REPORT_MAX_BYTES + 2
    while True:
        line = stream.readline(limit)
        if not line:
            return
        if len(line) >= limit and not line.endswith(b"\n"):
            while True:
                rest = stream.readline(limit)
                if not rest or rest.endswith(b"\n"):
                    break
            continue
        yield line.rstrip(b"\r\n")


def run_check(game_root: Path, *, relay: Callable[[bytes], None] | None = None,
              show: Callable[[str], None] | None = None,
              started: Callable[[object], None] | None = None,
              popen: Callable[..., object] | None = None) -> CheckOutcome:
    """Run the check grandchild to its end. ``relay`` gets each valid ``problems``/``done``
    line (report mode); ``show`` gets each problem's ``plain_line`` (CLI). ``started`` is
    told the process as soon as it runs (the step machine kills its tree on failure)."""
    kwargs = {} if popen is None else {"popen": popen}
    proc = procs.spawn(check_argv(game_root), **kwargs)
    if started is not None:
        started(proc)
    outcome = CheckOutcome()
    tail: collections.deque[str] = collections.deque(maxlen=TAIL_LINES)
    try:
        for body in read_lines(proc.stdout):
            if not body.startswith(REPORT_MARKER):
                tail.append(body.decode("utf-8", "replace"))
                continue
            decoded = decode_line(body)
            if decoded is None or decoded[0] == "other":
                continue
            event, data = decoded
            if outcome.done:
                continue                                # nothing after done counts
            if relay is not None:
                relay(body)
            if event == "problems":
                for item in data["items"]:
                    if item["severity"] == "error":
                        outcome.errors += 1
                        outcome.config_errors += item["source"] == "config"
                    elif item["severity"] == "warning":
                        outcome.warnings += 1
                    if show is not None:
                        show(plain_line(item))
            else:
                outcome.done = True
                outcome.loaded = data["loaded"]
                outcome.problems = data["problems"]
    finally:
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
    outcome.exit_code = proc.wait()
    outcome.tail = list(tail)
    return outcome


__all__ = ["CheckOutcome", "check_argv", "decode_line", "plain_line", "read_lines",
           "run_check"]
