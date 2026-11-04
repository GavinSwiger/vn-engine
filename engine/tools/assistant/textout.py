"""The only forms a tool result takes (F48 ``04-technical.md`` §3.1; ``05-security.md``
SEC-F48-09, SEC-F48-21; 01 §7.2).

Why this module exists: game files can carry text written to steer the model ("Ignore
previous instructions…", a raw line break and a fake "Tool result:" header). So game text
reaches a result in exactly two shapes, and no content line can pose as framing:

- **Numbered-line blocks** (SEC-F48-09 (a)): script and ``config.toml`` text sits under a
  fixed header (``script/ch2.vns, lines 1–48:``) and every physical line carries its number
  (`` 9 label start:``). Diffs use the same form with a mark column (`` 14 ``, ``-15 ``,
  ``+15 ``). Each line's hidden characters are made ``visible``, so U+2028 or a stray CR can't
  start a line of its own.
- **One-liners** (SEC-F48-09 (b)): every other content string (a name, choice text, problem
  text, file or asset name, the title) passes ``one_line``: ``echo()``'s redaction and
  escapes, every Cc/Cf/Cs/Zl/Zp character as ``\\uNNNN``, cut at 200.

Everything else is engine text. Lists stop at their cap with "…and N more" (01 §7.2), and a
whole result stops at 60,000 characters at a line boundary, ending "…and N more lines".

``TextOut`` builds a result line by line and keeps the ``SentRecord`` of what it actually
put in (script line ranges, ``config.toml``, the problem count, whether asset or file names
went out), so the pane's Sent line comes from the tool layer, never from model text
(SEC-F48-21). ``ToolText`` is the finished text plus that record.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.core.redact import redact
from engine.script.assetgroups import CONFIG_REF
from engine.tools.assistant.refs import ONE_LINE_MAX_CHARS, one_line, visible

# --- Caps (01 §7.2) -------------------------------------------------------------------------

TOOL_TEXT_MAX_CHARS: Final = 60_000
READ_MAX_LINES: Final = 800
HITS_MAX: Final = 200
NAMES_MAX: Final = 500                   # per kind
PROBLEMS_MAX: Final = 200
ARROWS_MAX: Final = 2_000
USES_MAX: Final = 50
SEARCH_TEXT_MAX_CHARS: Final = 200
DOC_SECTION_MAX_CHARS: Final = 8_000

MORE: Final = "…and {n:,} more"
MORE_LINES: Final = "…and {n:,} more lines"
# Room kept for the closing "…and N more lines" so a full result still ends with it.
_RESERVE: Final = 40

__all__ = ["ARROWS_MAX", "DOC_SECTION_MAX_CHARS", "HITS_MAX", "MORE", "MORE_LINES", "NAMES_MAX",
           "ONE_LINE_MAX_CHARS", "PROBLEMS_MAX", "READ_MAX_LINES", "SEARCH_TEXT_MAX_CHARS",
           "SentRecord", "TOOL_TEXT_MAX_CHARS", "TextOut", "ToolText", "USES_MAX",
           "block_header", "capped", "line_width", "numbered_line", "one_line"]


# --- The Sent record (SEC-F48-21) -----------------------------------------------------------

Range = tuple[str, int, int]             # (ref, first line, last line), 1-based, inclusive


def merge_ranges(ranges: Iterable[Range]) -> tuple[Range, ...]:
    """Overlapping or touching ranges of one ref joined; refs in first-seen order, each
    ref's ranges by line."""
    by_ref: dict[str, list[tuple[int, int]]] = {}
    for ref, first, last in ranges:
        by_ref.setdefault(ref, []).append((first, last))
    merged: list[Range] = []
    for ref, spans in by_ref.items():
        spans.sort()
        start, end = spans[0]
        for first, last in spans[1:]:
            if first <= end + 1:
                end = max(end, last)
            else:
                merged.append((ref, start, end))
                start, end = first, last
        merged.append((ref, start, end))
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class SentRecord:
    """What one result (or, merged, one answer) sent of the game.

    ``ranges``: script or ``config.toml`` lines sent in numbered blocks (merged);
    ``config``: ``config.toml`` text or values went out; ``problems``: how many problems were
    listed; ``names``: asset or file names went out (``list_files``, ``names``,
    ``project_summary``)."""

    ranges: tuple[Range, ...] = ()
    config: bool = False
    problems: int = 0
    names: bool = False

    def merge(self, other: "SentRecord") -> "SentRecord":
        """Both records together (an answer's steps)."""
        return SentRecord(merge_ranges((*self.ranges, *other.ranges)),
                          self.config or other.config, self.problems + other.problems,
                          self.names or other.names)

    @property
    def empty(self) -> bool:
        return not (self.ranges or self.config or self.problems or self.names)


@dataclass(frozen=True, slots=True)
class ToolText:
    """One tool result: the text the model gets, the record of what it sent, and whether
    it is a tool fault (MCP ``isError``)."""

    text: str
    sent: SentRecord = field(default_factory=SentRecord)
    is_error: bool = False

    @classmethod
    def error(cls, text: str) -> "ToolText":
        return cls(text, SentRecord(), True)


# --- Line forms -----------------------------------------------------------------------------

def line_width(last: int) -> int:
    """The number column's width for a block whose highest line number is ``last``."""
    return len(str(max(last, 1)))


def numbered_line(number: int, text: str, width: int, mark: str = "") -> str:
    """One content line: ``mark`` (``""``, or ``" "``/``"-"``/``"+"`` in a diff), the number
    right-aligned to ``width``, a space, then the line redacted with its hidden characters
    ``visible``. The line is never cut."""
    return f"{mark}{number:>{width}} {visible(redact(text))}"


def block_header(ref: str, first: int, last: int) -> str:
    """``script/ch2.vns, lines 1–48:`` (the ref as a one-liner); ``…, no lines:`` for an
    empty range."""
    if last < first:
        return f"{one_line(ref)}, no lines:"
    return f"{one_line(ref)}, lines {first}–{last}:"


def capped(rows: Sequence[str], cap: int, total: int | None = None) -> list[str]:
    """The first ``cap`` rows, then "…and N more" when ``total`` (default ``len(rows)``)
    is larger."""
    total = len(rows) if total is None else total
    kept = list(rows[:cap])
    if total > len(kept):
        kept.append(MORE.format(n=total - len(kept)))
    return kept


# --- The builder ----------------------------------------------------------------------------

class TextOut:
    """A result built line by line, at most ``limit`` characters in all.

    Every add is a whole line. Once a line doesn't fit, it and every later line are counted,
    not kept, and ``result`` ends with "…and N more lines". ``line`` is for engine text;
    game text goes through ``echo`` (one line) or ``block`` (numbered lines)."""

    def __init__(self, limit: int = TOOL_TEXT_MAX_CHARS) -> None:
        self._limit = limit
        self._lines: list[str] = []
        self._size = 0
        self._dropped = 0
        self._ranges: list[Range] = []
        self._config = False
        self._problems = 0
        self._names = False

    @property
    def full(self) -> bool:
        """A line has been dropped: later lines will be too."""
        return self._dropped > 0

    def _add(self, text: str) -> bool:
        cost = len(text) + (1 if self._lines else 0)
        if self._dropped or self._size + cost > self._limit - _RESERVE:
            self._dropped += 1
            return False
        self._lines.append(text)
        self._size += cost
        return True

    def line(self, text: str = "") -> bool:
        """Engine text (each ``\\n``-separated part is a line). False once full."""
        kept = True
        for part in text.split("\n"):
            kept = self._add(part) and kept
        return kept

    def echo(self, label: str, value: str, limit: int = ONE_LINE_MAX_CHARS) -> bool:
        """``label`` (engine text) followed by ``value`` as a one-liner."""
        return self._add(label + one_line(value, limit))

    def rows(self, rows: Iterable[str], cap: int, total: int | None = None) -> int:
        """Up to ``cap`` prepared one-line rows, then "…and N more" for the rest of
        ``total`` (default: the rows given). Returns how many rows were kept."""
        kept = given = 0
        for row in rows:
            given += 1
            if given <= cap and self._add(row):
                kept += 1
        total = given if total is None else max(total, given)
        if total > kept:
            if self.full:
                self._dropped += 1           # the "more" line is one more line not sent
            else:
                self._add(MORE.format(n=total - kept))
        return kept

    def block(self, ref: str, lines: Sequence[str], first: int = 1, *,
              header: bool = True) -> int:
        """A numbered-line block of ``lines`` (no line breaks inside) starting at line
        ``first``, under ``block_header`` unless ``header`` is False. Records the range it
        actually kept (``config.toml`` also sets ``config``) and returns its last line
        number (``first - 1`` when none fit)."""
        last = first + len(lines) - 1
        if header and not self._add(block_header(ref, first, last)):
            self._dropped += len(lines)
            return first - 1
        width = line_width(last)
        sent = first - 1
        for offset, text in enumerate(lines):
            if not self._add(numbered_line(first + offset, text, width)):
                self._dropped += len(lines) - offset - 1
                break
            sent = first + offset
        if sent >= first:
            self.record_range(ref, first, sent)
        return sent

    # -- the record --------------------------------------------------------------------------

    def record_range(self, ref: str, first: int, last: int) -> None:
        """Lines ``first..last`` of ``ref`` went out (e.g. a diff's context)."""
        self._ranges.append((ref, first, last))
        if ref == CONFIG_REF:
            self._config = True

    def record_config(self) -> None:
        """``config.toml`` values went out (``game_settings``, ``project_summary``)."""
        self._config = True

    def record_problems(self, count: int) -> None:
        self._problems += max(count, 0)

    def record_names(self) -> None:
        """Asset or file names went out."""
        self._names = True

    @property
    def sent(self) -> SentRecord:
        return SentRecord(merge_ranges(self._ranges), self._config, self._problems,
                          self._names)

    def text(self) -> str:
        lines = list(self._lines)
        if self._dropped:
            lines.append(MORE_LINES.format(n=self._dropped))
        return "\n".join(lines)

    def result(self, *, is_error: bool = False) -> ToolText:
        return ToolText(self.text(), self.sent, is_error)
