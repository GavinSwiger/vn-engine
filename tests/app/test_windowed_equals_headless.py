"""F09 step 4 — AC-F09-16, the same story everywhere (TR-F09-01; ``06-acceptance.md`` §0.2).
F19 step 4 adds AC-F19-23's windowed rows (Template R, ``walk/`` run 1).

Fixture ``all/`` (§5) played in App A (the real ``App`` on a ``FakeWindow``, a fake 1/60 s
clock, ``install_story``) under each of: defaults; ``[effects] reduce = true``; every
transition clicked through in its 2nd RUNNING frame; longer ``[effects]`` lengths. The
commands the App dispatches equal run H's (``run_headless``, seed 7), wait ids included,
compared as F03's canonical JSON. Lines show instantly and are pressed 2 frames after they
arrive; an untimed ``pause`` is pressed; a menu is answered with key 1. The window is 640×360:
only commands are compared.
"""

import shutil
from pathlib import Path

import pygame
import pytest

from engine.runtime.commands import StoryEnded
from engine.runtime.headless import run_headless
from engine.ui.builtin.choice_screen import ChoiceScreen
from tests.fakes.text_app import Session, make_text_game
from tests.fixtures.F04 import gen_images as gen
from tests.runtime.corpus import canon
from tests.runtime.effects_story import F09, IMG9, load_game
from tests.runtime.endings_story import F19
from tests.script.helpers import template_e

pytestmark = pytest.mark.display

INSTANT = "[textbox]\ncps = 0\n"
IMAGES = {"bg ember": (200, 40, 0), "bg sea": (0, 80, 240), "bg river": (0, 0, 255)}
SPRITES = {"hana happy": (0, 255, 0), "hana sad": (0, 255, 0), "daichi grin": (255, 255, 0)}


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def game(root: Path, config: str) -> Path:
    text = (F09 / "all" / "script" / "main.vns").read_text(encoding="utf-8")
    root = make_text_game(root, script=text, config=INSTANT + config)
    images = {gen.ref_of(n): gen.block(1280, 720, c) for n, c in IMAGES.items()}
    images.update({gen.ref_of(n): gen.block(300, 600, c) for n, c in SPRITES.items()})
    images["masks/iris.png"] = gen.block(64, 36, (128, 128, 128))
    gen.write(root, images)
    return root


def windowed(root: Path, *, click_through: bool) -> list:
    s = Session(root, size=(640, 360))
    commands: list = []

    def script(s: Session):
        router = s.app.router
        dispatch = router.dispatch

        def spy(command):
            commands.append(command)
            if not isinstance(command, StoryEnded):      # the shell would quit at once
                dispatch(command)

        router.dispatch = spy
        arrived, line, running = 0, None, 0
        for _ in range(3000):
            yield
            if commands and isinstance(commands[-1], StoryEnded):
                return
            stage, text = s.app.stage_screen, s.line_text()
            if stage is None:
                continue
            if isinstance(s.app.screens.top, ChoiceScreen):
                if s.frame % 6 == 0:
                    s.key(pygame.K_1)                    # F19's walk/: choose 1
                continue
            if text != line:
                line, arrived = text, s.frame
            run = stage.view._run
            running = running + 1 if run is not None and run.running else 0
            if click_through and running == 2:
                s.key(pygame.K_SPACE)                    # its 2nd RUNNING frame
            elif stage.wait_kind == "click" or (
                    text is not None and stage.wait_kind is None and s.frame - arrived == 2):
                s.key(pygame.K_SPACE)
        raise AssertionError("the story did not end")

    s.play(script, last=3200)
    return commands


@pytest.mark.parametrize("config, click_through", [
    ("", False),
    ("[effects]\nreduce = true\n", False),
    ("", True),
    ("[effects]\ndissolve = 2.0\nfade = 3.0\nshake = 1.0\nflash = 1.0\n", False),
], ids=["defaults", "reduce", "click-through", "lengths"])
def test_ac_f09_16_same_story_everywhere(tmp_path, config, click_through):
    root = game(tmp_path / "g", config)
    expected = canon(run_headless(load_game(root), seed=7, image_files=IMG9))
    assert canon(windowed(root, click_through=click_through)) == expected
    shutil.rmtree(root)


# --- AC-F19-23's windowed rows: an ending's card, then the end -----------------------------------

def test_ac_f19_23_endings_same_story_windowed(tmp_path):
    """Template R (no S, no T) and ``walk/`` run 1 (``choose 1``, ``[choice] show_locked``),
    with ``[effects] reduce`` false and true: the App releases ``run_headless``'s commands
    (the card's ``ShowStage``, its stage wait, the 3.0 s hold, ``StoryEnded``)."""
    walk = (F19 / "walk" / "script" / "main.vns").read_text(encoding="utf-8")
    rows = [("template", template_e(), []), ("walk", walk, ["advance", "choose 1"])]
    for name, text, inputs in rows:
        for reduce in ("false", "true"):
            root = make_text_game(tmp_path / f"{name}-{reduce}", script=text,
                                  config=INSTANT + "[choice]\nshow_locked = true\n"
                                  f"[effects]\nreduce = {reduce}\n")
            expected = run_headless(load_game(root), seed=7, inputs=inputs, show_locked=True)
            assert type(expected[-1]) is StoryEnded and any(
                getattr(getattr(c, "card", None), "kind", None) == "ending" for c in expected)
            assert canon(windowed(root, click_through=False)) == canon(expected), (name, reduce)
            shutil.rmtree(root)
