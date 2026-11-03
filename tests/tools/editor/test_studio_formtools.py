"""F47 P2 in Studio's forms: the condition builder (If, a choice's "Only show when"), the
Say text toolbar, and the P2 forms' dialog niceties (colour swatches, Insert player name,
Lock/Unlock's one name field, the Chapter name, Insert…'s form-only entries and text-only
reasons). Tk, in a real Studio window on the sample game; the helper child is faked."""

import pytest

from engine.tools.editor import conditions as C
from engine.tools.editor import formdialogs, forms, forms_more, formtools
from engine.tools.editor import texttools as T
from engine.tools.editor.forms import ChoiceItem, ChoiceValues

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import (  # noqa: E402,F401,I001
    apply_check, helper, sample_game, text_of)
from tests.tools.editor.test_studio_storyedit import events_on, row_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk
MAIN = "script/main.vns"


def opened(ed, monkeypatch, scene: str, text: str, answer) -> None:
    """Edit Events row ``text`` of ``scene`` with the real dialog; ``answer(dialog)`` drives
    it (it presses OK or Cancel itself)."""
    def edit(parent, form, start, *, names, ok="OK", assets=None):
        dialog = formdialogs.FormDialog(parent, form, start, names=names, ok=ok,
                                        assets=assets)
        answer(dialog)
        return dialog.result

    monkeypatch.setattr(formdialogs, "edit_form", edit)
    events_on(ed, scene)
    ed.win.story.edit(row_of(ed, text))
    ed.root.update()


def card(dialog) -> str:
    return dialog.card.get("1.0", "end-1c")


def test_condition_builder_in_the_if_and_choice_forms(studio, tmp_path, helper,
                                                      monkeypatch):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    ed.press(ed.text, "<Control-Key-2>")
    seen: dict = {}

    def build(dialog):
        builder = dialog.builder
        seen["names"] = builder.names_of(C.VARIABLE)
        seen["start"] = (builder.scripted, builder.rows())
        builder.add()                                       # + : a second check
        second = builder.checks[1]
        second.kind.set(C.KINDS[C.PLAYTHROUGH])
        second._kind_picked()
        second.op.set("is at least")
        second.value.set("")                                # not written yet: says why
        seen["problem"] = (second.hint.cget("text"), dialog.buttons[0].instate(["disabled"]),
                           card(dialog))
        dialog._pick(0)                                     # OK waits
        assert dialog.dialog.winfo_exists()
        second.value.set("2")
        builder.join.set(C.JOINS[C.ANY])
        seen["line"] = card(dialog)
        dialog._pick(0)

    opened(ed, monkeypatch, "bridge", "If  sent_lantern is yes", build)  # summary in words
    assert "sent_lantern" in seen["names"]
    assert seen["start"] == (False, [C.Row(C.VARIABLE, "sent_lantern", C.EQ, C.YES)])
    assert seen["problem"] == ("Fill in the value.", True, "")
    assert seen["line"] == "if sent_lantern or persistent.playthrough >= 2:"
    assert "    if sent_lantern or persistent.playthrough >= 2:" in text_of(ed, MAIN)
    assert "If  sent_lantern is yes or playthrough is at least 2" in ed.events_view.texts()

    # A condition the builder can't show: "Written as script", kept as typed.
    form = forms.form_by_key("if")
    odd = formdialogs.FormDialog(ed.root, form, {"keyword": "if",
                                                 "condition": "len(codex.tips)  > 2"},
                                 names=ed.win.story.names())
    assert odd.builder.scripted and odd.builder.problem() is None
    assert formtools.WRITTEN_AS_SCRIPT == "Written as script"
    assert card(odd) == "if len(codex.tips)  > 2:"
    odd.vars["keyword"].set("else")                          # Else: no condition shown
    assert "condition" in odd.hidden() and not odd.labels["condition"].winfo_manager()
    odd._pick(1)

    # A choice's "Only show when": a button in words that opens the builder.
    values = ChoiceValues("", "", "Which way?", (ChoiceItem("Left", "sent_lantern"),
                                                 ChoiceItem("Right")))
    choice = formdialogs.ChoiceDialog(ed.root, values, names=ed.win.story.names(),
                                      assets=ed.win.story.form_assets())
    buttons = [row["widgets"][2] for row in choice.items]
    assert [str(b.cget("text")) for b in buttons] == ["sent_lantern is yes",
                                                      formtools.ALWAYS]

    def ask(parent, text, names):
        dialog = formtools.ConditionDialog(parent, text, names)
        check = dialog.builder.checks[0]                     # one blank check to start
        check.kind.set(C.KINDS[C.ENDING])
        check._kind_picked()
        check.name.set("lantern")
        check.op.set(formtools.HAS_WORDS[C.ENDING][1])
        dialog._pick(0)
        return dialog.result

    monkeypatch.setattr(formtools, "ask_condition", ask)
    assert choice.edit_when(choice.items[1]) == '"lantern" not in persistent.endings'
    assert str(buttons[1].cget("text")) == "ending lantern not seen"
    choice._pick(0)
    assert [item.condition for item in choice.result.choices] == [
        "sent_lantern", '"lantern" not in persistent.endings']


def test_say_text_toolbar(studio, tmp_path, helper, monkeypatch):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    ed.press(ed.text, "<Control-Key-2>")
    seen: dict = {}

    def style(dialog):
        bar, entry = dialog.toolbar, dialog.text_entry
        assert [b.key for b in T.BUTTONS if not b.more] == list(bar.buttons)
        assert [bar.menu.entrycget(i, "label") for i in (0, 1, 3)] == [
            "Size", "Go on by itself", formtools.CLEAR_FORMATTING]
        text = dialog.vars["text"].get()
        at = text.index("lost")
        entry.selection_range(at, at + 4)
        asked: list[str] = []
        bar.asker = lambda _p, button, _n: asked.append(button.ask) or "#9a1c14"
        bar.press("colour")                                  # the colour picker's answer
        seen["colour"] = (asked, dialog.vars["text"].get(), bar.shown(),
                          entry.index("sel.first"), entry.index("sel.last"))
        bar.press("bold")                                    # the same words: Bold on
        bar.press("bold")                                    # ... and off again

        def pause(parent, button, names):                   # the seconds spinner
            ask = formtools.ValueDialog(parent, button, names)
            ask.var.set("40")
            seen["too_long"] = ask.why_not()
            ask.var.set("1.5")
            ask._pick(0)
            return ask.result

        bar.asker = pause
        entry.selection_clear()
        entry.icursor("end")
        bar.press("pause")
        dialog.vars["text"].set(dialog.vars["text"].get() + "{color=red}x{/color}")
        seen["problem"] = str(bar.problem.cget("text"))
        dialog.vars["text"].set(dialog.vars["text"].get()[:-len("{color=red}x{/color}")])
        seen["line"] = card(dialog)
        dialog._pick(0)

    opened(ed, monkeypatch, "start", "Say  hana: You came! Daichi said you'd get lost at "
           "least twice.", style)
    asked, text, shown, first, last = seen["colour"]
    assert asked == [T.ASK_COLOUR]
    assert "get {color=#9a1c14}lost{/color} at" in text
    assert shown == "You came! Daichi said you'd get lost at least twice."
    assert text[first:last] == "lost"
    assert seen["too_long"] and seen["problem"]
    want = ('hana "You came! Daichi said you\'d get {color=#9a1c14}lost{/color} at least '
            'twice.{pause=1.5}"')
    assert seen["line"] == want
    assert "    " + want in text_of(ed, MAIN)


def test_p2_form_dialogs_and_insert_picker(studio, tmp_path, helper, monkeypatch):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    ed.press(ed.text, "<Control-Key-2>")
    story = ed.win.story

    def dialog(key, values, names=None):
        start = {f.key: "" for f in forms.form_by_key(key).fields} | values
        return formdialogs.FormDialog(ed.root, forms.form_by_key(key), start,
                                      names=story.names() if names is None else names,
                                      assets=story.form_assets())

    # Colour swatches: Transition, Flash, Chapter; Pick… is the system colour picker.
    for key in ("transition", "flash", "chapter"):
        assert set(dialog(key, {}).colours) == {"colour"}
    flash = dialog("flash", {"colour": "white"})
    box = flash.colours["colour"]
    assert box.value == "#ffffff"
    monkeypatch.setattr(formtools, "ask_color", lambda _p, _c: "#123456")
    box.pick()
    assert flash.vars["colour"].get() == "#123456" and box.value == "#123456"
    assert card(flash) == 'flash "#123456"'
    flash._pick(1)

    # Fake crash: Insert player name.
    crash = dialog("crash", {"message": "Bye "})
    crash.text_entry.icursor("end")
    crash.player_name.invoke()
    assert crash.vars["message"].get() == "Bye " + forms_more.CRASH_PLAYER_NAME
    crash._pick(1)

    # Lock / Unlock: only the name field of "What".
    lock = dialog("lock", {"what": "tip", "tip": "river_god"})
    assert lock.hidden() == {"route", "ending", "item", "gallery", "replay"}
    assert lock.labels["tip"].winfo_manager() and not lock.labels["route"].winfo_manager()
    lock.vars["what"].set("route")
    assert lock.hidden() == {"tip", "ending", "item", "gallery", "replay"}
    # Plain words in the list ("Codex tip", "Gallery picture"); the line keeps script words.
    what = lock.widgets["what"]
    assert tuple(what.cget("values")) == ("Route", "Ending", "Codex tip", "Item",
                                          "Gallery picture", "Scene replay")
    assert what.get() == "Route"
    what.set("Gallery picture")
    assert lock.vars["what"].get() == "gallery" and lock.hidden() == {
        "route", "ending", "tip", "item", "replay"}
    lock.vars["gallery"].set("cg festival")
    assert card(lock) == "lock gallery cg festival"
    lock._pick(1)
    assert tuple(dialog("unlock", {}).widgets["what"].cget("values")) == (
        "Route", "Codex tip", "Item", "Gallery picture", "Scene replay", "Achievement")

    # A new Chapter's name: made from the title, unique; typing one stops that.
    names = dict(story.names(), chapter=["the_old_footbridge"])
    chapter = dialog("chapter", {}, names=names)
    chapter.vars["title"].set("The Old Footbridge")
    assert chapter.vars["name"].get() == "the_old_footbridge_2"
    chapter.vars["name"].set("bridge")
    chapter.vars["title"].set("Another Title")
    assert chapter.vars["name"].get() == "bridge"
    chapter._pick(1)

    # Insert…: Stop effects and Stop sound, and text-only entries' reasons.
    seen: dict = {}

    def pick(parent, menu):
        picker = formdialogs.InsertPicker(parent, menu)
        titles = dict(picker.groups())
        seen["audio"], seen["effects"] = titles["Audio"], titles["Effects"]
        seen["reasons"] = (picker.reason_of("Stage", "Position"),
                           picker.reason_of("Stage", "Background"))
        picker.choose("Audio", "Stop sound")
        picker._pick(0)
        return picker.result

    def edit(parent, form, start, *, names, ok="OK", assets=None):
        made = formdialogs.FormDialog(parent, form, start, names=names, ok=ok, assets=assets)
        made.vars["fade"].set("2")
        made._pick(0)
        return made.result

    monkeypatch.setattr(formdialogs, "pick_insert", pick)
    monkeypatch.setattr(formdialogs, "edit_form", edit)
    events_on(ed, "bridge")
    story.insert(row_of(ed, "Sound  sound/chime.wav"))
    ed.root.update()
    audio = seen["audio"]
    assert audio[audio.index("Stop music") + 1] == "Stop sound"
    effects = seen["effects"]
    assert effects[effects.index("Jitter character") + 1] == "Stop effects"
    assert seen["reasons"] == (forms.STORY_MAP_REASON, None)
    assert "    scene bg bridge_night with dissolve\n    stop sound fadeout 2\n" \
        in text_of(ed, MAIN)                    # above the Sound row (and its comment)
