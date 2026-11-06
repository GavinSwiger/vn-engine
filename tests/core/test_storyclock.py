"""F63 story clock: ``[calendar]`` in config.toml and the calendar arithmetic of
``engine/core/storyclock.py`` (specs/F63-story-clock/SPEC.md)."""

from engine.core.storyclock import (DEFAULT_PARTS, Calendar, CalendarProblem, MONTHS,
                                    calendar_of)


def test_no_calendar_and_no_kit_gives_the_defaults(load):
    calendar, problems = calendar_of(load("").config)
    assert problems == [] and calendar.parts == DEFAULT_PARTS and calendar.start_day == 1
    assert (calendar.weekday(1), calendar.weekday(8), calendar.date(9)) == \
        ("Monday", "Monday", "Day 9")
    assert calendar_of(None)[0] == Calendar()


def test_the_cards_example(load):
    result = load('[calendar]\nstart = "Monday 1 April"\n'
                  'parts = ["Morning", "After school", "Evening", "Night"]\nlast_day = 30\n')
    assert result.errors == [] and result.warnings == []
    calendar, problems = calendar_of(result.config)
    assert problems == [] and calendar.parts[1] == "After school"
    assert calendar.months == MONTHS                      # the start names a month
    assert calendar.date(1) == "Monday 1 April" and calendar.date(30) == "Tuesday 30 April"
    assert calendar.date(31) == "Wednesday 1 May" and calendar.last_day == 30
    assert calendar.find_date("31 October") == 214 and calendar.find_date("October 31") == 214
    assert calendar.find_date("1 April", on_or_after=2) == 366     # next year's
    assert calendar.find_date("31 April") is None and calendar.find_date("day 12") == 12
    assert calendar.part_index("after SCHOOL") == 1 and calendar.part_index("Noon") is None


def test_kit_wording_seasons_and_config_wins(load):
    cozy = load('[theme]\nkit = "cozy"\n').config
    calendar, _ = calendar_of(cozy)
    assert calendar.date(1) == "Spring, day 1" and calendar.date(29) == "Summer, day 1"
    assert calendar.find_date("Autumn 3") == 59
    own = load('[theme]\nkit = "horror"\n\n[calendar]\nparts = ["Day", "Night"]\n'
               'day_text = "Night {day} ({weekday})"\nstart = 3\n').config
    calendar, problems = calendar_of(own)
    assert problems == [] and calendar.parts == ("Day", "Night") and calendar.start_day == 3
    assert calendar.date(3) == "Night 3 (Wednesday)"


def test_custom_months_and_problems(load):
    result = load('[calendar]\nmonths = ["Thaw", "Bloom"]\nmonth_days = [10, 20]\n'
                  'start = "Bloom 5"\nweekdays = ["Moonday", "Fireday", "Restday"]\n')
    calendar, problems = calendar_of(result.config)
    assert problems == [] and calendar.date(1) == "Moonday 5 Bloom"
    assert calendar.date(17) == "Fireday 1 Thaw"
    _, problems = calendar_of(load('[calendar]\nstart = "Fooday 9"\n'
                                   'day_text = "{season} {day}"\n').config)
    assert problems == [CalendarProblem("start", "Fooday 9"), CalendarProblem("field", "season")]


def test_bad_values_are_config_errors(load):
    for text in ('parts = []', 'parts = ["A", "a"]', 'start = 0', 'month_days = 500',
                 'parts = ["' + "x" * 31 + '"]', 'last_day = "soon"'):
        result = load(f"[calendar]\n{text}\n")
        assert len(result.errors) == 1, text
