"""How Studio looks for this person, in every game (2026-11-04).

Why this module exists: hidden tabs, where the panes sit, Show warnings and Reduce motion are
the author's taste, not the game's. They used to be kept in each game's
``.studio/studio.json``, so a new game started from the defaults again. They are now kept in
the per-user folder (``paths.studio_user_dir()/studio-look.json``), and every game opens the
way the author left the last one. A game that still has its own value in ``studio.json``
(from before) is read when the per-user file hasn't that key yet.

Pure Python, no Tk. Never raises: a missing or damaged file is the defaults.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from engine.core import safefile
from engine.core.paths import studio_user_dir

LOOK_NAME: Final = "studio-look.json"
LOOK_MAX_BYTES: Final = 64 * 1024
# Keys kept here, with the type each must have (dict values: None means "the default").
LOOK_KEYS: Final = {"tabs": dict, "panes": dict, "show_warnings": bool, "reduce_motion": bool}

# Tests point this at a temporary folder (``tests/conftest.py``) so nothing reaches the real
# profile; None: ``studio_user_dir()``.
folder_override: Path | None = None


def _folder() -> Path | None:
    return folder_override if folder_override is not None else studio_user_dir()


def load() -> dict[str, object]:
    """The saved look: only known keys with the right type (a dict key may hold None)."""
    place = _folder()
    if place is None:
        return {}
    result = safefile.read_regular(Path(place) / LOOK_NAME, LOOK_MAX_BYTES)
    if not result.ok or result.data is None:
        return {}
    try:
        doc = json.loads(result.data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {key: doc[key] for key, kind in LOOK_KEYS.items()
            if key in doc and (isinstance(doc[key], kind) or (kind is dict and doc[key] is None))}


def value(key: str, game_value: object = None) -> object:
    """``key``'s saved value, else ``game_value`` (the game's own, from before)."""
    saved = load()
    return saved[key] if key in saved else game_value


def save(**changes: object) -> bool:
    """Merge ``changes`` (``LOOK_KEYS`` only) into the file; False when it can't be written."""
    place = _folder()
    if place is None:
        return False
    doc = load()
    doc.update({key: change for key, change in changes.items() if key in LOOK_KEYS})
    data = (json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    try:
        safefile.write_atomic(Path(place) / LOOK_NAME, [data])
    except OSError:
        return False
    return True


__all__ = ["LOOK_KEYS", "LOOK_NAME", "load", "save", "value"]
