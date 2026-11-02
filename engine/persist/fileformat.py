"""The ``persistent.json`` format: pre-scan, sliced read (``ReadJob``), and the cached
encoder (``PieceEncoder``) (F12 ``04-technical.md`` §4, §7.4 step 5, §7.5, §8).

Why this module exists: the file is untrusted (players edit and share it), so reading it
must never run code, blow up memory, or stall a frame for long, and a damaged entry must cost
only that entry (SEC-F12-01, -02, -05; PR-F12-12, -22). Writing must produce a file that this
same reader accepts (TR-F12-09).

The file (``format`` 1) is compact ASCII JSON with exactly six keys::

    {"format":1,"identity_scheme":1,
     "values":{"festivals":2,"hana_remembers":true},
     "seen":{"riverbank":"3fa9c2d81b07 9c1d04e2aa31~2"},
     "chosen":{"bridge/5e0c11aa9b02":"a1b2c3d4e5f6"},
     "unlocks":{"cg":["river_night"]}}

``seen`` maps a label to its seen keys (a sid is ``<label>/<key>``), space-separated;
``chosen`` maps a menu sid to its picked choice keys. A new top-level key bumps ``format``.

Reading (``ReadJob``), one bounded unit per ``step()``:

1. **Pre-scan** (no parse): over ``FILE_MAX_BYTES`` → BAD ``over 32 MB``; non-ASCII and over
   ``NON_ASCII_MAX_BYTES``, or more than ``PRESCAN_MAX`` ``{ [ , :`` bytes (which bounds the
   number of JSON values the parse can build) → BAD ``not persistent data``.
2. **Parse**: strict decode to ``str``, then ``json.loads`` with hooks refusing duplicate
   keys, NaN/Infinity, and ints over 4,300 digits. Any exception → BAD ``not valid JSON``.
3. **Classify**, ``format`` first: newer → NEWER (left alone); then the exact key set and
   section types → else BAD. A wrong ``identity_scheme`` drops seen lines and choice marks
   (W55).
4. **Values** (``READ_STEP_NAMES`` per step, known names first), **seen**, **chosen** (keys
   per step: ``READ_STEP_KEYS``), **unlocks**: bad entries are dropped (W54, counts only).
5. **Eviction** above ``EVICT_TO`` of a record's cap: keys the program no longer has first,
   then the oldest runs (W57).

The encoder escapes every string with ``ensure_ascii`` and also writes ``{ [ , :`` inside
labels, menu sids, kinds, and unlock names as ``\\uXXXX``, so only structure counts toward
the pre-scan; when the file would pass ``FILE_MAX_BYTES`` or ``PRESCAN_MAX`` it drops seen
runs first (runs the program no longer has, then the oldest), then menus (W57). It caches
its output and follows the store's changes, and its first build can be done in slices
(``PieceEncoder.warm``), so a write never costs a full encode on a frame.

A **merge** (``ReadJob(merge=MergeRules(...))``, F12 step 5; ``04`` §7.6) reads the file
another copy of the game wrote into a store already in use, with the same steps and bounds:
records are united (not after a progress clear or reset since the last sync), unlocks are
united (not after a reset) except revocable kinds (F19), which take the file's state per name
unless this process unlocked or relocked it since its last write (``store.merge_kind``, also
in the forced merge), and the values are applied last: each name this process hasn't
changed since its last write takes the file's value, and a stored name the file lacks is
removed. After a ``_clear()`` the file's values are ignored, and so they are when
``MergeRules.values`` is False (SEC-F12-08). A merge logs only W57; the caller logs W54 and
W55 from the outcome.
"""

import enum
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import chain, islice
from typing import Any

from engine.core.safefile import ReadKind, ReadResult
from engine.persist import limits
from engine.runtime import persistent as _store
from engine.runtime.persistent import (CHOSEN, KEY_RE, PROGRESS, RESET, SEEN, UNLOCK, VALUES,
                                       PersistentStore, RecordJournal, compact_json,
                                       scheme_text, valid_kind, valid_label, valid_menu_sid,
                                       valid_name, valid_unlock_name)
from engine.runtime.values import Unsaveable, freeze_untrusted

FORMAT = 1
SECTIONS = ("values", "seen", "chosen", "unlocks")
TOP_KEYS = frozenset(("format", "identity_scheme") + SECTIONS)
_KEY = KEY_RE.pattern
_KEYS_RE = re.compile(f"{_KEY}(?: {_KEY})*", re.ASCII)
_KEY_CHARS = 13                                        # a key's shortest length + its space

# W50 reasons (design §5.4, 07 I-7).
NOT_VALID_JSON = "not valid JSON"
NOT_PERSISTENT = "not persistent data"
OVER_CAP = "over 32 MB"
UNREADABLE = "couldn't be read"
NOT_REGULAR = "not a regular file"


class Outcome(enum.Enum):
    OK = "ok"
    BAD = "bad"                  # W50, quarantined
    NEWER = "newer"              # W51, left alone, READ_ONLY
    UNREADABLE = "unreadable"    # W50 "couldn't be read", no rename, READ_ONLY


@dataclass(frozen=True, slots=True)
class ReadOutcome:
    """``reason`` for BAD and UNREADABLE; ``dropped`` is W54's count; ``scheme_changed`` is
    W55; ``full`` names the records trimmed with W57."""

    kind: Outcome
    reason: str | None = None
    dropped: int = 0
    scheme_changed: bool = False
    full: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MergeRules:
    """A ``ReadJob`` that merges into a store in use (``04`` §7.6). ``values`` False skips
    the file's values: after ``MERGES_IN_A_ROW_MAX`` merges in a row the merge still
    classifies and unites records, but values aren't merged (SEC-F12-08)."""

    values: bool = True


def outcome_of_read(result: ReadResult) -> ReadOutcome | None:
    """The outcome of a read that gave no bytes to parse; None for OK and MISSING."""
    if result.kind is ReadKind.UNREADABLE:
        return ReadOutcome(Outcome.UNREADABLE, UNREADABLE)
    if result.kind is ReadKind.NOT_REGULAR:
        return ReadOutcome(Outcome.BAD, NOT_REGULAR)
    if result.kind is ReadKind.TOO_LARGE:
        return ReadOutcome(Outcome.BAD, OVER_CAP)
    return None


# --- Rules for entries read from the file (SEC-F12-05) -------------------------------------

def count_structure(data: bytes) -> int:
    """The pre-scan's count: ``{``, ``[``, ``,``, and ``:`` bytes."""
    return data.count(b"{") + data.count(b"[") + data.count(b",") + data.count(b":")


def prescan(data: bytes) -> str | None:
    """SEC-F12-02: a W50 reason if ``data`` must not be parsed, else None. C speed; no
    decode and no parse."""
    if len(data) > limits.FILE_MAX_BYTES:
        return OVER_CAP
    if len(data) > limits.NON_ASCII_MAX_BYTES and not data.isascii():
        return NOT_PERSISTENT
    if count_structure(data) > limits.PRESCAN_MAX:
        return NOT_PERSISTENT
    return None


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = dict(pairs)
    if len(out) != len(pairs):
        raise ValueError("duplicate key")
    return out


def _refuse_constant(name: str) -> None:
    raise ValueError("NaN and Infinity aren't allowed")


def _parse_int(text: str) -> int:
    """Refuses more than ``INT_MAX_DIGITS`` digits before converting, so the rule holds even
    when ``int_max_str_digits`` is lifted (SEC-F12-01c)."""
    if len(text) - (text[:1] == "-") > limits.INT_MAX_DIGITS:
        raise ValueError("number too long")
    return int(text)


def decode(data: bytes) -> str:
    """Strict: ASCII when it is ASCII, else UTF-8. ``UnicodeDecodeError`` otherwise. A BOM
    stays in the text, and ``json.loads`` refuses it."""
    return data.decode("ascii") if data.isascii() else data.decode("utf-8")


def parse(text: str) -> object:
    """``json.loads`` of an already decoded ``str`` (never bytes, SEC-F12-01b)."""
    return json.loads(text, object_pairs_hook=_no_duplicates,
                      parse_constant=_refuse_constant, parse_int=_parse_int)


def known_names(program: object) -> frozenset[str]:
    """Names the program mentions (``Program`` fields from F12 step 3; empty before)."""
    names: set[str] = set()
    for attr in ("persistent_reads", "persistent_writes", "persistent_default_names"):
        names.update(getattr(program, attr, None) or ())
    return frozenset(names)


# --- Reading -------------------------------------------------------------------------------

class ReadJob:
    """Reads one file's bytes into ``store`` in bounded steps: at launch, or as a merge
    (``merge``) into a store in use. Call ``step()`` until it returns True, then read
    ``outcome``.

    The job owns ``data`` and drops it once decoded. BAD and NEWER are decided before the
    store changes. At launch, W54, W55, and W57 are logged to ``store.log`` at the end with
    counts only; a merge logs only W57 (the caller logs W54 and W55 from the outcome). W50
    and W51 are the caller's."""

    def __init__(self, data: bytes, store: PersistentStore, program: object, *,
                 file: str | None = None, merge: MergeRules | None = None) -> None:
        self._data: bytes | None = data
        self.store = store
        self.program = program
        self.merge = merge
        self._disk: list[Any] = []           # merge: (name, value, fragment), file order
        self._present: set[str] = set()      # merge: every name in the file
        if file is not None:
            store.display = file
        self.outcome: ReadOutcome | None = None
        self.done = False
        self.steps = 0
        self.max_step_items = 0          # names or keys handled in one step
        self.max_step_lookups = 0        # Program.get calls in one step
        self._items = 0
        self._lookups = 0
        self._dropped = 0
        self._scheme_changed = False
        self._full: list[str] = []
        self._run_gen = self._run()

    def step(self) -> bool:
        """One unit of work; True when the job is done."""
        if self.done:
            return True
        self.steps += 1
        self._items = 0
        self._lookups = 0
        try:
            next(self._run_gen)
        except StopIteration:
            self.done = True
        self.max_step_items = max(self.max_step_items, self._items)
        self.max_step_lookups = max(self.max_step_lookups, self._lookups)
        return self.done

    def run(self) -> ReadOutcome:
        """Every step at once (tests, tools)."""
        while not self.step():
            pass
        assert self.outcome is not None
        return self.outcome

    # --- The steps -------------------------------------------------------------------------

    def _run(self) -> Iterator[None]:
        data = self._data
        assert data is not None
        reason = prescan(data)
        if reason is not None:
            self._data = data = None
            self.outcome = ReadOutcome(Outcome.BAD, reason)
            return
        yield
        try:
            text = decode(data)
            self._data = data = None
            obj = parse(text)
        except Exception:                    # anything the parse raises: RecursionError too
            self._data = data = None
            self.outcome = ReadOutcome(Outcome.BAD, NOT_VALID_JSON)
            return
        del text
        if type(obj) is not dict or "format" not in obj or type(obj["format"]) is not int:
            self.outcome = ReadOutcome(Outcome.BAD, NOT_PERSISTENT)
            return
        if obj["format"] > FORMAT:
            self.outcome = ReadOutcome(Outcome.NEWER)
            return
        if (obj["format"] != FORMAT or obj.keys() != TOP_KEYS
                or any(type(obj[key]) is not dict for key in SECTIONS)):
            self.outcome = ReadOutcome(Outcome.BAD, NOT_PERSISTENT)
            return
        scheme = obj["identity_scheme"]
        same_scheme = type(scheme) is int and scheme == self.store.identity_scheme
        values, seen, chosen, unlocks = (obj[key] for key in SECTIONS)
        del obj
        yield
        if self.merge is None or self._merging_values():
            yield from self._read_values(values)
        del values
        if same_scheme:
            yield from self._read_runs(SEEN, seen)
            yield from self._read_runs(CHOSEN, chosen)
        else:
            self._scheme_changed = True
        del seen, chosen
        yield from self._read_unlocks(unlocks)
        del unlocks
        yield from self._evict()
        if self.merge is not None:
            yield from self._apply_values()
        self._finish()

    def _merging_values(self) -> bool:
        return (self.merge is not None and self.merge.values
                and not self.store.cleared & VALUES)

    def _finish(self) -> None:
        store = self.store
        if self.merge is None:
            store.warn_dropped(self._dropped)
            if self._scheme_changed:
                store.log.warning("%s", scheme_text(store.display), extra={"code": "W55"})
        self.outcome = ReadOutcome(Outcome.OK, dropped=self._dropped,
                                   scheme_changed=self._scheme_changed, full=tuple(self._full))

    def _read_values(self, values: dict[str, Any]) -> Iterator[None]:
        step = max(1, limits.READ_STEP_NAMES)
        items: list[Any] = list(values.items())
        if self.merge is not None:
            self._present = set(values)
        values.clear()
        known = known_names(self.program) | self.store.known_names
        order = [i for i, (name, _) in enumerate(items) if name in known]
        order += [i for i, (name, _) in enumerate(items) if name not in known]
        budget = [limits.VALUES_MAX_ITEMS]
        for i in order:
            name, raw = items[i]
            items[i] = None
            if not self._load_value(name, raw, budget):
                self._dropped += 1
            self._items += 1
            if self._items >= step:
                yield

    def _load_value(self, name: str, raw: object, budget: list[int]) -> bool:
        store = self.store
        if (self.merge is None and store.value_count >= _store.PERSIST_MAX_NAMES
                and not store.has_value(name)):
            return False                     # no room for another name: skip the checks
        if not valid_name(name):
            return False
        if type(raw) is str and len(raw) > _store.PERSIST_MAX_BYTES:
            return False                     # can't fit; skip encoding it
        saved = budget[0]
        try:
            value = freeze_untrusted(raw, budget)
            frag = compact_json(value)
        except (Unsaveable, ValueError, RecursionError):
            budget[0] = saved
            return False
        if self.merge is not None:
            self._disk.append((name, value, frag))     # applied last (_apply_values)
            return True
        if not store.load_value(name, value, frag):
            budget[0] = saved
            return False
        return True

    def _read_runs(self, form: str, runs: dict[str, Any]) -> Iterator[None]:
        step = max(1, limits.READ_STEP_KEYS)
        group_cost = min(step, max(1, limits.READ_GROUP_KEYS))   # a group's checks ≈ keys
        cap = self.store.record_cap(form)
        valid_group = valid_label if form == SEEN else valid_menu_sid
        items: list[Any] = list(runs.items())
        runs.clear()
        for i in range(len(items)):
            if self._items + group_cost > step:
                yield
            group, text = items[i]
            items[i] = None
            self._items += group_cost
            ok = (valid_group(group) and type(text) is str and text != ""
                  and text[0] != " " and text[-1] != " ")
            pending: list[str] = []
            pos = 0
            while ok and pos < len(text):
                if self._items >= step:
                    yield
                chunk, pos = _next_chunk(text, pos, step - self._items)
                self._items += len(chunk)
                if not all(map(KEY_RE.fullmatch, chunk)):
                    ok = False
                elif len(pending) < cap:
                    pending.extend(chunk)
            if not ok:
                self._dropped += 1
            elif self.merge is None or not self.store.cleared & (PROGRESS | RESET):
                self.store.load_keys(form, group, pending)

    def _read_unlocks(self, kinds: dict[str, Any]) -> Iterator[None]:
        step = max(1, limits.READ_STEP_KEYS)
        items: list[Any] = list(kinds.items())
        kinds.clear()
        for i in range(len(items)):
            if self._items >= step:
                yield
            kind, names = items[i]
            items[i] = None
            self._items += 1
            if not valid_kind(kind) or type(names) is not list:
                self._dropped += 1
                continue
            if self.merge is not None and self.store.cleared & RESET:
                continue                     # a reset since the last sync: not united
            clean: dict[str, None] = {}
            for name in names:
                if self._items >= step:
                    yield
                self._items += 1
                if valid_unlock_name(name) and name not in clean:
                    clean[name] = None
                else:
                    self._dropped += 1
            if self.merge is not None and self.store.is_revocable(kind):
                # F19 (04 §7.5, 07 I-3): in every merge but one after a reset, even the
                # forced one, a revocable kind takes the file's state per name unless this
                # process changed it since its last write. One call, so the removal set
                # can't interleave with author code between steps.
                dropped = self.store.merge_kind(kind, list(clean))
            else:
                dropped = self.store.load_kind(kind, list(clean))
            self._dropped += 1 if dropped < 0 else dropped

    def _evict(self) -> Iterator[None]:
        """§7.4 step 5.7: records over ``EVICT_TO`` of their cap lose the keys the program
        no longer has, then their oldest runs (W57). At most ``READ_STEP_KEYS`` lookups per
        step; dropping an oldest run counts as ``READ_GROUP_KEYS`` lookups."""
        store = self.store
        step = max(1, limits.READ_STEP_KEYS)
        group_cost = min(step, max(1, limits.READ_GROUP_KEYS))
        get = getattr(self.program, "get", None)
        has_label = getattr(self.program, "label", None)
        for form in (SEEN, CHOSEN):
            target = int(limits.EVICT_TO * store.record_cap(form))
            if store.record_total(form) <= target:
                continue
            for group in list(store.records(form)) if get is not None else ():
                run = store.records(form).get(group)
                if run is None:
                    continue
                if self._lookups >= step:
                    yield
                self._lookups += 1
                if form == CHOSEN:
                    if get(group) is None:
                        store.drop_record(form, group)
                    continue
                if has_label is not None and has_label(group) is None:
                    store.drop_record(form, group)
                    continue
                unknown = []
                for key in list(run.order):
                    if self._lookups >= step:
                        yield
                    self._lookups += 1
                    if get(f"{group}/{key}") is None:
                        unknown.append(key)
                store.remove_keys(form, group, unknown)
            # Oldest first, from one snapshot: popping a dict's first key again and again
            # would rescan the removed slots each time. Runs a merge's author code adds
            # between steps are newer, so they go last.
            oldest = iter(list(store.records(form)))
            while store.record_total(form) > target and store.records(form):
                if self._lookups + group_cost > step:
                    yield
                self._lookups += group_cost
                group = next(oldest, None)
                store.drop_record(form, group if group is not None
                                  else next(iter(store.records(form))))
            store.warn_full(form)
            self._full.append(form)


    def _apply_values(self) -> Iterator[None]:
        """Merge only, the last step (``04`` §7.6): a stored name the file lacks is removed and
        each name in the file takes its value, unless this process changed it since its last
        write. Skipped after a ``_clear()`` or when ``MergeRules.values`` is False. Caps and
        give-way apply (W54). ``READ_STEP_NAMES`` names per step; the store is checked again
        at each name, since author code may run between steps."""
        store = self.store
        if not self._merging_values():
            self._disk = []
            return
        step = max(1, limits.READ_STEP_NAMES)
        present = self._present
        self._present = set()
        gone = [name for name, _ in store.value_entries() if name not in present]
        for name in gone:
            if self._items >= step:
                yield
            self._items += 1
            if name not in store.changed and not store.cleared & VALUES:
                store.merge_remove(name)
        disk = self._disk
        self._disk = []
        for i in range(len(disk)):
            if self._items >= step:
                yield
            self._items += 1
            name, value, frag = disk[i]
            disk[i] = None
            if (name in store.changed or store.cleared & VALUES
                    or store.value_frag(name) == frag):
                continue
            if not store.merge_value(name, value, frag):
                self._dropped += 1


def _next_chunk(text: str, pos: int, keys: int) -> tuple[list[str], int]:
    """At most ``keys`` valid keys from ``text`` at ``pos`` (a key is ≥ 12 characters plus
    a space), split at spaces, and the position after them."""
    end = len(text)
    limit = pos + _KEY_CHARS * keys
    if limit >= end:
        return text[pos:].split(" "), end + 1
    cut = text.rfind(" ", pos, limit)
    if cut < 0:
        cut = text.find(" ", limit)
        if cut < 0:
            cut = end
    return text[pos:cut].split(" "), cut + 1


# --- Encoding --------------------------------------------------------------------------------

_STRUCT = str.maketrans({"{": "\\u007b", "[": "\\u005b", ",": "\\u002c", ":": "\\u003a"})
_SEEN_OPEN = b',"seen":{'
_CHOSEN_OPEN = b',"chosen":{'
_UNLOCKS_OPEN = b',"unlocks":{'
_CLOSE = b"}"
_END = b"}}"

SEGMENT_GROUPS = 512         # runs per cached segment of the seen / chosen sections
BIG_PIECE = 4_096            # pieces at least this long are passed on, not copied into a join
WARM_CHECK = 64              # small units of warm-up work between two clock checks
WARM_BLOCKS = 8              # full blocks of one long run built per unit
WARM_NAMES = 128             # unlock names encoded per unit
WARM_SEGMENTS = 4            # segments joined per unit


def json_string(text: str) -> bytes:
    """A JSON string, ASCII only, with ``{ [ , :`` also escaped (SEC-F12-05, G9)."""
    return json.dumps(text, ensure_ascii=True).translate(_STRUCT).encode("ascii")


def _group_head(form: str, group: str) -> bytes | None:
    """``"group":"`` for a run that may be written; None for one that may not (a label or menu
    sid this engine can't produce is never written back, SEC-F12-05)."""
    if not (valid_label(group) if form == SEEN else valid_menu_sid(group)):
        return None
    if group.isascii():          # identifier characters, "/" and "~": nothing to escape
        return b'"' + group.encode("ascii") + b'":"'
    return json_string(group) + b':"'


@dataclass(slots=True, eq=False)
class _Segment:
    """Up to ``SEGMENT_GROUPS`` consecutive runs and their joined output. ``total`` and
    ``ctotal`` sum the written runs' sizes and pre-scan counts; ``n`` counts them."""

    names: list[str] = field(default_factory=list)
    out: list[bytes] = field(default_factory=list)
    total: int = 0
    ctotal: int = 0
    n: int = 0
    dirty: bool = False


@dataclass(slots=True, eq=False)
class _RunCache:
    """One run's output: full blocks of ``BLOCK_KEYS`` keys cached per epoch, the tail block
    per length, and the run's pieces (empty when it isn't written)."""

    epoch: int
    head: bytes | None
    seg: _Segment | None = None
    blocks: list[bytes] = field(default_factory=list)
    full_bytes: int = 0
    tail_len: int = -1
    tail: bytes | None = None
    pieces: tuple[bytes, ...] = ()
    size: int = 0
    count: int = 0

    def renew(self, epoch: int, head: bytes | None) -> None:
        self.epoch, self.head = epoch, head
        self.blocks, self.full_bytes, self.tail_len, self.tail = [], 0, -1, None


class _FormCache:
    """One section's runs in file order (the store's order), in segments, with running
    totals of the section's bytes and pre-scan count."""

    def __init__(self) -> None:
        self.groups: dict[str, _RunCache] = {}
        self.segs: list[_Segment] = []
        self.size = 0            # Σ written segments: their runs and the commas inside them
        self.count = 0
        self.k = 0               # segments holding at least one written run
        self.empty = 0           # segments with no runs left
        self.dirty: list[_Segment] = []      # segments whose output must be joined again

    def mark(self, seg: _Segment) -> None:
        if not seg.dirty:
            seg.dirty = True
            self.dirty.append(seg)

    def rebuild_some(self, count: int) -> bool:
        """Join up to ``count`` dirty segments again; True when none is left."""
        dirty = self.dirty
        while dirty and count > 0:
            seg = dirty.pop()
            if seg.dirty:
                self._rebuild(seg)
                count -= 1
        return not dirty

    @property
    def total_size(self) -> int:
        return self.size + max(0, self.k - 1)

    @property
    def total_count(self) -> int:
        return self.count + max(0, self.k - 1)

    def _seg_out(self, seg: _Segment) -> None:
        if seg.n:
            self.size -= seg.total + seg.n - 1
            self.count -= seg.ctotal + seg.n - 1
            self.k -= 1

    def _seg_in(self, seg: _Segment) -> None:
        if seg.n:
            self.size += seg.total + seg.n - 1
            self.count += seg.ctotal + seg.n - 1
            self.k += 1

    def account(self, cache: _RunCache, sign: int) -> None:
        """Add (+1) or take out (-1) a run's written pieces."""
        if not cache.pieces:
            return
        seg = cache.seg
        assert seg is not None
        self._seg_out(seg)
        seg.total += sign * cache.size
        seg.ctotal += sign * cache.count
        seg.n += sign
        self._seg_in(seg)
        self.mark(seg)

    def add(self, group: str, cache: _RunCache) -> None:
        """Append a run (no pieces yet) at the end of the order."""
        segs = self.segs
        if not segs or len(segs[-1].names) >= SEGMENT_GROUPS:
            segs.append(_Segment())
        seg = segs[-1]
        if not seg.names and self.empty:
            self.empty -= 1
        seg.names.append(group)
        cache.seg = seg
        self.groups[group] = cache

    def remove(self, group: str) -> None:
        cache = self.groups.pop(group)
        self.account(cache, -1)
        seg = cache.seg
        assert seg is not None
        seg.names.remove(group)
        self.mark(seg)
        if not seg.names:
            self.empty += 1
            if self.empty > 16 and 2 * self.empty > len(self.segs):
                self.segs = [s for s in self.segs if s.names]
                self.empty = 0

    def order(self) -> Iterator[str]:
        """Every run in order; safe while runs are removed."""
        for seg in list(self.segs):
            yield from list(seg.names)

    def write(self, out: list[bytes]) -> None:
        first = True
        for seg in self.segs:
            if not seg.n:
                continue
            if seg.dirty:
                self._rebuild(seg)
            if not first:
                out.append(b",")
            first = False
            out.extend(seg.out)
        self.dirty = []

    def _rebuild(self, seg: _Segment) -> None:
        out: list[bytes] = []
        small: list[bytes] = []
        groups = self.groups
        first = True
        for name in seg.names:
            pieces = groups[name].pieces
            if not pieces:
                continue
            if not first:
                small.append(b",")
            first = False
            for piece in pieces:
                if len(piece) >= BIG_PIECE:
                    if small:
                        out.append(b"".join(small))
                        small = []
                    out.append(piece)
                else:
                    small.append(piece)
        if small:
            out.append(b"".join(small))
        seg.out = out
        seg.dirty = False


@dataclass(slots=True, eq=False)
class _KindCache:
    epoch: int
    head: bytes                          # b'"kind":['
    parts: list[bytes] = field(default_factory=list)
    piece: bytes | None = None
    count: int = 0


@dataclass(slots=True)
class _Piece:
    name: str
    pieces: list[bytes]
    size: int
    count: int


class _Section:
    """Running byte and pre-scan totals of the unlocks section."""

    def __init__(self, items: list[_Piece]) -> None:
        self.reset(items)

    def reset(self, items: list[_Piece]) -> None:
        self.items = items
        self.n = len(items)
        self.size = sum(p.size for p in items)
        self.count = sum(p.count for p in items)

    @property
    def total_size(self) -> int:
        return self.size + max(0, self.n - 1)

    @property
    def total_count(self) -> int:
        return self.count + max(0, self.n - 1)


class PieceEncoder:
    """The file as byte pieces (main thread; joined by the writer), from caches that follow
    the store, so a write costs only what changed since the last one (F12 step 5).

    - **Runs** (seen labels, choice menus): full blocks of ``BLOCK_KEYS`` keys are cached per
      ``(group, epoch)``, the tail block per length, and runs are grouped into segments of
      ``SEGMENT_GROUPS`` whose joined output is cached until one of their runs changes. The
      store's ``RecordJournal`` says which runs changed, so nothing walks every run.
    - **Unlocks** are cached per ``(kind, epoch)`` and extended as names are added;
      **values** per ``values_gen``.
    - **Warm-up:** the first build for a store (up to seconds for a hostile store of
      hundreds of thousands of labels) is done by ``warm(store, until, clock)`` in slices
      that end when ``clock()`` reaches ``until``. ``warm`` also takes in the changes made
      since the last call, in slices. ``encode`` finishes whatever is left at once, so the
      sync calls it only after ``warm`` has returned True.

    ``program`` (optional) lets the trim drop runs the story no longer has first."""

    def __init__(self, program: object = None) -> None:
        self._program = program
        self._store: PersistentStore | None = None
        self._journal: RecordJournal | None = None
        self._warm_gen: Iterator[None] | None = None
        self._backlog: list[tuple[str, str | None, bool]] = []
        self._backlog_pos = 0
        self._values_key: tuple[int, int] | None = None
        self._values_piece = b"{}"
        self._values_count = 1
        self._forms: dict[str, _FormCache] = {SEEN: _FormCache(), CHOSEN: _FormCache()}
        self._kind_caches: dict[str, _KindCache] = {}
        self._gone: dict[str, list[str] | None] = {SEEN: None, CHOSEN: None}

    @property
    def program(self) -> object:
        return self._program

    @program.setter
    def program(self, program: object) -> None:
        """A reloaded story (F39): runs it lacks are looked up again at the next trim."""
        self._program = program
        self._gone = {SEEN: None, CHOSEN: None}

    # --- Warm-up and changes -------------------------------------------------------------

    def warm(self, store: PersistentStore, until: float | None = None,
             clock: Callable[[], float] | None = None) -> bool:
        """Build or bring the caches up to date for ``store``; True when nothing is left.
        With ``until`` and ``clock``, stop once ``clock() >= until`` (a slice) and go on at
        the next call; without them, do everything now."""
        self._attach(store)

        def out_of_time() -> bool:
            return until is not None and clock is not None and clock() >= until

        while self._warm_gen is not None:
            try:
                next(self._warm_gen)
            except StopIteration:
                self._warm_gen = None
                break
            if out_of_time():
                return False
        self._fill_backlog(store)
        backlog = self._backlog
        units = 0
        while self._backlog_pos < len(backlog):
            form, group, created = backlog[self._backlog_pos]
            if group is None:                            # a clear emptied this form
                self._forms[form] = _FormCache()
                self._backlog_pos += 1
                continue
            if self._touch_group(form, group, created, WARM_BLOCKS):
                self._backlog_pos += 1
                units += 1
            else:                                        # a long run: more blocks next time
                backlog[self._backlog_pos] = (form, group, False)
                units = WARM_CHECK
            if units >= WARM_CHECK:
                units = 0
                if out_of_time():
                    return False
        self._backlog = []
        self._backlog_pos = 0
        for fc in self._forms.values():
            while not fc.rebuild_some(WARM_SEGMENTS):
                if out_of_time():
                    return False
        for kind, entry in list(store.kind_items()):
            cache = self._kind_cache(kind, entry)
            while not self._extend_kind(cache, entry, WARM_NAMES):
                if out_of_time():
                    return False
        return True

    @property
    def is_warm(self) -> bool:
        """Built for a store, with no change waiting (as of the last ``warm``)."""
        return (self._store is not None and self._warm_gen is None
                and self._backlog_pos >= len(self._backlog))

    def detach(self) -> None:
        """Stop following the store (its journal is closed); the next use starts afresh."""
        if self._store is not None and self._journal is not None:
            self._store.close_journal(self._journal)
        self._store = None
        self._journal = None
        self._warm_gen = None

    def _attach(self, store: PersistentStore) -> None:
        if self._store is store:
            return
        self.detach()
        self._store = store
        self._forms = {SEEN: _FormCache(), CHOSEN: _FormCache()}
        self._kind_caches = {}
        self._values_key = None
        self._backlog = []
        self._backlog_pos = 0
        self._gone = {SEEN: None, CHOSEN: None}
        self._warm_gen = self._warm_steps(store)

    def _warm_steps(self, store: PersistentStore) -> Iterator[None]:
        """The first build, in units: the journal opens with the snapshot of each order, so
        every later change is in the journal."""
        self._journal = store.open_journal()
        snapshots = {form: list(store.records(form)) for form in (SEEN, CHOSEN)}
        yield
        for form in (SEEN, CHOSEN):
            units = 0
            for group in snapshots[form]:
                while not self._touch_group(form, group, False, WARM_BLOCKS):
                    yield
                units += 1
                if units >= WARM_CHECK:
                    units = 0
                    yield
            snapshots[form] = []

    def _fill_backlog(self, store: PersistentStore) -> None:
        journal = self._journal
        if journal is None or self._warm_gen is not None:
            return
        for form in (SEEN, CHOSEN):
            reset, touched = store.take_journal(journal, form)
            if reset:
                self._backlog.append((form, None, False))
            self._backlog.extend((form, group, created) for group, created in touched.items())

    def _touch_group(self, form: str, group: str, created: bool,
                     max_blocks: int | None) -> bool:
        """Bring one run's cache to the store's run; False if more blocks are left."""
        fc = self._forms[form]
        assert self._store is not None
        run = self._store.records(form).get(group)
        cache = fc.groups.get(group)
        if cache is not None and (run is None or created):
            fc.remove(group)
            cache = None
        if run is None:
            return True
        if cache is None:
            cache = _RunCache(run.epoch, _group_head(form, group))
            fc.add(group, cache)
        else:
            fc.account(cache, -1)
            if cache.epoch != run.epoch:
                cache.renew(run.epoch, _group_head(form, group))
        done = _grow_blocks(cache, run.order, max_blocks)
        if done:
            _finish_run(cache, run.order)
        else:
            cache.pieces, cache.size, cache.count = (), 0, 0
        fc.account(cache, +1)
        return done

    def _kind_cache(self, kind: str, entry: Any) -> _KindCache:
        cache = self._kind_caches.get(kind)
        if cache is None or cache.epoch != entry.epoch:
            cache = _KindCache(entry.epoch, json_string(kind) + b":[")
            self._kind_caches[kind] = cache
        return cache

    @staticmethod
    def _extend_kind(cache: _KindCache, entry: Any, limit: int | None) -> bool:
        names = entry.names
        have = len(cache.parts)
        if have < len(names):
            take = len(names) - have if limit is None else min(limit, len(names) - have)
            cache.parts.extend(map(json_string, islice(names, have, have + take)))
            cache.piece = None
            if len(cache.parts) < len(names):
                return False
        if cache.piece is None:
            cache.piece = cache.head + b",".join(cache.parts) + b"]"
            cache.count = count_structure(cache.piece)
        return True

    # --- Encoding ---------------------------------------------------------------------------

    def encode(self, store: PersistentStore) -> tuple[bytes, ...]:
        """The whole file as pieces; finishes any warm-up first (all at once)."""
        self.warm(store)
        values_piece, values_count = self._values(store)
        head = b'{"format":%d,"identity_scheme":%d,"values":' % (FORMAT, store.identity_scheme)
        fixed = (head, values_piece, _SEEN_OPEN, _CLOSE, _CHOSEN_OPEN, _CLOSE, _UNLOCKS_OPEN,
                 _END)
        fixed_size = sum(map(len, fixed))
        fixed_count = (sum(count_structure(p) for p in fixed if p is not values_piece)
                       + values_count)             # the values' count is cached with them
        kinds = _Section(self._kinds(store))
        forms = self._forms

        def over() -> bool:
            size = fixed_size + kinds.total_size + sum(f.total_size for f in forms.values())
            count = (fixed_count + kinds.total_count
                     + sum(f.total_count for f in forms.values()))
            return size > limits.FILE_MAX_BYTES or count > limits.PRESCAN_MAX

        if over():
            for form in (SEEN, CHOSEN):
                self._trim_runs(store, form, over)
            if over():
                self._trim_unlocks(store, kinds, over)

        out: list[bytes] = [head, values_piece, _SEEN_OPEN]
        forms[SEEN].write(out)
        out += (_CLOSE, _CHOSEN_OPEN)
        forms[CHOSEN].write(out)
        out += (_CLOSE, _UNLOCKS_OPEN)
        _join(out, kinds.items)
        out.append(_END)
        return tuple(out)

    def _values(self, store: PersistentStore) -> tuple[bytes, int]:
        key = (id(store), store.values_gen)
        if key != self._values_key:
            self._values_piece = (b"{" + b",".join(entry.name_json + b":" + entry.frag
                                                   for _, entry in store.value_entries())
                                  + b"}")
            self._values_count = count_structure(self._values_piece)
            self._values_key = key
        return self._values_piece, self._values_count

    def _kinds(self, store: PersistentStore) -> list[_Piece]:
        out = []
        fresh: dict[str, _KindCache] = {}
        for kind, entry in store.kind_items():
            cache = self._kind_cache(kind, entry)
            self._extend_kind(cache, entry, None)
            assert cache.piece is not None
            fresh[kind] = cache
            out.append(_Piece(kind, [cache.piece], len(cache.piece), cache.count))
        self._kind_caches = fresh
        return out

    # --- Trimming (W57) --------------------------------------------------------------------------

    def _gone_runs(self, form: str) -> list[str]:
        """Runs the program doesn't have, oldest first (looked up once per program)."""
        lookup = getattr(self._program, "label" if form == SEEN else "get", None)
        if lookup is None:
            return []
        fc = self._forms[form]
        gone = self._gone[form]
        if gone is None:
            gone = [group for group in fc.order() if lookup(group) is None]
        else:
            gone = [group for group in gone if group in fc.groups]
        self._gone[form] = gone
        return list(gone)

    def _trim_runs(self, store: PersistentStore, form: str, over: Callable[[], bool]) -> None:
        """Drop runs the program no longer has, then the oldest, until the file fits."""
        fc = self._forms[form]
        dropped = False
        for group in chain(self._gone_runs(form), fc.order()):
            if not over():
                break
            cache = fc.groups.get(group)
            if cache is None or not cache.pieces:
                continue
            store.drop_record(form, group)
            fc.remove(group)
            dropped = True
        if dropped:
            store.warn_full(form)

    def _trim_unlocks(self, store: PersistentStore, kinds: _Section,
                      over: Callable[[], bool]) -> None:
        """The last resort (very long unlock names): drop the oldest names, 1,000 at a time."""
        while over():
            name = next((p.name for p in kinds.items if store.drop_unlocks(p.name, 1_000)), None)
            if name is None:
                return
            kinds.reset(self._kinds(store))
            store.warn_full(UNLOCK, name)


def _grow_blocks(cache: _RunCache, order: list[str], max_blocks: int | None) -> bool:
    """Build the run's missing full blocks, at most ``max_blocks`` of them; True when none
    is missing. A block with a bad key stops the run from being written (``head`` None)."""
    size = limits.BLOCK_KEYS
    full = len(order) // size
    built = 0
    while cache.head is not None and len(cache.blocks) < full:
        if max_blocks is not None and built >= max_blocks:
            return False
        start = len(cache.blocks) * size
        block = _block(order[start:start + size])
        if block is None:
            cache.head = None
            break
        cache.blocks.append(block)
        cache.full_bytes += len(block)
        built += 1
    return True


def _finish_run(cache: _RunCache, order: list[str]) -> None:
    """The run's pieces from its blocks and tail, with their size and pre-scan count."""
    head = cache.head
    if head is None or not order:
        cache.pieces, cache.size, cache.count = (), 0, 0
        return
    size = limits.BLOCK_KEYS
    full = len(cache.blocks)
    tail = None
    if len(order) > full * size:
        if cache.tail_len != len(order):
            cache.tail = _block(order[full * size:])
            cache.tail_len = len(order)
        tail = cache.tail
        if tail is None:
            cache.pieces, cache.size, cache.count = (), 0, 0
            return
    if not full:
        assert tail is not None
        piece = head + tail + b'"'
        cache.pieces, cache.size = (piece,), len(piece)
    else:
        pieces = [head]
        for i, block in enumerate(cache.blocks):
            if i:
                pieces.append(b" ")
            pieces.append(block)
        if tail is not None:
            pieces += (b" ", tail)
        pieces.append(b'"')
        cache.pieces = tuple(pieces)
        cache.size = (len(head) + cache.full_bytes + (full - 1) + 1
                      + (1 + len(tail) if tail is not None else 0))
    cache.count = count_structure(head)


def _join(out: list[bytes], items: list[_Piece]) -> None:
    for i, item in enumerate(items):
        if i:
            out.append(b",")
        out.extend(item.pieces)


def _block(keys: list[str]) -> bytes | None:
    text = " ".join(keys)
    if _KEYS_RE.fullmatch(text) is None:
        return None
    return text.encode("ascii")


def encode_bytes(store: PersistentStore, program: object = None) -> bytes:
    """The whole file at once (tests, tools); leaves no journal open on the store."""
    encoder = PieceEncoder(program)
    try:
        return b"".join(encoder.encode(store))
    finally:
        encoder.detach()


__all__ = ["FORMAT", "KEY_RE", "MergeRules", "NOT_PERSISTENT", "NOT_REGULAR", "NOT_VALID_JSON",
           "OVER_CAP", "Outcome", "PieceEncoder", "ReadJob", "ReadOutcome", "UNREADABLE",
           "count_structure", "decode", "encode_bytes", "json_string", "known_names",
           "outcome_of_read", "parse", "prescan", "valid_label", "valid_menu_sid"]
