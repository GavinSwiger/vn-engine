"""F51 step W3 in the App: AC-F51-21 (skip ends at a timed menu, whose countdown then starts
full; auto never picks, the timeout does, and auto goes on after). App A
(``tests/fakes/text_app.py``) through F15's ``Probe`` (``tests/app/test_skip_auto_app.py``),
so the real ``ChoiceController``, ``TimerPanelView`` and ``SkipAuto`` run.

Delta from the AC's numbers: the menu is 3 s and auto is watched for 2 s of it (the AC's
60 s menu watched for 30 s is the same rule at 20× the frames).
"""

import pygame
import pytest

from engine.runtime.commands import Choose
from engine.ui.builtin.choice_screen import ChoiceScreen
from tests.app.test_skip_auto_app import INSTANT, SKIP_ALL, Probe, says, story
from tests.runtime.menu_story import K

pytestmark = pytest.mark.display

TIMED = ('    menu time 3:\n        "Stay":\n            "Stayed."\n'
         '        "..." timeout:\n            "Silent."\n')
AFTER = "".join(f'    "After {i}."\n' for i in range(4))
BERRY = (0xA0, 0x28, 0x60)                # the bar's fill: choice.marker.fill_color


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()


def _screen(s) -> ChoiceScreen | None:
    return next((x for x in s.app.screens if isinstance(x, ChoiceScreen)), None)


def test_ac21_skip_ends_at_a_timed_menu_and_auto_lets_the_timeout_pick(tmp_path):
    seen: dict[str, object] = {}
    s = story(tmp_path / "skip", says(10) + TIMED + AFTER, SKIP_ALL, size=(1280, 720))
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def skip_script(s):
            yield from p.ready()
            s.key(pygame.K_TAB)
            yield from s.until(lambda: _screen(s) is not None and _screen(s).started,
                               limit=600)
            screen = _screen(s)
            seen["skip"] = (p.sa.skip, screen.clock.shown(0), screen.clock.used < 0.02)
            for _ in range(10):                      # past the 120 ms fade
                yield
            x, y, w, h = screen.layout.header_rect
            seen["bar"] = s.px(round(x + 20), round(y + h / 2))
            for _ in range(50):
                yield
            seen["one second"] = screen.clock.shown(0)

        s.play(skip_script)
    assert seen["skip"] == ("off", 3, True)
    assert all(abs(a - b) <= 2 for a, b in zip(seen["bar"], BERRY)), seen["bar"]
    assert seen["one second"] == 2

    fast = "[auto]\ndelay = 0.2\nper_char = 0\n"
    s = story(tmp_path / "auto", says(3) + TIMED + AFTER, INSTANT + fast)
    with pytest.MonkeyPatch.context() as mp:
        p = Probe(s, mp)

        def auto_script(s):
            yield from p.ready()
            chosen: list[object] = []
            real = s.app.choices.post
            mp.setattr(s.app.choices, "post", lambda e: (chosen.append(e), real(e)))
            s.key(pygame.K_a)
            yield from s.until(lambda: s.app.choices.screen is not None, limit=400)
            n = len(s.posted)
            for _ in range(120):                     # 2 s at the menu: auto posts nothing
                yield
            seen["waiting"] = (len(s.posted) - n, len(chosen), p.sa.auto)
            yield from s.until_line("Silent.")
            seen["picked"] = [e for e in chosen if isinstance(e, Choose)]
            yield from s.until_line("After 1.")
            seen["after"] = p.sa.auto

        s.play(auto_script)
    assert seen["waiting"] == (0, 0, True)
    assert [e.choice for e in seen["picked"]] == [K("...")]
    assert seen["after"] is True
