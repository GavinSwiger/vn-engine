"""The Translate tab's model (F43 ``01-design.md`` §6.1, PR-F43-19, 20; ``04-technical.md`` §3,
P10; AC-F43-29).

Why this module exists: a translator works only in Studio's Translate tab, so everything the
tab shows and every change it makes is decided here, without Tk: the rows, the filters, the
statuses, typing a translation, Mark done, Copy original, Remove unused, re-matching after a
script save, the undo steps, and the ``.po`` bytes to save. W9's ``translateview.py`` draws it.

**The truth is the file.** The model holds one language's ``.po`` entries in file order
(``read_po(lean=False)``, so Was, notes, refs and translator comments survive) and the
story's ``SourceText`` list (``translatekeys.source_texts``; in Studio, the check child's
``texts`` event). The rows always come from ``translatematch.match`` over the two, so the
tab, ``check``, build and the game agree on every status:

- one row per source text, in script order, New / Changed / Done;
- one **Unused** row per entry no source claims, after them, in file order. Unused rows are
  kept until **Remove unused**; they can't be edited.

**Edits** (PR-F43-20), each one undo step:

- ``set_translation``: typing in a **New** row makes it **Done**; a **Changed** row stays
  Changed (Was kept) until ``mark_done``; clearing the box makes the row New again. Steps
  typed into the same row one after another merge into one step until ``seal()`` (W9 seals
  when the selection or focus moves), as a text box's undo does.
- ``mark_done``, ``copy_original``, ``remove_unused``, ``apply_updates`` (an import, one
  step; ``translateio.plan_import`` builds it), ``rematch``.
- A written entry is the row's whole entry again: its key, original and who are the
  source's, ``#.`` note ``Hana · festival``, ``#:`` the source's place; the translator's
  ``# `` comments are kept. Entries are frozen; changes use ``dataclasses.replace``.

**Re-matching** (``rematch``, after each script save or check; PR-F43-20, AC-F43-31): an
entry is rewritten when ``Matched.updated`` says so (moved key, new original, new status,
Was or who), when an Unused (``#~``) entry is matched again, and when a now-unused entry isn't
``#~`` yet. If anything was rewritten the entries are written in canonical order (source order,
then Unused in file order) as one undo step; otherwise nothing changes (a file Poedit
reordered isn't touched just by opening it). A source with no entry stays a New row with no
entry: the entry is written when someone types (``translateio`` exports New rows anyway).

**Unsaved and undo.** ``dirty`` is "the entries differ from the last ``mark_saved()``" by step
identity, so undoing back to the saved step is clean again. ``data()`` is the file's
canonical bytes (``po.write_po``; the file's own header and header comments, else
``header_for(code)``). W9 puts ``(ref, data())`` into F45's check overlay while dirty and
writes it on Ctrl+S.

**Problems.** Rows an import brought in with a problem (PR-F43-22) carry its text
(``Row.problem``) until edited; ``live_check`` gives the pane's W248–W251 texts for any text.

Pure: no Tk, no file access. Imports ``script`` (``po``, ``translatekeys``,
``translatematch``, ``translatecheck``) only.
"""

import enum
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import count
from typing import Final

from engine.script.po import PoEntry, PoFile, header_for, read_po, write_po
from engine.script.translatecheck import check_entry
from engine.script.translatekeys import (
    CHOICE_SEP, PREFIXES, SourceText, TextKind, is_script_key, key_scene)
from engine.script.translatematch import Matched, Status, match

# --- Texts (design §6.1, §6.2, final) ------------------------------------------------------------

STATUS_TEXTS: Final[Mapping[Status, str]] = {
    Status.NEW: "New", Status.CHANGED: "Changed", Status.DONE: "Done", Status.UNUSED: "Unused"}
ORIGINAL_TAG: Final = "original"            # the original language's line in the list
WAS: Final = "Was"
ALL: Final = "All"
NO_WHO: Final = "—"                         # Who of narration and non-script texts
REMOVE_UNUSED: Final = "Remove unused ({n})"
REMOVE_UNUSED_ASK: Final = ("Remove {n} unused translations? They belong to text that's no "
                            "longer in the game.")
REMOVE: Final = "Remove"
NOTE_SEP: Final = " · "                     # "#. Hana · festival"

# Undo step titles (Edit ▸ Undo {title}).
TYPE_STEP: Final = "Translation"
DONE_STEP: Final = "Mark done"
COPY_STEP: Final = "Copy original"
REMOVE_STEP: Final = "Remove unused"
MATCH_STEP: Final = "Update translations"
IMPORT_STEP: Final = "Import"

UNDO_MAX: Final = 200                       # steps kept (the oldest goes first)


class Show(enum.Enum):
    """The Show filter (PR-F43-19). ``ALL`` is every text in the game; Unused rows show only
    under ``UNUSED`` (they are never shown in the game either)."""

    ALL = "all"
    NEEDS_WORK = "needs_work"
    NEW = "new"
    CHANGED = "changed"
    DONE = "done"
    UNUSED = "unused"


SHOW_TEXTS: Final[Mapping[Show, str]] = {
    Show.ALL: "All", Show.NEEDS_WORK: "Needs work", Show.NEW: "New", Show.CHANGED: "Changed",
    Show.DONE: "Done", Show.UNUSED: "Unused"}

KIND_TEXTS: Final[Mapping[TextKind, str]] = {
    TextKind.LINE: "Story lines", TextKind.QUESTION: "Questions", TextKind.CHOICE: "Choices",
    TextKind.NAME: "Names", TextKind.WORD: "Button words", TextKind.TITLE: "Titles",
    TextKind.GAME: "Game", TextKind.EFFECT: "Effects", TextKind.VALUE: "Variable texts"}

_SHOWN: Final[Mapping[Show, frozenset[Status]]] = {
    Show.ALL: frozenset((Status.NEW, Status.CHANGED, Status.DONE)),
    Show.NEEDS_WORK: frozenset((Status.NEW, Status.CHANGED)),
    Show.NEW: frozenset((Status.NEW,)),
    Show.CHANGED: frozenset((Status.CHANGED,)),
    Show.DONE: frozenset((Status.DONE,)),
    Show.UNUSED: frozenset((Status.UNUSED,)),
}
_PREFIX_KINDS: Final[Mapping[str, TextKind]] = {
    "name": TextKind.NAME, "word": TextKind.WORD, "value": TextKind.VALUE,
    "game": TextKind.GAME, "warning": TextKind.GAME}


def kind_of_key(key: str) -> TextKind:
    """An Unused entry's kind from its key alone: prefixed keys by prefix (titles for the
    title families), a choice's ``#``, else a story line."""
    if not is_script_key(key):
        head = key.partition(":")[0]
        return _PREFIX_KINDS.get(head, TextKind.TITLE if head in PREFIXES else TextKind.LINE)
    return TextKind.CHOICE if CHOICE_SEP in key else TextKind.LINE


# --- Rows and filters ----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Row:
    """One table row. ``who`` is the speaker's define name (``""``: none; the view shows
    ``NO_WHO`` or the character's name). ``was`` only for Changed. ``problem``: an import's
    problem text, until the row is edited."""

    key: str
    kind: TextKind
    status: Status
    original: str
    translation: str = ""
    was: str | None = None
    scene: str = ""
    who: str = ""
    ref: str | None = None
    limit: int | None = None
    comments: tuple[str, ...] = ()
    problem: str | None = None

    @property
    def needs_work(self) -> bool:
        return self.status is Status.NEW or self.status is Status.CHANGED

    @property
    def status_text(self) -> str:
        return STATUS_TEXTS[self.status]


@dataclass(frozen=True, slots=True)
class Filter:
    """Show, Kind, Scene, Who and search, combined with "and" (AC-F43-29). None (and an empty
    search) admits everything; ``who=""`` is the rows with no speaker. Search ignores case and
    looks in the original and the translation."""

    show: Show = Show.ALL
    kind: TextKind | None = None
    scene: str | None = None
    who: str | None = None
    search: str = ""

    def admits(self, row: Row) -> bool:
        if row.status not in _SHOWN[self.show]:
            return False
        if self.kind is not None and row.kind is not self.kind:
            return False
        if self.scene is not None and row.scene != self.scene:
            return False
        if self.who is not None and row.who != self.who:
            return False
        if self.search:
            needle = self.search.casefold()
            return needle in row.original.casefold() or needle in row.translation.casefold()
        return True


@dataclass(frozen=True, slots=True)
class Update:
    """One row's new translation from an import: ``changed`` makes it Changed with ``was``
    (the original it was translated from)."""

    key: str
    translation: str
    changed: bool = False
    was: str | None = None


def note_for(source: SourceText, names: Mapping[str, str] | None = None) -> str:
    """The ``#.`` note of a written entry: ``Hana · festival`` (the character's name when
    ``names`` has it, else the define name), or the scene alone."""
    who = (names or {}).get(source.who, source.who) if source.who else ""
    return NOTE_SEP.join(part for part in (who, source.scene) if part)


def capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


# --- Undo steps ----------------------------------------------------------------------------------

_ids = count(1)


@dataclass(slots=True)
class _Step:
    """One undo step: the entries before and after (``index``/``old``/``new`` for a one-entry
    change, ``old is None`` an insert; else whole lists) and the problem marks before and
    after. ``key``: the row a typing step belongs to (merging); ``open``: still merging."""

    title: str
    ident: int
    before: tuple[PoEntry, ...] | None = None
    after: tuple[PoEntry, ...] | None = None
    index: int = -1
    old: PoEntry | None = None
    new: PoEntry | None = None
    marks_before: dict[str, str] | None = None
    marks_after: dict[str, str] | None = None
    key: str | None = None
    open: bool = False


# --- The model -----------------------------------------------------------------------------------

class TranslateModel:
    """One language's table (module docstring). ``code`` is the language code; ``sources``
    the story's texts; ``po`` the file as read (None: a new, empty file); ``names`` maps a
    define name to the character's name for notes."""

    def __init__(self, code: str, sources: Sequence[SourceText], po: PoFile | None = None, *,
                 names: Mapping[str, str] | None = None) -> None:
        self.code = code
        self._header = po.header if po is not None and po.header is not None else header_for(code)
        self._header_comments = po.header_comments if po is not None else ()
        self._entries: list[PoEntry] = list(po.entries) if po is not None else []
        self._sources: tuple[SourceText, ...] = tuple(sources)
        self._names: dict[str, str] = dict(names or {})
        self._marks: dict[str, str] = {}
        self._undo: list[_Step] = []
        self._redo: list[_Step] = []
        self._saved = 0                         # the step id the file on disk is at
        self._rows: list[Row] = []
        self._at: dict[str, int] = {}           # key → row position
        self._entry_of: list[int | None] = []   # source row → entry index
        self._matched: tuple[Matched, ...] = ()
        self._unused: list[int] = []
        self._rebuild()

    @classmethod
    def from_bytes(cls, code: str, sources: Sequence[SourceText], data: bytes | None, *,
                   ref: str | None = None, names: Mapping[str, str] | None = None
                   ) -> "TranslateModel":
        """A model over a file's bytes (None: no file yet), read with ``lean=False``."""
        po = None
        if data is not None:
            po = read_po(data, ref or f"translations/{code}.po", lean=False)
        return cls(code, sources, po, names=names)

    # -- Reading --------------------------------------------------------------------------------

    @property
    def rows(self) -> Sequence[Row]:
        """Every row: source rows in script order, then Unused rows in file order."""
        return tuple(self._rows)

    @property
    def entries(self) -> tuple[PoEntry, ...]:
        """The file's entries as ``data()`` writes them."""
        return tuple(self._entries)

    @property
    def sources(self) -> tuple[SourceText, ...]:
        return self._sources

    def row(self, key: str) -> Row | None:
        at = self._at.get(key)
        return self._rows[at] if at is not None else None

    def visible(self, flt: Filter = Filter()) -> list[Row]:
        return [row for row in self._rows if flt.admits(row)]

    def counts(self) -> dict[Status, int]:
        out = dict.fromkeys(Status, 0)
        for row in self._rows:
            out[row.status] += 1
        return out

    def percent_done(self) -> int:
        """Done of the game's texts, rounded down (the list's ``82 %``); 100 with none."""
        c = self.counts()
        total = c[Status.NEW] + c[Status.CHANGED] + c[Status.DONE]
        return 100 if total == 0 else c[Status.DONE] * 100 // total

    def scenes(self) -> list[str]:
        """The Scene filter's choices: scenes of the game's texts in script order."""
        return list(dict.fromkeys(s.scene for s in self._sources))

    def whos(self) -> list[str]:
        """The Who filter's choices: speakers in script order (``""`` first, when any row
        has none)."""
        found = dict.fromkeys(s.who for s in self._sources)
        return sorted(found, key=lambda who: who != "")

    def kinds(self) -> list[TextKind]:
        """The Kind filter's choices: the kinds the game has, in ``TextKind`` order."""
        found = {s.kind for s in self._sources}
        return [kind for kind in TextKind if kind in found]

    def next_needing_work(self, key: str | None, flt: Filter = Filter()) -> str | None:
        """The key of the next visible row after ``key`` that needs work, wrapping (Ctrl+Enter;
        None: none). ``key`` None starts at the top."""
        rows = self.visible(flt)
        start = 0
        if key is not None:
            for i, row in enumerate(rows):
                if row.key == key:
                    start = i + 1
                    break
        for row in rows[start:] + rows[:start]:
            if row.needs_work and row.key != key:
                return row.key
        return None

    def live_check(self, key: str, text: str) -> tuple[str, ...]:
        """The pane's live check (W248 long, W249–W251) for ``text`` typed into row ``key``:
        texts without file and line, capitalized; ``()`` when fine."""
        row = self.row(key)
        if row is None or not text:
            return ()
        result = check_entry(row.kind, row.original, text, key=key, limit=row.limit)
        return tuple(capitalized(problem.message()) for problem in result.problems)

    def unused_count(self) -> int:
        return len(self._unused)

    # -- Saving ---------------------------------------------------------------------------------

    def data(self) -> bytes:
        """The ``.po`` bytes to save (and to put in the check overlay while dirty)."""
        return write_po(PoFile(self._header, tuple(self._entries), self._header_comments))

    @property
    def dirty(self) -> bool:
        return self._top() != self._saved

    def mark_saved(self) -> None:
        self.seal()
        self._saved = self._top()

    # -- Edits ----------------------------------------------------------------------------------

    def set_translation(self, key: str, text: str, *, merge: bool = True,
                        title: str = TYPE_STEP) -> bool:
        """Set row ``key``'s translation (PR-F43-20): New becomes Done, Changed stays Changed,
        empty makes it New. False when nothing changed or the row can't be edited (Unused,
        unknown). ``merge``: join the open typing step of the same row."""
        at = self._at.get(key)
        if at is None or at >= len(self._sources):
            return False
        row = self._rows[at]
        if text == row.translation:
            return False
        if not text:
            status, was = Status.NEW, None
        elif row.status is Status.CHANGED:
            status, was = Status.CHANGED, row.was
        else:
            status, was = Status.DONE, None
        self._write(at, text, status, was, title, merge)
        return True

    def mark_done(self, key: str) -> bool:
        """A Changed row becomes Done (its Was dropped). False for any other row."""
        at = self._at.get(key)
        if at is None or at >= len(self._sources):
            return False
        row = self._rows[at]
        if row.status is not Status.CHANGED:
            return False
        self._write(at, row.translation, Status.DONE, None, DONE_STEP, False)
        return True

    def copy_original(self, key: str) -> bool:
        """The original into the translation (one step; a New row becomes Done)."""
        row = self.row(key)
        if row is None:
            return False
        return self.set_translation(key, row.original, merge=False, title=COPY_STEP)

    def remove_unused(self, keys: Iterable[str] | None = None) -> int:
        """Delete the Unused entries (``keys``: only those), one step. Returns how many."""
        chosen = set(self._unused)
        if keys is not None:
            wanted = set(keys)
            chosen = {e for e in chosen if self._entries[e].key in wanted}
        if not chosen:
            return 0
        after = [entry for e, entry in enumerate(self._entries) if e not in chosen]
        self._whole(REMOVE_STEP, after, dict(self._marks))
        return len(chosen)

    def rematch(self, sources: Sequence[SourceText] | None = None, *,
                names: Mapping[str, str] | None = None) -> bool:
        """Take the story's new texts (None: the same) and write the moved entries into the
        file as one undo step (module docstring). True when the file changed."""
        if names is not None:
            self._names = dict(names)
        if sources is not None:
            self._sources = tuple(sources)
        self.seal()
        self._rebuild()
        entries = self._entries
        written: list[PoEntry] = []
        changed = False
        for i, m in enumerate(self._matched):
            e = self._entry_of[i]
            if e is None:
                continue
            old = entries[e]
            if m.updated or old.obsolete:
                new = self._entry(i, m.translation, m.status, m.was, old)
                changed = changed or new != old
                written.append(new)
            else:
                written.append(old)
        for e in self._unused:
            old = entries[e]
            if not old.obsolete:
                changed = True
                written.append(replace(old, obsolete=True))
            else:
                written.append(old)
        if not changed:
            return False
        self._whole(MATCH_STEP, written, dict(self._marks))
        return True

    def apply_updates(self, updates: Sequence[Update], *, marks: Mapping[str, str] | None = None,
                      title: str = IMPORT_STEP) -> bool:
        """Several rows' translations at once, one undo step (an import). Unknown and Unused
        keys are ignored; ``marks`` (key → problem text) mark rows. True when anything
        changed."""
        new_marks = dict(self._marks)
        replaced: dict[int, PoEntry] = {}
        inserts: dict[int, list[PoEntry]] = {}
        for update in updates:
            at = self._at.get(update.key)
            if at is None or at >= len(self._sources):
                continue
            status = (Status.NEW if not update.translation else
                      Status.CHANGED if update.changed else Status.DONE)
            was = update.was if status is Status.CHANGED else None
            e = self._entry_of[at]
            new = self._entry(at, update.translation, status, was,
                              self._entries[e] if e is not None else None)
            new_marks.pop(update.key, None)
            if e is not None:
                if new != self._entries[e]:
                    replaced[e] = new
            elif update.translation:
                inserts.setdefault(self._anchor(at), []).append(new)
        for key, text in (marks or {}).items():
            if key in self._at and self._at[key] < len(self._sources):
                new_marks[key] = text
        if not replaced and not inserts and new_marks == self._marks:
            return False
        after: list[PoEntry] = []
        for e, entry in enumerate(self._entries):
            after.extend(inserts.get(e, ()))
            after.append(replaced.get(e, entry))
        after.extend(inserts.get(len(self._entries), ()))
        self._whole(title, after, new_marks)
        return True

    # -- Undo -----------------------------------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_title(self) -> str | None:
        return self._undo[-1].title if self._undo else None

    def redo_title(self) -> str | None:
        return self._redo[-1].title if self._redo else None

    def seal(self) -> None:
        """End the open typing step: the next keystroke starts a new undo step."""
        if self._undo:
            self._undo[-1].open = False

    def undo(self) -> bool:
        if not self._undo:
            return False
        step = self._undo.pop()
        step.open = False
        if step.before is not None:
            self._entries = list(step.before)
        elif step.old is None:
            del self._entries[step.index]
        else:
            self._entries[step.index] = step.old
        self._marks = dict(step.marks_before or {})
        self._redo.append(step)
        self._rebuild()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        step = self._redo.pop()
        self._do(step)
        self._undo.append(step)
        self._rebuild()
        return True

    # -- Inside ---------------------------------------------------------------------------------

    def _top(self) -> int:
        return self._undo[-1].ident if self._undo else 0

    def _do(self, step: _Step) -> None:
        if step.after is not None:
            self._entries = list(step.after)
        elif step.old is None:
            assert step.new is not None
            self._entries.insert(step.index, step.new)
        else:
            assert step.new is not None
            self._entries[step.index] = step.new
        self._marks = dict(step.marks_after or {})

    def _push(self, step: _Step) -> None:
        self._redo.clear()
        self._undo.append(step)
        if len(self._undo) > UNDO_MAX:
            del self._undo[0]

    def _whole(self, title: str, after: list[PoEntry], marks: dict[str, str]) -> None:
        self.seal()
        step = _Step(title, next(_ids), tuple(self._entries), tuple(after),
                     marks_before=dict(self._marks), marks_after=marks)
        self._do(step)
        self._push(step)
        self._rebuild()

    def _entry(self, i: int, translation: str, status: Status, was: str | None,
               base: PoEntry | None) -> PoEntry:
        """Source row ``i``'s whole entry with this translation and status."""
        source = self._sources[i]
        changed = status is Status.CHANGED and bool(translation)
        note = note_for(source, self._names)
        values = dict(key=source.key, original=source.original, translation=translation,
                      changed=changed, was=was if changed else None, who=source.who,
                      notes=(note,) if note else (),
                      refs=(source.ref,) if source.ref else (), obsolete=False)
        return replace(base, **values) if base is not None else PoEntry(**values)

    def _anchor(self, i: int) -> int:
        """Where a new entry for source row ``i`` goes: after the entry of the nearest earlier
        row that has one, else before the nearest later one's, else at the start."""
        for j in range(i - 1, -1, -1):
            e = self._entry_of[j]
            if e is not None:
                return e + 1
        for j in range(i + 1, len(self._entry_of)):
            e = self._entry_of[j]
            if e is not None:
                return e
        return 0

    def _write(self, at: int, translation: str, status: Status, was: str | None, title: str,
               merge: bool) -> None:
        """One row's edit: replace or insert its entry, merge or push the step, and update the
        row in place (the full re-match would give the same row: its entry now has its key)."""
        key = self._sources[at].key
        e = self._entry_of[at]
        base = self._entries[e] if e is not None else None
        new = self._entry(at, translation, status, was, base)
        marks_before = dict(self._marks)
        self._marks.pop(key, None)
        top = self._undo[-1] if self._undo else None
        if (merge and top is not None and top.open and top.key == key and not self._redo
                and top.before is None):
            # Merge into the open typing step: keep its "before", take this "after".
            top.new = new
            top.marks_after = dict(self._marks)
            if e is not None:
                self._entries[e] = new
            else:                                # cannot happen: the step inserted it
                self._insert(at, new)
        else:
            self.seal()
            if e is not None:
                step = _Step(title, next(_ids), index=e, old=base, new=new,
                             marks_before=marks_before, marks_after=dict(self._marks),
                             key=key, open=merge)
                self._entries[e] = new
            else:
                index = self._insert(at, new)
                step = _Step(title, next(_ids), index=index, old=None, new=new,
                             marks_before=marks_before, marks_after=dict(self._marks),
                             key=key, open=merge)
            self._push(step)
        status_now = Status.NEW if not translation else status
        self._rows[at] = replace(self._rows[at], status=status_now, translation=translation,
                                 was=new.was, comments=new.comments, problem=None)

    def _insert(self, at: int, new: PoEntry) -> int:
        index = self._anchor(at)
        self._entries.insert(index, new)
        self._entry_of = [None if e is None else e + 1 if e >= index else e
                          for e in self._entry_of]
        self._entry_of[at] = index
        self._unused = [e + 1 if e >= index else e for e in self._unused]
        return index

    def _rebuild(self) -> None:
        """Rows from ``match`` over the sources and the entries."""
        result = match(self._sources, self._entries)
        self._matched = result.rows
        self._entry_of = [m.entry for m in result.rows]
        self._unused = list(result.unused)
        rows: list[Row] = []
        marks = self._marks
        for m, e in zip(result.rows, self._entry_of):
            s = m.source
            comments = self._entries[e].comments if e is not None else ()
            rows.append(Row(s.key, s.kind, m.status, s.original, m.translation, m.was, s.scene,
                            s.who, s.ref, s.limit, comments, marks.get(s.key)))
        for e in result.unused:
            entry = self._entries[e]
            rows.append(Row(entry.key, kind_of_key(entry.key), Status.UNUSED, entry.original,
                            entry.translation, entry.was, key_scene(entry.key), entry.who,
                            entry.refs[0] if entry.refs else None, None, entry.comments))
        self._rows = rows
        at: dict[str, int] = {}
        for i, row in enumerate(rows):
            at.setdefault(row.key, i)
        self._at = at


__all__ = ["ALL", "COPY_STEP", "DONE_STEP", "Filter", "IMPORT_STEP", "KIND_TEXTS", "MATCH_STEP",
           "NOTE_SEP", "NO_WHO", "ORIGINAL_TAG", "REMOVE", "REMOVE_STEP", "REMOVE_UNUSED",
           "REMOVE_UNUSED_ASK", "Row", "SHOW_TEXTS", "STATUS_TEXTS", "Show", "TYPE_STEP",
           "TranslateModel", "UNDO_MAX", "Update", "WAS", "capitalized", "kind_of_key",
           "note_for"]
