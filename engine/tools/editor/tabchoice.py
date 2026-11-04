"""Which of the right area's tabs the strip shows, and the Tabs and panes window
(2026-11-04).

Why this module exists: six tabs is a lot for someone making their first game, and not every
author uses every page. An author can hide a tab they don't use. Every route to a page stays,
and taking one brings its tab back (``reveal_tab``):

- The View rows and Ctrl+1…6, which go to a tab.
- File ▸ Game settings (next to Studio settings…, so the two kinds of settings sit side by
  side), and a click on a picture or sound in Project for File preview.

**Tabs and panes…** (View, or a right-click on the tab strip) is one small window with a box
for every tab and pane, Lock pane layout and Reset pane layout. It stays open while the
author ticks several boxes (a menu closes on each click), and each box takes effect at once.

The Editor can't be hidden: every script opens there. File preview starts hidden, since a
click on a file shows it. What is hidden is the author's, kept for every game (``uiprefs``).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Final

from engine.tools.editor import studiostate, uiprefs

ALWAYS: Final = "editor"                     # never hidden: every script opens there
DEFAULT_HIDDEN: Final = frozenset({"asset"})  # a click on a picture or sound shows it
GAME_SETTINGS_MENU: Final = "Game settings"   # File's route to the Game settings tab
LAYOUT_MENU: Final = "Tabs and panes…"
LAYOUT_TITLE: Final = "Tabs and panes"
TABS_HEADING: Final = "Tabs"
PANES_HEADING: Final = "Panes"
EDITOR_NOTE: Final = "The Editor always stays: every script opens there."
SHOW_ALL: Final = "Show all tabs"
DONE: Final = "Done"


def hidden_from(saved: object) -> frozenset[str]:
    """The hidden tab names from a saved ``tabs`` value (the default without one; unknown
    names and the Editor are dropped by ``TabChoice``)."""
    if isinstance(saved, dict) and isinstance(saved.get("hidden"), list):
        return frozenset(name for name in saved["hidden"] if isinstance(name, str))
    return DEFAULT_HIDDEN


class TabChoice:
    """``EditorWindow``'s part: the shown tabs, bringing one back, and Tabs and panes…."""

    tabs: Any
    notebook: Any
    tab_strip: Any
    root: Any
    paths: Any

    def _build_tab_choice(self) -> None:
        names = [tab.name for tab in self.tabs]
        state = studiostate.read_state(self.paths.root)
        saved = uiprefs.value("tabs", getattr(state, "tabs", None))   # the author's, any game
        self.tabs_hidden: set[str] = {n for n in hidden_from(saved) if n in names and n != ALWAYS}
        self.tab_vars = {tab.name: tk.BooleanVar(self.root, value=tab.name not in
                                                 self.tabs_hidden) for tab in self.tabs}
        self.layout_window: tk.Toplevel | None = None
        self.tab_strip.on_menu = lambda _event: self.open_layout()
        self._apply_tabs()

    # -- the tabs ---------------------------------------------------------------------------

    def tab_shown(self, name: str) -> bool:
        return name not in self.tabs_hidden

    def set_tab_shown(self, name: str, on: bool) -> None:
        """Show or hide the tab called ``name`` (the Editor always stays) and keep it."""
        if name == ALWAYS or name not in self.tab_vars:
            if name in self.tab_vars:
                self.tab_vars[name].set(True)
            return
        if on == self.tab_shown(name):
            self.tab_vars[name].set(on)
            return
        if on:
            self.tabs_hidden.discard(name)
        else:
            self.tabs_hidden.add(name)
        self._apply_tabs()
        self._save_tabs()

    def show_all_tabs(self) -> None:
        if self.tabs_hidden:
            self.tabs_hidden.clear()
            self._apply_tabs()
            self._save_tabs()

    def reveal_tab(self, name: str) -> None:
        """A route to the tab ``name`` was taken: its tab comes back if it was hidden."""
        if not self.tab_shown(name):
            self.set_tab_shown(name, True)

    def _apply_tabs(self) -> None:
        for index, tab in enumerate(self.tabs):
            self.tab_vars[tab.name].set(self.tab_shown(tab.name))
            self.tab_strip.set_shown(index, self.tab_shown(tab.name))
        current = self.tabs[self.notebook.index("current")].name
        if not self.tab_shown(current):
            self.notebook.select(0)             # the page on screen was hidden: the Editor

    def _save_tabs(self) -> None:
        hidden = sorted(self.tabs_hidden)
        default = set(hidden) == set(DEFAULT_HIDDEN)
        self.save_studio_state(tabs=None if default else {"hidden": hidden})  # type: ignore[attr-defined]

    # -- Tabs and panes… ----------------------------------------------------------------------

    def open_layout(self) -> tk.Toplevel:
        """View ▸ Tabs and panes… (or a right-click on the tabs): the window, or the open
        one raised. Not modal: the author can watch Studio change behind it."""
        from engine.tools.editor import dialogs
        from engine.tools.editor.docking import CLOSABLE, LOCK_MENU, PANE_TITLES, RESET_MENU
        from engine.tools.editor.theme import dark_title_bar
        if self.layout_window is not None and self.layout_window.winfo_exists():
            self.layout_window.deiconify()
            self.layout_window.lift()
            self.layout_window.focus_force()
            return self.layout_window
        window = self.layout_window = dialogs._dialog(self.root)
        window.title(LAYOUT_TITLE)
        body, scale = dialogs._body(window)
        gap = round(8 * scale)

        def heading(text: str, top: int) -> None:
            ttk.Label(body, text=text, style="Dialog.TLabel",
                      font=getattr(self, "fonts", {}).get("bodyStrong")).pack(
                anchor="w", pady=(top, round(2 * scale)))

        def box(text: str, var: tk.BooleanVar, command: Any, on: bool = True) -> ttk.Checkbutton:
            check = ttk.Checkbutton(body, text=text, variable=var, command=command,
                                    style="Dialog.TCheckbutton")
            check.pack(anchor="w", padx=(gap, 0))
            if not on:
                check.state(["disabled"])
            return check

        heading(TABS_HEADING, 0)
        for tab in self.tabs:
            box(tab.title, self.tab_vars[tab.name],
                lambda n=tab.name: self.set_tab_shown(n, self.tab_vars[n].get()),
                on=tab.name != ALWAYS)
        ttk.Label(body, text=EDITOR_NOTE, style="Dialog.Hint.TLabel").pack(
            anchor="w", padx=(gap, 0), pady=(round(2 * scale), 0))
        dock_vars = getattr(self, "dock_vars", None)
        if dock_vars:
            heading(PANES_HEADING, gap * 2)
            for pane in CLOSABLE:
                box(PANE_TITLES[pane], dock_vars[pane], lambda p=pane: self.toggle_pane(p))  # type: ignore[attr-defined]
            box(LOCK_MENU, self.lock_var, self.toggle_lock)  # type: ignore[attr-defined]
        row = ttk.Frame(body, style="Dialog.TFrame")
        row.pack(fill="x", pady=(gap * 2, 0))
        ttk.Button(row, text=SHOW_ALL, style="Secondary.TButton",
                   command=self.show_all_tabs).pack(side="left")
        if dock_vars:
            ttk.Button(row, text=RESET_MENU, style="Secondary.TButton",
                       command=self.reset_layout).pack(side="left", padx=(gap, 0))  # type: ignore[attr-defined]
        done = ttk.Button(row, text=DONE, command=window.destroy)
        done.pack(side="right", padx=(gap * 2, 0))
        for key in ("<Escape>", "<Return>", "<KP_Enter>"):
            window.bind(key, lambda _e: window.destroy())
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        dialogs._center(window, self.root)
        window.deiconify()
        dark_title_bar(window)
        done.focus_set()
        return window


__all__ = ["ALWAYS", "DEFAULT_HIDDEN", "DONE", "EDITOR_NOTE", "GAME_SETTINGS_MENU",
           "LAYOUT_MENU", "LAYOUT_TITLE", "PANES_HEADING", "SHOW_ALL", "TABS_HEADING",
           "TabChoice", "hidden_from"]
