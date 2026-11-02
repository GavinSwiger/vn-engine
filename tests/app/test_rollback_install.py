"""F14 step 4 — rollback in the real app (``install_rollback``, the driver's view and listeners,
``RollbackKeys`` over the real screens): AC-F14-04 (config rows), 20, 22, 23, 29, AC-F14-10's
(F15) seen-skip row, and the Main Menu rows of AC-F14-03 and 06 (inside AC-F14-29's run).

Every run is App S (``tests/app/test_saves_service.py``: an in-process ``launch()`` on a fake
1/60 s clock, hidden window, dev, the unthreaded writer) on Run K's script (``tests/fixtures/
F14/steps``) with its images, instant text, and a game id so F11's saves work. A test script
is a generator (one ``yield`` per frame); ``go`` plays K live (Space, key 1 at the menu) and
records the first-pass snapshots ``k``; ``Spy`` records the posted rollback events and the
frames whose pump changed the timeline's counters.

Step 5 adds AC-F14-21 (the landing on screen, with its (F09) and (F15) rows) and AC-F14-31 (the
limit cue's look and placement: the drawn mark as a small surface, then framebuffer probes,
captures, and the theme rows).
"""

import dataclasses
import logging
import math
from pathlib import Path

import pygame
import pytest

from engine.app.story import RuntimeStoryDriver
from engine.app.ui_contrast import warn_contrast
from engine.core.config import load_config
from engine.core.config_schema import Config, RollbackMarkTheme, RollbackTheme, ThemeConfig
from engine.core.paths import GamePaths
from engine.persist import saves
from engine.persist.saves import SlotId, SlotStatus
from engine.render.canvas import Canvas
from engine.render.typewriter import TypeState
from engine.runtime.commands import Advance, Choose, StepBack, StepForward
from engine.runtime.interpreter import Status
from engine.ui.builtin.black_fade import BlackFadeScreen
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.rollback import LimitCue
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.builtin.title_screen import TitleScreen
from engine.ui.menus import EntryContext
from engine.ui.nav import InputKind
from engine.ui.theme import UiTheme, plain_theme, resolve_theme
from tests.app.test_autosave_app import fake_dt, spend
from tests.app.test_saves_service import launch, play, unthreaded
from tests.fakes.fake_mixer import ogg_bytes
from tests.fakes.loop import post_key, post_quit
from tests.fakes.ui_shell import TestShell, UiHarness
from tests.fixtures.F04 import gen_images as gen
from tests.persist import save_support as ss
from tests.render.conftest import make_assets
from tests.runtime.effects_story import load_game
from tests.runtime.rollback_story import F14, launched

pytestmark = pytest.mark.display
__all__ = ["fake_dt", "unthreaded"]                # fixtures, re-exported for pytest

K_TEXT = (F14 / "steps" / "script" / "main.vns").read_text(encoding="utf-8")
WALLS_TEXT = (F14 / "walls" / "script" / "main.vns").read_text(encoding="utf-8")
BASE = f'''[game]
id = "{ss.GAME_ID}"
title = "Rollback"
version = "1.0"

[textbox]
cps = 0
'''
NO_SAVES = "autosave_quit = false\nautosave_choices = false\n"
NO_TITLE = "\n[title]\nenabled = false\n"
STEPS = (("A", "One."), ("B", "Two."), ("C", "Three"), ("M", "Which way?"), ("D1", "Wade one."),
         ("D2", "Wade two."), ("S", "Side."), ("F", "Last"))


def k_game(tmp_path: Path, config: str = NO_TITLE, *, text: str = K_TEXT,
           name: str = "game", saves_: str = NO_SAVES) -> Path:
    """Run K's folder (or ``text``) with its three images; ``config`` follows ``BASE``, and
    ``saves_`` is the ``[saves]`` table (no auto-saves by default)."""
    root = tmp_path / name
    (root / "script").mkdir(parents=True)
    (root / "script" / "main.vns").write_text(text, encoding="utf-8")
    (root / "config.toml").write_text(BASE + config + "\n[saves]\n" + saves_,
                                      encoding="utf-8")
    gen.write(root, {gen.ref_of("river"): gen.block(64, 36, (0, 0, 255)),
                     gen.ref_of("hana happy"): gen.block(30, 60, (0, 255, 0)),
                     gen.ref_of("hana worried"): gen.block(30, 60, (255, 255, 0))})
    return root


# --- frame helpers ------------------------------------------------------------------------------

def line(app) -> str | None:
    box = app.textbox
    return None if box is None or box.line is None else box.line.text


def name_at(app) -> str | None:
    text = line(app)
    return None if text is None else next((n for n, p in STEPS if text.startswith(p)), None)


def choices(app) -> ChoiceScreen | None:
    return next((s for s in app.screens if isinstance(s, ChoiceScreen)), None)


def ready(app) -> bool:
    """The story waits at a shown step (at a menu: its choices are up), no chain running."""
    story = app.story
    if story is None or story.status is not Status.WAITING or story.interp.busy:
        return False
    if story.interp.current is None:
        return False
    menu = story.interp.choices.waiting is not None
    return (choices(app) is not None) if menu else line(app) is not None


def go(app, name: str, k: dict | None = None, *, pick=pygame.K_1, match=None):
    """Play live (Space at a line, ``pick`` at the menu) until step ``name`` waits; ``k``
    gets each step's first-pass snapshot. ``match`` (a predicate) replaces ``name``."""
    for _ in range(400):
        here = name_at(app) if line(app) is not None else None
        if ready(app):
            if k is not None and here is not None and here not in k:
                k[here] = app.story.checkpoint()
            if (match(app) if match is not None else here == name):
                return
            menu = choices(app)
            if menu is not None:
                if menu.past_guard:
                    post_key(pick)
            else:
                post_key(pygame.K_SPACE)
        yield
        yield
    raise AssertionError(f"never reached {name}")


def frames(n: int):
    for _ in range(n):
        yield


def settle(app):
    """Frames until the story waits at a shown step again (a landing's burst shown)."""
    for _ in range(3):
        yield
    for _ in range(60):
        if ready(app):
            return
        yield
    raise AssertionError("the story never settled")


def wheel(y: float, *, precise: bool = True) -> None:
    attrs = {"x": 0, "y": int(y), "flipped": False, "which": 0, "touch": False}
    if precise:
        attrs.update(precise_x=0.0, precise_y=float(y))
    pygame.event.post(pygame.event.Event(pygame.MOUSEWHEEL, **attrs))


def pad(button: int) -> None:
    pygame.event.post(pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=button,
                                         instance_id=0))
    pygame.event.post(pygame.event.Event(pygame.CONTROLLERBUTTONUP, button=button,
                                         instance_id=0))


LB = pygame.CONTROLLER_BUTTON_LEFTSHOULDER
RB = pygame.CONTROLLER_BUTTON_RIGHTSHOULDER


def all_back_inputs() -> None:
    """Wheel up, Page Up, and LB in one frame (AC-F14-20's column)."""
    wheel(1)
    post_key(pygame.K_PAGEUP)
    pad(LB)


class Spy:
    """Installed once the story is wired: ``posts`` holds ``(frame, event)`` for each posted
    ``StepBack``/``StepForward``/``Choose``; ``changed`` the frames whose pump changed
    ``landings`` (``"landing"``) or only ``matches`` (``"match"``); ``log`` the order of
    ``note_restore``, ``SaveService.update`` and ``skip_auto.reset`` calls by frame."""

    def __init__(self, app, out: dict) -> None:
        self.app, self.out = app, out
        self.posts: list[tuple[int, object]] = []
        self.changed: list[tuple[int, str]] = []
        self.log: list[tuple[int, str]] = []
        driver = app.story
        real_post, real_pump = driver.post, driver.pump
        timeline = driver.interp.timeline

        def post(event):
            if isinstance(event, (StepBack, StepForward, Choose)):
                self.posts.append((self.frame, event))
            real_post(event)

        def pump(*args, **kwargs):
            before = (timeline.landings, timeline.matches)
            commands = real_pump(*args, **kwargs)
            if timeline.landings != before[0]:
                self.changed.append((self.frame, "landing"))
            elif timeline.matches != before[1]:
                self.changed.append((self.frame, "match"))
            return commands

        driver.post, driver.pump = post, pump
        saves_ = app.saves
        if saves_ is not None:
            real_note, real_update = saves_.note_restore, saves_.update

            def note():
                self.log.append((self.frame, "note"))
                real_note()

            def update(dt):
                self.log.append((self.frame, "update"))
                real_update(dt)

            saves_.note_restore, saves_.update = note, update
        skip_auto = app.skip_auto
        if skip_auto is not None:
            real_reset = skip_auto.reset

            def reset():
                self.log.append((self.frame, "reset"))
                real_reset()

            skip_auto.reset = reset

    @property
    def frame(self) -> int:
        return self.out["frame"]

    def rollback_posts(self, since: int = 0) -> list:
        return [e for f, e in self.posts if f >= since and not isinstance(e, Choose)]

    def calls(self, kind: str, since: int = 0) -> list[int]:
        return [f for f, what in self.log if what == kind and f >= since]


def view(app):
    return app.story.rollback_view()


def back_entry(app):
    return app.shell.menus.entry("quick", "back")


def quick_shown(app):
    return app.shell.quick_menu.shown()


def run(scripted_app, game: Path, script, *, last: int = 2000, quits: bool = False) -> dict:
    """Launch ``game`` and play ``script``; it must finish unless it ``quits`` the game."""
    out = play(scripted_app, script, last=last)
    code = launch(game)
    assert out["done"] or quits, "the script did not finish"
    out["code"] = code
    return out


def started(app):
    """Frames until the story and its first line are up."""
    yield from frames(1)
    for _ in range(300):
        if app.story is not None and app.textbox is not None and ready(app):
            return
        yield
    raise AssertionError("the story never started")


# --- AC-F14-04 — [rollback] steps ---------------------------------------------------------------

def test_ac04_rollback_steps(tmp_path, scripted_app, unthreaded):
    """The config rows (absent, 0, 1000, bad values), the depth-100 run (105 lines: back_room
    100, the 101st back refused), and ``steps = 0`` in the App: no Back entry, inputs and
    posted events change nothing, no cue (also AC-F14-20's last row)."""
    def config_of(text: str):
        root = tmp_path / f"cfg{len(list(tmp_path.iterdir()))}"
        root.mkdir()
        (root / "config.toml").write_text(text, encoding="utf-8")
        return load_config(GamePaths.for_game(root))

    result = config_of("")
    assert (result.config.rollback.steps, result.config.rollback.marker) == (100, True)
    result = config_of("[rollback]\nsteps = 1000\nmarker = false\n")
    assert result.errors == [] and result.config.rollback.steps == 1000
    for line_ in ("steps = -1", "steps = 1001", "steps = 5000", 'steps = "100"', "steps = 1.5",
                  "steps = true", 'marker = "yes"'):
        result = config_of(f"[rollback]\n{line_}\n")
        key = line_.split(" ")[0]
        assert len(result.errors) == 1, line_
        text = result.errors[0].format()
        assert text.startswith(f"config.toml, line 2: [rollback] {key} must be "), text
        assert result.config.rollback.steps == 100 and result.config.rollback.marker is True
    # Depth 100 (the default), 105 lines through the driver: back_room 100, then refused.
    root = tmp_path / "lines"
    (root / "script").mkdir(parents=True)
    body = "".join(f'    "L{n}."\n' for n in range(105))
    (root / "script" / "main.vns").write_text("label start:\n" + body, encoding="utf-8")
    driver = RuntimeStoryDriver(launched(load_game(root),
                                         rollback_steps=config_of("").config.rollback.steps))
    driver.fixed_seed = 1
    driver.new_game()
    driver.pump()
    for _ in range(104):
        driver.post(Advance(driver.interp.current.sid))
        driver.pump()
    assert driver.rollback_view().back_room == 100
    for _ in range(100):
        driver.post(StepBack(1))
        driver.pump()
    refused = driver.rollback_view().refused
    driver.post(StepBack(1))
    driver.pump()
    assert driver.rollback_view().refused == refused + 1
    # The App with steps = 0.
    game = k_game(tmp_path, NO_TITLE + "\n[rollback]\nsteps = 0\n")

    def script(app, out):
        yield from started(app)
        spy = Spy(app, out)
        yield from go(app, "C")
        keys = app.rollback_keys
        out["depth"] = app.story.interp.timeline.depth
        out["view"] = view(app)
        out["quick"] = [e.id for e in app.shell.menus.shown("quick")]
        before = (app.story.checkpoint(), line(app), keys.cue.triggers)
        all_back_inputs()
        wheel(-1)
        post_key(pygame.K_PAGEDOWN)
        pad(RB)
        yield from frames(3)
        out["inputs_posted"] = spy.rollback_posts()
        app.story.post(StepBack(1))
        app.story.post(StepForward(1))
        yield from frames(3)
        out["after"] = (app.story.checkpoint(), line(app), keys.cue.triggers)
        out["before"] = before

    out = run(scripted_app, game, script)
    assert out["depth"] == 0 and not out["view"].shown
    assert "back" not in out["quick"]
    assert out["inputs_posted"] == []
    assert out["after"][0] is out["before"][0] and out["after"] == out["before"]


def test_i11_the_app_frees_dropped_states_per_frame(tmp_path, scripted_app, unthreaded):
    """07 I-11: in the App, a New Game queues the old timeline and the frame loop frees it;
    while ``run`` runs, full collections wait for ``GC_FULL_AFTER`` (AC-F14-35)."""
    import gc

    from engine.app.app import GC_FULL_AFTER
    before = gc.get_threshold()

    def script(app, out):
        yield from started(app)
        yield from go(app, "C")
        timeline = app.story.interp.timeline
        out["wired"] = timeline.defer_release and app.rollback_release == timeline.release
        out["threshold"] = gc.get_threshold()
        held = len(timeline.states)
        app.story.new_game()
        out["queued"] = (held, timeline.dropped)
        yield from frames(3)
        out["left"] = timeline.dropped

    out = run(scripted_app, k_game(tmp_path), script)
    assert out["wired"] and out["threshold"][2] == max(before[2], GC_FULL_AFTER)
    held, queued = out["queued"]
    assert held > 1 and queued == held and out["left"] == 0
    assert gc.get_threshold() == before


# --- AC-F14-20 — where rollback inputs act -------------------------------------------------------

def test_ac20_where_rollback_inputs_act(tmp_path, scripted_app, unthreaded):
    """One run with the title on: the title; choices up (wheel, Page Up, LB: each lands on C
    with no Choose and the focus kept until the landing); hidden mode; History, Save page,
    quit confirm; the story-end fade and the title after it; the error screen."""
    game = k_game(tmp_path, "")

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from frames(5)
        assert isinstance(app.screens.top, TitleScreen)
        all_back_inputs()
        yield from frames(2)
        res["title_on_stack"] = any(isinstance(s, TextboxScreen) for s in app.screens)
        app.shell.start_new_game()
        yield from started(app)
        spy = Spy(app, out)
        keys = app.rollback_keys
        k: dict = {}
        # Choices up: each back input steps back once; nothing is picked.
        rows = []
        for send in (lambda: wheel(1), lambda: post_key(pygame.K_PAGEUP), lambda: pad(LB)):
            yield from go(app, "M", k)
            menu = choices(app)
            post_key(pygame.K_DOWN)                   # focus choice 1, then choice 2
            yield
            post_key(pygame.K_DOWN)
            yield
            focus = menu.focus
            since = spy.frame
            send()
            yield
            posted = spy.rollback_posts(since)
            kept = menu.focus == focus and choices(app) is menu
            yield from settle(app)
            rows.append((posted, kept, name_at(app), choices(app) is None,
                         [e for f, e in spy.posts if f >= since and isinstance(e, Choose)]))
        res["choices"] = rows
        res["focus"] = focus
        # Hidden mode: the box shows and the step happens in the same frame.
        post_key(pygame.K_h)
        yield
        res["hidden"] = app.textbox.hidden
        since = spy.frame
        wheel(1)
        yield
        res["hidden_frame"] = (app.textbox.hidden, spy.rollback_posts(since))
        yield from settle(app)
        res["hidden_landed"] = name_at(app)
        # Under menus: no step.
        menus = {}
        for name, open_ in (
                ("history", lambda: app.shell.menus.entry("quick", "history").action(
                    EntryContext(app.shell, InputKind.MOUSE))),
                ("save", lambda: app.shell.menus.entry("quick", "save").action(
                    EntryContext(app.shell, InputKind.MOUSE))),
                ("quit", lambda: app.shell.ask_quit(InputKind.KEYS))):
            open_()
            yield from frames(3)
            before = app.story.checkpoint().to_json()
            since = spy.frame
            all_back_inputs()
            pad(RB)
            yield from frames(3)
            menus[name] = (spy.rollback_posts(since), app.story.checkpoint().to_json() == before,
                           app.screens.story_may_run())
            post_key(pygame.K_ESCAPE)
            yield from frames(2)
            if not app.screens.story_may_run():
                post_key(pygame.K_ESCAPE)
                yield from frames(2)
            if not app.screens.story_may_run():
                app.shell.close_game_menu()
                yield from frames(2)
        res["menus"] = menus
        # The story's end: the fade, then the title. Then the error screen.
        yield from go(app, "F", pick=pygame.K_2)
        cues = keys.cue.triggers
        since = spy.frame
        post_key(pygame.K_SPACE)
        for _ in range(20):
            yield
            if any(isinstance(s, BlackFadeScreen) for s in app.screens):
                break
        res["fade"] = any(isinstance(s, BlackFadeScreen) for s in app.screens)
        all_back_inputs()
        yield from frames(2)
        for _ in range(200):
            if isinstance(app.screens.top, TitleScreen):
                break
            yield
        res["title_again"] = isinstance(app.screens.top, TitleScreen)
        all_back_inputs()
        yield from frames(2)
        app.show_fatal_error(RuntimeError("test"))
        yield
        all_back_inputs()
        yield from frames(2)
        res["end"] = (spy.rollback_posts(since), keys.cue.triggers - cues)

    out = run(scripted_app, game, script)
    res = out["res"]
    assert res["title_on_stack"] is False
    for posted, kept, landed, closed, chose in res["choices"]:
        assert posted == [StepBack(1)] and chose == []
        assert kept and landed == "C" and closed
    assert res["focus"] == 1
    assert res["hidden"] is True and res["hidden_frame"] == (False, [StepBack(1)])
    assert res["hidden_landed"] == "B"
    for name, (posted, same, may_run) in res["menus"].items():
        assert posted == [] and same and not may_run, name
    assert res["fade"] and res["title_again"]
    assert res["end"] == ([], 0)


# --- AC-F14-22 — saves and auto-saves while rolled back ------------------------------------------

def slot_state(game: Path, slot: SlotId):
    read = saves.read_slot_full(game / "saves", slot, game_id=ss.GAME_ID)
    return read.state if read.status is SlotStatus.OK else None


def auto_states(game: Path) -> list:
    """The Auto saves' states, oldest ``seq`` first."""
    reads = [saves.read_slot_full(game / "saves", SlotId("auto", n), game_id=ss.GAME_ID)
             for n in range(1, 7)]
    ok = [r for r in reads if r.status is SlotStatus.OK]
    return [r.state for r in sorted(ok, key=lambda r: r.meta.seq)]


CHAPTER = ('image bg a = "#c82800"\nlabel start:\n    scene bg a\n    "L1"\n'
           '    chapter c "H" "T"\n    "L2"\n    "L3"\n    "L4"\n    return\n')


def test_ac22_saves_and_auto_saves_while_rolled_back(tmp_path, scripted_app, unthreaded,
                                                     fake_dt):
    """F5 at B landed from D2 holds k_B; the interval elapses while landed, then forward ×2,
    a matched pick and a matched advance make no Auto save, the first is at S (past the
    remembered path); each landing and match calls ``note_restore`` once, before
    ``saves.update`` that frame; F9 loads B with no room back and nothing ahead; the quit
    auto-save while landed at C holds C. (F18) a chapter crossed back and forward by wheel
    and by click makes one Auto save in all; a back during the card clears the armed
    request (``note_restore``, I-6)."""
    game = k_game(tmp_path, NO_TITLE, saves_="autosave_quit = true\nautosave_choices = false\n"
                  "autosave_interval = 60\nconfirm_quick_load = false\n")

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        spy = Spy(app, out)
        out["spy"] = spy
        k: dict = {}
        out["k"] = k
        yield from go(app, "D2", k)
        wheel(4)                                       # StepBack(4): B
        yield
        yield from settle(app)
        res["at"] = name_at(app)
        post_key(pygame.K_F5)
        yield from frames(4)
        res["quick"] = slot_state(game, SlotId("quick", 1))
        yield from spend(fake_dt, 61.0)                # the interval elapses while landed
        res["timer"] = app.saves.timer
        for _ in range(2):
            wheel(-1)                                  # StepForward(1): C, then M
            yield
            yield from settle(app)
        res["forward"] = name_at(app)
        yield from go(app, "D2")                       # a matched pick, a matched advance
        res["autos_on_path"] = len(auto_states(game))
        yield from go(app, "S", k)                     # the first step past the path
        yield from frames(3)
        res["autos_past"] = auto_states(game)
        post_key(pygame.K_F9)                          # quick-1 (B), no question
        for _ in range(120):
            yield
            if name_at(app) == "B" and ready(app) and app.screens.story_may_run():
                break
        res["loaded"] = (name_at(app), view(app))
        yield from go(app, "M")
        wheel(1)                                       # lands C
        yield
        yield from settle(app)
        res["quit_at"] = (name_at(app), app.story.checkpoint())
        post_quit()
        yield
        post_key(pygame.K_LEFT)
        yield
        post_key(pygame.K_RETURN)
        yield

    out = run(scripted_app, game, script, quits=True)
    res, spy, k = out["res"], out["spy"], out["k"]
    assert res["at"] == "B"
    assert res["quick"] == k["B"] and res["quick"].to_json().keys() == k["B"].to_json().keys()
    assert res["timer"] >= 60 and res["forward"] == "M"
    assert res["autos_on_path"] == 0
    assert [s.position for s in res["autos_past"]] == [k["S"].position]
    assert res["loaded"][0] == "B"
    assert res["loaded"][1].ahead == 0 and not res["loaded"][1].can_back
    assert res["quit_at"][0] == "C" and res["quit_at"][1] == k["C"]
    assert auto_states(game)[-1] == k["C"]
    # note_restore: exactly the frames whose pump landed or matched, once, before update.
    notes = spy.calls("note")
    assert notes == [f for f, _ in spy.changed] and len(set(notes)) == len(notes)
    assert {kind for _, kind in spy.changed} == {"landing", "match"}
    for frame in notes:
        order = [what for f, what in spy.log if f == frame and what in ("note", "update")]
        assert order[:2] == ["note", "update"], frame
    # (F18) a chapter: back across it, forward by wheel, then by click; a back in the card.
    chapter = k_game(tmp_path, NO_TITLE, text=CHAPTER, name="chapter")

    def chapter_script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        for _ in range(300):                           # L1, the card, L2, L3
            if line(app) == "L3" and ready(app):
                break
            if ready(app):
                post_key(pygame.K_SPACE)
            yield
            yield
        yield from frames(4)
        res["first"] = len(auto_states(chapter))
        wheel(2)                                       # back across the chapter: L1
        yield
        yield from settle(app)
        wheel(-1)                                      # forward by wheel: L2 (no card)
        yield
        yield from settle(app)
        yield from frames(4)
        res["wheel"] = (line(app), len(auto_states(chapter)))
        wheel(1)                                       # L1 again
        yield
        yield from settle(app)
        for _ in range(100):                           # click forward: the card plays
            if line(app) == "L2":
                break
            post_key(pygame.K_SPACE)                   # (presses end its phases)
            yield from frames(4)
        yield from frames(4)
        res["click"] = (line(app), len(auto_states(chapter)), app.saves.autosave_pending)
        wheel(1)                                       # L1; then into the card and back
        yield
        yield from settle(app)
        post_key(pygame.K_SPACE)
        for _ in range(60):
            yield
            if app.saves.autosave_pending:
                break
        res["armed"] = app.saves.autosave_pending
        wheel(1)                                       # back during the card: L1
        yield
        yield from settle(app)
        res["cleared"] = (line(app), app.saves.autosave_pending)
        app.saves.request_autosave()                   # I-6: note_restore itself drops it
        armed = app.saves.autosave_pending
        app.saves.note_restore()
        res["note"] = (armed, app.saves.autosave_pending)

    res = run(scripted_app, chapter, chapter_script)["res"]
    assert res["first"] == 1
    assert res["wheel"] == ("L2", 1)
    assert res["click"] == ("L2", 1, False)
    assert res["armed"] is True and res["cleared"] == ("L1", False)
    assert res["note"] == (True, False)


# --- AC-F14-23 — stepping turns skip and auto off -----------------------------------------------

MENU_NO_QUESTION = ('label start:\n    "One."\n    "Two."\n    menu:\n        "Left":\n'
                    '            "L."\n        "Right":\n            "R."\n    "End."\n')


def at_l(app) -> bool:
    return line(app) == "L."


def test_ac23_stepping_turns_skip_and_auto_off(tmp_path, scripted_app, unthreaded):
    """Each landing (back, forward, and at a question-less menu) calls the real F15's
    ``reset`` once, in the pump that released it; a live pick matching the remembered step
    doesn't. Skip on, then a back: off, and still off 5 s later; the same for auto."""
    game = k_game(tmp_path, NO_TITLE + "\n[skip]\nall = true\n", text=MENU_NO_QUESTION)

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        spy = Spy(app, out)
        out["spy"] = spy
        yield from go(app, "", match=at_l)
        rows = []
        for y in (1, 1, -1):                           # the menu, "Two.", the menu again
            since = spy.frame
            wheel(y)
            yield
            yield from settle(app)
            landed = [f for f, kind in spy.changed if f > since and kind == "landing"]
            rows.append((landed, spy.calls("reset", since + 1), choices(app) is not None))
        res["rows"] = rows
        since = spy.frame
        yield from go(app, "", match=at_l)             # the remembered pick
        res["matched"] = ([kind for f, kind in spy.changed if f >= since],
                          spy.calls("reset", since))
        skip_auto = app.skip_auto
        for mode in ("skip", "auto"):
            if mode == "skip":
                skip_auto.toggle_skip()
            else:
                skip_auto.toggle_auto()
            on = skip_auto.skipping if mode == "skip" else skip_auto.auto
            wheel(1)
            yield
            yield from settle(app)
            off = not (skip_auto.skipping or skip_auto.auto)
            yield from frames(300)
            res[mode] = (on, off, not (skip_auto.skipping or skip_auto.auto))
            yield from go(app, "", match=at_l)

    res = run(scripted_app, game, script)["res"]
    for landed, resets, _menu in res["rows"]:
        assert len(landed) == 1 and resets == landed
    assert [r[2] for r in res["rows"]] == [True, False, True]
    assert res["matched"] == (["match"], [])
    assert res["skip"] == (True, True, True) and res["auto"] == (True, True, True)


# --- AC-F14-10, row (F15) — seen-mode skip passes the remembered lines --------------------------

def test_ac10_f15_seen_skip_passes_matched_lines(tmp_path, scripted_app, unthreaded):
    """K@D2, back to B (``ahead`` 4), seen-mode skip on: it passes C (seen) without stopping
    and stops at M; no ``reset`` at the matched arrivals."""
    game = k_game(tmp_path)

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        spy = Spy(app, out)
        yield from go(app, "D2")
        wheel(4)
        yield
        yield from settle(app)
        res["at"] = (name_at(app), view(app).ahead)
        since = spy.frame
        skip_auto = app.skip_auto
        skip_auto.toggle_skip()
        seen: list = []
        for _ in range(200):
            yield
            seen.append((name_at(app), skip_auto.skipping))
            if choices(app) is not None:
                break
        yield from frames(2)
        res["seen"] = seen
        res["end"] = (name_at(app), skip_auto.skipping)
        res["changed"] = [kind for f, kind in spy.changed if f >= since]
        res["resets"] = spy.calls("reset", since)

    res = run(scripted_app, game, script)["res"]
    assert res["at"] == ("B", 4)
    assert ("C", True) in res["seen"]
    assert res["end"] == ("M", False)
    assert res["changed"] == ["match", "match"] and res["resets"] == []


# --- AC-F14-29 — the quick menu's Back ------------------------------------------------------------

def click(app, entry_id: str) -> None:
    found = quick_shown(app)
    item = dict(zip((e.id for e in found.entries), found.layout.items))[entry_id]
    x, y = item.box.center
    pos = (round(x), round(y))
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        pygame.event.post(pygame.event.Event(kind, pos=pos, button=1, touch=False))


def test_ac29_the_quick_menus_back(tmp_path, scripted_app, unthreaded):
    """Back is the pill's first item, ``Back``; disabled exactly while ``can_back`` is False
    (A after New Game, enabled in the frame B arrives; a loaded step; the depth limit; B1,
    C1, C2 of ``walls/``); a click posts ``StepBack(1)``; a click on disabled Back posts
    nothing, no cue, no UI sound. ``steps = 0`` or ``[quick_menu] entries`` without
    ``back``: no item (the pill narrower by its width; the wheel still works); ``[words]
    back``. Also AC-F14-03's and 06's Main Menu rows: Main Menu → title → New Game leaves
    ``[A]``, and ``StepBack(1)`` there releases nothing and adds 1 to ``refused``."""
    game = k_game(tmp_path, "\n[rollback]\nsteps = 3\n",
                  saves_="autosave_quit = false\nautosave_choices = false\n"
                         "confirm_quick_load = false\n")

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from frames(5)
        app.shell.start_new_game()
        yield from started(app)
        spy = Spy(app, out)
        keys = app.rollback_keys
        sounds: list = []
        real_play = app.shell.play_ui
        app.shell.play_ui = lambda token: (sounds.append(token), real_play(token))
        found = quick_shown(app)
        res["first"] = (found.entries[0].id, found.layout.items[0].label)
        res["pill_w"] = found.layout.pill.w
        first = found.layout.items[0]                  # its width: label + 2 × padding
        res["advance"] = first.label_box.w + 2 * found.layout.side_padding
        res["at_A"] = back_entry(app).enabled()
        cues, n_sounds, since = keys.cue.triggers, len(sounds), spy.frame
        click(app, "back")                             # disabled: nothing at all
        yield from frames(3)
        res["disabled_click"] = (spy.rollback_posts(since), keys.cue.triggers - cues,
                                 len(sounds) - n_sounds)
        post_key(pygame.K_SPACE)                       # enabled in the frame B arrives
        for _ in range(10):
            yield
            if name_at(app) == "B":
                break
        res["at_B"] = (name_at(app), back_entry(app).enabled())
        since = spy.frame
        click(app, "back")
        yield
        res["click"] = spy.rollback_posts(since)
        yield from settle(app)
        res["clicked_to"] = (name_at(app), back_entry(app).enabled())
        yield from go(app, "C")                        # a loaded step
        post_key(pygame.K_F5)
        yield from frames(3)
        post_key(pygame.K_F9)
        yield from frames(30)
        yield from settle(app)
        res["loaded"] = (name_at(app), back_entry(app).enabled())
        yield from go(app, "F")                        # the depth limit: back 3 lands D1
        wheel(3)
        yield
        yield from settle(app)
        res["limit"] = (name_at(app), back_entry(app).enabled())
        app.shell.return_to_title()                    # Main Menu → title → New Game
        for _ in range(200):
            yield
            if isinstance(app.screens.top, TitleScreen):
                break
        app.shell.start_new_game()
        yield from frames(2)
        yield from started(app)
        t = app.story.interp.timeline
        res["new_game"] = (name_at(app), list(t.states) == [app.story.checkpoint()],
                           back_entry(app).enabled())
        refused, before = t.refused, app.story.checkpoint()
        app.story.post(StepBack(1))
        yield
        res["refused"] = (t.refused - refused, app.story.checkpoint() is before,
                          name_at(app))

    res = run(scripted_app, game, script)["res"]
    assert res["first"] == ("back", "Back")
    assert res["at_A"] is False and res["disabled_click"] == ([], 0, 0)
    assert res["at_B"] == ("B", True)
    assert res["click"] == [StepBack(1)] and res["clicked_to"] == ("A", False)
    assert res["loaded"] == ("C", False)
    assert res["limit"] == ("D1", False)
    assert res["new_game"] == ("A", True, False)
    assert res["refused"] == (1, True, "A")
    with_back = (res["pill_w"], res["advance"])
    # walls/: B1, C1, C2 disabled, B2 and D2 enabled; [words] back.
    walls = k_game(tmp_path, NO_TITLE + '\n[words]\nback = "Zurück"\n', text=WALLS_TEXT,
                   name="walls")

    def walls_script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        res["label"] = quick_shown(app).layout.items[0].label
        for text in ("B1.", "B2.", "C1.", "C2.", "D2."):
            yield from go(app, "", match=lambda a, t=text: line(a) == t)
            res[text] = back_entry(app).enabled()

    res = run(scripted_app, walls, walls_script)["res"]
    assert res["label"] == "Zurück"
    assert [res[t] for t in ("B1.", "B2.", "C1.", "C2.", "D2.")] == [
        False, True, False, False, True]
    # steps = 0, and entries without back (the wheel still works).
    entries = ('["history", "skip", "auto", "save", "q_save", "q_load", "settings", "hide", '
               '"menu"]')
    for name, config in (("off", NO_TITLE + "\n[rollback]\nsteps = 0\n"),
                         ("entries", NO_TITLE + f"\n[quick_menu]\nentries = {entries}\n")):
        root = k_game(tmp_path, config, name=name)

        def other(app, out):
            res: dict = {}
            out["res"] = res
            yield from started(app)
            spy = Spy(app, out)
            found = quick_shown(app)
            res["ids"] = [e.id for e in found.entries]
            res["pill_w"] = found.layout.pill.w
            yield from go(app, "B")
            since = spy.frame
            wheel(1)
            yield
            res["wheel"] = spy.rollback_posts(since)

        res = run(scripted_app, root, other)["res"]
        assert "back" not in res["ids"], name
        assert abs(with_back[0] - res["pill_w"] - with_back[1]) < 1.0, name
        assert res["wheel"] == ([] if name == "off" else [StepBack(1)]), name


# --- step 5 helpers ----------------------------------------------------------------------------

def fb_px(app, x: float, y: float) -> tuple[int, int, int]:
    """The framebuffer color at canvas point (x, y) (the window is the canvas, 1280×720)."""
    return tuple(app.window.framebuffer().get_at((round(x), round(y))))[:3]


def crop(app, rect: tuple[int, int, int, int], *, blank: tuple | None = None) -> bytes:
    """The framebuffer pixels of ``rect``; ``blank`` (a rect inside it) painted black."""
    part = app.window.framebuffer().subsurface(pygame.Rect(rect)).copy()
    if blank is not None:
        x, y, w, h = blank
        part.fill((0, 0, 0), pygame.Rect(round(x) - rect[0], round(y) - rect[1],
                                         round(w), round(h)))
    return pygame.image.tobytes(part, "RGB")


def close(a: tuple[int, int, int], b: tuple[int, int, int], tol: int = 6) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


class Typing:
    """A typing listener: every ``glyph_shown`` (F06's blips follow these)."""

    def __init__(self) -> None:
        self.glyphs = 0

    def glyph_shown(self, index: int, grapheme: str) -> None:
        self.glyphs += 1

    def pause_started(self, seconds: float) -> None:
        pass

    def waiting(self, kind) -> None:
        pass

    def completed(self, by_press: bool) -> None:
        pass


STAGE_RECT = (200, 0, 1080, 450)              # above the name tab, right of the rewind tag
K9_TEXT = K_TEXT.replace("    menu:\n", "    shake\n    flash\n    menu:\n", 1)


def quick_crop(app) -> bytes:
    found = quick_shown(app)
    pill, back = found.layout.pill, found.layout.items[0].box
    rect = (math.floor(pill.x), math.floor(pill.y), math.ceil(pill.w), math.ceil(pill.h))
    return crop(app, rect, blank=(back.x, back.y, back.w, back.h))


# --- AC-F14-21 — the landing on screen ---------------------------------------------------------

def test_ac21_the_landing_on_screen(tmp_path, scripted_app, unthreaded):
    """App R (K with a shake and a flash before M, 40 cps): C typing 100 ms in → B complete
    with its indicator, no glyph; the stage at a landed B equals the first pass's (from C and
    from D1, hana worried → happy: a cut); D1 → M: choices at full opacity with no fade,
    nothing focused, a click at 100 ms ignored and one at 300 ms picks; F15's indicator gone;
    no shake or flash in any landed frame; no music restart; the quick menu unchanged outside
    Back. Then ``walls/``: a landed fixed menu shows the other choice locked."""
    assert K9_TEXT != K_TEXT
    game = k_game(tmp_path, text=K9_TEXT)
    (game / "audio").mkdir()
    (game / "audio" / "river.ogg").write_bytes(ogg_bytes(30.0))

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        spy = Spy(app, out)
        box = app.textbox
        box.settings.cps = 40
        typing = Typing()
        box.add_listener(typing)
        starts: list = []
        backend = getattr(app.audio, "backend", None)
        if backend is not None:
            real_start = backend.music_start
            backend.music_start = lambda *a, **k: (starts.append(spy.frame),
                                                   real_start(*a, **k))[1]
            for _ in range(120):                           # the river starts (decoded)
                if starts:
                    break
                yield
        yield from go(app, "B")
        for _ in range(60):
            if box.typer.state is TypeState.COMPLETE:
                break
            yield
        yield from frames(3)
        res["first_B"] = crop(app, STAGE_RECT)
        music = len(starts)
        # C typing, 100 ms in.
        post_key(pygame.K_SPACE)
        for _ in range(30):
            yield
            if name_at(app) == "C":
                break
        yield from frames(6)
        res["typing"] = box.typer.state is not TypeState.COMPLETE
        glyphs = typing.glyphs
        wheel(1)
        waited = 0
        while name_at(app) != "B" and waited < 10:
            yield
            waited += 1
        res["C_to_B"] = (waited, box.typer.state is TypeState.COMPLETE,
                         box.indicator_kind(), typing.glyphs - glyphs)
        yield
        res["B_from_C"] = crop(app, STAGE_RECT)
        # On to D1 (the shake and the flash play on the way), then back 3 to B.
        yield from go(app, "D1")
        yield from frames(90)
        wheel(3)
        waited = 0
        while name_at(app) != "B" and waited < 10:
            yield
            waited += 1
        yield
        res["B_from_D1"] = (waited, crop(app, STAGE_RECT))
        # M (the quick menu as a menu shows it: F15's Skip disabled), D1 again; F15's auto
        # on; back to M.
        yield from go(app, "", match=lambda a: choices(a) is not None)
        yield from frames(45)                         # the shake and the flash are over
        res["quick_M_first"] = quick_crop(app)
        yield from go(app, "D1")
        yield from frames(90)
        app.skip_auto.toggle_auto()
        yield
        res["auto_pill"] = app.skip_auto.indicator_right()
        wheel(1)
        landed = []
        menu = None
        for _ in range(10):
            yield
            menu = choices(app)
            if menu is not None:
                break
        effects = app.stage_screen.effects
        for i in range(30):
            landed.append((menu.alpha(), menu.focus, effects.active))
            if i == 0:
                res["f15"] = (app.skip_auto.auto, app.skip_auto.indicator_right())
            if i == 2:                                 # F07 tells F15 of a menu at its first
                res["quick_M"] = quick_crop(app)       # draw, after the quick menu drew
            if i in (5, 17):                           # 100 ms and 300 ms after the landing
                x, y, w, h = menu.layout.buttons[1].rect
                since = spy.frame
                for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                    pygame.event.post(pygame.event.Event(
                        kind, pos=(round(x + w / 2), round(y + h / 2)), button=1, touch=False))
                yield
                res[f"click_{i}"] = [e for f, e in spy.posts if f >= since
                                     and isinstance(e, Choose)]
                if i == 17:
                    break
                continue
            yield
        res["landed"] = landed
        res["fade"] = menu.fade
        res["music"] = (music, len(starts))

    res = run(scripted_app, game, script)["res"]
    assert res["typing"]
    waited, complete, indicator, glyphs = res["C_to_B"]
    assert waited <= 2 and complete and indicator == "line" and glyphs == 0
    assert res["B_from_C"] == res["first_B"]
    assert res["B_from_D1"][0] <= 2 and res["B_from_D1"][1] == res["first_B"]
    assert res["auto_pill"] is not None and res["f15"] == (False, None)
    assert res["fade"] == 0
    assert all(alpha == 1.0 and focus is None and not active
               for alpha, focus, active in res["landed"][:5])
    assert all(not active for _, _, active in res["landed"])
    assert res["quick_M"] == res["quick_M_first"]
    assert res["click_5"] == [] and len(res["click_17"]) == 1
    assert res["music"] == (1, 1)                  # the river, once: no landing restarts it
    # walls/: a landed fixed menu, with [choice] show_locked false (the default).
    walls = k_game(tmp_path, text=WALLS_TEXT, name="walls")

    def walls_script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        yield from go(app, "", match=lambda a: line(a) == "Y1.")
        wheel(1)
        for _ in range(10):
            yield
            menu = choices(app)
            if menu is not None:
                break
        res["states"] = (menu.states(), menu.alpha())

    res = run(scripted_app, walls, walls_script)["res"]
    assert res["states"] == (["normal", "locked"], 1.0)


# --- AC-F14-31 — the limit cue: look and placement ---------------------------------------------

MARK_FILL, MARK_BORDER, MARK_GLYPH = (0xFF, 0xE6, 0xF0), (0xF0, 0xA0, 0xC0), (0xA0, 0x28, 0x60)
MENU_FIRST = ('label start:\n    menu:\n' + "".join(
    f'        "Choice {n}":\n            "Picked {n}."\n' for n in range(1, 7))
    + '    "End."\n    return\n')


def test_ac31_limit_cue_look_and_placement(tmp_path, scripted_app, unthreaded, caplog):
    """The drawn mark (a small surface), then App R with reduced motion: the pill at (1088,
    504) in its colors, never in a save thumbnail or the game menu's backdrop; a menu as the
    first step with ``choice.width = 900``: the mark over a choice button; at text size 150%
    the anchor is y 472. Theme rows: an image, a missing image (W64), a pale glyph (W67), an
    out-of-range ``bump_height``, a missing ``limit_sound``."""
    # The drawn mark at scale 1: pill fill, border, bar, gap, triangle.
    cue = LimitCue()
    mark = cue.mark_surface((56, 28), 1.0)
    at = lambda x, y: tuple(mark.get_at((x, y)))[:3]          # noqa: E731
    assert at(6, 14) == MARK_FILL and at(28, 0) == MARK_BORDER and at(28, 1) == MARK_BORDER
    assert at(28, 7) == MARK_GLYPH and at(28, 10) == MARK_FILL and at(28, 19) == MARK_GLYPH
    assert at(18, 7) == MARK_GLYPH and at(17, 7) == MARK_FILL and at(37, 7) == MARK_GLYPH
    assert tuple(mark.get_at((0, 0)))[3] < 255                 # radius 14: a round corner
    # App R, reduced motion (no bump, the indicator at rest): placement and captures.
    game = k_game(tmp_path, NO_TITLE + "\n[effects]\nreduce = true\n")

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        yield from frames(5)
        thumbs: list = []
        app.shell.capture_scene(thumbs.append)
        yield from frames(2)
        post_key(pygame.K_ESCAPE)
        yield from frames(4)
        res["backdrop0"] = pygame.image.tobytes(app.shell.game_menu().scene_picture(), "RGB")
        post_key(pygame.K_ESCAPE)
        yield from frames(4)
        keys = app.rollback_keys
        wheel(1)                                       # at A: refused
        yield from frames(4)
        res["anchor"] = (keys.cue.anchor(), keys.cue.active)
        res["px"] = [fb_px(app, x, y) for x, y in
                     ((1068, 504), (1088, 490), (1088, 497), (1088, 500), (1088, 509))]
        app.shell.capture_scene(thumbs.append)
        yield
        res["thumbs"] = [pygame.image.tobytes(t, "RGB") for t in thumbs]
        wheel(1)
        yield
        post_key(pygame.K_ESCAPE)                      # the game menu while the mark shows
        yield from frames(4)
        res["backdrop1"] = pygame.image.tobytes(app.shell.game_menu().scene_picture(), "RGB")
        res["ended"] = keys.cue.active

    res = run(scripted_app, game, script)["res"]
    assert res["anchor"] == ((1088, 504), True)
    fill, border, bar, gap, tri = res["px"]
    assert close(fill, MARK_FILL) and close(border, MARK_BORDER) and close(bar, MARK_GLYPH)
    assert close(gap, MARK_FILL) and close(tri, MARK_GLYPH)
    assert len(res["thumbs"]) == 2 and res["thumbs"][0] == res["thumbs"][1]
    assert res["backdrop0"] == res["backdrop1"] and res["ended"] is False
    # A menu first (back refused), choices 900 wide: the mark over a button; then 150%.
    menu_game = k_game(tmp_path, NO_TITLE + "\n[theme.choice]\nwidth = 900\n",
                       text=MENU_FIRST, name="menu")

    def menu_script(app, out):
        res: dict = {}
        out["res"] = res
        for _ in range(200):
            yield
            menu = choices(app)
            if menu is not None and menu.past_guard:
                break
        res["under"] = menu.layout.hit((1068, 512))
        wheel(1)
        yield from frames(16)                          # the bump is over
        res["px"] = fb_px(app, 1068, 512)
        app.textbox.settings.text_size = 42            # 150%, from the next line
        post_key(pygame.K_1)
        for _ in range(30):
            yield
            if line(app) == "Picked 1.":
                break
        res["150"] = (app.textbox.geometry.box[3], app.textbox.cue_anchor())

    res = run(scripted_app, menu_game, menu_script)["res"]
    assert res["under"] is not None
    assert close(res["px"], MARK_FILL)
    assert res["150"] == (216, (1088, 472))
    # Theme rows.
    root = tmp_path / "themed"
    (root / "gui").mkdir(parents=True)
    picture = pygame.Surface((40, 20))
    picture.fill((0, 200, 0))
    pygame.image.save(picture, str(root / "gui" / "mark.png"))
    assets = make_assets(GamePaths.for_game(root))

    def themed(**mark) -> UiTheme:
        cfg = dataclasses.replace(ThemeConfig(), rollback=dataclasses.replace(
            RollbackTheme(), mark=dataclasses.replace(RollbackMarkTheme(), **mark)))
        return resolve_theme(dataclasses.replace(Config(), theme=cfg), assets)

    harness = UiHarness(TestShell(assets=assets), window=(320, 180))
    canvas = harness.canvas
    canvas.bind(harness.framebuffer, harness.viewport, harness.quality)

    class Box_:
        box_shown = True

        def cue_anchor(self):
            return (1088.0, 504.0)

        def set_bump(self, dy):
            pass

        def reduce_motion(self):
            return True

    def drawn_images(theme) -> list:
        cue = LimitCue(Box_(), theme=theme)
        cue.trigger()
        cue.update(1 / 60, covered=False, reduce_motion=True)
        cue.update(1 / 60, covered=False, reduce_motion=True)
        calls: list = []
        with pytest.MonkeyPatch.context() as mp:
            real = Canvas.draw_image
            mp.setattr(Canvas, "draw_image", lambda self, image, pos, **kw: (
                calls.append((image.ref, pos, kw.get("anchor"))), real(self, image, pos, **kw)))
            cue.draw(canvas)
        return calls

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert drawn_images(themed(image="gui/mark.png")) == [
            ("gui/mark.png", (1088.0, 504.0), "center")]
        assert drawn_images(themed(image="gui/nope.png")) == []
    w64 = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W64"]
    assert w64 == ['config.toml: [theme.rollback.mark] image "gui/nope.png" doesn\'t exist, '
                   "so the drawn limit mark is used."]
    pale = plain_theme(dataclasses.replace(ThemeConfig(), rollback=dataclasses.replace(
        RollbackTheme(), mark=RollbackMarkTheme(glyph_color=(0xF0, 0xC0, 0xD0)))))
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        warn_contrast(pale, dev=True)
        warn_contrast(pale, dev=False)
        warn_contrast(plain_theme(), dev=True)
    w67 = [r.getMessage() for r in caplog.records if getattr(r, "code", None) == "W67"]
    assert len(w67) == 1 and w67[0].startswith(
        "config.toml: [theme.rollback.mark] glyph_color #F0C0D0 is hard to see on fill_color "
        "#FFE6F0")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "config.toml").write_text("[theme.rollback]\nbump_height = 13\n", encoding="utf-8")
    result = load_config(GamePaths.for_game(bad))
    assert len(result.errors) == 1 and result.config.theme.rollback.bump_height == 6
    assert "[theme.rollback] bump_height must be a whole number from 0 to 12" in \
        result.errors[0].format()

    def trace(sound):
        played: list = []
        cfg = dataclasses.replace(ThemeConfig(), rollback=dataclasses.replace(
            RollbackTheme(), limit_sound=sound))
        cue = LimitCue(Box_(), theme=plain_theme(cfg), play=played.append)
        cue.trigger()
        rows = []
        for _ in range(40):
            cue.update(1 / 60, covered=False, reduce_motion=False)
            rows.append((cue.active, cue.visible, cue.opacity, cue.dy))
        return rows, played

    silent, none = trace(None)
    missing, played = trace("missing.ogg")
    assert none == [] and played == ["missing.ogg"] and missing == silent
