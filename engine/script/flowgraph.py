"""The flowchart's graph, built at load from the script alone (F20 ``04-technical.md`` §4,
§5, §7.1; ``07`` I-1, I-13).

Why this module exists: the Flowchart page draws the story as a map of chapters, author-
marked scenes, branching menus, endings, and F19 route gates. Which boxes exist and which
arrows join them is a pure function of the ``Program`` and ``FlowOptions`` (TR-F20-01), so it
is worked out once per load (load phase 6), never saved, and never depends on how the work
was sliced, on hash seeds, or on the clock.

**Nodes** (ids, 02 A6): ``start``, ``scene:<label>``, ``chapter:<name>``, ``menu:<sid>``,
``ending:<name>``, ``gate:<route>``. Each node but the start has an **anchor**: the statement
whose running reaches it (a scene's mark, which is its label's first statement; the
``chapter``, ``ending``, or ``menu:`` statement; a route label's first statement for its
gate, ordered before a scene or chapter anchored there). ``key`` is ``node_key(id)``.

**Edges** (§7.1 steps 2–6): every statement has successors by ``FLOW_RULES`` (the default:
the next statement, out of ``if`` and choice blocks, and a label's end acts as ``return``).
``reach(v)`` is the set of anchors first met on paths from ``v`` (and ``RET`` when a path
returns). A ``call`` is context sensitive: it gives the called label's first anchors, and,
only if the label can return, the anchors after the call. A ``RET`` reached in a label
resolves to the anchors after every call that can lead there by jumps (``frames``), so a scene
in a label called from three places links to the next node after each call, while a walk that
itself calls a helper resumes only after its own call. Menus with no mark are nodes under
``menus = "branching"`` when their choices lead to different definite anchors.

**How it is computed.** Runs of plain statements are collapsed onto the next statement that
matters. One iterative Tarjan walk (call edges included, so a called label's summary is final
before its callers) gives every vertex its reach set; a cycle through a ``call`` (recursion)
is solved by a local worklist fixpoint, which is exact, so no outer passes are needed. Return
targets are a worklist fixpoint over labels. Sets are frozensets shared when equal; every walk
uses explicit stacks or queues (SEC-F20-12(a)); the work is counted and capped
(``limits.FLOW_WORK_MAX``, E265's "too complex" form) and ``FlowGraphJob.step`` does at most
``units`` work units (one set union is never split, so a step passes ``units`` only when one
union alone is larger).

**Checks** (§7.1 step 10): E265 (whole game) and no graph when the nodes other than gates pass
``FLOW_NODES_MAX``, the edges ``FLOW_EDGES_MAX``, the persistent names (edge records, or node
keys plus chapter tombstones) ``FLOW_NAMES_MAX``, or the work ``FLOW_WORK_MAX``. Dev loads
also get W150 (an unreachable node), W151 (a statement whose rule is ``OPAQUE``), W152 (a
node menu's choice that is only ``{var}``), and W153 (``flowchart forget`` naming a label
with no nodes). A node whose key equals an earlier node's is dropped with one INFO record.

``FlowOptions`` lives here (``07`` I-1): ``app/loading.py`` builds it from ``[flowchart]`` and
``runtime/flowchart.py`` re-exports it with the graph types; ``app`` and ``ui`` never import
``engine.script``. ``FlowMark`` is re-exported from ``script/flowchart.py``.
"""

import hashlib
from collections import deque
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from engine.core.logsetup import get_logger
from engine.script import limits
from engine.script.diagnostics import Diagnostic, DiagnosticSink, ScriptWarning
from engine.script.flowchart import Flowchart, FlowMark
from engine.script.menu import Menu
from engine.script.messages import format_message
from engine.script.nodes import Call, Chapter, If, Jump, Label, Return, Say, Statement
from engine.script.program import Program
from engine.script.routes import Ending
from engine.script.startcheck import START_LABEL
from engine.script.texttags import NameMark, Span, TaggedText, VarMark

log = get_logger("script")

NodeKind = Literal["start", "chapter", "choice", "scene", "ending", "gate"]
Text = tuple[str | None, ...]            # plain parts; None = a {var} (word flowchart_var);
                                         # () = the kind word (flowchart_start, _choice)
MenusOption = Literal["branching", "all", "marked"]
MENUS: Final = ("branching", "all", "marked")
UNVISITED: Final = ("mystery", "hidden")
VAR_WORD: Final = "…"                    # flowchart_var's default (02 §3.7)


@dataclass(frozen=True)
class FlowOptions:
    """``[flowchart]`` as the graph and the page read it (02 §3.6). ``enabled`` False builds
    no graph (the marks are still checked, SR-F20-13)."""

    enabled: bool = True
    menus: MenusOption = "branching"
    unvisited: Literal["mystery", "hidden"] = "mystery"
    jump: bool = True

    @classmethod
    def from_config(cls, config: object) -> "FlowOptions":
        """From ``config.flowchart`` (``FlowchartConfig``, already checked by F01)."""
        menus = getattr(config, "menus", "branching")
        unvisited = getattr(config, "unvisited", "mystery")
        return cls(enabled=bool(getattr(config, "enabled", True)),
                   menus=menus if menus in MENUS else "branching",  # type: ignore[arg-type]
                   unvisited=unvisited if unvisited in UNVISITED  # type: ignore[arg-type]
                   else "mystery",
                   jump=bool(getattr(config, "jump", True)))


@dataclass(frozen=True, slots=True)
class FlowNode:
    """One box (04 §4). ``title`` is the box's own text (a chapter's or ending's title, without
    its heading; ``box_text`` joins them); ``anchor`` the anchor statement's sid (``""`` for
    the start); ``label`` the label holding it; ``chapter`` the nearest chapter node on the
    story-order tree above it; ``route`` the gate node of the innermost route it belongs to
    (PR-F20-12); ``order`` its place in story order."""

    id: str
    key: str
    kind: NodeKind
    name: str
    title: Text
    heading: str | None
    anchor: str
    label: str
    hidden: bool
    no_jump: bool
    chapter: int | None
    route: int | None
    order: int


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """An arrow. A choice edge holds every choice key leading to ``dst`` (script order) and
    its plain text; any other edge has the persistent ``record`` name ``src.key + dst.key``."""

    src: int
    dst: int
    choices: tuple[str, ...]
    texts: tuple[Text, ...]
    record: str | None


@dataclass(frozen=True, slots=True)
class FlowGraph:
    """The immutable graph (04 §4). ``anchors`` maps an anchor sid to its nodes (gates
    excluded), ``out``/``into`` give edge indexes per node, ``in_label`` the nodes written in
    a label (SR-F20-10: scene, chapters, choice menus)."""

    nodes: tuple[FlowNode, ...]
    edges: tuple[FlowEdge, ...]
    anchors: Mapping[str, tuple[int, ...]]
    by_id: Mapping[str, int]
    by_key: Mapping[str, int]
    out: tuple[tuple[int, ...], ...]
    into: tuple[tuple[int, ...], ...]
    records: frozenset[str]
    in_label: Mapping[str, tuple[int, ...]]


# --- Ids, keys, and text ---------------------------------------------------------------------

def node_key(node_id: str) -> str:
    """16 hex: ``blake2b(id utf-8, digest_size=8)``. The same id gives the same key in every
    process and version (SR-F20-06)."""
    data = node_id.encode("utf-8", "surrogatepass")
    return hashlib.blake2b(data, digest_size=8).hexdigest()


def plain_title(body: TaggedText) -> Text:
    """SR-F20-14: the text with every tag dropped, each ``{var}`` (F30: and ``{username}``)
    as None (the page shows ``flowchart_var``), ``{{`` already ``{``; neighbouring text parts
    joined. One pass."""
    parts: list[str | None] = []
    for piece in body.pieces:
        if isinstance(piece, Span):
            if parts and isinstance(parts[-1], str):
                parts[-1] += piece.text
            elif piece.text:
                parts.append(piece.text)
        elif isinstance(piece, (VarMark, NameMark)):
            parts.append(None)
    return tuple(parts)


def box_text(node: FlowNode) -> Text:
    """The box's text: ``"Heading: Title"`` for a chapter or ending with a heading (AC-F20-10),
    else the title (``()``: the kind word)."""
    if node.heading is not None and node.kind in ("chapter", "ending") and node.title:
        return (f"{node.heading}: {node.title[0]}", *node.title[1:])
    return node.title


def show_text(text: Text, *, var: str = VAR_WORD, empty: str = "") -> str:
    """A ``Text`` as shown: each None is ``var``; ``()`` is ``empty`` (the kind word)."""
    if not text:
        return empty
    return "".join(var if part is None else part for part in text)


def _var_only(text: Text) -> bool:
    return bool(text) and all(part is None or not part.strip() for part in text)


# --- Successor rules (§7.1 step 2) -----------------------------------------------------------

class _Ret:
    """A path returns: to the caller, or the story ends (F03: a label's end acts as return)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "RET"


RET: Final = _Ret()


@dataclass(frozen=True, slots=True)
class CallSucc:
    """``call target``: the called label, then ``then`` if it returns."""

    target: str
    then: "Statement | _Ret"


Succ = Statement | _Ret | CallSucc


class Walk:
    """What a ``FLOW_RULES`` row may ask: the statement after one (out of blocks; ``RET`` at
    a label's end), a label's first statement, a block's first statement."""

    __slots__ = ("_stmts", "_index", "_next", "_labels")

    def __init__(self, stmts: Sequence[Statement], index: Mapping[str, int],
                 nexts: Sequence[int], labels: Mapping[str, Label]) -> None:
        self._stmts = stmts
        self._index = index
        self._next = nexts
        self._labels = labels

    def next(self, stmt: Statement) -> "Statement | _Ret":
        at = self._next[self._index[stmt.sid]]
        return RET if at < 0 else self._stmts[at]

    def entry(self, label: str) -> "Statement | _Ret":
        node = self._labels.get(label)
        return node.block[0] if node is not None and node.block else RET

    def first(self, block: Sequence[Statement], stmt: Statement) -> "Statement | _Ret":
        """``block``'s first statement, or what follows ``stmt`` when it is empty."""
        return block[0] if block else self.next(stmt)


Rule = Callable[[Statement, Walk], Iterable[Succ]]
OPAQUE: Final = "OPAQUE"


def _rule_default(stmt: Statement, walk: Walk) -> Iterable[Succ]:
    return (walk.next(stmt),)


def _rule_if(stmt: If, walk: Walk) -> Iterable[Succ]:            # type: ignore[misc]
    out: list[Succ] = [walk.first(branch.block, stmt) for branch in stmt.branches]
    if not stmt.branches or stmt.branches[-1].keyword != "else":
        out.append(walk.next(stmt))
    return out


def _rule_menu(stmt: Menu, walk: Walk) -> Iterable[Succ]:        # type: ignore[misc]
    return [walk.first(choice.block, stmt) for choice in stmt.choices]


def _rule_jump(stmt: Jump, walk: Walk) -> Iterable[Succ]:        # type: ignore[misc]
    return (walk.entry(stmt.target),)


def _rule_call(stmt: Call, walk: Walk) -> Iterable[Succ]:        # type: ignore[misc]
    return (CallSucc(stmt.target, walk.next(stmt)),)


def _rule_return(stmt: Statement, walk: Walk) -> Iterable[Succ]:
    return (RET,)


def _rule_ending(stmt: Statement, walk: Walk) -> Iterable[Succ]:
    return ()                                                    # the story ends


# Statement type → its successors; a type not here has the default rule (the next
# statement). ``OPAQUE`` (none today, 02 A2): no successors, and W151 at the statement.
# ``labelgraph.LINK_RULES`` agrees on Jump and Call (F45 07 I-11; tested, no import).
FLOW_RULES: dict[type, "Rule | Literal['OPAQUE']"] = {
    If: _rule_if,                                               # type: ignore[dict-item]
    Menu: _rule_menu,                                           # type: ignore[dict-item]
    Jump: _rule_jump,                                           # type: ignore[dict-item]
    Call: _rule_call,                                           # type: ignore[dict-item]
    Return: _rule_return,
    Ending: _rule_ending,
}


# --- The job ---------------------------------------------------------------------------------

_RET: Final = -1                          # RET inside reach sets and successor lists
_RET_SET: Final = frozenset((_RET,))
_EMPTY: Final = frozenset()


class _TooComplex(Exception):
    pass


@dataclass(slots=True)
class _Proto:
    """A node before the final numbering (program order of anchors)."""

    id: str
    key: str
    kind: NodeKind
    name: str
    title: Text
    heading: str | None
    at: int                               # anchor statement index
    hidden: bool
    no_jump: bool
    line: int                             # W150's line (the mark, or the statement)
    file: object
    marked: bool
    definite: bool = True                 # False: a menu whose branching test decides


class FlowGraphJob:
    """Load phase 6 (04 §5, §7.1). ``step()`` does at most ``units`` work units and returns
    True when done; ``result`` is the graph, or None when ``options.enabled`` is False or
    after E265 (added to ``sink``). ``warnings`` holds W150–W153 on a ``dev`` load. Results
    never depend on ``units`` (TR-F20-01). ``last_units`` is the work of the last step."""

    def __init__(self, program: Program, options: FlowOptions, sink: DiagnosticSink, *,
                 dev: bool = True, units: int = limits.FLOW_STEP_UNITS) -> None:
        self.program = program
        self.options = options
        self.sink = sink
        self.dev = dev
        self.units = max(1, units)
        self.result: FlowGraph | None = None
        self.warnings: list[ScriptWarning] = []
        self.done = not options.enabled
        self.work = 0
        self.last_units = 0
        self._used = 0
        self._carry = 0
        self._gen = None if self.done else self._run()

    # Stepping ------------------------------------------------------------------------------

    def step(self) -> bool:
        if self.done:
            return True
        self._used, self._carry = self._carry, 0
        try:
            next(self._gen)                                   # type: ignore[arg-type]
        except StopIteration:
            self.done = True
            self._gen = None
        self.last_units = self._used
        return self.done

    def run(self) -> FlowGraph | None:
        """Step to the end in one go."""
        while not self.step():
            pass
        return self.result

    def _spend(self, units: int) -> bool:
        """Count ``units`` of work; True means "yield first: this work starts the next
        step"."""
        self.work += units
        if self.work > limits.FLOW_WORK_MAX:
            raise _TooComplex
        if self._used and self._used + units > self.units:
            self._carry = units
            return True
        self._used += units
        return False

    def _run(self) -> Generator[None, None, None]:
        try:
            graph = yield from self._build()
        except _TooComplex:
            self.sink.add(Diagnostic("E265", args=("complex", self.work,
                                                   limits.FLOW_WORK_MAX)))
            self.warnings = []
            return
        self.result = graph
        if graph is None:
            self.warnings = []

    # Set helpers ---------------------------------------------------------------------------

    def _intern(self, value: frozenset) -> frozenset:
        return self._sets.setdefault(value, value)

    def _union(self, parts: list[frozenset]) -> Generator[None, None, frozenset]:
        if not parts:
            return _EMPTY
        if len(parts) == 1:
            return self._intern(parts[0])
        cost = sum(len(part) for part in parts)
        if self._spend(cost):
            yield
        return self._intern(frozenset().union(*parts))

    def _val(self, at: int) -> frozenset:
        """The reach set of statement ``at`` (``_RET``: a return)."""
        if at < 0:
            return _RET_SET
        rep = self._rep[at]
        return _RET_SET if rep < 0 else self._reach[rep]

    def _resolve(self, value: frozenset, label: str) -> frozenset:
        """§7.1 step 4: a RET in ``label`` becomes the anchors after the calls that lead
        there; the rest is kept."""
        if _RET not in value:
            return value
        rest = value - _RET_SET
        back = self._ret.get(label)
        return self._intern(rest | back if back else rest)

    # Building ------------------------------------------------------------------------------

    def _build(self) -> Generator[None, None, FlowGraph | None]:
        self._sets: dict[frozenset, frozenset] = {_EMPTY: _EMPTY, _RET_SET: _RET_SET}
        yield from self._table()
        yield from self._anchors()
        # Round 1: definite anchors only (A0); the branching test; round 2 with them.
        yield from self._round()
        branching = yield from self._branching()
        if branching:
            for proto in branching:
                proto.definite = True
            self._first = self._first_anchors()
            yield from self._round()
        protos = [p for p in self._protos if p.definite]
        has_start = yield from self._has_start()
        others = sum(1 for p in protos if p.kind != "gate") + (1 if has_start else 0)
        if others > limits.FLOW_NODES_MAX:
            self.sink.add(Diagnostic("E265", args=("nodes", others, limits.FLOW_NODES_MAX)))
            return None
        return (yield from self._finish(protos, has_start))

    def _table(self) -> Generator[None, None, None]:
        """Number the statements (program order, pre-order), their next statements, each
        label's entry, and every statement's successors."""
        program = self.program
        stmts: list[Statement] = []
        index: dict[str, int] = {}
        for stmt in program.iter_statements():
            index[stmt.sid] = len(stmts)
            stmts.append(stmt)
            if self._spend(1):
                yield
        nexts = [_RET] * len(stmts)
        entry: dict[str, int] = {}
        for name, label in program.labels.items():
            entry[name] = index[label.block[0].sid] if label.block else _RET
            stack: list[tuple[tuple[Statement, ...], int]] = [(label.block, _RET)]
            while stack:
                block, after = stack.pop()
                for k, stmt in enumerate(block):
                    nxt = index[block[k + 1].sid] if k + 1 < len(block) else after
                    nexts[index[stmt.sid]] = nxt
                    for inner in stmt.blocks():
                        stack.append((inner, nxt))
            if self._spend(1):
                yield
        walk = Walk(stmts, index, nexts, program.labels)
        plain: list[tuple[int, ...]] = []
        calls: list[tuple[tuple[str, int], ...]] = []
        default: list[bool] = []
        opaque: list[int] = []
        forgets: list[int] = []
        sites: dict[str, list[int]] = {}
        jumps: dict[str, list[str]] = {}
        for i, stmt in enumerate(stmts):
            rule = FLOW_RULES.get(type(stmt), _rule_default)
            if rule == OPAQUE:
                opaque.append(i)
                plain.append(())
                calls.append(())
                default.append(False)
                continue
            succ_plain: list[int] = []
            succ_calls: list[tuple[str, int]] = []
            for succ in rule(stmt, walk):                     # type: ignore[operator]
                if isinstance(succ, CallSucc):
                    then = _RET if isinstance(succ.then, _Ret) else index[succ.then.sid]
                    succ_calls.append((succ.target, then))
                    sites.setdefault(succ.target, []).append(i)
                elif isinstance(succ, _Ret):
                    succ_plain.append(_RET)
                else:
                    succ_plain.append(index[succ.sid])
            if isinstance(stmt, Jump):
                jumps.setdefault(stmt.label, []).append(stmt.target)
            elif isinstance(stmt, Flowchart) and stmt.form == "forget":
                forgets.append(i)
            plain.append(tuple(succ_plain))
            calls.append(tuple(succ_calls))
            default.append(rule is _rule_default)
            if self._spend(1):
                yield
        self._stmts, self._index, self._nexts, self._entry = stmts, index, nexts, entry
        self._plain, self._calls, self._default, self._opaque = plain, calls, default, opaque
        self._sites, self._forgets = sites, forgets
        # frames(B): the call targets F from which B is reachable by jumps alone (§7.1
        # step 4); one BFS of the label jump graph per call target, in first-call order.
        frames: dict[str, list[str]] = {}
        for target in sites:
            seen = {target}
            queue = deque([target])
            while queue:
                here = queue.popleft()
                frames.setdefault(here, []).append(target)
                for there in jumps.get(here, ()):
                    if there not in seen:
                        seen.add(there)
                        queue.append(there)
                if self._spend(1):
                    yield
        self._frames = frames

    def _anchors(self) -> Generator[None, None, None]:
        """§7.1 step 1: every anchor in program order (a gate before what shares its
        statement); a menu with no mark is a candidate under ``"branching"``."""
        program = self.program
        marks = program.flow_marks
        menus = self.options.menus
        gates: dict[int, _Proto] = {}
        for route in program.routes:
            label = program.labels.get(route.name)
            if label is None or not label.block:
                continue
            at = self._index[label.block[0].sid]
            gates.setdefault(at, _Proto(
                f"gate:{route.name}", "", "gate", route.name, (route.title,), None, at, False,
                True, route.line, route.file, False))
        protos: list[_Proto] = []
        for at, stmt in enumerate(self._stmts):
            gate = gates.get(at)
            if gate is not None:
                protos.append(gate)
            proto = self._proto(at, stmt, marks.get(stmt.sid), menus)
            if proto is not None:
                protos.append(proto)
            if self._spend(1):
                yield
        kept: list[_Proto] = []
        seen: dict[str, str] = {node_key("start"): "start"}
        for proto in protos:
            key = node_key(proto.id)
            if key in seen:
                log.info("flowchart: node %s is left off the chart: its key equals node %s's",
                         proto.id, seen[key])
                continue
            seen[key] = proto.id
            proto.key = key
            kept.append(proto)
        self._protos = kept
        self._first = self._first_anchors()

    @staticmethod
    def _proto(at: int, stmt: Statement, mark: FlowMark | None, menus: str) -> _Proto | None:
        if isinstance(stmt, Flowchart):
            if stmt.form != "scene" or mark is None:
                return None
            label = stmt.label
            return _Proto(f"scene:{label}", "", "scene", label, (mark.title or "",), None, at,
                          mark.hidden, mark.no_jump, mark.line, stmt.file, True)
        if isinstance(stmt, Chapter):
            hidden = mark is not None and mark.hidden
            no_jump = mark is not None and mark.no_jump
            return _Proto(f"chapter:{stmt.name}", "", "chapter", stmt.name, (stmt.title,),
                          stmt.heading, at, hidden, no_jump, stmt.line, stmt.file, False)
        if isinstance(stmt, Ending):
            hidden = mark is not None and mark.hidden
            return _Proto(f"ending:{stmt.name}", "", "ending", stmt.name, (stmt.title,),
                          stmt.heading, at, hidden, True, stmt.line, stmt.file, False)
        if isinstance(stmt, Menu):
            if mark is not None and mark.omit:
                return None
            if mark is None and menus == "marked":
                return None
            if mark is not None and mark.title is not None:
                title: Text = (mark.title,)
            elif stmt.question is not None:
                title = plain_title(stmt.question.body)
            else:
                title = ()
            return _Proto(f"menu:{stmt.sid}", "", "choice", stmt.sid, title, None, at,
                          mark is not None and mark.hidden, mark is not None and mark.no_jump,
                          mark.line if mark is not None else stmt.line, stmt.file,
                          mark is not None, definite=mark is not None or menus == "all")
        return None

    def _first_anchors(self) -> dict[int, int]:
        """Statement index → the proto index of its first active anchor."""
        first: dict[int, int] = {}
        for number, proto in enumerate(self._protos):
            if proto.definite:
                first.setdefault(proto.at, number)
        return first

    # Reach (§7.1 step 3) -------------------------------------------------------------------

    def _round(self) -> Generator[None, None, None]:
        """Reach sets of every vertex under the active anchors, then the return targets."""
        stmts = self._stmts
        n = len(stmts)
        first = self._first
        # A plain, unanchored statement stands for whatever follows it (``rep``); its next
        # statement always comes later in pre-order, so one backward pass resolves chains.
        rep = [0] * n
        for i in range(n - 1, -1, -1):
            if self._default[i] and i not in first:
                nxt = self._plain[i][0]
                rep[i] = _RET if nxt < 0 else rep[nxt]
            else:
                rep[i] = i
            if self._spend(1):
                yield
        self._rep = rep
        entry = self._entry

        def target(at: int) -> int:
            return _RET if at < 0 else rep[at]

        # The vertices are the statements that stand for themselves; an anchored one has no
        # edges. A call depends on the called label's entry and on what follows it.
        none: tuple[int, ...] = ()
        deps: list[tuple[int, ...]] = [none] * n
        for i in range(n):
            if rep[i] == i and i not in first:
                found = [target(t) for t in self._plain[i]]
                for label, then in self._calls[i]:
                    found.append(target(entry.get(label, _RET)))
                    found.append(target(then))
                deps[i] = tuple(t for t in found if t >= 0)
            if self._spend(1):
                yield
        self._reach: list[frozenset] = [_EMPTY] * n
        yield from self._tarjan([i for i in range(n) if rep[i] == i], deps)
        yield from self._returns()

    def _tarjan(self, vertices: list[int], deps: list[tuple[int, ...]]
                ) -> Generator[None, None, None]:
        """Iterative Tarjan; each finished component (callees first) gets its reach set."""
        n = len(deps)
        index = [-1] * n
        low = [0] * n
        on = bytearray(n)
        stack: list[int] = []
        counter = 0
        for root in vertices:
            if index[root] >= 0:
                continue
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            on[root] = 1
            work: list[list[int]] = [[root, 0]]
            while work:
                frame = work[-1]
                v, at = frame
                out = deps[v]
                if at < len(out):
                    frame[1] = at + 1
                    w = out[at]
                    if index[w] < 0:
                        index[w] = low[w] = counter
                        counter += 1
                        stack.append(w)
                        on[w] = 1
                        work.append([w, 0])
                        if self._spend(1):
                            yield
                    elif on[w] and index[w] < low[v]:
                        low[v] = index[w]
                    continue
                work.pop()
                if work:
                    u = work[-1][0]
                    if low[v] < low[u]:
                        low[u] = low[v]
                if low[v] == index[v]:
                    members: list[int] = []
                    while True:
                        w = stack.pop()
                        on[w] = 0
                        members.append(w)
                        if w == v:
                            break
                    yield from self._component(members)

    def _call_value(self, label: str, then: int, value: Callable[[int], frozenset]
                    ) -> list[frozenset]:
        """CALL(label, then): the label's first anchors, and what follows the call if the
        label can return."""
        entry = self._entry.get(label, _RET)
        reached = _RET_SET if entry < 0 else value(entry)
        first = reached - _RET_SET
        parts = [first] if first else []
        if _RET in reached:
            parts.append(_RET_SET if then < 0 else value(then))
        return parts

    def _parts(self, v: int, value: Callable[[int], frozenset]) -> list[frozenset]:
        """What vertex ``v``'s reach is the union of."""
        anchor = self._first.get(v)
        if anchor is not None:
            return [self._intern(frozenset((anchor,)))]
        parts = [_RET_SET if t < 0 else value(t) for t in self._plain[v]]
        for label, then in self._calls[v]:
            parts.extend(self._call_value(label, then, value))
        return parts

    def _component(self, members: list[int]) -> Generator[None, None, None]:
        rep = self._rep
        reach = self._reach
        inside = set(members)

        def final(at: int) -> frozenset:
            r = rep[at]
            return _RET_SET if r < 0 else reach[r]

        recursive = any((entry >= 0 and rep[entry] in inside) or (then >= 0 and rep[then] in inside)
                        for v in members for label, then in self._calls[v]
                        for entry in (self._entry.get(label, _RET),))
        if not recursive:
            # Only plain edges inside: every member reaches every other, so one value. The
            # members' own values are still empty here and drop out of the union.
            parts: list[frozenset] = []
            for v in members:
                parts.extend(self._parts(v, final))
            value = yield from self._union([p for p in parts if p])
            for v in members:
                reach[v] = value
            if self._spend(len(members)):
                yield
            return
        # A cycle through a call (recursion): a local worklist fixpoint, exact.
        current: dict[int, frozenset] = {v: _EMPTY for v in members}

        def now(at: int) -> frozenset:
            r = rep[at]
            if r < 0:
                return _RET_SET
            return current[r] if r in current else reach[r]

        readers: dict[int, list[int]] = {v: [] for v in members}
        for v in members:
            found = [t for t in self._plain[v] if t >= 0]
            for label, then in self._calls[v]:
                found.append(self._entry.get(label, _RET))
                found.append(then)
            for t in found:
                if t >= 0 and rep[t] in current and v not in readers[rep[t]]:
                    readers[rep[t]].append(v)
        queue = deque(sorted(members))
        queued = set(members)
        while queue:
            v = queue.popleft()
            queued.discard(v)
            value = yield from self._union(self._parts(v, now))
            if self._spend(1):
                yield
            if value != current[v]:
                current[v] = value
                for u in readers[v]:
                    if u not in queued:
                        queued.add(u)
                        queue.append(u)
        for v in members:
            reach[v] = self._intern(current[v])

    # Returns (§7.1 step 4) -----------------------------------------------------------------

    def _returns(self) -> Generator[None, None, None]:
        """``ret(B)`` for every label B with frames: a worklist fixpoint over labels."""
        static: dict[str, frozenset] = {}
        reads: dict[str, list[str]] = {}
        for target, sites in self._sites.items():
            parts: list[frozenset] = []
            needs: list[str] = []
            for site in sites:
                after = self._val(self._nexts[site])
                rest = after - _RET_SET
                if rest:
                    parts.append(rest)
                label = self._stmts[site].label
                if _RET in after and label not in needs:
                    needs.append(label)
            static[target] = yield from self._union(parts)
            reads[target] = needs
        self._ret: dict[str, frozenset] = {}
        readers: dict[str, list[str]] = {}
        order: list[str] = []
        for label, targets in self._frames.items():
            order.append(label)
            for target in targets:
                for needed in reads.get(target, ()):
                    readers.setdefault(needed, []).append(label)
        queue = deque(order)
        queued = set(order)
        while queue:
            label = queue.popleft()
            queued.discard(label)
            parts = []
            for target in self._frames[label]:
                parts.append(static.get(target, _EMPTY))
                parts.extend(self._ret.get(needed, _EMPTY) for needed in reads.get(target, ()))
            value = yield from self._union([p for p in parts if p])
            if self._spend(1):
                yield
            if value != self._ret.get(label, _EMPTY):
                self._ret[label] = value
                for reader in readers.get(label, ()):
                    if reader not in queued:
                        queued.add(reader)
                        queue.append(reader)

    # Branching menus (§7.1 step 5) ---------------------------------------------------------

    def _choice_sets(self, at: int) -> list[frozenset]:
        menu = self._stmts[at]
        assert isinstance(menu, Menu)
        out = []
        for choice in menu.choices:
            start = self._index[choice.block[0].sid] if choice.block else self._nexts[at]
            out.append(self._resolve(self._val(start), menu.label))
        return out

    def _branching(self) -> Generator[None, None, list[_Proto]]:
        found: list[_Proto] = []
        if self.options.menus != "branching":
            return found
        for proto in self._protos:
            if proto.definite or proto.kind != "choice":
                continue
            sets = self._choice_sets(proto.at)
            if self._spend(len(sets)):
                yield
            if any(s != sets[0] for s in sets[1:]):
                found.append(proto)
        return found

    # Start (§7.1 step 7) -------------------------------------------------------------------

    def _returns_from(self, label: str) -> bool:
        entry = self._entry.get(label, _RET)
        return entry < 0 or _RET in self._val(entry)

    def _has_start(self) -> Generator[None, None, bool]:
        """A line or a menu that is no node runs before the first node."""
        begin = self._entry.get(START_LABEL, _RET)
        if begin < 0:
            return False
        seen = {begin}
        queue = deque([begin])
        while queue:
            at = queue.popleft()
            if self._spend(1):
                yield
            if at in self._first:
                continue
            if isinstance(self._stmts[at], (Say, Menu)):
                return True
            nxt = [t for t in self._plain[at] if t >= 0]
            for label, then in self._calls[at]:
                entry = self._entry.get(label, _RET)
                if entry >= 0:
                    nxt.append(entry)
                if then >= 0 and self._returns_from(label):
                    nxt.append(then)
            for t in nxt:
                if t not in seen:
                    seen.add(t)
                    queue.append(t)
        return False

    # Edges, order, routes, limits, warnings (§7.1 steps 6–10) --------------------------------

    def _out_of(self, at: int) -> list[frozenset]:
        parts = [_RET_SET if t < 0 else self._val(t) for t in self._plain[at]]
        for label, then in self._calls[at]:
            parts.extend(self._call_value(label, then, self._val))
        return parts

    def _finish(self, protos: list[_Proto], has_start: bool
                ) -> Generator[None, None, FlowGraph | None]:
        number = {id(p): i for i, p in enumerate(self._protos)}
        final: dict[int, int] = {}                       # proto index → node index
        base = 1 if has_start else 0
        for i, proto in enumerate(protos):
            final[number[id(proto)]] = base + i
        count = base + len(protos)

        def ids(value: frozenset) -> list[int]:
            return sorted(final[p] for p in value if p >= 0 and p in final)

        # Out-edges per node: (dst, choice positions or None).
        stmts = self._stmts
        out_lists: list[list[tuple[int, list[int] | None]]] = [[] for _ in range(count)]
        roots: list[int] = []
        start_entry = self._entry.get(START_LABEL, _RET)
        start_reach = self._val(start_entry) if start_entry >= 0 else _EMPTY
        if has_start:
            out_lists[0] = [(d, None) for d in ids(start_reach)]
        else:
            roots = ids(start_reach)
        at_stmt: dict[int, list[int]] = {}
        for i, proto in enumerate(protos):
            at_stmt.setdefault(proto.at, []).append(base + i)
        for i, proto in enumerate(protos):
            node = base + i
            sharing = at_stmt[proto.at]
            place = sharing.index(node)
            if place + 1 < len(sharing):
                out_lists[node] = [(sharing[place + 1], None)]
            elif proto.kind == "choice":
                by_target: dict[int, list[int]] = {}
                for c, value in enumerate(self._choice_sets(proto.at)):
                    for dst in ids(value):
                        by_target.setdefault(dst, []).append(c)
                out_lists[node] = list(by_target.items())
            else:
                value = yield from self._union(self._out_of(proto.at))
                value = self._resolve(value, stmts[proto.at].label)
                out_lists[node] = [(d, None) for d in ids(value)]
            if self._spend(1 + len(out_lists[node])):
                yield
        edge_count = sum(len(o) for o in out_lists)
        if edge_count > limits.FLOW_EDGES_MAX:
            self.sink.add(Diagnostic("E265", args=("paths", edge_count, limits.FLOW_EDGES_MAX)))
            return None
        # Node ids, keys, kinds, in final order.
        heads: list[tuple[str, str, NodeKind]] = []
        if has_start:
            heads.append(("start", node_key("start"), "start"))
        heads.extend((p.id, p.key, p.kind) for p in protos)
        keys = [h[1] for h in heads]
        edges: list[FlowEdge] = []
        records: set[str] = set()
        for src, targets in enumerate(out_lists):
            menu = stmts[protos[src - base].at] if src >= base and heads[src][2] == "choice" \
                else None
            for dst, chosen in targets:
                if chosen is not None and isinstance(menu, Menu):
                    picked = [menu.choices[c] for c in chosen]
                    edges.append(FlowEdge(src, dst, tuple(c.key for c in picked),
                                          tuple(plain_title(c.body) for c in picked), None))
                else:
                    record = keys[src] + keys[dst]
                    records.add(record)
                    edges.append(FlowEdge(src, dst, (), (), record))
        chapters = sum(1 for h in heads if h[2] == "chapter")
        names = max(len(records), count + chapters)
        if names > limits.FLOW_NAMES_MAX:
            self.sink.add(Diagnostic("E265", args=("names", names, limits.FLOW_NAMES_MAX)))
            return None
        out = [[] for _ in range(count)]                 # type: list[list[int]]
        into = [[] for _ in range(count)]                # type: list[list[int]]
        for e, edge in enumerate(edges):
            out[edge.src].append(e)
            into[edge.dst].append(e)
        # Story order: BFS from the start (or the roots) over out-edges in edge order.
        starts = [0] if has_start else roots
        order: list[int] = []
        parent: dict[int, int | None] = {}
        queue = deque()
        for root in starts:
            if root not in parent:
                parent[root] = None
                queue.append(root)
        while queue:
            here = queue.popleft()
            order.append(here)
            for e in out[here]:
                there = edges[e].dst
                if there not in parent:
                    parent[there] = here
                    queue.append(there)
            if self._spend(1):
                yield
        reached = set(order)
        order.extend(i for i in range(count) if i not in reached)
        place = {node: k for k, node in enumerate(order)}
        chapter_of: dict[int, int | None] = {}
        for node in order:
            if node not in reached:
                chapter_of[node] = None
                continue
            up = parent[node]
            if up is None:
                chapter_of[node] = None
            else:
                chapter_of[node] = up if heads[up][2] == "chapter" else chapter_of[up]
        # Routes (PR-F20-12): members are reachable from the gate, not from the start or
        # roots once the gate is taken out; the innermost route wins.
        route_of: dict[int, tuple[int, int]] = {}
        for gate in (i for i in range(count) if heads[i][2] == "gate"):
            outside = yield from self._bfs(starts, edges, out, skip=gate)
            inside = yield from self._bfs([edges[e].dst for e in out[gate]], edges, out,
                                          skip=gate)
            members = [m for m in inside if m not in outside and m != gate]
            for member in members:
                best = route_of.get(member)
                if best is None or (len(members), gate) < best:
                    route_of[member] = (len(members), gate)
        nodes: list[FlowNode] = []
        if has_start:
            nodes.append(FlowNode("start", keys[0], "start", START_LABEL, (), None, "",
                                  START_LABEL, False, False, None, None, place[0]))
        for i, proto in enumerate(protos):
            node = base + i
            stmt = stmts[proto.at]
            route = route_of.get(node)
            nodes.append(FlowNode(proto.id, proto.key, proto.kind, proto.name, proto.title,
                                  proto.heading, stmt.sid, stmt.label, proto.hidden,
                                  proto.no_jump, chapter_of[node],
                                  None if route is None else route[1], place[node]))
            if self._spend(1):
                yield
        anchors: dict[str, list[int]] = {}
        in_label: dict[str, list[int]] = {}
        for k, node in enumerate(nodes):
            if node.kind in ("start", "gate"):
                continue
            anchors.setdefault(node.anchor, []).append(k)
            if node.kind in ("scene", "chapter", "choice"):
                in_label.setdefault(node.label, []).append(k)
        graph = FlowGraph(
            nodes=tuple(nodes), edges=tuple(edges),
            anchors=MappingProxyType({s: tuple(v) for s, v in anchors.items()}),
            by_id=MappingProxyType({n.id: k for k, n in enumerate(nodes)}),
            by_key=MappingProxyType({n.key: k for k, n in enumerate(nodes)}),
            out=tuple(tuple(v) for v in out), into=tuple(tuple(v) for v in into),
            records=frozenset(records),
            in_label=MappingProxyType({s: tuple(v) for s, v in in_label.items()}))
        if self.dev:
            self.warnings = yield from self._dev_warnings(graph, protos, base, reached)
        return graph

    def _bfs(self, starts: Iterable[int], edges: list[FlowEdge], out: list[list[int]], *,
             skip: int) -> Generator[None, None, set[int]]:
        seen: set[int] = set()
        queue = deque()
        for s in starts:
            if s != skip and s not in seen:
                seen.add(s)
                queue.append(s)
        while queue:
            here = queue.popleft()
            for e in out[here]:
                there = edges[e].dst
                if there != skip and there not in seen:
                    seen.add(there)
                    queue.append(there)
            if self._spend(1):
                yield
        return seen

    def _dev_warnings(self, graph: FlowGraph, protos: list[_Proto], base: int,
                      reached: set[int]) -> Generator[None, None, list[ScriptWarning]]:
        found: list[tuple[int, int, int, ScriptWarning]] = []

        def add(file: object, line: int, code: str, args: tuple = ()) -> None:
            found.append((getattr(file, "order", 0), line, len(found),
                          ScriptWarning(format_message(code, args), code=code,
                                        file=getattr(file, "ref", None), line=line)))

        for i, proto in enumerate(protos):
            if self._spend(1):
                yield
            if proto.kind == "gate" or base + i in reached:
                continue
            stmt = self._stmts[proto.at]
            if proto.kind == "scene":
                args: tuple = ("scene", proto.title[0], stmt.label, True)
            elif proto.kind == "choice":
                args = ("menu", None, stmt.label, proto.marked)
            else:
                args = (proto.kind, proto.name, stmt.label, False)
            add(proto.file, proto.line, "W150", args)
        for at in self._opaque:
            stmt = self._stmts[at]
            add(stmt.file, stmt.line, "W151")
        for node in graph.nodes:
            if node.kind != "choice":
                continue
            menu = self.program.get(node.anchor)
            if not isinstance(menu, Menu):
                continue
            if self._spend(len(menu.choices)):
                yield
            for choice in menu.choices:
                if _var_only(plain_title(choice.body)):
                    name = next((p.name for p in choice.body.pieces if isinstance(p, VarMark)),
                                "name")
                    add(menu.file, choice.line, "W152", (choice.text, name))
        for at in self._forgets:
            stmt = self._stmts[at]
            assert isinstance(stmt, Flowchart)
            if stmt.target is not None and stmt.target not in graph.in_label:
                add(stmt.file, stmt.line, "W153", (stmt.target,))
        found.sort(key=lambda item: item[:3])
        return [item[3] for item in found]


def build_flowgraph(program: Program, options: FlowOptions = FlowOptions(),
                    sink: DiagnosticSink | None = None, *, dev: bool = True
                    ) -> FlowGraph | None:
    """``FlowGraphJob`` run to the end in one go (tests and tools)."""
    return FlowGraphJob(program, options, sink or DiagnosticSink(), dev=dev).run()


__all__ = ["CallSucc", "FLOW_RULES", "FlowEdge", "FlowGraph", "FlowGraphJob", "FlowMark",
           "FlowNode", "FlowOptions", "NodeKind", "OPAQUE", "RET", "Text", "VAR_WORD", "Walk",
           "box_text", "build_flowgraph", "node_key", "plain_title", "show_text"]
