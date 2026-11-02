"""F10 ``04`` §7.10 step 5 — ``app/ui_contrast``: AC-F10-17 (the default theme's pairs with
F05's contrast function, over pure black and pure white, ± 0.01; "track on focused fill" is
the fill over black, 07 I-15) and AC-F10-28's W67 rows (dev only; a pair drawn from a
frame image is skipped)."""

import dataclasses
import logging

import pytest

from engine.app.ui_contrast import PAIRS, pair_ratios, warn_contrast
from engine.core.config_schema import ButtonFocusedTheme, ButtonTheme, ThemeConfig
from engine.ui.theme import UiTheme, plain_theme

CFG = ThemeConfig()
BY_COLORS = {(p.fg, p.bg): p for p in PAIRS}


@pytest.mark.parametrize("fg, bg, black, white", [
    ("button.text_color", "button.fill_color", 9.81, 12.32),
    ("button.text_color", "button.focused.fill_color", 8.08, 10.31),
    ("button.text_color", "button.pressed.fill_color", 7.08, 9.13),
    ("button.disabled.text_color", "button.fill_color", 4.52, 5.68),
    ("button.marker.fill_color", "button.focused.fill_color", 4.35, 5.55),
    ("button.marker.fill_color", "button.pressed.fill_color", 3.81, 4.92),
    ("panel.text_color", "panel.fill_color", 10.70, 12.31),
    ("panel.heading.text_color", "panel.fill_color", 5.76, 6.63),
    ("toggle.track_color", "panel.fill_color", 4.66, 5.36),
    ("toggle.track_color", "button.focused.fill_color", 3.52, 4.49),
    ("list.scrollbar_color", "panel.fill_color", 5.76, 6.63),
    ("quick_menu.text_color", "quick_menu.fill_color", 9.81, 12.32),
    ("quick_menu.focused.text_color", "quick_menu.fill_color", 5.28, 6.63),
    ("quick_menu.text_color", "quick_menu.on.fill_color", 8.08, 10.31),
    ("quick_menu.disabled.text_color", "quick_menu.fill_color", 4.52, 5.68),
    ("title.version.text_color", "panel.fill_color", 4.52, 5.68),
    ("title.logo.text_color", "title.fill_top_color", 6.59, 6.59),
    ("title.logo.text_color", "title.fill_bottom_color", 5.40, 5.40),
    ("toggle.on.knob_color", "toggle.on.track_color", 7.08, 7.08),
    ("title.loading.text_color", "", 17.83, 17.83),
])
def test_ac_f10_17_readable_by_default(fg, bg, black, white):
    pair = BY_COLORS[(fg, bg)]
    over_black, over_white = pair_ratios(CFG, pair)
    assert over_black == pytest.approx(black, abs=0.01)
    assert over_white == pytest.approx(white, abs=0.01)
    assert min(over_black, over_white) >= pair.minimum


BUTTON_TEXT = ("config.toml: [theme.button] text_color #F6E8F0 on fill_color #FFE6F0 at "
               "fill_opacity 0.9 gives 1.0:1 over a white picture; button text needs at least "
               "4.5:1. Pick colors further apart.")
FOCUS_OUTLINE = ("config.toml: [theme.button.focused] border_color #FFD6E8 is hard to see on "
                 "fill_color #FFD6E8 (1.0:1; focus outlines need at least 3:1). Pick a darker "
                 "border_color.")
PALE_BUTTON = dataclasses.replace(ButtonTheme(), text_color=(0xF6, 0xE8, 0xF0),
                                  fill_color=(0xFF, 0xE6, 0xF0))
PALE_OUTLINE = dataclasses.replace(ButtonTheme(), focused=dataclasses.replace(
    ButtonFocusedTheme(), border_color=(0xFF, 0xD6, 0xE8)))


def w67_texts(caplog, theme: UiTheme, dev: bool) -> list[str]:
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="vn.ui"):
        warn_contrast(theme, dev=dev)
    return [r.getMessage() for r in caplog.records
            if r.name == "vn.ui" and getattr(r, "code", None) == "W67"]


@pytest.mark.parametrize("button, text", [(PALE_BUTTON, BUTTON_TEXT),
                                          (PALE_OUTLINE, FOCUS_OUTLINE)])
def test_ac_f10_28_w67_texts_dev_only(caplog, button, text):
    theme = plain_theme(dataclasses.replace(CFG, button=button))
    assert w67_texts(caplog, theme, dev=True).count(text) == 1
    assert w67_texts(caplog, theme, dev=False) == []
    assert w67_texts(caplog, plain_theme(), dev=True) == []


def test_w67_skips_a_pair_drawn_from_a_frame_image(caplog):
    framed = UiTheme(dataclasses.replace(CFG, button=PALE_BUTTON), frames={"button": object()})
    texts = w67_texts(caplog, framed, dev=True)
    assert BUTTON_TEXT not in texts
    assert texts                         # the focused and pressed looks are still drawn
