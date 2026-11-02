"""Layout and fit rules (F10 ``04`` §7.7.3, §7.8, §7.9; ``03`` worked numbers) with M20
metrics (``06`` §0.3): the layout rows of AC-F10-18, ahead of the screens that use them
(step 4). Pure functions, no display. AC-F10-19's fit rows (labels, the confirm message, and
the content rows of ``tests/fixtures/F10/content.toml``) are at the end.

Related rows share one test (loops, not ``parametrize``): every ``tests/ui`` test pays for
``pygame.init()``/``quit()`` (test-review-F10.md)."""

import tomllib
from pathlib import Path


from engine.core.graphemes import graphemes
from engine.ui.focus import Box
from engine.ui.layouts import (
    button_height,
    confirm_layout,
    cut_to_width,
    fit_message,
    list_row_height,
    pitch,
    quick_menu_layout,
    sidebar_layout,
    slider_row_height,
    title_layout,
    toggle_row_height,
    wrap_text,
)
from engine.ui.paint import fit_label
from tests.fakes.fixed_font import FixedFont


def m20(text: str, size: int) -> float:
    return FixedFont(size).size(text)[0]


def test_pitch_button_and_row_heights():
    for size, expected in ((20, 28), (24, 34), (28, 39), (42, 59)):
        assert pitch(size) == expected, size
    for scale, h_b in ((1.0, 56), (1.5, 75)):
        assert button_height(scale=scale) == h_b, scale
    assert (slider_row_height(), toggle_row_height(), list_row_height()) == (91, 56, 48)
    assert list_row_height(scale=1.5) == 67


# --- Title ---------------------------------------------------------------------------------

def test_title_layouts():
    layout = title_layout(2)
    assert layout.button_height == 56
    assert layout.buttons == (Box(80, 288, 320, 56), Box(80, 356, 320, 56))
    assert layout.logo == Box(80, 48, 560, 200)
    assert layout.step == 0
    # 6 entries fit as designed.
    layout = title_layout(6)
    assert layout.gap == 12 and layout.step == 0
    assert layout.buttons[-1].bottom == 684
    # 6 entries at 150% anchor bottom-left.
    layout = title_layout(6, scale=1.5)
    assert (layout.button_height, layout.gap, layout.step) == (75, 4, 2)
    assert layout.buttons[0].y == 218 and layout.buttons[-1].bottom == 688
    assert all(b.x == 80 for b in layout.buttons)
    assert (layout.logo.y, layout.logo.bottom, layout.logo.h) == (48, 194, 146)
    # 7 entries at 1.0: 7 × 56 + 6 × 12 = 464 > 400; with gaps 4: 416 > 400 → step 2.
    # 6 entries at 1.0 with H_b 60 (author height): 360 + 60 = 420 > 400; 360 + 20 = 380 fits.
    layout = title_layout(6, height=60)
    assert (layout.step, layout.gap, layout.buttons[0].y) == (1, 4, 288)
    assert layout.logo == Box(80, 48, 560, 200)
    # The logo is never below 80.
    layout = title_layout(10, scale=1.5)
    assert layout.logo.h == 80
    assert layout.buttons[-1].bottom == 688
    assert title_layout(0).buttons == ()


# --- Sidebar ---------------------------------------------------------------------------------

def test_sidebar_layouts():
    layout = sidebar_layout(3)
    assert [(b.x, b.right) for b in layout.buttons] == [(48, 336)] * 3
    assert [(b.y, b.bottom) for b in layout.buttons] == [(264, 320), (332, 388), (400, 456)]
    assert layout.panel == Box(24, 24, 336, 672)
    assert layout.content == Box(384, 24, 872, 672)
    assert layout.heading == (416, 56) and layout.body == Box(416, 112, 808, 552)
    # 8 entries at 150%.
    layout = sidebar_layout(8, scale=1.5)
    assert layout.gap == 4
    assert layout.buttons[0].y == 46 and layout.buttons[-1].bottom == 674
    assert layout.buttons[-1].bottom - layout.buttons[0].y == 628


# --- Confirm ---------------------------------------------------------------------------------

def test_confirm_layouts():
    for n in (1, 2, 3, 6):
        layout = confirm_layout(n)
        assert layout.panel.h == 40 + 39 * n + 32 + 56 + 40, n
        assert layout.panel.center == (640, 360), n
        assert layout.yes.y == layout.message.bottom + 32, n
        assert (layout.yes.x, layout.yes.right) == (424, 624), n
        assert (layout.no.x, layout.no.right) == (656, 856), n
    # Two lines match the probes.
    layout = confirm_layout(2)
    assert layout.panel == Box(320, 237, 640, 246)
    assert layout.yes == Box(424, 387, 200, 56)
    assert layout.no == Box(656, 387, 200, 56)
    assert layout.message == Box(368, 277, 544, 78)
    # The buttons grow with their labels, up to 280.
    layout = confirm_layout(2, yes_label_width=m20("Yes, return now", 28),   # 300 + 64
                            no_label_width=m20("Not yet", 28))               # 140 + 64
    assert (layout.yes.w, layout.no.w) == (280, 204)
    assert layout.yes.right + 32 == layout.no.x
    assert (layout.yes.x + layout.no.right) / 2 == 640
    # The message size sets the pitch.
    layout = confirm_layout(6, message_size=24)
    assert layout.message_pitch == 34 and layout.message.h == 6 * 34


# --- Quick menu (I-4) ------------------------------------------------------------------------

def test_quick_menu_layouts():
    layout = quick_menu_layout(["Hide", "Menu"], m20)
    assert layout.text_size == 20
    assert layout.pill == Box(556, 690, 168, 28)
    first, second = layout.items
    assert first.box == Box(556, 690, 84, 28) and second.box == Box(640, 690, 84, 28)
    assert first.label_box == Box(572, 694, 56, 20)
    assert layout.pill_top() == 690
    # At 150% it stays in the strip.
    layout = quick_menu_layout(["Hide", "Menu"], m20, scale=1.5)
    assert layout.text_size == 24
    assert (layout.pill.h, layout.pill.y, layout.pill.bottom) == (32, 688, 720)
    # The items tile the pill.
    layout = quick_menu_layout(["Back", "History", "Skip", "Auto", "Hide", "Menu"], m20)
    boxes = [item.box for item in layout.items]
    assert boxes[0].x == layout.pill.x and boxes[-1].right == layout.pill.right
    assert all(a.right == b.x for a, b in zip(boxes, boxes[1:]))
    # Ten long labels are cut.
    labels = [chr(ord("a") + i) * 30 for i in range(10)]
    layout = quick_menu_layout(labels, m20)
    assert layout.side_padding == 4
    assert layout.pill.w <= 1240
    for item in layout.items:
        assert item.label.endswith("…")
        assert m20(item.label, 20) <= 1232 / 10 - 8
    # The padding shrinks before cutting.
    labels = ["x" * 8] * 10            # 112 each: 10 × 136 + 8 = 1368 > 1240; × 120 + 8 fits
    layout = quick_menu_layout(labels, m20)
    assert layout.side_padding == 4
    assert [item.label for item in layout.items] == labels
    layout = quick_menu_layout([], m20)
    assert layout.items == () and layout.pill.w == 8


# --- Cutting ---------------------------------------------------------------------------------

def test_cut_to_width():
    text = "é" * 30                       # 30 graphemes, 60 code points
    cut = cut_to_width(text, 100, 20, m20)
    assert cut.endswith("…")
    body = cut[:-1]
    assert graphemes(body) == ["é"] * (len(graphemes(cut)) - 1)
    assert m20(cut, 20) <= 100
    assert cut_to_width("Hide", 56, 20, m20) == "Hide"
    assert cut_to_width("Hidden", 56, 20, m20) == "Hid…"


# --- AC-F10-19: label fit and content (M20) ---------------------------------------------------

CONTENT = Path(__file__).resolve().parents[1] / "fixtures" / "F10" / "content.toml"


def m20_font(size: int) -> FixedFont:
    return FixedFont(size)


def test_title_and_sidebar_label_fit():
    for n, size, shown in ((12, 28, 12), (13, 26, 13), (14, 24, 14), (15, 24, 15),
                           (16, 24, 14)):
        fit = fit_label("x" * n, m20_font, 28, 320 - 64)
        assert fit.size == size, n
        assert fit.text == "x" * shown + ("…" if shown < n else ""), n
        assert fit.truncated is (shown < n), n
    fit = fit_label("Return to the main title screen", m20_font, 28, 288 - 64)
    assert (fit.text, fit.size) == ("Return to th…", 24)


def test_confirm_message_fit_and_wrap():
    for n, size, cut in ((160, 28, False), (165, 26, False), (170, 24, False), (200, 24, True)):
        fit = fit_message("a" * n, 544, 28, m20)
        assert (fit.size, fit.truncated) == (size, cut), n
        assert len(fit.lines) == 6, n
        assert fit.lines[-1].endswith("…") is cut, n
        assert all(m20(line, fit.size) <= 544 for line in fit.lines), n
    # Wrapping keeps words and breaks long ones.
    assert wrap_text("one two three", 100, 28, m20) == ["one", "two", "three"]
    assert wrap_text("a" * 12, 100, 28, m20) == ["aaaaa", "aaaaa", "aa"]
    assert wrap_text("one\ntwo", 1000, 28, m20) == ["one", "two"]


def content_rows():
    rows = tomllib.loads(CONTENT.read_text(encoding="utf-8"))["row"]
    return [(row["name"], row["text"] * row.get("repeat", 1)) for row in rows]


def assert_prefix(text: str, shown: str) -> None:
    """``shown`` is ``text`` or a whole-grapheme prefix of it followed by "…"."""
    if shown == text:
        return
    assert shown.endswith("…")
    body = graphemes(shown[:-1])
    assert body == graphemes(text)[:len(body)]


def test_content_rows_fit_every_label():
    for name, text in content_rows():
        for scale in (1.0, 1.5):
            row = (name, scale)
            size = round(28 * scale)
            for width in (320 - 64, 288 - 64, 280 - 64):      # title, sidebar, confirm button
                fit = fit_label(text, m20_font, size, width, min_size=min(24, size))
                assert m20(fit.text, fit.size) <= width, row
                assert_prefix(text, fit.text)
            message = fit_message(text, 544, size, m20)
            assert all(m20(line, message.size) <= 544 for line in message.lines), row
            assert len(message.lines) <= 6, row
            for line in message.lines:
                assert "".join(graphemes(line)) == line, row
            layout = quick_menu_layout([text, "Menu"] * 5, m20, scale=scale)
            assert layout.pill.w <= 1240 and 0 <= layout.pill.x, row
            for item in layout.items:
                assert item.label_box.x >= item.box.x - 0.01, row
                if item.label != "Menu":
                    assert_prefix(text, item.label)


def test_title_text_fit_steps_by_four_then_cuts():
    """The title text rule (64, 560 wide, 2 lines, steps of 4 down to 40) through the same
    ``fit_message``; ``TitleScreen`` (step 6) uses it."""
    fit = fit_message("t" * 120, 560, 64, m20, max_lines=2, min_size=40, step=4)
    assert (fit.size, fit.truncated, len(fit.lines)) == (40, True, 2)
    assert fit.lines[-1].endswith("…")
    assert fit_message("t" * 24, 560, 64, m20, max_lines=2, min_size=40, step=4).size == 64
