"""W320: a remembered variable's name used without ``persistent.`` (first-game fix,
2026-11-06).

Why this module exists: ``default persistent.knows_recipe = False`` makes
``persistent.knows_recipe``; a line that says plain ``knows_recipe`` reads or sets a
different, story variable. When no ``default`` or ``define`` has that name, reading it stops
the story ("there is no variable named …", whose suggested fix is the opposite of what the
author meant), and setting it never reaches the remembered value. Ticking "Remembered across
playthroughs" in Studio used to leave such lines behind, and a hand edit can too, while the
check said nothing.

- **Which names**: each ``default persistent.<n>`` name that no ``define`` or ``default``
  also has (``Collected.define_defs``, ``default_defs``). None (the usual case): nothing
  is read.
- **Where**: every compiled piece (``bindings.iter_pieces(values=True)``: ``$`` lines,
  conditions, ``points`` amounts, minigame arguments, achievement conditions, and define and
  default values), nested code included, through ``bindings.parse`` (F02's compile rules;
  nothing runs). A plain name that is a parameter or a comprehension target somewhere in
  the piece is left out: it may be that code's own name.
- **Reported**: once per line, at the line, naming the persistent default's place, in
  reading order; at most ``W320_MAX`` lines.

Pure: no file access, no author code.
"""

import ast
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from engine.script import bindings
from engine.script.diagnostics import ScriptWarning
from engine.script.messages import format_message
from engine.script.nodes import Node, PersistentDefault

W320_MAX: Final = 50

Place = tuple[object, int]          # (ScriptFile, line)


def _own_names(tree: ast.AST) -> set[str]:
    """Names the piece's nested code binds for itself (parameters, comprehension targets)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, ast.comprehension):
            out.update(n.id for n in ast.walk(node.target) if isinstance(n, ast.Name))
    return out


def plain_uses(nodes: Iterable[Node], names: frozenset[str]
               ) -> list[tuple[str, int, str, bool]]:
    """``(file ref, line, name, sets)`` for each line whose code names one of ``names``
    plainly, in reading order (one per line: its first such name); ``sets``: no use on the
    line reads a watched name."""
    found: dict[tuple[str, int], tuple[str, bool]] = {}
    watched = tuple(sorted(names))
    for piece in bindings.iter_pieces(nodes, values=True):
        if not bindings.mentions(piece.py, watched):
            continue
        tree = bindings.parse(piece.py)
        if tree is None:
            continue
        own = _own_names(tree)
        changed = {id(node.target) for node in ast.walk(tree)        # x += 1 reads x too
                   if isinstance(node, ast.AugAssign)}
        hits = sorted((node.lineno, node.col_offset, node.id,
                       isinstance(node.ctx, ast.Load) or id(node) in changed)
                      for node in ast.walk(tree)
                      if isinstance(node, ast.Name) and node.id in names
                      and node.id not in own)
        for row, _col, name, reads in hits:
            key = (piece.file.ref, piece.py.line + row - 1)
            first, sets = found.get(key, (name, True))
            found[key] = (first, sets and not reads)
    return [(ref, line, name, sets) for (ref, line), (name, sets) in found.items()]


def check_story(nodes: Sequence[Node], defines: Mapping[str, object],
                defaults: Mapping[str, object]) -> list[ScriptWarning]:
    """W320 (module docstring) for the loaded ``nodes``; ``defines`` and ``defaults`` are the
    plain names declared (``Collected.define_defs``, ``default_defs``)."""
    first: dict[str, tuple[str, int]] = {}
    for node in nodes:
        if isinstance(node, PersistentDefault) and node.name not in defines \
                and node.name not in defaults:
            first.setdefault(node.name, (node.file.ref, node.line))
    if not first:
        return []
    out: list[ScriptWarning] = []
    for ref, line, name, sets in plain_uses(nodes, frozenset(first))[:W320_MAX]:
        out.append(ScriptWarning(format_message("W320", (name, first[name], sets)),
                                 code="W320", file=ref, line=line))
    return out


__all__ = ["W320_MAX", "check_story", "plain_uses"]
