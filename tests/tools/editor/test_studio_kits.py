"""F60: Studio's Game settings ▸ Kit page (specs/F60-genre-kits/SPEC.md), on a copy of the
F47 sample game in ``tmp_path`` (its config.toml has no ``[theme]``)."""

import pytest

from engine.core.kits import KITS
from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import kitmodel as km

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_schemes import (  # noqa: E402
    config_text, drawn, edit_editor, helper, press, sample_game)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk
_ = helper                                       # the fixture, imported for its name


def open_kits(ed):
    ed.root.update()
    ed.win.show_tab(ed.win.tab_index("settings"))
    pane = ed.win.settings
    pane.select_page("kits")
    ed.root.update()
    return pane.kit_page


def tags_of(cards, tag: str) -> set[str]:
    canvas = cards.widget
    return {t for item in canvas.find_withtag(tag) for t in canvas.gettags(item)}


def test_kit_cards_select_and_apply_with_its_scheme_as_one_undo_step(studio, tmp_path,
                                                                     helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    page = open_kits(ed)
    tree = ed.win.settings.page_tree
    assert [tree.item(k, "text") for k in tree.get_children()][:3] == [
        "Game", "Color scheme", "Kit"]
    assert ed.win.settings.title_label.cget("text") == "Kit"
    cards = page.cards
    assert [name for _id, name in drawn(cards, "name")] == [
        "No kit", *(k.name for k in KITS.values())]
    assert drawn(cards, "in_use") == [("", "In use")]
    # Each kit's preview draws its meter look in its corner, with its first meter's label.
    meters = tags_of(cards, "meter")
    for found in KITS.values():
        assert {f"look:{found.meters.look}", f"place:{found.meters.place}"} <= meters
    labels = {text for _id, text in drawn(cards, "label")}
    assert {"Sanity", "Affection", "Trust"} <= labels
    assert page.heading.cget("text") == "No kit"
    assert str(page.apply_button.cget("state")) == "disabled"        # no kit is in use
    assert page.scheme_check.winfo_manager() == ""                   # no scheme to offer
    original = config_text(ed)
    record = ed.win.files[CONFIG_REF]

    # A click selects: the blurb and what it sets show; nothing is written.
    x0, y0, x1, y1 = cards.card_box(3)                               # Mystery
    cards.widget.event_generate("<Button-1>", x=(x0 + x1) // 2, y=(y0 + y1) // 2)
    ed.root.update()
    assert page.pick == "mystery" and page.heading.cget("text") == "Mystery"
    assert page.lines[0].cget("text") == KITS["mystery"].blurb
    assert page.lines[1].cget("text") == km.details("mystery")[1]
    assert page.apply_button.cget("text") == "Apply Mystery"
    assert page.scheme_check.cget("text") == "Also use its color scheme (Black and White)"
    assert page.with_scheme.get() is True
    assert config_text(ed) == original and not record.dirty

    # Enter applies the kit and its scheme as one undo step.
    press(ed, cards, "<Return>")
    applied = config_text(ed)
    assert 'version = "0.1.0"\nkit = "mystery"\n' in applied
    assert applied.endswith('[theme]\npreset = "noir"')
    page = ed.win.settings.kit_page
    assert drawn(page.cards, "in_use") == [("mystery", "In use")]
    assert str(page.apply_button.cget("state")) == "disabled"
    assert str(page.scheme_check.cget("state")) == "disabled"        # its scheme is in use
    record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == original

    # Unticked, only the kit line is written; the arrow keys move the pick.
    page = open_kits(ed)
    page.cards.select("fantasy")
    ed.root.update()
    page.with_scheme.set(False)
    page.apply_button.invoke()
    ed.root.update()
    assert config_text(ed).endswith('version = "0.1.0"\nkit = "fantasy"')
    page = ed.win.settings.kit_page
    press(ed, page.cards, "<Left>")
    assert page.pick == "mystery"

    # No kit removes the line.
    page.cards.select(km.NONE)
    ed.root.update()
    assert page.apply_button.cget("text") == "Use no kit"
    page.apply_button.invoke()
    ed.root.update()
    assert "kit =" not in config_text(ed)
    assert "kit" not in (game / "config.toml").read_text(encoding="utf-8")     # unsaved


def test_unknown_kit_note(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    open_kits(ed)
    edit_editor(ed, config_text(ed) + '\n[theme]\nkit = "western"\n')
    page = open_kits(ed)
    ed.win.settings.refresh()
    ed.root.update()
    assert page.unknown.winfo_manager() == "pack"
    assert '("western")' in page.unknown_label.cget("text")
    assert drawn(page.cards, "in_use") == []
    assert page.pick == km.NONE
    assert str(page.apply_button.cget("state")) == "normal"          # removes the bad line

