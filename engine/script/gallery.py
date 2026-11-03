"""The CG gallery's script side: ``lock gallery`` declarations and ``lock|unlock gallery``
lines (F34 ``04-technical.md`` §3, §7.1; ``01`` §5).

Why this module exists: the gallery is a list of pictures the author declares once, in order,
with a title each; players unlock a picture the first time it shows in the story (the stage
executors, ``runtime/gallery.py``). The words go through F19's ``lock``/``unlock`` specs as
one row of ``routes.LOCK_TARGETS``: ``LockTarget("gallery", top=…, block=…, body=…)``.

- **Top level**, ``lock gallery <picture> "Title"[:]`` → ``GalleryDecl``; an indented block
  lists up to ``VERSIONS_MAX`` more pictures, one name per line (**versions**, one tile in the
  gallery). ``unlock gallery`` there is E342's ``top`` form.
- **In a label**, ``lock|unlock gallery <picture>`` → F19's own ``Lock("gallery", picture,
  unlock)``, so F19's ``run_lock`` executes it (07 I-12's rule: one executor for every
  ``unlock <kind>``). A title after ``lock`` is E342's ``declare`` form; anything else left
  over is F19's E244 ``need`` form.

Picture names are read as ``show`` reads them (F04: at most 5 words, E117, E112, E126,
E127); a picture with no file is F04's launch warning, not a load error. ``gallery`` is read
only after ``lock``/``unlock`` and stays usable as a name. Messages: E342 (shape), E344
(title and versions). The whole-game checks (E343, E345, W226) are ``checks.py``'s;
``Program.gallery`` and ``Program.gallery_pictures`` are built by ``program.py`` with
``build_gallery``.

**Registration.** Importing this module registers the declaration's identity
(``"gallery:" + picture``) and calls ``register_words()`` once, after F19's ``routes`` and
F21's ``codex`` (``script/__init__.py`` imports it right after ``codex``). Calling it again
does nothing.
"""

import dataclasses
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from engine.script.chapter import _shown
from engine.script.diagnostics import Diagnostic
from engine.script.identity import register_declaration
from engine.script.lexer import HEAD_WORD, STRING, RawStatement
from engine.script.nodes import Node
from engine.script.routes import LOCK_TARGETS, WORD_LOCK, Lock, LockTarget, register_target
from engine.script.stage import TEXT, _Chunk, _chunks, _image_name, _written
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, get_spec

WORD_GALLERY: Final = "gallery"
GALLERY_MAX: Final = 500                 # gallery entries in a story (E343)
VERSIONS_MAX: Final = 8                  # more pictures under one entry (E344)
TITLE_MAX: Final = 60                    # code points as shown (E344)


# --- Values and nodes (04 §3) -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GalleryEntry:
    """One tile of the gallery (``Program.gallery``): its picture, title as shown (``{{`` is
    ``{``), and versions in written order. ``pictures`` is the entry picture, then the
    versions."""

    picture: str
    title: str
    versions: tuple[str, ...]
    sid: str
    file: str
    line: int

    @property
    def pictures(self) -> tuple[str, ...]:
        return (self.picture,) + self.versions


@dataclass(slots=True, kw_only=True)
class GalleryDecl(Node):
    """``lock gallery <picture> "Title"`` at the top level. A declaration, sid
    ``"gallery:" + picture``. ``versions`` and their ``version_lines`` are set by
    ``gallery_body``."""

    picture: str
    title: str
    versions: tuple[str, ...] = ()
    version_lines: tuple[int, ...] = field(default=(), compare=False)

    def places(self) -> Iterator[tuple[str, int]]:
        """Each picture with its line: the entry, then the versions."""
        yield self.picture, self.line
        yield from zip(self.versions, self.version_lines)


# --- Parsing (01 §5.1, §5.2) --------------------------------------------------------------------

def _verb(unlock: bool) -> str:
    return f"{'unlock' if unlock else 'lock'} {WORD_GALLERY}"


def _title(ctx: ParseContext, raw: RawStatement, chunk: _Chunk) -> str | None:
    """The title as shown: E344's ``tags``, ``empty``, and ``long`` forms."""
    written = next((t.text for t in raw.tokens
                    if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column)), "")
    shown = _shown(written)
    if shown is None:
        ctx.error("E344", "tags")
        return None
    if not shown.strip():
        ctx.error("E344", "empty")
        return None
    if len(shown) > TITLE_MAX:
        ctx.error("E344", "long", len(shown), TITLE_MAX)
        return None
    return shown


def parse_gallery_decl(raw: RawStatement, ctx: ParseContext, unlock: bool,
                       chunks: list[_Chunk], colon: bool) -> GalleryDecl | None:
    """The row's ``top``: picture words, then one title in quotes; the versions come from
    ``gallery_body``."""
    if unlock:
        ctx.error("E342", "top")
        return None
    at = next((i for i, chunk in enumerate(chunks) if chunk.kind == TEXT), None)
    if not at:                                       # no title, or no picture before it
        ctx.error("E342", "need")
        return None
    picture = _image_name(ctx, _verb(False), raw, chunks[:at])
    if picture is None:
        return None
    title = _title(ctx, raw, chunks[at])
    if title is None:
        return None
    if at + 1 < len(chunks):
        ctx.error("E342", "left", _written(raw, chunks[at + 1:]))
        return None
    return GalleryDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                       picture=picture, title=title)


def parse_gallery_lock(raw: RawStatement, ctx: ParseContext, unlock: bool,
                       chunks: list[_Chunk], colon: bool) -> Lock | None:
    """The row's ``block``: ``lock|unlock gallery <picture>``, F19's ``Lock`` node."""
    at = next((i for i, chunk in enumerate(chunks) if chunk.kind == TEXT), None)
    if at is not None:
        if not unlock and at > 0:
            ctx.error("E342", "declare", " ".join(c.text for c in chunks[:at]),
                      _written(raw, chunks[at:at + 1]))
        else:
            ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    if not chunks:
        ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    picture = _image_name(ctx, _verb(unlock), raw, chunks)
    if picture is None:
        return None
    if colon:
        ctx.error("E110", "colon", raw.word)
        return None
    return Lock(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                unlock=unlock, kind=WORD_GALLERY, name=picture)


# --- The block of a declaration: versions -------------------------------------------------------

def _version(raw: RawStatement, ctx: ParseContext) -> str | None:
    """One line under a declaration: a picture name and nothing else (E342's ``body`` form),
    read as ``show`` reads one."""
    if (raw.head != HEAD_WORD or raw.py is not None or not raw.tokens
            or get_spec(raw.word) is not None):
        ctx.error("E342", "body")
        return None
    # ``_chunks`` sets the statement word aside: give it the first token twice.
    chunks, colon = _chunks(dataclasses.replace(raw, tokens=[raw.tokens[0], *raw.tokens]))
    if colon or any(chunk.kind == TEXT for chunk in chunks):
        ctx.error("E342", "body")
        return None
    return _image_name(ctx, _verb(False), raw, chunks)


def _body_error(api, raw: RawStatement, depth: int) -> None:
    """E342's ``body`` form on a line the versions can't hold (reported like any line)."""
    api.parse_line(raw, depth, lambda _raw, ctx: ctx.error("E342", "body"))


def gallery_body(api, raw: RawStatement, node: object, depth: int, own_error: bool,
                 widths: tuple[int, ...]) -> Iterator[None]:
    """The row's ``body`` (the ``lock`` spec's ``block_parser``, F19 07 I-6): a top-level
    declaration's versions; any other line gets the block parser's own rule. Under a line
    with its own error the block is skipped quietly (one mistake, one message)."""
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
    if own_error or not isinstance(node, GalleryDecl):
        yield from api.skip_deeper(w, quiet=True)
        return
    reader = api.reader
    block_w = nxt.width
    body_widths = widths + (block_w,)
    phantom: int | None = None
    versions: list[str] = []
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
            _body_error(api, line, depth + 1)              # deeper than the versions
            yield from api.skip_deeper(block_w, quiet=True)
        else:
            phantom = api.check_width(line, block_w, phantom, body_widths)
            picture, error = api.parse_line(line, depth + 1, _version)
            count += 1
            if count == VERSIONS_MAX + 1:
                over = line
            if not error and picture is not None:
                versions.append(picture)  # type: ignore[arg-type]
                lines.append(line.line)
            elif error:                                    # its own lines aren't versions
                yield from api.skip_deeper(line.width, quiet=True)
        if api.due():
            yield
    if over is not None:
        api.ctx.sink.add(Diagnostic("E344", api.file, over.line, None,
                                    ("versions", count, VERSIONS_MAX),
                                    source_line=over.texts.get(over.line), stmt=over.line))
    node.versions = tuple(versions[:VERSIONS_MAX])
    node.version_lines = tuple(lines[:VERSIONS_MAX])


# --- Program.gallery (04 §3) --------------------------------------------------------------------

def build_gallery(decls: Iterable[GalleryDecl]
                  ) -> tuple[tuple[GalleryEntry, ...], Mapping[str, str]]:
    """The entries in the order given (include order, then line) and every picture (entry
    and version) → its entry's picture. Call after identities are assigned (``sid``)."""
    entries: list[GalleryEntry] = []
    pictures: dict[str, str] = {}
    for decl in decls:
        entries.append(GalleryEntry(picture=decl.picture, title=decl.title,
                                    versions=tuple(decl.versions), sid=decl.sid,
                                    file=decl.file.ref, line=decl.line))
        for picture in (decl.picture, *decl.versions):
            pictures.setdefault(picture, decl.picture)
    return tuple(entries), MappingProxyType(pictures)


# --- Registration -------------------------------------------------------------------------------

GALLERY_TARGET = LockTarget(WORD_GALLERY, parse_gallery_decl, parse_gallery_lock, gallery_body)

# The docs heading: section 7's "lock gallery, unlock gallery" in docs/script-language.md
# (F34 W5).
DOCS_HEADING: Final = "lock gallery, unlock gallery"

DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Gallery picture", "Declarations", 'lock gallery <picture> "title"',
        "Adds a picture to the gallery in Extras. Players unlock it the first time it shows "
        "in the story; pictures indented under it are more versions of the same tile.",
        'lock gallery cg river "By the River"', DOCS_HEADING, "F34",
        fields=("cg river", "By the River")),
)

# The in-label lines' docs: Insert opens Studio's Lock/Unlock form on "Gallery picture"
# (F34-W4); registered with ``DOCS``.
LABEL_DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Forget a gallery picture", "Story flow", "lock gallery <picture>",
        "Makes the game forget a gallery picture, so its tile is locked again.",
        "lock gallery cg festival", DOCS_HEADING, "F34", fields=("cg festival",)),
    StatementDoc(
        "unlock", "Unlock a gallery picture", "Story flow", "unlock gallery <picture>",
        "Adds a picture to the player's gallery for good without showing it.",
        "unlock gallery cg festival", DOCS_HEADING, "F34", fields=("cg festival",)),
)


def register_words() -> None:
    """Register the ``gallery`` row of F19's ``LOCK_TARGETS`` and its docs, once (at import,
    through ``script/__init__.py``); calling it again does nothing."""
    if LOCK_TARGETS.get(WORD_GALLERY) is GALLERY_TARGET:
        return
    register_target(GALLERY_TARGET)
    for doc in (*DOCS, *LABEL_DOCS):
        register_doc(doc)


register_declaration(GalleryDecl, lambda node: "gallery:" + node.picture)  # type: ignore[attr-defined]
register_words()

__all__ = ["DOCS", "DOCS_HEADING", "GALLERY_MAX", "LABEL_DOCS", "GALLERY_TARGET", "GalleryDecl",
           "GalleryEntry", "TITLE_MAX", "VERSIONS_MAX", "WORD_GALLERY", "build_gallery",
           "gallery_body", "parse_gallery_decl", "parse_gallery_lock", "register_words"]
