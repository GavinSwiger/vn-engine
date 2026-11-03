"""F37-S3: achievements in Studio (``specs/F37-achievements/SPEC.md`` §4; AC-F37-11 to 13).

One test per AC. AC-F37-11 is the pure model (``declarations`` reads and writes every §3
shape byte for byte; the ``when`` text goes through ``conditions.read``/``write``). The Tk
test drives a copy of the F47 sample game (``files.new_game``: the Yes-No variable
``sent_lantern``, endings ``lantern`` and ``next_year``) the way an author does: + New
achievement, the form's fields, the condition builder on and off, ▲▼, ▶ Preview, the hints,
Delete refused while an Unlock achievement line names it. AC-F37-13 is the form and
settings registries."""

from pathlib import Path

import pytest

from engine.core.config_schema import config_fields, section_class
from engine.script.achievements import LABEL_DOCS
from engine.tools.editor import conditions as C
from engine.tools.editor import dbachievements as dba
from engine.tools.editor import declplan, files, formdialogs, forms
from engine.tools.editor import declarations as dec
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor.forms import form_by_key, form_for_doc, missing_forms, rows
from engine.tools.editor.preview import preview_argv
from engine.tools.editor.scenes import parse_chunk

DB_REF = declplan.DATABASE_REF
MAIN_REF = "script/main.vns"

SHAPES = (
    'lock achievement first_steps "First Steps"',
    'lock achievement first_steps "First Steps" "Finish the prologue."',
    'lock achievement first_steps "First Steps" "Finish the prologue." image achievements '
    'first_steps',
    'lock achievement garden "Secret Garden" "Find the hidden garden." hidden',
    'lock achievement garden "Secret Garden" image bg river_dusk hidden',
    'lock achievement completionist "Completionist" "See every ending." when "good" in '
    'persistent.endings and "true" in persistent.endings',
    'lock achievement rich "Rich {{and} Famous" hidden when coins >= 10',
    'lock achievement odd "Odd" when len(codex.tips) > 2',
)


def test_ac_f37_11_declarations_read_and_write_every_shape():
    for line in SHAPES:
        found = dec.scan({DB_REF: line})
        assert len(found) == 1 and found[0].kind == dec.ACHIEVEMENT, line
        decl = found[0]
        assert decl.values is not None, line
        assert set(decl.values) == set(dec.ACHIEVEMENT_KEYS)
        assert dec.lines_for(dec.ACHIEVEMENT, decl.name, decl.values) == (line,)  # byte-exact
    rich = dec.scan({DB_REF: SHAPES[6]})[0].values
    assert rich == {"title": "Rich {and} Famous", "description": "", "image": None,
                    "hidden": True, "when": "coins >= 10"}
    # The condition is the builder's: read, then written back unchanged; a changed row is
    # written in its plain form and the line reads back.
    when = dec.scan({DB_REF: SHAPES[5]})[0].values["when"]
    condition = C.read(when)
    assert condition is not None and [r.kind for r in condition.rows] == [C.ENDING, C.ENDING]
    assert C.write(condition) == when
    more = C.write(C.Condition(rows=(*condition.rows, C.Row(C.PLAYTHROUGH, "", C.GE, "2")),
                               join=C.ALL))
    line = dec.achievement_line("completionist", {**dec.scan({DB_REF: SHAPES[5]})[0].values,
                                                  "when": more})
    assert line.endswith('and persistent.playthrough >= 2')
    assert dec.scan({DB_REF: line})[0].values["when"] == more
    assert C.read(dec.scan({DB_REF: SHAPES[7]})[0].values["when"]) is None   # script only
    # Shapes the form can't edit read only (Edit as script); bad values aren't written.
    for line in ('lock achievement x "X" \\\n    hidden', 'lock achievement x "X" when',
                 'lock achievement x "X" hidden "late"'):
        assert [(d.name, d.values) for d in dec.scan({DB_REF: line})] == [("x", None)], line
    for bad in ({"title": ""}, {"title": "x" * 61}, {"description": "y" * 201},
                {"when": "coins >="}, {"when": "a\nb"}, {"image": "Bad Name!"}):
        values = {"title": "T", "description": "", "image": None, "hidden": False,
                  "when": None, **bad}
        with pytest.raises(ValueError):
            dec.achievement_line("t", values)
    # Uses: the unlock achievement lines in labels; a new name is unique among achievements.
    text = "label a:\n    unlock achievement first_steps  # here\n    unlock achievement b\n"
    assert dec.achievement_uses({MAIN_REF: text}) == (
        ("first_steps", MAIN_REF, 2), ("b", MAIN_REF, 3))
    taken = dec.taken_names(dec.scan({DB_REF: SHAPES[0]}), dec.ACHIEVEMENT)
    assert dec.script_name("First Steps", taken, dec.ACHIEVEMENT) == "first_steps_2"
    assert declplan.KIND_WORDS[dec.ACHIEVEMENT] == "achievement"


tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import open_database, text_of  # noqa: E402
from tests.tools.editor.test_studio_gallery import add_line, commit, label_texts  # noqa: E402
from tests.tools.editor.test_studio_playbar import fake_game  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401


def sample(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    return game


def achievement_lines(ed, ref: str = DB_REF) -> list[str]:
    return [line for line in text_of(ed, ref).split("\n")
            if line.startswith("lock achievement")]


def pick(box, value: str) -> None:
    """Choose ``value`` in a builder drop-down, as a click does."""
    box.set(value)
    box.event_generate("<<ComboboxSelected>>")


@pytest.mark.tk
def test_ac_f37_12_database_achievements(studio, tmp_path, monkeypatch):
    game = sample(tmp_path)
    ed = studio(game, mapped=True)
    runner = fake_game(ed.win)
    db = open_database(ed, "achievement")
    # Empty: after Scene replays; its words, + New achievement and the form's explanation.
    keys = list(db.cat_tree.get_children())
    assert keys[keys.index("replay") + 1] == "achievement"
    assert db.cat_tree.item("achievement", "text") == "Achievements"
    assert db.empty.title.cget("text") == "No achievements yet"
    assert db.new_button.cget("text") == "+ New achievement"
    assert dba.ABOUT_ACHIEVEMENTS in label_texts(db.body)

    # + New achievement: asks the name shown; the script name is made from it.
    ed.answers.append("First Steps")
    db.new_entry()
    assert ed.dialogs[-1][:4] == ("text", "Name shown:", "", None)
    assert achievement_lines(ed) == ['lock achievement first_steps "First Steps"']
    assert db.selected_row().iid == "a:first_steps" and db.counts()["achievement"] == 1
    assert ed.win.files[DB_REF].widget.edit("canundo")
    f = db.form.fields
    shown = label_texts(db.body)
    for hint in (dba.ICON_HINT, dba.NO_LINE, dba.HOOK_HINT, dba.NAME_KEPT,
                 "In the script: unlock achievement first_steps", "Not used yet"):
        assert hint in shown, hint

    # Fields: name shown, description, icon, Hidden (one line each time).
    commit(f["title"], "First Steps!")
    commit(f["description"], "Finish the prologue.")
    assert achievement_lines(ed) == [
        'lock achievement first_steps "First Steps!" "Finish the prologue."']
    commit(f["title"], "")                               # refused: the old one comes back
    assert f["title"].var.get() == "First Steps!"
    assert f["icon"].label_of(None) == "(no icon)"
    f["icon"].pick("bg river_dusk")
    f = db.form.fields
    f["hidden"].check.invoke()
    assert achievement_lines(ed) == [
        'lock achievement first_steps "First Steps!" "Finish the prologue." image '
        'bg river_dusk hidden']
    assert db.selected_row().detail == "hidden"

    # Automatically, when: its first check is the story's first ending, written at once.
    f["unlocked"]["auto"].invoke()
    ed.root.update()
    builder = db.form.fields["when"]
    assert builder.frame.winfo_ismapped() and len(builder.checks) == 1
    assert achievement_lines(ed)[0].endswith('hidden when "lantern" in persistent.endings')
    assert db.selected_row().detail == "hidden · auto"
    assert dba.NO_LINE not in label_texts(db.body)
    # A check that isn't complete isn't written: a variable needs its value.
    builder = db.form.fields["when"]
    check = builder.checks[0]
    pick(check.kind_box, "Variable")
    assert check.name.get() == "sent_lantern"
    assert achievement_lines(ed)[0].endswith('when "lantern" in persistent.endings')
    pick(check.value_box, "yes")                         # sent_lantern is yes
    assert achievement_lines(ed)[0].endswith("hidden when sent_lantern")
    pick(check.kind_box, "Ending seen")                  # its first ending, "was seen"
    assert achievement_lines(ed)[0].endswith('when "lantern" in persistent.endings')
    builder.add()                                        # a second check: All of
    pick(builder.checks[1].kind_box, "Ending seen")
    pick(builder.checks[1].name_box, "next_year")
    assert achievement_lines(ed)[0].endswith(
        'when "lantern" in persistent.endings and "next_year" in persistent.endings')
    assert builder.frame.winfo_exists()                  # edited in place, not rebuilt
    pick(builder.join_box, "Any of")
    assert achievement_lines(ed)[0].endswith(
        'when "lantern" in persistent.endings or "next_year" in persistent.endings')
    builder.remove(builder.checks[0])
    assert achievement_lines(ed)[0].endswith('when "next_year" in persistent.endings')
    builder.remove(builder.checks[0])                    # no checks: not written, says why
    assert db.form.fields["when_problem"].cget("text") == dba.NEEDS_CHECK
    assert achievement_lines(ed)[0].endswith('when "next_year" in persistent.endings')
    # Undo puts the old line back; the builder shows it.
    ed.win.files[DB_REF].widget.edit_undo()
    db.refresh()
    assert achievement_lines(ed)[0].endswith(
        'when "lantern" in persistent.endings or "next_year" in persistent.endings')
    assert len(db.form.fields["when"].checks) == 2
    # A condition the builder can't show: Written as script, kept; a bad one isn't written.
    widget = ed.win.files[DB_REF].widget
    at = widget.search(" when ", "1.0")
    widget.delete(at, f"{at} lineend")
    widget.insert(at, " when len(codex.tips) > 2")
    db.refresh()
    builder = db.form.fields["when"]
    assert builder.scripted and "Written as script" in label_texts(builder.frame)
    builder.var.set("len(codex.tips) >")
    builder.script_entry.event_generate("<FocusOut>")
    assert db.form.fields["when_problem"].cget("text") == dba.BAD_SCRIPT
    assert achievement_lines(ed)[0].endswith("when len(codex.tips) > 2")
    builder.var.set("len(codex.tips) > 3")
    builder.script_entry.event_generate("<FocusOut>")
    assert achievement_lines(ed)[0].endswith("when len(codex.tips) > 3")
    # By a line: when … goes.
    db.form.fields["unlocked"]["line"].invoke()
    assert achievement_lines(ed) == [
        'lock achievement first_steps "First Steps!" "Finish the prologue." image '
        'bg river_dusk hidden']
    ed.root.update()
    assert not db.form.fields["when_card"].winfo_ismapped()

    # ▲▼ reorder the page.
    db.add_achievement("Secret Garden")
    up, down = db.achievement_moves
    assert (str(up.cget("state")), str(down.cget("state"))) == ("normal", "disabled")
    up.invoke()
    assert [line.split()[2] for line in achievement_lines(ed)] == ["secret_garden",
                                                                   "first_steps"]
    assert db.selected_row().iid == "a:secret_garden" and db.selected_row().text.startswith("1.")
    db.select("a:secret_garden")
    db.achievement_moves[1].invoke()
    assert [line.split()[2] for line in achievement_lines(ed)] == ["first_steps",
                                                                   "secret_garden"]

    # ▶ Preview achievements: run --extras achievements through the Play bar.
    monkeypatch.setattr(dba, "preview_ready", lambda: False)
    db.refresh()
    assert str(db.achievement_preview.cget("state")) == "disabled"
    assert db.achievement_preview_tip.text.endswith(dba.NOT_YET)
    monkeypatch.setattr(dba, "preview_ready", lambda: True)
    db.refresh()
    db.achievement_preview.invoke()
    assert runner.argvs[-1] == preview_argv(game, None, [], extra=("--extras", "achievements"))

    # Events ▸ Unlock ▸ Achievement offers the declared ones (none: where to make them).
    story = ed.win.story
    unlock = form_by_key("unlock")
    start = {f.key: "" for f in unlock.fields} | {"what": "achievement"}
    dialog = formdialogs.FormDialog(ed.root, unlock, start, names={},
                                    assets=story.form_assets())
    assert list(dialog.names["achievement"].names) == ["first_steps", "secret_garden"]
    dialog._pick(1)
    empty = formdialogs.FormDialog(ed.root, unlock, start, names={}, assets=None)
    assert empty.hints()["achievement"] == "Make achievements in Database ▸ Achievements."
    empty._pick(1)

    # Delete is refused while an Unlock achievement line names it.
    add_line(ed, MAIN_REF, "    jump bridge", "    unlock achievement first_steps")
    db.refresh()
    db.select("a:first_steps")
    assert "Used in 1 line" in label_texts(db.body)
    assert dba.NO_LINE not in label_texts(db.body)
    ed.answers.append(0)                                 # Show uses
    db.form.fields["delete"].invoke()
    assert ed.dialogs[-1][:3] == (
        "ask", "“First Steps!” is given by 1 line (Unlock achievement), so it can't be "
        "deleted yet.", ("Show uses", "OK"))
    assert any(p.startswith("script/main.vns:") and "unlock achievement first_steps" in p
               for p in ed.win.panel_paragraphs())
    assert len(achievement_lines(ed)) == 2
    db.rename_selected()                                 # its name keys players' records
    assert ed.dialogs[-1][0] == "ask"
    widget = ed.win.files[MAIN_REF].widget
    at = widget.search("    unlock achievement first_steps", "1.0")
    widget.delete(at, f"{at} lineend +1c")
    db.refresh()
    ed.answers.append(1)                                 # Cancel
    db.delete_selected()
    assert ed.dialogs[-1][1].startswith("Delete the achievement “First Steps!”?")
    assert len(achievement_lines(ed)) == 2
    ed.answers.append(0)
    db.delete_selected()
    assert achievement_lines(ed) == ['lock achievement secret_garden "Secret Garden"']


def _rows(*body: str):
    text = "label t:\n" + "".join(f"    {line}\n" for line in body)
    read = parse_chunk("script/t.vns", text)
    assert read is not None and read.error is None, (body, read)
    return rows(read, text.split("\n")[:-1])


def test_ac_f37_13_unlock_form_and_words_pages():
    lock, unlock = form_by_key("lock"), form_by_key("unlock")
    what = unlock.fields[0]
    assert what.options[-1] == "achievement" and what.shown[-1] == "Achievement"
    assert "achievement" not in lock.fields[0].options        # achievements can't be taken
    field = next(f for f in unlock.fields if f.key == "achievement")
    assert (field.label, field.kind, field.name_kind) == ("Achievement", "name", "achievement")
    got = _rows("unlock achievement first_steps")
    blank = {"route": "", "tip": "", "item": "", "gallery": "", "replay": "", "achievement": ""}
    assert [(r.form, r.values, r.text) for r in got if r.form is not None] == [
        ("unlock", {**blank, "what": "achievement", "achievement": "first_steps"},
         "Unlock achievement  first_steps")]
    assert unlock.write({"what": "achievement", "achievement": " first_steps "}) == (
        "unlock achievement first_steps")
    assert unlock.row_word({"what": "achievement"}) == "Unlock achievement"
    # Insert ▸ Unlock achievement opens the Unlock form (the doc is registered now).
    assert [form_for_doc(doc) for doc in LABEL_DOCS] == [unlock]
    assert LABEL_DOCS[0] in forms.all_docs()
    assert missing_forms() == []

    # Game settings: Extras ▸ Achievement words and Button words ▸ Achievements.
    assert sm.ACHIEVEMENT_WORDS == ("achievements", "achievement_unlocked",
                                    "achievements_progress", "achievement_hidden",
                                    "achievement_hidden_text")
    words = config_fields(section_class("words"))
    want = [k for k in sm.ACHIEVEMENT_WORDS if k in words]
    for key, title in (("extras", "Achievement words"), ("words", "Achievements")):
        shown = [f.key for s in sm.page(key).sections if s.title == title for f in s.fields]
        assert shown == want, key
    for key in sm.ACHIEVEMENT_WORDS:
        assert sm.LABELS[f"words.{key}"]
    for key in sm.all_keys():                                  # Settings key coverage
        assert key in sm.fields_by_path() or sm.text_only(key) or sm.on_looks_page(key), key
