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


# --- AC-F49-04 — W67 names the color scheme both colors come from (F49 SPEC §3.4) -------------

def test_ac_f49_04_w67_names_the_scheme(tmp_path, caplog):
    from engine.app.looks import look_warnings
    from engine.app.ui_contrast import LOOK_PAIRS, SCHEME_SENTENCE, contrast_warnings
    from engine.core.config import load_config
    from engine.core.paths import GamePaths
    from engine.ui.looks import Looks
    from engine.ui.menus import UiOverrides

    def load(text: str):
        root = tmp_path / str(len(list(tmp_path.iterdir())))
        root.mkdir()
        (root / "config.toml").write_text(text, encoding="utf-8")
        result = load_config(GamePaths.for_game(root))
        assert result.errors == [] and result.warnings == []
        return result.config

    synth = SCHEME_SENTENCE.format(name="Synthwave Sunset")
    assert synth == " Both colors come from the Synthwave Sunset color scheme."
    cfg = load('[theme]\npreset = "synthwave"\n')
    texts = contrast_warnings(plain_theme(cfg.theme), pairs=PAIRS + LOOK_PAIRS,
                              scheme=cfg.theme.preset)
    assert texts and all(text.endswith(synth) for text in texts)
    track = ("config.toml: [theme.toggle] track_color #5A4A7A is hard to see on "
             "[theme.panel] fill_color #262335 (1.6:1; tracks need at least 3:1). Pick a "
             "lighter track_color." + synth)
    assert track in texts
    assert track in w67_texts(caplog, plain_theme(cfg.theme), dev=True)   # warn_contrast
    # The author's own panel fill: that pair loses the sentence; scheme-only pairs keep it.
    own = load('[theme]\npreset = "synthwave"\n[theme.panel]\nfill_color = "#262336"\n')
    texts = contrast_warnings(plain_theme(own.theme), scheme=own.theme.preset)
    track_own = [t for t in texts if t.startswith("config.toml: [theme.toggle] track_color")
                 and "[theme.panel] fill_color #262336" in t]
    assert track_own and not any(t.endswith(synth) for t in track_own)
    assert any(t.endswith(synth) for t in texts)
    # A style's scheme warnings name the style's own scheme, not the base one.
    styled = load('[theme]\npreset = "synthwave"\n[style.lcd.theme]\npreset = "pocket"\n')
    looks = Looks(plain_theme(styled.theme), styles=styled.style,
                  playthroughs=styled.playthrough, overrides=UiOverrides(),
                  image=lambda ref: None)
    texts = look_warnings(looks, styled.style, styled.playthrough)
    assert texts and all(t.startswith("config.toml: [style.lcd.theme.") for t in texts)
    pocket = SCHEME_SENTENCE.format(name="Pocket LCD")
    assert sum(t.endswith(pocket) for t in texts) >= 5 and not any(synth in t for t in texts)
    # The base title's version text on Pocket's panel: one color each, so no sentence.
    mixed = [t for t in texts if not t.endswith(pocket)]
    assert mixed == ["config.toml: [style.lcd.theme.title.version] text_color #9A90B4 on "
                     "[style.lcd.theme.panel] fill_color #9BBC0F at fill_opacity 0.9 gives "
                     "1.1:1 over a black picture; version text needs at least 4.5:1. Pick "
                     "colors further apart."]
    # Without a scheme, the texts are F10's (the existing W67 tests above).
    assert not any("color scheme" in t for t in contrast_warnings(
        plain_theme(dataclasses.replace(CFG, button=PALE_BUTTON))))
