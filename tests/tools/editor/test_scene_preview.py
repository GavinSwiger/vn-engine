"""The Story map side pane's opening shot (``scenepreview``): the stage before a scene's
first text, a carried-on background found back along the arrows, the positions, and the
drawing in a real window."""

from types import SimpleNamespace as Link

import pytest

from engine.tools.editor import scenepreview as sp
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import select, studio  # noqa: E402,F401


def test_the_opening_stage_stops_at_the_first_text():
    lines = ["label yard:", "    scene bg yard with fade", "    show hana happy at left",
             "    show daichi at 900 zoom 1.5", '    hana "Hi."', "    scene bg night"]
    stage = sp.opening_stage(lines)
    assert stage.background == "bg yard" and not stage.carried and stage.came_from is None
    assert stage.sprites == (sp.Sprite("hana happy", "left"),
                             sp.Sprite("daichi", None, 900.0, 1.5))
    assert sp.opening_stage(["label a:", '    "Narration first."', "    scene bg x"]).carried
    assert sp.opening_stage(["label a:", "    menu:", "    scene bg x"]).carried


def test_a_carried_background_is_found_back_along_the_arrows():
    scenes = {
        "start": (["label start:", "    scene bg river", "    show hana", '    "Hi."',
                   "    jump middle"], 1),
        "middle": (["label middle:", "    show hana sad at right", "    jump end"], 10),
        "end": (["label end:", '    "Bye."'], 20),
    }
    links = [Link(src="start", dst="middle", kind="jump", line=5),
             Link(src="middle", dst="end", kind="jump", line=12)]
    lead, came_from = sp.lead_in("end", links, lambda name: scenes.get(name))
    assert came_from == "start"
    stage = sp.opening_stage(scenes["end"][0], lead, came_from)
    assert stage.background == "bg river" and stage.came_from == "start"
    assert [s.image for s in stage.sprites] == ["hana sad"]          # the same tag: replaced
    # No way in, or a loop with no background: nothing is made up.
    assert sp.lead_in("start", links, lambda name: scenes.get(name)) == ([], None)
    loop = [Link(src="a", dst="b", kind="jump", line=2), Link(src="b", dst="a", kind="jump", line=2)]
    found = {"a": (["label a:", "    jump b"], 1), "b": (["label b:", "    jump a"], 1)}
    assert sp.lead_in("a", loop, found.get) == ([], None)


def test_stage_settings():
    positions, art = sp.stage_settings('[stage]\nart_height = 1080\n[stage.positions]\n'
                                       'far = 100\nup = [640, 300]\n')
    assert art == 1080 and positions["far"] == (100.0, 720.0)
    assert positions["up"] == (640.0, 300.0) and positions["left"] == (320.0, 720.0)
    assert sp.stage_settings("not toml [")[1] == 720


def test_the_preview_draws_in_studio(studio, tmp_path):
    game = make_game(tmp_path)
    ch2 = game / "script" / "ch2.vns"
    ch2.write_text(ch2.read_text(encoding="utf-8") + '\nlabel preview_here:\n'
                   '    scene bg room\n    show hana happy at left\n    show ghost\n'
                   '    "Hello."\n    return\n', encoding="utf-8")
    ed = studio(game, mapped=True)
    win = ed.win
    select(ed, "script/ch2.vns")                        # a box's click opens its file
    win.story.show("script/ch2.vns", "preview_here")
    ed.root.update()
    preview = win.scene_preview
    assert preview.frame.winfo_manager() == "grid"           # placed over the pages
    assert preview.stage.background == "bg room"
    assert len(preview.canvas.find_all()) == 2                   # the room and Hana
    caption = preview.caption.cget("text")
    assert "bg room" in caption and "hana happy (left)" in caption
    assert sp.MISSING.format(name="ghost") in caption           # no such picture: said
    win.story.show("script/ch2.vns", "no_such_scene")
    ed.root.update()
    assert preview.frame.winfo_manager() == ""
