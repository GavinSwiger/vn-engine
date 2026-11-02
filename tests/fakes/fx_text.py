"""F29 step 3 harness: the ADV say window's glyphs with hand-built effect bodies.

No tag makes an effect before F29 step 2, so bodies come from ``_fx_body`` (AC-F29-07's
builder in ``tests/render/test_textlayout.py``): ``{shake}``, ``{wave}``, ``{glitch}`` (with
``=small|medium|large``) become ``Style.effect`` and the real parser reads the rest. ``plain``
is the same text without the effect tags (06 §0.3's T′).

- ``real_assets()``: an ``AssetManager`` with no game folder (the bundled fonts).
- ``bind(canvas, size, quality)``: the canvas over a fresh framebuffer of ``size`` device px.
- ``FxSpy``: records every ``fx_blits`` call's output (the effect ``blits`` list) per draw.
- ``SurfaceLog``: a canvas-surface proxy logging ``blit``/``blits`` calls in order.
- ``TextLineSpy``: every ``assets.text_line`` call ``(font, text, color)`` and its surface.
"""

import pygame

from engine.core.constants import MB
from engine.core.geometry import Viewport
from engine.core.timing import GameTime
from engine.render import textbox as textbox_mod
from engine.render.assets import AssetManager
from engine.render.canvas import Canvas, RenderQuality
from engine.runtime.commands import Say, TaggedText
from engine.script.texttags import Span
from tests.fakes.fixed_font import tagged
from tests.render.test_textlayout import _FX_TAG, _fx_body

__all__ = ["FxSpy", "SurfaceLog", "TextLineSpy", "bind", "fx_body", "plain", "real_assets", "say"]


def fx_body(text: str) -> TaggedText:
    return _fx_body(text)


def plain(text: str) -> TaggedText:
    return tagged(_FX_TAG.sub("", text))


def say(text: str, sid: str = "main/1", *, effects: bool = True, name: str | None = None,
        restored: bool = False) -> Say:
    body = fx_body(text) if effects else plain(text)
    shown = "".join(p.text for p in body.pieces if isinstance(p, Span))
    return Say(sid, None, name, None, (), shown, body, restored=restored)


def real_assets() -> AssetManager:
    return AssetManager(None, budget_bytes=256 * MB, scale_filter="smooth", time=GameTime(),
                        format_source=lambda: pygame.Surface((1, 1)))


def bind(canvas: Canvas, size: tuple[int, int],
         quality: RenderQuality = RenderQuality.FINAL) -> pygame.Surface:
    w, h = size
    fb = pygame.Surface(size)
    canvas.bind(fb, Viewport(1280, 720, w, h, 0, 0, w, h), quality)
    return fb


class FxSpy:
    """Wraps ``render.textbox.fx_blits``: ``calls`` holds each call's appended blits."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list[list] = []
        real = textbox_mod.fx_blits

        def spy(glyphs, fx, seed, out):
            start = len(out)
            real(glyphs, fx, seed, out)
            self.calls.append(list(out[start:]))

        monkeypatch.setattr(textbox_mod, "fx_blits", spy)

    def take(self) -> list | None:
        """The effect blits of the draw since the last take (None: no effect pass)."""
        calls, self.calls = self.calls, []
        assert len(calls) <= 1
        return calls[0] if calls else None


class SurfaceLog:
    """Stands in for ``canvas.surface``: logs ``("blit", n)``/``("blits", n)`` in order."""

    def __init__(self, real: pygame.Surface) -> None:
        self.real = real
        self.log: list[tuple[str, int]] = []

    def blit(self, source, dest, area=None, special_flags=0):
        self.log.append(("blit", 1))
        return self.real.blit(source, dest, area, special_flags)

    def blits(self, seq, doreturn=True):
        seq = list(seq)
        self.log.append(("blits", len(seq)))
        return self.real.blits(seq, doreturn=doreturn)

    def __getattr__(self, name):
        return getattr(self.real, name)


class TextLineSpy:
    def __init__(self, monkeypatch, assets: AssetManager) -> None:
        self.calls: list[tuple] = []
        real = assets.text_line

        def text_line(font, text, color):
            surface = real(font, text, color)
            self.calls.append((font, text, tuple(color), surface))
            return surface

        monkeypatch.setattr(assets, "text_line", text_line)

    def take(self) -> list[tuple]:
        calls, self.calls = self.calls, []
        return calls
