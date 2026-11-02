"""Indentation, blocks, and if-chains (F02 checklist step 5; 04-technical.md §7.7).

AC-F02-16 (accepted indentation), AC-F02-17 (indentation errors), and AC-F02-24 (if, elif,
else), through a single-file parse. The example story stands in for the ``compat/`` corpus
(committed in step 8).
"""

import re

import pytest

from engine.script.nodes import If, PythonLine, Say
from tests.script.helpers import FIXTURES, dumps, message_at, parse_text, template


def _lanterns() -> str:
    return (FIXTURES / "lanterns" / "chapter1.vns").read_text(encoding="utf-8")


def _reindent(text: str, unit: str) -> str:
    def fix(match: re.Match[str]) -> str:
        return unit * (len(match.group(1)) // 4)
    # Continuation lines (8 spaces under a 4-space line) keep their relative depth.
    return "\n".join(re.sub(r"^( +)", fix, line) for line in text.split("\n"))


# --- AC-F02-16 ---------------------------------------------------------------------------

@pytest.mark.parametrize("unit", [" ", "  ", "   ", " " * 8, "\t"],
                         ids=["1", "2", "3", "8", "tab"])
def test_any_indentation_width_gives_the_same_program(unit):
    original = parse_text(_lanterns(), "script/chapter1.vns")
    changed = parse_text(_reindent(_lanterns(), unit), "script/chapter1.vns")
    assert changed.errors == [], changed.messages
    assert dumps(changed.nodes, positions=False) == dumps(original.nodes, positions=False)


def test_mixed_widths_per_block():
    text = ('define trust = 1\nlabel start:\n  "A."\n  if trust > 0:\n       "B."\n'
            '       $ trust += 1\n  else:\n   "C."\n  return\n')
    parsed = parse_text(text)
    assert parsed.errors == [], parsed.messages
    block = parsed.labels["start"].block
    assert [type(s).__name__ for s in block] == ["Say", "If", "Return"]


@pytest.mark.parametrize("row", ['"one⏎[5]two"', '"one⏎[40]two"', "$ x = (1,⏎[5]2)",
                                 "$ x = (1,⏎[30]2)"])
def test_continuations_any_amount_deeper(row):
    assert parse_text(template(S=row)).errors == []


def _nested(levels: int) -> str:
    lines = ["label start:"]
    for depth in range(levels):
        lines.append("    " * (depth + 1) + "if True:")
    lines.append("    " * (levels + 1) + '"Deep."')
    lines.append("    return")
    return "\n".join(lines) + "\n"


def test_fifty_nested_blocks_load():
    # The label's block is block 1; 49 nested ifs make blocks 2–50.
    parsed = parse_text(_nested(49))
    assert parsed.errors == [], parsed.messages
    node = parsed.labels["start"].block[0]
    for _ in range(49):
        assert isinstance(node, If)
        node = node.branches[0].block[0]
    assert isinstance(node, Say) and node.text == "Deep."


# --- AC-F02-17 ---------------------------------------------------------------------------

E10_TAB = ("this line is indented with a tab, but earlier lines in this file use spaces. Use "
           "one or the other in each file.")
E13 = ("this line is indented more than the line above, but the line above doesn't start a "
       "block. Remove the extra indentation.")
E14 = ("this line's indentation doesn't line up with any block above it. Indent it by 0, 4, "
       "or 8 spaces.")
E15 = ("this line is inside more than 50 blocks, which is the limit. Move some inner lines into "
       "their own label and call it.")
E16 = ("this line is longer than 10,000 characters, which is the limit. Split it over several "
       "lines.")


@pytest.mark.parametrize("edit,where,message", [
    ({"replace": {5: '[t]"A."'}}, "5", E10_TAB),
    ({"replace": {5: '[t][4]"A."'}}, "5",
     "this line is indented with both tabs and spaces. Use one or the other in each file."),
    ({"replace": {5: '[4]{U+00A0}"A."'}}, "5:5",
     "this line is indented with a non-breaking space (U+00A0), which looks like a space but "
     "isn't one. Retype the indentation with spaces or a tab."),
    ({"replace": {5: '[4]{U+3000}"A."'}}, "5:5",
     "this line is indented with a full-width space (U+3000), which looks like a space but "
     "isn't one. Retype the indentation with spaces or a tab."),
    ({"S": "if trust > 0:"}, "5",
     "this if has no lines under it. Indent the lines that belong to it."),
    ({"T": "label empty:"}, "9",
     "this label has no lines under it. Indent the scene, or write return for now."),
    ({"S": '"A."⏎[8]"B."'}, "6", E13),
    ({"S": 'if trust > 0:⏎[8]"A."⏎[6]"B."'}, "7", E14),
])
def test_indentation_errors(edit, where, message):
    parsed = parse_text(template(**edit))
    assert [message_at(e) for e in parsed.errors] == [(where, message)]


def test_e10_in_a_tab_file():
    text = 'label start:\n\t"A."\n    "B."\n\treturn\n'
    parsed = parse_text(text)
    assert parsed.codes == ["E10"] and parsed.errors[0].line == 3
    assert "spaces" in parsed.errors[0].message and "tab" in parsed.errors[0].message


def test_e12_names_comment_lines():
    parsed = parse_text(template(S="if trust > 0:⏎[8]# later"))
    assert parsed.codes == ["E12"] and parsed.errors[0].line == 5
    assert "(comment lines don't count)" in parsed.errors[0].message


def test_e15_past_fifty_blocks():
    parsed = parse_text(_nested(50))
    assert [message_at(e) for e in parsed.errors] == [("52", E15)]


def test_e16_for_long_lines():
    parsed = parse_text(template(S='"' + "a" * 9995 + '"'))
    assert [message_at(e) for e in parsed.errors] == [("5", E16)]
    parsed = parse_text(template(T="#" + "x" * 10000))
    assert [message_at(e) for e in parsed.errors] == [("9", E16)]
    parsed = parse_text(template(S='"' + "a" * 9994 + '"'))
    assert parsed.errors == []


def test_no_indentation_errors_after_the_first_e10():
    text = template(replace={5: '[t]"A."⏎[6]"B."⏎[t][2]"C."⏎[4]jmup bridge'})
    parsed = parse_text(text)
    assert parsed.codes == ["E10", "E30a"]
    assert [e.line for e in parsed.errors] == [5, 8]


def test_a_run_of_wrongly_indented_lines_gives_one_error():
    parsed = parse_text(template(S='"A."⏎[8]"B."⏎[8]"C."⏎[8]"D."'))
    assert parsed.codes == ["E13"]
    parsed = parse_text(template(S='if trust > 0:⏎[8]"A."⏎[6]"B."⏎[6]"C."'))
    assert parsed.codes == ["E14"]


def test_e14_in_a_tab_file_lists_tabs():
    text = 'label start:\n\tif x:\n\t\t"A."\n\t\t\t"B."\n'
    parsed = parse_text(text)
    assert parsed.codes == ["E13"]
    text = 'label start:\n\tif x:\n\t\t\t"A."\n\t\t"B."\n'
    parsed = parse_text(text)
    assert parsed.codes == ["E14"]
    assert parsed.errors[0].message.endswith("Indent it by 0, 1, or 3 tabs.")


# --- AC-F02-24 ---------------------------------------------------------------------------

@pytest.mark.parametrize("row,where,message", [
    ('if trust >= 3⏎[8]"A."', "5", "if needs : at the end of the line. Write if trust >= 3:"),
    ('elif trust > 1:⏎[8]"A."', "5", "this elif has no if directly above it at the same "
                                     "indentation. Line it up under its if, or change it to if."),
    ('else:⏎[8]"A."', "5", "this else has no if directly above it at the same indentation. "
                           "Line it up under its if."),
    ('if trust > 0:⏎[8]"A."⏎[4]else:⏎[8]"B."⏎[4]else:⏎[8]"C."', "9",
     "this if already has an else (line 7). Remove one, or change the first to elif with a "
     "condition."),
    ('if trust > 0:⏎[8]"A."⏎[4]else:⏎[8]"B."⏎[4]elif x:⏎[8]"C."', "9",
     "elif can't come after else (line 7). Move it above the else."),
    ('if trust > 0:⏎[8]"A."⏎[4]else trust < 2:⏎[8]"B."', "7",
     "else doesn't take a condition. Use elif trust < 2: instead."),
    ('if trust > 0:⏎[8]"A."⏎[4]else if x:⏎[8]"B."', "7", "write elif instead of else if."),
    ('if :⏎[8]"A."', "5", "if needs a condition before the colon, e.g. if trust >= 3:"),
])
def test_if_chain_errors(row, where, message):
    parsed = parse_text(template(S=row))
    assert [message_at(e) for e in parsed.errors] == [(where, message)]


def _if(parsed, index: int = 1) -> If:
    node = parsed.labels["start"].block[index]
    assert isinstance(node, If)
    return node


def test_chain_with_three_elifs_and_an_else():
    row = ('if trust > 3:⏎[8]"A."⏎[4]elif trust > 2:⏎[8]"B."⏎[4]elif trust > 1:⏎[8]"C."'
           '⏎[4]elif trust > 0:⏎[8]"D."⏎[4]else:⏎[8]"E."')
    parsed = parse_text(template(S=row))
    assert parsed.errors == []
    node = _if(parsed)
    assert [b.keyword for b in node.branches] == ["if", "elif", "elif", "elif", "else"]
    assert [b.block[0].text for b in node.branches] == ["A.", "B.", "C.", "D.", "E."]
    assert node.branches[-1].condition is None


def test_chain_inside_another_if_block():
    row = 'if trust > 0:⏎[8]if x:⏎[12]"A."⏎[8]else:⏎[12]"B."⏎[4]else:⏎[8]"C."'
    parsed = parse_text(template(S=row))
    assert parsed.errors == []
    outer = _if(parsed)
    inner = outer.branches[0].block[0]
    assert isinstance(inner, If) and len(inner.branches) == 2 and len(outer.branches) == 2


def test_comment_and_blank_between_block_and_elif():
    row = 'if trust > 0:⏎[8]"A."⏎⏎[4]# note⏎[4]elif x:⏎[8]"B."'
    parsed = parse_text(template(S=row))
    assert parsed.errors == []
    assert len(_if(parsed).branches) == 2


@pytest.mark.parametrize("condition", ['d["k:v"] == 1', "x[1:2]", "(n := 2) > 1",
                                       '{"a": 1}'])
def test_condition_ends_at_the_last_top_level_colon(condition):
    parsed = parse_text(template(S=f'if {condition}:⏎[8]"A."'))
    assert parsed.errors == [], parsed.messages
    assert _if(parsed).branches[0].condition.source == condition


def test_missing_colon_still_opens_the_block():
    parsed = parse_text(template(S='if trust >= 3⏎[8]"A."⏎[8]"B."'))
    assert parsed.codes == ["E31b"]


def test_if_with_condition_error_keeps_its_chain():
    parsed = parse_text(template(S='if trust = 3:⏎[8]"A."⏎[4]else:⏎[8]"B."'))
    assert parsed.codes == ["E81"]


def test_python_line_in_if_block():
    parsed = parse_text(template(S='if x:⏎[8]$ y = 1'))
    assert isinstance(_if(parsed).branches[0].block[0], PythonLine)
