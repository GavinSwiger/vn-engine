"""Light syntax coloring, the start label above the cursor, and the indent unit
(F44 ``04-technical.md`` §7.6 "Coloring", "Indent"; ``03-ui.md`` §1.2; PR-F44-05, 07, 09).

Pure Python, no Tk: ``color_spans`` returns ranges and the window applies them as tags. The
coloring is cosmetic and works one physical line at a time, so it is a small scanner rather
than F02's lexer. Its spans never overlap, so the precedence of ``03`` §1.2 (a comment beats
a text tag, a tag beats quoted text, quoted text beats the rest) is decided here and the Tk
tag priority doesn't matter.
"""

import re
from collections.abc import Sequence

from engine.script.words import STATEMENT_WORDS
from engine.tools.editor.theme import THEME

# The seven syntax tags and their colors (03 §1.2, Dark+ as amended 2026-11-02, regular
# weight, no slant).
TAG_COMMENT = "comment"
TAG_KEYWORD = "keyword"
TAG_LABEL = "label_name"
TAG_SPEAKER = "speaker"
TAG_QUOTE = "quote"
TAG_TEXT_TAG = "text_tag"
TAG_PYTHON = "python"
SYNTAX_TAGS: tuple[str, ...] = (TAG_COMMENT, TAG_KEYWORD, TAG_LABEL, TAG_SPEAKER, TAG_QUOTE,
                                TAG_TEXT_TAG, TAG_PYTHON)
TAG_COLORS: dict[str, str] = {
    TAG_COMMENT: THEME["syntax.comment"],
    TAG_KEYWORD: THEME["syntax.keyword"],
    TAG_LABEL: THEME["syntax.label"],
    TAG_SPEAKER: THEME["syntax.speaker"],
    TAG_QUOTE: THEME["syntax.quote"],
    TAG_TEXT_TAG: THEME["syntax.textTag"],
    TAG_PYTHON: THEME["syntax.python"],
}
PLAIN_COLOR = THEME["editor.foreground"]   # everything else (names, numbers, "=", ":")

# Matched at column 0 only (with .match): the start label of a line (PR-F44-09).
LABEL_LINE = re.compile(r"label[ \t]+([^\W\d]\w*)")

DEFAULT_INDENT = "    "
_MAX_INDENT_SPACES = 8
_LABEL_WORDS = frozenset(("label", "jump", "call"))
_WORD = re.compile(r"[^\W\d]\w*")
_NAME_AFTER = re.compile(r"[ \t]+([^\W\d]\w*)")
_SPEAKER = re.compile(r"([^\W\d]\w*(?:[ \t]+\w+)*)[ \t]*\"")
_QUOTE_OR_COMMENT = re.compile(r"[\"#]")
_PY_STOP = re.compile(r"[\"'#]")
_TIME = re.compile(r"[ \t]+(time)\b")                     # F51, after a leading ``menu``
_TIMEOUT = re.compile(r"[ \t]+(timeout)(?=[ \t]*:)")      # F51, between a choice and ":"
_FIRST_INDENT = re.compile(r"^([ \t]+)[^ \t\r\n#]", re.MULTILINE)

Span = tuple[int, int, str]


def color_spans(line: str) -> list[Span]:
    """Non-overlapping ``(start, end, tag)`` spans of one line, sorted, inside the line.
    Never raises; an unclosed quote colors to the end of the line."""
    spans: list[Span] = []
    n = len(line)
    start = n - len(line.lstrip(" \t"))
    if start == n:
        return spans
    if line[start] == "$":
        code_end = _python_end(line, start + 1)
        stop = code_end
        while stop > start and line[stop - 1] in " \t":
            stop -= 1
        spans.append((start, stop, TAG_PYTHON))
        if code_end < n:
            spans.append((code_end, n, TAG_COMMENT))
        return spans
    pos = start
    word = _WORD.match(line, start)
    if line[start] == '"':                          # F51: "text" timeout: (a timed choice)
        end, closed = _string_end(line, start + 1, '"')
        _quote_with_tags(line, start, end, closed, spans)
        pos = end
        mark = _TIMEOUT.match(line, pos) if closed else None
        if mark is not None:
            spans.append((mark.start(1), mark.end(1), TAG_KEYWORD))
            pos = mark.end(1)
    elif word is not None and word.group() in STATEMENT_WORDS:
        spans.append((word.start(), word.end(), TAG_KEYWORD))
        pos = word.end()
        if word.group() == "menu":                  # F51: menu time 5:
            time = _TIME.match(line, pos)
            if time is not None:
                spans.append((time.start(1), time.end(1), TAG_KEYWORD))
                pos = time.end(1)
        if word.group() in _LABEL_WORDS:
            name = _NAME_AFTER.match(line, pos)
            if name is not None:
                spans.append((name.start(1), name.end(1), TAG_LABEL))
                pos = name.end(1)
    elif word is not None:
        speaker = _SPEAKER.match(line, start)
        if speaker is not None:
            spans.append((speaker.start(1), speaker.end(1), TAG_SPEAKER))
            pos = speaker.end(1)
    _scan_text(line, pos, spans)
    return spans


def _scan_text(line: str, pos: int, spans: list[Span]) -> None:
    """Quoted text (with ``\\"`` escapes and text tags inside) and a ``#`` comment outside
    quotes, from ``pos`` to the end of the line."""
    n = len(line)
    while pos < n:
        found = _QUOTE_OR_COMMENT.search(line, pos)
        if found is None:
            return
        at = found.start()
        if line[at] == "#":
            spans.append((at, n, TAG_COMMENT))
            return
        end, closed = _string_end(line, at + 1, '"')
        _quote_with_tags(line, at, end, closed, spans)
        pos = end


def _string_end(line: str, pos: int, quote: str) -> tuple[int, bool]:
    """(index just past the closing ``quote``, True), or (the line's length, False) if the
    string is never closed. ``\\`` escapes the next character."""
    n = len(line)
    while pos < n:
        char = line[pos]
        if char == "\\":
            pos += 2
        elif char == quote:
            return pos + 1, True
        else:
            pos += 1
    return n, False


def _quote_with_tags(line: str, start: int, end: int, closed: bool,
                     spans: list[Span]) -> None:
    """The quote span ``[start, end)`` split around ``{…}`` text tags (``{{`` is a literal
    brace). A tag never includes the closing quote."""
    inner_end = end - 1 if closed else end
    pos = start
    j = start + 1
    while j < inner_end:
        char = line[j]
        if char == "\\":
            j += 2
            continue
        if char != "{":
            j += 1
            continue
        if line.startswith("{{", j):
            j += 2
            continue
        close = line.find("}", j + 1, inner_end)
        if close < 0:
            break
        reopen = line.find("{", j + 1, close)
        if reopen >= 0:
            j = reopen
            continue
        if j > pos:
            spans.append((pos, j, TAG_QUOTE))
        spans.append((j, close + 1, TAG_TEXT_TAG))
        pos = close + 1
        j = pos
    if end > pos:
        spans.append((pos, end, TAG_QUOTE))


def _python_end(line: str, pos: int) -> int:
    """Where the code of a ``$`` line ends: at a ``#`` outside Python strings (``'`` and
    ``"``, with ``\\`` escapes), or at the end of the line."""
    n = len(line)
    while pos < n:
        found = _PY_STOP.search(line, pos)
        if found is None:
            return n
        at = found.start()
        if line[at] == "#":
            return at
        pos = _string_end(line, at + 1, line[at])[0]
    return n


def label_above(lines: Sequence[str], line: int) -> str | None:
    """The start label for the cursor on 1-based ``line``: the nearest line at or above it
    that starts with ``label`` and a space or tab at column 0, read with ``LABEL_LINE``.
    None (the beginning) if there is none or that line names no valid label. The window
    does the same search with ``Text.search``."""
    for index in range(min(line, len(lines)) - 1, -1, -1):
        text = lines[index]
        if text.startswith(("label ", "label\t")):
            match = LABEL_LINE.match(text)
            return match.group(1) if match is not None else None
    return None


def indent_unit(text: str) -> str:
    """The file's indent step: ``"\\t"`` if its first indented line (not blank, not a
    comment) starts with a tab, otherwise that line's leading spaces (at most 8). Four
    spaces for a file with no indented line."""
    found = _FIRST_INDENT.search(text)
    if found is None:
        return DEFAULT_INDENT
    lead = found.group(1)
    if lead.startswith("\t"):
        return "\t"
    spaces = len(lead) - len(lead.lstrip(" "))
    return " " * min(spaces, _MAX_INDENT_SPACES)
