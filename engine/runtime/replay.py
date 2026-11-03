"""Scene replays at run time: the F12 unlock kind ``"replay"`` and the replay run (F36
``04-technical.md`` §3, §7.3; ``07`` I-9, I-10; run warning W229).

Why this module exists: a replay plays one scene as a throwaway game and must change nothing
the player keeps, and a scene unlocks the first time the player reaches it. The unlock record
is an F12 unlock kind (lasting across playthroughs, never ``GameState``); the replay itself
is **run-time only**: ``interp.replay`` (a ``ReplayRun``, or None) lives on the interpreter,
is never saved or snapshotted, and survives F14's restores (``_reset_runtime`` doesn't touch
it). While it is set the store is in F12's sandbox (``begin_sandbox`` at the start,
``end_sandbox`` at the end), so whatever the replay does to persistent data is put back,
except the kinds registered ``replay_keeps`` (F35's tracks, F37's achievements).

- ``register(interp)`` (``Interpreter.__init__``, after F34's line; F39 again with a new
  program): ``interp.replays`` (the ``ReplayIndex``) and the kind, revocable, ``known`` = the
  index. Safe to repeat.
- ``run_for(program, label)``: the ``ReplayRun`` for ``label``: a declared replay's ``to`` and
  starting values apply, else the label alone (an ending's replay, dev ``--replay``).
- ``arrive(interp, label)`` (``_enter``, one dict lookup): a declared scene is unlocked, but
  not in a replay and not during F14's quiet forward re-run (``timeline.replaying``); loads,
  rollback landings and flowchart jumps never enter a label.
- ``ends_at(interp, label)`` (``_enter``, only while a replay runs): with ``to``, the story
  reaches ``to`` (by a jump or a call); without, a jump at the scene's own depth (empty call
  stack) to another label. The scene's lines ending is ``_return``'s ordinary story end.
- ``leave(interp)`` (``_end``, ``_fail``, ``new_game``, ``stop_replay``): the store's sandbox
  ends and ``interp.replay`` is None. Always calls ``end_sandbox`` (07 I-10), idempotent.
- ``skipped(interp, stmt, form, name)``: in a replay a ``file write``/``file delete`` (F31)
  or ``ui delete saves`` (F32) does nothing; dev runs log W229 (area ``story``) once per line
  per interpreter. True when the line is to be skipped.

Layering as ``gallery.py``: below the interpreter, importing it only under ``TYPE_CHECKING``.
Pure: no file, clock, randomness, or thread.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from engine.core.logsetup import get_logger
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message

if TYPE_CHECKING:
    from engine.runtime.interpreter import Interpreter
    from engine.script.program import Program
    from engine.script.replay import ReplayEntry

REPLAY_KIND: Final = "replay"           # the F12 unlock kind (revocable)
WARNED_MAX: Final = 1_000               # W229 lines remembered per interpreter

_story_log = get_logger("story")        # W229 (dev, run)


@dataclass(frozen=True, slots=True)
class ReplayRun:
    """One replay as the interpreter runs it: the ``scene`` it starts at, the ``to`` scene that
    ends it (None: it ends when the story leaves the scene), and the starting ``values`` (F44's
    ``StartOptions.values`` shape, set after the defaults). Run-time only, never saved."""

    scene: str
    to: str | None = None
    values: tuple[tuple[str, object], ...] = ()


class ReplayIndex:
    """``Program.replays`` by scene label (immutable; rebuilt by ``register``)."""

    __slots__ = ("entries", "_by_label")

    def __init__(self, entries: "tuple[ReplayEntry, ...]") -> None:
        self.entries = entries
        self._by_label = {e.label: e for e in entries}

    def __contains__(self, label: object) -> bool:
        return label in self._by_label

    def has(self, name: object) -> bool:
        """``known`` for the store: a declared scene."""
        return type(name) is str and name in self._by_label

    def get(self, label: str) -> "ReplayEntry | None":
        return self._by_label.get(label)


def register(interp: "Interpreter") -> None:
    """Register (or re-register, F39) the ``"replay"`` kind on ``interp.persistent`` and set
    ``interp.replays`` for ``interp.program``. Safe to repeat."""
    index = ReplayIndex(interp.program.replays)
    interp.replays = index
    interp.persistent.register_kind(REPLAY_KIND, known=index.has, revocable=True)


def run_for(program: "Program", label: str) -> ReplayRun:
    """The replay of ``label``: a ``lock replay`` of it gives its ``to`` and starting values;
    any other label plays alone (an ending's replay, dev ``--replay``)."""
    for entry in program.replays:
        if entry.label == label:
            return ReplayRun(label, entry.to, entry.values)
    return ReplayRun(label)


def arrive(interp: "Interpreter", label: str) -> None:
    """The story entered ``label``: unlock it when it is a declared scene (PR-F36-04)."""
    if label in interp.replays and interp.replay is None and not interp.timeline.replaying:
        interp.persistent.unlock(REPLAY_KIND, label)


def ends_at(interp: "Interpreter", label: str) -> bool:
    """The running replay ends as the story enters ``label`` (PR-F36-09)."""
    run = interp.replay
    if run is None:
        return False
    if run.to is not None:
        return label == run.to
    return label != run.scene and not interp.call_stack


def leave(interp: "Interpreter") -> None:
    """End the replay: the store's sandbox is put back (always, 07 I-10) and no replay runs.
    Idempotent."""
    interp.persistent.end_sandbox()
    interp.replay = None


def skipped(interp: "Interpreter", stmt: object, form: str, name: str | None = None) -> bool:
    """True when a replay runs: the line (``form`` ``"write"``/``"delete"`` of the meta file
    ``name``, or ``"saves"``) must do nothing. Dev runs log W229 once per line."""
    if interp.replay is None:
        return False
    if interp.dev:
        warned = interp.replay_warned
        sid = getattr(stmt, "sid", None)
        if sid not in warned and len(warned) < WARNED_MAX:
            warned.add(sid)
            text = format_message("W229", (form, name) if name is not None else (form,))
            file = getattr(stmt, "file", None)
            warning = ScriptWarning(text, code="W229",
                                    file=None if file is None else file.ref,
                                    line=getattr(stmt, "line", None))
            _story_log.warning("%s", warning.format(), extra={"code": "W229"})
    return True


__all__ = ["REPLAY_KIND", "ReplayIndex", "ReplayRun", "arrive", "ends_at", "leave", "register",
           "run_for", "skipped"]
