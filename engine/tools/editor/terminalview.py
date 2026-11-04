"""Studio's Terminal editor (F56 ``01`` §9, ``04`` §2, §8 W2): Database ▸ Minigame data ▸
Terminals.

Why this module exists: an author writes a terminal's commands without code. Top to bottom:
Welcome text (4 lines), Prompt and "Unknown command" reply, "Can't yet" reply; then the
commands list (Command / In help / Ends, with + Add command, ✕, ▲, ▼) beside the selected
command's details:

- **Command**, **Also accepts** (one per line), **Reply**;
- **In help**: Always, Never (secret), After a tip (then a tip pick-list);
- **Works only after**: "any time" and the other commands;
- **Password** ("Capitals don't matter."), **Learned from tip** (disabled while the password
  is empty), **Unlocks tip** ("(none)" and the declared tips);
- **Ends the session**: No / Yes, goal reached / Yes, goal not reached.

Every change goes through ``Editor.changed``: written at once when the game accepts it, else
"Not saved yet" with the rules' sentence (``terminaldata.problem``, F47's rule). The reusable
pieces are ``minigameview``'s (``Editor``, ``_Entry``, ``_Combo``, ``_Message``); the list is
``EvidenceEditor``'s pattern, the inspector ``RoomEditor``'s (04 OQ-1: copied, not shared).
"""

import tkinter as tk
from dataclasses import replace
from tkinter import ttk
from typing import Any, Final

from engine.tools.editor import minigamedata as mg
from engine.tools.editor.minigameview import Editor, _Combo, _Entry, _Message
from engine.tools.editor.terminaldata import TerminalCommand, TerminalData

WELCOME: Final = "Welcome text"
PROMPT: Final = "Prompt"
UNKNOWN: Final = "Unknown command reply"
NOT_YET: Final = "\"Can't yet\" reply"
COMMANDS: Final = "Commands"
COLUMNS: Final = (("command", "Command", 180), ("help", "In help", 80), ("ends", "Ends", 60))
ADD: Final = "+ Add command"
REMOVE, UP, DOWN = "✕", "▲", "▼"
COMMAND: Final = "Command"
ALSO: Final = "Also accepts"
ALSO_HINT: Final = "(one per line)"
REPLY: Final = "Reply"
IN_HELP: Final = "In help"
HELP_ALWAYS, HELP_NEVER, HELP_TIP = "Always", "Never (secret)", "After a tip"
AFTER: Final = "Works only after"
ANY_TIME: Final = "any time"
PASSWORD: Final = "Password"
PASSWORD_HINT: Final = "Capitals don't matter."
KNOWN_FROM: Final = "Learned from tip"
UNLOCK: Final = "Unlocks tip"
ENDS: Final = "Ends the session"
ENDS_LABELS: Final = (("No", None), ("Yes, goal reached", "goal"),
                      ("Yes, goal not reached", "out"))
NONE: Final = "(none)"
NEW_COMMAND: Final = "new command"


def _help_word(c: TerminalCommand) -> str:
    if c.help is True:
        return "Always"
    if c.help is False:
        return "Never"
    return "Tip"


def _ends_word(c: TerminalCommand) -> str:
    return {"goal": "Goal", "out": "Out"}.get(c.ends or "", "–")


class TerminalEditor(Editor):
    """One terminal (module docstring). ``self.model`` is a ``TerminalData``."""

    kind = mg.TERMINAL

    def __init__(self, host: Any, parent: tk.Misc, ds: mg.DataSet, model: object) -> None:
        super().__init__(host, parent, ds, model)
        px = self.px
        self.selected = 0
        top = ttk.Frame(self.frame)
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)
        data: TerminalData = model                               # type: ignore[assignment]
        ttk.Label(top, text=WELCOME).grid(row=0, column=0, sticky="nw", padx=(0, px(8)))
        self.welcome = _Message(top, data.welcome, height=4, width=56,
                                on_change=lambda t: self._top(welcome=t))
        self.welcome.widget.grid(row=0, column=1, columnspan=3, sticky="we")
        ttk.Label(top, text=PROMPT).grid(row=1, column=0, sticky="w", pady=(px(6), 0))
        self.prompt = _Entry(top, data.prompt, width=10, on_change=lambda t: self._top(prompt=t))
        self.prompt.widget.grid(row=1, column=1, sticky="w", pady=(px(6), 0))
        ttk.Label(top, text=UNKNOWN).grid(row=1, column=2, sticky="w", padx=(px(12), px(8)))
        self.unknown = _Entry(top, data.unknown or "", width=30,
                              on_change=lambda t: self._top(unknown=t or None))
        self.unknown.widget.grid(row=1, column=3, sticky="we")
        ttk.Label(top, text=NOT_YET).grid(row=2, column=0, sticky="w", pady=(px(6), 0))
        self.not_yet = _Entry(top, data.not_yet or "", width=40,
                              on_change=lambda t: self._top(not_yet=t or None))
        self.not_yet.widget.grid(row=2, column=1, columnspan=3, sticky="w", pady=(px(6), 0))
        body = ttk.Frame(self.frame)
        body.pack(fill="both", expand=True, pady=(px(10), 0))
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        ttk.Label(left, text=COMMANDS).pack(anchor="w")
        self.tree = ttk.Treeview(left, columns=[c for c, _, _ in COLUMNS], show="headings",
                                 height=10, selectmode="browse")
        for key, title, width in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=px(width))
        self.tree.pack(fill="y", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._picked(), add="+")
        bar = ttk.Frame(left)
        bar.pack(anchor="w", pady=(px(4), 0))
        self.add_button = ttk.Button(bar, text=ADD, style="Secondary.TButton",
                                     command=self.add)
        self.add_button.pack(side="left")
        for text, command in ((REMOVE, self.remove), (UP, lambda: self.move(-1)),
                              (DOWN, lambda: self.move(1))):
            ttk.Button(bar, text=text, width=3, style="Secondary.TButton",
                       command=command).pack(side="left", padx=(px(4), 0))
        self.side = ttk.Frame(body)
        self.side.pack(side="left", fill="both", expand=True, padx=(px(16), 0))
        self.status.pack(anchor="w", pady=(px(8), 0))
        self.fields: dict[str, Any] = {}
        self.rebuild()

    # -- the model --

    @property
    def data(self) -> TerminalData:
        return self.model                                        # type: ignore[return-value]

    def _top(self, **changes: object) -> None:
        self.changed(replace(self.data, **changes))

    def command(self) -> TerminalCommand | None:
        rows = self.data.commands
        return rows[self.selected] if 0 <= self.selected < len(rows) else None

    def set_command(self, **changes: object) -> None:
        c = self.command()
        if c is None:
            return
        self.changed(self.data.with_command(self.selected, replace(c, **changes)),
                     rebuild=True)

    def add(self) -> None:
        taken = {c.command for c in self.data.commands}
        name, n = NEW_COMMAND, 2
        while name in taken:
            name, n = f"{NEW_COMMAND} {n}", n + 1
        rows = (*self.data.commands, TerminalCommand(name))
        self.selected = len(rows) - 1
        self.changed(replace(self.data, commands=rows), rebuild=True)

    def remove(self) -> None:
        rows = list(self.data.commands)
        if not 0 <= self.selected < len(rows):
            return
        del rows[self.selected]
        self.selected = max(0, min(self.selected, len(rows) - 1))
        self.changed(replace(self.data, commands=tuple(rows)), rebuild=True)

    def move(self, step: int) -> None:
        rows = list(self.data.commands)
        i, j = self.selected, self.selected + step
        if not (0 <= i < len(rows) and 0 <= j < len(rows)):
            return
        rows[i], rows[j] = rows[j], rows[i]
        self.selected = j
        self.changed(replace(self.data, commands=tuple(rows)), rebuild=True)

    def _picked(self) -> None:
        chosen = self.tree.selection()
        if chosen:
            index = int(chosen[0])
            if index != self.selected:
                self.selected = index
                self.show_side()

    # -- drawing --

    def rebuild(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.data.commands):
            self.tree.insert("", "end", iid=str(i), values=(c.command, _help_word(c),
                                                            _ends_word(c)))
        if self.data.commands:
            self.selected = max(0, min(self.selected, len(self.data.commands) - 1))
            self.tree.selection_set(str(self.selected))
        self.show_side()

    def show_side(self) -> None:
        for child in self.side.winfo_children():
            child.destroy()
        self.fields = {}
        c = self.command()
        if c is None:
            return
        px = self.px
        grid = ttk.Frame(self.side)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        r = [0]
        tips = [n for n, _ in self.lookups.tips] if hasattr(self.lookups, "tips") else []

        def row(label: str, widget: Any, extra: Any = None) -> None:
            ttk.Label(grid, text=label).grid(row=r[0], column=0, sticky="nw",
                                             padx=(0, px(8)), pady=(px(4), 0))
            widget.grid(row=r[0], column=1, sticky="w", pady=(px(4), 0))
            if extra is not None:
                extra.grid(row=r[0], column=2, sticky="w", padx=(px(8), 0), pady=(px(4), 0))
            r[0] += 1

        f = self.fields
        f["command"] = _Entry(grid, c.command, width=28,
                              on_change=lambda t: self.set_command(command=t.strip()))
        row(COMMAND, f["command"].widget)
        f["also"] = _Message(grid, "\n".join(c.also), height=3, width=28,
                             on_change=lambda t: self.set_command(
                                 also=tuple(line.strip() for line in t.split("\n")
                                            if line.strip())))
        row(ALSO, f["also"].widget, ttk.Label(grid, text=ALSO_HINT))
        f["reply"] = _Message(grid, c.reply, height=4, width=40,
                              on_change=lambda t: self.set_command(reply=t))
        row(REPLY, f["reply"].widget)
        helped = HELP_ALWAYS if c.help is True else HELP_NEVER if c.help is False else HELP_TIP
        f["help"] = _Combo(grid, (HELP_ALWAYS, HELP_NEVER, HELP_TIP), helped, readonly=True,
                           on_change=self._help)
        f["help_tip"] = _Combo(grid, tips, c.help if type(c.help) is str else "",
                               readonly=True, width=18,
                               on_change=lambda t: self.set_command(help=t or True))
        if type(c.help) is not str:
            f["help_tip"].widget.configure(state="disabled")
        row(IN_HELP, f["help"].widget, f["help_tip"].widget)
        others = [o.command for i, o in enumerate(self.data.commands) if i != self.selected]
        f["after"] = _Combo(grid, [ANY_TIME, *others], c.after or ANY_TIME, readonly=True,
                            width=22, on_change=lambda t: self.set_command(
                                after=None if t == ANY_TIME else t))
        row(AFTER, f["after"].widget)
        f["password"] = _Entry(grid, c.password or "", width=20,
                               on_change=lambda t: self.set_command(
                                   password=t or None,
                                   known_from=c.known_from if t else None))
        row(PASSWORD, f["password"].widget, ttk.Label(grid, text=PASSWORD_HINT))
        f["known_from"] = _Combo(grid, [NONE, *tips], c.known_from or NONE, readonly=True,
                                 width=22, on_change=lambda t: self.set_command(
                                     known_from=None if t == NONE else t))
        if not c.password:
            f["known_from"].widget.configure(state="disabled")
        row(KNOWN_FROM, f["known_from"].widget)
        f["unlock"] = _Combo(grid, [NONE, *tips], c.unlock or NONE, readonly=True, width=22,
                             on_change=lambda t: self.set_command(
                                 unlock=None if t == NONE else t))
        row(UNLOCK, f["unlock"].widget)
        ends = next(label for label, value in ENDS_LABELS if value == c.ends)
        f["ends"] = _Combo(grid, [label for label, _ in ENDS_LABELS], ends, readonly=True,
                           width=22, on_change=lambda t: self.set_command(
                               ends=dict(ENDS_LABELS)[t]))
        row(ENDS, f["ends"].widget)

    def _help(self, text: str) -> None:
        if text == HELP_ALWAYS:
            self.set_command(help=True)
        elif text == HELP_NEVER:
            self.set_command(help=False)
        else:
            tips = [n for n, _ in self.lookups.tips]
            self.set_command(help=tips[0] if tips else True)


__all__ = ["TerminalEditor"]
