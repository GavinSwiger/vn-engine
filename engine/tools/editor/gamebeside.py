"""Where Studio opens the game: beside its own window (proposal 2.3, "snap", 2026-11-06).

Why this module exists: a game that opens in the middle of the screen covers the script the
author is editing. When Play starts the game, Studio works out a spot beside its window and
passes it as ``run --window-at=X,Y --window-size=W,H`` (the game's drawing area, in screen
pixels; both processes are DPI aware on Windows, so Tk's and SDL's pixels agree):

- **Room beside Studio** (right first, then left; at least the engine's smallest window):
  the game opens there, level with Studio's top, at its own size or smaller (its shape kept).
- **No room** (Studio fills the screen) with **Game beside Studio** ticked (Run menu and the
  ▶ Play ▾ menu, remembered for this person in ``uiprefs``): Studio makes room. It leaves
  maximized and takes the left part of its screen; the game gets the right ``SHARE``.
  When the game ends, Studio goes back the way it was, unless it was moved or resized
  meanwhile.
- Otherwise nothing is added and the game opens where it always did (centered).

Hot reload keeps the spot: ``hotreload.resume_argv`` passes the old window's place, or keeps
Play's ``--window-at``; ``--window-size`` always stays.

Limits: Windows asks the system for the work area of the monitor Studio is on (taskbar left
out). macOS and Linux use Tk's screen size from the top-left corner, so a second monitor or
a dock isn't seen. The game's title bar is taken to be as tall as Studio's. A game the
player put in fullscreen (F11, kept in its settings) still opens fullscreen. Moving Studio
later doesn't move the game.

``place_game`` is pure (tests call it with numbers); ``studio_rect``, ``work_area`` and
``make_room`` read and move the Tk window. Imports only the standard library and
``engine.core.constants``.
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass

from engine.core.constants import MIN_WINDOW_SIZE

PLACES = True                           # tests set False: Play places nothing, moves nothing
MENU = "Game beside Studio"             # Run menu and ▶ Play ▾ check (remembered per person)
GAP = 8                                 # px at 100 %: between Studio and the game
SHARE = 0.45                            # the game's part of a shared screen
CAPTION = 32                            # px at 100 %: a title bar, when Tk can't measure one
WINDOW_AT = "--window-at"
WINDOW_SIZE = "--window-size"


@dataclass(frozen=True)
class Rect:
    """A screen rectangle in pixels."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


@dataclass(frozen=True)
class Placement:
    """``game``: the game's drawing area (``--window-at`` and ``--window-size``).
    ``studio``: Studio's new drawing area when it makes room, else None."""

    game: Rect
    studio: Rect | None = None

    def argv(self) -> list[str]:
        """The two options, each one argv item (a negative X isn't read as an option)."""
        g = self.game
        return [f"{WINDOW_AT}={g.x},{g.y}", f"{WINDOW_SIZE}={g.w},{g.h}"]


def _fit(width: int, height: int, natural: tuple[int, int]) -> tuple[int, int]:
    """The largest size of ``natural``'s shape inside ``width`` × ``height``, never larger
    than ``natural``."""
    nw, nh = natural
    w = min(width, nw, height * nw // nh)
    return w, w * nh // nw


def place_game(studio: Rect, work: Rect, natural: tuple[int, int], *, caption: int,
               gap: int, share: bool) -> Placement | None:
    """Where the game opens. ``studio`` is Studio's drawing area with its title bar
    (``y`` is the title bar's top); ``work`` the work area of Studio's monitor; ``natural``
    the game's own window size in pixels; ``caption`` a title bar's height. None: no spot
    (the game opens where it always did)."""
    min_w, min_h = MIN_WINDOW_SIZE
    natural = (max(natural[0], 1), max(natural[1], 1))
    top = max(studio.y, work.y)
    tall = work.bottom - top - caption
    for room, right in ((work.right - studio.right - gap, True),
                        (studio.x - work.x - gap, False)):
        w, h = _fit(room, tall, natural)
        if w >= min_w and h >= min_h:
            x = studio.right + gap if right else studio.x - gap - w
            return Placement(Rect(x, top + caption, w, h))
    if not share:
        return None
    w, h = _fit(round(work.w * SHARE), work.h - caption, natural)
    if w < min_w or h < min_h:
        return None                     # a screen too small to share
    game = Rect(work.right - w, work.y + caption, w, h)
    return Placement(game, Rect(work.x, work.y + caption, work.w - w - gap, work.h - caption))


# --- The Tk side -----------------------------------------------------------------------------

def caption_of(root: tk.Misc, scale: float) -> int:
    """Studio's title bar height (``CAPTION`` when Tk can't tell, as when maximized)."""
    try:
        measured = root.winfo_rooty() - root.winfo_y()
    except tk.TclError:
        measured = 0
    return measured if 8 <= measured <= 200 else round(CAPTION * scale)


def studio_rect(root: tk.Misc, caption: int) -> Rect:
    """Studio's drawing area with its title bar above it."""
    return Rect(root.winfo_rootx(), root.winfo_rooty() - caption, root.winfo_width(),
                root.winfo_height() + caption)


def work_area(root: tk.Misc) -> Rect:
    """The work area of the monitor Studio is on (Windows), else Tk's screen size."""
    if sys.platform == "win32":
        found = _windows_work_area(root)
        if found is not None:
            return found
    return Rect(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


def _windows_work_area(root: tk.Misc) -> Rect | None:
    try:
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
        hwnd = int(root.wm_frame(), 16)                         # type: ignore[attr-defined]
        monitor = user32.MonitorFromWindow(hwnd, 2)             # MONITOR_DEFAULTTONEAREST
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        r = info.rcWork
        if r.right <= r.left or r.bottom <= r.top:
            return None
        return Rect(r.left, r.top, r.right - r.left, r.bottom - r.top)
    except (AttributeError, OSError, ValueError, tk.TclError):
        return None


def make_room(root: tk.Wm, area: Rect) -> str:
    """Studio leaves maximized and fills ``area`` (its drawing area); returns how it was
    (``"zoomed"`` or a ``wm geometry``) for ``give_back``."""
    before = "zoomed" if str(root.state()) == "zoomed" else str(root.geometry())
    root.state("normal")
    root.update_idletasks()
    side = max(0, root.winfo_rootx() - root.winfo_x())          # the frame's left edge
    root.geometry(f"{max(area.w, 1)}x{max(area.h, 1)}+{area.x - side}+"
                  f"{area.y - max(0, root.winfo_rooty() - root.winfo_y())}")
    return before


def give_back(root: tk.Wm, before: str) -> None:
    """Studio as it was before ``make_room``."""
    if before == "zoomed":
        root.state("zoomed")
    else:
        root.geometry(before)


__all__ = ["GAP", "MENU", "PLACES", "SHARE", "Placement", "Rect", "caption_of", "give_back",
           "make_room", "place_game", "studio_rect", "work_area"]
