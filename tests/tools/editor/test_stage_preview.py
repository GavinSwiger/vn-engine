"""Studio UX 2.5, Stage preview at any line: the stage at a line (``stagemoment``: the most
likely path through branches, calls, faces on dialogue, the text box's line), and the
preview over the side pane following the Events rows and the Script cursor in Studio L,
flipping in a frame, then becoming the game's still at rest (a fake helper)."""

import time

import pytest

from engine.tools.editor import helperhub, scenepreview, stagestills
from engine.tools.editor import stagemoment as sm
from engine.tools.editor.helperrunner import HelperReply

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_storyedit import (  # noqa: E402,F401
    click_box, lanterns, side_page, studio_l)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

SPEAKERS = {"hana": ("Hana", "#b03070"), "daichi": ("Daichi", "#3a6aa8"),
            "thought": (None, None)}
SCENE = '''label riverbank:
    scene bg river with fade
    show hana happy at left
    "Paper lanterns drifted
        past us."
    hana "Did you write one?"
    call shed
    if fortune == "bad":
        hana sad "Bad luck?"
        show daichi at right
    elif x:
        jump away
    else:
        daichi "Small."
    menu:
        "Q?"
        "Go":
            jump river
        "Stay" if coins > 0:
            scene bg night
            thought "You stay."
    show hana
    chapter river "Two" "Three"
'''.split("\n")


def _at(at, **kw):
    called = {"shed": ["label shed:", "    show daichi zoom 1.5", "    return"]}
    return sm.moment(SCENE, at, speakers=SPEAKERS, scene_lines=called.get, **kw)


def test_the_stage_at_a_line():
    narration = _at(3)                                   # a text over two lines
    assert narration.background == "bg river" and not narration.carried
    assert narration.sprites == (scenepreview.Sprite("hana happy", "left"),)
    assert narration.say == sm.Say(None, None, "Paper lanterns drifted past us.")
    said = _at(5)
    assert said.say == sm.Say("Hana", "#b03070", "Did you write one?") and said.note is None
    # A call carries the stage it sets back; a face on dialogue keeps the place.
    sad = _at(8)
    assert [(s.image, s.at, s.zoom) for s in sad.sprites] == [
        ("hana sad", "left", 1.0), ("daichi", None, 1.5)]
    assert _at(9).sprites[1] == scenepreview.Sprite("daichi", "right", None, 1.5)  # its line
    # Inside the else: that branch, not the first.
    other = _at(13)
    assert [s.image for s in other.sprites] == ["hana happy", "daichi"]
    # Below the if: its first way that falls through, said in one quiet line.
    below = _at(14)
    assert [s.image for s in below.sprites] == ["hana sad", "daichi"]
    assert below.note == sm.BRANCH_NOTE and below.say is None
    # After the menu: "Go" jumps away, so "Stay" ran; its scene line clears the doubt.
    after = _at(21)
    assert after.background == "bg night" and after.note is None
    assert after.sprites == (scenepreview.Sprite("hana"),)
    assert _at(20).say == sm.Say(None, None, "You stay.")   # no name plate
    assert _at(22).say is None                          # "chapter" isn't a character


def test_carried_stage_and_show_rules():
    lines = ["label later:", "    show hana pout", '    hana "Hm."', "    show hana at right",
             "    show hana as h2 at left", "    hide hana"]
    lead = ["    scene bg room", "    show hana happy at left zoom 2"]
    stage = sm.moment(lines, 2, speakers=SPEAKERS, lead=lead, came_from="start")
    assert stage.background == "bg room" and stage.came_from == "start"
    assert stage.sprites == (scenepreview.Sprite("hana pout", "left", None, 2.0),)
    moved = sm.moment(lines, 5, speakers=SPEAKERS, lead=lead, came_from="start")
    assert moved.sprites == (scenepreview.Sprite("hana", "left"),)   # tag h2; hana hidden
    assert sm.moment(lines, 3, speakers=SPEAKERS).carried               # no way in known
    assert sm.Say("A", None, "{b}Hi{/b} \\\"you\\\"").plain == 'Hi "you"'


def _open_river(ed):
    click_box(ed, "river")
    ed.press(ed.map_canvas, "<Control-e>")
    assert side_page(ed) == "Events"
    return ed.win.scene_preview


def test_up_and_down_flip_the_stage_in_a_frame(studio, lanterns):
    ed = studio_l(studio, lanterns)
    preview = _open_river(ed)
    events, tree = ed.events_view, ed.events_view.tree
    assert preview.heading.cget("text") == scenepreview.HEADING        # the label line
    for key in ("<Down>", "<Down>", "<Up>"):
        ed.press(tree, key)
    assert events.selected() == 1 and preview.line == 13
    assert preview.heading.cget("text") == scenepreview.AT_LINE.format(line=13)
    assert preview.stage.say == sm.Say("Hana", None, "You came!")
    texts = [preview.canvas.itemcget(i, "text") for i in preview.canvas.find_all()
             if preview.canvas.type(i) == "text"]
    assert texts == ["Hana", "You came!"]                              # the text box
    assert preview.badge.winfo_manager() == "place"                    # "sketch"
    ed.press(tree, "<Up>")
    assert preview.line == 12 and preview.stage.say is None
    # A flip (the row chosen, the cursor moved, the sketch drawn) fits a 60 Hz frame.
    flips = []
    for index in (1, 2, 1, 0, 1, 2, 1, 0, 1, 2):
        started = time.perf_counter()
        events.select(index)                        # what Up/Down do, without Tk's idle
        flips.append(time.perf_counter() - started)
        assert preview.line == 12 + index
    assert sorted(flips)[len(flips) // 2] < 0.016, flips
    # The Script page's cursor: the window's refresh follows it.
    ed.press(ed.side_text if side_page(ed) == "Script" else tree, "<Control-e>")
    ed.side_text.mark_set("insert", "13.6")
    ed.root.update()
    assert preview.line == 13 and preview.stage.say.text == "You came!"
    ed.side_text.mark_set("insert", "11.0")                             # the label line
    ed.root.update()
    assert preview.line is None and preview.heading.cget("text") == scenepreview.HEADING


class StillRunner:
    """A fake helper runner that answers ``stage`` stills with a 4 × 2 PNG."""

    PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAQAAAACCAIAAADwyuo0AAAAEklEQVQImWPkEpFjgAEmBiQAAAXa"
           "AEDEfeWCAAAAAElFTkSuQmCC")

    def __init__(self, game) -> None:
        self.asked: list = []
        self.serial = 0
        self.pending: list[HelperReply] = []

    def still(self, kind, width, config, stage=None):
        self.serial += 1
        self.asked.append((kind, width, stage))
        self.pending.append(HelperReply("still", self.serial, True, data=self.PNG, width=4,
                                        height=2, kind=kind))
        return self.serial

    def thumb(self, ref, size, stamp=None):
        return None

    def poll(self):
        out, self.pending = self.pending, []
        return out

    def stop(self, timeout_s=None):
        pass


@pytest.mark.parametrize("reduce", [False, True])
def test_at_rest_the_sketch_becomes_the_games_still(studio, lanterns, monkeypatch, reduce):
    monkeypatch.setattr(helperhub, "make_runner", StillRunner)
    monkeypatch.setattr(scenepreview, "REST_MS", 30)
    ed = studio_l(studio, lanterns)
    if reduce:
        ed.win.reduce_motion.set(True)
    preview = _open_river(ed)
    ed.press(ed.events_view.tree, "<Down>")
    end = time.monotonic() + 5
    while preview.still is None and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.005)
    runner = ed.win.helper_hub.runner
    kind, width, stage = runner.asked[-1]
    assert kind == "stage" and width == preview.w
    assert stage["text"] == "You came!" and stage["who"] == "Hana"
    assert stage["sprites"] == [["hana", "hana happy", "left", 1.0, False]]
    assert preview.still is not None and preview.badge.winfo_manager() == ""
    veils = [i for i in preview.canvas.find_all() if preview.canvas.type(i) == "rectangle"]
    assert (veils == []) is reduce          # a settle under motion; a cut under Reduce
    # Back up and down again: both rows' stills come from the cache.
    asked = len(runner.asked)
    ed.press(ed.events_view.tree, "<Up>")
    ed.press(ed.events_view.tree, "<Down>")
    end = time.monotonic() + 5
    while preview.still is None and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.005)
    assert preview.still is not None and len(runner.asked) == asked       # both cached
    assert isinstance(ed.win.stage_stills, stagestills.StageStills)
