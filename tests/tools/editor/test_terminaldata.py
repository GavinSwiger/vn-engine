"""F56 step P2: Studio's terminal data (``tools/editor/terminaldata.py``): AC-F56-28, 29."""

import ast

import pytest

from engine.minigames.bundled import terminal_rules
from engine.tools.editor import terminaldata as td
from tests.minigames.bundled.test_terminal_rules import LIBRARY, REFUSALS


def evaluated(lines: list[str]) -> object:
    """The value a ``define``'s lines give (``define name = <literal>``)."""
    text = "\n".join(lines)
    return ast.literal_eval(text.split("=", 1)[1].strip())


# --- AC-F56-28: + New writes a define the game accepts; a read set writes back unchanged ---------

def test_ac_f56_28_starter_and_round_trip():
    lines = td.define_lines("my_terminal", td.starter())
    assert lines == ['define my_terminal = {',
                     '    "welcome": "Type help to see what you can do.",',
                     '    "commands": [',
                     '        {"command": "hello", "reply": "Hello."},',
                     '    ],',
                     '    }']
    value = evaluated(lines)
    assert terminal_rules.problem({"data": value}) is None              # the game accepts it
    assert not terminal_rules.w274_needed(terminal_rules.parse({"data": value}),
                                          lambda name: False)            # and help lists it
    model = td.read(LIBRARY)
    assert model is not None and td.value_of(model) == {
        **LIBRARY, "commands": [td._row_value(c) for c in model.commands]}
    assert td.read(td.value_of(model)) == model                          # unchanged round trip
    again = evaluated(td.define_lines("library_pc", model))
    assert td.read(again) == model and terminal_rules.problem({"data": again}) is None
    assert td.read([]) is None and td.read({"commands": [{"command": 3}]}) is None
    assert td.read({"commands": [], "extra": 1}) is None


# --- AC-F56-29: Studio's problems are the rules', case by case --------------------------------

@pytest.mark.parametrize(("data", "reason"), REFUSALS)
def test_ac_f56_29_problems_match_the_rules(data, reason):
    assert td.problem_value(data) == terminal_rules.problem({"data": data}) == reason
    assert td.problem_value(LIBRARY) is None
    self_loop = {"commands": [{"command": "a", "after": "a"}]}
    assert td.problem_value(self_loop) == terminal_rules.problem({"data": self_loop})
