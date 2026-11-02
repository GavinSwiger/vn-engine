"""F21 step 3 — AC-F21-21: ``layouts.codex_layout`` (pure) for the 808×552 slot at 100, 125,
and 150 %, and the smallest host (640×400).

Rows 3, 5, 6, and 7 use 07 I-9's picture rule (min(``image_height``, inner − a 2-line title −
a 2-line body − the gaps − the pick button); none under 80), which supersedes 06's
"as row 1" numbers for them; a no-picture row is added (the title moves up)."""

import pytest

from engine.ui.builtin.codex_page import CodexView
from engine.ui.focus import Box
from engine.ui.layouts import codex_layout

SLOT = Box(416, 112, 808, 552)


def boxes(layout) -> tuple:
    def t(box):
        return None if box is None else (box.x, box.y, box.w, box.h)
    return (t(layout.tab_row), t(layout.list), t(layout.panel), t(layout.picture),
            t(layout.pick))


def test_ac21_layout_numbers():
    row1 = ((416, 112, 808, 56), (416, 180, 300, 484), (736, 180, 488, 484),
            (756, 200, 448, 200), None)
    rows = [
        (dict(box=SLOT, text_scale=1.0, tabs=3, pick=False), row1),
        (dict(box=SLOT, text_scale=1.0, tabs=1, pick=False),
         (None, (416, 112, 300, 552), (736, 112, 488, 552), (756, 132, 448, 200), None)),
        (dict(box=SLOT, text_scale=1.0, tabs=3, pick=True),                    # I-9: 184
         (*row1[:3], (756, 200, 448, 184), (756, 588, 448, 56))),
        (dict(box=SLOT, text_scale=1.25, tabs=3, pick=False),
         ((416, 112, 808, 65), (416, 189, 300, 475), (736, 189, 488, 475),
          (756, 209, 448, 200), None)),
        (dict(box=SLOT, text_scale=1.5, tabs=3, pick=False),                   # I-9: 149
         ((416, 112, 808, 75), (416, 199, 300, 465), (736, 199, 488, 465),
          (756, 219, 448, 149), None)),
        (dict(box=Box(0, 0, 640, 400), text_scale=1.0, tabs=3, pick=True),     # I-9: none
         ((0, 0, 640, 56), (0, 68, 238, 332), (258, 68, 382, 332), None,
          (278, 324, 342, 56))),
        (dict(box=SLOT, text_scale=1.0, tabs=3, pick=False, image_height=0),
         (*row1[:3], None, None)),
        (dict(box=SLOT, text_scale=1.0, tabs=3, pick=False, image_height=320),  # I-9: 252
         (*row1[:3], (756, 200, 448, 252), None)),
        (dict(box=SLOT, text_scale=1.0, tabs=3, pick=False, picture=False),
         (*row1[:3], None, None)),
    ]
    for kwargs, expected in rows:
        assert boxes(codex_layout(**kwargs)) == expected, kwargs
    # The body fills the rest, 12 between picture, title, body, and pick; 1 or 2 title lines.
    for pick, lines in ((False, 2), (True, 1)):
        layout = codex_layout(SLOT, tabs=3, pick=pick, title_lines=lines)
        pic, title, body = layout.picture, layout.title, layout.body
        assert title.y == pic.bottom + 12 and title.h == lines * 45     # pitch(32) = 45
        assert body.y == title.bottom + 12 and body.x == 756 and body.w == 448
        assert body.bottom == (layout.pick.y - 12 if pick else 644)    # inner bottom 644
    plain = codex_layout(SLOT, tabs=1, pick=False, picture=False, title_lines=1)
    assert plain.title.y == plain.inner.y == 132                       # no picture: moves up
    # Rows are max(list.row_height, pitch + 16); titles fit to lw − 64.
    assert [codex_layout(SLOT, s, tabs=1, pick=False).row_height for s in (1.0, 1.25, 1.5)] \
        == [55, 65, 75]
    assert codex_layout(SLOT, tabs=1, pick=False, list_row_min=120).row_height == 120
    assert codex_layout(SLOT, tabs=1, pick=False).title_width == 236
    # A host under 640×400 is a programming error.
    view = CodexView.__new__(CodexView)
    for box in (Box(0, 0, 639, 400), Box(0, 0, 640, 399)):
        with pytest.raises(AssertionError):
            CodexView.build(view, box, 1.0)
