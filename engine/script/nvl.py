"""The ``nvl`` statement (F17 ``04-technical.md`` §5.2, §6; ``01-design.md`` §5.3, §5.4).

Why this module exists: an author switches a passage to full-screen text with one story
statement, ``nvl on|off|clear``, which the runtime runs (``runtime/nvl.py``). The mode is not
lexical (no block form), so the node is one word and nothing else.

- The tail is exactly one of ``on``, ``off``, ``clear``, in lower case (SR-F17-01): none, or
  another word, is **E210** (a capitalised one gets the lower-case form, a near one a
  did-you-mean); a ``:`` is **E211**'s colon form (this error stands in for F02's E12); a
  second item is **E211**, ``with`` … its transition form (quoting from ``with`` to the end
  of the line as written), anything else its "takes nothing else" form. One error per
  statement, in that order.
- Placement needs nothing here: ``menu:`` bodies refuse non-choices (F07's E174).
- Identity ``("nvl", action)`` (ADR-0006), like ``scene``. Not a checkpoint type and never a
  position. ``Nvl`` is ``VOICE_TRANSPARENT`` (``audio_checks``): a voice looks past it.
- ``on``, ``off`` and ``clear`` are not reserved (SR-F17-04): they are only arguments.

Its Studio doc is registered next to its statement spec (F45 07 O-2, I-5).
"""

from dataclasses import dataclass
from typing import Final, Literal

from engine.script.lexer import COLON, FWCOLON, NAME, TAIL_SCRIPT, RawStatement, Token
from engine.script.nodes import Statement
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, StatementSpec, _between, register
from engine.script.suggest import suggest

WORD_NVL: Final = "nvl"
NVL_ACTIONS: Final = ("on", "off", "clear")

Action = Literal["on", "off", "clear"]


@dataclass(slots=True, kw_only=True)
class Nvl(Statement):
    """``nvl on|off|clear``. Identity ``("nvl", action)``."""

    action: Action

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_NVL, self.action)


def _written(raw: RawStatement, items: list[Token], index: int) -> str:
    """Item ``index`` of the tail as written: a word's text, else its source up to the next
    item (a quoted text is one item)."""
    token = items[index]
    if token.kind == NAME:
        return token.text
    stop = items[index + 1] if index + 1 < len(items) else None
    return _between(raw, token, stop)


def parse_nvl(raw: RawStatement, ctx: ParseContext) -> Nvl | None:
    """``nvl`` and one action word (module docstring: E210, E211)."""
    tokens = raw.tokens[1:]
    colon = tokens[-1] if tokens and tokens[-1].kind in (COLON, FWCOLON) else None
    items = tokens[:-1] if colon is not None else tokens
    if not items:
        ctx.error("E210", "needs")
        return None
    first = items[0]
    if first.kind != NAME or first.text not in NVL_ACTIONS:
        if first.kind == NAME and first.text.lower() in NVL_ACTIONS:
            ctx.error("E210", "case", first.text.lower())
        else:
            written = _written(raw, items, 0)
            ctx.error("E210", "unknown", written, suggest(written, NVL_ACTIONS))
        return None
    action = first.text
    if colon is not None or raw.ends_with_colon:
        ctx.error("E211", "colon", action)
        return None
    if len(items) > 1:
        second = items[1]
        if second.kind == NAME and second.text == "with":
            ctx.error("E211", "with", action, _between(raw, second, None))
        else:
            ctx.error("E211", "extra", action, _written(raw, items, 1))
        return None
    return Nvl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
               action=action)  # type: ignore[arg-type]


register(StatementSpec(word=WORD_NVL, placement="story", takes_block=False,
                       tail=TAIL_SCRIPT, parse=parse_nvl))
register_doc(StatementDoc(
    "nvl", "Full-screen text", "Text", "nvl on|off|clear",
    "Shows the lines that follow as a full page of text (on), goes back to the text box "
    "(off), or starts a new, empty page (clear).",
    'nvl on\n"The festival comes once a year."\nnvl off', "nvl (full-screen text)", "F17",
    fields=("on",)))

__all__ = ["NVL_ACTIONS", "Nvl", "parse_nvl"]
