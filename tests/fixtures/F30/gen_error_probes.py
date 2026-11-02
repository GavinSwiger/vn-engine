"""Probe R (F30 ``06`` §5, AC-F30-05): the real ``ErrorScreen``'s draw calls and pixel probes.

Recorded once from the pre-F30 ``ErrorScreen`` (before the ``error_look`` lift) into
``error_probes.json``, keyed by ``sys.platform`` (font rasterizing may differ per OS runner).
``tests/ui/test_error_look.py`` calls ``record()`` on the current build and compares.

Run from the repository root to (re)record for this OS::

    .venv/Scripts/python -m tests.fixtures.F30.gen_error_probes
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBES = HERE / "error_probes.json"
LONG_MESSAGE = HERE.parent / "F01" / "text" / "long_message.txt"

SIZES = ((1280, 720), (640, 360))
# 8 bands (canvas y) x 4 columns (canvas x): heading, message (3), title, log, hint, and
# the empty band under the hint. Each point is snapped to the brightest pixel within
# SNAP window pixels to its right, so most probes sit on glyph pixels.
BANDS_Y = (110, 182, 300, 470, 554, 594, 654, 700)
COLUMNS_X = (84, 300, 640, 1000)
SNAP = 24


def _cases() -> list[tuple[str, str, str]]:
    """(name, message, game title)."""
    return [
        ("short", "Short problem.", "Paper Lanterns"),
        ("long_message", LONG_MESSAGE.read_text(encoding="utf-8"), "Paper Lanterns"),
        ("long_title", "Short problem.", "T" * 500),
    ]


def _render(size, message: str, title: str, monkeypatch_draw):
    import pygame

    from engine.core.config_schema import Config, GameConfig, WindowConfig
    from engine.core.errors import UserFacingError
    from tests.fakes.fake_window import FakeWindow
    from tests.fakes.harness import LETTERBOX, make_app

    config = Config(game=GameConfig(title=title, version="1.0"),
                    window=WindowConfig(letterbox_color=LETTERBOX))
    window = FakeWindow(size)
    app, limiter = make_app(window, config=config)
    app.show_fatal_error(UserFacingError(message), already_logged=True)
    calls: list[dict] = []
    with monkeypatch_draw(calls):
        limiter.quit_at(1)
        app.run()
    surface = window.framebuffer()
    assert surface is not None
    return calls, surface.copy(), pygame


def _probe(surface, size) -> list[dict]:
    width, height = size
    scale = width / 1280
    probes = []
    for cy in BANDS_Y:
        for cx in COLUMNS_X:
            y = min(int(cy * scale), height - 1)
            x0 = min(int(cx * scale), width - 1)
            best_x, best = x0, -1
            for x in range(x0, min(x0 + SNAP, width)):
                value = sum(tuple(surface.get_at((x, y)))[:3])
                if value > best:
                    best_x, best = x, value
            probes.append({"x": best_x, "y": y,
                           "rgb": list(tuple(surface.get_at((best_x, y)))[:3])})
    return probes


def record(monkeypatch_draw) -> dict:
    """{case key: {"calls": [...], "probes": [...]}} for every size and input.

    ``monkeypatch_draw(calls)`` is a context manager that appends one dict per
    ``Canvas.draw_text`` call (``text``, ``font``, ``size``, ``pos``, ``color``,
    ``options``)."""
    out: dict = {}
    for size in SIZES:
        for name, message, title in _cases():
            calls, surface, _ = _render(size, message, title, monkeypatch_draw)
            out[f"{name}@{size[0]}x{size[1]}"] = {"calls": calls,
                                                 "probes": _probe(surface, size)}
    return out


def draw_recorder():
    """A ``monkeypatch_draw`` for scripts (no pytest)."""
    import contextlib

    from engine.render.canvas import Canvas

    @contextlib.contextmanager
    def patch(calls):
        real = Canvas.draw_text

        def draw_text(self, text, font, color, pos, **options):
            calls.append(call_record(text, font, color, pos, options))
            return real(self, text, font, color, pos, **options)

        Canvas.draw_text = draw_text
        try:
            yield
        finally:
            Canvas.draw_text = real

    return patch


def call_record(text, font, color, pos, options) -> dict:
    return {"text": text, "font": font.ref, "size": font.size, "pos": list(pos),
            "color": list(color)[:3],
            "options": {k: v for k, v in sorted(options.items())}}


def main() -> None:
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    pygame.init()
    try:
        data = record(draw_recorder())
    finally:
        pygame.quit()
    stored = json.loads(PROBES.read_text(encoding="utf-8")) if PROBES.exists() else {}
    stored[sys.platform] = data
    PROBES.write_text(json.dumps(stored, indent=1, ensure_ascii=False) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"recorded {len(data)} cases for {sys.platform} into {PROBES}")


if __name__ == "__main__":
    main()
