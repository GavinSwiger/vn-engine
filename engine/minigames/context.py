"""A plugin's ``Context`` and its thread-checked handles (F23 ``04`` §4.3, SEC-F23-11).

Why this module exists: plugins are trusted code, but the engine's own rule (ADR-0007) is
that only the main thread touches engine state. A plugin that starts a thread and calls the
API from it would break that silently, so every object a plugin can reach from its
``Context`` is a thin ``ThreadBound`` wrapper: each public method and property first compares
``threading.get_ident()`` with the main thread the loader captured, and raises
``MinigameThreadError`` otherwise (the host maps it to E275). Engine objects are never handed
out unwrapped: the ledger, settings, theme, words, audio, focus scope, and painter reach the
plugin only through these wrappers.

The wrappers hold *ports*, plain objects the host (step 4) builds over the session's ledger,
dice, theme, words, and audio. This module defines what each port must offer; it imports no
host code, so the wrappers can be tested on their own (AC-F23-53).
"""

import functools
import inspect
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from types import FunctionType
from typing import Any, Protocol

from engine.core.minigame_types import StoryNames

_NO_NAMES = StoryNames((), (), ())


@dataclass(frozen=True, slots=True)
class PlayerSettings:
    """What a plugin learns of the player's settings (PR-F23-19): plain values, a fresh
    snapshot per read (``ctx.settings``, ``Minigame.settings_changed``)."""

    text_scale: float = 1.0
    reduce_motion: bool = False
    master_volume: int = 100
    music_volume: int = 100
    sound_volume: int = 100
    voice_volume: int = 100


class MinigameThreadError(RuntimeError):
    """A plugin called the minigame API from a thread other than the main thread."""


def _checked(fn: Callable[..., Any], label: str) -> Callable[..., Any]:
    @functools.wraps(fn)
    def method(self: "ThreadBound", *args: Any, **kwargs: Any) -> Any:
        if threading.get_ident() != self._main:
            raise MinigameThreadError(
                f"{label} was called from another thread; the minigame API works only on the "
                "main thread.")
        return fn(self, *args, **kwargs)

    method.__thread_checked__ = True        # type: ignore[attr-defined]
    return method


class ThreadBound:
    """Base of every object a plugin can reach. Subclasses define public methods and
    properties as usual; ``__init_subclass__`` wraps each one with the thread check, so a
    method added later is covered automatically. State lives in private slots only."""

    __slots__ = ("_main",)

    def __init__(self, main: int) -> None:
        self._main = main

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, value in list(vars(cls).items()):
            if name.startswith("_"):
                continue
            label = f"{cls.__name__}.{name}"
            if isinstance(value, FunctionType):
                setattr(cls, name, _checked(value, label))
            elif isinstance(value, property):
                setattr(cls, name, property(
                    None if value.fget is None else _checked(value.fget, label),
                    None if value.fset is None else _checked(value.fset, label),
                    None, value.__doc__))


def public_members(obj: object) -> list[str]:
    """Every public method and property of ``obj``'s class (for AC-F23-53's walk)."""
    found = []
    for name in dir(type(obj)):
        if name.startswith("_"):
            continue
        attr = inspect.getattr_static(type(obj), name)
        if isinstance(attr, (FunctionType, property)):
            found.append(name)
    return found


# --- Generic wrapper for engine objects defined by other features ------------------------------

_BOUND_TYPES: dict[type, type] = {}

# Instance data a plugin may read through ``bind`` (API 1.1, additive): read-only, checked
# properties. Keyed by the class's module and name so this module imports no UI code.
_READ_FIELDS: dict[str, tuple[str, ...]] = {
    "engine.ui.focus.FocusScope": ("focused",),                       # ctx.scope.focused
    "engine.ui.builtin.codex_page.CodexView": ("groups_changed",),    # codex_view(...)
}


def _forward(name: str) -> Callable[..., Any]:
    def method(self: Any, *args: Any, **kwargs: Any) -> Any:
        return getattr(self._target, name)(*args, **kwargs)
    method.__name__ = name
    return method


def _forward_property(name: str) -> property:
    def read(self: Any) -> Any:
        return getattr(self._target, name)
    read.__name__ = name
    return property(read)


def bind(obj: object, main: int) -> ThreadBound:
    """A ``ThreadBound`` wrapper exposing ``obj``'s public methods and properties (F10's
    ``FocusScope`` and ``Painter``, F08's music handle, F21's codex view), each checked.
    One wrapper class per wrapped class, built by introspection, so a method a later feature
    adds is covered. Instance data attributes are not exposed, except the few listed in
    ``_READ_FIELDS`` (``FocusScope.focused``, ``CodexView.groups_changed``), which become
    read-only checked properties."""
    kind = type(obj)
    wrapper = _BOUND_TYPES.get(kind)
    if wrapper is None:
        namespace: dict[str, Any] = {"__slots__": ("_target",)}
        for name in dir(kind):
            if name.startswith("_"):
                continue
            attr = inspect.getattr_static(kind, name)
            if isinstance(attr, property):
                namespace[name] = _forward_property(name)
            elif callable(attr) or isinstance(attr, (staticmethod, classmethod)):
                namespace[name] = _forward(name)
        for name in _READ_FIELDS.get(f"{kind.__module__}.{kind.__qualname__}", ()):
            namespace.setdefault(name, _forward_property(name))
        wrapper = type(f"Bound{kind.__name__}", (ThreadBound,), namespace)
        _BOUND_TYPES[kind] = wrapper
    bound = wrapper(main)
    bound._target = obj                          # type: ignore[attr-defined]
    return bound


# --- Ports (what the host supplies) ------------------------------------------------------------

class PointsPort(Protocol):
    def get(self, name: str) -> int: ...
    def names(self) -> tuple[str, ...]: ...
    def highest(self) -> object: ...
    def add(self, name: str, n: int) -> object: ...
    def set(self, name: str, n: int) -> object: ...


class CodexPort(Protocol):
    def tips(self) -> tuple[str, ...]: ...
    def items(self) -> tuple[str, ...]: ...
    def has(self, kind: str, name: str | None = None) -> bool: ...
    def give(self, name: str) -> object: ...
    def take(self, name: str) -> object: ...
    def unlock_tip(self, name: str) -> object: ...
    def title(self, name: str) -> str:
        """(F27 A9; F23 SPEC I-21) A declared item's or tip's title, held or not. Not
        exactly a ``str``: ``TypeError``; undeclared: F21's ``UnknownEntry`` (the host
        reports both as E275). Reads no ledger and changes nothing."""
        ...


class ReaderPort(Protocol):
    """Theme tokens or words: ``get`` reads an engine key, ``mine`` reads
    ``plugin.<name>.<key>``."""
    def get(self, key: str) -> object: ...
    def mine(self, key: str) -> object: ...


class ContextPort(Protocol):
    """The host's side of ``Context`` (step 4). Every asset call resolves only through
    ``ImageIndex``, ``GuiImageRef``, F08's audio-ref rule, and ``GamePaths`` (SEC-F23-10)."""
    def settings(self) -> object: ...
    def area(self) -> object: ...
    def image(self, name: str) -> object: ...
    def gui_image(self, ref: str) -> object: ...
    def font(self, ref: str, size: int) -> object: ...
    def play_sound(self, file: str, volume: int) -> object: ...
    def music(self) -> object: ...
    def play_ui(self, token: str) -> object: ...
    def heading(self, on: bool, text: str | None) -> None: ...
    def hint(self, text: str) -> None: ...
    def cue_point(self, at: object) -> None: ...
    def confirm(self, word: str, on_yes: Callable[[], object],
                on_no: Callable[[], object] | None) -> None: ...
    def codex_view(self, filter: object, pick: object) -> object: ...
    def finish(self, result: object) -> None: ...


# --- Handles -------------------------------------------------------------------------------

class PointsHandle(ThreadBound):
    """``ctx.points``: reads include the session's pending changes; ``add`` and ``set``
    are requests kept in the ledger (PR-F23-15–17)."""

    __slots__ = ("_port",)

    def __init__(self, main: int, port: PointsPort) -> None:
        super().__init__(main)
        self._port = port

    def get(self, name):
        return self._port.get(name)

    def names(self):
        return self._port.names()

    def highest(self):
        return self._port.highest()

    def add(self, name, n):
        return self._port.add(name, n)

    def set(self, name, n):
        return self._port.set(name, n)


class CodexHandle(ThreadBound):
    """``ctx.codex``: reads include pending changes; ``give``, ``take``, ``unlock_tip`` are
    requests kept in the ledger; ``title`` (F27 A9) reads a declared title."""

    __slots__ = ("_port",)

    def __init__(self, main: int, port: CodexPort) -> None:
        super().__init__(main)
        self._port = port

    def tips(self):
        return self._port.tips()

    def items(self):
        return self._port.items()

    def has(self, kind, name=None):
        return self._port.has(kind, name)

    def give(self, name):
        return self._port.give(name)

    def take(self, name):
        return self._port.take(name)

    def unlock_tip(self, name):
        return self._port.unlock_tip(name)

    def title(self, name):
        """(F27 A9) A declared item's or tip's title, held or not; the port refuses a
        non-``str`` or undeclared name (E275). A read: no ledger request."""
        return self._port.title(name)


class DiceHandle(ThreadBound):
    """``ctx.random``: the runtime's ``DiceFacade`` over the session's own ``Pcg32``."""

    __slots__ = ("_dice",)

    def __init__(self, main: int, dice: Any) -> None:
        super().__init__(main)
        self._dice = dice

    def roll(self, *args, **kwargs):
        return self._dice.roll(*args, **kwargs)

    def pick(self, *args, **kwargs):
        return self._dice.pick(*args, **kwargs)

    def decimal(self, *args, **kwargs):
        return self._dice.decimal(*args, **kwargs)

    def shuffle(self, *args, **kwargs):
        return self._dice.shuffle(*args, **kwargs)


class ThemeReader(ThreadBound):
    """``ctx.theme``: theme tokens; ``mine(key)`` reads ``plugin.<name>.<key>``."""

    __slots__ = ("_port",)

    def __init__(self, main: int, port: ReaderPort) -> None:
        super().__init__(main)
        self._port = port

    def get(self, key):
        return self._port.get(key)

    def mine(self, key):
        return self._port.mine(key)


class WordsReader(ThemeReader):
    """``ctx.words``: words; ``mine(key)`` reads ``[words.plugin.<name>] <key>``."""

    __slots__ = ()

    def get(self, key):
        return self._port.get(key)

    def mine(self, key):
        return self._port.mine(key)


def _plain_copy(value: object) -> object:
    """A deep copy of a frozen value (lists and dicts only hold built-ins)."""
    if type(value) is list:
        return [_plain_copy(v) for v in value]
    if type(value) is dict:
        return {k: _plain_copy(v) for k, v in value.items()}
    return value


class Context(ThreadBound):
    """The plugin's only handle on the engine (F23 ``04`` §4.3). Built by the host per
    session; every attribute is a checked property and every call checks the thread."""

    __slots__ = ("_port", "_args", "_points", "_codex", "_random", "_theme", "_words",
                 "_scope", "_painter", "_dev", "_log", "_story")

    def __init__(self, main: int, *, port: ContextPort, args: dict, points: PointsPort,
                 codex: CodexPort, dice: Any, theme: ReaderPort, words: ReaderPort,
                 scope: object, painter: object, dev: bool, log: logging.Logger,
                 story: StoryNames = _NO_NAMES) -> None:
        super().__init__(main)
        self._port = port
        self._args = _plain_copy(dict(args))
        self._points = PointsHandle(main, points)
        self._codex = CodexHandle(main, codex)
        self._random = DiceHandle(main, dice)
        self._theme = ThemeReader(main, theme)
        self._words = WordsReader(main, words)
        self._scope = bind(scope, main)
        self._painter = bind(painter, main)
        self._dev = bool(dev)
        self._log = log
        self._story = story

    # --- Data ---------------------------------------------------------------------------

    @property
    def args(self):
        return self._args

    @property
    def random(self):
        return self._random

    @property
    def points(self):
        return self._points

    @property
    def codex(self):
        return self._codex

    @property
    def settings(self):
        return self._port.settings()

    @property
    def area(self):
        return self._port.area()

    @property
    def scope(self):
        return self._scope

    @property
    def painter(self):
        return self._painter

    @property
    def theme(self):
        return self._theme

    @property
    def words(self):
        return self._words

    @property
    def dev(self):
        return self._dev

    @property
    def log(self):
        return self._log

    @property
    def story(self):
        """The story's declared names (F25 A5; F23 SPEC I-20): the host passes
        ``StartMinigame.names``. Frozen plain values, so the same object, not a copy."""
        return self._story

    # --- Calls --------------------------------------------------------------------------

    def image(self, name):
        return self._port.image(name)

    def gui_image(self, ref):
        return self._port.gui_image(ref)

    def font(self, ref, size):
        return self._port.font(ref, size)

    def play_sound(self, file, *, volume=100):
        return self._port.play_sound(file, volume)

    def music(self):
        return bind(self._port.music(), self._main)

    def play_ui(self, token):
        return self._port.play_ui(token)

    def heading(self, on, text=None):
        return self._port.heading(on, text)

    def hint(self, text):
        return self._port.hint(text)

    def cue_point(self, at):
        return self._port.cue_point(at)

    def confirm(self, word, on_yes, on_no=None):
        return self._port.confirm(word, on_yes, on_no)

    def codex_view(self, *, filter, pick=None):
        return bind(self._port.codex_view(filter, pick), self._main)

    def finish(self, result):
        return self._port.finish(result)


__all__ = ["CodexHandle", "Context", "ContextPort", "DiceHandle", "MinigameThreadError",
           "PlayerSettings", "PointsHandle", "ThemeReader", "ThreadBound", "WordsReader", "bind",
           "public_members"]
