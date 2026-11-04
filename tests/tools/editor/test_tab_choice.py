"""Which tabs the strip shows (``tabchoice``): File preview starts hidden, a tab can be hidden
from View ▸ Show tabs or the strip's right-click menu, every route to a page brings its tab
back, the Editor always stays, and the choice is kept in ``studio.json``."""

import pytest

from engine.tools.editor import studiostate, tabchoice
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import select, studio  # noqa: E402,F401


def _strip(win):
    return win.tab_strip.shown_words()


def test_hidden_from():
    assert tabchoice.hidden_from(None) == tabchoice.DEFAULT_HIDDEN
    assert tabchoice.hidden_from({"hidden": ["outline", 3]}) == {"outline"}
    assert tabchoice.hidden_from({"hidden": []}) == frozenset()


def test_hiding_and_every_route_back(studio, tmp_path):
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    assert _strip(win) == ["Editor", "Story map", "Database", "Game settings", "Outline"]
    labels = [win.view_menu.entrycget(i, "label") for i in range(win.view_menu.index("end") + 1)
              if win.view_menu.type(i) != "separator"]
    assert labels[6] == tabchoice.SHOW_TABS_MENU            # right after the six tab rows

    # Hide Game settings and Outline from the menu; the page on screen goes back to Editor.
    win.select_tab("settings")
    win.set_tab_shown("settings", False)
    win.set_tab_shown("outline", False)
    assert _strip(win) == ["Editor", "Story map", "Database"]
    assert win.current_tab() == "editor"
    assert studiostate.read_state(game).tabs == {"hidden": ["asset", "outline", "settings"]}

    # The Editor can't be hidden.
    win.set_tab_shown("editor", False)
    assert "Editor" in _strip(win) and win.tab_vars["editor"].get()

    # File ▸ Game settings brings its tab back; Ctrl+6 (View ▸ Outline) brings Outline back.
    win.file_menu.invoke(tabchoice.GAME_SETTINGS_MENU)
    assert win.current_tab() == "settings" and "Game settings" in _strip(win)
    win.show_tab(win.tab_index("outline"))
    assert "Outline" in _strip(win) and win.tab_vars["outline"].get()

    # A click on a picture shows File preview.
    select(ed, "images/bg/room.png")
    assert win.current_tab() == "asset" and "File preview" in _strip(win)

    # Show all tabs; the default comes back as no "tabs" entry at all.
    win.show_all_tabs()
    assert len(_strip(win)) == 6
    win.set_tab_shown("asset", False)
    assert studiostate.read_state(game).tabs is None

    # The choice is kept for the next window.
    win.set_tab_shown("database", False)
    again = studio(game, mapped=True)
    assert "Database" not in _strip(again.win)
