"""config.toml help in the window (2026-11-02, user: keep Studio updated; ``06``
AC-F45-64..66, their Tk row; the pure half is ``test_config_help.py``)."""

import pytest

from engine.core.config_schema import key_doc

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_assist_window import line, rows, set_line  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


def test_ac64_66_config_completion_and_help_in_the_window(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    ed.win.open_file("config.toml")
    ed.root.update()
    popup = ed.popup
    set_line(ed, 3, "")
    ed.press(ed.text, "<KeyPress>", keysym="bracketleft")      # "[" opens the sections
    assert line(ed, 3) == "[" and popup.is_open
    ed.press(ed.text, "<KeyPress>", keysym="c")
    ed.press(ed.text, "<KeyPress>", keysym="o")
    ed.press(ed.text, "<KeyPress>", keysym="n")
    assert rows(ed) == [("content_warning", "section")]
    ed.press(ed.text, "<Return>")
    assert line(ed, 3) == "[content_warning" and not popup.is_open
    ed.text.insert("insert", "]")
    ed.root.update_idletasks()
    assert ed.help_pane.content().split("\n")[0] == "[content_warning]"

    set_line(ed, 4, "min")                                     # keys of the section
    ed.press(ed.text, "<Control-space>")
    assert rows(ed) == [("min_seconds", "key")]
    ed.press(ed.text, "<Tab>")
    assert line(ed, 4) == "min_seconds"
    ed.root.update_idletasks()
    assert ed.help_pane.content().split("\n") == [
        "[content_warning] min_seconds", "Accepts seconds from 0 to 10",
        key_doc("content_warning", "min_seconds"), "min_seconds = 2.0   # default"]
    ed.text.mark_set("insert", "2.3")                          # [game] title
    ed.root.update_idletasks()
    assert ed.help_pane.content().split("\n")[:2] == [
        "[game] title", "Accepts text with at least one visible character"]
