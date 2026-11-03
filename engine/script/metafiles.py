"""The ``file`` statement: meta files in ``<game>/characters/`` (F31 ``04-technical.md`` §3,
§4.1, §5.1, §5.3; ``01-design.md`` SR-F31-01..06; load codes E309–E312, E315).

Why this module exists: a story writes, deletes, and checks small files the player can see
in the game folder, written as one line each, checked once at load, so the runtime gets a
listed name, the text, and a variable name and never parses anything:

- ``file write "<name>" ["<text>"]``: the text (F02 escapes applied, braces as written), or
  None to copy ``files/<name>`` (E313 at load, ``checks.py``).
- ``file delete "<name>"``.
- ``file exists "<name>" into <variable>`` and ``file read "<name>" into <variable>``
  (``read`` on ``.txt`` names only, E315).

**Parse (04 §5.1).** Tokens after ``file``; a trailing ``:`` is E309 ``block``, checked
first. No token: E309 ``needs``; a first word that isn't one of the four verbs: E309
``unknown`` (did-you-mean over the four). The name must be a quoted string (a word is E310
``variable``) that passes ``name_problem`` (E310's forms in the order ``slash``,
``capitals``, ``ending``, ``reserved``, ``long``, ``chars``; the same rule as
``core.paths.META_NAME_RE``). A write's text is at most ``META_TEXT_MAX_CHARS`` code points
(E311 ``long``) with no control character but ``\\n`` and ``\\t`` (E311 ``control``, a
defence: F02 refuses a raw control character first, 06 G6). Words left over are E309
``left``; ``exists``/``read`` need ``into`` and one plain name (E312 ``needs``,
``one_name``). The verbs and ``into`` are read only here, so they stay usable as names
(``default write = 1``). The parser makes no file-system call, and this module imports no
``os``, ``pathlib``, ``io``, or ``engine.meta`` (AC-F31-08).

Identity (ADR-0006): ``("file", verb, name)``: the text isn't in it, so editing it keeps
the sid. Each line is one step (E45). ``MetaFile`` is ``VOICE_TRANSPARENT``
(``audio_checks.py``). ``Program.meta_files`` holds every name (``program.py``); the
whole-game checks (E312's target forms, E313, E314) are ``checks.py``'s step 12.

**Registration (04 §5.3; F19 07 I-5).** ``register_words()`` adds the ``StatementSpec`` and
the four ``StatementDoc``s; calling it again does nothing. F31 s2 defines it without calling
it at import, so a real game keeps F02's E32 for ``file`` until F31 s3 registers the
executor (``runtime/metafiles.run_file``) and adds the import-time call.
"""

import unicodedata
from dataclasses import dataclass
from typing import Final, Literal

from engine.core.constants import META_TEXT_MAX_CHARS
from engine.core.paths import META_RESERVED_BASES, is_meta_name
from engine.script.lexer import COLON, FWCOLON, NAME, STRING, TAIL_SCRIPT, RawStatement, Token
from engine.script.nodes import Statement
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, StatementSpec, _between, get_spec, register
from engine.script.suggest import suggest
from engine.script.words import canonical_name

WORD_FILE: Final = "file"
WORD_INTO: Final = "into"
WRITE: Final = "write"
DELETE: Final = "delete"
EXISTS: Final = "exists"
READ: Final = "read"
VERBS: Final = (WRITE, DELETE, EXISTS, READ)
_ENDINGS: Final = (".chr", ".txt")
_TEXT_CONTROLS_OK: Final = frozenset("\n\t")
# The longest base before ``.chr``/``.txt`` (``META_NAME_RE``'s ``[a-z0-9][a-z0-9_-]{0,31}``).
NAME_BASE_MAX: Final = 32

Verb = Literal["write", "delete", "exists", "read"]


@dataclass(slots=True, kw_only=True)
class MetaFile(Statement):
    """``file <verb> "<name>" …`` (04 §3). ``name`` passes ``is_meta_name``; ``text`` is a
    write's text (None: copy ``files/<name>``); ``target`` the canonical ``into`` name of
    ``exists`` and ``read``."""

    verb: Verb
    name: str
    text: str | None = None
    target: str | None = None

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_FILE, self.verb, self.name)


# --- Parse (04 §5.1; E309–E312, E315) ---------------------------------------------------------

def name_problem(text: str) -> str | None:
    """E310's form for a written name, or None when ``is_meta_name`` accepts it (04 §5.1
    step 2's order: ``slash``, ``capitals``, ``ending``, ``reserved``, ``long``, ``chars``)."""
    if "/" in text or "\\" in text:
        return "slash"
    if any(char.isupper() for char in text):
        return "capitals"
    if not text.endswith(_ENDINGS):
        return "ending"
    base = text[:-len(_ENDINGS[0])]
    if base in META_RESERVED_BASES:
        return "reserved"
    if len(base) > NAME_BASE_MAX:
        return "long"
    if not is_meta_name(text):
        return "chars"
    return None


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


def _text(name: str, token: Token) -> str:
    """A write's text (E311)."""
    text = token.text
    if len(text) > META_TEXT_MAX_CHARS:
        raise _Error("E311", "long", name, len(text))
    bad = next((char for char in text if char not in _TEXT_CONTROLS_OK
                and unicodedata.category(char) == "Cc"), None)
    if bad is not None:
        raise _Error("E311", "control", name, bad)
    return text


def _target(raw: RawStatement, verb: str, rest: list[Token]) -> str:
    """``into <name>`` after an ``exists``/``read`` name (E312 ``needs``, ``one_name``)."""
    if not rest or rest[0].kind != NAME or rest[0].text != WORD_INTO or len(rest) < 2:
        raise _Error("E312", "needs", verb)
    after = rest[1:]
    if len(after) == 1 and after[0].kind == NAME:
        return canonical_name(after[0].text)
    raise _Error("E312", "one_name", verb, _between(raw, after[0], None))


def _read(raw: RawStatement, items: list[Token]) -> tuple[str, str, str | None, str | None]:
    """The line's verb, name, text, and target; raises ``_Error``."""
    if not items:
        raise _Error("E309", "needs", None)
    first = items[0]
    if first.kind != NAME or first.text not in VERBS:
        written = _written(raw, items, 0)
        raise _Error("E309", "unknown", written, suggest(written, VERBS))
    verb = first.text
    if len(items) < 2:
        raise _Error("E309", "needs", verb)
    token = items[1]
    if token.kind == NAME:
        raise _Error("E310", "variable", token.text)
    if token.kind != STRING:
        raise _Error("E309", "needs", verb)
    name = token.text
    problem = name_problem(name)
    if problem is not None:
        raise _Error("E310", problem, name)
    rest = items[2:]
    text = target = None
    if verb == WRITE:
        if rest and rest[0].kind == STRING:
            text = _text(name, rest[0])
            rest = rest[1:]
    elif verb in (EXISTS, READ):
        if verb == READ and name.endswith(_ENDINGS[0]):
            raise _Error("E315", name)
        return verb, name, None, _target(raw, verb, rest)
    if rest:
        left = items.index(rest[0])
        raise _Error("E309", "left", verb, _written(raw, items, left))
    return verb, name, text, target


def parse_file(raw: RawStatement, ctx: ParseContext) -> MetaFile | None:
    """A ``file`` line (module docstring). Errors are pending on ``raw``."""
    tokens = raw.tokens[1:]
    colon = tokens[-1] if tokens and tokens[-1].kind in (COLON, FWCOLON) else None
    if colon is not None or raw.ends_with_colon:
        ctx.error("E309", "block")
        return None
    try:
        verb, name, text, target = _read(raw, tokens)
    except _Error as error:
        ctx.error(error.code, *error.args_)
        return None
    return MetaFile(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                    verb=verb, name=name, text=text, target=target)   # type: ignore[arg-type]


# --- Registration (04 §5.3; F19 07 I-5) -------------------------------------------------------

SPEC: Final = StatementSpec(word=WORD_FILE, placement="story", takes_block=False,
                            tail=TAIL_SCRIPT, parse=parse_file)

# Four Insert entries in "Files". ``docs`` is None until F31 s5 writes the "Meta files"
# section; ``meta_file`` is the name kind F31 s5 adds to tools/check.py's NAME_SOURCES. The
# examples load in tests/fixtures/docgame/ once F31 s5 adds files/hana.chr and the two
# defaults (06 §5).
DOCS: Final = (
    StatementDoc(
        WORD_FILE, "Write a meta file", "Files", 'file write "<name>" ["<text>"]',
        "Puts a file in the game's characters folder, where the player can see it: the "
        "text given, or a copy of files/<name>.",
        'file write "hana.chr"', None, "F31", fields=("hana.chr",), names=("meta_file",)),
    StatementDoc(
        WORD_FILE, "Delete a meta file", "Files", 'file delete "<name>"',
        "Deletes a file the story wrote in the game's characters folder.",
        'file delete "hana.chr"', None, "F31", fields=("hana.chr",), names=("meta_file",)),
    StatementDoc(
        WORD_FILE, "Check a meta file", "Files", 'file exists "<name>" into <variable>',
        "Sets a variable to True if the file is in the characters folder, else False.",
        'file exists "hana.chr" into hana_here', None, "F31",
        fields=("hana.chr", "hana_here"), names=("meta_file",)),
    StatementDoc(
        WORD_FILE, "Read a meta file", "Files", 'file read "<name>" into <variable>',
        "Reads a .txt file the player may have changed into a variable: its text, or None.",
        'file read "answer.txt" into answer', None, "F31",
        fields=("answer.txt", "answer"), names=("meta_file",)),
)


def register_words() -> None:
    """Register ``file`` (spec and docs). Not called at import until F31 s3 (module
    docstring); tests call it inside ``statements.scoped_registry()``. Calling it again
    while it is registered does nothing (F19's rule)."""
    if get_spec(WORD_FILE) is SPEC:
        return
    register(SPEC)
    for doc in DOCS:
        register_doc(doc)


__all__ = ["DELETE", "DOCS", "EXISTS", "MetaFile", "NAME_BASE_MAX", "READ", "SPEC", "VERBS",
           "WORD_FILE", "WORD_INTO", "WRITE", "name_problem", "parse_file", "register_words"]
