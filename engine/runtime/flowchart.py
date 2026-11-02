"""The flowchart at run time (F20 ``04-technical.md`` §4, §6.3, §7.2–§7.4, §10; ``07`` §3.2,
§3.5, I-8, I-9, I-13, I-14).

Why this module exists: the graph (``script/flowgraph.py``) is built at load; this module
records which of its nodes the player reached, keeps each node's state for a jump, and turns
the records into what the Flowchart page may show, with every unseen text masked.

- ``FlowState`` (``GameState.flow``): the node keys reached in this playthrough, oldest first,
  at most ``limits.FLOW_PATH_MAX``. JSON ``{"path": ["<16 hex>", …]}``, always written,
  optional on read (``EMPTY_FLOW``); anything else is ``StateInvalid("flow")``, never echoed.
  Runtime-held like ``history`` (07 §3.2): checkpoint step 2c sets ``interp.flow``,
  ``_snapshot`` stores it, restore commits the saved one, new game empties it. Keys are
  lookups only: an unknown key is kept and ignored.
- **Arrivals** (§7.2). The run loop looks up each statement it is about to run in
  ``interp.flow_anchors`` (the graph's ``anchors``; an empty mapping without a graph): one
  dict lookup per step. ``FlowRecorder.anchor`` records an ending at once (its edge record
  and its key moved last for recency; F19 records the ending itself) and puts any other node
  in ``interp.flow_pending`` (at most ``FLOW_PENDING_MAX``; extras dropped). Checkpoint step
  2c (``flush``) walks the pending nodes from ``path[-1]`` (or the start node's key): a pair
  ``prev + key`` that is an edge record is kept, else the gate pairs ``prev + gate`` (when a
  record) and ``gate + key`` (a gate shares its anchor with the node after it, so it is never
  pending itself); the keys join the path. Step 4d (``record``), after F14's 4c, writes the
  store and keeps the checkpoint's snapshot as each node's state. Restore, back landings,
  loads, and jumps run no statement, so they reach nothing (PR-F20-07).
- **The start node** (anchor ``""``) is never recorded: ``chart_records`` shows it visited
  always, and step 2c starts from its key when the path is empty (04 amendment, F20 s3). It
  keeps no state; neither do endings or gates.
- **Store records** (§4 "Kind names"): ``"flowchart"`` holds node keys and chapter tombstones
  (``x`` + key; a forgotten chapter stays unvisited although F18's ``"chapter"`` record stays);
  ``"flowchart_edge"`` the taken non-choice edges' records. Both revocable, with ``known``
  recognizers over the current graph. A first arrival is a normal unlock; a re-arrival whose
  key isn't last is ``relock`` then a quiet ``unlock`` (moved last, 07 I-8); tombstones are
  quiet. At most 6 store operations per arrival (04 §11).
- **Node states** (I-14): ``FlowRecorder.states`` keeps the newest snapshot per node (the very
  ``GameState`` object, never a copy), at most ``FLOW_MEMORY_STATES``, oldest dropped first.
  ``take_dirty`` gives ``app`` the ids to write; ``take_forgotten`` the ids (or ``"all"``)
  whose files to delete. A store ``reset`` (F16's Delete progress, ``reset_count``) drops every
  state, as a forget of everything does.
- ``FlowRecorder.forget`` is ``flowchart forget [label]`` (§7.4): never rolled back; running it
  again changes nothing.
- ``FlowStates`` (§7.6 "Headless", 07 §3.5 G2, SEC-F20-13) is ``run_headless``'s ``flow=``
  holder: it backs the recorder's states (only ``GameState`` values, at most
  ``FLOW_MEMORY_STATES``, oldest dropped first) and lists every arrival's node id
  (``reached``, endings included) and edge records (``taken``), appended across runs. A
  headless ``jump <id>`` restores its state with ``fresh_menu`` (F20 s4).
- ``chart_records`` (§7.3, 07 §3.5) is pure: the page gets ``ChartRecords`` only, so a title or
  choice text the player hasn't earned never reaches it (SEC-F20-14(a)).

The graph types and ``FlowOptions`` are re-exported from ``script/flowgraph.py`` (07 I-1:
``app`` and ``ui`` read them here). Layering: ``state.py`` holds a ``FlowState`` and the
interpreter imports this module, so both are imported only under ``TYPE_CHECKING`` or inside
a function. Pure: no file, clock, thread, or randomness (AC-F20-69).
"""

import re
from collections.abc import Iterator, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from engine.runtime import limits
from engine.runtime.chapters import UNLOCK_KIND as CHAPTER_KIND
from engine.runtime.endings import ENDING_KIND
from engine.script.flowchart import Flowchart
from engine.script.flowgraph import (FlowEdge, FlowGraph, FlowNode, FlowOptions, NodeKind,
                                     Text, box_text, node_key, show_text)

if TYPE_CHECKING:
    from engine.runtime.chapters import ChapterIndex
    from engine.runtime.endings import EndingIndex, RouteIndex
    from engine.runtime.interpreter import Interpreter, Step
    from engine.runtime.persistent import PersistentStore
    from engine.runtime.state import GameState

FLOW_KIND: Final = "flowchart"          # node keys and chapter tombstones (revocable)
EDGE_KIND: Final = "flowchart_edge"     # taken non-choice edges' records (revocable)
TOMBSTONE: Final = "x"                  # "x" + a chapter's key: forgotten (04 §7.4)
START_KEY: Final = node_key("start")
_KEY_RE: Final = re.compile(r"[0-9a-f]{16}")
NO_ANCHORS: Final[Mapping[str, tuple[int, ...]]] = MappingProxyType({})


# --- GameState.flow (04 §4, §10) ----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FlowState:
    """``GameState.flow``: node keys reached in this playthrough, oldest first. No text, so not
    a display record (07 §3.2)."""

    path: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {"path": list(self.path)}

    @staticmethod
    def from_json(obj: object) -> "FlowState":
        """Validate untrusted ``obj``: exactly ``{"path": [...]}`` with at most
        ``FLOW_PATH_MAX`` entries, each 16 lowercase hex digits. Anything else is
        ``StateInvalid("flow")``, never echoing the input (TR-F20-02)."""
        from engine.runtime.state import StateInvalid   # state.py imports this module
        if type(obj) is not dict or obj.keys() != {"path"}:
            raise StateInvalid("flow")
        path = obj["path"]
        if type(path) is not list or len(path) > limits.FLOW_PATH_MAX:
            raise StateInvalid("flow")
        for key in path:
            if type(key) is not str or len(key) != 16 or not _KEY_RE.fullmatch(key):
                raise StateInvalid("flow")
        return FlowState(tuple(path)) if path else EMPTY_FLOW


EMPTY_FLOW: Final = FlowState()


# --- The headless holder (04 §7.6; 07 §3.5 G2; SEC-F20-13) --------------------------------------

class FlowStates(MutableMapping[str, "GameState"]):
    """``run_headless``'s ``flow=`` holder, shared across runs like ``persistent=``: node id
    → newest state (a ``GameState`` only, else ``ValueError``; setting moves the id last; at
    most ``keep``, the oldest dropped first). The recorder keeps its states here and appends
    each arrival's node ids to ``reached`` (arrival order, endings included) and its edge
    records to ``taken``."""

    def __init__(self, *, keep: int | None = None) -> None:
        self.keep = limits.FLOW_MEMORY_STATES if keep is None else keep
        self.reached: list[str] = []
        self.taken: list[str] = []
        self._states: dict[str, "GameState"] = {}

    def __getitem__(self, node_id: str) -> "GameState":
        return self._states[node_id]

    def __setitem__(self, node_id: str, state: "GameState") -> None:
        from engine.runtime.state import GameState      # state.py imports this module
        if type(node_id) is not str or type(state) is not GameState:
            raise ValueError("a flow holder keeps one GameState per node id")
        states = self._states
        states.pop(node_id, None)
        states[node_id] = state
        while len(states) > self.keep:
            del states[next(iter(states))]

    def __delitem__(self, node_id: str) -> None:
        del self._states[node_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self._states)

    def __len__(self) -> int:
        return len(self._states)

    def __repr__(self) -> str:
        return f"FlowStates({len(self._states)} states, {len(self.reached)} reached)"


# --- The recorder (04 §5, §7.2, §7.4) -----------------------------------------------------------

Arrived = tuple[tuple[int, ...], tuple[str, ...]]     # step 2c → 4d: nodes, edge records


class FlowRecorder:
    """``interp.flowchart``: arrivals into the store, node states for jumps, and forget. Main
    thread, plain data. ``graph`` None (no graph, 07 I-13): nothing is ever recorded and
    ``forget`` does nothing. ``gen`` counts up on every arrival, forget, and reset seen.
    ``states`` (headless): a ``FlowStates`` holder to keep the states in and to log
    arrivals to."""

    def __init__(self, graph: FlowGraph | None, store: "PersistentStore", *,
                 keep: int | None = None, states: FlowStates | None = None) -> None:
        self.graph = graph
        self.store = store
        self.keep = limits.FLOW_MEMORY_STATES if keep is None else keep
        self.gen = 0
        # node id → newest state, oldest first
        self.states: MutableMapping[str, "GameState"] = {} if states is None else states
        self._trace = states
        self._dirty: dict[str, None] = {}               # ids to write, arrival order
        self._forgotten: dict[str, None] | Literal["all"] = {}
        self._resets = store.reset_count

    # Run loop and checkpoint steps 2c, 4d (§7.2) --------------------------------------------

    def anchor(self, interp: "Interpreter", nodes: tuple[int, ...]) -> None:
        """The run loop found ``nodes`` anchored at the statement about to run: an ending is
        recorded now (no checkpoint follows it); any other node waits for the next one."""
        graph = self.graph
        assert graph is not None
        pending = interp.flow_pending
        for n in nodes:
            if graph.nodes[n].kind == "ending":
                path = interp.flow.path
                self._reach_ending(path[-1] if path else START_KEY, n)
            elif len(pending) < limits.FLOW_PENDING_MAX:
                pending.append(n)

    def flush(self, interp: "Interpreter") -> Arrived:
        """Step 2c: the pending nodes become arrivals: their keys join ``interp.flow`` (newest
        ``FLOW_PATH_MAX`` kept) and the edge records walked from the path's last key (or the
        start's) are returned for step 4d. Clears the pending list."""
        graph = self.graph
        assert graph is not None
        pending = interp.flow_pending
        path = interp.flow.path
        prev = path[-1] if path else START_KEY
        keys: list[str] = []
        pairs: list[str] = []
        for n in pending:
            pairs.extend(self._pairs(prev, n))
            prev = graph.nodes[n].key
            keys.append(prev)
        interp.flow = FlowState((path + tuple(keys))[-limits.FLOW_PATH_MAX:])
        nodes = tuple(pending)
        pending.clear()
        return nodes, tuple(pairs)

    def record(self, arrived: Arrived, state: "GameState") -> None:
        """Step 4d, in one main-thread step (no store encode or merge between, SEC-F20-11(c)):
        each node's key (moved last on a re-arrival), a chapter's tombstone taken back, the
        edge records, and ``state`` kept for every node but the start and endings."""
        self._check_reset()
        graph = self.graph
        assert graph is not None
        store = self.store
        nodes, pairs = arrived
        for n in nodes:
            node = graph.nodes[n]
            self._visit(node.key)
            if node.kind == "chapter" and store.is_unlocked(FLOW_KIND, TOMBSTONE + node.key):
                store.relock(FLOW_KIND, TOMBSTONE + node.key)
        for pair in pairs:
            store.unlock(EDGE_KIND, pair)
        for n in nodes:
            node = graph.nodes[n]
            if node.kind in ("scene", "chapter", "choice"):
                self._keep(node.id, state)
        trace = self._trace
        if trace is not None:                               # headless (07 §3.5 G2)
            trace.reached.extend(graph.nodes[n].id for n in nodes)
            trace.taken.extend(pairs)
        self.gen += 1

    def _visit(self, key: str) -> None:
        """A first arrival is a normal unlock; a re-arrival moves the key last (relock, then a
        quiet unlock) only when it isn't last already (07 I-8)."""
        store = self.store
        if not store.is_unlocked(FLOW_KIND, key):
            store.unlock(FLOW_KIND, key)
        elif store.last_unlocked(FLOW_KIND) != key:
            store.relock(FLOW_KIND, key)
            store.unlock(FLOW_KIND, key, quiet=True)

    def _reach_ending(self, prev: str, n: int) -> None:
        """An ending runs: the edge into it (from ``path[-1]`` or the start) when it is a
        record, and its key moved last for "most recently reached" (07 §3.5 G3). Whether it
        is visited is F19's ``"ending"`` kind (§7.3)."""
        self._check_reset()
        pairs = self._pairs(prev, n)
        for pair in pairs:
            self.store.unlock(EDGE_KIND, pair)
        assert self.graph is not None
        self._visit(self.graph.nodes[n].key)
        trace = self._trace
        if trace is not None:                               # headless (07 §3.5 G2)
            trace.reached.append(self.graph.nodes[n].id)
            trace.taken.extend(pairs)
        self.gen += 1

    def _pairs(self, prev: str, n: int) -> list[str]:
        """The records for an arrival at node ``n`` after the node keyed ``prev``: the edge
        ``prev → n``, else through a gate g into ``n`` (``prev + g`` when it is a record, a
        choice edge has none; then ``g + n``). [] when neither is an edge (a jump the graph
        doesn't draw, an unknown key)."""
        graph = self.graph
        assert graph is not None
        key = graph.nodes[n].key
        if prev + key in graph.records:
            return [prev + key]
        p = graph.by_key.get(prev)
        if p is None:
            return []
        edges, nodes = graph.edges, graph.nodes
        for e in graph.into[n]:
            into = edges[e]
            gate = into.src
            if nodes[gate].kind != "gate" or into.record is None:
                continue
            for f in graph.out[p]:
                step = edges[f]
                if step.dst == gate:
                    return ([step.record] if step.record is not None else []) + [into.record]
        return []

    def _keep(self, node_id: str, state: "GameState") -> None:
        states = self.states
        states.pop(node_id, None)
        states[node_id] = state
        self._dirty.pop(node_id, None)
        self._dirty[node_id] = None
        while len(states) > self.keep:                  # SEC-F20-05(a): oldest first
            oldest = next(iter(states))
            del states[oldest]
            self._dirty.pop(oldest, None)

    # For app (04 §5, §7.5) -----------------------------------------------------------------

    def state(self, node_id: str) -> "GameState | None":
        """The newest state of ``node_id`` held in memory (None: none held)."""
        self._check_reset()
        return self.states.get(node_id)

    def take_dirty(self) -> list[str]:
        """The node ids reached since the last call whose states are still held, arrival
        order (a re-reached id moves last)."""
        self._check_reset()
        out = list(self._dirty)
        self._dirty.clear()
        return out

    def take_forgotten(self) -> tuple[str, ...] | Literal["all"]:
        """The node ids forgotten since the last call, or ``"all"`` (a forget of the whole
        chart, or a store reset): their files are to be deleted (§7.5 "Deletes")."""
        self._check_reset()
        out = self._forgotten
        self._forgotten = {}
        return "all" if out == "all" else tuple(out)

    def drop_state(self, node_id: str) -> None:
        """``app`` wrote the state (or gave it up): stop holding it."""
        self.states.pop(node_id, None)
        self._dirty.pop(node_id, None)

    def _check_reset(self) -> None:
        """F16's Delete progress (``store.reset``): no state stays, every file goes."""
        count = self.store.reset_count
        if count != self._resets:
            self._resets = count
            self.states.clear()
            self._dirty.clear()
            self._forgotten = "all"
            self.gen += 1

    # Forget (§7.4) ---------------------------------------------------------------------------

    def forget(self, label: str | None) -> None:
        """``flowchart forget [label]``: every node but the start and endings, or the nodes
        written in ``label`` (``graph.in_label``), become unvisited: the key relocked, a
        chapter's tombstone written (quietly), the records of edges into and out of it
        relocked, its state and pending write dropped. The story state, path, saves, and
        other kinds are untouched. Without a graph it does nothing (07 I-13)."""
        graph = self.graph
        if graph is None:
            return
        self._check_reset()
        store = self.store
        if label is None:
            targets: Sequence[int] = [i for i, node in enumerate(graph.nodes)
                                      if node.kind not in ("start", "ending")]
        else:
            targets = graph.in_label.get(label, ())
        for i in targets:
            node = graph.nodes[i]
            store.relock(FLOW_KIND, node.key)
            if node.kind == "chapter":
                store.unlock(FLOW_KIND, TOMBSTONE + node.key, quiet=True)
            for e in graph.into[i] + graph.out[i]:
                record = graph.edges[e].record
                if record is not None:
                    store.relock(EDGE_KIND, record)
            self.states.pop(node.id, None)
            self._dirty.pop(node.id, None)
            if self._forgotten != "all":
                self._forgotten[node.id] = None
        if label is None:
            self._forgotten = "all"
        self.gen += 1


def register(interp: "Interpreter", *, states: FlowStates | None = None) -> None:
    """Per interpreter (F39 calls it again with a new program): ``interp.flowchart`` (a fresh
    recorder over ``program.flowgraph``; ``states``: headless's holder), ``interp.flow_anchors``,
    and, with a graph, the store's two revocable kinds with their ``known`` recognizers. Safe
    to repeat on one store (07 I-13); without a graph no kind is registered."""
    graph = interp.program.flowgraph
    store = interp.persistent
    interp.flowchart = FlowRecorder(graph, store, states=states)
    interp.flow_anchors = NO_ANCHORS if graph is None else graph.anchors
    if graph is not None:
        register_kinds(store, graph)


def register_kinds(store: "PersistentStore", graph: FlowGraph) -> None:
    """``"flowchart"`` and ``"flowchart_edge"``, revocable, recognizing exactly the current
    graph's node keys and chapter tombstones, and its edge records (SEC-F20-11(a))."""
    by_key, nodes = graph.by_key, graph.nodes

    def known_node(name: str) -> bool:
        if type(name) is not str:
            return False
        if name in by_key:
            return True
        if name[:1] == TOMBSTONE:
            at = by_key.get(name[1:])
            return at is not None and nodes[at].kind == "chapter"
        return False

    records = graph.records

    def known_edge(name: str) -> bool:
        return type(name) is str and name in records

    store.register_kind(FLOW_KIND, known=known_node, revocable=True)
    store.register_kind(EDGE_KIND, known=known_edge, revocable=True)


# --- The executor (04 §6.3) -----------------------------------------------------------------------

def run_flowchart(interp: "Interpreter", stmt: Flowchart) -> "Step":
    """The ``Flowchart`` executor: CONTINUE, releasing nothing. ``scene``, mark, and ``omit``
    do nothing (the anchor lookup sees arrivals); ``forget`` forgets (§7.4)."""
    from engine.runtime.interpreter import Step     # the interpreter imports this module

    if stmt.form == "forget":
        interp.flowchart.forget(stmt.target)
    return Step.CONTINUE


# --- What the page shows (04 §7.3; 07 §3.5) ---------------------------------------------------

@dataclass(frozen=True, slots=True)
class ChartEdge:
    """One drawn edge between two shown ends. ``parts`` are the graph edges it stands for:
    one, or (into, out of) an open route's gate, contracted. ``choices`` are the choice keys
    (script order) of its first part; () for a non-choice edge."""

    src: int
    dst: int
    parts: tuple[int, ...]
    choices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChartShape:
    """The visible graph, no text: per graph node its kind, ``no_jump``, chapter, and story
    order; ``nodes`` the shown nodes and gates in story order (nothing else is walked:
    reading order, Tab, culling); ``edges`` between shown ends, open gates contracted."""

    kinds: tuple[NodeKind, ...]
    no_jump: tuple[bool, ...]
    chapter: tuple[int | None, ...]
    order: tuple[int, ...]
    nodes: tuple[int, ...]
    edges: tuple[ChartEdge, ...]


@dataclass(frozen=True, slots=True)
class GateRow:
    """One ``until`` ending of a gate: its node (None: not on the chart), whether F19 holds
    it, and its text (``Heading: Title``) only when reached (None: ``???``)."""

    ending: int | None
    reached: bool
    text: Text | None


@dataclass(frozen=True, slots=True)
class GateView:
    """A shown (locked) gate: its node, the route's title once one of its nodes is visited
    (None: ``???``, PR-F20-12), and its ``until`` rows."""

    node: int
    title: Text | None
    rows: tuple[GateRow, ...]


@dataclass(frozen=True, slots=True)
class ChartRecords:
    """One page open, masked (SEC-F20-14(a)). Per graph node: ``titles`` (None: ``???``,
    unvisited or unshown; ``()``: the kind word), ``shown``, ``visited``. Per ``shape.edges``
    entry: ``edge_texts`` (one per choice; None: an untaken choice, ``???``) and ``taken``.
    ``here`` (in game) and ``recent`` (07 §3.5 G3, G4) are node indexes or None;
    ``path_nodes`` and ``path_edges`` (indexes into ``shape.edges``) are this playthrough's
    shown path. ``counts``: (endings visited, endings shown, nodes visited, nodes shown),
    over shown non-gate nodes only (SEC-F20-14(b))."""

    shape: ChartShape
    titles: tuple[Text | None, ...]
    edge_texts: tuple[tuple[Text | None, ...], ...]
    shown: tuple[bool, ...]
    visited: tuple[bool, ...]
    taken: tuple[bool, ...]
    gates: tuple[GateView, ...]
    here: int | None
    path_nodes: frozenset[int]
    path_edges: frozenset[int]
    recent: int | None
    counts: tuple[int, int, int, int]


def chart_records(graph: FlowGraph, store: "PersistentStore", chapters: "ChapterIndex",
                  endings: "EndingIndex", routes: "RouteIndex", options: FlowOptions,
                  path: tuple[str, ...] | None) -> ChartRecords:
    """§7.3: what the page may show for ``graph`` over ``store``'s records. ``path`` is the
    state on screen's ``flow.path`` in game, None from the title. Pure: reads only."""
    nodes, edges = graph.nodes, graph.edges
    count = len(nodes)
    is_unlocked = store.is_unlocked

    # Visited: start always; chapters by F20's key, or F18's record without a tombstone;
    # scenes and choices by F20's key; endings by F19's record only. Gates never.
    visited: list[bool] = []
    for node in nodes:
        kind = node.kind
        if kind == "start":
            seen = True
        elif kind == "ending":
            seen = endings.has(node.name) and is_unlocked(ENDING_KIND, node.name)
        elif kind == "gate":
            seen = False
        else:
            seen = is_unlocked(FLOW_KIND, node.key)
            if not seen and kind == "chapter":
                seen = (chapters.has(node.name) and is_unlocked(CHAPTER_KIND, node.name)
                        and not is_unlocked(FLOW_KIND, TOMBSTONE + node.key))
        visited.append(seen)

    # Shown: visited, or not hidden (a mark, ``unvisited = "hidden"``, a locked route).
    open_gate = [node.kind == "gate" and routes.is_open(node.name) for node in nodes]
    shown: list[bool] = []
    for i, node in enumerate(nodes):
        if node.kind == "gate":
            shown.append(False)                         # decided below
            continue
        hidden = (node.hidden or (options.unvisited == "hidden" and node.kind != "start")
                  or (node.route is not None and not open_gate[node.route]))
        shown.append(visited[i] or not hidden)
    for i, node in enumerate(nodes):                     # a locked gate with a shown pred
        if node.kind == "gate" and not open_gate[i]:
            shown[i] = any(shown[edges[e].src] for e in graph.into[i]
                           if nodes[edges[e].src].kind != "gate")

    # Titles: only for a visited, shown node; a gate's once a member is visited.
    member_seen = [False] * count
    for i, node in enumerate(nodes):
        if node.route is not None and visited[i]:
            member_seen[node.route] = True
    titles: list[Text | None] = []
    for i, node in enumerate(nodes):
        if node.kind == "gate":
            titles.append(node.title if shown[i] and member_seen[i] else None)
        else:
            titles.append(box_text(node) if visited[i] and shown[i] else None)

    # Edges between shown ends; an open gate is contracted (pred → successors, keeping the
    # pred's choices).
    chart_edges: list[ChartEdge] = []
    for e, edge in enumerate(edges):
        src, dst = edge.src, edge.dst
        if open_gate[src] or not shown[src]:
            continue
        if open_gate[dst]:
            for f in graph.out[dst]:
                out = edges[f]
                if shown[out.dst] and not open_gate[out.dst]:
                    chart_edges.append(ChartEdge(src, out.dst, (e, f), edge.choices))
        elif shown[dst]:
            chart_edges.append(ChartEdge(src, dst, (e,), edge.choices))

    def part_taken(e: int) -> bool:
        edge = edges[e]
        src = nodes[edge.src]
        if edge.choices:
            return visited[edge.src] and any(store.was_chosen(src.name, key)
                                             for key in edge.choices)
        return ((visited[edge.src] or src.kind == "gate") and edge.record is not None
                and is_unlocked(EDGE_KIND, edge.record))

    taken: list[bool] = []
    edge_texts: list[tuple[Text | None, ...]] = []
    for chart_edge in chart_edges:
        taken.append(all(part_taken(e) for e in chart_edge.parts))
        first = edges[chart_edge.parts[0]]
        if first.choices:
            src = nodes[first.src]
            picked = visited[first.src]
            edge_texts.append(tuple(
                text if picked and store.was_chosen(src.name, key) else None
                for key, text in zip(first.choices, first.texts)))
        else:
            edge_texts.append(())

    # Gates (PR-F20-12): each until ending as its text once reached.
    gates: list[GateView] = []
    for i, node in enumerate(nodes):
        if node.kind != "gate" or not shown[i]:
            continue
        info = routes.get(node.name)
        rows: list[GateRow] = []
        for name in (info.until if info is not None else ()):
            at = graph.by_id.get("ending:" + name)
            reached = endings.has(name) and is_unlocked(ENDING_KIND, name)
            text: Text | None = None
            if reached:
                ending = endings.get(name)
                assert ending is not None
                text = ((f"{ending.heading}: {ending.title}",) if ending.heading
                        else (ending.title,))
            rows.append(GateRow(at, reached, text))
        gates.append(GateView(i, titles[i], tuple(rows)))

    shown_order = sorted((i for i in range(count) if shown[i] and nodes[i].kind != "gate"),
                         key=lambda i: nodes[i].order)
    start = graph.by_id.get("start")
    fallback = start if start is not None else (shown_order[0] if shown_order else None)

    # Here and the path (in game): the last shown key of the path; shown nodes on it and the
    # edges between consecutive ones (SEC-F20-14(c)).
    here: int | None = None
    path_nodes: set[int] = set()
    path_edges: set[int] = set()
    if path is not None:
        on_path = [i for i in (graph.by_key.get(key) for key in path)
                   if i is not None and shown[i] and nodes[i].kind != "gate"]
        here = on_path[-1] if on_path else fallback
        path_nodes.update(on_path)
        between: dict[tuple[int, int], int] = {}
        for k, chart_edge in enumerate(chart_edges):
            between.setdefault((chart_edge.src, chart_edge.dst), k)
        gate_out: dict[int, list[int]] = {}
        for k, chart_edge in enumerate(chart_edges):
            if nodes[chart_edge.src].kind == "gate":
                gate_out.setdefault(chart_edge.src, []).append(k)
        for a, b in zip(on_path, on_path[1:]):
            k = between.get((a, b))
            if k is not None:
                path_edges.add(k)
                continue
            for k, chart_edge in enumerate(chart_edges):
                if chart_edge.src != a or nodes[chart_edge.dst].kind != "gate":
                    continue
                out = next((m for m in gate_out.get(chart_edge.dst, ())
                            if chart_edges[m].dst == b), None)
                if out is not None:
                    path_edges.update((k, out))
                    break

    # Recent (title, 07 §3.5 G3): the newest visited, shown key in "flowchart"'s order.
    recent: int | None = None
    for key in reversed(store.unlocked(FLOW_KIND)):
        at = graph.by_key.get(key)
        if at is not None and visited[at] and shown[at] and nodes[at].kind != "gate":
            recent = at
            break
    if recent is None:
        recent = fallback

    ending_shown = [i for i in shown_order if nodes[i].kind == "ending"]
    counts = (sum(1 for i in ending_shown if visited[i]), len(ending_shown),
              sum(1 for i in shown_order if visited[i]), len(shown_order))
    shape = ChartShape(
        kinds=tuple(node.kind for node in nodes),
        no_jump=tuple(node.no_jump for node in nodes),
        chapter=tuple(node.chapter for node in nodes),
        order=tuple(node.order for node in nodes),
        nodes=tuple(sorted((i for i in range(count) if shown[i]),
                           key=lambda i: nodes[i].order)),
        edges=tuple(chart_edges))
    return ChartRecords(shape=shape, titles=tuple(titles), edge_texts=tuple(edge_texts),
                        shown=tuple(shown), visited=tuple(visited), taken=tuple(taken),
                        gates=tuple(gates), here=here, path_nodes=frozenset(path_nodes),
                        path_edges=frozenset(path_edges), recent=recent, counts=counts)


__all__ = ["Arrived", "ChartEdge", "ChartRecords", "ChartShape", "EDGE_KIND", "EMPTY_FLOW",
           "FLOW_KIND", "FlowEdge", "FlowGraph", "FlowNode", "FlowOptions", "FlowRecorder",
           "FlowState", "FlowStates", "GateRow", "GateView", "NO_ANCHORS", "NodeKind", "START_KEY",
           "TOMBSTONE", "Text", "box_text", "chart_records", "node_key", "register",
           "register_kinds", "run_flowchart", "show_text"]
