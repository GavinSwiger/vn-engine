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

**F64 round 1 (item counts, the purse; specs/F64-items/SPEC.md).** An item declaration can
have ``count`` (up to ``ITEM_COUNT_MAX``), ``count <n>`` or ``count 0 to <n>`` (at most ``n``
held), and ``money`` (the purse's item; implies ``count``), anywhere after the title (``in``
still before ``image``; a picture's words stop at ``in``, ``count``, ``money``). In a label, ``unlock item
<name> <n>`` adds ``n`` and ``lock item <name> <n>`` takes ``n`` (never below 0); no number is
1, as before. ``count`` and ``money`` are words only there (ADR-0010). Messages: E436 (the
amount), E437 (``count``/``money`` on a tip), E438 (the count's range).
**F64 round 2 (the shop).** ``price <n>`` (0 to ``ITEM_COUNT_MAX``, items only, anywhere after
the title) is the price ``minigame shop`` asks when its stock names no price (E437's ``price``
form on a tip, E438's ``price`` form for the number).
**F64 round 2 (Use).** ``use <scene>`` (items only, anywhere after the title) names the
label a Use button runs as a call between lines (``runtime/itemuse.py``). The scene is a
jump target: E43 for a scene no label has; E41/E41b/E64 for its name; E437 on a tip.
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
from engine.script.stage import NUMBER, TEXT, WORD, _Chunk, _image_name, _written
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, line_body
from engine.script.texttags import NameMark, PauseMark, Span, TaggedText, VarMark, WaitMark
from engine.script.words import canonical_name, check_name

Kind = Literal["tip", "item"]

WORD_TIP: Final = "tip"
WORD_ITEM: Final = "item"
WORD_IN: Final = "in"
WORD_IMAGE: Final = "image"
WORD_COUNT: Final = "count"               # F64: lock item coin "Coins" count 0 to 999
WORD_MONEY: Final = "money"               # F64: the purse's item
WORD_PRICE: Final = "price"               # F64 round 2: the default shop price
WORD_USE: Final = "use"                   # F64 round 2: the scene Use runs
WORD_TO: Final = "to"
KINDS: Final[tuple[str, ...]] = (WORD_TIP, WORD_ITEM)
NAME_MAX: Final = 64                      # code points (E252)
TITLE_MAX: Final = 60                     # code points as shown (E252)
CATEGORY_MAX: Final = 24                  # code points as shown (E252)
PARAGRAPHS_MAX: Final = 32                # paragraphs of one entry (E252)
PARAGRAPH_MAX: Final = 2_000              # code points of one paragraph as written (E252)
TIPS_MAX: Final = 1_000                   # tip declarations in a story (E254)
ITEMS_MAX: Final = 1_000                  # item declarations in a story (E254)
CATEGORIES_MAX: Final = 24                # categories, the defaults included (E254)
ITEM_COUNT_MAX: Final = 999_999           # F64: the most of one item a player can hold
# The words after a declaration's title (``in`` before ``image``; a picture's words stop at
# any of the others).
_DECL_WORDS: Final = (WORD_IN, WORD_IMAGE, WORD_COUNT, WORD_MONEY, WORD_PRICE, WORD_USE)
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
    cap: int = 1                          # F64: the most held (1: a plain item)
    counted: bool = False                 # F64: declared with ``count`` (shown as "×n")
    money: bool = False                   # F64: the purse's item
    price: int | None = None              # F64 round 2: the shop's default price
    use: str | None = None                # F64 round 2: the scene Use runs (a label)


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
    count: int | None = None              # F64: ``count``'s most held; None: a plain item
    money: bool = False                   # F64: ``money``
    price: int | None = None              # F64 round 2: ``price <n>``
    use: str | None = None                # F64 round 2: ``use <label>``


@dataclass(slots=True, kw_only=True)
class CodexLock(Statement):
    """``lock|unlock tip|item <name> [<amount>]`` in a label. ``VOICE_TRANSPARENT``; not a
    checkpoint. ``amount`` (F64) is how many to add or take (1 when none is written); a
    written amount joins the identity, so a plain line keeps its sid."""

    unlock: bool
    kind: Kind
    name: str
    amount: int = 1
    written: bool = False                 # F64: an amount was written

    def identity_key(self) -> tuple[str, ...]:
        key = ("unlock" if self.unlock else "lock", self.kind, self.name)
        return key + (str(self.amount),) if self.written else key


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
    image: str | None = None
    count: int | None = None
    money = False
    price: int | None = None
    use: str | None = None
    seen: set[str] = set()
    while at < len(chunks):
        chunk = chunks[at]
        word = chunk.text if chunk.kind == WORD else ""
        if word in seen or word not in _DECL_WORDS                 or (word == WORD_IN and WORD_IMAGE in seen):     # F21: in before image
            break
        seen.add(word)
        if word in (WORD_COUNT, WORD_MONEY, WORD_PRICE, WORD_USE) and kind != WORD_ITEM:
            ctx.error("E437", word, name)
            return None
        if word == WORD_IN:
            if at + 1 >= len(chunks) or chunks[at + 1].kind != TEXT:
                ctx.error("E250", "in")
                return None
            category = _plain(ctx, _string(raw, chunks[at + 1]), "category", CATEGORY_MAX,
                              kind)
            if category is None:
                return None
            at += 2
        elif word == WORD_IMAGE:
            stop = at + 1
            while (stop < len(chunks) and chunks[stop].kind != TEXT
                   and not any(_is_word(chunks[stop], w)
                               for w in _DECL_WORDS if w != WORD_IMAGE)):
                stop += 1
            image = _image_name(ctx, WORD_IMAGE, raw, chunks[at + 1:stop])
            if image is None:
                return None
            at = stop
        elif word == WORD_COUNT:
            found = _count(ctx, chunks, at + 1, name)
            if found is None:
                return None
            count, at = found
        elif word == WORD_PRICE:
            written = chunks[at + 1].text if at + 1 < len(chunks) else ""
            number = at + 1 < len(chunks) and chunks[at + 1].kind == NUMBER
            price = _whole(written) if number else None
            if price is None or price > ITEM_COUNT_MAX:
                ctx.error("E438", "price", written, name, ITEM_COUNT_MAX)
                return None
            at += 2
        elif word == WORD_USE:
            use = _use_target(ctx, raw, chunks, at + 1)
            if use is None:
                return None
            at += 2
        else:
            money = True
            at += 1
    if at < len(chunks):
        ctx.error("E250", "left", _written(raw, chunks[at:]), kind)
        return None
    if money and count is None:
        count = ITEM_COUNT_MAX                       # money is always counted
    return CodexEntryDecl(file=raw.file, line=raw.line, end_line=raw.end_line,
                          column=raw.column, kind=kind, name=name, title=title,
                          category=category, image=image, count=count, money=money,
                          price=price, use=use)


def _use_target(ctx: ParseContext, raw: RawStatement, chunks: list[_Chunk],
                at: int) -> str | None:
    """F64 round 2: ``use``'s scene: one label name (E41 for none, E41b in quotes, E64 for a
    bad one). Recorded as a jump target, so a scene no label has is E43 (did-you-mean)."""
    if at >= len(chunks) or chunks[at].kind not in (WORD, TEXT):
        ctx.error("E41", WORD_USE)
        return None
    chunk = chunks[at]
    if chunk.kind == TEXT:
        ctx.error("E41b", WORD_USE, _string(raw, chunk))
        return None
    problem = check_name(chunk.text)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    target = canonical_name(chunk.text)
    ctx.uses.append(("target", target, ctx.place()))
    return target


def _whole(written: str) -> int | None:
    """A whole number as written (digits only, no sign or point), or None."""
    if written.isascii() and written.isdigit() and len(written) <= 9:
        return int(written)
    return None


def _count(ctx: ParseContext, chunks: list[_Chunk], at: int,
           name: str) -> tuple[int, int] | None:
    """``count``'s range from ``chunks[at]``: nothing (``ITEM_COUNT_MAX``), ``<n>``, or
    ``0 to <n>``; the most held and the next index. E438 for anything else."""
    if at >= len(chunks) or chunks[at].kind != NUMBER:
        return ITEM_COUNT_MAX, at
    first = chunks[at].text
    if not (at + 1 < len(chunks) and _is_word(chunks[at + 1], WORD_TO)):
        high = _whole(first)
        if high is None or not 1 <= high <= ITEM_COUNT_MAX:
            ctx.error("E438", "high", first, name, ITEM_COUNT_MAX)
            return None
        return high, at + 1
    if _whole(first) != 0:
        ctx.error("E438", "low", first, name)
        return None
    if at + 2 >= len(chunks) or chunks[at + 2].kind != NUMBER:
        ctx.error("E438", "to", name)
        return None
    high = _whole(chunks[at + 2].text)
    if high is None or not 1 <= high <= ITEM_COUNT_MAX:
        ctx.error("E438", "high", chunks[at + 2].text, name, ITEM_COUNT_MAX)
        return None
    return high, at + 3


def _lock(kind: Kind, raw: RawStatement, ctx: ParseContext, unlock: bool,
          chunks: list[_Chunk], colon: bool) -> CodexLock | None:
    """The in-label form: one name, then (F64) an optional amount."""
    if not chunks or chunks[0].kind != WORD:
        ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    amount, written = 1, False
    word = "unlock" if unlock else "lock"
    if len(chunks) > 1:
        if not unlock and chunks[1].kind == TEXT:
            ctx.error("E250", "declare", kind, canonical_name(chunks[0].text), chunks[1].text)
            return None
        shown = canonical_name(chunks[0].text)
        if len(chunks) == 2 and chunks[1].kind == NUMBER:
            if kind != WORD_ITEM:
                ctx.error("E436", "tip", word, shown, chunks[1].text)
                return None
            found = _whole(chunks[1].text)
            if found is None or not 1 <= found <= ITEM_COUNT_MAX:
                ctx.error("E436", "number", word, shown, chunks[1].text, ITEM_COUNT_MAX)
                return None
            amount, written = found, True
        elif len(chunks) == 2 and chunks[1].kind == WORD and kind == WORD_ITEM:
            ctx.error("E436", "word", word, shown, chunks[1].text)
            return None
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
                     unlock=unlock, kind=kind, name=name, amount=amount, written=written)


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
            file=decl.file.ref, line=decl.line,
            cap=decl.count if decl.count is not None else 1,
            counted=decl.count is not None, money=decl.money, price=decl.price,
            use=decl.use))
    return tuple(entries), tuple(categories.values())


# --- Registration (07 I-4) ----------------------------------------------------------------------

TIP_TARGET = LockTarget(WORD_TIP, parse_codex_decl, parse_codex_lock, codex_body)
ITEM_TARGET = LockTarget(WORD_ITEM, parse_codex_decl, parse_codex_lock, codex_body)

DOCS_HEADING: Final = "lock tip, lock item, unlock (codex)"   # docs/script-language.md

DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Codex entry", "Declarations",
        'lock tip|item <name> "title" [in "category"] [count [0 to <n>]] [money] '
        '[price <n>] [use <scene>] [image <name>]',
        "Declares a codex tip, kept across playthroughs, or an item, kept in this "
        "playthrough, with its text under it. An item with count can be held many times; "
        "money shows it at the top of the bag; price is what a shop asks by default; use "
        "gives it a Use button that runs that scene.",
        # An item, so the doc game's dev load gives no W142 (a tip no unlock tip line names).
        'lock item red_lantern "Red Lantern" in "Things":\n    "Bought at Daichi\'s stall."',
        DOCS_HEADING, "F21", fields=("red_lantern", "Red Lantern", "Things")),
    StatementDoc(
        WORD_LOCK, "Forget a tip or take an item", "Story flow",
        "lock tip|item <name> [<amount>]",
        "Makes the game forget a tip, or takes an item away from the player (with a number, "
        "takes that many, never below none).",
        "lock item brass_key", DOCS_HEADING, "F21", fields=("brass_key",)),
    StatementDoc(
        "unlock", "Give a tip or an item", "Story flow", "unlock tip|item <name> [<amount>]",
        "Adds a tip to the codex for good, or gives the player an item (with a number, that "
        "many).",
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

__all__ = ["ITEM_COUNT_MAX", "WORD_COUNT", "WORD_MONEY", "WORD_USE", "CATEGORIES_MAX", "CATEGORY_MAX", "CodexCategory", "CodexEntry", "CodexEntryDecl",
           "CodexLock", "DEFAULT_WORDS", "DOCS", "DOCS_HEADING", "ITEMS_MAX", "ITEM_TARGET", "KINDS",
           "NAME_MAX", "PARAGRAPHS_MAX", "PARAGRAPH_MAX", "TIPS_MAX", "TIP_TARGET",
           "TITLE_MAX", "build_entries", "codex_body", "parse_codex_decl", "parse_codex_lock",
           "register_words"]
