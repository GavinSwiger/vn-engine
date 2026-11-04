"""Help ▸ Connect an AI app… (F48 ``01-design.md`` §6.5, PR-F48-13; ``04-technical.md``
§3.2; SEC-F48-08; AC-F48-28).

Why this module exists: Claude Code, Claude Desktop and other MCP apps start the assistant's
server themselves (``python -m engine assist-mcp``, F48 W1), so the author needs the exact
command for this computer. The dialog shows it three ways, each with **Copy**, built from
Studio's own interpreter (``sys.executable``), the engine folder (``engine_root()``) and the
game folder. Every form is the safe launch form: ``-P`` keeps the app's working folder off
Python's module path and ``PYTHONPATH`` names only the engine folder, so nothing planted in
the working folder or the game folder is imported (SEC-F48-08). Unticking "Let the app change
script files" adds ``--read-only``. The server name is ``vn-`` plus the game folder's slug.

The full paths appear only in this dialog (and on the clipboard when the author copies): this
module logs nothing (01 §6.5).

- ``snippets(python, engine, game, *, write=True) -> Snippets``: the three texts (pure).
- ``open_connect_dialog(win)``: the menu row (the open one is raised).

Looks like Studio's other dialogs (``dialogs``: padding, buttons, title bar; ``theme``
tokens; captions as in Build game). Imports ``tkinter``, ``core`` and its own package.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from engine.core.paths import engine_root, slugify
from engine.tools.editor import dialogs
from engine.tools.editor.theme import THEME, dark_title_bar, scale_of

# --- Texts (01 §6.5, final) --------------------------------------------------------------------

MENU = "Connect an AI app…"
TITLE = "Connect an AI app"
HEADING = "USE THIS GAME IN AN AI APP"
INTRO = ("Claude Code, Claude Desktop and other apps that support MCP can read this game, "
         "check it and suggest changes. They use your account with that app; Studio sends "
         "nothing itself.")
WRITE_OPTION = "Let the app change script files (it shows each change first)"
CLAUDE_CODE = "CLAUDE CODE"
CLAUDE_CODE_HOW = "Run this in a terminal:"
CLAUDE_DESKTOP = "CLAUDE DESKTOP"
CLAUDE_DESKTOP_HOW = "Settings ▸ Developer ▸ Edit config, add this, then restart Claude:"
OTHER_APPS = "OTHER APPS"
NO_UNDO = "Studio can't undo changes an app makes. Save your work first."
COPY = "Copy"
CLOSE = "Close"
SERVER_PREFIX = "vn-"
READ_ONLY = "--read-only"

# --- Look (px at 100 %) -----------------------------------------------------------------------

WIDTH_PX = 640
PADDING = dialogs.PADDING
SECTION_GAP = 20
CAPTION_GAP = 8
CODE_PAD = (8, 6)


@dataclass(frozen=True)
class Snippets:
    """The three setups, as shown and as copied."""

    server: str
    claude_code: str
    claude_desktop: str
    other: str

    def all(self) -> tuple[str, str, str]:
        return (self.claude_code, self.claude_desktop, self.other)


def server_name(game: Path) -> str:
    """``vn-`` + the game folder's slug (``core.paths.slugify``)."""
    return SERVER_PREFIX + slugify(Path(game).name)


def quoted(text: str, *, windows: bool | None = None) -> str:
    """``text`` as one shell word in double quotes, as 01 §6.5 shows it; on macOS and Linux
    a value a POSIX shell would expand inside double quotes is single-quoted instead."""
    windows = os.name == "nt" if windows is None else windows
    if not windows and any(char in text for char in '"$`\\!'):
        return shlex.quote(text)
    return f'"{text}"'


def server_args(game: Path, *, write: bool = True) -> list[str]:
    """The server's arguments after the interpreter."""
    args = ["-P", "-m", "engine", "assist-mcp", str(game)]
    return args if write else [*args, READ_ONLY]


def desktop_config(name: str, python: str, args: list[str], engine: str) -> str:
    """Claude Desktop's ``mcpServers`` entry as JSON, laid out as 01 §6.5 shows it (the
    arguments on one line)."""
    def text(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)

    return "\n".join((
        "{",
        '  "mcpServers": {',
        f"    {text(name)}: {{",
        f'      "command": {text(python)},',
        f'      "args": [{", ".join(text(arg) for arg in args)}],',
        f'      "env": {{ "PYTHONPATH": {text(engine)} }}',
        "    }",
        "  }",
        "}"))


def snippets(python: Path | str, engine: Path | str, game: Path | str, *,
             write: bool = True, windows: bool | None = None) -> Snippets:
    """01 §6.5's three setups for ``game`` served by ``python`` with ``PYTHONPATH`` =
    ``engine`` only; ``write`` False adds ``--read-only``."""
    python, engine, game = str(python), str(engine), Path(game)
    name = server_name(game)
    flag = "" if write else f" {READ_ONLY}"
    claude_code = (f"claude mcp add {name} -e PYTHONPATH={quoted(engine, windows=windows)} -- "
                   f"{quoted(python, windows=windows)} -P -m engine assist-mcp "
                   f"{quoted(str(game), windows=windows)}{flag}")
    desktop = desktop_config(name, python, server_args(game, write=write), engine)
    other = (f"Command: {python}\n"
             f"Arguments: -P -m engine assist-mcp {quoted(str(game), windows=windows)}{flag}\n"
             f"Environment: PYTHONPATH={engine}")
    return Snippets(name, claude_code, desktop, other)


def studio_python() -> Path:
    """The interpreter Studio runs on: the one the app should start."""
    return Path(sys.executable)


def open_connect_dialog(win: Any) -> "ConnectDialog | None":
    """Help ▸ Connect an AI app…: the dialog (the open one is raised)."""
    if getattr(win, "closed", False):
        return None
    dialog = getattr(win, "connect_dialog", None)
    if dialog is not None and dialog.alive:
        dialog.dialog.lift()
        return dialog
    dialog = win.connect_dialog = ConnectDialog(win)
    dialog.show()
    return dialog


def _styles(root: tk.Misc, fonts: dict) -> None:
    """The dialog's ttk styles on Studio's tokens (as Build game's)."""
    style = ttk.Style(root)
    back = THEME["widget.background"]
    style.configure("ConnectCaption.TLabel", background=back, foreground=THEME["muted"],
                    font=fonts["caption"])
    style.configure("ConnectStrong.TLabel", background=back,
                    foreground=THEME["strongForeground"], font=fonts["bodyStrong"])
    style.configure("ConnectHint.TLabel", background=back, foreground=THEME["muted"],
                    font=fonts["small"])


class ConnectDialog:
    """The dialog over ``win`` (built hidden; ``show`` maps it). ``codes`` are the three
    snippet texts and ``copies`` their Copy buttons, in 01 §6.5's order."""

    def __init__(self, win: Any, *, python: Path | None = None,
                 engine: Path | None = None) -> None:
        self.win = win
        self.alive = True
        self.python = python if python is not None else studio_python()
        self.engine = engine if engine is not None else engine_root()
        self.game = Path(win.paths.root)
        dialog = self.dialog = dialogs._dialog(win.root)
        dialog.title(TITLE)
        self.scale = scale_of(dialog)
        self.fonts = win.fonts
        _styles(dialog, self.fonts)
        self.wrap = self.px(WIDTH_PX - 2 * PADDING)
        body = self.body = ttk.Frame(dialog, padding=self.px(PADDING), style="Dialog.TFrame")
        body.pack(fill="both", expand=True)
        ttk.Frame(body, width=self.wrap, height=0, style="Dialog.TFrame").pack(anchor="w")
        self._label(body, HEADING, "ConnectStrong.TLabel").pack(anchor="w")
        self._label(body, INTRO).pack(anchor="w", pady=(self.px(CAPTION_GAP), 0))
        self.write = tk.BooleanVar(dialog, value=True)
        self.write_box = ttk.Checkbutton(body, text=WRITE_OPTION, variable=self.write,
                                         command=self.refresh, style="Dialog.TCheckbutton")
        self.write_box.pack(anchor="w", pady=(self.px(12), 0))
        self.codes: list[tk.Text] = []
        self.copies: list[ttk.Button] = []
        for index, (caption, how) in enumerate(((CLAUDE_CODE, CLAUDE_CODE_HOW),
                                                (CLAUDE_DESKTOP, CLAUDE_DESKTOP_HOW),
                                                (OTHER_APPS, None))):
            self._section(body, index, caption, how)
        row = ttk.Frame(body, style="Dialog.TFrame")
        row.pack(fill="x", pady=(self.px(SECTION_GAP), 0))
        self.close_button = self._button(row, CLOSE, self.close, primary=True)
        self.close_button.pack(side="right", anchor="s")
        self._label(row, NO_UNDO, "ConnectHint.TLabel",
                    wrap=self.wrap - self.px(dialogs.BUTTON_MIN_WIDTH + 16)).pack(
            side="left", anchor="w")
        self.refresh()
        for key in ("<Return>", "<KP_Enter>", "<Escape>"):
            dialog.bind(key, lambda _e: self.close())
        dialog.protocol("WM_DELETE_WINDOW", self.close)

    # --- Helpers --------------------------------------------------------------------------------

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def _label(self, parent: tk.Misc, text: str, style: str = "Dialog.TLabel", *,
               wrap: int | None = None) -> ttk.Label:
        return ttk.Label(parent, text=text, style=style, justify="left",
                         wraplength=self.wrap if wrap is None else wrap)

    def _button(self, parent: tk.Misc, text: str, command: Any, *,
                primary: bool = False) -> ttk.Button:
        zero = max(1, self.fonts["body"].measure("0"))
        return ttk.Button(parent, text=text, command=command,
                          width=-max(1, -(-self.px(dialogs.BUTTON_MIN_WIDTH) // zero)),
                          style="TButton" if primary else "Secondary.TButton")

    def _section(self, body: ttk.Frame, index: int, caption: str, how: str | None) -> None:
        head = ttk.Frame(body, style="Dialog.TFrame")
        head.pack(anchor="w", fill="x", pady=(self.px(SECTION_GAP), self.px(CAPTION_GAP)))
        self._label(head, caption, "ConnectCaption.TLabel", wrap=0).pack(side="left")
        if how is not None:
            self._label(head, how, wrap=self.wrap - self.px(120)).pack(
                side="left", padx=(self.px(12), 0))
        frame = ttk.Frame(body, style="Dialog.TFrame")
        frame.pack(fill="x")
        font = self.fonts["codeSmall"]
        code = tk.Text(frame, height=1, width=1, wrap="char", font=font,
                       background=THEME["card.background"],
                       foreground=THEME["editor.foreground"], borderwidth=0,
                       highlightthickness=0, relief="flat", padx=self.px(CODE_PAD[0]),
                       pady=self.px(CODE_PAD[1]), cursor="xterm",
                       selectbackground=THEME["editor.selection"],
                       inactiveselectbackground=THEME["editor.selection"])
        code.grid(row=0, column=0, sticky="nsew")
        copy = self._button(frame, COPY, lambda i=index: self.copy(i))
        copy.grid(row=0, column=1, sticky="ne", padx=(self.px(8), 0))
        for key in ("<Return>", "<KP_Enter>"):          # Enter on Copy copies; elsewhere closes
            copy.bind(key, lambda _e, i=index: (self.copy(i), "break")[1])
        frame.columnconfigure(0, weight=1)
        code.bind("<Configure>", lambda _e, c=code: self._fit_box(c))
        self.codes.append(code)
        self.copies.append(copy)

    def _code_width(self) -> int:
        """The snippet boxes' text width in px (the body less Copy, its gap and padding)."""
        copy = self.px(dialogs.BUTTON_MIN_WIDTH) + self.px(8)
        return max(1, self.wrap - copy - 2 * self.px(CODE_PAD[0]))

    # --- State ----------------------------------------------------------------------------------

    def snippets(self) -> Snippets:
        return snippets(self.python, self.engine, self.game, write=bool(self.write.get()))

    def texts(self) -> tuple[str, str, str]:
        """The three snippets as shown."""
        return tuple(code.get("1.0", "end-1c") for code in self.codes)  # type: ignore[return-value]

    def refresh(self) -> None:
        """Show the snippets for the check box's state (unticked: ``--read-only``)."""
        font: tkfont.Font = self.fonts["codeSmall"]
        width = self._code_width()
        for code, text in zip(self.codes, self.snippets().all()):
            code.configure(state="normal")
            code.delete("1.0", "end")
            code.insert("1.0", text)
            code.configure(state="disabled")
            lines = sum(max(1, math.ceil(font.measure(line) / width))
                        for line in text.split("\n"))
            code.configure(height=lines)
        if self.dialog.winfo_viewable():
            self._fit()

    def _fit(self) -> None:
        """Once laid out at full width: each box's height to its real display lines (the
        measured estimate can be a line off). Not while a box is still narrow: then every
        character would count as a line."""
        self.dialog.update_idletasks()
        for code in self.codes:
            self._fit_box(code)

    def _fit_box(self, code: tk.Text) -> None:
        """One box's ``_fit``; also run whenever the box's size changes (``<Configure>``), so
        a box laid out late still ends at its real height."""
        if not self.alive or code.winfo_width() < self._code_width() // 2:
            return
        try:
            found = code.count("1.0", "end", "displaylines", "update")
        except tk.TclError:
            return
        lines = found[0] if isinstance(found, tuple) else found
        if lines and int(code.cget("height")) != lines:
            code.configure(height=lines)

    def copy(self, index: int) -> None:
        """**Copy**: snippet ``index`` onto the clipboard, as shown."""
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(self.snippets().all()[index])

    def close(self) -> None:
        if not self.alive:
            return
        self.alive = False
        try:
            self.dialog.grab_release()
        except tk.TclError:
            pass
        self.dialog.destroy()
        if getattr(self.win, "connect_dialog", None) is self:
            self.win.connect_dialog = None

    def show(self) -> None:
        """Map the dialog, centered and modal (no waiting: Close ends it)."""
        d = self.dialog
        dialogs._center(d, self.win.root.winfo_toplevel())
        d.deiconify()
        self._fit()
        dialogs._center(d, self.win.root.winfo_toplevel())
        dark_title_bar(d)
        self.close_button.focus_set()
        try:
            d.grab_set()
        except tk.TclError:
            pass


__all__ = ["CLAUDE_CODE", "CLAUDE_DESKTOP", "CLOSE", "COPY", "ConnectDialog", "HEADING",
           "INTRO", "MENU", "NO_UNDO", "OTHER_APPS", "READ_ONLY", "Snippets", "TITLE",
           "WRITE_OPTION", "desktop_config", "open_connect_dialog", "quoted", "server_args",
           "server_name", "snippets", "studio_python"]
