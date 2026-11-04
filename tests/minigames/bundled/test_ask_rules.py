"""F52 step P6: ``ask_text``'s rules (``bundled/ask_rules.py``): AC-F52-29, 30."""

import pytest

from engine.minigames.api import Outcome
from engine.minigames.bundled import ask_rules as rules

GOOD = {"prompt": "What's your name?", "max_length": 12, "allowed": "name"}


# --- AC-F52-29: the refusal texts, exactly --------------------------------------------------------

@pytest.mark.parametrize(("args", "reason"), [
    ({"prompt": "x" * 412},
     "prompt must be text of 1 to 300 characters, but it has 412."),
    ({"prompt": ""}, "prompt must be text of 1 to 300 characters, but it is empty."),
    ({"max_length": 0}, "max_length must be a whole number from 1 to 200, not 0."),
    ({"max_length": True}, "max_length must be a whole number from 1 to 200, not True."),
    ({"allowed": "letter"},
     'allowed must be "any", "name", "letters", "digits" or "letters_digits", not "letter". '
     'Did you mean "letters"?'),
    ({"allowed": "emoji"},
     'allowed must be "any", "name", "letters", "digits" or "letters_digits", not "emoji".'),
    ({"default": "x" * 31},
     "default can hold at most 12 characters (max_length), but it has 31."),
    ({"allowed": "digits", "default": "1ab"},
     'default has characters allowed="digits" doesn\'t let the player type: "a", "b".'),
    ({"hide": "yes"}, 'hide must be True or False, not "yes".'),
    ({"can_be_empty": "yes"}, 'can_be_empty must be True or False, not "yes".'),
])
def test_ac_f52_29_refusals(args, reason):
    assert rules.problem({**GOOD, **args}) == reason
    assert rules.problem(GOOD) is None and rules.problem({}) is None
    assert rules.problem({**GOOD, "default": "Sayo"}) is None
    # A family emoji is one character, as the field counts it.
    assert rules.problem({"max_length": 1, "default": "\U0001F468‍\U0001F469"}) is None


# --- AC-F52-30: the outcomes ---------------------------------------------------------------------

def test_ac_f52_30_outcomes():
    assert rules.fixed_outcome("test", {}) == Outcome("Test")
    assert rules.fixed_outcome("test", {"default": "  Sayo "}) == Outcome("Sayo")
    assert rules.fixed_outcome("skipped", {"default": "Sayo"}) is None   # never skipped
    assert rules.result_of("  Ren  ") == "Ren"
