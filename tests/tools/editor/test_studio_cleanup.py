"""F41 W2: Database ▸ Clean up in Studio (``01-design.md`` §4.4, §6.1, §6.2;
``04-technical.md`` §7.5; AC-F41-17, 18, 19, 21, 22).

One test per AC, Tk, in a real Studio window on a copy of the F47 sample game
(``files.new_game``) given an unreached scene, an unused picture, sound, variable and
define, then checked with the real (in-process) check."""

import shutil
from pathlib import Path

import pytest

from engine.tools.editor import cleanup as cu
from engine.tools.editor import dbmodel as db
from engine.tools.editor import files
from tests.tools.editor.conftest import png

tk = pytest.importorskip("tkinter")
pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_studio_database import (  # noqa: E402,F401
    apply_check, helper, open_database)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401

pytestmark = pytest.mark.tk

CLEANUP = db.CATEGORY_CLEANUP


def cleanup_game(tmp_path: Path) -> Path:
    game = files.new_game(tmp_path / "my_game")
    assert isinstance(game, Path)
    with open(game / "script/main.vns", "a", encoding="utf-8") as f:
        f.write('\nlabel old_ending:\n    "Nobody comes this way."\n    return\n')
    with open(game / "script/database.vns", "a", encoding="utf-8") as f:
        f.write("define unused_thing = 3\ndefault lantern_count = 0\n")
    (game / "images/bg/old_park.png").write_bytes(png(8, 8))
    shutil.copy(game / "audio/sound/chime.wav", game / "audio/sound/old_bell.wav")
    return game


def checked(studio, tmp_path, *, mapped: bool = True):
    game = cleanup_game(tmp_path)
    ed = studio(game, mapped=mapped)
    apply_check(ed, game)
    pane = open_database(ed, CLEANUP)
    return ed, pane, game


def texts(widget) -> list[str]:
    found = []
    for child in widget.winfo_children():
        try:
            text = str(child.cget("text"))
        except tk.TclError:
            text = ""
        if text:
            found.append(text)
        found += texts(child)
    return found


def button(widget, text: str):
    for child in widget.winfo_children():
        try:
            if str(child.cget("text")) == text:
                return child
        except tk.TclError:
            pass
        found = button(child, text)
        if found is not None:
            return found
    return None


def tree_rows(pane) -> list[tuple[str, str, str]]:
    tree = pane.list_tree
    out = []
    for gid in tree.get_children():
        out.append((gid, tree.item(gid, "text"), tree.set(gid, "detail")))
        out += [(iid, tree.item(iid, "text"), tree.set(iid, "detail"))
                for iid in tree.get_children(gid)]
    return out


def test_ac_f41_17_clean_up_last_category_groups_rows_and_form(studio, tmp_path, helper):
    ed, pane, _game = checked(studio, tmp_path)
    assert pane.cat_tree.get_children()[-1] == CLEANUP
    assert pane.cat_tree.item(CLEANUP, "text") == "Clean up"
    assert pane.counts()[CLEANUP] == 5
    assert pane.list_title.cget("text") == "CLEAN UP"
    assert not pane.new_button.winfo_ismapped()
    assert pane.cleanup_header.cget("text") == cu.HEADER and pane.cleanup_head.winfo_ismapped()
    assert tree_rows(pane) == [
        ("g:cleanup:scene", "SCENES NOT REACHED", "1"),
        ("u:unreached:old_ending", "old_ending", "main.vns:50"),
        ("g:cleanup:picture", "PICTURES", "1"),
        ("u:unused_picture:bg old_park", "bg old_park", "old_park.png"),
        ("g:cleanup:sound", "SOUNDS", "1"),
        ("u:unused_sound:sound/old_bell.wav", "sound/old_bell.wav", "old_bell.wav"),
        ("g:cleanup:variable", "VARIABLES", "1"),
        ("u:unused_variable:lantern_count", "lantern_count", "database.vns:15"),
        ("g:cleanup:other", "OTHER", "1"),
        ("u:unused_define:unused_thing", "unused_thing", "database.vns:14")]

    pane.select("u:unused_picture:bg old_park")
    ed.root.update()
    shown = texts(pane.body)
    assert "bg old_park" in shown and "Picture" in shown
    assert "images/bg/old_park.png" in shown
    warning = cu.cleanup_view(ed.win.check_result).item("u:unused_picture:bg old_park")
    assert warning is not None and warning.text in shown and "bg old_park" in warning.text
    assert pane._preview_ref == "images/bg/old_park.png"               # the picture preview
    assert "Open in Pictures" in shown and cu.DELETE in shown

    pane.select("u:unused_sound:sound/old_bell.wav")
    ed.root.update()
    shown = texts(pane.body)
    assert "▶ Play" in shown and "Open in Sounds" in shown and cu.DELETE in shown
    button(pane.body, "▶ Play").invoke()
    assert helper[-1].sent[-1] == ("play", "audio/sound/old_bell.wav")

    pane.select("u:unreached:old_ending")
    ed.root.update()
    shown = texts(pane.body)
    assert "Scene" in shown and "script/main.vns, line 50" in shown
    assert cu.SHOW_ON_MAP in shown and cu.DELETE in shown

    pane.select("u:unused_define:unused_thing")
    ed.root.update()
    shown = texts(pane.body)
    assert "Define" in shown and cu.OPEN_IN_EDITOR in shown and cu.DELETE in shown


def test_ac_f41_18_open_in_category_and_show_on_map(studio, tmp_path, helper):
    ed, pane, _game = checked(studio, tmp_path)
    pane.select("u:unused_variable:lantern_count")
    ed.root.update()
    button(pane.body, "Open in Variables").invoke()
    ed.root.update()
    assert pane.category == db.CATEGORY_VARIABLE
    row = pane.selected_row()
    assert row is not None and row.entry is not None and row.entry.name == "lantern_count"

    pane.select_category(CLEANUP)
    pane.select("u:unused_picture:bg old_park")
    ed.root.update()
    button(pane.body, "Open in Pictures").invoke()
    ed.root.update()
    assert pane.category == db.CATEGORY_PICTURE
    assert pane.selected_row().entry.name == "bg old_park"

    pane.select_category(CLEANUP)
    pane.select("u:unreached:old_ending")
    ed.root.update()
    button(pane.body, cu.SHOW_ON_MAP).invoke()
    ed.root.update()
    assert ed.win.current_tab() == "map"
    assert ed.win.story_map.focused_name() == "old_ending"


def test_ac_f41_19_delete_runs_the_category_delete_and_the_row_goes(studio, tmp_path, helper):
    ed, pane, game = checked(studio, tmp_path)
    # A picture file: Pictures' own question, then the file is gone and the row hides.
    pane.select("u:unused_picture:bg old_park")
    ed.root.update()
    ed.answers.append(1)                                  # Cancel: nothing happens
    button(pane.body, cu.DELETE).invoke()
    ed.root.update()
    assert (game / "images/bg/old_park.png").exists()
    assert ed.dialogs[-1][1] == files.DELETE_FILE_ASK.format(ref="images/bg/old_park.png")
    ed.answers.append(0)
    button(pane.body, cu.DELETE).invoke()
    ed.root.update()
    assert not (game / "images/bg/old_park.png").exists()
    assert "u:unused_picture:bg old_park" not in [r[0] for r in tree_rows(pane)]
    assert pane.counts()[CLEANUP] == 4

    # A define: the declaration delete (its line goes, one undo step).
    pane.select("u:unused_define:unused_thing")
    ed.root.update()
    ed.answers.append(0)
    button(pane.body, cu.DELETE).invoke()
    ed.root.update()
    assert ed.dialogs[-1][1].startswith("Delete unused_thing? Its line is removed from")
    db_text = ed.win.files["script/database.vns"].widget.get("1.0", "end-1c")
    assert "unused_thing" not in db_text and "lantern_count" in db_text

    # A scene: F46's Delete scene on the map.
    pane.select("u:unreached:old_ending")
    ed.root.update()
    ed.answers.append(0)
    button(pane.body, cu.DELETE).invoke()
    ed.root.update()
    main = ed.win.files["script/main.vns"].widget.get("1.0", "end-1c")
    assert "label old_ending" not in main
    assert ed.win.current_tab() == "map"

    # After the next check (saved first), the rows are gone for good.
    ed.win.save_all()
    apply_check(ed, game)
    open_database(ed, CLEANUP)
    left = [r[0] for r in tree_rows(pane)]
    assert left == ["g:cleanup:sound", "u:unused_sound:sound/old_bell.wav",
                    "g:cleanup:variable", "u:unused_variable:lantern_count"]


def test_ac_f41_21_search_filters_clean_up_by_name(studio, tmp_path, helper):
    ed, pane, _game = checked(studio, tmp_path)
    pane.set_search("OLD")
    ed.root.update()
    assert [r[1] for r in tree_rows(pane)] == [
        "SCENES NOT REACHED", "old_ending", "PICTURES", "bg old_park", "SOUNDS",
        "sound/old_bell.wav"]
    pane.set_search("nothing like it")
    ed.root.update()
    assert tree_rows(pane) == []


def test_ac_f41_22_narrow_window_drop_down_shows_clean_up_and_its_count(studio, tmp_path,
                                                                        helper):
    ed, pane, _game = checked(studio, tmp_path)
    ed.root.geometry("760x600+-3000+-3000")
    for _ in range(3):
        ed.root.update()
    assert pane.compact and pane.cat_choice.widget.winfo_ismapped()
    values = list(pane.cat_choice.box.cget("values"))
    assert values[-1] == "Clean up (5)"
    assert pane.cat_choice.var.get() == "Clean up (5)"


def test_clean_up_with_a_story_error_says_fix_it_first(studio, tmp_path, helper):
    """FRICTION 6: with an error in the story, Clean up shows "fix the errors first" (it
    raised ``KeyError: 'error'`` from the icon lookup), and its button opens Problems."""
    game = cleanup_game(tmp_path)
    with open(game / "script/main.vns", "a", encoding="utf-8") as f:
        f.write("\nlabel broken:\n    jump nowhere_at_all\n")
    ed = studio(game, mapped=True)
    apply_check(ed, game)
    pane = open_database(ed, CLEANUP)
    empty = pane.cleanup_empties[cu.STATE_ERRORS]
    assert empty.shown
    assert empty.title.cget("text") == "Fix the errors in Problems first."
    assert empty.hint.cget("text") == "Clean up needs a story that loads."
    assert empty.button is not None and empty.button.cget("text") == "Show Problems"
