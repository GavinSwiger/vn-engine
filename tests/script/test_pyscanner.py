"""AC-F02-33 (TR-F02-03): the Python span scanner agrees with ``tokenize`` on the extent of
a piece of Python and on the last top-level ``:`` of a condition."""

import io
import random
import tokenize

import pytest

from engine.script.lexer import PyScanner
from engine.script.pycheck import ROLE_CONDITION, ROLE_EXEC, ROLE_VALUE, compile_piece
from tests.script.helpers import FIXTURES, parse_text, template

SPANS = FIXTURES / "python_spans.txt"
SEED = 20261101


def _cases() -> list[tuple[str, list[str]]]:
    cases = []
    for raw in SPANS.read_text(encoding="utf-8").splitlines():
        tail, snippet = raw.split("\t", 1)
        cases.append((tail, snippet.split("⏎")))
    return cases


def scanner_view(lines: list[str]) -> tuple[tuple[int, int], tuple[int, int] | None]:
    """(extent end, last top-level colon) as tokenize-style (row, col) positions."""
    scanner = PyScanner()
    fed = 0
    for index, line in enumerate(lines):
        if index and not scanner.needs_more():
            break
        scanner.feed(line)
        fed += 1
    end = (fed, len(lines[fed - 1]))
    colon = None if scanner.colon is None else (scanner.colon[0] + 1, scanner.colon[1])
    return end, colon


def tokenize_view(lines: list[str]) -> tuple[tuple[int, int], tuple[int, int] | None]:
    """The same from Python 3.12's tokenize: the NEWLINE token's start, and the last OP ':'
    at bracket depth 0 outside f-strings."""
    source = "\n".join(lines) + "\n"
    depth = 0
    fstrings = 0
    colon = None
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.FSTRING_START:
            fstrings += 1
        elif token.type == tokenize.FSTRING_END:
            fstrings -= 1
        elif token.type == tokenize.OP and fstrings == 0:
            if token.string in "([{":
                depth += 1
            elif token.string in ")]}":
                depth -= 1
            elif token.string == ":" and depth == 0:
                colon = token.start
        elif token.type == tokenize.NEWLINE:
            return token.start, colon
    raise AssertionError("no NEWLINE token")


def test_fixture_has_at_least_300_snippets():
    cases = _cases()
    assert len(cases) >= 300
    tails = {tail for tail, _ in cases}
    assert tails == {"py_all", "py_condition", "py_after_equals"}


@pytest.mark.parametrize("tail,lines", _cases(), ids=lambda v: v if isinstance(v, str) else "")
def test_fixture_snippet_matches_tokenize(tail, lines):
    end, colon = scanner_view(lines)
    expected_end, expected_colon = tokenize_view(lines)
    assert end == expected_end
    if tail == "py_condition":
        assert colon == expected_colon


# --- Generated snippets (06 §5.7) ---------------------------------------------------------

_NAMES = ["x", "y", "trust", "d", "lst", "n"]
_PREFIXES = ["", "r", "b", "u", "f", "rb", "br", "fr", "rf", "R", "F", "Rb", "fR"]


def _string(rng: random.Random, depth: int) -> str:
    prefix = rng.choice(_PREFIXES)
    quote = rng.choice(["'", '"', "'''", '"""'])
    pieces = []
    for _ in range(rng.randint(0, 3)):
        kind = rng.randint(0, 5)
        if kind == 0:
            pieces.append(rng.choice(["a", "b c", "#", ":", "x=1", "(", "]"]))
        elif kind == 1 and "f" in prefix.lower() and depth < 2:
            inner = _expr(rng, depth + 1)
            spec = rng.choice(["", "", ":>10", ":{w}", "!r", "!r:^{w}.{p}"])
            pieces.append("{" + inner + spec + "}")
        elif kind == 2 and "f" in prefix.lower():
            pieces.append(rng.choice(["{{", "}}", "{{x}}"]))
        elif kind == 3 and "r" not in prefix.lower():
            pieces.append(rng.choice(["\\n", "\\\\", "\\" + quote[0]]))
        else:
            pieces.append(rng.choice(["it's" if quote[0] == '"' else 'say "hi"', "a:b"]))
    return prefix + quote + "".join(pieces) + quote


def _expr(rng: random.Random, depth: int = 0) -> str:
    kind = rng.randint(0, 9 if depth < 3 else 2)
    if kind == 0:
        return rng.choice(_NAMES)
    if kind == 1:
        return str(rng.randint(0, 999))
    if kind == 2:
        return _string(rng, depth)
    if kind == 3:
        return f"{_expr(rng, depth + 1)} {rng.choice(['+', '==', 'and', '>=', '%'])} " \
               f"{_expr(rng, depth + 1)}"
    if kind == 4:
        return f"[{', '.join(_expr(rng, depth + 1) for _ in range(rng.randint(0, 3)))}]"
    if kind == 5:
        return "{" + ", ".join(f"{_string(rng, depth)}: {_expr(rng, depth + 1)}"
                               for _ in range(rng.randint(0, 2))) + "}"
    if kind == 6:
        return f"{rng.choice(_NAMES)}[{rng.choice(['1:2', '::2', ':', 'a:b, c'])}]"
    if kind == 7:
        return f"(lambda {rng.choice(['', 'a', 'a=1'])}: {_expr(rng, depth + 1)})"
    if kind == 8:
        return f"({rng.choice(_NAMES)} := {_expr(rng, depth + 1)})"
    return f"f({_expr(rng, depth + 1)}, k={_expr(rng, depth + 1)})"


def _snippet(rng: random.Random) -> tuple[str, list[str]]:
    tail = rng.choice(["py_all", "py_condition", "py_after_equals"])
    expr = _expr(rng)
    if tail == "py_all":
        text = f"{rng.choice(_NAMES)} = {expr}"
    elif tail == "py_condition":
        text = expr + ":"
    else:
        text = expr
    if rng.random() < 0.3:
        text += "  # " + rng.choice(["note", "a: b", "'q'", '"dq"'])
    lines = [text]
    if rng.random() < 0.25:
        # Bracket continuation over 2–4 lines.
        parts = [f"({_expr(rng)},"]
        for _ in range(rng.randint(0, 2)):
            parts.append(f"        {_expr(rng)},")
        parts.append(f"        {_expr(rng)})")
        head = {"py_all": "x = ", "py_condition": "", "py_after_equals": ""}[tail]
        lines = [head + parts[0]] + parts[1:]
        if tail == "py_condition":
            lines[-1] += ":"
    return tail, lines


def test_generated_snippets_match_tokenize():
    rng = random.Random(SEED)
    checked = rejected = 0
    for _ in range(2000):
        tail, lines = _snippet(rng)
        end, colon = scanner_view(lines)
        try:
            expected_end, expected_colon = tokenize_view(lines)
        except (tokenize.TokenError, SyntaxError):
            rejected += 1
            role = {"py_all": ROLE_EXEC, "py_condition": ROLE_CONDITION,
                    "py_after_equals": ROLE_VALUE}[tail]
            source = "\n".join(lines[:end[0]])
            result = compile_piece(source, mode="exec" if role == ROLE_EXEC else "eval",
                                   role=role, filename="<script/main.vns>", line=5, column=7,
                                   lambdas=0)
            assert result.problem is not None or result.code is not None
            continue
        checked += 1
        assert end == expected_end, lines
        if tail == "py_condition":
            assert colon == expected_colon, lines
    assert checked > 1500


def test_reader_joins_deeper_blank_and_comment_lines():
    parsed = parse_text(template(S="$ x = (1,⏎[8]2,⏎⏎[8]# c⏎[8]3)"))
    assert parsed.errors == []
    line = parsed.labels["start"].block[1]
    assert line.py.source == "x = (1,\n        2,\n\n        # c\n        3)"
    assert (line.line, line.end_line) == (5, 9)


def test_reader_stops_at_a_shallower_line():
    parsed = parse_text(template(S="$ x = [1,⏎⏎[8]# c⏎[8]2"))
    assert [e.code for e in parsed.errors] == ["E80"]
    assert parsed.errors[0].message == 'this Python has a mistake: "[" was never closed.'
    # `jump bridge` (line 9) is still read as a statement.
    assert [type(s).__name__ for s in parsed.labels["start"].block] == ["Say", "Jump"]
