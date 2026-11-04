"""F52 step W1: ``[theme.text_entry]`` and W67 (AC-F52-33, 35)."""

import pytest

from engine.app.ui_contrast import PAIRS, contrast_warnings, pair_ratios
from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.core.schemes import FOLLOWING_TOKENS
from engine.ui.focus import Box
from engine.ui.textfield import TextField
from engine.ui.textgeom import cell_side, field_height
from engine.ui.theme import plain_theme
from engine.ui.widgets import Look
from tests.fakes.ui_shell import TestShell, UiHarness


def load(tmp_path, text: str):
    root = tmp_path / str(len(list(tmp_path.iterdir())))
    root.mkdir()
    (root / "config.toml").write_text(text, encoding="utf-8")
    result = load_config(GamePaths.for_game(root))
    assert result.errors == [] and result.warnings == []
    return result.config


# --- AC-F52-33: field and cell geometry, states and tokens under two schemes --------------------

@pytest.mark.parametrize("preset", ["sakura", "amber"])
def test_ac_f52_33_tokens_states_geometry(tmp_path, preset):
    cfg = load(tmp_path, f'[theme]\npreset = "{preset}"\n').theme
    theme = plain_theme(cfg)
    b = cfg.button
    normal = theme.style("text_entry", "normal")
    assert normal.frame.fill_color == b.fill_color and normal.frame.border_color == b.border_color
    assert normal.frame.fill_opacity == b.fill_opacity
    assert normal.frame.border_width == b.border_width
    assert normal.frame.corner_radius == b.corner_radius
    assert normal.text_color == b.text_color and normal.font.size == b.text_size
    assert normal.color("placeholder") == b.disabled.text_color
    assert normal.color("caret") == b.marker.fill_color
    focused = theme.style("text_entry", "focused")
    assert focused.frame.fill_color == b.focused.fill_color
    assert focused.frame.border_width == b.focused.border_width == 4
    disabled = theme.style("text_entry", "disabled")
    assert disabled.frame.border_width == 0 and disabled.text_color == b.disabled.text_color
    for key in ("fill_color", "border_color", "text_color", "placeholder_color", "caret_color"):
        assert f"text_entry.{key}" in FOLLOWING_TOKENS
    # An author's own value wins over the follow.
    own = load(tmp_path, f'[theme]\npreset = "{preset}"\n[theme.text_entry]\n'
                         'fill_color = "#102030"\ntext_size = 32\n').theme
    style = plain_theme(own).style("text_entry", "normal")
    assert style.frame.fill_color == (0x10, 0x20, 0x30) and style.font.size == 32
    # Geometry: the box max(56, pitch + 16), the cell max(40, pitch + 8).
    assert (field_height(28), field_height(42)) == (56, 75)
    assert (cell_side(28), cell_side(42), cell_side(20)) == (47, 67, 40)
    # States through the painter: focused draws the frame and marker; a disabled cell is bold.
    shell = TestShell(cfg=cfg)
    h = UiHarness(shell)
    h.frame()
    p = shell.painter
    p.bind(h.canvas)
    field = TextField(box=Box(100, 100, 600, 56))
    assert field.plan(p, Look("focused")).frame == "focused"
    assert field.plan(p, Look("focused")).marker
    cell = TextField(cell=True, allowed="AB", text="A", box=Box(100, 200, 47, 47),
                     enabled=lambda: False)
    plan = cell.plan(p, Look("disabled"))
    assert plan.bold and plan.underline is None
    at_rest = TextField(cell=True, allowed="AB", box=Box(100, 200, 47, 47)).plan(p, Look("normal"))
    assert at_rest.frame is None and at_rest.underline == Box(100, 245, 47, 2)
    field.draw(p, Look("focused"))                     # draws without error in either scheme
    cell.draw(p, Look("disabled"))


# --- AC-F52-35: W67 covers the text_entry pairs ---------------------------------------------------

def test_ac_f52_35_w67_text_entry_pairs(tmp_path):
    mine = [pair for pair in PAIRS if pair.fg.startswith("text_entry.")]
    assert [(p.fg, p.minimum) for p in mine] == [("text_entry.text_color", 4.5),
                                                 ("text_entry.placeholder_color", 4.5),
                                                 ("text_entry.caret_color", 3.0)]
    for preset in ("sakura", "pocket", "amber", "synthwave", "vaporwave", "groovy"):
        cfg = load(tmp_path, f'[theme]\npreset = "{preset}"\n').theme
        warned = [t for t in contrast_warnings(plain_theme(cfg)) if "text field" in t
                  or "text cursors" in t]
        assert warned == [], preset
    sakura = pair_ratios(plain_theme().cfg, mine[1])
    assert min(sakura) >= 4.5                              # exactly 4.5:1 passes (≥)
    bad = load(tmp_path, '[theme.text_entry]\nplaceholder_color = "#FFF0F6"\n').theme
    texts = contrast_warnings(plain_theme(bad))
    assert any("text field hints need" in t for t in texts)
