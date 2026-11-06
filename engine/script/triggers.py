"""The trigger core's declarations and its static check (F65 trigger core, ADR-0011).

Why this module exists: Events (I-02), the Inbox's delays (I-09), Places' "open when" (I-04)
and Thoughts (I-06) each declare a block that waits for its moment: a ``when`` condition, once
or repeating, optional story-time timing, and something the owning system does when it fits.
This is the one shared declaration (``Trigger``) and the check that tells an author, before
the game runs, which blocks can never fit and which always win and hide the ones below them.
The run-time side (saved state, evaluation points, the first-fit pick) is
``runtime/triggers.py``; docs/architecture.md "Trigger core" has the whole picture.

- ``Timing``: ``day`` (not before this story day), ``part`` (only in this part of the day, an
  index into the calendar's parts), and the relative ``after_days`` / ``after_parts`` /
  ``after_scenes``, which count from the moment the owning system *arms* the trigger
  (``runtime/triggers.arm``: the Inbox's ``send … after 1 day``). ``after_parts`` counts
  the parts of the day the clock passes, across days (evening + 2 parts is the next
  afternoon in a three-part day; ``clock next day`` passes every part it skips). A day
  number is resolved by the owner's statement (a date in quotes through
  ``Calendar.find_date``), so this module sees only numbers.
- ``Trigger``: ``kind`` (the owner's word: ``event``, ``message``, ``place``, ``thought``;
  every message names it, so authors read about their events), ``name`` (unique in the kind;
  ``id`` is ``kind:name``, the saved key), ``at`` (the declaring line, where errors point),
  ``when`` (a compiled condition, run as an ``if`` condition is), ``once`` (retires after it
  fires; else it repeats), ``timing``, ``where`` (Events' ``at library``: ``pick`` matches it
  exactly), ``live`` (waits from the start of the game; False: only once armed) and
  ``payload`` (the owner's, static, never saved).
- ``check_triggers(triggers, add, calendar, picked=…)``: E459 (two of one kind share a name),
  E458 (a trigger live from the start with ``after`` timing: nothing to count from) to
  ``add``; returns W316 (can never fit: a day past ``[calendar] last_day``, ``after N days``
  or ``after N parts`` past it, a part the calendar doesn't have, or a condition never
  true) and W315 (for kinds picked first-fit: an earlier block at the same place that
  always fits and repeats hides this one).

**How the condition is read** (pure: nothing here runs author code). The ``when`` source is
read as Python's tree. ``clock.day``, ``clock.part``, ``clock.weekday``, ``clock.month`` and
``clock.season``, constants, comparisons, ``and``/``or``/``not`` and small whole-number sums
are worked out; anything else (a variable, ``points.hana``, a call) is "unknown", and ``and``
and ``or`` follow three-valued logic, so ``clock.part == "Nite" and met`` is still never true.
The condition is tried on every part of the day the timing allows and on enough days to be
exact: the days around each number it compares ``clock.day`` with, or one full cycle of the
weekdays, months or seasons it reads, or every day of the calendar's span when that is at most
``SCAN_DAYS``. When none of that is exact, a condition is never called "never" or "always". A
game with its own ``clock`` (a define or default) passes ``calendar=None``: ``clock.…`` is then
unknown, as W302 says.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Final

from engine.core.storyclock import DAY_MAX, Calendar
from engine.script import trigger_messages
from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.messages import TEMPLATES, format_message
from engine.script.nodes import Node, PyCode

TEMPLATES.update(trigger_messages.TEMPLATES)

KIND_RE: Final = re.compile(r"[a-z][a-z_]{0,19}")
NAME_MAX: Final = 100                   # code points of a trigger's name
WHERE_MAX: Final = 100                  # code points of a ``where``
SCENES_MAX: Final = 10_000              # after N scenes, at most
AFTER_PARTS_MAX: Final = 10_000         # after N parts of the day, at most
SCAN_DAYS: Final = 1_000                # days the check tries one condition on, at most
CLOCK_VALUES: Final = ("day", "part", "weekday", "month", "season")
NEVER: Final = "never"
ALWAYS: Final = "always"
MAYBE: Final = "maybe"

_UNKNOWN: Final = object()
_SMALL: Final = 10**9                   # whole numbers the check adds up, at most
_COMPARE: Final = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                   ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
                   ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}
_ARITH: Final = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                 ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}


# --- Declarations ----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Timing:
    """When a trigger may fit, besides its condition (module docstring). All None: any
    time. ``ValueError`` for a value no statement can give (the owner's parser checks the
    author's text first)."""

    day: int | None = None
    part: int | None = None
    after_days: int | None = None
    after_scenes: int | None = None
    after_parts: int | None = None

    def __post_init__(self) -> None:
        for value, low, high in ((self.day, 1, DAY_MAX), (self.part, 0, 99),
                                 (self.after_days, 0, DAY_MAX),
                                 (self.after_scenes, 0, SCENES_MAX),
                                 (self.after_parts, 0, AFTER_PARTS_MAX)):
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise ValueError(f"Timing: {value!r} is out of range")

    @property
    def relative(self) -> bool:
        """Counts from when the trigger is armed (``after …``)."""
        return (self.after_days is not None or self.after_scenes is not None
                or self.after_parts is not None)


ANY_TIME: Final = Timing()


@dataclass(frozen=True, slots=True)
class Trigger:
    """One declared block that waits for its moment (module docstring). Built by the owning
    system's statement (or its ``collect``); never saved: a save keeps only its ``id``."""

    kind: str
    name: str
    at: Node
    when: PyCode | None = None
    once: bool = False
    timing: Timing = ANY_TIME
    where: str | None = None
    live: bool = True
    payload: object = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or not KIND_RE.fullmatch(self.kind):
            raise ValueError("Trigger: kind must be a short lower-case word")
        if type(self.name) is not str or not 0 < len(self.name) <= NAME_MAX:
            raise ValueError("Trigger: name must be 1 to 100 characters")
        if self.when is not None and (self.when.mode != "eval" or self.when.code is None):
            raise ValueError("Trigger: when must be a compiled condition")
        if self.where is not None and (type(self.where) is not str
                                       or not 0 < len(self.where) <= WHERE_MAX):
            raise ValueError("Trigger: where must be 1 to 100 characters")

    @property
    def id(self) -> str:
        """The saved key: ``kind:name``."""
        return f"{self.kind}:{self.name}"


# --- The static check ------------------------------------------------------------------------

def check_triggers(triggers: Sequence[Trigger], add: Callable[[Diagnostic], object],
                   calendar: Calendar | None = None, *,
                   picked: Collection[str] = ()) -> list[ScriptWarning]:
    """E459 and E458 to ``add``; W316 and W315 returned, in declaration order (module
    docstring). ``calendar`` None: no calendar to read the clock against (a tool with no
    config, or a game with its own ``clock``). ``picked``: the kinds picked first-fit (Events),
    the only ones W315 applies to; the others all fire when they fit."""
    warnings: list[ScriptWarning] = []
    seen: dict[str, Trigger] = {}
    verdicts: dict[int, str] = {}
    for index, trigger in enumerate(triggers):
        first = seen.get(trigger.id)
        if first is not None:
            _error(add, trigger, "E459", (trigger.kind, trigger.name, first.at.line))
            continue
        seen[trigger.id] = trigger
        timing = trigger.timing
        if trigger.live and timing.relative:
            unit, count = (("days", timing.after_days) if timing.after_days is not None
                           else ("parts", timing.after_parts)
                           if timing.after_parts is not None
                           else ("scenes", timing.after_scenes))
            _error(add, trigger, "E458", (trigger.kind, trigger.name, unit, count))
            continue
        result, args = verdict(trigger, calendar)
        verdicts[index] = result
        if result == NEVER:
            warnings.append(_warning(trigger, "W316", (args[0], trigger.kind, trigger.name,
                                                       *args[1:])))
    for index, trigger in enumerate(triggers):
        if trigger.kind not in picked or verdicts.get(index, NEVER) == NEVER:
            continue
        winner = _hidden_by(triggers, index, verdicts)
        if winner is not None:
            warnings.append(_warning(trigger, "W315", (trigger.kind, trigger.name, winner.name,
                                                       winner.at.line, trigger.where or "")))
    return warnings


def _hidden_by(triggers: Sequence[Trigger], index: int, verdicts: dict[int, str]
               ) -> Trigger | None:
    """The first earlier trigger of the same kind and place that fits whenever this one
    does and repeats: it always wins the first-fit pick."""
    later = triggers[index]
    for i in range(index):
        earlier = triggers[i]
        if (earlier.kind != later.kind or earlier.where != later.where or earlier.once
                or not earlier.live or verdicts.get(i, NEVER) == NEVER):
            continue
        if earlier.timing not in (ANY_TIME, later.timing):
            continue
        if verdicts[i] == ALWAYS or _same_when(earlier.when, later.when):
            return earlier
    return None


def _same_when(a: PyCode | None, b: PyCode | None) -> bool:
    if a is None or b is None:
        return a is b
    try:
        return ast.dump(ast.parse(a.source.strip(), mode="eval")) == ast.dump(
            ast.parse(b.source.strip(), mode="eval"))
    except (SyntaxError, ValueError):
        return False


def _error(add: Callable[[Diagnostic], object], trigger: Trigger, code: str,
           args: tuple) -> None:
    node = trigger.at
    add(Diagnostic(code, node.file, node.line, None, args, stmt=node.line))


def _warning(trigger: Trigger, code: str, args: tuple) -> ScriptWarning:
    return ScriptWarning(format_message(code, args), code=code, file=trigger.at.file.ref,
                         line=trigger.at.line)


# --- Never, always or maybe ------------------------------------------------------------------

def verdict(trigger: Trigger, calendar: Calendar | None) -> tuple[str, tuple]:
    """Whether ``trigger`` can fit: ``(NEVER, W316 args without kind and name)``,
    ``(ALWAYS, ())`` (whenever its timing allows, its condition is true), or
    ``(MAYBE, ())``. Pure (module docstring, "How the condition is read")."""
    timing = trigger.timing
    lo, hi, parts = 1, DAY_MAX, None
    if calendar is not None:
        if timing.part is not None and timing.part >= len(calendar.parts):
            return NEVER, ("part", timing.part + 1, len(calendar.parts))
        lo = max(calendar.start_day, timing.day or 1)
        if timing.after_days is not None:
            lo = max(lo, calendar.start_day + timing.after_days)
        if timing.after_parts is not None:     # at the soonest: armed in the first part
            lo = max(lo, calendar.start_day + timing.after_parts // len(calendar.parts))
        if calendar.last_day is not None:
            hi = calendar.last_day
            if lo > hi:
                if timing.day is not None and timing.day > hi:
                    return NEVER, ("past_last", timing.day, hi)
                if timing.after_days is None and timing.after_parts is not None:
                    return NEVER, ("after_parts", timing.after_parts, hi)
                return NEVER, ("after", timing.after_days, hi)
        parts = (timing.part,) if timing.part is not None else tuple(range(len(calendar.parts)))
    if trigger.when is None:
        return ALWAYS, ()
    try:
        tree = ast.parse(trigger.when.source.strip(), mode="eval").body
    except (SyntaxError, ValueError):
        return MAYBE, ()
    if calendar is None or parts is None:
        result = _truth(tree, None)
        return _settle({result}, exact=True, span="")
    uses = _clock_uses(tree)
    if "part" not in uses:
        parts = parts[:1]
    days, exact = _days(tree, uses, calendar, lo, hi)
    results: set[object] = set()
    for day in days:
        for part in parts:
            results.add(_truth(tree, _env(calendar, day, part)))
            if len(results) > 1:
                return MAYBE, ()
    span = ""
    if "day" in uses or uses & {"weekday", "month", "season"}:
        span = f" on days {lo} to {hi}" if hi < DAY_MAX else f" from day {lo} on"
    return _settle(results, exact=exact, span=span, source=trigger.when.source)


def _settle(results: set[object], *, exact: bool, span: str, source: str = ""
            ) -> tuple[str, tuple]:
    if len(results) != 1 or not exact:
        return MAYBE, ()
    (result,) = results
    if result is True:
        return ALWAYS, ()
    if result is False:
        return NEVER, ("never", " ".join(source.split()), span)
    return MAYBE, ()


def _days(tree: ast.expr, uses: set[str], calendar: Calendar, lo: int, hi: int
          ) -> tuple[list[int], bool]:
    """The days to try and whether trying them is exact (module docstring)."""
    count = hi - lo + 1
    if count <= SCAN_DAYS:
        return list(range(lo, hi + 1)), True
    if "day" not in uses:
        period = 1
        if "weekday" in uses:
            period = math.lcm(period, len(calendar.weekdays))
        if "month" in uses:
            period = math.lcm(period, max(sum(d for _, d in calendar.months), 1))
        if "season" in uses:
            period = math.lcm(period, max(len(calendar.seasons) * calendar.season_days, 1))
        if period <= SCAN_DAYS:
            return list(range(lo, lo + period)), True
        return list(range(lo, lo + SCAN_DAYS)), False
    if uses <= {"day", "part"} and not _day_arithmetic(tree):
        points = {lo, hi}
        for number in _numbers(tree):
            points.update(n for n in (number - 1, number, number + 1) if lo <= n <= hi)
        return sorted(points), True
    return list(range(lo, lo + SCAN_DAYS)), False


def _env(calendar: Calendar, day: int, part: int) -> dict[str, object]:
    month = calendar.month(day)
    season = calendar.season(day)
    return {"day": day, "part": calendar.parts[part], "weekday": calendar.weekday(day),
            "month": month[0] if month is not None else "",
            "season": season[0] if season is not None else ""}


def _is_clock(node: ast.AST) -> bool:
    return (type(node) is ast.Attribute and type(node.value) is ast.Name
            and node.value.id == "clock" and node.attr in CLOCK_VALUES)


def _clock_uses(tree: ast.AST) -> set[str]:
    return {node.attr for node in ast.walk(tree) if _is_clock(node)}  # type: ignore[attr-defined]


def _day_arithmetic(tree: ast.AST) -> bool:
    return any(type(node) is ast.BinOp and any(_is_clock(n) for n in ast.walk(node))
               for node in ast.walk(tree))


def _numbers(tree: ast.AST) -> set[int]:
    return {node.value for node in ast.walk(tree)
            if type(node) is ast.Constant and type(node.value) is int}


def _truth(node: ast.AST, env: dict[str, object] | None) -> object:
    """True, False or ``_UNKNOWN``: ``and``/``or``/``not`` in three-valued logic."""
    if type(node) is ast.BoolOp:
        values = [_truth(v, env) for v in node.values]
        stop = type(node.op) is ast.Or            # or: any True wins; and: any False wins
        if stop in values:
            return stop
        return _UNKNOWN if _UNKNOWN in values else not stop
    if type(node) is ast.UnaryOp and type(node.op) is ast.Not:
        value = _truth(node.operand, env)
        return value if value is _UNKNOWN else not value
    value = _value(node, env)
    if value is _UNKNOWN:
        return _UNKNOWN
    try:
        return bool(value)
    except Exception:                                   # noqa: BLE001 (plain values only)
        return _UNKNOWN


def _value(node: ast.AST, env: dict[str, object] | None) -> object:
    kind = type(node)
    if kind is ast.Constant:
        return node.value                               # type: ignore[attr-defined]
    if _is_clock(node):
        return _UNKNOWN if env is None else env[node.attr]  # type: ignore[attr-defined]
    if kind in (ast.Tuple, ast.List, ast.Set):
        items = [_value(n, env) for n in node.elts]     # type: ignore[attr-defined]
        return _UNKNOWN if _UNKNOWN in items else tuple(items)
    if kind is ast.UnaryOp and type(node.op) is ast.USub:   # type: ignore[attr-defined]
        value = _value(node.operand, env)               # type: ignore[attr-defined]
        return -value if type(value) is int else _UNKNOWN
    if kind is ast.BinOp:
        run = _ARITH.get(type(node.op))                 # type: ignore[attr-defined]
        a, b = _value(node.left, env), _value(node.right, env)  # type: ignore[attr-defined]
        if run is None or type(a) is not int or type(b) is not int \
                or abs(a) > _SMALL or abs(b) > _SMALL:
            return _UNKNOWN
        try:
            return run(a, b)
        except ZeroDivisionError:
            return _UNKNOWN
    if kind is ast.Compare:
        left = _value(node.left, env)                   # type: ignore[attr-defined]
        if left is _UNKNOWN:
            return _UNKNOWN
        for op, right_node in zip(node.ops, node.comparators):  # type: ignore[attr-defined]
            right = _value(right_node, env)
            run = _COMPARE.get(type(op))
            if right is _UNKNOWN or run is None:
                return _UNKNOWN
            try:
                if not run(left, right):
                    return False
            except TypeError:
                return _UNKNOWN
            left = right
        return True
    if kind in (ast.BoolOp, ast.UnaryOp):
        return _truth(node, env)
    return _UNKNOWN


__all__ = ["AFTER_PARTS_MAX", "ALWAYS", "ANY_TIME", "CLOCK_VALUES", "MAYBE", "NEVER",
           "SCAN_DAYS", "Timing", "Trigger", "check_triggers", "verdict"]
