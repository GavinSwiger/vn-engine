"""F64 present at a menu in Studio (specs/F64-items/SPEC-present.md): the Choice form's
"Accept an item" reads, writes and patches a menu's present: option; Events rows show it."""

from dataclasses import replace

import engine.script  # noqa: F401  registers every statement
from engine.tools.editor import forms, formpresent
from engine.tools.editor.formpresent import (ACCEPT_ITEM, ANY_OTHER_ITEM, PRESENT_ITEM_TEXT,
                                             PRESENT_REMOVE_TEXT, PRESENT_TWICE_TEXT,
                                             PresentValues, ReactionItem)
from engine.tools.editor.forms import (ChoiceItem, ChoiceValues, choice_lines, choice_patches,
                                       choice_problems, read_choice, rows)
from engine.tools.editor.scenes import parse_chunk

SCENE = '''label t:
    menu:
        hana "What's that?"
        "Nothing.":
            $ pass
        present if bag:  # the bag
            red_lantern:
                jump lantern
            brass_key:
                hana "A key?"
                $ door = True
            else:
                $ pass
    hana "End."
'''
PLAIN = '''label t:
    menu:
        "Go":
            jump hall
    "End."
'''


def _read(text: str = SCENE):
    read = parse_chunk("script/t.vns", text, positions=frozenset())
    assert read is not None and read.error is None, read
    return read, text.split("\n")[:-1]


def _apply(lines, patches):
    assert not isinstance(patches, str), patches
    out = list(lines)
    for patch in sorted(patches, key=lambda p: p.first, reverse=True):
        out[patch.first - 1:patch.last] = patch.lines
    return out


def _reparse(after):
    again = parse_chunk("script/t.vns", "\n".join(after) + "\n", positions=frozenset())
    assert again is not None and again.error is None, again
    return again


def test_read_and_events_rows():
    read, lines = _read()
    values = read_choice(read, 0)
    present = values.present
    assert present.condition == "bag"
    assert present.reactions == (ReactionItem("red_lantern", "lantern", False, 0),
                                 ReactionItem("brass_key", None, True, 1))
    assert present.other == ReactionItem("", None, False, 2)
    assert [c.text for c in values.choices] == ["Nothing."]
    texts = [(row.depth, row.word, row.summary, row.kind) for row in rows(read, lines)]
    at = texts.index((1, ACCEPT_ITEM, "if bag is yes", "stmt"))
    assert texts[at + 1] == (2, "Shows red_lantern", "", "header")
    assert (2, "Shows brass_key", "", "header") in texts
    assert (2, ANY_OTHER_ITEM, "", "header") in texts
    # Every Events row of the option opens the Choice form on its menu.
    option_rows = [row for row in rows(read, lines) if row.word in (
        ACCEPT_ITEM, "Shows red_lantern", ANY_OTHER_ITEM)]
    assert all(row.form == forms.CHOICE_FORM for row in option_rows)
    assert all(read_choice(read, row.stmt) == values for row in option_rows)


def test_a_new_menu_with_accept_an_item():
    new = ChoiceValues(choices=(ChoiceItem("Leave", goes="hall"),), present=PresentValues(
        "", (ReactionItem("red_lantern", "lantern"),), ReactionItem()))
    assert choice_lines(new, "    ", "    ") == [
        "    menu:", '        "Leave":', "            jump hall", "        present:",
        "            red_lantern:", "                jump lantern", "            else:",
        "                $ pass"]


def test_adding_it_to_a_menu_writes_it_after_the_choices():
    read, lines = _read(PLAIN)
    old = read_choice(read, 0)
    assert old.present is None
    new = replace(old, present=PresentValues("seen", (ReactionItem("coin", "hall"),),
                                             ReactionItem()))
    after = _apply(lines, choice_patches(read, 0, lines, new))
    assert after[4:9] == ["        present if seen:", "            coin:",
                          "                jump hall", "            else:",
                          "                $ pass"]
    assert after[-1] == '    "End."'
    _reparse(after)


def test_changes_keep_comments_and_lines_of_their_own():
    read, lines = _read()
    old = read_choice(read, 0)
    red, brass = old.present.reactions
    new = replace(old, present=replace(old.present, condition="", reactions=(
        brass, replace(red, item="coin", goes=None), ReactionItem("map", "hall")),
        other=replace(old.present.other, goes="hall")))
    after = _apply(lines, choice_patches(read, 0, lines, new))
    assert after[5:] == [
        "        present:  # the bag",
        "            brass_key:", '                hana "A key?"', "                $ door = True",
        "            coin:", "                $ pass",
        "            map:", "                jump hall",
        "            else:", "                jump hall",
        '    hana "End."']
    again = _reparse(after)
    assert read_choice(again, 0).present.reactions[0].in_text


def test_editing_the_choices_keeps_the_option():
    read, lines = _read()
    old = read_choice(read, 0)
    new = replace(old, choices=(replace(old.choices[0], goes="hall"),
                                ChoiceItem("Run", goes="hall")))
    after = _apply(lines, choice_patches(read, 0, lines, new))
    assert after[3:8] == ['        "Nothing.":', "            jump hall", '        "Run":',
                          "            jump hall", "        present if bag:  # the bag"]
    assert read_choice(_reparse(after), 0).present == old.present


def test_unchanged_writes_nothing_and_problems():
    read, lines = _read()
    old = read_choice(read, 0)
    assert choice_patches(read, 0, lines, old) == []
    red, brass = old.present.reactions
    assert choice_problems(replace(old, present=replace(
        old.present, reactions=(red, replace(brass, item=""))))) == PRESENT_ITEM_TEXT
    assert choice_problems(replace(old, present=replace(
        old.present, reactions=(red, replace(brass, item="red_lantern"))))) == \
        PRESENT_TWICE_TEXT
    # A reaction (or the whole option) with lines of its own isn't removed by the form.
    assert choice_patches(read, 0, lines, replace(old, present=replace(
        old.present, reactions=(red,)))) == PRESENT_REMOVE_TEXT
    assert choice_patches(read, 0, lines, replace(old, present=None)) == PRESENT_REMOVE_TEXT
    # Six options in all.
    many = tuple(ChoiceItem(f"C{n}") for n in range(6))
    assert choice_patches(read, 0, lines, replace(old, choices=many)) == \
        forms.CHOICE_LIMIT_TEXT


def test_removing_a_simple_option():
    text = SCENE.replace('''            brass_key:
                hana "A key?"
                $ door = True
''', "")
    read, lines = _read(text)
    old = read_choice(read, 0)
    after = _apply(lines, choice_patches(read, 0, lines, replace(old, present=None)))
    assert after == lines[:5] + ['    hana "End."']
    assert formpresent.summary_of(old.present.reactions[0]) == "lantern"
