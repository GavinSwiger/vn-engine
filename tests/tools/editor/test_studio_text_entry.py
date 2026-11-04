"""F52 step W6: Studio's Ask for text form, Insert ▸ Ask for a name…, and the Typing words
(AC-F52-36, 37, 38)."""

import ast

import pytest

from engine.minigames.bundled import ask_rules
from engine.tools.editor import assist, formdialogs, forms
from engine.tools.editor import minigamedata as mg
from engine.tools.editor import settingsmodel as sm

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import dialogs, minigameview as mv  # noqa: E402
from tests.tools.editor.test_studio_minigames import MAIN_REF, minigame_game, text_of  # noqa: E402
from tests.tools.editor.test_studio_database import helper  # noqa: E402,F401
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


# --- AC-F52-36: the Ask for text form ------------------------------------------------------------

def test_ac_f52_36_ask_text_form(studio, tmp_path, helper):
    ed = studio(minigame_game(tmp_path), mapped=True)
    form = mv.MinigameDialog(ed.win, None)
    assert "Ask for text" in form.game_box.cget("values")
    form.set_game("ask_text")
    assert list(form.widgets) == ["prompt", "default", "max_length", "allowed", "hide",
                                  "can_be_empty", "into"]
    labels = [f.label for f in form.form.fields]
    assert labels == ["Question", "Starts with", "Longest answer", "Characters allowed",
                      "Show dots instead of letters", "Can be left empty"]
    assert list(form.widgets["allowed"].cget("values")) == [
        "Anything", "Names", "Letters", "Digits", "Letters and digits"]
    assert form.vars["allowed"].get() == "Anything" and form.vars["max_length"].get() == "20"
    form.set("prompt", "What's your name?")
    form.set("max_length", "12")
    form.set("allowed", "Names")
    form.set("hide", "True")
    form.set("into", "poem_for")
    form._changed()
    form._pick(0)
    line = form.result["line"]
    assert line == ('minigame ask_text prompt="What\'s your name?" max_length=12 '
                    'allowed="name" hide=True into poem_for')
    call = mg.read_call(line)
    args = {k: ast.literal_eval(v) for k, v in call.args}
    assert ask_rules.problem(args) is None                     # the game accepts it
    edited = mv.MinigameDialog(ed.win, {"line": line})         # and it reads back
    assert edited.vars["allowed"].get() == "Names" and edited.vars["hide"].get() == "True"


# --- AC-F52-37: Insert ▸ Ask for a name… -------------------------------------------------------

def test_ac_f52_37_ask_for_a_name(studio, tmp_path, helper, monkeypatch):
    menu = dict(formdialogs._with_form_entries(assist.insert_menu()))
    titles = [formdialogs.entry_title(e) if not isinstance(e, forms.CommandForm) else e.title
              for e in menu["Story flow"]]
    assert titles[titles.index("Minigame") + 1] == "Ask for a name…"
    ed = studio(minigame_game(tmp_path), mapped=True)
    story = ed.win.story
    story.show(MAIN_REF, "minigames_demo")
    ed.root.update()
    entry = forms.form_by_key(mg.ASK_NAME_FORM)
    asked, opened = [], []
    before = text_of(ed, "script/database.vns")
    # Cancel on "Add it?": nothing added, no form (I-11).
    monkeypatch.setattr(dialogs, "ask", lambda parent, message, buttons, **k: (
        asked.append((message, tuple(buttons))), 1)[1])
    monkeypatch.setattr(mv, "edit_minigame", lambda win, values: opened.append(values))
    assert story.insert(0, entry) is None
    assert asked == [("player_name doesn't exist yet. Add it?", ("Add", "Cancel"))]
    assert opened == [] and text_of(ed, "script/database.vns") == before
    # Add: the variable, then the form filled with the name question.
    monkeypatch.setattr(dialogs, "ask", lambda parent, message, buttons, **k: 0)

    def fake_edit(win, values):
        opened.append(values)
        made = mv.MinigameDialog(win, values)
        seen = (made.game, made.vars["prompt"].get(), made.vars["max_length"].get(),
                made.vars["allowed"].get(), made.vars["into"].get())
        opened.append(seen)
        made._pick(0)
        return made.result

    monkeypatch.setattr(mv, "edit_minigame", fake_edit)
    story.insert(0, entry)
    assert 'default player_name = ""' in text_of(ed, "script/database.vns").split("\n")
    assert opened[0] == {"line": mg.ASK_NAME_LINE}
    assert opened[1] == ("ask_text", "What's your name?", "12", "Names", "player_name")
    assert "    " + mg.ASK_NAME_LINE in text_of(ed, MAIN_REF).split("\n")
    # Asked again with the variable there: no question.
    asked.clear()
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: asked.append(a) or 1)
    monkeypatch.setattr(mv, "edit_minigame", lambda win, values: None)
    story.insert(0, entry)
    assert asked == []


# --- AC-F52-38: Button words' Typing group; All settings' [theme.text_entry] ------------------------

def test_ac_f52_38_settings_pages():
    words = sm.page("words")
    typing = next(s for s in words.sections if s.title == "Typing")
    assert [f.key for f in typing.fields] == ["text_entry_space", "text_entry_delete",
                                             "text_entry_done", "text_entry_full",
                                             "text_entry_refused"]
    docs = {f.key: f.help for f in typing.fields}
    assert docs["text_entry_done"] == "the on-screen keyboard's finish button"
    assert docs["text_entry_full"] == "the note when typed text doesn't fit"
    every = sm.page(sm.ALL_SETTINGS)
    section = next(s for s in every.sections if s.path == "theme.text_entry")
    assert [f.key for f in section.fields] == ["fill_color", "fill_opacity", "border_color",
                                              "text_color", "text_size", "placeholder_color",
                                              "caret_color"]
    assert forms.missing_forms() == []
