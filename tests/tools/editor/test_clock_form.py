"""F63: Insert ▸ Time offers the three ``clock`` lines, each opening the Time form
(``forms_clock``), which reads and writes them (specs/F63-story-clock/SPEC.md)."""

import pytest

from engine.tools.editor.assist import help_for, insert_menu
from engine.tools.editor.forms import form_for_doc, missing_forms
from engine.tools.editor.forms_clock import FORM
from tests.script.helpers import first_say, parse_text, template


def test_insert_time_offers_the_three_lines():
    groups = dict(insert_menu())
    titles = [doc.title for doc in groups["Time"]]
    assert titles == ["Next part of the day", "Next day", "Go to a day"]
    assert all(form_for_doc(doc) is FORM for doc in groups["Time"])
    assert "clock" not in missing_forms()
    assert help_for("    clock go to day 3").title == "Go to a day"
    assert help_for("clock next").title == "Next part of the day"


@pytest.mark.parametrize("line,values,summary", [
    ("clock next", {"move": "next", "target": "", "part": ""}, "next part of the day"),
    ("clock next day", {"move": "next day", "target": "", "part": ""}, "next day"),
    ("clock go to day 7 Evening", {"move": "go to", "target": "7", "part": "Evening"},
     "go to day 7, Evening"),
    ('clock go to "31 October" "After school"',
     {"move": "go to", "target": "31 October", "part": "After school"},
     "go to 31 October, After school"),
    ("clock go to Night", {"move": "go to", "target": "", "part": "Night"}, "go to Night"),
])
def test_the_form_reads_and_writes(line, values, summary):
    parsed = parse_text(template(S=line))
    node = first_say(parsed)
    assert parsed.errors == [] and FORM.read(node, line) == values
    assert FORM.write(values) == line and FORM.summary(values) == summary
    # a line written another way is a script row
    assert FORM.read(node, line + "  ") == values
    assert FORM.read(first_say(parse_text(template(S="clock go to 7"))), "clock go to 7") is None
