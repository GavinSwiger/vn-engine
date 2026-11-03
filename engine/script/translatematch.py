"""Matching a language's entries to the current story (F43 PR-F43-03; ``04-technical.md``
§7.2): the one function that decides each text's status, New, Changed, Done or Unused.

Why this module exists: the game, ``check``, build and Studio must agree on which
translation a text shows and which entries are Unused, after any script edit, so they share
this pure, deterministic function. Standard library plus ``script`` only (Studio imports it).

**Statuses.** An entry with no translation is New; a ``fuzzy`` one Changed (its ``was`` the
original it was translated from); else Done. Entries that no source claims are Unused
(kept, never shown). A source no entry claims is New with no entry.

**Rules**, in order, each over what the earlier ones left:

1. **Key.** Equal keys match (an Unused entry whose key is back is restored). If the stored
   original differs from today's (``word:``, ``name:``, titles; a sid's text change makes a
   new sid) a translated entry becomes Changed, Was = the old original.
2. **Same text.** Unclaimed entries are indexed by (family, who, original) as FIFO lists in
   file order; unmatched sources in script order take the first. Status kept (a renamed
   scene, a moved line, ``~2`` duplicates in order).
3. **Near.** Candidates are the first ``CANDIDATES_MAX`` unclaimed entries (file order) with
   the source's scene and who. One whose previous and next matched entries (file order) are
   the source's script neighbours wins; else the best similarity ``≥ SIMILARITY_MIN`` over
   the first ``COMPARE_CHARS`` tag-stripped characters (``difflib.SequenceMatcher``,
   ``autojunk=False``; the quick ratios prefilter). Ties: neighbours, ratio, file order. A
   translated entry moves as Changed with Was.
4. **New.**

*Family* keeps rule 2 within one sort of key: script texts (sids) with script texts, and each
prefixed kind (``word``, ``chapter``, ...) with its own, so a word never takes a line's
translation.
"""

import bisect
import difflib
import enum
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from engine.script.translatekeys import SourceText, is_script_key, key_scene

CANDIDATES_MAX: Final = 64           # rule 3's candidates per source
COMPARE_CHARS: Final = 1000          # rule 3 compares this many tag-stripped characters
SIMILARITY_MIN: Final = 0.5          # rule 3's least ratio

_TAG_RE = re.compile(r"\{\{|\{[^{}]*\}")


class Status(enum.Enum):
    NEW = "new"
    CHANGED = "changed"
    DONE = "done"
    UNUSED = "unused"


class EntryLike(Protocol):
    """What the matcher reads from a stored entry (P3's ``PoEntry`` or ``Entry`` below):
    ``original`` is ``msgid``, ``translation`` ``msgstr`` (``""`` = none), ``changed`` the
    ``fuzzy`` flag, ``was`` the ``#| msgid`` (None: none), ``who`` the ``#. vn-who:`` name
    (``""``: none)."""

    @property
    def key(self) -> str: ...
    @property
    def original(self) -> str: ...
    @property
    def translation(self) -> str: ...
    @property
    def changed(self) -> bool: ...
    @property
    def was(self) -> str | None: ...
    @property
    def who(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Entry:
    """A plain ``EntryLike`` (tests, CSV import)."""

    key: str
    original: str
    translation: str = ""
    changed: bool = False
    was: str | None = None
    who: str = ""


@dataclass(frozen=True, slots=True)
class Matched:
    """One source's result. ``entry`` is the index into the entries given (None: New with no
    entry); ``rule`` 1–4; ``was`` is set only for Changed; ``translation`` is ``""`` for
    New. ``updated``: the entry must be rewritten (moved key, new original, new status, Was
    or who) for the file to say this; an entry that was ``#~`` (Unused) and is matched again
    needs rewriting too, which only the caller knows."""

    source: SourceText
    status: Status
    translation: str
    was: str | None
    entry: int | None
    rule: int
    updated: bool

    @property
    def key(self) -> str:
        return self.source.key

    @property
    def shown(self) -> bool:
        """Done and Changed show the translation (PR-F43-02)."""
        return self.status is Status.DONE or self.status is Status.CHANGED


@dataclass(frozen=True, slots=True)
class MatchResult:
    """``rows`` in source order; ``unused`` the unclaimed entries' indices in file order."""

    rows: tuple[Matched, ...]
    unused: tuple[int, ...]

    def by_key(self) -> Mapping[str, Matched]:
        return {row.key: row for row in self.rows}

    def counts(self) -> Mapping[Status, int]:
        out = dict.fromkeys(Status, 0)
        for row in self.rows:
            out[row.status] += 1
        out[Status.UNUSED] = len(self.unused)
        return out


def entry_status(entry: EntryLike) -> Status:
    """A stored entry's own status (before matching)."""
    if not entry.translation:
        return Status.NEW
    return Status.CHANGED if entry.changed else Status.DONE


def strip_tags(text: str) -> str:
    """Text without ``{tags}`` (``{{`` is a brace), cut to ``COMPARE_CHARS``."""
    return _TAG_RE.sub(lambda m: "{" if m.group() == "{{" else "", text)[:COMPARE_CHARS]


def _family(key: str) -> str:
    return "" if is_script_key(key) else key_scene(key)


def _translated_was(entry: EntryLike) -> str:
    """What a translated entry's translation was made from."""
    if entry.changed and entry.was is not None:
        return entry.was
    return entry.original


def _row(source: SourceText, entry: EntryLike, index: int, rule: int,
         as_changed: bool) -> Matched:
    """``source`` takes ``entry``. ``as_changed``: the source's text differs from what the
    entry was matched on, so a translated entry becomes Changed."""
    status = entry_status(entry)
    was: str | None = None
    if status is not Status.NEW:
        if as_changed or source.original != entry.original:
            status = Status.CHANGED
            was = _translated_was(entry)
        elif status is Status.CHANGED:
            was = entry.was
    translation = entry.translation if status is not Status.NEW else ""
    updated = (source.key != entry.key or source.original != entry.original
               or (status is Status.CHANGED) != bool(entry.changed)
               or (status is Status.CHANGED and was != entry.was)
               or source.who != entry.who)
    return Matched(source, status, translation, was, index, rule, updated)


def _ratio(a: str, b: str, floor: float) -> float:
    """The similarity of ``a`` and ``b``, or -1 when the quick ratios show it is under
    ``floor``."""
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if matcher.real_quick_ratio() < floor or matcher.quick_ratio() < floor:
        return -1.0
    return matcher.ratio()


def match(sources: Sequence[SourceText], entries: Sequence[EntryLike]) -> MatchResult:
    """Assign ``entries`` (file order) to ``sources`` (``source_texts`` order) by rules
    1–4. Pure and deterministic; never raises for any entries."""
    n = len(sources)
    rows: list[Matched | None] = [None] * n
    matched: list[int] = []                             # claimed entries, sorted (rule 3)
    owner: list[int | None] = [None] * len(entries)     # entry → source index
    claimed = [False] * len(entries)

    def take(s: int, e: int, rule: int, as_changed: bool) -> None:
        rows[s] = _row(sources[s], entries[e], e, rule, as_changed)
        owner[e] = s
        claimed[e] = True
        if rule == 3:
            bisect.insort(matched, e)

    # Rule 1: same key (the first entry of a key; P3 reports duplicates).
    first: dict[str, int] = {}
    for e, entry in enumerate(entries):
        first.setdefault(entry.key, e)
    for s, source in enumerate(sources):
        e = first.get(source.key)
        if e is not None and not claimed[e]:
            take(s, e, 1, False)

    # Rule 2: same family, who and original; FIFO in file order.
    same: dict[tuple[str, str, str], deque[int]] = defaultdict(deque)
    for e, entry in enumerate(entries):
        if not claimed[e]:
            same[(_family(entry.key), entry.who, entry.original)].append(e)
    if same:
        for s, source in enumerate(sources):
            if rows[s] is None:
                queue = same.get((_family(source.key), source.who, source.original))
                if queue:
                    take(s, queue.popleft(), 2, False)

    # Rule 3: near, within the same scene and who.
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for e, entry in enumerate(entries):
        if not claimed[e]:
            groups[(key_scene(entry.key), entry.who)].append(e)
    if groups:
        matched = [e for e in range(len(entries)) if claimed[e]]     # sorted
        stripped: dict[int, str] = {}
        for s, source in enumerate(sources):
            if rows[s] is not None:
                continue
            group = groups.get((source.scene, source.who))
            if not group:
                continue
            candidates = [e for e in group if not claimed[e]][:CANDIDATES_MAX]
            best = _near(s, candidates, sources, entries, owner, matched, stripped)
            if best is not None:
                take(s, best, 3, True)
                del group[group.index(best)]

    # Rule 4: New.
    out = tuple(row if row is not None else Matched(source, Status.NEW, "", None, None, 4, False)
                for row, source in zip(rows, sources))
    return MatchResult(out, tuple(e for e in range(len(entries)) if not claimed[e]))


def _neighbours(owner: list[int | None], matched: list[int], e: int
                ) -> tuple[int | None, int | None]:
    """The source indices of the nearest matched entries before and after unclaimed entry
    ``e`` in file order (None: none). ``matched`` is the sorted claimed entries."""
    at = bisect.bisect_left(matched, e)
    before = owner[matched[at - 1]] if at > 0 else None
    after = owner[matched[at]] if at < len(matched) else None
    return before, after


def _near(s: int, candidates: list[int], sources: Sequence[SourceText],
          entries: Sequence[EntryLike], owner: list[int | None], matched: list[int],
          stripped: dict[int, str]) -> int | None:
    """Rule 3's pick among ``candidates`` (file order) for source ``s``, or None."""
    if not candidates:
        return None
    want = (s - 1 if s > 0 else None, s + 1 if s + 1 < len(sources) else None)
    sitting = [] if want == (None, None) else [
        e for e in candidates if _neighbours(owner, matched, e) == want]
    pool = sitting or candidates
    floor = 0.0 if sitting else SIMILARITY_MIN
    text = strip_tags(sources[s].original)
    best: int | None = None
    best_ratio = -1.0
    for e in pool:                                       # file order: the first of a tie wins
        other = stripped.get(e)
        if other is None:
            other = stripped[e] = strip_tags(entries[e].original)
        ratio = _ratio(text, other, max(floor, best_ratio))
        if ratio > best_ratio and ratio >= floor:
            best, best_ratio = e, ratio
    return best


__all__ = ["CANDIDATES_MAX", "COMPARE_CHARS", "Entry", "EntryLike", "MatchResult", "Matched",
           "SIMILARITY_MIN", "Status", "entry_status", "match", "strip_tags"]
