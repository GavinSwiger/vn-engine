"""AC-F23-62 (example game rows): ``game/minigames/lantern_memory.py`` and the festival
scene. Loader L loads the real plugin file; Host U clears the board by keyboard only and by
gamepad only, following the layout the seed dealt. The headless rows run the example with
seeds 1–5 and no warning."""

import logging
import re
from pathlib import Path

import pygame
import pytest

from engine.core.minigame_types import ArgSpec, MeterChange
from engine.minigames.host import Phase
from tests.fakes.ui_shell import UiHarness as H
from tests.minigames.conftest import write
from tests.minigames.host_u import HostU

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "game" / "minigames" / "lantern_memory.py"
COLUMNS = 4
KEYS = {"down": pygame.K_DOWN, "up": pygame.K_UP, "right": pygame.K_RIGHT,
        "left": pygame.K_LEFT, "press": pygame.K_RETURN}
PAD = {"down": pygame.CONTROLLER_BUTTON_DPAD_DOWN, "up": pygame.CONTROLLER_BUTTON_DPAD_UP,
       "right": pygame.CONTROLLER_BUTTON_DPAD_RIGHT, "left": pygame.CONTROLLER_BUTTON_DPAD_LEFT,
       "press": pygame.CONTROLLER_BUTTON_A}


@pytest.fixture
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def _moves(start: int, target: int) -> list[str]:
    rows = target // COLUMNS - start // COLUMNS
    columns = target % COLUMNS - start % COLUMNS
    return (["down" if rows > 0 else "up"] * abs(rows)
            + ["right" if columns > 0 else "left"] * abs(columns))


@pytest.mark.parametrize("device", ["keys", "pad"])
def test_ac_f23_62_lantern_memory_plays_by_keyboard_and_gamepad(game, load, pygame_ready,
                                                                 device):
    write(game, "minigames/lantern_memory.py", PLUGIN.read_bytes())
    loaded = load(game)
    assert loaded.errors == [] and loaded.warnings() == []
    entry = loaded.result.registry.get("lantern_memory")
    sig = entry.sig
    assert sig.args == (ArgSpec("pairs", sig.args[0].default), ArgSpec("hints", False))
    assert sig.check is not None and sig.test is not None
    assert sig.test.result == 9 and sig.test.changes == (MeterChange("hana", "+=", 1),)
    plugin = entry.cls()
    assert plugin.check_args({"pairs": 6, "hints": False}) is None
    for bad in ({"pairs": 1, "hints": False}, {"pairs": 9, "hints": False},
                {"pairs": True, "hints": False}, {"pairs": 6, "hints": "yes"}):
        assert plugin.check_args(bad) is not None, bad

    w = HostU(game, registry=loaded.result.registry)
    w.start("lantern_memory", {"pairs": 6, "hints": True}, restored=False)
    w.frames(30)                                          # the fade-in ends; focus shows
    session = w.session
    assert session.phase is Phase.RUNNING and w.fatal == []
    game_ = session.plugin
    cards = game_.cards
    assert sorted(cards) == sorted(["Moon", "Crane", "Fish", "Star", "Bell", "Kite"] * 2)
    assert session.scope.focused is game_.buttons[0]
    send = (lambda name: H.key(KEYS[name])) if device == "keys" else (lambda name: H.pad(PAD[name]))
    at = 0
    for picture in dict.fromkeys(cards):
        for target in [i for i, c in enumerate(cards) if c == picture]:
            for move in _moves(at, target):
                w.frame(send(move))
            assert session.scope.focused is game_.buttons[target]
            w.frame(send("press"))
            at = target
    w.frames(40)
    done = w.done()
    assert [d.result for d in done] == [6] and w.fatal == []
    assert done[0].changes == (MeterChange("hana", "+=", 1),)


def test_ac_f23_62_the_festival_scene_uses_it(caplog):
    """The festival scene calls it with ``into turns`` and branches on ``turns``; the example
    plays headless (seeds 1–5) with zero WARNING records."""
    from tests.runtime import corpus

    text = (REPO / "game" / "script" / "chapter1.vns").read_text(encoding="utf-8")
    assert re.search(r"^    minigame lantern_memory pairs=\d .*into turns$", text, re.M)
    assert re.search(r"^    if turns <= \d+:$", text, re.M)
    caplog.set_level(logging.WARNING)
    program, images = corpus.example_program(), corpus.example_images()
    for seed in range(1, 6):
        played = corpus.play(program, seed, images, corpus.EXAMPLE_PICKS[seed])
        assert played.commands, seed
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
