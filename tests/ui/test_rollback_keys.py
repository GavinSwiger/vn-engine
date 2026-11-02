"""F14 step 4 — ``RollbackKeys``, the rollback inputs (``04`` §7.7; ``07`` I-2, I-10): AC-F14-18
(one post per frame's notches, presses, or a Back click; the App rows: a wheel in a letterbox
bar, Esc / right click / east open the game menu, and the restore runs in the frame after the
input) and AC-F14-19 (touchpad scrolling adds up to whole notches); step 5's AC-F14-30 (the
limit cue's timing and motion, ``LimitCue`` in App R's frame order on fake ports, 10 ms
frames) and AC-F14-32 (the rewind tag through a test shell's real painter, and F15's
``indicator_right``).

The overlay's rows use fake ports: a story whose view has room both ways and records what is
posted, a textbox with ``hidden``, and a fake game-time clock. The App rows run App S
(``tests/app/test_rollback_install.py``) on Run K.
"""

import dataclasses
from types import SimpleNamespace

import pygame
import pytest

from engine.core.config_schema import RollbackTheme, ThemeConfig
from engine.render.frames import FrameSpec
from engine.runtime.commands import RollbackView, StepBack, StepForward
from engine.ui.builtin import rollback as rollback_mod
from engine.ui.builtin.game_menu import GameMenuScreen
from engine.ui.builtin.rollback import LimitCue, RollbackKeys
from engine.ui.builtin.skip_auto import SkipIndicator
from engine.ui.focus import Box
from engine.ui.input import UiEvent
from engine.ui.theme import measure_with, plain_theme
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.ui_shell import TestShell, UiHarness
from tests.ui.test_skip_auto import unit as skip_unit
from tests.app.test_rollback_install import (NO_TITLE, Spy, frames, go, k_game, run, settle,
                                             started, unthreaded, wheel)
from tests.fakes.loop import post_key

__all__ = ["unthreaded"]                          # the fixture, re-exported for pytest

CTRL, ALT, META = pygame.KMOD_LCTRL, pygame.KMOD_LALT, pygame.KMOD_LMETA
LB = pygame.CONTROLLER_BUTTON_LEFTSHOULDER
RB = pygame.CONTROLLER_BUTTON_RIGHTSHOULDER


class FakeStory:
    def __init__(self, view: RollbackView = RollbackView(True, True, 10, 10, 0)) -> None:
        self.view = view
        self.posted: list = []

    def rollback_view(self) -> RollbackView:
        return self.view

    def post(self, event) -> None:
        self.posted.append(event)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make(view: RollbackView | None = None):
    story = FakeStory(view) if view is not None else FakeStory()
    textbox = SimpleNamespace(hidden=False)
    textbox.set_hidden = lambda hidden: setattr(textbox, "hidden", hidden)
    clock = Clock()
    return RollbackKeys(story, textbox, clock=clock), story, textbox, clock


def ev(kind: int, *, in_canvas: bool = True, **attrs) -> UiEvent:
    return UiEvent(pygame.event.Event(kind, **attrs), None, in_canvas)


def whl(y: float | None = None, *, precise: float | None = None, flipped: bool = False,
        in_canvas: bool = True) -> UiEvent:
    attrs = {"x": 0, "y": int(y if y is not None else 0), "flipped": flipped}
    if precise is not None:
        attrs.update(precise_x=0.0, precise_y=precise)
    elif y is not None:
        attrs.update(precise_x=0.0, precise_y=float(y))
    return ev(pygame.MOUSEWHEEL, in_canvas=in_canvas, **attrs)


def key(k: int, mod: int = 0, *, up: bool = False, repeat: bool | None = None) -> UiEvent:
    attrs = {"key": k, "mod": mod, "unicode": "", "scancode": 0}
    if repeat is not None:
        attrs["repeat"] = repeat
    return ev(pygame.KEYUP if up else pygame.KEYDOWN, **attrs)


def button(b: int, *, up: bool = False) -> UiEvent:
    kind = pygame.CONTROLLERBUTTONUP if up else pygame.CONTROLLERBUTTONDOWN
    return ev(kind, button=b, instance_id=0)


def frame(keys: RollbackKeys, *events: UiEvent) -> list[bool]:
    """One frame: the events, then the update (where the overlay posts)."""
    consumed = [keys.handle_event(e, box_shown=True) for e in events]
    keys.update(1 / 60, frozen=False)
    return consumed


# --- AC-F14-18 — one post per notch, press, or click ----------------------------------------------

@pytest.mark.display
def test_ac18_one_post_per_frame(tmp_path, scripted_app, unthreaded):
    rows = [
        ("wheel up", [whl(1)], [StepBack(1)]),
        ("wheel down", [whl(-1)], [StepForward(1)]),
        ("one event y +3", [whl(3)], [StepBack(3)]),
        ("three y +1", [whl(1), whl(1), whl(1)], [StepBack(3)]),
        ("y +1 and y -1", [whl(1), whl(-1)], []),
        ("Page Up", [key(pygame.K_PAGEUP)], [StepBack(1)]),
        ("Page Down", [key(pygame.K_PAGEDOWN)], [StepForward(1)]),
        ("Ctrl Page Up", [key(pygame.K_PAGEUP, CTRL)], []),
        ("Alt Page Up", [key(pygame.K_PAGEUP, ALT)], []),
        ("Meta Page Up", [key(pygame.K_PAGEUP, META)], []),
        ("KEYUP Page Up", [key(pygame.K_PAGEUP, up=True)], []),
        ("LB", [button(LB)], [StepBack(1)]),
        ("RB", [button(RB)], [StepForward(1)]),
        ("wheel in a letterbox bar", [whl(1, in_canvas=False)], [StepBack(1)]),
    ]
    for name, events, posted in rows:
        keys, story, _, _ = make()
        consumed = frame(keys, *events)
        assert story.posted == posted, name
        if name in ("Ctrl Page Up", "Alt Page Up", "Meta Page Up", "KEYUP Page Up"):
            assert consumed == [False], name               # goes on to the screens below
    # Page Up held 1 s with OS repeats (a repeat flag, or a second KEYDOWN while down).
    keys, story, _, _ = make()
    frame(keys, key(pygame.K_PAGEUP))
    for n in range(59):
        frame(keys, key(pygame.K_PAGEUP, repeat=True) if n % 2 else key(pygame.K_PAGEUP))
    frame(keys, key(pygame.K_PAGEUP, up=True))
    assert story.posted == [StepBack(1)]
    frame(keys, key(pygame.K_PAGEUP))                      # a new press counts again
    assert story.posted == [StepBack(1), StepBack(1)]
    # The quick menu's Back: one back notch.
    keys, story, _, _ = make()
    keys.request_back()
    keys.update(1 / 60, frozen=False)
    assert story.posted == [StepBack(1)]
    # The App: a wheel in a letterbox bar (window 1600×720) lands in the next frame's pump;
    # y +3 is one restore; Esc, right click, and east open the game menu with no step.
    game = k_game(tmp_path, NO_TITLE + "\n[window]\nwidth = 1600\nheight = 720\n")

    def script(app, out):
        res: dict = {}
        out["res"] = res
        yield from started(app)
        spy = Spy(app, out)
        yield from go(app, "D2")
        timeline = app.story.interp.timeline
        for y in (1, 3):
            landings, since = timeline.landings, spy.frame
            wheel(y)
            yield
            res[f"pointer{y}"] = app.screens.pointer
            yield
            res[y] = ([(f - since, e) for f, e in spy.posts if f >= since],
                      [(f - since, kind) for f, kind in spy.changed if f >= since],
                      timeline.landings - landings)
            yield from settle(app)
        opened = []
        for send in (lambda: post_key(pygame.K_ESCAPE),
                     lambda: pygame.event.post(pygame.event.Event(
                         pygame.MOUSEBUTTONDOWN, pos=(800, 360), button=3, touch=False)),
                     lambda: pygame.event.post(pygame.event.Event(
                         pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_B,
                         instance_id=0))):
            since = spy.frame
            send()
            yield from frames(3)
            opened.append((isinstance(app.screens.top, GameMenuScreen),
                           spy.rollback_posts(since)))
            app.shell.close_game_menu()
            yield from frames(3)
        res["opened"] = opened

    res = run(scripted_app, game, script)["res"]
    assert res["pointer1"] is None and res["pointer3"] is None      # in the bar
    assert res[1] == ([(0, StepBack(1))], [(1, "landing")], 1)       # post, then next pump
    assert res[3] == ([(0, StepBack(3))], [(1, "landing")], 1)       # one restore
    assert res["opened"] == [(True, [])] * 3


# --- AC-F14-19 — touchpad scrolling adds up to whole notches ------------------------------------

def test_ac19_touchpad_scrolling_adds_up():
    assert rollback_mod.TOUCH_UNITS_PER_STEP == 1.0
    unit = rollback_mod.TOUCH_UNITS_PER_STEP

    def run_rows(steps):
        """``steps``: precise values, or ``("gap", seconds)``; all in one frame unless a
        gap (the clock moves between events)."""
        keys, story, _, clock = make()
        for step in steps:
            if isinstance(step, tuple):
                clock.now += step[1]
                continue
            keys.handle_event(whl(precise=step * unit), box_shown=True)
        keys.update(1 / 60, frozen=False)
        return keys, story

    assert run_rows([0.4, 0.4])[1].posted == []
    keys, story = run_rows([0.4, 0.4, 0.3])
    assert story.posted == [StepBack(1)]
    keys.handle_event(whl(precise=0.9 * unit), box_shown=True)       # remainder 0.1 kept
    keys.update(1 / 60, frozen=False)
    assert story.posted == [StepBack(1), StepBack(1)]
    assert run_rows([0.4, -0.4, -0.4])[1].posted == []
    assert run_rows([0.6, ("gap", 0.31), 0.6])[1].posted == []
    assert run_rows([0.6, ("gap", 0.29), 0.6])[1].posted == [StepBack(1)]
    assert run_rows([2.0])[1].posted == [StepBack(2)]
    keys, story, _, _ = make()                                       # no precise_y: y
    frame(keys, ev(pygame.MOUSEWHEEL, x=0, y=1, flipped=False))
    assert story.posted == [StepBack(1)]
    for flipped in (True, False):
        keys, story, _, _ = make()
        frame(keys, whl(1, flipped=flipped), whl(precise=-0.5, flipped=flipped))
        assert story.posted == [StepBack(1)], flipped


# --- AC-F14-30 — the limit cue: timing and motion -------------------------------------------------

class CueBox:
    """F05's textbox as ``RollbackKeys`` and ``LimitCue`` see it; ``bumps`` records
    ``set_bump``."""

    def __init__(self, *, shown: bool = True, reduce: bool = False) -> None:
        self.hidden = False
        self.shown = shown
        self.reduce = reduce
        self.bump = 0.0
        self.bumps: list[float] = []

    @property
    def box_shown(self) -> bool:
        return self.shown and not self.hidden

    def set_hidden(self, hidden: bool) -> None:
        self.hidden = hidden

    def cue_anchor(self) -> tuple[float, float]:
        return (1088.0, 504.0)

    def set_bump(self, dy: float) -> None:
        self.bump = dy
        self.bumps.append(dy)

    def reduce_motion(self) -> bool:
        return self.reduce


class CueRun:
    """App R's frame order on fake ports: events, the overlay's update, the shell's cue
    layer update, then its draw (the draw spy records the opacity drawn, or None)."""

    def __init__(self, *, height: int = 6, sound: str | None = None, shown: bool = True,
                 reduce: bool = False,
                 view: RollbackView = RollbackView(True, False, 0, 0, 0)) -> None:
        cfg = dataclasses.replace(ThemeConfig(), rollback=dataclasses.replace(
            RollbackTheme(), bump_height=height, limit_sound=sound))
        self.box = CueBox(shown=shown, reduce=reduce)
        self.sounds: list = []
        self.cue = LimitCue(self.box, theme=plain_theme(cfg), play=self.sounds.append)
        self.story = FakeStory(view)
        self.keys = RollbackKeys(self.story, self.box, clock=lambda: self.t, cue=self.cue)
        self.drawn: float | None = None
        self.frames = 0
        self.dt = 0.01
        self.covered = False

    @property
    def t(self) -> float:
        return self.frames * self.dt

    def frame(self, *events: UiEvent, frozen: bool = False):
        for e in events:
            self.keys.handle_event(e, box_shown=self.box.box_shown)
        self.keys.update(self.dt, frozen=frozen)
        cue = self.cue
        cue.update(self.dt, covered=self.covered or frozen, reduce_motion=False)
        drawn = cue.opacity if cue.active and cue.visible and cue.opacity > 0 else None
        out = (round(self.t * 1000), None if self.covered or frozen else drawn, self.box.bump)
        self.frames += 1
        return out


def test_ac30_limit_cue_timing_and_motion():
    up = whl(1)
    # mark and bump: a refused wheel-up at t = 0 (10 ms frames).
    run = CueRun()
    rows = [run.frame(up)] + [run.frame() for _ in range(60)]
    by_ms = {ms: (op, dy) for ms, op, dy in rows}
    assert by_ms[0] == (None, 0.0)                               # not in the input frame
    assert all(by_ms[ms][0] == 1.0 for ms in range(10, 400, 10))
    assert by_ms[450][0] == pytest.approx(0.5, abs=0.17)
    assert all(by_ms[ms][0] is None for ms in range(500, 610, 10))
    assert by_ms[80][1] == pytest.approx(-6) and by_ms[40][1] == pytest.approx(-3, abs=1)
    assert all(by_ms[ms][1] == 0.0 for ms in range(200, 610, 10))
    assert min(run.box.bumps) == pytest.approx(-6)
    # A second refused input at 300 ms: full until 700, gone from 800; a bump at each.
    run = CueRun()
    starts, rows = [], []
    for i in range(100):
        rows.append(run.frame(up) if i in (0, 30) else run.frame())
        if run.cue.bump_t == 0.0:
            starts.append(rows[-1][0])
    by_op = {ms: op for ms, op, _ in rows}
    assert all(by_op[ms] == 1.0 for ms in range(10, 700, 10))
    assert all(by_op[ms] is None for ms in range(800, 1000, 10))
    assert starts == [0, 300]
    # The wheel spun at 30 notches/s for 3 s (60 fps): one steady mark, bumps ≥ 200 ms
    # apart, the sound once per appearance (not on a restarted hold).
    run = CueRun(sound="limit.ogg")
    run.dt = 1 / 60
    spin, starts = [], []
    for i in range(180):
        spin.append(run.frame(up) if i % 2 == 0 else run.frame())
        if run.cue.bump_t == 0.0:
            starts.append(i / 60)
    assert all(op == 1.0 for _, op, _ in spin[1:])
    assert len(starts) > 1 and all(b - a >= 0.2 - 1e-9 for a, b in zip(starts, starts[1:]))
    assert run.sounds == ["limit.ogg"]
    for _ in range(60):
        run.frame()
    run.frame(up)
    run.frame()
    assert run.sounds == ["limit.ogg"] * 2
    # Reduced motion: no bump; full until 400 ms, then gone with no in-between.
    run = CueRun(reduce=True)
    rows = [run.frame(up)] + [run.frame() for _ in range(60)]
    assert all(dy == 0.0 for _, _, dy in rows) and run.box.bumps == []
    assert {op for ms, op, _ in rows if 10 <= ms < 400} == {1.0}
    assert all(op is None for ms, op, _ in rows if ms >= 400)
    # bump_height 0, and a say window not drawn: the mark as above, no bump.
    for kw in ({"height": 0}, {"shown": False}):
        run = CueRun(**kw)
        rows = [run.frame(up)] + [run.frame() for _ in range(60)]
        assert run.box.bumps == [] and rows[5][1] == 1.0 and rows[55][1] is None, kw
    # StepForward posted, a new Say, H, or Esc during the cue: dy 0 and no mark that frame.
    for end in ("forward", "say", "hide", "esc"):
        run = CueRun(view=RollbackView(True, False, 0, 3, 0))
        run.frame(up)
        for _ in range(3):
            row = run.frame()
        assert row[1] == 1.0 and row[2] < 0, end
        if end == "forward":
            row = run.frame(whl(-1))
            assert run.story.posted == [StepForward(1)]
        elif end == "say":
            run.keys.on_say(None)
            row = run.frame()
        elif end == "hide":
            run.box.hidden = True
            row = run.frame()
        else:
            run.covered = True
            row = run.frame(frozen=True)
        assert row[1:] == (None, 0.0), end
    # StepForward(1) at the newest step: no cue.
    run = CueRun(view=RollbackView(True, True, 3, 0, 0))
    row = run.frame(whl(-1))
    assert run.story.posted == [] and run.cue.triggers == 0 and run.frame()[1] is None


# --- AC-F14-32 — the rewind tag --------------------------------------------------------------------

def test_ac32_rewind_tag():
    shell = TestShell()
    harness = UiHarness(shell, window=(320, 180))                 # a small canvas
    canvas = harness.canvas
    canvas.bind(harness.framebuffer, harness.viewport, harness.quality)
    q = shell.theme.cfg.quick_menu
    story = FakeStory(RollbackView(True, True, 4, 3, 0))           # K@F, then StepBack(3)
    textbox = SimpleNamespace(hidden=False)
    right: list = [None]
    keys = RollbackKeys(story, textbox, shell=shell, skip_indicator=lambda: right[0])
    painter = shell.painter
    shapes: list = []
    triangles: list = []
    with pytest.MonkeyPatch.context() as mp, spy_draw_text(mp) as texts:
        real_shape, real_tri = painter.shape, painter.triangle

        def shape(box, spec, **kw):
            shapes.append((box, spec))
            real_shape(box, spec, **kw)

        def triangle(box, color, **kw):
            triangles.append((box, color, kw))
            real_tri(box, color, **kw)

        mp.setattr(painter, "shape", shape)
        mp.setattr(painter, "triangle", triangle)

        def draw():
            shapes.clear()
            triangles.clear()
            texts.clear()
            keys.draw(canvas, box_shown=True)
            return shapes[:], triangles[:], [(t.text, t.pos, t.options) for t in texts]

        number = measure_with(shell.assets, shell.theme.font(q.text_size))("3", q.text_size)
        pills, tris, words = draw()
        pill = Box(24, 24, 12 + 22 + 6 + number + 12, 28)
        assert pills == [(pill, FrameSpec(q.fill_color, q.fill_opacity,
                                          border_color=q.on.border_color,
                                          border_width=q.on.border_width,
                                          corner_radius=q.corner_radius))]
        color = q.focused.text_color
        assert tris == [(Box(36, 32, 10, 12), color, {"direction": "left"}),
                        (Box(48, 32, 10, 12), color, {"direction": "left"})]
        assert words == [("3", (64, 38), {"anchor": "midleft"})]
        # The pill's fill is on the canvas (between the glyph and the number).
        dx, dy = canvas.px(60, 38)
        assert harness.framebuffer.get_at((dx + harness.viewport.x, dy + harness.viewport.y)) \
            != (0, 0, 0, 255)
        # Each StepForward(1) or matched Advance: the new number in that frame's draw.
        for ahead in (2, 1):
            story.view = RollbackView(True, True, 4, ahead, 0)
            assert draw()[2][0][0] == str(ahead)
        # Not drawn at ahead 0, in hidden mode, or with marker = false.
        story.view = RollbackView(True, True, 4, 0, 0)
        assert draw() == ([], [], [])
        story.view = RollbackView(True, True, 4, 3, 0)
        textbox.hidden = True
        assert draw() == ([], [], [])
        textbox.hidden = False
        keys.marker = False
        assert draw() == ([], [], [])
        keys.marker = True
        # A fake indicator_right() of 120: x 128.
        right[0] = 120.0
        assert draw()[0][0][0].x == 128
    # F15's real indicator_right (A6): the pill's right edge while it shows, else None.
    sa, tb, _ = skip_unit()
    sa.set_auto(False)
    assert sa.indicator_right() is None                           # no indicator yet
    sa.indicator = SkipIndicator(shell)
    assert sa.indicator_right() is None                           # both off
    sa.set_auto(True)
    assert sa.indicator_right() == sa.indicator.pill("auto")[1].right
    tb.hidden = True
    assert sa.indicator_right() is None
