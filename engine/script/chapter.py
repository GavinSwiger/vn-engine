"""The ``chapter`` statement (F18 SPEC §3; load codes E221–E223, E222's name form from 07 I-2).

Why this module exists: a chapter line holds only a name, plain texts, a number, and F09's
``with``, all checked once at load, so the runtime never parses text and the card gets
plain values. ``card_args`` reads ``<name> ["heading"] "title" [seconds] [with ...]`` with
the codes it is given, so F19's ``ending`` reuses it with its own (F19 ``07`` I-11).

- The name follows script-language §6 (``check_name``: E60–E64) and is at most
  ``CHAPTER_NAME_MAX`` code points (E222's name form), so every saved chapter name passes
  ``GameState.from_json`` (07 I-2). Chapters have their own namespace: duplicates (E220)
  and the total (E224) are the whole-game checks' (``checks.py``, ``Collected.chapter_defs``).
- One text is the title; two are heading and title. Texts are dialogue strings (quotes and
  escapes as for a line), shown as written: ``{{`` is ``{``, any other ``{`` is E222's tag
  form (F30: a ``{username}`` tag is E302's ``title_card`` form first, for both cards).
  Heading 1–60 and title 1–120 code points (E222).
- ``seconds`` 0–30 (E223; ``5s`` and ``.5`` are E192's unit and dot forms); 0 shows no card.
- ``with`` is F09's clause (``stage._with_part``: E113, E115, then E192–E194), last.

Chunks come from F04's reader (``stage._chunks``); a quoted chunk's shown text is its STRING
token's.
"""

from dataclasses import dataclass

from engine.script.effects import WithClause, _length_problem
from engine.script.lexer import STRING, TAIL_SCRIPT, RawStatement
from engine.script.limits import (CHAPTER_HEADING_MAX, CHAPTER_NAME_MAX,
                                  CHAPTER_SECONDS_RANGE, CHAPTER_TITLE_MAX)
from engine.script.nodes import Chapter
from engine.script.stage import NUMBER, TEXT, WORD, _Chunk, _chunks, _with_part, _written
from engine.script.statements import ParseContext, StatementSpec, register
from engine.script.texttags import has_username_tag
from engine.script.words import canonical_name, check_name


@dataclass(frozen=True, slots=True)
class CardCodes:
    """The codes ``card_args`` reports with (F19 passes its own). ``shape``: forms ``need``,
    ``texts`` (count), ``left`` (written); ``text``: forms ``empty`` (which), ``long``
    (which, count, limit), ``tags``, ``name`` (which, count, limit); ``seconds``: the
    written length; ``word``: the statement word (E110's colon form)."""

    shape: str
    text: str
    seconds: str
    word: str


CHAPTER_CODES = CardCodes(shape="E221", text="E222", seconds="E223", word="chapter")


@dataclass(frozen=True, slots=True)
class CardArgs:
    """What a card line gives: the canonical name, the texts as shown, the hold (None: the
    default), and F09's ``with``."""

    name: str
    heading: str | None
    title: str
    seconds: float | None
    with_clause: WithClause | None


def _shown(text: str) -> str | None:
    """``text`` as shown (``{{`` → ``{``), or None when it holds any other ``{``."""
    out: list[str] = []
    start = 0
    while True:
        at = text.find("{", start)
        if at < 0:
            out.append(text[start:])
            return "".join(out)
        if not text.startswith("{{", at):
            return None
        out.append(text[start:at + 1])
        start = at + 2


def _text(ctx: ParseContext, codes: CardCodes, which: str, value: str,
          limit: int) -> str | None:
    if has_username_tag(value):                         # F30 (04 §5.3): before E222/E242
        ctx.error("E302", "title_card")
        return None
    shown = _shown(value)
    if shown is None:
        ctx.error(codes.text, "tags")
        return None
    if not shown.strip():
        ctx.error(codes.text, "empty", which)
        return None
    if len(shown) > limit:
        ctx.error(codes.text, "long", which, len(shown), limit)
        return None
    return shown


def card_args(raw: RawStatement, ctx: ParseContext,
              codes: CardCodes = CHAPTER_CODES) -> CardArgs | None:
    """``<name> ["heading"] "title" [seconds] [with ...]`` after the statement word, or None
    with the first error pending (module docstring)."""
    chunks, colon = _chunks(raw)
    if not chunks or chunks[0].kind == TEXT:
        ctx.error(codes.shape, "need")
        return None
    first = chunks[0]
    problem = check_name(first.text) if first.kind == WORD else ("E64", (first.text,))
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    name = canonical_name(first.text)
    if len(name) > CHAPTER_NAME_MAX:
        ctx.error(codes.text, "name", "name", len(name), CHAPTER_NAME_MAX)
        return None
    index = 1
    texts: list[_Chunk] = []
    while index < len(chunks) and chunks[index].kind == TEXT:
        texts.append(chunks[index])
        index += 1
    if not texts:
        ctx.error(codes.shape, "need")
        return None
    if len(texts) > 2:
        ctx.error(codes.shape, "texts", len(texts))
        return None
    strings = {(t.line, t.column): t.text for t in raw.tokens if t.kind == STRING}
    values = [strings.get((c.line, c.column), "") for c in texts]
    heading: str | None = None
    if len(values) == 2:
        heading = _text(ctx, codes, "heading", values[0], CHAPTER_HEADING_MAX)
        if heading is None:
            return None
    title = _text(ctx, codes, "title", values[-1], CHAPTER_TITLE_MAX)
    if title is None:
        return None
    seconds: float | None = None
    if index < len(chunks) and chunks[index].kind == NUMBER:
        written = chunks[index].text
        value = float(written)
        low, high = CHAPTER_SECONDS_RANGE
        if not low <= value <= high:
            ctx.error(codes.seconds, written)
            return None
        seconds = value
        index += 1
    with_clause: WithClause | None = None
    if index < len(chunks):
        chunk = chunks[index]
        if chunk.kind == WORD and chunk.text == "with":
            with_clause = _with_part(ctx, raw, chunks, index)
            if with_clause is None:
                return None
        else:
            if seconds is None and _length_problem(ctx, chunk, codes.word):
                return None
            ctx.error(codes.shape, "left", _written(raw, chunks[index:]))
            return None
    if colon:
        ctx.error("E110", "colon", codes.word)
        return None
    return CardArgs(name, heading, title, seconds, with_clause)


def parse_chapter(raw: RawStatement, ctx: ParseContext) -> Chapter | None:
    args = card_args(raw, ctx, CHAPTER_CODES)
    if args is None:
        return None
    ctx.collected.chapter_defs.setdefault(args.name, []).append(ctx.place())
    return Chapter(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                   name=args.name, heading=args.heading, title=args.title,
                   seconds=args.seconds, with_clause=args.with_clause)


register(StatementSpec(word="chapter", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                       parse=parse_chapter))

__all__ = ["CHAPTER_CODES", "CardArgs", "CardCodes", "card_args", "parse_chapter"]
