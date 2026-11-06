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
- **Change** (in a block): ``points <name> +=|-=|= <amount> ["<notice>"]`` → ``PointsChange``.
  The amount is eval-mode Python compiled as a value (F02's rules); the bindings pass checks
  it like a condition and checks the meter name (E233, ``bindings.py``).
- **Ranks** (F62 round 1): ``ranks "<label>" <at> …`` after the range and start, for every
  name on the line. ``ranks`` is a word here only when a quoted label follows it (the
  positional-words rule, ADR-0010), so a meter may still be called ``ranks``. Labels are plain
  text, 1–``RANK_LABEL_MAX`` code points, each used once (E412); thresholds are whole numbers
  inside the range, each higher than the last (E413); the shape is E411. ``rank`` is
  ``points.rank(…)``, so it can't be a meter name (E414).
- **Change notice** (F62 round 1): a plain ``"..."`` string after the amount is shown as a
  notice when the line runs (``split_notice``; text rules E415).

``MeterSpec`` lives here, not in ``runtime`` (07 I-1: ``script`` never imports ``runtime``);
``runtime/points.py`` re-exports it.
"""

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import Final

from engine.script.identity import register_declaration
from engine.script.lexer import EQUALS, NAME, STRING, SYMBOL, TAIL_AFTER_EQUALS, RawStatement
from engine.script.nodes import Node, PyCode, Statement, norm
from engine.script.pycheck import ROLE_VALUE, parse_tree
from engine.script.stage import NUMBER, TEXT, WORD, _chunks, _written
from engine.script.statements import ParseContext, StatementSpec, register
from engine.script.words import ROLE_METER, canonical_name, check_name

WORD_POINTS: Final = "points"
POINTS_LIMIT: Final = 1_000_000_000      # every bound, start, and value: |v| ≤ this
METERS_MAX: Final = 200                  # distinct meter names in a story (E235)
METER_NAME_MAX: Final = 64               # code points (07 I-2)
STATEMENT_PARTS: Final = frozenset(("highest", "to", "start", "rank"))   # never a meter name
OPS: Final = ("+=", "-=", "=")
WORD_RANKS: Final = "ranks"              # positional: a word only before a quoted label
WORD_RANK: Final = "rank"                # points.rank("hana"); E414 as a meter name
RANK_LABEL_MAX: Final = 40               # code points of one rank label
RANKS_MAX: Final = 20                    # ranks on one points line
NOTICE_MAX: Final = 200                  # code points of a change notice, as shown
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
    ranks: tuple[tuple[str, int], ...] = ()     # F62: (label, at), thresholds rising

    def clamp(self, value: int) -> int:
        return self.low if value < self.low else self.high if value > self.high else value

    def rank(self, value: int) -> str:
        """F62: the label of the highest rank at or below ``value``; "" below the first."""
        found = ""
        for label, at in self.ranks:
            if value < at:
                break
            found = label
        return found


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
    ranks: tuple[tuple[str, int], ...] = ()

    def specs(self) -> tuple[MeterSpec, ...]:
        return tuple(MeterSpec(name, self.low, self.high, self.start, self.ranged, self.ranks)
                     for name in self.names)


@dataclass(slots=True, kw_only=True)
class PointsChange(Statement):
    """``points <name> +=|-=|= <amount> ["<notice>"]`` in a block. Not a checkpoint;
    ``VOICE_TRANSPARENT`` (07 I-3). ``notice`` (F62) is the text shown when the line runs, as
    shown (``{{`` already ``{``), or None. It is not part of the identity, so rewording a
    notice keeps the line's sid."""

    name: str
    op: str
    amount: PyCode
    notice: str | None = None

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
    if canonical_name(written) == WORD_RANK:
        ctx.error("E414")
        return None
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
           and chunks[index].text not in ("to", "start")
           and not _ranks_at(chunks, index)):
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
    ranks: tuple[tuple[str, int], ...] = ()
    if index < count and chunks[index].kind == WORD and chunks[index].text == WORD_RANKS:
        found_ranks = _parse_ranks(raw, ctx, chunks[index + 1:], low, high)
        if found_ranks is None:
            return None
        ranks, index = found_ranks, count
    if index < count:
        ctx.error("E230", "left", _written(raw, chunks[index:]))
        return None
    if colon:
        ctx.error("E110", "colon", WORD_POINTS)
        return None
    return PointsDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                      names=tuple(names), low=low, high=high, start=start, ranged=ranged,
                      ranks=ranks)


def _ranks_at(chunks: list, index: int) -> bool:
    """The positional-words rule (ADR-0010): among the names, ``ranks`` starts the ranks only
    when a quoted label follows it; otherwise it is a meter name."""
    chunk = chunks[index]
    return (chunk.kind == WORD and chunk.text == WORD_RANKS and index + 1 < len(chunks)
            and chunks[index + 1].kind == TEXT)


def _label(raw: RawStatement, chunk) -> str | None:
    """The text of the STRING token at ``chunk``'s place (None: unclosed)."""
    for token in raw.tokens:
        if token.kind == STRING and (token.line, token.column) == (chunk.line, chunk.column):
            return None if token.unclosed else token.text
    return None


def plain_text_problem(text: str, limit: int) -> tuple[object, ...] | None:
    """F62's plain-text rule for rank labels and notices: not blank, at most ``limit`` code
    points as shown, no line break, and no text tag (``{{`` is a ``{``). The problem as
    message args (``("empty",)``, ``("long", count, limit)``, ``("newline",)``,
    ``("tags",)``), or None."""
    if not text.strip():
        return ("empty",)
    if "\n" in text or "\r" in text:
        return ("newline",)
    if "{" in text.replace("{{", ""):
        return ("tags",)
    shown = text.replace("{{", "{")
    if len(shown) > limit:
        return ("long", len(shown), limit)
    return None


def _parse_ranks(raw: RawStatement, ctx: ParseContext, chunks: list, low: int,
                 high: int) -> tuple[tuple[str, int], ...] | None:
    """``"<label>" <at>`` pairs after ``ranks`` (module docstring): E411 for the shape, E412
    for a label, E413 for a threshold, E232 for a number that isn't whole or is too big."""
    if not chunks:
        ctx.error("E411", "need")
        return None
    ranks: list[tuple[str, int]] = []
    for index in range(0, len(chunks), 2):
        first = chunks[index]
        if first.kind != TEXT:
            ctx.error("E411", "label", first.text)
            return None
        label = _label(raw, first)
        if label is None:
            return None                       # the lexer reported the unclosed quote
        problem = plain_text_problem(label, RANK_LABEL_MAX)
        if problem is not None:
            ctx.error("E412", *problem)
            return None
        label = label.replace("{{", "{")
        if index + 1 >= len(chunks) or chunks[index + 1].kind != NUMBER:
            ctx.error("E411", "at", label)
            return None
        at = _number(ctx, chunks[index + 1].text)
        if at is None:
            return None
        if any(label == other for other, _ in ranks):
            ctx.error("E412", "twice", label)
            return None
        if not low <= at <= high:
            ctx.error("E413", "range", label, at, low, high)
            return None
        if ranks and at <= ranks[-1][1]:
            ctx.error("E413", "rising", label, at, ranks[-1][0], ranks[-1][1])
            return None
        ranks.append((label, at))
        if len(ranks) > RANKS_MAX:
            ctx.error("E411", "many", RANKS_MAX)
            return None
    return tuple(ranks)


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
    source, length = span.source, span.length
    comment_free = None if span.truncated else span.without_comments()
    notice: str | None = None
    split = split_notice(comment_free) if comment_free is not None else None
    if split is not None:
        source, notice = split
        comment_free, length = source, len(source)
        problem = plain_text_problem(notice, NOTICE_MAX)
        if problem is not None:
            ctx.error("E415", *problem)
            return None
        notice = notice.replace("{{", "{")
    amount, _ = ctx.compile(source, line=span.line, column=span.column, mode="eval",
                            role=ROLE_VALUE, lambdas=span.lambdas, length=length,
                            comment_free=comment_free)
    if amount.code is None:
        return None
    return PointsChange(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                        name=name, op=op, amount=amount, notice=notice)


def split_notice(source: str) -> tuple[str, str] | None:
    """F62: ``(amount, notice)`` when ``source`` (the Python after ``=``, comments removed)
    ends with a plain ``"..."`` string that isn't part of the amount: the whole doesn't
    compile but the part before the string does. None otherwise (the amount is all of it)."""
    stripped = source.rstrip()
    if not stripped.endswith('"') or stripped.endswith('"""'):
        return None
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(stripped).readline)
                  if t.type not in _NOT_CODE]
    except (tokenize.TokenError, SyntaxError):
        return None
    if len(tokens) < 2 or tokens[-1].type != tokenize.STRING:
        return None
    last = tokens[-1]
    if not last.string.startswith('"') or last.start[0] != last.end[0]:
        return None                           # a prefix (f, r, b…) or a multi-line string
    lines = stripped.split("\n")
    row, col = last.start
    before = "\n".join(lines[:row - 1] + [lines[row - 1][:col]]).rstrip()
    if not before.strip() or _compiles(stripped) or not _compiles(before):
        return None
    tree = parse_tree(last.string, "eval")              # the string alone: nothing runs
    body = tree.body if isinstance(tree, ast.Expression) else None
    if not isinstance(body, ast.Constant) or type(body.value) is not str:
        return None
    return before, body.value


_NOT_CODE: Final = frozenset((tokenize.NEWLINE, tokenize.NL, tokenize.ENDMARKER,
                              tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT))


def _compiles(source: str) -> bool:
    """Whether ``source`` is one Python value (parsed only, as ``pycheck`` does)."""
    return parse_tree("(\n" + source + "\n)", "eval") is not None


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

__all__ = ["METERS_MAX", "METER_NAME_MAX", "MeterSpec", "NOTICE_MAX", "OPS", "POINTS_LIMIT",
           "PointsChange", "PointsDecl", "RANKS_MAX", "RANK_LABEL_MAX", "STATEMENT_PARTS",
           "WORD_POINTS", "WORD_RANK", "WORD_RANKS", "parse_points", "plain_text_problem",
           "split_notice"]
