"""F63 round 2: ``show clock`` / ``hide clock`` (positional, ADR-0010 rule 2): the clock form
only with nothing else on the line; the picture forms stay (``script/clockshow.py``)."""

import pytest

from engine.script.clockshow import ClockShow
from engine.script.reach import analyze
from engine.script.stage import Hide, Show
from engine.tools.editor.assist import help_for
from engine.tools.editor.forms import form_for_doc
from engine.tools.editor.forms_clock import HIDE_CLOCK, SHOW_CLOCK
from tests.runtime.menu_story import load_text
from tests.script.helpers import first_say, parse_text, template


def _stmt(row):
    parsed = parse_text(template(S=row))
    return parsed, first_say(parsed)


@pytest.mark.parametrize("row,shown", [("show clock", True), ("hide clock  # away", False)])
def test_the_clock_forms(row, shown):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is ClockShow and node.shown is shown
    assert node.identity_key() == ("clock", "show" if shown else "hide")
    assert node.written() == row.split("  ")[0]


@pytest.mark.parametrize("row,kind", [("show clock at left", Show), ("show clock happy", Show),
                                      ("hide clock with dissolve", Hide),
                                      ("show clocks", Show), ("hide clock_face", Hide)])
def test_anything_more_is_a_picture(row, kind):
    parsed, node = _stmt(row)
    assert parsed.errors == [] and type(node) is kind


def test_reach_and_studio_treat_it_as_a_line(tmp_path):
    result = load_text(tmp_path, 'label start:\n    show clock\n    "One."\n    hide clock\n'
                       '    jump end\nlabel end:\n    "Two."\n')
    assert result.errors == () and result.program is not None
    analyze(result.program, ["start"])                        # a plain line: no trouble
    assert help_for("    show clock").title == "Show the clock"
    assert help_for("hide clock").title == "Hide the clock"
    _, node = _stmt("show clock")
    assert SHOW_CLOCK.read(node, "show clock") == {} and SHOW_CLOCK.write({}) == "show clock"
    assert HIDE_CLOCK.read(node, "show clock") is None
    docs = [d for d in (help_for("show clock"), help_for("hide clock"))]
    assert [form_for_doc(d) for d in docs] == [SHOW_CLOCK, HIDE_CLOCK]
