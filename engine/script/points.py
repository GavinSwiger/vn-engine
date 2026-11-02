"""The ``points`` statement: meters, the story's whole-number stats (F22 SPEC §3; 07 I-1 to I-5).

Why this module exists: a meter needs its own namespace (``points.sayori`` beside the
``sayori`` character), a range declared once, and a load check for every name, which a plain
``default`` variable can't give. One word, two forms (``StatementSpec.placement="either"``):

- **Declare** (depth 0): ``points <name>… [<low> to <high>] [start <n>]`` → ``PointsDecl``, a
  declaration with sid ``"points:" + names[0]``. Names follow script-language §6
  (``check_name``: E60–E64, role ``a meter name``), are not ``highest``, ``to``, or ``start``
  (E230), and are at most ``METER_NAME_MAX`` code points (E230's long form, 07 I-2). Numbers
  are whole, within ±``POINTS_LIMIT``, ``low < high``, ``start`` in range (E232). Duplicates
  (E231) and the total (E235) are the whole-game checks' (``checks.py``,
  ``Collected.meter_defs``).
- **Change** (in a block): ``points <name> +=|-=|= <amount>`` → ``PointsChange``. The amount is
  eval-mode Python compiled as a value (F02's rules); the bindings pass checks it like a
  condition and checks the meter name (E233, ``bindings.py``).

``MeterSpec`` lives here, not in ``runtime`` (07 I-1: ``script`` never imports ``runtime``);
``runtime/points.py`` re-exports it.
"""

from dataclasses import dataclass
from typing import Final

from engine.script.identity import register_declaration
from engine.script.lexer import EQUALS, NAME, SYMBOL, TAIL_AFTER_EQUALS, RawStatement
from engine.script.nodes import Node, PyCode, Statement, norm
from engine.script.pycheck import ROLE_VALUE
from engine.script.stage import NUMBER, WORD, _chunks, _written
from engine.script.statements import ParseContext, StatementSpec, register
from engine.script.words import ROLE_METER, canonical_name, check_name

WORD_POINTS: Final = "points"
POINTS_LIMIT: Final = 1_000_000_000      # every bound, start, and value: |v| ≤ this
METERS_MAX: Final = 200                  # distinct meter names in a story (E235)
METER_NAME_MAX: Final = 64               # code points (07 I-2)
STATEMENT_PARTS: Final = frozenset(("highest", "to", "start"))   # never a meter name
OPS: Final = ("+=", "-=", "=")
_DIGITS_MAX = 12                         # a longer number is out of range without int()


@dataclass(frozen=True, slots=True)
class MeterSpec:
    """One declared meter: its canonical name, range, and start. ``ranged`` is True when the
    line gave a range (the F3 overlay shows it only then)."""

    name: str
    low: int = -POINTS_LIMIT
    high: int = POINTS_LIMIT
    start: int = 0
    ranged: bool = False

    def clamp(self, value: int) -> int:
        return self.low if value < self.low else self.high if value > self.high else value


@dataclass(slots=True, kw_only=True)
class PointsDecl(Node):
    """``points <name>… [<low> to <high>] [start <n>]`` at the top level. ``low``/``high`` are
    the range (±``POINTS_LIMIT`` when none was given), ``start`` the resolved start (0, or
    ``low`` when 0 is outside the range). Its sid is ``"points:" + names[0]``."""

    names: tuple[str, ...]
    low: int = -POINTS_LIMIT
    high: int = POINTS_LIMIT
    start: int = 0
    ranged: bool = False

    def specs(self) -> tuple[MeterSpec, ...]:
        return tuple(MeterSpec(name, self.low, self.high, self.start, self.ranged)
                     for name in self.names)


@dataclass(slots=True, kw_only=True)
class PointsChange(Statement):
    """``points <name> +=|-=|= <amount>`` in a block. Not a checkpoint; ``VOICE_TRANSPARENT``
    (07 I-3)."""

    name: str
    op: str
    amount: PyCode

    def identity_key(self) -> tuple[str, ...]:
        return ("points", self.name, self.op, norm(self.amount.without_comments()))


# --- Parsing ---------------------------------------------------------------------------------

def _number(ctx: ParseContext, written: str) -> int | None:
    """A whole number within ±``POINTS_LIMIT`` (E232's ``whole`` and ``big`` forms)."""
    if "." in written:
        ctx.error("E232", "whole", written)
        return None
    digits = written.lstrip("-")
    if len(digits) > _DIGITS_MAX or abs(int(written)) > POINTS_LIMIT:
        ctx.error("E232", "big", written)
        return None
    return int(written)


def _meter_name(ctx: ParseContext, written: str) -> str | None:
    if written in STATEMENT_PARTS:
        ctx.error("E230", "word", written)
        return None
    problem = check_name(written, ROLE_METER)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    name = canonical_name(written)
    if len(name) > METER_NAME_MAX:
        ctx.error("E230", "long", len(name), METER_NAME_MAX)
        return None
    if name in STATEMENT_PARTS:
        ctx.error("E230", "word", name)
        return None
    return name


def _parse_decl(raw: RawStatement, ctx: ParseContext) -> PointsDecl | None:
    chunks, colon = _chunks(raw)
    count = len(chunks)
    index = 0
    while (index < count and chunks[index].kind == WORD
           and chunks[index].text not in ("to", "start")):
        index += 1
    if index == 0:
        if count and chunks[0].kind == WORD:
            ctx.error("E230", "word", chunks[0].text)
        else:
            ctx.error("E230", "need")
        return None
    names: list[str] = []
    for chunk in chunks[:index]:
        name = _meter_name(ctx, chunk.text)
        if name is None:
            return None
        names.append(name)
    # Registered even when the rest of the line has an error, so its uses give no E233.
    for name in names:
        ctx.collected.meter_defs.setdefault(name, []).append(ctx.place())
    low, high, ranged = -POINTS_LIMIT, POINTS_LIMIT, False
    if index < count and chunks[index].kind == NUMBER:
        if not (index + 2 < count and chunks[index + 1].kind == WORD
                and chunks[index + 1].text == "to" and chunks[index + 2].kind == NUMBER):
            ctx.error("E230", "left", _written(raw, chunks[index:]))
            return None
        found_low = _number(ctx, chunks[index].text)
        if found_low is None:
            return None
        found_high = _number(ctx, chunks[index + 2].text)
        if found_high is None:
            return None
        if found_low >= found_high:
            ctx.error("E232", "backwards" if found_low > found_high else "same",
                      found_low, found_high)
            return None
        low, high, ranged = found_low, found_high, True
        index += 3
    start = 0 if low <= 0 <= high else low
    if index < count and chunks[index].kind == WORD and chunks[index].text == "start":
        if index + 1 >= count or chunks[index + 1].kind != NUMBER:
            ctx.error("E230", "left", _written(raw, chunks[index:]))
            return None
        found = _number(ctx, chunks[index + 1].text)
        if found is None:
            return None
        if not low <= found <= high:
            ctx.error("E232", "start", found, low, high)
            return None
        start = found
        index += 2
    if index < count:
        ctx.error("E230", "left", _written(raw, chunks[index:]))
        return None
    if colon:
        ctx.error("E110", "colon", WORD_POINTS)
        return None
    return PointsDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                      names=tuple(names), low=low, high=high, start=start, ranged=ranged)


def _parse_change(raw: RawStatement, ctx: ParseContext) -> PointsChange | None:
    tokens = raw.tokens[1:]
    if ctx.depth == 0:
        ctx.error("E230", "declare")
        return None
    if not tokens or tokens[0].kind != NAME:
        ctx.error("E230", "need")
        return None
    middle = tokens[1:-1] if tokens[-1].kind == EQUALS else tokens[1:]
    if not all(t.kind == SYMBOL for t in middle):
        ctx.error("E230", "change")
        return None
    op = "".join(t.text for t in middle) + "="
    if op not in OPS:
        ctx.error("E230", "operator", op)
        return None
    name = _meter_name(ctx, tokens[0].text)
    if name is None:
        return None
    span = raw.py
    assert span is not None
    if not span.truncated and not span.source.strip():
        ctx.error("E230", "change")
        return None
    amount, _ = ctx.compile(span.source, line=span.line, column=span.column, mode="eval",
                            role=ROLE_VALUE, lambdas=span.lambdas, length=span.length,
                            comment_free=None if span.truncated else span.without_comments())
    if amount.code is None:
        return None
    return PointsChange(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                        name=name, op=op, amount=amount)


def parse_points(raw: RawStatement, ctx: ParseContext) -> PointsDecl | PointsChange | None:
    """Either form (module docstring): a line with ``=`` changes a meter, one without
    declares meters. The wrong form for the depth is E230."""
    if raw.py is not None:
        return _parse_change(raw, ctx)
    if ctx.depth != 0:
        has_name = len(raw.tokens) > 1 and raw.tokens[1].kind == NAME
        ctx.error("E230", "change" if has_name else "need")
        return None
    return _parse_decl(raw, ctx)


register(StatementSpec(word=WORD_POINTS, placement="either", takes_block=False,
                       tail=TAIL_AFTER_EQUALS, parse=parse_points))
register_declaration(PointsDecl,
                     lambda node: "points:" + node.names[0])  # type: ignore[attr-defined]

__all__ = ["METERS_MAX", "METER_NAME_MAX", "MeterSpec", "OPS", "POINTS_LIMIT", "PointsChange",
           "PointsDecl", "STATEMENT_PARTS", "WORD_POINTS", "parse_points"]
