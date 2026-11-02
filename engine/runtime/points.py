"""Meters at run time (F22 SPEC §5; 07 I-1, I-5 to I-8, I-10).

Why this module exists: meters are whole numbers in ``GameState``, so they save, load, and roll
back like variables, but they change only through one door, ``Points``, which checks the name,
the type, and the range the same way for the ``points`` line, F23/F24 plugins, and F40's
console. Author Python only reads them, through ``PointsView``.

- ``Points`` (``interp.points``; plain data, main thread only): ``names()``, ``spec(name)``,
  ``get``, ``add -> int``, ``set -> int``, ``highest(*names) -> str``. An unknown name is
  ``UnknownMeter`` (a ``KeyError`` with did-you-mean); an amount that isn't an ``int`` (or is a
  ``bool``) is ``TypeError``. Results are clamped to the meter's range. It keeps hidden meters
  (saved meters this version doesn't declare) so they are saved again, and caches its
  ``PointsState`` until the next change, so an unchanged checkpoint costs one read (07 I-7).
- ``PointsState`` is ``GameState.points``: a read-only mapping, declared meters in declaration
  order, then hidden ones. JSON ``{"values": {name: int}}``; ``from_json`` refuses anything
  else with ``StateInvalid("points")``, never echoing (≤ ``SAVED_NAMES_MAX`` names, each
  ``saved_name_ok``, each value an ``int``, not ``bool``, with |v| ≤ ``POINTS_LIMIT``).
- ``Points.merge`` is restore step 3 (07 I-6): a declared meter missing from the save starts
  at its start, a saved value outside today's range is clamped, an undeclared one is kept
  hidden while declared + hidden ≤ ``SAVED_NAMES_MAX``.
- ``PointsView`` is the engine name ``points`` (not saved): ``points.a``, ``points["a"]``,
  ``points.highest(…)``. Every write is E236; before a game starts (a define at launch) every
  read is E236's define form (``bind_view`` gives the view its ``Points``).
- ``run_points`` is the ``PointsChange`` executor: the amount runs like a condition, must be an
  ``int`` (E236), and is applied through ``Points``; dev runs log W120 (area ``runtime``) the
  first time each line is clamped. Not a checkpoint.

``MeterSpec`` is ``script/points.py``'s, re-exported here (07 I-1, the ``runtime.commands``
rule). Layering as ``chapters.py``: ``state.py`` holds a ``PointsState``, so this module sits
below the interpreter and imports it only when the executor runs.
"""

import unicodedata
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Final

from engine.runtime.errors import AuthorRefusal, StoryError, short_value, where
from engine.runtime.values import kind_words
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.nodes import norm
from engine.script.points import POINTS_LIMIT, MeterSpec, PointsChange
from engine.script.suggest import suggest

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step

SAVED_NAMES_MAX: Final = 1000           # names in a saved ``points`` (declared + hidden)
SAVED_NAME_MAX: Final = 64              # code points of a saved name (F22 07 I-2)


def saved_name_ok(name: object) -> bool:
    """A name a saved meter (F21: a saved item) may have: text of 1–64 code points that is an
    identifier in its canonical (NFKC) form and doesn't start with ``_``. Reads no live word
    set, so a name reserved later never makes an older save unreadable (07 I-9)."""
    return (type(name) is str and 0 < len(name) <= SAVED_NAME_MAX and name.isidentifier()
            and not name.startswith("_")
            and (name.isascii() or unicodedata.is_normalized("NFKC", name)))


# --- The state (GameState.points) ----------------------------------------------------------------

class PointsState(Mapping[str, int]):
    """``GameState.points``: meter name → value, read-only. Built only by ``Points`` and
    ``from_json``; the dict inside is never handed out."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, int] | None = None) -> None:
        self._values: dict[str, int] = dict(values or {})

    def __getitem__(self, name: str) -> int:
        return self._values[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PointsState):
            return NotImplemented
        return self._values == other._values

    def __hash__(self) -> int:                  # immutable: a frozen field's default
        return hash(frozenset(self._values.items()))

    def __repr__(self) -> str:
        return f"PointsState({self._values!r})"

    def to_json(self) -> dict[str, object]:
        return {"values": dict(self._values)}

    @staticmethod
    def from_json(obj: object) -> "PointsState":
        """Validate untrusted ``obj``; ``StateInvalid("points")`` for anything but
        ``{"values": {<saved name>: <int>, …}}`` within the bounds (module docstring)."""
        from engine.runtime.state import StateInvalid   # state.py imports this module
        if type(obj) is not dict or obj.keys() != {"values"}:
            raise StateInvalid("points")
        values = obj["values"]
        if type(values) is not dict or len(values) > SAVED_NAMES_MAX:
            raise StateInvalid("points")
        out: dict[str, int] = {}
        for name, value in values.items():
            if (not saved_name_ok(name) or type(value) is not int
                    or not -POINTS_LIMIT <= value <= POINTS_LIMIT):
                raise StateInvalid("points")
            out[name] = value
        return PointsState(out) if out else EMPTY_POINTS


EMPTY_POINTS: Final = PointsState()


# --- The API (interp.points) ----------------------------------------------------------------------

class UnknownMeter(KeyError):
    """No declared meter has this name. ``suggestion`` is the closest declared name, or None;
    ``str()`` is E236's unknown-meter text."""

    def __init__(self, name: object, suggestion: str | None = None) -> None:
        super().__init__(name)
        self.name = name
        self.suggestion = suggestion

    def __str__(self) -> str:
        return format_message("E236", ("unknown", _shown_name(self.name), self.suggestion))


def _shown_name(name: object) -> str:
    return name if type(name) is str else short_value(name)


class Points:
    """The launch's meters (module docstring). ``meters`` is ``Program.meters``."""

    __slots__ = ("_specs", "_names", "_values", "_hidden", "_state")

    def __init__(self, meters: tuple[MeterSpec, ...] = ()) -> None:
        self._specs: dict[str, MeterSpec] = {m.name: m for m in meters}
        self._names: tuple[str, ...] = tuple(self._specs)
        self._values: dict[str, int] = {}
        self._hidden: dict[str, int] = {}
        self._state: PointsState | None = None
        self.reset()

    # Reading ------------------------------------------------------------------------------

    def names(self) -> tuple[str, ...]:
        """The declared meters, in declaration order (hidden ones are not meters)."""
        return self._names

    def spec(self, name: str) -> MeterSpec:
        return self._specs[self._check(name)]

    def get(self, name: str) -> int:
        return self._values[self._check(name)]

    def highest(self, *names: str) -> str:
        """The name of the highest of ``names`` (none: every meter, in declaration order); a
        tie goes to the first listed. ``ValueError`` when there is no meter to compare."""
        names = names or self._names
        if not names:
            raise ValueError("no meters")
        best = self._check(names[0])
        for name in names[1:]:
            if self._values[self._check(name)] > self._values[best]:
                best = name
        return best

    def _check(self, name: object) -> str:
        if type(name) is not str or name not in self._specs:
            found = suggest(name, self._names) if type(name) is str else None
            raise UnknownMeter(name, found)
        return name

    # Changing -----------------------------------------------------------------------------

    def add(self, name: str, amount: int) -> int:
        """Add ``amount`` (an ``int``, not ``bool``) and return the clamped value."""
        return self.change(name, "+=", amount)[0]

    def set(self, name: str, value: int) -> int:
        """Set to ``value`` (an ``int``, not ``bool``) and return the clamped value."""
        return self.change(name, "=", value)[0]

    def change(self, name: str, op: str, amount: int) -> tuple[int, int]:
        """The ``points`` line's operation: ``(value now, value before clamping)``."""
        name = self._check(name)
        if type(amount) is not int:
            raise TypeError(f"a meter changes by a whole number, not {kind_words(amount)}")
        old = self._values[name]
        wanted = old + amount if op == "+=" else old - amount if op == "-=" else amount
        value = self._specs[name].clamp(wanted)
        if value != old:
            self._values[name] = value
            self._state = None
        return value, wanted

    # State ----------------------------------------------------------------------------------

    def state(self) -> PointsState:
        """The current values as a ``PointsState``: declared, then hidden. Cached until the
        next change, so unchanged checkpoints share one object (07 I-7)."""
        state = self._state
        if state is None:
            state = self._state = PointsState({**self._values, **self._hidden})
        return state

    def reset(self) -> None:
        """New Game: every meter at its start, no hidden meter (07 I-6)."""
        self._values = {name: spec.start for name, spec in self._specs.items()}
        self._hidden = {}
        self._state = None

    def merge(self, saved: PointsState) -> PointsState:
        """Restore step 3 (07 I-6): ``saved`` against today's meters. Changes nothing."""
        out = {name: spec.clamp(saved[name]) if name in saved else spec.start
               for name, spec in self._specs.items()}
        for name, value in saved.items():
            if len(out) >= SAVED_NAMES_MAX:
                break
            if name not in out:
                out[name] = value
        return PointsState(out)

    def install(self, state: PointsState) -> None:
        """Make ``state`` (from ``merge`` or ``state()``) the current values: restore's
        transaction and its roll-back."""
        self._values = {name: state[name] for name in self._names}
        self._hidden = {name: value for name, value in state.items()
                        if name not in self._specs}
        self._state = state


# --- The engine name ``points`` (PointsView) ------------------------------------------------------

class PointsView:
    """``points`` in author Python: reads only. Attributes are the meters and ``highest``
    (07 I-5); every write is E236. Without a ``Points`` (a define at launch), any read is
    E236's define form."""

    __slots__ = ("_points",)

    def __init__(self, points: Points | None = None) -> None:
        object.__setattr__(self, "_points", points)

    def _source(self) -> Points:
        points = object.__getattribute__(self, "_points")
        if points is None:
            raise AuthorRefusal.of("E236", "define")
        return points

    def _read(self, name: object) -> int:
        points = self._source()
        try:
            return points.get(name)  # type: ignore[arg-type]
        except UnknownMeter as e:
            raise AuthorRefusal.of("E236", "unknown", _shown_name(name), e.suggestion) from None

    def __getattr__(self, name: str) -> int:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._read(name)

    def __getitem__(self, name: object) -> int:
        return self._read(name)

    def __contains__(self, name: object) -> bool:
        return type(name) is str and name in self._source().names()

    def highest(self, *names: str) -> str:
        points = self._source()
        if not names and not points.names():
            raise AuthorRefusal.of("E236", "none")
        try:
            return points.highest(*names)
        except UnknownMeter as e:
            raise AuthorRefusal.of("E236", "unknown", _shown_name(e.name),
                                   e.suggestion) from None

    def _refuse(self, name: object = None) -> None:
        points = object.__getattribute__(self, "_points")
        names = points.names() if points is not None else ()
        example = name if type(name) is str and name in names else (names[0] if names else None)
        raise AuthorRefusal.of("E236", "write", example)

    def __setattr__(self, name: str, value: object) -> None:
        self._refuse(name)

    def __delattr__(self, name: str) -> None:
        self._refuse(name)

    def __setitem__(self, name: object, value: object) -> None:
        self._refuse(name)

    def __delitem__(self, name: object) -> None:
        self._refuse(name)

    def __dir__(self) -> list[str]:
        points = object.__getattribute__(self, "_points")
        return [*(points.names() if points is not None else ()), "highest"]

    def __repr__(self) -> str:
        return "points"


def bind_view(G: dict, points: Points) -> None:
    """Give ``G``'s ``points`` view its ``Points`` (the launch built it unbound, so a define
    that read it got E236); a hand-built ``G`` gets a new view."""
    view = G.get("points")
    if type(view) is PointsView:
        object.__setattr__(view, "_points", points)
    else:
        G["points"] = PointsView(points)


# --- The executor (SPEC §5) ----------------------------------------------------------------------

def run_points(interp: "Interpreter", stmt: PointsChange) -> "Step":
    """``points <name> +=|-=|= <amount>``: the amount (author code, like a condition), then
    ``Points.change``; W120 in dev runs, once per line."""
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    interp.running.set(stmt.file.ref, stmt.amount)
    amount = interp._eval(stmt.amount.code)
    if type(amount) is not int:
        message = format_message("E236", ("amount", stmt.name, short_value(amount),
                                          kind_words(amount)))
        raise StoryError(message, code="E236", **where(stmt))
    value, wanted = interp.points.change(stmt.name, stmt.op, amount)
    if value != wanted and interp.dev and stmt.sid not in interp.points_warned:
        interp.points_warned.add(stmt.sid)
        text = format_message("W120", (stmt.name, stmt.op, norm(stmt.amount.without_comments()),
                                       wanted > value, value, wanted))
        warning = ScriptWarning(text, code="W120", file=stmt.file.ref, line=stmt.line)
        interp.log.warning("%s", warning.format())
    return Step.CONTINUE


__all__ = ["EMPTY_POINTS", "MeterSpec", "Points", "PointsState", "PointsView", "SAVED_NAMES_MAX",
           "SAVED_NAME_MAX", "UnknownMeter", "bind_view", "run_points", "saved_name_ok"]
