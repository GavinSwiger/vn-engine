"""Studio's check runner, headless (F45 ``04`` §4.3, §7.2 steps 3-5; ``07`` I-1, I-2):
``decode_check_line``'s table and ``CheckRunner`` against the fake children in
``tests/fixtures/F45/children/``. AC-F45-09, AC-F45-14.

Every child is ended in the fixture's teardown. Timers are patched (``CHECK_TIMEOUT_S``
0.5 s, ``KILL_AFTER_S`` 0.2 s); no test waits for a real 30 s.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.core.editorreport import (
    CHECK_EVENT_MAX_ITEMS,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    REPORT_TEXT_MAX_CHARS,
)
from engine.core.paths import engine_root
from engine.tools.editor import checker
from engine.tools.editor.checker import (
    CheckDone,
    CheckItem,
    CheckRunner,
    CheckState,
    LabelLink,
    NameEntry,
    check_argv,
    decode_check_line,
)
from tests.tools.f45_games import CHILDREN

ITEM = {"severity": "error", "code": "E43", "source": "load", "text": "t",
        "file": "script/main.vns", "line": 1, "column": 2}


def line(obj: object) -> bytes:
    return REPORT_MARKER + json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode()


def event(name: str, **fields: object) -> dict:
    return {"v": 1, "event": name, **fields}


def problems(*items: dict) -> bytes:
    return line(event("problems", items=list(items)))


# --- AC-F45-09: bad check lines are dropped ---------------------------------------------------

BAD = {
    "invalid json": REPORT_MARKER + b"{not json",
    "v 2": line({"v": 2, "event": "done", "loaded": True, "problems": 0, "seconds": 0}),
    "bogus event": line(event("bogus")),
    "kind Image": line(event("names", kind="Image", items=[["a", None, None]])),
    "kind ../x": line(event("names", kind="../x", items=[["a", None, None]])),
    "severity fatal": problems({**ITEM, "severity": "fatal"}),
    "line -1": problems({**ITEM, "line": -1}),
    "line '9'": problems({**ITEM, "line": "9"}),
    "line true": problems({**ITEM, "line": True}),
    "name not a 3-list": line(event("names", kind="label", items=[["a", None]])),
    "link kind goto": line(event("graph", links=[["a", "b", "goto", "script/m.vns", 1]])),
    "link 4 fields": line(event("graph", links=[["a", "b", "jump", "script/m.vns"]])),
    "5,001 items": problems(*[ITEM] * (CHECK_EVENT_MAX_ITEMS + 1)),
    "long text": problems({**ITEM, "text": "a" * (REPORT_TEXT_MAX_CHARS + 1)}),
    "non-ascii": problems(ITEM).replace(b'"t"', '"日"'.encode("utf-8")),
    "over 1 MiB": problems(*[{**ITEM, "text": "a" * 9_000}] * 120),
    "done without loaded": line(event("done", problems=0, seconds=0)),
    "no marker": line(event("done", loaded=True, problems=0, seconds=0))[len(REPORT_MARKER):],
    "no items": problems(),
}


def test_ac_f45_09_bad_check_lines_are_dropped():
    for name, body in BAD.items():
        assert decode_check_line(body) is None, name
    # The largest valid line of each event, exactly at each limit, decodes.
    items = [{**ITEM, "text": "a" * REPORT_TEXT_MAX_CHARS} for _ in range(104)]
    items[-1]["text"] = "a" * (REPORT_TEXT_MAX_CHARS - (len(problems(*items)) - REPORT_MAX_BYTES))
    at_limit = problems(*items)
    assert len(at_limit) == REPORT_MAX_BYTES
    assert decode_check_line(at_limit)[0] == "problems"
    kind, payload = decode_check_line(problems(*[ITEM] * CHECK_EVENT_MAX_ITEMS))
    assert kind == "problems" and len(payload) == CHECK_EVENT_MAX_ITEMS
    assert payload[0] == CheckItem("error", "E43", "load", "t", "script/main.vns", 1, 2)
    names = line(event("names", kind="a" * 32, items=[["n", None, None]] * 5_000))
    assert decode_check_line(names) == ("names", ("a" * 32, (NameEntry("n"),) * 5_000))
    links = line(event("graph", links=[["a", "b", "menu", "script/m.vns", 3]] * 5_000))
    assert decode_check_line(links) == (
        "graph", (LabelLink("a", "b", "menu", "script/m.vns", 3),) * 5_000)
    done = decode_check_line(line(event("done", loaded=False, problems=7, seconds=1)))
    assert done == ("done", CheckDone(False, 7, 1.0, {}, 0))


# --- AC-F45-14: the runner with fake children ----------------------------------------------

class Fakes:
    """Runners whose children are the named fakes, in order; records every spawn, and
    ends every child afterwards."""

    def __init__(self) -> None:
        self.procs: list[subprocess.Popen] = []
        self.calls: list[tuple[list[str], dict]] = []
        self.runners: list[CheckRunner] = []
        self.queue: list[str] = []

    def make(self, *names: str, game: Path = Path("game")) -> CheckRunner:
        self.queue += names

        def spawn(argv, **kwargs):
            self.calls.append((list(argv), kwargs))
            fake = [sys.executable, str(CHILDREN / f"{self.queue.pop(0)}.py")]
            kwargs = {**kwargs, "cwd": str(CHILDREN)}
            proc = subprocess.Popen(fake, **kwargs)
            self.procs.append(proc)
            return proc

        runner = CheckRunner(game, popen=spawn)
        self.runners.append(runner)
        return runner

    def alive(self) -> int:
        return sum(1 for proc in self.procs if proc.poll() is None)

    def close(self) -> None:
        for runner in self.runners:
            runner.stop(timeout_s=1.0)
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass


@pytest.fixture
def fakes():
    made = Fakes()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(checker, "CHECK_TIMEOUT_S", 5.0)
        mp.setattr(checker, "KILL_AFTER_S", 0.2)
        try:
            yield made
        finally:
            made.close()


def poll_until(runner: CheckRunner, *states: CheckState, timeout: float = 10.0,
               every=None) -> list:
    events: list = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        events += runner.poll()
        if every is not None:
            every()
        if events and events[-1].state in states:
            return events
        time.sleep(0.05)
    raise AssertionError(f"timed out; events so far: {events}")


def kinds(events) -> list[CheckState]:
    return [e.state for e in events]


S = CheckState


def test_ac_f45_14_the_runner_with_fake_children(fakes, tmp_path):
    # done_ok: applied only on done; then eof_no_done and exit3 crash and keep it.
    runner = fakes.make("done_ok", "eof_no_done", "exit3", "garbage_then_done", "over_totals",
                        game=tmp_path)
    runner.request(b'{"v":1,"files":[]}\n', 1, launch=True)
    seen = []
    events = poll_until(runner, S.DONE, S.CRASHED, every=lambda: seen.append(runner.result))
    assert kinds(events) == [S.STARTED, S.DONE]
    assert seen[:-1] and all(result is None for result in seen[:-1])
    result = runner.result
    assert events[-1].result is result and result.serial == 1
    assert [i.text for i in result.problems] == ["first"] and result.problem_total == 1
    assert result.names == {"label": (NameEntry("start", "script/main.vns", 1),)}
    assert result.links == (LabelLink("start", "end", "jump", "script/main.vns", 2),)
    for serial, code in ((2, 0), (3, 3)):
        runner.request(None, serial, launch=False)
        events = poll_until(runner, S.CRASHED, S.DONE)
        assert kinds(events) == [S.STARTED, S.CRASHED] and events[-1].exit_code == code
        assert runner.result is result
    # garbage_then_done: bad lines dropped; over_totals: 1,000 kept of 1,001.
    runner.request(None, 4, launch=True)
    assert kinds(poll_until(runner, S.DONE, S.CRASHED)) == [S.STARTED, S.DONE]
    assert [i.text for i in runner.result.problems] == ["first"]
    runner.request(None, 5, launch=True)
    poll_until(runner, S.DONE, S.CRASHED)
    assert (len(runner.result.problems), runner.result.problem_total) == (1_000, 1_001)

    # Popen spy: argv, stdin, cwd, stderr, environment, window flags (07 I-1, I-2).
    (argv, kwargs), (argv2, kwargs2) = fakes.calls[:2]
    assert argv == check_argv(tmp_path) and kwargs["stdin"] == subprocess.PIPE
    assert argv2 == check_argv(tmp_path, overlay=False, launch=False)
    assert kwargs2["stdin"] == subprocess.DEVNULL
    assert "--stdin-overlay" in argv and "--stdin-overlay" not in argv2
    assert "--no-launch" in argv2 and "--no-launch" not in argv
    for options in (kwargs, kwargs2):
        assert options["cwd"] == str(engine_root())
        assert (options["stdout"], options["stderr"]) == (subprocess.PIPE, subprocess.DEVNULL)
        assert options["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert options["env"]["PYTHONIOENCODING"]
        if os.name == "nt":
            assert options["creationflags"] & subprocess.CREATE_NO_WINDOW

    # hang: TIMEOUT after 0.5 s, gone 0.2 s later (+ 0.5 s slack), old result kept.
    runner = fakes.make("hang", "hang", "done_ok", "no_stdin")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(checker, "CHECK_TIMEOUT_S", 0.5)
        runner.request(None, 6, launch=True)
        began = time.monotonic()
        assert kinds(poll_until(runner, S.TIMEOUT)) == [S.STARTED, S.TIMEOUT]
        assert time.monotonic() - began >= 0.5
        proc = fakes.procs[-1]
        gone_by = time.monotonic() + 0.2 + 0.5
        while proc.poll() is None and time.monotonic() < gone_by:
            runner.poll()
            time.sleep(0.05)
        assert proc.poll() is not None and runner.result is None

    # request twice while hang runs: never two children, the superseded serial never applied.
    runner.request(None, 7, launch=True)
    poll_until(runner, S.STARTED)
    while fakes.alive() == 0:
        time.sleep(0.02)
    runner.request(None, 8, launch=True)
    runner.request(None, 9, launch=True)
    counts = []
    events = poll_until(runner, S.DONE, S.CRASHED, every=lambda: counts.append(fakes.alive()))
    assert max(counts) <= 1
    assert kinds(events) == [S.STARTED, S.DONE] and runner.result.serial == 9

    # no_stdin with a 4 MiB overlay: request and every poll return within 10 ms. The poll
    # that spawns is allowed the process start (CreateProcess holds the GIL on Windows,
    # about 10-30 ms) but never the overlay write, which would block until the child exits.
    began = time.perf_counter()
    runner.request(b"x" * (4 << 20), 10, launch=True)
    times = [time.perf_counter() - began]
    events = []
    end = time.monotonic() + 10
    while time.monotonic() < end and not {S.DONE, S.CRASHED} & set(kinds(events)):
        began = time.perf_counter()
        new = runner.poll()
        took = time.perf_counter() - began
        if S.STARTED in kinds(new):
            assert took < 0.1
        else:
            times.append(took)
        events += new
        time.sleep(0.02)
    assert max(times) < 0.010
    assert kinds(events) == [S.STARTED, S.DONE]


def test_a_child_that_cant_spawn_is_crashed():
    """Not in AC-F45-14's table: ``Popen`` itself fails (no Python, a bad cwd)."""
    def refuse(argv, **kwargs):
        raise OSError(2, "No such file")

    runner = CheckRunner(Path("game"), popen=refuse)
    runner.request(None, 1, launch=True)
    events = poll_until(runner, S.CRASHED, timeout=2)
    assert kinds(events) == [S.STARTED, S.CRASHED]
    assert events[-1].reason == "No such file"
    assert not runner.running
