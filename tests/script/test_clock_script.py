"""F63 story clock, the script side: ``clock next`` / ``next day`` / ``go to`` (positional,
ADR-0010), E428–E430 at parse, the whole-game checks E431–E434 and W300–W303, and the story
map's reach (specs/F63-story-clock/SPEC.md)."""

from types import SimpleNamespace

import pytest

from engine.script.clock import ClockStep
from engine.script.loader import LoadOptions, load_story
from engine.script.reach import analyze
from engine.script.stage import Show
from tests.runtime.menu_story import load_text, write_game
from tests.script.helpers import first_say, parse_text, template


def _stmt(row):
    parsed = parse_text(template(S=row))
    return parsed, first_say(parsed)


@pytest.mark.parametrize("row,action,day,text,part", [
    ("clock next", "next", None, None, None),
    ("clock next day  # tomorrow", "next_day", None, None, None),
    ("clock go to day 7", "go", 7, None, None),
    ("clock go to 7 Evening", "go", 7, None, "Evening"),
    ('clock go to "31 October"', "go", None, "31 October", None),
    ('clock go to "Spring 4" "After school"', "go", None, "Spring 4", "After school"),
    ("clock go to Night", "go", None, None, "Night"),
])
def test_the_three_statements(row, action, day, text, part):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is ClockStep
    assert (node.action, node.day, node.text, node.part) == (action, day, text, part)
    assert node.identity_key()[:2] == ("clock", action)


def test_clock_stays_a_name_and_a_speaker():
    # ADR-0010 rule 3: dialogue by a character clock, and clock as a variable or picture
    for row in ('clock "Tick."', 'clock happy "Tick."', 'clock next "Tick."',
                "$ clock = 3", "show clock at left"):
        parsed, node = _stmt(row)
        assert parsed.errors == [] and type(node) is not ClockStep, row
    assert type(_stmt("show clock at left")[1]) is Show     # round 2: bare show clock isn't


@pytest.mark.parametrize("row,code,part", [
    ("clock nxt", "E428", 'Did you mean "next"?'),
    ("clock", "E428", "found nothing"),
    ("clock next:", "E428", "no colon"),
    ("clock next days", "E429", 'found "days"'),
    ("clock next day 2", "E429", "clock next day takes nothing more"),
    ("clock go Night", "E430", "needs to"),
    ("clock go to", "E430", "found nothing"),
    ("clock go to day soon", "E430", "needs a day number"),
    ("clock go to day 0", "E430", "out of range"),
    ("clock go to day 3 Evening late", "E430", 'found "late"'),
])
def test_parse_mistakes(row, code, part):
    parsed, _ = _stmt(row)
    assert parsed.codes == [code] and part in parsed.messages[0], parsed.messages


def test_rule_4_names_the_other_reading(tmp_path):
    result = load_text(tmp_path, 'define clock = Character("Clock")\nlabel start:\n'
                       '    clock happy\n    "Hi."\n')
    (error,) = result.errors
    assert error.code == "E428" and 'clock "Tick."' in error.message


def _config(kit=None, **calendar):
    defaults = dict(start=None, parts=None, weekdays=None, months=None, month_days=None,
                    seasons=None, season_days=None, last_day=None, day_text=None)
    return SimpleNamespace(game=SimpleNamespace(kit=kit),
                           calendar=SimpleNamespace(**(defaults | calendar)))


def _load(tmp_path, body, config=None, top=""):
    text = top + "label start:\n" + "".join(f"    {line}\n" for line in body) + '    "End."\n'
    return load_story(write_game(tmp_path, text), LoadOptions(meter_config=config))


def test_names_and_dates_are_checked_against_the_calendar(tmp_path):
    card = _config(start="Monday 1 April", parts=("Morning", "After school", "Night"),
                   last_day=30)
    assert _load(tmp_path, ['clock go to "31 October" Night', 'clock go to "After school"',
                            "if clock.days_left() == 3:", '    "Soon."'], card).errors == ()
    result = _load(tmp_path / "a", ["clock go to Nite"], card)
    assert [e.code for e in result.errors] == ["E432"]
    assert 'Did you mean "Night"?' in result.errors[0].message
    result = _load(tmp_path / "b", ['clock go to "31 Octobre"'], card)
    assert [e.code for e in result.errors] == ["E431"]
    # no config (tools): names can't be checked
    assert _load(tmp_path / "c", ["clock go to Nite"]).errors == ()
    # W303: past the last day
    result = _load(tmp_path / "d", ["clock go to day 40"], card)
    assert [w.code for w in result.warnings if w.code.startswith("W30")] == ["W303"]


def test_values_in_conditions(tmp_path):
    card = _config(parts=("Morning", "Night"))
    ok = ['if clock.part == "Night" and clock.weekday != "Sunday":', '    "Late."',
          '$ when = clock.date', '"{var=clock.date}, {var=clock.part}."',
          'if clock.days_left(30) > 0 or clock.days_left("day 9") > 0:', '    "Soon."']
    result = _load(tmp_path, ok, card)
    assert result.errors == () and not [w for w in result.warnings if w.code == "W300"]
    result = _load(tmp_path / "a", ['if clock.part == "night":', '    "Late."'], card)
    (warning,) = [w for w in result.warnings if w.code == "W300"]
    assert 'Did you mean "Night"?' in warning.message and warning.line == 2
    for body, code, part in (
            (['if clock.dya == 1:', '    "A."'], "E434", 'Did you mean "day"?'),
            (["$ clock.day = 3"], "E434", "can't change clock.day"),
            (['if clock.days_left() == 1:', '    "A."'], "E433", "last_day"),
            (['if clock.days_left("31 Octobre") == 1:', '    "A."'], "E433", "can't read"),
            (['if clock.days_left(1, 2) == 1:', '    "A."'], "E433", "one day at most")):
        result = _load(tmp_path / code / part[:4].strip(), body, card)
        assert [e.code for e in result.errors] == [code] and part in result.errors[0].message


def test_w301_and_w302(tmp_path):
    result = _load(tmp_path, [], _config(start="Fooday 9", day_text="{season} {day}"))
    assert [w.code for w in result.warnings if w.code == "W301"] == ["W301", "W301"]
    result = _load(tmp_path / "own", ['if clock.day == 1:', '    "A."'], _config(),
                   top="default clock = 0\n")
    assert result.errors == () and [w.code for w in result.warnings] == ["W302"]


def test_reach_treats_clock_conditions_as_unknown(tmp_path):
    program = load_text(tmp_path, 'label start:\n    clock next day\n'
                        '    if clock.day == 7:\n        jump festival\n    "Not yet."\n'
                        'label festival:\n    "Lanterns."\n').program
    assert program is not None
    found = analyze(program, ["start"])["festival"]
    assert found.blocked is None and found.ways[0].possible
    assert found.ways[0].needs == ("clock.day == 7",)
