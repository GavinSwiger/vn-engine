"""Studio's menus (F45 ``01`` §6.1): File, Edit, Insert, Story, View, Run, Help, built from
``menu_table`` as the ``StudioMenus`` mixin of ``window.EditorWindow``. A row is
``Item(label, accelerator, command)`` (``guarded``: through ``views.menu_command``, so a
disabled entry does nothing), ``Check(label, variable, command)``, or ``SEPARATOR``; Insert
and Story are built from the doc registry and ``story_actions``. View's tab rows come from
``window.TABS``. F47 adds Run and Help rows; F42 a File row after Save all.

macOS shows ``menubar`` as the native bar; elsewhere ``views.MenuBar`` posts the same menus
from a dark bar inside the window (``08`` D5).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass

from engine.tools.editor.assist import insert_menu
from engine.tools.editor.theme import MENU_BAR_PX
from engine.tools.editor.views import MenuBar, menu_command, set_entry_enabled
from engine.tools.editor.studiolook import FONT_STEP_PX
from engine.tools.editor.fileactions import ADD_BUTTON
from engine.tools.editor.playbar import PLAY_OPTIONS

SHOW_WARNINGS = "Show warnings"         # View menu toggle (PR-F45-12)
PLAY_MENU = "Play"                      # Run menu (F47 §6.1)
PLAY_SCENE_MENU = "Play this scene"
STOP_MENU = "Stop"


@dataclass(frozen=True)
class Item:
    """A menu entry. ``guarded``: its command goes through ``views.menu_command`` (it does
    nothing while the entry is off); ``file_op``: off while the game folder can't be found
    (AC-F45-26)."""

    label: str
    accelerator: str = ""
    command: Callable[[], object] | None = None
    guarded: bool = False
    file_op: bool = False


@dataclass(frozen=True)
class Check:
    """A check entry bound to a Tk variable."""

    label: str
    variable: tk.Variable
    command: Callable[[], object]


SEPARATOR = None
Row = Item | Check | None


class StudioMenus:
    """The menu bar from ``menu_table``, and the Story menu's enabled entries."""

    def menu_table(self) -> list[tuple[str, str, list[Row] | Callable[[tk.Menu], tk.Menu]]]:
        """``(cascade label, window attribute, rows)`` per menu, in bar order; ``rows`` is a
        builder for a menu made from a registry (Insert, Story)."""
        key = "Cmd" if self.mod == "Command" else "Ctrl"
        return [
            ("File", "file_menu", [
                Item("New game…", command=self.new_game),
                Item("New script file", f"{key}+N", lambda: self.new_script_file(),
                     guarded=True, file_op=True),
                Item(ADD_BUTTON, f"{key}+Shift+O", self.add_files, guarded=True,
                     file_op=True),
                Item("Rename", "F2", self.rename_selected, guarded=True, file_op=True),
                Item("Delete", "Delete", self.delete_selected, guarded=True, file_op=True),
                SEPARATOR,
                Item("Save", f"{key}+S", self.save_current),
                Item("Save all", f"{key}+Shift+S", self.save_all),
                SEPARATOR,
                Item("Close", command=self.on_close),
            ]),
            ("Edit", "edit_menu", [
                Item("Undo", f"{key}+Z", lambda: self._undo(self.text)),
                Item("Redo", f"{key}+Y", lambda: self._redo(self.text)),
                Item("Cut", f"{key}+X", lambda: self._clipboard(self.text, "<<Cut>>")),
                Item("Copy", f"{key}+C", lambda: self._clipboard(self.text, "<<Copy>>")),
                Item("Paste", f"{key}+V", lambda: self._clipboard(self.text, "<<Paste>>")),
                SEPARATOR,
                Item("Complete", f"{key}+Space", self.complete),
                Item("Go to label…", f"{key}+G", self.go_to_label),
            ]),
            ("Insert", "insert_menu", self._build_insert_menu),
            ("Story", "story_menu", self._build_story_menu),
            ("View", "view_menu", [
                *(Item(tab.title, f"{key}+{index + 1}", lambda i=index: self.show_tab(i))
                  for index, tab in enumerate(self.tabs)),
                SEPARATOR,
                Item("Zoom in", f"{key}+=", lambda: self.zoom_view(FONT_STEP_PX)),
                Item("Zoom out", f"{key}+-", lambda: self.zoom_view(-FONT_STEP_PX)),
                Item("Actual size", f"{key}+0", lambda: self.zoom_view(0)),
                SEPARATOR,
                Check(SHOW_WARNINGS, self.show_warnings, self.render_panel),
            ]),
            ("Run", "run_menu", [
                Item(PLAY_MENU, "Shift+F5", self.play_from_start),
                Item(PLAY_SCENE_MENU, "F5", self.play_scene),
                Item(STOP_MENU, f"{key}+F2", self.stop_game),
                Item(PLAY_OPTIONS, command=self.play_options),
                SEPARATOR,
                Item("Check now", "F7", self.check_now),
            ]),
            ("Help", "help_menu", [
                Item("Help for this line", command=self.focus_help),
            ]),
        ]

    def _build_menus(self) -> None:
        """F45 01 §6.1's menus from ``menu_table``: File, Edit, Insert (the doc registry's
        groups), Story, View, Run, Help. ``menubar`` holds them as cascades; macOS shows it
        as the native bar, elsewhere ``views.MenuBar`` posts the same menus from a dark bar
        in the window (``08`` D5)."""
        bar = tk.Menu(self.root, tearoff=0)
        file_ops: list[str] = []
        for label, attribute, rows in self.menu_table():
            if callable(rows):
                menu = rows(bar)
            else:
                menu = tk.Menu(bar, tearoff=0)
                for row in rows:
                    _add_row(menu, row)
                    if isinstance(row, Item) and row.file_op:
                        file_ops.append(row.label)
            setattr(self, attribute, menu)
            bar.add_cascade(label=label, menu=menu)
        self.file_ops = tuple(file_ops)
        self.menubar = bar
        if self.mod == "Command":
            self.root.configure(menu=bar)
            self.menu_bar = None
            return
        cascades = [(str(bar.entrycget(i, "label")), self.root.nametowidget(
            bar.entrycget(i, "menu"))) for i in range(bar.index("end") + 1)]
        font = self.ui_font
        self.menu_bar = MenuBar(self.root, cascades, font=font,
                                height=max(self._px(MENU_BAR_PX),
                                           font.metrics("linespace") + self._px(8)),
                                scale=self.scale)
        self.menu_bar.frame.pack(side="top", fill="x", before=self.play_bar.frame)

    def _build_insert_menu(self, bar: tk.Menu) -> tk.Menu:
        """Insert: one submenu per GROUPS entry with docs, built once from the registry."""
        menu = tk.Menu(bar, tearoff=0)
        self.insert_submenus: dict[str, tk.Menu] = {}
        for group, docs in insert_menu():
            sub = tk.Menu(menu, tearoff=0)
            for doc in docs:
                sub.add_command(label=doc.title, command=lambda d=doc: self.insert_doc(d))
            menu.add_cascade(label=group, menu=sub)
            self.insert_submenus[group] = sub
        return menu

    def _build_story_menu(self, bar: tk.Menu) -> tk.Menu:
        """F46 (design §6.1, 04 §6.11): one action table builds the Story menu and the
        map's and Events list's context menus; entries are enabled for their target."""
        key = "Cmd" if self.mod == "Command" else "Ctrl"
        menu = tk.Menu(bar, tearoff=0, postcommand=self._update_story_menu)
        for entry in self.story_actions():
            if entry is None:
                menu.add_separator()
                continue
            label, accel, run, _when, _kinds = entry
            menu.add_command(label=label, accelerator=accel.replace("Ctrl", key),
                             command=menu_command(menu, label, run))
        return menu

    def _update_story_menu(self) -> None:
        """The Story menu's entries, enabled for what is focused or selected now."""
        for entry in self.story_actions():
            if entry is not None:
                set_entry_enabled(self.story_menu, entry[0], entry[3]())


def _add_row(menu: tk.Menu, row: Row) -> None:
    if row is None:
        menu.add_separator()
    elif isinstance(row, Check):
        menu.add_checkbutton(label=row.label, variable=row.variable, command=row.command)
    else:
        command = (menu_command(menu, row.label, row.command) if row.guarded
                   else row.command)
        options: dict = {"label": row.label, "command": command}
        if row.accelerator:
            options["accelerator"] = row.accelerator
        menu.add_command(**options)
