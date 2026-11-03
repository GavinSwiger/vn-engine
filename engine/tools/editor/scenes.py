"""Studio's scene index: each open script file read as label chunks (F46 ``04-technical.md``
§3.1, §6.1, §6.2; ``07`` I-1 to I-5).

Why this module exists: the story map has to follow typing within ``FOLLOW_MS``, but a full
re-read costs about 28 µs per line (19 s at the 16 MB cap), and the check child takes over
0.5 s just to start. So Studio splits each open file into label chunks, digests them, and
parses only the chunks that changed since the last good check (or that the view or an action
needs). The check child stays the authority for every other scene. Pure: no Tk.

- ``chunks`` finds ``label <name>:`` at column 0 (labels are top-level only, E24). A chunk
  runs from its label line to the line before the next one; lines above the first label start
  no chunk. Chunks are keyed ``(label, ordinal)`` (I-3): ordinal 0 is a name's first chunk in
  the file, so a duplicated label keeps both chunks.
- ``parse_chunk`` runs F02's parser on one chunk as the loader would (positions included),
  lines chunk-relative (the label line is 1). The first error becomes ``error``, and so does a
  ``RecursionError`` or ``MemoryError`` (I-4), so a hostile chunk can't take down a window that
  holds unsaved work. A chunk over ``SCENE_PARSE_MAX_LINES`` lines is not parsed (I-2): it
  reads ``SCENE_TOO_LONG``, and the map keeps the check child's links for it.
- Spans (§6.2): ``head`` is the statement's own logical line (for a choice or ``if``/``elif``/
  ``else`` header, up to the last code line before its block); ``span`` adds nested blocks and
  the blank lines and deeper-indented comments that follow (trailing blanks dropped); ``unit``
  adds the same-indent comment lines right above. Built iteratively, so nesting costs no
  recursion.
- ``reindex`` re-reads one file's text. Reads are reused by ``(digest, positions)`` (I-4). With
  no checked snapshot (``checked=None``), the digests at hand are the baseline (I-1): nothing is
  parsed but ``want``. A scene that stops parsing keeps its last good read in ``good``.
- ``map_data`` swaps each indexed file's labels and links into the check child's lists for the
  map (§6.1.6); ``out_of_date`` names the scenes to mark; ``duplicates`` and
  ``duplicate_text`` give the read-only reason for a label defined twice (F02's E25, I-3).
"""

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from hashlib import blake2b
from typing import Final

from engine.core.constants import BUILTIN_POSITIONS
from engine.script.diagnostics import DiagnosticSink
from engine.script.identity import assign
from engine.script.labelgraph import LabelLink, block_links
from engine.script.menu import Menu
from engine.script.messages import Place, format_message
from engine.script.nodes import If, Label, ScriptFile, Statement
from engine.script.parser import parse_file
from engine.script.statements import ParseContext
from engine.script.words import canonical_name
from engine.tools.editor.checker import NameEntry

FOLLOW_MS: Final = 500                  # the map follows typing after this pause (§6.1.1)
SCENE_ROW_CAP: Final = 2_000            # Events rows shown per scene (§6.7.1)
SCENE_PARSE_MAX_LINES: Final = 10_000   # I-2: about 0.3 s of parsing on the Tk thread
SCENE_TOO_LONG: Final = "This scene is too long to change here. Change it in the text."
DIGEST_SIZE: Final = 8
SINK_LIMIT: Final = 10_000
LABEL_START: Final = re.compile(r"^label[ \t]+([^\s:#]+)[ \t]*:", re.MULTILINE)

Key = tuple[str, int]                   # (label, ordinal in its file), I-3


@dataclass(frozen=True, slots=True)
class Span:
    """Physical lines ``first`` to ``last``, chunk-relative (the label line is 1)."""

    first: int
    last: int


@dataclass(frozen=True, slots=True)
class StmtRead:
    """One statement of a scene: its node, ``Statement.path``, and line spans."""

    node: Statement
    path: tuple[int, ...]
    head: Span                          # its own logical line
    span: Span                          # head + nested blocks + trailing deeper comments
    unit: Span                          # span + leading same-indent comments (move/delete)
    indent: str


@dataclass(frozen=True, slots=True)
class BlockRead:
    """One block: the label's (``owner`` None) or branch ``branch`` of the statement at
    ``owner`` (a menu's choice, an ``if``'s branch). ``head``/``span``/``unit`` are that
    choice's or branch header's spans (None for the label's block); ``members`` index
    ``SceneRead.statements``."""

    owner: tuple[int, ...] | None
    branch: int
    indent: str
    members: tuple[int, ...]
    head: Span | None = None
    span: Span | None = None
    unit: Span | None = None


@dataclass(frozen=True, slots=True)
class SceneRead:
    """One parsed chunk. ``links`` are ``block_links`` with chunk-relative lines; ``error``
    (``(line, text)``, chunk-relative) makes the scene read-only, with no statements."""

    ref: str
    name: str
    digest: bytes
    last: int                           # last line of the label's block
    statements: tuple[StmtRead, ...]    # pre-order
    blocks: tuple[BlockRead, ...]
    links: tuple[LabelLink, ...]
    error: tuple[int, str] | None


@dataclass(slots=True)
class SceneIndex:
    """One open script document's chunks. Every dict is in file order and keyed by ``Key``:
    ``starts`` the absolute line of each label line, ``digests`` every chunk's digest,
    ``reads`` the chunks parsed now (or reused), ``good`` each key's last read that parsed."""

    ref: str
    changes: int                        # OpenFile.changes when built
    starts: dict[Key, int]
    digests: dict[Key, bytes]
    reads: dict[Key, SceneRead]
    good: dict[Key, SceneRead] = field(default_factory=dict)
    checked: dict[Key, bytes] = field(default_factory=dict)
    positions: frozenset[str] = frozenset()

    def key_of(self, name: str) -> Key | None:
        """The first chunk of label ``name`` in this file, or None."""
        key = (name, 0)
        return key if key in self.starts else None


def digest(chunk: str) -> bytes:
    return blake2b(chunk.encode("utf-8", "surrogatepass"), digest_size=DIGEST_SIZE).digest()


def _line_count(text: str) -> int:
    """Physical lines: a final line break ends the last line, it doesn't start one."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _chunk_spans(text: str) -> list[tuple[str, int, int, int, int]]:
    """``(label, first line, last line, start offset, end offset)`` per chunk."""
    found: list[tuple[str, int, int]] = []          # (label, line, offset)
    line, at = 1, 0
    for match in LABEL_START.finditer(text):
        start = match.start()
        line += text.count("\n", at, start)
        at = start
        found.append((canonical_name(match.group(1)), line, start))
    total = _line_count(text)
    out = []
    for i, (name, first, start) in enumerate(found):
        if i + 1 < len(found):
            last, end = found[i + 1][1] - 1, found[i + 1][2]
        else:
            last, end = total, len(text)
        out.append((name, first, last, start, end))
    return out


def chunks(text: str) -> list[tuple[str, int, int]]:
    """``(label, first, last)`` absolute lines of each chunk, in file order."""
    return [(name, first, last) for name, first, last, _, _ in _chunk_spans(text)]


# --- Parsing one chunk (§6.1.5, §6.2) --------------------------------------------------------

def _indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


def _code_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


@dataclass(slots=True)
class _Item:
    """A statement (``stmt`` set) or a block header (a choice or ``if`` branch) while spans
    are built; ``parent`` is the enclosing item's index."""

    first: int
    head_last: int
    parent: int | None
    stmt: Statement | None = None
    path: tuple[int, ...] = ()
    nested: int = 0
    last: int = 0


def _header_head(header_line: int, block: Sequence[Statement], lines: Sequence[str]) -> int:
    """The last code line from ``header_line`` up to the block's first statement."""
    if not block:
        return header_line
    for number in range(block[0].line - 1, header_line, -1):
        if _code_line(lines[number - 1]):
            return number
    return header_line


def _spans(label: Label, lines: Sequence[str]
           ) -> tuple[tuple[StmtRead, ...], tuple[BlockRead, ...], int]:
    """Statements, blocks and the block's last line. Items are made parents first, so
    one backward pass builds every span from its children's."""
    items: list[_Item] = []
    stmt_items: list[int] = []                         # pre-order statement items
    # Blocks: (owner path, branch, header item or None, member item indexes)
    blocks: list[tuple[tuple[int, ...] | None, int, int | None, list[int]]] = []
    # Frames: (parent item, path prefix, block slot, (index, statement) left, reversed)
    top: list[int] = []
    blocks.append((None, 0, None, top))
    stack: list[tuple[int | None, tuple[int, ...], int, list[tuple[int, Statement]]]] = [
        (None, (), 0, list(reversed(list(enumerate(label.block)))))]
    while stack:
        parent, prefix, slot, pending = stack[-1]
        if not pending:
            stack.pop()
            continue
        j, stmt = pending.pop()
        path = prefix + (j,)
        index = len(items)
        items.append(_Item(stmt.line, stmt.end_line, parent, stmt, path))
        stmt_items.append(index)
        blocks[slot][3].append(index)
        inner = stmt.blocks()
        if not inner:
            continue
        headers = (stmt.choices if isinstance(stmt, Menu)
                   else stmt.branches if isinstance(stmt, If) else (None,) * len(inner))
        frames = []
        for b, (header, block) in enumerate(zip(headers, inner)):
            owner = index
            if header is not None:
                owner = len(items)
                items.append(_Item(header.line, _header_head(header.line, block, lines), index))
            blocks.append((path, b, owner if header is not None else None, []))
            frames.append((owner, path + (b,), len(blocks) - 1,
                           list(reversed(list(enumerate(block))))))
        stack.extend(reversed(frames))              # branch 0 is walked first

    count = len(lines)
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        last = max(item.head_last, item.nested)
        width = len(_indent(lines[item.first - 1]))
        number = last + 1
        while number <= count:
            text = lines[number - 1]
            if not text.strip():
                number += 1
                continue
            if text.lstrip().startswith("#") and len(_indent(text)) > width:
                last = number
                number += 1
                continue
            break
        item.last = last
        if item.parent is not None:
            parent_item = items[item.parent]
            parent_item.nested = max(parent_item.nested, last)

    def unit_first(item: _Item) -> int:
        indent = _indent(lines[item.first - 1])
        first = item.first
        while first > 2:
            above = lines[first - 2]
            if not above.lstrip().startswith("#") or _indent(above) != indent:
                break
            first -= 1
        return first

    position = {item_index: n for n, item_index in enumerate(stmt_items)}
    statements = tuple(
        StmtRead(items[i].stmt, items[i].path,  # type: ignore[arg-type]
                 Span(items[i].first, items[i].head_last), Span(items[i].first, items[i].last),
                 Span(unit_first(items[i]), items[i].last), _indent(lines[items[i].first - 1]))
        for i in stmt_items)
    reads = []
    for owner, branch, header, members in blocks:
        indent = _indent(lines[items[members[0]].first - 1]) if members else ""
        if header is None:
            reads.append(BlockRead(owner, branch, indent, tuple(position[m] for m in members)))
            continue
        item = items[header]
        reads.append(BlockRead(owner, branch, indent, tuple(position[m] for m in members),
                               Span(item.first, item.head_last), Span(item.first, item.last),
                               Span(unit_first(item), item.last)))
    last = max((items[i].last for i in top), default=1)
    return statements, tuple(reads), last


def parse_chunk(ref: str, chunk: str, *, positions: Collection[str] = ()) -> SceneRead | None:
    """One chunk (its label line first) parsed as the loader parses ``ref``; None when it
    doesn't start with a label line. ``positions``: the check child's ``position`` names."""
    match = LABEL_START.match(chunk)
    if match is None:
        return None
    name = canonical_name(match.group(1))
    chunk_digest = digest(chunk)

    def failed(line: int, text: str) -> SceneRead:
        return SceneRead(ref, name, chunk_digest, 1, (), (), (), (line, text))

    lines = chunk.split("\n")
    if chunk.endswith("\n"):
        lines.pop()
    if len(lines) > SCENE_PARSE_MAX_LINES:
        return failed(1, SCENE_TOO_LONG)
    ctx = ParseContext(sink=DiagnosticSink(limit=SINK_LIMIT),
                       position_names=frozenset(BUILTIN_POSITIONS) | frozenset(positions))
    try:
        nodes = parse_file(ScriptFile(ref, ref.removeprefix("script/"), 0), chunk, ctx)
        kept = ctx.sink.kept()
        if kept:
            first = kept[0]
            return failed(first.line or 1, first.message())
        label = next((n for n in nodes if isinstance(n, Label) and n.name == name), None)
        if label is None:
            return None
        assign((label,))
        statements, blocks, last = _spans(label, lines)
        links = tuple(block_links(name, label.block))
    except (RecursionError, MemoryError):
        return failed(1, format_message("E86", ("exec",)))
    return SceneRead(ref, name, chunk_digest, last, statements, blocks, links, None)


# --- The index (§6.1.2-4) ---------------------------------------------------------------------

def reindex(old: SceneIndex | None, ref: str, text: str, changes: int, *,
            checked: Mapping[Key, bytes] | None, want: Collection[str] = (),
            positions: Collection[str] = ()) -> SceneIndex:
    """``ref``'s index for ``text``. A chunk is parsed when its digest differs from
    ``checked`` (the last good check's digests) or its label is in ``want``; a read of the
    same digest and positions in ``old`` is reused instead. ``checked=None`` (no snapshot
    yet) takes this text's digests as checked (I-1)."""
    names = frozenset(positions)
    reuse: dict[bytes, SceneRead] = {}
    good: dict[Key, SceneRead] = {}
    if old is not None and old.ref == ref and old.positions == names:
        reuse = {read.digest: read for read in (*old.good.values(), *old.reads.values())}
    if old is not None and old.ref == ref:
        good = dict(old.good)
    starts: dict[Key, int] = {}
    digests: dict[Key, bytes] = {}
    reads: dict[Key, SceneRead] = {}
    ordinals: dict[str, int] = {}
    spans = _chunk_spans(text)
    for name, first, _, start, end in spans:
        n = ordinals[name] = ordinals.get(name, -1) + 1
        key = (name, n)
        chunk = text[start:end]
        chunk_digest = digest(chunk)
        starts[key] = first
        digests[key] = chunk_digest
        read = reuse.get(chunk_digest)
        if read is None and (name in want or (checked is not None
                                              and checked.get(key) != chunk_digest)):
            read = parse_chunk(ref, chunk, positions=names)
        if read is None:
            continue
        reads[key] = read
        if read.error is None:
            good[key] = read
    good = {key: read for key, read in good.items() if key in starts}
    return SceneIndex(ref, changes, starts, digests, reads, good,
                      dict(digests if checked is None else checked), names)


def out_of_date(indexes: Iterable[SceneIndex]) -> set[str]:
    """Labels whose chunk doesn't parse now (the map keeps their last links). A too-long
    chunk that equals the checked one is read-only, but its links are current."""
    stale: set[str] = set()
    for index in indexes:
        for key, read in index.reads.items():
            if read.error is None:
                continue
            if read.error[1] == SCENE_TOO_LONG and index.checked.get(key) == read.digest:
                continue
            stale.add(key[0])
    return stale


def _shift(links: Iterable[LabelLink], by: int) -> list[LabelLink]:
    return [replace(link, line=link.line + by) for link in links]


def map_data(labels: Iterable[NameEntry], links: Iterable[LabelLink],
             indexes: Mapping[str, SceneIndex]) -> tuple[list[NameEntry], list[LabelLink]]:
    """The check child's ``labels`` and ``links`` with each indexed file's swapped in: a
    parsed scene's own links, else its last good read's (when it doesn't parse now), else
    the child's (moved to where the label is now). Labels keep file order, from where the
    file's first child label was; files the child didn't list go last."""
    child_lines: dict[tuple[str, str], int] = {}
    out_labels: list[NameEntry] = []
    emitted: set[str] = set()

    def emit_file(ref: str) -> None:
        emitted.add(ref)
        index = indexes[ref]
        for (name, n), line in index.starts.items():
            if n == 0:
                out_labels.append(NameEntry(name, ref, line))

    for entry in labels:
        name, ref, line = entry.name, entry.file, entry.line
        if ref in indexes:
            if line is not None:
                child_lines.setdefault((ref, name), line)
            if ref not in emitted:
                emit_file(ref)
            continue
        out_labels.append(entry)
    for ref in indexes:
        if ref not in emitted:
            emit_file(ref)

    by_src: dict[str, list[LabelLink]] = {}
    child_in: dict[tuple[str, str], list[LabelLink]] = {}
    for link in links:
        if link.file in indexes:
            child_in.setdefault((link.file, link.src), []).append(link)
        else:
            by_src.setdefault(link.src, []).append(link)

    out_links: list[LabelLink] = []
    for entry in out_labels:
        name, ref = entry.name, entry.file
        index = indexes.get(ref) if ref is not None else None
        if index is None:
            out_links.extend(by_src.pop(name, ()))
            continue
        for key, start in index.starts.items():
            if key[0] != name:
                continue
            read = index.reads.get(key)
            if read is not None and read.error is not None:
                read = index.good.get(key)
            if read is not None:
                out_links.extend(_shift(read.links, start - 1))
            elif key[1] == 0:
                old = child_lines.get((ref, name))
                out_links.extend(_shift(child_in.get((ref, name), ()),
                                        0 if old is None else start - old))
    for rest in by_src.values():
        out_links.extend(rest)
    return out_labels, out_links


# --- Duplicated labels (I-3) ------------------------------------------------------------------

def duplicates(labels: Iterable[NameEntry], indexes: Mapping[str, SceneIndex]
               ) -> dict[str, tuple[Place, ...]]:
    """Each label defined more than once, among the indexed chunks and the check child's
    labels of files that aren't indexed: label → every place, in order. Such a label is
    read-only everywhere it appears."""
    places: dict[str, list[Place]] = {}
    for entry in labels:
        if entry.file is None or entry.file in indexes or entry.line is None:
            continue
        places.setdefault(entry.name, []).append((entry.file, entry.line))
    for ref, index in indexes.items():
        for (name, _), line in index.starts.items():
            places.setdefault(name, []).append((ref, line))
    return {name: tuple(found) for name, found in places.items() if len(found) > 1}


def duplicate_text(name: str, here: Place, places: Sequence[Place]) -> str:
    """F02's E25 text for ``name`` at ``here``, naming its other places."""
    return format_message("E25", (name, [place for place in places if place != here]))


__all__ = ["BlockRead", "DIGEST_SIZE", "FOLLOW_MS", "Key", "LABEL_START", "SCENE_PARSE_MAX_LINES",
           "SCENE_ROW_CAP", "SCENE_TOO_LONG", "SceneIndex", "SceneRead", "Span", "StmtRead",
           "chunks", "digest", "duplicate_text", "duplicates", "map_data", "out_of_date",
           "parse_chunk", "reindex"]
