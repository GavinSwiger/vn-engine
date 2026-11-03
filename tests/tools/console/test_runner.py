"""F40 P1 — the console's Code line: ``codecheck.check_line``, ``runner.guarded`` and
``runner.run_code``, and ``fourthwall.names_identity`` (``04`` §7.3; ``05`` SEC-F40-02, -04,
-08, -11). AC-F40-13, AC-F40-14, AC-F40-15, AC-F40-16, AC-F40-36."""

import logging

import pytest

from engine.app.story import Watchdog
from engine.runtime import limits
from engine.runtime.commands import StoryFailed
from engine.runtime.fourthwall import names_identity
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.script.messages import format_message
from engine.tools.console import runner
from engine.tools.console.codecheck import LINE_MAX, CheckedLine, Refused, check_line
from engine.tools.console.runner import DONE, TOO_LONG, run_code
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)
from tests.runtime.story import load_files

STORY = '''define hana = Character("Hana")
points trust 0 to 10
default persistent.visited = []
default mood = "calm"
default bag = []
lock item lantern "Lantern" in "Things"
label start:
    hana "One."
    $ mood = "warm"
    hana "Two."
    "End."
    return
'''

W190_LINE = format_message("W190")
W190_LINE = W190_LINE[:1].upper() + W190_LINE[1:]


@pytest.fixture(scope="module")
def program(tmp_path_factory):
    return load_files(tmp_path_factory.mktemp("console_runner"), {"main.vns": STORY})


def waiting(program, *, guard=None) -> Interpreter:
    """A dev-run story WAITING on its first line (its ``print`` would log: SR-F03-28)."""
    store = PersistentStore(identity_scheme=program.identity_scheme)
    kwargs = {} if guard is None else {"guard": guard}
    launch = run_launch(program, persistent=store, dev=True, **kwargs)
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    interp = Interpreter(program, launch.namespace, persistent=store, **kwargs)
    interp.new_game(42)
    interp.run(10_000)
    assert interp.status is Status.WAITING
    interp.take_commands(1 << 30)
    return interp


def story_values(interp: Interpreter) -> dict:
    return {k: repr(v) for k, v in interp.G.items() if k not in interp.reserved}


def place(interp: Interpreter) -> tuple:
    """Status, line, checkpoint and timeline: what a failed or refused line leaves alone."""
    t = interp.timeline
    return (interp.status, interp.current, interp.last_checkpoint, list(t.states), t.cursor,
            t.block_pending, interp.core.state, interp.points.state(), interp.codex.state())


class Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.texts: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.texts.append(record.getMessage())


@pytest.fixture
def records():
    handler = Records()
    loggers = [logging.getLogger(), logging.getLogger("vn")]
    levels = [lg.level for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
    yield handler
    for lg, level in zip(loggers, levels):
        lg.removeHandler(handler)
        lg.setLevel(level)


def assert_running_on(interp: Interpreter) -> None:
    """The game runs on: WAITING, no E85m pending, no StoryFailed held or released."""
    assert interp.status is Status.WAITING
    assert interp.guard.consume_fired() is False
    assert not any(isinstance(c, StoryFailed) for c in interp.take_commands(1 << 30))


# --- AC-F40-13 — value, Done., and print -----------------------------------------------------

def test_ac13_expression_value_statement_done_and_print(program, records, capsys):
    interp = waiting(program)
    result = run_code(interp, 'mood == "calm" and "lantern" not in bag')
    assert result.lines == ("True",) and result.ok and result.ran
    result = run_code(interp, 'mood = "rainy"; bag.append("lantern")')
    assert result.lines == (DONE,) and result.ok
    assert interp.G["mood"] == "rainy" and interp.G["bag"] == ["lantern"]
    result = run_code(interp, 'print("hello", mood, sep="-"); print(len(bag))')
    assert result.lines == ("hello-rainy", "1", DONE)
    result = run_code(interp, 'print("before") or [mood] * 2')
    assert result.lines == ("before", "['rainy', 'rainy']")
    # The story's own print (which logs in a dev run) is back after each call.
    story_print = interp.G["__builtins__"]["print"]
    assert story_print.__name__ == "print" and not isinstance(story_print, runner._Printer)
    out = capsys.readouterr()
    for text in ("hello", "rainy", "before"):
        assert text not in out.out + out.err
        assert not any(text in t for t in records.texts)


# --- AC-F40-14 — refusals: E88, E87, E63, E62, E234, E245, E255, E233; nothing ran ---------

def test_ac14_refused_lines_run_nothing(program):
    interp = waiting(program)
    rows = [("import os", "E88"), ("hana = 1", "E87"), ("_x = 1", "E63"),
            ("dice = 1", "E62"), ("points.hana = 99", "E234"),
            ("persistent.endings = []", "E245"), ("codex.tips = 1", "E255"),
            ("points.patience + 1", "E233")]
    for line, code in rows:
        checked = check_line(line, program)
        assert isinstance(checked, Refused) and checked.code == code, (line, checked)
        before, calls, values = place(interp), interp.author_calls, story_values(interp)
        result = run_code(interp, line)
        assert result.lines == (checked.text,) and not result.ran and not result.ok
        assert not checked.text.startswith(("<console>", "script/"))   # no file or line
        assert (place(interp), interp.author_calls, story_values(interp)) == \
            (before, calls, values)
    # The same lines as a load shows them: the message text of each code.
    assert check_line("import os", program).text.startswith("A $ line can't import")
    assert isinstance(check_line("trust_seen = points.trust", program), CheckedLine)


# --- AC-F40-15 — Code runs in G only ---------------------------------------------------------

def test_ac15_engine_objects_are_not_reachable_by_name(program):
    interp = waiting(program)
    for name in ("interp", "program", "app", "self", "Interpreter", "G", "shell", "driver"):
        result = run_code(interp, name)
        assert result.lines == (f"NameError: name '{name}' is not defined",), name
    engine_types = (Interpreter, type(program), PersistentStore)
    assert not any(isinstance(v, engine_types) for v in interp.G.values())
    assert not any(isinstance(v, engine_types)
                   for v in interp.G["__builtins__"].values())
    assert_running_on(interp)


# --- AC-F40-16 — a Python error, SystemExit, and an endless loop: one line, game runs on -----

def test_ac16_errors_and_endless_loop_show_one_line(program, monkeypatch):
    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.1)
    watchdog = Watchdog(tick=0.02)
    watchdog.start()
    try:
        interp = waiting(program, guard=watchdog)
        before = place(interp)
        assert run_code(interp, "1 / 0").lines == ("ZeroDivisionError: division by zero",)
        assert run_code(interp, "raise SystemExit").lines == ("SystemExit",)
        assert run_code(interp, "while True: pass").lines == (TOO_LONG,)
        assert place(interp) == before
        assert_running_on(interp)
        # The story goes on as before.
        assert run_code(interp, "mood").lines == ("'calm'",)
    finally:
        watchdog.stop()


# --- AC-F40-36 — the Code-tab hostile table (05 §5) -------------------------------------------

class LateSigint:
    """A guard that fired just as the call returned: its SIGINT arrives in the drain."""

    def __init__(self) -> None:
        self.fired = False

    def enter(self) -> None:
        pass

    def exit(self) -> None:
        pass

    def consume_fired(self) -> bool:
        fired, self.fired = self.fired, False
        return fired


def test_ac36_hostile_code_lines(program, monkeypatch, records, capsys):
    monkeypatch.setattr(limits, "AUTHOR_CODE_LIMIT_S", 0.1)
    watchdog = Watchdog(tick=0.02)
    watchdog.start()
    try:
        interp = waiting(program, guard=watchdog)
        before = place(interp)
        rows = [
            ("raise KeyboardInterrupt", "KeyboardInterrupt"),
            ("raise SystemExit", "SystemExit"),
            ("exit()", "SystemExit"),
            ("raise GeneratorExit", "GeneratorExit"),
            ("while True: pass", TOO_LONG),
            ('__import__("time").sleep(30)', TOO_LONG),
            ("(lambda f: f(f))(lambda f: f(f))", "RecursionError: maximum recursion depth "
                                                 "exceeded"),
            ('"a" * 10**15', "MemoryError"),
            ("raise ValueError(type('E', (), {'__str__': lambda s: 1 / 0})())",
             "ValueError"),
            ("raise ValueError(type('E', (), {'__str__': lambda s: [0 for _ in iter(int, 1)]})"
             "())", TOO_LONG),
        ]
        for line, shown in rows:
            result = run_code(interp, line)
            assert result.lines == (shown,), (line, result.lines)
            assert result.ran and not result.ok
            assert place(interp) == before, line
            assert_running_on(interp)
        for line, code in (("points.hana = 99", "E234"), ("persistent.endings = []", "E245"),
                           ("codex.tips = 1", "E255"), ("(_x := 1)", "E63"),
                           ("import os", "E88"), ("(" * 300, "E80")):
            checked = check_line(line, program)
            calls = interp.author_calls
            result = run_code(interp, line)
            assert checked.code == code and result.lines == (checked.text,) and not result.ran
            assert interp.author_calls == calls and place(interp) == before
        # x = (lambda: 1): ran, then undone (it can't go into a save).
        result = run_code(interp, "x = (lambda: 1)")
        assert result.ran and not result.ok and result.undone and result.lines == ()
        assert "x" not in interp.G and place(interp) == before
        # 2,001 characters: cut to 2,000.
        result = run_code(interp, "1" * (LINE_MAX + 1))
        assert result.source == "1" * LINE_MAX and len(result.lines[0]) <= LINE_MAX
        # Identity reads still run and add W190's line (the name guard refuses the read).
        result = run_code(interp, '__import__("getpass").getuser()')
        assert result.ran and result.lines[0].startswith("RealNameRead")
        assert result.lines[-1] == W190_LINE
        result = run_code(interp, '__import__("getpass").__name__  # a comment')
        assert result.lines == ("'getpass'", W190_LINE)
        assert run_code(interp, "trust_note = 3  # USERNAME").lines == (DONE,)
        # A needle in code, value, print and error text reaches no log, stdout or stderr.
        result = run_code(interp, 'print("NDL7p") or "NDL7v"')
        assert result.lines == ("NDL7p", "'NDL7v'")
        assert run_code(interp, 'raise ValueError("NDL7e")').lines == ("ValueError: NDL7e",)
        assert_running_on(interp)
    finally:
        watchdog.stop()
    out = capsys.readouterr()
    assert "NDL7" not in out.out + out.err
    assert not any("NDL7" in t for t in records.texts)

    # The watchdog's SIGINT arriving after the call returned is drained here, not later.
    late = LateSigint()
    interp = waiting(program, guard=late)
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(runner, "_sleep", fake_sleep)
    before = place(interp)

    def returns_as_it_fires() -> int:
        late.fired = True
        return 1

    result = runner.guarded(interp, returns_as_it_fires)
    assert result.too_long and result.error == TOO_LONG and len(sleeps) == 3
    assert place(interp) == before and late.consume_fired() is False

    # W190's scan on one text (``fourthwall.names_identity``, SEC-F40-11).
    assert names_identity('__import__("getpass").getuser()')
    assert names_identity("import os; os . environ['X']")
    assert names_identity("LOGNAME")
    assert not names_identity("usernames = 1") and not names_identity("environ")
    assert not names_identity(None)  # type: ignore[arg-type]
