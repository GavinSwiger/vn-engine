"""F61: ``ui/statuscorner.StatusCorner``, the ``[theme.corner]`` tokens, their W67 pairs, and
the shell's visibility rules. Layout rows use F05's M20 metrics (17 units per character at
24); pixel probes draw with the bundled font on the 1280×720 unit canvas under the dummy
driver. ``Label`` is the one test-only item (text, and an optional accent bar)."""

import dataclasses
from types import SimpleNamespace

import pygame
import pytest

from engine.app.ui_contrast import PAIRS, contrast_warnings, pair_ratios
from engine.core.config import load_config
from engine.core.config_schema import Config, CornerTheme, ThemeConfig
from engine.core.constants import CANVAS_SIZE
from engine.core.geometry import Viewport
from engine.core.paths import GamePaths
from engine.core.schemes import SCHEMES
from engine.core.skins import CORNER_PLACES
from engine.render.canvas import Canvas, RenderQuality
from engine.ui import statuscorner as sc
from engine.ui.builtin import skip_auto
from engine.ui.focus import Box
from engine.ui.screen import Screen, ScreenStack
from engine.ui.shell import GameShell, Mode, ShellPorts
from engine.ui.statuscorner import (
    CornerStyle,
    StatusCorner,
    corner_layout,
    corner_style,
    reserved_areas,
)
from engine.ui.theme import Words, measure_with, plain_theme
from tests.fakes.fixed_font import FixedFont
from tests.render.conftest import make_assets

W, H = CANVAS_SIZE
STAGE = (40, 90, 160)
PINK_WHITE = (0xFF, 0xF4, 0xF8)
BERRY = (0xA0, 0x28, 0x60)
CORNER_PAIRS = [p for p in PAIRS if p.fg.startswith("corner.")]


@pytest.fixture
def load(tmp_path):
    """Load ``text`` as a game's config.toml."""
    count = iter(range(1000))

    def load_text(text: str):
        root = tmp_path / f"game{next(count)}"
        root.mkdir()
        (root / "config.toml").write_text(text, encoding="utf-8")
        return load_config(GamePaths.for_game(root))
    return load_text


def m20(text: str, size: int) -> float:
    return FixedFont(size).size(text)[0]


class Label:
    """The test-only item: one line of text, and an accent bar ``bar`` wide under it."""

    def __init__(self, text: str, bar: float = 0.0) -> None:
        self.text = text
        self.bar = bar
        self.revision = 0
        self.measured = 0

    def measure(self, ctx):
        self.measured += 1
        w = max(ctx.measure(self.text, ctx.size), self.bar)
        return w, ctx.pitch + (10 if self.bar else 0)

    def draw(self, canvas, box, ctx):
        ctx.text(canvas, self.text, (box.x, box.y))
        if self.bar:
            ctx.fill(canvas, Box(box.x, box.y + ctx.pitch + 2, self.bar, 6))


def corner(*, reduce: bool = False, scale: float = 1.0, style: CornerStyle | None = None):
    return StatusCorner(style or CornerStyle(), lambda font: m20, text_scale=lambda: scale,
                        reduce_motion=lambda: reduce)


def boxes(layer: StatusCorner, reserved=()) -> dict:
    return {v.key: v.box for v in layer.views(reserved)}


# --- Layout ---------------------------------------------------------------------------------

def test_items_stack_inward_from_each_corner_in_insertion_order():
    layer = corner(reduce=True)
    for place in CORNER_PLACES:
        layer.set_item(f"{place}1", place, Label("Hana 3"))
        layer.set_item(f"{place}2", place, Label("Ren 10"))
    found = boxes(layer)
    # 6 chars × 17 = 102 + 2 × 12 padding; pitch 34 + 2 × 8 padding.
    assert found["top_left1"] == Box(24, 24, 126, 50)
    assert found["top_left2"] == Box(24, 82, 126, 50)                     # 8 below
    assert found["top_right1"] == Box(W - 24 - 126, 24, 126, 50)
    assert found["top_right2"].right == W - 24 and found["top_right2"].y == 82
    assert found["bottom_left1"] == Box(24, H - 24 - 50, 126, 50)
    assert found["bottom_left2"].bottom == found["bottom_left1"].y - 8
    assert found["bottom_right2"].right == W - 24
    assert layer.keys("top_left") == ("top_left1", "top_left2")


def test_text_scale_and_padding_tokens_size_the_panels():
    layer = corner(reduce=True, scale=1.5, style=CornerStyle(side_padding=20, top_padding=4))
    layer.set_item("a", "top_left", Label("abc"))
    box = boxes(layer)["a"]
    assert box.w == FixedFont(36).size("abc")[0] + 40 and box.h == round(1.4 * 36) + 8


def test_a_panel_jumps_past_reserved_areas():
    say = Box(140, 460, 1000, 228)                 # the default box with its name tab
    pill = Box(500, 690, 280, 28)
    row = Box(24, 24, 320, 28)
    stacks = {"bottom_left": [("wide", (300, 34)), ("narrow", (80, 34))],
              "top_left": [("t", (80, 34))], "bottom_right": [("n", (80, 34))]}
    found = corner_layout(stacks, CornerStyle(), [say, pill, row])
    assert found["t"].y == row.bottom + 8                                # below the F15 row
    assert found["wide"].bottom == say.y - 8                              # above the box
    assert found["narrow"].bottom == found["wide"].y - 8
    assert found["n"] == Box(W - 24 - 104, H - 24 - 50, 104, 50)          # beside the box


def test_items_that_do_not_fit_are_left_out_with_the_rest_of_their_corner():
    stacks = {"top_left": [(i, (80, 60)) for i in range(6)],
              "bottom_left": [("b", (80, 330)), ("c", (80, 10))]}
    found = corner_layout(stacks, CornerStyle())
    assert [k for k in range(6) if found[k] is not None] == [0, 1, 2, 3]    # ends by y 360
    assert all(found[k].bottom <= H / 2 for k in range(4))
    assert found["b"] is None and found["c"] is None   # would reach into the top-left stack
    layer = corner(reduce=True)
    layer.set_item("big", "top_right", Label("x", bar=100))
    layer.set_item("huge", "top_right", Label("y" * 60))
    assert boxes(layer)["huge"].w <= W / 2 - 24     # content kept to its half
    assert layer.overflow([Box(0, 0, W, 400)]) == ("big", "huge")


def test_reserved_areas_read_the_say_window_nvl_and_quick_menu():
    assert (sc.INDICATOR_TOPLEFT, skip_auto.INDICATOR_TOPLEFT) == ((24, 24), (24, 24))
    pill = SimpleNamespace(layout=SimpleNamespace(pill=Box(500, 690, 280, 28)))
    quick = SimpleNamespace(shown=lambda: pill)
    adv = SimpleNamespace(nvl=SimpleNamespace(on=False),
                          geometry=SimpleNamespace(box=(140, 504, 1000, 184)),
                          tab_top=lambda: 460.0)
    assert reserved_areas(adv, quick) == [Box(500, 690, 280, 28), Box(24, 24, 320, 28),
                                          Box(140, 460, 1000, 228)]
    metrics = SimpleNamespace(left=180, top=64, width=920, height=584)
    nvl = SimpleNamespace(nvl=SimpleNamespace(on=True, metrics=metrics))
    assert reserved_areas(nvl, None) == [Box(24, 24, 320, 32), Box(180, 64, 920, 584)]


# --- Set, replace, remove, fades ------------------------------------------------------------

def test_set_replace_move_remove_and_clear():
    layer = corner()
    with pytest.raises(ValueError, match="top_left"):
        layer.set_item("a", "middle", Label("a"))
    a, b = Label("a"), Label("b")
    layer.set_item("a", "top_left", a)
    layer.set_item("b", "top_left", b)
    newer = Label("A")
    layer.set_item("a", "top_left", newer)                  # same slot, new item
    assert layer.keys() == ("a", "b") and layer.item("a") is newer
    layer.set_item("a", "bottom_right", newer)              # moves to the end of that stack
    assert layer.keys("bottom_right") == ("a",) and layer.keys("top_left") == ("b",)
    layer.clear()
    assert layer.keys() == ()


def test_fades_and_reduce_motion_cuts():
    layer = corner()                                        # fade_ms 150
    layer.set_item("a", "top_left", Label("a"))
    assert layer.views()[0].opacity == 0.0
    layer.update(0.075)
    assert layer.views()[0].opacity == pytest.approx(0.5)
    layer.update(0.1)
    assert layer.views()[0].opacity == 1.0
    layer.remove_item("a")
    layer.update(0.075)
    assert layer.views()[0].opacity == pytest.approx(0.5)
    layer.set_item("a", "top_left", Label("a"))             # comes back from half
    assert layer.views()[0].opacity == pytest.approx(0.5)
    layer.remove_item("a")
    layer.update(0.2)
    assert layer.keys() == ()
    cut = corner(reduce=True)
    cut.set_item("a", "top_left", Label("a"))
    assert cut.views()[0].opacity == 1.0
    cut.remove_item("a")
    assert cut.keys() == ()
    cut.remove_item("unknown")                              # nothing


def test_items_are_measured_again_only_when_they_change():
    layer = corner(reduce=True)
    item = Label("a")
    layer.set_item("a", "top_left", item)
    for _ in range(3):
        layer.views()
    assert item.measured == 1
    item.text, item.revision = "abcdef", 1
    assert boxes(layer)["a"].w == 6 * 17 + 24 and item.measured == 2


# --- Tokens ---------------------------------------------------------------------------------

def test_corner_tokens_follow_the_text_box_and_author_colors_win(load):
    style = corner_style(plain_theme())
    assert style.frame.fill_color == PINK_WHITE and style.frame.fill_opacity == 0.90
    assert style.text_color == (0x3D, 0x2B, 0x36) and style.accent_color == BERRY
    amber = load('[theme]\npreset = "amber"\n').config.theme
    found = corner_style(plain_theme(amber))
    assert found.frame.fill_color == amber.textbox.fill_color
    assert found.text_color == amber.textbox.text_color
    own = load('[theme.corner]\ntext_color = "#112233"\nfill_opacity = 0.5\nmargin = 40\n')
    assert own.errors == [] and own.warnings == []
    style = corner_style(plain_theme(own.config.theme))
    assert style.text_color == (0x11, 0x22, 0x33) and style.frame.fill_opacity == 0.5
    assert style.margin == 40 and style.frame.fill_color == PINK_WHITE


@pytest.mark.parametrize("scheme", sorted(SCHEMES))
def test_every_scheme_meets_the_corner_contrast_pairs(load, scheme):
    cfg = load(f'[theme]\npreset = "{scheme}"\n').config.theme
    for pair in CORNER_PAIRS:
        assert min(pair_ratios(cfg, pair)) >= pair.minimum, (scheme, pair.fg)


def test_w67_names_a_pale_corner_color_over_the_see_through_fill():
    assert len(CORNER_PAIRS) == 2
    assert [t for t in contrast_warnings(plain_theme()) if "corner" in t] == []
    pale = dataclasses.replace(ThemeConfig(), corner=CornerTheme(text_color=(0xF0, 0xE0, 0xE8)))
    found = [t for t in contrast_warnings(plain_theme(pale)) if "corner" in t]
    assert len(found) == 1
    assert found[0].startswith("config.toml: [theme.corner] text_color #F0E0E8 on fill_color "
                               "#FFF4F8 at fill_opacity 0.9 gives ")
    assert "status corner text needs at least 4.5:1" in found[0]
    from engine.core.config_schema import TextboxTheme
    pale_box = dataclasses.replace(ThemeConfig(), textbox=TextboxTheme(text_color=(250, 250, 250)))
    assert [t for t in contrast_warnings(plain_theme(pale_box)) if "corner" in t] == []
    thin = dataclasses.replace(ThemeConfig(), corner=CornerTheme(fill_opacity=0.2))
    assert any("[theme.corner]" in t for t in contrast_warnings(plain_theme(thin)))


# --- The shell: visibility and drawing ------------------------------------------------------

class Stage(Screen):
    in_game = True

    def draw(self, canvas) -> None:
        canvas.fill(STAGE)


class Box_(Screen):
    """A say window stand-in: ``box_shown``, ``hidden``, ADV geometry."""
    in_game = True
    opaque = False

    def __init__(self) -> None:
        self.box_shown = True
        self.nvl = SimpleNamespace(on=False)
        self.geometry = SimpleNamespace(box=(140, 504, 1000, 184))

    def tab_top(self) -> float:
        return 460.0

    def reduce_motion(self) -> bool:
        return True


class Menu(Screen):
    opaque = False


class Opaque(Screen):
    in_game = True


def game_shell():
    config = Config()
    textbox = Box_()
    ports = ShellPorts(stack=ScreenStack(), assets=make_assets(None), dev=True, config=config,
                       new_game=lambda: None, in_game_screens=lambda: [],
                       reset_in_game=lambda: None, request_quit=lambda: None, textbox=textbox)
    shell = GameShell(ports, theme=plain_theme(config.theme), words=Words(config.words))
    shell.stack.push(Stage())
    shell.stack.push(textbox)
    shell.mode = Mode.GAME
    return shell, textbox


def test_shown_in_game_hidden_with_the_box_under_menus_and_opaque_screens():
    shell, textbox = game_shell()
    assert shell.corner_shown()
    textbox.nvl = SimpleNamespace(on=True, metrics=SimpleNamespace(
        left=180, top=64, width=920, height=584))
    assert shell.corner_shown()                                 # NVL
    textbox.box_shown = False                                   # hide key, window hide
    assert not shell.corner_shown()
    textbox.box_shown = True
    menu = Menu()
    shell.stack.push(menu)                                      # game menu, pages, confirms
    assert not shell.corner_shown()
    shell.stack.remove(menu)
    minigame = Opaque()
    shell.stack.push(minigame)
    assert not shell.corner_shown()
    shell.stack.remove(minigame)
    shell.mode = Mode.TITLE
    assert not shell.corner_shown()


def _frame(shell) -> pygame.Surface:
    canvas = Canvas(shell.assets)
    framebuffer = pygame.Surface(CANVAS_SIZE)
    canvas.bind(framebuffer, Viewport.compute(CANVAS_SIZE, CANVAS_SIZE), RenderQuality.FINAL)
    shell.assets.time.advance(None)
    shell.stack.draw(canvas)
    shell.draw_layer(canvas)
    return framebuffer


def close(a, b, tol=2) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def over(color, opacity, base):
    return tuple(round(c * opacity + b * (1 - opacity)) for c, b in zip(color, base,
                                                                         strict=True))


def test_draw_layer_draws_each_corner_and_nothing_while_hidden():
    shell, textbox = game_shell()
    for place in CORNER_PLACES:
        shell.corner.set_item(place, place, Label("Hana 3", bar=80))
    shell.update_layer(0.0, focused=True)
    views = {v.key: v for v in shell.corner.views(reserved_areas(textbox, None))}
    assert all(v.opacity == 1.0 for v in views.values())       # the textbox's reduce motion
    frame = _frame(shell)
    for place in CORNER_PLACES:
        box = views[place].box
        assert close(tuple(frame.get_at((int(box.x) + 6, int(box.y + box.h / 2))))[:3],
                     over(PINK_WHITE, 0.90, STAGE)), place
        bar = (int(box.x) + 12 + 40, int(box.bottom) - 8 - 5)  # the accent bar's middle
        assert close(tuple(frame.get_at(bar))[:3], BERRY), place
        text = [tuple(frame.get_at((x, y)))[:3] for x in range(int(box.x) + 12, int(box.x) + 60)
                for y in range(int(box.y) + 8, int(box.y) + 40)]
        assert any(sum(c) < 300 for c in text), place           # plum text
    say = Box(140, 460, 1000, 228)
    assert not any(sc._overlaps(v.box, say) for v in views.values())   # beside the box
    textbox.box_shown = False
    assert tuple(_frame(shell).get_at((30, 30)))[:3] == STAGE


def test_the_corner_follows_a_new_look_through_sync_look():
    shell, _ = game_shell()
    assert shell.corner.style.frame.fill_color == PINK_WHITE
    shell._corner_style = sc.CornerStyle(text_color=(1, 2, 3))   # what sync_look sets
    assert shell.corner.style.text_color == (1, 2, 3)


def test_shell_measures_in_the_corner_font():
    shell, _ = game_shell()
    style = shell.corner.style
    measure = measure_with(shell.assets, style.font)
    shell.corner.set_item("a", "top_left", Label("Hana"))
    assert shell.corner.views()[0].box.w == pytest.approx(measure("Hana", 24) + 24)
