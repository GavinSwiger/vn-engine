"""The ``rollback`` statement (F14 ``04-technical.md`` §6; load codes E200–E204).

Why this module exists: an author controls how far the player can step back with one story
statement, ``rollback block|off|on|fixed``. The first three run (``runtime/rollback.py``);
``fixed`` is static script data: it marks the ``menu:`` or (F23 A3) the ``minigame`` line right
below it (``Menu.fixed``, ``Minigame.fixed``; ``attach_fixed``), so no ``GameState`` field is
needed.

- The tail is exactly one word: none is E200, a word not among the four is E201 (with a
  did-you-mean over them), more is E202, and a ``:`` is E203. Lines indented under a
  ``rollback`` line without a ``:`` are F02's indentation error, as for any line.
- ``attach_fixed`` runs once in the whole-game checks, next to F08's voice attachment: a
  ``rollback fixed`` whose next statement in the same block isn't a ``Menu`` or a
  ``Minigame`` is E204
  (the block's last statement included). Choice and ``if`` blocks are walked too.
- ``Rollback`` is ``VOICE_TRANSPARENT`` (``audio_checks``): a voice looks past it.
- ``ATTACH_SKIPS`` (F20 07 A4): predicates later features append at import; ``attach_fixed``
  looks past a statement any of them accepts (F20: a ``flowchart`` node mark, so
  ``rollback fixed`` / ``flowchart …`` / ``menu:`` works). ``statements.scoped_registry()``
  restores the list.
"""

from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass
from typing import Final, Literal

from engine.script.diagnostics import Diagnostic, DiagnosticSink
from engine.script.lexer import COLON, FWCOLON, NAME, STRING, TAIL_SCRIPT, RawStatement
from engine.script.limits import IDENTITY_YIELD_ITEMS
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.nodes import Label, Node, Say, Statement
from engine.script.statements import ParseContext, StatementSpec, _between, register
from engine.script.suggest import suggest

WORD_ROLLBACK: Final = "rollback"
ROLLBACK_WORDS: Final = ("block", "off", "on", "fixed")
# F20 07 A4: statements ``attach_fixed`` looks past (module docstring).
ATTACH_SKIPS: list[Callable[[Statement], bool]] = []


@dataclass(slots=True, kw_only=True)
class Rollback(Statement):
    """``rollback <word>``. Identity ``("rollback", word)`` (ADR-0006), like F08's
    statements; a ``fixed`` line never changes the menu's identity."""

    word: Literal["block", "off", "on", "fixed"]

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_ROLLBACK, self.word)


def parse_rollback(raw: RawStatement, ctx: ParseContext) -> Rollback | None:
    """One word after ``rollback`` (module docstring: E200–E203)."""
    tokens = raw.tokens[1:]
    colon = tokens[-1] if tokens and tokens[-1].kind in (COLON, FWCOLON) else None
    words = tokens[:-1] if colon is not None else tokens
    if not words:
        ctx.error("E200")
        return None
    first = words[0]
    written = first.text if first.kind in (NAME, STRING) else raw.chunk_at(first)
    if first.kind != NAME or first.text not in ROLLBACK_WORDS:
        ctx.error("E201", written, suggest(written, ROLLBACK_WORDS))
        return None
    if len(words) > 1:
        ctx.error("E202", first.text, _between(raw, words[1], colon))
        return None
    if colon is not None:
        ctx.error("E203")
        return None
    return Rollback(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                    word=first.text)  # type: ignore[arg-type]


# --- attach_fixed (04 §6.2) ---------------------------------------------------------------

def _blocks(nodes: Iterable[Node]) -> Iterable[tuple[Statement, ...]]:
    """Every statement block of every label, nested ones included (no recursion)."""
    for node in nodes:
        if isinstance(node, Label):
            stack = [node.block]
            while stack:
                block = stack.pop()
                yield block
                for stmt in block:
                    stack.extend(stmt.blocks())


def _next_form(stmt: Statement | None) -> str:
    """What follows a ``rollback fixed`` line, as E204's form: ``nothing``, ``say``, ``py``,
    or the statement word (the first part of its identity key)."""
    if stmt is None:
        return "nothing"
    if isinstance(stmt, Say):
        return "say"
    return stmt.identity_key()[0]


def iter_attach_fixed(nodes: Iterable[Node], sink: DiagnosticSink
                      ) -> Generator[None, None, None]:
    """Set ``fixed`` on the menu or minigame (F23 A3) right below each ``rollback fixed``;
    E204 where there is none. Yields every ``IDENTITY_YIELD_ITEMS`` statements."""
    count = 0
    for block in _blocks(nodes):
        for index, stmt in enumerate(block):
            count += 1
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield
            if not isinstance(stmt, Rollback) or stmt.word != "fixed":
                continue
            at = index + 1
            while at < len(block) and any(skip(block[at]) for skip in ATTACH_SKIPS):
                at += 1
            nxt = block[at] if at < len(block) else None
            if isinstance(nxt, (Menu, Minigame)):
                nxt.fixed = True
                continue
            line = nxt.line if nxt is not None else None
            sink.add(Diagnostic("E204", stmt.file, stmt.line, None, (_next_form(nxt), line),
                                stmt=stmt.line))


register(StatementSpec(word=WORD_ROLLBACK, placement="story", takes_block=False,
                       tail=TAIL_SCRIPT, parse=parse_rollback))

__all__ = ["ATTACH_SKIPS", "ROLLBACK_WORDS", "Rollback", "iter_attach_fixed", "parse_rollback"]
