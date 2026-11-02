"""Saveable story values: ``freeze``, its untrusted twin, and kinds in words.

Why this module exists: a checkpoint must copy every story variable and check that it can
be saved, in one walk (F03 ``04-technical.md`` §7.4, invariant 2). The same rules bound a
state read back from JSON (§9.1), and the error messages name a value's kind in plain words
(SR-F03-33).

Story variables hold exactly: ``None``, ``bool``, ``int`` (fewer than 4,301 digits), finite
``float``, ``str``, ``list``, and ``dict`` with ``str`` keys, nested at most
``STATE_MAX_DEPTH`` levels. Types are exact: a subclass of any of them is refused.
"""

import math
from types import (BuiltinFunctionType, FunctionType, MethodDescriptorType, MethodType,
                   MethodWrapperType, ModuleType, WrapperDescriptorType)
from typing import TypeAlias

from engine.runtime.limits import INT_LIMIT, STATE_MAX_DEPTH, STATE_MAX_ITEMS

Value: TypeAlias = "None | bool | int | float | str | list[Value] | dict[str, Value]"

# Unsaveable reasons (one per E85e form, 02-script.md §5).
KIND = "kind"            # set, tuple, function, module, Character, dice, other objects
KEY = "key"              # a dict key that isn't exact str
NAN = "nan"
INF = "inf"
TOO_DEEP = "too_deep"    # nested more than STATE_MAX_DEPTH levels, or contains itself
BIG_INT = "big_int"      # 4,301 digits or more
TOO_MANY = "too_many"    # untrusted input only: more than STATE_MAX_ITEMS members

_NONE = type(None)
_BIG_BITS = INT_LIMIT.bit_length()   # below this, abs(v) < INT_LIMIT for sure
_I62 = 2**62                         # list/dict members inside ±2**62 skip the freeze call
_SCALARS = frozenset((_NONE, bool, int, float, str))


class Unsaveable(Exception):
    """A value that can't be stored in a story variable (E85e).

    ``reason`` is one of the constants above; ``value`` is the offending value (the key for
    ``KEY``); ``path`` is the way from the variable to it (``("bag", 2)`` for
    ``inventory["bag"][2]``), built only on failure. ``TOO_DEEP`` has no path: the message
    names the variable. The text never contains the value."""

    def __init__(self, reason: str, value: object) -> None:
        super().__init__(f"value can't be saved ({reason})")
        self.reason = reason
        self.value = value
        self._parts: list[str | int] = []   # innermost first, while unwinding
        self._at: object = value            # the object whose freeze raised

    @property
    def path(self) -> tuple[str | int, ...]:
        return tuple(reversed(self._parts))

    @property
    def kind(self) -> str:
        """The kind words of the offending value (for ``KEY``, of the key)."""
        return kind_words(self.value)

    def path_text(self, name: str) -> str:
        """``inventory["bag"][2]`` for variable ``inventory`` (SR-F03-10)."""
        out = [name]
        for part in self.path:
            if type(part) is int:
                out.append(f"[{part}]")
            else:
                escaped = part.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'["{escaped}"]')
        return "".join(out)

    def _locate(self, container: list | dict) -> None:
        """Add the index or key under ``container`` that holds the failed object."""
        if self.reason == TOO_DEEP or self._at is container:
            return
        at = self._at
        items = enumerate(container) if type(container) is list else container.items()
        for key, item in items:
            if item is at:
                self._parts.append(key)
                break
        self._at = container


def freeze(v: object, depth: int = 0) -> Value:
    """A deep copy of ``v`` that shares no list or dict with it, after checking that it can
    be saved; raises ``Unsaveable``. One pass; called by ``take_checkpoint`` for each story
    variable. Trusted input (author values): sizes are capped only by depth and digits."""
    t = type(v)
    if t is str or t is bool or v is None:
        return v
    if t is int:
        if v.bit_length() >= _BIG_BITS and abs(v) >= INT_LIMIT:
            raise Unsaveable(BIG_INT, v)
        return v
    if t is float:
        if math.isfinite(v):
            return v
        raise Unsaveable(NAN if v != v else INF, v)
    if t is list or t is dict:
        if depth >= STATE_MAX_DEPTH:
            raise Unsaveable(TOO_DEEP, v)
        d = depth + 1
        try:
            if t is list:
                return [x if ((u := type(x)) is str or (u is int and -_I62 < x < _I62)
                              or u is bool or x is None) else freeze(x, d) for x in v]
            out = {}
            for k, x in v.items():
                if type(k) is not str:
                    error = Unsaveable(KEY, k)
                    error._at = v
                    raise error
                out[k] = x if ((u := type(x)) is str or (u is int and -_I62 < x < _I62)
                               or u is bool or x is None) else freeze(x, d)
            return out
        except Unsaveable as error:
            error._locate(v)
            raise
    raise Unsaveable(KIND, v)


def freeze_untrusted(v: object, budget: list[int]) -> Value:
    """``freeze`` for a value read from a saved state (§9.1). Also counts list and dict
    members against ``budget[0]`` (shared by all variables of one state, starting at
    ``STATE_MAX_ITEMS``); going below zero raises ``Unsaveable(TOO_MANY)``."""
    return _freeze_counted(v, 0, budget)


def new_item_budget() -> list[int]:
    """A fresh member budget for one untrusted state."""
    return [STATE_MAX_ITEMS]


def _freeze_counted(v: object, depth: int, budget: list[int]) -> Value:
    t = type(v)
    if t is list or t is dict:
        if depth >= STATE_MAX_DEPTH:
            raise Unsaveable(TOO_DEEP, v)
        budget[0] -= len(v)
        if budget[0] < 0:
            raise Unsaveable(TOO_MANY, None)
        d = depth + 1
        try:
            if t is list:
                return [x if ((u := type(x)) is str or (u is int and -_I62 < x < _I62)
                              or u is bool or x is None) else _freeze_counted(x, d, budget)
                        for x in v]
            out = {}
            for k, x in v.items():
                if type(k) is not str:
                    error = Unsaveable(KEY, k)
                    error._at = v
                    raise error
                out[k] = x if ((u := type(x)) is str or (u is int and -_I62 < x < _I62)
                               or u is bool or x is None) else _freeze_counted(x, d, budget)
            return out
        except Unsaveable as error:
            if error.reason != TOO_MANY:
                error._locate(v)
            raise
    return freeze(v, depth)


def plain_copy(v: Value) -> Value:
    """A deep copy of an already frozen value (no checks). Snapshots are read-only by
    contract; this is how ``GameState.to_json`` hands out copies."""
    t = type(v)
    if t is list:
        return [x if type(x) in _SCALARS else plain_copy(x) for x in v]
    if t is dict:
        return {k: (x if type(x) in _SCALARS else plain_copy(x)) for k, x in v.items()}
    return v


def same_value(a: object, b: object) -> bool:
    """Equality by value and exact type at every level: ``1``, ``1.0``, and ``True`` differ,
    and so do ``0.0`` and ``-0.0``. Dicts compare as mappings (order ignored)."""
    t = type(a)
    if t is not type(b):
        return False
    if t is float:
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    if t is list:
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    if t is dict:
        return len(a) == len(b) and all(k in b and same_value(x, b[k]) for k, x in a.items())
    return a == b


# --- Kinds in words (SR-F03-33) -----------------------------------------------------------

_EXACT_KINDS: dict[type, str] = {
    _NONE: "nothing (None)",
    bool: "True or False",
    int: "a whole number",
    float: "a decimal number",
    str: "text",
    list: "a list",
    dict: "a dictionary",
    tuple: "a tuple",
    set: "a set",
    frozenset: "a set",
}
_FUNCTION_TYPES = (FunctionType, BuiltinFunctionType, MethodType, MethodWrapperType,
                   WrapperDescriptorType, MethodDescriptorType)
_ENGINE_KINDS: dict[type, str] = {}


def register_kind(cls: type, words: str) -> None:
    """Name an engine class and its subclasses in words (``dice.py``: "the dice";
    ``character.py``: "a character"). One explicit call per owning module."""
    _ENGINE_KINDS[cls] = words


def kind_words(v: object) -> str:
    """SR-F03-33: the kind of ``v`` in words, by exact type for the built-in kinds, so a
    ``str`` subclass is ``a Python object (Name)``."""
    t = type(v)
    words = _EXACT_KINDS.get(t)
    if words is not None:
        return words
    if _ENGINE_KINDS:
        for base in t.__mro__:
            words = _ENGINE_KINDS.get(base)
            if words is not None:
                return words
    if isinstance(v, _FUNCTION_TYPES):
        return "a function"
    if isinstance(v, ModuleType):
        return "a module"
    return f"a Python object ({t.__name__})"
