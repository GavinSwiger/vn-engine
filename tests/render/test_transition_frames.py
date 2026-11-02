"""F09 step 2 — dissolve and fade frames in harness V (``06-acceptance.md`` §0.2): a
``StageView`` drawn by a ``StageScreen`` in an ``App`` on a ``FakeWindow`` (1280×720), shown a
``ShowStage``, drawn until PREPARING ends, then ``advance(p × seconds)`` and one draw, with
pixel probes in window pixels.

AC-F09-18; AC-F09-24 (``finish``, also while PREPARING); AC-F09-40 (a kind added to ``KINDS``
plays through its spec).
"""

from pathlib import Path

import pygame
import pytest

from engine.core.config_schema import Config, StageConfig
from engine.core.constants import BUILTIN_POSITIONS
from engine.core.paths import GamePaths
from engine.render import transitions
from engine.render.stage import StageView
from engine.render.transitions import KINDS, KindFrame
from engine.runtime.commands import ShowStage, TransitionSpec
from engine.runtime.images import ImageIndex, SolidColor
from engine.runtime.stage import StageState
from engine.ui.builtin.stage_screen import StageScreen
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app

pytestmark = pytest.mark.display

EMBER, SEA = (200, 40, 0), (0, 80, 240)
PROBES = ((640, 360), (20, 20), (1259, 20), (20, 699), (1259, 699))


def spec(kind: str, seconds: float | None = 1.0, color: str | None = None) -> TransitionSpec:
    return TransitionSpec(kind, kind, "sid-1", seconds, color, None, 0.1, False, None)


class V:
    def __init__(self, root: Path, *, empty=(0, 0, 0), fade_color=(0, 0, 0)) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.window = FakeWindow((1280, 720))
        config = Config(stage=StageConfig(positions=BUILTIN_POSITIONS))
        self.app, _ = make_app(self.window, config=config, paths=GamePaths.for_game(root))
        index = ImageIndex({"bg ember": SolidColor(EMBER), "bg sea": SolidColor(SEA)})
        self.view = StageView(self.app.assets, index, art_height=720,
                              positions=BUILTIN_POSITIONS, empty_color=empty,
                              fade_color=fade_color)
        self.app.screens.push(StageScreen(self.app, self.view))

    def frame(self) -> set[tuple[int, int, int]]:
        self.app.present()
        fb = self.window.framebuffer()
        return {tuple(fb.get_at(p))[:3] for p in PROBES}

    def play(self, cmd: ShowStage, p: float) -> set[tuple[int, int, int]]:
        """The frame at progress ``p`` of ``cmd`` (its seconds are 1.0)."""
        self.view.show(cmd)
        for _ in range(5):                        # PREPARING: the old picture
            self.frame()
            if self.view._run.running:
                break
        self.view.advance(p)
        return self.frame()


FADE_ROWS = {                                     # AC-F09-18: p = 0.25, 0.5, 0.75
    "dissolve": (None, None, [(150, 50, 60), (100, 60, 120), (50, 70, 180)]),
    "fade": (None, None, [(100, 20, 0), (0, 0, 0), (0, 40, 120)]),
    "fade white": ("#FFFFFF", None, [(228, 148, 128), (255, 255, 255), (128, 168, 248)]),
    "theme white": (None, (255, 255, 255), [(228, 148, 128), (255, 255, 255),
                                            (128, 168, 248)]),
    "fade red": ("#FF0000", None, [(228, 20, 0), (255, 0, 0), (128, 40, 120)]),
    "fade ffe08a": ("#FFE08A", None, [(228, 132, 69), (255, 224, 138), (128, 152, 189)]),
}


def test_ac_f09_18_dissolve_and_fade_frames(tmp_path):
    for row, (color, theme, expected) in FADE_ROWS.items():
        kind = row.split()[0] if row != "theme white" else "fade"
        for p, want in zip((0.25, 0.5, 0.75), expected):
            v = V(tmp_path / f"{row}{p}", fade_color=theme or (0, 0, 0))
            v.view.show(ShowStage(StageState("bg ember")))
            assert v.frame() == {EMBER}
            seen = v.play(ShowStage(StageState("bg sea"), transition=spec(kind, color=color)), p)
            assert len(seen) == 1, (row, p, seen)
            assert all(abs(a - b) <= 2 for a, b in zip(seen.pop(), want)), (row, p)
    v = V(tmp_path / "g", empty=(0x20, 0x40, 0x60))
    # The game's first statement: the old picture was never composed (the empty stage).
    seen = v.play(ShowStage(StageState("bg sea"), transition=spec("fade")), 0.25)
    assert seen == {(16, 32, 48)}
    # Every channel of a dissolve moves monotonically from old to new (p every 0.01).
    old = pygame.Surface((8, 8))
    old.fill(EMBER)
    new = pygame.Surface((8, 8))
    new.fill(SEA)
    scratch = pygame.Surface((8, 8), pygame.SRCALPHA, 32)
    kind = KINDS["dissolve"](KindFrame(old, new, (0, 0, 0), lambda: scratch))
    assert kind.prepare_step()
    target = pygame.Surface((8, 8))
    last = EMBER
    for step in range(1, 100):
        kind.draw(target, step / 100, (0, 0))
        now = tuple(target.get_at((4, 4)))[:3]
        assert now[0] <= last[0] and now[1] >= last[1] and now[2] >= last[2], step
        last = now


def test_ac_f09_24_finish_gives_the_new_picture_at_the_next_draw(tmp_path):
    """A click while PREPARING, or mid-transition: p = 1 at the next draw, exactly."""
    for kind in ("dissolve", "fade"):
        v = V(tmp_path / kind)
        v.view.show(ShowStage(StageState("bg ember")))
        v.frame()
        v.view.show(ShowStage(StageState("bg sea"), transition=spec(kind)))
        assert v.frame() == {EMBER}, kind                    # PREPARING: the old picture
        v.view.finish()
        assert v.frame() == {SEA} and v.view.finished_drawn and not v.view.transitioning
        v.play(ShowStage(StageState("bg ember"), transition=spec(kind)), 0.3)
        v.view.finish()
        assert v.frame() == {EMBER} and v.view.finished_drawn, kind


def test_ac_f09_40_a_kind_added_to_kinds_plays_through_its_spec(tmp_path):
    drawn = []

    class TestKind:
        def __init__(self, frame):
            self.frame = frame

        def prepare_step(self):
            return True

        def draw(self, target, p, offset):
            drawn.append(p)
            target.fill((1, 2, 3))

    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(transitions.KINDS, "test", TestKind)
        v = V(tmp_path / "g")
        v.view.show(ShowStage(StageState("bg ember")))
        v.frame()
        assert v.play(ShowStage(StageState("bg sea"), transition=spec("test")), 0.5) \
            == {(1, 2, 3)}
        v.view.advance(0.5)
        assert v.frame() == {SEA} and v.view.finished_drawn and not v.view.transitioning
    assert drawn == [0.5]
