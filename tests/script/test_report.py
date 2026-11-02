"""Reporting a load to the log and console (F02 checklist step 9; 04-technical.md §7.10.1).

The loader (step 6) isn't built yet, so the ``LoadResult`` here is a stand-in with the same
attributes, filled from a single-file parse or from diagnostics built directly.
ACs: AC-F02-42, 45 (synthetic report), 48 (format; the 50,000-word corpus needs step 6),
49 (reporting; the release-run switch is ``LoadOptions.collect_todos``).
"""

import io
import logging
from dataclasses import dataclass, field

import pytest

from engine.core import redact as redact_module
from engine.core.logsetup import RedactingFormatter, get_logger
from engine.core.redact import Redactor, RedactRoot
from engine.script.diagnostics import (
    Diagnostic,
    DiagnosticSink,
    ScriptError,
    ScriptWarning,
)
from engine.script.limits import SCRIPT_REPORT_MAX_RECORDS
from engine.script.messages import format_message, source_window
from engine.script.nodes import ScriptFile
from engine.script.report import error_records, report_load_result
from engine.script.statements import ParseContext
from tests.script.helpers import parse_text, template

MAIN = ScriptFile("script/main.vns", "main.vns", 0)


@dataclass
class Stats:
    files: int = 1
    labels: int = 2
    statements: int = 3
    words: int = 4
    seconds: float = 0.25


@dataclass
class Result:
    """Stand-in for ``LoadResult`` (04 §4.3) until the loader exists."""

    program: object | None = None
    no_story: bool = False
    error_count: int = 0
    errors: tuple = ()
    checks_skipped: bool = False
    warnings: tuple = ()
    todos: tuple = ()
    todo_count: int = 0
    stats: Stats = field(default_factory=Stats)


class Capture(logging.Handler):
    """Keeps every record and its F01-formatted line."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []
        self.formatter_ = RedactingFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]

    def lines(self) -> list[str]:
        return [self.formatter_.format(r) for r in self.records]


@pytest.fixture
def log():
    logger = get_logger("script")
    handler = Capture()
    old_level, old_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield logger, handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate


def _result_of(text: str, **kw) -> Result:
    parsed = parse_text(text, **kw)
    errors = tuple(parsed.errors)
    return Result(program=None if errors else object(), error_count=parsed.ctx.sink.error_count,
                  errors=errors, warnings=parsed.warnings)


# --- AC-F02-42: the line and a caret ---------------------------------------------------------

def test_ac42_three_error_records_with_the_caret_under_the_column(log):
    logger, handler = log
    result = _result_of(template(S="hana “Hi”"))
    report_load_result(result, logger)
    assert [r.levelno for r in handler.records] == [logging.ERROR] * 3
    assert {r.name for r in handler.records} == {"vn.script"}
    message, line, caret = handler.messages
    assert message.startswith("script/main.vns, line 5, column 10: this line uses curly quotes")
    assert line == "    " + "    hana “Hi”"
    assert caret == "    " + " " * 9 + "^"
    # In the formatted log lines (fixed-width prefix) the ^ is under the “.
    formatted = handler.lines()
    assert formatted[2].index("^") == formatted[1].index("“")


def test_ac42_console_gets_the_same_three_lines(log):
    logger, _ = log
    stream = io.StringIO()
    console = logging.StreamHandler(stream)
    console.setFormatter(RedactingFormatter())
    console.setLevel(logging.WARNING)
    logger.addHandler(console)
    try:
        report_load_result(_result_of(template(S="hana “Hi”")), logger)
    finally:
        logger.removeHandler(console)
    lines = stream.getvalue().splitlines()
    assert len(lines) == 3
    assert lines[1].endswith("    " + "    hana “Hi”")
    assert lines[2].endswith("    " + " " * 9 + "^")
    assert lines[2].index("^") == lines[1].index("“")


def test_ac42_a_tab_is_shown_as_one_space(log):
    logger, handler = log
    text = ('define hana = Character("Hana")\ndefine daichi = Character("Daichi")\n'
            'label start:\n\t"Start."\n\thana “Hi”\n')
    result = _result_of(text)
    assert [(e.line, e.column) for e in result.errors] == [(5, 7)]
    report_load_result(result, logger)
    _, line, caret = handler.messages
    assert line == "    " + " hana “Hi”"
    assert caret == "    " + " " * 6 + "^"


def test_ac42_a_far_column_shows_a_window():
    source = "".join(chr(ord("a") + i % 26) for i in range(200))
    shown, caret = source_window(source, 130)
    assert shown.startswith("…") and len(shown) <= 120
    assert shown[caret] == source[129]
    error = ScriptError("x.", code="E52", file="script/main.vns", line=5, column=130,
                        source_line=source)
    records = error_records(error)
    assert records[1] == "    " + shown
    assert records[1][records[2].index("^")] == source[129]


def test_ac42_no_caret_without_a_column(log):
    logger, handler = log
    result = _result_of(template(S="jmup bridge"))
    report_load_result(result, logger)
    assert handler.messages == [
        'script/main.vns, line 5: "jmup" is not a statement. Did you mean "jump"?',
        "    " + "    jmup bridge"]


def test_source_window_short_line_and_controls():
    assert source_window("    hana “Hi”", 10) == ("    hana “Hi”", 9)
    assert source_window("    hana “Hi”") == ("    hana “Hi”", None)
    # Escaping a control before the column moves the caret with it.
    assert source_window("\x1bab", 3) == ("\\x1bab", 5)
    long_tail, caret = source_window("x" * 50 + "y" + "x" * 300, 51)
    assert len(long_tail) == 120 and long_tail.endswith("…") and long_tail[caret] == "y"


def test_window_is_taken_after_redaction():
    # AC-F02-44 F3 (reporting part): the redaction happens before the 120-character window,
    # so a cut never leaves part of a root behind.
    saved = redact_module._installed
    redact_module.install(Redactor([RedactRoot("<home>", "/home/qauser7")], home_name="qauser7",
                                   case_insensitive=False))
    try:
        source = " " * 110 + 'str(home / "x") = "/home/qauser7/x"' + " " * 5 + "Q" + " " * 60
        shown, caret = source_window(source, source.index("Q") + 1)
        inside, inside_caret = source_window(source, source.index("qauser7") + 3)
        before, before_caret = source_window(source, source.index("str") + 1)
    finally:
        redact_module._installed = saved
    for text in (shown, inside, before):
        assert "qau" not in text and "<home>" in text
    assert shown[caret] == "Q"
    assert before[before_caret] == "s"
    assert inside[inside_caret:].startswith("<home>")


# --- Warnings, TODOs, success line -----------------------------------------------------------

def test_warnings_are_logged_at_warning_level(log):
    logger, handler = log
    warnings = (ScriptWarning(format_message("W02", ("script/golden.vns",)), code="W02"),
                ScriptWarning(format_message("W02", ("script/\x1b[31mx.vns",)), code="W02"),
                ScriptWarning(format_message("W02", ("script/a‮b.vns",)), code="W02"))
    report_load_result(Result(program=object(), warnings=warnings), logger)
    levels = [r.levelno for r in handler.records]
    assert levels == [logging.WARNING] * 3 + [logging.INFO]
    assert handler.messages[0] == ('script/golden.vns is not included, so it is not part of the '
                                   'game. Add include "golden.vns" to a file that is.')
    # AC-F02-44 F1 (reporting part): no raw ESC or U+202E in any record.
    for text in handler.messages + handler.lines():
        assert "\x1b" not in text and "‮" not in text
    assert "\\x1b" in handler.messages[1] and "\\u202e" in handler.messages[2]


def test_ac49_todo_records_in_a_dev_run(log):
    logger, handler = log
    ctx = ParseContext(sink=DiagnosticSink(), collect_todos=True)
    parsed = parse_text(template(T="# TODO: rewrite the bridge"), ctx=ctx)
    assert not parsed.errors
    report_load_result(Result(program=object(), todos=tuple(ctx.collected.todos),
                              todo_count=ctx.collected.todo_count), logger)
    todo = [r for r in handler.records if "TODO" in r.getMessage()]
    assert len(todo) == 1 and todo[0].levelno == logging.INFO
    assert todo[0].getMessage() == "script/main.vns, line 9: TODO: rewrite the bridge"


def test_ac49_no_todo_records_in_a_release_run(log):
    logger, handler = log
    ctx = ParseContext(sink=DiagnosticSink(), collect_todos=False)
    parse_text(template(T="# TODO: rewrite the bridge"), ctx=ctx)
    report_load_result(Result(program=object(), todos=tuple(ctx.collected.todos),
                              todo_count=ctx.collected.todo_count), logger)
    assert not any("TODO" in m for m in handler.messages)


def test_ac49_151_todos_give_150_records_and_a_summary(log):
    logger, handler = log
    ctx = ParseContext(sink=DiagnosticSink(), collect_todos=True)
    text = template(T="⏎".join(f"# TODO {i}" for i in range(151)))
    parse_text(text, ctx=ctx)
    report_load_result(Result(program=object(), todos=tuple(ctx.collected.todos),
                              todo_count=ctx.collected.todo_count), logger)
    todo = [m for m in handler.messages if "TODO" in m]
    assert len(todo) == 151
    assert todo[-1] == "…and 1 more TODO comments."
    assert todo[0] == "script/main.vns, line 9: TODO 0"


def test_ac48_success_line(log):
    logger, handler = log
    stats = Stats(files=10, labels=1_234, statements=56_789, words=50_000, seconds=1.234)
    report_load_result(Result(program=object(), stats=stats), logger)
    loaded = [r for r in handler.records if r.getMessage().startswith("Loaded story:")]
    assert len(loaded) == 1 and loaded[0].levelno == logging.INFO
    assert loaded[0].getMessage() == ("Loaded story: 10 files, 1,234 labels, 56,789 statements, "
                                      "50,000 words in 1.23 seconds.")
    assert loaded[0].name == "vn.script"


def test_ac48_no_success_line_with_errors(log):
    logger, handler = log
    report_load_result(_result_of(template(S="jmup bridge")), logger)
    assert not any(m.startswith("Loaded story:") for m in handler.messages)


def test_ac48_singular_counts():
    from engine.script.messages import loaded_line
    assert loaded_line(1, 1, 1, 1, 0.0) == ("Loaded story: 1 file, 1 label, 1 statement, 1 word "
                                            "in 0.00 seconds.")


def test_e100_and_e99_follow_the_errors(log):
    logger, handler = log
    sink = DiagnosticSink()
    for line in range(1, 61):
        sink.add(Diagnostic("E30a", MAIN, line, None, ("jmup", "jump")))
    result = Result(error_count=sink.error_count, errors=sink.errors(), checks_skipped=True)
    report_load_result(result, logger)
    assert handler.messages[-2:] == [
        "…and 10 more problems. Fix these and launch again.",
        "Some checks (labels, characters) were skipped because a file couldn't be read. Launch "
        "again after fixing it."]
    assert len(handler.records) == 52


# --- AC-F02-45: the report is bounded ----------------------------------------------------------

def _line_errors(count: int) -> tuple[ScriptError, ...]:
    return tuple(ScriptError("this line has a mistake.", code="E52", file="script/main.vns",
                             line=n, column=5, source_line='    "a\\qb"')
                 for n in range(1, count + 1))


def _warnings(code: str, count: int, *args) -> list[ScriptWarning]:
    return [ScriptWarning(format_message(code, args), code=code, file="script/main.vns", line=n)
            for n in range(1, count + 1)]


def test_ac45_synthetic_report_writes_at_most_400_records(log):
    logger, handler = log
    warnings = (_warnings("W02", 25, "script/x.vns") + _warnings("W02b", 1)
                + _warnings("W03", 120, "x") + _warnings("W04", 20, "hаna", "Cyrillic")
                + _warnings("W04s", 1, 1))
    todos = tuple((MAIN, n, f"TODO {n}") for n in range(1, 401))
    result = Result(program=None, error_count=60, errors=_line_errors(50), checks_skipped=True,
                    warnings=tuple(warnings), todos=todos, todo_count=400)
    report_load_result(result, logger)
    assert len(handler.records) <= SCRIPT_REPORT_MAX_RECORDS
    assert len(handler.records) == SCRIPT_REPORT_MAX_RECORDS     # the guard dropped the rest
    assert sum(r.levelno == logging.ERROR for r in handler.records) == 152


def test_ac45_record_budget_399_by_construction(log):
    # I-9: 50 × 3 errors + E100 + E99 + W01 + 21 W02 + W02b + 51 W03 + 21 W04 + 151 TODO
    # + 1 success line = 399 ≤ 400. Errors and the success line exclude each other, so the
    # largest real report is 398; nothing is dropped.
    logger, handler = log
    warnings = (_warnings("W01", 1) + _warnings("W02", 20, "script/x.vns") + _warnings("W02s", 1, 5)
                + _warnings("W02b", 1) + _warnings("W03", 50, "x") + _warnings("W03b", 1, "70")
                + _warnings("W04", 20, "hаna", "Cyrillic") + _warnings("W04s", 1, 3))
    todos = tuple((MAIN, n, f"TODO {n}") for n in range(1, 151))
    result = Result(program=None, error_count=70, errors=_line_errors(50), checks_skipped=True,
                    warnings=tuple(warnings), todos=todos, todo_count=9_999)
    report_load_result(result, logger)
    assert len(handler.records) == 150 + 2 + 1 + 21 + 1 + 51 + 21 + 151
    assert handler.messages[-1] == "…and 9,849 more TODO comments."
    assert 150 + 2 + 1 + 21 + 1 + 51 + 21 + 151 + 1 == 399 <= SCRIPT_REPORT_MAX_RECORDS


def test_report_accepts_todo_objects(log):
    logger, handler = log

    @dataclass
    class Todo:
        file: ScriptFile
        line: int
        text: str

    report_load_result(Result(program=object(), todos=(Todo(MAIN, 3, "TODO: x"),)), logger)
    assert handler.messages[0] == "script/main.vns, line 3: TODO: x"
