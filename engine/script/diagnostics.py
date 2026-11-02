"""Load diagnostics: the bounded error sink, ``ScriptError``, and Python warnings
(F02 ``04-technical.md`` §4.3, §7.11).

A ``Diagnostic`` is lazy: its text is built only for the errors that are reported. The
``DiagnosticSink`` counts every error but keeps only the first ``SCRIPT_MAX_ERRORS`` in
reading order (a max-heap of size 50), so memory stays O(50) even for a 16 MB file of bad
lines (TR-F02-06). It also applies SR-F02-15 and SR-F02-68: nothing more for a file after
E01a/E01b/E02/E05, no E10–E15 for a file after its first E10/E10c, and one error per
logical line.
"""

import heapq
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field

from engine.core.errors import UserFacingError
from engine.script.limits import SCRIPT_MAX_ERRORS, SCRIPT_W03_LIMIT
from engine.script.messages import format_message, problems_head, source_window
from engine.script.nodes import ScriptFile

# File order used for file-less (whole-game) diagnostics: they sort after every file.
_BIG = 1 << 40

# I-18: file-less errors sort as E06, E06b, E06c, E06d, E07, E26, E05b (the limit errors sit
# with E06, which they extend); F44 C2 puts the start-option errors E26b, E26c after E26.
# Other file-less codes come after them.
FILELESS_ORDER: tuple[str, ...] = ("E06", "E06b", "E06c", "E06d", "E07", "E26", "E26b", "E26c",
                                   "E05b")
_FILELESS_RANK = {code: rank for rank, code in enumerate(FILELESS_ORDER)}

# After one of these, a file reports nothing more (§7.11).
_FILE_ENDING = frozenset(("E01a", "E01b", "E02", "E05"))
# SR-F02-15: after the first E10/E10c, the file gets no more indentation errors.
_KIND_ERRORS = frozenset(("E10", "E10c"))
_INDENT_ERRORS = frozenset(("E10", "E10c", "E11", "E12", "E13", "E14", "E15"))
# Remember this many recent logical lines for the one-error-per-line rule.
_RECENT_LINES = 8


@dataclass(slots=True)
class Diagnostic:
    """One problem found while loading. ``stmt`` is the first line of the logical line it
    belongs to (SR-F02-68); ``source_line`` is the physical line, for the report."""

    code: str
    file: ScriptFile | None = None
    line: int | None = None
    column: int | None = None
    args: tuple = ()
    whole_file: bool = False
    source_line: str | None = None
    stmt: int | None = None
    seq: int = 0

    @property
    def order(self) -> tuple[int, int, int, int]:
        """``(file order | BIG, line, column, seq)`` (§4.3)."""
        if self.file is None:
            rank = _FILELESS_RANK.get(self.code, len(FILELESS_ORDER))
            return (_BIG + rank, 0, 0, self.seq)
        return (self.file.order, self.line or 0, self.column or 0, self.seq)

    def message(self) -> str:
        return format_message(self.code, self.args)

    def to_error(self) -> "ScriptError":
        if self.file is None or self.whole_file:
            return ScriptError(self.message(), code=self.code)
        return ScriptError(self.message(), code=self.code, file=self.file.ref,
                           line=self.line, column=self.column, source_line=self.source_line)


class ScriptError(UserFacingError):
    """One reported script problem. Line errors format as
    ``script/a.vns, line 5, column 3: <message>`` (SR-F02-67); whole-file and whole-game
    errors have no file or line and name the file in the message (F01 I-2)."""

    def __init__(self, message: str, *, code: str, file: str | None = None,
                 line: int | None = None, column: int | None = None,
                 source_line: str | None = None) -> None:
        super().__init__(message, file=file, line=line, column=column)
        self.code = code
        self.source_line = source_line
        self.caret = column


class ScriptErrorGroup(UserFacingError):
    """Every reported error of one load, shown together on the error screen (§7.10.2,
    PR-F02-30). ``format()`` is built from ``parts()``, so the two can't differ (F44 C2,
    TR-F44-05): ``"\\n\\n".join([head, *paragraphs, *tail])``.

    ``errors`` are the reported errors (at most ``SCRIPT_MAX_ERRORS``), ``total`` is every
    error found (``LoadResult.error_count``), and ``checks_skipped`` adds the E99 note."""

    def __init__(self, errors: Sequence[ScriptError], total: int | None = None, *,
                 checks_skipped: bool = False) -> None:
        self.errors = tuple(errors)
        self.total = len(self.errors) if total is None else total
        self.checks_skipped = checks_skipped
        super().__init__(self.format())

    @classmethod
    def from_result(cls, result: object) -> "ScriptErrorGroup":
        """The group for a ``LoadResult`` (``errors``, ``error_count``, ``checks_skipped``)."""
        return cls(result.errors, result.error_count,           # type: ignore[attr-defined]
                   checks_skipped=result.checks_skipped)        # type: ignore[attr-defined]

    def parts(self) -> tuple[str, tuple[tuple[ScriptError, str], ...], tuple[str, ...]]:
        """(head, (error, paragraph) in order, tail lines). A paragraph is the error's
        ``format()`` and, for a line error, its source line in the redacted 120-character
        window, indented 4 spaces, with no caret (the screen font isn't monospaced). The
        tail is E100 when errors were left out, then E99 when checks were skipped."""
        items = []
        for error in self.errors:
            text = error.format()
            if error.source_line is not None:
                shown, _ = source_window(error.source_line, error.column)
                text += "\n    " + shown
            items.append((error, text))
        tail = []
        extra = self.total - len(self.errors)
        if extra > 0:
            tail.append(format_message("E100", (f"{extra:,}",)))
        if self.checks_skipped:
            tail.append(format_message("E99"))
        return problems_head(self.total), tuple(items), tuple(tail)

    def format(self) -> str:
        head, items, tail = self.parts()
        return "\n\n".join([head, *(text for _, text in items), *tail])


class ScriptWarning(UserFacingError):
    """A load warning (W01, W02, W02b, W03, W03b, W04; F05's W42 has a column). The game
    still starts."""

    def __init__(self, message: str, *, code: str, file: str | None = None,
                 line: int | None = None, column: int | None = None) -> None:
        super().__init__(message, file=file, line=line, column=column)
        self.code = code


class DiagnosticSink:
    """Counts every error and keeps the ``limit`` first ones in reading order."""

    def __init__(self, limit: int = SCRIPT_MAX_ERRORS) -> None:
        self.limit = limit
        self.error_count = 0
        self._heap: list[tuple[tuple[int, int, int, int], Diagnostic]] = []
        self._seq = 0
        self._ended_files: set[int] = set()
        self._kind_done: set[int] = set()
        self._recent: deque[tuple[int, int]] = deque(maxlen=_RECENT_LINES)

    def file_ended(self, file: ScriptFile) -> bool:
        """True after E01a/E01b/E02/E05 for ``file``."""
        return file.order in self._ended_files

    def kind_done(self, file: ScriptFile) -> bool:
        """True after the first E10/E10c of ``file``."""
        return file.order in self._kind_done

    def add(self, diag: Diagnostic) -> bool:
        """Count and keep ``diag`` unless a rule drops it. Returns True if counted."""
        file = diag.file
        if file is not None:
            if file.order in self._ended_files:
                return False
            if diag.code in _INDENT_ERRORS and file.order in self._kind_done:
                return False
            if diag.stmt is not None:
                key = (file.order, diag.stmt)
                if key in self._recent:
                    return False
                self._recent.append(key)
            if diag.code in _FILE_ENDING:
                self._ended_files.add(file.order)
            elif diag.code in _KIND_ERRORS:
                self._kind_done.add(file.order)
        self._seq += 1
        diag.seq = self._seq
        self.error_count += 1
        key = diag.order
        entry = (tuple(-part for part in key), diag)
        if len(self._heap) < self.limit:
            heapq.heappush(self._heap, entry)
        elif entry[0] > self._heap[0][0]:          # smaller order than the largest kept
            heapq.heapreplace(self._heap, entry)
        return True

    def line_has_error(self, file: ScriptFile, stmt: int) -> bool:
        """True if an error was counted for the logical line starting at ``stmt``."""
        return (file.order, stmt) in self._recent

    def kept(self) -> list[Diagnostic]:
        """The kept diagnostics in reading order."""
        return [diag for _, diag in sorted(self._heap, key=lambda e: e[1].order)]

    def errors(self) -> tuple[ScriptError, ...]:
        """The kept diagnostics formatted (the only place their text is built)."""
        return tuple(diag.to_error() for diag in self.kept())


@dataclass
class WarningLog:
    """Load warnings in found order. W03 is capped at ``SCRIPT_W03_LIMIT`` per load; the
    rest are only counted, for W03b (SR-F02-76, SEC-F02-04)."""

    warnings: list[ScriptWarning] = field(default_factory=list)
    w03_count: int = 0

    def add_w03(self, file: ScriptFile, line: int, text: str) -> None:
        self.w03_count += 1
        if self.w03_count <= SCRIPT_W03_LIMIT:
            self.warnings.append(ScriptWarning(format_message("W03", (text,)), code="W03",
                                               file=file.ref, line=line))

    def finish(self) -> tuple[ScriptWarning, ...]:
        """Every warning, plus the W03b summary when W03s were dropped."""
        result = list(self.warnings)
        extra = self.w03_count - SCRIPT_W03_LIMIT
        if extra > 0:
            result.append(ScriptWarning(format_message("W03b", (f"{extra:,}",)), code="W03b"))
        return tuple(result)
