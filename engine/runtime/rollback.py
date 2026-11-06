"""Rollback at run time (F14 ``04-technical.md`` §4, §6.3, §7.1–§7.3, §7.6, §12; 07 I-5, I-6,
I-11, I-13).

Why this module exists: the player steps back through lines and menus already seen, and the
author controls how far with ``rollback block|off|on|fixed``. It holds:

- ``RollbackState``, ``GameState.rollback``: ``{"enabled": <bool>}``, always written,
  optional on read (a state from before F14 loads as ``ROLLBACK_ON``). ``from_json`` accepts
  exactly that key with a real ``bool``; anything else is ``StateInvalid("rollback")``, never
  echoed. It returns one of the two constants.
- ``Timeline`` (runtime-only, never saved): the very ``GameState`` objects
  ``take_checkpoint`` built (TR-F14-01; no second copy), at most ``depth + 1`` of them.
  ``states[0..cursor]`` were reached on the current path; ``states[cursor+1..]`` is the
  remembered future, only matched and counted, never restored or shown (§7.1). ``record`` is
  checkpoint step 4b; ``reset`` is new game's and every non-landing restore's (G12);
  ``land`` is a back landing's (restore's commit with ``landing=True``); ``view`` is what the
  presentation reads (§7.6); ``carry`` puts an updated preview's earlier steps before the
  resumed one (F39 PR-F39-08). With ``defer_release`` (set by the App, 07 I-11) the states it
  drops wait in a queue that ``release`` frees a few at a time, once per frame.
- ``same_step``: "the story arrived at the remembered step" (§7.3), a loose compare that is
  safe because the remembered future is never shown.
- ``ROLLBACK_PAUSES`` (07 I-13): predicates other features register (F19's ending card, F23's
  minigame). While any is true, back is refused and nothing is ahead (forward is ignored).
- ``CHAIN_STOPS`` (F23 A1): statement types a forward chain never passes; a checkpoint at one
  is the chain's last landing. Empty here; F23 s2 adds ``Minigame``.
- ``fix_menu`` (§7.5, 07 I-7): a ``rollback fixed`` menu reached with a remembered future
  offers only the remembered pick. F51: any menu read again in the past loses its time
  limit (step 0).
- ``run_rollback`` (the executor, §6.3), ``on_step_back`` (the ``StepBack`` handler, §7.3)
  and ``on_step_forward`` (the ``StepForward`` handler, §7.4), registered by the interpreter,
  which runs the forward chain itself (``_forward_once``, ``_land_replay``).

Layering (as ``chapters.py``): ``state.py`` holds a ``RollbackState``, so this module imports
``state`` and the interpreter only under ``TYPE_CHECKING`` or inside a function (07 I-6). Pure
(TR-F03-05): no file, clock, randomness, or thread.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.runtime.commands import RollbackView, ShowMenu, StepBack, StepForward
from engine.script.menu import Menu
from engine.script.messages import format_message
from engine.script.rollback import Rollback

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.state import GameState

DEPTH_MAX: Final = 1_000                 # [rollback] steps, and headless N (04 §12, §13)
DEFAULT_DEPTH: Final = 100               # [rollback] steps when config.toml has none
RELEASE_PER_PUMP: Final = 8              # 07 I-11: queued dropped states freed per frame

_log = get_logger("runtime")


# --- The state (GameState.rollback) -------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RollbackState:
    """``GameState.rollback``: ``enabled`` is False between ``rollback off`` and
    ``rollback on``."""

    enabled: bool = True

    def to_json(self) -> dict[str, object]:
        return {"enabled": self.enabled}

    @staticmethod
    def from_json(obj: object) -> "RollbackState":
        """Validate untrusted ``obj``: exactly ``{"enabled": true | false}``, else
        ``StateInvalid("rollback")``. Returns ``ROLLBACK_ON`` or ``ROLLBACK_OFF``."""
        from engine.runtime.state import StateInvalid   # state.py imports this module
        if type(obj) is not dict or obj.keys() != {"enabled"}:
            raise StateInvalid("rollback")
        enabled = obj["enabled"]
        if type(enabled) is not bool:
            raise StateInvalid("rollback")
        return ROLLBACK_ON if enabled else ROLLBACK_OFF


ROLLBACK_ON: Final = RollbackState(True)
ROLLBACK_OFF: Final = RollbackState(False)


# --- Pauses (07 I-13; A2) -----------------------------------------------------------------------

# While any predicate is true, ``view`` has no room and nothing ahead: a back request is
# refused (the limit cue) and a forward one ignored. A feature appends its own once, at import
# (F19 ``ending_in_progress``, F23 ``minigame_used``); a predicate only reads.
ROLLBACK_PAUSES: list[Callable[["Interpreter"], bool]] = []


def paused(interp: "Interpreter") -> bool:
    """Whether a registered pause holds rollback now."""
    return any(pause(interp) for pause in ROLLBACK_PAUSES)


# --- Chain stops (F23 A1, A5) -------------------------------------------------------------------

# Statement types a forward chain stops at: a checkpoint at one is the chain's last landing,
# whatever is left of the count. A feature adds its type once, at import (F23 s2:
# ``Minigame``). Forward at such a step then does nothing (``_forward_once`` has no branch
# for it).
CHAIN_STOPS: set[type] = set()


# --- The timeline (runtime-only) ----------------------------------------------------------------

class Timeline:
    """The steps the player can go back to (04 §4). ``depth`` is ``[rollback] steps`` (0
    turns rollback off for the game: nothing is kept). ``cursor`` is the interpreter's step
    (-1: empty); ``shown`` the step drawn (``cursor``, except during step 3's forward chain).
    ``block_pending``: a wall applies to the next checkpoint. ``replay``/``replaying``: the
    forward chain (F14 step 3). The counters only count up: ``refused`` (back requests that
    couldn't move: the limit cue), ``landings`` (real rollback steps), and ``matches``
    (checkpoints that matched the remembered next step); the driver reports both of the
    last to F11 (F18 I-6).

    07 I-11: a load, New Game, a wall or PR-F14-23's drop can let go of up to ``depth + 1``
    states at once, and freeing them all in one frame costs several ms at the default depth.
    With ``defer_release`` (False by default: headless runs and tests free at once) every
    dropped state joins a queue instead, and ``release`` frees a few per call (the App calls
    it once per frame). A drop that arrives before the queue is empty joins it; past
    ``depth + 1`` queued states the oldest are freed at once, so the queue never holds more
    than one full timeline. The queue belongs to the timeline, so it goes with the
    interpreter; the App also empties it at shutdown."""

    __slots__ = ("depth", "states", "cursor", "shown", "block_pending", "replay", "replaying",
                 "refused", "landings", "matches", "defer_release", "_dropped", "_use",
                 "_uses")

    def __init__(self, depth: int) -> None:
        assert type(depth) is int and 0 <= depth <= DEPTH_MAX, "depth outside 0..1000"
        self.depth = depth
        self.states: list[GameState] = []
        self.cursor = -1
        self.shown = -1
        self.block_pending = False
        self.replay = 0
        self.replaying = False
        self.refused = 0
        self.landings = 0
        self.matches = 0
        self.defer_release = False
        self._dropped: list[GameState] = []
        # F64 round 2: the item a use started since the last step (``note_use``), and, per
        # kept step reached through a use, that item (by the state's id, with the state).
        self._use: str | None = None
        self._uses: dict[int, tuple[GameState, str]] = {}

    @property
    def dropped(self) -> int:
        """07 I-11: dropped states not freed yet (always 0 without ``defer_release``)."""
        return len(self._dropped)

    def release(self, n: int | None = RELEASE_PER_PUMP) -> int:
        """07 I-11: free up to ``n`` queued dropped states, newest first (None: all of
        them); returns how many went. The queue holds the engine's last reference to each,
        so this is where their memory is freed."""
        pending = self._dropped
        if not pending:
            return 0
        keep = 0 if n is None else max(0, len(pending) - n)
        gone = len(pending) - keep
        del pending[keep:]
        return gone

    def _let_go(self, states: "list[GameState]") -> None:
        """Queue ``states`` (just dropped from the timeline) when releases are deferred;
        else nothing: the caller's list holds their last reference."""
        if not self.defer_release or not states:
            return
        pending = self._dropped
        pending.extend(states)
        extra = len(pending) - (self.depth + 1)
        if extra > 0:                                   # at most one full timeline queued
            del pending[:extra]

    def reset(self, state: "GameState | None") -> None:
        """New game (None: empty) and every OK restore that isn't a landing (``[state]``;
        G12, TR-F14-03). Clears the wall and the chain; the counters keep counting. The old
        list (up to ``depth + 1`` states) is freed at once, or queued (07 I-11)."""
        keep = state is not None and self.depth > 0
        old = self.states
        self.states = [state] if keep else []           # type: ignore[list-item]
        self._let_go(old)
        self.cursor = self.shown = 0 if keep else -1
        self.block_pending = False
        self.replay = 0
        self.replaying = False
        self._use = None
        self._uses.clear()

    def record(self, state: "GameState") -> bool:
        """Checkpoint step 4b (§7.2): keep ``state`` (the object itself, TR-F14-01) as the
        current step. True if it matched the remembered next step, which keeps the
        remembered future; else that future is dropped. A wall (``rollback block``, rollback
        off, on-from-off) makes it the earliest step; the depth trims the oldest."""
        assert self.cursor >= -1, "cursor below -1"
        if self.depth == 0:
            return False
        wall = self.block_pending or not state.rollback.enabled
        self.block_pending = False
        states = self.states
        nxt = self.cursor + 1
        use, self._use = self._use, None
        if nxt < len(states) and same_step(state, states[nxt]):
            found = self._uses.pop(id(states[nxt]), None)       # F64: keep a use's mark
            if use is None and found is not None:
                use = found[1]
            states[nxt] = state
            self.cursor = nxt
            self.matches += 1
            matched = True
        else:
            del states[nxt:]
            states.append(state)
            self.cursor = len(states) - 1
            matched = False
        if use is not None:
            self._mark_use(state, use)
        if wall and self.cursor > 0:
            drop = self.cursor
            self._let_go(states[:drop])
            del states[:drop]
            self.cursor = 0
            self.shown -= drop
        extra = len(states) - 1 - self.depth
        if extra > 0:                                   # only on a new step: cursor is newest
            self._let_go(states[:extra])
            del states[:extra]
            self.cursor -= extra
            self.shown -= extra
        return matched

    def note_use(self, item: str) -> None:
        """F64 round 2: a use of ``item`` started; the next step recorded is its."""
        self._use = item

    def _mark_use(self, state: "GameState", item: str) -> None:
        uses = self._uses
        if len(uses) >= 2 * (self.depth + 1):             # forget steps no longer kept
            kept = {id(s) for s in self.states}
            for key in [k for k in uses if k not in kept]:
                del uses[key]
        uses[id(state)] = (state, item)

    def remembered_use(self) -> str | None:
        """F64 round 2: the item whose use led to the remembered next step, or None."""
        nxt = self.cursor + 1
        if self.cursor < 0 or nxt >= len(self.states):
            return None
        found = self._uses.get(id(self.states[nxt]))
        return found[1] if found is not None and found[0] is self.states[nxt] else None

    def land(self, state: "GameState", snapshot: "GameState") -> None:
        """A back landing committed (restore's step 6 with ``landing``): the kept step
        ``state`` (the object ``on_step_back`` restored, at or before the shown step) becomes
        the current and shown step and holds the restore's new snapshot."""
        states = self.states
        i = max(self.cursor, self.shown)
        while i >= 0 and states[i] is not state:
            i -= 1
        assert i >= 0, "a landing restores a kept step at or before the current one"
        found = self._uses.pop(id(state), None)              # F64: the mark stays with it
        if found is not None:
            self._uses[id(snapshot)] = (snapshot, found[1])
        self._use = None
        states[i] = snapshot
        self.cursor = self.shown = i
        self.landings += 1

    def carry(self, older: "Sequence[GameState]") -> int:
        """F39 (PR-F39-08): an updated preview resumed at the current step; ``older`` are
        the earlier steps carried over from the old child, **newest first**. They go before
        the current step, oldest first, trimmed so at most ``depth`` stand before it (the
        newest are kept). Carries nothing at depth 0, with an empty timeline, or when the
        current step has rollback off (it is a wall, 04 §7.2). The remembered future stays
        (a resume has none). A carried step whose line is gone stays: Back stops there with
        W90 and drops it with every older step (PR-F14-23). Returns how many went in."""
        if self.depth == 0 or self.cursor < 0 or not older:
            return 0
        if not self.states[self.cursor].rollback.enabled:
            return 0
        room = self.depth - self.cursor
        if room <= 0:
            return 0
        added = list(older[:room])
        added.reverse()
        self.states[:0] = added
        n = len(added)
        self.cursor += n
        self.shown += n
        extra = len(self.states) - 1 - self.depth       # the remembered future past depth
        if extra > 0:
            self._let_go(self.states[len(self.states) - extra:])
            del self.states[len(self.states) - extra:]
        return n

    def remembered_pick(self, menu_sid: str) -> str | None:
        """§7.4: the key of the last pick in the remembered next step, if that pick was made
        at the menu ``menu_sid`` (exactly one pick happens between a menu step and the next,
        so it is the last one, even past F07's cap); else None."""
        nxt = self.cursor + 1
        if self.cursor < 0 or nxt >= len(self.states):
            return None
        picks = self.states[nxt].choices.picks
        if not picks or picks[-1].menu != menu_sid:
            return None
        return picks[-1].choice

    def remembered_item(self) -> str | None:
        """F64: the item the remembered next step's pick showed at a ``present:`` option
        (None for any other pick, or no remembered step)."""
        nxt = self.cursor + 1
        if self.cursor < 0 or nxt >= len(self.states):
            return None
        picks = self.states[nxt].choices.picks
        return picks[-1].item if picks else None

    def drop_through(self, target: int) -> None:
        """PR-F14-23: ``states[target]`` can't be restored, so it and every older step go."""
        n = target + 1
        self._let_go(self.states[:n])
        del self.states[:n]
        self.cursor -= n
        self.shown -= n

    def view(self, interp: "Interpreter") -> RollbackView:
        """§7.6, O(1): Back's room and the steps ahead. No room when the story isn't live
        (ENDED, FAILED: the end fade, the error screen), at a wall, with rollback off, or
        while a pause holds (07 I-13, which also hides the steps ahead)."""
        if self.depth == 0:
            return RollbackView(False, False, 0, 0, self.refused)
        from engine.runtime.interpreter import Status   # the interpreter imports this module
        cursor = self.cursor
        hold = paused(interp)
        live = interp.status is Status.WAITING or interp.status is Status.RUNNING
        if (not live or cursor < 0 or hold or self.block_pending
                or not interp.rollback_state.enabled):
            room = 0
        elif self.replay > 0:
            room = max(0, self.shown)
        else:
            room = cursor + (0 if resting(interp) else 1)
        ahead = 0
        if cursor >= 0 and not hold:
            ahead = len(self.states) - 1 - (self.shown if self.replay > 0 else cursor)
        return RollbackView(True, room > 0, room, max(0, ahead), self.refused)


def resting(interp: "Interpreter") -> bool:
    """§7.3: the story waits at its current step (no F09 wait, no forward chain). When it
    doesn't (mid-run, in a transition or pause), the first back notch lands on the current
    step itself."""
    from engine.runtime.interpreter import Status   # the interpreter imports this module
    return (interp.status is Status.WAITING and interp.waiting_for is None
            and interp.timeline.replay == 0)


def same_step(a: "GameState", b: "GameState") -> bool:
    """§7.3: "the story arrived at the remembered step". Every ``GameState`` field with
    plain ``==`` (a later field joins with no change here) except ``history`` (it follows
    from the rest) and ``variables``, compared last by one C-level mapping compare. Python's
    ``==`` (``1 == 1.0``) is loose on purpose: a missed difference only keeps an expectation,
    never shows a wrong step (§7.1)."""
    for f in fields(a):
        name = f.name
        if name == "variables" or name == "history":
            continue
        if getattr(a, name) != getattr(b, name):
            return False
    va, vb = a.variables, b.variables
    return len(va) == len(vb) and va == vb


def fix_menu(interp: "Interpreter", stmt: Menu, cmd: ShowMenu) -> ShowMenu:
    """§7.5 (07 I-7): at a ``rollback fixed`` menu with a remembered future, only the
    remembered pick stays pickable. The other shown choices are locked in ``cmd`` (whatever
    ``[choice] show_locked`` says), in the waiting ``choices``, and in ``menu_open``. Called
    at a matched checkpoint (step 4c) and at every landing (``_hold_restored``), after the
    snapshot, so ``checkpoint()`` and a save made there hold the normal menu. A menu that
    isn't fixed, has no remembered pick, or whose pick isn't pickable now keeps ``cmd``.

    F51 step 0 (04 §2 OQ-1, 07 I-7): at any menu the player has picked at and is now reading
    again (a remembered future with a pick at this sid), the time limit is dropped: one
    command without ``seconds`` and ``timeout``, in ``cmd`` and ``menu_open`` alike. A load,
    jump or replay resets the timeline, so the test is false there."""
    t = interp.timeline
    past = 0 <= t.cursor < len(t.states) - 1
    if past and cmd.seconds is not None and t.remembered_pick(stmt.sid) is not None:
        cmd = replace(cmd, seconds=None, timeout=None)
        if interp.menu_open is not None:
            interp.menu_open = (cmd, interp.menu_open[1])
    if not stmt.fixed or not past:
        return cmd
    key = t.remembered_pick(stmt.sid)
    waiting = interp.choices.waiting
    if key is None or waiting is None or key not in waiting.pickable:
        return cmd
    shown = [c.key for c in cmd.choices]                    # script order
    interp.choices = replace(interp.choices, waiting=replace(
        waiting, pickable=(key,), locked=tuple(k for k in shown if k != key)))
    fixed = replace(cmd, choices=tuple(replace(c, locked=c.key != key) for c in cmd.choices))
    if interp.menu_open is not None:
        interp.menu_open = (fixed, interp.menu_open[1])
    return fixed


# --- The statement (04 §6.3) ----------------------------------------------------------------------

def run_rollback(interp: "Interpreter", stmt: Rollback) -> "Step":
    """``block``: a wall at the next checkpoint. ``off``: rollback off. ``on``: rollback on,
    with a wall when it was off. ``fixed``: nothing (``Menu.fixed`` is static)."""
    from engine.runtime.interpreter import Step     # the interpreter imports this module
    word = stmt.word
    if word == "block":
        interp.timeline.block_pending = True
    elif word == "off":
        interp.rollback_state = ROLLBACK_OFF
    elif word == "on":
        if not interp.rollback_state.enabled:
            interp.timeline.block_pending = True
        interp.rollback_state = ROLLBACK_ON
    return Step.CONTINUE


# --- Back (04 §7.3, §12) ------------------------------------------------------------------------------

def count_ok(count: object) -> bool:
    """A ``StepBack``/``StepForward`` count: an ``int`` (not a bool) from 1 to 1,000."""
    return type(count) is int and 1 <= count <= DEPTH_MAX


# W90's cause, by the restore's result (04 §12).
_CAUSES: Final = {"position_not_found": "position", "scheme_mismatch": "scheme",
                  "default_failed": "default"}


def on_step_back(interp: "Interpreter", event: StepBack) -> None:
    """Go back ``count`` steps, clamped to the room (§7.6): one restore of the target in
    the load form (``restore(..., landing=True)``). No room, or notches past it, add to
    ``refused`` (the cue). A target that can't be restored is dropped with every older step
    (PR-F14-23, W90), and the player stays on the shown step. At depth 0 nothing happens."""
    count = event.count
    if not count_ok(count):
        _log.debug("StepBack ignored: the count isn't a whole number from 1 to %d.", DEPTH_MAX)
        return
    t = interp.timeline
    if t.depth == 0:
        return
    room = t.view(interp).back_room
    if room == 0:
        t.refused += 1
        return
    n = min(count, room)
    base = t.shown if t.replay > 0 else t.cursor
    target = base - n + (1 if not resting(interp) and t.replay == 0 else 0)
    if count > room:
        t.refused += 1                                   # the extra notches couldn't move
    state = t.states[target]
    outcome = interp.restore(state, landing=True)
    result = outcome.result.value
    if result == "ok":
        return                                           # restore's commit did the rest
    t.drop_through(target)
    t.refused += 1
    if interp.dev or result != "default_failed":         # release: F03's ERROR is the record
        at = state.position_at
        label = at[0] if type(at) is tuple and at and type(at[0]) is str else "?"
        _log.warning("%s", format_message("W90", (label, _CAUSES[result])),
                     extra={"code": "W90"})


# --- Forward (04 §7.4; 07 I-4, I-13) ------------------------------------------------------------

def on_step_forward(interp: "Interpreter", event: StepForward) -> None:
    """Re-run the script quietly ``count`` steps along the remembered path, clamped to the
    steps ahead: ``Interpreter.run`` chains the steps and the chain lands once, in the
    restore form (``_land_replay``). Ignored with nothing ahead, while a chain runs, while a
    pause holds (07 I-13), when the story isn't live, and at depth 0. A story that waits
    takes its first forward step here (``_forward_once``); one that is running (sliced
    mid-step) turns quiet from here on."""
    count = event.count
    if not count_ok(count):
        _log.debug("StepForward ignored: the count isn't a whole number from 1 to %d.",
                   DEPTH_MAX)
        return
    from engine.runtime.interpreter import Status   # the interpreter imports this module
    t = interp.timeline
    status = interp.status
    if t.depth == 0 or (status is not Status.WAITING and status is not Status.RUNNING):
        return
    ahead = len(t.states) - 1 - t.cursor
    if t.cursor < 0 or ahead <= 0 or t.replay > 0 or paused(interp):
        return
    t.replay = min(count, ahead)
    t.shown = t.cursor
    if status is Status.WAITING:
        interp._forward_once()
    else:
        t.replaying = True


__all__ = ["CHAIN_STOPS", "DEFAULT_DEPTH", "DEPTH_MAX", "RELEASE_PER_PUMP", "ROLLBACK_OFF",
           "ROLLBACK_ON", "ROLLBACK_PAUSES", "RollbackState", "Timeline", "count_ok", "fix_menu",
           "on_step_back", "on_step_forward", "paused", "resting", "run_rollback",
           "same_step"]
