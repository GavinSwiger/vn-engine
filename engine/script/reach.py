"""What a scene needs before the story can get there, and scenes no playthrough can reach.

Why this module exists: an author who writes ``if has_key:`` before ``jump vault`` wants to
see, on the vault scene, that it needs ``has_key``, which scenes give and take it, and a
warning when the way in can never be taken (every scene that leads there has already set
``has_key = False``). The story map shows this for the chosen scene (``tools/check.py``
sends it as ``reach`` rows).

How (pure: nothing here runs author code):

- **Ways in.** Every ``jump``, ``call`` and choice that leads to a scene, with the
  conditions it sits under: each enclosing ``if``/``elif`` branch (an ``elif`` or ``else``
  also needs every earlier branch false) and the choice's own ``if``.
- **Watched variables.** Every name those conditions read. For each, the values it can hold
  are tracked as a small set of plain values (``True``, ``3``, ``"red"``…), or "anything"
  once the script does something this module can't follow (a computed value, a ``minigame
  … into`` it, a method call on it, more than ``VALUES_MAX`` values).
- **Walk.** From the starts (``start`` and every scene replay) with each watched variable's
  ``default``, every scene's lines run in order: ``$`` assignments of plain values (``=``,
  ``+=``, ``-=``…) change the sets; an ``if`` or a menu runs each block from the same values
  and joins them after; a ``call`` makes anything the called scenes may set "anything". A
  way in is taken with the values at its line, and only when its conditions can be true
  for some of them; the scene it leads to starts with the join of every way taken. This
  repeats until nothing changes (the sets only grow, and are capped, so it ends).
- **A condition** is checked against every mix of its variables' values (at most
  ``MIXES_MAX``); one this module can't read (a function call, ``persistent.x``, a variable
  set to "anything") counts as possible. So a warning is only given when the script shows,
  in plain values, that a way can never be taken.

``analyze(program, starts)`` returns a ``SceneReach`` for each scene with a condition on a
way in, or that can't be reached although a ``jump``, ``call`` or choice leads to it
(scenes nothing leads to at all are lint's W237).
"""

from __future__ import annotations

import ast
import itertools
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from engine.script.choicecheck import CheckRoll
from engine.script.choicepresent import reaction_text
from engine.script.menu import Menu
from engine.script.minigame import Minigame
from engine.script.nodes import Call, Default, Define, If, Jump, PythonLine, Return, Statement
from engine.script.program import Program

VALUES_MAX: Final = 8          # more than this many values: "anything"
MIXES_MAX: Final = 256         # more mixes than this: the condition counts as possible
TEXT_MAX: Final = 80           # a condition or line as shown
WHY_WAYS_MAX: Final = 3        # ways named in a scene's warning
UNREACHED_SOURCE: Final = "{scene} itself can't be reached"

ANY: Final = None              # a variable that can hold anything (this module can't tell)


class _Unknown(Exception):
    """A condition (or value) this module can't work out."""


# --- Results ---------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Way:
    """One way into ``dst``: from scene ``src`` by a ``kind`` link (``jump``, ``call``,
    ``menu``) at ``file``:``line``, inside ``choice`` (its text, or None). ``needs``: the
    conditions it sits under, as written (``not …`` for a branch that needs one false).
    ``possible``: False when it can never be taken, with ``why``."""

    src: str
    dst: str
    kind: str
    file: str
    line: int
    choice: str | None
    needs: tuple[str, ...]
    possible: bool = True
    why: str | None = None


@dataclass(frozen=True, slots=True)
class Setter:
    """A line that sets watched variable ``var``: in scene ``scene`` (None: a ``default``)
    at ``file``:``line``; ``text`` is the line as written."""

    var: str
    scene: str | None
    file: str
    line: int
    text: str


@dataclass(frozen=True, slots=True)
class SceneReach:
    """For scene ``scene``: its ``ways`` in (every one when any has a condition or can't be
    taken), the ``setters`` of the variables their conditions read, and ``blocked``: the
    warning when no playthrough can get there (None: it can be reached, or can't be told)."""

    scene: str
    ways: tuple[Way, ...]
    setters: tuple[Setter, ...]
    blocked: str | None = None


# --- Values ----------------------------------------------------------------------------------

Values = frozenset | None                       # a set of plain values, or ANY
State = dict[str, Values]


def _join_values(a: Values, b: Values) -> Values:
    if a is ANY or b is ANY:
        return ANY
    joined = a | b
    return ANY if len(joined) > VALUES_MAX else joined


def _join(a: State | None, b: State | None) -> State | None:
    if a is None:
        return None if b is None else dict(b)
    if b is None:
        return dict(a)
    return {name: _join_values(a.get(name, ANY), b.get(name, ANY)) for name in a.keys() | b}


def _plain(node: ast.AST) -> object:
    """A plain value written in the script (``True``, ``3``, ``-1``, ``"red"``), else
    ``_Unknown``. Read by ``_eval`` with no variables: nothing runs."""
    value = _eval(node, {})
    try:
        hash(value)
    except TypeError:
        raise _Unknown from None
    return value


def _show(value: object) -> str:
    return repr(value) if isinstance(value, str) else str(value)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX - 1] + "…"


# --- Conditions ------------------------------------------------------------------------------

_COMPARE: Final = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b, ast.IsNot: lambda a, b: a is not b,
}
_ARITH: Final = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                 ast.Mult: lambda a, b: a * b}
NUMBER_MAX: Final = 10 ** 12   # arithmetic on numbers past this counts as unknown


def _eval(node: ast.AST, values: Mapping[str, object]) -> object:
    """``node`` with the variables' ``values``; ``_Unknown`` for anything else."""
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in values:
            return values[node.id]
        if node.id in ("True", "False", "None"):
            return {"True": True, "False": False, "None": None}[node.id]
        raise _Unknown
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return tuple(_eval(item, values) for item in node.elts)
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, values)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub) and isinstance(operand, (int, float)):
            return -operand
        raise _Unknown
    if isinstance(node, ast.BoolOp):
        result: object = isinstance(node.op, ast.And)
        for item in node.values:
            result = _eval(item, values)
            if isinstance(node.op, ast.And) and not result:
                return result
            if isinstance(node.op, ast.Or) and result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, values)
        for op, right_node in zip(node.ops, node.comparators):
            rule = _COMPARE.get(type(op))
            if rule is None:
                raise _Unknown
            right = _eval(right_node, values)
            try:
                if not rule(left, right):
                    return False
            except TypeError:
                raise _Unknown from None
            left = right
        return True
    if isinstance(node, ast.BinOp) and type(node.op) in _ARITH:
        return _arith(type(node.op), _eval(node.left, values), _eval(node.right, values))
    raise _Unknown


def _arith(op: type, a: object, b: object) -> object:
    """``a op b`` for plain numbers only (no string or list growth), within ``NUMBER_MAX``."""
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) <= NUMBER_MAX
               for v in (a, b)):
        raise _Unknown
    return _ARITH[op](a, b)


@dataclass(frozen=True, slots=True)
class _Guard:
    """One condition a way sits under: its parsed ``tree``, the names it reads, ``want``
    (True: it must hold; False: it must not) and its text as written."""

    tree: ast.Expression | None
    names: frozenset[str]
    want: bool
    source: str

    @property
    def text(self) -> str:
        if self.want:
            return _short(self.source)
        simple = self.tree is not None and isinstance(self.tree.body, ast.Name)
        return _short(f"not {self.source}" if simple else f"not ({self.source})")


def _guard(source: str, want: bool) -> _Guard:
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return _Guard(None, frozenset(), want, source)
    names = frozenset(n.id for n in ast.walk(tree) if isinstance(n, ast.Name))
    return _Guard(tree, names, want, source)


def _possible(guards: Sequence[_Guard], state: State) -> bool:
    """Some mix of the variables' values makes every guard come out as it must (a guard
    this module can't read counts as possible)."""
    if not guards:
        return True
    if any(g.tree is None for g in guards):
        return True
    names = sorted(set().union(*(g.names for g in guards)) & state.keys())
    pools = []
    for name in names:
        values = state[name]
        if values is ANY:
            return True
        pools.append(sorted(values, key=repr))
    count = 1
    for pool in pools:
        count *= max(1, len(pool))
    if count > MIXES_MAX or any(not pool for pool in pools):
        return True
    for mix in itertools.product(*pools):
        values = dict(zip(names, mix))
        try:
            if all(bool(_eval(g.tree, values)) == g.want for g in guards):
                return True
        except _Unknown:
            return True
    return False


def _why(guards: Sequence[_Guard], state: State) -> str:
    """Why ``guards`` can't all hold: the watched variables they read and their values
    ("has_key is always False there")."""
    parts = []
    for name in sorted(set().union(*(g.names for g in guards)) & state.keys()):
        values = state[name]
        if values is ANY:
            continue
        shown = sorted((_show(v) for v in values))
        if not shown:
            continue
        parts.append(f"{name} is always {shown[0]} there" if len(shown) == 1
                     else f"{name} is only {', '.join(shown[:-1])} or {shown[-1]} there")
    return "; ".join(parts) if parts else "it can never be true there"


# --- The walk --------------------------------------------------------------------------------

@dataclass(slots=True)
class _Link:
    src: str
    dst: str
    kind: str
    file: str
    line: int
    choice: str | None
    guards: tuple[_Guard, ...]


@dataclass(slots=True)
class _Walk:
    program: Program
    watched: frozenset[str]
    calls_set: Mapping[str, frozenset[str]]
    setters: dict[str, list[Setter]] = field(default_factory=dict)
    links: list[tuple[_Link, State]] = field(default_factory=list)
    record: bool = False

    def scene(self, name: str, state: State) -> None:
        label = self.program.labels.get(name)
        if label is not None:
            self.block(name, label.block, dict(state), (), None)

    def block(self, scene: str, block: Sequence[Statement], state: State | None,
              guards: tuple[_Guard, ...], choice: str | None) -> State | None:
        """Run ``block`` from ``state``; the state after it (None: no path gets past)."""
        for stmt in block:
            if state is None:
                return None
            state = self.statement(scene, stmt, state, guards, choice)
        return state

    def statement(self, scene: str, stmt: Statement, state: State,
                  guards: tuple[_Guard, ...], choice: str | None) -> State | None:
        if isinstance(stmt, (Jump, Call)):
            kind = "call" if isinstance(stmt, Call) else ("menu" if choice is not None
                                                          else "jump")
            link = _Link(scene, stmt.target, kind, stmt.file.ref, stmt.line, choice, guards)
            self.links.append((link, dict(state)))
            if isinstance(stmt, Jump):
                return None
            after = dict(state)
            for name in self.calls_set.get(stmt.target, frozenset()):
                after[name] = ANY
            return after
        if isinstance(stmt, Return):
            return None
        if isinstance(stmt, If):
            out: State | None = None
            earlier: list[_Guard] = []
            has_else = False
            for branch in stmt.branches:
                if branch.condition is None:
                    has_else = True
                    here = tuple(_guard(g.source, False) for g in earlier)
                else:
                    here = tuple(_guard(g.source, False) for g in earlier) + (
                        _guard(branch.condition.source, True),)
                    earlier.append(_guard(branch.condition.source, True))
                out = _join(out, self.block(scene, branch.block, dict(state),
                                            guards + here, choice))
            return _join(out, state) if not has_else else out
        if isinstance(stmt, CheckRoll):                 # F59: success or failure, no guard
            out = None
            for branch in stmt.branches:
                out = _join(out, self.block(scene, branch.block, dict(state), guards, choice))
            return out
        if isinstance(stmt, Menu):
            out = None
            for item in stmt.choices:
                here = guards + ((_guard(item.condition.source, True),)
                                 if item.condition is not None else ())
                out = _join(out, self.block(scene, item.block, dict(state), here, item.text))
            option = stmt.present                       # F64: one branch per reaction
            if option is not None:
                here = guards + ((_guard(option.condition.source, True),)
                                 if option.condition is not None else ())
                for reaction in option.reactions:
                    out = _join(out, self.block(scene, reaction.block, dict(state), here,
                                                reaction_text(reaction.item)))
            return out
        if isinstance(stmt, PythonLine):
            return self.python(scene, stmt, state)
        if isinstance(stmt, Minigame) and stmt.target in self.watched:
            self.set_any(state, stmt.target, scene, stmt, f"minigame {stmt.name} into "
                                                          f"{stmt.target}")
        return state

    def set_any(self, state: State, name: str, scene: str, stmt: Statement, text: str) -> None:
        state[name] = ANY
        self.note(name, scene, stmt, text)

    def note(self, name: str, scene: str | None, node: object, text: str) -> None:
        if self.record:
            rows = self.setters.setdefault(name, [])
            row = Setter(name, scene, node.file.ref, node.line, _short(text))
            if row not in rows:
                rows.append(row)

    def python(self, scene: str, stmt: PythonLine, state: State) -> State:
        try:
            tree = ast.parse(stmt.py.source, mode="exec")
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return state
        for node in tree.body:
            text = ast.get_source_segment(stmt.py.source, node) or stmt.py.source
            if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name)
                                                     for t in node.targets):
                for target in node.targets:
                    if target.id in self.watched:
                        try:
                            state[target.id] = frozenset({_plain(node.value)})
                        except _Unknown:
                            state[target.id] = ANY
                        self.note(target.id, scene, stmt, text)
                continue
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                    and node.target.id in self.watched:
                name = node.target.id
                state[name] = self.step(state.get(name, ANY), node)
                self.note(name, scene, stmt, text)
                continue
            for name in _written(node) & self.watched:
                self.set_any(state, name, scene, stmt, text)
        return state

    @staticmethod
    def step(values: Values, node: ast.AugAssign) -> Values:
        rule = _ARITH.get(type(node.op))
        if values is ANY or rule is None:
            return ANY
        try:
            amount = _plain(node.value)
            out = frozenset(_arith(type(node.op), v, amount) for v in values)
        except _Unknown:
            return ANY
        return ANY if len(out) > VALUES_MAX else out


def _written(node: ast.AST) -> set[str]:
    """Names ``node`` may change: stores, ``del``, and a method called on a name."""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            found.add(sub.id)
        elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and isinstance(sub.func.value, ast.Name):
            found.add(sub.func.value.id)
        elif isinstance(sub, (ast.Global, ast.Nonlocal)):
            found.update(sub.names)
    return found


def _guards_of(program: Program) -> list[_Link]:
    """Every way, with its guards, without values (for the watched names and calls)."""
    walk = _Walk(program, frozenset(), {})
    for name in program.labels:
        walk.scene(name, {})
    return [link for link, _state in walk.links]


def _sets_in(program: Program, watched: frozenset[str]) -> dict[str, frozenset[str]]:
    """For each scene, the watched names it (or a scene it calls or jumps to) may set."""
    direct: dict[str, set[str]] = {}
    for name, label in program.labels.items():
        found: set[str] = set()
        for stmt in _statements(label.block):
            if isinstance(stmt, PythonLine):
                try:
                    found |= _written(ast.parse(stmt.py.source, mode="exec"))
                except (SyntaxError, ValueError, RecursionError, MemoryError):
                    continue
            elif isinstance(stmt, Minigame) and stmt.target:
                found.add(stmt.target)
        direct[name] = found & watched
    links = {name: {s.target for s in _statements(label.block)
                    if isinstance(s, (Jump, Call))}
             for name, label in program.labels.items()}
    out: dict[str, frozenset[str]] = {}
    for name in program.labels:
        seen, todo, sets = {name}, [name], set()
        while todo:
            at = todo.pop()
            sets |= direct.get(at, set())
            for nxt in links.get(at, ()):
                if nxt not in seen and nxt in program.labels:
                    seen.add(nxt)
                    todo.append(nxt)
        out[name] = frozenset(sets)
    return out


def _statements(block: Iterable[Statement]) -> Iterable[Statement]:
    todo = list(block)[::-1]
    while todo:
        stmt = todo.pop()
        yield stmt
        if isinstance(stmt, Menu):
            for item in reversed(stmt.choices):
                todo.extend(reversed(item.block))
        else:
            for inner in reversed(stmt.blocks()):
                todo.extend(reversed(inner))


def _first_values(program: Program, watched: frozenset[str], walk: _Walk) -> State:
    """Each watched name's values at a start: its ``default`` (or a ``define``), else ANY."""
    state: State = {name: ANY for name in watched}
    for node in (*program.defines, *program.defaults):
        if node.name not in watched:
            continue
        try:
            value = _plain(ast.parse(node.value.source.strip(), mode="eval").body)
            state[node.name] = frozenset({value})
        except (_Unknown, SyntaxError, ValueError, RecursionError, MemoryError):
            state[node.name] = ANY
        if isinstance(node, Default):
            walk.note(node.name, None, node, f"default {node.name} = "
                                             f"{node.value.source.strip()}")
        elif isinstance(node, Define):
            walk.note(node.name, None, node, f"define {node.name} = "
                                             f"{node.value.source.strip()}")
    return state


def analyze(program: Program, starts: Iterable[str]) -> dict[str, SceneReach]:
    """``SceneReach`` for every scene with a condition on a way in, or that no playthrough
    reaches although something leads to it."""
    starts = tuple(starts)
    plain_links = _guards_of(program)
    watched = frozenset(name for link in plain_links for g in link.guards for name in g.names)
    walk = _Walk(program, watched, _sets_in(program, watched) if watched else {})
    walk.record = True
    first = _first_values(program, watched, walk)
    entry: dict[str, State] = {}
    todo: list[str] = []
    for name in starts:
        if name in program.labels and name not in entry:
            entry[name] = dict(first)
            todo.append(name)
    taken: dict[tuple[str, str, int], State] = {}
    rounds = 0
    while todo and rounds < 50 * max(1, len(program.labels)):
        rounds += 1
        name = todo.pop()
        walk.links = []
        walk.scene(name, entry[name])
        for link, state in walk.links:
            key = (link.src, link.file, link.line)
            taken[key] = _join(taken.get(key), state)
            if not _possible(link.guards, state) or link.dst not in program.labels:
                continue
            joined = _join(entry.get(link.dst), state)
            if joined != entry.get(link.dst):
                entry[link.dst] = joined
                if link.dst not in todo:
                    todo.append(link.dst)
    ways_into: dict[str, list[Way]] = {}
    read_by: dict[str, set[str]] = {}
    for link in plain_links:
        if link.dst not in program.labels:
            continue
        state = taken.get((link.src, link.file, link.line))
        needs = tuple(g.text for g in link.guards)
        if state is None:
            way = Way(link.src, link.dst, link.kind, link.file, link.line, link.choice, needs,
                      False, UNREACHED_SOURCE.format(scene=link.src))
        elif not _possible(link.guards, state):
            way = Way(link.src, link.dst, link.kind, link.file, link.line, link.choice, needs,
                      False, _why(link.guards, state))
        else:
            way = Way(link.src, link.dst, link.kind, link.file, link.line, link.choice, needs)
        ways_into.setdefault(link.dst, []).append(way)
        for guard in link.guards:
            read_by.setdefault(link.dst, set()).update(guard.names)
    out: dict[str, SceneReach] = {}
    for scene, ways in ways_into.items():
        guarded = [w for w in ways if w.needs]
        blocked = None
        if scene not in entry and scene not in starts:
            impossible = [w for w in ways if not w.possible]
            if impossible and any(w.needs for w in impossible):
                reasons = [_reason(w) for w in impossible][:WHY_WAYS_MAX]
                blocked = "No playthrough can reach this scene. " + " ".join(reasons)
        if not guarded and blocked is None:
            continue
        read = sorted(read_by.get(scene, set()) & watched)
        setters = tuple(row for name in read for row in walk.setters.get(name, ()))
        out[scene] = SceneReach(scene, tuple(ways), setters, blocked)
    return out


def _reason(way: Way) -> str:
    """One sentence of a blocked scene's warning, for one way in."""
    if way.why == UNREACHED_SOURCE.format(scene=way.src):
        return f"From {way.src}: {way.why}."
    return f"From {way.src}, it needs {' and '.join(way.needs)}, but {way.why}."


__all__ = ["SceneReach", "Setter", "VALUES_MAX", "Way", "analyze"]
