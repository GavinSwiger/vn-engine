"""F65 trigger core's static check (``script/triggers.py``, ADR-0011): E459 (a name used twice),
E458 (``after`` on a trigger waiting from the start), W316 (can never fit) and W315 (hidden by
an earlier block that always fits), and the message texts."""

import pytest

from engine.core.storyclock import Calendar
from engine.script import triggers as trig
from engine.script.messages import format_message
from engine.script.nodes import Label, PyCode, ScriptFile
from engine.script.triggers import ALWAYS, MAYBE, NEVER, Timing, Trigger, check_triggers
from tests.fakes.banned_words import BANNED_ANY, BANNED_CASED

FILE = ScriptFile("script/main.vns", "main.vns", 0)
CAL = Calendar(parts=("Morning", "After school", "Evening", "Night"), last_day=30,
               months=(("April", 30), ("May", 31)), seasons=("Spring", "Summer"))


def at(line: int) -> Label:
    return Label(file=FILE, line=line, end_line=line, column=1, name=f"l{line}")


def cond(source: str) -> PyCode:
    return PyCode(source=source, line=1, column=0, mode="eval",
                  code=compile(source.strip(), "<script/main.vns>", "eval"))


def t(name: str, when: str | None = None, line: int = 1, kind: str = "event", **kw) -> Trigger:
    return Trigger(kind, name, at(line), cond(when) if when else None, **kw)


def run(triggers, calendar=CAL, picked=("event",)):
    errors = []
    warnings = check_triggers(triggers, errors.append, calendar, picked=picked)
    return [(e.code, e.line, e.args) for e in errors], [(w.code, w.line, str(w)) for w in warnings]


@pytest.mark.parametrize("code", ["E457", "E458", "E459", "W315", "W316"])
def test_messages_format_plainly(code):
    text = format_message(code)
    assert text and len(text) <= 1000
    assert not BANNED_CASED.search(text) and not BANNED_ANY.search(text)
    assert "trigger" not in text                    # authors read about their own kind


def test_w316_forms():
    for form in ("past_last", "after", "part", "never"):
        assert "can never happen" in format_message("W316", (form, "message", "invite", 3, 2))


def test_declarations_refuse_what_no_statement_gives():
    with pytest.raises(ValueError):
        Trigger("Event", "x", at(1))
    with pytest.raises(ValueError):
        Trigger("event", "", at(1))
    with pytest.raises(ValueError):
        Timing(day=0)
    with pytest.raises(ValueError):
        Timing(after_scenes=-1)
    with pytest.raises(ValueError):
        Trigger("event", "x", at(1), PyCode(source="x = 1", line=1, column=0, mode="exec"))
    assert t("hana").id == "event:hana" and not Timing(day=3).relative
    assert Timing(after_days=1).relative


def test_e459_and_e458():
    errors, warnings = run([t("hana", line=3), t("hana", line=9),
                            t("letter", live=True, timing=Timing(after_days=1), line=12),
                            t("mull", kind="thought", timing=Timing(after_scenes=2), line=14),
                            t("hana", kind="place", line=20)])          # another kind: fine
    assert errors == [("E459", 9, ("event", "hana", 3)),
                      ("E458", 12, ("event", "letter", "days", 1)),
                      ("E458", 14, ("thought", "mull", "scenes", 2))]
    assert warnings == []
    assert "there is already an event called hana (line 3)" in format_message(
        "E459", errors[0][2])


@pytest.mark.parametrize("trigger, form", [
    (t("late", timing=Timing(day=31)), "past_last"),
    (t("pigeon", kind="message", live=False, timing=Timing(after_days=30)), "after"),
    (t("dusk", timing=Timing(part=4)), "part"),
    (t("off", "False"), "never"),
    (t("typo", 'clock.part == "Nite" and met'), "never"),
    (t("after_end", "clock.day > 30"), "never"),
    (t("both", "clock.day == 3 and clock.day == 4"), "never"),
    (t("wrong_part", 'clock.part == "Evening"', timing=Timing(part=0)), "never"),
    (t("no_june", 'clock.month == "June"'), "never"),
    (t("sunday", 'clock.weekday == "Sundy"'), "never"),
])
def test_w316_can_never_fit(trigger, form):
    errors, warnings = run([trigger])
    assert errors == [] and len(warnings) == 1 and warnings[0][0] == "W316"
    assert trig.verdict(trigger, CAL)[1][0] == form


@pytest.mark.parametrize("trigger, result", [
    (t("plain"), ALWAYS),
    (t("yes", "True or met"), ALWAYS),
    (t("day7", "clock.day >= 7"), MAYBE),
    (t("weekend", 'clock.weekday in ("Saturday", "Sunday")'), MAYBE),
    (t("from1", "clock.day >= 1"), ALWAYS),
    (t("met", "met and clock.day < 40"), MAYBE),
    (t("evening", 'clock.part == "Evening"', timing=Timing(part=2)), ALWAYS),
    (t("odd", "clock.day % 2 == 1"), MAYBE),
    (t("never_odd", "clock.day % 2 == 7"), NEVER),
    (t("call", "len(names) > 2"), MAYBE),
    (t("spring", 'clock.season == "Spring"'), MAYBE),
])
def test_verdicts(trigger, result):
    assert trig.verdict(trigger, CAL)[0] == result


def test_no_last_day_and_no_calendar():
    open_ended = Calendar()
    assert trig.verdict(t("late", timing=Timing(day=500)), open_ended)[0] == ALWAYS
    assert trig.verdict(t("far", "clock.day == 5000"), open_ended)[0] == MAYBE
    found = trig.verdict(t("before", "clock.day < 1"), open_ended)
    assert found[0] == NEVER and found[1][2] == " from day 1 on"
    assert trig.verdict(t("wk", 'clock.weekday == "Caturday"'), open_ended)[0] == NEVER
    # a game with its own clock: clock.… is unknown; constants are still read
    assert trig.verdict(t("own", "clock.day > 99"), None)[0] == MAYBE
    assert trig.verdict(t("off", "0"), None)[0] == NEVER
    assert trig.verdict(t("dusk", timing=Timing(part=9)), None)[0] == ALWAYS


def test_w315_an_earlier_block_that_always_fits_hides_the_later_ones():
    errors, warnings = run([
        t("chat", "met", once=True, where="library", line=2),
        t("quiet", where="library", line=5),                # always fits, repeats
        t("late", "clock.day > 3", where="library", line=8),  # hidden
        t("park", where="park", line=11),                   # another place: fine
        t("night", where="park", timing=Timing(part=3), line=14),   # hidden by park
    ])
    assert errors == []
    assert [(code, line) for code, line, _ in warnings] == [("W315", 8), ("W315", 14)]
    assert ("event late never happens: event quiet (line 5) comes before it at library"
            in warnings[0][2])


def test_w315_cases_that_leave_later_blocks_reachable():
    _, warnings = run([
        t("once", where="a", once=True), t("after_once", where="a"),
        t("armed", where="b", live=False), t("after_armed", where="b"),
        t("timed", where="c", timing=Timing(part=1)), t("after_timed", where="c"),
        t("maybe", "met", where="d"), t("after_maybe", "other", where="d"),
    ])
    assert warnings == []
    # the same condition and timing: the earlier one wins every time
    _, warnings = run([t("a", "met", where="x"), t("b", " met ", where="x")])
    assert [w[0] for w in warnings] == ["W315"]
    # pushed kinds all fire: no W315
    _, warnings = run([t("a", kind="message"), t("b", kind="message")])
    assert warnings == []
