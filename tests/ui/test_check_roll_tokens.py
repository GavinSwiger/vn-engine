"""F59's roll card colors (``ui/builtin/check_roll.roll_colors``): the choice tokens, so every
color scheme styles it, and its two text pairs meet W67's minimums in every scheme: the
text on the card's fill (4.5:1) and the marker (dice, border, "Success") on it (3:1 for
the dice; the 4.47:1 F59 gives the badge, rounded as W67 floors it)."""

from engine.app.text_check import BLACK, WHITE, composite, contrast_ratio
from engine.core.config_schema import ChoiceTheme
from engine.core.schemes import SCHEMES, scheme_colors
from engine.ui.builtin.check_roll import CARD_OPACITY_MIN, roll_colors


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def test_the_card_uses_the_choice_tokens():
    theme = ChoiceTheme()
    colors = roll_colors(theme)
    assert (colors.fill, colors.border, colors.text) == (
        theme.fill_color, theme.marker.fill_color, theme.text_color)
    assert colors.opacity == max(theme.fill_opacity, CARD_OPACITY_MIN)


def test_text_and_marker_read_on_the_card_in_every_scheme():
    worst: dict[str, tuple[float, float]] = {}
    for id_ in SCHEMES:
        c = scheme_colors(id_)
        fill = _rgb(c["choice.fill_color"])
        opacity = max(float(c.get("choice.fill_opacity", 0.9)), CARD_OPACITY_MIN)
        text, marker = _rgb(c["choice.text_color"]), _rgb(c["choice.marker.fill_color"])
        backs = [composite(fill, opacity, under) for under in (BLACK, WHITE)]
        worst[id_] = (min(contrast_ratio(text, b) for b in backs),
                      min(contrast_ratio(marker, fill), *(contrast_ratio(marker, b)
                                                          for b in backs)))
    assert len(worst) == len(SCHEMES) == 28
    assert all(t >= 4.5 and m >= 3.0 for t, m in worst.values()), worst
