"""Studio's Table panel: one rows-by-columns editor for the minigames' ``define`` tables (F64
round 2; proposal "Table panel" foundation).

Why this module exists: gift tables, shop stock, and later recipes, letter phrases, timelines
and decks are all rows by columns in a ``define`` literal. Each used to need its own grid of
widgets; this panel is that grid once. The owner (an ``minigameview.Editor``) keeps the model
and turns each edit into a new model, which it writes as one plan (one undo step per edit,
``Editor.changed``); the panel only shows rows and reports what the author did.

**API.**

- ``Column(key, head, kind, …)``: one typed column. ``kind`` is ``PICK`` (a read-only
  drop-down of ``choices()``: ``(value, shown)`` pairs; the cell reports the value), ``NUMBER``
  (a spinner from ``lo`` to ``hi``; with ``blank=True`` an empty cell is ``None``), ``TEXT``
  (one line; with ``blank=True`` an empty cell is ``None``, else ``""``) or ``LABEL`` (read
  only, ``text(row)``). ``width`` is in characters; ``rule`` is the message shown when a typed
  number is refused (None: the old value just comes back).
- ``TablePanel(parent, columns, px=…, on_edit=…, on_remove=…, on_move=…)``: the grid in
  ``panel.frame``. ``show(rows, pinned=())`` (re)builds it: a caption row (the heads, upper
  case), then each pinned row (``(label, values)``: a fixed first cell, no remove or move: the
  gift table's "Any other gift"), then each row (``values``: column key → value). Each row
  ends with ✕ (``on_remove(i)``) and, with ``on_move``, ▲ and ▼ (``on_move(i, -1|+1)``).
- An edit calls ``on_edit(i, key, value)`` for row ``i`` and ``on_pinned(i, key, value)`` for
  a pinned row, once per commit (Enter, a pick, leaving the cell) of a changed cell. A typed
  number outside ``lo``..``hi`` (or not a number) is refused in the cell: its old value
  comes back and ``rule`` is said.
- ``rows`` / ``pinned_cells``: each shown row's cells, column key → widget: a ``Combo`` or
  ``Entry`` (``.var``, ``.commit()``), or for a number the ``StringVar`` with its spinner at
  ``key + ".spin"``. ``message``: the validation line under the grid (``say(text)``).
- Pure helpers for owners: ``moved(seq, i, step)`` and ``removed(seq, i)``.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any, Final, TypeVar

from engine.tools.editor.theme import ROLES

PICK: Final = "pick"
NUMBER: Final = "number"
TEXT: Final = "text"
LABEL: Final = "label"
KINDS: Final = (PICK, NUMBER, TEXT, LABEL)

REMOVE: Final = "✕"
UP, DOWN = "▲", "▼"
PAD_PX: Final = 6

T = TypeVar("T")


@dataclass(frozen=True)
class Column:
    """One typed column (module docstring)."""

    key: str
    head: str
    kind: str
    width: int = 18
    choices: Callable[[], Sequence[tuple[object, str]]] = lambda: ()
    lo: int = 0
    hi: int = 999_999
    blank: bool = False
    rule: str | None = None
    text: Callable[[Mapping[str, object]], str] = field(default=lambda row: "")


# --- Pure helpers ----------------------------------------------------------------------------

def moved(seq: Sequence[T], index: int, step: int) -> tuple[T, ...]:
    """``seq`` with item ``index`` moved ``step`` places (the same order when it can't)."""
    items = list(seq)
    to = index + step
    if not (0 <= index < len(items) and 0 <= to < len(items)):
        return tuple(items)
    items.insert(to, items.pop(index))
    return tuple(items)


def removed(seq: Sequence[T], index: int) -> tuple[T, ...]:
    """``seq`` without item ``index``."""
    return tuple(x for i, x in enumerate(seq) if i != index)


def number_value(text: str, lo: int, hi: int, *, blank: bool) -> tuple[bool, int | None]:
    """A number cell's text as ``(ok, value)``: a whole number from ``lo`` to ``hi``, or, with
    ``blank``, ``None`` for an empty cell."""
    text = str(text).strip().replace(",", "")
    if not text:
        return blank, None
    try:
        value = int(text)
    except ValueError:
        return False, None
    return lo <= value <= hi, value if lo <= value <= hi else None


# --- Small widgets ---------------------------------------------------------------------------

class Combo:
    """An editable drop-down that commits on a pick, Enter or focus-out (``on_change(text)``)."""

    def __init__(self, parent: tk.Misc, values: Sequence[str], value: str, *,
                 on_change: Callable[[str], object], width: int = 18,
                 readonly: bool = False) -> None:
        self.var = tk.StringVar(master=parent, value=value)
        self.value = value
        self.on_change = on_change
        self.widget = self.box = ttk.Combobox(parent, textvariable=self.var, values=list(values),
                                              width=width,
                                              state="readonly" if readonly else "normal")
        self.box.bind("<<ComboboxSelected>>", lambda _e: self.commit(), add="+")
        for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
            self.box.bind(key, lambda _e: self.commit(), add="+")

    def set(self, value: str) -> None:
        self.value = value
        self.var.set(value)

    def commit(self) -> None:
        text = self.var.get().strip()
        if text != self.value:
            self.value = text
            self.on_change(text)


class Entry:
    """A one-line entry committing on Enter or focus-out; Escape puts the value back."""

    def __init__(self, parent: tk.Misc, value: str, *, on_change: Callable[[str], object],
                 width: int = 30) -> None:
        self.var = tk.StringVar(master=parent, value=value)
        self.value = value
        self.on_change = on_change
        self.widget = self.entry = ttk.Entry(parent, textvariable=self.var, width=width)
        for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
            self.entry.bind(key, lambda _e: self.commit(), add="+")
        self.entry.bind("<Escape>", lambda _e: self.var.set(self.value), add="+")

    def set(self, value: str) -> None:
        self.value = value
        self.var.set(value)

    def commit(self) -> None:
        text = self.var.get()
        if text != self.value:
            self.value = text
            self.on_change(text)


# --- The panel -------------------------------------------------------------------------------

Report = Callable[[int, str, object], object]


class TablePanel:
    """The grid (module docstring)."""

    def __init__(self, parent: tk.Misc, columns: Sequence[Column], *,
                 px: Callable[[float], int], on_edit: Report,
                 on_pinned: Report | None = None,
                 on_remove: Callable[[int], object] | None = None,
                 on_move: Callable[[int, int], object] | None = None,
                 message: bool = False) -> None:
        self.columns = tuple(columns)
        self.px = px
        self.on_edit = on_edit
        self.on_pinned = on_pinned
        self.on_remove = on_remove
        self.on_move = on_move
        self.frame = ttk.Frame(parent)
        self.message = ttk.Label(parent, text="", foreground=ROLES["warning"],
                                 wraplength=px(560), justify="left") if message else None
        self.rows: list[dict[str, Any]] = []
        self.pinned_cells: list[dict[str, Any]] = []
        self.values: list[Mapping[str, object]] = []
        self._last_spin: Any = None

    def say(self, text: str) -> None:
        """The validation line (only when the panel was made with ``message=True``)."""
        if self.message is not None:
            self.message.configure(text=text)

    # -- building --

    def clear(self) -> None:
        for child in self.frame.winfo_children():
            child.destroy()
        self.rows, self.pinned_cells, self.values = [], [], []

    def show(self, rows: Sequence[Mapping[str, object]],
             pinned: Sequence[tuple[str, Mapping[str, object]]] = ()) -> None:
        self.clear()
        self.values = list(rows)
        pad = self.px(PAD_PX)
        for c, column in enumerate(self.columns):
            ttk.Label(self.frame, text=column.head.upper(), style="Caption.TLabel").grid(
                row=0, column=c, sticky="w", padx=(0, pad))
        r = 1
        for i, (label, values) in enumerate(pinned):
            ttk.Label(self.frame, text=label).grid(row=r, column=0, sticky="w", padx=(0, pad),
                                                   pady=1)
            report = self.on_pinned or (lambda *_a: None)
            self.pinned_cells.append(self._cells(r, values, lambda k, v, i=i, f=report: f(i, k, v),
                                                 skip_first=True))
            r += 1
        for i, values in enumerate(rows):
            cells = self._cells(r, values, lambda k, v, i=i: self.on_edit(i, k, v))
            at = len(self.columns)
            if self.on_move is not None:
                for step, text in ((-1, UP), (1, DOWN)):
                    ok = 0 <= i + step < len(rows)
                    move = self.on_move
                    button = ttk.Button(self.frame, text=text, width=3, style="Ghost.TButton",
                                        command=lambda i=i, s=step, m=move: m(i, s))
                    button.grid(row=r, column=at, sticky="w")
                    if not ok:
                        button.state(["disabled"])
                    cells["up" if step < 0 else "down"] = button
                    at += 1
            if self.on_remove is not None:
                button = ttk.Button(self.frame, text=REMOVE, width=3, style="Ghost.TButton",
                                    command=lambda i=i: self.on_remove(i))  # type: ignore[misc]
                button.grid(row=r, column=at, sticky="w")
                cells["remove"] = button
            self.rows.append(cells)
            r += 1

    def _cells(self, r: int, values: Mapping[str, object],
               report: Callable[[str, object], object], *,
               skip_first: bool = False) -> dict[str, Any]:
        pad = self.px(PAD_PX)
        cells: dict[str, Any] = {}
        for c, column in enumerate(self.columns):
            if skip_first and c == 0:
                continue
            cell = self._cell(column, values, report)
            if column.kind == NUMBER:
                widget = cells[column.key + ".spin"] = self._last_spin
            else:
                widget = getattr(cell, "widget", cell)
            widget.grid(row=r, column=c, sticky="w", padx=(0, pad), pady=1)
            cells[column.key] = cell
        return cells

    def _cell(self, column: Column, values: Mapping[str, object],
              report: Callable[[str, object], object]) -> Any:
        value = values.get(column.key)
        if column.kind == PICK:
            choices = list(column.choices())
            shown = [s for _v, s in choices]
            current = next((s for v, s in choices if v == value),
                           "" if value is None else str(value))

            def picked(text: str, c=choices, key=column.key) -> None:
                report(key, next((v for v, s in c if s == text), text))
            return Combo(self.frame, shown, current, width=column.width, readonly=True,
                         on_change=picked)
        if column.kind == NUMBER:
            var = tk.StringVar(master=self.frame, value="" if value is None else str(value))
            spin = ttk.Spinbox(self.frame, from_=column.lo, to=column.hi, increment=1,
                               width=column.width, textvariable=var)
            state = {"value": value}

            def done(_e: object = None, col=column, v=var) -> None:
                ok, number = number_value(v.get(), col.lo, col.hi, blank=col.blank)
                if not ok:
                    v.set("" if state["value"] is None else str(state["value"]))
                    if col.rule:
                        self.say(col.rule)
                    return
                self.say("")
                if number != state["value"]:
                    state["value"] = number
                    report(col.key, number)
            spin.configure(command=done)
            for key in ("<Return>", "<KP_Enter>", "<FocusOut>"):
                spin.bind(key, done, add="+")
            self._last_spin = spin
            return var
        if column.kind == TEXT:
            def typed(text: str, col=column) -> None:
                found: object = text.strip()
                report(col.key, None if col.blank and not found else found)
            return Entry(self.frame, "" if value is None else str(value), width=column.width,
                         on_change=typed)
        return ttk.Label(self.frame, text=column.text(values), style="Hint.TLabel",
                         width=column.width)


__all__ = ["Column", "Combo", "DOWN", "Entry", "KINDS", "LABEL", "NUMBER", "PICK", "REMOVE",
           "TEXT", "TablePanel", "UP", "moved", "number_value", "removed"]
