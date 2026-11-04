"""F57 step 3: AC-F57-08, Studio's Minigame form for Heartbeat (SPEC §7) in a real Studio
window on a copy of the F47 sample game; the helper child is faked
(``test_studio_database.helper``)."""

import pytest

from engine.tools.editor import fieldhints
from engine.tools.editor import minigamedata as mg

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from engine.tools.editor import minigameview as mv  # noqa: E402
from engine.tools.editor.fieldwidgets import PLAY, STOP  # noqa: E402
from tests.tools.editor.test_studio_database import helper, sample_game  # noqa: E402,F401
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

FIELDS = [  # name, label, kind, default text, (lo, hi), choices
    ("beats", "Beats", mg.NUMBER, "8", (4, 20), ()),
    ("bpm", "Beats a minute", mg.NUMBER, "60", (40, 120), ()),
    ("window", "How forgiving", mg.CHOICE, '"normal"', (None, None),
     ("tight", "normal", "wide")),
    ("meter", "Meter a miss lowers", mg.METER, "None", (None, None), ()),
    ("cost", "A miss costs", mg.NUMBER, "1", (0, 20), ()),
    ("sound", "Beat sound", mg.SOUND, "None", (None, None), ()),
]
HINTS = {
    "beats": "How many beats the player presses on.",
    "bpm": "60 is one beat a second. Players with Timing assist get half the speed, or no "
           "time limit.",
    "window": "How close to the beat a press must be: tight, normal or wide.",
    "sound": "Plays on each beat, with the ring. Empty: no sound.",
}


def test_ac_f57_08_heartbeat_form(studio, tmp_path, helper):
    form = mg.form_fields("heartbeat")
    assert [(f.name, f.label, f.widget, f.default_text, (f.lo, f.hi), f.choices)
            for f in form.fields] == FIELDS
    assert (form.into.name, form.into.label) == ("into", "Result goes to")
    assert "heartbeat" in mg.BUNDLED and mg.game_title("heartbeat") == "Heartbeat"
    for name, hint in HINTS.items():
        assert fieldhints.minigame_hint("heartbeat", name) == hint

    ed = studio(sample_game(tmp_path), mapped=True)
    win = ed.win
    dialog = mv.MinigameDialog(win, None)
    assert "Heartbeat" in list(dialog.game_box.cget("values"))
    dialog.set_game("heartbeat")
    assert list(dialog.widgets) == ["beats", "bpm", "window", "meter", "cost", "sound", "into"]
    assert [dialog.vars[n].get() for n in ("beats", "bpm", "window", "meter", "cost",
                                           "sound")] == ["8", "60", "normal", "", "1", ""]
    assert dialog.tips["bpm"].text == HINTS["bpm"]
    assert str(dialog.widgets["beats"].cget("from")) in ("4", "4.0")
    assert str(dialog.widgets["bpm"].cget("to")) in ("120", "120.0")
    assert list(dialog.widgets["window"].cget("values")) == ["tight", "normal", "wide"]

    # Writing leaves the defaults out.
    dialog.set("beats", "10")
    dialog.set("into", "calm")
    dialog._pick(0)
    assert dialog.result == {"line": "minigame heartbeat beats=10 into calm"}

    # The sound field lists audio/'s files and plays one.
    dialog = mv.MinigameDialog(win, None)
    dialog.set_game("heartbeat")
    picker = dialog.pickers["sound"]
    refs = [label for _value, label in picker.choices]
    assert refs[0] == mv.NO_SOUND and "sound/chime.wav" in refs
    assert "music/lantern_walk.wav" in refs and all(not r.startswith("audio/") for r in refs)
    assert "disabled" in picker.play_button.state()                  # nothing to play yet
    picker.pick("sound/chime.wav")
    assert dialog.vars["sound"].get() == "sound/chime.wav"
    picker.play_button.invoke()
    sent = helper[0].sent
    assert sent[-1] == ("play", "audio/sound/chime.wav")
    assert str(picker.play_button.cget("text")) == STOP
    picker.play_button.invoke()
    assert sent[-1] == ("stop",) and str(picker.play_button.cget("text")) == PLAY
    picker.play_button.invoke()
    dialog.set("meter", "composure")
    dialog.set("window", "wide")
    dialog.skip_var.set(True)
    dialog._pick(0)                                                  # closing stops it
    assert sent[-1] == ("stop",)
    line = ('minigame heartbeat skippable window="wide" meter="composure" '
            'sound="sound/chime.wav"')
    assert dialog.result == {"line": line}

    # Reading a written line fills the form back.
    dialog = mv.MinigameDialog(win, {"line": line + " into calm"})
    assert dialog.game == "heartbeat" and dialog.skip_var.get()
    assert [dialog.vars[n].get() for n in ("beats", "window", "meter", "sound", "into")] == [
        "8", "wide", "composure", "sound/chime.wav", "calm"]
    assert dialog.pickers["sound"].value == "sound/chime.wav"
    dialog.set("sound", "")                                          # empty writes nothing
    assert dialog.pickers["sound"].value is None
    dialog._pick(0)
    assert dialog.result == {
        "line": 'minigame heartbeat skippable window="wide" meter="composure" into calm'}
