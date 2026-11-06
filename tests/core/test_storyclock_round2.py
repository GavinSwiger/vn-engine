"""F63 round 2: ``[calendar] day_card`` and ``place`` (config > kit > defaults), the kits' clock
corner, and ``Calendar.moment`` for save slots (specs/F63-story-clock/SPEC.md)."""

from engine.core.kits import KITS
from engine.core.storyclock import DEFAULT_CLOCK_PLACE, Calendar, calendar_of


def test_day_card_and_place_from_config_then_kit(load):
    calendar, _ = calendar_of(load("").config)
    assert calendar.day_card is True and calendar.place == DEFAULT_CLOCK_PLACE == "top_right"
    calendar, _ = calendar_of(load('[theme]\nkit = "romance"\n').config)
    assert calendar.place == "top_left"                   # the corner its meters don't use
    result = load('[theme]\nkit = "romance"\n\n[calendar]\nday_card = false\n'
                  'place = "bottom_right"\n')
    assert result.errors == []
    calendar, _ = calendar_of(result.config)
    assert calendar.day_card is False and calendar.place == "bottom_right"
    for text in ('day_card = "no"', 'place = "middle"'):
        assert len(load(f"[calendar]\n{text}\n").errors) == 1, text


def test_every_kit_puts_the_clock_away_from_its_meters():
    for kit in KITS.values():
        assert kit.clock is not None and kit.clock.place != kit.meters.place, kit.id


def test_moment_words():
    assert Calendar().moment(4, 2) == "Day 4, Evening"
    assert Calendar().moment(4, 99) == "Day 4, Night"      # a part past the last: the last
    cozy = Calendar(seasons=("Spring",), day_text="{season}, day {season_day}")
    assert cozy.moment(4, 0) == "Spring, day 4 · Morning"
