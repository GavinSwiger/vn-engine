"""``install_clock``: the story clock in the status corner and in save slots (F63 round 2).

Why this module exists: ``show clock`` sets ``GameState.clock.shown`` (saved, rolled back,
restored by a load) and F61's corner owns no game state, so ``ClockCorner`` keeps the corner
in line with it, as ``app/meters.MeterCorner`` does for meters: a corner source
(``StatusCorner.add_source``) that once per frame adds the clock (fading in) when it is shown
and removes it (fading out) when it isn't. The ``ClockItem`` reads the clock every frame, so a
``clock`` line's new day or part shows at once; a ``ClockChanged`` (``runtime/clock.listen``)
also sends one pulse round the clock's panel (none under Reduce motion, none for F14's quiet
re-run, none after going back or a load: those put back a moment).

The corner is ``Calendar.place`` (``[calendar] place`` > the kit's > top right). While NVL is
on the item takes the narrow column that fits beside the text (as meters do).

**New game and load.** ``reset`` is a shell in-game reset: it drops the clock at once and the
next frame puts it back, as a cut, if the restored state shows it.

**Save slots.** ``moment`` gives F11 (``SaveService.set_clock_provider``) the story time of a
save's checkpoint, "Day 4, Evening", for a game whose script uses the clock (a ``clock`` line
or ``show clock``); a game that doesn't keeps its descriptions as they were.
"""

import weakref
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from engine.runtime import clock as clock_mod
from engine.runtime.interpreter import Status
from engine.script.clock import ClockStep
from engine.script.clockshow import ClockShow
from engine.ui.clockitem import ClockItem, ClockReading

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.interpreter import Interpreter
    from engine.runtime.state import GameState
    from engine.script.program import Program

KEY: Final = ("clock",)                 # the corner key (meters use ("meter", name))


def reading(interp: "Interpreter") -> ClockReading:
    """The date and part of the day now, in the calendar's words."""
    cal = clock_mod.calendar(interp)
    at = clock_mod.now(interp)
    return ClockReading(cal.date(at.day), cal.parts[at.part])


def uses_clock(program: "Program") -> bool:
    """Whether the script has a ``clock`` line or ``show clock``."""
    return any(isinstance(stmt, (ClockStep, ClockShow)) for stmt in program.iter_statements())


class ClockCorner:
    """The clock's side of the corner (module docstring)."""

    def __init__(self, app: "App", interp: "Interpreter") -> None:
        self.app = app
        self.interp = interp
        self._cut = True                    # the first fill and every refill are cuts
        self._changed = False               # a ClockChanged since the last frame
        self._uses: tuple[int, bool] | None = None      # (id(program), uses_clock)

    @property
    def corner(self):
        return self.app.shell.corner

    def heard(self, interp: "Interpreter", _event: clock_mod.ClockChanged) -> None:
        """``ClockChanged``: pulse at the next frame (not for F14's quiet re-run)."""
        if interp is self.interp and not interp.timeline.replaying:
            self._changed = True

    def _narrow(self) -> float | None:
        from engine.app.meters import MeterCorner
        return MeterCorner._narrow(self)                # the same column as the meters'

    def wanted(self) -> bool:
        return self.interp.status is not Status.IDLE and self.interp.clock.shown

    def sync(self) -> None:
        """Bring the corner in line with ``clock.shown`` (module docstring)."""
        corner, cut = self.corner, self._cut
        self._cut = False
        changed, self._changed = self._changed, False
        here = KEY in corner.keys()
        if not self.wanted():
            if here:
                corner.remove_item(KEY, fade=not cut)
            return
        if not here:
            place = clock_mod.calendar(self.interp).place
            corner.set_item(KEY, place, ClockItem(lambda: reading(self.interp),
                                                  narrow=self._narrow), fade=not cut)
        elif changed and not cut:
            corner.pulse(KEY)

    def reset(self) -> None:
        """A shell in-game reset: drop the clock at once; the next frame refills it."""
        if KEY in self.corner.keys():
            self.corner.remove_item(KEY, fade=False)
        self._cut = True
        self._changed = False

    def moment(self, state: "GameState") -> str | None:
        """F11's clock provider: "Day 4, Evening" at ``state``, for a game using the clock."""
        program = self.interp.program
        if self._uses is None or self._uses[0] != id(program):
            self._uses = (id(program), uses_clock(program))
        if not self._uses[1]:
            return None
        cal = clock_mod.calendar(self.interp)
        at = clock_mod.resolved(cal, state.clock)
        return cal.moment(at.day, at.part)


def _listener(owner: ClockCorner) -> Callable[..., None]:
    """A ``ClockChanged`` listener that holds ``owner`` weakly and stops when it is gone (the
    hook is the runtime's, for every launch in the process)."""
    ref = weakref.ref(owner)

    def listener(interp: "Interpreter", event: clock_mod.ClockChanged) -> None:
        found = ref()
        if found is None:
            clock_mod.unlisten(listener)
        else:
            found.heard(interp, event)
    return listener


def install_clock(app: "App", interp: "Interpreter") -> ClockCorner | None:
    """Every launch with a shell: the corner's clock source, its in-game reset, the pulse's
    listener and F11's clock provider."""
    shell = getattr(app, "shell", None)
    corner = getattr(shell, "corner", None)
    if corner is None:
        return None
    owner = ClockCorner(app, interp)
    corner.add_source(owner.sync)
    shell.add_in_game_reset(owner.reset)
    clock_mod.listen(_listener(owner))
    saves = getattr(app, "saves", None)
    if saves is not None:
        saves.set_clock_provider(owner.moment)
    return owner


__all__ = ["ClockCorner", "KEY", "install_clock", "reading", "uses_clock"]
