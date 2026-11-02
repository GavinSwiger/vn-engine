"""Studio's config.toml help, the pure half (2026-11-02, user: keep Studio updated;
``06`` AC-F45-63..66). The Tk row is ``test_studio_assist_window.py``."""

from engine.core.config_schema import key_doc
from engine.tools.editor.assist import help_sections
from engine.tools.editor.config_help import (
    auto_open_config, config_candidates, config_context, config_help, section_at,
    section_paths)


def names(line, section=None, column=None):
    ctx = config_context(line, len(line) if column is None else column, section)
    return None if ctx is None else [(c.text, c.kind) for c in config_candidates(ctx)]


def test_ac64_section_names_complete_after_the_bracket():
    assert {"content_warning", "codex", "theme.minigame", "effects", "flowchart", "words",
            "stage.positions", "theme.textbox.name_tab"} <= set(section_paths())
    assert names("[con") == [("content_warning", "section")]
    assert names("[theme.mini")[0] == ("theme.minigame", "section")
    assert auto_open_config("[", 1, None) and not auto_open_config("x", 1, "game")


def test_ac65_key_names_and_fixed_values_complete_inside_a_section():
    assert names("no", "codex") == [("notify", "key")]
    assert ("warning_heading", "key") in names("warn", "words")
    assert names("no", None) is None                       # before any header
    assert names('show = "o', "content_warning") == [('"once"', "value")]
    assert names("reduce = ", "effects") == [("true", "value"), ("false", "value")]
    assert auto_open_config("jump = ", 7, "flowchart")
    assert not auto_open_config('title = ', 8, "game")   # free text: nothing to offer
    assert section_at('[game]\ntitle = "x"\n[theme.minigame]\nfade_ms = 3\n') == \
        "theme.minigame"


def test_ac66_help_shows_description_type_and_default():
    rows = dict(help_sections(config_help("min_seconds = 3", "content_warning")))
    assert rows == {
        "title": "[content_warning] min_seconds",
        "syntax": "Accepts seconds from 0 to 10",
        "summary": key_doc("content_warning", "min_seconds"),
        "example": "min_seconds = 2.0   # default"}
    colour = dict(help_sections(config_help("text_color = 1", "theme.textbox")))
    assert colour["example"] == 'text_color = "#3D2B36"   # default'
    assert colour["summary"] == "the text color"
    dotted = dict(help_sections(config_help("name_tab.text_size = 3", "theme.textbox")))
    assert dotted["title"] == "[theme.textbox.name_tab] text_size"
    section = dict(help_sections(config_help("[theme.minigame]", None)))
    assert section["title"] == "[theme.minigame]"
    assert section["summary"] == "the frame around every minigame"
    assert config_help("nonsense = 1", "game") is None
    assert config_help("# a comment", "game") is None
