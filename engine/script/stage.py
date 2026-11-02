"""The stage statements ``scene``, ``show``, ``hide`` and the ``image`` declaration (F04
``04-technical.md`` §6.1; ``02-script.md`` §3.2–3.7, §3.11; load codes E110–E118, E120–E127,
E130–E132).

Why this module exists: it turns stage lines into small frozen-shaped nodes that hold names
and numbers as written (no pixels, no paths looked up), so the runtime can apply them to the
stage state and the launch check can compare image names with the image index. Every check
that needs only the line itself is made here, at load; checks that need the image files or
the evaluated characters (W10–W16, E135) are made at launch.

The statements are read over F02's script tokens. Tokens that touch (no space between them)
are grouped into one *chunk* first: ``hana/happy.png``, ``400px``, ``-1300`` and ``2560.5``
are one chunk each, which is what an author sees as one word. A chunk is a WORD (one name), a
NUMBER (``-?digits[.digits]``, SR-F02-36's ``number``; a bare number the scanner reads as a
name is a NUMBER), a STRING (quoted text), or OTHER. A trailing ``:`` is set aside and is E110
when nothing else is wrong.

F09 (C5): ``with`` is read by ``effects.parse_with`` into a ``WithClause`` (field
``with_clause``); E113 and E115 stay here. ``effects`` imports this module's chunk reader, so
it is imported here only inside ``_with_part``.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from engine.core.constants import (
    IMAGE_SUFFIXES,
    LAYER_RANGE,
    STAGE_COORD_RANGE,
    STAGE_WORDS,
    STATEMENT_WORDS,
    ZOOM_RANGE,
)
from engine.core.errors import AssetRefError
from engine.core.paths import REASON_OUTSIDE, check_ref
from engine.script.identity import register_declaration
from engine.script.lexer import (
    COLON,
    EQUALS,
    FWCOLON,
    NAME,
    STRING,
    TAIL_SCRIPT,
    RawStatement,
    Token,
)
from engine.script.nodes import Node, Statement
from engine.script.statements import ParseContext, StatementSpec, register
from engine.script.suggest import suggest
from engine.script.words import SHOW_MODIFIER_WORDS, canonical_name, is_image_word, is_word_char

if TYPE_CHECKING:
    from engine.script.effects import WithClause

IMAGE_NAME_MAX_WORDS = 5                         # SR-F04-01

# Chunk kinds.
WORD = "word"
NUMBER = "number"
TEXT = "string"
OTHER = "other"

_NUMBER_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
_UNITS_RE = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:px|pt|em|rem|vw|vh|cm|mm|in|u|units?)",
                       re.IGNORECASE)
_EXTENSION_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]*\Z")
_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")


# --- Nodes (04 §6.1) -------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class At:
    """Where ``at`` puts a sprite, as written: a position name, or x and an optional y in
    canvas units (int when written without a decimal point, else float). The name is looked
    up when drawn (SR-F04-14)."""

    name: str | None = None
    x: int | float | None = None
    y: int | float | None = None


@dataclass(slots=True, kw_only=True)
class Scene(Statement):
    """``scene [image] [with …]``: every sprite leaves and ``image`` (None: the empty stage)
    becomes the background (SR-F04-07)."""

    image: str | None
    with_clause: "WithClause | None" = None

    def identity_key(self) -> tuple[str, ...]:
        return ("scene", self.image or "")


@dataclass(slots=True, kw_only=True)
class Show(Statement):
    """``show <image> [modifiers]`` (SR-F04-08–17). A field is None when the line doesn't
    give it, so the runtime keeps the sprite's value (SR-F04-11)."""

    image: str
    tag: str | None = None                   # the word after ``as``
    at: At | None = None
    behind: str | None = None
    layer: int | None = None
    zoom: float | None = None
    flip: bool | None = None
    with_clause: "WithClause | None" = None

    def identity_key(self) -> tuple[str, ...]:
        return ("show", self.image, self.tag or "")


@dataclass(slots=True, kw_only=True)
class Hide(Statement):
    """``hide <tag> [with …]`` (SR-F04-18)."""

    tag: str
    with_clause: "WithClause | None" = None

    def identity_key(self) -> tuple[str, ...]:
        return ("hide", self.tag)


@dataclass(slots=True, kw_only=True)
class ImageDecl(Node):
    """``image <name> = "<file or color>"`` (SR-F04-04, 05): exactly one of ``ref`` (a path
    relative to the game folder, PR-F01-55) and ``color`` is set. A declaration, not a
    position: its sid is ``"image:" + name`` and ``Program.get`` never returns it."""

    name: str
    ref: str | None = None
    color: tuple[int, int, int] | None = None


# --- Chunks ------------------------------------------------------------------------------------

@dataclass(slots=True)
class _Chunk:
    kind: str
    text: str                                # as written
    line: int
    column: int

    @property
    def end(self) -> int:
        """The column just after the chunk (on its line)."""
        return self.column + len(self.text)

    def is_modifier(self) -> bool:
        return self.kind == WORD and self.text in SHOW_MODIFIER_WORDS


def _token_end(token: Token) -> int:
    return token.column + len(token.text)


def _chunks(raw: RawStatement) -> tuple[list[_Chunk], bool]:
    """The chunks after the statement word, and whether a trailing ``:`` was set aside."""
    tokens = list(raw.tokens[1:])
    colon = bool(tokens) and tokens[-1].kind in (COLON, FWCOLON) and raw.ends_with_colon
    if colon:
        tokens.pop()
    chunks: list[_Chunk] = []
    current: list[Token] = []

    def close() -> None:
        if current:
            text = "".join(t.text for t in current)
            first = current[0]
            if _NUMBER_RE.fullmatch(text):
                kind = NUMBER
            elif len(current) == 1 and first.kind == NAME:
                kind = WORD
            else:
                kind = OTHER
            chunks.append(_Chunk(kind, text, first.line, first.column))
            current.clear()

    for index, token in enumerate(tokens):
        if token.kind == STRING:
            close()
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            line_text = raw.texts.get(token.line, "")
            if following is not None and following.line == token.line:
                written = line_text[token.column - 1:following.column - 1].strip()
            else:
                written = raw.rest_from(token.line, token.column)
            chunks.append(_Chunk(TEXT, written, token.line, token.column))
            continue
        if current and (token.line != current[-1].line
                        or token.column != _token_end(current[-1])):
            close()
        current.append(token)
    close()
    return chunks, colon


def _written(raw: RawStatement, chunks: list[_Chunk]) -> str:
    """The source text covering ``chunks``, as written."""
    first, last = chunks[0], chunks[-1]
    if first.line == last.line:
        return raw.texts.get(first.line, "")[first.column - 1:last.end - 1]
    return " ".join(c.text for c in chunks)


def _next_modifier(chunks: list[_Chunk], start: int) -> int:
    """The index of the first modifier word at or after ``start``, or ``len(chunks)``."""
    for index in range(start, len(chunks)):
        if chunks[index].is_modifier():
            return index
    return len(chunks)


def _fixed(word: str) -> str | None:
    """``word`` with ``_`` for each character a word can't hold, if that gives a word."""
    fixed = "".join(c if is_word_char(c) else "_" for c in word).strip("_")
    return fixed if fixed and is_image_word(fixed) else None


def _word_problem(ctx: ParseContext, chunk: _Chunk, *, tag: bool) -> bool:
    """E127 for a chunk that can't be an image-name word (or a tag). True if raised."""
    if chunk.kind in (WORD, NUMBER) and is_image_word(chunk.text):
        return False
    if chunk.kind == WORD and all(is_word_char(c) for c in canonical_name(chunk.text)):
        lowered = canonical_name(chunk.text).lower()
        form = "stage" if lowered in STAGE_WORDS and lowered not in STATEMENT_WORDS \
            else "statement"
        ctx.error("E127", form, chunk.text, tag)
        return True
    ctx.error("E127", "characters", chunk.text, tag, _fixed(chunk.text))
    return True


def _is_file(chunk: _Chunk) -> bool:
    """A chunk that looks like a file path (``/`` or an extension), E117."""
    return chunk.kind == OTHER and ("/" in chunk.text or bool(_EXTENSION_RE.search(chunk.text)))


def _name_from_file(text: str) -> str:
    """The image name a file path gives: ``images/`` and the extension dropped, folders as
    words (``hana/happy.png`` → ``hana happy``)."""
    path = text.removeprefix("images/")
    path = _EXTENSION_RE.sub("", path)
    return " ".join(part for part in path.split("/") if part)


def _image_name(ctx: ParseContext, word: str, raw: RawStatement, items: list[_Chunk], *,
                declared: bool = False) -> str | None:
    """The image name the chunks give (SR-F04-01, 08), or None with the error pending:
    E117 (quotes, a file), E112 (none), E126 (over 5 words), E127 (a word it can't hold)."""
    for chunk in items:
        if chunk.kind == TEXT and not declared:
            inside = chunk.text[1:-1] if chunk.text.endswith('"') else chunk.text[1:]
            ctx.error("E117", "quotes", word, chunk.text, " ".join(inside.split()))
            return None
        if _is_file(chunk) and not declared:
            ctx.error("E117", "file", word, chunk.text, _name_from_file(chunk.text))
            return None
    if not items:
        ctx.error("E112", word)
        return None
    if len(items) > IMAGE_NAME_MAX_WORDS:
        ctx.error("E126", _written(raw, items), len(items), declared)
        return None
    for chunk in items:
        if _word_problem(ctx, chunk, tag=False):
            return None
    return " ".join(canonical_name(chunk.text) for chunk in items)


def _with_part(ctx: ParseContext, raw: RawStatement, chunks: list[_Chunk],
               start: int) -> "WithClause | None":
    """``with`` at ``chunks[start]`` to the line end (SR-F04-25): E113 with nothing after it,
    E115 when a modifier word follows; then F09's ``parse_with`` (E192–E194)."""
    from engine.script.effects import parse_with    # effects reads this module's chunks
    keyword = chunks[start]
    stop = _next_modifier(chunks, start + 1)
    values = chunks[start + 1:stop]
    if not values:
        ctx.error("E113", "with")
        return None
    if stop < len(chunks):
        ctx.error("E115", _written(raw, chunks[start:stop]))
        return None
    return parse_with(ctx, values, keyword)


def _number(text: str) -> int | float:
    return float(text) if "." in text else int(text)


# --- show (SR-F04-08–17) ---------------------------------------------------------------------

def _parse_at(ctx: ParseContext, raw: RawStatement, chunks: list[_Chunk], start: int,
              values: list[_Chunk]) -> At | None:
    """``at``'s value (SR-F04-12, 13; 04 §6.1 step 3). ``values`` run to the next modifier."""
    first = values[0]
    if first.kind == WORD and not first.text[0].isdigit():
        name = canonical_name(first.text)
        if name not in ctx.position_names:
            ctx.error("E120", first.text, suggest(name, ctx.position_names))
            return None
        used = 1
        at = At(name=name)
    else:
        count = 0
        while count < len(values) and values[count].kind == NUMBER:
            count += 1
        if count > 2:
            ctx.error("E122", "count", count)
            return None
        if count < len(values):
            bad = values[count]
            if count == 0 or bad.kind != WORD or bad.text[0].isdigit():
                if _UNITS_RE.fullmatch(bad.text):
                    form = "units"
                elif "," in bad.text:
                    form = "comma"
                elif bad.kind == WORD:
                    form = "letter"
                else:
                    form = "other"
                ctx.error("E122", form, bad.text)
                return None
        numbers = [_number(c.text) for c in values[:count]]
        low, high = STAGE_COORD_RANGE
        for axis, (chunk, value) in enumerate(zip(values[:count], numbers)):
            if value < low or value > high:
                if axis == 0:
                    direction = "too far left" if value < low else "too far right"
                else:
                    direction = "too high" if value < low else "too low"
                ctx.error("E121", chunk.text, direction)
                return None
        used = count
        at = At(x=numbers[0], y=numbers[1] if count == 2 else None)
    if used < len(values):
        _left_over(ctx, raw, chunks[start:start + 1] + values[:used], values[used:], "at")
        return None
    return at


def _left_over(ctx: ParseContext, raw: RawStatement, after: list[_Chunk],
               rest: list[_Chunk], word: str) -> None:
    ctx.error("E110", "left", _written(raw, rest), _written(raw, after), word)


def _one_value(ctx: ParseContext, raw: RawStatement, chunks: list[_Chunk], start: int,
               values: list[_Chunk]) -> bool:
    """E110 when a one-value modifier has more than one value. True if fine."""
    if len(values) > 1:
        _left_over(ctx, raw, chunks[start:start + 2], values[1:], chunks[start].text)
        return False
    return True


def parse_show(raw: RawStatement, ctx: ParseContext) -> Show | None:
    chunks, colon = _chunks(raw)
    stop = _next_modifier(chunks, 0)
    image = _image_name(ctx, "show", raw, chunks[:stop])
    if image is None:
        return None
    given: dict[str, object] = {}
    with_clause: "WithClause | None" = None
    index = stop
    while index < len(chunks):
        word = chunks[index].text
        if word in given:
            ctx.error("E114", word)
            return None
        if word == "with":
            with_clause = _with_part(ctx, raw, chunks, index)
            if with_clause is None:
                return None
            break
        stop = _next_modifier(chunks, index + 1)
        values = chunks[index + 1:stop]
        if not values:
            if word == "flip":
                ctx.error("E125")
            else:
                ctx.error("E113", word)
            return None
        value = _modifier_value(ctx, raw, chunks, index, values)
        if value is None:
            return None
        given[word] = value
        index = stop
    if "behind" in given and "layer" in given:
        ctx.error("E118")
        return None
    if colon:
        ctx.error("E110", "colon", "show")
        return None
    return Show(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                image=image, tag=given.get("as"), at=given.get("at"),  # type: ignore[arg-type]
                behind=given.get("behind"), layer=given.get("layer"),  # type: ignore[arg-type]
                zoom=given.get("zoom"), flip=given.get("flip"),  # type: ignore[arg-type]
                with_clause=with_clause)


def _modifier_value(ctx: ParseContext, raw: RawStatement, chunks: list[_Chunk], index: int,
                    values: list[_Chunk]) -> object | None:
    """The value of the modifier at ``chunks[index]``, or None with the error pending."""
    word = chunks[index].text
    if word == "at":
        return _parse_at(ctx, raw, chunks, index, values)
    first = values[0]
    if word in ("as", "behind"):
        # SR-F04-09: the ``as`` word follows the image-word rules (E127); a ``behind`` tag
        # names a sprite, so it follows them too (a tag no show can give).
        if _word_problem(ctx, first, tag=True):
            return None
        value: object = canonical_name(first.text)
    elif word == "layer":
        low, high = LAYER_RANGE
        if first.kind != NUMBER or "." in first.text or not low <= int(first.text) <= high:
            ctx.error("E123", first.text, first.kind != NUMBER)
            return None
        value = int(first.text)
    elif word == "zoom":
        low, high = ZOOM_RANGE
        if first.kind != NUMBER or not low <= float(first.text) <= high:
            ctx.error("E124", first.text, first.kind != NUMBER)
            return None
        value = float(first.text)
    else:                                            # flip
        if first.kind != WORD or first.text not in ("on", "off"):
            ctx.error("E125")
            return None
        value = first.text == "on"
    if not _one_value(ctx, raw, chunks, index, values):
        return None
    return value


# --- scene and hide (SR-F04-07, 18) ----------------------------------------------------------

def parse_scene(raw: RawStatement, ctx: ParseContext) -> Scene | None:
    chunks, colon = _chunks(raw)
    stop = _next_modifier(chunks, 0)
    image: str | None = None
    if stop > 0:
        image = _image_name(ctx, "scene", raw, chunks[:stop])
        if image is None:
            return None
    for chunk in chunks[stop:]:
        if chunk.is_modifier() and chunk.text != "with":
            ctx.error("E111", chunk.text)
            return None
    with_clause: "WithClause | None" = None
    if stop < len(chunks):
        with_clause = _with_part(ctx, raw, chunks, stop)
        if with_clause is None:
            return None
    if colon:
        ctx.error("E110", "colon", "scene")
        return None
    return Scene(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                 image=image, with_clause=with_clause)


def parse_hide(raw: RawStatement, ctx: ParseContext) -> Hide | None:
    chunks, colon = _chunks(raw)
    if not chunks or chunks[0].is_modifier():
        ctx.error("E112", "hide")
        return None
    first = chunks[0]
    tag = canonical_name(first.text)
    if first.kind not in (WORD, NUMBER) or not all(is_word_char(c) for c in tag):
        ctx.error("E127", "characters", first.text, True, _fixed(first.text))
        return None
    stop = _next_modifier(chunks, 1)
    if stop > 1:
        ctx.error("E116", "words", first.text, "hide " + _written(raw, chunks[:stop]))
        return None
    with_clause: "WithClause | None" = None
    if stop < len(chunks):
        word = chunks[stop].text
        if word != "with":
            ctx.error("E116", "modifier", word)
            return None
        with_clause = _with_part(ctx, raw, chunks, stop)
        if with_clause is None:
            return None
    if colon:
        ctx.error("E110", "colon", "hide")
        return None
    return Hide(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                tag=tag, with_clause=with_clause)


# --- image (SR-F04-04, 05) -------------------------------------------------------------------

def parse_image(raw: RawStatement, ctx: ParseContext) -> ImageDecl | None:
    tokens = raw.tokens[1:]
    equals = next((i for i, t in enumerate(tokens) if t.kind == EQUALS), None)
    if equals is None:
        ctx.error("E131", "shape")
        return None
    head = RawStatement(raw.file, raw.line, tokens=[raw.tokens[0], *tokens[:equals]],
                        texts=raw.texts, segments=raw.segments)
    items, _ = _chunks(head)
    if not items or any(c.kind == TEXT for c in items):
        ctx.error("E131", "shape")
        return None
    name = _image_name(ctx, "image", raw, items, declared=True)
    if name is None:
        return None
    if ctx.depth == 0:
        ctx.collected.image_defs.setdefault(name, []).append(ctx.place())
    after = tokens[equals + 1:]
    if not after:
        comment = raw.comment
        quotes = comment is not None and comment[:1].strip() != ""
        ctx.error("E131", "quotes" if quotes else "shape")
        return None
    value = after[0]
    if value.kind != STRING:
        ctx.error("E131", "quotes")
        return None
    if len(after) > 1:
        ctx.error("E131", "shape")
        return None
    if value.unclosed:
        return None                                  # E54 is pending
    text = value.text
    if text.startswith("#"):
        if not _COLOR_RE.fullmatch(text):
            ctx.error("E132", "color", text)
            return None
        color = (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
        return ImageDecl(file=raw.file, line=raw.line, end_line=raw.end_line,
                         column=raw.column, name=name, color=color)
    try:
        check_ref(text)
    except AssetRefError as exc:
        if exc.reason == REASON_OUTSIDE:
            ctx.error("E132", "outside", text)
        else:
            ctx.error("E132", "reason", text, exc.reason)
        return None
    if not text.lower().endswith(IMAGE_SUFFIXES):
        ctx.error("E132", "type", text)
        return None
    return ImageDecl(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     name=name, ref=text)


for _spec in (
    StatementSpec(word="scene", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_scene),
    StatementSpec(word="show", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_show),
    StatementSpec(word="hide", placement="story", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_hide),
    StatementSpec(word="image", placement="top", takes_block=False, tail=TAIL_SCRIPT,
                  parse=parse_image, misplaced="E130"),
):
    register(_spec)
del _spec
register_declaration(ImageDecl, lambda node: "image:" + node.name)  # type: ignore[attr-defined]

__all__ = ["At", "Hide", "IMAGE_NAME_MAX_WORDS", "ImageDecl", "Scene", "Show",
           "parse_hide", "parse_image", "parse_scene", "parse_show"]
