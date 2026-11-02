"""F23 s5a: the shared column fit (F23 ``07`` §2.1 C3, I-3; ``03`` "Sidebar fit") used by
``title_layout`` and ``sidebar_layout``. AC-F23-41 and AC-F10-18's new sidebar and title rows,
with ``07`` §2.1's numbers. Pure functions; one test per table (loops, not ``parametrize``)."""

from engine.ui.layouts import FitStep, fit_column, sidebar_layout, title_layout


def span(layout) -> tuple[float, float]:
    return layout.buttons[0].y, layout.buttons[-1].bottom


def test_ac41_sidebar_fit_rows():
    # n, scale → step, button height, gap, label size, column height
    rows = {
        (3, 1.0): (FitStep.DESIGNED, 56, 12, 28, 192),
        (9, 1.0): (FitStep.DESIGNED, 56, 12, 28, 600),        # unchanged from F10
        (8, 1.5): (FitStep.GAPS, 75, 4, 42, 628),             # AC-F10-18 unchanged
        (9, 1.5): (FitStep.HEIGHT, 67, 4, 42, 635),           # step 2, label size unchanged
        (10, 1.5): (FitStep.LABEL, 58, 4, 36, 616),           # step 3
        (11, 1.5): (FitStep.LABEL, 53, 4, 32, 623),
    }
    for (n, scale), (step, h, gap, size, total) in rows.items():
        layout = sidebar_layout(n, scale=scale)
        top, bottom = span(layout)
        got = (layout.step, layout.button_height, layout.gap, layout.text_size, bottom - top)
        assert got == (step, h, gap, size, total), (n, scale, got)
        assert top + bottom == 720, (n, scale)                 # centred in the sidebar
        assert 40 <= top and bottom <= 680, (n, scale)          # inside the 640 room


def test_title_fit_rows():
    # n, scale → step, button height, label size, column y, logo height
    rows = {
        (6, 1.0): (FitStep.DESIGNED, 56, 28, (288, 684), 200),
        (6, 1.5): (FitStep.ANCHOR, 75, 42, (218, 688), 146),   # AC-F10-18 unchanged
        (7, 1.5): (FitStep.HEIGHT, 67, 42, (195, 688), 123),
        (8, 1.5): (FitStep.LABEL, 61, 38, (172, 688), 100),
    }
    for (n, scale), (step, h, size, ys, logo_h) in rows.items():
        layout = title_layout(n, scale=scale)
        got = (layout.step, layout.button_height, layout.text_size, span(layout), layout.logo.h)
        assert got == (step, h, size, ys, logo_h), (n, scale, got)
        assert layout.logo.bottom + 24 <= layout.buttons[0].y or step == FitStep.DESIGNED
        assert all(b.x == 80 for b in layout.buttons)


def test_registered_ids_fit_at_every_text_size_and_the_last_step_stops_at_24():
    scales = [1.0 + i / 20 for i in range(11)]                 # 1.0 … 1.5
    for scale in scales:
        for n in range(1, 12):
            layout = sidebar_layout(n, scale=scale)
            top, bottom = span(layout)
            assert bottom - top <= 640 and layout.text_size >= 24, (n, scale)
        for n in range(1, 9):
            layout = title_layout(n, scale=scale)
            assert layout.buttons[-1].bottom <= 688 and layout.logo.h >= 80, (n, scale)
            assert layout.logo.bottom + 24 <= layout.buttons[0].y or layout.step < 2
    # Nothing fits: the label stops at 24 (H 48) and the column overflows.
    over = sidebar_layout(20, scale=1.5)
    assert (over.step, over.text_size, over.button_height, over.gap) == (FitStep.LABEL, 24, 48, 4)
    # A label at or below 24 has no step 3; step 2 never makes buttons taller (H_b 44 < 48).
    fit = fit_column(30, 640, text_size=20, height=40, gap=2)
    assert (fit.step, fit.text_size, fit.button_height, fit.gap) == (FitStep.HEIGHT, 20, 44, 2)
