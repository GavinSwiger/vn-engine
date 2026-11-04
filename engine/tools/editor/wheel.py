"""One mouse-wheel route for all of Studio: the wheel scrolls whatever is under the pointer.

Why this module exists: Tk gives the wheel only to text boxes, lists and trees. A scrolled
form (Game settings, Database, Minigames) is a canvas holding many fields, so the wheel did
nothing over its fields; the line-number gutters and the Assistant's cards inside its
transcript didn't scroll either.

- ``install(root)`` binds the wheel once for every widget (the ``all`` tag), so it covers the
  main window and every dialog. Each turn goes to the widget under the pointer, then up its
  parents: the first that can scroll that way takes it.
- ``register(widget, scroll)``: ``widget`` scrolls with ``scroll(units)`` (``ScrollFrame``'s
  canvas, a gutter for its text). ``scroll`` returns False when it can't move that way
  (already at the end, or it fits), and the turn goes on to the parents.
- A text box, list or tree under the pointer scrolls itself (Tk's own binding); the turn goes
  to the parents only when it has nothing to scroll. One holding the pointer only through an
  embedded window (an Assistant card) is scrolled here.
- Dropdowns and spin boxes inside a scrolled form scroll the form instead of changing their
  value (a turn on the way past must not change a setting). Elsewhere they step their value.

Imports ``tkinter`` only.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Final

LINES_PER_NOTCH: Final = 3
NATIVE: Final = frozenset({"Text", "Listbox", "Treeview"})
STEPPERS: Final = ("TCombobox", "TSpinbox")

_scrollers: dict[str, Callable[[int], object]] = {}


def register(widget: tk.Misc, scroll: Callable[[int], object]) -> None:
    """``widget`` takes wheel turns as ``scroll(units)`` (negative: up) until destroyed."""
    path = str(widget)
    _scrollers[path] = scroll
    widget.bind("<Destroy>", lambda e: _scrollers.pop(path, None)
                if str(e.widget) == path else None, add="+")


def units_of(event: tk.Event) -> int:
    """The turn in lines (negative: up). Windows sends 120 per notch, macOS small steps, X11
    buttons 4 and 5."""
    num = getattr(event, "num", None)
    if num == 4:
        return -LINES_PER_NOTCH
    if num == 5:
        return LINES_PER_NOTCH
    delta = int(getattr(event, "delta", 0) or 0)
    if delta == 0:
        return 0
    if abs(delta) >= 120:
        return -round(delta / 120 * LINES_PER_NOTCH)
    return -1 if delta > 0 else 1


def overflows(widget: tk.Misc) -> bool:
    """``widget``'s content doesn't fit: it has something to scroll at all."""
    return can_scroll(widget, -1) or can_scroll(widget, 1)


def can_scroll(widget: tk.Misc, units: int) -> bool:
    """``widget`` (a text box, list, tree or canvas) has room to move ``units``' way."""
    try:
        first, last = (float(v) for v in widget.yview())
    except (tk.TclError, AttributeError, ValueError, TypeError):
        return False
    return first > 0.0 if units < 0 else last < 1.0


def _under(event: tk.Event) -> tk.Misc | None:
    widget = event.widget
    if not isinstance(widget, tk.Misc):
        return None
    try:
        found = widget.winfo_containing(event.x_root, event.y_root)
    except (tk.TclError, KeyError):
        found = None
    return found or widget


def route(event: tk.Event) -> str | None:
    """The ``all`` binding: give the turn to the nearest widget that can take it."""
    units = units_of(event)
    widget = _under(event)
    if not units or widget is None:
        return None
    first = True
    while widget is not None:
        scroll = _scrollers.get(str(widget))
        if scroll is not None and scroll(units) is not False:
            return "break"
        try:
            kind = widget.winfo_class()
        except tk.TclError:
            return None
        if kind in NATIVE:
            if first and overflows(widget):
                return None                     # Tk's own binding scrolled it (no chaining)
            if not first and can_scroll(widget, units):
                widget.yview_scroll(units, "units")
                return "break"
        widget = widget.master
        first = False
    return None


def _in_scroller(widget: tk.Misc) -> bool:
    parent = widget.master
    while parent is not None:
        if str(parent) in _scrollers:
            return True
        parent = parent.master
    return False


def _step(event: tk.Event) -> str:
    """A dropdown or spin box: inside a scrolled form, scroll the form; else step it."""
    widget = event.widget
    units = units_of(event)
    if not units:
        return "break"
    if _in_scroller(widget):
        route(event)
        return "break"
    if "disabled" in widget.state():
        return "break"
    if widget.winfo_class() == "TSpinbox":
        widget.event_generate("<<Decrement>>" if units > 0 else "<<Increment>>")
        return "break"
    values = list(widget.cget("values") or ())
    if values:
        index = max(0, min(len(values) - 1, widget.current() + (1 if units > 0 else -1)))
        if index != widget.current():
            widget.current(index)
            widget.event_generate("<<ComboboxSelected>>")
    return "break"


def install(root: tk.Misc) -> None:
    """Once per Tk interpreter (more calls do nothing)."""
    if getattr(root, "_vn_wheel", False):
        return
    root._vn_wheel = True                       # type: ignore[attr-defined]
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        root.bind_all(sequence, route, add="+")
        for kind in STEPPERS:
            root.bind_class(kind, sequence, _step)


__all__ = ["LINES_PER_NOTCH", "can_scroll", "install", "register", "route", "units_of"]
