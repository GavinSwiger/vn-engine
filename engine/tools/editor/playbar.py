"""Studio's Play bar and its Play options dialog (F47 ``01-design.md`` PR-F47-07..09, §6.1,
§6.4; ``04-technical.md`` §3.2, §7.4).

Why this module exists: playing the game is the one thing every author does all the time, so
it gets a 36 px toolbar on ``chrome`` under the menu bar, across the window, instead of F44's
small button at the bottom of the left column::

    [▶ Play] [▶ Play this scene] club_poem  [■ Stop]  Play options…  [AI Assistant] [? Guide]

**▶ Play** is the window's one primary button (from the start, Shift+F5). **▶ Play this
scene** is secondary (F5) and the muted name after it says which scene that is. **■ Stop**
(Ctrl+F2) is a ghost button, enabled only while the game runs. **Play options…** opens the
dialog that holds the start values and "Play as a new player"; **? Guide** toggles the
Guide pane and F48's **AI Assistant**, left of it, the Assistant pane (they share the
column). Each button has a tooltip; Left and Right move between the bar's buttons.

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
PLAY_SCENE = "▶ Play this scene"
STOP = "■ Stop"
PLAY_OPTIONS = "Play options…"
GUIDE = "? Guide"
ASSISTANT = "AI Assistant"              # F48 01 §6.1
BEGINNING = "the beginning"             # what Play this scene plays with no scene chosen

TIP_PLAY = "Play from the start (Shift+F5)"
TIP_SCENE = "Play from the selected scene (F5)"
TIP_STOP = "Stop the game (Ctrl+F2)"
TIP_OPTIONS = "Start values, and playing as a new player"
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
        # Play, Play this scene, the scene name, Stop and Play options live in the Run menu
        # only (2026-11-04: one place to run the game). They are still made, so the run
        # code keeps their state, but never shown; the bar holds the pane toggles.
        self.run_widgets = (self.play_button, self.scene_button, self.scene_label,
                            self.stop_button, self.options_button)
        for widget in self.run_widgets:
            widget.pack_forget()
        self.buttons = (*((self.assistant_button,) if self.assistant_button else ()),
                        self.guide_button)          # left to right on screen
        for widget in self.buttons:                       # a toolbar: arrows move along it
            widget.bind("<Left>", lambda _e, w=widget: self._step(w, -1))
            widget.bind("<Right>", lambda _e, w=widget: self._step(w, 1))

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
        # Pack order is who keeps room in a narrow window: ? Guide, then AI Assistant.
        keep = [self.guide_button,
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
        """Stop is enabled only while the game runs (or is starting)."""
        self.stop_button.state(["!disabled"] if running else ["disabled"])

    def set_scene(self, name: str | None) -> None:
        text = name if name is not None else BEGINNING
        if self.scene_label.cget("text") != text:
            self.scene_label.configure(text=text)

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


__all__ = ["ASSISTANT", "BEGINNING", "FRESH", "GUIDE", "OPTIONS_TITLE", "PLAY", "PLAY_OPTIONS",
           "PLAY_SCENE", "START_VALUES_HEADING", "START_VALUES_HINT", "STOP", "TIP_PLAY",
           "TIP_SCENE", "TIP_STOP", "PlayBar", "Tooltip", "ask_play_options"]
