"""Record every ``Canvas.draw_text`` call (text, font, color, position, options, bounds)."""

import contextlib
from dataclasses import dataclass, field

from engine.render.canvas import Canvas
from engine.render.text import FontSpec


@dataclass
class TextCall:
    text: str
    font: FontSpec
    color: tuple
    pos: tuple
    options: dict = field(default_factory=dict)
    bounds: tuple = ()


@contextlib.contextmanager
def spy_draw_text(monkeypatch):
    calls: list[TextCall] = []
    real = Canvas.draw_text

    def draw_text(self, text, font, color, pos, **options):
        bounds = real(self, text, font, color, pos, **options)
        calls.append(TextCall(text, font, tuple(color), tuple(pos), dict(options), bounds))
        return bounds

    monkeypatch.setattr(Canvas, "draw_text", draw_text)
    yield calls
