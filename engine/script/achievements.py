"""Achievements' script side: ``lock achievement`` declarations and ``unlock achievement``
lines (F37 ``SPEC.md`` §3, §5.1; F36 ``07-architecture-review.md`` I-12).

Why this module exists: an achievement rewards the player across playthroughs. The author
declares each one at the top level (Studio writes them into ``database.vns``) and gives it
with an ``unlock achievement`` line, or lets it unlock by itself when its ``when`` condition
comes true (``runtime/achievements.py`` checks it at checkpoints and at the story's end). The
words go through F19's ``lock``/``unlock`` specs as one row of ``routes.LOCK_TARGETS``:
``LockTarget("achievement", top=…, block=…)``.

- **Top level**, ``lock achievement <name> "Title" ["Description"] [image <picture>]
  [hidden] [when <condition>]`` → ``AchievementDecl``, in that order. The condition runs to
  the end of the line and is compiled once here, as an ``if`` condition is (F02's checks,
  E339's ``python`` form for a syntax error; F03's binding checks in ``bindings.py``).
  ``unlock achievement`` there is E339's ``top`` form.
- **In a label**, ``unlock achievement <name>`` → F19's own ``Lock("achievement", name,
  unlock=True)``, so F19's ``run_lock`` executes it (07 I-12: one executor for every
  ``unlock <kind>``). ``lock achievement`` there is E339: the ``declare`` form with a title
  (a declaration in the wrong place), else the ``relock`` form (achievements can't be taken
  back). Anything else left over is F19's E244 ``need`` form.

The name is a script name (E64 for a word Python can't use); the title as shown (``{{`` is
``{``, no text tags, 1–``TITLE_MAX`` code points); the description likewise, 0–
``DESCRIPTION_MAX``; the picture as ``show`` reads one (F04: at most 5 words, E117, E112,
E126, E127; a picture with no file is F04's launch warning); the condition at most
``CONDITION_MAX`` code points. ``achievement``, ``image``, ``hidden`` and ``when`` are read
only after ``lock``/``unlock achievement`` and stay usable as names (SR-F37-02). The
whole-game checks (E340, W224) are ``checks.py``'s; ``Program.achievements`` is built by
``program.py`` (the declarations themselves, reading order).

**Registration.** Importing this module registers the declaration's identity
(``"achievement:" + name``) and calls ``register_words()`` once, after F36's ``replay``
(``script/__init__.py`` imports it right after ``replay``). Calling it again does nothing.
The in-label Help doc (``LABEL_DOCS``) is registered with it: Studio's Unlock form has the
"achievement" choice (F37-S3; AC-F47-33's ``missing_forms``).
"""

from dataclasses import dataclass
from types import CodeType
from typing import Final

from engine.script.chapter import _shown
from engine.script.identity import register_declaration
from engine.script.lexer import STRING, RawStatement
from engine.script.nodes import Node, PyCode
from engine.script.pycheck import ROLE_CONDITION, compile_piece
from engine.script.routes import LOCK_TARGETS, WORD_LOCK, Lock, LockTarget, register_target
from engine.script.stage import TEXT, WORD, _Chunk, _image_name, _written
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext
from engine.script.words import canonical_name, is_name

WORD_ACHIEVEMENT: Final = "achievement"
WORD_IMAGE: Final = "image"
WORD_HIDDEN: Final = "hidden"
WORD_WHEN: Final = "when"
ACHIEVEMENTS_MAX: Final = 200            # achievements in a story (E340)
WHEN_MAX: Final = 64                     # achievements with when (E340)
TITLE_MAX: Final = 60                    # code points as shown (E339)
DESCRIPTION_MAX: Final = 200             # code points as shown (E339)
CONDITION_MAX: Final = 500               # code points as written (E339)


# --- The node (SPEC §5.1) ----------------------------------------------------------------------

@dataclass(slots=True, kw_only=True)
class AchievementDecl(Node):
    """``lock achievement <name> "Title" ["Description"] [image …] [hidden] [when …]`` at
    the top level. A declaration, sid ``"achievement:" + name``. ``Program.achievements``
    holds these in reading order; ``runtime/achievements.py`` reads ``name``, ``title``,
    ``description``, ``image``, ``hidden``, ``when`` (the condition as written, None: given
    only by a line), ``when_code`` (compiled once at load), ``file.ref`` and ``line``."""

    name: str
    title: str
    description: str = ""
    image: str | None = None
    hidden: bool = False
    when: str | None = None
    when_py: PyCode | None = None

    @property
    def when_code(self) -> CodeType | None:
        return self.when_py.code if self.when_py is not None else None


# --- Parsing (SPEC §3) -------------------------------------------------------------------------

def _string(raw: RawStatement, chunk: _Chunk) -> str:
    """A quoted chunk's text as written (escapes already read by the lexer)."""
    return next((t.text for t in raw.tokens
                 if t.kind == STRING and (t.line, t.column) == (chunk.line, chunk.column)), "")


def _text(ctx: ParseContext, raw: RawStatement, chunk: _Chunk, *, title: bool) -> str | None:
    """A title or description as shown: E339's ``tags``, ``empty`` (a title only),
    ``long`` and ``description`` forms."""
    shown = _shown(_string(raw, chunk))
    if shown is None:
        ctx.error("E339", "tags")
        return None
    if title and not shown.strip():
        ctx.error("E339", "empty")
        return None
    limit = TITLE_MAX if title else DESCRIPTION_MAX
    if len(shown) > limit:
        ctx.error("E339", "long" if title else "description", len(shown), limit)
        return None
    return shown


def _name(ctx: ParseContext, chunk: _Chunk) -> str | None:
    """An achievement name: E64 for a word Python can't use."""
    if not is_name(chunk.text):
        ctx.error("E64", chunk.text)
        return None
    return canonical_name(chunk.text)


def _is(chunk: _Chunk, word: str) -> bool:
    return chunk.kind == WORD and chunk.text == word


def _condition_source(raw: RawStatement, when: _Chunk) -> tuple[str, int, int]:
    """The text after ``when`` to the end of the line (continuation lines joined with
    ``"\\n"``), with the file line and column of its first character."""
    first = raw.texts.get(when.line, "")
    end = raw.segments.get(when.line)
    stop = end.comment_at if end is not None and end.comment_at is not None else len(first)
    start = when.end - 1
    while start < stop and first[start] in " \t":
        start += 1
    parts = [first[start:stop].rstrip()]
    for line in range(when.line + 1, raw.end_line + 1):
        parts.append(raw.rest_from(line, 1))
    return "\n".join(parts).strip(), when.line, start + 1


def _compile_when(ctx: ParseContext, source: str, line: int, column: int) -> PyCode | None:
    """The condition compiled as an ``if`` condition is (``ParseContext.compile``'s rules),
    with a syntax error as E339's ``python`` form."""
    assert ctx.file is not None
    result = compile_piece(source, mode="eval", role=ROLE_CONDITION,
                           filename=f"<{ctx.file.ref}>", line=line, column=column,
                           lambdas=source.count("lambda"), length=len(source),
                           compile_name=ctx.compile_name)
    ctx.py_pieces += 1
    ctx.py_chars += len(source)
    for warn_line, text in result.warnings:
        ctx.warnings.add_w03(ctx.file, warn_line, text)
    problem = result.problem
    if problem is not None:
        if problem.code == "E81":
            ctx.error("E339", "python", problem.args[0])
        else:
            ctx.error(problem.code, *problem.args, line=problem.line, column=problem.column)
        return None
    return PyCode(source=source, line=line, column=column, mode="eval", code=result.code)


def parse_achievement_decl(raw: RawStatement, ctx: ParseContext, unlock: bool,
                           chunks: list[_Chunk], colon: bool) -> AchievementDecl | None:
    """The row's ``top``: name, title, then description, ``image``, ``hidden`` and ``when``
    in that order."""
    if unlock:
        ctx.error("E339", "top")
        return None
    if len(chunks) < 2 or chunks[0].kind != WORD or chunks[1].kind != TEXT:
        ctx.error("E339", "need")
        return None
    name = _name(ctx, chunks[0])
    if name is None:
        return None
    title = _text(ctx, raw, chunks[1], title=True)
    if title is None:
        return None
    rest = chunks[2:]
    at = next((i for i, c in enumerate(rest) if _is(c, WORD_WHEN)), None)
    before = rest if at is None else rest[:at]
    description = ""
    if before and before[0].kind == TEXT:
        found = _text(ctx, raw, before[0], title=False)
        if found is None:
            return None
        description = found
        before = before[1:]
    image: str | None = None
    if before and _is(before[0], WORD_IMAGE):
        end = next((i for i in range(1, len(before)) if _is(before[i], WORD_HIDDEN)),
                   len(before))
        image = _image_name(ctx, WORD_IMAGE, raw, before[1:end])
        if image is None:
            return None
        before = before[end:]
    hidden = False
    if before and _is(before[0], WORD_HIDDEN):
        hidden = True
        before = before[1:]
    if before:
        ctx.error("E339", "left", _written(raw, before))
        return None
    if colon:
        ctx.error("E110", "colon", raw.word)
        return None
    when: str | None = None
    when_py: PyCode | None = None
    if at is not None:
        source, line, column = _condition_source(raw, rest[at])
        if not source:
            ctx.error("E339", "when")
            return None
        if len(source) > CONDITION_MAX:
            ctx.error("E339", "condition", len(source), CONDITION_MAX)
            return None
        when_py = _compile_when(ctx, source, line, column)
        if when_py is None:
            return None
        when = source
    return AchievementDecl(file=raw.file, line=raw.line, end_line=raw.end_line,
                           column=raw.column, name=name, title=title,
                           description=description, image=image, hidden=hidden, when=when,
                           when_py=when_py)


def parse_achievement_lock(raw: RawStatement, ctx: ParseContext, unlock: bool,
                           chunks: list[_Chunk], colon: bool) -> Lock | None:
    """The row's ``block``: ``unlock achievement <name>``, F19's ``Lock`` node; ``lock
    achievement`` in a label is E339 (``declare`` with a title, else ``relock``)."""
    if not unlock:
        if len(chunks) > 1 and chunks[0].kind == WORD and chunks[1].kind == TEXT:
            ctx.error("E339", "declare", canonical_name(chunks[0].text),
                      _written(raw, chunks[1:2]))
        else:
            name = canonical_name(chunks[0].text) if chunks and chunks[0].kind == WORD \
                else None
            ctx.error("E339", "relock", name)
        return None
    if len(chunks) != 1 or chunks[0].kind != WORD:
        ctx.error("E244", "need", tuple(LOCK_TARGETS))
        return None
    name = _name(ctx, chunks[0])
    if name is None:
        return None
    if colon:
        ctx.error("E110", "colon", raw.word)
        return None
    return Lock(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                unlock=True, kind=WORD_ACHIEVEMENT, name=name)


# --- Registration --------------------------------------------------------------------------------

ACHIEVEMENT_TARGET = LockTarget(WORD_ACHIEVEMENT, parse_achievement_decl, parse_achievement_lock)

# The docs heading: docs/script-language.md section 7's "lock achievement (achievements)".
DOCS_HEADING: Final = "lock achievement (achievements)"

DOCS: Final = (
    StatementDoc(
        WORD_LOCK, "Achievement", "Declarations",
        'lock achievement <name> "title" ["description"] [image <picture>] [hidden] '
        "[when <condition>]",
        "Declares an achievement: a reward kept across playthroughs, shown with a notice and "
        "listed on the Achievements page in Extras. With when, it unlocks by itself once "
        "the condition is true.",
        'lock achievement first_steps "First Steps" "Finish the prologue."', DOCS_HEADING,
        "F37", fields=("first_steps", "First Steps", "Finish the prologue.")),
)

# The in-label line's doc: Insert opens Studio's Unlock form on "Achievement" (F37-S3
# registered it with that form's choice: Studio's form registry checks every in-label
# lock/unlock doc has a form, AC-F47-33, F45's ``missing_forms``).
LABEL_DOCS: Final = (
    StatementDoc(
        "unlock", "Unlock achievement", "Story flow", "unlock achievement <name>",
        "Gives the player an achievement for good, with its notice.",
        "unlock achievement garden", DOCS_HEADING, "F37", fields=("garden",)),
)


def register_words() -> None:
    """Register the ``achievement`` row of F19's ``LOCK_TARGETS`` and its docs, once (at
    import, through ``script/__init__.py``); calling it again does nothing."""
    if LOCK_TARGETS.get(WORD_ACHIEVEMENT) is ACHIEVEMENT_TARGET:
        return
    register_target(ACHIEVEMENT_TARGET)
    for doc in (*DOCS, *LABEL_DOCS):     # LABEL_DOCS: Studio's Unlock "Achievement"
        register_doc(doc)


register_declaration(AchievementDecl,
                     lambda node: "achievement:" + node.name)  # type: ignore[attr-defined]
register_words()

__all__ = ["ACHIEVEMENTS_MAX", "ACHIEVEMENT_TARGET", "AchievementDecl", "CONDITION_MAX",
           "DESCRIPTION_MAX", "DOCS", "DOCS_HEADING", "LABEL_DOCS", "TITLE_MAX",
           "WHEN_MAX", "WORD_ACHIEVEMENT", "parse_achievement_decl", "parse_achievement_lock",
           "register_words"]
