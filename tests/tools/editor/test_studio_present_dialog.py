"""F64 present at a menu, the Choice form's "Accept an item" section (specs/F64-items/
SPEC-present.md): ticking it, a row per item and one for any other item, its problems, and
the values it gives. Tk, in a real Studio window on the sample game."""

import pytest

from engine.tools.editor import formdialogs, formpresent, forms, presentdialog
from engine.tools.editor.formpresent import PresentValues, ReactionItem
from engine.tools.editor.forms import ChoiceItem, ChoiceValues

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import helper, sample_game  # noqa: E402,F401,I001
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


def _card(dialog) -> str:
    return dialog.card.get("1.0", "end-1c")


def test_accept_an_item_section(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    names = ed.win.story.names()
    values = ChoiceValues("", "", "What's that?", (ChoiceItem("Nothing.", old=0),))
    d = formdialogs.ChoiceDialog(ed.root, values, names=names)
    ed.root.update()
    section = d.accept
    assert str(section.box.cget("text")) == presentdialog.LET_THEM_SHOW
    assert not section.on.get() and section.add_button.instate(["disabled"])
    assert "present" not in _card(d)
    section.on.set(True)
    ed.root.update()
    assert not section.add_button.instate(["disabled"])
    assert _card(d).splitlines()[-3:] == ["    present:", "        else:", "            $ pass"]
    section.add()
    assert d.problem.cget("text") == formpresent.PRESENT_ITEM_TEXT
    assert d.buttons[0].instate(["disabled"])
    section.rows[0]["item"].set("red_lantern")
    section.rows[0]["goes"].set(forms.CONTINUES)
    assert d.problem.cget("text") == "" and not d.buttons[0].instate(["disabled"])
    section.other[0].set(forms.CONTINUES)
    assert "        red_lantern:" in _card(d).splitlines()
    section.add()
    section.rows[1]["item"].set("red_lantern")
    assert d.problem.cget("text") == formpresent.PRESENT_TWICE_TEXT
    section.remove()
    assert d.problem.cget("text") == ""
    d._pick(0)
    assert d.result is not None
    assert d.result.present == PresentValues("", (ReactionItem("red_lantern"),),
                                             ReactionItem(""))


def test_a_menu_read_with_an_option_opens_ticked(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    names = ed.win.story.names()
    present = PresentValues("bag", (ReactionItem("red_lantern", "hall", old=0),
                                    ReactionItem("coin", None, True, 1)),
                            ReactionItem("", None, False, 2))
    values = ChoiceValues(choices=(ChoiceItem("Go", old=0),), present=present)
    d = formdialogs.ChoiceDialog(ed.root, values, names=names)
    ed.root.update()
    assert d.accept.on.get() and d.values() == values
    _, _, goes_box = d.accept.rows[1]["widgets"]
    assert goes_box.instate(["disabled"])                   # lines of its own: kept
    # Six options in all: Accept an item is one of them.
    for n in range(4):
        d.add()
    assert d.tool_buttons[formdialogs.ADD].instate(["disabled"])
    d.accept.on.set(False)
    assert d.values().present is None
    assert not d.tool_buttons[formdialogs.ADD].instate(["disabled"])
    d._pick(1)
