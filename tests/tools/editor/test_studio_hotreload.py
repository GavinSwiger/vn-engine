"""F39 W2, Studio's side of hot reload wired into the window (``specs/F39-hot-reload/SPEC.md``
§4.2, §5.1): AC-F39-13 (the Run menu rows, Ctrl+R, update on save, the status texts and the
Problems suffix) and AC-F39-14 (save the line on screen: the game is updated in the same
window spot, well within 5 s; the docs page).

The game runner is the real ``PreviewRunner`` on in-process fake children
(``test_hotreload.FakeChild``: stdout is a real pipe, stdin records what Studio wrote), and
the check runner is ``FakeChecks``: the test hands the window each finished check.
"""

import time
from pathlib import Path

import pytest

from engine.app import hot_reload as game
from engine.core import editorreport as er
from engine.tools.editor.checker import CheckEvent, CheckState
from engine.tools.editor.hotreload import HELD_SUFFIX
from engine.tools.editor.preview import PreviewRunner, PreviewState
from engine.tools.editor.runwiring import UPDATE_MENU, UPDATE_ON_SAVE_MENU
from engine.tools.editor.views import _menu_off
from tests.tools.editor.test_hotreload import LINES, STARTED, FakeChild, result
from tests.tools.editor.test_studio_window import studio  # noqa: F401  (fixture)

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.tk

REPO = Path(__file__).resolve().parents[3]


class Game:
    """A real ``PreviewRunner`` on fake children, put in the window."""

    def __init__(self, win) -> None:
        self.children: list[FakeChild] = []
        self.runner = PreviewRunner(popen=self._popen, forward=lambda line: None)
        win.runner = self.runner
        win.hot._clock_text = lambda: "14:32"

    def _popen(self, argv, **kwargs):
        child = FakeChild(list(argv))
        self.children.append(child)
        return child

    @property
    def child(self) -> FakeChild:
        return self.children[-1]

    def close(self) -> None:
        for child in self.children:
            child.exit(0)


@pytest.fixture
def games():
    made: list[Game] = []

    def make(win) -> Game:
        made.append(Game(win))
        return made[-1]

    yield make
    for each in made:
        each.close()


def status(ed) -> str:
    return ed.win.status_label.cget("text")


def pump(ed, test, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ed.win._poll_preview()
        ed.root.update()
        if test():
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out; status {status(ed)!r}")


def finish_check(ed, *severities: str) -> None:
    """The newest check request finishes with ``severities``."""
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, ed.win._check_serial,
                                          result(*severities))])


def run_game(ed, game: Game) -> FakeChild:
    ed.win.play_from_start()
    child = game.child
    child.say(STARTED)
    pump(ed, lambda: status(ed) == "Running. F5 restarts it.")
    return child


def edit_and_save(ed, line: str = "2.0") -> None:
    ed.text.insert(line, "# edited\n")
    ed.press(ed.text, "<Control-s>")


def answer_reload(ed, game: Game, old: FakeChild, window=(120, 80)) -> FakeChild:
    """``old`` answers ``reload`` with its place and quits; returns the new child once it
    reported ``started``."""
    count = len(game.children)
    pump(ed, lambda: old.stdin.data().endswith(er.RELOAD_MESSAGE))
    old.say(game_state(window))
    old.exit(0)
    pump(ed, lambda: len(game.children) > count)
    new = game.child
    new.say(STARTED)
    pump(ed, lambda: status(ed) == "Running. Updated at 14:32.")
    return new


def game_state(window) -> bytes:
    return game.state_event(LINES, list(window))


def menu_rows(menu) -> list[tuple[str, str, str]]:
    return [(menu.type(i), str(menu.entrycget(i, "label")),
             str(menu.entrycget(i, "accelerator")) if menu.type(i) == "command" else "")
            for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]


# --- AC-F39-13 ---------------------------------------------------------------------------------

def test_ac_f39_13_studio_updates_the_running_game(studio, studio_game, games):
    """Both Run menu rows and Ctrl+R; the toggle on by default; with it on, Ctrl+S of a
    ``.vns`` file or ``config.toml`` updates; off doesn't; Ctrl+R works when off; nothing
    happens without a running game; the status follows the runner; the suffix while held."""
    ed = studio(studio_game, mapped=True)
    win = ed.win
    game = games(win)
    rows = menu_rows(win.run_menu)
    assert ("command", UPDATE_MENU, "Ctrl+R") in rows
    assert ("checkbutton", UPDATE_ON_SAVE_MENU, "") in rows
    assert UPDATE_MENU == "Update the running game"
    assert win.update_on_save.get() is True and win.hot.update_on_save    # D2: on

    # No running game: the row is off, and Ctrl+R and a save do nothing.
    assert UPDATE_MENU in _menu_off(win.run_menu)
    win.open_file("script/ch2.vns")
    asked = len(ed.checks.requests)
    ed.press(ed.text, "<Control-r>")
    edit_and_save(ed)
    assert len(ed.checks.requests) == asked + 1             # the save's own check only
    assert status(ed) == "Not running." and game.children == []

    # Running: Ctrl+S of a .vns file checks, then updates; the status follows.
    old = run_game(ed, game)
    assert UPDATE_MENU not in _menu_off(win.run_menu)
    edit_and_save(ed)
    assert status(ed) == "Updating…"
    assert ed.checks.requests[-1][0] is None                # no other file is unsaved
    finish_check(ed, "warning")                             # warnings never hold
    new = answer_reload(ed, game, old)
    assert "--resume-from-editor" in new.argv
    assert not win.play_bar.stop_button.instate(["disabled"])

    # An error holds the update: the old story runs on, N5's count goes to the game,
    # the status says so and Problems' summary gets the suffix.
    edit_and_save(ed)
    finish_check(ed, "error", "error")
    pump(ed, lambda: b'"msg":"held"' in new.stdin.data())
    assert new.stdin.data().endswith(b'{"v":1,"msg":"held","errors":2}\n')
    assert status(ed) == "Running the old story: fix 2 problems to update it."
    summary = ed.problems.get("1.0", "1.end")
    assert summary == "Checked: 2 errors." + HELD_SUFFIX
    assert summary.endswith(" The preview is still running the old story.")

    # Ctrl+R after a fix: the suffix goes, the game updates.
    ed.press(ed.text, "<Control-r>")
    assert status(ed) == "Updating…"
    assert ed.checks.requests[-1] == (None, win.edit_serial, True)   # saved files, armed
    finish_check(ed)
    assert ed.problems.get("1.0", "1.end") == "Checked: no problems."
    new = answer_reload(ed, game, new)

    # config.toml updates too.
    win.open_file("config.toml")
    edit_and_save(ed)
    assert status(ed) == "Updating…"
    finish_check(ed)
    new = answer_reload(ed, game, new)

    # The toggle off: a save only checks; Ctrl+R still updates.
    win.run_menu.invoke(win.run_menu.index(UPDATE_ON_SAVE_MENU))
    assert win.update_on_save.get() is False and not win.hot.update_on_save
    win.open_file("script/ch2.vns")
    edit_and_save(ed)
    finish_check(ed)
    assert status(ed) == "Running. Updated at 14:32." and len(game.children) == 4
    win.run_menu.invoke(win.run_menu.index(UPDATE_MENU))
    assert status(ed) == "Updating…"
    finish_check(ed)
    new = answer_reload(ed, game, new)

    # Unsaved text in another file: the save's check carries it, so the gate asks for one
    # more of the saved files only.
    win.update_on_save.set(True)
    win.toggle_update_on_save()
    win.open_file("script/main.vns")
    ed.text.insert("1.0", "# unsaved\n")
    win.open_file("script/ch2.vns")
    edit_and_save(ed)
    assert ed.checks.requests[-1][0] is not None            # the overlay
    finish_check(ed)
    assert ed.checks.requests[-1] == (None, win.edit_serial, True)
    finish_check(ed)
    new = answer_reload(ed, game, new)

    # Play restarts: never reported as "Updated"; Stop forgets any update.
    edit_and_save(ed)
    win.play_from_start()
    new.exit(0)
    pump(ed, lambda: len(game.children) == 7)
    game.child.say(STARTED)
    pump(ed, lambda: status(ed) == "Running. F5 restarts it.")
    finish_check(ed)
    win._poll_preview()
    assert status(ed) == "Running. F5 restarts it."
    ed.press(ed.text, "<Control-r>")
    win.stop_game()
    assert status(ed) == "Closed." and UPDATE_MENU in _menu_off(win.run_menu)


# --- AC-F39-14 ---------------------------------------------------------------------------------

def test_ac_f39_14_saving_the_line_on_screen_updates_the_game_in_place(
        studio, studio_game, games):
    """Edit the line on screen and save: the game shows the update well within 5 s, its new
    window opens at the old one's spot, and the place travels unchanged. The docs page tells
    authors how."""
    ed = studio(studio_game, mapped=True)
    win = ed.win
    game = games(win)
    old = run_game(ed, game)
    win.open_file("script/ch2.vns")
    ed.text.delete("9.0", "9.end")
    ed.text.insert("9.0", '    "The old bridge."')
    began = time.monotonic()
    ed.press(ed.text, "<Control-s>")
    assert (studio_game / "script" / "ch2.vns").read_text(encoding="utf-8").count(
        "The old bridge.") == 1
    finish_check(ed)
    new = answer_reload(ed, game, old, window=(-40, 300))
    assert time.monotonic() - began < 5
    assert new.argv[-2:] == ["--resume-from-editor", "--window-at=-40,300"]
    assert "--start" not in new.argv
    header = b'{"v":1,"msg":"resume","bytes":%d,"states":2,"lost":false}\n' % len(
        b"".join(LINES))
    assert new.stdin.data() == header + b"".join(LINES)

    page = (REPO / "docs" / "hot-reload.md").read_text(encoding="utf-8")
    flat = " ".join(page.split())
    for needed in ("Ctrl+S", "Ctrl+R", f"**{UPDATE_MENU}**", f"**{UPDATE_ON_SAVE_MENU}**",
                   "Story updated.", "Running the old story", "same place"):
        assert needed in flat, needed
    assert "(hot-reload.md)" in (REPO / "docs" / "scene-editor.md").read_text(encoding="utf-8")
    assert len((REPO / "docs" / "scene-editor.md").read_text(encoding="utf-8").split()) <= 1000


def test_update_with_nothing_changed_needs_no_check(studio, studio_game, games):
    """v1 finding 2: Ctrl+R right after a clean, full check of the saved files restarts the
    game with no new check. An edit, unsaved text, a changed file on disk, an error, or a
    check that left unsaved text out each bring the gate's check back."""
    import os
    from dataclasses import replace

    ed = studio(studio_game, mapped=True)
    win = ed.win
    game = games(win)
    old = run_game(ed, game)
    win.update_on_save.set(False)                           # only Ctrl+R updates here
    win.toggle_update_on_save()
    win.open_file("script/ch2.vns")
    edit_and_save(ed)

    def clean_check(*severities: str) -> None:
        win.apply_check_events([CheckEvent(CheckState.DONE, win._check_serial, replace(
            result(*severities), serial=win._check_serial))])

    clean_check()
    asked = len(ed.checks.requests)
    assert win.check_covers_saved()
    ed.press(ed.text, "<Control-r>")
    assert len(ed.checks.requests) == asked                 # no check: straight to restart
    old = answer_reload(ed, game, old)

    ed.text.insert("1.0", "# unsaved\n")                    # an edit, not saved
    assert not win.check_covers_saved()
    ed.press(ed.text, "<Control-s>")
    clean_check()
    assert win.check_covers_saved()
    image = studio_game / "images" / "hana" / "happy.png"
    stamp = image.stat().st_mtime_ns
    os.utime(image, ns=(stamp + 10**9, stamp + 10**9))      # changed on disk since
    assert not win.check_covers_saved()
    ed.press(ed.text, "<Control-r>")
    assert ed.checks.requests[-1] == (None, win.edit_serial, True)
    clean_check()
    old = answer_reload(ed, game, old)

    win.request_check()
    clean_check("error")                                    # errors: the gate decides
    assert not win.check_covers_saved()
    win.check_now()
    clean_check("warning")
    assert win.check_covers_saved()
