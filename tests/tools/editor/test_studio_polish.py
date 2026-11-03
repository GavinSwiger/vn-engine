"""Studio polish batch: the Database's message form wraps to a narrow form column, the
narrow-window category drop-down lists every category (Minigame data included), and the
room canvas's hotspot labels don't cover one another.

Tk, in a real Studio window on the sample game (``files.new_game``)."""

from pathlib import Path

import pytest

from engine.tools.editor import database, files, minigameview

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import helper, open_database  # noqa: E402,F401
from tests.tools.editor.test_studio_minigames import minigame_game, open_minigames  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


def sample(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    return game


def sized(ed, width: int, height: int = 700) -> None:
    ed.root.geometry(f"{width}x{height}+-3000+-3000")
    for _ in range(3):
        ed.root.update()


def test_message_form_wraps_to_a_narrow_column(studio, tmp_path):
    ed = studio(sample(tmp_path), mapped=True)
    db = open_database(ed, "gallery")
    sized(ed, 920)
    label = next(w for w in db.body.winfo_children() if isinstance(w, tk.ttk.Label))
    assert label.cget("text") == database.ABOUT["gallery"]
    width = label.winfo_width()
    assert width < db._px(360)                      # the column is narrower than 360 px
    assert 0 < int(str(label.cget("wraplength"))) <= width      # so the text wraps to it
    sized(ed, 1600)
    assert int(str(label.cget("wraplength"))) == db._px(360)    # wide: the usual measure


def test_narrow_window_category_drop_down_lists_every_category(studio, tmp_path):
    ed = studio(sample(tmp_path), mapped=True)
    db = open_database(ed, "character")
    sized(ed, 800)
    assert db.compact and db.cat_choice.widget.winfo_ismapped()
    titles = list(db.cat_choice.box.cget("values"))
    for title in ("Gallery", "Music room", minigameview.CATEGORY_TITLE):
        assert title in titles
    assert titles == [db.cat_tree.item(key, "text") for key in db.cat_tree.get_children()]

    # Minigame data from the drop-down: its own list, with the drop-down over it.
    db.cat_choice.pick(minigameview.CATEGORY)
    ed.root.update()
    pane = db.minigames
    assert pane.showing and pane.cat_choice.widget.winfo_ismapped()
    assert pane.cat_choice.var.get() == minigameview.CATEGORY_TITLE
    pane.cat_choice.pick("gallery")                 # and back to a Database category
    ed.root.update()
    assert not pane.showing and db.category == "gallery"
    assert db.cat_choice.var.get() == "Gallery" and db.cat_choice.widget.winfo_ismapped()

    sized(ed, 1300)                                 # wide again: the side bar, no drop-downs
    assert not db.compact and not db.cat_choice.widget.winfo_ismapped()
    assert not pane.cat_choice.widget.winfo_ismapped()


def _apart(a, b) -> bool:
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_place_labels_nudges_overlapping_labels_and_stays_on_the_canvas():
    big, small = (100, 100, 300, 160), (130, 110, 170, 150)     # one box inside another
    boxes = minigameview.place_labels([(big, (80, 16)), (small, (50, 16)),
                                       ((600, 330, 640, 360), (90, 16))], 640, 360)
    assert boxes[0][:2] == (102, 102)                   # the first keeps its corner
    assert _apart(boxes[0], boxes[1])                   # the second is nudged off it
    assert boxes[1][0] == 132                           # (still lined up with its box)
    for x0, y0, x1, y1 in boxes:                        # all inside the canvas
        assert 0 <= x0 and x1 <= 640 and 0 <= y0 and y1 <= 360


def test_room_canvas_labels_do_not_overlap(studio, tmp_path, helper):
    ed = studio(minigame_game(tmp_path), mapped=True)
    pane = open_minigames(ed)
    pane.pick("attic")
    ed.root.update()
    room = pane.editor
    boxes = room.label_boxes
    assert set(boxes) == {"window", "hook", "drawer", "magnet", "door", "out"}
    names = sorted(boxes)
    for i, a in enumerate(names):                       # "Desk drawer" and "Magnet" too
        for b in names[i + 1:]:
            assert _apart(boxes[a], boxes[b]), (a, b)
    for x0, y0, x1, y1 in boxes.values():
        assert 0 <= x0 and x1 <= room.width and 0 <= y0 and y1 <= room.height
