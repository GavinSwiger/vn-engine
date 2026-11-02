"""Reporting a finished load to the log and console (F02 ``04-technical.md`` §7.10.1).

``report_load_result(result, log)`` writes, in this order:

1. per reported error one ERROR record ``err.format()``; for a line error with a source line,
   the line in its redacted 120-character window indented 4 spaces, and, when the error has a
   column, a caret line under it (PR-F02-34; no caret without a column, G6);
2. E100 when more errors were found than reported; the E99 note when checks were skipped;
3. every warning as WARNING (W01, W02, W03, W02b, W04 and their summary lines), in the
   order the load produced them;
4. dev runs only: each TODO as INFO up to ``SCRIPT_TODO_LOG_LIMIT``, then SR-F02-13's
   summary line;
5. on success, the PR-F02-40 INFO line.

One call writes at most ``SCRIPT_REPORT_MAX_RECORDS`` (400) records (SEC-F02-04): the
pieces above add up to 50 × 3 + 2 + 1 + 21 + 1 + 51 + 21 + 151 + 1 = 399 by construction
(I-9), and a final guard drops anything past 400. Records pass F01's redacting formatter,
which redacts and escapes again; ERROR and WARNING also reach the console through F01's
handlers.

The result is read by attribute (``errors``, ``error_count``, ``checks_skipped``,
``warnings``, ``todos``, ``todo_count``, ``program``, ``stats``), so this module needs
neither ``loader`` nor ``program``. A TODO is ``Todo(file, line, text)`` or the parser's
``(file, line, text)`` tuple; ``file`` is a ``ScriptFile`` or a ref.
"""

import logging
from typing import Any

from engine.script.limits import SCRIPT_REPORT_MAX_RECORDS, SCRIPT_TODO_LOG_LIMIT
from engine.script.messages import (
    format_message,
    loaded_line,
    source_window,
    todo_line,
    todo_more,
)

INDENT = "    "


class _Records:
    """Writes log records until the budget is used up, then drops the rest."""

    def __init__(self, log: logging.Logger, budget: int) -> None:
        self.log = log
        self.left = budget
        self.dropped = 0

    def write(self, level: int, text: str) -> None:
        if self.left <= 0:
            self.dropped += 1
            return
        self.left -= 1
        self.log.log(level, "%s", text)


def error_records(error: Any) -> list[str]:
    """The ERROR records of one reported error: the message, then (line errors with a
    source line) the line and, with a column, the caret line (§7.10.1 step 1)."""
    records = [error.format()]
    source = getattr(error, "source_line", None)
    if source is not None:
        column = getattr(error, "column", None)
        shown, caret = source_window(source, column)
        records.append(INDENT + shown)
        if caret is not None:
            records.append(INDENT + " " * caret + "^")
    return records


def _todo_parts(todo: Any) -> tuple[str, int, str]:
    if isinstance(todo, tuple):
        file, line, text = todo
    else:
        file, line, text = todo.file, todo.line, todo.text
    return getattr(file, "ref", file), line, text


def report_load_result(result: Any, log: logging.Logger) -> None:
    """Log ``result`` (area ``script``) as §7.10.1 describes. Never raises for any
    content; writes at most ``SCRIPT_REPORT_MAX_RECORDS`` records."""
    out = _Records(log, SCRIPT_REPORT_MAX_RECORDS)
    errors = tuple(result.errors)
    for error in errors:
        for text in error_records(error):
            out.write(logging.ERROR, text)
    extra = result.error_count - len(errors)
    if extra > 0:
        out.write(logging.ERROR, format_message("E100", (f"{extra:,}",)))
    if result.checks_skipped:
        out.write(logging.ERROR, format_message("E99"))

    for warning in result.warnings:
        out.write(logging.WARNING, warning.format())

    todos = tuple(result.todos)
    for todo in todos[:SCRIPT_TODO_LOG_LIMIT]:
        out.write(logging.INFO, todo_line(*_todo_parts(todo)))
    todo_count = getattr(result, "todo_count", None)
    total = len(todos) if todo_count is None else max(todo_count, len(todos))
    shown = min(len(todos), SCRIPT_TODO_LOG_LIMIT)
    if total > shown:
        out.write(logging.INFO, todo_more(total - shown))

    if result.program is not None and result.error_count == 0 and not errors:
        stats = result.stats
        out.write(logging.INFO, loaded_line(stats.files, stats.labels, stats.statements,
                                            stats.words, stats.seconds))
