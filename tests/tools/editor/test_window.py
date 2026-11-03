"""The editor window on game R (F44 ``04`` §7.1, §7.2, §7.6; ``03`` §1-§4; ``07`` I-3, I-6,
I-13, I-14). Tk rows of AC-F44-12, 14, 15, 16, 18, 19, 20, 22, 23, 24, 25, 32, and the
``run_editor`` start-up lines of AC-F44-13. AC-F44-12, 15, 18 and 24 as amended by F45 step 3:
the project panel's Script group replaces the file list, and the title says Studio.

Conventions (``06`` §0.2): the window is built on a hidden root; tests that press keys or
measure geometry map it off-screen at ``+-3000+-3000`` (a withdrawn root gets no keyboard
focus on Windows). Text is typed through the ``Text`` widget's own commands, which pass
through the change hook. Dialogs are answered by patching ``ask`` and
``show_error``, except the rows that drive the real ``ask`` dialog. Every root is
destroyed in the fixture's ``finally``. Skipped when Tk or a display is missing.
"""

import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.core.paths import GamePaths
from engine.script.loader import load_story
from engine.script.source import LineCursor, decode_script
from engine.tools import editor as editor_package
from engine.tools.editor.document import open_document
from engine.tools.editor.syntax import SYNTAX_TAGS, TAG_COLORS, label_above
from tests.fixtures.F44.byte_variants import VARIANTS
from tests.tools.editor.conftest import patch_studio
from tests.tools.editor.conftest import R_SCRIPTS, link_dir

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")

pytestmark = pytest.mark.tk

R_REFS = ["script/main.vns", "script/chapter2.vns", "script/chapter3.vns",
          "script/routes/hana.vns"]
R_ROWS = ["main.vns", "chapter2.vns", "chapter3.vns", "hana.vns"]
TITLE = "my_game — vn-engine Studio"
# X11 modifier masks, which Tk uses on every platform: a real Caps Lock press is the
# upper-case keysym with Lock and without Shift (event_generate adds Shift on its own).
SHIFT, LOCK, CONTROL = 0x1, 0x2, 0x4


def take_focus(widget, timeout: float = 2.0) -> None:
    """``widget.focus_force()``, then Tk events until the application holds the keyboard
    focus (at most ``timeout`` seconds). Under load (pytest-xdist workers) Windows can hand
    the focus over a moment late, and Tk drops a key event sent before then."""
    end = time.monotonic() + timeout
    while True:
        widget.focus_force()
        widget.update()
        try:
            focused = widget.focus_get()
        except KeyError:                    # a Tk-internal widget has the focus
            focused = widget
        if focused is not None or time.monotonic() >= end:
            return
        time.sleep(0.01)


class NoChecks:
    """A check runner that runs nothing (F45 ``07`` I-2): F44's window tests spawn no check
    child."""

    def request(self, overlay, serial, *, launch):
        pass

    def poll(self):
        return []

    def stop(self):
        pass


class Editor:
    """An ``EditorWindow`` plus test helpers."""

    def __init__(self, win: "window.EditorWindow", errors_shown: list[str]) -> None:
        self.win = win
        self.root = win.root
        self.errors_shown = errors_shown

    def __getattr__(self, name):
        return getattr(self.win, name)

    def idle(self) -> None:
        self.root.update_idletasks()

    def press(self, widget, sequence: str, **fields) -> None:
        """A real key event (needs a mapped window). ``Control`` in ``sequence`` becomes
        Command on macOS."""
        take_focus(widget)
        widget.event_generate(sequence.replace("Control", self.win.mod), **fields)
        self.root.update()

    def focus(self):
        self.root.update()
        return self.root.focus_get()

    def rows(self) -> list[str]:
        """The Script group's file rows as shown, in panel order (F45 amended A-12)."""
        return [self.project_view.row_text(ref) for ref in self.win.refs]

    def row(self, ref: str) -> str:
        return self.project_view.row_text(ref)

    def selected(self) -> str | None:
        return self.project_view.selected()

    def body(self, widget=None) -> str:
        return (widget or self.text).get("1.0", "end-1c")

    def gutter_numbers(self) -> list[tuple[str, float, float]]:
        """(text, top y, right x) of every number drawn, top to bottom."""
        canvas = self.gutter
        found = []
        for item in canvas.find_all():
            x1, y1, x2, y2 = canvas.bbox(item)
            found.append((canvas.itemcget(item, "text"), canvas.coords(item)[1], x2))
        return sorted(found, key=lambda entry: entry[1])


def new_root():
    """A ``tk.Tk``, or skip without Tk or a display. Tk reads its library scripts from
    disk at every start; on a busy Windows machine (a virus scan) a read can fail once, so
    a failure is retried before the test is skipped."""
    for attempt in range(3):
        try:
            return tk.Tk()
        except tk.TclError as exc:
            error = exc
            time.sleep(0.05 * (attempt + 1))
    pytest.skip(f"Tk can't start here: {error}")


@pytest.fixture
def make_editor(monkeypatch):
    """``make_editor(game, mapped=False) -> Editor``; every root is destroyed afterwards,
    and a Tk callback that raised fails the test."""
    roots: list = []
    callback_errors: list = []
    errors_shown: list[str] = []
    patch_studio(monkeypatch, "show_error",
                 lambda parent, message: errors_shown.append(message))

    def build(game: Path, *, mapped: bool = False) -> Editor:
        root = new_root()
        roots.append(root)
        root.report_callback_exception = lambda *info: callback_errors.append(info)
        root.withdraw()
        editor = Editor(window.EditorWindow(root, GamePaths.for_game(game),
                                            check_runner=NoChecks()), errors_shown)
        if mapped:
            root.geometry("+-3000+-3000")
            root.deiconify()
            root.update()
        else:
            root.update_idletasks()
        return editor

    try:
        yield build
    finally:
        for root in roots:
            try:
                root.destroy()
            except tk.TclError:
                pass                    # closed by the test
    assert not callback_errors, callback_errors


@pytest.fixture
def no_dialog(monkeypatch):
    """Fail if ``ask`` is called; returns the list of calls when a test sets answers."""
    calls: list[tuple[str, tuple[str, ...], int]] = []
    answers: list[int] = []

    def fake_ask(parent, message, buttons, *, escape):
        calls.append((message, tuple(buttons), escape))
        assert answers, f"unexpected dialog: {message}"
        return answers.pop(0)

    patch_studio(monkeypatch, "ask", fake_ask)
    return SimpleNamespace(calls=calls, answers=answers)


def put(game: Path, ref: str, data: bytes) -> Path:
    path = game / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def f02_line_count(data: bytes) -> int:
    cursor = LineCursor(decode_script("script/x.vns", data).text)
    while cursor.next() is not None:
        pass
    return cursor.lines_read


def r_bytes(name: str) -> bytes:
    return R_SCRIPTS[name].encode("utf-8")


class read_only:
    """Make a file read-only for the block (the read-only attribute on Windows)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> Path:
        os.chmod(self.path, stat.S_IREAD)
        return self.path

    def __exit__(self, *exc) -> None:
        os.chmod(self.path, stat.S_IREAD | stat.S_IWRITE)


# --- The real dialog (ask) ------------------------------------------------------------------

def answer_dialog(root, action, seen: dict) -> None:
    """Answer the next ``ask`` dialog from inside its wait loop. ``action`` is a button
    index, ``"escape"``, or ``"close box"``. ``seen`` gets its message, buttons, and the
    focused button."""

    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    def step(tries=[0]):
        dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if not dialogs:
            tries[0] += 1
            if tries[0] < 100:
                root.after(10, step)
            return
        dialog = dialogs[0]
        dialog.update()
        widgets = list(walk(dialog))
        buttons = [w for w in widgets if w.winfo_class() == "TButton"]
        seen["message"] = [w.get("1.0", "end-1c") for w in widgets
                           if w.winfo_class() == "Text"][0]     # F45 08 §7: styled spans
        seen["buttons"] = [str(b.cget("text")) for b in buttons]
        focused = dialog.focus_get()
        seen["focused"] = str(focused.cget("text")) if focused in buttons else None
        seen["transient"] = bool(dialog.transient())
        if action == "escape":
            focused.event_generate("<Escape>")
        elif action == "close box":
            dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))
        else:
            buttons[action].invoke()

    def safety():
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel):
                seen["timed out"] = True
                w.destroy()

    root.after(10, step)
    root.after(5000, safety)


# --- AC-F44-12: opening the game ------------------------------------------------------------

def test_rows_selection_cursor_focus_and_title(make_editor, route_game, outside):
    put(route_game, "script/notes.txt", b"not a script\n")
    put(outside, "x.vns", b'label x:\n    "X."\n')
    link_dir(route_game / "script" / "ext", outside)
    ed = make_editor(route_game, mapped=True)
    assert ed.rows() == R_ROWS
    assert ed.win.refs == R_REFS
    assert list(ed.tree.get_children("script")) == R_REFS[:3] + ["script/routes"]
    assert list(ed.tree.get_children("script/routes")) == ["script/routes/hana.vns"]
    assert ed.selected() == "script/main.vns"
    assert ed.current.ref == "script/main.vns"
    assert ed.body() == R_SCRIPTS["main.vns"].rstrip("\n")
    assert ed.text.index("insert") == "1.0"
    take_focus(ed.root)                         # the window gets the focus, as at launch
    assert ed.focus() is ed.text
    assert ed.root.title() == TITLE


def test_the_title_never_shows_a_path(make_editor, tmp_path):
    game = tmp_path / "qauser7" / "ゲーム"
    put(game, "script/main.vns", b'label start:\n    "Hi."\n')
    ed = make_editor(game)
    title = ed.root.title()
    assert title.startswith("ゲーム")
    assert title == "ゲーム — vn-engine Studio"
    assert "/" not in title and "\\" not in title and "qauser7" not in title


def test_window_sizes_and_resizing(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    root = ed.root
    assert abs(root.winfo_width() - 1100) <= 1 and abs(root.winfo_height() - 720) <= 1
    assert root.minsize() == (760, 480)
    assert abs(ed.left.winfo_width() - 240) <= 2
    before = {
        "left": ed.left.winfo_width(),
        "values": ed.start_values.winfo_height(),
        "problems": ed.problems_frame.winfo_height(),
        "list": ed.tree.winfo_height(),
        "editor": (ed.text.winfo_width(), ed.text.winfo_height()),
    }
    root.geometry("1400x900")
    root.update()
    assert abs(ed.left.winfo_width() - before["left"]) <= 1
    assert abs(ed.start_values.winfo_height() - before["values"]) <= 1
    assert abs(ed.problems_frame.winfo_height() - before["problems"]) <= 1
    assert ed.tree.winfo_height() > before["list"]
    assert ed.text.winfo_width() > before["editor"][0]
    assert ed.text.winfo_height() > before["editor"][1]


def test_up_down_open_files_and_enter_moves_to_the_editor(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.press(ed.tree, "<Down>")
    assert ed.current.ref == "script/chapter2.vns"
    assert ed.body().startswith("default sayo_points = 0")
    ed.press(ed.tree, "<Down>")
    assert ed.current.ref == "script/chapter3.vns"
    ed.press(ed.tree, "<Up>")
    assert ed.current.ref == "script/chapter2.vns"
    assert ed.selected() == "script/chapter2.vns"
    ed.press(ed.tree, "<Return>")
    assert ed.focus() is ed.text


# --- AC-F44-14: saving changes only the edits ------------------------------------------------

def test_ctrl_s_without_an_edit_writes_nothing(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    path = route_game / "script" / "main.vns"
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    before = os.stat(path).st_mtime_ns
    ed.press(ed.text, "<Control-s>")
    assert os.stat(path).st_mtime_ns == before
    assert path.read_bytes() == r_bytes("main.vns")
    assert ed.errors_shown == []


def test_replacing_a_word_on_line_3_saves_only_line_3(make_editor, route_game):
    ed = make_editor(route_game)
    ed.open_file("script/chapter2.vns")
    ed.text.delete("3.8", "3.12")
    ed.text.insert("3.8", "found")
    assert ed.save_current()
    expected = r_bytes("chapter2.vns").replace(b"default seen = []", b"default found = []")
    assert (route_game / "script" / "chapter2.vns").read_bytes() == expected


def test_edit_then_undo_then_save_gives_the_original_bytes(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.text.insert("2.0", "zzz")
    ed.press(ed.text, "<Control-z>")
    assert ed.body() == R_SCRIPTS["main.vns"].rstrip("\n")
    assert ed.save_current()
    assert (route_game / "script" / "main.vns").read_bytes() == r_bytes("main.vns")


def test_an_emoji_typed_through_tk_is_saved_as_utf8(make_editor, route_game):
    ed = make_editor(route_game)
    ed.text.insert("6.end", " \U0001F600")
    assert ed.save_current()
    data = (route_game / "script" / "main.vns").read_bytes()
    assert b"\xf0\x9f\x98\x80" in data
    assert b"\xed\xa0" not in data and b"\xed\xb0" not in data


def test_the_editor_line_count_equals_f02s(make_editor, route_game):
    for name, data in VARIANTS.items():
        put(route_game, f"script/{name}.vns", data)
    ed = make_editor(route_game)
    for name, data in VARIANTS.items():
        ed.open_file(f"script/{name}.vns")
        lines = 0 if ed.body() == "" else int(ed.text.index("end-1c").split(".")[0])
        assert lines == f02_line_count(data), name


# --- AC-F44-15 (rows written at step 3, I-19): files that can't be opened ---------------

@pytest.mark.parametrize("case", ["invalid utf-8", "too large"])
def test_a_file_that_cant_be_opened_is_read_only(make_editor, route_game, case):
    path = route_game / "script" / "chapter2.vns"
    if case == "invalid utf-8":
        lines = R_SCRIPTS["chapter2.vns"].encode("utf-8").split(b"\n")
        lines[3] = lines[3] + b"\xff"
        path.write_bytes(b"\n".join(lines))
    else:
        path.write_bytes(b"#" * (16 * 1024 * 1024 + 1))
    original = path.read_bytes()
    ed = make_editor(route_game)
    ed.open_file("script/chapter2.vns")
    ed.idle()
    expected = open_document(GamePaths.for_game(route_game), "script/chapter2.vns").format()
    assert ed.selected() == "script/chapter2.vns"
    assert ed.body() == expected
    assert ed.text.cget("foreground") == "#9D9D9D"
    ed.text.insert("1.0", "typed")
    ed.idle()
    assert ed.body() == expected
    assert ed.start_label.cget("text") == "the beginning"
    assert not any(row.startswith("* ") for row in ed.rows())
    assert not ed.root.title().startswith("* ")
    assert ed.save_current()
    assert path.read_bytes() == original


def test_no_vns_files_shows_an_empty_script_group(make_editor, tmp_path):
    """AC-F44-15 as amended by F45: the Script group reads ``Script (0)`` with no leaves."""
    game = tmp_path / "my_game"
    (game / "script").mkdir(parents=True)
    ed = make_editor(game, mapped=True)
    assert ed.rows() == []
    assert ed.tree.item("script", "text") == "Script (0)"
    assert ed.tree.get_children("script") == ()
    ed.tree.selection_set("script")
    ed.root.update()
    assert ed.current is None
    assert ed.body() == ""
    ed.text.insert("1.0", "typed")
    assert ed.body() == ""
    assert ed.start_label.cget("text") == "the beginning"


def test_empty_states_show_and_run_existing_commands(make_editor, tmp_path):
    """F45 08 §9: with no scripts every tab shows its empty state; the button is the tab's
    F6 stop, and the story map's runs Check now (the check arms)."""
    game = tmp_path / "my_game"
    (game / "script").mkdir(parents=True)
    ed = make_editor(game, mapped=True)
    assert ed.editor_empty.shown
    assert ed.editor_empty.button.cget("text").startswith("New script file (")
    assert ed.story_map.empty.shown and ed.outline_view.empty.shown and ed.asset_pane.empty.shown
    ed.show_tab(1)
    assert ed._tab_widget() is ed.story_map.empty.button
    assert not ed.armed
    ed.story_map.empty.button.invoke()
    assert ed.armed


# --- AC-F44-16 (Tk row): a failed save keeps everything ---------------------------------

def test_a_failed_ctrl_s_shows_the_dialog_and_keeps_the_text(make_editor, route_game):
    path = route_game / "script" / "chapter2.vns"
    ed = make_editor(route_game, mapped=True)
    ed.open_file("script/chapter2.vns")
    ed.text.insert("1.0", "x")
    ed.idle()
    with read_only(path):
        ed.press(ed.text, "<Control-s>")
    assert ed.errors_shown == ["Couldn't save `script/chapter2.vns`: the file is read-only."]
    assert path.read_bytes() == r_bytes("chapter2.vns")
    assert ed.body().startswith("xdefault")
    assert ed.rows()[1] == "* chapter2.vns"


# --- AC-F44-18: unsaved markers, switching, standard keys -------------------------------------

def test_unsaved_marks_switching_and_saving_one_file(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.open_file("script/chapter2.vns")
    ed.text.insert("1.0", "x")
    ed.idle()
    assert ed.rows()[1] == "* chapter2.vns"
    assert ed.root.title() == "* " + TITLE
    ed.open_file("script/main.vns")
    assert ed.body() == R_SCRIPTS["main.vns"].rstrip("\n")
    ed.open_file("script/chapter2.vns")
    assert ed.body().startswith("xdefault")
    ed.press(ed.text, "<Control-z>")
    assert ed.body() == R_SCRIPTS["chapter2.vns"].rstrip("\n")

    ed.text.insert("1.0", "y")
    ed.open_file("script/main.vns")
    ed.text.insert("1.0", "z")
    ed.open_file("script/chapter2.vns")
    ed.idle()
    assert ed.selected() == "script/chapter2.vns"
    ed.press(ed.text, "<Control-s>")
    assert ed.rows()[:2] == ["* main.vns", "chapter2.vns"]
    assert ed.root.title() == "* " + TITLE
    assert (route_game / "script" / "chapter2.vns").read_bytes() == b"y" + r_bytes(
        "chapter2.vns")
    assert (route_game / "script" / "main.vns").read_bytes() == r_bytes("main.vns")


CAPS = [False, True]              # each key as typed, then with Caps Lock (AC-F44-18)


def test_undo_and_redo_keys(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    text = ed.text
    for caps in CAPS:
        original = ed.body()
        z, y, lock = ("Z", "Y", {"state": CONTROL | LOCK}) if caps else ("z", "y", {})
        text.edit_separator()
        text.insert("1.0", "abc")
        text.edit_separator()
        ed.press(text, f"<Control-{z}>", **lock)
        assert ed.body() == original, caps
        ed.press(text, f"<Control-{y}>", **lock)
        assert ed.body() == "abc" + original, caps
        ed.press(text, f"<Control-{z}>", **lock)
        assert ed.body() == original, caps
        ed.press(text, "<Control-Shift-Z>",
                 **({"state": CONTROL | LOCK | SHIFT} if caps else {}))
        assert ed.body() == "abc" + original, caps


def test_select_all_keeps_the_cursor(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    for caps in CAPS:
        ed.text.tag_remove("sel", "1.0", "end")
        ed.text.mark_set("insert", "3.7")
        if caps:
            ed.press(ed.text, "<Control-A>", state=CONTROL | LOCK)
        else:
            ed.press(ed.text, "<Control-a>")
        assert [str(i) for i in ed.text.tag_ranges("sel")] == ["1.0",
                                                                ed.text.index("end-1c")]
        assert ed.text.index("insert") == "3.7", caps


def test_cut_copy_paste_round_trip_wide_characters(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    root, text = ed.root, ed.text
    try:
        saved = root.clipboard_get()
    except tk.TclError:
        saved = None
    try:
        for caps in CAPS:
            x, c, v = ("X", "C", "V") if caps else ("x", "c", "v")
            lock = {"state": CONTROL | LOCK} if caps else {}
            word = "日本\U0001F600"
            text.tag_remove("sel", "1.0", "end")
            text.insert("end", "\n" + word)
            last = text.index("end-1c").split(".")[0]
            text.tag_add("sel", f"{last}.0", f"{last}.end")
            ed.press(text, f"<Control-{c}>", **lock)
            assert root.clipboard_get() == word, caps
            text.tag_remove("sel", "1.0", "end")
            text.mark_set("insert", "end-1c")
            ed.press(text, f"<Control-{v}>", **lock)
            assert text.get(f"{last}.0", f"{last}.end") == word + word, caps
            text.tag_add("sel", f"{last}.0", f"{last}.end")
            ed.press(text, f"<Control-{x}>", **lock)
            assert text.get(f"{last}.0", f"{last}.end") == "", caps
            assert root.clipboard_get() == word + word, caps
    finally:
        root.clipboard_clear()
        if saved is not None:
            root.clipboard_append(saved)


# --- AC-F44-19: the close dialog --------------------------------------------------------------

def dirty_two(ed) -> None:
    for ref in ("script/chapter2.vns", "script/routes/hana.vns"):
        ed.open_file(ref)
        ed.text.insert("1.0", "x")
    ed.idle()


def run_close(ed) -> None:
    ed.root.tk.call(ed.root.protocol("WM_DELETE_WINDOW"))


def test_escape_close_box_and_cancel_keep_the_editor_open(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    dirty_two(ed)
    for action in ("escape", "close box", 2):          # each closes the real dialog
        seen: dict = {}
        answer_dialog(ed.root, action, seen)
        run_close(ed)
        assert "timed out" not in seen, action
        assert seen["message"] == ("Save changes to 2 files before closing?\n\n"
                                   "script/chapter2.vns\nscript/routes/hana.vns")
        assert seen["buttons"] == ["Save all", "Don't save", "Cancel"]
        assert seen["focused"] == "Save all"
        assert seen["transient"]
        assert not ed.closed, action
        assert ed.root.winfo_exists()
        assert (route_game / "script" / "chapter2.vns").read_bytes() == r_bytes(
            "chapter2.vns")
        assert (route_game / "script" / "routes" / "hana.vns").read_bytes() == r_bytes(
            "routes/hana.vns")


def test_dont_save_closes_and_writes_nothing(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    dirty_two(ed)
    answer_dialog(ed.root, 1, seen := {})
    run_close(ed)
    assert "timed out" not in seen
    assert ed.closed
    assert (route_game / "script" / "chapter2.vns").read_bytes() == r_bytes("chapter2.vns")
    assert (route_game / "script" / "routes" / "hana.vns").read_bytes() == r_bytes(
        "routes/hana.vns")


def test_save_all_saves_both_and_closes(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    dirty_two(ed)
    answer_dialog(ed.root, 0, seen := {})
    run_close(ed)
    assert "timed out" not in seen
    assert ed.closed
    assert (route_game / "script" / "chapter2.vns").read_bytes() == b"x" + r_bytes(
        "chapter2.vns")
    assert (route_game / "script" / "routes" / "hana.vns").read_bytes() == b"x" + r_bytes(
        "routes/hana.vns")


def test_save_all_stops_at_a_failure_and_stays_open(make_editor, route_game, no_dialog):
    ed = make_editor(route_game)
    dirty_two(ed)
    no_dialog.answers.append(0)
    hana = route_game / "script" / "routes" / "hana.vns"
    with read_only(hana):
        run_close(ed)
    assert no_dialog.calls[0][1:] == (("Save all", "Don't save", "Cancel"), 2)
    assert (route_game / "script" / "chapter2.vns").read_bytes() == b"x" + r_bytes(
        "chapter2.vns")
    assert hana.read_bytes() == r_bytes("routes/hana.vns")
    assert ed.errors_shown == [
        "Couldn't save `script/routes/hana.vns`: the file is read-only."]
    assert not ed.closed
    assert "* hana.vns" in ed.rows()
    assert "chapter2.vns" in ed.rows()


def test_closing_with_nothing_unsaved_shows_no_dialog(make_editor, route_game, no_dialog):
    ed = make_editor(route_game)
    ed.text.mark_set("insert", "3.0")
    run_close(ed)
    assert no_dialog.calls == []
    assert ed.closed


def test_one_file_uses_the_singular(make_editor, route_game, no_dialog):
    ed = make_editor(route_game)
    ed.text.insert("1.0", "x")
    no_dialog.answers.append(2)
    run_close(ed)
    assert no_dialog.calls[0][0] == "Save changes to 1 file before closing?\n\nscript/main.vns"


# --- AC-F44-20: line numbers -------------------------------------------------------------------

def test_the_gutter_numbers_every_line_at_its_y(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.open_file("script/chapter2.vns")
    ed.root.update()
    numbers = ed.gutter_numbers()
    assert [entry[0] for entry in numbers] == [str(n) for n in range(1, 13)]
    for text, y, _right in numbers:
        assert abs(y - ed.text.dlineinfo(f"{text}.0")[1]) <= 1, text
    assert len({right for _text, _y, right in numbers}) == 1          # right-aligned


def test_long_lines_dont_wrap_and_scroll_sideways(make_editor, route_game):
    lines = R_SCRIPTS["chapter2.vns"].split("\n")
    lines[4] = "# " + "x" * 1198
    put(route_game, "script/chapter2.vns", "\n".join(lines).encode("utf-8"))
    ed = make_editor(route_game, mapped=True)
    ed.open_file("script/chapter2.vns")
    ed.root.update()
    assert str(ed.text.cget("wrap")) == "none"
    tops = {text: y for text, y, _right in ed.gutter_numbers()}
    assert tops["6"] - tops["5"] == ed.text.dlineinfo("6.0")[1] - ed.text.dlineinfo("5.0")[1]
    assert tops["6"] - tops["5"] == ed.font.metrics("linespace")
    assert ed.text.xview()[0] == 0.0
    ed.text.xview_moveto(0.5)
    ed.root.update()
    assert ed.text.xview()[0] > 0.0


def test_the_last_number_equals_f02s_line_count(make_editor, route_game):
    for name in ("V3", "V4"):
        put(route_game, f"script/{name}.vns", VARIANTS[name])
    ed = make_editor(route_game, mapped=True)
    for name in ("V3", "V4"):
        ed.open_file(f"script/{name}.vns")
        ed.root.update()
        assert ed.gutter_numbers()[-1][0] == str(f02_line_count(VARIANTS[name])), name


def test_the_gutter_width_grows_with_the_digits(make_editor, route_game):
    put(route_game, "script/long.vns", ("# line\n" * 998 + "# line").encode("utf-8"))
    ed = make_editor(route_game)
    ed.open_file("script/long.vns")
    ed.idle()
    zero = ed.font.measure("0")
    assert int(ed.text.index("end-1c").split(".")[0]) == 999
    marker = window.MARKER_CHARS                         # F45's marker column (UI-F45-03)
    assert int(ed.gutter.cget("width")) == (5 + marker) * zero
    ed.text.insert("end", "\n# line 1000")
    ed.idle()
    assert int(ed.gutter.cget("width")) == (6 + marker) * zero
    ed.text.insert("end", "\n# more" * 9000)
    ed.idle()
    assert int(ed.text.index("end-1c").split(".")[0]) == 10_000
    assert int(ed.gutter.cget("width")) == (7 + marker) * zero


def test_after_scrolling_the_first_number_is_the_first_visible_line(make_editor, route_game):
    put(route_game, "script/long.vns", "\n".join(f"# {n}" for n in range(1, 801)).encode())
    ed = make_editor(route_game, mapped=True)
    ed.open_file("script/long.vns")
    ed.text.yview("500.0")
    ed.root.update()
    first = ed.gutter_numbers()[0][0]
    assert first == ed.text.index("@0,0").split(".")[0] == "500"


def test_zoom_keeps_the_gutter_font_equal_to_the_editor_font(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.press(ed.text, "<Control-equal>")
    ed.root.update()
    item = ed.gutter.find_all()[0]
    gutter_font = tk.font.Font(root=ed.root, font=ed.gutter.itemcget(item, "font"))
    assert gutter_font.actual("size") == ed.font.actual("size")
    assert ed.font.cget("size") == -16


# --- AC-F44-22: colors and zoom ----------------------------------------------------------------

def test_the_syntax_tags_use_the_ui_colors(make_editor, route_game):
    ed = make_editor(route_game)
    text = ed.text
    for tag in SYNTAX_TAGS:
        assert text.tag_cget(tag, "foreground") == TAG_COLORS[tag]
        assert text.tag_cget(tag, "font") == ""
    assert ed.font.actual("weight") == "normal" and ed.font.actual("slant") == "roman"
    names = list(text.tag_names())
    assert names.index("sel") > names.index("jump")
    assert text.tag_cget("jump", "background") == "#322E16"
    assert names.index("jump") > names.index(window.TAG_LINE)
    assert text.tag_cget(window.TAG_LINE, "background") == "#2A2D2E"
    assert str(text.cget("selectbackground")) == "#264F78"
    assert text.tag_cget("sel", "foreground") == "#D4D4D4"      # amended 2026-11-02


def test_visible_lines_are_colored_and_follow_edits(make_editor, route_game):
    ed = make_editor(route_game)
    ed.open_file("script/chapter2.vns")
    ed.idle()
    text = ed.text
    ranges = lambda tag: [str(i) for i in text.tag_ranges(tag)]   # noqa: E731
    assert ["6.0", "6.5"] == ranges("keyword")[ranges("keyword").index("6.0"):][:2]
    assert "6.6" in ranges("label_name") and "6.15" in ranges("label_name")
    assert ["11.21", "11.24"] == ranges("text_tag")[:2]
    assert "5.0" in ranges("comment")
    text.insert("12.end", "  # done")
    ed.idle()
    assert ["12.13", "12.19"] == ranges("comment")[-2:]


def test_coloring_counts_emoji_columns_like_tk(make_editor, route_game):
    put(route_game, "script/wide.vns", '    "\U0001F600 Smile." # c'.encode("utf-8"))
    ed = make_editor(route_game)
    ed.open_file("script/wide.vns")
    ed.idle()
    text = ed.text
    quote = [str(i) for i in text.tag_ranges("quote")]
    comment = [str(i) for i in text.tag_ranges("comment")]
    assert text.get(quote[0], quote[1]) == '"\U0001F600 Smile."'
    assert text.get(comment[0], comment[1]) == "# c"


def test_zoom_keys_step_and_stop(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    size = lambda: -int(ed.font.cget("size"))                       # noqa: E731
    assert size() == 14
    ed.press(ed.text, "<Control-equal>")
    assert size() == 16
    ed.press(ed.tree, "<Control-minus>")
    assert size() == 14
    for _ in range(12):
        ed.win.zoom(2)
    assert size() == 32
    ed.press(ed.text, "<Control-plus>")
    assert size() == 32
    for _ in range(14):
        ed.win.zoom(-2)
    assert size() == 10
    ed.press(ed.text, "<Control-0>")
    assert size() == 14


# --- AC-F44-23: indent helpers ---------------------------------------------------------------

INDENT_FILES = {
    "four": 'label a:  # c\n    "Hi"\n    if x >= 1:\n        "y"\n',
    "tabs": 'label t:\n\tif x:\n\t\t"y"\n',
    "two": 'label s:\n  "a"\n  "b"\n  "c"\n  "d"\n',
    "flat": 'label f:\n"a"\n',
}


def indent_editor(make_editor, tmp_path, name):
    game = tmp_path / "my_game"
    put(game, "script/main.vns", INDENT_FILES[name].encode("utf-8"))
    return game, make_editor(game, mapped=True)


def assert_no_mixed_indent(ed, game):
    assert ed.save_current()
    result = load_story(GamePaths.for_game(game))
    assert not [e for e in result.errors if e.code in ("E10", "E10c")]


@pytest.mark.parametrize("name, rows", [
    ("four", [("3.end", " " * 8), ("2.end", " " * 4), ("1.end", " " * 4)]),
    ("tabs", [("2.end", "\t\t")]),
])
def test_enter_keeps_and_adds_indent(make_editor, tmp_path, name, rows):
    """One editor per file. Each row: Enter, then one Ctrl+Z restores the text. Then Enter
    at every row (bottom row first, so the line numbers hold) and F02 loads the saved file
    with no mixed-indent error."""
    game, ed = indent_editor(make_editor, tmp_path, name)
    original = ed.body()
    for cursor, expected in rows:
        ed.text.mark_set("insert", cursor)
        line = int(ed.text.index("insert").split(".")[0])
        ed.press(ed.text, "<Return>")
        assert ed.text.get(f"{line + 1}.0", f"{line + 1}.end") == expected, cursor
        assert ed.text.index("insert") == f"{line + 1}.{len(expected)}"
        ed.press(ed.text, "<Control-z>")
        assert ed.body() == original, cursor
    for cursor, _ in rows:
        ed.text.mark_set("insert", cursor)
        ed.press(ed.text, "<Return>")
    assert_no_mixed_indent(ed, game)


def test_tab_inserts_the_files_unit(make_editor, tmp_path):
    game = tmp_path / "my_game"
    units = {"flat": "    ", "two": "  ", "tabs": "\t"}
    for name in units:
        put(game, f"script/{name}.vns", INDENT_FILES[name].encode("utf-8"))
    ed = make_editor(game, mapped=True)
    for name, unit in units.items():
        ed.open_file(f"script/{name}.vns")
        original = ed.body()
        ed.text.mark_set("insert", "2.0")
        ed.press(ed.text, "<Tab>")
        assert ed.text.get("2.0", "2.end").startswith(unit), name
        assert ed.text.get("2.0", "2.end")[len(unit):] == original.split("\n")[1]
        assert ed.focus() is ed.text
        ed.press(ed.text, "<Control-z>")
        assert ed.body() == original, name


def test_tab_and_shift_tab_on_selected_lines(make_editor, tmp_path):
    game, ed = indent_editor(make_editor, tmp_path, "two")
    text = ed.text
    text.insert("4.0", " ")                     # line 4 now has 3 spaces
    original = ed.body()
    text.tag_add("sel", "3.0", "5.end")
    ed.press(text, "<Tab>")
    assert [text.get(f"{n}.0", f"{n}.end") for n in (2, 3, 4, 5)] == [
        '  "a"', '    "b"', '     "c"', '    "d"']
    ed.press(text, "<Control-z>")
    assert ed.body() == original
    text.tag_add("sel", "3.0", "5.end")
    ed.press(text, "<Shift-Tab>")
    assert [text.get(f"{n}.0", f"{n}.end") for n in (3, 4, 5)] == ['"b"', ' "c"', '"d"']
    text.tag_add("sel", "3.0", "5.end")
    ed.press(text, "<Shift-Tab>")
    assert [text.get(f"{n}.0", f"{n}.end") for n in (3, 4, 5)] == ['"b"', '"c"', '"d"']
    ed.press(text, "<Control-z>")
    assert [text.get(f"{n}.0", f"{n}.end") for n in (3, 4, 5)] == ['"b"', ' "c"', '"d"']


# --- AC-F44-24: changes made outside the editor ---------------------------------------------

def focus_in(ed) -> None:
    ed.win._last_outside_check = float("-inf")
    ed.root.event_generate("<FocusIn>")
    ed.root.update_idletasks()


def test_a_new_file_on_disk_appears_in_order(make_editor, route_game):
    ed = make_editor(route_game)
    put(route_game, "script/chapter4.vns", b'label four:\n    "Four."\n')
    focus_in(ed)
    assert ed.rows() == ["main.vns", "chapter2.vns", "chapter3.vns", "chapter4.vns",
                         "hana.vns"]
    assert ed.tree.item("script", "text") == "Script (5)"
    assert ed.selected() == "script/main.vns"


def test_a_clean_file_changed_on_disk_reloads_at_the_same_line(make_editor, route_game):
    ed = make_editor(route_game)
    ed.text.mark_set("insert", "5.3")
    new = R_SCRIPTS["main.vns"].replace("Opening line.", "A new first line.")
    put(route_game, "script/main.vns", new.encode("utf-8"))
    focus_in(ed)
    assert ed.body() == new.rstrip("\n")
    assert ed.text.index("insert").split(".")[0] == "5"
    assert ed.rows()[0] == "main.vns"
    assert not ed.root.title().startswith("* ")


@pytest.mark.parametrize("answer", [0, 1], ids=["keep mine", "use the file on disk"])
def test_a_dirty_file_changed_on_disk_asks(make_editor, route_game, no_dialog, answer):
    ed = make_editor(route_game)
    ed.open_file("script/chapter2.vns")
    ed.text.insert("1.0", "x")
    mine = ed.body()
    disk = R_SCRIPTS["chapter2.vns"] + "# added outside\n"
    put(route_game, "script/chapter2.vns", disk.encode("utf-8"))
    no_dialog.answers.append(answer)
    focus_in(ed)
    assert no_dialog.calls == [(
        "`script/chapter2.vns` changed on disk while you were editing it. "
        "Keep which version?", ("Keep mine", "Use the file on disk"), 0)]
    if answer == 0:
        assert ed.body() == mine
        assert ed.rows()[1] == "* chapter2.vns"
    else:
        assert ed.body() == disk.rstrip("\n")
        assert ed.rows()[1] == "chapter2.vns"
        assert not ed.root.title().startswith("* ")
    focus_in(ed)                                # not asked again for the same change
    assert len(no_dialog.calls) == 1


def test_escape_in_the_changed_on_disk_dialog_keeps_mine(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.open_file("script/chapter2.vns")
    ed.text.insert("1.0", "x")
    mine = ed.body()
    put(route_game, "script/chapter2.vns", b"# replaced outside\n")
    answer_dialog(ed.root, "escape", seen := {})
    focus_in(ed)
    assert "timed out" not in seen
    assert seen["buttons"] == ["Keep mine", "Use the file on disk"]
    assert seen["focused"] == "Keep mine"
    assert ed.body() == mine
    assert ed.rows()[1] == "* chapter2.vns"


def test_focus_events_check_the_disk_at_most_once_a_second(make_editor, route_game,
                                                           monkeypatch):
    ed = make_editor(route_game)
    clock = [100.0]
    patch_studio(monkeypatch, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    checks = []
    monkeypatch.setattr(ed.win, "check_outside_changes", lambda: checks.append(clock[0]))
    ed.win._last_outside_check = float("-inf")
    ed.root.event_generate("<FocusIn>")
    clock[0] += 0.2
    ed.root.event_generate("<FocusIn>")
    assert checks == [100.0]
    clock[0] += 1.0
    ed.root.event_generate("<FocusIn>")
    assert len(checks) == 2


# --- AC-F44-25: where Preview starts ---------------------------------------------------------

BUFFER_B = ['# label fake:', 'default x = 0', 'label club_poem:', '    "A."',
            '    label inner:', '"label quoted:"', 'label\tafter_tab:', '    "B."']


def test_the_start_label_follows_the_cursor(make_editor, route_game):
    put(route_game, "script/b.vns", "\n".join(BUFFER_B).encode("utf-8"))
    ed = make_editor(route_game)
    ed.open_file("script/b.vns")
    expected = [None, None, "club_poem", "club_poem", "club_poem", "club_poem",
                "after_tab", "after_tab"]
    for line in range(1, 9):
        ed.text.mark_set("insert", f"{line}.0")
        ed.idle()
        shown = ed.start_label.cget("text")
        assert shown == (expected[line - 1] or "the beginning"), line
        assert label_above(BUFFER_B, line) == expected[line - 1]


def test_the_start_label_updates_when_switching_files(make_editor, route_game):
    ed = make_editor(route_game)
    ed.open_file("script/chapter2.vns")
    ed.text.mark_set("insert", "4.0")
    ed.idle()
    assert ed.start_label.cget("text") == "the beginning"
    ed.text.mark_set("insert", "9.0")
    ed.idle()
    assert ed.start_label.cget("text") == "club_poem"
    ed.open_file("script/routes/hana.vns")
    ed.idle()
    assert ed.start_label.cget("text") == "hana_route"
    ed.open_file("script/main.vns")
    ed.idle()
    assert ed.start_label.cget("text") == "the beginning"
    ed.open_file("script/chapter2.vns")
    ed.idle()
    assert ed.start_label.cget("text") == "club_poem"


def test_the_start_label_follows_edits(make_editor, route_game):
    ed = make_editor(route_game)
    ed.text.mark_set("insert", "7.0")
    ed.idle()
    assert ed.start_label.cget("text") == "start"
    ed.text.delete("5.0", "5.end")
    ed.text.insert("5.0", "label renamed:")
    ed.text.mark_set("insert", "7.0")
    ed.idle()
    assert ed.start_label.cget("text") == "renamed"


# --- AC-F44-32: moving between areas by keyboard ----------------------------------------------

def test_f6_cycles_the_five_areas(make_editor, route_game):
    """Amended by F45 (AC-F44-32): start values → problems → help → project → editor."""
    ed = make_editor(route_game, mapped=True)
    order = [ed.start_values, ed.problems, ed.help_text, ed.tree, ed.text]
    widget = ed.text
    for expected in order:
        ed.press(widget, "<F6>")
        widget = ed.focus()
        assert widget is expected
    for expected in reversed([ed.text] + order[:-1]):
        ed.press(widget, "<Shift-F6>")
        widget = ed.focus()
        assert widget is expected
    ed.press(ed.preview_button, "<F6>")
    assert ed.focus() is ed.problems


def test_tab_indents_in_the_editor_and_moves_focus_elsewhere(make_editor, route_game):
    ed = make_editor(route_game, mapped=True)
    ed.text.mark_set("insert", "6.0")
    ed.press(ed.text, "<Tab>")
    assert ed.focus() is ed.text
    assert ed.text.get("6.0", "6.end") == "        \"Opening line.\""
    ed.press(ed.start_values, "<Tab>")
    assert ed.focus() is ed.preview_button
    ed.press(ed.preview_button, "<Shift-Tab>")
    assert ed.focus() is ed.start_values
    ed.press(ed.preview_button, "<Tab>")
    assert ed.focus() is ed.problems
    ed.press(ed.problems, "<Tab>")
    assert ed.focus() is ed.tree
    ed.press(ed.tree, "<Tab>")
    assert ed.focus() is ed.text
    ed.press(ed.start_values, "<Shift-Tab>")
    assert ed.focus() is ed.text
    if ed.root.tk.call("tk", "windowingsystem") == "x11":
        ed.press(ed.preview_button, "<ISO_Left_Tab>")       # X11's Shift+Tab
        assert ed.focus() is ed.start_values
    assert ed.body(ed.start_values) == ""


def test_no_key_binding_in_the_main_window_reacts_to_escape(make_editor, route_game):
    ed = make_editor(route_game)
    root = ed.root

    def walk(widget):
        yield widget
        for child in widget.winfo_children():
            yield from walk(child)

    # The editor's own bindings: each widget, the editor tag, the window, and "all".
    widgets = list(walk(root)) + ed.win._editor_widgets()
    tags = {str(widget) for widget in widgets} | {window.EditorWindow._editor_bindtag, "all"}
    for tag in tags:
        sequences = root.tk.splitlist(root.tk.call("bind", tag))
        assert not [s for s in sequences if "Escape" in s], tag
    # Tk's own class bindings do nothing here: Text's is empty, and the project tree is a
    # single-selection Treeview.
    assert root.bind_class("Text", "<Key-Escape>").strip() == "# nothing"
    assert str(ed.tree.cget("selectmode")) == "browse"


# --- Change hook ---------------------------------------------------------------------------

def test_tk_errors_from_the_widget_command_are_unchanged(make_editor, route_game):
    ed = make_editor(route_game)
    with pytest.raises(tk.TclError, match='tagged with "sel"'):
        ed.text.index("sel.first")
    ed.text.delete("1.0", "1.0")                # a no-op edit still goes through the hook
    ed.idle()


def test_the_astral_probe_matches_this_tk(make_editor, route_game):
    ed = make_editor(route_game)
    probe = tk.Text(ed.root)
    probe.insert("1.0", "\U0001F600")
    assert ed.astral_columns == int(probe.index("end-1c").split(".")[1])


# --- run_editor (04 §7.1; the start-up rows of AC-F44-13 run in-process here) ----------------

def test_run_editor_opens_the_game_and_returns_0_when_closed(route_game, monkeypatch):
    seen = {}

    def mainloop(self, n=0):
        seen["title"] = self.title()
        self.tk.call(self.protocol("WM_DELETE_WINDOW"))

    new_root().destroy()
    monkeypatch.setattr(tk.Tk, "mainloop", mainloop)
    assert editor_package.run_editor(route_game) == 0
    assert seen["title"] == TITLE


def test_no_tkinter_message_per_platform():
    for platform, fragment in [
        ("win32", "choose Modify, and tick 'tcl/tk and IDLE'."),
        ("linux", "python3-tk"),
        ("darwin", f"brew install python-tk@3.{sys.version_info.minor}"),
    ]:
        assert fragment in editor_package.no_tkinter_message(platform), platform


def test_run_editor_without_tkinter_prints_one_line(route_game, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert editor_package.run_editor(route_game) == 1
    err = capsys.readouterr().err
    assert err == editor_package.no_tkinter_message() + "\n"


def test_run_editor_without_a_display_prints_one_line(route_game, monkeypatch, capsys):
    def no_display(*args, **kwargs):
        raise tk.TclError("no display name and no $DISPLAY environment variable")

    monkeypatch.setattr(tk, "Tk", no_display)
    assert editor_package.run_editor(route_game) == 1
    assert capsys.readouterr().err == "The editor needs a desktop session; no display was found.\n"


def test_run_editor_on_a_missing_folder_prints_runs_message(tmp_path, capsys):
    assert editor_package.run_editor(tmp_path / "nowhere") == 1
    err = capsys.readouterr().err
    assert err.startswith("Can't find the game folder") and err.count("\n") == 1
    assert "Traceback" not in err
