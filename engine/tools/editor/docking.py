"""Studio's movable panes: drag a pane's header to the left, right or bottom edge, close it
with ✕, bring it back from View, lock the layout, or reset it.

Why this module exists: authors arrange their workspace differently (the AI Assistant under
the editor, no Help pane, …), and the window should keep that per game.

- Docks: ``left`` and ``right`` stack their panes top to bottom beside the tabs; ``bottom``
  puts its panes side by side under them. A dock with no pane shown takes no space.
- Panes: ``project``, ``problems``, ``help``, ``guide``, ``assistant``. Every pane frame is
  a child of the window's main container, so any dock (a ``tk.PanedWindow`` inside it) can
  hold it.
- ``Layout`` (pure, frozen): which dock each pane is in, their order, the panes the author
  closed (Project, Problems, Help; the Guide and the Assistant keep their own open flags),
  and ``locked``. Kept in ``.studio/studio.json`` as ``panes`` (``to_json``/``from_json``;
  anything odd falls back to the default, which is Studio's usual layout).
- ``DockWiring`` (window mixin): ``_build_docks()`` after the panes exist, ``dock_apply()``
  whenever a pane is shown, hidden or moved, the header drag (an outline shows where the pane
  will go), the ✕ buttons, and View's pane rows.

Imports ``tkinter`` and its own package.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from tkinter import ttk
from typing import Any, Final

from engine.tools.editor.studiolook import (
    BOTTOM_MIN_WIDTH, LEFT_MIN_WIDTH, LEFT_WIDTH, PROBLEMS_HEIGHT, PROBLEMS_MIN_HEIGHT,
    PROBLEMS_SHARE, SASH_WIDTH)
from engine.tools.editor.theme import THEME

PROJECT: Final = "project"
PROBLEMS: Final = "problems"
HELP: Final = "help"
GUIDE: Final = "guide"
ASSISTANT: Final = "assistant"
PANES: Final = (PROJECT, PROBLEMS, HELP, GUIDE, ASSISTANT)
CLOSABLE: Final = (PROJECT, PROBLEMS, HELP)        # the others have their own close
LEFT: Final = "left"
RIGHT: Final = "right"
BOTTOM: Final = "bottom"
DOCKS: Final = (LEFT, RIGHT, BOTTOM)
DEFAULT_DOCKS: Final = {PROJECT: LEFT, PROBLEMS: BOTTOM, HELP: BOTTOM, GUIDE: RIGHT,
                        ASSISTANT: RIGHT}

# --- Texts ---------------------------------------------------------------------------------------

PANE_TITLES: Final = {PROJECT: "Project", PROBLEMS: "Problems", HELP: "Help", GUIDE: "Guide",
                      ASSISTANT: "AI Assistant"}
LOCK_MENU: Final = "Lock pane layout"
RESET_MENU: Final = "Reset pane layout"
CLOSE: Final = "✕"
TIP_CLOSE: Final = "Hide this pane (View brings it back)"
TIP_DRAG: Final = "Drag to the left, right or bottom edge to move this pane"

# --- Look (px at 100 %) --------------------------------------------------------------------------

SIDE_WIDTH: Final = 280                 # a right dock's first width
DRAG_START_PX: Final = 8                # the pointer moves this far before a drag starts
EDGE_SHARE: Final = 0.22                # left and right drop zones: this share of the width
BOTTOM_SHARE: Final = 0.30              # the bottom drop zone: this share of the height
OUTLINE_PX: Final = 3


# --- The layout (pure) -------------------------------------------------------------------------

@dataclass(frozen=True)
class Layout:
    docks: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_DOCKS))
    order: tuple[str, ...] = PANES
    hidden: frozenset[str] = frozenset()
    locked: bool = False

    def dock_of(self, pane: str) -> str:
        return self.docks.get(pane, DEFAULT_DOCKS[pane])

    def in_dock(self, dock: str) -> list[str]:
        """The dock's panes in order (shown or not)."""
        return [pane for pane in self.order if self.dock_of(pane) == dock]

    def moved(self, pane: str, dock: str) -> "Layout":
        """``pane`` at the end of ``dock``."""
        order = tuple(p for p in self.order if p != pane) + (pane,)
        return replace(self, docks={**self.docks, pane: dock}, order=order)

    def shown(self, pane: str, on: bool) -> "Layout":
        hidden = self.hidden - {pane} if on else self.hidden | {pane}
        return replace(self, hidden=frozenset(hidden & set(CLOSABLE)))

    @property
    def is_default(self) -> bool:
        return self == Layout()

    def to_json(self) -> dict:
        return {"docks": {pane: self.dock_of(pane) for pane in PANES},
                "order": list(self.order), "hidden": sorted(self.hidden),
                "locked": self.locked}

    @classmethod
    def from_json(cls, data: object) -> "Layout":
        """The saved layout; anything not understood keeps its default."""
        if not isinstance(data, dict):
            return cls()
        docks = dict(DEFAULT_DOCKS)
        found = data.get("docks")
        if isinstance(found, dict):
            docks.update({pane: dock for pane, dock in found.items()
                          if pane in PANES and dock in DOCKS})
        order = data.get("order")
        if not (isinstance(order, list) and sorted(order) == sorted(PANES)):
            order = list(PANES)
        hidden = data.get("hidden")
        hidden = frozenset(p for p in hidden if p in CLOSABLE) if isinstance(hidden, list) \
            else frozenset()
        return cls(docks, tuple(order), hidden, data.get("locked") is True)


def drop_zone(x: int, y: int, width: int, height: int) -> str | None:
    """The dock a pane dropped at (x, y) inside the work area goes to, or None (middle)."""
    if not (0 <= x < width and 0 <= y < height):
        return None
    if x < width * EDGE_SHARE:
        return LEFT
    if x >= width * (1 - EDGE_SHARE):
        return RIGHT
    if y >= height * (1 - BOTTOM_SHARE):
        return BOTTOM
    return None


def zone_box(zone: str, width: int, height: int) -> tuple[int, int, int, int]:
    """(x, y, width, height) of the outline shown for ``zone`` in the work area."""
    side = max(1, int(width * EDGE_SHARE))
    if zone == LEFT:
        return 0, 0, side, height
    if zone == RIGHT:
        return width - side, 0, side, height
    tall = max(1, int(height * BOTTOM_SHARE))
    return 0, height - tall, width, tall


# --- The window mixin --------------------------------------------------------------------------

class DockWiring:
    """Docks and panes in the window (``EditorWindow`` mixes this in)."""

    layout: Layout
    dock_vars: dict[str, tk.BooleanVar]

    def _build_docks(self) -> None:
        """After every pane exists: the left and right docks, the saved layout, the header
        drags and ✕ buttons, then the panes in their places."""
        sash, sash_width = THEME["sash"], self._px(SASH_WIDTH)
        self.left_dock = tk.PanedWindow(self.hpane, orient="vertical", sashwidth=sash_width,
                                        borderwidth=0, sashrelief="flat", background=sash)
        self.right_dock = tk.PanedWindow(self.hpane, orient="vertical", sashwidth=sash_width,
                                         borderwidth=0, sashrelief="flat", background=sash)
        self.dock_of = {LEFT: self.left_dock, RIGHT: self.right_dock, BOTTOM: self.bottom}
        self.pane_frames = {PROJECT: self.left, PROBLEMS: self.problems_frame,
                            HELP: self.help_pane.frame, GUIDE: self.guide_pane.frame,
                            ASSISTANT: self.assist_pane.frame}
        self.layout = self._saved_layout()
        self.dock_vars = {pane: tk.BooleanVar(master=self.root, value=pane not in
                                              self.layout.hidden) for pane in CLOSABLE}
        self.lock_var = tk.BooleanVar(master=self.root, value=self.layout.locked)
        self._dragging: dict[str, Any] | None = None
        self._outline: list[tk.Frame] = []
        for pane, frame in self.pane_frames.items():
            header = header_of(frame)
            if header is None:
                continue
            if pane in CLOSABLE:
                self._add_close(header, pane)
            for widget in (header, *header.winfo_children()):
                if isinstance(widget, (ttk.Button, tk.Button)):
                    continue
                widget.bind("<ButtonPress-1>", lambda e, p=pane: self._drag_press(p, e),
                            add="+")
                widget.bind("<B1-Motion>", lambda e, p=pane: self._drag_motion(p, e), add="+")
                widget.bind("<ButtonRelease-1>", lambda e, p=pane: self._drag_release(p, e),
                            add="+")
        self.dock_apply()

    def _saved_layout(self) -> Layout:
        from engine.tools.editor import studiostate
        state = studiostate.read_state(self.paths.root)
        panes = getattr(state, "panes", None)
        return Layout.from_json(panes) if panes else Layout()

    def _add_close(self, header: tk.Misc, pane: str) -> None:
        button = ttk.Button(header, text=CLOSE, width=3, takefocus=0,
                            command=lambda: self.show_pane(pane, False),
                            style="Chrome.Ghost.TButton")
        button.pack(side="right", padx=(0, self._px(4)))
        from engine.tools.editor.playbar import Tooltip
        Tooltip(button, TIP_CLOSE, self.fonts.get("small"))

    # -- what is shown where ---------------------------------------------------------------------

    def pane_wanted(self, pane: str) -> bool:
        """The pane should be shown (the Guide and the Assistant: their own flags)."""
        if pane == GUIDE:
            return bool(getattr(self, "_guide_wanted", False))
        if pane == ASSISTANT:
            return bool(getattr(self, "assistant_shown", False))
        return pane not in self.layout.hidden

    def pane_shown(self, pane: str) -> bool:
        return bool(self.pane_frames[pane].winfo_manager())

    def same_dock(self, a: str, b: str) -> bool:
        layout = getattr(self, "layout", None) or self._saved_layout()
        return layout.dock_of(a) == layout.dock_of(b)

    def dock_apply(self) -> None:
        """Put every wanted pane in its dock, in order, and show only docks with panes. A
        dock whose panes didn't change keeps its sizes. Nothing before ``_build_docks``."""
        if not hasattr(self, "dock_of"):
            return
        for dock, window in self.dock_of.items():
            wanted = [self.pane_frames[p] for p in self.layout.in_dock(dock)
                      if self.pane_wanted(p)]
            current = [self.root.nametowidget(str(name)) for name in window.panes()]
            if current != wanted:
                for frame in current:
                    window.forget(frame)
                along = "height" if dock in (LEFT, RIGHT) else "width"
                room = window.winfo_height() if dock in (LEFT, RIGHT) else window.winfo_width()
                if room <= 1:
                    room = self.hpane.winfo_height() if dock in (LEFT, RIGHT) \
                        else self.vpane.winfo_width()
                share = max(1, room // max(1, len(wanted)))     # even shares to begin with
                for frame in wanted:
                    pane = next(p for p, f in self.pane_frames.items() if f is frame)
                    window.add(frame, minsize=self._px(self._pane_min(pane, dock)),
                               stretch="always", **{along: share})
                    frame.lift()
                if dock == BOTTOM and len(wanted) > 1:
                    self._help_sash_placed = False
            self._show_dock(dock, bool(wanted))
        self.root.after(50, self._even_docks)

    def _pane_min(self, pane: str, dock: str) -> int:
        if dock == BOTTOM:
            return BOTTOM_MIN_WIDTH
        return 80 if pane != PROJECT else 120

    def _show_dock(self, dock: str, on: bool) -> None:
        window = self.dock_of[dock]
        holder = self.vpane if dock == BOTTOM else self.hpane
        shown = str(window) in [str(name) for name in holder.panes()]
        if on == shown:
            return
        if not on:
            holder.forget(window)
            return
        px = self._px
        if dock == BOTTOM:
            holder.add(window, after=self.tab_area, height=px(PROBLEMS_HEIGHT),
                       minsize=px(PROBLEMS_MIN_HEIGHT), stretch="never")
        elif dock == LEFT:
            holder.add(window, before=self.vpane, width=px(LEFT_WIDTH),
                       minsize=px(LEFT_MIN_WIDTH), stretch="never")
        else:
            holder.add(window, after=self.vpane, width=px(SIDE_WIDTH),
                       minsize=px(LEFT_MIN_WIDTH), stretch="never")

    def _even_docks(self) -> None:
        """Panes sharing a dock start with even shares (Problems 60 % beside Help)."""
        if getattr(self, "closed", False):
            return
        for dock, window in self.dock_of.items():
            panes = window.panes()
            if len(panes) < 2:
                continue
            if dock == BOTTOM and getattr(self, "_help_sash_placed", False):
                continue
            size = window.winfo_width() if dock == BOTTOM else window.winfo_height()
            if size <= 1:
                continue
            names = [str(name) for name in panes]
            problems = str(self.pane_frames[PROBLEMS])
            shares = [1 / len(panes)] * len(panes)
            if dock == BOTTOM and len(panes) == 2 and names[0] == problems:
                shares = [PROBLEMS_SHARE, 1 - PROBLEMS_SHARE]
            along = "width" if dock == BOTTOM else "height"
            for name, share in zip(panes, shares):   # the pane sizes, so a relayout keeps them
                window.paneconfigure(name, **{along: max(1, int(size * share))})
            if dock == BOTTOM:
                self._help_sash_placed = True

    # -- View rows ----------------------------------------------------------------------------

    def show_pane(self, pane: str, on: bool) -> None:
        """View ▸ Project / Problems / Help, and their ✕."""
        if pane not in CLOSABLE:
            return
        self.layout = self.layout.shown(pane, on)
        self.dock_vars[pane].set(on)
        self.dock_apply()
        self._save_layout()

    def toggle_pane(self, pane: str) -> None:
        """View's check row: the variable already holds the new value."""
        self.show_pane(pane, bool(self.dock_vars[pane].get()))

    def toggle_lock(self) -> None:
        self.layout = replace(self.layout, locked=bool(self.lock_var.get()))
        self._save_layout()

    def reset_layout(self) -> None:
        """View ▸ Reset pane layout: every pane back in its first place, shown, unlocked."""
        self.layout = Layout()
        for var in self.dock_vars.values():
            var.set(True)
        self.lock_var.set(False)
        self._help_sash_placed = False
        if self.pane_wanted(GUIDE) and self.pane_wanted(ASSISTANT):
            self.toggle_guide()                 # back in one dock: one at a time again
        self.dock_apply()
        self._save_layout()

    def move_pane(self, pane: str, dock: str) -> None:
        """``pane`` to the end of ``dock`` (a drop, or tests)."""
        if dock not in DOCKS or self.layout.dock_of(pane) == dock:
            return
        self.layout = self.layout.moved(pane, dock)
        if pane in (GUIDE, ASSISTANT):          # they share a dock only one at a time
            other = ASSISTANT if pane == GUIDE else GUIDE
            if self.same_dock(pane, other) and self.pane_wanted(pane) and \
                    self.pane_wanted(other):
                if other == GUIDE:
                    self.toggle_guide()
                else:
                    self.show_assistant(False)
        self.dock_apply()
        self._save_layout()

    def _save_layout(self) -> None:
        self.save_studio_state(panes=None if self.layout.is_default else self.layout.to_json())

    # -- dragging a header -------------------------------------------------------------------

    def _drag_press(self, pane: str, event: tk.Event) -> None:
        self._dragging = {"pane": pane, "x": event.x_root, "y": event.y_root, "on": False,
                          "zone": None}

    def _drag_motion(self, pane: str, event: tk.Event) -> None:
        drag = self._dragging
        if drag is None or drag["pane"] != pane or self.layout.locked:
            return
        if not drag["on"]:
            if abs(event.x_root - drag["x"]) + abs(event.y_root - drag["y"]) < \
                    self._px(DRAG_START_PX):
                return
            drag["on"] = True
            self.root.configure(cursor="fleur")
        zone = self._zone_at(event.x_root, event.y_root)
        if zone != drag["zone"]:
            drag["zone"] = zone
            self._show_outline(zone)

    def _drag_release(self, pane: str, event: tk.Event) -> None:
        drag, self._dragging = self._dragging, None
        if drag is None or not drag["on"]:
            return
        self.root.configure(cursor="")
        self._show_outline(None)
        zone = self._zone_at(event.x_root, event.y_root)
        if zone is not None and not self.layout.locked:
            self.move_pane(pane, zone)

    def _zone_at(self, x_root: int, y_root: int) -> str | None:
        area = self.hpane
        return drop_zone(x_root - area.winfo_rootx(), y_root - area.winfo_rooty(),
                         area.winfo_width(), area.winfo_height())

    def _show_outline(self, zone: str | None) -> None:
        """Four thin bars round the drop zone (none for None)."""
        for bar in self._outline:
            bar.place_forget()
        if zone is None:
            return
        if not self._outline:
            self._outline = [tk.Frame(self.hpane.master, background=THEME["focusBorder"])
                             for _ in range(4)]
        area = self.hpane
        x, y, width, height = zone_box(zone, area.winfo_width(), area.winfo_height())
        x += area.winfo_x()
        y += area.winfo_y()
        line = self._px(OUTLINE_PX)
        for bar, (bx, by, bw, bh) in zip(self._outline, (
                (x, y, width, line), (x, y + height - line, width, line),
                (x, y, line, height), (x + width - line, y, line, height))):
            bar.place(x=bx, y=by, width=bw, height=bh)
            bar.lift()


def header_of(frame: tk.Misc) -> tk.Misc | None:
    """A pane's header strip (``views.panel_header``): its first ``Header.TFrame`` child."""
    for child in frame.winfo_children():
        try:
            if str(child.cget("style")) == "Header.TFrame":
                return child
        except tk.TclError:
            continue
    return None


__all__ = ["ASSISTANT", "BOTTOM", "CLOSABLE", "DOCKS", "DockWiring", "GUIDE", "HELP", "LEFT",
           "LOCK_MENU", "Layout", "PANES", "PANE_TITLES", "PROBLEMS", "PROJECT", "RESET_MENU",
           "RIGHT", "drop_zone", "header_of", "zone_box"]
