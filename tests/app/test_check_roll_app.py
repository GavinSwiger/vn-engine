"""F59's dice roll in the App (App A, ``tests/fakes/text_app.py``): after a checked pick the
roll card shows, tumbles, lands on the rolled faces with the sum and the result, and the
story goes on when the wait ends; a click ends it early; Reduce motion shows the result at
once; skip shows nothing for longer than a frame; going back never shows it again. Also the
card's pure timing and texts (``ui/builtin/check_roll``), and a retry choice locked."""

import os

import pygame
import pytest

from engine.runtime.commands import CheckRolled
from engine.ui.builtin.check_roll import (FACE_STEP_S, LAND_S, CheckRollScreen, result_text,
                                          roll_frame, sum_text, tumble_face)
from tests.app.test_skip_auto_app import story

pytestmark = pytest.mark.display

SCRIPT = '''points empathy 0 to 10 start 3
label start:
    "The river is loud tonight."
    menu:
        "You're scared of something." check empathy medium retry:
            success:
                "...Of the river."
            failure:
                "He looks away."
        "Listen.":
            points empathy += 1
    "Again."
    jump start
'''
BODY = SCRIPT.split("label start:\n", 1)[1]
HEAD = SCRIPT.split("label start:\n", 1)[0]
SHOTS = os.environ.get("VN_CHECK_SHOTS")          # a folder: save the two screenshots there


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def _cmd(**kw) -> CheckRolled:
    base = dict(wait_id=7, sid="start/0123456789ab", seconds=1.3, for_stage=False,
                hide_box=False, meter="Empathy", dice=(4, 2), value=3, difficulty=10,
                ok=False)
    return CheckRolled(**{**base, **kw})


# --- the card, pure -------------------------------------------------------------------------

def test_the_dice_tumble_then_land_on_the_roll():
    cmd = _cmd()
    frames = [roll_frame(cmd, n * FACE_STEP_S, reduce=False) for n in range(8)]
    assert not any(f.landed for f in frames)
    faces = [f.faces for f in frames]
    assert all(a != b for a, b in zip(faces, faces[1:]))          # a new face each step
    assert all(1 <= x <= 6 for pair in faces for x in pair)
    assert faces == [roll_frame(cmd, n * FACE_STEP_S, reduce=False).faces for n in range(8)]
    assert any(max(f.lifts) > 0 for f in frames)
    landed = roll_frame(cmd, LAND_S, reduce=False)
    assert (landed.faces, landed.lifts, landed.landed) == ((4, 2), (0.0, 0.0), True)
    assert roll_frame(cmd, 0.0, reduce=True) == landed              # Reduce motion: at once
    assert all(tumble_face(3, s, 0) != tumble_face(3, s + 1, 0) for s in range(30))


def test_the_card_texts():
    assert sum_text(_cmd(), False) == "Needs 10"
    assert sum_text(_cmd(), True) == "Dice 6 + Empathy 3 = 9 vs 10"
    assert sum_text(_cmd(value=-2), True) == "Dice 6 - Empathy 2 = 4 vs 10"
    assert result_text(_cmd()) == "Failure"
    assert result_text(_cmd(dice=(6, 6), ok=True)) == "Success (double six)"


# --- in the App -----------------------------------------------------------------------------

def _failing_seed(root) -> int:
    """A seed whose first roll (empathy 3 against medium) fails."""
    from engine.runtime.dice import Pcg32
    from engine.script.choicecheck import passes
    from tests.runtime.menu_story import launched, load_text
    program = load_text(root, SCRIPT).program
    for seed in range(100):
        interp = launched(program)
        interp.new_game(seed)
        core = Pcg32(interp.core.state, ready=True)
        if not passes(1 + core.below(6), 1 + core.below(6), 3, 10):
            return seed
    raise AssertionError("no seed")


def _roll_screen(s) -> CheckRollScreen | None:
    return next((x for x in s.app.screens if isinstance(x, CheckRollScreen)), None)


def _pick_first(s):
    yield from s.until(lambda: s.app.choices.screen is not None
                       and s.app.choices.screen.past_guard, limit=600)
    s.key(pygame.K_1)


def test_the_roll_shows_lands_and_the_story_goes_on(tmp_path):
    seen: dict[str, object] = {}
    s = story(tmp_path / "g", BODY, "[textbox]\ncps = 0\n", size=(1280, 720))
    main = s.paths.root / "script" / "main.vns"
    main.write_text(HEAD + main.read_text(encoding="utf-8"), encoding="utf-8")

    def script(s):
        yield from s.until_line("The river is loud tonight.")
        s.key(pygame.K_RETURN)
        yield from _pick_first(s)
        yield from s.until(lambda: _roll_screen(s) is not None, limit=60)
        screen = _roll_screen(s)
        start = s.frame
        seen["history"] = s.app.story.interp.history.entries[-1].text
        for _ in range(20):                   # about a third of a second at 60 fps
            yield
        seen["mid"] = screen.frame().landed
        if SHOTS:
            pygame.image.save(s.fb, os.path.join(SHOTS, "dice-roll-midway.png"))
        for _ in range(30):                   # landed, the result showing
            yield
        seen["landed"] = screen.frame().landed
        if SHOTS:
            pygame.image.save(s.fb, os.path.join(SHOTS, "dice-roll-landed.png"))
        yield from s.until(lambda: _roll_screen(s) is None, limit=200)
        seen["frames"] = s.frame - start
        yield from s.until(lambda: s.line_text() in ("...Of the river.", "He looks away."))
        seen["line"] = s.line_text()

    s.play(script)
    assert seen["mid"] is False and seen["landed"] is True
    assert 70 <= seen["frames"] <= 90                     # ROLL_S = 1.3 s at 60 fps
    assert seen["history"].startswith("Empathy check: ")
    assert seen["history"].endswith(seen["line"] == "...Of the river." and "success"
                                    or "failure") or "double" in seen["history"]


def test_a_click_skips_and_reduce_motion_lands_at_once(tmp_path):
    seen: dict[str, object] = {}
    config = "[textbox]\ncps = 0\n[effects]\nreduce = true\n"
    s = story(tmp_path / "g", BODY, config, size=(1280, 720))
    main = s.paths.root / "script" / "main.vns"
    main.write_text(HEAD + main.read_text(encoding="utf-8"), encoding="utf-8")

    def script(s):
        yield from s.until_line("The river is loud tonight.")
        s.key(pygame.K_RETURN)
        yield from _pick_first(s)
        yield from s.until(lambda: _roll_screen(s) is not None, limit=60)
        seen["landed"] = _roll_screen(s).frame().landed
        start = s.frame
        yield
        s.key(pygame.K_RETURN)                            # an advance ends the roll
        yield from s.until(lambda: _roll_screen(s) is None, limit=30)
        seen["frames"] = s.frame - start
        yield from s.until(lambda: s.line_text() in ("...Of the river.", "He looks away."))

    s.play(script)
    assert seen["landed"] is True
    assert seen["frames"] <= 5


def test_a_failed_retry_choice_shows_locked(tmp_path):
    """Picks until a roll fails, then looks at the menu: the retry choice is locked with its
    "Retry once Empathy changes" badge (``[choice] show_locked``)."""
    seen: dict[str, object] = {}
    config = "[textbox]\ncps = 0\n[choice]\nshow_locked = true\n"
    s = story(tmp_path / "g", BODY, config, size=(1280, 720))
    main = s.paths.root / "script" / "main.vns"
    main.write_text(HEAD + main.read_text(encoding="utf-8"), encoding="utf-8")
    s.app.seed = _failing_seed(tmp_path / "find")            # the first roll fails

    def script(s):
        yield from s.until_line("The river is loud tonight.")
        for _ in range(12):
            yield from s.until(lambda: s.app.choices.screen is not None
                               or s.line_text() is not None)
            if s.app.choices.screen is not None:
                cmd = s.app.choices.screen.cmd
                if cmd.choices[0].locked:
                    seen["badge"] = cmd.choices[0].check
                    for _ in range(20):
                        yield
                    if SHOTS:
                        pygame.image.save(s.fb, os.path.join(SHOTS, "retry-choice-locked.png"))
                    return
                yield from _pick_first(s)
                yield from s.until(lambda: s.app.choices.screen is None)
            else:
                text = s.line_text()
                s.key(pygame.K_RETURN)
                yield from s.until(lambda: s.line_text() != text or
                                   s.app.choices.screen is not None)

    s.play(script)
    assert seen["badge"] == "[Empathy · Medium · Retry once Empathy changes]"
