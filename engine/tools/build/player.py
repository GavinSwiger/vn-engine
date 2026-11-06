"""Where a build's player runtime is, and whether Build is ready (F66; shared with Studio).

Why this module exists: every built game runs the same frozen player, the *runtime*
(``runtime.build_player_runtime`` makes it once with PyInstaller), so a build copies it instead
of running PyInstaller. Studio's Build dialog and the build child both need to know which
runtime a build would use and what Build still needs, so that answer lives here, in a module
Studio may import (it imports only ``core``, the shared build modules and the standard
library; ``07`` I-10):

- ``find_runtime()``: Studio's bundled one (``engine.core.paths.player_runtime_dir()``, the
  Studio app only) or, in a developer install, the cached one for this exact engine
  (``<Studio local folder>/player-runtime/<key>``, ``cached_runtime``). None when there is
  none yet.
- ``tool_status()``: Build's readiness: ready with a runtime; in Studio's app without one,
  ``B_NO_RUNTIME`` (a damaged install); in a developer install without one, whether
  PyInstaller is installed (``procs.tool_status``): the first build makes the runtime.
- ``can_install_tool()``: **Install build tool** is offered only in a developer install.
- ``runtime_key()``: a hash of everything a runtime is made from: the engine's shipped code
  and data, ``main.py``, ``engine/tools/build`` (spec, notices), Python's and pygame-ce's
  versions and the pinned PyInstaller. An engine change in a developer install makes a new
  runtime on the next build.
- ``read_meta(folder)``: ``vn-runtime.json`` of a folder that has a runtime's shape.

A runtime folder: ``player.exe``, ``_internal/``, ``licenses/`` and ``vn-runtime.json``
(format, engine version, key). Builds ship all but the last.
"""

import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Final

from engine.core import paths
from engine.tools.build import procs, tree

RUNTIME_FORMAT: Final = 1
PLAYER_STEM: Final = "player"
PLAYER_EXE: Final = PLAYER_STEM + ".exe"
CONTENTS_DIR: Final = tree.MARKER_DIR            # "_internal"
LICENSES_DIR: Final = "licenses"
META_NAME: Final = "vn-runtime.json"
META_MAX_BYTES: Final = 4096
ENTRY_SCRIPT: Final = "main.py"
CACHE_DIR: Final = "player-runtime"
KEY_CHARS: Final = 32                    # a cache folder's name: the key's first 32 hex
NO_RUNTIME: Final = "B_NO_RUNTIME"
IS_WINDOWS: Final = os.name == "nt"


def player_name() -> str:
    """The player exe's file name in a runtime on this platform."""
    return PLAYER_EXE if IS_WINDOWS else PLAYER_STEM


# --- The key ---------------------------------------------------------------------------------

def _hash_files(digest, base: Path, top: Path) -> None:
    """Every regular file under ``top`` (sorted, links not followed, ``__pycache__``
    skipped): its path relative to ``base`` and its bytes."""
    found: list[Path] = []
    for folder, dirs, files in os.walk(top, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        found.extend(Path(folder) / name for name in files)
    for path in sorted(found, key=lambda p: p.relative_to(base).as_posix()):
        if path.is_symlink() or not path.is_file():
            continue
        digest.update(path.relative_to(base).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")


def _pygame_version() -> str:
    import importlib.metadata
    try:
        return importlib.metadata.version("pygame-ce")
    except Exception:
        return "?"


def runtime_key(root: Path | None = None) -> str:
    """A SHA-256 hex digest of everything a runtime is made from (module docstring)."""
    base = Path(root) if root is not None else paths.engine_root()
    digest = hashlib.sha256()
    digest.update(json.dumps([RUNTIME_FORMAT, sys.version, platform.machine(),
                              _pygame_version(), procs.PYINSTALLER_VERSION]).encode())
    digest.update((base / ENTRY_SCRIPT).read_bytes())
    code = base / "engine"
    for path in sorted(code.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    for name in sorted(os.listdir(code)):
        folder = code / name
        if name in ("data", "__pycache__") or not folder.is_dir() or folder.is_symlink():
            continue
        _hash_files(digest, base, folder / "build" if name == "tools" else folder)
    _hash_files(digest, base, code / "data" / "fonts")
    digest.update((code / "data" / "icon.png").read_bytes())
    return digest.hexdigest()


# --- Finding one -----------------------------------------------------------------------------

def read_meta(folder: Path) -> dict | None:
    """``<folder>/vn-runtime.json`` when ``folder`` is a runtime (a real folder holding the
    player exe, ``_internal`` and ``licenses``, the meta file in the current format), else
    None."""
    folder = Path(folder)
    if not (tree.is_real_dir(folder) and tree.is_real_dir(folder / CONTENTS_DIR)
            and tree.is_real_dir(folder / LICENSES_DIR)):
        return None
    exe = folder / player_name()
    meta = folder / META_NAME
    try:
        if exe.is_symlink() or not exe.is_file() or meta.is_symlink() \
                or meta.stat().st_size > META_MAX_BYTES:
            return None
        value = json.loads(meta.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or value.get("format") != RUNTIME_FORMAT \
            or not isinstance(value.get("key"), str):
        return None
    return value


def bundled_runtime() -> Path | None:
    """Studio's own player folder (``paths.player_runtime_dir()``), if it is a runtime."""
    finder = getattr(paths, "player_runtime_dir", None)
    if finder is None:
        return None
    folder = finder()
    return Path(folder) if folder is not None and read_meta(folder) is not None else None


def cache_root() -> Path | None:
    """The developer runtime cache, ``<Studio local folder>/player-runtime`` (not made)."""
    base = paths.studio_user_dir(local=True)
    return None if base is None else base / CACHE_DIR


def cached_runtime(key: str | None = None) -> Path | None:
    """The cached runtime for ``key`` (default: this engine's), if there is one."""
    root = cache_root()
    if root is None:
        return None
    key = key or runtime_key()
    folder = root / key[:KEY_CHARS]
    meta = read_meta(folder)
    return folder if meta is not None and meta["key"] == key else None


def find_runtime() -> Path | None:
    """The runtime a build copies (module docstring); None when there is none yet."""
    bundled = bundled_runtime()
    if bundled is not None:
        return bundled
    if paths.is_frozen():
        return None
    return cached_runtime()


def can_install_tool() -> bool:
    """Whether **Install build tool** may be offered: a developer install only (Studio's
    app never runs pip)."""
    return not paths.is_frozen() and bundled_runtime() is None


def tool_status() -> procs.ToolStatus:
    """Build's readiness (module docstring)."""
    if find_runtime() is not None:
        return procs.ToolStatus(None)
    if paths.is_frozen():
        return procs.ToolStatus(NO_RUNTIME)
    return procs.tool_status()


__all__ = ["CACHE_DIR", "CONTENTS_DIR", "LICENSES_DIR", "META_NAME", "NO_RUNTIME",
           "PLAYER_EXE", "PLAYER_STEM", "RUNTIME_FORMAT", "bundled_runtime", "cache_root",
           "cached_runtime", "can_install_tool", "find_runtime", "player_name", "read_meta",
           "runtime_key", "tool_status"]
