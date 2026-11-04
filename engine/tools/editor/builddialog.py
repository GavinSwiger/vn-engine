"""File ▸ Build game… (F42 ``01-design.md`` §6, PR-F42-09..17, -21, -23; ``04-technical.md``
§3.2 W2/W3; ``07`` I-11, I-12).

Why this module exists: a non-programmer turns their game into a folder players can run,
without a terminal. One modal dialog shows one view at a time: **Setup** (game details, where
to save, zip) → **Progress** (steps in plain words) → **Finished** (Open folder / Run the
game) or **Failed** (the message and its fix; Try again). The words, checks and plans come
from ``buildmodel`` (pure); this module only lays out widgets and wires the runners.

- ``open_build_dialog(win)``: the menu row and Ctrl+Shift+B (off while a build runs).
- **Build**: ``REPLACE_ASK`` when an earlier build is at the computed name (then
  ``--replace``); the changed details go into ``config.toml`` with ``win.apply_plan`` (one
  undo step); every open file is saved (``win.save_all``, which arms full checks); *Save
  to* and the zip choice go to ``.studio/build.json`` (``buildprefs``); then the build child
  starts (``BuildRunner``, joined to the window's poll loop with ``win.join_runner``).
- The relayed check's result is applied as a check run, so Problems fill (``B_ERRORS``).
- **Cancel build** stops the child's whole tree (``BuildRunner.cancel``); the dialog shows
  "Stopping…", then ``CANCELLED``.
- **Open folder** / **Run the game** use Studio's own computed ``<Save to>/<folder>`` after
  the marker test (``buildmodel.open_targets``), never a path from a report (I-11). Run
  starts the exe from an argument list with the build folder as working directory.
- **Install build tool** (D2) runs ``InstallRunner`` (pinned, hashed pip) with its output in
  the Setup view.
- ``build_running(win)``: the close guard (``CLOSE_WHILE_BUILDING``) in ``window.on_close``.

``make_runner``, ``make_installer``, ``tool_status``, ``open_folder``, ``run_game``,
``choose_folder``, ``choose_icon``, ``clock``, ``ask`` and ``show_error`` are module names so
tests replace them.

Imports ``tkinter``, its own package and the shared ``tools.build`` modules; never pygame.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from engine.core.paths import GamePaths, engine_data_dir
from engine.script.assetgroups import CONFIG_REF
from engine.tools.build import names, procs, texts
from engine.tools.editor import buildmodel, buildprefs, dialogs, icons
from engine.tools.editor.buildrunner import (
    DONE as ROW_DONE,
    FAILED as ROW_FAILED,
    RUNNING as ROW_RUNNING,
    BuildEvent,
    BuildRunner,
    BuildState,
    InstallEvent,
    InstallRunner,
)
from engine.tools.editor.checker import CheckEvent, CheckState
from engine.tools.editor.dialogs import ask, show_error
from engine.tools.editor.scriptedit import Refuse
from engine.tools.editor.theme import THEME, dark_title_bar, scale_of
from engine.tools.editor.views import set_entry_enabled, thumbnail_step

# --- Words (01 §6.3 come from tools.build.texts; these are the dialog's own) -------------------

TITLE = "Build game"
CAPTION_DETAILS = "GAME DETAILS"
CAPTION_WHERE = "WHERE"
LABEL_NAME = "Name"
LABEL_VERSION = "Version"
LABEL_ID = "Game ID"
LABEL_ICON = "Icon"
LABEL_FOR = "For"
LABEL_SAVE_TO = "Save to"
ENGINE_ICON = "The engine's icon"
CHOOSE = "Choose…"
USE_DEFAULT = "Use default"
BROWSE = "Browse…"
BUILD = "Build"
CANCEL = "Cancel"
CANCEL_BUILD = "Cancel build"
STOPPING = "Stopping…"
OPEN_FOLDER = "Open folder"
RUN_GAME = "Run the game"
CLOSE = "Close"
TRY_AGAIN = "Try again"
BACK = "Back"
SHOW_LIST = "Show list"
SHOW_DETAILS = "Show details"
HIDE = "Hide"
COPY = "Copy"
INSTALL = "Install build tool"
INSTALLING = "Installing the build tool… This takes a minute or two."
INSTALLED = "The build tool is installed. You can build now."
INSTALL_FAILED = ("The build tool couldn't be installed. Check your internet connection and "
                  "try again; the lines below say what went wrong.")
INSTALL_DIDNT_START = "The build tool couldn't be installed: {reason}"
NO_PNGS = ("Your game folder has no PNG images yet. Add one with File ▸ Add files…, then "
           "choose it here.")
PICK_ICON_TITLE = "Choose an icon"
PICK_ICON_ASK = "PNG images in your game folder:"
SAVE_TO_TITLE = "Save the build in"
CONFIG_NOT_WRITTEN = ("Studio couldn't write the game details into config.toml. Save or "
                      "close config.toml, then build again.")
OPEN_FAILED = "Windows couldn't open it: {reason}"
FOR_LINUX = "Linux 64-bit (this computer)"

WIDTH_PX = 560                  # 01 §6.1: the dialog's width at 100 %
PADDING = 20
LABEL_PX = 72                   # the field labels' column
THUMB_PX = 24
LIST_LINES = 8                  # Show list / Show details
KEY_LINES = 3                   # F48: key warnings shown as lines; more go in a list
INSTALL_LINES = 6
TICK_MS = 1000                  # the elapsed time changes once a second
FIELD_ORDER = ("name", "version", "id", buildmodel.FIELD_ICON, buildmodel.FIELD_SAVE_TO)
TOOL_KEYS = ("B_NO_TOOL", "B_TOOL_VERSION")

SETUP, PROGRESS, FINISHED, FAILED, CANCELLED = (
    "setup", "progress", "finished", "failed", "cancelled")


# --- Seams tests replace ------------------------------------------------------------------------

def make_runner(game_root: Path) -> Any:
    """The window's build runner (tests pass a fake child)."""
    return BuildRunner(game_root)


def make_installer(game_root: Path) -> Any:
    return InstallRunner(game_root)


def tool_status() -> procs.ToolStatus:
    importlib.invalidate_caches()               # a pip install just now must be seen
    return procs.tool_status()


clock: Callable[[], float] = time.monotonic


def open_folder(folder: Path) -> None:
    """Open a real folder in the OS file manager (I-11: the caller checked it)."""
    if sys.platform == "win32":
        os.startfile(str(folder))               # type: ignore[attr-defined]  (a folder: Explorer)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(folder)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_game(exe: Path, folder: Path) -> None:
    """Start the built game: an argument list (no shell), the build folder as the working
    directory, ``PYTHON*`` left out of its environment (I-11, SEC-F42-04)."""
    kwargs: dict = {"cwd": str(folder), "env": procs.child_env(), "shell": False,
                    "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    subprocess.Popen([str(exe)], **kwargs)


def choose_folder(parent: tk.Misc, initial: str) -> str | None:
    """**Browse…**: the OS folder picker."""
    start = initial if initial and os.path.isdir(initial) else None
    picked = filedialog.askdirectory(parent=parent, title=SAVE_TO_TITLE, initialdir=start,
                                     mustexist=False)
    return picked or None


def choose_icon(parent: tk.Misc, refs: Sequence[str], current: str | None) -> str | None:
    """**Choose…**: a list of the game folder's PNGs; the picked ref, or None."""
    return _IconPicker(parent, refs, current).run(parent)


# --- The window's runners -----------------------------------------------------------------------

def runner_for(win: Any) -> Any:
    """The window's build runner, made and joined to its poll loop on first use."""
    runner = getattr(win, "build_runner", None)
    if runner is None:
        runner = win.build_runner = make_runner(win.paths.root)
        win.join_runner(runner, lambda events: _on_build_events(win, events))
    return runner


class _JoinedInstaller:
    """``InstallRunner`` as a joined runner (``poll`` and ``stop``)."""

    def __init__(self, runner: Any) -> None:
        self.runner = runner

    def poll(self) -> list:
        return self.runner.poll()

    def stop(self) -> None:
        self.runner.cancel()


def installer_for(win: Any) -> Any:
    installer = getattr(win, "build_installer", None)
    if installer is None:
        installer = win.build_installer = make_installer(win.paths.root)
        win.join_runner(_JoinedInstaller(installer),
                        lambda events: _on_install_events(win, events))
    return installer


def build_running(win: Any) -> bool:
    """A build (or its cancel) is under way in ``win``."""
    runner = getattr(win, "build_runner", None)
    return bool(runner is not None and runner.running)


def _dialog_of(win: Any) -> "BuildDialog | None":
    dialog = getattr(win, "build_dialog", None)
    return dialog if dialog is not None and dialog.alive else None


def _on_build_events(win: Any, events: list) -> None:
    """Each poll tick: the events to the dialog; the menu entry and **Build** follow the
    runner (it stops running at the child's end of output, which brings no event)."""
    running = build_running(win)
    changed = running != getattr(win, "build_running_shown", None)
    if not events and not changed:
        return
    win.build_running_shown = running
    dialog = _dialog_of(win)
    if dialog is not None:
        dialog.on_events(events)
        if changed and dialog.view == SETUP:
            dialog._changed()
    else:                                       # the dialog is gone: Problems still fill
        for event in events:
            _apply_check(win, event)
    update_menu(win)


def _on_install_events(win: Any, events: list) -> None:
    dialog = _dialog_of(win)
    if events and dialog is not None:
        dialog.on_install_events(events)


def _apply_check(win: Any, event: BuildEvent) -> None:
    """The build's relayed check, applied as a check run (Problems, markers, names)."""
    if event.state is BuildState.CHECK and event.check is not None:
        win.apply_check_events([CheckEvent(CheckState.DONE, event.check.serial,
                                           result=event.check)])


def update_menu(win: Any) -> None:
    """File ▸ Build game… is off while a build runs (UI-F42-01)."""
    menu = getattr(win, "file_menu", None)
    if menu is None or getattr(win, "closed", False):
        return
    try:
        set_entry_enabled(menu, texts.MENU, not build_running(win))
    except tk.TclError:
        pass


def open_build_dialog(win: Any) -> "BuildDialog | None":
    """File ▸ Build game… / Ctrl+Shift+B: the dialog (the open one is raised)."""
    if getattr(win, "closed", False):
        return None
    dialog = _dialog_of(win)
    if dialog is not None:
        dialog.dialog.lift()
        return dialog
    if build_running(win):
        return None
    dialog = win.build_dialog = BuildDialog(win)
    dialog.show()
    return dialog


# --- Look -----------------------------------------------------------------------------------------

def _styles(root: tk.Misc, fonts: dict) -> None:
    """The dialog's ttk styles on Studio's tokens (08 §3, §4)."""
    style = ttk.Style(root)
    back = THEME["widget.background"]
    style.configure("BuildCaption.TLabel", background=back, foreground=THEME["muted"],
                    font=fonts["caption"])
    style.configure("BuildHint.TLabel", background=back, foreground=THEME["muted"],
                    font=fonts["small"])
    style.configure("BuildError.TLabel", background=back, foreground=THEME["marker.error"],
                    font=fonts["small"])
    style.configure("BuildWarn.TLabel", background=back, foreground=THEME["marker.warning"],
                    font=fonts["small"])
    style.configure("BuildStrong.TLabel", background=back,
                    foreground=THEME["strongForeground"], font=fonts["bodyStrong"])
    style.configure("BuildCode.TLabel", background=back, foreground=THEME["foreground"],
                    font=fonts["codeSmall"])
    style.configure("Build.Horizontal.TProgressbar", troughcolor=THEME["input.background"],
                    background=THEME["button.background"],
                    bordercolor=THEME["input.background"],
                    lightcolor=THEME["button.background"],
                    darkcolor=THEME["button.background"])


class BuildDialog:
    """The Build game dialog over ``win`` (built hidden; ``show`` maps it). ``view`` is the
    view on screen: ``setup``, ``progress``, ``finished``, ``failed`` or ``cancelled``."""

    def __init__(self, win: Any) -> None:
        self.win = win
        self.game_root = Path(win.paths.root)
        self.prefs = buildprefs.read_prefs(self.game_root)
        self.view = SETUP
        self.alive = True
        self.installing = False
        self.install_state: str | None = None   # installing / installed / failed
        self.tool = tool_status()
        self.started: tuple[buildmodel.BuildFields, Path, str] | None = None
        self.messages: dict[str, str] = {}
        self.targets: tuple[Path, Path] | None = None
        self._tick_id: str | None = None
        dialog = self.dialog = dialogs._dialog(win.root)
        dialog.title(TITLE)
        self.scale = scale_of(dialog)
        self.fonts = win.fonts
        _styles(dialog, self.fonts)
        self.wrap = self.px(WIDTH_PX - 2 * PADDING)
        self.body = ttk.Frame(dialog, padding=self.px(PADDING), style="Dialog.TFrame")
        self.body.pack(fill="both", expand=True)
        # Every view is at least 560 px wide at 100 % (01 §6.1), so the dialog keeps its size.
        ttk.Frame(self.body, width=self.wrap, height=0, style="Dialog.TFrame").pack(anchor="w")
        self._images: dict[str, tk.PhotoImage] = {}
        fields = buildmodel.initial_fields(self._config_text(), self.game_root, self.prefs)
        self._build_setup(fields)
        self.page: ttk.Frame | None = None
        for key in ("<Return>", "<KP_Enter>"):
            dialog.bind(key, self._on_enter)
        dialog.bind("<Escape>", lambda _e: self._on_escape())
        dialog.protocol("WM_DELETE_WINDOW", self._on_escape)
        self._changed()

    # --- Helpers --------------------------------------------------------------------------------

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def icon(self, name: str, color: str, size: int = 16) -> tk.PhotoImage:
        key = f"{name}:{color}:{size}"
        if key not in self._images:
            self._images[key] = icons.photo(self.dialog, name, self.px(size), color)
        return self._images[key]

    def _ask(self, message: str, buttons: Sequence[str], *, escape: int,
             default: int) -> int:
        """``ask`` over this dialog; the question took the grab, so take it back."""
        try:
            return ask(self.dialog, message, buttons, escape=escape, default=default)
        finally:
            self._regrab()

    def _error(self, message: str) -> None:
        try:
            show_error(self.dialog, message)
        finally:
            self._regrab()

    def _regrab(self) -> None:
        if self.alive:
            try:
                self.dialog.grab_set()
            except tk.TclError:
                pass

    def _config_text(self) -> str:
        try:
            record = self.win.record_for(CONFIG_REF)
            return record.widget.get("1.0", "end-1c")
        except Exception:                       # no config.toml: the defaults
            return ""

    def _label(self, parent: tk.Misc, text: str = "", style: str = "Dialog.TLabel", *,
               wrap: int | None = None, **options: Any) -> ttk.Label:
        return ttk.Label(parent, text=text, style=style, justify="left",
                         wraplength=self.wrap if wrap is None else wrap, **options)

    def _button(self, parent: tk.Misc, text: str, command: Callable[[], object], *,
                primary: bool = False) -> ttk.Button:
        zero = max(1, self.fonts["body"].measure("0"))
        return ttk.Button(parent, text=text, command=command,
                          width=-max(1, -(-self.px(dialogs.BUTTON_MIN_WIDTH) // zero)),
                          style="TButton" if primary else "Secondary.TButton")

    def _button_row(self, parent: tk.Misc,
                    buttons: Sequence[tuple[str, Callable[[], object], bool]]
                    ) -> list[ttk.Button]:
        row = ttk.Frame(parent, style="Dialog.TFrame")
        row.pack(anchor="e", pady=(self.px(PADDING), 0))
        made = []
        for index, (text, command, primary) in enumerate(buttons):
            button = self._button(row, text, command, primary=primary)
            button.pack(side="left", padx=(self.px(dialogs.BUTTON_GAP) if index else 0, 0))
            made.append(button)
        return made

    def _caption(self, parent: tk.Misc, text: str, *, first: bool = False) -> None:
        self._label(parent, text, "BuildCaption.TLabel").pack(
            anchor="w", pady=(0 if first else self.px(20), self.px(8)))

    def _list_box(self, parent: tk.Misc, lines: Sequence[str]) -> ttk.Frame:
        """An 8-line read-only ``codeSmall`` text with **Copy** (Show list / Show details)."""
        frame = ttk.Frame(parent, style="Dialog.TFrame")
        text = tk.Text(frame, height=min(LIST_LINES, max(1, len(lines))), wrap="none",
                       font=self.fonts["codeSmall"], background=THEME["card.background"],
                       foreground=THEME["editor.foreground"], borderwidth=0,
                       highlightthickness=0, relief="flat", padx=self.px(8), pady=self.px(6),
                       width=1, selectbackground=THEME["editor.selection"],
                       inactiveselectbackground=THEME["editor.selection"])
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        if len(lines) > LIST_LINES:
            scroll.grid(row=0, column=1, sticky="ns")
        frame.columnconfigure(0, weight=1)
        copy = self._button(frame, COPY, lambda: self._copy("\n".join(lines)))
        copy.grid(row=1, column=0, columnspan=2, sticky="e", pady=(self.px(8), 0))
        frame.text = text                       # type: ignore[attr-defined]  (tests)
        frame.copy = copy                       # type: ignore[attr-defined]
        return frame

    def _copy(self, text: str) -> None:
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(text)

    def _toggle(self, button: ttk.Button, box: ttk.Frame, label: str,
                after: tk.Widget) -> None:
        if box.winfo_manager():
            box.pack_forget()
            button.configure(text=label)
        else:
            box.pack(anchor="w", fill="x", pady=(self.px(8), 0), after=after)
            button.configure(text=HIDE)

    # --- Setup ----------------------------------------------------------------------------------

    def _build_setup(self, fields: buildmodel.BuildFields) -> None:
        d = self.dialog
        self.title_var = tk.StringVar(d, value=fields.title)
        self.version_var = tk.StringVar(d, value=fields.version)
        self.id_var = tk.StringVar(d, value=fields.app_id)
        self.save_var = tk.StringVar(d, value=fields.save_to)
        self.zip_var = tk.BooleanVar(d, value=fields.zip)
        self.icon_ref: str | None = fields.icon
        setup = self.setup = ttk.Frame(self.body, style="Dialog.TFrame")
        setup.pack(fill="both", expand=True)
        self._label(setup, texts.INTRO).pack(anchor="w")
        self._caption(setup, CAPTION_DETAILS)
        grid = ttk.Frame(setup, style="Dialog.TFrame")
        grid.pack(anchor="w", fill="x")
        grid.columnconfigure(0, minsize=self.px(LABEL_PX))
        grid.columnconfigure(1, weight=1)
        gap, hint_gap = self.px(8), self.px(4)
        self.hints: dict[str, ttk.Label] = {}
        self.inputs: dict[str, tk.Widget] = {}
        hint_wrap = self.wrap - self.px(LABEL_PX)

        def row(index: int, label: str, key: str, widget: tk.Widget,
                extra: tk.Widget | None = None) -> None:
            top = 0 if index == 0 else gap
            ttk.Label(grid, text=label, style="Dialog.TLabel").grid(
                row=2 * index, column=0, sticky="w", pady=(top, 0))
            widget.grid(row=2 * index, column=1, sticky="ew" if extra is None else "w",
                        pady=(top, 0))
            if extra is not None:
                extra.grid(row=2 * index, column=2, sticky="e", padx=(gap, 0), pady=(top, 0))
            hint = self._label(grid, "", "BuildHint.TLabel", wrap=hint_wrap, compound="left")
            hint.grid(row=2 * index + 1, column=1, columnspan=2, sticky="w",
                      pady=(hint_gap, 0))
            self.hints[key] = hint

        self.name_entry = ttk.Entry(grid, textvariable=self.title_var, width=40)
        row(0, LABEL_NAME, "name", self.name_entry)
        self.version_entry = ttk.Entry(grid, textvariable=self.version_var, width=16)
        row(1, LABEL_VERSION, "version", self.version_entry, ttk.Frame(grid,
                                                                         style="Dialog.TFrame"))
        self.id_entry = ttk.Entry(grid, textvariable=self.id_var, width=24)
        self.slug_button = self._button(grid, "", self._use_slug)
        row(2, LABEL_ID, "id", self.id_entry, self.slug_button)
        icon_row = ttk.Frame(grid, style="Dialog.TFrame")
        self._images["blank"] = tk.PhotoImage(master=d, width=self.px(THUMB_PX),
                                              height=self.px(THUMB_PX))
        self.thumb = tk.Label(icon_row, background=THEME["card.background"],
                              image=self._images["blank"], borderwidth=0,
                              highlightthickness=0)
        self.thumb.pack(side="left")
        self.icon_label = self._label(icon_row, "", wrap=0)
        self.icon_label.pack(side="left", padx=(gap, 0))
        self.default_button = self._button(icon_row, USE_DEFAULT, self._use_default)
        self.default_button.pack(side="right")
        self.choose_button = self._button(icon_row, CHOOSE, self._choose_icon)
        self.choose_button.pack(side="right", padx=(0, gap))
        row(3, LABEL_ICON, buildmodel.FIELD_ICON, icon_row)
        grid.grid_slaves(row=6, column=1)[0].grid_configure(columnspan=2, sticky="ew")
        self.inputs = {"name": self.name_entry, "version": self.version_entry,
                       "id": self.id_entry, buildmodel.FIELD_ICON: self.choose_button}

        self._caption(setup, CAPTION_WHERE)
        where = ttk.Frame(setup, style="Dialog.TFrame")
        where.pack(anchor="w", fill="x")
        where.columnconfigure(0, minsize=self.px(LABEL_PX))
        where.columnconfigure(1, weight=1)
        ttk.Label(where, text=LABEL_FOR, style="Dialog.TLabel").grid(row=0, column=0,
                                                                     sticky="w")
        self.mac = sys.platform == "darwin"
        platform_text = (texts.MAC_NOT_YET if self.mac
                         else texts.FOR_WINDOWS if sys.platform == "win32" else FOR_LINUX)
        self.for_label = self._label(where, platform_text, wrap=hint_wrap)
        self.for_label.grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Label(where, text=LABEL_SAVE_TO, style="Dialog.TLabel").grid(
            row=1, column=0, sticky="w", pady=(gap, 0))
        self.save_entry = ttk.Entry(where, textvariable=self.save_var, width=40)
        self.save_entry.grid(row=1, column=1, sticky="ew", pady=(gap, 0))
        self.browse_button = self._button(where, BROWSE, self._browse)
        self.browse_button.grid(row=1, column=2, sticky="e", padx=(gap, 0), pady=(gap, 0))
        hint = self._label(where, "", "BuildHint.TLabel", wrap=hint_wrap, compound="left")
        hint.grid(row=2, column=1, columnspan=2, sticky="w", pady=(hint_gap, 0))
        self.hints[buildmodel.FIELD_SAVE_TO] = hint
        self.inputs[buildmodel.FIELD_SAVE_TO] = self.save_entry
        self.zip_box = ttk.Checkbutton(setup, text=texts.ZIP, variable=self.zip_var,
                                       style="Dialog.TCheckbutton")
        self.zip_box.pack(anchor="w", pady=(self.px(12), 0))

        # The build tool (D2): shown only while it is missing or another version.
        self.tool_frame = ttk.Frame(setup, style="Dialog.TFrame")
        self.tool_label = self._label(self.tool_frame, "", compound="left")
        self.tool_label.pack(anchor="w")
        # The one thing to do while the tool is missing: primary (Build is off then).
        self.install_button = self._button(self.tool_frame, INSTALL, self.install,
                                           primary=True)
        self.install_button.pack(anchor="w", pady=(self.px(8), 0))
        self.install_text = tk.Text(
            self.tool_frame, height=INSTALL_LINES, wrap="none", width=1,
            font=self.fonts["codeSmall"], background=THEME["card.background"],
            foreground=THEME["editor.foreground"], borderwidth=0, highlightthickness=0,
            relief="flat", padx=self.px(8), pady=self.px(6), state="disabled")
        self.note = self._label(setup, texts.NOTE, "BuildHint.TLabel", compound="left",
                                image=self.icon("info", THEME["info"]))
        self.note.pack(anchor="w", pady=(self.px(12), 0))
        self.cancel_button, self.build_button = self._button_row(
            setup, ((CANCEL, self.close, False), (BUILD, self.build, True)))
        for var in (self.title_var, self.version_var, self.id_var, self.save_var):
            var.trace_add("write", lambda *_a: self._changed())

    def fields(self) -> buildmodel.BuildFields:
        return buildmodel.BuildFields(
            title=self.title_var.get().strip(), version=self.version_var.get().strip(),
            app_id=self.id_var.get().strip(), icon=self.icon_ref,
            save_to=self.save_var.get().strip(), zip=bool(self.zip_var.get()))

    def _set_hint(self, key: str, text: str, kind: str = "hint") -> None:
        style = {"hint": "BuildHint.TLabel", "error": "BuildError.TLabel",
                 "warn": "BuildWarn.TLabel"}[kind]
        image = (self.icon("error", THEME["marker.error"], 14) if kind == "error"
                 else self.icon("warning", THEME["marker.warning"], 14) if kind == "warn"
                 else "")
        hint = self.hints[key]
        hint.configure(text=text, style=style, image=image)
        if text:
            hint.grid()
        else:
            hint.grid_remove()

    def _changed(self) -> None:
        """Every field's hint or message, the slug button, the icon, and **Build**."""
        if not self.alive:
            return
        fields = self.fields()
        messages = self.messages = buildmodel.field_messages(fields, self.game_root)
        self._set_hint("name", messages.get("name") or buildmodel.name_hint(fields),
                       "error" if "name" in messages else "hint")
        self._set_hint("version", messages.get("version", ""), "error")
        changed = buildmodel.id_changed_text(self.prefs.last_id, fields.app_id)
        if "id" in messages:
            self._set_hint("id", messages["id"], "error")
        elif changed is not None:
            self._set_hint("id", changed, "warn")
        else:
            self._set_hint("id", texts.ID_HINT)
        slug = buildmodel.use_slug_text(fields.title)
        self.slug_button.configure(text=slug)
        if "id" in messages and fields.app_id != names.use_slug(fields.title):
            self.slug_button.grid()
        else:
            self.slug_button.grid_remove()
        self._set_hint(buildmodel.FIELD_ICON, messages.get(buildmodel.FIELD_ICON, ""), "error")
        self._show_icon()
        key = buildmodel.FIELD_SAVE_TO
        self._set_hint(key, messages.get(key) or buildmodel.makes_hint(fields),
                       "error" if key in messages else "hint")
        self._show_tool()
        self.build_button.state(["!disabled"] if self.can_build() else ["disabled"])

    def can_build(self) -> bool:
        return (not self.messages and self.tool.ok and not self.installing and not self.mac
                and not build_running(self.win))

    def _use_slug(self) -> None:
        self.id_var.set(names.use_slug(self.title_var.get()))
        self.id_entry.focus_set()

    def _use_default(self) -> None:
        self.icon_ref = None
        self._changed()

    def _choose_icon(self) -> None:
        project = getattr(self.win, "project", None)
        refs = sorted({node.ref for node in (project.nodes() if project else ())
                       if node.is_file and node.ref.casefold().endswith(".png")},
                      key=str.casefold)
        if not refs:
            self._error(NO_PNGS)
            return
        picked = choose_icon(self.dialog, refs, self.icon_ref)
        if picked:
            self.icon_ref = picked
            self._changed()

    def _browse(self) -> None:
        path = buildmodel.save_to_path(self.game_root, self.save_var.get())
        picked = choose_folder(self.dialog, str(path) if path else "")
        if picked:
            self.save_var.set(os.path.normpath(picked))

    def _show_icon(self) -> None:
        ref = self.icon_ref
        self.icon_label.configure(text=ENGINE_ICON if ref is None else ref)
        self.default_button.state(["disabled"] if ref is None else ["!disabled"])
        key = f"thumb:{ref}"
        if key not in self._images:
            image = self._thumbnail(ref)
            self._images[key] = image if image is not None else self._images["blank"]
        self.thumb.configure(image=self._images[key])

    def _thumbnail(self, ref: str | None) -> tk.PhotoImage | None:
        """The icon fitted into 24×24 (never upscaled)."""
        try:
            if ref is None:
                data = (engine_data_dir() / "icon.png").read_bytes()
            else:
                data = GamePaths.for_game(self.game_root).read_file(
                    ref, max_bytes=buildmodel.ICON_MAX_BYTES, regular=True)
            image = tk.PhotoImage(master=self.dialog, data=data)
        except Exception:
            return None
        step = thumbnail_step(image.width(), image.height(),
                              (self.px(THUMB_PX), self.px(THUMB_PX)))
        return image.subsample(step) if step > 1 else image

    # --- The build tool (D2, W3) ----------------------------------------------------------------

    def _show_tool(self) -> None:
        """The build tool's line: shown while it is missing, installing, or just
        installed (or failed to)."""
        frame = self.tool_frame
        if self.tool.ok and self.install_state is None:
            if frame.winfo_manager():
                frame.pack_forget()
            return
        if not frame.winfo_manager():
            frame.pack(anchor="w", fill="x", pady=(self.px(12), 0), before=self.note)
        if self.install_state is None:          # missing: say so, offer the button
            message = texts.failure(self.tool.key or "B_NO_TOOL", x=self.tool.found or "",
                                    y=self.tool.wanted)[0]
            self.tool_label.configure(text=message, style="BuildWarn.TLabel",
                                      image=self.icon("warning", THEME["marker.warning"]))

    def _set_install_state(self, state: str | None, text: str = "") -> None:
        """``installing``, ``installed``, ``failed`` (or ``None``): the line and button."""
        self.install_state = state
        self.installing = state == "installing"
        looks = {"installing": ("Dialog.TLabel", "info", THEME["info"]),
                 "installed": ("Dialog.TLabel", "success", THEME["success"]),
                 "failed": ("BuildError.TLabel", "error", THEME["marker.error"])}
        if state in looks:
            style, icon, color = looks[state]
            self.tool_label.configure(text=text, style=style, image=self.icon(icon, color))
        if state == "installed":
            self.install_button.pack_forget()
        else:
            self.install_button.state(["disabled"] if self.installing else ["!disabled"])

    def install(self) -> None:
        """**Install build tool**: pip with the pinned, hashed file, output below."""
        if self.installing:
            return
        if self.view != SETUP:
            self.show_setup()
        installer = installer_for(self.win)
        refused = installer.start()
        if refused is not None:
            self._set_install_state("failed", INSTALL_DIDNT_START.format(reason=refused.reason))
            self._changed()
            return
        self._set_install_state("installing", INSTALLING)
        self._set_install_lines([])
        if not self.install_text.winfo_manager():
            self.install_text.pack(anchor="w", fill="x", pady=(self.px(8), 0))
        self._changed()
        self.install_text.focus_set()

    def _set_install_lines(self, lines: Sequence[str], *, append: bool = False) -> None:
        text = self.install_text
        text.configure(state="normal")
        if not append:
            text.delete("1.0", "end")
        for line in lines:
            if text.index("end-1c") != "1.0":
                text.insert("end", "\n")
            text.insert("end", line)
        text.configure(state="disabled")
        text.see("end")

    def install_lines(self) -> list[str]:
        return self.install_text.get("1.0", "end-1c").split("\n")

    def on_install_events(self, events: Sequence[InstallEvent]) -> None:
        if not self.alive:
            return
        for event in events:
            if event.lines:
                self._set_install_lines(event.lines, append=True)
            if event.finished:
                self.tool = tool_status()
                if event.exit_code == 0 and self.tool.ok:
                    self._set_install_state("installed", INSTALLED)
                elif event.reason is not None:
                    self._set_install_state(
                        "failed", INSTALL_DIDNT_START.format(reason=event.reason))
                else:
                    self._set_install_state("failed", INSTALL_FAILED)
        self._changed()
        if self.view == SETUP and not self.installing:
            self._focus_setup()

    # --- Build ----------------------------------------------------------------------------------

    def build(self) -> None:
        """**Build** (01 §6.1, PR-F42-09, -11, -13, -21)."""
        if not self.can_build():
            return
        win, fields = self.win, self.fields()
        save_to = buildmodel.save_to_path(self.game_root, fields.save_to)
        if save_to is None:
            return
        folder = buildmodel.folder_of(fields)
        replace = False
        question = buildmodel.replace_question(save_to, folder, with_zip=fields.zip)
        if question is not None:
            if self._ask(question, (texts.REPLACE, CANCEL), escape=1, default=1) != 0:
                return
            replace = True
        plan = buildmodel.config_plan(self._config_text(), fields)
        if isinstance(plan, Refuse):
            self._error(plan.text)
            return
        if plan is not None and not win.apply_plan(plan.plan, plan.verify):
            self._error(CONFIG_NOT_WRITTEN)
            return
        if not win.save_all():                  # its failure dialog was shown
            self._regrab()
            return
        buildprefs.write_prefs(self.game_root, buildprefs.BuildPrefs(
            save_to=save_to, zip=fields.zip, last_id=self.prefs.last_id))
        self.started = (fields, save_to, folder)
        runner = runner_for(win)
        events = runner.start(save_to, folder, zip=fields.zip, replace=replace,
                              serial=win.edit_serial)
        self.show_progress()
        update_menu(win)
        self.on_events(events)

    def on_events(self, events: Sequence[BuildEvent]) -> None:
        """The build runner's events (from the window's poll loop)."""
        if not self.alive:
            return
        for event in events:
            state = event.state
            if state is BuildState.CHECK:
                _apply_check(self.win, event)
            elif state is BuildState.DONE and event.done is not None:
                self.show_finished(event.done)
            elif state is BuildState.FAILED and event.failure is not None:
                message, fix, details = buildmodel.failed_texts(event.failure)
                self.show_failed(message, fix, details, code=event.failure.code)
            elif state is BuildState.CRASHED:
                message, fix = texts.FAILURES["B_CRASHED"]
                details = tuple(line for line in (event.reason or "").split("\n") if line)
                self.show_failed(message, fix, details, code="B_CRASHED")
            elif state is BuildState.CANCELLED:
                self.show_cancelled()
        if self.view == PROGRESS:
            self.draw_progress()

    # --- Views ----------------------------------------------------------------------------------

    def _new_page(self, view: str) -> ttk.Frame:
        self._cancel_tick()
        if self.page is not None:
            self.page.destroy()
        if self.setup.winfo_manager():
            self.setup.pack_forget()
        self.view = view
        page = self.page = ttk.Frame(self.body, style="Dialog.TFrame")
        page.pack(fill="both", expand=True)
        return page

    def show_setup(self) -> None:
        """Back to Setup with the values kept (**Try again**, **Back**)."""
        self._cancel_tick()
        if self.page is not None:
            self.page.destroy()
            self.page = None
        self.view = SETUP
        self.setup.pack(fill="both", expand=True)
        self.tool = tool_status()
        self._changed()
        self._focus_setup()
        self._recenter()

    def show_progress(self) -> None:
        fields = self.started[0] if self.started else self.fields()
        page = self._new_page(PROGRESS)
        self._label(page, buildmodel.head_text(fields), "BuildStrong.TLabel").pack(anchor="w")
        bar_row = ttk.Frame(page, style="Dialog.TFrame")
        bar_row.pack(anchor="w", fill="x", pady=(self.px(12), self.px(8)))
        self.bar = ttk.Progressbar(bar_row, style="Build.Horizontal.TProgressbar",
                                   mode="determinate", maximum=1000,
                                   length=self.px(320))
        self.bar.pack(side="left")
        self.counter = self._label(bar_row, "", "BuildHint.TLabel", wrap=0)
        self.counter.pack(side="left", padx=(self.px(12), 0))
        self.rows_frame = ttk.Frame(page, style="Dialog.TFrame")
        self.rows_frame.pack(anchor="w", fill="x")
        self.row_labels: list[tuple[tk.Label, tk.Label]] = []
        self.slow_label = tk.Label(self.rows_frame, text=texts.SLOW, anchor="w",
                                   background=THEME["widget.background"],
                                   foreground=THEME["muted"], font=self.fonts["small"])
        (self.cancel_build_button,) = self._button_row(
            page, ((CANCEL_BUILD, self.cancel_build, False),))
        self.draw_progress()
        self.cancel_build_button.focus_set()
        self._recenter()
        self._tick_id = self.dialog.after(TICK_MS, self._tick)

    def _tick(self) -> None:
        self._tick_id = None
        if self.alive and self.view == PROGRESS:
            self.draw_progress()
            self._tick_id = self.dialog.after(TICK_MS, self._tick)

    def _cancel_tick(self) -> None:
        if self._tick_id is not None:
            try:
                self.dialog.after_cancel(self._tick_id)
            except tk.TclError:
                pass
            self._tick_id = None

    def draw_progress(self) -> None:
        """Rows (✓ done, › running, ⊗ failed, plain waiting), ``Step N of M``, the running
        step's elapsed time, ``SLOW`` under the packing step, and "Stopping…"."""
        runner = runner_for(self.win)
        progress = runner.progress
        if progress is None or self.view != PROGRESS:
            return
        now = clock()
        rows = progress.rows()
        while len(self.row_labels) < len(rows):
            glyph = tk.Label(self.rows_frame, width=2, anchor="w",
                             background=THEME["widget.background"], font=self.fonts["body"])
            text = tk.Label(self.rows_frame, anchor="w", justify="left",
                            background=THEME["widget.background"], font=self.fonts["body"])
            index = len(self.row_labels)
            glyph.grid(row=2 * index, column=0, sticky="nw", pady=(self.px(4), 0))
            text.grid(row=2 * index, column=1, sticky="w", pady=(self.px(4), 0))
            self.row_labels.append((glyph, text))
        self.slow_label.grid_remove()
        for index, row in enumerate(rows):
            glyph, label = self.row_labels[index]
            if row.status == ROW_DONE:
                mark, color, font = "✓", THEME["success"], self.fonts["body"]
            elif row.status == ROW_RUNNING:
                mark, color, font = "›", THEME["button.background"], self.fonts["bodyStrong"]
                glyph.configure(font=self.fonts["bodyStrong"])
            elif row.status == ROW_FAILED:
                mark, color, font = "⊗", THEME["marker.error"], self.fonts["body"]
            else:
                mark, color, font = "", THEME["muted"], self.fonts["body"]
            text = row.text
            if row.status == ROW_RUNNING:
                elapsed = progress.elapsed_text(now)
                text = f"{text}… {elapsed}" if elapsed else f"{text}…"
            glyph.configure(text=mark, foreground=color)
            label.configure(text=text, font=font,
                            foreground=THEME["strongForeground"] if row.status == ROW_RUNNING
                            else THEME["muted"] if row.status not in (ROW_DONE, ROW_FAILED)
                            else THEME["foreground"])
            if row.status == ROW_RUNNING and progress.slow:
                self.slow_label.grid(row=2 * index + 1, column=1, sticky="w")
        self.bar.configure(value=round(progress.fraction * 1000))
        if runner.stopping:
            self.counter.configure(text=STOPPING)
            self.cancel_build_button.state(["disabled"])
        else:
            self.counter.configure(text=progress.counter_text())

    def progress_rows(self) -> list[tuple[str, str]]:
        """(glyph, text) of each step row as shown (tests and screenshots)."""
        return [(str(g.cget("text")), str(t.cget("text"))) for g, t in self.row_labels]

    def cancel_build(self) -> None:
        """**Cancel build** / **Stop build**: stop the child's tree; "Stopping…" until
        ``CANCELLED``."""
        runner = runner_for(self.win)
        if runner.running and not runner.stopping:
            runner.cancel()
        self.draw_progress()

    def _heading(self, page: tk.Misc, icon: str, color: str, text: str) -> ttk.Label:
        heading = self._label(page, text, "BuildStrong.TLabel", compound="left",
                              image=self.icon(icon, color, 20))
        heading.configure(padding=0)
        heading.pack(anchor="w")
        return heading

    def _line(self, page: tk.Misc, text: str, style: str = "Dialog.TLabel", *,
              top: int = 8, icon: tuple[str, str] | None = None) -> ttk.Label:
        options: dict = {}
        if icon is not None:
            options = {"compound": "left", "image": self.icon(icon[0], icon[1])}
        label = self._label(page, text, style, **options)
        label.pack(anchor="w", pady=(self.px(top), 0))
        return label

    def show_finished(self, done: Any) -> None:
        """✓ Your game is built: sizes, how to share, SmartScreen, warnings, left-out files;
        **Open folder**, **Run the game** (Enter), **Close** (Esc)."""
        fields, save_to, folder = self.started   # type: ignore[misc]
        if self.prefs.last_id != fields.app_id:
            self.prefs = buildprefs.BuildPrefs(save_to=save_to, zip=fields.zip,
                                               last_id=fields.app_id)
            buildprefs.write_prefs(self.game_root, self.prefs)
        words = buildmodel.finished_texts(done)
        page = self._new_page(FINISHED)
        self._heading(page, "success", THEME["success"], words.done)
        self.finished_lines = [words.done, words.folder_line]
        self._line(page, words.folder_line, top=12)
        if words.zip_line:
            self._line(page, words.zip_line, top=4)
            self.finished_lines.append(words.zip_line)
        self._line(page, words.share, top=12)
        self._line(page, words.smartscreen, "BuildHint.TLabel")
        self.finished_lines += [words.share, words.smartscreen]
        warn = ("warning", THEME["marker.warning"])
        if words.warnings:
            self._line(page, words.warnings, icon=warn, top=12)
            self.finished_lines.append(words.warnings)
        self.list_button: ttk.Button | None = None
        if words.left_out:
            row = ttk.Frame(page, style="Dialog.TFrame")
            row.pack(anchor="w", fill="x", pady=(self.px(8), 0))
            self._label(row, words.left_out, compound="left", wrap=0,
                        image=self.icon(*warn)).pack(side="left")
            self.finished_lines.append(words.left_out)
            box = self.left_out_box = self._list_box(page, words.left_out_lines)
            button = self.list_button = self._button(row, SHOW_LIST, lambda: None)
            button.configure(command=lambda: self._toggle(button, box, SHOW_LIST, row))
            button.pack(side="left", padx=(self.px(12), 0))
        if words.long_paths:
            self._line(page, words.long_paths, icon=warn)
            self.finished_lines.append(words.long_paths)
        # F48 PR-F48-32: key-shaped text in a shipped file, by ref and line only. A few are
        # warning lines; more go in a list box under the first.
        self.keys_box: ttk.Frame | None = None
        for line in words.keys[:1 if len(words.keys) > KEY_LINES else KEY_LINES]:
            self._line(page, line, icon=warn)
        if len(words.keys) > KEY_LINES:
            box = self.keys_box = self._list_box(page, words.keys)
            box.pack(anchor="w", fill="x", pady=(self.px(8), 0))
        self.finished_lines += list(words.keys)
        self.targets =buildmodel.open_targets(save_to, folder, buildmodel.exe_of(fields))
        self.open_button, self.run_button, self.close_button = self._button_row(page, (
            (OPEN_FOLDER, self.open_folder, False), (RUN_GAME, self.run_game, True),
            (CLOSE, self.close, False)))
        if self.targets is None:
            self.open_button.state(["disabled"])
            self.run_button.state(["disabled"])
            self.close_button.focus_set()
        else:
            self.run_button.focus_set()
        self._recenter()

    def open_folder(self) -> None:
        """**Open folder**: Studio's computed build folder, a real folder (I-11)."""
        targets = self.targets
        if targets is None or not os.path.isdir(targets[0]) or os.path.islink(targets[0]):
            return
        try:
            open_folder(targets[0])
        except OSError as error:
            self._error(OPEN_FAILED.format(reason=error.strerror or error))

    def run_game(self) -> None:
        """**Run the game**: the computed exe, from an argument list, in its folder (I-11)."""
        targets = self.targets
        if targets is None:
            return
        folder, exe = targets
        if not os.path.isfile(exe) or os.path.islink(exe):
            return
        try:
            run_game(exe, folder)
        except OSError as error:
            self._error(OPEN_FAILED.format(reason=error.strerror or error))

    def show_failed(self, message: str, fix: str, details: Sequence[str] = (), *,
                    code: str = "") -> None:
        """⊗ the message, its fix, **Show details** (with **Copy**) when the child sent
        lines, **Install build tool** for a missing tool; **Close**, **Try again**."""
        page = self._new_page(FAILED)
        self.failure = (message, fix, tuple(details), code)
        self._heading(page, "error", THEME["marker.error"], message)
        self._line(page, fix, top=8)
        self.details_button: ttk.Button | None = None
        if details:
            row = ttk.Frame(page, style="Dialog.TFrame")
            row.pack(anchor="w", pady=(self.px(12), 0))
            box = self.details_box = self._list_box(page, details)
            button = self.details_button = self._button(row, SHOW_DETAILS, lambda: None)
            button.configure(command=lambda: self._toggle(button, box, SHOW_DETAILS, row))
            button.pack(side="left")
        buttons: list[tuple[str, Callable[[], object], bool]] = []
        if code in TOOL_KEYS:
            buttons.append((INSTALL, self.install, False))
        buttons += [(CLOSE, self.close, False), (TRY_AGAIN, self.show_setup, True)]
        made = self._button_row(page, buttons)
        self.try_button = made[-1]
        self.try_button.focus_set()
        self._recenter()

    def show_cancelled(self) -> None:
        """``CANCELLED``: nothing in *Save to* changed; **Back** to Setup or **Close**."""
        save_to = self.started[1] if self.started else Path(".")
        page = self._new_page(CANCELLED)
        self.cancelled_line = buildmodel.cancelled_text(save_to)
        self._heading(page, "info", THEME["info"], self.cancelled_line)
        _back, close = self._button_row(page, ((BACK, self.show_setup, False),
                                               (CLOSE, self.close, True)))
        close.focus_set()
        self._recenter()

    # --- Keys and closing (UI-F42-02, -03) ------------------------------------------------------

    def _on_enter(self, event: tk.Event) -> str:
        widget = event.widget
        if isinstance(widget, ttk.Button):
            widget.invoke()                     # Enter presses the focused button
            return "break"
        if self.view == SETUP:
            self.build()
        elif self.view == FINISHED:
            self.run_game()
        elif self.view == FAILED:
            self.show_setup()
        elif self.view == CANCELLED:
            self.close()
        return "break"

    def _on_escape(self) -> None:
        if self.view == PROGRESS:
            if build_running(self.win):
                if self._ask(texts.CANCEL_ASK, (texts.STOP_BUILD, texts.KEEP_BUILDING),
                       escape=1, default=1) == 0:
                    self.cancel_build()
            return
        self.close()

    def close(self) -> None:
        """Close the dialog (Setup's **Cancel**, **Close**, Esc). A running install stops."""
        if not self.alive or self.view == PROGRESS:
            return
        if self.installing:
            installer_for(self.win).cancel()
        self.alive = False
        self._cancel_tick()
        if getattr(self.win, "build_dialog", None) is self:
            self.win.build_dialog = None
        try:
            self.dialog.grab_release()
            self.dialog.destroy()
        except tk.TclError:
            pass
        update_menu(self.win)
        try:
            self.win.text.focus_set()
        except (tk.TclError, AttributeError):
            pass

    # --- Showing --------------------------------------------------------------------------------

    def _focus_setup(self) -> None:
        """UI-F42-02: the first invalid field, else **Build** (else what can fix it)."""
        for key in FIELD_ORDER:
            if key in self.messages:
                self.inputs[key].focus_set()
                return
        if not self.tool.ok and self.install_button.winfo_manager() \
                and self.install_button.instate(["!disabled"]):
            self.install_button.focus_set()
        else:
            self.build_button.focus_set()

    def _recenter(self) -> None:
        if self.dialog.winfo_viewable():
            dialogs._center(self.dialog, self.win.root.winfo_toplevel())

    def show(self) -> None:
        """Map the dialog, centered and modal (no waiting: the poll loop drives it)."""
        d = self.dialog
        dialogs._center(d, self.win.root.winfo_toplevel())
        d.deiconify()
        dark_title_bar(d)
        self._focus_setup()
        try:
            d.grab_set()
        except tk.TclError:
            pass
        update_menu(self.win)


# --- The icon picker ------------------------------------------------------------------------------

class _IconPicker:
    """A list of PNG refs; OK picks the selected one (double-click and Enter too)."""

    def __init__(self, parent: tk.Misc, refs: Sequence[str], current: str | None) -> None:
        self.refs = list(refs)
        self.result: str | None = None
        dialog = self.dialog = dialogs._dialog(parent)
        dialog.title(PICK_ICON_TITLE)
        body, scale = dialogs._body(dialog)
        ttk.Label(body, text=PICK_ICON_ASK, style="Dialog.TLabel").pack(anchor="w")
        self.box = tk.Listbox(body, height=min(10, max(3, len(self.refs))), width=40,
                              background=THEME["input.background"],
                              foreground=THEME["foreground"], borderwidth=0,
                              highlightthickness=1,
                              highlightbackground=THEME["input.border"],
                              highlightcolor=THEME["focusBorder"],
                              selectbackground=THEME["list.activeSelection"],
                              selectforeground=THEME["list.activeSelectionForeground"],
                              activestyle="none", exportselection=False)
        for ref in self.refs:
            self.box.insert("end", ref)
        index = self.refs.index(current) if current in self.refs else 0
        self.box.selection_set(index)
        self.box.activate(index)
        self.box.see(index)
        self.box.pack(anchor="w", fill="both", expand=True, pady=(round(8 * scale), 0))
        dialogs._buttons(dialog, body, (dialogs.OK, CANCEL), self._pick)
        self.box.bind("<Double-Button-1>", lambda _e: self._pick(0))
        self.box.bind("<Return>", lambda _e: self._pick(0))
        dialog.bind("<Escape>", lambda _e: self._pick(1))
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._pick(1))

    def _pick(self, index: int) -> None:
        if index == 0:
            chosen = self.box.curselection()
            self.result = self.refs[chosen[0]] if chosen else None
        self.dialog.destroy()

    def run(self, parent: tk.Misc) -> str | None:
        dialogs._run(parent, self.dialog, self.box)
        return self.result


__all__ = ["BuildDialog", "build_running", "choose_folder", "choose_icon", "installer_for",
           "make_installer", "make_runner", "open_build_dialog", "open_folder", "run_game",
           "runner_for", "tool_status", "update_menu"]
