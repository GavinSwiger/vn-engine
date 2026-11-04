"""F49 S2: the Color scheme page's model (``schememodel``) and its Game settings fields
(``settingsmodel``; AC-F49-09, 10). The Tk page is W1's (``test_studio_schemes``)."""

import tomllib

from engine.core.schemes import SCHEMES
from engine.tools.editor import schememodel as scm
from engine.tools.editor import settingsmodel as sm
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)


def test_ac_f49_09_cards_in_use_custom_colors_clear_and_preview_text():
    shown = scm.cards()
    assert [c.id for c in shown] == ["sakura", "pocket", "amber", "synthwave", "vaporwave",
                                     "groovy"]
    assert [c.name for c in shown] == ["Sakura", "Pocket LCD", "Amber Terminal",
                                       "Synthwave Sunset", "Vaporwave Dream", "Groovy '70s"]
    assert shown[1].swatches == ("#9BBC0F", "#306230", "#0F380F", "#0F380F")
    for card in shown:
        colors = SCHEMES[card.id].colors
        assert card.swatches == (colors["fill"], colors["border"], colors["accent"],
                                 colors["text"])

    # In use: Sakura with no preset, the set one, none for an id this version lacks.
    assert scm.in_use(sm.values("[game]\ntitle = \"x\"\n")) == "sakura"
    assert scm.in_use(sm.values('[theme]\npreset = "amber"\n')) == "amber"
    assert scm.unknown_text(sm.values('[theme]\npreset = "amber"\n')) is None
    unknown = sm.values('[theme]\npreset = "neon\\u0007"\n')
    assert scm.in_use(unknown) is None
    assert scm.unknown_text(unknown) == (
        "config.toml asks for a color scheme this version doesn't have (\"neon\\x07\"), so "
        "the default colors show. Pick one and press Apply.")                   # echo()

    # Custom colors: mapped or following [theme] color keys only.
    text = ('[theme]\npreset = "pocket"\n'
            '[theme.textbox]\nfill_color = "#FFFFFF"\nfill_opacity = 0.5\n'
            '[theme.nvl]\ntext_color = "#101010"\n'                  # following: counts
            '[theme.menu]\ndim_color = "#000000"\n'                  # neutral: no
            '[theme.plugin.pong]\nball_color = "#FF0000"\n'          # plugin: no
            '[style.term.theme.panel]\nfill_color = "#000000"\n')    # a style's: no
    found = sm.values(text)
    assert scm.custom_colors(found) == ("theme.textbox.fill_color", "theme.nvl.text_color")
    assert scm.note_body(2) == "2 colors you set yourself still show over the scheme."
    assert scm.note_body(1) == "1 color you set yourself still shows over the scheme."
    assert scm.custom_colors(sm.values('[theme.textbox]\nfill_opacity = 0.5\n')) == ()
    changes = scm.clear_changes(found)
    assert changes == (("theme.textbox", "fill_color", None), ("theme.nvl", "text_color", None))
    from engine.tools.editor import tomlpatch
    from engine.tools.editor.scriptedit import apply_lines
    plan = tomlpatch.plan_changes(text, changes)
    cleared = sm.values("\n".join(apply_lines(text.split("\n"), plan.edits)))
    assert scm.custom_colors(cleared) == () and cleared["theme.menu.dim_color"] == "#000000"

    # The preview's text: the open text with only preset changed (a [theme] added if none).
    for start in (text, '[game]\ntitle = "x"\n', ""):
        made = scm.preview_text(start, "synthwave")
        before = tomllib.loads(start)
        after = tomllib.loads(made)
        assert after.get("theme", {}).pop("preset") == "synthwave"
        before.get("theme", {}).pop("preset", None)
        if not after["theme"] and "theme" not in before:
            del after["theme"]
        assert after == before, start
    assert scm.preview_text('[theme]\npreset = "amber"\n', "amber") == \
        '[theme]\npreset = "amber"\n'
    assert scm.apply_change("groovy") == ("theme", "preset", "groovy")


def test_ac_f49_10_preset_on_all_settings_and_each_style_look_page():
    assert "theme.preset" in sm.all_keys()
    field = sm.fields_by_path()["theme.preset"]
    assert field.kind == "choice" and field.label == "Color scheme"
    assert field.widget.options == tuple(SCHEMES)
    assert [field.widget.option_text(o) for o in field.widget.options] == [
        s.name for s in SCHEMES.values()]
    assert sm.fields_by_path()["engine.log_level"].widget.option_text("debug") == "Debug"
    assert any(field in s.fields for s in sm.search("color scheme"))
    page = sm.look_page("style", "x")
    first = page.sections[0]
    assert (first.title, first.path) == ("Color scheme", "style.x.theme")
    assert [f.path for f in first.fields] == ["style.x.theme.preset"]
    assert first.fields[0].default_text == sm.LOOK_UNSET and sm.is_look(first.fields[0])
    assert first.fields[0].widget.labels == field.widget.labels
    assert not any(f.path.endswith("preset") for f in sm.look_page("playthrough", "2").fields)
    # The page is second, a generated one with the text box still.
    assert [p.key for p in sm.pages()][:2] == ["game", sm.SCHEMES]
    assert sm.page(sm.SCHEMES).title == "Color scheme"
    assert sm.page(sm.SCHEMES).preview == "textbox"
