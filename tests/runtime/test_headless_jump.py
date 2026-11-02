"""F20 s4 — the headless jump (F20 ``06-acceptance.md`` AC-F20-29, 34, 50; ``04`` §7.6
"Headless"; ``07`` §3.5 G2; SEC-F20-13, TR-F20-06).

Harness **Run H** (06 §0.3): ``run_headless(program, seed=42, persistent=store, flow=holder,
inputs=…)`` on Template L, one store and one ``FlowStates`` holder shared across runs.
Reached nodes and taken records are the holder's ``reached`` and ``taken`` (07 §3.5 G2).

Not here (F20 s6): AC-F20-29's App F row (the windowed jump through ``FlowService``); here the
headless burst is compared with ``RuntimeStoryDriver.restore(..., fresh_menu=True)``, the
call the windowed jump makes. 06 counts "five" non-choice records on run 1; Template L's
graph has four (start → festival → stall → M21, river → sad: M21 → river is a choice)."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from engine.app.story import RuntimeStoryDriver
from engine.core.startvalues import StartOptions
from engine.runtime.commands import ShowMenu
from engine.runtime.flowchart import FlowStates
from engine.runtime.headless import HeadlessInputError, run_headless
from engine.runtime.menu import plain_text
from engine.runtime.persistent import PersistentStore
from tests.runtime.flow_story import (at_line, key, launched, load_l, node, play, record,
                                      released, visited_ids)
from tests.script.helpers import template_l

RUN_1 = ["advance"] * 3 + ["choose 1", "advance", "choose 1"]   # red lantern, the river


def m21_id(program) -> str:
    graph = program.flowgraph
    return graph.nodes[node(graph, "M21")].id


def menus(commands) -> list[list[str]]:
    return [[plain_text(c.body) for c in cmd.choices] for cmd in commands
            if type(cmd) is ShowMenu]


def run(program, store, holder, inputs, **kwargs):
    return run_headless(program, seed=42, persistent=store, flow=holder, inputs=inputs,
                        **kwargs)


def fresh(program):
    return PersistentStore(identity_scheme=program.identity_scheme), FlowStates()


# --- AC-F20-29 — headless jump ---------------------------------------------------------------

def test_ac_f20_29_headless_jump(tmp_path):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    store, holder = fresh(program)
    m21 = m21_id(program)

    run(program, store, holder, RUN_1)
    assert holder.reached == ["chapter:festival", "scene:stall", m21, "chapter:river",
                              "ending:sad"]
    assert holder.taken == [record(graph, *pair) for pair in (
        ("start", "festival"), ("festival", "stall"), ("stall", "M21"), ("river", "sad"))]
    assert list(holder) == ["chapter:festival", "scene:stall", m21, "chapter:river"]

    # Run 2: the jump restores M21 (lantern red, coins 0); the shrine reaches good.
    commands = run(program, store, holder, [f"jump {m21}", "choose 2"])
    assert menus(commands)[-1] == ["By the river", "From the shrine steps"]
    assert holder.reached[-2:] == ["chapter:shrine", "ending:good"]
    shrine = holder["chapter:shrine"].variables
    assert (shrine["lantern"], shrine["coins"]) == ("red", 0)
    assert store.is_unlocked("ending", "good")

    # The jump's burst equals the windowed jump's restore of the same state (TR-F20-06).
    commands = run(program, store, holder, [f"jump {m21}"])
    interp = launched(program, store)
    play(interp, until=at_line(6))
    released(interp)
    driver = RuntimeStoryDriver(interp, clock=lambda: 0.0, fixed_seed=42)
    driver.restore(holder[m21], fresh_menu=True)
    burst = released(interp)
    assert commands[-len(burst):] == burst and type(burst[-1]) is ShowMenu

    # A state whose point moved: the retry with hints lands at the nearest point.
    state = holder[m21]
    holder[m21] = replace(state, position="stall/0123456789ab")
    commands = run(program, store, holder, [f"jump {m21}"])
    assert commands[-1].sid == state.position and commands[-1].restored


# --- AC-F20-34 — the Paper Lanterns walkthrough -----------------------------------------------

RELOCK = 'label relock:⏎    lock ending sad⏎    lock ending good⏎    "Locked."'


def test_ac_f20_34_paper_lanterns_walkthrough(tmp_path):
    program = load_l(tmp_path / "l", template_l(T=RELOCK))
    store, holder = fresh(program)
    m21 = m21_id(program)

    run(program, store, holder, RUN_1)                  # 1. the Sad End
    assert "ending:sad" in visited_ids(program, store)

    # 2. Jump: red lantern, two choices; the shrine; back from its last line stops at M21;
    # then the Good End.
    commands = run(program, store, holder, [f"jump {m21}", "choose 2", "back 5", "choose 2",
                                            "advance"])
    assert menus(commands) == [["By the river", "From the shrine steps"]] * 2
    jumped, back = (c for c in commands if type(c) is ShowMenu)
    assert jumped.restored and back.restored and back.sid == jumped.sid
    assert holder["chapter:shrine"].variables["lantern"] == "red"
    assert "ending:good" in visited_ids(program, store)

    # 3. The route is open now: the jump offers the bridge, which reaches the True End.
    commands = run(program, store, holder, [f"jump {m21}", "choose 3"])
    assert menus(commands)[-1][-1] == "Wait at the bridge"
    assert store.is_unlocked("ending", "true")

    # 4. lock ending sad and good: both ??? again; the other nodes stay visited.
    run(program, store, holder, [], start=StartOptions(label="relock"))
    seen = visited_ids(program, store)
    assert not {"ending:sad", "ending:good"} & seen
    assert {"chapter:festival", "scene:stall", m21, "chapter:river", "chapter:shrine"} <= seen


# --- AC-F20-50 — group J: headless jump is total -----------------------------------------------

class CountingIds(dict):
    gets = 0

    def get(self, name, default=None):
        CountingIds.gets += 1
        return super().get(name, default)


def test_ac_f20_50_headless_jump_is_total(tmp_path, monkeypatch):
    program = load_l(tmp_path / "l")
    graph = program.flowgraph
    store, holder = fresh(program)
    run(program, store, holder, RUN_1)
    m21 = m21_id(program)

    def refused(text: str) -> str:
        with pytest.raises(HeadlessInputError) as caught:
            run(program, store, holder, [text])
        message = str(caught.value)
        assert "Traceback" not in message and len(message) <= 400
        assert not any(ch in message for ch in "\x00‮\n")
        return message

    # The id is refused before any lookup when too long; else looked up exactly, once.
    spy = CountingIds(graph.by_id)
    real = graph.by_id
    object.__setattr__(graph, "by_id", spy)
    try:
        assert "needs a box id" in refused("jump")
        assert "1,200" in refused("jump " + "s" * 1_201) and CountingIds.gets == 0
        opened: list = []
        for name in ("open", "scandir", "listdir", "stat", "lstat"):
            real_fn = getattr(os, name)
            monkeypatch.setattr(os, name, lambda *a, _f=real_fn, **k: (opened.append(a),
                                                                       _f(*a, **k))[1])
        monkeypatch.setattr(Path, "open", lambda *a, **k: opened.append(a))
        for bad in ("../x", "scene:a\x00", "scene:‮stall", "Scene:stall",
                    "ｓcene:stall", "scene:nowhere"):
            assert "has no box" in refused("jump " + bad), bad
        assert opened == [] and CountingIds.gets == 6
    finally:
        object.__setattr__(graph, "by_id", real)
        monkeypatch.undo()
    assert "no state" in refused("jump chapter:shrine")
    state = holder[m21]
    holder[m21] = replace(state, identity_scheme=state.identity_scheme + 1)
    assert "scheme_mismatch" in refused(f"jump {m21}")

    # The holder takes GameState values only, and keeps the newest 256.
    with pytest.raises(ValueError):
        holder["scene:stall"] = {"position": "x"}
    keep = FlowStates()
    for i in range(257):
        keep[f"scene:s{i}"] = state
    assert len(keep) == 256 and "scene:s0" not in keep and list(keep)[-1] == "scene:s256"
    assert key(graph, "stall") in holder["scene:stall"].flow.path
