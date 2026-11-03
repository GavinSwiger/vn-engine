"""The game side of F39's hot reload (``specs/F39-hot-reload/SPEC.md`` §4.1, §4.3, §5.1, §5.2).

Why this module exists: when the author saves in Studio, the running preview must carry on
from the same line with the new story (D1: restart and resume). The old child hands its place
to Studio as F11 state lines and quits; a fresh child gets them back on stdin and resumes.
Everything here is pure or thread-light, so W1 only wires it in:

- **Messages** (Studio → child stdin, ASCII JSON lines of at most ``MESSAGE_LINE_MAX``
  bytes): ``reload`` and ``held`` (``parse_message``), and, only as a resume child's first
  line, the ``resume`` frame header followed by exactly ``bytes`` bytes (``parse_resume_header``).
  Longer, non-ASCII, malformed, ``v`` ≠ 1 or unknown lines are dropped. Input is never logged
  or echoed.
- ``StdinReader``: a daemon thread that touches only its stream, a ``SimpleQueue`` and the
  frame slot (ADR-0007 thread note); the frame loop calls ``poll`` once per frame (W1:
  ``app/editor_link.py``'s ``EditorLink.listen`` and ``update``).
  ``handle_messages`` turns a frame's messages into N5 (never in error mode) and the reload.
- **Collection** (§5.2): ``collect_states`` (newest first: the checkpoint, then the rollback
  steps, at most ``FRAME_STATES_MAX`` and ``FRAME_BYTES_MAX``), ``story_states`` (what an
  App carries now; none on the title or while loading), ``fatal_states`` (the fatal hook's,
  taken from a FAILED story), and ``state_event`` (the stdout header line and body).
- **Resume** (§5.1 step 5): ``split_frame``, ``parse_states``, ``pick_resume`` (exact, then
  the location hint, both with ``fresh_menu``) and ``ResumeScreen``, which waits for the
  frame, parses one state per frame, enters the game through the shell's ``enter_game``
  (a parameter: W1 wires ``GameShell.enter_game``), carries the older steps
  (``Timeline.carry``) and shows N1-N4.

The notes are dev-only fixed English (§4.3): never ``[words]`` keys. One INFO record (area
``app``) says how a resume went and at which label, never state contents.

Imports ``engine.core``, ``engine.persist`` and ``engine.runtime``; the shell and the App are
reached only through the objects passed in.
"""

import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from typing import TYPE_CHECKING, BinaryIO

from engine.core.editorreport import (
    RELOAD_FRAME_MAX,
    RELOAD_HELD_MAX,
    RELOAD_MESSAGE_MAX,
    RELOAD_STATE_LINE_MAX,
    RELOAD_STATES_MAX,
    RELOAD_WAIT_S,
    RELOAD_WINDOW_MAX,
    REPORT_MARKER,
    REPORT_VERSION,
)
from engine.core.logsetup import get_logger
from engine.persist import limits
from engine.persist.saves import SlotStatus, count_structure, iter_pieces, parse_state_line
from engine.runtime.interpreter import RestoreResult, Status
from engine.ui.screen import Screen

if TYPE_CHECKING:
    from engine.render.canvas import Canvas
    from engine.runtime.rollback import Timeline
    from engine.runtime.state import GameState

_log = get_logger("app")

# --- Limits (§5.2; shared with Studio through ``core/editorreport.py``) ----------------------

PROTOCOL_VERSION = REPORT_VERSION
MESSAGE_LINE_MAX = RELOAD_MESSAGE_MAX    # one stdin line, newline not included
FRAME_STATES_MAX = RELOAD_STATES_MAX     # the checkpoint and up to 19 rollback steps
FRAME_BYTES_MAX = RELOAD_FRAME_MAX       # one frame or state body (32 MiB)
STATE_LINE_MAX = RELOAD_STATE_LINE_MAX   # one state line and its "\n" (24 MiB, F11)
RESUME_WAIT_S = RELOAD_WAIT_S            # a resume child waits this long for its frame
WINDOW_COORD_MAX = RELOAD_WINDOW_MAX     # |x|, |y| of a window position
HELD_ERRORS_MAX = RELOAD_HELD_MAX        # a ``held`` count above this is a bad line
_SKIP_CHUNK = 1 << 20                    # a refused frame body is skipped in these chunks
# STATE_LINE_MAX is F11's ``limits.STATE_MAX_BYTES`` (AC-F39-10's test checks they agree).

# --- The notes (§4.3) ------------------------------------------------------------------------

NOTE_UPDATED = "Story updated."                                                       # N1
NOTE_WENT_BACK = ("Story updated. Your line was removed, so the story went back to an "
                  "earlier line.")                                                    # N2
NOTE_RESTARTED = "Story updated. Your place was removed, so the game started again."  # N3
NOTE_LOST = ("Story updated. Your place couldn't be carried over, so the game started "
             "again.")                                                                # N4


def held_note(errors: int) -> str:
    """N5, singular or plural."""
    if errors == 1:
        return "Story not updated: Studio found 1 problem. Fix it and save again."
    return f"Story not updated: Studio found {errors:,} problems. Fix them and save again."


# --- Messages --------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Reload:
    """``{"v":1,"msg":"reload"}``: send the state event and quit."""


@dataclass(frozen=True, slots=True)
class Held:
    """``{"v":1,"msg":"held","errors":N}``: Studio's check held the update (N5)."""

    errors: int


@dataclass(frozen=True, slots=True)
class ResumeFrame:
    """The resume frame. ``body`` is None when the frame was bad: a malformed header, a body
    over the caps, or a short body (EOF first). ``lost``: Studio got no state (N4)."""

    body: bytes | None
    states: int = 0
    lost: bool = False


@dataclass(frozen=True, slots=True)
class _Header:
    bytes: int
    states: int
    lost: bool


def _is_int(value: object) -> bool:
    return type(value) is int


def _load_line(line: bytes) -> dict | None:
    """``line`` (no newline) as a JSON object with ``v`` 1 and a ``str`` ``msg``, else None.
    Only short ASCII lines are decoded."""
    if len(line) > MESSAGE_LINE_MAX or not line.isascii():
        return None
    try:
        obj = json.loads(line.decode("ascii"))
    except (ValueError, RecursionError):
        return None
    if type(obj) is not dict:
        return None
    if not _is_int(obj.get("v")) or obj["v"] != PROTOCOL_VERSION:
        return None
    if type(obj.get("msg")) is not str:
        return None
    return obj


def parse_message(line: bytes) -> Reload | Held | None:
    """A ``reload`` or ``held`` line (newline stripped), else None (dropped). Exact keys."""
    obj = _load_line(line)
    if obj is None:
        return None
    msg = obj["msg"]
    if msg == "reload" and obj.keys() == {"v", "msg"}:
        return Reload()
    if msg == "held" and obj.keys() == {"v", "msg", "errors"}:
        errors = obj["errors"]
        if _is_int(errors) and 1 <= errors <= HELD_ERRORS_MAX:
            return Held(errors)
    return None


def _resume_header(line: bytes) -> "_Header | int | None":
    """A ``resume`` header: ``_Header`` when it is valid; the declared ``bytes`` (an int to
    skip) when it is a resume line with bad fields but a usable length; None otherwise."""
    obj = _load_line(line)
    if obj is None or obj["msg"] != "resume":
        return None
    size, states, lost = obj.get("bytes"), obj.get("states"), obj.get("lost")
    skip = size if _is_int(size) and size >= 0 else -1
    if (obj.keys() != {"v", "msg", "bytes", "states", "lost"} or not _is_int(size)
            or not _is_int(states) or type(lost) is not bool
            or not 0 <= size <= FRAME_BYTES_MAX or not 0 <= states <= FRAME_STATES_MAX
            or (states == 0) != (size == 0)):
        return skip
    return _Header(size, states, lost)


def parse_resume_header(line: bytes) -> tuple[int, int, bool] | None:
    """``(bytes, states, lost)`` of a valid ``resume`` header line (newline stripped)."""
    header = _resume_header(line)
    if type(header) is not _Header:
        return None
    return header.bytes, header.states, header.lost


def handle_messages(messages: Sequence[object], *, error_mode: bool,
                    notify: Callable[[str, str], None], reload: Callable[[], None]) -> bool:
    """One frame's messages: ``held`` shows N5 (a problem notice), except in error mode,
    whose screen has no notices; ``reload`` calls ``reload`` once, whatever the count.
    Returns True when a reload was asked for."""
    asked = False
    for message in messages:
        if type(message) is Held:
            if not error_mode:
                notify(held_note(message.errors), "problem")
        elif type(message) is Reload:
            asked = True
    if asked:
        reload()
    return asked


class _TooLong:
    pass


_TOO_LONG = _TooLong()


class StdinReader:
    """Reads Studio's messages from ``stream`` (the child's binary stdin) on a daemon
    thread. Messages go to a ``SimpleQueue`` (``poll``); a resume child's frame
    (``expect_resume``: the first line must be its header) goes to ``take_frame``. EOF ends
    the thread quietly (``closed``). Nothing read is logged or written anywhere."""

    def __init__(self, stream: BinaryIO, *, expect_resume: bool = False) -> None:
        self.stream = stream
        self.expect_resume = expect_resume
        self.queue: SimpleQueue = SimpleQueue()
        self.closed = threading.Event()
        self._frame: ResumeFrame | None = None
        self._frame_ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="vn-editor-stdin",
                                        daemon=True)

    def start(self) -> "StdinReader":
        self._thread.start()
        return self

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def poll(self) -> list[Reload | Held]:
        """The messages read since the last poll (never blocks)."""
        out = []
        while True:
            try:
                out.append(self.queue.get_nowait())
            except Empty:
                return out

    def take_frame(self) -> ResumeFrame | None:
        """The resume frame once it is read (a bad one too); None before. EOF without a
        frame in a resume child gives a bad frame."""
        if not self._frame_ready.is_set():
            return None
        return self._frame

    # -- the thread --

    def _run(self) -> None:
        try:
            self._read()
        except Exception:                   # a broken pipe, a closed stream: end quietly
            _log.debug("The editor's input ended with an error", exc_info=True)
        finally:
            if self.expect_resume and not self._frame_ready.is_set():
                self._set_frame(ResumeFrame(None))
            self.closed.set()

    def _set_frame(self, frame: ResumeFrame) -> None:
        self._frame = frame
        self._frame_ready.set()

    def _read(self) -> None:
        first = self.expect_resume
        while True:
            line = self._line()
            if line is None:
                return
            if first:
                first = False
                if not self._frame_from(line):
                    return                  # the stream is out of step: stop reading
                continue
            if line is _TOO_LONG:
                continue
            message = parse_message(line)   # type: ignore[arg-type]
            if message is not None:
                self.queue.put(message)

    def _line(self) -> "bytes | _TooLong | None":
        """One line without its newline; ``_TOO_LONG`` for a longer line (read to its end
        and dropped); None at EOF (a last line without a newline is dropped)."""
        stream = self.stream
        line = stream.readline(MESSAGE_LINE_MAX + 2)
        if not line:
            return None
        if line.endswith(b"\n"):
            line = line[:-1]
            if line.endswith(b"\r"):
                line = line[:-1]
            return _TOO_LONG if len(line) > MESSAGE_LINE_MAX else line
        if len(line) < MESSAGE_LINE_MAX + 2:
            return None                     # EOF in the middle of a line
        while True:                         # drain the rest of the long line
            more = stream.readline(_SKIP_CHUNK)
            if not more:
                return None
            if more.endswith(b"\n"):
                return _TOO_LONG

    def _frame_from(self, line: "bytes | _TooLong") -> bool:
        """The first line of a resume child: the header, then the body. Returns False when
        the rest of the stream can't be read in step."""
        header = None if line is _TOO_LONG else _resume_header(line)  # type: ignore[arg-type]
        if type(header) is _Header:
            body = self._exactly(header.bytes)
            if body is None:
                self._set_frame(ResumeFrame(None))
                return False
            self._set_frame(ResumeFrame(body, header.states, header.lost))
            return True
        self._set_frame(ResumeFrame(None))
        if type(header) is int and header >= 0:   # a refused body of a known length
            return self._skip(header)
        return False                        # no usable length: the stream is out of step

    def _exactly(self, n: int) -> bytes | None:
        """Exactly ``n`` bytes, or None when the stream ends first."""
        parts: list[bytes] = []
        left = n
        while left > 0:
            chunk = self.stream.read(min(left, _SKIP_CHUNK))
            if not chunk:
                return None
            parts.append(chunk)
            left -= len(chunk)
        return b"".join(parts)

    def _skip(self, n: int) -> bool:
        left = n
        while left > 0:
            chunk = self.stream.read(min(left, _SKIP_CHUNK))
            if not chunk:
                return False
            left -= len(chunk)
        return True


# --- Collection (§5.2) -----------------------------------------------------------------------

def encode_state_line(state: "GameState") -> bytes | None:
    """``state`` as one F11 state line with its ``\\n``: ``iter_pieces`` of ``to_json``, or
    None when it can't be carried (F11's ``save_problem``, over ``STATE_LINE_MAX``, or more
    structure than ``parse_state_line``'s pre-scan takes)."""
    try:
        if state.save_problem() is not None:
            return None
        parts: list[bytes] = []
        size = structure = 0
        for piece in iter_pieces(state.to_json()):
            size += len(piece)
            if size + 1 > STATE_LINE_MAX:
                return None
            structure += count_structure(piece)
            if structure > limits.SAVE_PRESCAN_MAX:
                return None
            parts.append(piece)
    except (ValueError, RecursionError, MemoryError, OverflowError, TypeError):
        return None
    parts.append(b"\n")
    return b"".join(parts)


def gather(checkpoint: "GameState | None", timeline: "Timeline | None") -> list["GameState"]:
    """The states to carry, newest first: ``checkpoint``, then the timeline's steps from
    ``cursor`` down to 0, each object once; at most ``FRAME_STATES_MAX``. None without a
    checkpoint."""
    if checkpoint is None:
        return []
    out = [checkpoint]
    seen = {id(checkpoint)}
    if timeline is not None:
        states = timeline.states
        for i in range(min(timeline.cursor, len(states) - 1), -1, -1):
            if len(out) >= FRAME_STATES_MAX:
                break
            state = states[i]
            if id(state) in seen:
                continue
            seen.add(id(state))
            out.append(state)
    return out


def collect_states(checkpoint: "GameState | None",
                   timeline: "Timeline | None") -> list[bytes] | None:
    """The state lines to send, newest first (``gather``), within ``FRAME_BYTES_MAX``
    (the oldest are dropped). An older state that can't be encoded ends the list there;
    None when the checkpoint itself can't be carried (the child then quits without a state,
    so Studio's frame says ``lost``: N4)."""
    lines: list[bytes] = []
    total = 0
    for index, state in enumerate(gather(checkpoint, timeline)):
        line = encode_state_line(state)
        if line is None:
            if index == 0:
                return None
            break
        if total + len(line) > FRAME_BYTES_MAX:
            break
        total += len(line)
        lines.append(line)
    return lines


def _game_mode(app: object) -> bool:
    if getattr(app, "loading", False) or getattr(app, "error_mode", False):
        return False
    shell = getattr(app, "shell", None)
    mode = getattr(shell, "mode", None)
    return mode is not None and getattr(mode, "value", None) == "game"


def _in_replay(app: object) -> bool:
    """F36 (04 decision 11): a scene replay runs (or just failed). A reload then carries
    nothing, so the updated preview starts at the title instead of resuming the replay."""
    return getattr(getattr(app, "shell", None), "replay", None) is not None


def story_states(app: object) -> list[bytes] | None:
    """What the App carries now (§5.2): none on the title, while loading, between title and
    game, before the first line, or during a scene replay (F36); else ``collect_states`` of
    the driver's checkpoint and timeline. (In error mode the caller sends the list the fatal
    hook kept.)"""
    story = getattr(app, "story", None)
    if story is None or not _game_mode(app) or _in_replay(app):
        return []
    interp = story.interp
    return collect_states(interp.checkpoint(), interp.timeline)


def fatal_states(app: object) -> list[bytes] | None:
    """The fatal hook's list (§5.2, PR-F39-05): taken while ``app.story`` is still set, from
    the FAILED story's last checkpoint (``checkpoint()`` is None once FAILED) and its
    timeline: the next update resumes at the last line before the error. Empty when the
    story isn't in game (an error on the title or while loading) or was a scene replay (F36)."""
    story = getattr(app, "story", None)
    if story is None or getattr(app, "loading", False) or _in_replay(app):
        return []
    shell = getattr(app, "shell", None)
    mode = getattr(shell, "mode", None)
    if mode is None or getattr(mode, "value", None) != "game":
        return []
    interp = story.interp
    checkpoint = interp.checkpoint() if interp.status is not Status.FAILED else None
    if checkpoint is None:
        checkpoint = interp.last_checkpoint
    return collect_states(checkpoint, interp.timeline)


def window_at(window: object) -> list[int] | None:
    """The state event's ``window``: ``[x, y]`` of a windowed game window, else None
    (fullscreen, no position, or out of bounds)."""
    if getattr(window, "fullscreen", True):
        return None
    try:
        x, y = window.position                          # type: ignore[attr-defined]
    except Exception:
        return None
    if not (_is_int(x) and _is_int(y)) or abs(x) > WINDOW_COORD_MAX or abs(y) > WINDOW_COORD_MAX:
        return None
    return [x, y]


def state_event(lines: Sequence[bytes], window: list[int] | None) -> bytes:
    """The ``state`` report line (marker, JSON, newline) followed by its body: the lines
    joined, newest first."""
    body = b"".join(lines)
    header = {"v": REPORT_VERSION, "event": "state", "bytes": len(body),
              "states": len(lines), "window": window}
    return (REPORT_MARKER + json.dumps(header, ensure_ascii=True, separators=(",", ":"))
            .encode("ascii") + b"\n" + body)


# --- Resume (§4.1, §5.1 step 5) --------------------------------------------------------------

def split_frame(body: bytes, states: int) -> list[bytes] | None:
    """The frame body as ``states`` lines, each with its ``\\n`` and at most
    ``STATE_LINE_MAX`` bytes; None when the body doesn't hold exactly that."""
    if len(body) > FRAME_BYTES_MAX or not 0 <= states <= FRAME_STATES_MAX:
        return None
    lines: list[bytes] = []
    start = 0
    while start < len(body):
        end = body.find(b"\n", start)
        if end < 0:
            return None
        end += 1
        if end - start > STATE_LINE_MAX or end - start < 2:
            return None
        lines.append(body[start:end])
        start = end
    return lines if len(lines) == states else None


def parse_state(line: bytes) -> "GameState | None":
    """One state line through F11's ``parse_state_line``; None when DAMAGED or NEWER."""
    parsed = parse_state_line(line, (0, len(line)))
    return parsed.state if parsed.status is SlotStatus.OK else None


@dataclass(frozen=True, slots=True)
class Pick:
    """``pick_resume``'s choice: ``states[index]`` restores, exactly or by its location
    hint; ``older`` are the parsed states after it (newest first) for ``Timeline.carry``."""

    index: int
    state: "GameState"
    use_hints: bool
    older: tuple["GameState", ...]


def pick_resume(driver: object, states: Sequence["GameState | None"]) -> Pick | None:
    """§4.1: the first state, newest first, that ``restore(check_only=True)`` accepts by
    its identity, else by its location hint, both with ``fresh_menu``. Unusable (None)
    states are skipped. Nothing changes."""
    for index, state in enumerate(states):
        if state is None:
            continue
        for hints in (False, True):
            outcome = driver.restore(state, use_hints=hints,       # type: ignore[attr-defined]
                                     check_only=True, fresh_menu=True)
            if outcome.result is RestoreResult.OK:
                older = tuple(s for s in states[index + 1:] if s is not None)
                return Pick(index, state, hints, older)
    return None


@dataclass
class ResumePorts:
    """What ``ResumeScreen`` needs from the App (W1 wires them).

    - ``take_frame``: ``StdinReader.take_frame``.
    - ``driver``: the story driver (``app.story``: ``restore``, ``interp.timeline``).
    - ``enter_game(start)``: F10's ``GameShell.enter_game``: builds the in-game screens,
      skips the title and F33's warning, and calls ``start()`` where a new game would start.
    - ``start_normally()``: ``build_initial_screens(app)`` on the stack.
    - ``notify(text, kind)``: ``shell.notify``.
    - ``show_fatal_error(error)``: ``app.show_fatal_error``.
    - ``keep(lines)``: the carried list the next ``reload`` sends (after DEFAULT_FAILED)."""

    take_frame: Callable[[], ResumeFrame | None]
    driver: Callable[[], object]
    enter_game: Callable[[Callable[[], None]], None]
    start_normally: Callable[[], None]
    notify: Callable[[str, str], None]
    show_fatal_error: Callable[[BaseException], None]
    keep: Callable[[list[bytes]], None]


class ResumeScreen(Screen):
    """The resume child's first screen (§5.1 step 5): black and holding notices while it
    waits up to ``RESUME_WAIT_S`` for the frame, then parses one state per frame, picks the
    place, and hands over. ``done`` holds the outcome word once it has (``updated``,
    ``went_back``, ``restarted``, ``lost``, ``failed``)."""

    opaque = True
    holds_notices = True

    def __init__(self, ports: ResumePorts, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.ports = ports
        self._clock = clock
        self._since: float | None = None
        self._lines: list[bytes] | None = None
        self._states: list["GameState | None"] = []
        self.done: str | None = None

    def update(self, dt: float, *, is_top: bool) -> None:
        if self.done is not None:
            return
        now = self._clock()
        if self._since is None:
            self._since = now
        if self._lines is None:
            frame = self.ports.take_frame()
            if frame is None:
                if now - self._since >= RESUME_WAIT_S:
                    self._start_over("lost")
                return
            self._take(frame)
            return
        if len(self._states) < len(self._lines):            # one state per frame
            self._states.append(parse_state(self._lines[len(self._states)]))
            if len(self._states) < len(self._lines):
                return
        self._resume()

    def draw(self, canvas: "Canvas") -> None:
        canvas.fill((0, 0, 0))

    def _take(self, frame: ResumeFrame) -> None:
        if frame.body is None:
            self._start_over("lost")
            return
        if frame.states == 0:
            self._start_over("lost" if frame.lost else "fresh")
            return
        lines = split_frame(frame.body, frame.states)
        if lines is None:
            self._start_over("lost")
            return
        self._lines = lines

    def _start_over(self, word: str) -> None:
        """A normal start (the title, or ``start`` with the title off) and its note."""
        self.done = word
        _log.info("Story update: %s, a normal start.",
                  {"lost": "the place couldn't be carried over",
                   "restarted": "the place was removed",
                   "fresh": "no place to carry"}[word])
        self.ports.start_normally()
        self.ports.notify({"lost": NOTE_LOST, "restarted": NOTE_RESTARTED,
                           "fresh": NOTE_UPDATED}[word], "info")

    def _resume(self) -> None:
        states = self._states
        driver = self.ports.driver()
        if all(state is None for state in states):
            self._start_over("lost")
            return
        pick = pick_resume(driver, states)
        if pick is None:
            self._start_over("restarted")
            return
        outcome: list[object] = []

        def start() -> None:
            outcome.append(driver.restore(pick.state, use_hints=pick.use_hints,  # type: ignore
                                          fresh_menu=True))

        self.ports.enter_game(start)
        result = outcome[0] if outcome else None
        label = _label(pick.state)
        if result is None or result.result is not RestoreResult.OK:  # type: ignore[attr-defined]
            self.done = "failed"
            _log.info("Story update: the place at %s couldn't be restored.", label)
            error = getattr(result, "error", None)
            if error is not None:
                self.ports.show_fatal_error(error)
            else:                                  # a fit that stopped fitting: start over
                self.ports.start_normally()
                self.ports.notify(NOTE_LOST, "info")
            self.ports.keep(list(self._lines or ()))   # after the fatal hook ran
            return
        driver.interp.timeline.carry(pick.older)        # type: ignore[attr-defined]
        went_back = pick.index > 0
        self.done = "went_back" if went_back else "updated"
        _log.info("Story update: resumed at %s%s.", label,
                  ", an earlier line" if went_back else "")
        self.ports.notify(NOTE_WENT_BACK if went_back else NOTE_UPDATED, "info")


def _label(state: "GameState") -> str:
    at = state.position_at
    if type(at) is tuple and at and type(at[0]) is str:
        return at[0]
    return "?"


__all__ = ["FRAME_BYTES_MAX", "FRAME_STATES_MAX", "Held", "MESSAGE_LINE_MAX", "NOTE_LOST",
           "NOTE_RESTARTED", "NOTE_UPDATED", "NOTE_WENT_BACK", "Pick", "RESUME_WAIT_S",
           "Reload", "ResumeFrame", "ResumePorts", "ResumeScreen", "STATE_LINE_MAX",
           "StdinReader", "WINDOW_COORD_MAX", "collect_states", "encode_state_line",
           "fatal_states", "gather", "handle_messages", "held_note", "parse_message",
           "parse_resume_header", "parse_state", "pick_resume", "split_frame", "state_event",
           "story_states", "window_at"]
