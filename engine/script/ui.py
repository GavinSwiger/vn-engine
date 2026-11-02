"""The ``ui`` statement: dynamic UI from the story (F32 ``04-technical.md`` §4.2, §5.1;
``01-design.md`` SR-F32-01..05; ``07`` G5, I-9, I-10; load codes E319, E320, E321).

Why this module exists: a story changes the game's own interface with one checked line, so
the runtime gets a plain style name, a switch, and an already shown reason, and never parses
text:

- ``ui style <name>`` / ``ui style off``: the in-game look of a ``[style.<name>]`` table in
  ``config.toml`` (E320 when the config has no such table and the load was given the names,
  ``LoadOptions.style_names``; None skips the check);
- ``ui saving off ["reason"]`` / ``ui saving on`` and the same for ``loading``: block or allow
  the Save (Load) page, with an optional reason shown there (1–``UI_REASON_MAX`` code points
  as shown, ``{{`` is ``{``, any other ``{`` is E321's ``tags`` form);
- ``ui delete saves``: delete every save slot.

**Parse** (04 §5.1). The items are the tail's tokens. At the top level the line is E319
``top`` (``placement="either"``, as F20's ``flowchart``: ``"story"`` would give F02's E40). A
trailing ``:`` is E110's colon form (F28 and F30 do the same, 07 G5). ``style``, ``saving``,
``loading``, ``delete``, ``saves``, ``on``, and ``off`` are read only here and stay usable as
names (SR-F32-01). Style names are matched as written (config names are lower case).

Identity (ADR-0006): ``("ui", form)``. Not a checkpoint type; each line is one step; not
``VOICE_TRANSPARENT``.

**Registration (F19 07 I-5).** ``register_words()`` adds the ``StatementSpec`` and the four
``StatementDoc``s; calling it again does nothing. The executor is the state lane's (F32 s3,
``runtime/ui.py``), so until then the word is **not** registered at import: a ``ui`` line is
F02's E32 in a real game, and tests register it inside ``scoped_registry()``. F32 s3 adds the
``register_words()`` call at the bottom of this module.
"""

from dataclasses import dataclass
from typing import Final, Literal

from engine.core.constants import UI_REASON_MAX
from engine.script.chapter import _shown
from engine.script.lexer import COLON, FWCOLON, NAME, STRING, TAIL_SCRIPT, RawStatement, Token
from engine.script.nodes import Statement
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, StatementSpec, _between, get_spec, register
from engine.script.suggest import suggest

WORD_UI: Final = "ui"
STYLE: Final = "style"
SAVING: Final = "saving"
LOADING: Final = "loading"
DELETE: Final = "delete"
SAVES: Final = "saves"
WORD_ON: Final = "on"
WORD_OFF: Final = "off"
FORMS: Final = (STYLE, SAVING, LOADING, DELETE)       # E319's list and its did-you-mean

Form = Literal["style", "saving", "loading", "delete"]


@dataclass(slots=True, kw_only=True)
class UiStatement(Statement):
    """A ``ui`` line (04 §4.2). ``style``: the style name, None for ``off`` (form ``style``);
    ``on``: ``saving``/``loading`` allowed again; ``reason``: the ``off`` reason as shown
    (``{{`` already ``{``), None for the game's own words."""

    form: Form
    style: str | None = None
    on: bool = False
    reason: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_UI, self.form)


def reason_ok(text: str) -> bool:
    """A reason's length rule (SR-F32-04): 1 to ``UI_REASON_MAX`` code points. A restore
    checks a saved reason with it."""
    return 1 <= len(text) <= UI_REASON_MAX


# --- Parse (04 §5.1; E319, E320, E321) -------------------------------------------------------

class _Error(Exception):
    def __init__(self, code: str, *args: object) -> None:
        super().__init__(code)
        self.code = code
        self.args_ = args


def _written(raw: RawStatement, items: list[Token], index: int) -> str:
    """Item ``index`` as written: a word's text, a string's text without its quotes, else its
    source up to the next item."""
    token = items[index]
    if token.kind in (NAME, STRING):
        return token.text
    stop = items[index + 1] if index + 1 < len(items) else None
    return _between(raw, token, stop)


def _word(items: list[Token], index: int) -> str | None:
    """Item ``index``'s text when it is a word, else None."""
    if index < len(items) and items[index].kind == NAME:
        return items[index].text
    return None


def _left(raw: RawStatement, items: list[Token], index: int, which: str) -> None:
    """E319 ``left`` when anything follows item ``index - 1``."""
    if index < len(items):
        raise _Error("E319", "left", which, _written(raw, items, index))


def _reason(token: Token) -> str:
    """A reason as shown (SR-F32-04), or raises E321."""
    shown = _shown(token.text)
    if shown is None:
        raise _Error("E321", "tags")
    if not shown:
        raise _Error("E321", "empty")
    if len(shown) > UI_REASON_MAX:
        raise _Error("E321", "long", len(shown))
    return shown


class _Pending(Exception):
    """The reader already has an error for this line (an unclosed quote)."""


def _read(raw: RawStatement, ctx: ParseContext, items: list[Token]) -> dict[str, object]:
    """The node's fields from the items; raises ``_Error`` (or ``_Pending``)."""
    if not items:
        raise _Error("E319", "needs")
    form = _word(items, 0)
    if form not in FORMS:
        written = _written(raw, items, 0)
        raise _Error("E319", "unknown", written, suggest(written, FORMS))
    if form == STYLE:
        name = _word(items, 1)
        if name is None:
            raise _Error("E319", "style_needs")
        names = ctx.style_names
        if name != WORD_OFF and names is not None and name not in names:
            raise _Error("E320", name, suggest(name, names))
        _left(raw, items, 2, STYLE)
        return {"form": STYLE, "style": None if name == WORD_OFF else name}
    if form == DELETE:
        if _word(items, 1) != SAVES:
            raise _Error("E319", "delete_needs")
        _left(raw, items, 2, DELETE)
        return {"form": DELETE}
    switch = _word(items, 1)
    if switch not in (WORD_ON, WORD_OFF):
        raise _Error("E319", "block_needs", form)
    if switch == WORD_ON:
        _left(raw, items, 2, f"{form} {WORD_ON}")
        return {"form": form, "on": True}
    reason: str | None = None
    rest = 2
    if rest < len(items) and items[rest].kind == STRING:
        if items[rest].unclosed:
            raise _Pending
        reason = _reason(items[rest])
        rest += 1
    _left(raw, items, rest, f"{form} {WORD_OFF}")
    return {"form": form, "on": False, "reason": reason}


def parse_ui(raw: RawStatement, ctx: ParseContext) -> UiStatement | None:
    """A ``ui`` line (module docstring). Errors are pending on ``raw``."""
    if ctx.depth == 0:
        ctx.error("E319", "top")
        return None
    tokens = raw.tokens[1:]
    colon = bool(tokens) and tokens[-1].kind in (COLON, FWCOLON)
    if colon or raw.ends_with_colon:
        ctx.error("E110", "colon", WORD_UI)
        return None
    try:
        fields = _read(raw, ctx, tokens)
    except _Error as error:
        ctx.error(error.code, *error.args_)
        return None
    except _Pending:
        return None
    return UiStatement(file=raw.file, line=raw.line, end_line=raw.end_line,
                       column=raw.column, **fields)                  # type: ignore[arg-type]


# --- Registration (F19 07 I-5) ---------------------------------------------------------------

SPEC: Final = StatementSpec(word=WORD_UI, placement="either", takes_block=False,
                            tail=TAIL_SCRIPT, parse=parse_ui)

# The docs/script-language.md section F32 s6 writes; each doc's ``docs`` is None until then
# (the completeness test's DOCS_PENDING), and s6 sets it to HEADING.
HEADING: Final = "Dynamic UI"
# Four Insert entries in "Effects" (04 §15 step 2). Completion (07 I-10, F45's slot rule):
# ``ui`` lists the kind ``ui`` (style, saving, loading, delete; tools/check.py's NAME_SOURCES)
# and ``style <style>`` is a slot (assist's SLOT_KINDS: the config's style names and off).
# The ``ashes`` example needs a [style.ashes] table: tests/fixtures/docgame has one (I-9).
DOCS: Final = (
    StatementDoc(
        WORD_UI, "UI style", "Effects", "ui style <style>",
        "Switches the text box, choices, NVL page, and quick menu to a [style.<name>] look "
        "from config.toml. ui style off brings back the normal look. Saves keep the style.",
        'ui style ashes\n"The room feels colder now."\nui style off', None, "F32",
        fields=("ashes",), names=("ui",)),
    StatementDoc(
        WORD_UI, "Stop saving", "Effects", 'ui saving off ["<reason>"]|on',
        "Turns off saving: the Save page shows the reason (or the game's own words) instead "
        "of slots, and auto-saves stop. ui saving on allows saving again.",
        'ui saving off "There\'s nothing left to keep."\n"Something is watching."\n'
        "ui saving on", None, "F32", fields=("There's nothing left to keep.",), names=("ui",)),
    StatementDoc(
        WORD_UI, "Stop loading", "Effects", 'ui loading off ["<reason>"]|on',
        "Turns off loading during the story: the Load page shows the reason (or the game's "
        "own words) instead of slots. The title's Load page always works.",
        'ui loading off "Not now."\n"There is no going back."\nui loading on', None, "F32",
        fields=("Not now.",), names=("ui",)),
    StatementDoc(
        WORD_UI, "Delete all saves", "Effects", "ui delete saves",
        "Deletes every save slot of this game, auto-saves included. Write ui saving off first, "
        "so no auto-save makes a new one. A Studio preview deletes nothing.",
        "ui saving off\nui delete saves", None, "F32", names=("ui",)),
)


def register_words() -> None:
    """Register ``ui`` (spec and docs). F32 s3 calls it once at import, with the executor;
    calling it again while it is registered does nothing (F19's rule)."""
    if get_spec(WORD_UI) is SPEC:
        return
    register(SPEC)
    for doc in DOCS:
        register_doc(doc)


__all__ = ["DOCS", "FORMS", "HEADING", "SPEC", "UiStatement", "WORD_UI", "parse_ui",
           "reason_ok", "register_words"]
