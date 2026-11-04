"""Which of the right area's tabs the strip shows (2026-11-04).

Why this module exists: six tabs is a lot for someone making their first game, and not every
author uses every page. An author can hide a tab they don't use. Every route to a page stays,
and taking one brings its tab back (``reveal_tab``):

- View ▸ Show tabs (a check row per tab, and Show all tabs), and the same menu on a
  right-click on the strip.
- The View rows and Ctrl+1…6, which go to a tab.
- File ▸ Game settings (next to Studio settings…, so the two kinds of settings sit side by
  side), and a click on a picture or sound in Project for File preview.

The Editor can't be hidden: every script opens there. File preview starts hidden, since a
click on a file shows it. What is hidden is kept in ``.studio/studio.json`` (``tabs``).
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Final

from engine.tools.editor import studiostate

ALWAYS: Final = "editor"                     # never hidden: every script opens there
DEFAULT_HIDDEN: Final = frozenset({"asset"})  # a click on a picture or sound shows it
SHOW_TABS_MENU: Final = "Show tabs"
SHOW_ALL: Final = "Show all tabs"
GAME_SETTINGS_MENU: Final = "Game settings"   # File's route to the Game settings tab


def hidden_from(saved: object) -> frozenset[str]:
    """The hidden tab names from ``studio.json``'s ``tabs`` value (the default without one;
    unknown names and the Editor are dropped by ``TabChoice``)."""
    if isinstance(saved, dict) and isinstance(saved.get("hidden"), list):
        return frozenset(name for name in saved["hidden"] if isinstance(name, str))
    return DEFAULT_HIDDEN


class TabChoice:
    """``EditorWindow``'s part: the shown tabs, their menus, and bringing one back."""

    tabs: Any
    notebook: Any
    tab_strip: Any
    root: Any
    view_menu: Any
    paths: Any

    def _build_tab_choice(self) -> None:
        names = [tab.name for tab in self.tabs]
        state = studiostate.read_state(self.paths.root)
        hidden = hidden_from(getattr(state, "tabs", None))
        self.tabs_hidden: set[str] = {n for n in hidden if n in names and n != ALWAYS}
        self.tab_vars = {tab.name: tk.BooleanVar(self.root, value=tab.name not in
                                                 self.tabs_hidden) for tab in self.tabs}
        self.tabs_menu = self._tab_menu(self.view_menu)
        last = max(i for i in range(self.view_menu.index("end") + 1)
                   if self.view_menu.type(i) == "command"
                   and self.view_menu.entrycget(i, "label") == self.tabs[-1].title)
        self.view_menu.insert_cascade(last + 1, label=SHOW_TABS_MENU, menu=self.tabs_menu)
        self.strip_menu = self._tab_menu(self.root)
        self.tab_strip.on_menu = self._post_strip_menu
        self._apply_tabs()

    def _tab_menu(self, parent: tk.Misc) -> tk.Menu:
        menu = tk.Menu(parent, tearoff=0)
        for tab in self.tabs:
            menu.add_checkbutton(label=tab.title, variable=self.tab_vars[tab.name],
                                 command=lambda n=tab.name: self.set_tab_shown(
                                     n, self.tab_vars[n].get()),
                                 state="disabled" if tab.name == ALWAYS else "normal")
        menu.add_separator()
        menu.add_command(label=SHOW_ALL, command=self.show_all_tabs)
        return menu

    def _post_strip_menu(self, event: tk.Event) -> None:
        try:
            self.strip_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.strip_menu.grab_release()

    def tab_shown(self, name: str) -> bool:
        return name not in self.tabs_hidden

    def set_tab_shown(self, name: str, on: bool) -> None:
        """Show or hide the tab called ``name`` (the Editor always stays) and keep it."""
        if name == ALWAYS or name not in self.tab_vars:
            self.tab_vars.get(name, tk.BooleanVar(value=True)).set(True)
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


__all__ = ["ALWAYS", "DEFAULT_HIDDEN", "GAME_SETTINGS_MENU", "SHOW_ALL", "SHOW_TABS_MENU",
           "TabChoice", "hidden_from"]
