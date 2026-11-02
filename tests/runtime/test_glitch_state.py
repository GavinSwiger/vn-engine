"""F28 s3 — ``GameState.glitch`` (F28 ``06-acceptance.md`` AC-F28-09; ``04`` §3, §6.3, §7
items 3–4; TR-F28-01)."""

import dataclasses
import itertools
import logging

import pytest

from engine.runtime.glitch import EMPTY_GLITCH, GlitchEntry, GlitchState
from engine.runtime.stage import SpriteState, StageState
from engine.runtime.state import STATE_FORMAT, GameState, StateInvalid
from tests.runtime.conftest import make_state, round_trip

HANA = StageState("bg grain", (SpriteState("hana", "hana happy"),))
ALL = (StageState("bg grain", tuple(SpriteState(t, t + " happy")
                                    for t in ("hana", "daichi", "aiko"))))


def _set(*entries: GlitchEntry) -> GlitchState:
    state = EMPTY_GLITCH
    for entry in entries:
        state = state.with_entry(entry)
    return state


def _in(glitch: GlitchState, stage: StageState = ALL) -> GameState:
    return dataclasses.replace(make_state(), stage=stage, glitch=glitch)


def test_ac_f28_09_lasting_set_round_trips_and_hostile_sets_are_refused(caplog):
    # Canonical order from any with_entry order, and the JSON round trip.
    rows = [
        (),
        (GlitchEntry("colorshift", None),),
        (GlitchEntry("static", "small"),),
        (GlitchEntry("tear", "large"), GlitchEntry("colorshift", None),
         GlitchEntry("static", "small"), GlitchEntry("jitter", None, "aiko"),
         GlitchEntry("jitter", "large", "daichi"), GlitchEntry("jitter", "small", "hana")),
    ]
    for want in rows:
        for order in itertools.permutations(want):
            glitch = _set(*order)
            assert glitch.on == want, order
            assert round_trip(_in(glitch)).glitch == glitch
    replaced = _set(GlitchEntry("static", "small"), GlitchEntry("static", "large"))
    assert replaced.on == (GlitchEntry("static", "large"),)

    # 04 §3's JSON exactly; each removal takes only what it names.
    three = _set(GlitchEntry("jitter", "large", "hana"), GlitchEntry("static", "small"),
                 GlitchEntry("colorshift", None))
    assert three.to_json() == {"on": [{"kind": "colorshift", "size": None},
                                      {"kind": "static", "size": "small"},
                                      {"kind": "jitter", "tag": "hana", "size": "large"}]}
    jitters = three.with_entry(GlitchEntry("jitter", None, "daichi"))
    assert [e.kind for e in three.without("static", None).on] == ["colorshift", "jitter"]
    assert three.without("jitter", "daichi") is three
    assert [e.tag for e in jitters.without_tag("hana").on] == [None, None, "daichi"]
    assert [e.kind for e in jitters.without_jitter().on] == ["colorshift", "static"]
    no_hana = StageState("bg grain", (SpriteState("daichi", "daichi grin"),))
    assert [e.tag for e in jitters.on_stage(no_hana).on] == [None, None, "daichi"]

    # Hostile values: StateInvalid("glitch") only, never echoing the input.
    def entry(**fields):
        return {"kind": "static", "size": None, **fields}
    hostile = [
        {}, {"on": {}}, {"on": [], "x": 1}, [],
        {"on": [entry(kind="ZZMARK")]}, {"on": [entry(size="huge")]},
        {"on": [entry(size="Medium")]}, {"on": [entry(size=1)]},
        {"on": [entry(ZZMARK=1)]}, {"on": [{"kind": "static"}]}, {"on": [entry(tag="hana")]},
        {"on": [entry(kind="jitter")]},
        *({"on": [entry(kind="jitter", tag=tag)]} for tag in ("", "../x", "ZZMARK x", "a" * 300)),
        {"on": [entry(), entry(size="small")]},
        {"on": [entry(kind="jitter", tag=f"t{i}") for i in range(260)]},
    ]
    base = _in(EMPTY_GLITCH).to_json()
    for value in hostile:
        with pytest.raises(StateInvalid) as caught:
            GameState.from_json({**base, "glitch": value})
        assert caught.value.reason == "glitch", value
        assert "ZZMARK" not in str(caught.value)

    # No key: EMPTY_GLITCH; a jitter of a sprite not on the saved stage drops, silently;
    # "glitch" is always written; format stays 1.
    data = _in(EMPTY_GLITCH, HANA).to_json()
    assert data["glitch"] == {"on": []} and data["format"] == STATE_FORMAT == 1
    del data["glitch"]
    assert GameState.from_json(data).glitch is EMPTY_GLITCH
    caplog.set_level(logging.DEBUG)
    loaded = GameState.from_json({**data, "glitch": {"on": [
        {"kind": "jitter", "tag": "daichi", "size": None},
        {"kind": "jitter", "tag": "hana", "size": None}]}})
    assert loaded.glitch.on == (GlitchEntry("jitter", None, "hana"),)
    assert caplog.records == []
