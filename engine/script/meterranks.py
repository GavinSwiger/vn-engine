"""F62 round 1: the whole-game checks of ``points.rank("<meter>")`` (specs/F62-visible-meters).

Why this module exists: ``points.rank`` is a method, so the bindings pass (``bindings.py``)
doesn't treat it as a meter read, and its meter is a quoted argument that pass never looks
at. Here, once every file is read, each condition, ``$`` line, and ``points`` amount that
mentions ``rank`` is parsed (nothing runs) and every ``points.rank("<name>")`` with a plain
string argument is checked against the declared meters:

- E233 (F22's text, did-you-mean) when no ``points`` line declares that meter;
- E416 when the meter has no ranks;
- W290 when it is compared with ``==`` or ``!=`` to a plain string that is none of its
  rank labels (did-you-mean): that comparison never matches.

A computed argument (``points.rank(who)``) is left to run time (E236's forms).
"""

import ast
from collections.abc import Callable, Iterable, Iterator, Mapping

from engine.script.bindings import Piece, iter_pieces, parse
from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.messages import format_message
from engine.script.nodes import Node
from engine.script.points import WORD_POINTS, WORD_RANK, PointsDecl
from engine.script.suggest import suggest


def meter_ranks(nodes: Iterable[Node]) -> dict[str, tuple[str, ...]]:
    """Every declared meter → its rank labels (``()``: none), from the ``points`` lines."""
    return {name: tuple(label for label, _ in node.ranks)
            for node in nodes if isinstance(node, PointsDecl) for name in node.names}


def _rank_call(node: ast.AST) -> str | None:
    """The meter of ``points.rank("<name>")``, or None for anything else."""
    if not (isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords):
        return None
    func, arg = node.func, node.args[0]
    if (isinstance(func, ast.Attribute) and func.attr == WORD_RANK
            and isinstance(func.value, ast.Name) and func.value.id == WORD_POINTS
            and isinstance(arg, ast.Constant) and type(arg.value) is str):
        return arg.value
    return None


def _compared(tree: ast.AST) -> Iterator[tuple[ast.Call, str, str]]:
    """``(call, meter, label)`` for each ``points.rank("m") ==/!= "label"`` (either side)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], (ast.Eq, ast.NotEq)):
            continue
        left, right = node.left, node.comparators[0]
        for call, other in ((left, right), (right, left)):
            meter = _rank_call(call)
            if (meter is not None and isinstance(other, ast.Constant)
                    and type(other.value) is str):
                yield call, meter, other.value  # type: ignore[misc]


def check_rank_uses(pieces: Iterable[Piece], ranks: Mapping[str, tuple[str, ...]],
                    add: Callable[[Diagnostic], object]) -> list[ScriptWarning]:
    """E233 and E416 go to ``add`` (one per piece, the first in source order); W290s are
    returned in reading order (module docstring)."""
    warnings: list[ScriptWarning] = []
    for piece in pieces:
        py = piece.py
        if WORD_RANK not in py.source or WORD_POINTS not in py.source:
            continue
        tree = parse(py)
        if tree is None:
            continue
        calls = sorted(((node.lineno, node.col_offset, meter) for node in ast.walk(tree)
                        if (meter := _rank_call(node)) is not None))
        error = None
        for lineno, _col, meter in calls:
            if meter not in ranks:
                error = ("E233", lineno, (meter, suggest(meter, tuple(ranks))))
            elif not ranks[meter]:
                error = ("E416", lineno, (meter,))
            if error is not None:
                break
        if error is not None:
            code, lineno, args = error
            add(Diagnostic(code, piece.file, py.line + lineno - 1, None, args,
                           stmt=piece.stmt))
            continue
        for call, meter, label in _compared(tree):
            labels = ranks.get(meter, ())
            if labels and label not in labels:
                text = format_message("W290", (label, meter, suggest(label, labels), labels))
                warnings.append(ScriptWarning(text, code="W290", file=piece.file.ref,
                                              line=py.line + call.lineno - 1))
    return warnings


def check_story(nodes: list[Node], add: Callable[[Diagnostic], object]) -> list[ScriptWarning]:
    """``check_rank_uses`` over every piece of ``nodes`` (for ``checks.py`` and tests)."""
    return check_rank_uses(iter_pieces(nodes), meter_ranks(nodes), add)


__all__ = ["check_rank_uses", "check_story", "meter_ranks"]
