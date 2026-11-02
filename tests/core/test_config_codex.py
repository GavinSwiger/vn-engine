"""F21 step 3 — AC-F21-34: ``[codex]``, ``[theme.codex]``, and the seven codex words (F21
01 §5.4, §6; 04 §13). A bad value is one F01 ``ConfigError`` and the default is kept; an
unknown key warns (AC-F10-20's form)."""

from engine.core.config_schema import (SECTIONS, ButtonDisabledTheme, ButtonMarkerTheme,
                                       ButtonTheme, CodexConfig, CodexLockedTheme,
                                       CodexNewTheme, CodexTheme, Config, ThemeConfig)
from engine.ui.builtin.codex_page import locked_color, new_dot_color

LINE2 = "config.toml, line 2: "
WORDS = {"codex": "Codex", "codex_tips": "Tips", "codex_items": "Items",
         "codex_new_tip": "New tip", "codex_new_item": "New item", "codex_locked": "???",
         "codex_empty": "Nothing here yet."}


def test_ac34_configuration_theme_and_words(load):
    config = Config()
    assert config.codex == CodexConfig(notify=True, show_locked=False)
    assert SECTIONS["codex"] is CodexConfig and config.theme.codex.image_height == 200
    result = load("[codex]\nnotify = false\nshow_locked = true\n")
    assert result.errors == [] and result.config.codex == CodexConfig(False, True)
    result = load('[codex]\nnotify = "yes"\n')
    assert [e.format() for e in result.errors] == [
        LINE2 + '[codex] notify must be true or false, but found the text "yes"']
    assert result.config.codex == CodexConfig()
    result = load("[codex]\nshow_lockd = true\n")
    assert result.errors == [] and any("show_lockd" in w for w in result.warnings)
    for value in (0, 320):
        result = load(f"[theme.codex]\nimage_height = {value}\n")
        assert result.errors == [] and result.config.theme.codex.image_height == value
    for value in (-1, 321):
        result = load(f"[theme.codex]\nimage_height = {value}\n")
        assert len(result.errors) == 1 and "image_height" in result.errors[0].format()
        assert result.config.theme.codex.image_height == 200
    # The dot follows button.marker.fill_color (an author's too) until set; the same for ???.
    marker, disabled = (1, 2, 3), (4, 5, 6)
    theme = ThemeConfig(button=ButtonTheme(marker=ButtonMarkerTheme(marker),
                                           disabled=ButtonDisabledTheme(text_color=disabled)))
    assert (new_dot_color(theme), locked_color(theme)) == (marker, disabled)
    own = ThemeConfig(button=theme.button, codex=CodexTheme(
        new=CodexNewTheme((7, 8, 9)), locked=CodexLockedTheme((10, 11, 12))))
    assert (new_dot_color(own), locked_color(own)) == ((7, 8, 9), (10, 11, 12))
    result = load('[theme.codex.new]\nfill_color = "#102030"\n'
                  '[theme.codex.locked]\ntext_color = "#405060"\n')
    assert result.errors == []
    assert (new_dot_color(result.config.theme), locked_color(result.config.theme)) == \
        ((0x10, 0x20, 0x30), (0x40, 0x50, 0x60))
    # The seven words: English defaults, each settable.
    assert {key: getattr(config.words, key) for key in WORDS} == WORDS
    text = "[words]\n" + "".join(f'{key} = "x{key}"\n' for key in WORDS)
    result = load(text)
    assert result.errors == []
    assert {key: getattr(result.config.words, key) for key in WORDS} == \
        {key: f"x{key}" for key in WORDS}
