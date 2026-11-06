"""Help ▸ Guides: the engine's guides in ``docs/``, read in Studio's own reader window
(``guidereader``), whose **Open in your viewer** hands the file to the system's viewer for
Markdown files (``open_guide``; many PCs have none, so the reader is the default). The
story's comments name these guides by their menu path, since a game folder has no
``docs/`` of its own."""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from engine.core.paths import engine_root, is_frozen

GUIDES_MENU = "Guides"
GUIDE_MISSING = "The guide “{title}” isn't in this copy of vn-engine. {fix}"
# Where a missing guide belongs: the Studio app keeps docs/ inside its own folder, a copy
# run with Python has it next to main.py.
FIX_APP = "Unzip vn-engine Studio again to get it back."
FIX_DEV = "It belongs in the docs folder next to main.py."
GUIDE_NO_VIEWER = ("Couldn't open the guide “{title}” in another app. Open {path} with any "
                   "text editor.")

# (menu label, file in docs/), in the order a game maker needs them.
GUIDES: tuple[tuple[str, str], ...] = (
    ("Beginner's guide", "first-game.md"),     # the Guide checklist follows it (guide.py)
    ("Script language", "script-language.md"),
    ("Studio", "scene-editor.md"),
    ("Story map", "story-map.md"),
    ("Database", "database.md"),
    ("Game settings", "game-settings.md"),
    ("Screens and UI", "ui-system.md"),
    ("Minigames", "minigames.md"),
    ("Meta files", "meta-files.md"),
    ("Update the running game", "hot-reload.md"),
    ("Developer console", "dev-console.md"),
    ("Build game", "build-game.md"),
    ("AI assistant", "assistant.md"),                    # F48 PR-F48-31
)


def guide_path(name: str) -> Path:
    return engine_root() / "docs" / name


def missing_text(title: str) -> str:
    """What to say when the guide ``title`` isn't in this copy (app or Python run)."""
    return GUIDE_MISSING.format(title=title, fix=FIX_APP if is_frozen() else FIX_DEV)


def open_path(path: Path) -> None:
    """Show ``path`` in the system's viewer (a seam for tests)."""
    if sys.platform == "win32":
        os.startfile(path)                     # noqa: S606 (a local docs file)
    else:
        webbrowser.open(path.as_uri())


def open_guide(title: str, name: str) -> str | None:
    """Open the guide ``name`` in the system's viewer (the reader's **Open in your
    viewer**); the message to show when it can't be opened, else None."""
    path = guide_path(name)
    if not path.is_file():
        return missing_text(title)
    try:
        open_path(path)
    except OSError:
        return GUIDE_NO_VIEWER.format(title=title, path=path)
    return None
