"""The codex at run time: tips and items (F21 ``04-technical.md`` §5, §7.1–7.5; ``07`` I-4,
I-6, I-7, I-8).

Why this module exists: a **tip** is kept across playthroughs (a name in F12's revocable
unlock kind ``"tip"``, so ``lock tip`` can take it back), an **item** belongs to this
playthrough (a name in ``GameState.items``, saved and rolled back like a variable). Both
change only through one door, ``Codex``, which checks the name and the kind the same way for
the ``lock``/``unlock`` lines, F25/F27, and F40's console. Author Python only reads them,
through ``CodexReader`` (the engine name ``codex``).

- ``CodexIndex`` (``interp.codex.index``): every declared entry of a ``Program`` in include
  order, then line (``Program.codex``); ``has`` is ``"codex_read"``'s ``known`` recognizer
  and ``is_tip`` ``"tip"``'s, so undeclared names on file are never shown or counted and give
  way in a full kind (PR-F21-10).
- ``Codex`` (``interp.codex``; main thread only): ``tips()`` (cached per the store's
  ``unlocks_gen``, 07 I-7), ``items()``, ``has``, ``give``/``take`` (the live held list,
  order obtained; hidden names kept and saved again), ``unlock_tip``/``relock_tip`` (the
  store), ``is_read``/``mark_read`` (kind ``"codex_read"``, the presentation's one write,
  07 I-13), ``state()`` (an ``ItemsState`` cached until the list changes, TR-F21-04),
  ``new_game``, ``merged`` (restore step 3, pure), ``install`` (restore step 4). A new tip or
  item holds ``CodexAdded`` through the interpreter's ``_hold``. A bad name raises
  ``UnknownEntry`` or ``WrongKind`` (both ``KeyError``).
- ``CodexReader`` is ``G["codex"]`` (not saved): ``codex.tips`` and ``codex.items``, a fresh
  ``list`` per read (06 D1). Every other attribute is E256 form 3 (``CodexNoAttr``, an
  ``AttributeError``); any set or delete is form 2 (``CodexReadOnly``); before a game starts
  (a define at launch) every read is form 1 (``CodexNotStarted``). Python's own
  ``__dunder__`` attributes behave as on any object. The ``Codex`` lives outside the
  reader's attributes (07 I-6), in ``_BOUND``.
- ``run_codex_lock`` is the ``CodexLock`` executor (§7.1), registered once by
  ``interpreter.py``; dev runs log W141 (area ``story``) for a ``lock item`` that takes
  nothing, once per line per ``Codex``. Not a checkpoint.
- ``install(interp)`` (§7.3): per interpreter (F39 calls it again with a new program): the
  index, the ``Codex``, the store's two kinds (registering again replaces ``known``), and
  ``G``'s reader bound to it.

**F64 round 1 (item counts, the purse; specs/F64-items/SPEC.md).** Each held item has a
count (``count(name)``; 0 when not held): ``give(name, n)`` adds up to the item's ``cap`` (1
for a plain item, so a plain item still holds one), ``take(name, n)`` removes down to 0 and
drops the name at 0. The counts are saved in ``ItemsState.counts`` (a save from before F64
holds one of each); ``merged`` clamps a saved count to the item's ``cap`` now. ``purse()`` is
the money item and its count. The engine name ``items`` (``ItemsReader``, read-only,
``items.count("coin")``) is bound only when the story has no variable of its own named
``items`` (``itemcounts.program_binds_items``): then it is reserved for this interpreter, never
saved; otherwise the story's own ``items`` is left alone and ``codex.count`` reads counts.
A bad name is E440, any other use of ``items`` E441.

**F65 round 1 (codex kinds, chats you can reread).** A kind is a description in
``core/codexkinds`` (its page, tab word, order, fields; tips and items were the first two),
and ``Codex`` is the one store for all of them: tips in the persistent store, everything
else in ``GameState.items``. ``listed(kind)`` gives any kind's names in its page's order
(``tips()``, ``items()``, or the inbox's thread keys newest first). The Inbox's store is
**deliveries** (``runtime/inbox.py``): ``deliveries()`` (oldest first), ``add_delivery``
(the oldest drop past ``inbox.THREADS_MAX``/``CHARS_MAX``; no notice: the player just read
it), saved in ``ItemsState.inbox`` by ``state``/``merged``/``install`` like the held list,
so rollback and loads replay them. ``delivery_read``/``mark_delivery_read`` keep the Inbox's
read marks in the persistent kind ``inbox.READ_KIND`` (as tips' and items' marks are), so
reading a thread survives a load. The page's port (``app/inbox.py``) builds its rows.
F65 round 2: the ``chat`` kind's entries are **threads**, one per contact (``inbox()``,
``inbox.group_threads`` over the deliveries and the program's declared contacts, cached per
deliveries tuple); ``unread()`` counts the deliveries not read yet (the quick menu's Inbox
button), ``thread_unread(key)`` one thread's.

``CodexEntry`` and ``CodexCategory`` are ``script/codex.py``'s, re-exported here (F22 I-1
rule), so ``ui`` never imports ``engine.script``. Layering as ``points.py``: below the
interpreter, importing it only under ``TYPE_CHECKING`` or inside a function. Pure: no file,
clock, randomness, or thread; W141 prints only script names (04 §8 item 2).
"""

import weakref
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.runtime.commands import CodexAdded, Command
from engine.runtime.errors import AuthorRefusal
from engine.runtime.inbox import READ_KIND as INBOX_READ_KIND
from engine.runtime.inbox import ContactThread, Delivery, group_threads, kept
from engine.runtime.persistent import PersistentStore
from engine.runtime.state import EMPTY_ITEMS, ITEMS_HELD_MAX, ItemsState
from engine.runtime.values import kind_words
from engine.runtime.values import register_kind as register_value_kind
from engine.core.codexkinds import CHAT
from engine.script.codex import WORD_ITEM, WORD_TIP, CodexCategory, CodexEntry, CodexLock
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.suggest import suggest

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.script.program import Program

TIP_KIND: Final = "tip"                 # F12 unlock kinds: tips (revocable) and read marks
READ_KIND: Final = "codex_read"
ATTRS: Final[tuple[str, ...]] = ("tips", "items", "count")  # what ``codex`` has (E255, E256)
ITEMS_NAME: Final = "items"             # F64: the engine view of the counts (soft name)
CHAT_KIND: Final = CHAT.name            # F65: the Inbox's threads

_story_log = get_logger("story")        # W141 (dev, run)


# --- The index (04 §5) --------------------------------------------------------------------------

class CodexIndex:
    """Every declared entry of a ``Program`` (immutable). Lookups take any value and give
    None/False for anything that isn't a declared name."""

    __slots__ = ("_entries", "_by_name", "tips", "items", "categories", "money")

    def __init__(self, entries: tuple[CodexEntry, ...],
                 categories: tuple[CodexCategory, ...]) -> None:
        self._entries = entries
        self._by_name = {e.name: e for e in entries}
        self.tips: tuple[CodexEntry, ...] = tuple(e for e in entries if e.kind == WORD_TIP)
        self.items: tuple[CodexEntry, ...] = tuple(e for e in entries if e.kind == WORD_ITEM)
        self.categories = categories
        # F64: the purse's item (the first marked money; a second is E439 at load)
        self.money: CodexEntry | None = next((e for e in self.items if e.money), None)

    @classmethod
    def build(cls, program: "Program") -> "CodexIndex":
        return cls(tuple(program.codex), tuple(program.codex_categories))

    def get(self, name: object) -> CodexEntry | None:
        return self._by_name.get(name) if type(name) is str else None   # type: ignore[arg-type]

    def has(self, name: object) -> bool:
        """``"codex_read"``'s ``known`` recognizer: a declared tip or item."""
        return type(name) is str and name in self._by_name

    def is_tip(self, name: object) -> bool:
        """``"tip"``'s ``known`` recognizer."""
        entry = self.get(name)
        return entry is not None and entry.kind == WORD_TIP

    def is_item(self, name: object) -> bool:
        entry = self.get(name)
        return entry is not None and entry.kind == WORD_ITEM

    def suggest(self, name: str, kind: str) -> str | None:
        """The closest declared name of ``kind`` (F02's did-you-mean), or None."""
        pool = self.tips if kind == WORD_TIP else self.items
        return suggest(name, (e.name for e in pool)) if type(name) is str else None

    def __iter__(self) -> Iterator[CodexEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


class UnknownEntry(KeyError):
    """No entry of ``kind`` has this name; ``suggestion`` is the closest one, or None."""

    def __init__(self, name: object, kind: str, suggestion: str | None = None) -> None:
        super().__init__(name)
        self.name = name
        self.kind = kind
        self.suggestion = suggestion


class WrongKind(KeyError):
    """``name`` is declared, but as the other kind: ``kind`` is its kind, ``wanted`` the one
    asked for."""

    def __init__(self, name: str, kind: str, wanted: str) -> None:
        super().__init__(name)
        self.name = name
        self.kind = kind
        self.wanted = wanted


# --- The API (interp.codex) -----------------------------------------------------------------------

class Codex:
    """The launch's tips and items (module docstring). ``hold`` is the interpreter's
    ``_hold``, so a ``CodexAdded`` is released with the burst (F03 I-3)."""

    __slots__ = ("index", "_store", "_hold", "dev", "log", "_held", "_counts", "_state",
                 "_items", "_tips", "_tips_gen", "w141_warned", "_bar", "_threads",
                 "contacts", "_grouped", "_unread")

    def __init__(self, index: CodexIndex, store: PersistentStore,
                 hold: Callable[[Command], None], *, dev: bool = False,
                 log=None) -> None:
        self.index = index
        self._store = store
        self._hold = hold
        self.dev = dev
        self.log = log if log is not None else _story_log
        self._held: list[str] = []
        self._counts: dict[str, int] = {}           # F64: held name -> count (absent: 1)
        self._bar = False                           # F64 round 2: show hotbar
        self._threads: tuple[Delivery, ...] = ()     # F65: the Inbox, oldest first
        self.contacts: dict[str, str] = {}             # F65 round 2: name -> shown name
        self._grouped: tuple = ((), ())                # (deliveries, threads)
        self._unread: tuple = (None, -1, 0)            # (deliveries, unlocks_gen, count)
        self._state: ItemsState | None = EMPTY_ITEMS
        self._items: tuple[str, ...] | None = ()
        self._tips: tuple[str, ...] = ()
        self._tips_gen = -1
        self.w141_warned: set[str] = set()

    # Reading --------------------------------------------------------------------------------

    def tips(self) -> tuple[str, ...]:
        """The unlocked declared tips, in declaration order; cached per ``unlocks_gen``
        (07 I-7: ``version`` rises with every seen mark)."""
        store = self._store
        if self._tips_gen != store.unlocks_gen:
            self._tips = tuple(e.name for e in self.index.tips
                               if store.is_unlocked(TIP_KIND, e.name))
            self._tips_gen = store.unlocks_gen
        return self._tips

    def items(self) -> tuple[str, ...]:
        """The held declared items, in the order obtained (hidden names left out)."""
        items = self._items
        if items is None:
            is_item = self.index.is_item
            items = self._items = tuple(n for n in self._held if is_item(n))
        return items

    def has(self, name: object) -> bool:
        """A tip that is unlocked or an item that is held; False for anything undeclared."""
        entry = self.index.get(name)
        if entry is None:
            return False
        if entry.kind == WORD_TIP:
            return self._store.is_unlocked(TIP_KIND, entry.name)
        return entry.name in self._held

    def is_read(self, name: object) -> bool:
        return type(name) is str and self._store.is_unlocked(READ_KIND, name)

    def count(self, name: object) -> int:
        """F64: how many of item ``name`` the player holds (0: none). ``UnknownEntry`` or
        ``WrongKind`` for a name that isn't a declared item."""
        entry = self._entry(name, WORD_ITEM)
        if entry.name not in self._held:
            return 0
        return self._counts.get(entry.name, 1)

    def purse(self) -> "tuple[CodexEntry, int] | None":
        """F64: the item marked ``money`` and how many the player holds, or None."""
        entry = self.index.money
        return None if entry is None else (entry, self.count(entry.name))

    def bar_shown(self) -> bool:
        """F64 round 2: ``show hotbar`` is in force (story state, saved with the items)."""
        return self._bar

    def deliveries(self) -> tuple[Delivery, ...]:
        """F65: the Inbox's deliveries (finished chats and sent messages), oldest first."""
        return self._threads

    def inbox(self) -> tuple[ContactThread, ...]:
        """F65 round 2: the Inbox's threads, one per contact, newest first."""
        grouped = self._grouped
        if grouped[0] is not self._threads:
            grouped = self._grouped = (self._threads,
                                       group_threads(self._threads, self.contacts))
        return grouped[1]

    def unread(self) -> int:
        """F65 round 2: the deliveries not read on the Inbox page yet (asked every frame by
        the quick menu, so kept per deliveries tuple and store change)."""
        kept_ = self._unread
        gen = self._store.unlocks_gen
        if kept_[0] is not self._threads or kept_[1] != gen:
            count = sum(1 for d in self._threads if not self.delivery_read(d.key))
            kept_ = self._unread = (self._threads, gen, count)
        return kept_[2]

    def thread_unread(self, key: object) -> int:
        """F65 round 2: thread ``key``'s deliveries not read yet (0 for no such thread)."""
        thread = next((t for t in self.inbox() if t.key == key), None)
        if thread is None:
            return 0
        return sum(1 for d in thread.parts if not self.delivery_read(d.key))

    def listed(self, kind: str) -> tuple[str, ...]:
        """F65: kind ``kind``'s names in its page's order (``core/codexkinds``): the unlocked
        tips, the held items, the thread keys newest first (round 2: one per contact); ()
        for any other kind."""
        if kind == WORD_TIP:
            return self.tips()
        if kind == WORD_ITEM:
            return self.items()
        if kind == CHAT_KIND:
            return tuple(t.key for t in self.inbox())
        return ()

    def delivery_read(self, key: object) -> bool:
        return type(key) is str and self._store.is_unlocked(INBOX_READ_KIND, key)

    def has_delivery(self, key: object) -> bool:
        """``inbox.READ_KIND``'s ``known`` recognizer: a delivery in this inbox."""
        return type(key) is str and any(t.key == key for t in self._threads)

    # Changing --------------------------------------------------------------------------------

    def set_bar(self, shown: bool) -> None:
        """F64 round 2: ``show hotbar`` / ``hide hotbar``."""
        if self._bar != bool(shown):
            self._bar = bool(shown)
            self._state = None

    def _entry(self, name: object, kind: str) -> CodexEntry:
        entry = self.index.get(name)
        if entry is None:
            raise UnknownEntry(name, kind, self.index.suggest(name, kind))  # type: ignore[arg-type]
        if entry.kind != kind:
            raise WrongKind(entry.name, entry.kind, kind)
        return entry

    def give(self, name: str, amount: int = 1) -> bool:
        """``unlock item``: add ``amount`` (F64; at most the item's ``cap`` held); a new name
        goes at the end. True if it wasn't held (holds ``CodexAdded``). Past
        ``ITEMS_HELD_MAX`` names the oldest hidden one is dropped."""
        entry = self._entry(name, WORD_ITEM)
        held = self._held
        if entry.name in held:
            now = self._counts.get(entry.name, 1)
            new = min(entry.cap, now + max(0, amount))
            if new > now:
                self._counts[entry.name] = new
                self._changed()
            return False
        new = min(entry.cap, max(1, amount))
        if new != 1:
            self._counts[entry.name] = new
        held.append(entry.name)
        if len(held) > ITEMS_HELD_MAX:
            is_item = self.index.is_item
            oldest = next((n for n in held if not is_item(n)), None)
            if oldest is not None:
                held.remove(oldest)
                self._counts.pop(oldest, None)
        self._changed()
        self._hold(CodexAdded(WORD_ITEM, entry.name, entry.title))
        return True

    def take(self, name: str, amount: int = 1) -> bool:
        """``lock item``: take ``amount`` (F64; never below 0, and the name goes at 0); True
        if any was held."""
        entry = self._entry(name, WORD_ITEM)
        if entry.name not in self._held:
            return False
        left = self._counts.get(entry.name, 1) - max(1, amount)
        if left > 1:
            self._counts[entry.name] = left
        elif left == 1:
            self._counts.pop(entry.name, None)
        else:
            self._held.remove(entry.name)
            self._counts.pop(entry.name, None)
        self._changed()
        return True

    def unlock_tip(self, name: str) -> bool:
        """``unlock tip``: record ``name`` in the store; True if it is new (holds
        ``CodexAdded``)."""
        entry = self._entry(name, WORD_TIP)
        if not self._store.unlock(TIP_KIND, entry.name):
            return False
        self._hold(CodexAdded(WORD_TIP, entry.name, entry.title))
        return True

    def relock_tip(self, name: str) -> bool:
        """``lock tip``: F19's ``relock``; True if it was unlocked."""
        entry = self._entry(name, WORD_TIP)
        return self._store.relock(TIP_KIND, entry.name)

    def add_delivery(self, thread: Delivery) -> None:
        """F65: a finished chat joins the Inbox (``inbox.record_chat``)."""
        self._threads = kept(self._threads + (thread,))
        self._state = None

    def replace_delivery(self, delivery: Delivery) -> bool:
        """F65 round 3: the delivery with ``delivery.key`` becomes ``delivery`` (a reply
        picked); False when no delivery has that key."""
        threads = self._threads
        for i, found in enumerate(threads):
            if found.key == delivery.key:
                self._threads = threads[:i] + (delivery,) + threads[i + 1:]
                self._state = None
                return True
        return False

    def mark_delivery_read(self, key: object) -> bool:
        """F65: the Inbox page's one write: a delivery's read mark; True if it is new. False,
        writing nothing, for a key not in the inbox."""
        if not self.has_delivery(key):
            return False
        return self._store.unlock(INBOX_READ_KIND, key)  # type: ignore[arg-type]

    def mark_read(self, name: object) -> bool:
        """The presentation port's one write (04 §7.7, 07 I-13): a declared entry's read
        mark; True if it is new. False, writing nothing, for an undeclared name."""
        if not self.index.has(name):
            return False
        return self._store.unlock(READ_KIND, name)  # type: ignore[arg-type]

    def _changed(self) -> None:
        self._state = None
        self._items = None

    # State (GameState.items, 04 §7.4) ------------------------------------------------------

    def state(self) -> ItemsState:
        """The held names as an ``ItemsState``, cached until the next change, so unchanged
        checkpoints share one object (TR-F21-04)."""
        state = self._state
        if state is None:
            held = tuple(self._held)
            counts = self._counts
            numbers = tuple(counts.get(n, 1) for n in held) if counts else ()
            threads = self._threads
            state = self._state = (ItemsState(held, numbers, self._bar, threads)
                                   if held or self._bar or threads else EMPTY_ITEMS)
        return state

    def new_game(self) -> None:
        """New Game: no items (before the first default, 04 §7.4)."""
        self._held = []
        self._counts = {}
        self._bar = False
        self._threads = ()
        self._state = EMPTY_ITEMS
        self._items = ()

    def merged(self, saved: ItemsState) -> ItemsState:
        """Restore step 3 (pure): ``saved``'s names in order; a name that isn't a declared
        item (a tip now included) is hidden, and only the newest ``ITEMS_HELD_MAX -
        len(index.items)`` hidden names are kept. F64: each declared item's count is clamped
        to its ``cap`` now (a hidden name keeps its count). ``saved`` itself when nothing
        changes."""
        index = self.index
        is_item = index.is_item
        room = max(0, ITEMS_HELD_MAX - len(index.items))
        hidden = [n for n in saved.held if not is_item(n)]
        keep = set(hidden[len(hidden) - room:]) if room else set()
        held: list[str] = []
        counts: list[int] = []
        for i, name in enumerate(saved.held):
            entry = index.get(name)
            if entry is not None and entry.kind == WORD_ITEM:
                count = min(saved.count_of(i), entry.cap)
            elif name in keep:
                count = saved.count_of(i)
            else:
                continue
            held.append(name)
            counts.append(count)
        numbers = tuple(counts) if any(n != 1 for n in counts) else ()
        if tuple(held) == saved.held and numbers == saved.counts:
            return saved
        return ItemsState(tuple(held), numbers, saved.bar, saved.inbox) \
            if held or saved.bar or saved.inbox else EMPTY_ITEMS

    def install(self, held: "tuple[str, ...] | ItemsState") -> None:
        """Make ``held`` (from ``merged``, or a ``state()`` to put back) the held list:
        restore step 4 and its roll-back. An ``ItemsState`` is kept as the cached state; a
        tuple of names holds one of each."""
        if type(held) is ItemsState:
            self._held = list(held.held)
            self._counts = {n: c for n, c in zip(held.held, held.counts) if c != 1}
            self._bar = held.bar
            self._threads = held.inbox
            self._state = held
        else:
            self._held = list(held)                         # type: ignore[arg-type]
            self._counts = {}
            self._bar = False
            self._threads = ()
            self._state = None
        self._items = None


# --- The engine name ``codex`` (CodexReader, 07 I-6) ---------------------------------------------

class CodexNotStarted(AuthorRefusal):
    """E256 form 1: ``codex`` was read before a game started (a define at launch)."""

    def __init__(self, name: str) -> None:
        super().__init__("E256", format_message("E256", ("define", name)))


class CodexReadOnly(AuthorRefusal):
    """E256 form 2: a set or delete through ``codex`` that the load check couldn't see."""

    def __init__(self, name: str) -> None:
        super().__init__("E256", format_message("E256", ("change", name)))


class CodexNoAttr(AuthorRefusal, AttributeError):
    """E256 form 3: ``codex`` has no such attribute (an ``AttributeError``, so ``hasattr``
    is False). Its text is E255 form 1's (06 D4)."""

    def __init__(self, name: str) -> None:
        super().__init__("E256", format_message("E256", ("unknown", name,
                                                         suggest(name, ATTRS))))
        self.name = name


# The ``Codex`` of each bound reader, outside the reader's own attributes (07 I-6).
_BOUND: "weakref.WeakKeyDictionary[CodexReader, Codex]" = weakref.WeakKeyDictionary()


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name[:2] == "__" and name[-2:] == "__"


class CodexReader:
    """``codex`` in author Python (module docstring). ``repr`` is ``<codex>``; ``dir`` lists
    ``items`` and ``tips``."""

    __slots__ = ("__weakref__",)

    def __getattribute__(self, name: str) -> object:
        if _is_dunder(name):
            return object.__getattribute__(self, name)
        codex = _BOUND.get(self)
        if codex is None:
            raise CodexNotStarted(name)
        if name == "tips":
            return list(codex.tips())
        if name == "items":
            return list(codex.items())
        if name == "count":
            return _counter(codex)
        raise CodexNoAttr(name)

    def __setattr__(self, name: str, value: object) -> None:
        raise CodexReadOnly(name)

    def __delattr__(self, name: str) -> None:
        raise CodexReadOnly(name)

    def __dir__(self) -> list[str]:
        return ["count", "items", "tips"]

    def __repr__(self) -> str:
        return "<codex>"


def _counter(codex: Codex) -> Callable[[object], int]:
    """F64: ``codex.count`` / ``items.count``: an item's count, E440 for a bad name."""

    def count(name: object) -> int:
        if type(name) is not str:
            raise AuthorRefusal("E440", format_message("E440", ("text", kind_words(name))))
        try:
            return codex.count(name)
        except UnknownEntry as e:
            raise AuthorRefusal("E440", format_message(
                "E440", ("unknown", name, e.suggestion))) from None
        except WrongKind:
            raise AuthorRefusal("E440", format_message("E440", ("tip", name))) from None

    return count


# --- The engine name ``items`` (F64) ------------------------------------------------------------

_ITEMS_BOUND: "weakref.WeakKeyDictionary[ItemsReader, Codex]" = weakref.WeakKeyDictionary()


class ItemsReader:
    """``items`` in author Python (F64): ``items.count("coin")`` only. Read-only; before a
    game starts every read is E441's define form; any other attribute E441's unknown form."""

    __slots__ = ("__weakref__",)

    def __getattribute__(self, name: str) -> object:
        if _is_dunder(name):
            return object.__getattribute__(self, name)
        codex = _ITEMS_BOUND.get(self)
        if codex is None:
            raise AuthorRefusal("E441", format_message("E441", ("define", name)))
        if name == "count":
            return _counter(codex)
        raise _ItemsNoAttr(name)

    def __setattr__(self, name: str, value: object) -> None:
        raise AuthorRefusal("E441", format_message("E441", ("change", name)))

    def __delattr__(self, name: str) -> None:
        raise AuthorRefusal("E441", format_message("E441", ("change", name)))

    def __dir__(self) -> list[str]:
        return ["count"]

    def __repr__(self) -> str:
        return "<items>"


class _ItemsNoAttr(AuthorRefusal, AttributeError):
    def __init__(self, name: str) -> None:
        super().__init__("E441", format_message("E441", ("unknown", name)))
        self.name = name


def bind_reader(reader: CodexReader, codex: Codex) -> None:
    """Give ``reader`` its ``Codex`` (the launch built it unbound, so a define that read it
    got E256 form 1). A function, not a method: every attribute of the reader but ``tips``
    and ``items`` is E256 form 3 (04 §5's ``bind``)."""
    _BOUND[reader] = codex


register_value_kind(CodexReader, "the codex")           # E85e's kind words
register_value_kind(ItemsReader, "the item counts")


# --- The executor (04 §7.1) -----------------------------------------------------------------------

def run_codex_lock(interp: "Interpreter", stmt: CodexLock) -> "Step":
    """``unlock tip`` → ``unlock_tip``; ``lock tip`` → ``relock_tip``; ``unlock item`` →
    ``give``; ``lock item`` → ``take``, W141 in dev runs when nothing was taken (once per
    line). No wait, no checkpoint."""
    from engine.runtime.interpreter import Step         # the interpreter imports this module
    codex: Codex = interp.codex
    if stmt.kind == WORD_TIP:
        if stmt.unlock:
            codex.unlock_tip(stmt.name)
        else:
            codex.relock_tip(stmt.name)
    elif stmt.unlock:
        codex.give(stmt.name, stmt.amount)
    elif not codex.take(stmt.name, stmt.amount) and interp.dev \
            and stmt.sid not in codex.w141_warned:
        codex.w141_warned.add(stmt.sid)
        text = format_message("W141", (stmt.name,))
        warning = ScriptWarning(text, code="W141", file=stmt.file.ref, line=stmt.line)
        _story_log.warning("%s", warning.format(), extra={"code": "W141"})
    return Step.CONTINUE


# --- Installing (04 §7.3) -------------------------------------------------------------------------

def install(interp: "Interpreter") -> Codex:
    """Per interpreter (F39: again with a new program): the index, the ``Codex``, the store's
    kinds ``"tip"`` (revocable, ``known`` = ``is_tip``), ``"codex_read"`` (``known`` =
    ``has``) and F65's ``"inbox_read"`` (``known`` = ``has_delivery``), and ``G``'s ``codex``
    reader bound to it (a hand-built ``G`` gets one). F65 round 2: the declared contacts'
    shown names (``Codex.contacts``)."""
    store = interp.persistent
    index = CodexIndex.build(interp.program)
    codex = Codex(index, store, interp._hold, dev=interp.dev)
    store.register_kind(TIP_KIND, known=index.is_tip, revocable=True)
    store.register_kind(READ_KIND, known=index.has)
    store.register_kind(INBOX_READ_KIND, known=codex.has_delivery)  # F65
    codex.contacts = {c.name: c.title for c in getattr(interp.program, "contacts", ())}
    reader = interp.G.get("codex")
    if type(reader) is not CodexReader:
        reader = interp.G["codex"] = CodexReader()
    bind_reader(reader, codex)
    _install_items(interp, codex)
    return codex


def _install_items(interp: "Interpreter", codex: Codex) -> None:
    """F64: bind ``G["items"]`` to an ``ItemsReader`` and reserve the name for this
    interpreter, unless the story has a variable of its own named ``items`` (then any reader
    a previous program left is removed, and the name is the story's)."""
    from engine.script.itemcounts import program_binds_items
    G = interp.G
    if program_binds_items(interp.program):
        interp.reserved = interp.reserved - {ITEMS_NAME}
        if type(G.get(ITEMS_NAME)) is ItemsReader:
            del G[ITEMS_NAME]
        return
    reader = G.get(ITEMS_NAME)
    if type(reader) is not ItemsReader:
        reader = G[ITEMS_NAME] = ItemsReader()
    _ITEMS_BOUND[reader] = codex
    interp.reserved = interp.reserved | {ITEMS_NAME}


__all__ = ["ATTRS", "ITEMS_NAME", "ItemsReader", "Codex", "CodexCategory", "CodexEntry", "CodexIndex", "CodexNoAttr",
           "CodexNotStarted", "CodexReadOnly", "CodexReader", "READ_KIND", "TIP_KIND",
           "UnknownEntry", "WrongKind", "bind_reader", "install", "run_codex_lock"]
