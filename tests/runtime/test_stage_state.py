"""F04 step 4 — the stage state, unit (F04 ``06-acceptance.md`` §1.2, §1.3, §1.5): AC-F04-08
(``show``), 13 (positions as written), 14 (layers, order, ``behind``), 15 (zoom and flip),
19 (plain story state; JSON round trip with exact number types, TR-F04-02), 23 (hostile
saved stages). Statements are parsed by F04's own parser and applied through ``shown``,
``hidden``, and ``StageState(...)`` exactly as ``run_show``, ``run_hide``, and ``run_scene``
apply them. Stages are written in §0.5's notation (``stage_story.stage``).
"""

import json
import math
from types import SimpleNamespace

import pytest

from engine.core.constants import BUILTIN_POSITIONS
from engine.runtime import stage as stage_mod
from engine.runtime.interpreter import EXECUTORS, Step
from engine.runtime.glitch import EMPTY_GLITCH, PendingGlitch
from engine.runtime.stage import (EMPTY_STAGE, SpriteState, StageInvalid, StageState, hidden,
                                  shown)
from engine.runtime.state import GameState, StateInvalid
from engine.script.diagnostics import DiagnosticSink
from engine.script.stage import Hide, Scene, Show
from engine.script.statements import ParseContext
from tests.runtime import fuzz_stage
from tests.runtime.conftest import state_b_json
from tests.runtime.stage_story import (IMG_L, lanterns, launched, run_h, same_types, stage,
                                       stages)
from tests.runtime.story import fingerprint, start
from tests.script.helpers import parse_text


def statements(*lines: str) -> list:
    """``lines`` parsed inside ``label start:`` (positions: built-ins and ``stall_spot``)."""
    ctx = ParseContext(sink=DiagnosticSink(),
                       position_names=frozenset([*BUILTIN_POSITIONS, "stall_spot"]))
    parsed = parse_text("label start:\n" + "".join(f"    {s}\n" for s in lines), ctx=ctx)
    assert parsed.errors == [], parsed.messages
    (label,) = parsed.nodes
    return list(label.block)


def apply(start: StageState, *lines: str) -> StageState:
    s = start
    for node in statements(*lines):
        if type(node) is Show:
            s = shown(s, node)
        elif type(node) is Hide:
            s = hidden(s, node.tag)
        else:
            assert type(node) is Scene
            s = StageState(node.image, ())
    return s


class FakeInterp:
    stage = EMPTY_STAGE
    glitch = EMPTY_GLITCH                   # F28: hide and scene prune jitter
    pending_glitch = PendingGlitch()
    timeline = SimpleNamespace(replaying=False)                 # F34: scene/show call
    program = SimpleNamespace(gallery_pictures={})              # gallery.seen (no picture)


def test_executors_change_only_the_stage_and_continue():
    """``run_scene``, ``run_show``, ``run_hide`` are the registered executors, each one step
    that changes ``interp.stage`` and continues (04 §6.2)."""
    assert EXECUTORS[Scene] is stage_mod.run_scene
    assert EXECUTORS[Show] is stage_mod.run_show
    assert EXECUTORS[Hide] is stage_mod.run_hide
    interp = FakeInterp()
    scene, show, hide = statements("scene bg bridge", "show hana happy", "hide hana")
    assert stage_mod.run_scene(interp, scene) is Step.CONTINUE
    assert interp.stage == stage("bg bridge |")
    assert stage_mod.run_show(interp, show) is Step.CONTINUE
    assert interp.stage == stage("bg bridge | hana happy@center")
    assert stage_mod.run_hide(interp, hide) is Step.CONTINUE
    assert interp.stage == stage("bg bridge |")


# --- AC-F04-08 — show -------------------------------------------------------------------------

@pytest.mark.parametrize("start, lines, result", [
    ("∅ |", ["show hana happy"], "∅ | hana happy@center"),
    ("∅ | hana happy@left", ["show hana sad"], "∅ | hana sad@left"),
    ("∅ | hana happy@left z2 flip", ["show hana sad at right"], "∅ | hana sad@right z2 flip"),
    ("∅ | hana happy@left", ["show hana at right"], "∅ | hana happy@right"),
    ("∅ | hana happy@left", ["show hana"], "∅ | hana happy@left"),
    ("∅ |", ["show hana"], "∅ | hana=hana@center"),
    ("∅ | hana happy@left, stall@center", ["show hana sad"], "∅ | hana sad@left, stall@center"),
    ("∅ | hana happy@left z2 flip L3", ["hide hana", "show hana sad"], "∅ | hana sad@center"),
], ids=["new", "image", "image-and-at", "one-word-moves", "one-word-only", "image-hana",
        "order-kept", "hide-resets"])
def test_ac_f04_08_show(start, lines, result):
    got = apply(stage(start), *lines)
    assert got == stage(result)
    assert got.sprites[0].image == stage(result).sprites[0].image


def test_ac_f04_08_sprites_stay_after_return(tmp_path):
    from tests.runtime.stage_story import story_game
    program = story_game(tmp_path, ["call side", '"After."'],
                         top="label side:\n    show daichi grin\n    return\n")
    assert stages(run_h(program)) == [stage("∅ | daichi grin@center")]


# --- AC-F04-13 — positions as written ---------------------------------------------------------

@pytest.mark.parametrize("line, at, as_json", [
    ("show hana happy", "center", "center"),
    ("show hana happy at stall_spot", "stall_spot", "stall_spot"),
    ("show hana happy at 400", (400,), [400]),
    ("show hana happy at 400.5 680", (400.5, 680), [400.5, 680]),
    ("show hana happy at -1280 2560", (-1280, 2560), [-1280, 2560]),
])
def test_ac_f04_13_positions_are_kept_as_written(line, at, as_json):
    (sprite,) = apply(EMPTY_STAGE, line).sprites
    assert sprite.at == at and type(sprite.at) is type(at)
    if type(at) is tuple:
        assert [type(v) for v in sprite.at] == [type(v) for v in at]
    text = json.dumps(sprite.to_json()["at"])
    assert json.loads(text) == as_json and text == json.dumps(as_json)


# --- AC-F04-14 — layers, order, and behind ----------------------------------------------------

def order(s: StageState) -> str:
    return ", ".join(sp.tag + (f" L{sp.layer}" if sp.layer else "") for sp in s.sprites)


def tags(text: str) -> StageState:
    """``a, b L5`` → sprites tagged and named a, b (layer 5) at center."""
    if not text:
        return EMPTY_STAGE
    out = []
    for item in text.split(", "):
        tag, _, layer = item.partition(" L")
        out.append(SpriteState(tag, tag, "center", int(layer or 0)))
    return StageState(None, tuple(out))


@pytest.mark.parametrize("start, lines, result", [
    ("", ["show a", "show b", "show c"], "a, b, c"),
    ("a, b, c", ["show a at left", "show a zoom 2", "show a happy"], "a, b, c"),
    ("a, b, c", ["hide a", "show a"], "b, c, a"),
    ("a, b, c", ["show a layer 0"], "a, b, c"),
    ("a, b, c", ["show a layer 5"], "b, c, a L5"),
    ("desk L10", ["show witness"], "witness, desk L10"),
    ("a, desk L10", ["show witness behind desk"], "a, witness L10, desk L10"),
    ("a, b, c", ["show c behind a"], "c, a, b"),
    ("a, b", ["show a behind a", "show a behind zz"], "a, b"),
    ("a L-100, b L100", ["show c"], "a L-100, c, b L100"),
], ids=["append", "place-kept", "hide-show-front", "same-layer", "new-layer", "below-layer",
        "behind-takes-layer", "behind-moves", "behind-no-effect", "between-layers"])
def test_ac_f04_14_layers_order_and_behind(start, lines, result):
    got = apply(tags(start), *lines)
    assert order(got) == result
    layers = [s.layer for s in got.sprites]
    assert layers == sorted(layers)                         # draw order (04 §4.1)


# --- AC-F04-15 — zoom and flip are kept until changed ----------------------------------------

def test_ac_f04_15_zoom_and_flip_are_kept():
    s0 = apply(EMPTY_STAGE, "show hana happy zoom 1.5 flip on")
    s1 = apply(s0, "show hana sad")
    s2 = apply(s1, "show hana flip off")
    assert [s0, s1, s2] == [stage("∅ | hana happy@center z1.5 flip"),
                            stage("∅ | hana sad@center z1.5 flip"),
                            stage("∅ | hana sad@center z1.5")]


@pytest.mark.parametrize("line, zoom", [("show hana zoom 2", 2.0), ("show hana zoom 0.25", 0.25),
                                        ("show hana zoom 4", 4.0)])
def test_ac_f04_15_zoom_is_a_float(line, zoom):
    (sprite,) = apply(EMPTY_STAGE, line).sprites
    assert sprite.zoom == zoom and type(sprite.zoom) is float


# --- AC-F04-19 — the stage is plain story state -----------------------------------------------

LINE_7 = {"background": "bg river_night", "sprites": [
    {"tag": "daichi", "image": "daichi sigh", "at": [1120], "layer": 0, "zoom": 1.0,
     "flip": False},
    {"tag": "stall", "image": "stall", "at": "stall_spot", "layer": 0, "zoom": 1.0,
     "flip": False},
    {"tag": "hana", "image": "hana happy", "at": "hana_close", "layer": 0, "zoom": 1.0,
     "flip": False}]}


def lantern_checkpoints(tmp_path) -> list[GameState]:
    from tests.runtime.story import checkpoints
    program = lanterns(tmp_path / "lanterns")
    interp = launched(program)
    interp.new_game(42)
    interp.run(10_000)
    return checkpoints(interp)


def test_ac_f04_19_the_saved_stage_is_names_only(tmp_path):
    states = lantern_checkpoints(tmp_path)
    assert len(states) == 9
    for state in states:
        data = state.to_json()["stage"]
        assert data.keys() == {"background", "sprites"}
        for sprite in data["sprites"]:
            assert sprite.keys() == {"tag", "image", "at", "layer", "zoom", "flip"}
        text = json.dumps(data)
        assert "/" not in text and ".png" not in text
        assert not any(k in text for k in ("width", "height", "size", "path", "ref"))
    assert states[6].to_json()["stage"] == LINE_7
    assert type(LINE_7["sprites"][0]["at"][0]) is int


def test_ac_f04_19_round_trip_keeps_number_types(tmp_path):
    lantern_stages = [s.stage for s in lantern_checkpoints(tmp_path)]
    for s in [*lantern_stages, *fuzz_stage.valid_stages(200, seed=1)]:
        back = StageState.from_json(json.loads(json.dumps(s.to_json())))
        assert same_types(back, s), s


def test_ac_f04_19_example_game_stages_round_trip(tmp_path):
    """The example game (``game/``) at every checkpoint: AC-F03-55 with ``stage``."""
    from tests.runtime.stage_story import load_example
    from tests.runtime.story import checkpoints
    program = load_example().program
    assert program is not None
    for state in checkpoints(start(program, seed=1)):
        back = GameState.from_json(json.loads(json.dumps(state.to_json())))
        assert back == state and same_types(back.stage, state.stage)


# --- AC-F04-23 — hostile saved stages are rejected -------------------------------------------

def sprite(**changes) -> dict:
    return {"tag": "hana", "image": "hana happy", "at": "center", "layer": 0, "zoom": 1.0,
            "flip": False, **changes}


def with_sprites(*sprites) -> dict:
    return {"background": "bg dusk", "sprites": list(sprites)}


def many(n: int) -> dict:
    return with_sprites(*(sprite(tag=f"t{i}") for i in range(n)))


def missing(key: str) -> dict:
    s = sprite()
    del s[key]
    return with_sprites(s)


BAD_STAGES = {
    "list": [], "null": None, "one-key": {"background": None},
    "extra-key": {"background": None, "sprites": [], "x": 1},
    "bg-empty": {"background": "", "sprites": []},
    "bg-two-spaces": {"background": "bg  dusk", "sprites": []},
    "bg-six-words": {"background": "a b c d e f", "sprites": []},
    "bg-path": {"background": "../x.png", "sprites": []},
    "bg-stage-word": {"background": "zoom", "sprites": []},
    "bg-statement-word": {"background": "call", "sprites": []},
    "bg-number": {"background": 5, "sprites": []},
    "bg-513": {"background": "a " * 256 + "a", "sprites": []},
    "bg-word-101": {"background": "x" * 101, "sprites": []},
    "257-sprites": many(257), "no-flip": missing("flip"),
    "seventh-key": with_sprites(sprite(extra=1)),
    "duplicate-tag": with_sprites(sprite(), sprite(image="hana sad")),
    "tag-two-words": with_sprites(sprite(tag="a b")), "tag-empty": with_sprites(sprite(tag="")),
    "tag-number": with_sprites(sprite(tag=7)),
    "at-empty": with_sprites(sprite(at=[])), "at-three": with_sprites(sprite(at=[1, 2, 3])),
    "at-bool": with_sprites(sprite(at=[True])),
    "at-nan": with_sprites(sprite(at=[float("nan")])),
    "at-3000": with_sprites(sprite(at=[3000])), "at-1281": with_sprites(sprite(at=[-1281])),
    "at-two-words": with_sprites(sprite(at="le ft")),
    "at-word-101": with_sprites(sprite(at="x" * 101)),
    "layer-101": with_sprites(sprite(layer=101)), "layer-float": with_sprites(sprite(layer=1.0)),
    "layer-bool": with_sprites(sprite(layer=True)),
    "layer-order": with_sprites(sprite(tag="a", layer=5), sprite(tag="b", layer=0)),
    "zoom-0.2": with_sprites(sprite(zoom=0.2)), "zoom-text": with_sprites(sprite(zoom="1")),
    "zoom-bool": with_sprites(sprite(zoom=True)),
    "zoom-inf": with_sprites(sprite(zoom=float("inf"))),
    "flip-1": with_sprites(sprite(flip=1)), "flip-on": with_sprites(sprite(flip="on")),
}


def state_with(stage_value) -> dict:
    data = state_b_json()
    data["stage"] = stage_value
    return data


@pytest.mark.parametrize("value", BAD_STAGES.values(), ids=BAD_STAGES.keys())
def test_ac_f04_23_hostile_stages_are_rejected(value):
    with pytest.raises(StateInvalid) as caught:
        GameState.from_json(json.loads(json.dumps(state_with(value))))
    assert caught.value.reason == "stage"
    assert str(caught.value) == "the story state is not valid (stage)"   # nothing echoed
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


@pytest.mark.parametrize("value, check", [
    (many(256), lambda s: len(s.sprites) == 256),
    (with_sprites(sprite(at="no_such_place")), lambda s: s.sprites[0].at == "no_such_place"),
    (with_sprites(sprite(zoom=2)), lambda s: s.sprites[0].zoom == 2.0
     and type(s.sprites[0].zoom) is float),
], ids=["256-sprites", "unknown-position-name", "zoom-int"])
def test_ac_f04_23_edges_are_accepted(value, check):
    assert check(GameState.from_json(state_with(value)).stage)


def test_ac_f04_23_a_refused_restore_changes_nothing(tmp_path):
    """The restore of a state built around a hostile stage never starts: ``from_json``
    refuses it first (AC-F03-63 fingerprint)."""
    from tests.runtime.story import load_r
    interp = start(load_r(tmp_path))
    before = fingerprint(interp), interp.stage, interp._stage_shown
    for value in BAD_STAGES.values():
        with pytest.raises(StateInvalid):
            interp.restore(GameState.from_json(state_with(value)))
    assert (fingerprint(interp), interp.stage, interp._stage_shown) == before


def test_ac_f04_23_fuzz_200(tmp_path):
    _fuzz(tmp_path, 200)


@pytest.mark.slow
def test_ac_f04_23_fuzz_10000(tmp_path):
    _fuzz(tmp_path, 10_000)


def _fuzz(tmp_path, count: int) -> None:
    bases = [s.stage.to_json() for s in lantern_checkpoints(tmp_path)]
    for obj in fuzz_stage.mutations(bases, count, seed=1):
        try:
            StageState.from_json(obj)
        except StageInvalid:
            pass
        try:
            GameState.from_json(state_with(obj))
        except StateInvalid as e:
            assert e.reason == "stage"


def test_stage_from_json_shares_nothing_and_needs_finite_numbers():
    raw = with_sprites(sprite(at=[400.5, 680]))
    s = StageState.from_json(raw)
    raw["sprites"][0]["at"].append(1)
    assert s.sprites[0].at == (400.5, 680)
    assert not math.isnan(s.sprites[0].zoom)
    assert StageState.from_json({"background": None, "sprites": []}) is not EMPTY_STAGE
    assert StageState.from_json({"background": None, "sprites": []}) == EMPTY_STAGE


def test_pre_f04_state_loads_as_the_empty_stage():
    data = state_b_json()
    del data["stage"]
    assert GameState.from_json(data).stage == EMPTY_STAGE
    assert GameState.from_json(data).to_json()["stage"] == {"background": None, "sprites": []}


def test_lanterns_stage_sequence(tmp_path):
    """AC-F04-06's stage sequence (its no-warning half is step 6's stage check)."""
    cmds = run_h(lanterns(tmp_path / "g"), IMG_L)
    assert stages(cmds) == [stage(t) for t in (
        "bg river_night | stall@stall_spot, hana happy@center",
        "bg river_night | stall@stall_spot, hana pout@center",
        "bg river_night | stall@stall_spot, hana pout@center, daichi grin@right",
        "bg river_night | stall@stall_spot, hana surprised@center, daichi grin@right",
        "bg river_night | stall@stall_spot, hana happy@hana_close, daichi grin@right",
        "bg river_night | stall@stall_spot, hana happy@hana_close, daichi sigh@right",
        "bg river_night | daichi sigh@(1120), stall@stall_spot, hana happy@hana_close",
        "bg dusk | hana sad@left, girl_a=lantern_girl@(900) flip, "
        "girl_b=lantern_girl@(-200), railing@center L10",
        "bg dusk | hana sad@left, girl_a=lantern_girl@(900) flip, "
        "girl_b=lantern_girl@(1100), railing@center L10")]
    from engine.runtime.commands import Say
    assert [c.speaker_tag for c in cmds if type(c) is Say] == [
        None, "hana", "daichi", "hana", "hana", "daichi", None, "hana", None]
