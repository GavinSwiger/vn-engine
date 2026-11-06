"""The condition builder's model (F47 design PR-F47-21, ``04-technical.md`` P2-C; AC-F47-34).

Why this module exists: an ``if`` line and a choice's "Only show when" hold a Python
condition, and a game developer should never have to write one. The builder shows a
condition as up to four rows, "All of" or "Any of" them:

    [what ▾ variable · meter · codex tip · item · ending seen · route open · playthrough]
    [is ▾ = ≠ > ≥ < ≤ / has / hasn't] [value]

``read(text)`` gives a ``Condition`` or None. None means the builder can't show it (``x <
y < z``, ``(a or b) and c``, ``len(codex.tips) > 2``, …); the form then shows the text as
written, marked "Written as script", and never rewrites it. ``write(condition)`` gives the
text back: unchanged, it is the text that was read, byte for byte; a changed row is written
in one plain form and the rows left alone keep their spelling.

The shapes it reads (ground truth: ``docs/script-language.md`` §7 if/menu, §9 variables
and persistent, points, codex, endings and routes; F32's ``persistent.playthrough``):

==============  =====================================  ==========================
kind            Python                                 row
==============  =====================================  ==========================
variable        ``coins >= 1``, ``lantern == "red"``   coins is at least 1
variable        ``met_daichi`` / ``not met_daichi``    met_daichi is yes / no
variable        ``persistent.festivals == 2``          (a persistent name)
meter           ``points.hana > 3``                    hana meter is more than 3
tip             ``"river_god" in codex.tips``          has tip river_god
item            ``"key" not in items.held``            doesn't have item key
ending          ``"sad" in persistent.endings``        ending sad seen
route           ``"promise" in persistent.routes``     route promise open
playthrough     ``persistent.playthrough >= 2``        playthrough is at least 2
==============  =====================================  ==========================

joined by ``and`` (all) or ``or`` (any), never both, on one line. A value is a Python
literal as written (``1``, ``-2.5``, ``"red"``, ``True``, ``None``) or ``YES``/``NO``.

Pure: imports only stdlib and ``engine.script.words``.
"""

import ast
import json
import re
from dataclasses import dataclass, field, replace
from typing import Final

from engine.script.words import ENGINE_NAMES, PYTHON_KEYWORDS

MAX_ROWS: Final = 4                      # PR-F47-21: "All of / Any of" join up to 4 rows

ALL: Final = "all"
ANY: Final = "any"
JOINS: Final = {ALL: "All of", ANY: "Any of"}
_JOIN_WORD: Final = {ALL: "and", ANY: "or"}

VARIABLE: Final = "variable"
METER: Final = "meter"
TIP: Final = "tip"
ITEM: Final = "item"
ENDING: Final = "ending"
ROUTE: Final = "route"
PLAYTHROUGH: Final = "playthrough"

# The "what" menu, in the design's order: kind -> label.
KINDS: Final = {VARIABLE: "Variable", METER: "Meter", TIP: "Codex tip", ITEM: "Item",
                ENDING: "Ending seen", ROUTE: "Route open", PLAYTHROUGH: "Playthrough"}

EQ, NE, GT, GE, LT, LE = "=", "≠", ">", "≥", "<", "≤"
HAS: Final = "has"
HASNT: Final = "hasn't"
COMPARE_OPS: Final = (EQ, NE, GT, GE, LT, LE)
HAS_OPS: Final = (HAS, HASNT)
_PY_OP: Final = {EQ: "==", NE: "!=", GT: ">", GE: ">=", LT: "<", LE: "<="}
_AST_OP: Final = {ast.Eq: EQ, ast.NotEq: NE, ast.Gt: GT, ast.GtE: GE, ast.Lt: LT,
                  ast.LtE: LE}
_OP_WORDS: Final = {EQ: "is", NE: "is not", GT: "is more than", GE: "is at least",
                    LT: "is less than", LE: "is at most"}

_PICK_WORD: Final = {METER: "meter", TIP: "codex tip", ITEM: "item", ENDING: "ending",
                     ROUTE: "route"}

# A variable's "is yes" / "is no": the bare name, or ``not`` and the name.
YES: Final = "yes"
NO: Final = "no"

# The lists a has/hasn't row looks in.
_LISTS: Final = {TIP: "codex.tips", ITEM: "items.held", ENDING: "persistent.endings",
                 ROUTE: "persistent.routes"}
# v1: ``codex.items`` (before version 1, W323) still reads as an item row; rows write
# ``items.held``.
_KIND_OF_LIST: Final = {**{source: kind for kind, source in _LISTS.items()},
                        "codex.items": ITEM}
_PLAYTHROUGH_NAME: Final = "persistent.playthrough"
# persistent names the engine keeps (not a plain persistent variable).
_PERSISTENT_ENGINE: Final = frozenset(("endings", "routes", "playthrough"))


def ops_for(kind: str) -> tuple[str, ...]:
    """The "is" menu for a kind: comparisons, or has/hasn't for the codex, endings, routes."""
    return HAS_OPS if kind in _LISTS else COMPARE_OPS


@dataclass(frozen=True, slots=True)
class Row:
    """One builder row. ``name`` is the variable (``coins``, ``persistent.festivals``),
    meter, tip, item, ending, or route; "" for playthrough. ``value`` is a Python literal as
    written, ``YES``/``NO`` (a variable with ``=``), or "" (has/hasn't)."""

    kind: str
    name: str = ""
    op: str = EQ
    value: str = ""


@dataclass(frozen=True, slots=True)
class _Origin:
    """What ``read`` saw, so ``write`` gives unchanged parts back byte for byte."""

    text: str
    rows: tuple[Row, ...]
    join: str
    pieces: tuple[str, ...]              # each row's text as written
    separators: tuple[str, ...]          # between rows, e.g. " and "
    prefix: str
    suffix: str


@dataclass(frozen=True, slots=True)
class Condition:
    """The builder's rows, "All of" (``ALL``) or "Any of" (``ANY``). No rows: no condition.
    Edit it with ``dataclasses.replace`` (or ``with_rows``) so ``write`` keeps what's
    unchanged."""

    rows: tuple[Row, ...] = ()
    join: str = ALL
    origin: _Origin | None = field(default=None, compare=False, repr=False)

    def with_rows(self, rows: tuple[Row, ...] | list[Row]) -> "Condition":
        return replace(self, rows=tuple(rows))


# --- Reading ---------------------------------------------------------------------------------

def read(text: str) -> Condition | None:
    """The builder's rows for ``text``, or None: keep it as text ("Written as script")."""
    body = text.strip()
    if not body:
        return Condition(origin=_Origin(text, (), ALL, (), (), text, ""))
    if "\n" in text or "\r" in text:
        return None
    try:
        tree = ast.parse(body, mode="eval").body
    except (SyntaxError, ValueError):
        return None
    lead = text[:len(text) - len(text.lstrip())]
    if isinstance(tree, ast.BoolOp):
        join = ALL if isinstance(tree.op, ast.And) else ANY
        parts = tree.values
    else:
        join, parts = ALL, [tree]
    if len(parts) > MAX_ROWS:
        return None
    rows: list[Row] = []
    spans: list[tuple[int, int]] = []
    for part in parts:
        row = _row(part, body)
        if row is None:
            return None
        rows.append(row)
        spans.append((_offset(body, part.col_offset), _offset(body, part.end_col_offset)))
    if spans[0][0] != 0 or spans[-1][1] != len(body):
        return None                                   # parentheses around it all
    word = _JOIN_WORD[join]
    separators = tuple(body[spans[k][1]:spans[k + 1][0]] for k in range(len(spans) - 1))
    if any(re.fullmatch(rf"\s+{word}\s+", sep) is None for sep in separators):
        return None                                   # parentheses around a row
    pieces = tuple(body[a:b] for a, b in spans)
    suffix = text[len(lead) + len(body):]
    origin = _Origin(text, tuple(rows), join, pieces, separators, lead, suffix)
    return Condition(tuple(rows), join, origin)


def _offset(body: str, col: int | None) -> int:
    """``ast``'s UTF-8 byte column as a character offset into the one-line ``body``."""
    return len(body.encode("utf-8")[:col or 0].decode("utf-8", "ignore"))


def _row(node: ast.expr, body: str) -> Row | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        name = _variable(node.operand)
        return None if name is None else Row(VARIABLE, name, EQ, NO)
    name = _variable(node)
    if name is not None:
        return Row(VARIABLE, name, EQ, YES)
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    op, left, right = node.ops[0], node.left, node.comparators[0]
    if isinstance(op, (ast.In, ast.NotIn)):
        kind = _KIND_OF_LIST.get(_dotted(right) or "")
        if kind is None or not isinstance(left, ast.Constant) or \
                not isinstance(left.value, str) or not _is_name(left.value):
            return None
        return Row(kind, left.value, HAS if isinstance(op, ast.In) else HASNT)
    symbol = _AST_OP.get(type(op))
    value = _literal(right, body)
    if symbol is None or value is None:
        return None
    dotted = _dotted(left)
    if dotted == _PLAYTHROUGH_NAME:
        return Row(PLAYTHROUGH, "", symbol, value)
    if dotted is not None and dotted.startswith("points."):
        meter = dotted.removeprefix("points.")
        return Row(METER, meter, symbol, value) if _is_name(meter) else None
    name = _variable(left)
    return None if name is None else Row(VARIABLE, name, symbol, value)


def _dotted(node: ast.expr) -> str | None:
    """``a`` or ``a.b`` (one dot) as text, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def _variable(node: ast.expr) -> str | None:
    """A story variable (``coins``) or a persistent one (``persistent.festivals``)."""
    name = _dotted(node)
    return name if name is not None and is_variable_name(name) else None


def _literal(node: ast.expr, body: str) -> str | None:
    """A value's text as written, when it is a plain literal: a number (maybe negative),
    text, True, False, or None."""
    inner = node.operand if isinstance(node, ast.UnaryOp) and \
        isinstance(node.op, (ast.USub, ast.UAdd)) else node
    if not isinstance(inner, ast.Constant):
        return None
    value = inner.value
    if inner is not node and (isinstance(value, bool) or
                              not isinstance(value, (int, float))):
        return None
    if isinstance(value, (bytes, complex)) or value is ...:
        return None
    return body[_offset(body, node.col_offset):_offset(body, node.end_col_offset)]


def _is_name(word: str) -> bool:
    return word.isidentifier() and word not in PYTHON_KEYWORDS


def is_variable_name(name: str) -> bool:
    """A name a variable row can hold: a story variable that isn't the engine's, or
    ``persistent.<name>`` (not ``_``-led, not endings/routes/playthrough)."""
    head, dot, rest = name.partition(".")
    if dot:
        return head == "persistent" and _is_name(rest) and not rest.startswith("_") \
            and rest not in _PERSISTENT_ENGINE
    return _is_name(name) and name not in ENGINE_NAMES and not name.startswith("_")


# --- Writing ---------------------------------------------------------------------------------

def problem(row: Row) -> str | None:
    """Why ``row`` can't be written yet, in plain words, or None."""
    if row.kind not in KINDS:
        return f"Pick what to check ({', '.join(KINDS.values())})."
    if row.op not in ops_for(row.kind):
        return "Pick how to compare."
    if row.kind == PLAYTHROUGH:
        pass
    elif row.kind == VARIABLE:
        if not is_variable_name(row.name):
            return f"{row.name or 'The variable'} can't be used here: pick a story variable."
    elif not _is_name(row.name):
        return f"Pick the {_PICK_WORD[row.kind]}."
    if row.kind in _LISTS:
        return None
    if row.value in (YES, NO):
        return None if row.kind == VARIABLE and row.op == EQ else "Pick a number or a word."
    if not row.value.strip():
        return "Fill in the value."
    try:
        node = ast.parse(row.value.strip(), mode="eval").body
    except (SyntaxError, ValueError):
        return f"{row.value} isn't a value: write a number, or text in quotes."
    if _literal(node, row.value.strip()) is None:
        return f"{row.value} isn't a value: write a number, or text in quotes."
    if row.kind in (METER, PLAYTHROUGH) and not _is_number(row.value):
        return "Write a number."
    return None


def _is_number(value: str) -> bool:
    try:
        number = ast.literal_eval(value.strip())
    except (SyntaxError, ValueError):
        return False
    return isinstance(number, (int, float)) and not isinstance(number, bool)


def write_row(row: Row) -> str:
    """One row in its plain form. ValueError (``problem``'s words) if it can't be written."""
    why = problem(row)
    if why is not None:
        raise ValueError(why)
    if row.kind in _LISTS:
        word = "in" if row.op == HAS else "not in"
        return f'"{row.name}" {word} {_LISTS[row.kind]}'
    if row.value == YES:
        return row.name
    if row.value == NO:
        return f"not {row.name}"
    subject = {PLAYTHROUGH: _PLAYTHROUGH_NAME, METER: f"points.{row.name}"}.get(row.kind,
                                                                              row.name)
    return f"{subject} {_PY_OP[row.op]} {row.value.strip()}"


def write(condition: Condition) -> str:
    """The condition's text. Unchanged since ``read``: the same text. Otherwise rows left
    alone keep their spelling, and the spacing around them stays. No rows: ""."""
    rows, join, origin = condition.rows, condition.join, condition.origin
    if len(rows) > MAX_ROWS:
        raise ValueError(f"A condition has at most {MAX_ROWS} rows.")
    if join not in JOINS:
        raise ValueError("Pick All of or Any of.")
    if origin is not None and rows == origin.rows and join == origin.join:
        return origin.text
    if not rows:
        return ""
    old = origin.rows if origin is not None else ()
    pieces = [origin.pieces[k] if k < len(old) and row == old[k] else write_row(row)
              for k, row in enumerate(rows)]
    word = _JOIN_WORD[join]
    if origin is not None and join == origin.join and len(rows) == len(old):
        text = pieces[0] + "".join(sep + piece
                                   for sep, piece in zip(origin.separators, pieces[1:]))
        return origin.prefix + text + origin.suffix
    return f" {word} ".join(pieces)


# --- Showing ---------------------------------------------------------------------------------

def value_text(value: str) -> str:
    """A value as the builder's field shows it: text without its quotes."""
    if value in (YES, NO):
        return value
    try:
        literal = ast.literal_eval(value.strip())
    except (SyntaxError, ValueError):
        return value
    return literal if isinstance(literal, str) else value.strip()


def value_from_text(shown: str) -> str:
    """What the author typed in the value field as a Python literal: a number, True,
    False, None, ``yes``/``no`` as they are; text in quotes, or quoted for them."""
    word = shown.strip()
    if word in (YES, NO, "True", "False", "None") or _is_number(word):
        return word
    if len(word) >= 2 and word[0] == word[-1] and word[0] in "\"'":
        try:
            if isinstance(ast.literal_eval(word), str):
                return word
        except (SyntaxError, ValueError):
            pass
    return json.dumps(shown, ensure_ascii=False)


def describe(row: Row) -> str:
    """The row in words, for the Events list: "coins is at least 1", "met_daichi is yes",
    "hana meter is more than 3", "ending sad seen"."""
    has = row.op == HAS
    if row.kind == TIP:
        return f"{'has' if has else 'does not have'} tip {row.name}"
    if row.kind == ITEM:
        return f"{'has' if has else 'does not have'} item {row.name}"
    if row.kind == ENDING:
        return f"ending {row.name} {'seen' if has else 'not seen'}"
    if row.kind == ROUTE:
        return f"route {row.name} {'open' if has else 'not open'}"
    subject = {PLAYTHROUGH: "playthrough", METER: f"{row.name} meter"}.get(row.kind,
                                                                         row.name)
    return f"{subject} {_OP_WORDS.get(row.op, row.op)} {value_text(row.value)}"


def summary(condition: Condition) -> str:
    """The whole condition in words: rows joined by "and" / "or"; "" without rows."""
    return f" {_JOIN_WORD[condition.join]} ".join(describe(row) for row in condition.rows)


__all__ = ["ALL", "ANY", "COMPARE_OPS", "Condition", "ENDING", "EQ", "GE", "GT", "HAS",
           "HASNT", "HAS_OPS", "ITEM", "JOINS", "KINDS", "LE", "LT", "MAX_ROWS", "METER",
           "NE", "NO", "PLAYTHROUGH", "ROUTE", "Row", "TIP", "VARIABLE", "YES", "describe",
           "is_variable_name", "ops_for", "problem", "read", "summary", "value_from_text",
           "value_text", "write", "write_row"]
