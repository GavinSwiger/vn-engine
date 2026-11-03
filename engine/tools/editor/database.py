"""Studio's Database tab (F47 ``01-design.md`` §4.3, §6.2, §6.4; ``04-technical.md`` §3.2, §7.1;
PR-F47-02, 03, 05, 10..13; AC-F47-04, 07, 09..12).

Why this module exists: RPG Maker's Database for a visual novel. A non-programmer makes
characters, pictures, sounds and variables from lists and forms instead of typing
``define``/``default``/``image`` lines. Three sashed columns: **categories** (with counts),
the category's **list** (``+ New``, a search box, an empty state), and the selected
entry's **form**. Forms apply each field on Enter or focus-out (one undo step per file per
field, no OK button). The ``.vns`` text stays the only truth: every write is a
``declplan`` plan applied through ``win.apply_plan`` (stale-checked by
``declplan.verify_decl``); files are added through F45's Add files… checks
(``win.add_files``) and deleted with ``files.delete_file``.

- **Characters**: name shown, name colour, text colour and italics, the looks gallery
  (``images/<tag>/``, + Add looks…), the voice blip (sound ▶, every, pitch, volume).
- **Pictures**: backgrounds, each character's looks and other pictures, as thumbnails;
  + Add backgrounds… and + Colour background (``image bg <n> = "#rrggbb"``).
- **Sounds**: Music, Sound effects, Voices, Blips, Other (by folder), ▶/■ through the
  helper child (one sound at a time, stopped on a tab or category switch).
- **Variables**: name, kind (Number, Text, Yes-No) and starting value (``default``), and
  "Remembered across playthroughs" (``default persistent.<n>``).
- W7's P2 categories (Meters, Codex, Endings & routes, Chapters, Transitions, Positions)
  live in ``dbmore.MoreCategories``, a mixin of the pane; the Positions canvas is
  ``stagecanvas.StageCanvas``.

Every entry shows "Used in N lines" (the last check's ``*_use`` rows) with **Show uses**
(the Problems panel lists the lines), and Delete is refused while it is used. The lists are
rebuilt when the tab shows, after each check (``win.on_check_done``) and after each write.
Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any

from engine.script.messages import show
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, fieldhints, files
from engine.tools.editor.dbmore import (
    ABOUT_MORE,
    DELETE,
    DELETE_BUTTONS,
    IN_SCRIPT,
    PREFIXES,
    READ_ONLY,
    REMEMBERED_HINT,
    RENAME_LOCKED,
    MoreCategories,
    Row,
)
from engine.tools.editor.dialogs import ask, ask_text, show_error
from engine.tools.editor.document import ScriptDocument, open_document
from engine.tools.editor.fieldwidgets import (
    AssetPicker,
    ChoiceField,
    ColorField,
    FormGrid,
    Gallery,
    NumberField,
    ScrollFrame,
    TextField,
    ToggleField,
    color_dot,
)
from engine.tools.editor.helperhub import CANT_PLAY, PLAYING, ThumbLoader, hub_for
from engine.tools.editor.preview import Report
from engine.tools.editor.scriptedit import STALE, Refuse
from engine.tools.editor.theme import THEME
from engine.tools.editor.views import EmptyState, panel_header

# --- Texts (design §6.4; the rest are this step's, in the same voice) --------------------------

# Every category, P1 then P2, in the design's order (§4.3).
ALL_CATEGORIES = (*db.CATEGORIES, *db.P2_CATEGORIES)
TITLES: Mapping[str, str] = {key: db.CATEGORY_TITLES[key] for key in ALL_CATEGORIES}
# Lower-cased titles, built rather than spelled: "characters" as a literal belongs only to
# core/constants.py (the meta-files write root; tests/core/test_paths_meta.py).
THINGS: Mapping[str, str] = {key: db.EMPTY_THINGS.get(key, title.lower())
                             for key, title in TITLES.items()}
CATEGORIES_HEADING = "Categories"
NEW_BUTTON = "+ New"
SEARCH_HINT = "Search…"
NO_MATCH = "Nothing matches “{text}”."
PICK_ENTRY = "Pick something in the list to see it here."
ABOUT: Mapping[str, str] = {        # an empty category's form explains what it is for
    db.CATEGORY_CHARACTER: "Characters are the people who speak in your story. Each has a "
                           "name, a colour, pictures (looks) and, if you like, a voice blip.",
    db.CATEGORY_VARIABLE: "Variables remember things while the game plays, such as a choice "
                          "the player made or how many coins they have.",
    **ABOUT_MORE}
REFUSED_BUTTONS = (db.SHOW_USES, "OK")
DELETE_ASK = "Delete {name}? Its line is removed from {ref}; Edit ▸ Undo there brings it back."
DELETE_FILE_ASK = "Delete {ref} from the game folder? This can't be undone."
USES_HEAD = "{name} is used in {lines}:"
NOT_CHECKED = "Not checked yet"
NEW_CHARACTER_ASK = "Name of the new character, as players will see it:"
NEW_VARIABLE_ASK = "Name of the new variable:"
NEW_COLOR_ASK = "Name of the new colour background:"
RENAME_ASK = "New script name for {name}:"
ADD_LOOKS = "+ Add looks…"
ADD_BACKGROUNDS = "Add backgrounds…"
ADD_COLOR = "Colour background…"
ADD_PICTURES_TO = "Add pictures to {title}…"
ADD_SOUNDS = {"music": "Add music…", "sound": "Add sound effects…", "voice": "Add voices…",
              "blips": "Add blips…"}
NO_LOOKS = "No looks yet. Add pictures of {name} with + Add looks…"
BACKGROUNDS = "Backgrounds"
LOOKS_OF = "{name}'s looks"
PICTURES_OF = "{tag} pictures"
OTHER_PICTURES = "Other pictures"
COLOR_WORD = "colour"
FOLDER_EMPTY = "empty"
NAME_FROM = "Comes from the variable {name}"
PLAY_BUTTON = "▶ Play"
STOP_BUTTON = "■ Stop"
YES, NO = "Yes", "No"

LABEL_NAME = "Name shown"
LABEL_NAME_COLOR = "Name colour"
LABEL_TEXT_COLOR = "Text colour"
LABEL_TEXT_STYLE = "Text style"
LABEL_ITALIC = "Italic"
LABEL_SOUND = "Sound"
LABEL_EVERY = "Every"
LABEL_PITCH = "Pitch"
LABEL_VOLUME = "Volume"
EVERY_HINT = "Blip on every this many letters (1 to 10)."
PITCH_HINT = "How much each blip's pitch varies: 0 (none) to 0.5."
VOLUME_HINT = "Loudness in % of the sound volume (0 to 100)."
LABEL_SCRIPT_NAME = "Script name"
LABEL_KIND = "Kind"
LABEL_START = "Starting value"
LABEL_COLOR = "Colour"
LABEL_FILE = "File"
LABEL_FOLDER = "Folder"

# A new character's name colour, so names differ at a glance (cycled by count).
NEW_COLORS = ("#e06c9f", "#4f8fd8", "#e0a040", "#5cb85c", "#a070d0", "#40b0b0", "#d05050")

# --- Sizes (px at 100 %) ------------------------------------------------------------------------

CATEGORY_WIDTH = 160
LIST_WIDTH = 240
FORM_MIN_WIDTH = 320
COMPACT_BELOW = 900             # window width under which categories become a drop-down
DOT_PX = 10
PREVIEW_PX = 192
FORM_PAD = 16
SCRIPT_TEXTS_MAX = 64           # 04 §7.1: the overlay cap

AUDIO_PREFIX = "audio/"
IMAGES_PREFIX = "images/"


# --- Rows ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class UseItem:
    """A Show uses paragraph (a ``preview.ReportItem`` with an info icon)."""

    text: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    severity: str = "info"


def script_texts(win: Any) -> dict[str, str]:
    """Every script's editor text: the open document's, else the file's on disk (04 §7.1)."""
    texts: dict[str, str] = {}
    for ref in list(win.refs)[:SCRIPT_TEXTS_MAX]:
        record = win.files.get(ref)
        if record is not None:
            if record.editable:
                texts[ref] = record.widget.get("1.0", "end-1c")
            continue
        try:
            found = open_document(win.paths, ref)
        except ValueError:
            continue
        if isinstance(found, ScriptDocument):
            texts[ref] = found.text
    return texts


def lines_word(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


def look_name(name: str) -> str:
    """``hana happy`` → ``happy``; a one-word name stays."""
    parts = name.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else name


# --- The pane -----------------------------------------------------------------------------------

@dataclass
class _Form:
    """The form on screen: its key (rebuilt when it changes), and how to show new values."""

    key: tuple
    update: Callable[[Row], object] | None = None
    fields: dict[str, Any] = field(default_factory=dict)


class DatabasePane(MoreCategories):
    """The Database tab of ``win`` (an ``EditorWindow``): ``frame`` is the notebook page."""

    def __init__(self, win: Any, parent: tk.Misc) -> None:
        self.win = win
        self.root = win.root
        self.scale = win.scale
        px = self._px
        self.category = db.CATEGORY_CHARACTER
        self.rows: dict[str, list[Row]] = {key: [] for key in ALL_CATEGORIES}
        self.chosen: dict[str, str | None] = {key: None for key in ALL_CATEGORIES}
        self.texts: dict[str, str] = {}
        self.decls: tuple[dec.Decl, ...] = ()
        self.names: Mapping = {}
        self.form: _Form | None = None
        self.compact = False
        self._search_live = False
        self._refresh_id: str | None = None
        self.fonts = win.fonts
        style = ttk.Style(self.root)
        style.configure("Caption.TLabel", background=THEME["editor.background"],
                        foreground=THEME["muted"], font=self.fonts["caption"])
        style.configure("Link.Ghost.TButton", foreground=THEME["link"],
                        padding=(px(4), px(2)))
        style.configure("Detail.TLabel", background=THEME["editor.background"],
                        foreground=THEME["muted"], font=self.fonts["small"])

        self.frame = ttk.Frame(parent)
        self.paned = tk.PanedWindow(self.frame, orient="horizontal",
                                    sashwidth=px(4), borderwidth=0, sashrelief="flat",
                                    background=THEME["sash"])
        self.paned.pack(fill="both", expand=True)

        # Categories (chrome, like a side bar).
        self.cat_frame = ttk.Frame(self.paned, style="Side.TFrame")
        panel_header(self.cat_frame, CATEGORIES_HEADING, self.scale).pack(fill="x")
        self.cat_tree = ttk.Treeview(self.cat_frame, show="tree", selectmode="browse",
                                     columns=("count",), height=1)
        self.cat_tree.column("#0", width=px(110), stretch=True)
        self.cat_tree.column("count", width=px(40), anchor="e", stretch=False)
        self.cat_tree.pack(fill="both", expand=True)
        for key in ALL_CATEGORIES:
            self.cat_tree.insert("", "end", iid=key, text=TITLES[key], values=("",))
        self.cat_tree.bind("<<TreeviewSelect>>", self._on_category, add="+")
        self.cat_tree.bind("<Return>", lambda _e: (self.list_tree.focus_set(), "break")[1])

        # The list.
        self.list_frame = ttk.Frame(self.paned)
        self.list_head = panel_header(self.list_frame, TITLES[self.category], self.scale)
        self.list_head.pack(fill="x")
        self.list_title = self.list_head.winfo_children()[0]
        self.new_button = ttk.Button(self.list_head, text=NEW_BUTTON, command=self.new_entry,
                                     style="Chrome.Ghost.TButton", takefocus=1)
        self.new_button.pack(side="right", padx=(0, px(4)))
        self.cat_choice = ChoiceField(self.list_frame, [(k, TITLES[k]) for k in ALL_CATEGORIES],
                                      self.category,
                                      on_change=lambda key: self.select_category(str(key)))
        self.search_var = tk.StringVar(master=self.root)
        self.search = ttk.Entry(self.list_frame, textvariable=self.search_var)
        self.search.pack(fill="x", padx=px(8), pady=(px(8), px(6)))
        self._search_placeholder(True)
        self.search.bind("<FocusIn>", lambda _e: self._search_placeholder(False), add="+")
        self.search.bind("<FocusOut>", lambda _e: self._search_placeholder(
            not self.search_var.get()), add="+")
        self.search_var.trace_add("write", lambda *_a: self._on_search())
        self.search.bind("<Down>", lambda _e: (self._focus_list(), "break")[1])
        self.list_body = ttk.Frame(self.list_frame)
        self.list_body.pack(fill="both", expand=True)
        self.list_tree = ttk.Treeview(self.list_body, show="tree", selectmode="browse",
                                      columns=("detail",), height=1, style="Surface.Treeview")
        self.list_tree.column("#0", width=px(120), stretch=True)
        self.list_tree.column("detail", width=px(96), anchor="e", stretch=False)
        self.list_tree.tag_configure("group", foreground=THEME["muted"],
                                     font=self.fonts["caption"])
        self.list_tree.tag_configure("muted", foreground=THEME["muted"])
        self.list_tree.pack(fill="both", expand=True)
        self.list_tree.bind("<<TreeviewSelect>>", self._on_row, add="+")
        self.list_tree.bind("<Delete>", lambda _e: (self.delete_selected(), "break")[1])
        self.list_tree.bind("<F2>", lambda _e: (self.rename_selected(), "break")[1])
        for key in ("<Return>", "<KP_Enter>"):
            self.list_tree.bind(key, lambda _e: (self._focus_form(), "break")[1])
        self.list_tree.bind("<space>", lambda _e: (self._toggle_row_sound(), "break")[1])
        self.list_tree.bind("<Double-Button-1>", lambda _e: self._toggle_row_sound(),
                            add="+")
        self._dots: dict[str | None, tk.PhotoImage] = {}
        self.empty = EmptyState(self.list_body, icon="add", title="", hint=db.EMPTY_HINT,
                                button=NEW_BUTTON, command=self.new_entry, scale=self.scale)
        self.empty.hint.configure(wraplength=px(LIST_WIDTH - 40))   # fits the list column

        # The form.
        self.form_frame = ttk.Frame(self.paned)
        self.scroll = ScrollFrame(self.form_frame)
        self.scroll.frame.pack(fill="both", expand=True)
        self.body: ttk.Frame | None = None

        self.paned.add(self.cat_frame, width=px(CATEGORY_WIDTH), minsize=px(120),
                       stretch="never")
        self.paned.add(self.list_frame, width=px(LIST_WIDTH), minsize=px(160),
                       stretch="never")
        self.paned.add(self.form_frame, minsize=px(FORM_MIN_WIDTH), stretch="always")
        self.frame.bind("<Configure>", self._on_resize, add="+")

        self.thumbs = ThumbLoader(win, self.frame, px(96), self._thumb_ready)
        self.previews = ThumbLoader(win, self.frame, px(PREVIEW_PX), self._thumb_ready)
        self.gallery: Gallery | None = None
        self.gallery_refs: dict[str, str] = {}     # gallery key → image ref
        self.sound_status = ""
        self._listening = False
        win.on_check_done.append(lambda _result: self._schedule_refresh())
        win.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab_changed(),
                          add="+")
        self.cat_tree.selection_set(self.category)

    # --- Small helpers ----------------------------------------------------------------------

    def _px(self, value: float) -> int:
        return round(value * self.scale)

    @property
    def shown(self) -> bool:
        try:
            return self.win.current_tab() == "database"
        except (tk.TclError, StopIteration, IndexError):
            return False

    def _search_placeholder(self, on: bool) -> None:
        self._search_live = not on
        if on and not self.search_var.get():
            self.search.configure(foreground=THEME["muted"])
            self._placeholder = True
            self.search_var.set(SEARCH_HINT)
        elif not on and getattr(self, "_placeholder", False):
            self._placeholder = False
            self.search_var.set("")
            self.search.configure(foreground=THEME["input.foreground"])

    def search_text(self) -> str:
        return "" if getattr(self, "_placeholder", False) else self.search_var.get()

    def set_search(self, text: str) -> None:
        """Type ``text`` into the search box (tests, keyboard helpers)."""
        self._search_placeholder(False)
        self.search_var.set(text)

    def _dot(self, color: str | None) -> tk.PhotoImage:
        image = self._dots.get(color)
        if image is None:
            image = self._dots[color] = color_dot(self.frame, color, self._px(DOT_PX))
        return image

    # --- Refresh ----------------------------------------------------------------------------

    def _schedule_refresh(self) -> None:
        if self.win.closed or self._refresh_id is not None:
            return
        self._refresh_id = self.root.after_idle(self.refresh)

    def refresh(self, select: str | None = None) -> None:
        """Read the scripts and the check again; rebuild the counts, the list and the form
        (the form only when what it shows changed). ``select`` picks a row by iid."""
        self._refresh_id = None
        if self.win.closed:
            return
        self.texts = script_texts(self.win)
        self.decls = dec.scan(self.texts)
        self.names = self.win.check_names
        self.rows = {db.CATEGORY_CHARACTER: self._character_rows(),
                     db.CATEGORY_PICTURE: self._picture_rows(),
                     db.CATEGORY_SOUND: self._sound_rows(),
                     db.CATEGORY_VARIABLE: self._variable_rows(),
                     **self._p2_rows()}
        for key in ALL_CATEGORIES:
            count = sum(1 for row in self.rows[key] if row.entry is not None)
            self.cat_tree.item(key, values=(str(count),))
        if select is not None:
            self.chosen[self.category] = select
        self._fill_list()

    def counts(self) -> dict[str, int]:
        return {key: int(self.cat_tree.set(key, "count") or 0) for key in ALL_CATEGORIES}

    def _read_texts(self) -> dict[str, str]:
        return script_texts(self.win)

    def _check_ran(self) -> bool:
        return self.win.check_result is not None

    def _detail(self, entry: db.Entry) -> str:
        """The form's line: "Used in 3 lines", "Not used yet" (or "Not checked yet")."""
        return entry.used_text if self._check_ran() else NOT_CHECKED

    def _short(self, entry: db.Entry) -> str:
        """The list's right column (design §6.2): "12 lines", "Not used yet"."""
        if not self._check_ran():
            return ""
        return lines_word(entry.uses) if entry.uses > 0 else db.NOT_USED

    def _character_rows(self) -> list[Row]:
        rows = []
        for entry in db.character_entries(self.decls, self.names):
            values = entry.decl.values if entry.decl is not None else None
            color = values.get("color") if values else None
            rows.append(Row(f"c:{entry.name}", entry.shown, self._short(entry), entry,
                            color=color if isinstance(color, str) else None))
        return rows

    def _variable_rows(self) -> list[Row]:
        rows = [Row(f"v:{entry.name}", entry.name, self._short(entry), entry)
                for entry in db.variable_entries(self.decls, self.names)]
        rows += self._remembered_rows()
        return sorted(rows, key=lambda r: (r.text.casefold(), r.iid))

    def _project_refs(self, group: str) -> list[str]:
        project = self.win.project
        return project.file_refs(group) if project is not None else []

    def _tag_title(self, tag: str) -> str:
        for decl in self.decls:
            if decl.kind == dec.CHARACTER and decl.values is not None:
                image_tag = decl.values.get("image_tag") or decl.name
                if str(image_tag).casefold() == tag.casefold():
                    shown = decl.values.get(dec.NAME) or decl.name
                    return LOOKS_OF.format(name=shown)
        return PICTURES_OF.format(tag=tag.capitalize())

    def _picture_rows(self) -> list[Row]:
        groups: dict[str, list[Row]] = {}
        for ref in self._project_refs("images"):
            parts = ref.split("/")
            tag = parts[1] if len(parts) == 3 else ""
            name = files.image_name_of(ref)
            uses = db.uses_of(self.names, db.BACKGROUND, name) if name else 0
            entry = db.Entry(db.BACKGROUND, name or ref, look_name(name) if name and tag
                             else (name or parts[-1]), None, False, uses)
            groups.setdefault(tag.casefold(), []).append(
                Row(f"p:{ref}", entry.shown, self._short(entry), entry, ref=ref,
                    group=tag.casefold()))
        for decl in self.decls:
            if decl.kind != dec.COLOR:
                continue
            words = decl.name.split()
            tag = words[0].casefold() if len(words) > 1 else ""
            uses = db.uses_of(self.names, dec.COLOR, decl.name)
            entry = db.Entry(dec.COLOR, decl.name, look_name(decl.name) if tag else
                             decl.name, decl.place, decl.values is not None, uses, decl)
            groups.setdefault(tag, []).append(
                Row(f"k:{decl.name}", f"{entry.shown} ({COLOR_WORD})", self._short(entry),
                    entry, group=tag,
                    color=str(decl.values["color"]) if decl.values else None))
        order = [dec.BACKGROUND_TAG] + sorted(k for k in groups if k not in
                                              (dec.BACKGROUND_TAG, "")) + [""]
        rows: list[Row] = []
        for key in order:
            members = sorted(groups.get(key, []), key=lambda r: r.text.casefold())
            if not members and key != dec.BACKGROUND_TAG:
                continue
            title = BACKGROUNDS if key == dec.BACKGROUND_TAG else \
                OTHER_PICTURES if key == "" else self._tag_title(key)
            gid = f"g:{key}"
            rows.append(Row(gid, title, str(len(members)) if members else FOLDER_EMPTY,
                            group=key, title=title))
            rows += [Row(r.iid, r.text, r.detail, r.entry, gid, r.ref, r.color, r.group)
                     for r in members]
        return rows

    def _sound_rows(self) -> list[Row]:
        groups: dict[str, list[Row]] = {f: [] for f in (*db.SOUND_FOLDERS, db.OTHER_SOUNDS)}
        for ref in self._project_refs("audio"):
            name = ref[len(AUDIO_PREFIX):]
            folder = db.sound_folder(name)
            entry = db.Entry(db.SOUND, name, name.rsplit("/", 1)[-1], None, False,
                             db.uses_of(self.names, db.SOUND, name), folder=folder)
            groups[folder].append(Row(f"s:{name}", entry.shown, self._short(entry), entry,
                                      ref=ref, group=folder))
        rows: list[Row] = []
        for folder, members in groups.items():
            if not members and folder == db.OTHER_SOUNDS:
                continue
            gid = f"g:{folder}"
            title = db.SOUND_TITLES[folder]
            rows.append(Row(gid, title, str(len(members)) if members else FOLDER_EMPTY,
                            group=folder, title=title))
            rows += [Row(r.iid, r.text, r.detail, r.entry, gid, r.ref, r.color, r.group)
                     for r in sorted(members, key=lambda r: r.text.casefold())]
        return rows

    # --- Categories -------------------------------------------------------------------------

    def _on_category(self, _event: tk.Event | None = None) -> None:
        chosen = self.cat_tree.selection()
        if chosen and chosen[0] != self.category:
            self.select_category(chosen[0])

    def select_category(self, key: str) -> None:
        if key not in ALL_CATEGORIES:
            return
        self.stop_sound()
        changed = key != self.category
        self.category = key
        if tuple(self.cat_tree.selection()) != (key,):
            self.cat_tree.selection_set(key)
        self.cat_choice.set(key)
        self.list_title.configure(text=TITLES[key].upper())
        if key in READ_ONLY:
            self.new_button.pack_forget()
        elif not self.new_button.winfo_ismapped():
            self.new_button.pack(side="right", padx=(0, self._px(4)))
        if changed:
            self.set_search("")
            self._search_placeholder(self.root.focus_get() is not self.search)
            self.form = None
        self._fill_list()

    def _on_resize(self, _event: tk.Event | None = None) -> None:
        compact = self.root.winfo_width() < self._px(COMPACT_BELOW)
        if compact == self.compact:
            return
        self.compact = compact
        if compact:
            self.paned.forget(self.cat_frame)
            self.cat_choice.widget.pack(fill="x", padx=self._px(8), pady=(self._px(8), 0),
                                        before=self.search)
        else:
            self.cat_choice.widget.pack_forget()
            self.paned.add(self.cat_frame, before=self.list_frame,
                           width=self._px(CATEGORY_WIDTH), minsize=self._px(120),
                           stretch="never")

    # --- The list ---------------------------------------------------------------------------

    def visible_rows(self) -> list[Row]:
        """The category's rows the search keeps (a group stays while one of its rows
        does)."""
        rows = self.rows[self.category]
        text = self.search_text().strip()
        if not text:
            return rows
        keep = {r.iid for r in rows if r.entry is not None
                and db.search([r.entry], text)}
        parents = {r.parent for r in rows if r.iid in keep}
        return [r for r in rows if r.iid in keep or r.iid in parents]

    def _fill_list(self) -> None:
        tree = self.list_tree
        rows = self.visible_rows()
        tree.delete(*tree.get_children())
        for row in rows:
            image = self._dot(row.color) if self.category == db.CATEGORY_CHARACTER or \
                row.iid.startswith("k:") else ""
            tags = ("group",) if row.entry is None else \
                ("muted",) if row.entry is not None and not row.entry.editable and \
                row.entry.kind in dec.EDITABLE_KINDS | {dec.POSITION} else ()
            tree.insert(row.parent, "end", iid=row.iid, text=" " + row.text if image else
                        row.text, values=(row.detail,), image=image, open=True, tags=tags)
        has_entries = any(r.entry is not None for r in self.rows[self.category])
        if self.category == db.CATEGORY_POSITION and self.positions is None:
            self.empty.hide()
            self._broken_positions_form()
            return
        if not has_entries:
            self.empty.title.configure(text=db.EMPTY_TITLE.format(
                things=THINGS[self.category]))
            read_only = self.category in READ_ONLY
            self.empty.hint.configure(text=db.CHAPTERS_HINT if read_only else db.EMPTY_HINT)
            if self.empty.button is not None:
                if read_only:
                    self.empty.button.pack_forget()
                elif not self.empty.button.winfo_ismapped():
                    self.empty.button.pack(pady=(self._px(16), 0))
            self.empty.show(self.list_body)
        else:
            self.empty.hide()
        chosen = self.chosen.get(self.category)
        if chosen is not None and tree.exists(chosen):
            if tuple(tree.selection()) != (chosen,):
                tree.selection_set(chosen)
                tree.focus(chosen)
            tree.see(chosen)
            self._show_form(self._row(chosen))
        else:
            first = next((r for r in rows if r.entry is not None), None)
            if first is not None and not self.search_text().strip():
                self.chosen[self.category] = first.iid
                tree.selection_set(first.iid)
                tree.focus(first.iid)
                self._show_form(first)
            elif self.search_text().strip() and not rows:
                self._message_form(NO_MATCH.format(text=self.search_text().strip()))
            elif not has_entries and self.category in ABOUT:
                self._message_form(ABOUT[self.category])
            else:
                group = next((r for r in rows if r.entry is None), None)
                if group is not None:
                    self._show_form(group)
                else:
                    self._message_form(PICK_ENTRY)

    def _row(self, iid: str) -> Row | None:
        return next((r for r in self.rows[self.category] if r.iid == iid), None)

    def selected_row(self) -> Row | None:
        chosen = self.list_tree.selection()
        return self._row(chosen[0]) if chosen else None

    def _on_row(self, _event: tk.Event | None = None) -> None:
        row = self.selected_row()
        if row is None or self.chosen.get(self.category) == row.iid and self.form is not None \
                and self.form.key[:2] == (self.category, row.iid):
            return
        self.stop_sound()                   # switching entry stops the sound (PR-F47-12)
        self.chosen[self.category] = row.iid
        self._show_form(row)

    def select(self, iid: str) -> None:
        """Select the row ``iid`` of the current category (tests, Show me)."""
        if self.chosen.get(self.category) != iid:
            self.stop_sound()
        self.chosen[self.category] = iid
        self._fill_list()

    def _on_search(self) -> None:
        if not self._search_live and getattr(self, "_placeholder", False):
            return
        self._fill_list()

    def _focus_list(self) -> None:
        self.list_tree.focus_set()
        children = self.list_tree.get_children()
        if children and not self.list_tree.selection():
            self.list_tree.selection_set(children[0])

    def _focus_form(self) -> None:
        if self.body is not None:
            self.body.focus_set()
            self.body.event_generate("<<NextWindow>>")

    @property
    def focus_widget(self) -> tk.Widget:
        return self.list_tree

    # --- Forms ------------------------------------------------------------------------------

    def _new_body(self, key: tuple) -> tuple[ttk.Frame, _Form]:
        if self.body is not None:
            self.body.destroy()
        self.gallery = None
        self.gallery_refs = {}
        pad = self._px(FORM_PAD)
        self.body = ttk.Frame(self.scroll.inner, padding=(pad, pad, pad, pad))
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self.form = _Form(key)
        self.scroll.top()
        return self.body, self.form

    def _message_form(self, text: str) -> None:
        body, _form = self._new_body(("message", text))
        if text:
            ttk.Label(body, text=text, style="Hint.TLabel", wraplength=self._px(360),
                      justify="left").grid(row=0, column=0, sticky="w")

    def _form_key(self, row: Row) -> tuple:
        entry = row.entry
        if entry is None:
            members = tuple(r.iid for r in self.rows[self.category] if r.parent == row.iid)
            return (self.category, row.iid, "group", members)
        values = entry.decl.values if entry.decl is not None else None
        shape: tuple = (entry.editable, entry.uses > 0, entry.place)
        if entry.kind == dec.CHARACTER and values is not None:
            shape += (values.get("name_from") is None, tuple(self._looks(entry)))
        if entry.kind in (dec.VARIABLE, dec.PERSISTENT) and values is not None:
            shape += (values.get("kind"),)
        more = self._p2_key(entry, shape)
        if more == ("stage",):
            return (self.category, "stage")
        return (self.category, row.iid, entry.kind, more or shape)

    def _show_form(self, row: Row | None) -> None:
        if row is None:
            self._message_form(PICK_ENTRY)
            return
        key = self._form_key(row)
        form = self.form
        if form is not None and form.key == key:
            if form.update is not None:
                form.update(row)
            return
        entry = row.entry
        if entry is None:
            self._group_form(row, key)
        elif entry.kind == dec.CHARACTER:
            self._character_form(row, key)
        elif entry.kind in (dec.VARIABLE, dec.PERSISTENT):
            self._variable_form(row, key)
        elif entry.kind in (db.BACKGROUND, dec.COLOR):
            self._picture_form(row, key)
        elif entry.kind == db.SOUND:
            self._sound_form(row, key)
        else:
            self._p2_form(row, key)
        self._wrap_hints()

    def _title(self, body: ttk.Frame, text: str, row: int = 0) -> ttk.Label:
        label = ttk.Label(body, text=text, style="Title.TLabel")
        label.grid(row=row, column=0, sticky="w", pady=(0, self._px(12)))
        return label

    def _uses_line(self, parent: tk.Misc, entry: db.Entry) -> ttk.Frame:
        line = ttk.Frame(parent)
        ttk.Label(line, text=self._detail(entry)).pack(side="left")
        if entry.uses > 0:
            ttk.Button(line, text=db.SHOW_USES, style="Link.Ghost.TButton",
                       command=lambda: self.show_uses(entry), cursor="hand2").pack(
                side="left", padx=(self._px(8), 0))
        return line

    def _bottom(self, body: ttk.Frame, row: int, entry: db.Entry,
                delete: Callable[[], object] | None) -> None:
        line = ttk.Frame(body)
        line.grid(row=row, column=0, sticky="ew", pady=(self._px(20), 0))
        if delete is not None:
            ttk.Button(line, text=DELETE, style="Secondary.TButton",
                       command=lambda: self.delete_entry(entry, delete)).pack(side="right")

    def _complex(self, body: ttk.Frame, row: int, entry: db.Entry) -> None:
        box = ttk.Frame(body)
        box.grid(row=row, column=0, sticky="w")
        ttk.Label(box, text=declplan.COMPLEX, wraplength=self._px(360),
                  justify="left").pack(anchor="w")
        if entry.place is not None:
            ref, line = entry.place
            ttk.Button(box, text=db.EDIT_AS_SCRIPT, style="Secondary.TButton",
                       command=lambda: self.win.jump_to(ref, line)).pack(
                anchor="w", pady=(self._px(8), 0))

    # Characters --------------------------------------------------------------------------

    def _looks(self, entry: db.Entry) -> list[str]:
        values = entry.decl.values if entry.decl is not None else None
        tag = str((values or {}).get("image_tag") or entry.name)
        folder = f"{IMAGES_PREFIX}{tag}/".casefold()
        return [ref for ref in self._project_refs("images")
                if ref.casefold().startswith(folder) and ref.count("/") == 2]

    def _look_tag(self, entry: db.Entry) -> str:
        values = entry.decl.values if entry.decl is not None else None
        return str((values or {}).get("image_tag") or entry.name)

    def _character_form(self, row: Row, key: tuple) -> None:
        entry = row.entry
        assert entry is not None
        body, form = self._new_body(key)
        title = self._title(body, entry.shown)
        if not entry.editable or entry.decl is None or entry.decl.values is None:
            self._complex(body, 1, entry)
            body.rowconfigure(2, minsize=self._px(12))
            self._uses_line(body, entry).grid(row=3, column=0, sticky="w")
            return
        values = dict(entry.decl.values)
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_CHARACTER))
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        if values.get(dec.NAME) is not None:
            f["name"] = TextField(grid.frame, str(values[dec.NAME]), width=28,
                                  check=lambda t: bool(t.strip()),
                                  on_change=lambda v: self._edit(entry, {dec.NAME: v.strip()}))
            grid.row(LABEL_NAME, f["name"])
        else:
            grid.row(LABEL_NAME, ttk.Label(grid.frame, text=NAME_FROM.format(
                name=values.get("name_from"))))
        f["color"] = ColorField(grid.frame, values.get("color"), allow_none=True,
                                scale=self.scale,
                                on_change=lambda v: self._edit(entry, {"color": v}))
        grid.row(LABEL_NAME_COLOR, f["color"])
        f["text_color"] = ColorField(grid.frame, values.get("text_color"), allow_none=True,
                                     scale=self.scale,
                                     on_change=lambda v: self._edit(entry, {"text_color": v}))
        grid.row(LABEL_TEXT_COLOR, f["text_color"])
        f["italic"] = ToggleField(grid.frame, LABEL_ITALIC, bool(values.get("text_italic")),
                                  on_change=lambda v: self._edit(entry, {"text_italic": v}))
        grid.row(LABEL_TEXT_STYLE, f["italic"])
        script = ttk.Frame(grid.frame)
        script_label = ttk.Label(script, text=db.SCRIPT_NAME.format(name=entry.name),
                                 style="Hint.TLabel")
        script_label.pack(side="left")
        if entry.name_editable:
            ttk.Button(script, text="Rename…", style="Link.Ghost.TButton",
                       command=self.rename_selected).pack(side="left",
                                                          padx=(self._px(8), 0))
        grid.widget(script, pady=(2, 2))
        grid.widget(self._uses_line(grid.frame, entry), pady=(2, 0))

        grid.caption("Looks", button=(ADD_LOOKS, lambda: self.add_looks(entry)))
        gallery = self._gallery(grid.frame, NO_LOOKS.format(name=entry.shown))
        grid.widget(gallery.widget, pady=(0, 4))
        self._fill_gallery([(ref, look_name(files.image_name_of(ref) or ref))
                            for ref in self._looks(entry)])

        grid.caption("Voice blip")
        sounds = self._sound_names()
        f["blip"] = AssetPicker(grid.frame, sounds, values.get("blip"), scale=self.scale,
                                play=lambda name: self.toggle_sound(AUDIO_PREFIX + name),
                                on_change=lambda v: self._edit(entry, self._blip_values(v)))
        grid.row(LABEL_SOUND, f["blip"])
        f["every"] = NumberField(grid.frame, int(values.get("blip_every", 2)), lo=1, hi=10,
                                 on_change=lambda v: self._edit(entry, {"blip_every": v}))
        grid.row(LABEL_EVERY, f["every"], hint=EVERY_HINT)
        f["pitch"] = NumberField(grid.frame, float(values.get("blip_pitch", 0.0)), lo=0.0,
                                 hi=0.5, step=0.05, whole=False,
                                 on_change=lambda v: self._edit(entry, {"blip_pitch": v}))
        grid.row(LABEL_PITCH, f["pitch"], hint=PITCH_HINT)
        f["volume"] = NumberField(grid.frame, int(values.get("blip_volume", 100)), lo=0,
                                  hi=100, step=5,
                                  on_change=lambda v: self._edit(entry, {"blip_volume": v}))
        grid.row(LABEL_VOLUME, f["volume"], hint=VOLUME_HINT)
        self.sound_label = ttk.Label(grid.frame, text="", style="Detail.TLabel")
        grid.widget(self.sound_label, pady=(0, 0))
        self._bottom(body, 2, entry, lambda: self._delete_decl(entry))

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            now = entry.decl.values
            title.configure(text=entry.shown)
            if "name" in f:
                f["name"].set(str(now.get(dec.NAME) or ""))
            f["color"].set(now.get("color"))
            f["text_color"].set(now.get("text_color"))
            f["italic"].set(bool(now.get("text_italic")))
            f["blip"].set_refs(self._sound_names())
            f["blip"].set(now.get("blip"))
            f["every"].set(int(now.get("blip_every", 2)))
            f["pitch"].set(float(now.get("blip_pitch", 0.0)))
            f["volume"].set(int(now.get("blip_volume", 100)))
            on = now.get("blip") is not None
            for name in ("every", "pitch", "volume"):
                f[name].enable(on)
            script_label.configure(text=db.SCRIPT_NAME.format(name=entry.name))
            self._sync_play_buttons()

        form.update = update
        update(row)

    def _blip_values(self, blip: object) -> dict[str, object]:
        if blip is None:            # tuning needs a blip (SR-F06-02): back to the defaults
            return {"blip": None, "blip_every": 2, "blip_pitch": 0.0, "blip_volume": 100}
        return {"blip": blip}

    def _sound_names(self) -> list[str]:
        names = [ref[len(AUDIO_PREFIX):] for ref in self._project_refs("audio")]
        return sorted(names, key=lambda n: (db.sound_folder(n) != "blips", n.casefold()))

    # Variables ---------------------------------------------------------------------------

    def _variable_form(self, row: Row, key: tuple) -> None:
        entry = row.entry
        assert entry is not None
        body, form = self._new_body(key)
        title = self._title(body, entry.name)
        if not entry.editable or entry.decl is None or entry.decl.values is None:
            self._complex(body, 1, entry)
            body.rowconfigure(2, minsize=self._px(12))
            self._uses_line(body, entry).grid(row=3, column=0, sticky="w")
            return
        values = dict(entry.decl.values)
        kind = str(values["kind"])
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_VARIABLE))
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        if entry.name_editable:
            f["name"] = TextField(grid.frame, entry.name, width=24,
                                  check=lambda t: bool(t.strip()),
                                  on_change=lambda v: self._rename(entry, str(v).strip()))
            grid.row(LABEL_SCRIPT_NAME, f["name"])
        else:
            grid.row(LABEL_SCRIPT_NAME, ttk.Label(grid.frame, text=entry.name),
                     hint=RENAME_LOCKED)
        f["kind"] = ChoiceField(grid.frame, [(k, dec.KIND_TITLES[k]) for k in
                                             dec.VARIABLE_KINDS], kind, width=12,
                                on_change=lambda v: self._edit(entry, {
                                    "kind": v, "value": dec.VARIABLE_STARTS[str(v)]}))
        grid.row(LABEL_KIND, f["kind"])
        if kind == dec.YES_NO:
            f["value"] = ChoiceField(grid.frame, [(True, YES), (False, NO)],
                                     bool(values["value"]), width=12,
                                     on_change=lambda v: self._edit(entry, {"value": v}))
        elif kind == dec.NUMBER:
            f["value"] = TextField(grid.frame, self._number_text(values["value"]), width=12,
                                   check=lambda t: self._number(t) is not None,
                                   on_change=lambda v: self._edit(entry, {
                                       "value": self._number(str(v))}))
        else:
            f["value"] = TextField(grid.frame, str(values["value"]), width=28,
                                   on_change=lambda v: self._edit(entry, {"value": v}))
        grid.row(LABEL_START, f["value"])
        remembered = entry.kind == dec.PERSISTENT
        f["remembered"] = ToggleField(
            grid.frame, db.REMEMBERED, remembered,
            on_change=lambda v: self._swap(entry, dec.PERSISTENT if v else dec.VARIABLE))
        grid.widget(f["remembered"].widget, pady=(6, 2))
        if remembered:
            grid.widget(ttk.Label(grid.frame, text=REMEMBERED_HINT.format(name=entry.name),
                                  style="Hint.TLabel"), pady=(0, 4))
        if not remembered:                  # the check counts no uses of persistent.<n>
            grid.widget(self._uses_line(grid.frame, entry), pady=(8, 0))
        self._bottom(body, 2, entry, lambda: self._delete_decl(entry))

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            now = entry.decl.values
            title.configure(text=entry.name)
            f["remembered"].set(entry.kind == dec.PERSISTENT)
            if "name" in f:
                f["name"].set(entry.name)
            value = now["value"]
            f["value"].set(self._number_text(value) if now["kind"] == dec.NUMBER else
                           bool(value) if now["kind"] == dec.YES_NO else str(value))

        form.update = update

    @staticmethod
    def _number(text: str) -> int | float | None:
        text = text.strip()
        try:
            return int(text)
        except ValueError:
            pass
        try:
            value = float(text)
        except ValueError:
            return None
        return value if value == value and value not in (float("inf"), float("-inf")) \
            else None

    @staticmethod
    def _number_text(value: object) -> str:
        return repr(value) if isinstance(value, float) else str(value)

    # Pictures ----------------------------------------------------------------------------

    def _group_form(self, row: Row, key: tuple) -> None:
        if self.category not in (db.CATEGORY_PICTURE, db.CATEGORY_SOUND):
            self._p2_group_form(row, key)
            return
        body, _form = self._new_body(key)
        self._title(body, row.title)
        buttons = ttk.Frame(body)
        buttons.grid(row=1, column=0, sticky="w", pady=(0, self._px(12)))
        members = [r for r in self.rows[self.category] if r.parent == row.iid]
        if self.category == db.CATEGORY_PICTURE:
            group = row.group or ""
            if group == dec.BACKGROUND_TAG:
                ttk.Button(buttons, text="+ " + ADD_BACKGROUNDS, style="Secondary.TButton",
                           command=lambda: self.add_pictures(dec.BACKGROUND_TAG)).pack(
                    side="left")
                ttk.Button(buttons, text="+ " + ADD_COLOR, style="Secondary.TButton",
                           command=self.new_color).pack(side="left", padx=(self._px(8), 0))
            elif group:
                ttk.Button(buttons, text="+ " + ADD_PICTURES_TO.format(title=row.title),
                           style="Secondary.TButton",
                           command=lambda: self.add_pictures(group)).pack(side="left")
            gallery = self._gallery(body, db.EMPTY_TITLE.format(things=THINGS[
                db.CATEGORY_PICTURE]))
            gallery.widget.grid(row=2, column=0, sticky="ew")
            gallery.on_select = lambda iid: self.select(iid)
            self._fill_gallery([(r.ref or r.iid, r.text) for r in members], keys=[
                r.iid for r in members])
        else:
            folder = row.group or ""
            if folder in ADD_SOUNDS:
                ttk.Button(buttons, text="+ " + ADD_SOUNDS[folder], style="Secondary.TButton",
                           command=lambda: self.add_sounds(folder)).pack(side="left")
            text = "\n".join(r.text for r in members) if members else \
                db.EMPTY_TITLE.format(things=row.title.casefold())
            ttk.Label(body, text=text, style="Hint.TLabel", justify="left").grid(
                row=2, column=0, sticky="w")

    def _gallery(self, parent: tk.Misc, empty_text: str) -> Gallery:
        self.gallery = Gallery(parent, scale=self.scale, font=self.fonts["small"],
                               empty_text=empty_text,
                               on_activate=lambda key: self._open_picture(key))
        return self.gallery

    def _fill_gallery(self, items: list[tuple[str, str]],
                      keys: list[str] | None = None) -> None:
        """``items`` are (image ref, label); ``keys`` the gallery keys (default: the refs)."""
        gallery = self.gallery
        if gallery is None:
            return
        keys = keys or [ref for ref, _label in items]
        self.gallery_refs = {key: ref for key, (ref, _label) in zip(keys, items)}
        gallery.set_items([(key, label) for key, (_ref, label) in zip(keys, items)])
        for key, (ref, _label) in zip(keys, items):
            if ref.startswith(IMAGES_PREFIX):
                image = self.thumbs.get(ref)
                if image is not None:
                    gallery.images[key] = image
        gallery.draw()

    def _thumb_ready(self, ref: str) -> None:
        gallery = self.gallery
        if gallery is not None:
            for key, shown in self.gallery_refs.items():
                if shown == ref:
                    image = self.thumbs.get(ref)
                    if image is not None:
                        gallery.set_image(key, image)
        if self.form is not None and self.form.update is not None and \
                getattr(self, "_preview_ref", None) == ref:
            row = self.selected_row()
            if row is not None:
                self.form.update(row)

    def _open_picture(self, key: str) -> None:
        if key.startswith(("p:", "k:")):
            self.select(key)
            return
        if key.startswith(IMAGES_PREFIX):
            self.win.show_asset(key)

    def _picture_form(self, row: Row, key: tuple) -> None:
        entry = row.entry
        assert entry is not None
        body, form = self._new_body(key)
        self._title(body, row.text)
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_PICTURE))
        grid.frame.grid(row=1, column=0, sticky="ew")
        if entry.kind == dec.COLOR:
            if entry.editable and entry.decl is not None and entry.decl.values is not None:
                form.fields["color"] = ColorField(
                    grid.frame, str(entry.decl.values["color"]), scale=self.scale,
                    on_change=lambda v: self._edit(entry, {"color": v}))
                grid.row(LABEL_COLOR, form.fields["color"])
            else:
                self._complex(body, 2, entry)
            if entry.name_editable:
                rename = ttk.Button(grid.frame, text="Rename…", style="Link.Ghost.TButton",
                                    command=self.rename_selected)
                grid.row(LABEL_SCRIPT_NAME, rename)
        else:
            picture = ttk.Label(grid.frame, style="TLabel")
            grid.widget(picture, pady=(0, 8))
            self._preview_ref = row.ref

            def update(_new: Row) -> None:
                image = self.previews.get(row.ref) if row.ref else None
                picture.configure(image=image or "", text="" if image else "…")
                picture.image = image                                 # type: ignore[attr-defined]

            form.update = update
            update(row)
            grid.row(LABEL_FILE, ttk.Label(grid.frame, text=show(row.ref or "")))
        verb = "scene" if entry.name.split()[0].casefold() == dec.BACKGROUND_TAG else "show"
        grid.widget(ttk.Label(grid.frame, text=IN_SCRIPT.format(line=f"{verb} {entry.name}"),
                              style="Hint.TLabel"), pady=(6, 2))
        grid.widget(self._uses_line(grid.frame, entry), pady=(2, 0))
        if entry.kind == dec.COLOR:
            delete = (lambda: self._delete_decl(entry)) if entry.editable else None
        else:
            delete = lambda: self._delete_file(entry, row.ref)              # noqa: E731
        self._bottom(body, 3, entry, delete)

    # Sounds ------------------------------------------------------------------------------

    def _sound_form(self, row: Row, key: tuple) -> None:
        entry = row.entry
        assert entry is not None and row.ref is not None
        body, form = self._new_body(key)
        self._title(body, row.text)
        grid = FormGrid(body, scale=self.scale,
                        tips=fieldhints.database_tips(db.CATEGORY_SOUND))
        grid.frame.grid(row=1, column=0, sticky="ew")
        grid.row(LABEL_FOLDER, ttk.Label(grid.frame, text=db.SOUND_TITLES[
            entry.folder or db.OTHER_SOUNDS]))
        grid.row(LABEL_FILE, ttk.Label(grid.frame, text=show(row.ref)))
        play = ttk.Frame(grid.frame)
        self.play_button = ttk.Button(play, text=PLAY_BUTTON, style="Secondary.TButton",
                                      command=lambda: self.toggle_sound(row.ref or ""))
        self.play_button.pack(side="left")
        self.sound_label = ttk.Label(play, text="", style="Detail.TLabel")
        self.sound_label.pack(side="left", padx=(self._px(12), 0))
        grid.widget(play, pady=(10, 4))
        if entry.folder == "music":
            line = f'play music "{entry.name}"'
        elif entry.folder == "blips":
            line = f'Character("…", blip="{entry.name}")'
        elif entry.folder == "voice":
            line = f'voice "{entry.name}"'
        else:
            line = f'play sound "{entry.name}"'
        grid.widget(ttk.Label(grid.frame, text=IN_SCRIPT.format(line=line),
                              style="Hint.TLabel"), pady=(6, 2))
        grid.widget(self._uses_line(grid.frame, entry), pady=(2, 0))
        self._bottom(body, 2, entry, lambda: self._delete_file(entry, row.ref))
        form.update = lambda _new: self._sync_play_buttons()
        self._sync_play_buttons()

    # --- Sounds (PR-F47-12) -----------------------------------------------------------------

    def hub_playing(self) -> str | None:
        hub = getattr(self.win, "helper_hub", None)
        return hub.playing if hub is not None else None

    def toggle_sound(self, ref: str) -> None:
        """▶ plays ``ref`` (``audio/…``); ■ (the same ref playing) stops it."""
        hub = hub_for(self.win)
        if not self._listening:
            hub.listen(self._sound_reply)
            self._listening = True
        if hub.playing == ref:
            hub.stop_sound()
            self.sound_status = ""
        else:
            hub.play(ref)
            self.sound_status = PLAYING.format(name=ref.rsplit("/", 1)[-1])
        self._sync_play_buttons()

    def stop_sound(self) -> None:
        hub = getattr(self.win, "helper_hub", None)
        if hub is not None and hub.playing is not None:
            hub.stop_sound()
            self.sound_status = ""
            self._sync_play_buttons()

    def _toggle_row_sound(self) -> None:
        row = self.selected_row()
        if row is not None and row.entry is not None and row.entry.kind == db.SOUND \
                and row.ref is not None:
            self.toggle_sound(row.ref)

    def _sound_reply(self, reply: Any) -> None:
        if reply.op == "play" and not reply.ok:
            self.sound_status = CANT_PLAY.format(reason=reply.reason or "")
        elif reply.op == "ended" or (reply.op == "stop" and self.hub_playing() is None):
            self.sound_status = ""
        self._sync_play_buttons()

    def _sync_play_buttons(self) -> None:
        playing = self.hub_playing()
        row = self.selected_row()
        button = getattr(self, "play_button", None)
        if button is not None and button.winfo_exists() and row is not None:
            button.configure(text=STOP_BUTTON if playing == row.ref else PLAY_BUTTON)
        if self.form is not None and "blip" in self.form.fields:
            picker = self.form.fields["blip"]
            value = picker.value
            picker.set_playing(isinstance(value, str) and playing == AUDIO_PREFIX + value)
        label = getattr(self, "sound_label", None)
        if label is not None and label.winfo_exists():
            label.configure(text=self.sound_status if playing is not None or
                            self.sound_status.startswith(CANT_PLAY[:10]) else "")

    def _on_tab_changed(self) -> None:
        if not self.shown:
            self.stop_sound()

    # --- Writing (04 §7.1) ------------------------------------------------------------------

    def _fresh(self, entry: db.Entry) -> dec.Decl | None:
        """``entry``'s declaration as the texts hold it now."""
        self.texts = script_texts(self.win)
        old = entry.decl
        if old is None:
            return None
        return dec.find(dec.scan(self.texts), old.kind, old.name, old.ref)

    def _edit(self, entry: db.Entry, change: Mapping[str, object]) -> bool:
        """One field changed: rewrite the declaration with it (one undo step)."""
        decl = self._fresh(entry)
        if decl is None or decl.values is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        values = {**decl.values, **change}
        return self._write(declplan.plan_edit(decl, values, self.texts))

    def _rename(self, entry: db.Entry, name: str) -> bool:
        decl = self._fresh(entry)
        if decl is None or decl.values is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        if name == decl.name:
            return True
        prefix = PREFIXES[decl.kind]
        return self._write(declplan.plan_edit(decl, decl.values, self.texts, name=name),
                           select=prefix + name)

    def _write(self, plan: object, select: str | None = None) -> bool:
        """Apply a ``DeclPlan`` (creating ``database.vns`` first when it says so), or show a
        ``Refuse``'s text. Then the lists are read again."""
        if plan is None:
            return True
        if isinstance(plan, Refuse):
            show_error(self.root, plan.text)
            self.refresh()
            return False
        assert isinstance(plan, declplan.DeclPlan)
        if plan.create is not None:
            folder, name = plan.create.rsplit("/", 1)
            made = files.new_script(self.win.paths, folder, name, text=declplan.DATABASE_TEXT)
            if isinstance(made, files.Refusal):
                show_error(self.root, made.text)
                return False
            self.win.refresh_project()
        if not self.win.apply_plan(plan.plan, lambda texts: declplan.verify_decl(plan, texts)):
            show_error(self.root, STALE)
            self.refresh()
            return False
        self.win._update_marks()
        self.refresh(select=select)
        return True

    def new_entry(self) -> None:
        """+ New for the category on screen."""
        if self.category == db.CATEGORY_CHARACTER:
            self.new_character()
        elif self.category == db.CATEGORY_VARIABLE:
            self.new_variable()
        elif self.category in (db.CATEGORY_PICTURE, db.CATEGORY_SOUND):
            self._new_menu()
        else:
            self._p2_new()

    def _new_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        if self.category == db.CATEGORY_PICTURE:
            menu.add_command(label=ADD_BACKGROUNDS,
                             command=lambda: self.add_pictures(dec.BACKGROUND_TAG))
            menu.add_command(label=ADD_COLOR, command=self.new_color)
            tags = [r for r in self.rows[db.CATEGORY_PICTURE] if r.entry is None
                    and r.group not in (dec.BACKGROUND_TAG, "")]
            for decl in self.decls:
                if decl.kind == dec.CHARACTER and decl.values is not None:
                    tag = str(decl.values.get("image_tag") or decl.name)
                    if all(r.group != tag.casefold() for r in tags):
                        tags.append(Row(f"g:{tag}", "", "", group=tag,
                                        title=self._tag_title(tag)))
            if tags:
                menu.add_separator()
            for row in tags:
                menu.add_command(label=ADD_PICTURES_TO.format(title=row.title),
                                 command=lambda g=row.group: self.add_pictures(str(g)))
        else:
            for folder in db.SOUND_FOLDERS:
                menu.add_command(label=ADD_SOUNDS[folder],
                                 command=lambda f=folder: self.add_sounds(f))
        self.last_menu = menu
        x = self.new_button.winfo_rootx()
        y = self.new_button.winfo_rooty() + self.new_button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _taken(self, kind: str) -> frozenset[str]:
        return dec.taken_names(dec.scan(self.texts), kind)

    def new_character(self) -> bool:
        self.texts = script_texts(self.win)
        taken = self._taken(dec.CHARACTER)
        answer = ask_text(self.root, NEW_CHARACTER_ASK, "", ok="Add",
                          hint=lambda shown: IN_SCRIPT.format(
                              line=f"define {dec.script_name(shown, taken)}")
                          if shown.strip() else None)
        if answer is None or not answer[0].strip():
            return False
        shown = answer[0].strip()
        name = dec.script_name(shown, taken)
        count = sum(1 for d in self.decls if d.kind == dec.CHARACTER)
        values = {dec.NAME: shown, **dec.OPTION_DEFAULTS,
                  "color": NEW_COLORS[count % len(NEW_COLORS)]}
        self.select_category(db.CATEGORY_CHARACTER)
        return self._write(declplan.plan_new(dec.CHARACTER, name, values, self.texts),
                           select=f"c:{name}")

    def new_variable(self) -> bool:
        self.texts = script_texts(self.win)
        taken = self._taken(dec.VARIABLE)
        answer = ask_text(self.root, NEW_VARIABLE_ASK, "", ok="Add",
                          hint=lambda shown: IN_SCRIPT.format(
                              line=f"default {dec.script_name(shown, taken, dec.VARIABLE)}"
                                   " = 0") if shown.strip() else None,
                          option=db.REMEMBERED, option_value=False)
        if answer is None or not answer[0].strip():
            return False
        kind = dec.PERSISTENT if answer[1] else dec.VARIABLE
        name = dec.script_name(answer[0].strip(), self._taken(kind), kind)
        self.select_category(db.CATEGORY_VARIABLE)
        return self._write(declplan.plan_new(kind, name,
                                             {"kind": dec.NUMBER, "value": 0}, self.texts),
                           select=PREFIXES[kind] + name)

    def new_color(self) -> bool:
        """+ Colour background: a name, then a colour (``image bg <n> = "#rrggbb"``)."""
        from engine.tools.editor import fieldwidgets
        self.texts = script_texts(self.win)
        taken = self._taken(dec.COLOR)
        answer = ask_text(self.root, NEW_COLOR_ASK, "", ok="Next",
                          hint=lambda shown: IN_SCRIPT.format(
                              line=f"scene {dec.script_name(shown, taken, dec.COLOR)}")
                          if shown.strip() else None)
        if answer is None or not answer[0].strip():
            return False
        color = fieldwidgets.ask_color(self.root, "#203040")
        if color is None:
            return False
        name = dec.script_name(answer[0].strip(), taken, dec.COLOR)
        self.select_category(db.CATEGORY_PICTURE)
        return self._write(declplan.plan_new(dec.COLOR, name, {"color": color}, self.texts),
                           select=f"k:{name}")

    def rename_selected(self) -> None:
        """F2 / Rename…: a new script name while nothing uses the entry (PR-F47-10)."""
        row = self.selected_row()
        entry = row.entry if row is not None else None
        if entry is None or entry.kind not in dec.EDITABLE_KINDS or not entry.name_editable:
            return
        answer = ask_text(self.root, RENAME_ASK.format(name=entry.shown), entry.name,
                          ok="Rename")
        if answer is None or not answer[0].strip():
            return
        self._rename(entry, answer[0].strip())

    # --- Files (PR-F47-11) ------------------------------------------------------------------

    def _add(self, group: str, folder: str) -> None:
        made = files.ensure_folder(self.win.paths, folder)
        if made is not None:
            show_error(self.root, made.text)
            return
        self.win.add_files(target=(group, folder), on_done=lambda _refs: self.refresh())

    def add_looks(self, entry: db.Entry) -> None:
        """+ Add looks…: pictures into ``images/<tag>/`` (made when missing)."""
        self.add_pictures(self._look_tag(entry))

    def add_pictures(self, tag: str) -> None:
        self._add("images", f"{IMAGES_PREFIX}{tag}")

    def add_sounds(self, folder: str) -> None:
        self._add("audio", f"{AUDIO_PREFIX}{folder}")

    # --- Uses and delete (PR-F47-05) --------------------------------------------------------

    def _use_kind(self, entry: db.Entry) -> str:
        return entry.kind

    def show_uses(self, entry: db.Entry) -> None:
        """Show uses: the lines in the Problems panel, each a link to its line."""
        places = db.use_places(self.names, self._use_kind(entry), entry.name)
        items = []
        for ref, line in places:
            text = ""
            if ref is not None and line is not None:
                lines = self.texts.get(ref, "").split("\n")
                text = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            where = f"{ref}:{line}" if ref is not None and line is not None else (ref or "")
            items.append(UseItem(f"{where}: {text}" if text else where, ref, line))
        head = USES_HEAD.format(name=entry.shown, lines=lines_word(len(places)))
        self.win.show_report(Report("editor", head, tuple(items)))   # type: ignore[arg-type]

    def delete_entry(self, entry: db.Entry, delete: Callable[[], object]) -> None:
        refusal = db.delete_refusal(entry)
        if refusal is not None:
            if ask(self.root, refusal, REFUSED_BUTTONS, escape=1, default=1) == 0:
                self.show_uses(entry)
            return
        delete()

    def delete_selected(self) -> None:
        row = self.selected_row()
        if row is None or row.entry is None:
            return
        entry = row.entry
        if entry.kind in (db.BACKGROUND, db.SOUND):
            self.delete_entry(entry, lambda: self._delete_file(entry, row.ref))
        elif entry.kind == dec.POSITION:
            if entry.values and not entry.values.get("builtin"):
                self.delete_entry(entry, lambda: self.delete_position(entry))
        elif entry.editable:
            self.delete_entry(entry, lambda: self._delete_decl(entry))

    def _delete_decl(self, entry: db.Entry) -> bool:
        decl = self._fresh(entry)
        if decl is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        if ask(self.root, DELETE_ASK.format(name=entry.shown, ref=show(decl.ref)),
               DELETE_BUTTONS, escape=1, default=1) != 0:
            return False
        self.chosen[self.category] = None
        return self._write(declplan.plan_delete(decl, self.texts))

    def _delete_file(self, entry: db.Entry, ref: str | None) -> bool:
        if ref is None:
            return False
        if ask(self.root, DELETE_FILE_ASK.format(ref=show(ref)), DELETE_BUTTONS, escape=1,
               default=1) != 0:
            return False
        self.stop_sound()
        result = files.delete_file(self.win.paths, ref)
        if isinstance(result, files.Refusal):
            show_error(self.root, result.text)
            return False
        self.chosen[self.category] = None
        self.win.refresh_project()
        self.refresh()
        return True


__all__ = ["ALL_CATEGORIES", "DatabasePane", "Row", "TITLES", "THINGS", "UseItem",
           "script_texts"]
