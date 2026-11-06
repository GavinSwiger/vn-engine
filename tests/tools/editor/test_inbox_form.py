"""F65 round 2: Insert ▸ Messages offers Send and Open, each opening its form
(``forms_inbox``), which reads and writes the line; the check child lists contacts and
messages for Send's pickers."""

import pytest

from engine.tools.editor.assist import help_for, insert_menu
from engine.tools.editor.forms import form_for_doc, missing_forms
from engine.tools.editor.forms_inbox import OPEN, SEND
from tests.script.helpers import first_say, parse_text, template


def test_insert_messages_offers_send_and_open():
    groups = dict(insert_menu())
    docs = groups["Messages"]
    assert [doc.title for doc in docs] == ["Send a message", "Open the Inbox"]
    assert [form_for_doc(doc) for doc in docs] == [SEND, OPEN]
    assert "send" not in missing_forms() and "open" not in missing_forms()
    assert help_for("    send invite from hana").title == "Send a message"
    assert help_for("open pigeon").title == "Open the Inbox"
    # The contact declaration is a Declarations doc (Database ▸ Contacts is round 3).
    assert "Contact" in [doc.title for doc in groups["Declarations"]]
    assert [f.name_kind for f in SEND.fields[:2]] == ["message", "contact"]


_NOW = {"arrives": "", "after": "", "replies": ""}


@pytest.mark.parametrize("form,line,values,summary", [
    (SEND, "send invite from hana", {"message": "invite", "contact": "hana", "look": "",
                                     **_NOW}, "invite from hana"),
    (SEND, "send late from ren on radio", {"message": "late", "contact": "ren",
                                            "look": "radio", **_NOW}, "late from ren, by radio"),
    # F65 round 3: Arrives and Replies.
    (SEND, "send invite from hana after 1 day",
     {"message": "invite", "contact": "hana", "look": "", "arrives": "days", "after": "1",
      "replies": ""}, "invite from hana, after 1 day"),
    (SEND, 'send late from ren on radio after 2 scenes ask "On my way." "Start without me."',
     {"message": "late", "contact": "ren", "look": "radio", "arrives": "scenes", "after": "2",
      "replies": "On my way. / Start without me."},
     "late from ren, by radio, after 2 scenes, replies: On my way. / Start without me."),
    # After some parts of the day.
    (SEND, "send late from ren after 2 parts",
     {"message": "late", "contact": "ren", "look": "", "arrives": "parts", "after": "2",
      "replies": ""}, "late from ren, after 2 parts"),
    (OPEN, "open inbox", {"at": "inbox"}, "the Inbox"),
    (OPEN, "open pigeon", {"at": "pigeon"}, "the Inbox, newest by pigeon"),
])
def test_the_forms_read_and_write(form, line, values, summary):
    parsed = parse_text(template(S=line))
    node = first_say(parsed)
    assert parsed.errors == [] and form.read(node, line) == values
    assert form.write(values) == line and form.summary(values) == summary
    other = OPEN if form is SEND else SEND
    assert other.read(node, line) is None


def test_the_check_child_lists_contacts_and_messages(tmp_path):
    from engine.tools.check import NAME_SOURCES
    from tests.runtime.menu_story import load_text
    program = load_text(tmp_path, 'lock contact hana "Hana"\ndefine invite = ["Hi.", '
                        '{"me": "Yo."}]\ndefine count = 3\ndefault note = "Hey."\n'
                        'label start:\n    send invite from hana\n    "End."\n').program
    assert program is not None
    ctx = type("Ctx", (), {"program": program})()
    assert NAME_SOURCES["contact"](ctx) == [("hana", "script/main.vns", 1)]
    assert [row[0] for row in NAME_SOURCES["message"](ctx)] == ["invite", "note"]


def test_syntax_colours_send_and_open_only_in_their_place():
    from engine.tools.editor.syntax import color_spans
    assert color_spans("    send invite from hana")[0] == (4, 8, "keyword")
    assert color_spans("    open pigeon")[0] == (4, 8, "keyword")
    assert color_spans('    send "On my way."')[0] == (4, 8, "speaker")      # ADR-0010
    assert color_spans('    open "Come in."')[0] == (4, 8, "speaker")


def test_send_form_round_3_fields():
    from engine.tools.editor.fieldhints import form_hint
    from engine.tools.editor.forms_inbox import replies_of
    keys = [f.key for f in SEND.fields]
    assert keys[3:] == ["arrives", "after", "replies"]
    assert all(form_hint("send", key) for key in keys)
    assert [f.shown_for(o) for f in SEND.fields[3:4] for o in f.options] == [
        "Now", "After some days", "After some parts of the day", "After some scenes"]
    # Forgiving input: a missing or bad count is 1, "Now" drops the count, replies are
    # trimmed, deduplicated, at most four, with quotes made plain.
    base = {"message": "invite", "contact": "hana", "look": ""}
    assert SEND.write({**base, "arrives": "days", "after": ""}) == \
        "send invite from hana after 1 day"
    assert SEND.write({**base, "arrives": "scenes", "after": "0"}) == \
        "send invite from hana after 1 scene"
    assert SEND.write({**base, "arrives": "", "after": "3"}) == "send invite from hana"
    assert SEND.write({**base, "arrives": "parts", "after": "x"}) == (
        "send invite from hana after 1 part")
    assert replies_of(' Yes /No/ yes/Yes / say "hi" /a/b ') == ("Yes", "No", "yes", "say 'hi'")
    line = SEND.write({**base, "replies": "Yes/No"})
    assert line == 'send invite from hana ask "Yes" "No"'
    parsed = parse_text(template(S=line))
    assert parsed.errors == [] and SEND.read(first_say(parsed), line)["replies"] == "Yes / No"


def test_parts_are_offered_only_with_calendar_parts():
    from types import SimpleNamespace

    from engine.tools.check import NAME_SOURCES
    from engine.tools.editor.forms_inbox import arrives_field
    arrives = SEND.fields[3]
    without = arrives_field(arrives, {}, "")
    assert without.options == ("", "days", "scenes")
    assert without.shown == ("Now", "After some days", "After some scenes")
    assert arrives_field(arrives, {"day_part": ["Day", "Night"]}, "") is arrives
    assert arrives_field(arrives, {}, "parts") is arrives       # a line that already says so
    assert arrives_field(SEND.fields[0], {}, "") is SEND.fields[0]
    # The check child lists [calendar] parts when it names two or more.
    names = NAME_SOURCES["day_part"]
    ctx = SimpleNamespace(config=SimpleNamespace(calendar=SimpleNamespace(
        parts=("Morning", "Evening"))))
    assert [row[0] for row in names(ctx)] == ["Morning", "Evening"]
    for parts in (None, ("Day",)):
        ctx = SimpleNamespace(config=SimpleNamespace(calendar=SimpleNamespace(parts=parts)))
        assert names(ctx) is None


@pytest.mark.tk
def test_the_send_dialog_offers_parts_only_with_calendar_parts():
    tk = pytest.importorskip("tkinter")
    from engine.tools.editor import formdialogs as fd
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        for names, value, offered in (({}, "", 3), ({"day_part": ["Day", "Night"]}, "", 4),
                                      ({}, "parts", 4)):
            start = fd.new_values(SEND) | {"arrives": value}
            dialog = fd.FormDialog(root, SEND, start, names=names)
            assert len(dialog.widgets["arrives"].cget("values")) == offered, (names, value)
            dialog.dialog.destroy()
    finally:
        root.destroy()
