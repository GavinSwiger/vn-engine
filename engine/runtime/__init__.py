"""The story runtime (F03): GameState, freeze, dice, and the interpreter.

Headless: never imports pygame, and never imports ``time``, ``random``, ``secrets``,
``threading``, ``_thread``, or ``datetime`` (TR-F03-05, invariant 7). ``app`` times the
slicing and supplies the seed.

One explicit import line per module that registers executors (no discovery).
"""

# F04's scene, show, and hide are registered by the interpreter too: runtime/stage.py sits
# below it (state.py and commands.py use StageState).
from engine.runtime import interpreter  # noqa: F401  F03: Say, $, if, jump, call, return
