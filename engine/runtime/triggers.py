"""The trigger core at run time (F65 trigger core, ADR-0011; declarations and the static check:
``script/triggers.py``).

Why this module exists: Events, Inbox delays, Places' "open when" and Thoughts all need the
same thing: blocks that wait for their moment, fire when their condition and timing fit, retire
when they are ``once``, and do all of that as story state, so saves, loads, going back and the
quiet forward re-run end exactly where the first run did. One registry does it for all of them;
each owning system only says what its blocks are and what firing one does.

**Kinds.** An owning system calls ``register_kind(word, collect=…, on_fire=…, pick=…)`` once,
when its module is imported (registering the same word again replaces it). ``collect(program)``
returns its ``Trigger`` declarations in file order. A kind with ``on_fire`` is **pushed**: at
each evaluation point every one of its triggers that fits fires (``on_fire(interp, fired)``).
A kind without is **picked**: nothing fires by itself; the owner asks ``pick(interp, kind,
where)`` (Events' ``events at library``), which takes the first that fits by the kind's
``pick`` policy.

**The table** (``interp.trigger_table``, built by ``install`` from every kind's ``collect``,
kinds in registration order): the declarations, never saved. **The state**
(``interp.triggers``, ``GameState.triggers``): ``armed`` (instances the owner armed with
``arm``: the ``after`` timing counted from that moment, and the owner's saved ``data``) and
``retired`` (the ids of ``once`` triggers that fired while live from the start). Ids are
``kind:name``. A saved id the script no longer declares is kept and ignored (as F21 keeps a
hidden item), so an older save loads; a save from before the trigger core has neither key
(``EMPTY_TRIGGERS``) and writes nothing new (``triggers_json``).

**After an update** (``restored``, restore's step for this state): an armed id the script no
longer declares is offered to its kind's ``adopt(interp, armed)``, which may name the
declared trigger it is now (a message saved under an older key, or its ``send`` line's
occurrence shifted), given the ids already armed. The instance moves to that id with its timing and data, so it still
fires; one no kind adopts stays armed (never dropped: a later update may declare it again)
and is logged once as a WARNING.

**When a trigger fits** (``due``): it is armed (and its ``after`` days, parts and scenes
have come), or it is ``live`` with no ``after`` timing and not retired; the clock is on or
after ``timing.day`` and, with ``timing.part``, in that part of the day; and its ``when`` is
true.
The condition runs as an ``if`` condition does: under the watchdog (``Interpreter._test``),
with ``print`` naming its line, and an exception is the same story error an ``if`` would give
(E85…, E85m), at the declaring line. **Firing** (``take``): a ``once`` armed instance is
removed, a ``once`` live trigger is retired; a repeating one stays and fires again whenever it
fits.

**After N parts** counts the parts of the day the clock passes, as a position on the
calendar: arming at evening of day 3 with ``after 2 parts`` in a three-part day is due from
the afternoon of day 4 (``Armed.day`` 4, ``Armed.part`` 1). Any ``clock`` line that passes
that point fires it: ``clock next day`` from the morning passes all of that day's parts, so
``after 1 part`` sent in the morning arrives with the next morning, not later. Going back to
an earlier day with ``clock go to day 1`` passes nothing; the message waits until the clock
comes forward to its point again. A part past a calendar that has fewer parts now is its
last part (as ``clock.resolved``).

**Evaluation points**, pushed kinds only, in declaration order:

1. Every ``ClockChanged`` (``clock.listen``).
2. Every scene the story enters (``Interpreter._enter``: a jump, a call, the start, a Use's
   scene; returning from a call is not entering). Each armed ``after N scenes`` counts one
   down first.
3. Whenever the owner calls ``evaluate`` (say, right after ``arm`` for ``after 0 days``).

A pass that is already running doesn't start another (``on_fire`` may ``arm``; that trigger
waits for the next point). ``on_fire`` changes story state only and never moves the story.

**The replay rule** (clock.py's, kept): load, restore, going back and New Game put the state
back and evaluate nothing. The quiet forward re-run (``interp.timeline.replaying``) runs the
same ``clock`` lines and enters the same scenes, so it evaluates again and fires the same
triggers, which is what makes it end where the first run did: ``on_fire`` always changes the
story state it changes, and only *shows* something (a notice, a sound) when
``not interp.timeline.replaying``.

**Pick order.** First fit in declaration order (``first_fit``). A kind may pass its own
``pick`` (it is given the fitting triggers lazily, in order, and returns one or None); a
saliency pick (most conditions, least recently seen, as Yarn Spinner does) is the planned
second policy and needs a "last seen" stamp per trigger in this state (ADR-0011).

Layering as ``clock.py``: ``state.py`` holds a ``TriggerState``, so this module sits below the
interpreter and reaches it only through the ``interp`` it is given.
"""

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.core.storyclock import DAY_MAX
from engine.runtime import clock as clock_mod
from engine.runtime.errors import AuthorRefusal, StoryError, timeout_error
from engine.runtime.values import Value, plain_copy, same_value
from engine.script.program import Program
from engine.script.triggers import SCENES_MAX, Trigger

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter

ARMED_MAX: Final = 1_000                # armed at once (E457 past it)
RETIRED_MAX: Final = 10_000             # retired ids a save may hold
DATA_MEMBERS_MAX: Final = 100           # list and dict members in one armed ``data``
DATA_DEPTH_MAX: Final = 4
DATA_TEXT_MAX: Final = 1_000
_INT_MAX: Final = 2**53
_log = get_logger("runtime")
_ID_RE: Final = re.compile(r"[a-z][a-z_]{0,19}:[^\x00-\x1f\x7f\ud800-\udfff]{1,100}")


# --- The state (GameState.triggers) ----------------------------------------------------------

@dataclass(frozen=True, slots=True, eq=False)
class Armed:
    """One armed instance: ``day`` (due from this story day; with ``part``, from that part
    of it: ``after N parts``) and ``scenes`` (scenes still to enter) are None once met or
    when not asked for; ``data`` is the owner's plain value."""

    id: str
    day: int | None = None
    scenes: int | None = None
    data: Value = None
    part: int | None = None

    def __eq__(self, other: object) -> bool:
        if type(other) is not Armed:
            return NotImplemented
        return (self.id == other.id and self.day == other.day and self.scenes == other.scenes
                and self.part == other.part and same_value(self.data, other.data))

    __hash__ = None  # type: ignore[assignment]

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {"id": self.id}
        if self.day is not None:
            out["day"] = self.day
        if self.part is not None:
            out["part"] = self.part
        if self.scenes is not None:
            out["scenes"] = self.scenes
        if self.data is not None:
            out["data"] = plain_copy(self.data)
        return out


@dataclass(frozen=True, slots=True)
class TriggerState:
    """``GameState.triggers`` (module docstring). JSON ``{"armed": [{"id", "day"?,
    "part"?, "scenes"?, "data"?}, …], "retired": [id, …]}``, each key only when not empty
    (``part`` only with ``day``)."""

    armed: tuple[Armed, ...] = ()
    retired: frozenset[str] = frozenset()

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {}
        if self.armed:
            out["armed"] = [a.to_json() for a in self.armed]
        if self.retired:
            out["retired"] = sorted(self.retired)
        return out

    @staticmethod
    def from_json(obj: object) -> "TriggerState":
        """Validate untrusted ``obj``; anything else is ``StateInvalid("triggers")``, never
        echoing the input. Shares nothing with ``obj``."""
        from engine.runtime.state import StateInvalid      # state.py imports this module
        if type(obj) is not dict or not obj.keys() <= {"armed", "retired"}:
            raise StateInvalid("triggers")
        armed_raw, retired_raw = obj.get("armed", []), obj.get("retired", [])
        if (type(armed_raw) is not list or len(armed_raw) > ARMED_MAX
                or type(retired_raw) is not list or len(retired_raw) > RETIRED_MAX
                or not all(_id_ok(r) for r in retired_raw)
                or len(set(retired_raw)) != len(retired_raw)):
            raise StateInvalid("triggers")
        armed: list[Armed] = []
        for entry in armed_raw:
            if (type(entry) is not dict or "id" not in entry
                    or not entry.keys() <= {"id", "day", "part", "scenes", "data"}):
                raise StateInvalid("triggers")
            day, part, scenes = entry.get("day"), entry.get("part"), entry.get("scenes")
            if (not _id_ok(entry["id"])
                    or (day is not None and not _int_in(day, 1, 2 * DAY_MAX))
                    or (part is not None and (day is None or not _int_in(part, 0, 99)))
                    or (scenes is not None and not _int_in(scenes, 1, SCENES_MAX))
                    or ("data" in entry and (entry["data"] is None
                                             or data_problem(entry["data"]) is not None))):
                raise StateInvalid("triggers")
            armed.append(Armed(entry["id"], day, scenes, plain_copy(entry.get("data")), part))
        if len({a.id for a in armed}) != len(armed):
            raise StateInvalid("triggers")
        if not armed and not retired_raw:
            return EMPTY_TRIGGERS
        return TriggerState(tuple(armed), frozenset(retired_raw))


EMPTY_TRIGGERS: Final = TriggerState()


def triggers_json(state: TriggerState) -> dict[str, object]:
    """``{"triggers": …}`` only when something is armed or retired, so other saves are as
    before the trigger core."""
    return {} if state == EMPTY_TRIGGERS else {"triggers": state.to_json()}


def _int_in(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _id_ok(value: object) -> bool:
    return type(value) is str and _ID_RE.fullmatch(value) is not None


def data_problem(value: object) -> str | None:
    """Why ``value`` can't be an armed instance's ``data`` (None when it can): plain JSON
    values only (None, bools, whole numbers within ±2**53, text up to ``DATA_TEXT_MAX`` with
    no lone surrogate, lists, and dicts with text keys), at most ``DATA_MEMBERS_MAX`` members
    and ``DATA_DEPTH_MAX`` levels. No floats, so a save always reads back equal."""
    members = 0
    level = [value]
    for depth in range(DATA_DEPTH_MAX + 1):
        nxt: list[object] = []
        for item in level:
            kind = type(item)
            if item is None or kind is bool:
                continue
            if kind is int:
                if abs(item) > _INT_MAX:                # type: ignore[arg-type]
                    return "int"
            elif kind is str:
                if len(item) > DATA_TEXT_MAX or not _text_ok(item):  # type: ignore[arg-type]
                    return "text"
            elif kind is list:
                members += len(item)                    # type: ignore[arg-type]
                nxt.extend(item)                        # type: ignore[arg-type]
            elif kind is dict:
                members += len(item)                    # type: ignore[arg-type]
                for key, sub in item.items():           # type: ignore[attr-defined]
                    if type(key) is not str or len(key) > DATA_TEXT_MAX or not _text_ok(key):
                        return "key"
                    nxt.append(sub)
            else:
                return "kind"
        if members > DATA_MEMBERS_MAX:
            return "too_many"
        if not nxt:
            return None
        if depth == DATA_DEPTH_MAX:
            return "too_deep"
        level = nxt
    return None


def _text_ok(text: str) -> bool:
    return text.isascii() or not any(0xD800 <= ord(c) <= 0xDFFF for c in text)


# --- Kinds and the table -----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Fired:
    """A trigger that fits now: the declaration, the armed instance's ``data`` (None for a
    live one) and whether it was armed."""

    trigger: Trigger
    data: Value = None
    armed: bool = False


OnFire = Callable[["Interpreter", Fired], None]
Pick = Callable[[Iterator[Fired]], "Fired | None"]
Collect = Callable[[Program], Iterable[Trigger]]
Adopt = Callable[["Interpreter", Armed, set[str]], "str | None"]


def first_fit(fitting: Iterator[Fired]) -> Fired | None:
    """The default pick: the first that fits, in declaration order (later ones aren't
    tested, so their conditions don't run)."""
    return next(fitting, None)


@dataclass(frozen=True, slots=True)
class Kind:
    word: str
    collect: Collect
    on_fire: OnFire | None
    pick: Pick
    adopt: Adopt | None = None


_KINDS: dict[str, Kind] = {}


def register_kind(word: str, *, collect: Collect, on_fire: OnFire | None = None,
                  pick: Pick = first_fit, adopt: Adopt | None = None) -> None:
    """Declare a kind of trigger (module docstring, "Kinds"). Registering ``word`` again
    replaces it (an import that runs twice is harmless). Interpreters built afterwards see
    it. ``adopt``: module docstring, "After an update"."""
    _KINDS[word] = Kind(word, collect, on_fire, pick, adopt)


def unregister_kind(word: str) -> None:
    _KINDS.pop(word, None)


class TriggerTable:
    """One interpreter's declarations (never saved): ``triggers`` in order, ``by_id``, and
    ``pushed`` (the ones whose kind has ``on_fire``, with it). A second declaration with an
    id already seen is left out (the load's check gives E459 for it)."""

    __slots__ = ("triggers", "by_id", "pushed", "busy")

    def __init__(self, triggers: Iterable[Trigger]) -> None:
        self.by_id: dict[str, Trigger] = {}
        for trigger in triggers:
            self.by_id.setdefault(trigger.id, trigger)
        self.triggers: tuple[Trigger, ...] = tuple(self.by_id.values())
        self.pushed: tuple[tuple[Trigger, OnFire], ...] = tuple(
            (t, kind.on_fire) for t in self.triggers
            if (kind := _KINDS.get(t.kind)) is not None and kind.on_fire is not None)
        self.busy = False

    @staticmethod
    def build(program: Program) -> "TriggerTable":
        return TriggerTable(t for kind in tuple(_KINDS.values())
                            for t in kind.collect(program) if t.kind == kind.word)


def install(interp: "Interpreter") -> TriggerTable:
    """Per interpreter: ``interp.trigger_table`` from every registered kind. The story state
    ``interp.triggers`` is the interpreter's own (New Game empties it)."""
    table = TriggerTable.build(interp.program)
    interp.trigger_table = table            # type: ignore[attr-defined]
    return table


def _table(interp: "Interpreter") -> TriggerTable:
    table = getattr(interp, "trigger_table", None)
    return table if table is not None else install(interp)


def restored(interp: "Interpreter", state: TriggerState) -> TriggerState:
    """Restore's step for a saved ``TriggerState`` (load, going back; module docstring,
    "After an update"): ``state`` itself when every armed id is declared, else a copy where
    each armed instance its kind adopts has moved to the declared id it names (one not
    declared, or already armed, is not taken). The rest stay as they are; their ids are
    logged once per interpreter as a WARNING. Never raises for an adopt that fails."""
    by_id = _table(interp).by_id
    if all(a.id in by_id for a in state.armed):
        return state
    taken = {a.id for a in state.armed}
    out: list[Armed] = []
    kept: list[str] = []
    for armed in state.armed:
        if armed.id in by_id:
            out.append(armed)
            continue
        kind = _KINDS.get(armed.id.partition(":")[0])
        new = None
        if kind is not None and kind.adopt is not None:
            try:
                new = kind.adopt(interp, armed, taken)
            except Exception:               # noqa: BLE001 (a saved id is untrusted)
                new = None
        if type(new) is str and new in by_id and new not in taken:
            taken.add(new)
            out.append(Armed(new, armed.day, armed.scenes, armed.data, armed.part))
        else:
            out.append(armed)
            kept.append(armed.id)
    _warn_kept(interp, kept)
    return TriggerState(tuple(out), state.retired)


def _warn_kept(interp: "Interpreter", ids: list[str]) -> None:
    """The WARNING for armed ids no declaration takes, once per id and interpreter."""
    logged: set[str] | None = getattr(interp, "_kept_triggers_logged", None)
    if logged is None:
        logged = set()
        try:
            interp._kept_triggers_logged = logged       # type: ignore[attr-defined]
        except AttributeError:
            pass
    fresh = [i for i in ids if i not in logged]
    if not fresh:
        return
    logged.update(fresh)
    log = getattr(interp, "log", None) or _log
    log.warning("The save holds %d waiting trigger%s the script no longer has (%s); kept, "
                "but it won't fire unless the script declares it again.", len(fresh),
                "" if len(fresh) == 1 else "s", ", ".join(sorted(fresh)[:5]))


def _declared(interp: "Interpreter", trigger_id: str) -> Trigger:
    found = _table(interp).by_id.get(trigger_id)
    if found is None:
        raise ValueError(f"no trigger {trigger_id!r} is declared")
    return found


# --- Arming and retiring -----------------------------------------------------------------------

def arm(interp: "Interpreter", trigger_id: str, data: Value = None) -> None:
    """Arm the declared trigger ``trigger_id``: its ``after`` days, parts and scenes count
    from now (module docstring, "After N parts"), and ``data`` is saved with it
    (``data_problem`` must be None: ``ValueError``). Arming
    one that is already armed starts it again with the new ``data``; arming a retired one
    un-retires it. Over ``ARMED_MAX`` armed: E457 (an ``AuthorRefusal``, so the owner's
    statement reports it at its line)."""
    trigger = _declared(interp, trigger_id)
    problem = data_problem(data)
    if problem is not None:
        raise ValueError(f"arm: data can't be saved ({problem})")
    timing = trigger.timing
    now = clock_mod.now(interp)
    day = now.day + timing.after_days if timing.after_days else None
    part = None
    if timing.after_parts:
        count = len(clock_mod.calendar(interp).parts)
        day, part = divmod(now.day * count + now.part + timing.after_parts, count)
    scenes = timing.after_scenes or None
    state = interp.triggers
    armed = tuple(a for a in state.armed if a.id != trigger_id)
    if len(armed) >= ARMED_MAX:
        raise AuthorRefusal.of("E457", trigger.kind, ARMED_MAX)
    interp.triggers = TriggerState(armed + (Armed(trigger_id, day, scenes, plain_copy(data),
                                                  part),),
                                   state.retired - {trigger_id})


def disarm(interp: "Interpreter", trigger_id: str) -> bool:
    """Take back an armed instance (a letter that won't be sent after all). Whether one was
    armed."""
    state = interp.triggers
    armed = tuple(a for a in state.armed if a.id != trigger_id)
    if len(armed) == len(state.armed):
        return False
    interp.triggers = TriggerState(armed, state.retired)
    return True


def is_armed(interp: "Interpreter", trigger_id: str) -> bool:
    return any(a.id == trigger_id for a in interp.triggers.armed)


def retire(interp: "Interpreter", trigger_id: str) -> None:
    """Retire ``trigger_id`` (a live trigger then never fits again, until armed)."""
    state = interp.triggers
    if trigger_id not in state.retired and len(state.retired) < RETIRED_MAX:
        interp.triggers = TriggerState(state.armed, state.retired | {trigger_id})


def is_retired(interp: "Interpreter", trigger_id: str) -> bool:
    return trigger_id in interp.triggers.retired


def take(interp: "Interpreter", fired: Fired) -> None:
    """Mark ``fired`` as fired (module docstring, "Firing")."""
    trigger = fired.trigger
    if not trigger.once:
        return
    if fired.armed:
        disarm(interp, trigger.id)
    else:
        retire(interp, trigger.id)


# --- Fitting, picking, evaluating --------------------------------------------------------------

def due(interp: "Interpreter", kind: str, where: str | None = None) -> Iterator[Fired]:
    """The ``kind`` triggers that fit now whose ``where`` is ``where`` (exactly; None
    matches those with none), lazily, in declaration order. Each one's condition runs only
    when the iteration reaches it. A failing condition raises its ``StoryError``."""
    for trigger in _table(interp).triggers:
        if trigger.kind == kind and trigger.where == where:
            found = fits(interp, trigger)
            if found is not None:
                yield found


def pick(interp: "Interpreter", kind: str, where: str | None = None, *,
         take_it: bool = True) -> Fired | None:
    """The one ``kind`` trigger to fire at ``where`` now, by the kind's pick policy (first
    fit unless it registered another), or None; ``take_it`` marks it fired (``take``)."""
    registered = _KINDS.get(kind)
    policy = registered.pick if registered is not None else first_fit
    found = policy(due(interp, kind, where))
    if found is not None and take_it:
        take(interp, found)
    return found


def fits(interp: "Interpreter", trigger: Trigger) -> Fired | None:
    """``trigger`` as a ``Fired`` when it fits now (module docstring), else None."""
    state = interp.triggers
    armed = next((a for a in state.armed if a.id == trigger.id), None)
    timing = trigger.timing
    now = clock_mod.now(interp)
    if armed is None:
        if not trigger.live or timing.relative or trigger.id in state.retired:
            return None
    elif armed.scenes is not None or (armed.day is not None and _before(interp, now, armed)):
        return None
    if timing.day is not None and now.day < timing.day:
        return None
    if timing.part is not None and now.part != timing.part:
        return None
    if trigger.when is not None and not _test(interp, trigger):
        return None
    return Fired(trigger, armed.data if armed is not None else None, armed is not None)


def _before(interp: "Interpreter", now: clock_mod.ClockState, armed: Armed) -> bool:
    """Whether the clock is still before ``armed``'s day (and part)."""
    if armed.part is None:
        return now.day < armed.day                      # type: ignore[operator]
    last = len(clock_mod.calendar(interp).parts) - 1
    return (now.day, now.part) < (armed.day, min(armed.part, last))


def evaluate(interp: "Interpreter") -> int:
    """One pass over the pushed triggers (module docstring, "Evaluation points"): each that
    fits is taken, then its ``on_fire`` runs. Returns how many fired. Raises a failing
    condition's ``StoryError``."""
    table = _table(interp)
    if not table.pushed or table.busy:
        return 0
    table.busy = True
    count = 0
    try:
        for trigger, on_fire in table.pushed:
            found = fits(interp, trigger)
            if found is None:
                continue
            take(interp, found)
            try:
                on_fire(interp, found)
            except AuthorRefusal as e:
                raise interp._map(e, trigger.at) from None
            count += 1
    finally:
        table.busy = False
    return count


def scene_entered(interp: "Interpreter") -> bool:
    """Evaluation point 2 (``Interpreter._enter``): count down each armed ``after N scenes``,
    then ``evaluate``. A failing condition fails the story here (``_fail``) and this returns
    False, so the caller stops."""
    state = interp.triggers
    if any(a.scenes is not None for a in state.armed):
        interp.triggers = TriggerState(tuple(
            a if a.scenes is None else Armed(a.id, a.day, a.scenes - 1 or None, a.data, a.part)
            for a in state.armed), state.retired)
    try:
        evaluate(interp)
    except StoryError as e:
        interp._fail(e)
        return False
    return True


def _on_clock(interp: "Interpreter", event: clock_mod.ClockChanged) -> None:
    """Evaluation point 1: a failing condition raises to the ``clock`` line's step."""
    evaluate(interp)


def _test(interp: "Interpreter", trigger: Trigger) -> bool:
    """``trigger.when`` as an ``if`` condition runs (module docstring)."""
    when = trigger.when
    assert when is not None
    interp.running.set(trigger.at.file.ref, when)
    try:
        return interp._test(when.code)
    except KeyboardInterrupt as e:
        if interp.guard.consume_fired():
            raise timeout_error(trigger.at, e, program=interp.program) from None
        raise
    except StoryError:
        raise
    except BaseException as e:                          # author code; SystemExit included
        raise interp._map(e, trigger.at) from None


clock_mod.listen(_on_clock)


__all__ = ["ARMED_MAX", "Armed", "EMPTY_TRIGGERS", "Fired", "Kind", "RETIRED_MAX",
           "TriggerState", "TriggerTable", "arm", "data_problem", "disarm", "due", "evaluate",
           "first_fit", "fits", "install", "is_armed", "is_retired", "pick", "register_kind",
           "restored", "retire", "scene_entered", "take", "triggers_json", "unregister_kind"]
