"""The game's translation lookup table (F43 PR-F43-01, 02, 04, 05, 11, 15; ``04-technical.md``
§3, §7.1, §7.3 step 1; ``07`` I-13).

Why this module exists: the runtime asks "what does key K show in the current language?" for
every line, choice, name, word and title it draws, so the answer must be a dict get. This
module builds that table from one language's ``translations/<code>.po`` and the program's
source texts, and decides which languages a game has. It is pure (standard library, ``core``
and ``script``; no file API): the app lists the folder and reads the file, through
``runtime/texts.py`` (W3) and ``app/language.py`` (W4).

- ``discover(names, original)``: which files in ``translations/`` are languages (PR-F43-01).
  Only ``*.po`` names count (other files there are ignored, as the build leaves them out).
  A stem that isn't a language code, the original's own code, or a file past the 32nd (in
  sorted name order) is W253; a stem equal to an earlier one ignoring case is ignored.
- ``shown_languages(codes, show, release=)``: the languages a player can pick; ``show`` maps
  a code to ``[translation.<code>] show`` and hides it only in release runs (PR-F43-11).
- ``ReadJob``: read → decode → parse → match → build, in units the caller runs with
  ``run_for(deadline)`` (``SCRIPT_LOAD_SLICE_S`` for a switch, a player-chosen load). The
  parse runs ``po.read_po(lean=True)`` over pieces of about ``PARSE_CHUNK_CHARS`` cut at
  entry boundaries, so no unit parses the whole file; the result is the whole-file read's
  (same entries, lines and problems). Matching (``translatematch.match``) is one unit.
- ``TextTable``: key → shown text. Rows that are Done or Changed show their translation (a
  typo fix keeps the old translation showing until Mark done); New, Unused, skipped (W248)
  and refused entries show the original (``None``). Each entry is checked
  (``translatecheck.check_entry``) the first time it is looked up, as its kind with its
  kind's length cap; a refusal (W248 ``long``, W249, W250) is warned once and the original
  shows from then on. ``sweep`` checks the rest in slices (dev runs, ≤ 2 ms at a time). A
  lookup never returns ``""``.

Warnings are ``ScriptWarning``s raised with ``PoProblem.warning("translations/<file>")``: the
read's (W247, W248, W254 once per file) are in ``ReadResult.warnings``; a lookup's go to
``TextTable.warn`` (or wait in ``take_warnings()`` while it is None). W251 and W254 are dev
notes (01 §5.4): they are kept only when ``dev``.

A table never changes once built except for its check memo, so the language service keeps
the current and the previous table and switching back is instant (04 §7.3, decision 4).
"""

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, NamedTuple

from engine.core.errors import AssetTooLarge
from engine.core.langtags import english_name, is_language_code
from engine.script.diagnostics import ScriptWarning
from engine.script.po import (
    PO_MAX_BYTES,
    PO_MAX_ENTRIES,
    TRANSLATIONS_DIR,
    PoEntry,
    PoProblem,
    read_po,
)
from engine.script.translatecheck import check_entry, rtl_warning
from engine.script.translatekeys import (
    SourceText,
    choice_key,
    line_key,
    name_key,
    value_key,
    word_key,
)
from engine.script.translatematch import Matched, match

MAX_LANGUAGES: Final = 32               # translation files a game can have (PR-F43-01, W253)
PO_SUFFIX: Final = ".po"
PARSE_CHUNK_CHARS: Final = 128 * 1024   # about 2 ms of parse per unit (04 §4 Q2: 380 ms / 28 MB)
BUILD_CHUNK_ROWS: Final = 2_000         # matched rows added to the table per unit
RTL_CHUNK: Final = 4_000                # translations scanned for W254 per unit
SWEEP_CHUNK: Final = 16                 # entries checked between clock reads in ``sweep``
W251: Final = "W251"
# A later parse piece starts with this header, so its first real entry is never taken as
# the file's header (and a header-shaped entry there is W248, as in a whole-file read).
_PIECE_HEAD: Final = 'msgid ""\nmsgstr ""\n\n'
_PIECE_HEAD_LINES: Final = 3


def po_ref(file: str) -> str:
    """``ja.po`` → ``translations/ja.po`` (the warnings' file)."""
    return f"{TRANSLATIONS_DIR}/{file}"


# --- Which languages a game has --------------------------------------------------------------

class Language(NamedTuple):
    """One translation file that is a language: ``code`` (the file's stem) and ``file``."""

    code: str
    file: str


@dataclass(frozen=True, slots=True)
class Discovered:
    """``languages`` in file-name order; ``problems`` the W253s (raise each with
    ``warning(po_ref(file))``; ``files`` gives the file of each, same order)."""

    languages: tuple[Language, ...] = ()
    problems: tuple[PoProblem, ...] = ()
    files: tuple[str, ...] = ()

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(language.code for language in self.languages)

    def file_of(self, code: str) -> str | None:
        for language in self.languages:
            if language.code == code:
                return language.file
        return None

    def warnings(self) -> tuple[ScriptWarning, ...]:
        return tuple(p.warning(po_ref(f)) for p, f in zip(self.problems, self.files))


def discover(names: Iterable[str], original: str) -> Discovered:
    """The languages among the file names ``names`` of ``translations/`` (PR-F43-01, W253).
    ``original`` is ``[language] source``. Never raises."""
    languages: list[Language] = []
    problems: list[PoProblem] = []
    files: list[str] = []
    seen = {original.lower()} if isinstance(original, str) else set()
    for name in sorted(n for n in names if isinstance(n, str)):
        if not name.endswith(PO_SUFFIX) or "/" in name or "\\" in name:
            continue
        stem = name[:-len(PO_SUFFIX)]
        if not is_language_code(stem):
            problem = PoProblem("W253", ("bad_name", name, stem))
        elif stem == original or stem.lower() == str(original).lower():
            problem = PoProblem("W253", ("original", name, stem))
        elif stem.lower() in seen:
            continue
        elif len(languages) >= MAX_LANGUAGES:
            problem = PoProblem("W253", ("too_many", name, stem))
        else:
            seen.add(stem.lower())
            languages.append(Language(stem, name))
            continue
        problems.append(problem)
        files.append(name)
    return Discovered(tuple(languages), tuple(problems), tuple(files))


def shown_languages(codes: Sequence[str], show: Mapping[str, bool], *,
                    release: bool) -> tuple[str, ...]:
    """The translated languages a player can pick, in ``codes`` order (PR-F43-11):
    ``show[code]`` False hides one in release runs only; dev runs and Studio keep all."""
    if not release:
        return tuple(codes)
    return tuple(code for code in codes if show.get(code, True) is not False)


# --- The table -------------------------------------------------------------------------------

class _Slot(NamedTuple):
    """A shown row not checked yet."""

    translation: str
    kind: object
    original: str
    limit: int | None
    line: int | None


class TextTable:
    """One language's key → shown text (module docstring). ``code`` None is the original
    language (every lookup None). Lookups: ``text(key)`` and the per-kind helpers, which
    spell keys with ``translatekeys``' builders. None means "show the original"."""

    def __init__(self, code: str | None = None, file: str = "", *, dev: bool = False,
                 unreadable: str | None = None,
                 warn: Callable[[ScriptWarning], None] | None = None) -> None:
        self.code = code
        self.file = file
        self.ref = po_ref(file) if file else ""
        self.dev = dev
        self.unreadable = unreadable           # PoFile.unreadable: originals only
        self.warn = warn
        self._shown: dict[str, str] = {}       # checked and used
        self._pending: dict[str, _Slot] = {}   # shown rows not checked yet
        self._waiting: list[ScriptWarning] = []

    # Building (ReadJob) ---------------------------------------------------------------

    def add(self, rows: Iterable[Matched], lines: Sequence[int]) -> None:
        """Add the shown rows of ``rows`` (``lines[row.entry]`` is each entry's line)."""
        pending = self._pending
        for row in rows:
            if row.shown and row.translation and row.entry is not None:
                source = row.source
                pending[source.key] = _Slot(row.translation, source.kind, source.original,
                                            source.limit, lines[row.entry] or None)

    # Lookups --------------------------------------------------------------------------

    def text(self, key: str) -> str | None:
        """The translation ``key`` shows, or None (the original)."""
        shown = self._shown.get(key)
        if shown is not None:
            return shown
        slot = self._pending.pop(key, None)
        if slot is None:
            return None
        return self._check(key, slot)

    def line(self, sid: str) -> str | None:
        """A ``Say``, a menu's question, or an effect's text."""
        return self.text(line_key(sid))

    def choice(self, menu_sid: str, key: str) -> str | None:
        return self.text(choice_key(menu_sid, key))

    def name(self, define: str) -> str | None:
        return self.text(name_key(define))

    def word(self, key: str, *, style: str | None = None,
             playthrough: int | None = None) -> str | None:
        return self.text(word_key(key, style=style, playthrough=playthrough))

    def title(self, key: str) -> str | None:
        """A title, by the key ``translatekeys`` builds (``chapter_key``, ``gallery_key``,
        ...), or ``game:title`` / ``warning:text``."""
        return self.text(key)

    def value(self, text: str) -> str | None:
        """A variable text (``default x = "???"``) as it is shown (PR-F43-05)."""
        return self.text(value_key(text))

    # Checks ---------------------------------------------------------------------------

    def _check(self, key: str, slot: _Slot) -> str | None:
        result = check_entry(slot.kind, slot.original, slot.translation, key=key,
                             limit=slot.limit, line=slot.line)
        for problem in result.problems:
            if problem.code != W251 or self.dev:
                self._report(problem)
        if not result.use:
            return None
        self._shown[key] = slot.translation
        return slot.translation

    def _report(self, problem: PoProblem) -> None:
        warning = problem.warning(self.ref)
        if self.warn is not None:
            self.warn(warning)
        else:
            self._waiting.append(warning)

    def take_warnings(self) -> list[ScriptWarning]:
        """Lookup warnings raised while ``warn`` was None (then forgotten)."""
        out, self._waiting = self._waiting, []
        return out

    def sweep(self, until: float, clock: Callable[[], float] = time.perf_counter) -> bool:
        """Check unchecked entries until ``clock() >= until`` (at least one); True when
        every entry is checked (dev runs after a switch, ``07`` I-13: ≤ 2 ms slices)."""
        pending = self._pending
        while pending:
            for _ in range(SWEEP_CHUNK):
                if not pending:
                    break
                key = next(iter(pending))
                self._check(key, pending.pop(key))
            if clock() >= until:
                break
        return not pending

    @property
    def unchecked(self) -> int:
        return len(self._pending)

    def __len__(self) -> int:
        """Rows that show (or may show, until checked) a translation."""
        return len(self._shown) + len(self._pending)

    def __repr__(self) -> str:
        return f"TextTable({self.code!r}, {len(self)} texts)"


ORIGINAL: Final = TextTable()                   # the original language: every lookup None


# --- Reading a language ----------------------------------------------------------------------

@dataclass(slots=True)
class ReadResult:
    """A finished read: the table and the read's warnings (W247, W248, W254)."""

    table: TextTable
    warnings: tuple[ScriptWarning, ...] = ()
    entries: int = 0                            # entries kept from the file
    problems: tuple[PoProblem, ...] = field(default=(), repr=False)


def _cut(text: str, start: int, size: int) -> int:
    """Where a parse piece starting at ``start`` ends: after the first blank line at or
    past ``start + size`` that follows a keyword or string line (so the entry before it is
    complete and no comment carries into the next piece), else the text's end."""
    end = len(text)
    pos = start + size
    while pos < end:
        at = text.find("\n\n", pos)
        if at < 0:
            return end
        line = text[text.rfind("\n", 0, at) + 1:at]
        if line[:3] == "msg" or line[:1] == '"':
            return at + 2
        pos = at + 1
    return end


class ReadJob:
    """Read one language into a ``TextTable`` in units (module docstring).

    ``read`` returns the file's bytes (``GamePaths.read_file`` with ``po.PO_MAX_BYTES``; an
    ``AssetTooLarge`` is W247 ``large``, any other failure W247's default form).
    ``sources`` are ``translatekeys.source_texts(program, config)`` (computed once per
    program by the caller). ``language`` is the English name W247 shows (default: the
    built-in name for ``code``)."""

    def __init__(self, code: str, file: str, read: Callable[[], bytes],
                 sources: Sequence[SourceText], *, language: str | None = None,
                 dev: bool = False, clock: Callable[[], float] = time.perf_counter,
                 chunk_chars: int = PARSE_CHUNK_CHARS) -> None:
        self.code = code
        self.file = file
        self.ref = po_ref(file)
        self.language = language if language is not None else english_name(code)
        self.dev = dev
        self.steps = 0                          # units done (tests, diagnostics)
        self.result: ReadResult | None = None
        self._read = read
        self._sources = sources
        self._clock = clock
        self._chunk = max(1, int(chunk_chars))
        self._table = TextTable(code, file, dev=dev)
        self._phase = self._read_step
        self._data: bytes = b""
        self._text = ""
        self._at = 0                            # parse: next piece's first character
        self._line = 1                          # ... and its line number
        self._entries: list[PoEntry] = []
        self._lines: list[int] = []
        self._keys: set[str] = set()
        self._problems: list[PoProblem] = []
        self._count = 0
        self._rows: tuple[Matched, ...] = ()
        self._row = 0
        self._shown_texts: list[str] = []
        self._rtl: PoProblem | None = None

    @property
    def done(self) -> bool:
        return self.result is not None

    def run_for(self, until: float) -> bool:
        """Units until done or ``clock() >= until`` (at least one); True when done."""
        while self.result is None:
            self._phase()
            self.steps += 1
            if self.result is not None or self._clock() >= until:
                break
        return self.result is not None

    def run(self) -> ReadResult:
        """Every unit at once (tools, tests)."""
        while self.result is None:
            self._phase()
            self.steps += 1
        return self.result

    # Phases ---------------------------------------------------------------------------

    def _unreadable(self, form: str, problem: PoProblem | None = None) -> None:
        if problem is None:
            problem = PoProblem("W247", (form, self.file, self.language), None)
        self._table.unreadable = form
        self._finish((problem,))

    def _read_step(self) -> None:
        try:
            data = self._read()
        except AssetTooLarge:
            self._unreadable("large")
            return
        except Exception:                               # a gone or locked file
            self._unreadable("unreadable")
            return
        if not isinstance(data, (bytes, bytearray, memoryview)):
            self._unreadable("utf8")
            return
        self._data = bytes(data)
        self._phase = self._decode_step

    def _decode_step(self) -> None:
        data, self._data = self._data, b""
        text: str | None = None
        if len(data) <= PO_MAX_BYTES:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
        if text is None:
            # po.read_po gives W247's own form (large, utf8) at once.
            po = read_po(data, self.ref, lean=True, language=self.language)
            self._unreadable(po.unreadable or "utf8", po.problems[0] if po.problems else None)
            return
        self._text = text.replace("\r\n", "\n") if "\r" in text else text
        self._phase = self._parse_step

    def _parse_step(self) -> None:
        text = self._text
        start = self._at
        end = _cut(text, start, self._chunk)
        if start == 0:
            piece, offset = text[:end], 0
        else:
            piece = _PIECE_HEAD + text[start:end]
            offset = self._line - 1 - _PIECE_HEAD_LINES
        po = read_po(piece.encode("utf-8"), self.ref, lean=True, language=self.language)
        if po.unreadable is not None:
            self._unreadable("entries")
            return
        self._count += len(po.entries) + len(po.problems)
        if self._count > PO_MAX_ENTRIES:
            self._unreadable("entries")
            return
        found = [PoProblem(p.code, p.args, p.line + offset if p.line else p.line)
                 for p in po.problems]
        keys = self._keys
        later = start > 0
        for entry in po.entries:
            line = entry.line + offset
            if later and entry.key in keys:
                found.append(PoProblem("W248", ("twice", entry.key), line))
                continue
            keys.add(entry.key)
            self._entries.append(entry)
            self._lines.append(line)
        if later and found:
            found.sort(key=lambda p: p.line or 0)
        self._problems.extend(found)
        self._line += text.count("\n", start, end)
        self._at = end
        if end >= len(text):
            self._text = ""
            self._phase = self._match_step

    def _match_step(self) -> None:
        self._rows = match(self._sources, self._entries).rows
        self._phase = self._build_step

    def _build_step(self) -> None:
        rows = self._rows[self._row:self._row + BUILD_CHUNK_ROWS]
        self._table.add(rows, self._lines)
        if self.dev:
            self._shown_texts.extend(r.translation for r in rows if r.shown)
        self._row += len(rows)
        if self._row >= len(self._rows):
            self._rows = ()
            self._phase = self._rtl_step if self.dev else self._done_step

    def _rtl_step(self) -> None:
        texts = self._shown_texts
        piece, self._shown_texts = texts[:RTL_CHUNK], texts[RTL_CHUNK:]
        self._rtl = rtl_warning(self.file, piece)
        if self._rtl is not None or not self._shown_texts:
            self._shown_texts = []
            self._phase = self._done_step

    def _done_step(self) -> None:
        problems = list(self._problems)
        if self._rtl is not None:
            problems.append(self._rtl)
        self._finish(tuple(problems), entries=len(self._entries))
        self._entries = []
        self._lines = []
        self._keys = set()

    def _finish(self, problems: tuple[PoProblem, ...], entries: int = 0) -> None:
        self.result = ReadResult(self._table, tuple(p.warning(self.ref) for p in problems),
                                 entries, problems)


def read_language(code: str, file: str, data: bytes, sources: Sequence[SourceText], *,
                  language: str | None = None, dev: bool = False) -> ReadResult:
    """``ReadJob`` run at once over ``data`` (``check``, build, tests)."""
    return ReadJob(code, file, lambda: data, sources, language=language, dev=dev).run()


__all__ = ["BUILD_CHUNK_ROWS", "Discovered", "Language", "MAX_LANGUAGES", "ORIGINAL",
           "PARSE_CHUNK_CHARS", "ReadJob", "ReadResult", "TextTable", "discover",
           "po_ref", "read_language", "shown_languages"]
