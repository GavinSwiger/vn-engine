"""Screen effects and moments in the runtime (F09 ``04-technical.md`` §5.3, §6.1;
PR-F09-02, 03, 10..13, 16; SR-F09-04..06).

Why this module exists: what the player sees changes only at a *moment*: a line or choice
(a checkpoint), a ``with``, or a ``pause``. ``shake`` and ``flash`` only fill the
interpreter's pending slots (the last of each wins), which the next moment's
``flush_stage`` holds right after its ``ShowStage``. A ``with`` ends a moment: everything
changed since the picture last shown appears in its one ``ShowStage``, through its
transition, and the story waits until it has been drawn (``begin_wait``, no snapshot). A
moment whose picture equals the one on screen takes no time: its effects ride the next
burst. ``pause`` shows the moment as a cut and waits for its time or an advance.

None of these executors registers a presenter, so none is a checkpoint type. The runtime
reads no clock: a wait ends by ``WaitDone`` (headless runs post it themselves).

Pure (TR-F03-05). Below the interpreter, like ``stage.py``: ``Step`` is imported when an
executor first runs.
"""

from typing import TYPE_CHECKING

from engine.runtime.commands import Flash as FlashCommand
from engine.runtime.commands import Shake as ShakeCommand
from engine.runtime.stage import flush_stage, stage_changed
from engine.script.effects import Flash, Pause, Shake
from engine.script.nodes import Statement

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.transitions import TransitionSpec


def _continue() -> "Step":
    from engine.runtime.interpreter import Step     # below the interpreter (docstring)
    return Step.CONTINUE


def moment(interp: "Interpreter", stmt: Statement, spec: "TransitionSpec | None") -> "Step":
    """A ``with`` ends a moment (04 §6.1): when the stage differs from the picture on
    screen, hold its ``ShowStage`` through ``spec`` (None: a cut, which still waits until
    drawn once) and the pending effects, then wait for the stage. An unchanged picture
    takes no time and holds nothing: its effects wait for the next moment, so the burst
    order stays ``[ShowStage] [Shake] [Flash]``."""
    if not stage_changed(interp):
        return _continue()
    flush_stage(interp, transition=spec)
    return interp.begin_wait(stmt, seconds=None, for_stage=True)


def run_shake(interp: "Interpreter", stmt: Shake) -> "Step":
    interp.pending_shake = ShakeCommand(stmt.size, stmt.direction, stmt.seconds)
    return _continue()


def run_flash(interp: "Interpreter", stmt: Flash) -> "Step":
    interp.pending_flash = FlashCommand(stmt.color, stmt.seconds, stmt.sid)
    return _continue()


def run_pause(interp: "Interpreter", stmt: Pause) -> "Step":
    """Show the moment as a cut (with any pending effects), then wait ``seconds`` or, with
    none, for an advance."""
    flush_stage(interp)
    return interp.begin_wait(stmt, seconds=stmt.seconds, for_stage=False)


__all__ = ["moment", "run_flash", "run_pause", "run_shake"]
