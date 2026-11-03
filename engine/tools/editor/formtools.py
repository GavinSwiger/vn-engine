"""The statement forms' visual helpers (F47 design PR-F47-21, PR-F47-22, §4.5; ``04-technical.md``
P2): the condition builder, the Say text toolbar, the form colour field, and the small value
dialogs they open. ``formdialogs`` puts them in its forms; they hold no script rules of
their own (``conditions`` and ``texttools`` do).

- ``ConditionBuilder``: an If's condition (and, inside ``ConditionDialog``, a choice's "Only
  show when") as up to four rows ``[what ▾] [name ▾] [is at least ▾] [value]`` with + / −
  and All of / Any of. Names come from the Database and the check (variables, meters, codex
  tips, items, endings, routes). A condition the builder can't show (``conditions.read``
  gives None) stays a text field marked "Written as script", kept exactly as typed. The
  builder writes into the form's ``StringVar``, so the form's line preview follows it; a row
  that can't be written yet says why under it and ``problem()`` keeps OK off.
- ``TextToolbar``: Bold, Italic, Colour, Pause, Speed, Shake, Wave, Glitch, Player name,
  Variable and More (Size, Go on by itself, Clear formatting) above Say's text field. Each
  puts its tag from ``texttools`` around the selection (asking for a colour, seconds, speed,
  size, strength or variable first); the text's tag mistake shows under it, with a
  one-line preview of the text as the player reads it.
- ``ColourBox``: a swatch, the colour as typed (``white``, ``black``, ``red`` or
  ``#rrggbb``; empty for the game's default) and **Pick…** (the system colour picker).

Imports ``tkinter``, its own package and ``core.constants``; never pygame.
"""

import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from tkinter import font as tkfont
from tkinter import ttk

from engine.core.constants import COLOR_WORDS
from engine.tools.editor import conditions as C
from engine.tools.editor import dialogs
from engine.tools.editor import texttools as T
from engine.tools.editor.fieldwidgets import HEX, ColorField, ask_color
from engine.tools.editor.theme import THEME, TYPE_SCALE, font_families, scale_of

# --- Words ------------------------------------------------------------------------------------

WRITTEN_AS_SCRIPT = "Written as script"
SCRIPT_HINT = "The builder can't show this condition, so it is kept exactly as typed."
USE_BUILDER = "Use the builder instead"
ADD_CHECK = "+ Add a check"
REMOVE_CHECK = "−"
NEEDS_CHECK = "Add a check (or pick Else)."
ALWAYS = "Always"
SCRIPT_MARK = "(script)"
CONDITION_TITLE = "Only show when"
CONDITION_HINT = "No checks: the option always shows."
SUMMARY_CHARS = 30                       # the choice table's condition button, then "…"
SHOWS_AS = "Reads as: "
MORE = "More ▾"
CLEAR_FORMATTING = "Clear formatting"
GAME_COLOUR = "the game's default"
PLAYER_NAME = "Insert player name"
OK = "OK"
CANCEL = "Cancel"

# The "is" menu in words. Has/hasn't reads by kind ("ending … was seen").
OP_WORDS: Mapping[str, str] = {C.EQ: "is", C.NE: "is not", C.GT: "is more than",
                               C.GE: "is at least", C.LT: "is less than", C.LE: "is at most"}
HAS_WORDS: Mapping[str, tuple[str, str]] = {
    C.TIP: ("is unlocked", "is not unlocked"), C.ITEM: ("is held", "is not held"),
    C.ENDING: ("was seen", "was not seen"), C.ROUTE: ("is open", "is not open")}
# A row kind → the name kind whose names its picker offers (none for playthrough).
NAME_KINDS: Mapping[str, str] = {C.VARIABLE: "variable", C.METER: "meter", C.TIP: "tip",
                                 C.ITEM: "item", C.ENDING: "ending", C.ROUTE: "route"}
YES_NO = (C.YES, C.NO)

# What a toolbar value dialog asks: (label, low, high, step, a "none" check box's words, the
# value that check box writes).
_ASK: Mapping[str, tuple[str, float, float, float, str | None, str]] = {
    T.ASK_SECONDS: ("Seconds", 0.1, 30, 0.1, "Wait for a click instead", ""),
    T.ASK_SPEED: ("Speed (1 is the player's speed)", 0.1, 10, 0.1, "Show all at once",
                  "instant"),
    T.ASK_SIZE: ("Size (1 is normal)", 0.5, 2, 0.1, None, ""),
}
STRENGTHS = (("medium", ""), ("small", "small"), ("large", "large"))
VARIABLE_LABEL = "Variable"


def op_words(kind: str) -> list[tuple[str, str]]:
    """``(op, words)`` for ``kind``'s "is" menu."""
    if kind in HAS_WORDS:
        has, hasnt = HAS_WORDS[kind]
        return [(C.HAS, has), (C.HASNT, hasnt)]
    return [(op, OP_WORDS[op]) for op in C.ops_for(kind)]


def condition_label(text: str) -> str:
    """A choice's condition on its button: "Always", the rows in words, or the text with
    "(script)" when the builder can't show it."""
    if not text.strip():
        return ALWAYS
    found = C.read(text)
    shown = C.summary(found) if found is not None and found.rows else " ".join(text.split())
    if len(shown) > SUMMARY_CHARS:
        shown = shown[:SUMMARY_CHARS - 1].rstrip() + "…"
    return shown if found is not None else f"{shown} {SCRIPT_MARK}"


def _error_label(parent: tk.Misc, scale: float) -> ttk.Label:
    return ttk.Label(parent, text="", style="Dialog.Hint.TLabel",
                     foreground=THEME["marker.warning"], wraplength=round(420 * scale),
                     justify="left")


def _tool_style(widget: tk.Misc) -> str:
    """A compact secondary button for the toolbars (24 high)."""
    scale = scale_of(widget)
    style = ttk.Style(widget)
    style.configure("Tool.Secondary.TButton", padding=(round(7 * scale), round(2 * scale)))
    return "Tool.Secondary.TButton"


# --- The condition builder --------------------------------------------------------------------

class _CheckRow:
    """One builder row's widgets; ``origin`` is the row it was read as (None: new)."""

    def __init__(self, builder: "ConditionBuilder", row: C.Row, origin: bool) -> None:
        self.builder = builder
        self.origin = row if origin else None
        self.origin_shown = C.value_text(row.value) if origin else None
        parent = builder.rows_frame
        self.kind = tk.StringVar(parent, value=C.KINDS[row.kind])
        self.name = tk.StringVar(parent, value=row.name)
        self.op = tk.StringVar(parent, value=dict(op_words(row.kind)).get(row.op, ""))
        self.value = tk.StringVar(parent, value=C.value_text(row.value))
        self.kind_box = ttk.Combobox(parent, textvariable=self.kind, values=list(C.KINDS.values()),
                                     state="readonly", width=11)
        self.name_box = ttk.Combobox(parent, textvariable=self.name, width=16)
        self.op_box = ttk.Combobox(parent, textvariable=self.op, state="readonly", width=14)
        self.value_box = ttk.Combobox(parent, textvariable=self.value, width=10)  # yes / no
        self.value_entry = ttk.Entry(parent, textvariable=self.value, width=12)    # a number
        self.remove = ttk.Button(parent, text=REMOVE_CHECK, width=3, takefocus=0,
                                 style=_tool_style(parent),
                                 command=lambda: builder.remove(self))
        self.hint = _error_label(parent, builder.scale)
        self._options()
        self.kind_box.bind("<<ComboboxSelected>>", lambda _e: self._kind_picked())
        for var in (self.name, self.op, self.value):
            var.trace_add("write", lambda *_a: builder.changed())

    @property
    def kind_key(self) -> str:
        label = self.kind.get()
        return next((k for k, v in C.KINDS.items() if v == label), C.VARIABLE)

    def _options(self) -> None:
        kind = self.kind_key
        self.name_box.configure(values=self.builder.names_of(kind))
        self.op_box.configure(values=[words for _op, words in op_words(kind)])
        self.value_box.configure(values=YES_NO if kind == C.VARIABLE else ())

    def _kind_picked(self) -> None:
        kind = self.kind_key
        self._options()
        words = [w for _op, w in op_words(kind)]
        if self.op.get() not in words:
            self.op.set(words[0])
        offered = self.builder.names_of(kind)
        if self.name.get() not in offered:
            self.name.set(offered[0] if offered else "")
        if kind in HAS_WORDS:
            self.value.set("")
        self.builder.grid_rows()
        self.builder.changed()

    def row(self) -> C.Row:
        kind = self.kind_key
        op = next((o for o, w in op_words(kind) if w == self.op.get()), "")
        name = "" if kind == C.PLAYTHROUGH else self.name.get().strip()
        if kind in HAS_WORDS:
            value = ""
        else:
            shown = self.value.get()
            if self.origin is not None and shown == self.origin_shown:
                value = self.origin.value
            elif not shown.strip():
                value = ""
            else:
                value = C.value_from_text(shown)
        return C.Row(kind, name, op, value)

    def widgets(self) -> tuple[tk.Widget, ...]:
        return (self.kind_box, self.name_box, self.op_box, self.value_box, self.value_entry,
                self.remove, self.hint)

    def destroy(self) -> None:
        for widget in self.widgets():
            widget.destroy()


class ConditionBuilder:
    """``var``'s condition as builder rows (module docstring). ``names``: name kind → names;
    ``required``: no rows is a problem (an If needs a check). ``frame`` is the widget."""

    def __init__(self, parent: tk.Misc, var: tk.StringVar, names: Mapping[str, Sequence[str]],
                 *, required: bool = False,
                 on_change: Callable[[], object] | None = None) -> None:
        self.var = var
        self.names = names
        self.required = required
        self.on_change = on_change
        self.scale = scale_of(parent)
        self.frame = ttk.Frame(parent, style="Dialog.TFrame")
        self.condition: C.Condition | None = None
        self.checks: list[_CheckRow] = []
        self._quiet = False
        self.script_frame = ttk.Frame(self.frame, style="Dialog.TFrame")
        self.builder_frame = ttk.Frame(self.frame, style="Dialog.TFrame")
        gap = round(6 * self.scale)
        # Written as script: the text as typed
        ttk.Label(self.script_frame, text=WRITTEN_AS_SCRIPT, style="Dialog.TLabel").pack(
            anchor="w")
        self.script_entry = ttk.Entry(self.script_frame, textvariable=var, width=44)
        self.script_entry.pack(anchor="w", fill="x", pady=(gap // 2, 0))
        ttk.Label(self.script_frame, text=SCRIPT_HINT, style="Dialog.Hint.TLabel",
                  wraplength=round(420 * self.scale), justify="left").pack(
            anchor="w", pady=(gap // 2, 0))
        self.use_builder = ttk.Button(self.script_frame, text=USE_BUILDER,
                                      style="Secondary.TButton", command=self.start_over)
        self.use_builder.pack(anchor="w", pady=(gap, 0))
        # The builder
        head = ttk.Frame(self.builder_frame, style="Dialog.TFrame")
        head.pack(anchor="w", fill="x")
        self.join = tk.StringVar(self.frame, value=C.JOINS[C.ALL])
        self.join_box = ttk.Combobox(head, textvariable=self.join, values=list(C.JOINS.values()),
                                     state="readonly", width=8)
        self.join_label = ttk.Label(head, text="these checks", style="Dialog.TLabel")
        self.join.trace_add("write", lambda *_a: self.changed())
        self.rows_frame = ttk.Frame(self.builder_frame, style="Dialog.TFrame")
        self.rows_frame.pack(anchor="w", fill="x")
        self.add_button = ttk.Button(self.builder_frame, text=ADD_CHECK,
                                     style=_tool_style(self.frame), command=self.add)
        self.add_button.pack(anchor="w", pady=(gap, 0))
        self.problem_label = _error_label(self.builder_frame, self.scale)
        self.problem_label.pack(anchor="w")
        self._head = head
        self.load(var.get())

    # --- names ---------------------------------------------------------------------------

    def names_of(self, kind: str) -> list[str]:
        name_kind = NAME_KINDS.get(kind)
        found = list(self.names.get(name_kind, ())) if name_kind else []
        if kind == C.VARIABLE:
            found = [n for n in found if C.is_variable_name(n)]
        return sorted(dict.fromkeys(found), key=str.casefold)

    # --- reading -------------------------------------------------------------------------

    @property
    def scripted(self) -> bool:
        """True while the condition shows as text ("Written as script")."""
        return self.condition is None

    def load(self, text: str) -> None:
        """Show ``text``: builder rows, or the script field."""
        for check in self.checks:
            check.destroy()
        self.checks = []
        self.condition = C.read(text)
        if self.condition is None:
            self.builder_frame.pack_forget()
            self.script_frame.pack(anchor="w", fill="x")
            return
        self.script_frame.pack_forget()
        self.builder_frame.pack(anchor="w", fill="x")
        self._quiet = True
        self.join.set(C.JOINS[self.condition.join])
        for row in self.condition.rows:
            self.checks.append(_CheckRow(self, row, origin=True))
        if not self.checks and self.required:
            self.checks.append(_CheckRow(self, self._blank(), origin=False))
        self._quiet = False
        self.grid_rows()
        self.changed()

    def _blank(self) -> C.Row:
        offered = self.names_of(C.VARIABLE)
        return C.Row(C.VARIABLE, offered[0] if offered else "", C.EQ, "")

    def start_over(self) -> None:
        """**Use the builder instead**: forget the script text, start with one check."""
        self.var.set("")
        self.load("")
        if not self.checks:
            self.add()

    # --- rows ----------------------------------------------------------------------------

    def grid_rows(self) -> None:
        gap = round(6 * self.scale)
        if len(self.checks) > 1:
            self.join_box.pack(side="left")
            self.join_label.pack(side="left", padx=(gap, 0))
            self._head.pack(anchor="w", fill="x", pady=(0, gap), before=self.rows_frame)
        else:
            self._head.pack_forget()
        for n, check in enumerate(self.checks):
            kind = check.kind_key
            row = 2 * n
            pad = (gap if n else 0, 0)
            check.kind_box.grid(row=row, column=0, sticky="w", pady=pad)
            if kind == C.PLAYTHROUGH:
                check.name_box.grid_remove()
            else:
                check.name_box.grid(row=row, column=1, sticky="w", padx=(gap, 0), pady=pad)
            check.op_box.grid(row=row, column=2, sticky="w", padx=(gap, 0), pady=pad)
            for value in (check.value_box, check.value_entry):
                wanted = check.value_box if kind == C.VARIABLE else check.value_entry
                shown = kind not in HAS_WORDS and value is wanted
                if shown:
                    value.grid(row=row, column=3, sticky="w", padx=(gap, 0), pady=pad)
                else:
                    value.grid_remove()
            check.remove.grid(row=row, column=4, sticky="w", padx=(gap, 0), pady=pad)
            check.hint.grid(row=row + 1, column=0, columnspan=5, sticky="w")
        if len(self.checks) >= C.MAX_ROWS:
            self.add_button.state(["disabled"])
        else:
            self.add_button.state(["!disabled"])

    def add(self) -> None:
        if self.scripted or len(self.checks) >= C.MAX_ROWS:
            return
        self.checks.append(_CheckRow(self, self._blank(), origin=False))
        self.grid_rows()
        self.changed()
        self.checks[-1].name_box.focus_set()

    def remove(self, check: _CheckRow) -> None:
        if check in self.checks:
            self.checks.remove(check)
            check.destroy()
            self.grid_rows()
            self.changed()

    def rows(self) -> list[C.Row]:
        return [check.row() for check in self.checks]

    def join_key(self) -> str:
        return next((k for k, v in C.JOINS.items() if v == self.join.get()), C.ALL)

    # --- writing -------------------------------------------------------------------------

    def row_problems(self) -> list[str | None]:
        return [C.problem(row) for row in self.rows()]

    def problem(self) -> str | None:
        """Why the condition can't be written now, or None."""
        if self.scripted:
            return NEEDS_CHECK if self.required and not self.var.get().strip() else None
        found = next((p for p in self.row_problems() if p), None)
        if found:
            return found
        return NEEDS_CHECK if self.required and not self.checks else None

    def text(self) -> str | None:
        """The condition's text now, or None while a row can't be written."""
        if self.scripted:
            return self.var.get()
        if any(self.row_problems()):
            return None
        assert self.condition is not None
        return C.write(replace(self.condition, rows=tuple(self.rows()), join=self.join_key()))

    def changed(self) -> None:
        if self._quiet:
            return
        if not self.scripted:
            for check, why in zip(self.checks, self.row_problems(), strict=True):
                check.hint.configure(text=why or "")
                if why:
                    check.hint.grid()
                else:
                    check.hint.grid_remove()
            text = self.text()
            if text is not None and text != self.var.get():
                self.var.set(text)
            self.problem_label.configure(
                text=NEEDS_CHECK if self.required and not self.checks else "")
        if self.on_change is not None:
            self.on_change()

    def summary(self) -> str:
        return condition_label(self.var.get())


class ConditionDialog:
    """A choice's "Only show when" (the builder in a small dialog). ``result``: the new
    condition text after OK ("" for always), None after Cancel."""

    def __init__(self, parent: tk.Misc, text: str, names: Mapping[str, Sequence[str]]) -> None:
        self.result: str | None = None
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(CONDITION_TITLE)
        body, scale = dialogs._body(dialog)
        self.var = tk.StringVar(dialog, value=text)
        ttk.Label(body, text=CONDITION_HINT, style="Dialog.Hint.TLabel").pack(
            anchor="w", pady=(0, round(8 * scale)))
        self.builder = ConditionBuilder(body, self.var, names, on_change=self._changed)
        self.builder.frame.pack(anchor="w", fill="x")
        self.buttons = dialogs._buttons(dialog, body, (OK, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        if not self.builder.scripted and not self.builder.checks:
            self.builder.add()
        self._changed()

    def _changed(self) -> None:
        if hasattr(self, "buttons"):
            ok = self.builder.problem() is None
            self.buttons[0].state(["!disabled"] if ok else ["disabled"])

    def _pick(self, index: int) -> None:
        if index == 0:
            if self.builder.problem() is not None:
                return
            text = self.builder.text()
            self.result = (text if text is not None else "").strip()
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> str | None:
        first = self.builder.checks[0].kind_box if self.builder.checks \
            else self.builder.script_entry
        dialogs._run(parent, self.dialog, first)
        return self.result


def ask_condition(parent: tk.Misc, text: str, names: Mapping[str, Sequence[str]]
                  ) -> str | None:
    """The "Only show when" dialog, modal: the new condition text, or None (Cancel)."""
    return ConditionDialog(parent, text, names).run(parent)


# --- The Say text toolbar ---------------------------------------------------------------------

class ValueDialog:
    """What a toolbar button asks before it puts its tag in: seconds, speed or size (a
    spinner, maybe with a "none" check box), a strength, or a variable. ``result``: the
    tag's value ("" for none), None after Cancel."""

    def __init__(self, parent: tk.Misc, button: T.TextButton,
                 names: Mapping[str, Sequence[str]]) -> None:
        self.button = button
        self.result: str | None = None
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(button.label)
        body, scale = dialogs._body(dialog)
        gap = round(8 * scale)
        ttk.Label(body, text=button.doc.summary, style="Dialog.Hint.TLabel",
                  wraplength=round(360 * scale), justify="left").pack(anchor="w")
        row = ttk.Frame(body, style="Dialog.TFrame")
        row.pack(anchor="w", fill="x", pady=(gap, 0))
        self.var = tk.StringVar(dialog, value=button.value or "")
        self.none = tk.StringVar(dialog, value="")
        self.none_box: ttk.Checkbutton | None = None
        ask = button.ask
        if ask in _ASK:
            label, lo, hi, step, none_words, _none_value = _ASK[ask]
            ttk.Label(row, text=label, style="Dialog.TLabel").pack(side="left")
            self.input: tk.Widget = ttk.Spinbox(row, from_=lo, to=hi, increment=step,
                                                textvariable=self.var, width=6,
                                                format="%.1f")
            self.var.set(button.value or "")
            self.input.pack(side="left", padx=(gap, 0))
            if none_words is not None:
                self.none_box = ttk.Checkbutton(body, text=none_words, variable=self.none,
                                                onvalue="1", offvalue="",
                                                style="Dialog.TCheckbutton")
                self.none_box.pack(anchor="w", pady=(gap, 0))
        elif ask == T.ASK_STRENGTH:
            ttk.Label(row, text="Strength", style="Dialog.TLabel").pack(side="left")
            self.var.set(STRENGTHS[0][0])
            self.input = ttk.Combobox(row, textvariable=self.var, state="readonly", width=10,
                                      values=[words for words, _v in STRENGTHS])
            self.input.pack(side="left", padx=(gap, 0))
        else:                                                   # a variable
            ttk.Label(row, text=VARIABLE_LABEL, style="Dialog.TLabel").pack(side="left")
            offered = sorted(dict.fromkeys(names.get("variable", ())), key=str.casefold)
            self.var.set(offered[0] if offered else "")
            self.input = ttk.Combobox(row, textvariable=self.var, values=offered, width=18)
            self.input.pack(side="left", padx=(gap, 0))
        self.problem = _error_label(body, scale)
        self.problem.pack(anchor="w", pady=(round(4 * scale), 0))
        self.buttons = dialogs._buttons(dialog, body, (OK, CANCEL), self._pick)
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))
        self.input.bind("<Return>", lambda _e: self._pick(0) or "break")
        for var in (self.var, self.none):
            var.trace_add("write", lambda *_a: self._changed())
        self._changed()

    def value(self) -> str:
        ask = self.button.ask
        if ask in _ASK and self.none.get():
            return _ASK[ask][5]
        typed = self.var.get().strip()
        if ask == T.ASK_STRENGTH:
            return dict(STRENGTHS).get(typed, "")
        if ask in _ASK and typed:
            try:
                return f"{float(typed):g}"
            except ValueError:
                return typed
        return typed

    def why_not(self) -> str | None:
        value = self.value()
        if self.button.ask == T.ASK_VARIABLE and not value:
            return "Pick a variable."
        if self.button.ask in (T.ASK_SPEED, T.ASK_SIZE) and not value:
            return "Fill in a number."
        return T.check_value(self.button.tag, value)

    def _changed(self) -> None:
        if self.none_box is not None:
            self.input.state(["disabled"] if self.none.get() else ["!disabled"])
        why = self.why_not()
        self.problem.configure(text=why or "")
        self.buttons[0].state(["disabled"] if why else ["!disabled"])

    def _pick(self, index: int) -> None:
        if index == 0:
            if self.why_not() is not None:
                return
            self.result = self.value()
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> str | None:
        dialogs._run(parent, self.dialog, self.input)
        return self.result


def ask_tag_value(parent: tk.Misc, button: T.TextButton,
                  names: Mapping[str, Sequence[str]]) -> str | None:
    """What ``button`` asks for (``button.ask``): a colour from the system picker, else a
    ``ValueDialog``. None: cancelled."""
    if button.ask == T.ASK_COLOUR:
        return ask_color(parent, button.value)
    return ValueDialog(parent, button, names).run(parent)


def _font(widget: tk.Misc, weight: str = "normal", slant: str = "roman") -> tkfont.Font:
    family, _w = font_families(widget)["ui"]
    return tkfont.Font(root=widget, family=family, weight=weight, slant=slant,
                       size=-round(TYPE_SCALE["body"][0] * scale_of(widget)))


class TextToolbar:
    """The text-tag buttons for ``entry`` (its text is ``var``), and the "Reads as" preview
    and tag problem under it (``below``). ``asker(parent, button, names)`` answers what a
    button asks (``ask_tag_value``; a test may swap it)."""

    def __init__(self, parent: tk.Misc, entry: ttk.Entry, var: tk.StringVar, *,
                 names: Mapping[str, Sequence[str]]) -> None:
        self.entry, self.var, self.names = entry, var, names
        self.asker: Callable[[tk.Misc, T.TextButton, Mapping[str, Sequence[str]]],
                             str | None] = ask_tag_value
        scale = self.scale = scale_of(parent)
        self.frame = ttk.Frame(parent, style="Dialog.TFrame")
        style = _tool_style(parent)
        self.buttons: dict[str, ttk.Button] = {}
        gap = round(4 * scale)
        self._fonts = {"bold": _font(parent, weight="bold"),
                       "italic": _font(parent, slant="italic")}
        ttk.Style(parent).configure("Bold.Tool.Secondary.TButton", font=self._fonts["bold"])
        ttk.Style(parent).configure("Italic.Tool.Secondary.TButton",
                                    font=self._fonts["italic"])
        from engine.tools.editor.playbar import Tooltip     # Tk only; playbar imports dialogs
        self.tips: dict[str, object] = {}
        for button in T.BUTTONS:
            if button.more:
                continue
            look = {"bold": "Bold." + style, "italic": "Italic." + style}.get(button.key, style)
            widget = ttk.Button(self.frame, text=button.label, style=look, takefocus=0,
                                width=-2, command=lambda key=button.key: self.press(key))
            widget.pack(side="left", padx=(0, gap))
            self.buttons[button.key] = widget
            self.tips[button.key] = Tooltip(widget, button.doc.summary)
        self.more = ttk.Button(self.frame, text=MORE, style=style, takefocus=0, width=-2,
                               command=self._post_more)
        self.more.pack(side="left")
        self.menu = tk.Menu(self.frame, tearoff=False)
        for button in T.BUTTONS:
            if button.more:
                self.menu.add_command(
                    label=button.label,
                    command=lambda key=button.key: self.press(key, self._selection))
        self.menu.add_separator()
        self.menu.add_command(label=CLEAR_FORMATTING,
                              command=lambda: self.clear(self._selection))
        self.preview = ttk.Frame(parent, style="Dialog.TFrame")
        ttk.Label(self.preview, text=SHOWS_AS, style="Dialog.Hint.TLabel").pack(side="left")
        back = THEME["widget.background"]
        self.preview_text = tk.Text(self.preview, height=1, width=1, wrap="none",
                                    font=_font(parent), background=back,
                                    foreground=THEME["foreground"], borderwidth=0,
                                    highlightthickness=0, relief="flat", takefocus=0,
                                    cursor="arrow", padx=0, pady=0)
        self.preview_text.pack(side="left", fill="x", expand=True)
        self._fonts["both"] = _font(parent, weight="bold", slant="italic")
        self.preview_text.tag_configure("b", font=self._fonts["bold"])
        self.preview_text.tag_configure("i", font=self._fonts["italic"])
        self.preview_text.tag_configure("bi", font=self._fonts["both"])
        self.preview_text.tag_configure("fx", underline=True)     # shake, wave, glitch
        self.preview_text.configure(state="disabled")
        self.problem = _error_label(parent, scale)
        self._selection: tuple[int, int] | None = None        # as More opened
        var.trace_add("write", lambda *_a: self.refresh())
        self.refresh()

    def _post_more(self) -> None:
        self._selection = self.selection()      # the menu may take the selection
        self.menu.tk_popup(self.more.winfo_rootx(),
                           self.more.winfo_rooty() + self.more.winfo_height())

    def selection(self) -> tuple[int, int]:
        """The selection (or the caret) a button acts on."""
        entry = self.entry
        try:
            if entry.selection_present():
                return int(entry.index("sel.first")), int(entry.index("sel.last"))
        except tk.TclError:
            pass
        at = int(entry.index("insert"))
        return at, at

    def show(self, edit: T.TextEdit) -> None:
        """Put ``edit`` in the field: its text, then its selection (a caret when empty)."""
        self.var.set(edit.text)
        entry = self.entry
        entry.selection_clear()
        if edit.start != edit.end:
            entry.selection_range(edit.start, edit.end)
        entry.icursor(edit.end)
        self.problem.configure(text=edit.problem or "")
        try:
            entry.focus_set()
        except tk.TclError:
            pass

    def press(self, key: str, where: tuple[int, int] | None = None) -> T.TextEdit | None:
        """Button ``key`` on the selection (``where``: the one More saw): ask what it needs
        (before asking: a dialog may take the selection), then put its tag in (a pair tag
        on the same text again comes off). None: cancelled."""
        button = T.button(key)
        if button is None:
            return None
        start, end = where if where is not None else self.selection()
        value: str | None = None
        if button.ask is not None:
            value = self.asker(self.entry, button, self.names)
            if value is None:
                return None
        edit = T.toggle(self.var.get(), start, end, button.tag, value)
        self.show(edit)
        return edit

    def clear(self, where: tuple[int, int] | None = None) -> T.TextEdit:
        """Clear formatting: the selection's tags off (all the text's, with none)."""
        start, end = where if where is not None else self.selection()
        edit = T.strip_tags(self.var.get(), start, end) if start != end \
            else T.strip_tags(self.var.get())
        self.show(edit)
        return edit

    def refresh(self) -> None:
        text = self.var.get()
        shown = self.preview_text
        shown.configure(state="normal")
        shown.delete("1.0", "end")
        for chunk, styles, colour in preview_runs(text):
            tags = []
            if "b" in styles or "i" in styles:
                tags.append("bi" if {"b", "i"} <= styles else "b" if "b" in styles else "i")
            if styles & _MOVING:
                tags.append("fx")
            if colour is not None:
                tag = "c" + colour
                shown.tag_configure(tag, foreground=colour)
                tags.append(tag)
            shown.insert("end", chunk, tuple(tags))
        shown.configure(state="disabled")
        self.problem.configure(text=T.problem(text) or "")

    def shown(self) -> str:
        """The preview's words as the player reads them."""
        return self.preview_text.get("1.0", "end-1c")


_MOVING = frozenset(("shake", "wave", "glitch"))


def preview_runs(text: str) -> list[tuple[str, frozenset[str], str | None]]:
    """``text`` as the player reads it, in runs: (words, the pair tags on them, their
    colour or None). Tags show as ``texttools.preview`` shows them."""
    runs: list[tuple[str, frozenset[str], str | None]] = []
    at = 0
    pieces: list[tuple[int, int]] = []
    for tag in T._tags(text):                       # noqa: SLF001  (the toolbar's own model)
        if at < tag.start:
            pieces.append((at, tag.start))
        pieces.append((tag.start, tag.end))
        at = tag.end
    if at < len(text):
        pieces.append((at, len(text)))
    for start, end in pieces:
        chunk = T.preview(text[start:end])
        if not chunk:
            continue
        active = T.active_tags(text, start)
        styles = frozenset(a.name for a in active)
        colour = next((colour_hex(a.value or "") for a in reversed(active)
                       if a.name == "color"), None)
        runs.append((chunk, styles, colour))
    return runs


# --- Colours ----------------------------------------------------------------------------------

def colour_hex(text: str) -> str | None:
    """``white``/``black``/``red`` or ``#rrggbb`` (with or without ``#``) as ``#rrggbb``."""
    word = text.strip().strip('"')
    if word in COLOR_WORDS:
        return COLOR_WORDS[word].lower()
    if word and not word.startswith("#"):
        word = "#" + word
    return word.lower() if HEX.fullmatch(word) else None


class ColourBox(ColorField):
    """A form's colour field: ``ColorField``'s swatch, text and **Pick…**, with the text in
    the form's ``var`` as typed (a colour word, ``#rrggbb``, or empty for the game's
    default)."""

    def __init__(self, parent: tk.Misc, var: tk.StringVar) -> None:
        self.form_var = var
        super().__init__(parent, colour_hex(var.get()), allow_none=True, none_text=GAME_COLOUR,
                         scale=scale_of(parent))
        self.frame.configure(style="Dialog.TFrame")
        self.hint.configure(style="Dialog.Hint.TLabel")
        self.var = var
        self.entry.configure(textvariable=var, width=10)
        var.trace_add("write", lambda *_a: self._draw())
        self._draw()

    def _show(self) -> None:
        if hasattr(self, "form_var") and self.var is self.form_var:
            self._draw()
        else:
            super()._show()

    def _typed(self) -> None:
        self._draw()

    def _draw(self) -> None:
        colour = colour_hex(self.form_var.get())
        self.value = colour
        canvas, side = self.swatch, self.side
        canvas.delete("all")
        if colour is not None:
            canvas.create_rectangle(0, 0, side + 1, side + 1, fill=colour, outline="")
        else:
            canvas.create_line(2, side - 2, side - 2, 2, fill=THEME["muted"], width=1)
        empty = not self.form_var.get().strip()
        self.hint.configure(text=GAME_COLOUR if empty else "")

    def pick(self) -> None:
        if str(self.button.cget("state")) == "disabled":
            return
        chosen = ask_color(self.swatch, colour_hex(self.form_var.get()))
        if chosen is not None:
            self.form_var.set(chosen)


__all__ = ["ALWAYS", "ColourBox", "ConditionBuilder", "ConditionDialog", "PLAYER_NAME",
           "TextToolbar", "ValueDialog", "WRITTEN_AS_SCRIPT", "ask_condition", "ask_tag_value",
           "colour_hex", "condition_label", "op_words"]
