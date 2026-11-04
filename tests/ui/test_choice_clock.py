"""F51 step P1, the countdown's pure counter (``ui/builtin/choice_clock.py``; ``04`` §7.3,
07 I-2): AC-F51-17 (the number table, and the number shown whenever the bar is)."""

import pytest

from engine.core.settings_schema import TIMING_NORMAL, TIMING_OFF, TIMING_SLOWER
from engine.ui.builtin.choice_clock import ChoiceClock


def _clock_with_left(seconds: float, left: float) -> ChoiceClock:
    clock = ChoiceClock(seconds)
    clock.tick(seconds - left, TIMING_NORMAL, counting=True)
    return clock


# --- AC-F51-17 — the number table --------------------------------------------------------------

@pytest.mark.parametrize("left,number", [(5.0, 5), (4.01, 5), (4.0, 4), (0.2, 1)])
def test_ac17_number_is_whole_seconds_left_rounded_up(left, number):
    clock = _clock_with_left(5.0, left)
    assert clock.left(TIMING_NORMAL) == pytest.approx(left)
    assert clock.shown(TIMING_NORMAL) == number
    assert clock.fraction(TIMING_NORMAL) == pytest.approx(left / 5.0)
    for level in (TIMING_NORMAL, TIMING_SLOWER, TIMING_OFF):   # the number with the bar
        assert (clock.shown(level) is None) == (clock.fraction(level) is None)
    assert clock.shown(TIMING_OFF) is None and clock.fraction(TIMING_OFF) is None
    untimed = ChoiceClock(None)
    assert untimed.shown(TIMING_NORMAL) is None and untimed.fraction(TIMING_NORMAL) is None
    assert not untimed.tick(600.0, TIMING_NORMAL, counting=True)
