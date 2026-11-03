"""The Positions canvas (F47 ``01-design.md`` §4.3 "Positions"; AC-F47-40).

Why this module exists: a stage position is a point on the 1280×720 canvas where a
character's picture stands (its bottom centre). Numbers in ``config.toml`` mean little to a
non-programmer, so the Database draws the stage, scaled, with one marker per position, and
the author drags a marker where the character should stand. ``StageCanvas`` is only the
drawing and the dragging: it calls ``on_pick(name)`` when a marker is pressed and
``on_move(name, x, y)`` (canvas units, whole numbers) when one is dropped or nudged with
the arrow keys; the Database writes ``[stage.positions]``. A drop within ``SNAP_BOTTOM``
units of the bottom edge lands on it (y 720 is written as x alone). Imports the standard
library, ``tkinter`` and its own package; never pygame.
"""

import tkinter as tk
from collections.abc import Callable, Sequence
from typing import Any

from engine.core.constants import CANVAS_SIZE
from engine.tools.editor.theme import ROLES, THEME

STAGE_W, STAGE_H = CANVAS_SIZE
SNAP_BOTTOM = 12                # canvas units: a drop this close to the floor lands on it
NUDGE = 8                       # canvas units per arrow key (Shift: 1)
FIGURE_W, FIGURE_H = 220, 520   # the ghost figure drawn above each marker, canvas units
MARKER_PX = 7                   # the marker's radius at 100 %
PAD_PX = 14                     # room around the stage for markers on its edge


class StageCanvas:
    """``widget``: a canvas showing the stage at ``width`` px (16:9) with ``points``
    (name → (x, y)) as markers; ``selected`` is drawn in the accent colour, with a ghost
    figure standing on it."""

    def __init__(self, parent: tk.Misc, *, width: int, scale: float = 1.0,
                 font: Any = None,
                 on_pick: Callable[[str], object] | None = None,
                 on_move: Callable[[str, float, float], object] | None = None) -> None:
        self.scale = scale
        self.pad = round(PAD_PX * scale)
        self.w = width
        self.h = round(width * STAGE_H / STAGE_W)
        self.font = font
        self.on_pick, self.on_move = on_pick, on_move
        self.points: dict[str, tuple[float, float]] = {}
        self.locked: set[str] = set()          # markers that can't move (Edit as script)
        self.selected: str | None = None
        self.dragging: str | None = None
        self.moved = False
        self.widget = self.canvas = tk.Canvas(
            parent, width=self.w + 2 * self.pad, height=self.h + 2 * self.pad,
            background=THEME["editor.background"], highlightthickness=1,
            highlightbackground=THEME["editor.background"],
            highlightcolor=THEME["focusBorder"], borderwidth=0, takefocus=1)
        c = self.canvas
        c.bind("<ButtonPress-1>", self._press, add="+")
        c.bind("<B1-Motion>", self._motion, add="+")
        c.bind("<ButtonRelease-1>", self._release, add="+")
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            c.bind(f"<{key}>", lambda _e, x=dx, y=dy: (self.nudge(x * NUDGE, y * NUDGE),
                                                       "break")[1])
            c.bind(f"<Shift-{key}>", lambda _e, x=dx, y=dy: (self.nudge(x, y), "break")[1])

    def resize(self, width: int) -> None:
        """Draw the stage ``width`` px wide (the form got narrower or wider)."""
        if width == self.w or width <= 0:
            return
        self.w, self.h = width, round(width * STAGE_H / STAGE_W)
        self.canvas.configure(width=self.w + 2 * self.pad, height=self.h + 2 * self.pad)
        self.draw()

    # --- Coordinates --------------------------------------------------------------------

    def to_canvas(self, x: float, y: float) -> tuple[float, float]:
        """Stage units → canvas pixels (clamped to the drawn area)."""
        cx = self.pad + max(0.0, min(STAGE_W, x)) * self.w / STAGE_W
        cy = self.pad + max(0.0, min(STAGE_H, y)) * self.h / STAGE_H
        return cx, cy

    def to_stage(self, cx: float, cy: float) -> tuple[float, float]:
        """Canvas pixels → whole stage units on the stage; near the floor snaps to it."""
        x = round((cx - self.pad) * STAGE_W / self.w)
        y = round((cy - self.pad) * STAGE_H / self.h)
        x, y = max(0, min(STAGE_W, x)), max(0, min(STAGE_H, y))
        if STAGE_H - y <= SNAP_BOTTOM:
            y = STAGE_H
        return float(x), float(y)

    # --- Showing ------------------------------------------------------------------------

    def set_points(self, points: Sequence[tuple[str, float, float]], selected: str | None,
                   locked: Sequence[str] = ()) -> None:
        if self.dragging is not None:
            return                                 # don't jump under the pointer
        self.points = {name: (x, y) for name, x, y in points}
        self.locked = set(locked)
        self.selected = selected
        self.draw()

    def draw(self) -> None:
        c, px = self.canvas, self.scale
        c.delete("all")
        x0, y0 = self.pad, self.pad
        x1, y1 = x0 + self.w, y0 + self.h
        c.create_rectangle(x0, y0, x1, y1, fill=ROLES["raised"], outline=ROLES["border"])
        for k in (1, 2, 3):                         # the quarters left/center/right stand on
            gx = x0 + self.w * k / 4
            c.create_line(gx, y0, gx, y1, fill=ROLES["divider"], dash=(2, 4))
        c.create_line(x0, y1, x1, y1, fill=ROLES["muted"], width=max(1, round(2 * px)))
        order = [n for n in self.points if n != self.selected]
        if self.selected in self.points:
            order.append(self.selected)
        for name in order:
            self._marker(name)

    def _marker(self, name: str) -> None:
        c, px = self.canvas, self.scale
        x, y = self.points[name]
        cx, cy = self.to_canvas(x, y)
        on = name == self.selected
        color = ROLES["accent"] if on else ROLES["muted"]
        if on:                                      # a ghost figure standing on the marker
            fw = FIGURE_W * self.w / STAGE_W / 2
            fh = FIGURE_H * self.h / STAGE_H
            top = self.pad                          # the figure stays on the stage
            head = max(top, cy - fh)
            c.create_oval(cx - fw * 0.45, head, cx + fw * 0.45, max(head + 2, cy - fh * 0.78),
                          outline=color, dash=(3, 3), tags=("figure",))
            c.create_rectangle(cx - fw, max(top, cy - fh * 0.78), cx + fw, cy, outline=color,
                               dash=(3, 3), tags=("figure",))
        r = round(MARKER_PX * px)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color if on else ROLES["raised"],
                      outline=color, width=max(1, round(2 * px)), tags=("marker", f"m:{name}"))
        c.create_text(cx, cy - r - round(4 * px), text=name, anchor="s",
                      fill=ROLES["textStrong"] if on else ROLES["text"], font=self.font,
                      tags=("label", f"m:{name}"))

    # --- Dragging -----------------------------------------------------------------------

    def marker_at(self, cx: float, cy: float) -> str | None:
        """The marker nearest pixel ``(cx, cy)`` within reach (the selected one first)."""
        reach = round((MARKER_PX + 8) * self.scale)
        best: tuple[float, int, str] | None = None
        for name, (x, y) in self.points.items():
            mx, my = self.to_canvas(x, y)
            d = ((mx - cx) ** 2 + (my - cy) ** 2) ** 0.5
            if d <= reach:
                key = (d, 0 if name == self.selected else 1, name)
                best = key if best is None or key < best else best
        return best[2] if best else None

    def _press(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        name = self.marker_at(event.x, event.y)
        if name is None:
            return
        self.moved = False
        if name != self.selected:
            self.selected = name
            if self.on_pick is not None:
                self.on_pick(name)
            self.draw()
        self.dragging = name if name not in self.locked else None
        if self.dragging is not None:
            self.canvas.configure(cursor="fleur")

    def _motion(self, event: tk.Event) -> None:
        name = self.dragging
        if name is None:
            return
        self.points[name] = self.to_stage(event.x, event.y)
        self.moved = True
        self.draw()

    def _release(self, event: tk.Event) -> None:
        name, self.dragging = self.dragging, None
        self.canvas.configure(cursor="")
        if name is None or not self.moved:
            return
        x, y = self.to_stage(event.x, event.y)
        self.points[name] = (x, y)
        self.draw()
        if self.on_move is not None:
            self.on_move(name, x, y)

    def nudge(self, dx: float, dy: float) -> None:
        """Move the selected marker by ``(dx, dy)`` stage units (arrow keys)."""
        name = self.selected
        if name is None or name not in self.points or name in self.locked:
            return
        x, y = self.points[name]
        x = max(0.0, min(float(STAGE_W), x + dx))
        y = max(0.0, min(float(STAGE_H), y + dy))
        self.points[name] = (x, y)
        self.draw()
        if self.on_move is not None:
            self.on_move(name, x, y)


__all__ = ["NUDGE", "SNAP_BOTTOM", "STAGE_H", "STAGE_W", "StageCanvas"]
