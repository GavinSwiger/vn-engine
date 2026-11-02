"""F19 step 4 in the real app: an ending's card on screen, the way out to the title, and saves
around it (``04-technical.md`` §2 Q7, §7.1; ``06-acceptance.md`` §0.3 App E and App S).

Every run is an in-process ``launch()`` (``scripted_app``: F01's fake frame clock at 1/60 s,
hidden window, 1280×720, dev) on Template R (``template_e``) in a game folder under
``tmp_path``, scripted frame by frame (``play``); the save writer is unthreaded (App S). No
app module is new: the card is F18's (``install_chapters``' painter, ``TitleCard.kind``),
the end is F10's (``GameShell.story_ended``), and the saves are F11's.

AC-F19-19 (saves around an ending), AC-F19-20 (the card on screen and the way out), and
AC-F19-23's sessions (``--no-persistent`` and READ_ONLY; its windowed rows are in
``test_windowed_equals_headless.py``).
"""

import json

import pygame
import pytest

from engine.app import cli
from engine.app.app import App
from engine.persist.location import FILE_NAME
from engine.persist.saves import SlotId
from engine.runtime.commands import Say, ShowMenu, StoryEnded, TitleCard
from engine.runtime.flowchart import EDGE_KIND, FLOW_KIND
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.nav import InputKind
from engine.ui.shell import GameShell, Mode
from tests.app.test_autosave_app import autos
from tests.app.test_save_pages_app import open_page
from tests.app.test_saves_service import (full, launch, line_text, make_game, play, unthreaded,
                                          wait)
from tests.fakes.loop import post_key, post_quit
from tests.persist.writer_support import tree
from tests.runtime.corpus import canon
from tests.runtime.endings_story import F19, run_e, store_with, walk
from tests.script.helpers import template_e

# F20's first arrivals are normal unlocks too (07 I-8); these rows hear F19's kinds only.
FLOW_KINDS = (FLOW_KIND, EDGE_KIND)

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

FILL = (0x2A, 0x1E, 0x26)                      # [theme.chapter] fill_color
RED = (0xC8, 0x28, 0x00)                       # the stage under the card (S/T below)
PROBE = (640, 100)                             # above the card's text
INSTANT = "[textbox]\ncps = 0\n"
WALK = (F19 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")


def game_of(root, text: str | None = None, *, title: bool = True, config: str = ""):
    """App S's game folder (``[game] id``, ``autosave_quit = false`` unless set) holding
    ``text`` (Template R by default), with the title on unless ``title`` is False."""
    root.mkdir(parents=True, exist_ok=True)
    game = make_game(root, INSTANT + config)
    (game / "script" / "main.vns").write_text(text if text is not None else template_e(),
                                              encoding="utf-8")
    if title:
        cfg = game / "config.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("[title]\nenabled = false\n",
                                                               ""), encoding="utf-8")
    return game


def spy_commands(app) -> list:
    """Every command the router dispatches from now on."""
    router = app.router
    real = router.dispatch
    seen: list = []

    def dispatch(command):
        seen.append(command)
        real(command)

    router.dispatch = dispatch
    return seen


def title_ready(app) -> bool:
    top = app.screens.top
    return (app.shell is not None and isinstance(top, TitleScreen) and top.in_t >= 1.0
            and not top.leaving)


def new_game(app):
    yield from wait(lambda: title_ready(app))
    app.shell.start_new_game()
    yield from wait(lambda: line_text(app) is not None)


def press_until(app, pred, key=pygame.K_SPACE, every: int = 3):
    """``key`` every few frames until ``pred()``."""
    n = 0
    while not pred():
        if n % every == 0:
            post_key(key)
        n += 1
        yield


def in_card(app) -> bool:
    stage = app.stage_screen
    return stage is not None and stage.view.card is not None


def in_hold(app) -> bool:
    return in_card(app) and app.stage_screen.wait_kind == "timed"


def ended(app) -> bool:
    return app.shell.mode is not Mode.GAME


def after_line(commands: list, text: str) -> list:
    """The commands after the last ``Say`` of ``text``, up to and with ``StoryEnded``, as
    canonical JSON without wait ids (the session's counter goes on across games)."""
    at = max(i for i, c in enumerate(commands) if type(c) is Say and c.text == text)
    rest = commands[at + 1:]
    end = next(i for i, c in enumerate(rest) if type(c) is StoryEnded)
    out = []
    for item in canon(rest[:end + 1]):
        item.pop("wait_id", None)
        out.append(item)
    return out


def click() -> None:
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        pygame.event.post(pygame.event.Event(kind, pos=(640, 360), button=1, touch=False))


# --- AC-F19-20 — the card on screen and the way out ---------------------------------------------

class Frames:
    """Per presented frame (the limiter's number): the probe, the stage view's card, the
    stack's top, and the shell's mode; plus the frame ``StoryEnded`` was handled in, the
    ``stop_story_audio`` calls, and every card the painter was given."""

    def __init__(self, session, mp) -> None:
        self.session = session
        self.rows: dict[int, tuple] = {}
        self.ended: list[int] = []
        self.audio: list[tuple[int, float]] = []
        self.painted: set[str] = set()
        rows, frames = self.rows, self
        real_present, real_end = App.present, GameShell.story_ended

        def present(app):
            result = real_present(app)
            stage = app.stage_screen
            card = stage.view.card if stage is not None else None
            rows[frames.frame] = (tuple(app.window.framebuffer().get_at(PROBE))[:3], card,
                                  type(app.screens.top), app.shell and app.shell.mode)
            return result

        def story_ended(shell, cmd):
            frames.ended.append(frames.frame)
            real_end(shell, cmd)

        mp.setattr(App, "present", present)
        mp.setattr(GameShell, "story_ended", story_ended)

    @property
    def frame(self) -> int:
        return self.session.limiters[-1].frame

    def wire(self, app) -> None:
        """At the first line: spy on the audio service and the card painter."""
        audio, painter = app.audio, app.stage_screen.view.card_painter
        real_stop, real_paint = audio.stop_story_audio, painter.paint
        audio.stop_story_audio = lambda s: (self.audio.append((self.frame, s)), real_stop(s))
        painter.paint = lambda canvas, card: (self.painted.add(card.kind),
                                              real_paint(canvas, card))


def test_ac20_the_card_on_screen_and_the_way_out(tmp_path, scripted_app, unthreaded):
    """Template R with a red stage (S: ``scene bg a``, T: its image). R(s) = round(60 s)
    from the click at "Before." (frame t0). F09's frame rule (AC-F18-04): a ``with`` keeps
    the old picture for one preparing frame, and each wait hands off to the next a frame or
    two later, so the card is full at R(1.0) + 1 and the hold's 180 frames end at R(4.0)
    + 4 (AC-F18-04's measured 184), where ``StoryEnded`` is handled: no out phase."""
    edits = dict(S="scene bg a", T='image bg a = "#c82800"')

    def to_before(app, out, frames):
        yield from wait(lambda: title_ready(app) or line_text(app) is not None)
        if title_ready(app):
            yield from new_game(app)
        frames.wire(app)
        yield from press_until(app, lambda: line_text(app) == "Before.")
        for _ in range(3):
            yield
        click()                                      # t = 0
        out["t0"] = out["frame"]

    # Run 1: left alone, title on.
    game = game_of(tmp_path / "alone", template_e(**edits))
    with pytest.MonkeyPatch.context() as mp:
        frames = Frames(scripted_app, mp)

        def script(app, out):
            yield from wait(lambda: app.shell is not None)
            yield from to_before(app, out, frames)
            yield from wait(lambda: title_ready(app))

        out = play(scripted_app, script, last=700)
        assert launch(game) == 0
    t0, rows = out["t0"], frames.rows
    full = min(f for f, r in rows.items() if f >= t0 and r[0] == FILL) - t0
    [end] = [f - t0 for f in frames.ended]
    assert full == 60 + 1                                    # R(1.0), its preparing frame
    assert end == 240 + 4 and end - full == 183              # R(4.0) and the hand-offs
    assert all(rows[t0 + t][0] == FILL for t in range(full, end + 1))
    assert frames.audio == [(t0 + end, 0.5)]
    # AC-F10-40's fade: 60 frames over the card (it stays set, the stage never shows),
    # then the title from black.
    for k in range(60):
        probe, card, top, mode = rows[t0 + end + k]
        assert top is BlackFadeScreen and mode is Mode.ENDING, k
        assert card is not None and card.kind == "ending" and card.name == "sad", k
        assert probe != RED and all(p <= f for p, f in zip(probe, FILL)), (k, probe)
    probe, card, top, mode = rows[t0 + end + 60]
    assert (probe, card, top, mode) == ((0, 0, 0), None, TitleScreen, Mode.TITLE)
    assert all(r[1] is not None for f, r in rows.items() if t0 + 1 <= f < t0 + end + 60)
    assert frames.painted == {"ending"}
    assert TitleCard("c", None, "T").kind == "chapter"

    # Run 2: a click at R(2.0) ends the hold; with the title off the game exits 0 after
    # the 60-frame fade (AC-F10-41's form).
    game = game_of(tmp_path / "click", template_e(**edits), title=False)
    with pytest.MonkeyPatch.context() as mp:
        frames = Frames(scripted_app, mp)

        def script(app, out):
            yield from wait(lambda: app.shell is not None)
            yield from to_before(app, out, frames)
            for _ in range(120):
                yield
            out["clicked"] = out["frame"]
            click()                                          # R(2.0)
            while True:
                yield

        out = play(scripted_app, script, last=700)
        assert launch(game) == 0
    t0 = out["t0"]
    # The click is read in its frame's event phase, which posts the hold's ``WaitDone``; the
    # story pumps later in that frame, so ``StoryEnded`` is handled in the click's own frame.
    assert out["clicked"] - t0 == 120 and frames.rows[out["clicked"] - 1][0] == FILL
    assert frames.ended == [out["clicked"]]
    assert frames.audio == [(out["clicked"], 0.5)]
    last = scripted_app.limiters[-1].frame
    assert last - frames.ended[0] == 60                     # the fade, then the quit
    assert all(r[2] is BlackFadeScreen and r[1] is not None
               for f, r in frames.rows.items() if frames.ended[0] <= f < frames.ended[0] + 60)


# --- AC-F19-19 — saves around an ending ---------------------------------------------------------

def slots(game) -> dict:
    folder = game / "saves"
    return tree(folder) if folder.is_dir() else {}


def through_card(app):
    """From "Before." shown: Space until the story has ended, then the title."""
    yield from press_until(app, lambda: ended(app), every=2)
    yield from wait(lambda: title_ready(app))


def quit_now(app):
    """The window's close button, then Yes if the shell asks."""
    post_quit()
    for _ in range(3):
        yield
    if isinstance(app.screens.top, ConfirmScreen):
        post_key(pygame.K_LEFT)
        yield
        post_key(pygame.K_RETURN)
    while True:
        yield


def test_ac19_saves_around_an_ending(tmp_path, scripted_app, unthreaded):
    """One session on Template R with ``[saves] autosave_quit = true``: F5 at "Before.", then
    the end (rows 1–2: no slot file changes, and loading the quick save from the title
    replays the card with no new unlock); a Save to slot 1 from the game menu during the
    hold (row 3); then a quit in the hold (row 5). Then the chapter row (R8) and a quit in
    the story-end fade, one launch each."""
    quits = "[saves]\nautosave_quit = true\n"
    game = game_of(tmp_path / "session", config=quits)

    def script(app, out):
        yield from wait(lambda: title_ready(app))
        store = app.persist.store
        commands = spy_commands(app)
        heard: list = []
        app.persist.add_unlock_listener(lambda kind, name: heard.append((kind, name))
                                            if kind not in FLOW_KINDS else None)
        # Row 1–2: F5 at "Before.", play to the title.
        yield from new_game(app)
        yield from press_until(app, lambda: line_text(app) == "Before.")
        app.saves.quick_save()
        yield from wait(lambda: (game / "saves" / "quick-1.vnsave").is_file())
        for _ in range(3):
            yield
        before = slots(game)
        yield from through_card(app)
        out["row1"] = slots(game) == before
        out["first"] = after_line(commands, "Before.")
        out["heard_first"] = list(heard)
        # Load the quick save from the title; advance through the card again.
        version, records = store.version, store.unlocked("ending")
        results: list = []
        real_unlock = store.unlock
        store.unlock = lambda kind, name, **kw: results.append(
            (kind, real_unlock(kind, name, **kw))) or results[-1][1]
        app.saves.load_from(SlotId("quick", 1), InputKind.KEYS, origin="title")
        yield from wait(lambda: line_text(app) is not None)
        out["loaded_line"] = line_text(app)
        for _ in range(3):
            yield
        yield from through_card(app)
        out["replay"] = after_line(commands, "Before.")
        out["unlocks"] = results
        out["store"] = (store.version == version, store.unlocked("ending") == records)
        out["heard"] = list(heard)
        del store.unlock
        # Row 3: in the hold, Esc → Save → slot 1 → back; then the end; then load slot 1.
        yield from new_game(app)
        yield from press_until(app, lambda: line_text(app) == "Before.")
        yield from press_until(app, lambda: in_hold(app), every=4)
        yield from open_page(app, "save")
        post_key(pygame.K_RIGHT)                                 # into the grid, cell 1
        yield
        post_key(pygame.K_RETURN)                                # an empty slot: saved
        yield from wait(lambda: (game / "saves" / "page1-1.vnsave").is_file())
        yield from press_until(app, lambda: app.shell.game_menu() is None, pygame.K_ESCAPE,
                               every=40)
        out["held_after_menu"] = in_hold(app)
        yield from wait(lambda: ended(app))
        yield from wait(lambda: title_ready(app))
        app.saves.load_from(SlotId(1, 1), InputKind.KEYS, origin="title")
        yield from wait(lambda: line_text(app) is not None)
        out["slot1_line"] = line_text(app)
        for _ in range(3):
            yield
        yield from through_card(app)
        out["slot1_replay"] = after_line(commands, "Before.")
        # Row 5: a quit in the hold.
        yield from new_game(app)
        yield from press_until(app, lambda: in_hold(app), every=4)
        out["quit_mode"] = app.shell.mode
        yield from quit_now(app)

    out = play(scripted_app, script, last=2500)
    assert launch(game) == 0
    assert out.get("quit_mode") is Mode.GAME, sorted(out)
    assert out["row1"] is True
    first = out["first"]
    assert first[0]["type"] == "ShowStage" and first[0]["card"]["kind"] == "ending"
    assert first[-1]["type"] == "StoryEnded"
    assert out["heard_first"] == [("ending", "sad")]
    assert out["loaded_line"] == "Before."
    assert out["replay"] == first                    # AC-F19-09's commands, again
    assert [made for kind, made in out["unlocks"] if kind not in FLOW_KINDS] == [False]
    assert not any(made for _, made in out["unlocks"])     # F20's re-arrival: nothing new
    assert out["store"] == (True, True) and out["heard"] == [("ending", "sad")]
    assert out["held_after_menu"] is True
    assert full(game, SlotId(1, 1)).meta.description == "Before."
    assert out["slot1_line"] == "Before." and out["slot1_replay"] == first
    assert autos(game) == ["Before."]                       # row 5: the quit in the hold

    # R8: a chapter with no card just before the ending: its Auto save request is pending
    # through the card, and goes with the game at the title.
    game = game_of(tmp_path / "chapter", template_e(replace={8: '[4]chapter c "C" 0'}))

    def chapter(app, out):
        yield from new_game(app)
        yield from press_until(app, lambda: in_hold(app), every=4)
        out["pending"] = app.saves.autosave_pending
        yield from wait(lambda: ended(app))
        yield from wait(lambda: title_ready(app))
        for _ in range(5):
            yield
        out["pending_title"] = app.saves.autosave_pending

    out = play(scripted_app, chapter, last=900)
    assert launch(game) == 0
    assert (out["pending"], out["pending_title"]) == (True, False)
    assert autos(game) == []

    # Row 5: a quit in the story-end fade saves nothing (mode ENDING).
    game = game_of(tmp_path / "fade", config=quits)

    def quit_in_fade(app, out):
        yield from new_game(app)
        yield from press_until(app, lambda: ended(app), every=4)
        out["mode"] = (app.shell.mode, type(app.screens.top))
        yield from quit_now(app)

    out = play(scripted_app, quit_in_fade, last=900)
    assert launch(game) == 0
    assert out["mode"] == (Mode.ENDING, BlackFadeScreen)
    assert autos(game) == []


# --- AC-F19-23 — without a persistent file (its windowed rows: test_windowed_equals_headless) ---

# AC-F19-24's table: the bridge choice's lock in ``ShowMenu``, then the records after the run
# (endings, ``persistent.routes``, ``persistent.playthrough``, the run's new unlocks).
WALK_RUNS = [
    ([False, False, True], ("sad",), [], 1, [("ending", "sad")]),
    ([False, False, True], ("sad", "good"), ["promise"], 1, [("ending", "good")]),
    ([False, False, False], ("true",), [], 2, [("ending", "true")]),
    ([False, False, True], ("true",), [], 2, []),
]
CHOICES = (1, 2, 3, None)
NEWER = json.dumps({"format": 2, "identity_scheme": 1, "values": {"festivals": 2}, "seen": {},
                    "chosen": {}, "unlocks": {}}).encode("ascii")


def records(store, menu, heard) -> tuple:
    return ([c.locked for c in menu.choices], store.unlocked("ending"), store.get("routes"),
            store.get("playthrough"), heard)


def walk_session(app, out):
    """Runs 1–4 of AC-F19-24 from the title, one New Game each (run 4 stops at the menu)."""
    yield from wait(lambda: title_ready(app))
    store = app.persist.store
    out["mode"] = app.persist.mode
    commands = spy_commands(app)
    heard: list = []
    app.persist.add_unlock_listener(lambda kind, name: heard.append((kind, name))
                                    if kind not in FLOW_KINDS else None)
    rows = out["rows"] = []
    for choice in CHOICES:
        yield from new_game(app)
        yield from press_until(app, lambda: isinstance(app.screens.top, ChoiceScreen), every=2)
        menu = [c for c in commands if type(c) is ShowMenu][-1]
        if choice is None:
            rows.append(records(store, menu, []))
            break
        yield from press_until(app, lambda: not isinstance(app.screens.top, ChoiceScreen),
                               pygame.K_0 + choice, every=6)
        yield from press_until(app, lambda: ended(app), every=2)
        yield from wait(lambda: title_ready(app))
        rows.append(records(store, menu, list(heard)))
        heard.clear()


def test_ac23_without_a_persistent_file(tmp_path, user_roots, scripted_app, unthreaded):
    """Runs 1–4 in one session under ``--no-persistent`` (MEMORY), READ_ONLY (a ``format`` 2
    file), and the headless runner's in-memory store (one store, Run R): the menus and
    records are AC-F19-24's. No file is written; the READ_ONLY file's bytes are unchanged."""
    from engine.persist.sync import MEMORY, READ_ONLY

    store = store_with()
    rows = []
    for choice in CHOICES:
        commands = run_e(walk(), store, show_locked=True,
                         inputs=["advance"] + ([f"choose {choice}"] if choice else []))
        [menu] = [c for c in commands if type(c) is ShowMenu]
        rows.append(records(store, menu, list(store.take_new_unlocks())))
    assert rows == WALK_RUNS

    config = "[choice]\nshow_locked = true\n"
    memory = game_of(tmp_path / "memory", WALK, config=config)
    out = play(scripted_app, walk_session, last=3000)
    assert cli.main(["run", str(memory), "--no-persistent"]) == 0
    assert out["mode"] is MEMORY and out["rows"] == WALK_RUNS
    assert not (memory / "persistent").exists()

    newer = game_of(tmp_path / "newer", WALK, config=config)
    (newer / "persistent").mkdir()
    (newer / "persistent" / FILE_NAME).write_bytes(NEWER)
    out = play(scripted_app, walk_session, last=3000)
    assert launch(newer) == 0
    assert out["mode"] is READ_ONLY and out["rows"] == WALK_RUNS
    assert tree(newer / "persistent") == {FILE_NAME: NEWER}
