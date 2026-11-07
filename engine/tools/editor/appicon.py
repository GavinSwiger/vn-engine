"""Studio's app icon (F45 ``08-visual-refresh.md`` §7): an accent rounded square with a white
speech bubble, drawn in code at 16, 32, 48 and 256 px, so there is no image file to ship.

``icon_png(size)`` renders one size as RGBA PNG bytes (each shape's edge is anti-aliased from
its distance to the pixel's centre); ``set_app_icon(root)`` hands every size to Tk's
``wm iconphoto -default``, so the window and every dialog opened after it share the icon.
Colors come from ``theme.THEME``. Imports only the standard library and ``theme``; ``tkinter``
and ``uiprefs`` only inside ``set_app_icon``. Drawing every size takes about 0.2 s, so the
PNGs are kept in Studio's per-user folder (``icons/``), named by a digest of this file and
the colours: a changed icon or theme draws them again (v1 review finding 6).
"""

import base64
import functools
import hashlib
import math
import struct
import zlib

from engine.tools.editor.theme import THEME

ICON_SIZES = (256, 48, 32, 16)              # largest first, as ``wm iconphoto`` prefers


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _round_box(x: float, y: float, cx: float, cy: float, half_w: float, half_h: float,
               radius: float) -> float:
    """Signed distance from (x, y) to a rounded rectangle (negative inside)."""
    qx = abs(x - cx) - (half_w - radius)
    qy = abs(y - cy) - (half_h - radius)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius


def _triangle(x: float, y: float, points: tuple[tuple[float, float], ...]) -> float:
    """Signed distance (edges only, which is enough for a 1 px edge) to a convex triangle
    given clockwise on screen."""
    far = -math.inf
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        nx, ny = by - ay, ax - bx              # the outward normal of a clockwise edge
        length = math.hypot(nx, ny) or 1.0
        far = max(far, ((x - ax) * nx + (y - ay) * ny) / length)
    return far


def _coverage(distance: float) -> float:
    return min(1.0, max(0.0, 0.5 - distance))


@functools.lru_cache(maxsize=None)
def icon_png(size: int) -> bytes:
    """The icon at ``size`` × ``size`` px as PNG bytes (8-bit RGBA)."""
    s = float(size)
    back, front = _rgb(THEME["icon.background"]), _rgb(THEME["icon.foreground"])
    margin = s / 16
    half = s / 2 - margin
    corner = s * 0.22
    bubble = (s / 2, s * 0.44, s * 0.30, s * 0.20, s * 0.11)  # centre, half sizes, radius
    tail = ((s * 0.30, s * 0.56), (s * 0.48, s * 0.56), (s * 0.28, s * 0.78))
    rows = bytearray()
    for row in range(size):
        rows.append(0)                          # PNG filter: none
        y = row + 0.5
        for column in range(size):
            x = column + 0.5
            alpha = _coverage(_round_box(x, y, s / 2, s / 2, half, half, corner))
            if alpha <= 0.0:
                rows += b"\0\0\0\0"
                continue
            white = _coverage(min(_round_box(x, y, *bubble), _triangle(x, y, tail)))
            rows += bytes(round(b + (f - b) * white) for b, f in zip(back, front))
            rows.append(round(255 * alpha))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _cache_key() -> str | None:
    """A digest of this file's source and the icon colours, or None (no source to read,
    as in a frozen build: draw every time)."""
    try:
        with open(__file__, "rb") as handle:
            source = handle.read()
    except (OSError, TypeError, NameError):
        return None
    colors = f"{THEME['icon.background']}|{THEME['icon.foreground']}".encode()
    return hashlib.sha256(source + b"\0" + colors).hexdigest()[:16]


def cached_png(size: int) -> bytes:
    """``icon_png(size)``, read from Studio's per-user folder when drawn before with this
    code and these colours, else drawn and kept there (a failure to keep it is ignored)."""
    from engine.tools.editor import uiprefs

    key = _cache_key()
    folder = uiprefs._folder()
    if key is None or folder is None:
        return icon_png(size)
    path = folder / "icons" / f"app-{size}-{key}.png"
    try:
        with open(path, "rb") as handle:
            data = handle.read(1 << 20)
        if data.startswith(PNG_SIGNATURE):
            return data
    except OSError:
        pass
    data = icon_png(size)
    try:
        from engine.core.safefile import write_atomic

        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, [data])
    except (OSError, ValueError):
        pass
    return data


def set_app_icon(root: object) -> list[object]:
    """Give ``root`` and every later toplevel (the dialogs) Studio's icon instead of Tk's
    feather. Returns the images: keep them, or Tk deletes them. Nothing on failure."""
    import tkinter as tk

    try:
        images = [tk.PhotoImage(master=root, format="png",  # type: ignore[arg-type]
                                data=base64.b64encode(cached_png(size)).decode("ascii"))
                  for size in ICON_SIZES]
        root.iconphoto(True, *images)  # type: ignore[attr-defined]
    except (tk.TclError, OSError):
        return []
    return images


__all__ = ["ICON_SIZES", "cached_png", "icon_png", "set_app_icon"]
