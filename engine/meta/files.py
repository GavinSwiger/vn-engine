"""The meta files folder: the one sandbox helper for ``<game>/characters/`` (F31 ``04`` §4.3,
§6.1; ``05`` SEC-F31-01, -02, -04; invariant 9 (a), (b)).

Why this module exists: a story may check for, read, write, and delete a few files beside the
game, so players find them there. That folder is untrusted (players and anyone with write
access to the game folder can put links, junctions, hard links, folders, or huge files in
it), so every story-driven check goes through ``MetaFolder``: a fixed root, the script's
literal names only (``require`` refuses any other before a file call), the dev real-folder
rule on every call, and no link ever followed. Changes are never made here: ``app`` turns
names ``require`` returned into ``FileWrite``/``FileRemove`` jobs of the writer's ``meta``
owner.

Imports only the standard library and ``engine.core``; only ``app/metafiles.py`` imports it
(the import-rule test), and it never imports ``meta.username``. The only direct ``os`` call
is ``lstat``; reads go through ``safefile``. Nothing here logs, and no ``repr`` holds a path.
"""

import enum
import os
import re
from pathlib import Path

from engine.core import safefile
from engine.core.constants import META_NAMES_MAX, META_READ_MAX_BYTES, META_SHOWN
from engine.core.paths import is_meta_name
from engine.core.safefile import EntryKind, ReadResult


class RootState(enum.Enum):
    """``MetaFolder.root_state()``."""

    OK = "ok"                    # a real folder that is its own real path (dev rule)
    MISSING = "missing"          # no entry at the root
    BAD = "bad"                  # a link, junction, reparse point, file, or reached via one
    UNREADABLE = "unreadable"    # ``lstat`` failed for another reason


class MetaFolder:
    """The folder ``root`` (absolute) and its allow-list ``names`` (each ``is_meta_name``, at
    most ``META_NAMES_MAX``; else ``ValueError``). Every method that takes a name calls
    ``require`` before any file call, and paths are only ``root / name``."""

    __slots__ = ("root", "names", "_temps")

    def __init__(self, root: Path, names: frozenset[str]) -> None:
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("the meta files root must be an absolute Path")
        names = frozenset(names)
        if len(names) > META_NAMES_MAX:
            raise ValueError("too many meta file names")
        if not all(is_meta_name(name) for name in names):
            raise ValueError("not a meta file name")
        self.root = root
        self.names = names
        # The listed names as one alternation, for ``remove_stale_temps``'s target pattern.
        self._temps = "|".join(re.escape(name) for name in sorted(names)) or None

    def __repr__(self) -> str:
        return f"MetaFolder({META_SHOWN.rstrip('/')})"          # never the path (SEC-F31-07)

    def require(self, name: str) -> str:
        """``name`` when it is one of ``names``; ``ValueError`` (a programmer error) without
        any file call otherwise."""
        if type(name) is not str or name not in self.names:
            raise ValueError("not a listed meta file name")
        return name

    def root_state(self) -> RootState:
        """``lstat(root)``: missing → MISSING; another error → UNREADABLE; else OK when
        ``ensure_real_dir(root, release=False, create=False)`` holds (a real folder that is
        its own real path), BAD otherwise. Never creates anything; never raises."""
        try:
            os.lstat(self.root)
        except FileNotFoundError:
            return RootState.MISSING
        except (OSError, ValueError):
            return RootState.UNREADABLE
        if safefile.ensure_real_dir(self.root, release=False, create=False):
            return RootState.OK
        return RootState.BAD

    def exists(self, name: str) -> bool:
        """A regular file at ``name`` by ``lstat`` (a link, folder, or error is False)."""
        return safefile.is_regular_at(self.root / self.require(name))

    def read(self, name: str) -> ReadResult:
        """``read_regular(root / name, META_READ_MAX_BYTES, single_link=True)``: a regular
        file of at most 16 KiB whose open handle counts one link (else ``LINKED``)."""
        return safefile.read_regular(self.root / self.require(name), META_READ_MAX_BYTES,
                                     single_link=True)

    def entry_kind(self, name: str) -> EntryKind:
        """MISSING, REGULAR, or OTHER by one ``lstat`` (no follow); a failure path only."""
        return safefile.entry_kind(self.root / self.require(name))

    def stale_cleanup(self) -> int:
        """Remove old temp files of the listed names (``.<name>.<8 hex>.tmp``, regular files
        only, at most 16 of at most 1,000 entries examined); the folder's only listing.
        Nothing happens unless ``root_state()`` is OK. Returns the number removed."""
        if self._temps is None or self.root_state() is not RootState.OK:
            return 0
        return safefile.remove_stale_temps(self.root, target_pattern=self._temps)


__all__ = ["MetaFolder", "RootState"]
