"""F64 round 2 in Studio: Database ▸ Minigame data ▸ Shops (the stock on the Table panel),
the Shop in the Minigame form, and the codex item form's Price, in a real Studio window."""

from pathlib import Path

import pytest

from engine.tools.editor import declplan, files
from engine.tools.editor import minigamedata as mg

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import minigameview as mv  # noqa: E402
from tests.tools.editor.test_studio_database import (apply_check, helper,  # noqa: E402,F401
                                                     open_database)
from tests.tools.editor.test_studio_database import commit as type_into  # noqa: E402
from tests.tools.editor.test_studio_minigames import commit, open_minigames, text_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

DB_REF = declplan.DATABASE_REF
DATA = '''
lock item coin "Coins" in "Purse" money
lock item tea "Jasmine Tea" count 0 to 9 price 5
lock item matches "Matches" count 0 to 99
lock item lantern "Red Lantern"
default bought = {}

define stall_stock = {
    "tea": None,
    "matches": [1, 10],
    }
'''
CALLS = '''
label stall:
    minigame shop skippable stock=stall_stock into bought
    return
'''


def shop_game(tmp_path: Path, *, data: str = DATA) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    db = game / "script" / "database.vns"
    db.write_text(db.read_text(encoding="utf-8") + data, encoding="utf-8")
    main = game / "script" / "main.vns"
    main.write_text(main.read_text(encoding="utf-8") + CALLS, encoding="utf-8")
    return game


def stock_now(ed) -> dict:
    found = [ds for ds in mg.scan({DB_REF: text_of(ed, DB_REF)}) if ds.name == "stall_stock"]
    assert len(found) == 1
    return mg.value_of(mg.SHOP, found[0].model)


def enter(ed, spin) -> None:
    spin.focus_force()
    ed.root.update()
    spin.event_generate("<Return>")


def test_shop_table(studio, tmp_path, helper):
    ed = studio(shop_game(tmp_path), mapped=True)
    pane = open_minigames(ed)
    assert "Shops" in [pane.tree.item(g, "text") for g in pane.tree.get_children()]
    pane.pick("stall_stock")
    shop = pane.editor
    assert isinstance(shop, mv.ShopEditor)
    assert [(r["item"].var.get(), r["price"].get(), r["stock"].get(),
             str(r["own"].cget("text"))) for r in shop.rows] == [
        ("Jasmine Tea", "", "", "5"), ("Matches", "1", "10", "none")]
    # Each column writes the define; an empty price is the item's own.
    shop.rows[1]["price"].set("2")
    enter(ed, shop.rows[1]["price.spin"])
    shop.rows[1]["stock"].set("")
    enter(ed, shop.rows[1]["stock.spin"])
    assert stock_now(ed) == {"tea": None, "matches": 2}
    assert '    "matches": 2,' in text_of(ed, DB_REF)
    shop.rows[1]["price"].set("")                       # Matches has no price of its own
    enter(ed, shop.rows[1]["price.spin"])
    assert stock_now(ed) == {"tea": None, "matches": None}
    assert "Matches has no price of its own" in shop.panel.message.cget("text")
    shop.rows[1]["price"].set("3")
    enter(ed, shop.rows[1]["price.spin"])
    assert shop.panel.message.cget("text") == ""
    shop.rows[0]["stock"].set("1000")                   # refused in the cell, with the rule
    enter(ed, shop.rows[0]["stock.spin"])
    assert shop.rows[0]["stock"].get() == "" and shop.panel.message.cget("text") == \
        mv.SHOP_STOCK_RULE
    # Add, move, remove; the same item twice stays on screen, unsaved.
    shop.add_row()                                      # the next item, never the money
    assert list(stock_now(ed)) == ["tea", "matches", "lantern"]
    assert stock_now(ed)["lantern"] == 1                # no price of its own: 1 to start
    shop.rows[2]["up"].invoke()
    assert list(stock_now(ed)) == ["tea", "lantern", "matches"]
    text = text_of(ed, DB_REF)
    commit(shop.rows[1]["item"], "Jasmine Tea")
    assert shop.pending and shop.status.cget("text").startswith("Not saved yet: ")
    assert text_of(ed, DB_REF) == text
    commit(shop.rows[1]["item"], "Red Lantern")
    assert not shop.pending
    shop.rows[1]["remove"].invoke()
    assert stock_now(ed) == {"tea": None, "matches": 3}
    # Each change is one undo step.
    widget = ed.win.record_for(DB_REF).widget
    widget.edit_undo()
    assert list(stock_now(ed)) == ["tea", "lantern", "matches"]
    widget.edit_redo()
    assert stock_now(ed) == {"tea": None, "matches": 3}


def test_new_shop_and_the_form(studio, tmp_path, helper, monkeypatch):
    ed = studio(shop_game(tmp_path), mapped=True)
    pane = open_minigames(ed)
    monkeypatch.setattr(mv, "ask_text", lambda *a, **k: ("Night market", True))
    assert pane.new(mg.SHOP) == "night_market"
    assert 'define night_market = {\n    "tea": None,\n    }' in text_of(ed, DB_REF)
    dialog = mv.MinigameDialog(ed.win, None)
    assert "Shop" in list(dialog.game_box.cget("values"))
    dialog.set_game("shop")
    assert list(dialog.widgets) == ["stock", "money", "name", "into"]
    assert set(dialog.widgets["stock"].cget("values")) == {"stall_stock", "night_market"}
    dialog.set("stock", "stall_stock")
    dialog.set("name", "Daichi's Stall")
    dialog.set("into", "bought")
    dialog._pick(0)
    assert dialog.result == {"line": 'minigame shop stock=stall_stock name="Daichi\'s Stall" '
                                     'into bought'}


def test_item_form_price(studio, tmp_path):
    game = files.new_game(tmp_path / "my_game")
    main = game / "script" / "main.vns"
    text = main.read_text("utf-8")
    main.write_text('lock item tea "Tea" count 0 to 9\n' + text.replace(
        "label start:\n", "label start:\n    unlock item tea\n", 1), "utf-8")
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    db = open_database(ed, "codex")
    db.select("i:tea")
    price = db.form.fields["price"]
    type_into(price, "5")
    assert 'lock item tea "Tea" count 0 to 9 price 5\n' in text_of(ed, "script/main.vns") + "\n"
    type_into(price, "five")                                  # refused: the old value comes back
    assert price.var.get() == "5"
    type_into(price, "")
    assert 'lock item tea "Tea" count 0 to 9\n' in text_of(ed, "script/main.vns") + "\n"
