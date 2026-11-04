"""Which tabs the strip shows (``tabchoice``) and View ▸ Tabs and panes…: File preview starts
hidden, the window has a box for every tab and pane and stays open while several are ticked,
every route to a page brings its tab back, the Editor always stays, and the author's look
(tabs, panes, Show warnings) is kept for every game (``uiprefs``)."""

import json

import pytest

from engine.tools.editor import studiostate, tabchoice, uiprefs
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import select, studio  # noqa: E402,F401


def _strip(win):
    return win.tab_strip.shown_words()


def _checks(widget):
    out = {}
    for child in widget.winfo_children():
        if child.winfo_class() == "TCheckbutton":
            out[str(child.cget("text"))] = child
        out.update(_checks(child))
    return out


def test_hidden_from_and_the_look_file(tmp_path, monkeypatch):
    assert tabchoice.hidden_from(None) == tabchoice.DEFAULT_HIDDEN
    assert tabchoice.hidden_from({"hidden": ["outline", 3]}) == {"outline"}
    monkeypatch.setattr(uiprefs, "folder_override", tmp_path)
    assert uiprefs.load() == {} and uiprefs.value("tabs", {"hidden": []}) == {"hidden": []}
    assert uiprefs.save(tabs={"hidden": ["map"]}, show_warnings=False, other=1)
    assert uiprefs.load() == {"tabs": {"hidden": ["map"]}, "show_warnings": False}
    (tmp_path / uiprefs.LOOK_NAME).write_text(json.dumps({"tabs": 3, "panes": None,
                                                          "show_warnings": "no"}))
    assert uiprefs.load() == {"panes": None}             # wrong types dropped
    (tmp_path / uiprefs.LOOK_NAME).write_text("{oops")
    assert uiprefs.load() == {}


def test_tabs_and_panes_window_and_every_route_back(studio, tmp_path):
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    assert _strip(win) == ["Editor", "Story map", "Database", "Game settings", "Outline"]

    # View ▸ Tabs and panes…: a box per tab and pane; several clicks, the window stays open.
    win.view_menu.invoke(tabchoice.LAYOUT_MENU)
    window = win.layout_window
    checks = _checks(window)
    assert {"Editor", "Story map", "Game settings", "Outline", "File preview", "Project",
            "Problems", "Help", "Lock pane layout"} <= set(checks)
    assert checks["Editor"].instate(["disabled"])        # every script opens there
    win.select_tab("settings")
    checks["Game settings"].invoke()
    checks["Outline"].invoke()
    checks["Help"].invoke()
    ed.root.update()
    assert window.winfo_exists() and window.winfo_viewable()
    assert _strip(win) == ["Editor", "Story map", "Database"]
    assert win.current_tab() == "editor" and not win.pane_shown("help")
    assert win.open_layout() is window                  # opened again: the same window
    window.destroy()

    # Kept for every game, not in the game's file.
    assert uiprefs.load()["tabs"] == {"hidden": ["asset", "outline", "settings"]}
    assert studiostate.read_state(game).tabs is None

    # File ▸ Game settings brings its tab back; Ctrl+6 brings Outline back.
    win.file_menu.invoke(tabchoice.GAME_SETTINGS_MENU)
    assert win.current_tab() == "settings" and "Game settings" in _strip(win)
    win.show_tab(win.tab_index("outline"))
    assert "Outline" in _strip(win)
    # A click on a picture shows File preview.
    select(ed, "images/bg/room.png")
    assert win.current_tab() == "asset" and "File preview" in _strip(win)

    # Show warnings is kept too.
    win.show_warnings.set(False)
    win.toggle_warnings()
    assert uiprefs.load()["show_warnings"] is False

    # Another game opens the way this one was left.
    win.set_tab_shown("database", False)
    other = studio(make_game(tmp_path / "other"), mapped=True)
    assert "Database" not in _strip(other.win) and not other.win.pane_shown("help")
    assert other.win.show_warnings.get() is False

    # Show all tabs; the default is saved as no tabs value at all.
    win.show_all_tabs()
    assert len(_strip(win)) == 6
    win.set_tab_shown("asset", False)
    assert uiprefs.load()["tabs"] is None


def test_a_games_own_old_value_is_read_until_the_author_changes_one(studio, tmp_path):
    game = make_game(tmp_path)
    studiostate.with_change(game, tabs={"hidden": ["outline"]})
    ed = studio(game, mapped=True)
    assert "Outline" not in _strip(ed.win)
