"""Build game…'s remembered choices, ``<game>/.studio/build.json`` (F42 ``04-technical.md``
§3.2, PR-F42-21, SEC-F42-08, D6; ``07`` I-12; ADR-0008 Amendment 2 as amended by F42).

Why this module exists: an author builds the same game many times, so the dialog should open
with last time's *Save to*, zip choice and Game ID. The file travels with the project when it
is shared, so it must never hold the author's home path, and a planted one is only a
suggestion: every value passes the dialog's own checks again. The CLI never reads it.

- ``read_prefs(game_root)`` → ``BuildPrefs`` (never raises). Missing, damaged, over 64 KiB,
  or not a regular file (link, junction): the defaults. A wrongly typed value keeps its
  default. ``save_to`` is resolved against the game folder; an absolute one is used only if
  ``redact()`` leaves it unchanged (no home path), and one inside the game folder (or holding
  it) is ignored: the default is ``<game parent>/builds`` (D6). ``last_id`` must pass
  ``is_valid_app_id``.
- ``write_prefs(game_root, prefs)`` → bool. *Save to* is stored relative to the game folder
  (``../builds``, ``/`` separators) when on the same volume, else absolute only if
  ``redact()`` leaves it unchanged, else not at all. Written like ``studiostate``:
  ``.studio`` a real folder, the target missing or regular, unchanged bytes skipped,
  ``safefile.write_atomic`` with the stamp checked, a new file's mode ``0o666 & ~umask``. A
  failed write is silent (False); Studio never deletes the file.

Pure Python: no Tk, no pygame. Imports ``core`` and the standard library (ADR-0008).
"""

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core import safefile
from engine.core.paths import is_valid_app_id
from engine.core.redact import redact

PREFS_DIR: Final = ".studio"
PREFS_NAME: Final = "build.json"
PREFS_MAX_BYTES: Final = 64 * 1024
SAVE_TO_MAX_CHARS: Final = 1024
DEFAULT_FOLDER: Final = "builds"


def _umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


NEW_FILE_MODE: Final = 0o666 & ~_umask() if os.name == "posix" else None


@dataclass(frozen=True, slots=True)
class BuildPrefs:
    """``save_to``: an absolute folder (None = the default). ``zip``: make the zip.
    ``last_id``: the Game ID of the last build (for ``ID_CHANGED``)."""

    save_to: Path | None = None
    zip: bool = True
    last_id: str | None = None


def prefs_path(game_root: Path) -> Path:
    return Path(game_root) / PREFS_DIR / PREFS_NAME


def default_save_to(game_root: Path) -> Path:
    """D6: a ``builds`` folder next to the game folder."""
    return Path(os.path.abspath(game_root)).parent / DEFAULT_FOLDER


def save_to_or_default(game_root: Path, prefs: BuildPrefs) -> Path:
    return prefs.save_to if prefs.save_to is not None else default_save_to(game_root)


# --- Reading ---------------------------------------------------------------------------------

def read_prefs(game_root: Path) -> BuildPrefs:
    """The remembered choices, or the defaults. Never raises."""
    try:
        data = _read_bytes(Path(game_root))
        return BuildPrefs() if data is None else decode_prefs(data, Path(game_root))
    except Exception:
        return BuildPrefs()


def _read_bytes(game_root: Path) -> bytes | None:
    folder = game_root / PREFS_DIR
    if not os.path.lexists(folder) or not safefile.ensure_real_dir(folder, create=False):
        return None
    target = folder / PREFS_NAME
    if safefile.entry_kind(target) is not safefile.EntryKind.REGULAR:
        return None
    result = safefile.read_regular(target, PREFS_MAX_BYTES)
    return result.data if result.ok else None


def decode_prefs(data: bytes, game_root: Path) -> BuildPrefs:
    """Strict UTF-8 JSON object; each known key checked, anything else ignored."""
    if len(data) > PREFS_MAX_BYTES:
        return BuildPrefs()
    try:
        doc = json.loads(data.decode("utf-8", errors="strict"),
                         parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return BuildPrefs()
    if not isinstance(doc, dict):
        return BuildPrefs()
    zip_value = doc.get("zip")
    last_id = doc.get("last_id")
    return BuildPrefs(save_to=_decode_save_to(doc.get("save_to"), game_root),
                      zip=zip_value if type(zip_value) is bool else True,
                      last_id=last_id if is_valid_app_id(last_id) else None)


def _reject_constant(name: str) -> object:
    raise ValueError(name)


def _decode_save_to(value: object, game_root: Path) -> Path | None:
    if not isinstance(value, str) or not value or len(value) > SAVE_TO_MAX_CHARS \
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    if os.path.isabs(value):
        if redact(value) != value:
            return None
        folder = os.path.normpath(value)
    elif os.path.splitdrive(value)[0] or value.startswith(("/", "\\")):
        return None                                  # drive-relative or rooted: not ours
    else:
        folder = os.path.normpath(os.path.join(os.path.abspath(game_root), value))
    if _overlaps(Path(folder), Path(os.path.abspath(game_root))):
        return None
    return Path(folder)


def _overlaps(folder: Path, game_root: Path) -> bool:
    """``folder`` is the game folder, inside it, or holds it (lexically and by real path;
    the build's own ``B_OUT_INSIDE`` check runs again before anything is written)."""
    pairs = [(folder, game_root)]
    try:
        pairs.append((Path(os.path.realpath(folder)), Path(os.path.realpath(game_root))))
    except (OSError, ValueError):
        pass
    for a, b in pairs:
        ka, kb = os.path.normcase(str(a)), os.path.normcase(str(b))
        if ka == kb or ka.startswith(kb.rstrip("\\/") + os.sep) \
                or kb.startswith(ka.rstrip("\\/") + os.sep):
            return True
    return False


# --- Encoding and writing --------------------------------------------------------------------

def stored_save_to(save_to: Path | None, game_root: Path) -> str | None:
    """What ``build.json`` keeps for ``save_to``: relative (``/``) on the same volume, else
    the absolute path only if ``redact()`` leaves it unchanged, else None."""
    if save_to is None:
        return None
    absolute = os.path.abspath(save_to)
    try:
        relative = os.path.relpath(absolute, os.path.abspath(game_root))
    except ValueError:                               # another drive on Windows
        relative = None
    if relative is not None:
        return relative.replace(os.sep, "/")
    return absolute if redact(absolute) == absolute else None


def encode_prefs(prefs: BuildPrefs, game_root: Path) -> bytes:
    doc: dict[str, object] = {}
    stored = stored_save_to(prefs.save_to, game_root)
    if stored is not None:
        doc["save_to"] = stored
    doc["zip"] = bool(prefs.zip)
    if is_valid_app_id(prefs.last_id):
        doc["last_id"] = prefs.last_id
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_prefs(game_root: Path, prefs: BuildPrefs) -> bool:
    """Write ``prefs``; True when written or unchanged. A failure is silent (False)."""
    try:
        return _write(Path(game_root), encode_prefs(prefs, Path(game_root)))
    except Exception:
        return False


def _write(game_root: Path, data: bytes) -> bool:
    folder = game_root / PREFS_DIR
    if not safefile.ensure_real_dir(folder):
        return False
    target = folder / PREFS_NAME
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        st = None
    if st is not None:
        if not safefile.is_regular(st):
            return False
        old = safefile.read_regular(target, PREFS_MAX_BYTES)
        if old.ok and old.data == data:
            return True
        mode: int | None = stat.S_IMODE(st.st_mode) if os.name == "posix" else None
        expected: safefile.Stamp | None = safefile.Stamp.of(st)
    else:
        mode, expected = NEW_FILE_MODE, None
    try:
        safefile.write_atomic(target, (data,), check=True, expected=expected, mode=mode,
                              replace_tries=1)
    except (safefile.TargetChanged, OSError):
        return False
    return True


__all__ = ["BuildPrefs", "DEFAULT_FOLDER", "PREFS_DIR", "PREFS_MAX_BYTES", "PREFS_NAME",
           "decode_prefs", "default_save_to", "encode_prefs", "prefs_path", "read_prefs",
           "save_to_or_default", "stored_save_to", "write_prefs"]
