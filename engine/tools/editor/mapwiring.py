"""Studio's Story map tab (PR-F45-18, 19; F46 ``04`` §6), as the ``MapWiring`` mixin of
``window.EditorWindow``: the map, its side pane (Events | Script, a Tk peer of the file's
text), following the text (``scenes.FOLLOW_MS`` after the last change ``follow`` re-reads
the changed scripts' label chunks), the layout file and the map history (§6.8–6.10), and the
Story menu's, map's and Events list's actions (§6.11).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from engine.script.labelgraph import LabelLink
from engine.script.menu import Menu
from engine.script.messages import show
from engine.tools.editor import files, formdialogs, layoutfile, scenes, scriptedit
from engine.tools.editor.checker import NameEntry
from engine.tools.editor.dialogs import ask, ask_text, show_error
from engine.tools.editor.document import ScriptDocument, open_document
from engine.tools.editor.syntax import PLAIN_COLOR, indent_unit
from engine.tools.editor.eventsview import EventsView
from engine.tools.editor.storyeditor import StoryEditor, apply_edits
from engine.tools.editor.storymap import (
    Box,
    COLUMN_STEP,
    MapStep,
    place_free,
    label_notes,
    layout_places,
    map_undo,
    undo_blocked_text,
)
from engine.tools.editor.theme import THEME
from engine.tools.editor.views import DIRTY_MARK, StoryMapView, TabStrip, autohide
from engine.tools.editor.studiolook import (
    BACKGROUND,
    GUTTER_BACKGROUND,
    MAP_MIN_WIDTH,
    PANEL_INSET,
    SASH_WIDTH,
    SIDE_MIN_WIDTH,
    SIDE_SHARE,
    line_of,
)

if TYPE_CHECKING:
    from engine.tools.editor.window import OpenFile

SIDE_OPEN_TAB = "Open in Editor tab"     # the Story map's side editor (2026-11-02)
SIDE_CLOSE = "\u2715"
SIDE_TAB_EVENTS = "Events"              # the side pane's tabs (F46 C1, 04 \u00a76.11)
SIDE_TAB_SCRIPT = "Script"
SIDE_PAGES = ("events", "script")       # side_tab values, in tab order
GO_TO_LABEL_ASK = "Go to label:"
GO_TO_LABEL_OK = "Go"
NO_SUCH_LABEL = "There is no label named `{name}` in the last check."
NO_LABELS_YET = "Labels are listed after the first check."
# F46 step 5: the Story menu and context menus (design §6.1; plain words, AC-F46-34).
STORY_NEW_SCENE = "New scene"
STORY_NEW_SCENE_HERE = "New scene here"
STORY_GO_TO = "Go to scene…"
STORY_RENAME = "Rename scene"
STORY_DELETE_SCENE = "Delete scene"
STORY_MOVE_BOX = "Move box"
STORY_DELETE_ARROW = "Delete arrow"
STORY_CHOICE_TEXT = "Edit choice text"
STORY_CHANGE_TARGET = "Change target…"
STORY_TIDY_UP = "Tidy up"
STORY_INSERT = "Insert command…"
STORY_EDIT = "Edit command"
STORY_UP = "Move up"
STORY_DOWN = "Move down"
STORY_DELETE_ROW = "Delete command"
STORY_PREVIEW = "Preview from this scene"
RENAME_SCENE_ASK = "Rename the scene `{name}`. Type its new name:"
RENAME_SCENE_OK = "Continue"
CHANGE_TARGET_TITLE = "Change target"
CHANGE_TARGET_OK = "Change"
CHOICE_STATUS = "Choice: {text}"
NO_SCRIPT_FOR_SCENE = "Add a script file first: a scene lives in one."
CONTEXT_MENUS_POST = True               # tests set False: tk_popup would wait for a click


class _UndoFile:
    """An open file as ``storymap.map_undo`` sees it: its change counter and its text's
    undo and redo (each counted by the change hook as it happens)."""

    __slots__ = ("record",)

    def __init__(self, record: "OpenFile") -> None:
        self.record = record

    @property
    def changes(self) -> int:
        return self.record.changes

    def edit_undo(self) -> None:
        try:
            self.record.widget.edit_undo()
        except tk.TclError:
            pass

    def edit_redo(self) -> None:
        try:
            self.record.widget.edit_redo()
        except tk.TclError:
            pass


# --- Helpers --------------------------------------------------------------------------------

def _label_row(row: object) -> tuple:
    """``(name, file, line)`` of a ``NameEntry`` or a row of the name index."""
    name = getattr(row, "name", None)
    if name is not None:
        return name, getattr(row, "file", None), getattr(row, "line", None)
    if isinstance(row, str):
        return row, None, None
    return tuple(row)[:3]


class MapWiring:
    """The Story map tab, its side pane, following the text, places and the map history,
    and the story actions."""

    def _build_map_tab(self) -> tk.Widget:
        """The Story map tab's page: the map, and beside it (after a click) the side
        editor (``_build_side_pane``)."""
        px = self._px
        sash, sash_width = THEME["sash"], px(SASH_WIDTH)
        self.map_frame = ttk.Frame(self.notebook)
        self.map_split = tk.PanedWindow(self.map_frame, orient="horizontal",
                                        sashwidth=sash_width, borderwidth=0,
                                        sashrelief="flat", background=sash)
        self.map_split.pack(fill="both", expand=True)
        map_box = ttk.Frame(self.map_split, padding=px(8))
        self.map_split.add(map_box, minsize=px(MAP_MIN_WIDTH), stretch="always")
        self.story_map = StoryMapView(map_box, background=BACKGROUND,
                                      family=self.ui_font.actual("family"), mod=self.mod,
                                      on_open=self.open_label_beside,
                                      on_open_tab=self.open_label_box, fonts=self.fonts,
                                      scale=self.scale, on_check=self.check_now,
                                      on_step=self._map_moved)
        self.story_map.frame.pack(fill="both", expand=True)
        self.map_canvas = self.story_map.canvas
        # F46 04 §6.9: Ctrl+Z / Ctrl+Y on the map are the map history's (only there).
        for letter in "zZ":
            self.map_canvas.bind(f"<{self.mod}-{letter}>",
                                 lambda _e: self._break(self.map_undo, False))
        for letter in "yY":
            self.map_canvas.bind(f"<{self.mod}-{letter}>",
                                 lambda _e: self._break(self.map_undo, True))
        # F46 step 5 (04 §6.4, §6.6, §6.11): the map's arrows, choices and new scenes.
        view = self.story_map
        view.on_new_scene = lambda place: self.new_scene(place)
        view.on_arrow = lambda src, dst: self.add_arrow(
            view.layout.boxes[src].name, view.layout.boxes[dst].name)
        view.on_edge = lambda _index: self._edge_chosen()
        view.on_choice_text = lambda index, text: self.choice_text(index, text)
        view.on_delete = lambda: self.map_delete()
        view.on_edit_choice = lambda: self.edit_choice_text()
        view.on_rename = lambda: self.rename_scene()
        view.on_retarget = lambda index, target: self._head_dropped(index, target)
        view.on_context = lambda kind, what, x, y: self.map_context(kind, what, x, y)
        canvas = self.map_canvas
        for key in (f"<{self.mod}-j>", f"<{self.mod}-J>"):
            canvas.bind(key, lambda _e: self._break(self.go_to_scene))
        # 07 I-7: Ctrl+Shift+N here, before the bind_all Ctrl+N (New script file) sees it.
        for key in (f"<{self.mod}-Shift-N>", f"<{self.mod}-Shift-n>", f"<{self.mod}-N>"):
            canvas.bind(key, lambda _e: self._break(self.new_scene))
        return self.map_frame

    def _build_side_pane(self) -> None:
        """The Story map's side pane (F46 C1): a header (the tabs Events | Script, the file,
        Open in Editor tab, ✕) over a tabless notebook holding the Events page and the
        Script page (a gutter and the peer text). Added to ``map_split`` only while open."""
        px = self._px
        side = self.side_frame = ttk.Frame(self.map_split)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(1, weight=1)
        self.side_book = ttk.Notebook(side, takefocus=0, style="Tabless.TNotebook")
        self.events_view = EventsView(self.side_book, fonts=self.fonts, scale=self.scale)
        script = self.script_page = ttk.Frame(self.side_book)
        script.columnconfigure(1, weight=1)
        script.rowconfigure(0, weight=1)
        self.side_book.add(self.events_view.frame, text=SIDE_TAB_EVENTS)
        self.side_book.add(script, text=SIDE_TAB_SCRIPT)
        self.side_book.select(SIDE_PAGES.index(self.side_tab))
        self.side_tabs = TabStrip(side, self.side_book, (
            (SIDE_TAB_EVENTS, "events"), (SIDE_TAB_SCRIPT, "script")),
            font=self.fonts["body"], scale=self.scale)
        head = self.side_tabs.frame
        head.grid(row=0, column=0, sticky="ew")
        self.side_book.grid(row=1, column=0, sticky="nsew")
        self.side_book.bind("<<NotebookTabChanged>>", self._on_side_tab_changed, add="+")
        self.side_close_button = ttk.Button(head, text=SIDE_CLOSE, width=3, takefocus=0,
                                            style="Chrome.Ghost.TButton",
                                            command=self.close_side)
        # ✕ before the tabs; then Open in Editor tab and the file, dropped when narrow.
        self.side_close_button.pack(side="right", padx=px(4), pady=px(4),
                                    before=self.side_tabs.cells[0][0])
        self.side_open_button = ttk.Button(head, text=SIDE_OPEN_TAB, takefocus=0,
                                           style="Chrome.Ghost.TButton",
                                           command=self.side_to_editor)
        self.side_open_button.pack(side="right", pady=px(4))
        self.side_name = ttk.Label(head, text="", style="Side.TLabel",
                                   foreground=THEME["muted"])
        self.side_name.pack(side="left", padx=(px(PANEL_INSET), 0))
        head.bind("<Configure>", self._fit_side_head, add="+")
        self.story = StoryEditor(self, self.events_view)
        tree = self.events_view.tree
        tree.bind("<Button-3>", self.events_context)
        if self.mod == "Command":
            tree.bind("<Button-2>", self.events_context)
        for key in ("<Shift-F10>", "<App>", "<Menu>"):
            try:
                tree.bind(key, self.events_context)
            except tk.TclError:
                pass
        for key in (f"<{self.mod}-e>", f"<{self.mod}-E>"):
            tree.bind(key, lambda _e: self._break(self.toggle_side_tab, True))
            self.map_canvas.bind(key, lambda _e: self._break(self.toggle_side_tab, False))
        for key in (f"<{self.mod}-Return>", f"<{self.mod}-KP_Enter>"):
            tree.bind(key, lambda _e: self._break(self.side_to_editor))
        self.side_gutter = tk.Canvas(script, width=self._gutter_width(1),
                                     background=GUTTER_BACKGROUND, highlightthickness=0,
                                     borderwidth=0, takefocus=0)
        self.side_gutter.grid(row=0, column=0, sticky="ns")
        self.side_vbar = ttk.Scrollbar(script, orient="vertical")
        self._side_vbar_set = autohide(self.side_vbar, row=0, column=2, sticky="ns")
        self.side_hbar = ttk.Scrollbar(script, orient="horizontal")
        self._side_hbar_set = autohide(self.side_hbar, row=1, column=1, sticky="ew")

    # --- Story map (PR-F45-18, 19; design §6.2) ---------------------------------------------

    def refresh_story_map(self) -> None:
        """Draw the map from ``check_names["label"]`` and ``check_links`` with the open
        scripts' scenes swapped in (``map_data``, F46 04 §6.1.6), if they changed."""
        if self.closed or not self._map_dirty:
            return
        self._map_dirty = False
        labels, links, stale = self.map_data()
        notes = label_notes(labels, self._check_names)
        data = (tuple(labels), tuple(links), self._check_stale, stale, notes)
        if data == self._map_shown:
            return                              # redraw only on change (04 §6.1.6)
        self._map_shown = data
        self._read_layout()
        self.story_map.set_data(labels, links, self._check_stale, notes, out_of_date=stale)

    # --- Places, the layout file and the map history (F46 04 §6.8–6.10) --------------------

    def _read_layout(self) -> None:
        """The layout file, once, at the first draw: its places, or the automatic layout
        and the design's status line."""
        if self._layout_read:
            return
        self._layout_read = True
        found = layoutfile.read_layout(self.paths.root)
        if isinstance(found, layoutfile.LayoutProblem):
            self._layout_writable = not found.link
            self.story_map.message = found.text
            found = {}
        self.story_map.places = dict(found)

    def _map_moved(self, title: str, before: dict, after: dict) -> None:
        """A move or Tidy up on the map: one map step; the layout file is saved soon."""
        self.map_history.push(MapStep(title, before, after))
        self._places_changed()

    def map_plan_done(self, plan: object) -> None:
        """A plan applied from the map or the Events list (``StoryEditor._after``): one map
        step holding each touched file's edit token and the plan's places."""
        places = dict(getattr(plan, "places", {}) or {})
        view = self.story_map
        before = {name: view.places.get(name) for name in places}
        tokens = tuple((fp.ref, self.files[fp.ref].changes)
                       for fp in getattr(plan, "files", ()) if fp.ref in self.files)
        self.map_history.push(MapStep(str(getattr(plan, "title", "")), before, places,
                                      tokens))
        if places:
            view.apply_places(places)
            self._places_changed()

    def map_undo(self, redo: bool = False) -> None:
        """Map Ctrl+Z (Ctrl+Y with ``redo``), 04 §6.9: a step whose files changed since (or
        closed) is dropped with the "Undo blocked" line; otherwise each file's text undo
        runs once and the places go back."""
        view = self.story_map
        view.cancel_move()
        step = self.map_history.redo_step() if redo else self.map_history.undo_step()
        if step is None:
            return
        records = {ref: _UndoFile(self.files[ref]) if ref in self.files
                   and self.files[ref].editable else None for ref, _token in step.files}
        done = map_undo(self.map_history, records, redo=redo)
        if done.places is None:
            text = undo_blocked_text(done.blocked)
            view.say(text)
            if self.story is not None:
                self.story.say(text)
            return
        view.say("")
        if step.files:
            self.follow()
            if self.story is not None:
                self.story.refresh()
        if done.places:
            view.apply_places(done.places)
            self._places_changed()

    def _places_changed(self) -> None:
        self._layout_dirty = True
        self._cancel_layout_save()
        if not self.closed and self._layout_writable:
            self._layout_save_id = self.root.after(layoutfile.LAYOUT_SAVE_MS, self.save_layout)

    def _cancel_layout_save(self) -> None:
        if self._layout_save_id is not None:
            try:
                self.root.after_cancel(self._layout_save_id)
            except tk.TclError:
                pass
            self._layout_save_id = None

    def save_layout(self) -> None:
        """Write the layout file (04 §6.10): only labels that exist, in program order, the
        shown boxes kept first; nothing is marked unsaved. A failure shows one status line
        and the next move tries again; a link stops writes for this window."""
        self._layout_save_id = None
        if not self._layout_dirty or not self._layout_writable:
            return
        view = self.story_map
        places = view.saved_places()
        names = [_label_row(row)[0] for row in view.labels]
        ordered = {name: places[name] for name in dict.fromkeys(names) if name in places}
        shown = [box.name for box in view.layout.boxes] if view.layout is not None else []
        problem = layoutfile.write_layout(self.paths.root,
                                          layoutfile.encode_layout(ordered, shown))
        if problem is None:
            self._layout_dirty = False
            return
        if problem.link:
            self._layout_writable = False
        if not self.closed:
            view.say(problem.text)

    def map_data(self) -> tuple[list, list, frozenset[str]]:
        """The map's labels and links: the last good check's, with each open script's
        parsed scenes swapped in once a check has listed labels; and the scenes that read
        "out of date" (their text doesn't parse now)."""
        labels = self._check_names.get("label", ())
        if not labels or not self.scene_indexes:
            return list(labels), list(self._check_links), frozenset()
        entries = [row if isinstance(row, NameEntry) else NameEntry(*_label_row(row))
                   for row in labels]
        links = [row if isinstance(row, LabelLink) else LabelLink(*tuple(row)[:7])
                 for row in self._check_links]
        out_labels, out_links = scenes.map_data(entries, links, self.scene_indexes)
        return out_labels, out_links, frozenset(scenes.out_of_date(
            self.scene_indexes.values()))

    # --- Following the text (F46 04 §6.1) ---------------------------------------------------

    def _is_script(self, record: OpenFile) -> bool:
        return (record.editable and record.ref.startswith("script/")
                and record.ref.endswith(".vns"))

    def _positions(self) -> frozenset[str]:
        return frozenset(_label_row(row)[0] for row in self._check_names.get("position", ()))

    def _baseline(self, record: OpenFile) -> None:
        """Index a script as loaded: its digests count as checked until a check that saw
        them lands (07 I-1), so nothing is parsed now."""
        if not self._is_script(record):
            return
        index = scenes.reindex(None, record.ref, record.widget.get("1.0", "end-1c"),
                               record.changes, checked=None, positions=self._positions())
        self.scene_indexes[record.ref] = index
        self._checked[record.ref] = index.checked
        self._map_dirty = True

    def _forget_index(self, ref: str) -> None:
        self.scene_indexes.pop(ref, None)
        self._checked.pop(ref, None)
        self._map_dirty = True

    def _schedule_follow(self) -> None:
        """``follow`` ``FOLLOW_MS`` after the last change (separate from the check's
        debounce)."""
        self._cancel_follow()
        if not self.closed:
            self._follow_id = self.root.after(scenes.FOLLOW_MS, self.follow)

    def _cancel_follow(self) -> None:
        if self._follow_id is not None:
            try:
                self.root.after_cancel(self._follow_id)
            except tk.TclError:
                pass
            self._follow_id = None

    def follow(self) -> None:
        """Re-read the scripts that changed since their index and redraw what changed."""
        self._follow_id = None
        if not self.closed and self._reindex():
            self._index_changed()

    def _reindex(self) -> bool:
        """``scenes.reindex`` each open script whose ``changes`` its index hasn't seen;
        True when any was re-read. The Events tab's scene is parsed even when unchanged
        (``want``)."""
        positions = self._positions()
        changed = False
        shown = self.story.ref if self.story is not None else None
        for ref, record in self.files.items():
            index = self.scene_indexes.get(ref)
            if index is None:
                continue
            want = self.story.want() if self.story is not None and ref == shown \
                else frozenset()
            missing = any((name, 0) in index.starts and (name, 0) not in index.reads
                          for name in want)
            current = index.changes == record.changes and index.positions == positions
            if current and not missing:
                continue
            self.scene_indexes[ref] = scenes.reindex(
                index, ref, record.widget.get("1.0", "end-1c"), record.changes,
                checked=self._checked.get(ref, index.checked), want=want,
                positions=positions)
            changed = changed or not current
        return changed

    def open_label_box(self, box: Box) -> None:
        """A click or Enter on a box: its label line in the Editor tab."""
        if box.file is not None and box.line is not None:
            self.jump_to(box.file, box.line)

    # --- The side editor (2026-11-02, user: map opens editor to the side) ------------------

    def open_label_beside(self, box: Box) -> None:
        """A click or Enter on a box: its label line in the side editor beside the map (a
        file that didn't load opens in the Editor tab)."""
        if box.file is None or box.line is None:
            return
        record = self._record(box.file)
        if not record.editable:
            self.jump_to(box.file, box.line)
            return
        self.current = record
        self._show(record.widget)           # retargets an open side editor
        if self._side_source is not record.widget:
            self._make_side_peer(record.widget)
        self._show_side_pane()
        peer = self.side_text
        assert peer is not None
        self._place_jump(peer, max(1, min(box.line, line_of(peer.index("end-1c")))))
        if self.side_tab == "events" and self.story is not None:
            self.story.show(record.ref, box.name)
        self.show_side_tab(self.side_tab)   # F46 C1: the tab last chosen in this window
        view = self.story_map
        shown = view.layout.index_of(box.name) if view.layout is not None else None
        view.select_box(shown)                          # F46: 2 px accent while it shows
        if shown is not None and shown != view.focused:
            view.focus_box(shown)                       # the box opened is the map's own
        if view.focused is not None:                    # the map just got narrower: the
            self.map_split.update_idletasks()           # pane mustn't cover the box (F46)
            view.see(view.focused)
        # Last: the row's quiet <<TreeviewSelect>> must not meet update_idletasks above.
        self._select_current_row()

    def _make_side_peer(self, source: tk.Text) -> None:
        """A Tk text peer of ``source``: the same text, tags, marks, undo and modified flag;
        its own cursor, selection and view."""
        self._drop_side_peer()
        peer = tk.Text.__new__(tk.Text)
        tk.BaseWidget._setup(peer, self.script_page, {})
        peer.widgetName = "text"
        source.peer_create(peer._w, **self._text_options(editable=True))
        peer.tag_configure("sel", foreground=PLAIN_COLOR)
        peer.tag_raise("sel")
        peer.configure(yscrollcommand=self._on_side_yscroll, xscrollcommand=self._side_hbar_set)
        peer.bind("<Configure>", lambda _e: self._schedule_refresh(), add="+")
        # Esc closes the side editor (an open completion list takes it first).
        peer.bind("<Escape>", lambda _e: None if self.popup.is_open
                  else self._break(self.close_side))
        # Ctrl+E: the Events page (G8; only here, the Editor tab keeps Tk's end of line).
        for key in (f"<{self.mod}-e>", f"<{self.mod}-E>"):
            peer.bind(key, lambda _e: self._break(self.toggle_side_tab, True))
        tags = list(peer.bindtags())
        tags.insert(1, self._editor_bindtag)
        peer.bindtags(tuple(tags))
        self._install_change_hook(peer, owner=source)
        peer.grid(row=0, column=1, sticky="nsew")
        self.side_vbar.configure(command=peer.yview)
        self.side_hbar.configure(command=peer.xview)
        self.side_text, self._side_source = peer, source
        self._update_side_name()

    def _drop_side_peer(self) -> None:
        peer = self.side_text
        if peer is None:
            return
        if self.popup.widget is peer:
            self.close_completion()
        self.side_text = self._side_source = None
        name = str(peer)
        peer.destroy()
        try:
            peer.tk.call("rename", name, "")    # the change hook's proc outlives the widget
        except tk.TclError:
            pass

    def _show_side_pane(self) -> None:
        """Add the side editor to the Story map tab: 45 % of it at first, then the width
        the author left it at."""
        if self._side_open:
            return
        split = self.map_split
        split.update_idletasks()
        total = split.winfo_width()
        width = self._side_width or int(total * SIDE_SHARE)
        split.add(self.side_frame, minsize=self._px(SIDE_MIN_WIDTH), stretch="always")
        self._side_open = True
        # Esc in the Events list closes the pane (bound only while open, as the peer's).
        self.events_view.tree.bind("<Escape>", lambda _e: self._break(self.close_side))
        if total > 1:
            split.update_idletasks()
            split.sash_place(0, max(self._px(MAP_MIN_WIDTH), total - width), 0)

    def close_side(self, focus_map: bool = True) -> None:
        """✕ or Esc: hide the side editor; the focus goes back to the map."""
        if not self._side_open:
            return
        width = self.side_frame.winfo_width()
        if width > 1:
            self._side_width = width
        self.map_split.forget(self.side_frame)
        self._side_open = False
        self.story_map.select_box(None)
        self.events_view.tree.unbind("<Escape>")
        self._drop_side_peer()
        if focus_map and not self.closed:
            self.map_canvas.focus_set()
        self._schedule_refresh()

    def side_to_editor(self) -> None:
        """Open in Editor tab (and Ctrl+1 in the side editor): the Editor tab at the side
        editor's cursor."""
        peer, record = self.side_text, self.current
        if peer is None or record is None:
            return
        line, column = (int(part) for part in peer.index("insert").split("."))
        self.select_tab("editor")
        self._place_jump(record.widget, line, column)

    # --- The side pane's tabs (F46 C1, 04 §6.11) ---------------------------------------------

    def show_side_tab(self, name: str, focus: bool = True) -> None:
        """The side pane's Events or Script page, remembered for this window (G12); Events
        shows the scene at the Script cursor with its row selected. ``focus``: the keyboard
        focus goes to the page."""
        self.side_tab = name
        index = SIDE_PAGES.index(name)
        if self.side_book.index("current") != index:
            self.side_book.select(index)
        if name == "events" and self.story is not None:
            self.story.follow_cursor()
        widget = self._side_page_widget()
        if focus and self._side_open and widget is not None:
            widget.focus_set()
            if widget is self.side_text:
                widget.see("insert")

    def toggle_side_tab(self, from_side: bool) -> None:
        """Ctrl+E: Events ⇄ Script. From the map the focus stays there; with the pane
        closed, the focused box opens on the other tab."""
        other = "events" if self.side_tab == "script" else "script"
        if not self._side_open or self.side_text is None:
            focused = self.story_map.focused
            if from_side or focused is None:
                return
            self.side_tab = other
            self.open_label_beside(self.story_map.layout.boxes[focused])
            self.map_canvas.focus_set()
            return
        self.show_side_tab(other, focus=from_side)

    def _on_side_tab_changed(self, _event: tk.Event | None = None) -> None:
        """A click on the side pane's tab strip."""
        try:
            name = SIDE_PAGES[self.side_book.index("current")]
        except (tk.TclError, IndexError):
            return
        if name != self.side_tab and not self.closed:
            self.show_side_tab(name)

    def _fit_side_head(self, _event: tk.Event | None = None) -> None:
        """The side pane's header never clips: Open in Editor tab, then the file name, are
        hidden while the tabs and ✕ leave no room for them."""
        head = self.side_tabs.frame
        width = head.winfo_width()
        if width <= 1:
            return
        need = self.side_close_button.winfo_reqwidth() + self._px(8) + sum(
            cell.winfo_reqwidth() for cell, *_rest in self.side_tabs.cells)
        for widget, pad, side in ((self.side_open_button, 0, "right"),
                                  (self.side_name, self._px(PANEL_INSET), "left")):
            need += widget.winfo_reqwidth() + pad
            packed = widget.winfo_manager() == "pack"
            if need <= width and not packed:
                widget.pack(side=side, pady=self._px(4) if side == "right" else 0,
                            padx=(pad, 0))
            elif need > width and packed:
                widget.pack_forget()

    def _side_page_widget(self) -> tk.Widget | None:
        """The shown side page's focus stop: the Events list or the Script peer."""
        return self.events_view.tree if self.side_tab == "events" else self.side_text

    def story_ask(self, text: str, buttons: Sequence[str], *, escape: int,
                  default: int) -> int:
        """A story action's question (``scriptedit.Ask``), in Studio's dialog."""
        return ask(self.root, text, buttons, escape=escape, default=default)

    def reindex_scenes(self) -> None:
        """Bring the scene index up to date now (the Events tab asks before drawing)."""
        if not self.closed and self._reindex():
            self._index_changed()

    def text_cursor_moved(self) -> None:
        """The Events tab moved the Script cursor: the gutter and status bar follow."""
        self._schedule_refresh()

    def _follow_events(self) -> None:
        if not self.closed and self._side_open and self.side_tab == "events" \
                and self.story is not None:
            self.story.follow_cursor()

    def _side_active(self) -> tk.Text | None:
        """The side editor's peer while it is on screen, else None."""
        side = self.side_text
        if side is None or self.closed or self.current is None \
                or self._side_source is not self.current.widget:
            return None
        return side if self.current_tab() == "map" else None

    def _side_has_focus(self) -> bool:
        try:
            return self.side_text is not None and self.root.focus_get() is self.side_text
        except (KeyError, tk.TclError):
            return False

    def _on_side_yscroll(self, first: str, last: str) -> None:
        self._side_vbar_set(first, last)
        self._schedule_refresh()

    def _update_side_name(self) -> None:
        """The side editor's header: the file's ref, ``* `` in front while unsaved."""
        record = self.current
        if self.side_text is not None and record is not None:
            text = (DIRTY_MARK if record.dirty else "") + show(record.ref)
            if self.side_name.cget("text") != text:
                self.side_name.configure(text=text)

    def label_places(self) -> dict[str, tuple[str | None, int | None]]:
        """Label name -> (file, line), from the last good check, in program order."""
        places: dict[str, tuple[str | None, int | None]] = {}
        for entry in self._check_names.get("label", ()):
            if isinstance(entry, str):
                name, where, line = entry, None, None
            elif hasattr(entry, "name"):
                name = entry.name
                where, line = getattr(entry, "file", None), getattr(entry, "line", None)
            else:
                name, where, line = tuple(entry)[:3]
            places.setdefault(name, (where, line))
        return places

    def go_to_label(self) -> None:
        """Ctrl+G: the story map's text alternative. Asks for a label name and jumps to its
        line."""
        if self.closed:
            return
        places = self.label_places()

        def hint(text: str) -> str:
            if not places:
                return NO_LABELS_YET
            name = text.strip()
            where = places.get(name)
            if where is None or where[0] is None:
                return ", ".join([n for n in places if n.startswith(name)][:6])
            return f"{show(where[0])}, line {where[1]}"

        answer = ask_text(self.root, GO_TO_LABEL_ASK, "", ok=GO_TO_LABEL_OK, hint=hint,
                          select_stem=False)
        if answer is None:
            return
        name = answer[0].strip()
        where = places.get(name)
        if where is None or where[0] is None or where[1] is None:
            show_error(self.root, NO_SUCH_LABEL.format(name=name))
            return
        self.jump_to(where[0], where[1])

    # --- The Story menu, context menus and the map's actions (F46 step 5) ---------------------

    def story_actions(self) -> list:
        """The action table (04 §6.11): ``(label, accelerator, run, enabled, targets)`` rows
        and None for a separator. ``targets`` names the context menus that show it: box,
        edge, map (empty space) and row."""
        view = self.story_map
        alt = "Option" if self.mod == "Command" else "Alt"

        def box() -> bool:
            return view.layout is not None and view.focused is not None

        def edge() -> bool:
            return view.selected_edge() is not None

        def choice() -> bool:
            found = view.selected_edge()
            return found is not None and found[2] == "menu"

        def row() -> bool:
            return self._side_open and self.side_tab == "events" \
                and self.events_view.selected() is not None

        def editable_row() -> bool:
            return row() and not (self.story is not None and self.story.stale)

        return [
            (STORY_NEW_SCENE, "Ctrl+Shift+N", lambda: self.new_scene(), lambda: True,
             ("map", "box")),
            (STORY_GO_TO, "Ctrl+J", lambda: self.go_to_scene(), box, ("box",)),
            (STORY_RENAME, "F2", lambda: self.rename_scene(), box, ("box",)),
            (STORY_DELETE_SCENE, "Delete", lambda: self.delete_scene(), box, ("box",)),
            (STORY_MOVE_BOX, "", lambda: self.move_box(), box, ("box",)),
            None,
            (STORY_DELETE_ARROW, "Delete", lambda: self.delete_arrow(), edge, ("edge",)),
            (STORY_CHOICE_TEXT, "F2", lambda: self.edit_choice_text(), choice, ("edge",)),
            (STORY_CHANGE_TARGET, "", lambda: self.change_target(), edge, ("edge",)),
            None,
            (STORY_TIDY_UP, "", lambda: self.tidy_up(), lambda: bool(view.places),
             ("map", "box")),
            None,
            (STORY_INSERT, "Insert", lambda: self.insert_command(), editable_row, ("row",)),
            (STORY_EDIT, "Enter", lambda: self.edit_command(), editable_row, ("row",)),
            (STORY_UP, f"{alt}+Up", lambda: self.move_command(-1), editable_row, ("row",)),
            (STORY_DOWN, f"{alt}+Down", lambda: self.move_command(1), editable_row,
             ("row",)),
        ]

    def context_menu(self, kind: str) -> tk.Menu:
        """The context menu for a ``box``, an ``edge``, the ``map``'s empty space or an
        Events ``row``: that target's enabled actions only (AC-F46-33; built anew)."""
        menu = tk.Menu(self.root, tearoff=0)
        last_was_item = False
        for entry in self.story_actions():
            if entry is None:
                if last_was_item:
                    menu.add_separator()
                last_was_item = False
                continue
            label, accel, run, when, kinds = entry
            if kind not in kinds or not when():
                continue
            if kind == "map" and label == STORY_NEW_SCENE:
                label, run = STORY_NEW_SCENE_HERE, (lambda: self.new_scene(self._context_at))
            if kind == "row" and label == STORY_DOWN:
                menu.add_command(label=label, accelerator=accel, command=run)
                menu.add_command(label=STORY_DELETE_ROW, accelerator="Delete",
                                 command=self.delete_command)
                last_was_item = True
                continue
            menu.add_command(label=label, accelerator=accel.replace("Ctrl", self._key_word()),
                             command=run)
            last_was_item = True
        if kind == "box" and self.story_map.focused_name() is not None:
            if last_was_item:
                menu.add_separator()
            menu.add_command(label=STORY_PREVIEW, command=self.preview_scene)
        if menu.index("end") is not None and menu.type("end") == "separator":
            menu.delete("end")
        self.last_context = menu            # tests read it
        return menu

    def _key_word(self) -> str:
        return "Cmd" if self.mod == "Command" else "Ctrl"

    def map_context(self, kind: str, what: object, x: int, y: int) -> None:
        """Button-3, Shift+F10 or the Menu key on the map (``StoryMapView.on_context``)."""
        if kind == "map":
            self._context_at = what if isinstance(what, tuple) else None
        self._post(self.context_menu(kind), x, y)

    def events_context(self, event: tk.Event | None = None) -> str:
        """Button-3 on an Events row (it is chosen first), Shift+F10 or the Menu key."""
        events = self.events_view
        if event is not None and event.type == tk.EventType.ButtonPress:
            index = events._row_at(event.y)
            if index is not None:
                events.select(index)
            x, y = event.x_root, event.y_root
        else:
            index = events.selected()
            tree = events.tree
            box = tree.bbox(f"{index + 1}.0") if index is not None else None
            x = tree.winfo_rootx() + (box[0] + 40 if box else 20)
            y = tree.winfo_rooty() + (box[1] + box[3] // 2 if box else 20)
        events.tree.focus_set()
        self._post(self.context_menu("row"), x, y)
        return "break"

    def _post(self, menu: tk.Menu, x: int, y: int) -> None:
        if CONTEXT_MENUS_POST:
            try:
                menu.tk.call("tk_popup", menu, x, y)
            finally:
                menu.grab_release()

    def _map_say(self, text: str) -> None:
        """A map action's outcome or refusal: the map's banner and the Events status."""
        self.story_map.say(text)
        if self.story is not None and text:
            self.story.say(text)

    def _edge_chosen(self) -> None:
        """A selected arrow: its full choice text in the status bar (PR-F46-13)."""
        found = self.story_map.selected_edge()
        text = ""
        if found is not None and found[3]:
            text = CHOICE_STATUS.format(text=found[3])
        self.story_status.configure(text=text)
        self.status_bar.layout()

    def _scene_names(self) -> list[str]:
        names = {_label_row(row)[0] for row in self._check_names.get("label", ())}
        for index in self.scene_indexes.values():
            names.update(name for name, _n in index.starts)
        if self.story_map.layout is not None:
            names.update(box.name for box in self.story_map.layout.boxes)
        return sorted(names)

    def _scene_file(self, name: str) -> str | None:
        view = self.story_map
        index = view.layout.index_of(name) if view.layout is not None else None
        if index is not None:
            return view.layout.boxes[index].file
        return self.label_places().get(name, (None, None))[0]

    def new_scene(self, place: tuple[int, int] | None = None) -> None:
        """New scene (toolbar, Ctrl+Shift+N, a double-click on empty map space, New scene
        here; PR-F46-14): the dialog, then the label and placeholder appended to the file
        as one undo step, the box placed (at the click, else beside the selected box) and
        opened beside the map with the placeholder selected."""
        if self.closed:
            return
        view = self.story_map
        refs = [ref for ref in self.refs if ref.startswith("script/") and ref.endswith(".vns")]
        if not refs:
            show_error(self.root, NO_SCRIPT_FOR_SCENE)
            return
        chosen = view.selected_name() or view.focused_name()
        default = self._scene_file(chosen) if chosen else None
        if default not in refs:
            default = "script/main.vns" if "script/main.vns" in refs else refs[0]
        taken = self._scene_names()
        answer = formdialogs.ask_new_scene(self.root, refs, default, taken=taken,
                                           problem=files.label_problem,
                                           new_file=self.new_script_file)
        if answer is None:
            return
        name, ref = answer
        record = self._record(ref)
        if not record.editable:
            show_error(self.root, record.error.format() if record.error is not None
                       else scriptedit.UNSAFE)
            return
        text = record.widget.get("1.0", "end-1c")
        if place is None and chosen is not None and view.layout is not None:
            near = view.layout.boxes[view.layout.index_of(chosen)]
            occupied = [(b.x, b.y) for b in view.layout.boxes]
            place = place_free(occupied, (near.x + COLUMN_STEP, near.y))
        plan = scriptedit.plan_new_scene(text.split("\n"), ref, name, indent_unit(text),
                                         place, taken=taken)
        if isinstance(plan, scriptedit.Refuse):
            show_error(self.root, plan.text)
            return
        if not isinstance(plan, scriptedit.Plan) or not scriptedit.verify(
                plan, {ref: text}, positions=self._positions()):
            show_error(self.root, scriptedit.UNSAFE)
            return
        widget = record.widget
        for file_plan in plan.files:
            self._as_one_step(widget, lambda e=file_plan.edits: apply_edits(widget, e))
        self.follow()
        self.map_plan_done(plan)
        self._map_dirty = True
        self.refresh_story_map()
        index = view.layout.index_of(name) if view.layout is not None else None
        if index is None:
            return
        self.open_label_beside(view.layout.boxes[index])
        select = plan.files[0].select
        peer = self.side_text
        if select is not None and peer is not None and self.side_tab == "script":
            line, col0, col1 = select
            peer.tag_remove("sel", "1.0", "end")
            peer.tag_add("sel", f"{line}.{col0}", f"{line}.{col1}")
            peer.mark_set("insert", f"{line}.{col1}")
            peer.see("insert")
        self.map_canvas.focus_set()

    def add_arrow(self, src: str, dst: str) -> object:
        """An arrow ``src → dst`` (a handle drag, Go to scene…; PR-F46-07, 12): what it
        writes follows the source's end; Make a choice opens the new arrow's text field."""
        ref = self._scene_file(src)
        if ref is None or self.story is None:
            return None
        record = self._record(ref)
        unit = indent_unit(record.widget.get("1.0", "end-1c"))
        plan = self.story.act_on(ref, src, lambda read, lines, start, **kw:
                                 scriptedit.plan_add_arrow(read, lines, start, dst, unit,
                                                           **kw), answer="choice")
        self._map_done(plan)
        if plan is not None and plan.then is not None \
                and plan.then[0] == scriptedit.THEN_CHOICE_TEXT:
            view = self.story_map
            index = view.edge_index(src, plan.then[1], "menu")
            if index is not None:
                view.focus_box(view.layout.index_of(src))
                view.select_edge(index)
                view.open_choice_field(index)
        return plan

    def _map_done(self, plan: object) -> None:
        """After a map action: the map redrawn now, and its status or refusal said."""
        self._map_dirty = True
        self.refresh_story_map()
        if plan is None:
            self._map_say(self.story.status if self.story is not None else "")
        else:
            self._map_say(getattr(plan, "status", None) or "")

    def go_to_scene(self) -> None:
        """Go to scene… (Ctrl+J): pick a scene; the focused box gets an arrow to it, as a
        drag would write."""
        view = self.story_map
        src = view.focused_name()
        if src is None:
            return
        picked = formdialogs.pick_scene(self.root, self._scene_names())
        if picked is not None:
            self.add_arrow(src, picked)

    def delete_arrow(self) -> object:
        """Delete arrow (Delete on a selected arrow, PR-F46-08)."""
        found = self.story_map.selected_edge()
        if found is None or self.story is None:
            return None
        src, dst, kind, _choice = found
        ref = self._scene_file(src)
        if ref is None:
            return None
        self._record(ref)
        plan = self.story.act_on(ref, src, lambda read, lines, start, **kw:
                                 scriptedit.plan_delete_arrow(read, lines, start, dst, kind,
                                                              **kw))
        self._map_done(plan)
        return plan

    def edit_choice_text(self) -> None:
        """Edit choice text (F2 on a choice arrow): its inline field."""
        view = self.story_map
        found = view.selected_edge()
        if found is not None and found[2] == "menu" and view.edge is not None:
            view.open_choice_field(view.edge)

    def choice_text(self, index: int, text: str) -> object:
        """The inline field's Enter: the choice's quoted text (PR-F46-13), as one step."""
        view = self.story_map
        if view.layout is None or self.story is None or not 0 <= index < len(
                view.layout.edges):
            return None
        edge = view.layout.edges[index]
        src, dst = view.layout.boxes[edge.src].name, view.layout.boxes[edge.dst].name
        ref = self._scene_file(src)
        if ref is None:
            return None
        old = edge.choice

        def planner(read: Any, lines: Any, start: int) -> object:
            paths = []
            for i in scriptedit._link_statements(read, dst, "menu"):
                block = read.blocks[scriptedit.block_of(read, i)]
                menu = next((s for s in read.statements if s.path == block.owner), None)
                if block.owner is None or menu is None or not isinstance(menu.node, Menu):
                    continue
                said = menu.node.choices[block.branch].text
                paths.append((said != old, (*block.owner, block.branch)))
            if not paths:
                return scriptedit.Refuse(scriptedit.STALE)
            return scriptedit.plan_choice_text(read, lines, start, min(paths)[1], text)
        plan = self.story.act_on(ref, src, planner)
        self._map_done(plan)
        found = view.edge_index(src, dst, "menu")
        if found is not None:
            view.select_edge(found)
        self.map_canvas.focus_set()
        return plan

    def map_delete(self) -> None:
        """Delete on the map: the selected arrow, else (step 6) the focused scene."""
        if self.story_map.edge is not None:
            self.delete_arrow()
        else:
            self.delete_scene()

    def _script_refs(self) -> list[str]:
        return [ref for ref in self.refs if ref.startswith("script/") and ref.endswith(".vns")]

    def _script_text(self, ref: str) -> tuple[str, str | None]:
        """``ref``'s text as the editor holds it (an open file) or as on disk, without
        opening a record; and F44's read-only reason when it can't be edited (its text is
        then read leniently, only to find names in it)."""
        record = self.files.get(ref)
        if record is not None and record.editable:
            return record.widget.get("1.0", "end-1c"), None
        got = record.error if record is not None else open_document(self.paths, ref)
        if isinstance(got, ScriptDocument):
            return got.text, None
        reason = got.format() if got is not None else scriptedit.UNSAFE
        try:
            raw = (self.paths.root / ref).read_bytes()
        except OSError:
            raw = b""
        return raw.decode("utf-8", "replace").replace("\r\n", "\n"), reason

    def rename_scene(self) -> object:
        """Rename scene (F2 or a double-click on a box, PR-F46-09, 04 §6.5): the new name
        (its script name shown as you type), the question, then the label line and every
        line that goes to it changed in every script file as one undo step per file
        (closed files open unsaved) and one map step; the box keeps its place."""
        view = self.story_map
        old = view.focused_name()
        if self.closed or old is None or view.layout is None:
            return None
        if old == scriptedit.START:
            show_error(self.root, scriptedit.RENAME_START)
            return None
        taken = set(self._scene_names()) - {old}

        def hint(text: str) -> str:
            name = formdialogs.scene_name(text)
            if not name or name == old:
                return ""
            problem = files.label_problem(name)
            if problem is not None:
                return problem
            if name in taken:
                return scriptedit.NAME_TAKEN.format(name=show(name))
            return formdialogs.SCENE_NAMED.format(name=name)

        answer = ask_text(self.root, RENAME_SCENE_ASK.format(name=show(old)), old,
                          ok=RENAME_SCENE_OK, hint=hint)
        if answer is None:
            return None
        new = formdialogs.scene_name(answer[0])
        if not new or new == old:
            return None
        positions = self._positions()
        hits: dict[str, list] = {}
        locked: dict[str, str] = {}
        texts: dict[str, list[str]] = {}
        busy = self._busy(True)
        try:
            for ref in self._script_refs():
                text, reason = self._script_text(ref)
                if reason is not None:
                    locked[ref] = reason
                found = scriptedit.rename_hits(ref, text, old, positions=positions)
                if found:
                    hits[ref] = found
                texts[ref] = text.split("\n")
        finally:
            self._busy(busy)
        place = view.places.get(old) or layout_places(view.layout).get(old)

        def plan(confirm: bool) -> object:
            try:
                return scriptedit.plan_rename(hits, old, new, taken=taken, locked=locked,
                                              texts=texts, place=place, confirm=confirm)
            except Exception:           # a planner bug must never reach the text
                return scriptedit.Refuse(scriptedit.UNSAFE)
        result = plan(False)
        if isinstance(result, scriptedit.Ask):
            if self.story_ask(result.text, result.buttons, escape=result.escape,
                              default=result.default) != 0:
                return None
            result = plan(True)
        if isinstance(result, scriptedit.Refuse):
            show_error(self.root, result.text)
            return None
        if not isinstance(result, scriptedit.Plan):
            return None
        if not self.apply_plan(result, lambda now: scriptedit.verify(result, now,
                                                                     positions=positions)):
            show_error(self.root, scriptedit.UNSAFE)
            return None
        self.follow()
        self.map_plan_done(result)
        story = self.story
        if story is not None and story.key is not None and story.key[0] == old:
            story.key = (new, story.key[1])
            story.refresh()
        self._map_done(result)
        self._update_marks()
        index = view.layout.index_of(new) if view.layout is not None else None
        if index is not None:
            view.focus_box(index)
        return result

    def _busy(self, on: bool) -> bool:
        """The busy cursor on (or back off); gives whether it was on."""
        was = str(self.root.cget("cursor")) == "watch"
        try:
            self.root.configure(cursor="watch" if on else "")
            if on:
                self.root.update_idletasks()
        except tk.TclError:
            pass
        return was

    def delete_scene(self) -> object:
        """Delete scene (Delete on a box, PR-F46-16): after the question naming the arrows
        that lead there, its label and block go as one undo step."""
        view = self.story_map
        name = view.focused_name()
        if self.closed or name is None or self.story is None or view.layout is None:
            return None
        if name == scriptedit.START:
            self._map_say(scriptedit.DELETE_START)
            return None
        ref = self._scene_file(name)
        if ref is None:
            return None
        self._record(ref)
        here = view.layout.index_of(name)
        arrows = sum(1 for edge in view.layout.edges if edge.dst == here)
        plan = self.story.act_on(ref, name, lambda read, lines, start, **kw:
                                 scriptedit.plan_delete_scene(read, lines, start,
                                                              arrows=arrows, **kw))
        self._map_done(plan)
        return plan

    def change_target(self) -> object:
        """Change target… on an arrow (PR-F46-10): pick a scene; only the line's target
        word changes."""
        view = self.story_map
        found = view.selected_edge()
        if self.closed or found is None or self.story is None:
            return None
        src, dst, kind, _choice = found
        ref = self._scene_file(src)
        if ref is None:
            return None
        names = [name for name in self._scene_names() if name != dst]
        picked = formdialogs.pick_scene(self.root, names, title=CHANGE_TARGET_TITLE,
                                        ok=CHANGE_TARGET_OK)
        if picked is None:
            return None
        return self.retarget(src, dst, kind, picked)

    def retarget(self, src: str, dst: str, kind: str, new: str) -> object:
        """Point the arrow ``src → dst`` (``kind``) at ``new`` (Change target…, or its
        head dragged onto another box)."""
        ref = self._scene_file(src)
        if ref is None or self.story is None:
            return None
        self._record(ref)
        plan = self.story.act_on(ref, src, lambda read, lines, start, **_kw:
                                 scriptedit.plan_retarget(read, lines, start, dst, new, kind))
        self._map_done(plan)
        index = self.story_map.edge_index(src, new, kind)
        if plan is not None and index is not None:
            self.story_map.select_edge(index)
        return plan

    def _head_dropped(self, index: int, target: int) -> object:
        """A selected arrow's head dropped on box ``target`` (PR-F46-10)."""
        layout = self.story_map.layout
        if layout is None or not 0 <= index < len(layout.edges):
            return None
        edge = layout.edges[index]
        return self.retarget(layout.boxes[edge.src].name, layout.boxes[edge.dst].name,
                             edge.kind, layout.boxes[target].name)

    def preview_scene(self) -> None:
        """Preview from this scene (a box's context menu, PR-F46-17): F44's preview,
        started at the focused box's label."""
        name = self.story_map.focused_name()
        if name is not None:
            self.preview(at=name)

    def move_box(self) -> None:
        """Move box (G3): the focused box follows the arrow keys until Enter."""
        self.story_map.start_move()

    def tidy_up(self) -> None:
        self.story_map.tidy_up()

    def insert_command(self) -> None:
        if self.story is not None:
            self.story.insert(self.events_view.selected())

    def edit_command(self) -> None:
        index = self.events_view.selected()
        if self.story is not None and index is not None:
            self.story.edit(index)

    def move_command(self, step: int) -> None:
        index = self.events_view.selected()
        if self.story is not None and index is not None:
            self.story.move(index, step)

    def delete_command(self) -> None:
        index = self.events_view.selected()
        if self.story is not None and index is not None:
            self.story.delete(index)
