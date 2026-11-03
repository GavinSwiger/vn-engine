"""F32 step 5: choices, the quick menu, and menus in a style (``06-acceptance.md`` AC-F32-20;
``04`` §6.4, §6.5; D2).

Uses ``StyleRig`` (``tests/ui/test_textbox_style.py``): the launch order of ``install_story``
with Template U's styles; ``ShowMenu`` and ``UiStyle`` go through the App's router.
"""

from types import SimpleNamespace

import pygame
import pytest

from engine.app.text_check import composite
from engine.render.choices import half_up
from engine.render.textbox import hex_rgb
from engine.runtime.commands import ShowMenu, ShownChoice
from engine.ui.builtin.choice_screen import ChoiceScreen
from engine.ui.builtin.quick_menu import QuickMenu
from engine.ui.builtin.textbox_screen import TextSettings
from tests.fakes.fixed_font import tagged
from tests.ui.test_textbox_style import StyleRig, close

pytestmark = pytest.mark.display

QUICK = '[style.ashes.theme.quick_menu]\nfill_color = "#401020"\ntext_size = 24\n'


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


def menu(rig: StyleRig) -> ChoiceScreen:
    rig.show("Which way?", "main/5")
    rig.app.router.dispatch(ShowMenu("menu/1", (ShownChoice("c1", tagged("Left"), False),
                                                ShownChoice("c2", tagged("Right"), False)),
                                     "question", False))
    for _ in range(400):
        rig.frame()
        top = rig.app.screens.top
        if isinstance(top, ChoiceScreen):
            rig.h.frames(30)                               # past the fade-in
            return top
    raise AssertionError("the menu never opened")


def quick_menu(rig: StyleRig) -> QuickMenu:
    return next(o for o in rig.textbox.overlays if isinstance(o, QuickMenu))


def test_ac_f32_20_choices_quick_menu_and_menus_in_a_style(tmp_path):
    rig = StyleRig(tmp_path / "calm", QUICK)
    base_choice = rig.app.config.theme.choice
    rig.style("calm")
    screen = menu(rig)
    controller = rig.choices
    # calm's choice fill; the focused fill and the sounds stay the base's (calm sets none).
    assert controller.theme.fill_color == hex_rgb("#334455")
    assert controller.view.theme.fill_color == hex_rgb("#334455")
    assert controller.theme.focused.fill_color == base_choice.focused.fill_color
    assert (controller.focus_sound, controller.pick_sound) == \
        (base_choice.focus_sound, base_choice.pick_sound)
    want = composite(hex_rgb("#334455"), base_choice.fill_opacity, (0, 0, 0))
    x = 640 - base_choice.width / 2 + 10
    focused = screen.focus
    column = [rig.px(x, y) for y in range(16, int(rig.textbox.tab_top()))]
    assert any(close(p, want) for p in column), (focused, column[::20])

    # ashes at 150 %: (choice.text_size or base) × textbox.text_scale().
    ashes = StyleRig(tmp_path / "ashes", QUICK)
    ashes.style("ashes")
    ashes.textbox.settings = TextSettings(text_size_pct=150)
    menu(ashes)
    c = ashes.choices
    base = c.theme.text_size if c.theme.text_size is not None else 30
    assert c.base_text_size == 30
    assert c.text_size() == half_up(base * ashes.textbox.text_scale()) == 45

    # A switch to ashes with [style.ashes.theme.quick_menu]: the pill's colors and layout
    # change in the switch frame (D2).
    q = StyleRig(tmp_path / "quick", QUICK)
    q.show("A line.")
    q.frame()
    qm = quick_menu(q)
    before = qm.shown().layout
    pill = before.pill
    probe = (pill.x + 4, pill.y + pill.h / 2)
    base_px = q.px(*probe)
    q.style("ashes")
    q.frame()
    after = qm.shown().layout
    assert after.text_size != before.text_size
    pill = after.pill
    got = q.px(pill.x + 4, pill.y + pill.h / 2)
    assert got != base_px
    assert close(got, composite(hex_rgb("#401020"), q.shell.theme.cfg.quick_menu.fill_opacity,
                                (0, 0, 0))), got

    # Game menu and quick menu under ashes say Keep for Save; after `ui style off`, Save.
    # (This rig has no F11 saves, so the Save entry's label is asked directly: both menus
    # label entries through the shell's words.)
    menus = q.shell.menus
    plain_ids = ([e.id for e in menus.shown("game")], [e.id for e in menus.shown("quick")])
    words = q.shell.words
    save = SimpleNamespace(id="save")
    assert words.get("save") == "Keep" and qm.label(save) == "Keep"
    q.style(None)
    q.frame()
    assert words.get("save") == "Save" and qm.label(save) == "Save"
    # Entries under any style: the same id lists as with no style.
    for name in ("ashes", "calm", None):
        q.style(name)
        assert ([e.id for e in menus.shown("game")],
                [e.id for e in menus.shown("quick")]) == plain_ids
