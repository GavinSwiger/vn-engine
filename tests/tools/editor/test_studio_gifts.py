"""F54 step W1: the Gift table editor (Database ▸ Minigame data) and Gift giving in the
Minigame form, in a real Studio window on a new game with SPEC §3.1's data: AC-F54-09 (the
editor writes the ``define``) and AC-F54-10 (the form's fields and data choices)."""

from pathlib import Path

import pytest

from engine.tools.editor import declplan, files
from engine.tools.editor import minigamedata as mg

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import minigameview as mv  # noqa: E402
from tests.tools.editor.test_studio_database import helper  # noqa: E402,F401
from tests.tools.editor.test_studio_minigames import commit, open_minigames, text_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

DB_REF = declplan.DATABASE_REF
DATA = '''
points hana daichi 0 to 10
lock item red_lantern "Red Lantern" in "Gifts"
lock item umbrella "Umbrella" in "Gifts"
default reaction = None
define day1_words = {"sunshine": {"hana": 3}, "pencil": {}}

define birthday_gifts = {
    "hana": {
        "*": ["neutral", 0, "Oh. Thank you."],
        "red_lantern": ["loved", 3, "You kept it all this time?"],
        "umbrella": ["liked", 1],
        },
    "daichi": {
        "umbrella": ["disliked", -1, "I have three of these."],
        },
    }
'''
CALLS = '''
label birthday:
    minigame gift_giving skippable gifts=birthday_gifts to="hana" categories=["Gifts"] into reaction
    return
'''


def gift_game(tmp_path: Path, *, data: str = DATA) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    db = game / "script" / "database.vns"
    db.write_text(db.read_text(encoding="utf-8") + data, encoding="utf-8")
    main = game / "script" / "main.vns"
    main.write_text(main.read_text(encoding="utf-8") + CALLS, encoding="utf-8")
    return game


def table_now(ed) -> dict:
    found = [ds for ds in mg.scan({DB_REF: text_of(ed, DB_REF)}) if ds.name == "birthday_gifts"]
    assert len(found) == 1
    return mg.value_of(mg.GIFTS, found[0].model)


def test_ac_f54_09_gift_table_editor(studio, tmp_path, helper, monkeypatch):
    ed = studio(gift_game(tmp_path), mapped=True)
    pane = open_minigames(ed)
    assert "Gift tables" in [pane.tree.item(g, "text") for g in pane.tree.get_children()]
    pane.pick("birthday_gifts")
    gifts = pane.editor
    assert isinstance(gifts, mv.GiftsEditor)
    assert list(gifts.character.box.cget("values")) == ["hana", "daichi"]
    assert gifts.character.var.get() == "hana"
    assert (gifts.any_fields["reaction"].var.get(), gifts.any_fields["points"].get(),
            gifts.any_fields["line"].var.get()) == ("Neutral", "0", "Oh. Thank you.")
    assert [(r["item"].var.get(), r["reaction"].var.get(), r["points"].get(),
             r["line"].var.get()) for r in gifts.rows] == [
        ("Red Lantern", "Loved", "3", "You kept it all this time?"),
        ("Umbrella", "Liked", "1", "")]
    # Each column writes the define.
    commit(gifts.rows[1]["reaction"], "Loved")
    gifts.rows[1]["points"].set("2")
    gifts.rows[1]["spin"].focus_force()
    ed.root.update()
    gifts.rows[1]["spin"].event_generate("<Return>")
    commit(gifts.rows[1]["line"], "For rainy days?")
    assert table_now(ed)["hana"]["umbrella"] == ["loved", 2, "For rainy days?"]
    assert '        "umbrella": ["loved", 2, "For rainy days?"],' in text_of(ed, DB_REF)
    # "Any other gift": written only when it isn't Neutral, 0, empty.
    commit(gifts.any_fields["line"], "")
    assert "*" not in table_now(ed)["hana"]
    commit(gifts.any_fields["reaction"], "Disliked")
    assert list(table_now(ed)["hana"].items())[0] == ("*", ["disliked", 0])
    # A gift the game would refuse (the same item twice) stays on screen, unsaved.
    text = text_of(ed, DB_REF)
    commit(gifts.rows[1]["item"], "Red Lantern")
    assert gifts.pending and gifts.status.cget("text").startswith("Not saved yet: ")
    assert text_of(ed, DB_REF) == text
    commit(gifts.rows[1]["item"], "Umbrella")
    assert not gifts.pending and gifts.status.cget("text") == ""
    # The other character: rows add and remove.
    commit(gifts.character, "daichi")
    assert [r["item"].var.get() for r in gifts.rows] == ["Umbrella"]
    gifts.add_gift()
    assert table_now(ed)["daichi"] == {"umbrella": ["disliked", -1, "I have three of these."],
                                       "red_lantern": ["liked", 1]}
    gifts.remove_gift(0)
    assert table_now(ed)["daichi"] == {"red_lantern": ["liked", 1]}
    # Characters add (a typed name) and remove.
    monkeypatch.setattr(mv, "ask_text", lambda *a, **k: ("yuki", True))
    gifts.add_character()
    assert list(table_now(ed)) == ["hana", "daichi", "yuki"] and table_now(ed)["yuki"] == {}
    assert gifts.character.var.get() == "yuki"
    gifts.remove_character()
    assert list(table_now(ed)) == ["hana", "daichi"]
    # Each change is one undo step.
    widget = ed.win.record_for(DB_REF).widget
    widget.edit_undo()
    assert list(table_now(ed)) == ["hana", "daichi", "yuki"]
    widget.edit_redo()
    assert list(table_now(ed)) == ["hana", "daichi"]


def test_ac_f54_09_new_table_and_no_items(studio, tmp_path, helper, monkeypatch):
    plain = "\npoints hana 0 to 10\n"
    ed = studio(gift_game(tmp_path, data=plain), mapped=True)
    pane = open_minigames(ed)
    monkeypatch.setattr(mv, "ask_text", lambda *a, **k: ("Birthday gifts", True))
    assert pane.new(mg.GIFTS) == "birthday_gifts"
    assert 'define birthday_gifts = {\n    "hana": {},\n    }' in text_of(ed, DB_REF)
    gifts = pane.editor
    assert isinstance(gifts, mv.GiftsEditor)
    assert gifts.no_items.winfo_manager() == "pack"                # "No items yet. …"
    assert gifts.no_items.cget("text") == mv.NO_GIFT_ITEMS
    assert "disabled" in gifts.add_button.state()


def test_ac_f54_10_gift_giving_in_the_minigame_form(studio, tmp_path, helper):
    ed = studio(gift_game(tmp_path), mapped=True)
    dialog = mv.MinigameDialog(ed.win, None)
    assert "Gift giving" in list(dialog.game_box.cget("values"))
    dialog.set_game("gift_giving")
    assert list(dialog.widgets) == ["gifts", "to", "speaker", "categories", "use_up", "leave",
                                    "result", "into"]
    assert list(dialog.widgets["gifts"].cget("values")) == ["birthday_gifts"]   # tables only
    holder = dialog.widgets["gifts"].master
    buttons = [str(c.cget("text")) for c in holder.winfo_children()
               if c.winfo_class() == "TButton"]
    assert buttons == [mv.SET_UP, mv.NEW_SET]
    assert "hana" in list(dialog.widgets["to"].cget("values"))
    assert list(dialog.widgets["result"].cget("values")) == ["reaction", "item"]
    dialog.set("gifts", "birthday_gifts")
    dialog.set("to", "hana")
    dialog.set("categories", '["Gifts"]')
    dialog.set("into", "reaction")
    dialog._pick(0)
    assert dialog.result == {"line": 'minigame gift_giving gifts=birthday_gifts to="hana" '
                                     'categories=["Gifts"] into reaction'}
    line = ('minigame gift_giving skippable gifts=birthday_gifts to="hana" '
            'categories=["Gifts"] into reaction')
    again = mv.MinigameDialog(ed.win, {"line": line})
    assert [again.vars[n].get() for n in ("gifts", "to", "categories", "into")] == [
        "birthday_gifts", "hana", '["Gifts"]', "reaction"]
    again._pick(1)
