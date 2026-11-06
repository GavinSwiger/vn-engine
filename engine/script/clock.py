"""``clock``: story time moves on (F63 round 1, specs/F63-story-clock/SPEC.md; proposal I-03).

Why this module exists: day-and-night stories (Persona-style weeks, horror countdowns, farm and
café days) need time as saved story state. Three lines move it, and conditions and text read it:

- ``clock next``: the next part of the day (after the last part, the first of the next day).
- ``clock next day``: the first part of the next day.
- ``clock go to <target>``: ``day 7`` (or ``7``), a written date in quotes (``"31 October"``,
  ``"Spring 4"``: the next time that date comes, today counting), a part of the day (``Night``,
  ``"After school"``: later today, else the next day), or a day or date followed by a part
  (``clock go to day 7 Evening``).
- ``clock.day``, ``clock.part``, ``clock.weekday``, ``clock.date``, ``clock.month``,
  ``clock.season``, ``clock.days_left(…)`` in conditions and ``$`` lines (``runtime/clock.py``),
  and ``{var=clock.date}`` (any of the six values) in text.

**Positional word** (ADR-0010 rules 3 and 4). ``clock`` is not reserved: a line is the clock
statement only when ``clock`` is its first word and ``next`` or ``go`` follows (``clock next
"Tick."`` stays dialogue, as any ``clock "…"``). A ``clock`` line with no quoted text that isn't
claimed is E428, which names the other reading when the game defines a character ``clock``.
In Python ``clock`` is a built-in name, so a game's own ``clock`` variable or character hides
the story clock there (W302).

**Checks.** Parse: E428 (no ``next``/``go``, a colon), E429 (after ``next``), E430 (``go to``).
Whole game (``check_story``, with the config when the load has one): E431 (a date this
calendar can't read), E432 (a part of the day it doesn't have), E433 (``clock.days_left``),
E434 (``clock.<name>`` it doesn't have, or a write), W300 (``clock.part == "Nite"``), W301
(``[calendar]`` problems), W302, W303 (``go to day`` past ``last_day``).

``ClockStep`` is not a checkpoint and never branches: the story map and reach treat it as a
plain line, and conditions on ``clock`` like any condition on a value they can't know.
"""

import ast
import difflib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final, Literal

from engine.core.constants import CONFIG_FILENAME
from engine.core.storyclock import DAY_MAX, Calendar, DateProblem, calendar_of
from engine.script import clock_messages
from engine.script.bindings import Piece, iter_pieces, parse
from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.identity import walk_block
from engine.script.lexer import NAME, STRING, RawStatement
from engine.script.messages import TEMPLATES, format_message
from engine.script.nodes import Default, Define, Label, Node, Statement
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import (NoText, ParseContext, PositionalWord, StatementSpec,
                                      register_positional)
from engine.script.suggest import suggest

WORD_CLOCK: Final = "clock"
WORD_NEXT: Final = "next"
WORD_GO: Final = "go"
WORD_TO: Final = "to"
WORD_DAY: Final = "day"
# What ``clock.<name>`` may read (runtime/clock.ClockView), and the names compared to text.
VALUES: Final = ("day", "part", "weekday", "date", "month", "season")
DAYS_LEFT: Final = "days_left"
NAMES: Final = (*VALUES, DAYS_LEFT)
_NAMED: Final = {"part": "parts", "weekday": "weekdays", "month": "months", "season": "seasons"}
_NUMBER_RE: Final = re.compile(r"\d{1,6}")

TEMPLATES.update(clock_messages.TEMPLATES)


@dataclass(slots=True, kw_only=True)
class ClockStep(Statement):
    """One ``clock`` line. ``action``: ``next`` (a part), ``next_day``, or ``go`` with ``day``
    (a number), ``text`` (a quoted date, or a quoted part when nothing follows it) and/or
    ``part`` (a part's name as written). Not a checkpoint."""

    action: Literal["next", "next_day", "go"]
    day: int | None = None
    text: str | None = None
    part: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        target = ("" if self.day is None else str(self.day), self.text or "", self.part or "")
        return (WORD_CLOCK, self.action, *(target if self.action == "go" else ()))

    def written(self) -> str:
        """The line as Studio writes it back."""
        if self.action == "next":
            return "clock next"
        if self.action == "next_day":
            return "clock next day"
        parts = ["clock go to"]
        if self.day is not None:
            parts.append(f"day {self.day}")
        if self.text is not None:
            parts.append(f'"{self.text}"')
        if self.part is not None:
            parts.append(self.part if self.part.isidentifier() else f'"{self.part}"')
        return " ".join(parts)


# --- Parsing ---------------------------------------------------------------------------------

def claims(raw: RawStatement) -> bool:
    """Whether a line starting with ``clock`` is the clock statement (module docstring)."""
    tokens = raw.tokens
    if len(tokens) < 2 or tokens[1].kind != NAME or tokens[1].text not in (WORD_NEXT, WORD_GO):
        return False
    return tokens[1].text == WORD_GO or all(t.kind != STRING for t in tokens)


def _found(raw: RawStatement, index: int) -> str:
    token = raw.tokens[index]
    return raw.rest_from(token.line, token.column)


def parse_clock(raw: RawStatement, ctx: ParseContext) -> ClockStep | None:
    tokens = raw.tokens
    if raw.ends_with_colon:
        ctx.error("E428", "colon", tokens[1].text)
        return None
    common = dict(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column)
    if tokens[1].text == WORD_NEXT:
        if len(tokens) == 2:
            return ClockStep(action="next", **common)
        if len(tokens) == 3 and tokens[2].kind == NAME and tokens[2].text == WORD_DAY:
            return ClockStep(action="next_day", **common)
        at = 3 if tokens[2].kind == NAME and tokens[2].text == WORD_DAY else 2
        ctx.error("E429", "day" if at == 3 else "next", _found(raw, at))
        return None
    if len(tokens) < 3 or tokens[2].kind != NAME or tokens[2].text != WORD_TO:
        ctx.error("E430", "to", raw.rest_after(tokens[1]) if len(tokens) > 2 else "")
        return None
    rest = tokens[3:]
    if not rest:
        ctx.error("E430", "target", "")
        return None
    day: int | None = None
    text: str | None = None
    part: str | None = None
    index = 0
    first = rest[0]
    if first.kind == NAME and first.text == WORD_DAY and len(rest) > 1 \
            and rest[1].kind == NAME and rest[1].text.isdigit():
        index = 2
        day = _day(ctx, rest[1].text)
    elif first.kind == NAME and first.text == WORD_DAY and len(rest) > 1 \
            and rest[1].kind != STRING:
        ctx.error("E430", "day", _found(raw, 4))
        return None
    elif first.kind == NAME and first.text.isdigit():
        index = 1
        day = _day(ctx, first.text)
    elif first.kind == STRING:
        index = 1
        text = " ".join(first.text.split())
    elif first.kind == NAME and first.text.isidentifier():
        index = 1
        part = first.text
    else:
        ctx.error("E430", "target", _found(raw, 3))
        return None
    if raw.has_error:                                         # _day's E430
        return None
    if index < len(rest) and part is None:
        nxt = rest[index]
        if nxt.kind == STRING or (nxt.kind == NAME and nxt.text.isidentifier()):
            part = " ".join(nxt.text.split())
            index += 1
    if index < len(rest):
        ctx.error("E430", "extra", _found(raw, 3 + index))
        return None
    if text == "" or part == "":
        ctx.error("E430", "empty", "")
        return None
    return ClockStep(action="go", day=day, text=text, part=part, **common)


def _day(ctx: ParseContext, digits: str) -> int | None:
    number = int(digits) if _NUMBER_RE.fullmatch(digits) else DAY_MAX + 1
    if not 1 <= number <= DAY_MAX:
        ctx.error("E430", "range", digits)
        return None
    return number


def no_text(item: NoText, defined: bool) -> Diagnostic:
    """ADR-0010 rule 4: a ``clock`` line with no quoted text that isn't the statement."""
    rest = item.rest.split()
    found = rest[0] if rest else ""
    form = "speaker" if defined else "word"
    return Diagnostic("E428", item.file, item.line, None,
                      (form, found, suggest(found, (WORD_NEXT, WORD_GO)) if found else None),
                      source_line=item.source_line, stmt=item.line)


SPEC: Final = StatementSpec(word=WORD_CLOCK, placement="story", takes_block=False,
                            tail="script", parse=parse_clock)
register_positional(PositionalWord(SPEC, claims, no_text))


# --- Whole-game checks -----------------------------------------------------------------------

def _steps(nodes: Iterable[Node]) -> Iterable[ClockStep]:
    for node in nodes:
        if isinstance(node, Label):
            for stmt, _ in walk_block(node.block):
                if isinstance(stmt, ClockStep):
                    yield stmt


def close_name(text: str, names: Iterable[str]) -> str | None:
    """The one of ``names`` ``text`` most likely means: the same in other capitals, else
    F02's suggestion, else the closest by spelling ("Nite" → "Night"), else None."""
    names = tuple(names)
    folded = text.casefold()
    same = next((n for n in names if n.casefold() == folded), None)
    if same is not None:
        return same
    found = suggest(text, names)
    if found is not None:
        return found
    by_fold = {n.casefold(): n for n in names}
    match = difflib.get_close_matches(folded, list(by_fold), n=1, cutoff=0.6)
    return by_fold[match[0]] if match else None


def _clock_attr(node: ast.AST) -> ast.Attribute | None:
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == WORD_CLOCK):
        return node
    return None


def _names_of(calendar: Calendar, value: str) -> tuple[str, ...]:
    if value == "part":
        return calendar.parts
    if value == "weekday":
        return calendar.weekdays
    if value == "month":
        return tuple(name for name, _ in calendar.months)
    return calendar.seasons


def _check_piece(piece: Piece, calendar: Calendar | None, add: Callable[[Diagnostic], object],
                 warnings: list[ScriptWarning]) -> None:
    py = piece.py
    tree = parse(py)
    if tree is None:
        return

    def error(code: str, node: ast.AST, args: tuple) -> None:
        add(Diagnostic(code, piece.file, py.line + getattr(node, "lineno", 1) - 1, None, args,
                       stmt=piece.stmt))

    found = sorted((n for n in ast.walk(tree) if _clock_attr(n) is not None),
                   key=lambda n: (n.lineno, n.col_offset))
    for attr in found:
        assert isinstance(attr, ast.Attribute)
        if not isinstance(attr.ctx, ast.Load):
            error("E434", attr, ("write", attr.attr, None))
            return
        if attr.attr not in NAMES and not attr.attr.startswith("_"):
            error("E434", attr, ("unknown", attr.attr, suggest(attr.attr, NAMES)))
            return
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and (attr := _clock_attr(node.func)) is not None
                and attr.attr == DAYS_LEFT):
            if len(node.args) > 1 or node.keywords:
                error("E433", node, ("args", ""))
                return
            if calendar is None:
                continue
            if not node.args and calendar.last_day is None:
                error("E433", node, ("no_last_day", ""))
                return
            arg = node.args[0] if node.args else None
            if (isinstance(arg, ast.Constant) and type(arg.value) is str
                    and calendar.find_date(arg.value) is None):
                error("E433", node, ("date", arg.value, _example(calendar)))
                return
    if calendar is None:
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 \
                or not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            continue
        left, right = node.left, node.comparators[0]
        for side, other in ((left, right), (right, left)):
            attr = _clock_attr(side)
            if (attr is None or attr.attr not in _NAMED or not isinstance(other, ast.Constant)
                    or type(other.value) is not str):
                continue
            names = _names_of(calendar, attr.attr)
            if other.value not in names:
                close = close_name(other.value, names)
                text = format_message("W300", (attr.attr, other.value, close, names))
                warnings.append(ScriptWarning(text, code="W300", file=piece.file.ref,
                                              line=py.line + node.lineno - 1))


def _example(calendar: Calendar) -> str:
    """A date this calendar can read, for messages."""
    if calendar.months:
        return f"{min(3, calendar.months[-1][1])} {calendar.months[-1][0]}"
    if calendar.seasons:
        return f"{calendar.seasons[-1]} 3"
    return "day 3"


def _check_step(stmt: ClockStep, calendar: Calendar, add: Callable[[Diagnostic], object],
                warnings: list[ScriptWarning]) -> None:
    if stmt.action != "go":
        return
    try:
        calendar.go_to(calendar.start_day, 0, day=stmt.day, text=stmt.text, part=stmt.part)
    except DateProblem as problem:
        if problem.form == "part":
            add(Diagnostic("E432", stmt.file, stmt.line, None,
                           (problem.text, close_name(problem.text, calendar.parts),
                            calendar.parts), stmt=stmt.line))
        else:
            add(Diagnostic("E431", stmt.file, stmt.line, None,
                           (problem.text, _example(calendar)), stmt=stmt.line))
        return
    last = calendar.last_day
    if stmt.day is not None and last is not None and stmt.day > last:
        warnings.append(ScriptWarning(format_message("W303", (stmt.day, last)), code="W303",
                                      file=stmt.file.ref, line=stmt.line))


def check_story(nodes: Iterable[Node], add: Callable[[Diagnostic], object],
                config: Any = None) -> list[ScriptWarning]:
    """E431–E434 to ``add``; W300–W303 returned. ``config`` None (tools without one): the
    checks that need the calendar's names (E431, E432, E433's date and last-day forms, W300,
    W301, W303) are skipped."""
    nodes = list(nodes)
    warnings: list[ScriptWarning] = []
    calendar: Calendar | None = None
    if config is not None:
        calendar, problems = calendar_of(config)
        for problem in problems:
            warnings.append(ScriptWarning(
                format_message("W301", (problem.form, problem.text)), code="W301",
                file=CONFIG_FILENAME))
    own = next((node for node in nodes if isinstance(node, Define)
                and node.name == WORD_CLOCK), None)
    if own is None:
        own = next((node for node in nodes if isinstance(node, Default)
                    and node.name == WORD_CLOCK), None)
    steps = list(_steps(nodes))
    uses = [piece for piece in iter_pieces(nodes)
            if WORD_CLOCK in piece.py.source and WORD_CLOCK in piece.py.code.co_names]
    if own is not None:
        if uses:
            first = uses[0]
            warnings.append(ScriptWarning(format_message("W302", ()), code="W302",
                                          file=first.file.ref, line=first.py.line))
        return warnings
    if calendar is not None:
        for stmt in steps:
            _check_step(stmt, calendar, add, warnings)
    for piece in uses:
        _check_piece(piece, calendar, add, warnings)
    return warnings


# --- Studio docs (F45): Insert ▸ Time ----------------------------------------------------------

for _doc in (
        StatementDoc(
            "clock", "Next part of the day", "Time", "clock next",
            "Moves story time to the next part of the day, or to the next morning after the "
            "last part.", "clock next", "clock (story time)", "F63"),
        StatementDoc(
            "clock", "Next day", "Time", "clock next day",
            "Moves story time to the first part of the next day.", "clock next day",
            "clock (story time)", "F63"),
        StatementDoc(
            "clock", "Go to a day", "Time", "clock go to day <n> [<part>]",
            "Moves story time to a day, a date in quotes, or a part of the day.",
            "clock go to day 7 Evening", "clock (story time)", "F63", fields=("7",)),
):
    register_doc(_doc)
del _doc


__all__ = ["ClockStep", "DAYS_LEFT", "NAMES", "SPEC", "VALUES", "WORD_CLOCK", "check_story",
           "claims", "no_text", "parse_clock"]
