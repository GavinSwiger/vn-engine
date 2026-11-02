"""F20 s3 — what the page may show (``chart_records``; F20 ``06-acceptance.md`` AC-F20-17, 18,
19, 23, and the store rows of AC-F20-10 and 12; ``04`` §7.3; ``07`` §3.5 G3, G4).

Harness **Records R** (06 §0.3): ``chart_records`` on Template L's graph over a store written
as ``v=(…)``, ``tomb=(…)``, ``ch=(…)``, ``e=(…)``, ``ro=(…)``, ``mk=(…)``, ``t=(…)``
(``flow_story.store_r``) and ``path=(…)``. Rows that need a run use Run H or Driver D.

Not here: the Jump and reason halves of AC-F20-17's first row (``flowchart_no_state``) are
``FlowService``'s (F20 s6); here the recorder holds no state for the node. AC-F20-12's third
row ("``e=(sad, good)``, route still locked in store") reads as F19 decides it: with both
``until`` endings reached the route is open (``RouteIndex.is_open``, W132), so its gate is
contracted and not drawn; ``promise`` and ``true`` stay unshown, as the row says."""

import json

from engine.runtime.commands import StepBack
from engine.runtime.flowchart import FLOW_KIND
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import GameState
from tests.runtime.flow_story import (RUN_1, at_line, launched, load_l, node, path_of, play,
                                      records_r, store_r)
from tests.script.helpers import template_l


def edge(program, recs, src: str, dst: str) -> int | None:
    """The index in ``recs.shape.edges`` of the drawn edge ``src → dst`` (None: not drawn)."""
    graph = program.flowgraph
    a, b = node(graph, src), node(graph, dst)
    return next((k for k, e in enumerate(recs.shape.edges) if (e.src, e.dst) == (a, b)), None)


def texts(recs) -> list[str]:
    """Every text part ``recs`` holds (titles, choice texts, gate rows)."""
    out: list[str] = []
    for text in [*recs.titles, *(t for ts in recs.edge_texts for t in ts),
                 *(g.title for g in recs.gates),
                 *(r.text for g in recs.gates for r in g.rows)]:
        out.extend(part for part in (text or ()) if part is not None)
    return out


# --- AC-F20-17 — records from F18 and F19 ----------------------------------------------------------

def test_ac_f20_17_records_from_f18_and_f19(tmp_path):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    river, sad = node(graph, "river"), node(graph, "sad")
    # A game that had no flowchart: F18's record alone; no state is held for it.
    store = store_r(program, ch=("river",))
    assert records_r(program, store).visited[river]
    assert launched(program, store).flowchart.state("chapter:river") is None
    # With F20's tombstone it is unvisited; a re-arrival takes the tombstone back.
    store = store_r(program, ch=("river",), tomb=("river",))
    recs = records_r(program, store)
    assert not recs.visited[river] and recs.titles[river] is None
    play(launched(program, store), RUN_1)
    recs = records_r(program, store)
    assert recs.visited[river] and not store.is_unlocked(FLOW_KIND, "x" + graph.nodes[river].key)
    # Endings follow F19 only.
    store = store_r(program, e=("sad",))
    assert records_r(program, store).visited[sad]
    store.relock("ending", "sad")                       # lock ending sad
    recs = records_r(program, store)
    assert not recs.visited[sad] and recs.titles[sad] is None
    recs = records_r(program, store_r(program, v=("sad",)))
    assert not recs.visited[sad] and recs.titles[sad] is None


# --- AC-F20-18 — taken edges ----------------------------------------------------------------------

def test_ac_f20_18_taken_edges(tmp_path):
    program = load_l(tmp_path / "l")
    seen = ("festival", "stall", "M21")
    recs = records_r(program, store_r(program, v=seen, mk=(("M21", "By the river"),)))
    river, shrine, gate = (edge(program, recs, "M21", n) for n in ("river", "shrine", "gate"))
    assert recs.taken[river] and not recs.taken[shrine] and not recs.taken[gate]
    assert recs.edge_texts[river] == (("By the river",),)
    assert recs.edge_texts[shrine] == (None,) and recs.edge_texts[gate] == (None,)
    # festival → stall is taken iff its record is held.
    stall = edge(program, recs, "festival", "stall")
    assert not recs.taken[stall]
    recs = records_r(program, store_r(program, v=seen, t=(("festival", "stall"),)))
    assert recs.taken[edge(program, recs, "festival", "stall")]
    # M21 forgotten (unvisited) with its pick still marked: nothing out of it is taken.
    recs = records_r(program, store_r(program, v=("festival", "stall"),
                                      mk=(("M21", "By the river"),)))
    out = [k for k, e in enumerate(recs.shape.edges)
           if e.src == node(program.flowgraph, "M21")]
    assert len(out) == 3 and not any(recs.taken[k] for k in out)
    assert all(recs.edge_texts[k] == (None,) for k in out)
    # The contracted M21 → promise (route open, promise visited): both parts must be taken.
    bridge = (("M21", "Wait at the bridge"),)
    for marks, records, taken in ((bridge, (("gate", "promise"),), True),
                                  (bridge, (), False), ((), (("gate", "promise"),), False)):
        recs = records_r(program, store_r(program, v=(*seen, "promise"), ro=("promise",),
                                          mk=marks, t=records))
        k = edge(program, recs, "M21", "promise")
        assert k is not None and len(recs.shape.edges[k].parts) == 2
        assert recs.taken[k] is taken, (marks, records)
        assert edge(program, recs, "M21", "gate") is None


# --- AC-F20-19 — "You are here", the path, and recency ---------------------------------------------

def test_ac_f20_19_here_path_and_recency(tmp_path):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    n = lambda name: node(graph, name)                          # noqa: E731
    store = store_r(program, v=("festival", "stall", "M21"))
    recs = records_r(program, store, path=())
    assert recs.here == n("start") and recs.path_nodes == frozenset() == recs.path_edges
    recs = records_r(program, store, path=path_of(graph, "festival", "stall"))
    assert recs.here == n("stall") and recs.path_nodes == {n("festival"), n("stall")}
    assert recs.path_edges == {edge(program, recs, "festival", "stall")}
    recs = records_r(program, store, path=path_of(graph, "festival", "stall", "M21", "promise"))
    assert not recs.shown[n("promise")]
    assert recs.here == n("M21") and recs.path_nodes == {n("festival"), n("stall"), n("M21")}
    assert recs.path_edges == {edge(program, recs, "festival", "stall"),
                               edge(program, recs, "stall", "M21")}
    recs = records_r(program, store, path=path_of(graph, "festival", "stall") + ("0" * 16,))
    assert recs.here == n("stall") and len(recs.path_nodes) == 2
    # From the title after run 1: no here, no path; recent is the Sad End.
    played = store_r(program)
    play(launched(program, played), RUN_1)
    recs = records_r(program, played, path=None)
    assert recs.here is None and recs.path_nodes == frozenset() and recs.recent == n("sad")
    # Driver D: after a back-step, a load, and a jump (here a restore of k_21, which a jump
    # is), "here" follows the restored state's path.
    interp = launched(program, played)
    play(interp, RUN_1, until=at_line(21))
    k21 = GameState.from_json(json.loads(json.dumps(interp.checkpoint().to_json())))
    play(interp, RUN_1[1:], new=False, until=at_line(30))
    assert records_r(program, played, interp.flow.path).here == n("river")
    interp.post(StepBack(1))
    interp.run(10_000)
    assert interp.current.line == 21
    assert records_r(program, played, interp.flow.path).here == n("M21")
    play(interp, RUN_1, until=at_line(12))
    assert records_r(program, played, interp.flow.path).here == n("stall")
    assert interp.restore(k21).result is RestoreResult.OK
    assert records_r(program, played, interp.flow.path).here == n("M21")


# --- AC-F20-23 — shown, ???, and hidden ------------------------------------------------------------

def test_ac_f20_23_shown_mystery_and_hidden(tmp_path):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    n = lambda name: node(graph, name)                          # noqa: E731
    seen = ("festival", "stall", "M21", "river")
    recs = records_r(program, store_r(program, v=seen))
    assert recs.shown[n("shrine")] and recs.titles[n("shrine")] is None
    assert not recs.shown[n("true")]
    hidden = records_r(program, store_r(program, v=seen), unvisited="hidden")
    assert not hidden.shown[n("shrine")] and n("shrine") not in hidden.shape.nodes
    assert all(n("shrine") not in (e.src, e.dst) for e in hidden.shape.edges)
    assert hidden.shown[n("river")] and hidden.shown[n("start")]
    opened = records_r(program, store_r(program, v=seen, ro=("promise",)))
    assert not opened.shown[n("promise")]
    visited = records_r(program, store_r(program, v=(*seen, "promise")))
    assert visited.shown[n("promise")] and visited.titles[n("promise")] == ("The Promise",)
    # A locked-route member with no mark: unshown until visited.
    plain = load_l(tmp_path / "plain", template_l(replace={37: '    flowchart scene "Plain"'}))
    pn = node(plain.flowgraph, "promise")
    assert not records_r(plain, store_r(plain, v=seen)).shown[pn]
    assert records_r(plain, store_r(plain, v=(*seen, "promise"))).shown[pn]
    # An edge is drawn iff both ends are shown; unshown nodes aren't walked.
    for r in (recs, hidden, opened, visited):
        assert all(r.shown[e.src] and r.shown[e.dst] for e in r.shape.edges)
        assert set(r.shape.nodes) == {i for i, s in enumerate(r.shown) if s}
        assert all(r.titles[i] is None for i, s in enumerate(r.shown) if not s)


# --- AC-F20-10 (run-time row) and AC-F20-12 (store rows) -------------------------------------------

def test_ac_f20_10_no_value_reaches_the_records(tmp_path):
    text = template_l(replace={22: '        "Take {var=player_name} by the river":'},
                      T='default player_name = "QXV"')
    program = load_l(tmp_path / "q", text)
    store = store_r(program)
    interp = launched(program, store)
    play(interp, ("Buy the red one", "Take {var=player_name} by the river"))
    assert interp.G["player_name"] == "QXV"
    in_game = records_r(program, store, path=interp.flow.path)
    title = records_r(program, store, path=None)
    assert not any("QXV" in part for part in texts(in_game))
    k = edge(program, in_game, "M21", "river")
    assert in_game.taken[k] and in_game.edge_texts[k] == (("Take ", None, " by the river"),)
    assert texts(title) == texts(in_game) and title.edge_texts == in_game.edge_texts


def test_ac_f20_12_gate_store_rows(tmp_path):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    n = lambda name: node(graph, name)                          # noqa: E731
    sad_text = ("Sad End: Paper Ashes",)

    def gate_of(recs):
        return next((g for g in recs.gates if g.node == n("gate")), None)

    recs = records_r(program, store_r(program))
    gate = gate_of(recs)
    assert recs.shown[n("gate")] and gate.title is None and recs.titles[n("gate")] is None
    assert [(r.reached, r.text) for r in gate.rows] == [(False, None), (False, None)]
    assert [r.ending for r in gate.rows] == [n("sad"), n("good")]
    assert not recs.shown[n("promise")] and not recs.shown[n("true")]
    gate = gate_of(records_r(program, store_r(program, e=("sad",))))
    assert [(r.reached, r.text) for r in gate.rows] == [(True, sad_text), (False, None)]
    both = records_r(program, store_r(program, e=("sad", "good")))       # open (F19)
    assert gate_of(both) is None and not both.shown[n("gate")]
    assert not both.shown[n("promise")] and not both.shown[n("true")]
    recs = records_r(program, store_r(program, v=("promise",)))
    assert gate_of(recs).title == ("Hana's Promise",)
    assert recs.shown[n("promise")] and not recs.shown[n("true")]
    recs = records_r(program, store_r(program, v=("festival", "stall", "M21"), ro=("promise",)))
    assert not recs.shown[n("gate")] and not recs.shown[n("promise")]
    assert edge(program, recs, "M21", "promise") is None
    recs = records_r(program, store_r(program, v=("festival", "stall", "M21", "promise"),
                                      ro=("promise",)))
    k = edge(program, recs, "M21", "promise")
    menu = program.get(graph.nodes[n("M21")].anchor)
    assert recs.shape.edges[k].choices == (menu.choices[2].key,)      # "Wait at the bridge"
    assert recs.edge_texts[k] == (None,)                               # not picked yet
