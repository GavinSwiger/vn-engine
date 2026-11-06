"""F65 round 3, the script side: ``send … after 1 day`` / ``after 2 parts`` / ``after 2 scenes``
and ``ask "…"``
on the line (E448's new forms), a message that ends with an ask (the phone chat's shapes),
the whole-game checks E455, W312–W314 and the trigger core's W316 for delays, and the story
map's reach reading ``inbox.reply`` like a variable (``script/inbox.py``, ``reach.py``)."""

from types import SimpleNamespace

import pytest

from engine.script.inbox import (SendStep, ask_options, collect, message_ask, message_lines,
                                 message_problem)
from engine.script.reach import analyze
from tests.script.helpers import first_say, parse_text, template
from tests.script.test_inbox_script import _load

TOP = ('lock contact hana "Hana" on pigeon\n'
       'define invite = ["Meet me?", {"ask": "come", "yes": "I will.", "no": "No."}]\n'
       'define late = "Running late!"\n')
CONFIG = SimpleNamespace(theme=SimpleNamespace(kit=None),
                         calendar=SimpleNamespace(last_day=5, parts=None))


def _stmt(row):
    parsed = parse_text(template(S=row))
    return parsed, first_say(parsed)


@pytest.mark.parametrize("row,days,scenes,parts,replies", [
    ("send invite from hana after 1 day", 1, None, None, ()),
    ("send invite from hana on letters after 3 days", 3, None, None, ()),
    ("send invite from hana after 2 scenes", None, 2, None, ()),
    ("send invite from hana after 1 scene", None, 1, None, ()),
    ("send invite from hana after 1 part", None, None, 1, ()),
    ("send invite from hana on letters after 2 parts", None, None, 2, ()),
    ('send late from hana ask "On my way." "Start without me."', None, None, None,
     ("On my way.", "Start without me.")),
    ('send late from hana after 2 days ask "Yes"', 2, None, None, ("Yes",)),
    ('send late from hana after 3 parts ask "Yes"', None, None, 3, ("Yes",)),
])
def test_send_after_and_ask(row, days, scenes, parts, replies):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is SendStep
    assert (node.after_days, node.after_scenes, node.after_parts, node.replies) == (
        days, scenes, parts, replies)
    assert node.written() == row
    # The delay and the replies keep the line's sid (and a saved waiting message).
    assert node.identity_key() == ("send", node.message, "hana", node.device or "")


def test_after_parts_in_any_order():
    parsed, node = _stmt('send late from hana ask "Yes" after 2 parts on letters')
    assert parsed.errors == [] and (node.after_parts, node.device, node.replies) == (
        2, "letters", ("Yes",))
    assert node.written() == 'send late from hana on letters after 2 parts ask "Yes"'


@pytest.mark.parametrize("row,part", [
    ("send invite from hana after", "needs a number and days, parts or scenes"),
    ("send invite from hana after 2", "needs a number and days, parts or scenes"),
    ("send invite from hana after two days", "needs a number and days, parts or scenes"),
    ("send invite from hana after 2 weeks", "needs a number and days, parts or scenes"),
    ("send invite from hana after 0 days", "whole number from 1 to"),
    ("send invite from hana after 0 parts", "whole number from 1 to"),
    ("send invite from hana after 10001 parts", "whole number from 1 to 10,000"),
    ("send invite from hana after 1 part after 1 day", "has after twice"),
    ("send invite from hana after 1 day after 2 days", "has after twice"),
    ("send invite from hana ask", "found none"),
    ('send invite from hana ask "A" "B" "C" "D" "E"', "found 5"),
    ('send invite from hana ask "A" "A"', "two are the same"),
    ('send invite from hana ask " A"', "starts or ends with a space"),
    ("send invite from hana soon", "found \"soon\""),
])
def test_after_and_ask_mistakes(row, part):
    parsed, _node = _stmt(row)
    assert [e.code for e in parsed.errors] == ["E448"], row
    assert part in parsed.errors[0].message, parsed.errors[0].message


def test_message_asks():
    assert message_problem(["Tea?", {"ask": ["Yes", "No"]}]) is None
    assert message_ask(["Tea?", {"ask": ["Yes", "No"]}]) == (("Yes", "Yes"), ("No", "No"))
    named = ["Tea?", {"ask": "tea", "y": "Yes", "n": "No", "ignore": True}]
    assert message_problem(named) is None and message_ask(named) == (("y", "Yes"), ("n", "No"))
    assert message_lines(named, "Hana") == [("them", "Hana", "Tea?")]
    assert message_ask("Tea?") == () and message_ask(["Tea?"]) == ()
    for value, form in (([{"ask": ["Yes"]}], "ask_only"),
                        (["Hi", {"ask": ["Yes"]}, "Bye"], "ask_last"),
                        (["Hi", {"ask": []}], "ask"),
                        (["Hi", {"ask": ["A", "B", "C", "D", "E"]}], "ask"),
                        (["Hi", {"ask": "x", "y": ["Yes", "More"]}], "ask"),
                        (["Hi", {"ask": "x y", "y": "Yes"}], "ask"),
                        (["Hi", {"ask": ["A"], "other": 1}], "ask"),
                        (["Hi", {"ask": 3}], "ask")):
        found = message_problem(value)
        assert found is not None and found[0] == form, (value, found)
    assert "send the answer as another message" in ask_options(
        {"ask": "x", "y": ["Yes", "More"]})[1]


def test_delays_are_trigger_timing():
    parsed = parse_text(template(S="send invite from hana after 2 days"))
    program = SimpleNamespace(iter_statements=lambda: iter([first_say(parsed)]))
    (trigger,) = collect(program)
    assert trigger.timing.after_days == 2 and not trigger.live and trigger.once
    parsed = parse_text(template(S="send invite from hana after 3 parts"))
    program = SimpleNamespace(iter_statements=lambda: iter([first_say(parsed)]))
    (trigger,) = collect(program)
    assert trigger.timing.after_parts == 3 and trigger.timing.relative


def test_whole_game_checks(tmp_path):
    # E455: replies on the line and in the message.
    result = _load(tmp_path / "a", ['send invite from hana ask "Yes"'], top=TOP)
    assert [e.code for e in result.errors] == ["E455"]
    assert "asks for a reply too" in result.errors[0].message
    # W312: after days with no clock line.
    result = _load(tmp_path / "b", ["send late from hana after 2 days"], top=TOP)
    assert result.errors == ()
    (w,) = [w for w in result.warnings if w.code == "W312"]
    assert "never arrives" in w.message
    assert not [w for w in _load(tmp_path / "c", ["send late from hana after 2 scenes"],
                                 top=TOP).warnings if w.code == "W312"]
    # W312 for parts: the same, naming clock next.
    result = _load(tmp_path / "b2", ["send late from hana after 1 part"], top=TOP)
    (w,) = [w for w in result.warnings if w.code == "W312"]
    assert "after 1 part waits" in w.message and "clock next line" in w.message
    # W316 (the trigger core): past [calendar] last_day, counting from the first day.
    result = _load(tmp_path / "d", ["send late from hana after 9 days", "clock next day"],
                   top=TOP, config=CONFIG)
    (w,) = [w for w in result.warnings if w.code == "W316"]
    assert "message" in w.message and "last_day (5)" in w.message
    assert not [w for w in _load(tmp_path / "e", ["send late from hana after 2 days",
                                                  "clock next day"], top=TOP,
                                 config=CONFIG).warnings if w.code in ("W316", "W312")]
    # W316 for parts (the default calendar's four parts): 24 parts is day 7 at the soonest.
    result = _load(tmp_path / "f", ["send late from hana after 24 parts", "clock next"],
                   top=TOP, config=CONFIG)
    (w,) = [w for w in result.warnings if w.code == "W316"]
    assert "after 24 parts of the day" in w.message and "last_day (5)" in w.message
    assert not [w for w in _load(tmp_path / "g", ["send late from hana after 16 parts",
                                                  "clock next"], top=TOP,
                                 config=CONFIG).warnings if w.code in ("W316", "W312")]


def test_reply_reads_are_checked(tmp_path):
    body = ["send invite from hana", 'if inbox.reply("invte") == "yes":', '    "A."',
            'if inbox.reply("invite") == "maybe":', '    "B."',
            'if inbox.reply("invite") in ("yes", "no", ""):', '    "C."']
    result = _load(tmp_path / "a", body, top=TOP)
    assert result.errors == ()
    (w313,) = [w for w in result.warnings if w.code == "W313"]
    assert 'Did you mean "invite"?' in w313.message
    (w314,) = [w for w in result.warnings if w.code == "W314"]
    assert '"maybe"' in w314.message and '"no" or "yes"' in w314.message
    # A line's replies are its texts; a message sent without replies is W313.
    body = ['send late from hana ask "Coming"', 'if inbox.reply("late") == "Coming":', '    "D."']
    assert not [w for w in _load(tmp_path / "b", body, top=TOP).warnings
                if w.code in ("W313", "W314")]
    body = ["send late from hana", 'if inbox.reply("late"):', '    "E."']
    assert [w.code for w in _load(tmp_path / "c", body, top=TOP).warnings
            if w.code in ("W313", "W314")] == ["W313"]
    # A game with its own inbox variable reads that instead: no warning.
    body = ['if inbox.reply("x"):', '    "F."']
    result = _load(tmp_path / "d", body, top=TOP + "define inbox = None\n")
    assert not [w for w in result.warnings if w.code == "W313"]


def test_reach_reads_a_reply_like_a_variable(tmp_path):
    top = TOP + 'label bridge:\n    "Bridge."\nlabel home:\n    "Home."\nlabel never:\n    "N."\n'
    body = ["send invite from hana", '"Wait."',
            'if inbox.reply("invite") == "yes":', "    jump bridge",
            'if inbox.reply("invite") == "maybe":', "    jump never",
            "jump home"]
    result = _load(tmp_path, body, top=top)
    reach = analyze(result.program, ["start"])
    bridge, never = reach["bridge"], reach["never"]
    assert bridge.blocked is None and bridge.ways[0].needs == ('inbox.reply("invite") == "yes"',)
    assert never.blocked is not None
    assert any("send invite from hana" in row.text for row in bridge.setters)
