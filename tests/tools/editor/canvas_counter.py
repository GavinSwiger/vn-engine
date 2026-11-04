"""A counting stand-in for a ``tk.Canvas`` (F58 ``04-technical.md`` §11, §16 P0; AC-F58-15).

``CountingCanvas(canvas)`` forwards every call to the real canvas and counts it by method
name, so a test can check that a one-scene update makes no ``delete("all")``, no restyle of
a tag many items share, and the same number of canvas calls at 300 as at 1,000 scenes.

- ``calls``: method name → count; ``log``: every ``(method, args)`` in order.
- ``deleted_all``: how many ``delete("all")`` calls ran.
- ``shared_restyles(shared)``: ``itemconfigure``/``itemconfig`` calls whose first argument
  is one of the ``shared`` tags (``"chip"``, ``"box"``, an ``edge-<kind>`` tag ...).
- ``total(ignore=...)``: all calls but the named methods (AC-15 ignores the deferred
  ``file:line`` texts by passing the method they use, or filters ``log`` itself).
- ``reset()`` starts a new count.

``CountingCanvas.install(view)`` swaps a view's ``canvas`` attribute for a counter and
returns it (``view.canvas`` keeps working, so bindings made earlier are untouched).
"""

from collections import Counter
from collections.abc import Iterable


class CountingCanvas:
    def __init__(self, canvas) -> None:
        object.__setattr__(self, "_canvas", canvas)
        object.__setattr__(self, "calls", Counter())
        object.__setattr__(self, "log", [])

    @classmethod
    def install(cls, view, attr: str = "canvas") -> "CountingCanvas":
        counter = cls(getattr(view, attr))
        setattr(view, attr, counter)
        return counter

    @property
    def real(self):
        return self._canvas

    def __getattr__(self, attr: str):
        value = getattr(self._canvas, attr)
        if not callable(value) or attr.startswith("_"):
            return value

        def counted(*args, **kwargs):
            self.calls[attr] += 1
            self.log.append((attr, args))
            return value(*args, **kwargs)

        return counted

    def __setattr__(self, attr: str, value) -> None:
        setattr(self._canvas, attr, value)

    def __str__(self) -> str:                   # Tk widget paths (bind, focus, winfo)
        return str(self._canvas)

    def reset(self) -> None:
        self.calls.clear()
        self.log.clear()

    @property
    def deleted_all(self) -> int:
        return sum(1 for method, args in self.log if method == "delete" and "all" in args)

    def shared_restyles(self, shared: Iterable[str]) -> int:
        tags = set(shared)
        return sum(1 for method, args in self.log
                   if method in ("itemconfigure", "itemconfig") and args
                   and isinstance(args[0], str) and args[0] in tags)

    def total(self, ignore: Iterable[str] = ()) -> int:
        skip = set(ignore)
        return sum(n for method, n in self.calls.items() if method not in skip)


__all__ = ["CountingCanvas", "box_parts"]


def box_parts(view, name: str) -> dict[str, int]:
    """Box ``name``'s items by role, from the view's ``MapPainter`` registry (F58 I-10: the
    index tags ``rect{i}``, ``name{i}``, ``startbar{i}`` ... are gone): ``rect``, ``name``,
    ``where``, ``marks`` (the registry's own), and by look ``inner`` (an ending's second
    border), ``startbar``, ``scene`` (the quoted title), ``chapter``, ``minigame`` and
    ``wipe`` (the tags under the box). Missing roles are left out."""
    from engine.tools.editor import mapcanvas as mc
    found = view.painter.boxes[name]
    canvas = view.canvas
    parts = {"rect": found.rect}
    for role in ("name", "where", "marks"):
        if getattr(found, role) is not None:
            parts[role] = getattr(found, role)
    for item in found.items:
        if item in parts.values():
            continue
        kind = canvas.type(item)
        if kind == "rectangle":
            if canvas.itemcget(item, "fill") == mc.START_COLOR:
                parts.setdefault("startbar", item)
            elif canvas.itemcget(item, "outline") == mc.ENDING_COLOR:
                parts.setdefault("inner", item)
        elif kind == "text":
            text = str(canvas.itemcget(item, "text"))
            if text.startswith("“"):
                parts.setdefault("scene", item)
            elif text.startswith("▶"):
                parts.setdefault("minigame", item)
            elif text.startswith("⚠"):
                parts.setdefault("wipe", item)
            elif canvas.itemcget(item, "fill") == mc.CHAPTER_COLOR:
                parts.setdefault("chapter", item)
    return parts
