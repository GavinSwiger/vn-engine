"""Checking author Python with ``compile()`` (F02 ``04-technical.md`` §7.5).

``compile()`` executes nothing: F02 runs no author code (SEC-F02-12). This is the only module
in ``engine/script`` that calls ``compile``, always on ``str`` source with
``dont_inherit=True``.

* A piece longer than ``SCRIPT_PY_PIECE_MAX_CHARS`` (E86b) or with more than
  ``SCRIPT_PY_MAX_LAMBDAS`` ``lambda`` keywords (E86) is never compiled (SEC-F02-02).
* The compile name has a 300-character segment with ``<`` and ``>``, which no OS can open,
  so CPython's attempt to read the offending line fails harmlessly; the code objects are then
  renamed ``<script/a.vns>``, which ``linecache`` never opens (SEC-F02-01).
  Only ``msg``, ``lineno``, and ``offset`` of a ``SyntaxError`` are read.
* Every compile runs inside ``warnings.catch_warnings(record=True)`` with all categories set
  to ``always``, entered and left within one call (SEC-F02-12). ``SyntaxWarning`` → W03.
* Python's message is rewritten per SR-F02-43 and I-12.
"""

import ast
import builtins
import re
import types
import warnings
from dataclasses import dataclass, field

from engine.script.limits import SCRIPT_PY_MAX_LAMBDAS, SCRIPT_PY_PIECE_MAX_CHARS
from engine.script.messages import E50_CHARS, show
from engine.script.words import STATEMENT_WORDS

# The name compile() sees. CPython tries to open it to quote the offending line (exec-mode
# syntax errors and compiler-stage errors); a 300-character segment with "<" and ">" can't be
# opened on any OS, so the attempt fails. The loader may pass the same name under the real
# script folder (``compile_name``), so that the attempt never names a path outside it.
COMPILE_NAME = "<vns-" + "x" * 300 + ">"

ROLE_EXEC = "exec"            # a $ line (E80)
ROLE_CONDITION = "condition"  # if/elif (E81)
ROLE_VALUE = "value"          # define (E82)
_ERROR_CODE = {ROLE_EXEC: "E80", ROLE_CONDITION: "E81", ROLE_VALUE: "E82"}
# F23 (04 §5.2 step 5): a minigame argument is checked like a condition (E81), and its
# messages name it: the role is ``argument_role(name)``, ``the argument <name>``.
ARGUMENT_ROLE_PREFIX = "the argument "

# F23 (02 §4.1, 04 §5.2): ``$ x = minigame …`` or ``$ minigame …`` is E270's ``$`` form.
_MINIGAME_DOLLAR_RE = re.compile(r"\s*(?:([A-Za-z_]\w*)\s*=\s*)?minigame\s+(?=[A-Za-z_])")
_MINIGAME_EXAMPLE_MAX = 120

_CURLY = "".join(sorted(E50_CHARS | {"‘", "’"}))
_INVALID_CHAR_RE = re.compile(r"invalid character '(.)' \(U\+[0-9A-Fa-f]+\)")
_DETECTED_RE = re.compile(r"\s*\(detected at line \d+\)")
_ON_LINE_RE = re.compile(r"\bon line (\d+)")
_SINGLE_QUOTED_RE = re.compile(r"'([^']*)'")
_FIRST_WORD_RE = re.compile(r"\w+")
_EXCEPTION_NAMES = frozenset(
    name for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException))
_JARGON_CASED_RE = re.compile(r"\b(INDENT|DEDENT|EOF|AST)\b")
_JARGON_ANY_RE = re.compile(r"\b(tokens?|pars(e|ed|er|ing)|nodes?|lexer)\b|indent",
                            re.IGNORECASE)
_WORD_RE = re.compile(r"\w+")


@dataclass(slots=True)
class PyProblem:
    """A problem with one piece: code, args for the message, file line and column."""

    code: str
    args: tuple
    line: int
    column: int | None = None


@dataclass(slots=True)
class PyResult:
    code: types.CodeType | None = None
    names: frozenset[str] = frozenset()
    problem: PyProblem | None = None
    warnings: list[tuple[int, str]] = field(default_factory=list)   # (file line, text)
    is_character_call: bool = False


def _rename(code: types.CodeType, filename: str) -> types.CodeType:
    """``code`` and every nested code object with ``co_filename`` = ``filename``. Iterative
    (an explicit stack, post-order), so nothing here recurses (SEC-F02-05)."""
    if not any(isinstance(const, types.CodeType) for const in code.co_consts):
        return code.replace(co_filename=filename)
    done: dict[int, types.CodeType] = {}
    stack: list[tuple[types.CodeType, bool]] = [(code, False)]
    while stack:
        current, expanded = stack.pop()
        if expanded:
            consts = tuple(done[id(c)] if isinstance(c, types.CodeType) else c
                           for c in current.co_consts)
            done[id(current)] = current.replace(co_filename=filename, co_consts=consts)
            continue
        stack.append((current, True))
        for const in current.co_consts:
            if isinstance(const, types.CodeType) and id(const) not in done:
                stack.append((const, False))
    return done[id(code)]


def argument_role(name: str) -> str:
    """The ``compile_piece`` role of a minigame argument (F23): E81, naming the argument."""
    return ARGUMENT_ROLE_PREFIX + name


def compiles_as_expression(source: str) -> bool:
    """True if ``source`` compiles as one Python expression (``eval`` mode), under
    ``compile_piece``'s rules; nothing runs (F23: where a minigame argument's value ends)."""
    if len(source) > SCRIPT_PY_PIECE_MAX_CHARS:
        return False
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        try:
            compile(source, COMPILE_NAME, "eval", dont_inherit=True)
        except (SyntaxError, RecursionError, MemoryError, OverflowError, ValueError):
            return False
    return True


def _minigame_line(source: str) -> str | None:
    """F23: the ``minigame`` line a ``$`` line meant (E270's ``$`` form), or None when the
    ``$`` line isn't one. ``$ found = minigame stargazing(stars=5)`` → ``minigame stargazing
    stars=5 into found``; a form it can't rebuild gives ``""`` (the message's example)."""
    match = _MINIGAME_DOLLAR_RE.match(source)
    if match is None:
        return None
    target = match.group(1)
    into = f" into {target}" if target else ""
    rest = source[match.end():].strip()
    if "\n" in rest or len(rest) > _MINIGAME_EXAMPLE_MAX:
        return ""
    tree = parse_tree(rest, "eval")
    body = tree.body if isinstance(tree, ast.Expression) else None
    if isinstance(body, ast.Name):
        return f"minigame {body.id}{into}"
    if (isinstance(body, ast.Call) and isinstance(body.func, ast.Name) and not body.args
            and all(kw.arg is not None for kw in body.keywords)):
        parts = [f"{kw.arg}={ast.get_source_segment(rest, kw.value)}" for kw in body.keywords]
        return " ".join(["minigame", body.func.id, *parts]) + into
    if not target and rest[:1].isidentifier():
        return f"minigame {rest}"                    # $ minigame stargazing stars=5
    return ""


def _is_jargon(text: str) -> bool:
    if _JARGON_CASED_RE.search(text) or _JARGON_ANY_RE.search(text):
        return True
    return any(word in _EXCEPTION_NAMES for word in _WORD_RE.findall(text))


def rewrite(message: str, first_line: int, hint: str | None = None) -> str:
    """Python's message in the author's words (SR-F02-43, I-12). ``first_line`` is the file
    line of code line 1 (for ``on line N``). ``hint`` replaces the text after a bare
    ``invalid syntax`` (I-8). The result is echoed but has no final ``.`` yet."""
    text = message
    match = _INVALID_CHAR_RE.match(text)
    if match is not None and match.group(1) in _CURLY:
        text = (f"it uses a curly quote {match.group(1)}. Python needs straight quotes "
                "\" or '")
        return show(text)
    if text.startswith("unterminated triple-quoted string literal"):
        return "a triple quote is never closed"
    if text.startswith("unterminated string literal"):
        return "a quote is never closed"
    if text.startswith(("unexpected EOF while parsing", "incomplete input")):
        return "the line ends before the Python is complete"
    if text.startswith("unexpected character after line continuation character"):
        return "something follows a \\ that Python doesn't expect"
    lead = ""
    if text.startswith("invalid syntax"):
        text = text[len("invalid syntax"):]
        if hint is not None and hint.startswith("invalid syntax"):
            text = hint[len("invalid syntax"):]
        lead = "this isn't valid Python"
    text = _DETECTED_RE.sub("", text)
    text = _ON_LINE_RE.sub(lambda m: f"on line {first_line + int(m.group(1)) - 1}", text)
    text = show(_SINGLE_QUOTED_RE.sub(r'"\1"', text))
    if _is_jargon(text):
        return "this isn't valid Python"
    return lead + text


def compile_piece(source: str, *, mode: str, role: str, filename: str, line: int,
                  column: int, lambdas: int, length: int | None = None,
                  collect_names: bool = False, compile_name: str = COMPILE_NAME) -> PyResult:
    """Check one piece of Python. Never raises (except for programming errors).

    ``line``/``column`` place code line 1 in the file. ``length`` is ``len(source)`` as
    stored (I-5); it is passed separately when the source was not kept past the cap.
    """
    result = PyResult()
    size = len(source) if length is None else length
    if size > SCRIPT_PY_PIECE_MAX_CHARS:
        result.problem = PyProblem("E86b", (role,), line)
        return result
    if lambdas > SCRIPT_PY_MAX_LAMBDAS:
        result.problem = PyProblem("E86", (role,), line)
        return result
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            if collect_names:
                tree = compile(source, compile_name, mode, ast.PyCF_ONLY_AST,
                               dont_inherit=True)
                names = frozenset(node.id for node in ast.walk(tree)
                                  if isinstance(node, ast.Name))
                body = tree.body if isinstance(tree, ast.Expression) else None
                result.is_character_call = (isinstance(body, ast.Call)
                                            and isinstance(body.func, ast.Name)
                                            and body.func.id == "Character")
                code = compile(tree, compile_name, mode, dont_inherit=True)
                result.names = names
            else:
                code = compile(source, compile_name, mode, dont_inherit=True)
            result.code = _rename(code, filename)
        except SyntaxError as exc:
            result.problem = _syntax_problem(exc, source, mode, role, line, column,
                                             compile_name)
        except (RecursionError, MemoryError, OverflowError, ValueError):
            result.problem = PyProblem("E86", (role,), line)
        for item in caught:
            if issubclass(item.category, SyntaxWarning):
                lineno = item.lineno if isinstance(item.lineno, int) else 1
                count = source.count("\n") + 1
                lineno = min(max(lineno, 1), count)
                result.warnings.append((line + lineno - 1,
                                        rewrite(str(item.message), line)))
    return result


def parse_tree(source: str, mode: str, *, compile_name: str = COMPILE_NAME) -> ast.AST | None:
    """The tree of a piece that already compiled (F03 ``bindings.py``), under the same rules
    as ``compile_piece``: ``str`` source, ``dont_inherit=True``, warnings caught and dropped
    (the piece's W03s were reported when it compiled). None if it can't be built."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        try:
            return compile(source, compile_name, mode, ast.PyCF_ONLY_AST, dont_inherit=True)
        except (SyntaxError, RecursionError, MemoryError, OverflowError, ValueError):
            return None


def _syntax_problem(exc: SyntaxError, source: str, mode: str, role: str, line: int,
                    column: int, compile_name: str) -> PyProblem:
    message = exc.msg if isinstance(exc.msg, str) else "invalid syntax"
    count = source.count("\n") + 1
    lineno = exc.lineno if isinstance(exc.lineno, int) else 1
    lineno = min(max(lineno, 1), count)
    offset = exc.offset if isinstance(exc.offset, int) and exc.offset > 0 else None
    hint = None
    if message == "invalid syntax" and role not in (ROLE_EXEC, ROLE_VALUE):
        hint = _paren_hint(source, mode, compile_name)   # I-8 (F23: arguments too)
    if role == ROLE_EXEC:
        rebuilt = _minigame_line(source)
        if rebuilt is not None:                          # F23: E270's $ form
            return PyProblem("E270", ("dollar", rebuilt), line)
        first = _FIRST_WORD_RE.match(source)
        if first is not None and first.group() in STATEMENT_WORDS:
            return PyProblem("E83", (first.group(),), line)
    file_column = None
    if offset is not None:
        file_column = offset + (column - 1 if lineno == 1 else 0)
    text = rewrite(message, line, hint)
    code = _ERROR_CODE.get(role)
    args: tuple = (text,) if code is not None else (text, role)   # F23: (text, subject)
    return PyProblem(code or "E81", args, line + lineno - 1, file_column)


def _paren_hint(source: str, mode: str, compile_name: str) -> str | None:
    """I-8: ``compile("(" + code + ")")`` a second time, only for Python's hint text."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        try:
            compile("(" + source + ")", compile_name, mode, dont_inherit=True)
        except SyntaxError as exc:
            return exc.msg if isinstance(exc.msg, str) else None
        except (RecursionError, MemoryError, OverflowError, ValueError):
            return None
    return None
