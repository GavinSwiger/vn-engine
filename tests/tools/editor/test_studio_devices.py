"""F65 round 3: Studio's Game settings ▸ Devices (``devicepage``, ``devicemodel``), on a copy
of the sample game in ``tmp_path``: one card per device with the game's device first and
marked, the live preview of the notice and a message, the fields, Use default, and each
change as one undo step of config.toml."""

import pytest

from engine.core.kits import DEVICE_LOOKS
from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import devicemodel as dm
from engine.tools.editor import settingsmodel as sm

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_schemes import (  # noqa: E402
    config_text, edit_editor, helper, sample_game)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk
_ = helper


def open_devices(ed):
    ed.root.update()
    ed.win.show_tab(ed.win.tab_index("settings"))
    pane = ed.win.settings
    pane.select_page(sm.DEVICES)
    ed.root.update()
    return pane.devices_page


def with_config(ed, more: str):
    open_devices(ed)
    edit_editor(ed, config_text(ed) + more)
    ed.win.settings.refresh()
    ed.root.update()
    return ed.win.settings.devices_page


def texts(card, tag):
    return [card.canvas.itemcget(i, "text") for i in card.canvas.find_withtag(tag)]


def test_devices_page_marks_the_kit_device_and_writes_one_undo_step(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    page = with_config(ed, '\n[theme]\nkit = "fantasy"\n')
    assert ed.win.settings.title_label.cget("text") == "Devices"
    assert page.order[0] == "pigeon" and set(page.order) == set(DEVICE_LOOKS)
    pigeon = page.cards["pigeon"]
    assert pigeon.mark.cget("text") == "The game's device (from the Fantasy kit)"
    assert page.cards["phone"].mark.cget("text") == ""
    assert texts(pigeon, "notice_text") == [
        "A pigeon lands on the sill with a note from Hana."]
    assert texts(pigeon, "header") == ["Arrived by pigeon · Day 3"]
    assert texts(pigeon, "signature") == ["— Hana"]                  # reads as a letter
    assert "Not set: “Arrived by pigeon”" in pigeon.rows["header_text"].hint.cget("text")
    record = ed.win.files[CONFIG_REF]
    before = config_text(ed)

    # A field writes [device.pigeon]; the preview and the title follow.
    pigeon.inputs["arrive_text"].var.set("A grey bird lands on the sill.")
    pigeon.inputs["arrive_text"]._done()
    ed.root.update()
    assert config_text(ed).endswith(                               # the end kept
        '[device.pigeon]\narrive_text = "A grey bird lands on the sill."\n')
    pigeon = ed.win.settings.devices_page.cards["pigeon"]
    assert texts(pigeon, "notice_text") == ["A grey bird lands on the sill."]
    assert str(pigeon.rows["arrive_text"].default.cget("state")) == "normal"
    pigeon.inputs["name"].var.set("Rookery")
    pigeon.inputs["name"]._done()
    pigeon.inputs["reading"].pick("chat")
    ed.root.update()
    found = dm.own(sm.values(config_text(ed)), "pigeon")
    assert (found["name"], found["reading"]) == ("Rookery", "chat")
    pigeon = ed.win.settings.devices_page.cards["pigeon"]
    assert pigeon.title.cget("text") == "Rookery (Pigeon post)"
    assert texts(pigeon, "signature") == []                         # chat lines now
    assert any(t.startswith("Hana: ") for t in texts(pigeon, "line"))
    # Each change was one undo step.
    for _ in range(3):
        record.widget.edit_undo()
    ed.root.update()
    assert config_text(ed) == before

    # Use default removes the line, and the table once it is empty.
    page = ed.win.settings.devices_page
    page.cards["radio"].inputs["header_text"].var.set("Static")
    page.cards["radio"].inputs["header_text"]._done()
    ed.root.update()
    assert "[device.radio]" in config_text(ed)
    ed.win.settings.devices_page.cards["radio"].rows["header_text"].default.invoke()
    ed.root.update()
    assert "[device.radio]" not in config_text(ed)
    assert config_text(ed) == before                    # with its final newline


def test_each_card_previews_its_look_in_the_scheme(studio, tmp_path, helper):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    page = with_config(ed, '\n[theme]\npreset = "noir"\n')
    assert page.order[0] == "phone"                                   # no kit: a phone
    for look in DEVICE_LOOKS:
        card = page.cards[look]
        assert card.canvas.find_withtag("notice") and card.canvas.find_withtag("message")
        colors = dm.palette(sm.values(config_text(ed)), look)
        panel = card.canvas.find_withtag("panel")[0]
        assert card.canvas.itemcget(panel, "fill").upper() == colors.page
    assert page.cards["terminal"].canvas.find_withtag("cursor")
    assert texts(page.cards["radio"], "signal") == ["[signal]"]
