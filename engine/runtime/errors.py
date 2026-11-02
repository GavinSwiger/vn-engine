"""Run-time and launch errors of the story (F03 ``04-technical.md`` §7.11; texts ``02`` §5.2,
§5.3, held in ``engine/script/messages.py``, the one catalogue).

Why this module exists: every author failure, whatever Python raised, ends as one
``StoryError`` with a plain message naming the file and line (PR-F03-20), and one log record
with the script frames instead of a Python traceback (TR-F03-09). The interpreter and the
launch phase call ``map_exception``; nothing else builds a run-time message.

How a failure is read (§7.11):
- **Line.** The traceback is walked with an ``id(code) → owner`` map. The outermost frame
  that belongs to the running piece gives ``py.line + tb_lineno − 1`` (SR-F03-29); the
  innermost frame that belongs to a define gives SR-F03-34's ``(in define …)`` suffix.
- **Code.** The first matching row of the classification table (SR-F03-32).
- **Trace.** One line per frame: ``script/a.vns, line 9 (label start)``, ``in define bonus,
  script/main.vns, line 7``, ``in Python module json``; the engine's own frames are left
  out, repeats are folded, and the exception's class name comes last.

No file is opened and ``linecache`` is never used (SEC-F02-01): source lines come from
``PyCode.source``. Everything author-made (``str(e)``, ``dir(obj)``) is read under the guard.
The launch rules that need an AST (E75e second form, E75g, E85l second form) are
``launch.py``'s.

F12 (step 3a): the store's refusals map first, E180 before E85c (``PersistentNoValue`` is
an ``AttributeError``): E180 (no value; did-you-mean over defaults and stored names), E181
(a value persistent data can't hold), E182 (engine names), E183 (over a cap), E185 (a
define read ``persistent``). F03's E85h is retired. A persistent default
(``PersistentDefault``) fails with the prefix ``default persistent.<name> couldn't be set: ``.
F19: E245 after E180, for a set or delete of an engine view (``persistent.endings``,
``routes``) that the load check can't see (a computed ``setattr``/``delattr``).
"""

import ast
import builtins
import logging
import re
from collections.abc import Iterable, Mapping
from types import CodeType, FrameType, ModuleType, TracebackType
from typing import Self

from engine.core.constants import VALUE_ECHO_MAX_CHARS
from engine.core.redact import echo
from engine.runtime.dice import DICE_CALLS, DiceArgumentError, DiceFacade
from engine.runtime.guard import NO_GUARD, AuthorCodeGuard
from engine.runtime.persistent import (PersistentEngineName, PersistentError,
                                       PersistentInDefine, PersistentNoValue, PersistentTooBig,
                                       PersistentUnsaveable, PersistentViewName)
from engine.runtime.values import KEY, KIND, TOO_DEEP, Unsaveable, kind_words
from engine.script.diagnostics import ScriptError
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.messages import format_message
from engine.script.nodes import (Call, Default, Define, If, Jump, Node, PersistentDefault,
                                 PyCode, PythonLine, Return, Say)
from engine.script.points import PointsChange
from engine.script.suggest import suggest
from engine.script.words import ENGINE_NAMES

TRACE_HEAD = "Traceback (script frames):"
E185_VALUE_MAX_CHARS = 80              # F12: E185's "e.g. define x = lambda: …"


class StoryError(ScriptError):
    """A run-time or launch error (SR-F02-67 shape, no column). ``trace`` is for the log
    only: ``Traceback (script frames):``, one line per frame, and the exception's class name
    (never a raw Python traceback). ``logged`` is set once its log record is written, so the
    error screen doesn't log it a second time."""

    def __init__(self, message: str, *, code: str, file: str | None = None,
                 line: int | None = None, source_line: str | None = None,
                 trace: tuple[str, ...] = ()) -> None:
        super().__init__(message, code=code, file=file, line=line, source_line=source_line)
        self.trace = trace
        self.logged = False


class AuthorRefusal(Exception):
    """An engine object refused what author code asked (``Character`` options, ``module``).
    ``code`` and ``message`` are final; ``prefixed`` says whether the SR-F03-31 prefix
    (``define X couldn't be set: ``) goes before the message at launch."""

    prefixed = True

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @classmethod
    def of(cls, code: str, *args: object) -> Self:
        """The refusal ``code`` with its catalogue text (``messages.format_message``)."""
        return cls(code, format_message(code, args))


class ConsoleUnavailable(Exception):
    """``input``, ``breakpoint``, or ``help`` was called (E85n)."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name}() needs a console")
        self.name = name


# --- Where -------------------------------------------------------------------------------

def where(node: Node, line: int | None = None) -> dict[str, object]:
    """``file``/``line``/``source_line`` keyword arguments for an error at ``node``.

    A define's error (launch) carries its source line too: ``04`` §7.6 reports launch
    errors "as F02 §7.10.1" in one ``ScriptErrorGroup``, so each is logged and shown like a
    load error, with the redacted line under its message (F02 §7.10.2)."""
    line = node.line if line is None else line
    return {"file": node.file.ref, "line": line, "source_line": statement_source(node, line)}


def _pieces(node: Node) -> list[PyCode]:
    if isinstance(node, PythonLine):
        return [node.py]
    if isinstance(node, If):
        return [b.condition for b in node.branches if b.condition is not None]
    if isinstance(node, Menu):                              # F07: its choices' conditions
        return [c.condition for c in node.choices if c.condition is not None]
    if isinstance(node, (Define, Default, PersistentDefault)):
        return [node.value]
    if isinstance(node, PointsChange):                      # F22: the amount
        return [node.amount]
    if isinstance(node, Minigame):                          # F23: its argument values
        return [arg.value for arg in node.args]
    return []


Owner = tuple[Node, PyCode]


def _owners(nodes: Iterable[Node], skip: Node | None = None) -> dict[int, Owner]:
    """``id(code) → (node, piece)`` for every code object of the nodes' Python, nested ones
    (lambdas, functions, comprehensions) included."""
    out: dict[int, Owner] = {}
    for node in nodes:
        if node is skip:
            continue
        for piece in _pieces(node):
            stack = [piece.code] if piece.code is not None else []
            while stack:
                code = stack.pop()
                out[id(code)] = (node, piece)
                stack.extend(c for c in code.co_consts if isinstance(c, CodeType))
    return out


def _frames(e: BaseException) -> list[tuple[FrameType, int]]:
    """The traceback's frames, outermost first, with their line numbers."""
    out = []
    tb: TracebackType | None = e.__traceback__
    while tb is not None:
        out.append((tb.tb_frame, max(tb.tb_lineno or 1, 1)))
        tb = tb.tb_next
    return out


def error_line(e: BaseException, node: Node) -> int:
    """The script line of the outermost traceback frame that belongs to ``node``'s
    Python; ``node.line`` when no frame does (§7.11 line mapping)."""
    owners = _owners([node])
    for frame, lineno in _frames(e):
        found = owners.get(id(frame.f_code))
        if found is not None:
            return found[1].line + lineno - 1
    return node.line


def _code_line(piece: PyCode, line: int) -> str | None:
    lines = piece.source.split("\n")
    k = line - piece.line
    return lines[k] if 0 <= k < len(lines) else None


def statement_source(node: Node, line: int | None = None) -> str | None:
    """The script text of ``line`` (default: the node's first line), rebuilt from the
    program (no file is read): ``$ x = 1``, ``if trust > 1:``, ``default luck = 1 / 0``,
    a continuation line as written, ``hana "Hi."``. None when unknown."""
    line = node.line if line is None else line
    if isinstance(node, Say):
        if line != node.line:
            return None
        text = node.text.replace("\\", "\\\\").replace('"', '\\"')
        words = " ".join(w for w in (node.speaker, *node.attributes) if w)
        return f'{words} "{text}"' if words else f'"{text}"'
    if isinstance(node, Jump):
        return f"jump {node.target}"
    if isinstance(node, Call):
        return f"call {node.target}"
    if isinstance(node, Return):
        return "return"
    if isinstance(node, If):
        for branch in node.branches:
            piece = branch.condition
            if piece is None:
                continue
            text = _code_line(piece, line)
            if text is not None:
                return f"{branch.keyword} {text}:" if line == piece.line else text.strip()
        return None
    if isinstance(node, Minigame):                          # F23: the line, rebuilt
        return _minigame_source(node, line)
    if isinstance(node, Menu):                              # F07: menu:, a choice line
        if line == node.line:
            return "menu:"
        for choice in node.choices:
            piece = choice.condition
            quoted = '"' + choice.text.replace("\\", "\\\\").replace('"', '\\"') + '"'
            if line == choice.line:
                if piece is None:
                    return f"{quoted}:"
                text = _code_line(piece, line)
                return f"{quoted} if {text}:" if text is not None else None
            if piece is not None:
                text = _code_line(piece, line)
                if text is not None:
                    return text.strip()
        return None
    for piece in _pieces(node):
        text = _code_line(piece, line)
        if text is None:
            return None
        if line != piece.line:
            return text.strip()
        if isinstance(node, PythonLine):
            return f"$ {text}"
        if isinstance(node, PointsChange):                  # F22
            return f"points {node.name} {node.op} {text}"
        return f"{_declared(node)} = {text}"
    return None


def _minigame_source(node: Minigame, line: int) -> str | None:
    """F23: ``minigame <name> [skippable] <arg>=<value> … [into <target>]`` (the arguments'
    first lines), or a continuation line of an argument's value as written."""
    if line == node.line:
        words = ["minigame", node.name] + (["skippable"] if node.skippable else [])
        words += [f"{arg.name}={arg.value.source.split(chr(10))[0]}" for arg in node.args
                  if arg.line == node.line]
        if node.target is not None and all(arg.line == node.line
                                           and "\n" not in arg.value.source
                                           for arg in node.args):
            words += ["into", node.target]
        return " ".join(words)
    for arg in node.args:
        text = _code_line(arg.value, line)
        if text is not None:
            return text.strip()
    return None


# --- Python's own text (SR-F03-32, G8) -----------------------------------------------------

_EXCEPTION_NAMES = frozenset(
    name for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException))
_TYPE_NAMES = frozenset(
    name for name, value in vars(builtins).items()
    if isinstance(value, type) and not issubclass(value, BaseException)) | {
    "NoneType", "function", "builtin_function_or_method", "method", "module", "code",
    "generator", "coroutine", "cell", "frame", "traceback", "ellipsis"}
_BANNED_CASED = re.compile(r"\b(INDENT|DEDENT|EOF|AST)\b")
_BANNED_ANY = re.compile(r"\b(tokens?|parse|parsed|parser|parsing|nodes?|lexer)\b", re.I)
_TYPE_IN_QUOTES = re.compile(r"""['"](\w+)['"]|\b(\w+)\(\)""")
_SINGLE_QUOTED = re.compile(r"(?<!\w)'([^'\n]*)'(?!\w)")


def python_text_allowed(text: str) -> bool:
    """SR-F03-32: Python's message may be quoted only if it holds no PR-F02-31 banned term,
    no exception class name, and no Python type name in Python's quoted form (G8: ``'list'``,
    ``"NoneType"``; a type called as ``int()`` counts too, so ``int("abc")``'s text is left
    out as AC-F03-45 requires). Plain words like ``list index out of range`` pass."""
    if _BANNED_CASED.search(text) or _BANNED_ANY.search(text):
        return False
    if set(re.findall(r"\w+", text)) & _EXCEPTION_NAMES:
        return False
    for quoted, called in _TYPE_IN_QUOTES.findall(text):
        if (quoted or called) in _TYPE_NAMES:
            return False
    return True


def _python_text(e: BaseException, guard: AuthorCodeGuard) -> str | None:
    """Python's own text for E85, ``'…'`` turned into ``"…"``, or None (SR-F03-32)."""
    try:
        guard.enter()
        try:
            text = str(e)
        finally:
            guard.exit()
    except Exception:
        return None
    if type(text) is not str:
        return None
    text = text.strip()
    if not text or not python_text_allowed(text):
        return None
    return echo(_SINGLE_QUOTED.sub(r'"\1"', text))


def short_value(v: object) -> str:
    """``repr`` of a plain value cut to 40 characters, for messages."""
    try:
        text = repr(v)
    except Exception:
        return "?"
    return echo(text, VALUE_ECHO_MAX_CHARS)


# --- E85c, E85d, E85e, E85f, E85j helpers ---------------------------------------------------

_TYPE_WORDS = {
    "str": "text", "int": "a whole number", "float": "a decimal number",
    "bool": "True or False", "NoneType": "nothing (None)", "list": "a list",
    "dict": "a dictionary", "tuple": "a tuple", "set": "a set", "frozenset": "a set",
    "function": "a function", "builtin_function_or_method": "a function",
    "method": "a function", "module": "a module", "Character": "a character",
    "dice": "the dice",
}


def type_words(name: str) -> str:
    """SR-F03-33's words for a type known only by its name (from CPython's message)."""
    return _TYPE_WORDS.get(name) or f"a Python object ({echo(name, VALUE_ECHO_MAX_CHARS)})"


# CPython's three TypeError templates (§7.11), pinned per minor version by
# tests/runtime/test_errors.py.
_CONCAT_RE = re.compile(r'^can only concatenate (\w+) \(not "(\w+)"\) to \w+$')
_OPERAND_RE = re.compile(r"^unsupported operand type\(s\) for (.+?): '(\w+)' and '(\w+)'$")
_COMPARE_RE = re.compile(r"^'(.+?)' not supported between instances of '(\w+)' and '(\w+)'$")


def mixed_kinds(text: str) -> tuple[str, str, str, str] | None:
    """``(form, left, right, op)`` for E85d when ``text`` is one of CPython's three mixed-type
    messages, else None."""
    match = _CONCAT_RE.match(text)
    if match:
        return "add", type_words(match[1]), type_words(match[2]), "+"
    match = _OPERAND_RE.match(text)
    if match:
        op = match[1].removesuffix(" or pow()")
        op = op[:-1] if op.endswith("=") and op not in ("==", "!=", "<=", ">=") else op
        form = "add" if op == "+" else "operator"
        return form, type_words(match[2]), type_words(match[3]), op
    match = _COMPARE_RE.match(text)
    if match:
        return "compare", type_words(match[2]), type_words(match[3]), match[1]
    return None


def _public_names(obj: object, guard: AuthorCodeGuard) -> list[str]:
    """The public ``dir()`` names of ``obj``, read under the guard (E85c candidates)."""
    try:
        guard.enter()
        try:
            names = dir(obj)
        finally:
            guard.exit()
    except Exception:
        return []
    return [n for n in names if type(n) is str and not n.startswith("_")]


def _e85c(e: AttributeError, guard: AuthorCodeGuard, suffix: str) -> str:
    from engine.runtime.character import Character    # character.py imports this module
    name, obj = e.name, e.obj
    if isinstance(obj, DiceFacade):
        return format_message("E85c", ("dice", name, suggest(name, DICE_CALLS), True, suffix))
    if isinstance(obj, ModuleType):
        modname = getattr(obj, "__name__", None)
        owner = f"the module {echo(modname)}" if type(modname) is str else "this module"
    elif isinstance(obj, Character):
        owner = echo(obj.define_name) if obj.define_name else "this character"
    else:
        owner = kind_words(obj)
    found = suggest(name, _public_names(obj, guard))
    return format_message("E85c", (owner, name, found, False, suffix))


_EXIT_RE = re.compile(r"((?:[A-Za-z_]\w*\s*\.\s*)*(?:exit|quit))\s*\(")


def _exit_call(at: tuple[PyCode, int] | None) -> str:
    """E85f: the call as written (``sys.exit()``, ``exit()``, ``quit()``)."""
    if at is None:
        return "exit()"
    piece, line = at
    for text in (_code_line(piece, line) or "", piece.source):
        match = _EXIT_RE.search(text)
        if match:
            return re.sub(r"\s+", "", match[1]) + "()"
    return "exit()"


def _call_argument(at: tuple[PyCode, int] | None, call: str) -> str | None:
    """The one argument of ``dice.<call>(…)`` as written in the piece, when it is the only
    such call there and at most 40 characters on one line (E85j's example)."""
    if at is None:
        return None
    piece = at[0]
    try:
        tree = ast.parse(piece.source, mode=piece.mode)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == call and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "dice" and len(node.args) == 1):
            found.add(ast.get_source_segment(piece.source, node.args[0]))
    if len(found) != 1:
        return None
    text = found.pop()
    if not text or "\n" in text or len(text) > VALUE_ECHO_MAX_CHARS:
        return None
    return text


def _e85j(e: DiceArgumentError, at: tuple[PyCode, int] | None, suffix: str) -> str:
    call, form, value = e.call, e.form, e.value
    if form == "order":
        lo, hi = value
        return format_message("E85j", (call, form, "", "", 0, (short_value(lo), short_value(hi)),
                                       None, suffix))
    if form == "whole":
        shown = short_value(value) if value is None or type(value) in (bool, float) else ""
        return format_message("E85j", (call, form, kind_words(value), shown, 0, ("", ""),
                                       None, suffix))
    if form == "empty":
        return format_message("E85j", (call, form, "", "", 0, ("", ""),
                                       _call_argument(at, call), suffix))
    if form == "list":
        return format_message("E85j", (call, form, kind_words(value), "", 0, ("", ""), None,
                                       suffix))
    return format_message("E85j", (call, "count", "", "", e.got, ("", ""), None, suffix))


def unsaveable_message(name: str, exc: Unsaveable) -> str:
    """E85e (``02`` §5.3; no ``(set at …)`` clause, I-14). The subject is the variable in
    quotes, or the path to the value inside it (``inventory["bag"][2]``), unquoted."""
    path = None
    if exc.reason != TOO_DEEP and exc.path:
        path = exc.path_text(name)
    detail = ""
    if exc.reason == KIND and isinstance(exc.value, ModuleType):
        modname = getattr(exc.value, "__name__", None)
        detail = modname if type(modname) is str else ""
    elif exc.reason == KEY:
        key = exc.value
        if key is None or type(key) in (bool, int, float):
            detail = short_value(key)
    kind = kind_words(exc.value) if exc.reason == KIND else ""
    return format_message("E85e", (exc.reason, name, path, kind, detail))


# --- E85b: names and the $ lines that set them ----------------------------------------------

def _binding_targets(tree: ast.AST) -> Iterable[tuple[ast.AST, ast.AST | None]]:
    """``(target Name, assigned value or None)`` for every story-level binding in a ``$``
    line: assignment targets, ``for`` targets, ``:=`` (also inside comprehensions),
    ``def``/``class`` names. Comprehension variables and lambda parameters are local."""
    stack: list[tuple[ast.AST, bool]] = [(tree, True)]
    while stack:
        node, story_level = stack.pop()
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            yield node.target, node.value
        if story_level:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    plain = isinstance(target, ast.Name)
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                            yield sub, node.value if plain else None
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                if isinstance(node.target, ast.Name):
                    yield node.target, (node.value if isinstance(node, ast.AnnAssign) else None)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.With)):
                targets = ([node.target] if isinstance(node, (ast.For, ast.AsyncFor))
                           else [i.optional_vars for i in node.items if i.optional_vars])
                for target in targets:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                            yield sub, None
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield node, None
        inner = story_level and not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ListComp,
                   ast.SetComp, ast.DictComp, ast.GeneratorExp))
        stack.extend((child, inner) for child in reversed(list(ast.iter_child_nodes(node))))


def _target_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return getattr(node, "name", None)


def first_setting_line(program: object, name: str, *,
                       skip: object = None) -> tuple[PythonLine, int, str] | None:
    """The first ``$`` line in reading order that sets ``name`` (its ``co_names`` hold the
    name, confirmed by the AST): ``(statement, line, value as written or "0")`` (E85b's
    second form). ``skip`` is the statement that failed: ``$ trsut += 1`` reads the name it
    sets, so it is no "line that hasn't run" for its own error (01 Priya step 4)."""
    labels = getattr(program, "labels", None)
    if labels is None:
        return None
    for label in labels:
        for stmt in program.statements_in(label):  # type: ignore[attr-defined]
            if not isinstance(stmt, PythonLine) or stmt is skip:
                continue
            py = stmt.py
            if py.code is None or name not in py.code.co_names:
                continue
            try:
                tree = ast.parse(py.source, mode="exec")
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                continue
            for target, value in _binding_targets(tree):
                if _target_name(target) != name:
                    continue
                written = "0"
                if value is not None:
                    segment = ast.get_source_segment(py.source, value)
                    if segment and "\n" not in segment:
                        written = segment if len(segment) <= VALUE_ECHO_MAX_CHARS else "…"
                return stmt, py.line + getattr(target, "lineno", 1) - 1, written
    return None


def _builtin_candidates() -> set[str]:
    return {n for n in dir(builtins) if not n.startswith("_") and n not in _EXCEPTION_NAMES}


def _e85b(name: str, names: Iterable[str], program: object | None, suffix: str,
          node: Node | None = None) -> str:
    if program is not None:
        found = first_setting_line(program, name, skip=node)
        if found is not None:
            stmt, line, value = found
            return format_message("E85b", (name, None, (stmt.file.ref, line), value, suffix))
    pool = {n for n in names if type(n) is str and not n.startswith("_")}
    pool |= set(ENGINE_NAMES) | _builtin_candidates()
    pool |= set(getattr(program, "default_names", ())) | set(getattr(program, "define_names", ()))
    pool.discard(name)
    return format_message("E85b", (name, suggest(name, pool), None, "0", suffix))


# --- Subject words and the trace ------------------------------------------------------------

def _subject(node: Node, piece: PyCode | None = None) -> str:
    """SR-F03-30's role words; G10 (drafted): "this value" for a define or default. F23:
    "the argument <name>" for a minigame argument's value (``piece``, the running one)."""
    if isinstance(node, Minigame):
        for arg in node.args:
            if arg.value is piece:
                return f"the argument {arg.name}"
        return "this Python"
    if isinstance(node, (If, Menu)):                        # F07: a choice's condition
        return "this condition"
    if isinstance(node, (Define, Default, PersistentDefault)):
        return "this value"
    return "this Python"


def _declared(node: Node) -> str:
    """``define x``, ``default x``, or (F12) ``default persistent.x``."""
    if isinstance(node, PersistentDefault):
        return f"default persistent.{node.name}"
    word = "default" if isinstance(node, Default) else "define"
    return f"{word} {node.name}"  # type: ignore[attr-defined]


def _role(node: Node) -> str:
    if isinstance(node, (Define, Default, PersistentDefault)):
        return _declared(node)
    label = getattr(node, "label", "")
    return f"label {label}" if label else "story"


def _is_engine_frame(frame: FrameType) -> bool:
    module = frame.f_globals.get("__name__") if isinstance(frame.f_globals, dict) else None
    return type(module) is str and (module == "engine" or module.startswith("engine."))


def _fold(lines: list[str]) -> list[str]:
    """Consecutive repeats of one frame line become one line and a count."""
    out: list[str] = []
    k = 0
    while k < len(lines):
        j = k
        while j + 1 < len(lines) and lines[j + 1] == lines[k]:
            j += 1
        out.append(lines[k])
        if j > k:
            out.append(f"  (the line above repeats {j - k:,} more times)")
        k = j + 1
    return out


def _trace(e: BaseException, frames: list[tuple[FrameType, int]], node: Node,
           running: Mapping[int, Owner], helpers: Mapping[int, Owner]) -> tuple[str, ...]:
    lines = []
    for frame, lineno in frames:
        code = frame.f_code
        found = running.get(id(code))
        if found is not None:
            piece = found[1]
            lines.append(f"  {node.file.ref}, line {piece.line + lineno - 1} ({_role(node)})")
            continue
        found = helpers.get(id(code))
        if found is not None:
            owner, piece = found
            lines.append(f"  in {_role(owner)}, {owner.file.ref}, line "
                         f"{piece.line + lineno - 1}")
            continue
        if _is_engine_frame(frame):
            continue
        filename = code.co_filename
        module = frame.f_globals.get("__name__") if isinstance(frame.f_globals, dict) else None
        if filename.startswith("<script/") and filename.endswith(">"):
            lines.append(f"  in the story's Python, {echo(filename[1:-1])}")
        elif type(module) is str:
            lines.append(f"  in Python module {echo(module, VALUE_ECHO_MAX_CHARS)}")
        else:
            lines.append("  in Python code")
    return (TRACE_HEAD, *_fold(lines), type(e).__name__)


# --- The mapping -------------------------------------------------------------------------

def prefix_text(owner: Node) -> str:
    """SR-F03-31's prefix: ``define X couldn't be set: `` / ``default X couldn't be set: ``
    / (F12 SR-F12-06) ``default persistent.X couldn't be set: ``."""
    return f"{_declared(owner)} couldn't be set: "


class _Reading:
    """What the traceback says: the line at the running piece, the define-helper suffix, the
    innermost author piece (for E85f and E85j), and the trace."""

    def __init__(self, e: BaseException, node: Node, program: object | None) -> None:
        frames = _frames(e)
        running = _owners([node])
        helpers: dict[int, Owner] = {}
        if program is not None:
            helpers = _owners(getattr(program, "defines", ()), skip=node)
        self.line = node.line
        self.suffix = ""
        self.innermost: tuple[PyCode, int] | None = None
        self.piece: PyCode | None = None        # F23: the outermost running piece
        outer_found = False
        for frame, lineno in frames:
            code_id = id(frame.f_code)
            found = running.get(code_id)
            if found is not None:
                if not outer_found:
                    self.line = found[1].line + lineno - 1
                    self.piece = found[1]
                    outer_found = True
                self.innermost = (found[1], found[1].line + lineno - 1)
                continue
            found = helpers.get(code_id)
            if found is not None:
                owner, piece = found
                line = piece.line + lineno - 1
                name = owner.name  # type: ignore[attr-defined]
                self.suffix = f" (in define {name}, {owner.file.ref}, line {line})"
                self.innermost = (piece, line)
        self.trace = _trace(e, frames, node, running, helpers)


def map_exception(e: BaseException, stmt: Node, *, prefix: Node | None = None,
                  names: Iterable[str] = (), program: object | None = None,
                  guard: AuthorCodeGuard = NO_GUARD) -> StoryError:
    """``e`` raised by author code at ``stmt`` as a ``StoryError`` (§7.11, first match).

    ``prefix`` is the define or default whose value failed: the error is then at its line
    with SR-F03-31's prefix. ``names`` are the names an E85b suggestion may offer (story
    variables, defaults, defines); ``program`` adds the default and define names, the
    define helpers for SR-F03-34's suffix and the trace, and E85b's ``$``-line form.
    ``guard`` wraps every call that may run author code (``str(e)``, ``dir(obj)``)."""
    if isinstance(e, StoryError):
        return e
    node = prefix if prefix is not None else stmt
    head = prefix_text(prefix) if prefix is not None else ""
    read = _Reading(e, node, program)
    try:
        code, message, head = _classify(e, node, head, read, names, program, guard)
    except Exception:            # an author object misbehaved while being described
        code, message = "E85", format_message("E85", (_subject(node), None, read.suffix))
    return StoryError(head + message, code=code, trace=read.trace, **where(node, read.line))


def _classify(e: BaseException, node: Node, head: str, read: _Reading, names: Iterable[str],
              program: object | None, guard: AuthorCodeGuard) -> tuple[str, str, str]:
    """(code, message, prefix) by the first matching row of §7.11's table."""
    prefix = node if head else None
    suffix = read.suffix
    subject = _subject(node, read.piece)
    if isinstance(e, PersistentError):                    # F12, first (E180 before E85c)
        code, message = persistent_error(e, node, suffix)
    elif isinstance(e, Unsaveable):
        name = prefix.name if prefix is not None else "value"  # type: ignore[attr-defined]
        code, message = "E85e", unsaveable_message(name, e)
    elif isinstance(e, AuthorRefusal):
        code, message = e.code, e.message
        if not e.prefixed:
            head = ""
    elif isinstance(e, NameError) and type(getattr(e, "name", None)) is str:
        code, message = "E85b", _e85b(e.name, names, program, suffix, node)
    elif isinstance(e, AttributeError) and type(getattr(e, "name", None)) is str:
        code, message = "E85c", _e85c(e, guard, suffix)
    elif isinstance(e, TypeError) and (kinds := mixed_kinds(_raw_text(e, guard))) is not None:
        code, message = "E85d", format_message("E85d", (*kinds, suffix))
    elif isinstance(e, SystemExit):
        code = "E85f"
        message = format_message("E85f", (_close_subject(node), _exit_call(read.innermost),
                                          suffix))
    elif isinstance(e, ZeroDivisionError):
        code, message = "E85g", format_message("E85g", (suffix,))
    elif isinstance(e, RecursionError):
        code, message = "E85i", format_message("E85i", (suffix,))
    elif isinstance(e, DiceArgumentError):
        code, message = "E85j", _e85j(e, read.innermost, suffix)
    elif isinstance(e, ConsoleUnavailable):
        code, message = "E85n", format_message("E85n", (e.name, suffix))
    else:
        code = "E85"
        message = format_message("E85", (subject, _python_text(e, guard), suffix))
    return code, message, head


# --- F12: the store's refusals (E180–E183, E185) ---------------------------------------------

HIDDEN_KEY = "[…]"                     # E181: a dict key that isn't a script literal


def script_strings(node: Node) -> frozenset[str]:
    """The string literals written in ``node``'s Python (its ``$`` line, condition, or
    value, with the lambdas and comprehensions inside them): the only dict keys an E181
    path may show (SEC-F12-09)."""
    found: set[str] = set()

    def visit(const: object) -> None:
        if type(const) is str:
            found.add(const)
        elif type(const) in (tuple, frozenset):
            for item in const:                                  # type: ignore[attr-defined]
                visit(item)
        elif isinstance(const, CodeType):
            for item in const.co_consts:
                visit(item)

    pieces = [getattr(node, attr, None) for attr in ("py", "value", "condition")]
    pieces += [getattr(branch, "condition", None) for branch in getattr(node, "branches", ())]
    for piece in pieces:
        if isinstance(piece, PyCode) and piece.code is not None:
            visit(piece.code)
    return frozenset(found)


def private_path(subject: str, path: Iterable[str | int], shown: frozenset[str]) -> str:
    """``persistent.bag["key"][2]``, with each dict key not in ``shown`` written ``[…]``:
    keys can come from a file players edit and share, and may hold a name (SEC-F12-09)."""
    out = [subject]
    for part in path:
        if type(part) is int:
            out.append(f"[{part}]")
        elif part in shown:
            escaped = part.replace("\\", "\\\\").replace('"', '\\"')
            out.append(f'["{escaped}"]')
        else:
            out.append(HIDDEN_KEY)
    return "".join(out)


def persistent_unsaveable(name: str, exc: Unsaveable, suffix: str = "",
                          shown: frozenset[str] = frozenset()) -> str:
    """E181: the subject is ``persistent.<name>``, or the path to the value inside it
    (``persistent.bag["key"][2]``, a key not among ``shown``, the script's literals, as
    ``[…]``); kinds and fixes as SR-F03-33."""
    subject = f"persistent.{name}"
    if exc.reason != TOO_DEEP and exc.path:
        subject = private_path(subject, exc.path, shown)
    detail = ""
    if exc.reason == KEY:
        key = exc.value
        if key is None or type(key) in (bool, int, float):
            detail = short_value(key)
    kind = kind_words(exc.value) if exc.reason == KIND else ""
    return format_message("E181", (exc.reason, subject, kind, detail, suffix))


def define_written(define: Node) -> str | None:
    """E185's example value: the define's value as written, comments left out and its
    lines joined, when that is at most ``E185_VALUE_MAX_CHARS`` characters."""
    piece = getattr(define, "value", None)
    if not isinstance(piece, PyCode):
        return None
    text = " ".join(part.strip() for part in piece.without_comments().split("\n")
                    if part.strip())
    return text if text and len(text) <= E185_VALUE_MAX_CHARS else None


def persistent_error(e: PersistentError, node: Node, suffix: str = "") -> tuple[str, str]:
    """``(code, message)`` for a refused persistent access (F12 ``04`` §6 mapping). A
    did-you-mean drawn from stored names goes through ``messages``' quoting (SEC-F12-09d)."""
    name = e.name
    if isinstance(e, PersistentNoValue):
        pool = [n for n in e.candidates() if type(n) is str and n != name]
        return "E180", format_message("E180", (name, suggest(name, pool), suffix))
    if isinstance(e, PersistentViewName):                 # F19: a computed setattr/delattr
        return "E245", format_message("E245", ("change", name))
    if isinstance(e, PersistentUnsaveable):
        return "E181", persistent_unsaveable(name, e.error, suffix, script_strings(node))
    if isinstance(e, PersistentEngineName):
        if e.form == "read":
            args: tuple = ("read", name, "", suggest(name, ("_clear",)), suffix)
        elif e.form == "progress":
            args = ("progress", name, short_value(e.value), None, suffix)
        else:
            args = (e.form, name, "", None, suffix)
        return "E182", format_message("E182", args)
    if isinstance(e, PersistentTooBig):
        return "E183", format_message("E183", (e.form, e.size, suffix, e.limit))
    if isinstance(e, PersistentInDefine):
        define = node.name if isinstance(node, Define) else ""
        return "E185", format_message("E185", (define, name, define_written(node)))
    return "E85", format_message("E85", (_subject(node), None, suffix))


def _close_subject(node: Node) -> str:
    """E85f's subject: ``this $ line`` as in ``02``; a condition or value names itself."""
    return "this $ line" if isinstance(node, PythonLine) else _subject(node)


def _raw_text(e: BaseException, guard: AuthorCodeGuard) -> str:
    try:
        guard.enter()
        try:
            text = str(e)
        finally:
            guard.exit()
    except Exception:
        return ""
    return text if type(text) is str else ""


def timeout_error(stmt: Node | None, e: BaseException | None = None, *,
                  prefix: Node | None = None, program: object | None = None) -> StoryError:
    """E85m: the watchdog interrupted author code at ``stmt``. With the interrupt ``e``, the
    line and SR-F03-34's suffix come from its traceback. ``stmt`` None (``App.run``'s I-8
    fallback with no statement to name) gives the message with no place."""
    node = prefix if prefix is not None else stmt
    if node is None:
        return StoryError(format_message("E85m", ("this Python",)), code="E85m")
    head = prefix_text(prefix) if prefix is not None else ""
    line, suffix, trace, piece = node.line, "", (), None
    if e is not None:
        read = _Reading(e, node, program)
        line, suffix, trace, piece = read.line, read.suffix, read.trace, read.piece
    message = format_message("E85m", (_subject(node, piece), suffix))
    return StoryError(head + message, code="E85m", trace=trace, **where(node, line))


# --- The log record (§7.11, TR-F03-09) -------------------------------------------------------

def log_details(error: StoryError) -> str:
    """The lines after the message in the error's log record: the script line through
    ``echo()``, then the script-frame trace. Never a raw Python traceback."""
    lines = []
    if error.source_line is not None:
        lines.append("    " + echo(error.source_line))
    lines.extend(error.trace)
    return "\n".join(lines)


def log_error(log: logging.Logger, error: StoryError) -> None:
    """One ERROR record (area ``runtime``): ``error.format()`` as the message, and the script
    line and trace as the record's detail text, which F01's formatter writes on the following
    lines like a traceback. Marks the error ``logged``."""
    if log.isEnabledFor(logging.ERROR):
        record = log.makeRecord(log.name, logging.ERROR, __file__, 0, "%s", (error.format(),),
                                None, func="log_error")
        details = log_details(error)
        if details:
            record.exc_text = details
        log.handle(record)
    error.logged = True


__all__ = ["AuthorRefusal", "ConsoleUnavailable", "StoryError", "TRACE_HEAD",
           "define_written", "error_line", "first_setting_line", "log_details", "log_error",
           "map_exception", "mixed_kinds", "persistent_error", "persistent_unsaveable",
           "prefix_text", "python_text_allowed", "short_value", "statement_source",
           "timeout_error", "type_words", "unsaveable_message", "where",
           # F24 07 I-1: re-exported for ``minigames.api.closest`` (minigames never imports
           # script); the one did-you-mean rule (SR-F02-70).
           "suggest"]
