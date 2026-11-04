"""Help ▸ Guides: the engine's guides in ``docs/``, opened in the system's own viewer for
Markdown files (a text editor at worst). The story's comments name these guides by their
menu path, since a game folder has no ``docs/`` of its own."""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from engine.core.paths import engine_root

GUIDES_MENU = "Guides"
GUIDE_MISSING = ("The guide “{title}” isn't in this copy of vn-engine. It belongs in the "
                 "docs folder next to main.py.")
GUIDE_NO_VIEWER = ("Couldn't open the guide “{title}”. Open docs/{name} in the vn-engine "
                   "folder with any text editor.")

# (menu label, file in docs/), in the order a game maker needs them.
GUIDES: tuple[tuple[str, str], ...] = (
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


def open_path(path: Path) -> None:
    """Show ``path`` in the system's viewer (a seam for tests)."""
    if sys.platform == "win32":
        os.startfile(path)                     # noqa: S606 (a local docs file)
    else:
        webbrowser.open(path.as_uri())


def open_guide(title: str, name: str) -> str | None:
    """Open the guide ``name``; the message to show when it can't be opened, else None."""
    path = guide_path(name)
    if not path.is_file():
        return GUIDE_MISSING.format(title=title)
    try:
        open_path(path)
    except OSError:
        return GUIDE_NO_VIEWER.format(title=title, name=name)
    return None
