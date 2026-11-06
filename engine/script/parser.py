"""The block parser (F02 ``04-technical.md`` §7.7): block structure, placement, if-chains,
and recovery.

``parse_file`` reads one decoded file with a ``StatementReader`` and returns its top-level
nodes (``Label``, ``Define``, ``Include``). Recursion depth is bounded by
``SCRIPT_MAX_BLOCK_DEPTH`` + 1; deeper lines are parsed for errors without recursion (E15).
``phantom`` is a width accepted after an indentation error, so a run of lines with the same
wrong width gives one message (SR-F02-20).

``iter_parse_file`` is the sliced form the loader drives (§7.9): it yields after about every
``SCRIPT_YIELD_LINES`` physical lines, between statements or inside a run of blank and comment
lines (``StatementReader.peek_within``), and returns the nodes. A statement
that opens a block hands back the generator that parses the block, so only block-opening
statements cost a generator object.

F07 C7: a statement whose spec has a ``block_parser`` reads its own block through the
``BlockApi`` methods of ``_Parser`` (``peek``, ``parse_block``, ``parse_line``,
``check_width``, ``skip_deeper``, ``empty_block``, and ``block_of``, the default block
rule; F07 ``04-technical.md`` §6.2, F21 ``04`` §6.1). They
are generators like the rest of this module where they read lines (``yield from``).
"""

from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field

from engine.script.diagnostics import Diagnostic
from engine.script.lexer import (
    HEAD_NARRATION,
    HEAD_PYTHON,
    HEAD_WORD,
    MORE,
    NAME,
    RANK_BLOCK,
    RawStatement,
    StatementReader,
)
from engine.script.limits import SCRIPT_MAX_BLOCK_DEPTH, SCRIPT_YIELD_LINES
from engine.script.nodes import If, IfBranch, Label, Node, ScriptFile, Statement
from engine.script.statements import (
    ParseContext,
    misplaced_args,
    parse_dialogue,
    parse_narration,
    parse_python_line,
    spec_for,
    tail_for,
)
from engine.script.words import (MODIFIER_WORDS, SHOW_MODIFIER_WORDS, STATEMENT_WORDS,
                                 canonical_name, is_name)

@dataclass(slots=True)
class _Chain:
    """The if-chain open at the end of a block's items."""

    node: If
    width: int
    branches: list[IfBranch]
    else_line: int | None = None


@dataclass(slots=True)
class _BlockState:
    items: list[Node] = field(default_factory=list)
    chain: _Chain | None = None
    story_run: bool = False          # depth 0: inside a run of top-level story lines (E40)

    def close_chain(self) -> None:
        if self.chain is not None:
            self.chain.node.branches = tuple(self.chain.branches)
            self.chain = None


class _Parser:
    def __init__(self, reader: StatementReader, ctx: ParseContext) -> None:
        self.reader = reader
        self.ctx = ctx
        self.file = reader.file
        self.yield_at = SCRIPT_YIELD_LINES     # next physical-line count to yield at (§7.9)

    def due(self) -> bool:
        """True when the frame loop should get a turn (every ``SCRIPT_YIELD_LINES`` lines)."""
        read = self.reader.lines_read
        if read < self.yield_at:
            return False
        self.yield_at = read + SCRIPT_YIELD_LINES
        return True

    def wait_raw(self, raw: object) -> Generator[None, None, RawStatement | None]:
        """Given ``MORE`` from ``peek_within``, yield after every ``SCRIPT_YIELD_LINES``
        lines of a run of blank, comment, or over-long lines until the next statement (or
        the end) is peeked, and return it. Without this a file of only such lines would be
        read in one piece (F02 Step 11; §7.9)."""
        reader = self.reader
        while raw is MORE:
            self.yield_at = reader.lines_read + SCRIPT_YIELD_LINES
            yield
            raw = reader.peek_within(SCRIPT_YIELD_LINES)
        return raw  # type: ignore[return-value]

    # Blocks -------------------------------------------------------------------------------

    def parse_block(self, parent_w: int, block_w: int, depth: int,
                    widths: tuple[int, ...]) -> Generator[None, None, list[Node]]:
        reader = self.reader
        state = _BlockState()
        phantom: int | None = None
        while True:
            raw = reader.peek_within(SCRIPT_YIELD_LINES)
            if raw is MORE:
                raw = yield from self.wait_raw(raw)
            if raw is None:
                break
            w = raw.width
            if w < block_w and w != phantom:
                if w <= parent_w:
                    break
                raw.error("E14", (widths, reader.kind or " "), rank=RANK_BLOCK)
                phantom = w
            elif w > block_w and w != phantom:
                raw.error("E13", rank=RANK_BLOCK)
                phantom = w
            reader.next()
            follow = self.statement(raw, depth, state, widths)
            if follow is not None:
                yield from follow
            if self.due():
                yield
        state.close_chain()
        return state.items

    # BlockApi (F07 C7) ------------------------------------------------------------------

    def peek(self) -> Generator[None, None, RawStatement | None]:
        """The next statement, not consumed (None at the end of the file)."""
        raw = self.reader.peek_within(SCRIPT_YIELD_LINES)
        if raw is MORE:
            raw = yield from self.wait_raw(raw)
        return raw  # type: ignore[return-value]

    def check_width(self, raw: RawStatement, block_w: int, phantom: int | None,
                    widths: tuple[int, ...]) -> int | None:
        """The E14/E13 check of a statement inside a block of width ``block_w`` (the caller
        has made sure it is deeper than the block's parent): ``parse_block``'s rule,
        SR-F02-20. Returns the new phantom width."""
        w = raw.width
        if w < block_w and w != phantom:
            raw.error("E14", (widths, self.reader.kind or " "), rank=RANK_BLOCK)
            return w
        if w > block_w and w != phantom:
            raw.error("E13", rank=RANK_BLOCK)
            return w
        return phantom

    def parse_line(self, raw: RawStatement, depth: int,
                   parse: Callable[[RawStatement, ParseContext], object | None] | None = None,
                   ) -> tuple[object | None, bool]:
        """One consumed statement parsed alone, with ``parse`` or as the block parser
        would (``parse_one``); its first error is reported and its uses recorded (dropped
        on an error). Returns the node and whether the statement had an error of its own.
        Counts nothing: the caller counts statements."""
        ctx = self.ctx
        ctx.raw = raw
        ctx.depth = depth
        ctx.file = self.file
        if parse is not None:
            node = parse(raw, ctx)
        else:
            word = raw.word if raw.head == HEAD_WORD else ""
            node = self.parse_one(raw, spec_for(raw, word))
        own_error = raw.flush(ctx.sink)
        if own_error:
            ctx.uses.clear()
        else:
            ctx.commit_uses()
        return node, own_error

    def empty_block(self, raw: RawStatement, word: str, nxt: RawStatement | None) -> None:
        """E12 for ``raw``, which needs lines under it and has none. ``word`` picks the form
        (``label``, ``if``, …; F07 ``menu`` and ``choice``); ``nxt`` is the statement after
        it, for the "comment lines don't count" note."""
        comment_width = nxt.comment_width_before if nxt is not None \
            else self.reader.comment_width
        self.ctx.sink.add(Diagnostic("E12", self.file, raw.line, None,
                                     (word, comment_width > raw.width),
                                     source_line=raw.texts.get(raw.line), stmt=raw.line))

    def statement(self, raw: RawStatement, depth: int, state: _BlockState,
                  widths: tuple[int, ...]) -> Iterator[None] | None:
        """Handle one statement. Returns the generator that parses its block (the caller
        runs it with ``yield from``), or None when it opens no block."""
        ctx = self.ctx
        ctx.statement_count += 1
        word = raw.word if raw.head == HEAD_WORD else ""
        spec = spec_for(raw, word)
        is_branch = spec is not None and word in ("elif", "else")
        if not is_branch:
            state.close_chain()
        if word in STATEMENT_WORDS and spec is None:
            # A reserved word with no statement yet (E32/E32b/E33): its own lines are
            # unknown, so lines indented under it are skipped without messages.
            if word == "python":
                raw.error("E33")
            elif word in MODIFIER_WORDS or word in SHOW_MODIFIER_WORDS:   # F09: with
                raw.error("E32b", (word,))
            else:
                raw.error("E32", (word,))
            raw.flush(ctx.sink)
            ctx.uses.clear()
            if raw.ends_with_colon:
                return self.skip_deeper(raw.width, quiet=True)
            return None
        # F22 (07 I-4): an "either" statement is top-level at depth 0, a story line deeper.
        top = spec is not None and (spec.placement == "top"
                                    or (spec.placement == "either" and depth == 0))
        if depth == 0:
            if top:
                state.story_run = False
            elif not state.story_run:
                raw.error("E40", rank=RANK_BLOCK)
                state.story_run = True
        elif top:
            raw.error(spec.misplaced, misplaced_args(raw, spec), rank=RANK_BLOCK)
        ctx.raw = raw
        ctx.depth = depth
        ctx.file = self.file
        node = self.parse_one(raw, spec)
        keep = node is not None and (depth == 0) == top
        if is_branch:
            keep = self.chain(raw, node, state) and keep  # type: ignore[arg-type]
        own_error = raw.flush(ctx.sink)
        if own_error:
            ctx.uses.clear()
            keep = False
            if depth == 0 and raw.ends_with_colon:
                self.soft_label(raw)
        else:
            ctx.commit_uses()
        if keep and not is_branch:
            state.items.append(node)  # type: ignore[arg-type]
        if isinstance(node, If):
            state.chain = _Chain(node, raw.width, list(node.branches))
        if spec is not None and spec.block_parser is not None:     # F07 C7: menu
            return spec.block_parser(self, raw, node, depth, own_error, widths)
        takes_block = spec is not None and spec.takes_block
        if takes_block or raw.ends_with_colon:
            return self.block_of(raw, node, depth, own_error, widths)
        return None

    def parse_one(self, raw: RawStatement, spec) -> object | None:
        if spec is not None:
            return spec.parse(raw, self.ctx)
        if raw.head == HEAD_PYTHON:
            return parse_python_line(raw, self.ctx)
        if raw.head == HEAD_NARRATION:
            return parse_narration(raw, self.ctx)
        if raw.head == HEAD_WORD:
            return parse_dialogue(raw, self.ctx)
        return None                                   # E30d, E50, E51 heads

    def block_of(self, raw: RawStatement, node: object, depth: int, own_error: bool,
                 widths: tuple[int, ...]) -> Generator[None, None, None]:
        """Parse the block under ``raw`` (SR-F02-18/19/69) and attach it to ``node``."""
        reader = self.reader
        w = raw.width
        nxt = reader.peek_within(SCRIPT_YIELD_LINES)
        if nxt is MORE:
            nxt = yield from self.wait_raw(nxt)
        if nxt is not None and nxt.width > w:
            if depth + 1 > SCRIPT_MAX_BLOCK_DEPTH:
                nxt.error("E15", rank=RANK_BLOCK)
                yield from self.skip_deeper(w, quiet=False)
                return
            block = yield from self.parse_block(w, nxt.width, depth + 1,
                                                widths + (nxt.width,))
            statements = tuple(item for item in block if isinstance(item, Statement))
            if isinstance(node, Label):
                node.block = statements
            elif isinstance(node, If):
                node.branches[0].block = statements
            elif isinstance(node, IfBranch):
                node.block = statements
            return
        if raw.ends_with_colon and not own_error:
            self.empty_block(raw, raw.word if raw.head == HEAD_WORD else "line", nxt)

    def chain(self, raw: RawStatement, branch: IfBranch | None, state: _BlockState) -> bool:
        """Attach an ``elif``/``else`` to the chain directly above (§7.7.2). True if
        attached; otherwise the error is pending on ``raw``."""
        chain = state.chain
        keyword = raw.word
        if chain is None or chain.width != raw.width:
            raw.error("E34" if keyword == "elif" else "E35")
            return False
        if chain.else_line is not None:
            if keyword == "elif":
                raw.error("E37", (chain.else_line,))
            else:
                raw.error("E36", (chain.else_line,))
            return False
        if keyword == "else":
            chain.else_line = raw.line
        if branch is not None:
            chain.branches.append(branch)
        return True

    def skip_deeper(self, width: int, *, quiet: bool) -> Generator[None, None, None]:
        """Consume every statement deeper than ``width``: without messages (``quiet``), or
        parsed for errors with no nodes and no recursion (E15)."""
        reader = self.reader
        ctx = self.ctx
        while True:
            raw = reader.peek_within(SCRIPT_YIELD_LINES)
            if raw is MORE:
                raw = yield from self.wait_raw(raw)
            if raw is None or raw.width <= width:
                break
            reader.next()
            ctx.statement_count += 1
            if self.due():
                yield
            if quiet:
                raw.pending.clear()
                continue
            word = raw.word if raw.head == HEAD_WORD else ""
            spec = spec_for(raw, word)
            ctx.raw = raw
            ctx.depth = SCRIPT_MAX_BLOCK_DEPTH + 1          # F22 I-4: never depth 0 here
            ctx.file = self.file
            if word in STATEMENT_WORDS and spec is None:
                raw.error("E32", (word,))
            elif spec is not None and spec.placement == "top":
                raw.error(spec.misplaced, misplaced_args(raw, spec), rank=RANK_BLOCK)
                self.parse_one(raw, spec)
            else:
                self.parse_one(raw, spec)
            if raw.flush(ctx.sink):
                ctx.uses.clear()
            else:
                ctx.commit_uses()

    def soft_label(self, raw: RawStatement) -> None:
        """SR-F02-69: a top-level line with an error that ends in ``:`` counts its second
        word, if a valid name, as a label."""
        tokens = raw.tokens
        if len(tokens) >= 2 and tokens[1].kind == NAME and is_name(tokens[1].text):
            name = canonical_name(tokens[1].text)
            self.ctx.collected.soft_labels.setdefault(name, (raw.file, raw.line))


def iter_parse_file(file: ScriptFile, text: str, ctx: ParseContext, *,
                    on_todo: Callable[[ScriptFile, int, str], None] | None = None,
                    ) -> Generator[None, None, list[Node]]:
    """``parse_file`` in slices: yields about every ``SCRIPT_YIELD_LINES`` physical lines
    and returns the top-level nodes (``nodes = yield from iter_parse_file(...)``). The
    caller may ``close()`` it at a yield (a story limit stops reading, §7.6.1)."""
    if on_todo is None and ctx.collect_todos:
        on_todo = ctx.collected.add_todo
    reader = StatementReader(file, text, ctx.sink, tail_for, on_todo=on_todo)
    parser = _Parser(reader, ctx)
    return (yield from parser.parse_block(-1, 0, 0, (0,)))


def parse_file(file: ScriptFile, text: str, ctx: ParseContext, *,
               on_todo: Callable[[ScriptFile, int, str], None] | None = None) -> list[Node]:
    """Parse one decoded file. Errors go to ``ctx.sink``; names and uses to
    ``ctx.collected``. Returns the top-level nodes that have no error."""
    job = iter_parse_file(file, text, ctx, on_todo=on_todo)
    while True:
        try:
            next(job)
        except StopIteration as stop:
            return stop.value
