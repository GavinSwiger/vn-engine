"""F36-W4: scene replays in Studio (``specs/F36-ending-list/01-design.md`` §7;
``04-technical.md`` W4; AC-F36-29 to 34).

One test per AC. The Tk tests drive a copy of the F47 sample game (``files.new_game``:
scenes ``start`` and ``bridge``, the Yes-No variable ``sent_lantern``, endings ``lantern``
and ``next_year`` in ``bridge``) the way an author does: + New replay…, the form's fields,
the starting values, ◀ ▶, Delete, ▶ Play replay (the scene picker and the game runner are
faked). AC-F36-32 and 33 are the pure form and settings registries."""

from pathlib import Path

import pytest

from engine.core.config_schema import config_fields, section_class
from engine.script.replay import LABEL_DOCS
from engine.tools.editor import dbreplays, declplan, files, forms
from engine.tools.editor import declarations as dec
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor.forms import form_by_key, form_for_doc, missing_forms, rows
from engine.tools.editor.preview import preview_argv
from engine.tools.editor.scenes import parse_chunk

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import open_database, text_of  # noqa: E402
from tests.tools.editor.test_studio_gallery import add_line, commit, label_texts  # noqa: E402
from tests.tools.editor.test_studio_playbar import fake_game  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

DB_REF = declplan.DATABASE_REF
MAIN_REF = "script/main.vns"


def sample(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    return game


def replay_lines(ed, ref: str = DB_REF) -> list[str]:
    """The ``lock replay`` lines of ``ref`` with their indented starting values."""
    out: list[str] = []
    for line in text_of(ed, ref).split("\n"):
        if line.startswith("lock replay") or (out and line.startswith("    ")
                                              and out[-1].startswith(("lock replay", "    "))):
            out.append(line)
        elif out and out[-1].startswith("    "):
            out.append("")                         # a block ended: keep blocks apart
    return [line for line in out if line]


def pick_scenes(monkeypatch, *answers: str | None) -> list[list[str]]:
    offered: list[list[str]] = []
    queue = list(answers)

    def pick(parent, names, **kw):
        offered.append(list(names))
        assert kw == {"title": "New scene replay", "ok": "Add"}
        return queue.pop(0)
    monkeypatch.setattr(dbreplays, "pick_scene", pick)
    return offered


@pytest.mark.tk
def test_ac_f36_29_new_replay_title_picture_and_ends(studio, tmp_path, monkeypatch):
    game = sample(tmp_path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "replay")
    # Empty: after Endings & routes, its words, + New replay… and the form's explanation.
    keys = list(db.cat_tree.get_children())
    assert keys[keys.index("ending") + 1] == "replay"
    assert db.cat_tree.item("replay", "text") == "Scene replays"
    assert db.empty.title.cget("text") == "No scene replays yet"
    assert db.empty.hint.cget("text") == "Add scenes players can watch again."
    assert db.new_button.cget("text") == "+ New replay…"
    assert dbreplays.ABOUT_REPLAYS in label_texts(db.body)

    # + New replay…: the scene picker; the title from the scene's Flowchart title.
    add_line(ed, MAIN_REF, "label bridge:", '    flowchart scene "On the Bridge"')
    offered = pick_scenes(monkeypatch, "bridge", "start")
    db.new_entry()
    assert offered[-1] == ["bridge", "start"]
    assert replay_lines(ed) == ['lock replay bridge "On the Bridge"']
    assert db.selected_row().iid == "w:bridge" and db.counts()["replay"] == 1
    db.new_entry()                                 # else the scene's name in words
    assert offered[-1] == ["start"]                # a scene with a replay isn't offered
    assert replay_lines(ed)[-1] == 'lock replay start "Start"'
    assert [r.text for r in db.rows["replay"]] == ["1.  On the Bridge", "2.  Start"]
    assert ed.win.files[DB_REF].widget.edit("canundo")

    # Title, Picture (first choice: the scene's first background) and Ends.
    db.select("w:bridge")
    f = db.form.fields
    commit(f["title"], "By the River")
    assert replay_lines(ed)[0] == 'lock replay bridge "By the River"'
    assert f["picture"].label_of(None) == "(scene's first background)"
    f["picture"].pick("bg river_dusk")
    assert replay_lines(ed)[0] == 'lock replay bridge "By the River" image bg river_dusk'
    f = db.form.fields
    assert str(f["to"].box.cget("state")) == "disabled"
    f["ends"]["at"].invoke()                       # nothing written until a scene is picked
    assert replay_lines(ed)[0].endswith("image bg river_dusk")
    assert str(f["to"].box.cget("state")) == "readonly"
    assert [c for c, _l in f["to"].choices] == ["start"]          # not the scene itself
    f["to"].pick("start")
    assert replay_lines(ed)[0] == ('lock replay bridge "By the River" image bg river_dusk '
                                   'to start')
    db.form.fields["ends"]["scene"].invoke()
    assert replay_lines(ed)[0].endswith("river_dusk")
    db.form.fields["ends"]["at"].invoke()
    db.form.fields["to"].pick("start")
    # Scene: another one (here the ``to`` scene, which is then dropped).
    db.delete_replay(next(e for e in db.replay_entries() if e.name == "start"),
                     confirm=False)
    db.select("w:bridge")
    db.form.fields["scene"].pick("start")
    assert replay_lines(ed) == ['lock replay start "By the River" image bg river_dusk']
    assert db.selected_row().iid == "w:start"
    db.form.fields["go"].invoke()                  # Go to the scene
    assert ed.win.current_tab() == "editor"


@pytest.mark.tk
def test_ac_f36_30_starting_values(studio, tmp_path, monkeypatch):
    game = sample(tmp_path)
    ed = studio(game, mapped=True)
    add_line(ed, DB_REF, "names a story variable", "default coins = 3")
    add_line(ed, DB_REF, "default coins", 'default player = "Hana"')
    db = open_database(ed, "replay")
    db.add_replay("bridge")
    f = db.form.fields
    assert dbreplays.STARTING_HELP in label_texts(db.body)
    f["add_value"].invoke()                        # the first variable, its own start
    assert replay_lines(ed) == ['lock replay bridge "Bridge":', "    coins = 3"]
    pick, value, _remove = db.form.fields["values"][0]
    assert [c for c, _l in pick.choices] == ["coins", "player", "sent_lantern"]
    commit(value, "lots")                          # a Number: words are refused
    assert replay_lines(ed)[1] == "    coins = 3" and value.var.get() == "3"
    commit(value, "-2.5")
    assert replay_lines(ed)[1] == "    coins = -2.5"
    db.form.fields["add_value"].invoke()
    assert replay_lines(ed)[2] == '    player = "Hana"'
    pick, value, _remove = db.form.fields["values"][1]
    assert [c for c, _l in pick.choices] == ["player", "sent_lantern"]   # not one taken
    pick.pick("sent_lantern")                      # another kind: its own starting value
    assert replay_lines(ed)[2] == "    sent_lantern = False"
    value = db.form.fields["values"][1][1]
    assert [label for _c, label in value.choices] == ["Yes", "No"]       # Yes-No
    value.pick(True)
    assert replay_lines(ed)[2] == "    sent_lantern = True"
    db.form.fields["values"][1][0].pick("player")
    commit(db.form.fields["values"][1][1], 'Hana "Lantern" Sato')         # Text
    assert replay_lines(ed)[2] == '    player = "Hana \\"Lantern\\" Sato"'
    assert dec.scan({DB_REF: text_of(ed, DB_REF)})[-1].values["values"][1] == (
        "player", 'Hana "Lantern" Sato')
    assert str(db.form.fields["add_value"].cget("state")) == "normal"
    db.form.fields["values"][0][2].invoke()        # Remove
    assert replay_lines(ed) == ['lock replay bridge "Bridge":',
                                '    player = "Hana \\"Lantern\\" Sato"']
    db.form.fields["values"][0][2].invoke()        # the last one: the colon goes too
    assert replay_lines(ed) == ['lock replay bridge "Bridge"']
    assert db.form.fields["values"] == []
    assert ed.win.files[DB_REF].widget.edit("canundo")


@pytest.mark.tk
def test_ac_f36_31_move_delete_refused_and_info_line(studio, tmp_path, monkeypatch):
    game = sample(tmp_path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "replay")
    db.add_replay("start")
    db.add_replay("bridge")
    earlier, later = db.replay_moves
    assert (str(earlier.cget("state")), str(later.cget("state"))) == ("normal", "disabled")
    earlier.invoke()                               # ◀ Move earlier
    assert replay_lines(ed) == ['lock replay bridge "Bridge"', 'lock replay start "Start"']
    assert db.selected_row().iid == "w:bridge" and db.selected_row().text.startswith("1.")
    later.invoke()                                 # Move later ▶
    assert replay_lines(ed) == ['lock replay start "Start"', 'lock replay bridge "Bridge"']
    # A neighbour in another file: the button toward it is off, with the hint.
    add_line(ed, MAIN_REF, 'include "database.vns"', 'lock replay zz "Zz"')
    db.refresh()
    db.select("w:start")
    assert db.replay_note.cget("text") == dbreplays.ACROSS_FILES
    assert str(earlier.cget("state")) == "disabled"
    widget = ed.win.files[MAIN_REF].widget
    at = widget.search('lock replay zz', "1.0")
    widget.delete(at, f"{at} lineend +1c")

    # The info line; an Unlock event names the scene: the scene stays, Delete is refused.
    db.refresh()
    db.select("w:bridge")
    assert db.form.fields["info"].cget("text") == (
        "Players unlock this replay the first time they reach the scene.")
    assert dbreplays.NOT_NAMED in label_texts(db.body)
    add_line(ed, MAIN_REF, "    jump bridge", "    unlock replay bridge")
    db.refresh()
    assert "scene" not in db.form.fields and dbreplays.SCENE_LOCKED in label_texts(db.body)
    assert "Named in 1 line" in label_texts(db.body)
    ed.answers.append(0)                           # Show uses
    db.form.fields["delete"].invoke()
    assert ed.dialogs[-1][:3] == (
        "ask", "“Bridge” is named in 1 line (Unlock or Forget scene replay), so it can't be "
        "deleted yet.", ("Show uses", "OK"))
    assert any(p.startswith("script/main.vns:") and "unlock replay bridge" in p
               for p in ed.win.panel_paragraphs())
    assert len(replay_lines(ed)) == 2
    widget = ed.win.files[MAIN_REF].widget
    at = widget.search("    unlock replay bridge", "1.0")
    widget.delete(at, f"{at} lineend +1c")
    db.refresh()
    ed.answers.append(1)                           # Cancel
    db.delete_selected()
    assert ed.dialogs[-1][1].startswith("Delete the scene replay “Bridge”?")
    assert len(replay_lines(ed)) == 2
    ed.answers.append(0)
    db.delete_selected()
    assert replay_lines(ed) == ['lock replay start "Start"']


def _rows(*body: str):
    text = "label t:\n" + "".join(f"    {line}\n" for line in body)
    read = parse_chunk("script/t.vns", text)
    assert read is not None and read.error is None, (body, read)
    return rows(read, text.split("\n")[:-1])


def test_ac_f36_32_lock_unlock_form_scene_replay():
    lock, unlock = form_by_key("lock"), form_by_key("unlock")
    for form in (lock, unlock):
        what = form.fields[0]
        assert "replay" in what.options
        assert what.shown[what.options.index("replay")] == "Scene replay"
        field = next(f for f in form.fields if f.key == "replay")
        assert (field.label, field.kind, field.name_kind) == ("Scene replay", "name", "replay")
    got = _rows("unlock replay river", "lock replay river")
    blank_u = {"route": "", "tip": "", "item": "", "gallery": "", "replay": "",
               "achievement": ""}                   # F37-S3: Unlock achievement
    blank_l = {"route": "", "ending": "", "tip": "", "item": "", "gallery": "", "replay": ""}
    assert [(r.form, r.values, r.text) for r in got if r.form is not None] == [
        ("unlock", {**blank_u, "what": "replay", "replay": "river"},
         "Unlock scene replay  river"),
        ("lock", {**blank_l, "what": "replay", "replay": "river"},
         "Forget scene replay  river")]
    assert unlock.write({"what": "replay", "replay": " river "}) == "unlock replay river"
    assert lock.write({"what": "replay", "replay": "river"}) == "lock replay river"
    # Insert's in-label replay docs open these forms (W1's LABEL_DOCS, now registered).
    assert [form_for_doc(doc) for doc in LABEL_DOCS] == [lock, unlock]
    assert missing_forms() == []
    assert forms.form_by_key("unlock").row_word({"what": "replay"}) == "Unlock scene replay"


def test_ac_f36_33_game_settings_extras_endings_keys():
    extras = next(p for p in sm.PAGES if p.key == "extras")
    rows_ = [(r.path, r.title, r.keys) for r in extras.rows]
    assert ("endings", "Endings list", ("list", "replay")) in rows_
    assert ("words", "Endings and scene replay words", sm.REPLAY_WORDS) in rows_
    assert sm.REPLAY_WORDS == ("endings", "endings_count", "ending_locked", "ending_replay",
                               "replays", "replay_end", "replay_no_saving")
    assert sm.LABELS["endings.list"] == "Show an Endings page in Extras"
    assert sm.LABELS["endings.replay"] == "Let players replay endings they've reached"
    page = sm.page("extras")
    endings = section_class("endings")
    want = [k for k in ("list", "replay") if endings is not None and k in config_fields(endings)]
    assert [f.key for s in page.sections if s.title == "Endings list" for f in s.fields] == want
    words = config_fields(section_class("words"))
    want_words = [k for k in sm.REPLAY_WORDS if k in words]
    for key, title in (("extras", "Endings and scene replay words"),
                       ("words", "Endings and scene replays")):
        shown = [f.key for s in sm.page(key).sections if s.title == title for f in s.fields]
        assert shown == want_words, key
    for key in sm.all_keys():                                  # Settings key coverage
        assert key in sm.fields_by_path() or sm.text_only(key) or sm.on_looks_page(key), key
    assert missing_forms() == []


@pytest.mark.tk
def test_ac_f36_34_play_replay_through_the_play_bar(studio, tmp_path, monkeypatch):
    game = sample(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    runner = fake_game(win)
    db = open_database(ed, "replay")
    db.add_replay("bridge")
    # This engine without --replay: the button is off and says why.
    monkeypatch.setattr(dbreplays, "replay_ready", lambda: False)
    db.refresh()
    play = db.form.fields["play"]
    assert play.cget("text") == "▶ Play replay" and str(play.cget("state")) == "disabled"
    assert db.replay_play_tip.text.endswith(dbreplays.NOT_YET)
    play.invoke()
    assert runner.argvs == []
    # With it: run --replay <scene> through the Play bar (saved first).
    monkeypatch.setattr(dbreplays, "replay_ready", lambda: True)
    db.refresh()
    db.form.fields["play"].invoke()
    assert runner.argvs == [preview_argv(game, None, [], replay="bridge")]
    assert runner.argvs[0][-2:] == ["--replay", "bridge"]
    db.replay_preview.invoke()                     # ▶ Preview Extras
    assert runner.argvs[-1] == preview_argv(game, None, [], extra=("--extras", "replays"))

    # Endings & routes: each ending's ▶ Play replay plays its scene.
    db.select_category("ending")
    db.select("e:lantern")
    assert db.ending_play is not None and db.ending_play.cget("text") == "▶ Play replay"
    db.ending_play.invoke()
    assert runner.argvs[-1] == preview_argv(game, None, [], replay="bridge")
    # ... while [endings] replay is on.
    config = win.record_for("config.toml").widget
    config.insert("end", "\n[endings]\nreplay = false\n")
    db.select("e:next_year")
    assert db.ending_play is None
