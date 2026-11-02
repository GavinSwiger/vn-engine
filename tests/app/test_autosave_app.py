"""F11 step 10 in the real app (App S, unthreaded writer unless a test says threaded):
auto-saves on the timer, at choices, and on request (AC-F11-28); on leaving by Main Menu and
by quit (AC-F11-29, I-2, I-3); the quit and Main Menu words (AC-F11-30, C6); a choices
auto-save loaded (AC-F11-33); the quit auto-save's kept thumbnail (AC-F11-16's quit row);
and ``autosave_now("quit")`` on the writer's thread within the quit deadline (AC-F11-54).

The timer is driven by a fake ``dt``: ``SaveService.update`` is wrapped so a scripted frame
can stand for many seconds of play (``06`` §0.2 ``frame_dt``; the App's own frame dt is
clamped). Template S's menu rows use a small menu script of their own until Template S is
whole (I-14 A8).
"""

import errno
import threading
import time

import pygame
import pytest

from engine.app.saves import SaveService
from engine.core import safefile
from engine.persist import limits, saves
from engine.persist.saves import SlotId, SlotStatus
from engine.render.thumbnail import decode_jpeg
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.nav import InputKind
from tests.app.test_saves_service import (LINE6, at_line, file_of, launch, line_text, make_game,
                                          notices, play, save_log, unthreaded, wait)
from tests.fakes.loop import post_key, post_quit
from tests.persist import save_support as ss

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

LINE8 = "The wind picks up."
ON = "[saves]\nautosave_quit = true\n"
LINES = "".join(f'    "L{n}"\n' for n in range(1, 10))
LINES_SCRIPT = f"label start:\n{LINES}    return\n"
MENU_SCRIPT = '''define hana = Character("Hana")
default trust = 0
label start:
    menu:
        hana "Where should we go?"
        "Help Hana with the posters":
            $ trust += 1
            hana "Thanks!"
        "Go home":
            "Home."
    "Between."
    menu:
        "Again?"
        "Yes":
            "Yes."
        "No":
            "No."
    return
'''
QUIT_LOST = "Quit the game? Unsaved progress will be lost."
TITLE_LOST = "Return to the title screen? Unsaved progress will be lost."


@pytest.fixture
def fake_dt(monkeypatch):
    """``ctl["dt"]``, when set, is the next ``SaveService.update``'s dt (seconds of play)."""
    ctl: dict = {"dt": None}
    real = SaveService.update

    def update(self, dt):
        real(self, ctl["dt"] if ctl["dt"] is not None else dt)

    monkeypatch.setattr(SaveService, "update", update)
    return ctl


def spend(ctl: dict, seconds: float):
    """One frame standing for ``seconds`` of play."""
    ctl["dt"] = seconds
    yield
    ctl["dt"] = None


def autos(game) -> list[str]:
    """The Auto saves' descriptions, oldest ``seq`` first."""
    heads = [saves.read_slot_full(game / "saves", SlotId("auto", n), game_id=ss.GAME_ID)
             for n in range(1, 7)]
    ok = sorted((h for h in heads if h.status is SlotStatus.OK), key=lambda h: h.meta.seq)
    return [h.meta.description for h in ok]


def files(game) -> list[str]:
    folder = game / "saves"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def advance(app, text: str):
    """Space until ``text`` is the shown line, then a few frames for a save's write."""
    while line_text(app) != text:
        post_key(pygame.K_SPACE)
        yield
        yield
    for _ in range(2):
        yield


def word(app, action: str) -> str:
    return app.shell.words.get(app.shell.confirm_key(action))


def top_message(app) -> str | None:
    top = app.screens.top
    return top.message if isinstance(top, ConfirmScreen) else None


def yes(app):
    post_key(pygame.K_LEFT)
    yield
    post_key(pygame.K_RETURN)
    yield


# --- AC-F11-28: the timer, a request, and blocking ------------------------------------------

def test_ac28_timer_request_interval_and_block(tmp_path, scripted_app, unthreaded, fake_dt):
    """Each row acts at line Ln, then advances to L(n+1): the Auto saves made at L(n+1)."""
    game = make_game(tmp_path)
    (game / "script" / "main.vns").write_text(LINES_SCRIPT, encoding="utf-8")

    def menu_20s(app):
        app.shell.open_game_menu(InputKind.KEYS)
        yield
        yield from spend(fake_dt, 10)
        yield from spend(fake_dt, 10)
        app.shell.close_game_menu()
        yield from wait(lambda: app.screens.story_may_run())

    def menu_290_20(app):
        yield from spend(fake_dt, 290)
        yield from menu_20s(app)

    def blocked(app):
        app.saves.set_blocked(save="In a minigame.")
        yield from spend(fake_dt, 400)

    def unblock(app):
        app.saves.set_blocked(save=None)
        yield

    def interval(n, seconds):
        def act(app):
            app.saves.autosave_interval = n
            yield from spend(fake_dt, seconds)
        return act

    def request(app):
        app.saves.request_autosave()
        yield

    rows = [  # (at line, action, Auto saves made at the next line)
        ("L1", lambda app: spend(fake_dt, 300), 1),           # due at P6f, saved at the next
        ("L2", menu_290_20, 0),                                # menu time doesn't count
        ("L3", blocked, 0),                                    # blocked across the advance
        ("L4", unblock, 0),                                    # 290 s + 400 s blocked: frozen
        ("L5", request, 1),
        ("L6", interval(60, 61), 1),
        ("L7", interval(0, 1000), 0),
        ("L8", interval(300, 0), 1),                           # back on, 1000 s banked
    ]

    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        out["rows"] = []
        for line, act, _ in rows:
            yield from wait(lambda line=line: at_line(app, line))
            before = len(autos(game))
            yield from act(app)
            at_line_count = len(autos(game)) - before
            nxt = f"L{int(line[1:]) + 1}"
            yield from advance(app, nxt)
            out["rows"].append((line, at_line_count, autos(game)[before:],
                                app.saves.autosave_pending))
        app.saves.autosave_interval = 300

    out = play(scripted_app, script, last=600)
    assert launch(game) == 0
    for (line, _, made), (_, at_count, got, pending) in zip(rows, out["rows"], strict=True):
        nxt = f"L{int(line[1:]) + 1}"
        assert at_count == 0, line                             # never at the line itself
        assert got == [nxt] * made, (line, got)
        assert pending is False, line                          # the request cleared
    assert not file_of(game, "quick-1.vnsave").exists()


def test_a_failed_auto_save_does_not_stop_the_next(tmp_path, scripted_app, unthreaded):
    """I-3 (AC-F11-29 A2): an Auto save whose write fails (W83, the problem notice) is
    followed by a successful one in another Auto slot."""
    game = make_game(tmp_path)
    (game / "script" / "main.vns").write_text(LINES_SCRIPT, encoding="utf-8")
    real = safefile.write_atomic
    fails = [1]

    def write_atomic(target, pieces, **kw):
        if target.name.endswith(".vnsave") and fails:
            fails.pop()
            raise OSError(errno.EIO, "io")
        return real(target, pieces, **kw)

    def script(app, out):
        yield from wait(lambda: at_line(app, "L1"))
        for line in ("L2", "L3"):
            app.saves.request_autosave()
            yield from advance(app, line)
        out["notices"] = notices(app)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(safefile, "write_atomic", write_atomic)
        out = play(scripted_app, script)
        assert launch(game) == 0
    assert out["notices"] == ["Couldn't save: the file couldn't be written."]
    assert "couldn't save to Auto 1: couldn't write" in save_log(game)
    assert autos(game) == ["L3"] and files(game) == ["auto-2.vnsave"]


# --- AC-F11-28 choices rows, AC-F11-33, AC-F11-31's timer ---------------------------------------

def test_ac28_ac33_choices_auto_save_loads_and_is_not_saved_again(tmp_path, scripted_app,
                                                                 unthreaded, fake_dt):
    """Reaching a menu makes one Auto save holding it; the game menu and F5 add none to the
    Auto page; loading it makes no new Auto save (restored), resets the timer, and the
    choice works (``trust`` 1, ``Thanks!``). ``autosave_choices = false`` at the next menu:
    none."""
    from engine.ui.builtin.choice_screen import ChoiceScreen

    game = make_game(tmp_path)
    (game / "script" / "main.vns").write_text(MENU_SCRIPT, encoding="utf-8")

    def script(app, out):
        yield from wait(lambda: isinstance(app.screens.top, ChoiceScreen))
        for _ in range(4):
            yield
        out["first"] = autos(game)
        app.shell.open_game_menu(InputKind.KEYS)
        for _ in range(3):
            yield
        app.shell.close_game_menu()
        yield from wait(lambda: isinstance(app.screens.top, ChoiceScreen))
        post_key(pygame.K_F5)
        for _ in range(4):
            yield
        out["after_f5"] = autos(game)
        yield from spend(fake_dt, 100)
        app.saves.load_from(SlotId("auto", 1), InputKind.KEYS, origin="title")   # no question
        yield from wait(lambda: app.saves.loading_slot is None)
        yield from wait(lambda: isinstance(app.screens.top, ChoiceScreen))
        out["timer"] = app.saves.timer
        for _ in range(20):                                    # past F07's 250 ms guard
            yield
        out["after_load"] = autos(game)
        post_key(pygame.K_1)
        yield from wait(lambda: line_text(app) == "Thanks!")
        out["trust"] = app.story.checkpoint().variables["trust"]
        app.saves.autosave_choices = False
        while not isinstance(app.screens.top, ChoiceScreen):
            post_key(pygame.K_SPACE)
            yield
            yield
        for _ in range(4):
            yield
        out["second_menu"] = autos(game)

    out = play(scripted_app, script, last=400)
    assert launch(game) == 0
    menu = ["Hana: Where should we go?"]
    assert out["first"] == menu
    assert out["after_f5"] == menu and file_of(game, "quick-1.vnsave").is_file()
    assert out["timer"] < 0.05                                 # reset by the load
    assert out["after_load"] == menu
    assert out["trust"] == 1
    assert out["second_menu"] == menu


# --- AC-F11-29 Main Menu row, AC-F11-30 Main Menu words, the title rows --------------------------

def test_ac29_main_menu_auto_save_then_the_title(tmp_path, scripted_app, unthreaded, fake_dt):
    """Main Menu → Yes saves line 8 to an Auto slot before the title's first frame; 400 s on
    the title, New Game, and advancing make none; a quit from the title makes none."""
    from engine.ui.builtin.title_screen import TitleScreen

    game = make_game(tmp_path, ON)
    config = (game / "config.toml").read_text(encoding="utf-8")
    (game / "config.toml").write_text(config.replace("enabled = false", "enabled = true"),
                                      encoding="utf-8")

    def on_title(app) -> bool:
        return isinstance(app.screens.top, TitleScreen)

    def script(app, out):
        yield from wait(lambda: app.shell is not None and on_title(app))
        app.shell.start_new_game()
        yield from wait(lambda: at_line(app, LINE6))
        yield from advance(app, LINE8)
        out["words"] = (word(app, "main_menu"), word(app, "quit"))
        app.shell.open_game_menu(InputKind.KEYS)
        yield
        app.shell.ask_main_menu(InputKind.KEYS)
        yield
        out["question"] = top_message(app)
        yield from yes(app)
        yield from wait(lambda: on_title(app))
        out["at_title"] = autos(game)
        yield from spend(fake_dt, 400)
        for _ in range(30):
            yield
        app.shell.start_new_game()
        yield from wait(lambda: at_line(app, LINE6))
        yield from advance(app, LINE8)
        out["after"] = autos(game)
        app.shell.open_game_menu(InputKind.KEYS)
        yield
        app.shell.ask_main_menu(InputKind.KEYS)
        yield
        app.saves.autosave_quit = False                         # I-2: no file
        out["words_off"] = word(app, "main_menu")
        yield from yes(app)
        yield from wait(lambda: on_title(app))
        for _ in range(30):
            yield
        out["off"] = autos(game)
        app.saves.autosave_quit = True                          # the title's quit: none

    out = play(scripted_app, script, last=900)
    assert launch(game) == 0
    assert out["words"] == ("Return to the title screen?", "Quit the game?")
    assert out["question"] == "Return to the title screen?"
    assert out["at_title"] == [LINE8]
    assert out["after"] == [LINE8]
    assert out["words_off"] == TITLE_LOST
    assert out["off"] == [LINE8]
    assert autos(game) == [LINE8]


# --- AC-F11-29 quit rows, AC-F11-16 quit row ------------------------------------------------------

def _quit_menu_yes(app, out):
    app.shell.open_game_menu(InputKind.KEYS)
    yield
    app.shell.ask_quit(InputKind.KEYS)
    yield
    out["question"] = top_message(app)
    out["kept"] = app.shell.kept_thumbnail
    yield from yes(app)


def _quit_close_yes(app, out):
    post_quit()
    yield
    out["question"] = top_message(app)
    out["kept"] = app.shell.kept_thumbnail
    yield from yes(app)


def _quit_no_then_close_close(app, out):
    post_quit()
    yield
    post_key(pygame.K_ESCAPE)                                  # No
    yield from wait(lambda: top_message(app) is None)
    for _ in range(4):
        yield
    out["after_no"] = (files(out["game"]), line_text(app), type(app.screens.top).__name__)
    yield                                                      # then QUIT, QUIT (the ending)


def _quit_error(app, out):
    app.show_fatal_error(RuntimeError("boom"))
    yield
    yield                                                      # then QUIT: exit 1


QUIT_ROWS = {  # name: (script, config, expected exit, Auto saves after)
    "menu_quit_yes": (_quit_menu_yes, ON, 0, [LINE8]),
    "close_yes": (_quit_close_yes, ON, 0, [LINE8]),
    "no_then_close_close": (_quit_no_then_close_close, ON, 0, [LINE8]),
    "autosave_quit_false": (_quit_menu_yes, "", 0, []),
    "eacces": (_quit_close_yes, ON, 0, []),
    "error_screen": (_quit_error, ON, 1, []),
}


@pytest.mark.parametrize("name", list(QUIT_ROWS))
def test_ac29_quit_auto_save(tmp_path, scripted_app, unthreaded, name):
    """Each way of quitting at line 8: the Auto slot holds line 8 before exit 0 (with the
    kept thumbnail: no dialog, no dim), or no file."""
    act, config, code, expected = QUIT_ROWS[name]
    game = make_game(tmp_path, config)
    real = safefile.write_atomic

    def write_atomic(target, pieces, **kw):
        if target.name.endswith(".vnsave"):
            raise PermissionError(errno.EACCES, "denied")
        return real(target, pieces, **kw)

    def script(app, out):
        out["game"] = game
        yield from wait(lambda: at_line(app, LINE6))
        yield from advance(app, LINE8)
        yield from act(app, out)

    with pytest.MonkeyPatch.context() as mp:
        if name == "eacces":
            mp.setattr(safefile, "write_atomic", write_atomic)
        out = play(scripted_app, script, last=300)
        assert launch(game) == code
    assert autos(game) == expected
    if name != "error_screen":
        assert out["after_no" if name.startswith("no_") else "question"] is not None
    if name == "no_then_close_close":
        assert out["after_no"] == ([], LINE8, "TextboxScreen")
    elif name == "eacces":
        assert "couldn't save to Auto 1: no permission" in save_log(game)
    elif name in ("menu_quit_yes", "close_yes"):
        assert out["question"] == "Quit the game?"
        read = saves.read_slot_head(game / "saves", SlotId("auto", 1), game_id=ss.GAME_ID,
                                    thumb=True)
        thumb, kept = decode_jpeg(read.jpeg), out["kept"]
        assert kept is not None and thumb.get_size() == (320, 180)
        for x, y in ((160, 90), (20, 20), (300, 160)):         # the dialog's place included
            a, b = thumb.get_at((x, y))[:3], kept.get_at((x, y))[:3]
            assert all(abs(p - q) <= 8 for p, q in zip(a, b)), (x, y, a, b)
    elif name == "autosave_quit_false":
        assert out["question"] == QUIT_LOST
    assert files(game) == (["auto-1.vnsave"] if expected else [])


# --- AC-F11-30: the words -----------------------------------------------------------------------

def test_ac30_quit_words_follow_saving(tmp_path, scripted_app, unthreaded):
    """``Quit the game?`` while a quit would save; the "lost" text with ``autosave_quit =
    false``, before the first checkpoint, and while saving is blocked."""
    game = make_game(tmp_path, ON)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        saves_ = app.saves
        rows = out["rows"] = []
        rows.append(("possible", word(app, "quit")))
        saves_.autosave_quit = False
        rows.append(("off", word(app, "quit")))
        saves_.autosave_quit = True
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(app.story, "checkpoint", lambda: None)
            rows.append(("no checkpoint", word(app, "quit")))
        saves_.set_blocked(save="Not now.")
        rows.append(("blocked", word(app, "quit")))
        app.shell.ask_quit(InputKind.KEYS)                     # the dialog reads it too
        yield
        rows.append(("dialog", top_message(app)))
        post_key(pygame.K_ESCAPE)
        yield from wait(lambda: top_message(app) is None)
        saves_.set_blocked(save=None)
        rows.append(("unblocked", word(app, "quit")))
        rows.append(("main menu, no title", word(app, "main_menu")))

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["rows"] == [("possible", "Quit the game?"), ("off", QUIT_LOST),
                           ("no checkpoint", QUIT_LOST), ("blocked", QUIT_LOST),
                           ("dialog", QUIT_LOST), ("unblocked", "Quit the game?"),
                           ("main menu, no title", "Quit the game?")]


def test_set_blocked_keeps_the_other_mode_and_checks_types(tmp_path, scripted_app, unthreaded):
    """``set_blocked``: an omitted mode keeps its reason; the page reads it; F5 and F9 do
    nothing (no notice); a non-str reason is a TypeError."""
    game = make_game(tmp_path, ON)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        s = app.saves
        s.set_blocked(save="A", load="B")
        s.set_blocked(load=None)
        out["blocked"] = (s.slots.blocked("save"), s.slots.blocked("load"), s.can_save())
        s.set_blocked(save="A", load="B")
        post_key(pygame.K_F5)
        yield
        post_key(pygame.K_F9)
        yield
        yield
        out["quiet"] = (notices(app), type(app.screens.top).__name__)
        with pytest.raises(TypeError):
            s.set_blocked(save=3)
        s.set_blocked(save=None, load=None)
        s.autosave_quit = False

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["blocked"] == ("A", None, False)
    assert out["quiet"] == ([], "TextboxScreen")
    assert files(game) == []


# --- AC-F11-54: autosave_now("quit") on the writer's thread, within the deadline --------------

def test_ac54_quit_auto_save_runs_on_the_writer_thread_within_the_deadline(
        tmp_path, scripted_app, monkeypatch):
    """Threaded writer, fsync sleeping 0.5 s, ``CLOSE_WAIT_S`` 0.2 s: the quit's Auto save is
    written on the writer's thread, never the main one; the quit returns ≤ 1.0 s; the
    abandoned write leaves no file and logs W83 ``the quit didn't wait for it``."""
    game = make_game(tmp_path, ON)
    threads: list[int] = []
    done = threading.Event()
    real = safefile.write_atomic

    def write_atomic(target, pieces, **kw):
        if target.name.endswith(".vnsave"):
            threads.append(threading.get_ident())
            done.wait(0.5)                                     # the slow fsync
            raise OSError(errno.EIO, "abandoned")              # never a file after the test
        return real(target, pieces, **kw)

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)
    monkeypatch.setattr(limits, "CLOSE_WAIT_S", 0.2)
    started: dict = {}

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        yield
        started["t"] = time.perf_counter()                     # QUIT, QUIT follow

    play(scripted_app, script)
    try:
        assert launch(game) == 0
        elapsed = time.perf_counter() - started["t"]
    finally:
        done.set()
    assert elapsed <= 1.0, elapsed
    assert threads and threading.main_thread().ident not in threads
    assert "couldn't save to Auto 1: the quit didn't wait for it" in save_log(game)
    assert files(game) == []
