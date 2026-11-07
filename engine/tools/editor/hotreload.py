"""Studio's side of F39's hot reload (``specs/F39-hot-reload/SPEC.md`` §4.2, §5.1, §5.2).

Why this module exists: when the author saves (or presses Ctrl+R) while a preview runs, the
preview should carry on from the same line with the new story (D1: restart and resume). This
module decides whether and how; ``preview.PreviewRunner`` does the process work.

- **Gate** (D3, §5.1 step 2): ``gate`` turns the next check event into update, hold (with
  the error count), recheck (that check carried unsaved text: run one of the saved files
  only), or failed (timeout or crash: S4). Warnings and info never hold.
- **Restart** (§5.1 step 4): ``resume_argv`` is the preview's F5 argv plus
  ``--resume-from-editor``; with one or more states it also drops ``--start L`` and every
  ``--set n=v``; it adds ``--window-at=X,Y`` unless the old window was fullscreen (then
  Play's own ``--window-at``, if any, stays).
  ``resume_frame`` is the ``resume`` header line and the ``state`` body, byte for byte; no
  answer gives the ``lost`` frame (0 states, ``lost`` true: the new child starts normally
  and shows N4).
- **Messages**: ``held_message`` (N5's count); the ``reload`` line is
  ``core.editorreport.RELOAD_MESSAGE``.
- **Texts**: S1-S4 and the Problems suffix, verbatim (§4.2).
- ``HotReload``: the coordinator Studio's window drives (W2). One update at a time; a save
  during an update queues exactly one more; while a check is under way, a new save is
  covered by the check the save itself starts; with nothing changed since the newest clean
  check of the saved files (``checked``), the update needs no new check.

Pure Python, no Tk; imports ``engine.core`` and Studio's ``preview`` and ``checker`` only.
"""

import enum
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from engine.core.editorreport import RELOAD_FRAME_MAX, RELOAD_HELD_MAX, RELOAD_STATES_MAX
from engine.tools.editor.checker import CheckEvent, CheckState
from engine.tools.editor.preview import PreviewEvent, PreviewRunner, PreviewState, StateFrame

# --- Texts (§4.2) ----------------------------------------------------------------------------

UPDATING_TEXT = "▶ Updating…"                                                        # S1
CHECK_FAILED_TEXT = ("▶ Running the old story: the check didn't finish. Press Ctrl+R to "
                     "try again.")                                                   # S4
HELD_SUFFIX = " The preview is still running the old story."


def updated_text(hhmm: str) -> str:
    """S2: ``▶ Running. Updated at 14:32.``"""
    return f"▶ Running. Updated at {hhmm}."


def held_text(errors: int) -> str:
    """S3, singular or plural."""
    if errors == 1:
        return "▶ Running the old story: fix 1 problem to update it."
    return f"▶ Running the old story: fix {errors:,} problems to update it."


# --- Which saves update (PR-F39-01) ----------------------------------------------------------

CONFIG_FILE = "config.toml"
SCRIPT_SUFFIX = ".vns"


def updates_on_save(ref: str) -> bool:
    """Whether saving the game file ``ref`` (``scenes/a.vns``, ``config.toml``) updates a
    running preview when "Update preview on save" is on."""
    ref = ref.replace("\\", "/")
    return ref == CONFIG_FILE or ref.lower().endswith(SCRIPT_SUFFIX)


# --- Messages and argv (§5.1 step 4, §5.2) ---------------------------------------------------

RESUME_OPTION = "--resume-from-editor"
WINDOW_OPTION = "--window-at"
_DROPPED_WITH_STATES = ("--start", "--set")


def held_message(errors: int) -> bytes:
    """``{"v":1,"msg":"held","errors":N}`` and its newline (N clamped to 1..1e9)."""
    errors = min(max(int(errors), 1), RELOAD_HELD_MAX)
    return _line({"v": 1, "msg": "held", "errors": errors})


def _line(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii") + b"\n"


def _without(argv: Sequence[str], options: Sequence[str]) -> list[str]:
    """``argv`` without each of ``options`` and its value (``--opt v`` or ``--opt=v``)."""
    out: list[str] = []
    skip = False
    for arg in argv:
        if skip:
            skip = False
        elif arg in options:
            skip = True
        elif not any(arg.startswith(option + "=") for option in options):
            out.append(arg)
    return out


def resume_argv(base: Sequence[str], frame: StateFrame | None) -> list[str]:
    """The next child's argv: ``base`` (the preview's F5 argv) plus ``--resume-from-editor``.
    With 1 or more states, also without ``--start``/``--set`` (restore ignores them, so a
    renamed start label can't stop it). With ``--window-at=X,Y`` when the old window wasn't
    fullscreen (one argv item, so a negative ``X`` isn't read as an option), on the title
    too; without that spot, ``base``'s own ``--window-at`` (Play's "beside Studio" spot)
    stays, so the game reopens where it was. ``--window-size`` always stays."""
    window = None if frame is None else frame.window
    kept = base if window is None else _without(base, (WINDOW_OPTION,))
    argv = [arg for arg in kept if arg != RESUME_OPTION]
    if frame is not None and frame.states > 0:
        argv = _without(argv, _DROPPED_WITH_STATES)
    argv.append(RESUME_OPTION)
    if window is not None:
        x, y = window
        argv.append(f"{WINDOW_OPTION}={x},{y}")
    return argv


def resume_frame(frame: StateFrame | None) -> bytes:
    """The new child's stdin: ``{"v":1,"msg":"resume","bytes":B,"states":K,"lost":bool}``,
    a newline, then the ``state`` body unchanged. None (no answer) or a frame over the caps
    gives the ``lost`` frame: 0 bytes, 0 states, ``lost`` true."""
    if frame is None or len(frame.body) > RELOAD_FRAME_MAX or \
            not 0 <= frame.states <= RELOAD_STATES_MAX or \
            (frame.states == 0) != (len(frame.body) == 0):
        return _line({"v": 1, "msg": "resume", "bytes": 0, "states": 0, "lost": True})
    return _line({"v": 1, "msg": "resume", "bytes": len(frame.body), "states": frame.states,
                  "lost": False}) + frame.body


def restart(base: list[str], frame: StateFrame | None) -> tuple[list[str], bytes]:
    """``PreviewRunner.update``'s ``restart``: the next child's argv and stdin bytes."""
    return resume_argv(base, frame), resume_frame(frame)


# --- The gate (D3, §5.1 step 2) --------------------------------------------------------------

class Gate(enum.Enum):
    UPDATE = "update"                   # clean (warnings and info only)
    HOLD = "hold"                       # errors: the old story keeps running (S3, N5)
    RECHECK = "recheck"                 # that check carried unsaved text: check the saved
    FAILED = "failed"                   # the check timed out or crashed (S4)


@dataclass(frozen=True)
class GateDecision:
    gate: Gate
    errors: int = 0                     # HOLD's count


def gate(event: CheckEvent, *, overlay: bool) -> GateDecision | None:
    """What a finished check means for an update; None for an event that isn't an end
    (``STARTED``). ``overlay``: that check carried unsaved text. A script that didn't load
    holds with at least 1 error."""
    if event.state in (CheckState.TIMEOUT, CheckState.CRASHED):
        return GateDecision(Gate.FAILED)
    if event.state is not CheckState.DONE or event.result is None:
        return None
    if overlay:
        return GateDecision(Gate.RECHECK)
    result = event.result
    errors = sum(1 for item in result.problems if item.severity == "error")
    if not result.loaded:
        errors = max(errors, 1)
    if errors:
        return GateDecision(Gate.HOLD, errors)
    return GateDecision(Gate.UPDATE)


# --- The coordinator --------------------------------------------------------------------------

class Phase(enum.Enum):
    IDLE = "idle"
    CHECKING = "checking"               # waiting for the gate's check
    READY = "ready"                     # the gate passed; waiting for the preview's started
    UPDATING = "updating"               # the runner is restarting the preview


@dataclass(frozen=True)
class HotReloadEvent:
    """The preview's status-bar text now (S1-S4) and the Problems summary's suffix now
    (``HELD_SUFFIX`` while held, else ``""``)."""

    status: str
    suffix: str


_LIVE = (PreviewState.STARTING, PreviewState.RUNNING, PreviewState.UPDATING,
         PreviewState.STOPPED_ERROR)
_ENDED = (PreviewState.NOT_RUNNING, PreviewState.DIDNT_START, PreviewState.CLOSED,
          PreviewState.STOPPED_UNEXPECTED)


class HotReload:
    """Updates a running preview on save or on demand (§5.1). Studio's window (W2):

    - calls ``saved(ref)`` after each save's own check request (or ``request()`` for
      Ctrl+R; "Update preview on save" is ``update_on_save``);
    - passes every check event to ``check_event(event, overlay=…)`` (whether that check
      carried unsaved text) and every preview event to ``preview_event``, whose text (when
      not None) replaces F44's status text for it;
    - polls it with ``join_runner`` (``poll`` → ``HotReloadEvent``s) and appends
      ``problems_suffix()`` to the Problems summary.

    ``check_running()`` says whether a check is under way (its event will come);
    ``start_check()`` asks for a check of the saved files only (no overlay, armed).
    ``checked()`` says whether the newest finished check already passes the gate: clean,
    of the saved files with no unsaved text, and nothing edited or changed on disk since;
    then an update skips the check and restarts at once (v1 review, finding 2)."""

    def __init__(self, runner: PreviewRunner, *, start_check: Callable[[], None],
                 check_running: Callable[[], bool] = lambda: False,
                 checked: Callable[[], bool] = lambda: False,
                 clock_text: Callable[[], str] = lambda: time.strftime("%H:%M")) -> None:
        self.runner = runner
        self._start_check = start_check
        self._check_running = check_running
        self._checked = checked
        self._clock_text = clock_text
        self.update_on_save = True          # D2: on by default, per window, not remembered
        self.phase = Phase.IDLE
        self.again = False                  # a request came during an update: one more
        self.held: int | None = None        # the errors holding the last update
        self.status: str | None = None
        self._events: list[HotReloadEvent] = []

    # -- what Studio calls --

    def saved(self, ref: str) -> bool:
        """A save of ``ref``: updates when the toggle is on and ``ref`` is a ``.vns`` file or
        ``config.toml``. Returns whether an update was asked for."""
        if not self.update_on_save or not updates_on_save(ref):
            return False
        return self.request()

    def request(self) -> bool:
        """Update preview (Ctrl+R): False, doing nothing, without a running preview. During
        an update, one more is queued; during the gate's check, the newest check counts."""
        if not self.preview_live():
            return False
        if self.phase is Phase.CHECKING:
            if not self._check_running():
                self._start_check()
            return True
        if self.phase is not Phase.IDLE:
            self.again = True
            return True
        self._begin()
        return True

    def preview_live(self) -> bool:
        """A preview is starting or running (the error screen included)."""
        state = self.runner.state
        if state not in _LIVE:
            return False
        return state is not PreviewState.STOPPED_ERROR or self.runner.alive()

    def check_event(self, event: CheckEvent, *, overlay: bool) -> None:
        """Every check event the window gets; only the gate's next end counts."""
        if self.phase is not Phase.CHECKING:
            return
        decision = gate(event, overlay=overlay)
        if decision is None:
            return
        if decision.gate is Gate.RECHECK:
            self._start_check()
        elif decision.gate is Gate.FAILED:
            self.phase = Phase.IDLE
            self._say(CHECK_FAILED_TEXT)
            self._next()
        elif decision.gate is Gate.HOLD:
            self.phase = Phase.IDLE
            self.held = decision.errors
            self.runner.send(held_message(decision.errors))
            self._say(held_text(decision.errors))
            self._next()
        else:
            self.held = None
            self.phase = Phase.READY
            self._try_update()

    def preview_event(self, event: PreviewEvent) -> str | None:
        """The status text for a preview event while an update is under way (S1, or S2 once
        the new child started), or None for F44's text. An ended preview ends any update
        and the hold."""
        state = event.state
        if state in _ENDED:
            self.phase = Phase.IDLE
            self.again = False
            self.held = None
            self.status = None
            return None
        if self.phase is Phase.UPDATING:
            if state is PreviewState.RUNNING:
                self.phase = Phase.IDLE
                self.status = updated_text(self._clock_text())
                if self.again:
                    self.again = False
                    self._begin()
                return self.status
            if state is PreviewState.STOPPED_ERROR:     # the new child stopped: F44's text
                self.phase = Phase.IDLE
                self.status = None
                self._next()
                return None
            return UPDATING_TEXT
        if self.phase is not Phase.IDLE and state is not PreviewState.STOPPED_ERROR:
            return UPDATING_TEXT
        self.status = None
        return None

    def poll(self) -> list[HotReloadEvent]:
        """The status and suffix changes since the last call. A gate that passed while the
        preview was starting updates once it runs."""
        if self.phase is Phase.READY:
            self._try_update()
        events, self._events = self._events, []
        return events

    def problems_suffix(self) -> str:
        """``HELD_SUFFIX`` while an update is held, else ``""``."""
        return HELD_SUFFIX if self.held is not None else ""

    def stop(self) -> None:
        """The window closing (``join_runner``), or Play/Stop restarting or ending the
        preview: forget any update and any hold, so a restart isn't reported as "Updated";
        the preview runner is stopped or restarted by the window."""
        self.phase = Phase.IDLE
        self.again = False
        self.held = None
        self.status = None

    # -- internals --

    def _say(self, text: str) -> None:
        self.status = text
        self._events.append(HotReloadEvent(text, self.problems_suffix()))

    def _begin(self) -> None:
        self.again = False
        self.phase = Phase.CHECKING
        self._say(UPDATING_TEXT)
        if self._check_running():
            return                                  # that check's end is the gate
        if self._checked():                         # the last clean check still holds
            self.held = None
            self.phase = Phase.READY
            self._try_update()
            return
        self._start_check()

    def _next(self) -> None:
        """After an update ended without a new child: run the queued one, if any."""
        if self.again and self.preview_live():
            self._begin()
        else:
            self.again = False

    def _try_update(self) -> None:
        state = self.runner.state
        if state in (PreviewState.STARTING, PreviewState.UPDATING):
            return                                  # wait for started
        if self.runner.update(restart):
            self.phase = Phase.UPDATING
            self._say(UPDATING_TEXT)
        else:                                       # the preview ended meanwhile
            self.phase = Phase.IDLE
            self.again = False


__all__ = ["CHECK_FAILED_TEXT", "Gate", "GateDecision", "HELD_SUFFIX", "HotReload",
           "HotReloadEvent", "Phase", "RESUME_OPTION", "UPDATING_TEXT", "WINDOW_OPTION",
           "gate", "held_message", "held_text", "restart", "resume_argv", "resume_frame",
           "updated_text", "updates_on_save"]
