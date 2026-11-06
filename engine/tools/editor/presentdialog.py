"""The Choice form's "Accept an item" section (F64 SPEC-present; I-13 "Studio accept an
item").

Why this module exists: the Choice form (``formdialogs.ChoiceDialog``) can give a menu a
``present:`` option. This section holds it: a tick box, the option's "Only show when"
condition, a row per item reaction (the item, where it goes) and the row for any other
item. A reaction whose lines the form can't hold shows ``forms.IN_TEXT`` and keeps them.
``values()`` is the ``PresentValues`` (None while unticked); ``on_change`` runs on every edit.
"""

import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from tkinter import ttk
from typing import Final

from engine.tools.editor import formpresent, formtools, forms
from engine.tools.editor.formpresent import PresentValues, ReactionItem
from engine.tools.editor.theme import THEME

ACCEPT_ITEM: Final = formpresent.ACCEPT_ITEM
LET_THEM_SHOW: Final = "Let the player show an item from their bag"
ITEM: Final = "Item"
GOES: Final = "Goes to"
WHEN: Final = "Only show when"
ADD_ITEM: Final = "+ Item"
REMOVE_ITEM: Final = "Remove item"
ITEM_WIDTH: Final = 20
PROBLEMS: Final = (formpresent.PRESENT_ITEM_TEXT, formpresent.PRESENT_TWICE_TEXT,
                   formpresent.PRESENT_REMOVE_TEXT, forms.CHOICE_LIMIT_TEXT)


class AcceptItemSection:
    """The section, packed into ``body`` under the options."""

    def __init__(self, body: ttk.Frame, dialog: tk.Misc, values: PresentValues | None, *,
                 items: Sequence[str], scenes: Sequence[str],
                 condition_names: Mapping[str, Sequence[str]], strong, scale: float,
                 on_change: Callable[[], None]) -> None:
        self.dialog = dialog
        self.items_known = list(items)
        self.scenes = list(scenes)
        self.condition_names = condition_names
        self.on_change = on_change
        self.scale = scale
        gap = self.gap = round(8 * scale)
        start = values or PresentValues()
        heading = ttk.Label(body, text=ACCEPT_ITEM, style="Dialog.TLabel", font=strong)
        heading.pack(anchor="w", pady=(round(16 * scale), 0))
        self.on = tk.BooleanVar(dialog, value=values is not None)
        line = ttk.Frame(body, style="Dialog.TFrame")
        line.pack(anchor="w", fill="x", pady=(round(6 * scale), 0))
        self.box = ttk.Checkbutton(line, text=LET_THEM_SHOW, variable=self.on,
                                   style="Dialog.TCheckbutton")
        self.box.pack(side="left")
        from engine.tools.editor.formdialogs import field_tip   # formdialogs imports us
        self.tip = field_tip(self.box, forms.CHOICE_FORM, "present")
        self.when = tk.StringVar(dialog, value=start.condition)
        self.when_button = ttk.Button(line, text=formtools.condition_label(start.condition),
                                      width=formtools.SUMMARY_CHARS,
                                      style="Secondary.TButton", command=self.edit_when)
        ttk.Label(line, text=WHEN, style="Dialog.Hint.TLabel").pack(
            side="left", padx=(round(16 * scale), gap))
        self.when_button.pack(side="left")
        self.when.trace_add("write", lambda *_a: self.when_button.configure(
            text=formtools.condition_label(self.when.get())))
        self.table = ttk.Frame(body, style="Dialog.TFrame")
        self.table.pack(anchor="w", fill="x", pady=(round(6 * scale), 0))
        for column, text in ((1, ITEM), (2, GOES)):
            ttk.Label(self.table, text=text, style="Dialog.Hint.TLabel").grid(
                row=0, column=column, sticky="w", padx=(0, gap))
        self.rows: list[dict] = []
        self.chosen = 0
        for reaction in start.reactions:
            self._add_row(reaction)
        self.other = self._goes_box(start.other)
        self.other_item = start.other
        self.other_label = ttk.Label(self.table, text=formpresent.ANY_OTHER_ITEM,
                                     style="Dialog.TLabel")
        tools = ttk.Frame(body, style="Dialog.TFrame")
        tools.pack(anchor="w", fill="x", pady=(gap, 0))
        self.add_button = ttk.Button(tools, text=ADD_ITEM, style="Secondary.TButton",
                                     command=self.add)
        self.add_button.pack(side="left", padx=(0, gap))
        self.remove_button = ttk.Button(tools, text=REMOVE_ITEM, style="Secondary.TButton",
                                        command=self.remove)
        self.remove_button.pack(side="left")
        for var in (self.on, self.when, self.other[0]):
            var.trace_add("write", lambda *_a: self._changed())
        self._grid()
        self._sync()

    # -- rows --

    def _goes_box(self, reaction: ReactionItem) -> tuple[tk.StringVar, ttk.Combobox]:
        var = tk.StringVar(self.dialog, value=formpresent.summary_of(reaction))
        if reaction.in_text:
            box = ttk.Combobox(self.table, textvariable=var, values=(forms.IN_TEXT,),
                               width=18, state="disabled")
        else:
            box = ttk.Combobox(self.table, textvariable=var, width=18,
                               values=[forms.CONTINUES, *self.scenes])
        return var, box

    def _add_row(self, reaction: ReactionItem) -> dict:
        item = tk.StringVar(self.dialog, value=reaction.item)
        mark = ttk.Label(self.table, text="", width=2, style="Dialog.TLabel",
                         foreground=THEME["focusBorder"])
        item_box = ttk.Combobox(self.table, textvariable=item, width=ITEM_WIDTH,
                                values=self.items_known)
        goes, goes_box = self._goes_box(reaction)
        row = {"reaction": reaction, "item": item, "goes": goes,
               "widgets": (mark, item_box, goes_box)}
        self.rows.append(row)
        for var in (item, goes):
            var.trace_add("write", lambda *_a: self._changed())
        for widget in (item_box, goes_box):
            widget.bind("<FocusIn>", lambda _e, r=row: self._choose(r), add="+")
        return row

    def _grid(self) -> None:
        gap = self.gap
        for n, row in enumerate(self.rows):
            mark, item_box, goes_box = row["widgets"]
            mark.grid(row=n + 1, column=0, sticky="w", pady=(gap if n else 0, 0))
            item_box.grid(row=n + 1, column=1, sticky="ew", padx=(0, gap),
                          pady=(gap if n else 0, 0))
            goes_box.grid(row=n + 1, column=2, sticky="ew", pady=(gap if n else 0, 0))
        last = len(self.rows) + 1
        self.other_label.grid(row=last, column=1, sticky="w", pady=(gap, 0))
        self.other[1].grid(row=last, column=2, sticky="ew", pady=(gap, 0))
        self.chosen = max(0, min(self.chosen, len(self.rows) - 1))
        for n, row in enumerate(self.rows):
            row["widgets"][0].configure(text="▸" if n == self.chosen else "")

    def _choose(self, row: dict) -> None:
        if row in self.rows:
            self.chosen = self.rows.index(row)
            self._grid()

    def add(self) -> None:
        self._add_row(ReactionItem(""))
        self.chosen = len(self.rows) - 1
        self._grid()
        self._changed()
        self.rows[-1]["widgets"][1].focus_set()

    def remove(self) -> None:
        if not self.rows:
            return
        row = self.rows.pop(self.chosen)
        for widget in row["widgets"]:
            widget.destroy()
        self._grid()
        self._changed()

    def edit_when(self) -> str | None:
        """The option's "Only show when" button: the condition builder."""
        got = formtools.ask_condition(self.dialog, self.when.get(), self.condition_names)
        try:
            self.dialog.grab_set()          # the nested dialog took the grab
        except tk.TclError:
            pass
        if got is not None:
            self.when.set(got)
        return got

    # -- state --

    def _sync(self) -> None:
        on = bool(self.on.get())
        state = ["!disabled"] if on else ["disabled"]
        for widget in (self.when_button, self.add_button, self.other[1]):
            if widget is self.other[1] and self.other_item.in_text:
                continue
            widget.state(state)
        self.remove_button.state(["!disabled"] if on and self.rows else ["disabled"])
        for row in self.rows:
            mark, item_box, goes_box = row["widgets"]
            item_box.state(state)
            if not row["reaction"].in_text:
                goes_box.state(state)

    def _changed(self) -> None:
        self._sync()
        self.on_change()

    @staticmethod
    def _goes(reaction: ReactionItem, text: str) -> tuple[str | None, bool]:
        if reaction.in_text:
            return reaction.goes, True
        text = text.strip()
        return (None if text in ("", forms.CONTINUES) else text), False

    def values(self) -> PresentValues | None:
        if not self.on.get():
            return None
        out = []
        for row in self.rows:
            reaction: ReactionItem = row["reaction"]
            goes, in_text = self._goes(reaction, row["goes"].get())
            out.append(ReactionItem(row["item"].get().strip(), goes, in_text, reaction.old))
        other = self.other_item
        goes, in_text = self._goes(other, self.other[0].get())
        return PresentValues(self.when.get().strip(), tuple(out),
                             ReactionItem("", goes, in_text, other.old))


__all__ = ["ACCEPT_ITEM", "ADD_ITEM", "AcceptItemSection", "LET_THEM_SHOW", "PROBLEMS",
           "REMOVE_ITEM"]
