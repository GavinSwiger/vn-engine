"""Scene replays' script side: ``lock replay`` declarations and ``lock|unlock replay`` lines
(F36 ``04-technical.md`` §3, §7.5; ``01`` §5).

Why this module exists: the title's Extras has a Scenes page that lists the scenes the author
marks for replay, in order, each with a title; a scene unlocks the first time the player
reaches its label (``runtime/replay.py``, F36-W2). The words go through F19's
``lock``/``unlock`` specs as one row of ``routes.LOCK_TARGETS``: ``LockTarget("replay",
top=…, block=…, body=…)``.

- **Top level**, ``lock replay <scene> "Title" [image <picture>] [to <scene>][:]`` →
  ``ReplayDecl``; an indented block holds up to ``VALUES_MAX`` **starting values**, one
  ``name = literal`` per line (SR-F36-03). ``unlock replay`` there is E348's ``top`` form.
- **In a label**, ``lock|unlock replay <scene>`` → F19's own ``Lock("replay", scene,
  unlock)``, so F19's ``run_lock`` executes it (07 I-12's rule: one executor for every
  ``unlock <kind>``). A title after ``lock`` is E348's ``declare`` form; anything else left
  over is F19's E244 ``need`` form.

The scene and ``to`` are label names (E64 for a word Python can't use); the title as shown
(``{{`` is ``{``, no text tags, 1–``TITLE_MAX`` code points); the picture as ``show`` reads
one (F04: at most 5 words, E117, E112, E126, E127; a picture with no file is F04's launch
warning). A starting value is a literal read by F44's ``parse_literal`` (never evaluated)
and must be a number, quoted text, ``True``, ``False`` or ``None`` (E352). ``replay``,
``image`` and ``to`` are read only after ``lock``/``unlock replay`` and stay usable as names.
Messages: E348 (shape), E350 (title, number of values), E351's ``own`` form (``to`` names
the scene itself), E352's ``value``, ``twice`` and dotted-name forms. The whole-game checks
(E349, E351, E352's variable form) are ``checks.py``'s; ``Program.replays`` is built by
``program.py`` with ``build_replays``.

**Registration.** Importing this module registers the declaration's identity
(``"replay:" + label``) and calls ``register_words()`` once, after F19's ``routes``, F21's
``codex``, F34's ``gallery`` and F35's ``musicroom`` (``script/__init__.py`` imports it right
after ``musicroom``). Calling it again does nothing.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Final

from engine.core.startvalues import StartValueError, parse_literal
from engine.script.chapter import _shown
from engine.script.diagnostics import Diagnostic
from engine.script.identity import register_declaration, walk_block
from engine.script.lexer import EQUALS, HEAD_WORD, NAME, STRING, SYMBOL, RawStatement
from engine.script.nodes import Label, Node
from engine.script.routes import LOCK_TARGETS, WORD_LOCK, Lock, LockTarget, register_target
from engine.script.stage import TEXT, WORD, Scene, _Chunk, _chunks, _image_name, _written
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, get_spec
from engine.script.words import ROLE_VARIABLE, canonical_name, check_name, is_name

WORD_REPLAY: Final = "replay"
WORD_IMAGE: Final = "image"
WORD_TO: Final = "to"
REPLAYS_MAX: Final = 500                 # replays in a story (E349)
VALUES_MAX: Final = 32                   # starting values under one replay (E350)
TITLE_MAX: Final = 60                    # code points as shown (E350)

# The kinds of value a starting value may be (SR-F36-03): F44's literals without lists and
# dicts. ``bool`` is listed for clarity; it is an ``int``.
_VALUE_TYPES: Final = (type(None), bool, int, float, str)


# --- Values and nodes (04 §3) -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ReplayEntry:
    """One scene replay (``Program.replays``, reading order): the scene's ``label``, the
    title as shown (``{{`` is ``{``), the declared ``image`` (a picture name, or None), the
    ``tile_picture`` (the first picture a ``scene`` line shows in the label's own lines, or
    None; PR-F36-07), ``to`` (the scene that ends the replay, or None), the starting
    ``values`` in written order (F44's ``StartOptions.values`` shape), and its place (``file``
    ref, ``line``). F36-P2's ``ScenesPage`` reads ``label``, ``title``, ``image`` and
    ``tile_picture``."""

    label: str
    title: str
    image: str | None
    tile_picture: str | None
    to: str | None
    values: tuple[tuple[str, object], ...]
    sid: str
    file: str
    line: int


@dataclass(slots=True, kw_only=True)
class ReplayDecl(Node):
    """``lock replay <scene> "Title" [image <picture>] [to <scene>]`` at the top level. A
    declaration, sid ``"replay:" + label``. ``values`` and their ``value_lines`` are set by
    ``replay_body``. (``Node.file`` is the script file, so the scene is ``label``.)"""

    label: str
    title: str
    image: str | None = None
    to: str | None = None
    values: tuple[tuple[str, object], ...] = ()
    value_lines: tuple[int, ...] = field(default=(), compare=False)


# --- Parsing (01 §5.1, §5.2) --------------------------------------------------------------------

def _string(raw: RawStatement, chunk: _Chunk) -> str:
    """A quoted chunk's text as written (escapes already read by the lexer)."""
    return next((t.text for t in raw.tokens
                 if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column)), "")


def _title(ctx: ParseContext, raw: RawStatement, chunk: _Chunk) -> str | None:
    """The title as shown: E350's ``tags``, ``empty`` and ``long`` forms."""
    shown = _shown(_string(raw, chunk))
    if shown is None:
        ctx.error("E350", "tags")
        return None
    if not shown.strip():
        ctx.error("E350", "empty")
        return None
    if len(shown) > TITLE_MAX:
        ctx.error("E350", "long", len(shown), TITLE_MAX)
        return None
    return shown


def _scene(ctx: ParseContext, chunk: _Chunk) -> str | None:
    """A scene (label) name: E64 for a word Python can't use."""
    if not is_name(chunk.text):
        ctx.error("E64", chunk.text)
        return None
    return canonical_name(chunk.text)


def _is(chunk: _Chunk, word: str) -> bool:
    return chunk.kind == WORD and chunk.text == word


def parse_replay_decl(raw: RawStatement, ctx: ParseContext, unlock: bool,
                      chunks: list[_Chunk], colon: bool) -> ReplayDecl | None:
    """The row's ``top``: scene, title, then ``image <picture>`` and ``to <scene>`` in that
    order; the starting values come from ``replay_body``."""
    if unlock:
        ctx.error("E348", "top")
        return None
    if len(chunks) < 2 or chunks[0].kind != WORD or chunks[1].kind != TEXT:
        ctx.error("E348", "need")
        return None
    label = _scene(ctx, chunks[0])
    if label is None:
        return None
    title = _title(ctx, raw, chunks[1])
    if title is None:
        return None
    rest = chunks[2:]
    image: str | None = None
    to: str | None = None
    if rest and _is(rest[0], WORD_IMAGE):
        end = next((i for i in range(2, len(rest)) if _is(rest[i], WORD_TO)), len(rest))
        image = _image_name(ctx, WORD_IMAGE, raw, rest[1:end])
        if image is None:
            return None
        rest = rest[end:]
    if rest and _is(rest[0], WORD_TO):
        if len(rest) < 2 or rest[1].kind != WORD:
            ctx.error("E348", "to")
            return None
        to = _scene(ctx, rest[1])
        if to is None:
            return None
        if to == label:
            ctx.error("E351", "own", to)
            return None
        rest = rest[2:]
    if rest:
        ctx.error("E348", "left", _written(raw, rest))
        return None
    return ReplayDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                      label=label, title=title, image=image, to=to)


def parse_replay_lock(raw: RawStatement, ctx: ParseContext, unlock: bool,
                      chunks: list[_Chunk], colon: bool) -> Lock | None:
    """The row's ``block``: ``lock|unlock replay <scene>``, F19's ``Lock`` node."""
    if len(chunks) != 1 or chunks[0].kind != WORD:
        if not unlock and len(chunks) > 1 and chunks[0].kind == WORD and chunks[1].kind == TEXT:
            ctx.error("E348", "declare", canonical_name(chunks[0].text),
                      _written(raw, chunks[1:2]))
        else:
            ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    label = _scene(ctx, chunks[0])
    if label is None:
        return None
    if colon:
        ctx.error("E110", "colon", raw.word)
        return None
    return Lock(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                unlock=unlock, kind=WORD_REPLAY, name=label)


# --- The block of a declaration: starting values ------------------------------------------------

def _value(raw: RawStatement, ctx: ParseContext) -> tuple[str, object] | None:
    """One line under a declaration: ``name = literal`` (E348's ``body`` form for any other
    shape; E352 for a dotted name or a value that isn't a literal)."""
    if (raw.head != HEAD_WORD or raw.py is not None or not raw.tokens or raw.ends_with_colon
            or get_spec(raw.word) is not None):
        ctx.error("E348", "body")
        return None
    tokens = raw.tokens
    equals = next((i for i, t in enumerate(tokens)
                   if t.kind == EQUALS or (t.kind == SYMBOL and t.text == "=")), None)
    if equals is None or equals == 0:
        ctx.error("E348", "body")
        return None
    before = tokens[:equals]
    if len(before) > 1:
        if (len(before) % 2 == 1
                and all(t.kind == NAME if i % 2 == 0 else (t.kind == SYMBOL and t.text == ".")
                        for i, t in enumerate(before))):
            dotted = "".join(t.text for t in before)
            ctx.error("E352", "variable", dotted)           # persistent.x and the like
        else:
            ctx.error("E348", "body")
        return None
    if before[0].kind != NAME:
        ctx.error("E348", "body")
        return None
    text = raw.rest_after(tokens[equals])
    if not text:
        ctx.error("E348", "body")
        return None
    problem = check_name(before[0].text, ROLE_VARIABLE)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    try:
        value = parse_literal(text)
    except StartValueError:
        ctx.error("E352", "value", text)
        return None
    if type(value) not in _VALUE_TYPES:                      # a list or a dict
        ctx.error("E352", "value", text)
        return None
    return canonical_name(before[0].text), value


def _body_error(api, raw: RawStatement, depth: int) -> None:
    """E348's ``body`` form on a line the values can't hold (reported like any line)."""
    api.parse_line(raw, depth, lambda _raw, ctx: ctx.error("E348", "body"))


def replay_body(api, raw: RawStatement, node: object, depth: int, own_error: bool,
                widths: tuple[int, ...]) -> Iterator[None]:
    """The row's ``body`` (the ``lock`` spec's ``block_parser``, F19 07 I-6): a top-level
    declaration's starting values; any other line gets the block parser's own rule. Under a
    line with its own error the block is skipped quietly (one mistake, one message)."""
    if depth != 0 or not raw.ends_with_colon:
        if raw.ends_with_colon:
            yield from api.block_of(raw, node, depth, own_error, widths)
        return
    w = raw.width
    nxt = yield from api.peek()
    if nxt is None or nxt.width <= w:
        if not own_error:
            api.empty_block(raw, raw.word, nxt)
        return
    if own_error or not isinstance(node, ReplayDecl):
        yield from api.skip_deeper(w, quiet=True)
        return
    reader = api.reader
    block_w = nxt.width
    body_widths = widths + (block_w,)
    phantom: int | None = None
    values: list[tuple[str, object]] = []
    lines: list[int] = []
    count = 0
    over: RawStatement | None = None
    while True:
        line = yield from api.peek()
        if line is None or line.width <= w:
            break
        reader.next()
        api.ctx.statement_count += 1
        if line.width > block_w and line.width != phantom:
            _body_error(api, line, depth + 1)              # deeper than the values
            yield from api.skip_deeper(block_w, quiet=True)
        else:
            phantom = api.check_width(line, block_w, phantom, body_widths)
            found, error = api.parse_line(line, depth + 1, _value)
            count += 1
            if count == VALUES_MAX + 1:
                over = line
            if not error and found is not None:
                name, _ = found  # type: ignore[misc]
                if any(name == n for n, _ in values):
                    api.ctx.sink.add(Diagnostic("E352", api.file, line.line, None,
                                                ("twice", name),
                                                source_line=line.texts.get(line.line),
                                                stmt=line.line))
                else:
                    values.append(found)  # type: ignore[arg-type]
                    lines.append(line.line)
            elif error:                                    # its own lines aren't values
                yield from api.skip_deeper(line.width, quiet=True)
        if api.due():
            yield
    if over is not None:
        api.ctx.sink.add(Diagnostic("E350", api.file, over.line, None,
                                    ("values", count, VALUES_MAX),
                                    source_line=over.texts.get(over.line), stmt=over.line))
    node.values = tuple(values[:VALUES_MAX])
    node.value_lines = tuple(lines[:VALUES_MAX])


# --- Program.replays (04 §3, §7.5) --------------------------------------------------------------

def first_scene_picture(label: Label | None) -> str | None:
    """PR-F36-07: the first picture a ``scene`` line shows in the label's own lines (its
    nested blocks included, reading order; called labels are not looked into), or None."""
    if label is None:
        return None
    for stmt, _ in walk_block(label.block):
        if isinstance(stmt, Scene) and stmt.image is not None:
            return stmt.image
    return None


def build_replays(decls: Iterable[ReplayDecl],
                  labels: Mapping[str, Label]) -> tuple[ReplayEntry, ...]:
    """The replays in the order given (reading order), each with its tile picture from
    ``labels``. Call after identities are assigned (``sid``)."""
    return tuple(ReplayEntry(label=d.label, title=d.title, image=d.image,
                             tile_picture=first_scene_picture(labels.get(d.label)), to=d.to,
                             values=tuple(d.values), sid=d.sid, file=d.file.ref, line=d.line)
                 for d in decls)


# --- Registration -------------------------------------------------------------------------------

REPLAY_TARGET = LockTarget(WORD_REPLAY, parse_replay_decl, parse_replay_lock, replay_body)

# The docs heading: docs/script-language.md section 7's "lock replay (scene replays)".
DOCS_HEADING: Final = "lock replay (scene replays)"

DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Scene replay", "Declarations",
        'lock replay <scene> "title" [image <picture>] [to <scene>]',
        "Lets players watch a scene again from the Scenes page in Extras. It unlocks the "
        "first time the story reaches the scene; starting values for variables can be "
        "indented under it.",
        'lock replay river "By the River"', DOCS_HEADING, "F36",
        fields=("river", "By the River")),
)

# The in-label lines' docs: Insert opens Studio's Lock/Unlock form on "Scene replay" (F36-W4
# registered them with that form's choice: Studio's form registry checks every in-label
# lock/unlock doc has a form, AC-F47-33, F45's ``missing_forms``).
LABEL_DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Forget a scene replay", "Story flow", "lock replay <scene>",
        "Makes the game forget a scene replay, so its tile is locked again.",
        "lock replay lantern_stall", DOCS_HEADING, "F36", fields=("lantern_stall",)),
    StatementDoc(
        "unlock", "Unlock a scene replay", "Story flow", "unlock replay <scene>",
        "Adds a scene to the player's Scenes page for good without playing it.",
        "unlock replay lantern_stall", DOCS_HEADING, "F36", fields=("lantern_stall",)),
)


def register_words() -> None:
    """Register the ``replay`` row of F19's ``LOCK_TARGETS`` and its docs, once (at import,
    through ``script/__init__.py``); calling it again does nothing."""
    if LOCK_TARGETS.get(WORD_REPLAY) is REPLAY_TARGET:
        return
    register_target(REPLAY_TARGET)
    for doc in (*DOCS, *LABEL_DOCS):     # LABEL_DOCS: Studio's Lock/Unlock "Scene replay"
        register_doc(doc)


register_declaration(ReplayDecl, lambda node: "replay:" + node.label)  # type: ignore[attr-defined]
register_words()

__all__ = ["DOCS", "DOCS_HEADING", "LABEL_DOCS", "REPLAYS_MAX", "REPLAY_TARGET", "ReplayDecl",
           "ReplayEntry", "TITLE_MAX", "VALUES_MAX", "WORD_REPLAY", "build_replays",
           "first_scene_picture", "parse_replay_decl", "parse_replay_lock", "register_words",
           "replay_body"]
