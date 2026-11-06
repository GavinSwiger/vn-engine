"""F65 round 2, the script side: ``lock contact``, ``send`` and ``open`` (positional,
ADR-0010), E448–E450 at parse, the whole-game checks E450 (twice), E451, E452 and W311, the
message shapes ``send`` takes, the trigger core's ``message`` kind, and the story map's reach
(``script/inbox.py``)."""

from types import SimpleNamespace

import pytest

from engine.script.inbox import (ContactDecl, OpenStep, SendStep, collect, message_lines,
                                 message_problem)
from engine.script.loader import LoadOptions, load_story
from engine.script.reach import analyze
from tests.runtime.menu_story import load_text, write_game
from tests.script.helpers import first_say, parse_text, template

TOP = 'lock contact hana "Hana" on pigeon image hana portrait\ndefine invite = "Hi."\n'


def _stmt(row):
    parsed = parse_text(template(S=row))
    return parsed, first_say(parsed)


def _load(tmp_path, body, top=TOP, config=None):
    text = top + "label start:\n" + "".join(f"    {line}\n" for line in body) + '    "End."\n'
    return load_story(write_game(tmp_path, text), LoadOptions(meter_config=config))


@pytest.mark.parametrize("row,message,contact,device", [
    ("send invite from hana", "invite", "hana", None),
    ("send invite from hana on pigeon  # by post", "invite", "hana", "pigeon"),
])
def test_send(row, message, contact, device):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is SendStep
    assert (node.message, node.contact, node.device) == (message, contact, device)
    assert node.identity_key() == ("send", message, contact, device or "")
    assert node.written() == row.split("  #")[0]


@pytest.mark.parametrize("row,look", [("open inbox", None), ("open pigeon", "pigeon")])
def test_open(row, look):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is OpenStep and node.look == look
    assert node.written() == row and node.identity_key() == ("open", look or "inbox")


def test_send_and_open_stay_names_and_speakers():
    # ADR-0010 rule 3: dialogue by characters send and open, and variables of those names.
    for row in ('send "On my way."', 'send happy "On my way."', 'open "Come in."',
                "$ send = 3", "$ open = 'x'", 'open inbox "Hi."'):
        parsed, node = _stmt(row)
        assert type(node) not in (SendStep, OpenStep), row


@pytest.mark.parametrize("row,code,part", [
    ("send", "E448", "needs the message's name"),
    ("send invite", "E448", "needs from and a contact"),
    ("send invite to hana", "E448", "needs from and a contact"),
    ("send invite from", "E448", "found nothing"),
    ('send invite from "Hana"', "E448", "without quotes"),
    ("send invite from hana on pigon", "E448", 'Did you mean "pigeon"?'),
    ("send invite from hana tonight", "E448", 'found "tonight"'),
    ("send invite from hana:", "E448", "no colon"),
    ("open", "E449", "needs inbox or a device look"),
    ("open inbx", "E449", 'Did you mean "inbox"?'),
    ("open inbox now", "E449", 'found "now"'),
    ("open inbox:", "E449", "no colon"),
])
def test_parse_mistakes(row, code, part):
    parsed, _ = _stmt(row)
    assert parsed.codes == [code] and part in parsed.messages[0], parsed.messages


def test_rule_4_names_the_other_reading(tmp_path):
    result = load_text(tmp_path, 'define send = Character("Send")\nlabel start:\n'
                       '    send\n    "Hi."\n')
    (error,) = result.errors
    assert error.code == "E448" and 'send "On my way."' in error.message


def test_contact_declarations(tmp_path):
    result = _load(tmp_path, [], top='lock contact hana "Hana" on pigeon image hana portrait\n'
                   'lock contact ren "Ren"\n')
    assert result.errors == ()
    hana, ren = result.program.contacts
    assert (hana.name, hana.title, hana.device, hana.image) == ("hana", "Hana", "pigeon",
                                                                "hana portrait")
    assert (ren.title, ren.device, ren.image, ren.sid) == ("Ren", None, None, "contact:ren")
    assert type(hana) is ContactDecl
    # image before on works too
    result = _load(tmp_path / "b", [], top='lock contact hana "Hana" image hana on radio\n')
    assert result.errors == () and result.program.contacts[0].device == "radio"


@pytest.mark.parametrize("top,part", [
    ("lock contact hana", "needs the contact's name and the name to show"),
    ('lock contact hana ""', "needs a name to show"),
    ('lock contact hana "{b}Hana{/b}"', "plain text"),
    ('lock contact hana "' + "x" * 41 + '"', "41 characters long"),
    ('lock contact hana "Hana" on pigon', 'Did you mean "pigeon"?'),
    ('lock contact hana "Hana" on radio on phone', "on twice"),
    ('lock contact hana "Hana" in "Friends"', 'but found "in '),
    ('lock contact hana "Hana":', "no colon"),
    ('unlock contact hana', "never unlocked"),
    ('lock contact hana "Hana"\nlock contact hana "H"', "already a contact called hana"),
])
def test_contact_mistakes(tmp_path, top, part):
    result = _load(tmp_path, [], top=top + "\n")
    assert [e.code for e in result.errors] == ["E450"], [e.format() for e in result.errors]
    assert part in result.errors[0].message, result.errors[0].message


def test_lock_contact_in_a_scene(tmp_path):
    result = _load(tmp_path, ["lock contact hana"])
    assert [e.code for e in result.errors] == ["E450"]
    assert "top level of a file" in result.errors[0].message


def test_whole_game_checks(tmp_path):
    assert _load(tmp_path, ["send invite from hana"]).errors == ()
    result = _load(tmp_path / "a", ["send invite from hnaa"])
    assert [e.code for e in result.errors] == ["E451"]
    assert 'Did you mean "hana"?' in result.errors[0].message
    result = _load(tmp_path / "b", ["send invte from hana"])
    assert [e.code for e in result.errors] == ["E452"]
    assert 'Did you mean "invite"?' in result.errors[0].message
    # a default is a message too; its value is checked as a define's
    result = _load(tmp_path / "c", ["send note from hana"],
                   top=TOP + 'default note = ["Hi.", {"me": "Yo."}, {"time": "Day 2"}, '
                             '{"Ren": "Hey."}]\n')
    assert result.errors == ()
    for value, part in (("3", "it is a number"), ("[]", "is empty"),
                        ('[{"ask": "come", "yes": "Yes."}, "Hi."]', "line 1 of message bad "
                                                                     "asks for a reply"),
                        ('["Hi.", ("x",)]', "it is a tuple"),
                        ('["Hi.", ""]', "line 2 of message bad is empty")):
        result = _load(tmp_path / "d" / str(len(part)), ["send bad from hana"],
                       top=TOP + f"define bad = {value}\n")
        assert [e.code for e in result.errors] == ["E452"], value
        assert part in result.errors[0].message and result.errors[0].line == 3
    # a value the check can't read as a literal is checked when it is sent
    assert _load(tmp_path / "e", ["send dyn from hana"],
                 top=TOP + 'define dyn = "Hi " + "there."\n').errors == ()


def test_w311_open_by_a_look_nothing_comes_by(tmp_path):
    config = SimpleNamespace(game=SimpleNamespace(kit=None))
    result = _load(tmp_path, ["send invite from hana", "open pigeon", "open inbox"],
                   config=config)
    assert not [w for w in result.warnings if w.code == "W311"]
    result = _load(tmp_path / "a", ["send invite from hana", "open radio"], config=config)
    (warning,) = [w for w in result.warnings if w.code == "W311"]
    assert "nothing in this game comes by radio" in warning.message
    # send … on radio, or a kit whose device is the radio (Mystery), make it fine
    assert not [w for w in _load(tmp_path / "b", ["send invite from hana on radio",
                                                  "open radio"], config=config).warnings
                if w.code == "W311"]
    mystery = SimpleNamespace(game=SimpleNamespace(kit="mystery"))
    assert not [w for w in _load(tmp_path / "c", ["open radio"],
                                 top='lock contact ren "Ren"\n', config=mystery).warnings
                if w.code == "W311"]
    # no config (tools): no W311
    assert not [w for w in _load(tmp_path / "d", ["open radio"]).warnings if w.code == "W311"]


def test_message_shapes():
    assert message_problem("Hi.") is None and message_problem(["a", {"me": "b"}]) is None
    assert message_problem("  ")[0] == "empty" and message_problem(None)[0] == "kind"
    assert message_problem(["x"] * 201)[0] == "steps"
    assert message_problem([{"a": "b", "c": "d"}]) == ("step", 1, "a dictionary with 2 keys")
    assert message_problem([{" Ren": "x"}])[0] == "line"
    assert message_problem(["x" * 2001])[0] == "line"
    assert message_lines(["Hi.", {"me": "Yo."}, {"time": "Day 2"}, {"Ren": "Hey."}],
                         "Hana") == [("them", "Hana", "Hi."), ("me", "", "Yo."),
                                     ("time", "", "Day 2"), ("them", "Ren", "Hey.")]
    assert message_lines("Hi.", "Hana") == [("them", "Hana", "Hi.")]


def test_each_send_line_is_a_message_trigger_and_reach_treats_them_as_lines(tmp_path):
    result = _load(tmp_path, ["send invite from hana", "open inbox", "jump after"],
                   top=TOP + 'label after:\n    send invite from hana\n    "After."\n')
    program = result.program
    assert program is not None, [e.format() for e in result.errors]
    triggers = list(collect(program))
    assert [t.kind for t in triggers] == ["message", "message"]
    assert len({t.name for t in triggers}) == 2                # each line its own
    first = triggers[0]
    assert (first.live, first.once, first.timing.relative) == (False, True, False)
    assert type(first.payload) is SendStep and first.at is first.payload
    # analyze lists only scenes behind a condition or never reached: after is reached plainly
    assert "after" not in analyze(program, ["start"])
