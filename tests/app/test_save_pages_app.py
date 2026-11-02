"""F11 step 9 in the real app (App S on the reduced Template S, I-14 A8): the Save and Load
pages over ``SaveService`` through ``SaveSlots``. Milestone: Esc → Save fills a slot with its
picture, date, and line; Load lists it and loads it.

ACs: AC-F11-21 (saving to a slot), 43 (delete), 45 (reading pages), 19 (decode only loadable
slots), 46 (initial page, "No saves yet."), 47 (quick-menu Save), 27 (a failed overwrite),
05 and 17 (the cell after TooLarge and after a refused picture), 20 (entries), and the App
rows of 44 (keys only). The page's own drawing and keys are ``tests/ui/test_save_page.py``.
Every run is an in-process ``launch()`` (``scripted_app``, unthreaded writer, 1280×720, dev);
``time.time`` is the AC's moment and ``localtime`` is UTC (06 §0.2 App S).
"""

import base64
import errno
import io
import os
import time
import types

import pygame
import pytest

import engine.app.saves as saves_app
from engine.core import safefile
from engine.persist import limits, saves
from engine.persist.saves import SlotId
from engine.render import thumbnail
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.save_page import SavePage
from tests.app.test_saves_service import (LINE6, at_line, file_of, launch, line_text, make_game,
                                          notices, play, save_log, textbox, unthreaded, wait)
from tests.fakes import jpegs
from tests.fakes.loop import post_key
from tests.persist import save_support as ss

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

DATE = "2026-11-01 21:04"
DESCRIPTION = "Hana: " + LINE6[:50] + "…"


@pytest.fixture
def utc_moment(monkeypatch):
    """06 §0.2: ``time.time`` is 1,793,567,040; ``localtime`` is UTC."""
    fake = types.SimpleNamespace(time=lambda: ss.SAVED_AT, localtime=time.gmtime,
                                 strftime=time.strftime, perf_counter=time.perf_counter)
    monkeypatch.setattr(saves_app, "time", fake)


def page_of(app) -> SavePage | None:
    menu = app.shell.game_menu()
    page = menu.page if menu is not None else None
    return page if isinstance(page, SavePage) else None


def open_page(app, entry_id: str):
    """Esc, then Down to ``entry_id`` in the sidebar, then Enter (keys only)."""
    post_key(pygame.K_ESCAPE)
    yield
    menu = app.shell.game_menu()
    for _ in range([e.id for e in menu.entries].index(entry_id)):
        post_key(pygame.K_DOWN)
        yield
    post_key(pygame.K_RETURN)
    yield


def to_sidebar_entry(app, entry_id: str):
    """From a page: Left to the sidebar, then Down/Up to ``entry_id``, then Enter."""
    menu = app.shell.game_menu()
    while menu.scope.focused not in menu.buttons:
        post_key(pygame.K_LEFT)
        yield
    ids = [e.id for e in menu.entries]
    here = menu.buttons.index(menu.scope.focused)
    there = ids.index(entry_id)
    for _ in range(abs(there - here)):
        post_key(pygame.K_DOWN if there > here else pygame.K_UP)
        yield
    post_key(pygame.K_RETURN)
    yield


def no_confirm(app) -> bool:
    return not any(isinstance(s, ConfirmScreen) for s in app.screens)


def confirm_yes(app):
    """Yes on the open question, then wait until it has faded out and acted."""
    post_key(pygame.K_LEFT)
    yield
    post_key(pygame.K_RETURN)
    yield
    yield from wait(lambda: no_confirm(app))
    yield


def confirm_no(app):
    post_key(pygame.K_ESCAPE)
    yield
    yield from wait(lambda: no_confirm(app))
    yield


def top_message(app) -> str | None:
    top = app.screens.top
    return top.message if isinstance(top, ConfirmScreen) else None


def px(app, x: int, y: int) -> tuple:
    return tuple(app.window.framebuffer().get_at((x, y)))[:3]


def close(a, b, tol: int = 8) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def write(game, data: bytes, slot: SlotId) -> None:
    ss.write_slot(game / "saves", data, slot)


# --- Milestone and AC-F11-21: Esc → Save fills a slot; Load lists and loads it ----------------

def test_milestone_save_to_a_slot_then_load_it(tmp_path, scripted_app, unthreaded, utc_moment):
    game = make_game(tmp_path)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        post_key(pygame.K_SPACE)                                     # P6f
        yield from wait(lambda: textbox(app).shown_count() == len(LINE6))
        yield
        out["scene"] = px(app, 640, 300)
        yield from open_page(app, "save")
        page = page_of(app)
        out["save_rows"] = list(page.row.labels())
        post_key(pygame.K_RIGHT)                                     # enter at cell 1
        yield
        post_key(pygame.K_RETURN)                                    # frame f: save
        yield
        out["confirm_after_empty"] = top_message(app)
        yield                                                         # frame f + 1 drawn
        view = page.views[0]
        out["view"] = (view.state, view.date, view.description, view.thumb is not None)
        out["probe"] = px(app, 544, 187)
        yield from wait(lambda: file_of(game, "page1-1.vnsave").is_file())
        out["focus"] = (app.shell.game_menu().page is page, page.grid.focus_cell,
                        app.shell.game_menu().scope.focused is page.grid)
        first = file_of(game, "page1-1.vnsave").read_bytes()
        post_key(pygame.K_RETURN)                                    # filled: asks
        yield
        out["overwrite"] = top_message(app)
        yield from confirm_no(app)
        out["after_no"] = (file_of(game, "page1-1.vnsave").read_bytes() == first,
                           app.shell.game_menu().scope.focused is page.grid,
                           page.grid.focus_cell)
        post_key(pygame.K_RETURN)
        yield
        yield from confirm_yes(app)
        yield from wait(lambda: file_of(game, "page1-1.vnsave").read_bytes() != first)
        yield
        out["seqs"] = (ss.meta(first)["seq"],
                       ss.meta(file_of(game, "page1-1.vnsave").read_bytes())["seq"])
        yield from to_sidebar_entry(app, "load")
        page = page_of(app)
        out["load_page"] = (page.mode, page.page, list(page.row.labels())[:3],
                            page.row.layout().arrows, len(page.row.layout().buttons))
        yield from wait(lambda: page.views[0].state == "filled")
        out["load_view"] = (page.views[0].label, page.views[0].date, page.views[0].description)
        post_key(pygame.K_RIGHT)
        yield
        post_key(pygame.K_RETURN)
        yield
        out["load_question"] = top_message(app)
        post_key(pygame.K_LEFT)
        yield
        post_key(pygame.K_RETURN)
        yield from wait(lambda: app.saves.loading_slot is not None)  # Yes, after its fade
        out["badge_frame"] = app.shell.game_menu() is not None       # not loaded yet
        yield
        out["badge"] = page.views[0].busy                            # drawn before the read
        yield from wait(lambda: app.shell.game_menu() is None)
        yield from wait(lambda: app.screens.top is textbox(app))     # after the load fade
        out["loaded"] = (line_text(app), app.screens.top is textbox(app))

    out = play(scripted_app, script, last=500)
    assert launch(game) == 0
    assert out["save_rows"] == [str(n) for n in range(1, 11)]       # never Auto or Quick
    assert out["confirm_after_empty"] is None
    assert out["view"] == ("filled", DATE, DESCRIPTION, True)
    assert close(out["probe"], out["scene"]), out                   # the scene's picture
    assert out["focus"] == (True, 0, True)
    assert out["overwrite"] == "Overwrite this save?"
    assert out["after_no"] == (True, True, 0)
    assert out["seqs"] == (1, 2)
    # With Noto Sans the 12-button row is 812 > 808 wide, so ◀ ▶ show (step 6's strict xfail
    # in test_save_layout, reported to the UI designer): 10 pages and the arrows.
    assert out["load_page"] == ("load", 1, ["Auto", "Quick", "1"], True, 12)
    assert out["load_view"] == ("Slot 1", DATE, DESCRIPTION)
    assert out["load_question"] == "Load this save? Unsaved progress will be lost."
    assert out["badge_frame"] is True and out["badge"] is True
    assert out["loaded"] == (LINE6, True)


# --- AC-F11-43: delete ------------------------------------------------------------------------

def test_ac43_delete_confirm_no_yes_failure_and_a_queued_save(tmp_path, scripted_app, unthreaded,
                                                              monkeypatch):
    game = make_game(tmp_path)
    for n in (1, 2):
        write(game, ss.make_save(seq=n), SlotId(1, n))
    write(game, ss.make_save(seq=3), SlotId("auto", 1))
    real_unlink = os.unlink
    deny = {"page1-2.vnsave"}

    def unlink(path, *args, **kwargs):
        if os.path.basename(path) in deny:
            raise PermissionError(errno.EACCES, "injected")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(safefile.os, "unlink", unlink)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        yield from open_page(app, "save")
        page = page_of(app)
        menu = app.shell.game_menu()
        post_key(pygame.K_RIGHT)
        yield
        out["default"] = page.grid.focus_cell                       # C1: the newest (Slot 2)
        post_key(pygame.K_HOME)
        yield
        yield from wait(lambda: page.views[0].state == "filled")
        post_key(pygame.K_DELETE)
        yield
        out["question"] = top_message(app)
        yield from confirm_no(app)
        out["after_no"] = (file_of(game, "page1-1.vnsave").is_file(),
                           menu.scope.focused is page.grid)
        post_key(pygame.K_BACKSPACE)
        yield
        yield from confirm_yes(app)
        out["after_yes"] = (file_of(game, "page1-1.vnsave").exists(), page.views[0].state,
                            menu.scope.focused is page.grid, page.grid.focus_cell)
        post_key(pygame.K_RIGHT)                                      # Slot 2: unlink denied
        yield
        post_key(pygame.K_DELETE)
        yield
        yield from confirm_yes(app)
        yield
        out["denied"] = (file_of(game, "page1-2.vnsave").is_file(), page.views[1].state,
                         notices(app)[-1] if notices(app) else None, page.grid.focus_cell)
        post_key(pygame.K_RIGHT)                                      # Slot 3: empty
        yield
        post_key(pygame.K_DELETE)
        yield
        out["empty_delete"] = top_message(app)
        post_key(pygame.K_RETURN)                                     # save into Slot 3 …
        yield
        app.saves.delete(SlotId(1, 3))                                # … and delete it queued
        yield
        yield
        yield
        out["queued"] = file_of(game, "page1-3.vnsave").exists()
        yield from to_sidebar_entry(app, "load")                      # Auto on the Load page
        page = page_of(app)
        out["load_on"] = page.page
        post_key(pygame.K_PAGEUP)
        post_key(pygame.K_PAGEUP)
        yield
        yield from wait(lambda: page.page == "auto" and page.views[0].state == "filled")
        post_key(pygame.K_RIGHT)
        yield
        post_key(pygame.K_DELETE)
        yield
        yield from confirm_yes(app)
        out["auto"] = file_of(game, "auto-1.vnsave").exists()

    out = play(scripted_app, script, last=600)
    assert launch(game) == 0
    assert out["default"] == 1
    assert out["question"] == "Delete this save?"
    assert out["after_no"] == (True, True)
    assert out["after_yes"] == (False, "empty", True, 0)
    assert out["denied"] == (True, "filled", "Couldn't delete this save.", 1)
    assert out["empty_delete"] is None
    assert out["queued"] is False
    assert out["auto"] is False
    w83 = [m for m in save_log(game) if m.startswith("couldn't delete")]
    assert w83 == ["couldn't delete Slot 2: no permission"]
    assert sorted(p.name for p in (game / "saves").iterdir()) == ["page1-2.vnsave"]


# --- AC-F11-45 and 19: reading pages, decoding only what can load -----------------------------

def _hostile_page(game) -> None:
    folder = game / "saves"
    big = folder / SlotId(2, 1).file_name()
    with open(big, "wb") as f:
        f.truncate(limits.SAVE_FILE_MAX + 1)
    write(game, ss.with_meta(ss.make_save(seq=5), state=limits.STATE_MAX_BYTES), SlotId(2, 2))
    repro = ss.with_line2(ss.make_save(seq=6), b'{"jpeg":"' + base64.b64encode(
        jpegs.svg_confusion()) + b'"}\n')
    write(game, repro, SlotId(2, 3))
    write(game, b"[" * 8000 + b"\n", SlotId(2, 4))


def test_ac45_ac19_reading_pages_and_lazy_decodes(tmp_path, scripted_app, unthreaded,
                                                  monkeypatch):
    game = make_game(tmp_path)
    valid = jpegs.engine_jpeg("flat")
    # Page 1: OK (valid picture), OK (bad picture), DAMAGED, NEWER, OTHER_GAME, empty; each
    # of the not-OK ones with a valid picture too.
    write(game, ss.make_save(seq=10, jpeg=valid), SlotId(1, 1))
    write(game, ss.with_line2(ss.make_save(seq=11), b'{"jpeg":"AAAA"}\n'), SlotId(1, 2))
    write(game, ss.with_meta(ss.make_save(seq=12, jpeg=valid), seq="x"), SlotId(1, 3))
    write(game, ss.with_meta(ss.make_save(seq=13, jpeg=valid), vnsave=2), SlotId(1, 4))
    write(game, ss.make_save(seq=14, jpeg=valid, game="other-game"), SlotId(1, 5))
    _hostile_page(game)
    reads = ss.ReadSpy().install(monkeypatch)
    b64 = ss.DecodeSpy().install(monkeypatch)
    decodes: list = []
    loads: list = []
    real_decode, real_load = saves_app.decode_jpeg, pygame.image.load

    def decode(data):
        decodes.append(len(data))
        return real_decode(data)

    def image_load(source, *args):
        loads.append(type(source))
        return real_load(source, *args)

    monkeypatch.setattr(saves_app, "decode_jpeg", decode)
    monkeypatch.setattr(thumbnail.pygame.image, "load", image_load)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        yield from open_page(app, "load")
        page = page_of(app)
        out["page"] = page.page
        out["first"] = [v.state for v in page.views]
        slots = app.saves.slots
        counts = []
        for _ in range(30):
            counts.append(slots.reads)
            yield
            if all(v.state != "loading" for v in page.views):
                break
        out["counts"] = counts
        out["states"] = [v.state for v in page.views]
        out["pictures"] = [v.thumb is not None for v in page.views]
        out["b64"], out["decodes"] = len(b64), len(decodes)
        reads.clear()
        post_key(pygame.K_PAGEDOWN)                                   # page 2: hostile
        yield
        for _ in range(30):
            yield
            if all(v.state != "loading" for v in page.views):
                break
        out["hostile"] = [(v.state, v.thumb is not None) for v in page.views]
        out["reads"] = list(reads)
        out["decodes_after"] = len(decodes)
        post_key(pygame.K_RIGHT)
        yield
        out["takes_input"] = app.shell.game_menu().scope.focused is page.grid

    out = play(scripted_app, script, last=300)
    assert launch(game) == 0
    assert out["page"] == 1
    assert out["first"].count("loading") >= 5                        # unread: "Loading…"
    steps = [b - a for a, b in zip(out["counts"], out["counts"][1:])]
    assert steps and set(steps) <= {0, 1} and len(out["counts"]) <= 30   # one head per update
    assert out["states"] == ["filled", "filled", "damaged", "newer", "other_game", "empty"]
    assert out["pictures"] == [True, False, False, False, False, False]
    assert out["b64"] == 2 and out["decodes"] == 1                    # OK slots only
    assert set(loads) == {io.BytesIO}
    assert out["hostile"] == [("damaged", False), ("damaged", False), ("filled", False),
                              ("damaged", False), ("empty", False), ("empty", False)]
    assert out["reads"] and max(out["reads"]) <= limits.HEAD_MAX
    assert out["decodes_after"] == 1                                  # nothing refused decodes
    assert out["takes_input"]


def test_ac19_sixty_saves_decode_six_and_a_wrong_size_is_no_picture(tmp_path, scripted_app,
                                                                   unthreaded, monkeypatch):
    game = make_game(tmp_path)
    picture = ss.make_save(seq=1, jpeg=jpegs.engine_jpeg("flat"))
    for page in range(1, 11):
        for n in range(1, 7):
            write(game, ss.with_meta(picture, seq=page * 10 + n), SlotId(page, n))
    calls: list = []
    real = saves_app.decode_jpeg

    def decode(data):
        calls.append(1)
        return real(data)

    monkeypatch.setattr(saves_app, "decode_jpeg", decode)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        yield from open_page(app, "load")
        page = page_of(app)
        out["page"] = page.page                                       # page 10 holds seq 106
        yield from wait(lambda: all(v.state == "filled" for v in page.views))
        for _ in range(10):
            yield
        out["decodes"] = len(calls)
        wrong = pygame.Surface((321, 180))
        monkeypatch.setattr(thumbnail.pygame.image, "load", lambda *a: wrong)
        post_key(pygame.K_PAGEUP)
        yield
        yield from wait(lambda: all(v.state == "filled" for v in page.views))
        out["wrong"] = [v.thumb is None for v in page.views]

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    assert out["page"] == 10 and out["decodes"] == 6
    assert out["wrong"] == [True] * 6                                 # "No picture"


# --- AC-F11-46: initial page and "No saves yet." -------------------------------------------------

def test_ac46_no_saves_from_the_title_and_in_game(tmp_path, scripted_app, unthreaded):
    game = make_game(tmp_path)
    config = (game / "config.toml").read_text(encoding="utf-8")
    (game / "config.toml").write_text(config.replace("enabled = false", "enabled = true"),
                                      encoding="utf-8")

    def script(app, out):
        yield from wait(lambda: app.shell is not None and app.shell.mode.name == "TITLE"
                        and type(app.screens.top).__name__ == "TitleScreen")
        for _ in range(40):
            yield
        title = app.screens.top
        out["title"] = [b.label() for b in title.buttons]
        out["load_enabled"] = title.buttons[1].enabled()
        post_key(pygame.K_DOWN)
        yield
        post_key(pygame.K_DOWN)
        yield
        post_key(pygame.K_RETURN)
        yield
        screen = app.screens.top
        page = screen.page
        out["from_title"] = (isinstance(screen, GameMenuScreen) and screen.from_title,
                             page._shape, screen.scope.focused is page.row)
        post_key(pygame.K_PAGEDOWN)
        yield
        out["still"] = page._shape[1]
        post_key(pygame.K_ESCAPE)
        yield

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    assert out["title"] == ["New Game", "Load", "Settings", "Quit"] and out["load_enabled"]
    assert out["from_title"] == (True, (None, True), True)       # message; row kept; focused
    assert out["still"] is True


def test_title_load_loads_with_no_question(tmp_path, scripted_app, unthreaded):
    """§7.6 step 1: from the title the choose loads at once (no confirm), the badge frame
    first; the game shows the saved line (C8: the menus close, mode GAME)."""
    game = make_game(tmp_path)
    config = (game / "config.toml").read_text(encoding="utf-8")
    (game / "config.toml").write_text(config.replace("enabled = false", "enabled = true"),
                                      encoding="utf-8")
    write(game, ss.make_save(seq=3), SlotId(1, 2))

    def script(app, out):
        yield from wait(lambda: app.shell is not None
                        and type(app.screens.top).__name__ == "TitleScreen")
        for _ in range(40):
            yield
        post_key(pygame.K_DOWN)
        yield
        post_key(pygame.K_DOWN)
        yield
        post_key(pygame.K_RETURN)
        yield
        page = page_of(app)
        out["focus"] = (page.page, page.grid.focus_cell,
                        app.screens.top.scope.focused is page.grid)
        yield from wait(lambda: page.views[1].state == "filled")
        post_key(pygame.K_RETURN)
        yield
        out["question"] = top_message(app)
        yield from wait(lambda: app.shell.mode.name == "GAME")
        yield from wait(lambda: line_text(app) is not None)
        out["line"] = line_text(app)
        out["stack"] = [type(s).__name__ for s in app.screens]

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    assert out["focus"] == (1, 1, True)                               # the newest save's cell
    assert out["question"] is None
    assert out["line"] == "The wind picks up."
    assert "GameMenuScreen" not in out["stack"] and "TitleScreen" not in out["stack"]


def test_ac46_initial_pages_and_the_remembered_page(tmp_path, scripted_app, unthreaded):
    game = make_game(tmp_path)
    write(game, ss.make_save(seq=3), SlotId(2, 1))
    write(game, ss.make_save(seq=9), SlotId("quick", 4))
    write(game, ss.make_save(seq=5), SlotId("auto", 2))
    write(game, b"junk\n", SlotId(3, 1))

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        yield from open_page(app, "load")
        page = page_of(app)
        out["load_first"] = page.page
        out["default"] = page.grid.focus_cell                          # quick-4's cell
        for _ in range(3):
            post_key(pygame.K_PAGEDOWN)
            yield
        out["viewed"] = page.page
        yield from to_sidebar_entry(app, "save")
        out["save_first"] = page_of(app).page
        yield from to_sidebar_entry(app, "load")
        out["load_again"] = page_of(app).page
        yield from wait(lambda: page_of(app).views[0].state != "loading")
        out["damaged_shown"] = page_of(app).views[0].state

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    assert out["load_first"] == "quick" and out["default"] == 3
    assert out["viewed"] == 3 and out["save_first"] == 1
    assert out["load_again"] == 3 and out["damaged_shown"] == "damaged"


# --- AC-F11-47 and 20: quick-menu Save, entries, disabled looks ----------------------------------

def test_ac47_ac20_quick_menu_save_and_the_entries(tmp_path, scripted_app, unthreaded):
    game = make_game(tmp_path)

    def script(app, out):
        yield from wait(lambda: app.shell is not None and app.saves is not None)
        out["before"] = (app.shell.menus.entry("game", "save").enabled(),
                         app.shell.menus.entry("quick", "q_save").enabled(),
                         app.shell.menus.entry("game", "load").enabled())
        yield from wait(lambda: at_line(app, LINE6))
        shell = app.shell
        out["shown"] = {m: [e.id for e in shell.menus.shown(m)] for m in ("game", "quick")}
        out["title"] = [e.id for e in shell.menus.shown("title")]
        out["enabled"] = shell.menus.entry("game", "save").enabled()
        found = shell.quick_menu.shown()
        item = next(i for i, e in zip(found.layout.items, found.entries) if e.id == "save")
        x, y = (round(v) for v in item.box.center)
        pygame.event.post(pygame.event.Event(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0),
                                             buttons=(0, 0, 0)))
        yield
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x, y)))
        yield
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(x, y)))
        yield
        page = page_of(app)
        out["opened"] = (page is not None and page.mode, page is not None and page.from_quick)
        for _ in range(12):
            yield
        post_key(pygame.K_ESCAPE)
        yield
        yield from wait(lambda: shell.game_menu() is None)
        out["back"] = app.screens.top is textbox(app)

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    assert out["before"] == (False, False, True)                      # no checkpoint yet
    assert {"save", "load"} <= set(out["shown"]["game"])
    assert {"save", "q_save", "q_load"} <= set(out["shown"]["quick"])
    assert out["title"] == ["new_game", "load", "settings", "quit"]
    assert out["enabled"] is True
    assert out["opened"] == ("save", True)
    assert out["back"] is True
    log = (game / "logs" / "latest.log").read_text(encoding="utf-8")
    assert "entries has" not in log and "entries is empty" not in log    # no W66


# --- AC-F11-27, 05, 17: the cell after a failure, TooLarge, and a refused picture ---------------

def test_ac27_failed_overwrite_shows_the_old_save(tmp_path, scripted_app, unthreaded, monkeypatch):
    game = make_game(tmp_path)
    write(game, ss.make_save(seq=4, description="Old save."), SlotId(1, 1))
    before = file_of(game, "page1-1.vnsave").read_bytes()
    real = safefile.write_atomic

    def write_atomic(target, pieces, **kw):
        if target.name == "page1-1.vnsave":
            raise OSError(errno.ENOSPC, "injected")
        return real(target, pieces, **kw)

    monkeypatch.setattr(safefile, "write_atomic", write_atomic)

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        yield from open_page(app, "save")
        page = page_of(app)
        post_key(pygame.K_RIGHT)
        yield
        yield from wait(lambda: page.views[0].state == "filled")
        post_key(pygame.K_RETURN)
        yield
        yield from confirm_yes(app)
        yield from wait(lambda: "Couldn't save: the disk is full." in notices(app))
        yield
        out["after"] = (page.views[0].description, page.grid.focus_cell,
                        app.shell.game_menu().scope.focused is page.grid)

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    assert out["after"] == ("Old save.", 0, True)
    assert file_of(game, "page1-1.vnsave").read_bytes() == before
    assert [p.name for p in (game / "saves").iterdir()] == ["page1-1.vnsave"]


def test_ac05_too_large_and_ac17_no_picture_cells(tmp_path, scripted_app, unthreaded,
                                                 monkeypatch):
    game = make_game(tmp_path)
    write(game, ss.make_save(seq=4, description="Old save."), SlotId(1, 1))

    def script(app, out):
        yield from wait(lambda: at_line(app, LINE6))
        yield from open_page(app, "save")
        page = page_of(app)
        post_key(pygame.K_RIGHT)
        yield
        yield from wait(lambda: page.views[0].state == "filled")
        monkeypatch.setattr(saves.limits, "STATE_MAX_BYTES", 64)      # every state too big
        post_key(pygame.K_RETURN)
        yield
        yield from confirm_yes(app)
        yield from wait(lambda: "This save is too large." in notices(app))
        yield
        out["too_large"] = page.views[0].description
        monkeypatch.setattr(saves.limits, "STATE_MAX_BYTES", 25_165_824)
        monkeypatch.setattr(thumbnail, "check_engine_jpeg", lambda data, size: False)
        post_key(pygame.K_RIGHT)                                       # Slot 2: no picture
        yield
        post_key(pygame.K_RETURN)
        yield
        yield from wait(lambda: file_of(game, "page1-2.vnsave").is_file())
        yield from wait(lambda: page.views[1].thumb is None)
        out["line2"] = ss.lines(file_of(game, "page1-2.vnsave").read_bytes())[1]
        out["state"] = page.views[1].state

    out = play(scripted_app, script, last=200)
    assert launch(game) == 0
    assert out["too_large"] == "Old save."
    assert out["line2"] == b'{"jpeg":null}\n' and out["state"] == "filled"
    assert any("too large" in m for m in save_log(game))
