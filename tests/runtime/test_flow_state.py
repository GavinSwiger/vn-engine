"""F20 s3 — ``GameState.flow`` (F20 ``06-acceptance.md`` AC-F20-15; ``04`` §4, §10; TR-F20-02;
``07`` §3.2), with ``fuzz_state.py``'s ``FLOW_ROWS``."""

import dataclasses
import json

import pytest

from engine.runtime import limits
from engine.runtime.flowchart import EMPTY_FLOW, FlowState
from engine.runtime.rollback import same_step
from engine.runtime.state import GameState, StateInvalid
from tests.runtime import fuzz_state
from tests.runtime.conftest import make_state, round_trip
from tests.runtime.flow_story import RUN_1, ids, launched, load_l, play


def _scenes(count: int) -> str:
    """``count`` scene labels in a row, each with one line, then the end."""
    lines = ["label start:", '    "Hi."', "    jump s1"]
    for i in range(1, count + 1):
        lines += [f"label s{i}:", f'    flowchart scene "S{i}"', f'    "Line {i}."',
                  f"    jump s{i + 1}" if i < count else "    return"]
    return "\n".join(lines) + "\n"


def _arrivals(tmp_path, count: int) -> tuple[list[str], tuple[str, ...]]:
    program = load_l(tmp_path, _scenes(count))
    interp = launched(program)
    play(interp)
    graph = program.flowgraph
    return [graph.nodes[graph.by_id[f"scene:s{i}"]].key for i in range(1, count + 1)], \
        interp.flow.path


@pytest.mark.parametrize("tier", ["default", pytest.param("slow", marks=pytest.mark.slow)])
def test_ac_f20_15_game_state_flow(tmp_path, monkeypatch, tier):
    if tier == "slow":                                   # the real 1,000, 1,001 arrivals
        keys, path = _arrivals(tmp_path, limits.FLOW_PATH_MAX + 1)
        assert path == tuple(keys[1:]) and len(path) == 1_000
        return
    # A path of 3 keys round-trips; "flow" is always written.
    state = dataclasses.replace(make_state(), flow=FlowState(tuple(fuzz_state.flow_base()
                                                                   ["path"])))
    data = state.to_json()
    assert data["flow"] == fuzz_state.flow_base() and round_trip(state) == state
    assert make_state().to_json()["flow"] == {"path": []}
    # A save without "flow" loads as EMPTY_FLOW.
    del data["flow"]
    assert GameState.from_json(data).flow is EMPTY_FLOW
    # Hostile values: StateInvalid("flow") with no echo; an unknown 16-hex key loads.
    for name, value in fuzz_state.FLOW_ROWS.items():
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**make_state().to_json(), "flow": value})
        assert caught.value.reason == "flow", name
        assert "ZZMARK" not in str(caught.value) and "0123" not in str(caught.value), name
    unknown = GameState.from_json({**make_state().to_json(),
                                   "flow": {"path": [fuzz_state.FLOW_KEY]}})
    assert unknown.flow.path == (fuzz_state.FLOW_KEY,)
    # 1,000 keys: the cap, and the JSON stays under 19 KB.
    full = {"path": [f"{i:016x}" for i in range(1_000)]}
    assert len(FlowState.from_json(full).path) == 1_000
    assert len(json.dumps(full, ensure_ascii=True, separators=(",", ":"))) <= 19 * 1024
    # With FLOW_PATH_MAX patched to 10, 11 arrivals keep the newest 10.
    monkeypatch.setattr(limits, "FLOW_PATH_MAX", 10)
    keys, path = _arrivals(tmp_path / "eleven", 11)
    assert path == tuple(keys[1:])
    # F14's same_step sees a changed path as a different step.
    other = dataclasses.replace(state, flow=FlowState(state.flow.path[:2]))
    assert same_step(state, state) and not same_step(state, other)
    # New Game sets EMPTY_FLOW.
    program = load_l(tmp_path / "l")
    interp = launched(program)
    play(interp, RUN_1)
    assert ids(program.flowgraph, interp.flow.path)[-1] == "chapter:river"
    interp.new_game(42)
    interp.run(10_000)
    assert interp.flow is EMPTY_FLOW and interp.checkpoint().flow is EMPTY_FLOW
