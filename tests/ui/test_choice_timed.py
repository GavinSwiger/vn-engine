"""F51 step W3, timed menus on the choice screen (``01`` §6, ``04`` §7.3, §7.4; 07 I-2, I-5,
I-6): AC-F51-12 (expiry under each Timing assist level, the pick sound), 13 (pauses), 14 (a
player's pick in the expiry frame wins), 15 (a level change keeps the fraction left), 16
(panel geometry, part of the fit, NVL), 18 (reduce motion), 19 (alpha and hidden), 20 (no
panel and no timeout when reading the past or under No time limits), 24 (the tick sound).
AC-F51-21 (skip and auto) runs in the App: ``tests/app/test_choice_timed_app.py``.

The rig is F07's unit rig (``tests/ui/test_choice_screen.py``): a ``ChoiceController`` on a
bare ``ScreenStack`` with the textbox stand-in (``tab_top`` 460), a view that records
alphas, and here a timer view that records what it is asked to draw. Frames are 1/60 s.
"""

import pygame
import pytest

from engine.core.config_schema import ChoiceTheme
from engine.core.settings_schema import TIMING_NORMAL, TIMING_OFF, TIMING_SLOWER
from engine.render.choices import AREA_TOP, ChoiceArea, ChoiceLayout
from engine.render.choicetimer import (TIMER_BAR_HEIGHT, TIMER_INSET, panel_height,
                                       timer_geometry)
from engine.render.textlayout import BUNDLED_FACES
from engine.runtime.commands import Choose, ShowMenu, ShownChoice
from engine.ui.builtin.choice_screen import ChoiceController, ChoiceScreen
from engine.ui.input import UiEvent
from engine.ui.screen import ScreenStack
from tests.fakes.fixed_font import FixedFontAssets, tagged
from tests.ui.test_choice_screen import FakeTextbox, NoDraw, key

FRAME = 1 / 60
SLOT = 30.0                               # the recording view's "60" width


class TimerSpy:
    """A ``TimerPanelView`` stand-in: the geometry rule with a fixed slot, and each draw's
    (fraction, number, alpha)."""

    def __init__(self) -> None:
        self.draws: list[tuple[float, int, float]] = []

    def geometry(self, rect, size):
        return timer_geometry(rect, size, SLOT)

    def draw(self, canvas, geometry, fraction, number, colors, *, alpha=1.0) -> None:
        self.draws.append((fraction, number, alpha))


class Timed:
    """A timed menu (``seconds``; the third choice is the timeout one) on the unit rig, with
    the Timing assist ``level`` and the window's focus as settable ports."""

    def __init__(self, seconds: float | None = 5.0, *, level: int = TIMING_NORMAL,
                 theme: ChoiceTheme | None = None, tick: str | None = None,
                 size: int = 28) -> None:
        self.stack = ScreenStack()
        self.textbox = FakeTextbox()
        self.textbox.size = size
        self.stack.push(self.textbox)
        self.posted: list[object] = []
        self.played: list[str] = []
        self.level = level
        self.focused = True
        self.timer = TimerSpy()
        self.controller = ChoiceController(
            self.stack, self.textbox, theme=theme or ChoiceTheme(), assets=FixedFontAssets(),
            faces=BUNDLED_FACES, base_text_size=28, post=self.posted.append, view=NoDraw(),
            play=self.played.append, pick_sound="pick.ogg", tick_sound=tick,
            timing_level=lambda: self.level, window_focused=lambda: self.focused,
            timer_view=self.timer)
        self.cmd = ShowMenu("menu/1", tuple(
            ShownChoice(f"c{i}", tagged(f"Choice {i}"), False) for i in (1, 2, 3)),
            "question", seconds=seconds, timeout="c3" if seconds is not None else None)
        self.controller.show(self.cmd)
        self.textbox.on_shown()
        self.screen = self.stack.top
        assert isinstance(self.screen, ChoiceScreen)

    def frames(self, n: int, *, is_top: bool = True, draw: bool = True, dt: float = FRAME
               ) -> None:
        for _ in range(n):
            if self.controller.screen is not self.screen:
                return
            self.screen.update(dt, is_top=is_top)
            if draw and self.controller.screen is self.screen:
                self.screen.draw(None)

    def until_posted(self, limit: int) -> int | None:
        """Frames until a ``Choose`` is posted (None: none within ``limit``)."""
        self.screen.draw(None)                               # the first draw starts it
        for n in range(1, limit + 1):
            self.frames(1)
            if self.posted:
                return n
        return None

    def chosen(self) -> list[str]:
        return [e.choice for e in self.posted if isinstance(e, Choose)]

    def left(self) -> float | None:
        return self.screen.clock.left(self.level)


# --- AC-F51-12 — expiry at each level ------------------------------------------------------------

def test_ac12_timeout_posts_once_at_5_s_normal_10_s_slower_never_off():
    rows = {}
    for level, limit in ((TIMING_NORMAL, 400), (TIMING_SLOWER, 700)):
        rig = Timed(level=level)
        frames = rig.until_posted(limit)
        rig.frames(60)                                       # nothing more after
        rows[level] = (frames * FRAME if frames else None, rig.chosen(), rig.played)
    off = Timed(level=TIMING_OFF)
    off.screen.draw(None)
    off.frames(6000, dt=0.1)                                 # 600 s
    rows[TIMING_OFF] = (None, off.chosen(), off.played)
    assert rows[TIMING_NORMAL] == (pytest.approx(5.0), ["c3"], ["pick.ogg"])
    assert rows[TIMING_SLOWER] == (pytest.approx(10.0), ["c3"], ["pick.ogg"])
    assert rows[TIMING_OFF] == (None, [], [])
    assert off.controller.screen is off.screen               # still waiting for the player


# --- AC-F51-13 — pauses --------------------------------------------------------------------------

@pytest.mark.parametrize("pause", ["game menu on top", "hidden", "focus lost",
                                   "before first draw"])
def test_ac13_the_clock_pauses_and_keeps_the_time_counted(pause):
    rig = Timed()
    if pause == "before first draw":
        rig.frames(600, draw=False)                          # 10 s, never drawn
        assert rig.left() == pytest.approx(5.0)
        rig.screen.draw(None)
    else:
        rig.screen.draw(None)
        rig.frames(120)                                      # 2 s counted
        if pause == "game menu on top":
            rig.frames(600, is_top=False)
        elif pause == "hidden":
            rig.textbox.hidden = True
            rig.frames(600)
            rig.textbox.hidden = False
        else:
            rig.focused = False
            rig.frames(600)
            rig.focused = True
        assert rig.left() == pytest.approx(3.0)              # elapsed kept on return
    assert rig.posted == []
    rig.frames(int(round(rig.left() / FRAME)) + 1)
    assert rig.chosen() == ["c3"]


# --- AC-F51-14 — a player's pick in the expiry frame wins ---------------------------------------

def test_ac14_a_pick_and_the_expiry_in_one_frame_post_the_players_choice_once():
    rig = Timed()
    rig.screen.draw(None)
    rig.frames(299)                                          # 1/60 s left
    assert rig.posted == []
    stack = rig.stack
    stack.handle_event(UiEvent(key(pygame.K_1), None, False))   # events come before update
    rig.screen.update(FRAME, is_top=True)                    # the clock runs out here
    assert rig.chosen() == ["c1"] and rig.played == ["pick.ogg"]


# --- AC-F51-15 — a level change keeps the fraction left -------------------------------------------

def test_ac15_level_changes_keep_the_fraction_of_time_left():
    rig = Timed()
    rig.screen.draw(None)
    rig.frames(240)                                          # 4 of 5 s
    rig.level = TIMING_SLOWER
    rig.frames(1, dt=0.0)
    rows = {"normal→slower": rig.left()}
    rig.level = TIMING_OFF
    rig.frames(1, dt=0.0)
    draws = len(rig.timer.draws)
    rig.frames(6000, dt=0.1)                                 # 600 s: frozen, no timeout
    rows["→off"] = (rig.left(), rig.screen.layout.header_rect, len(rig.timer.draws) - draws,
                    rig.posted)
    rig.level = TIMING_NORMAL
    rig.frames(1, dt=0.0)
    rows["→normal"] = (rig.left(), rig.screen.layout.header_rect is not None)
    assert rows == {"normal→slower": pytest.approx(2.0), "→off": (None, None, 0, []),
                    "→normal": (pytest.approx(1.0), True)}
    rig.frames(61)
    assert rig.chosen() == ["c3"]


# --- AC-F51-16 — panel geometry, the fit, NVL ----------------------------------------------------

@pytest.mark.parametrize("size,height", [(28, 36), (42, 48)])     # 100 % and 150 % text
def test_ac16_panel_geometry_and_place_in_the_stack(size, height):
    rig = Timed(size=size)
    rig.screen.draw(None)
    layout = rig.screen.layout
    assert panel_height(size / 28) == height
    x, y, w, h = layout.header_rect
    assert (x, w, h) == (240, 800, height)
    assert layout.tops[0] - (y + h) == layout.gap                   # one gap below it
    assert layout.top == y and layout.bottom == layout.tops[-1] + layout.heights[-1]
    stack = h + layout.gap + sum(layout.heights) + layout.gap * (len(layout.heights) - 1)
    assert layout.bottom - layout.top == stack                      # part of the fit
    assert layout.hit((640, y + h / 2)) is None                     # never a button
    geometry = rig.controller.timer_geometry(layout.header_rect)
    tx, ty, tw, th = geometry.track
    sx, sy, sw, sh = geometry.slot
    assert (tx, th, ty + th / 2) == (x + TIMER_INSET, TIMER_BAR_HEIGHT, y + h / 2)
    assert (sx + sw, sw) == (x + w - TIMER_INSET, SLOT)
    assert tx + tw == sx - TIMER_INSET
    assert geometry.size == height - 12
    untimed = Timed(None, size=size)
    assert untimed.screen.layout.header_rect is None
    # The panel's height is in every fit step: an area that fits the buttons alone but not
    # the panel too steps down.
    alone = untimed.screen.layout
    area = ChoiceArea(AREA_TOP, AREA_TOP + alone.bottom - alone.top)
    assert alone.relaid(area).step == 0 and layout.relaid(area).step > 0


def test_ac16_nvl_the_panel_heads_the_stack_under_the_page():
    theme = ChoiceTheme()
    bodies = [tagged(f"Choice {i}") for i in (1, 2, 3)]
    area = ChoiceArea(300.0, 640.0, 704.0, "top")
    layout = ChoiceLayout(bodies, assets=FixedFontAssets(), faces=BUNDLED_FACES, theme=theme,
                          text_size=28, area=area, colors=["#3d2b36"] * 3, header=36)
    assert layout.header_rect == (240, 300.0, 800, 36)
    assert layout.tops[0] == 300.0 + 36 + layout.gap
    moved = layout.relaid(area, 48)                                 # 150 %: a relaid
    assert moved.header_rect[3] == 48 and moved.tops[0] == 300.0 + 48 + moved.gap


# --- AC-F51-18 — reduce motion -------------------------------------------------------------------

def test_ac18_reduce_motion_moves_the_bar_by_whole_seconds_and_never_fades():
    rig = Timed()
    rig.textbox.reduced = True
    rig.screen.draw(None)
    rig.frames(290)
    fractions = [f for f, _, _ in rig.timer.draws]
    assert set(fractions) == {1.0, 0.8, 0.6, 0.4, 0.2}
    assert all(f == n / 5 for f, n, _ in rig.timer.draws)          # moves with the number
    assert {a for _, _, a in rig.timer.draws} == {1.0}               # alpha 1 from the first
    assert rig.controller.view.alphas[0] == 1.0
    smooth = Timed()
    smooth.screen.draw(None)
    smooth.frames(30)
    assert len({f for f, _, _ in smooth.timer.draws}) == 31          # every frame otherwise


# --- AC-F51-19 — alpha with the choices, hidden with them ---------------------------------------

def test_ac19_panel_alpha_follows_the_choices_and_hides_with_them():
    rig = Timed()
    rig.screen.draw(None)
    rig.frames(9)
    alphas = [a for _, _, a in rig.timer.draws]
    assert alphas == rig.controller.view.alphas and alphas[0] < 1.0 and alphas[-1] == 1.0
    rig.textbox.hidden = True
    before = len(rig.timer.draws)
    rig.frames(30)
    assert len(rig.timer.draws) == before


# --- AC-F51-20 — reading the past and No time limits ----------------------------------------------

@pytest.mark.parametrize("case", ["reading the past", "no time limits"])
def test_ac20_no_panel_no_timeout_and_the_timeout_choice_stays_pickable(case):
    rig = Timed(None) if case == "reading the past" else Timed(level=TIMING_OFF)
    rig.screen.draw(None)
    rig.frames(6000, dt=0.1)
    assert rig.posted == [] and rig.timer.draws == []
    assert rig.screen.layout.header_rect is None
    rig.stack.handle_event(UiEvent(key(pygame.K_3), None, False))
    assert rig.chosen() == ["c3"]


# --- AC-F51-24 — the tick sound (Could) ----------------------------------------------------------

def test_ac24_tick_sound_at_3_2_1_once_each_and_never_without_the_token():
    rig = Timed(tick="tick.ogg")
    rig.until_posted(400)
    assert rig.played == ["tick.ogg"] * 3 + ["pick.ogg"]
    silent = Timed()
    silent.until_posted(400)
    assert silent.played == ["pick.ogg"]
