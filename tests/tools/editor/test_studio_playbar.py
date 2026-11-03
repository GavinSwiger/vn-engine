"""F47 W1, the Play bar (``01-design.md`` PR-F47-07..09, §6.1, §6.4; ``04-technical.md``
§7.4): AC-F47-01 (the bar, Play, Play this scene, Stop) and AC-F47-02 (Play from this scene
on box and row context menus). The game runner is faked: ``start`` records argv and ``poll``
hands out queued events."""

import json

import pytest

from engine.tools.editor import playbar
from engine.tools.editor.preview import PreviewEvent, PreviewState
from tests.tools.editor.conftest import patch_studio
from tests.tools.editor.test_studio_storyedit import (  # noqa: F401  (fixtures)
    events_on,
    lanterns,
    studio_l,
)
from tests.tools.editor.test_studio_window import studio  # noqa: F401  (fixture)

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.tk


class FakeGame:
    """Stands in for ``PreviewRunner``: records each argv and each stop."""

    def __init__(self) -> None:
        self.argvs: list[list[str]] = []
        self.events: list[PreviewEvent] = []
        self.stops = 0

    def start(self, argv) -> None:
        self.argvs.append(list(argv))
        self.events.append(PreviewEvent(PreviewState.STARTING))

    def poll(self):
        events, self.events = self.events, []
        return events

    def stop(self, timeout_s: float = 2.0) -> None:
        self.stops += 1

    def alive(self) -> bool:
        return False


def start_of(argv: list[str]) -> str | None:
    return argv[argv.index("--start") + 1] if "--start" in argv else None


def fake_game(win) -> FakeGame:
    game = FakeGame()
    win.runner = game
    return game


def test_ac_f47_01_the_play_bar_plays_from_the_start_this_scene_and_stops(
        studio, lanterns, monkeypatch):
    ed = studio_l(studio, lanterns)                     # on the Story map
    win, view = ed.win, ed.story_map
    game = fake_game(win)
    bar = win.play_bar
    assert [b.cget("text") for b in bar.buttons] == [
        "▶ Play", "▶ Play this scene", "■ Stop", "Play options…", "? Guide"]
    assert str(bar.play_button.cget("style")) == "TButton"          # the one primary
    assert [b.tooltip.text for b in bar.buttons[:3]] == [
        "Play from the start (Shift+F5)", "Play from the selected scene (F5)",
        "Stop the game (Ctrl+F2)"]
    assert bar.frame.winfo_ismapped() and bar.frame.winfo_y() < win.hpane.winfo_y()
    assert bar.stop_button.instate(["disabled"])                     # not running yet

    bar.play_button.invoke()                                         # ▶ Play: the start
    assert start_of(game.argvs[-1]) is None
    assert not bar.stop_button.instate(["disabled"])                 # starting
    win.apply_events([PreviewEvent(PreviewState.RUNNING)])
    played = json.loads((lanterns / ".studio" / "studio.json").read_text(encoding="utf-8"))
    assert played["played"] is True                                  # Guide step 7

    view.focus_box(view.layout.index_of("river"))                    # the selected box
    win._poll_preview()
    assert bar.scene_label.cget("text") == "river"
    bar.scene_button.invoke()
    assert start_of(game.argvs[-1]) == "river"
    ed.press(ed.map_canvas, "<Shift-F5>")
    assert start_of(game.argvs[-1]) is None
    ed.press(ed.map_canvas, "<F5>")
    assert start_of(game.argvs[-1]) == "river"

    bar.stop_button.invoke()                                         # ■ Stop ends it
    assert game.stops == 1 and bar.stop_button.instate(["disabled"])
    assert win.status_label.cget("text").endswith("Closed.")
    ed.press(ed.map_canvas, "<Control-F2>")                          # not running: nothing
    assert game.stops == 1

    ed.press(ed.map_canvas, "<Control-Key-1>")                       # the Editor: the cursor
    win.open_file("script/main.vns")
    win.text.mark_set("insert", "14.0")                              # in label festival
    ed.idle()
    win._poll_preview()
    assert bar.scene_label.cget("text") == "festival"
    ed.press(ed.text, "<F5>")
    assert start_of(game.argvs[-1]) == "festival"
    win.text.mark_set("insert", "2.0")                               # above every label
    ed.idle()
    assert bar.scene_label.cget("text") == "the beginning"
    ed.press(ed.text, "<F5>")
    assert start_of(game.argvs[-1]) is None

    rows = [(str(win.run_menu.entrycget(i, "label")),
             str(win.run_menu.entrycget(i, "accelerator")))
            for i in range(win.run_menu.index("end") + 1) if win.run_menu.type(i) == "command"]
    assert rows[:4] == [("Play", "Shift+F5"), ("Play this scene", "F5"), ("Stop", "Ctrl+F2"),
                        ("Play options…", "")]

    asked = []                                                      # Play options…
    patch_studio(monkeypatch, "ask_play_options",
                 lambda parent, values, fresh, font=None:
                 asked.append((values, fresh)) or ("trust = 2", True))
    bar.options_button.invoke()
    assert asked == [("", False)]
    bar.play_button.invoke()
    argv = game.argvs[-1]
    assert "--no-persistent" in argv and argv[-2:] == ["--set", "trust = 2"]

    bar.guide_button.invoke()                                        # ? Guide toggles
    state = json.loads((lanterns / ".studio" / "studio.json").read_text(encoding="utf-8"))
    assert state["guide_open"] is True and state["played"] is True
    assert str(bar.guide_button.cget("style")) == "Secondary.TButton"


def test_ac_f47_02_play_from_this_scene_on_box_and_row_menus(studio, lanterns, monkeypatch):
    patch_studio(monkeypatch, "CONTEXT_MENUS_POST", False)
    ed = studio_l(studio, lanterns)
    win, view = ed.win, ed.story_map
    game = fake_game(win)
    view.focus_box(view.layout.index_of("river"))
    menu = win.context_menu("box")
    assert menu.entrycget("end", "label") == "Play from this scene"
    menu.invoke("Play from this scene")
    assert start_of(game.argvs[-1]) == "river"

    events_on(ed, "stall")                              # an Events row of scene stall
    ed.events_view.select(0)
    menu = win.context_menu("row")
    assert menu.entrycget("end", "label") == "Play from this scene"
    menu.invoke("Play from this scene")
    assert start_of(game.argvs[-1]) == "stall"
    assert "Play from this scene" not in [
        str(m.entrycget(i, "label")) for m in (win.context_menu("map"),)
        for i in range(m.index("end") + 1) if m.type(i) == "command"]
