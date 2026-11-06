"""Studio's dialogs: every modal window the editor opens (F44 ``04`` §7.6 "Dialogs"; F45
``01`` §6.3, UI-F45-06; ``04`` §3).

Small Tk dialogs built from ``ttk`` widgets in Studio's theme (``theme.THEME``, the ttk
styles of ``theme.style_ttk``; F45 ``08`` §7: padding 20, buttons at least 80 px wide, 8
apart and 20 below the message, all times the screen's scale), transient to the editor and
centered on it. They show Studio's icon, which the window set as every toplevel's default
(``appicon``). A message shows a `` `name` `` span without its backticks, in the small code
font and the strong text color (display only: the texts keep their backticks). Info and
error are the same dialog with one OK and a 24 px icon (``08`` §7, P2). The default button is
the primary (accent) one. Esc and the close box always pick the safe answer, and a destructive
button is never the default. The window calls these through its own module names
(``window.ask`` and so on), so tests answer them by patching the window module. The OS pickers are thin wrappers over
``tkinter.filedialog`` for the same reason.

Imports only the standard library, ``icons`` and ``theme`` (ADR-0008).
"""

import math
import re
import tkinter as tk
from collections.abc import Callable, Sequence
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from engine.core.paths import default_games_dir
from engine.tools.editor import icons
from engine.tools.editor.theme import THEME, TYPE_SCALE, dark_title_bar, font_families, scale_of

APP_NAME = "vn-engine Studio"
WRAP = 400
PADDING = 20
BUTTON_MIN_WIDTH = 80
BUTTON_GAP = 8
ICON_PX = 24
ICON_GAP = 12
OK = "OK"
MUTED = THEME["muted"]
CODE_SPAN = re.compile(r"`([^`\n]+)`")
TAG_CODE = "code"


def show_error(parent: tk.Misc, message: str) -> None:
    """A failure (03 §2.2): Studio's dialog with the error icon and one OK button."""
    ask(parent, message, (OK,), escape=0, icon=("error", THEME["marker.error"]))


def show_info(parent: tk.Misc, message: str) -> None:
    """A result, such as the add summary: Studio's dialog with the info icon and one OK."""
    ask(parent, message, (OK,), escape=0, icon=("info", THEME["info"]))


def spans(message: str) -> list[tuple[str, bool]]:
    """``message`` as (text, is code) runs; a code run is a `` `name` `` span's inside."""
    runs: list[tuple[str, bool]] = []
    at = 0
    for found in CODE_SPAN.finditer(message):
        if found.start() > at:
            runs.append((message[at:found.start()], False))
        runs.append((found.group(1), True))
        at = found.end()
    if at < len(message):
        runs.append((message[at:], False))
    return runs


def shown_text(message: str) -> str:
    """What the dialog shows: ``message`` without its code spans' backticks."""
    return "".join(text for text, _code in spans(message))


def ask_open_files(parent: tk.Misc) -> list[Path]:
    """Add files…: the OS file dialog, several files. An empty list when cancelled."""
    picked = filedialog.askopenfilenames(parent=parent, title="Add files")
    return [Path(name) for name in parent.tk.splitlist(picked)] if picked else []


def _games_folder() -> dict[str, str]:
    """``initialdir`` for New game and Open game: the Studio app's games folder
    (``paths.default_games_dir``), else nothing (the OS dialog's own default)."""
    folder = default_games_dir()
    return {} if folder is None else {"initialdir": str(folder)}


def ask_directory(parent: tk.Misc) -> Path | None:
    """New game…: the OS folder dialog (a new folder name may be typed). None if cancelled."""
    picked = filedialog.askdirectory(parent=parent, title="New game folder", mustexist=False,
                                     **_games_folder())
    return Path(picked) if picked else None


def ask_game_folder(parent: tk.Misc) -> Path | None:
    """Open game…: the OS folder dialog for an existing game folder. None if cancelled."""
    picked = filedialog.askdirectory(parent=parent, title="Open game folder", mustexist=True,
                                     **_games_folder())
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


def _run(parent: tk.Misc, dialog: tk.Toplevel, focus: tk.Widget,
         message: tk.Text | None = None) -> None:
    """Show ``dialog`` centered, modal, with ``focus`` focused, until it closes."""
    _center(dialog, parent.winfo_toplevel())
    dialog.deiconify()
    dialog.update_idletasks()
    if message is not None:             # the estimate was off: fit, then center again
        height = int(message.cget("height"))
        _fit(message)
        if int(message.cget("height")) != height:
            _center(dialog, parent.winfo_toplevel())
    dark_title_bar(dialog)
    focus.focus_force()                 # a modal dialog takes the keyboard
    try:
        dialog.grab_set()
    except tk.TclError:
        pass                            # not viewable yet; the dialog is still modal enough
    parent.wait_window(dialog)


def _wrapped_lines(runs: list[tuple[str, bool]], fonts: tuple[tkfont.Font, tkfont.Font],
                   width: int) -> int:
    """How many lines ``runs`` take, word-wrapped at ``width`` px (as a Text wraps)."""
    lines, used = 1, 0
    for text, code in runs:
        font = fonts[code]
        for index, part in enumerate(text.split("\n")):
            if index:
                lines, used = lines + 1, 0
            for word in re.findall(r"\S+\s*|\s+", part):
                size = font.measure(word.rstrip())
                if used and used + size > width:
                    lines, used = lines + 1, 0
                used += font.measure(word)
    return lines


def _message(dialog: tk.Toplevel, parent: tk.Misc, message: str, wrap: int) -> tk.Text:
    """The message as read-only text: word-wrapped at ``wrap`` px (narrower when it fits),
    each code span in the small code font and the strong text color, without backticks."""
    scale = scale_of(dialog)
    body = tkfont.nametofont("TkDefaultFont", root=dialog)
    family, weight = font_families(dialog)["mono"]
    code = tkfont.Font(root=dialog, family=family, weight=weight,
                       size=-round(TYPE_SCALE["codeSmall"][0] * scale))
    dialog.code_font = code             # type: ignore[attr-defined]  (Tk deletes a lost font)
    runs = spans(message)
    natural = max(sum((code if c else body).measure(line) for line, c in row)
                  for row in _rows(runs))
    width = min(wrap, natural + 2)
    zero = max(1, body.measure("0"))
    background = THEME["widget.background"]
    text = tk.Text(parent, wrap="word", width=max(1, math.ceil(width / zero)), font=body,
                   height=_wrapped_lines(runs, (body, code), math.ceil(width / zero) * zero),
                   background=background, foreground=THEME["foreground"], borderwidth=0,
                   highlightthickness=0, padx=0, pady=0, relief="flat", takefocus=0,
                   cursor="arrow", selectbackground=THEME["editor.selection"],
                   inactiveselectbackground=background)
    text.tag_configure(TAG_CODE, font=code, foreground=THEME["strongForeground"])
    for part, is_code in runs:
        text.insert("end", part, (TAG_CODE,) if is_code else ())
    text.configure(state="disabled")
    text.message = message              # type: ignore[attr-defined]  (the source, for tests)
    return text


def _rows(runs: list[tuple[str, bool]]) -> list[list[tuple[str, bool]]]:
    """``runs`` split at newlines into rows of runs (each row is one paragraph line)."""
    rows: list[list[tuple[str, bool]]] = [[]]
    for text, code in runs:
        for index, part in enumerate(text.split("\n")):
            if index:
                rows.append([])
            rows[-1].append((part, code))
    return rows


def _fit(text: tk.Text) -> None:
    """Once the dialog is laid out: the message's height to its real display lines (not
    before Tk gave the text its width: then every character is a line)."""
    text.update_idletasks()
    if text.winfo_width() < int(text.cget("width")):
        return
    try:
        found = text.count("1.0", "end", "displaylines", "update")
    except tk.TclError:
        return
    lines = found[0] if isinstance(found, tuple) else found
    if lines and int(text.cget("height")) != lines:
        text.configure(height=lines)


def _body(dialog: tk.Toplevel) -> tuple[ttk.Frame, float]:
    """The dialog's padded body and the screen's scale."""
    scale = scale_of(dialog)
    body = ttk.Frame(dialog, padding=round(PADDING * scale), style="Dialog.TFrame")
    body.pack(fill="both", expand=True)
    return body, scale


def _buttons(dialog: tk.Toplevel, body: ttk.Frame, labels: Sequence[str],
             pick: Callable[[int], None], default: int = 0) -> list[ttk.Button]:
    scale = scale_of(dialog)
    row = ttk.Frame(body, style="Dialog.TFrame")
    row.pack(anchor="e", pady=(round(PADDING * scale), 0))
    zero = max(1, tkfont.nametofont("TkDefaultFont", root=dialog).measure("0"))
    chars = -math.ceil(BUTTON_MIN_WIDTH * scale / zero)   # negative: a minimum width
    widgets = []
    for index, label in enumerate(labels):
        button = ttk.Button(row, text=label, command=lambda i=index: pick(i), width=chars,
                            style="TButton" if index == default else "Secondary.TButton")
        button.pack(side="left", padx=(round(BUTTON_GAP * scale) if index else 0, 0))
        for key in ("<Return>", "<KP_Enter>"):
            button.bind(key, lambda _e, i=index: pick(i))
        widgets.append(button)
    return widgets


def ask(parent: tk.Misc, message: str, buttons: Sequence[str], *, escape: int,
        default: int = 0, icon: tuple[str, str] | None = None) -> int:
    """A small modal question built from native buttons (``04`` §7.6, UI Q2), with button
    ``default`` focused. Enter picks the focused button; Esc and the close box pick
    ``escape`` (I-6). ``icon`` is an ``icons`` name and its color, shown left of the
    message. Returns the chosen button's index."""
    dialog = _dialog(parent)
    choice = [escape]

    def pick(index: int) -> None:
        choice[0] = index
        dialog.destroy()

    body, scale = _body(dialog)
    row = ttk.Frame(body, style="Dialog.TFrame")
    row.pack(anchor="w", fill="x")
    if icon is not None:
        image = icons.photo(dialog, icon[0], round(ICON_PX * scale), icon[1])
        dialog.icon_image = image       # type: ignore[attr-defined]  (keep it)
        ttk.Label(row, image=image, style="Dialog.TLabel").pack(
            side="left", anchor="n", padx=(0, round(ICON_GAP * scale)))
    shown = _message(dialog, row, message, round(WRAP * scale))
    shown.pack(side="left", anchor="w")
    widgets = _buttons(dialog, body, buttons, pick, default)
    dialog.bind("<Escape>", lambda _e: pick(escape))
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(escape))
    _run(parent, dialog, widgets[default], shown)
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

    body, scale = _body(dialog)
    wrap, gap = round(WRAP * scale), round(8 * scale)
    text = _message(dialog, body, message, wrap)
    text.pack(anchor="w")
    entry = ttk.Entry(body, textvariable=value, width=48)
    entry.pack(anchor="w", fill="x", pady=(gap, 0))
    shown = ttk.Label(body, text="", wraplength=wrap, justify="left",
                      style="Dialog.Hint.TLabel")
    if hint is not None:
        # The hint sits 4 below the entry and takes no space while it is empty (08 §7).
        def update(*_args: object) -> None:
            line = hint(value.get()) or ""
            shown.configure(text=line)
            if line and not shown.winfo_manager():
                shown.pack(anchor="w", pady=(round(4 * scale), 0), after=entry)
            elif not line and shown.winfo_manager():
                shown.pack_forget()

        value.trace_add("write", update)
        update()
    if option is not None:
        ttk.Checkbutton(body, text=option, variable=ticked,
                        style="Dialog.TCheckbutton").pack(anchor="w", pady=(gap, 0))
    _buttons(dialog, body, (ok, "Cancel"), pick)
    for key in ("<Return>", "<KP_Enter>"):
        entry.bind(key, lambda _e: pick(0))
    dialog.bind("<Escape>", lambda _e: pick(1))
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(1))
    dot = initial.rfind(".")
    entry.selection_range(0, dot if select_stem and dot > 0 else "end")
    entry.icursor(dot if select_stem and dot > 0 else "end")
    _run(parent, dialog, entry, text)
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
