"""Bundled minigames (F24–F27): engine modules registered with the same ``register`` as
game plugins, before the game's own (F23 ``04`` §7.10).

Each bundled feature adds one explicit import line and its class to ``BUNDLED``, in feature
order (F25 ``07`` I-8); nothing is found by listing a folder. A game plugin with the same
name replaces a bundled minigame (W160 in dev, one INFO record every run). Bundled modules
don't call ``register`` themselves: the loader registers each class here under the unit
``"engine"``. ``rule_text`` holds the text helpers they share (F25 ``07`` I-5).
"""

from engine.minigames.bundled.poem_game import PoemGame          # F24
from engine.minigames.bundled.present_evidence import PresentEvidence   # F25
from engine.minigames.bundled.phone_chat import PhoneChat              # F26
from engine.minigames.bundled.puzzle_room import PuzzleRoom            # F27

BUNDLED: tuple[type, ...] = (PoemGame, PresentEvidence, PhoneChat, PuzzleRoom)
