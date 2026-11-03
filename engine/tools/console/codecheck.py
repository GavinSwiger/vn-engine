"""The console's Code-line check (F40 ``04`` §7.3, ``05`` SEC-F40-02, SEC-F40-12; AC-F40-14).

Why this module exists: a Code line runs in the story namespace with the same rules as a
``$`` line, so it must pass the same load-time checks before anything runs. Those checks
aren't a sandbox (05 §1): they catch mistakes, and a refused line runs nothing.

``check_line(source, program)``:

1. ``clean_line``: the first line only, NUL and C0/C1 control characters dropped, cut to
   ``LINE_MAX`` (2,000) characters. The input field and Ctrl+V use the same function
   (SEC-F40-12), so what is checked is what the field holds.
2. ``pycheck``: eval mode when the line compiles as one expression, else exec mode, then
   ``compile_piece`` under the ``<console>`` file name (E80/E83/E270 for exec, E86 for too
   deep or too many ``lambda``; the lambda count comes from ``parse_tree``).
3. The whole per-piece verdict of a ``$`` line, through ``bindings``' public functions:
   ``check_piece(prefilter=False)`` (E88, E87, E62, E63), else ``use_error`` over the
   piece's ``persistent``/``points``/``codex`` uses with the program's meters and engine
   views (E234, E245, E255, E233). Defines come from ``program.defines`` (first node of
   each name).

The result is a ``CheckedLine`` (the compiled code and its mode) or a ``Refused`` with the
message as the load shows it (``message_text``: first letter capitalized unless it opens
with code; no file or line, since there is none). Nothing here runs author code, touches ``G``, or logs.
"""

import ast
import io
import re
import tokenize
import types
from dataclasses import dataclass

from engine.runtime.fourthwall import names_identity
from engine.script.bindings import (KIND_CONDITION, KIND_EXEC, ROOTS, Defines, Piece,
                                    check_piece, parse, scan, use_error)
from engine.script.messages import format_message
from engine.script.nodes import PyCode, ScriptFile
from engine.script.program import Program
from engine.script.pycheck import (ROLE_CONDITION, ROLE_EXEC, compile_piece,
                                   compiles_as_expression, parse_tree)
from engine.script.routes import PERSISTENT_VIEWS

LINE_MAX = 2_000                          # PR-F40-13, SEC-F40-12
CONSOLE_NAME = "<console>"                # co_filename of every console code object
CONSOLE_FILE = ScriptFile(ref=CONSOLE_NAME, include_path=CONSOLE_NAME, order=1 << 30)

# NUL, C0, DEL, and C1 controls (SEC-F40-12); line breaks are handled before this.
_CONTROLS = dict.fromkeys((*range(0x20), 0x7F, *range(0x80, 0xA0)))
_OPENS_WITH_CODE = re.compile(r"[a-z_]\w*\.\w")


@dataclass(frozen=True, slots=True)
class CheckedLine:
    """A line that passed every check: ``code`` runs with ``eval`` (``mode`` ``"eval"``,
    show its value) or ``exec`` (``"exec"``, show ``Done.``). ``reads_identity``: W190's
    scan flagged it (SEC-F40-11)."""

    source: str
    code: types.CodeType
    mode: str
    reads_identity: bool = False


@dataclass(frozen=True, slots=True)
class Refused:
    """A line that failed a check: its message code (``E80``, ``E88``, …) and text."""

    code: str
    text: str


def clean_line(text: str) -> str:
    """What the Code field keeps of typed or pasted text: its first line, without NUL and
    C0/C1 control characters, cut to ``LINE_MAX`` characters (SEC-F40-12)."""
    if type(text) is not str:
        return ""
    lines = text[:LINE_MAX * 4].splitlines()      # bounded work on a huge paste
    first = lines[0] if lines else ""
    return first.translate(_CONTROLS)[:LINE_MAX]


def message_text(code: str, args: tuple = ()) -> str:
    """``code``'s message as a line of its own: ``format_message``'s text with its first
    letter capitalized, unless it opens with code such as ``persistent.endings``."""
    text = format_message(code, args)
    return text if _OPENS_WITH_CODE.match(text) else text[:1].upper() + text[1:]


def _refused(code: str, args: tuple) -> Refused:
    return Refused(code, message_text(code, args))


def _lambdas(source: str, mode: str) -> int:
    tree = parse_tree(source, mode)
    if tree is None:
        return 0                                  # compile_piece reports the mistake
    return sum(1 for node in ast.walk(tree) if isinstance(node, ast.Lambda))


def _without_comment(source: str) -> str:
    """The one-line ``source`` up to its comment, if it has one (W190 skips comments)."""
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                return source[:tok.start[1]]
    except (tokenize.TokenError, SyntaxError, ValueError):
        pass
    return source


def _defines(program: Program) -> Defines:
    first = {}
    for node in program.defines:
        first.setdefault(node.name, ((node.file, node.line),))
    return Defines.from_nodes(first, program.defines)


def check_line(source: str, program: Program) -> CheckedLine | Refused:
    """Check one Code line as a ``$`` line is checked at load (module docstring)."""
    source = clean_line(source)
    mode = "eval" if compiles_as_expression(source) else "exec"
    kind = KIND_CONDITION if mode == "eval" else KIND_EXEC
    result = compile_piece(source, mode=mode, role=ROLE_CONDITION if mode == "eval" else ROLE_EXEC,
                           filename=CONSOLE_NAME, line=1, column=1,
                           lambdas=_lambdas(source, mode))
    if result.problem is not None or result.code is None:
        problem = result.problem
        if problem is None:                       # pragma: no cover (compile_piece's rule)
            return _refused("E86", (ROLE_EXEC,))
        return _refused(problem.code, problem.args)
    py = PyCode(source=source, line=1, column=1, mode=mode, code=result.code)
    piece = Piece(file=CONSOLE_FILE, stmt=1, py=py, kind=kind)
    error, _ = check_piece(piece, _defines(program), frozenset(), prefilter=False)
    if error is None:
        tree = parse(py)
        if tree is not None:
            meters = frozenset(meter.name for meter in program.meters)
            error = use_error(piece, scan(tree, ROOTS).uses, meters, PERSISTENT_VIEWS)
    if error is not None:
        return _refused(error.code, error.args)
    return CheckedLine(source, result.code, mode, names_identity(_without_comment(source)))


__all__ = ["CONSOLE_FILE", "CONSOLE_NAME", "CheckedLine", "LINE_MAX", "Refused", "check_line",
           "clean_line", "message_text"]
