"""F05 step 6 — the textbox screen in App A (``06-acceptance.md`` §0.2): input, one advance
per line, hide and show, ``{next}``, live settings, restore, nothing new saved, and the
typing cost guard. AC-F05-07, 08 (on screen), 18, 19, 20, 21, 22, 35, 36, 46 (counts and
CI median), and C2 (e)–(f). Step 8: AC-F05-23 (focus freeze, I-4), 24 (gamepad, I-15), 37
(seams), and F07's ``tab_top``.

Every run is a real ``App`` loop (``tests/fakes/text_app.py``): a ``FakeWindow``, 1/60 s
frames, the F05 template game in ``tmp_path``. Times are ± 1 frame.
"""

import ast
import json
import logging
import statistics
import sys
import time
from pathlib import Path

import pygame
import pytest

from engine.app import bootstrap
from engine.render.textbox import TextboxView
from engine.render.textlayout import LineLayout
from engine.render.typewriter import TypeState
from engine.runtime.commands import Advance
from engine.script.texttags import Span
from engine.ui.builtin.stage_screen import StageScreen
from engine.ui.builtin.textbox_screen import TextboxScreen
from engine.ui.input import UiEvent
from engine.ui.screen import Screen
from tests.fakes.text_app import Session, make_text_game

pytestmark = pytest.mark.display

REPO = Path(__file__).resolve().parents[2]
FPS = 60
LONG = "a" * 40                                   # 40 graphemes: 1.0 s at 40 cps


def session(tmp_path, *, size=(1280, 720), **game) -> Session:
    return Session(make_text_game(tmp_path / "game", **game), size=size)


def advances(s: Session) -> list[Advance]:
    return [event for _, event in s.posted]


def wait_complete(s: Session):
    yield from s.until(lambda: s.textbox is not None and s.textbox.typer is not None
                       and s.textbox.typer.state is TypeState.COMPLETE)


def darkest(s: Session, rect) -> tuple[int, int, int]:
    """The darkest pixel (by channel sum) of the last frame inside window ``rect``."""
    x0, y0, w, h = rect
    best = None
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            color = s.px(x, y)
            if best is None or sum(color) < sum(best):
                best = color
    return best


def glyph_rect(s: Session, first: int, end: int) -> tuple[int, int, int, int]:
    """Canvas = window rect (1280×720) around glyphs ``first``..``end`` − 1 of the page."""
    tb = s.textbox
    page = tb.layout.page(tb.typer.page)
    ax, ay = tb.geometry.area[:2]
    for line in page.lines:
        glyphs = [g for g in line.glyphs if first <= g.index < end]
        if glyphs:
            left = ax + glyphs[0].x
            right = ax + glyphs[-1].right
            return round(left), round(ay + line.top), round(right - left), line.pitch
    raise AssertionError("no such glyphs on the page")


def close(a, b, tol=2) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b))


# --- AC-F05-21 — one advance per line, shown in the frame it arrives (C2 e, f) ----------------

def test_ac21_the_textbox_replaces_the_stand_in(tmp_path):
    assert not (REPO / "engine" / "ui" / "builtin" / "standin.py").exists()
    s = session(tmp_path, S=LONG)
    seen = {}

    def script(s):
        yield from s.until_line(LONG)
        seen["screens"] = bootstrap.in_game_screens(s.app)
        seen["types"] = [type(x) for x in s.app.screens]

    s.play(script)
    assert seen["types"] == [StageScreen, TextboxScreen]
    assert seen["screens"] == [s.app.stage_screen, s.app.textbox]
    assert TextboxScreen.in_game and not TextboxScreen.opaque


@pytest.mark.parametrize("cps", [40, 0])
def test_ac21_glyph_0_or_page_0_in_the_arrival_frame(tmp_path, monkeypatch, cps):
    s = session(tmp_path, S="a\\nb\\nc\\nd", config=f"[textbox]\ncps = {cps}\n")
    drawn = []
    real = TextboxView.draw_typed

    def draw_typed(self, canvas, page, line_id, shown, geometry, **fx):
        drawn.append((s.frame, page.index, shown))
        real(self, canvas, page, line_id, shown, geometry, **fx)

    monkeypatch.setattr(TextboxView, "draw_typed", draw_typed)

    def script(s):
        yield from s.until(lambda: s.said)
        yield

    s.play(script)
    arrival = s.said[0][0]
    first = [d for d in drawn if d[0] == arrival]
    assert first, "nothing drawn in the arrival frame"
    assert first[0][1] == 0
    assert first[0][2] == (1 if cps else 3)        # glyph 0; at cps 0 all of page 0 (a b c)


def test_ac21_presses_while_typing_and_after_the_advance_post_nothing(tmp_path):
    s = session(tmp_path, S="ab{pause=0.6}cd{pause}ef" + "g" * 30)
    notes = {}

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        s.key(pygame.K_SPACE)                      # typing (in the timed pause or before)
        yield
        yield from s.until(lambda: s.textbox.typer.state is TypeState.WAIT_CLICK)
        notes["at_wait"] = list(s.posted)
        s.key(pygame.K_SPACE)                      # continue
        yield
        s.key(pygame.K_SPACE)                      # typing again: completes
        yield
        yield from wait_complete(s)
        notes["before"] = list(s.posted)
        for _ in range(6):                         # the one advance, then five more presses
            s.key(pygame.K_SPACE)                  # before the next Say (same frame's pump)
        yield
        yield from s.until_line("End.")
        yield

    s.play(script)
    assert notes["at_wait"] == [] and notes["before"] == []
    line_sid = s.said[0][1].sid
    assert advances(s) == [Advance(line_sid)]
    assert all(type(event) is Advance for _, event in s.posted)


# --- AC-F05-20 — advance inputs ---------------------------------------------------------------

IN = (640, 360)


@pytest.mark.parametrize("inject, expected", [
    (lambda s: s.mouse(IN, 1), 1),
    (lambda s: s.key(pygame.K_SPACE), 1),
    (lambda s: s.key(pygame.K_RETURN), 1),
    (lambda s: s.key(pygame.K_KP_ENTER), 1),
    (lambda s: s.mouse(IN, 1, up=True), 0),
    (lambda s: s.key_up(pygame.K_SPACE), 0),
    (lambda s: s.mouse(IN, 3), 0),
    (lambda s: s.mouse(IN, 4), 0),
    (lambda s: s.mouse(IN, 5), 0),
    (lambda s: s.event(pygame.MOUSEWHEEL, x=0, y=-1, flipped=False), 0),
    (lambda s: s.key(pygame.K_ESCAPE), 0),
    (lambda s: s.key(pygame.K_a), 0),
    (lambda s: s.key(pygame.K_TAB), 0),
    (lambda s: s.event(pygame.MOUSEMOTION, pos=IN, rel=(0, 0), buttons=(0, 0, 0)), 0),
], ids=["click", "space", "return", "kp-enter", "click-up", "space-up", "right", "wheel-4",
        "wheel-5", "wheel", "esc", "a", "tab", "motion"])
def test_ac20_advance_inputs(tmp_path, inject, expected):
    s = session(tmp_path, S="x")

    def script(s):
        yield from wait_complete(s)
        inject(s)
        yield
        yield
        yield

    s.play(script)
    assert len(advances(s)) == expected


def test_ac20_a_click_in_a_letterbox_bar_does_nothing(tmp_path):
    s = session(tmp_path, S="x", size=(1600, 720))

    def script(s):
        yield from wait_complete(s)
        s.mouse((50, 360), 1)
        yield
        yield
        s.mouse((800, 360), 1)                     # inside the canvas: advances
        yield
        yield

    s.play(script)
    assert len(advances(s)) == 1


def test_ac20_key_repeat_stays_off(tmp_path):
    s = session(tmp_path, S="x")

    def script(s):
        yield from wait_complete(s)
        assert pygame.key.get_repeat() == (0, 0)
        s.key(pygame.K_SPACE)
        yield from s.until_line("End.")
        yield from wait_complete(s)
        s.key(pygame.K_SPACE)
        yield
        yield

    s.play(script)
    assert pygame.key.get_repeat() == (0, 0)
    for path in (REPO / "engine").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "set_repeat" not in source:              # parse only the files that could match
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute):
                assert node.attr != "set_repeat", path


# --- AC-F05-22 — hide and show -----------------------------------------------------------------

def test_ac22_hide_freezes_and_show_returns_the_same_box(tmp_path):
    s = session(tmp_path, S=LONG)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        for _ in range(12):                        # 0.2 s
            yield
        seen["typed"] = s.snapshot()
        s.key(pygame.K_h)
        yield
        seen["hidden_shown"] = s.textbox.typer.shown
        seen["hidden_frame"] = s.snapshot()
        for _ in range(120):                       # 2 s
            yield
        seen["after_2s"] = s.textbox.typer.shown
        s.key(pygame.K_SPACE)                      # shows the box only
        yield
        seen["back"] = s.snapshot()
        seen["back_shown"] = s.textbox.typer.shown
        for _ in range(6):
            yield
        seen["resumed"] = s.textbox.typer.shown

    s.play(script)
    black = bytes(1280 * 720 * 3)
    assert seen["hidden_frame"] == black            # the stage-only frame (empty stage)
    assert seen["after_2s"] == seen["hidden_shown"]
    assert seen["back_shown"] == seen["hidden_shown"]
    assert seen["back"] != black and seen["resumed"] > seen["back_shown"]
    assert advances(s) == []


@pytest.mark.parametrize("hide, show", [
    (lambda s: s.mouse(IN, 2), lambda s: s.mouse(IN, 2)),
    (lambda s: s.key(pygame.K_h, pygame.KMOD_LSHIFT), lambda s: s.key(pygame.K_h)),
    (lambda s: s.key(pygame.K_h), lambda s: s.mouse(IN, 1)),
], ids=["middle-click", "shift-h", "click-shows"])
def test_ac22_other_hide_and_show_inputs(tmp_path, hide, show):
    s = session(tmp_path, S="x")
    seen = {}

    def script(s):
        yield from wait_complete(s)
        hide(s)
        yield
        seen["hidden"] = s.textbox.hidden
        show(s)
        yield
        seen["shown"] = not s.textbox.hidden

    s.play(script)
    assert seen == {"hidden": True, "shown": True}
    assert advances(s) == []


@pytest.mark.parametrize("mod", [pygame.KMOD_LCTRL, pygame.KMOD_LALT, pygame.KMOD_LMETA])
def test_ac22_h_with_ctrl_alt_or_meta_does_nothing(tmp_path, mod):
    s = session(tmp_path, S="x")
    seen = {}

    def script(s):
        yield from wait_complete(s)
        s.key(pygame.K_h, mod)
        yield
        seen["hidden"] = s.textbox.hidden

    s.play(script)
    assert seen["hidden"] is False


def test_ac22_a_hidden_complete_line_shows_its_indicator_at_rest(tmp_path):
    s = session(tmp_path, S="x")
    seen = {}

    def script(s):
        yield from wait_complete(s)
        for _ in range(20):
            yield
        seen["bob_before"] = s.textbox._bob_t
        s.key(pygame.K_h)
        yield
        s.key(pygame.K_h)
        yield
        seen["bob_after"] = s.textbox._bob_t

    s.play(script)
    assert seen["bob_before"] > 0.2
    assert seen["bob_after"] <= 1 / FPS + 1e-9      # restarted at rest on show


# --- AC-F05-19 — {next} --------------------------------------------------------------------------

NEXT_SCRIPT = ('define hana = Character("Hana")\ndefine d = Character("Daichi", color="#1e4a9c")\n'
               'label start:\n    d "it\'s a paper bag with a candle in i—{0}{{next}}"\n'
               '    hana "LOOK!"\n')


def _states(s: Session, log: list):
    while True:
        tb = s.textbox
        if tb is not None and tb.typer is not None:
            log.append((s.frame, tb.line.text, tb.typer.state))
        yield


def test_ac19_next_advances_in_the_frame_after_completion(tmp_path, monkeypatch):
    s = session(tmp_path, script=NEXT_SCRIPT.format(""))
    indicators = []
    real = TextboxView.draw_indicator

    def draw_indicator(self, canvas, page, line_id, shown, geometry, **kw):
        indicators.append(s.textbox.line.text)
        real(self, canvas, page, line_id, shown, geometry, **kw)

    monkeypatch.setattr(TextboxView, "draw_indicator", draw_indicator)

    def script(s):
        log = []
        states = _states(s, log)
        while s.line_text() != "LOOK!":
            next(states)
            yield
        s.log = log

    s.play(script)
    first_line = s.said[0][1]
    completed = min(f for f, text, state in s.log
                    if text == first_line.text and state is TypeState.COMPLETE)
    assert s.posted[0] == (completed, Advance(first_line.sid))
    assert first_line.text not in indicators


def test_ac19_a_press_while_typing_shows_the_indicator_and_waits(tmp_path):
    s = session(tmp_path, script=NEXT_SCRIPT.format(""))
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        s.key(pygame.K_SPACE)                      # completes
        yield
        for _ in range(30):
            yield
        seen["posted"] = list(s.posted)
        seen["indicator"] = s.textbox.indicator_kind()
        s.key(pygame.K_SPACE)
        yield
        yield

    s.play(script)
    assert seen["posted"] == [] and seen["indicator"] == "line"
    assert len(s.posted) == 1


def test_ac19_a_pause_before_next_delays_the_advance(tmp_path):
    s = session(tmp_path, script=NEXT_SCRIPT.format("{pause=0.5}"))

    def script(s):
        log = []
        states = _states(s, log)
        while s.line_text() != "LOOK!":
            next(states)
            yield
        s.log = log

    s.play(script)
    first = s.said[0][1].text
    paused = min(f for f, text, state in s.log if text == first and state is TypeState.PAUSED)
    # PAUSED is first seen the frame after the last glyph showed; the advance 0.5 s later.
    gap = s.posted[0][0] - (paused - 1)
    assert abs(gap - 0.5 * FPS) <= 2


# --- AC-F05-18 — speed and size changed on screen ------------------------------------------------

def _completion_time(s: Session, change=None) -> float:
    out = {}

    def script(s):
        yield from s.until(lambda: s.said)
        arrival = s.said[0][0]
        while s.textbox.typer.state is not TypeState.COMPLETE:
            if change is not None:
                change(s, (s.frame - arrival) / FPS)
            yield
        out["t"] = (s.frame - 1 - arrival) / FPS

    s.play(script)
    return out["t"]


def test_ac18_cps_changed_mid_line(tmp_path):
    def change(s, t):
        if t >= 0.5:
            s.textbox.settings.cps = 80

    s = session(tmp_path, S=LONG)
    assert abs(_completion_time(s, change) - 0.75) <= 1.5 / FPS


def test_ac18_settings_cps_from_the_start_with_a_speed_tag(tmp_path):
    s = session(tmp_path, S="{speed=0.5}" + "a" * 10 + "{/speed}")

    def change(s, t):
        s.textbox.settings.cps = 80

    # The first frame types with config cps 40 for 0 s (the arrival adds no time).
    assert abs(_completion_time(s, change) - 0.25) <= 1.5 / FPS


def test_ac18_instant_mid_line_keeps_timed_pauses(tmp_path):
    s = session(tmp_path, S="a" * 20 + "{pause=0.5}" + "b" * 20)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        for _ in range(6):
            yield
        s.textbox.settings.instant = True
        yield
        seen["state"] = s.textbox.typer.state
        seen["shown"] = s.textbox.typer.shown
        start = s.frame
        yield from wait_complete(s)
        seen["waited"] = (s.frame - start) / FPS

    s.play(script)
    assert seen["shown"] == 20 and seen["state"] is TypeState.PAUSED
    assert abs(seen["waited"] - 0.5) <= 2 / FPS


def test_ac18_text_size_applies_from_the_next_line(tmp_path):
    s = session(tmp_path, S=LONG)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        s.textbox.settings.text_size = 42
        yield
        seen["first"] = (s.textbox.geometry.top, s.textbox.layout.ctx.text_size)
        s.key(pygame.K_SPACE)
        yield
        s.key(pygame.K_SPACE)
        yield from s.until_line("End.")
        seen["next"] = (s.textbox.geometry.top, s.textbox.layout.ctx.text_size)
        s.textbox.settings.text_size = None
        s.textbox.settings.cps = None

    s.play(script)
    assert seen["first"] == (504, 28)
    assert seen["next"] == (472, 42)


# --- AC-F05-07, 08 — styles and plain names on screen ----------------------------------------------

def test_ac07_text_colors_on_screen(tmp_path):
    s = session(tmp_path, D='thought "Do {i}they{/i} {color=#9a1c14}swim{/color}?"⏎    hana "Plain."')
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        yield from wait_complete(s)
        yield
        seen["swim"] = darkest(s, glyph_rect(s, 8, 12))
        s.key(pygame.K_SPACE)
        yield from s.until_line("Plain.")
        yield from wait_complete(s)
        yield
        seen["plain"] = darkest(s, glyph_rect(s, 0, 6))

    s.play(script)
    assert close(seen["swim"], (0x9A, 0x1C, 0x14))
    assert close(seen["plain"], (0x3D, 0x2B, 0x36))


def test_ac08_a_name_with_braces_is_drawn_as_written(tmp_path, monkeypatch):
    from tests.fakes.draw_spy import spy_draw_text

    s = session(tmp_path, D='r "Hi."', T='define r = Character(name_from="nm")⏎default nm = "{b}Ren{/b}"')
    with spy_draw_text(monkeypatch) as calls:
        def script(s):
            yield from s.until_line("Hi.")
            yield

        s.play(script)
    assert s.said[0][1].name == "{b}Ren{/b}"
    names = [c for c in calls if c.text == "{b}Ren{/b}"]
    assert names and names[0].font.bundled.value == "bold"


# --- AC-F05-35 — a restored line appears complete ------------------------------------------------

RESTORE = ('define hana = Character(name_from="hana_name")\ndefault hana_name = "???"\n'
           'label start:\n    hana "One{pause} two\\nb\\nc\\nd\\ne\\nf\\ng"\n'
           '    $ hana_name = "Hana"\n    hana "Next."\n    "End."\n')


@pytest.mark.parametrize("where", ["page2", "click-wait"])
def test_ac35_a_restored_line_shows_complete_on_its_last_page(tmp_path, where):
    s = session(tmp_path, script=RESTORE)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        state = s.app.story.checkpoint()
        tb = s.textbox
        if where == "page2":
            s.key(pygame.K_SPACE)                  # complete to the click-wait
            yield
            s.key(pygame.K_SPACE)                  # continue
            yield
            s.key(pygame.K_SPACE)                  # complete page 1 to its break
            yield
            s.key(pygame.K_SPACE)                  # page 2
            yield
            assert tb.typer.page == 1
        else:
            yield from s.until(lambda: tb.typer.state is TypeState.WAIT_CLICK)
        tb.press()
        tb.typer.complete_all()
        tb.press()                                 # the advance
        yield from s.until_line("Next.")
        yield
        outcome = s.app.story.restore(state)
        assert outcome.result.name == "OK"
        yield
        seen["page"] = tb.typer.page
        seen["state"] = tb.typer.state
        seen["shown"] = (tb.typer.shown, tb.layout.glyph_count)
        seen["events"] = tb.typer.take_events()
        seen["name"] = tb.line.name
        seen["restored"] = tb.line.restored
        seen["indicator"] = tb.indicator_kind()
        before = len(s.posted)
        s.key(pygame.K_SPACE)
        yield
        seen["advanced"] = s.posted[before:]

    s.play(script)
    assert seen["restored"] and seen["page"] == 2 and seen["state"] is TypeState.COMPLETE
    assert seen["shown"][0] == seen["shown"][1] and seen["events"] == []
    assert seen["name"] == "???" and seen["indicator"] == "line"
    assert [event for _, event in seen["advanced"]] == [Advance(s.said[0][1].sid)]


def test_ac35_a_restored_next_line_waits_for_a_press(tmp_path):
    s = session(tmp_path, script=NEXT_SCRIPT.format(""))
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        state = s.app.story.checkpoint()
        yield from s.until_line("LOOK!")
        s.app.story.restore(state)
        yield from s.until(lambda: s.textbox.line.restored)
        before = len(s.posted)
        for _ in range(30):
            yield
        seen["posted"] = s.posted[before:]
        seen["indicator"] = s.textbox.indicator_kind()

    s.play(script)
    assert seen["posted"] == [] and seen["indicator"] == "line"


# --- AC-F05-36 — nothing new is saved -------------------------------------------------------------

def test_ac36_the_checkpoint_is_the_same_in_every_presentation_state(tmp_path):
    s = session(tmp_path, script=RESTORE)
    snaps = []

    def snap(s):
        snaps.append(json.dumps(s.app.story.checkpoint().to_json(), sort_keys=True))

    def script(s):
        yield from s.until(lambda: s.said)
        snap(s)                                    # arrival
        yield
        snap(s)                                    # typing
        yield from s.until(lambda: s.textbox.typer.state is TypeState.WAIT_CLICK)
        snap(s)
        s.key(pygame.K_SPACE)
        yield
        s.key(pygame.K_h)
        yield
        snap(s)                                    # hidden
        s.key(pygame.K_h)
        yield
        s.textbox.typer.complete_all()
        yield
        snap(s)                                    # page 3, complete

    s.play(script)
    assert len(set(snaps)) == 1
    assert json.loads(snaps[0])["format"] == 1


# --- AC-F05-46 — CI guard for typing cost -----------------------------------------------------------

def test_ac46_steady_typing_frames_build_nothing(tmp_path, monkeypatch):
    # The quick menu is off: its labels are F10's cached text lines (AC-F10-67), drawn each
    # frame by the textbox's overlay, not F05's glyphs.
    s = session(tmp_path, S=" ".join(["lanterns"] * 30), size=(1920, 1080),
                config="[textbox]\ncps = 1000\n[quick_menu]\nenabled = false\n")
    counts = {"build": 0, "text_line": 0, "place": 0, "width": 0}
    frames = []
    real_build = TextboxView.build_glyphs
    real_place = LineLayout._place
    real_width = LineLayout._width

    def build(self, *args):
        counts["build"] += 1
        return real_build(self, *args)

    def place(self, k):
        counts["place"] += 1
        return real_place(self, k)

    def width(self, a, b):
        counts["width"] += 1
        return real_width(self, a, b)

    monkeypatch.setattr(TextboxView, "build_glyphs", build)
    monkeypatch.setattr(LineLayout, "_place", place)
    monkeypatch.setattr(LineLayout, "_width", width)
    real_update, real_draw = TextboxScreen.update, TextboxScreen.draw
    work, pending = [], [0.0]

    def update(self, dt, *, is_top):
        t = time.perf_counter()
        real_update(self, dt, is_top=is_top)
        pending[0] = time.perf_counter() - t

    def draw(self, canvas):
        t = time.perf_counter()
        real_draw(self, canvas)
        work.append(pending[0] + time.perf_counter() - t)
        pending[0] = 0.0

    monkeypatch.setattr(TextboxScreen, "update", update)
    monkeypatch.setattr(TextboxScreen, "draw", draw)
    text_line = s.assets.text_line

    def spy_text_line(*args):
        counts["text_line"] += 1
        return text_line(*args)

    s.assets.text_line = spy_text_line

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        while s.textbox.typer.state is TypeState.TYPING:
            frames.append(dict(counts))
            yield
        frames.append(dict(counts))

    s.play(script)
    steady = list(zip(frames, frames[1:]))[1:]
    assert len(steady) >= 5
    for before, after in steady:
        assert after == before, (before, after)
    assert statistics.median(work[-len(steady):]) <= 0.002


# --- F05 step 8: AC-F05-23 — typing freezes when covered or unfocused ------------------------------

class Cover(Screen):
    """An opaque test screen (not in_game: the story holds under it)."""

    opaque = True


class Recorder:
    """A ``TypingListener`` that records ``(frame, kind, arg)``."""

    def __init__(self, s: Session) -> None:
        self.s = s
        self.log: list[tuple[int, str, object]] = []

    def glyph_shown(self, index, grapheme):
        self.log.append((self.s.frame, "glyph", (index, grapheme)))

    def pause_started(self, seconds):
        self.log.append((self.s.frame, "pause", seconds))

    def waiting(self, kind):
        self.log.append((self.s.frame, "waiting", kind.value))

    def completed(self, by_press):
        self.log.append((self.s.frame, "completed", by_press))

    def kinds(self, start: int = 0) -> list[str]:
        return [kind for _, kind, _ in self.log[start:]]


def _focus(s: Session, gained: bool) -> None:
    s.event(pygame.WINDOWFOCUSGAINED if gained else pygame.WINDOWFOCUSLOST, window=None)


@pytest.mark.parametrize("cover", ["screen", "focus"])
@pytest.mark.parametrize("text", [LONG, "x"], ids=["typing", "complete"])
def test_ac23_typing_and_bob_freeze_while_covered_or_unfocused(tmp_path, cover, text):
    s = session(tmp_path, S=text)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        tb = s.textbox
        for _ in range(12):                        # 0.2 s
            yield
        screen = Cover()
        if cover == "screen":
            s.app.screens.push(screen)             # covers it from this frame's update
        else:
            _focus(s, False)
        yield
        seen["at"] = (tb.typer.shown, tb.typer._acc, tb._bob_t)
        frozen = []
        for _ in range(120):                       # 2 s
            frozen.append((tb.typer.shown, tb.typer._acc, tb._bob_t))
            yield
        seen["frozen"] = frozen
        if cover == "screen":
            assert s.app.screens.pop() is screen
        else:
            _focus(s, True)                        # no press needed (G8)
        yield                                      # the frame of the pop / focus gain
        seen["resumed"] = (tb.typer.shown, tb.typer._acc, tb._bob_t)

    s.play(script)
    assert set(seen["frozen"]) == {seen["at"]}
    shown, acc, bob = seen["at"]
    if text == LONG:                               # typing time flows again at once
        assert 0 < shown < len(LONG)
        assert (seen["resumed"][0], seen["resumed"][1]) != (shown, acc)
    else:
        assert bob > 0 and seen["resumed"][2] > bob
    assert advances(s) == []


def test_ac23_focus_changes_under_a_pushed_screen_do_not_leave_the_box_frozen(tmp_path):
    # I-4: WINDOWFOCUS* reach only the top screen; the box reads App.focused instead.
    s = session(tmp_path, S=LONG)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        tb = s.textbox
        yield
        _focus(s, False)                           # lost while the textbox is top
        yield
        screen = Cover()
        s.app.screens.push(screen)
        _focus(s, True)                            # gained while the cover is top
        yield
        s.app.screens.pop()
        yield
        before = tb.typer.shown
        for _ in range(6):
            yield
        seen["moved"] = tb.typer.shown > before
        s.app.screens.push(screen)
        _focus(s, False)                           # lost under the cover
        yield
        s.app.screens.pop()
        yield
        before = tb.typer.shown
        for _ in range(6):
            yield
        seen["still"] = tb.typer.shown == before
        _focus(s, True)
        yield
        yield
        seen["after_gain"] = tb.typer.shown > before

    s.play(script)
    assert seen == {"moved": True, "still": True, "after_gain": True}


def test_ac23_a_frozen_timed_pause_keeps_its_remaining_time(tmp_path):
    # ab{pause=0.6}cd at 40 cps: frozen 0.3 s into the pause, `c` shows 0.3 s after resuming.
    s = session(tmp_path, S="ab{pause=0.6}cd")
    rec = Recorder(s)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.textbox is not None)
        s.textbox.add_listener(rec)
        yield from s.until(lambda: "pause" in rec.kinds())
        start = rec.log[rec.kinds().index("pause")][0]
        while s.frame < start + 19:                # 18 frames (0.3 s) of pause pass
            yield
        _focus(s, False)
        for _ in range(120):
            yield
        seen["frozen_glyphs"] = [x for x in rec.log if x[1] == "glyph" and x[2][0] >= 2]
        _focus(s, True)
        seen["resume"] = s.frame                   # this frame's update is the first again
        yield from s.until(lambda: any(x[1] == "glyph" and x[2][0] == 2 for x in rec.log))

    s.play(script)
    assert seen["frozen_glyphs"] == []
    c_frame = next(f for f, kind, arg in rec.log if kind == "glyph" and arg[0] == 2)
    assert abs((c_frame - seen["resume"] + 1) - 18) <= 1     # 0.3 s ± 1 frame


# --- AC-F05-24 — gamepad --------------------------------------------------------------------------

def _pad_added(s: Session) -> None:
    s.event(pygame.CONTROLLERDEVICEADDED, device_index=0, guid="")


def _pad(s: Session, button: int) -> None:
    s.event(pygame.CONTROLLERBUTTONDOWN, button=button, instance_id=0)


@pytest.mark.parametrize("button, advanced, hidden", [
    (pygame.CONTROLLER_BUTTON_A, 1, False),
    (pygame.CONTROLLER_BUTTON_Y, 0, True),
    (pygame.CONTROLLER_BUTTON_B, 0, False),
], ids=["A", "Y", "B"])
def test_ac24_gamepad_buttons_on_a_complete_line(tmp_path, button, advanced, hidden):
    s = session(tmp_path, S="x")
    seen = {}

    def script(s):
        _pad_added(s)
        yield from wait_complete(s)
        _pad(s, button)
        yield
        seen["hidden"] = s.textbox.hidden
        yield
        yield

    s.play(script)
    assert len(advances(s)) == advanced
    assert seen["hidden"] is hidden
    # B is not F05's (03 "Interaction": F10's game menu); the textbox never reads it.
    if button == pygame.CONTROLLER_BUTTON_B:
        raw = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=button, instance_id=0)
        assert TextboxScreen._input_kind(UiEvent(raw, None, False)) is None


def test_ac24_gamepad_a_completes_typing_like_space_and_y_shows_the_box(tmp_path):
    s = session(tmp_path, S=LONG)
    seen = {}

    def script(s):
        _pad_added(s)
        yield from s.until(lambda: s.said)
        yield
        _pad(s, pygame.CONTROLLER_BUTTON_A)        # completes, no advance
        yield
        seen["state"] = s.textbox.typer.state
        _pad(s, pygame.CONTROLLER_BUTTON_Y)
        yield
        seen["hidden"] = s.textbox.hidden
        _pad(s, pygame.CONTROLLER_BUTTON_A)        # only shows the box
        yield
        seen["shown_again"] = not s.textbox.hidden
        seen["posted"] = len(s.posted)
        _pad(s, pygame.CONTROLLER_BUTTON_A)        # the advance
        yield
        yield

    s.play(script)
    assert seen == {"state": TypeState.COMPLETE, "hidden": True, "shown_again": True,
                    "posted": 0}
    assert len(advances(s)) == 1


def _no_controller_module(monkeypatch) -> None:
    import pygame._sdl2 as sdl2

    monkeypatch.setitem(sys.modules, "pygame._sdl2.controller", None)
    monkeypatch.delattr(sdl2, "controller", raising=False)


def test_ac24_without_the_controller_module_one_line_and_keyboard_and_mouse_work(
        tmp_path, monkeypatch, caplog):
    _no_controller_module(monkeypatch)
    s = session(tmp_path, S="x")

    def script(s):
        _pad_added(s)
        yield
        _pad_added(s)
        yield from wait_complete(s)
        s.key(pygame.K_SPACE)
        yield from s.until_line("End.")
        yield from wait_complete(s)
        s.mouse(IN, 1)
        yield
        yield

    with caplog.at_level(logging.DEBUG, logger="vn"):
        assert s.play(script) == 0
    pad_lines = [r.getMessage() for r in caplog.records if "amepad" in r.getMessage()]
    assert len(pad_lines) == 1 and pad_lines[0].startswith("Gamepads are off")
    assert len(advances(s)) == 2


def test_ac24_only_app_input_imports_the_controller_module():
    # I-15: F10 builds on the same Controllers; nothing else opens devices.
    found = []
    for path in (REPO / "engine").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "controller" not in source:              # parse only the files that could match
            continue
        for node in ast.walk(ast.parse(source)):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [f"{node.module}.{a.name}" for a in node.names] + [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any(n.startswith("pygame._sdl2.controller") for n in names):
                found.append(path.relative_to(REPO).as_posix())
    assert found == ["engine/app/input.py"]


# --- AC-F05-37 — seams for later features ---------------------------------------------------------

PAGED = "One{pause} two\\nb\\nc\\nd\\ne\\nf\\ng"
LANTERN = "I saw it... the lantern moved."
SEAMS = ('define hana = Character("Hana")\nlabel start:\n'
         '    hana "I saw it... {pause=0.6}the {b}{color=#e05050}lantern{/color}{/b} moved."\n'
         f'    "{PAGED}"\n    "{LONG}"\n    "End."\n')


def test_ac37_typing_and_say_listeners(tmp_path):
    s = session(tmp_path, script=SEAMS)
    rec = Recorder(s)
    says: list = []
    seen = {}

    def script(s):
        yield from s.until(lambda: s.textbox is not None)
        s.textbox.add_listener(rec)
        s.textbox.add_say_listener(lambda cmd: says.append(cmd))
        yield from s.until(lambda: s.said)
        state = s.app.story.checkpoint()
        yield from wait_complete(s)
        seen["line1"] = list(rec.log)
        s.key(pygame.K_SPACE)
        yield from s.until(lambda: s.textbox.line.text.startswith("One"))
        mark = len(rec.log)
        yield from s.until(lambda: s.textbox.typer.state is TypeState.WAIT_CLICK)
        s.key(pygame.K_SPACE)                      # continue
        yield
        yield from s.until(lambda: s.textbox.typer.state is TypeState.WAIT_PAGE)
        seen["waits"] = [arg for _, kind, arg in rec.log[mark:] if kind == "waiting"]
        s.textbox.complete_now()
        s.key(pygame.K_SPACE)                      # the advance
        yield from s.until_line(LONG)
        for _ in range(6):
            yield
        mark = len(rec.log)
        s.key(pygame.K_SPACE)                      # mid-line press
        for _ in range(60):
            yield
        seen["after_press"] = rec.log[mark:]
        s.app.story.restore(state)
        yield from s.until(lambda: s.textbox.line.restored)
        seen["last"] = rec.log[-1][1:]
        yield

    s.play(script)
    arrival = s.said[0][0]
    line1 = seen["line1"]
    glyphs = [(f, arg) for f, kind, arg in line1 if kind == "glyph"]
    assert [g for _, (_, g) in glyphs] == list(LANTERN)
    assert [i for _, (i, _) in glyphs] == list(range(len(LANTERN)))
    for frame, (i, _) in glyphs:                   # AC-F05-16 times, ± 1 frame
        expected = 0.025 * i + (0.6 if i >= 12 else 0.0)
        assert expected - 1e-6 <= (frame - arrival) / FPS <= expected + 1 / FPS + 1e-6, i
    pauses = [(f, arg) for f, kind, arg in line1 if kind == "pause"]
    assert len(pauses) == 1 and pauses[0][1] == 0.6
    assert abs((pauses[0][0] - arrival) / FPS - 0.300) <= 1 / FPS + 1e-6
    assert [arg for _, kind, arg in line1 if kind == "completed"] == [False]
    assert seen["waits"] == ["click", "page"]
    assert [x[1:] for x in seen["after_press"]] == [("completed", True)]
    # Each Say once, the restored one included.
    assert says == [cmd for _, cmd in s.said]
    assert [cmd.restored for cmd in says] == [False, False, False, True]
    assert says[-1].text == says[0].text
    assert seen["last"] == ("completed", True)     # a restored line arrives complete
    plain = says[0].body.plain()
    assert all(isinstance(span, Span) for span in plain)
    assert "".join(span.text for span in plain) == LANTERN
    lantern = [span for span in plain if span.text == "lantern"]
    assert len(lantern) == 1 and lantern[0].style.bold
    assert lantern[0].style.color.lower() == "#e05050"


def test_ac37_complete_now_shows_the_last_page_complete(tmp_path):
    s = session(tmp_path, S=PAGED)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        yield
        tb = s.textbox
        tb.complete_now()
        seen["now"] = (tb.typer.page, tb.layout.all_pages(), tb.typer.state,
                       tb.typer.shown == tb.layout.glyph_count, tb.indicator_kind())
        yield
        yield
        seen["posted"] = len(s.posted)
        tb.complete_now()                          # already complete: nothing
        tb.press()                                 # F15's advance path
        yield
        yield

    s.play(script)
    page, pages, state, all_shown, indicator = seen["now"]
    assert pages >= 2 and page == pages - 1
    assert state is TypeState.COMPLETE and all_shown and indicator == "line"
    assert seen["posted"] == 0 and len(advances(s)) == 1


def test_ac37_set_hidden_behaves_as_h(tmp_path):
    s = session(tmp_path, S=LONG)
    seen = {}

    def script(s):
        yield from s.until(lambda: s.said)
        for _ in range(12):
            yield
        tb = s.textbox
        tb.set_hidden(True)
        yield
        seen["hidden_frame"] = s.snapshot()
        shown = tb.typer.shown
        for _ in range(60):
            yield
        seen["frozen"] = tb.typer.shown == shown
        tb.set_hidden(False)
        yield
        seen["back"] = s.snapshot()
        for _ in range(6):
            yield
        seen["resumed"] = tb.typer.shown > shown

    s.play(script)
    assert seen["hidden_frame"] == bytes(1280 * 720 * 3)
    assert seen["frozen"] and seen["resumed"]
    assert seen["back"] != seen["hidden_frame"]
    assert advances(s) == []


def test_f07_tab_top_follows_the_text_size(tmp_path):
    s = session(tmp_path, S="x")
    seen = {}

    def script(s):
        yield from wait_complete(s)
        tb = s.textbox
        seen["default"] = tb.tab_top()
        seen["drawn"] = tb.view.name_tab("Hana", tb.geometry).rect[1]
        tb.settings.text_size = 36
        seen["36"] = tb.tab_top()

    s.play(script)
    # 03-ui.md's diagram: tab top 462 (F07 04 §5.3 says 460; F05's geometry wins).
    assert seen["default"] == 462 == seen["drawn"]
    assert seen["36"] < seen["default"]
