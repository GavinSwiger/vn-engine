"""The Database's **Gallery** category and the Pictures form's gallery switch (F34
``01-design.md`` §7; ``04-technical.md`` §3, W4; AC-F34-29, 30, 31, 34).

Why this module exists: the gallery is the Extras page where players look again at the
pictures they've seen. A non-programmer never types ``lock gallery``: on a picture's form
in Database ▸ Pictures they turn on **In the gallery** (Studio writes the line with a title
made from the picture's name), and in Database ▸ **Gallery** they see the gallery as
thumbnails in the order players will, add pictures from a thumbnail picker, add up to 8
versions of a tile, retitle, reorder (**◀ Move earlier** / **Move later ▶**, through
``declplan.plan_move``) and run **▶ Preview the gallery** (the game's dev ``--extras``).

``GalleryCategory`` is a mixin of ``database.DatabasePane`` (as ``dbmore.MoreCategories``):
the pane's tree still holds the rows (selection, search, counts); in this category a
thumbnail grid (``fieldwidgets.Gallery``) is shown over it and mirrors it. Every write is a
``declplan`` plan applied through the pane's ``_write``.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import importlib.util
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from tkinter import ttk
from typing import Any

from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor import declplan, dialogs
from engine.tools.editor.dbmore import Row
from engine.tools.editor.dialogs import ask, show_error
from engine.tools.editor.fieldwidgets import (
    AssetPicker,
    FormGrid,
    Gallery,
    ScrollFrame,
    TextField,
    ToggleField,
)
from engine.tools.editor.scriptedit import STALE, Refuse
from engine.tools.editor.theme import ROLES, THEME

# --- Texts (design §7) ------------------------------------------------------------------------

ABOUT_GALLERY = ("The gallery is the Extras page where players look again at the pictures "
                 "they've seen. Add a picture here and it unlocks the first time it shows in "
                 "the story.")
EMPTY_HINT = "Add pictures you want players to collect."   # under "No gallery pictures yet"
ADD_PICTURES = "+ Add pictures…"
ADD_VERSION = "+ Add a version…"
MOVE_EARLIER = "◀ Move earlier"
MOVE_LATER = "Move later ▶"
PREVIEW = "▶ Preview the gallery"
PREVIEW_TIP = "Opens Extras with every picture unlocked. Nothing is saved."
PREVIEW_NOT_YET = ("Opens Extras with every picture unlocked. This engine can't open Extras "
                   "on its own yet; it comes with the Extras screen.")
ACROSS_FILES = declplan.MOVE_ACROSS_FILES
INFO = ("Players unlock this picture the first time it shows in the story, or with an "
        "Unlock gallery picture event.")
NEVER_SHOWN = "This picture never shows in the story yet, so players can't unlock it."
IN_GALLERY = "In the gallery"
GALLERY_TITLE = "Gallery title"
SWITCH_HINT = "Players unlock it the first time it shows in the story."
PART_OF = "Part of “{title}”"
GO_TO = "Go to"
LABEL_PICTURE = "Picture"
LABEL_TITLE = "Title"
VERSIONS = "More versions"
NO_VERSIONS = "None yet. A version is another picture in the same tile, such as a close-up."
VERSIONS_FULL = "A tile holds up to {n} more pictures."
REMOVE = "Remove"
REMOVE_FROM = "Remove from gallery"
REMOVE_ASK = ("Take “{title}” out of the gallery? Its line is removed from {ref}; Edit ▸ Undo "
              "there brings it back.")
REMOVE_BUTTONS = ("Remove", "Cancel")
USED_REFUSED = ("“{name}” is named in {lines} (Lock or Unlock gallery picture), so it can't be "
                "taken out of the gallery yet.")
REFUSED_BUTTONS = (db.SHOW_USES, "OK")
SHOWN_IN = "Shown in {lines}"
NOT_SHOWN = "Not shown in the story yet"
NOT_CHECKED = "Not checked yet"
USES_HEAD = "{name} is in {lines}:"
PICTURE_LOCKED = "Unlock lines name this picture, so it can't change here."
PICK_TITLE = "Add pictures to the gallery"
PICK_VERSION_TITLE = "Add a version"
PICK_HINT = "Click pictures to tick them, then Add. They go at the end of the gallery."
PICK_VERSION_HINT = "Pick the picture to add to this tile."
PICK_NONE = "Every picture is in the gallery already. Add pictures under Pictures first."
PICK_OK = "Add"
CANCEL = "Cancel"
COLOUR_LABEL = "{name} (colour)"

GALLERY_PREFIX = "y:"
LIST_PX = 452                          # the list column while Gallery shows (4 thumbnails)
SWATCH_PX = 96
EXTRAS_PAGE = "gallery"


def extras_ready() -> bool:
    """True when this engine's ``run`` has the dev ``--extras`` flag (F34-W3 adds it with
    ``engine/app/extras.py``); the check reads no code."""
    try:
        return importlib.util.find_spec("engine.app.extras") is not None
    except (ImportError, ValueError):
        return False


def lines_word(n: int) -> str:
    return f"{n} line" if n == 1 else f"{n} lines"


# --- The picture picker -----------------------------------------------------------------------

class _TickGallery(Gallery):
    """A ``Gallery`` whose clicks tick and untick pictures (``ticked``), with a ✓ badge."""

    def __init__(self, parent: tk.Misc, *, multi: bool, **kw: Any) -> None:
        self.multi = multi
        self.ticked: list[str] = []
        super().__init__(parent, **kw)

    def _choose(self, key: str) -> None:
        if self.multi:
            if key in self.ticked:
                self.ticked.remove(key)
            else:
                self.ticked.append(key)
        else:
            self.ticked = [key]
        super()._choose(key)

    def draw(self) -> None:
        super().draw()
        badge = max(12, self.side // 5)
        cw, ch = self._cell()
        for index, (key, _label) in enumerate(self.items):
            if key not in self.ticked:
                continue
            col, row = index % self.columns, index // self.columns
            x, y = col * cw + 1 + self.side - badge - 4, row * ch + 5
            self.canvas.create_rectangle(x, y, x + badge, y + badge,
                                         fill=THEME["focusBorder"], outline="")
            self.canvas.create_text(x + badge // 2, y + badge // 2, text="✓",
                                    fill=THEME["strongForeground"])


class PicturePicker:
    """A modal thumbnail picker: ``items`` (picture name, label); ``thumb(name)`` gives a
    ``PhotoImage`` or None (asked again while the dialog is open, so thumbnails arrive);
    ``multi``: several can be ticked. ``result``: the ticked names in the order ticked
    (None: Cancel)."""

    def __init__(self, parent: tk.Misc, items: Sequence[tuple[str, str]],
                 thumb: Callable[[str], object | None], *, multi: bool, title: str,
                 hint: str) -> None:
        self.result: list[str] | None = None
        self.thumb = thumb
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(title)
        dialog.resizable(True, True)
        body, scale = dialogs._body(dialog)
        ttk.Label(body, text=hint if items else PICK_NONE, style="Dialog.Hint.TLabel",
                  wraplength=round(440 * scale), justify="left").pack(
            anchor="w", pady=(0, round(8 * scale)))
        self.grid = _TickGallery(body, multi=multi, scale=scale,
                                 on_activate=lambda _key: self._pick(0))
        self.grid.canvas.configure(width=round(4 * 108 * scale), background=THEME[
            "widget.background"])
        self.grid.canvas.pack(fill="both", expand=True)
        self.grid.set_items(list(items))
        self.buttons = dialogs._buttons(dialog, body, (PICK_OK, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        self._poll()

    def _poll(self) -> None:
        missing = [key for key, _label in self.grid.items if key not in self.grid.images]
        for key in missing:
            image = self.thumb(key)
            if image is not None:
                self.grid.images[key] = image
        if missing:
            self.grid.draw()
            try:
                self.dialog.after(200, self._poll)
            except tk.TclError:
                pass

    def tick(self, name: str) -> None:
        """Tick (or untick) ``name`` as a click does (tests)."""
        self.grid._choose(name)

    def _pick(self, index: int) -> None:
        if index == 0:
            if not self.grid.ticked:
                return
            self.result = list(self.grid.ticked)
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> list[str] | None:
        dialogs._run(parent, self.dialog, self.grid.canvas)
        return self.result


def pick_pictures(parent: tk.Misc, items: Sequence[tuple[str, str]],
                  thumb: Callable[[str], object | None], *, multi: bool = True,
                  title: str = PICK_TITLE, hint: str = PICK_HINT) -> list[str] | None:
    """The picker, modal: the picked picture names, or None."""
    return PicturePicker(parent, items, thumb, multi=multi, title=title, hint=hint).run(parent)


# --- The mixin --------------------------------------------------------------------------------

class GalleryCategory:
    """Database ▸ Gallery and the Pictures form's switch (a mixin of
    ``database.DatabasePane``: it uses the pane's rows, forms and writers)."""

    win: Any
    root: Any
    scale: float
    texts: dict[str, str]
    decls: tuple[dec.Decl, ...]
    names: Mapping
    rows: dict[str, list[Row]]
    form: Any
    fonts: Any
    category: str
    chosen: dict[str, str | None]
    body: Any
    thumbs: Any
    paned: Any
    list_frame: Any
    list_body: Any
    list_tree: Any
    new_button: Any
    empty: Any
    _px: Callable[[float], int]
    _check_ran: Callable[[], bool]
    _new_body: Callable[[tuple], tuple[ttk.Frame, Any]]
    _title: Callable[..., ttk.Label]
    _complex: Callable[..., None]
    _fresh: Callable[[db.Entry], dec.Decl | None]
    _edit: Callable[[db.Entry, Mapping[str, object]], bool]
    _write: Callable[..., bool]
    _read_texts: Callable[[], dict[str, str]]
    _image_names: Callable[[], dict[str, str]]
    _read_only: Callable[[Row, tuple], bool]
    refresh: Callable[..., None]
    select: Callable[[str], None]
    select_category: Callable[[str], None]
    selected_row: Callable[[], Row | None]
    gallery_grid: Gallery | None = None
    gallery_box: Any = None
    move_buttons: tuple[Any, Any] | None = None
    move_note: Any = None
    preview_button: Any = None
    preview_tip: Any = None
    _swatches: dict[str, tk.PhotoImage] | None = None

    # --- Rows -------------------------------------------------------------------------------

    def _gallery_rows(self) -> list[Row]:
        return [Row(GALLERY_PREFIX + e.name, e.shown, self._gallery_short(e), e)
                for e in db.gallery_entries(self.decls, self.texts)]

    def gallery_entries(self) -> list[db.Entry]:
        """The Gallery category's entries in gallery order (as listed)."""
        return [r.entry for r in self.rows.get(db.CATEGORY_GALLERY, ()) if r.entry is not None]

    def _gallery_short(self, entry: db.Entry) -> str:
        if not self._check_ran():
            return ""
        shown = self._shown_places(entry)
        return lines_word(len(shown)) if shown else db.NOT_USED

    def _pictures_of(self, entry: db.Entry) -> tuple[str, ...]:
        values = entry.decl.values if entry.decl is not None else None
        return (entry.name, *((values or {}).get("versions") or ()))      # type: ignore[misc]

    def _shown_places(self, entry: db.Entry) -> list[tuple[str | None, int | None]]:
        """The distinct lines that put one of the entry's pictures on stage (the check's
        ``image_use`` rows, without F41's declaration and config.toml rows)."""
        seen: dict[tuple[str | None, int | None], None] = {}
        for picture in self._pictures_of(entry):
            for place in db.story_places(self.names, self.texts, db.BACKGROUND, picture):
                seen[place] = None
        return list(seen)

    def _lock_places(self, pictures: Sequence[str]) -> list[tuple[str, int]]:
        """The ``lock|unlock gallery`` lines naming one of ``pictures``."""
        return list(dict.fromkeys((ref, line) for name, ref, line, _u in
                                  dec.gallery_uses(self.texts) if name in pictures))

    # --- Thumbnails -------------------------------------------------------------------------

    def _swatch(self, color: str) -> tk.PhotoImage:
        if self._swatches is None:
            self._swatches = {}
        image = self._swatches.get(color)
        if image is None:
            side = self._px(SWATCH_PX)
            image = tk.PhotoImage(master=self.root, width=side, height=side * 9 // 16)
            image.put(color, to=(0, 0, side, side * 9 // 16))
            self._swatches[color] = image
        return image

    def picture_thumb(self, name: str) -> object | None:
        """The thumbnail of picture ``name``: its file's (loaded in the background; None
        until it arrives) or its colour's swatch."""
        for decl in self.decls:
            if decl.kind == dec.COLOR and decl.name.casefold() == name.casefold() \
                    and decl.values is not None:
                return self._swatch(str(decl.values["color"]))
        ref = self._image_names().get(name)
        return self.thumbs.get(ref) if ref else None

    def picture_names(self) -> list[str]:
        """Every picture the game has: its image files' names and its colour pictures."""
        found = dict.fromkeys(self._image_names())
        for decl in self.decls:
            if decl.kind == dec.COLOR:
                found.setdefault(decl.name)
        return sorted(found, key=str.casefold)

    def _picture_label(self, name: str) -> str:
        colour = any(d.kind == dec.COLOR and d.name == name for d in self.decls)
        return COLOUR_LABEL.format(name=name) if colour else name

    def _gallery_thumb_ready(self, _ref: str) -> None:
        if self.gallery_grid is not None and self.category == db.CATEGORY_GALLERY:
            self._fill_gallery_grid()

    # --- The list column --------------------------------------------------------------------

    def _build_gallery_list(self) -> None:
        """The thumbnail grid and its buttons, over the list (built once, when first shown)."""
        px = self._px
        box = self.gallery_box = ttk.Frame(self.list_body)
        scroll = ScrollFrame(box)
        scroll.frame.pack(fill="both", expand=True, padx=(px(8), 0))
        self.gallery_grid = Gallery(scroll.inner, scale=self.scale, font=self.fonts["small"],
                                    on_select=lambda key: self.select(key),
                                    on_activate=lambda _key: self._focus_gallery_form())
        self.gallery_grid.widget.pack(fill="x", expand=True)
        self.gallery_grid.canvas.bind("<Delete>",
                                      lambda _e: (self.remove_from_gallery(), "break")[1])
        bottom = ttk.Frame(box)
        bottom.pack(fill="x", padx=px(8), pady=(px(6), px(8)))
        moves = ttk.Frame(bottom)
        moves.pack(anchor="w")
        earlier = ttk.Button(moves, text=MOVE_EARLIER, style="Secondary.TButton",
                             command=lambda: self.move_gallery(-1))
        earlier.pack(side="left")
        later = ttk.Button(moves, text=MOVE_LATER, style="Secondary.TButton",
                           command=lambda: self.move_gallery(1))
        later.pack(side="left", padx=(px(8), 0))
        self.move_buttons = (earlier, later)
        self.move_note = ttk.Label(bottom, text="", style="Hint.TLabel", justify="left",
                                   wraplength=px(LIST_PX - 40))
        self.move_note.pack(anchor="w", pady=(px(4), 0))
        ready = extras_ready()
        self.preview_button = ttk.Button(bottom, text=PREVIEW, command=self.preview_gallery,
                                         state="normal" if ready else "disabled")
        self.preview_button.pack(anchor="w", pady=(px(8), 0))
        from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
        self.preview_tip = Tooltip(self.preview_button, PREVIEW_TIP if ready else PREVIEW_NOT_YET)

    def _show_gallery_list(self, on: bool) -> None:
        """Swap the tree and the thumbnail grid in the list column (and widen it)."""
        if on and self.gallery_box is None:
            self._build_gallery_list()
        box = self.gallery_box
        if box is None:
            return
        width = LIST_PX if on else None
        if on and not box.winfo_ismapped():
            self.list_tree.pack_forget()
            box.pack(fill="both", expand=True)
        elif not on and box.winfo_ismapped():
            box.pack_forget()
            self.list_tree.pack(fill="both", expand=True)
        if on != getattr(self, "_gallery_wide", False):
            self._gallery_wide = on
            from engine.tools.editor.database import LIST_WIDTH
            try:
                self.paned.paneconfigure(self.list_frame,
                                         width=self._px(width or LIST_WIDTH))
            except tk.TclError:
                pass
        self.new_button.configure(text=ADD_PICTURES if on else "+ New")

    def _gallery_after_fill(self, has_entries: bool) -> None:
        """After the list is filled: the grid, the buttons and the empty state's words."""
        on = self.category == db.CATEGORY_GALLERY
        self._show_gallery_list(on)
        if not on:
            if self.empty.button is not None:
                self.empty.button.configure(text="+ New")
            return
        if not has_entries:
            self.empty.hint.configure(text=EMPTY_HINT)
            if self.empty.button is not None:
                self.empty.button.configure(text=ADD_PICTURES)
        self._fill_gallery_grid()

    def visible_gallery(self) -> list[Row]:
        rows: list[Row] = self.visible_rows()                       # type: ignore[attr-defined]
        return [r for r in rows if r.entry is not None]

    def _fill_gallery_grid(self) -> None:
        grid = self.gallery_grid
        if grid is None:
            return
        rows = self.visible_gallery()
        grid.set_items([(r.iid, r.text) for r in rows])
        for row in rows:
            assert row.entry is not None
            image = self.picture_thumb(row.entry.name)
            if image is not None:
                grid.images[row.iid] = image
        chosen = self.chosen.get(db.CATEGORY_GALLERY)
        grid.selected = chosen if any(r.iid == chosen for r in rows) else None
        grid.draw()
        self._sync_moves()

    def _sync_moves(self) -> None:
        if self.move_buttons is None:
            return
        earlier, later = self.move_buttons
        row = self.selected_row() if self.category == db.CATEGORY_GALLERY else None
        entries = self.gallery_entries()
        note = ""
        states = ["disabled", "disabled"]
        searching = bool(self.search_text().strip())                # type: ignore[attr-defined]
        if row is not None and row.entry is not None and not searching:
            names = [e.name for e in entries]
            at = names.index(row.entry.name) if row.entry.name in names else -1
            for side, step in ((0, -1), (1, 1)):
                other = at + step
                if at < 0 or not 0 <= other < len(entries):
                    continue
                if entries[other].place is not None and row.entry.place is not None \
                        and entries[other].place[0] != row.entry.place[0]:
                    note = ACROSS_FILES
                    continue
                if row.entry.editable and entries[other].editable:
                    states[side] = "normal"
        earlier.configure(state=states[0])
        later.configure(state=states[1])
        self.move_note.configure(text=note)
        if note and not self.move_note.winfo_ismapped():
            self.move_note.pack(anchor="w", pady=(self._px(4), 0), before=self.preview_button)
        elif not note and self.move_note.winfo_ismapped():
            self.move_note.pack_forget()

    def _focus_gallery_form(self) -> None:
        self._focus_form()                                          # type: ignore[attr-defined]

    # --- Writes -----------------------------------------------------------------------------

    def _now_gallery(self, entry: db.Entry) -> dec.Decl | None:
        decl = self._fresh(entry)
        if decl is None or decl.values is None:
            show_error(self.root, STALE)
            self.refresh()
            return None
        return decl

    def add_to_gallery(self, names: Sequence[str]) -> bool:
        """Add pictures ``names`` at the end of the gallery, one plan each (one undo step
        per picture)."""
        done = False
        last = None
        for name in names:
            self.texts = self._read_texts()
            title = dec.gallery_title(name)
            plan = declplan.plan_new(dec.GALLERY, name, {"title": title, "versions": ()},
                                     self.texts)
            if self.category != db.CATEGORY_GALLERY:
                self.select_category(db.CATEGORY_GALLERY)
            last = GALLERY_PREFIX + name
            if not self._write(plan, select=last):
                return done
            done = True
        return done

    def _free_pictures(self, keep: str | None = None) -> list[tuple[str, str]]:
        """Pictures not in the gallery yet (as entry or version), for the pickers."""
        taken = db.gallery_pictures(dec.scan(self._read_texts()))
        return [(name, self._picture_label(name)) for name in self.picture_names()
                if name not in taken or name == keep]

    def add_gallery_pictures(self) -> bool:
        """+ Add pictures…: tick pictures in the picker; they join the end of the gallery."""
        self.texts = self._read_texts()
        picked = pick_pictures(self.root, self._free_pictures(), self.picture_thumb)
        if not picked:
            return False
        return self.add_to_gallery(picked)

    def add_version(self, entry: db.Entry) -> bool:
        """+ Add a version…: one picture from the picker joins the entry's tile."""
        decl = self._now_gallery(entry)
        if decl is None:
            return False
        picked = pick_pictures(self.root, self._free_pictures(), self.picture_thumb,
                               multi=False, title=PICK_VERSION_TITLE, hint=PICK_VERSION_HINT)
        if not picked:
            return False
        versions = (*decl.values["versions"], picked[0])            # type: ignore[index, misc]
        return self._write(declplan.plan_edit(decl, {**decl.values, "versions": versions},
                                              self.texts), select=GALLERY_PREFIX + decl.name)

    def _refuse_used(self, shown: str, places: list[tuple[str, int]]) -> bool:
        """The refusal while ``places`` (lock/unlock gallery lines) name a picture; True when
        refused."""
        if not places:
            return False
        text = USED_REFUSED.format(name=shown, lines=lines_word(len(places)))
        if ask(self.root, text, REFUSED_BUTTONS, escape=1, default=1) == 0:
            self.show_lines(shown, list(places))
        return True

    def remove_version(self, entry: db.Entry, version: str) -> bool:
        decl = self._now_gallery(entry)
        if decl is None:
            return False
        if self._refuse_used(version, self._lock_places((version,))):
            return False
        versions = tuple(v for v in decl.values["versions"] if v != version)  # type: ignore[union-attr]
        return self._write(declplan.plan_edit(decl, {**decl.values, "versions": versions},
                                              self.texts), select=GALLERY_PREFIX + decl.name)

    def remove_from_gallery(self, entry: db.Entry | None = None, *, confirm: bool = True
                            ) -> bool:
        """Remove from gallery (and the Pictures switch off, without the question): refused
        while a lock/unlock gallery line names one of its pictures."""
        if entry is None:
            row = self.selected_row()
            entry = row.entry if row is not None else None
            if entry is None or entry.kind != dec.GALLERY:
                return False
        if self._refuse_used(entry.shown, self._lock_places(self._pictures_of(entry))):
            return False
        decl = self._fresh(entry)
        if decl is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        if confirm and ask(self.root, REMOVE_ASK.format(title=entry.shown, ref=decl.ref),
                           REMOVE_BUTTONS, escape=1, default=1) != 0:
            return False
        if self.category == db.CATEGORY_GALLERY:
            self.chosen[db.CATEGORY_GALLERY] = None
        return self._write(declplan.plan_delete(decl, self.texts))

    def move_gallery(self, step: int) -> bool:
        """◀ Move earlier (-1) / Move later ▶ (+1): swap the selected entry's lines with its
        neighbour's (``declplan.plan_move``)."""
        row = self.selected_row()
        if row is None or row.entry is None or row.entry.kind != dec.GALLERY:
            return False
        entries = self.gallery_entries()
        names = [e.name for e in entries]
        at = names.index(row.entry.name)
        if not 0 <= at + step < len(entries):
            return False
        decl, other = self._fresh(row.entry), self._fresh(entries[at + step])
        if decl is None or other is None:
            show_error(self.root, STALE)
            self.refresh()
            return False
        return self._write(declplan.plan_move(decl, other, self.texts), select=row.iid)

    def preview_gallery(self) -> None:
        """▶ Preview the gallery: the game opens on Extras ▸ Gallery with every picture
        unlocked in memory (dev ``run --extras gallery``), through the Play bar."""
        play = getattr(self.win, "play_extras", None)
        if callable(play) and extras_ready():
            play(EXTRAS_PAGE)

    def show_lines(self, name: str, places: list[tuple[str | None, int | None]]) -> None:
        """The lines in the Problems panel, each a link to its line (Show uses)."""
        from engine.tools.editor.database import UseItem
        from engine.tools.editor.preview import Report
        items = []
        for ref, line in places:
            text = ""
            if ref is not None and line is not None:
                lines = self.texts.get(ref, "").split("\n")
                text = lines[line - 1].strip() if 0 < line <= len(lines) else ""
            where = f"{ref}:{line}" if ref is not None and line is not None else (ref or "")
            items.append(UseItem(f"{where}: {text}" if text else where, ref, line))
        head = USES_HEAD.format(name=name, lines=lines_word(len(places)))
        self.win.show_report(Report("editor", head, tuple(items)))   # type: ignore[arg-type]

    # --- The Gallery form -------------------------------------------------------------------

    def _gallery_key(self, entry: db.Entry, shape: tuple) -> tuple:
        values = entry.decl.values if entry.decl is not None else None
        shown = len(self._shown_places(entry)) if self._check_ran() else None
        return shape + (tuple((values or {}).get("versions") or ()), shown,  # type: ignore[arg-type]
                        bool(self._lock_places(self._pictures_of(entry))))

    def _gallery_form(self, row: Row, key: tuple) -> None:
        if self._read_only(row, key):
            return
        entry = row.entry
        assert entry is not None and entry.decl is not None and entry.decl.values is not None
        values = entry.decl.values
        body, form = self._new_body(key)
        title = self._title(body, entry.shown)
        grid = FormGrid(body, scale=self.scale)
        grid.frame.grid(row=1, column=0, sticky="ew")
        f = form.fields
        used = self._lock_places(self._pictures_of(entry))
        if used:
            grid.row(LABEL_PICTURE, ttk.Label(grid.frame, text=entry.name), hint=PICTURE_LOCKED)
        else:
            names = [n for n, _label in self._free_pictures(keep=entry.name)]
            f["picture"] = AssetPicker(grid.frame, names, entry.name, width=20,
                                       thumb=self.picture_thumb, scale=self.scale,
                                       on_change=lambda v: self._repicture(entry, v))
            grid.row(LABEL_PICTURE, f["picture"])
        f["title"] = TextField(grid.frame, str(values["title"]), width=28,
                               check=lambda t: 0 < len(t.strip()) <= dec.GALLERY_TITLE_MAX,
                               on_change=lambda v: self._edit(entry, {"title": str(v).strip()}))
        grid.row(LABEL_TITLE, f["title"])
        grid.caption(VERSIONS)
        versions = tuple(values.get("versions") or ())              # type: ignore[arg-type]
        f["versions"] = {}
        for version in versions:
            line = ttk.Frame(grid.frame)
            thumb = ttk.Label(line)
            image = self.picture_thumb(version)
            thumb.configure(image=image or "", text="" if image else "…")
            thumb.image = image                                     # type: ignore[attr-defined]
            thumb.pack(side="left")
            ttk.Label(line, text=version).pack(side="left", padx=(self._px(8), 0))
            remove = ttk.Button(line, text=REMOVE, style="Secondary.TButton",
                                command=lambda v=version: self.remove_version(entry, v))
            remove.pack(side="left", padx=(self._px(12), 0))
            f["versions"][version] = remove
            grid.widget(line, pady=(2, 2))
        if not versions:
            grid.widget(ttk.Label(grid.frame, text=NO_VERSIONS, style="Hint.TLabel",
                                  justify="left"), pady=(0, 4))
        full = len(versions) >= dec.GALLERY_VERSIONS_MAX
        f["add_version"] = ttk.Button(grid.frame, text=ADD_VERSION, style="Secondary.TButton",
                                      command=lambda: self.add_version(entry),
                                      state="disabled" if full else "normal")
        grid.widget(f["add_version"], pady=(4, 4))
        if full:
            grid.widget(ttk.Label(grid.frame, text=VERSIONS_FULL.format(
                n=dec.GALLERY_VERSIONS_MAX), style="Hint.TLabel"), pady=(0, 4))
        shown = self._shown_places(entry)
        never = self._check_ran() and not shown and not self._lock_places(
            [p for p in self._pictures_of(entry)])
        f["info"] = ttk.Label(grid.frame, text=NEVER_SHOWN if never else INFO,
                              style="Hint.TLabel", justify="left")
        grid.widget(f["info"], pady=(12, 2))
        if never:
            f["info"].configure(text="⚠ " + NEVER_SHOWN)
        uses = ttk.Frame(grid.frame)
        text = (SHOWN_IN.format(lines=lines_word(len(shown))) if shown else NOT_SHOWN) \
            if self._check_ran() else NOT_CHECKED
        ttk.Label(uses, text=text).pack(side="left")
        if shown:
            ttk.Button(uses, text=db.SHOW_USES, style="Link.Ghost.TButton", cursor="hand2",
                       command=lambda: self.show_lines(entry.shown, shown)).pack(
                side="left", padx=(self._px(8), 0))
        if not never:                       # the warning above says it already
            grid.widget(uses, pady=(2, 0))
        bottom = ttk.Frame(body)
        bottom.grid(row=2, column=0, sticky="ew", pady=(self._px(20), 0))
        ttk.Button(bottom, text=REMOVE_FROM, style="Secondary.TButton",
                   command=lambda: self.remove_from_gallery(entry)).pack(side="right")

        def update(new: Row) -> None:
            nonlocal entry
            entry = new.entry
            assert entry is not None and entry.decl is not None and entry.decl.values
            title.configure(text=entry.shown)
            f["title"].set(str(entry.decl.values["title"]))
            if "picture" in f:
                f["picture"].set(entry.name)

        form.update = update
        self._sync_moves()

    def _repicture(self, entry: db.Entry, name: object) -> bool:
        """The Picture field: the entry shows another picture (kept in its place)."""
        if not isinstance(name, str) or name == entry.name:
            return True
        decl = self._now_gallery(entry)
        if decl is None:
            return False
        return self._write(declplan.plan_edit(decl, decl.values, self.texts, name=name),
                           select=GALLERY_PREFIX + name)

    # --- The Pictures form's switch ---------------------------------------------------------

    def gallery_state(self, picture: str) -> tuple[str, db.Entry | None]:
        """``("off", None)``, ``("on", entry)`` or ``("version", its entry)``."""
        for entry in self.gallery_entries():
            if entry.name == picture:
                return "on", entry
            if picture in self._pictures_of(entry):
                return "version", entry
        return "off", None

    def _picture_gallery_shape(self, picture: str) -> tuple:
        state, entry = self.gallery_state(picture)
        return (state, entry.name if entry else None, entry.shown if entry else None,
                entry.editable if entry else None)

    def _picture_gallery_rows(self, grid: FormGrid, form: Any, picture: str) -> None:
        """Under a picture's thumbnail: **In the gallery** and **Gallery title**, or "Part
        of “…”" with Go to for a version."""
        state, entry = self.gallery_state(picture)
        f = form.fields
        if state == "version" and entry is not None:
            line = ttk.Frame(grid.frame)
            ttk.Label(line, text=PART_OF.format(title=entry.shown)).pack(side="left")
            f["gallery_go"] = ttk.Button(line, text=GO_TO, style="Link.Ghost.TButton",
                                         cursor="hand2",
                                         command=lambda: self.show_in_gallery(entry.name))
            f["gallery_go"].pack(side="left", padx=(self._px(8), 0))
            grid.widget(line, pady=(10, 2))
            return
        on = state == "on"
        f["gallery"] = ToggleField(grid.frame, "", on,
                                   on_change=lambda v: self._gallery_switch(picture, bool(v)))
        grid.row(IN_GALLERY, f["gallery"], hint=SWITCH_HINT)
        if on and entry is not None:
            if entry.editable and entry.decl is not None and entry.decl.values is not None:
                f["gallery_title"] = TextField(
                    grid.frame, str(entry.decl.values["title"]), width=26,
                    check=lambda t: 0 < len(t.strip()) <= dec.GALLERY_TITLE_MAX,
                    on_change=lambda v: self._edit(entry, {"title": str(v).strip()}))
                grid.row(GALLERY_TITLE, f["gallery_title"])
            else:
                f["gallery"].enable(False)
                grid.row(GALLERY_TITLE, ttk.Label(grid.frame, text=entry.shown))

    def _gallery_switch(self, picture: str, on: bool) -> bool:
        state, entry = self.gallery_state(picture)
        select = self.chosen.get(self.category)
        if on and state == "off":
            self.texts = self._read_texts()
            plan = declplan.plan_new(dec.GALLERY, picture,
                                     {"title": dec.gallery_title(picture), "versions": ()},
                                     self.texts)
            return self._write(plan, select=select)
        if not on and state == "on" and entry is not None:
            if not self.remove_from_gallery(entry, confirm=False):
                field = self.form.fields.get("gallery") if self.form is not None else None
                if field is not None:
                    field.set(True)                       # refused: the switch stays on
                self.refresh(select=select)
                return False
            return True
        return True

    def show_in_gallery(self, picture: str) -> None:
        """Go to: Database ▸ Gallery with ``picture``'s entry selected."""
        self.chosen[db.CATEGORY_GALLERY] = GALLERY_PREFIX + picture
        self.select_category(db.CATEGORY_GALLERY)


__all__ = ["ABOUT_GALLERY", "ADD_PICTURES", "ADD_VERSION", "EMPTY_HINT", "GALLERY_PREFIX",
           "GalleryCategory", "INFO", "MOVE_EARLIER", "MOVE_LATER", "NEVER_SHOWN", "PREVIEW",
           "PREVIEW_NOT_YET", "PREVIEW_TIP", "PicturePicker", "extras_ready", "pick_pictures"]
