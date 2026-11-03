"""F41 P5: Database ▸ Clean up's model (``engine/tools/editor/cleanup.py``; F41 04 §7.5).

AC-F41-20 (unit: states and texts; W2's pane shows them as given): not checked, story with
errors, lint not run, empty after a full check, empty while waiting for a full check, a
list (groups in §6.1 order, rows with kind line, place, warning text, actions and their
Database entry found by name), and over the 1,000-row cap."""

from dataclasses import dataclass

import pytest

from engine.tools.editor import cleanup as cu
from engine.tools.editor import dbmodel as db
from engine.tools.editor.checker import CheckItem, CheckResult, NameEntry

LINT_KINDS = tuple(cu.KINDS)
MAIN = "script/main.vns"


def _result(names: dict, *, problems: tuple = (), totals: dict | None = None) -> CheckResult:
    sent = {kind: tuple(NameEntry(*row) for row in rows) for kind, rows in names.items()}
    return CheckResult(problems, len(problems), sent, (), True, 0, 0.0,
                       totals if totals is not None else {k: len(v) for k, v in sent.items()})


def _all(**rows) -> dict:
    """Every lint kind (empty unless given), plus a non-lint kind."""
    return {"label": [("start", MAIN, 1)], **{kind: [] for kind in LINT_KINDS}, **rows}


ERROR = CheckItem("error", "E43", "load", "no label.", MAIN, 3)
WARNING = CheckItem("warning", "W02", "load", "not included.", "script/x.vns", None)
LIST = _all(
    unused_picture=[("hana sad_blink1", "images/hana/sad_blink1.png", None),
                    ("bg old_park", "images/bg/old_park.png", None)],
    unreached=[("old_ending", "script/end.vns", 4)],
    unused_variable=[("lantern_count", MAIN, 12)],
    unused_sound=[("music/old_theme.ogg", "audio/music/old_theme.ogg", None)],
    unused_meter=[("trust", MAIN, 9)],
    unused_define=[("max_tries", MAIN, 5)],
    unused_position=[("far_left", "config.toml", None)],
    unused_transition=[("slow_fade", MAIN, 3)],
    unused_character=[("kenji", MAIN, 2)])
WAITING = {k: v for k, v in LIST.items() if k != "unused_character"}
MANY = _all(unused_picture=[(f"bg p{n:04}", f"images/bg/p{n:04}.png", None)
                            for n in range(1_200)],
            unused_variable=[("v", MAIN, 1)])

STATES = {
    "not checked": (None, cu.STATE_NOT_CHECKED, "Not checked yet"),
    "story with errors": (_result(LIST, problems=(ERROR,)), cu.STATE_ERRORS,
                          "Fix the errors in Problems first. Clean up needs a story that "
                          "loads."),
    "lint didn't run": (_result({"label": [("start", MAIN, 1)]}), cu.STATE_ERRORS,
                        "Fix the errors in Problems first. Clean up needs a story that "
                        "loads."),
    "empty": (_result(_all(), problems=(WARNING,)), cu.STATE_EMPTY,
              "Nothing to clean up. Everything in your game is used."),
    "empty, waiting": (_result({k: v for k, v in _all().items() if k != "unused_character"}),
                       cu.STATE_EMPTY, "Nothing to clean up. Everything in your game is used."),
    "list": (_result(LIST, problems=(WARNING,)), cu.STATE_LIST, None),
    "list, waiting": (_result(WAITING), cu.STATE_LIST, None),
    "over the cap": (_result(MANY, totals={"unused_picture": 1_499, "unused_variable": 1}),
                     cu.STATE_LIST, None),
}


@dataclass(frozen=True)
class _Row:                          # a Database row: its entry carries the name
    iid: str
    entry: db.Entry


def _entry(kind: str, name: str) -> _Row:
    return _Row(f"x:{name}", db.Entry(kind, name, name, None, False, 0))


@pytest.mark.parametrize("state", list(STATES))
def test_ac_f41_20_states_and_texts(state):
    """AC-F41-20: each state's text, the waiting line only without ``unused_character``,
    the header, the groups and rows of a list, and the cap line."""
    result, expected_state, message = STATES[state]
    view = cu.cleanup_view(result)
    assert (view.state, view.message) == (expected_state, message)
    waiting = state.endswith("waiting")
    assert view.waiting == ("Characters are listed after your first Play or Check now."
                            if waiting else None)
    if view.state != cu.STATE_LIST:
        assert (view.groups, view.count, view.header) == ((), 0, None)
        return
    assert view.header == ("These aren't used in your story. Delete what you don't need "
                           "before you build.")
    assert cu.TITLE == "Clean up"
    if state == "over the cap":
        assert view.over_cap == "Showing 1,000 of 1,500."
        assert [(g.heading, g.count, len(g.items)) for g in view.groups] == [
            ("PICTURES", 1_499, 1_000), ("VARIABLES", 1, 0)]
        assert view.count == 1_500
        return
    assert view.over_cap is None
    shown = [(g.heading, g.count, [(i.kind_line, i.name, i.place) for i in g.items])
             for g in view.groups]
    characters = [("CHARACTERS", 1, [("Character", "kenji", "main.vns:2")])]
    assert shown == [
        ("SCENES NOT REACHED", 1, [("Scene", "old_ending", "end.vns:4")]),
        *(characters if state == "list" else []),
        ("PICTURES", 2, [("Picture", "bg old_park", "old_park.png"),
                         ("Picture", "hana sad_blink1", "sad_blink1.png")]),
        ("SOUNDS", 1, [("Sound", "music/old_theme.ogg", "old_theme.ogg")]),
        ("VARIABLES", 1, [("Variable", "lantern_count", "main.vns:12")]),
        ("OTHER", 4, [("Define", "max_tries", "main.vns:5"),
                      ("Transition", "slow_fade", "main.vns:3"),
                      ("Position", "far_left", "config.toml"),
                      ("Meter", "trust", "main.vns:9")]),
    ]
    assert view.count == (10 if state == "list" else 9)
    by_name = {item.name: item for item in view.items}
    assert {name: [(a.action, a.text) for a in item.actions]
            for name, item in by_name.items() if name in (
                "old_ending", "bg old_park", "max_tries", "far_left")} == {
        "old_ending": [("map", "Show on map"), ("delete", "Delete…")],
        "bg old_park": [("open", "Open in Pictures"), ("delete", "Delete…")],
        "max_tries": [("editor", "Open in Editor"), ("delete", "Delete…")],
        "far_left": [("open", "Open in Positions"), ("delete", "Delete…")],
    }
    assert [by_name[n].text for n in ("old_ending", "hana sad_blink1", "trust")] == [
        'nothing leads to label "old_ending" from start (no jump, call or choice), so '
        "players never see it. Add a jump to it, or delete it if you don't need it.",
        'picture "hana sad_blink1" isn\'t shown anywhere in the story.',
        'meter "trust" is defined but never used.']
    assert view.item("u:unused_sound:music/old_theme.ogg") is by_name["music/old_theme.ogg"]
    # Each row finds its Database entry by name in its category.
    pictures = [_entry(db.BACKGROUND, "bg park"), _entry(db.BACKGROUND, "BG Old_Park")]
    assert cu.target_entry(by_name["bg old_park"], pictures) is pictures[1]
    sounds = [_entry(db.SOUND, "music/old_theme.ogg")]
    assert cu.target_entry(by_name["music/old_theme.ogg"], sounds) is sounds[0]
    assert cu.target_entry(by_name["lantern_count"], pictures) is None
    assert cu.target_entry(by_name["old_ending"], pictures) is None
    assert [i.name for i in cu.search(view, "OLD")] == [
        "old_ending", "bg old_park", "music/old_theme.ogg"]
