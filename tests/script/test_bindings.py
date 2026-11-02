"""F03 step 11: what a ``$`` line or condition may set (``engine/script/bindings.py``; F03
``04-technical.md`` §6.2; SR-F03-09, SR-F03-21, SR-F03-25).

AC-F03-23 and AC-F03-24's message rows live in ``tests/fixtures/F02/messages/cases.toml``
(``feature = "F03"``, one catalogue) and feed the golden file; here they run once more as the
ACs. AC-F03-25 compares the prefilter with the forced parse over 25,000 generated pieces.
The rest are the edge cases: scope rules, source order, E88's forms, E87's value, W05's
place, ordering with F02's errors, and the yields.
"""

import ast
import random

import pytest

from engine.script import bindings
from engine.script.bindings import (
    KIND_CONDITION,
    KIND_EXEC,
    Defines,
    Piece,
    check_piece,
    e88_args,
    needs_parse,
    scan,
)
from engine.script.loader import LoadResult, load_story
from engine.script.messages import format_message
from engine.script.nodes import PyCode, ScriptFile
from engine.script.words import ENGINE_NAMES
from tests.script import message_cases
from tests.script.helpers import template_r

MAIN = "script/main.vns"
FILE = ScriptFile(MAIN, "main.vns", 0)


def load(game, text: str, **files: str) -> LoadResult:
    return load_story(game({"main.vns": text, **files}))


def report(result: LoadResult) -> list[tuple[str, str | None, int | None]]:
    return [(e.code, e.file, e.line) for e in result.errors]


def piece(source: str, kind: str = KIND_EXEC, line: int = 8) -> Piece:
    mode = "exec" if kind == KIND_EXEC else "eval"
    code = compile(source, "<script/main.vns>", mode, dont_inherit=True)
    return Piece(FILE, line, PyCode(source=source, line=line, column=5, mode=mode, code=code),
                 kind)


DEFINES = Defines(places={name: [(FILE, i)] for i, name in
                          enumerate(("hana", "daichi", "fortunes"), 1)}, nodes={})
WATCHED = frozenset(DEFINES.places) | ENGINE_NAMES


def finding(source: str, kind: str = KIND_EXEC, *, prefilter: bool = False):
    """(code, name or args, line) of the piece's error, or None."""
    error, _ = check_piece(piece(source, kind), DEFINES, WATCHED, prefilter=prefilter)
    if error is None:
        return None
    return error.code, error.args[0], error.line


# --- AC-F03-23, AC-F03-24 ----------------------------------------------------------------------

AC23 = [c for c in message_cases.load_cases() if c.ac == "AC-F03-23"]
AC24 = [c for c in message_cases.load_cases() if c.ac == "AC-F03-24"]


def test_ac23_ac24_have_every_row():
    codes = [c.code for c in AC23]
    assert codes.count("E87") == 8 and codes.count("E88") == 8
    assert codes.count("E62") == 4 and codes.count("E63") == 2 and codes.count("-") == 6
    assert [c.code for c in AC24] == ["W05", "W05", "-"]
    assert all(c.feature == "F03" and c.time == "load" and c.needs == "load"
               for c in AC23 + AC24)


@pytest.mark.parametrize("case", AC23 + AC24, ids=lambda case: case.id)
def test_ac23_ac24_rows(case):
    message_cases.check_case(case, message_cases.run_case(case))


def test_ac24_exactly_one_w05_and_the_game_still_runs(game):
    from engine.runtime.commands import Say, StoryEnded
    from engine.runtime.headless import run_headless

    result = load(game, template_r(S="$ deck = [1, 2]⏎[4]$ dice.shuffle(deck)"))
    assert result.errors == () and result.program is not None
    assert [(w.code, w.file, w.line) for w in result.warnings] == [("W05", MAIN, 9)]
    commands = run_headless(result.program, seed=42)
    assert [c.text for c in commands if type(c) is Say] == ["Start.", "End."]
    assert type(commands[-1]) is StoryEnded


def test_02_texts():
    # 02 §5.1's own examples.
    assert format_message("E87", ("hana", ("script/main.vns", 4), None, True)) == (
        '"hana" is set by define in script/main.vns, line 4, so the story can\'t change it. '
        'To change the name the player sees, use Character(name_from="hana_name") and set '
        "hana_name.")
    assert format_message("E87", ("wish_cost", ("script/main.vns", 6), "300")) == (
        '"wish_cost" is set by define in script/main.vns, line 6, so the story can\'t change '
        "it. If the story changes it, write default wish_cost = 300 instead of define.")
    assert format_message("E88", ("c", "a.b")).endswith(
        'Add define c = module("a.b") at the top level instead.')
    assert format_message("E88", ("a", "a", "a.b")).endswith(
        'Add define a = module("a") at the top level instead. Then write a.b.')
    assert format_message("W05", ("deck",)) == (
        "dice.shuffle gives back a shuffled copy and leaves deck unchanged. Write $ deck = "
        "dice.shuffle(deck).")


# --- AC-F03-25: the prefilter misses nothing ------------------------------------------------

DEFINE_NAMES = ("hana", "daichi", "fortunes")
UNDERSCORE = ("_x", "_seen", "__y")
PLAIN = ("trust", "deck", "x", "y", "k", "path", "math")


class Grammar:
    """Random pieces over every SR-F03-09 binding form, nested lambdas, comprehensions,
    attribute and item targets, imports, and ``dice.shuffle`` calls."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.engine = sorted(ENGINE_NAMES)

    def name(self) -> str:
        # Plain names half the time, so many pieces pass the prefilter untouched.
        pool = self.rng.choice((DEFINE_NAMES, self.engine, UNDERSCORE, PLAIN, PLAIN, PLAIN))
        return self.rng.choice(pool)

    def expr(self, depth: int = 0) -> str:
        r = self.rng
        n = self.name
        if depth > 2:
            return r.choice(("1", n(), '"a"', "[1, 2]"))
        e = lambda: self.expr(depth + 1)  # noqa: E731
        return r.choice((
            lambda: "1", n, lambda: f"{n()}.{n()}", lambda: f"{n()}[{e()}]",
            lambda: f"({n()} := {e()})", lambda: f"(lambda {n()}, {n()}={e()}: {e()})",
            lambda: f"(lambda: ({n()} := {e()}))",
            lambda: f"[{e()} for {n()} in {e()} if {e()}]",
            lambda: f"{{{n()}: {e()} for {n()}, {n()} in {e()}}}",
            lambda: f"({e()} for {n()} in range(2))",
            lambda: f"[({n()} := {n()}) for {n()} in range(2)]",
            lambda: f"dice.shuffle({e()})", lambda: f"{n()}({e()}, {n()}={e()})",
            lambda: f"{e()} + {e()}", lambda: f"not {e()}",
        ))()

    def target(self) -> str:
        r = self.rng
        n = self.name
        return r.choice((n, n, lambda: f"{n()}.{n()}", lambda: f"{n()}[{self.expr(2)}]",
                         lambda: f"({n()}, {n()})", lambda: f"[{n()}, *{n()}]"))()

    def body(self, depth: int, indent: str, levels: int = 1) -> str:
        count = self.rng.randint(1, 2)
        inner = indent + "    " * levels
        return "\n".join(inner + self.stmt(depth + 1, inner) for _ in range(count))

    def stmt(self, depth: int = 0, indent: str = "") -> str:
        r = self.rng
        n, e, t = self.name, self.expr, self.target
        simple = [
            lambda: f"{t()} = {e()}", lambda: f"{t()} = {t()} = {e()}",
            lambda: f"{r.choice((n, lambda: f'{n()}.{n()}', lambda: f'{n()}[0]'))()} += {e()}",
            lambda: f"{n()}: int = {e()}", lambda: f"{n()}: int",
            lambda: f"{n()}.{n()}: int = {e()}", lambda: f"del {t()}", lambda: f"del {n()}, {n()}",
            lambda: f"import {r.choice(('math', 'os.path', 'os'))}",
            lambda: f"import os.path as {n()}", lambda: f"from os import {n()}",
            lambda: f"from os import path as {n()}", lambda: f"dice.shuffle({e()})",
            lambda: f"{e()}", lambda: f"type {n()} = list[{n()}]",
            lambda: f"global {n()}", lambda: "pass",
        ]
        if depth >= 2:
            return r.choice(simple)()
        b = lambda: self.body(depth, indent)  # noqa: E731
        case = lambda: self.body(depth, indent, 2)  # noqa: E731
        compound = [
            lambda: f"for {t()} in {e()}:\n{b()}", lambda: f"with open('x') as {t()}:\n{b()}",
            lambda: f"def {n()}({n()}={e()}, *, {n()}={e()}) -> {e()}:\n{b()}",
            lambda: f"@{n()}({e()})\n{indent}def {n()}():\n{b()}",
            lambda: f"class {n()}({e()}, metaclass={e()}):\n{b()}",
            lambda: f"if {e()}:\n{b()}\n{indent}else:\n{b()}",
            lambda: f"while {e()}:\n{b()}",
            lambda: f"try:\n{b()}\n{indent}except Exception as {n()}:\n{b()}",
            lambda: f"match {e()}:\n{indent}    case [{n()}, *{n()}]:\n{case()}\n"
                    f"{indent}    case {{'k': {n()}, **{n()}}}:\n{case()}",
        ]
        return r.choice(simple + compound)()

    def exec_piece(self) -> str:
        return "\n".join(self.stmt() for _ in range(self.rng.randint(1, 3)))

    def condition(self) -> str:
        return self.expr()


def _valid(make, kind: str) -> Piece:
    """The first generated piece that compiles (the load only checks pieces that do)."""
    while True:
        try:
            return piece(make(), kind)
        except SyntaxError:
            continue


def _result(p: Piece, prefilter: bool):
    error, warning = check_piece(p, DEFINES, WATCHED, prefilter=prefilter)
    return ((error.code, error.args, error.line, error.stmt) if error else None,
            (warning.code, warning.message, warning.file, warning.line) if warning else None)


@pytest.mark.parametrize("count, least_skipped", [
    (1_000, 100),                                   # every outcome; under 1 s
    pytest.param(20_000, 1_000, marks=pytest.mark.slow),
])
def test_ac25_prefilter_matches_the_forced_parse(count, least_skipped):
    rng = random.Random(3)
    grammar = Grammar(rng)
    pieces = [_valid(grammar.exec_piece, KIND_EXEC) for _ in range(count)]
    pieces += [_valid(grammar.condition, KIND_CONDITION) for _ in range(count // 4)]
    codes: dict[str | None, int] = {}
    skipped = 0
    for p in pieces:
        fast, slow = _result(p, True), _result(p, False)
        assert fast == slow, p.py.source
        skipped += not needs_parse(p.py, WATCHED)
        key = fast[0][0] if fast[0] else None
        codes[key] = codes.get(key, 0) + 1
        if fast[1]:
            codes["W05"] = codes.get("W05", 0) + 1
    # The grammar reaches every outcome, and the prefilter does skip pieces.
    assert {"E87", "E88", "E62", "E63", "W05", None} <= set(codes), codes
    assert skipped > least_skipped, skipped


def test_ac25_runs_through_check_all(game):
    # check_all with and without the prefilter on a loaded story gives the same output.
    text = template_r(S="$ x = [hana for hana in range(3)]⏎[4]$ fortunes, y = 1, 2⏎[4]"
                        "$ dice.shuffle(x)⏎[4]if (_k := 1):⏎[8]\"A.\"⏎[4]$ trust = 1")
    from engine.script.loader import StoryLoader
    loader = StoryLoader(game({"main.vns": text}))
    while not loader.step(1.0):
        pass
    result = loader.result
    assert [e.code for e in result.errors] == ["E87", "E63"]
    collected = {"hana": [(FILE, 1)], "daichi": [(FILE, 2)], "fortunes": [(FILE, 3)]}
    fast = bindings.check_all(loader.nodes, collected)
    slow = bindings.check_all(loader.nodes, collected, prefilter=False)
    assert [(d.code, d.line) for d in fast.errors] == [(d.code, d.line) for d in slow.errors] \
        == [("E87", 9), ("E63", 11)]
    assert [w.line for w in fast.warnings] == [w.line for w in slow.warnings] == [10]


# --- Scope and order (unit) ------------------------------------------------------------------

@pytest.mark.parametrize("source, expected", [
    # Bound at the top level, in every SR-F03-09 form.
    ("hana = 1", ("E87", "hana", 8)),
    ("x = fortunes = 1", ("E87", "fortunes", 8)),
    ("(a, [b, *fortunes]) = 1, [2, 3]", ("E87", "fortunes", 8)),
    ("fortunes -= 1", ("E87", "fortunes", 8)),
    ("fortunes: int = 1", ("E87", "fortunes", 8)),
    ("y = (fortunes := 1)", ("E87", "fortunes", 8)),
    ("del x, fortunes", ("E87", "fortunes", 8)),
    ("for i, fortunes in []: pass", ("E87", "fortunes", 8)),
    ("with open('a') as x, open('b') as fortunes: pass", ("E87", "fortunes", 8)),
    ("def fortunes(): pass", ("E87", "fortunes", 8)),
    ("class fortunes: pass", ("E87", "fortunes", 8)),
    ("if True:\n    for fortunes in []: pass", ("E87", "fortunes", 9)),
    # The parts of a scope that run in the piece's scope.
    ("def f(a=(fortunes := 1)): pass", ("E87", "fortunes", 8)),
    ("def f(*, a=(fortunes := 1)): pass", ("E87", "fortunes", 8)),
    ("def f(a: (fortunes := int)): pass", ("E87", "fortunes", 8)),
    ("def f() -> (fortunes := int): pass", ("E87", "fortunes", 8)),
    ("@(fortunes := print)\ndef f(): pass", ("E87", "fortunes", 8)),
    ("class C((fortunes := object)): pass", ("E87", "fortunes", 8)),
    ("class C(metaclass=(fortunes := type)): pass", ("E87", "fortunes", 8)),
    ("f = lambda a=(fortunes := 1): a", ("E87", "fortunes", 8)),
    # The same scope binds these too (see bindings.py's docstring).
    ("try: pass\nexcept Exception as fortunes: pass", ("E87", "fortunes", 9)),
    ("match 1:\n    case fortunes: pass", ("E87", "fortunes", 9)),
    ("match [1]:\n    case [1, *fortunes]: pass", ("E87", "fortunes", 9)),
    ("match {}:\n    case {**fortunes}: pass", ("E87", "fortunes", 9)),
    ("type fortunes = int", ("E87", "fortunes", 8)),
    # Source order picks the first; rules don't outrank it.
    ("_a = 1; hana = 2", ("E63", "_a", 8)),
    ("hana = 2; _a = 1", ("E87", "hana", 8)),
    ("dice, hana = 1, 2", ("E62", "dice", 8)),
    ("x = 1\nfortunes = 2\ndice = 3", ("E87", "fortunes", 9)),
    ("hana = 1; import math", ("E88", "math", 8)),
    ("x = 1\nimport math", ("E88", "math", 9)),
    ("def f():\n    import math", ("E88", "math", 9)),
    ("class C:\n    from os import path", ("E88", "os", 9)),
])
def test_bindings_that_count(source, expected):
    assert finding(source) == expected
    assert finding(source, prefilter=True) == expected


@pytest.mark.parametrize("source", [
    "fortunes[0] = 1", "hana.name = 'x'", "persistent.seen = True", "del persistent.seen",
    "fortunes: list", "x = [hana for hana in range(3)]", "x = {hana: 1 for hana in 'ab'}",
    "x = (hana for hana in 'ab')", "x = [(hana := k) for k in range(2)]",
    "f = lambda hana: hana", "f = lambda: (hana := 1)",
    "def f(hana):\n    fortunes = hana\n    del daichi", "def f():\n    global hana\n    hana = 1",
    "class C:\n    hana = 1\n    def dice(self): pass", "type T[hana] = list[hana]",
    "globals()['hana'] = 1", "exec('hana = 1')", "setattr(x, 'hana', 1)", "x = hana",
    "x = _y", "important = 1", "x = 'import math'",
])
def test_bindings_that_dont_count(source):
    assert finding(source) is None
    assert finding(source, prefilter=True) is None


@pytest.mark.parametrize("source, expected", [
    ("(fortunes := 1)", ("E87", "fortunes", 8)),
    ("x and (dice := 2)", ("E62", "dice", 8)),
    ("(_seen := True)", ("E63", "_seen", 8)),
    ("[(hana := k) for k in range(2)]", None),
    ("(lambda: (hana := 1))()", None),
    ("hana", None),
])
def test_conditions(source, expected):
    assert finding(source, KIND_CONDITION) == expected


def test_one_error_per_piece_and_per_branch(game):
    text = template_r(S='if (hana := 1):⏎[8]"A."⏎[4]elif (dice := 2):⏎[8]"B."⏎[4]'
                        "else:⏎[8]$ _x = 1; fortunes = 2")
    result = load(game, text)
    assert report(result) == [("E87", MAIN, 8), ("E62", MAIN, 10), ("E63", MAIN, 13)]


def test_error_line_inside_a_continued_piece(game):
    result = load(game, template_r(S="$ x = (1,⏎[8]2)⏎[4]$ y = (1,⏎[8]fortunes := 2)"))
    assert report(result) == [("E87", MAIN, 11)]


# --- E88's forms (G10) ------------------------------------------------------------------------

@pytest.mark.parametrize("source, args", [
    ("import math", ("math", "math", None)),
    ("import math, os", ("math", "math", None)),
    ("import os.path as p", ("p", "os.path", None)),
    ("import os.path", ("path", "os.path", "path instead of os.path")),
    ("from os import path", ("os", "os", "os.path")),
    ("from os import path as p, sep", ("os", "os", "os.path")),
    ("from os.path import join", ("path", "os.path", "path.join")),
    ("from math import *", ("math", "math", None)),
    ("from . import x", ("math", "math", None)),
    ("from .. import x", ("math", "math", None)),
])
def test_e88_args(source, args):
    tree = ast.parse(source)
    assert e88_args(tree.body[0]) == args


def test_e88_names_the_first_import_in_source_order():
    found = scan(ast.parse("def f():\n    import os\nimport math"))
    assert e88_args(found.first_import()) == ("os", "os", None)


# --- E87's value and form ---------------------------------------------------------------------

@pytest.mark.parametrize("define, shown", [
    ('define wish_cost = 300', 'write default wish_cost = 300 instead'),
    ('define wish_cost = 300  # yen', 'write default wish_cost = 300 instead'),
    ('define wish_cost = "' + "x" * 38 + '"', 'write default wish_cost = "' + "x" * 38 + '" '),
    ('define wish_cost = "' + "x" * 39 + '"', "write default wish_cost = … instead"),
    ("define wish_cost = [1,⏎[4]2]", "write default wish_cost = … instead"),
    ('define wish_cost = Character("A") if True else 1', "write default wish_cost = Character"),
])
def test_e87_value(game, define, shown):
    result = load(game, template_r(S="$ wish_cost = 1", T=define))
    (error,) = result.errors
    assert (error.code, error.line) == ("E87", 8)
    assert shown in error.message


def test_e87_character_form_and_a_define_in_another_file(game):
    result = load(game, template_r(S="$ guide = 1", T='include "people.vns"'),
                  **{"people.vns": 'define guide = Character("Guide")'})
    (error,) = result.errors
    assert error.message == (
        '"guide" is set by define in script/people.vns, line 1, so the story can\'t change it. '
        'To change the name the player sees, use Character(name_from="guide_name") and set '
        "guide_name.")


def test_e87_names_the_first_define_when_there_are_two(game):
    result = load(game, template_r(S="$ fortunes = []", T="define fortunes = 1"))
    assert report(result) == [("E87", MAIN, 8), ("E47", MAIN, 11)]
    assert "line 3" in result.errors[0].message


def test_e87_for_a_define_with_its_own_error(game):
    result = load(game, template_r(S="$ wish = 1", T="define wish ="))
    assert report(result) == [("E87", MAIN, 8), ("E49", MAIN, 11)]
    assert "write default wish = … instead of define." in result.errors[0].message


# --- W05 --------------------------------------------------------------------------------------

@pytest.mark.parametrize("source, name, line", [
    ("dice.shuffle(deck)", "deck", 8),
    ("x = 1\ndice.shuffle(x)", "x", 9),
    ("dice.shuffle(deck); dice.shuffle(other)", "deck", 8),
    ("if x:\n    dice.shuffle(deck)", "deck", 9),
    ("dice.shuffle()", None, 8),
    ("dice.shuffle(*decks)", None, 8),
    ("dice.shuffle(deck, 1)", None, 8),
    ("dice.shuffle(deck[0])", None, 8),
])
def test_w05(source, name, line):
    _, warning = check_piece(piece(source), DEFINES, WATCHED)
    assert (warning.code, warning.file, warning.line) == ("W05", MAIN, line)
    assert warning.message == format_message("W05", (name,))


@pytest.mark.parametrize("source, kind", [
    ("deck = dice.shuffle(deck)", KIND_EXEC), ("print(dice.shuffle(deck))", KIND_EXEC),
    ("def f():\n    dice.shuffle(deck)", KIND_EXEC), ("f = lambda: dice.shuffle(deck)", KIND_EXEC),
    ("random.shuffle(deck)", KIND_EXEC), ("dice.roll(1, 6)", KIND_EXEC),
    ("dice.shuffle(deck)", KIND_CONDITION),
])
def test_no_w05(source, kind):
    assert check_piece(piece(source, kind), DEFINES, WATCHED) == (None, None)


def test_w05_comes_with_an_error_of_the_same_piece(game):
    result = load(game, template_r(S="$ dice.shuffle(fortunes); fortunes = 1"))
    assert report(result) == [("E87", MAIN, 8)]
    assert [(w.code, w.line) for w in result.warnings] == [("W05", 8)]


# --- In the load ------------------------------------------------------------------------------

def test_errors_sort_with_f02s(game):
    text = template_r(S="$ hana = 1", T='label start:⏎[4]"Again."⏎label later:⏎[4]$ _x = 1')
    result = load(game, text)
    assert report(result) == [("E87", MAIN, 8), ("E25", MAIN, 11), ("E63", MAIN, 14)]


def test_runs_when_a_file_couldnt_be_read(game):
    text = template_r(S="$ dice = 1", T='include "bad.vns"')
    result = load_story(game({"main.vns": text, "bad.vns": b"\xff\xfe\x00"}))
    assert result.checks_skipped
    assert ("E62", MAIN, 8) in report(result)


def test_pieces_with_their_own_error_are_skipped(game):
    result = load(game, template_r(S="$ hana = = 1"))
    assert [e.code for e in result.errors] == ["E80"]


def _yields(source: str, count: int) -> tuple[int, int]:
    errors: list = []
    job = bindings.iter_check_all([piece(source)] * count, DEFINES, errors.append)
    yields = 0
    while True:
        try:
            next(job)
        except StopIteration:
            return yields, len(errors)
        yields += 1


def test_iter_check_all_yields_every_2000_pieces_and_sooner_when_parsing():
    assert _yields("x = 1", 4_001) == (2, 0)                      # skipped by the prefilter
    assert bindings.PARSE_WEIGHT == 8
    assert _yields("hana = 1", 4_001) == (16, 4_001)              # parsed: every 250

