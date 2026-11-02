"""The ``default`` statement (F03 SR-F03-01–03; ``04-technical.md`` §3.2, §6.1, §6.3).

``default name = value`` gives a story variable its starting value. It has the shape of a
``define`` (F02 SR-F02-66): top level only (E46b inside a block), a name and a Python value
continued over lines like a define value (compiled in ``eval`` mode, E82). A malformed line
is E49 with ``default`` in place of ``define``; a bad name is E60–E64 through ``check_name``
(E60's role word: ``a variable name``).

A line with another error still registers a valid name (SR-F03-02, as SR-F02-60), so later
uses don't give follow-on errors; a ``default`` inside a block registers nothing, because it
declares nothing. The whole-game checks (``checks.py``) then give E47b, E47c, and the default
order (E48/E48b).

The value is never run at load. The runtime evaluates the defaults in ``Program.defaults``
order on a new game and on a restore that lacks a name (SR-F03-04).

F12 (SR-F12-05, 07; ``04-technical.md`` §6): ``default persistent.<name> = value`` is a
``PersistentDefault``, evaluated once at launch (phase 2b), in reading order. More than one
name after ``persistent.`` is E184's first form, a leading ``_`` its second; a second
default of one name is its third (``checks.py``). The name must be one Python accepts (E64,
E61); statement words and the story's engine names are fine there, because ``persistent``
is a namespace of its own. A bare ``default persistent = …`` stays E62, and any other dotted
name stays E49.
"""

from engine.script.identity import register_declaration
from engine.script.lexer import TAIL_AFTER_EQUALS, RawStatement
from engine.script.nodes import Default, PersistentDefault
from engine.script.pycheck import ROLE_VALUE
from engine.script.statements import ParseContext, StatementSpec, assignment_target, register
from engine.script.words import ROLE_VARIABLE, canonical_name, check_name

WORD = "default"
PERSISTENT = "persistent"


def parse_default(raw: RawStatement, ctx: ParseContext) -> Default | PersistentDefault | None:
    written, dotted, has_equals = assignment_target(raw)
    if dotted is not None:
        parts = [part.strip() for part in dotted.split(".")]
        if canonical_name(parts[0]) == PERSISTENT:
            return _parse_persistent(raw, ctx, dotted, parts[1:], has_equals)
        ctx.error("E49", dotted, WORD)
        return None
    span = raw.py
    if written is None or not has_equals or span is None or \
            (not span.truncated and not span.source.strip()):
        ctx.error("E49", None, WORD)
        if written is not None and check_name(written) is None:
            _register(ctx, canonical_name(written))
        return None
    value, _ = ctx.compile(span.source, line=span.line, column=span.column, mode="eval",
                           role=ROLE_VALUE, lambdas=span.lambdas, length=span.length,
                           collect_names=True)
    problem = check_name(written, ROLE_VARIABLE)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    name = canonical_name(written)
    _register(ctx, name)
    if value.code is None:
        return None
    return Default(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                   name=name, value=value)


def _parse_persistent(raw: RawStatement, ctx: ParseContext, dotted: str, rest: list[str],
                      has_equals: bool) -> PersistentDefault | None:
    """``default persistent.<name> = value`` (F12 SR-F12-05, 07): E184 for more than one
    name after ``persistent.`` or a ``_`` name, E64/E61 for a name Python can't use, E49 for
    a line without ``=`` or a value. Only a top-level line makes a node."""
    if len(rest) != 1:
        ctx.error("E184", "dotted", dotted)
        return None
    written = rest[0]
    if written.startswith("_"):
        ctx.error("E184", "engine", written)
        return None
    span = raw.py
    if not has_equals or span is None or (not span.truncated and not span.source.strip()):
        ctx.error("E49", None, WORD)
        return None
    value, _ = ctx.compile(span.source, line=span.line, column=span.column, mode="eval",
                           role=ROLE_VALUE, lambdas=span.lambdas, length=span.length,
                           collect_names=True)
    problem = check_name(written, ROLE_VARIABLE)
    if problem is not None and problem[0] in ("E61", "E64"):
        ctx.error(problem[0], *problem[1])
        return None
    if value.code is None or ctx.depth != 0:
        return None
    return PersistentDefault(file=raw.file, line=raw.line, end_line=raw.end_line,
                             column=raw.column, name=canonical_name(written), value=value)


def _register(ctx: ParseContext, name: str) -> None:
    """Record a default's name for the whole-game checks, at the top level only."""
    if ctx.depth == 0:
        ctx.collected.default_defs.setdefault(name, []).append(ctx.place())


register(StatementSpec(word=WORD, placement="top", takes_block=False, tail=TAIL_AFTER_EQUALS,
                       parse=parse_default, misplaced="E46b"))
register_declaration(Default, lambda node: "default:" + node.name)  # type: ignore[attr-defined]
register_declaration(PersistentDefault,
                     lambda node: "default:persistent." + node.name)  # type: ignore[attr-defined]

__all__ = ["PERSISTENT", "WORD", "parse_default"]
