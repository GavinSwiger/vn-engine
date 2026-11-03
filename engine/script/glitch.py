"""The ``effect`` statement: glitch effects on the stage (F28 ``04-technical.md`` §3, §5.1;
``01-design.md`` SR-F28-01..03; ``07`` I-11, I-14; load code E294).

Why this module exists: a glitch is written as one line, ``effect <kind> [tag] [size]
[length|on|off]``, checked once at load, so the runtime gets plain words and numbers and
never parses text. ``effect off`` alone ends every F28 glitch.

- **The kind table** (C2, ``07`` I-11): ``EFFECT_STATEMENT_KINDS`` maps each kind word to the
  function that reads the rest of the line. F28's four kinds share ``parse_glitch``. A later
  feature adds a row through review; its words must not be F28's (``tear colorshift static
  jitter on off small medium large``). F30 added ``window_title`` and ``crash``
  (``fourthwall.py``'s parsers, F30 ``07`` §3). E294's list and its did-you-mean read the
  whole table. Bare ``effect off`` is ``Effect(kind=None)``, and its
  executor ends only ``GLITCH_KINDS`` (F30's tricks end through their own ``effect <kind>
  off``). (F29's ``texttags.EFFECT_KINDS`` is the text-tag table, a different thing.)
- **Parse** (04 §5.1, ``07`` I-14): chunks come from F04's reader (``stage._chunks``), as in
  ``effects.py``. A ``:`` is E110's colon form. ``jitter`` takes a sprite tag right after it
  (F04 ``hide``'s rule, but a WORD only, and not an argument word: D9). Another kind followed
  by a word that names a character, a speaker, or a declared image's tag is E294 ``notag``;
  any other unknown word is ``left``. Then, in any order: one size, one length (0.1–30, plain
  seconds), and ``on`` or ``off``. After the line is read the combinations are checked in
  I-14's order: ``off`` with a size or length (``off_args``), ``on`` with a length
  (``both``), ``on`` with ``off`` (``onoff``), a repeated ``on`` or ``off`` (``left``).
- Identity (ADR-0006): ``("effect",)``, as F09's statements; not a checkpoint type; one step;
  ``VOICE_TRANSPARENT`` (``audio_checks.py``, SR-F28-04).

**Registration (F19 07 I-5).** ``register_words()`` adds the ``StatementSpec`` and its
``StatementDoc``s (F30's two included); it is called once at import (F28 s3, with the
executor, ``runtime/glitch.run_effect``, registered in ``interpreter.py``), and calling it
again does nothing.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from engine.core.constants import GLITCH_KINDS, GLITCH_SECONDS_RANGE, GLITCH_SIZES
from engine.script.effects import _DOT_RE, _UNITS_RE, _in, _seconds
from engine.script.fourthwall import CRASH, WINDOW_TITLE, parse_crash, parse_title
from engine.script.fourthwall import register_docs as register_fourthwall_docs
from engine.script.lexer import TAIL_SCRIPT, RawStatement
from engine.script.nodes import Statement
from engine.script.stage import NUMBER, OTHER, WORD, _Chunk, _chunks
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, StatementSpec, get_spec, register
from engine.script.suggest import suggest
from engine.script.words import canonical_name, is_word_char

WORD_EFFECT: Final = "effect"
WORD_ON: Final = "on"
WORD_OFF: Final = "off"
JITTER: Final = "jitter"
# Words that only mean something after a kind (SR-F28-05): never a jitter tag (D9).
ARGUMENT_WORDS: Final = frozenset((*GLITCH_SIZES, WORD_ON, WORD_OFF))
# E294's hint form (PR-F28-20, Could): words for text corruption, which is F29's {glitch}.
HINT_WORDS: Final = frozenset(("corrupt", "glitchtext", "garble"))


@dataclass(slots=True, kw_only=True)
class Effect(Statement):
    """``effect …`` (04 §3). ``kind`` None is ``effect off`` (every F28 glitch); ``tag``
    jitter's sprite (canonical); ``size`` None and ``seconds`` None are the ``[effects]``
    defaults, resolved by the presentation; ``action`` ``burst``, ``on``, or ``off``."""

    kind: str | None = None
    tag: str | None = None
    size: str | None = None
    action: str = "burst"
    seconds: float | None = None

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_EFFECT,)


# A kind's parser: (raw, ctx, kind word, the chunks after it) → the node, or None with the
# error pending.
KindParser = Callable[[RawStatement, ParseContext, str, list[_Chunk]], Statement | None]


# --- Parse (04 §5.1; E294) --------------------------------------------------------------------

def suggest_kind(written: str, kinds: tuple[str, ...]) -> str | None:
    """E294's did-you-mean: F02's ``suggest`` (SR-F02-70), else a kind with the same letters
    in another order (``tare`` → ``tear``, 01 §5.3's example, which is two edits away)."""
    found = suggest(written, kinds)
    if found is not None or len(written) > max(map(len, kinds), default=0):
        return found
    letters = sorted(written.casefold())
    return next((kind for kind in sorted(kinds) if sorted(kind) == letters), None)


def _effect(raw: RawStatement, **fields: object) -> Effect:
    return Effect(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                  **fields)                                       # type: ignore[arg-type]


def _tag(chunk: _Chunk) -> str | None:
    """Jitter's tag: a WORD of word characters that isn't an argument word (F04 ``hide``'s
    rule, D9), canonical; else None."""
    if chunk.kind != WORD:
        return None
    tag = canonical_name(chunk.text)
    if tag in ARGUMENT_WORDS or not all(is_word_char(c) for c in tag):
        return None
    return tag


def _names_a_sprite(ctx: ParseContext, word: str) -> bool:
    """True if ``word`` is a name the script has used for a character or an image so far
    (a define, a speaker, a declared image's tag): E294 ``notag`` rather than ``left``."""
    collected = ctx.collected
    name = canonical_name(word)
    if name in collected.define_defs or name in collected.speakers:
        return True
    return any(image.split(" ", 1)[0] == name for image in collected.image_defs)


def parse_glitch(raw: RawStatement, ctx: ParseContext, kind: str,
                 rest: list[_Chunk]) -> Effect | None:
    """The rest of an F28 kind's line (module docstring)."""
    tag: str | None = None
    subject = kind                       # how the messages name the statement
    if kind == JITTER:
        tag = _tag(rest[0]) if rest else None
        if tag is None:
            ctx.error("E294", "tag")
            return None
        subject = f"{kind} {tag}"
        rest = rest[1:]
    elif (rest and rest[0].kind == WORD and rest[0].text not in ARGUMENT_WORDS
          and _names_a_sprite(ctx, rest[0].text)):
        ctx.error("E294", "notag", kind, rest[0].text)
        return None
    size: str | None = None
    seconds: float | None = None
    switches: list[str] = []             # on / off, as written
    for chunk in rest:
        if chunk.kind == NUMBER:
            if seconds is not None:
                ctx.error("E294", "twice", subject, "lengths")
                return None
            value = _seconds(chunk.text)
            if not _in(value, GLITCH_SECONDS_RANGE):
                ctx.error("E294", "length", subject, chunk.text)
                return None
            seconds = value
        elif chunk.kind == WORD and chunk.text in GLITCH_SIZES:
            if size is not None:
                ctx.error("E294", "twice", subject, "sizes")
                return None
            size = chunk.text
        elif chunk.kind == WORD and chunk.text in (WORD_ON, WORD_OFF):
            switches.append(chunk.text)
        else:
            if chunk.kind in (WORD, OTHER):
                units = _UNITS_RE.fullmatch(chunk.text)
                if units is not None:
                    ctx.error("E294", "units", units.group(1), chunk.text)
                    return None
                if _DOT_RE.fullmatch(chunk.text):
                    ctx.error("E294", "dot", chunk.text)
                    return None
            ctx.error("E294", "left", chunk.text, subject)
            return None
    # 07 I-14's order.
    if WORD_OFF in switches and (size is not None or seconds is not None):
        ctx.error("E294", "off_args", subject)
        return None
    if WORD_ON in switches and seconds is not None:
        ctx.error("E294", "both", subject)
        return None
    if WORD_ON in switches and WORD_OFF in switches:
        ctx.error("E294", "onoff", subject)
        return None
    if len(switches) > 1:
        ctx.error("E294", "left", switches[1], subject)
        return None
    return _effect(raw, kind=kind, tag=tag, size=size,
                   action=switches[0] if switches else "burst", seconds=seconds)


# The one kind table (C2, 07 I-11): word → its parser. F30 (07 §3): window_title, crash.
EFFECT_STATEMENT_KINDS: Final[Mapping[str, KindParser]] = MappingProxyType(
    {**{kind: parse_glitch for kind in GLITCH_KINDS},
     WINDOW_TITLE: parse_title, CRASH: parse_crash})


def parse_effect(raw: RawStatement, ctx: ParseContext) -> Statement | None:
    """An ``effect`` line (module docstring). Errors are pending on ``raw``."""
    chunks, colon = _chunks(raw)
    if colon:
        ctx.error("E110", "colon", WORD_EFFECT)
        return None
    kinds = tuple(EFFECT_STATEMENT_KINDS)
    if not chunks:
        ctx.error("E294", "empty", kinds)
        return None
    first, rest = chunks[0], chunks[1:]
    if first.kind == WORD and first.text == WORD_OFF:
        if rest:
            ctx.error("E294", "left", rest[0].text, None)
            return None
        return _effect(raw)
    word = canonical_name(first.text) if first.kind == WORD else first.text
    parse = EFFECT_STATEMENT_KINDS.get(word) if first.kind == WORD else None
    if parse is None:
        if word in HINT_WORDS:
            ctx.error("E294", "hint", word)
        else:
            ctx.error("E294", "kind", word, suggest_kind(word, kinds), kinds)
        return None
    return parse(raw, ctx, word, rest)


# --- Registration (F19 07 I-5) ---------------------------------------------------------------

SPEC: Final = StatementSpec(word=WORD_EFFECT, placement="story", takes_block=False,
                            tail=TAIL_SCRIPT, parse=parse_effect)

# 07 I-16: two Insert entries in "Effects", documented under HEADING (F28 s6). ``glitch``
# names the kind words (tools/check.py's NAME_SOURCES); ``jitter <sprite>`` is a slot
# (assist's SLOT_KINDS), so tags complete after it.
HEADING: Final = "Glitch effects"           # docs/script-language.md
DOCS: Final = (
    StatementDoc(
        WORD_EFFECT, "Glitch effect", "Effects",
        "effect <glitch> [small|medium|large] [<seconds>|on|off]",
        "Glitches the stage: tear, colorshift, static, or jitter. With a length (or none) it "
        "is a short burst; on keeps it until off. effect off stops them all.",
        "effect tear large 0.3", HEADING, "F28", fields=("tear",), names=("glitch",)),
    StatementDoc(
        WORD_EFFECT, "Jitter a sprite", "Effects",
        "effect jitter <sprite> [small|medium|large] [<seconds>|on|off]",
        "Makes one sprite twitch: a short burst, or on until effect jitter <sprite> off.",
        "show hana happy\neffect jitter hana 1.0", HEADING, "F28", fields=("hana",)),
)


def register_words() -> None:
    """Register ``effect`` (spec and docs, F30's two entries included). Called once at
    import; calling it again while it is registered does nothing (F19's rule)."""
    if get_spec(WORD_EFFECT) is SPEC:
        return
    register(SPEC)
    for doc in DOCS:
        register_doc(doc)
    register_fourthwall_docs()


register_words()                            # F28 s3 (F19 07 I-5)

__all__ = ["ARGUMENT_WORDS", "DOCS", "EFFECT_STATEMENT_KINDS", "Effect", "HINT_WORDS",
           "KindParser", "SPEC", "WORD_EFFECT", "parse_effect", "parse_glitch",
           "register_words", "suggest_kind"]
