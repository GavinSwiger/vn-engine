"""F62 round 1 in Studio: the meter declaration reads and writes ranks (Database ▸ Meters'
Ranks table), the Change meter form's Notice text, rename inside ``points.rank``, and the
``ranks`` word's colour."""

from pathlib import Path

import pytest

from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, files
from engine.tools.editor.forms import code_of, form_by_key, rows
from engine.tools.editor.syntax import TAG_KEYWORD, color_spans
from tests.tools.editor.test_forms import _head, _inline

DB_REF = declplan.DATABASE_REF
RANKED = 'points hana 0 to 10 ranks "Stranger" 0 "Friend" 4 "Close" 8'


def test_meter_declarations_read_and_write_ranks():
    for line in (RANKED, 'points a b ranks "X" 3', 'points a 0 to 10 ranks "{{x" 1 "say \\"hi\\"" 2',
                 "points ranks 0 to 10"):
        names, values = dec.meter_read(line)
        assert values is not None, line
        assert dec.meter_line(names, values) == line           # byte for byte
    assert dec.meter_read(RANKED)[1]["ranks"] == (("Stranger", 0), ("Friend", 4), ("Close", 8))
    assert "ranks" not in dec.meter_read("points a 0 to 10")[1]          # unchanged shape
    assert dec.meter_read('points a 0 to 10 ranks "X" 30')[1] is None    # Edit as script
    assert dec.meter_read('points a ranks "X"')[1] is None
    base = {"low": 0, "high": 10, "start": None}
    for ranks, words in (((("A", 5), ("B", 5)), "lowest to highest"),
                         ((("A", 11),), "outside 0 to 10"), ((("", 1),), "needs a label"),
                         ((("A", 1), ("A", 2)), "Two ranks")):
        assert words in dec.ranks_problem({**base, "ranks": ranks}), ranks
        with pytest.raises(ValueError):
            dec.meter_line(("a",), {**base, "ranks": ranks})


def test_change_meter_form_has_notice_text():
    form = form_by_key("points")
    assert [f.key for f in form.fields] == ["meter", "op", "amount", "notice"]
    plain = {"meter": "hana", "op": "+=", "amount": "1"}
    noted = {**plain, "notice": 'She said "{wink}".'}
    assert form.write(plain) == "points hana += 1"
    assert form.write(noted) == 'points hana += 1 "She said \\"{{wink}\\"."'
    assert form.write({**plain, "op": "=", "notice": "  "}) == "points hana = 1"
    read, lines = _inline(form.write(plain), form.write(noted),
                          'points hana -= 2 "Daichi noticed."')
    got = [row for row in rows(read, lines) if row.form == "points"]
    assert [row.values for row in got] == [
        plain, noted, {"meter": "hana", "op": "-=", "amount": "2", "notice": "Daichi noticed."}]
    for row in got:
        code, _ = code_of(lines[_head(read, row).first - 1:_head(read, row).last])
        assert form.write(row.values) == code
    assert form.summary(noted) == 'hana += 1 · “She said "{wink}".”'


def test_ranks_word_is_coloured_only_before_a_label():
    spans = color_spans(RANKED)
    assert (RANKED.index("ranks"), RANKED.index("ranks") + 5, TAG_KEYWORD) in spans
    assert [t for _a, _b, t in color_spans("points ranks 0 to 10")] == [TAG_KEYWORD]


tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import commit, open_database, text_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401


def _meter_line(ed) -> str:
    return next(line for line in text_of(ed, DB_REF).split("\n") if line.startswith("points"))


@pytest.mark.tk
def test_database_meter_ranks_table(studio, tmp_path):
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "meter")
    ed.answers.append("hana")
    db.new_meter()                                  # + New ▸ Blank meter…
    assert _meter_line(ed) == "points hana 0 to 100"
    db.form.fields["add_rank"].invoke()
    ed.root.update()
    assert _meter_line(ed) == 'points hana 0 to 100 ranks "Rank 1" 0'
    commit(db.form.fields["rank0"], "Stranger")
    db.form.fields["add_rank"].invoke()
    ed.root.update()
    commit(db.form.fields["at1"], "40")
    commit(db.form.fields["rank1"], "Friend")
    assert _meter_line(ed) == 'points hana 0 to 100 ranks "Stranger" 0 "Friend" 40'
    # refused: not rising (the old number comes back, the line is unchanged)
    commit(db.form.fields["at1"], "0")
    assert ed.dialogs and "lowest to highest" in str(ed.dialogs[-1])
    assert _meter_line(ed).endswith('"Friend" 40')
    # the highest can't drop below a rank
    commit(db.form.fields["high"], "30")
    assert _meter_line(ed).startswith("points hana 0 to 100 ")
    db.form.fields["rank1"].widget.master.winfo_children()[-1].invoke()      # ×
    ed.root.update()
    assert _meter_line(ed) == 'points hana 0 to 100 ranks "Stranger" 0'
