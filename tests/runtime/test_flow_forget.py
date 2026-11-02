"""F20 s3 — ``flowchart forget`` (F20 ``06-acceptance.md`` AC-F20-21; ``04`` §7.4; ``02``
SR-F20-09..12; D1).

Run H on Template L after runs to the Sad End and the Good End on one store, plus four labels
(``f_all``, ``f_stall``, ``f_start``, ``f_river``) each running one forget line between two
lines; a new game starts at one of them (F44's start label). Files are AC-F20-44's (F20 s6);
here the recorder's memory states and pending writes are dropped and ``take_forgotten``
names the nodes."""

import pytest

from engine.core.startvalues import StartOptions
from engine.runtime import flowchart as flowchart_mod
from engine.runtime.commands import Advance, StepBack, StepForward
from engine.runtime.flowchart import EDGE_KIND, FLOW_KIND, TOMBSTONE
from engine.runtime.interpreter import RestoreResult
from engine.runtime.persistent import PersistentStore
from engine.script.flowchart import Flowchart
from tests.runtime.flow_story import (RUN_1, RUN_GOOD, key, launched, load_l, play, record,
                                      visited_ids)
from tests.runtime.story import fingerprint
from tests.script.helpers import template_l

FORGETS = "⏎".join(f'label f_{name}:⏎[4]"Before {name}."⏎[4]flowchart forget {target}⏎'
                   f'[4]"After {name}."'
                   for name, target in (("all", ""), ("stall", "stall"), ("start", "start"),
                                        ("river", "river")))
EVERY = {"start", "chapter:festival", "scene:stall", "chapter:river", "chapter:shrine",
         "ending:sad", "ending:good"}


def played(root):
    program = load_l(root, template_l(T=FORGETS))
    store = PersistentStore(identity_scheme=program.identity_scheme)
    interp = launched(program, store)
    play(interp, RUN_1)
    play(interp, RUN_GOOD)
    m21 = next(n.id for n in program.flowgraph.nodes if n.kind == "choice")
    assert visited_ids(program, store) == EVERY | {m21}
    return program, store, interp, m21


def at(text: str):
    return lambda interp: getattr(interp.current, "text", None) == text


def forget(interp, name: str) -> None:
    """A new game at ``f_<name>``, run to its "After" line."""
    interp.start = StartOptions(label=f"f_{name}")
    play(interp, until=at(f"After {name}."))
    interp.take_commands(1 << 30)


@pytest.mark.parametrize("row", ["all", "stall", "start", "river"])
def test_ac_f20_21_forget(tmp_path, row):
    program, store, interp, m21 = played(tmp_path / "l")
    graph = program.flowgraph
    expected = {"all": EVERY | {m21}, "stall": {"scene:stall", m21},
                "start": {"chapter:festival"}, "river": {"chapter:river"}}[row]
    if row == "all":
        expected = expected - {"start", "ending:sad", "ending:good"}
    others = {kind: store.unlocked(kind) for kind in ("chapter", "ending", "route")}
    def marks() -> dict:
        """Seen lines (but the forget labels' own, seen on the way) and choice marks."""
        return {form: {g: list(r.order) for g, r in store.records(form).items()
                       if not g.startswith("f_")} for form in ("seen", "chosen")}

    seen = marks()
    forget(interp, row)
    assert visited_ids(program, store) == (EVERY | {m21}) - expected, row
    tombs = {n.id for n in graph.nodes if store.is_unlocked(FLOW_KIND, TOMBSTONE + n.key)}
    assert tombs == {i for i in expected if i.startswith("chapter:")}
    # Edge records into and out of each forgotten node are relocked; states and pending
    # writes dropped; the forgotten ids (or "all") are given to app.
    forgotten = [graph.by_id[i] for i in expected]
    for e in graph.edges:
        if e.record is not None and (e.src in forgotten or e.dst in forgotten):
            assert not store.is_unlocked(EDGE_KIND, e.record)
    assert store.is_unlocked(EDGE_KIND, record(graph, "shrine", "good")) is (
        row not in ("all",))
    assert not expected & set(interp.flowchart.states)
    assert not expected & set(interp.flowchart.take_dirty())
    taken = interp.flowchart.take_forgotten()
    assert taken == "all" if row == "all" else set(taken) == expected
    # Other kinds, seen lines, and choice marks are untouched.
    assert {kind: store.unlocked(kind) for kind in others} == others
    assert marks() == seen

    # The story state and path are unchanged (fingerprint) by the line itself.
    interp.start = StartOptions(label=f"f_{row}")
    play(interp, until=at(f"Before {row}."))
    before_print, path, version = fingerprint(interp), interp.flow, store.version
    stmt = program.at(f"f_{row}", (1,))
    assert type(stmt) is Flowchart and stmt.form == "forget"
    flowchart_mod.run_flowchart(interp, stmt)
    assert fingerprint(interp) == before_print and interp.flow is path
    assert store.version == version                     # a second run changes nothing
    # StepBack over the line and a forward re-run, and a load from before it: no change.
    before = interp.checkpoint()
    interp.post(Advance(interp.current.sid))
    interp.run(10_000)
    assert interp.current.text == f"After {row}." and store.version == version
    interp.post(StepBack(1))
    interp.run(10_000)
    interp.post(StepForward(1))
    interp.run(10_000)
    assert interp.current.text == f"After {row}." and store.version == version
    assert interp.restore(before).result is RestoreResult.OK and store.version == version
    assert visited_ids(program, store) == (EVERY | {m21}) - expected
    # The next arrival at a forgotten node records it as usual.
    interp.start = None
    play(interp, RUN_1)
    again = {"all": {"chapter:festival", "scene:stall", m21, "chapter:river"},
             "stall": expected, "start": expected, "river": expected}[row]
    assert again <= visited_ids(program, store)
    assert interp.flowchart.state("scene:stall") is not None
    assert store.is_unlocked(FLOW_KIND, key(graph, "stall"))
