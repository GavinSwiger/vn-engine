"""Studio's small icons as images (F45 ``08-visual-refresh.md`` §6, P2): the project tree's
file kinds (a ``ttk.Treeview`` shows only images) and the severity icons beside
Problems rows, in the dialogs and in the empty states, drawn in code like ``appicon`` so there is no image file to ship.

Each icon is a few strokes on a 16-unit grid (``_SHAPES``), rendered at any pixel size as RGBA
PNG bytes; a stroke's edge is anti-aliased from its distance to the pixel's centre. One
color per icon: the tree's set is ``muted``, the severity icons take their severity's color.
``photo(master, name, px, color)`` returns a ``tk.PhotoImage``; keep it, or Tk deletes it.
Imports only the standard library, ``appicon`` and ``theme``; ``tkinter`` only inside
``photo``.
"""

import base64
import functools
import math
import struct
import zlib

from engine.tools.editor.appicon import _coverage, _rgb, _round_box, _triangle

STROKE = 1.25                               # a line's width, in grid units

# A shape is (kind, *numbers) on the 16 × 16 grid: "seg" x0 y0 x1 y1 (a stroke), "ring" cx
# cy r (a stroked circle), "dot" cx cy r (a filled circle), "box" cx cy hw hh radius (a
# stroked rounded rectangle), "fill" cx cy hw hh radius (a filled one), "tri" x0 y0 x1 y1 x2
# y2 (a stroked triangle, clockwise on screen).
_SHAPES: dict[str, tuple[tuple, ...]] = {
    "error": (("ring", 8, 8, 6.5), ("seg", 5.5, 5.5, 10.5, 10.5), ("seg", 10.5, 5.5, 5.5, 10.5)),
    "warning": (("tri", 8, 1.6, 14.8, 14, 1.2, 14), ("seg", 8, 6, 8, 9.6), ("dot", 8, 11.8, 0.9)),
    "info": (("ring", 8, 8, 6.5), ("seg", 8, 7.2, 8, 11.6), ("dot", 8, 4.9, 0.9)),
    "success": (("ring", 8, 8, 6.5), ("seg", 5, 8.3, 7.2, 10.5), ("seg", 7.2, 10.5, 11.2, 5.8)),
    "folder": (("box", 8, 9.25, 6.5, 4.25, 1), ("seg", 1.5, 3, 6, 3), ("seg", 6, 3, 7.5, 5),
               ("seg", 1.5, 3, 1.5, 6)),
    "file": (("box", 8, 8, 5, 6.5, 1),),
    "script": (("box", 8, 8, 5, 6.5, 1), ("seg", 5.5, 5.5, 10.5, 5.5), ("seg", 5.5, 8, 10.5, 8),
               ("seg", 5.5, 10.5, 9, 10.5)),
    "image": (("box", 8, 8, 6.5, 5.5, 1), ("seg", 3, 12, 6.5, 8), ("seg", 6.5, 8, 9.5, 11),
              ("seg", 9.5, 11, 11, 9.5), ("seg", 11, 9.5, 13, 11.5), ("dot", 10.8, 5.6, 1.1)),
    "audio": (("dot", 5.5, 12, 2), ("seg", 7, 12, 7, 2.5), ("seg", 7, 2.5, 12, 4.5),
              ("seg", 12, 4.5, 12, 7)),
    "up": (("seg", 8, 3, 8, 13), ("seg", 3.5, 7.5, 8, 3), ("seg", 8, 3, 12.5, 7.5)),
    "down": (("seg", 8, 3, 8, 13), ("seg", 3.5, 8.5, 8, 13), ("seg", 8, 13, 12.5, 8.5)),
    "font": (("seg", 3, 13.5, 8, 2.5), ("seg", 8, 2.5, 13, 13.5), ("seg", 5, 9.5, 11, 9.5)),
    "code": (("seg", 5.5, 4.5, 2, 8), ("seg", 2, 8, 5.5, 11.5), ("seg", 10.5, 4.5, 14, 8),
             ("seg", 14, 8, 10.5, 11.5), ("seg", 9, 3.5, 7, 12.5)),
    "config": (("seg", 2, 4.5, 14, 4.5), ("seg", 2, 8, 14, 8), ("seg", 2, 11.5, 14, 11.5),
               ("fill", 5, 4.5, 1.5, 1.5, 0.6), ("fill", 10.5, 8, 1.5, 1.5, 0.6),
               ("fill", 7, 11.5, 1.5, 1.5, 0.6)),
}
NAMES = tuple(_SHAPES)


def _segment(x: float, y: float, x0: float, y0: float, x1: float, y1: float) -> float:
    dx, dy = x1 - x0, y1 - y0
    t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / ((dx * dx + dy * dy) or 1.0)))
    return math.hypot(x - x0 - t * dx, y - y0 - t * dy)


def _distance(shape: tuple, x: float, y: float, half: float) -> float:
    """Signed distance in grid units from (x, y) to one shape's ink (negative inside)."""
    kind, *n = shape
    if kind == "seg":
        return _segment(x, y, *n) - half
    if kind == "ring":
        return abs(math.hypot(x - n[0], y - n[1]) - n[2]) - half
    if kind == "dot":
        return math.hypot(x - n[0], y - n[1]) - n[2]
    if kind == "box":
        return abs(_round_box(x, y, *n)) - half
    if kind == "fill":
        return _round_box(x, y, *n)
    points = ((n[0], n[1]), (n[2], n[3]), (n[4], n[5]))
    return abs(_triangle(x, y, points)) - half


@functools.lru_cache(maxsize=None)
def icon_png(name: str, size: int, color: str) -> bytes:
    """Icon ``name`` at ``size`` × ``size`` px in ``color`` as PNG bytes (8-bit RGBA)."""
    unit = size / 16                            # pixels per grid unit
    rgb = bytes(_rgb(color))
    half = max(STROKE, 1.0 / unit) / 2          # never thinner than one pixel
    shapes = _SHAPES[name]
    rows = bytearray()
    for row in range(size):
        rows.append(0)                          # PNG filter: none
        y = (row + 0.5) / unit
        for column in range(size):
            x = (column + 0.5) / unit
            ink = min(_distance(shape, x, y, half) for shape in shapes) * unit
            rows += rgb
            rows.append(round(255 * _coverage(ink)))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def photo(master: object, name: str, px: int, color: str, gap: int = 0) -> object:
    """Icon ``name`` as a ``tk.PhotoImage`` of ``px`` × ``px`` screen pixels, plus ``gap``
    clear pixels on its right (a tree row's space before its text)."""
    import tkinter as tk

    data = base64.b64encode(icon_png(name, max(8, px), color)).decode("ascii")
    image = tk.PhotoImage(master=master, format="png", data=data)  # type: ignore[arg-type]
    if gap <= 0:
        return image
    padded = tk.PhotoImage(master=master, width=image.width() + gap,  # type: ignore[arg-type]
                           height=image.height())
    padded.tk.call(padded, "copy", image)
    return padded


__all__ = ["NAMES", "icon_png", "photo"]
