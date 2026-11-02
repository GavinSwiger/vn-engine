"""F03 step 12 — the watchdog and the interrupt (``04-technical.md`` §7.7, TR-F03-07; ``07``
I-8, I-10). AC-F03-52 (stuck author code becomes E85m), AC-F03-53 (the watchdog fires only
when it should, a real Ctrl+C still exits 0), and AC-F03-83's watchdog row (a default that
hits the watchdog during restore).

The watchdog's rule is tested on a fake clock with a fake interrupt, and the App's I-8
fallback with a fake guard. Real-time rows patch ``AUTHOR_CODE_LIMIT_S`` to 0.5 s (each under
1 s); the one row at the real 5 s limit is ``slow`` (it prints the measured time with ``-s``).
AC-F03-53's sleeps are scaled to the 0.5 s limit in the same proportions (4 s → 0.4 s;
30 × 0.3 s → 30 × 0.03 s); the fake-clock rows cover the rule itself.
"""

import _thread
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pygame
import pytest

from engine.app.app import App
from engine.app.story import (RuntimeStoryDriver, Watchdog, interrupt_main, start_watchdog,
                              watchdog_timeout_error)
from engine.runtime import limits
from engine.runtime.interpreter import RestoreResult, Status
from engine.runtime.state import GameState
from engine.ui.screen import Screen
from tests.app.test_story_driver import instant
from tests.app.test_story_load_screen import launch, make_game, records
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.fakes.loop import post_key
from tests.runtime.story import advance, fingerprint, launched, load_files, load_r, start
from tests.script.helpers import template_r

E85M_TEXT = ("this Python ran for 5 seconds without finishing, so it is probably stuck in a "
             "loop. Check any while loop in this line and in the helpers it uses.")
SPIN = "any(x for x in iter(int, 1))"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Interrupts(list):
    def __call__(self) -> None:
        self.append(1)


@pytest.fixture
def fake():
    clock, interrupts = FakeClock(), Interrupts()
    return Watchdog(clock=clock, interrupt=interrupts), clock, interrupts


@pytest.fixture
def short_limit(monkeypatch):
    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.5)
    return 0.5


# --- The rule (fake clock) --------------------------------------------------------------------

def test_one_stuck_call_fires_once_at_the_limit(fake):
    w, clock, interrupts = fake
    w.enter()
    assert w.check() is False                           # first look: the call is noted
    clock.now = 4.99
    assert w.check() is False and interrupts == []
    clock.now = 5.0
    assert w.check() is True and interrupts == [1]
    clock.now = 60.0
    assert w.check() is False and interrupts == [1]     # once per call
    assert w.consume_fired() is True
    assert w.consume_fired() is False                   # True once


def test_nothing_fires_while_no_author_code_runs(fake):
    w, clock, interrupts = fake
    for k in range(100):
        clock.now = k
        w.check()
    w.enter()
    w.exit()
    for k in range(100, 200):
        clock.now = k
        w.check()
    assert interrupts == [] and w.consume_fired() is False


def test_each_call_starts_its_own_five_seconds(fake):
    """AC-F03-53's rule: 30 calls of 0.3 s each (9 s, no line between) never fire; neither
    does one 4 s call."""
    w, clock, interrupts = fake
    for _ in range(30):
        w.enter()
        w.check()
        clock.now += 0.3
        w.check()
        w.exit()
    w.enter()
    w.check()
    clock.now += 4.0
    w.check()
    w.exit()
    assert interrupts == [] and w.consume_fired() is False


def test_the_limit_is_read_at_each_look(fake, short_limit):
    w, clock, interrupts = fake
    w.enter()
    w.check()
    clock.now = 0.49
    assert w.check() is False
    clock.now = 0.5
    assert w.check() is True


def test_a_swallowed_interrupt_does_not_stop_the_next_call_firing(fake):
    """Author code that catches ``KeyboardInterrupt`` defeats one fire (accepted, §7.7);
    the next stuck call fires again."""
    w, clock, interrupts = fake
    w.enter()
    w.check()
    clock.now = 5.0
    w.check()
    w.exit()                                            # nobody asked consume_fired
    w.enter()
    w.check()
    clock.now = 10.0
    assert w.check() is True and interrupts == [1, 1]


def test_the_next_look_is_at_the_limit_when_that_comes_first(fake):
    w, clock, interrupts = fake
    assert w.next_look() == 0.25                        # idle: every tick
    clock.now = 10.0
    w.enter()
    assert w.next_look() == 0.25
    clock.now = 14.9
    assert w.next_look() == pytest.approx(0.1)          # 5 s after the call entered
    clock.now = 15.2
    assert w.next_look() == 0.0 and w.check() is True
    assert w.next_look() == 0.25                        # fired: back to every tick


def test_the_thread_starts_and_stops(fake):
    w, clock, interrupts = fake
    assert not w.alive
    w.start()
    try:
        assert w.alive and w._thread.daemon and w._thread.name == "vn-watchdog"
    finally:
        began = time.perf_counter()
        w.stop()
    assert not w.alive and time.perf_counter() - began < 0.5


def test_the_thread_touches_only_its_counters():
    """The thread rule (``docs/architecture.md``, ``07`` §3.3): the watchdog holds no
    reference to story state, the namespace, or the interpreter."""
    w = Watchdog()
    assert set(vars(w)) == {"_clock", "_interrupt", "_tick", "_lock", "_gen", "_started",
                            "_active", "_fired", "_fired_gen", "_stop", "_thread"}


# --- interrupt_main ---------------------------------------------------------------------------

def test_interrupt_main_wakes_a_blocking_sleep():
    """I-8: ``time.sleep`` in the main thread wakes with ``KeyboardInterrupt``."""
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    timer = threading.Timer(0.2, interrupt_main)
    began = time.perf_counter()
    timer.start()
    with pytest.raises(KeyboardInterrupt):
        time.sleep(5)
    assert time.perf_counter() - began < 1.5
    timer.join()


def test_interrupt_main_does_nothing_without_a_python_handler():
    saved = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        interrupt_main()
        time.sleep(0.05)
    finally:
        signal.signal(signal.SIGINT, saved)


# --- start_watchdog and the App's I-8 fallback ------------------------------------------------

class FakeGuard:
    def __init__(self, fired: bool) -> None:
        self.fired = fired

    def enter(self) -> None:
        pass

    def exit(self) -> None:
        pass

    def consume_fired(self) -> bool:
        fired, self.fired = self.fired, False
        return fired


class Interrupting(Screen):
    """A screen whose first update gets a ``KeyboardInterrupt`` (one that landed in engine
    code, past every other catch layer)."""

    opaque = True

    def __init__(self) -> None:
        self.raised = False

    def update(self, dt: float, *, is_top: bool) -> None:
        if not self.raised:
            self.raised = True
            raise KeyboardInterrupt

    def draw(self, canvas) -> None:
        canvas.fill((0, 0, 0))


@pytest.fixture
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.mark.display
def test_i8_a_fired_interrupt_in_the_loop_shows_e85m(pygame_ready, caplog):
    from engine.ui.builtin.error import ErrorScreen

    app, limiter = make_app(FakeWindow())
    app.watchdog = FakeGuard(fired=True)
    app.screens.replace_all([Interrupting()])
    limiter.quit_at(4)
    assert app.run() == 1                               # the error screen's exit code
    assert isinstance(app.screens.top, ErrorScreen)
    assert app.screens.top.message == E85M_TEXT
    assert [r.getMessage() for r in caplog.records if r.levelname == "ERROR"] == [E85M_TEXT]


@pytest.mark.display
@pytest.mark.parametrize("guard", [None, FakeGuard(fired=False)], ids=["no-story", "not-fired"])
def test_i8_a_real_ctrl_c_still_ends_the_loop(pygame_ready, guard):
    app, limiter = make_app(FakeWindow())
    app.watchdog = guard
    app.screens.replace_all([Interrupting()])
    limiter.quit_at(4)
    with pytest.raises(KeyboardInterrupt):
        app.run()
    assert not app.error_mode


def test_i8_with_a_story_e85m_names_the_current_line(tmp_path, caplog):
    """``watchdog_timeout_error`` with a story: E85m at its current statement, the story
    FAILED (logged once, nothing left to take)."""
    interp = start(load_r(tmp_path))
    driver = RuntimeStoryDriver(interp)
    driver.pump()
    holder = type("A", (), {"story": driver})()
    error = watchdog_timeout_error(holder)
    assert error.code == "E85m" and error.format() == "script/main.vns, line 7: " + E85M_TEXT
    assert interp.status is Status.FAILED and interp.take_commands(10) == []
    assert error.logged and [r.levelname for r in caplog.records].count("ERROR") == 1


def test_start_watchdog_once_per_app_and_stopped_at_shutdown():
    hooks = []
    holder = type("A", (), {"add_shutdown": staticmethod(hooks.append)})()
    w = start_watchdog(holder)
    try:
        assert holder.watchdog is w and start_watchdog(holder) is w and w.alive
        assert hooks == [w.stop]
    finally:
        for hook in hooks:
            hook()
    assert not w.alive


# --- AC-F03-52 — stuck author code becomes an error -------------------------------------------

HELPER_END = (" (in define wait, script/main.vns, line 11). Check any while loop in this line "
              "and in the helpers it uses.")

# id: (the row's edit, what the message starts with, where it ends or None)
AC52_ROWS = {
    "dollar": (dict(S="$ while True: pass"), "script/main.vns, line 8: " + E85M_TEXT, None),
    "condition": (dict(S=f'if {SPIN}:⏎[8]"A."'),
                  "script/main.vns, line 8: this condition ran for 5 seconds", None),
    "define": (dict(T=f"define spin = {SPIN}"),
               "The script has 1 problem:\n\nscript/main.vns, line 11: define spin couldn't "
               "be set: ", None),
    "default": (dict(T=f"default spin = {SPIN}"),
                "script/main.vns, line 11: default spin couldn't be set: ", None),
    "helper": (dict(T=f"define wait = lambda: {SPIN}", S="$ x = wait()"),
               "script/main.vns, line 8: this Python ran for 5 seconds", HELPER_END),
}


def _stuck_in_app(session, tmp_path: Path, *, S=None, T=None, space=True):
    """Launch R with the row's edit (Space at frame 5 when the row runs a line); returns
    (exit code, the App, seconds from the last guard entry to the error screen, the frame
    of that entry, the first frame whose start shows the error screen, launch seconds)."""
    from engine.ui.builtin.error import ErrorScreen

    game = instant(make_game(tmp_path, {"main.vns": template_r(S=S, T=T)}))
    entries, shown, tops = [], [], {}
    real_enter = Watchdog.enter
    real_show = App.show_fatal_error

    def enter(self):
        entries.append((time.perf_counter(), session.limiters[-1].frame))
        real_enter(self)

    def show_fatal_error(self, error, **kwargs):
        shown.append(time.perf_counter())
        real_show(self, error, **kwargs)

    for frame in range(1, 30):
        session.at(frame, lambda app, frame=frame: tops.__setitem__(frame, type(app.screens.top)))
    if space:
        session.at(5, lambda app: post_key(pygame.K_SPACE))
    session.quit_frame = 12
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Watchdog, "enter", enter)
        mp.setattr(App, "show_fatal_error", show_fatal_error)
        began = time.perf_counter()
        code = launch(game)
        took = time.perf_counter() - began
    errors = [f for f, t in tops.items() if t is ErrorScreen]
    last_entry = entries[-1]
    return (code, session.apps[-1], shown[0] - last_entry[0], last_entry[1],
            min(errors) if errors else None, took)


@pytest.mark.display
@pytest.mark.parametrize("row", AC52_ROWS.values(), ids=AC52_ROWS.keys())
def test_ac_f03_52_stuck_code_shows_e85m(tmp_path, user_roots, scripted_app, short_limit, row):
    from engine.ui.builtin.error import ErrorScreen

    edit, starts, ends = row
    code, app, waited, frame, first_error, took = _stuck_in_app(scripted_app, tmp_path, **edit)
    assert code == 1                                    # the QUIT ended launch() (error mode)
    assert isinstance(app.screens.top, ErrorScreen)
    message = app._fatal_message
    assert message.startswith(starts) and "ran for 5 seconds without finishing" in message
    if ends is not None:
        assert message.split("\n")[0].endswith(ends)
    assert 0.45 <= waited <= 1.0, waited
    assert first_error is not None and first_error <= frame + 2
    assert took < waited + 3.0                          # the rest of launch() is quick
    assert app.watchdog is not None and not app.watchdog.alive     # stopped at shutdown


@pytest.mark.display
@pytest.mark.slow
def test_ac_f03_52_the_real_five_seconds(tmp_path, user_roots, scripted_app, capsys):
    """Row 1 at the real limit: the error shows 5.0–5.5 s after the line starts (5.0–5.25 s
    by design) and the next frame shows the screen."""
    code, app, waited, frame, first_error, _ = _stuck_in_app(scripted_app, tmp_path,
                                                             S="$ while True: pass")
    assert code == 1 and app._fatal_message == "script/main.vns, line 8: " + E85M_TEXT
    with capsys.disabled():
        print(f"\nwatchdog fired after {waited:.3f} s")
    assert 5.0 <= waited <= 5.5, waited
    assert first_error == frame + 1


# --- TR-F03-07 / I-8: a blocking call is interrupted too --------------------------------------

@pytest.mark.display
def test_tr07_a_long_sleep_ends_in_e85m(tmp_path, user_roots, scripted_app, short_limit):
    code, app, waited, *_ = _stuck_in_app(scripted_app, tmp_path,
                                          T='define t = module("time")', S="$ t.sleep(30)")
    assert code == 1 and app._fatal_message == "script/main.vns, line 8: " + E85M_TEXT
    assert 0.45 <= waited <= 1.0, waited


# --- AC-F03-53 — the watchdog fires only when it should ---------------------------------------

def _play(session, tmp_path: Path, *, S: str, T: str, frames: int = 40):
    """Launch R; Space every frame from 5 (each line shows complete at once); the lines
    shown, the exit code, and the App."""
    from engine.ui.builtin.textbox_screen import TextboxScreen

    game = instant(make_game(tmp_path, {"main.vns": template_r(S=S, T=T)}))
    shown = []
    real_show = TextboxScreen.show
    for frame in range(5, frames):
        session.at(frame, lambda app: post_key(pygame.K_SPACE))
    session.quit_frame = frames
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(TextboxScreen, "show",
                   lambda self, cmd: shown.append(cmd.text) or real_show(self, cmd))
        code = launch(game)
    return shown, code, session.apps[-1]


@pytest.mark.display
@pytest.mark.parametrize("S", ["$ x = t.sleep(0.4)", "⏎[4]".join(["$ x = t.sleep(0.03)"] * 30)],
                         ids=["one-long-call", "thirty-calls"])
def test_ac_f03_53_long_but_finishing_calls_are_fine(tmp_path, user_roots, scripted_app,
                                                     short_limit, S):
    shown, code, app = _play(scripted_app, tmp_path, S=S, T='define t = module("time")')
    assert shown[:2] == ["Start.", "End."]
    assert not app.error_mode
    log = records(tmp_path / "game" / "logs" / "latest.log")
    assert not [r for r in log if r[0] == "ERROR"]


@pytest.mark.display
def test_ac_f03_53_a_real_ctrl_c_exits_zero(tmp_path, user_roots, scripted_app):
    """A 2 s author loop and a real SIGINT while ``fired`` is False: F01's interrupt path
    (exit 0), not E85m. SIGINT keeps Python's default handler at story start."""
    game = instant(make_game(tmp_path, {"main.vns": template_r(
        T='define t = module("time")',
        S="$ end = t.monotonic() + 2⏎[4]$ while t.monotonic() < end: pass")}))
    handlers = []

    def press_and_interrupt(app):
        handlers.append(signal.getsignal(signal.SIGINT))
        post_key(pygame.K_SPACE)
        if sys.platform == "win32":
            threading.Timer(0.3, _thread.interrupt_main).start()
        else:
            threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGINT)).start()

    scripted_app.at(5, press_and_interrupt)
    scripted_app.quit_frame = 20
    began = time.perf_counter()
    assert launch(game) == 0
    assert time.perf_counter() - began < 1.9            # interrupted, not the full 2 s loop
    assert handlers == [signal.default_int_handler]
    log = records(game / "logs" / "latest.log")
    assert ("INFO", "app", "Interrupted from the terminal (Ctrl+C)") in log
    assert not [r for r in log if r[0] == "ERROR"]
    assert scripted_app.apps[-1].watchdog.consume_fired() is False


# --- AC-F03-83's watchdog row: a default stuck during restore ---------------------------------

def _flow(root: Path, T: str):
    flow = Path(__file__).resolve().parents[1] / "fixtures" / "F03" / "flow" / "main.vns"
    return load_files(root, {"main.vns": flow.read_text(encoding="utf-8") + T + "\n"})


def _state_at_six(root: Path) -> dict:
    interp = start(_flow(root, "default base = 1\ndefault c = base + 1"))
    while interp.current.text != "6":
        advance(interp)
    data = json.loads(json.dumps(interp.checkpoint().to_json()))
    del data["variables"]["base"]
    return data


def test_ac_f03_83_a_default_stuck_during_restore(tmp_path, short_limit):
    data = _state_at_six(tmp_path / "v1")
    program = _flow(tmp_path / "v2", f"default base = {SPIN}\ndefault c = base + 1")
    watchdog = Watchdog()
    watchdog.start()
    try:
        driver = RuntimeStoryDriver(launched(program, guard=watchdog))
        interp = driver.interp
        for status in (Status.IDLE, Status.FAILED):
            if status is Status.FAILED:
                driver.new_game()                       # the stuck default fails the game
                assert driver.pump()[-1].error.code == "E85m"
            assert interp.status is status
            before = fingerprint(interp)
            began = time.perf_counter()
            outcome = driver.restore(GameState.from_json(data))
            assert 0.45 <= time.perf_counter() - began <= 1.0
            assert outcome.result is RestoreResult.DEFAULT_FAILED
            assert outcome.error.code == "E85m"
            assert outcome.error.format().startswith(
                "script/main.vns, line 17: default base couldn't be set: this value ran for "
                "5 seconds")
            assert fingerprint(interp) == before
            assert watchdog.consume_fired() is False    # the catch layer took it
        assert interp.checkpoint() is None
    finally:
        watchdog.stop()
