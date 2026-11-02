"""F05 step 7 — AC-F05-43: the example game played headless and in App A with the same seed
gives the same released commands, ``Say.body`` included (TR-F05-03, invariant 7).

App A plays a copy of ``game/`` with the title off and ``cps = 0`` (presentation only: typing
speed never changes a command), pressing Space every third frame; the headless run advances
at every line. ``06`` §4 lists this AC under ``tests/runtime/``; it lives here because App A
needs the display fixtures of ``tests/app``.
"""

import shutil
from pathlib import Path

import pygame
import pytest

from engine.core.config import load_config
from engine.core.paths import GamePaths
from engine.runtime.commands import Say, StoryEnded
from engine.runtime.headless import run_headless
from engine.script import LoadOptions, load_story
from tests.fakes.text_app import Session

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "game"

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def test_ac43_headless_and_windowed_runs_agree(tmp_path):
    root = tmp_path / "game"
    # Not a playtest's persistent data or saves: the headless run starts with none.
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("logs", "persistent", "saves",
                                                                "settings", "characters"))
    with (root / "config.toml").open("a", encoding="utf-8") as f:
        f.write("\n[title]\nenabled = false\n\n[textbox]\ncps = 0\n")
    paths = GamePaths.for_game(root)
    positions = frozenset(load_config(paths).config.stage.positions)
    from tests.runtime.stage_story import example_minigames
    program = load_story(paths, LoadOptions(position_names=positions,
                                            minigames=example_minigames())).program
    images = tuple(sorted(p.relative_to(root).as_posix()
                          for p in (root / "images").rglob("*") if p.is_file()))
    # F07: the example's menus take their first choice, as the window's Space presses do.
    from tests.runtime.corpus import play
    # F19: game/config.toml sets [choice] show_locked = true; the window reads it.
    headless = run_headless(program, seed=7, image_files=images, show_locked=True,
                            inputs=play(program, 7, images).inputs, minigames=example_minigames())
    assert headless[-1] == StoryEnded()

    s = Session(root)
    s.app.seed = 7                                   # as ``run --seed 7``
    released = []
    real_dispatch = s.app.router.dispatch

    def dispatch(command):
        released.append(command)
        real_dispatch(command)

    s.app.router.dispatch = dispatch

    def script(s):
        while not released or released[-1] != StoryEnded():
            host = s.app.minigame_host
            if getattr(host, "session", None) is not None:
                # F24-4: the poem ends by Shift+F8 (dev), with the test outcome headless uses.
                if s.frame % 3 == 0:
                    Session.key(pygame.K_F8, pygame.KMOD_SHIFT)
            elif s.frame % 3 == 0 and s.textbox is not None and s.textbox.line is not None:
                Session.key(pygame.K_SPACE)
            yield

    assert s.play(script, last=3000) == 0
    assert released == headless
    bodies = [c.body for c in released if type(c) is Say]
    assert any(len(body.pieces) > 1 for body in bodies)          # styled lines took part
