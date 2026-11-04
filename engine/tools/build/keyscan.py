"""The build's API-key scan (F48 ``04-technical.md`` §7.8; ``05-security.md`` SEC-F48-24;
``01-design.md`` PR-F48-32, §6.6).

Why this module exists: an author who pastes an API key into a script, a plugin or a
settings file would ship it to every player. After **Copy**, the build child reads each
copied text file (``SCANNED_SUFFIXES``, at most ``SCAN_MAX_BYTES``) and looks for
``core.redact.KEY_SHAPE_RE`` (``sk-ant-…``, ``sk-proj-…``, or ``sk-`` and 20 key
characters, from a word boundary). A hit is a warning naming ``ref`` and line only: the
text, or any part of it, is never kept, printed, logged or reported. At most
``KEY_HITS_MAX`` hits are kept, one per line.

Child-only, like the rest of ``tools/build``: ``core`` and the standard library.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core import safefile
from engine.core.editorreport import BUILD_MAX_KEYS
from engine.core.redact import KEY_SHAPE_RE

SCANNED_SUFFIXES: Final = frozenset({".vns", ".toml", ".py", ".json", ".txt", ".po", ".md",
                                     ".csv", ".ini", ".cfg", ".yml", ".yaml"})
SCAN_MAX_BYTES: Final = 16 * 1024 * 1024
KEY_HITS_MAX: Final = BUILD_MAX_KEYS


@dataclass(frozen=True, slots=True)
class KeyHit:
    """A key-shaped text at ``line`` (1-based) of the game-relative ``ref``."""

    ref: str
    line: int


def key_lines(text: str) -> list[int]:
    """The 1-based lines (split on ``\\n``) holding a key shape, each once."""
    lines: list[int] = []
    line, counted = 1, 0
    for match in KEY_SHAPE_RE.finditer(text):
        line += text.count("\n", counted, match.start())
        counted = match.start()
        if not lines or lines[-1] != line:
            lines.append(line)
    return lines


def scan(game_copy: Path, *, limit: int = KEY_HITS_MAX) -> list[KeyHit]:
    """Scan the copied game folder ``game_copy`` (made by the build, so links were never
    copied); refs are relative to it with ``/``, folders and files in name order."""
    hits: list[KeyHit] = []
    root = Path(game_copy)
    for top, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        rel = Path(top).relative_to(root).parts
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() not in SCANNED_SUFFIXES:
                continue
            result = safefile.read_regular(Path(top) / name, SCAN_MAX_BYTES)
            if not result.ok or result.data is None:
                continue
            ref = "/".join((*rel, name))
            for line in key_lines(result.data.decode("utf-8", "replace")):
                hits.append(KeyHit(ref, line))
                if len(hits) >= limit:
                    return hits
    return hits


__all__ = ["KEY_HITS_MAX", "KeyHit", "SCANNED_SUFFIXES", "SCAN_MAX_BYTES", "key_lines",
           "scan"]
