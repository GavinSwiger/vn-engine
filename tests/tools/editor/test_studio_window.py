"""Studio's window wiring for project and files (F45 step 3; ``06`` AC-F45-16, 19, 20, 21,
26, 29 Tk rows; ``07`` I-1, I-2).

Built on game S with a fake check runner (records ``request``) and the dialogs answered by
patching the window module's ``ask``, ``ask_text``, ``ask_open_files``, ``show_error`` and
``show_info``. The logic under each row is tested without Tk in ``test_files.py``."""

import logging
import os
import shutil
import time
from pathlib import Path

import pytest

from engine.core.paths import GamePaths
from tests.tools.editor.conftest import S_SCRIPTS, patch_studio, png

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
from tests.tools.editor.test_window import Editor, new_root  # noqa: E402

pytestmark = pytest.mark.tk


class FakeChecks:
    def __init__(self) -> None:
        self.requests: list[tuple[object, int, bool]] = []
        self.stopped = False

    def request(self, overlay, serial, *, launch):
        self.requests.append((overlay, serial, launch))

    def poll(self):
        return []

    def stop(self):
        self.stopped = True


@pytest.fixture
def studio(monkeypatch):
    """``studio(game, mapped=False) -> Editor`` with ``.dialogs`` (every dialog text, in
    order), ``.answers`` (queued answers for ``ask``/``ask_text``) and ``.checks``."""
    roots: list = []
    callback_errors: list = []
    dialogs: list[tuple] = []
    answers: list = []
    picked: list[Path] = []

    def fake_ask(parent, message, buttons, *, escape, default=0):
        dialogs.append(("ask", message, tuple(buttons), escape, default))
        return answers.pop(0)

    def fake_ask_text(parent, message, initial, *, ok, hint=None, option=None,
                      option_value=True, select_stem=True):
        dialogs.append(("text", message, initial, hint(initial) if hint else None, option))
        answer = answers.pop(0)
        return None if answer is None else (answer if isinstance(answer, tuple)
                                            else (answer, option_value))

    patch_studio(monkeypatch, "ask", fake_ask)
    patch_studio(monkeypatch, "ask_text", fake_ask_text)
    patch_studio(monkeypatch, "ask_open_files", lambda parent: list(picked))
    patch_studio(monkeypatch, "show_error",
                 lambda parent, text: dialogs.append(("error", text)))
    patch_studio(monkeypatch, "show_info",
                 lambda parent, text: dialogs.append(("info", text)))

    def build(game: Path, *, mapped: bool = False) -> Editor:
        root = new_root()
        roots.append(root)
        root.report_callback_exception = lambda *info: callback_errors.append(info)
        root.withdraw()
        checks = FakeChecks()
        ed = Editor(window.EditorWindow(root, GamePaths.for_game(game), check_runner=checks),
                    [])
        ed.dialogs, ed.answers, ed.picked, ed.checks = dialogs, answers, picked, checks
        if mapped:
            root.geometry("+-3000+-3000")
            root.deiconify()
            root.update()
        else:
            root.update_idletasks()
        return ed

    try:
        yield build
    finally:
        for root in roots:
            try:
                root.destroy()
            except tk.TclError:
                pass
    assert not callback_errors, callback_errors


def select(ed: Editor, ref: str) -> None:
    ed.tree.selection_set(ref)
    ed.tree.focus(ref)
    ed.root.update()


def wait_adding(ed: Editor) -> None:
    end = time.monotonic() + 5
    while ed.win.adding and time.monotonic() < end:
        ed.root.update()
        time.sleep(0.005)
    assert not ed.win.adding


def tab(ed: Editor) -> str:
    return ed.notebook.tab(ed.notebook.select(), "text")


# --- AC-F45-16 (Tk): selecting rows and refreshing on focus --------------------------------

def test_ac16_selecting_rows_opens_the_right_tab(studio, studio_game):
    ed = studio(studio_game)
    assert ed.root.title() == "my_game — vn-engine Studio"
    assert ed.checks.requests == [(None, 0, False)]     # load-only at open (07 I-1)
    select(ed, "script/ch2.vns")
    assert tab(ed) == "Editor" and ed.current.ref == "script/ch2.vns"
    select(ed, "config.toml")
    assert tab(ed) == "Editor" and ed.body() == '[game]\ntitle = "My Game"'
    select(ed, "images/bg/room.png")
    assert tab(ed) == "File preview" and "Image name: bg room" in ed.asset_pane.text()
    (studio_game / "images" / "bg" / "new.png").write_bytes(png(1, 1))
    ed.win._last_outside_check = float("-inf")
    ed.root.event_generate("<FocusIn>")
    ed.root.update_idletasks()
    assert ed.tree.item("images", "text") == "Images (4)"
    assert ed.tree.exists("images/bg/new.png")


# --- AC-F45-19 and AC-F45-21's window rows: the file dialogs --------------------------------

def test_ac19_file_dialogs(studio, studio_game, tmp_path):
    ed = studio(studio_game, mapped=True)
    src = tmp_path / "src"
    src.mkdir()
    (src / "Hana Smile.png").write_bytes(png(3, 3))
    (src / "happy.png").write_bytes(png(4, 4))

    # The image-name dialog, then the milestone: the sprite appears in the tree.
    select(ed, "images/hana")
    ed.picked[:] = [src / "Hana Smile.png"]
    ed.answers[:] = ["smile.png"]
    ed.press(ed.tree, "<Control-Shift-O>")
    wait_adding(ed)
    assert ed.dialogs[0] == ("text", "`Hana Smile.png` can't be an image name (spaces). "
                             "Use `hana_smile.png`?", "hana_smile.png",
                             "In the script: show hana hana_smile", None)
    assert ed.dialogs[-1] == ("info", "Added 1 file.")
    assert ed.tree.item("images/hana/smile.png", "text") == "smile.png (hana smile)"
    assert ed.tree.item("images", "text") == "Images (4)"

    # The clash question; Skip changes nothing.
    ed.dialogs.clear()
    ed.picked[:] = [src / "happy.png"]
    ed.answers[:] = [2]
    before = (studio_game / "images" / "hana" / "happy.png").read_bytes()
    ed.win.add_files()
    assert ed.dialogs == [("ask", "`images/hana/happy.png` already exists.",
                           ("Keep both", "Replace", "Skip"), 2, 0)]
    assert (studio_game / "images" / "hana" / "happy.png").read_bytes() == before

    # Rename and delete confirmations; Cancel changes nothing.
    ed.dialogs.clear()
    select(ed, "images/hana/happy.png")
    ed.answers[:] = ["smile2.png", 1]
    ed.press(ed.tree, "<F2>")
    assert ed.dialogs[1] == ("ask", "Rename `images/hana/happy.png` to `smile2.png`? The "
                             "script calls it `hana smile2` after this. Lines that use "
                             "`hana happy` aren't changed.", ("Rename", "Cancel"), 1, 0)
    select(ed, "audio/bgm/theme.ogg")
    ed.answers[:] = [1]
    ed.press(ed.tree, "<Delete>")
    assert ed.dialogs[2] == ("ask", "Move `audio/bgm/theme.ogg` to the Recycle Bin? You "
                             "can restore it from there." if window.files.recycle.AVAILABLE
                             else window.files.delete_message("audio/bgm/theme.ogg"),
                             ("Delete", "Cancel"), 1, 1)
    assert (studio_game / "images" / "hana" / "happy.png").exists()
    assert (studio_game / "audio" / "bgm" / "theme.ogg").exists()

    # main.vns can't be renamed or deleted.
    ed.dialogs.clear()
    select(ed, "script/main.vns")
    ed.press(ed.tree, "<F2>")
    ed.press(ed.tree, "<Delete>")
    assert ed.dialogs == [("error", window.files.MAIN_FIXED)] * 2

    # AC-F45-21: renaming dirty ch2.vns keeps its text and * and saves to the new name;
    # deleting it names the unsaved changes and closes its record.
    ed.open_file("script/ch2.vns")
    ed.text.insert("1.0", "# mine\n")
    select(ed, "script/ch2.vns")
    ed.dialogs.clear()
    ed.answers[:] = ["ch4.vns", 0]
    ed.win.rename_selected()
    assert "unsaved changes" in ed.dialogs[1][1]
    assert ed.current.ref == "script/ch4.vns" and ed.body().startswith("# mine")
    assert ed.row("script/ch4.vns") == "* ch4.vns"
    assert ed.win.save_current()
    assert (studio_game / "script" / "ch4.vns").read_text().startswith("# mine")
    assert not (studio_game / "script" / "ch2.vns").exists()
    ed.text.insert("1.0", "x")
    select(ed, "script/ch4.vns")
    ed.dialogs.clear()
    ed.answers[:] = [0]
    ed.win.delete_selected()
    assert "`script/ch4.vns` has unsaved changes, which will be lost." in ed.dialogs[0][1]
    assert not (studio_game / "script" / "ch4.vns").exists()
    assert "script/ch4.vns" not in ed.files and ed.current.ref == "script/main.vns"


# --- AC-F45-20 (Tk): New script file adds an include line ------------------------------------

def test_ac20_ctrl_n_adds_an_undoable_include(studio, studio_game):
    (studio_game / "script" / "routes").mkdir()
    ed = studio(studio_game, mapped=True)
    main = studio_game / "script" / "main.vns"

    def main_text():
        return ed.files["script/main.vns"].widget.get("1.0", "end-1c").split("\n")

    ed.answers[:] = ["ch3.vns"]
    ed.press(ed.text, "<Control-n>")
    assert main_text()[:2] == ['include "ch2.vns"', 'include "ch3.vns"']
    assert ed.row("script/main.vns") == "* main.vns"
    assert main.read_text() == S_SCRIPTS["main.vns"]
    assert ed.current.ref == "script/ch3.vns"
    ed.open_file("script/main.vns")
    ed.press(ed.text, "<Control-z>")
    assert main_text() == S_SCRIPTS["main.vns"].rstrip("\n").split("\n")

    select(ed, "script/routes")
    ed.answers[:] = ["kai.vns"]
    ed.win.new_script_file()
    assert main_text()[1] == 'include "routes/kai.vns"'

    widget = ed.files["script/main.vns"].widget
    widget.delete("1.0", "3.0")                         # no top-level include left
    select(ed, "script")
    ed.answers[:] = ["ch5.vns"]
    ed.win.new_script_file()
    assert main_text()[0] == 'include "ch5.vns"'

    text = "\n".join(main_text())
    ed.answers[:] = [("ch6.vns", False)]
    ed.win.new_script_file()
    assert "\n".join(main_text()) == text
    assert (studio_game / "script" / "ch6.vns").read_bytes() == b"label ch6:\n"


# --- AC-F45-26 (Tk): the game folder goes away ---------------------------------------------

def test_ac26_a_missing_game_folder_turns_file_operations_off(studio, studio_game):
    ed = studio(studio_game)
    assert ed.win.file_ops_enabled()
    shutil.rmtree(studio_game)
    ed.win._last_outside_check = float("-inf")
    ed.root.event_generate("<FocusIn>")
    ed.root.update_idletasks()
    assert [ed.tree.item(i, "text") for i in ed.tree.get_children("")] == [
        "The game folder can't be found."]
    assert not ed.win.file_ops_enabled()
    for label in ("New script file", "Add files…", "Rename", "Delete"):
        assert not window.entry_enabled(ed.win.file_menu, label)
    assert str(ed.win.add_button.cget("state")) == "disabled"
    ed.win.add_files()
    ed.win.new_script_file()
    assert ed.dialogs == []


# --- The project panel's right-click menu: Open in File Explorer --------------------------

def test_reveal_command_per_system(tmp_path):
    from engine.tools.editor import fileactions as fa
    file, folder = tmp_path / "a b" / "x.png", tmp_path / "a b"
    assert fa.reveal_command(file, True, "win32") == f'explorer /select,"{file}"'
    assert fa.reveal_command(folder, False, "win32") == f'explorer "{folder}"'
    assert fa.reveal_command(file, True, "darwin") == ["open", "-R", str(file)]
    assert fa.reveal_command(folder, False, "darwin") == ["open", str(folder)]
    assert fa.reveal_command(file, True, "linux") == ["xdg-open", str(folder)]


def test_right_click_menu_shows_rows_in_the_file_manager(studio, studio_game, monkeypatch):
    from engine.tools.editor import fileactions as fa
    launched: list = []
    patch_studio(monkeypatch, "CONTEXT_MENUS_POST", False)
    patch_studio(monkeypatch, "launch_file_manager", launched.append)
    ed = studio(studio_game)
    root = studio_game.resolve()

    def menu_for(ref: str) -> dict[str, bool]:
        select(ed, ref)
        ed.win.project_context()                    # Shift+F10 on the selected row
        menu = ed.win.last_project_menu
        return {menu.entrycget(i, "label"): window.entry_enabled(menu, i)
                for i in range(menu.index("end") + 1) if menu.type(i) == "command"}

    # A file is selected in its folder; Rename and Delete are on for it.
    assert menu_for("images/hana/happy.png") == {
        fa.REVEAL_LABEL: True, fa.RENAME_ITEM: True, fa.DELETE_ITEM: True}
    ed.win.reveal_selected()
    assert launched[-1] == fa.reveal_command(root / "images" / "hana" / "happy.png", True)

    # A folder opens; Rename and Delete are dimmed.
    assert menu_for("images/hana") == {
        fa.REVEAL_LABEL: True, fa.RENAME_ITEM: False, fa.DELETE_ITEM: False}
    ed.win.reveal_selected()
    assert launched[-1] == fa.reveal_command(root / "images" / "hana", False)

    # A group whose folder doesn't exist yet opens the game folder.
    select(ed, "minigames")
    ed.win.reveal_selected()
    assert launched[-1] == fa.reveal_command(root, False)

    # The file manager failing to start is said, not raised.
    def broken(command):
        raise OSError("no file manager")
    patch_studio(monkeypatch, "launch_file_manager", broken)
    select(ed, "config.toml")
    ed.win.reveal_selected()
    assert ed.dialogs[-1] == ("error", fa.REVEAL_FAILED)


# --- AC-F45-29 (Tk): nothing names the user ------------------------------------------------

def test_ac29_dialogs_show_file_names_only(studio, studio_game, tmp_path):
    downloads = tmp_path / "vn_user_7f3a" / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "Hana Smile.png").write_bytes(png(3, 3))
    (downloads / "notes.txt").write_text("n")
    handlers = list(logging.getLogger().handlers)
    ed = studio(studio_game)
    select(ed, "images/hana")
    ed.picked[:] = [downloads / "Hana Smile.png", downloads / "notes.txt"]
    ed.answers[:] = [None]                              # Skip the name dialog
    ed.win.add_files()
    wait_adding(ed)
    texts = [str(part) for entry in ed.dialogs for part in entry[1:] if part is not None]
    assert ed.dialogs[-1] == ("info", "No files were added.\n1 file wasn't added:\n"
                              "`notes.txt`: Images takes PNG, JPEG, or WebP files.")
    for text in texts + [ed.status_label.cget("text"), ed.root.title()]:
        assert "vn_user_7f3a" not in text and str(tmp_path) not in text and "\\" not in text
    assert logging.getLogger().handlers == handlers
    assert not [p for p in os.listdir(studio_game) if p.endswith(".log")]


def test_right_click_in_the_editor_goes_to_definition(studio, studio_game, monkeypatch):
    """2026-11-04: right-click a name (or Ctrl+click it) to go where it is made."""
    from engine.tools.editor import editormenu as em
    from engine.tools.editor.checker import NameEntry
    patch_studio(monkeypatch, "CONTEXT_MENUS_POST", False)
    ed = studio(studio_game, mapped=True)
    win = ed.win
    win.check_names = {"label": (NameEntry("bridge", "script/ch2.vns", 8),),
                       "character": (NameEntry("hana", "script/main.vns", 2),)}
    win.open_file("script/main.vns")
    text = win.text
    ed.root.update()

    def menu_at(index: str) -> dict[str, bool]:
        text.mark_set("insert", index)
        menu = win.editor_menu(text)          # what Shift+F10 or a right-click posts
        return {menu.entrycget(i, "label"): window.entry_enabled(menu, i)
                for i in range(menu.index("end") + 1) if menu.type(i) == "command"}

    bound = ed.root.bind_class(win._editor_bindtag)
    assert {"<Button-3>", "<Shift-Key-F10>"} <= set(bound)
    assert menu_at("8.10") == {"Go to scene bridge": True, em.CUT: False, em.COPY: False,
                               em.PASTE: True, em.SELECT_ALL: True}
    win.last_editor_menu.invoke(0)
    assert win.current.ref == "script/ch2.vns" and text is not win.text
    assert win.text.index("insert") == "8.0"
    # Nothing to go to: the entry is there, dimmed.
    win.open_file("script/main.vns")
    assert menu_at("4.2")["Go to definition"] is False
    # The picture in ``show hana happy`` opens in the File preview.
    assert "Show picture hana happy" in menu_at("5.12")
    win.last_editor_menu.invoke(0)
    assert win.current_tab() == "asset"
    # Ctrl+click on the speaker's name.
    win.open_file("script/main.vns")
    text.see("6.5")
    ed.root.update()
    x, y, _w, _h = text.bbox("6.5")
    text.event_generate(f"<{win.mod}-Button-1>", x=x + 1, y=y + 1)
    assert win.text.index("insert") == "2.0"


def test_switching_files_registers_no_new_tcl_commands(studio, studio_game):
    """v1 finding 8: the editor's scrollbars keep one command each, which scrolls the
    text on screen; switching files no longer leaves a Tcl command behind per switch."""
    ed = studio(studio_game, mapped=True)
    win = ed.win
    win.open_file("script/ch2.vns")
    win.open_file("script/main.vns")
    ed.root.update()

    def scrolls() -> int:                       # Python callbacks named after yview/xview
        return sum(1 for name in ed.root.tk.splitlist(ed.root.tk.call("info", "commands"))
                   if name[:1].isdigit() and name.endswith(("yview", "xview")))

    count = scrolls()
    for i in range(20):
        win.open_file(("script/ch2.vns", "script/main.vns")[i % 2])
    assert scrolls() == count
    win.open_file("script/ch2.vns")
    shown = win._shown
    shown.insert("end", "\n" * 200)
    ed.root.update()
    win.vbar.tk.call(str(win.vbar.cget("command")), "moveto", "1.0")
    assert shown.yview()[1] == 1.0


def test_the_app_icon_is_drawn_once_and_kept(monkeypatch):
    """v1 finding 6: the icon PNGs are kept in Studio's per-user folder (a fresh one per
    test) by a digest of the drawing code and colours; the next launch reads them."""
    from engine.tools.editor import appicon

    drawn: list[int] = []
    draw = appicon.icon_png.__wrapped__
    monkeypatch.setattr(appicon, "icon_png", lambda size: (drawn.append(size), draw(size))[1])
    first = [appicon.cached_png(size) for size in appicon.ICON_SIZES]
    assert drawn == list(appicon.ICON_SIZES)
    assert [appicon.cached_png(size) for size in appicon.ICON_SIZES] == first
    assert drawn == list(appicon.ICON_SIZES)                # read back, not drawn again
    monkeypatch.setitem(appicon.THEME, "icon.background", "#123456")
    appicon.cached_png(16)
    assert drawn[-1] == 16 and len(drawn) == len(appicon.ICON_SIZES) + 1
