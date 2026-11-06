"""Studio's menus (F45 ``01`` §6.1): File, Edit, Insert, Story, View, Run, Help, built from
``menu_table`` as the ``StudioMenus`` mixin of ``window.EditorWindow``. A row is
``Item(label, accelerator, command)`` (``guarded``: through ``views.menu_command``, so a
disabled entry does nothing), ``Check(label, variable, command)``, or ``SEPARATOR``; Insert
and Story are built from the doc registry and ``story_actions``. View's tab rows come from
``window.TABS``. F47 adds Run and Help rows; Help ▸ Guides opens the docs pages; F42 a File row after Save all; F39 the Run
menu's "Update the running game" (Ctrl+R, on while a game runs) and "Update the game on
save"; F48 Help ▸ Connect an AI app… (``connectdialog``), File ▸ Studio settings…
(Ctrl+,, ``aisettings``) and View ▸ AI Assistant (Ctrl+Shift+A, ``assistwiring``).

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
from engine.tools.editor.gamebeside import MENU as BESIDE_MENU
from engine.tools.editor.runwiring import (
    CONSOLE_MENU,
    JUMP_MENU,
    NO_GAME,
    PLAYTHROUGH_MENU,
    UPDATE_MENU,
    UPDATE_ON_SAVE_MENU,
)
from engine.tools.editor.guide import GUIDE_TITLE
from engine.tools.editor.guides import GUIDES, GUIDES_MENU
from engine.tools.editor.builddialog import open_build_dialog
from engine.tools.editor.connectdialog import MENU as CONNECT_MENU, open_connect_dialog
from engine.tools.editor.aisettings import MENU as SETTINGS_MENU, open_ai_settings
from engine.tools.editor.assistwiring import MENU as ASSISTANT_MENU
from engine.tools.editor.formdialogs import entry_title
from engine.tools.editor.tabchoice import GAME_SETTINGS_MENU, LAYOUT_MENU
from engine.tools.build.texts import MENU as BUILD_MENU
from engine.tools.editor.livemap import FOLLOW_CHANGES, REDUCE_MOTION

FIND_SCENE_MENU = "Find scene…"         # Edit: goes to a scene's line by name
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
                Item("Open game…", f"{key}+O", self.open_game),
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
                Item(BUILD_MENU, f"{key}+Shift+B", lambda: open_build_dialog(self),
                     guarded=True),
                SEPARATOR,
                # The game's settings beside Studio's own, so the two are told apart.
                Item(GAME_SETTINGS_MENU, command=lambda: self.show_tab(
                    self.tab_index("settings"))),
                Item(SETTINGS_MENU, f"{key}+,", self.studio_settings),     # F48 §6.2
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
                Item(FIND_SCENE_MENU, f"{key}+G", self.go_to_label),
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
                Check(SHOW_WARNINGS, self.show_warnings, self.toggle_warnings),
                Check(REDUCE_MOTION, self.reduce_motion, self.toggle_reduce_motion),   # F58
                SEPARATOR,
                Item(ASSISTANT_MENU, f"{key}+Shift+A", self.toggle_assistant),   # F48 §6.1
                # One window with every tab and pane box: a menu closes on each click.
                Item(LAYOUT_MENU, command=self.open_layout),
            ]),
            ("Run", "run_menu", [
                Item(PLAY_MENU, "Shift+F5", self.play_from_start),
                Item(PLAY_SCENE_MENU, "F5", self.play_scene),
                Item(STOP_MENU, f"{key}+F2", self.stop_game),
                Item(PLAY_OPTIONS, command=self.play_options),
                Check(BESIDE_MENU, self.game_beside, self.toggle_game_beside),  # 2.3
                Item(CONSOLE_MENU, "F12", self.open_console),               # F40
                Item(JUMP_MENU, NO_GAME, self.jump_game_to_scene),          # F40: dimmed
                Item(PLAYTHROUGH_MENU, command=self.preview_playthrough),   # F32
                SEPARATOR,
                Item(UPDATE_MENU, f"{key}+R", self.update_game, guarded=True),
                Check(UPDATE_ON_SAVE_MENU, self.update_on_save, self.toggle_update_on_save),
                SEPARATOR,
                Item("Check now", "F7", self.check_now),
            ]),
            ("Help", "help_menu", self._build_help_menu),
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
        set_entry_enabled(self.run_menu, UPDATE_MENU, False)    # on while a game runs
        set_entry_enabled(self.run_menu, JUMP_MENU, False)      # F40: likewise
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
        self.play_bar.merge_into(self.menu_bar.frame)   # one row: menus, then Play's buttons

    def _build_insert_menu(self, bar: tk.Menu) -> tk.Menu:
        """Insert: one submenu per GROUPS entry with docs, built once from the registry."""
        menu = tk.Menu(bar, tearoff=0)
        self.insert_submenus: dict[str, tk.Menu] = {}
        for group, docs in insert_menu():
            sub = tk.Menu(menu, tearoff=0)
            for doc in docs:
                # The names Events ▸ Insert… uses ("Background", not "Scene").
                sub.add_command(label=entry_title(doc),
                                command=lambda d=doc: self.insert_doc(d))
            menu.add_cascade(label=group, menu=sub)
            self.insert_submenus[group] = sub
        return menu

    def _build_help_menu(self, bar: tk.Menu) -> tk.Menu:
        """Help: help for the line, the Guide pane (F47: shows or hides it), **Guides**,
        the engine's docs pages (``guides.GUIDES``), and F48's Connect an AI app…."""
        menu = tk.Menu(bar, tearoff=0)
        for row in (Item("Help for this line", command=self.focus_help),
                    Item(GUIDE_TITLE, command=self.toggle_guide)):
            _add_row(menu, row)
        sub = tk.Menu(menu, tearoff=0)
        for title, name in GUIDES:
            sub.add_command(label=title, command=lambda t=title, n=name: self.open_guide(t, n))
        menu.add_cascade(label=GUIDES_MENU, menu=sub)
        self.guides_menu = sub
        _add_row(menu, SEPARATOR)
        _add_row(menu, Item(CONNECT_MENU, command=self.connect_ai_app))
        return menu

    def toggle_warnings(self) -> None:
        """View ▸ Show warnings: the panel again, and the choice kept for every game."""
        self.save_studio_state(show_warnings=bool(self.show_warnings.get()))
        self.render_panel()

    def studio_settings(self) -> None:
        """File ▸ Studio settings… (F48 01 §6.2): the AI page."""
        open_ai_settings(self)

    def connect_ai_app(self) -> None:
        """Help ▸ Connect an AI app… (F48 01 §6.5)."""
        open_connect_dialog(self)

    def open_guide(self, title: str, name: str) -> None:
        """Help ▸ Guides ▸ ``title``: the guide ``name`` in Studio's reader window."""
        from engine.tools.editor import guidereader
        guidereader.show_guide(self, name, title)

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
        menu.add_separator()                # F58 PR-13: the map's toolbar box, no key
        menu.add_checkbutton(label=FOLLOW_CHANGES, variable=self.story_map.follow_var,
                             command=self._follow_changes_toggled)
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
