"""Helpers for F20's runtime tests (F20 ``06-acceptance.md`` §0.3, §5).

- ``load_l(root, text=None, **options)``: Template L (or ``text``, e.g. ``template_l(...)``)
  in ``root`` with its ``config.toml``, loaded with ``LoadOptions(flowchart=FlowOptions(...))``
  (Graph G's load); the load must be clean.
- ``launched(program, store)`` / ``play(interp, picks)``: Run H on a launched interpreter we
  keep (the recorder lives on it): ``new_game(42)``, ``Advance`` at each line, the choice
  whose text is next in ``picks`` at each menu, every story wait ended (``end_waits``).
- ``store_r(graph, v=…, tomb=…, ch=…, e=…, ro=…, mk=…, t=…)``: Records R's store (06 §0.3),
  written by node id (``v``, ``tomb``), F18 chapter names (``ch``), F19 endings and routes
  (``e``, ``ro``), ``(menu node id, choice text)`` marks (``mk``), and ``(src id, dst id)``
  edge records (``t``); F12's, F18's, F19's, and F20's kinds registered as the runtime does.
- ``records_r(program, store, path=…, **options)``: ``chart_records`` over them.
- ``ids(graph, keys)``: node ids for keys (unknown keys as ``?<key>``).
"""

import shutil
from pathlib import Path

from engine.core.paths import GamePaths
from engine.runtime import flowchart
from engine.runtime.chapters import ChapterIndex
from engine.runtime.commands import Advance, Choose, Command
from engine.runtime.endings import EndingIndex, RouteIndex
from engine.runtime.interpreter import Interpreter, Status
from engine.runtime.launch import run_launch
from engine.runtime.persistent import PersistentStore
from engine.script import load_story
from engine.script.flowgraph import FlowGraph, FlowOptions
from engine.script.loader import LoadOptions
from engine.script.menu import Menu
from engine.script.program import Program
from tests.runtime.story import end_waits
from tests.script.helpers import F20_TEMPLATE_DIR

RUN_1 = ("Buy the red one", "By the river")             # 06 §5: Run 1 (Sad End)
RUN_GOOD = ("Buy the red one", "From the shrine steps")  # the Good End


def load_l(root: Path, text: str | None = None, *, dev: bool = False, **options) -> Program:
    """Template L (or ``text``) as ``root/script/main.vns`` beside its ``config.toml``."""
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(F20_TEMPLATE_DIR / "config.toml", root / "config.toml")
    (root / "script").mkdir(exist_ok=True)
    main = F20_TEMPLATE_DIR / "script" / "main.vns"
    data = main.read_bytes() if text is None else text.encode("utf-8")
    (root / "script" / "main.vns").write_bytes(data)
    result = load_story(GamePaths(root.resolve()),
                        LoadOptions(dev=dev, flowchart=FlowOptions(**options)))
    assert result.program is not None and not result.errors, [e.format() for e in result.errors]
    return result.program


def launched(program: Program, store: PersistentStore | None = None, **kwargs) -> Interpreter:
    if store is None:
        store = PersistentStore(identity_scheme=program.identity_scheme)
    launch = run_launch(program, persistent=store, dev=kwargs.get("dev", False))
    assert launch.namespace is not None, [e.format() for e in launch.errors]
    return Interpreter(program, launch.namespace, persistent=store, **kwargs)


def choose(interp: Interpreter, text: str) -> None:
    """Pick the choice shown as ``text`` at the waiting menu (06 §0.3 ``pick "<text>"``)."""
    menu = interp.current
    assert type(menu) is Menu
    key = next(c.key for c in menu.choices if c.text == text)
    assert key in interp.choices.waiting.pickable, text
    interp.post(Choose(menu.sid, key))


def step(interp: Interpreter, picks: list[str]) -> None:
    """One input at the line or menu waiting: ``Advance``, or the next pick."""
    current = interp.current
    if type(current) is Menu:
        choose(interp, picks.pop(0))
    else:
        interp.post(Advance(current.sid))
    interp.run(10_000)
    end_waits(interp)


def play(interp: Interpreter, picks=(), *, new: bool = True, until=None) -> None:
    """Run H: from a new game (``new``) to the end, or to the first menu once ``picks`` run
    out, or until ``until(interp)`` holds at a line or menu."""
    picks = list(picks)
    if new:
        interp.new_game(42)
        interp.run(10_000)
    end_waits(interp)
    while interp.status is Status.WAITING:
        if until is not None and until(interp):
            return
        if type(interp.current) is Menu and not picks:
            return
        step(interp, picks)


def at_line(n: int):
    """``until`` for ``play``: the story waits at line ``n``."""
    return lambda interp: interp.current is not None and interp.current.line == n


def node(graph: FlowGraph, name: str) -> int:
    """A node index by 06's short names: ``M21`` (the titled menu), ``gate``, ``start``, or
    the id's name part (``festival``, ``stall``, ``sad`` …)."""
    if name == "M21":
        return next(i for i, n in enumerate(graph.nodes) if n.kind == "choice")
    if name in ("start", "gate"):
        return next(i for i, n in enumerate(graph.nodes) if n.kind == name)
    return next(i for i, n in enumerate(graph.nodes)
                if n.kind not in ("gate", "start") and n.id.split(":", 1)[1] == name)


def key(graph: FlowGraph, name: str) -> str:
    return graph.nodes[node(graph, name)].key


def record(graph: FlowGraph, src: str, dst: str) -> str:
    return key(graph, src) + key(graph, dst)


def store_r(program: Program, *, v=(), tomb=(), ch=(), e=(), ro=(), mk=(), t=(),
            store: PersistentStore | None = None) -> PersistentStore:
    """Records R's store (06 §0.3), its kinds registered as an interpreter registers them."""
    graph = program.flowgraph
    assert graph is not None
    if store is None:
        store = PersistentStore(identity_scheme=program.identity_scheme)
    store.register_kind("chapter", known=ChapterIndex.build(program).has)
    store.register_kind("ending", known=EndingIndex.build(program).has, revocable=True)
    store.register_kind("route", revocable=True)
    flowchart.register_kinds(store, graph)
    for name in v:
        store.unlock(flowchart.FLOW_KIND, key(graph, name))
    for name in tomb:
        store.unlock(flowchart.FLOW_KIND, flowchart.TOMBSTONE + key(graph, name), quiet=True)
    for name in ch:
        store.unlock("chapter", name)
    for name in e:
        store.unlock("ending", name)
    for name in ro:
        store.unlock("route", name)
    for menu, text in mk:
        anchor = program.get(graph.nodes[node(graph, menu)].anchor)
        store.mark_chosen(anchor.sid, next(c.key for c in anchor.choices if c.text == text))
    for src, dst in t:
        store.unlock(flowchart.EDGE_KIND, record(graph, src, dst))
    store.take_new_unlocks()
    return store


def records_r(program: Program, store: PersistentStore, path=None, **options
              ) -> flowchart.ChartRecords:
    graph = program.flowgraph
    assert graph is not None
    return flowchart.chart_records(graph, store, ChapterIndex.build(program),
                                   EndingIndex.build(program), RouteIndex.build(program, store),
                                   FlowOptions(**options), path)


def path_of(graph: FlowGraph, *names: str) -> tuple[str, ...]:
    return tuple(key(graph, n) for n in names)


def ids(graph: FlowGraph, keys) -> list[str]:
    return [graph.nodes[graph.by_key[k]].id if k in graph.by_key else f"?{k}" for k in keys]


def visited_ids(program: Program, store: PersistentStore, **options) -> set[str]:
    graph = program.flowgraph
    assert graph is not None
    recs = records_r(program, store, **options)
    return {graph.nodes[i].id for i, seen in enumerate(recs.visited) if seen}


def released(interp: Interpreter) -> list[Command]:
    return interp.take_commands(1 << 30)


__all__ = ["RUN_1", "RUN_GOOD", "at_line", "choose", "ids", "key", "launched", "load_l",
           "node", "path_of", "play", "record", "records_r", "released", "step", "store_r",
           "visited_ids"]
