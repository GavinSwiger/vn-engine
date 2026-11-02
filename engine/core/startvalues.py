"""Start values: the options ``run --start LABEL`` and ``--set NAME=VALUE`` (F44 §3, §4, §7.3).

Why this module exists: an author can start a dev run at any label with chosen values for
some ``default`` names (PR-F44-17, PR-F44-19), from the command line or from the editor's
Preview. A value is written like a plain ``default`` value, but it comes from outside the
script, so it must never run code (SC-5, ADR-0008 D4). ``parse_literal`` parses the text with
``ast.parse`` and builds the value from the syntax tree through an allow-list. Nothing is
ever evaluated, compiled to bytecode, or imported.

*Why ``core``:* ``app/cli.py`` (before anything else loads), ``script`` (load checks),
``runtime`` (``new_game``) and ``tools`` (the editor) all need it, and ``core`` is the only
package all four may import. Standard library plus ``core`` only, no side effects on import.

One list check, ``parse_set_list``, finds every malformed value, every name given twice,
and more than ``SET_MAX_COUNT`` values (I-5). The CLI and the editor's ``start_value_args``
both use it, so bad start values never reach a preview. Whether a name belongs to a
``default`` is checked later, at load (E26c, ``script/startcheck.py``).
"""

import ast
import keyword
import math
# CPython's parser imports unicodedata to normalize a non-ASCII name ("日本"). Loading it
# here keeps parse_literal free of any import, which AC-F44-03's audit hook checks.
import unicodedata  # noqa: F401
import warnings
from collections.abc import Sequence
from dataclasses import dataclass

from engine.core.constants import SET_MAX_COUNT, SET_MAX_DEPTH, SET_VALUE_MAX_CHARS
from engine.core.redact import echo

# --- Messages (PR-F44-19 with I-9; the drafts are for the narrative designer, G5) --------
# A reason is a sentence fragment with no final period. The CLI writes it as
# ``--set "<argument>": <reason>.``; the editor as ``Start values, line N: <reason>.``

QUOTE_TEXT = "put text in quotes"
NOT_A_VALUE = ("the value must be a number, True, False, None, quoted text, a list, "
               "or a dictionary")
# Drafted (G5): a --set with no "=" or no name, a bad name, a Python keyword, too many.
NEEDS_NAME_AND_VALUE = "write it as name=value, like sayo_points=1"
BAD_NAME = "the name must start with a letter or _ and use only letters, digits, and _"


def keyword_name(name: str) -> str:
    """Drafted (G5): a name that is a Python keyword."""
    return f"`{echo(name)}` is a Python keyword and can't be a name"


def set_twice(name: str) -> str:
    """04 §5.4: the same name in two ``--set`` values (or two editor lines)."""
    return f"`{echo(name)}` is set twice"


def too_many(count: int) -> str:
    """Drafted (G5): more than SET_MAX_COUNT values."""
    return f"at most {SET_MAX_COUNT} start values can be set, and there are {count}"


# A decimal literal may have at most 4,300 digits (Python's default int/str limit, which
# ``ast.parse`` enforces); a hex, octal, or binary literal gets the same bound, so every
# accepted int can be printed and written to JSON.
_INT_LIMIT = 10 ** 4300


@dataclass(frozen=True)
class StartOptions:
    """Session configuration from ``--start`` and ``--set``; held by ``App`` and the
    ``Interpreter``, never saved (04 §3)."""

    label: str | None = None                       # None → "start"
    values: tuple[tuple[str, object], ...] = ()    # --set order, names unique, plain data


class StartValueError(ValueError):
    """A start value that can't be used.

    ``reason`` is the bare fragment (``put text in quotes``). ``message`` is the PR-F44-19
    usage text: ``--set "<echo(argument)>": <reason>.``, or ``--set: <reason>.`` when no
    single argument is at fault (too many values, or ``parse_literal`` called on its own).
    ``index`` is the argument's position in ``parse_set_list``'s input, None otherwise.
    """

    def __init__(self, reason: str, *, argument: str | None = None,
                 index: int | None = None) -> None:
        self.reason = reason
        self.argument = argument
        self.index = index
        if argument is None:
            self.message = f"--set: {reason}."
        else:
            self.message = f'--set "{echo(argument)}": {reason}.'
        super().__init__(self.message)


def parse_literal(text: str) -> object:
    """§7.3. Builds the value from the syntax tree. Never evaluates. Raises StartValueError.

    Allowed: ``int``, finite ``float``, ``str``, ``True``, ``False``, ``None``, a sign
    (``-``/``+``) on a number, lists, and dictionaries with text keys, nested at most
    SET_MAX_DEPTH deep, in at most SET_VALUE_MAX_CHARS characters.
    """
    if len(text) > SET_VALUE_MAX_CHARS:
        raise StartValueError(NOT_A_VALUE)
    text = text.strip()
    try:
        with warnings.catch_warnings():
            # ``"\q"`` keeps its backslash as in a script; ``1 is 1`` is refused anyway.
            warnings.simplefilter("ignore")
            tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        # Unquoted words ("Hana Sato") are the usual mistake; anything else is general.
        raise StartValueError(QUOTE_TEXT if text[:1].isalpha() else NOT_A_VALUE) from None
    return _build(tree.body, 0)


def parse_set(text: str) -> tuple[str, object]:
    """'name = value' → (name, value). The name must be an identifier and not a Python
    keyword; the value goes through parse_literal. Errors carry ``argument=text``."""
    name, value_text = _split(text)
    try:
        return name, parse_literal(value_text)
    except StartValueError as error:
        raise StartValueError(error.reason, argument=text) from None


def parse_set_list(arguments: Sequence[str]
                   ) -> tuple[tuple[tuple[str, object], ...], tuple[StartValueError, ...]]:
    """I-5: the one start-value list check, shared by ``cli.py`` and the editor.

    Returns ``(values, problems)``. ``values`` is the ``StartOptions.values`` tuple in input
    order; it is empty whenever there is a problem. ``problems`` lists every malformed
    argument and every later repeat of a name (one problem per argument, in input order,
    each with its ``index``), then one problem without an index if there are more than
    SET_MAX_COUNT arguments. A name counts as given even when its value is refused, so
    ``x = Hana`` followed by ``x = 2`` reports both lines.
    """
    values: list[tuple[str, object]] = []
    problems: list[StartValueError] = []
    seen: set[str] = set()
    for index, argument in enumerate(arguments):
        try:
            name, value_text = _split(argument)
        except StartValueError as error:
            problems.append(StartValueError(error.reason, argument=argument, index=index))
            continue
        try:
            value = parse_literal(value_text)
        except StartValueError as error:
            problems.append(StartValueError(error.reason, argument=argument, index=index))
        else:
            if name in seen:
                problems.append(StartValueError(set_twice(name), argument=argument,
                                                index=index))
            else:
                values.append((name, value))
        seen.add(name)
    if len(arguments) > SET_MAX_COUNT:
        problems.append(StartValueError(too_many(len(arguments))))
    if problems:
        return (), tuple(problems)
    return tuple(values), ()


# --- Internals ---------------------------------------------------------------------------

def _split(text: str) -> tuple[str, str]:
    """``name = value`` → (name, value text); the name is checked, the value is not."""
    name, equals, value_text = text.partition("=")
    name = name.strip()
    if not equals or not name:
        raise StartValueError(NEEDS_NAME_AND_VALUE, argument=text)
    if not name.isidentifier():
        raise StartValueError(BAD_NAME, argument=text)
    if keyword.iskeyword(name):
        raise StartValueError(keyword_name(name), argument=text)
    return name, value_text


def _build(node: ast.expr, depth: int) -> object:
    """The value of an allowed node; ``depth`` counts the lists and dicts around it."""
    if isinstance(node, ast.Constant):
        return _constant(node.value)
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) in (int, float)):          # not bool
        number = node.operand.value
        return _number(-number if isinstance(node.op, ast.USub) else number)
    if isinstance(node, ast.Name):
        raise StartValueError(QUOTE_TEXT)
    if isinstance(node, ast.List):
        _enter(depth)
        return [_build(item, depth + 1) for item in node.elts]
    if isinstance(node, ast.Dict):
        _enter(depth)
        result: dict[str, object] = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Name):
                raise StartValueError(QUOTE_TEXT)
            if not (isinstance(key, ast.Constant) and type(key.value) is str):
                raise StartValueError(NOT_A_VALUE)           # also None: a ** entry
            result[key.value] = _build(value, depth + 1)
        return result
    raise StartValueError(NOT_A_VALUE)


def _enter(depth: int) -> None:
    if depth >= SET_MAX_DEPTH:
        raise StartValueError(NOT_A_VALUE)


def _constant(value: object) -> object:
    if value is None or type(value) in (bool, str):
        return value
    if type(value) in (int, float):
        return _number(value)
    raise StartValueError(NOT_A_VALUE)          # bytes, complex, Ellipsis


def _number(value: int | float) -> int | float:
    if type(value) is float and not math.isfinite(value):
        raise StartValueError(NOT_A_VALUE)
    if type(value) is int and abs(value) >= _INT_LIMIT:
        raise StartValueError(NOT_A_VALUE)
    return value
