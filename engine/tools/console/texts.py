"""Every text the in-game console shows (F40 ``01`` §6.3; ``04`` §3).

Why this module exists: the console is read by authors who may not program, so its words are
fixed in one place, written plainly, and tested as written. ``CODE_HINT`` holds the needle
``One line of Python, like a $ line``: the real build's leak scan looks for it to prove the
console never ships (SEC-F40-01 (d)), so it must exist only under ``engine/tools/``.

Texts with ``{…}`` are ``str.format`` templates; every value put into them is already shown
text (``valuetext``) or an escaped name. User-facing words never say "node".

Additions beyond ``01`` §6.3 (delegated decisions, F40 ``04`` §18 style): ``EDIT_HINT`` (the
hint while a value field is open: Esc cancels the field before it closes the console),
``NOTHING_MATCHES`` and ``NO_VARIABLES`` (an empty list says why), ``CODE_EMPTY`` (the Code
tab before its first run), and the gamepad hint ``PAD_HINT``.
"""

# Header (01 §6.3)
HEADER = "Console — {label}, {file} line {line}"
HEADER_NO_STORY = "Console — no story running"
HEADER_KEYS = "F12 / Esc"

# Tabs, fields, groups, buttons
TAB_VARIABLES = "Variables"
TAB_JUMP = "Jump"
TAB_CODE = "Code"
FILTER_PLACEHOLDER = "Type to filter"
GROUP_VARIABLES = "STORY VARIABLES"
GROUP_METERS = "METERS"
METER_VALUE = "{value}   ({low} to {high})"
SWITCH = "Switch"
MINUS = "-1"
PLUS = "+1"
VALUE_LABEL = "New value"
LABEL_PLACE = "{file} line {line}"

# Hints
VARIABLES_HINT = "Enter: change · Esc: close"
EDIT_HINT = "Enter: set it · Esc: cancel"
JUMP_HINT = "Enter: jump there. The story keeps its variables."
CODE_HINT = "One line of Python, like a $ line. Enter runs it."
PAD_HINT = "A: act · B: close"

# Results
SET_DONE = "{name} is now {value}."
JUMP_DONE = "Jumped to {label}."
JUMP_NEW_GAME = "Started a new game at {label}."
CODE_DONE = "Done."

# Refusals and problems
BAD_VALUE = ("That isn't a value the console understands. Use a number, True, False, None, "
             "text in quotes, a list or a dict.")
METER_WHOLE = "{name} is a meter, so it needs a whole number."
NOT_VARIABLE = ("{name} isn't a story variable. Add \"default {name} = ...\" to your "
                "script first.")
NOT_PLAIN = "This value isn't plain data. Change it in Code."
TOO_LONG = "That ran too long and was stopped."
CANT_SAVE = "That change can't go into a save ({reason}), so it was undone."
NO_SCENE = "There's no scene called {label}."
MINIGAME = "Not while a minigame runs. Shift+F8 ends it."
REPLAY = "Not during a scene replay."
NO_STORY = "Start a game first. Jump starts one at any scene."
NOTHING_MATCHES = "Nothing matches “{filter}”."
NO_VARIABLES = "This story has no default lines or meters yet."
CODE_EMPTY = "Type a line below. Up and Down bring back earlier lines."

__all__ = [name for name in dir() if name.isupper()]
