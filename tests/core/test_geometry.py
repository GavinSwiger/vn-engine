"""Viewport math, mouse mapping, and the initial window size.

AC-F01-24 (initial size), 34 (example sizes), 35 (odd pixel), 36 (properties for any
window), 40 (mouse mapping), 47 (integer scaling).
"""

import random

import pytest

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport, initial_window_size

CW, CH = CANVAS_SIZE


def _rect(viewport: Viewport) -> tuple[int, int, int, int]:
    return viewport.x, viewport.y, viewport.w, viewport.h


# --- AC-F01-34, 35: example sizes and the odd pixel ---------------------------------------

EXAMPLES = {
    (1280, 720): (0, 0, 1280, 720),
    (1920, 1080): (0, 0, 1920, 1080),
    (1920, 1200): (0, 60, 1920, 1080),
    (2560, 1080): (320, 0, 1920, 1080),
    (1024, 768): (0, 96, 1024, 576),
    (640, 360): (0, 0, 640, 360),
}


@pytest.mark.parametrize("window, expected", EXAMPLES.items())
def test_viewport_for_example_sizes(window, expected):
    viewport = Viewport.compute(CANVAS_SIZE, window)
    assert _rect(viewport) == expected
    assert (viewport.canvas_w, viewport.canvas_h) == CANVAS_SIZE
    assert (viewport.window_w, viewport.window_h) == window


@pytest.mark.parametrize("window, expected", [
    ((1281, 720), (0, 0, 1280, 720)),
    ((1280, 721), (0, 0, 1280, 720)),
    ((1923, 1080), (1, 0, 1920, 1080)),
])
def test_odd_leftover_pixel_goes_right_or_bottom(window, expected):
    assert _rect(Viewport.compute(CANVAS_SIZE, window)) == expected


def test_bars_for_odd_width():
    viewport = Viewport.compute(CANVAS_SIZE, (1923, 1080))
    assert viewport.bar_rects() == [(0, 0, 1, 1080), (1921, 0, 2, 1080)]


def test_bars_for_tall_and_exact_windows():
    assert Viewport.compute(CANVAS_SIZE, (1920, 1200)).bar_rects() == [
        (0, 0, 1920, 60), (0, 1140, 1920, 60)]
    assert Viewport.compute(CANVAS_SIZE, (1280, 720)).bar_rects() == []


def test_scale_properties():
    viewport = Viewport.compute(CANVAS_SIZE, (2560, 1440))
    assert viewport.scale_x == 2.0 and viewport.scale_y == 2.0


# --- AC-F01-36: properties for any window -------------------------------------------------

def test_viewport_properties_for_10000_random_windows():
    rng = random.Random(20261101)
    for _ in range(10_000):
        W = rng.randint(1, 7680)
        H = rng.randint(1, 4320)
        v = Viewport.compute(CANVAS_SIZE, (W, H))
        assert 1 <= v.w <= W and 1 <= v.h <= H, (W, H)
        assert v.w == W or v.h == H, (W, H)
        if v.w == W:
            assert abs(v.h - v.w * 9 / 16) <= 0.5, (W, H)
        else:
            assert abs(v.w - v.h * 16 / 9) <= 0.5, (W, H)
        assert v.x == (W - v.w) // 2 and v.y == (H - v.h) // 2, (W, H)
        covered = v.w * v.h + sum(r[2] * r[3] for r in v.bar_rects())
        assert covered == W * H, (W, H)       # bars and canvas tile the framebuffer


def test_one_pixel_window():
    assert _rect(Viewport.compute(CANVAS_SIZE, (1, 1))) == (0, 0, 1, 1)


@pytest.mark.parametrize("window", [(0, 720), (1280, 0), (0, 0)])
def test_empty_framebuffer_is_a_precondition_failure(window):
    with pytest.raises(AssertionError):
        Viewport.compute(CANVAS_SIZE, window)


# --- AC-F01-40: mouse mapping --------------------------------------------------------------

@pytest.mark.parametrize("window", EXAMPLES)
def test_first_and_last_canvas_pixels(window):
    v = Viewport.compute(CANVAS_SIZE, window)
    assert v.window_to_canvas(v.x, v.y) == ((0, 0), True)
    assert v.window_to_canvas(v.x + v.w - 1, v.y + v.h - 1) == ((CW - 1, CH - 1), True)


def test_center_and_bar_mapping():
    v = Viewport.compute(CANVAS_SIZE, (1920, 1080))
    assert v.window_to_canvas(960, 540) == ((640, 360), True)

    wide = Viewport.compute(CANVAS_SIZE, (2560, 1080))
    assert wide.window_to_canvas(319, 540) == ((0, 360), False)
    assert wide.window_to_canvas(2240, 540) == ((1279, 360), False)

    tall = Viewport.compute(CANVAS_SIZE, (1920, 1200))
    assert tall.window_to_canvas(960, 59)[1] is False
    assert tall.window_to_canvas(960, 60)[1] is True


def test_fractional_pixels_and_one_pixel_canvas():
    v = Viewport.compute(CANVAS_SIZE, (1920, 1080))
    assert v.window_to_canvas(0.4, 0.4) == ((0, 0), True)
    tiny = Viewport.compute(CANVAS_SIZE, (1, 1))
    assert tiny.window_to_canvas(0, 0) == ((0, 0), True)


# --- AC-F01-47: integer scaling -------------------------------------------------------------

@pytest.mark.parametrize("window, expected", [
    ((1920, 1080), (320, 180, 1280, 720)),
    ((2560, 1440), (0, 0, 2560, 1440)),
    ((2000, 1200), (360, 240, 1280, 720)),
    ((1000, 600), (0, 18, 1000, 563)),
    ((640, 360), (0, 0, 640, 360)),
])
def test_integer_scaling(window, expected):
    assert _rect(Viewport.compute(CANVAS_SIZE, window, integer_scale=True)) == expected


def test_integer_scaling_has_four_bars():
    v = Viewport.compute(CANVAS_SIZE, (1920, 1080), integer_scale=True)
    assert v.bar_rects() == [(0, 0, 1920, 180), (0, 900, 1920, 180),
                             (0, 180, 320, 720), (1600, 180, 320, 720)]


# --- AC-F01-24: initial window size ---------------------------------------------------------

@pytest.mark.parametrize("requested, scale, usable, expected", [
    ((1280, 720), 1.0, (1366, 728), (1164, 655)),
    ((1280, 720), 1.0, (1920, 1040), (1280, 720)),
    ((1280, 720), 1.25, (1366, 728), (1164, 655)),
    ((1280, 720), 1.5, (2560, 1392), (1920, 1080)),
    ((7680, 4320), 1.0, (1920, 1040), (1664, 936)),
    ((800, 600), 1.0, (1920, 1040), (800, 600)),
    ((640, 360), 1.0, (600, 400), (640, 360)),
])
def test_initial_window_size(requested, scale, usable, expected):
    assert initial_window_size(requested, scale, usable) == expected


def test_initial_window_size_height_limited_by_wide_area():
    # A very wide, short usable area: the 16:9 size is limited by the height.
    assert initial_window_size((1280, 720), 1.0, (4000, 500)) == (800, 450)
