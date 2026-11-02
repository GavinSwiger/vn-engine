"""F11 step 12 in the real app: the example game uses saves (AC-F11-66's window half), and
the App S rows that waited for Template S in full (I-14 A8).

Every run is an in-process ``launch()`` (``scripted_app``: fake clock at 1/60 s, hidden
window 1280×720, dev, unthreaded writer) scripted frame by frame (``play``). The example
game runs from a copy of ``game/`` without its run folders, with no ``[saves]`` setting of
its own; Template S is ``tests/persist/template_s.py``'s.
"""

import shutil
from pathlib import Path

import pygame
import pytest

from engine.core.config_schema import SavesConfig
from engine.persist import saves
from engine.persist.saves import SlotStatus
from engine.render.thumbnail import decode_jpeg
from engine.render.typewriter import TypeState
from engine.ui.menus import EntryContext
from engine.ui.nav import InputKind
from tests.app.test_save_pages_app import confirm_yes, open_page, page_of, to_sidebar_entry, \
    top_message
from tests.app.test_saves_service import (file_of, launch, line_text, notices, play, textbox,
                                          unthreaded, wait)
from tests.app.test_story_load_screen import records
from tests.fakes.loop import post_key
from tests.persist import template_s as ts

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

REPO = Path(__file__).resolve().parents[2]


def reading(app) -> str | None:
    """The line the textbox shows when it is the top screen, else None."""
    box = textbox(app)
    return line_text(app) if box is not None and app.screens.top is box else None


def advance_until(app, done):
    """Once the shown line has typed, Space every 30 frames until ``done()`` (a press
    during a transition only finishes it)."""
    box = textbox(app)
    yield from wait(lambda: done() or box.typer is None
                    or box.typer.state is TypeState.COMPLETE)
    for frame in range(10_000):
        if done():
            return
        if frame % 30 == 0:
            post_key(pygame.K_SPACE)
        yield


def next_line(app):
    here = reading(app)
    yield from advance_until(app, lambda: reading(app) not in (None, here))


def quick_entry(app, entry_id: str) -> None:
    """Q.Save or Q.Load, as the quick menu's button does when chosen by keys."""
    entry = app.shell.menus.entry("quick", entry_id)
    assert entry is not None and entry.visible() and entry.enabled()
    entry.action(EntryContext(app.shell, InputKind.KEYS))


def read_full(game: Path, name: str, game_id: str | None) -> saves.FullRead:
    return saves.parse_full((game / "saves" / name).read_bytes(), game_id=game_id)


# --- AC-F11-66: the example game's Save, Load, Q.Save, and Q.Load ------------------------------

def test_ac66_the_example_game_saves_and_loads(tmp_path, scripted_app, unthreaded, user_roots):
    game = Path(shutil.copytree(REPO / "game", tmp_path / "game",
                                ignore=shutil.ignore_patterns("logs", "saves", "persistent",
                                                              "settings", "characters")))

    def script(app, out):
        out["saves_config"] = app.config.saves
        n = 0
        while reading(app) is None:                    # Space: New Game, then past the card
            n += 1
            if n % 6 == 0:
                post_key(pygame.K_SPACE)
            yield
        first = out["first"] = reading(app)
        quick_entry(app, "q_save")                     # Q.Save
        yield from wait(lambda: file_of(game, "quick-1.vnsave").is_file())
        out["quick_notice"] = list(notices(app))
        yield from next_line(app)
        second = out["second"] = reading(app)
        yield from open_page(app, "save")              # Save → Slot 1
        post_key(pygame.K_RIGHT)
        yield
        post_key(pygame.K_RETURN)
        yield from wait(lambda: file_of(game, "page1-1.vnsave").is_file())
        yield from to_sidebar_entry(app, "return")
        yield from wait(lambda: reading(app) == second)
        yield from next_line(app)
        out["third"] = reading(app)
        quick_entry(app, "q_load")                     # Q.Load → Yes
        yield
        out["quick_question"] = top_message(app)
        yield from confirm_yes(app)
        yield from wait(lambda: reading(app) == first)
        out["quick_loaded"] = app.story.checkpoint().position
        yield from open_page(app, "load")              # Load → Slot 1 → Yes
        page = page_of(app)
        out["load_page"] = page.page
        yield from wait(lambda: page.views[0].state == "filled")
        post_key(pygame.K_RIGHT)
        yield
        post_key(pygame.K_RETURN)
        yield
        out["load_question"] = top_message(app)
        yield from confirm_yes(app)
        yield from wait(lambda: reading(app) == second)
        out["slot_loaded"] = app.story.checkpoint().position

    out = play(scripted_app, script, last=2400)
    assert launch(game) == 0
    assert out.get("done"), " ".join(sorted(out))
    assert out["saves_config"] == SavesConfig()            # no [saves] setting of its own
    assert out["first"] == "The festival comes once a year, on the night the river runs slowest."
    assert "Quick saved." in out["quick_notice"]
    assert out["second"] != out["third"]
    assert out["quick_question"] == out["load_question"] == (
        "Load this save? Unsaved progress will be lost.")
    quick, slot = read_full(game, "quick-1.vnsave", None), read_full(game, "page1-1.vnsave", None)
    assert quick.status is slot.status is SlotStatus.OK
    assert out["quick_loaded"] == quick.state.position
    assert out["load_page"] == 1 and out["slot_loaded"] == slot.state.position
    assert quick.meta.description == slot.meta.description == "Prologue"    # F18's chapter
    problems = [r for r in records(game / "logs" / "latest.log") if r[0] in ("WARNING", "ERROR")]
    assert problems == []


# --- I-14 A8: the App S rows that waited for Template S in full ----------------------------------

def pick_first(app):
    """Past the choices' guard: Space focuses the first choice, Space picks it."""
    yield from wait(lambda: app.screens.top.past_guard)
    post_key(pygame.K_SPACE)
    yield
    post_key(pygame.K_SPACE)
    yield


def test_a8_template_s_menu_fade_and_music_rows(tmp_path, scripted_app, unthreaded):
    """On Template S in full: F5 at P-menu saves the menu (AC-F11-23); that save loads as the
    same menu, and "Help Hana with the posters" then sets ``trust`` 1 and shows ``Thanks!``
    (AC-F11-33); F5 at P-fade stores the frame as drawn, mid-fade, and the checkpoint of line
    13 (AC-F11-16, 22); after each load the saved ``bgm/theme.ogg`` plays (F08 keeps the
    same track playing rather than restarting it)."""
    from engine.ui.builtin.choice_screen import ChoiceScreen

    game = ts.make_game(tmp_path / "game", title=False)

    def at_menu(app) -> bool:
        return isinstance(app.screens.top, ChoiceScreen)

    def music_starts() -> int:
        return len(scripted_app.mixers[-1].actions("music_start"))

    def script(app, out):
        yield from wait(lambda: reading(app) == ts.LINE6)
        yield from advance_until(app, lambda: reading(app) == ts.LINE8)
        yield from advance_until(app, lambda: at_menu(app))
        out["menu_cp"] = app.story.checkpoint()
        post_key(pygame.K_F5)                                       # P-menu
        yield from wait(lambda: file_of(game, "quick-1.vnsave").is_file())
        out["menu_top"] = at_menu(app)
        yield from pick_first(app)
        yield from wait(lambda: reading(app) == "Thanks!")
        starts = music_starts()
        post_key(pygame.K_F9)                                       # the menu save
        yield
        yield from confirm_yes(app)
        yield from wait(lambda: at_menu(app))
        out["loaded_menu"] = (app.story.checkpoint().to_json(), line_text(app),
                              len(app.screens.top.cmd.choices))
        out["music_1"] = (music_starts() - starts, app.audio.music.current.file,
                          app.audio.music.current.story)
        yield from pick_first(app)
        yield from wait(lambda: reading(app) == "Thanks!")
        out["p13"] = app.story.checkpoint()
        out["trust"] = out["p13"].variables["trust"]
        yield from advance_until(app, lambda: app.story.interp.waiting_for is not None)
        for _ in range(30):                             # the fade, 0.5 s of 2.0 s
            yield
        out["fade_px"] = tuple(app.window.framebuffer().get_at((640, 360)))[:3]
        post_key(pygame.K_F5)                                       # P-fade
        yield from wait(lambda: file_of(game, "quick-2.vnsave").is_file())
        yield from advance_until(app, lambda: reading(app) == ts.LINE18)
        starts = music_starts()
        post_key(pygame.K_F9)                                       # the newest: P-fade
        yield
        yield from confirm_yes(app)
        yield from wait(lambda: reading(app) == "Thanks!")
        out["music_2"] = (music_starts() - starts, app.audio.music.current.file,
                          app.audio.music.current.story)
        out["after_fade_load"] = app.story.checkpoint()

    out = play(scripted_app, script, last=3000)
    assert launch(game) == 0
    assert out.get("done"), " ".join(sorted(out))
    menu = saves.read_slot_full(game / "saves", saves.SlotId("quick", 1), game_id=ts.ss.GAME_ID)
    assert menu.status is SlotStatus.OK and menu.state == out["menu_cp"]
    assert menu.state.choices.waiting is not None and out["menu_top"]
    assert out["loaded_menu"] == (out["menu_cp"].to_json(), "Where should we go?", 2)
    assert out["trust"] == 1
    fade = saves.read_slot_full(game / "saves", saves.SlotId("quick", 2), game_id=ts.ss.GAME_ID)
    assert fade.status is SlotStatus.OK and fade.state == out["p13"]
    head = saves.read_slot_head(game / "saves", saves.SlotId("quick", 2), game_id=ts.ss.GAME_ID,
                                thumb=True)
    picture = decode_jpeg(head.jpeg)
    shown = tuple(picture.get_at((160, 90)))[:3]
    assert all(abs(a - b) <= 24 for a, b in zip(shown, out["fade_px"])), (shown, out)
    assert max(shown) < 180                                     # dimmed: the fade, not the room
    assert out["after_fade_load"].to_json() == out["p13"].to_json()
    # The saved music plays on: F08 keeps the same track playing through a load (§7.6).
    assert out["music_1"] == out["music_2"] == (0, "bgm/theme.ogg", True)
