"""The statement forms' pickers in a real Studio window (F47 W5: AC-F47-13, AC-F47-22).
Tk; the helper child is faked (``test_studio_database.helper``)."""

from pathlib import Path

import pytest

from engine.tools.editor import formdialogs, forms
from engine.tools.editor.fieldwidgets import PLAY, STOP, THUMB_PX

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import (  # noqa: E402,F401,I001
    apply_check, helper, open_database, sample_game)
from tests.tools.editor.test_studio_storyedit import events_on, row_of  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk


def form(ed, key: str, values: dict) -> formdialogs.FormDialog:
    """``key``'s dialog as the Events tab opens it: the window's names and assets."""
    story = ed.win.story
    start = {f.key: "" for f in forms.form_by_key(key).fields} | values
    return formdialogs.FormDialog(ed.root, forms.form_by_key(key), start, names=story.names(),
                                  assets=story.form_assets())


def open_from_events(ed, monkeypatch, text: str) -> formdialogs.FormDialog:
    """Edit the Events row ``text`` of scene ``start``; the dialog Studio opened (kept open
    until the test closes it)."""
    got: dict = {}

    def edit(parent, form_, start, *, names, ok="OK", assets=None):
        got["dialog"] = formdialogs.FormDialog(parent, form_, start, names=names, ok=ok,
                                               assets=assets)
        return None

    monkeypatch.setattr(formdialogs, "edit_form", edit)
    apply_check(ed, ed.win.paths.root)
    ed.press(ed.text, "<Control-Key-2>")
    events_on(ed, "start")
    ed.win.story.edit(row_of(ed, text))
    return got["dialog"]


def test_ac_f47_13_music_sound_and_blip_pickers_have_play(studio, tmp_path: Path, helper,
                                                          monkeypatch):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    music = open_from_events(ed, monkeypatch, "Music  music/lantern_walk.wav · fade in 1 s")
    button = music.play_buttons["file"]
    assert str(button.cget("text")) == PLAY
    button.invoke()                                     # ▶ plays it through the helper
    sent = helper[0].sent
    assert sent[-1] == ("play", "audio/music/lantern_walk.wav")
    assert str(button.cget("text")) == STOP
    button.invoke()                                     # ■ stops it
    assert sent[-1] == ("stop",) and str(button.cget("text")) == PLAY
    music.vars["file"].set("")                          # nothing to play: ▶ is off
    assert "disabled" in button.state()
    music.vars["file"].set("music/lantern_walk.wav")
    button.invoke()
    music._pick(1)                                      # closing the form stops the sound
    assert sent[-1] == ("stop",) and ed.win.helper_hub.playing is None

    sound = form(ed, "sound", {"file": "sound/chime.wav"})
    sound.play_buttons["file"].invoke()
    assert sent[-1] == ("play", "audio/sound/chime.wav")
    sound._pick(0)
    assert sent[-1] == ("stop",) and sound.result == {"file": "sound/chime.wav"}

    db = open_database(ed, "character")                 # the voice blip (Database, W2)
    db.select("c:hana")
    assert db.form.fields["blip"].play_button is not None


def test_ac_f47_22_look_pickers_filtered_with_thumbnails(studio, tmp_path: Path, helper,
                                                         monkeypatch):
    game = sample_game(tmp_path)
    ed = studio(game, mapped=True)
    side = round(THUMB_PX * formdialogs.scale_of(ed.root))

    say = open_from_events(ed, monkeypatch, "Say  hana: You came! Daichi said you'd get "
                                            "lost at least twice.")
    looks = say.names["look"]
    assert looks.names == ["happy", "sad"]              # Hana's looks only
    assert say.thumb_shows["look"] is None              # no look: no picture of "hana"
    say.vars["look"].set("happy")
    assert say.thumb_shows["look"] == "hana happy"
    image = say.thumbs["look"].image                    # type: ignore[attr-defined]
    assert image.width() <= side and image.height() <= side
    dot, shown = say.dots["speaker"]
    assert str(shown.cget("text")) == "Hana" and str(dot.cget("image"))
    say.vars["speaker"].set("daichi")                   # another speaker: their looks
    assert looks.names == ["grin", "smile"] and say.thumb_shows["look"] is None
    assert say.hints()["look"] == formdialogs.NOT_FOUND
    say.vars["look"].set("grin")
    assert say.thumb_shows["look"] == "daichi grin" and say.hints()["look"] == ""
    assert str(say.dots["speaker"][1].cget("text")) == "Daichi"
    say._pick(1)

    show = form(ed, "show", {"character": "daichi", "look": "smile"})
    assert show.names["look"].names == ["grin", "smile"]
    assert show.thumb_shows["look"] == "daichi smile"
    assert str(show.dots["character"][1].cget("text")) == "Daichi"
    show._pick(1)

    scene = form(ed, "scene", {"image": "bg river_dusk"})
    assert scene.names["image"].names[:2] == ["bg bridge_night", "bg river_dusk"]
    assert scene.thumb_shows["image"] == "bg river_dusk"
    scene.vars["image"].set("bg bridge_night")
    assert scene.thumb_shows["image"] == "bg bridge_night"
    scene._pick(1)

    plain = formdialogs.FormDialog(ed.root, forms.form_by_key("say"), {"speaker": "hana"},
                                   names={})           # no assets: F46's form
    assert not plain.thumbs and not plain.dots and "look" not in plain.names
    plain._pick(1)
