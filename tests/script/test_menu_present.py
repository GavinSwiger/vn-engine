"""F64 present at a menu, the script side (specs/F64-items/SPEC-present.md): parse, the load
codes E442–E447, W310, and the walks (story map links, reach, flow rules)."""

import pytest

from engine.script.choicepresent import PRESENT_KEY, PresentOption
from engine.script.flowgraph import FLOW_RULES
from engine.script.labelgraph import block_links
from engine.script.menu import Menu
from tests.runtime.menu_story import load_text

STORY = '''define hana = Character("Hana")
lock item red_lantern "Red Lantern"
lock item brass_key "Brass Key"
lock tip lanterns "Lanterns"
default bag = True
label start:
    menu:
        hana "What's that in your hand?"
        "Nothing.":
            $ pass
        present if bag:
            red_lantern:
                hana "You kept it!"
                jump lantern
            else:
                hana "...Why?"
    hana "End."
label lantern:
    "The lantern glows."
'''
REACTIONS = '''            red_lantern:
                hana "You kept it!"
                jump lantern
            else:
                hana "...Why?"
'''


def _menu(program) -> Menu:
    menu = program.labels["start"].block[0]
    assert isinstance(menu, Menu)
    return menu


def _codes(tmp_path, text):
    result = load_text(tmp_path, text)
    return ([(e.code, e.line) for e in result.errors],
            [(w.code, w.line) for w in result.warnings if w.code == "W310"])


def test_present_parses_with_a_condition_and_reactions(tmp_path):
    result = load_text(tmp_path, STORY)
    assert not result.errors, [e.format() for e in result.errors]
    menu = _menu(result.program)
    option = menu.present
    assert isinstance(option, PresentOption) and option.key == PRESENT_KEY
    assert option.condition is not None and option.condition.source == "bag"
    assert [r.item for r in option.reactions] == ["red_lantern", None]
    assert option.items() == ("red_lantern",)
    assert option.reaction_for("brass_key").item is None          # else
    assert len(menu.choices) == 1 and menu.blocks()[-1] == (option,)
    assert option.sid.startswith("start/") and option.line == 11
    assert [s.text for s in option.blocks()[1]] == ["...Why?"]


def test_present_stays_a_free_word(tmp_path):
    text = STORY.replace("default bag = True\n", "default bag = True\ndefault present = 3\n")
    assert not load_text(tmp_path, text).errors
    text = STORY.replace("        present if bag:", "        present:")
    assert not load_text(tmp_path, text).errors


@pytest.mark.parametrize("old, new, code, line", [
    (REACTIONS, REACTIONS.replace("            else:\n                hana \"...Why?\"\n", ""),
     "E445", 11),
    ("            else:", "            red_lantern:\n                $ pass\n            else:",
     "E446", 15),
    ("            else:", "            else:\n                $ pass\n            else:", "E446", 17),
    ("present if bag:\n" + REACTIONS, "present:\n", "E444", 11),
    ("                hana \"...Why?\"\n", "", "E444", 15),
    ("            red_lantern:", "            hana \"x\"\n            red_lantern:", "E443", 12),
    ("                hana \"...Why?\"\n",
     "                hana \"...Why?\"\n            brass_key:\n                $ pass\n",
     "E443", 17),
    ("present if bag:", "present timeout:", "E442", 11),
    ('    hana "End."', '        present:\n            else:\n                $ pass\n'
                       '    hana "End."', "E442", 17),
    ("            red_lantern:", "            red_lantren:", "E447", 12),
    ("            red_lantern:", "            lanterns:", "E447", 12),
])
def test_present_mistakes(tmp_path, old, new, code, line):
    assert old in STORY
    errors, _ = _codes(tmp_path, STORY.replace(old, new, 1))
    assert errors and errors[0] == (code, line), errors


def test_unknown_item_suggests_the_closest(tmp_path):
    result = load_text(tmp_path, STORY.replace("            red_lantern:", "            red_lantren:"))
    message = next(e.message for e in result.errors if e.code == "E447")
    assert 'Did you mean "red_lantern"?' in message


def test_w310_a_key_item_given_in_the_scene_with_no_reaction(tmp_path):
    text = STORY.replace("label start:\n", "label start:\n    unlock item brass_key\n"
                                           "    unlock item red_lantern\n")
    errors, warnings = _codes(tmp_path, text)
    assert not errors and warnings == [("W310", 13)]
    result = load_text(tmp_path, text)
    message = next(w.message for w in result.warnings if w.code == "W310")
    assert "brass_key" in message and "red_lantern" not in message


def test_reactions_are_branches_on_the_map_and_the_flow_graph(tmp_path):
    program = load_text(tmp_path, STORY).program
    links = list(block_links("start", program.labels["start"].block))
    assert [(link.dst, link.kind, link.choice, link.conditional) for link in links] == [
        ("lantern", "menu", "Show red_lantern", True)]
    assert PresentOption in FLOW_RULES


def test_a_menu_counts_present_as_one_of_its_six(tmp_path):
    choices = "".join(f'        "C{n}":\n            $ pass\n' for n in range(6))
    text = STORY.replace('        "Nothing.":\n            $ pass\n', choices)
    errors, _ = _codes(tmp_path, text)
    assert ("E173", 7) in errors
