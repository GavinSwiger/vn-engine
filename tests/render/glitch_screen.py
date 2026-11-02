"""Screen L for F28's on-screen tests (``06-acceptance.md`` §0.3): a ``StageScreen`` with a
``GlitchLayer`` (seed 7) and a ``StageView`` over generated IMG9+ art (``bg grain``, hana as a
green 300×600 block, daichi yellow) in an ``App`` on a ``FakeWindow``, fed commands by direct
handler calls, then ``update(1/60)`` and one present per frame. Probes read the presented
framebuffer. The control is the same rig fed no ``Glitch``.

``grain`` is ``bg grain``: 8×8-unit blocks of seeded random RGB (seed 3)."""

from pathlib import Path
from random import Random

import pygame

from engine.core.config_schema import Config, StageConfig
from engine.core.constants import BUILTIN_POSITIONS, CANVAS_SIZE
from engine.core.paths import GamePaths
from engine.render.effects import EffectSettings
from engine.render.glitch import GlitchLayer
from engine.render.stage import StageView
from engine.runtime.commands import Glitch, GlitchBurst, ShowStage
from engine.runtime.glitch import EMPTY_GLITCH, GlitchEntry, GlitchState
from engine.runtime.images import ImageFile, ImageIndex, SolidColor
from engine.runtime.stage import SpriteState, StageState
from engine.ui.builtin.stage_screen import StageScreen
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.fixtures.F04 import gen_images as gen

DT = 1 / 60
GREEN, YELLOW, SEA = (0, 255, 0), (255, 255, 0), (0, 80, 240)
SPRITES = {"hana happy": GREEN, "hana sad": GREEN, "daichi grin": YELLOW}
GRAIN_REF = "images/bg/grain.png"


def grain(size: tuple[int, int] = CANVAS_SIZE, seed: int = 3) -> pygame.Surface:
    cells = (CANVAS_SIZE[0] // 8, CANVAS_SIZE[1] // 8)
    small = pygame.image.frombytes(Random(seed).randbytes(cells[0] * cells[1] * 3), cells, "RGB")
    out = pygame.Surface(size, 0, 32)
    out.blit(pygame.transform.scale(small, size), (0, 0))
    return out


def stage(*sprites: tuple[str, str, object], background: str = "bg grain") -> StageState:
    """``("hana", "hana happy", "center")`` per sprite."""
    return StageState(background, tuple(SpriteState(tag, image, at)
                                         for tag, image, at in sprites))


HANA = ("hana", "hana happy", "center")
DAICHI = ("daichi", "daichi grin", "right")


def lasting(*entries: tuple) -> GlitchState:
    """``("static", "medium")`` or ``("jitter", "large", "hana")`` per entry."""
    state = EMPTY_GLITCH
    for entry in entries:
        state = state.with_entry(GlitchEntry(*entry))
    return state


def on(*entries: tuple, stops: tuple = ()) -> Glitch:
    return Glitch(lasting(*entries), stops=stops)


def burst(kind: str, size: str | None = None, seconds: float | None = None, *,
          tag: str | None = None, sid: str = "s1", keep: GlitchState = EMPTY_GLITCH) -> Glitch:
    return Glitch(keep, bursts=(GlitchBurst(kind, tag, size, seconds, sid),))


class L:
    """One Screen L rig in game folder ``root``."""

    def __init__(self, root: Path, *, size: tuple[int, int] = (640, 360), seed: int = 7,
                 reduce: bool = False, seconds: float = 0.5, glitch_size: str = "medium"
                 ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        images = {gen.ref_of(name): gen.block(300, 600, color) for name, color in SPRITES.items()}
        images[GRAIN_REF] = grain()
        gen.write(root, images)
        entries = {name: ImageFile(gen.ref_of(name)) for name in SPRITES}
        entries["bg grain"] = ImageFile(GRAIN_REF)
        entries["bg sea"] = SolidColor(SEA)
        entries["ghost x"] = ImageFile("images/ghost/x.png")     # never written: placeholder
        self.window = FakeWindow(size)
        config = Config(stage=StageConfig(positions=BUILTIN_POSITIONS))
        self.app, self.limiter = make_app(self.window, config=config,
                                          paths=GamePaths.for_game(root))
        self.view = StageView(self.app.assets, ImageIndex(entries), art_height=720,
                              positions=BUILTIN_POSITIONS, empty_color=(0, 0, 0))
        self.layer = GlitchLayer(seconds=seconds, size=glitch_size, seed=seed)
        self.screen = StageScreen(self.app, self.view, glitches=self.layer,
                                  settings=EffectSettings(reduce=reduce))
        self.app.screens.push(self.screen)

    def show(self, shown: StageState, **kwargs) -> None:
        self.screen.show_stage(ShowStage(shown, **kwargs))

    def frame(self) -> pygame.Surface:
        """One frame: update, then present; a copy of the framebuffer."""
        self.screen.update(DT, is_top=True)
        self.app.present()
        return self.window.framebuffer().copy()

    def frames(self, n: int) -> list[pygame.Surface]:
        return [self.frame() for _ in range(n)]

    @property
    def scale(self) -> float:
        return self.window.framebuffer().get_width() / CANVAS_SIZE[0]


def rows(surface: pygame.Surface) -> list[bytes]:
    """Each row's RGB bytes."""
    raw = pygame.image.tobytes(surface, "RGB")
    pitch = surface.get_width() * 3
    return [raw[i:i + pitch] for i in range(0, len(raw), pitch)]


def multiset(row: bytes) -> list[bytes]:
    return sorted(row[i:i + 3] for i in range(0, len(row), 3))


def mean(surface: pygame.Surface) -> float:
    """The stage mean: (R + G + B) / 3 over every pixel."""
    raw = pygame.image.tobytes(surface, "RGB")
    return sum(raw) / len(raw)


__all__ = ["DAICHI", "DT", "GREEN", "HANA", "L", "YELLOW", "burst", "grain", "lasting",
           "mean", "multiset", "on", "rows", "stage"]
