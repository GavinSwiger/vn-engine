"""F28 step 4 — save thumbnails show glitches (``06-acceptance.md`` AC-F28-21; ``07`` §2.2:
thumbnails come from the framebuffer, so they include glitches).

App A on Template G with ``effect static large on`` ⏎ ``effect tear large on`` and a control
without them. At "A." the shell's scene capture (F11 C3: the quick save and the Save page
both take it) is asked for a thumbnail; it is the frame as drawn, scaled to 320×180.
Deviation (lean): the capture is asked directly rather than through F5 and a written save;
F11's AC-F11-16 proves a save stores what ``capture_scene`` hands it.
"""

import pygame
import pytest

from engine.render.thumbnail import THUMB_SIZE, make_thumbnail
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen
from tests.render.glitch_screen import GRAIN_REF, GREEN, grain

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    """As ``tests/ui/conftest.py`` (this package's conftest has no display)."""
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


GRID = [(20 + 40 * i, 20 + 45 * j) for i in range(4) for j in range(4)]   # 16 probes, 320×180


def _thumbnail(root, effects: str) -> tuple[pygame.Surface, pygame.Surface]:
    """(the captured thumbnail, the presented frame it was taken from)."""
    script = ('define hana = Character("Hana")\nlabel start:\n    scene bg grain\n'
              '    show hana happy at center\n' + effects + '    hana "A."\n    "End."\n')
    root = make_text_game(root, script=script, config="[textbox]\ncps = 0\n")
    gen.write(root, {GRAIN_REF: grain(), gen.ref_of("hana happy"): gen.block(300, 600, GREEN)})
    s = Session(root)
    got: list = []

    def script_(s: Session):
        yield from s.until_line("A.")
        yield
        s.app.shell.capture_scene(got.append)              # served in this frame's draw
        yield
        got.append(s.fb.copy())

    s.play(script_)
    assert got[0] is not None and got[0].get_size() == THUMB_SIZE
    return got[0], got[1]


def _px(surface: pygame.Surface, point: tuple[int, int]) -> tuple[int, ...]:
    return tuple(surface.get_at(point))[:3]


def test_ac_f28_21_save_thumbnails_show_glitches(tmp_path):
    thumb, frame = _thumbnail(tmp_path / "g", "    effect static large on\n"
                                              "    effect tear large on\n")
    drawn = make_thumbnail(frame)
    for point in GRID:
        assert all(abs(a - b) <= 8 for a, b in zip(_px(thumb, point), _px(drawn, point))), point
    control, _ = _thumbnail(tmp_path / "c", "")
    assert any(max(abs(a - b) for a, b in zip(_px(thumb, p), _px(control, p))) > 24
               for p in GRID)
