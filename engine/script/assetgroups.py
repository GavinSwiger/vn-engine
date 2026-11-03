"""The game folder's asset groups, in Studio's panel order (F45 ``04`` §4.1, Q8; PR-F45-01, 02;
TR-F45-06).

Why this module exists: Studio lists and adds files per group (``images/``, ``audio/``, …)
and must accept exactly what the engine reads. Each row is built from the loaders' own
constants, never a copy, so a changed suffix list or cap reaches Studio by itself. Two caps
are the exception: F08's ``MUSIC_MAX_BYTES`` (``audio/limits.py``) and F23's
``MAX_FILE_BYTES`` (``minigames/loader.py``) live in packages ``script`` may not import, so
they are literals here and ``tests/script/test_assetgroups.py`` asserts they are equal
(F45 ``07`` I-3). The validators keyed by ``kind`` are Studio code (``tools/editor/files.py``).

Pure data; the loaders don't read this table.
"""

from dataclasses import dataclass
from typing import Literal

from engine.core.constants import (ASSET_MAX_BYTES, CONFIG_FILENAME, FONT_SUFFIXES,
                                   IMAGE_SUFFIXES, MB, META_ORIGINAL_MAX_BYTES,
                                   META_ORIGINALS_DIR)
from engine.script.audio import PLAYABLE_EXTS
from engine.script.limits import SCRIPT_FILE_MAX_BYTES
from engine.script.loader import SCRIPT_DIR, SCRIPT_SUFFIX

AssetKind = Literal["script", "image", "audio", "gui_image", "font", "code", "meta"]

# Caps from packages ``script`` can't import (I-3); a parity test ties each to its source.
MUSIC_MAX_BYTES = 64 * MB            # F08 engine.audio.limits.MUSIC_MAX_BYTES
MINIGAME_FILE_MAX_BYTES = 1 << 20    # F23 engine.minigames.loader.MAX_FILE_BYTES

CONFIG_REF = CONFIG_FILENAME         # opened and saved; never added, renamed, or deleted


@dataclass(frozen=True, slots=True)
class AssetGroup:
    """One top-level folder of the game: files with one of ``suffixes`` (lower case, with
    the dot), each at most ``max_bytes``. ``title`` is the panel's group name."""
    key: str
    folder: str
    title: str
    suffixes: tuple[str, ...]
    max_bytes: int
    kind: AssetKind


ASSET_GROUPS: tuple[AssetGroup, ...] = (
    AssetGroup("script", SCRIPT_DIR, "Script", (SCRIPT_SUFFIX,), SCRIPT_FILE_MAX_BYTES, "script"),
    AssetGroup("images", "images", "Images", IMAGE_SUFFIXES, ASSET_MAX_BYTES, "image"),
    AssetGroup("audio", "audio", "Audio", tuple(sorted(PLAYABLE_EXTS)), MUSIC_MAX_BYTES, "audio"),
    AssetGroup("gui", "gui", "GUI", IMAGE_SUFFIXES, ASSET_MAX_BYTES, "gui_image"),
    AssetGroup("fonts", "fonts", "Fonts", FONT_SUFFIXES, ASSET_MAX_BYTES, "font"),
    AssetGroup("minigames", "minigames", "Minigames", (".py",), MINIGAME_FILE_MAX_BYTES, "code"),
    # F31 (C5): the originals ``file write`` copies; ``characters/`` is never a group.
    AssetGroup("files", META_ORIGINALS_DIR, "Meta files", (".chr", ".txt"),
               META_ORIGINAL_MAX_BYTES, "meta"),
)

__all__ = ["ASSET_GROUPS", "AssetGroup", "AssetKind", "CONFIG_REF", "MINIGAME_FILE_MAX_BYTES",
           "MUSIC_MAX_BYTES"]
