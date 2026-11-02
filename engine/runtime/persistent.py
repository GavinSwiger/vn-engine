"""The persistent data store: author values, seen lines, choice marks, and unlocks
(F12 ``04-technical.md`` §4, §5.1, §7.1–7.3).

Why this module exists: data that lasts across playthroughs (``persistent.x``, the lines a
player has seen, the choices they picked, unlocked gallery items) must live outside
``GameState`` (invariant 6) yet be changed by the runtime and author code. The store is
plain data with no I/O, no clock, and no thread, so the interpreter and namespace can use it
without importing ``persist``; ``engine/persist/`` reads and writes the file.

- **Values** are kept *live* (the object author code sees and may change in place) beside
  their *fragment*: the compact, ASCII JSON of the last checked value, which is what gets
  written. Caps: ``PERSIST_MAX_NAMES`` names and ``PERSIST_MAX_BYTES`` bytes for the whole
  values object (E183); names the program mentions push out names it doesn't (SEC-F12-04c).
- **Records** (seen lines per label, picked choices per menu) are append-only sets in
  first-seen order. At ``SEEN_MAX`` / ``CHOSEN_MAX`` the oldest run is dropped (W57).
- **Unlocks** are names per *kind*; features register kinds (at most ``UNLOCK_KINDS_MAX``)
  and may pass a recognizer so a kind full of junk from a shared file can't block a real
  unlock (SEC-F12-04b, d). A kind registered **revocable** (F19's ``"ending"`` and
  ``"route"``) also allows ``relock``, and a merge applies the value rule to it per name
  (``merge_kind``: the last copy to write a change to a name wins), from
  ``_unlock_changed``, this process's unlocks and relocks since its last write (F19 ``04``
  §7.5, ``07`` I-3).
- **Views** (F19 ``04`` §7.4, ``07`` I-1, I-4) are engine names such as
  ``persistent.endings``: ``get``/``peek`` return a fresh list from the owner's getter,
  whose result is cached per ``unlocks_gen``; ``set``/``delete`` raise
  ``PersistentViewName`` (E245). A stored value under a view's name goes to the view's
  ``migrate`` and is removed.

This module's ``register_kind`` (unlock kinds) is not ``engine.runtime.values.register_kind``
(kind words for messages).

Persist-side methods (``load_*``, ``merge_*``, ``records``, ``drop_record``, the record
journal, ``warn_full``, …) are for ``engine/persist`` only. The limits live in
``runtime/limits.py`` and are read here as module globals.

Author code reaches the store only through ``PersistentNamespace``, bound as ``persistent``
in the story namespace (F12 step 3a, ``04`` §5.1): attribute reads, sets, and deletes go to
``get``/``set``/``delete``; ``_clear`` is the one engine method; any other ``_`` name is
E182. While the launch evaluates defines (``begin_defines``), every access is E185. The
facade never shows a value in its ``repr`` (SEC-F12-09).
"""

import json
import keyword
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field

from engine.core.logsetup import get_logger
from engine.runtime.limits import (CHOSEN_MAX, PERSIST_MAX_BYTES, PERSIST_MAX_NAMES,
                                   PERSIST_NAME_MAX_CHARS, POSITION_MAX_CHARS, SEEN_MAX,
                                   UNLOCK_KINDS_MAX, UNLOCK_NAMES_MAX)
from engine.runtime.values import Unsaveable, Value, freeze, plain_copy
from engine.runtime.values import register_kind as register_value_kind
from engine.script.identity import IDENTITY_SCHEME
from engine.script.words import ROLE_LABEL, check_name

# --- Limits (04 §13; the caps come from runtime/limits.py and are read as this module's
# globals at call time, so tests can patch them here) ----------------------------------------
KIND_MAX_CHARS = 64
UNLOCK_NAME_MAX_CHARS = 255
SMALL_RUN = 8                        # runs up to this many keys keep no set
LABEL_MAX_CHARS = 255                # a label in a seen record (AC-F12-24)

# --- Clear flags since the last sync (04 §7.6) ----------------------------------------------
VALUES = 1
PROGRESS = 2
RESET = 4

SEEN = "seen"
CHOSEN = "chosen"
UNLOCK = "unlock"
DEFAULT_DISPLAY = "persistent.json"  # until app/persistence sets the display path
KEY_RE = re.compile(r"[0-9a-f]{12}(?:~[1-9][0-9]{0,6})?", re.ASCII)   # ADR-0006 keys


class _MissingType:
    """The type of ``Missing``: what ``peek`` returns for a name with no value."""

    _instance: "_MissingType | None" = None

    def __new__(cls) -> "_MissingType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "Missing"

    def __bool__(self) -> bool:
        return False


Missing = _MissingType()


# --- Errors (E180–E183, E185; mapped to messages by the runtime, F12 step 3) ---------------

class PersistentError(Exception):
    """A refused persistent access. ``name`` is the author's name; the text never holds a
    value (SEC-F12-09)."""

    def __init__(self, name: str, text: str = "persistent data refused this access") -> None:
        super().__init__(text)
        self.name = name


class PersistentNoValue(PersistentError, AttributeError):
    """E180: no stored value and no default (``hasattr`` gives False). ``candidates``
    gives the names a did-you-mean may offer (defaults and stored names), computed only
    when the message is built."""

    def __init__(self, name: str,
                 candidates: Callable[[], Iterable[str]] = lambda: ()) -> None:
        super().__init__(name, "this persistent name has no value yet")
        self.candidates = candidates


class PersistentUnsaveable(PersistentError):
    """E181: the value can't be saved; ``error`` is F03's ``Unsaveable``."""

    def __init__(self, name: str, error: Unsaveable) -> None:
        super().__init__(name, "this persistent value can't be saved")
        self.error = error


class PersistentEngineName(PersistentError):
    """E182. ``form``: ``set`` (a ``_`` name set or deleted), ``read`` (a ``_`` name read),
    ``progress`` (``_clear(progress=…)`` not exactly a bool; ``value`` holds it), or ``name``
    (``setattr`` with a name that isn't a valid persistent name, 07 I-4 O1)."""

    def __init__(self, name: str, form: str, value: object = None) -> None:
        super().__init__(name, "this persistent name belongs to the engine or isn't a name")
        self.form = form
        self.value = value


class PersistentTooBig(PersistentError):
    """E183. ``form`` ``bytes``: ``size`` is the values object's size in bytes the change
    would give; ``names``: ``size`` is the name count it would give. ``limit`` is the cap
    it passes."""

    def __init__(self, name: str, form: str, size: int, limit: int = 0) -> None:
        super().__init__(name, "persistent data would be over its limit")
        self.form = form
        self.size = size
        self.limit = limit


class PersistentInDefine(PersistentError):
    """E185: persistent data used while defines run."""

    def __init__(self, name: str) -> None:
        super().__init__(name, "persistent data can't be used by a define")


class PersistentViewName(PersistentError):
    """E245 (F19): a set (``form`` ``set``) or delete (``delete``) of an engine view such as
    ``persistent.endings``, which only the engine changes."""

    def __init__(self, name: str, form: str) -> None:
        super().__init__(name, "this persistent name is kept by the engine")
        self.form = form


# --- Small helpers ---------------------------------------------------------------------------

def compact_json(value: object) -> bytes:
    """The fragment of a checked value: compact, ASCII, no NaN or Infinity."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii")


def _refuse(obj: object) -> None:
    raise TypeError("not a plain value")


def _live_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
                      default=_refuse).encode("ascii")


def valid_name(name: object) -> bool:
    """A name an author could store: an identifier that isn't a keyword, NFKC-normal, with
    no leading ``_``, and at most ``PERSIST_NAME_MAX_CHARS`` characters (04 §8)."""
    return (type(name) is str
            and 0 < len(name) <= PERSIST_NAME_MAX_CHARS
            and not name.startswith("_")
            and name.isidentifier()
            and not keyword.iskeyword(name)
            and (name.isascii() or unicodedata.is_normalized("NFKC", name)))


def valid_label(label: object) -> bool:
    """F02's label-name rules (an identifier, NFKC-normal, not a statement word, keyword,
    engine name, or ``_`` name), at most ``LABEL_MAX_CHARS`` characters. Here rather than in
    ``persist`` because only ``runtime`` may import ``engine.script`` (AC-F02-66)."""
    return (type(label) is str
            and 0 < len(label) <= LABEL_MAX_CHARS
            and label.isidentifier()
            and (label.isascii() or unicodedata.is_normalized("NFKC", label))
            and check_name(label, ROLE_LABEL) is None)


def valid_menu_sid(sid: object) -> bool:
    """A label, ``/``, and an ADR-0006 key, at most ``POSITION_MAX_CHARS`` characters."""
    if type(sid) is not str or len(sid) > POSITION_MAX_CHARS:
        return False
    label, sep, key = sid.rpartition("/")
    return bool(sep) and KEY_RE.fullmatch(key) is not None and valid_label(label)


def valid_kind(kind: object) -> bool:
    return type(kind) is str and 0 < len(kind) <= KIND_MAX_CHARS


def valid_unlock_name(name: object) -> bool:
    return type(name) is str and 0 < len(name) <= UNLOCK_NAME_MAX_CHARS


def dropped_text(file: str, count: int) -> str:
    """W54 (design §5.4; the singular form is drafted here, G13)."""
    if count == 1:
        return (f"persistent data in {file} had 1 entry that couldn't be used (a bad name or "
                "value). It was dropped and the rest was kept.")
    return (f"persistent data in {file} had {count:,} entries that couldn't be used (bad "
            "names or values). They were dropped and the rest was kept.")


def scheme_text(file: str) -> str:
    """W55 (07 I-4: "a different engine version", since wrong types give it too)."""
    return (f"seen-line records in {file} come from a different engine version, so every "
            "line counts as unread once more. Your other persistent data is kept.")


def full_text(form: str, kind: str | None = None) -> str:
    """W57. The seen form is design §5.4's; the choice and unlock forms are drafts (G3)."""
    if form == SEEN:
        return (f"the seen-line record is full ({SEEN_MAX:,} lines), so the oldest lines from "
                "scenes no longer in the story were dropped.")
    if form == CHOSEN:
        return (f"the choice record is full ({CHOSEN_MAX:,} choices), so the oldest choices "
                "from menus no longer in the story were dropped.")
    quoted = json.dumps(kind if kind is not None else "", ensure_ascii=True)
    return (f"unlock record {quoted} is full ({UNLOCK_NAMES_MAX:,}), so new unlocks of this "
            "kind aren't recorded.")


# --- Data ------------------------------------------------------------------------------------

@dataclass(slots=True)
class _Entry:
    live: Value              # what author code sees and may change in place
    frag: bytes              # compact ASCII JSON of the last checked value (written)
    name_json: bytes         # the name as a JSON string
    watched: bool = False    # a list/dict author code has read

    @property
    def size(self) -> int:
        """Bytes this entry adds to the values object, without its separating comma."""
        return len(self.name_json) + 1 + len(self.frag)


@dataclass(slots=True)
class _KeyRun:
    """One label's seen keys, or one menu's picked choice keys. Small runs search
    ``order``. A run past ``SMALL_RUN`` keys gets its set (``members``) at its first
    lookup, so a launch read holds only the keys of each run, and sets exist only for the
    runs the session plays (marks and ``is_seen``): at the 1,000,000-sid cap the sets would
    cost more memory than the keys' order (AC-F12-46), and a file of many tiny labels stays
    within SEC-F12-02's memory bound. ``members`` is None or equals ``set(order)``."""

    order: list[str]         # first-seen, append-only within an epoch
    epoch: int               # store-unique; renewed when the run shrinks
    members: set[str] | None = None

    def __contains__(self, key: str) -> bool:
        members = self.members
        if members is None:
            if len(self.order) <= SMALL_RUN:
                return key in self.order
            members = self.members = set(self.order)
        return key in members

    def __len__(self) -> int:
        return len(self.order)

    def lookup(self) -> "set[str] | list[str]":
        """The keys for one batch of membership tests that shouldn't leave a set behind
        (the read's union, eviction): ``members`` if built, else ``order`` or a
        throwaway set."""
        if self.members is not None:
            return self.members
        return self.order if len(self.order) <= SMALL_RUN else set(self.order)

    def extend(self, keys: list[str]) -> None:
        """Append keys known to be new."""
        self.order.extend(keys)
        if self.members is not None:
            self.members.update(keys)


@dataclass(slots=True)
class _Kind:
    names: dict[str, None]                  # unlock order
    registered: bool                        # False: read from the file, no owner yet
    known: Callable[[str], bool] | None     # the owner's recognizer (SEC-F12-04d)
    epoch: int                              # renewed when names are removed
    revocable: bool = False                 # F19: relock and the per-name merge


@dataclass(slots=True)
class _View:
    """An engine view (F19 ``04`` §7.4): the owner's getter and migration hook, and the
    getter's last list, kept for one ``unlocks_gen`` (``07`` I-4)."""

    getter: Callable[[], list[str]]
    migrate: Callable[[Value], None] | None
    gen: int = -1
    cached: tuple[str, ...] = ()


@dataclass(slots=True)
class _Records:
    runs: dict[str, _KeyRun] = field(default_factory=dict)
    total: int = 0


@dataclass(slots=True, eq=False)
class RecordJournal:
    """Which seen and choice runs changed since the reader last took them (F12 step 5: the
    encoder's cache, so a write costs only what changed). ``touched[form]`` maps a group to
    True if its run was created (it moved to the end of the order) since the last take;
    ``reset`` holds the forms a clear emptied. Opened and read by ``engine/persist`` only."""

    touched: dict[str, dict[str, bool]] = field(
        default_factory=lambda: {SEEN: {}, CHOSEN: {}})
    reset: set[str] = field(default_factory=set)


# --- The store -------------------------------------------------------------------------------

class PersistentStore:
    """All persistent data of one session (main thread only). ``version`` goes up by one per
    change; the writer compares it with the last written version."""

    def __init__(self, *, identity_scheme: int, log: logging.Logger | None = None) -> None:
        self.identity_scheme = identity_scheme
        self.version = 0
        self.values_gen = 0                  # bumped on every values change (encoder cache)
        self.unlocks_gen = 0                 # bumped on every change to unlock names (views)
        self.log = log if log is not None else get_logger("persist")
        self.display = DEFAULT_DISPLAY       # <file> in W54
        self._values: dict[str, _Entry] = {}
        self._launch: dict[str, Value] = {}
        self._known: frozenset[str] = frozenset()
        self._sum = 0                        # Σ entry sizes (commas and braces added on use)
        self._changed: dict[str, int] = {}
        self._cleared = 0
        self._cleared_at = 0
        self._records: dict[str, _Records] = {SEEN: _Records(), CHOSEN: _Records()}
        self._kinds: dict[str, _Kind] = {}
        self._new_unlocks: list[tuple[str, str]] = []
        self._in_defines = False
        self._epoch = 0
        self._full_warned: set[tuple[str, str | None]] = set()
        self._journals: list[RecordJournal] = []
        self._unlock_changed: dict[tuple[str, str], int] = {}   # revocable: version per name
        self._views: dict[str, _View] = {}
        self._reset_count = 0                # F20 (07 A9): F16's Delete progress resets

    @property
    def reset_count(self) -> int:
        """How many times ``reset`` ran (F16's Delete progress), read-only. F20's recorder and
        ``FlowService`` compare it to notice a reset and drop every node state (F20 ``04``
        §7.5 "Deletes")."""
        return self._reset_count

    @classmethod
    def with_data(cls, *, values: Mapping[str, object] | Iterable[tuple[str, object]] = (),
                  seen: Iterable[str] = (), chosen: Iterable[tuple[str, str]] = (),
                  unlocks: Mapping[str, Iterable[str]] | Iterable[tuple[str, str]] = (),
                  identity_scheme: int = IDENTITY_SCHEME,
                  log: logging.Logger | None = None) -> "PersistentStore":
        """A store already holding this data, as if read from a file (tests, harnesses).
        ``seen`` holds sids, ``chosen`` ``(menu sid, choice key)`` pairs, ``unlocks`` a kind →
        names mapping or ``(kind, name)`` pairs; their kinds are registered."""
        store = cls(identity_scheme=identity_scheme, log=log)
        for name, value in (values.items() if isinstance(values, Mapping) else values):
            store.set(name, value)
        for sid in seen:
            store.mark_seen(sid)
        for menu, choice in chosen:
            store.mark_chosen(menu, choice)
        pairs = ([(k, n) for k, names in unlocks.items() for n in names]
                 if isinstance(unlocks, Mapping) else unlocks)
        for kind, name in pairs:
            entry = store._kinds.get(kind)
            if entry is None or not entry.registered:
                store.register_kind(kind)
            store.unlock(kind, name)
        store._new_unlocks.clear()
        store._changed.clear()
        store._unlock_changed.clear()
        return store

    # --- Author values (§7.1) ------------------------------------------------------------

    @property
    def values_bytes(self) -> int:
        """The size of the values object as written: ``{"a":1,"b":2}``."""
        return 2 + self._sum + max(0, len(self._values) - 1)

    @property
    def value_count(self) -> int:
        return len(self._values)

    def has_value(self, name: str) -> bool:
        return name in self._values

    @property
    def known_names(self) -> frozenset[str]:
        return self._known

    def get(self, name: str) -> Value:
        """The live value (a list or dict becomes watched); a launch value is stored first;
        else ``PersistentNoValue``. A view gives a fresh list (after the access check, so a
        define still gets E185)."""
        self._check_access(name)
        if name in self._views:
            return self._view_list(name)
        entry = self._values.get(name)
        if entry is None:
            if name not in self._launch:
                raise PersistentNoValue(name, self.names)
            launch = self._launch[name]
            self._put(name, plain_copy(launch), compact_json(launch), changed=False)
            entry = self._values[name]
        if type(entry.live) is list or type(entry.live) is dict:
            entry.watched = True
        return entry.live

    def set(self, name: str, value: object) -> None:
        """Store a checked copy of ``value``: E181 if it can't be saved, E182 for a ``_`` or
        invalid name, E183 over a cap (nothing changes then), E245 for a view."""
        self._check_access(name)
        if name in self._views:
            raise PersistentViewName(name, "set")
        self._check_name(name)
        try:
            frozen = freeze(value)
        except Unsaveable as error:
            raise PersistentUnsaveable(name, error) from None
        self._put(name, frozen, compact_json(frozen), changed=True)

    def delete(self, name: str) -> None:
        """Remove ``name``; a name with a launch value gets a copy of it back; E180 if there
        is neither; E245 for a view."""
        self._check_access(name)
        if name in self._views:
            raise PersistentViewName(name, "delete")
        self._check_name(name)
        if name in self._launch:
            launch = self._launch[name]
            self._put(name, plain_copy(launch), compact_json(launch), changed=True)
        elif name in self._values:
            self._remove(name)
            self._bump_values()
            self._changed[name] = self.version
        else:
            raise PersistentNoValue(name, self.names)

    def clear(self, *, progress: bool = False) -> None:
        """``persistent._clear()``: every value goes back to its launch value (names without
        one are removed). ``progress=True`` also empties seen lines and choice marks.
        Unlocks stay (07 I-4)."""
        if type(progress) is not bool:
            raise PersistentEngineName("_clear", "progress", progress)
        self._check_access("_clear")
        self._values.clear()
        self._sum = 0
        for name, launch in self._launch.items():
            try:
                self._put(name, plain_copy(launch), compact_json(launch), changed=False)
            except PersistentTooBig:
                pass                              # stays a launch value, stored on read
        self._cleared |= VALUES
        if progress:
            for records in self._records.values():
                records.runs.clear()
                records.total = 0
            for journal in self._journals:
                for touched in journal.touched.values():
                    touched.clear()
                journal.reset.update((SEEN, CHOSEN))
            self._cleared |= PROGRESS
        self._bump_values()
        self._cleared_at = self.version

    def reset(self) -> None:
        """F16: launch values only, no records, no unlocks. Registered kinds stay
        registered (empty); kinds no feature registered are removed."""
        self._check_access("_clear")
        self.clear(progress=True)
        for kind in [k for k, entry in self._kinds.items() if not entry.registered]:
            del self._kinds[kind]
        for entry in self._kinds.values():
            entry.names.clear()
            entry.epoch = self._next_epoch()
        self._new_unlocks.clear()
        self._unlock_changed.clear()
        self._cleared |= RESET
        self._reset_count += 1
        self.version += 1
        self.unlocks_gen += 1
        self._cleared_at = self.version

    def names(self) -> frozenset[str]:
        """Stored names, names with a launch value, and views (for did-you-mean and
        ``dir``)."""
        return frozenset(self._values).union(self._launch, self._views)

    def peek(self, name: str) -> "Value | _MissingType":
        """A copy of the value for engine readers (F32), or ``Missing``. Never E180,
        never a change. **The result is untrusted**: it may come from a file players edit
        and share, so callers check its exact type and range and fall back on anything
        else, and never use it as a path, code, or a file name (SEC-F12-10). A view gives
        its fresh list."""
        if type(name) is str and name in self._views:
            return self._view_list(name)
        entry = self._values.get(name) if type(name) is str else None
        if entry is None:
            launch = self._launch.get(name) if type(name) is str else None
            return Missing if launch is None and name not in self._launch else plain_copy(launch)
        try:
            return freeze(entry.live)
        except Unsaveable:
            return json.loads(entry.frag)

    def set_known(self, names: Iterable[str]) -> None:
        """The names the program mentions (LaunchJob, before phase 2b; SEC-F12-04)."""
        self._known = frozenset(names)

    def set_default(self, name: str, value: object) -> None:
        """Phase 2b: remember the launch value; store it only if ``name`` has no value. A
        name with a default always gets room (unmentioned names give way)."""
        if not valid_name(name):
            raise ValueError("not a persistent name")
        try:
            frozen = freeze(value)
        except Unsaveable as error:
            raise PersistentUnsaveable(name, error) from None
        self._launch[name] = frozen
        if name not in self._values:
            self._put(name, plain_copy(frozen), compact_json(frozen), changed=False)

    def set_builtin_default(self, name: str, value: object) -> None:
        """An engine launch value (F32: ``playthrough`` = 0), set after the author's defaults:
        ``set_default`` only when no author default gave ``name`` one, so the author's wins
        and never meets E184. Stored and written like any default (07 I-11)."""
        if name not in self._launch:
            self.set_default(name, value)

    def check_in_place(self) -> None:
        """§7.2: notice changes made in place to watched values since their last check.
        E181 / E183 as for ``set``; the last good fragment stays on failure."""
        for name, entry in list(self._values.items()):
            if not entry.watched or self._values.get(name) is not entry:
                continue
            try:
                encoded: bytes | None = _live_json(entry.live)
            except (TypeError, ValueError, RecursionError):
                encoded = None
            if encoded == entry.frag:
                continue
            try:
                frozen = freeze(entry.live)
            except Unsaveable as error:
                raise PersistentUnsaveable(name, error) from None
            frag = compact_json(frozen)
            size = len(entry.name_json) + 1 + len(frag)
            self._make_room(name, size)
            self._sum += len(frag) - len(entry.frag)
            entry.frag = frag
            self._bump_values()
            self._changed[name] = self.version

    def begin_defines(self) -> None:
        self._in_defines = True

    def end_defines(self) -> None:
        self._in_defines = False

    # --- Records (§7.3) ------------------------------------------------------------------

    def mark_seen(self, sid: str) -> None:
        label, sep, key = sid.rpartition("/")
        if not sep or not label or not key:
            raise ValueError("not a statement identity")
        self._mark(SEEN, label, key)

    def is_seen(self, sid: str) -> bool:
        if type(sid) is not str:
            return False
        label, _, key = sid.rpartition("/")
        run = self._records[SEEN].runs.get(label)
        return run is not None and key in run

    def mark_chosen(self, menu: str, choice: str) -> None:
        if type(menu) is not str or type(choice) is not str or not menu or not choice:
            raise ValueError("not a menu identity and choice key")
        self._mark(CHOSEN, menu, choice)

    def was_chosen(self, menu: str, choice: str) -> bool:
        run = self._records[CHOSEN].runs.get(menu) if type(menu) is str else None
        return run is not None and choice in run

    # --- Unlocks (§7.3, SEC-F12-04b/d) -----------------------------------------------------

    def register_kind(self, kind: str, *,
                      known: Callable[[str], bool] | None = None,
                      revocable: bool = False) -> None:
        """Register an unlock kind (F19, F21, F34, F35, F37). ``known`` recognizes the
        owner's real names, so in a full kind they push out names it doesn't recognize.
        ``revocable`` (F19) allows ``relock`` and the per-name merge (``merge_kind``).
        ``ValueError`` for a bad kind or a registration past ``UNLOCK_KINDS_MAX``. A kind
        read from the file is adopted; kinds nobody registered give way (W54). Registering
        again replaces ``known`` and ``revocable`` (F39)."""
        if not valid_kind(kind):
            raise ValueError("an unlock kind is 1 to 64 characters of text")
        entry = self._kinds.get(kind)
        registered = sum(1 for k in self._kinds.values() if k.registered)
        if entry is not None:
            if not entry.registered:
                if registered >= UNLOCK_KINDS_MAX:
                    raise ValueError(f"more than {UNLOCK_KINDS_MAX} unlock kinds")
                entry.registered = True
            entry.known = known
            entry.revocable = revocable
            return
        if registered >= UNLOCK_KINDS_MAX:
            raise ValueError(f"more than {UNLOCK_KINDS_MAX} unlock kinds")
        if len(self._kinds) >= UNLOCK_KINDS_MAX:
            oldest = next(k for k, e in self._kinds.items() if not e.registered)
            del self._kinds[oldest]
            self.version += 1
            self.unlocks_gen += 1
            self.warn_dropped(1)
        self._kinds[kind] = _Kind({}, True, known, self._next_epoch(), revocable)

    def is_revocable(self, kind: str) -> bool:
        """``kind`` is registered and revocable (the merge's choice, F19 ``04`` §7.5)."""
        entry = self._kinds.get(kind) if type(kind) is str else None
        return entry is not None and entry.registered and entry.revocable

    def unlock(self, kind: str, name: str, *, quiet: bool = False,
               migrating: bool = False) -> bool:
        """Record ``name`` under ``kind``; True if it is new. ``ValueError`` for a kind
        nobody registered or a name that isn't 1–255 characters of text. A revocable kind
        also notes the change for the merge (``_unlock_changed``). ``quiet``: not offered by
        ``take_new_unlocks`` (F19's migration; F20's re-arrival reorder and chapter
        tombstones, F20 ``07`` I-8). ``migrating`` (F19's migration only): a revocable name
        this process unlocked or relocked since its last write is left as it is, so an older
        copy's value merged in can't undo a ``lock`` (F19 ``07`` I-3). F20 (its ``07`` A9,
        I-8) split this from ``quiet``: a reorder is ``relock`` then a quiet ``unlock`` of the
        same name, which the migration rule would refuse."""
        entry = self._kinds.get(kind) if type(kind) is str else None
        if entry is None or not entry.registered:
            raise ValueError("unlock kind not registered")
        if not valid_unlock_name(name):
            raise ValueError("an unlock name is 1 to 255 characters of text")
        if name in entry.names:
            return False
        if migrating and entry.revocable and (kind, name) in self._unlock_changed:
            return False
        if len(entry.names) >= UNLOCK_NAMES_MAX:
            stranger = None
            if entry.known is not None and entry.known(name):
                stranger = next((n for n in entry.names if not entry.known(n)), None)
            if stranger is None:
                self.warn_full(UNLOCK, kind)
                return False
            del entry.names[stranger]
            entry.epoch = self._next_epoch()
            self.warn_dropped(1)
        entry.names[name] = None
        if not quiet:
            self._new_unlocks.append((kind, name))
        self.version += 1
        self.unlocks_gen += 1
        if entry.revocable:
            self._unlock_changed[(kind, name)] = self.version
        return True

    def relock(self, kind: str, name: str) -> bool:
        """Remove ``name`` from a revocable kind (F19's ``lock``); True if it was there.
        ``ValueError`` for a kind nobody registered or one that isn't revocable (achievements
        stay permanent, F12 ``07`` I-4); nothing changes then (TR-F19-03)."""
        entry = self._kinds.get(kind) if type(kind) is str else None
        if entry is None or not entry.registered or not entry.revocable:
            raise ValueError("relock needs a registered revocable unlock kind")
        if type(name) is not str or name not in entry.names:
            return False
        del entry.names[name]
        entry.epoch = self._next_epoch()      # the encoder's kind cache only appends
        self.version += 1
        self.unlocks_gen += 1
        self._unlock_changed[(kind, name)] = self.version
        return True

    def is_unlocked(self, kind: str, name: str) -> bool:
        entry = self._kinds.get(kind) if type(kind) is str else None
        return entry is not None and name in entry.names

    def last_unlocked(self, kind: str) -> str | None:
        """The newest name of ``kind`` (None when empty or unknown), in O(1): F20's re-arrival
        reorders a node's key only when it isn't already last (F20 ``07`` I-8)."""
        entry = self._kinds.get(kind) if type(kind) is str else None
        return next(reversed(entry.names), None) if entry is not None else None

    def unlocked(self, kind: str) -> tuple[str, ...]:
        """Names in unlock order: lookup keys into the owner's registry, never paths or
        display text (SEC-F12-10)."""
        entry = self._kinds.get(kind) if type(kind) is str else None
        return () if entry is None else tuple(entry.names)

    def take_new_unlocks(self) -> tuple[tuple[str, str], ...]:
        """Each ``(kind, name)`` unlocked since the last call, once."""
        new = tuple(self._new_unlocks)
        self._new_unlocks.clear()
        return new

    # --- Views (F19 ``04`` §7.4; ``07`` I-1, I-4) ---------------------------------------------

    def register_view(self, name: str, getter: Callable[[], list[str]], *,
                      migrate: Callable[[Value], None] | None = None) -> None:
        """An engine view ``persistent.<name>``: ``get``/``peek`` return a fresh list of what
        ``getter()`` gave (called again only after ``unlocks_gen`` changes); ``set`` and
        ``delete`` raise ``PersistentViewName``; ``names()`` includes it. A stored value
        under ``name`` (an older game's author value) goes to ``migrate`` and is removed, so
        the next write drops it. Registering a name again replaces the getter and
        ``migrate`` (``07`` I-1; F39). ``ValueError`` for a name that isn't a persistent
        name (a ``_`` name)."""
        if not valid_name(name):
            raise ValueError("a view is named like a persistent value, without a leading _")
        self._views[name] = _View(getter, migrate)
        self._launch.pop(name, None)
        entry = self._values.get(name)
        if entry is not None:
            if migrate is not None:
                migrate(entry.live)
            self._remove(name)
            self._changed.pop(name, None)
            self._bump_values()

    def is_view(self, name: str) -> bool:
        return name in self._views

    def _view_list(self, name: str) -> list[str]:
        view = self._views[name]
        if view.gen != self.unlocks_gen:
            view.cached = tuple(view.getter())
            view.gen = self.unlocks_gen
        return list(view.cached)

    def _migrate_view(self, name: str, value: Value) -> None:
        migrate = self._views[name].migrate
        if migrate is not None:
            migrate(value)

    # --- Sync (persist only) ---------------------------------------------------------------

    def mark_synced(self, version: int) -> None:
        """The file now holds this store at ``version``: forget changes up to it."""
        self._changed = {n: v for n, v in self._changed.items() if v > version}
        if self._unlock_changed:
            self._unlock_changed = {k: v for k, v in self._unlock_changed.items()
                                    if v > version}
        if self._cleared_at <= version:
            self._cleared = 0

    @property
    def changed(self) -> Mapping[str, int]:
        return self._changed

    @property
    def cleared(self) -> int:
        return self._cleared

    # --- Persist-side access (fileformat, sync) ---------------------------------------------

    def value_entries(self) -> Iterator[tuple[str, _Entry]]:
        return iter(self._values.items())

    def values_snapshot(self) -> dict[str, Value]:
        """name → a copy of each value's last checked form (tests, comparisons)."""
        return {name: json.loads(entry.frag) for name, entry in self._values.items()}

    def load_value(self, name: str, value: Value, frag: bytes) -> bool:
        """Store a value read from the file (already checked); False if it doesn't fit the
        caps. No give-way: the reader offers known names first. A view's name goes to its
        ``migrate`` instead and isn't stored (True)."""
        if name in self._views:
            self._migrate_view(name, value)
            return True
        try:
            self._put(name, value, frag, changed=False, give_way=False)
        except PersistentTooBig:
            return False
        return True

    def value_frag(self, name: str) -> bytes | None:
        """The stored fragment of ``name`` (None if it has no stored value)."""
        entry = self._values.get(name)
        return None if entry is None else entry.frag

    def merge_value(self, name: str, value: Value, frag: bytes) -> bool:
        """Store a value another copy wrote (already checked; 04 §7.6). Not a change of this
        process: ``changed`` is untouched. Names the program mentions may push out names it
        doesn't (W54), as for ``set``. False if it doesn't fit (nothing changes then). A
        view's name (an older engine copy wrote it) goes to its ``migrate`` instead and
        isn't stored (True)."""
        if name in self._views:
            self._migrate_view(name, value)
            return True
        try:
            self._put(name, value, frag, changed=False)
        except PersistentTooBig:
            return False
        return True

    def merge_remove(self, name: str) -> None:
        """Remove a stored value another copy deleted (04 §7.6). A launch value comes back
        on the next read, as after a restart."""
        if name in self._values:
            self._remove(name)
            self._bump_values()

    def open_journal(self) -> RecordJournal:
        """Start recording which runs change (one journal per reader)."""
        journal = RecordJournal()
        self._journals.append(journal)
        return journal

    def close_journal(self, journal: RecordJournal) -> None:
        self._journals = [j for j in self._journals if j is not journal]

    def take_journal(self, journal: RecordJournal, form: str) -> tuple[bool, dict[str, bool]]:
        """``(reset, touched)`` for ``form`` since the last take, and start afresh."""
        touched = journal.touched[form]
        journal.touched[form] = {}
        reset = form in journal.reset
        journal.reset.discard(form)
        return reset, touched

    def records(self, form: str) -> Mapping[str, _KeyRun]:
        return self._records[form].runs

    def record_total(self, form: str) -> int:
        return self._records[form].total

    def record_cap(self, form: str) -> int:
        return SEEN_MAX if form == SEEN else CHOSEN_MAX

    def load_keys(self, form: str, group: str, keys: Iterable[str]) -> int:
        """Unite ``keys`` into ``group``'s run in order. Over the cap, the oldest other runs
        are dropped first, then the excess is cut (W57). Returns the keys added."""
        records = self._records[form]
        run = records.runs.get(group)
        if run is None:
            new = list(dict.fromkeys(keys))
        else:
            have = run.lookup()
            new = [k for k in dict.fromkeys(keys) if k not in have]
            del have
        if not new:
            return 0
        cap = self.record_cap(form)
        if records.total + len(new) > cap:
            for other in [g for g in records.runs if g != group]:
                if records.total + len(new) <= cap:
                    break
                self.drop_record(form, other)
            if records.total + len(new) > cap:
                new = new[:max(0, cap - records.total)]
            self.warn_full(form)
            if not new:
                return 0
        if run is None:
            run = records.runs[group] = _KeyRun([], self._next_epoch())
            if self._journals:
                self._touch(form, group, True)
        elif self._journals:
            self._touch(form, group)
        run.extend(new)
        records.total += len(new)
        self.version += 1
        return len(new)

    def remove_keys(self, form: str, group: str, keys: Iterable[str]) -> int:
        """Remove some keys from one run (eviction); returns how many."""
        records = self._records[form]
        run = records.runs.get(group)
        if run is None:
            return 0
        have = run.lookup()
        gone = {k for k in keys if k in have}
        del have
        if not gone:
            return 0
        if len(gone) == len(run):
            self.drop_record(form, group)
            return len(gone)
        run.order = [k for k in run.order if k not in gone]
        run.members = None                        # rebuilt at the next lookup
        run.epoch = self._next_epoch()
        if self._journals:
            self._touch(form, group)
        records.total -= len(gone)
        self.version += 1
        return len(gone)

    def drop_record(self, form: str, group: str) -> int:
        """Remove one label's (menu's) whole run; returns its key count."""
        records = self._records[form]
        run = records.runs.pop(group, None)
        if run is None:
            return 0
        if self._journals:
            self._touch(form, group)
        records.total -= len(run.order)
        self.version += 1
        return len(run.order)

    def kind_items(self) -> Iterator[tuple[str, _Kind]]:
        return iter(self._kinds.items())

    def load_kind(self, kind: str, names: list[str]) -> int:
        """Unite checked, de-duplicated ``names`` into ``kind`` (read from a file). Returns
        the number dropped: -1 if the kind itself doesn't fit, else the names past the
        per-kind cap."""
        entry = self._kinds.get(kind)
        if entry is None:
            if len(self._kinds) >= UNLOCK_KINDS_MAX:
                return -1
            entry = self._kinds[kind] = _Kind({}, False, None, self._next_epoch())
        dropped = self._add_names(entry, names, kind, ())
        self.version += 1
        return dropped

    def merge_kind(self, kind: str, names: list[str]) -> int:
        """Merge a registered revocable kind from another copy's file (persist only; F19
        ``04`` §7.5): checked, de-duplicated ``names`` in file order. Per name, the file
        wins unless this process unlocked or relocked it since its last write: a name we
        hold that the file lacks is removed, and a name the file has that we lack is added
        (``load_kind``'s cap rule). Returns the names past the per-kind cap. ``ValueError``
        for a kind that isn't registered and revocable."""
        entry = self._kinds.get(kind)
        if entry is None or not entry.registered or not entry.revocable:
            raise ValueError("merge_kind needs a registered revocable unlock kind")
        changed = self._unlock_changed
        mine = {n for k, n in changed if k == kind} if changed else ()
        disk = set(names)
        gone = [n for n in entry.names if n not in disk and n not in mine]
        for name in gone:
            del entry.names[name]
        if gone:
            entry.epoch = self._next_epoch()      # the encoder's kind cache only appends
            self.unlocks_gen += 1
        before = len(entry.names)
        dropped = self._add_names(entry, names, kind, changed)
        if gone or len(entry.names) != before:
            self.version += 1
        return dropped

    def drop_unlocks(self, kind: str, count: int) -> int:
        """Remove the ``count`` oldest names of ``kind`` (the encoder's last resort)."""
        entry = self._kinds.get(kind)
        if entry is None:
            return 0
        gone = list(entry.names)[:count]
        for name in gone:
            del entry.names[name]
        if gone:
            entry.epoch = self._next_epoch()
            self.version += 1
            self.unlocks_gen += 1
        return len(gone)

    def _add_names(self, entry: _Kind, names: list[str], kind: str,
                   skip: Mapping[tuple[str, str], int]) -> int:
        """Append the ``names`` ``entry`` lacks, except ``(kind, name)`` pairs in ``skip``;
        past ``UNLOCK_NAMES_MAX`` they are counted, not added. Bumps ``unlocks_gen`` if any
        is added."""
        dropped = 0
        added = False
        for name in names:
            if name in entry.names or (skip and (kind, name) in skip):
                continue
            if len(entry.names) >= UNLOCK_NAMES_MAX:
                dropped += 1
                continue
            entry.names[name] = None
            added = True
        if added:
            self.unlocks_gen += 1
        return dropped

    def warn_full(self, form: str, kind: str | None = None) -> None:
        """W57, once per session per record (per kind for unlocks)."""
        key = (form, kind if form == UNLOCK else None)
        if key in self._full_warned:
            return
        self._full_warned.add(key)
        self.log.warning("%s", full_text(form, kind), extra={"code": "W57"})

    def warn_dropped(self, count: int) -> None:
        """W54 with a count only (SEC-F12-09a)."""
        if count > 0:
            self.log.warning("%s", dropped_text(self.display, count), extra={"code": "W54"})

    # --- Internals ---------------------------------------------------------------------------

    def _check_access(self, name: str) -> None:
        if self._in_defines:
            raise PersistentInDefine(name)

    def _check_name(self, name: str) -> None:
        if type(name) is str and name.startswith("_"):
            raise PersistentEngineName(name, "set")
        if not valid_name(name):
            raise PersistentEngineName(name if type(name) is str else "", "name")

    def _next_epoch(self) -> int:
        self._epoch += 1
        return self._epoch

    def _touch(self, form: str, group: str, created: bool = False) -> None:
        for journal in self._journals:
            touched = journal.touched[form]
            if created:
                touched.pop(group, None)          # re-created: it moved to the end
                touched[group] = True
            elif group not in touched:
                touched[group] = False

    def _bump_values(self) -> None:
        self.version += 1
        self.values_gen += 1

    def _remove(self, name: str) -> None:
        entry = self._values.pop(name)
        self._sum -= entry.size

    def _over(self, count: int, total: int) -> tuple[str, int] | None:
        if count > PERSIST_MAX_NAMES:
            return "names", count
        size = 2 + total + max(0, count - 1)
        if size > PERSIST_MAX_BYTES:
            return "bytes", size
        return None

    def _make_room(self, name: str, size: int, *, give_way: bool | None = None) -> None:
        """Make an entry of ``size`` bytes under ``name`` fit: names the program doesn't
        mention give way, oldest first (W54), if ``name`` is mentioned or has a default.
        Raises ``PersistentTooBig`` with nothing changed if it can't fit."""
        old = self._values.get(name)
        count = len(self._values) + (old is None)
        total = self._sum - (old.size if old is not None else 0) + size
        problem = self._over(count, total)
        if problem is None:
            return
        if give_way is None:
            give_way = name in self._known or name in self._launch
        drop: list[str] = []
        if give_way:
            for other, entry in self._values.items():
                if other == name or other in self._known or other in self._launch:
                    continue
                drop.append(other)
                count -= 1
                total -= entry.size
                if self._over(count, total) is None:
                    break
            else:
                drop = []
        if not drop:
            form, size = problem
            limit = PERSIST_MAX_NAMES if form == "names" else PERSIST_MAX_BYTES
            raise PersistentTooBig(name, form, size, limit)
        for other in drop:
            self._remove(other)
        self.warn_dropped(len(drop))

    def _put(self, name: str, value: Value, frag: bytes, *, changed: bool,
             give_way: bool | None = None) -> None:
        name_json = compact_json(name)
        size = len(name_json) + 1 + len(frag)
        self._make_room(name, size, give_way=give_way)
        old = self._values.get(name)
        if old is not None:
            self._sum -= old.size
        self._values[name] = _Entry(value, frag, name_json)
        self._sum += size
        self._bump_values()
        if changed:
            self._changed[name] = self.version

    def _mark(self, form: str, group: str, key: str) -> None:
        records = self._records[form]
        run = records.runs.get(group)
        if run is not None and key in run:
            return
        cap = self.record_cap(form)
        if records.total >= cap:
            while records.total >= cap and records.runs:
                oldest = next((g for g in records.runs if g != group), group)
                self.drop_record(form, oldest)
            self.warn_full(form)
            run = records.runs.get(group)
        if run is None:
            run = records.runs[group] = _KeyRun([], self._next_epoch())
            if self._journals:
                self._touch(form, group, True)
        elif self._journals:
            self._touch(form, group)
        run.order.append(key)
        if run.members is not None:
            run.members.add(key)
        records.total += 1
        self.version += 1


# --- The author's facade (04 §5.1; F12 step 3a) ----------------------------------------------

def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name[:2] == "__" and name[-2:] == "__"


class PersistentNamespace:
    """``persistent`` in the story namespace: ``persistent.x`` reads, sets, and deletes go to
    the store (E180, E181, E183 there); ``persistent._clear(progress=False)`` is the one
    engine method; any other ``_`` name read is E182's read form, set or deleted its set
    form. While defines are evaluated every access is E185 (``PersistentInDefine``).

    Python's own ``__dunder__`` attributes behave as on any object (``isinstance`` and the
    engine's checks look them up), and never reach the store. ``dir()`` lists the store's
    names; ``repr`` never shows a value (SEC-F12-09)."""

    __slots__ = ("_store",)

    def __init__(self, store: "PersistentStore") -> None:
        object.__setattr__(self, "_store", store)

    def __getattribute__(self, name: str) -> object:
        if _is_dunder(name):
            return object.__getattribute__(self, name)
        store: PersistentStore = object.__getattribute__(self, "_store")
        if name.startswith("_"):
            store._check_access(name)
            if name == "_clear":
                return _clearer(store)
            raise PersistentEngineName(name, "read")
        return store.get(name)

    def __setattr__(self, name: str, value: object) -> None:
        object.__getattribute__(self, "_store").set(name, value)

    def __delattr__(self, name: str) -> None:
        object.__getattribute__(self, "_store").delete(name)

    def __dir__(self) -> list[str]:
        store: PersistentStore = object.__getattribute__(self, "_store")
        store._check_access("")
        return sorted(store.names())

    def __repr__(self) -> str:
        return "<persistent data>"


def _clearer(store: "PersistentStore") -> Callable[..., None]:
    """``persistent._clear``: only ``progress=True`` or ``progress=False`` (keyword), else
    E182's progress form (a value that isn't exactly a bool) or its call form."""

    def _clear(*args: object, **kwargs: object) -> None:
        if args or any(key != "progress" for key in kwargs):
            raise PersistentEngineName("_clear", "call")
        store.clear(progress=kwargs.get("progress", False))  # type: ignore[arg-type]

    return _clear


def store_of(namespace: object) -> "PersistentStore | None":
    """The store behind a ``PersistentNamespace``, else None."""
    if type(namespace) is PersistentNamespace:
        return object.__getattribute__(namespace, "_store")
    return None


register_value_kind(PersistentNamespace, "persistent data")      # E85e's kind words (G13)


__all__ = ["CHOSEN", "CHOSEN_MAX", "KIND_MAX_CHARS", "Missing", "PERSIST_MAX_BYTES",
           "PERSIST_MAX_NAMES", "PERSIST_NAME_MAX_CHARS", "PROGRESS", "PersistentEngineName",
           "PersistentError", "PersistentInDefine", "PersistentNamespace", "PersistentNoValue",
           "PersistentStore", "PersistentViewName", "store_of",
           "PersistentTooBig", "PersistentUnsaveable", "RESET", "RecordJournal", "SEEN",
           "SEEN_MAX", "UNLOCK",
           "UNLOCK_KINDS_MAX", "UNLOCK_NAMES_MAX", "UNLOCK_NAME_MAX_CHARS", "VALUES",
           "KEY_RE", "LABEL_MAX_CHARS", "compact_json", "dropped_text", "full_text",
           "scheme_text", "valid_kind", "valid_label", "valid_menu_sid", "valid_name",
           "valid_unlock_name"]
