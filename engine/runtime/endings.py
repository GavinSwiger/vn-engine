"""Endings and routes at run time (F19 ``04-technical.md`` §5, §7.1–7.4; ``07`` I-1 to I-4,
I-12).

Why this module exists: an ``ending`` line ends the story and is remembered across
playthroughs, and a route is a label that opens once the player has reached some endings (or
an ``unlock route`` ran). Both records are F12 unlock kinds, ``"ending"`` and ``"route"``,
registered **revocable** so ``lock`` can take a name back. Author code reads them through
two store views, ``persistent.endings`` and ``persistent.routes``.

- ``EndingIndex`` (``interp.endings``): every ``ending`` line in include order, then line;
  ``has`` is the ``"ending"`` kind's ``known`` recognizer, so undeclared names on file are
  never shown, counted, or opened, and give way in a full kind (PR-F19-15).
- ``RouteIndex`` (``interp.routes``): every ``lock route`` declaration in program order;
  ``is_open`` is PR-F19-07 (unlocked, or every ``until`` ending reached).
- ``run_ending`` (the ``Ending`` executor, §7.1): record the ending first, then F18's card
  in and hold phases (``chapters.play_card``) finished by ``Interpreter.end_story()``
  instead of F18's out phase; ``seconds`` 0 ends at once. ``run_lock`` (``Lock``, §7.2):
  ``store.unlock`` / ``store.relock``, W132 in dev runs. Both are registered once, at
  import, by ``interpreter.py`` (07 I-1); neither is a checkpoint type (07 I-12).
- ``ending_in_progress``: F14's pause (07 I-2): appended to ``ROLLBACK_PAUSES`` once, at
  import, so back is refused and forward ignored from the moment an ``ending`` runs until
  the story has ended.
- ``register(interp)`` (§7.3): per interpreter and store, safe to repeat (07 I-1; F39 with a
  new program): the indexes, the two kinds, then the two views with their migration hooks
  (an older game's author values ``endings``/``routes``, W131 once per store).

The getters don't cache: the store caches a view's list per ``unlocks_gen`` (07 I-4) and
hands every read a fresh copy (06 D1).

Layering (as ``chapters.py``): below the interpreter, imported by it, and importing it only
under ``TYPE_CHECKING`` or inside a function. Pure (TR-F03-05): no file, clock, randomness,
or thread; W131 prints only a count, W132 only script names (04 §8 item 2).
"""

import weakref
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.runtime.chapters import play_card
from engine.runtime.commands import TitleCard
from engine.runtime.fourthwall import clear_title
from engine.runtime.persistent import PersistentStore
from engine.runtime.rollback import ROLLBACK_PAUSES
from engine.runtime.values import Value
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.routes import Ending, Lock

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.script.program import Program

ENDING_KIND: Final = "ending"           # F12 unlock kinds (revocable)
ROUTE_KIND: Final = "route"
ENDINGS_VIEW: Final = "endings"         # persistent.endings / persistent.routes
ROUTES_VIEW: Final = "routes"
CARD_KIND: Final = "ending"             # TitleCard.kind: W110's word (04 §19.1 O3)

_story_log = get_logger("story")        # W132 (dev, run)

# W131 forms already logged, per store (07 I-1: once per store, so an older copy's value
# merged in later logs nothing more, TR-F19-08).
_w131_logged: "weakref.WeakKeyDictionary[PersistentStore, set[str]]" = (
    weakref.WeakKeyDictionary())


# --- The indexes (04 §5) ------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EndingInfo:
    """One ``ending`` line: its name, texts as shown, sid, and the label it is in (for an
    ending inside a menu choice, the containing label)."""

    name: str
    heading: str | None
    title: str
    sid: str
    label: str


class EndingIndex:
    """Every ending of a ``Program`` in include order, then line (immutable). Lookups take
    any value and give None/False for anything that isn't an ending's name."""

    __slots__ = ("_items", "_by_name")

    def __init__(self, items: tuple[EndingInfo, ...]) -> None:
        self._items = items
        self._by_name = {info.name: info for info in items}

    @classmethod
    def build(cls, program: "Program") -> "EndingIndex":
        found = sorted(program.endings, key=lambda s: (s.file.order, s.line))
        return cls(tuple(EndingInfo(s.name, s.heading, s.title, s.sid, s.label)
                         for s in found))

    def get(self, name: object) -> EndingInfo | None:
        return self._by_name.get(name) if type(name) is str else None

    def has(self, name: object) -> bool:
        """The ``"ending"`` kind's ``known`` recognizer."""
        return type(name) is str and name in self._by_name

    def __iter__(self) -> Iterator[EndingInfo]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def reached(self, store: PersistentStore) -> tuple[EndingInfo, ...]:
        """The declared endings the store holds, first reached first."""
        by_name = self._by_name
        return tuple(by_name[n] for n in store.unlocked(ENDING_KIND) if n in by_name)


@dataclass(frozen=True, slots=True)
class RouteInfo:
    """One ``lock route`` declaration: the route's name (the label it starts at), title as
    shown, ``until`` endings as written ((): opens only by ``unlock route``), and sid."""

    name: str
    title: str
    until: tuple[str, ...]
    sid: str
    label: str


class RouteIndex:
    """Every route of a ``Program`` in declaration order, read against one store."""

    __slots__ = ("_items", "_by_name", "_store", "_gates")

    def __init__(self, items: tuple[RouteInfo, ...], store: PersistentStore) -> None:
        self._items = items
        self._by_name = {info.name: info for info in items}
        self._store = store
        # (name, until as a set) per route, for open_names' one set test per route.
        self._gates = tuple((info.name, frozenset(info.until)) for info in items)

    @classmethod
    def build(cls, program: "Program", store: PersistentStore) -> "RouteIndex":
        return cls(tuple(RouteInfo(d.name, d.title, tuple(d.until), "route:" + d.name, d.name)
                         for d in program.routes), store)

    def get(self, name: object) -> RouteInfo | None:
        return self._by_name.get(name) if type(name) is str else None

    def has(self, name: object) -> bool:
        """The ``"route"`` kind's ``known`` recognizer."""
        return type(name) is str and name in self._by_name

    def __iter__(self) -> Iterator[RouteInfo]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def is_open(self, name: object) -> bool:
        """PR-F19-07: a declared route is open when ``unlock route`` recorded it, or when it
        has ``until`` endings and every one of them is reached. False for anything else."""
        info = self.get(name)
        return info is not None and (self._store.is_unlocked(ROUTE_KIND, info.name)
                                     or self._until_reached(info))

    def open_names(self) -> list[str]:
        """Every open route in declaration order (``persistent.routes``), as ``is_open``
        decides, with each kind read once and one subset test per route, so a cache-missing
        read at the limits (1,000 routes × 32 ``until``) stays near 1 ms (04 §11,
        AC-F19-33)."""
        store = self._store
        unlocked = set(store.unlocked(ROUTE_KIND))
        reached = set(store.unlocked(ENDING_KIND))
        return [name for name, until in self._gates
                if name in unlocked or (until and until <= reached)]

    def _until_reached(self, info: RouteInfo) -> bool:
        store = self._store
        return bool(info.until) and all(store.is_unlocked(ENDING_KIND, n) for n in info.until)


# --- The rollback pause (07 I-2; F14 07 I-13) -----------------------------------------------------

def ending_in_progress(interp: "Interpreter") -> bool:
    """F14's seam (04 §2 Q4, TR-F19-05): an ``ending`` runs now, from its unlock through every
    card phase and the ``then`` between them, until ``end_story`` clears ``current``."""
    from engine.runtime.interpreter import Status   # the interpreter imports this module
    status = interp.status
    return ((status is Status.RUNNING or status is Status.WAITING)
            and type(interp.current) is Ending)


ROLLBACK_PAUSES.append(ending_in_progress)


# --- The executors (04 §7.1, §7.2) ----------------------------------------------------------------

def _finish(interp: "Interpreter") -> "Step":
    """The card's ``after_hold``: no out phase; F10's story end fades over the card."""
    return interp.end_story()


def run_ending(interp: "Interpreter", stmt: Ending) -> "Step":
    """Record the ending (before anything is drawn, PR-F19-02), then the card's in and hold
    phases and the story's end; ``seconds`` 0 ends the story at once. F30 (04 §6.1 step 2):
    a window title set by the script goes back to the game's first (``WindowTitle(None)``)."""
    interp.persistent.unlock(ENDING_KIND, stmt.name)
    clear_title(interp)
    if stmt.seconds == 0:
        return interp.end_story()
    card = TitleCard(stmt.name, stmt.heading, stmt.title, kind=CARD_KIND)
    return play_card(interp, card, stmt.seconds, stmt.with_clause, after_hold=_finish)


def run_lock(interp: "Interpreter", stmt: Lock) -> "Step":
    """``unlock route n`` records ``n``; ``lock route n`` / ``lock ending n`` take it back
    (absent: nothing changes). No command, wait, or checkpoint. W132 in dev runs when a
    locked route stays open through its ``until`` endings, once per route per
    interpreter."""
    from engine.runtime.interpreter import Step     # the interpreter imports this module
    store = interp.persistent
    if stmt.unlock:
        store.unlock(stmt.kind, stmt.name)
        return Step.CONTINUE
    store.relock(stmt.kind, stmt.name)
    if (stmt.kind == ROUTE_KIND and interp.dev and stmt.name not in interp.routes_warned
            and interp.routes.is_open(stmt.name)):
        interp.routes_warned.add(stmt.name)
        info = interp.routes.get(stmt.name)
        assert info is not None
        text = format_message("W132", (stmt.name, info.until))
        warning = ScriptWarning(text, code="W132", file=stmt.file.ref, line=stmt.line)
        _story_log.warning("%s", warning.format(), extra={"code": "W132"})
    return Step.CONTINUE


# --- Registration and the views (04 §7.3, §7.4) ---------------------------------------------------

def _w131(store: PersistentStore, form: str, count: int = 0) -> None:
    """W131 (launch, area ``persist``), once per store per form; a count only (04 §8)."""
    logged = _w131_logged.setdefault(store, set())
    if form in logged:
        return
    logged.add(form)
    args = (form, count) if form == ENDINGS_VIEW else (form,)
    store.log.warning("%s", format_message("W131", args), extra={"code": "W131"})


def register(interp: "Interpreter") -> None:
    """Per interpreter (F39 calls it again with a new program): ``interp.endings`` and
    ``interp.routes``, then the store's kinds (``known`` = the indexes' ``has``; kinds
    before views, because migration unlocks), then the views. Safe to repeat on one store
    (07 I-1)."""
    store = interp.persistent
    endings = EndingIndex.build(interp.program)
    routes = RouteIndex.build(interp.program, store)
    interp.endings = endings
    interp.routes = routes
    store.register_kind(ENDING_KIND, known=endings.has, revocable=True)
    store.register_kind(ROUTE_KIND, known=routes.has, revocable=True)

    def endings_view() -> list[str]:
        return [n for n in store.unlocked(ENDING_KIND) if endings.has(n)]

    def routes_view() -> list[str]:
        return routes.open_names()

    def migrate_endings(value: Value) -> None:
        """PR-F19-14: each declared ending name in an older ``endings`` list is recorded as
        reached, quietly (no new-unlock entry); W131 with the count of those names."""
        names: dict[str, None] = {}
        if type(value) is list:
            for item in value:
                if type(item) is str and endings.has(item) and item not in names:
                    names[item] = None
                    store.unlock(ENDING_KIND, item, quiet=True, migrating=True)
        _w131(store, ENDINGS_VIEW, len(names))

    def migrate_routes(value: Value) -> None:
        """An older ``routes`` value is dropped (routes open with ``unlock route``)."""
        _w131(store, ROUTES_VIEW)

    store.register_view(ENDINGS_VIEW, endings_view, migrate=migrate_endings)
    store.register_view(ROUTES_VIEW, routes_view, migrate=migrate_routes)


__all__ = ["CARD_KIND", "ENDINGS_VIEW", "ENDING_KIND", "EndingIndex", "EndingInfo",
           "ROUTES_VIEW", "ROUTE_KIND", "RouteIndex", "RouteInfo", "ending_in_progress",
           "register", "run_ending", "run_lock"]
