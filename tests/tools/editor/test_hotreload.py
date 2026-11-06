"""F39 P1, Studio's hot-reload runner, headless (``specs/F39-hot-reload/SPEC.md`` §4.2,
§5.1, §5.2): AC-F39-01 (happy path), AC-F39-02 (failures and the queued update), AC-F39-03
(the gate and the texts).

The children are in-process fakes: stdout is a real OS pipe read by the runner's reader
thread, stdin records what the writer thread sends, and the runner's clock is a fake, so
the 5-second waits cost nothing. The game's side (``engine.app.hot_reload``) writes the
``state`` event and reads the resume frame, so both ends of the protocol meet here.
"""

import io
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from engine.app import hot_reload as game
from engine.core import editorreport as er
from engine.tools.editor.checker import CheckEvent, CheckItem, CheckResult, CheckState
from engine.tools.editor.hotreload import (
    CHECK_FAILED_TEXT,
    HELD_SUFFIX,
    UPDATING_TEXT,
    HotReload,
    HotReloadEvent,
    held_text,
    updated_text,
)
from engine.tools.editor.preview import PreviewRunner, PreviewState, preview_argv

S = PreviewState
STARTED = b'VN-EDITOR-REPORT {"v":1,"event":"started"}\n'
LINES = [b'{"newest":1}\n', b'{"older":2}\n']        # Studio never parses a state


class Inbox:
    """A child's stdin: records every byte the writer thread sends."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> int:
        with self._lock:
            self._data += data
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def data(self) -> bytes:
        with self._lock:
            return bytes(self._data)


class FakeChild:
    """A preview child the test drives: ``say`` writes its stdout, ``exit`` ends it.
    ``stubborn`` ignores ``terminate`` (only ``kill`` ends it)."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        r, w = os.pipe()
        self.stdout = os.fdopen(r, "rb")
        self._out = os.fdopen(w, "wb")
        self.stdin = Inbox()
        self.returncode: int | None = None
        self.stubborn = False
        self.terminated = self.killed = False

    def say(self, data: bytes) -> None:
        self._out.write(data)
        self._out.flush()

    def exit(self, code: int = 0) -> None:
        if self.returncode is None:
            self.returncode = code
            self._out.close()

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.stubborn:
            self.exit(1)

    def kill(self) -> None:
        self.killed = True
        self.exit(-9)

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout or 0)
        return self.returncode


class Rig:
    """A runner on fake children and a fake clock, with a ``HotReload`` on it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.children: list[FakeChild] = []
        self.kwargs: list[dict] = []
        self.checks = 0
        self.runner = PreviewRunner(popen=self._popen, forward=lambda line: None,
                                    clock=lambda: self.now)
        self.hot = HotReload(self.runner, start_check=self._check,
                             clock_text=lambda: "14:32")
        self.events: list = []                  # preview events
        self.texts: list = []                   # preview_event's texts
        self.hot_events: list[HotReloadEvent] = []

    def _popen(self, argv, **kwargs):
        child = FakeChild(list(argv))
        self.children.append(child)
        self.kwargs.append(kwargs)
        return child

    def _check(self) -> None:
        self.checks += 1

    @property
    def child(self) -> FakeChild:
        return self.children[-1]

    def tick(self) -> None:
        """One poll-loop tick, as W2 wires it."""
        for event in self.runner.poll():
            self.events.append(event)
            self.texts.append(self.hot.preview_event(event))
        self.hot_events += self.hot.poll()

    def until(self, test, timeout: float = 5.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.tick()
            if test():
                return
            time.sleep(0.005)
        raise AssertionError(f"timed out; events: {[e.state for e in self.events]}")

    def until_state(self, state: PreviewState) -> None:
        self.until(lambda: self.runner.state is state)

    def until_children(self, n: int) -> None:
        self.until(lambda: len(self.children) >= n)

    def stdin_of(self, child: FakeChild, size: int) -> bytes:
        self.until(lambda: len(child.stdin.data()) >= size)
        return child.stdin.data()

    def reload_sent(self, child: FakeChild) -> None:
        """Wait until ``reload`` is the last thing ``child``'s stdin got."""
        self.until(lambda: child.stdin.data().endswith(er.RELOAD_MESSAGE))

    def started(self) -> None:
        self.child.say(STARTED)
        self.until_state(S.RUNNING)

    def done(self, *severities: str, overlay: bool = False) -> None:
        self.hot.check_event(CheckEvent(CheckState.DONE, 1, result(*severities)),
                             overlay=overlay)

    def close(self) -> None:
        for child in self.children:
            child.exit(0)
        self.runner.stop(timeout_s=0.5)


def result(*severities: str, loaded: bool = True) -> CheckResult:
    items = tuple(CheckItem(sev, "E43", "load", f"{sev} {i}", "a.vns", 1)  # type: ignore
                  for i, sev in enumerate(severities))
    return CheckResult(problems=items, problem_total=len(items), names={}, links=(),
                       loaded=loaded, serial=1, seconds=0.1)


def resume_frame_read(data: bytes) -> game.ResumeFrame:
    """The new child's stdin, read the way the game reads it."""
    reader = game.StdinReader(io.BytesIO(data), expect_resume=True).start()
    reader.join(5)
    frame = reader.take_frame()
    assert frame is not None
    return frame


@pytest.fixture
def rig():
    made = Rig()
    try:
        yield made
    finally:
        made.close()


BASE = preview_argv(Path("games/club"), "club_poem", ["--set", "sayo = 1", "--set", "x = 2"])


# --- AC-F39-01 ---------------------------------------------------------------------------------

def test_ac_f39_01_update_carries_the_place_to_a_new_child(rig):
    """``reload`` written; the ``state`` header and body read; the old child exits; the new
    argv drops ``--start``/``--set`` and adds ``--resume-from-editor`` and ``--window-at``;
    the frame body is byte-identical; with 0 states the argv is F5's plus
    ``--resume-from-editor`` and the window's spot."""
    rig.runner.start(BASE)
    assert rig.kwargs[0]["stdin"] is subprocess.PIPE
    rig.started()
    old = rig.child

    assert rig.hot.request() is True
    assert rig.checks == 1 and rig.hot.status == UPDATING_TEXT
    rig.done("warning", "info")
    rig.tick()
    assert rig.runner.state is S.UPDATING
    assert rig.stdin_of(old, len(er.RELOAD_MESSAGE)) == er.RELOAD_MESSAGE

    event = game.state_event(LINES, [-120, 80])         # the game's own writer
    old.say(b"an author's print\n" + event)
    old.exit(0)
    rig.until_children(2)
    new = rig.child
    assert not old.terminated and not old.killed
    assert new.argv == [*BASE[:BASE.index("--start")], "--resume-from-editor",
                        "--window-at=-120,80"]
    body = b"".join(LINES)
    header = (b'{"v":1,"msg":"resume","bytes":%d,"states":2,"lost":false}\n' % len(body))
    stdin = rig.stdin_of(new, len(header) + len(body))
    assert stdin == header + body
    frame = resume_frame_read(stdin)
    assert (frame.body, frame.states, frame.lost) == (body, 2, False)
    assert UPDATING_TEXT in rig.texts

    rig.started()
    assert rig.texts[-1] == updated_text("14:32") == "▶ Running. Updated at 14:32."

    # On the title (0 states): F5's argv plus --resume-from-editor, a plain frame.
    rig.hot.request()
    rig.done()
    rig.tick()
    rig.reload_sent(new)
    new.say(game.state_event([], [5, 5]))
    new.exit(0)
    rig.until_children(3)
    assert rig.child.argv == [*BASE, "--resume-from-editor", "--window-at=5,5"]   # its spot
    zero = b'{"v":1,"msg":"resume","bytes":0,"states":0,"lost":false}\n'
    assert rig.stdin_of(rig.child, len(zero)) == zero


# --- AC-F39-02 ---------------------------------------------------------------------------------

def test_ac_f39_02_no_answer_gives_a_lost_frame_and_updates_queue_once(rig):
    """No ``state`` in 5 s, or an exit without one: terminate (then kill) and a ``lost``
    frame. A bad header or an oversized body counts as no answer. A second update during one
    runs once after it."""
    # The shared limits match the game side's (W1 switches it to import them).
    assert (er.RELOAD_MESSAGE_MAX, er.RELOAD_STATES_MAX, er.RELOAD_FRAME_MAX,
            er.RELOAD_STATE_LINE_MAX, er.RELOAD_WAIT_S, er.RELOAD_WINDOW_MAX,
            er.RELOAD_HELD_MAX) == (
        game.MESSAGE_LINE_MAX, game.FRAME_STATES_MAX, game.FRAME_BYTES_MAX,
        game.STATE_LINE_MAX, game.RESUME_WAIT_S, game.WINDOW_COORD_MAX,
        game.HELD_ERRORS_MAX)
    lost = b'{"v":1,"msg":"resume","bytes":0,"states":0,"lost":true}\n'
    lost_argv = [*BASE, "--resume-from-editor"]

    def ask() -> FakeChild:
        child = rig.child
        rig.hot.request()
        rig.done()
        rig.tick()
        rig.reload_sent(child)
        return child

    def next_child_is_lost(n: int) -> None:
        rig.until_children(n)
        assert rig.child.argv == lost_argv
        assert rig.stdin_of(rig.child, len(lost)) == lost
        assert resume_frame_read(lost).lost is True
        rig.started()

    rig.runner.start(BASE)
    rig.started()

    # 1. Silent for 5 s, and deaf to terminate: terminated, then killed.
    silent = ask()
    silent.stubborn = True
    rig.now += 4.9
    rig.tick()
    assert not silent.terminated
    rig.now += 0.2
    rig.tick()
    assert silent.terminated and not silent.killed
    rig.now += rig.runner.kill_after_s
    rig.tick()
    assert silent.killed
    next_child_is_lost(2)

    # 2. Exits without a state.
    ask().exit(0)
    next_child_is_lost(3)

    # 3. A bad header (states without bytes) is no answer at once.
    bad = ask()
    bad.say(b'VN-EDITOR-REPORT {"v":1,"event":"state","bytes":0,"states":1,"window":null}\n')
    rig.until(lambda: bad.terminated)
    next_child_is_lost(4)

    # 4. An oversized body is no answer, and is never read into memory.
    big = ask()
    big.say(b'VN-EDITOR-REPORT {"v":1,"event":"state","bytes":%d,"states":1,'
            b'"window":null}\n' % (er.RELOAD_FRAME_MAX + 1))
    rig.until(lambda: big.terminated)
    next_child_is_lost(5)

    # 5. Saves during an update queue exactly one more, run after it.
    first = ask()
    assert rig.hot.request() and rig.hot.request()
    checks = rig.checks
    first.say(game.state_event(LINES, None))
    first.exit(0)
    rig.until_children(6)
    assert rig.checks == checks                         # nothing until it started
    rig.started()
    assert rig.checks == checks + 1                     # the queued one, once
    rig.done()
    rig.tick()
    rig.reload_sent(rig.child)
    rig.child.say(game.state_event(LINES, None))
    rig.child.exit(0)
    rig.until_children(7)
    rig.started()
    assert rig.checks == checks + 1 and len(rig.children) == 7


# --- AC-F39-03 ---------------------------------------------------------------------------------

def test_ac_f39_03_the_gate_and_its_texts(rig):
    """Errors hold with the count; warnings or info only update; a timeout or crash gives
    S4; an overlay check forces a check without overlay; S1-S4 and the suffix verbatim."""
    assert UPDATING_TEXT == "▶ Updating…"
    assert CHECK_FAILED_TEXT == ("▶ Running the old story: the check didn't finish. Press "
                                 "Ctrl+R to try again.")
    assert HELD_SUFFIX == " The preview is still running the old story."
    assert rig.hot.request() is False and rig.checks == 0      # no preview: nothing
    rig.runner.start(BASE)
    rig.started()
    child = rig.child

    # Errors hold: S3 with the count, N5's count to the game, the suffix.
    rig.hot.request()
    rig.done("error", "warning", "error")
    held = b'{"v":1,"msg":"held","errors":2}\n'
    assert rig.stdin_of(child, len(held)) == held
    assert rig.hot.status == held_text(2) == ("▶ Running the old story: fix 2 problems to "
                                             "update it.")
    assert rig.hot.problems_suffix() == HELD_SUFFIX
    rig.tick()
    assert rig.hot_events[-1] == HotReloadEvent(held_text(2), HELD_SUFFIX)
    rig.hot.request()
    rig.done("error")
    assert rig.hot.status == "▶ Running the old story: fix 1 problem to update it."
    assert rig.runner.state is S.RUNNING

    # A timeout or a crash: S4, nothing sent.
    for state in (CheckState.TIMEOUT, CheckState.CRASHED):
        rig.hot.request()
        rig.hot.check_event(CheckEvent(state, 1), overlay=False)
        assert rig.hot.status == CHECK_FAILED_TEXT
    assert rig.runner.state is S.RUNNING

    # An overlay check (even with errors in unsaved text) forces a saved-files check; then
    # warnings and info only update, and the hold ends.
    rig.hot.request()
    checks = rig.checks
    rig.done("error", overlay=True)
    assert rig.checks == checks + 1 and rig.runner.state is S.RUNNING
    rig.done("warning", "info")
    rig.tick()
    assert rig.runner.state is S.UPDATING and rig.hot.problems_suffix() == ""
    assert rig.hot_events[-1] == HotReloadEvent(UPDATING_TEXT, "")


def test_resume_keeps_plays_beside_studio_spot_without_a_new_one():
    """Proposal 2.3: Play's ``--window-at``/``--window-size`` (the game beside Studio) stay
    when the old window had no spot (fullscreen, no answer); a spot it had replaces them."""
    from engine.tools.editor.hotreload import resume_argv
    from engine.tools.editor.preview import StateFrame

    base = [*BASE[:6], "--window-at=1300,40", "--window-size=960,540", *BASE[6:]]
    for frame in (None, StateFrame(b"", 0, None), StateFrame(b"x\n", 1, None)):
        argv = resume_argv(base, frame)
        assert "--window-at=1300,40" in argv and "--window-size=960,540" in argv
    argv = resume_argv(base, StateFrame(b"x\n", 1, (-40, 300)))
    assert "--window-at=1300,40" not in argv and argv[-1] == "--window-at=-40,300"
    assert "--window-size=960,540" in argv
