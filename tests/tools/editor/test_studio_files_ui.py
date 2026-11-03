"""F47 W9 in Studio (``01-design.md`` §4.4, §4.5; AC-F47-47, 48): the Meta file form (F31)
with its name picker from ``files/`` and "Result goes to", the ``files/`` group feeding it;
the Game UI form (F32) with the config's styles and Delete all saves asking first; and Game
settings' **Styles & playthrough looks** page with + New style. One test per AC, in a real
Studio window on the sample game (the helper child faked); the pure halves are
``test_forms_files_ui.py``."""

import pytest

from engine.script.assetgroups import CONFIG_REF
from engine.tools.editor import dialogs, formdialogs, forms_files_ui as W9
from engine.tools.editor import settingsmodel as sm

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import settingsview  # noqa: E402
from tests.tools.editor.test_studio_database import (  # noqa: E402,F401,I001
    apply_check, helper, sample_game, text_of)
from tests.tools.editor.test_studio_formtools import card, opened  # noqa: E402
from tests.tools.editor.test_studio_settings import open_settings, type_into  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk
MAIN = "script/main.vns"


def _add_lines(game, *lines: str) -> None:
    main = game / "script" / "main.vns"
    text = main.read_text(encoding="utf-8")
    body = "".join(f"    {line}\n" for line in lines)
    main.write_text(text.replace("label bridge:\n", "label bridge:\n" + body, 1),
                    encoding="utf-8", newline="\n")


def test_ac_f47_47_meta_file_form_and_the_files_group(studio, tmp_path, helper, monkeypatch):
    game = sample_game(tmp_path)
    (game / "files").mkdir(exist_ok=True)
    (game / "files" / "hana.chr").write_bytes(b"HANA")
    (game / "files" / "Not A Name.png").write_bytes(b"x")            # not offered
    _add_lines(game, 'file write "hana.chr"')
    db = game / "script" / "database.vns"
    db.write_text(db.read_text(encoding="utf-8") + "default hana_here = False\n",
                  encoding="utf-8", newline="\n")
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    ed.press(ed.text, "<Control-Key-2>")
    # The files/ group feeds the picker (F31's originals; a new one shows before a check).
    assets = ed.win.story.form_assets()
    assert assets.meta_files() == ("hana.chr",)
    source = tmp_path / "picked"
    source.mkdir()
    (source / "read_me.txt").write_text("hi", encoding="utf-8")
    monkeypatch.setattr(dialogs, "show_info", lambda *_a, **_k: None)
    from engine.tools.editor import fileactions
    monkeypatch.setattr(fileactions, "show_info", lambda *_a, **_k: None, raising=False)
    ed.win.add_files([source / "read_me.txt"], target=("files", "files"))
    for _ in range(200):
        ed.root.update()
        if not ed.win.adding and (game / "files" / "read_me.txt").exists():
            break
    ed.win.refresh_project()
    assert ed.win.story.form_assets().meta_files() == ("hana.chr", "read_me.txt")
    seen: dict = {}

    def drive(dialog):
        names = dialog.names["name"].names
        seen["start"] = (dialog.values(), dialog.hidden(), card(dialog), "hana.chr" in names,
                         "read_me.txt" in names)
        dialog.vars["action"].set("read")                   # a .chr can't be read
        seen["read"] = (dialog.problem_label.cget("text"), dialog.buttons[0].instate(
            ["disabled"]), card(dialog))
        dialog.vars["name"].set("Hana.chr")
        seen["bad"] = dialog.problem_label.cget("text")
        dialog.vars["name"].set("hana.chr")
        dialog.vars["action"].set("check exists")
        dialog.vars["into"].set("hana_here")
        seen["into"] = (dialog.hidden(), dialog.labels["into"].cget("text"), card(dialog),
                        dialog.problem_label.winfo_manager())
        dialog._pick(0)

    opened(ed, monkeypatch, "bridge", "Write meta file  hana.chr · a copy of files/hana.chr",
           drive)
    assert seen["start"] == (
        {"action": "write", "name": "hana.chr", "text": "", "into": ""}, {"into"},
        'file write "hana.chr"', True, True)
    assert seen["read"] == (W9.READ_TXT_ONLY, True, "")
    assert seen["bad"] == W9.NAME_RULE
    assert seen["into"] == ({"text"}, "Result goes to",
                            'file exists "hana.chr" into hana_here', "")
    assert '    file exists "hana.chr" into hana_here\n' in text_of(ed, MAIN)
    assert "Check meta file  hana.chr → hana_here" in ed.events_view.texts()


def test_ac_f47_48_game_ui_form_and_the_styles_page(studio, tmp_path, helper, monkeypatch):
    game = sample_game(tmp_path)
    _add_lines(game, 'ui saving off "Not now."')
    ed = studio(game, mapped=True)
    apply_check(ed, game)

    # Game settings ▸ Styles & playthrough looks: empty, then + New style.
    pane = open_settings(ed, sm.LOOKS)
    assert pane.page.title == "Styles & playthrough looks" and pane.look is None
    assert str(pane.new_style_button.cget("text")) == "+ New style"
    errors: list[str] = []
    monkeypatch.setattr(settingsview, "show_error", lambda _p, text: errors.append(text))
    assert not pane.new_look(sm.STYLE, "Ashes") and errors == [sm.STYLE_NAME_RULE]
    asked: list = []
    monkeypatch.setattr(settingsview, "ask_text", lambda _p, message, start, **kw: (
        asked.append((message, start, kw["hint"]("off"))) or ("ashes", True)))
    pane.new_style_button.invoke()                   # + New style: asks, then writes
    ed.root.update()
    assert asked == [(settingsview.NEW_STYLE_ASK, "", sm.STYLE_NAME_RULE)]
    text = text_of(ed, CONFIG_REF)
    assert '[style.ashes.theme.textbox]\nfill_color = "#FFF4F8"' in text
    assert pane.look == ("style", "ashes") and pane.look_box.get() == "Style ashes"
    fill = pane.shown_fields["style.ashes.theme.textbox.fill_color"]
    type_into(fill.widget, "#1E1A1C")
    words = pane.shown_fields["style.ashes.words.saving_off"]
    type_into(words.widget, "Not here.")
    ed.root.update()
    text = text_of(ed, CONFIG_REF)
    assert 'fill_color = "#1e1a1c"' in text.lower() and "[style.ashes.words]" in text
    assert "Not set: the main look" in pane.shown_fields[
        "style.ashes.theme.choice.text_color"].row.hint.cget("text")
    assert pane.new_look(sm.PLAYTHROUGH, "2")
    ed.root.update()
    assert "[playthrough.2.theme.title]" in text_of(ed, CONFIG_REF)
    assert pane.look == ("playthrough", "2") and pane.look_box.cget("values") == (
        "Style ashes", "Playthrough 2 look")
    pane.select_look(("style", "ashes"))
    pane.use_default(pane.shown_fields["style.ashes.words.saving_off"].field)
    assert "Not here." not in text_of(ed, CONFIG_REF)
    ed.win.files[CONFIG_REF].widget.edit_undo()                     # one undo step each
    assert "Not here." in text_of(ed, CONFIG_REF)

    # The Game UI form: styles from the open config.toml, Delete all saves asks first.
    ed.win.show_tab(ed.win.tab_index("editor"))
    ed.press(ed.text, "<Control-Key-2>")
    answers = [1, 0]                                     # Cancel, then Delete all saves
    questions: list = []

    def ask(_parent, message, buttons, **kw):
        questions.append((message, tuple(buttons), kw.get("default")))
        return answers.pop(0)

    monkeypatch.setattr(formdialogs.dialogs, "ask", ask)
    seen: dict = {}

    def drive(dialog):
        seen["start"] = (dialog.values(), dialog.hidden(), card(dialog))
        dialog.vars["action"].set("style")
        seen["styles"] = (dialog.names["style"].names, dialog.hidden())
        dialog.vars["style"].set("ashes")
        seen["style"] = card(dialog)
        dialog.vars["action"].set("delete all saves")
        dialog._pick(0)                                  # asks; Cancel keeps the dialog
        seen["kept"] = dialog.dialog.winfo_exists() and dialog.result is None
        dialog._pick(0)

    opened(ed, monkeypatch, "bridge", "Stop saving  Not now.", drive)
    assert seen["start"] == ({"action": "saving off", "style": "", "reason": "Not now."},
                             {"style"}, 'ui saving off "Not now."')
    assert "ashes" in seen["styles"][0] and "off" in seen["styles"][0]
    assert seen["styles"][1] == {"reason"} and seen["style"] == "ui style ashes"
    assert seen["kept"] and questions == [(W9.CONFIRM_DELETE, W9.CONFIRM_BUTTONS, 1)] * 2
    assert "    ui delete saves\n" in text_of(ed, MAIN)
    assert "Delete all saves" in ed.events_view.texts()
