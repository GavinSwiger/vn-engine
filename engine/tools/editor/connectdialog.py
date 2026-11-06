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
- ``setup_claude_code`` / ``setup_claude_desktop``: the **Set up** buttons. The first runs
  ``claude mcp add --scope user`` as an argument list (no shell); the second adds this game's
  entry to Claude Desktop's settings file, keeping the rest and a ``.bak`` of the old file.
- ``open_connect_dialog(win)``: the menu row (the open one is raised).

Looks like Studio's other dialogs (``dialogs``: padding, buttons, title bar; ``theme``
tokens; captions as in Build game). Imports ``tkinter``, ``core`` and its own package.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from engine.core.childcmd import server_prefix
from engine.core.paths import engine_root, slugify
from engine.tools.editor import dialogs
from engine.tools.editor.theme import THEME, dark_title_bar, scale_of

# --- Texts (01 §6.5, final) --------------------------------------------------------------------

MENU = "Connect an AI app…"
TITLE = "Connect an AI app"
HEADING = "USE THIS GAME IN AN AI APP"
INTRO = ("Claude Code, Claude Desktop and other apps that support MCP can read this game, "
         "check it and suggest changes. They run on your plan with that app (for Claude, "
         "your Pro or Max plan), so no API key or API credit is needed. Studio sends "
         "nothing itself.")
WRITE_OPTION = "Let the app change script files (it shows each change first)"
CLAUDE_CODE = "CLAUDE CODE"
CLAUDE_CODE_HOW = "Click Set up, or run this in a terminal:"
CLAUDE_DESKTOP = "CLAUDE DESKTOP"
CLAUDE_DESKTOP_HOW = "Click Set up, or add this under Settings ▸ Developer ▸ Edit config:"
OTHER_APPS = "OTHER APPS"
NO_UNDO = "Studio can't undo changes an app makes. Save your work first."
COPY = "Copy"
SET_UP = "Set up"
SETTING_UP = "Setting up…"
CODE_DONE = ("Done. Restart Claude Code (in VS Code: Developer: Reload Window), then ask it "
             "about your game.")
CODE_MISSING = ("Claude Code isn't installed on this computer. Install it from "
                "claude.com/claude-code, then click Set up again.")
CODE_FAILED = "Claude Code couldn't add it: {reason}. Copy the command and run it in a terminal."
CODE_UNSAFE = ("Studio can't start Claude Code safely with these folder names. Copy the command "
               "and run it in a terminal.")
DESKTOP_DONE = "Done. Quit Claude Desktop fully (also from the tray), then open it again."
DESKTOP_MISSING = ("Claude Desktop isn't installed on this computer. Install it from "
                   "claude.com/download, open it once, then click Set up again.")
DESKTOP_FAILED = "Couldn't change Claude Desktop's settings: {reason}. Copy the text instead."
DESKTOP_BAD_FILE = "its settings file isn't valid JSON, so Studio left it alone"
DESKTOP_CONFIG = "claude_desktop_config.json"
SETUP_TIMEOUT_S = 60
CLOSE = "Close"
SERVER_PREFIX = "vn-"
READ_ONLY = "--read-only"
SERVER_FLAGS = ("-P",)                 # the dev server's interpreter flag (no unsafe path)

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
    args = [*server_prefix(SERVER_FLAGS), "assist-mcp", str(game)]
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
    prefix = " ".join(server_prefix(SERVER_FLAGS))
    # PowerShell drops a bare -- before claude sees it, and claude then reads -P as its own
    # option; a quoted "--" reaches claude from PowerShell and cmd alike.
    dashes = quoted("--", windows=True) if (os.name == "nt" if windows is None else windows) \
        else "--"
    claude_code = (f"claude mcp add --scope user {name} -e PYTHONPATH={quoted(engine, windows=windows)} "
                   f"{dashes} {quoted(python, windows=windows)} {prefix} assist-mcp "
                   f"{quoted(str(game), windows=windows)}{flag}")
    desktop = desktop_config(name, python, server_args(game, write=write), engine)
    other = (f"Command: {python}\n"
             f"Arguments: {prefix} assist-mcp {quoted(str(game), windows=windows)}{flag}\n"
             f"Environment: PYTHONPATH={engine}")
    return Snippets(name, claude_code, desktop, other)


def claude_code_argv(claude: str, python: str, engine: str, game: Path | str, *,
                     write: bool = True) -> list[str]:
    """``claude mcp add`` as an argument list (no shell, so nothing needs quoting). User
    scope: the server is there in every folder Claude Code is opened in."""
    return [claude, "mcp", "add", "--scope", "user", server_name(Path(game)),
            "-e", f"PYTHONPATH={engine}", "--", str(python),
            *server_args(Path(game), write=write)]


# cmd.exe reads these even inside quotes, so a .cmd launcher can't take them safely.
_CMD_SPECIAL = frozenset('%^&|<>!"\n\r')


def setup_claude_code(python: str, engine: str, game: Path | str, *, write: bool = True,
                      which: Callable[[str], str | None] = shutil.which,
                      run: Callable[..., Any] = subprocess.run) -> tuple[bool, str]:
    """**Set up** for Claude Code: replace any earlier user-scope entry for this game, then
    add this one. Returns (done, the text to show)."""
    claude = which("claude")
    if claude is None:
        return False, CODE_MISSING
    argv = claude_code_argv(claude, python, engine, game, write=write)
    if claude.lower().endswith((".cmd", ".bat")) and any(
            char in _CMD_SPECIAL for arg in argv[1:] for char in arg):
        return False, CODE_UNSAFE
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        run([claude, "mcp", "remove", "--scope", "user", server_name(Path(game))],
            capture_output=True, timeout=SETUP_TIMEOUT_S, creationflags=flags)
        done = run(argv, capture_output=True, timeout=SETUP_TIMEOUT_S, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, CODE_FAILED.format(reason=type(exc).__name__)
    if done.returncode != 0:
        said = (done.stderr or done.stdout or b"").decode("utf-8", "replace").strip()
        reason = said.splitlines()[-1][:200] if said else f"exit status {done.returncode}"
        return False, CODE_FAILED.format(reason=reason)
    return True, CODE_DONE


def desktop_config_path(environ: Mapping[str, str] | None = None,
                        platform: str | None = None) -> Path | None:
    """Claude Desktop's settings file, or None when Claude Desktop isn't installed (its
    folder is missing). Windows also checks the Microsoft Store install's folder."""
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        roaming = environ.get("APPDATA")
        if roaming and (Path(roaming) / "Claude").is_dir():
            return Path(roaming) / "Claude" / DESKTOP_CONFIG
        local = environ.get("LOCALAPPDATA")
        if local:
            for package in sorted((Path(local) / "Packages").glob("Claude_*")):
                folder = package / "LocalCache" / "Roaming" / "Claude"
                if folder.is_dir():
                    return folder / DESKTOP_CONFIG
        return None
    if platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "Claude"
        return folder / DESKTOP_CONFIG if folder.is_dir() else None
    return None


def setup_claude_desktop(python: str, engine: str, game: Path | str, *, write: bool = True,
                         path: Path | None = None) -> tuple[bool, str]:
    """**Set up** for Claude Desktop: add (or replace) this game's entry in its settings
    file, keeping everything else. The old file is kept beside it as ``….json.bak``."""
    path = desktop_config_path() if path is None else path
    if path is None:
        return False, DESKTOP_MISSING
    try:
        old = path.read_bytes() if path.exists() else b""
        try:
            data = json.loads(old.decode("utf-8-sig")) if old.strip() else {}
        except (UnicodeDecodeError, ValueError):
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            return False, DESKTOP_FAILED.format(reason=DESKTOP_BAD_FILE)
        data.setdefault("mcpServers", {})[server_name(Path(game))] = {
            "command": str(python), "args": server_args(Path(game), write=write),
            "env": {"PYTHONPATH": str(engine)}}
        if old:
            path.with_name(path.name + ".bak").write_bytes(old)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    except OSError as exc:
        return False, DESKTOP_FAILED.format(reason=exc.strerror or type(exc).__name__)
    return True, DESKTOP_DONE


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
        self.setups: list[ttk.Button] = []            # Claude Code, Claude Desktop
        self.statuses: list[ttk.Label] = []
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
            setup = self._button(head, SET_UP, lambda i=index: self.set_up(i), primary=True)
            setup.pack(side="right")
            self.setups.append(setup)
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
        if how is not None:
            status = self._label(body, "", "ConnectHint.TLabel")
            status.pack(anchor="w", pady=(self.px(4), 0))
            self.statuses.append(status)

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

    def set_up(self, index: int) -> None:
        """**Set up** (0: Claude Code, 1: Claude Desktop), off the Tk thread; the result
        shows under the section."""
        work = (setup_claude_code, setup_claude_desktop)[index]
        args = (str(self.python), str(self.engine), self.game)
        write = bool(self.write.get())
        result: list[tuple[bool, str]] = []
        self.setups[index].state(["disabled"])
        self.statuses[index].configure(text=SETTING_UP)
        threading.Thread(target=lambda: result.append(work(*args, write=write)),
                         daemon=True).start()

        def poll() -> None:
            if not self.alive:
                return
            if not result:
                self.dialog.after(100, poll)
                return
            self.setups[index].state(["!disabled"])
            self.statuses[index].configure(text=result[0][1])
            self._fit()

        self.dialog.after(100, poll)

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


__all__ = ["CLAUDE_CODE", "CLAUDE_DESKTOP", "CLOSE", "COPY", "SET_UP", "claude_code_argv",
           "desktop_config_path", "setup_claude_code", "setup_claude_desktop", "ConnectDialog", "HEADING",
           "INTRO", "MENU", "NO_UNDO", "OTHER_APPS", "READ_ONLY", "Snippets", "TITLE",
           "WRITE_OPTION", "desktop_config", "open_connect_dialog", "quoted", "server_args",
           "server_name", "snippets", "studio_python"]
