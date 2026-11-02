"""F30 fourth-wall tricks at load: ``effect window_title`` and ``effect crash`` (F30
``04-technical.md`` §3, §5.1, §5.2; ``07`` I-7, I-14; load codes E300, E301).

Why this module exists: both tricks are written as ``effect <kind> …`` lines and checked once
at load, so the runtime gets a plain title or an already parsed message and never parses
text.

- **Rows in F28's kind table** (C1, ``07`` §3): ``glitch.EFFECT_STATEMENT_KINDS`` maps
  ``window_title`` to ``parse_title`` and ``crash`` to ``parse_crash`` (F28's ``KindParser``
  signature: the chunks after the kind word come in ``rest``). This module never imports
  ``glitch``; ``glitch`` imports the parsers. Bare ``effect off`` stays F28's and ends no trick.
- **``window_title``** (04 §5.1): one quoted text, shown as written (``{{`` is ``{``, any other
  ``{`` is E300's ``tags`` form, so ``{username}`` never reaches a title), at most
  ``WINDOW_TITLE_MAX`` code points; ``""`` is allowed. ``off`` gives back ``[game] title``.
- **``crash``** (04 §5.2): no text (``[words] fake_crash_message``) or one quoted message of at
  most ``CRASH_MESSAGE_MAX`` code points as written, read by F05's ``line_body`` with
  ``crash=True``: only ``{var=…}``, ``{username}``, and ``{{`` (E301's ``tag`` form).
- Identity (ADR-0006): ``("effect",)``, as F28's ``Effect``; neither node is a checkpoint
  type; both are ``VOICE_TRANSPARENT`` (``audio_checks.py``).

**Registration.** The ``effect`` word and its docs are registered by ``glitch.register_words()``,
which also calls ``register_docs()`` here, so the two entries come and go with the word (F19
07 I-5). ``docs`` is None until F30 s6 writes the "Fourth-wall tricks" section. The executors
come with F30 s3 (``runtime/fourthwall.py``); until then both load (``effect`` registers at
import since F28 s3) and stop the story with E32 when reached (``interpreter.py``'s
placeholders; 07 I-15).
"""

from dataclasses import dataclass
from typing import Final

from engine.core.constants import CRASH_MESSAGE_MAX, WINDOW_TITLE_MAX
from engine.script.chapter import _shown
from engine.script.lexer import STRING, RawStatement, Token
from engine.script.nodes import Statement
from engine.script.stage import TEXT, WORD, _Chunk
from engine.script.statement_docs import StatementDoc, docs_for, register_doc
from engine.script.statements import ParseContext, line_body
from engine.script.texttags import TaggedText

WORD_EFFECT: Final = "effect"
WINDOW_TITLE: Final = "window_title"
CRASH: Final = "crash"
WORD_OFF: Final = "off"


@dataclass(slots=True, kw_only=True)
class TitleEffect(Statement):
    """``effect window_title "…"`` / ``effect window_title off`` (04 §3). ``text`` is the
    title as shown (``{{`` already ``{``, at most ``WINDOW_TITLE_MAX`` code points); None is
    ``off``: the game's own ``[game] title``."""

    text: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_EFFECT,)


@dataclass(slots=True, kw_only=True)
class CrashEffect(Statement):
    """``effect crash ["…"]`` (04 §3). ``body`` is the message's tags parsed once (only
    ``VarMark``, ``NameMark``, and spans); None: ``[words] fake_crash_message``."""

    body: TaggedText | None = None

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_EFFECT,)


def _string(raw: RawStatement, chunk: _Chunk) -> Token:
    """The STRING token of a TEXT chunk (``stage._chunks`` starts one at each)."""
    return next(t for t in raw.tokens
                if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column))


def _place(raw: RawStatement) -> dict[str, object]:
    return {"file": raw.file, "line": raw.line, "end_line": raw.end_line, "column": raw.column}


def parse_title(raw: RawStatement, ctx: ParseContext, kind: str,
                rest: list[_Chunk]) -> TitleEffect | None:
    """The rest of an ``effect window_title`` line (04 §5.1; E300)."""
    first = rest[0] if rest else None
    if first is None or not (first.kind == TEXT or (first.kind == WORD
                                                    and first.text == WORD_OFF)):
        ctx.error("E300", "needs")
        return None
    left = rest[1:]
    if first.kind == WORD:                                     # off
        if left:
            ctx.error("E300", "left", left[0].text)
            return None
        return TitleEffect(**_place(raw), text=None)          # type: ignore[arg-type]
    token = _string(raw, first)
    if token.unclosed:
        return None                                  # the reader's error is pending
    shown = _shown(token.text)
    if shown is None:
        ctx.error("E300", "tags")
        return None
    if len(shown) > WINDOW_TITLE_MAX:
        ctx.error("E300", "long", len(shown))
        return None
    if left:
        ctx.error("E300", "left", left[0].text)
        return None
    return TitleEffect(**_place(raw), text=shown)              # type: ignore[arg-type]


def parse_crash(raw: RawStatement, ctx: ParseContext, kind: str,
                rest: list[_Chunk]) -> CrashEffect | None:
    """The rest of an ``effect crash`` line (04 §5.2; E301, and F05's E160–E167 in the
    message)."""
    if not rest:
        return CrashEffect(**_place(raw), body=None)           # type: ignore[arg-type]
    first = rest[0]
    if first.kind != TEXT:
        ctx.error("E301", "left", first.text)
        return None
    token = _string(raw, first)
    if token.unclosed:
        return None                                  # the reader's error is pending
    if len(token.text) > CRASH_MESSAGE_MAX:
        ctx.error("E301", "long", len(token.text))
        return None
    if len(rest) > 1:
        ctx.error("E301", "left", rest[1].text)
        return None
    body = line_body(raw, ctx, token, crash=True)
    if body is None:
        return None
    return CrashEffect(**_place(raw), body=body)               # type: ignore[arg-type]


# --- Docs (F45; 07 I-14) ---------------------------------------------------------------------

# Two Insert entries in "Effects". ``docs`` is None until F30 s6 writes the section (and sets
# ``names``, ``07`` I-14 (1)).
DOCS: Final = (
    StatementDoc(
        WORD_EFFECT, "Window title", "Effects", 'effect window_title "<title>"|off',
        "Changes the text in the game window's title bar until effect window_title off "
        "brings back the game's own title.",
        'effect window_title "She is still here"', None, "F30",
        fields=("She is still here",)),
    StatementDoc(
        WORD_EFFECT, "Fake crash", "Effects", 'effect crash ["<message>"]',
        "Shows a fake error screen, as if the game had crashed; the story goes on when the "
        "player clicks or presses a key. The message may use {username} and {var=...}.",
        'effect crash "LanternError: Hana is not responding"', None, "F30",
        fields=("LanternError: Hana is not responding",)),
)


def register_docs() -> None:
    """Register the two entries (``glitch.register_words()`` calls this right after it
    registers ``effect``); calling it again while they are registered does nothing."""
    if DOCS[0] in docs_for(WORD_EFFECT):
        return
    for doc in DOCS:
        register_doc(doc)


__all__ = ["CRASH", "CrashEffect", "DOCS", "TitleEffect", "WINDOW_TITLE", "parse_crash",
           "parse_title", "register_docs"]
