"""Launch helpers for copies of the example game (F30 s6).

The example offers the player's computer user name (``[meta] username = true``), so a fresh
launch asks F30's first-launch question before the title. Tests that copy ``game/`` and
expect the title (or the story) at once store an answer first.
"""

import json
from pathlib import Path


def answer_name_question(game: Path, allow: bool = False) -> None:
    """Store the player's answer to F30's first-launch question in a copied game's dev
    ``settings/settings.json`` (``username_use`` 2 or 1), so a launch of a game that offers
    ``{username}`` (the example, since F30 s6) goes on to the title without asking."""
    folder = game / "settings"
    folder.mkdir(exist_ok=True)
    (folder / "settings.json").write_text(
        json.dumps({"format": 3, "values": {"username_use": 2 if allow else 1}}),
        encoding="utf-8")
