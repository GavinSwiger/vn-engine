"""F40 W2: Studio's developer-console wiring (``01-design.md`` §4.3, §6.4; ``04-technical.md``
§7.5; AC-F40-30, 31, 32, 33, 34, 38).

One test per AC, Tk, with the game runner faked: ``start`` records argv, ``send`` records
each stdin line, and ``console_events`` hands out queued answers."""

from pathlib import Path

import pytest

from engine.tools.editor import consoleclient as cc
from engine.tools.editor import dbmodel as db
from engine.tools.editor import files, guides, runwiring, views
from engine.tools.editor.consoleclient import ConsoleEvent, ConsoleTracker
from engine.tools.editor.preview import PreviewEvent, PreviewState
from tests.tools.editor.test_studio_storyedit import lanterns, studio_l  # noqa: F401

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import open_database  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

REPO = Path(__file__).resolve().parents[3]


class FakeGame:
    """Stands in for ``PreviewRunner``."""

    def __init__(self) -> None:
        self.argvs: list[list[str]] = []
        self.sent: list[bytes] = []
        self.answers: list[ConsoleEvent] = []
        self.events: list[PreviewEvent] = []

    def start(self, argv) -> None:
        self.argvs.append(list(argv))
        self.events.append(PreviewEvent(PreviewState.STARTING))

    def poll(self):
        out, self.events = self.events, []
        return out

    def console_events(self):
        out, self.answers = self.answers, []
        return out

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True

    def stop(self, timeout_s: float = 2.0) -> None:
        pass

    def alive(self) -> bool:
        return False


def fake_game(win) -> FakeGame:
    game = FakeGame()
    win.runner = game
    return game


def running(win) -> None:
    win.apply_events([PreviewEvent(PreviewState.RUNNING)])


def answer(win, game: FakeGame, event: ConsoleEvent) -> None:
    game.answers.append(event)
    win._poll_console()


def status(win) -> str:
    return str(win.status_label.cget("text"))


def enabled(menu, label: str) -> bool:
    return label not in views._menu_off(menu) and \
        str(menu.entrycget(label, "state")) != "disabled"


def test_ac_f40_30_open_console_plays_first_when_no_game_runs(studio, lanterns):
    ed = studio_l(studio, lanterns)
    win = ed.win
    game = fake_game(win)
    assert win.run_menu.entrycget(runwiring.CONSOLE_MENU, "accelerator") == "F12"
    ed.press(ed.map_canvas, "<F12>")                 # no game: Play from the start …
    assert len(game.argvs) == 1 and "--start" not in game.argvs[0]
    assert game.sent == [] and win.preview_state is PreviewState.STARTING
    running(win)                                     # … then open once it runs
    assert game.sent == [cc.open_line()]
    win.run_menu.invoke(runwiring.CONSOLE_MENU)      # running: just open
    assert game.sent == [cc.open_line()] * 2 and len(game.argvs) == 1


def test_ac_f40_31_jump_the_game_here_and_to_this_scene(studio, lanterns):
    ed = studio_l(studio, lanterns)
    win, view = ed.win, ed.story_map
    game = fake_game(win)
    menu = win.run_menu
    assert not enabled(menu, runwiring.JUMP_MENU)                     # no game: dimmed …
    assert menu.entrycget(runwiring.JUMP_MENU, "accelerator") == runwiring.NO_GAME
    view.focus_box(view.layout.index_of("river"))
    box_menu = win.context_menu("box")
    labels = [box_menu.entrycget(i, "label") for i in range(box_menu.index("end") + 1)
              if box_menu.type(i) == "command"]
    assert labels[-2:] == ["Play from this scene", runwiring.JUMP_HERE]
    assert not enabled(box_menu, runwiring.JUMP_HERE)
    win.jump_game_to_scene()                                          # … with a hint
    assert game.sent == [] and status(win) == runwiring.JUMP_NEEDS_GAME

    running(win)
    assert enabled(menu, runwiring.JUMP_MENU)
    assert menu.entrycget(runwiring.JUMP_MENU, "accelerator") == ""
    menu.invoke(runwiring.JUMP_MENU)                                  # the selected box
    assert game.sent == [cc.jump_line("river")]
    answer(win, game, ConsoleEvent("jump", True, "Jumped to river."))
    assert status(win) == "Console: Jumped to river."
    box_menu = win.context_menu("box")
    assert enabled(box_menu, runwiring.JUMP_HERE)
    box_menu.invoke(runwiring.JUMP_HERE)
    assert game.sent[-1] == cc.jump_line("river")


def test_ac_f40_32_database_in_the_game_now_and_change(studio, tmp_path):
    game_dir = files.new_game(tmp_path / "my_game")
    with open(game_dir / "script/database.vns", "a", encoding="utf-8") as f:
        f.write("points trust 0 to 10\n")
    ed = studio(game_dir, mapped=True)
    win = ed.win
    game = fake_game(win)
    pane = open_database(ed, db.CATEGORY_VARIABLE)
    pane.refresh()
    ed.root.update()
    assert pane.game_now is not None and not pane.game_now[1].winfo_ismapped()   # no game
    running(win)
    ed.root.update()
    name, line, label, button = pane.game_now
    assert name == "sent_lantern" and line.winfo_ismapped()
    assert game.sent == [cc.values_line()] and label.cget("text") == "In the game now: …"
    answer(win, game, ConsoleEvent("values", True, "", story=False, values=()))
    assert label.cget("text") == "In the game now: not started"
    assert button.instate(["disabled"])

    pane.select_category(db.CATEGORY_VARIABLE)
    win.ask_game_values()
    answer(win, game, ConsoleEvent("values", True, "", story=True,
                                   values=(("sent_lantern", "False"), ("trust", "4"))))
    assert label.cget("text") == "In the game now: False" and not button.instate(["disabled"])
    ed.answers.append("True")
    button.invoke()                                   # Change…: one field, then set
    assert ed.dialogs[-1][:4] == ("text", "Change sent_lantern in the game", "False",
                                  runwiring.CHANGE_HINT)
    assert game.sent[-1] == cc.set_line("sent_lantern", "True")
    answer(win, game, ConsoleEvent("set", True, "sent_lantern is now True."))
    assert status(win) == "Console: sent_lantern is now True."
    assert game.sent[-1] == cc.values_line()          # refreshed after the Change
    answer(win, game, ConsoleEvent("values", True, "", story=True,
                                   values=(("sent_lantern", "True"), ("trust", "4"))))
    assert label.cget("text") == "In the game now: True"

    pane.select_category(db.CATEGORY_METER)           # Meters too
    ed.root.update()
    name, line, label, button = pane.game_now
    assert name == "trust" and line.winfo_ismapped()
    answer(win, game, ConsoleEvent("values", True, "", story=True,
                                   values=(("sent_lantern", "True"), ("trust", "4"))))
    assert label.cget("text") == "In the game now: 4"

    win.apply_events([PreviewEvent(PreviewState.CLOSED)])        # the game ends: hidden
    ed.root.update()
    assert not line.winfo_ismapped()


def test_ac_f40_33_didnt_answer_after_two_seconds(studio, lanterns):
    ed = studio_l(studio, lanterns)
    win = ed.win
    game = fake_game(win)
    now = [100.0]
    win.__dict__["_console_tracker"] = ConsoleTracker(clock=lambda: now[0])
    running(win)
    win.jump_game_to("river")
    now[0] += 1.9
    win._poll_console()
    assert not status(win).startswith(cc.DIDNT_ANSWER)
    now[0] += 0.2
    win._poll_console()
    assert status(win).startswith(cc.DIDNT_ANSWER)
    assert "Try again" in status(win)
    answer(win, game, ConsoleEvent("jump", True, "Jumped to river."))   # too late: ignored
    assert status(win).startswith(cc.DIDNT_ANSWER)


def test_ac_f40_34_dev_console_doc_is_linked_from_help():
    assert ("Developer console", "dev-console.md") in guides.GUIDES
    text = (REPO / "docs" / "dev-console.md").read_text(encoding="utf-8")
    flat = " ".join(text.split())
    for words in ("runs real Python with your permissions", "aren't a sandbox",
                  "persistent data and to files aren't undone",
                  "Never paste code you don't understand",
                  runwiring.CONSOLE_MENU, runwiring.JUMP_MENU, runwiring.JUMP_HERE,
                  "In the game now:", "Change…", cc.DIDNT_ANSWER, "F12"):
        assert words in flat, words
    assert "(dev-console.md)" in (REPO / "docs" / "scene-editor.md").read_text("utf-8")


def test_ac_f40_38_forged_answers_are_escaped_short_and_never_acted_on(studio, lanterns):
    ed = studio_l(studio, lanterns)
    win = ed.win
    game = fake_game(win)
    running(win)
    before = status(win)
    answer(win, game, ConsoleEvent("jump", True, "Jumped to evil."))    # nothing asked
    assert status(win) == before
    win.jump_game_to("river")
    forged = "\u202eevil\nfile:///C:/x " + "x" * 5000
    answer(win, game, ConsoleEvent("jump", True, forged))
    shown = status(win)
    assert shown.startswith("Console: ") and len(shown) <= len("Console: ") + 200
    assert "\n" not in shown and "\u202e" not in shown
    assert game.sent == [cc.jump_line("river")]               # nothing sent in reply
    assert ed.win.current_tab() == "map"                       # nothing opened
    win.ask_game_values()
    answer(win, game, ConsoleEvent("values", True, "", story=True,
                                   values=(("not_a_variable", "1"),)))
    assert win.game_values == (True, {})                       # unknown names ignored
