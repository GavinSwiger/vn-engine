"""F35-S3: the music room in Studio (``specs/F35-music-room/SPEC.md`` §4, step 3;
AC-F35-11 to 13).

One test per AC. AC-F35-11 is the pure model (``declarations``, ``declplan.plan_move``);
AC-F35-12 drives a copy of the F47 sample game (``files.new_game``) with more music files,
the way an author does: + Add track…, the form's fields, ▲▼, ▶, Preview, Delete and the
Sounds ▸ Music switch (the helper and the game runner are faked); AC-F35-13 the settings
pages."""

import shutil
from pathlib import Path

import pytest

from engine.core.config_schema import SECTIONS, config_fields
from engine.tools.editor import dbextras, declplan, files
from engine.tools.editor import declarations as dec
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor.forms import missing_forms
from engine.tools.editor.preview import preview_argv
from engine.tools.editor.scriptedit import Refuse

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import (  # noqa: E402,F401
    helper, open_database, text_of)
from tests.tools.editor.test_studio_gallery import add_line, commit, label_texts  # noqa: E402
from tests.tools.editor.test_studio_playbar import fake_game  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

DB_REF = declplan.DATABASE_REF
MAIN_REF = "script/main.vns"
FORMS = ('lock track main_theme "Main Theme" file "music/main_theme.ogg" open',
         'lock track festival "Festival Night" file "music/festival.ogg"',
         'lock track credits "Paper Lanterns" file "music/credits.ogg" until true, good')


def music_game(tmp_path: Path) -> Path:
    """The sample story with ``festival_night.wav`` and ``credits.wav`` next to its
    ``lantern_walk.wav`` (which ``label start`` plays)."""
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    music = game / "audio" / "music"
    for name in ("festival_night", "credits"):
        shutil.copy(music / "lantern_walk.wav", music / f"{name}.wav")
    return game


def track_lines(ed, ref: str = DB_REF) -> list[str]:
    return [line for line in text_of(ed, ref).split("\n") if line.startswith("lock track")]


def test_ac_f35_11_declarations_and_plan_move():
    # The three rule forms read and write back byte-exact.
    texts = {DB_REF: "\n".join(FORMS) + "\n"}
    decls = [d for d in dec.scan(texts) if d.kind == dec.TRACK]
    assert [d.values for d in decls] == [
        {"title": "Main Theme", "file": "music/main_theme.ogg", "open": True, "until": ()},
        {"title": "Festival Night", "file": "music/festival.ogg", "open": False, "until": ()},
        {"title": "Paper Lanterns", "file": "music/credits.ogg", "open": False,
         "until": ("true", "good")}]
    assert [dec.track_line(d.name, d.values) for d in decls] == list(FORMS)
    assert dec.track_title("music/festival_night.ogg") == "Festival Night"
    # Shapes the form can't edit stay read-only (Edit as script).
    for odd in ('lock track a "A" file "music/a.ogg" open until good',
                'lock track a "A" file "music/a.ogg" loud', 'lock track a "{b}A" file "x.ogg"'):
        assert dec.scan({DB_REF: odd})[0].values is None, odd
    # A new track, then plan_move swaps two declarations' lines (one undo step).
    plan = declplan.plan_new(dec.TRACK, "festival", decls[1].values, {DB_REF: "", MAIN_REF: ""})
    assert isinstance(plan, declplan.DeclPlan)
    moved = declplan.plan_move(decls[2], decls[1], texts, across=dbextras.ACROSS_FILES)
    assert isinstance(moved, declplan.DeclPlan) and len(moved.plan.files) == 1
    edit = moved.plan.files[0].edits[0]
    assert (edit.first, edit.last, edit.lines) == (2, 3, (FORMS[2], FORMS[1]))
    # ... and refuses across files with the music room's own words.
    other = dec.scan({MAIN_REF: FORMS[0]})[0]
    refused = declplan.plan_move(decls[1], other, {**texts, MAIN_REF: FORMS[0]},
                                 across=dbextras.ACROSS_FILES)
    assert refused == Refuse("This track is declared in another file; move it there.")


@pytest.mark.tk
def test_ac_f35_12_database_music_room(studio, tmp_path, helper, monkeypatch):
    game = music_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    db = open_database(ed, "music_room")
    # Empty: the words, + Add track… and the form's explanation.
    assert db.counts()["music_room"] == 0
    assert db.empty.title.cget("text") == "No tracks yet"
    assert db.new_button.cget("text") == "+ Add track…"
    assert dbextras.ABOUT_MUSIC == ("The music room lets players listen to your soundtrack "
                                    "from the title screen's Extras. Click + Add track… to "
                                    "list a music file.")
    assert dbextras.ABOUT_MUSIC in label_texts(db.body)

    # + Add track…: the picker offers the music files; the §4 line, title from the file name.
    offered = []

    def pick(parent, music, play, playing):
        offered.append(list(music))
        return ["music/festival_night.wav"]
    monkeypatch.setattr(dbextras, "pick_music", pick)
    db.new_entry()
    assert offered == [["music/credits.wav", "music/festival_night.wav",
                        "music/lantern_walk.wav"]]
    assert track_lines(ed) == [
        'lock track festival_night "Festival Night" file "music/festival_night.wav"']
    assert db.selected_row().iid == "u:festival_night"
    db.add_track_files(["music/lantern_walk.wav"])
    assert track_lines(ed)[1] == ('lock track lantern_walk "Lantern Walk" file '
                                  '"music/lantern_walk.wav"')
    assert [r.text for r in db.rows["music_room"]] == ["1.  Festival Night", "2.  Lantern Walk"]
    assert ed.win.files[DB_REF].widget.edit("canundo")

    # Title, rule and endings.
    db.select("u:festival_night")
    commit(db.form.fields["title"], "Festival Night!")
    assert track_lines(ed)[0] == ('lock track festival_night "Festival Night!" file '
                                  '"music/festival_night.wav"')
    db.form.fields["rule"]["open"].invoke()
    assert track_lines(ed)[0].endswith('"music/festival_night.wav" open')
    db.form.fields["rule"]["until"].invoke()                  # nothing yet: tick endings
    assert track_lines(ed)[0].endswith(" open")
    ticks = db.form.fields["until"]
    assert set(ticks) == {"lantern", "next_year"}
    assert str(ticks["lantern"].check.cget("state")) == "normal"
    ticks["lantern"].check.invoke()
    assert track_lines(ed)[0].endswith('"music/festival_night.wav" until lantern')
    db.form.fields["until"]["next_year"].check.invoke()
    assert track_lines(ed)[0].endswith(" until lantern, next_year")
    assert db.selected_row().detail == "after 2 endings"
    db.form.fields["until"]["lantern"].check.invoke()
    db.form.fields["until"]["next_year"].check.invoke()       # the last one: the default rule
    assert track_lines(ed)[0].endswith('file "music/festival_night.wav"')
    assert db.form.fields["rule_var"].get() == "heard"

    # ▶ plays the track's file through the helper; ■ stops it.
    picker = db.form.fields["file"]
    picker.play_button.invoke()
    assert helper[0].sent[-1] == ("play", "audio/music/festival_night.wav")
    assert picker.play_button.cget("text") == "■ Stop"
    picker.play_button.invoke()
    assert helper[0].sent[-1] == ("stop",)
    picker.pick("music/credits.wav")                          # File: another music file
    assert 'file "music/credits.wav"' in track_lines(ed)[0]

    # ▲▼ swap the lines; the top one can't go up.
    up, down = db.music_moves
    assert str(up.cget("state")) == "disabled" and str(down.cget("state")) == "normal"
    down.invoke()
    assert [line.split()[2] for line in track_lines(ed)] == ["lantern_walk", "festival_night"]
    assert db.selected_row().iid == "u:festival_night" and db.selected_row().text[:2] == "2."
    up.invoke()
    assert [line.split()[2] for line in track_lines(ed)] == ["festival_night", "lantern_walk"]
    # A neighbour in another file: disabled, with the hint.
    add_line(ed, MAIN_REF, "label start:", "")
    text = win.files[MAIN_REF].widget
    text.insert("1.0", 'lock track zz "Zz" file "music/credits.wav" open\n')
    db.refresh()
    db.select("u:zz")
    assert db.music_note.cget("text") == dbextras.ACROSS_FILES
    assert str(db.music_moves[1].cget("state")) == "disabled"
    text.delete("1.0", "2.0")
    db.refresh()

    # ▶ Preview the music room: run --extras music_room through the Play bar.
    runner = fake_game(win)
    monkeypatch.setattr(dbextras, "preview_ready", lambda: True)
    db.select("u:festival_night")
    db.music_preview.invoke()
    assert runner.argvs == [preview_argv(game, None, [], extra=("--extras", "music_room"))]

    # Delete asks; the file stays.
    ed.answers.append(1)                                      # Cancel
    db.form.fields["delete"].invoke()
    assert ed.dialogs[-1][:3] == (
        "ask", 'Remove "Festival Night!" from the music room? The music file stays.',
        ("Remove", "Cancel"))
    assert len(track_lines(ed)) == 2
    ed.answers.append(0)
    db.delete_selected()
    assert [line.split()[2] for line in track_lines(ed)] == ["lantern_walk"]
    assert (game / "audio" / "music" / "credits.wav").is_file()

    # Sounds ▸ Music: the switch, the title and both buttons.
    db.select_category("sound")
    db.select("s:music/lantern_walk.wav")
    f = db.form.fields
    assert f["room"].value is True
    commit(f["room_title"], "Lanterns")
    assert track_lines(ed) == [
        'lock track lantern_walk "Lanterns" file "music/lantern_walk.wav"']
    db.form.fields["room_go"].invoke()                        # Open in Music room
    assert db.category == "music_room" and db.selected_row().iid == "u:lantern_walk"
    db.select_category("sound")
    db.select("s:music/festival_night.wav")
    assert db.form.fields["room"].value is False and "room_title" not in db.form.fields
    db.form.fields["room"].check.invoke()                     # Add to music room
    assert track_lines(ed)[-1] == ('lock track festival_night "Festival Night" file '
                                   '"music/festival_night.wav"')
    assert db.category == "sound" and db.selected_row().iid == "s:music/festival_night.wav"
    db.form.fields["room"].check.invoke()                     # off: taken out, no question
    assert len(track_lines(ed)) == 1
    db.select("s:sound/chime.wav")
    assert "room" not in db.form.fields                       # only music files


def test_ac_f35_13_words_page_and_registries():
    words = config_fields(SECTIONS["words"])
    want = [k for k in sm.MUSIC_ROOM_WORDS if k in words]
    assert len(sm.MUSIC_ROOM_WORDS) == 9
    for page in ("words", "extras"):
        shown = [f.key for s in sm.page(page).sections
                 if s.title in ("Music room", "Music room words") for f in s.fields]
        assert shown == want, page
    for key in sm.all_keys():                                  # Settings key coverage
        assert key in sm.fields_by_path() or sm.text_only(key) or sm.on_looks_page(key), key
    assert missing_forms() == []
