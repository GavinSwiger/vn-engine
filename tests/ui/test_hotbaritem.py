"""F64 round 2: ``HotbarItem`` in the status corner (layout, drawing, contrast in every
scheme) and ``Hotbar``'s place in the corner (show, hide, the cut after a reset)."""

from types import SimpleNamespace

import pygame
import pytest

from engine.app.hotbar import KEY, Hotbar, line_ready
from engine.app.ui_contrast import PAIRS, pair_ratios
from engine.core.config import load_config
from engine.core.config_schema import HotbarConfig
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.core.schemes import SCHEMES
from engine.render.canvas import Canvas, RenderQuality
from engine.render.typewriter import TypeState
from engine.runtime.interpreter import Status
from engine.ui.focus import Box
from engine.ui.hotbaritem import HotbarItem, HotbarSlot, initials
from engine.ui.statuscorner import CornerStyle, StatusCorner, corner_style
from engine.ui.theme import plain_theme
from tests.ui.test_statuscorner import corner, game_shell, m20

SLOTS = (HotbarSlot("1", "tea", "Jasmine Tea", 3), HotbarSlot("2", "map", "Old Map"),
         HotbarSlot("3"), HotbarSlot("4"))


def _ctx():
    return corner(reduce=True)._context(CornerStyle(), "bottom_left")


def test_initials():
    assert initials("Jasmine Tea") == "JT"
    assert initials("Matches") == "Ma"
    assert initials("") == ""


def test_layout_one_row_of_wells_with_a_strip():
    item = HotbarItem(lambda: SLOTS)
    ctx = _ctx()
    well, gap, small, strip = item.metrics(ctx.size)
    assert (well, gap) == (53.0, 18.0) and small >= 14
    assert item.measure(ctx) == (4 * well + 3 * gap, well + strip)
    boxes = item.slot_boxes(Box(100, 200, 999, 999), ctx.size)
    assert [b.x for b in boxes] == [100 + i * (well + gap) for i in range(4)]
    eight = HotbarItem(lambda: SLOTS * 2)
    assert eight.measure(ctx)[0] <= ctx.max_width


def _draw(style, slots=SLOTS, focus=None):
    layer = StatusCorner(style, lambda font: m20, reduce_motion=lambda: True)
    item = HotbarItem(lambda: slots, focus=lambda: focus)
    layer.set_item(KEY, "bottom_left", item)
    shell, _ = game_shell()
    canvas = Canvas(shell.assets)
    frame = pygame.Surface((1280, 720))
    canvas.bind(frame, Viewport.compute((1280, 720), (1280, 720)), RenderQuality.FINAL)
    layer.draw(canvas, shell.painter)
    return frame, item


def _count(frame, box, color):
    return sum(1 for x in range(int(box.x), int(box.right))
               for y in range(int(box.y), int(box.bottom))
               if tuple(frame.get_at((x, y)))[:3] == tuple(color))


@pytest.mark.parametrize("scheme", sorted(SCHEMES))
def test_every_scheme_hotbar_meets_contrast(tmp_path, scheme):
    """The hotbar draws only the corner's text and accent colors on its fill, and no text
    over a picture, so the corner's W67 pairs are its contrast in all 28 schemes."""
    (tmp_path / "config.toml").write_text(f'[theme]\npreset = "{scheme}"\n', encoding="utf-8")
    cfg = load_config(GamePaths.for_game(tmp_path)).config.theme
    for pair in (p for p in PAIRS if p.fg.startswith("corner.")):
        assert min(pair_ratios(cfg, pair)) >= pair.minimum, (scheme, pair.fg)
    style = corner_style(plain_theme(cfg))
    frame, item = _draw(style)
    first = item.boxes[0]
    assert _count(frame, first, style.accent_color) > 0, scheme      # the well's outline
    assert _count(frame, first, style.text_color) > 0, scheme        # "JT", "1", "×3"


def test_the_focused_slot_has_a_thicker_ring():
    style = CornerStyle()
    plain, item = _draw(style)
    ringed, _ = _draw(style, focus=0)
    box = item.boxes[0]
    assert _count(ringed, box, style.accent_color) > _count(plain, box, style.accent_color)


def test_line_ready():
    assert line_ready(None)
    typing = SimpleNamespace(line=object(), typer=SimpleNamespace(state=TypeState.TYPING))
    done = SimpleNamespace(line=object(), typer=SimpleNamespace(state=TypeState.COMPLETE))
    paused = SimpleNamespace(line=object(), typer=SimpleNamespace(state=TypeState.WAIT_CLICK))
    assert not line_ready(typing) and line_ready(done) and not line_ready(paused)


# --- Hotbar: the corner follows show hotbar ----------------------------------------------

class _Codex:
    def __init__(self):
        self.bar = False
        self.held = ["tea", "key"]
        self.index = SimpleNamespace(get=lambda n: None, is_item=lambda n: True)

    def bar_shown(self):
        return self.bar

    def has(self, name):
        return name in self.held

    def items(self):
        return tuple(self.held)


def test_hotbar_follows_show_hotbar_and_cuts_after_a_reset(monkeypatch):
    from engine.runtime import itemuse
    shell, _ = game_shell()
    codex = _Codex()
    interp = SimpleNamespace(codex=codex, status=Status.WAITING)
    monkeypatch.setattr(itemuse, "usable_items", lambda i: ("tea",))
    app = SimpleNamespace(shell=shell, config=SimpleNamespace(
        hotbar=HotbarConfig(slots=5, place="top_right"), game=SimpleNamespace(kit=None)))
    hotbar = Hotbar(app, lambda: interp, user=None, port=None)     # type: ignore[arg-type]
    shell.corner.add_source(hotbar.sync)
    shell.update_layer(0.0, focused=True)
    assert KEY not in shell.corner.keys()
    codex.bar = True
    shell.update_layer(0.0, focused=True)
    assert shell.corner.keys("top_right") == (KEY,)
    assert hotbar.names() == ("tea", None, None, None, None)
    app.config = SimpleNamespace(hotbar=HotbarConfig(slots=4, items=("key", "tea", "nope")),
                                 game=SimpleNamespace(kit=None))
    assert hotbar.names() == ("key", "tea", None, None)      # "nope": empty
    codex.held = ["tea"]
    assert hotbar.names() == (None, "tea", None, None)       # not held: empty
    codex.bar = False
    shell.update_layer(1.0, focused=True)
    assert KEY not in shell.corner.keys()
    codex.bar = True
    hotbar.reset()
    shell.update_layer(0.0, focused=True)
    views = [v for v in shell.corner.views() if v.key == KEY]
    assert views and views[0].opacity == 1.0                        # a cut, not a fade
