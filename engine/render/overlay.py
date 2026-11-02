"""The developer FPS overlay (PR-F01-51), toggled with F3 in dev runs only.

Why this module exists: authors need a quick look at the frame rate and frame cost while
they build a scene, without a profiler. It reads ``RecentFrames`` (the last frames'
intervals and work) and draws one small line at canvas (8, 8). Release runs never draw it
(SEC-F01-20).

F22 (UI-F22-01, contract change 5): ``draw`` also takes ``lines``, ready-made strings from the
App's ``overlay_lines`` providers (F22's meters), drawn under the FPS line at the same x, with
the same font, color, and backdrop, one font line size apart. ``render`` only gets strings.
"""

from collections.abc import Sequence

from engine.core.timing import RecentFrames
from engine.render.canvas import Canvas
from engine.render.text import FontSpec

POSITION = (8, 8)
FONT = FontSpec(None, 20)
TEXT_COLOR = (0xFF, 0xFF, 0x80)
BACKDROP = (0, 0, 0, 160)


def overlay_text(recent: RecentFrames) -> str:
    return f"{recent.fps():.0f} FPS | {recent.last_work_ms():.1f} ms"


def draw(canvas: Canvas, recent: RecentFrames, lines: Sequence[str] = ()) -> None:
    """``"<fps> FPS | <work> ms"``, then each of ``lines``, on one translucent backdrop."""
    texts = [overlay_text(recent), *lines]
    font = canvas.assets.font(FONT.ref, FONT.size).font
    pitch = font.get_linesize()
    width = max(font.size(text)[0] for text in texts)
    x, y = POSITION
    canvas.fill(BACKDROP, (x - 4, y - 2, width + 8, pitch * len(texts) + 4))
    for index, text in enumerate(texts):
        canvas.draw_text(text, FONT, TEXT_COLOR, (x, y + index * pitch))
