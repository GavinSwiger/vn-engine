"""F47 W8: Studio's minigame setup panels and the Minigame form (``01-design.md`` §4.6, §4.5;
``04-technical.md`` §16 W8; AC-F47-45, and AC-F47-46's form in Events).

On copies of the F47 sample game with the data of ``docs/minigames.md`` added to its
``database.vns`` (and, for the form, the example game's ``lantern_memory`` plugin). The
logic under the panels (models, plans, checks, the form's fields) is tested without Tk in
``test_minigamedata.py``."""

from pathlib import Path

import pytest

from engine.script.statement_docs import all_docs
from engine.tools.editor import declplan, files
from engine.tools.editor import minigamedata as mg

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import minigameview as mv  # noqa: E402
from tests.tools.editor.test_studio_database import helper  # noqa: E402,F401
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

REPO = Path(__file__).resolve().parents[3]
DB_REF = declplan.DATABASE_REF
MAIN_REF = "script/main.vns"

DATA = '''
points sayori natsuki yuri
lock item rusty_key "Rusty Key"
lock item string "String"
lock item magnet "Magnet"
lock item magnet_string "Magnet on a String"
lock item door_key "Door Key"
lock item brass_key "Brass Key" in "Evidence"

define day1_words = {
    "sunshine": {"sayori": 3, "natsuki": 1},
    "whisper": "yuri",
    "pencil": {},
    }

define daichi_says = {
    "after_dark": "Nobody went near the shrine after dark.",
    "gate": "The gate was locked all night. I checked it myself.",
    }
define daichi_answer = {"gate": "brass_key"}

define late_chat = [
    "you awake?",
    {"ask": "awake", "yes": ["Yeah, what's up?", "nothing really"], "sleep": "Go to sleep.",
        "ignore": True},
    {"time": "11:51 PM"},
    ]

define attic = {
    "background": "bg river_dusk",
    "hotspots": {
        "window": {"rect": [880, 90, 220, 260], "label": "Window", "look": "Snow, as far as you can see."},
        "hook":   {"rect": [300, 260, 64, 96], "label": "Coat hook", "take": "rusty_key"},
        "drawer": {"rect": [520, 420, 200, 90], "label": "Desk drawer", "use": "rusty_key", "look": "Locked.", "nope": "It doesn't fit."},
        "magnet": {"rect": [590, 440, 60, 50], "label": "Magnet", "after": "drawer", "take": "magnet"},
        "door":   {"rect": [40, 120, 180, 420], "label": "Door", "use": "door_key", "look": "Locked tight."},
        "out":    {"rect": [40, 120, 180, 420], "label": "Door", "after": "door", "exit": True},
    },
    "combine": {"magnet_string": ["magnet", "string"]},
    }
default attic_state = None
default poem_for = None
'''

CALLS = '''
label minigames_demo:
    minigame poem_game words=day1_words into poem_for
    minigame puzzle_room skippable room=attic state=attic_state into attic_state  # loop
    return
'''


def minigame_game(tmp_path: Path, *, plugin: bool = False) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    db = game / "script" / "database.vns"
    db.write_text(db.read_text(encoding="utf-8") + DATA, encoding="utf-8")
    main = game / "script" / "main.vns"
    main.write_text(main.read_text(encoding="utf-8") + CALLS, encoding="utf-8")
    if plugin:
        (game / "minigames").mkdir(exist_ok=True)
        (game / "minigames" / "lantern_memory.py").write_text(
            (REPO / "game" / "minigames" / "lantern_memory.py").read_text("utf-8"), "utf-8")
    return game


def text_of(ed, ref: str) -> str:
    return ed.win.record_for(ref).widget.get("1.0", "end-1c")


def room_now(ed) -> mg.Room:
    found = [ds for ds in mg.scan({DB_REF: text_of(ed, DB_REF)}) if ds.name == "attic"]
    assert len(found) == 1
    return found[0].model


def open_minigames(ed) -> mv.MinigamePane:
    ed.root.update()
    ed.win.show_tab(ed.win.tab_index("database"))
    pane = ed.win.database.minigames
    pane.select()
    ed.root.update()
    return pane


def drag(canvas, start: tuple[float, float], end: tuple[float, float], *,
         release: bool = True) -> None:
    """A real mouse drag on ``canvas`` (canvas px), in three motion steps."""
    (x0, y0), (x1, y1) = start, end
    canvas.event_generate("<ButtonPress-1>", x=round(x0), y=round(y0))
    for k in (1, 2, 3):
        canvas.event_generate("<B1-Motion>", x=round(x0 + (x1 - x0) * k / 3),
                              y=round(y0 + (y1 - y0) * k / 3))
    if release:
        canvas.event_generate("<ButtonRelease-1>", x=round(x1), y=round(y1))
    canvas.update()


def commit(field, text: str) -> None:
    """Type ``text`` into a panel field and leave it (Enter, or focus-out for a message)."""
    if isinstance(field, mv._Message):
        field.text.delete("1.0", "end")
        field.text.insert("1.0", text)
    else:
        field.var.set(text)
    field.commit()


def test_ac_f47_45_puzzle_room_canvas_round_trips_hotspots_drawn_on_the_background(
        studio, tmp_path, helper):
    game = minigame_game(tmp_path)
    ed = studio(game, mapped=True)
    pane = open_minigames(ed)
    db_cats = ed.win.database.cat_tree
    assert db_cats.item(mv.CATEGORY, "text") == "Minigame data"
    assert db_cats.set(mv.CATEGORY, "count") == "4"
    assert [pane.tree.item(g, "text") for g in pane.tree.get_children()] == [
        "Poem word lists", "Evidence", "Phone chats", "Puzzle rooms"]
    pane.pick("attic")
    ed.root.update()
    room = pane.editor
    assert isinstance(room, mv.RoomEditor)
    assert room.photo is not None                   # the background, scaled onto the canvas
    assert room.photo.width() <= room.width
    s, canvas = room.scale, room.canvas
    before = text_of(ed, DB_REF)

    # Draw a new hotspot on an empty part of the picture: mid-drag nothing is written yet.
    drag(canvas, (1000 * s, 520 * s), (1150 * s, 660 * s), release=False)
    assert room.live is not None and canvas.find_withtag("live")
    assert text_of(ed, DB_REF) == before
    canvas.event_generate("<ButtonRelease-1>", x=round(1150 * s), y=round(660 * s))
    ed.root.update()
    assert room.chosen == "hotspot_7"
    spot = next(h for h in room_now(ed).hotspots if h.name == "hotspot_7")
    assert (spot.rect, spot.label) == ((1000, 520, 150, 140), "Hotspot 7")

    # Its side form: name tag (the script name follows while it is the made-up one), what a
    # click does, and the item it gives.
    commit(room.fields["label"], "Loose board")
    assert room.chosen == "loose_board"
    commit(room.fields["does"], "Gives an item")
    commit(room.fields["take"], "string")
    spot = next(h for h in room_now(ed).hotspots if h.name == "loose_board")
    assert (spot.label, spot.take, spot.look, spot.exit) == ("Loose board", "string", None, None)

    # Drag the window to move it, then its bottom-right corner to resize it.
    drag(canvas, (990 * s, 200 * s), (1090 * s, 240 * s))
    assert room.chosen == "window"
    assert room_now(ed).hotspots[0].rect == (980, 130, 220, 260)
    drag(canvas, (1200 * s, 390 * s), (1240 * s, 430 * s))
    assert room_now(ed).hotspots[0].rect == (980, 130, 260, 300)
    # A drag past the screen's edge is kept inside it; the keyboard moves it too.
    drag(canvas, (1100 * s, 250 * s), (1300 * s, 250 * s))
    assert room_now(ed).hotspots[0].rect == (1020, 130, 260, 300)
    ed.press(canvas, "<Key-Left>")
    assert room_now(ed).hotspots[0].rect == (1012, 130, 260, 300)

    # The define reads back as the editor's model; untouched hotspots keep every field.
    model = room_now(ed)
    assert model == room.room
    assert [h.name for h in model.hotspots] == [
        "window", "hook", "drawer", "magnet", "door", "out", "loose_board"]
    assert model.hotspots[2] == mg.Hotspot("drawer", (520, 420, 200, 90), "Desk drawer",
                                           look="Locked.", use=("rusty_key",),
                                           nope="It doesn't fit.")
    assert model.combine == (("magnet_string", "magnet", "string"),)

    # Each change is one undo step.
    text = text_of(ed, DB_REF)
    widget = ed.win.record_for(DB_REF).widget
    widget.edit_undo()
    assert room_now(ed).hotspots[0].rect == (1020, 130, 260, 300)
    widget.edit_redo()
    assert text_of(ed, DB_REF) == text

    # A change the game would refuse stays on screen, unsaved, with the reason.
    room.choose("out")
    commit(room.fields["does"], "Shows its text")
    assert room.pending and room.status.cget("text") == mv.NOT_SAVED.format(
        problem=mg.NO_EXIT)
    assert text_of(ed, DB_REF) == text
    commit(room.fields["does"], "Leaves the room")
    assert not room.pending and room.status.cget("text") == ""
    assert room_now(ed) == model                    # back as it was: nothing written


def test_minigame_editors_write_their_define(studio, tmp_path, helper, monkeypatch):
    """The poem table, the evidence statements and the chat steps write their ``define``
    (one undo step each); + New makes a starter data set in ``database.vns``."""
    game = minigame_game(tmp_path)
    ed = studio(game, mapped=True)
    pane = open_minigames(ed)

    pane.pick("day1_words")
    poem = pane.editor
    assert isinstance(poem, mv.PoemEditor)
    assert poem.meters() == ("sayori", "natsuki", "yuri")     # the story's order
    var = poem.cells[(2, "yuri")]
    var.set("2")
    poem.set_points(2, "yuri")
    assert 'define day1_words = {\n    "sunshine": {"sayori": 3, "natsuki": 1},\n    ' \
        '"whisper": "yuri",\n    "pencil": {"yuri": 2},\n    }' in text_of(ed, DB_REF)

    pane.pick("daichi_says")
    evidence = pane.editor
    assert isinstance(evidence, mv.EvidenceEditor)
    evidence.tree.selection_set("0")
    ed.root.update()
    assert evidence.items.ticked() == ()            # its answer, found by its shape
    evidence.items.tick("string")
    assert 'define daichi_answer = {"after_dark": "string", "gate": "brass_key"}' in \
        text_of(ed, DB_REF)
    evidence.tree.selection_set("1")
    ed.root.update()
    assert evidence.items.ticked() == ("brass_key",)

    pane.pick("late_chat")
    chat = pane.editor
    assert isinstance(chat, mv.ChatEditor)
    chat.select("s1")
    chat.add_reply()
    commit(chat.fields["text"], "Maybe later")
    chat.select("s2")
    chat.add_step(mg.FROM_ME)
    commit(chat.fields["text"], "on my way")
    chat_now = next(ds for ds in mg.scan({DB_REF: text_of(ed, DB_REF)})
                    if ds.name == "late_chat").model
    assert chat_now[1].replies[-1] == mg.Reply("new_reply", "Maybe later")
    assert chat_now[1].ignore is True
    assert chat_now[3] == mg.Step(mg.FROM_ME, "on my way")

    monkeypatch.setattr(mv, "ask_text", lambda *a, **k: ("Night chat", True))
    assert pane.new(mg.CHAT) == "night_chat"
    assert 'define night_chat = [\n    "hi!",\n    {"me": "hey"},\n    ]' in text_of(ed, DB_REF)
    assert isinstance(pane.editor, mv.ChatEditor) and pane.chosen == "night_chat"

    # Another category puts the Database's own list and form back.
    database = ed.win.database
    database.select_category("character")
    ed.root.update()
    assert not pane.shown
    assert str(database.list_frame) in [str(p) for p in database.paned.panes()]
    assert str(pane.list_frame) not in [str(p) for p in database.paned.panes()]


def doc_of(key: str):
    return next(d for d in all_docs() if d.key == key and d.insert)


def test_ac_f47_46_minigame_form_in_events(studio, tmp_path, helper, monkeypatch):
    """AC-F47-46 (its form): the Minigame form lists installed games; its fields come from
    the game's declared args; data-set pickers list that game's data; "Result goes to"
    picks a variable. A ``minigame`` line is a Minigame row that the form edits."""
    game = minigame_game(tmp_path, plugin=True)
    ed = studio(game, mapped=True)
    win = ed.win
    form = mv.MinigameDialog(win, None)
    assert form.games == [*mg.BUNDLED, "lantern_memory"]
    assert list(form.game_box.cget("values")) == [
        "Poem", "Present evidence", "Phone chat", "Puzzle room", "lantern_memory"]
    form.set_game("poem_game")
    assert list(form.widgets) == ["words", "rounds", "page_words", "to_points", "result", "into"]
    assert list(form.widgets["words"].cget("values")) == ["day1_words"]
    assert "poem_for" in form.widgets["into"].cget("values")
    assert form.vars["result"].get() == "winner"               # a default, shown unquoted
    form.set("words", "")
    assert form.line.cget("text") == mg.NEEDED.format(label="Word list")
    form.set("words", "day1_words")
    form.set("rounds", "4")
    form.set("into", "poem_for")
    form.skip_var.set(True)
    form._changed()
    form._pick(0)
    assert form.result == {
        "line": "minigame poem_game skippable words=day1_words rounds=4 into poem_for"}

    form = mv.MinigameDialog(win, None)
    form.set_game("phone_chat")
    form.set("chat", "late_chat")
    form.set("contact", 'Sayori "Yori"')
    form._pick(0)
    assert form.result == {"line": 'minigame phone_chat chat=late_chat contact="Sayori \\"Yori\\""'}
    form = mv.MinigameDialog(win, None)
    form.set_game("lantern_memory")                            # a game plugin's own args
    assert list(form.widgets) == ["pairs", "hints", "into"]
    form.set("pairs", "6")
    form.set("hints", "True")
    form._pick(0)
    assert form.result == {"line": "minigame lantern_memory pairs=6 hints=True"}

    # Events: the line is a Minigame row; Edit opens this form with the line's values.
    story = win.story
    story.show(MAIN_REF, "minigames_demo")
    ed.root.update()
    words = [(r.word, r.form) for r in story.rows if r.kind == "stmt"]
    assert words[:2] == [("Minigame", "minigame"), ("Minigame", "minigame")]
    assert story.rows[1].summary == "Puzzle room · attic → attic_state"
    seen = {}

    def fake_edit(win_, values):
        seen["values"] = values
        made = mv.MinigameDialog(win_, values)
        seen["room"] = made.vars["room"].get(), made.vars["state"].get(), \
            made.vars["into"].get(), made.skip_var.get()
        made.set("state", "")
        made._pick(0)
        return made.result

    monkeypatch.setattr(mv, "edit_minigame", fake_edit)
    story.edit(1)
    assert seen["room"] == ("attic", "attic_state", "attic_state", True)
    lines = text_of(ed, MAIN_REF).split("\n")
    assert "    minigame puzzle_room skippable room=attic into attic_state  # loop" in lines

    # Insert ▸ Minigame goes through the same form.
    monkeypatch.setattr(mv, "edit_minigame", lambda win_, values: {
        "line": "minigame phone_chat chat=late_chat contact=\"Sayori\""})
    story.insert(0, doc_of("minigame"))
    assert '    minigame phone_chat chat=late_chat contact="Sayori"' in \
        text_of(ed, MAIN_REF).split("\n")
