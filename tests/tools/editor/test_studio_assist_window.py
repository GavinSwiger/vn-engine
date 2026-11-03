"""Studio's writing help and visualizer in the window (F45 step 5; ``06`` AC-F45-38, 39,
40, 41, 43, 45 and 46, their Tk rows; the pure halves are ``test_assist.py`` and
``test_storymap.py``).

Built on game S with the fake check runner of ``test_studio_window.py``. The check's name
index and links are set straight on the window (``check_names``, ``check_links``,
``check_stale``), as step 4 does when a ``DONE`` arrives."""

import base64
import struct
import zlib

import pytest

from engine.script.statement_docs import GROUPS, all_docs, docs_for
from tests.tools.editor.conftest import png

tk = pytest.importorskip("tkinter")
window = pytest.importorskip("engine.tools.editor.window")
views = pytest.importorskip("engine.tools.editor.views")
from tests.tools.editor.test_studio_window import studio, tab  # noqa: E402,F401
from tests.tools.editor.test_window import take_focus  # noqa: E402

pytestmark = pytest.mark.tk

# AC-F45-37's name index N, as ``(name, file, line)`` rows.
N = {
    "label": [(n, None, None) for n in ("start", "club", "bridge", "Bridge_old", "river")],
    "image": [(n, None, None) for n in ("hana happy", "hana smile", "bg room")],
    "character": [("hana", None, None)],
    "transition": [("dissolve", None, None), ("fade", None, None)],
    "position": [("left", None, None), ("right", None, None)],
    "audio": [("audio/bgm/theme.ogg", None, None)],
}

# Game S's labels and links, as the check child sends them (AC-F45-07, AC-F45-04).
S_LABELS = [("start", "script/main.vns", 4), ("club", "script/ch2.vns", 1),
            ("bridge", "script/ch2.vns", 8), ("river", "script/ch2.vns", 10),
            ("side", "script/ch2.vns", 12)]
S_LINKS = [("start", "club", "call", "script/main.vns", 7),
           ("start", "bridge", "jump", "script/main.vns", 8),
           ("club", "river", "menu", "script/ch2.vns", 4)]


def set_line(ed, number: int, text: str) -> None:
    """Replace line ``number`` of the editor and put the cursor at its end."""
    widget = ed.text
    while int(widget.index("end-1c").split(".")[0]) < number:
        widget.insert("end-1c", "\n")
    widget.delete(f"{number}.0", f"{number}.end")
    widget.insert(f"{number}.0", text)
    widget.mark_set("insert", f"{number}.end")
    ed.root.update()


def line(ed, number: int) -> str:
    return ed.text.get(f"{number}.0", f"{number}.end")


def rows(ed) -> list[tuple[str, str]]:
    popup = ed.popup
    return list(zip(popup.names.get(0, "end"), popup.kinds.get(0, "end")))


def type_space(ed) -> None:
    """A real space key press in the editor (inserted by Tk's own Text binding)."""
    ed.press(ed.text, "<KeyPress>", keysym="space")


# --- AC-F45-38: the completion list ----------------------------------------------------------

def test_ac38_the_completion_list(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    ed.win.check_names = N
    popup = ed.popup
    set_line(ed, 9, "    jump b")
    ed.press(ed.text, "<Control-space>")
    assert popup.is_open and bool(popup.window.overrideredirect())
    assert popup.window.winfo_ismapped()
    assert rows(ed) == [("bridge", "label"), ("Bridge_old", "label")]
    assert popup.kinds.cget("foreground") == "#9D9D9D"
    assert ed.focus() is ed.text                        # the editor keeps the keys
    ed.press(ed.text, "<Down>")
    ed.press(ed.text, "<Return>")
    assert line(ed, 9) == "    jump Bridge_old" and not popup.is_open

    set_line(ed, 9, "    jump b")                     # Tab also accepts
    ed.press(ed.text, "<Control-space>")
    ed.press(ed.text, "<Tab>")
    assert line(ed, 9) == "    jump bridge" and not popup.is_open

    set_line(ed, 9, "    jump b")                     # typing filters; bridge stays first
    ed.press(ed.text, "<Control-space>")
    ed.press(ed.text, "<KeyPress>", keysym="r")
    assert line(ed, 9) == "    jump br"
    assert popup.is_open and rows(ed)[0] == ("bridge", "label")

    ed.press(ed.text, "<Escape>")                     # Esc closes, text unchanged
    assert not popup.is_open and line(ed, 9) == "    jump br"
    ed.press(ed.text, "<Control-space>")              # another line closes it
    ed.text.mark_set("insert", "8.0")
    ed.root.update()
    assert not popup.is_open and line(ed, 9) == "    jump br"
    ed.text.mark_set("insert", "9.end")
    ed.press(ed.text, "<Control-space>")              # focus leaving closes it
    assert popup.is_open
    take_focus(ed.tree)
    assert not popup.is_open and line(ed, 9) == "    jump br"

    many = dict(N, label=[(f"l{n:02}", None, None) for n in range(30)])
    ed.win.check_names = many                       # at most 10 rows show
    set_line(ed, 9, "    jump l")
    ed.press(ed.text, "<Control-space>")
    assert len(rows(ed)) == 30 and popup.visible_rows() == 10
    ed.press(ed.text, "<Escape>")

    set_line(ed, 9, "    x")                         # with no list open, Tab indents
    ed.text.mark_set("insert", "9.4")
    ed.press(ed.text, "<Tab>")
    assert line(ed, 9) == "        x" and not popup.is_open


# --- AC-F45-39: the list opens by itself -----------------------------------------------------

def test_ac39_the_list_opens_by_itself(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    ed.win.check_names = N
    for typed, opens in (("    jump", True), ("    show hana happy with", True),
                         ('    "Hi', False), ("    pause", False)):
        set_line(ed, 9, typed)
        type_space(ed)
        assert line(ed, 9) == typed + " ", typed
        assert ed.popup.is_open is opens, typed
        ed.win.close_completion()


# --- AC-F45-40: Insert ------------------------------------------------------------------------

def test_ac40_insert_menu_and_one_step_insert(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    menu = ed.insert_menu
    groups = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
    with_docs = [g for g in GROUPS if any(d.insert and d.group == g for d in all_docs())]
    assert groups == with_docs
    for group in groups:
        sub = ed.insert_submenus[group]
        titles = [sub.entrycget(i, "label") for i in range(sub.index("end") + 1)]
        assert titles == [d.title for d in all_docs() if d.insert and d.group == group]
    every = [t for g in groups for t in (ed.insert_submenus[g].entrycget(i, "label")
             for i in range(ed.insert_submenus[g].index("end") + 1))]
    for key in ("dialogue", "narration", "$"):
        assert docs_for(key)[0].title in every
    for key in ("elif", "else"):
        assert all(d.title not in every for d in docs_for(key))

    set_line(ed, 9, "    ")                            # a blank line in label start
    before = ed.body()
    ed.insert_submenus["Choices"].invoke("Menu")
    ed.root.update()
    assert [line(ed, n) for n in range(9, 14)] == [
        "    menu:", '        "Go to the river":', "            jump river",
        '        "Stay here":', '            "You stay a while."']
    first, last = ed.text.tag_ranges("sel")
    assert ed.text.get(first, last) == "Go to the river"
    assert tab(ed) == "Editor" and ed.current.dirty
    ed.press(ed.text, "<Control-z>")
    assert ed.body() == before


# --- AC-F45-41: Help ---------------------------------------------------------------------------

def test_ac41_the_help_pane_follows_the_cursor(studio, studio_game):
    ed = studio(studio_game)
    jump = docs_for("jump")[0]
    ed.text.mark_set("insert", "8.6")                 # main.vns line 8: "    jump bridge"
    ed.root.update_idletasks()
    shown = ed.help_pane.content()
    for part in (jump.title, jump.syntax, jump.summary, jump.example, f"Docs: {jump.docs}"):
        assert part in shown
    assert "Docs: jump" in shown
    set_line(ed, 9, "")
    assert ed.help_pane.content() == "No help for this line."
    ed.text.mark_set("insert", "6.2")                 # '    hana "Hi."'
    ed.root.update_idletasks()
    assert ed.help_pane.content().startswith(docs_for("dialogue")[0].title)


# --- AC-F45-43: the story map view -------------------------------------------------------------

def test_ac43_the_story_map_view(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    ed.win.check_names = {"label": S_LABELS}
    ed.win.check_links = S_LINKS
    ed.press(ed.text, "<Control-Key-2>")
    assert tab(ed) == "Story map" and ed.focus() is ed.map_canvas
    view, canvas = ed.story_map, ed.map_canvas
    m = view.layout
    for name, ref, number in S_LABELS:
        i = m.index_of(name)
        x0, y0, x1, y1 = canvas.coords(canvas.find_withtag(f"rect{i}")[0])
        assert (x1 - x0, y1 - y0) == (160, 40)
        assert canvas.itemcget(f"name{i}", "text") == name
        assert canvas.itemcget(f"where{i}", "text") == f"{ref}:{number}"
    start = m.index_of("start")
    # F45 08 §8: start's accent bar inside its left edge replaces the 2 px border.
    assert float(canvas.itemcget(f"rect{start}", "width")) == 1
    assert float(canvas.itemcget(f"rect{m.index_of('club')}", "width")) == 1
    assert canvas.itemcget(f"rect{start}", "fill") == "#2B2B2B"
    assert canvas.itemcget(f"startbar{start}", "fill") == "#0078D4"
    assert not canvas.find_withtag(f"startbar{m.index_of('club')}")
    assert "start" in canvas.itemcget(f"marks{start}", "text").split(", ")
    styles = {kind: (canvas.itemcget(item, "arrow"), canvas.itemcget(item, "dash"),
                     canvas.itemcget(item, "fill")) for item, kind in view.edge_items}
    assert styles == {"jump": ("last", "", "#808080"), "call": ("last", "6 4", "#808080"),
                      "menu": ("last", "2 4", "#808080")}
    assert view.legend_words() == ["jump", "call", "menu", "ending", "chapter", "minigame"]

    def centre(name):
        x0, y0, x1, y1 = canvas.coords(f"rect{m.index_of(name)}")
        return int((x0 + x1) / 2 - canvas.canvasx(0)), int((y0 + y1) / 2 - canvas.canvasy(0))

    x, y = centre("river")                       # a click opens the label's line beside
    canvas.event_generate("<Button-1>", x=x, y=y)
    canvas.event_generate("<ButtonRelease-1>", x=x, y=y)     # F46: the release opens it
    ed.root.update()
    assert tab(ed) == "Story map" and ed.current.ref == "script/ch2.vns"
    assert ed.text is ed.side_text and ed.text.index("insert") == "10.0"
    ed.close_side()
    ed.press(canvas, "<Control-Return>")                 # Ctrl+Enter: the Editor tab
    assert tab(ed) == "Editor" and ed.text.index("insert") == "10.0"
    ed.text.mark_set("insert", "1.0")
    ed.press(ed.text, "<Control-Key-2>")                 # Enter on the focused box
    assert view.focused_name() == "river"
    ed.press(canvas, "<Return>")
    assert ed.current.ref == "script/ch2.vns" and ed.text.index("insert") == "10.0"

    ed.press(ed.text, "<Control-Key-2>")
    view.focus_box(start)
    ed.press(canvas, "<Right>")                          # Right: a column-1 box
    assert m.boxes[view.focused].column == 1
    ring = canvas.coords(view.ring)
    x0, y0, x1, y1 = canvas.coords(f"rect{view.focused}")
    assert ring == [x0 - 3, y0 - 3, x1 + 3, y1 + 3]
    assert canvas.itemcget(view.ring, "outline") == "#007FD4"
    assert float(canvas.itemcget(view.ring, "width")) == 2
    view.focus_box(start)                                # Tab selects start's arrows (F46
    names = []                                           # C2); Enter focuses the target
    for _ in range(3):
        ed.press(canvas, "<Tab>")
        names.append(view.selected_edge()[1])
    assert names == ["club", "bridge", "club"] and view.focused == start
    ed.press(canvas, "<Return>")
    assert view.focused_name() == "club"

    for _ in range(10):
        ed.press(canvas, "<Control-equal>")
    assert view.zoom == 200
    x0, _, x1, _ = canvas.coords(f"rect{start}")
    assert x1 - x0 == 320
    for _ in range(10):
        ed.press(canvas, "<Control-minus>")
    assert view.zoom == 50
    assert ed.font.cget("size") == -14                   # the editor's text is untouched

    ed.win.check_stale = True                            # a check that didn't load
    ed.root.update()
    assert "out of date" in view.note.cget("text") and len(view.layout.boxes) == 5

    ed.answers.append("river")                           # Go to label (Ctrl+G)
    ed.text.mark_set("insert", "1.0")
    ed.press(ed.text, "<Control-g>")
    assert ed.dialogs[-1][1] == window.GO_TO_LABEL_ASK
    assert tab(ed) == "Editor" and ed.current.ref == "script/ch2.vns"
    assert ed.text.index("insert") == "10.0"


# --- AC-F45-70: the side editor (2026-11-02, user: map opens editor to the side) ---------------

def test_ac70_the_map_opens_the_editor_beside_it(studio, studio_game):
    ed = studio(studio_game, mapped=True)
    ed.win.check_names = {"label": S_LABELS}
    ed.win.check_links = S_LINKS
    ed.press(ed.text, "<Control-Key-2>")
    canvas = ed.map_canvas
    ed.story_map.focus_box(ed.story_map.layout.index_of("river"))
    ed.press(canvas, "<Return>")                         # Enter: ch2 line 10 beside the map
    side, main = ed.side_text, ed.current.widget
    assert tab(ed) == "Story map" and ed.focus() is side and ed.text is side
    assert ed.side_name.cget("text") == "script/ch2.vns" and side.index("insert") == "10.0"
    # F46 step 2 (06 §2, A-F45-70): the side pane has tabs Events | Script, showing Script.
    assert ed.side_tabs.words() == ["Events", "Script"]
    assert ed.side_book.tab(ed.side_book.select(), "text") == "Script"
    assert side.tag_ranges("jump") and ed.side_gutter.find_all()
    assert abs(ed.side_frame.winfo_width() / ed.map_split.winfo_width() - 0.45) < 0.05
    assert side.cget("font") == main.cget("font")
    before = main.get("10.0", "10.end")
    ed.press(side, "<KeyPress>", keysym="x")             # one buffer with the Editor tab's
    assert main.get("10.0", "10.end") == "x" + before and ed.current.dirty
    assert ed.side_name.cget("text") == "* script/ch2.vns"
    ed.press(side, "<Control-z>")
    assert main.get("10.0", "10.end") == before
    ed.press(side, "<KeyPress>", keysym="x")
    ed.press(side, "<Control-s>")
    text = (studio_game / "script/ch2.vns").read_text(encoding="utf-8")
    assert text.splitlines()[9] == "x" + before and not ed.current.dirty
    ed.press(side, "<F6>")                               # F6: side editor → ▶ Play (F47)
    assert ed.focus() is ed.play_button
    ed.press(ed.play_button, "<Shift-F6>")
    assert ed.focus() is side
    ed.press(side, "<Escape>")                           # Esc: closed, focus on the map
    assert ed.side_text is None and ed.focus() is canvas
    assert str(ed.side_frame) not in [str(p) for p in ed.map_split.panes()]


# --- AC-F45-45: the image preview --------------------------------------------------------------

def real_png(width: int, height: int) -> bytes:
    """A decodable RGB PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


GIF_1X1 = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
CAP = views.PREVIEW_MAX_BYTES


def test_ac45_the_image_preview(studio, studio_game, monkeypatch):
    bg = studio_game / "images" / "bg"
    (bg / "room.png").write_bytes(real_png(400, 300))
    (studio_game / "images" / "hana" / "happy.png").write_bytes(real_png(2, 2))
    (bg / "sky.gif").write_bytes(GIF_1X1)
    (bg / "wide.webp").write_bytes(b"RIFF\x1a\x00\x00\x00WEBPVP8X" + bytes(18))
    (bg / "huge.png").write_bytes(png(5000, 5000))
    (bg / "corrupt.png").write_bytes(png(10, 10) + b"garbage")
    with open(bg / "sparse.png", "wb") as sparse:
        sparse.write(png(10, 10))
        sparse.truncate(CAP + 1)
    ed = studio(studio_game)
    calls: list[dict] = []
    real = tk.PhotoImage

    def spy(*args, **kwargs):
        calls.append(dict(kwargs, _args=args))
        return real(*args, **kwargs)

    monkeypatch.setattr(tk, "PhotoImage", spy)
    pane = ed.asset_pane

    def show(ref):
        calls.clear()
        ed.win.show_asset(ref, box=(200, 200))
        return pane.text()

    room = (bg / "room.png").stat().st_size
    text = show("images/bg/room.png")
    assert tab(ed) == "Asset" and pane.step == 2 and pane.photo.width() == 200
    for fact in ("400 × 300", f"{room:,} bytes", "Image name: bg room"):
        assert fact in text
    assert any("data" in c for c in calls)
    pane.copy_button.invoke()
    assert ed.root.clipboard_get() == "bg room"
    show("images/hana/happy.png")
    assert pane.step == 1 and pane.photo.width() == 2           # never upscaled
    show("images/bg/sky.gif")
    assert pane.step == 1 and pane.photo is not None
    for ref in ("images/bg/photo.jpg", "images/bg/wide.webp"):
        text = show(ref)
        assert views.NO_PREVIEW in text and "File size:" in text and pane.photo is None
        assert calls == [], ref
    text = show("images/bg/huge.png")
    assert "5000 × 5000" in text and views.NO_PREVIEW in text and calls == []
    text = show("images/bg/sparse.png")
    assert f"{CAP + 1:,} bytes" in text and views.NO_PREVIEW in text and calls == []
    text = show("images/bg/corrupt.png")
    assert "10 × 10" in text and views.NO_PREVIEW in text and pane.photo is None
    assert all("file" not in c for c in calls)


# --- AC-F45-46: menus, keys and tabs -----------------------------------------------------------

HANDLERS = ("new_script_file", "add_files", "rename_selected", "delete_selected",
            "save_current", "save_all", "complete", "go_to_label", "show_tab", "play_scene",
            "play_from_start", "stop_game", "check_now")


def test_ac46_menus_keys_and_tabs(studio, studio_game, monkeypatch):
    calls: list[tuple] = []
    for name in HANDLERS:
        monkeypatch.setattr(window.EditorWindow, name,
                            lambda self, *args, n=name: calls.append((n, *args)))
    ed = studio(studio_game, mapped=True)
    assert ed.root.title() == "my_game — vn-engine Studio"
    assert [ed.notebook.tab(t, "text") for t in ed.notebook.tabs()] == [
        "Editor", "Story map", "Asset", "Outline"]   # Outline: AC-F45-54
    bar = ed.menubar
    assert [bar.entrycget(i, "label") for i in range(bar.index("end") + 1)] == [
        "File", "Edit", "Insert", "Story", "View", "Run", "Help"]   # Story: AC-F46-33
    rows = [  # (menu, entry, key widget, key, the handler call both make)
        (ed.file_menu, "New script file", ed.text, "<Control-n>", ("new_script_file",)),
        (ed.file_menu, "Add files…", ed.text, "<Control-Shift-O>", ("add_files",)),
        (ed.file_menu, "Rename", ed.tree, "<F2>", ("rename_selected",)),
        (ed.file_menu, "Delete", ed.tree, "<Delete>", ("delete_selected",)),
        (ed.file_menu, "Save", ed.text, "<Control-s>", ("save_current",)),
        (ed.file_menu, "Save all", ed.text, "<Control-Shift-S>", ("save_all",)),
        (ed.edit_menu, "Complete", ed.text, "<Control-space>", ("complete",)),
        (ed.edit_menu, "Go to label…", ed.text, "<Control-g>", ("go_to_label",)),
        (ed.view_menu, "Editor", ed.text, "<Control-Key-1>", ("show_tab", 0)),
        (ed.view_menu, "Story map", ed.text, "<Control-Key-2>", ("show_tab", 1)),
        (ed.view_menu, "Asset", ed.text, "<Control-Key-3>", ("show_tab", 2)),
        (ed.run_menu, "Play", ed.text, "<Shift-F5>", ("play_from_start",)),   # F47
        (ed.run_menu, "Play this scene", ed.text, "<F5>", ("play_scene",)),
        (ed.run_menu, "Stop", ed.text, "<Control-F2>", ("stop_game",)),
        (ed.run_menu, "Check now", ed.text, "<F7>", ("check_now",)),
    ]
    for menu, entry, widget, key, call in rows:
        calls.clear()
        menu.invoke(entry)
        assert calls == [call], entry
        calls.clear()
        ed.press(widget, key)
        assert calls == [call], key
    before = ed.body()
    ed.text.mark_set("insert", "1.0")
    calls.clear()
    ed.press(ed.text, "<Delete>")                        # Delete in the text: one character
    assert ed.body() == before[1:] and calls == []
    assert (studio_game / "script" / "main.vns").exists()


# --- AC-F45-57, 58: text tags in the window (2026-11-02, user: keep Studio updated) ---------

def test_ac57_58_text_tag_completion_and_help(studio, studio_game):
    from engine.script.tag_docs import tag_doc, tag_names

    ed = studio(studio_game, mapped=True)
    popup = ed.popup
    set_line(ed, 9, '    hana "Hi ')
    ed.press(ed.text, "<KeyPress>", keysym="braceleft")      # "{" opens the tag list
    assert line(ed, 9) == '    hana "Hi {' and popup.is_open
    assert rows(ed) == [(n, "tag") for n in sorted(tag_names())]
    ed.press(ed.text, "<Return>")
    assert line(ed, 9) == '    hana "Hi {b' and not popup.is_open
    ed.text.insert("insert", "}x{")
    ed.press(ed.text, "<KeyPress>", keysym="slash")          # "{/" offers the open tag
    assert line(ed, 9) == '    hana "Hi {b}x{/' and popup.is_open
    assert rows(ed) == [("b", "close tag")]
    ed.press(ed.text, "<Tab>")
    assert line(ed, 9) == '    hana "Hi {b}x{/b' and not popup.is_open

    ed.text.mark_set("insert", "9.15")                       # inside "{b}"
    ed.root.update_idletasks()
    b = tag_doc("b")
    assert ed.help_pane.content().split("\n") == [
        b.title, b.syntax, b.summary, b.example, "Docs: Text tags"]
    ed.text.mark_set("insert", "9.17")                       # on "x": the dialogue doc
    ed.root.update_idletasks()
    assert ed.help_pane.content().startswith(docs_for("dialogue")[0].title)
