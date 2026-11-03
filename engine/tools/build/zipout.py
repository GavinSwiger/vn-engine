"""The build's zip file (F42 ``04-technical.md`` §3.1, PR-F42-19, SEC-F42-11).

Why this module exists: authors share one file, and players unzip it with whatever their PC
has. ``write_zip(folder, target)`` writes the finished build folder (in staging, made by the
build itself) as ``<folder name>.zip`` with one top folder, so unzipping always makes a fresh
folder holding the exe, ``_internal``, ``game``, ``licenses`` and ``README.txt``.

- Deflate; Zip64 only when a file or the archive needs it; UTF-8 names (``zipfile`` sets the
  UTF-8 flag for non-ASCII names); no extra fields beyond what Zip64 needs; empty comment.
- Entries are ``<folder name>/…`` with ``/`` only, every folder listed (``name/``) so empty
  folders survive, in sorted order. ``check_entry_name`` refuses ``..``, ``.``, a drive,
  a leading ``/``, ``\\``, a control character and a casefold duplicate; a link, junction,
  device or FIFO in the tree is refused too (the build never makes one). Refusals raise
  ``ZipNameError``: P5 reports it as a crash, since the build made the tree.
- The target is created exclusively (``"x"``): an existing file is never overwritten.

Child-only; imports the standard library and ``core.paths``.
"""

import os
import shutil
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Final

from engine.core import paths

CHUNK: Final = 1 << 20


class ZipNameError(Exception):
    """An entry name or tree entry the zip must not hold (SEC-F42-11)."""


def check_entry_name(name: str) -> None:
    """Raise ``ZipNameError`` unless ``name`` is a plain relative ``/`` path (a trailing
    ``/`` marks a folder)."""
    body = name[:-1] if name.endswith("/") else name
    if not body or body.startswith("/") or "\\" in body or ":" in body:
        raise ZipNameError(name)
    if any(unicodedata.category(ch) == "Cc" for ch in body):
        raise ZipNameError(name)
    if any(part in ("", ".", "..") for part in body.split("/")):
        raise ZipNameError(name)


def write_zip(folder: Path, target: Path) -> tuple[int, int]:
    """Zip the build ``folder`` into the new file ``target`` under ``<folder.name>/``.
    Returns ``(files, bytes)`` of the source files. Raises ``ZipNameError`` or ``OSError``;
    a partial ``target`` is left to the caller (it is inside staging)."""
    folder = Path(folder)
    entries = _entries(folder)
    seen: set[str] = set()
    for name, _ in entries:
        check_entry_name(name)
        key = name.casefold()
        if key in seen:
            raise ZipNameError(name)
        seen.add(key)
    files = total = 0
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED,
                         allowZip64=True) as archive:
        for name, path in entries:
            st = os.lstat(path)
            info = zipfile.ZipInfo(name, _zip_time(st.st_mtime))
            info.external_attr = (st.st_mode & 0xFFFF) << 16
            if name.endswith("/"):
                info.external_attr |= 0x10                     # MS-DOS directory bit
                archive.writestr(info, b"")
                continue
            info.compress_type = zipfile.ZIP_DEFLATED
            info.file_size = st.st_size                        # decides Zip64 up front
            with open(path, "rb") as source, archive.open(info, "w") as sink:
                shutil.copyfileobj(source, sink, CHUNK)
            files += 1
            total += st.st_size
    return files, total


def _zip_time(mtime: float) -> tuple[int, int, int, int, int, int]:
    """The local time for a zip entry, clamped to the format's 1980–2107 range."""
    try:
        stamp = time.localtime(mtime)[:6]
    except (OverflowError, OSError, ValueError):
        return (1980, 1, 1, 0, 0, 0)
    if stamp[0] < 1980:
        return (1980, 1, 1, 0, 0, 0)
    if stamp[0] > 2107:
        return (2107, 12, 31, 23, 59, 58)
    return stamp


def _entries(folder: Path) -> list[tuple[str, Path]]:
    """``(entry name, path)`` for the top folder and everything under it, sorted; folders
    end in ``/``. Iterative; nothing is followed."""
    top = folder.name
    found: list[tuple[str, Path]] = [(top + "/", folder)]
    stack: list[tuple[Path, str]] = [(folder, top)]
    while stack:
        current, prefix = stack.pop()
        with os.scandir(current) as listing:
            listed = [(entry.name, paths.dir_entry_kind(entry)) for entry in listing]
        for name, kind in listed:
            entry_name = f"{prefix}/{name}"
            if kind == paths.ENTRY_DIR:
                found.append((entry_name + "/", current / name))
                stack.append((current / name, entry_name))
            elif kind == paths.ENTRY_FILE:
                found.append((entry_name, current / name))
            else:
                raise ZipNameError(entry_name)
    found.sort(key=lambda item: item[0])
    return found


__all__ = ["ZipNameError", "check_entry_name", "write_zip"]
