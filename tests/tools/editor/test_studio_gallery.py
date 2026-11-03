"""F34-W4: the gallery in Studio (``specs/F34-cg-gallery/01-design.md`` §7; ``04`` W4;
AC-F34-29 to 34).

One test per AC. The Tk ones drive copies of the F47 sample game (``files.new_game``) with
three pictures added under ``images/cg/``, the way an author does: the Pictures form's
switch, the Gallery category's picker, versions and Move buttons, the Lock/Unlock form, the
Extras settings page and ▶ Preview the gallery (the game runner is faked)."""

import shutil
from pathlib import Path

import pytest

from engine.core.config_schema import config_fields, section_class
from engine.script.gallery import LABEL_DOCS
from engine.tools.editor import dbgallery, declplan, files, forms, forms_more
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor.forms import form_by_key, form_for_doc, missing_forms, rows
from engine.tools.editor.preview import preview_argv
from engine.tools.editor.scenes import parse_chunk

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import apply_check, open_database, text_of  # noqa: E402
from tests.tools.editor.test_studio_playbar import fake_game  # noqa: E402
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

DB_REF = declplan.DATABASE_REF
MAIN_REF = "script/main.vns"


def cg_game(tmp_path: Path) -> Path:
    """The sample story with ``cg festival``, ``cg river`` and ``cg river_smile``."""
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    (game / "images" / "cg").mkdir()
    for name in ("festival", "river", "river_smile"):
        shutil.copy(game / "images" / "bg" / "river_dusk.png", game / "images" / "cg" /
                    f"{name}.png")
    return game


def commit(field, text: str) -> None:
    field.var.set(text)
    field._done()


def add_line(ed, ref: str, after: str, line: str) -> None:
    """Type ``line`` into ``ref``'s editor text under the line holding ``after``."""
    widget = ed.win.files[ref].widget if ref in ed.win.files else None
    if widget is None:
        ed.win.open_file(ref)
        widget = ed.win.files[ref].widget
    text = widget.get("1.0", "end-1c").split("\n")
    at = next(i for i, t in enumerate(text, start=1) if after in t)
    widget.insert(f"{at + 1}.0", line + "\n")


def gallery_lines(ed) -> list[str]:
    return [line for line in text_of(ed, DB_REF).split("\n") if line.startswith("lock gallery")]


@pytest.mark.tk
def test_ac_f34_29_pictures_in_the_gallery_switch(studio, tmp_path):
    game = cg_game(tmp_path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "picture")
    db.select("p:images/cg/festival.png")
    switch = db.form.fields["gallery"]
    assert switch.value is False and "gallery_title" not in db.form.fields
    switch.check.invoke()                                     # on: the line, a title made
    assert gallery_lines(ed) == ['lock gallery cg festival "Festival"']
    assert db.selected_row().iid == "p:images/cg/festival.png"
    commit(db.form.fields["gallery_title"], "Festival Night")  # the title rewrites it
    assert gallery_lines(ed) == ['lock gallery cg festival "Festival Night"']
    assert dbgallery_title(db) == "Festival Night"
    db.form.fields["gallery"].check.invoke()                  # off: removed
    assert gallery_lines(ed) == []
    assert ed.win.files[DB_REF].widget.edit("canundo")

    # Off is refused while an Unlock gallery picture line names it.
    db.form.fields["gallery"].check.invoke()
    add_line(ed, MAIN_REF, "label bridge:", "    unlock gallery cg festival")
    db.refresh()
    ed.answers.append(1)                                      # "OK"
    db.form.fields["gallery"].check.invoke()
    assert ed.dialogs[-1][:3] == (
        "ask", "“Festival” is named in 1 line (Lock or Unlock gallery picture), so it can't "
        "be taken out of the gallery yet.", ("Show uses", "OK"))
    assert gallery_lines(ed) == ['lock gallery cg festival "Festival"']
    assert db.form.fields["gallery"].value is True

    # A version shows "Part of “…”" with Go to (its entry in Database ▸ Gallery).
    db.add_to_gallery(["cg river"])
    entry = next(e for e in db.gallery_entries() if e.name == "cg river")
    ed.answers.append(None)
    pick = ["cg river_smile"]
    import engine.tools.editor.dbgallery as module
    old = module.pick_pictures
    module.pick_pictures = lambda *a, **k: pick
    try:
        assert db.add_version(entry)
    finally:
        module.pick_pictures = old
    db.select_category("picture")
    db.select("p:images/cg/river_smile.png")
    assert "gallery" not in db.form.fields
    assert label_texts(db.body).count("Part of “River”") == 1
    db.form.fields["gallery_go"].invoke()
    assert db.category == "gallery" and db.selected_row().iid == "y:cg river"


def dbgallery_title(db) -> str:
    return db.form.fields["gallery_title"].value


def label_texts(frame) -> list[str]:
    out, stack = [], [frame]
    while stack:
        widget = stack.pop()
        stack.extend(widget.winfo_children())
        if widget.winfo_class() == "TLabel":
            out.append(str(widget.cget("text")))
    return out


@pytest.mark.tk
def test_ac_f34_30_gallery_list_add_pictures_and_versions(studio, tmp_path, monkeypatch):
    game = cg_game(tmp_path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "gallery")
    assert db.empty.shown and db.empty.hint.cget("text") == dbgallery.EMPTY_HINT
    assert db.new_button.cget("text") == "+ Add pictures…"
    assert db.gallery_box.winfo_ismapped() and not db.list_tree.winfo_ismapped()

    offered: list = []
    picks = [["cg river", "cg festival"]]
    monkeypatch.setattr(dbgallery, "pick_pictures", lambda parent, items, thumb, **kw: (
        offered.append((list(items), kw.get("multi", True))), picks.pop(0))[1])
    db.new_entry()                                            # + Add pictures… (multi-pick)
    items, multi = offered[-1]
    assert multi and ("cg festival", "cg festival") in items and ("cg river", "cg river") in items
    assert gallery_lines(ed) == ['lock gallery cg river "River"',
                                 'lock gallery cg festival "Festival"']     # in tick order
    assert db.gallery_grid.labels() == ["River", "Festival"]               # gallery order
    assert db.counts()["gallery"] == 2
    assert db.selected_row().iid == "y:cg festival"
    # The picker offers only pictures not in the gallery yet.
    picks.append(None)
    db.add_gallery_pictures()
    assert {n for n, _l in offered[-1][0]} >= {"cg river_smile", "bg river_dusk"}
    assert not {"cg river", "cg festival"} & {n for n, _l in offered[-1][0]}

    # Versions: + Add a version… (one picture), Remove.
    db.select("y:cg river")
    picks.append(["cg river_smile"])
    db.form.fields["add_version"].invoke()
    assert offered[-1][1] is False
    assert text_of(ed, DB_REF).count('lock gallery cg river "River":\n    cg river_smile') == 1
    assert list(db.form.fields["versions"]) == ["cg river_smile"]
    commit(db.form.fields["title"], "By the River")
    assert 'lock gallery cg river "By the River":\n    cg river_smile' in text_of(ed, DB_REF)
    db.form.fields["versions"]["cg river_smile"].invoke()     # Remove
    assert 'lock gallery cg river "By the River"\n' in text_of(ed, DB_REF) + "\n"
    assert db.form.fields["versions"] == {}

    # The Lock/Unlock form's picker offers the gallery's pictures, versions too.
    from engine.tools.editor.formassets import WindowAssets
    picks.append(["cg river_smile"])
    db.form.fields["add_version"].invoke()
    assert list(WindowAssets(ed.win).names("gallery")) == ["cg festival", "cg river",
                                                           "cg river_smile"]

    # The picker itself: clicks tick (in order), Add returns them; Cancel returns None.
    picker = dbgallery.PicturePicker(ed.root, [("a", "A"), ("b", "B"), ("c", "C")],
                                     lambda _n: None, multi=True, title="t", hint="h")
    picker.tick("c")
    picker.tick("a")
    picker.tick("c")
    picker.tick("b")
    picker._pick(0)
    assert picker.result == ["a", "b"]


@pytest.mark.tk
def test_ac_f34_31_move_earlier_later_across_files_and_info_line(studio, tmp_path):
    game = cg_game(tmp_path)
    ed = studio(game, mapped=True)
    db = open_database(ed, "gallery")
    db.add_to_gallery(["cg festival", "cg river"])
    db.select("y:cg river")
    earlier, later = db.move_buttons
    assert (str(earlier.cget("state")), str(later.cget("state"))) == ("normal", "disabled")
    earlier.invoke()                                          # ◀ Move earlier
    assert gallery_lines(ed) == ['lock gallery cg river "River"',
                                 'lock gallery cg festival "Festival"']
    assert db.gallery_grid.labels() == ["River", "Festival"]
    assert db.selected_row().iid == "y:cg river"
    assert (str(earlier.cget("state")), str(later.cget("state"))) == ("disabled", "normal")
    later.invoke()                                            # Move later ▶
    assert gallery_lines(ed) == ['lock gallery cg festival "Festival"',
                                 'lock gallery cg river "River"']
    assert ed.win.files[DB_REF].widget.edit("canundo")

    # An entry in another file: the buttons toward it are off, with the hint.
    add_line(ed, MAIN_REF, 'include "database.vns"', 'lock gallery cg river_smile "Smile"')
    db.refresh()
    assert [e.name for e in db.gallery_entries()] == ["cg river_smile", "cg festival",
                                                      "cg river"]
    db.select("y:cg festival")
    assert (str(earlier.cget("state")), str(later.cget("state"))) == ("disabled", "normal")
    assert db.move_note.cget("text") == (
        "These pictures are in different script files. Move their lines in the text to "
        "reorder them.")

    # W226's info line: a picture no line shows (after a check), else the usual line.
    add_line(ed, MAIN_REF, "label bridge:", "    scene cg festival")
    for ref in (DB_REF, MAIN_REF):
        assert ed.win.save_record(ed.win.files[ref])
    apply_check(ed, game)
    db.select("y:cg river")
    assert db.form.fields["info"].cget("text") == "⚠ " + dbgallery.NEVER_SHOWN
    db.select("y:cg festival")
    assert db.form.fields["info"].cget("text") == dbgallery.INFO
    assert "Shown in 1 line" in label_texts(db.body)


def _rows(*body: str):
    text = "label t:\n" + "".join(f"    {line}\n" for line in body)
    read = parse_chunk("script/t.vns", text)
    assert read is not None and read.error is None, (body, read)
    return rows(read, text.split("\n")[:-1])


def test_ac_f34_32_lock_unlock_form_gallery_picture():
    lock, unlock = form_by_key("lock"), form_by_key("unlock")
    for form in (lock, unlock):
        field = next(f for f in form.fields if f.key == "gallery")
        assert (field.label, field.kind, field.name_kind) == ("Gallery picture", "name",
                                                              "gallery")
        assert "gallery" in form.fields[0].options
    got = _rows("unlock gallery cg festival", "lock gallery cg river_smile")
    blank_u = {"route": "", "tip": "", "item": "", "gallery": ""}
    blank_l = {**blank_u, "ending": ""}
    assert [(r.form, r.values, r.text) for r in got if r.form is not None] == [
        ("unlock", {**blank_u, "what": "gallery", "gallery": "cg festival"},
         "Unlock gallery picture  cg festival"),
        ("lock", {**blank_l, "what": "gallery", "gallery": "cg river_smile"},
         "Forget gallery picture  cg river_smile")]
    assert unlock.write({"what": "gallery", "gallery": " cg  festival "}) == \
        "unlock gallery cg festival"
    assert lock.write({"what": "gallery", "gallery": "cg river_smile"}) == \
        "lock gallery cg river_smile"
    # Insert's in-label gallery docs open these forms (W1's LABEL_DOCS, now registered).
    assert [form_for_doc(doc) for doc in LABEL_DOCS] == [lock, unlock]
    assert missing_forms() == []
    # The picker is a picture picker (a thumbnail beside it) of gallery pictures only.
    from engine.tools.editor import formdialogs
    assert "gallery" in formdialogs.PICTURE_KINDS
    assert forms_more.GALLERY_WHAT == "gallery"
    assert forms.form_by_key("lock").row_word({"what": "gallery"}) == "Forget gallery picture"


def test_ac_f34_33_game_settings_extras_page():
    keys = [p.key for p in sm.pages()]
    assert keys.index("extras") == keys.index("words") - 1     # before Button words
    page = sm.page("extras")
    assert page.title == "Extras" and "extras" in sm.P2_PAGES
    want: set[str] = set()
    for path in ("gallery", "theme.gallery.caption", "theme.gallery.viewer"):   # F34-W3's
        cls = section_class(path)
        if cls is not None:
            want |= {f"{path}.{k}" for k in config_fields(cls)}
    words = config_fields(section_class("words"))                 # F35-S3: the music room's
    want |= {f"words.{k}" for k in sm.MUSIC_ROOM_WORDS if k in words}
    assert {f.path for f in page.fields} == want
    if "gallery.show_locked" in want:
        assert sm.fields_by_path()["gallery.show_locked"].label == "Show locked pictures as ???"
    for key in sm.all_keys():                                  # Settings key coverage
        assert key in sm.fields_by_path() or sm.text_only(key) or sm.on_looks_page(key), key
    assert missing_forms() == []


@pytest.mark.tk
def test_ac_f34_34_preview_the_gallery_runs_extras(studio, tmp_path, monkeypatch):
    game = cg_game(tmp_path)
    ed = studio(game, mapped=True)
    win = ed.win
    runner = fake_game(win)
    db = open_database(ed, "gallery")
    button = db.preview_button
    assert button.cget("text") == "▶ Preview the gallery"
    ready = dbgallery.extras_ready()
    assert str(button.cget("state")) == ("normal" if ready else "disabled")
    assert db.preview_tip.text == (dbgallery.PREVIEW_TIP if ready else
                                   dbgallery.PREVIEW_NOT_YET)
    win.play_extras("gallery")                                 # through the Play bar
    assert runner.argvs == [preview_argv(game, None, [], extra=("--extras", "gallery"))]
    assert runner.argvs[0][-2:] == ["--extras", "gallery"]
    monkeypatch.setattr(dbgallery, "extras_ready", lambda: True)
    db.preview_gallery()                                       # the button's command
    assert runner.argvs[-1][-2:] == ["--extras", "gallery"] and len(runner.argvs) == 2
