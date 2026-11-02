"""F24-3: the poem game played on screen (F24 ``06``: AC-F24-07, 08, 09, 10, 11, 14, 15, 18,
21). One test per AC, its rows inside. AC-F24-13 (fit) is a pure test in
``test_poem_rules.py``.

**Host P** (``06`` §0.2): F23's Host U pieces (``MinigameHost`` and ``MinigameScreen`` on
F10's unit canvas, SDL dummy, 1280×720, default theme, fake clock 1/60 s, an Audio spy, a
post sink, a ``fatal`` recorder) with ``PoemGame``'s signature from ``BUNDLED`` (no Loader
L), the meters D, and ``where(sid)`` → ``script/main.vns`` line 16. Sessions start as a cut
(``restored``) unless a row needs the opening fade. The button sounds are set so the
activation sound can be counted (``shell.sounds``).

Config rows build F23 s5b's ``PluginTables`` from a ``config.toml`` (``configured``); the W64
row (a missing ``page.paper_image``, 07 I-5) is met by F23 s5b's ``ctx.gui_image``.
"""

import dataclasses
import logging
import threading
from types import MappingProxyType

import pygame
import pytest

from engine.core.config import load_config
from engine.core.config_schema import ThemeConfig
from engine.core.minigame_types import MeterChange, Outcome, StoryNames
from engine.core.paths import GamePaths
from engine.minigames import api
from engine.minigames.bundled import BUNDLED, poem_game, poem_rules
from engine.minigames.bundled.poem_game import PoemGame, WordSlot
from engine.minigames.context import DiceHandle
from engine.minigames.host import HostPorts, MinigameHost, Phase
from engine.minigames.registry import Registry
from engine.minigames.screen import MinigameScreen
from engine.minigames.tables import PluginTables
from engine.runtime.commands import MeterView, MinigameBase, MinigameDone, StartMinigame
from engine.runtime.minigame import entry_check
from engine.runtime.points import Points
from engine.script.points import MeterSpec
from engine.ui.nav import InputKind
from tests.fakes.ui_shell import SolidScreen, UiHarness
from tests.minigames.host_u import INDEX, AudioSpy, CueSpy, HostShell
from tests.render.conftest import make_assets

H = UiHarness
D = ("sayori", "natsuki", "yuri", "monika")
W8 = {"sunshine": {"sayori": 3, "natsuki": 1}, "candy": {"natsuki": 3},
      "melancholy": {"yuri": 3, "sayori": 1}, "whisper": "yuri", "blank": {},
      "zero": {"monika": 0}, "ribbon": {"sayori": 2}, "lantern": {"yuri": 1, "natsuki": 1}}
W12 = dict.fromkeys(["alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
                     "india", "juliett", "kilo", "lima"], "yuri")
P16 = {"words": W8, "rounds": 2, "page_words": 3}
WHERE = ("script/main.vns", 16)
ACTIVATE = "sfx/activate.ogg"
GAP = 13                                     # frames between picks (06 AC-F24-07)
PAGE_FILL = (0xFF, 0xFD, 0xF6)
POINTS = Points(tuple(MeterSpec(m, 0, 100, 0, True) for m in D))
NAMES = StoryNames(D, (), (), ())
ENTRY = api.declarations(BUNDLED[0], "engine")            # PoemGame, from BUNDLED


def _theme(**button) -> ThemeConfig:
    cfg = ThemeConfig()
    return dataclasses.replace(cfg, button=dataclasses.replace(
        cfg.button, focus_sound="sfx/focus.ogg", activate_sound=ACTIVATE, **button))


SOUNDS = _theme()


@pytest.fixture(scope="module", autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


class HostP:
    """One Host P world (06 §0.2): ``entry`` is the registered minigame (the poem's by
    default); ``config``/``tables`` give ``[words.plugin]`` and ``[theme.plugin]``."""

    def __init__(self, *, cfg=SOUNDS, dev=True, reduce_motion=False, assets=None,
                 entry=ENTRY, config=None, tables=None) -> None:
        self.registry = Registry(main_thread=threading.get_ident())
        self.registry.add(entry)
        self.shell = HostShell(dev=dev, reduce_motion=reduce_motion, cfg=cfg, assets=assets,
                               config=config)
        self.ui = UiHarness(self.shell)
        self.shell.stack.push(SolidScreen((200, 200, 200)))
        self.posted: list = []
        self.fatal: list = []
        self.audio = AudioSpy()
        self.ports = HostPorts(
            shell=self.shell, lookup=self.registry.get, post=self.posted.append,
            where=lambda sid: WHERE, fatal=self.fatal.append, check_meter=POINTS.spec,
            check_entry=entry_check(INDEX), index=lambda: INDEX, audio=self.audio,
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

    def start(self, args=None, *, seed=42, by=InputKind.KEYS, restored=True, run=1,
              name="poem_game", skippable=False) -> StartMinigame:
        self.shell.stack.last_input = by
        args = dict(P16 if args is None else args)
        base = MinigameBase(tuple(MeterView(m, 0, 0, 100) for m in D), (), ())
        cmd = StartMinigame("main.vns:16", run, name, MappingProxyType(args), seed, base,
                            skippable, restored, NAMES)
        self.host.start(cmd)
        return cmd

    def frame(self, *events):
        self.texts.clear()
        self.fills.clear()
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
    def game(self) -> PoemGame:
        return self.host.session.plugin

    @property
    def scope(self):
        return self.host.session.scope

    def words(self) -> list[str]:
        g = self.game
        return [g.poem.entries[e].word for e in g.page]

    def counter(self) -> str | None:
        found = [t[0] for t in self.texts if " / " in t[0]]
        return found[-1] if found else None

    def focused(self) -> int | None:
        w = self.scope.focused
        return None if w is None else w.index

    def done(self) -> list[MinigameDone]:
        return [e for e in self.posted if isinstance(e, MinigameDone)]

    def used(self) -> list:
        return [e for e in self.posted if type(e).__name__ == "MinigameUsed"]

    def activations(self) -> int:
        return self.shell.sounds.count(ACTIVATE)


def running(w: HostP, args=None, **kwargs) -> HostP:
    w.start(args, **kwargs)
    w.frame()
    assert w.session is not None and w.session.phase is Phase.RUNNING, w.fatal
    return w


def center(w: HostP, i: int) -> tuple[float, float]:
    return w.game.slots[i].box.center


def expected(picked_words: list[str], args=None) -> Outcome:
    poem = poem_rules.parse(dict(P16 if args is None else args))
    index = [e.word for e in poem.entries]
    picked = [index.index(word) for word in picked_words]
    meters = poem_rules.named_meters(poem, D)
    totals = poem_rules.score(poem, picked, meters)
    return Outcome(poem_rules.result_of(poem, picked, totals),
                   poem_rules.changes_of(poem, totals))


class RandomSpy:
    """A call spy on ``ctx.random`` (every ``DiceHandle`` method)."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list[tuple[str, tuple]] = []
        for name in ("roll", "pick", "decimal", "shuffle"):
            real = getattr(DiceHandle, name)

            def spy(handle, *args, _real=real, _name=name, **kwargs):
                self.calls.append((_name, tuple(list(a) if type(a) is list else a
                                                for a in args)))
                return _real(handle, *args, **kwargs)

            monkeypatch.setattr(DiceHandle, name, spy)


# --- AC-F24-07 — a poem by each input device ---------------------------------------------------

def _keys(w: HostP) -> None:
    w.frame(H.key(pygame.K_DOWN))
    w.frame(H.key(pygame.K_RETURN))


def _pad(button: int) -> list:
    return [H.pad(button), H.pad(button, up=True)]


@pytest.mark.parametrize("device", ["keyboard", "mouse", "gamepad", "reduced_motion"])
def test_ac07_a_poem_by_each_device(device):
    args = dict(P16)
    if device == "mouse":
        args["result"] = "totals"
    elif device == "gamepad":
        args.update(to_points=False, result="words")
    by = InputKind.MOUSE if device == "mouse" else InputKind.KEYS

    def play(w: HostP) -> tuple[list, list[str], list[pygame.Surface]]:
        frames = []

        def frame(*events):
            frames.append(w.frame(*events).copy())

        running(w, args, by=by)
        frames.append(w.ui.framebuffer.copy())
        page1 = w.words()
        assert len(set(page1)) == 3 and w.counter() == "0 / 2"
        picks = []
        steps = {"keyboard": [[H.key(pygame.K_DOWN)], [H.key(pygame.K_RETURN)]],
                 "gamepad": [_pad(pygame.CONTROLLER_BUTTON_DPAD_DOWN),
                             _pad(pygame.CONTROLLER_BUTTON_A)]}
        steps["reduced_motion"] = steps["keyboard"]
        for turn in range(2):
            if device == "mouse":
                slot = (0, 2)[turn]
                frame(H.motion(center(w, slot)))
                picks.append(w.words()[slot])
                frame(H.down(center(w, slot)), H.up(center(w, slot)))
            else:
                if turn == 1 and device == "gamepad":
                    frame(_stick(32767))
                    frame(_stick(0))
                elif turn == 1:
                    frame(H.key(pygame.K_RIGHT))
                else:
                    frame(*steps[device][0])
                picks.append(w.words()[w.focused()])
                frame(*steps[device][1])
            if turn == 0:
                assert w.counter() == "1 / 2" and len(set(w.words())) == 3
                assert picks[0] not in w.words()
                for _ in range(GAP):
                    frame()
        for _ in range(30):
            frame()
        return picks, page1, frames

    w = HostP()
    picks, page1, frames = play(w)
    assert len(w.done()) == 1, w.fatal
    done = w.done()[0]
    assert Outcome(done.result, done.changes) == expected(picks, args)
    assert [c.name for c in done.changes] == [m for m in D if m in [c.name for c in done.changes]]
    assert w.activations() == 2                                   # the host's, one per pick
    assert not [c for c in w.audio.calls if c[0] == "play_ui"]    # the game plays none (Q-b)
    if device == "reduced_motion":
        calm = HostP(reduce_motion=True)
        picks2, page2, frames2 = play(calm)
        assert (picks2, page2) == (picks, page1)
        running_frames = len(frames) - 31                 # before the last pick's frame
        for a, b in zip(frames[:running_frames], frames2[:running_frames]):
            assert pygame.image.tobytes(a, "RGB") == pygame.image.tobytes(b, "RGB")


def _stick(value: int):
    from engine.ui.input import UiEvent
    return UiEvent(pygame.event.Event(pygame.CONTROLLERAXISMOTION, instance_id=0,
                                      axis=pygame.CONTROLLER_AXIS_LEFTX, value=value),
                   None, False)


# --- AC-F24-08 — focus and the F23 fallbacks ---------------------------------------------------

P5 = {"words": W8, "rounds": 2, "page_words": 5}
TAB, SHIFT_TAB = H.key(pygame.K_TAB), H.key(pygame.K_TAB, pygame.KMOD_SHIFT)


@pytest.mark.parametrize("row", ["by_enter", "by_click", "tab", "arrows", "enter_pick",
                                 "click_pick", "wheel_unused", "wheel_used", "menu_inputs",
                                 "fallbacks"])
def test_ac08_focus_and_the_f23_fallbacks(row, monkeypatch):
    w = HostP()
    by = InputKind.MOUSE if row in ("by_click", "click_pick", "wheel_unused") else \
        InputKind.KEYS
    running(w, P5, by=by)
    screen = w.session.screen
    if row == "by_enter":
        assert w.focused() == 0 and w.scope.visible and w.used() == []
    elif row == "by_click":
        assert w.focused() is None
        w.frame(H.key(pygame.K_DOWN))
        assert w.focused() == 0 and len(w.used()) == 1
    elif row == "tab":
        seen = []
        for _ in range(5):
            w.frame(TAB)
            seen.append(w.focused())
        assert seen == [1, 2, 3, 4, 0]
        seen = []
        for _ in range(5):
            w.frame(SHIFT_TAB)
            seen.append(w.focused())
        assert seen == [4, 3, 2, 1, 0]
    elif row == "arrows":
        slots = w.game.slots
        for start, key, end in ((0, pygame.K_UP, 2), (2, pygame.K_DOWN, 0),
                                (1, pygame.K_RIGHT, 4), (2, pygame.K_RIGHT, 4),
                                (3, pygame.K_LEFT, 0)):
            w.scope.focus(slots[start], InputKind.KEYS, sound=False)
            w.frame(H.key(key))
            assert w.focused() == end, (start, key)
    elif row == "enter_pick":
        w.frame(H.key(pygame.K_DOWN))
        w.frame(H.key(pygame.K_DOWN))
        before = w.words()
        w.frame(H.key(pygame.K_RETURN))
        assert w.counter() == "1 / 2" and w.words() != before and w.focused() == 2
    elif row == "click_pick":
        pos = center(w, 3)
        w.frame(H.motion(pos))
        w.frame(H.down(pos), H.up(pos))
        assert w.counter() == "1 / 2" and w.focused() == 3
        w.frames(3)
        assert w.focused() == 3                     # the pointer stays: focus follows it
    elif row == "wheel_unused":
        w.frame(H.motion(center(w, 0)))
        assert screen.handle_event(H.wheel(center(w, 0), 1)) is False   # F14's StepBack
        assert w.used() == []
    elif row == "wheel_used":
        w.frame(H.key(pygame.K_DOWN))
        assert len(w.used()) == 1                   # posted before the wheel's StepBack
        assert screen.handle_event(H.wheel(center(w, 1), 1)) is False
    elif row == "menu_inputs":                      # right click, east, Esc: the game menu
        for event in (H.down(center(w, 0), 3), H.pad(pygame.CONTROLLER_BUTTON_B),
                      H.key(pygame.K_ESCAPE)):
            assert screen.handle_event(event) is False
        assert w.used() == []
    else:                                           # Backspace, Page Up, LB: F23's fallbacks
        answers = []
        real = PoemGame.handle_event

        def spy(game, ev):
            answers.append(real(game, ev))
            return answers[-1]

        monkeypatch.setattr(PoemGame, "handle_event", spy)
        got = [screen.handle_event(e) for e in (
            H.key(pygame.K_BACKSPACE), H.key(pygame.K_PAGEUP),
            H.pad(pygame.CONTROLLER_BUTTON_LEFTSHOULDER))]
        assert answers == [False, False, False]
        assert got == [True, False, False]          # Backspace: nothing; the others: F14
        assert w.used() == []


# --- AC-F24-09 — double-press guard -------------------------------------------------------------

W7 = {"words": W8, "rounds": 5, "page_words": 3}


@pytest.mark.parametrize("row", ["first_frame", "11_frames", "12_frames", "13_frames",
                                 "double_click"])
def test_ac09_double_press_guard(row):
    w = HostP()
    if row == "double_click":
        running(w, W7, by=InputKind.MOUSE)
        pos = center(w, 0)
        w.frame(H.motion(pos))
        w.frame(H.down(pos), H.up(pos))
        w.frames(2)
        w.frame(H.down(pos), H.up(pos))
        assert len(w.game.picked) == 1 and w.counter() == "1 / 5"
        return
    w.start(W7)                                     # the first running frame: accepted
    w.frame(H.key(pygame.K_RETURN))
    assert len(w.game.picked) == 1 and w.counter() == "1 / 5"
    if row == "first_frame":
        return
    gap = {"11_frames": 10, "12_frames": 11, "13_frames": 12}[row]
    w.frames(gap)                                   # + the pick's own frame's update
    before = w.words()
    w.frame(H.key(pygame.K_RETURN))
    if row == "11_frames":                          # 183 ms: ignored (its sound still plays)
        assert len(w.game.picked) == 1 and w.counter() == "1 / 5" and w.words() == before
    else:                                           # 200 ms (I-6) and 217 ms: accepted
        assert len(w.game.picked) == 2 and w.counter() == "2 / 5"


# --- AC-F24-10 — same poem on replay ------------------------------------------------------------

W8_INDEX = {word: i for i, word in enumerate(W8)}


def test_ac10_same_poem_on_replay(monkeypatch):
    spy = RandomSpy(monkeypatch)

    def poem(seed: int) -> tuple[list[list[str]], MinigameDone]:
        w = HostP()
        running(w, seed=seed)
        pages = [w.words()]
        w.frame(H.key(pygame.K_RETURN))
        pages.append(w.words())
        w.frames(GAP)
        w.frame(H.key(pygame.K_RETURN))
        w.frames(30)
        return pages, w.done()[0]

    pages, done = poem(42)
    assert [name for name, _ in spy.calls] == ["shuffle", "shuffle"]
    first = list(range(8))
    picked = W8_INDEX[pages[0][0]]
    assert spy.calls[0][1] == (first,)
    assert spy.calls[1][1] == ([i for i in first if i != picked],)       # list order
    again, done2 = poem(42)
    assert (again, done2.result, done2.changes) == (pages, done.result, done.changes)
    other, _ = poem(43)
    assert other[0] != pages[0]                     # the two seeds' first pages differ
    for restored in (True, False):                  # a load / a back landing on P
        w = HostP()
        w.start(seed=42, by=InputKind.MOUSE, restored=restored)
        w.frames(25)
        assert (w.words(), w.counter(), w.focused()) == (pages[0], "0 / 2", None)


# --- AC-F24-11 — settings changed mid-poem ------------------------------------------------------

@pytest.mark.parametrize("row", ["text_150", "reduce_motion", "layout_alone"])
def test_ac11_settings_changed_mid_poem(row, monkeypatch):
    spy = RandomSpy(monkeypatch)
    fits: list[str] = []
    real_fit = poem_game.fit_label

    def fit_spy(text, *args, **kwargs):
        fits.append(text)
        return real_fit(text, *args, **kwargs)

    monkeypatch.setattr(poem_game, "fit_label", fit_spy)
    w = running(HostP())
    w.frame(H.key(pygame.K_DOWN))
    w.frame(H.key(pygame.K_RETURN))
    w.frames(GAP)
    words, shuffles = w.words(), len(spy.calls)
    before = pygame.image.tobytes(w.frame(), "RGB")
    assert w.focused() == 1 and w.counter() == "1 / 2"
    if row == "text_150":
        w.shell.painter.set_text_scale(lambda: 1.5)
        w.frame()
        g = w.game
        a = w.session.area
        lay = poem_rules.page_layout((a.x, a.y, a.w, a.h), max_width=800, n=3, pitch=67,
                                     counter_h=poem_rules.line_pitch(42))
        assert g.lay == lay and g.word_px == 48
        for slot, cell in zip(g.slots, lay.cells):
            assert slot.box.y == cell[1] and slot.box.h == cell[3]
            assert slot.box.center[0] == cell[0] + cell[2] / 2
        assert (w.focused(), w.words(), w.counter()) == (1, words, "1 / 2")
        assert len(spy.calls) == shuffles
        w.shell.painter.set_text_scale(None)
        assert pygame.image.tobytes(w.frame(), "RGB") == before
    elif row == "reduce_motion":
        assert w.game.reduce is False
        w.shell.reduce_motion = True
        assert pygame.image.tobytes(w.frame(), "RGB") == before
        assert w.game.reduce is True
        w.shell.reduce_motion = False
        assert pygame.image.tobytes(w.frame(), "RGB") == before
        assert w.game.reduce is False
    else:                                           # F23's resize path: layout(area) alone
        fits.clear()
        w.game.layout(w.session.area)
        assert fits == []                           # never before the draw …
        w.frame()
        assert len(fits) == 3 and pygame.image.tobytes(w.ui.framebuffer, "RGB") == before
        w.frame()
        assert len(fits) == 3                       # … and once


# --- AC-F24-14 — the page, word states, and opening picture -------------------------------------

P12 = {"words": W12, "rounds": 2, "page_words": 10}
RULES = [106.5 + 53 * k for k in range(10)]
INK = (0x3A, 0x2E, 0x39)


def near(a, b, tol: int = 8) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def far(a, b, by: int = 64) -> bool:
    return any(abs(x - y) > by for x, y in zip(a, b))


@pytest.mark.parametrize("row", ["page", "focused_patched", "press_and_last", "opening"])
def test_ac14_the_page_word_states_and_opening_picture(row):
    cfg = SOUNDS
    if row == "focused_patched":
        cfg = dataclasses.replace(SOUNDS, button=dataclasses.replace(
            SOUNDS.button, focused=dataclasses.replace(SOUNDS.button.focused,
                                                       fill_color=PAGE_FILL)))
    w = HostP(cfg=cfg)
    if row == "opening":
        w.start(P12, restored=False)
        opening = w.session.opening.copy()
        slot0 = w.game.slots[0].box
        cx, cy = slot0.x + 15, slot0.center[1]                    # the marker's place
        assert near(opening.get_at((round(cx), round(cy)))[:3], PAGE_FILL)   # no marker
        w.game.opened = True                                      # a render of page 1 …
        w.scope.visible = False                                   # … with focus hidden
        hidden = w.host._offscreen((1280, 720), w.session.screen.draw_running)
        assert pygame.image.tobytes(hidden, "RGB") == pygame.image.tobytes(opening, "RGB")
        w.scope.visible = True
        w.frames(25)                                              # the fade-in, then RUNNING
        assert w.session.phase is Phase.RUNNING and w.focused() == 0
        assert far(w.px(cx, cy), PAGE_FILL)                       # the marker now
        frame = w.session.frame
        assert frame.heading is None and frame.hint_lines == ("Pick a word for your poem.",)
        return
    running(w, P12)
    w.frame()
    g = w.game
    slots = g.slots
    if row == "page":
        assert near(w.px(280, 600), PAGE_FILL)
        assert near(w.px(312, 400), (0xE8, 0xA0, 0xA0)) and near(w.px(313, 400),
                                                                 (0xE8, 0xA0, 0xA0))
        rules = [r for c, r in w.fills if c == (0xC9, 0xD8, 0xEE)]
        assert [r[1] for r in rules] == RULES and {r[3] for r in rules} == {1}
        counter = [t for t in w.texts if t[0] == "0 / 2"]
        assert counter == [("0 / 2", 28, INK, (1008, 56), "topright")]
        drawn = [t for t in w.texts if t[0] in W12]
        assert sorted(t[0] for t in drawn) == sorted(w.words())   # each word once
        assert [t[2] for t in drawn if t[0] != w.words()[0]] == [INK] * 9   # at rest
        assert w.px(1100, 300) == w.px(1270, 300) and far(w.px(1100, 300), PAGE_FILL, 0)
        rest = slots[1].box
        assert near(w.px(rest.x + 2, rest.y + 2), PAGE_FILL)      # no fill at rest
        box = slots[0].box
        focused = SOUNDS.button.focused
        assert near(w.px(box.x + 8, box.bottom - 10), focused.fill_color)
        return
    box = slots[0].box
    if row == "focused_patched":
        border, marker = w.px(box.x + 1, box.center[1]), w.px(box.x + 15, box.center[1])
        assert near(w.px(box.x + 8, box.bottom - 10), PAGE_FILL)
        assert far(border, PAGE_FILL) and far(marker, PAGE_FILL)
        return
    page1 = w.words()
    w.frame(H.key(pygame.K_RETURN))                               # the press frame …
    box = slots[0].box                                            # (the new word's box)
    assert near(w.px(box.x + 8, box.bottom - 10), SOUNDS.button.pressed.fill_color)
    assert w.counter() == "1 / 2" and w.words() != page1          # … is page 2 already
    w.frames(GAP)
    page2 = w.words()
    w.frame(H.key(pygame.K_RETURN))                               # the last pick
    assert w.session.phase is Phase.CLOSING
    assert w.counter() == "2 / 2"                                 # the last frame
    assert sorted(t[0] for t in w.texts if t[0] in W12) == sorted(page2)


# --- AC-F24-15 — tokens, words, and long labels ------------------------------------------------

LONG = ["W" * 24, "春の雨", "🌸", "שלום"]


def configured(tmp_path, text: str, *, dev: bool = True) -> HostP:
    """Host P over a game folder holding ``config.toml`` (``text``) and ``gui/bg.png``
    (solid (10, 200, 10)): F23 s5b's ``PluginTables`` checks ``[theme.plugin]`` and
    ``[words.plugin]`` against the poem's declarations, as ``install_minigames`` does."""
    root = tmp_path / "game"
    (root / "gui").mkdir(parents=True, exist_ok=True)
    image = pygame.Surface((64, 48))
    image.fill((10, 200, 10))
    pygame.image.save(image, str(root / "gui" / "bg.png"))
    (root / "config.toml").write_text(text, encoding="utf-8")
    paths = GamePaths.for_game(root)
    result = load_config(paths)
    assert result.errors == [], [e.format() for e in result.errors]
    tables = PluginTables(result.config.theme.plugin, result.config.words.plugin, SOUNDS,
                          dev=dev)
    tables.check([ENTRY])
    return HostP(assets=make_assets(paths), config=result.config, tables=tables, dev=dev)


@pytest.mark.parametrize("row", [
    "words", "fill", "max_width", "sizes", "paper", "paper_missing", "long_labels", "w64"])
def test_ac15_tokens_words_and_long_labels(row, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    theme = "[theme.plugin.poem_game.{}]\n{} = {}\n".format
    if row == "words":
        w = running(configured(tmp_path, '[words.plugin.poem_game]\nhint = "Choisis un mot."\n'
                                         'title = "Poème"\n'))
        assert w.session.frame.hint_lines == ("Choisis un mot.",)
        assert w.session.title == "Poème"                        # the save description's
    elif row == "fill":
        w = running(configured(tmp_path, theme("page", "fill_color", '"#102030"')))
        assert near(w.px(280, 600), (0x10, 0x20, 0x30))
    elif row == "max_width":
        for width, page in ((2000, (24, 1232)), (100, (360, 560))):
            caplog.clear()
            w = running(configured(tmp_path, theme("page", "max_width", width)))
            assert (w.game.lay.page[0], w.game.lay.page[2]) == page
            assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    elif row == "sizes":
        w = running(configured(tmp_path, theme("word", "text_size", 60)
                               + theme("counter", "text_size", 10)))
        assert w.game.word_px == 48
        assert [t[1] for t in w.texts if t[0] == "0 / 2"] == [24]
        assert {t[1] for t in w.texts if t[0] in W8} <= set(range(24, 49))
    elif row == "paper":
        w = running(configured(tmp_path, theme("page", "paper_image", '"gui/bg.png"')))
        assert w.px(280, 600) == w.px(312, 400) == (10, 200, 10)
        assert not [f for f in w.fills if f[0] in ((0xC9, 0xD8, 0xEE), (0xE8, 0xA0, 0xA0))]
    elif row in ("paper_missing", "w64"):
        warned = {}
        for dev in (True, False):
            caplog.clear()
            w = running(configured(tmp_path, theme("page", "paper_image", '"gui/nope.png"'),
                                   dev=dev))
            assert near(w.px(280, 600), PAGE_FILL)                # the drawn page
            assert near(w.px(312, 400), (0xE8, 0xA0, 0xA0))
            assert [f for f in w.fills if f[0] == (0xC9, 0xD8, 0xEE)]   # the rules
            warned[dev] = [(getattr(r, "code", None), r.getMessage()) for r in caplog.records
                           if r.levelno >= logging.WARNING]
        if row == "paper_missing":                                # one line names the file
            assert len(warned[True]) == 1 and "gui/nope.png" in warned[True][0][1], warned
        else:                                                     # 07 I-5 (Q-c): W64, dev only
            assert [code for code, _ in warned[True]] == ["W64"] and warned[False] == []
    else:
        w = HostP()
        w.shell.painter.set_text_scale(lambda: 1.5)
        running(w, {"words": dict.fromkeys(LONG, "yuri"), "rounds": 1, "page_words": 4})
        g = w.game
        canvas = w.ui.canvas
        lay = g.lay
        col = lay.cells[0][2]
        font_at = lambda s: canvas.font_handle(g._font(s), s).font          # noqa: E731
        assert sorted(g.poem.entries[e].word for e in g.page) == sorted(LONG)
        for slot, entry, fit in zip(g.slots, g.page, g.fits):
            word = g.poem.entries[entry].word
            want = poem_game.fit_label(word, font_at, 48, lay.label_width, min_size=24, step=2)
            assert fit == want and fit.size >= 24
            width = font_at(fit.size).size(fit.text)[0]
            assert width <= lay.label_width
            assert slot.box.w == min(col - 16, width + 48)
            if word == "W" * 24:
                assert fit.text.endswith("…") == want.truncated


# --- AC-F24-18 — A3 and A4: host outcomes and host-drawn widgets --------------------------------

class Stub(api.Minigame):
    """An API 1.1 minigame whose ``outcome_for`` returns None or raises."""
    name = "stub"
    api = "1.1"
    test_outcome = Outcome(7)
    mode = "none"

    def outcome_for(self, kind, args, story):
        if Stub.mode == "raises":
            raise ZeroDivisionError("division by zero")
        return None


@pytest.mark.parametrize("row", [
    "shift_f8", "skip_game", "stub_none", "stub_raises", "draw_order", "handle_event",
    "draw_raises"])
def test_ac18_host_outcomes_and_host_drawn_widgets(row, monkeypatch, caplog):
    if row in ("stub_none", "stub_raises"):
        monkeypatch.setattr(Stub, "mode", row[5:])
        w = HostP(entry=api.declarations(Stub, "engine"))
        running(w, {}, name="stub")
        w.frame(H.key(pygame.K_F8, pygame.KMOD_SHIFT))
        w.frames(30)
        if row == "stub_none":
            assert [(d.result, d.changes) for d in w.done()] == [(7, ())]
        else:
            assert w.done() == [] and w.fatal[0].code == "E275"
        return
    if row == "skip_game":                       # the call AC-F23-40's Yes makes
        w = running(HostP(), dict(P16, result="totals"), skippable=True)
        w.frame(H.key(pygame.K_DOWN))
        assert w.host.can_skip()
        w.host.skip(w.session)
        w.frames(30)
        assert [Outcome(d.result, d.changes) for d in w.done()] == [
            Outcome(dict.fromkeys(D, 0), ())]
        assert list(w.done()[0].result) == list(D)               # key order
        return
    w = running(HostP())
    if row == "shift_f8":
        w.frame(H.key(pygame.K_F8, pygame.KMOD_SHIFT))
        w.frames(30)
        done = w.done()
        assert len(done) == 1 and Outcome(done[0].result, done[0].changes) == Outcome(
            "natsuki", (MeterChange("sayori", "+=", 3), MeterChange("natsuki", "+=", 4)))
    elif row == "draw_order":
        order: list[str] = []
        real_draw, real_slot = PoemGame.draw, WordSlot.draw
        real_frame = MinigameScreen._draw_frame
        looks = []

        def draw(game, canvas):
            order.append("plugin")
            real_draw(game, canvas)

        def slot_draw(slot, p, look):
            order.append(f"slot{slot.index}")
            looks.append((slot, look))
            real_slot(slot, p, look)

        def frame(screen, canvas, p):
            order.append("frame")
            real_frame(screen, canvas, p)

        monkeypatch.setattr(PoemGame, "draw", draw)
        monkeypatch.setattr(WordSlot, "draw", slot_draw)
        monkeypatch.setattr(MinigameScreen, "_draw_frame", frame)
        w.frame()
        assert order == ["plugin", "slot0", "slot1", "slot2", "frame"]
        screen = w.session.screen
        assert all(look == screen.look_for(slot) for slot, look in looks)
        order.clear()
        w.start(restored=False, run=2)                            # the opening picture
        assert order == ["plugin", "slot0", "slot1", "slot2", "frame"]
    elif row == "handle_event":
        answers = []
        real = PoemGame.handle_event
        monkeypatch.setattr(PoemGame, "handle_event",
                            lambda g, ev: answers.append(real(g, ev)) or answers[-1])
        pos = center(w, 0)
        w.frame(H.motion(pos), H.down(pos), H.up(pos), H.key(pygame.K_DOWN),
                H.pad(pygame.CONTROLLER_BUTTON_A), H.wheel(pos, 1))
        assert answers and not any(answers)
        assert w.game.picked                                      # the click reached a slot
    else:
        caplog.set_level(logging.DEBUG, logger="vn.plugin")

        def broken(game, canvas):
            return 1 / 0

        monkeypatch.setattr(PoemGame, "draw", broken)
        w.frame()
        assert len(w.fatal) == 1 and w.fatal[0].code == "E275"
        text = w.fatal[0].format()
        assert text.startswith("script/main.vns, line 16: ")
        assert "poem_game.py" not in text and "engine/" not in text
        records = [r for r in caplog.records if r.levelno == logging.ERROR
                   and r.name == "vn.plugin"]
        assert len(records) == 1 and "ZeroDivisionError" in records[0].exc_text


# --- AC-F24-21 — CI guard: costs ----------------------------------------------------------------

def test_ac21_costs(monkeypatch):
    spy = RandomSpy(monkeypatch)
    fits: list[str] = []
    real_fit = poem_game.fit_label
    monkeypatch.setattr(poem_game, "fit_label",
                        lambda text, *a, **k: fits.append(text) or real_fit(text, *a, **k))
    adds: list[tuple] = []
    from engine.minigames.host import LedgerPoints
    real_add = LedgerPoints.add
    monkeypatch.setattr(LedgerPoints, "add",
                        lambda port, name, n: adds.append((name, n)) or real_add(port, name, n))
    w = HostP()
    renders: list[tuple] = []
    cache = w.shell.assets.cache
    real_put = cache.put

    def put(key, *args, **kwargs):
        if key and key[0] == "text":
            renders.append(key)
        return real_put(key, *args, **kwargs)

    monkeypatch.setattr(cache, "put", put)
    running(w, {"words": W8, "rounds": 2, "page_words": 3})
    assert len(fits) == 3 and [n for n, _ in spy.calls] == ["shuffle"]
    fits.clear()
    renders.clear()
    builds = w.shell.painter.builds
    for _ in range(600):
        w.frame()
        rules = [f for f in w.fills if f[0] == (0xC9, 0xD8, 0xEE)]
        assert len(rules) <= 40
    assert fits == [] and renders == [] and w.shell.painter.builds == builds
    w.frame(H.key(pygame.K_RETURN))                               # a page change
    assert [n for n, _ in spy.calls] == ["shuffle", "shuffle"] and len(fits) <= 3
    w.frames(GAP)
    w.frame(H.key(pygame.K_RETURN))                               # the finish
    named = poem_rules.named_meters(poem_rules.parse(P16), D)
    assert len(adds) <= len(named) and len({n for n, _ in adds}) == len(adds)


@pytest.mark.slow
def test_ac21_slow_large_list_checks_and_save():
    import json
    import time
    from engine.runtime.values import freeze
    names = [f"m{i}" for i in range(16)]
    words = {f"w{i:04}": dict.fromkeys(names, 1) for i in range(2000)}
    args = {"words": words, "rounds": 50, "page_words": 12}
    began = time.perf_counter()
    assert poem_rules.problem(args) is None and poem_rules.meter_problem(args, names) is None
    assert time.perf_counter() - began < 0.2
    back = json.loads(json.dumps(freeze(args)))
    assert list(back["words"]) == list(words) and back == args
