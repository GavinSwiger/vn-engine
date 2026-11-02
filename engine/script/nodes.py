"""AST nodes of a parsed story (F02 ``04-technical.md`` §4.1).

Named ``nodes`` to avoid confusion with the stdlib ``ast``. Every node is static content:
built from the script files at each launch, treated as immutable once ``load_story``
returns, never saved. Names are stored canonical (NFKC, §7.3.3) and interned. Later
features add ``Statement`` subclasses in their own modules; each defines ``identity_key()``
under ADR-0006's rule.
"""

import types
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from engine.script.texttags import EMPTY_TEXT, TaggedText

if TYPE_CHECKING:
    from engine.script.effects import WithClause    # effects imports this module


@dataclass(slots=True, frozen=True)
class ScriptFile:
    """One story file. ``ref`` is how messages name it; ``order`` is its reading order."""

    ref: str                                          # "script/routes/hana.vns"
    include_path: str                                 # relative to script/: "routes/hana.vns"
    order: int                                        # 0 = main.vns (SR-F02-04)
    depth: int = 0                                    # BFS include depth
    included_by: tuple["ScriptFile", int] | None = None   # first includer + line (E07 chain)


def norm(text: str) -> str:
    """ADR-0006's whitespace normalization: ``" ".join(text.split())``."""
    return " ".join(text.split())


@dataclass(slots=True, kw_only=True)
class Node:
    """Something with a place in a file. Lines and columns are 1-based; ``end_line`` is the
    last physical line of the logical line (continuations included)."""

    file: ScriptFile
    line: int
    end_line: int
    column: int
    sid: str = ""                                     # ADR-0006, assigned after checks


@dataclass(slots=True, kw_only=True)
class PyCode:
    """One piece of author Python: a ``$`` line, a condition, or a define value.

    ``source`` starts at the code's first character; continuation lines are kept whole and
    joined with ``"\\n"``, one code line per physical line, so code line *k* is physical line
    ``line + k - 1``. ``code`` has ``co_filename`` ``"<script/a.vns>"`` (SEC-F02-01); it is
    None only while the piece has an error (the load then fails).
    """

    source: str
    line: int
    column: int
    mode: Literal["exec", "eval"]
    code: types.CodeType | None = field(default=None, compare=False, repr=False)
    names: frozenset[str] = frozenset()               # define values only (§7.6.4)
    comment_free: str | None = field(default=None, compare=False, repr=False)

    def without_comments(self) -> str:
        """The source with Python comments removed (ADR-0006 ``PythonLine`` key)."""
        return self.source if self.comment_free is None else self.comment_free


@dataclass(slots=True, kw_only=True)
class Statement(Node):
    """A story line inside a label block. ``label``/``path`` locate it (``StmtLocation``)."""

    label: str = ""
    path: tuple[int, ...] = ()

    def identity_key(self) -> tuple[str, ...]:
        raise NotImplementedError

    def blocks(self) -> tuple[tuple["Statement", ...], ...]:
        """The statement blocks nested in this statement, in order (F07 C7): an ``If``'s
        branch blocks, a ``Menu``'s choice blocks. Every walk of nested statements
        (``walk_block``, ``Program.at``, F03's successor, F04's look-ahead) goes through
        this, so a path ``p + (b, j)`` is ``blocks()[b][j]`` of the statement at ``p``."""
        return ()

    def inner(self) -> tuple["Statement", ...]:
        """Statements held inside this one that are never walked and take its ``sid``,
        ``label``, and ``path`` (F07: a menu's question, ADR-0006 addendum 1)."""
        return ()


@dataclass(slots=True, kw_only=True)
class Say(Statement):
    """Dialogue (``speaker`` set) or narration (``speaker`` None). ``text`` is the line text
    as written, after escapes and joining (SR-F02-26, 31); ``body`` is that text with its
    tags parsed once at load (F05 ``04-technical.md`` §6.2), still holding ``VarMark``s.
    ``voice`` is the file of the ``voice`` line above it (F08 SR-F08-19, relative to
    ``audio/``), attached by the whole-game checks (``audio_checks``); static line data, not
    part of the line's identity."""

    speaker: str | None
    attributes: tuple[str, ...] = ()
    text: str
    body: TaggedText = EMPTY_TEXT
    voice: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        return ("say", self.speaker or "", norm(self.text))


@dataclass(slots=True, kw_only=True)
class PythonLine(Statement):
    """A ``$`` line."""

    py: PyCode

    def identity_key(self) -> tuple[str, ...]:
        return ("py", norm(self.py.without_comments()))


@dataclass(slots=True, kw_only=True)
class IfBranch:
    """One branch of an if-chain. ``condition`` is None for ``else``."""

    keyword: Literal["if", "elif", "else"]
    condition: PyCode | None
    line: int
    column: int
    block: tuple[Statement, ...] = ()


@dataclass(slots=True, kw_only=True)
class If(Statement):
    """An if-chain: the ``if`` branch, any ``elif`` branches, at most one ``else`` (last)."""

    branches: tuple[IfBranch, ...] = ()

    def identity_key(self) -> tuple[str, ...]:
        first = self.branches[0].condition if self.branches else None
        return ("if", norm(first.source if first is not None else ""))

    def blocks(self) -> tuple[tuple[Statement, ...], ...]:
        return tuple(branch.block for branch in self.branches)


@dataclass(slots=True, kw_only=True)
class Jump(Statement):
    target: str

    def identity_key(self) -> tuple[str, ...]:
        return ("jump", self.target)


@dataclass(slots=True, kw_only=True)
class Call(Statement):
    target: str

    def identity_key(self) -> tuple[str, ...]:
        return ("call", self.target)


@dataclass(slots=True, kw_only=True)
class Return(Statement):
    def identity_key(self) -> tuple[str, ...]:
        return ("return",)


@dataclass(slots=True, kw_only=True)
class Chapter(Statement):
    """F18 ``chapter <name> ["heading"] "title" [seconds] [with ...]`` (SPEC §3), parsed by
    ``script/chapter.py``. ``name`` is canonical (1–64 code points; chapters have their own
    namespace); ``heading`` (None: title only) and ``title`` are plain text as shown
    (``{{`` is already ``{``); ``seconds`` is the hold, None for the default (3.0) and 0 for
    no card; ``with_clause`` is F09's, used for both transitions (None: the built-in
    ``fade``). Not ``VOICE_TRANSPARENT`` (07 I-7)."""

    name: str
    heading: str | None = None
    title: str
    seconds: float | None = None
    with_clause: "WithClause | None" = None

    def identity_key(self) -> tuple[str, ...]:
        return ("chapter", self.name)


@dataclass(slots=True, kw_only=True)
class Label(Node):
    """``label name:`` and its block. Its sid is its name."""

    name: str
    block: tuple[Statement, ...] = ()


@dataclass(slots=True, kw_only=True)
class Define(Node):
    """``define name = value``. Its sid is ``"define:" + name``."""

    name: str
    value: PyCode


@dataclass(slots=True, kw_only=True)
class Default(Node):
    """``default name = value`` (F03 SR-F03-01). Its sid is ``"default:" + name``: a
    declaration, not a position (no ``identity_key``). Never executed in the story; the
    runtime evaluates it on a new game and on a restore that lacks the name."""

    name: str
    value: PyCode


@dataclass(slots=True, kw_only=True)
class PersistentDefault(Node):
    """``default persistent.<name> = value`` (F12 SR-F12-05). Its sid is
    ``"default:persistent." + name``. A declaration of its own type, so F03's new-game and
    restore loops (``Program.defaults``) never see it: the launch evaluates it once, in
    program order, after the defines (F12 ``04-technical.md`` §7.4 phase 2b). ``name`` is
    the part after ``persistent.``."""

    name: str
    value: PyCode


@dataclass(slots=True, kw_only=True)
class Include(Node):
    """``include "path"``. ``target`` is set by the loader. Its sid is ``"include:" + path``."""

    path: str
    target: ScriptFile | None = None
