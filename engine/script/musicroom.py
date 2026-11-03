"""The music room's script side: ``lock track`` declarations (F35 ``SPEC.md`` §2 PR-F35-01,
02; §3 SR-F35-01, 02; §5.1).

Why this module exists: the title's Music Room (Extras) lists the tracks the author declares
once, in order, each with a title, a file and the rule that opens it. The words go through
F19's ``lock``/``unlock`` specs as one row of ``routes.LOCK_TARGETS``: ``LockTarget("track",
top=…, block=…)``.

- **Top level**, ``lock track <name> "Title" file "<audio file>" [open | until e1, e2]`` →
  ``TrackDecl``. No ``open``/``until``: the default rule (the track opens the first time the
  story plays its file); ``open``: always open; ``until``: open while every named ending is
  reached (``runtime/musicroom.py`` decides, at display).
- ``lock track`` in a label and ``unlock track`` anywhere are E336 (there is no in-label form:
  a track opens when the story plays its music).

The name is read as F19 reads a route's (script-language §6, E60–E64; at most ``NAME_MAX``
code points, E242's name form for a ``track``); the title as shown (``{{`` is ``{``, no text
tags, 1–``TITLE_MAX`` code points); the file as ``play music`` reads one (E143–E145, inside
``audio/``); ``until`` takes 1–``UNTIL_MAX`` ending names separated by commas (a name given
twice counts once). ``track``, ``file``, ``open`` and ``until`` are read only after ``lock``
and stay usable as names. Messages: E336 (every shape). The whole-game checks (E337, E338,
W220, W221) are ``checks.py``'s; ``Program.tracks`` is built by ``program.py`` with
``build_tracks``.

**Registration.** Importing this module registers the declaration's identity (``"track:" +
name``) and calls ``register_words()`` once, after F19's ``routes``, F21's ``codex`` and F34's
``gallery`` (``script/__init__.py`` imports it right after ``gallery``). Calling it again does
nothing.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from engine.script.audio import file_problem
from engine.script.chapter import _shown
from engine.script.identity import register_declaration
from engine.script.lexer import NAME, STRING, SYMBOL, RawStatement
from engine.script.nodes import Node
from engine.script.routes import LOCK_TARGETS, WORD_LOCK, LockTarget, _name, register_target
from engine.script.stage import TEXT, WORD, _Chunk, _written
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext
from engine.script.words import canonical_name, check_name

WORD_TRACK: Final = "track"
WORD_FILE: Final = "file"
WORD_OPEN: Final = "open"
WORD_UNTIL: Final = "until"
TRACKS_MAX: Final = 200                  # tracks in a story (E337)
NAME_MAX: Final = 64                     # code points (E242's name form)
TITLE_MAX: Final = 60                    # code points as shown (E336)
UNTIL_MAX: Final = 32                    # ending names after until (E336)


# --- Values and nodes ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Track:
    """One music-room track (``Program.tracks``, declaration order): its name (the record
    key), title as shown, ``file`` as written (inside ``audio/``), its rule (``open``;
    ``until`` endings, () when none), and its place (``script`` file ref, ``line``).
    ``runtime/musicroom.py``'s ``TrackDeclLike``."""

    name: str
    title: str
    file: str
    open: bool
    until: tuple[str, ...]
    sid: str
    script: str
    line: int


@dataclass(slots=True, kw_only=True)
class TrackDecl(Node):
    """``lock track <name> "Title" file "<audio file>" [open | until a, b]`` at the top level.
    A declaration, sid ``"track:" + name``. ``audio_file`` is the file as written (``Node.file``
    is the script file); ``always_open`` is the ``open`` rule (an ``.open`` attribute would read
    as a file call to F02's no-file-API check, AC-F02-66)."""

    name: str
    title: str
    audio_file: str
    always_open: bool = False
    until: tuple[str, ...] = ()


# --- Parsing ------------------------------------------------------------------------------------

def _string(raw: RawStatement, chunk: _Chunk) -> str:
    """A quoted chunk's text as written (escapes already read by the lexer)."""
    return next((t.text for t in raw.tokens
                 if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column)), "")


def _title(ctx: ParseContext, raw: RawStatement, chunk: _Chunk) -> str | None:
    """The title as shown: E336's ``tags``, ``empty`` and ``long`` forms."""
    shown = _shown(_string(raw, chunk))
    if shown is None:
        ctx.error("E336", "tags")
        return None
    if not shown.strip():
        ctx.error("E336", "empty")
        return None
    if len(shown) > TITLE_MAX:
        ctx.error("E336", "long", len(shown), TITLE_MAX)
        return None
    return shown


def _until(ctx: ParseContext, raw: RawStatement, chunk: _Chunk,
           colon: bool) -> tuple[str, ...] | None:
    """The ending names after ``until``: 1–``UNTIL_MAX`` names separated by commas (E336's
    ``until`` form), each a name (E60–E64); a name given twice counts once."""
    tokens = list(raw.tokens)
    if colon:
        tokens.pop()
    at = next(i for i, t in enumerate(tokens) if (t.line, t.column) == (chunk.line, chunk.column))
    rest = tokens[at + 1:]
    written: list[str] = []
    for index, token in enumerate(rest):
        if index % 2 == 0:
            if token.kind != NAME:
                ctx.error("E336", "until")
                return None
            written.append(token.text)
        elif not (token.kind == SYMBOL and token.text == ","):
            ctx.error("E336", "until")
            return None
    if not rest or len(rest) % 2 == 0 or len(written) > UNTIL_MAX:   # none, a trailing comma
        ctx.error("E336", "until")
        return None
    names: list[str] = []
    for text in written:
        problem = check_name(text)
        if problem is not None:
            ctx.error(problem[0], *problem[1])
            return None
        name = canonical_name(text)
        if name not in names:
            names.append(name)
    return tuple(names)


def parse_track_decl(raw: RawStatement, ctx: ParseContext, unlock: bool,
                     chunks: list[_Chunk], colon: bool) -> TrackDecl | None:
    """The row's ``top``: name, title, ``file "…"``, then ``open`` or ``until`` endings."""
    if unlock:
        ctx.error("E336", "unlock")
        return None
    if len(chunks) < 2 or chunks[0].kind != WORD or chunks[1].kind != TEXT:
        ctx.error("E336", "need")
        return None
    at = next((i for i in range(2, len(chunks))
               if chunks[i].kind == WORD and chunks[i].text == WORD_FILE), None)
    if at is None or at + 1 >= len(chunks) or chunks[at + 1].kind != TEXT \
            or not _string(raw, chunks[at + 1]):
        ctx.error("E336", "need")
        return None
    if at > 2:                                        # something between the title and file
        ctx.error("E336", "left", _written(raw, chunks[2:at]))
        return None
    name = _name(ctx, chunks[0], WORD_TRACK)
    if name is None:
        return None
    title = _title(ctx, raw, chunks[1])
    if title is None:
        return None
    audio_file = _string(raw, chunks[at + 1])
    problem = file_problem(audio_file)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    rest = chunks[at + 2:]
    is_open = False
    until: tuple[str, ...] = ()
    if rest:
        word = rest[0].text if rest[0].kind == WORD else None
        if word == WORD_OPEN:
            if len(rest) > 1:
                ctx.error("E336", "left", _written(raw, rest[1:]))
                return None
            is_open = True
        elif word == WORD_UNTIL:
            found = _until(ctx, raw, rest[0], colon)
            if found is None:
                return None
            until = found
        else:
            ctx.error("E336", "left", _written(raw, rest))
            return None
    if colon:
        ctx.error("E110", "colon", WORD_LOCK)
        return None
    return TrackDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     name=name, title=title, audio_file=audio_file, always_open=is_open,
                     until=until)


def parse_track_lock(raw: RawStatement, ctx: ParseContext, unlock: bool,
                     chunks: list[_Chunk], colon: bool) -> None:
    """The row's ``block``: there is none. ``unlock track`` is E336's ``unlock`` form, and
    ``lock track`` in a label its ``top`` form (naming the line's name and title)."""
    if unlock:
        ctx.error("E336", "unlock")
        return None
    name = chunks[0].text if chunks and chunks[0].kind == WORD else None
    title = _written(raw, chunks[1:2]) if len(chunks) > 1 and chunks[1].kind == TEXT else None
    ctx.error("E336", "top", *((name, title) if name is not None else ()))
    return None


# --- Program.tracks -----------------------------------------------------------------------------

def build_tracks(decls: Iterable[TrackDecl]) -> tuple[Track, ...]:
    """The tracks in the order given (reading order). Call after identities are assigned
    (``sid``)."""
    return tuple(Track(name=d.name, title=d.title, file=d.audio_file, open=d.always_open,
                       until=tuple(d.until), sid=d.sid, script=d.file.ref, line=d.line)
                 for d in decls)


# --- Registration -------------------------------------------------------------------------------

TRACK_TARGET = LockTarget(WORD_TRACK, parse_track_decl, parse_track_lock)

# The docs heading: docs/script-language.md section 7's music-room part.
DOCS_HEADING: Final = "lock track (music room)"

DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Music room track", "Declarations",
        'lock track <name> "title" file "<file>" [open | until <ending>, ...]',
        "Lists a music file in the Music Room under the title's Extras. It opens the first "
        "time the story plays it; with open it is there from the start, with until once the "
        "player has reached those endings.",
        'lock track theme "Main Theme" file "bgm/theme.wav" open', DOCS_HEADING, "F35",
        fields=("theme", "Main Theme", "bgm/theme.wav")),
)


def register_words() -> None:
    """Register the ``track`` row of F19's ``LOCK_TARGETS`` and its docs, once (at import,
    through ``script/__init__.py``); calling it again does nothing."""
    if LOCK_TARGETS.get(WORD_TRACK) is TRACK_TARGET:
        return
    register_target(TRACK_TARGET)
    for doc in DOCS:
        register_doc(doc)


register_declaration(TrackDecl, lambda node: "track:" + node.name)  # type: ignore[attr-defined]
register_words()

__all__ = ["DOCS", "DOCS_HEADING", "NAME_MAX", "TITLE_MAX", "TRACKS_MAX", "TRACK_TARGET",
           "Track", "TrackDecl", "UNTIL_MAX", "WORD_TRACK", "build_tracks", "parse_track_decl",
           "parse_track_lock", "register_words"]
