"""Studio's side of ``reach`` (``script/reach.py`` via the check child): the rows decode
strictly, and the Events page shows them under the scene, a warning first."""

import json

import pytest

from engine.tools.editor.checker import ReachRow, decode_check_line

tk = pytest.importorskip("tkinter")


def _line(items):
    return b"VN-EDITOR-REPORT " + json.dumps({"v": 1, "event": "reach", "items": items}).encode()


def test_reach_rows_decode_strictly():
    good = [["vault", "way", "From hallway: needs has_key", "script/main.vns", 25],
            ["secret", "blocked", "No playthrough can reach this scene.", None, None]]
    assert decode_check_line(_line(good)) == ("reach", (
        ReachRow("vault", "way", "From hallway: needs has_key", "script/main.vns", 25),
        ReachRow("secret", "blocked", "No playthrough can reach this scene.")))
    for bad in (["vault", "maybe", "x", None, None], ["vault", "way", "x", None],
                ["vault", "way", "x", "script/main.vns", 0]):
        assert decode_check_line(_line([bad])) is None


@pytest.mark.tk
def test_the_box_shows_the_warning_first_and_opens_places():
    from engine.tools.editor.eventsview import REACH_HEADING, REACH_SET_HEADING, ReachBox
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        box = ReachBox(root, fonts={})
        box.frame.pack()
        opened = []
        box.on_place = lambda file, line: opened.append((file, line))
        box.show([ReachRow("secret", "way", "From yard: needs has_key (never: x)", "a.vns", 3),
                  ReachRow("secret", "set", "has_key = True, in shed", "a.vns", 9),
                  ReachRow("secret", "blocked", "No playthrough can reach this scene.",
                           "a.vns", 1)])
        assert box.texts() == ["⚠ No playthrough can reach this scene.", REACH_HEADING,
                               "• From yard: needs has_key (never: x)", REACH_SET_HEADING,
                               "• has_key = True, in shed"]
        box.labels[2].event_generate("<Button-1>")
        assert opened == [("a.vns", 3)]
        box.show([])
        assert box.texts() == []
    finally:
        root.destroy()
