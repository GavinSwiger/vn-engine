"""F25-3 — present evidence on screen (``06-acceptance.md``: AC-F25-06 to 12, 14 to 17, 19,
20, 23, 24; F25-4's 25). One test per AC, its rows inside.

**Host E** (``06`` §0.2): F23's Host U pieces (``MinigameHost`` and ``MinigameScreen`` on
F10's unit canvas, SDL dummy, 1280×720, default theme with F10's button sounds, 100% text,
1/60 s frames, an Audio spy, a post sink, a ``fatal`` recorder) with ``PresentEvidence``'s
signature from ``BUNDLED`` (no Loader L), a real F21 ``CodexView`` over ``LedgerCodexPort``,
and Template E's state at M: ``brass_key``, ``festival_map``, ``shrine_photo`` held,
``lanterns`` unlocked, ``credibility`` 5 on a 0–5 meter (``tests/fixtures/F25/args.py``).
Sessions start as a cut (``restored``), reached by Enter unless a row says otherwise; each
row opens a fresh session. ``_WARNED`` is cleared around every test.

**Frames.** An input handled in a frame comes before that frame's ``update``. The loss's
frame 0 is the frame of the pick (it shows ``t = 0``), so frame N's picture shows
``t = N / 60`` and the run finishes in frame 60.

**Acceptance.** Driver D's rows are read from the posted ``MinigameDone``: its result is
``shown``, and its changes applied to the meter (F22 clamps) give the accepted value. AC-F23
rows cover the driver itself (AC-F23-07, 14, 18).
"""

import dataclasses
import logging
import threading
import time
from types import MappingProxyType

import pygame
import pytest

from engine.core.config_schema import ThemeConfig
from engine.core.minigame_types import MeterChange
from engine.minigames import api
from engine.minigames.bundled import BUNDLED, present_evidence, present_rules
from engine.minigames.bundled.present_evidence import PresentEvidence
from engine.minigames.context import DiceHandle, MinigameThreadError
from engine.minigames.host import HostPorts, MinigameHost, Phase
from engine.minigames.registry import Registry
from engine.runtime.commands import (
    MeterView,
    MinigameBase,
    MinigameDone,
    MinigameUsed,
    StartMinigame,
)
from engine.runtime.minigame import entry_check
from engine.runtime.points import Points
from engine.script.points import MeterSpec
from engine.ui import layouts
from engine.ui.builtin.codex_page import CodexFilter, CodexView, PickAction
from engine.ui.focus import Box
from engine.ui.nav import InputKind
from tests.fakes.ui_shell import SolidScreen, UiHarness
from tests.fixtures.F25 import args as fx
from tests.minigames.host_u import AudioSpy, CueSpy, HostShell

H = UiHarness
DT = 1 / 60
SID = "main.vns:19"
WHERE = ("script/main.vns", 19)
ACTIVATE = "sfx/activate.ogg"
ENTRY = api.declarations(next(c for c in BUNDLED if c is PresentEvidence), "engine")
WIN, WRONG = fx.WIN, fx.WRONG
PANEL_FILL = (0xFF, 0xF4, 0xF8)
BAR_FILL, BAR_TRACK, LOSS = (0xA0, 0x28, 0x60), (0xF0, 0xD0, 0xDE), (0xC6, 0x28, 0x28)
STATEMENT_GREEN = (0x1E, 0x6B, 0x34)


def _sounds() -> ThemeConfig:
    cfg = ThemeConfig()
    return dataclasses.replace(cfg, button=dataclasses.replace(
        cfg.button, focus_sound="sfx/focus.ogg", activate_sound=ACTIVATE))


SOUNDS = _sounds()


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


@pytest.fixture(autouse=True)
def warned():
    present_evidence._WARNED.clear()
    yield present_evidence._WARNED
    present_evidence._WARNED.clear()


# --- Host E -----------------------------------------------------------------------------------

def tap(key: int, mod: int = 0) -> tuple:
    return H.key(key, mod), H.key(key, mod, up=True)


def pad(button: int) -> tuple:
    return H.pad(button), H.pad(button, up=True)


def click(pos, button: int = 1) -> tuple:
    return H.motion(pos), H.down(pos, button), H.up(pos, button)


ENTER, LEFT, RIGHT, DOWN = (tap(k) for k in (pygame.K_RETURN, pygame.K_LEFT, pygame.K_RIGHT,
                                               pygame.K_DOWN))
UP, BACKSPACE = tap(pygame.K_UP), tap(pygame.K_BACKSPACE)
PAGE_UP, PAGE_DOWN = tap(pygame.K_PAGEUP), tap(pygame.K_PAGEDOWN)
SOUTH, EAST = pad(pygame.CONTROLLER_BUTTON_A), pad(pygame.CONTROLLER_BUTTON_B)
D_RIGHT, D_DOWN = pad(pygame.CONTROLLER_BUTTON_DPAD_RIGHT), pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN)
LB, RB = pad(pygame.CONTROLLER_BUTTON_LEFTSHOULDER), pad(pygame.CONTROLLER_BUTTON_RIGHTSHOULDER)


def stick_left() -> tuple:
    """One step of the left stick to the left, then back to rest."""
    return _axis(pygame.CONTROLLER_AXIS_LEFTX, -32767), _axis(pygame.CONTROLLER_AXIS_LEFTX, 0)


def _axis(axis: int, value: int):
    from engine.ui.input import UiEvent
    return UiEvent(pygame.event.Event(pygame.CONTROLLERAXISMOTION, axis=axis, value=value,
                                      instance_id=0), None, False)


class HostE:
    """One Host E world (module docstring)."""

    def __init__(self, *, cfg=SOUNDS, dev=True, reduce_motion=False, config=None, tables=None,
                 meter=(0, 5), extra_evidence=0, assets=None, index=None) -> None:
        self.registry = Registry(main_thread=threading.get_ident())
        self.registry.add(ENTRY)
        self.shell = HostShell(dev=dev, reduce_motion=reduce_motion, cfg=cfg, config=config,
                               assets=assets)
        self.ui = UiHarness(self.shell)
        self.shell.stack.push(SolidScreen((200, 200, 200)))
        self.posted: list = []
        self.fatal: list = []
        self.audio = AudioSpy()
        self.meter = meter
        self.points = Points((MeterSpec("credibility", meter[0], meter[1], meter[1], True),))
        self.index = fx.index(extra_evidence) if index is None else index
        self.ports = HostPorts(
            shell=self.shell, lookup=self.registry.get, post=self.posted.append,
            where=lambda sid: WHERE, fatal=self.fatal.append, check_meter=self.points.spec,
            check_entry=entry_check(self.index), index=lambda: self.index, audio=self.audio,
            cue=CueSpy(), viewport=lambda: (1280, 720), tables=tables,
            main_thread=self.registry.main_thread)
        self.host = MinigameHost(self.ports)
        self.texts: list[tuple] = []
        self.fills: list[tuple] = []
        canvas = self.ui.canvas
        draw_text, fill = canvas.draw_text, canvas.fill

        def text_spy(text, font, color, pos, **kw):
            self.texts.append((text, font.size, tuple(color), tuple(pos), kw.get("anchor")))
            return draw_text(text, font, color, pos, **kw)

        def fill_spy(color, rect=None):
            self.fills.append((tuple(color), None if rect is None else tuple(rect)))
            return fill(color, rect)

        canvas.draw_text, canvas.fill = text_spy, fill_spy
        self.finishes: list = []
        self.g: PresentEvidence | None = None

    def command(self, args=None, *, value=None, held=fx.HELD, tips=("lanterns",),
                restored=True, run=1, skippable=True, seed=42) -> StartMinigame:
        a = fx.args() if args is None else args
        low, high = self.meter
        value = high if value is None else value
        base = MinigameBase((MeterView("credibility", value, low, high),), tuple(held),
                            tuple(tips))
        return StartMinigame(SID, run, "present_evidence", MappingProxyType(dict(a)), seed,
                             base, skippable, restored, fx.STORY_S)

    def open(self, args=None, *, by=InputKind.KEYS, cmd=None, frame=True,
             **kw) -> PresentEvidence:
        """A fresh session reached by ``by``; ``g.finishes`` records ``ctx.finish``."""
        self.posted.clear()
        self.shell.sounds.clear()
        self.shell.stack.last_input = by
        self.host.start(cmd if cmd is not None else self.command(args, **kw))
        assert not self.fatal, [f.format() for f in self.fatal]
        s = self.host.session
        g = s.plugin
        port = s.ctx._port
        real = port.finish
        g.finishes = []

        def finish(result):
            g.finishes.append(result)
            return real(result)

        port.finish = finish
        self.g = g
        if frame:
            self.frame()
            assert self.host.session is s and s.phase is Phase.RUNNING, self.fatal
        return g

    def frame(self, *events):
        self.texts.clear()
        self.fills.clear()
        if self.g is not None:
            self.g.hatch_drawn = ()
        return self.ui.frame(*events)

    def frames(self, n: int):
        for _ in range(n):
            self.frame()
        return self.ui.framebuffer

    def px(self, x, y):
        return self.ui.px(x, y)

    @property
    def session(self):
        return self.host.session

    @property
    def game(self) -> PresentEvidence:
        return self.host.session.plugin

    @property
    def scope(self):
        return self.host.session.scope

    def focused(self):
        s = self.host.session
        return None if s is None else s.scope.focused

    def done(self) -> list[MinigameDone]:
        return [e for e in self.posted if isinstance(e, MinigameDone)]

    def used(self) -> list:
        return [e for e in self.posted if isinstance(e, MinigameUsed)]

    def activations(self) -> int:
        return self.shell.sounds.count(ACTIVATE)

    def count(self) -> str | None:
        found = [t[0] for t in self.texts if t[4] == "topright" and " / " in t[0]
                 and t[3][1] > 200]
        return found[-1] if found else None

    def value(self) -> str | None:
        found = [t[0] for t in self.texts if t[4] == "topright" and " / " in t[0]
                 and t[3][1] < 200]
        return found[-1] if found else None

    def hatch(self) -> list[tuple]:
        """The hatch blocks the last frame drew (canvas units; the plugin fills them on the
        canvas surface directly, so they aren't in ``fills``)."""
        g = self.g
        return list(g.hatch_drawn) if g is not None else []

    def hatch_edge(self) -> float | None:
        rects = self.hatch()
        return max(r[0] + r[2] for r in rects) if rects else None

    def accepted(self, value: int | None = None) -> int:
        """The meter after Driver D accepts the one posted ``MinigameDone``."""
        (done,) = self.done()
        v = self.meter[1] if value is None else value
        for change in done.changes:
            assert isinstance(change, MeterChange) and change.name == "credibility"
            v = v + change.amount if change.op == "+=" else (
                v - change.amount if change.op == "-=" else change.amount)
        return max(self.meter[0], min(self.meter[1], v))


def center(w: Box) -> tuple[float, float]:
    return w.box.center


def raw_view(g: PresentEvidence) -> CodexView:
    """The session's ``CodexView`` behind ``bind``'s wrapper."""
    assert g.view is not None
    return g.view._target


def run_closing(w: HostE) -> None:
    """Frames until the closing dissolve posts ``MinigameDone``."""
    for _ in range(60):
        if w.done():
            return
        w.frame()


# --- AC-F25-06 — every result by each input device --------------------------------------------

def _keyboard(w, outcome):
    return {"press": [ENTER],
            "wrong": [RIGHT, RIGHT, ENTER, LEFT, ENTER, DOWN, ENTER, ENTER],
            "correct": [RIGHT, RIGHT, ENTER, LEFT, ENTER, ENTER, ENTER]}[outcome]


def _gamepad(w, outcome):
    return {"press": [SOUTH],
            "wrong": [D_RIGHT, D_RIGHT, SOUTH, stick_left(), SOUTH, D_DOWN, SOUTH, SOUTH],
            "correct": [D_RIGHT, D_RIGHT, SOUTH, stick_left(), SOUTH, SOUTH, SOUTH]}[outcome]


@pytest.mark.parametrize("device", ["keyboard", "mouse", "gamepad"])
def test_ac_f25_06_every_result_by_each_device(device):
    w = HostE()
    expected = {"press": fx.PRESS, "wrong": WRONG, "correct": WIN}
    for outcome in ("press", "wrong", "correct"):
        by = InputKind.MOUSE if device == "mouse" else InputKind.KEYS
        g = w.open(by=by)
        if device == "mouse":
            g = w.game
            if outcome == "press":
                steps = [click(center(g.press))]
            else:
                steps = [click(center(g.next)), click(center(g.present))]
        else:
            steps = (_keyboard if device == "keyboard" else _gamepad)(w, outcome)
        for events in steps:
            w.frame(*events)
        if device == "mouse" and outcome != "press":
            view = raw_view(g)
            assert g.mode == "picker"
            if outcome == "wrong":
                pos = _row_center(view, 1)
                w.frame(*click(pos))
                assert view.selected == "festival_map"
            w.frame(*click(center(view.pick_button)))
        if outcome == "wrong":
            assert g.finishes == [] and g.loss is not None
            n = 0
            while not g.finishes:
                w.frame()
                n += 1
            assert abs(n - 60) <= 1, (device, n)
        assert g.finishes == [expected[outcome]], (device, outcome)
        run_closing(w)
        done = w.done()
        assert len(done) == 1 and done[0].result == expected[outcome]
        assert done[0].changes == ((MeterChange("credibility", "+=", -1),)
                                   if outcome == "wrong" else ())
        assert w.accepted() == (4 if outcome == "wrong" else 5)
        # One activation sound per activation: a button, a list row, the pick button.
        presses = {"press": 1, "wrong": 4, "correct": 3 if device == "mouse" else 4}[outcome]
        assert w.activations() == presses, (device, outcome, w.shell.sounds)
        assert w.fatal == []


def _row_center(view: CodexView, i: int) -> tuple[float, float]:
    return view.list.row_box(i).center


# --- Shared steps -----------------------------------------------------------------------------

def wrong_pick_by_keys(w: HostE, g: PresentEvidence) -> None:
    """On ``gate`` with Press focused: Present, the Festival Map row, then the pick button.
    The last frame is the loss's frame 0."""
    for keys in (RIGHT, ENTER, DOWN, ENTER):
        w.frame(*keys)
    assert g.mode == "picker" and raw_view(g).selected == "festival_map"
    w.frame(*ENTER)
    assert g.loss is not None and g.loss.t == 0.0


def record_events(g: PresentEvidence) -> list[bool]:
    """``handle_event``'s answers from now on (the host looks the method up per call)."""
    answers: list[bool] = []
    real = g.handle_event

    def spy(ev):
        answer = real(ev)
        answers.append(answer)
        return answer

    g.handle_event = spy
    return answers


def screen_answer(w: HostE, *events) -> list[bool]:
    """``MinigameScreen.handle_event``'s answer to each event (True: consumed; False: it
    reaches the shell's fallbacks: the game menu, F14's ``RollbackKeys``)."""
    screen = w.session.screen
    return [screen.handle_event(e) for e in events]


def configured(tmp_path, text: str, **kw) -> HostE:
    """Host E over a ``config.toml`` holding ``text`` (s5b's ``PluginTables``)."""
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.minigames.tables import PluginTables
    root = tmp_path / f"cfg{len(list(tmp_path.iterdir()))}"
    root.mkdir()
    (root / "config.toml").write_text(text, encoding="utf-8")
    result = load_config(GamePaths.for_game(root))
    assert result.errors == [] and result.warnings == [], text
    tables = PluginTables(result.config.theme.plugin, result.config.words.plugin,
                          result.config.theme, dev=True)
    tables.check([ENTRY])
    return HostE(config=result.config, tables=tables, **kw)


def near(a, b, tol: int = 8) -> bool:
    return max(abs(x - y) for x, y in zip(a, b)) <= tol


# --- AC-F25-07 — browsing, focus, and used inputs ---------------------------------------------

def test_ac_f25_07_browsing_focus_and_used_inputs():
    w = HostE()
    # Reached by Enter: Press focused at the first running frame; nothing used.
    g = w.open()
    assert w.focused() is g.press and w.scope.visible and w.used() == []
    assert w.session.hint_text == "Press the witness, or present evidence."
    # press=False: 3 buttons, Present focused, the other hint.
    g = w.open(fx.args(press=False))
    assert [b.label() for b in g.buttons] == ["‹ Previous", "Present", "Next ›"]
    assert w.focused() is g.present
    assert w.session.hint_text == "Present evidence that contradicts the statement."
    # Reached by click: nothing focused; the first Right focuses Press and is used.
    g = w.open(by=InputKind.MOUSE)
    assert w.focused() is None
    w.frame(*RIGHT)
    assert w.focused() is g.press and len(w.used()) == 1
    # Next ×3 from s0 wraps; focus stays on Next. Previous at s0 gives 3 / 3.
    g = w.open()
    w.frame(*RIGHT)
    w.frame(*RIGHT)
    assert w.focused() is g.next
    counts = []
    for _ in range(3):
        w.frame(*ENTER)
        counts.append(w.count())
        assert w.focused() is g.next
    assert counts == ["2 / 3", "3 / 3", "1 / 3"]
    for _ in range(3):
        w.frame(*LEFT)
    assert w.focused() is g.previous
    w.frame(*ENTER)
    assert w.count() == "3 / 3"
    # After 10 statement changes: no ledger request, no finish, one MinigameUsed.
    for _ in range(6):
        w.frame(*ENTER)
    assert w.session.ledger.changes == () and g.finishes == [] and len(w.used()) == 1
    # (Should) Page Down, RB; Page Up, LB: next / previous; handle_event True.
    g = w.open()
    answers = record_events(g)
    seen = []
    for keys in (PAGE_DOWN, RB, PAGE_UP, LB):
        w.frame(*keys)
        seen.append(g.stmt)
    assert seen == [1, 2, 1, 0] and answers[0::2] == [True] * 4
    # A one-statement testimony: no Previous, Next, or count; Page Down isn't used (F23's
    # fallback: False, so F14's RollbackKeys steps forward).
    g = w.open(fx.args(testimony={"gate": "The gate was locked."},
                       answer={"gate": "brass_key"}))
    assert [b.label() for b in g.buttons] == ["Press", "Present"] and w.count() is None
    answers = record_events(g)
    assert screen_answer(w, H.key(pygame.K_PAGEDOWN)) == [False] and answers == [False]
    # Hover over Next, then wheel up: nothing used; the wheel falls through (StepBack).
    g = w.open(by=InputKind.MOUSE)
    w.frame(H.motion(center(g.next)))
    assert screen_answer(w, H.wheel(center(g.next), 1)) == [False] and w.used() == []
    # Next, then wheel up: MinigameUsed first, then the wheel falls through (the cue).
    w.frame(*click(center(g.next)))
    assert len(w.used()) == 1
    assert screen_answer(w, H.wheel(center(g.next), 1)) == [False]
    # Backspace; right click; east; Esc: handle_event False for the first three (Esc is never
    # offered). F23's fallbacks: Backspace nothing, right click and east the game menu.
    g = w.open()
    answers = record_events(g)
    got = screen_answer(w, H.key(pygame.K_BACKSPACE), H.down((640, 200), 3),
                        H.pad(pygame.CONTROLLER_BUTTON_B), H.key(pygame.K_ESCAPE))
    assert answers == [False, False, False] and got == [True, False, False, False]
    assert g.finishes == [] and w.fatal == []


# --- AC-F25-08 — the picker -------------------------------------------------------------------

def test_ac_f25_08_the_picker():
    w = HostE()
    gate = fx.args(at="gate")
    # Opened by keys: two tabs, no tip, Brass Key focused, the hint, the pick word.
    g = w.open(gate)
    w.frame(*RIGHT)
    w.frame(*ENTER)
    view = raw_view(g)
    assert g.mode == "picker"
    assert [tab.label for tab in view.tabs] == ["Evidence", "Items"]
    names = [row.entry.name for tab in view.tabs for row in tab.rows]
    assert names == ["brass_key", "festival_map", "shrine_photo"]
    assert w.focused() is view.list and view.selected == "brass_key"
    assert w.session.hint_text == "Present evidence against: “The gate was locked all night.…”"
    assert view.pick_button.label() == "Present"
    # Opened by click: nothing focused.
    g = w.open(gate, by=InputKind.MOUSE)
    w.frame(*click(center(g.present)))
    assert g.mode == "picker" and w.focused() is None
    # evidence=["Evidence"]: one tab.
    g = w.open(fx.args(at="gate", evidence=["Evidence"]))
    w.frame(*RIGHT)
    w.frame(*ENTER)
    view = raw_view(g)
    assert [[r.entry.title for r in tab.rows] for tab in view.tabs] == [
        ["Brass Key", "Festival Map"]]
    # evidence=["codex_items"] with shrine_photo locked: codex_empty, no pick button, Back.
    g = w.open(fx.args(at="gate", evidence=["codex_items"]),
               held=("brass_key", "festival_map"))
    w.frame(*RIGHT)
    w.frame(*ENTER)
    w.frame()
    view = raw_view(g)
    assert view.tabs == () and view.pick_button not in w.scope.widgets()
    assert w.shell.words.get("codex_empty") in [t[0] for t in w.texts]
    assert w.focused() is g.back
    w.frame(*ENTER)
    assert g.mode == "testimony"
    # Back by the button, Backspace, right click, east: testimony on s1; Present focused
    # (keys) or nothing (mouse); the hint restored; no ledger request; no game menu.
    for how in ("button", "backspace", "right_click", "east"):
        g = w.open(gate)
        w.frame(*RIGHT)
        w.frame(*ENTER)
        if how == "button":
            w.frame(*click(center(g.back)))
        else:
            event = {"backspace": H.key(pygame.K_BACKSPACE), "east": EAST[0],
                     "right_click": H.down((640, 300), 3)}[how]
            assert screen_answer(w, event) == [True], how
            w.frame()
        mouse = how in ("button", "right_click")
        assert g.mode == "testimony" and g.stmt == 1, how
        assert w.focused() is (None if mouse else g.present), how
        assert w.session.hint_text == "Press the witness, or present evidence."
        assert w.session.ledger.changes == () and g.finishes == []
    # Left from row 1 and row 2, Down from row 2: Back; at 100% and at 150% (two-line hint).
    for scale in (1.0, 1.5):
        for keys in ((LEFT,), (DOWN, LEFT), (DOWN, DOWN)):
            w.shell.painter.set_text_scale(lambda s=scale: s)
            g = w.open(gate)
            w.frame(*RIGHT)
            w.frame(*ENTER)
            w.frame()
            if scale == 1.5:
                assert len(w.session.frame.hint_lines) == 2
                assert w.session.area.bottom == 556
            for k in keys:
                w.frame(*k)
            assert w.focused() is g.back, (scale, keys)
            w.frame(*ENTER)                          # Back focused, then Enter: closes
            assert g.mode == "testimony" and w.focused() is g.present
    # 10 held Evidence items at 150%: Down ×9 scrolls to row 10, then Down reaches Back.
    w = HostE(extra_evidence=8)
    w.shell.painter.set_text_scale(lambda: 1.5)
    held = ("brass_key", "festival_map", *(f"clue_{i}" for i in range(1, 9)), "shrine_photo")
    g = w.open(fx.args(at="gate", evidence=["Evidence"]), held=held)
    w.frame(*RIGHT)
    w.frame(*ENTER)
    w.frame()
    view = raw_view(g)
    assert len(view.list_rows) == 10 and len(w.session.frame.hint_lines) == 2
    for _ in range(9):
        w.frame(*DOWN)
    assert view.list.focus_row == 9 and view.list.scroll > 0
    assert w.focused() is view.list
    w.frame(*DOWN)
    assert w.focused() is g.back
    assert w.fatal == []


# --- AC-F25-09 — the penalty and the loss display ---------------------------------------------

def _timeline(w: HostE, *, reduce: bool) -> dict:
    w.shell.reduce_motion = reduce
    g = w.open(fx.args(at="gate"))
    wrong_pick_by_keys(w, g)
    seen: dict = {}
    edges = []
    for n in range(1, 70):
        w.frame()
        fill = [r for c, r in w.fills if c == BAR_FILL]
        span = g.loss_view()[0] if g.loss is not None and not g.done else None
        edges.append(None if span is None else 44 + 78.4 * span[1])
        seen[n] = (fill[-1][0] + fill[-1][2] if fill else None, w.hatch(), w.hatch_edge(),
                   w.value(), list(g.finishes), span)
        if g.finishes:
            seen["finish"] = n
            break
    seen["edges"] = edges
    return seen


def test_ac_f25_09_penalty_and_loss_display():
    w = HostE()
    for reduce in (False, True):
        seen = _timeline(w, reduce=reduce)
        fill, hatch, edge, value, _, span = seen[15]
        assert fill == pytest.approx(357.6) and value == "5 / 5"
        assert span == (4, 5) and min(r[0] for r in hatch) >= 357.6 and 433 <= edge <= 436
        fill, hatch, edge, value, _, span = seen[39]
        if reduce:
            assert hatch == [] and value == "4 / 5"
        else:
            assert 44 + 78.4 * span[1] == pytest.approx(396.8, abs=1)
            assert 393.8 <= edge <= 396.8 and value == "4 / 5"
        fill, hatch, edge, value, _, _ = seen[54]
        assert hatch == [] and fill == pytest.approx(357.6) and value == "4 / 5"
        assert abs(seen["finish"] - 60) <= 1
        assert seen[seen["finish"]][4] == [WRONG]
        if reduce:
            assert all(e is None or abs(e - 436) < 1e-6 for e in seen["edges"])
    w.shell.reduce_motion = False

    def finish_now(g):
        assert g.finishes != [] and g.loss is None

    # Press; correct present: no request, no hatch, 5.
    g = w.open()
    w.frame(*ENTER)
    finish_now(g)
    run_closing(w)
    assert w.done()[0].changes == () and w.accepted() == 5
    g = w.open(fx.args(at="gate"))
    for keys in (RIGHT, ENTER, ENTER, ENTER):
        w.frame(*keys)
    finish_now(g)
    assert w.hatch() == []
    run_closing(w)
    assert w.done()[0].changes == () and w.accepted() == 5
    # penalty unset: no panel or bar; a wrong pick finishes at once from the picker.
    g = w.open(fx.args(at="gate", penalty=None))
    assert w.value() is None and not [f for f in w.fills if f[0] in (BAR_FILL, BAR_TRACK)]
    for keys in (RIGHT, ENTER, DOWN, ENTER, ENTER):
        w.frame(*keys)
    finish_now(g)
    assert g.mode == "picker" and g.finishes == [WRONG]
    run_closing(w)
    assert w.done()[0].changes == ()
    # cost=0: no request, finishes at once.
    g = w.open(fx.args(at="gate", cost=0))
    for keys in (RIGHT, ENTER, DOWN, ENTER, ENTER):
        w.frame(*keys)
    finish_now(g)
    run_closing(w)
    assert w.done()[0].changes == () and w.accepted() == 5
    # Meter 0: one request; hatch 44–122.4; 0 / 5 throughout; 0.
    # Meter 2, cost=3: hatch 44–200.8; 0.
    for value, cost, right, after in ((0, 1, 122.4, 0), (2, 3, 200.8, 0)):
        g = w.open(fx.args(at="gate", cost=cost), value=value)
        wrong_pick_by_keys(w, g)
        w.frames(15)
        assert 44 <= min(r[0] for r in w.hatch()) <= 47
        assert right - 3 <= w.hatch_edge() <= right
        values = set()
        while not g.finishes:
            w.frame()
            values.add(w.value())
        if value == 0:
            assert values == {"0 / 5"}
        run_closing(w)
        assert len(w.done()[0].changes) == 1 and w.accepted(value) == after
    # points credibility 0 to 10, meter 8, penalty_max=5: full bar, 5 / 5 throughout, 7.
    w10 = HostE(meter=(0, 10))
    g = w10.open(fx.args(at="gate"), value=8)
    wrong_pick_by_keys(w10, g)
    values, hatched = set(), []
    while not g.finishes:
        w10.frame()
        values.add(w10.value())
        hatched += w10.hatch()
        fill = [r for c, r in w10.fills if c == BAR_FILL]
        assert fill[-1][2] == pytest.approx(392)
    assert values == {"5 / 5"} and hatched == []
    run_closing(w10)
    assert w10.accepted(8) == 7
    # I-9: meter 2 on a 2-to-5 meter (at its floor), cost 1: the hatch spans units 2–3,
    # 2 / 5 throughout; accepted 2.
    w2 = HostE(meter=(2, 5))
    g = w2.open(fx.args(at="gate"), value=2)
    wrong_pick_by_keys(w2, g)
    w2.frames(15)
    assert (g.loss.lo, g.loss.hi) == (2, 3)
    assert 200.8 <= min(r[0] for r in w2.hatch()) and w2.hatch_edge() <= 279.2
    values = set()
    while not g.finishes:
        w2.frame()
        values.add(w2.value())
    assert values == {"2 / 5"}
    run_closing(w2)
    assert w2.accepted(2) == 2
    assert w.fatal == w10.fatal == w2.fatal == []


# --- AC-F25-10 — interruptions during the loss ------------------------------------------------

def _at_frame_24(w: HostE) -> PresentEvidence:
    g = w.open(fx.args(at="gate"))
    wrong_pick_by_keys(w, g)
    w.frames(24)
    assert g.loss is not None and g.loss.t == pytest.approx(0.4)
    return g


def _count_updates(g: PresentEvidence) -> list[float]:
    calls: list[float] = []
    real = g.update

    def spy(dt):
        calls.append(dt)
        return real(dt)

    g.update = spy
    return calls


def test_ac_f25_10_interruptions_during_the_loss():
    w = HostE()
    # The host's Skip Game path (AC-F23-40's Yes) and Shift+F8: the fixed outcome's own
    # changes only (G2: the pending penalty is dropped), no update after it, one post.
    for how in ("skip", "shift_f8"):
        g = _at_frame_24(w)
        updates = _count_updates(g)
        if how == "skip":
            w.host.skip(w.session)
        else:
            w.frame(H.key(pygame.K_F8, pygame.KMOD_SHIFT))
        w.frames(120)
        assert updates == [] and g.finishes == [] and w.fatal == []
        done = w.done()
        assert len(done) == 1 and done[0].result == WIN and done[0].changes == ()
        assert w.accepted() == 5
    # A covering screen for 120 frames: no update while covered; finish at frame 180 ± 1.
    g = _at_frame_24(w)
    updates = _count_updates(g)
    cover = SolidScreen((10, 10, 10))
    w.shell.stack.push(cover)
    w.frames(120)
    assert updates == [] and g.finishes == []
    w.shell.stack.remove(cover) if hasattr(w.shell.stack, "remove") else w.shell.stack.pop()
    n = 24 + 120
    while not g.finishes:
        w.frame()
        n += 1
    assert abs(n - 180) <= 1 and g.finishes == [WRONG]
    # A back landing (abandon): nothing posted, then or later; the meter untouched.
    g = _at_frame_24(w)
    w.host.abandon()
    w.frames(120)
    assert w.done() == [] and w.fatal == [] and g.finishes == []
    # Saved during the loss and restored: waiting at M with credibility 5 (the request was
    # never accepted); the new session opens on at with 5 / 5.
    g = _at_frame_24(w)
    w.host.abandon()
    g = w.open(fx.args(at="gate"), restored=True)
    assert (w.count(), w.value(), g.mode, g.loss) == ("2 / 3", "5 / 5", "testimony", None)
    # The thumbnail source during the loss is the opening picture's (5 / 5, no hatch).
    g = w.open(fx.args(at="gate"))
    thumb = w.host.thumbnail()
    assert thumb is not None
    wrong_pick_by_keys(w, g)
    w.frames(24)
    assert w.host.thumbnail() is thumb
    # Inputs during the loss: consumed, no focus or statement change, no StepBack.
    for event in (ENTER[0], H.down(center(g.next)), H.up(center(g.next)), LEFT[0], RIGHT[0],
                  H.key(pygame.K_BACKSPACE), H.key(pygame.K_PAGEDOWN),
                  H.wheel(center(g.next), 1)):
        answers = record_events(g)
        focus, stmt = w.focused(), g.stmt
        assert screen_answer(w, event) == [True] and answers == [True]
        assert (w.focused(), g.stmt) == (focus, stmt)
        g.handle_event = PresentEvidence.handle_event.__get__(g)
    # layout(area) at 150% in the middle: relaid out; the finish still at frame 60 ± 1.
    g = w.open(fx.args(at="gate"))
    wrong_pick_by_keys(w, g)
    w.frames(24)
    w.shell.painter.set_text_scale(lambda: 1.5)
    n = 24
    while not g.finishes:
        w.frame()
        n += 1
    assert abs(n - 60) <= 1
    assert g.tlay.box[3] == 391
    assert w.fatal == []


# --- AC-F25-11 — same picture on replay and restart -------------------------------------------

class RandomSpy:
    def __init__(self, monkeypatch) -> None:
        self.calls: list[str] = []
        for name in ("roll", "pick", "decimal", "shuffle"):
            real = getattr(DiceHandle, name)

            def spy(handle, *args, _real=real, _name=name, **kwargs):
                self.calls.append(_name)
                return _real(handle, *args, **kwargs)

            monkeypatch.setattr(DiceHandle, name, spy)


def _opening(w: HostE, args=None, **kw) -> pygame.Surface:
    """The opening picture (F23 draws it in ``start``, before first focus): reached by keys
    with a fade, so the session holds it while OPENING."""
    w.open(args, frame=False, restored=False, **kw)
    s = w.session
    assert s.phase is Phase.OPENING and s.opening is not None
    return s.opening.copy()


def _bbox_of_difference(a: pygame.Surface, b: pygame.Surface):
    ab, bb = pygame.image.tobytes(a, "RGB"), pygame.image.tobytes(b, "RGB")
    width = a.get_width()
    xs, ys = [], []
    for i in range(0, len(ab), 3):
        if ab[i:i + 3] != bb[i:i + 3]:
            p = i // 3
            xs.append(p % width)
            ys.append(p // width)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def test_ac_f25_11_same_picture_on_replay_and_restart(monkeypatch):
    w = HostE()
    spy = RandomSpy(monkeypatch)
    for steps in ([ENTER], [RIGHT, RIGHT, ENTER, LEFT, ENTER, ENTER, ENTER]):
        g = w.open()
        for keys in steps:
            w.frame(*keys)
        assert g.finishes
    g = w.open(fx.args(at="gate"))
    wrong_pick_by_keys(w, g)
    w.frames(62)
    assert g.finishes == [WRONG] and spy.calls == []
    # Two sessions, meter 5: pixel-equal opening pictures; meter 4: different only inside
    # the penalty panel's box (24, 24, 432, 98).
    a, b = _opening(w), _opening(w)
    assert pygame.image.tobytes(a, "RGB") == pygame.image.tobytes(b, "RGB")
    c = _opening(w, value=4)
    x0, y0, x1, y1 = _bbox_of_difference(a, c)
    assert 24 <= x0 and x1 < 24 + 432 and 24 <= y0 and y1 < 24 + 98
    # at="gate" opens on 2 / 3.
    w.open(fx.args(at="gate"))
    assert w.count() == "2 / 3"
    # A restored StartMinigame and a back landing on M (both restored=True, by keys): at,
    # the accepted bar, testimony mode, no focus marker in the opening picture (pixel-equal
    # to the same session reached by mouse, where nothing is focused).
    keys_pic = _opening(w, fx.args(at="gate"), value=4)
    w.open(fx.args(at="gate"), value=4, by=InputKind.MOUSE)
    assert w.focused() is None
    mouse_pic = w.ui.framebuffer.copy()
    assert pygame.image.tobytes(keys_pic, "RGB") == pygame.image.tobytes(mouse_pic, "RGB")
    # Template L after a wrong present: the restart opens on s1 with 4 / 5.
    g = w.open(fx.args(at="gate"), value=4)
    assert (w.count(), w.value(), g.mode) == ("2 / 3", "4 / 5", "testimony")


# --- AC-F25-12 — W173 -------------------------------------------------------------------------

def test_ac_f25_12_w173(caplog, warned):
    caplog.set_level(logging.DEBUG, logger="vn.plugin")

    def records():
        return [r for r in caplog.records if getattr(r, "code", None) == "W173"]

    def start(w, args, **kw):
        caplog.clear()
        w.open(args, frame=False, **kw)
        return [r.getMessage() for r in records()]

    w = HostE()
    assert start(w, fx.args()) == []
    (text,) = start(w, fx.args(answer={"gate": "shrine_photo"}, evidence=["Evidence"]))
    assert text == ("present_evidence can't be won here: the player holds none of the "
                    "answer's items (shrine_photo). Unlock one before this line, or change "
                    "answer.")
    (text,) = start(w, fx.args(answer={"gate": ["n1", "n2", "n3", "n4", "n5"]}))
    assert "(n1, n2, n3, and 2 more)" in text
    (text,) = start(w, fx.args(evidence=["Clues"]))
    assert text == ('present_evidence has no evidence to show: the player holds no items in '
                    '"Clues". Unlock one before this line, or change evidence.')
    (text,) = start(w, fx.args(evidence=["Clues", "Notes"]))
    assert '"Clues" or "Notes"' in text
    (text,) = start(w, fx.args(), held=())
    assert "holds no items in any category" in text
    assert start(w, fx.args(), held=()) == []                # the same line again: once
    warned.clear()
    caplog.clear()
    w.open(fx.args(), frame=False, held=())
    (r,) = records()
    assert (r.name, r.levelno, r.code) == ("vn.plugin", logging.WARNING, "W173")
    # Release: none.
    warned.clear()
    rel = HostE(dev=False)
    assert start(rel, fx.args(), held=()) == []
    # _WARNED never holds more than 100 texts (102 distinct starts).
    warned.clear()
    for i in range(102):
        w.open(fx.args(answer={"gate": f"missing_{i}"}), frame=False)
    assert len(warned) == 100


# --- AC-F25-14 — fit from 100% to 150% --------------------------------------------------------

def test_ac_f25_14_fit_from_100_to_150_percent():
    from engine.ui.theme import measure_with, plain_theme
    from tests.render.conftest import make_assets
    theme = plain_theme(ThemeConfig())
    assets = make_assets(None)
    cfg = theme.cfg
    hint_one = "Press the witness, or present evidence."
    hint_two = "Present evidence against: “The gate was locked all night.…” " * 2
    cases = 0
    for scale in (1.0, 1.25, 1.5):
        frames = {}
        for name, hint in (("one", hint_one), ("two", hint_two)):
            frames[name] = layouts.minigame_frame(
                scale, heading=None, hint=hint,
                measure=measure_with(assets, theme.font(cfg.minigame.hint.text_size)),
                heading_measure=measure_with(assets, theme.font(32, bold=True)),
                heading_size=32, hint_size=cfg.minigame.hint.text_size)
        assert len(frames["two"].hint_lines) == 2
        for name, frame in frames.items():
            area = frame.content
            ax, ay, aw, ah = area.x, area.y, area.w, area.h
            pitches = dict(label_pitch=layouts.pitch(layouts.scaled(24, scale)),
                           name_pitch=layouts.pitch(layouts.scaled(32, scale)),
                           statement_pitch=layouts.pitch(layouts.scaled(28, scale)),
                           button_h=layouts.button_height(scale=scale))
            for n in range(1, 5):
                for penalty in (True, False):
                    cases += 1
                    lay = present_rules.testimony_layout(area, n_buttons=n, penalty=penalty,
                                                         **pitches)
                    rects = [lay.box, lay.statement, *lay.buttons] + (
                        [lay.panel, lay.bar] if penalty else [])
                    for x, y, rw, rh in rects:
                        assert ax <= x and y >= ay and x + rw <= ax + aw + 1e-9 \
                            and y + rh <= ay + ah + 1e-9, (scale, name, n, penalty)
                    if penalty:
                        assert lay.box[1] >= lay.panel[1] + lay.panel[3]
                    for (x1, _, w1, _), (x2, _, _, _) in zip(lay.buttons, lay.buttons[1:]):
                        assert x1 + w1 <= x2
                    pick = present_rules.picker_layout(area, button_h=pitches["button_h"])
                    assert pick.view[2] >= 640 and pick.view[3] >= 400
                    bx, by, bw, bh = pick.back
                    assert bx + bw <= pick.backing[0] and by + bh <= ay + ah + 1e-9
    assert cases == 48
    # A 120-code-point statement of W fits 3 lines at ≥ 24 at 150%.
    measure = measure_with(assets, theme.font(28))
    fit = layouts.fit_message("W" * 59 + " " + "W" * 60, 952, layouts.scaled(28, 1.5),
                              measure, max_lines=3, min_size=24, step=2)
    assert len(fit.lines) <= 3 and fit.size >= 24


# --- AC-F25-15 — the screen -------------------------------------------------------------------

def test_ac_f25_15_the_screen():
    w = HostE()
    cfg = w.shell.theme.cfg
    g = w.open(fx.args(at="gate"), value=4)
    w.frame()
    assert near(w.px(300, 345), PANEL_FILL)
    assert near(w.px(60, 94), BAR_FILL) and near(w.px(400, 94), BAR_TRACK)
    texts = {t[0]: t for t in w.texts}
    heading = cfg.panel.heading
    assert texts["Daichi"][2] == heading.text_color
    assert texts["2 / 3"] and texts["Credibility"] and texts["4 / 5"]
    statement = texts["The gate was locked all night. I checked it myself."]
    assert statement[1] == 28 and statement[2] == STATEMENT_GREEN
    assert {"‹ Previous", "Press", "Present", "Next ›"} <= set(texts)
    stage = tuple(round(200 * (1 - w.session.look.stage_dim_opacity) + c
                        * w.session.look.stage_dim_opacity) for c in cfg.menu.dim_color)
    assert near(w.px(1200, 300), stage)
    look = w.session.screen.look_for(g.press)
    assert look.state == "focused" and w.focused() is g.press
    assert near(w.px(g.press.box.x + 1, g.press.box.center[1]),
                cfg.button.focused.border_color, 24)
    # The frame: no heading; the hint.
    assert w.session.frame.heading is None
    assert w.session.hint_text == "Press the witness, or present evidence."
    # Frame 15 of a loss: a #C62828 pixel in x 357.6–436 (meter 5).
    g = w.open(fx.args(at="gate"))
    wrong_pick_by_keys(w, g)
    w.frames(15)
    assert any(w.px(x, y) == LOSS for x in range(358, 436) for y in range(83, 105))
    # The opening picture: testimony on s1, 4 / 5, no marker (AC-F25-11's rows compare it
    # pixel for pixel with a render with nothing focused).
    pic = _opening(w, fx.args(at="gate"), value=4)
    w.open(fx.args(at="gate"), value=4, by=InputKind.MOUSE)
    assert pygame.image.tobytes(pic, "RGB") == pygame.image.tobytes(w.ui.framebuffer, "RGB")
    # Present activated: the very next picture is picker mode (backing panel, view, Back).
    g = w.open(fx.args(at="gate"))
    w.frame(*RIGHT)
    w.frame(*ENTER)
    assert g.mode == "picker"
    drawn = [t[0] for t in w.texts]
    assert "Back" in drawn and "Brass Key" in drawn and "Daichi" not in drawn
    assert near(w.px(640, 30), PANEL_FILL)


# --- AC-F25-16 — tokens, words, and long text -------------------------------------------------

def _rect(box: Box) -> tuple:
    return (box.x, box.y, box.w, box.h)


def _contrast(a, b) -> float:
    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (ch(v) for v in c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_ac_f25_16_tokens_words_and_long_text(tmp_path):
    w = configured(tmp_path, '[words.plugin.present_evidence]\nhint = "Appuie ou présente."\n'
                   'title = "Contre-interrogatoire"\n'
                   'hint_picker = "Contre : “{statement}” {0} {}"\n'
                   'previous = "Avant"\nnext = "Après"\npress = "Presser"\n'
                   'present = "Présenter"\nback = "Retour"\nbar_label = "Crédibilité"\n')
    g = w.open(fx.args(at="gate"))
    assert w.session.hint_text == "Appuie ou présente." and w.session.title == \
        "Contre-interrogatoire"
    labels = {t[0] for t in w.texts}
    assert {"Avant", "Après", "Presser", "Présenter", "Crédibilité"} <= labels
    w.frame(*RIGHT)
    w.frame(*ENTER)
    assert w.fatal == []
    assert w.session.hint_text == "Contre : “The gate was locked all night.…” {0} {}"
    assert "Retour" in {t[0] for t in w.texts}
    assert raw_view(g).pick_button.label() == "Présenter"
    # statement.text_size 60 / 10: drawn at 40 / 24 (× the text scale).
    for size, drawn in ((60, 40), (10, 24)):
        w = configured(tmp_path, f"[theme.plugin.present_evidence.statement]\n"
                       f"text_size = {size}\n")
        w.open(fx.args(at="gate"))
        w.frame()
        sizes = {t[1] for t in w.texts if t[0].startswith("The gate")}
        assert sizes == {drawn}, size
        w.shell.painter.set_text_scale(lambda: 1.5)
        w.frame()
        sizes = {t[1] for t in w.texts if t[0].startswith("The gate")}
        assert sizes == {layouts.scaled(drawn, 1.5)}, size
    # bar.fill_color.
    w = configured(tmp_path, '[theme.plugin.present_evidence.bar]\nfill_color = "#102030"\n')
    w.open()
    w.frame()
    assert near(w.px(60, 94), (0x10, 0x20, 0x30), 2)
    # At 150%: a 24-W speaker fitted to 600 with "…" (fit_label); long statements fitted.
    w = HostE()
    w.shell.painter.set_text_scale(lambda: 1.5)
    from engine.ui.paint import fit_label
    statements = {"w": "W" * 59 + " " + "W" * 60, "cjk": "漢" * 120,
                  "emoji": "👨‍👩‍👧 " * 20, "rtl": "שלום " * 24}
    for key, text in statements.items():
        text = text.strip()
        g = w.open(fx.args(testimony={key: text}, answer={key: "brass_key"},
                           speaker="W" * 24))
        canvas = w.ui.canvas
        spec = g.heading_spec
        expect = fit_label("W" * 24, lambda s: canvas.font_handle(spec, s).font,
                           layouts.scaled(spec.size, 1.5), 600)
        assert g.speaker_fit == expect and expect.text.endswith("…") == expect.truncated
        width = canvas.font_handle(spec, expect.size).font.size(expect.text)[0]
        assert width <= 600
        font = lambda s: canvas.font_handle(g.panel_spec, s).font   # noqa: E731
        want = layouts.fit_message(text, g.tlay.statement[2], layouts.scaled(28, 1.5),
                                   lambda t, s: font(s).size(t)[0] if t else 0,
                                   max_lines=3, min_size=24, step=2)
        assert g.fit == want and len(want.lines) <= 3, key
        assert want.truncated == want.lines[-1].endswith("…"), key
        drawn = [t for t in w.texts if t[2] == STATEMENT_GREEN]
        assert [t[0] for t in drawn] == list(want.lines) and {t[1] for t in drawn} == \
            {want.size}
    # Contrast of the default tokens.
    panel = ThemeConfig().panel.fill_color
    assert _contrast(STATEMENT_GREEN, panel) >= 4.5
    assert _contrast(BAR_FILL, BAR_TRACK) >= 3 and _contrast(LOSS, BAR_TRACK) >= 3


# --- AC-F25-17 — settings changed mid-run -----------------------------------------------------

def test_ac_f25_17_settings_changed_mid_run(monkeypatch):
    w = HostE()
    painter = w.shell.painter
    # Testimony mode, focus on Next: 150%, then F23's new area.
    g = w.open()
    w.frame(*RIGHT)
    w.frame(*RIGHT)
    before = w.ui.framebuffer.copy()
    painter.set_text_scale(lambda: 1.5)
    w.frame()
    area = w.session.area
    expected = present_rules.testimony_layout(
        area, label_pitch=layouts.pitch(36), name_pitch=layouts.pitch(48),
        statement_pitch=layouts.pitch(42), button_h=layouts.button_height(scale=1.5),
        n_buttons=4, penalty=True)
    assert g.tlay == expected and [_rect(b.box) for b in g.buttons] == list(expected.buttons)
    assert w.focused() is g.next and g.stmt == 0
    painter.set_text_scale(None)
    w.frame()
    assert pygame.image.tobytes(w.ui.framebuffer, "RGB") == pygame.image.tobytes(before, "RGB")
    # Picker by keys, Festival Map selected: 150% builds once, keeps the selection, focuses
    # the view's default widget, and moves Back.
    for by in (InputKind.KEYS, InputKind.MOUSE):
        painter.set_text_scale(None)
        g = w.open(fx.args(at="gate"), by=by)
        if by is InputKind.KEYS:
            for keys in (RIGHT, ENTER, DOWN):
                w.frame(*keys)
        else:
            w.frame(*click(center(g.present)))
            view = raw_view(g)
            w.frame(*click(_row_center(view, 1)))
            w.frame(H.motion((640, 690)))               # the pointer leaves the widgets
            assert w.focused() is None
        view = raw_view(g)
        assert view.selected == "festival_map"
        builds = g.builds
        painter.set_text_scale(lambda: 1.5)
        w.frame()
        assert g.builds == builds + 1 and view.selected == "festival_map"
        assert w.focused() is (view.list if by is InputKind.KEYS else None)
        bottom = w.session.area.bottom
        assert _rect(g.back.box) == (24, bottom - layouts.button_height(scale=1.5), 180,
                                     layouts.button_height(scale=1.5))
    painter.set_text_scale(None)
    # Reduced motion on, then a wrong pick: AC-F25-09's reduced column (frame 39: no hatch).
    w.shell.reduce_motion = True
    g = w.open(fx.args(at="gate"))
    wrong_pick_by_keys(w, g)
    w.frames(39)
    assert w.hatch() == [] and w.value() == "4 / 5"
    # I-9: reduced motion switched on at frame 39 of a loss: no hatch from frame 40; the
    # finish still at 60 ± 1.
    w.shell.reduce_motion = False
    g = w.open(fx.args(at="gate"))
    wrong_pick_by_keys(w, g)
    w.frames(39)
    assert w.hatch() != []
    w.shell.reduce_motion = True
    n = 39
    while not g.finishes:
        w.frame()
        n += 1
        assert w.hatch() == [] or g.finishes
    assert abs(n - 60) <= 1
    w.shell.reduce_motion = False
    # layout(area) alone: recomputed once, at the next draw, never before.
    g = w.open()
    fits = g.fits_made
    w.host.call(g.layout, w.session.area)
    assert g.fits_made == fits and g.t_dirty
    w.frame()
    assert g.fits_made == fits + 1 and not g.t_dirty
    w.frame()
    assert g.fits_made == fits + 1
    assert w.fatal == []


# --- AC-F25-19 — A5's ctx.story and A6's codex_view contract (Host U) -------------------------

def test_ac_f25_19_ctx_story_and_the_codex_view_contract(game):
    from tests.minigames.host_u import HostU
    from tests.minigames.test_host import running
    assert api.CodexFilter is CodexFilter and api.PickAction is PickAction
    assert {"CodexFilter", "PickAction"} <= set(api.__all__)
    w = HostU(game)
    b = w.behavior

    class Sub(CodexFilter):
        pass

    class Text(str):
        pass

    def calls(filter_, pick=None):
        def on_start(ctx):
            b.view = ctx.codex_view(filter=filter_, pick=pick)
        return on_start

    bad = [{"kinds": {"item"}}, Sub(frozenset({"item"})), CodexFilter(frozenset()),
           CodexFilter(frozenset({"item", "x"})),
           CodexFilter(frozenset({"item"}), frozenset(f"c{i}" for i in range(25))),
           CodexFilter(frozenset({"item"}), frozenset({"x" * 25})),
           CodexFilter(frozenset({"item"}), frozenset({Text("Evidence")}))]
    picks = [PickAction(3, lambda name: None), PickAction("Show", 5)]
    for filter_, pick in [(f, None) for f in bad] + [
            (CodexFilter(frozenset({"item"})), p) for p in picks]:
        w.host.abandon()
        b.reset()
        w.fatal.clear()
        b.on_start = calls(filter_, pick)
        w.start()
        assert len(w.fatal) == 1 and w.fatal[0].code == "E275", (filter_, pick)
    # The pick word: cleaned by SEC-F23-07's rule and cut to 200.
    w.host.abandon()
    b.reset()
    w.fatal.clear()
    b.on_start = calls(CodexFilter(frozenset({"item"})),
                       PickAction("Pre\x00sent" + "x" * 300, lambda name: None))
    running(w, items=("coin",))
    word = b.view._target.pick.word
    assert "\x00" not in word and len(word) <= 200 and word.startswith("Pre")
    # A valid call with its groups in the scope: the host draws them after the plugin's
    # draw; CodexView.draw draws no scope widget. A pick runs inside the delivering call.
    w.host.abandon()
    b.reset()
    order: list[str] = []
    depth: list[int] = []
    raise_pick = []

    def on_pick(name):
        depth.append(w.host._depth)
        if raise_pick:
            raise ValueError("boom")
        b.ctx.finish(name)

    def on_start(ctx):
        view = ctx.codex_view(filter=CodexFilter(frozenset({"item"})),
                              pick=PickAction("Show", on_pick))
        groups = view.build(ctx.area, 1.0)
        ctx.scope.set_groups(groups)
        ctx.scope.set_default(view.default_widget())
        b.view = view
        b.painter = ctx.painter

    b.on_start = on_start
    running(w, items=("coin",))
    view = b.view._target
    for widget in w.session.scope.widgets():
        real = widget.draw
        widget.draw = (lambda p, look, _real=real: order.append("widget") or _real(p, look))
    plugin = w.session.plugin
    real_draw = plugin.draw

    def plugin_draw(canvas):
        order.append("plugin")
        real_draw(canvas)
        mark = len(order)
        b.view.draw(canvas, b.painter)
        assert len(order) == mark                     # the view drew no widget
        order.append("view")

    plugin.draw = plugin_draw
    w.frame()
    assert order[:2] == ["plugin", "view"] and set(order[2:]) == {"widget"} and order[2:]
    for key in (pygame.K_RETURN, pygame.K_RETURN):
        w.frame(H.key(key))
    w.frames(25)
    assert depth == [1] and [d.result for d in w.done()] == ["coin"]
    # One that raises: E275 naming the script line.
    w.host.abandon()
    b.reset()
    w.fatal.clear()
    raise_pick.append(True)
    b.on_start = on_start
    running(w, items=("coin",))
    for key in (pygame.K_RETURN, pygame.K_RETURN):
        w.frame(H.key(key))
    assert len(w.fatal) == 1 and w.fatal[0].code == "E275" and w.fatal[0].line == 9
    # ctx.story is StartMinigame.names; a worker thread gets MinigameThreadError, as does a
    # LedgerCodexPort method (07 I-9).
    w.host.abandon()
    b.reset()
    w.fatal.clear()
    b.on_start = on_start
    cmd = w.start(items=("coin",))
    ctx = w.session.ctx
    assert ctx.story is cmd.names
    port = b.view._target.port
    errors = []

    def worker():
        for fn in (lambda: ctx.story, port.items, port.entries, lambda: port.picture("x")):
            try:
                fn()
            except MinigameThreadError as e:
                errors.append(e)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=10)
    assert len(errors) == 4


# --- AC-F25-20 — A7: the focus default (the Host U row) ---------------------------------------

def test_ac_f25_20_focus_default_host_row(game):
    from engine.ui.focus import FocusGroup
    from engine.ui.widgets import Button
    from tests.minigames.host_u import HostU
    w = HostU(game)
    b = w.behavior
    for by, expect_third in ((InputKind.KEYS, True), (InputKind.MOUSE, False)):
        w.host.abandon()
        b.reset()
        buttons = [Button(lambda i=i: f"B{i}", lambda: None) for i in range(3)]

        def on_start(ctx, buttons=buttons):
            for i, button in enumerate(buttons):
                button.box = Box(100 + 240 * i, 300, 220, 56)
            ctx.scope.set_groups([FocusGroup(buttons)])
            ctx.scope.set_default(buttons[2])

        b.on_start = on_start
        w.shell.stack.last_input = by
        w.start(restored=False)
        s = w.session
        assert s.phase is Phase.OPENING and s.scope.focused is None
        for _ in range(60):
            if s.phase is Phase.RUNNING:
                break
            w.frame()
        assert s.phase is Phase.RUNNING
        assert s.scope.focused is (buttons[2] if expect_third else None)


# --- AC-F25-23 — CI guard: costs --------------------------------------------------------------

def test_ac_f25_23_costs(monkeypatch):
    fits: list[str] = []
    real_fit = present_evidence.fit_message
    monkeypatch.setattr(present_evidence, "fit_message",
                        lambda text, *a, **k: fits.append(text) or real_fit(text, *a, **k))
    w = HostE()
    renders: list[tuple] = []
    cache = w.shell.assets.cache
    real_put = cache.put

    def put(key, *args, **kwargs):
        if key and key[0] == "text":
            renders.append(key)
        return real_put(key, *args, **kwargs)

    monkeypatch.setattr(cache, "put", put)
    surfaces: list[tuple] = []
    real_surface = pygame.Surface

    class CountedSurface(real_surface):
        def __init__(self, *a, **k):
            surfaces.append(a[:1])
            super().__init__(*a, **k)

    g = w.open()
    w.frame()
    fits.clear()
    renders.clear()
    builds = w.shell.painter.builds
    monkeypatch.setattr(pygame, "Surface", CountedSurface)
    bar_colors = {BAR_FILL, BAR_TRACK, w.game.border_color}
    for _ in range(600):
        w.frame()
        assert len([f for f in w.fills if f[0] in bar_colors]) <= 12
    monkeypatch.setattr(pygame, "Surface", real_surface)
    assert fits == [] and renders == [] and w.shell.painter.builds == builds
    assert surfaces == []
    # A statement change: one fit at the next draw.
    w.host.call(g._next)
    assert fits == []
    w.frame()
    assert len(fits) == 1
    # A full-width loss: penalty_max 20, meter 20, cost 20 → ≤ 420 hatch fills a frame.
    w20 = HostE(meter=(0, 20))
    g = w20.open(fx.args(at="gate", penalty_max=20, cost=20), value=20)
    wrong_pick_by_keys(w20, g)
    most = 0
    while not g.finishes:
        w20.frame()
        most = max(most, len(w20.hatch()))
    assert 0 < most <= 420
    # The checks on the largest args: under 5 ms.
    big = fx.big_args()
    names = dataclasses.replace(fx.STORY_S, meters=("credibility",),
                                items=tuple(f"item_{i}" for i in range(8)),
                                item_categories=tuple((f"Category {i}", (f"item_{i % 8}",))
                                                      for i in range(24)))
    began = time.perf_counter()
    assert present_rules.problem(big) is None
    present_rules.story_problem(big, names)
    assert time.perf_counter() - began < 0.005


# --- AC-F25-25 — sounds (Could) ----------------------------------------------------------------

def test_ac_f25_25_sounds(tmp_path):
    def plays(w: HostE) -> list[str]:
        return [c[1] for c in w.audio.calls if c[0] == "play_ui"]

    w = configured(tmp_path, '[theme.plugin.present_evidence]\npress_sound = "sfx/press.ogg"\n'
                   'present_sound = "sfx/present.ogg"\n')
    g = w.open()
    w.frame(*ENTER)                                         # Press
    assert g.finishes == [fx.PRESS] and plays(w) == ["sfx/press.ogg"]
    for wrong in (False, True):
        w.audio.calls.clear()
        g = w.open(fx.args(at="gate"))
        if wrong:
            wrong_pick_by_keys(w, g)
            w.frames(61)                                    # the loss, then the finish
        else:
            for keys in (RIGHT, ENTER, ENTER, ENTER):       # Present, Brass Key, the pick
                w.frame(*keys)
        assert g.finishes == [WRONG if wrong else WIN] and plays(w) == ["sfx/present.ogg"]
    # The defaults play nothing.
    w = HostE()
    g = w.open()
    w.frame(*ENTER)
    assert g.finishes == [fx.PRESS] and plays(w) == []
