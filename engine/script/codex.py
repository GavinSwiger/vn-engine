"""The codex: ``lock tip|item`` declarations and ``lock|unlock tip|item`` lines (F21
``04-technical.md`` §4, §6.1; ``07`` I-3, I-4).

Why this module exists: tips (kept across playthroughs) and items (this playthrough's) are
entries the author declares once, so their names, titles, categories, and texts are checked
at load and the runtime gets plain values. The words go through F19's ``lock``/``unlock``
specs as two rows of ``routes.LOCK_TARGETS``: ``LockTarget("tip", top=…, block=…,
body=codex_body)`` and the same for ``item``.

- **Top level**, ``lock tip|item <name> "Title" [in "Category"] [image <words>] [:]`` →
  ``CodexEntryDecl``, with the paragraphs of its block (``codex_body``): one quoted line
  each, ``{b}``, ``{i}``, ``{color}`` only. ``unlock tip|item`` there is E250's ``top`` form.
- **In a label**, ``lock|unlock tip|item <name>`` → ``CodexLock``. A title after ``lock`` is
  E250's ``declare`` form; anything else left over is F19's E244 ``need`` form.

``tip``, ``item``, and ``in`` are read only in these positions and stay usable as names.
Messages: E250 (shape), E252 (lengths and tags), F04's image-name codes for ``image``, F05's
tag codes in a paragraph, E60–E64 for a name. The whole-game checks (E251, E253, E254,
W140, W142) are ``checks.py``'s; ``Program.codex`` and ``Program.codex_categories`` are
built by ``program.py`` with ``build_entries``.

**Registration (07 I-4).** Importing this module registers the declaration's identity
(``"codex:" + name``) and, since F21 step 2, calls ``register_words()`` (the two rows and
their docs) once, after F19's ``routes`` (its import above); ``script/__init__.py`` imports
it right after ``routes``. Calling ``register_words()`` again does nothing.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Final, Literal

from engine.script.chapter import _shown
from engine.script.diagnostics import Diagnostic
from engine.script.identity import register_declaration
from engine.script.lexer import HEAD_NARRATION, STRING, RawStatement
from engine.script.nodes import Node, Statement
from engine.script.routes import WORD_LOCK, LOCK_TARGETS, LockTarget, register_target
from engine.script.stage import TEXT, WORD, _Chunk, _image_name, _written
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, line_body
from engine.script.texttags import NameMark, PauseMark, Span, TaggedText, VarMark, WaitMark
from engine.script.words import canonical_name, check_name

Kind = Literal["tip", "item"]

WORD_TIP: Final = "tip"
WORD_ITEM: Final = "item"
WORD_IN: Final = "in"
WORD_IMAGE: Final = "image"
KINDS: Final[tuple[str, ...]] = (WORD_TIP, WORD_ITEM)
NAME_MAX: Final = 64                      # code points (E252)
TITLE_MAX: Final = 60                     # code points as shown (E252)
CATEGORY_MAX: Final = 24                  # code points as shown (E252)
PARAGRAPHS_MAX: Final = 32                # paragraphs of one entry (E252)
PARAGRAPH_MAX: Final = 2_000              # code points of one paragraph as written (E252)
TIPS_MAX: Final = 1_000                   # tip declarations in a story (E254)
ITEMS_MAX: Final = 1_000                  # item declarations in a story (E254)
CATEGORIES_MAX: Final = 24                # categories, the defaults included (E254)
# The ``[words]`` key of each kind's default category (01 §6).
DEFAULT_WORDS: Final[dict[str, str]] = {WORD_TIP: "codex_tips", WORD_ITEM: "codex_items"}


# --- Values and nodes (04 §4) -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CodexCategory:
    """A tab of the codex: an author's text (``word`` None), or a kind's default category
    (``text`` None, ``word`` the ``[words]`` key)."""

    kind: Kind
    text: str | None
    word: str | None


@dataclass(frozen=True, slots=True)
class CodexEntry:
    """A declared tip or item (``Program.codex``): texts as shown (``{{`` is ``{``),
    paragraphs with ``Span``s only (size and speed 1.0)."""

    name: str
    kind: Kind
    title: str
    category: CodexCategory
    image: str | None
    paragraphs: tuple[TaggedText, ...]
    sid: str
    file: str
    line: int


@dataclass(slots=True, kw_only=True)
class CodexEntryDecl(Node):
    """``lock tip|item <name> "Title" [in "Category"] [image <words>]`` at the top level. A
    declaration, sid ``"codex:" + name``; ``paragraphs`` are set by ``codex_body``."""

    kind: Kind
    name: str
    title: str
    category: str | None = None
    image: str | None = None
    paragraphs: tuple[TaggedText, ...] = ()


@dataclass(slots=True, kw_only=True)
class CodexLock(Statement):
    """``lock|unlock tip|item <name>`` in a label. ``VOICE_TRANSPARENT``; not a
    checkpoint."""

    unlock: bool
    kind: Kind
    name: str

    def identity_key(self) -> tuple[str, ...]:
        return ("unlock" if self.unlock else "lock", self.kind, self.name)


# --- Parsing (04 §6.1) --------------------------------------------------------------------------

def _string(raw: RawStatement, chunk: _Chunk) -> str:
    """The text of the STRING token at ``chunk`` (escapes and joins applied)."""
    return next((t.text for t in raw.tokens
                 if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column)), "")


def _name(ctx: ParseContext, chunk: _Chunk, kind: str) -> str | None:
    """An entry name: script-language §6 (E60–E64), at most ``NAME_MAX`` code points."""
    problem = check_name(chunk.text)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    name = canonical_name(chunk.text)
    if len(name) > NAME_MAX:
        ctx.error("E252", "name", len(name), NAME_MAX, kind)
        return None
    return name


def _plain(ctx: ParseContext, written: str, which: str, limit: int, kind: str) -> str | None:
    """A title or category as shown: E252's ``tags``, ``empty``, and ``long`` forms."""
    shown = _shown(written)
    if shown is None:
        ctx.error("E252", "tags", kind)
        return None
    if not shown.strip():
        ctx.error("E252", "empty", which, kind)
        return None
    if len(shown) > limit:
        ctx.error("E252", "long", which, len(shown), limit, kind)
        return None
    return shown


def _is_word(chunk: _Chunk, word: str) -> bool:
    return chunk.kind == WORD and chunk.text == word


def _decl(kind: Kind, raw: RawStatement, ctx: ParseContext, unlock: bool,
          chunks: list[_Chunk], colon: bool) -> CodexEntryDecl | None:
    """The top-level form (module docstring): name, title, ``in``, ``image``, in order."""
    if unlock:
        ctx.error("E250", "top")
        return None
    if len(chunks) < 2 or chunks[0].kind != WORD or chunks[1].kind != TEXT:
        ctx.error("E250", "need", kind)
        return None
    name = _name(ctx, chunks[0], kind)
    if name is None:
        return None
    title = _plain(ctx, _string(raw, chunks[1]), "title", TITLE_MAX, kind)
    if title is None:
        return None
    at = 2
    category: str | None = None
    if at < len(chunks) and _is_word(chunks[at], WORD_IN):
        if at + 1 >= len(chunks) or chunks[at + 1].kind != TEXT:
            ctx.error("E250", "in")
            return None
        category = _plain(ctx, _string(raw, chunks[at + 1]), "category", CATEGORY_MAX, kind)
        if category is None:
            return None
        at += 2
    image: str | None = None
    if at < len(chunks) and _is_word(chunks[at], WORD_IMAGE):
        stop = at + 1
        while (stop < len(chunks) and chunks[stop].kind != TEXT
               and not _is_word(chunks[stop], WORD_IN)):
            stop += 1
        image = _image_name(ctx, WORD_IMAGE, raw, chunks[at + 1:stop])
        if image is None:
            return None
        at = stop
    if at < len(chunks):
        ctx.error("E250", "left", _written(raw, chunks[at:]), kind)
        return None
    return CodexEntryDecl(file=raw.file, line=raw.line, end_line=raw.end_line,
                          column=raw.column, kind=kind, name=name, title=title,
                          category=category, image=image)


def _lock(kind: Kind, raw: RawStatement, ctx: ParseContext, unlock: bool,
          chunks: list[_Chunk], colon: bool) -> CodexLock | None:
    """The in-label form: one name, nothing else."""
    if not chunks or chunks[0].kind != WORD:
        ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    if len(chunks) > 1:
        if not unlock and chunks[1].kind == TEXT:
            ctx.error("E250", "declare", kind, canonical_name(chunks[0].text), chunks[1].text)
        else:
            ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    name = _name(ctx, chunks[0], kind)
    if name is None:
        return None
    if colon:
        ctx.error("E110", "colon", raw.word)
        return None
    return CodexLock(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     unlock=unlock, kind=kind, name=name)


def parse_codex_decl(raw: RawStatement, ctx: ParseContext, unlock: bool,
                     chunks: list[_Chunk], colon: bool) -> CodexEntryDecl | None:
    """A row's ``top``: the kind is the word before ``chunks`` (``tip`` or ``item``)."""
    return _decl(_kind_of(raw), raw, ctx, unlock, chunks, colon)


def parse_codex_lock(raw: RawStatement, ctx: ParseContext, unlock: bool,
                     chunks: list[_Chunk], colon: bool) -> CodexLock | None:
    """A row's ``block``: the kind is the word before ``chunks``."""
    return _lock(_kind_of(raw), raw, ctx, unlock, chunks, colon)


def _kind_of(raw: RawStatement) -> Kind:
    word = raw.tokens[1].text if len(raw.tokens) > 1 else ""
    return WORD_ITEM if word == WORD_ITEM else WORD_TIP


# --- The block of a declaration -----------------------------------------------------------------

# F30: {username} gets E252's username form (E302's wording).
_BAD_TAGS = ((VarMark, "var"), (NameMark, "username"), (PauseMark, "pause"),
             (WaitMark, "pause"))


def _bad_tag(body: TaggedText) -> str | None:
    """The first tag a paragraph can't use (E252's ``tag`` form), or None."""
    for piece in body.pieces:
        for kind, tag in _BAD_TAGS:
            if isinstance(piece, kind):
                return tag
        if isinstance(piece, Span):
            if piece.style.size != 1.0:
                return "size"
            if piece.style.speed != 1.0:
                return "speed"
            if piece.style.effect is not None:                 # F29 SR-F29-04
                return piece.style.effect.kind
    return "next" if body.auto_next else None


def _paragraph(kind: str):
    """The parser of one line under a declaration: one quoted text (E250's ``body`` form),
    at most ``PARAGRAPH_MAX`` code points, F05's tags without timing or ``{var}``."""

    def parse(raw: RawStatement, ctx: ParseContext) -> TaggedText | None:
        tokens = raw.tokens
        if raw.head != HEAD_NARRATION or len(tokens) != 1 or raw.py is not None:
            ctx.error("E250", "body", kind)
            return None
        token = tokens[0]
        if token.unclosed:
            return None                              # the reader's own error is pending
        if len(token.text) > PARAGRAPH_MAX:
            ctx.error("E252", "paragraph", len(token.text), PARAGRAPH_MAX)
            return None
        body = line_body(raw, ctx, token)
        if body is None:
            return None
        bad = _bad_tag(body)
        if bad is not None:
            ctx.error("E252", "tag", bad, kind)
            return None
        return body

    return parse


def _body_error(api, raw: RawStatement, depth: int, kind: str) -> None:
    """E250's ``body`` form on a line the paragraphs can't hold (reported like any line)."""
    api.parse_line(raw, depth, lambda _raw, ctx: ctx.error("E250", "body", kind))


def codex_body(api, raw: RawStatement, node: object, depth: int, own_error: bool,
               widths: tuple[int, ...]) -> Iterator[None]:
    """The rows' ``body`` (the ``lock`` spec's ``block_parser``, F19 07 I-6): a top-level
    declaration's paragraphs (04 §6.1); any other line gets the block parser's own rule."""
    if depth != 0 or not raw.ends_with_colon:
        if raw.ends_with_colon:
            yield from api.block_of(raw, node, depth, own_error, widths)
        return
    kind = _kind_of(raw)
    reader = api.reader
    w = raw.width
    nxt = yield from api.peek()
    if nxt is None or nxt.width <= w:
        if not own_error:
            api.empty_block(raw, raw.word, nxt)
        return
    block_w = nxt.width
    body_widths = widths + (block_w,)
    phantom: int | None = None
    paragraphs: list[TaggedText] = []
    count = 0
    over: RawStatement | None = None
    parse = _paragraph(kind)
    while True:
        line = yield from api.peek()
        if line is None or line.width <= w:
            break
        reader.next()
        api.ctx.statement_count += 1
        if line.width > block_w and line.width != phantom:
            _body_error(api, line, depth + 1, kind)    # deeper than the paragraphs
            yield from api.skip_deeper(block_w, quiet=True)
        else:
            phantom = api.check_width(line, block_w, phantom, body_widths)
            body, error = api.parse_line(line, depth + 1, parse)
            if line.head == HEAD_NARRATION and len(line.tokens) == 1:
                count += 1
                if count == PARAGRAPHS_MAX + 1:
                    over = line
            if not error and body is not None:
                paragraphs.append(body)  # type: ignore[arg-type]
            elif error:                                # its own lines aren't paragraphs
                yield from api.skip_deeper(line.width, quiet=True)
        if api.due():
            yield
    if over is not None:
        api.ctx.sink.add(Diagnostic("E252", api.file, over.line, None,
                                    ("paragraphs", count, PARAGRAPHS_MAX, kind),
                                    source_line=over.texts.get(over.line), stmt=over.line))
    if isinstance(node, CodexEntryDecl):
        node.paragraphs = tuple(paragraphs[:PARAGRAPHS_MAX])


# --- Program.codex (04 §6.2 step 7) -------------------------------------------------------------

def build_entries(decls: Iterable[CodexEntryDecl]
                  ) -> tuple[tuple[CodexEntry, ...], tuple[CodexCategory, ...]]:
    """The entries in the order given (include order, then line) and the categories in
    first-declaration order; a kind's default category sits at its first use. Call after
    identities are assigned (``sid``)."""
    categories: dict[tuple[str, str | None], CodexCategory] = {}
    entries: list[CodexEntry] = []
    for decl in decls:
        key = (decl.kind, decl.category)
        category = categories.get(key)
        if category is None:
            word = None if decl.category is not None else DEFAULT_WORDS[decl.kind]
            category = categories[key] = CodexCategory(decl.kind, decl.category, word)
        entries.append(CodexEntry(
            name=decl.name, kind=decl.kind, title=decl.title, category=category,
            image=decl.image, paragraphs=decl.paragraphs, sid=decl.sid,
            file=decl.file.ref, line=decl.line))
    return tuple(entries), tuple(categories.values())


# --- Registration (07 I-4) ----------------------------------------------------------------------

TIP_TARGET = LockTarget(WORD_TIP, parse_codex_decl, parse_codex_lock, codex_body)
ITEM_TARGET = LockTarget(WORD_ITEM, parse_codex_decl, parse_codex_lock, codex_body)

DOCS_HEADING: Final = "lock tip, lock item, unlock (codex)"   # docs/script-language.md

DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Codex entry", "Declarations",
        'lock tip|item <name> "title" [in "category"] [image <name>]',
        "Declares a codex tip, kept across playthroughs, or an item, kept in this "
        "playthrough, with its text under it.",
        # An item, so the doc game's dev load gives no W142 (a tip no unlock tip line names).
        'lock item red_lantern "Red Lantern" in "Things":\n    "Bought at Daichi\'s stall."',
        DOCS_HEADING, "F21", fields=("red_lantern", "Red Lantern", "Things")),
    StatementDoc(
        WORD_LOCK, "Forget a tip or take an item", "Story flow", "lock tip|item <name>",
        "Makes the game forget a tip, or takes an item away from the player.",
        "lock item brass_key", DOCS_HEADING, "F21", fields=("brass_key",)),
    StatementDoc(
        "unlock", "Give a tip or an item", "Story flow", "unlock tip|item <name>",
        "Adds a tip to the codex for good, or gives the player an item.",
        "unlock tip lanterns", DOCS_HEADING, "F21", fields=("lanterns",)),
)


def register_words() -> None:
    """Register F21's ``LOCK_TARGETS`` rows and their docs. Needs F19's ``lock``/``unlock``
    specs (``routes.register_words()``) for the words to parse. Since F21 step 2 (the
    executor, in ``runtime/codex.py``, registered by ``interpreter.py``) it runs once at
    import, through the one line in ``script/__init__.py`` after ``routes``'; calling it
    again does nothing, so the step-1 tests that call it inside
    ``statements.scoped_registry()`` still run (07 I-4, F19 I-5's pattern)."""
    if LOCK_TARGETS.get(WORD_TIP) is TIP_TARGET:
        return
    for row in (TIP_TARGET, ITEM_TARGET):
        register_target(row)
    for doc in DOCS:
        register_doc(doc)


register_declaration(CodexEntryDecl, lambda node: "codex:" + node.name)  # type: ignore[attr-defined]
register_words()

__all__ = ["CATEGORIES_MAX", "CATEGORY_MAX", "CodexCategory", "CodexEntry", "CodexEntryDecl",
           "CodexLock", "DEFAULT_WORDS", "DOCS", "DOCS_HEADING", "ITEMS_MAX", "ITEM_TARGET", "KINDS",
           "NAME_MAX", "PARAGRAPHS_MAX", "PARAGRAPH_MAX", "TIPS_MAX", "TIP_TARGET",
           "TITLE_MAX", "build_entries", "codex_body", "parse_codex_decl", "parse_codex_lock",
           "register_words"]
