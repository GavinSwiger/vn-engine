"""Stage stills, the helper side: ``parse_stage`` keeps the ``stage`` object in shape, and
``draw_stage_still`` draws the background, the sprites and the text box with the real code
(in-process here; ``test_helper.py`` drives the real child)."""

import io
import json

import pytest

from engine.core.paths import GamePaths
from engine.tools import helper as h
from tests.tools.f45_games import studio

pygame = pytest.importorskip("pygame")


def _stage(**over):
    stage = {"bg": "bg x", "images": {"bg x": "#204060", "hana happy": "images/hana/happy.png"},
             "sprites": [["hana", "hana happy", "left", 1.0, False]],
             "who": "Hana", "color": "#e8a0b4", "text": "Hi."}
    stage.update(over)
    return stage


def test_parse_stage_keeps_the_shape():
    parsed = h.parse_stage(_stage(sprites=[["d", "hana happy", [900], 1.5, True],
                                           ["e", "hana happy", [10, 20.5], 1, False]]))
    assert parsed.bg == "bg x" and parsed.who == "Hana" and parsed.text == "Hi."
    assert parsed.sprites == (("d", "hana happy", (900,), 1.5, True),
                              ("e", "hana happy", (10, 20.5), 1.0, False))
    assert h.parse_stage({}) == h.StageRequest()
    for bad in (None, [], {"extra": 1}, _stage(bg=""), _stage(color="red"),
                _stage(images={"a": 3}), _stage(images={f"n{i}": "#000000" for i in range(17)}),
                _stage(sprites=[["t", "i", "left", 1.0]]),
                _stage(sprites=[["t", "i", [1, 2, 3], 1.0, False]]),
                _stage(sprites=[["t", "i", "left", 0, False]]),
                _stage(sprites=[["t", "i", "left", 1.0, 0]]),
                _stage(sprites=[["t", "i", "left", 1.0, False]] * 13),
                _stage(text="x" * 601), _stage(who="x" * 257)):
        with pytest.raises(h.BadRequest):
            h.parse_stage(bad)
    line = json.dumps({"v": 1, "op": "still", "serial": 1, "kind": "stage", "width": 64,
                       "stage": _stage()}).encode("ascii")
    assert isinstance(h.parse_request(line)["stage"], h.StageRequest)
    with pytest.raises(h.BadRequest):
        h.parse_request(line.replace(b'"stage": {', b'"stagex": {'))


def test_a_stage_still_is_drawn_by_the_real_code(tmp_path):
    game = studio(tmp_path)
    helper = h.Helper(GamePaths.for_game(game))
    with_box = helper.still("stage", 320, None, h.parse_stage(_stage()))
    assert with_box.get_size() == (320, 180)
    assert tuple(with_box.get_at((4, 4)))[:3] == (0x20, 0x40, 0x60)       # the colour background
    bare = helper.still("stage", 320, None, h.parse_stage(_stage(text=None)))
    assert tuple(bare.get_at((160, 170)))[:3] == (0x20, 0x40, 0x60)       # no text box
    assert tuple(with_box.get_at((160, 170)))[:3] != (0x20, 0x40, 0x60)   # the text box
    empty = helper.still("stage", 64, None, h.StageRequest())
    assert empty.get_size() == (64, 36)
    # Through ``handle``: a png reply; a config the game can't load is a failed one.
    request = h.parse_request(json.dumps({"v": 1, "op": "still", "serial": 7, "kind": "stage",
                                          "width": 64, "stage": _stage()}).encode("ascii"))
    assert helper.handle(request, io.BytesIO())["event"] == "png"
    (game / "config.toml").write_text("[stage]\nart_height = -1\n", encoding="utf-8")
    reply = helper.handle(request, io.BytesIO())
    assert reply["event"] == "failed" and reply["reason"]
