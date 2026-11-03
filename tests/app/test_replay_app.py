"""F36 W3 — scene replays in the game: AC-F36-15, 19, 20, 24, 26, 27.

Every run is App A (F12's in-process launch, ``scripted_app``: fake frame clock at 1/60 s,
hidden window, dev), scripted frame by frame with a generator (``play``). The story is a small
*Paper Lanterns*: ``festival`` (declared ``lock replay festival "The Festival"`` with
``coins = 3``) jumps on to ``stall``, which holds the ending ``good``. On the title the test
unlocks the scene and the ending in the live store, then opens Extras as the player would.
"""

import json

import pygame
import pytest

from engine.app import cli
from engine.persist.location import FILE_NAME
from engine.runtime.audio import EMPTY_AUDIO
from engine.runtime.replay import REPLAY_KIND, ReplayRun
from engine.runtime.stage import EMPTY_STAGE
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.endings_page import EndingsPage
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.scenes_page import ScenesPage
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.nav import InputKind
from engine.ui.shell import REPLAY_HIDDEN, Mode
from tests.app.test_autosave_app import advance, fake_dt
from tests.app.test_saves_service import line_text, play, unthreaded, wait
from tests.fakes.loop import post_key
from tests.persist.writer_support import tree

pytestmark = pytest.mark.display
__all__ = ["fake_dt", "unthreaded"]            # the fixtures, re-exported for pytest

FIRST = "Festival {var=coins} {var=name}."   # the line as the text box holds it
NO_SAVING = "Saving and loading are off during a replay."
CONFIG = '[game]\nid = "f36-replay"\ntitle = "Replay Test"\nversion = "1.0"\n\n' \
         '[textbox]\ncps = 0\n'
FESTIVAL = '''    "Festival {var=coins} {var=name}."
    "Festival two."
    jump stall
'''


def story(festival: str = FESTIVAL) -> str:
    return ('default coins = 0\ndefault name = "nobody"\n'
            'lock replay festival "The Festival":\n    coins = 3\n'
            'label start:\n    "Start."\n    jump festival\n'
            f'label festival:\n{festival}'
            'label stall:\n    "Stall."\n    ending good "Good End" "Lanterns"\n')


def game_of(tmp_path, script: str | None = None, config: str = ""):
    game = tmp_path / "game"
    (game / "script").mkdir(parents=True)
    (game / "config.toml").write_text(CONFIG + config, encoding="utf-8")
    (game / "script" / "main.vns").write_text(script or story(), encoding="utf-8")
    return game


def on_title(app) -> bool:
    return (not app.loading and app.persist is not None and app.shell is not None
            and app.shell.mode is Mode.TITLE and isinstance(app.screens.top, TitleScreen))


def unlock_all(app) -> None:
    store = app.persist.store
    store.unlock(REPLAY_KIND, "festival")
    store.unlock("ending", "good")


def extras_top(app) -> GameMenuScreen | None:
    top = app.screens.top
    return top if isinstance(top, GameMenuScreen) and top.menu == "extras" else None


def to_title(app):
    """Wait for the title, unlock the scene and the ending, let the title settle."""
    yield from wait(lambda: on_title(app))
    unlock_all(app)
    for _ in range(3):
        yield


def back_on_extras(app) -> bool:
    return app.shell.mode is Mode.TITLE and extras_top(app) is not None


# --- AC-F36-15 — the start ---------------------------------------------------------------------

def test_ac15_start_defaults_then_values_at_the_scene_after_the_fade(tmp_path, user_roots,
                                                                      scripted_app):
    """Scenes → The Festival (Enter): the title fades to black over ``ui.fade_ms`` taking no
    input, then the game starts at ``festival`` (not ``start``) with ``name`` at its default
    and ``coins`` at its starting value, an empty stage and silence, in the store's sandbox,
    with the replay's hidden entries."""
    game = game_of(tmp_path)

    def script(app, out):
        yield from to_title(app)
        screen = app.shell.open_extras("replays", by=InputKind.KEYS)
        for _ in range(12):
            yield
        out["page"] = type(screen.page)
        post_key(pygame.K_RETURN)                    # the focused tile: The Festival
        yield
        yield
        out["fading"] = (app.shell.mode, type(app.screens.top))
        start = out["frame"]
        yield from wait(lambda: app.shell.mode is Mode.GAME)
        out["fade_frames"] = out["frame"] - start
        yield from wait(lambda: line_text(app) is not None)
        interp = app.story.interp
        out.update(line=line_text(app), run=interp.replay,
                   values=(interp.G["coins"], interp.G["name"]),
                   empty=(interp.stage == EMPTY_STAGE, interp.audio == EMPTY_AUDIO),
                   sandbox=app.persist.store.in_sandbox,
                   hidden=app.shell.menus.session_hidden, page=out["page"],
                   request=(app.shell.replay.page, app.shell.replay.key))

    out = play(scripted_app, script)
    assert cli.main(["run", str(game)]) == 0
    assert out["done"]
    assert out["fading"] == (Mode.ENDING, BlackFadeScreen)
    assert 7 <= out["fade_frames"] <= 12              # ui.fade_ms 150 at 60 fps
    assert out["line"] == FIRST
    assert out["run"] == ReplayRun("festival", None, (("coins", 3),))
    assert out["values"] == (3, "nobody") and out["empty"] == (True, True)
    assert out["sandbox"] is True and out["hidden"] == REPLAY_HIDDEN
    assert out["page"] is ScenesPage and out["request"] == ("replays", "festival")


# --- AC-F36-19 — back to Extras ----------------------------------------------------------------

@pytest.mark.parametrize("reduce", [False, True], ids=["fades", "reduced-motion"])
def test_ac19_after_the_end_extras_on_the_source_page_row_focused(tmp_path, user_roots,
                                                                   scripted_app, reduce):
    """Endings → Good End: its label ``stall`` replays; after the ending's card the story
    ends, the game fades to black (1 s) and the title shows with Extras on Endings, the
    Good End row focused, the store out of its sandbox and nothing hidden. Reduced motion:
    no fade at either end (cuts)."""
    game = game_of(tmp_path, config="[effects]\nreduce = true\n" if reduce else "")

    def script(app, out):
        yield from to_title(app)
        screen = app.shell.open_extras("endings", by=InputKind.KEYS)
        for _ in range(12):
            yield
        page = screen.page
        out["focus_first"] = screen.scope.focused is page.widget_for("good")
        post_key(pygame.K_RETURN)
        seen_fade = False
        while app.shell.replay is None or line_text(app) != "Stall.":
            seen_fade |= any(isinstance(s, BlackFadeScreen) for s in app.screens)
            yield
        out["start_fade"] = seen_fade
        out["run"] = app.story.interp.replay
        seen_fade = False
        post_key(pygame.K_SPACE)
        while not back_on_extras(app):
            seen_fade |= any(isinstance(s, BlackFadeScreen) for s in app.screens)
            post_key(pygame.K_SPACE)                 # past the ending's card
            yield
        out["end_fade"] = seen_fade
        top = extras_top(app)
        for _ in range(12):
            yield
        out.update(page=(top.page_id, type(top.page)),
                   focused=top.scope.focused is top.page.widget_for("good"),
                   stack=[type(s) for s in app.screens], replay=app.shell.replay,
                   hidden=app.shell.menus.session_hidden,
                   sandbox=app.persist.store.in_sandbox)

    out = play(scripted_app, script, last=900)
    assert cli.main(["run", str(game)]) == 0
    assert out["done"]
    assert out["focus_first"] is True
    assert out["run"] == ReplayRun("stall")
    assert (out["start_fade"], out["end_fade"]) == ((False, False) if reduce else (True, True))
    assert out["page"] == ("endings", EndingsPage) and out["focused"] is True
    assert out["stack"] == [TitleScreen, GameMenuScreen]
    assert out["replay"] is None and out["hidden"] == frozenset()
    assert out["sandbox"] is False


# --- AC-F36-20 — saves untouched ---------------------------------------------------------------

def test_ac20_no_save_or_load_in_a_replay(tmp_path, user_roots, scripted_app, unthreaded,
                                          fake_dt):
    """A quick save made before, then in the replay: F5, F9, Q.Save/Q.Load/Save hidden, the
    timer (400 s of play), a chapter's auto-save, a choice's auto-save, ``ui saving on`` and
    ``ui loading on``, and the quit question's word: the save folder is byte-identical, and
    both pages' reason is ``replay_no_saving``."""
    festival = ('    "Festival {var=coins} {var=name}."\n'
                '    chapter night "Chapter 1" "Night"\n'
                '    ui saving on\n    ui loading on\n'
                '    "Festival two."\n'
                '    menu:\n        "Stay":\n            "Stayed."\n'
                '    jump stall\n')
    game = game_of(tmp_path, story(festival))

    def script(app, out):
        yield from wait(lambda: on_title(app))
        unlock_all(app)
        # A quick save to load from: New Game, F5, back to the title.
        app.shell.start_new_game()
        yield from wait(lambda: line_text(app) == "Start.")
        post_key(pygame.K_F5)
        yield from wait(lambda: (game / "saves" / "quick-1.vnsave").is_file())
        for _ in range(5):
            yield
        app.shell.return_to_title()
        yield from wait(lambda: on_title(app))
        before = tree(game / "saves")
        out["before"] = sorted(before)
        app.shell.open_extras("replays", by=InputKind.KEYS).page.port.start(
            "festival", InputKind.KEYS)
        yield from wait(lambda: line_text(app) == FIRST)
        post_key(pygame.K_F5)
        yield
        post_key(pygame.K_F9)
        yield
        yield
        out["confirm_after_f9"] = isinstance(app.screens.top, ConfirmScreen)
        out["quick"] = [e.id for e in app.shell.menus.shown("quick")]
        fake_dt["dt"] = 400.0                        # the timer's interval, many times over
        yield from advance(app, "Festival two.")     # past the chapter card and ui lines
        while not any(isinstance(s, ChoiceScreen) for s in app.screens):
            post_key(pygame.K_SPACE)                 # on to the choice (its auto-save)
            yield
            yield
        for _ in range(10):
            yield
        fake_dt["dt"] = None
        slots = app.saves.slots
        out.update(can_save=app.saves.can_save(), reasons=(slots.blocked("save"),
                                                           slots.blocked("load")),
                   quit_word=app.shell.confirm_key("quit"))
        out["after"] = tree(game / "saves") == before
        app.shell.ask_main_menu(InputKind.KEYS)      # End Replay
        yield from wait(lambda: back_on_extras(app))
        out["lifted"] = (slots.blocked("save"), slots.blocked("load"))
        out["final"] = tree(game / "saves") == before

    out = play(scripted_app, script, last=900)
    assert cli.main(["run", str(game)]) == 0
    assert out["done"]
    assert "quick-1.vnsave" in out["before"]
    assert out["confirm_after_f9"] is False
    assert "save" not in out["quick"] and "q_save" not in out["quick"] \
        and "q_load" not in out["quick"] and "history" in out["quick"]
    assert out["can_save"] is False and out["reasons"] == (NO_SAVING, NO_SAVING)
    assert out["quit_word"] == "confirm_quit"         # "Unsaved progress will be lost."
    assert out["after"] is True and out["final"] is True
    assert out["lifted"] == (None, None)


# --- AC-F36-24 — the game menu in a replay ----------------------------------------------------

def test_ac24_game_menu_end_replay_hidden_entries_and_settings_kept(tmp_path, user_roots,
                                                                     scripted_app):
    """The game menu reads "End Replay" where Main Menu was; Save, Load and Flowchart are
    gone and Settings' Delete progress is disabled; a volume changed in the replay stays.
    End Replay asks nothing: the game fades out and Extras comes back on Scenes."""
    game = game_of(tmp_path)

    def script(app, out):
        yield from to_title(app)
        out["progress_title"] = app.settings.progress()
        app.shell.open_extras("replays", by=InputKind.KEYS).page.port.start(
            "festival", InputKind.KEYS)
        yield from wait(lambda: line_text(app) == FIRST)
        app.shell.open_game_menu(InputKind.KEYS)
        yield
        menu = app.shell.game_menu()
        out["sidebar"] = [b.label() for b in menu.buttons]
        out["progress"] = app.settings.progress()
        app.settings.set("music_volume", 40)
        menu.button("main_menu").activate()
        yield
        out["asked"] = any(isinstance(s, ConfirmScreen) for s in app.screens)
        out["mode"] = app.shell.mode
        yield from wait(lambda: back_on_extras(app))
        top = extras_top(app)
        out.update(page=top.page_id, focused=top.scope.focused is top.page.widget_for("festival"),
                   volume=app.settings.value("music_volume"),
                   progress_after=app.settings.progress(),
                   menu_word=app.shell.entry_word("main_menu"))

    out = play(scripted_app, script, last=600)
    assert cli.main(["run", str(game)]) == 0
    assert out["done"]
    assert out["sidebar"] == ["Return", "History", "Settings", "End Replay", "Quit"]
    assert (out["progress_title"], out["progress"], out["progress_after"]) == \
        ("enabled", "disabled", "enabled")
    assert out["asked"] is False and out["mode"] is Mode.ENDING
    assert out["page"] == "replays" and out["focused"] is True
    assert out["volume"] == 40 and out["menu_word"] == "Main Menu"


# --- AC-F36-26 — a failing replay --------------------------------------------------------------

@pytest.mark.parametrize("where", ["default", "line"])
def test_ac26_a_failing_replay_takes_the_error_path_store_and_saves_as_before(
        tmp_path, user_roots, scripted_app, where):
    """A replay failing at a default (``boom`` divides by zero) or at a line after a
    ``persistent`` change: F01's error screen; the store is out of its sandbox with its
    values as before, and the persistent file and the save folder hold what they did."""
    if where == "default":
        text = story().replace('default name = "nobody"\n',
                               'default name = "nobody"\ndefault boom = 1 // 0\n')
    else:
        text = story('    $ persistent.seen_it = 7\n    $ x = 1 // 0\n    jump stall\n')
    game = game_of(tmp_path, 'default persistent.seen_it = 0\n' + text)

    def script(app, out):
        yield from to_title(app)
        app.persist.flush_now()
        yield
        path = game / "persistent" / FILE_NAME
        out["file"] = json.loads(path.read_bytes())["values"]
        out["saves"] = tree(game / "saves")
        app.shell.open_extras("replays", by=InputKind.KEYS).page.port.start(
            "festival", InputKind.KEYS)
        yield from wait(lambda: app.error_mode)
        for _ in range(3):
            yield
        store = app.persist.store
        out.update(sandbox=store.in_sandbox, seen_it=store.peek("seen_it"),
                   message=app._fatal_message,
                   file_after=json.loads(path.read_bytes())["values"],
                   saves_after=tree(game / "saves"))

    out = play(scripted_app, script, last=400)
    cli.main(["run", str(game)])
    assert out["done"]
    assert "zero" in out["message"].lower()
    assert out["sandbox"] is False and out["seen_it"] == 0
    assert out["file_after"] == out["file"] and out["saves_after"] == out["saves"]


# --- AC-F36-27 — dev run --replay --------------------------------------------------------------

def test_ac27_run_replay_starts_it_and_closes_at_its_end(tmp_path, user_roots, scripted_app,
                                                         capsys):
    """``run --replay festival``: no title; the replay's first line with its starting value;
    the game closes on its own when the scene jumps on. An unknown label is an error at
    launch with did-you-mean; usage errors for a bad name and the options it can't go with;
    ``--release`` refuses it."""
    game = game_of(tmp_path)
    seen: dict = {}

    def script(app, out):
        yield from wait(lambda: line_text(app) is not None)
        seen.update(stack=[type(s) for s in app.screens], line=line_text(app),
                    replay=app.shell.replay.page, titles=0)
        while True:
            seen["titles"] += isinstance(app.screens.top, TitleScreen)
            post_key(pygame.K_SPACE)
            yield

    play(scripted_app, script, last=600)
    assert cli.main(["run", str(game), "--replay", "festival"]) == 0
    assert seen["line"] == FIRST and seen["replay"] is None
    assert TitleScreen not in seen["stack"] and seen["titles"] == 0
    assert scripted_app.limiters[-1].frame < 590      # it quit on its own

    found: dict = {}

    def look(app):
        if app.error_mode and "message" not in found:
            found["message"] = app._fatal_message

    scripted_app.actions.clear()
    for frame in range(2, 60):
        scripted_app.at(frame, look)
    scripted_app.quit_frame = 60
    cli.main(["run", str(game), "--replay", "festivl"])
    assert 'There is no label named "festivl" to replay (--replay). ' \
           'Did you mean "festival"?' in found["message"]

    for extra, message in ((["--release"], "--replay is only available in dev runs"),
                           (["--start", "start"], cli.REPLAY_WITH_START),
                           (["--extras", "replays"], cli.REPLAY_WITH_START),
                           (["--try-stdin"], cli.REPLAY_WITH_START)):
        with pytest.raises(SystemExit) as refused:
            cli.main(["run", str(game), "--replay", "festival", *extra])
        assert refused.value.code == 2, extra
        assert capsys.readouterr().err.strip().splitlines()[-1].endswith(message), extra
    with pytest.raises(SystemExit) as refused:
        cli.main(["run", str(game), "--replay", "9 lives"])
    assert refused.value.code == 2
    assert capsys.readouterr().err.strip().splitlines()[-1].endswith(cli.REPLAY_NEEDS_LABEL)
