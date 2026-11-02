"""``CapturedBackdrop`` under a menu (F10 ``04`` §7.6; TR-F10-04): one capture per open and per
viewport change, held ``SizedLru`` entries released on close, the dim colors of the probes in
``06`` §0.4, and fade B (the scene opaque, a partial dim, the content layer)."""

import pygame
import pytest

from engine.core.config_schema import ThemeConfig
from engine.render.canvas import RenderQuality
from engine.ui.backdrop import BACKDROP_KEY, CapturedBackdrop
from engine.ui.builtin.confirm import ConfirmScreen
from engine.ui.menu_screen import Phase
from engine.ui.nav import InputKind
from engine.ui.paint import SHAPE_KEY
from tests.fakes.ui_shell import ColumnMenu, SolidScreen, TestShell, UiHarness

pytestmark = pytest.mark.display

CFG = ThemeConfig()
D = (1000, 100)                       # a probe away from every panel (06 §0.4)


def menu_over_scene(*, fade=True, keep_scene=True):
    shell = TestShell()
    h = UiHarness(shell)
    scene = SolidScreen((200, 200, 200))
    shell.stack.push(scene)
    backdrop = CapturedBackdrop(shell.assets, CFG.menu.dim_color, CFG.menu.dim_opacity,
                                keep_scene=keep_scene)
    menu = ColumnMenu(shell, by=InputKind.KEYS, fade=fade, backdrop=backdrop)
    shell.stack.push(menu)
    return shell, h, scene, menu, backdrop


def backdrop_keys(shell):
    return [k for k in shell.assets.cache.keys() if k[0] == BACKDROP_KEY]


def near(actual, expected, tol=2):
    return all(abs(a - e) <= tol for a, e in zip(actual, expected))


def test_the_scene_is_captured_once_and_dimmed():
    shell, h, scene, menu, backdrop = menu_over_scene(fade=False)
    h.frame()
    assert backdrop.captures == 1 and backdrop.ready and menu.opaque
    draws = scene.draws
    builds = shell.painter.builds
    for _ in range(60):
        h.frame()
    assert scene.draws == draws                     # the frozen scene is never drawn again
    assert backdrop.captures == 1 and shell.painter.builds == builds
    assert near(h.px(*D), (113, 107, 111))


def test_held_entries_until_close():
    shell, h, scene, menu, backdrop = menu_over_scene(fade=False)
    h.frame()
    keys = backdrop_keys(shell)
    assert sorted(k[2] for k in keys) == ["dimmed", "scene"]
    cost = 1280 * 720 * 4
    assert all(shell.assets.cache.cost(k) == cost for k in keys)
    menu.close()
    assert backdrop_keys(shell) == [] and backdrop.scene is None


def test_resize_recaptures_once():
    shell, h, scene, menu, backdrop = menu_over_scene(fade=False)
    h.frames(3)
    h.resize((1920, 1080))
    h.frame()                                       # the old picture, scaled
    assert backdrop.captures == 1 and not menu.opaque
    assert near(h.px(*D), (113, 107, 111), 3)
    h.frame()                                       # the screens below again, recaptured
    assert backdrop.captures == 2 and menu.opaque
    assert backdrop.dimmed.get_size() == (1920, 1080)
    h.frames(30)
    assert backdrop.captures == 2
    h.resize((1920, 1080), RenderQuality.FAST)
    h.frames(2)
    assert backdrop.captures == 3                   # quality is part of the key


def test_invalidate_recaptures():
    shell, h, scene, menu, backdrop = menu_over_scene(fade=False)
    h.frames(2)
    backdrop.invalidate()
    h.frames(2)
    assert backdrop.captures == 2


def test_steady_open_menu_builds_no_shape():
    shell, h, scene, menu, backdrop = menu_over_scene()
    h.frames(12)
    assert menu.phase is Phase.OPEN
    puts = [k for k in shell.assets.cache.keys() if k[0] in (SHAPE_KEY, BACKDROP_KEY)]
    builds = shell.painter.builds
    h.frames(60)
    assert shell.painter.builds == builds and backdrop.captures == 1
    assert [k for k in shell.assets.cache.keys() if k[0] in (SHAPE_KEY, BACKDROP_KEY)] == puts


def test_fade_b_dims_progressively():
    shell, h, scene, menu, backdrop = menu_over_scene()
    reds = []
    for _ in range(11):
        h.frame()
        reds.append(h.px(*D)[0])
    assert reds[0] == 200 and near((reds[-1],), (113,))
    assert reds == sorted(reds, reverse=True)
    assert menu.phase is Phase.OPEN


def test_confirm_over_a_menu_dims_again():
    shell, h, scene, menu, backdrop = menu_over_scene(fade=False)
    h.frame()
    confirm = ConfirmScreen(shell, "Quit?", lambda: None, by=InputKind.KEYS, fade=False)
    shell.stack.push(confirm)
    h.frames(2)
    assert near(h.px(*D), (88, 80, 85), 3)
    assert confirm.backdrop.scene is None          # the confirm keeps no scene


def test_a_confirm_drops_its_scene_after_the_opening_fade_and_fades_out_live():
    shell, h, scene, menu, backdrop = menu_over_scene(fade=False)
    h.frame()
    confirm = ConfirmScreen(shell, "Quit?", lambda: None, by=InputKind.KEYS)
    shell.stack.push(confirm)
    h.frame()
    assert confirm.backdrop.scene is not None
    h.frames(10)
    assert confirm.phase is Phase.OPEN and confirm.backdrop.scene is None
    h.frame(UiHarness.key(pygame.K_ESCAPE))
    assert confirm.backdrop.live and not confirm.opaque
    values = []
    for _ in range(10):
        h.frame()
        values.append(h.px(*D)[0])
    assert shell.stack.top is menu
    assert near((values[-1],), (113,))
    assert values == sorted(values)


def test_scene_picture_is_the_undimmed_scene():
    shell, h, scene, menu, backdrop = menu_over_scene(fade=False)
    h.frame()
    picture = backdrop.scene_picture()
    assert picture is not None and picture.get_at((1000, 100))[:3] == (200, 200, 200)
