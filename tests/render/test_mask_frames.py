"""F09 step 3 — the mask on screen, resize mid-transition, and the view's buffers, in harness V
(``06-acceptance.md`` §0.2): a ``StageView`` drawn by a ``StageScreen`` in an ``App`` on a
``FakeWindow``, shown a ``ShowStage``, drawn until PREPARING ends, then advanced, with pixel
probes in window pixels. Whole-frame compares use small canvases; the full-size rows are
``slow``.

AC-F09-20, 21, 22, 27, 29, 31, 41; AC-F09-39's mask row (reads only through the
``AssetManager`` and ``GamePaths.read_file``). AC-F09-46 (wipes, Could) is not built.
"""

import builtins
import io
import logging
import os
import random
import shutil
import statistics
import sys
import time
import types
import weakref
from pathlib import Path

import pygame
import pytest

from engine.core.config_schema import Config, StageConfig
from engine.core.constants import BUILTIN_POSITIONS, IMAGE_MAX_SIDE
from engine.core.paths import GamePaths
from engine.render import stage as stage_module
from engine.render import transitions
from engine.render.assets import AssetManager
from engine.render.canvas import RenderQuality
from engine.render.stage import StageView
from engine.render.transitions import (KINDS, KindFrame, MaskBuffer, MaskStore, mask_alpha,
                                       mask_palette, scratch_format, view_order)
from engine.runtime.commands import ShowStage, TransitionSpec
from engine.runtime.images import ImageFile, ImageIndex, SolidColor
from engine.runtime.stage import SpriteState, StageState
from engine.ui.builtin.stage_screen import StageScreen
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.fixtures.F04 import gen_images as gen

pytestmark = pytest.mark.display
slow = pytest.mark.slow

F09 = Path(__file__).resolve().parents[1] / "fixtures" / "F09"
EMBER, SEA = (200, 40, 0), (0, 80, 240)
QUARTERS = (0, 64, 191, 255)                      # §5: masks/quarters.png, gray by quarter
QUARTER_POINTS = ((160, 360), (480, 360), (800, 360), (1120, 360))   # canvas units
FLAT_POINTS = ((640, 360), (40, 40), (1240, 40), (40, 680), (1240, 680))
SPRITES = {"hana happy": (0, 255, 0), "hana sad": (0, 200, 60), "daichi grin": (255, 255, 0)}
OLD = StageState("bg ember", (SpriteState("hana", "hana happy", "left"),
                              SpriteState("daichi", "daichi grin", "right")))
NEW = StageState("bg sea", (SpriteState("hana", "hana sad", "center"),))
DT = 1 / 60


def spec(kind: str, seconds: float = 1.0, *, color: str | None = None,
         mask: str | None = "masks/quarters.png", soft: float = 0.1,
         reverse: bool = False) -> TransitionSpec:
    return TransitionSpec(kind, kind, "sid-1", seconds, color,
                          mask if kind == "mask" else None, soft, reverse, None)


def quarters() -> pygame.Surface:
    surface = pygame.Surface((64, 36))
    for k, g in enumerate(QUARTERS):
        surface.fill((g, g, g), (16 * k, 0, 16, 36))
    return surface


def mix(alpha: int) -> tuple[int, int, int]:
    """Old ``bg ember`` under new ``bg sea`` at ``alpha`` (0–255)."""
    a = alpha / 255
    return tuple(round(o * (1 - a) + n * a) for o, n in zip(EMBER, SEA))


def near(a, b, tol: int = 2) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


class Rig:
    """A game folder with the §5 masks (and sprites), an index, and an ``App`` on a
    ``FakeWindow`` whose only screen is a ``StageScreen``."""

    def __init__(self, root: Path, size=(1280, 720), *, desktop=(1920, 1080),
                 sprites: bool = False) -> None:
        root.mkdir(parents=True, exist_ok=True)
        files: dict = {"masks/quarters.png": quarters(),
                       "masks/corrupt.png": random.Random(1).randbytes(512),
                       "masks/huge.png": gen.header_only(IMAGE_MAX_SIDE + 1, 16)}
        entries: dict = {"bg ember": SolidColor(EMBER), "bg sea": SolidColor(SEA)}
        if sprites:
            files.update({gen.ref_of(n): gen.block(300, 600, c) for n, c in SPRITES.items()})
            entries.update({n: ImageFile(gen.ref_of(n)) for n in SPRITES})
        gen.write(root, files)
        shutil.copyfile(F09 / "template" / "masks" / "iris.png", root / "masks" / "iris.png")
        self.window = FakeWindow(size, desktop=desktop)
        self.app, self.limiter = make_app(self.window,
                                          config=Config(stage=StageConfig(
                                              positions=BUILTIN_POSITIONS)),
                                          paths=GamePaths.for_game(root))
        self.view = StageView(self.app.assets, ImageIndex(entries), art_height=720,
                              positions=BUILTIN_POSITIONS, empty_color=(0, 0, 0))
        self.screen = StageScreen(self.app, self.view)
        self.app.screens.push(self.screen)

    def frame(self, *, update: bool = False) -> pygame.Surface:
        """One frame: the screen's update (the transition clock, +1/60 s) if asked, then
        the draw; the app clock moves on 1/60 s (F01's resize settle)."""
        if update:
            self.screen.update(DT, is_top=True)
        self.limiter.clock.now += DT
        self.app.present()
        return self.window.framebuffer()

    def prepare(self, cmd: ShowStage | None = None, *, update: bool = False) -> int:
        """Show ``cmd`` (if given), then draw until PREPARING ends; the frames it took."""
        if cmd is not None:
            self.view.show(cmd)
        frames = 0
        while self.view.transitioning and not self.view._run.running:
            self.frame(update=update)
            frames += 1
            assert frames < 30
        return frames

    def play(self, cmd: ShowStage, p: float) -> pygame.Surface:
        self.prepare(cmd)
        self.view.advance(p * cmd.transition.seconds)
        return self.frame()

    def cut(self, stage: StageState) -> None:
        self.view.show(ShowStage(stage))
        self.frame()

    def resize(self, width: int, height: int) -> None:
        """A new window size and its FAST frame; the settle is over at the next frame."""
        self.window.resize(width, height)
        self.frame()
        self.limiter.clock.now += 0.25

    def probes(self, points, scale: float = 1.0) -> list[tuple[int, int, int]]:
        fb = self.window.framebuffer()
        return [tuple(fb.get_at((round(x * scale), round(y * scale))))[:3] for x, y in points]

    def scale(self) -> float:
        return self.window.framebuffer().get_width() / 1280


# --- AC-F09-20 — mask frames -------------------------------------------------------------------

@pytest.mark.parametrize("size", [(1280, 720), pytest.param((1920, 1080), marks=slow)])
def test_ac_f09_20_mask_frames(tmp_path, size):
    rows = [  # (p, reverse, quarters 1–4: N, O, or a partial value ±3)
        (0.25, False, [SEA, (152, 50, 57), EMBER, EMBER]),
        (0.5, False, [SEA, SEA, EMBER, EMBER]),
        (0.75, False, [SEA, SEA, (48, 70, 182), EMBER]),
        (0.5, True, [EMBER, EMBER, SEA, SEA]),
    ]
    rig = Rig(tmp_path / "g", size)
    for n, (p, reverse, expected) in enumerate(rows):
        rig.cut(StageState("bg ember"))
        frames = rig.prepare(ShowStage(StageState("bg sea"),
                                       transition=spec("mask", reverse=reverse)))
        assert frames <= (8 if n == 0 else 2), frames      # M8 is kept for the next use
        rig.view.advance(p)
        rig.frame()
        seen = rig.probes(QUARTER_POINTS, rig.scale())
        for got, want in zip(seen, expected):
            assert got == want if want in (SEA, EMBER) else near(got, want, 3), (p, seen)
        rig.view.finish()
        rig.frame()


# --- AC-F09-21 — mask buffers on every OS ------------------------------------------------------

def test_ac_f09_21_mask_buffers(tmp_path, record_property, caplog):
    rig = Rig(tmp_path / "g", (320, 180))
    rig.cut(StageState("bg ember"))
    rig.play(ShowStage(StageState("bg sea"), transition=spec("mask")), 0.5)
    s = rig.view._scratch
    fmt = scratch_format(s)
    record_property("scratch_format", fmt)                 # the run records which
    print(f"S is {fmt}")
    assert fmt in ("ARGB8888", "ABGR8888")
    b = MaskBuffer((256, 1), view_order(s))
    assert tuple(b.a.get_masks()) == tuple(s.get_masks())
    m8 = pygame.image.frombytes(bytes(range(256)), (256, 1), "P")
    for p in (0.3, 0.7):
        m8.set_palette(mask_palette(p, 0.1, False))
        b.g.blit(m8, (0, 0))
        assert [b.a.get_at((i, 0)).a for i in range(256)] == \
            [mask_alpha(i, p, 0.1, False) for i in range(256)], p
    # S patched to another 32-bit format: Mask frames are dissolve frames, one INFO line.
    rig = Rig(tmp_path / "h", (320, 180))
    rgba8888 = (0xFF000000, 0xFF0000, 0xFF00, 0xFF)
    rig.view._scratch = pygame.Surface((320, 180), pygame.SRCALPHA, 32, rgba8888)
    assert scratch_format(rig.view._scratch) is None
    with caplog.at_level(logging.INFO, logger="vn.stage"):
        for p, want in ((0.25, (150, 50, 60)), (0.5, (100, 60, 120)), (0.75, (50, 70, 180))):
            rig.cut(StageState("bg ember"))
            rig.play(ShowStage(StageState("bg sea"), transition=spec("mask")), p)
            assert all(near(got, want) for got in rig.probes(FLAT_POINTS, 0.25)), p
            rig.view.finish()
            assert rig.probes(FLAT_POINTS, 0.25) != [SEA] * 5
            rig.frame()
            assert rig.probes(FLAT_POINTS, 0.25) == [SEA] * 5
    infos = [r for r in caplog.records if r.levelno == logging.INFO and "dissolve" in
             r.getMessage() and "mask" in r.getMessage()]
    assert len(infos) == 1                                  # once per run


# --- AC-F09-22 — the last frame is exactly the new picture --------------------------------------

KINDS_22 = [spec("dissolve"), spec("fade"), spec("fade", color="#FFFFFF"),
            spec("fade", color="#FFE08A"), spec("mask"), spec("mask", soft=0.0),
            spec("mask", reverse=True)]


def _exact(rig: Rig) -> bool:
    fb, picture = rig.window.framebuffer(), rig.view.picture()
    return fb.get_size() == picture.get_size() and \
        pygame.image.tobytes(fb, "RGB") == pygame.image.tobytes(picture, "RGB")


@pytest.mark.parametrize("sizes", [
    [((320, 180), (400, 225)), ((480, 270), (320, 180))],     # resized up, then down
    pytest.param([((1280, 720), (1600, 900)), ((1920, 1080), (1280, 720))], marks=slow)],
    ids=["small", "large"])
def test_ac_f09_22_the_last_frame_is_exactly_the_new_picture(tmp_path, sizes):
    for size, other in sizes:
        _last_frame_is_exact(tmp_path / f"g{size[0]}", size, other)


def _last_frame_is_exact(root, size, other):
    rig = Rig(root, size, sprites=True)
    for kind in KINDS_22:
        for end in ("natural", "finish at 0.3", "finish preparing", "resize at 0.4"):
            if rig.window.framebuffer().get_size() != size:
                rig.resize(*size)
            rig.cut(OLD)
            cmd = ShowStage(NEW, transition=kind)
            if end == "finish preparing":
                rig.view.show(cmd)
                rig.frame()
                rig.view.finish()
            elif end == "finish at 0.3":
                rig.play(cmd, 0.3)
                rig.view.finish()
            elif end == "resize at 0.4":
                rig.play(cmd, 0.4)
                rig.resize(*other)
                rig.prepare()
                rig.view.advance(0.6)
            else:
                rig.prepare(cmd)
                rig.view.advance(1.0)
            rig.frame()
            assert not rig.view.transitioning and rig.view.finished_drawn, (kind, end)
            assert _exact(rig), (kind.kind, kind.color, kind.soft, kind.reverse, end)


# --- AC-F09-27 — resize and fullscreen mid-transition -------------------------------------------

@pytest.mark.parametrize("size, bigger, desktop", [
    ((320, 180), (400, 225), (480, 270)),
    pytest.param((1280, 720), (1600, 900), (1920, 1080), marks=slow)])
def test_ac_f09_27_resize_and_fullscreen_mid_transition(tmp_path, size, bigger, desktop):
    for kind in (spec("dissolve", 2.0), spec("mask", 2.0)):
        points = FLAT_POINTS[:1] if kind.kind == "dissolve" else QUARTER_POINTS
        for change, at in (("resize", 0.4), ("fullscreen", 0.6)):
            rig = Rig(tmp_path / f"{kind.kind}-{change}", size, desktop=desktop)
            rig.cut(StageState("bg ember"))
            rig.screen.show_stage(ShowStage(StageState("bg sea"), transition=kind))
            rig.prepare(update=True)
            run = rig.view._run
            ticks = 0                                      # frames whose update ran the clock
            while run.clock < at * 2.0 - 1e-9:
                before = run.clock
                rig.frame(update=True)
                ticks += run.clock > before
            if change == "resize":
                rig.window.resize(*bigger)
            else:
                rig.window.set_fullscreen(True)
            half = SEA if at >= 0.5 else EMBER
            first, settle = True, 0
            while first or not run.running:                # FAST settle, then re-preparing
                before = run.clock
                rig.frame(update=True)
                ticks += run.clock > before
                if first:
                    paused = run.clock
                    assert rig.app.canvas.quality is RenderQuality.FAST
                first = False
                settle += 1
                assert run.clock == paused, "the clock is paused through the settle"
                assert set(rig.probes(points, rig.scale())) == {half}, (kind.kind, settle)
            assert settle <= 12 + 8 + 1                    # 0.2 s settle + re-preparing
            p = paused / 2.0
            rig.frame()                                    # resumed at the same p
            for (x, _), got in zip(points, rig.probes(points, rig.scale())):
                g = QUARTERS[x // 320] if kind.kind == "mask" else None
                alpha = round(255 * p) if g is None else mask_alpha(g, p, 0.1, False)
                assert near(got, mix(alpha)), (kind.kind, change, x, got, mix(alpha))
            while rig.view.transitioning:
                before = run.clock
                rig.frame(update=True)
                ticks += run.clock > before
            assert abs(ticks - 120) <= 1, ticks             # F = R(2.0) clock frames in all
            assert set(rig.probes(points, rig.scale())) == {SEA} and _exact(rig)


# --- AC-F09-29 — an unusable mask plays as a dissolve -------------------------------------------

def test_ac_f09_29_an_unusable_mask_plays_as_a_dissolve(tmp_path):
    rig = Rig(tmp_path / "g", (320, 180))
    calls: list[str] = []
    real = AssetManager.image
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(AssetManager, "image", lambda self, ref: calls.append(ref) or real(self, ref))
        for ref in ("masks/missing.png", "masks/corrupt.png", "masks/huge.png"):
            first = None
            for _ in range(2):
                rig.cut(StageState("bg ember"))
                rig.play(ShowStage(StageState("bg sea"), transition=spec("mask", mask=ref)), 0.5)
                assert all(near(got, (100, 60, 120)) for got in rig.probes(FLAT_POINTS, 0.25))
                rig.view.finish()
                rig.frame()
                assert _exact(rig) and rig.probes(FLAT_POINTS, 0.25) == [SEA] * 5
                if first is None:
                    first = calls.count(ref)
                assert calls.count(ref) == first, ref     # a second use: no more image()
            assert ref in rig.view._masks.unusable


# --- AC-F09-31 — bounded buffers ---------------------------------------------------------------

@pytest.mark.parametrize("n", [500, pytest.param(10_000, marks=slow)])
def test_ac_f09_31_bounded_buffers(tmp_path, n):
    surfaces: weakref.WeakSet = weakref.WeakSet()
    buffers: weakref.WeakSet = weakref.WeakSet()

    class Counted(pygame.Surface):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            surfaces.add(self)

    class CountedB(MaskBuffer):
        __slots__ = ()

        def __init__(self, *args):
            super().__init__(*args)
            buffers.add(self)

    counting = types.ModuleType("pygame")
    counting.__getattr__ = lambda name: getattr(pygame, name)
    counting.Surface = Counted
    rng = random.Random(7)
    sizes = [(160, 90), (192, 108), (224, 126)]
    stages = [StageState("bg ember"), StageState("bg sea")]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stage_module, "pygame", counting)
        mp.setattr(transitions, "MaskBuffer", CountedB)
        rig = Rig(tmp_path / "g", sizes[0])
        masked = False

        def check() -> None:
            composites = [s for s in surfaces if not s.get_flags() & pygame.SRCALPHA]
            scratch = [s for s in surfaces if s.get_flags() & pygame.SRCALPHA]
            assert len(composites) <= 2 and len(scratch) <= 1 and len(buffers) <= 1
            assert masked or not buffers                   # no B before the first Mask

        for _ in range(n):
            op = rng.choice(["cut", "dissolve", "fade", "mask", "bad mask", "restore",
                             "finish", "cancel", "resize", "settle"])
            stage = rng.choice(stages)
            if op == "cut":
                rig.screen.show_stage(ShowStage(stage))
            elif op in ("dissolve", "fade", "mask", "bad mask"):
                kind = "mask" if op.endswith("mask") else op
                ref = "masks/corrupt.png" if op == "bad mask" else "masks/quarters.png"
                masked = masked or op == "mask"
                rig.screen.show_stage(ShowStage(stage, transition=spec(
                    kind, rng.choice([0.05, 0.1, 0.2]), mask=ref)))
            elif op == "restore":
                rig.screen.show_stage(ShowStage(stage, restored=True))
            elif op == "finish":
                rig.view.finish()
            elif op == "cancel":
                rig.view.cancel()
            elif op == "resize":
                rig.window.resize(*rng.choice(sizes))
            else:
                rig.limiter.clock.now += 0.25
            check()
            for _ in range(rng.randrange(4)):
                rig.frame(update=True)
                check()
        assert masked and rig.view._masks.buffer is not None   # the stream played masks


# --- AC-F09-41 — one heavy step, few operations ------------------------------------------------

class Spy(pygame.Surface):
    """Records the drawing calls made on it."""
    ops: list[str] = []

    def blit(self, *args, **kwargs):
        Spy.ops.append("blit")
        return super().blit(*args, **kwargs)

    def fill(self, *args, **kwargs):
        Spy.ops.append("fill")
        return super().fill(*args, **kwargs)

    def set_palette(self, *args, **kwargs):
        Spy.ops.append("set_palette")
        return super().set_palette(*args, **kwargs)

    def set_alpha(self, *args, **kwargs):
        Spy.ops.append("set_alpha")
        return super().set_alpha(*args, **kwargs)

    def convert(self, *args, **kwargs):
        Spy.ops.append("convert")
        return super().convert(*args, **kwargs)

    def convert_alpha(self, *args, **kwargs):
        Spy.ops.append("convert")
        return super().convert_alpha(*args, **kwargs)


class _GSpy:
    def __init__(self, g: pygame.Surface) -> None:
        self.g = g

    def blit(self, *args, **kwargs):
        Spy.ops.append("blit")
        return self.g.blit(*args, **kwargs)


def test_ac_f09_41_one_heavy_step_and_few_operations(tmp_path):
    size = (1920, 1080)
    rig = Rig(tmp_path / "g", (320, 180))
    old, new, target = Spy(size, 0, 32), Spy(size, 0, 32), Spy(size, 0, 32)
    old.fill(EMBER)
    new.fill(SEA)
    scratch = Spy(size, pygame.SRCALPHA, 32)
    store = MaskStore(rig.app.assets)
    expected = {"dissolve": ["fill", "blit", "blit"], "fade": ["blit", "fill", "fill"],
                "mask": ["set_palette", "blit", "fill", "blit", "blit", "blit"]}
    scaled = []
    real_smooth = pygame.transform.smoothscale
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pygame.transform, "smoothscale",
                   lambda *a, **k: scaled.append(1) or real_smooth(*a, **k))
        for name, ops in expected.items():
            kind = KINDS[name](KindFrame(old, new, (0, 0, 0), lambda: scratch, spec(name),
                                         store))
            while not kind.prepare_step():
                pass
            if name == "mask":                             # spies on M8 and G
                m8 = Spy(size, 0, 8)
                m8.set_palette(kind.ready.m8.get_palette())
                kind.ready.m8 = m8
                kind.ready.b = types.SimpleNamespace(g=_GSpy(kind.ready.b.g), a=kind.ready.b.a)
            times = []
            for p in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
                Spy.ops.clear()
                scaled.clear()
                started = time.perf_counter()
                kind.draw(target, p, (0, 0))
                times.append(time.perf_counter() - started)
                assert Spy.ops == ops and not scaled, (name, Spy.ops)
            assert statistics.median(times) <= 0.010, (name, times)
    # PREPARING at 1920×1080: a first-use Mask takes ≤ 8 frames, each with one heavy step
    # (a compose, the mask scale, one band of ≤ 270 rows, or the scratch fill).
    rig = Rig(tmp_path / "h", (1920, 1080))
    rig.cut(StageState("bg ember"))
    heavy: list[str] = []
    real_paint, real_smooth = StageView._paint, pygame.transform.smoothscale
    real_tobytes, real_views = pygame.image.tobytes, MaskStore.views
    real_dissolve = transitions.Dissolve.prepare_step

    def tobytes(surface, *args):
        assert surface.get_height() <= 270
        heavy.append("band")
        return real_tobytes(surface, *args)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(StageView, "_paint", lambda *a, **k: heavy.append("compose")
                   or real_paint(*a, **k))
        mp.setattr(pygame.transform, "smoothscale",
                   lambda *a, **k: heavy.append("scale") or real_smooth(*a, **k))
        mp.setattr(pygame.image, "tobytes", tobytes)
        mp.setattr(MaskStore, "views", lambda *a: heavy.append("scratch") or real_views(*a))
        mp.setattr(transitions.Dissolve, "prepare_step",
                   lambda self: heavy.append("scratch") or real_dissolve(self))
        for ref, most in (("masks/iris.png", 8), ("masks/iris.png", 2), ("masks/no.png", 3)):
            rig.view.show(ShowStage(StageState("bg sea"), transition=spec("mask", mask=ref)))
            frames = 0
            while not rig.view._run.running:
                heavy.clear()
                rig.frame()
                frames += 1
                assert len(heavy) <= 1, heavy
            assert frames <= most, (ref, frames)
            rig.view.finish()
            rig.frame()
            rig.cut(StageState("bg ember"))


# --- AC-F09-39 (mask row) — reads only through the asset manager ------------------------------

def test_ac_f09_39_a_valid_mask_reads_only_through_the_asset_manager(tmp_path):
    rig = Rig(tmp_path / "g", (320, 180))
    reads: list[str] = []
    opens: list[tuple[str, bool]] = []
    inside: list[int] = []
    real_read, real_open, real_os_open = GamePaths.read_file, builtins.open, os.open

    def read_file(self, ref, **kwargs):
        caller = sys._getframe(1)
        assert caller.f_globals["__name__"] == "engine.render.assets", caller.f_code.co_name
        reads.append(ref)
        inside.append(1)
        try:
            return real_read(self, ref, **kwargs)
        finally:
            inside.pop()

    def spy_open(file, *args, **kwargs):
        opens.append((str(file), bool(inside)))
        return real_open(file, *args, **kwargs)

    def spy_os_open(path, *args, **kwargs):
        opens.append((str(path), bool(inside)))
        return real_os_open(path, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(GamePaths, "read_file", read_file)
        mp.setattr(builtins, "open", spy_open)
        mp.setattr(io, "open", spy_open)
        mp.setattr(os, "open", spy_os_open)
        for _ in range(2):
            rig.cut(StageState("bg ember"))
            rig.play(ShowStage(StageState("bg sea"),
                               transition=spec("mask", mask="masks/iris.png")), 0.5)
            rig.view.finish()
            rig.frame()
    assert reads.count("masks/iris.png") == 1               # read once, then cached
    iris = [was_inside for path, was_inside in opens if "iris" in path]
    assert iris and all(iris)                               # no other open of the file
    assert "masks/iris.png" not in rig.view._masks.unusable
