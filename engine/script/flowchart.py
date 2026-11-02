"""The ``flowchart`` statement (F20 ``02-script.md`` §3; ``04-technical.md`` §6.1–§6.4).

Why this module exists: the flowchart is built at load from the script (F20 s2), and an
author shapes it with one word. Every F20 line starts with ``flowchart``, so one search finds
them all and no existing statement changes shape:

- ``flowchart scene "Title" [hidden] [no jump]``: the label's first statement makes the
  label a scene node.
- ``flowchart ["Title"] [hidden] [no jump]`` (a **node mark**) and ``flowchart omit``: they
  mark the **next statement** in their block, a ``menu:``, ``chapter``, or ``ending``; one
  ``rollback fixed`` line in between is skipped (both orders work: F14's ``attach_fixed``
  skips a node mark through ``ATTACH_SKIPS``, F20 07 A4).
- ``flowchart forget [label]``: runs (F20 s3's recorder); it forgets every node, or the
  nodes written in that label.

**Parse (E260, E263).** The tail is read token by token: ``scene`` + a title + flags;
``omit`` alone; ``forget`` + an optional label name; else an optional title and flags.
Flags (``hidden``, ``no jump``) come after the title, each once. ``scene``, ``omit``,
``forget``, ``hidden``, ``no``, and ``jump`` are read only here, so ``omit``, ``forget``,
``hidden``, and ``no`` stay usable as names. A title follows F18's title rules: 1–120 code
points, shown as written, ``{{`` is ``{`` and any other ``{`` is E263. A ``:`` is E260's
block form. At the top level the line is E261's ``top`` form (``placement="either"``, as
F19's ``ending`` and F23's ``minigame``: ``"story"`` would give F02's E40 there).

**Load (E261, E262, E264; ``iter_attach_marks``, the whole-game checks beside F14's
``attach_fixed``).** One walk of every label block: a scene mark that isn't its label's
first statement is E261; a node mark whose target is missing, of the wrong kind, already
marked, or given a mark it can't take is E262; ``forget`` naming no label is E264. The
walk returns the marks (``FlowMark``) by target, for F20 s2's ``Program.flow_marks``. These
run whatever ``[flowchart] enabled`` says (SR-F20-13).

Identity (ADR-0006): ``("flowchart", form)``; ``forget``: ``("flowchart", "forget", label or
"")``. Titles and flags are not in it, so changing them keeps every sid (SR-F20-06). Each
line is one step (E45), like ``rollback``. Not ``VOICE_TRANSPARENT``.

**Registration (F19 07 I-5).** ``register_words()`` adds the ``StatementSpec``, its
``StatementDoc``s, and the ``ATTACH_SKIPS`` predicate; it runs once at import (the executor,
``runtime/flowchart.py``, is registered by ``interpreter.py``); calling it again does nothing.
``statements.scoped_registry()`` restores ``ATTACH_SKIPS`` too.
"""

from collections.abc import Callable, Container, Generator, Iterable
from dataclasses import dataclass
from typing import Final, Literal

from engine.script.chapter import _shown
from engine.script.diagnostics import Diagnostic, DiagnosticSink
from engine.script.lexer import COLON, FWCOLON, NAME, STRING, TAIL_SCRIPT, RawStatement, Token
from engine.script.limits import IDENTITY_YIELD_ITEMS
from engine.script.menu import Menu
from engine.script.nodes import Chapter, Label, Node, Statement
from engine.script.rollback import ATTACH_SKIPS, Rollback, _next_form
from engine.script.routes import Ending
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, StatementSpec, _between, get_spec, register
from engine.script.suggest import suggest
from engine.script.words import canonical_name

WORD_FLOWCHART: Final = "flowchart"
WORD_SCENE: Final = "scene"
WORD_OMIT: Final = "omit"
WORD_FORGET: Final = "forget"
WORD_HIDDEN: Final = "hidden"
WORD_NO: Final = "no"
WORD_JUMP: Final = "jump"
FLAG_NO_JUMP: Final = "no jump"
TITLE_MAX: Final = 120                  # code points (SR-F20-15, F18's title rule)
# E260's did-you-mean words (02 §5); ``nojump`` and ``no_jump`` suggest "no jump".
SUGGEST_WORDS: Final = (WORD_SCENE, WORD_OMIT, WORD_FORGET, WORD_HIDDEN, FLAG_NO_JUMP)
_NO_JUMP_SPELLINGS: Final = frozenset(("nojump", "no_jump"))
_FIRST_WORDS: Final = frozenset((WORD_SCENE, WORD_OMIT, WORD_FORGET))

Form = Literal["scene", "mark", "omit", "forget"]


@dataclass(slots=True, kw_only=True)
class Flowchart(Statement):
    """A ``flowchart`` line. ``title`` is as shown (``{{`` is already ``{``); ``target`` is
    ``forget``'s canonical label name (None: the whole chart)."""

    form: Form
    title: str | None = None
    hidden: bool = False
    no_jump: bool = False
    target: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        if self.form == WORD_FORGET:
            return (WORD_FLOWCHART, WORD_FORGET, self.target or "")
        return (WORD_FLOWCHART, self.form)


@dataclass(frozen=True, slots=True)
class FlowMark:
    """What a mark says about its target (F20 04 §4): the title (None: the target's own,
    PR-F20-05), the flags, ``omit`` (a menu kept off the chart), and the mark's line. F20
    s2 keys these by the target's sid (``Program.flow_marks``)."""

    title: str | None
    hidden: bool
    no_jump: bool
    omit: bool
    line: int


# What ``iter_attach_marks`` returns: (target, mark) in reading order. The target is the
# scene's ``Label``, or the marked ``Menu``, ``Chapter``, or ``Ending``.
MarkTargets = list[tuple[Node, FlowMark]]


# --- Parse (04 §6.1; E260, E263) ------------------------------------------------------------

class _Error(Exception):
    def __init__(self, code: str, *args: object) -> None:
        super().__init__(code)
        self.code = code
        self.args_ = args


def _written(raw: RawStatement, items: list[Token], index: int) -> str:
    """Item ``index`` as written: a word's text, else its source up to the next item."""
    token = items[index]
    if token.kind == NAME:
        return token.text
    stop = items[index + 1] if index + 1 < len(items) else None
    return _between(raw, token, stop)


def _unknown(raw: RawStatement, items: list[Token], index: int) -> _Error:
    written = _written(raw, items, index)
    if written.casefold() in _NO_JUMP_SPELLINGS or written == WORD_NO:
        return _Error("E260", "unknown", written, FLAG_NO_JUMP)
    return _Error("E260", "unknown", written, suggest(written, SUGGEST_WORDS))


def _title(text: str) -> str:
    """A title as shown (SR-F20-15), or raises E263."""
    shown = _shown(text)
    if shown is None:
        raise _Error("E263", "tags")
    if not shown.strip():
        raise _Error("E263", "empty")
    if len(shown) > TITLE_MAX:
        raise _Error("E263", "long", len(shown), TITLE_MAX)
    return shown


def _marks(raw: RawStatement, items: list[Token], start: int, *, scene: bool
           ) -> tuple[str | None, bool, bool]:
    """``[title] {flag}`` from ``items[start:]``: the raw title text, ``hidden``,
    ``no_jump``. A scene's title is required (the caller checks)."""
    title: str | None = None
    hidden = no_jump = False
    flagged = False
    index = start
    while index < len(items):
        token = items[index]
        if token.kind == STRING:
            if flagged:
                raise _Error("E260", "order", scene)
            if title is not None:
                raise _Error("E260", "two_titles")
            title = token.text
        elif token.kind == NAME and token.text == WORD_HIDDEN:
            if hidden:
                raise _Error("E260", "twice", WORD_HIDDEN)
            hidden = flagged = True
        elif token.kind == NAME and token.text == WORD_NO:
            nxt = items[index + 1] if index + 1 < len(items) else None
            if nxt is None or nxt.kind != NAME or nxt.text != WORD_JUMP:
                raise _unknown(raw, items, index)
            if no_jump:
                raise _Error("E260", "twice", FLAG_NO_JUMP)
            no_jump = flagged = True
            index += 1
        elif token.kind == NAME and token.text in _FIRST_WORDS:
            raise _Error("E260", "place", token.text)
        else:
            raise _unknown(raw, items, index)
        index += 1
    return title, hidden, no_jump


def _read(raw: RawStatement, items: list[Token]) -> tuple[Form, str | None, bool, bool,
                                                          str | None]:
    """The tail's form, title (as shown), flags, and forget's target; raises ``_Error``."""
    first = items[0] if items else None
    word = first.text if first is not None and first.kind == NAME else None
    if word == WORD_OMIT:
        if len(items) > 1:
            raise _Error("E260", "omit_more")
        return "omit", None, False, False, None
    if word == WORD_FORGET:
        if len(items) == 1:
            return "forget", None, False, False, None
        target = items[1]
        if target.kind != NAME or len(items) > 2:
            rest = 2 if target.kind == NAME else 1
            raise _Error("E260", "forget_more", _between(raw, items[rest], None))
        return "forget", None, False, False, canonical_name(target.text)
    if word == WORD_SCENE:
        if len(items) < 2 or items[1].kind != STRING:
            raise _Error("E260", "scene_title")
        title, hidden, no_jump = _marks(raw, items, 1, scene=True)
        assert title is not None
        return "scene", _title(title), hidden, no_jump, None
    title, hidden, no_jump = _marks(raw, items, 0, scene=False)
    return "mark", None if title is None else _title(title), hidden, no_jump, None


def parse_flowchart(raw: RawStatement, ctx: ParseContext) -> Flowchart | None:
    """A ``flowchart`` line (module docstring). Errors are pending on ``raw``."""
    tokens = raw.tokens[1:]
    colon = tokens[-1] if tokens and tokens[-1].kind in (COLON, FWCOLON) else None
    items = tokens[:-1] if colon is not None else tokens
    if ctx.depth == 0:
        forget = bool(items) and items[0].kind == NAME and items[0].text == WORD_FORGET
        ctx.error("E261", "top", forget)
        return None
    try:
        form, title, hidden, no_jump, target = _read(raw, items)
    except _Error as error:
        ctx.error(error.code, *error.args_)
        return None
    if colon is not None or raw.ends_with_colon:
        ctx.error("E260", "block")
        return None
    return Flowchart(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     form=form, title=title, hidden=hidden, no_jump=no_jump, target=target)


# --- Load checks (04 §6.2; E261, E262, E264) --------------------------------------------------

def _is_fixed(stmt: Statement | None) -> bool:
    return isinstance(stmt, Rollback) and stmt.word == "fixed"


def _target(block: tuple[Statement, ...], index: int) -> tuple[Statement | None, int]:
    """The statement a mark at ``block[index]`` marks (one ``rollback fixed`` skipped), and
    its index (``len(block)`` for none)."""
    at = index + 1
    if at < len(block) and _is_fixed(block[at]):
        at += 1
    return (block[at] if at < len(block) else None), at


def _is_mark(stmt: Statement | None) -> bool:
    return isinstance(stmt, Flowchart) and stmt.form in ("mark", "omit")


def _kind(stmt: Statement | None) -> str:
    """E262 form 3's word for the marked statement."""
    if isinstance(stmt, Menu):
        return "menu"
    if isinstance(stmt, Chapter):
        return "chapter"
    if isinstance(stmt, Ending):
        return "ending"
    return "line"


def _mark_problem(mark: Flowchart, target: Statement | None, block: tuple[Statement, ...],
                  at: int) -> tuple | None:
    """E262's args for a node mark, or None when it marks ``target`` fine."""
    if _is_mark(target):
        assert target is not None
        below, _ = _target(block, at)
        return ("two", _kind(below), mark.line, target.line)
    if isinstance(target, Menu):
        return None
    if isinstance(target, (Chapter, Ending)):
        kind = "chapter" if isinstance(target, Chapter) else "ending"
        if mark.form == WORD_OMIT:
            return ("omit", kind)
        if mark.title is None and not mark.hidden and not mark.no_jump:
            return ("bare", kind)
        if kind == "ending" and (mark.title is not None or mark.no_jump):
            return ("ending",)
        if mark.title is not None:
            return ("chapter", mark.title)
        return None
    return ("next", _next_form(target), None if target is None else target.line)


def iter_attach_marks(nodes: Iterable[Node], sink: DiagnosticSink,
                      labels: Container[str] | None = None,
                      suggest_label: Callable[[str], str | None] | None = None
                      ) -> Generator[None, None, MarkTargets]:
    """The load checks of every ``flowchart`` line (module docstring) and the marks by
    target. ``labels`` None (a file couldn't be read) skips E264. Yields every
    ``IDENTITY_YIELD_ITEMS`` statements; no recursion."""
    found: MarkTargets = []
    count = 0
    for node in nodes:
        if not isinstance(node, Label):
            continue
        stack: list[tuple[tuple[Statement, ...], bool]] = [(node.block, True)]
        while stack:
            block, top = stack.pop()
            for index, stmt in enumerate(block):
                count += 1
                if count % IDENTITY_YIELD_ITEMS == 0:
                    yield
                stack.extend((inner, False) for inner in stmt.blocks())
                if not isinstance(stmt, Flowchart):
                    continue
                if stmt.form == WORD_SCENE:
                    if top and index == 0:
                        found.append((node, FlowMark(stmt.title, stmt.hidden, stmt.no_jump,
                                                     False, stmt.line)))
                    else:
                        sink.add(Diagnostic("E261", stmt.file, stmt.line, None,
                                            ("first", node.name, node.block[0].line),
                                            stmt=stmt.line))
                elif stmt.form == WORD_FORGET:
                    if (labels is not None and stmt.target is not None
                            and stmt.target not in labels):
                        hint = suggest_label(stmt.target) if suggest_label else None
                        sink.add(Diagnostic("E264", stmt.file, stmt.line, None,
                                            (stmt.target, hint), stmt=stmt.line))
                else:
                    target, at = _target(block, index)
                    problem = _mark_problem(stmt, target, block, at)
                    if problem is not None:
                        sink.add(Diagnostic("E262", stmt.file, stmt.line, None, problem,
                                            stmt=stmt.line))
                    else:
                        assert target is not None
                        found.append((target, FlowMark(stmt.title, stmt.hidden, stmt.no_jump,
                                                       stmt.form == WORD_OMIT, stmt.line)))
    return found


def skips_attach_fixed(stmt: Statement) -> bool:
    """F14's ``ATTACH_SKIPS`` predicate (07 A4): ``rollback fixed`` looks past a node mark."""
    return type(stmt) is Flowchart and stmt.form in ("mark", "omit")


# --- Registration (F19 07 I-5) ---------------------------------------------------------------

SPEC: Final = StatementSpec(word=WORD_FLOWCHART, placement="either", takes_block=False,
                            tail=TAIL_SCRIPT, parse=parse_flowchart)

HEADING: Final = "flowchart (the story map)"   # docs/script-language.md (F20 s9)
DOCS: Final = (
    StatementDoc(
        WORD_FLOWCHART, "Flowchart scene", "Story flow",
        'flowchart scene "title" [hidden] [no jump]',
        "On a label's first line: the label is a box on the Flowchart page, with this title. "
        "hidden keeps it off the chart until reached; no jump never offers Jump.",
        'flowchart scene "The Festival"', HEADING, "F20", fields=("The Festival",)),
    StatementDoc(
        WORD_FLOWCHART, "Flowchart choice", "Choices", 'flowchart ["title"] [hidden] [no jump]',
        "Right above a menu: puts the menu on the Flowchart page as a choice box. Above a "
        "chapter or ending it takes only hidden (and no jump for a chapter).",
        'flowchart "Where should we go?"\nmenu:\n    "The river":\n        jump river\n'
        '    "The bridge":\n        jump bridge',
        HEADING, "F20", fields=("Where should we go?",)),
    StatementDoc(
        WORD_FLOWCHART, "Leave a menu off the flowchart", "Choices", "flowchart omit",
        "Right above a menu: the menu is never a box on the Flowchart page.",
        'flowchart omit\nmenu:\n    "Tea":\n        "Warm."\n    "Juice":\n        "Sweet."',
        HEADING, "F20"),
    StatementDoc(
        WORD_FLOWCHART, "Forget the flowchart", "Story flow", "flowchart forget [<label>]",
        "Makes the game forget the boxes reached on the Flowchart page: all of them, or "
        "those written in one label. Loading or rolling back doesn't undo it.",
        "flowchart forget", HEADING, "F20", names=("label",)),
)


def register_words() -> None:
    """Register ``flowchart`` (spec, docs, the ``ATTACH_SKIPS`` predicate). Called once at
    import; calling it again while it is registered does nothing (F19's rule)."""
    if get_spec(WORD_FLOWCHART) is SPEC:
        return
    register(SPEC)
    for doc in DOCS:
        register_doc(doc)
    if skips_attach_fixed not in ATTACH_SKIPS:
        ATTACH_SKIPS.append(skips_attach_fixed)


register_words()                            # F20 s1 (F19 07 I-5)

__all__ = ["DOCS", "FLAG_NO_JUMP", "FlowMark", "Flowchart", "MarkTargets", "SPEC",
           "SUGGEST_WORDS", "TITLE_MAX", "WORD_FLOWCHART", "iter_attach_marks",
           "parse_flowchart", "register_words", "skips_attach_fixed"]
