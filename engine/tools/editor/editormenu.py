"""The script editor's right-click menu and Ctrl+click (2026-11-04), as the ``EditorMenu``
mixin of ``window.EditorWindow``.

Why this module exists: right-clicking a name in a script and choosing "Go to scene market"
(VS Code's Go to definition, in the author's words) beats searching the files for it. The
menu also holds Cut, Copy, Paste and Select all, which a right-click is expected to offer.

- ``editor_context(event)``: Button-3 moves the cursor to the click (unless it lands in the
  selection), then posts the menu; Shift+F10 and the Menu key post it at the cursor.
- ``editor_menu(widget)``: builds the menu for the cursor in ``widget``. The first entry is
  ``gotodef.target_at``'s text, or a dimmed "Go to definition" when the cursor names
  nothing Studio can find.
- ``go_to_definition(widget)``, and Ctrl+click: a line opens in the editor (``jump_to``); a
  picture or sound opens in the File preview (``show_asset``).

Names come from the last check's index (``check_names``), so a name typed since the last
check is found after the next one.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Final

from engine.tools.editor import gotodef
from engine.tools.editor.views import menu_command, set_entry_enabled

CONTEXT_MENUS_POST = True               # tests set False: tk_popup would wait for a click
CUT: Final = "Cut"
COPY: Final = "Copy"
PASTE: Final = "Paste"
SELECT_ALL: Final = "Select all"


class EditorMenu:
    """Go to definition and the editor's context menu (module docstring)."""

    root: tk.Tk
    mod: str
    last_editor_menu: tk.Menu | None = None     # tests read it

    # --- What the cursor names --------------------------------------------------------------

    def _image_refs(self) -> dict[str, str]:
        from engine.tools.editor import files
        project = getattr(self, "project", None)
        refs = project.file_refs("images") if project is not None else []
        out: dict[str, str] = {}
        for ref in refs:
            name = files.image_name_of(ref)
            if name is not None:
                out.setdefault(" ".join(name.split()).casefold(), ref)
        return out

    def _widget_ref(self, widget: tk.Misc) -> str | None:
        """The file shown in ``widget``: an open file's text, or the side editor's peer."""
        for ref, record in self.files.items():               # type: ignore[attr-defined]
            if record.widget is widget:
                return ref
        current = self.current                               # type: ignore[attr-defined]
        if widget is getattr(self, "side_text", None) and current is not None:
            return current.ref
        return None

    def definition_at(self, widget: tk.Text, index: str = "insert") -> gotodef.Target | None:
        """The ``Target`` for the text at ``index`` in ``widget``, or None."""
        line_no, column = (int(part) for part in widget.index(index).split("."))
        line = widget.get(f"{line_no}.0", f"{line_no}.end")
        ref = self._widget_ref(widget)
        return gotodef.target_at(line, column, self.check_names or {},  # type: ignore[attr-defined]
                                 self._image_refs(),
                                 here=(ref, line_no) if ref is not None else None)

    def go_to_definition(self, widget: tk.Text, index: str = "insert") -> bool:
        """Open where the name at ``index`` is made; False when nothing was found."""
        target = self.definition_at(widget, index)
        if target is None:
            return False
        self.open_target(target)
        return True

    def open_target(self, target: gotodef.Target) -> None:
        if target.line is None:
            self.show_asset(target.ref)                       # type: ignore[attr-defined]
        else:
            self.jump_to(target.ref, target.line)             # type: ignore[attr-defined]

    # --- The menu --------------------------------------------------------------------------

    def editor_menu(self, widget: tk.Text) -> tk.Menu:
        menu = self.last_editor_menu
        if menu is None:
            menu = self.last_editor_menu = tk.Menu(self.root, tearoff=0)
        menu.delete(0, "end")
        target = self.definition_at(widget)
        label = target.text if target is not None else gotodef.NOTHING
        menu.add_command(label=label, accelerator=f"{self._key_word()}+Click",
                         command=menu_command(menu, label, lambda: target is not None
                                              and self.open_target(target)))
        set_entry_enabled(menu, label, target is not None)
        menu.add_separator()
        editable = str(widget.cget("state")) != "disabled"
        selected = bool(widget.tag_ranges("sel"))
        key = self._key_word()
        for label, letter, virtual, on in ((CUT, "X", "<<Cut>>", editable and selected),
                                           (COPY, "C", "<<Copy>>", selected),
                                           (PASTE, "V", "<<Paste>>", editable)):
            menu.add_command(label=label, accelerator=f"{key}+{letter}",
                             command=menu_command(menu, label, lambda v=virtual:
                                                  widget.event_generate(v)))
            set_entry_enabled(menu, label, on)
        menu.add_separator()
        menu.add_command(label=SELECT_ALL, accelerator=f"{key}+A", command=menu_command(
            menu, SELECT_ALL, lambda: self._select_all(widget)))   # type: ignore[attr-defined]
        return menu

    def _key_word(self) -> str:
        return "Cmd" if self.mod == "Command" else "Ctrl"

    def editor_context(self, event: tk.Event) -> str:
        """Button-3 at the click (the cursor moves there unless the click is in the
        selection); Shift+F10 or the Menu key at the cursor."""
        widget: Any = event.widget
        if event.type == tk.EventType.ButtonPress:
            at = widget.index(f"@{event.x},{event.y}")
            inside = widget.tag_ranges("sel") and widget.compare(
                "sel.first", "<=", at) and widget.compare(at, "<", "sel.last")
            if not inside:
                widget.tag_remove("sel", "1.0", "end")
                widget.mark_set("insert", at)
            x, y = event.x_root, event.y_root
        else:
            box = widget.bbox("insert") or (0, 0, 0, 0)
            x = widget.winfo_rootx() + box[0]
            y = widget.winfo_rooty() + box[1] + box[3]
        widget.focus_set()
        menu = self.editor_menu(widget)
        if CONTEXT_MENUS_POST:
            try:
                menu.tk.call("tk_popup", menu, x, y)
            finally:
                menu.grab_release()
        return "break"

    def editor_click_definition(self, event: tk.Event) -> str | None:
        """Ctrl+click: go to what the clicked name names (else Tk's own click)."""
        widget: Any = event.widget
        at = widget.index(f"@{event.x},{event.y}")
        if self.go_to_definition(widget, at):
            return "break"
        return None


__all__ = ["CONTEXT_MENUS_POST", "COPY", "CUT", "EditorMenu", "PASTE", "SELECT_ALL"]
