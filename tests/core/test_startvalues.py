"""Start values (F44 Step 1): AC-F44-03, TR-F44-02, the PR-F44-19 messages (with I-9), and
I-5's list check (malformed, duplicates, more than 100)."""

import ast
import dataclasses
import json
import math
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from engine.core import constants as c
from engine.core import startvalues as sv
from engine.core.startvalues import (
    StartOptions,
    StartValueError,
    parse_literal,
    parse_set,
    parse_set_list,
)

ROOT = Path(__file__).resolve().parents[2]

Q = "put text in quotes"
G = ("the value must be a number, True, False, None, quoted text, a list, "
     "or a dictionary")


def nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def nested_value(depth: int) -> list:
    value: list = []
    for _ in range(depth - 1):
        value = [value]
    return value


def same(a: object, b: object) -> bool:
    """Equal and of the same types all the way down (so 1 is not True, 1.0 is not 1)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, float) and math.isnan(a):
        return False
    return a == b


def plain(value: object) -> bool:
    """Only int, finite float, str, bool, None, list, and dict with str keys (AC-F44-03)."""
    if value is None or type(value) in (bool, int, str):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(plain(item) for item in value)
    if type(value) is dict:
        return all(type(k) is str and plain(v) for k, v in value.items())
    return False


# --- Constants ----------------------------------------------------------------------------

def test_constants():
    assert (c.SET_MAX_COUNT, c.SET_VALUE_MAX_CHARS, c.SET_MAX_DEPTH) == (100, 10_000, 100)


# --- Accepted values ----------------------------------------------------------------------

ACCEPTED = [
    # AC-F44-03 rows
    ("1", 1),
    ("-2.5", -2.5),
    ("+3", 3),
    ("0x10", 16),
    ("1_000", 1000),
    ("  7  ", 7),
    ("True", True),
    ("False", False),
    ("None", None),
    ('"Hana"', "Hana"),
    ("'Hana'", "Hana"),
    ('"a" "b"', "ab"),
    ('"日本語 😀"', "日本語 😀"),
    ('[1, {"a": None}]', [1, {"a": None}]),
    ("[]", []),
    ("{}", {}),
    (nested(100), nested_value(100)),
    # more numbers
    ("0", 0),
    ("-0x10", -16),
    ("0b101", 5),
    ("0o17", 15),
    ("1.5e3", 1500.0),
    ("-1e308", -1e308),
    ("+0.5", 0.5),
    ("1" * 4300, int("1" * 4300)),
    # more text
    ('""', ""),
    ("'it''s'", "its"),
    (r'"a\nb"', "a\nb"),
    (r'"C:\q"', "C:\\q"),
    ('"""three"""', "three"),
    ('"a = b"', "a = b"),
    ('"' + "a" * 9_998 + '"', "a" * 9_998),
    # more containers
    ('{"a": [1, "b"], "c": {"d": True}}', {"a": [1, "b"], "c": {"d": True}}),
    ('[1, 2, 3,]', [1, 2, 3]),
    ("[[], {}]", [[], {}]),
    ('{"k": ' + nested(99) + "}", {"k": nested_value(99)}),
    ("\t7\n", 7),
    ("1  # a comment", 1),
]


@pytest.mark.parametrize(("text", "expected"), ACCEPTED,
                         ids=[repr(t[:20]) for t, _ in ACCEPTED])
def test_accepted(text, expected):
    value = parse_literal(text)
    assert same(value, expected)
    assert plain(value)


def test_accepted_values_are_fresh():
    """Each parse builds new objects; nothing is shared between two parses."""
    first, second = parse_literal("[1, [2]]"), parse_literal("[1, [2]]")
    assert first == second and first is not second and first[1] is not second[1]


# --- Refused values -----------------------------------------------------------------------

QUOTE_ROWS = [
    # AC-F44-03 rows
    "Hana", "x", "nan", "inf", "Hana Sato",
    # a name anywhere, and unquoted words that don't parse
    "[1, Hana]", '{"a": Hana}', "{a: 1}", "Hana's book", "  sayo  ", "日本",
    "sayo_points=1", 'f"Hana', "yield",   # a syntax error starting with a letter
]

GENERAL_ROWS = [
    # AC-F44-03 rows
    "__import__('vn_canary')", "1+1", 'b"x"', "{1, 2}", "(1, 2)", "1e999", "-True", "--1",
    "~1", "1j", "...", 'f"x"', '{1: "a"}', "{**d}", "[i for i in y]", "lambda: 0",
    "1 if True else 2", '"Hana', "",
    nested(101), '"' + "a" * 9_999 + '"', "1" * 4301,
    # code-like input: calls, attributes, subscripts, operators, comprehensions
    "__import__('os').system('echo')", "open('x')", "x.y", "().__class__", "a[0]",
    "'a' + 'b'", "'ab' * 3", "1 < 2", "not True", "True and False", "-x", "-(1+1)",
    "{i: i for i in y}", "(i for i in y)", "{i for i in y}", "[*x]", "{'a': 1, **d}",
    "(x := 1)", "f'{x}'", "rf'x'", "await x", "set()", "dict(a=1)",
    # wrong constants and signs
    "-1e999", "+1e999", "-None", "+True", "-'a'", "-1j", "-...", "--1.5", "+-1",
    "{None: 1}", "{True: 1}", "{(1, 2): 1}", "{b'a': 1}", "()", "1,", "[1, 2,,]",
    # huge: a long hex literal beyond 4,300 decimal digits, deep nesting the parser refuses,
    # sign chains the parser can't hold, and 10,001 characters that would otherwise parse
    "0x" + "f" * 3600, nested(300), "-" * 9_000 + "1", "1" + " " * 10_000,
    "[" + "1," * 5_000 + "]",
    # broken text
    "   ", "1abc", "[1, 2", "{'a' 1}", "\x00", '"a\x00"', "=1", "'''",
]


@pytest.mark.parametrize("text", QUOTE_ROWS)
def test_put_text_in_quotes(text):
    with pytest.raises(StartValueError) as info:
        parse_literal(text)
    assert info.value.reason == Q
    assert info.value.message == f"--set: {Q}."
    assert info.value.argument is None and info.value.index is None


@pytest.mark.parametrize("text", GENERAL_ROWS, ids=[repr(t[:20]) for t in GENERAL_ROWS])
def test_general_message(text):
    with pytest.raises(StartValueError) as info:
        parse_literal(text)
    assert info.value.reason == G


def test_length_and_depth_limits_are_exact():
    assert parse_literal("1" + " " * 9_999) == 1                     # 10,000 characters
    assert len('"' + "a" * 9_998 + '"') == 10_000
    assert len('"' + "a" * 9_999 + '"') == 10_001
    assert parse_literal(nested(100)) == nested_value(100)
    with pytest.raises(StartValueError):
        parse_literal(nested(101))
    with pytest.raises(StartValueError):
        parse_literal('{"a": ' + nested(100) + "}")                 # 101 with the dict


def test_error_is_a_value_error():
    with pytest.raises(ValueError, match="put text in quotes"):
        parse_literal("Hana")


def test_invalid_escape_is_kept_without_a_warning(recwarn):
    assert parse_literal(r'"\q"') == "\\q"
    assert not [w for w in recwarn if issubclass(w.category, SyntaxWarning)]


# --- parse_set and its usage messages -----------------------------------------------------

SET_OK = [
    ("sayo_points=1", ("sayo_points", 1)),
    ("sayo_points = 1", ("sayo_points", 1)),
    ("hana_name='Hana'", ("hana_name", "Hana")),
    ("seen=[1, {'a': None}]", ("seen", [1, {"a": None}])),
    ("  x  =  -2.5  ", ("x", -2.5)),
    ("note = 'a=b'", ("note", "a=b")),
    ("_private=None", ("_private", None)),
    ("名前='Hana'", ("名前", "Hana")),
]


@pytest.mark.parametrize(("text", "expected"), SET_OK)
def test_parse_set_accepts(text, expected):
    assert parse_set(text) == expected


SET_MESSAGES = [
    # AC-F44-04 rows (exact where the AC gives the whole text)
    ("sayo_points=Hana", '--set "sayo_points=Hana": put text in quotes.'),
    ("sayo_points=1+1", f'--set "sayo_points=1+1": {G}.'),
    ("sayo_points=", f'--set "sayo_points=": {G}.'),
    ("sayo_points= ", f'--set "sayo_points= ": {G}.'),
    # drafted texts (G5)
    ("sayo_points", '--set "sayo_points": write it as name=value, like sayo_points=1.'),
    ("=1", '--set "=1": write it as name=value, like sayo_points=1.'),
    ("  = 1", '--set "  = 1": write it as name=value, like sayo_points=1.'),
    ("1x=1", '--set "1x=1": the name must start with a letter or _ and use only '
             'letters, digits, and _.'),
    ("sayo points=1", '--set "sayo points=1": the name must start with a letter or _ and '
                      'use only letters, digits, and _.'),
    ("class=1", "--set \"class=1\": `class` is a Python keyword and can't be a name."),
    ("True=1", "--set \"True=1\": `True` is a Python keyword and can't be a name."),
    # a value with its own "=" splits at the first one
    ("a=b=c", '--set "a=b=c": put text in quotes.'),
    ("x == 1", f'--set "x == 1": {G}.'),
]


@pytest.mark.parametrize(("text", "message"), SET_MESSAGES)
def test_parse_set_messages(text, message):
    with pytest.raises(StartValueError) as info:
        parse_set(text)
    assert info.value.message == message
    assert str(info.value) == message
    assert info.value.argument == text
    assert message == f'--set "{text}": {info.value.reason}.'


def test_long_argument_is_echoed_short():
    """AC-F44-04 last row: the echoed argument is cut by echo() (AC-F01-166)."""
    argument = 's="' + "a" * 9_999 + '"'
    with pytest.raises(StartValueError) as info:
        parse_set(argument)
    message = info.value.message
    assert info.value.reason == G and "the value must be a number" in message
    assert message.startswith('--set "s="')
    echoed = message[len('--set "'):message.index('": the value')]
    assert len(echoed) == c.ECHO_MAX_CHARS and echoed.endswith("…")


def test_control_characters_are_escaped_in_the_message():
    with pytest.raises(StartValueError) as info:
        parse_set("x=\x1b[31m")
    assert "\x1b" not in info.value.message


# --- parse_set_list (I-5) -----------------------------------------------------------------

def test_list_all_good_keeps_order():
    values, problems = parse_set_list(["b = 1", "a='x'", "c=[1]"])
    assert problems == ()
    assert values == (("b", 1), ("a", "x"), ("c", [1]))
    assert parse_set_list([]) == ((), ())


def test_list_reports_every_problem_in_order():
    """AC-F44-27's box without its comment line (the editor drops comments and blanks)."""
    arguments = ["sayo_points = Hana", "seen = 1+1", "sayo_points = 2"]
    values, problems = parse_set_list(arguments)
    assert values == ()
    assert [(p.index, p.reason) for p in problems] == [
        (0, Q),
        (1, G),
        (2, "`sayo_points` is set twice"),
    ]
    assert [p.argument for p in problems] == arguments
    assert problems[2].message == '--set "sayo_points = 2": `sayo_points` is set twice.'


def test_list_duplicates():
    values, problems = parse_set_list(["x=1", "y=2", "x = 2", "x=3", "y=2"])
    assert values == ()
    assert [(p.index, p.reason) for p in problems] == [
        (2, "`x` is set twice"), (3, "`x` is set twice"), (4, "`y` is set twice"),
    ]


def test_list_bad_value_and_bad_name_are_one_problem_each():
    _, problems = parse_set_list(["1x=Hana", "x=Hana", "x=Hana", "class=1"])
    assert [(p.index, p.reason) for p in problems] == [
        (0, sv.BAD_NAME), (1, Q), (2, Q), (3, sv.keyword_name("class")),
    ]


def test_list_limit_is_100():
    hundred = [f"v{i}=1" for i in range(100)]
    values, problems = parse_set_list(hundred)
    assert problems == () and len(values) == 100

    values, problems = parse_set_list(hundred + ["v100=1"])
    assert values == ()
    assert len(problems) == 1
    (problem,) = problems
    assert problem.index is None and problem.argument is None
    assert "100" in problem.message
    assert problem.reason == "at most 100 start values can be set, and there are 101"
    assert problem.message == "--set: at most 100 start values can be set, and there are 101."


def test_list_limit_comes_after_line_problems():
    arguments = [f"v{i}=1" for i in range(101)] + ["v0=2"]
    _, problems = parse_set_list(arguments)
    assert [(p.index, p.reason) for p in problems] == [
        (101, "`v0` is set twice"),
        (None, "at most 100 start values can be set, and there are 102"),
    ]


def test_list_accepts_any_sequence():
    assert parse_set_list(("a=1",)) == ((("a", 1),), ())


# --- StartOptions -------------------------------------------------------------------------

def test_start_options():
    options = StartOptions()
    assert options.label is None and options.values == ()
    options = StartOptions(label="club_poem", values=(("sayo_points", 1),))
    assert type(options.label) is str
    with pytest.raises(dataclasses.FrozenInstanceError):
        options.label = "x"                                       # type: ignore[misc]
    assert options == StartOptions("club_poem", (("sayo_points", 1),))


# --- The module stays small and safe ------------------------------------------------------

def test_imports_only_stdlib_and_core():
    tree = ast.parse((ROOT / "engine/core/startvalues.py").read_text(encoding="utf-8"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module)
    engine = {m for m in modules if m.split(".")[0] == "engine"}
    assert engine <= {"engine.core.constants", "engine.core.redact"}
    assert all(m.split(".")[0] in sys.stdlib_module_names for m in modules - engine)


# Run in a child: audit hooks can't be removed, and the canary must not be importable here.
_CHILD = textwrap.dedent("""
    import json, os, sys
    sys.path.insert(0, sys.argv[1])          # the folder holding vn_canary
    before = sorted(os.listdir("."))
    import engine.core.startvalues as sv
    after = sorted(os.listdir("."))
    loaded = sorted(m for m in sys.modules if m == "engine" or m.startswith("engine."))
    inputs = json.loads(open(sys.argv[2], encoding="utf-8").read())

    events = []
    recording = False

    def hook(event, args):
        if recording and event in ("exec", "import", "compile", "subprocess.Popen",
                                   "os.system", "open"):
            if event == "compile":      # ast.parse hands compile() the UTF-8 bytes
                source = args[0]
                if isinstance(source, bytes):
                    source = source.decode("utf-8", "surrogatepass")
                events.append([event, source if isinstance(source, str) else None,
                               str(args[1])])
            else:
                events.append([event, str(args[0]) if args else None, None])

    sys.addaudithook(hook)
    refused = 0
    recording = True
    for text in inputs:
        for call, arg in ((sv.parse_literal, text), (sv.parse_set, "x=" + text)):
            try:
                call(arg)
            except sv.StartValueError:
                refused += 1
    recording = False
    canary_before = os.path.exists("canary.txt")
    import vn_canary                          # proves the canary works
    canary_after = os.path.exists("canary.txt")
    print(json.dumps({"before": before, "after": after, "loaded": loaded,
                      "pygame": "pygame" in sys.modules, "events": events,
                      "refused": refused, "canary": [canary_before, canary_after]}))
""")

_CANARY = 'open("canary.txt", "w").close()\n'

CODE_LIKE = [
    "__import__('vn_canary')", "exec('import vn_canary')", "eval(\"__import__('vn_canary')\")",
    "compile('1', 'x', 'eval')", "[__import__('vn_canary')]", "{'a': __import__('vn_canary')}",
    "(lambda: __import__('vn_canary'))()", "[__import__('vn_canary') for _ in [1]]",
    "f\"{__import__('vn_canary')}\"", "vn_canary", "import vn_canary",
    "__builtins__.__import__('vn_canary')", "().__class__.__base__.__subclasses__()",
]


def test_refused_input_never_runs_code(tmp_path):
    """AC-F44-03: with vn_canary importable and an audit hook installed, no refused input
    creates the canary file or raises an exec/import event; compile events come only from
    ast.parse (filename '<unknown>', source = the stripped input). Also: importing the module
    loads only engine.core modules, never pygame, and touches no file."""
    canary_dir = tmp_path / "lib"
    (canary_dir / "vn_canary").mkdir(parents=True)
    (canary_dir / "vn_canary" / "__init__.py").write_text(_CANARY, encoding="utf-8")
    inputs = CODE_LIKE + [row for row in GENERAL_ROWS + QUOTE_ROWS if len(row) < 2_000]
    data = tmp_path / "inputs.json"
    data.write_text(json.dumps(inputs), encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()

    result = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
                                     f"exec({_CHILD!r})", str(canary_dir), str(data)],
        cwd=work, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])

    assert report["before"] == report["after"] == []
    assert report["loaded"] == ["engine", "engine.core", "engine.core.constants",
                                "engine.core.redact", "engine.core.startvalues"]
    assert report["pygame"] is False
    assert report["refused"] == 2 * len(inputs)
    assert report["canary"] == [False, True]
    kinds = {event for event, _, _ in report["events"]}
    assert kinds <= {"compile"}, [e for e in report["events"] if e[0] != "compile"]
    sources = {text.strip() for text in inputs}
    for _, source, filename in report["events"]:
        assert filename == "<unknown>"
        assert source in sources
