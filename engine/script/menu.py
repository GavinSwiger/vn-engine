"""The ``menu`` statement (F07 ``04-technical.md`` §6; ``01-design.md`` §5, SR-F07-01–05).

Why this module exists: a menu has its own child grammar (an optional ``voice``, an optional
question line, then 1–6 choices, each with a story block), so it reads its body itself
through F02's block-parser hook (``StatementSpec.block_parser``, C7) instead of the plain
``block_of``. The result is one ``Menu`` node: its question is a normal ``Say`` that shares
the menu's identity and is never walked (ADR-0006 addendum 1), and each ``Choice`` holds a
per-menu key and a block that ``Statement.blocks()`` exposes to every walk.

Codes: E12 (``menu`` and ``choice`` forms), E172–E174, E176, E177 here; E175 in
``texttags.parse(choice=True)``; F02's own codes for the question, conditions, and blocks.

F51 (timed choices, ``04-technical.md`` §7.1): ``menu time N:`` (``Menu.time``) and one
``"..." timeout:`` choice (``Choice.timeout``), both outside the identity (SR-F51-05);
E368 (the header), E369 (the marking), E370 (the timeout choice's ``if``) here.
"""

import re

from collections.abc import Generator
from dataclasses import dataclass
from typing import Final

from engine.script.audio import Voice
from engine.script.diagnostics import Diagnostic
from engine.script.identity import statement_hash
from engine.script.lexer import (
    COLON,
    FWCOLON,
    HEAD_ERROR,
    HEAD_NARRATION,
    HEAD_WORD,
    NAME,
    RANK_BLOCK,
    TAIL_SCRIPT,
    RawStatement,
    Token,
)
from engine.script.limits import SCRIPT_MAX_BLOCK_DEPTH
from engine.script.nodes import PyCode, Say, Statement, norm
from engine.script.statements import (
    ParseContext,
    StatementSpec,
    condition_of,
    line_body,
    register,
)
from engine.script.texttags import EMPTY_TEXT, TaggedText
from engine.script.words import STATEMENT_WORDS

MENU_MAX_CHOICES: Final = 6               # SR-F07-04 (E173)
MENU_TIME_MIN: Final = 1.0                 # SR-F51-01 (E368)
MENU_TIME_MAX: Final = 60.0
_TIME_RE: Final = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_FOUND_MAX: Final = 30                     # E368's {found}: the text cut to 30 characters

# The phases of a menu body (04 §6.3).
_START, _VOICE, _QUESTION, _CHOICES = range(4)
# What a line directly in a menu body is.
_CHOICE, _VOICE_LINE, _LINE, _OTHER, _BROKEN = range(5)


@dataclass(slots=True, kw_only=True)
class Choice:
    """One choice: not a ``Statement`` (no sid, never a position). ``text`` is as written
    (escapes applied), ``body`` its parsed tags (the choice subset), ``key`` its identity in
    the menu (``<12 hex>`` or ``<12 hex>~n`` for the n-th equal text, ADR-0006 addendum 1)."""

    text: str
    body: TaggedText = EMPTY_TEXT
    condition: PyCode | None = None
    line: int
    column: int
    key: str = ""
    block: tuple[Statement, ...] = ()
    timeout: bool = False        # F51: what time running out picks; not part of the key


@dataclass(slots=True, kw_only=True)
class Menu(Statement):
    """``menu:``. ``voice`` is the ``voice`` line above the question (attached to it by
    ``audio_checks``); ``question`` the question line, whose sid, label, and path are the
    menu's (``inner``); ``choices`` in script order. ``fixed`` (F14 A5): a ``rollback
    fixed`` line is right above it, set only by ``script/rollback.attach_fixed``; static, and
    not part of the identity key."""

    voice: Voice | None = None
    question: Say | None = None
    choices: tuple[Choice, ...] = ()
    fixed: bool = False
    # F51: ``menu time N:``. ``time`` in seconds (None: untimed), ``time_text`` the number as
    # written (Studio and W257 echo it); neither is part of the identity key (SR-F51-05).
    time: float | None = None
    time_text: str = ""

    def identity_key(self) -> tuple[str, ...]:
        question = self.question
        if question is None:
            return ("menu", "", "")
        return ("menu", question.speaker or "", norm(question.text))

    def blocks(self) -> tuple[tuple[Statement, ...], ...]:
        return tuple(choice.block for choice in self.choices)

    def inner(self) -> tuple[Statement, ...]:
        return (self.question,) if self.question is not None else ()


def choice_key(text: str) -> str:
    """The hash part of a choice's key (``K(t)`` of F07 06 §0.4)."""
    return statement_hash(("choice", norm(text)))


def assign_keys(choices: list[Choice]) -> None:
    """Each choice's key: its hash, with ``~n`` for the n-th equal one in the menu."""
    counts: dict[str, int] = {}
    for choice in choices:
        h = choice_key(choice.text)
        n = counts[h] = counts.get(h, 0) + 1
        choice.key = h if n == 1 else f"{h}~{n}"


# --- The header (04 §6.2) -----------------------------------------------------------------------

def parse_menu(raw: RawStatement, ctx: ParseContext) -> Menu:
    """``menu`` then ``:`` (E177 for anything else; no colon is E31b). F51: ``menu time N:``
    with N a number from 1 to 60 (E368's three forms). The node is returned even with an
    error, so the body is still checked (the block parser drops it)."""
    tokens = raw.tokens[1:]
    colon = tokens[-1] if tokens and tokens[-1].kind in (COLON, FWCOLON) else None
    before = tokens[:-1] if colon is not None else tokens
    menu = Menu(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column)
    if before and before[0].kind == NAME and before[0].text == "time":
        if not _parse_time(raw, ctx, menu, before[0], colon):
            return menu
    elif before:
        ctx.error("E177")
        return menu
    if colon is None or colon.kind == FWCOLON:
        ctx.error("E31b", "menu", "")
    return menu


def _parse_time(raw: RawStatement, ctx: ParseContext, menu: Menu, word: Token,
                colon: Token | None) -> bool:
    """F51 (04 §7.1 step 1): the text from the end of ``time`` up to the colon (or the
    comment, or the line end). Sets ``menu.time``; False after an E368."""
    text = raw.texts.get(word.line, "")
    start = word.column - 1 + len(word.text)
    if colon is not None and colon.line == word.line:
        rest = text[start:colon.column - 1].strip()
    else:
        rest = raw.rest_from(word.line, start + 1)
    if not rest:
        ctx.error("E368", 1)
        return False
    first, *more = rest.split()
    value = float(first) if _TIME_RE.fullmatch(first) else 0.0
    if not MENU_TIME_MIN <= value <= MENU_TIME_MAX:
        ctx.error("E368", 2, rest[:_FOUND_MAX])
        return False
    if more:
        ctx.error("E368", 3, first)
        return False
    menu.time = value
    menu.time_text = first
    return True


# --- One choice (04 §6.3) --------------------------------------------------------------------------

def parse_choice(raw: RawStatement, ctx: ParseContext) -> Choice | None:
    """``"text":`` or ``"text" if condition:``. An unclosed quote is F02's error (already
    pending); blank text is E176; the condition is read like ``if``'s (E39, E22, Python
    errors); without one only ``:`` may follow the text (E53); then the text's tags in
    choice mode (E160–E167, E175). F51: ``"text" timeout:`` marks the timeout choice; an
    ``if`` after ``timeout`` is E370, and that choice is still returned (marked, with no
    condition), so no E369 follows."""
    token = raw.tokens[0]
    if token.unclosed:
        return None
    if not token.text.strip():
        ctx.error("E176")
        return None
    condition: PyCode | None = None
    timeout = False
    if raw.py is not None:
        condition = condition_of(raw, ctx, keyword="if")
        if condition is None:
            return None
    else:
        after = raw.tokens[1:]
        if len(after) > 1 and after[0].kind == NAME and after[0].text == "timeout":
            if after[1].kind == NAME and after[1].text == "if":
                ctx.error("E370")                  # still returned, marked: no E369 cascade
                timeout = True
                after = after[-1:]
            elif len(after) == 2:                  # "x" timeout: (a fullwidth colon as today)
                timeout = after[1].kind == COLON
                after = after[1:]
        if len(after) != 1 or after[0].kind != COLON:
            first = after[0]
            ctx.error("E53", raw.rest_from(first.line, first.column), line=first.line,
                      column=first.column)
            return None
    body = line_body(raw, ctx, token, choice=True)
    if body is None:
        return None
    return Choice(text=token.text, body=body, condition=condition, line=raw.line,
                  column=raw.column, timeout=timeout)


def _no_node(raw: RawStatement, ctx: ParseContext) -> None:
    return None


def _kind(raw: RawStatement) -> int:
    head = raw.head
    if head == HEAD_NARRATION:
        return _CHOICE if raw.ends_with_colon or raw.py is not None else _LINE
    if head == HEAD_WORD:
        if raw.word == "voice":
            return _VOICE_LINE
        return _OTHER if raw.word in STATEMENT_WORDS else _LINE
    if head == HEAD_ERROR:
        return _BROKEN
    return _OTHER                                                # $ lines


# --- The body (04 §6.3) -----------------------------------------------------------------------------

def parse_menu_body(api, raw: RawStatement, menu: Menu, depth: int, own_error: bool,
                    widths: tuple[int, ...]) -> Generator[None, None, None]:
    """Read the menu's body (``api`` is F02's ``BlockApi``): START → VOICE → QUESTION →
    CHOICES. Each choice's block is an ordinary block (a nested ``menu`` included). E172 or
    E173 at the menu's line counts every line shaped like a choice, so a choice with an
    error of its own still counts."""
    ctx = api.ctx
    reader = api.reader
    w = raw.width
    nxt = yield from api.peek()
    if nxt is None or nxt.width <= w:
        if not own_error:
            api.empty_block(raw, "menu", nxt)
        return
    if depth + 1 > SCRIPT_MAX_BLOCK_DEPTH:
        nxt.error("E15", rank=RANK_BLOCK)
        yield from api.skip_deeper(w, quiet=False)
        return
    block_w = nxt.width
    body_widths = widths + (block_w,)
    inner = depth + 1
    phantom: int | None = None
    phase = _START
    choices: list[Choice] = []
    shaped = 0                                    # lines shaped like a choice (E172, E173)
    sources: dict[int, str | None] = {}           # F51 E369: each choice line's text
    while True:
        line = yield from api.peek()
        if line is None or line.width <= w:
            break
        phantom = api.check_width(line, block_w, phantom, body_widths)
        reader.next()
        ctx.statement_count += 1
        kind = _kind(line)
        after = yield from api.peek()
        deeper = after is not None and after.width > line.width
        if kind == _CHOICE and (line.py is None or line.py.colon is not None):
            shaped += 1
            phase = _CHOICES
            choice, error = api.parse_line(line, inner, parse_choice)
            if deeper:
                if depth + 2 > SCRIPT_MAX_BLOCK_DEPTH:
                    after.error("E15", rank=RANK_BLOCK)
                    yield from api.skip_deeper(line.width, quiet=False)
                else:
                    block = yield from api.parse_block(line.width, after.width, depth + 2,
                                                       body_widths + (after.width,))
                    if choice is not None:
                        choice.block = tuple(s for s in block if isinstance(s, Statement))
            elif not error:
                api.empty_block(line, "choice", after)
            if choice is not None:
                choices.append(choice)  # type: ignore[arg-type]
                sources[line.line] = line.texts.get(line.line)
        elif kind == _CHOICE or (kind == _LINE and deeper):
            # Text with a condition but no ":", or a line with lines under it: a choice
            # without its ":" (E174 form 2, 07 I-4 O4); its block is skipped quietly.
            shaped += 1
            _reject(api, line, inner, 2)
            if deeper:
                yield from api.skip_deeper(line.width, quiet=True)
        elif kind == _VOICE_LINE and phase == _START:
            node, _ = api.parse_line(line, inner)
            menu.voice = node if isinstance(node, Voice) else None
            phase = _VOICE
        elif kind == _LINE and phase in (_START, _VOICE):
            node, _ = api.parse_line(line, inner)
            menu.question = node if isinstance(node, Say) else None
            phase = _QUESTION
        elif kind == _LINE and phase == _CHOICES:
            _reject(api, line, inner, 1)
        elif kind == _BROKEN:
            api.parse_line(line, inner)            # its own error (E30d, E50, E51)
            if deeper:
                yield from api.skip_deeper(line.width, quiet=True)
        else:                                      # a second question, voice, any statement
            _reject(api, line, inner, 3)
            if line.ends_with_colon and deeper:
                yield from api.skip_deeper(line.width, quiet=True)
        if api.due():
            yield
    if shaped == 0:
        _menu_error(api, raw, "E172", ())
    elif shaped > MENU_MAX_CHOICES:
        _menu_error(api, raw, "E173", (shaped,))
    elif not own_error:
        _check_timeout(api, raw, menu, choices, shaped, sources)
    assign_keys(choices)
    menu.choices = tuple(choices)


def _check_timeout(api, raw: RawStatement, menu: Menu, choices: list[Choice], shaped: int,
                   sources: dict[int, str | None]) -> None:
    """F51 E369 (04 §7.1 step 3, 07 I-3): a marked choice in an untimed menu (at that
    choice), a timed menu with none (at the menu; skipped when a broken choice line may have
    been the marked one), or a second marked choice (at it). A clean timed menu is kept for
    W257."""
    marked = [choice for choice in choices if choice.timeout]
    if menu.time is None:
        if marked:
            _choice_error(api, marked[0], "E369", (1,), sources)
        return
    if not marked:
        if len(choices) == shaped:
            _menu_error(api, raw, "E369", (2,))
        return
    if len(marked) > 1:
        _choice_error(api, marked[1], "E369", (3, len(marked)), sources)
        return
    api.ctx.collected.timed_menus.append(menu)


def _choice_error(api, choice: Choice, code: str, args: tuple,
                  sources: dict[int, str | None]) -> None:
    api.ctx.sink.add(Diagnostic(code, api.file, choice.line, None, args,
                                source_line=sources.get(choice.line), stmt=choice.line))


def _reject(api, line: RawStatement, depth: int, form: int) -> None:
    """E174 (``form``) for a line that can't go directly in a menu; the line isn't parsed,
    so its first error is a line error of the reader or this one."""
    line.error("E174", (form,))
    api.parse_line(line, depth, _no_node)


def _menu_error(api, raw: RawStatement, code: str, args: tuple) -> None:
    api.ctx.sink.add(Diagnostic(code, api.file, raw.line, None, args,
                                source_line=raw.texts.get(raw.line), stmt=raw.line))


register(StatementSpec(word="menu", placement="story", takes_block=True, tail=TAIL_SCRIPT,
                       parse=parse_menu, block_parser=parse_menu_body))

__all__ = ["Choice", "MENU_MAX_CHOICES", "MENU_TIME_MAX", "MENU_TIME_MIN", "Menu", "assign_keys",
           "choice_key", "parse_choice", "parse_menu", "parse_menu_body"]
