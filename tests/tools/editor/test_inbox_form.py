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


@pytest.mark.parametrize("form,line,values,summary", [
    (SEND, "send invite from hana", {"message": "invite", "contact": "hana", "look": ""},
     "invite from hana"),
    (SEND, "send late from ren on radio", {"message": "late", "contact": "ren",
                                            "look": "radio"}, "late from ren, by radio"),
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
