"""F38 step 2 — blinking and talking in the App (``install_stage`` builds the animator,
``install_sprite_anim`` feeds it the textbox's lines and typing, ``StageScreen`` ticks it):
AC-F38-07 (presentation only: the story state mid-talk equals the one with ``[animation]
enabled = false``; rollback back and forward shows plain looks and the restored line never
talks) and AC-F38-15 (an NVL line flaps; ``set_index`` after F39 picks up a new frame file).

Each run is ``tests/app/test_stage_wiring.py``'s ``Played``: an in-process App on a fake
1/60 s clock and a ``FakeWindow``; the prefetcher decodes unthreaded.
"""

from pathlib import Path

import pygame
import pytest

from engine.render import prefetch
from engine.runtime.commands import StepBack, StepForward
from engine.runtime.images import ImageFile, ImageIndex, look_frames
from tests.app.test_stage_wiring import Played, make_game
from tests.fakes.loop import post_key
from tests.fixtures.F04 import gen_images as gen

pytestmark = pytest.mark.display


@pytest.fixture(autouse=True)
def pygame_ready(monkeypatch):
    # The fake clock never sleeps, which starves the decode thread (``prefetch.py``): decode
    # in ``pump`` instead, as the per-OS fallback does (same pixels, AC-F04-44).
    monkeypatch.setattr(prefetch, "PREFETCH_THREADED", False)
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()

LOOK = gen.block(60, 120, (0, 200, 0))
TALK = gen.block(60, 120, (200, 0, 0))
CONFIG = "\n[textbox]\ncps = 30\n\n[animation]\nblink_every = 30.0\n"


class Spy:
    """Per frame: the line shown, the animator's speaker, and the frames on the stage."""

    def __init__(self, actions: dict[int, object] | None = None) -> None:
        self.rows: list[tuple[int, str | None, str | None, dict]] = []
        self.states: dict[int, dict] = {}
        self.actions = actions or {}

    def __call__(self, played: Played) -> None:
        app = played.app
        frame = played.limiter.frame
        action = self.actions.get(frame)
        if action is not None:
            action(app)
        stage = getattr(app, "stage_screen", None)
        if stage is None or getattr(app, "sprite_anim", None) is None:
            return
        self.rows.append((frame, played.line, app.sprite_anim.speaker,
                          dict(stage.view.shown_frames)))
        story = getattr(app, "story", None)
        state = None if story is None else story.interp.checkpoint()
        if state is not None:
            self.states[frame] = state.to_json()          # what a save takes

    def talk_frames(self, lo: int = 0, hi: int = 10 ** 9) -> list[int]:
        return [f for f, _, _, shown in self.rows if lo <= f < hi and shown]


def game(root: Path, script: str, *, talk: bool = True, config: str = CONFIG) -> Path:
    images = {gen.ref_of("hana happy"): LOOK}
    if talk:
        images[gen.ref_of("hana happy_talk1")] = TALK
    return make_game(root, script, images, config)


ADV = '''define hana = Character("Hana")

label start:
    show hana happy
    hana "The lanterns are lit all along the river."
    hana "Shall we walk down to the water together?"
    "Fin."
'''


def test_ac_f38_07_presentation_only(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.app.story.secrets.randbits", lambda bits: 7)   # same dice
    def back(app):
        app.story.post(StepBack(1))

    def forward(app):
        app.story.post(StepForward(1))

    def press(app):
        post_key(pygame.K_SPACE)

    spy = Spy({110: press, 150: back, 200: forward})
    Played(game(tmp_path / "on", ADV), last=240, on_frame=spy)
    off = Spy({110: press})
    Played(game(tmp_path / "off", ADV, config=CONFIG + "enabled = false\n"), last=60,
           on_frame=off)
    talked = spy.talk_frames(0, 110)
    assert talked and off.talk_frames() == []
    mid = talked[len(talked) // 2]                       # Hana's mouth is open here
    assert spy.states[mid] == off.states[mid]            # the story never saw it
    # Line 2 talks, then a step back restores line 1 and a step forward line 2: plain
    # looks, and the restored lines never talk.
    assert spy.talk_frames(112, 150)
    after = [(f, line, speaker, shown) for f, line, speaker, shown in spy.rows if f > 151]
    assert any(line and line.startswith("The lanterns") for _, line, _, _ in after)
    assert any(line and line.startswith("Shall we") for f, line, _, _ in after if f > 201)
    assert all(not shown and speaker is None for _, _, speaker, shown in after)


NVL = '''define hana = Character("Hana")

label start:
    show hana happy
    nvl on
    hana "In the full-screen page her mouth moves too, letter by letter, on and on."
    "Fin."
'''


def test_ac_f38_15_nvl_flaps_and_set_index_reads_new_frames(tmp_path):
    root = game(tmp_path / "nvl", NVL)
    spy = Spy()
    Played(root, last=150, on_frame=spy)
    assert len(spy.talk_frames()) >= 5                   # an NVL line flaps

    # F39: a frame file added while the game runs is picked up by ``set_index``.
    root = game(tmp_path / "late", NVL, talk=False)

    def add_frame(app):
        gen.write(root, {gen.ref_of("hana happy_talk1"): TALK})
        app.assets.paths.invalidate_listings()           # F39 rescans the folder
        view = app.stage_screen.view
        index = ImageIndex({**dict(view.index.items()),
                            "hana happy_talk1": ImageFile(gen.ref_of("hana happy_talk1"))})
        app.stage_screen.set_index(index, look_frames(index))

    late = Spy({60: add_frame})
    Played(root, last=150, on_frame=late)
    assert late.talk_frames(0, 61) == [] and len(late.talk_frames(61)) >= 3
