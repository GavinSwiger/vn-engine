"""render/frames.py: drawn frames, nine-slice frames, markers, gradient, dim, and fades.

F10 SPEC step 2 (no ACs of its own; AC-F10-15, 16, 19 prove it in step 4). Small synthetic
surfaces and pixel probes under the dummy driver.
"""

import ast
from pathlib import Path

import pygame
import pytest

from engine.render.frames import (
    TOP_CORNERS,
    FrameSpec,
    build_ellipse,
    build_frame,
    build_triangle,
    dim,
    surface_cost,
    to_black,
    vertical_gradient,
)

pytestmark = pytest.mark.display

FILL = (0xFF, 0xF4, 0xF8)
BORDER = (0xA0, 0x28, 0x60)
RED, GREEN, BLUE, YELLOW = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)


def rgba(surface, pos):
    return tuple(surface.get_at(pos))


def near(actual, expected, tol=2):
    return all(abs(a - e) <= tol for a, e in zip(actual, expected))


# --- drawn frame ---------------------------------------------------------------------------

def test_drawn_frame_has_fill_at_its_opacity_and_an_opaque_inside_border():
    spec = FrameSpec(FILL, 0.8, BORDER, border_width=2, corner_radius=12)
    surface = build_frame(spec, (200, 56), 1.0)
    assert surface.get_size() == (200, 56)
    assert surface.get_flags() & pygame.SRCALPHA and surface.get_bitsize() == 32
    assert rgba(surface, (100, 28)) == (*FILL, round(255 * 0.8))
    for pos in [(100, 0), (100, 1), (100, 55), (0, 28), (199, 28)]:
        assert rgba(surface, pos) == (*BORDER, 255), pos
    assert rgba(surface, (100, 2)) == (*FILL, 204)
    assert rgba(surface, (0, 0))[3] == 0                      # rounded corner
    assert rgba(surface, (199, 55))[3] == 0


def test_border_and_radius_are_whole_device_pixels_at_scale():
    spec = FrameSpec(FILL, 1.0, BORDER, border_width=2, corner_radius=12)
    surface = build_frame(spec, (300, 84), 1.5)               # border 3 px, radius 18 px
    for y in (0, 1, 2):
        assert rgba(surface, (150, y)) == (*BORDER, 255)
        assert rgba(surface, (150, 83 - y)) == (*BORDER, 255)
    assert rgba(surface, (150, 3)) == (*FILL, 255)
    assert rgba(surface, (3, 3))[3] == 0                      # inside the 18 px rounding
    assert rgba(surface, (18, 42)) == (*FILL, 255)


def test_no_border_fills_to_the_edge_and_no_dark_fringe_on_the_smoothed_corner():
    spec = FrameSpec(FILL, 1.0, corner_radius=8)
    surface = build_frame(spec, (40, 40), 1.0)
    assert rgba(surface, (20, 0)) == (*FILL, 255)
    for x in range(8):                                         # every edge pixel keeps FILL's RGB
        r, g, b, a = rgba(surface, (x, x // 2))
        if a:
            assert (r, g, b) == FILL


def test_top_corners_only_for_the_name_tab():
    spec = FrameSpec(FILL, 1.0, BORDER, border_width=2, corner_radius=12, corners=TOP_CORNERS)
    surface = build_frame(spec, (120, 44), 1.0)
    assert rgba(surface, (0, 0))[3] == 0
    assert rgba(surface, (119, 0))[3] == 0
    assert rgba(surface, (0, 43)) == (*BORDER, 255)
    assert rgba(surface, (119, 43)) == (*BORDER, 255)


def test_zero_opacity_keeps_the_border_and_clears_the_fill():
    surface = build_frame(FrameSpec(FILL, 0.0, BORDER, border_width=2), (20, 20), 1.0)
    assert rgba(surface, (10, 10))[3] == 0
    assert rgba(surface, (10, 0)) == (*BORDER, 255)


@pytest.mark.parametrize("size", [(1, 1), (3, 2), (5, 40), (0, -4)])
def test_tiny_sizes_and_huge_radius_or_border_clamp(size):
    spec = FrameSpec(FILL, 1.0, BORDER, border_width=8, corner_radius=48)
    surface = build_frame(spec, size, 2.0)
    assert surface.get_size() == (max(1, size[0]), max(1, size[1]))


def test_drawn_frame_blends_over_the_screen():
    background = pygame.Surface((20, 20))
    background.fill((0, 0, 0))
    background.blit(build_frame(FrameSpec((200, 100, 0), 0.5), (20, 20), 1.0), (0, 0))
    assert near(rgba(background, (10, 10))[:3], (100, 50, 0))


# --- nine-slice ----------------------------------------------------------------------------

def nine_slice_source(*, alpha: bool = True) -> pygame.Surface:
    """30×30: 10 px red corners, green edges, blue center, one yellow pixel at the top-left
    corner's inner corner (9, 9)."""
    surface = pygame.Surface((30, 30), pygame.SRCALPHA if alpha else 0, 32)
    surface.fill(GREEN)
    surface.fill(BLUE, (10, 10, 10, 10))
    for x, y in [(0, 0), (20, 0), (0, 20), (20, 20)]:
        surface.fill(RED, (x, y, 10, 10))
    surface.set_at((9, 9), YELLOW)
    return surface


def test_nine_slice_corners_unscaled_edges_and_center_stretched():
    spec = FrameSpec(FILL, 1.0, slice_width=10)
    surface = build_frame(spec, (100, 60), 1.0, nine_slice_source())
    assert rgba(surface, (0, 0)) == (*RED, 255)
    assert rgba(surface, (9, 9)) == (*YELLOW, 255)            # corner copied pixel for pixel
    assert rgba(surface, (99, 59)) == (*RED, 255)
    assert rgba(surface, (90, 0)) == (*RED, 255)
    assert rgba(surface, (89, 0)) == (*GREEN, 255)            # top edge stretched to 80 px
    assert rgba(surface, (10, 0)) == (*GREEN, 255)
    assert rgba(surface, (0, 30)) == (*GREEN, 255)            # left edge
    assert rgba(surface, (50, 30)) == (*BLUE, 255)            # center
    assert rgba(surface, (10, 10)) == (*BLUE, 255)


def test_nine_slice_corners_scale_with_the_canvas_only():
    spec = FrameSpec(FILL, 1.0, slice_width=10)
    surface = build_frame(spec, (150, 90), 1.5, nine_slice_source())   # corners 15 px
    assert rgba(surface, (5, 5)) == (*RED, 255)
    assert rgba(surface, (16, 16)) == (*BLUE, 255)
    assert rgba(surface, (144, 84)) == (*RED, 255)
    assert rgba(surface, (75, 2)) == (*GREEN, 255)


def test_nine_slice_is_multiplied_by_fill_opacity():
    spec = FrameSpec(FILL, 0.5, slice_width=10)
    surface = build_frame(spec, (60, 60), 1.0, nine_slice_source())
    r, g, b, a = rgba(surface, (30, 30))
    assert (r, g, b) == BLUE and abs(a - 128) <= 1


def test_nine_slice_accepts_an_image_without_alpha():
    surface = build_frame(FrameSpec(FILL, 1.0, slice_width=10), (60, 40), 1.0,
                          nine_slice_source(alpha=False))
    assert surface.get_flags() & pygame.SRCALPHA
    assert rgba(surface, (0, 0)) == (*RED, 255)
    assert rgba(surface, (30, 20)) == (*BLUE, 255)


def test_nine_slice_smaller_than_two_corners_shrinks_them():
    surface = build_frame(FrameSpec(FILL, 1.0, slice_width=10), (12, 8), 1.0,
                          nine_slice_source())
    assert surface.get_size() == (12, 8)
    assert near(rgba(surface, (0, 0)), (*RED, 255))           # 4 px corners, smoothed
    assert near(rgba(surface, (11, 7)), (*RED, 255))


def test_nine_slice_width_zero_stretches_the_whole_image():
    source = pygame.Surface((4, 4), pygame.SRCALPHA, 32)
    source.fill((10, 20, 30, 255))
    surface = build_frame(FrameSpec(FILL, 1.0, slice_width=0), (40, 20), 1.0, source)
    assert rgba(surface, (0, 0)) == (10, 20, 30, 255)
    assert rgba(surface, (39, 19)) == (10, 20, 30, 255)


def test_nine_slice_leaves_the_source_unchanged():
    source = nine_slice_source()
    before = pygame.image.tobytes(source, "RGBA")
    build_frame(FrameSpec(FILL, 0.3, slice_width=10), (90, 70), 2.0, source)
    assert pygame.image.tobytes(source, "RGBA") == before


# --- markers -------------------------------------------------------------------------------

def test_triangle_points_right_by_default():
    surface = build_triangle((12, 16), BORDER)
    assert surface.get_size() == (12, 16)
    assert rgba(surface, (1, 8)) == (*BORDER, 255)            # wide base on the left
    assert rgba(surface, (11, 0))[3] == 0                     # top-right empty
    assert rgba(surface, (11, 15))[3] == 0
    r, g, b, _ = rgba(surface, (6, 3))
    assert (r, g, b) == BORDER                                # no dark fringe on the edge


@pytest.mark.parametrize("direction, solid, empty", [
    ("left", (10, 8), (0, 0)), ("down", (8, 1), (0, 15)), ("up", (8, 14), (0, 0))])
def test_triangle_directions(direction, solid, empty):
    surface = build_triangle((16, 16), RED, direction=direction)
    assert rgba(surface, solid) == (*RED, 255)
    assert rgba(surface, empty)[3] == 0


def test_ellipse_filled_and_ring():
    filled = build_ellipse((12, 12), BORDER)
    assert rgba(filled, (6, 6)) == (*BORDER, 255)
    assert rgba(filled, (0, 0))[3] == 0
    ring = build_ellipse((24, 24), BORDER, ring_px=4)
    assert rgba(ring, (12, 12))[3] == 0
    assert rgba(ring, (12, 1)) == (*BORDER, 255)
    assert rgba(build_ellipse((6, 6), RED, ring_px=10), (3, 3)) == (*RED, 255)   # too thick


# --- gradient ------------------------------------------------------------------------------

def test_vertical_gradient_runs_top_to_bottom_and_is_opaque():
    surface = vertical_gradient((7, 101), (0, 0, 0), (200, 100, 50))
    assert surface.get_size() == (7, 101)
    assert not surface.get_flags() & pygame.SRCALPHA
    assert rgba(surface, (0, 0))[:3] == (0, 0, 0)
    assert rgba(surface, (6, 100))[:3] == (200, 100, 50)
    assert rgba(surface, (3, 50))[:3] == (100, 50, 25)
    assert all(rgba(surface, (x, 25)) == rgba(surface, (0, 25)) for x in range(7))
    assert vertical_gradient((3, 1), (9, 9, 9), (1, 1, 1)).get_at((0, 0))[:3] == (9, 9, 9)


# --- dim and to_black ----------------------------------------------------------------------

def screen(color=(200, 100, 0), size=(10, 10)):
    surface = pygame.Surface(size)
    surface.fill(color)
    return surface


def test_dim_blends_the_color_at_opacity():
    surface = screen()
    dim(surface, (0x2A, 0x1E, 0x26), 0.55)
    expected = tuple(round(c * 0.45 + d * 0.55) for c, d in zip((200, 100, 0),
                                                                 (0x2A, 0x1E, 0x26)))
    assert near(rgba(surface, (5, 5))[:3], expected)


@pytest.mark.parametrize("opacity, expected", [(0.0, (200, 100, 0)), (-1, (200, 100, 0)),
                                               (1.0, (1, 2, 3)), (5.0, (1, 2, 3))])
def test_dim_ends(opacity, expected):
    surface = screen()
    dim(surface, (1, 2, 3), opacity)
    assert rgba(surface, (0, 0))[:3] == expected


def test_dim_and_to_black_respect_rect_and_work_on_a_subsurface():
    framebuffer = screen(size=(20, 10))
    view = framebuffer.subsurface((10, 0, 10, 10))
    dim(view, (0, 0, 0), 1.0, (0, 0, 5, 10))
    assert rgba(framebuffer, (9, 5))[:3] == (200, 100, 0)
    assert rgba(framebuffer, (10, 5))[:3] == (0, 0, 0)
    assert rgba(framebuffer, (15, 5))[:3] == (200, 100, 0)
    to_black(view, 1.0)
    assert rgba(framebuffer, (19, 5))[:3] == (0, 0, 0)
    assert rgba(framebuffer, (9, 5))[:3] == (200, 100, 0)


@pytest.mark.parametrize("t, expected", [(0.0, (200, 100, 0)), (1.0, (0, 0, 0)),
                                         (0.5, (100, 50, 0)), (2.0, (0, 0, 0))])
def test_to_black(t, expected):
    surface = screen()
    to_black(surface, t)
    assert near(rgba(surface, (0, 0))[:3], expected)


def test_dim_keeps_alpha():
    surface = pygame.Surface((4, 4), pygame.SRCALPHA, 32)
    surface.fill((200, 100, 0, 77))
    dim(surface, (0, 0, 0), 1.0)
    to_black(surface, 0.5)
    assert rgba(surface, (0, 0)) == (0, 0, 0, 77)


def test_surface_cost():
    assert surface_cost(pygame.Surface((10, 3), pygame.SRCALPHA, 32)) == 120


# --- imports -------------------------------------------------------------------------------

def test_frames_imports_only_core_and_pygame():
    path = Path(__file__).resolve().parents[2] / "engine" / "render" / "frames.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    engine = {name for name in names if name.startswith("engine")}
    assert all(name.startswith("engine.core") for name in engine), engine


def test_nine_slice_wider_than_half_the_image_keeps_a_center():
    source = nine_slice_source()                              # 30 px, center blue 10–20
    surface = build_frame(FrameSpec(FILL, 1.0, slice_width=24), (100, 100), 1.0, source)
    assert rgba(surface, (50, 50)) == (*BLUE, 255)            # corner capped at 14 px
    assert rgba(surface, (0, 0)) == (*RED, 255)
    assert rgba(surface, (13, 13))[:3] in (YELLOW, BLUE)
