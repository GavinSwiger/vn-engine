"""The Database's **Clean up** category (F41 ``01-design.md`` §4.4, §6.1, §6.2;
``04-technical.md`` §7.5; W2; AC-F41-17, 18, 19, 21, 22).

Why this module exists: a game in progress collects scenes nothing leads to and pictures,
sounds, characters and variables the story never uses. Each check's linter finds them
(``tools/lint.py``, sent as names rows, never as Problems), and ``cleanup.cleanup_view``
turns one run's result into groups and rows. This mixin of ``database.DatabasePane`` shows
them as the last Database category, **Clean up**, with its count: a header line, the groups
(Scenes not reached, Characters, Pictures, Sounds, Variables, Other), each row the name and
its place. Selecting a row shows its kind, where it is, a picture or ▶ preview, the warning
text, and two actions:

- **Open in {category}** selects the entry in its own category (a scene: **Show on map**,
  the story map with its box focused; a plain ``define``: **Open in Editor** at its line);
- **Delete…** runs that category's own Delete with its own question (a file: to the
  Recycle Bin on Windows, ``files.delete_file``; a line: removed as one undo step; a scene:
  F46's Delete scene on the map). It is offered only where the category offers Delete.

A deleted row hides until the next check result, which lists what is left. The states
(not checked yet, story with errors, nothing to clean up) have their own empty states,
each with the one button that helps (Check now, Show Problems). Imports the standard
library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any

from engine.script.messages import show
from engine.tools.editor import cleanup as cu
from engine.tools.editor import dbmodel as db
from engine.tools.editor import declarations as dec
from engine.tools.editor.dbmore import Row
from engine.tools.editor.fieldwidgets import FormGrid, fit_wrap
from engine.tools.editor.views import EmptyState

# --- Texts (design §6.2; the rest in the same voice) -------------------------------------------

ABOUT_CLEANUP = ("Clean up lists the scenes nothing leads to and the things your story never "
                 "uses, found each time the game is checked.")
NOT_CHECKED_HINT = "Check the game to see the scenes and things your story doesn't use."
CHECK_NOW = "Check now"
SHOW_PROBLEMS = "Show Problems"
LABEL_KIND = "Kind"
LABEL_WHERE = "Where"
WHERE_LINE = "{file}, line {line}"
GROUP_HINT = "Pick one to see where it is and what you can do with it."
DELETE_HINTS = {            # what Delete… does, said before it is pressed
    "file": "Delete… asks first, then removes the file from the game folder.",
    "line": "Delete… asks first, then removes its line. Edit ▸ Undo brings it back.",
    "scene": "Delete… asks first, then removes the scene. Edit ▸ Undo brings it back.",
}
NO_ENTRY = "It isn't in {category} any more. The next check updates this list."

ROW_GROUP = "g:cleanup:"
FILE_KINDS = (db.BACKGROUND, db.SOUND, db.META_FILE)


def _split(text: str) -> tuple[str, str]:
    """A final text as an empty state's title and hint: its first sentence, then the rest."""
    head, _dot, rest = text.partition(". ")
    return (head + "." if rest else head), rest


class CleanupCategory:
    """Database ▸ Clean up (a mixin of ``database.DatabasePane``)."""

    root: tk.Misc
    win: Any
    category: str
    rows: dict[str, list[Row]]
    chosen: dict[str, str | None]
    decls: tuple[dec.Decl, ...]
    list_frame: ttk.Frame
    list_body: ttk.Frame
    empty: Any
    fonts: Any
    scale: float

    def _cleanup_init(self) -> None:
        self.cleanup: cu.CleanupView = cu.cleanup_view(None)
        self.cleanup_items: dict[str, cu.CleanupItem] = {}
        self.cleanup_count: int | None = None
        self.cleanup_hidden: set[str] = set()
        self._cleanup_for: Any = None

    # --- Rows -----------------------------------------------------------------------------

    def _cleanup_rows(self) -> list[Row]:
        """The groups and rows of the newest check (after every other category's rows,
        which the targets are found in). Rows deleted here stay hidden until a new result."""
        result = self.win.check_result
        if result is not self._cleanup_for:
            self._cleanup_for = result
            self.cleanup_hidden = set()
        hidden = self.cleanup_hidden
        view = cu.cleanup_view(result)
        self.cleanup = view
        self.cleanup_items = {}
        rows: list[Row] = []
        count = 0
        for group in view.groups:
            items = [item for item in group.items if item.iid not in hidden]
            total = group.count - (len(group.items) - len(items))
            if total <= 0:
                continue
            count += total
            gid = ROW_GROUP + group.key
            rows.append(Row(gid, group.heading, str(total), group=group.key,
                            title=group.heading))
            for item in items:
                self.cleanup_items[item.iid] = item
                target = self.cleanup_target(item)
                place = (item.file, item.line) if item.file and item.line else None
                entry = db.Entry(item.kind, item.name, item.name, place, False, 0)
                rows.append(Row(item.iid, item.name, item.place, entry, gid,
                                ref=target.ref if target is not None else None))
        self.cleanup_count = count if view.state in (cu.STATE_LIST, cu.STATE_EMPTY) else None
        return rows

    def cleanup_target(self, item: cu.CleanupItem) -> Row | None:
        """The row ``item`` is in its own category (by name), or a plain define's own row
        (made here: defines have no category); None for a scene or when it is gone."""
        if item.kind == "unused_define":
            decl = next((d for d in self.decls if d.kind == dec.DEFINE
                         and d.name == item.name), None)
            if decl is None:
                return None
            return Row(item.iid, item.name, "", db.Entry(
                dec.DEFINE, decl.name, decl.name, (decl.ref, decl.first), True, 0, decl))
        if item.target != cu.TO_CATEGORY or item.category is None:
            return None
        return cu.target_entry(item, [r for r in self.rows.get(item.category, ())
                                      if r.entry is not None])

    def _cleanup_choice_title(self, title: str) -> str:
        """The narrow window's drop-down shows Clean up with its count (UI-F41-02)."""
        count = self.cleanup_count
        return f"{title} ({count})" if count else title

    # --- Form -----------------------------------------------------------------------------

    def _cleanup_key(self, row: Row) -> tuple:
        if row.entry is None:
            members = tuple(r.iid for r in self.rows[db.CATEGORY_CLEANUP]
                            if r.parent == row.iid)
            return (db.CATEGORY_CLEANUP, row.iid, "group", row.detail, members)
        item = self.cleanup_items.get(row.iid)
        target = self.cleanup_target(item) if item is not None else None
        return (db.CATEGORY_CLEANUP, row.iid, "item", row.ref, target is not None,
                target is not None and self.can_delete(target))

    def _cleanup_form(self, row: Row, key: tuple) -> None:
        px = self._px                                                  # type: ignore[attr-defined]
        body, form = self._new_body(key)                               # type: ignore[attr-defined]
        if row.entry is None:
            self._title(body, row.title.capitalize())                  # type: ignore[attr-defined]
            names = [r.text for r in self.rows[db.CATEGORY_CLEANUP] if r.parent == row.iid]
            ttk.Label(body, text="\n".join(names), justify="left").grid(
                row=1, column=0, sticky="w")
            ttk.Label(body, text=GROUP_HINT, style="Hint.TLabel").grid(
                row=2, column=0, sticky="w", pady=(px(12), 0))
            return
        item = self.cleanup_items[row.iid]
        target = self.cleanup_target(item)
        self._title(body, item.name)                                   # type: ignore[attr-defined]
        grid = FormGrid(body, scale=self.scale)
        grid.frame.grid(row=1, column=0, sticky="ew")
        grid.row(LABEL_KIND, ttk.Label(grid.frame, text=item.kind_line))
        if item.file:
            where = show(item.file) if item.line is None else WHERE_LINE.format(
                file=show(item.file), line=item.line)
            grid.row(LABEL_WHERE, ttk.Label(grid.frame, text=where))
        if row.ref is not None and item.kind == "unused_picture":
            picture = ttk.Label(grid.frame, style="TLabel")
            grid.widget(picture, pady=(8, 8))
            self._preview_ref = row.ref

            def update(_new: Row) -> None:
                image = self.previews.get(row.ref) if row.ref else None  # type: ignore[attr-defined]
                picture.configure(image=image or "", text="" if image else "…")
                picture.image = image                                   # type: ignore[attr-defined]

            form.update = update
            update(row)
        elif row.ref is not None and item.kind == "unused_sound":
            from engine.tools.editor.database import PLAY_BUTTON
            play = ttk.Frame(grid.frame)
            self.play_button = ttk.Button(play, text=PLAY_BUTTON, style="Secondary.TButton",
                                          command=lambda: self.toggle_sound(  # type: ignore[attr-defined]
                                              row.ref or ""))
            self.play_button.pack(side="left")
            self.sound_label = ttk.Label(play, text="", style="Detail.TLabel")
            self.sound_label.pack(side="left", padx=(px(12), 0))
            grid.widget(play, pady=(8, 4))
            form.update = lambda _new: self._sync_play_buttons()        # type: ignore[attr-defined]
            self._sync_play_buttons()                                   # type: ignore[attr-defined]
        grid.widget(fit_wrap(ttk.Label(grid.frame, text=item.text, justify="left"), px(360)),
                    pady=(6, 2))
        line = ttk.Frame(body)
        line.grid(row=2, column=0, sticky="ew", pady=(px(20), 0))
        first = item.actions[0]
        opens = item.target != cu.TO_CATEGORY or target is not None
        self.cleanup_open_button = ttk.Button(
            line, text=first.text, style="Secondary.TButton",
            command=lambda: self.cleanup_open(item))
        self.cleanup_open_button.pack(side="left")
        if not opens:
            self.cleanup_open_button.state(["disabled"])
        deletes = item.target == cu.TO_MAP or (target is not None and self.can_delete(target))
        self.cleanup_delete_button: ttk.Button | None = None
        if deletes:
            self.cleanup_delete_button = ttk.Button(
                line, text=cu.DELETE, style="Secondary.TButton",
                command=lambda: self.cleanup_delete(item))
            self.cleanup_delete_button.pack(side="right")
        if item.target == cu.TO_CATEGORY and target is None:
            hint = NO_ENTRY.format(category=db.CATEGORY_TITLES[item.category or ""])
        elif not deletes:
            hint = ""
        elif item.target == cu.TO_MAP:
            hint = DELETE_HINTS["scene"]
        else:
            assert target is not None and target.entry is not None
            hint = DELETE_HINTS["file" if target.entry.kind in FILE_KINDS else "line"]
        if hint:
            fit_wrap(ttk.Label(body, text=hint, style="Hint.TLabel", justify="left"),
                     px(360)).grid(row=3, column=0, sticky="ew", pady=(px(8), 0))

    # --- Actions --------------------------------------------------------------------------

    def can_delete(self, row: Row) -> bool:
        """Whether ``row``'s category offers Delete for it (``delete_row`` would act)."""
        entry = row.entry
        if entry is None:
            return False
        if entry.kind in FILE_KINDS:
            return row.ref is not None
        if entry.kind == dec.POSITION:
            return bool(entry.values) and not (entry.values or {}).get("builtin")
        if entry.kind in (dec.GALLERY, dec.TRACK, dec.REPLAY, dec.ACHIEVEMENT):
            return True
        return entry.editable

    def cleanup_open(self, item: cu.CleanupItem) -> None:
        """Open in {category} (the entry selected there), Show on map, or Open in Editor."""
        if item.target == cu.TO_MAP:
            self.win.show_scene_on_map(item.name)
            return
        if item.target == cu.TO_EDITOR:
            if item.file is not None:
                self.win.jump_to(item.file, item.line or 1)
            return
        target = self.cleanup_target(item)
        if target is None or item.category is None:
            return
        self.select_category(item.category)                            # type: ignore[attr-defined]
        self.select(target.iid)                                        # type: ignore[attr-defined]

    def cleanup_delete(self, item: cu.CleanupItem) -> None:
        """Delete…: the category's own Delete and question (a scene: F46's Delete scene on
        the map). The row hides when the thing is gone, until the next check."""
        if item.target == cu.TO_MAP:
            if self.win.show_scene_on_map(item.name) and self.win.delete_scene() is not None:
                self._cleanup_hide(item)
            return
        target = self.cleanup_target(item)
        if target is None or not self.can_delete(target):
            return
        self.delete_row(target, item.category or db.CATEGORY_CLEANUP)  # type: ignore[attr-defined]
        if self.cleanup_target(item) is None:
            self._cleanup_hide(item)

    def _cleanup_hide(self, item: cu.CleanupItem) -> None:
        self.cleanup_hidden.add(item.iid)
        if self.chosen.get(db.CATEGORY_CLEANUP) == item.iid:
            self.chosen[db.CATEGORY_CLEANUP] = None
        self.refresh()                                                 # type: ignore[attr-defined]

    def cleanup_delete_selected(self) -> None:
        """The Delete key on a Clean up row."""
        row = self.selected_row()                                      # type: ignore[attr-defined]
        item = self.cleanup_items.get(row.iid) if row is not None else None
        if item is not None:
            self.cleanup_delete(item)

    # --- After the list is filled ---------------------------------------------------------

    def _cleanup_empty(self, state: str) -> EmptyState:
        empties: dict[str, EmptyState] = self.__dict__.setdefault("cleanup_empties", {})
        found = empties.get(state)
        if found is None:
            if state == cu.STATE_NOT_CHECKED:
                found = EmptyState(self.list_body, icon="info", title=cu.NOT_CHECKED,
                                   hint=NOT_CHECKED_HINT, button=CHECK_NOW,
                                   command=self.win.check_now, scale=self.scale)
            elif state == cu.STATE_ERRORS:
                title, hint = _split(cu.ERRORS)
                found = EmptyState(self.list_body, icon="error", title=title, hint=hint,
                                   button=SHOW_PROBLEMS, command=self.win.focus_problems,
                                   scale=self.scale)
            else:
                title, hint = _split(cu.EMPTY)
                found = EmptyState(self.list_body, icon="success", title=title, hint=hint,
                                   scale=self.scale)
            px = self._px                                              # type: ignore[attr-defined]
            for label in (found.title, found.hint):
                label.configure(justify="center", wraplength=px(200))
            found.frame.bind("<Configure>", lambda e, f=found: [label.configure(
                wraplength=max(px(60), min(px(200), e.width - px(24))))
                for label in (f.title, f.hint)], add="+")
            empties[state] = found
        return found

    def _cleanup_head(self) -> ttk.Frame:
        head = getattr(self, "cleanup_head", None)
        if head is None:
            px = self._px                                              # type: ignore[attr-defined]
            head = self.cleanup_head = ttk.Frame(self.list_frame)
            self.cleanup_header = ttk.Label(head, text=cu.HEADER, style="Hint.TLabel",
                                            justify="left")
            self.cleanup_note = ttk.Label(head, text="", justify="left")
            head.bind("<Configure>", lambda e: [label.configure(
                wraplength=max(px(60), e.width)) for label in
                (self.cleanup_header, self.cleanup_note)], add="+")
        return head

    def _cleanup_after_fill(self, has_entries: bool) -> None:
        """The header and waiting lines above the list, and the state's empty state."""
        empties: dict[str, EmptyState] = self.__dict__.get("cleanup_empties", {})
        head = getattr(self, "cleanup_head", None)
        if self.category != db.CATEGORY_CLEANUP:
            for empty in empties.values():
                empty.hide()
            if head is not None:
                head.pack_forget()
            return
        view: cu.CleanupView = self.cleanup
        head = self._cleanup_head()
        px = self._px                                                  # type: ignore[attr-defined]
        note = "\n".join(line for line in (view.waiting, view.over_cap) if line)
        self.cleanup_note.configure(text=note)
        self.cleanup_header.pack_forget()
        self.cleanup_note.pack_forget()
        if has_entries:
            self.cleanup_header.pack(anchor="w", fill="x")
        if note:
            self.cleanup_note.pack(anchor="w", fill="x", pady=(px(4), 0))
        if has_entries or note:
            if not head.winfo_manager():
                head.pack(fill="x", padx=px(8), pady=(0, px(6)), before=self.list_body)
        else:
            head.pack_forget()
        self.empty.hide()
        state = view.state if not has_entries else cu.STATE_LIST
        if state == cu.STATE_LIST and not has_entries:
            state = cu.STATE_EMPTY                    # every row deleted since the check
        for key, empty in empties.items():
            if key != state:
                empty.hide()
        if state != cu.STATE_LIST:
            self._cleanup_empty(state).show(self.list_body)


__all__ = ["ABOUT_CLEANUP", "CHECK_NOW", "CleanupCategory", "SHOW_PROBLEMS"]
