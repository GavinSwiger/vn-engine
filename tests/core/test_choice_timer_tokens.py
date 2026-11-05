"""F51 step P2, the countdown bar's tokens (``01`` §6.2, ``04`` §3; C1, 07 I-4): AC-F51-22
(the follow rule, author values, F49's following group), 23 (fill on track in every
scheme), 31 (Game settings ▸ Choices shows "Time limit bar")."""

import dataclasses

from engine.app.text_check import contrast_ratio
from engine.core.config_schema import ChoiceTheme, ThemeConfig
from engine.core.schemes import FOLLOWING_TOKENS, SCHEMES, scheme_colors
from engine.render.choicetimer import timer_colors

TOKENS = ("choice.timer.fill_color", "choice.timer.track_color")


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


# --- AC-F51-22 — the tokens follow, and an author's values win -----------------------------------

def test_ac22_tokens_follow_marker_and_focused_fill_and_author_values_win(load):
    theme = ChoiceTheme()
    assert (theme.timer.fill_color, theme.timer.track_color, theme.timer.tick_sound) == (
        None, None, None)
    assert timer_colors(theme) == (theme.marker.fill_color, theme.focused.fill_color)
    assert timer_colors(theme) == ((0xA0, 0x28, 0x60), (0xFF, 0xD6, 0xE8))   # Sakura
    moved = dataclasses.replace(
        theme, marker=dataclasses.replace(theme.marker, fill_color=(1, 2, 3)),
        focused=dataclasses.replace(theme.focused, fill_color=(4, 5, 6)))
    assert timer_colors(moved) == ((1, 2, 3), (4, 5, 6))                    # they follow
    result = load('[theme.choice.timer]\nfill_color = "#123456"\ntrack_color = "#ABCDEF"\n')
    assert result.errors == [] and result.warnings == []
    assert timer_colors(result.config.theme.choice) == ((0x12, 0x34, 0x56), (0xAB, 0xCD, 0xEF))
    assert set(TOKENS) <= set(FOLLOWING_TOKENS)
    amber = load('[theme]\npreset = "amber"\n').config.theme
    assert amber.choice.timer.fill_color is None                           # a scheme leaves them
    assert timer_colors(amber.choice) == (amber.choice.marker.fill_color,
                                          amber.choice.focused.fill_color)
    assert ThemeConfig().choice.timer.track_color is None


# --- AC-F51-23 — fill on track, every scheme -----------------------------------------------------

def test_ac23_fill_on_track_meets_3_to_1_in_every_scheme():
    ratios = {}
    for id_ in SCHEMES:
        colors = scheme_colors(id_)
        ratios[id_] = contrast_ratio(_rgb(colors["choice.marker.fill_color"]),
                                     _rgb(colors["choice.focused.fill_color"]))
    assert len(ratios) == len(SCHEMES)
    assert all(ratio >= 3.0 for ratio in ratios.values()), ratios


# --- AC-F51-31 — Game settings ▸ Choices ---------------------------------------------------------

def test_ac31_choices_page_shows_the_time_limit_bar():
    from engine.tools.editor import settingsmodel as sm

    page = sm.page("choices")
    sections = {section.path: section.title for section in page.sections}
    assert sections["theme.choice.timer"] == "Time limit bar"
    paths = {f.path for f in page.fields}
    assert {"theme.choice.timer.fill_color", "theme.choice.timer.track_color",
            "theme.choice.timer.tick_sound"} <= paths
    for path in ("theme.choice.timer.fill_color", "theme.choice.timer.track_color",
                 "theme.choice.timer.tick_sound"):
        assert path in sm.fields_by_path() and sm.fields_by_path()[path].help, path
