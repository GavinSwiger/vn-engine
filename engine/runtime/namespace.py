"""The story namespace ``G`` (F03 ``04-technical.md`` §7.12; SR-F03-07, 08; PR-F03-17).

Why this module exists: every ``$`` line, condition, ``define``, and ``default`` runs in one
dict, and what a story can reach by name is decided here and nowhere else: its own names,
the engine names (``Character``, ``dice``, ``module``, ``persistent``), and a private copy
of Python's built-ins with the console functions replaced. No interpreter, program, or
state object is reachable by name (AC-F03-22).

F12 (step 3a): ``persistent`` is a ``PersistentNamespace`` over the launch's
``PersistentStore`` (``build_namespace(persistent=)``; a fresh in-memory store when none is
given). ``persistent_store(G)`` finds that store again (the interpreter's marks and step 3b).

F09 (04 §4.2): the transition constructors ``Dissolve``, ``Fade``, and ``Mask`` are bound as
engine names; ``Transition`` is reserved (``ENGINE_NAMES``) and never bound (F28).

F22 (SPEC §5 contract change 4): ``points`` is a ``PointsView`` with no ``Points`` yet, so a
define that reads it is E236; the interpreter binds it (``points.bind_view``). Not saved.

F21 (04 §3, 07 I-6): ``codex`` is a ``CodexReader`` with no ``Codex`` yet, so a define that
reads it is E256 form 1; the interpreter binds it (``codex.install``). Not saved.
"""

import builtins
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from engine.core.logsetup import get_logger
from engine.core.redact import echo
from engine.runtime.character import CharacterFactory
from engine.runtime.codex import CodexReader
from engine.runtime.dice import DiceFacade, Pcg32, make_dice
from engine.runtime.errors import ConsoleUnavailable
from engine.runtime.modules import make_module
from engine.runtime.persistent import PersistentNamespace, PersistentStore, store_of
from engine.runtime.points import PointsView
from engine.runtime.transitions import CONSTRUCTORS
from engine.script.nodes import PyCode
from engine.script.program import Program

# The PCG32 core behind each namespace's ``dice`` facade, keyed by the facade's id. The
# facade is kept in the entry, so an id is never reused while its entry exists.
_CORES: dict[int, tuple[DiceFacade, Pcg32]] = {}
# The ``Running`` slot of each namespace, keyed by the id of its built-ins dict (kept in the
# entry, so the id is never reused while the entry exists).
_RUNNING: dict[int, tuple[dict, "Running"]] = {}


class Running:
    """Which piece of author Python runs now: set by the interpreter and the launch phase
    before each ``$`` line, condition, default, and define, and read by ``print`` to name
    its file and line (PR-F03-31). Holds no story state."""

    __slots__ = ("file", "piece")

    def __init__(self) -> None:
        self.file: str | None = None
        self.piece: PyCode | None = None

    def set(self, file: str, piece: PyCode) -> None:
        self.file = file
        self.piece = piece

    def location(self, frame) -> str | None:
        """``script/main.vns, line 8`` for the running piece: its line plus the line of
        the outermost frame of its own code above ``frame`` (a continued piece names the
        exact line, SR-F03-29); None when nothing runs."""
        piece, file = self.piece, self.file
        if piece is None or file is None:
            return None
        line = piece.line
        code = piece.code
        while frame is not None:
            if frame.f_code is code:
                line = piece.line + max(frame.f_lineno or 1, 1) - 1
                break
            frame = frame.f_back
        return f"{file}, line {line}"


def _console(name: str) -> Callable[..., object]:
    def refused(*args: object, **kwargs: object) -> object:
        raise ConsoleUnavailable(name)

    refused.__qualname__ = refused.__name__ = name
    return refused


def _closer(name: str) -> Callable[..., object]:
    def close(*args: object, **kwargs: object) -> object:
        raise SystemExit(*args)

    close.__qualname__ = close.__name__ = name
    return close


def _printer(dev: bool, log: logging.Logger, running: Running) -> Callable[..., None]:
    """``print``: dev runs log one INFO record (``runtime``) ``<file>, line <N>: print:
    <text>`` with the text through ``echo()`` (PR-F03-31, SR-F03-28); release runs print
    and log nothing."""

    def print_(*args: object, sep: object = " ", end: object = "\n", **kwargs: object) -> None:
        if not dev:
            return
        text = (sep if isinstance(sep, str) else " ").join(str(a) for a in args)
        at = running.location(sys._getframe(1))
        if at is None:
            log.info("print: %s", echo(text))
        else:
            log.info("%s: print: %s", at, echo(text))

    print_.__qualname__ = print_.__name__ = "print"
    return print_


def build_namespace(program: Program, *, dev: bool = False, log: logging.Logger | None = None,
                    game_has: Callable[[str], bool] = lambda ref: False,
                    game_root: Path | None = None,
                    persistent: PersistentStore | None = None) -> dict[str, object]:
    """A fresh ``G`` for one launch. Its ``dice`` is not ready until a game starts
    (``Pcg32.ready`` False, E85k for a define that uses it). ``persistent`` is the session's
    store (F12); None gives an empty in-memory one."""
    if persistent is None:
        persistent = PersistentStore(identity_scheme=program.identity_scheme)
    log = log if log is not None else get_logger("runtime")
    b = dict(builtins.__dict__)
    running = Running()
    _RUNNING[id(b)] = (b, running)
    b["print"] = _printer(dev, log, running)
    for name in ("input", "breakpoint", "help"):
        b[name] = _console(name)
    for name in ("exit", "quit"):
        b[name] = _closer(name)
    core = Pcg32()
    dice = make_dice(core)
    _CORES[id(dice)] = (dice, core)
    return {
        "__builtins__": b,
        "Character": CharacterFactory(program.default_names),
        "dice": dice,
        "module": make_module(game_has, game_root=game_root),
        "persistent": PersistentNamespace(persistent),
        "points": PointsView(),                         # F22: bound by the interpreter
        "codex": CodexReader(),                         # F21: bound by the interpreter
        **CONSTRUCTORS,                                 # F09: Dissolve, Fade, Mask
    }


def dice_core(G: dict[str, object]) -> Pcg32 | None:
    """The PCG32 core behind ``G["dice"]``, or None when ``G`` wasn't built here."""
    entry = _CORES.get(id(G.get("dice")))
    if entry is None or entry[0] is not G.get("dice"):
        return None
    return entry[1]


def persistent_store(G: dict[str, object]) -> PersistentStore | None:
    """The store behind ``G["persistent"]`` (F12), or None when ``G`` has no facade."""
    return store_of(G.get("persistent"))


def running_slot(G: dict[str, object]) -> Running | None:
    """The ``Running`` slot of ``G``, or None when ``G`` wasn't built here (or the story
    replaced its ``__builtins__``)."""
    b = G.get("__builtins__")
    entry = _RUNNING.get(id(b))
    if entry is None or entry[0] is not b:
        return None
    return entry[1]


def install_dice(G: dict[str, object]) -> Pcg32:
    """Give a hand-built ``G`` a fresh ``dice`` (tests and tools)."""
    core = Pcg32()
    dice = make_dice(core)
    _CORES[id(dice)] = (dice, core)
    G["dice"] = dice
    return core


__all__ = ["Running", "build_namespace", "dice_core", "install_dice", "persistent_store",
           "running_slot"]
