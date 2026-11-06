"""Game settings ▸ Kit (F60; specs/F60-genre-kits/SPEC.md): the page's widgets.

Why this module exists: the Kit page lives in ``settingsview``'s form column but keeps its
own widgets and state here, so the shared view only calls ``KitPage(view, body)`` when the
page is built and ``show()`` after each read of ``config.toml``. Top to bottom:

- the unknown-id note (when ``[game] kit`` names no kit);
- the picked kit: its name, blurb and what it sets (``kitmodel.details``);
- **Apply <kit>** and, for a kit, "Also use its color scheme (<name>)";
- the cards (``kitcards``), "No kit" first.

Selecting a card writes nothing. Apply (or Enter, a double-click) writes ``[game] kit``
and, when ticked, ``[theme] preset`` too, as one ``tomlpatch.plan_changes`` plan: one undo
step of ``config.toml``.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any

from engine.tools.editor import kitmodel as km
from engine.tools.editor import settingsmodel as sm
from engine.tools.editor import tomlpatch
from engine.tools.editor.kitcards import KitCards
from engine.tools.editor.theme import ROLES, THEME


class KitPage:
    """The Kit page inside ``body``, for the Game settings ``view`` (``SettingsView``)."""

    def __init__(self, view: Any, body: ttk.Frame) -> None:
        self.view = view
        px = view._px
        found = view.found
        use = km.in_use(found)
        self.pick: str = use if use is not None else km.NONE
        self.unknown, inner = view._note_box(body, ROLES["warning"])
        self.unknown_label = view._note_label(inner)
        self.detail = tk.Frame(body, background=THEME["editor.background"])
        self.detail.pack(fill="x", pady=(px(4), 0))
        self.heading = view._note_label(self.detail, strong=True)
        self.lines = [view._note_label(self.detail) for _ in range(3)]
        self.buttons = ttk.Frame(body)
        self.buttons.pack(anchor="w", fill="x", pady=(px(10), 0))
        self.apply_button = ttk.Button(self.buttons, text="",
                                       command=lambda: self.apply(self.pick))
        self.apply_button.pack(side="left")
        self.with_scheme = tk.BooleanVar(master=view.root, value=True)
        self.scheme_check = ttk.Checkbutton(self.buttons, text="", variable=self.with_scheme,
                                            command=self._show_apply)
        self.scheme_check.pack(side="left", padx=(px(12), 0))
        self.cards = KitCards(body, km.cards(found), scale=view.scale, fonts=view.win.fonts,
                              selected=self.pick, in_use=use, on_select=self.select,
                              on_apply=self.apply)
        self.cards.widget.pack(fill="x", pady=(px(12), 0))
        self._offered: str | None = None
        self.show()

    @property
    def widget(self) -> tk.Canvas:
        return self.cards.widget

    def show(self) -> None:
        """The page's state from the open text: the cards, "In use", the picked kit's
        details, the scheme option and Apply, and the unknown-id note."""
        if not self.cards.widget.winfo_exists():
            return
        found = self.view.found
        use = km.in_use(found)
        self.cards.set_cards(km.cards(found))
        self.cards.set_state(self.pick, use)
        name = km.name_of(self.pick)
        self.heading.configure(text=name)
        lines = km.details(self.pick)
        for label, text in zip(self.lines, (*lines, "", "")):
            label.configure(text=text)
            if text:
                label.pack(anchor="w", fill="x")
            else:
                label.pack_forget()
        offer = km.scheme_offer(self.pick, found)
        if offer is None:
            self.scheme_check.pack_forget()
        else:
            if self._offered != self.pick:            # a new pick starts at its default
                self.with_scheme.set(offer.ticked)
                self._offered = self.pick
            if not offer.enabled:
                self.with_scheme.set(True)
            self.scheme_check.configure(text=offer.text,
                                        state="normal" if offer.enabled else "disabled")
            self.scheme_check.pack(side="left", padx=(self.view._px(12), 0))
        self._show_apply()
        unknown = km.unknown_text(found)
        if unknown is not None:
            self.unknown_label.configure(text=unknown)
            self.unknown.pack(fill="x", pady=(0, self.view._px(8)), before=self.detail)
        else:
            self.unknown.pack_forget()

    def _changes(self, id_: str) -> tuple[tuple[str, str, str | None], ...]:
        offer = km.scheme_offer(id_, self.view.found)
        ticked = offer is not None and offer.enabled and self.with_scheme.get()
        return km.apply_changes(id_, ticked, self.view.found)

    def _show_apply(self) -> None:
        self.apply_button.configure(text=km.apply_text(self.pick),
                                    state="normal" if self._changes(self.pick) else "disabled")

    def select(self, id_: str) -> None:
        """A card was picked: show it (nothing is written)."""
        self.pick = id_
        self.show()

    def apply(self, id_: str | None) -> bool:
        """Apply (Enter, a double-click): write the kit, and its scheme when ticked, as one
        undo step; nothing to change writes nothing."""
        view = self.view
        text = view.config_text()
        if text is None or id_ is None:
            view.refresh()
            return False
        if id_ != self.pick:
            self.select(id_)
        changes = self._changes(id_)
        if not changes:
            view.refresh()
            return True
        field = sm.fields_by_path()[km.PATH]
        return view._apply(tomlpatch.plan_changes(text, changes), field)


__all__ = ["KitPage"]
