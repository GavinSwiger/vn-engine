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
from engine.runtime.persistent import PersistentStore
from engine.runtime.state import EMPTY_ITEMS, ITEMS_HELD_MAX, ItemsState
from engine.runtime.values import register_kind as register_value_kind
from engine.script.codex import WORD_ITEM, WORD_TIP, CodexCategory, CodexEntry, CodexLock
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.suggest import suggest

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.script.program import Program

TIP_KIND: Final = "tip"                 # F12 unlock kinds: tips (revocable) and read marks
READ_KIND: Final = "codex_read"
ATTRS: Final[tuple[str, str]] = ("tips", "items")     # what ``codex`` has (E255, E256)

_story_log = get_logger("story")        # W141 (dev, run)


# --- The index (04 §5) --------------------------------------------------------------------------

class CodexIndex:
    """Every declared entry of a ``Program`` (immutable). Lookups take any value and give
    None/False for anything that isn't a declared name."""

    __slots__ = ("_entries", "_by_name", "tips", "items", "categories")

    def __init__(self, entries: tuple[CodexEntry, ...],
                 categories: tuple[CodexCategory, ...]) -> None:
        self._entries = entries
        self._by_name = {e.name: e for e in entries}
        self.tips: tuple[CodexEntry, ...] = tuple(e for e in entries if e.kind == WORD_TIP)
        self.items: tuple[CodexEntry, ...] = tuple(e for e in entries if e.kind == WORD_ITEM)
        self.categories = categories

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

    __slots__ = ("index", "_store", "_hold", "dev", "log", "_held", "_state", "_items",
                 "_tips", "_tips_gen", "w141_warned")

    def __init__(self, index: CodexIndex, store: PersistentStore,
                 hold: Callable[[Command], None], *, dev: bool = False,
                 log=None) -> None:
        self.index = index
        self._store = store
        self._hold = hold
        self.dev = dev
        self.log = log if log is not None else _story_log
        self._held: list[str] = []
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

    # Changing --------------------------------------------------------------------------------

    def _entry(self, name: object, kind: str) -> CodexEntry:
        entry = self.index.get(name)
        if entry is None:
            raise UnknownEntry(name, kind, self.index.suggest(name, kind))  # type: ignore[arg-type]
        if entry.kind != kind:
            raise WrongKind(entry.name, entry.kind, kind)
        return entry

    def give(self, name: str) -> bool:
        """``unlock item``: add ``name`` at the end; True if it wasn't held (holds
        ``CodexAdded``). Past ``ITEMS_HELD_MAX`` names the oldest hidden one is dropped."""
        entry = self._entry(name, WORD_ITEM)
        held = self._held
        if entry.name in held:
            return False
        held.append(entry.name)
        if len(held) > ITEMS_HELD_MAX:
            is_item = self.index.is_item
            oldest = next((n for n in held if not is_item(n)), None)
            if oldest is not None:
                held.remove(oldest)
        self._changed()
        self._hold(CodexAdded(WORD_ITEM, entry.name, entry.title))
        return True

    def take(self, name: str) -> bool:
        """``lock item``: remove ``name``; True if it was held."""
        entry = self._entry(name, WORD_ITEM)
        if entry.name not in self._held:
            return False
        self._held.remove(entry.name)
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
            state = self._state = ItemsState(held) if held else EMPTY_ITEMS
        return state

    def new_game(self) -> None:
        """New Game: no items (before the first default, 04 §7.4)."""
        self._held = []
        self._state = EMPTY_ITEMS
        self._items = ()

    def merged(self, saved: ItemsState) -> tuple[str, ...]:
        """Restore step 3 (pure): ``saved``'s names in order; a name that isn't a declared
        item (a tip now included) is hidden, and only the newest ``ITEMS_HELD_MAX -
        len(index.items)`` hidden names are kept."""
        is_item = self.index.is_item
        room = max(0, ITEMS_HELD_MAX - len(self.index.items))
        hidden = [n for n in saved.held if not is_item(n)]
        keep = set(hidden[len(hidden) - room:]) if room else set()
        return tuple(n for n in saved.held if is_item(n) or n in keep)

    def install(self, held: "tuple[str, ...] | ItemsState") -> None:
        """Make ``held`` (from ``merged``, or a ``state()`` to put back) the held list:
        restore step 4 and its roll-back. An ``ItemsState`` is kept as the cached state."""
        if type(held) is ItemsState:
            self._held = list(held.held)
            self._state = held
        else:
            self._held = list(held)                         # type: ignore[arg-type]
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
        raise CodexNoAttr(name)

    def __setattr__(self, name: str, value: object) -> None:
        raise CodexReadOnly(name)

    def __delattr__(self, name: str) -> None:
        raise CodexReadOnly(name)

    def __dir__(self) -> list[str]:
        return ["items", "tips"]

    def __repr__(self) -> str:
        return "<codex>"


def bind_reader(reader: CodexReader, codex: Codex) -> None:
    """Give ``reader`` its ``Codex`` (the launch built it unbound, so a define that read it
    got E256 form 1). A function, not a method: every attribute of the reader but ``tips``
    and ``items`` is E256 form 3 (04 §5's ``bind``)."""
    _BOUND[reader] = codex


register_value_kind(CodexReader, "the codex")           # E85e's kind words


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
        codex.give(stmt.name)
    elif not codex.take(stmt.name) and interp.dev and stmt.sid not in codex.w141_warned:
        codex.w141_warned.add(stmt.sid)
        text = format_message("W141", (stmt.name,))
        warning = ScriptWarning(text, code="W141", file=stmt.file.ref, line=stmt.line)
        _story_log.warning("%s", warning.format(), extra={"code": "W141"})
    return Step.CONTINUE


# --- Installing (04 §7.3) -------------------------------------------------------------------------

def install(interp: "Interpreter") -> Codex:
    """Per interpreter (F39: again with a new program): the index, the ``Codex``, the store's
    kinds ``"tip"`` (revocable, ``known`` = ``is_tip``) and ``"codex_read"`` (``known`` =
    ``has``), and ``G``'s ``codex`` reader bound to it (a hand-built ``G`` gets one)."""
    store = interp.persistent
    index = CodexIndex.build(interp.program)
    codex = Codex(index, store, interp._hold, dev=interp.dev)
    store.register_kind(TIP_KIND, known=index.is_tip, revocable=True)
    store.register_kind(READ_KIND, known=index.has)
    reader = interp.G.get("codex")
    if type(reader) is not CodexReader:
        reader = interp.G["codex"] = CodexReader()
    bind_reader(reader, codex)
    return codex


__all__ = ["ATTRS", "Codex", "CodexCategory", "CodexEntry", "CodexIndex", "CodexNoAttr",
           "CodexNotStarted", "CodexReadOnly", "CodexReader", "READ_KIND", "TIP_KIND",
           "UnknownEntry", "WrongKind", "bind_reader", "install", "run_codex_lock"]
