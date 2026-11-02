"""F29 step 3 — the say window's effect clock, typing, reduce motion, and restores
(``04-technical.md`` §7.3–§7.5, §7.7; ``06-acceptance.md`` AC-F29-11, 12, 13, 14;
``07-architecture-review.md`` I-3, I-4, I-5, I-7).

``TextboxScreen`` runs by hand, one frame at a time (``show`` when a line arrives, then
``update(1/60)`` and ``draw``), on the bundled fonts at 1280×720. Its app is a stand-in with
``story.post``, ``focused``, and ``screens.story_may_run()`` (the overlays' freeze rule), so a
game menu (``may_run`` False, not top), F07's choices (``may_run`` True, not top), hiding, and
focus loss are each one flag. Bodies are hand-built until F29 step 2's tags exist
(``tests/fakes/fx_text.py``); each run is compared with the same text without effect tags.
Frame 0 is a line's arrival frame; ``FxSpy`` records each draw's effect ``blits`` list (None:
no effect pass).

AC-F29-14's rows that need F29 step 2's tags in a real script (F13's history text, F11's
quick-save across a relaunch, F15's skip and auto) run Template T in the real app (the
``app_*`` rows, at the end), beside the seam rows (a restored ``Say``, ``complete_now``, the
typing listeners).
"""

import math
import re
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from engine.core.config_schema import Config
from engine.persist import writer as writer_mod
from engine.render import nvl as nvl_mod
from engine.render import textbox as textbox_mod
from engine.render.canvas import Canvas
from engine.render.textbox import TextboxView, fx_blits
from engine.render.textfx import FxTime, glitch_pick, h, line_seed, shake_unit, \
    u, wave_unit
from engine.render.textlayout import BUNDLED_FACES
from engine.render.typewriter import TypeState
from engine.runtime.commands import Advance
from engine.ui.builtin.history_page import HistoryPage
from engine.ui.builtin.textbox_screen import TextboxScreen, TextSettings
from tests.app.test_nvl_saves import quick_load, quick_save, restored_at
from tests.app.test_saves_service import launch, line_text, play, wait
from tests.app.test_ui_flow import _click
from tests.fakes.fx_text import FxSpy, bind, real_assets, say
from tests.fakes.loop import post_key

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]

DT = 1 / 60
L4 = "I'm {wave}so{/wave} happy you came today!"
L5 = "{shake=small}I just... {pause=0.6}{speed=0.2}don't{/speed} want you to leave.{/shake}"
L6 = "{glitch=large}You're not going anywhere.{/glitch}"
L7 = "My name is {glitch}Hana{/glitch}."
L14 = "{speed=0.2}It was... {/speed}{speed=instant}{shake=large}GONE.{/shake}{/speed}"
SIDS = {L4: "main/4", L5: "main/5", L6: "main/6", L7: "main/7", L14: "main/14"}


class Listener:
    def __init__(self, box: "Box") -> None:
        self.box = box
        self.events: list[tuple] = []

    def glyph_shown(self, index, grapheme):
        self.events.append((self.box.frame, "glyph", index, grapheme))

    def pause_started(self, seconds):
        self.events.append((self.box.frame, "pause", seconds))

    def waiting(self, kind):
        self.events.append((self.box.frame, "wait", kind))

    def completed(self, by_press):
        self.events.append((self.box.frame, "completed", by_press))


class Box:
    """One ``TextboxScreen`` driven frame by frame."""

    def __init__(self, monkeypatch, *, cps=40, config: Config | None = None) -> None:
        self.assets = real_assets()
        self.canvas = Canvas(self.assets)
        bind(self.canvas, (1280, 720))
        config = config if config is not None else Config()
        view = TextboxView(self.assets, config.theme.textbox, BUNDLED_FACES.for_style(True, False))
        self.posted: list[tuple[int, object]] = []
        self.may_run = True
        self.is_top = True
        self.frame = -1
        screens = SimpleNamespace(story_may_run=lambda: self.may_run)
        story = SimpleNamespace(post=lambda event: self.posted.append((self.frame, event)))
        self.app = SimpleNamespace(story=story, focused=True, screens=screens)
        self.tb = TextboxScreen(self.app, config, view, BUNDLED_FACES)
        self.tb.settings = TextSettings(cps=cps)
        self.listener = Listener(self)
        self.tb.add_listener(self.listener)
        self.spy = FxSpy(monkeypatch)

    def show(self, text, *, effects=True, restored=False, sid=None):
        self.frame += 1
        self.tb.show(say(text, sid or SIDS.get(text, "main/x"), effects=effects,
                         restored=restored))
        return self.run(advance_frame=False)

    def run(self, *, advance_frame=True):
        """One frame: update then draw; the frame's effect blits."""
        if advance_frame:
            self.frame += 1
        self.tb.update(DT, is_top=self.is_top)
        self.tb.draw(self.canvas)
        return self.spy.take()

    def frames(self, n, press_waits=False):
        out = []
        for _ in range(n):
            if press_waits and self.tb.typer.state in (TypeState.WAIT_CLICK,
                                                       TypeState.WAIT_PAGE):
                self.tb.press()
            out.append(self.run())
        return out

    @property
    def draw(self):
        tb = self.tb
        return tb.view._glyphs(self.canvas, tb.layout.page(tb.typer.page), tb._line_id,
                               tb.geometry)

    def expected(self, t, *, still=False):
        draw, out = self.draw, []
        if still:
            draw.prepare_still(self.tb._fx_seed)
        k = sum(1 for i in draw.fx_indices if i < self.tb.typer.shown)
        fx_blits(draw.fx[:k], FxTime(t, still), self.tb._fx_seed, out)
        return out

    def rest(self):
        return [(g.surface, g.dest) for g in self.draw.fx]


def _symbols(box, blits):
    return {surface for surface, _ in blits} - {g.surface for g in box.draw.fx}


# --- AC-F29-11 — typing, completion, and blips ----------------------------------------------------

def _wave450():
    words = "".join(f"w{n % 10}xy " for n in range(90))          # 450 graphemes, words of 5
    return words[:30] + "{wave}" + words[30:420] + "{/wave}" + words[420:]


AC11_ROWS = ["L6_typing", "press_at_0.2", "L5_pause", "next", "L14", "instant", "wave450",
             "blips", "indicator"]


@pytest.mark.parametrize("row", AC11_ROWS)
def test_ac_f29_11_typing_completion_and_blips(row, monkeypatch):
    box = Box(monkeypatch, cps=0 if row in ("instant", "wave450") else 40)
    if row == "L6_typing":
        blits, frames = box.show(L6), 0
        while True:
            fx_shown = [i for i in box.draw.fx_indices if i < box.tb.typer.shown]
            assert len(blits or []) == len(fx_shown)
            if box.tb.typer.state is TypeState.COMPLETE:
                break
            blits, frames = box.run(), frames + 1
        assert frames > 20 and len(blits) == 23
    elif row == "press_at_0.2":
        box.show(L6)
        box.frames(12)
        assert box.tb.typer.state is TypeState.TYPING
        box.tb.press()
        blits = box.run()
        assert box.tb.typer.state is TypeState.COMPLETE and len(blits) == 23
        later = [box.run() for _ in range(7)]                    # the next 0.12 s
        assert any(set(b) != set(blits) for b in later)
    elif row == "L5_pause":
        box.show(L5)
        paused = []
        for _ in range(200):
            blits = box.run()
            if box.tb.typer.state is TypeState.PAUSED:
                paused.append((box.tb._fx_t, box.tb.typer.shown, blits))
        assert len(paused) >= 30
        assert len({shown for _, shown, _ in paused}) == 1
        for (t0, _, a), (t1, _, b) in zip(paused, paused[1:]):
            if math.floor(t1 / 0.05) != math.floor(t0 / 0.05):
                assert a != b, t1                                # a new pose at each step
    elif row == "next":
        frames = []
        for effects in (True, False):
            box = Box(monkeypatch)
            box.show("{wave}Wait{/wave}{next}", effects=effects)
            box.frames(40)
            box.show("x")
            frames.append([(f, e) for f, e in box.posted if isinstance(e, Advance)])
        assert frames[0] == frames[1] and frames[0]
    elif row == "L14":
        box.show(L14)
        seen = []
        for _ in range(120):
            blits = box.run()
            seen.append((box.tb.typer.shown, blits))
        gone = [(shown, b) for shown, b in seen if b]
        assert all(len(b) == 5 for _, b in gone)                 # "GONE." in one frame
        shown, blits = gone[-1]
        t, seed = box.tb._fx_t, box.tb._fx_seed
        for g in box.draw.fx:
            ux, uy = shake_unit(g.index, t, seed)
            x, y = g.dest
            assert (g.surface, (x + round(4 * ux), y + round(4 * uy))) in blits
    elif row == "instant":
        blits = box.show(L6)
        assert box.tb.typer.state is TypeState.COMPLETE and len(blits) == 23
        blits = box.frames(30)[-1]
        assert blits == box.expected(box.tb._fx_t) and _symbols(box, blits)
    elif row == "wave450":
        box.show(_wave450())
        assert box.tb.typer.state is TypeState.WAIT_PAGE
        box.tb.press()
        box.frames(5)
        blits = box.run()
        page = box.tb.layout.page(box.tb.typer.page)
        assert box.tb.typer.page >= 1 and page.first_glyph > 0
        t = box.tb._fx_t
        for g in box.draw.fx:
            assert g.index >= page.first_glyph                   # the line's index
            x, y = g.dest
            assert (g.surface, (x, y + round(-3.5 * wave_unit(g.index, t)))) in blits
    elif row == "blips":
        runs = []
        for effects in (True, False):
            box = Box(monkeypatch)
            box.show(L6, effects=effects)
            box.frames(80)
            runs.append(box.listener.events)
        assert runs[0] == runs[1] and len(runs[0]) > 20
    else:                                                        # indicator, L4–L7
        runs = []
        for effects in (True, False):
            box = Box(monkeypatch)
            trace = []
            for text in (L4, L5, L6, L7):
                box.show(text, effects=effects)
                for _ in range(150):
                    tb = box.tb
                    page = tb.layout.page(tb.typer.page)
                    trace.append((tb.indicator_kind(), tb.view.indicator_anchor(
                        page, tb._line_id, tb.typer.shown, tb.geometry)))
                    box.run()
            runs.append(trace)
        assert runs[0] == runs[1]


# --- AC-F29-12 — the effect clock -----------------------------------------------------------------

AC12_ROWS = ["steady", "game_menu", "hidden", "focus", "next_line", "rollback", "choices"]


@pytest.mark.parametrize("row", AC12_ROWS)
def test_ac_f29_12_the_effect_clock(row, monkeypatch):
    box = Box(monkeypatch, cps=0)
    tb = box.tb
    blits = box.show(L6)
    assert tb._fx_t == 0.0 and blits == box.expected(0.0)
    assert tb._fx_seed == line_seed("main/6")
    if row == "steady":
        for f in range(1, 121):
            blits = box.run()
            assert tb._fx_t == pytest.approx(f / 60, abs=1e-9)
            assert blits == box.expected(tb._fx_t)
        return
    if row == "next_line":
        box.frames(30)
        blits = box.show(L7)
        assert tb._fx_t == 0.0 and blits == box.expected(0.0)
        assert tb._fx_seed == line_seed("main/7")
        return
    if row == "rollback":
        runs = []
        for _ in range(2):
            box.show(L5)
            box.frames(20, press_waits=True)
            runs.append([box.show(L6)] + box.frames(120))
            box.show(L5, restored=True)                          # rolled back
            box.frames(3)
        assert runs[0] == runs[1]
        return
    if row == "choices":                                         # I-5: F07's choices on top
        box.frames(30)
        box.is_top = False
        held = [box.run() for _ in range(30)]
        assert tb._fx_t == pytest.approx(60 / 60)
        assert len({tuple(b) for b in held}) > 1                 # still moving
        return
    box.frames(30)
    frame30 = box.run()
    t30 = tb._fx_t
    assert t30 == pytest.approx(31 / 60)
    for _ in range(60):
        if row == "game_menu":
            box.may_run, box.is_top = False, False
        elif row == "hidden":
            tb.set_hidden(True)
        else:
            box.app.focused = False
        blits = box.run()
        assert tb._fx_t == t30
        if row == "hidden":
            assert blits is None                                 # nothing drawn
        else:
            assert blits == frame30                              # poses held
    box.may_run, box.is_top, box.app.focused = True, True, True
    tb.set_hidden(False)
    box.run()
    assert tb._fx_t == pytest.approx(32 / 60)                    # the clock resumes


# --- AC-F29-13 — reduce motion --------------------------------------------------------------------

def _quiet_sid() -> str:
    """A sid whose seed makes neither glyph of ``{glitch=small}ab`` a symbol at step 0."""
    for n in range(1000):
        seed = line_seed(f"main/q{n}")
        if all(glitch_pick(i, 0.0, seed, 0.10, True) < 0 for i in (0, 1)):
            return f"main/q{n}"
    raise AssertionError("no quiet sid")


AC13_ROWS = ["settings", "config", "toggle", "typing", "I-4_minimum", "I-4_spaces"]


@pytest.mark.parametrize("row", AC13_ROWS)
def test_ac_f29_13_reduce_motion(row, monkeypatch):
    if row == "config":
        config = Config()
        config = replace(config, effects=replace(config.effects, reduce=True))
        box = Box(monkeypatch, cps=0, config=config)
    else:
        box = Box(monkeypatch, cps=40 if row == "typing" else 0)
    tb = box.tb
    if row in ("settings", "config"):
        if row == "settings":
            tb.settings.reduce_motion = True
        assert tb.reduce_motion()
        for text in (L4, L5, L6, L14):
            box.show(text)
            tb.complete_now()
            frames = box.frames(120)
            assert all(b == frames[0] for b in frames)           # no change between frames
            if text == L6:
                seed = line_seed("main/6")
                for g in box.draw.fx:
                    k = glitch_pick(g.index, 0, seed, 0.5, False)
                    assert (g.subs[k] if k >= 0 else (g.surface, g.dest)) in frames[0]
            else:
                assert frames[0] == box.rest()                   # shake and wave at rest
        return
    if row == "toggle":
        box.show(L6)
        box.frames(40)
        tb.settings.reduce_motion = True
        blits = box.run()                                        # frame 41
        assert blits == box.expected(0.0, still=True) == box.expected(5.0, still=True)
        box.frames(58)
        tb.settings.reduce_motion = False
        blits = box.run()                                        # frame 100
        assert tb._fx_t == pytest.approx(100 / 60) and blits == box.expected(tb._fx_t)
        return
    if row == "typing":
        runs = []
        for reduce in (False, True):
            box = Box(monkeypatch)
            box.tb.settings.reduce_motion = reduce
            box.show(L5)
            box.frames(200, press_waits=True)
            runs.append(box.listener.events)
        assert runs[0] == runs[1]
        return
    tb.settings.reduce_motion = True
    if row == "I-4_spaces":
        assert box.show("x{glitch}   {/glitch}y") is None         # no glyph, no symbol
        assert box.draw.fx == [] and box.draw.runs == []
        return
    sid = _quiet_sid()
    seed = line_seed(sid)
    blits = box.show("{glitch=small}ab{/glitch}", sid=sid)
    symbols = [(s, d) for s, d in blits if (s, d) not in box.rest()]
    assert len(symbols) == 1                                     # exactly one, frozen
    pick = min((0, 1), key=lambda i: (u(h(i, 0, 3, seed)), i))
    g = box.draw.fx[pick]
    assert g.still_sub >= 0 and symbols[0] == g.subs[g.still_sub]
    assert all(b == blits for b in box.frames(30))
    tb.settings.reduce_motion = False                            # moving: the plain picks
    assert all(set(b) <= set(box.rest()) | {s for g in box.draw.fx for s in g.subs}
               for b in box.frames(5))


# --- AC-F29-14 — restore, skip, auto, and old lines -----------------------------------------------

AC14_ROWS = ["quick_load", "rollback", "skip", "auto", "no_effects", "app_history",
             "app_quick_save_relaunch", "app_skip", "app_auto"]


@pytest.mark.parametrize("row", AC14_ROWS)
def test_ac_f29_14_restore_skip_and_auto(row, monkeypatch, tmp_path, request):
    if row.startswith("app_"):
        _APP_ROWS[row](tmp_path, request.getfixturevalue("scripted_app"), monkeypatch)
        return
    box = Box(monkeypatch)
    tb = box.tb
    if row in ("quick_load", "rollback"):
        if row == "rollback":
            box.show(L6)
            box.frames(50)
        blits = box.show(L6, restored=True)
        assert tb.typer.state is TypeState.COMPLETE and tb._fx_t == 0.0
        assert len(blits) == 23 and blits == box.expected(0.0)
        frames = box.frames(6)
        assert tb._fx_t == pytest.approx(0.1) and frames[-1] == box.expected(tb._fx_t)
        assert frames[0] == box.expected(1 / 60)                 # posed from the next frame
        return
    if row == "skip":
        for text in (L4, L5, L6, L7, L14):
            box.show(text)
            tb.complete_now()
            blits = box.run()
            assert tb.typer.state is TypeState.COMPLETE
            assert len(blits) == len(box.draw.fx) > 0
        return
    if row == "auto":
        runs = []
        for effects in (True, False):
            box = Box(monkeypatch)
            for text in (L4, L5, L6, L7):
                box.show(text, effects=effects)
                box.frames(150, press_waits=True)
            runs.append([e for e in box.listener.events if e[1] in ("completed", "pause",
                                                                     "wait")])
        assert runs[0] == runs[1] and len(runs[0]) >= 4
        return
    blits = box.show(L4, effects=False, restored=True)           # a save from before F29
    assert blits is None and box.draw.fx == [] and box.draw.runs == []
    assert all(b is None for b in box.frames(10))


# --- AC-F29-14 — the App rows (F29 step 2: Template T in the real app, 06 G10) ---------------------
# Each run is an in-process ``launch()`` of Template T (``tests/fixtures/F29/template``, 06 §0.3;
# T′ without its effect tags) under ``scripted_app`` (fake clock at 1/60 s, hidden 1280×720
# window, dev, unthreaded writer). ``_AppDraws`` wraps the textbox's ``draw`` and counts the
# effect passes (``fx_blits`` in ``render.textbox`` and ``render.nvl``) of each draw.

T_DIR = REPO / "tests" / "fixtures" / "F29" / "template"
FX_TAG = re.compile(r"\{/?(?:shake|wave|glitch)(?:=[a-z]*)?\}")
T_L7 = "My name is {glitch}{var=hana_name}{/glitch}."
APP_CONFIG = ('[game]\nid = "f29-app"\ntitle = "F29"\nversion = "1.0"\n\n[title]\n'
              "enabled = false\n\n[saves]\nautosave_quit = false\n")
HISTORY_4 = [("I'm so happy you came today!",), ("I just... don't want you to leave.",),
             ("You're not going anywhere.",), ("My name is Hana.",)]


def _t_game(root, *, plain=False, config=""):
    shutil.copytree(T_DIR, root)
    main = root / "script" / "main.vns"
    if plain:
        main.write_text(FX_TAG.sub("", main.read_text(encoding="utf-8")), encoding="utf-8")
    (root / "config.toml").write_text(APP_CONFIG + config, encoding="utf-8")
    return root


class _AppDraws:
    """Per textbox draw: ``(frame, sid, complete, effect passes)``."""

    def __init__(self, monkeypatch) -> None:
        self.mp = monkeypatch
        self.calls = 0
        self.draws: list[tuple[int, str | None, bool, int]] = []
        for module in (textbox_mod, nvl_mod):
            real = module.fx_blits

            def spy(glyphs, fx, seed, out, real=real):
                self.calls += 1
                real(glyphs, fx, seed, out)

            monkeypatch.setattr(module, "fx_blits", spy)

    def install(self, app, frame) -> None:
        tb = app.textbox
        real = tb.draw

        def draw(canvas):
            before = self.calls
            real(canvas)
            self.draws.append((frame(), tb.line.sid if tb.line else None,
                               tb.typer is not None and tb.typer.state is TypeState.COMPLETE,
                               self.calls - before))

        self.mp.setattr(tb, "draw", draw)


def _press_until(app, done):
    """Space every 4 frames, once the shown line waits, until ``done()``."""
    for n in range(3000):
        if done():
            return
        box = app.textbox
        if n % 4 == 0 and box.typer is not None and box.typer.state in (
                TypeState.COMPLETE, TypeState.WAIT_CLICK, TypeState.WAIT_PAGE):
            post_key(pygame.K_SPACE)
        yield
    raise AssertionError("not reached")


def _lines(app) -> dict[str, str]:
    return {s.sid: f"L{s.line}" for s in app.program.iter_statements()}


def _app_history(tmp_path, scripted_app, monkeypatch):
    """History (F13) opened at L7: the four plain texts, drawn as those exact strings; the
    history page makes no effect pass."""
    game = _t_game(tmp_path / "h", config="\n[textbox]\ncps = 0\n")
    fx = _AppDraws(monkeypatch)

    def script(app, out):
        yield from wait(lambda: line_text(app) is not None)
        yield from _press_until(app, lambda: line_text(app) == T_L7)
        texts: list[str] = []
        real = app.assets.text_line
        monkeypatch.setattr(app.assets, "text_line",
                            lambda font, text, color: (texts.append(text),
                                                       real(font, text, color))[1])
        _click(app, "history")
        yield from wait(lambda: isinstance(getattr(app.screens.top, "page", None),
                                           HistoryPage))
        for _ in range(3):
            yield
        calls = fx.calls
        for _ in range(10):
            yield
        page = app.screens.top.page
        out.update(rows=[(r.kind, r.name, r.lines) for r in page.rows], texts=texts,
                   fx=fx.calls - calls)

    out = play(scripted_app, script, last=900)
    assert launch(game) == 0 and out["done"]
    assert out["rows"] == [("line", "Hana", t) if i < 3 else ("line", "", t)
                           for i, t in enumerate(HISTORY_4)]
    assert all(t in out["texts"] for (t,) in HISTORY_4)
    assert out["fx"] == 0


def _app_quick_save_relaunch(tmp_path, scripted_app, monkeypatch):
    """F5 while L6 types, quit, relaunch, F9: L6 complete at t = 0, then 1/60 a frame."""
    monkeypatch.setattr(writer_mod, "WRITER_THREADED", False)
    game = _t_game(tmp_path / "q")

    def save(app, out):
        yield from wait(lambda: line_text(app) is not None)
        yield from _press_until(app, lambda: line_text(app) == L6)
        box = app.textbox
        yield from wait(lambda: box.shown_count() >= 2)
        out["typing"] = box.typer.state is not TypeState.COMPLETE
        yield from quick_save(app, game, 1, out, "cp6")

    def load(app, out):
        yield from wait(lambda: line_text(app) is not None)
        yield from quick_load(app, lambda: restored_at(app, L6))
        box = app.textbox
        out["first"] = (box.typer.state, box._fx_t)
        times, passes = [], 0
        for _ in range(60):
            calls = fx.calls
            yield
            times.append(box._fx_t)
            passes += fx.calls - calls
        out.update(times=times, passes=passes)

    fx = _AppDraws(monkeypatch)
    one = play(scripted_app, save, last=1200)
    assert launch(game) == 0 and one["done"] and one["typing"]
    two = play(scripted_app, load, last=1200)
    assert launch(game) == 0 and two["done"]
    assert two["first"] == (TypeState.COMPLETE, 0.0)
    steps = [round((b - a) * 60, 6) for a, b in zip([0.0] + two["times"], two["times"])]
    assert set(steps) <= {0.0, 1.0} and steps.count(1.0) >= 6   # holds (load fade) or 1/60
    running = [i for i, step in enumerate(steps) if step == 1.0]
    assert two["times"][running[5]] == pytest.approx(0.1)       # the sixth running frame
    assert two["passes"] > 0


def _skip_run(root, scripted_app, monkeypatch):
    fx = _AppDraws(monkeypatch)

    def script(app, out):
        yield from wait(lambda: getattr(app, "skip_auto", None) is not None
                        and line_text(app) is not None)
        monkeypatch.setattr(app.skip_auto, "get_mods", lambda: pygame.KMOD_LCTRL)
        fx.install(app, lambda: out["frame"])
        post_key(pygame.K_LCTRL)
        yield from wait(lambda: line_text(app) == "End.")
        out.update(state=app.story.checkpoint().to_json(), lines=_lines(app))

    out = play(scripted_app, script, last=1500)
    assert launch(root) == 0 and out["done"]
    return out, fx.draws


def _app_skip(tmp_path, scripted_app, monkeypatch):
    """Ctrl held from L4 to L15: each line complete in its first frame; effect lines drawn
    with effect passes; the state at L15 equals T′'s skip run."""
    from tests.runtime.test_textfx_headless import _json

    t, t_draws = _skip_run(_t_game(tmp_path / "t", config="\n[skip]\nall = true\n"),
                           scripted_app, monkeypatch)
    p, _ = _skip_run(_t_game(tmp_path / "p", plain=True, config="\n[skip]\nall = true\n"),
                     scripted_app, monkeypatch)
    firsts: dict[str, tuple[bool, int]] = {}
    passes: dict[str, int] = {}
    for _, sid, complete, n in t_draws:
        if sid is not None:
            firsts.setdefault(sid, (complete, n))
            passes[sid] = passes.get(sid, 0) + n
    names = {t["lines"][sid]: sid for sid in firsts}
    assert set(names) >= {"L5", "L6", "L7", "L9", "L10", "L11", "L12", "L14", "L15"}
    assert all(firsts[names[n]][0] for n in names if n != "L4")   # complete on arrival
    for n in ("L5", "L6", "L7", "L9", "L10", "L11", "L12", "L14"):
        assert passes[names[n]] > 0, n
    assert passes[names["L15"]] == 0
    # Each launch's new game draws its own dice seed; everything else is equal.
    t_state, p_state = (_json({k: v for k, v in run["state"].items() if k != "dice"},
                              run["lines"], []) for run in (t, p))
    assert t_state == p_state


def _auto_run(root, scripted_app):
    def script(app, out):
        yield from wait(lambda: getattr(app, "skip_auto", None) is not None
                        and line_text(app) is not None)
        post_key(pygame.K_a)
        arrivals, last = [], None
        lines = _lines(app)
        while len(arrivals) < 5:
            sid = app.textbox.line.sid if app.textbox.line is not None else None
            if sid != last:
                arrivals.append((out["frame"], lines.get(sid)))
                last = sid
            yield
        out["arrivals"] = arrivals

    out = play(scripted_app, script, last=3000)
    assert launch(root) == 0 and out["done"]
    return out["arrivals"]


def _app_auto(tmp_path, scripted_app, monkeypatch):
    """Auto mode L4–L7: each line's auto delay equals T′'s."""
    fast = "\n[auto]\ndelay = 0\n\n[textbox]\ncps = 80\n"         # fewer frames, same rule
    t = _auto_run(_t_game(tmp_path / "t", config=fast), scripted_app)
    p = _auto_run(_t_game(tmp_path / "p", plain=True, config=fast), scripted_app)
    assert [n for _, n in t] == [n for _, n in p] == ["L4", "L5", "L6", "L7", "L9"]
    assert [b - a for (a, _), (b, _) in zip(t, t[1:])] == \
           [b - a for (a, _), (b, _) in zip(p, p[1:])]


_APP_ROWS = {"app_history": _app_history, "app_quick_save_relaunch": _app_quick_save_relaunch,
             "app_skip": _app_skip, "app_auto": _app_auto}
