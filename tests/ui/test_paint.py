"""ui/paint.py: the painter's States table, label fit, frame-image fallback, and shape cache.

F10 SPEC step 2 (no ACs of its own; AC-F10-15, 16, 19 prove it in step 4). The cache tests
are the unit form of TR-F10-04 (no shape built on a steady second draw).

Related checks share one test (fresh ``make_assets(None)`` where a section counts builds or
keys): every ``tests/ui`` test pays for ``pygame.init()``/``quit()`` (test-review-F10.md).
"""

from dataclasses import dataclass

import pygame
import pytest

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.render.canvas import Canvas, RenderQuality
from engine.render.frames import FrameSpec
from engine.render.text import ELLIPSIS, FontSpec
from engine.ui.paint import (
    HEADING_AREA,
    SHAPE_KEY,
    PaintStyle,
    Painter,
    StyleTable,
    fit_label,
    frame_state,
)
from tests.render.conftest import copy_game, make_assets

pytestmark = pytest.mark.display

FILL = (0xFF, 0xF4, 0xF8)
FOCUS_FILL = (0xFF, 0xD6, 0xE8)
PRESS_FILL = (0xFF, 0xC2, 0xDC)
BORDER = (0xF0, 0xA0, 0xC0)
ACCENT = (0xA0, 0x28, 0x60)
TEXT = (0x3D, 0x2B, 0x36)
BACKGROUND = (0, 0, 0)


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Look:
    state: str = "normal"
    on: bool | None = None
    selected: bool = False


def button(fill, border_width, border=BORDER, **kw):
    kw = {"font": FontSpec(None, 28), "text_color": TEXT, "marker_color": ACCENT, **kw}
    return PaintStyle(frame=FrameSpec(fill, 1.0, border, border_width, 12), **kw)


def styles(extra=None) -> StyleTable:
    table = {
        ("panel", "normal"): PaintStyle(frame=FrameSpec(FILL, 1.0, BORDER, 2, 16)),
        ("button", "normal"): button(FILL, 2),
        ("button", "focused"): button(FOCUS_FILL, 4, ACCENT),
        ("button", "pressed"): button(PRESS_FILL, 4, ACCENT),
        ("button", "selected"): button(FOCUS_FILL, 2),
        ("button", "disabled"): button(FILL, 0, text_color=(0x6E, 0x5E, 0x68)),
        ("row", "normal"): PaintStyle(frame=None),
        (HEADING_AREA, "normal"): PaintStyle(font=FontSpec(None, 32), text_color=ACCENT),
    }
    table.update(extra or {})
    return StyleTable(table)


def bound(painter, assets, scale=1.0, quality=RenderQuality.FINAL, canvas=None):
    size = (round(CANVAS_SIZE[0] * scale), round(CANVAS_SIZE[1] * scale))
    framebuffer = pygame.Surface(size)
    framebuffer.fill(BACKGROUND)
    canvas = canvas or Canvas(assets)
    canvas.bind(framebuffer, Viewport.compute(CANVAS_SIZE, size), quality)
    painter.bind(canvas)
    return canvas, framebuffer


def shape_keys(assets):
    return [key for key in assets.cache.keys() if key[0] == SHAPE_KEY]


def px(framebuffer, x, y, scale=1.0):
    return tuple(framebuffer.get_at((round(x * scale), round(y * scale))))[:3]


@pytest.fixture
def assets():
    return make_assets(None)


# --- frame_state ----------------------------------------------------------------------------

def test_frame_state_and_style_table_fallbacks():
    for look, state in [
        (Look(), "normal"), (Look("focused"), "focused"), (Look("pressed"), "pressed"),
        (Look("disabled"), "disabled"), (Look(selected=True), "selected"),
        (Look("focused", selected=True), "focused"), (Look("disabled", selected=True), "disabled"),
    ]:
        assert frame_state(look) == state, look
    # The style table falls back to normal, then the default.
    table = styles()
    assert table.style("button", "focused").frame.fill_color == FOCUS_FILL
    assert table.style("panel", "focused") is table.style("panel", "normal")
    assert table.style("nowhere", "normal") == PaintStyle()


# --- panels and states ----------------------------------------------------------------------

def test_panel_draws_fill_and_border(assets):
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    painter.panel(Box(100, 100, 400, 200))
    assert px(framebuffer, 300, 200) == FILL
    assert px(framebuffer, 300, 100) == BORDER
    assert px(framebuffer, 300, 99) == BACKGROUND
    assert px(framebuffer, 100, 100) == BACKGROUND             # rounded corner


def test_panel_alpha_blends_and_leaves_the_cached_shape_opaque(assets):
    painter = Painter(styles({("panel", "normal"): PaintStyle(frame=FrameSpec((200, 100, 0)))}))
    _, framebuffer = bound(painter, assets)
    painter.panel(Box(0, 0, 50, 50), alpha=0.5)
    r, g, b = px(framebuffer, 25, 25)
    assert abs(r - 100) <= 2 and abs(g - 50) <= 2 and b == 0
    shape = assets.cache.get(shape_keys(assets)[0], 0)
    assert shape.get_alpha() in (None, 255)
    painter.panel(Box(0, 0, 50, 50), alpha=0.0)                # nothing, no error


def test_button_states_markers_pips_and_bars(assets):
    # Focused: focus fill, accent border, and marker.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    box = Box(100, 100, 288, 56)
    painter.widget_frame(box, "button", Look("focused"))
    assert px(framebuffer, 300, 128) == FOCUS_FILL
    for y in (100, 101, 102, 103):
        assert px(framebuffer, 250, y) == ACCENT                # 4-unit border
    assert px(framebuffer, 250, 104) == FOCUS_FILL
    assert px(framebuffer, 114, 128) == ACCENT                  # marker: x 112–124, y 120–136
    assert px(framebuffer, 123, 121) == FOCUS_FILL              # the triangle's empty corner
    # Normal and disabled: no marker.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    painter.widget_frame(Box(100, 100, 288, 56), "button", Look())
    painter.widget_frame(Box(100, 200, 288, 56), "button", Look("disabled"))
    assert px(framebuffer, 114, 128) == FILL
    assert px(framebuffer, 100 + 50, 101) == BORDER
    assert px(framebuffer, 114, 228) == FILL
    assert px(framebuffer, 150, 200) == FILL                    # disabled: no border
    # Pressed: pressed fill and marker.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    painter.widget_frame(Box(100, 100, 288, 56), "button", Look("pressed"))
    assert px(framebuffer, 300, 128) == PRESS_FILL
    assert px(framebuffer, 114, 128) == ACCENT
    # A grid cell may drop the marker.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    painter.widget_frame(Box(100, 100, 96, 80), "button", Look("focused"), marker=False)
    assert px(framebuffer, 114, 140) == FOCUS_FILL
    # On/off pip and the selected bar.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    painter.widget_frame(Box(100, 100, 288, 56), "button", Look(on=True))
    painter.widget_frame(Box(100, 200, 288, 56), "button", Look(on=False))
    painter.widget_frame(Box(100, 300, 288, 56), "button", Look(selected=True))
    assert px(framebuffer, 364, 128) == ACCENT                  # on: filled, center 24 inside
    assert px(framebuffer, 364, 228) == FILL                    # off: ring, hollow center
    assert px(framebuffer, 364, 222) == ACCENT                  # ring edge (radius 6, ring 2)
    assert px(framebuffer, 300, 328) == FOCUS_FILL              # selected fill
    assert px(framebuffer, 250, 300) == BORDER                  # normal border
    assert px(framebuffer, 106, 328) == ACCENT                  # bar: x 104–110, y 312–344
    assert px(framebuffer, 106, 313) == ACCENT
    assert px(framebuffer, 106, 310) == FOCUS_FILL
    assert px(framebuffer, 114, 328) == FOCUS_FILL              # no marker when not focused
    # A style without a frame draws nothing.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    painter.widget_frame(Box(100, 100, 300, 48), "row", Look())
    assert px(framebuffer, 200, 124) == BACKGROUND
    assert painter.builds == 0


# --- shape cache ----------------------------------------------------------------------------

def test_second_draw_builds_nothing(assets):
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    box = Box(100, 100, 288, 56)
    painter.panel(Box(0, 0, 400, 400))
    painter.widget_frame(box, "button", Look("focused", on=True, selected=True))
    built = painter.builds
    keys = shape_keys(assets)
    assert built == 4 == len(keys)                    # panel, frame, triangle, pip
    before = pygame.image.tobytes(framebuffer, "RGB")
    for _ in range(3):
        assets.time.advance(1 / 60)
        _, framebuffer = bound(painter, assets)
        painter.panel(Box(0, 0, 400, 400))
        painter.widget_frame(box, "button", Look("focused", on=True, selected=True))
    assert painter.builds == built
    assert shape_keys(assets) == keys
    assert pygame.image.tobytes(framebuffer, "RGB") == before


def test_keys_follow_area_state_and_device_size_and_build_once_each(assets):
    painter = Painter(styles())
    bound(painter, assets, 1.5)
    painter.widget_frame(Box(100, 100, 288, 56), "button", Look("focused"))
    key = next(k for k in shape_keys(assets) if k[1] == "button")
    assert key[:5] == (SHAPE_KEY, "button", "focused", 432, 84)
    assert assets.cache.cost(key) >= 432 * 84 * 4
    # A new size or state builds once each.
    assets = make_assets(None)
    painter = Painter(styles())
    bound(painter, assets)
    for _ in range(2):
        painter.widget_frame(Box(0, 0, 200, 56), "button", Look())
        painter.widget_frame(Box(0, 0, 220, 56), "button", Look())
        painter.widget_frame(Box(0, 100, 200, 56), "button", Look("disabled"))
    assert painter.builds == 3


def test_fast_quality_and_final_rescale(assets):
    # FAST scales the FINAL shape and caches nothing new.
    painter = Painter(styles())
    canvas, _ = bound(painter, assets, 1.5)
    painter.panel(Box(100, 100, 400, 200))
    keys = shape_keys(assets)
    _, framebuffer = bound(painter, assets, 1.0, RenderQuality.FAST, canvas=canvas)
    painter.panel(Box(100, 100, 400, 200))
    assert painter.builds == 1 and shape_keys(assets) == keys
    assert px(framebuffer, 300, 200) == FILL
    # A rescale at FINAL builds the new size.
    assets = make_assets(None)
    painter = Painter(styles())
    canvas, _ = bound(painter, assets, 1.5)
    painter.panel(Box(100, 100, 400, 200))
    _, framebuffer = bound(painter, assets, 1.0, canvas=canvas)
    painter.panel(Box(100, 100, 400, 200))
    assert painter.builds == 2
    assert px(framebuffer, 100, 300) == BACKGROUND and px(framebuffer, 300, 100) == BORDER


def test_invalidate_primitives_and_unbound(assets):
    # invalidate() discards this painter's shapes.
    painter, other = Painter(styles()), Painter(styles())
    bound(painter, assets)
    painter.panel(Box(0, 0, 100, 100))
    other.bind(painter.canvas)
    other.panel(Box(0, 0, 100, 100))
    assert len(shape_keys(assets)) == 2
    painter.invalidate()
    assert len(shape_keys(assets)) == 1
    painter.panel(Box(0, 0, 100, 100))
    assert painter.builds == 2
    # Primitives are cached.
    assets = make_assets(None)
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    spec = FrameSpec((0x7E, 0x5C, 0x74), 1.0, corner_radius=14)
    for _ in range(2):
        painter.shape(Box(10, 10, 56, 28), spec)
        painter.triangle(Box(100, 10, 12, 16), ACCENT)
        painter.ellipse(Box(200, 10, 20, 20), (255, 255, 255))
        painter.rect(Box(300, 10, 10, 1), BORDER)
    assert painter.builds == 3
    assert px(framebuffer, 38, 24) == (0x7E, 0x5C, 0x74)
    assert px(framebuffer, 210, 20) == (255, 255, 255)
    assert px(framebuffer, 305, 10) == BORDER
    assert px(framebuffer, 305, 11) == BACKGROUND
    # An unbound painter asserts.
    with pytest.raises(AssertionError):
        Painter(styles()).panel(Box(0, 0, 10, 10))


# --- frame images ---------------------------------------------------------------------------

@pytest.fixture
def gui_assets(tmp_path):
    root = copy_game("assets", tmp_path / "assets")
    frame = pygame.Surface((30, 30), pygame.SRCALPHA, 32)
    frame.fill((0, 200, 0, 255))
    frame.fill((0, 0, 200, 255), (10, 10, 10, 10))
    pygame.image.save(frame, str(root / "gui" / "frame9.png"))
    return make_assets(GamePaths.for_game(root))


def test_state_frame_image_replaces_fill_and_border(gui_assets):
    image = gui_assets.image("gui/frame9.png")
    assert not image.is_placeholder
    table = styles({("button", "focused"): button(FOCUS_FILL, 4, ACCENT, image=image)})
    painter = Painter(table)
    _, framebuffer = bound(painter, gui_assets)
    painter.widget_frame(Box(100, 100, 288, 56), "button", Look("focused"), marker=False)
    painter.widget_frame(Box(100, 200, 288, 56), "button", Look())
    assert px(framebuffer, 300, 128) == (0, 0, 200)             # image center
    assert px(framebuffer, 300, 101) == (0, 200, 0)             # image edge
    assert px(framebuffer, 300, 228) == FILL                    # other states keep the fill


def test_missing_frame_image_falls_back_to_the_drawn_look(caplog):
    assets = make_assets(None)
    image = assets.image("gui/missing.png")
    assert image.is_placeholder
    painter = Painter(styles({("panel", "normal"): PaintStyle(
        frame=FrameSpec(FILL, 1.0, BORDER, 2, 16), image=image)}))
    _, framebuffer = bound(painter, assets)
    painter.panel(Box(100, 100, 400, 200))
    assert px(framebuffer, 300, 200) == FILL
    assert px(framebuffer, 300, 100) == BORDER
    painter.shape(Box(600, 100, 100, 100), FrameSpec(FILL), image=image)
    assert px(framebuffer, 650, 150) == FILL


# --- labels and the fit rule ----------------------------------------------------------------

def test_fit_label_steps_down_by_two_then_ellipsis(assets):
    # The fit steps down by two, then cuts with an ellipsis.
    font_at = lambda size: assets.font(None, size).font          # noqa: E731
    assert fit_label("Load", font_at, 28, 224).size == 28
    word = "Preferences"
    w28, w26 = font_at(28).size(word)[0], font_at(26).size(word)[0]
    fit = fit_label(word, font_at, 28, (w28 + w26) / 2)
    assert (fit.text, fit.size, fit.truncated) == (word, 26, False)
    long = fit_label("A very long button label that cannot fit", font_at, 28, 120)
    assert long.size == 24 and long.truncated and long.text.endswith(ELLIPSIS)
    assert font_at(24).size(long.text)[0] <= 120
    small = fit_label("Too wide for this", font_at, 20, 30)
    assert small.size == 20 and small.truncated               # below 24: tried alone


def test_labels_fit_heading_and_text_draw_in_their_style(assets, monkeypatch):
    # A label is centered in the padded box, in the state color.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    box = Box(100, 100, 288, 56)
    painter.widget_frame(box, "button", Look())
    fit = painter.label("Settings", box, area="button", look=Look())
    assert fit.size == 28 and not fit.truncated
    columns = [x for x in range(100, 388) for y in range(100, 156)
               if px(framebuffer, x, y) == TEXT]
    assert columns and abs((min(columns) + max(columns)) / 2 - 244) <= 2
    left = Painter(styles())
    left.bind(painter.canvas)
    left.label("Settings", Box(100, 300, 288, 56), area="button", look=Look(), align="left")
    xs = [x for x in range(100, 388) for y in range(300, 356) if px(framebuffer, x, y) == TEXT]
    assert xs and 132 <= min(xs) <= 136
    # The fit uses the side padding and the text scale.
    scale = [1.0]
    painter = Painter(styles(), text_scale=lambda: scale[0])
    bound(painter, assets)
    box = Box(0, 0, 288, 56)                                    # 224 wide inside the padding
    assert painter.label("Settings", box, area="button", look=Look()).size == 28
    scale[0] = 1.5
    assert painter.text_scale() == 1.5
    fit = painter.label("Settings", box, area="button", look=Look())
    assert (fit.size, fit.truncated) == (42, False)
    tight = painter.fit("A label far too long for any button at all", "button", 224)
    assert tight.truncated and tight.size == 24
    # A fit is laid out once.
    painter = Painter(styles())
    bound(painter, assets)
    calls = []
    real = assets.font
    monkeypatch.setattr(assets, "font", lambda *a, **k: calls.append(a) or real(*a, **k))
    painter.fit("Settings", "button", 224)
    first = len(calls)
    painter.fit("Settings", "button", 224)
    assert first > 0 and len(calls) == first
    # Heading and text draw in their style.
    painter = Painter(styles())
    _, framebuffer = bound(painter, assets)
    x, y, w, h = painter.heading("Options", (100, 100))
    assert (x, y) == (100, 100) and w > 0 and h > 0
    assert any(px(framebuffer, i, j) == ACCENT for i in range(100, 100 + int(w))
               for j in range(100, 100 + int(h)))
    _, _, w2, _ = painter.text("Off", (400, 100), area="button", anchor="topright")
    assert w2 > 0
