"""The ``minigame`` statement (F23 ``02-script.md`` §2.1; ``04-technical.md`` §5.1, §5.2).

Why this module exists: a writer starts a piece of plugin gameplay with one story line,
``minigame <name> [skippable] [<arg>=<value> …] [into <variable>]``, and the load must check
it against the plugins' signatures (``checks.py``) before anything runs. Argument values are
Python, so the line is read with a Python tail (``py_condition``: brackets, strings, and
comments across lines) and split with Python's own tokenizer (SR-F23-02):

1. No tokens → E270 ``no_name``; the first token not a name → ``left``.
2. ``skippable`` second, not followed by ``=`` → the flag; a later ``skippable`` outside
   brackets that starts a new word → E271 ``skippable_place``.
3. The target: the last ``into`` outside brackets whose token before isn't ``=``. Nothing
   after it → E270 ``into_alone``; one name → ``target``; a dotted, subscripted, or other
   target → ``not_plain`` (``points``, ``persistent``, or ``other``); a name and more →
   ``left``. Without ``into``, ``as <name>`` at the end → E270 ``as``.
4. Each name outside brackets followed by a single ``=`` starts an argument; its value runs
   to the next start or the target. Words before the first argument, a value that is empty,
   or words left after a value's longest compiling prefix give E271 (``space``, ``double``,
   ``bare``, ``empty``), or E270 ``left`` when they don't start with a name (``with
   dissolve``, a trailing ``:``). A repeat is E271 ``twice``.
5. Each value is compiled as an eval-mode piece (``ctx.compile``, role ``the argument
   <name>``: F02's Python messages as E81 naming it); ``bindings.iter_pieces`` gives it to
   F12 3a's walk as a condition (E87/E88, E233, E255).

``into`` and ``skippable`` are read only in these positions, so they stay usable as names.
At the top level the line is E270 ``top`` (``placement="either"``, as F19's ``ending``:
``"story"`` would give F02's E40 there). The identity is ``("minigame", name, target or
"")`` (ADR-0006): arguments, ``skippable``, and ``fixed`` (set by ``rollback.attach_fixed``,
F14 A3) are left out. ``Minigame`` is not ``VOICE_TRANSPARENT`` (a voice above it is W20).

**Registration (F19 07 I-5).** ``register_words()`` adds the ``StatementSpec`` and its
``StatementDoc``. Since F23 s2 (the executor, ``runtime/minigame.py``, registered by
``interpreter.py``) it runs once at import, through the one line in ``script/__init__.py``;
calling it again does nothing, so the s1 tests that call it inside
``statements.scoped_registry()`` still run.
"""

import keyword
import tokenize
from dataclasses import dataclass
from typing import Final

from engine.script.lexer import TAIL_CONDITION, RawStatement
from engine.script.nodes import PyCode, Statement
from engine.script.pycheck import argument_role, compiles_as_expression
from engine.script.statement_docs import StatementDoc, register_doc
from engine.script.statements import ParseContext, StatementSpec, get_spec, register
from engine.script.words import canonical_name

WORD_MINIGAME: Final = "minigame"
WORD_INTO: Final = "into"
WORD_SKIPPABLE: Final = "skippable"
WORD_AS: Final = "as"
# Where a value's leftover is searched (step 4): the longest compiling prefix among the last
# this many bracket-free token boundaries; past it the value's own Python message is shown.
PREFIX_TRIES: Final = 32

_SKIP = frozenset((tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.ENDMARKER,
                   tokenize.INDENT, tokenize.DEDENT))
_OPEN, _CLOSE = frozenset("([{"), frozenset(")]}")
_REST = -1                                  # the part the tokenizer couldn't read


@dataclass(slots=True, kw_only=True)
class MinigameArg:
    """One written argument: its name, its compiled value, and the value's first token's
    file line and column."""

    name: str
    value: PyCode
    line: int
    column: int


@dataclass(slots=True, kw_only=True)
class Minigame(Statement):
    """``minigame <name> [skippable] [<arg>=<value> …] [into <variable>]``. ``args`` in
    written order. ``fixed``: a ``rollback fixed`` line is right above it (F14 A3); static,
    not part of the identity."""

    name: str
    skippable: bool = False
    args: tuple[MinigameArg, ...] = ()
    target: str | None = None
    fixed: bool = False

    def identity_key(self) -> tuple[str, ...]:
        return (WORD_MINIGAME, self.name, self.target or "")


@dataclass(slots=True)
class _Tok:
    kind: int                 # tokenize's type, or _REST
    text: str
    start: int                # offsets into the span's source
    end: int
    row: int                  # 1-based code line
    col: int                  # 0-based column in that code line
    depth: int                # brackets open before it (a closer: after it)

    @property
    def is_name(self) -> bool:
        return self.kind == tokenize.NAME

    def is_op(self, text: str) -> bool:
        return self.kind == tokenize.OP and self.text == text


class _Error(Exception):
    """One parse error: E270/E271 with its form and args, at the statement's line."""

    def __init__(self, code: str, *args: object) -> None:
        super().__init__(code)
        self.code = code
        self.args_ = args


def _tokens(source: str) -> list[_Tok]:
    """The significant tokens of ``source``; what the tokenizer couldn't read (an unclosed
    string, a bracket open at the end) is one ``_REST`` token, left for ``compile``'s
    message."""
    starts = [0]
    for line in source.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    found: list[_Tok] = []
    depth = 0
    reached = 0
    try:
        for tok in tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__):
            if tok.type in _SKIP:
                continue
            (srow, scol), (erow, ecol) = tok.start, tok.end
            start, end = starts[srow - 1] + scol, starts[erow - 1] + ecol
            if tok.type == tokenize.OP and tok.string in _CLOSE:
                depth = max(0, depth - 1)
            found.append(_Tok(tok.type, tok.string, start, end, srow, scol, depth))
            if tok.type == tokenize.OP and tok.string in _OPEN:
                depth += 1
            reached = end
    except (tokenize.TokenError, SyntaxError):
        rest = source[reached:]
        stripped = rest.lstrip()
        if stripped:
            start = reached + len(rest) - len(stripped)
            row = source.count("\n", 0, start) + 1
            col = start - starts[row - 1]
            found.append(_Tok(_REST, stripped.rstrip(), start, len(source.rstrip()), row, col,
                              depth))
    return found


def _text(source: str, toks: list[_Tok]) -> str:
    return source[toks[0].start:toks[-1].end] if toks else ""


def _ends_word(tok: _Tok) -> bool:
    """True if ``tok`` can end an expression, so a name after it starts a new word."""
    if tok.kind == tokenize.NAME:
        return not keyword.iskeyword(tok.text) or tok.text in ("None", "True", "False")
    return tok.kind in (tokenize.NUMBER, tokenize.STRING) or (
        tok.kind == tokenize.OP and tok.text in _CLOSE)


def _stray(source: str, toks: list[_Tok], *, leftover: str | None) -> _Error:
    """The error for words that aren't an argument (step 4). ``leftover`` is what came
    before them when they follow a value (E270 ``left`` unless they start with a name),
    None before the first argument (E271 ``bare`` then)."""
    first = toks[0]
    plain_name = first.is_name and not keyword.iskeyword(first.text)
    if plain_name and len(toks) > 1 and toks[1].is_op("=="):
        return _Error("E271", "double", first.text, _text(source, toks[2:]))
    if plain_name and len(toks) > 1 and toks[1].kind != tokenize.OP:
        return _Error("E271", "space", first.text, _text(source, toks[1:]))
    if plain_name or leftover is None:
        return _Error("E271", "bare", _text(source, toks))
    return _Error("E270", "left", _text(source, toks), leftover)


def _target(source: str, toks: list[_Tok], cut: int) -> str | None:
    """Step 3: the target after ``into`` at ``cut`` (or raises)."""
    after = toks[cut + 1:]
    if not after:
        raise _Error("E270", "into_alone")
    first = after[0]
    if first.is_name and len(after) == 1:
        return canonical_name(first.text)
    if first.is_name and (after[1].is_op(".") or after[1].is_op("[")):
        written = _text(source, after)
        if first.text in ("points", "persistent") and len(after) == 3 and \
                after[1].is_op(".") and after[2].is_name:
            raise _Error("E270", "not_plain", first.text, written, after[2].text)
        raise _Error("E270", "not_plain", "other", written, "")
    if first.is_name:
        raise _Error("E270", "left", _text(source, after[1:]),
                     f"{WORD_INTO} {first.text}")
    raise _Error("E270", "not_plain", "other", _text(source, after), "")


def _find_cut(toks: list[_Tok], begin: int) -> int | None:
    """The index of the target's ``into`` (step 3), or None."""
    for index in range(len(toks) - 1, begin - 1, -1):
        tok = toks[index]
        if tok.depth == 0 and tok.is_name and tok.text == WORD_INTO and \
                not toks[index - 1].is_op("="):
            return index
    return None


def _value_end(source: str, toks: list[_Tok]) -> int:
    """How many of the value's ``toks`` make its value: all, when they compile as one
    expression (or none does); else the longest prefix that does (its leftover follows)."""
    if compiles_as_expression(_text(source, toks)):
        return len(toks)
    tries = 0
    for end in range(len(toks) - 1, 0, -1):
        if toks[end - 1].depth != 0 or toks[end - 1].kind == _REST:
            continue
        tries += 1
        if tries > PREFIX_TRIES:
            break
        if compiles_as_expression(_text(source, toks[:end])):
            return end
    return len(toks)


def _split(source: str, toks: list[_Tok]
           ) -> tuple[str, bool, list[tuple[_Tok, list[_Tok]]], str | None]:
    """Steps 1–4 on the tokens: the name, the flag, ``(name token, value tokens)`` per
    argument, and the target. Raises ``_Error``."""
    if not toks:
        raise _Error("E270", "no_name")
    if not toks[0].is_name:
        raise _Error("E270", "left", _text(source, toks), WORD_MINIGAME)
    name = toks[0].text
    begin = 1
    skippable = False
    if len(toks) > 1 and toks[1].is_name and toks[1].text == WORD_SKIPPABLE and \
            not (len(toks) > 2 and toks[2].is_op("=")):
        skippable = True
        begin = 2
    cut = _find_cut(toks, begin)
    end = len(toks) if cut is None else cut
    target = None
    if cut is not None:
        target = _target(source, toks, cut)
    elif end - begin >= 2 and toks[end - 2].depth == 0 and toks[end - 2].is_name and \
            toks[end - 2].text == WORD_AS and toks[end - 1].is_name and \
            not toks[end - 3].is_op("="):
        raise _Error("E270", "as", toks[end - 1].text)
    starts = [i for i in range(begin, end - 1)
              if toks[i].depth == 0 and toks[i].is_name and toks[i + 1].is_op("=")]
    for index in range(max(begin, 2), end):
        tok = toks[index]
        if tok.depth == 0 and tok.is_name and tok.text == WORD_SKIPPABLE and \
                _ends_word(toks[index - 1]) and index not in starts:
            example = f"{WORD_MINIGAME} {name} {WORD_SKIPPABLE}"
            if starts:                       # with the line's first argument, as written
                stop = min((i for i in (*starts[1:], index) if i > starts[0]), default=end)
                example += " " + _text(source, toks[starts[0]:stop])
            raise _Error("E271", "skippable_place", example)
    if toks[begin:starts[0] if starts else end]:
        raise _stray(source, toks[begin:starts[0] if starts else end], leftover=None)
    args: list[tuple[_Tok, list[_Tok]]] = []
    seen: set[str] = set()
    for number, start in enumerate(starts):
        stop = starts[number + 1] if number + 1 < len(starts) else end
        arg, value = toks[start], toks[start + 2:stop]
        if not value:
            raise _Error("E271", "empty", arg.text)
        if arg.text in seen:
            raise _Error("E271", "twice", arg.text)
        seen.add(arg.text)
        keep = _value_end(source, value)
        if keep < len(value):
            raise _stray(source, value[keep:],
                         leftover=f"{arg.text}={_text(source, value[:keep])}")
        args.append((arg, value))
    return name, skippable, args, target


def parse_minigame(raw: RawStatement, ctx: ParseContext) -> Minigame | None:
    """The ``minigame`` line (module docstring). Errors are pending on ``raw``."""
    if ctx.depth == 0:
        ctx.error("E270", "top")
        return None
    span = raw.py
    assert span is not None
    if span.truncated:
        ctx.compile(span.source, line=span.line, column=span.column, mode="eval",
                    role="this minigame line", lambdas=span.lambdas, length=span.length)
        return None
    source = span.source
    try:
        name, skippable, written, target = _split(source, _tokens(source))
    except _Error as error:
        ctx.error(error.code, *error.args_)
        return None
    args = []
    for arg, value in written:
        first = value[0]
        line = span.line + first.row - 1
        column = span.column + first.col if first.row == 1 else first.col + 1
        text = _text(source, value)
        lambdas = sum(1 for tok in value if tok.is_name and tok.text == "lambda")
        py, _ = ctx.compile(text, line=line, column=column, mode="eval",
                            role=argument_role(arg.text), lambdas=lambdas, length=len(text))
        if py.code is None:
            return None
        args.append(MinigameArg(name=arg.text, value=py, line=line, column=column))
    return Minigame(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                    name=name, skippable=skippable, args=tuple(args), target=target)


SPEC: Final = StatementSpec(word=WORD_MINIGAME, placement="either", takes_block=False,
                            tail=TAIL_CONDITION, parse=parse_minigame)

DOC: Final = StatementDoc(
    WORD_MINIGAME, "Minigame", "Story flow",
    "minigame <name> [skippable] [<arg>=<value> ...] [into <variable>]",
    "Starts a minigame and waits until the player finishes it. The result goes into a "
    "variable that has a default.",
    "minigame lantern_memory pairs=6 into turns", None, "F23",
    fields=("lantern_memory", "pairs=6", "turns"))


def register_words() -> None:
    """Register ``minigame`` (spec and doc). F23 s2 calls it at import; until then tests
    call it inside ``statements.scoped_registry()`` (F19 07 I-5). Calling it again while it
    is registered does nothing (F19's ``routes.register_words`` rule), so these tests keep
    running once s2 registers at import."""
    if get_spec(WORD_MINIGAME) is SPEC:
        return
    register(SPEC)
    register_doc(DOC)


register_words()                            # F23 s2 (F19 07 I-5)


__all__ = ["DOC", "Minigame", "MinigameArg", "PREFIX_TRIES", "SPEC", "WORD_MINIGAME",
           "parse_minigame", "register_words"]
