"""F47 P1-D: Game settings built from ``config_schema`` (``settingsmodel``; AC-F47-16, 17).
The Tk tab is W4's (AC-F47-19, 20)."""

import pytest

from engine.core.config_schema import SECTIONS, config_fields, section_class
from engine.tools.editor import settingsmodel as sm
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)


def test_ac16_p1_pages_and_all_settings_reach_every_key():
    shown = sm.pages()
    assert [p.title for p in shown if p.key not in (*sm.P2_PAGES, sm.LOOKS)] == [
        "Game", "Title screen", "Text box", "Content warning", "All settings"]
    assert [f.path for f in sm.page("game").fields] == [
        "game.title", "game.version", "window.width", "window.height", "window.fullscreen",
        "window.icon"]
    paths = {p.key: {f.path for f in p.fields} for p in shown}
    own = lambda path: {f"{path}.{k}" for k in config_fields(section_class(path))}  # noqa: E731
    assert own("title") | own("theme.title.logo") | own("theme.title.loading") <= paths["title"]
    assert {"theme.title.music", "theme.title.background_image",
            "theme.title.version.text_size"} <= paths["title"]
    assert {"textbox.cps", "theme.textbox.fill_color", "theme.textbox.name_tab.text_color",
            "theme.textbox.indicator.page_image"} <= paths["textbox"]
    assert paths["content_warning"] == own("content_warning")
    assert (sm.page("title").preview, sm.page("textbox").preview) == ("title", "textbox")
    # Settings key coverage (the README's Studio coverage rule): every key, of every
    # section a later feature adds too, is on All settings or text only with a reason.
    assert {k.split(".")[0] for k in sm.all_keys()} >= set(SECTIONS)
    for key in sm.all_keys():
        assert key in sm.fields_by_path() or sm.text_only(key) or sm.on_looks_page(key), key
    assert sm.on_looks_page("playthrough.<N>.title_entries")            # W9's Looks page
    assert set(paths[sm.ALL_SETTINGS]) == set(sm.fields_by_path())
    for p in shown[:-1]:                               # hand-picked keys are real keys
        assert paths[p.key] <= paths[sm.ALL_SETTINGS], p.key
    hits = sm.search("NAME TAB")
    assert hits and all("name_tab" in s.path for s in hits)
    # A config.toml that doesn't parse shows only PR-F47-18's message.
    assert sm.broken('[game]\ntitle = "x"\n') is None
    assert sm.broken('[game]\ntitle = "x"\nversion = \n') == 3
    assert sm.broken_message(3) == ("config.toml has a mistake on line 3, so these settings "
                                    "can't be shown. Fix it in the Editor.")


CASES = [  # path, kind, WidgetSpec values, Use default caption
    ("window.fullscreen", "toggle", {}, "Default: Off"),
    ("engine.log_level", "choice", {"options": ("debug", "info", "warning", "error")},
     "Default: info"),
    ("theme.textbox.fill_color", "color", {}, "Default: #FFF4F8"),
    ("textbox.cps", "number", {"lo": 0, "hi": 1000, "integer": True}, "Default: 40"),
    ("saves.autosave_interval", "number", {"off": True, "lo": 60}, "Default: 300"),
    ("theme.textbox.fill_opacity", "number", {"lo": 0.0, "hi": 1.0, "integer": False},
     "Default: 0.8"),
    ("content_warning.min_seconds", "number", {"lo": 0, "hi": 10, "integer": False},
     "Default: 2.0"),
    ("theme.textbox.text_font", "file", {"group": "fonts", "preview": "thumb"},
     "Default: not set"),
    ("theme.textbox.frame_image", "file", {"group": "gui"}, "Default: not set"),
    ("theme.title.music", "file", {"group": "audio", "strip": "audio/", "preview": "play"},
     "Default: not set"),
    ("window.icon", "file", {"group": "gui", "suffixes": (".png",)}, "Default: not set"),
    ("game.title", "text", {"multiline": False}, "Default: Untitled Visual Novel"),
    ("content_warning.text", "text", {"multiline": True}, "Default: empty"),
    ("title.entries", "text", {"names": True}, "Default: not set"),
    ("stage.positions", "table", {"reason": sm.TABLE_REASON}, "Default: not set"),
]


@pytest.mark.parametrize("path, kind, spec, caption", CASES, ids=[c[0] for c in CASES])
def test_ac17_widget_by_validator_with_hint_and_use_default(path, kind, spec, caption):
    field = sm.fields_by_path()[path]
    assert field.kind == kind and field.widget.expected
    for name, value in spec.items():
        assert getattr(field.widget, name) == value, name
    assert field.help and field.label and field.label != field.key
    assert field.default_text == caption
    # Use default: the file's value wins while set; removing it shows the default again.
    found = sm.values('[theme.textbox]\nfill_color = "#000000"\nname_tab.text_size = 30\n'
                      '[saves]\nautosave_interval = 0\n')
    assert found["theme.textbox.name_tab.text_size"] == 30
    if path == "theme.textbox.fill_color":
        assert field.current(found) == "#000000" and field.changed(found)
        assert field.current({}) == field.default and not field.is_set({})
    if path == "saves.autosave_interval":
        assert field.current(found) == 0 and field.widget.clamp(10) == 0
        assert field.widget.clamp(50) == 60 and field.widget.clamp(9999) == 3600
    if kind == "number":
        assert field.widget.clamp(-1e9) == (0 if field.widget.off else field.widget.lo)
        assert field.problem(field.default) is None
    if kind == "text" and field.widget.names:
        assert field.widget.from_text("new_game, quit") == ["new_game", "quit"]
        assert field.problem(field.widget.from_text("new_game, quit")) is None
    assert sm.values("[game\n") is None
    for every in sm.all_settings().fields:            # every key gets a widget and a hint
        assert every.kind in sm.KINDS and every.help, every.path


def test_ac49_p2_pages_exist_and_list_real_keys():
    titles = {p.key: p.title for p in sm.pages()}
    assert [titles[key] for key in sm.P2_PAGES] == [
        "Choices", "Saves & going back", "Sound volumes", "Effects & comfort",
        "Chapters & codex", "Flowchart", "Fourth wall", "Extras", "Button words"]
    for found in sm.PAGES:                     # each listed key is a config_schema key
        for row in found.rows:
            if found.key == "extras" and section_class(row.path) is None:
                continue                       # F34-W4: [gallery] comes with F34-W3
            if row.later:                      # a parallel step adds them (F36-W3's words)
                continue
            assert set(row.keys) <= set(config_fields(section_class(row.path))), row
    for key in sm.P2_PAGES:
        page = sm.page(key)
        assert (page.fields or key == "extras") and {f.path for f in page.fields} <= set(sm.fields_by_path()), key
        assert len({f.path for f in page.fields}) == len(page.fields), key   # none twice
    paths = {key: {f.path for f in sm.page(key).fields} for key in sm.P2_PAGES}
    assert {"choice.show_locked", "theme.choice.locked.text_color"} <= paths["choices"]
    assert {"saves.autosave_interval", "rollback.steps", "chapter.autosave"} <= paths["saves"]
    assert {f"audio.{k}" for k in config_fields(SECTIONS["audio"])} == paths["sound"]
    assert {"effects.reduce", "effects.glitch_size", "auto.delay"} <= paths["effects"]
    assert {"codex.notify", "theme.chapter.title.text_size"} <= paths["chapters"]
    assert {"flowchart.jump", "theme.flowchart.here.fill_color"} <= paths["flowchart"]
    assert {"meta.username", "words.fake_crash_hint"} <= paths["fourth_wall"]
    # Button words holds every word, a later one under "Other words".
    assert paths["words"] == {f"words.{k}" for k in config_fields(SECTIONS["words"])}
    assert sm.page("words").sections[-1].title == "Other words"
