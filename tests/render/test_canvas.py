"""Canvas: canvas units → device pixels, images, text layout at every scale.

AC-F01-43 (line breaks independent of window size and quality), 44 (no gaps), and the
canvas parts of AC-F01-157 (d) (FAST text creates no new font size or text line).
"""

import math

import pygame
import pytest

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.render.canvas import Canvas, RenderQuality
from engine.render.text import ELLIPSIS, Face, FontSpec, Synth
from tests.render.conftest import FIXTURES, make_assets

pytestmark = pytest.mark.display

PARAGRAPH = (FIXTURES / "text" / "paragraph.txt").read_text(encoding="utf-8")


def bound_canvas(assets, scale: float, quality=RenderQuality.FINAL, canvas=None):
    size = (round(CANVAS_SIZE[0] * scale), round(CANVAS_SIZE[1] * scale))
    framebuffer = pygame.Surface(size)
    canvas = canvas or Canvas(assets)
    canvas.bind(framebuffer, Viewport.compute(CANVAS_SIZE, size), quality)
    return canvas, framebuffer


# --- AC-F01-44 -----------------------------------------------------------------------------

@pytest.mark.parametrize("scale", [1366 / 1280, 1.5, 0.5])
def test_adjacent_rectangles_never_gap_or_overlap(scale):
    canvas, _ = bound_canvas(make_assets(None), scale)
    first = canvas.rect_to_px((0, 0, 333, 10))
    second = canvas.rect_to_px((333, 0, 333, 10))
    assert first.right == second.left


def test_px_rounds_half_up_per_axis():
    canvas, _ = bound_canvas(make_assets(None), 1.5)
    assert canvas.px(1, 1) == (math.floor(1.5 + 0.5), math.floor(1.5 + 0.5)) == (2, 2)
    assert canvas.px(0, 0) == (0, 0)
    assert canvas.px(1279, 719) == (1919, 1079)


def test_bind_takes_a_subsurface_of_the_viewport_and_asserts_it_fits():
    assets = make_assets(None)
    framebuffer = pygame.Surface((2560, 1080))
    canvas = Canvas(assets)
    canvas.bind(framebuffer, Viewport.compute(CANVAS_SIZE, (2560, 1080)), RenderQuality.FINAL)
    assert canvas.surface.get_size() == (1920, 1080)
    assert canvas.surface.get_abs_offset() == (320, 0)
    assert canvas.final_scale == 1.5
    canvas.fill((1, 2, 3))
    assert framebuffer.get_at((319, 0))[:3] == (0, 0, 0)
    assert framebuffer.get_at((320, 0))[:3] == (1, 2, 3)
    with pytest.raises(AssertionError):
        canvas.bind(pygame.Surface((100, 100)), Viewport.compute(CANVAS_SIZE, (2560, 1080)),
                    RenderQuality.FINAL)


def test_fill_with_alpha_blends():
    canvas, framebuffer = bound_canvas(make_assets(None), 1.0)
    canvas.fill((200, 0, 0))
    canvas.fill((0, 0, 200, 128), (0, 0, 10, 10))
    r, g, b = framebuffer.get_at((5, 5))[:3]
    assert 90 <= r <= 110 and 90 <= b <= 110 and g == 0
    assert framebuffer.get_at((20, 20))[:3] == (200, 0, 0)


# --- images --------------------------------------------------------------------------------

def test_draw_image_with_anchors_at_device_scale(assets):
    canvas, framebuffer = bound_canvas(assets, 1.5)
    image = assets.image("images/bg/club.png")
    canvas.draw_image(image, (0, 0))
    assert framebuffer.get_at((0, 0))[:3] == (0x44, 0x66, 0x88)
    assert framebuffer.get_at((1919, 1079))[:3] == (0x44, 0x66, 0x88)
    canvas.fill((0, 0, 0))
    rgba = assets.image("images/rgba.png")                   # 64×64, left half transparent
    canvas.draw_image(rgba, (640, 360), anchor="center")
    left, top = canvas.px(640 - 32, 360 - 32)
    assert framebuffer.get_at((left + 2, top + 2))[:3] == (0, 0, 0)       # transparent half
    assert framebuffer.get_at((left + 90, top + 2))[:3] == (0x33, 0x66, 0xCC)
    canvas.fill((0, 0, 0))
    canvas.draw_image(rgba, (1280, 720), anchor="bottomright", alpha=128)
    pixel = framebuffer.get_at((1919 - 2, 1079 - 2))[:3]
    assert 0 < pixel[2] < 0xCC                                 # half transparent
    assert rgba is not None and assets.surface(rgba).get_alpha() in (None, 255)


# --- AC-F01-43: line breaks never depend on the window size ----------------------------------

def test_line_breaks_are_the_same_at_every_scale_and_quality(monkeypatch):
    assets = make_assets(None)
    drawn: list[str] = []
    real_text_line = assets.text_line

    def spy(font, text, color):
        drawn.append(text)
        return real_text_line(font, text, color)

    monkeypatch.setattr(assets, "text_line", spy)
    results = []
    for scale in (0.5, 0.75, 1.0, 1.333, 2.0, 3.0):
        for quality in (RenderQuality.FINAL, RenderQuality.FAST):
            canvas, _ = bound_canvas(assets, 1.0)               # a FINAL bind first
            canvas, _ = bound_canvas(assets, scale, quality, canvas)
            drawn.clear()
            bounds = canvas.draw_text(PARAGRAPH, FontSpec(None, 28), (255, 255, 255),
                                      (10, 10), max_width=600)
            results.append(list(drawn))
            assert bounds[2] <= 600
    assert all(lines == results[0] for lines in results)
    assert len(results[0]) >= 4
    assert any(len(line) < 60 and line in PARAGRAPH for line in results[0])


def test_max_lines_cuts_with_an_ellipsis_and_centers():
    assets = make_assets(None)
    canvas, _ = bound_canvas(assets, 1.0)
    title = ("Long title " * 46)[:500]
    lines = canvas.layout_lines(title, FontSpec(None, 48), 1120, 2)
    assert len(lines) == 2 and lines[1].endswith(ELLIPSIS)
    bounds = canvas.draw_text(title, FontSpec(None, 48), (224, 224, 224), (640, 360),
                              anchor="center", max_width=1120, align="center", max_lines=2)
    x, y, w, h = bounds
    assert abs(x + w / 2 - 640) <= 1 and abs(y + h / 2 - 360) <= 1
    assert 80 <= x and x + w <= 1200
    word = canvas.layout_lines("W" * 200, FontSpec(None, 48), 1120, 2)
    assert len(word) == 2 and word[1].endswith(ELLIPSIS)


def test_bottomright_anchor_and_returned_bounds():
    assets = make_assets(None)
    canvas, _ = bound_canvas(assets, 1.0)
    x, y, w, h = canvas.draw_text("0.1.0", FontSpec(None, 20), (160, 160, 160), (1264, 704),
                                  anchor="bottomright")
    assert x + w == pytest.approx(1264) and y + h == pytest.approx(704)


# --- AC-F01-157 (d), canvas part: FAST frames create no new font size or text line ----------

def test_fast_text_reuses_the_final_raster():
    assets = make_assets(None)
    canvas, _ = bound_canvas(assets, 1.5)                       # FINAL at scale 1.5
    spec = FontSpec(None, 28)
    canvas.draw_text("Fixture Game", spec, (224, 224, 224), (100, 100))

    def keys():
        return {key for key in assets.cache.keys() if key[0] in ("font", "text")}

    before = keys()
    for step in range(30):
        scale = 0.6 + step * 0.07
        canvas, framebuffer = bound_canvas(assets, scale, RenderQuality.FAST, canvas)
        canvas.draw_text("Fixture Game", spec, (224, 224, 224), (100, 100))
    assert keys() == before
    canvas, _ = bound_canvas(assets, 2.0, RenderQuality.FINAL, canvas)
    canvas.draw_text("Fixture Game", spec, (224, 224, 224), (100, 100))
    new_fonts = {key for key in keys() - before if key[0] == "font"}
    assert len(new_fonts) == 1


# --- F10 step 4: a FontSpec can ask for a bundled face (F05's Face/Synth) ---------------------

@pytest.mark.parametrize(("face", "name"), [(Face.REGULAR, "<default>"),
                                            (Face.BOLD, "<default-bold>"),
                                            (Face.ITALIC, "<default-italic>")])
def test_font_spec_picks_the_bundled_face(face, name):
    assets = make_assets(None)
    canvas, framebuffer = bound_canvas(assets, 2.0)
    canvas.draw_text("Heading", FontSpec(None, 32, face), (0, 0, 0), (10, 10))
    fonts = {key[1:3] for key in assets.cache.keys() if key[0] == "font"}
    assert fonts == {(name, 32), (name, 64)}         # reference and raster sizes


def test_bold_text_is_wider_than_regular():
    assets = make_assets(None)
    canvas, _ = bound_canvas(assets, 1.0)
    regular = canvas.draw_text("Widget sampler", FontSpec(None, 32), (0, 0, 0), (0, 0))
    bold = canvas.draw_text("Widget sampler", FontSpec(None, 32, Face.BOLD), (0, 0, 0), (0, 0))
    assert bold[2] > regular[2]


def test_plain_specs_keep_the_two_argument_font_call():
    """Stand-ins with ``font(ref, size_px)`` (no face arguments) still work."""
    assets = make_assets(None)
    calls = []

    class TwoArgs:
        cache = assets.cache

        def font(self, ref, size_px):
            calls.append((ref, size_px))
            return assets.font(ref, size_px)

        def text_line(self, font, text, color):
            return assets.text_line(font, text, color)

    canvas = Canvas(TwoArgs())
    canvas.bind(pygame.Surface(CANVAS_SIZE), Viewport.compute(CANVAS_SIZE, CANVAS_SIZE),
                RenderQuality.FINAL)
    canvas.draw_text("Plain", FontSpec(None, 28), (0, 0, 0), (0, 0))
    assert calls and all(ref is None for ref, _ in calls)
    assert FontSpec(None, 28) == FontSpec(None, 28, Face.REGULAR, Synth.NONE)
