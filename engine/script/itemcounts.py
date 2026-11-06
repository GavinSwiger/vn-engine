"""F64 round 1: the whole-game checks of item counts and the purse (specs/F64-items/SPEC.md).

Why this module exists: an item's count is read in Python as ``items.count("coin")`` (or
``codex.count("coin")``, its spelling from before version 1, W323), with the item's name as a quoted argument the bindings pass never
looks at, and the purse is one item marked ``money`` across every file. So, once every file is
read (nothing runs):

- E439 at the second item marked ``money`` (the bag shows one purse);
- each condition, ``$`` line and ``points`` amount that mentions ``count`` is parsed, and every
  ``items.count("<name>")`` / ``codex.count("<name>")`` with a plain argument is checked: E440
  when no ``lock item`` declares that name (did-you-mean; its ``tip`` form for a tip, its
  ``text`` form for a number); E441 for ``items.<other>`` or a change of ``items``. These hold
  only while ``items`` is the engine's: a story that sets a variable of its own named
  ``items`` (``default``, ``define``, or a ``$`` line) keeps it, and W306 says to rename it
  where it counts a declared item through it;
- each ``unlock item <name> <n>``: W305 when the item has no count (it holds one), W307 when
  ``n`` is over its count's most.

``binds_items`` is shared with the runtime (``runtime/codex.install``), so the checker and
the game agree on whose ``items`` it is. A computed argument (``items.count(which)``) is left
to run time (E440, E441).
"""

import ast
from collections.abc import Callable, Iterable

from engine.script.bindings import Piece, iter_pieces, parse, scan
from engine.script.codex import WORD_ITEM, CodexEntryDecl, CodexLock
from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.identity import walk_block
from engine.script.messages import format_message
from engine.script.nodes import Default, Define, Label, Node
from engine.script.suggest import suggest

ITEMS = "items"                       # the engine view (soft: a story's own variable wins)
CODEX = "codex"
COUNT = "count"
HELD = "held"                         # v1: items.held, the held names (was codex.items)


def binds_items(pieces: Iterable[Piece], names: Iterable[str]) -> bool:
    """True when the story sets a variable named ``items`` of its own: a define or default
    among ``names``, or a ``$`` line or condition that binds it at its top level."""
    if ITEMS in set(names):
        return True
    for piece in pieces:
        code = piece.py.code
        if code is None or ITEMS not in code.co_names:
            continue
        tree = parse(piece.py)
        if tree is not None and scan(tree).first_binding(lambda n: n == ITEMS) is not None:
            return True
    return False


def program_binds_items(program) -> bool:
    """``binds_items`` for a built ``Program`` (the runtime's question)."""
    return binds_items(iter_pieces(program.labels.values()),
                       program.define_names | program.default_names)


def _count_call(node: ast.AST, roots: tuple[str, ...]) -> tuple[str, object] | None:
    """``(root, argument)`` of ``<root>.count(<constant>)``, or None."""
    if not (isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords):
        return None
    func, arg = node.func, node.args[0]
    if (isinstance(func, ast.Attribute) and func.attr == COUNT
            and isinstance(func.value, ast.Name) and func.value.id in roots
            and isinstance(arg, ast.Constant)):
        return func.value.id, arg.value
    return None


def _items_misuse(tree: ast.AST) -> tuple[int, str, str] | None:
    """The first ``items.<attr>`` that isn't a read of ``count`` or ``held``: (line, form,
    attr)."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == ITEMS:
            if not isinstance(node.ctx, ast.Load):
                found.append((node.lineno, node.col_offset, "change", node.attr))
            elif node.attr not in (COUNT, HELD) and not node.attr.startswith("__"):
                found.append((node.lineno, node.col_offset, "unknown", node.attr))
    if not found:
        return None
    line, _col, form, attr = min(found)
    return line, form, attr


def check_count_uses(pieces: Iterable[Piece], items: dict[str, CodexEntryDecl],
                     tips: frozenset[str], own: bool,
                     add: Callable[[Diagnostic], object]) -> list[ScriptWarning]:
    """E440 and E441 go to ``add`` (one per piece, the first in source order); W306s are
    returned in reading order (module docstring)."""
    warnings: list[ScriptWarning] = []
    roots = (CODEX,) if own else (CODEX, ITEMS)
    for piece in pieces:
        py = piece.py
        source = py.source
        if not ((not own and ITEMS in source)
                or (COUNT in source and (ITEMS in source or CODEX in source))):
            continue
        tree = parse(py)
        if tree is None:
            continue
        at = py.line - 1

        def report(code: str, line: int, args: tuple) -> None:
            add(Diagnostic(code, piece.file, at + line, None, args, stmt=piece.stmt))

        if not own:
            misuse = _items_misuse(tree)
            if misuse is not None:
                line, form, attr = misuse
                report("E441", line, (form, attr))
                continue
        calls = sorted((node.lineno, node.col_offset, root, arg) for node in ast.walk(tree)
                       if (found := _count_call(node, (CODEX, ITEMS))) is not None
                       for root, arg in (found,))
        for line, _col, root, arg in calls:
            if root == ITEMS and own:
                if type(arg) is str and arg in items:
                    warnings.append(ScriptWarning(format_message("W306", (arg,)),
                                                  code="W306", file=piece.file.ref,
                                                  line=at + line))
                continue
            if type(arg) is not str:
                report("E440", line, ("text", repr(arg)))
                break
            if arg in items:
                continue
            if arg in tips:
                report("E440", line, ("tip", arg))
            else:
                report("E440", line, ("unknown", arg, suggest(arg, tuple(items))))
            break
    return warnings


def check_story(nodes: list[Node], add: Callable[[Diagnostic], object]) -> list[ScriptWarning]:
    """Every check of the module docstring over ``nodes`` (for ``checks.py`` and tests)."""
    items: dict[str, CodexEntryDecl] = {}
    tips: set[str] = set()
    money: CodexEntryDecl | None = None
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, CodexEntryDecl):
            if node.kind != WORD_ITEM:
                tips.add(node.name)
                continue
            items.setdefault(node.name, node)
            if node.money:
                if money is None:
                    money = node
                elif money.name != node.name:
                    add(Diagnostic("E439", node.file, node.line, None,
                                   (node.name, money.name, (money.file.ref, money.line)),
                                   stmt=node.line))
        elif isinstance(node, (Define, Default)):
            names.add(node.name)
    own = binds_items(iter_pieces(nodes), names)
    warnings = check_count_uses(iter_pieces(nodes), items, frozenset(tips), own, add)
    for node in nodes:
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if not (isinstance(stmt, CodexLock) and stmt.unlock and stmt.written
                    and stmt.kind == WORD_ITEM):
                continue
            decl = items.get(stmt.name)
            if decl is None:
                continue                                  # F21's E253 names it
            if decl.count is None and stmt.amount > 1:
                code, args = "W305", (stmt.name, stmt.amount)
            elif decl.count is not None and stmt.amount > decl.count:
                code, args = "W307", (stmt.name, stmt.amount, decl.count)
            else:
                continue
            warnings.append(ScriptWarning(format_message(code, args), code=code,
                                          file=stmt.file.ref, line=stmt.line))
    return warnings


__all__ = ["binds_items", "check_count_uses", "check_story", "program_binds_items"]
