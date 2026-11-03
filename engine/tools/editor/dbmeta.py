"""The Database's **Character files** category (F47 ``01-design.md`` §4.3: "Files the story
can write into the meta folder; + Add…; preview text"; F31 meta files).

Why this module exists: a story's **Meta file** events (``file write "hana.chr"``) copy an
original from ``<game>/files/`` into the folder players can see. A non-programmer never
opens Explorer for that: Database ▸ **Character files** lists the originals (name, size;
the ``.chr`` or ``.txt`` ending is the kind), **+ Add…** copies files in through F45's Add
files… checks with F31's name rules (``win.add_files`` into ``files/``), the form shows the
kind, the size, a text preview, "Used in N lines" (the check's ``meta_file_use`` rows: every
``file`` line naming it) with **Show uses**, and Delete, refused while a line uses the name.

``MetaFilesCategory`` is a mixin of ``database.DatabasePane`` (as ``dbextras``'s). The meta
folder's own name is never spelled here: it comes from ``engine.core.constants``
(``tests/core/test_paths_meta.py``). Imports the standard library, ``tkinter`` and its own
package; never pygame.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any

from engine.core.constants import META_ORIGINAL_MAX_BYTES, META_ORIGINALS_DIR, META_SHOWN
from engine.core.errors import EngineError, UserFacingError
from engine.script.assetgroups import ASSET_GROUPS
from engine.script.messages import show
from engine.tools.editor import dbmodel as db
from engine.tools.editor import files
from engine.tools.editor.dbmore import Row
from engine.tools.editor.fieldwidgets import FormGrid, fit_wrap
from engine.tools.editor.theme import ROLES, THEME

# --- Texts (design §4.3; the rest in the same voice) ------------------------------------------

ABOUT_META = ("Character files are files your story can put in the game's "
              f"{META_SHOWN} folder for players to find, with a Meta file event. "
              "Click + Add… to bring one in.")
EMPTY_HINT = "Add the files your story can put where players find them."
ADD = "+ Add…"
NEW = "+ New"
LABEL_KIND = "Kind"
LABEL_SIZE = "Size"
LABEL_FILE = "File"
KINDS = {".chr": "Character file (.chr)", ".txt": "Text file (.txt)"}
IN_SCRIPT = 'In the script: file write "{name}"'
COPIES = f"A Meta file event copies it into {META_SHOWN} while the game runs."
BAD_NAME = "The story can't use this file: {why}. Rename it in the project panel."
PREVIEW = "Preview"
NOT_TEXT = "This file isn't plain text, so there's no preview. The game copies it as it is."
UNREADABLE = "Studio can't read this file right now."
MORE = "…"
PREVIEW_CHARS = 4000            # the preview shows at most this much of the text
PREVIEW_LINES = 12
ROW_PREFIX = "o:"
# The project group that holds the originals (F31: ``files/``).
META_GROUP = next(group.key for group in ASSET_GROUPS if group.kind == "meta")


def size_text(size: int) -> str:
    """"512 bytes", "1.2 KB", "3.4 MB"."""
    if size < 1024:
        return "1 byte" if size == 1 else f"{size} bytes"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def preview_text(data: bytes) -> str | None:
    """The text a preview shows (at most ``PREVIEW_CHARS``), or None when ``data`` isn't
    plain text (a NUL byte, or not UTF-8)."""
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    text = text.replace("\r\n", "\n")
    return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + MORE


class MetaFilesCategory:
    """Database ▸ Character files (a mixin of ``database.DatabasePane``)."""

    root: tk.Misc
    win: Any
    names: Any
    category: str
    rows: dict[str, list[Row]]
    chosen: dict[str, str | None]
    new_button: ttk.Button
    empty: Any
    fonts: Any

    def _meta_rows(self) -> list[Row]:
        rows = []
        for ref in self._project_refs(META_GROUP):                   # type: ignore[attr-defined]
            name = ref.rsplit("/", 1)[-1]
            try:
                size: int | None = self.win.paths.file_size(ref)
            except (EngineError, UserFacingError, OSError):
                size = None
            entry = db.Entry(db.META_FILE, name, name, None, False,
                             db.uses_of(self.names, db.META_FILE, name))
            rows.append(Row(f"{ROW_PREFIX}{name}", name,
                            size_text(size) if size is not None else "", entry, ref=ref))
        return sorted(rows, key=lambda r: r.text.casefold())

    def _meta_key(self, row: Row, shape: tuple) -> tuple:
        """The form's key: a changed size (a replaced file) builds the form again."""
        return (*shape, row.detail)

    def _meta_form(self, row: Row, key: tuple) -> None:
        entry = row.entry
        assert entry is not None and row.ref is not None
        px = self._px                                                  # type: ignore[attr-defined]
        body, _form = self._new_body(key)                              # type: ignore[attr-defined]
        self._title(body, row.text)                                    # type: ignore[attr-defined]
        grid = FormGrid(body, scale=self.scale)                        # type: ignore[attr-defined]
        grid.frame.grid(row=1, column=0, sticky="ew")
        suffix = "." + entry.name.rsplit(".", 1)[-1].lower() if "." in entry.name else ""
        grid.row(LABEL_KIND, ttk.Label(grid.frame, text=KINDS.get(suffix, suffix or "—")))
        grid.row(LABEL_SIZE, ttk.Label(grid.frame, text=row.detail or "—"))
        grid.row(LABEL_FILE, ttk.Label(grid.frame, text=show(row.ref)))
        problem = files.meta_problem(entry.name)
        if problem is not None:
            grid.widget(fit_wrap(ttk.Label(grid.frame, text=BAD_NAME.format(why=problem[0]),
                                           foreground=ROLES["warning"], justify="left"),
                                 px(360)), pady=(6, 2))
        else:
            grid.widget(ttk.Label(grid.frame, text=IN_SCRIPT.format(name=entry.name),
                                  style="Hint.TLabel"), pady=(6, 0))
            grid.widget(fit_wrap(ttk.Label(grid.frame, text=COPIES, style="Hint.TLabel",
                                           justify="left"), px(360)), pady=(0, 2))
        grid.widget(self._uses_line(grid.frame, entry), pady=(2, 0))   # type: ignore[attr-defined]
        box = ttk.Frame(body)
        box.grid(row=2, column=0, sticky="ew", pady=(px(16), 0))
        ttk.Label(box, text=PREVIEW, style="Caption.TLabel").pack(anchor="w")
        try:
            data = self.win.paths.read_file(row.ref, max_bytes=META_ORIGINAL_MAX_BYTES,
                                            regular=True)
            text = preview_text(data)
            note = None if text is not None else NOT_TEXT
        except (EngineError, UserFacingError, OSError):
            text, note = None, UNREADABLE
        if text is None:
            fit_wrap(ttk.Label(box, text=note, style="Hint.TLabel", justify="left"),
                     px(360)).pack(anchor="w", fill="x", pady=(px(4), 0))
            self.meta_preview: tk.Text | None = None
        else:
            preview = tk.Text(box, height=min(PREVIEW_LINES, max(3, text.count("\n") + 1)),
                              wrap="word", font=self.fonts["code"], relief="flat",
                              background=THEME["card.background"],
                              foreground=THEME["editor.foreground"], borderwidth=0,
                              highlightthickness=1, highlightbackground=THEME["border"],
                              padx=px(8), pady=px(6), takefocus=0)
            preview.insert("1.0", text)
            preview.configure(state="disabled")
            preview.pack(anchor="w", fill="x", pady=(px(4), 0))
            self.meta_preview = preview
        self._bottom(body, 3, entry,                                   # type: ignore[attr-defined]
                     lambda: self._delete_file(entry, row.ref))         # type: ignore[attr-defined]

    def add_meta_files(self) -> None:
        """+ Add…: files into ``files/`` (made when missing), F31's name rules applied."""
        self._add(META_GROUP, META_ORIGINALS_DIR)       # type: ignore[attr-defined]

    def _meta_after_fill(self, has_entries: bool) -> None:
        """After the list is filled: the + button's and the empty state's words."""
        if self.category != db.CATEGORY_META:
            return
        self.new_button.configure(text=ADD)
        if not has_entries:
            self.empty.hint.configure(text=EMPTY_HINT)
            if self.empty.button is not None:
                self.empty.button.configure(text=ADD)


__all__ = ["ABOUT_META", "ADD", "MetaFilesCategory", "NOT_TEXT", "preview_text", "size_text"]
