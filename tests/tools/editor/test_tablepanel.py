"""F64 round 2: Studio's Table panel (``tablepanel``), the rows-by-columns editor the gift
table and the shop table share: its pure helpers, and the grid in a Tk window (typed
columns, pinned rows, remove and move, a refused number with its rule)."""

import pytest

from engine.tools.editor import tablepanel as tp

tk = pytest.importorskip("tkinter")


def test_helpers():
    assert tp.moved("abc", 0, 1) == ("b", "a", "c")
    assert tp.moved("abc", 2, -2) == ("c", "a", "b")
    assert tp.moved("abc", 0, -1) == ("a", "b", "c")          # can't: unchanged
    assert tp.removed("abc", 1) == ("a", "c") and tp.removed("abc", 5) == ("a", "b", "c")
    assert tp.number_value(" 1,200 ", 0, 9999, blank=False) == (True, 1200)
    assert tp.number_value("", 0, 9, blank=True) == (True, None)
    assert tp.number_value("", 0, 9, blank=False) == (False, None)
    assert tp.number_value("10", 0, 9, blank=True) == (False, None)
    assert tp.number_value("x", 0, 9, blank=True) == (False, None)


@pytest.mark.tk
def test_the_grid():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        said: list[tuple] = []
        panel = tp.TablePanel(root, (
            tp.Column("item", "Item", tp.PICK, choices=lambda: [("tea", "Jasmine Tea"),
                                                                ("matches", "Matches")]),
            tp.Column("price", "Price", tp.NUMBER, lo=0, hi=99, blank=True,
                      rule="A price is 0 to 99."),
            tp.Column("note", "Note", tp.TEXT, blank=True),
            tp.Column("own", "Own", tp.LABEL, text=lambda row: f"own {row.get('item')}")),
            px=lambda v: int(v), on_edit=lambda i, k, v: said.append(("row", i, k, v)),
            on_pinned=lambda i, k, v: said.append(("pinned", i, k, v)),
            on_remove=lambda i: said.append(("remove", i)),
            on_move=lambda i, s: said.append(("move", i, s)), message=True)
        panel.frame.pack()
        panel.message.pack()

        def enter(spin):
            spin.focus_force()
            root.update()
            spin.event_generate("<Return>")
        panel.show([{"item": "tea", "price": None, "note": "hot"},
                    {"item": "matches", "price": 1, "note": None}],
                   pinned=[("Anything else", {"price": 3})])
        first, second = panel.rows
        assert first["item"].var.get() == "Jasmine Tea" and first["price"].get() == ""
        assert second["price"].get() == "1" and second["note"].var.get() == ""
        assert str(first["own"].cget("text")) == "own tea"
        assert "item" not in panel.pinned_cells[0]                 # the label stands there
        first["item"].var.set("Matches")
        first["item"].commit()
        second["price"].set("5")
        enter(second["price.spin"])
        second["price"].set("500")                                 # refused: the rule
        enter(second["price.spin"])
        assert second["price"].get() == "5" and panel.message.cget("text") == \
            "A price is 0 to 99."
        first["note"].var.set("  ")
        first["note"].commit()
        panel.pinned_cells[0]["price"].set("")
        enter(panel.pinned_cells[0]["price.spin"])
        first["down"].invoke()
        second["remove"].invoke()
        assert "disabled" in first["up"].state() and "disabled" in second["down"].state()
        assert said == [("row", 0, "item", "matches"), ("row", 1, "price", 5),
                        ("row", 0, "note", None), ("pinned", 0, "price", None),
                        ("move", 0, 1), ("remove", 1)]
    finally:
        root.destroy()
