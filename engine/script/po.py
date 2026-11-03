"""Reading and writing a language's ``translations/<code>.po`` (F43 ``01-design.md`` §5.2,
PR-F43-02; ``04-technical.md`` §3, §8 rule 3).

Why this module exists: the game (``translations.TextTable``), ``check``, build and Studio's
Translate tab all read the same file, and Studio writes it, so one pure reader and one
canonical writer live here. Studio imports it, so it is standard library plus ``core`` and
``script`` only: no pygame, no runtime, no Tk.

**The file** is standard gettext PO, UTF-8 only (a leading BOM is skipped; the header's
``charset`` is not consulted). One entry per text::

    # a translator's note                  -> PoEntry.comments
    #. Hana · festival                     -> PoEntry.notes
    #. vn-who: hana                        -> PoEntry.who (04 §7.2)
    #: script/festival.vns:42              -> PoEntry.refs (each #: line as written)
    #, fuzzy                               -> PoEntry.changed (Changed)
    #| msgid "the old original"            -> PoEntry.was (Was)
    msgctxt "start/3"                      -> PoEntry.key
    msgid "The original."                  -> PoEntry.original
    msgstr "訳。"                           -> PoEntry.translation ("" = New)

``#~`` before the keyword lines (and ``#~|`` for Was) marks an Unused entry
(``PoEntry.obsolete``). The first entry with no ``msgctxt`` and an empty ``msgid`` is the
header (``Language: ja``); its translator comments are ``PoFile.header_comments``.

**Reading never raises.** ``read_po`` returns a ``PoFile`` whose ``problems`` hold the
warnings (``PoProblem``: code, args, line):

- **W247** (no line) when the file isn't read at all: larger than ``PO_MAX_BYTES``
  (``large``), not UTF-8 (``utf8``), more than ``PO_MAX_ENTRIES`` entries (``entries``).
  The ``PoFile`` then has no header and no entries (``unreadable`` names the form), so the
  language shows the original text.
- **W248** per skipped entry, the rest used: ``quote`` (a string not closed, or text after
  it; at the string's own line), ``no_msgstr``, ``twice`` (a key used again; the first
  wins), ``unsupported`` (``msgid_plural``/``msgstr[N]``, an unknown keyword, no
  ``msgctxt``, no ``msgid``, a second ``msgstr``). These are at the entry's first keyword
  line. W248's ``long`` form is the kind's cap, checked by ``translatecheck``.

Entries past the cap are counted, good or bad; the header isn't. A blank line ends an entry
that has keyword lines, so one bad entry never swallows the next.

``lean`` (the game) skips what only Studio shows: ``#|`` (Was), ``#:``, ``#.`` notes, ``# ``
comments; ``#. vn-who:`` is kept (matching rule 2 needs it).

**Writing** (``write_po``) is canonical: entries in the order given, a blank line between
them, ``\\n`` line ends, one final newline, no BOM. A string holding a line break before its
end is written as ``""`` and one quoted line per line (the header always is). Strings escape
``\\``, ``"``, ``\\n``, ``\\t``, ``\\r`` and other control characters as three-digit octal.
Comment-like fields (comments, notes, refs, who) are one line each: a line break in them is
written as a space. So ``write_po(read_po(write_po(f)))`` is byte-for-byte
``write_po(f)``, and reading a file this module wrote gives back every field
(AC-F43-02).
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.core.constants import MB
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import _PO_MAX_ENTRIES, _PO_MAX_TEXT, format_message

PO_MAX_BYTES: Final = 16 * MB                   # 04 §8 rule 3; W247 says _PO_MAX_TEXT
PO_MAX_ENTRIES: Final = _PO_MAX_ENTRIES         # the same number W247's text shows
PO_MAX_TEXT: Final = _PO_MAX_TEXT               # "16 MB" (tests pin it to PO_MAX_BYTES)
TRANSLATIONS_DIR: Final = "translations"
WHO_PREFIX: Final = "vn-who: "                  # "#. vn-who: hana" (04 §7.2, decision 9)
FUZZY: Final = "fuzzy"


@dataclass(frozen=True, slots=True)
class PoProblem:
    """One warning from reading or checking a ``.po``: ``code`` and its ``format_message``
    args; ``line`` the entry's (None: the whole file, W247). Raise it with
    ``warning(ref)``, ``ref`` the file as ``translations/ja.po``."""

    code: str
    args: tuple
    line: int | None = None

    def message(self) -> str:
        return format_message(self.code, self.args)

    def warning(self, ref: str) -> ScriptWarning:
        return ScriptWarning(self.message(), code=self.code, file=ref, line=self.line)


@dataclass(frozen=True, slots=True)
class PoEntry:
    """One entry; an ``EntryLike`` for ``translatematch`` (key, original, translation,
    changed, was, who). ``line`` is its first keyword line (W248–W251's place; 0 for an
    entry not read from a file) and takes no part in equality."""

    key: str
    original: str
    translation: str = ""
    changed: bool = False                       # #, fuzzy: Changed
    was: str | None = None                      # #| msgid: Was
    who: str = ""                               # #. vn-who:
    notes: tuple[str, ...] = ()                 # other #. lines
    refs: tuple[str, ...] = ()                  # #: lines
    comments: tuple[str, ...] = ()              # translator "# " lines
    obsolete: bool = False                      # #~: Unused
    line: int = field(default=0, compare=False)


@dataclass(frozen=True, slots=True)
class PoFile:
    """A read file, or one to write. ``header`` is the header entry's ``msgstr`` text (None:
    no header entry). ``problems`` and ``unreadable`` (W247's form) are the reader's;
    ``write_po`` ignores them."""

    header: str | None = None
    entries: tuple[PoEntry, ...] = ()
    header_comments: tuple[str, ...] = ()
    problems: tuple[PoProblem, ...] = ()
    unreadable: str | None = None

    @property
    def language(self) -> str | None:
        """The header's ``Language:`` value, or None."""
        return header_fields(self.header or "").get("Language")


def header_for(language: str) -> str:
    """The header text Studio writes for a new file (``Language: ja``; UTF-8)."""
    return (f"Language: {language}\n"
            "MIME-Version: 1.0\n"
            "Content-Type: text/plain; charset=UTF-8\n"
            "Content-Transfer-Encoding: 8bit\n")


def header_fields(header: str) -> dict[str, str]:
    """``Name: value`` lines of a header text (the first of a name wins)."""
    out: dict[str, str] = {}
    for line in header.split("\n"):
        name, colon, value = line.partition(":")
        if colon and name.strip():
            out.setdefault(name.strip(), value.strip())
    return out


# --- Strings ---------------------------------------------------------------------------------

_ESCAPES: Final = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "a": "\a",
                   "b": "\b", "f": "\f", "v": "\v", "'": "'", "?": "?"}
_OCTAL: Final = frozenset("01234567")
_HEX: Final = frozenset("0123456789abcdefABCDEF")
_NEEDS_ESCAPE = re.compile(r'[\\"\x00-\x1f\x7f]')
_WRITE_ESCAPES: Final = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def _escape_char(match: "re.Match[str]") -> str:
    char = match.group()
    return _WRITE_ESCAPES.get(char) or f"\\{ord(char):03o}"


def _escape(text: str) -> str:
    if _NEEDS_ESCAPE.search(text) is None:
        return text
    return _NEEDS_ESCAPE.sub(_escape_char, text)


def _unescape(body: str) -> str | None:
    """A quoted string's inside with escapes; None when an unescaped ``"`` ends it early
    (or a final ``\\`` escapes the closing quote). An unknown escape keeps both
    characters."""
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        j = body.find("\\", i)
        k = body.find('"', i)
        if k >= 0 and (j < 0 or k < j):
            return None
        if j < 0:
            out.append(body[i:])
            break
        out.append(body[i:j])
        if j + 1 >= n:
            return None
        char = body[j + 1]
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
            i = j + 2
        elif char in _OCTAL:
            end = j + 1
            while end < n and end < j + 4 and body[end] in _OCTAL:
                end += 1
            out.append(chr(int(body[j + 1:end], 8)))
            i = end
        elif char == "x" and j + 2 < n and body[j + 2] in _HEX:
            end = j + 2
            while end < n and end < j + 4 and body[end] in _HEX:
                end += 1
            out.append(chr(int(body[j + 2:end], 16)))
            i = end
        else:
            out.append(body[j:j + 2])
            i = j + 2
    return "".join(out)


def _unquote(rest: str) -> str | None:
    """The text of one quoted string (``rest`` stripped), or None (W248 ``quote``)."""
    if len(rest) < 2 or rest[0] != '"' or rest[-1] != '"':
        return None
    body = rest[1:-1]
    if "\\" not in body:
        return None if '"' in body else body
    return _unescape(body)


_CTX: Final = 1                                 # _Draft.seen bits
_MID: Final = 2
_STR: Final = 4


class _Draft:
    """The entry being read. ``seen`` holds the keywords met (even when their string was
    bad), so the next entry's ``msgctxt``/``msgid`` always starts a new draft."""

    __slots__ = ("ctx", "mid", "mstr", "was", "who", "notes", "refs", "comments", "fuzzy",
                 "obsolete", "line", "problem", "target", "seen", "keywords")

    def __init__(self) -> None:
        self.ctx: str | None = None
        self.mid: str | None = None
        self.mstr: str | None = None
        self.was: str | None = None
        self.who = ""
        self.notes: list[str] = []
        self.refs: list[str] = []
        self.comments: list[str] = []
        self.fuzzy = False
        self.obsolete = False
        self.line = 0
        self.problem: PoProblem | None = None
        self.target = ""                    # "ctx" / "mid" / "mstr" / "was" / "skip" / ""
        self.seen = 0
        self.keywords = False               # a keyword line (or a bad line) was seen

    def start(self, number: int, obsolete: bool) -> None:
        if not self.keywords:
            self.keywords = True
            self.line = number
            self.obsolete = obsolete

    def fail(self, number: int, form: str, *detail: object) -> None:
        """W248 ``form`` at line ``number`` (the first problem of an entry wins)."""
        if not self.keywords:
            self.keywords = True
            self.line = number
        self.target = ""
        if self.problem is None:
            self.problem = PoProblem("W248", (form, *detail), number or None)


def _split_keyword(line: str) -> tuple[str, str]:
    space = line.find(" ")
    quote = line.find('"')
    if space < 0 or 0 <= quote < space:
        space = quote
    if space < 0:
        return line, ""
    return line[:space].rstrip(), line[space:].strip()


class _Reader:
    __slots__ = ("lean", "entries", "problems", "keys", "header", "header_comments", "count",
                 "first", "over")

    def __init__(self, lean: bool) -> None:
        self.lean = lean
        self.entries: list[PoEntry] = []
        self.problems: list[PoProblem] = []
        self.keys: set[str] = set()
        self.header: str | None = None
        self.header_comments: tuple[str, ...] = ()
        self.count = 0
        self.first = True                   # no entry finished yet (the header's place)
        self.over = False

    def finish(self, d: _Draft) -> _Draft:
        """End ``d`` (kept, the header, or a W248) and return a fresh draft."""
        if not d.keywords:
            return d
        first, self.first = self.first, False
        if not d.seen & _MID:
            d.fail(d.line, "unsupported")
        elif not d.seen & _STR:
            d.fail(d.line, "no_msgstr")
        if (first and d.problem is None and d.ctx is None and d.mid == ""
                and not d.obsolete):
            self.header = d.mstr
            self.header_comments = tuple(d.comments)
            return _Draft()
        self.count += 1
        if self.count > PO_MAX_ENTRIES:
            self.over = True
            return _Draft()
        if d.problem is None:
            if d.ctx is None:
                d.fail(d.line, "unsupported")
            elif d.ctx in self.keys:
                d.fail(d.line, "twice", d.ctx)
        if d.problem is not None:
            self.problems.append(d.problem)
            return _Draft()
        key, mid, mstr = d.ctx, d.mid, d.mstr
        assert key is not None and mid is not None and mstr is not None
        self.keys.add(key)
        self.entries.append(PoEntry(key, mid, mstr, d.fuzzy, d.was, d.who, tuple(d.notes),
                                    tuple(d.refs), tuple(d.comments), d.obsolete, d.line))
        return _Draft()

    def continuation(self, d: _Draft, line: str, number: int, previous: bool) -> None:
        """A ``"…"`` line: more of the last keyword's (or Was's) string."""
        target = d.target
        if not target or previous != (target in ("was", "skip")):
            d.fail(number, "quote" if d.keywords else "unsupported")
            return
        if target == "skip":
            return
        text = _unquote(line)
        if text is None:
            d.fail(number, "quote")
        elif target == "mstr":
            d.mstr = (d.mstr or "") + text
        elif target == "mid":
            d.mid = (d.mid or "") + text
        elif target == "ctx":
            d.ctx = (d.ctx or "") + text
        else:
            d.was = (d.was or "") + text

    def previous(self, d: _Draft, line: str, number: int) -> _Draft:
        """A ``#|`` / ``#~|`` line (prefix removed): Was, before the entry's keywords."""
        if line.startswith('"'):
            self.continuation(d, line, number, True)
            return d
        if d.keywords:
            d = self.finish(d)
        word, rest = _split_keyword(line)
        if word == "msgid" and not self.lean:
            text = _unquote(rest)
            if text is None:
                d.fail(number, "quote")
                return d
            d.was = text
            d.target = "was"
        else:
            d.target = "skip"               # #| msgctxt, or Was in a lean read
        return d

    def keyword(self, d: _Draft, line: str, number: int, obsolete: bool) -> _Draft:
        """A keyword or continuation line (``#~`` removed)."""
        if line.startswith('"'):
            self.continuation(d, line, number, False)
            return d
        word, rest = _split_keyword(line)
        if word == "msgctxt" or word == "msgid":
            bit = _CTX if word == "msgctxt" else _MID
            if d.seen & (_STR | _MID | bit):
                d = self.finish(d)
                if self.over:
                    return d
            d.start(number, obsolete)
            d.seen |= bit
            text = _unquote(rest)
            if text is None:
                d.fail(number, "quote")
            elif bit == _CTX:
                d.ctx = text
                d.target = "ctx"
            else:
                d.mid = text
                d.target = "mid"
            return d
        d.start(number, obsolete)
        if word == "msgstr" and d.seen & _MID and not d.seen & _STR:
            d.seen |= _STR
            text = _unquote(rest)
            if text is None:
                d.fail(number, "quote")
            else:
                d.mstr = text
                d.target = "mstr"
            return d
        # msgid_plural, msgstr[N], a second msgstr, anything else: not used by this engine.
        if word.startswith("msgstr"):
            d.seen |= _STR
        d.fail(d.line, "unsupported")
        return d

    def run(self, text: str) -> None:
        d = _Draft()
        lean = self.lean
        if "\r" in text:
            text = text.replace("\r\n", "\n")
        for number, line in enumerate(text.split("\n"), 1):
            if line[:3] == "msg":
                # Fast path: a canonical keyword line (one simple string, the usual order).
                space = line.find(" ")
                rest = line[space + 1:]
                if (space > 0 and rest[:1] == '"' and rest[-1:] == '"' and rest.count('"') == 2
                        and "\\" not in rest):
                    word = line[:space]
                    seen = d.seen
                    if word == "msgstr":
                        if seen & 6 == 2:
                            d.seen = seen | 4
                            d.mstr = rest[1:-1]
                            d.target = "mstr"
                            continue
                    elif word == "msgid":
                        if not seen & 6:
                            if not d.keywords:
                                d.keywords = True
                                d.line = number
                            d.seen = seen | 2
                            d.mid = rest[1:-1]
                            d.target = "mid"
                            continue
                    elif word == "msgctxt" and not seen and not d.keywords:
                        d.keywords = True
                        d.line = number
                        d.seen = 1
                        d.ctx = rest[1:-1]
                        d.target = "ctx"
                        continue
                d = self.keyword(d, line, number, False)
                if self.over:
                    return
                continue
            if not line or line[0] in " \t":
                line = line.strip()
                if not line:
                    if d.keywords:              # a blank line ends an entry
                        d = self.finish(d)
                        if self.over:
                            return
                    continue
            if line[0] != "#":
                d = self.keyword(d, line, number, False)
            elif line[1:2] == "~":
                rest = line[2:].lstrip()
                if rest.startswith("|"):
                    d = self.previous(d, rest[1:].lstrip(), number)
                else:
                    d = self.keyword(d, rest, number, True)
            elif line[1:2] == "|":
                d = self.previous(d, line[2:].lstrip(), number)
            else:
                # A comment line belongs to the next entry.
                if d.keywords:
                    d = self.finish(d)
                mark = line[1:2]
                if mark == ".":
                    note = line[3:] if line.startswith("#. ") else line[2:]
                    if note.startswith(WHO_PREFIX):
                        d.who = note[len(WHO_PREFIX):]
                    elif not lean:
                        d.notes.append(note)
                elif mark == ",":
                    if FUZZY in line[2:].replace(",", " ").split():
                        d.fuzzy = True
                elif lean:
                    pass
                elif mark == ":":
                    d.refs.append(line[3:] if line.startswith("#: ") else line[2:])
                else:
                    d.comments.append(line[2:] if line.startswith("# ") else line[1:])
            if self.over:
                return
        self.finish(d)


def read_po(data: bytes, ref: str = "translations/xx.po", *, lean: bool = False,
            language: str | None = None) -> PoFile:
    """Read a ``.po`` (module docstring). ``ref`` is the file as ``translations/ja.po``;
    W247 names its file part and ``language`` (default: the file's code). Never raises."""
    name = ref.rpartition("/")[2]
    shown_language = language if language is not None else name.removesuffix(".po")

    def unreadable(form: str) -> PoFile:
        problem = PoProblem("W247", (form, name, shown_language), None)
        return PoFile(problems=(problem,), unreadable=form)

    if not isinstance(data, (bytes, bytearray, memoryview)):
        return unreadable("utf8")
    if len(data) > PO_MAX_BYTES:
        return unreadable("large")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        return unreadable("utf8")
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = _Reader(bool(lean))
    reader.run(text)
    if reader.over:
        return unreadable("entries")
    return PoFile(reader.header, tuple(reader.entries), reader.header_comments,
                  tuple(reader.problems))


# --- Writing ---------------------------------------------------------------------------------

def _one_line(text: str) -> str:
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _string_lines(prefix: str, keyword: str, text: str, split: bool = False) -> list[str]:
    if split or "\n" in text[:-1]:
        parts = text.split("\n")
        pieces = [part + "\n" for part in parts[:-1]]
        if parts[-1]:
            pieces.append(parts[-1])
        return [f'{prefix}{keyword} ""', *(f'{prefix}"{_escape(p)}"' for p in pieces)]
    return [f'{prefix}{keyword} "{_escape(text)}"']


def _comment(mark: str, text: str) -> str:
    text = _one_line(text)
    return f"{mark} {text}" if text else mark


def entry_lines(entry: PoEntry) -> list[str]:
    """One entry's canonical lines (no blank line)."""
    lines = [_comment("#", c) for c in entry.comments]
    lines.extend(_comment("#.", n) for n in entry.notes)
    if entry.who:
        lines.append(f"#. {WHO_PREFIX}{_one_line(entry.who)}")
    lines.extend(_comment("#:", r) for r in entry.refs)
    if entry.changed:
        lines.append(f"#, {FUZZY}")
    if entry.was is not None:
        lines.extend(_string_lines("#~| " if entry.obsolete else "#| ", "msgid", entry.was))
    prefix = "#~ " if entry.obsolete else ""
    lines.extend(_string_lines(prefix, "msgctxt", entry.key))
    lines.extend(_string_lines(prefix, "msgid", entry.original))
    lines.extend(_string_lines(prefix, "msgstr", entry.translation))
    return lines


def write_po(po: PoFile | None = None, *, header: str | None = None,
             entries: Iterable[PoEntry] = (), header_comments: Sequence[str] = ()) -> bytes:
    """The canonical bytes of ``po`` (or of ``header``, ``entries`` and
    ``header_comments`` given separately). Never raises for any text: a character UTF-8
    can't hold (a lone surrogate) is written as ``?``."""
    if po is not None:
        header, entries, header_comments = po.header, po.entries, po.header_comments
    blocks: list[str] = []
    if header is not None:
        lines = [_comment("#", c) for c in header_comments]
        lines.append('msgid ""')
        lines.extend(_string_lines("", "msgstr", header, split=True))
        blocks.append("\n".join(lines))
    for entry in entries:
        blocks.append("\n".join(entry_lines(entry)))
    text = "\n\n".join(blocks) + ("\n" if blocks else "")
    return text.encode("utf-8", "replace")


__all__ = ["FUZZY", "PO_MAX_BYTES", "PO_MAX_ENTRIES", "PO_MAX_TEXT", "PoEntry", "PoFile",
           "PoProblem", "TRANSLATIONS_DIR", "WHO_PREFIX", "entry_lines", "header_fields",
           "header_for", "read_po", "write_po"]
