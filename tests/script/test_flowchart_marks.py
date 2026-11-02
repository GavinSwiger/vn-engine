"""F20 s1 — the load checks of ``flowchart`` lines (F20 ``06-acceptance.md`` AC-F20-03;
``04-technical.md`` §6.2; ``07`` A4).

Each placement row of AC-F20-03 is a ``feature = "F20"`` row of
``tests/fixtures/F02/messages/cases.toml`` (``test_messages.py`` runs them through
``load_story``, with the exact text and line). Here: the rows are all there, and the marks
``iter_attach_marks`` returns, with F14's ``ATTACH_SKIPS`` seam in both orders; and (F20 s2)
every row gives the same outcome with ``[flowchart] enabled = false``."""

import pytest

from engine.script import rollback
from engine.script.diagnostics import DiagnosticSink
from engine.script.flowchart import FlowMark, iter_attach_marks, skips_attach_fixed
from engine.script.flowgraph import FlowOptions
from engine.script.menu import Menu
from engine.script.nodes import Chapter, Label
from engine.script.routes import Ending
from engine.script.statements import scoped_registry
from tests.script.helpers import parse_text, template_l
from tests.script import message_cases
from tests.script.test_messages import CASES


def _marks(text: str) -> tuple[list, list[str]]:
    parsed = parse_text(text)
    assert parsed.errors == [], parsed.messages
    sink = DiagnosticSink()
    walk = iter_attach_marks(parsed.nodes, sink, {"start", "stall", "river", "shrine",
                                                  "promise"}, lambda name: None)
    try:
        while True:
            next(walk)
    except StopIteration as done:
        found = done.value
    fixed = list(rollback.iter_attach_fixed(parsed.nodes, sink))
    assert fixed is not None
    return found, [d.code for d in sink.kept()]


def _outcome(case) -> tuple:
    outcome = message_cases.run_case(case)
    return ([e.format() for e in outcome.errors], [w.format() for w in outcome.warnings],
            outcome.error_count)


def test_ac_f20_03_load_checks_and_marks():
    # Every AC-F20-03 outcome has its cases.toml rows (E261 both forms, E262 every form,
    # E264, E204's flowchart line, E174, and the rows that load).
    ids = {c.id for c in CASES if c.ac == "AC-F20-03"}
    for row in ("F20-03-E261-top", "F20-03-E261-first", "F20-03-E262-next",
                "F20-03-E262-chapter-ending", "F20-03-E262-two", "F20-03-E204", "F20-03-E264",
                "F20-03-E174", "F20-03-clean", "F20-03-clean-r"):
        assert row in ids or any(i.startswith(row + "-") for i in ids), row
    # Template L's marks: two scenes, the M21 menu, and the hidden True End.
    found, codes = _marks(template_l())
    assert codes == []
    kinds = [(type(target).__name__, getattr(target, "name", None), mark)
             for target, mark in found]
    assert kinds == [
        ("Label", "stall", FlowMark("Daichi's Stall", False, False, False, 11)),
        ("Menu", None, FlowMark("Where should we watch the lanterns?", False, False, False, 20)),
        ("Label", "promise", FlowMark("The Promise", True, True, False, 37)),
        ("Ending", "true", FlowMark(None, True, False, False, 39)),
    ]
    assert isinstance(found[1][0], Menu) and found[1][0].line == 21
    # Chapter flags and omit.
    found, codes = _marks(template_l(replace={6: "    flowchart hidden no jump"},
                                     S="flowchart omit"))
    assert codes == []
    assert [(type(t), m.hidden, m.no_jump, m.omit) for t, m in found[:3]] == [
        (Chapter, True, True, False), (Label, False, False, False), (Menu, False, False, True)]
    # F14's seam, both orders: the menu is marked and fixed.
    for s in ('flowchart "T"⏎[4]rollback fixed', 'rollback fixed⏎[4]flowchart "T"'):
        found, codes = _marks(template_l(S=s))
        assert codes == [], s
        menu = next(t for t, m in found if m.title == "T")
        assert isinstance(menu, Menu) and menu.fixed and menu.line == 14, s
    # rollback fixed / flowchart forget / menu: is F14's E204 (a flowchart line); forget alone.
    found, codes = _marks(template_l(S="rollback fixed⏎[4]flowchart forget"))
    assert codes == ["E204"]
    # The seam is registered once, and scoped_registry() restores it.
    assert rollback.ATTACH_SKIPS.count(skips_attach_fixed) == 1
    with scoped_registry():
        rollback.ATTACH_SKIPS.clear()
    assert rollback.ATTACH_SKIPS.count(skips_attach_fixed) == 1
    # Endings take hidden only; a forget naming a label needs it (E264 with the labels).
    assert all(not isinstance(t, Ending) or m.title is None for t, m in found)
    found, codes = _marks(template_l(S="flowchart forget nowhere"))
    assert codes == ["E264"] and not any(isinstance(t, Label) and t.name == "nowhere"
                                         for t, _ in found)
    # F20 s2 (SR-F20-13): every row's outcome is the same with [flowchart] enabled = false.
    rows = [c for c in CASES if c.ac == "AC-F20-03"]
    on = [_outcome(c) for c in rows]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(message_cases, "FlowOptions", lambda: FlowOptions(enabled=False))
        off = [_outcome(c) for c in rows]
    assert off == on
