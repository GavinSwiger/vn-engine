"""The preview runner, headless (F44 ``04`` §3 "Report line", §6 item 3, §7.5; TR-F44-08;
``07`` I-4, I-5, I-16): ``start_value_args``, ``preview_argv``, report decoding, the reader,
and ``PreviewRunner``'s states against the fake children in ``tests/fixtures/F44/children/``.
Rows of AC-F44-10 (fake children), AC-F44-11, AC-F44-26 (argv), AC-F44-27 (start values).

Every child process is killed in the fixture's teardown. The default tier keeps one quick
subprocess row per behavior; the 50 MB, 5 MB, and real 2-second kill rows are ``slow``.
"""

import io
import json
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

from engine.core.paths import engine_root
from engine.core.startvalues import parse_set
from engine.tools.editor import preview
from engine.tools.editor.preview import (
    COULDNT_START,
    EOF,
    REPORT_MARKER,
    REPORT_MAX_BYTES,
    STARTED,
    TOO_LONG,
    PreviewRunner,
    PreviewState,
    Report,
    ReportItem,
    decode_report,
    preview_argv,
    read_child_output,
    start_value_args,
    start_values_head,
    start_values_report,
)

S = PreviewState
CHILDREN = Path(__file__).resolve().parents[2] / "fixtures" / "F44" / "children"


def child(name: str, *args: str) -> list[str]:
    """argv for a fake child."""
    return [sys.executable, str(CHILDREN / f"{name}.py"), *args]


class StubbornPopen(subprocess.Popen):
    """A child that ignores ``terminate()``, as ``hang`` does with SIGTERM on POSIX, so the
    kill path runs on every OS."""

    def terminate(self) -> None:
        pass


class Runners:
    """Makes runners whose children are all recorded, and ends them all afterwards."""

    def __init__(self) -> None:
        self.runners: list[PreviewRunner] = []
        self.procs: list[subprocess.Popen] = []
        self.calls: list[tuple[list[str], dict]] = []

    def make(self, popen=subprocess.Popen, **options) -> PreviewRunner:
        def spawn(argv, **kwargs):
            self.calls.append((list(argv), kwargs))
            proc = popen(argv, **kwargs)
            self.procs.append(proc)
            return proc

        options.setdefault("forward", lambda line: None)
        runner = PreviewRunner(popen=spawn, **options)
        self.runners.append(runner)
        return runner

    def alive(self) -> int:
        return sum(1 for proc in self.procs if proc.poll() is None)

    def close(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
        for runner in self.runners:
            runner.stop(timeout_s=1.0)


@pytest.fixture
def runners():
    made = Runners()
    try:
        yield made
    finally:
        made.close()


def run_until(runner: PreviewRunner, *states: PreviewState, timeout: float = 10.0,
              interval: float = 0.02) -> list:
    """Poll until the last event's state is one of ``states``; returns every event."""
    events: list = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        events += runner.poll()
        if events and events[-1].state in states:
            return events
        time.sleep(interval)
    raise AssertionError(f"timed out; events so far: {events}")


def states(events) -> list[PreviewState]:
    return [event.state for event in events]


# --- start_value_args (04 §7.3, I-5, I-14; AC-F44-26, AC-F44-27 rows) ------------------------

def test_box_lines_become_set_arguments():
    args, problems = start_value_args("sayo_points = 1\n# comment\n\nseen = ['x']")
    assert problems == []
    assert args[0::2] == ["--set", "--set"]
    assert parse_set(args[1]) == ("sayo_points", 1)
    assert parse_set(args[3]) == ("seen", ["x"])


def test_an_empty_box_gives_no_arguments():
    assert start_value_args("") == ([], [])
    assert start_value_args("\n   \n# only a comment\n") == ([], [])


def test_box_problems_name_every_line_and_start_nothing():
    args, problems = start_value_args(
        "sayo_points = Hana\n# ok\nseen = 1+1\nsayo_points = 2")
    assert args == []
    assert problems == [
        "Start values, line 1: put text in quotes.",
        "Start values, line 3: the value must be a number, True, False, None, quoted text, "
        "a list, or a dictionary.",
        "Start values, line 4: `sayo_points` is set twice.",
    ]
    report = start_values_report(problems)
    assert report.head == "The start values have 3 problems:"
    assert report.paragraphs() == [report.head, *problems]
    assert all(item.file is None and item.line is None for item in report.items)
    assert report.problem_count == 3


def test_line_numbers_count_blank_and_comment_lines():
    _, problems = start_value_args("\n# a\n\n  x = Hana  \n")
    assert problems == ["Start values, line 4: put text in quotes."]
    assert start_values_head(1) == "The start values have 1 problem:"


def test_more_than_100_values_is_one_problem():
    box = "\n".join(f"v{i} = {i}" for i in range(101))
    args, problems = start_value_args(box)
    assert args == []
    assert len(problems) == 1 and "100" in problems[0]
    assert problems[0].startswith("Start values: ")
    ok, none = start_value_args("\n".join(f"v{i} = {i}" for i in range(100)))
    assert none == [] and len(ok) == 200


def test_a_name_error_is_not_checked_in_the_editor():
    """E26c comes from the child (AC-F44-27's last row)."""
    args, problems = start_value_args("sayo_point = 1")
    assert problems == [] and args == ["--set", "sayo_point = 1"]


# --- preview_argv (04 §7.5; AC-F44-26) -------------------------------------------------------

def test_preview_argv(tmp_path):
    game = tmp_path / "my_game"
    assert preview_argv(game, "club_poem", ["--set", "x = 1"]) == [
        sys.executable, "-m", "engine", "run", str(game), "--report-to-editor",
        "--start", "club_poem", "--set", "x = 1"]
    assert preview_argv(game, None, []) == [
        sys.executable, "-m", "engine", "run", str(game), "--report-to-editor"]


def test_play_options_argv_ac_f47_03(tmp_path):
    """AC-F47-03: Play options' start values reach ``--set``; "Play as a new player"
    (``fresh``) adds ``--no-persistent``, and leaving it off adds nothing."""
    game = tmp_path / "my_game"
    args, problems = start_value_args("# start values\nsayo_points = 2\n\nname = 'Hana'")
    assert problems == []
    base = [sys.executable, "-m", "engine", "run", str(game), "--report-to-editor"]
    sets = ["--set", "sayo_points = 2", "--set", "name = 'Hana'"]
    assert preview_argv(game, "club", args, fresh=True) == [
        *base, "--no-persistent", "--start", "club", *sets]
    assert preview_argv(game, None, args) == [*base, *sets]
    assert "--no-persistent" not in preview_argv(game, None, [], fresh=False)


# --- decode_report (04 §3, §6 item 3; AC-F44-11's bad lines) --------------------------------

ITEM = {"text": "script/a.vns, line 14, column 16: boom.\n    x", "file": "script/a.vns",
        "line": 14, "column": 16}


def line_of(obj, *, ascii_only=True) -> bytes:
    return REPORT_MARKER + json.dumps(obj, ensure_ascii=ascii_only).encode("utf-8")


def error(**changes) -> dict:
    obj = {"v": 1, "event": "error", "phase": "start", "head": "The script has 1 problem:",
           "items": [ITEM], "tail": []}
    obj.update(changes)
    return obj


def test_started_and_error_lines_decode():
    assert decode_report(line_of({"v": 1, "event": "started"})) == STARTED
    report = decode_report(line_of(error(tail=["…and 3 more problems. Fix these."])))
    assert report == Report("start", "The script has 1 problem:", (
        ReportItem(ITEM["text"], "script/a.vns", 14, 16),), ("…and 3 more problems. Fix these.",))
    assert report.problem_count == 4
    nulls = decode_report(line_of(error(phase="run", head=None, items=[
        {"text": "x", "file": None, "line": None, "column": None}])))
    assert nulls.phase == "run" and nulls.head is None and nulls.items[0].file is None


def test_problem_count_reads_thousands_in_the_tail():
    report = Report("start", "h", (ReportItem("a"),),
                    ("…and 1,234 more problems. Fix these and launch again.",))
    assert report.problem_count == 1235


BAD_REPORT_LINES = [
    REPORT_MARKER + b"{not json",
    REPORT_MARKER + b"[1, 2]",
    line_of({"v": 2, "event": "started"}),
    line_of({"v": True, "event": "started"}),
    line_of({"v": "1", "event": "started"}),
    line_of({"event": "started"}),
    line_of({"v": 1, "event": "bogus"}),
    line_of(error(phase="later")),
    line_of(error(items=[ITEM] * 61)),
    line_of(error(items=[])),
    line_of(error(items=[dict(ITEM, text="z" * 10_001)])),
    line_of(error(head="h" * 10_001)),
    line_of(error(tail=["t" * 10_001])),
    line_of(error(tail="…and 3 more")),
    line_of(error(head=3)),
    line_of(error(items=[dict(ITEM, line=True)])),
    line_of(error(items=[dict(ITEM, line=0)])),
    line_of(error(items=[dict(ITEM, column=-1)])),
    line_of(error(items=[dict(ITEM, line=1.5)])),
    line_of(error(items=[dict(ITEM, file=7)])),
    line_of(error(items=[{"file": "script/a.vns"}])),
    line_of(error(items=["text"])),
    line_of({k: v for k, v in error().items() if k != "tail"}),
    line_of(error(head="日本"), ascii_only=False),
    REPORT_MARKER + b"[" * 100_000 + b"]" * 100_000,
]


def test_a_bad_report_line_is_dropped():
    for bad in BAD_REPORT_LINES:
        assert decode_report(bad) is None, bad[:40]


def test_the_limits_themselves_are_accepted():
    items = [dict(ITEM, text="z" * 10_000)] * 60
    report = decode_report(line_of(error(items=items)))
    assert len(report.items) == 60
    # A line of exactly 1 MiB is accepted; one byte more is dropped.
    tail = ["t" * 10_000] * ((REPORT_MAX_BYTES - len(line_of(error(items=items)))) // 10_004)
    missing = REPORT_MAX_BYTES - len(line_of(error(items=items, tail=[*tail, ""])))
    assert 0 < missing <= 10_000
    exact = line_of(error(items=items, tail=[*tail, "t" * missing]))
    assert len(exact) == REPORT_MAX_BYTES and decode_report(exact) is not None
    assert decode_report(line_of(error(items=items, tail=[*tail, "t" * (missing + 1)]))) \
        is None


def test_a_line_over_1_mib_is_dropped_even_when_every_field_fits():
    big = line_of(error(phase="run", items=[dict(ITEM, text="a" * 10_000)] * 60,
                        tail=["t" * 10_000] * 60))
    assert len(big) > REPORT_MAX_BYTES
    assert decode_report(big) is None


# --- read_child_output (04 §7.5 "Reader thread") --------------------------------------------

def read_all(data: bytes):
    put, forwarded = [], []
    read_child_output(io.BytesIO(data), put.append, forwarded.append)
    return put, forwarded


def test_the_reader_queues_reports_and_forwards_other_lines_unchanged():
    started = line_of({"v": 1, "event": "started"})
    put, forwarded = read_all(b"hello \xe6\x97\xa5\xe6\x9c\xac\n" + started + b"\r\n"
                              + line_of(error()) + b"\nlast line, no break")
    assert put[0] == (STARTED, None)
    assert put[1][0] == "error" and put[1][1].items[0].line == 14
    assert put[-1] == (EOF, None) and len(put) == 3
    assert forwarded == [b"hello \xe6\x97\xa5\xe6\x9c\xac\n", b"last line, no break"]


def test_a_line_cut_off_by_the_limit_is_discarded_up_to_its_newline():
    started = line_of({"v": 1, "event": "started"})
    huge = b"y" * (3 * REPORT_MAX_BYTES + 5)
    put, forwarded = read_all(huge + b"\n" + started + b"\n" + b"after\n")
    assert put == [(STARTED, None), (EOF, None)]
    assert forwarded == [b"after\n"]
    put, forwarded = read_all(REPORT_MARKER + huge + b"\n" + started + b"\n")
    assert put == [(STARTED, None), (EOF, None)] and forwarded == []


def test_bad_report_lines_are_neither_queued_nor_forwarded():
    put, forwarded = read_all(REPORT_MARKER + b"{oops\n" + line_of({"v": 2}) + b"\n")
    assert put == [(EOF, None)] and forwarded == []


def test_the_reader_survives_a_broken_pipe():
    class Broken(io.BytesIO):
        def readline(self, size=-1):
            raise OSError("broken pipe")

    put = []
    read_child_output(Broken(), put.append, lambda line: None)
    assert put == [(EOF, None)]


def test_forwarded_lines_reach_the_editors_stdout(capfd):
    preview.forward_to_stdout("hello 日本\n".encode("utf-8"))
    assert capfd.readouterr().out.replace("\r\n", "\n") == "hello 日本\n"


def test_forwarding_without_a_stdout_does_nothing(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    preview.forward_to_stdout(b"x\n")


# --- Spawning (04 §7.5; AC-F44-10 argv row, AC-F44-26 Popen row) ----------------------------

def test_popen_gets_the_engine_root_two_pipes_and_utf8(runners):
    runner = runners.make()
    runner.start(child("started_exit0"))
    run_until(runner, S.CLOSED)
    (argv, kwargs), = runners.calls
    assert argv == child("started_exit0")
    assert Path(kwargs["cwd"]) == engine_root()
    assert kwargs["stdin"] is subprocess.PIPE and kwargs["stdout"] is subprocess.PIPE  # F39
    assert "stderr" not in kwargs                  # inherited: the log goes to the terminal
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8:backslashreplace"


def test_a_missing_program_didnt_start(runners, tmp_path):
    runner = runners.make()
    runner.start([str(tmp_path / "no_such_python.exe"), "-c", "pass"])
    events = runner.poll()
    assert states(events) == [S.DIDNT_START] and runner.state is S.DIDNT_START
    text = events[0].report.paragraphs()
    assert len(text) == 1 and text[0].startswith(COULDNT_START.format(reason=""))
    assert events[0].report.problem_count == 1
    assert not runner.alive()


def test_an_oserror_from_popen_didnt_start():
    def refuse(argv, **kwargs):
        raise PermissionError(13, "Access is denied")

    runner = PreviewRunner(popen=refuse)
    runner.start(["x"])
    (event,) = runner.poll()
    assert event.report.paragraphs() == ["Couldn't start the preview: Access is denied."]


def test_a_command_line_over_32000_characters_starts_nothing_on_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(preview, "_IS_WINDOWS", True)
    runner = PreviewRunner(popen=lambda *a, **k: calls.append(a))
    runner.start(["python", "--set", "x = '" + "a" * 32_000 + "'"])
    (event,) = runner.poll()
    assert event.state is S.DIDNT_START and event.report.paragraphs() == [TOO_LONG]
    assert calls == []


def test_a_long_command_line_is_fine_elsewhere(monkeypatch, runners):
    monkeypatch.setattr(preview, "_IS_WINDOWS", False)
    runner = runners.make(popen=lambda argv, **k: subprocess.Popen(argv[:2], **k))
    runner.start([*child("started_exit0"), "a" * 33_000])
    assert states(run_until(runner, S.CLOSED)) == [S.STARTING, S.RUNNING, S.CLOSED]


# --- States with fake children (AC-F44-10) ---------------------------------------------------

def test_started_then_exit_0_is_closed(runners):
    runner = runners.make()
    runner.start(child("started_exit0"))
    events = run_until(runner, S.CLOSED)
    assert states(events) == [S.STARTING, S.RUNNING, S.CLOSED]
    assert all(event.report is None for event in events)


def test_a_run_time_error_stays_stopped_with_an_error(runners):
    runner = runners.make()
    runner.start(child("started_runerror_exit1"))
    events = run_until(runner, S.STOPPED_ERROR)
    assert states(events) == [S.STARTING, S.RUNNING, S.STOPPED_ERROR]
    report = events[-1].report
    assert report.phase == "run"
    assert report.items[0] == ReportItem(
        "script/chapter2.vns, line 7, column 5: dividing by zero isn't possible.",
        "script/chapter2.vns", 7, 5)
    runners.procs[0].wait(5)
    time.sleep(0.05)
    assert runner.poll() == [] and runner.state is S.STOPPED_ERROR


def test_a_load_error_didnt_start_with_the_kept_report(runners):
    runner = runners.make()
    runner.start(child("starterror_exit1"))
    events = run_until(runner, S.DIDNT_START)
    assert states(events) == [S.STARTING, S.DIDNT_START]
    report = events[-1].report
    assert report.head == "The script has 2 problems:" and report.problem_count == 2
    assert [(i.file, i.line, i.column) for i in report.items] == [
        ("script/chapter2.vns", 11, 16), ("script/main.vns", 7, None)]
    assert runners.procs[0].returncode == 1


def test_exit_3_with_no_report_stopped_unexpectedly(runners):
    runner = runners.make()
    runner.start(child("exit3"))
    assert states(run_until(runner, S.STOPPED_UNEXPECTED)) == [S.STARTING,
                                                               S.STOPPED_UNEXPECTED]


def test_a_killed_child_stopped_unexpectedly(runners):
    runner = runners.make()
    runner.start(child("started_selfkill"))
    events = run_until(runner, S.STOPPED_UNEXPECTED)
    assert states(events) == [S.STARTING, S.RUNNING, S.STOPPED_UNEXPECTED]


def test_bad_report_lines_change_nothing_and_started_still_runs(runners):
    runner = runners.make()
    runner.start(child("bad_reports_then_started"))
    assert states(run_until(runner, S.CLOSED)) == [S.STARTING, S.RUNNING, S.CLOSED]


def test_other_output_reaches_the_editors_stdout(runners, capfd):
    runner = runners.make(forward=preview.forward_to_stdout)
    runner.start(child("hello_utf8"))
    run_until(runner, S.CLOSED)
    assert "hello 日本\n" in capfd.readouterr().out.replace("\r\n", "\n")


def test_stop_ends_a_running_child_within_2_5_s(runners):
    runner = runners.make()
    runner.start(child("hang"))
    run_until(runner, S.RUNNING)
    began = time.monotonic()
    runner.stop()
    assert time.monotonic() - began < 2.5
    assert runners.alive() == 0 and not runner.alive()


def test_poll_never_waits_on_a_hanging_child(runners):
    runner = runners.make()
    runner.start(child("hang", "--silent"))
    worst = 0.0
    for _ in range(30):
        began = time.perf_counter()
        runner.poll()
        worst = max(worst, time.perf_counter() - began)
        time.sleep(0.01)
    assert worst < 0.010 and runner.state is S.STARTING


# --- One preview at a time (PR-F44-11; AC-F44-10 last row, AC-F44-30) -----------------------

def restart_while_hanging(runners: Runners, kill_after_s: float) -> tuple[list, float]:
    """``start()`` again while a child that ignores terminate is running. Samples every
    50 ms that at most one child is alive; returns the events and how long the old child
    took to die."""
    runner = runners.make(popen=StubbornPopen, kill_after_s=kill_after_s)
    runner.start(child("hang"))
    run_until(runner, S.RUNNING)
    old = runners.procs[0]
    runner.start(child("started_exit0"))
    began = time.monotonic()
    events = runner.poll()
    gone_after = None
    end = began + kill_after_s + 8
    while time.monotonic() < end:
        assert runners.alive() <= 1
        if gone_after is None and old.poll() is not None:
            gone_after = time.monotonic() - began
        events += runner.poll()
        if events and events[-1].state is S.CLOSED:
            break
        time.sleep(0.05)
    assert gone_after is not None, events
    return events, gone_after


def test_a_second_start_kills_the_old_child_then_spawns(runners):
    events, gone_after = restart_while_hanging(runners, kill_after_s=0.3)
    assert 0.25 <= gone_after < 1.5
    assert states(events) == [S.STARTING, S.RUNNING, S.CLOSED]
    assert len(runners.procs) == 2


@pytest.mark.slow
def test_a_hung_child_is_killed_within_2_5_s(runners):
    events, gone_after = restart_while_hanging(runners, kill_after_s=preview.KILL_AFTER_S)
    assert gone_after < 2.5
    assert states(events)[-1] is S.CLOSED


def test_a_child_that_obeys_terminate_is_replaced_at_once(runners):
    runner = runners.make()
    runner.start(child("hang"))
    run_until(runner, S.RUNNING)
    runner.start(child("started_exit0"))
    began = time.monotonic()
    events = run_until(runner, S.CLOSED)
    assert time.monotonic() - began < 2.0
    assert states(events) == [S.STARTING, S.RUNNING, S.CLOSED]
    assert runners.alive() == 0


def test_starting_three_times_spawns_only_the_last(runners):
    runner = runners.make(popen=StubbornPopen, kill_after_s=0.2)
    runner.start(child("hang"))
    run_until(runner, S.RUNNING)
    runner.start(child("exit3"))
    runner.start(child("started_exit0"))
    events = run_until(runner, S.CLOSED)
    assert [argv for argv, _ in runners.calls] == [child("hang"), child("started_exit0")]
    assert S.STOPPED_UNEXPECTED not in states(events)


def test_an_old_childs_reports_are_ignored(runners):
    runner = runners.make(popen=StubbornPopen, kill_after_s=0.2)
    runner.start(child("hang"))
    run_until(runner, S.RUNNING)
    runner.start(child("exit3"))
    events = run_until(runner, S.STOPPED_UNEXPECTED)
    assert S.RUNNING not in states(events)


def test_start_after_the_child_exited_spawns_at_once(runners):
    runner = runners.make()
    runner.start(child("exit3"))
    run_until(runner, S.STOPPED_UNEXPECTED)
    runner.start(child("started_exit0"))
    assert states(run_until(runner, S.CLOSED)) == [S.STARTING, S.RUNNING, S.CLOSED]


# --- Bounded reading (AC-F44-11, TR-F44-08) --------------------------------------------------

def timed_polls(runner: PreviewRunner, count: int = 200, interval: float = 0.02) -> tuple:
    worst, events = 0.0, []
    for index in range(count):
        began = time.perf_counter()
        events += runner.poll()
        took = time.perf_counter() - began
        if index:
            worst = max(worst, took)
        time.sleep(interval)
    return worst, events


@pytest.mark.slow
@pytest.mark.parametrize("name, end", [
    ("hang --silent", S.STARTING),
    ("flood50mb", S.RUNNING),
    ("longline5mb_then_started", S.RUNNING),
])
def test_reading_is_bounded_and_poll_never_blocks(runners, name, end):
    seen = []
    forwarded = [0]

    def forward(line: bytes) -> None:
        forwarded[0] += len(line)               # counted, never stored

    tracemalloc.start()
    try:
        baseline = tracemalloc.get_traced_memory()[0]
        runner = runners.make(forward=forward)
        runner.start(child(*name.split()))
        worst, events = timed_polls(runner)
        seen += events
        peak = tracemalloc.get_traced_memory()[1] - baseline
    finally:
        tracemalloc.stop()
    assert worst < 0.010, worst
    assert runner.state is end, states(seen)
    assert peak < 50 * 1024 * 1024
    if name == "flood50mb":
        deadline = time.monotonic() + 20
        while forwarded[0] < 50 * 1024 * 1024 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert forwarded[0] == 50 * 1024 * 1024
    if name.startswith("longline"):
        assert forwarded[0] == 0                # the cut-off line is dropped, not forwarded
