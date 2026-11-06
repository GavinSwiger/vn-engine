"""The statement reader and its two scanners (F02 ``04-technical.md`` §7.3, §7.4).

``StatementReader`` turns the physical lines of one file into ``RawStatement``s: one per
logical line, with its continuation lines pulled in. Blank and comment lines produce no
statement. The tail of a statement is read by one of two scanners:

* ``ScriptScanner`` (here: ``StatementReader._scan_script``) for script text: names,
  quoted text (SR-F02-23–33), include paths, ``:``, ``=``, and symbols;
* ``PyScanner`` for Python: it decides only where a piece of Python ends and, for
  conditions, which ``:`` ends it (§7.4); ``compile()`` decides whether it is valid.

Errors found while reading a statement are not reported at once: they are kept on the
``RawStatement`` (``pending``) so that the block parser can report the first of them together
with the statement's own errors, one error per logical line (SR-F02-68). Errors on lines that
produce no statement (long, blank, or comment lines) go to the sink directly.
"""

import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

from engine.script.diagnostics import Diagnostic, DiagnosticSink
from engine.script.limits import SCRIPT_MAX_LINE_CHARS, SCRIPT_PY_PIECE_MAX_CHARS
from engine.script.messages import E50_CHARS, E51_CHARS, INVISIBLE_CHARS
from engine.script.nodes import ScriptFile
from engine.script.source import SEPARATORS, LineCursor, PhysicalLine
from engine.script.words import canonical_name, is_word_char

# --- Token kinds (§7.3.2) ----------------------------------------------------------------
NAME = "NAME"
STRING = "STRING"
PATH = "PATH"
COLON = "COLON"
FWCOLON = "FWCOLON"
EQUALS = "EQUALS"
SYMBOL = "SYMBOL"
CURLY = "CURLY"
SQUOTE = "SQUOTE"

# Tails (§5.1). "path" is the include statement's literal path string (§6.1).
TAIL_SCRIPT = "script"
TAIL_PATH = "path"
TAIL_CONDITION = "py_condition"
TAIL_AFTER_EQUALS = "py_after_equals"
TAIL_PY_ALL = "py_all"

# Heads (SR-F02-40).
HEAD_PYTHON = "$"
HEAD_NARRATION = '"'
HEAD_WORD = "word"
HEAD_ERROR = "error"

# Pending-error ranks: hidden, decoding, and indentation-kind problems first; then block
# structure and placement; then everything else by position.
RANK_LINE = 0
RANK_BLOCK = 1
RANK_STATEMENT = 2

BIDI_CHARS = "‪-‮⁦-⁩"
_BIDI_RE = re.compile(f"[{BIDI_CHARS}]")
_INVISIBLE_RE = re.compile(f"[{INVISIBLE_CHARS}]")
_ZERO_WIDTH = "﻿​"
_ZERO_WIDTH_RE = re.compile(f"[{_ZERO_WIDTH}]")
_HIDDEN_RE = re.compile(f"[{BIDI_CHARS}{INVISIBLE_CHARS}{_ZERO_WIDTH}]")
_WORD_RE = re.compile(r"\w+")
_STRING_STOP_RE = re.compile(r'["\\]')
_TODO_RE = re.compile(r"todo(?![^\W_])", re.IGNORECASE)
# Plain blank and comment lines (``StatementReader._quiet_run``): spaces and tabs, then nothing
# or a comment of printable ASCII and tabs; at most SCRIPT_MAX_LINE_CHARS long; ended by LF.
# While TODOs are collected, a comment that may be a ``# TODO`` (SR-F02-13) is not plain.
_QUIET_RUN_LINES = 512
# Only at a line start (``(?<![^\n])``), so a ``search`` stays linear (AC-F02-54).
_FITS = rf"(?<![^\n])(?=[^\n]{{0,{SCRIPT_MAX_LINE_CHARS}}}\n)"
_QUIET_RUN_RE = re.compile(
    rf"(?:{_FITS}[ \t]*(?:#[\t\x20-\x7e]*)?\n){{1,{_QUIET_RUN_LINES}}}")
_QUIET_RUN_NO_TODO_RE = re.compile(
    rf"(?:{_FITS}[ \t]*(?:#(?![ \t]*[Tt][Oo][Dd][Oo])[\t\x20-\x7e]*)?\n){{1,{_QUIET_RUN_LINES}}}")
_COMMENT_INDENT_RE = re.compile(r"^[ \t]*(?=#)", re.MULTILINE)


@dataclass(slots=True)
class Token:
    """One script token. ``text`` is the word (NAME), the shown value (STRING), the raw
    path (PATH), or the character. ``line``/``column`` are 1-based.

    A STRING's ``origins`` (F05 ``04-technical.md`` §6.1) map its text back to the source:
    one ``(text_offset, line, column)`` per slice, where a slice is a run of text copied as
    is, one escape's character, or the space of a plain continuation. Inside a slice
    offsets map one to one (``texttags.origin_of``). Internal to ``script``; dropped with
    the token once the statement is parsed."""

    kind: str
    text: str
    line: int
    column: int
    unclosed: bool = False
    origins: tuple[tuple[int, int, int], ...] = ()


@dataclass(slots=True)
class PendingError:
    rank: int
    line: int
    column: int | None
    code: str
    args: tuple
    seq: int


@dataclass(slots=True)
class Segment:
    """The part of one physical line that belongs to a statement, with the regions the
    hidden-character checks need (indexes into ``text``)."""

    number: int
    text: str
    script_strings: list[tuple[int, int]] = field(default_factory=list)
    py_from: int | None = None
    py_strings: list[tuple[int, int]] = field(default_factory=list)
    comments: list[tuple[int, int]] = field(default_factory=list)
    comment_at: int | None = None       # start of a script comment ("#") on this line


@dataclass(slots=True)
class PySpan:
    """The extent of one piece of Python (§7.4), in code-line coordinates: line index 0 is
    the first code line (starting at ``column``), later lines are whole physical lines."""

    lines: list[str]
    line: int
    column: int
    length: int                          # len("\n".join(all lines)), even past the cap
    lambdas: int = 0
    colon: tuple[int, int] | None = None  # (line index, index) of the last top-level ":"
    comments: list[tuple[int, int, int]] = field(default_factory=list)
    truncated: bool = False
    in_string_at_end: bool = False

    @property
    def source(self) -> str:
        return "\n".join(self.lines)

    @property
    def end_line(self) -> int:
        return self.line + len(self.lines) - 1

    def without_comments(self, lines: list[str] | None = None) -> str:
        """The code with its ``#`` comments cut off (ADR-0006 ``PythonLine`` key)."""
        lines = list(self.lines if lines is None else lines)
        for index, start, _end in self.comments:
            if index < len(lines):
                lines[index] = lines[index][:start]
        return "\n".join(line.rstrip() for line in lines)


@dataclass(slots=True, eq=False)
class RawStatement:
    """One logical line as read (§7.3.1 step 7)."""

    file: ScriptFile
    line: int
    width: int = 0
    column: int = 1
    end_line: int = 0
    head: str = HEAD_ERROR
    word: str = ""
    tail: str = TAIL_SCRIPT
    tokens: list[Token] = field(default_factory=list)
    py: PySpan | None = None
    py_after: str = ""                    # text after a condition's ":" (comment excluded)
    ends_with_colon: bool = False
    fullwidth_colon: bool = False
    comment: str | None = None
    comment_width_before: int = -1
    pending: list[PendingError] = field(default_factory=list)
    texts: dict[int, str] = field(default_factory=dict)
    segments: dict[int, Segment] = field(default_factory=dict)

    @property
    def has_error(self) -> bool:
        return bool(self.pending)

    def error(self, code: str, args: tuple = (), *, line: int | None = None,
              column: int | None = None, rank: int = RANK_STATEMENT) -> None:
        self.pending.append(PendingError(rank, self.line if line is None else line, column,
                                         code, args, len(self.pending)))

    def rest_from(self, line: int, column: int) -> str:
        """The text of ``line`` from ``column`` to its script comment, stripped."""
        text = self.texts.get(line, "")
        segment = self.segments.get(line)
        end = segment.comment_at if segment is not None and segment.comment_at is not None \
            else len(text)
        return text[column - 1:end].strip()

    def rest_after(self, token: Token) -> str:
        """The text after ``token`` on its line (a STRING token's end is not known, so this
        is for NAME and symbol tokens)."""
        return self.rest_from(token.line, token.column + len(token.text))

    def chunk_at(self, token: Token) -> str:
        """The run of non-space characters starting at ``token``, up to a quote (E30d, E72)."""
        text = self.texts.get(token.line, "")
        start = token.column - 1
        end = start
        while end < len(text) and not text[end].isspace() and \
                (end == start or text[end] != '"'):
            end += 1
        return text[start:end]

    def flush(self, sink: DiagnosticSink) -> bool:
        """Report the first pending error the sink accepts (one per logical line). Returns
        True if one was counted. The pending list is cleared."""
        accepted = False
        if self.pending:
            ordered = sorted(self.pending,
                             key=lambda p: (p.rank, p.line, p.column or 0, p.seq))
            for pending in ordered:
                diag = Diagnostic(pending.code, self.file, pending.line, pending.column,
                                  pending.args, source_line=self.texts.get(pending.line),
                                  stmt=self.line)
                if sink.add(diag):
                    accepted = True
                    break
            self.pending.clear()
        return accepted


def word_end(text: str, start: int) -> int:
    """End index of the word starting at ``start`` (§7.3.3): ``\\w`` runs, extended one
    character at a time for combining marks and other identifier characters."""
    end = start
    length = len(text)
    while end < length:
        match = _WORD_RE.match(text, end)
        if match is not None:
            end = match.end()
            # ``\w`` takes every ASCII word character, so an ASCII one next ends the word
            # (the common case: a space or a quote; F02 Step 11 hot path).
            if end == length or text[end].isascii():
                break
        elif is_word_char(text[end]):
            end += 1
        else:
            break
    return end


def _indent_end(text: str) -> int:
    # In C, not a Python loop per character: D10's deep nesting has indentation thousands
    # of characters wide on every line (F02 Step 11, AC-F02-54).
    return len(text) - len(text.lstrip(" \t"))


_NON_SPACE_RE = re.compile(r"\S")     # re's \s is str.isspace()


def _first_non_space(text: str) -> int:
    match = _NON_SPACE_RE.search(text)
    return match.start() if match is not None else len(text)


def _in_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start <= position < end:
            return True
    return False


def _control_code(char: str) -> str:
    return "E04" if char in SEPARATORS else "E03"


def _name_around(text: str, position: int) -> str:
    """The name (word and invisible characters) containing ``text[position]`` (E64b)."""
    start = position
    while start > 0 and (is_word_char(text[start - 1])
                         or _INVISIBLE_RE.match(text, start - 1)):
        start -= 1
    end = position + 1
    while end < len(text) and (is_word_char(text[end]) or _INVISIBLE_RE.match(text, end)):
        end += 1
    return text[start:end]


# --- Python spans (§7.4) -----------------------------------------------------------------

_CODE, _STR, _SPEC = 0, 1, 2
_STRING_PREFIXES = frozenset(("r", "u", "b", "br", "rb", "f", "fr", "rf"))
_PY_STOP = {
    ('"', False): re.compile(r'["\\]'), ("'", False): re.compile(r"['\\]"),
    ('"', True): re.compile(r'["\\{}]'), ("'", True): re.compile(r"['\\{}]"),
}
_SPEC_STOP = re.compile(r"[{}]")


class _Ctx:
    __slots__ = ("kind", "brackets", "field", "quote", "triple", "raw", "fstr", "seg")

    def __init__(self, kind: int, *, field_: bool = False, quote: str = "",
                 triple: bool = False, raw: bool = False, fstr: bool = False,
                 seg: int = 0) -> None:
        self.kind = kind
        self.brackets: list[str] = []
        self.field = field_
        self.quote = quote
        self.triple = triple
        self.raw = raw
        self.fstr = fstr
        self.seg = seg


class PyScanner:
    """Finds the extent of a piece of Python one physical line at a time (§7.4).

    It knows string prefixes, single and triple quotes, PEP 701 f-strings (nested fields,
    nested strings with any quote, format specs), comments, and brackets. ``feed`` takes the
    next code line; ``needs_more`` says whether a bracket is still open (so the next deeper,
    blank, or comment line joins). A string open at the end of a line ends the piece
    (``compile()`` reports the unclosed quote).
    """

    __slots__ = ("_stack", "_index", "colon", "lambdas", "strings", "comments", "ended",
                 "in_string")

    def __init__(self) -> None:
        self._stack: list[_Ctx] = [_Ctx(_CODE)]
        self._index = -1
        self.colon: tuple[int, int] | None = None
        self.lambdas = 0
        self.strings: list[tuple[int, int, int]] = []
        self.comments: list[tuple[int, int, int]] = []
        self.ended = False
        self.in_string = False

    @property
    def depth(self) -> int:
        return len(self._stack[0].brackets)

    def needs_more(self) -> bool:
        return not self.ended and bool(self._stack[0].brackets)

    def feed(self, line: str) -> None:
        self._index += 1
        index = self._index
        stack = self._stack
        strings = self.strings
        i = 0
        n = len(line)
        while i < n:
            top = stack[-1]
            kind = top.kind
            if kind == _CODE:
                char = line[i]
                if char == "#":
                    self.comments.append((index, i, n))
                    i = n
                    break
                if char == '"' or char == "'":
                    i = self._open_string(line, i, i, "")
                    continue
                if char == "_" or char.isalnum():
                    match = _WORD_RE.match(line, i)
                    end = match.end() if match is not None else i + 1
                    word = line[i:end]
                    if end < n and line[end] in "\"'" and word.lower() in _STRING_PREFIXES:
                        i = self._open_string(line, i, end, word.lower())
                        continue
                    if word == "lambda":
                        self.lambdas += 1
                    i = end
                    continue
                if char in "([{":
                    top.brackets.append(char)
                elif char in ")]}":
                    if top.brackets:
                        top.brackets.pop()
                    elif top.field and char == "}":
                        stack.pop()
                        stack[-1].seg = i + 1
                elif char == ":" and not top.brackets:
                    if top.field:
                        stack.append(_Ctx(_SPEC, seg=i + 1))
                    elif len(stack) == 1 and line[i + 1:i + 2] != "=":
                        self.colon = (index, i)
                i += 1
            elif kind == _STR:
                match = _PY_STOP[(top.quote, top.fstr)].search(line, i)
                if match is None:
                    i = n
                    break
                j = match.start()
                char = line[j]
                if char == "\\":
                    if top.fstr and not top.raw and line.startswith("N{", j + 1):
                        close = line.find("}", j + 3)
                        i = close + 1 if close >= 0 else n
                    else:
                        i = j + 2
                elif char == top.quote:
                    if not top.triple:
                        strings.append((index, top.seg, j + 1))
                        stack.pop()
                        i = j + 1
                    elif line.startswith(top.quote * 3, j):
                        strings.append((index, top.seg, j + 3))
                        stack.pop()
                        i = j + 3
                    else:
                        i = j + 1
                elif char == "{":
                    if line.startswith("{{", j):
                        i = j + 2
                    else:
                        strings.append((index, top.seg, j))
                        stack.append(_Ctx(_CODE, field_=True))
                        i = j + 1
                else:  # "}"
                    i = j + 2 if line.startswith("}}", j) else j + 1
            else:  # _SPEC
                match = _SPEC_STOP.search(line, i)
                if match is None:
                    i = n
                    break
                j = match.start()
                strings.append((index, top.seg, j))
                if line[j] == "{":
                    stack.append(_Ctx(_CODE, field_=True))
                else:
                    stack.pop()                    # the spec
                    stack.pop()                    # its field
                    stack[-1].seg = j + 1
                i = j + 1
        if len(stack) > 1:
            for ctx in reversed(stack):
                if ctx.kind != _CODE:
                    strings.append((index, ctx.seg, n))
                    break
            self.ended = True
            self.in_string = True

    def _open_string(self, line: str, start: int, quote_at: int, prefix: str) -> int:
        quote = line[quote_at]
        triple = line.startswith(quote * 3, quote_at)
        self._stack.append(_Ctx(_STR, quote=quote, triple=triple, raw="r" in prefix,
                                fstr="f" in prefix, seg=start))
        return quote_at + (3 if triple else 1)


def scan_python_lines(lines: list[str]) -> PyScanner:
    """Run a ``PyScanner`` over ``lines`` while it needs more (tests and tools)."""
    scanner = PyScanner()
    for index, line in enumerate(lines):
        if index and not scanner.needs_more():
            break
        scanner.feed(line)
    return scanner


# --- The statement reader (§7.3) ---------------------------------------------------------

class _More:
    """The type of ``MORE``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "MORE"


# ``StatementReader.peek_within``: no statement yet, more lines to read (Step 11).
MORE = _More()


class StatementReader:
    """Reads ``RawStatement``s from one decoded file, one logical line at a time."""

    def __init__(self, file: ScriptFile, text: str, sink: DiagnosticSink,
                 tail_for: Callable[[str], str], *,
                 on_todo: Callable[[ScriptFile, int, str], None] | None = None) -> None:
        self.file = file
        self.cursor = LineCursor(text)
        self.sink = sink
        self.tail_for = tail_for
        self.on_todo = on_todo
        self.kind: str | None = None          # " " or "\t" once the first indented line is read
        self._comment_width = -1
        self._peeked: RawStatement | None = None
        self._peeked_valid = False

    # Public interface -------------------------------------------------------------------

    def peek(self) -> RawStatement | None:
        if not self._peeked_valid:
            self._peeked = self._read_statement()  # type: ignore[assignment]
            self._peeked_valid = True
        return self._peeked

    def peek_within(self, limit: int) -> "RawStatement | None | _More":
        """``peek()`` that reads about ``limit`` lines producing no statement (blank,
        comment, and over-long lines; a plain run can take it up to ``_QUIET_RUN_LINES`` - 1
        past) before it gives up and returns ``MORE``; calling it
        again goes on where it stopped. The block parser yields to the frame loop on
        ``MORE``, so a file of nothing but such lines is still read in slices (§7.9)."""
        if self._peeked_valid:
            return self._peeked
        raw = self._read_statement(limit)
        if raw is MORE:
            return MORE
        self._peeked = raw  # type: ignore[assignment]
        self._peeked_valid = True
        return raw

    def next(self) -> RawStatement | None:
        raw = self.peek()
        self._peeked_valid = False
        self._peeked = None
        return raw

    @property
    def comment_width(self) -> int:
        """The deepest comment-line width since the last statement (E12's suffix)."""
        return self._comment_width

    @property
    def lines_read(self) -> int:
        return self.cursor.lines_read

    # Lines that produce no statement ------------------------------------------------------

    def _emit(self, code: str, line: PhysicalLine, column: int | None = None,
              args: tuple = ()) -> None:
        self.sink.add(Diagnostic(code, self.file, line.number, column, args,
                                 source_line=line.text, stmt=line.number))

    def _comment_line(self, line: PhysicalLine, start: int) -> None:
        text = line.text
        if line.control is not None:
            column, char = line.control
            self._emit(_control_code(char), line, column, (char,))
        else:
            match = _HIDDEN_RE.search(text)
            if match is not None:
                for found in _HIDDEN_RE.finditer(text):
                    char = found.group()
                    if char in _ZERO_WIDTH:
                        self._emit("E03", line, found.start() + 1, (char,))
                        break
                    if _BIDI_RE.match(char):
                        self._emit("E03b", line, found.start() + 1, (char, False))
                        break
        if start > self._comment_width:
            self._comment_width = start
        self._todo(line.number, text[start + 1:])

    def _todo(self, number: int, comment: str) -> None:
        if self.on_todo is None:
            return
        body = comment.strip()
        if _TODO_RE.match(body):
            self.on_todo(self.file, number, body)

    # Statements ---------------------------------------------------------------------------

    def _read_statement(self, limit: int = -1) -> "RawStatement | None | _More":
        """The next statement, None at the end, or ``MORE`` once at least ``limit`` lines
        that produce no statement were read (``-1``: no limit)."""
        cursor = self.cursor
        skipped = 0
        if limit < 0:
            limit = sys.maxsize
        while True:
            if skipped >= limit:
                return MORE
            start = cursor.free_position()
            if start is not None:
                quiet = self._quiet_run(start)
                if quiet:
                    skipped += cursor.skip_to(quiet)
                    continue
            line = cursor.next()
            if line is None:
                return None
            skipped += 1
            text = line.text
            if len(text) > SCRIPT_MAX_LINE_CHARS:
                self._emit("E16", line)
                continue
            start = _first_non_space(text)
            if start == len(text):
                if line.control is not None:
                    column, char = line.control
                    self._emit(_control_code(char), line, column, (char,))
                continue
            if text[start] == "#":
                self._comment_line(line, start)
                continue
            return self._statement(line)

    def _quiet_run(self, start: int) -> int:
        """The end of a run of up to ``_QUIET_RUN_LINES`` plain blank and comment lines at
        ``start`` (0 if none): ASCII only, no control character, not over-long, so each
        would give no message. They are passed over without a ``PhysicalLine`` each (``04``
        §10 hot path; F02 Step 11: a 16 MiB file of comments took about 2.5 s line by
        line). Their deepest comment counts for E12's suffix as it would line by line; a
        comment that may be a ``# TODO`` ends the run while TODOs are collected."""
        text = self.cursor.text
        pattern = _QUIET_RUN_RE if self.on_todo is None else _QUIET_RUN_NO_TODO_RE
        match = pattern.match(text, start)
        if match is None:
            return 0
        end = match.end()
        widths = _COMMENT_INDENT_RE.findall(text, start, end)
        if widths:
            width = len(max(widths, key=len))
            if width > self._comment_width:
                self._comment_width = width
        return end

    def _kind_check(self, raw: RawStatement, number: int, run: str) -> None:
        if not run:
            return
        if " " in run and "\t" in run:
            raw.error("E10c", line=number, rank=RANK_LINE)
            return
        kind = run[0]
        if self.kind is None:
            self.kind = kind
        elif kind != self.kind:
            raw.error("E10", (kind,), line=number, rank=RANK_LINE)

    def _add_line(self, raw: RawStatement, line: PhysicalLine) -> Segment:
        raw.texts[line.number] = line.text
        segment = Segment(line.number, line.text)
        raw.segments[line.number] = segment
        raw.end_line = line.number
        if line.control is not None:
            column, char = line.control
            raw.error(_control_code(char), (char,), line=line.number, column=column,
                      rank=RANK_LINE)
        return segment

    def _statement(self, line: PhysicalLine) -> RawStatement:
        raw = RawStatement(self.file, line.number)
        raw.comment_width_before = self._comment_width
        self._comment_width = -1
        segment = self._add_line(raw, line)
        text = line.text
        length = len(text)
        index = _indent_end(text)
        self._kind_check(raw, line.number, text[:index])
        if index < length and not text[index].isascii()                 and unicodedata.category(text[index]) == "Zs":
            raw.error("E11", (text[index],), column=index + 1, rank=RANK_LINE)
            while index < length and (text[index] in " \t"
                                      or unicodedata.category(text[index]) == "Zs"):
                index += 1
        raw.width = index
        while index < length and text[index] in _ZERO_WIDTH:
            index += 1                       # reported by the hidden-character check
        raw.column = index + 1
        char = text[index] if index < length else ""
        if char == "$":
            raw.head = HEAD_PYTHON
            raw.tail = TAIL_PY_ALL
            start = _indent_end_any(text, index + 1)
            self._read_python(raw, segment, start)
        elif char == '"':
            raw.head = HEAD_NARRATION
            self._scan_script(raw, segment, index, if_tail=True)
        elif char and is_word_char(char) and canonical_name(
                word := text[index:word_end(text, index)]).isidentifier():
            raw.head = HEAD_WORD
            raw.word = word
            raw.tail = tail = self.tail_for(word)
            if tail == TAIL_CONDITION:
                raw.tokens.append(Token(NAME, word, line.number, index + 1))
                start = _indent_end_any(text, index + len(word))
                self._read_python(raw, segment, start)
            elif tail == TAIL_AFTER_EQUALS:
                stop = self._scan_script(raw, segment, index, stop_at_equals=True)
                if stop is not None:
                    stop_segment, position = stop
                    self._read_python(raw, stop_segment,
                                      _indent_end_any(stop_segment.text, position))
            else:
                self._scan_script(raw, segment, index, path=tail == TAIL_PATH)
        else:
            raw.head = HEAD_ERROR
            if char in E50_CHARS:
                raw.error("E50", (char,), column=index + 1)
            elif char in E51_CHARS:
                raw.error("E51", column=index + 1)
            else:
                chunk_end = index
                while chunk_end < length and not text[chunk_end].isspace() \
                        and (chunk_end == index or text[chunk_end] != '"'):
                    chunk_end += 1
                raw.error("E30d", (text[index:chunk_end],), column=index + 1)
            self._scan_script(raw, segment, index)
        self._hidden_checks(raw)
        return raw

    # Script tails (ScriptScanner) ---------------------------------------------------------

    def _scan_script(self, raw: RawStatement, segment: Segment, start: int, *,
                     path: bool = False, stop_at_equals: bool = False, if_tail: bool = False,
                     ) -> tuple[Segment, int] | None:
        """``if_tail`` (F07 C8, narration): right after the first string, ``if`` followed by
        a space, a tab, or ``(`` is a NAME token and the rest of the statement is read as
        Python, exactly like a ``TAIL_CONDITION`` (a menu choice's condition). The rule is
        context-free; outside a menu such a line is E74 or E53 (``statements._after_text``).
        F59: also right after ``check <meter> <difficulty>`` (any words after the string that
        start with ``check``), so a checked choice can have a condition."""
        tokens = raw.tokens
        text = segment.text
        number = segment.number
        length = len(text)
        i = start
        while i < length:
            char = text[i]
            if char == " " or char == "\t":
                i += 1
                continue
            if char == "#":
                segment.comment_at = i
                segment.comments.append((i, length))
                raw.comment = text[i + 1:]
                self._todo(number, raw.comment)
                break
            if char == '"':
                if path:
                    close = text.find('"', i + 1)
                    if close < 0:
                        tokens.append(Token(PATH, text[i + 1:], number, i + 1, unclosed=True))
                        i = length
                    else:
                        tokens.append(Token(PATH, text[i + 1:close], number, i + 1))
                        i = close + 1
                    continue
                segment, i = self._scan_string(raw, segment, i)
                text = segment.text
                number = segment.number
                length = len(text)
                if if_tail and len(tokens) == 1:
                    j = _indent_end_any(text, i)
                    if text.startswith("if", j) and j + 2 < length and text[j + 2] in " \t(":
                        tokens.append(Token(NAME, "if", number, j + 1))
                        self._read_python(raw, segment, _indent_end_any(text, j + 2))
                        return None
                continue
            column = i + 1
            if char == ":":
                tokens.append(Token(COLON, char, number, column))
            elif char == "：":
                tokens.append(Token(FWCOLON, char, number, column))
            elif char == "=":
                tokens.append(Token(EQUALS, char, number, column))
                if stop_at_equals:
                    self._finish_script(raw)
                    return segment, i + 1
            elif char in E50_CHARS:
                tokens.append(Token(CURLY, char, number, column))
            elif char in E51_CHARS:
                tokens.append(Token(SQUOTE, char, number, column))
            elif is_word_char(char):
                end = word_end(text, i)
                if (if_tail and len(tokens) > 1 and text[i:end] == "if" and end < length
                        and text[end] in " 	(" and tokens[1].kind == NAME
                        and tokens[1].text == "check"):                 # F59
                    tokens.append(Token(NAME, "if", number, column))
                    self._read_python(raw, segment, _indent_end_any(text, end))
                    return None
                tokens.append(Token(NAME, text[i:end], number, column))
                i = end
                continue
            else:
                tokens.append(Token(SYMBOL, char, number, column))
            i += 1
        self._finish_script(raw)
        return None

    @staticmethod
    def _finish_script(raw: RawStatement) -> None:
        if raw.tokens:
            last = raw.tokens[-1].kind
            raw.ends_with_colon = last in (COLON, FWCOLON)
            raw.fullwidth_colon = last == FWCOLON

    def _scan_string(self, raw: RawStatement, segment: Segment,
                     quote_at: int) -> tuple[Segment, int]:
        """Read quoted text from ``segment.text[quote_at]`` (a ``"``), pulling continuation
        lines (SR-F02-30–33). Returns the segment and index after the closing quote. The
        STRING token gets the ``origins`` of its slices (F05 §6.1)."""
        open_line = segment.number
        open_column = quote_at + 1
        opening_text = segment.text
        parts: list[str] = []
        origins: list[tuple[int, int, int]] = []
        size = 0                                   # len("".join(parts))

        def put(piece: str, line: int, column: int) -> None:
            nonlocal size
            if piece:
                origins.append((size, line, column))
                parts.append(piece)
                size += len(piece)

        text = segment.text
        position = quote_at + 1
        region_start = position
        while True:
            match = _STRING_STOP_RE.search(text, position)
            if match is None or (text[match.start()] == "\\"
                                 and _rest_is_blank(text, match.start() + 1)):
                joined = match is not None
                if joined:
                    piece = text[position:match.start()]
                else:
                    piece = text[position:].rstrip(" \t")
                put(piece, segment.number, position + 1)
                segment.script_strings.append((region_start, len(text)))
                following = self._continue_text(raw)
                if following is None:
                    tail = opening_text[open_column:]
                    code = "E54b" if ("”" in tail or "＂" in tail) else "E54"
                    raw.error(code, line=open_line, column=open_column)
                    raw.tokens.append(Token(STRING, "".join(parts), open_line, open_column,
                                            unclosed=True, origins=tuple(origins)))
                    return segment, len(text)
                if not joined:
                    put(" ", segment.number, position + 1 + len(piece))
                segment = following
                text = segment.text
                position = _indent_end(text)
                region_start = position
                continue
            j = match.start()
            if text[j] == '"':
                put(text[position:j], segment.number, position + 1)
                segment.script_strings.append((region_start, j))
                raw.tokens.append(Token(STRING, "".join(parts), open_line, open_column,
                                        origins=tuple(origins)))
                return segment, j + 1
            put(text[position:j], segment.number, position + 1)
            following_char = text[j + 1]
            if following_char == '"':
                put('"', segment.number, j + 1)
            elif following_char == "\\":
                put("\\", segment.number, j + 1)
            elif following_char == "n":
                put("\n", segment.number, j + 1)
            else:
                raw.error("E52", ("\\" + following_char,), line=segment.number, column=j + 1)
                put("\\" + following_char, segment.number, j + 1)
            position = j + 2

    def _continue_text(self, raw: RawStatement) -> Segment | None:
        """The next non-blank line if it is deeper than the statement (consumed), else None
        (left for the next statement). Blank lines on the way are consumed."""
        cursor = self.cursor
        while True:
            line = cursor.peek()
            if line is None:
                return None
            text = line.text
            if len(text) > SCRIPT_MAX_LINE_CHARS:
                cursor.next()
                raw.texts[line.number] = text
                raw.error("E16", line=line.number, rank=RANK_LINE)
                continue
            if not text or text.isspace():
                cursor.next()
                if line.control is not None:
                    self._add_line(raw, line)
                continue
            width = _indent_end(text)
            if width <= raw.width:
                return None
            cursor.next()
            segment = self._add_line(raw, line)
            self._kind_check(raw, line.number, text[:width])
            return segment

    # Python tails (PyScanner) ---------------------------------------------------------------

    def _read_python(self, raw: RawStatement, segment: Segment, start: int) -> None:
        cursor = self.cursor
        scanner = PyScanner()
        first = segment.text[start:].rstrip()
        segment.py_from = start
        lines = [first]
        length = len(first)
        truncated = False
        scanner.feed(first)
        while scanner.needs_more():
            line = cursor.peek()
            if line is None:
                break
            text = line.text
            if len(text) > SCRIPT_MAX_LINE_CHARS:
                cursor.next()
                raw.texts[line.number] = text
                raw.end_line = line.number
                raw.error("E16", line=line.number, rank=RANK_LINE)
                code = ""
            elif not text or text.isspace():
                cursor.next()
                if line.control is not None:
                    self._add_line(raw, line)
                raw.end_line = line.number
                code = ""
            else:
                begin = _first_non_space(text)
                comment_line = text[begin] == "#"
                width = _indent_end(text)
                if not comment_line and width <= raw.width:
                    break
                cursor.next()
                more = self._add_line(raw, line)
                more.py_from = 0
                if not comment_line:
                    self._kind_check(raw, line.number, text[:width])
                code = text.rstrip()
            scanner.feed(code)
            length += 1 + len(code)
            if not truncated and length > SCRIPT_PY_PIECE_MAX_CHARS:
                truncated = True
            if not truncated:
                lines.append(code)
        # ``lines`` stops growing past the cap (SEC-F02-02); such a piece is never compiled.
        span = PySpan(lines, segment.number, start + 1, length, scanner.lambdas,
                      scanner.colon, scanner.comments, truncated, scanner.in_string)
        raw.py = span
        # Region map for the hidden-character checks (physical coordinates).
        for regions, target in ((scanner.strings, "py_strings"), (scanner.comments, "comments")):
            for index, begin, end in regions:
                seg = raw.segments.get(span.line + index)
                if seg is not None:
                    offset = start if index == 0 else 0
                    getattr(seg, target).append((begin + offset, end + offset))
        if span.colon is not None:
            colon_index, colon_at = span.colon
            after = span_line(span, raw, colon_index)[colon_at + 1:].strip()
            for index in range(colon_index + 1, raw.end_line - span.line + 1):
                more = span_line(span, raw, index).strip()
                if more and not more.startswith("#"):
                    after = (after + " " + more).strip()
            if after.startswith("#"):
                after = ""
            raw.py_after = after
            raw.ends_with_colon = not after
        if raw.end_line < segment.number:
            raw.end_line = segment.number

    # Hidden characters (§7.3.4) -------------------------------------------------------------

    def _hidden_checks(self, raw: RawStatement) -> None:
        for segment in raw.segments.values():
            text = segment.text
            if _HIDDEN_RE.search(text) is None:
                continue
            for match in _HIDDEN_RE.finditer(text):
                position = match.start()
                char = match.group()
                if _in_ranges(position, segment.script_strings):
                    continue
                in_py = segment.py_from is not None and position >= segment.py_from
                in_py_string = in_py and _in_ranges(position, segment.py_strings)
                in_comment = _in_ranges(position, segment.comments)
                if _BIDI_RE.match(char):
                    raw.error("E03b", (char, in_py_string), line=segment.number,
                              column=position + 1, rank=RANK_LINE)
                    break
                if char in _ZERO_WIDTH:
                    if in_py:
                        continue                 # Python's own check (compile) applies
                    raw.error("E03", (char,), line=segment.number, column=position + 1,
                              rank=RANK_LINE)
                    break
                if in_py_string or in_comment:
                    continue
                raw.error("E64b", (_name_around(text, position), char), line=segment.number,
                          column=position + 1, rank=RANK_LINE)
                break


def _indent_end_any(text: str, start: int) -> int:
    """Skip spaces and tabs from ``start``."""
    length = len(text)
    while start < length and text[start] in " \t":
        start += 1
    return start


def _rest_is_blank(text: str, start: int) -> bool:
    """True if only spaces and tabs follow ``start`` (a ``\\`` line join, SR-F02-26)."""
    return not text[start:].strip(" \t")


def span_line(span: PySpan, raw: RawStatement, index: int) -> str:
    """Code line ``index`` of ``span`` (from the kept lines or the statement's texts)."""
    if index < len(span.lines):
        return span.lines[index]
    return raw.texts.get(span.line + index, "").rstrip()
