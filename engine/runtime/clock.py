"""The story clock at run time (F63 round 1, specs/F63-story-clock/SPEC.md).

Why this module exists: story time is saved story state, so it lives in ``GameState`` (saves,
loads and rollback restore it exactly) and changes only through ``clock`` lines; author Python
reads it through the read-only ``clock`` view. Other systems react to it through one hook,
``ClockChanged``.

- ``ClockState`` is ``GameState.clock``: ``day`` and ``part`` (an index into the calendar's
  parts), and (round 2) ``shown``: ``show clock`` put the clock in the status corner.
  ``EMPTY_CLOCK`` (day 0) means "where the calendar starts": nothing has moved the clock, so
  a save of a game that never uses it writes nothing new (``clock_json``) and an older save
  loads as the start. JSON ``{"day": int, "part": int}`` plus ``"shown": true`` while shown
  (day 0 with part 0 then: shown, never moved); ``from_json`` refuses anything else with
  ``StateInvalid("clock")``.
- ``now(interp)``: the clock as it stands, never empty (a part past a calendar that has
  fewer parts now is its last part).
- ``run_clock`` is the ``ClockStep`` executor; not a checkpoint. Round 2: when the day
  changes it plays the **day card** (below). ``run_clock_show`` is ``show clock`` /
  ``hide clock``'s: it sets ``shown`` and announces nothing (time didn't move).
- ``ClockView`` is the built-in name ``clock`` (``bind_view`` puts it in ``G``'s builtins, so a
  game's own ``clock`` variable or character simply hides it: ADR-0010, no reserved name).
  ``clock.day``, ``part``, ``weekday``, ``date``, ``month``, ``season`` and
  ``days_left(target=None)``; every write is E435.

**ClockChanged** (skins contract, "The clock announces itself"): every ``clock`` line that
changes story time calls each function given to ``listen`` once, in order, with the
interpreter and ``ClockChanged(old, new)`` (both as ``now`` gives them, so never empty), right
after the change and before the next line runs. A line that leaves the clock where it was
(``clock go to Night`` at night) announces nothing. Load, restore, going back (F14) and New
Game set the clock without announcing it: they put back a moment, nothing happens in it.
F14's quiet forward re-run (``interp.timeline.replaying``) runs the ``clock`` lines again and
so announces again: a listener that changes story state must, so the re-run ends exactly
where the first run did; a listener that shows something checks ``replaying`` and stays
quiet. The app's corner clock listens (round 2); the trigger core and Inbox delays will.

**The day card** (round 2). A ``clock`` line that changes the day plays a card with the new
date (``Calendar.date``: ``[calendar] day_text`` > the kit's wording) after the listeners, as
a chapter card plays: F18's ``play_card`` (in through ``fade``, ``DAY_CARD_HOLD`` seconds,
out), so a click skips it and skip mode and Reduce motion treat it exactly as a chapter
card. None with ``[calendar] day_card = false``, and none during F14's quiet re-run (the
card is shown, not story state). It is part of the clock line, not a listener: a listener
can't make the story wait.

Layering as ``points.py``: ``state.py`` holds a ``ClockState``, so this module sits below the
interpreter and imports it only when the executor runs.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

from engine.core.storyclock import DAY_MAX, DEFAULT_CALENDAR, Calendar, DateProblem
from engine.runtime.commands import TitleCard
from engine.runtime.errors import AuthorRefusal, StoryError, short_value, where

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.script.clock import ClockStep
    from engine.script.clockshow import ClockShow

WORD_CLOCK: Final = "clock"
DAY_CARD_HOLD: Final = 2.0              # seconds the day card holds (a chapter card's is 3)
DAY_CARD_KIND: Final = "day"            # TitleCard.kind (W110's word)


@dataclass(frozen=True, slots=True)
class ClockState:
    """``GameState.clock`` (module docstring). ``day`` 0 is the calendar's start (never
    moved); ``EMPTY_CLOCK`` is that, not shown."""

    day: int = 0
    part: int = 0
    shown: bool = False

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {"day": self.day, "part": self.part}
        if self.shown:
            out["shown"] = True
        return out

    @staticmethod
    def from_json(obj: object) -> "ClockState":
        """Validate untrusted ``obj``: exactly ``{"day": 1..DAY_MAX, "part": 0..99}``, ints
        (not bools), with ``"shown": true`` or no ``shown``; day 0 only with part 0 and
        shown. Anything else is ``StateInvalid("clock")``, never echoing the input."""
        from engine.runtime.state import StateInvalid   # state.py imports this module
        if type(obj) is not dict or obj.keys() not in ({"day", "part"},
                                                       {"day", "part", "shown"}):
            raise StateInvalid("clock")
        day, part, shown = obj["day"], obj["part"], obj.get("shown", False)
        if type(day) is not int or type(part) is not int or not 0 <= day <= DAY_MAX \
                or not 0 <= part < 100 or ("shown" in obj and shown is not True) \
                or (day == 0 and (part != 0 or not shown)):
            raise StateInvalid("clock")
        return ClockState(day, part, shown)


EMPTY_CLOCK: Final = ClockState()


def clock_json(state: ClockState) -> dict[str, object]:
    """``{"clock": …}`` only once the clock has moved, so other saves are as before F63."""
    return {} if state == EMPTY_CLOCK else {"clock": state.to_json()}


@dataclass(frozen=True, slots=True)
class ClockChanged:
    """Story time changed from ``old`` to ``new`` (never empty states; module docstring)."""

    old: ClockState
    new: ClockState


ClockListener = Callable[["Interpreter", ClockChanged], None]
_LISTENERS: list[ClockListener] = []


def listen(listener: ClockListener) -> None:
    """Call ``listener`` at every ``ClockChanged`` (once per change, in the order added)."""
    _LISTENERS.append(listener)


def unlisten(listener: ClockListener) -> None:
    """Stop calling ``listener`` (nothing if it isn't listening)."""
    if listener in _LISTENERS:
        _LISTENERS.remove(listener)


# --- Reading ---------------------------------------------------------------------------------

def calendar(interp: "Interpreter") -> Calendar:
    """The launch's calendar: ``Program.calendar`` (the loader builds it from config.toml),
    else the defaults."""
    found = getattr(interp.program, "calendar", None)
    return found if isinstance(found, Calendar) else DEFAULT_CALENDAR


def resolved(cal: Calendar, state: ClockState) -> ClockState:
    """``state`` against ``cal``: the start for ``EMPTY_CLOCK``, a part past the last one as
    the last (a calendar with fewer parts than when the game was saved)."""
    if state.day == 0:
        return ClockState(cal.start_day, 0, state.shown)
    return ClockState(state.day, min(state.part, len(cal.parts) - 1), state.shown)


def now(interp: "Interpreter") -> ClockState:
    return resolved(calendar(interp), interp.clock)


def merged(interp: "Interpreter", saved: ClockState) -> ClockState:
    """Restore: the saved clock as it is kept (``EMPTY_CLOCK`` stays empty, so the start
    follows ``[calendar] start``; a part past today's last is the last)."""
    return saved if saved.day == 0 else resolved(calendar(interp), saved)


# --- The executor ----------------------------------------------------------------------------

def target(cal: Calendar, at: ClockState, stmt: "ClockStep") -> ClockState:
    """Where ``stmt`` takes the clock from ``at`` (``DateProblem`` when it can't)."""
    if stmt.action == "next":
        if at.part + 1 < len(cal.parts):
            return ClockState(at.day, at.part + 1, at.shown)
        day, part = at.day + 1, 0
    elif stmt.action == "next_day":
        day, part = at.day + 1, 0
    else:
        day, part = cal.go_to(at.day, at.part, day=stmt.day, text=stmt.text, part=stmt.part)
    if day > DAY_MAX:
        raise DateProblem("max", str(day))
    return ClockState(day, part, at.shown)


def run_clock(interp: "Interpreter", stmt: "ClockStep") -> "Step":
    """``clock next`` / ``clock next day`` / ``clock go to …``: move story time and announce
    the change (module docstring). A date or part the calendar doesn't have (a config changed
    since the load's checks) is a story error, E435."""
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    cal = calendar(interp)
    old = resolved(cal, interp.clock)
    try:
        new = target(cal, old, stmt)
    except DateProblem as problem:
        from engine.script.messages import format_message
        raise StoryError(format_message("E435", (problem.form, problem.text)), code="E435",
                         **where(stmt)) from None
    if new != old:
        interp.clock = new
        event = ClockChanged(old, new)
        for listener in tuple(_LISTENERS):
            listener(interp, event)
        if new.day != old.day and cal.day_card and not interp.timeline.replaying:
            return _day_card(interp, cal, new)
    return Step.CONTINUE


def day_card(cal: Calendar, day: int) -> TitleCard:
    """The card a new ``day`` shows (module docstring, "The day card")."""
    date = cal.date(day)
    return TitleCard(date, None, date, kind=DAY_CARD_KIND)


def _day_card(interp: "Interpreter", cal: Calendar, new: ClockState) -> "Step":
    from engine.runtime.chapters import play_card       # chapters reads the stage
    return play_card(interp, day_card(cal, new.day), DAY_CARD_HOLD, None,
                     after_hold=_card_out)


def _card_out(interp: "Interpreter") -> "Step":
    """The day card goes out through the same fade to the stage, then the next line."""
    from engine.runtime.chapters import card_transition
    from engine.runtime.stage import flush_stage
    stmt = interp.current
    assert stmt is not None
    flush_stage(interp, transition=card_transition(interp, None, stmt.sid))
    return interp.begin_wait(stmt, for_stage=True)


def run_clock_show(interp: "Interpreter", stmt: "ClockShow") -> "Step":
    """``show clock`` / ``hide clock``: the clock in the status corner or not (saved in
    ``GameState.clock``; the app's corner follows it). No ``ClockChanged``."""
    from engine.runtime.interpreter import Step         # below the interpreter (docstring)
    if interp.clock.shown != stmt.shown:
        interp.clock = replace(interp.clock, shown=stmt.shown)
    return Step.CONTINUE


# --- The built-in name ``clock`` (ClockView) ---------------------------------------------------

class ClockView:
    """``clock`` in author Python: reads only (module docstring)."""

    __slots__ = ("_interp",)

    def __init__(self, interp: "Interpreter | None" = None) -> None:
        object.__setattr__(self, "_interp", interp)

    def _now(self) -> tuple[Calendar, ClockState]:
        interp = object.__getattribute__(self, "_interp")
        if interp is None:
            raise AuthorRefusal.of("E435", "define")
        cal = calendar(interp)
        return cal, resolved(cal, interp.clock)

    @property
    def day(self) -> int:
        return self._now()[1].day

    @property
    def part(self) -> str:
        cal, at = self._now()
        return cal.parts[at.part]

    @property
    def weekday(self) -> str:
        cal, at = self._now()
        return cal.weekday(at.day)

    @property
    def date(self) -> str:
        cal, at = self._now()
        return cal.date(at.day)

    @property
    def month(self) -> str:
        cal, at = self._now()
        found = cal.month(at.day)
        return found[0] if found is not None else ""

    @property
    def season(self) -> str:
        cal, at = self._now()
        found = cal.season(at.day)
        return found[0] if found is not None else ""

    def days_left(self, target: object = None) -> int:
        """Days until ``target`` (a day number, or a written date: its next coming), or until
        ``[calendar] last_day`` when none is given; 0 once it has come."""
        cal, at = self._now()
        if target is None:
            if cal.last_day is None:
                raise AuthorRefusal.of("E433", "no_last_day", "")
            day: int | None = cal.last_day
        elif type(target) is int:
            day = target
        elif type(target) is str:
            day = cal.find_date(target, at.day)
            if day is None:
                raise AuthorRefusal.of("E435", "date", target)
        else:
            raise AuthorRefusal.of("E435", "arg", short_value(target))
        return cal.days_left(at.day, day)

    def __setattr__(self, name: str, value: object) -> None:
        raise AuthorRefusal.of("E435", "write", name)

    def __delattr__(self, name: str) -> None:
        raise AuthorRefusal.of("E435", "write", name)

    def __repr__(self) -> str:
        return WORD_CLOCK

    def __dir__(self) -> list[str]:
        return ["date", "day", "days_left", "month", "part", "season", "weekday"]


def bind_view(G: dict, interp: "Interpreter") -> None:
    """Put the ``clock`` view in ``G``'s builtins (not in ``G``: never a story variable, never
    saved, and a game's own ``clock`` hides it)."""
    builtins: Any = G.get("__builtins__")
    if isinstance(builtins, dict):
        builtins[WORD_CLOCK] = ClockView(interp)


def shown_value(interp: "Interpreter", name: str) -> object:
    """``{var=clock.date}``'s value (F05's ``_shown`` for a dotted name): the game's own
    ``clock`` if it has one, else the view. ``KeyError`` when there is neither."""
    root, _, attr = name.partition(".")
    holder = interp.G.get(root)
    if holder is None:
        builtins: Any = interp.G.get("__builtins__")
        holder = builtins.get(root) if isinstance(builtins, dict) else None
    if holder is None:
        raise KeyError(name)
    return getattr(holder, attr)


def uses_clock(program: Any) -> bool:
    """Whether the script has a ``clock`` line or ``show clock`` (here, not in ``app``:
    only ``app/loading.py`` of the app layer imports ``engine.script``, 07 I-7)."""
    from engine.script.clock import ClockStep
    from engine.script.clockshow import ClockShow
    return any(isinstance(stmt, (ClockStep, ClockShow)) for stmt in program.iter_statements())


__all__ = ["ClockChanged", "ClockListener", "ClockState", "ClockView", "DAY_CARD_HOLD",
           "DAY_CARD_KIND", "EMPTY_CLOCK", "bind_view", "calendar", "clock_json", "day_card",
           "listen", "merged", "now", "resolved", "run_clock", "run_clock_show", "shown_value",
           "target", "unlisten", "uses_clock"]
