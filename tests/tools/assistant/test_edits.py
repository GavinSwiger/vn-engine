"""F48 step S4: ``propose_edit`` (AC-F48-13 to 16; 04 §7.1, §7.4; SEC-F48-02, SEC-F48-10;
01 §4.4, §6.3). AC-F48-18's code-bearing rows are S5's (test_code_bearing.py)."""

import pytest

from engine.tools.assistant import edits
from engine.tools.assistant.edits import (
    CHANGES_SHAPE, CHECK_UNKNOWN, EMPTY_OLD, NEW_TEXT_TOO_LONG, NO_CHANGE, OVERLAP,
    TEXT_TOO_LONG, TOO_MANY_FILES, numbered_diff, problem_delta, rebase)
from engine.tools.assistant.refs import NOT_EDITABLE, NOT_TEXT, UNKNOWN_ARG, ToolError
from engine.tools.assistant.tools import MODE_MCP, MODE_PANE, ToolBox
from engine.tools.assistant.workspace import REASON_TIMEOUT
from engine.tools.editor.checker import CheckState
from engine.tools.editor.scriptedit import LineEdit
from tests.tools.assistant.assist_games import FakeRunner, disk, item, pane, result, studio, tree
from tests.tools.assistant.test_tools import Writer

CH2 = "script/ch2.vns"


def change(file: object, old: object, new: object) -> dict:
    return {"file": file, "old_text": old, "new_text": new}


def call(box: ToolBox, *changes: dict, summary: object = "Change it") -> str:
    return box.call("propose_edit", {"summary": summary, "changes": list(changes)}).text


# --- AC-F48-13: matches, widening, new files; id and diff -------------------------------------

def test_ac13_propose_matches_widens_and_creates_with_an_id_and_diff(tmp_path):
    game = studio(tmp_path)
    writer = Writer()
    box = ToolBox(disk(game), MODE_MCP, writer=writer)
    assert box.call("propose_edit", {"summary": "s", "changes": [
        change(CH2, "jump nowhere", "x")]}).text == "That text isn't in script/ch2.vns."
    assert call(box, change(CH2, "The", "A")) == (
        "That text is in script/ch2.vns 2 times; include more lines around it.")
    # Mid-line text widens to its whole line.
    shown = call(box, change(CH2, "stay", "wait")).split("\n")
    assert shown[:3] == ["Proposed change: Change it", "id: p1", "script/ch2.vns, +1 −1:"]
    assert shown[3:11] == ['  3         "Go to the river":', "  4             jump river",
                           '  5         "Stay":', '- 6             "You stay."',
                           '+ 6             "You wait."', "  7     return",
                           "  8 label bridge:", '  9     "The bridge."']
    assert shown[11:] == ["No new problems.", edits.APPLY_HINT]
    plan = writer.kept[0].files[0].plan
    assert plan.edits == (LineEdit(6, 6, ('            "You wait."',)),)
    assert plan.guards and plan.guards[0][0] == "club"
    # A new file: an unlisted script ref with an empty old_text.
    made = call(box, change("script/ch3.vns", "", 'label three:\n    "Three."\n'))
    assert made.split("\n")[1:5] == ["id: p2", "script/ch3.vns (new file), +2 −0:",
                                     "+1 label three:", '+2     "Three."']
    assert writer.kept[1].new_refs == ("script/ch3.vns",)
    assert not (game / "script" / "ch3.vns").exists()


# --- AC-F48-14: a change that doesn't parse ---------------------------------------------------

def test_ac14_a_change_that_doesnt_parse_is_refused_with_the_error_and_no_id(tmp_path):
    game = studio(tmp_path)
    writer = Writer()
    box = ToolBox(disk(game), MODE_MCP, writer=writer)
    refused = box.call("propose_edit", {"summary": "s", "changes": [
        change(CH2, '"The river."', '"The river.')]})
    assert refused.is_error and "id:" not in refused.text
    assert refused.text == ('This change doesn\'t parse: script/ch2.vns, line 11: this quote is '
                            'never closed. Add " at the end of the text.')
    new = box.call("propose_edit", {"summary": "s", "changes": [
        change("script/ch3.vns", "", "label three\n    jump\n")]})
    assert new.is_error and new.text.startswith("This change doesn't parse: script/ch3.vns")
    assert writer.kept == []


# --- AC-F48-15: the overlay check finds added and fixed problems; disk untouched --------------

def test_ac15_the_overlay_check_reports_added_and_fixed_problems_on_disk_unchanged(tmp_path):
    game = studio(tmp_path)
    (game / "script" / "ch2.vns").write_text(
        (game / "script" / "ch2.vns").read_text(encoding="utf-8").replace("jump river",
                                                                          "jump rivr"),
        encoding="utf-8")
    before = tree(game)
    box = ToolBox(disk(game, "real"), MODE_MCP, writer=Writer())
    shown = call(box, change(CH2, "jump rivr", "jump river"),
                 change("script/main.vns", "    jump bridge", "    jump bridg")).split("\n")
    assert "This change adds 1 problem(s):" in shown
    assert ('E43 script/main.vns line 8: there is no label named "bridg". Did you mean '
            '"bridge"?') in shown
    assert "Fixes 1 problem(s)." in shown
    assert tree(game) == before
    # A check that can't finish keeps the proposal, with 01 §6.3's text.
    slow = ToolBox(disk(game, FakeRunner(state=CheckState.TIMEOUT)), MODE_MCP, writer=Writer())
    kept = call(slow, change(CH2, "jump rivr", "jump river")).split("\n")
    assert kept[1] == "id: p1"
    assert CHECK_UNKNOWN.format(reason=REASON_TIMEOUT + ".") in kept


# --- AC-F48-16: targets and bounds ------------------------------------------------------------

def test_ac16_targets_and_bounds_are_refused(tmp_path):
    game = studio(tmp_path)
    workspace = disk(game)
    big = "x" * (64 * 1024 + 1)
    half = "    " + "y" * (40 * 1024)
    cases = [
        ({"summary": "s", "changes": [change("config.toml", "[game]", "[x]")]}, NOT_EDITABLE),
        ({"summary": "s", "changes": [change("images/a.png", "", "x")]}, NOT_EDITABLE),
        ({"summary": "s", "changes": [change("minigames/a.vns", "", "x")]}, NOT_EDITABLE),
        ({"summary": "s", "changes": [change(".studio/a.vns", "", "x")]}, NOT_EDITABLE),
        ({"summary": "s", "changes": [{**change(CH2, "", ""), "delete": True}]},
         UNKNOWN_ARG.format(key="delete")),
        ({"summary": "s", "changes": [{**change(CH2, "x", "y"), "rename": "a.vns"}]},
         UNKNOWN_ARG.format(key="rename")),
        ({"summary": "s", "changes": [change(f"script/n{i}.vns", "", f"label n{i}:")
                                      for i in range(9)]}, TOO_MANY_FILES),
        ({"summary": "s", "changes": [change(CH2, "jump river", half),
                                      change("script/main.vns", "jump bridge", half)]},
         NEW_TEXT_TOO_LONG),
        ({"summary": "s", "changes": [change(CH2, "x", "y")] * 65}, CHANGES_SHAPE),
        ({"summary": "s", "changes": []}, CHANGES_SHAPE),
        ({"summary": "s", "changes": {"file": CH2}}, CHANGES_SHAPE),
        ({"summary": "s", "changes": [change(CH2, big, "y")]},
         TEXT_TOO_LONG.format(key="old_text")),
        ({"summary": "s", "changes": [change(CH2, "y", big)]},
         TEXT_TOO_LONG.format(key="new_text")),
        ({"summary": "s", "changes": [change(CH2, "y", "\ud800")]},
         edits.TEXT_NOT_SAVABLE.format(key="new_text")),
        ({"summary": "s", "changes": [change(CH2, "jump river", "jump bridge"),
                                      change(CH2, "            jump", "            call")]},
         OVERLAP.format(file=CH2)),
        ({"summary": "s", "changes": [change(CH2, "", "label more:")]},
         EMPTY_OLD.format(file=CH2)),
        ({"summary": "x" * 201, "changes": [change(CH2, "jump river", "jump bridge")]},
         NOT_TEXT.format(key="summary", limit=200)),
        ({"summary": "s", "changes": [change(CH2, "jump river", "jump river")]}, NO_CHANGE),
        ({"summary": "s", "changes": [change("script/../x.vns", "", "label x:")]},
         "`x.vns` can't be used as a file name"),
        ({"summary": "s", "changes": [change(["script/ch2.vns"], "x", "y")]},
         "a list isn't something the assistant can read."),
    ]
    for args, text in cases:
        with pytest.raises(ToolError) as refused:
            edits.propose(workspace, args, check=False)
        assert refused.value.text.startswith(text), (args, refused.value.text)
    assert (workspace.checks.runner.requests == [])        # nothing was checked


# --- Rebase, diff and delta (§7.4; used by the pane's Apply) ----------------------------------

def test_rebase_follows_a_moved_scene_and_refuses_a_changed_one(tmp_path):
    game = studio(tmp_path)
    text = (game / "script" / "ch2.vns").read_text(encoding="utf-8").rstrip("\n")
    proposal = edits.propose(pane(game, {CH2: text}),
                             {"summary": "s", "changes": [change(CH2, "The river.",
                                                                 "The wide river.")]},
                             check=False)
    file = proposal.files[0]
    assert rebase(file, text) is file.plan
    moved = rebase(file, "label intro:\n    \"Hi.\"\n" + text)
    assert moved is not None and moved.edits == (LineEdit(13, 13, ('    "The wide river."',)),)
    assert rebase(file, text.replace("The river.", "The stream.")) is None
    assert rebase(file, text.replace("label river:", "label river:\n    pause 1")) is None


def test_numbered_diff_and_problem_delta():
    old = [f"line {n}" for n in range(1, 21)]
    rows, shown = numbered_diff(old, [LineEdit(2, 2, ("two",)), LineEdit(18, 17, ("new",))])
    assert rows[:4] == ["  1 line 1", "- 2 line 2", "+ 2 two", "  3 line 3"]
    assert rows[4:] == ["  4 line 4", "  5 line 5", "…", " 15 line 15", " 16 line 16",
                        " 17 line 17", "+18 new", " 19 line 18", " 20 line 19", " 21 line 20"]
    assert shown == [(1, 5), (15, 20)]
    base = [item("E43", CH2, 9, "a"), item("E43", CH2, 3, "b")]
    proposed = [item("E43", CH2, 10, "a"), item("E10", CH2, 2, "c")]
    added, fixed = problem_delta(base, proposed, {CH2: edits.line_map([LineEdit(2, 3, ("x", "y", "z"))])})
    assert [p.code for p in added] == ["E10"] and [p.text for p in fixed] == ["b"]


def test_pane_proposals_are_cards_from_the_plan(tmp_path):
    game = studio(tmp_path)
    cards = []
    box = ToolBox(pane(game, runner=FakeRunner(result())), MODE_PANE, on_proposal=cards.append)
    shown = call(box, change(CH2, "$x", "y"))
    assert shown == "That text isn't in script/ch2.vns." and cards == []
    shown = call(box, change(CH2, '    "The river."', '    "The river."\n    $ seen = True'))
    assert "id:" not in shown and shown.endswith(edits.CARD_SHOWN)
    assert edits.NO_CODE_RUN in shown and edits.CODE_NOTICE in shown
    assert len(cards) == 1 and cards[0].code and not cards[0].launch
