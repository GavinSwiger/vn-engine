"""F11 step 11 in the real app (App S on Template S in full: F04, F07, F08, F09 are built):
loading in game and from the title (AC-F11-31, 32), a refused load changes nothing and W82
(AC-F11-34, 58), the nearest point (AC-F11-35), patched stories (AC-F11-36), the golden
saves in the app (AC-F11-37), the load fade (AC-F11-38), G3's loading indicator (I-14 A3),
and the seams (AC-F11-61, I-4's ``delete_all``, AC-F11-13's ``delete_all`` rows).

Every run is an in-process ``launch()`` (``scripted_app``: fake clock at 1/60 s, hidden
window 1280×720, dev, unthreaded writer) scripted frame by frame (``play``). Saves to load
are written by this build from headless Template S checkpoints (``template_s``), so their
sids are the running story's. Probe D is (1000, 100), ``bg room`` (200, 200, 200).
"""

import dataclasses
import json
import shutil

import pygame
import pytest

from engine.app.saves import NO_NEARBY_POINT, position_reason, w82_text
from engine.persist import saves
from engine.persist.saves import SlotId, SlotStatus
from engine.runtime.interpreter import RestoreResult
from engine.ui.builtin import save_page as save_page_mod
from engine.ui.builtin.load_fade import LoadFadeScreen
from engine.ui.nav import InputKind
from tests.app.test_save_pages_app import (confirm_no, confirm_yes, no_confirm, open_page,
                                           page_of, px, top_message)
from tests.app.test_saves_service import (at_line, file_of, launch, line_text, notices, play,
                                          save_log, textbox, unthreaded, wait)
from tests.app.test_story_load_screen import records
from tests.fakes.loop import post_key
from tests.persist import save_support as ss
from tests.persist import template_s as ts

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

D = (1000, 100)
BLACK = (0, 0, 0)
SLOT1 = SlotId(1, 1)
NOFIT = "This save no longer fits the story and can't be loaded."
FAILED = "This save couldn't be loaded."
DAMAGED = "This save is damaged and can't be loaded."
NEWER = "Made by a newer version of the game."
FAST = "\n[theme.ui]\nfade_ms = 0\n\n[theme.save]\nload_fade_ms = 0\n"   # fewer frames
NEAREST = "The story has changed since this save. Continue from the nearest point?"


@pytest.fixture(scope="module")
def states(tmp_path_factory) -> dict:
    """Template S's checkpoints by line (seed 42, choice 1), and a picture's JPEG."""
    program = ts.load_program(tmp_path_factory.mktemp("s") / "game")
    return {"cp": ts.checkpoints(program), "jpeg": ts.thumbnail_jpeg()}


def save_of(states, line: int, seq: int = 1, **variables) -> bytes:
    state = states["cp"][line]
    if variables:
        state = dataclasses.replace(state, variables={**state.variables, **variables})
    return ts.save_bytes(state, seq, states["jpeg"])


def put(game, data: bytes, slot: SlotId = SLOT1) -> None:
    ss.write_slot(game / "saves", data, slot)


def installed(app):
    """Wait for the story load: ``app.saves`` and ``app.shell`` exist from then on."""
    yield from wait(lambda: getattr(app, "saves", None) is not None)


def fade_screen(app) -> LoadFadeScreen | None:
    top = app.screens.top
    return top if isinstance(top, LoadFadeScreen) else None


def choose_slot(app, mode: str = "load"):
    """The page is open with the grid focused on cell 1 after Right: Enter."""
    post_key(pygame.K_RIGHT)
    yield
    post_key(pygame.K_RETURN)
    yield


# --- AC-F11-31, 38: loading in game, the badge, no closing fade, the load fade ---------------

def test_ac31_ac38_load_in_game_then_the_fade(tmp_path, scripted_app, unthreaded, states):
    game = ts.make_game(tmp_path / "game", title=False)
    put(game, save_of(states, 8))
    before = (file_of(game, SLOT1.file_name()).read_bytes(),
              file_of(game, SLOT1.file_name()).stat().st_mtime_ns)
    calls = []

    def script(app, out):
        yield from installed(app)
        app.saves.add_load_listener(lambda: calls.append(out["frame"]))
        yield from wait(lambda: at_line(app, ts.LINE6))
        yield from open_page(app, "load")
        page = page_of(app)
        yield from wait(lambda: page.views[0].state == "filled")
        yield from choose_slot(app)
        out["question"] = top_message(app)
        yield from confirm_yes(app)                            # f + 1 drawn: the badge
        yield from wait(lambda: app.saves.loading_slot is None)
        out["menus"] = app.shell.game_menu() is None and no_confirm(app)
        probes = []
        while fade_screen(app) is not None or not probes:
            probes.append(px(app, *D))
            yield
        out["probes"] = probes
        out["top"] = app.screens.top is textbox(app)
        out["line"] = line_text(app)
        out["cp"] = app.story.checkpoint().to_json()
        out["timer"] = app.saves.timer

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["question"] == "Load this save? Unsaved progress will be lost."
    assert out["menus"]
    probes = out["probes"]
    assert probes[0] == BLACK                                  # menus gone, no fade: black
    first = probes.index(next(p for p in probes if p != BLACK))
    assert all(p == BLACK for p in probes[:first]) and first <= 3
    k = probes.index(min(probes[first:], key=lambda p: abs(p[0] - 100)))
    assert abs(probes[k][0] - 100) <= 3 and 8 <= k - first + 1 <= 10
    assert 17 <= len(probes) - first + 1 <= 19                 # 300 ms: 18 frames, then gone
    assert out["top"] and out["line"] == ts.LINE8
    assert out["cp"] == states["cp"][8].to_json()
    assert out["timer"] < 0.1 and len(calls) == 1
    after = file_of(game, SLOT1.file_name())
    assert (after.read_bytes(), after.stat().st_mtime_ns) == before


@pytest.mark.parametrize("config", ["\n[theme.save]\nload_fade_ms = 0\n", ""],
                         ids=["fade_0", "reduce_motion"])
def test_ac38_no_fade_and_a_key_or_notice_during_one(tmp_path, scripted_app, unthreaded,
                                                     states, config):
    """With ``load_fade_ms = 0`` or reduce motion the first frame after F9 is the full scene.
    (The key and notice rows run on the default fade in the reduce-motion run first.)"""
    game = ts.make_game(tmp_path / "game", "\n[saves]\nconfirm_quick_load = false\n" + config,
                        title=False)
    put(game, save_of(states, 8), SlotId("quick", 1))
    put(game, save_of(states, 8, seq=2), SlotId("quick", 2))

    def script(app, out):
        yield from wait(lambda: at_line(app, ts.LINE6))
        if not config:
            post_key(pygame.K_F9)                              # the default 300 ms fade
            yield from wait(lambda: fade_screen(app) is not None)
            for _ in range(5):
                yield
            app.shell.notify("Hi")
            yield
            out["held"] = notices(app)
            post_key(pygame.K_SPACE)                           # frame 5: ends it
            yield
            yield
            yield
            # Not delivered: Space on the (restored, complete) line would go on to the menu.
            out["after_key"] = (fade_screen(app) is None, line_text(app),
                                app.screens.top is textbox(app), notices(app))
            app.shell.clear_notices()
            app.shell.reduce_motion = True
        post_key(pygame.K_F9)
        yield
        yield
        out["first"] = (fade_screen(app) is None, px(app, *D), line_text(app))

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["first"] == (True, ts.ROOM, ts.LINE8)
    if not config:
        assert out["held"] == []
        assert out["after_key"] == (True, ts.LINE8, True, ["Hi"])


# --- AC-F11-34, 58 (W82): a refused load changes nothing --------------------------------------

def _rows(states) -> list:
    p8 = save_of(states, 8)
    obj = json.loads(ss.lines(p8)[2])
    gone_obj = json.loads(ss.lines(p8)[2])
    gone_obj["position"] = {"sid": "start/000000000000", "at": ["start", [99]]}
    lengths = p8[:-20]
    return [
        ("missing", None, FAILED, "the file is gone"),
        ("cut", lengths, DAMAGED, "line lengths"),
        ("rejected", ss.with_line3(p8, ss.state_json_line({**obj, "dice": "x"})), DAMAGED,
         "story state ("),
        ("format", ss.with_line3(p8, ss.state_json_line({**obj, "format": 2})), NEWER,
         "made with state format 2"),
        ("scheme", ss.with_line3(p8, ss.state_json_line({**obj, "identity_scheme": 2})), NOFIT,
         "made with identity scheme 2; this story uses 1"),
        ("gone", ss.with_line3(p8, ss.state_json_line(gone_obj)), NOFIT,
         "the saved line in label start (statement 99) is gone and no nearby point was found"),
        ("other", ss.with_meta(p8, game="another-game"), "This save is from a different game.",
         "it was made by a different game"),
        ("default", p8, FAILED, "the story couldn't set this save up (E"),
    ]


def test_ac34_ac58_refused_loads_change_nothing(tmp_path, scripted_app, unthreaded, states):
    """V-default here is ``default trust = 1`` plus ``default ratio = 10 // trust``: a new
    game is fine, and restoring a P8 save (``trust`` 0, no ``ratio``) fails that default."""
    script_text = ts.script_text().replace(
        "default trust = 0\n", "default trust = 1\ndefault ratio = 10 // trust\n")
    game = ts.make_game(tmp_path / "game", title=False, script=script_text)
    rows = _rows(states)
    listened = []

    def script(app, out):
        yield from installed(app)
        app.saves.add_load_listener(lambda: listened.append(1))
        yield from wait(lambda: at_line(app, ts.LINE6))
        seen = []
        for name, data, _, _ in rows:
            path = file_of(game, SLOT1.file_name())
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
            screens, cp = list(app.screens), app.story.checkpoint()
            app.saves.release = name == "other"                # W82: none in release runs
            app.saves._load(SLOT1, "game")
            yield
            seen.append((notices(app), list(app.screens) == screens,
                         app.story.checkpoint() is cp, line_text(app)))
            app.shell.clear_notices()
        app.saves.release = False
        out["seen"] = seen

    out = play(scripted_app, script)
    assert launch(game) == 0
    w82 = [m for m in save_log(game) if m.startswith("couldn't load")]
    expected_w82 = [r for r in rows if r[0] != "other"]
    assert len(w82) == len(expected_w82)
    for (name, _, notice, reason), seen, in zip(rows, out["seen"]):
        assert seen == ([notice], True, True, ts.LINE6), name
    for (name, _, _, reason), message in zip(expected_w82, w82):
        assert message.startswith("couldn't load Slot 1: " + reason), (name, message)
    errors = [r for r in records(game / "logs" / "latest.log") if r[0] == "ERROR"]
    assert len(errors) == 1 and "script/main.vns, line 3" in errors[0][2], errors
    assert listened == []


# --- AC-F11-35: the nearest point -------------------------------------------------------------

def test_ac35_nearest_point_no_then_yes(tmp_path, scripted_app, unthreaded, states):
    rewritten = ts.script_text().replace('"The wind picks up."', '"The wind howls."')
    game = ts.make_game(tmp_path / "game", FAST, title=False, script=rewritten)
    put(game, save_of(states, 8, seq=2))                      # Newest: Load opens on page 1
    put(game, save_of(states, 8), SlotId("quick", 1))

    def script(app, out):
        yield from wait(lambda: at_line(app, ts.LINE6))
        cp = app.story.checkpoint()
        yield from open_page(app, "load")
        page = page_of(app)
        yield from wait(lambda: page.views[0].state == "filled")
        yield from choose_slot(app)
        yield from confirm_yes(app)                            # confirm_load
        yield from wait(lambda: top_message(app) is not None)
        out["page_question"] = top_message(app)
        yield from confirm_no(app)
        out["after_no"] = (app.story.checkpoint() is cp, page_of(app) is page,
                           page.grid.focus_cell, notices(app))
        app.shell.close_game_menu()
        yield from wait(lambda: app.shell.game_menu() is None)
        yield from wait(lambda: app.screens.top is textbox(app))
        post_key(pygame.K_F9)                                  # F9: confirm_load first
        yield
        post_key(pygame.K_LEFT)
        yield
        post_key(pygame.K_RETURN)                              # Yes: the nearest question next
        yield from wait(lambda: top_message(app) == NEAREST)
        out["f9_question"] = top_message(app)
        yield from confirm_yes(app)
        yield from wait(lambda: app.screens.top is textbox(app) and line_text(app) != ts.LINE6)
        out["loaded"] = line_text(app)

    out = play(scripted_app, script, last=900)
    assert launch(game) == 0
    assert out["page_question"] == out["f9_question"] == NEAREST
    assert out["after_no"] == (True, True, 0, [])
    assert out["loaded"] == "The wind howls."
    path = ".".join(map(str, states["cp"][8].position_at[1]))
    w82 = [m for m in save_log(game) if m.startswith("couldn't load")]
    assert w82 == [f"couldn't load {label}: the saved line in label start (statement {path}) "
                   "is gone; offering the nearest point" for label in ("Slot 1", "Quick 1")]


# --- AC-F11-32 (golden saves from the title); AC-F11-31's G3 row (I-14 A3) ---------------------

def test_ac32_title_load_of_golden_saves(tmp_path, scripted_app, unthreaded):
    game = ts.make_game(tmp_path / "game")
    put(game, (ts.GOLDEN / "p6.vnsave").read_bytes())
    put(game, ss.with_meta((ts.GOLDEN / "p18.vnsave").read_bytes(), seq=2),
        SlotId("auto", 2))
    left = []

    def script(app, out):
        yield from installed(app)
        real = app.shell.leave_title
        app.shell.leave_title = lambda: (left.append(1), real())[1]
        yield from wait(lambda: app.shell.mode.name == "TITLE" and no_confirm(app))
        app.shell.open_title_page("load", InputKind.KEYS)
        yield
        page = page_of(app)
        yield from wait(lambda: page.views[1].state == "filled")
        out["page"] = (page.page, page.grid.focus_cell, app.shell.game_menu().scope.focused
                       is page.grid)
        post_key(pygame.K_RETURN)                              # no confirm from the title
        yield
        out["confirm"] = top_message(app)
        yield from wait(lambda: app.screens.top is textbox(app))
        out["line"] = line_text(app)

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["page"] == ("auto", 1, True) and out["confirm"] is None
    assert out["line"] == ts.LINE18 and left == [1]


def test_g3_loading_indicator_only_over_1_mib(tmp_path, scripted_app, unthreaded, states):
    game = ts.make_game(tmp_path / "game", title=False)
    big = save_of(states, 8, seq=2, note="n" * (1 << 20))      # Newest: the focused cell
    assert len(big) > 1 << 20
    put(game, big)
    put(game, save_of(states, 8), SlotId(1, 2))
    drawn = []

    def script(app, out):
        yield from wait(lambda: at_line(app, ts.LINE6))
        for cell in (0, 1):
            yield from open_page(app, "load")
            page = page_of(app)
            yield from wait(lambda: page.views[cell].state == "filled")
            post_key(pygame.K_RIGHT)
            yield
            if cell:
                post_key(pygame.K_RIGHT)
                yield
            post_key(pygame.K_RETURN)
            yield
            yield from confirm_yes(app)
            yield from wait(lambda: app.saves.loading_slot is None)
            out[cell] = list(drawn)
            drawn.clear()
            yield from wait(lambda: app.screens.top is textbox(app))

    real = save_page_mod.draw_loading_indicator
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(save_page_mod, "draw_loading_indicator",
                   lambda canvas, word, color, *, bright: (drawn.append((word, color, bright)),
                                                           real(canvas, word, color,
                                                                bright=bright)))
        out = play(scripted_app, script)
        assert launch(game) == 0
    # Drawn still (dot 1 bright) in the badge frame(s): the read is one step.
    assert out[0] and set(out[0]) == {("Loading", (0xFF, 0xE6, 0xF0), 0)}
    assert out[1] == []


# --- AC-F11-36: patched stories ---------------------------------------------------------------

def test_ac36_v_add_loads_at_the_exact_line(tmp_path, states):
    text = ts.script_text()
    late = 'label late:\n    "Late line."\n    return\n'
    patched = text.replace(late, "").replace("default trust = 0\n",
                                             "default trust = 0\ndefault met = False\n")
    patched = patched.replace("label start:\n", late + "label start:\n").replace(
        '    hana "Hey, have', '    hana "One more thing."\n    hana "Hey, have')
    patched += 'label extra:\n    "Extra."\n    return\n'
    program = ts.load_program(tmp_path / "game", patched)
    for line in (8, 9):
        state = dataclasses.replace(states["cp"][line],
                                    variables={**states["cp"][line].variables, "trust": 4})
        interp = ts.launched(program)
        interp.new_game(1)
        interp.run(10_000)
        assert interp.restore(state, check_only=True).result is RestoreResult.OK, line
        assert interp.restore(state).result is RestoreResult.OK, line
        cp = interp.checkpoint()
        assert cp.position == state.position and cp.variables["met"] is False, line
        assert cp.variables["trust"] == 4, line


def test_ac36_v_noasset_loads_with_no_failure(tmp_path, scripted_app, unthreaded, states):
    game = ts.make_game(tmp_path / "game", "\n[saves]\nconfirm_quick_load = false\n",
                        title=False)
    (game / "images" / "bg" / "room.png").unlink()
    shutil.rmtree(game / "audio")
    put(game, save_of(states, 8), SlotId("quick", 1))

    def script(app, out):
        yield from wait(lambda: at_line(app, ts.LINE6))
        post_key(pygame.K_F9)
        yield from wait(lambda: at_line(app, ts.LINE8))
        out["notices"] = notices(app)

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["notices"] == []


# --- AC-F11-61, I-4, AC-F11-13: the seams -----------------------------------------------------

def test_ac61_chapter_listeners_note_restore_refresh(tmp_path, scripted_app, unthreaded, states):
    game = ts.make_game(tmp_path / "game", title=False)
    loads = []

    def script(app, out):
        yield from installed(app)
        service = app.saves
        service.add_load_listener(lambda: loads.append(1))
        yield from wait(lambda: at_line(app, ts.LINE6))
        cp6 = app.story.checkpoint()
        service.set_chapter_provider(lambda state: "Chapter 2: The Poem")
        post_key(pygame.K_F5)
        yield from wait(lambda: file_of(game, "quick-1.vnsave").is_file())
        service.set_chapter_provider(None)
        post_key(pygame.K_SPACE)
        yield
        post_key(pygame.K_SPACE)
        yield from wait(lambda: at_line(app, ts.LINE8))
        # F14: a restore reported by note_restore is never auto-saved, even when requested.
        assert app.story.restore(cp6).result is RestoreResult.OK
        service.note_restore()
        service.request_autosave()
        for _ in range(4):
            yield
        out["auto_after_note"] = file_of(game, "auto-1.vnsave").exists()
        put(game, b"junk\n", SlotId(1, 1))
        service._load(SlotId(1, 1), "game")                   # refused: no listener
        yield
        out["loads_after_refusal"] = len(loads)
        service.quick_load(InputKind.KEYS)                     # confirm_load, then Yes
        yield
        yield from confirm_yes(app)
        yield from wait(lambda: app.screens.top is textbox(app))
        out["loads"] = len(loads)
        # F39: a file copied in while the Load page shows appears after refresh().
        yield from open_page(app, "load")
        page = page_of(app)
        while page.page != 1:
            post_key(pygame.K_PAGEDOWN)
            yield
        yield from wait(lambda: page.views[2].state != "loading")
        out["before"] = page.views[2].state
        put(game, save_of(states, 8, seq=9), SlotId(1, 3))
        for _ in range(3):
            yield
        out["unrefreshed"] = page.views[2].state
        service.refresh()
        yield from wait(lambda: page.views[2].state == "filled")
        out["refreshed"] = page.views[2].description

    out = play(scripted_app, script)
    assert launch(game) == 0
    meta = ss.meta(file_of(game, "quick-1.vnsave").read_bytes())
    assert meta["description"] == meta["chapter"] == "Chapter 2: The Poem"
    assert out["auto_after_note"] is False
    assert out["loads_after_refusal"] == 0 and out["loads"] == 1
    assert out["before"] == out["unrefreshed"] == "empty"
    assert out["refreshed"] == ts.LINE8


def test_ac61_i4_delete_all(tmp_path, scripted_app, unthreaded, states):
    """Every slot name of the shown pages goes over several frames; ``notes.txt``,
    ``page03-1.vnsave``, ``page11-1.vnsave`` (past ``pages``), and temps stay; a real folder
    at a slot name fails with W83 and the notice (AC-F11-13); ``delete`` meanwhile raises,
    F5 saves nothing; a save queued before it is written, then deleted (I-4)."""
    game = ts.make_game(tmp_path / "game", title=False)
    p8 = save_of(states, 8)
    for slot in (SlotId("auto", 1), SlotId("quick", 6), SlotId(1, 1), SlotId(10, 6)):
        put(game, p8, slot)
    # (QUICK-1.vnsave is quick-1's own entry on a case-insensitive file system.)
    kept = ["notes.txt", "page03-1.vnsave", "page11-1.vnsave", ".quick-1.vnsave.0123abcd.tmp"]
    for name in kept:
        file_of(game, name).write_bytes(b"x")
    (game / "saves" / "page2-2.vnsave").mkdir()
    (game / "saves" / "page2-2.vnsave" / "inside").write_bytes(b"y")

    def script(app, out):
        yield from wait(lambda: at_line(app, ts.LINE6))
        service = app.saves
        post_key(pygame.K_F5)                                  # queued before delete_all
        yield
        service.delete_all()
        out["at_once"] = service.view(SlotId(1, 1)).status
        with pytest.raises(ValueError):
            service.delete(SlotId(1, 1))
        frames = 0
        while service.deleting_all:
            post_key(pygame.K_F5)                              # saving is off meanwhile
            yield
            frames += 1
        out["frames"] = frames
        yield
        out["notices"] = notices(app)

    out = play(scripted_app, script)
    assert launch(game) == 0
    assert out["at_once"] is SlotStatus.EMPTY
    slots = len(saves.all_slots(10))
    assert slots // 16 <= out["frames"] <= slots // 16 + 3
    left = sorted(p.name for p in (game / "saves").iterdir())
    assert left == sorted(kept + ["page2-2.vnsave"])
    assert (game / "saves" / "page2-2.vnsave" / "inside").read_bytes() == b"y"
    assert "Couldn't delete this save." in out["notices"]
    w83 = [m for m in save_log(game) if m.startswith("couldn't delete")]
    assert w83 == ["couldn't delete Slot 2: not a file or link"]


def test_ac56_w82_echoes_a_hostile_saved_label():
    """SEC-F11-09b: a 500-character saved label with newlines reaches W82 escaped and cut to
    ``echo()``'s 120 characters; the path likewise."""
    state = dataclasses.replace(ss.p8_state(), position_at=("ab\n" * 167, (1, 2)))
    text = w82_text("Slot 1", position_reason(state, NO_NEARBY_POINT))
    label = text.split(" in label ", 1)[1].split(" (statement ", 1)[0]
    assert "\n" not in text and len(label) <= 120 and label.startswith("ab\\nab")
    assert text.endswith("(statement 1.2) is gone and no nearby point was found")
