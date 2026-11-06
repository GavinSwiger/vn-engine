"""Studio's Play bar and its Play options dialog (F47 ``01-design.md`` PR-F47-07..09, §6.1,
§6.4; ``04-technical.md`` §3.2, §7.4).

Why this module exists: playing the game is the one thing every author does all the time, so
it gets a 36 px toolbar on ``chrome`` under the menu bar, across the window, instead of F44's
small button at the bottom of the left column::

    [▶ Play|▾]                                                   [AI Assistant] [? Guide]

**▶ Play** is the window's one primary button, a split button (proposal 2.1, 2026-11-06):
a click plays from the start (Shift+F5); its **▾** opens a small menu with Play, Play this
scene (F5, with the scene's name) and Play options…, plus what ``add_check`` adds (the
"Game beside Studio" switch). While the game runs the button reads **■ Stop** (Ctrl+F2) in
gray. The Run menu keeps every row and key. **? Guide** toggles the Guide pane and F48's
**AI Assistant**, left of it, the Assistant pane (they share the column). Each button has a
tooltip; Left and Right move between the bar's buttons, Down opens the ▾ menu.

The old cluster's widgets (Play this scene, the scene name, a separate Stop, Play options…)
are still made, hidden, so the run code keeps their state (2026-11-04 moved running the
game to the Run menu; the one split button came back on 2026-11-06).

On Windows and Linux the bar shares the in-window menu bar's row (``merge_into``: the menu
titles, then these buttons), so the window has no separate toolbar row; macOS, whose menu bar
is the system's, keeps it as its own row under the title bar.

``PlayBar`` only draws and calls back: ``runwiring.RunWiring`` owns what Play does.
``ask_play_options`` is the modal dialog; the window calls it through ``runwiring``'s own
name, so tests answer it by patching that module.

Imports only the standard library, ``dialogs``, ``studiolook`` and ``theme`` (ADR-0008).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from engine.tools.editor import dialogs
from engine.tools.editor.studiolook import (
    CURSOR_COLOR,
    CURSOR_WIDTH,
    FOCUS_BORDER,
    INACTIVE_SELECTION,
    INPUT_BACKGROUND,
    INPUT_BORDER,
    SELECTION_BACKGROUND,
    START_VALUES_ROWS,
    TEXT_PAD,
)
from engine.tools.editor.syntax import PLAIN_COLOR
from engine.tools.editor.theme import THEME, scale_of

BAR_PX = 36                             # PR-F47-07
BAR_INSET = 12                          # as the map toolbar (08 §7)
BAR_GAP = 8
TIP_DELAY_MS = 500

PLAY = "▶ Play"
MORE = "▾"                              # the split button's menu half
PLAY_SCENE = "▶ Play this scene"
STOP = "■ Stop"
PLAY_OPTIONS = "Play options…"
GUIDE = "? Guide"
ASSISTANT = "AI Assistant"              # F48 01 §6.1
PLAY_MENU_ROW = "Play"                  # the ▾ menu's rows, as the Run menu's
PLAY_SCENE_MENU_ROW = "Play this scene"
PLAY_SCENE_NAMED = "Play this scene: {name}"
BEGINNING = "the beginning"             # what Play this scene plays with no scene chosen

TIP_PLAY = "Play from the start (Shift+F5)"
TIP_SCENE = "Play from the selected scene (F5)"
TIP_STOP = "Stop the game (Ctrl+F2)"
TIP_OPTIONS = "Start values, and playing as a new player"
TIP_MORE = "More ways to play"
MENUS_POST = True                       # tests set False: tk_popup would wait for a click
TIP_GUIDE = "Show or hide the Guide"
TIP_ASSISTANT = "Show or hide the AI Assistant (Ctrl+Shift+A)"

OPTIONS_TITLE = "Play options"
START_VALUES_HEADING = "Start values"
START_VALUES_HINT = "One per line, e.g. sayo_points = 1"
FRESH = "Play as a new player (forget what earlier playthroughs remember)"
OPTIONS_OK = "OK"


class Tooltip:
    """A small hint box under ``widget`` after the pointer rests on it for
    ``TIP_DELAY_MS``; it goes on leave or click. ``text`` is what it shows (tests read it)."""

    def __init__(self, widget: tk.Widget, text: str, font: object = None) -> None:
        self.widget, self.text, self.font = widget, text, font
        self._after: str | None = None
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        for sequence in ("<Leave>", "<ButtonPress>", "<Destroy>"):
            widget.bind(sequence, self.hide, add="+")

    def _schedule(self, _event: tk.Event | None = None) -> None:
        self.hide()
        self._after = self.widget.after(TIP_DELAY_MS, self.show)

    def show(self) -> None:
        self._after = None
        if self.window is not None or not self.widget.winfo_viewable():
            return
        scale = scale_of(self.widget)
        tip = self.window = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)    # above a topmost Studio window too
        except tk.TclError:
            pass
        tip.configure(background=THEME["widget.border"])
        label = tk.Label(tip, text=self.text, background=THEME["widget.background"],
                         foreground=THEME["foreground"], padx=round(8 * scale),
                         pady=round(4 * scale), borderwidth=0)
        if self.font is not None:
            label.configure(font=self.font)
        label.pack(padx=1, pady=1)
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + round(4 * scale)
        tip.wm_geometry(f"+{x}+{y}")

    def hide(self, _event: tk.Event | None = None) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


class PlayBar:
    """The Play bar on ``parent`` (pack ``frame``, then ``divider`` under it)."""

    def __init__(self, parent: tk.Misc, *, scale: float, font: object, tip_font: object,
                 on_play: Callable[[], object], on_scene: Callable[[], object],
                 on_stop: Callable[[], object], on_options: Callable[[], object],
                 on_guide: Callable[[], object],
                 on_assistant: Callable[[], object] | None = None) -> None:
        px = lambda value: round(value * scale)       # noqa: E731
        chrome = THEME["sideBar.background"]
        linespace = font.metrics("linespace") if hasattr(font, "metrics") else px(16)
        self.frame = tk.Frame(parent, background=chrome,
                              height=max(px(BAR_PX), linespace + px(16)))
        self.frame.pack_propagate(False)
        self.merged = False                 # True once it shares the menu bar's row
        self.divider = tk.Frame(parent, background=THEME["divider"], height=1)
        inset, gap = px(BAR_INSET), px(BAR_GAP)
        style = ttk.Style(parent)
        for name in ("Split.TButton", "Split.Secondary.TButton"):     # ▶ Play, ■ Stop
            style.configure(name, padding=(px(12), px(3)))
        for name in ("More.Split.TButton", "More.Split.Secondary.TButton"):     # the ▾
            style.configure(name, padding=(px(6), px(3)))

        def button(text: str, style: str, command: Callable[[], object], tip: str,
                   side: str = "left", pad: tuple[int, int] = (0, gap)) -> ttk.Button:
            widget = ttk.Button(self.frame, text=text, command=command, style=style)
            widget.pack(side=side, padx=pad)
            for key in ("<Return>", "<KP_Enter>"):          # Space works by itself
                widget.bind(key, lambda _e, w=widget: _press(w))
            widget.tooltip = Tooltip(widget, tip, tip_font)  # type: ignore[attr-defined]
            return widget

        self.play_button = button(PLAY, "TButton", on_play, TIP_PLAY, pad=(inset, gap))
        self.scene_button = button(PLAY_SCENE, "Secondary.TButton", on_scene, TIP_SCENE,
                                   pad=(0, px(6)))
        self.scene_label = ttk.Label(self.frame, text=BEGINNING, style="Side.Hint.TLabel")
        self.scene_label.pack(side="left", padx=(0, px(16)))
        self.stop_button = button(STOP, "Chrome.Ghost.TButton", on_stop, TIP_STOP)
        self.stop_button.state(["disabled"])
        self.options_button = button(PLAY_OPTIONS, "Chrome.Ghost.TButton", on_options,
                                     TIP_OPTIONS)
        self.guide_button = button(GUIDE, "Chrome.Ghost.TButton", on_guide, TIP_GUIDE,
                                   side="right", pad=(gap, inset))
        self.assistant_button: ttk.Button | None = None
        if on_assistant is not None:                    # F48: left of ? Guide
            self.assistant_button = button(ASSISTANT, "Chrome.Ghost.TButton", on_assistant,
                                           TIP_ASSISTANT, side="right", pad=(0, 0))
        # Play this scene, the scene name, Stop and Play options are made but never shown:
        # the split button's ▾ and the Run menu hold them (the run code keeps their state).
        self.run_widgets = (self.scene_button, self.scene_label, self.stop_button,
                            self.options_button)
        for widget in self.run_widgets:
            widget.pack_forget()
        self.running = False
        self._on_play, self._on_stop = on_play, on_stop
        self.play_button.configure(command=self._play_or_stop, style="Split.TButton",
                                   width=-max(len(PLAY), len(STOP)))
        self.play_button.pack_configure(padx=(inset, 1))   # a 1 px seam, then the ▾
        self.more_button = button(MORE, "More.Split.TButton", self.open_menu, TIP_MORE)
        self.more_button.configure(width=1)         # the theme's -9 would make it wide
        self.more_button.pack_configure(after=self.play_button)
        self.menu = tk.Menu(self.frame, tearoff=0)
        self.menu.add_command(label=PLAY_MENU_ROW, accelerator="Shift+F5", command=on_play)
        self.menu.add_command(label=PLAY_SCENE_MENU_ROW, accelerator="F5", command=on_scene)
        self.menu.add_command(label=PLAY_OPTIONS, command=on_options)
        self.buttons = (self.play_button, self.more_button,
                        *((self.assistant_button,) if self.assistant_button else ()),
                        self.guide_button)          # left to right on screen
        for widget in self.buttons:                       # a toolbar: arrows move along it
            widget.bind("<Left>", lambda _e, w=widget: self._step(w, -1))
            widget.bind("<Right>", lambda _e, w=widget: self._step(w, 1))
        for widget in (self.play_button, self.more_button):
            widget.bind("<Down>", lambda _e: self.open_menu() or "break")

    def merge_into(self, row: tk.Frame) -> None:
        """Share the in-window menu bar's row (Windows, Linux): the buttons sit right of the
        menu titles, the row grows to the bar's height, and the divider stays under it."""
        height = max(int(row.cget("height")), int(self.frame.cget("height")))
        row.configure(height=height)
        self.frame.pack_forget()
        self.frame.configure(background=str(row.cget("background")))
        self.frame.pack(in_=row, side="left", fill="both", expand=True,
                        padx=(round(BAR_GAP * scale_of(row)), 0))
        self.frame.lift(row)
        # Pack order is who keeps room in a narrow window: ▶ Play and its ▾, ? Guide, then
        # AI Assistant.
        keep = [self.play_button, self.more_button, self.guide_button,
                *((self.assistant_button,) if self.assistant_button else ())]
        packed = {str(w): w.pack_info() for w in keep}
        for widget in keep:
            widget.pack_forget()
        for widget in keep:
            info = {k: v for k, v in packed[str(widget)].items() if k != "in"}
            widget.pack(**info)
        self.merged = True

    def _step(self, widget: ttk.Button, step: int) -> str:
        enabled = [b for b in self.buttons if b is widget or not b.instate(["disabled"])]
        enabled[(enabled.index(widget) + step) % len(enabled)].focus_set()
        return "break"

    def set_running(self, running: bool) -> None:
        """While the game runs (or is starting) the split button reads ■ Stop in gray and
        the hidden Stop is enabled; at rest it reads ▶ Play in the accent."""
        self.stop_button.state(["!disabled"] if running else ["disabled"])
        if running == self.running:
            return
        self.running = running
        gray = "Secondary." if running else ""
        self.play_button.configure(text=STOP if running else PLAY,
                                   style=f"Split.{gray}TButton")
        self.more_button.configure(style=f"More.Split.{gray}TButton")
        self.play_button.tooltip.text = TIP_STOP if running else TIP_PLAY  # type: ignore

    def _play_or_stop(self) -> None:
        (self._on_stop if self.running else self._on_play)()

    def open_menu(self) -> None:
        """The ▾ menu, under the split button's left edge."""
        if not MENUS_POST:
            return
        x = self.play_button.winfo_rootx()
        y = self.more_button.winfo_rooty() + self.more_button.winfo_height()
        try:
            self.menu.tk_popup(x, y)
        finally:
            self.menu.grab_release()

    def add_check(self, label: str, variable: tk.Variable,
                  command: Callable[[], object]) -> None:
        """A switch at the ▾ menu's end, under a line (2.3's "Game beside Studio")."""
        self.menu.add_separator()
        self.menu.add_checkbutton(label=label, variable=variable, command=command)

    def set_scene(self, name: str | None) -> None:
        """What Play this scene plays now: the hidden name, and the ▾ menu's row."""
        text = name if name is not None else BEGINNING
        if self.scene_label.cget("text") != text:
            self.scene_label.configure(text=text)
            self.menu.entryconfigure(1, label=PLAY_SCENE_MENU_ROW if name is None
                                     else PLAY_SCENE_NAMED.format(name=name))

    def set_guide(self, shown: bool) -> None:
        """The Guide button looks pressed (secondary fill) while the Guide is shown."""
        self.guide_button.configure(style="Secondary.TButton" if shown
                                    else "Chrome.Ghost.TButton")

    def set_assistant(self, shown: bool) -> None:
        """AI Assistant looks pressed while the Assistant pane is shown (as ? Guide)."""
        if self.assistant_button is not None:
            self.assistant_button.configure(style="Secondary.TButton" if shown
                                            else "Chrome.Ghost.TButton")


def _press(widget: ttk.Button) -> str:
    if not widget.instate(["disabled"]):
        widget.invoke()
    return "break"


def ask_play_options(parent: tk.Misc, values: str, fresh: bool, *,
                     font: object = None) -> tuple[str, bool] | None:
    """The Play options dialog (PR-F47-09, §6.4): the start values box (one ``name =
    value`` per line, checked when Play starts) and "Play as a new player". Returns
    ``(values, fresh)`` for OK, None for Cancel, Esc or the close box."""
    dialog = dialogs._dialog(parent)
    dialog.title(OPTIONS_TITLE)
    result: list[tuple[str, bool] | None] = [None]
    ticked = tk.BooleanVar(dialog, value=fresh)
    body, scale = dialogs._body(dialog)
    px = lambda value: round(value * scale)       # noqa: E731
    ttk.Label(body, text=START_VALUES_HEADING, style="Dialog.TLabel").pack(anchor="w")
    ttk.Label(body, text=START_VALUES_HINT, style="Dialog.Hint.TLabel").pack(anchor="w")
    box = tk.Text(body, height=START_VALUES_ROWS, width=44, wrap="none", undo=True,
                  maxundo=-1, background=INPUT_BACKGROUND, foreground=PLAIN_COLOR,
                  insertbackground=CURSOR_COLOR, insertwidth=px(CURSOR_WIDTH),
                  selectbackground=SELECTION_BACKGROUND,
                  inactiveselectbackground=INACTIVE_SELECTION, padx=px(8), pady=px(TEXT_PAD),
                  highlightthickness=1, highlightbackground=INPUT_BORDER,
                  highlightcolor=FOCUS_BORDER, borderwidth=0, relief="flat")
    if font is not None:
        box.configure(font=font)
    box.tag_configure("sel", foreground=PLAIN_COLOR)
    box.insert("1.0", values)
    box.pack(anchor="w", fill="x", pady=(px(4), 0))
    ttk.Checkbutton(body, text=FRESH, variable=ticked, style="Dialog.TCheckbutton").pack(
        anchor="w", pady=(px(12), 0))

    def pick(index: int) -> None:
        if index == 0:
            result[0] = (box.get("1.0", "end-1c"), bool(ticked.get()))
        dialog.destroy()

    dialogs._buttons(dialog, body, (OPTIONS_OK, "Cancel"), pick)
    dialog.bind("<Escape>", lambda _e: pick(1))
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(1))
    box.mark_set("insert", "end-1c")
    dialogs._run(parent, dialog, box)
    return result[0]


__all__ = ["ASSISTANT", "BEGINNING", "FRESH", "GUIDE", "MORE", "OPTIONS_TITLE", "PLAY",
           "PLAY_OPTIONS", "PLAY_SCENE", "PLAY_SCENE_NAMED", "TIP_MORE", "START_VALUES_HEADING", "START_VALUES_HINT", "STOP", "TIP_PLAY",
           "TIP_SCENE", "TIP_STOP", "PlayBar", "Tooltip", "ask_play_options"]
