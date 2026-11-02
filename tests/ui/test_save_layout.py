"""F11 step 6: ``layouts.save_layout`` and ``layouts.page_row_layout`` (F11 03-ui "Save and
Load pages", Fit table, "Page row contents"; 04 §7.7). AC-F11-39, with M20 metrics (20 units
per character at 28) and, for its last rows, the bundled UI font. Pure functions; the
bundled-font rows open fonts under the dummy driver."""

import pygame
import pytest

from engine.ui.focus import Box
from engine.ui.layouts import PAGE_BODY, page_row_layout, save_layout
from engine.ui.theme import measure_with, plain_theme
from tests.fakes.fixed_font import FixedFont
from tests.render.conftest import make_assets


def m20(text: str, size: int) -> float:
    return FixedFont(size).size(text)[0]


def load_labels(pages: int) -> list[str]:
    return ["Auto", "Quick", *(str(n) for n in range(1, pages + 1))]


def save_labels(pages: int) -> list[str]:
    return [str(n) for n in range(1, pages + 1)]


# --- AC-F11-39: the Fit table ----------------------------------------------------------------

@pytest.mark.parametrize("scale, pitch, h_b, g, t, box, c, row2", [
    (1.0, 34, 56, 16, 135, (240, 135), 225, 353),
    (1.25, 42, 65, 16, 121, (215, 121), 227, 355),
    (1.5, 50, 75, 8, 108, (192, 108), 230, 350),
])
def test_ac39_layout_numbers(scale, pitch, h_b, g, t, box, c, row2):
    layout = save_layout(scale)
    assert (layout.pitch, layout.button_height, layout.gap) == (pitch, h_b, g)
    assert layout.thumb_height == t and layout.thumb == box
    assert layout.cell_height == c and layout.row2_y == row2
    assert layout.lines == 2
    assert [cell.box.x for cell in layout.cells] == [416, 692, 968] * 2
    assert [cell.box.y for cell in layout.cells] == [112] * 3 + [row2] * 3
    assert all(cell.box.w == 256 and cell.box.h == c for cell in layout.cells)


@pytest.mark.parametrize("scale, tag", [(1.0, 34), (1.25, 40), (1.5, 46)])
def test_tags_are_text_size_plus_10(scale, tag):
    assert save_layout(scale).tag_height == tag


def test_cell_parts_at_100_percent():
    layout = save_layout()
    cell = layout.cells[0]
    assert cell.picture == Box(424, 120, 240, 135)
    assert cell.date == (424, 261) and cell.description == (424, 295)
    assert cell.placeholder == Box(424, 120, 240, 209)
    assert cell.label_tag == (428, 124) and cell.newest_tag == (428, 251)
    assert cell.delete_center == (644, 140) and cell.delete_hit == Box(624, 120, 40, 40)
    assert layout.tag_max_width == 188 and layout.line_width == 240
    assert layout.grid == Box(416, 112, 808, 466)            # ends at y 578
    assert layout.row_bottom == (820, 664)
    assert layout.text_size == 24


def test_picture_box_is_centered_at_150_percent():
    layout = save_layout(1.5)
    cell = layout.cells[4]
    assert cell.picture == Box(692 + 32, 350 + 8, 192, 108)
    # 03-ui: 4 + 46 + 8 + 46 + 4 = 108 — the label and Newest tags fit the box's height.
    assert 2 * 4 + 2 * layout.tag_height + 8 == cell.picture.h


def test_grid_and_page_row_fit_the_body_at_every_scale():
    for scale in (1.0, 1.25, 1.5):
        layout = save_layout(scale)
        assert layout.grid.bottom + layout.gap + layout.button_height <= PAGE_BODY.bottom


def test_very_large_text_drops_the_description_line():
    layout = save_layout(1.5, text_size=36)                   # pitch 76
    assert layout.gap == 8 and layout.lines == 1
    assert layout.thumb_height == (552 - 75 - 16) // 2 - 22 - 76
    assert layout.cells[0].description is None
    assert layout.cell_height == 8 + layout.thumb_height + 6 + 76 + 8


# --- AC-F11-39: the page row (M20) -------------------------------------------------------------

def test_load_row_with_three_pages_has_no_arrows():
    row = page_row_layout(load_labels(3), 0, m20, fixed=2)
    assert not row.arrows
    assert [b.label for b in row.buttons] == ["Auto", "Quick", "1", "2", "3"]
    widths = [b.box.w for b in row.buttons]
    assert widths == [112, 132, 56, 56, 56]                  # max(H_b, label + 32)
    for left, right in zip(row.buttons, row.buttons[1:]):
        assert right.box.x == left.box.right + 4
    assert row.width == 428
    assert (row.buttons[0].box.x + row.width / 2, row.buttons[0].box.bottom) == (820, 664)
    assert all(b.box.h == 56 for b in row.buttons)


def test_default_ten_pages_save_row_fits():
    row = page_row_layout(save_labels(10), 0, m20)
    assert not row.arrows and len(row.buttons) == 10


def test_arrows_appear_exactly_when_the_row_exceeds_808():
    fits = page_row_layout(["a" * 20, "a" * 17], 0, m20)      # 432 + 4 + 372 = 808
    assert not fits.arrows and fits.width == 808
    over = page_row_layout(["a" * 20, "a" * 18], 0, m20)      # 812
    assert over.arrows
    assert [b.kind for b in over.buttons] == ["prev", "page", "next"]
    assert over.buttons[0].box.w == over.buttons[-1].box.w == 56     # H_b square


def test_window_is_centered_on_the_current_page():
    row = page_row_layout(save_labels(100), 49, m20)          # page "50"
    assert row.arrows
    assert [b.label for b in row.buttons] == ["◀", *(str(n) for n in range(46, 55)), "▶"]
    assert row.width <= 808
    assert row.prev_enabled and row.next_enabled


def test_window_at_the_ends_and_arrows_never_wrap():
    first = page_row_layout(save_labels(100), 0, m20)
    assert first.pages[0] == 0 and not first.prev_enabled and first.next_enabled
    last = page_row_layout(save_labels(100), 99, m20)
    assert last.pages[-1] == 99 and last.prev_enabled and not last.next_enabled
    assert len(last.pages) >= 5


def test_load_window_keeps_auto_and_quick_and_starts_at_page_1_from_them():
    row = page_row_layout(load_labels(100), 1, m20, fixed=2)   # Quick is current
    labels = [b.label for b in row.buttons]
    assert labels[:3] == ["◀", "Auto", "Quick"] and labels[3] == "1" and labels[-1] == "▶"
    later = page_row_layout(load_labels(100), 60, m20, fixed=2)   # page "59"
    labels = [b.label for b in later.buttons]
    assert labels[1:3] == ["Auto", "Quick"] and "59" in labels
    assert later.width <= 808


def test_page_row_at_150_percent_uses_the_scaled_button():
    row = page_row_layout(load_labels(3), 0, m20, fixed=2, scale=1.5)
    assert all(b.box.h == 75 for b in row.buttons)
    assert row.buttons[0].box.bottom == 664
    assert row.buttons[2].box.w == 75                          # max(75, 30 + 32)


# --- AC-F11-39: bundled UI font rows ---------------------------------------------------------

@pytest.fixture
def bundled():
    pygame.init()
    yield measure_with(make_assets(None), plain_theme().font(28))
    pygame.quit()


def test_bundled_font_at_150_percent_shows_auto_quick_arrows_and_4_pages(bundled):
    row = page_row_layout(load_labels(10), 0, bundled, fixed=2, scale=1.5)
    assert [b.label for b in row.buttons] == ["◀", "Auto", "Quick", "1", "2", "3", "4", "▶"]


@pytest.mark.xfail(strict=True, reason=(
    "03-ui's rules give 812 > 808 with Noto Sans (Auto 94, Quick 106, 1–9 56, 10 64, 11 gaps "
    "of 4); 03-ui's '800 wide' estimate is 12 short. Reported to the UI designer."))
def test_bundled_font_at_100_percent_shows_all_12_load_buttons(bundled):
    row = page_row_layout(load_labels(10), 0, bundled, fixed=2)
    assert not row.arrows and len(row.buttons) == 12
