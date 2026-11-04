"""Studio's movable panes (``docking``): the saved layout, drop zones, and moving, closing,
locking and resetting panes in a real window."""

import json

import pytest

from engine.tools.editor import docking, studiostate, uiprefs
from engine.tools.editor.docking import ASSISTANT, BOTTOM, HELP, LEFT, PROBLEMS, RIGHT, Layout
from tests.tools.f45_games import studio as make_game

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)


def test_layout_round_trips_and_falls_back():
    layout = Layout().moved(ASSISTANT, BOTTOM).shown(HELP, False)
    again = Layout.from_json(json.loads(json.dumps(layout.to_json())))
    assert again == layout and again.dock_of(ASSISTANT) == BOTTOM and HELP in again.hidden
    assert again.in_dock(BOTTOM) == [PROBLEMS, HELP, ASSISTANT]
    assert Layout.from_json({"docks": {"assistant": "top", "nope": "left"},
                             "order": ["x"], "hidden": ["guide", "help"],
                             "locked": "yes"}) == Layout(hidden=frozenset({HELP}))
    assert Layout.from_json([1]) == Layout() and Layout().is_default
    assert not Layout(locked=True).is_default


def test_drop_zones():
    assert docking.drop_zone(10, 300, 1000, 600) == LEFT
    assert docking.drop_zone(990, 10, 1000, 600) == RIGHT
    assert docking.drop_zone(500, 590, 1000, 600) == BOTTOM
    assert docking.drop_zone(500, 100, 1000, 600) is None
    assert docking.drop_zone(-1, 100, 1000, 600) is None
    assert docking.zone_box(BOTTOM, 1000, 600) == (0, 420, 1000, 180)


def _texts(widget):
    out = []
    for child in widget.winfo_children():
        try:
            out.append(str(child.cget("text")))
        except Exception:
            pass
        out += _texts(child)
    return out


def _names(window):
    return [str(name) for name in window.panes()]


@pytest.mark.tk
def test_panes_move_close_lock_and_reset(studio, tmp_path):
    game = make_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    frames = win.pane_frames
    # Studio's usual layout: Project left, Problems and Help below, nothing on the right.
    assert _names(win.left_dock) == [str(frames["project"])]
    assert _names(win.bottom) == [str(frames[PROBLEMS]), str(frames[HELP])]
    assert str(win.right_dock) not in _names(win.hpane)
    # The AI Assistant opens on the right, then moves to the bottom, after Help.
    win.toggle_assistant()
    ed.root.update()
    assert _names(win.right_dock) == [str(frames[ASSISTANT])]
    win.move_pane(ASSISTANT, BOTTOM)
    ed.root.update()
    assert _names(win.bottom)[-1] == str(frames[ASSISTANT])
    assert str(win.right_dock) not in _names(win.hpane)           # an empty dock takes no room
    # The Guide can now open beside it (they no longer share a dock).
    win.toggle_guide()
    ed.root.update()
    assert win.assistant_shown and _names(win.right_dock) == [str(frames["guide"])]
    # Help closes with its ✕ and comes back from View.
    win.show_pane(HELP, False)
    ed.root.update()
    assert str(frames[HELP]) not in _names(win.bottom) and not win.dock_vars[HELP].get()
    win.dock_vars[HELP].set(True)
    win.toggle_pane(HELP)
    assert str(frames[HELP]) in _names(win.bottom)
    # The layout is kept per game.
    saved = uiprefs.load()["panes"]                     # the author's, for every game
    assert Layout.from_json(saved).dock_of(ASSISTANT) == BOTTOM
    assert studiostate.read_state(game).panes is None   # not in the game's own file
    # Locked: a drag doesn't move the pane.
    win.lock_var.set(True)
    win.toggle_lock()
    assert win.layout.locked

    class Event:
        def __init__(self, x, y):
            self.x_root, self.y_root = x, y

    area = win.hpane
    x0, y0 = area.winfo_rootx(), area.winfo_rooty()
    win._drag_press(ASSISTANT, Event(x0 + 300, y0 + area.winfo_height() - 5))
    win._drag_motion(ASSISTANT, Event(x0 + 2, y0 + 50))
    win._drag_release(ASSISTANT, Event(x0 + 2, y0 + 50))
    assert win.layout.dock_of(ASSISTANT) == BOTTOM
    # Unlocked: dragging the header to the left edge moves it there.
    win.lock_var.set(False)
    win.toggle_lock()
    win._drag_press(ASSISTANT, Event(x0 + 300, y0 + area.winfo_height() - 5))
    win._drag_motion(ASSISTANT, Event(x0 + 2, y0 + 50))
    assert any(bar.winfo_manager() for bar in win._outline)      # the drop outline shows
    win._drag_release(ASSISTANT, Event(x0 + 2, y0 + 50))
    ed.root.update()
    assert win.layout.dock_of(ASSISTANT) == LEFT
    assert not any(bar.winfo_manager() for bar in win._outline)
    assert _names(win.left_dock)[-1] == str(frames[ASSISTANT])
    # Reset: everything back where it started, and nothing kept in the state file.
    win.reset_layout()
    ed.root.update()
    assert win.layout == Layout() and uiprefs.load()["panes"] is None
    assert str(frames[ASSISTANT]) in _names(win.right_dock)
    assert not win.guide_shown or not win.assistant_shown          # they share a dock again
    # View ▸ Tabs and panes… has a box per pane, Lock and Reset, and stays open.
    from engine.tools.editor import tabchoice
    win.view_menu.invoke(tabchoice.LAYOUT_MENU)
    texts = _texts(win.layout_window)
    for label in ("Project", "Problems", "Help", docking.LOCK_MENU, docking.RESET_MENU):
        assert label in texts
