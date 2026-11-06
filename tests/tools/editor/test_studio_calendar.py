"""F63 round 2: Studio's Game settings ▸ Calendar (``calendarpage``, ``calendarmodel``), on a
copy of the sample game in ``tmp_path``: the parts list, the fields, weekdays/months/seasons
on demand, the live preview, and each change as one undo step of config.toml."""

import pytest

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import calendarmodel as cm
from engine.tools.editor import settingsmodel as sm

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_schemes import (  # noqa: E402
    config_text, edit_editor, helper, sample_game)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk
_ = helper                                       # the fixture, imported for its name


def open_calendar(ed):
    ed.root.update()
    ed.win.show_tab(ed.win.tab_index("settings"))
    pane = ed.win.settings
    pane.select_page(sm.CALENDAR)
    ed.root.update()
    return pane.calendar_page


def with_config(ed, more: str):
    open_calendar(ed)
    edit_editor(ed, config_text(ed) + more)
    ed.win.settings.refresh()
    ed.root.update()
    return ed.win.settings.calendar_page


def texts(page, tag):
    return [page.canvas.itemcget(i, "text") for i in page.canvas.find_withtag(tag)]


def test_calendar_page_edits_and_previews(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    page = with_config(ed, '\n[theme]\nkit = "horror"\n')
    assert ed.win.settings.title_label.cget("text") == "Calendar"
    record = ed.win.files[CONFIG_REF]
    # The kit's parts and wording show until the author changes them.
    assert list(page.parts_list.get(0, "end")) == ["Dusk", "Midnight", "Witching hour", "Dawn"]
    assert "From the Horror kit" in page.rows["parts"].hint.cget("text")
    assert texts(page, "card_text") == ["Night 2"]
    assert texts(page, "clock_date") == ["Night 1"] and texts(page, "clock_part") == ["Dusk"]
    assert page.canvas.find_withtag("place:top_right")             # horror's clock corner
    assert not page.more_open and not page.rows["weekdays"].label.winfo_ismapped()
    before = config_text(ed)

    # Add a part after the selected one: the whole list is written, as one undo step.
    page.parts_list.selection_set(1)
    page.add_part("Small hours")
    ed.root.update()
    assert config_text(ed).endswith(
        '[calendar]\nparts = ["Dusk", "Midnight", "Small hours", "Witching hour", "Dawn"]\n')
    page = ed.win.settings.calendar_page
    assert page.parts_list.curselection() == (2,)
    assert page.move_part(-1) and page.parts_list.curselection() == (1,)
    page.parts_list.selection_clear(0, "end")
    page.parts_list.selection_set(2)                    # Midnight
    assert page.remove_part()
    ed.root.update()
    assert cm.own(sm.values(config_text(ed)))["parts"] == (
        "Dusk", "Small hours", "Witching hour", "Dawn")
    record.widget.edit_undo()
    record.widget.edit_undo()
    record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == before

    # Fields: start, wording, the card off, the corner; the preview follows.
    page = open_calendar(ed)
    page.inputs["start"].var.set("Monday 1 April")
    page.inputs["start"]._done()
    page.inputs["day_text"].var.set("{weekday} {month_day} {month}")
    page.inputs["day_text"]._done()
    page.inputs["day_card"].var.set(False)
    page.inputs["day_card"]._commit(False)
    page.inputs["place"].pick("bottom_left")
    ed.root.update()
    found = cm.own(sm.values(config_text(ed)))
    assert (found["start"], found["day_card"], found["place"]) == (
        "Monday 1 April", False, "bottom_left")
    page = ed.win.settings.calendar_page
    assert "Reads: Monday 1 April" in page.rows["start"].hint.cget("text")
    assert texts(page, "clock_date") == ["Monday 1 April"]
    assert page.canvas.find_withtag("card_off") and page.canvas.find_withtag(
        "place:bottom_left")
    assert str(page.rows["start"].default.cget("state")) == "normal"
    page.rows["place"].default.invoke()                     # Use default removes the line
    ed.root.update()
    assert "place" not in config_text(ed)

    # Weekdays, months and seasons on demand; a list the game would refuse isn't written.
    page = ed.win.settings.calendar_page
    page.toggle_more()
    ed.root.update()
    assert page.more_open and page.rows["seasons"].label.winfo_ismapped()
    page.inputs["seasons"].var.set("Wet, Dry")
    page.inputs["seasons"]._done()
    ed.root.update()
    assert 'seasons = ["Wet", "Dry"]' in config_text(ed)
    page = ed.win.settings.calendar_page
    page.inputs["weekdays"].var.set("A, a")                 # the same name twice
    page.inputs["weekdays"]._done()
    ed.root.update()
    assert "weekdays" not in config_text(ed)


def test_a_start_the_calendar_cant_read_is_explained(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    page = with_config(ed, '\n[calendar]\nstart = "Fooday 9"\n')
    assert page.problem_box.winfo_ismapped()
    assert "Fooday 9" in page.problem_label.cget("text")
