"""F49: a style's color scheme in the real app (AC-F49-08; 07 I-1, I-2).

App S (``tests/app/test_saves_service.py``): an in-process ``launch()`` with a fake frame
clock. The story runs ``ui style term`` and ``ui style off`` between its lines, and at each
line the long-lived holders paint into a fresh canvas: the shell's painter (a panel), the
notice layer (a shown notice), the chapter card, and F14's limit mark. Panels and notices
are drawn solid (``[theme.panel] fill_opacity = 1.0``), so a pixel is the fill color.
"""

import pygame
import pytest

from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.core.schemes import SCHEMES
from engine.render.canvas import Canvas, RenderQuality
from engine.runtime.commands import TitleCard
from engine.ui.focus import Box
from tests.app.test_autosave_app import advance
from tests.app.test_saves_service import at_line, launch, make_game, play, unthreaded, wait
from tests.render.conftest import make_assets

pytestmark = pytest.mark.display
__all__ = ["unthreaded"]                       # the fixture, re-exported for pytest

CONFIG = ('[theme.panel]\nfill_opacity = 1.0\n'
          '[style.term.theme]\npreset = "amber"\n')
SCRIPT = ('label start:\n    "L1"\n    ui style term\n    "L2"\n    ui style off\n'
          '    "L3"\n    return\n')


def rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def colors(name: str) -> dict[str, tuple[int, int, int]]:
    """What each holder paints under scheme ``name``: the panel and notice fill, the card
    fill (Sakura's is its extra), and the limit mark's pill (``soft``)."""
    found = SCHEMES[name]
    card = found.extra.get("chapter.fill_color", found.colors["fill"])
    return {"panel": rgb(found.colors["fill"]), "notice": rgb(found.colors["fill"]),
            "card": rgb(card), "mark": rgb(found.colors["soft"])}


def canvas() -> Canvas:
    w, h = CANVAS_SIZE
    surface = pygame.Surface((w, h))
    surface.fill((1, 2, 3))
    out = Canvas(make_assets(None))
    out.bind(surface, Viewport(w, h, w, h, 0, 0, w, h), RenderQuality.FINAL)
    return out


def at(target: Canvas, x: float, y: float) -> tuple[int, int, int]:
    return tuple(target.surface.get_at((round(x), round(y))))[:3]


def painted(app) -> dict:
    """The holders' painted colors now, and whether the painter draws the base theme."""
    shell = app.shell
    painter = shell.painter
    out: dict = {"base": painter.styles is shell.base_theme,
                 "style": painter.style("panel").frame.fill_color}
    target = canvas()
    painter.bind(target)
    try:
        painter.panel(Box(100, 100, 200, 100))
        out["panel"] = at(target, 200, 150)
        target = canvas()
        painter.bind(target)
        shell.notices.draw(target, painter)
        view = shell.notices.views()[0]
        out["notice"] = at(target, view.box.x + 8, view.box.y + view.box.h / 2)
    finally:
        painter.bind(app.canvas)
    target = canvas()
    app.stage_screen.view.card_painter.paint(target, TitleCard("c", "H", "T"))
    out["card"] = at(target, 10, 10)
    mark = app.rollback_keys.cue.mark_surface((56, 28), 1.0)
    out["mark"] = tuple(mark.get_at((8, 14)))[:3]
    return out


# --- AC-F49-08 — ui style term recolors the menus and holders; ui style off brings Sakura -------

def test_ac_f49_08_a_scheme_style_in_the_app(tmp_path, scripted_app, unthreaded):
    game = make_game(tmp_path, CONFIG)
    (game / "script" / "main.vns").write_text(SCRIPT, encoding="utf-8")

    def script(app, out):
        for line in ("L1", "L2", "L3"):
            if line == "L1":
                yield from wait(lambda: at_line(app, "L1"))
            else:
                yield from advance(app, line)
            app.shell.notify("Saved.")
            yield from wait(lambda: app.shell.notices.views()
                            and app.shell.notices.views()[0].phase == "shown")
            out[line] = painted(app)
            out[line + " theme"] = app.shell.theme.cfg.panel.fill_color

    out = play(scripted_app, script, last=900)
    assert launch(game) == 0
    sakura, amber = colors("sakura"), colors("amber")
    for line, want in (("L1", sakura), ("L2", amber), ("L3", sakura)):
        got = out[line]
        assert out[line + " theme"] == want["panel"], line          # GameShell.theme
        assert got["style"] == want["panel"], line                  # shell.painter.style
        assert {key: got[key] for key in want} == want, line         # what is painted
    # Off again: the base UiTheme object itself (07 I-2).
    assert out["L1"]["base"] and not out["L2"]["base"] and out["L3"]["base"]
