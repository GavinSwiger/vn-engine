"""What a ``$`` line or condition may set (F03 SR-F03-09, SR-F03-21, SR-F03-25;
``04-technical.md`` §6.2).

Every compiled ``$`` line and ``if``/``elif`` condition of the labels is a **piece**. For
each piece, the first match wins, one error per piece (SR-F02-68):

1. ``import`` or ``from … import`` anywhere in a ``$`` line → E88 (the first one in source
   order), with the ``define … = module(…)`` form of that import.
2. Else the names the piece binds at its top level, the first in source order that is a
   define name → E87, an engine name (``ENGINE_NAMES``) → E62, or starts with ``_`` → E63.

A **top-level binding** is a ``Name`` stored or deleted in the piece's own scope: targets of
``=``, ``+=`` and the other augmented assignments, annotated assignment with a value, ``:=``,
``del``, ``for``, ``with … as``, and the names of ``def`` and ``class``. The same scope also
binds ``except … as``, ``match`` captures, and ``type`` aliases, which count too. Names
bound inside ``lambda``, comprehensions, and function or class bodies don't; the parts of
those that run in the piece's scope (decorators, default values, bases, a comprehension's
first ``in``) do. Attribute and item targets (``persistent.x = 1``, ``scores["a"] = 2``)
bind no name.

W05 (SR-F03-21): a top-level expression statement of a ``$`` line that is a call of
``dice.shuffle``, whose result is thrown away. At most one per piece.

**Prefilter** (§6.2 step 1): a piece is parsed only if its top-level ``code.co_names`` meets
``define names ∪ ENGINE_NAMES``, holds a name starting with ``_``, or its source matches
``\\bimport\\b``. Every top-level binding puts its name in ``co_names`` (``STORE_NAME``,
``DELETE_NAME``, import targets, ``:=`` in ``eval`` mode), and W05 needs ``dice`` there, so
nothing is missed; attribute names only cost a parse (AC-F03-25).

The parse follows F02's rules for author Python through ``pycheck.parse_tree`` (the one
module that compiles): ``str`` source, ``dont_inherit=True``, warnings caught; nothing
runs. The walk over the tree is iterative (SEC-F02-05). The pass runs in F02's whole-game
checks (``checks.py``), yielding every ``IDENTITY_YIELD_ITEMS`` pieces, sooner when they
are parsed (``iter_check_all``); errors go through the caller's ``report`` into the sorted
sink, so they sort with F02's.

**Root uses** (F12 conflict 6, F12 07 I-1; F22 07 question 2): the same walk collects every
``<root>.<attr>`` use for the names in ``ROOTS`` (F12: ``persistent``; F22 adds ``points``):
a read is an attribute loaded (``persistent.a``, ``persistent.j.append(1)``), a write one
stored, augmented, or deleted (``persistent.b += 1``, ``del persistent.c``) or a literal
``setattr``/``delattr(persistent, "d")``. Attributes starting with ``_`` belong to the engine
and aren't collected. The collection covers every piece kind, nested code (lambdas,
functions, comprehensions) included, and also visits define values, default values, and
F12's persistent default values (``KIND_VALUE``, ``iter_pieces(values=True)``), which get no
binding checks. A piece is parsed for it only if a root is among the names of its code or
any code nested in it (``mentions``). ``RootUses`` keeps, per root, each read name's first
use (file ref, line) in reading order and the set of written names; ``checks.py`` hands
``persistent``'s to the ``Program``.

**Meters** (F22 SPEC SR-F22-04, 07 I-5): the amount of a ``points`` line is a piece too, an
eval-mode one checked like a condition, that also carries the line's meter name. Given the
declared meters (``iter_check_all(meters=)``), each piece then gets, after its E88/E87/E62/E63
and in source order, E234 for a ``points.<name>`` stored, augmented, or deleted (literal
``setattr``/``delattr`` included), else E233 for its line's meter name or a ``points.<name>``
read that names no meter (did-you-mean). ``points.highest`` is not a meter read. Still one
error per piece; define, default, and persistent default values get these checks too.

**Engine views** (F19 ``04-technical.md`` §6.3, ``06`` D2): a third use kind, ``CHANGE``, is
``<root>.<attr>.<m>`` with ``m`` in ``MUTATORS`` (``persistent.endings.append``) or
``<root>.<attr>[…]`` stored or deleted. ``RootUses`` ignores it (F12's reads and writes are
unchanged: the inner ``<root>.<attr>`` is still a read). A write or change of
``persistent.endings`` or ``persistent.routes`` (``routes.PERSISTENT_VIEWS``) is E245, after
E234 and before E233 in a piece (``use_error``). An alias or ``getattr`` changes only the copy
each read returns, so it is no use.

**Minigames** (F23 ``04`` §5.2 step 5): each value of a ``minigame`` line's arguments is an
eval-mode piece checked like a condition (E87/E62/E63, then E234, E245, E255, E233).

**The codex** (F21 ``04-technical.md`` §6.2, ``06`` D1): ``codex`` is a root too. Each piece
gets, after E245 and before E233, E255 for its first ``codex`` use in source order that is
not a read of ``tips`` or ``items``: a read of another attribute is E255's ``unknown`` form
(did-you-mean over the two), a write or change of ``tips``/``items`` its ``change`` form.
"""

import ast
import re
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import CodeType

from engine.core.constants import VALUE_ECHO_MAX_CHARS
from engine.script.achievements import AchievementDecl
from engine.script.diagnostics import Diagnostic, ScriptWarning
from engine.script.identity import walk_block
from engine.script.limits import IDENTITY_YIELD_ITEMS
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.messages import format_message
from engine.script.nodes import (Default, Define, If, Label, Node, PersistentDefault, PyCode,
                                 PythonLine, ScriptFile)
from engine.script.points import PointsChange, PointsDecl
from engine.script.pycheck import parse_tree
from engine.script.routes import PERSISTENT_VIEWS
from engine.script.suggest import suggest
from engine.script.words import ENGINE_NAMES

IMPORT_RE = re.compile(r"\bimport\b")

KIND_EXEC = "exec"              # a $ line
KIND_CONDITION = "condition"    # an if/elif condition
KIND_VALUE = "value"            # a define, default, or persistent default value (uses only)

# The roots whose ``<root>.<attr>`` uses the walk collects (F12; F22 adds "points"; F21
# "codex").
ROOTS: tuple[str, ...] = ("persistent", "points", "codex")
CODEX = "codex"
CODEX_ATTRS: tuple[str, ...] = ("tips", "items")      # F21: what codex has (E255)
POINTS = "points"
HIGHEST = "highest"               # points.highest(...) is a method, not a meter read
RANK = "rank"                     # F62: so is points.rank(...) (meterranks.py checks its uses)
PERSISTENT = "persistent"
READ = "read"
WRITE = "write"
CHANGE = "change"                 # F19: a method that changes the value, or an item set/del
_ATTR_CALLS = frozenset(("setattr", "delattr"))
# F19 (04 §6.3): ``<root>.<attr>.<m>`` with ``m`` here changes the value in place.
MUTATORS: frozenset[str] = frozenset((
    "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse", "update",
    "setdefault", "popitem", "__setitem__", "__delitem__", "__iadd__"))

Place = tuple[ScriptFile, int]

# A parsed piece costs about as much as this many skipped ones (``iter_check_all``'s yields).
PARSE_WEIGHT = 8

# Nodes whose body is a scope of its own; only their parts listed in ``_outer_parts`` run in
# the piece's scope.
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda, ast.ListComp,
           ast.SetComp, ast.DictComp, ast.GeneratorExp)


@dataclass(slots=True, frozen=True)
class Piece:
    """One piece of author Python with its place: ``stmt`` is the first line of its logical
    line (SR-F02-68), ``kind`` ``KIND_EXEC`` or ``KIND_CONDITION``. ``meter`` (F22): the
    meter a ``points`` line's amount belongs to."""

    file: ScriptFile
    stmt: int
    py: PyCode
    kind: str
    meter: str | None = None


@dataclass(slots=True, frozen=True, order=True)
class AttrUse:
    """One ``<root>.<attr>`` use in a piece: its line and column in the piece's tree (line 1
    is the piece's first line), the root, the attribute, and ``READ`` or ``WRITE``."""

    line: int
    column: int
    root: str
    name: str
    kind: str


@dataclass(slots=True)
class Scan:
    """What one walk over a piece's tree found. ``bindings``: the names bound at the top
    level as ``(line, column, name)`` in walk order (``first_binding`` sorts them).
    ``imports``: every ``import``/``from … import``, anywhere. ``shuffles``: the top-level
    expression statements that call ``dice.shuffle``. ``uses``: the root uses (when the
    walk was given roots), anywhere in the tree, in walk order."""

    bindings: list[tuple[int, int, str]] = field(default_factory=list)
    imports: list[ast.Import | ast.ImportFrom] = field(default_factory=list)
    shuffles: list[ast.Call] = field(default_factory=list)
    uses: list[AttrUse] = field(default_factory=list)

    def first_import(self) -> ast.Import | ast.ImportFrom | None:
        if not self.imports:
            return None
        return min(self.imports, key=lambda node: (node.lineno, node.col_offset))

    def first_binding(self, wanted: Callable[[str], bool]) -> tuple[int, int, str] | None:
        """The first top-level binding in source order whose name is ``wanted``."""
        found = [item for item in self.bindings if wanted(item[2])]
        return min(found) if found else None


def _outer_parts(node: ast.AST) -> list[ast.AST]:
    """The parts of a scope node that run in the enclosing scope."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = node.args
        parts: list[ast.AST] = [*node.decorator_list, *args.defaults,
                                *(d for d in args.kw_defaults if d is not None)]
        parts += [a.annotation for a in (*args.posonlyargs, *args.args, *args.kwonlyargs,
                                         args.vararg, args.kwarg)
                  if a is not None and a.annotation is not None]
        if node.returns is not None:
            parts.append(node.returns)
        return parts
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    if isinstance(node, ast.Lambda):
        args = node.args
        return [*args.defaults, *(d for d in args.kw_defaults if d is not None)]
    return [node.generators[0].iter]                     # a comprehension


def _is_shuffle(node: ast.AST) -> bool:
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return False
    func = node.value.func
    return (isinstance(func, ast.Attribute) and func.attr == "shuffle"
            and isinstance(func.value, ast.Name) and func.value.id == "dice")


def _inner(node: ast.AST, roots: tuple[str, ...]) -> tuple[str, str] | None:
    """``(root, attr)`` when ``node`` is ``<root>.<attr>``."""
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id in roots):
        return node.value.id, node.attr
    return None


def _root_use(node: ast.AST, roots: tuple[str, ...]) -> AttrUse | None:
    """The root use ``node`` is, if any: ``<root>.<attr>`` (Load → read; Store, Del → write)
    or ``setattr``/``delattr(<root>, "<attr>", …)`` (write). F19 (04 §6.3): ``<root>.<attr>``
    followed by a ``MUTATORS`` attribute, or subscripted in a Store or Del, is a change of
    ``<attr>`` (the inner attribute is still visited, and stays a read). ``_`` attributes
    aren't uses."""
    if isinstance(node, ast.Attribute):
        value = node.value
        if isinstance(value, ast.Name) and value.id in roots:
            name, root = node.attr, value.id
            kind = READ if isinstance(node.ctx, ast.Load) else WRITE
        else:
            inner = _inner(value, roots) if node.attr in MUTATORS else None
            if inner is None:
                return None
            (root, name), kind = inner, CHANGE
    elif isinstance(node, ast.Subscript):
        inner = _inner(node.value, roots) if isinstance(node.ctx, (ast.Store, ast.Del)) else None
        if inner is None:
            return None
        (root, name), kind = inner, CHANGE
    elif isinstance(node, ast.Call):
        func, args = node.func, node.args
        if not (isinstance(func, ast.Name) and func.id in _ATTR_CALLS and len(args) >= 2
                and isinstance(args[0], ast.Name) and args[0].id in roots
                and isinstance(args[1], ast.Constant) and type(args[1].value) is str):
            return None
        name, root, kind = args[1].value, args[0].id, WRITE
    else:
        return None
    if name.startswith("_"):
        return None
    return AttrUse(node.lineno, node.col_offset, root, name, kind)


def scan(tree: ast.AST, roots: tuple[str, ...] = ()) -> Scan:
    """One iterative walk over ``tree`` (no recursion, SEC-F02-05). Each node is visited
    once, with ``top`` True while it runs in the piece's own scope. With ``roots``, every
    use of one of them (``_root_use``) is collected too, at any depth."""
    found = Scan()
    bindings = found.bindings
    uses = found.uses
    # The outer parts of the top-level scope nodes, walked once with top=True; the walk of
    # the scope's inside skips them.
    outside: set[int] = set()
    stack: list[tuple[ast.AST, bool]] = [(tree, True)]
    while stack:
        node, top = stack.pop()
        if not top and id(node) in outside:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.imports.append(node)
        if roots and isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
            use = _root_use(node, roots)
            if use is not None:
                uses.append(use)
        children: list[tuple[ast.AST, bool]]
        if top and isinstance(node, _SCOPES):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings.append((node.lineno, node.col_offset, node.name))
            outer = _outer_parts(node)
            outside.update(id(part) for part in outer)
            children = [(part, True) for part in outer]
            children += [(child, False) for child in ast.iter_child_nodes(node)
                         if id(child) not in outside]
        else:
            if top:
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    bindings.append((node.lineno, node.col_offset, node.id))
                elif isinstance(node, ast.ExceptHandler) and node.name is not None:
                    bindings.append((node.lineno, node.col_offset, node.name))
                elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name is not None:
                    bindings.append((node.lineno, node.col_offset, node.name))
                elif isinstance(node, ast.MatchMapping) and node.rest is not None:
                    bindings.append((node.lineno, node.col_offset, node.rest))
                elif _is_shuffle(node):
                    found.shuffles.append(node.value)  # type: ignore[attr-defined]
            children = [(child, top) for child in ast.iter_child_nodes(node)]
            if isinstance(node, ast.AnnAssign) and node.value is None:
                # ``x: int`` binds nothing; its annotation still runs.
                children = [(node.annotation, top)]
            elif isinstance(node, ast.TypeAlias):
                # ``type T = …`` binds T; its value and parameters are a scope of their own.
                children = [(node.name, top), (node.value, False),
                            *((param, False) for param in node.type_params)]
        stack.extend(reversed(children))
    return found


def parse(py: PyCode) -> ast.AST | None:
    """The piece's tree under F02's compile rules (``pycheck.parse_tree``), or None if it
    can't be built (it compiled at load, so only pathological nesting gets here)."""
    return parse_tree(py.source, py.mode)


def needs_parse(py: PyCode, watched: frozenset[str] | set[str]) -> bool:
    """§6.2's prefilter: True if the piece may bind a watched name, import, or call
    ``dice.shuffle``."""
    names = py.code.co_names  # type: ignore[union-attr]
    if not watched.isdisjoint(names):
        return True
    if any(name.startswith("_") for name in names):
        return True
    return IMPORT_RE.search(py.source) is not None


def mentions(py: PyCode, roots: tuple[str, ...]) -> bool:
    """True if a root is among the names of the piece's code or of any code nested in it
    (a lambda's ``persistent`` is a name of the lambda's code, not the piece's)."""
    if not roots or py.code is None:
        return False
    stack = [py.code]
    while stack:
        code = stack.pop()
        names = code.co_names
        if any(root in names for root in roots):
            return True
        stack.extend(c for c in code.co_consts if isinstance(c, CodeType))
    return False


# --- Message args ------------------------------------------------------------------------------

def _dotted_last(module: str) -> str:
    return module.rsplit(".", 1)[-1]


def e88_args(node: ast.Import | ast.ImportFrom) -> tuple[str, str, str | None]:
    """E88's ``(define name, module name, "then" text or None)`` for one import (G10, drafted
    past ``02`` §5.1's three forms):

    - ``import math`` → ``define math = module("math")``;
    - ``import a.b as c`` → ``define c = module("a.b")``;
    - ``import a.b`` → ``define b = module("a.b")``, then ``b`` instead of ``a.b``;
    - ``from a import b`` → ``define a = module("a")``, then ``a.b``; ``from a.b import c``
      → ``define b = module("a.b")``, then ``b.c``; ``from a import *`` adds nothing;
    - a relative import (``from . import x``) → the plain example, ``math``.

    The first alias of the statement is used."""
    if isinstance(node, ast.Import):
        alias = node.names[0]
        if alias.asname is not None:
            return alias.asname, alias.name, None
        if "." not in alias.name:
            return alias.name, alias.name, None
        last = _dotted_last(alias.name)
        return last, alias.name, f"{last} instead of {alias.name}"
    if node.level or not node.module:
        return "math", "math", None
    last = _dotted_last(node.module)
    alias = node.names[0]
    if alias.name == "*":
        return last, node.module, None
    return last, node.module, f"{last}.{alias.name}"


def define_value(define: Define | None) -> tuple[str | None, bool]:
    """E87's facts about a define: its value as written (one line of at most
    ``VALUE_ECHO_MAX_CHARS`` characters, comments outside the value left out; else None,
    shown as ``…``), and whether it is a ``Character(...)`` call."""
    if define is None:
        return None, False
    tree = parse(define.value)
    if not isinstance(tree, ast.Expression):
        return None, False
    body = tree.body
    is_character = (isinstance(body, ast.Call) and isinstance(body.func, ast.Name)
                    and body.func.id == "Character")
    written = ast.get_source_segment(define.value.source, body)
    if not written or "\n" in written or len(written) > VALUE_ECHO_MAX_CHARS:
        return None, is_character
    return written, is_character


def w05_args(call: ast.Call) -> tuple[str | None]:
    """W05's argument: the list's name when the call's one argument is a plain name."""
    args = call.args
    if len(args) == 1 and not call.keywords and isinstance(args[0], ast.Name):
        return (args[0].id,)
    return (None,)


# --- The pass ----------------------------------------------------------------------------------

def iter_pieces(nodes: Iterable[Node], *, values: bool = False) -> Iterator[Piece]:
    """Every compiled ``$`` line and ``if``/``elif`` (F07: menu choice) condition (F22: a
    ``points`` line's amount, as a condition with its meter; F23: each ``minigame``
    argument's value, as a condition; F37: an achievement's ``when``, at the top level) inside
    the labels, in reading order (pre-order within a label). Pieces with an error of their own
    (no ``code``) are left out. With ``values`` (F12), the value of every define, default,
    and persistent default joins in reading order too, as ``KIND_VALUE`` (root uses only)."""
    for node in nodes:
        if values and isinstance(node, (Define, Default, PersistentDefault)):
            if node.value.code is not None:
                yield Piece(node.file, node.line, node.value, KIND_VALUE)
            continue
        if isinstance(node, AchievementDecl):               # F37: a when condition
            if node.when_py is not None and node.when_py.code is not None:
                yield Piece(node.file, node.line, node.when_py, KIND_CONDITION)
            continue
        if not isinstance(node, Label):
            continue
        for stmt, _ in walk_block(node.block):
            if isinstance(stmt, PythonLine):
                if stmt.py.code is not None:
                    yield Piece(stmt.file, stmt.line, stmt.py, KIND_EXEC)
            elif isinstance(stmt, If):
                for branch in stmt.branches:
                    condition = branch.condition
                    if condition is not None and condition.code is not None:
                        yield Piece(stmt.file, branch.line, condition, KIND_CONDITION)
            elif isinstance(stmt, Menu):                    # F07: choice conditions
                for choice in stmt.choices:
                    condition = choice.condition
                    if condition is not None and condition.code is not None:
                        yield Piece(stmt.file, choice.line, condition, KIND_CONDITION)
            elif isinstance(stmt, PointsChange):            # F22: the amount
                if stmt.amount.code is not None:
                    yield Piece(stmt.file, stmt.line, stmt.amount, KIND_CONDITION, stmt.name)
            elif isinstance(stmt, Minigame):                # F23: each argument's value
                for arg in stmt.args:
                    if arg.value.code is not None:
                        yield Piece(stmt.file, stmt.line, arg.value, KIND_CONDITION)


@dataclass(slots=True)
class Defines:
    """The define names (``Collected.define_defs``: name → places in reading order) and
    their first ``Define`` nodes, for E87's place, value, and form."""

    places: Mapping[str, Sequence[Place]]
    nodes: Mapping[str, Define]
    _facts: dict[str, tuple[str | None, bool]] = field(default_factory=dict)

    @classmethod
    def from_nodes(cls, places: Mapping[str, Sequence[Place]],
                   nodes: Iterable[Node]) -> "Defines":
        first: dict[str, Define] = {}
        for node in nodes:
            if isinstance(node, Define):
                first.setdefault(node.name, node)
        return cls(places, first)

    def e87_args(self, name: str) -> tuple:
        file, line = self.places[name][0]
        node = self.nodes.get(name)
        if node is not None and (node.file is not file or node.line != line):
            node = None
        facts = self._facts.get(name)
        if facts is None:
            facts = self._facts[name] = define_value(node)
        value, is_character = facts
        return name, (file.ref, line), value, is_character


@dataclass(slots=True)
class RootUses:
    """The root uses of a whole story, per root: ``reads`` maps each read name to its first
    use ``(file ref, line)`` in reading order; ``writes`` holds every written name."""

    roots: tuple[str, ...] = ROOTS
    reads: dict[str, dict[str, tuple[str, int]]] = field(default_factory=dict)
    writes: dict[str, set[str]] = field(default_factory=dict)

    def add(self, piece: Piece, uses: Iterable[AttrUse]) -> None:
        """Record one piece's uses (in source order within the piece)."""
        for use in sorted(uses):
            if use.kind == READ:
                place = (piece.file.ref, piece.py.line + use.line - 1)
                self.reads.setdefault(use.root, {}).setdefault(use.name, place)
            elif use.kind == WRITE:                         # F19: CHANGE isn't collected
                self.writes.setdefault(use.root, set()).add(use.name)

    def reads_of(self, root: str) -> dict[str, tuple[str, int]]:
        return dict(self.reads.get(root, {}))

    def writes_of(self, root: str) -> frozenset[str]:
        return frozenset(self.writes.get(root, ()))


def _verdict(piece: Piece, found: Scan,
             defines: Defines) -> tuple[Diagnostic | None, ScriptWarning | None]:
    """The error (E88, E87, E62, E63) and W05 of one scanned ``$`` line or condition."""
    py = piece.py
    error = None
    first_import = found.first_import() if piece.kind == KIND_EXEC else None
    if first_import is not None:
        error = Diagnostic("E88", piece.file, py.line + first_import.lineno - 1, None,
                           e88_args(first_import), stmt=piece.stmt)
    else:
        places = defines.places

        def wanted(name: str) -> bool:
            return name in places or name in ENGINE_NAMES or name.startswith("_")

        hit = found.first_binding(wanted)
        if hit is not None:
            line, _, name = hit
            if name in places:
                code, args = "E87", defines.e87_args(name)
            elif name in ENGINE_NAMES:
                code, args = "E62", (name,)
            else:
                code, args = "E63", (name,)
            error = Diagnostic(code, piece.file, py.line + line - 1, None, args,
                               stmt=piece.stmt)
    warning = None
    if piece.kind == KIND_EXEC and found.shuffles:
        call = found.shuffles[0]
        warning = ScriptWarning(format_message("W05", w05_args(call)), code="W05",
                                file=piece.file.ref, line=py.line + call.lineno - 1)
    return error, warning


def meter_error(piece: Piece, uses: Iterable[AttrUse],
                meters: frozenset[str]) -> Diagnostic | None:
    """F22 (07 I-5): E234 for the first ``points.<name>`` write in source order, else E233
    for the piece's own meter (a ``points`` line) or the first ``points.<name>`` read that
    names no declared meter."""
    py = piece.py
    found = sorted(use for use in uses if use.root == POINTS)

    def at(line: int, code: str, args: tuple) -> Diagnostic:
        return Diagnostic(code, piece.file, line, None, args, stmt=piece.stmt)

    for use in found:
        if use.kind == WRITE:
            return at(py.line + use.line - 1, "E234", (use.name,))
    meter = piece.meter
    if meter is not None and meter not in meters:
        return at(piece.stmt, "E233", (meter, suggest(meter, meters)))
    for use in found:
        if use.name not in (HIGHEST, RANK) and use.name not in meters:
            return at(py.line + use.line - 1, "E233", (use.name, suggest(use.name, meters)))
    return None


def view_error(piece: Piece, uses: Iterable[AttrUse],
               views: frozenset[str] = PERSISTENT_VIEWS) -> Diagnostic | None:
    """F19 (04 §6.3): E245 for the first ``persistent.<view>`` write or change in source
    order, where ``<view>`` is an engine view (``endings``, ``routes``)."""
    for use in sorted(uses):
        if use.root == PERSISTENT and use.kind != READ and use.name in views:
            return Diagnostic("E245", piece.file, piece.py.line + use.line - 1, None,
                              ("change", use.name), stmt=piece.stmt)
    return None


def codex_error(piece: Piece, uses: Iterable[AttrUse]) -> Diagnostic | None:
    """F21 (04 §6.2): E255 for the first ``codex`` use in source order that isn't a read of
    ``tips`` or ``items`` (module docstring)."""
    for use in sorted(uses):
        if use.root != CODEX or (use.kind == READ and use.name in CODEX_ATTRS):
            continue
        line = piece.py.line + use.line - 1
        if use.name in CODEX_ATTRS:
            args: tuple = ("change", use.name)
        else:
            args = ("unknown", use.name, suggest(use.name, CODEX_ATTRS))
        return Diagnostic("E255", piece.file, line, None, args, stmt=piece.stmt)
    return None


def use_error(piece: Piece, uses: Sequence[AttrUse], meters: frozenset[str] | None,
              views: frozenset[str]) -> Diagnostic | None:
    """The root-use error of a piece without an error of its own, in F22's per-piece order
    with F19's and F21's: E234, E245, E255, E233 (``meters`` None: no meter checks)."""
    if meters is not None:
        for use in sorted(uses):
            if use.root == POINTS and use.kind == WRITE:
                return meter_error(piece, uses, meters)            # E234
    if views:
        error = view_error(piece, uses, views)
        if error is not None:
            return error
    error = codex_error(piece, uses)                               # F21: E255
    if error is not None:
        return error
    if meters is not None:
        return meter_error(piece, uses, meters)                    # E233
    return None


def check_piece(piece: Piece, defines: Defines, watched: frozenset[str], *,
                prefilter: bool = True) -> tuple[Diagnostic | None, ScriptWarning | None]:
    """The error (E88, E87, E62, E63) and W05 of one piece (none for a ``KIND_VALUE``)."""
    py = piece.py
    if piece.kind == KIND_VALUE or (prefilter and not needs_parse(py, watched)):
        return None, None
    tree = parse(py)
    if tree is None:
        return None, None
    return _verdict(piece, scan(tree), defines)


def iter_check_all(pieces: Iterable[Piece], defines: Defines,
                   report: Callable[[Diagnostic], object], *,
                   prefilter: bool = True, uses: RootUses | None = None,
                   meters: frozenset[str] | None = None,
                   views: frozenset[str] = PERSISTENT_VIEWS,
                   ) -> Generator[None, None, list[ScriptWarning]]:
    """Check every piece; errors go to ``report`` (the sink's ``add``), W05s are returned in
    reading order. ``prefilter=False`` parses every piece (AC-F03-25). With ``uses``, the
    root uses of every piece that ``mentions`` a root are recorded there (F12). With
    ``meters`` (F22), a piece without an error of its own gets ``meter_error`` (needs ``uses``
    for its ``points.<name>`` uses); F19's E245 for ``views`` joins that order
    (``use_error``: E234, E245, E233).

    Yields every ``IDENTITY_YIELD_ITEMS`` pieces (§6.2), and sooner when pieces are parsed:
    a parsed piece counts ``PARSE_WEIGHT`` (2,000 parses take 60–170 ms, so a slice would
    overshoot F02's frame budget; 250 take 7–20 ms). Yielding sooner changes no result
    (TR-F02-08)."""
    watched = frozenset(defines.places) | ENGINE_NAMES
    roots = uses.roots if uses is not None else ()
    found: list[ScriptWarning] = []
    work = 0
    for piece in pieces:
        checked = piece.kind != KIND_VALUE and (not prefilter or needs_parse(piece.py, watched))
        collect = bool(roots) and mentions(piece.py, roots)
        error: Diagnostic | None = None
        piece_uses: list[AttrUse] = []                      # not parsed: no root use
        if not checked and not collect:
            work += 1
        else:
            work += PARSE_WEIGHT
            tree = parse(piece.py)
            if tree is not None:
                result = scan(tree, roots if collect else ())
                piece_uses = result.uses
                if checked:
                    error, warning = _verdict(piece, result, defines)
                    if warning is not None:
                        found.append(warning)
                if collect:
                    uses.add(piece, piece_uses)  # type: ignore[union-attr]
        if error is None and (piece_uses or (meters is not None and piece.meter is not None)):
            error = use_error(piece, piece_uses, meters, views)  # E234, E245, E255, E233
        if error is not None:
            report(error)
        if work >= IDENTITY_YIELD_ITEMS:
            work = 0
            yield
    return found


@dataclass(slots=True)
class BindingsResult:
    errors: list[Diagnostic]
    warnings: list[ScriptWarning]
    uses: RootUses = field(default_factory=RootUses)


def check_all(nodes: Iterable[Node], define_places: Mapping[str, Sequence[Place]], *,
              prefilter: bool = True) -> BindingsResult:
    """``iter_check_all`` over the labels of ``nodes`` (and, for the root uses, their
    define, default, and persistent default values) in one go, keeping every error (no
    sink): for tests and tools. ``define_places`` is ``Collected.define_defs``."""
    nodes = list(nodes)
    errors: list[Diagnostic] = []
    uses = RootUses()
    meters = frozenset(name for node in nodes if isinstance(node, PointsDecl)
                       for name in node.names)
    job = iter_check_all(iter_pieces(nodes, values=True),
                         Defines.from_nodes(define_places, nodes), errors.append,
                         prefilter=prefilter, uses=uses, meters=meters)
    while True:
        try:
            next(job)
        except StopIteration as stop:
            return BindingsResult(errors, stop.value, uses)


__all__ = ["AttrUse", "BindingsResult", "CHANGE", "CODEX", "CODEX_ATTRS", "Defines", "IMPORT_RE", "KIND_CONDITION",
           "KIND_EXEC", "KIND_VALUE", "MUTATORS", "PARSE_WEIGHT", "Piece", "READ", "ROOTS",
           "RootUses", "Scan", "WRITE", "check_all", "check_piece", "codex_error", "define_value", "e88_args",
           "iter_check_all", "iter_pieces", "mentions", "meter_error", "needs_parse", "parse",
           "scan", "use_error", "view_error", "w05_args"]
