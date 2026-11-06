"""A small drawn stage with a meter in its corner (F60's kit cards, F62's meter preview).

Why this module exists: the Kit page's cards and Database ▸ Meters' live preview show the
same thing, a tiny game screen in a scheme's colors with one meter drawn in its look (bar,
number, hearts, pips or dial) in its corner. ``MeterPainter`` draws it on any canvas, so
both look alike and match what the game shows.

- ``Reading``: what the mock meter shows: how full (``share``), its number and what it is
  out of, and a rank label ("" for none).
- ``MeterPainter.stage(...)``: the stage (soft background, text box with a name tab), then
  the meter's box in its corner: label, the look, and the rank under it.

Canvas tags: every item gets the caller's tags plus ``"preview"``; the meter's items also
``"meter"``, ``"look:<look>"`` and ``"place:<place>"``; its label ``"label"``, its rank
``"rank"``.

Imports the standard library, ``tkinter`` and its own package; never pygame.
"""

import math
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from dataclasses import dataclass

from engine.tools.editor.schemecards import fit_text
from engine.tools.editor.theme import THEME

TEXTBOX_HEIGHT = 24             # px at 100 %
INSET = 5                       # the meter's distance from the stage's edges
STEPS = 5                       # hearts and pips
SHOWN = 0.6                     # the kit cards' mock fill


@dataclass(frozen=True, slots=True)
class Reading:
    """What the mock meter shows: ``share`` full (0 to 1), ``number`` (bold) and ``of``
    after it ("/ 10", or "" without a range), and ``rank`` ("" for none)."""

    share: float = SHOWN
    number: str = "6"
    of: str = "/ 10"
    rank: str = ""


class MeterPainter:
    """Draws on ``canvas``; ``px`` scales a 100 % size; ``tiny``/``tiny_bold`` are the
    meter's fonts; the meter's box is ``meter_width`` px (at 100 %) wide."""

    def __init__(self, canvas: tk.Canvas, px: Callable[[float], int], tiny: tkfont.Font,
                 tiny_bold: tkfont.Font, *, meter_width: int = 66) -> None:
        self.canvas, self.px = canvas, px
        self.tiny, self.tiny_bold = tiny, tiny_bold
        self.meter_width = meter_width

    def stage(self, tags: tuple[str, ...], x0: int, y0: int, x1: int, y1: int,
              colors: tuple[str, str, str, str, str, str], look: str, place: str,
              label: str, reading: Reading = Reading()) -> None:
        """The small stage: ``colors`` (fill, text, border, accent, soft, track) with the
        soft color behind, the text box at the bottom (a name tab, two lines of text), and
        the meter in ``place``."""
        canvas, px = self.canvas, self.px
        fill, text, border, accent, soft, _track = colors
        tags = (*tags, "preview")
        canvas.create_rectangle(x0, y0, x1, y1, fill=soft, outline=THEME["border"], width=1,
                                tags=tags)
        box_top = y1 - px(TEXTBOX_HEIGHT)
        canvas.create_rectangle(x0 + px(4), box_top, x1 - px(4), y1 - px(4), fill=fill,
                                outline=border, width=1, tags=tags)
        canvas.create_rectangle(x0 + px(10), box_top - px(5), x0 + px(36), box_top + px(2),
                                fill=accent, outline="", tags=tags)
        for n, share in enumerate((0.72, 0.48)):
            ly = box_top + px(7 + 6 * n)
            canvas.create_rectangle(x0 + px(10), ly, x0 + px(10) + round(
                (x1 - x0 - px(24)) * share), ly + px(2), fill=text, outline="", tags=tags)
        self.meter(tags, x0, y0, x1, box_top - px(4), colors, look, place, label, reading)

    def meter(self, tags: tuple[str, ...], x0: int, y0: int, x1: int, y1: int,
              colors: tuple[str, str, str, str, str, str], look: str, place: str,
              label: str, reading: Reading = Reading()) -> None:
        """The meter's box in ``place`` inside ``(x0, y0)``–``(x1, y1)``."""
        canvas, px = self.canvas, self.px
        fill, text, border, accent, _soft, track = colors
        line = self.tiny.metrics("linespace")
        row = px(10)
        height = px(4) + (line if label else 0) + row + (line if reading.rank else 0) + px(4)
        width = px(self.meter_width)
        left = x0 + px(INSET) if place.endswith("left") else x1 - px(INSET) - width
        top = y0 + px(INSET) if place.startswith("top") else y1 - height
        tags = (*tags, "meter", f"look:{look}", f"place:{place}")
        canvas.create_rectangle(left, top, left + width, top + height, fill=fill,
                                outline=border, width=1, tags=tags)
        inner_left, inner_right = left + px(5), left + width - px(5)
        y = top + px(4)
        if label:
            canvas.create_text(inner_left, y, anchor="nw", fill=text, font=self.tiny,
                               text=fit_text(label, inner_right - inner_left,
                                             self.tiny.measure), tags=(*tags, "label"))
            y += line
        self._look(look, tags, inner_left, y, inner_right, y + row, accent, track, reading)
        if reading.rank:
            canvas.create_text(inner_left, y + row + px(1), anchor="nw", fill=accent,
                               font=self.tiny_bold,
                               text=fit_text(reading.rank, inner_right - inner_left,
                                             self.tiny_bold.measure), tags=(*tags, "rank"))

    def _look(self, look: str, tags: tuple[str, ...], x0: int, y0: int, x1: int, y1: int,
              accent: str, track: str, reading: Reading) -> None:
        canvas, px = self.canvas, self.px
        mid = (y0 + y1) // 2
        share = min(1.0, max(0.0, reading.share))
        if look == "bar":
            canvas.create_rectangle(x0, mid - px(2), x1, mid + px(2), fill=track, outline="",
                                    tags=tags)
            if share > 0:
                canvas.create_rectangle(x0, mid - px(2), x0 + round((x1 - x0) * share),
                                        mid + px(2), fill=accent, outline="", tags=tags)
        elif look == "number":
            canvas.create_text(x0, mid, anchor="w", fill=accent, font=self.tiny_bold,
                               text=reading.number, tags=tags)
            if reading.of:
                canvas.create_text(x0 + self.tiny_bold.measure(reading.number + " "), mid,
                                   anchor="w", fill=track, font=self.tiny, text=reading.of,
                                   tags=tags)
        elif look in ("hearts", "pips"):
            step = (x1 - x0) // STEPS
            size = min(step - px(2), y1 - y0)
            for n in range(STEPS):
                color = accent if n < round(STEPS * share) else track
                cx = x0 + n * step + size // 2
                if look == "pips":
                    r = size // 2 - px(1)
                    canvas.create_oval(cx - r, mid - r, cx + r, mid + r, fill=color,
                                       outline="", tags=tags)
                else:
                    canvas.create_polygon(heart(cx, mid, size), fill=color, outline="",
                                          smooth=True, tags=tags)
        else:                                                            # dial
            r = y1 - y0
            cx, cy = x0 + r, y1
            box = (cx - r, cy - r, cx + r, cy + r)
            canvas.create_arc(*box, start=0, extent=180, style="arc", outline=track,
                              width=px(3), tags=tags)
            if share > 0:
                canvas.create_arc(*box, start=180, extent=-180 * share, style="arc",
                                  outline=accent, width=px(3), tags=tags)
            angle = math.pi * (1 - share)
            canvas.create_line(cx, cy, cx + round(r * 0.8 * math.cos(angle)),
                               cy - round(r * 0.8 * math.sin(angle)), fill=accent,
                               width=max(1, px(1)), tags=tags)
            canvas.create_text(cx + r + px(6), mid, anchor="w", fill=accent,
                               font=self.tiny_bold, text=f"{round(share * 100)}%", tags=tags)


def heart(cx: int, cy: int, size: int) -> list[int]:
    """A heart's points (drawn smooth) of about ``size`` px, centred on ``(cx, cy)``."""
    h = size / 2
    points = ((0, -0.35), (0.35, -0.9), (1, -0.55), (0.75, 0.15), (0, 0.9), (-0.75, 0.15),
              (-1, -0.55), (-0.35, -0.9))
    return [round(v) for x, y in points for v in (cx + x * h, cy + y * h)]


def fonts(parent: tk.Misc, small: tkfont.Font, scale: float) -> tuple[tkfont.Font,
                                                                      tkfont.Font]:
    """The meter's two fonts (regular and bold) at ``scale``, in ``small``'s family."""
    family = small.actual("family")
    size = -max(8, round(10 * scale))
    return (tkfont.Font(root=parent, family=family, size=size),
            tkfont.Font(root=parent, family=family, size=size, weight="bold"))


__all__ = ["INSET", "MeterPainter", "Reading", "SHOWN", "STEPS", "TEXTBOX_HEIGHT", "fonts",
           "heart"]
