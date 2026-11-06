"""F64 round 1 in Studio: the codex item form's Count, Most held and "This is the money", and
the declarations they write (specs/F64-items/SPEC.md)."""

import pytest

from engine.script.codex import ITEM_COUNT_MAX
from engine.tools.editor import declarations as dec
from engine.tools.editor import files

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import (apply_check, commit,  # noqa: E402
                                                     open_database, text_of)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

MAIN_REF = "script/main.vns"


@pytest.mark.parametrize("values, head", [
    ({"count": ITEM_COUNT_MAX}, 'lock item coin "Coins" count'),
    ({"count": 50}, 'lock item coin "Coins" count 0 to 50'),
    ({"count": ITEM_COUNT_MAX, "money": True}, 'lock item coin "Coins" money'),
    ({"count": 50, "money": True}, 'lock item coin "Coins" count 0 to 50 money'),
    ({}, 'lock item coin "Coins"'),
])
def test_item_values_round_trip(values, head):
    full = {"title": "Coins", "category": None, "image": None, "text": (), **values}
    assert dec.codex_lines(dec.ITEM, "coin", full) == (head,)
    read = dec._codex_read(head.split()[3:], [])
    assert read == full


def test_tip_values_never_write_counts():
    full = {"title": "Lore", "category": None, "image": None, "text": (), "count": 5}
    assert dec.codex_lines(dec.TIP, "lore", full) == ('lock tip lore "Lore"',)


@pytest.mark.tk
def test_item_form_count_most_and_money(studio, tmp_path):
    game = files.new_game(tmp_path / "my_game")
    main = game / "script" / "main.vns"
    text = main.read_text("utf-8")
    main.write_text('lock item coin "Coins"\n' + text.replace(
        "label start:\n", "label start:\n    unlock item coin\n", 1), "utf-8")
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    db = open_database(ed, "codex")
    db.select("i:coin")
    f = db.form.fields
    assert {"count", "most", "money"} <= set(f)
    f["count"].check.invoke()
    assert 'lock item coin "Coins" count\n' in text_of(ed, MAIN_REF) + "\n"
    commit(db.form.fields["most"], "50")
    assert 'lock item coin "Coins" count 0 to 50\n' in text_of(ed, MAIN_REF) + "\n"
    db.form.fields["money"].check.invoke()
    assert 'lock item coin "Coins" count 0 to 50 money\n' in text_of(ed, MAIN_REF) + "\n"
    db.form.fields["count"].check.invoke()                 # off: a plain item again
    assert 'lock item coin "Coins"\n' in text_of(ed, MAIN_REF) + "\n"
