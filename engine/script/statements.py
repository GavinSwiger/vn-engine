"""The statement registry and the F02 statements (F02 ``04-technical.md`` §5.1, §6.1).

A feature adds a statement with ``register(StatementSpec)`` in its own module under
``engine/script/``, imported by one explicit line in ``engine/script/__init__.py``. F02
registers ``label``, ``define``, ``include`` (top level) and ``jump``, ``call``, ``return``,
``if``, ``elif``, ``else`` (story); ``$`` lines, narration, and dialogue are built in. A
reserved word with no spec gives E32 (E32b for ``at``/``as``/``behind``, E33 for
``python``).

Statement parsers report through ``ParseContext.error``: errors stay pending on the
``RawStatement`` until the block parser reports the first of them (SR-F02-68).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

from engine.core.constants import BUILTIN_POSITIONS
from engine.script.diagnostics import Diagnostic, DiagnosticSink, WarningLog
from engine.script.lexer import (
    COLON,
    CURLY,
    EQUALS,
    FWCOLON,
    NAME,
    PATH,
    SQUOTE,
    STRING,
    SYMBOL,
    TAIL_AFTER_EQUALS,
    TAIL_CONDITION,
    TAIL_PATH,
    TAIL_PY_ALL,
    TAIL_SCRIPT,
    RawStatement,
    Token,
    span_line,
)
from engine.script.limits import SCRIPT_MAX_ATTRIBUTES, SCRIPT_TODO_LOG_LIMIT
from engine.script.nodes import (
    Call,
    Define,
    If,
    IfBranch,
    Include,
    Jump,
    Label,
    Node,
    PyCode,
    PythonLine,
    Return,
    Say,
    ScriptFile,
)
from engine.script.pycheck import (
    COMPILE_NAME,
    ROLE_CONDITION,
    ROLE_EXEC,
    ROLE_VALUE,
    compile_piece,
)
from engine.script.suggest import suggest
from engine.script.texttags import TaggedText, TagProblem, origin_of
from engine.script.texttags import parse as parse_tags
from engine.script.words import (
    ROLE_CHARACTER,
    ROLE_LABEL,
    ROLE_NAME,
    SHOW_MODIFIER_WORDS,
    STATEMENT_WORDS,
    canonical_name,
    check_name,
    is_name,
)

Place = tuple[ScriptFile, int]
_PLACES_KEPT = 4          # first use + SCRIPT_MESSAGE_LIST_ITEMS others (§7.10.1)


# --- Registry (§5.1) ---------------------------------------------------------------------

@dataclass(frozen=True)
class StatementSpec:
    """How one statement word is read. ``tail`` picks the scanner for the rest of the line
    (``"path"`` is F02's include path). ``misplaced`` is the code for a ``"top"`` statement
    inside a block (F03 ``04-technical.md`` §3.2; its args come from ``misplaced_args``).

    Fields after ``parse`` have defaults (F03 ``misplaced``, F07 ``block_parser``), so
    construct specs by keyword. ``block_parser`` (F07 C7) reads the statement's own block
    instead of the block parser's ``block_of``: a generator function called with the block
    parser (``BlockApi``), the statement, its node, its depth, whether it had an error of its
    own, and the enclosing block widths (``script/menu.py``'s ``parse_menu_body``).

    ``placement="either"`` (F22 contract change 1): at depth 0 the statement is a top-level
    statement (it ends a run of top-level story lines, like ``"top"``), in a block a story
    statement; its ``parse`` reads ``ctx.depth`` to tell which. It needs no ``misplaced``."""

    word: str
    placement: Literal["top", "story", "either"]
    takes_block: bool
    tail: Literal["script", "py_condition", "py_after_equals", "py_all", "path"]
    parse: Callable[[RawStatement, "ParseContext"], object | None]
    misplaced: str | None = None
    block_parser: Callable[..., Iterator[None]] | None = None


_REGISTRY: dict[str, StatementSpec] = {}


def register(spec: StatementSpec) -> None:
    """Add ``spec``. ``ValueError`` if its word is not reserved or already registered."""
    if spec.word not in STATEMENT_WORDS:
        raise ValueError(f"{spec.word!r} is not a reserved statement word")
    if spec.word in _REGISTRY:
        raise ValueError(f"{spec.word!r} is already registered")
    if spec.placement == "top" and spec.misplaced is None:
        raise ValueError(f"{spec.word!r} is a top-level statement without a misplaced code")
    _REGISTRY[spec.word] = spec


def get_spec(word: str) -> StatementSpec | None:
    return _REGISTRY.get(word)


# ADR-0010 rule 3: a statement word that is not reserved (F63 ``clock``, and later ``send``,
# ``open``…) is that statement only as the first word of its own line and only when
# ``claims(raw)`` says the line is written as the statement; otherwise the line stays what it
# was (dialogue by a character of that name). ``no_text`` (rule 4) words a line that starts
# with the word, has no quoted text, and isn't claimed: given the ``NoText`` and whether the
# game defines that name, it returns the ``Diagnostic`` (None: F02's E71/E30a/E30b).
@dataclass(frozen=True)
class PositionalWord:
    spec: StatementSpec
    claims: Callable[[RawStatement], bool]
    no_text: "Callable[[NoText, bool], Diagnostic | None] | None" = None


_POSITIONAL: dict[str, PositionalWord] = {}


def register_positional(word: PositionalWord) -> None:
    """Add a positional statement word (``ValueError`` if reserved or already added)."""
    name = word.spec.word
    if name in STATEMENT_WORDS or name in _POSITIONAL:
        raise ValueError(f"{name!r} is reserved or already a positional word")
    _POSITIONAL[name] = word


def spec_for(raw: RawStatement, word: str) -> StatementSpec | None:
    """The spec of the statement ``raw`` (whose first word is ``word``, "" for none) is: a
    reserved word's, else a positional word's when it claims the line, else None."""
    if not word:
        return None
    spec = _REGISTRY.get(word)
    if spec is None:
        positional = _POSITIONAL.get(word)
        if positional is not None and positional.claims(raw):
            return positional.spec
    return spec


def registered_words() -> frozenset[str]:
    return frozenset(_REGISTRY)


def tail_for(word: str) -> str:
    """The tail of a statement word (``script`` for dialogue and unregistered words)."""
    spec = _REGISTRY.get(word)
    return spec.tail if spec is not None else TAIL_SCRIPT


@contextmanager
def scoped_registry() -> Iterator[None]:
    """Test-only (I-6): registrations made inside the block are undone when it ends, F45's
    statement docs, F19's ``LOCK_TARGETS`` rows, and F14's ``ATTACH_SKIPS`` included (imported
    here, not at the top: F45 ``07`` I-5; F19 ``07`` I-5; F20 ``07`` A4)."""
    from engine.script import rollback, routes, statement_docs

    saved = dict(_REGISTRY)
    saved_positional = dict(_POSITIONAL)
    saved_docs = statement_docs._snapshot()
    saved_targets = dict(routes.LOCK_TARGETS)
    saved_skips = list(rollback.ATTACH_SKIPS)
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(saved)
        _POSITIONAL.clear()
        _POSITIONAL.update(saved_positional)
        statement_docs._restore(saved_docs)
        routes.LOCK_TARGETS.clear()
        routes.LOCK_TARGETS.update(saved_targets)
        rollback.ATTACH_SKIPS[:] = saved_skips


# --- What parsing collects for the whole-game checks (§7.6.2) ----------------------------

@dataclass(slots=True)
class Uses:
    """Where a name is used: the first few places in reading order and the total count."""

    places: list[Place] = field(default_factory=list)
    count: int = 0

    def add(self, place: Place) -> None:
        self.count += 1
        if len(self.places) < _PLACES_KEPT:
            self.places.append(place)


@dataclass(slots=True)
class NoText:
    """A dialogue-shaped line with no quoted text, decided after all defines are known
    (SR-F02-41 rows 3–5): E71, E30a, or E30b."""

    file: ScriptFile
    line: int
    word: str
    name: str
    line_text: str
    rest: str
    source_line: str


@dataclass(slots=True)
class Collected:
    label_defs: dict[str, list[Place]] = field(default_factory=dict)
    define_defs: dict[str, list[Place]] = field(default_factory=dict)
    default_defs: dict[str, list[Place]] = field(default_factory=dict)    # F03
    image_defs: dict[str, list[Place]] = field(default_factory=dict)      # F04 (E133)
    chapter_defs: dict[str, list[Place]] = field(default_factory=dict)    # F18 (E220, E224)
    meter_defs: dict[str, list[Place]] = field(default_factory=dict)      # F22 (E231, E235)
    soft_labels: dict[str, Place] = field(default_factory=dict)
    targets: dict[str, Uses] = field(default_factory=dict)
    # F05: each {var} name's first use (file, line, column of its "{"), for W42.
    var_uses: dict[str, tuple[ScriptFile, int, int]] = field(default_factory=dict)
    speakers: dict[str, Uses] = field(default_factory=dict)
    no_text: list[NoText] = field(default_factory=list)
    # F29 W185: (file, line, column of the "{", graphemes, largest strength) per long
    # outermost {glitch}, in reading order (04 §6.2).
    long_glitches: list[tuple[ScriptFile, int, int, int, str]] = field(default_factory=list)
    # F51 W257: each timed menu with no error, in parse order (``script/menu.py`` nodes).
    timed_menus: list = field(default_factory=list)
    # F59 E233: each choice check as (file, ChoiceCheck, source line), in parse order.
    choice_checks: list = field(default_factory=list)
    todos: list[tuple[ScriptFile, int, str]] = field(default_factory=list)
    todo_count: int = 0

    def add_todo(self, file: ScriptFile, line: int, text: str) -> None:
        self.todo_count += 1
        if len(self.todos) < SCRIPT_TODO_LOG_LIMIT:
            self.todos.append((file, line, text))


def resolve_no_text(item: NoText, defined_names: set[str] | dict) -> Diagnostic:
    """E71 if the name is defined, else E30a with a statement-word suggestion, else E30b.
    A positional word's ``no_text`` decides first (ADR-0010 rule 4)."""
    positional = _POSITIONAL.get(item.word)
    if positional is not None and positional.no_text is not None:
        diagnostic = positional.no_text(item, item.name in defined_names)
        if diagnostic is not None:
            return diagnostic
    if item.name in defined_names:
        code, args = "E71", (item.word, item.rest)
    else:
        suggestion = suggest(item.word, STATEMENT_WORDS)
        if suggestion is not None:
            code, args = "E30a", (item.word, suggestion)
        else:
            code, args = "E30b", (item.word, item.line_text)
    return Diagnostic(code, item.file, item.line, None, args, source_line=item.source_line,
                      stmt=item.line)


@dataclass
class ParseContext:
    """Shared state of one load's parsing."""

    sink: DiagnosticSink
    collected: Collected = field(default_factory=Collected)
    warnings: WarningLog = field(default_factory=WarningLog)
    collect_todos: bool = False
    compile_name: str = COMPILE_NAME     # the loader passes it under the real script folder
    # F04: the names ``at`` may use (E120), from ``LoadOptions.position_names``.
    position_names: frozenset[str] = frozenset(BUILTIN_POSITIONS)
    # F32: the names ``ui style`` may use (E320), from ``LoadOptions.style_names``; None skips.
    style_names: frozenset[str] | None = None
    statement_count: int = 0
    py_pieces: int = 0
    py_chars: int = 0
    # Per statement (set by the block parser):
    file: ScriptFile | None = None
    raw: RawStatement | None = None
    depth: int = 0
    uses: list[tuple[str, str, object]] = field(default_factory=list)

    def error(self, code: str, *args: object, line: int | None = None,
              column: int | None = None) -> None:
        assert self.raw is not None
        self.raw.error(code, tuple(args), line=line, column=column)

    def place(self) -> Place:
        assert self.raw is not None
        return (self.raw.file, self.raw.line)

    def compile(self, source: str, *, line: int, column: int, mode: str, role: str,
                lambdas: int, length: int, collect_names: bool = False,
                comment_free: str | None = None) -> tuple[PyCode, bool]:
        """Compile one piece. Returns the ``PyCode`` and whether it is a ``Character(...)``
        call. On a problem the error is pending and ``code`` is None."""
        assert self.file is not None
        result = compile_piece(source, mode=mode, role=role, filename=f"<{self.file.ref}>",
                               line=line, column=column, lambdas=lambdas, length=length,
                               collect_names=collect_names, compile_name=self.compile_name)
        self.py_pieces += 1
        self.py_chars += length
        for warn_line, text in result.warnings:
            self.warnings.add_w03(self.file, warn_line, text)
        if result.problem is not None:
            problem = result.problem
            self.error(problem.code, *problem.args, line=problem.line, column=problem.column)
        py = PyCode(source=source, line=line, column=column, mode=mode,  # type: ignore[arg-type]
                    code=result.code, names=result.names, comment_free=comment_free)
        return py, result.is_character_call

    def commit_uses(self) -> None:
        """Record the uses of a statement that had no error of its own."""
        collected = self.collected
        for kind, name, value in self.uses:
            if kind == "no_text":
                collected.no_text.append(value)  # type: ignore[arg-type]
                continue
            if kind == "var":
                collected.var_uses.setdefault(name, value)  # type: ignore[arg-type]
                continue
            if kind == "glitch":                                       # F29 W185
                collected.long_glitches.append(value)  # type: ignore[arg-type]
                continue
            table = collected.targets if kind == "target" else collected.speakers
            uses = table.get(name)
            if uses is None:
                uses = table[name] = Uses()
            uses.add(value)  # type: ignore[arg-type]
        self.uses.clear()


# --- Helpers ------------------------------------------------------------------------------

def _first_index(tokens: list[Token], kinds: tuple[str, ...]) -> int | None:
    for index, token in enumerate(tokens):
        if token.kind in kinds:
            return index
    return None


def _written(raw: RawStatement, tokens: list[Token]) -> str:
    """The source text covered by ``tokens`` (all on one line)."""
    first, last = tokens[0], tokens[-1]
    text = raw.texts.get(first.line, "")
    if last.line != first.line:
        return text[first.column - 1:].strip()
    end = last.column - 1 + (len(last.text) if last.kind in (NAME, SYMBOL) else 1)
    if last.kind == STRING:
        end = len(text)
    return text[first.column - 1:end].strip()


def _between(raw: RawStatement, start: Token, stop: Token | None) -> str:
    """Source text from ``start`` up to ``stop`` (exclusive) or the comment, stripped."""
    text = raw.texts.get(start.line, "")
    if stop is not None and stop.line == start.line:
        return text[start.column - 1:stop.column - 1].strip()
    return raw.rest_from(start.line, start.column)


def _after_text(raw: RawStatement, ctx: ParseContext, after: list[Token]) -> bool:
    """SR-F02-28, SR-F02-55: only a comment may follow the text. True if fine. A narration
    line whose text is followed by ``if`` was read with a Python tail (F07 C8): outside a
    menu it is E74 when it ends in ``:`` (a choice out of place, SR-F07-08), else E53."""
    if raw.py is not None:
        if raw.ends_with_colon:
            ctx.error("E74")
        else:
            first = after[0]
            ctx.error("E53", raw.rest_from(first.line, first.column), line=first.line,
                      column=first.column)
        return False
    if not after:
        return True
    if len(after) == 1 and after[0].kind in (COLON, FWCOLON):
        ctx.error("E74")
        return False
    first = after[0]
    ctx.error("E53", raw.rest_from(first.line, first.column), line=first.line,
              column=first.column)
    return False


def line_body(raw: RawStatement, ctx: ParseContext, token: Token, *,
              choice: bool = False, crash: bool = False) -> TaggedText | None:
    """The parsed tags of a line's text (F05 ``04-technical.md`` §6.2): a tag mistake is
    pending on the statement (one error per logical line) and gives None; each ``{var}`` is a
    use for W42. ``choice`` (F07 C9): a menu choice's text, where the timing tags are E175.
    F29: each long ``{glitch}`` is a use for W185 (``Collected.long_glitches``). ``crash``
    (F30): an ``effect crash`` message, where any tag but ``{var}`` and ``{username}`` is
    E301."""
    file = raw.file

    def report(problem: TagProblem) -> None:
        ctx.error(problem.code, *problem.args, line=problem.line, column=problem.column)

    def on_var(name: str, line: int, column: int) -> None:
        ctx.uses.append(("var", name, (file, line, column)))

    def on_glitch(count: int, strength: str, line: int, column: int) -> None:
        ctx.uses.append(("glitch", "", (file, line, column, count, strength)))

    return parse_tags(token.text, origin_of(token.origins, (token.line, token.column + 1)),
                      report, on_var=on_var, choice=choice, on_glitch=on_glitch,
                      crash=crash)


# --- Built-in story lines ----------------------------------------------------------------

def parse_narration(raw: RawStatement, ctx: ParseContext) -> Say | None:
    tokens = raw.tokens
    text = tokens[0]
    ok = _after_text(raw, ctx, tokens[1:])
    if not ok or text.unclosed:
        return None
    body = line_body(raw, ctx, text)
    if body is None:
        return None
    return Say(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
               speaker=None, attributes=(), text=text.text, body=body)


def parse_dialogue(raw: RawStatement, ctx: ParseContext) -> Say | None:
    """``speaker { attribute } "text"`` (SR-F02-41)."""
    tokens = raw.tokens
    word = raw.word
    if word.lower() in STATEMENT_WORDS:
        ctx.error("E31", word)
        return None
    index = 1
    while index < len(tokens) and tokens[index].kind == NAME:
        index += 1
    words = tokens[1:index]
    following = tokens[index] if index < len(tokens) else None
    if following is not None and following.kind == CURLY:
        ctx.error("E50", following.text, line=following.line, column=following.column)
        return None
    if following is not None and following.kind == SQUOTE:
        ctx.error("E51", line=following.line, column=following.column)
        return None
    if _first_index(tokens, (STRING,)) is None:
        line_text = raw.rest_from(raw.line, raw.column)
        rest = raw.rest_after(tokens[0])
        ctx.uses.append(("no_text", "", NoText(raw.file, raw.line, word, canonical_name(word),
                                               line_text, rest,
                                               raw.texts.get(raw.line, ""))))
        return None
    assert following is not None
    text_at = _first_index(tokens, (STRING,))
    for token in tokens[1:text_at]:
        if token.kind == NAME and token.text in SHOW_MODIFIER_WORDS:
            # F04 E119 (row 5b of SR-F02-41), before E72, E73, and E70. The speaker's image
            # tag is filled in by the whole-game checks when they can tell it (checks.py).
            ctx.error("E119", token.text, _between(raw, token, tokens[text_at]), None,
                      canonical_name(word))
            return None
    if following.kind != STRING:
        ctx.error("E72", raw.chunk_at(following), word, line=following.line,
                  column=following.column)
        return None
    if len(words) > SCRIPT_MAX_ATTRIBUTES:
        ctx.error("E73", len(words), word)
        return None
    if not _after_text(raw, ctx, tokens[index + 1:]) or following.unclosed:
        return None
    body = line_body(raw, ctx, following)
    if body is None:
        return None
    speaker = canonical_name(word)
    ctx.uses.append(("speaker", speaker, ctx.place()))
    return Say(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
               speaker=speaker, attributes=tuple(canonical_name(t.text) for t in words),
               text=following.text, body=body)


def parse_python_line(raw: RawStatement, ctx: ParseContext) -> PythonLine | None:
    span = raw.py
    assert span is not None
    if not span.truncated and not span.source.strip():
        ctx.error("E84")
        return None
    source = span.source
    py, _ = ctx.compile(source, line=span.line, column=span.column, mode="exec",
                        role=ROLE_EXEC, lambdas=span.lambdas, length=span.length,
                        comment_free=None if span.truncated else span.without_comments())
    if py.code is None:
        return None
    return PythonLine(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                      py=py)


# --- F02 statements -----------------------------------------------------------------------

def label_name_written(raw: RawStatement) -> str:
    """The label name as written (for E24), or "" when there is none."""
    tokens = raw.tokens[1:]
    stop = _first_index(tokens, (COLON, FWCOLON))
    before = tokens if stop is None else tokens[:stop]
    return _written(raw, before) if before else ""


def parse_label(raw: RawStatement, ctx: ParseContext) -> Label | None:
    tokens = raw.tokens[1:]
    colon = _first_index(tokens, (COLON, FWCOLON))
    before = tokens if colon is None else tokens[:colon]
    after = [] if colon is None else tokens[colon + 1:]
    name: str | None = None
    if not before:
        ctx.error("E20")
    elif any(t.kind == SYMBOL and t.text == "(" for t in before):
        start = next(t for t in before if t.kind == SYMBOL and t.text == "(")
        ctx.error("E23", _between(raw, start, tokens[colon] if colon is not None else None))
    elif len(before) > 1 and all(t.kind == NAME for t in before):
        ctx.error("E23b")
    else:
        written = _written(raw, before)
        problem = check_name(written, ROLE_LABEL) if len(before) == 1 and \
            before[0].kind == NAME else ("E64", (written,))
        if problem is not None:
            ctx.error(problem[0], *problem[1])
        else:
            name = canonical_name(written)
            if colon is None:
                ctx.error("E21", written, False)
            elif tokens[colon].kind == FWCOLON:
                ctx.error("E21", written, True)
    if after:
        ctx.error("E22")
    if name is None:
        return None
    ctx.collected.label_defs.setdefault(name, []).append(ctx.place())
    return Label(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                 name=name)


def _parse_target(raw: RawStatement, ctx: ParseContext, node_type: type) -> Node | None:
    keyword = raw.word
    tokens = raw.tokens[1:]
    if not tokens or tokens[0].kind not in (NAME, STRING):
        ctx.error("E41", keyword)
        return None
    first = tokens[0]
    if first.kind == STRING:
        ctx.error("E41b", keyword, first.text)
        return None
    if not is_name(first.text):
        ctx.error("E64", first.text)
        return None
    rest = tokens[1:]
    if rest:
        if len(rest) == 1 and rest[0].kind == COLON:
            ctx.error("E42", keyword, ":")
        else:
            ctx.error("E42", keyword, raw.rest_after(first))
        return None
    target = canonical_name(first.text)
    ctx.uses.append(("target", target, ctx.place()))
    return node_type(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                     target=target)


def parse_jump(raw: RawStatement, ctx: ParseContext) -> Jump | None:
    return _parse_target(raw, ctx, Jump)  # type: ignore[return-value]


def parse_call(raw: RawStatement, ctx: ParseContext) -> Call | None:
    return _parse_target(raw, ctx, Call)  # type: ignore[return-value]


def parse_return(raw: RawStatement, ctx: ParseContext) -> Return | None:
    if len(raw.tokens) > 1:
        ctx.error("E44", raw.rest_after(raw.tokens[0]))
        return None
    return Return(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column)


def condition_of(raw: RawStatement, ctx: ParseContext, keyword: str | None = None
                 ) -> PyCode | None:
    """The condition of ``if``/``elif`` up to the last top-level ``:`` (SR-F02-61).
    ``keyword`` names the statement in messages (default: the line's word; F07: ``"if"`` for
    a menu choice's ``"text" if condition:``)."""
    keyword = raw.word if keyword is None else keyword
    span = raw.py
    assert span is not None
    if span.colon is None:
        condition = span.source.strip() if not span.truncated else "…"
        if not condition:
            ctx.error("E39", keyword)
        else:
            ctx.error("E31b", keyword, condition)
        return None
    colon_index, colon_at = span.colon
    lines = [span_line(span, raw, i) for i in range(colon_index)]
    lines.append(span_line(span, raw, colon_index)[:colon_at].rstrip())
    source = "\n".join(lines)
    if not source.strip():
        ctx.error("E39", keyword)
        return None
    if raw.py_after:
        ctx.error("E22")
        return None
    length = len(source) if not span.truncated else span.length
    py, _ = ctx.compile(source, line=span.line, column=span.column, mode="eval",
                        role=ROLE_CONDITION, lambdas=span.lambdas, length=length)
    return py if py.code is not None else None


_condition = condition_of


def parse_if(raw: RawStatement, ctx: ParseContext) -> If | None:
    condition = _condition(raw, ctx)
    branch = IfBranch(keyword="if", condition=condition, line=raw.line, column=raw.column)
    return If(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
              branches=(branch,))


def parse_elif(raw: RawStatement, ctx: ParseContext) -> IfBranch:
    condition = _condition(raw, ctx)
    return IfBranch(keyword="elif", condition=condition, line=raw.line, column=raw.column)


def parse_else(raw: RawStatement, ctx: ParseContext) -> IfBranch:
    tokens = raw.tokens[1:]
    colon = _first_index(tokens, (COLON,))
    before = tokens if colon is None else tokens[:colon]
    if before:
        if before[0].kind == NAME and before[0].text == "if":
            ctx.error("E38b")
        else:
            ctx.error("E38", _between(raw, before[0], tokens[colon] if colon is not None
                                      else None))
    elif colon is None:
        ctx.error("E31b", "else", "")
    elif tokens[colon + 1:]:
        ctx.error("E22")
    return IfBranch(keyword="else", condition=None, line=raw.line, column=raw.column)


def assignment_target(raw: RawStatement) -> tuple[str | None, str | None, bool]:
    """The target of a ``word name = value`` line (``define``, F03 ``default``): the name as
    written (one NAME before ``=``) or None; the dotted name as written (``a.b``, E49's
    variant) or None; and whether the line has an ``=``."""
    tokens = raw.tokens[1:]
    equals = _first_index(tokens, (EQUALS,))
    before = tokens if equals is None else tokens[:equals]
    if len(before) == 1 and before[0].kind == NAME:
        return before[0].text, None, equals is not None
    if (len(before) >= 3 and len(before) % 2 == 1
            and all(t.kind == NAME if i % 2 == 0 else (t.kind == SYMBOL and t.text == ".")
                    for i, t in enumerate(before))):
        return None, _written(raw, before), equals is not None
    return None, None, equals is not None


def misplaced_args(raw: RawStatement, spec: StatementSpec) -> tuple:
    """The args of ``spec.misplaced``: the label name (E24); for a ``name = value`` line the
    line's own assignment as one string, ``"trust = 0"``, or None when it has none (E46,
    F03 E46b); else nothing (E90)."""
    if spec.word == "label":
        return (label_name_written(raw),)
    if spec.tail != TAIL_AFTER_EQUALS:
        return ()
    written, dotted, has_equals = assignment_target(raw)
    name = written if written is not None else dotted
    span = raw.py
    if name is None or not has_equals or span is None or span.truncated:
        return (None,)
    value = " ".join(part.strip() for part in span.without_comments().split("\n")
                     if part.strip())
    return (f"{name} = {value}" if value else None,)


def parse_define(raw: RawStatement, ctx: ParseContext) -> Define | None:
    written, dotted, equals = assignment_target(raw)
    if dotted is not None:
        ctx.error("E49", dotted)
        return None
    span = raw.py
    if written is None or not equals or span is None or \
            (not span.truncated and not span.source.strip()):
        ctx.error("E49", None)
        if written is not None and check_name(written) is None:
            name = canonical_name(written)
            ctx.collected.define_defs.setdefault(name, []).append(ctx.place())
        return None
    value, is_character = ctx.compile(span.source, line=span.line, column=span.column,
                                      mode="eval", role=ROLE_VALUE, lambdas=span.lambdas,
                                      length=span.length, collect_names=True)
    problem = check_name(written, ROLE_CHARACTER if is_character else ROLE_NAME)
    if problem is not None:
        ctx.error(problem[0], *problem[1])
        return None
    name = canonical_name(written)
    ctx.collected.define_defs.setdefault(name, []).append(ctx.place())
    if value.code is None:
        return None
    return Define(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                  name=name, value=value)


def parse_include(raw: RawStatement, ctx: ParseContext) -> Include | None:
    tokens = raw.tokens[1:]
    if not tokens or tokens[0].kind != PATH or tokens[0].unclosed:
        written = raw.rest_after(raw.tokens[0]).strip('"') or "chapter2.vns"
        ctx.error("E95", written)
        return None
    if len(tokens) > 1:
        extra = tokens[1]
        ctx.error("E96", line=extra.line, column=extra.column)
        return None
    return Include(file=raw.file, line=raw.line, end_line=raw.end_line, column=raw.column,
                   path=tokens[0].text)


# F02's statements (04-technical.md §6.1).
for _spec in (
    StatementSpec("label", "top", True, TAIL_SCRIPT, parse_label, misplaced="E24"),
    StatementSpec("define", "top", False, TAIL_AFTER_EQUALS, parse_define, misplaced="E46"),
    StatementSpec("include", "top", False, TAIL_PATH, parse_include, misplaced="E90"),
    StatementSpec("jump", "story", False, TAIL_SCRIPT, parse_jump),
    StatementSpec("call", "story", False, TAIL_SCRIPT, parse_call),
    StatementSpec("return", "story", False, TAIL_SCRIPT, parse_return),
    StatementSpec("if", "story", True, TAIL_CONDITION, parse_if),
    StatementSpec("elif", "story", True, TAIL_CONDITION, parse_elif),
    StatementSpec("else", "story", True, TAIL_SCRIPT, parse_else),
):
    register(_spec)
del _spec

__all__ = [
    "Collected", "NoText", "ParseContext", "StatementSpec", "TAIL_PY_ALL", "Uses",
    "assignment_target", "condition_of", "get_spec", "line_body", "misplaced_args", "register",
    "registered_words", "register_positional", "PositionalWord", "spec_for",
    "resolve_no_text", "scoped_registry", "tail_for",
]
