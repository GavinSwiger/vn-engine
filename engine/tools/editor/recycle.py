"""Studio's Delete sends a file to the Windows Recycle Bin (``SHFileOperationW`` with
``FOF_ALLOWUNDO``, through ``ctypes``: no new dependency), so a mistaken Delete can be
restored from there. Off Windows there is no Recycle Bin call and ``AVAILABLE`` is False:
``files.delete_file`` then removes the file for good, after a confirmation that says so.

Only a regular file goes to the Recycle Bin. A link is removed as ``safefile.remove_file``
removes it (the link itself, never its target), and a real folder or any other entry is
refused, exactly as before.
"""

from __future__ import annotations

import ctypes
import os
import stat
import sys
from pathlib import Path

from engine.core import safefile

AVAILABLE = sys.platform == "win32"

FO_DELETE = 0x0003
FOF_SILENT = 0x0004                 # no progress window
FOF_NOCONFIRMATION = 0x0010         # Studio asked already
FOF_ALLOWUNDO = 0x0040              # to the Recycle Bin, not gone for good
FOF_NOERRORUI = 0x0400              # a failure comes back as a code, Studio words it
FOF_WANTNUKEWARNING = 0x4000        # if the drive has no Recycle Bin, Windows asks first
FLAGS = (FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
         | FOF_WANTNUKEWARNING)


class KEPT:
    """The author said No to Windows' "permanently delete?" question: nothing changed."""


def to_recycle_bin(path: Path) -> safefile.RemoveKind | type[KEPT]:
    """Send the file at ``path`` to the Recycle Bin. Returns ``safefile.RemoveKind`` (only
    ``REMOVED`` is success) or ``KEPT``; never raises ``OSError``."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return safefile.RemoveKind.MISSING
    except PermissionError:
        return safefile.RemoveKind.NO_PERMISSION
    except (OSError, ValueError):
        return safefile.RemoveKind.FAILED
    if not AVAILABLE or not stat.S_ISREG(st.st_mode) or _is_link(st):
        return safefile.remove_file(path)
    full = os.path.abspath(os.fspath(path))
    if any(ch in full for ch in "*?"):          # SHFileOperation would read a wildcard
        return safefile.RemoveKind.FAILED
    code, aborted = _shell_delete(full)
    if aborted:
        return KEPT if os.path.lexists(full) else safefile.RemoveKind.REMOVED
    if not os.path.lexists(full):
        return safefile.RemoveKind.REMOVED
    return safefile.RemoveKind.NO_PERMISSION if code else safefile.RemoveKind.FAILED


def _is_link(st: os.stat_result) -> bool:
    """A symlink or junction (left to ``safefile.remove_file``); a cloud placeholder such
    as a OneDrive file is a reparse point too, but not a link, so it is recycled."""
    return stat.S_ISLNK(st.st_mode) or (
        bool(getattr(st, "st_file_attributes", 0) & safefile._REPARSE_POINT)
        and getattr(st, "st_reparse_tag", 0) in safefile._LINK_TAGS)


def _shell_delete(full: str) -> tuple[int, bool]:
    """``SHFileOperationW(FO_DELETE, FLAGS)`` on the one absolute path ``full``: the
    return code (0 is success) and whether the operation was aborted."""
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _pack_ = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 1
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    source = ctypes.create_unicode_buffer(full + "\0")     # the list ends with two NULs
    op = SHFILEOPSTRUCTW(None, FO_DELETE, ctypes.cast(source, wintypes.LPCWSTR), None,
                         FLAGS, False, None, None)
    try:
        code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    except OSError:
        return -1, False
    return int(code), bool(op.fAnyOperationsAborted)


__all__ = ["AVAILABLE", "FLAGS", "KEPT", "to_recycle_bin"]
