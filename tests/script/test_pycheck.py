"""Checking author Python (F02 checklist step 5; 04-technical.md §7.5).

AC-F02-31 (accepted Python), AC-F02-32 (wording and position of mistakes), AC-F02-34
(warnings are bounded), AC-F02-35 (CPython opens no file on F02's behalf), AC-F02-36
(compile work is bounded), and AC-F02-37 (F02 runs no author code), through a single-file
parse. Logging of W03 (AC-34) is the reporter's (step 9); slicing (AC-37's ``step()``
part) is the loader's (step 6).
"""

import ast
import builtins
import linecache
import sys
import time
import traceback
import tracemalloc
import warnings
from pathlib import Path

import pytest

from engine.script import pycheck
from engine.script.diagnostics import DiagnosticSink
from engine.script.nodes import If, PythonLine
from engine.script.statements import ParseContext
from tests.script.helpers import FIXTURES, message_at, parse_text, template

SCRIPT_DIR = Path(pycheck.__file__).resolve().parent


def node(parsed, index: int = 1):
    return parsed.labels["start"].block[index]


# --- AC-F02-31 ---------------------------------------------------------------------------

@pytest.mark.parametrize("row,source,column", [
    ("$ trust += 1", "trust += 1", 7),
    ("$trust=1", "trust=1", 6),
    ('$ x = f"{a!r:>{w}}" # note', 'x = f"{a!r:>{w}}" # note', 7),
    ('$ s = "#notcomment"', 's = "#notcomment"', 7),
    ("$ if x: pass", "if x: pass", 7),
])
def test_accepted_python_lines(row, source, column):
    parsed = parse_text(template(S=row))
    assert parsed.errors == [], parsed.messages
    line = node(parsed)
    assert isinstance(line, PythonLine)
    assert (line.py.mode, line.py.source, line.py.line, line.py.column) == (
        "exec", source, 5, column)


def test_bracket_continued_python_line():
    parsed = parse_text(template(S="$ x = (1,⏎[8]2,⏎⏎[8]# c⏎[8]3)"))
    assert parsed.errors == []
    line = node(parsed)
    assert line.py.source.split("\n") == ["x = (1,", "        2,", "", "        # c",
                                          "        3)"]
    assert (line.line, line.end_line, line.py.line) == (5, 9, 5)


def test_condition_and_define_value():
    parsed = parse_text(template(S='if (n := 2) > 1:⏎[8]"A."'))
    assert parsed.errors == []
    chain = node(parsed)
    assert isinstance(chain, If)
    condition = chain.branches[0].condition
    assert (condition.mode, condition.source, condition.line, condition.column) == (
        "eval", "(n := 2) > 1", 5, 8)
    parsed = parse_text(template(T='define v = {"a": [1, 2]}'))
    assert parsed.errors == []
    define = [n for n in parsed.nodes if getattr(n, "name", "") == "v"][0]
    assert (define.value.mode, define.value.source, define.value.line, define.value.column) == (
        "eval", '{"a": [1, 2]}', 9, 12)


@pytest.mark.parametrize("row", ["$ x = 2**10**100", "$ y = 'a'*10**9"])
def test_nothing_is_evaluated(row):
    start = time.perf_counter()
    parsed = parse_text(template(S=row))
    assert time.perf_counter() - start < 1.0
    assert parsed.errors == []


def test_empty_dollar_is_e84():
    parsed = parse_text(template(S="$"))
    assert [message_at(e) for e in parsed.errors] == [(
        "5", "this $ line is empty. Write Python after $, e.g. $ trust = 0, or remove the line.")]


@pytest.mark.parametrize("row,word", [("$ jump bridge", "jump"), ("$ return 1", "return")])
def test_statement_after_dollar_is_e83(row, word):
    parsed = parse_text(template(S=row))
    assert [message_at(e) for e in parsed.errors] == [
        ("5", f'"{word}" is a statement, not Python. Remove the $.')]


# --- AC-F02-32 ---------------------------------------------------------------------------

E80 = "this Python has a mistake: "
E81 = "this condition has a mistake: "
E82 = "this value has a mistake: "


@pytest.mark.parametrize("edit,where,message", [
    ({"S": "$ x = (1"}, "5:11", E80 + '"(" was never closed.'),
    ({"S": "$ x = [1,⏎⏎[8]# c⏎[8]2"}, "5:11", E80 + '"[" was never closed.'),
    ({"S": "$ x = “hi”"}, "5:11", E80 + "it uses a curly quote “. Python needs straight quotes \" or '."),
    ({"S": "$ x = ‘hi’"}, "5:11", E80 + "it uses a curly quote ‘. Python needs straight quotes \" or '."),
    ({"S": "$ x = 'abc"}, "5:11", E80 + "a quote is never closed."),
    ({"S": '$ x = """abc'}, "5:11", E80 + "a triple quote is never closed."),
    ({"S": "$ x = ('a' 'b'⏎[8]\"c)"}, "6:9", E80 + "a quote is never closed."),
    ({"S": "$ x = 1 \\"}, "5:14", E80 + "the line ends before the Python is complete."),
    ({"S": "$ x = 1 \\ 2"}, "5:14", E80 + "something follows a \\ that Python doesn't expect."),
    ({"S": "$ x = = 1"}, "5:11", E80 + "this isn't valid Python."),
    ({"S": "$ while x:"}, "5:15", E80 + "this isn't valid Python."),
    ({"S": "$ x = (1,⏎[8]2 +⏎[8])"}, "7:9", E80 + "this isn't valid Python."),
    ({"S": "$ break"}, "5:7", E80 + '"break" outside loop.'),
    ({"S": "$ x = (yield)"}, "5:12", E80 + '"yield" outside function.'),
    ({"S": "$ x == 1 = 2"}, "5:7", E80 + "cannot assign to comparison."),
    ({"S": "$ x = 0b2"}, "5:13", E80 + 'invalid digit "2" in binary literal.'),
    ({"S": "$ print 'hi'"}, "5:7",
     E80 + 'Missing parentheses in call to "print". Did you mean print(...)?'),
    ({"S": "$ x = " + "(" * 201 + "1" + ")" * 201}, "5:211", E80 + "too many nested parentheses."),
    ({"S": "$ x = " + "f'{" * 150 + "1" + "}'" * 150}, "5:459", E80 + "too many nested f-strings."),
    # I-8: the condition is compiled a second time in parentheses for Python's hint.
    ({"S": 'if trust = 3:⏎[8]"A."'}, "5:14",
     E81 + 'this isn\'t valid Python. Maybe you meant "==" or ":=" instead of "="?'),
    ({"S": 'if trust >= 2 and:⏎[8]"A."'}, "5", E81 + "this isn't valid Python."),
    ({"S": 'if 1 if x:⏎[8]"A."'}, "5:8", E81 + 'expected "else" after "if" expression.'),
    ({"S": 'if [x for x in y] = 1:⏎[8]"A."'}, "5:23", E81 + "this isn't valid Python."),
    ({"T": "define v = “x”"}, "9:12",
     E82 + "it uses a curly quote “. Python needs straight quotes \" or '."),
    ({"T": "define a = await b"}, "9:12", E82 + '"await" outside function.'),
])
def test_python_mistakes(edit, where, message):
    parsed = parse_text(template(**edit))
    assert [message_at(e) for e in parsed.errors] == [(where, message)]


def test_huge_integer_literal():
    parsed = parse_text(template(S="$ x = " + "1" * 5000))
    assert len(parsed.errors) == 1
    where, message = message_at(parsed.errors[0])
    assert where == "5"
    python_part = message.removeprefix(E80)
    assert python_part.startswith("Exceeds the limit (4300 digits) for integer string "
                                  "conversion")
    assert len(python_part) <= 120 and python_part.endswith("…")


def test_on_line_n_is_rewritten_to_the_file_line():
    parsed = parse_text(template(S="$ x = (1,⏎[8]2]"))
    assert [message_at(e) for e in parsed.errors] == [(
        "6:10", E80 + 'closing parenthesis "]" does not match opening parenthesis "(" on '
                      "line 5.")]


def test_rewrite_turns_jargon_into_plain_words():
    assert pycheck.rewrite("unexpected INDENT", 1) == "this isn't valid Python"
    assert pycheck.rewrite("bad token here", 1) == "this isn't valid Python"
    assert pycheck.rewrite("raise ValueError", 1) == "this isn't valid Python"
    assert pycheck.rewrite("unindent does not match", 1) == "this isn't valid Python"
    assert pycheck.rewrite("cannot assign to literal", 1) == "cannot assign to literal"


# --- AC-F02-34 ---------------------------------------------------------------------------

def test_python_warning_is_w03():
    keys = set(linecache.cache)
    parsed = parse_text(template(S="$ x = 1 is 1"))
    assert parsed.errors == []
    assert [w.format() for w in parsed.warnings] == [
        'script/main.vns, line 5: Python warns: "is" with "int" literal. Did you mean "=="?']
    assert set(linecache.cache) <= keys


def test_invalid_escape_warning():
    parsed = parse_text(template(S='$ x = "\\d"'))
    assert [w.format() for w in parsed.warnings] == [
        'script/main.vns, line 5: Python warns: invalid escape sequence "\\d".']


def test_at_most_50_w03_then_w03b():
    rows = "⏎".join(['[4]$ x = "\\d"'] * 100).removeprefix("[4]")
    parsed = parse_text(template(S=rows))
    warnings_ = parsed.warnings
    assert [w.code for w in warnings_] == ["W03"] * 50 + ["W03b"]
    assert warnings_[-1].format() == "…and 50 more Python warnings."


def test_one_piece_with_many_warnings_is_bounded():
    lines = ["$ x = ["]
    for _ in range(190):
        lines.append("[8]" + '"\\d",' * 100)     # 19,000 items, under the 100,000 cap
    lines.append("[8]]")
    parsed = parse_text(template(S="⏎".join(lines)))
    assert parsed.errors == []
    assert len(parsed.warnings) <= 51
    assert parsed.warnings[-1].code == "W03b"


def test_compile_leaves_warning_filters_alone():
    filters = list(warnings.filters)
    showwarning = warnings.showwarning
    rows = "⏎".join(['[4]$ x = "\\d"'] * 60).removeprefix("[4]")
    parse_text(template(S=rows))
    assert warnings.filters == filters and warnings.showwarning is showwarning


# --- AC-F02-35 ---------------------------------------------------------------------------

_OPENS: list[str] | None = None


def _audit(event: str, args: tuple) -> None:
    if _OPENS is not None and event == "open":
        _OPENS.append(str(args[0]))


sys.addaudithook(_audit)


@pytest.fixture
def opens():
    global _OPENS
    _OPENS = []
    try:
        yield _OPENS
    finally:
        _OPENS = None


@pytest.mark.parametrize("edit", [
    {"S": "$ x = (1"}, {"S": "$ break"}, {"S": "$ yield 1"}, {"S": "$ return 1"},
    {"S": 'if [x for x in y] = 1:⏎[8]"A."'}, {"T": "define a = await b"},
    {"S": "$ x = 1 is 1"},
])
def test_compiling_opens_no_file(edit, opens, tmp_path, monkeypatch):
    """CPython tries to open the compile name to quote the offending line (exec-mode syntax
    errors, compiler-stage errors). The loader passes the name under the real script folder;
    it can't be opened (a 300-character segment with ``<``/``>``), so the attempt fails and
    nothing outside ``<root>/script`` is ever named."""
    script = tmp_path / "script"
    script.mkdir()
    (script / "main.vns").write_text("MARKER-7f3a", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    ctx = ParseContext(sink=DiagnosticSink(), compile_name=str(script / pycheck.COMPILE_NAME))
    opens.clear()
    parsed = parse_text(template(**edit), ctx=ctx)
    for path in opens:
        assert Path(path).is_absolute() and Path(path).parent == script, path
        assert not Path(path).exists()
    for error in parsed.errors:
        assert "MARKER" not in error.format() and "MARKER" not in repr(vars(error))
    for warning in parsed.warnings:
        assert "MARKER" not in warning.format()


def test_default_compile_name_is_never_an_openable_path(opens):
    parse_text(template(S="$ x = (1"))
    assert set(opens) <= {pycheck.COMPILE_NAME}
    assert not Path(pycheck.COMPILE_NAME).exists()


def test_tracebacks_of_compiled_code_open_no_file(opens):
    parsed = parse_text(template(S="$ f = lambda: 1/0⏎[4]$ x = 1/0"))
    assert parsed.errors == []
    lambda_line, plain_line = node(parsed, 1), node(parsed, 2)
    for py in (lambda_line.py, plain_line.py):
        stack = [py.code]
        while stack:
            code = stack.pop()
            assert code.co_filename == "<script/main.vns>"
            stack.extend(c for c in code.co_consts if hasattr(c, "co_filename"))
    linecache.getlines(__file__)      # this test's own frames are in the traceback too
    opens.clear()
    namespace: dict = {}
    exec(lambda_line.py.code, namespace)  # the test runs it; F02 never does
    for run in (lambda: namespace["f"](), lambda: exec(plain_line.py.code, {})):
        try:
            run()
        except ZeroDivisionError as exc:
            text = "".join(traceback.format_exception(exc))
            assert '"<script/main.vns>"' in text
    assert opens == []


# --- AC-F02-36 ---------------------------------------------------------------------------

def _piece_lines(head: str, target: int, tail: str = "        )") -> list[str]:
    """``head`` + bracket-continued lines of ``"aaa",`` items (each line ≤ 10,000
    characters) + ``tail``, whose joined length (I-5) is exactly ``target``."""
    lines = [head]
    total = len(head)
    while True:
        remaining = target - total - 1 - (1 + len(tail))   # newline, line, newline + tail
        if remaining <= 9000:
            break
        line = "        " + '"aaa",' * 1498
        lines.append(line)
        total += 1 + len(line)
    lines.append("        " + '"' + "a" * (remaining - 8 - 3) + '",')
    lines.append(tail)
    assert len(chr(10).join(lines)) == target
    return lines


def _chunked(body: str, unit: int = 1) -> list[str]:
    """``x = (`` + ``body`` split over bracket-continued lines + ``)``; lines break at
    multiples of ``unit`` characters, so repeated items stay whole."""
    size = 8000 - 8000 % unit
    chunks = [body[i:i + size] for i in range(0, len(body), size)]
    return ["x = ("] + ["        " + chunk for chunk in chunks] + ["        )"]


def _as_s(lines: list[str]) -> str:
    return "⏎".join([lines[0]] + ["[0]" + line for line in lines[1:]])


class _CompileSpy:
    def __init__(self) -> None:
        self.sources: list[object] = []

    def __call__(self, source, *args, **kwargs):
        self.sources.append(source)
        return builtins.compile(source, *args, **kwargs)


@pytest.fixture
def compile_spy(monkeypatch):
    spy = _CompileSpy()
    monkeypatch.setattr(pycheck, "compile", spy, raising=False)
    return spy


def test_piece_of_exactly_100000_characters_is_compiled(compile_spy):
    lines = _piece_lines("x = (", 100_000)
    parsed = parse_text(template(S="$ " + _as_s(lines)))
    assert set(parsed.codes) <= {"E80"}
    assert any(isinstance(s, str) and len(s) == 100_000 for s in compile_spy.sources)


E86B = "{what} is longer than 100,000 characters, which is the limit. Split it into several $ lines."


@pytest.mark.parametrize("kind", ["exec", "condition", "value"])
def test_piece_over_100000_characters_is_e86b(kind, compile_spy):
    if kind == "exec":
        lines = _piece_lines("x = (", 100_001)
        text = template(S="$ " + _as_s(lines))
        what = "this Python"
    elif kind == "condition":
        lines = _piece_lines("(", 100_001)
        lines[-1] += ":"
        text = template(S="if " + _as_s(lines) + '⏎[8]"A."')
        what = "this condition"
    else:
        lines = _piece_lines("(", 100_001)
        text = template(T="define v = " + _as_s(lines))
        what = "this value"
    parsed = parse_text(text)
    assert [e.code for e in parsed.errors] == ["E86b"]
    assert parsed.errors[0].message == E86B.format(what=what)
    assert not any(isinstance(s, str) and len(s) > 100_000 for s in compile_spy.sources)


@pytest.mark.parametrize("body,unit", [("[" + "1," * 49_499 + "1]", 2),
                                       ("x and " * 16_499 + "x", 6)])
def test_long_linear_pieces_compile_quickly(body, unit):
    text = template(S="$ " + _as_s(_chunked(body, unit)))
    tracemalloc.start()
    start = time.perf_counter()
    try:
        parsed = parse_text(text)
        elapsed = time.perf_counter() - start
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert parsed.errors == [], parsed.messages
    assert elapsed < 3.0 * 3          # tracemalloc slows CPython down ~3×; 3 s without it
    assert peak <= 200 * 1024 * 1024


def test_64_lambdas_load():
    parsed = parse_text(template(S="$ x = " + "lambda: " * 64 + "1"))
    assert parsed.errors == []


E86 = ("this Python is too complex to check (too deeply nested, or more than 64 lambda). "
       "Split it into several $ lines.")


@pytest.mark.parametrize("count", [65, 2900, 4000])
def test_more_than_64_lambdas_is_e86_without_compiling(count, compile_spy):
    lines = _chunked("lambda: " * count + "1", 8)
    start = time.perf_counter()
    parsed = parse_text(template(S="$ " + _as_s(lines)))
    assert time.perf_counter() - start < 1.0
    assert [message_at(e) for e in parsed.errors] == [("5", E86)]
    assert not any("lambda" in str(source) for source in compile_spy.sources)


@pytest.mark.parametrize("body", ["-" * 99_000 + "1", "1+" * 5000 + "1", "x" + ".a" * 20_000])
def test_parser_and_compiler_limits_are_e86(body):
    parsed = parse_text(template(S="$ " + _as_s(_chunked(body))))
    assert [message_at(e) for e in parsed.errors] == [("5", E86)]


# --- AC-F02-37 ---------------------------------------------------------------------------

_BANNED_CALLS = {"exec", "eval", "__import__"}


def _script_modules() -> list[Path]:
    return sorted(SCRIPT_DIR.rglob("*.py"))


def test_no_author_code_runs_in_engine_script():
    for path in _script_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for item in ast.walk(tree):
            if isinstance(item, ast.Name):
                assert item.id not in _BANNED_CALLS, (path.name, item.lineno)
            if isinstance(item, ast.Attribute):
                assert item.attr != "literal_eval", (path.name, item.lineno)
            if isinstance(item, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in item.names] + [getattr(item, "module", "") or ""]
                for name in names:
                    assert not name.startswith(("runpy", "importlib")), (path.name, name)
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) \
                    and item.func.id == "compile":
                assert path.name == "pycheck.py", path.name
                keywords = {k.arg: k.value for k in item.keywords}
                assert isinstance(keywords.get("dont_inherit"), ast.Constant) \
                    and keywords["dont_inherit"].value is True, item.lineno
                first = item.args[0]
                assert not (isinstance(first, ast.Constant) and isinstance(first.value, bytes))


def test_exec_and_eval_are_never_called(monkeypatch):
    calls = []
    real_exec, real_eval = builtins.exec, builtins.eval
    monkeypatch.setattr(builtins, "exec", lambda *a, **k: calls.append("exec") or real_exec(*a, **k))
    monkeypatch.setattr(builtins, "eval", lambda *a, **k: calls.append("eval") or real_eval(*a, **k))
    for name in ("main.vns", "chapter1.vns", "routes/daichi.vns"):
        path = FIXTURES / "lanterns" / name
        parsed = parse_text(path.read_text(encoding="utf-8"), f"script/{name}")
        assert parsed.errors == []
    assert calls == []
