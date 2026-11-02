"""Studio's dialogs: every modal window the editor opens (F44 ``04`` §7.6 "Dialogs"; F45
``01`` §6.3, UI-F45-06; ``04`` §3).

Small Tk dialogs built from ``ttk`` widgets in Studio's theme (``theme.THEME``, the ttk
styles of ``theme.style_ttk``), transient to the editor and centered on it. The default
button is the blue one. Esc and the close box always pick the safe answer, and a destructive
button is never the default. The window calls these through its own module names
(``window.ask`` and so on), so tests answer them by patching the window module. The OS pickers are thin wrappers over
``tkinter.filedialog`` for the same reason.

Imports only the standard library and ``theme`` (ADR-0008).
"""

import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from engine.tools.editor.theme import THEME, dark_title_bar

APP_NAME = "vn-engine Studio"
WRAP = 440
MUTED = THEME["muted"]


def show_error(parent: tk.Misc, message: str) -> None:
    """A failure (03 §2.2): a native message box with one OK button."""
    messagebox.showerror(APP_NAME, message, parent=parent)


def show_info(parent: tk.Misc, message: str) -> None:
    """A result, such as the add summary: a native message box with one OK button."""
    messagebox.showinfo(APP_NAME, message, parent=parent)


def ask_open_files(parent: tk.Misc) -> list[Path]:
    """Add files…: the OS file dialog, several files. An empty list when cancelled."""
    picked = filedialog.askopenfilenames(parent=parent, title="Add files")
    return [Path(name) for name in parent.tk.splitlist(picked)] if picked else []


def ask_directory(parent: tk.Misc) -> Path | None:
    """New game…: the OS folder dialog (a new folder name may be typed). None if cancelled."""
    picked = filedialog.askdirectory(parent=parent, title="New game folder", mustexist=False)
    return Path(picked) if picked else None


def _dialog(parent: tk.Misc) -> tk.Toplevel:
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title(APP_NAME)
    dialog.resizable(False, False)
    dialog.configure(background=THEME["widget.background"])
    if parent.winfo_viewable():
        dialog.transient(parent.winfo_toplevel())
    return dialog


def _run(parent: tk.Misc, dialog: tk.Toplevel, focus: tk.Widget) -> None:
    """Show ``dialog`` centered, modal, with ``focus`` focused, until it closes."""
    _center(dialog, parent.winfo_toplevel())
    dialog.deiconify()
    dialog.update_idletasks()
    dark_title_bar(dialog)
    focus.focus_force()                 # a modal dialog takes the keyboard
    try:
        dialog.grab_set()
    except tk.TclError:
        pass                            # not viewable yet; the dialog is still modal enough
    parent.wait_window(dialog)


def _buttons(dialog: tk.Toplevel, body: ttk.Frame, labels: Sequence[str],
             pick: Callable[[int], None], default: int = 0) -> list[ttk.Button]:
    row = ttk.Frame(body, style="Dialog.TFrame")
    row.pack(anchor="e", pady=(16, 0))
    widgets = []
    for index, label in enumerate(labels):
        button = ttk.Button(row, text=label, command=lambda i=index: pick(i),
                            style="TButton" if index == default else "Secondary.TButton")
        button.pack(side="left", padx=(8 if index else 0, 0))
        for key in ("<Return>", "<KP_Enter>"):
            button.bind(key, lambda _e, i=index: pick(i))
        widgets.append(button)
    return widgets


def ask(parent: tk.Misc, message: str, buttons: Sequence[str], *, escape: int,
        default: int = 0) -> int:
    """A small modal question built from native buttons (``04`` §7.6, UI Q2), with button
    ``default`` focused. Enter picks the focused button; Esc and the close box pick
    ``escape`` (I-6). Returns the chosen button's index."""
    dialog = _dialog(parent)
    choice = [escape]

    def pick(index: int) -> None:
        choice[0] = index
        dialog.destroy()

    body = ttk.Frame(dialog, padding=16, style="Dialog.TFrame")
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=message, wraplength=WRAP, justify="left",
              style="Dialog.TLabel").pack(anchor="w")
    widgets = _buttons(dialog, body, buttons, pick, default)
    dialog.bind("<Escape>", lambda _e: pick(escape))
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(escape))
    _run(parent, dialog, widgets[default])
    return choice[0]


def ask_text(parent: tk.Misc, message: str, initial: str, *, ok: str,
             hint: Callable[[str], str | None] | None = None,
             option: str | None = None, option_value: bool = True,
             select_stem: bool = True) -> tuple[str, bool] | None:
    """A question with one editable line: ``(text, option ticked)``, or None for Cancel,
    Esc, or the close box. ``hint(text)`` gives a gray line under the entry that follows
    the typing (``In the script: show hana smile``). ``option`` adds a check box, ticked
    when ``option_value``. The name's stem is selected, so typing replaces it."""
    dialog = _dialog(parent)
    result: list[tuple[str, bool] | None] = [None]
    value = tk.StringVar(dialog, value=initial)
    ticked = tk.BooleanVar(dialog, value=option_value)

    def pick(index: int) -> None:
        if index == 0:
            result[0] = (value.get(), bool(ticked.get()))
        dialog.destroy()

    body = ttk.Frame(dialog, padding=16, style="Dialog.TFrame")
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=message, wraplength=WRAP, justify="left",
              style="Dialog.TLabel").pack(anchor="w")
    entry = ttk.Entry(body, textvariable=value, width=48)
    entry.pack(anchor="w", fill="x", pady=(8, 0))
    shown = ttk.Label(body, text="", foreground=MUTED, wraplength=WRAP, justify="left",
                      style="Dialog.TLabel")
    if hint is not None:
        shown.pack(anchor="w", pady=(4, 0))

        def update(*_args: object) -> None:
            shown.configure(text=hint(value.get()) or "")

        value.trace_add("write", update)
        update()
    if option is not None:
        ttk.Checkbutton(body, text=option, variable=ticked,
                        style="Dialog.TCheckbutton").pack(anchor="w", pady=(8, 0))
    _buttons(dialog, body, (ok, "Cancel"), pick)
    for key in ("<Return>", "<KP_Enter>"):
        entry.bind(key, lambda _e: pick(0))
    dialog.bind("<Escape>", lambda _e: pick(1))
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(1))
    dot = initial.rfind(".")
    entry.selection_range(0, dot if select_stem and dot > 0 else "end")
    entry.icursor(dot if select_stem and dot > 0 else "end")
    _run(parent, dialog, entry)
    return result[0]


def _center(window: tk.Toplevel, over: tk.Misc) -> None:
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    if over.winfo_viewable():
        x = over.winfo_rootx() + (over.winfo_width() - width) // 2
        y = over.winfo_rooty() + (over.winfo_height() - height) // 2
    else:
        x = (over.winfo_screenwidth() - width) // 2
        y = (over.winfo_screenheight() - height) // 2
    window.geometry(f"+{x}+{y}")
