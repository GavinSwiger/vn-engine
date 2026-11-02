"""F07 step 2 — ``ChoiceLayout``, the fit rule (AC-F07-21; ``04`` §7.8; 07 I-4, I-8; F10's
AC-F07-21 amendment: a ``none`` menu's area and the last resort end at F10's floor).

Unit tests with F05's M20 font (``tests/fakes/fixed_font.py``: 20 units per grapheme at 28,
so 36 graphemes per 720-unit line). ``aN`` is a run of N ``a``s. B is 444 as in the AC
(F05's built ``tab_top`` is 462, so the live B is 446; the controller rows check that).
"""

import pytest

from engine.core.config_schema import ChoiceTheme, TextboxTheme
from engine.render.choices import ChoiceArea, ChoiceLayout, half_up
from engine.render.textbox import TextboxView, box_geometry
from engine.render.textlayout import BUNDLED_FACES
from engine.runtime.commands import ShowMenu, ShownChoice
from engine.ui.builtin.choice_screen import ChoiceController
from engine.ui.screen import ScreenStack
from tests.fakes.fixed_font import FixedFontAssets, tagged

TEMPLATE_M = ("The red one", "The paper crane (2 coins)", "Not this year")
ONE = tuple(f"Choice {n}" for n in range(1, 7))
A60 = "a" * 60


def layout(texts, *, bottom=444.0, last=704.0, size=28, theme=None, align="center"):
    return ChoiceLayout([tagged(t) for t in texts], assets=FixedFontAssets(),
                        faces=BUNDLED_FACES, theme=theme or ChoiceTheme(), text_size=size,
                        area=ChoiceArea(16, bottom, last, align),
                        colors=["#3d2b36"] * len(texts))


def line_text(line) -> str:
    return "".join(g.text for g in line.glyphs if not g.hangs)


FIT_ROWS = [
    ("A", TEMPLATE_M, 0, 28, 12, (130, 201, 272), 331, 444),
    ("B", ONE, 0, 28, 12, (23, 94, 165, 236, 307, 378), 437, 444),
    ("C", (A60,) * 4, 0, 28, 12, (16, 126, 236, 346), 444, 444),
    ("D", ONE[:5] + (A60,), 1, 28, 4, (24, 87, 150, 213, 276, 339), 437, 444),
    ("E", (A60,) * 4 + ONE[:2], 2, 20, 4, (20, 100, 180, 260, 340, 392), 440, 444),
    ("F", (A60,) * 6, 3, 20, 4, (122, 202, 282, 362, 442, 522), 598, 444),
    ("G", TEMPLATE_M, 0, 28, 12, (260, 331, 402), 461, 704),
]


def test_ac21_fit_rows():
    """The AC's rows A–G (one test: they share no setup but the font)."""
    for row, texts, step, size, gap, tops, bottom, b in FIT_ROWS:
        out = layout(texts, bottom=b)
        assert (out.step, out.size, out.gap) == (step, size, gap), row
        assert out.tops == tops and out.bottom == bottom, row
        for button in out.buttons:
            x, _y, w, _h = button.rect
            assert (x, x + w) == (240, 1040), row
            for line in button.lines:
                assert abs(line.x + line.width / 2 - 640) <= 1, row     # ink centered on 640
                assert line.glyphs and min(g.size for g in line.glyphs) >= 20, row
    assert layout(TEMPLATE_M).heights == (59, 59, 59)                   # row A


def test_ac21_row_h_two_lines_then_the_cut():
    out = layout(("a" * 100,))
    button = out.buttons[0]
    assert button.rect[3] == 98 and button.cut
    first, second = button.lines
    assert line_text(first) == "a" * 36
    # F05's fit_line of the rest (64 a's) in 720 units at 20 per grapheme: 35 a's and "…".
    assert line_text(second) == "a" * 35 + "…"
    assert second.baseline - first.baseline == 39


def test_ac21_two_lines_are_never_cut_and_a_hard_break_is_a_line():
    out = layout(("a" * 72, "Two\nlines"))               # F02's lexer turns \n into this
    assert [len(b.lines) for b in out.buttons] == [2, 2]
    assert not any(b.cut for b in out.buttons)
    assert [line_text(line) for line in out.buttons[1].lines] == ["Two", "lines"]


def test_ac21_a_cut_keeps_styles_and_drops_hard_breaks():
    out = layout(("{b}" + "a" * 36 + "{/b} b\nc " + "d" * 60,))
    second = out.buttons[0].lines[1]
    text = line_text(second)
    assert text.startswith("b c d") and text.endswith("…") and len(text) == 36
    assert all(not g.face.bundled.name.startswith("BOLD") for g in second.glyphs)


def test_ac21_text_never_below_20_and_size_is_clamped():
    assert layout(TEMPLATE_M, size=19).size == 20
    assert layout(TEMPLATE_M, size=60).size == 48
    out = layout((A60,) * 6, last=300)                         # overflow at step 3
    assert out.step == 3 and out.size == 20 and out.top == 16  # runs off the bottom


def test_i4_narrow_text_width_and_centering_rounds_half_up():
    out = layout(TEMPLATE_M, theme=ChoiceTheme(width=400, side_padding=200))
    assert out.text_width == 100
    assert out.buttons[0].rect[0] == 440 and out.buttons[0].rect[2] == 400
    assert half_up(113.5) == 114 and half_up(112.5) == 113


# --- F17 07 I-2: room for NVL ------------------------------------------------------------------

def test_i2_steps_0_to_2_take_the_area_and_align():
    assert layout(TEMPLATE_M, align="top").tops == (16, 87, 158)
    out = ChoiceLayout([tagged(t) for t in TEMPLATE_M], assets=FixedFontAssets(),
                       faces=BUNDLED_FACES, theme=ChoiceTheme(), text_size=28,
                       area=ChoiceArea(100, 400, 704, "top"), colors=["#3d2b36"] * 3)
    assert out.step == 0 and out.tops == (100, 171, 242)


def test_i2_the_defaults_reproduce_f07():
    assert ChoiceArea() == ChoiceArea(16, 704, 704, "center")       # row G: test_ac21_fit_rows


def test_i2_step_3_keeps_f07s_own_area_centered():
    out = ChoiceLayout([tagged(A60)] * 6, assets=FixedFontAssets(), faces=BUNDLED_FACES,
                       theme=ChoiceTheme(), text_size=28,
                       area=ChoiceArea(300, 400, 704, "top"), colors=["#3d2b36"] * 6)
    assert out.step == 3 and out.tops[0] == 122                     # row F: 16..704, centered


def test_i2_fits_is_pure_and_matches_steps_0_to_2():
    out = layout((A60,) * 6)
    before = (out.step, out.size, out.tops)
    assert not out.fits(16, 444)                     # row F needs step 3
    assert out.fits(16, 704) and out.fits(0, 476) and not out.fits(0, 475)
    assert (out.step, out.size, out.tops) == before
    assert layout(TEMPLATE_M).fits(16, 444)


def test_hit_testing_follows_the_rects():
    out = layout(TEMPLATE_M)
    assert out.hit((640, 160)) == 0 and out.hit((640, 231)) == 1 and out.hit((640, 301)) == 2
    assert out.hit((640, 196)) is None and out.hit((239, 160)) is None
    assert out.hit((1040, 160)) is None and out.hit((1039, 160)) == 0
    assert out.hit((640, 188)) == 0 and out.hit((640, 189)) is None     # 130 + 59


# --- The controller's area (F05's tab_top, F10's floor) ------------------------------------

class _Box:
    """A textbox stand-in: the real ``tab_top`` at ``size``."""

    hidden = False
    has_box = True
    nvl_on = False                                  # ADV (F17's NVL area: test_nvl_choices)

    def __init__(self, size: int = 28) -> None:
        self.size = size
        theme = TextboxTheme()
        self._view = TextboxView(FixedFontAssets(), theme, BUNDLED_FACES.for_style(True, False))
        self._theme = theme

    def text_size(self) -> int:
        return self.size

    def tab_top(self) -> float:
        return self._view.tab_top(box_geometry(self._theme, self.size))


def controller(box) -> ChoiceController:
    return ChoiceController(ScreenStack(), box, theme=ChoiceTheme(), assets=FixedFontAssets(),
                            faces=BUNDLED_FACES, base_text_size=28, post=lambda e: None)


def menu(line: str) -> ShowMenu:
    return ShowMenu("m", tuple(ShownChoice(f"k{i}", tagged(t), False)
                               for i, t in enumerate(TEMPLATE_M)), line)


def test_ac21_live_area_b_is_tab_top_minus_16():
    box = _Box()
    c = controller(box)
    assert box.tab_top() == 462                     # F05 as built (04 drew 460)
    assert c.area("question") == ChoiceArea(16, 446, 704)
    assert c.layout(menu("question")).tops == (131, 202, 273)


def test_ac21_row_i_b_follows_the_text_size():
    box = _Box(36)
    c = controller(box)
    assert c.text_size() == 36
    assert c.area("kept").bottom == box.tab_top() - 16
    out = c.layout(menu("kept"))
    assert out.size == 36 and out.heights == (70, 70, 70)


def test_f10_amendment_none_and_last_resort_end_at_the_floor():
    c = controller(_Box())
    assert c.area("none") == ChoiceArea(16, 704, 704)
    c.set_floor(lambda: 686)
    assert c.area("none") == ChoiceArea(16, 686, 686)
    assert c.area("question") == ChoiceArea(16, 446, 686)


def test_a_text_size_change_gives_a_new_layout_and_none_otherwise():
    box = _Box()
    c = controller(box)
    cmd = menu("question")
    first = c.layout(cmd)
    assert c.layout(cmd) is first
    box.size = 36
    second = c.layout(cmd)
    assert second is not first and second.size == 36
