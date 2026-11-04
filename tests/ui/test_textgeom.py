"""F52 step P3: field and keyboard geometry (``ui/textgeom.py``): AC-F52-16, 24."""

import pytest

from engine.ui.focus import Box
from engine.ui.textgeom import caret_at, keyboard_layout, scroll_x


# --- AC-F52-16: a click puts the caret at the nearest boundary ----------------------------------

@pytest.mark.parametrize(("x", "index"), [
    (-50, 0), (0, 0), (4, 0), (5, 0), (6, 1), (10, 1), (17, 2), (24, 2), (25, 2), (26, 3),
    (40, 3), (999, 3),
])
def test_ac_f52_16_click_to_caret(x, index):
    assert caret_at(x, [0, 10, 20, 30]) == index
    assert caret_at(5, []) == 0


def test_scroll_keeps_the_caret_in_view():
    assert scroll_x(50, 50, 100, 0) == 0                 # fits: no shift
    assert scroll_x(250, 250, 100, 0) == 150             # end of a long text
    assert scroll_x(30, 250, 100, 150) == 30             # caret moved left of the view
    assert scroll_x(120, 250, 100, 30) == 30             # still inside: no change
    assert scroll_x(0, 250, 100, 150) == 0


# --- AC-F52-24: the keyboard at 100 % and 150 % ------------------------------------------------

@pytest.mark.parametrize(("scale", "height", "echo", "row", "key"), [
    (1.0, 472, 56, 56, 56),
    (1.5, 504, 59, 75, 58),
])
def test_ac_f52_24_keyboard_geometry(scale, height, echo, row, key):
    lay = keyboard_layout(scale)
    p = lay.panel
    assert (p.w, p.h) == (1040, height)
    assert (p.x + p.w / 2, p.bottom) == (640, 696)            # midbottom never moves
    assert p.y >= 192 and p.x >= 0 and p.right <= 1280        # inside the canvas
    assert (lay.echo.h, lay.page_row.h, lay.key_h) == (echo, row, key)
    assert lay.page_row.w == 1008 and lay.echo.x == p.x + 16
    assert len(lay.keys) == 40
    assert lay.keys[0].w == pytest.approx(93.6) and lay.keys[1].x - lay.keys[0].right == 8
    assert lay.keys[9].right == pytest.approx(p.right - 16)
    assert lay.keys[10].y - lay.keys[0].bottom == 8
    names = [n for n, _ in lay.bottom]
    assert names == ["left", "right", "space", "delete", "done"]
    boxes = dict(lay.bottom)
    unit = lay.keys[0].w
    assert boxes["space"].w == pytest.approx(4 * unit + 3 * 8)
    assert boxes["delete"].w == pytest.approx(2 * unit + 8)
    assert boxes["done"].right == pytest.approx(p.right - 16)
    assert boxes["left"].bottom == pytest.approx(p.bottom - 16)
    assert lay.echo.y == p.y + 16
    assert lay.page_row.y == lay.echo.bottom + 8
    assert lay.keys[0].y == lay.page_row.bottom + 8
    assert isinstance(p, Box)
