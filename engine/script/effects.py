"""Transitions and screen effects in the script (F09 ``04-technical.md`` §3, §5.1;
``01-design.md`` SR-F09-01..06; load codes E192–E197).

Why this module exists: a ``with`` clause, ``shake``, ``flash``, and ``pause`` hold only
names, numbers, and colors as written, checked once at load, so the runtime never parses
text and the presentation gets plain values. Which transition a name means is decided at
launch, after the defines (``runtime/transitions.py``: E190, E191, E194's launch form).

- ``parse_with`` reads ``with <name> [length] [color]`` for F04's ``scene``, ``show``, and
  ``hide`` parsers (they keep E113 and E115). After the name each chunk is a NUMBER (the
  length, 0–30, else E192), a color word (``COLOR_WORDS``) or a quoted ``"#RRGGBB"`` (the
  color; another quoted text is E193), or anything else (E194's leftover form, ``07``
  I-8: an unquoted word is never E193, because load can't know a define's kind). A
  repeated length or color is E194, ``cut`` takes nothing, and the built-in ``dissolve``
  takes no color (E194). A length written ``0.5s`` or ``2s`` is E192's unit form, ``.5``
  its dot form.
- ``shake [size] [direction] [seconds]``, ``flash [color] [seconds]``, ``pause
  [seconds]``: story statements with no block; arguments in any order, each at most once
  (E195, E196, E197). Their identity keys leave the arguments out (ADR-0006).

Chunks come from F04's reader (``stage._chunks``), so a word is what the author sees as one
word. Imports ``stage`` (``stage`` imports this module only inside ``_with_part``).
"""

import re
from dataclasses import dataclass

from engine.core.constants import (
    COLOR_WORDS,
    FLASH_SECONDS_RANGE,
    PAUSE_SECONDS_RANGE,
    SHAKE_DIRECTIONS,
    SHAKE_SECONDS_RANGE,
    SHAKE_SIZES,
    TRANSITION_SECONDS_RANGE,
)
from engine.script.lexer import TAIL_SCRIPT, RawStatement
from engine.script.nodes import Statement
from engine.script.stage import NUMBER, OTHER, TEXT, WORD, _Chunk, _chunks
from engine.script.statements import ParseContext, StatementSpec, register
from engine.script.words import canonical_name

# The built-in transitions, in the fixed order of E190's list. ``define`` can't use these
# names (E198, ``checks.py``). The Could wipes would join here. F28 (C4, SR-F28-05):
# ``glitch``, which takes a length but no color, as ``dissolve``.
BUILTIN_TRANSITION_NAMES: tuple[str, ...] = ("cut", "dissolve", "fade", "glitch")

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")
_UNITS_RE = re.compile(r"(-?[0-9]+(?:\.[0-9]+)?)[A-Za-z]+")
_DOT_RE = re.compile(r"-?\.[0-9]+")


# --- Nodes (04 §3) ----------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WithClause:
    """``with <name> [length] [color]`` as loaded (SR-F09-01..03): ``name`` canonical, as
    written; ``seconds`` 0–30 or None (the transition's own length); ``color`` ``#RRGGBB``
    (upper case) or None. ``line``/``column`` are the ``with`` word's."""

    name: str
    seconds: float | None
    color: str | None
    line: int
    column: int


@dataclass(slots=True, kw_only=True)
class Shake(Statement):
    """``shake [small|medium|large] [horizontal|vertical] [seconds]`` (SR-F09-04). None
    means the ``[effects]`` default, resolved by the presentation."""

    size: str | None = None
    direction: str | None = None
    seconds: float | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("shake",)


@dataclass(slots=True, kw_only=True)
class Flash(Statement):
    """``flash [color] [seconds]`` (SR-F09-05): ``color`` ``#RRGGBB`` (upper case) or None
    (``[theme.effects] flash_color``); ``seconds`` the fade-back, or None."""

    color: str | None = None
    seconds: float | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("flash",)


@dataclass(slots=True, kw_only=True)
class Pause(Statement):
    """``pause [seconds]`` (SR-F09-06): None waits for an advance."""

    seconds: float | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("pause",)


# --- Values -------------------------------------------------------------------------------------

def _seconds(text: str) -> float:
    return float(text)


def _in(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _inner(chunk: _Chunk) -> str:
    """The text between a STRING chunk's quotes (an unclosed one has only its opening)."""
    text = chunk.text
    return text[1:-1] if len(text) >= 2 and text.endswith('"') else text[1:]


def _color(chunk: _Chunk) -> str | None:
    """The ``#RRGGBB`` a color chunk gives (a color word, or a quoted hex), else None."""
    if chunk.kind == WORD and chunk.text in COLOR_WORDS:
        return COLOR_WORDS[chunk.text]
    if chunk.kind == TEXT:
        inner = _inner(chunk)
        if _HEX_RE.fullmatch(inner):
            return inner.upper()
    return None


def _bad_text(ctx: ParseContext, chunk: _Chunk) -> None:
    """E193 for a quoted text that isn't ``"#RRGGBB"``."""
    inner = _inner(chunk)
    ctx.error("E193", "hex" if inner.startswith("#") else "name", inner)


def _length_problem(ctx: ParseContext, chunk: _Chunk, name: str) -> bool:
    """E192's unit or dot form for a chunk that is a length written wrongly; True if
    raised."""
    if chunk.kind in (WORD, OTHER):
        units = _UNITS_RE.fullmatch(chunk.text)
        if units is not None:
            ctx.error("E192", "units", units.group(1), chunk.text)
            return True
        if _DOT_RE.fullmatch(chunk.text):
            ctx.error("E192", "dot", name, chunk.text)
            return True
    return False


# --- with (SR-F09-01..03) ---------------------------------------------------------------------

def parse_with(ctx: ParseContext, values: list[_Chunk], keyword: _Chunk) -> WithClause | None:
    """The ``WithClause`` of ``with`` (``keyword``) and its ``values`` (the name first, at
    least one; F04's ``_with_part`` raised E113 and E115), or None with the error pending
    (E192, E193, E194)."""
    first = values[0]
    name = canonical_name(first.text) if first.kind == WORD else first.text
    args = values[1:]
    if name == "cut" and args:
        ctx.error("E194", "cut")
        return None
    seconds: float | None = None
    color: str | None = None
    for chunk in args:
        if chunk.kind == NUMBER:
            if seconds is not None:
                ctx.error("E194", "twice", name, "lengths")
                return None
            value = _seconds(chunk.text)
            if not _in(value, TRANSITION_SECONDS_RANGE):
                ctx.error("E192", "range", name, chunk.text)
                return None
            seconds = value
            continue
        found = _color(chunk)
        if found is not None:
            if color is not None:
                ctx.error("E194", "twice", name, "colors")
                return None
            if name in BUILTIN_TRANSITION_NAMES and name != "fade":
                ctx.error("E194", "color", name)
                return None
            color = found
            continue
        if chunk.kind == TEXT:
            _bad_text(ctx, chunk)
            return None
        if _length_problem(ctx, chunk, name):
            return None
        ctx.error("E194", "left", chunk.text, name)
        return None
    return WithClause(name=name, seconds=seconds, color=color, line=keyword.line,
                      column=keyword.column)


# --- shake, flash, pause (SR-F09-04..06) --------------------------------------------------------

def _arguments(raw: RawStatement, ctx: ParseContext, word: str) -> list[_Chunk] | None:
    """The chunks after the statement word, or None with E110's colon form pending."""
    chunks, colon = _chunks(raw)
    if colon:
        ctx.error("E110", "colon", word)
        return None
    return chunks


def parse_shake(raw: RawStatement, ctx: ParseContext) -> Shake | None:
    chunks = _arguments(raw, ctx, "shake")
    if chunks is None:
        return None
    size: str | None = None
    direction: str | None = None
    seconds: float | None = None
    for chunk in chunks:
        if chunk.kind == NUMBER:
            if seconds is not None:
                ctx.error("E195", "twice", "lengths")
                return None
            value = _seconds(chunk.text)
            if not _in(value, SHAKE_SECONDS_RANGE):
                ctx.error("E195", "length", chunk.text, False)
                return None
            seconds = value
        elif chunk.kind == WORD and chunk.text in SHAKE_SIZES:
            if size is not None:
                ctx.error("E195", "twice", "sizes")
                return None
            size = chunk.text
        elif chunk.kind == WORD and chunk.text in SHAKE_DIRECTIONS:
            if direction is not None:
                ctx.error("E195", "twice", "directions")
                return None
            direction = chunk.text
        else:
            ctx.error("E195", "bad", chunk.text, True)
            return None
    return Shake(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                 size=size, direction=direction, seconds=seconds)


def parse_flash(raw: RawStatement, ctx: ParseContext) -> Flash | None:
    chunks = _arguments(raw, ctx, "flash")
    if chunks is None:
        return None
    color: str | None = None
    seconds: float | None = None
    for chunk in chunks:
        if chunk.kind == NUMBER:
            if seconds is not None:
                ctx.error("E196", "twice", "lengths")
                return None
            value = _seconds(chunk.text)
            if not _in(value, FLASH_SECONDS_RANGE):
                ctx.error("E196", "bad", chunk.text, False)
                return None
            seconds = value
            continue
        found = _color(chunk)
        if found is not None:
            if color is not None:
                ctx.error("E196", "twice", "colors")
                return None
            color = found
        elif chunk.kind == TEXT:
            _bad_text(ctx, chunk)
            return None
        else:
            ctx.error("E196", "bad", chunk.text, True)
            return None
    return Flash(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                 color=color, seconds=seconds)


def parse_pause(raw: RawStatement, ctx: ParseContext) -> Pause | None:
    chunks = _arguments(raw, ctx, "pause")
    if chunks is None:
        return None
    seconds: float | None = None
    for chunk in chunks:
        if chunk.kind != NUMBER:
            ctx.error("E197", "bad", chunk.text, True)
            return None
        if seconds is not None:
            ctx.error("E197", "twice")
            return None
        value = _seconds(chunk.text)
        if not _in(value, PAUSE_SECONDS_RANGE):
            ctx.error("E197", "bad", chunk.text, False)
            return None
        seconds = value
    return Pause(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                 seconds=seconds)


for _spec in (
    StatementSpec(word="shake", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_shake),
    StatementSpec(word="flash", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_flash),
    StatementSpec(word="pause", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_pause),
):
    register(_spec)
del _spec

__all__ = ["BUILTIN_TRANSITION_NAMES", "Flash", "Pause", "Shake", "WithClause", "parse_flash",
           "parse_pause", "parse_shake", "parse_with"]
