"""F47 condition builder model (``engine/tools/editor/conditions.py``; AC-F47-34)."""

from dataclasses import replace

import pytest

from engine.tools.editor import conditions as c
from engine.tools.editor.conditions import Row

# (condition as written, join, rows, the rows in words)
SHAPES = [
    ("coins >= 1", c.ALL, [Row(c.VARIABLE, "coins", c.GE, "1")], "coins is at least 1"),
    ("met_daichi", c.ALL, [Row(c.VARIABLE, "met_daichi", c.EQ, c.YES)], "met_daichi is yes"),
    ("not met_daichi", c.ALL, [Row(c.VARIABLE, "met_daichi", c.EQ, c.NO)],
     "met_daichi is no"),
    ('lantern != "red"', c.ALL, [Row(c.VARIABLE, "lantern", c.NE, '"red"')],
     "lantern is not red"),
    ("persistent.festivals == 2", c.ALL,
     [Row(c.VARIABLE, "persistent.festivals", c.EQ, "2")], "persistent.festivals is 2"),
    ("points.hana > 3", c.ALL, [Row(c.METER, "hana", c.GT, "3")],
     "hana meter is more than 3"),
    ('"river_god" in codex.tips', c.ALL, [Row(c.TIP, "river_god", c.HAS)],
     "has tip river_god"),
    ("'key' not in codex.items", c.ALL, [Row(c.ITEM, "key", c.HASNT)],
     "does not have item key"),
    ('"sad" in persistent.endings', c.ALL, [Row(c.ENDING, "sad", c.HAS)], "ending sad seen"),
    ('"promise" not in persistent.routes', c.ALL, [Row(c.ROUTE, "promise", c.HASNT)],
     "route promise not open"),
    ("persistent.playthrough <= -1.5", c.ALL, [Row(c.PLAYTHROUGH, "", c.LE, "-1.5")],
     "playthrough is at most -1.5"),
    ("  bought_lantern and trust >= 2 ", c.ALL,
     [Row(c.VARIABLE, "bought_lantern", c.EQ, c.YES), Row(c.VARIABLE, "trust", c.GE, "2")],
     "bought_lantern is yes and trust is at least 2"),
    ('a<1  or  "x" in codex.tips or b == None or c', c.ANY,
     [Row(c.VARIABLE, "a", c.LT, "1"), Row(c.TIP, "x", c.HAS),
      Row(c.VARIABLE, "b", c.EQ, "None"), Row(c.VARIABLE, "c", c.EQ, c.YES)],
     "a is less than 1 or has tip x or b is None or c is yes"),
    ("", c.ALL, [], ""),
]

KEPT_AS_TEXT = [
    "a and (b or c)", "(a and b)", "(a) and b", "a and b or c", "1 < x < 3", "3 < coins",
    'points["hana"] > 1', "len(codex.tips) > 2", "x == y", "codex", "points.hana",
    "persistent.endings == 1", "persistent._x", "a and b and c and d and e", '"a b" in codex.tips',
    "x in codex.tips", '"x" in inventory', "not not a", "x == -True", "x # note", "f(x)",
    "x is None", "a and\nb", "x ==", "dice.roll(1, 6) > 3", "x == b'1'",
]


def test_ac_f47_34_condition_builder_reads_writes_and_keeps_text():
    for text, join, rows, words in SHAPES:
        cond = c.read(text)
        assert cond is not None, text
        assert (cond.join, list(cond.rows), c.summary(cond)) == (join, rows, words), text
        assert c.write(cond) == text, text                      # byte for byte
        fresh = c.Condition(cond.rows, cond.join)               # written from scratch
        written = c.write(fresh)
        if rows:
            compile(written, "<condition>", "eval")
        again = c.read(written)
        assert again is not None and again.rows == cond.rows and again.join == join, written

    # Other conditions stay text (read gives None: "Written as script").
    for text in KEPT_AS_TEXT:
        assert c.read(text) is None, text

    # A changed row is written plainly; the rows left alone keep their spelling.
    cond = c.read("coins  >=  1  and   met")
    assert c.write(cond.with_rows([cond.rows[0], Row(c.TIP, "river_god", c.HAS)])) == \
        'coins  >=  1  and   "river_god" in codex.tips'
    assert c.write(replace(cond, join=c.ANY)) == "coins  >=  1 or met"
    assert c.write(cond.with_rows(cond.rows[:1])) == "coins  >=  1"
    assert c.write(cond.with_rows([])) == ""
    assert c.write(c.Condition((Row(c.METER, "hana", c.GE, "5"),
                                Row(c.ROUTE, "promise", c.HAS)), c.ANY)) == \
        'points.hana >= 5 or "promise" in persistent.routes'

    # The "is" menu per kind, the value field, and rows that can't be written yet.
    assert c.ops_for(c.METER) == c.COMPARE_OPS and c.ops_for(c.ENDING) == c.HAS_OPS
    assert [c.value_from_text(v) for v in ("3", "-2.5", "red", '"red"', "True", "yes")] == \
        ["3", "-2.5", '"red"', '"red"', "True", "yes"]
    assert c.value_text('"red"') == "red" and c.value_text("3") == "3"
    for row in (Row(c.METER, "hana", c.GE, '"a"'), Row(c.VARIABLE, "x", c.GE, ""),
                Row(c.VARIABLE, "codex", c.EQ, c.YES), Row(c.TIP, "", c.HAS),
                Row(c.VARIABLE, "x", c.HAS), Row(c.VARIABLE, "x", c.NE, c.YES),
                Row(c.VARIABLE, "x", c.EQ, "y")):
        assert c.problem(row), row
        with pytest.raises(ValueError):
            c.write(c.Condition((row,)))
    with pytest.raises(ValueError):
        c.write(c.Condition((Row(c.VARIABLE, "x", c.EQ, c.YES),) * 5))
