"""The ``ending``, ``lock``, and ``unlock`` statements (F19 ``04-technical.md`` §4, §6.1;
``07`` I-5, I-6, I-12).

Why this module exists: endings and routes are records the engine keeps across
playthroughs, so their names must be known at load (E241–E246) and the runtime gets plain
values. Three words, each ``placement="either"`` so the parser can give F19's own codes at
the wrong depth instead of E40 or a ``misplaced`` code:

- ``ending <name> ["heading"] "title" [seconds] [with ...]`` inside a label → ``Ending``. The
  line after the word is F18's card line (``chapter.card_args`` with ``ENDING_CODES``):
  E240 for its shape, E242 for the name, texts, and length, F09's E190–E194 for ``with``.
  At the top level it is E240's ``top`` form.
- ``lock <target> …`` / ``unlock <target> …``: the second word picks a row of
  ``LOCK_TARGETS`` (07 I-6), a ``LockTarget(word, top, block, body)``. ``top`` reads the
  depth-0 form of both verbs (None: E244's ``top`` form; F21 07 I-3), ``block`` the in-label form, ``body`` an
  optional declaration block (the ``lock`` spec's ``block_parser`` hands it the block; with
  none it falls back to the block parser's ``block_of``). Each row returns its own node
  type and gives the messages that depend on its target; the shared code reads only the
  second word. F19's rows: ``route`` (``lock route <label> "Title" [until a, b]`` at the
  top level → ``RouteDecl``; ``lock|unlock route <name>`` in a label → ``Lock``) and
  ``ending`` (``lock ending <name>`` in a label → ``Lock``; ``unlock ending`` is E244).

``route`` and ``until`` are read only in these positions and stay usable as names.

**Registration (07 I-5).** ``register_words()`` adds the three ``StatementSpec``s, their
``StatementDoc``s, and F19's ``LOCK_TARGETS`` rows. Since F19's step 3 (the executors, in
``runtime/endings.py``, registered by ``interpreter.py``) it runs once at import, through
the one line in ``script/__init__.py``; calling it again does nothing, so the step-1 tests
that call it inside ``statements.scoped_registry()`` still run.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

from engine.script.chapter import CardCodes, _shown, card_args
from engine.script.effects import WithClause
from engine.script.identity import register_declaration
from engine.script.lexer import NAME, STRING, SYMBOL, TAIL_SCRIPT, RawStatement
from engine.script.limits import CHAPTER_TITLE_MAX
from engine.script.nodes import Node, Statement
from engine.script.stage import TEXT, WORD, _Chunk, _chunks
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, StatementSpec, get_spec, register
from engine.script.words import canonical_name, check_name

WORD_ENDING: Final = "ending"
WORD_LOCK: Final = "lock"
WORD_UNLOCK: Final = "unlock"
WORD_UNTIL: Final = "until"
ENDINGS_MAX: Final = 1_000                # ending lines in a story (E246)
ROUTES_MAX: Final = 1_000                 # route declarations in a story (E246)
NAME_MAX: Final = 64                      # code points, ending and route names (E242)
ROUTE_TITLE_MAX: Final = CHAPTER_TITLE_MAX            # 120 code points (E242)
UNTIL_MAX: Final = 32                     # names after until (E243)

# The engine's views ``persistent.endings`` and ``persistent.routes`` (04 §7.4): a default
# of either is E245 at load, and so is any write or change the script shows (bindings.py).
PERSISTENT_VIEWS: Final[frozenset[str]] = frozenset({"endings", "routes"})

ENDING_CODES = CardCodes(shape="E240", text="E242", seconds="E242", word=WORD_ENDING)


# --- Nodes (04 §4) ----------------------------------------------------------------------------

@dataclass(slots=True, kw_only=True)
class Ending(Statement):
    """``ending <name> ["heading"] "title" [seconds] [with ...]``. ``name`` is canonical
    (1–64 code points, unique, E241); texts are plain as shown (``{{`` is ``{``);
    ``seconds`` None is the default (3.0), 0 no card. Not ``VOICE_TRANSPARENT`` and never a
    checkpoint (07 I-12)."""

    name: str
    heading: str | None = None
    title: str
    seconds: float | None = None
    with_clause: WithClause | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("ending", self.name)


@dataclass(slots=True, kw_only=True)
class RouteDecl(Node):
    """``lock route <label> "Title" [until a, b]`` at the top level: a route that starts
    locked at that label. ``until`` () means it opens only through ``unlock route``. A
    declaration, sid ``"route:" + name`` (never a position, 07 I-12)."""

    name: str
    title: str
    until: tuple[str, ...] = ()


@dataclass(slots=True, kw_only=True)
class Lock(Statement):
    """``lock|unlock <kind> <name>`` in a label. ``kind`` is a ``LOCK_TARGETS`` word (str, so
    later rows need no change here). ``VOICE_TRANSPARENT``; not a checkpoint."""

    unlock: bool
    kind: str
    name: str

    def identity_key(self) -> tuple[str, ...]:
        return ("unlock" if self.unlock else "lock", self.kind, self.name)


# --- The lock/unlock target table (07 I-6) ------------------------------------------------------

# A row parser: (raw, ctx, unlock, chunks after the target word, trailing colon) → node.
RowParser = Callable[[RawStatement, ParseContext, bool, list[_Chunk], bool], Node | None]
BodyParser = Callable[..., Iterator[None]]


@dataclass(frozen=True, slots=True)
class LockTarget:
    """One ``lock``/``unlock`` target word. ``top``: the depth-0 form, or None (E244's
    ``top`` form); ``block``: the in-label form; ``body``: an optional parser for a
    declaration's block (``StatementSpec.block_parser``'s signature)."""

    word: str
    top: RowParser | None
    block: RowParser
    body: BodyParser | None = None


LOCK_TARGETS: dict[str, LockTarget] = {}


def register_target(row: LockTarget) -> None:
    """Add a ``lock``/``unlock`` target. ``ValueError`` for a word already in the table."""
    if row.word in LOCK_TARGETS:
        raise ValueError(f"{row.word!r} is already a lock target")
    LOCK_TARGETS[row.word] = row


def _row_of(chunks: list[_Chunk]) -> LockTarget | None:
    if not chunks or chunks[0].kind != WORD:
        return None
    return LOCK_TARGETS.get(chunks[0].text)


def top_error(ctx: ParseContext) -> None:
    """E244's ``top`` form, naming the rows that have a top-level form (F21 07 I-14)."""
    ctx.error("E244", "top", tuple(w for w, row in LOCK_TARGETS.items() if row.top is not None))


# --- Parsing ----------------------------------------------------------------------------------

def parse_ending(raw: RawStatement, ctx: ParseContext) -> Ending | None:
    if ctx.depth == 0:
        ctx.error("E240", "top")
        return None
    args = card_args(raw, ctx, ENDING_CODES)
    if args is None:
        return None
    return Ending(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                  name=args.name, heading=args.heading, title=args.title,
                  seconds=args.seconds, with_clause=args.with_clause)


def _name(ctx: ParseContext, chunk: _Chunk, kind: str) -> str | None:
    """A route or ending name: script-language §6 (E60–E64), at most ``NAME_MAX`` code points
    (E242's name form)."""
    problem = check_name(chunk.text)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    name = canonical_name(chunk.text)
    if len(name) > NAME_MAX:
        ctx.error("E242", "name", "name", len(name), NAME_MAX, kind)
        return None
    return name


def _route_title(raw: RawStatement, ctx: ParseContext, chunk: _Chunk) -> str | None:
    """A route title as shown: E242's route forms (tags, empty, more than 120)."""
    written = next((t.text for t in raw.tokens
                    if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column)), "")
    shown = _shown(written)
    if shown is None:
        ctx.error("E242", "tags", "route")
        return None
    if not shown.strip():
        ctx.error("E242", "empty", "title", "route")
        return None
    if len(shown) > ROUTE_TITLE_MAX:
        ctx.error("E242", "long", "title", len(shown), ROUTE_TITLE_MAX, "route")
        return None
    return shown


def _until(raw: RawStatement, ctx: ParseContext, chunk: _Chunk,
           colon: bool) -> tuple[str, ...] | None:
    """The names after ``until``: 1–``UNTIL_MAX`` different names separated by commas
    (E243: ``empty``, ``need``, ``many``, ``twice``)."""
    tokens = list(raw.tokens)
    if colon:
        tokens.pop()
    at = next(i for i, t in enumerate(tokens)
              if (t.line, t.column) == (chunk.line, chunk.column))
    rest = tokens[at + 1:]
    if not rest:
        ctx.error("E243", "empty")
        return None
    written: list[str] = []
    for index, token in enumerate(rest):
        if index % 2 == 0:
            if token.kind != NAME:
                ctx.error("E243", "need")
                return None
            written.append(token.text)
        elif not (token.kind == SYMBOL and token.text == ","):
            ctx.error("E243", "need")
            return None
    if len(rest) % 2 == 0:                       # a trailing comma
        ctx.error("E243", "need")
        return None
    if len(written) > UNTIL_MAX:
        ctx.error("E243", "many", len(written), UNTIL_MAX)
        return None
    names: list[str] = []
    for text in written:
        problem = check_name(text)
        if problem is not None:
            ctx.error(problem[0], *problem[1])
            return None
        name = canonical_name(text)
        if name in names:
            ctx.error("E243", "twice", name)
            return None
        names.append(name)
    return tuple(names)


def _route_top(raw: RawStatement, ctx: ParseContext, unlock: bool, chunks: list[_Chunk],
               colon: bool) -> RouteDecl | None:
    """``lock route <label> "Title" [until a, b]``; ``unlock route`` at the top level is
    E244's ``top`` form (F21 07 I-3: the row reads the verb)."""
    if unlock:
        top_error(ctx)
        return None
    if len(chunks) < 2 or chunks[0].kind != WORD or chunks[1].kind != TEXT:
        ctx.error("E243", "need")
        return None
    name = _name(ctx, chunks[0], "route")
    if name is None:
        return None
    title = _route_title(raw, ctx, chunks[1])
    if title is None:
        return None
    until: tuple[str, ...] = ()
    if len(chunks) > 2:
        if not (chunks[2].kind == WORD and chunks[2].text == WORD_UNTIL):
            ctx.error("E243", "need")
            return None
        found = _until(raw, ctx, chunks[2], colon)
        if found is None:
            return None
        until = found
    if colon:
        ctx.error("E110", "colon", WORD_LOCK)
        return None
    return RouteDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     name=name, title=title, until=until)


def _lock_block(kind: str, raw: RawStatement, ctx: ParseContext, unlock: bool,
                chunks: list[_Chunk], colon: bool) -> Lock | None:
    """``lock|unlock <kind> <name>`` in a label: one name, nothing else (E244 ``need``)."""
    if not chunks or chunks[0].kind != WORD:
        ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    if len(chunks) > 1:
        if kind == "route" and not unlock and chunks[1].kind == TEXT:
            ctx.error("E244", "declare", canonical_name(chunks[0].text))
        else:
            ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    name = _name(ctx, chunks[0], kind)
    if name is None:
        return None
    if colon:
        ctx.error("E110", "colon", raw.word)
        return None
    return Lock(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                unlock=unlock, kind=kind, name=name)


def _route_block(raw: RawStatement, ctx: ParseContext, unlock: bool, chunks: list[_Chunk],
                 colon: bool) -> Lock | None:
    return _lock_block("route", raw, ctx, unlock, chunks, colon)


def _ending_block(raw: RawStatement, ctx: ParseContext, unlock: bool, chunks: list[_Chunk],
                  colon: bool) -> Lock | None:
    if unlock:
        ctx.error("E244", "unlock_ending")
        return None
    return _lock_block("ending", raw, ctx, unlock, chunks, colon)


def parse_lock(raw: RawStatement, ctx: ParseContext) -> Node | None:
    """``lock``/``unlock``: the row named by the second word parses the rest (module
    docstring). At the top level a row's ``top`` form reads the line, ``unlock`` included
    (F21 07 I-3: the row gives its own message for it); a row with no ``top`` is E244's
    ``top`` form. In a label an unknown target is E244's ``need`` form."""
    unlock = raw.word == WORD_UNLOCK
    chunks, colon = _chunks(raw)
    row = _row_of(chunks)
    if ctx.depth == 0:
        if row is None or row.top is None:
            top_error(ctx)
            return None
        return row.top(raw, ctx, unlock, chunks[1:], colon)
    if row is None:
        ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    return row.block(raw, ctx, unlock, chunks[1:], colon)


def parse_lock_body(api, raw: RawStatement, node: object, depth: int, own_error: bool,
                    widths: tuple[int, ...]) -> Iterator[None]:
    """The ``lock`` spec's ``block_parser`` (07 I-6): the row's ``body`` reads a block under
    the line; with none, the block parser's own rule (``block_of`` after a ``:``)."""
    row = _row_of(_chunks(raw)[0])
    if row is not None and row.body is not None:
        return (yield from row.body(api, raw, node, depth, own_error, widths))
    if raw.ends_with_colon:
        return (yield from api.block_of(raw, node, depth, own_error, widths))
    return None


# --- Registration (07 I-5) -------------------------------------------------------------------

ROUTE_TARGET = LockTarget("route", _route_top, _route_block)
ENDING_TARGET = LockTarget("ending", None, _ending_block)

SPECS: Final = (
    StatementSpec(word=WORD_ENDING, placement="either", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_ending),
    StatementSpec(word=WORD_LOCK, placement="either", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_lock, block_parser=parse_lock_body),
    StatementSpec(word=WORD_UNLOCK, placement="either", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_lock),
)

# The heading of docs/script-language.md section 7 that documents all three words.
DOCS_HEADING: Final = "ending, lock route, unlock route"

DOCS: Final = (
    StatementDoc(
        "ending", "Ending", "Story flow", 'ending <name> ["heading"] "title" [seconds] [with ...]',
        "Ends the story, remembers the ending across playthroughs, and shows a card with its "
        "texts before the title screen.",
        'if coins >= 10:\n    ending good "Good End" "The Lantern Festival"', DOCS_HEADING, "F19",
        fields=("good", "Good End", "The Lantern Festival")),
    StatementDoc(
        "lock", "Locked route", "Declarations", 'lock route <label> "title" [until <ending>, ...]',
        "Declares a route that starts locked at a label. With until, it opens once the player "
        "has reached those endings.",
        'lock route bridge "At the Bridge"', DOCS_HEADING, "F19",
        fields=("bridge", "At the Bridge")),
    StatementDoc(
        "lock", "Lock a route or forget an ending", "Story flow", "lock route|ending <name>",
        "Locks a route again, or makes the game forget an ending.",
        "lock route river", DOCS_HEADING, "F19", fields=("river",)),
    StatementDoc(
        "unlock", "Unlock a route", "Story flow", "unlock route <name>",
        "Opens a locked route for good.", "unlock route river", DOCS_HEADING, "F19",
        fields=("river",)),
)


def register_words() -> None:
    """Register ``ending``, ``lock``, ``unlock`` (specs and docs) and F19's ``LOCK_TARGETS``
    rows. Called once at import (step 3, 07 I-5, with the executors in ``interpreter.py``).
    Calling it again while they are registered does nothing, so tests written for steps
    1–2 (``register_words()`` inside ``statements.scoped_registry()``) still run."""
    if get_spec(WORD_ENDING) is SPECS[0]:
        return
    for row in (ROUTE_TARGET, ENDING_TARGET):
        register_target(row)
    for spec in SPECS:
        register(spec)
    for doc in DOCS:
        register_doc(doc)


register_declaration(RouteDecl, lambda node: "route:" + node.name)  # type: ignore[attr-defined]
register_words()

__all__ = ["DOCS", "ENDINGS_MAX", "ENDING_CODES", "Ending", "LOCK_TARGETS", "Lock",
           "LockTarget", "NAME_MAX", "PERSISTENT_VIEWS", "ROUTES_MAX", "ROUTE_TITLE_MAX",
           "RouteDecl", "SPECS", "UNTIL_MAX", "parse_ending", "parse_lock", "parse_lock_body",
           "register_target", "register_words", "top_error"]
