"""Achievements at run time (F37 ``SPEC.md`` §5.1; F36 ``07-architecture-review.md`` I-12 to
I-15).

Why this module exists: an achievement is kept across playthroughs, a name in F12's
**non-revocable** unlock kind ``"achievement"`` (no ``lock`` can take it back; only F16's
"delete persistent data" clears it). It is given in two ways: an ``unlock achievement`` line,
which goes through F19's one ``Lock`` executor (``endings.run_lock``, 07 I-12: this module has
no executor), or a ``when`` condition, checked here.

- ``AchievementIndex`` (``interp.achievements.index``): every declaration in declaration
  order (``Program.achievements``, F37-S2), immutable; ``has`` is the kind's ``known``
  recognizer, so undeclared names on file are never shown or counted and give way in a full
  kind.
- ``Achievements`` (``interp.achievements``): the index, the store, and the **pending** list
  (the locked declarations with ``when``, in declaration order). ``check_pending(test,
  guard)`` evaluates each pending condition once (one guard entry each, through the
  interpreter's ``_test``), unlocks the true ones in declaration order and drops them, and
  drops a condition that raises or trips the watchdog with W223, once, for the rest of the
  session (``failed``). A pending name unlocked another way (a line, F40's console) is
  dropped without being evaluated. After F16's reset (``store.reset_count`` moved) the
  pending list is made again from the locked ones, the failed ones still left out.
- ``register(interp)`` (07 I-13; called from ``Interpreter.__init__`` by F37-S2, after
  F36's line): ``interp.achievements`` and the store's kind (``known=``, not revocable,
  ``replay_keeps=True``: achievements earned in a replay are kept). Safe to repeat on one
  store (F39 with a new program).
- ``check_pending(interp)``: the interpreter's call (07 I-14: in ``take_checkpoint`` before
  the snapshot and in ``_end``, both skipped while ``timeline.replaying``; F37-S2 wires it).

W223's text is ``w223_text`` here until F37-S2 moves it into ``script/messages.py`` (a
serial-lane file; 07 I-15). It prints only the achievement's script name and the
exception's type name (SPEC §6 item 2).

Layering (as ``endings.py``): below the interpreter, importing it only under
``TYPE_CHECKING``. Pure (TR-F03-05): no file, clock, randomness, thread, or network.
"""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from engine.core.logsetup import get_logger
from engine.runtime.guard import AuthorCodeGuard
from engine.runtime.persistent import PersistentStore
from engine.script.diagnostics import ScriptWarning

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter

ACHIEVEMENT_KIND: Final = "achievement"     # F12 unlock kind (not revocable)
IDENTITY_PREFIX: Final = "achievement:"     # SPEC §5.1: an achievement's identity
TOO_LONG: Final = "it ran too long"         # W223's reason for the watchdog

_story_log = get_logger("story")            # W223 (run)


class AchievementDeclLike(Protocol):
    """A declaration as ``Program.achievements`` holds it (F37-S2's ``AchievementDecl``):
    ``when`` is the condition as written (None: given only by a line), ``when_code`` it
    compiled once at load; ``file.ref`` and ``line`` place W223."""

    name: str
    title: str
    description: str
    image: str | None
    hidden: bool
    when: str | None
    when_code: object
    line: int

    @property
    def file(self) -> object: ...


@dataclass(frozen=True, slots=True)
class AchievementInfo:
    """One declared achievement: its name, texts as shown, icon image name (None: the
    frame), whether it is hidden until unlocked, and its condition (text and code)."""

    name: str
    title: str
    description: str = ""
    image: str | None = None
    hidden: bool = False
    when: str | None = None
    when_code: object = None
    file: str | None = None
    line: int | None = None

    @property
    def identity(self) -> str:
        return IDENTITY_PREFIX + self.name

    @property
    def automatic(self) -> bool:
        return self.when_code is not None


def info_of(decl: AchievementDeclLike) -> AchievementInfo:
    file = getattr(decl, "file", None)
    ref = getattr(file, "ref", None)
    return AchievementInfo(decl.name, decl.title, decl.description, decl.image,
                           bool(decl.hidden), decl.when, decl.when_code,
                           ref if type(ref) is str else None, decl.line)


class AchievementIndex:
    """Every achievement of a ``Program`` in declaration order (immutable). Lookups take any
    value and give None/False for anything that isn't a declared name."""

    __slots__ = ("_items", "_by_name")

    def __init__(self, items: Iterable[AchievementInfo]) -> None:
        self._items = tuple(items)
        self._by_name = {info.name: info for info in self._items}

    @classmethod
    def build(cls, program: object) -> "AchievementIndex":
        """From ``program.achievements`` (F37-S2); a program without them has none."""
        return cls(info_of(d) for d in getattr(program, "achievements", ()))

    def get(self, name: object) -> AchievementInfo | None:
        return self._by_name.get(name) if type(name) is str else None   # type: ignore[arg-type]

    def has(self, name: object) -> bool:
        """The ``"achievement"`` kind's ``known`` recognizer."""
        return type(name) is str and name in self._by_name

    def __iter__(self) -> Iterator[AchievementInfo]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def unlocked(self, store: PersistentStore) -> tuple[AchievementInfo, ...]:
        """The declared achievements the store holds, in declaration order."""
        held = set(store.unlocked(ACHIEVEMENT_KIND))
        return tuple(info for info in self._items if info.name in held)


def w223_text(name: str, reason: str) -> str:
    """W223 L run (SPEC §3). ``reason`` is the exception's type name or ``TOO_LONG``."""
    return (f"achievement {name}'s when condition failed ({reason}), so it isn't checked "
            "again until the game restarts.")


class Achievements:
    """The launch's achievements against one store (module docstring). Main thread only."""

    __slots__ = ("index", "_store", "_pending", "_reset_count", "failed", "evaluations")

    def __init__(self, index: AchievementIndex, store: PersistentStore) -> None:
        self.index = index
        self._store = store
        self.failed: set[str] = set()       # W223 given: never checked again this session
        self.evaluations = 0                # conditions evaluated (tests, AC-F37-14)
        self._pending: list[AchievementInfo] = []
        self._reset_count = -1
        self._rebuild()

    def _rebuild(self) -> None:
        store = self._store
        self._reset_count = store.reset_count
        self._pending = [info for info in self.index
                         if info.automatic and info.name not in self.failed
                         and not store.is_unlocked(ACHIEVEMENT_KIND, info.name)]

    @property
    def pending(self) -> tuple[str, ...]:
        """The names still checked at checkpoints, in declaration order."""
        if self._store.reset_count != self._reset_count:
            self._rebuild()
        return tuple(info.name for info in self._pending)

    def is_unlocked(self, name: str) -> bool:
        return self._store.is_unlocked(ACHIEVEMENT_KIND, name)

    def check_pending(self, test: Callable[[object], bool],
                      guard: AuthorCodeGuard) -> tuple[str, ...]:
        """Evaluate each pending condition with ``test`` (the interpreter's ``_test``: one
        guard entry each); unlock the true ones in declaration order. A condition that raises
        (an ``Exception``) or that the watchdog stopped gives W223 once and is dropped; a
        real Ctrl+C goes on up. Returns the names unlocked now."""
        store = self._store
        if store.reset_count != self._reset_count:
            self._rebuild()
        pending = self._pending
        if not pending:
            return ()
        unlocked: list[str] = []
        keep: list[AchievementInfo] = []
        for info in pending:
            if store.is_unlocked(ACHIEVEMENT_KIND, info.name):
                continue                                   # given by a line meanwhile
            self.evaluations += 1
            try:
                true = test(info.when_code)
            except KeyboardInterrupt:
                if not guard.consume_fired():
                    raise
                self._fail(info, TOO_LONG)
                continue
            except Exception as exc:                       # author code: W223, not E85
                self._fail(info, type(exc).__name__)
                continue
            if true:
                store.unlock(ACHIEVEMENT_KIND, info.name)
                unlocked.append(info.name)
            else:
                keep.append(info)
        self._pending = keep
        return tuple(unlocked)

    def _fail(self, info: AchievementInfo, reason: str) -> None:
        self.failed.add(info.name)
        warning = ScriptWarning(w223_text(info.name, reason), code="W223", file=info.file,
                                line=info.line)
        _story_log.warning("%s", warning.format(), extra={"code": "W223"})


def register(interp: "Interpreter") -> Achievements:
    """Per interpreter (F39 calls it again with a new program): ``interp.achievements`` and
    the store's ``"achievement"`` kind (``known`` = the index's ``has``; not revocable;
    kept through a replay). Safe to repeat on one store."""
    store = interp.persistent
    index = AchievementIndex.build(interp.program)
    store.register_kind(ACHIEVEMENT_KIND, known=index.has, revocable=False, replay_keeps=True)
    achievements = Achievements(index, store)
    interp.achievements = achievements      # type: ignore[attr-defined]  (F37-S2 declares it)
    return achievements


def check_pending(interp: "Interpreter") -> tuple[str, ...]:
    """The interpreter's checkpoint and story-end step (07 I-14; the caller skips it while
    ``timeline.replaying``)."""
    achievements: Achievements = interp.achievements  # type: ignore[attr-defined]
    return achievements.check_pending(interp._test, interp.guard)


__all__ = ["ACHIEVEMENT_KIND", "AchievementDeclLike", "AchievementIndex", "AchievementInfo",
           "Achievements", "IDENTITY_PREFIX", "TOO_LONG", "check_pending", "info_of",
           "register", "w223_text"]
