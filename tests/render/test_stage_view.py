"""F04 step 5 — the visible stage: ``StageView`` and ``StageScreen`` in render harness V
(``06-acceptance.md`` §0.2): the dummy video driver, an ``AssetManager`` over a game folder
of generated images (``tests/fixtures/F04/gen_images.py``), a ``StageView`` drawn by a
``StageScreen`` in an ``App`` around a ``FakeWindow``, and pixel probes in window pixels.

AC-F04-21 (view side, I-17), 25, 26, 27, 28, 29, 30, 31, 32, 33, 35, 36, 37; ``variant``,
``scaled`` through ``variant`` (I-8), ``adopt``, ``is_cached``.
"""

import json
import logging
import math
from pathlib import Path
from types import MappingProxyType

import pygame
import pytest

from engine.core.config_schema import (Config, StageConfig, StageTheme, ThemeConfig,
                                       WindowConfig)
from engine.core.constants import BUILTIN_POSITIONS, CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.render import stage as stage_module
from engine.render.assets import AssetManager
from engine.render.canvas import Canvas, RenderQuality
from engine.render.placeholder import LABEL_FONT
from engine.render.stage import StageView
from engine.runtime.commands import Say, ShowStage
from engine.runtime.images import ImageFile, ImageIndex, ImageSource, SolidColor, build_index
from engine.runtime.interpreter import Interpreter, RestoreResult
from engine.runtime.launch import run_launch
from engine.runtime.stage import EMPTY_STAGE, SpriteState, StageState
from engine.runtime.state import GameState
from engine.ui.builtin.stage_screen import StageScreen
from tests.fakes.draw_spy import spy_draw_text
from tests.fakes.fake_window import FakeWindow
from tests.fakes.harness import make_app
from tests.fixtures.F04 import gen_images as gen
from tests.runtime.stage_story import IMG_L, lanterns, load_game, run_h, stage, stages, story_game
from tests.runtime.story import advance

pytestmark = pytest.mark.display

MAGENTA = (0xFF, 0x00, 0xFF)
BLACK = (0, 0, 0)
WHITE = (0xFF, 0xFF, 0xFF)
LETTERBOX = (0x12, 0x34, 0x56)
EMPTY = (0x10, 0x20, 0x30)


# --- Harness V ---------------------------------------------------------------------------------

class Rig:
    """A game folder ``root`` holding the image files, an index (``name → ref`` or a
    ``SolidColor``), and an ``App`` on a ``FakeWindow`` whose only screen is a
    ``StageScreen``."""

    def __init__(self, root: Path, index: dict[str, object], *, window=(1280, 720),
                 art_height: int = 720, positions: dict | None = None,
                 empty=(0, 0, 0), letterbox=LETTERBOX, scale_filter: str = "smooth",
                 integer_scale: bool = False, builtins: bool = True) -> None:
        root.mkdir(parents=True, exist_ok=True)
        entries = {name: value if isinstance(value, SolidColor) else ImageFile(value)
                   for name, value in index.items()}
        points = dict(BUILTIN_POSITIONS) if builtins else {}
        for name, value in (positions or {}).items():
            points[name] = (float(value[0]), float(value[1]))
        self.positions = MappingProxyType(points)
        config = Config(window=WindowConfig(letterbox_color=letterbox, scale_filter=scale_filter,
                                            integer_scale=integer_scale),
                        stage=StageConfig(art_height=art_height, positions=self.positions),
                        theme=ThemeConfig(stage=StageTheme(empty_color=empty)))
        self.window = FakeWindow(window)
        self.app, self.limiter = make_app(self.window, config=config,
                                          paths=GamePaths.for_game(root),
                                          scale_filter=scale_filter)
        self.view = StageView(self.app.assets, ImageIndex(entries), art_height=art_height,
                              positions=self.positions, empty_color=empty)
        self.app.screens.push(StageScreen(self.app, self.view))

    def frame(self, shown: StageState | None = None) -> pygame.Surface:
        """Show ``shown`` (if given), fill the framebuffer ``#FF00FF``, and present."""
        if shown is not None:
            self.view.show(ShowStage(shown))
        framebuffer = self.window.framebuffer()
        framebuffer.fill(MAGENTA)
        self.app.present()
        return framebuffer

    def resize(self, width: int, height: int) -> pygame.Surface:
        """A new window size, then the first FINAL frame after F01's settle."""
        self.window.resize(width, height)
        self.frame()                                         # FAST: the settle starts
        self.limiter.clock.now += 0.25
        return self.frame()

    def canvas_area(self) -> pygame.Surface:
        vp = self.app.viewport
        return self.window.framebuffer().subsurface((vp.x, vp.y, vp.w, vp.h))

    def px(self, x: float, y: float) -> tuple[int, int]:
        """Canvas units → viewport pixels (F01's rounding)."""
        vp = self.app.viewport
        return math.floor(x * vp.scale_x + 0.5), math.floor(y * vp.scale_y + 0.5)


def box(surface: pygame.Surface, color, tol: int = 2):
    """The bounding box ``(x0, y0, x1, y1)`` (x1, y1 exclusive) of ``color`` pixels."""
    mask = pygame.mask.from_threshold(surface, color, (tol + 1, tol + 1, tol + 1, 255))
    rects = mask.get_bounding_rects()
    if not rects:
        return None
    r = rects[0].unionall(rects[1:])
    return r.left, r.top, r.right, r.bottom


def near(a, b, tol: int = 3) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3]))


def within(actual, expected, tol: int = 1) -> bool:
    return actual is not None and all(abs(a - e) <= tol for a, e in zip(actual, expected))


def count(surface: pygame.Surface, color, tol: int = 0) -> int:
    return pygame.mask.from_threshold(surface, color, (tol + 1, tol + 1, tol + 1, 255)).count()


def sprite(image: str, at="center", *, tag=None, layer=0, zoom=1.0, flip=False) -> SpriteState:
    return SpriteState(tag or image.split(" ")[0], image, at, layer, zoom, flip)


@pytest.fixture
def variant_calls(monkeypatch):
    """Every ``AssetManager.variant`` call: (ref, size_px, quality, crop)."""
    calls = []
    real = AssetManager.variant

    def variant(self, image, size_px, quality, **kw):
        calls.append((image.ref, tuple(size_px), quality, kw.get("crop")))
        return real(self, image, size_px, quality, **kw)

    monkeypatch.setattr(AssetManager, "variant", variant)
    return calls


@pytest.fixture
def scale_calls(monkeypatch):
    """Sizes passed to ``transform.smoothscale`` and ``transform.scale``."""
    calls = {"smooth": [], "scale": []}
    smooth, scale = pygame.transform.smoothscale, pygame.transform.scale
    monkeypatch.setattr(pygame.transform, "smoothscale",
                        lambda s, size, *a: calls["smooth"].append(tuple(size)) or
                        smooth(s, size, *a))
    monkeypatch.setattr(pygame.transform, "scale",
                        lambda s, size, *a: calls["scale"].append(tuple(size)) or
                        scale(s, size, *a))
    return calls


# --- AssetManager.variant (04 §5.3, I-8) -----------------------------------------------------

def test_variant_source_flip_crop_and_cache(tmp_path):
    gen.write(tmp_path, {"images/q.png": gen.quadrants(40, 20)})
    rig = Rig(tmp_path, {})
    assets = rig.app.assets
    image = assets.image("images/q.png")
    source = assets.surface(image)
    assert assets.variant(image, (40, 20), RenderQuality.FINAL) == (source, (0, 0))
    entries = len(assets.cache)
    big, offset = assets.variant(image, (80, 40), RenderQuality.FINAL)
    assert big.get_size() == (80, 40) and offset == (0, 0) and len(assets.cache) == entries + 1
    assert assets.variant(image, (80, 40), RenderQuality.FINAL)[0] is big       # cached
    fast, _ = assets.variant(image, (80, 40), RenderQuality.FAST)
    assert fast is not big and len(assets.cache) == entries + 1                 # never cached
    flipped, _ = assets.variant(image, (40, 20), RenderQuality.FINAL, flip_x=True)
    assert flipped.get_at((1, 1))[:3] == gen.QUADRANT_COLORS[1]                 # mirrored
    # A crop of the mirrored, doubled variant: the right half shows the source's left.
    part, at = assets.variant(image, (80, 40), RenderQuality.FINAL, flip_x=True,
                              crop=(40, 0, 40, 40))
    assert at == (40, 0) and part.get_size() == (40, 40)
    assert near(part.get_at((5, 5)), gen.QUADRANT_COLORS[0])
    assert near(part.get_at((5, 35)), gen.QUADRANT_COLORS[2])
    # scaled() goes through variant(): the same cached surface (I-8).
    assert assets.scaled(image, 2.0, 2.0, RenderQuality.FINAL) is big


def test_adopt_and_is_cached(tmp_path):
    rig = Rig(tmp_path, {})
    assets = rig.app.assets
    assert not assets.is_cached("images/x.png")
    source = gen.block(10, 10, (1, 2, 3))
    scaled = gen.block(20, 20, (1, 2, 3))
    image_key = ("img", "images/x.png")
    key = ("variant", image_key, (20, 20), False, None, assets.scale_filter)
    assets.adopt("images/x.png", source, {key: scaled})
    assert assets.is_cached("images/x.png")
    image = assets.image("images/x.png")                     # no file: from the cache
    assert not image.is_placeholder and image.size == (10, 10)
    assert assets.variant(image, (20, 20), RenderQuality.FINAL)[0] is scaled


# --- AC-F04-25 — the stage paints every canvas pixel and nothing else --------------------------

def test_ac_f04_25_every_canvas_pixel_and_no_bar(tmp_path):
    gen.write(tmp_path, {"images/hana/happy.png": gen.block(100, 200, (0xE0, 0x30, 0x30))})
    rig = Rig(tmp_path, {"hana happy": "images/hana/happy.png"}, window=(1920, 1200),
              empty=EMPTY, letterbox=BLACK)
    for shown in (EMPTY_STAGE, StageState(None, (sprite("hana happy"),))):
        fb = rig.frame(shown)
        vp = rig.app.viewport
        assert (vp.x, vp.y, vp.w, vp.h) == (0, 60, 1920, 1080)
        assert count(rig.canvas_area(), MAGENTA) == 0
        assert fb.get_at((960, 30))[:3] == BLACK and fb.get_at((960, 1170))[:3] == BLACK
        if not shown.sprites:
            for point in ((0, 60), (1919, 60), (0, 1139), (1919, 1139), (960, 600)):
                assert fb.get_at(point)[:3] == EMPTY, point
        else:
            area = rig.canvas_area()
            sprite_pixels = count(area, (0xE0, 0x30, 0x30), tol=3)
            assert sprite_pixels and sprite_pixels + count(area, EMPTY) == 1920 * 1080


# --- AC-F04-26 — backgrounds cover the canvas ------------------------------------------------

COVER = [  # source, {viewport: (size, offset)}, bands visible
    ((1920, 1080), {(1024, 576): ((1024, 576), (0, 0)), (1280, 720): ((1280, 720), (0, 0)),
                    (1920, 1080): ((1920, 1080), (0, 0))}, "tblr"),
    ((1280, 720), {(1024, 576): ((1024, 576), (0, 0)), (1280, 720): ((1280, 720), (0, 0)),
                   (1920, 1080): ((1920, 1080), (0, 0))}, "tblr"),
    ((3840, 2160), {(1024, 576): ((1024, 576), (0, 0)), (1280, 720): ((1280, 720), (0, 0)),
                    (1920, 1080): ((1920, 1080), (0, 0))}, "tblr"),
    ((640, 360), {(1024, 576): ((1024, 576), (0, 0)), (1280, 720): ((1280, 720), (0, 0)),
                  (1920, 1080): ((1920, 1080), (0, 0))}, "tblr"),
    ((1024, 768), {(1024, 576): ((1024, 768), (0, -96)), (1280, 720): ((1280, 960), (0, -120)),
                   (1920, 1080): ((1920, 1440), (0, -180))}, "lr"),
    ((2560, 1080), {(1024, 576): ((1366, 576), (-171, 0)),
                    (1280, 720): ((1707, 720), (-214, 0)),
                    (1920, 1080): ((2560, 1080), (-320, 0))}, "tb"),
    ((1080, 1920), {(1024, 576): ((1024, 1821), (0, -623)),
                    (1280, 720): ((1280, 2276), (0, -778)),
                    (1920, 1080): ((1920, 3414), (0, -1167))}, "lr"),
]


def _bands(area: pygame.Surface) -> str:
    w, h = area.get_size()
    seen = ""
    for name, point, color in (("t", (w // 2, 0), gen.RED), ("b", (w // 2, h - 1), gen.GREEN),
                               ("l", (0, h // 2), gen.BLUE), ("r", (w - 1, h // 2), gen.YELLOW)):
        pixel = area.get_at(point)
        if near(pixel, color, 6):
            seen += name
        else:
            assert near(pixel, gen.GRAY, 6), (name, pixel)
    return seen


@pytest.mark.parametrize("source, rows, bands", COVER, ids=lambda v: str(v))
def test_ac_f04_26_cover_fit(tmp_path, variant_calls, scale_calls, source, rows, bands):
    gen.write(tmp_path, {"images/bg/x.png": gen.edge_marked(*source)})
    rig = Rig(tmp_path, {"bg x": "images/bg/x.png"}, window=(1024, 576), empty=EMPTY)
    first = True
    for viewport, (size, offset) in rows.items():
        variant_calls.clear()
        scale_calls["smooth"].clear()
        if first:
            rig.frame(StageState("bg x"))
            first = False
        else:
            rig.resize(*viewport)
        finals = [c for c in variant_calls if c[2] is RenderQuality.FINAL]
        assert finals and all(c[1] == size for c in finals), (viewport, finals)
        # Never stretched: the same scale on both axes (within the rounding up).
        assert abs(size[0] / source[0] - size[1] / source[1]) * max(source) <= 1.0
        # The offset of the full variant: ((vw - w) // 2, (vh - h) // 2).
        assert ((viewport[0] - size[0]) // 2, (viewport[1] - size[1]) // 2) == offset
        assert _bands(rig.canvas_area()) == bands, viewport
        if size == source:                       # 1:1: the source itself, no scale call
            assert scale_calls["smooth"] == []


@pytest.mark.parametrize("window", [(1366, 768), (1001, 563), (1279, 719), (2561, 1441)])
def test_ac_f04_26_no_unpainted_edge(tmp_path, window):
    gen.write(tmp_path, {"images/bg/a.png": gen.edge_marked(1920, 1080),
                         "images/bg/b.png": gen.edge_marked(1024, 768)})
    rig = Rig(tmp_path, {"bg a": "images/bg/a.png", "bg b": "images/bg/b.png"}, window=window,
              empty=EMPTY)
    for name in ("bg a", "bg b"):
        rig.frame(StageState(name))
        area = rig.canvas_area()
        w, h = area.get_size()
        edge = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)] + \
               [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)]
        for point in edge:
            pixel = area.get_at(point)[:3]
            assert pixel != EMPTY and pixel != MAGENTA, (name, point, pixel)


# --- AC-F04-27 — sprite size and anchor ------------------------------------------------------

@pytest.mark.parametrize("window, art_height, zoom, expected", [
    ((1280, 720), 720, 1.0, (190, 0, 1090, 720)),
    ((1280, 720), 1080, 1.0, (340, 0, 940, 720)),
    ((1280, 720), 1080, 0.5, (490, 220, 790, 720)),
    ((1280, 720), 2160, 1.0, (490, 220, 790, 720)),
    ((1920, 1080), 1080, 1.0, (510, 0, 1410, 1080)),
    ((1024, 576), 1080, 1.0, (272, 0, 752, 576)),
])
def test_ac_f04_27_sprite_size_and_anchor(tmp_path, scale_calls, window, art_height, zoom,
                                          expected):
    color = (0xE0, 0x30, 0x30)
    gen.write(tmp_path, {"images/big.png": gen.block(900, 1500, color)})
    rig = Rig(tmp_path, {"big": "images/big.png"}, window=window, art_height=art_height)
    rig.frame(StageState(None, (sprite("big", zoom=zoom),)))
    assert within(box(rig.canvas_area(), color), expected)
    if window == (1920, 1080):
        assert scale_calls["smooth"] == [] and scale_calls["scale"] == []   # the source itself


# --- AC-F04-28 — positions on screen, and clipping -------------------------------------------

GREEN_BLOCK = (0x30, 0xE0, 0x30)


@pytest.mark.parametrize("at, expected", [
    ("left", (270, 520, 370, 720)), ("center", (590, 520, 690, 720)),
    ("right", (910, 520, 1010, 720)), ((640, 400), (590, 200, 690, 400)),
    ((1250,), (1200, 520, 1280, 720)), ((-600,), None),
])
def test_ac_f04_28_positions_and_clipping(tmp_path, at, expected):
    gen.write(tmp_path, {"images/g.png": gen.block(100, 200, GREEN_BLOCK)})
    rig = Rig(tmp_path, {"g": "images/g.png"})
    rig.frame(StageState(None, (sprite("g", at),)))
    found = box(rig.canvas_area(), GREEN_BLOCK)
    assert found == expected if expected is None else within(found, expected)


def test_ac_f04_28_author_positions_and_the_bars(tmp_path):
    gen.write(tmp_path, {"images/g.png": gen.block(100, 200, GREEN_BLOCK)})
    rig = Rig(tmp_path, {"g": "images/g.png"}, positions={"left": (200, 720)})
    rig.frame(StageState(None, (sprite("g", "left"),)))
    assert within(box(rig.canvas_area(), GREEN_BLOCK), (150, 520, 250, 720))
    tall = Rig(tmp_path, {"g": "images/g.png"}, window=(1920, 1200))
    fb = tall.frame(StageState(None, (sprite("g", (640, 900)),)))
    assert fb.get_at((960, 1170))[:3] == LETTERBOX
    wide = Rig(tmp_path, {"g": "images/g.png"}, window=(2000, 1080))
    fb = wide.frame(StageState(None, (sprite("g", (1250,)),)))
    assert wide.app.viewport.x == 40 and fb.get_at((1990, 540))[:3] == LETTERBOX
    assert count(fb.subsurface((1960, 0, 40, 1080)), GREEN_BLOCK, 3) == 0


# --- AC-F04-29 — draw order on screen ----------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("∅ | a@(600), b@(640), c@(680)", gen.BLUE),
    ("∅ | a@(600), c@(680), b@(640) L10", gen.GREEN),
    ("∅ | c@(680), b@(640), a@(600)", gen.RED),
])
def test_ac_f04_29_draw_order(tmp_path, text, expected):
    gen.write(tmp_path, {"images/a.png": gen.block(400, 600, gen.RED),
                         "images/b.png": gen.block(400, 600, gen.GREEN),
                         "images/c.png": gen.block(400, 600, gen.BLUE)})
    rig = Rig(tmp_path, {"a": "images/a.png", "b": "images/b.png", "c": "images/c.png"})
    fb = rig.frame(stage(text))
    assert fb.get_at((660, 500))[:3] == expected


# --- AC-F04-30 — zoom and flip on screen --------------------------------------------------------

def test_ac_f04_30_zoom_and_flip(tmp_path):
    gen.write(tmp_path, {"images/h.png": gen.half_and_half(200, 300)})
    rig = Rig(tmp_path, {"h": "images/h.png"})

    def drawn(**mods):
        fb = rig.frame(StageState(None, (sprite("h", **mods),)))
        red, blue = box(fb, gen.RED), box(fb, gen.BLUE)
        whole = (min(red[0], blue[0]), min(red[1], blue[1]), max(red[2], blue[2]),
                 max(red[3], blue[3]))
        return fb.copy(), whole

    _, whole = drawn(zoom=2.0)
    assert within(whole, (440, 120, 840, 720))
    fb, whole = drawn(flip=True)
    assert within(whole, (540, 420, 740, 720))
    assert fb.get_at((600, 600))[:3] == gen.BLUE and fb.get_at((680, 600))[:3] == gen.RED
    both, _ = drawn(zoom=2.0, flip=True)
    assert both.get_at((500, 600))[:3] == gen.BLUE and both.get_at((780, 600))[:3] == gen.RED


def test_ac_f04_30_modifier_order_gives_one_stage(tmp_path):
    """``zoom 2 flip on`` and ``flip on zoom 2`` give the same ``StageState`` (so the same
    frame)."""
    results = []
    for k, mods in enumerate(("zoom 2 flip on", "flip on zoom 2")):
        program = story_game(tmp_path / str(k), [f"show hana happy {mods}", '"A."'])
        results.append(stages(run_h(program))[-1])
    assert results[0] == results[1]
    assert results[0].sprites[0].zoom == 2.0 and results[0].sprites[0].flip is True


# --- AC-F04-31 — solid-color images --------------------------------------------------------------

def test_ac_f04_31_solid_colors(tmp_path):
    tint = (0x40, 0x20, 0x40)
    gen.write(tmp_path, {"images/bg/river_night.png": gen.edge_marked(1280, 720),
                         "images/a.png": gen.block(100, 200, gen.RED),
                         "images/b.png": gen.block(100, 200, gen.GREEN)})
    rig = Rig(tmp_path, {"black": SolidColor((0, 0, 0)), "tint": SolidColor(tint),
                         "bg river_night": "images/bg/river_night.png",
                         "a": "images/a.png", "b": "images/b.png"}, empty=EMPTY)
    rig.frame(StageState("black"))
    assert count(rig.canvas_area(), BLACK) == 1280 * 720
    rig.frame(StageState("bg river_night", (
        sprite("a", "left"), sprite("tint", (100,), zoom=3.0, flip=True),
        sprite("b", "right"))))
    area = rig.canvas_area()
    b_box = box(area, gen.GREEN, 0)
    assert within(b_box, (910, 520, 1010, 720))
    assert count(area, gen.GREEN) == 100 * 200
    assert count(area, tint) == 1280 * 720 - 100 * 200


# --- AC-F04-32 — missing background ------------------------------------------------------------

def _band_rows(area: pygame.Surface, x: int, y0: int, y1: int) -> bool:
    return all(area.get_at((x, y))[:3] == BLACK for y in range(y0, y1))


def test_ac_f04_32_missing_background(tmp_path, monkeypatch):
    gen.write(tmp_path, {"images/hana/happy.png": gen.block(100, 200, (0xE0, 0x30, 0x30))})
    rig = Rig(tmp_path, {"hana happy": "images/hana/happy.png"})
    with spy_draw_text(monkeypatch) as calls:
        fb = rig.frame(StageState("bg forest", (sprite("hana happy", "left"),)))
    assert fb.get_at((5, 5))[:3] == (0x20, 0x20, 0x20)
    assert fb.get_at((528, 248))[:3] == MAGENTA and fb.get_at((560, 248))[:3] == BLACK
    assert fb.get_at((511, 248))[:3] == (0x20, 0x20, 0x20)      # 256×256 at (512, 232)
    assert fb.get_at((767, 487))[:3] in (MAGENTA, BLACK)
    assert fb.get_at((768, 487))[:3] == (0x20, 0x20, 0x20)
    labels = [c for c in calls if c.text == "no image: bg forest"]
    assert len(labels) == 1
    call = labels[0]
    assert call.font == LABEL_FONT and call.color == WHITE and call.pos == (640, 360)
    assert call.options["anchor"] == "center" and call.options["max_width"] == 232
    assert call.options["max_lines"] == 6
    line_size = rig.app.canvas.font_handle(LABEL_FONT, 20).font.get_linesize()
    lines = rig.app.canvas.layout_lines(call.text, LABEL_FONT, 232, 6)
    band = len(lines) * line_size + 16
    top = 360 - band / 2
    assert abs(call.bounds[1] - (top + 8)) <= 0.5                 # 8 units above the text
    assert _band_rows(fb, 512, math.ceil(top), math.floor(top + band))
    assert _band_rows(fb, 767, math.ceil(top), math.floor(top + band))
    assert fb.get_at((320, 700))[:3] == (0xE0, 0x30, 0x30)       # the sprite over the fill


def test_ac_f04_32_a_broken_file_shows_f01_label(tmp_path, monkeypatch, caplog):
    gen.write(tmp_path, {"images/bg/forest.png": b""})
    rig = Rig(tmp_path, {"bg forest": "images/bg/forest.png"})
    with spy_draw_text(monkeypatch) as calls, caplog.at_level(logging.WARNING, logger="vn"):
        fb = rig.frame(StageState("bg forest"))
    assert [c.text for c in calls] == ["images/bg/forest.png"]
    assert fb.get_at((5, 5))[:3] == (0x20, 0x20, 0x20)
    assert len([r for r in caplog.records if r.name == "vn.assets"]) == 1


# --- AC-F04-33 — missing sprite ---------------------------------------------------------------

def test_ac_f04_33_missing_sprite(tmp_path, monkeypatch):
    rig = Rig(tmp_path, {})
    with spy_draw_text(monkeypatch) as calls:
        fb = rig.frame(StageState(None, (sprite("daichi smiel"),))).copy()
    assert fb.get_at((479, 400))[:3] == BLACK and fb.get_at((800, 400))[:3] == BLACK
    assert fb.get_at((496, 160))[:3] == MAGENTA and fb.get_at((528, 160))[:3] == BLACK
    assert fb.get_at((482, 336))[:3] == BLACK
    assert box(fb, MAGENTA, 0) == (480, 144, 800, 720)
    (call,) = calls
    assert call.text == "no image: daichi smiel" and call.font == LABEL_FONT
    assert call.color == WHITE and call.pos == (640, 336)
    assert call.options["max_width"] == 296 and call.options["max_lines"] == 6
    line_size = rig.app.canvas.font_handle(LABEL_FONT, 20).font.get_linesize()
    band = len(rig.app.canvas.layout_lines(call.text, LABEL_FONT, 296, 6)) * line_size + 16
    assert _band_rows(fb, 480, math.ceil(336 - band / 2), math.floor(336 + band / 2))
    assert _band_rows(fb, 799, math.ceil(336 - band / 2), math.floor(336 + band / 2))
    # Zoom, flip, and art_height don't change it (never mirrored).
    other = Rig(tmp_path / "other", {}, art_height=1080)
    same = other.frame(StageState(None, (sprite("daichi smiel", zoom=2.0, flip=True),)))
    assert same.get_at((496, 160))[:3] == MAGENTA
    assert pygame.image.tobytes(same, "RGB") == pygame.image.tobytes(fb, "RGB")
    # Left, center, and right touch without overlap.
    fb = rig.frame(StageState(None, (sprite("x a", "left"), sprite("y b", "center"),
                                     sprite("z c", "right"))))
    assert fb.get_at((479, 150))[:3] == BLACK and fb.get_at((480, 150))[:3] == MAGENTA


def test_ac_f04_33_long_names_and_device_text(tmp_path, monkeypatch):
    rig = Rig(tmp_path, {})
    with spy_draw_text(monkeypatch) as calls:
        rig.frame(StageState(None, (sprite("x" * 600, tag="x"),)))
    lines = rig.app.canvas.layout_lines(calls[0].text, LABEL_FONT, 296, 6)
    assert 1 <= len(lines) <= 6 and lines[-1].endswith("…")

    def glyph_height(window) -> float:
        r = Rig(tmp_path / f"w{window[0]}", {}, window=window)
        fb = r.frame(StageState(None, (sprite("daichi smiel"),)))
        area = r.canvas_area()
        x0, y0 = r.px(480, 336 - 40)
        x1, y1 = r.px(800, 336 + 40)
        white = box(area.subsurface((x0, y0, x1 - x0, y1 - y0)), WHITE, 60)
        assert white is not None and fb is not None
        return white[3] - white[1]

    assert glyph_height((1920, 1080)) >= 1.4 * glyph_height((1280, 720))


# --- AC-F04-21 (view side, I-17) — a restore after a patch -----------------------------------

LANTERN_COLORS = {"stall": (0xC0, 0x60, 0x20), "hana happy": (0xE0, 0x30, 0x30),
                  "hana pout": (0xE0, 0x30, 0x90), "hana surprised": (0xE0, 0x90, 0x30),
                  "hana sad": (0x90, 0x30, 0xE0), "daichi grin": (0x30, 0x30, 0xE0),
                  "daichi sigh": (0x30, 0x90, 0xE0), "railing": (0x60, 0x60, 0x60),
                  "lantern_girl": (0x30, 0xE0, 0x30)}


def lanterns_game(root: Path) -> Path:
    """``lanterns/`` with its images (§5.2's render variant): 300×600 blocks and an
    edge-marked 1920×1080 background."""
    lanterns(root)
    files = {gen.ref_of(name): gen.block(300, 600, color)
             for name, color in LANTERN_COLORS.items()}
    files["images/bg/river_night.png"] = gen.edge_marked(1920, 1080)
    gen.write(root, files)
    return root


def _image_index(root: Path, program) -> ImageIndex:
    from engine.app.loading import image_source

    return build_index(program, image_source(GamePaths.for_game(root)))


def _line3_save(root: Path) -> dict:
    """Line 3's checkpoint of ``lanterns/``, saved as JSON."""
    program = load_game(root)
    launch = run_launch(program, images=ImageSource.from_files(IMG_L))
    interp = Interpreter(program, launch.namespace)
    interp.new_game(42)
    interp.run(10_000)
    for _ in range(2):
        advance(interp)
    return json.loads(json.dumps(interp.checkpoint().to_json()))


@pytest.mark.parametrize("patch", ["moved", "removed", "sprite_deleted", "bg_deleted"])
def test_ac_f04_21_restore_after_a_patch(tmp_path, monkeypatch, caplog, patch):
    root = lanterns_game(tmp_path / "game")
    saved = _line3_save(root)
    assert StageState.from_json(saved["stage"]) == stage(
        "bg river_night | stall@stall_spot, hana pout@center, daichi grin@right")
    config = root / "config.toml"
    text = config.read_text(encoding="utf-8")
    if patch == "moved":
        config.write_text(text.replace("stall_spot = 1060", "stall_spot = 200"), "utf-8")
    elif patch == "removed":
        config.write_text(text.replace("stall_spot = 1060", ""), "utf-8")
        (root / "script" / "chapter1.vns").write_text(
            (root / "script" / "chapter1.vns").read_text("utf-8").replace(
                "show stall at stall_spot", "show stall"), "utf-8")
    elif patch == "sprite_deleted":
        (root / "images" / "daichi" / "grin.png").unlink()
    else:
        (root / "images" / "bg" / "river_night.png").unlink()
    # The patched game launches again; the save is restored into it.
    program = load_game(root)
    from engine.core.config import load_config

    stage_config = load_config(GamePaths.for_game(root)).config.stage
    index = _image_index(root, program)
    interp = Interpreter(program, run_launch(program).namespace)
    assert interp.restore(GameState.from_json(saved)).result is RestoreResult.OK
    (shown,) = [c for c in interp.take_commands(1000) if type(c) is ShowStage]
    assert shown.restored
    rig = Rig(root, {}, art_height=stage_config.art_height,
              positions=dict(stage_config.positions))
    rig.view.index = index
    with caplog.at_level(logging.DEBUG, logger="vn"), spy_draw_text(monkeypatch) as calls:
        fb = rig.frame(shown.stage)
    warnings = [r.getMessage() for r in caplog.records
                if r.name == "vn.stage" and r.levelno >= logging.WARNING]
    # art_height 1080: the 300×600 blocks are 200×400 canvas units.
    stall = box(fb, LANTERN_COLORS["stall"], 3)
    if patch == "moved":
        assert warnings == []
        assert abs((stall[0] + stall[2]) / 2 - 200) <= 1 and stall[3] == 720
    elif patch == "removed":
        assert warnings == ['A restored game puts stall at the position "stall_spot", which '
                            "config.toml no longer has, so stall is shown at center."]
        assert within(box(fb, LANTERN_COLORS["hana pout"], 3), (540, 320, 740, 720))
        caplog.clear()
        rig.frame(shown.stage)                         # restored again: no second W15
        rig.view.show(ShowStage(shown.stage, restored=True))
        assert not [r for r in caplog.records if r.name == "vn.stage"]
    elif patch == "sprite_deleted":
        assert warnings == []
        assert [c.text for c in calls] == ["no image: daichi grin"]
        assert box(fb, MAGENTA, 0) == (800, 144, 1120, 720)
    else:
        assert warnings == []
        assert fb.get_at((5, 5))[:3] == (0x20, 0x20, 0x20)
        assert [c.text for c in calls] == ["no image: bg river_night"]
        assert within(box(fb, LANTERN_COLORS["daichi grin"], 3), (860, 320, 1060, 720))


# --- AC-F04-35 — the same composition at every window size -------------------------------------

LINE5 = "bg river_night | stall@stall_spot, hana happy@hana_close, daichi grin@right"
# Canvas boxes of what shows of each sprite (daichi stands in front of the stall).
LINE5_BOXES = {"stall": (1060, 320, 1160, 720), "hana happy": (460, 360, 660, 720),
               "daichi grin": (860, 320, 1060, 720)}


def _line5_rig(root: Path, **kwargs) -> tuple[Rig, StageState]:
    lanterns_game(root)
    program = load_game(root)
    commands = run_h(program, images=IMG_L)
    says = [i for i, c in enumerate(commands) if type(c) is Say]
    line5 = [c.stage for c in commands[:says[4]] if type(c) is ShowStage][-1]
    assert line5 == stage(LINE5)
    rig = Rig(root, {name: gen.ref_of(name) for name in LANTERN_COLORS} |
              {"bg river_night": "images/bg/river_night.png"}, art_height=1080,
              positions={"stall_spot": (1060, 720), "hana_close": (560, 760)}, **kwargs)
    return rig, line5


def _check_boxes(rig: Rig, tol: int) -> None:
    area = rig.canvas_area()
    for name, (x0, y0, x1, y1) in LINE5_BOXES.items():
        left, top = rig.px(x0, y0)
        right, bottom = rig.px(x1, y1)
        assert within(box(area, LANTERN_COLORS[name], 3), (left, top, right, bottom), tol), \
            (name, area.get_size())
    w, h = area.get_size()
    for point, color in (((w // 2, 0), gen.RED), ((rig.px(200, 0)[0], h - 1), gen.GREEN),
                         ((0, h // 2), gen.BLUE), ((w - 1, h // 2), gen.YELLOW)):
        assert near(area.get_at(point), color, 6), (point, area.get_at(point))


def test_ac_f04_35_every_window_size(tmp_path):
    rig, line5 = _line5_rig(tmp_path / "game")
    rig.frame(line5)
    _check_boxes(rig, 1)
    for size in ((1024, 768), (1920, 1080), (2560, 1440)):
        rig.resize(*size)
        _check_boxes(rig, 1)
    rig.window.set_fullscreen(True)                       # desktop 1920×1080
    rig.frame()
    rig.limiter.clock.now += 0.25
    rig.frame()
    _check_boxes(rig, 1)


def test_ac_f04_35_resize_settle(tmp_path, variant_calls):
    rig, line5 = _line5_rig(tmp_path / "game")
    rig.frame(line5)
    variant_calls.clear()
    rig.window.resize(1920, 1080)
    for _ in range(5):                                    # the settle: FAST
        rig.frame()
        assert rig.app.canvas.quality is RenderQuality.FAST
        _check_boxes(rig, 2)
    assert variant_calls == []
    rig.limiter.clock.now += 0.2
    rig.frame()
    assert rig.app.canvas.quality is RenderQuality.FINAL
    _check_boxes(rig, 1)


def test_ac_f04_35_pixel_filter_and_integer_scale(tmp_path, scale_calls):
    rig, line5 = _line5_rig(tmp_path / "game", scale_filter="pixel")
    rig.frame(line5)
    assert scale_calls["smooth"] == [] and scale_calls["scale"]
    whole, _ = _line5_rig(tmp_path / "game2", integer_scale=True, window=(2000, 1200),
                          letterbox=LETTERBOX)
    fb = whole.frame(line5)
    vp = whole.app.viewport
    assert (vp.x, vp.y, vp.w, vp.h) == (360, 240, 1280, 720)
    assert count(whole.canvas_area(), MAGENTA) == 0
    for point in ((359, 600), (1640, 600), (1000, 239), (1000, 960)):
        assert fb.get_at(point)[:3] == LETTERBOX, point


# --- AC-F04-36 — a still stage costs one blit per frame --------------------------------------

class _CountingSurface:
    """Stands in for ``canvas.surface``: counts blits, forwards the rest."""

    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.blits = 0

    def get_size(self):
        return self.surface.get_size()

    def blit(self, *args, **kwargs):
        self.blits += 1
        return self.surface.blit(*args, **kwargs)


def test_ac_f04_36_one_blit_per_frame(tmp_path, monkeypatch, variant_calls):
    rig, line5 = _line5_rig(tmp_path / "game")
    rig.frame(line5)
    images = []
    real_image = AssetManager.image
    monkeypatch.setattr(AssetManager, "image",
                        lambda self, ref: images.append(ref) or real_image(self, ref))
    composes = []
    real_compose = StageView._compose
    monkeypatch.setattr(StageView, "_compose",
                        lambda self, canvas: composes.append(1) or real_compose(self, canvas))
    variant_calls.clear()
    framebuffer = pygame.Surface((1280, 720))
    canvas = Canvas(rig.app.assets)
    viewport = Viewport.compute(CANVAS_SIZE, (1280, 720))
    for _ in range(60):
        canvas.bind(framebuffer, viewport, RenderQuality.FINAL)
        counting = _CountingSurface(canvas.surface)
        canvas.surface = counting                       # type: ignore[assignment]
        rig.view.draw(canvas)
        assert counting.blits == 1
    for _ in range(60):
        rig.frame()
    assert variant_calls == [] and images == [] and composes == []
    rig.view.show(ShowStage(stage("bg river_night | hana sad@left")))
    rig.frame()
    assert len(composes) == 1
    variant_calls.clear()
    for _ in range(10):
        rig.frame()
    assert variant_calls == [] and len(composes) == 1


# --- AC-F04-37 — huge sprites are cropped before scaling -------------------------------------

def _quadrant_boxes(rig: Rig) -> list:
    area = rig.canvas_area()
    return [box(area, color, 3) for color in gen.QUADRANT_COLORS]


def test_ac_f04_37_cropped_matches_uncropped(tmp_path, monkeypatch, scale_calls):
    gen.write(tmp_path, {"images/q.png": gen.quadrants(2000, 2000)})
    rig = Rig(tmp_path, {"q": "images/q.png"})
    shown = StageState(None, (sprite("q", zoom=4.0),))
    rig.frame(shown)
    cropped = _quadrant_boxes(rig)
    limit = 2 * 1280 * 720 + 1280 + 720 + 1
    assert all(w * h <= limit for w, h in scale_calls["smooth"]), scale_calls["smooth"]
    monkeypatch.setattr(stage_module, "CROP_AREA_FACTOR", 10 ** 9)
    reference = Rig(tmp_path, {"q": "images/q.png"})
    reference.frame(shown)
    full = _quadrant_boxes(reference)
    assert [b is None for b in cropped] == [b is None for b in full]
    for a, b in zip(cropped, full):
        assert a is None or within(a, b, 1), (a, b)


@pytest.mark.slow
def test_ac_f04_37_4k_memory_bound(tmp_path, scale_calls):
    gen.write(tmp_path, {"images/q.png": gen.quadrants(4096, 8192)})
    rig = Rig(tmp_path, {"q": "images/q.png"}, window=(3840, 2160))
    rig.frame(StageState(None, (sprite("q", zoom=4.0),)))
    limit = 2 * 3840 * 2160 + 3840 + 2160 + 1
    assert scale_calls["smooth"] and all(w * h <= limit for w, h in scale_calls["smooth"])
    assert rig.view.picture().get_size() == (3840, 2160)


# --- StageScreen --------------------------------------------------------------------------------

def test_stage_screen_is_opaque_in_game_and_takes_no_input(tmp_path):
    rig = Rig(tmp_path, {})
    screen = rig.app.screens.top
    assert isinstance(screen, StageScreen) and screen.opaque and screen.in_game
    assert screen.handle_event(object()) is False             # type: ignore[arg-type]
    screen.show_stage(ShowStage(StageState("nothing here")))
    rig.frame()
    assert rig.window.framebuffer().get_at((5, 5))[:3] == (0x20, 0x20, 0x20)
    screen.clear()
    rig.frame()
    assert rig.window.framebuffer().get_at((5, 5))[:3] == BLACK
    assert rig.view.picture() is not None
