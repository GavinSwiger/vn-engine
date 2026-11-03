"""F47 Say text toolbar model (``engine/tools/editor/texttools.py``; AC-F47-35)."""

from engine.script.tag_docs import TAG_DOCS, tag_names
from engine.script.texttags import STYLE_TAGS
from engine.tools.editor import texttools as t
from tests.fakes.username import no_real_username  # noqa: F401  (name guard)

TEXT = "I saw the lantern move."          # "lantern" is [10, 17)

# button key -> (value, the text after it, selection after)
WRAPPED = {
    "bold": (None, "I saw the {b}lantern{/b} move.", (13, 20)),
    "italic": (None, "I saw the {i}lantern{/i} move.", (13, 20)),
    "colour": ("#9a1c14", "I saw the {color=#9a1c14}lantern{/color} move.", (25, 32)),
    "pause": ("0.6", "I saw the lantern{pause=0.6} move.", (28, 28)),
    "speed": ("instant", "I saw the {speed=instant}lantern{/speed} move.", (25, 32)),
    "shake": (None, "I saw the {shake}lantern{/shake} move.", (17, 24)),
    "wave": ("large", "I saw the {wave=large}lantern{/wave} move.", (22, 29)),
    "glitch": ("small", "I saw the {glitch=small}lantern{/glitch} move.", (24, 31)),
    "player_name": (None, "I saw the lantern{username} move.", (27, 27)),
    "variable": ("player_name", "I saw the lantern{var=player_name} move.", (34, 34)),
    "size": ("1.5", "I saw the {size=1.5}lantern{/size} move.", (20, 27)),
    "next": (None, "I saw the lantern move.{next}", (29, 29)),
}


def test_ac_f47_35_text_toolbar_wraps_selection_in_each_tag():
    # A button for every tag in tag_docs (the toolbar's ten, then More), and each one
    # wraps the selection (or, for a mark, goes in at the caret) so the engine reads it.
    assert {b.tag for b in t.BUTTONS} == set(tag_names())
    assert [b.label for b in t.BUTTONS if not b.more] == [
        "Bold", "Italic", "Colour", "Pause", "Speed", "Shake", "Wave", "Glitch",
        "Player name", "Variable"]
    assert set(WRAPPED) == {b.key for b in t.BUTTONS}
    for row in TAG_DOCS:
        b = t.button_for_tag(row.name)
        assert b.doc is row and b.pair is row.closes
        value, text, selection = WRAPPED[b.key]
        edit = t.apply(TEXT, 10, 17, b.tag, value)
        assert (edit.text, (edit.start, edit.end), edit.problem) == (text, selection, None), \
            b.key
        if b.tag in STYLE_TAGS:
            assert [a.name for a in t.active_tags(edit.text, edit.start)] == [b.tag]
            assert t.strip_tags(edit.text).text == TEXT
            assert t.toggle(edit.text, edit.start, edit.end, b.tag).text == TEXT  # off again
        assert t.preview(edit.text) == TEXT.replace(
            "lantern", "lantern[player name]" if b.tag == "username" else
            "lantern[player_name]" if b.tag == "var" else "lantern"), b.key

    # Nothing selected: the pair goes in empty with the caret between.
    assert t.apply("Hi", 2, 2, "b") == t.TextEdit("Hi{b}{/b}", 5, 5)
    # A selection never splits a tag or {{, and grows to hold whole pairs (no E166).
    assert t.apply("a {b}bc{/b} d", 0, 6, "i").text == "{i}a {b}bc{/b}{/i} d"
    assert t.apply("a {color=#112233}bc{/color} d", 5, 12, "i").text == \
        "a {i}{color=#112233}bc{/color}{/i} d"
    assert t.apply("x{{y", 2, 4, "b").text == "x{b}{{y{/b}"
    # {next} goes at the end, once; a bad value or nesting comes back with the engine's words.
    assert t.apply("hi{next}", 0, 0, "next").text == "hi{next}"
    assert t.apply(TEXT, 10, 17, "var").problem
    assert t.apply("{shake}abc{/shake}", 8, 9, "wave").problem
    assert t.check_value("color", "9a1c14") and t.check_value("pause", "40")
    assert t.check_value("shake", "huge") and t.check_value("speed", "instant") is None

    # Toggle: off when it covers the selection, split a run, change a value.
    assert t.toggle("{b}abc{/b}", 4, 5, "b").text == "{b}a{/b}b{b}c{/b}"
    assert t.toggle("{b}abc{/b}", 0, 10, "b").text == "abc"
    assert t.toggle("{color=#111111}abc{/color}", 15, 18, "color", "#222222").text == \
        "{color=#222222}abc{/color}"
    stuck = t.toggle("{b}a{i}bc{/i}{/b}", 7, 8, "b")
    assert stuck.text == "{b}a{i}bc{/i}{/b}" and stuck.problem

    # Clear formatting: whole pairs and timing marks only; words and unknown tags stay.
    assert t.strip_tags("I {b}saw{/b} it {pause=0.6}{wave}now{/wave} {var=x} {foo}{{b}").text \
        == "I saw it now {var=x} {foo}{{b}"
    assert t.strip_tags("{b}abc{/b} {i}de{/i}", 3, 6) == t.TextEdit("abc {i}de{/i}", 0, 3)
    assert t.strip_tags("{b}abc{/b} {i}de{/i}", 0, 5).text == "{b}abc{/b} {i}de{/i}"
    assert t.preview('{b}Hi{/b}, \\"{username=nick}\\" {{b}\\nok {pause}{next}') == \
        'Hi, "[nick]" {b} ok '
