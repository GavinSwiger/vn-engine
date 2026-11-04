"""F49: a style's color scheme in the headless app (AC-F49-08; 07 I-1, I-2).

Every launch is F32's ``LookRig`` (``tests/ui/test_title_playthrough.py``): the title rig
with ``install_looks``. ``ui style term`` is the ``UiStyle`` command its handler gets.
"""

import pygame
import pytest

from engine.core.schemes import SCHEMES
from engine.runtime.commands import UiStyle
from tests.ui.test_title_playthrough import LookRig

pytestmark = pytest.mark.display

SCHEME_STYLE = '[style.term.theme]\npreset = "amber"\n'


def rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


AMBER = {role: rgb(value) for role, value in SCHEMES["amber"].colors.items()}
SAKURA = {role: rgb(value) for role, value in SCHEMES["sakura"].colors.items()}


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    yield
    pygame.quit()


# --- AC-F49-08 — ui style term recolors the menus; ui style off brings Sakura back -------------

def test_ac_f49_08_a_scheme_style_in_the_app(tmp_path):
    rig = LookRig(tmp_path, SCHEME_STYLE)
    shell = rig.shell
    shell.start_new_game()
    rig.frames(60)
    base = shell.theme
    assert base is shell.base_theme and base.cfg.panel.fill_color == SAKURA["fill"]
    rig.app.router.dispatch(UiStyle("term"))
    assert shell.theme.cfg.panel.fill_color == AMBER["fill"]
    assert shell.theme.cfg.title == base.cfg.title                    # never the title (D2)
    rig.app.router.dispatch(UiStyle(None))
    assert shell.theme is base and shell.theme.cfg.panel.fill_color == SAKURA["fill"]
