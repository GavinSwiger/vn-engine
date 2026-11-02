"""F03 step 7 — run-time errors (06-acceptance §1.2, §1.3, §1.7–1.9): AC-F03-09, 16, 19, 20,
21, 26, 27, 40, 45, 47, 49, 58 here; the message tables of AC-16, 19–21, 26, 27, 40, 45, 47
are rows of ``cases.toml`` (``test_messages_f03.py``); AC-48 and AC-50 run in the app
(``tests/app/test_story_driver.py``). Unit parts: the classification helpers of
``engine/runtime/errors.py`` (§7.11), the trace, and ``print`` (§7.12, PR-F03-31)."""

import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from engine.core.logsetup import RedactingFormatter
from engine.runtime import errors
from engine.runtime.commands import (Advance, AudioRestore, Say, ShowStage, StoryEnded,
                                     StoryFailed)
from engine.runtime.errors import (TRACE_HEAD, StoryError, first_setting_line, mixed_kinds,
                                   python_text_allowed, statement_source)
from engine.runtime.headless import run_headless
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.values import Unsaveable, freeze
from tests.runtime.story import advance, load_files, load_r, run_r, start, texts

ROOT = Path(__file__).resolve().parents[2]


def runtime_errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "vn.runtime" and r.levelno >= logging.ERROR]


# --- AC-F03-09 — a failed burst shows no part of itself -------------------------------------

def test_ac_f03_09_a_failed_burst_shows_nothing(tmp_path, monkeypatch):
    # The lines built for a checkpoint. Since F14 A2 (its 07 §3.2) a checkpoint holds its
    # line after the snapshot, so a line whose snapshot fails (E85e) is built, never held.
    held = []
    real_checkpoint = Interpreter.take_checkpoint

    def take_checkpoint(self, stmt, cmd, **kwargs):
        held.append(cmd)
        real_checkpoint(self, stmt, cmd, **kwargs)

    monkeypatch.setattr(Interpreter, "take_checkpoint", take_checkpoint)
    cmds = run_r(tmp_path, S="$ s = {1}")
    # F04: Start.'s stage; F08: the new game's AudioRestore first
    assert [type(c) for c in cmds] == [AudioRestore, ShowStage, Say, StoryFailed]
    assert cmds[2].text == "Start."
    assert (cmds[3].error.code, cmds[3].error.line) == ("E85e", 8)
    assert [c.text for c in held if type(c) is Say] == ["Start.", "End."]   # built, not shown


# --- AC-F03-16 — a failing default stops the game before it begins --------------------------

@pytest.mark.parametrize("T", ["default luck = 1 / 0", "default bag = {1, 2}",
                               "default luck = fortunez"])
def test_ac_f03_16_nothing_is_shown_and_no_checkpoint(tmp_path, T):
    interp = start(load_r(tmp_path, T=T))
    cmds = interp.take_commands(100)
    assert [type(c) for c in cmds] == [StoryFailed] and cmds[0].error.line == 11
    assert interp.checkpoint() is None and interp.status is Status.FAILED


# --- AC-F03-19 — subclasses are refused with their class name (unit) -------------------------

@pytest.mark.parametrize("value, name", [
    (__import__("collections").OrderedDict(), "OrderedDict"),
    (__import__("http").HTTPStatus.OK, "HTTPStatus"),
    (type("Shout", (str,), {})("x"), "Shout"),
])
def test_ac_f03_19_exact_types_only(value, name):
    with pytest.raises(Unsaveable) as caught:
        freeze(value)
    message = errors.unsaveable_message("v", caught.value)
    assert f"a Python object ({name})" in message and "(set at" not in message


# --- AC-F03-20 — when and where an unsaveable value is reported -----------------------------

def test_ac_f03_20_values_are_checked_at_checkpoints(tmp_path):
    assert texts(run_r(tmp_path / "a", S="$ s = {1}⏎[4]$ del s")) == ["Start.", "End."]
    cmds = run_r(tmp_path / "b", S="$ s = {1}⏎[4]return")
    assert [type(c) for c in cmds] == [AudioRestore, ShowStage, Say, StoryEnded]   # F08
    interp = start(load_r(tmp_path / "c", S="$ v = 1⏎[4]$ del v"))
    advance(interp)
    assert interp.current.text == "End." and "v" not in interp.checkpoint().variables
    cmds = run_r(tmp_path / "d", S='$ a = []⏎[4]$ b = a⏎[4]"Mid."⏎[4]$ b.append({1})')
    assert texts(cmds) == ["Start.", "Mid."] and cmds[-1].error.line == 12


# AC-F03-26 (E85h, the stub before F12) is retired by F12 (its 06 §0.1); F12's own tests
# are tests/runtime/test_persistent_story.py.


# --- AC-F03-27 — print, and exit/quit without site ------------------------------------------

def test_ac_f03_27_print_in_a_dev_run(tmp_path, caplog, capsys):
    caplog.set_level(logging.INFO, logger="vn.runtime")
    program = load_r(tmp_path, S='$ print("hello")')
    texts_ = texts(run_headless(program, seed=42, dev=True))
    assert texts_ == ["Start.", "End."]
    printed = [r for r in caplog.records if "print:" in r.getMessage()]
    assert [(r.levelno, r.name, r.getMessage()) for r in printed] == [
        (logging.INFO, "vn.runtime", "script/main.vns, line 8: print: hello")]
    assert capsys.readouterr().out == ""


def test_ac_f03_27_print_in_a_release_run(tmp_path, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    program = load_r(tmp_path, S='$ print("hello")')
    assert texts(run_headless(program, seed=42, dev=False)) == ["Start.", "End."]
    assert not [r for r in caplog.records if "hello" in r.getMessage()]
    captured = capsys.readouterr()
    assert captured.out == "" and "hello" not in captured.err


@pytest.mark.parametrize("S, T, line", [
    ('$ x = (1,⏎[8]print("a" * 300))', None, 9),             # a continued piece: exact line
    ("$ x = shout()", 'define shout = lambda: print("hi")', 8),   # the calling line
    ('if print("c") is None:⏎[8]"A."', None, 8),
], ids=["continued", "helper", "condition"])
def test_print_names_the_running_line(tmp_path, caplog, S, T, line):
    caplog.set_level(logging.INFO, logger="vn.runtime")
    run_headless(load_r(tmp_path, S=S, T=T), seed=42, dev=True)
    printed = [r.getMessage() for r in caplog.records if ": print: " in r.getMessage()]
    assert len(printed) == 1 and printed[0].startswith(f"script/main.vns, line {line}: print: ")
    assert len(printed[0].split(": print: ")[1]) <= 120               # through echo()


EXIT_WITHOUT_SITE = textwrap.dedent("""
    import builtins, sys
    from pathlib import Path
    del builtins.exit, builtins.quit
    from engine.runtime.headless import run_headless
    from tests.runtime.story import load_r
    for i, S in enumerate(("$ exit()", "$ quit()")):
        cmds = run_headless(load_r(Path(sys.argv[1]) / str(i), S=S), seed=42)
        print(cmds[-1].error.code, cmds[-1].error.format())
    print("still running")
""")


def test_ac_f03_27_exit_and_quit_without_site(tmp_path):
    out = subprocess.run([sys.executable, "-c", EXIT_WITHOUT_SITE, str(tmp_path.resolve())],
                         cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()[-3:]
    assert lines == [
        "E85f script/main.vns, line 8: this $ line tried to close the game with exit(). To end "
        "the story, use return instead.",
        "E85f script/main.vns, line 8: this $ line tried to close the game with quit(). To end "
        "the story, use return instead.",
        "still running"]


# --- AC-F03-40 — wrong dice use changes nothing ----------------------------------------------

@pytest.mark.parametrize("S", ["$ dice.seed(1)", "$ dice.state = 0", "$ dice.extra = 1",
                               "$ del dice.roll", "$ x = dice.roll(6, 1)"])
def test_ac_f03_40_the_dice_state_is_unchanged(tmp_path, S):
    interp = start(load_r(tmp_path, S=S))
    before = (interp.core.state, interp.core.ready)
    advance(interp)
    assert interp.status is Status.FAILED
    assert (interp.core.state, interp.core.ready) == before
    assert [a for a in dir(interp.G["dice"]) if not a.startswith("__")] == [
        "decimal", "pick", "roll", "shuffle"]


# --- AC-F03-45 — CPython's mixed-type messages (pinned for this minor version) ---------------

def _type_error(source: str) -> str:
    with pytest.raises(TypeError) as caught:
        exec(source, {})
    return str(caught.value)


@pytest.mark.parametrize("source, expected", [
    ('"3" + 1', ("add", "text", "a whole number", "+")),
    ('1 + "3"', ("add", "a whole number", "text", "+")),
    ('[1] + 1', ("add", "a list", "a whole number", "+")),
    ('None + 1', ("add", "nothing (None)", "a whole number", "+")),
    ('"a" - 1', ("operator", "text", "a whole number", "-")),
    ('"a" ** 2', ("operator", "text", "a whole number", "**")),
    ('x = "a"⏎x -= 1', ("operator", "text", "a whole number", "-")),
    ('{} * 1.5', ("operator", "a dictionary", "a decimal number", "*")),
    ('"a" < 1', ("compare", "text", "a whole number", "<")),
    ('1.5 >= "a"', ("compare", "a decimal number", "text", ">=")),
    ('[] < {}', ("compare", "a list", "a dictionary", "<")),
], ids=lambda v: v if isinstance(v, str) else None)
def test_ac_f03_45_cpython_templates(source, expected):
    text = _type_error(source.replace("⏎", "\n"))
    assert mixed_kinds(text) == expected, (sys.version_info[:2], text)


@pytest.mark.parametrize("source", ["len(5)", "(lambda: 1)(2)", "f = 1\nf()", "-'a'"])
def test_other_type_errors_are_not_e85d(source):
    assert mixed_kinds(_type_error(source)) is None


@pytest.mark.parametrize("S, message", [
    ("$ n = None + 1", "this adds nothing (None) and a whole number, which Python can't do. "
                       "Check the values this line uses."),
    ("$ n = [1] + 1", "this adds a list and a whole number, which Python can't do. Check the "
                      "values this line uses."),
    ("$ n = 1.5 + \"a\"", "this adds a decimal number and text, which Python can't do. Convert "
                          "one first with int(…), float(…), or str(…)."),
    ('$ n = "a" * "b"', "this Python stopped with an error. Check the values this line uses; "
                        "the log has the details."),
], ids=["none", "list", "decimal", "not-a-template"])
def test_e85d_drafted_forms(tmp_path, S, message):
    cmds = run_r(tmp_path, S=S)
    assert cmds[-1].error.message == message


@pytest.mark.parametrize("text, allowed", [
    ("list index out of range", True),                      # G8: plain words pass
    ("'k'", True),
    ("bad lantern", True),
    ("invalid literal for int() with base 10: 'abc'", False),  # a type called, int()
    ("object of type 'int' has no len()", False),           # a quoted type name
    ('can only concatenate str (not "int") to str', False),
    ("see KeyError", False),                                # an exception class name
    ("unexpected EOF while reading", False),                # PR-F02-31 banned terms
    ("bad node", False),
    ("the parser failed", False),
], ids=lambda v: v if isinstance(v, str) else None)
def test_sr_f03_32_python_text(text, allowed):
    assert python_text_allowed(text) is allowed


@pytest.mark.parametrize("S, message", [
    ("$ raise ValueError(\"it's 'odd'\")",
     "this Python stopped with an error: it's \"odd\". Check the values this line uses; the log "
     "has the details."),
    ('$ raise ValueError("done.")',
     "this Python stopped with an error: done. Check the values this line uses; the log has "
     "the details."),
    ('$ raise ValueError("x" * 300)', None),
], ids=["quotes", "full-stop", "long"])
def test_e85_quotes_python_text(tmp_path, S, message):
    error = run_r(tmp_path, S=S)[-1].error
    if message is not None:
        assert error.message == message
    else:
        assert len(error.message) < 220 and "…" in error.message           # echo() cuts


@pytest.mark.parametrize("S, T, message", [
    ('$ x = [].apend', None, 'a list has no "apend". Did you mean "append"?'),
    ("$ x = m.flor(1.5)", 'define m = module("math")',
     'the module math has no "flor". Did you mean "floor"?'),
    ("$ x = hana.nme", None, 'hana has no "nme". Did you mean "name"?'),
    ("$ x = None.zzz", None, 'nothing (None) has no "zzz". Check the spelling.'),
    ("$ x = bonus()", "define bonus = lambda: \"a\".uper()",
     'text has no "uper" (in define bonus, script/main.vns, line 11). Did you mean "upper"?'),
], ids=["list", "module", "character", "none", "helper"])
def test_e85c_forms(tmp_path, S, T, message):
    error = run_r(tmp_path, S=S, T=T)[-1].error
    assert (error.code, error.message) == ("E85c", message)


def test_e85c_reads_dir_under_the_guard(tmp_path):
    calls = []

    class Guard:
        def enter(self):
            calls.append("enter")

        def exit(self):
            calls.append("exit")

        def consume_fired(self):
            return False

    program = load_r(tmp_path, S="$ x = [].apend")
    from engine.runtime.launch import run_launch
    interp = Interpreter(program, run_launch(program).namespace, guard=Guard())
    interp.new_game(42)
    interp.run(100)
    advance(interp)
    assert interp.status is Status.FAILED
    assert calls.count("enter") == calls.count("exit") >= 3      # $ line, str(e), dir()


# --- E85b's $-line form (unit) ----------------------------------------------------------------

@pytest.mark.parametrize("S, written, line", [
    ("$ x = 1⏎[4]$ seen = [1, 2]", "[1, 2]", 9),
    ("$ seen += 1", "0", 8),
    ("$ for seen in range(3): pass", "0", 8),
    ("$ y = (seen := 5)", "5", 8),
    ("$ y = [(seen := k) for k in range(3)]", "k", 8),
    ('$ seen = "' + "x" * 50 + '"', "…", 8),
    ("$ a, seen = 1, 2", "0", 8),
    ("$ y = (1,⏎[8]seen := 2)", "2", 9),
], ids=["plain", "augmented", "for", "walrus", "walrus-in-comprehension", "long", "tuple",
        "continued"])
def test_first_setting_line(tmp_path, S, written, line):
    program = load_r(tmp_path, T="label later:⏎[4]" + S)    # label at 11, S from 12
    stmt, at, value = first_setting_line(program, "seen")
    assert (value, at) == (written, line + 4)


@pytest.mark.parametrize("S", ["$ y = [seen for seen in range(3)]", "$ f = (lambda seen: seen)",
                               "$ y = seen", "$ del seen", "$ y = {'seen': 1}"])
def test_first_setting_line_ignores_local_names(tmp_path, S):
    assert first_setting_line(load_r(tmp_path, T="label later:⏎[4]" + S), "seen") is None


# --- AC-F03-49 — the log record of a run-time error -------------------------------------------

def test_ac_f03_49_one_record_with_script_frames(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    program = load_r(tmp_path, S="$ x = bonus()", T="define bonus = lambda: 1 / 0")
    error = run_headless(program, seed=42, dev=True)[-1].error
    records = runtime_errors(caplog)
    assert len(records) == 1 and error.logged
    record = records[0]
    assert record.getMessage() == error.format()
    assert record.exc_text.split("\n") == [
        "    $ x = bonus()",
        TRACE_HEAD,
        "  script/main.vns, line 8 (label start)",
        "  in define bonus, script/main.vns, line 11",
        "ZeroDivisionError",
    ]
    text = RedactingFormatter().format(record)
    assert text.split("\n")[0].endswith(error.format())
    assert 'File "' not in text and ".py" not in text
    assert not [r for r in caplog.records if r is not record and r.levelno >= logging.ERROR]


def test_ac_f03_49_module_frames(tmp_path, caplog):
    program = load_r(tmp_path, S='$ x = js.loads("{")', T='define js = module("json")')
    error = run_headless(program, seed=42)[-1].error
    assert error.code == "E85"
    assert error.trace[0] == TRACE_HEAD and error.trace[-1] == "JSONDecodeError"
    modules = [line for line in error.trace if line.startswith("  in Python module ")]
    assert modules and modules[0] == "  in Python module json"
    assert all(".py" not in line and 'File "' not in line for line in error.trace)


def test_ac_f03_49_long_lines_are_cut(tmp_path, caplog):
    S = '$ x = len("' + "a" * 280 + '") / 0'
    assert len(S) >= 290
    run_headless(load_r(tmp_path, S=S), seed=42)
    (record,) = runtime_errors(caplog)
    shown = record.exc_text.split("\n")[0]
    assert shown.startswith("    $ x = len(") and shown.endswith("…") and len(shown) == 124


def test_ac_f03_49_engine_frames_are_left_out_and_repeats_folded(tmp_path):
    program = load_r(tmp_path, S="$ x = f(f, 0)", T="define f = lambda g, n: g(g, n + 1)")
    error = run_r(tmp_path / "x", S="$ x = dice.roll(6, 1)")[-1].error
    assert error.trace == (TRACE_HEAD, "  script/main.vns, line 8 (label start)",
                           "DiceArgumentError")
    error = run_headless(program, seed=42)[-1].error
    assert error.code == "E85i" and len(error.trace) == 5
    assert error.trace[2] == "  in define f, script/main.vns, line 11"
    assert error.trace[3].startswith("  (the line above repeats ")


AUDIT = textwrap.dedent("""
    import logging, sys
    from pathlib import Path
    from engine.runtime.commands import Advance
    from engine.runtime.interpreter import Interpreter
    from engine.runtime.launch import run_launch
    from tests.runtime.story import load_r

    program = load_r(Path(sys.argv[1]), S="$ x = bonus()", T="define bonus = lambda: 1 / 0")
    interp = Interpreter(program, run_launch(program, dev=True).namespace, dev=True)
    interp.new_game(42)
    interp.run(10_000)
    state = {"on": False, "opens": [], "written": 0}

    class Spy(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                state["on"] = False
                state["written"] += 1

    logging.getLogger("vn.runtime").addHandler(Spy())

    def hook(event, args):
        if state["on"] and event == "open":
            state["opens"].append(str(args[0]))

    sys.addaudithook(hook)
    interp.post(Advance(interp.current.sid))
    state["on"] = True
    interp.run(10_000)
    print(state["written"], len(state["opens"]), interp.status.name)
""")


def test_ac_f03_49_no_file_is_opened_before_the_record(tmp_path):
    out = subprocess.run([sys.executable, "-c", AUDIT, str(tmp_path.resolve())], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "1 0 FAILED"


# --- The record holds the statement's own text --------------------------------------------------

@pytest.mark.parametrize("S, T, shown", [
    ('if {}["k"]:⏎[8]"A."', None, 'if {}["k"]:'),
    ('if False:⏎[8]"A."⏎[4]elif 1 / 0:⏎[8]"B."', None, "elif 1 / 0:"),
    ("$ total = (1 +⏎[8]2 +⏎[8]1 / 0)", None, "1 / 0)"),
    (None, "default luck = 1 / 0", "default luck = 1 / 0"),
], ids=["if", "elif", "continued", "default"])
def test_the_source_line_is_rebuilt_from_the_program(tmp_path, S, T, shown):
    error = run_r(tmp_path, S=S, T=T)[-1].error
    assert error.source_line == shown
    assert errors.log_details(error).split("\n")[0] == "    " + shown


def test_statement_source_of_lines(tmp_path):
    program = load_r(tmp_path)
    say = program.labels["start"].block[0]
    assert statement_source(say) == 'hana "Start."'
    assert statement_source(say, say.line + 1) is None


# --- AC-F03-58 — when a checkpoint exists -------------------------------------------------------

def test_ac_f03_58_checkpoint_timing(tmp_path):
    program = load_r(tmp_path, S="⏎[4]".join(["$ a = 1"] * 50))
    from engine.runtime.launch import run_launch
    interp = Interpreter(program, run_launch(program).namespace)
    assert interp.checkpoint() is None
    interp.new_game(42)
    assert interp.checkpoint() is None                        # before the first run
    interp.run(10_000)
    first = interp.checkpoint()
    assert first is not None and first.position == interp.current.sid
    for _ in range(100):
        interp.run(10_000)
        assert interp.checkpoint() is first
    interp.post(Advance(interp.current.sid))
    for _ in range(50):
        interp.run(1)
        assert interp.checkpoint() is first                   # while the $ lines run
    interp.run(1)
    assert interp.current.text == "End." and interp.checkpoint() is not first
    assert interp.checkpoint().variables["a"] == 1

    failing = start(load_r(tmp_path / "f", S="$ x = 1 / 0"))
    assert failing.checkpoint() is not None
    advance(failing)
    assert failing.checkpoint() is None


def test_ac_f03_58_equality_is_type_aware():
    from tests.runtime.conftest import make_state
    assert make_state({"a": 1}) != make_state({"a": True})
    assert make_state({"a": 1}) != make_state({"a": 1.0})
    assert make_state({"a": 1}) == make_state({"a": 1})


# --- The error itself --------------------------------------------------------------------------

def test_story_error_is_logged_once(tmp_path, caplog):
    interp = start(load_r(tmp_path, S="$ x = 1 / 0"))
    interp.take_commands(10)
    advance(interp)
    (cmd,) = interp.take_commands(10)
    assert isinstance(cmd.error, StoryError) and cmd.error.logged
    assert len(runtime_errors(caplog)) == 1
    interp.post(Advance(interp.current.sid))
    interp.run(100)
    assert interp.take_commands(10) == [] and len(runtime_errors(caplog)) == 1


def test_no_message_names_a_set_at_clause(tmp_path):
    cmds = run_r(tmp_path, S="$ visited = set()")
    assert "(set at" not in cmds[-1].error.format()


def test_a_misbehaving_object_still_gives_a_message(tmp_path):
    error = run_r(tmp_path, S="$ x = W().zz",
                  T='define W = type("W", (), {"__class__": property(lambda s: 1 / 0)})')[-1].error
    assert (error.code, error.line) == ("E85", 8)
    assert error.message == ("this Python stopped with an error. Check the values this line "
                             "uses; the log has the details.")
