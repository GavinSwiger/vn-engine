"""Viewport math: where the canvas sits in the window, mouse mapping, initial window size.

Why this module exists: the fixed canvas is letterboxed into a window of any size and
rasterized at device resolution (ADR-0001), and mouse positions must map back to canvas
units exactly (PR-F01-21..26, PR-F01-17). The math is pure and must hold for every window
size, so it lives in pygame-free ``core`` where it can be tested exhaustively.

All arithmetic on sizes is done in integers, so the round-half-up rules of §7.3 and §7.4
hold exactly (no floating-point surprises at ``.5``).
"""

import math
from dataclasses import dataclass

from engine.core.constants import MIN_WINDOW_SIZE

Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class Viewport:
    """The canvas placement inside a framebuffer, all in device pixels except the canvas."""

    canvas_w: int           # canvas units (CANVAS_SIZE)
    canvas_h: int
    window_w: int           # framebuffer, device pixels (both >= 1)
    window_h: int
    x: int                  # canvas placement in device pixels
    y: int
    w: int
    h: int

    @property
    def scale_x(self) -> float:
        return self.w / self.canvas_w

    @property
    def scale_y(self) -> float:
        return self.h / self.canvas_h

    @staticmethod
    def compute(canvas: tuple[int, int], window: tuple[int, int],
                *, integer_scale: bool = False) -> "Viewport":
        """Letterbox ``canvas`` into ``window`` (§7.3).

        ``s = min(W / cw, H / ch)`` (floored when ``integer_scale`` and ``s >= 1``);
        ``w = min(W, max(1, floor(cw * s + 0.5)))``, same for ``h``; the canvas is centered
        and an odd leftover pixel goes to the right or bottom bar (PR-F01-22).

        Precondition (assert): window[0] >= 1 and window[1] >= 1. Callers never pass 0.
        """
        cw, ch = canvas
        W, H = window
        assert W >= 1 and H >= 1, f"empty framebuffer {W}x{H}"
        if integer_scale and W >= cw and H >= ch:
            k = min(W // cw, H // ch)                   # floor(s), s >= 1
            w, h = cw * k, ch * k
        elif W * ch <= H * cw:                          # s = W / cw (width-limited)
            w = W
            h = (2 * ch * W + cw) // (2 * cw)           # floor(ch * W / cw + 0.5)
        else:                                           # s = H / ch (height-limited)
            w = (2 * cw * H + ch) // (2 * ch)           # floor(cw * H / ch + 0.5)
            h = H
        w = min(W, max(1, w))
        h = min(H, max(1, h))
        assert 1 <= w <= W and 1 <= h <= H
        return Viewport(cw, ch, W, H, (W - w) // 2, (H - h) // 2, w, h)

    def window_to_canvas(self, px: float, py: float) -> tuple[tuple[int, int], bool]:
        """Framebuffer pixel → (canvas position, inside the canvas) (§7.3, PR-F01-24).

        The first device pixel of the canvas maps to 0 and the last to ``cw - 1``; points
        in the bars are clamped to the nearest canvas edge and flagged outside.
        """
        inside = self.x <= px < self.x + self.w and self.y <= py < self.y + self.h
        cx = _map_axis(px - self.x, self.w, self.canvas_w)
        cy = _map_axis(py - self.y, self.h, self.canvas_h)
        return (cx, cy), inside

    def bar_rects(self) -> list[Rect]:
        """The letterbox bars as (x, y, w, h) rects in device pixels; empty bars omitted.

        Without integer scaling the canvas touches two opposite edges, so there are at most
        two bars. With integer scaling there can be four (top and bottom span the full
        width; left and right fill the canvas's rows).
        """
        W, H = self.window_w, self.window_h
        right = W - (self.x + self.w)
        bottom = H - (self.y + self.h)
        candidates = [
            (0, 0, W, self.y),                                  # top
            (0, self.y + self.h, W, bottom),                    # bottom
            (0, self.y, self.x, self.h),                        # left
            (self.x + self.w, self.y, right, self.h),           # right
        ]
        return [rect for rect in candidates if rect[2] > 0 and rect[3] > 0]


def _map_axis(offset: float, size: int, canvas: int) -> int:
    value = math.floor(offset * (canvas - 1) / (size - 1) + 0.5) if size > 1 else 0
    return min(max(value, 0), canvas - 1)


def initial_window_size(requested: tuple[int, int], display_scale: float,
                        usable: tuple[int, int], *, fraction: float = 0.9,
                        minimum: tuple[int, int] = MIN_WINDOW_SIZE) -> tuple[int, int]:
    """The window size to open with (§7.4, PR-F01-17, PR-F01-20).

    The requested size times the display scale if it fits in ``fraction`` of the usable
    area; otherwise the largest 16:9 size that fits; never below ``minimum``.
    Worked example: 1280×720 into a 1366×728 usable area → 1164×655.
    """
    rw, rh = requested
    uw, uh = usable
    want = (round(rw * display_scale), round(rh * display_scale))
    # round(…, 9) absorbs floating-point noise such as 1229.3999999999999 before floor.
    lw = math.floor(round(uw * fraction, 9))
    lh = math.floor(round(uh * fraction, 9))
    if want[0] <= lw and want[1] <= lh:
        return want
    w = min(lw, lh * 16 // 9)                   # floor(lh * 16 / 9)
    h = (18 * w + 16) // 32                     # floor(w * 9 / 16 + 0.5)
    if h > lh:
        h = lh
        w = h * 16 // 9
    return max(w, minimum[0]), max(h, minimum[1])
