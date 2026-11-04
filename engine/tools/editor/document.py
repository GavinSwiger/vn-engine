"""Editor documents: open a ``.vns`` file or ``config.toml``, re-encode edited text exactly,
save atomically (F44 ``04-technical.md`` §7.2, TR-F44-03, TR-F44-04; ADR-0008 and its
Amendment 1; F44 ``07`` I-1, I-2, I-13; F45 ``04`` §3, §7.5 Rename).

Pure Python, no Tk. A ``ScriptDocument`` remembers how its file was written (UTF-8 BOM,
line endings, final line break), so ``encode`` gives back the original bytes for an unedited
text and changes only the bytes of edited lines. ``save`` writes only a listed ``.vns`` file
that still lies inside the real ``<game>/script`` folder: the check is repeated at every
save, then ``core.safefile.write_atomic`` creates the temp file exclusively beside the target
and swaps it in (F12 ``04`` §3, I-17).

``open_config`` opens ``config.toml`` the same way (F45 PR-F45-22): it is saved only while it
is a regular file whose real path is ``<game>/config.toml`` itself. ``retarget`` moves an
open document to its new ref after Studio renames the file, keeping its unsaved text.
"""

import difflib
import errno
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from engine.core import safefile
from engine.core.errors import (
    AssetMissing,
    AssetNotFile,
    AssetRefError,
    AssetTooLarge,
    AssetUnreadable,
    UserFacingError,
)
from engine.core.constants import CONFIG_FILENAME, CONFIG_MAX_BYTES
from engine.core.paths import GamePaths
from engine.script.diagnostics import ScriptError
from engine.script.limits import (
    SCRIPT_FILE_MAX_BYTES,
    SCRIPT_WALK_MAX_DEPTH,
    SCRIPT_WALK_MAX_ENTRIES,
)
from engine.script.messages import format_message, show
from engine.script.source import decode_script, normalize_line_ends

SCRIPT_DIR = "script"
SCRIPT_SUFFIX = ".vns"
MAIN_REF = "script/main.vns"

# Read-only reasons shown in the editor area (UI-F44-12). ``07`` I-2 for the save-time one.
OUTSIDE_AT_OPEN = "This file links outside script/, so the editor won't change it."
OUTSIDE_AT_SAVE = "This file now links outside script/, so the editor won't change it."
NOT_VNS = "This file links to a file that isn't a .vns file, so the editor won't change it."
# config.toml's read-only reasons (F45 PR-F45-22, AC-F45-22 last row).
CONFIG_LINKED = "config.toml is a link or not a regular file, so Studio won't change it."
CONFIG_LINKED_AT_SAVE = ("config.toml is now a link or not a regular file, so Studio won't "
                         "change it.")
CONFIG_MISSING = "There is no config.toml in the game folder."
CONFIG_TOO_LARGE = "config.toml is larger than 1 MB, so Studio can't open it."
CONFIG_NOT_UTF8 = "config.toml isn't saved as UTF-8, so Studio can't open it."
# Mirrors F02's E08b wording for a file other than main.vns.
CANT_READ = ("{ref} couldn't be read. Check that another program isn't locking it and that "
             "you have permission to read it.")

# SaveError reasons (§7.2 Save step 3, AC-F44-14 (h), AC-F44-16).
REASON_READ_ONLY = "the file is read-only."
REASON_DISK_FULL = "the disk is full."
REASON_LOCKED = "the file is read-only or locked."
REASON_SYSTEM = "the system reported an error."
REASON_NOT_UTF8 = "it contains a character that can't be saved as UTF-8."
REASON_GONE = "the file was moved or deleted."

_BOM = "﻿"
_BOM_BYTES = b"\xef\xbb\xbf"
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_REPLACE_TRIES = 1                      # the editor reports a locked file at once (AC-F44-16)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class SaveError(UserFacingError):
    """A save that didn't happen. The file on disk is unchanged and no temp file is left.
    ``message`` is the whole dialog text: ``Couldn't save `<ref>`: <reason>`` (no path)."""

    def __init__(self, ref: str, reason: str) -> None:
        super().__init__(f"Couldn't save `{show(ref)}`: {reason}")
        self.ref = ref
        self.reason = reason


@dataclass
class ScriptDocument:
    """One opened ``.vns`` file (editor only, never saved anywhere)."""

    ref: str                                # "script/routes/hana.vns"
    real_path: Path                         # inside the real <game>/script
    bom: bool
    newline: str                            # dominant: "\n", "\r\n", or "\r" ("\n" if none)
    final_newline: bool
    old_lines: list[str] | None             # only for mixed line endings
    old_endings: list[str] | None           # per line; "" for a last line with no break
    stamp: tuple[int, int]                  # (st_mtime_ns, st_size) at load/save
    script_root: Path                       # the real <game>/script when the file was opened
                                            # (config.toml: the real game folder)
    dirty: bool = False
    config: bool = False                    # config.toml: saved only as <game>/config.toml
    # The text to put in the editor at load: lines joined by "\n", no final break, so the
    # line count equals F02's. The window may drop it (set "") once inserted.
    text: str = field(default="", repr=False)

    @property
    def mixed(self) -> bool:
        return self.old_lines is not None


# --- Listing (I-13) -------------------------------------------------------------------------

def list_scripts(paths: GamePaths) -> list[str]:
    """The ``.vns`` refs under ``script/`` in the file list's order: ``script/main.vns``
    first, then the others sorted by ``(ref.casefold(), ref)``. A ``script`` folder that
    leaves the game folder lists nothing."""
    try:
        walk = paths.walk_files(SCRIPT_DIR, suffix=SCRIPT_SUFFIX,
                                max_entries=SCRIPT_WALK_MAX_ENTRIES,
                                max_depth=SCRIPT_WALK_MAX_DEPTH)
    except AssetRefError:
        return []
    refs = sorted(walk.refs, key=lambda ref: (ref.casefold(), ref))
    if MAIN_REF in refs:
        refs.remove(MAIN_REF)
        refs.insert(0, MAIN_REF)
    return refs


# --- Open (§7.2 Open) -----------------------------------------------------------------------

def open_document(paths: GamePaths, ref: str) -> "ScriptDocument | ScriptError":
    """Read and decode ``ref``. A ``ScriptError`` means the file is shown read-only with
    ``error.format()``: F02's E05, E01a, E01b, E02 text, or one of the editor's reasons."""
    if not (ref.startswith(SCRIPT_DIR + "/") and ref.endswith(SCRIPT_SUFFIX)):
        raise ValueError("the editor opens only .vns files under script/")
    try:
        data = paths.read_file(ref, max_bytes=SCRIPT_FILE_MAX_BYTES)
        real = paths.resolve(ref)
        script_root = paths.resolve(SCRIPT_DIR)
    except AssetTooLarge:
        return ScriptError(format_message("E05", (ref,)), code="E05")
    except AssetRefError:
        return ScriptError(OUTSIDE_AT_OPEN, code="editor-outside")
    except (AssetMissing, AssetNotFile, AssetUnreadable):
        return ScriptError(CANT_READ.format(ref=show(ref)), code="editor-unreadable")
    decoded = decode_script(ref, data)
    if decoded.problem is not None:
        code, args, line = decoded.problem
        message = format_message(code, args)
        if code == "E01a" and decoded.text is not None:
            number = line or 1
            return ScriptError(message, code=code, file=ref, line=number,
                               source_line=_physical_line(decoded.text, number))
        return ScriptError(message, code=code)
    if not _inside(real.parent, script_root):
        return ScriptError(OUTSIDE_AT_OPEN, code="editor-outside")
    if not real.name.endswith(SCRIPT_SUFFIX):
        return ScriptError(NOT_VNS, code="editor-not-vns")
    return _make_document(ref, real, data, script_root, config=False)


def open_config(paths: GamePaths) -> "ScriptDocument | ScriptError":
    """Read ``config.toml`` for editing (F45 PR-F45-22). A ``ScriptError`` means it is shown
    read-only: a link (inside the game folder or not), a missing or too large file, or text
    that isn't UTF-8. The load errors themselves come from the check child."""
    ref = CONFIG_FILENAME
    try:
        data = paths.read_file(ref, max_bytes=CONFIG_MAX_BYTES, regular=True)
        real = paths.resolve(ref)
    except AssetTooLarge:
        return ScriptError(CONFIG_TOO_LARGE, code="editor-too-large")
    except (AssetRefError, AssetNotFile):
        return ScriptError(CONFIG_LINKED, code="editor-outside")
    except AssetMissing:
        return ScriptError(CONFIG_MISSING, code="editor-unreadable")
    except AssetUnreadable:
        return ScriptError(CANT_READ.format(ref=ref), code="editor-unreadable")
    if os.path.normcase(str(real)) != os.path.normcase(str(paths.root / ref)):
        return ScriptError(CONFIG_LINKED, code="editor-outside")
    try:
        (data[len(_BOM_BYTES):] if data.startswith(_BOM_BYTES) else data).decode("utf-8")
    except UnicodeDecodeError:
        return ScriptError(CONFIG_NOT_UTF8, code="E01a")
    return _make_document(ref, real, data, paths.root, config=True)


def _make_document(ref: str, real: Path, data: bytes, root: Path, *,
                   config: bool) -> "ScriptDocument | ScriptError":
    """The document for UTF-8 ``data``: BOM, line endings, final break, and stamp."""
    try:
        st = os.stat(real)
    except OSError:
        return ScriptError(CANT_READ.format(ref=show(ref)), code="editor-unreadable")

    bom = data.startswith(_BOM_BYTES)
    text = data[len(_BOM_BYTES):].decode("utf-8") if bom else data.decode("utf-8")
    del data
    newline, final, body, lines, endings = _split_lines(text)
    del text
    return ScriptDocument(
        ref=ref, real_path=real, bom=bom, newline=newline, final_newline=final,
        old_lines=lines, old_endings=endings,
        stamp=(st.st_mtime_ns, st.st_size), script_root=root, config=config, text=body)


def _split_lines(text: str) -> tuple[str, bool, str, list[str] | None, list[str] | None]:
    """``(newline, final_newline, "\\n"-joined text, old_lines, old_endings)`` for ``text``;
    the old lists only for mixed endings. One ending kind throughout (nearly every file)
    takes C-level string calls, so a large file never holds the GIL in a Python loop
    (F58 P0: 2 µs a line, which stalled Tk while the map's watch thread read big files)."""
    if "\r" not in text:
        return "\n", text.endswith("\n"), text[:-1] if text.endswith("\n") else text, \
            None, None
    crlf = text.count("\r\n")
    if crlf == text.count("\r") == text.count("\n"):
        text = text.replace("\r\n", "\n")
        return "\r\n", text.endswith("\n"), text[:-1] if text.endswith("\n") else text, \
            None, None
    return _split_lines_slow(text)


def _split_lines_slow(text: str) -> tuple[str, bool, str, list[str] | None, list[str] | None]:
    """The per-line read, for files that mix line endings (and the reference
    ``_split_lines`` is tested against)."""
    lines: list[str] = []
    endings: list[str] = []
    for match in _LINE_RE.finditer(text):
        piece = match.group()
        body = piece.rstrip("\r\n")
        lines.append(body)
        endings.append(piece[len(body):])
    mixed = len({ending for ending in endings if ending}) > 1
    return (_dominant(endings), bool(endings) and endings[-1] != "", "\n".join(lines),
            lines if mixed else None, endings if mixed else None)


def _physical_line(text: str, number: int) -> str:
    """Line ``number`` (1-based) of ``"\\n"``-separated text, without splitting it all."""
    parts = text.split("\n", number)
    return parts[number - 1] if number <= len(parts) else ""


def _dominant(endings: list[str]) -> str:
    """The most common line ending; a tie goes to the one seen first. "\\n" if none."""
    counts: dict[str, int] = {}
    for ending in endings:
        if ending:
            counts[ending] = counts.get(ending, 0) + 1
    if not counts:
        return "\n"
    return max(counts, key=counts.__getitem__)   # dicts keep first-seen order for ties


def _inside(path: Path, root: Path) -> bool:
    """``path`` is ``root`` or below it (both real paths), compared like GamePaths.contains."""
    key = os.path.normcase(str(path))
    root_key = os.path.normcase(str(root))
    prefix = root_key if root_key.endswith(os.sep) else root_key + os.sep
    return key == root_key or key.startswith(prefix)


# --- Encode (§7.2 Encode) -------------------------------------------------------------------

def encode(doc: ScriptDocument, text: str) -> bytes:
    """The file bytes for the editor's ``text`` (from ``Text.get("1.0", "end-1c")``).
    Unedited text gives the original bytes. Raises SaveError for a lone surrogate."""
    return _encode(doc, text)[0]


def _encode(doc: ScriptDocument, text: str) -> tuple[bytes, list[str], list[str] | None]:
    """(bytes, lines, per-line endings or None when the endings aren't mixed)."""
    try:
        # Tk 8.6 may hand back characters outside the BMP as surrogate pairs: join them.
        text = text.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        raise SaveError(doc.ref, REASON_NOT_UTF8) from None
    lines = normalize_line_ends(text).split("\n")
    endings: list[str] | None = None
    if doc.old_lines is None or doc.old_endings is None:
        out = doc.newline.join(lines) + (doc.newline if doc.final_newline else "")
    else:
        endings = _mixed_endings(doc.old_lines, doc.old_endings, lines, doc.newline)
        out = "".join(line + ending for line, ending in zip(lines, endings))
    if doc.bom:
        out = _BOM + out
    try:
        data = out.encode("utf-8")
    except UnicodeEncodeError:
        raise SaveError(doc.ref, REASON_NOT_UTF8) from None
    return data, lines, endings


def _mixed_endings(old_lines: list[str], old_endings: list[str], lines: list[str],
                   newline: str) -> list[str]:
    """§7.2 Encode step 3: a line in an ``equal`` block keeps its old ending, any other
    line gets ``newline``; no line but the last is left without a break; a changed last
    line gets the old last line's ending.

    One refinement, so an edited line keeps its own ending (AC-F44-14 (c)): in a
    ``replace`` block, the new lines take the old lines' endings pairwise, in order; only
    the lines past the shorter side get ``newline``."""
    endings = [newline] * len(lines)
    kept = [False] * len(lines)
    matcher = difflib.SequenceMatcher(None, old_lines, lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                endings[j1 + k] = old_endings[i1 + k]
                kept[j1 + k] = True
        elif tag == "replace":
            for k in range(min(i2 - i1, j2 - j1)):
                endings[j1 + k] = old_endings[i1 + k]
    last = len(lines) - 1
    for j in range(last):
        if not endings[j]:
            endings[j] = newline
    if not kept[last]:
        endings[last] = old_endings[-1] if old_endings else ""
    return endings


# --- Save (§7.2 Save, I-2) ------------------------------------------------------------------

def save(doc: ScriptDocument, text: str) -> None:
    """Write ``encode(doc, text)`` over the file atomically. Raises SaveError; on failure
    the original bytes stay and no temp file is left. On success the stamp is updated and
    ``dirty`` is cleared."""
    data, lines, endings = _encode(doc, text)
    target = _checked_target(doc)
    if not os.access(target, os.W_OK):
        raise SaveError(doc.ref, REASON_READ_ONLY)
    try:
        mode = stat.S_IMODE(os.lstat(target).st_mode)     # the file keeps its permissions
        # A temp file whose every random name is taken raises FileExistsError: "the system
        # reported an error", as before the lift.
        safefile.write_atomic(target, (data,), mode=mode, replace_tries=_REPLACE_TRIES,
                              token=_temp_token, write=_write_all)
    except OSError as exc:
        raise SaveError(doc.ref, _reason(exc)) from None
    try:
        st = os.stat(target)
        doc.stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        doc.stamp = (0, -1)                 # unknown: the next outside-change check reloads
    if endings is not None:
        doc.old_lines = lines
        doc.old_endings = endings
        doc.final_newline = endings[-1] != ""
    doc.dirty = False


def _checked_target(doc: ScriptDocument) -> Path:
    """I-2: re-resolve the target's folder, require it inside the real ``script`` folder
    seen at open (``config.toml``: exactly the real game folder, F45), and require the
    target to be a regular file (not a link or junction)."""
    outside = CONFIG_LINKED_AT_SAVE if doc.config else OUTSIDE_AT_SAVE
    try:
        folder = doc.real_path.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        raise SaveError(doc.ref, REASON_GONE) from None
    if doc.config:
        if (os.path.normcase(str(folder)) != os.path.normcase(str(doc.script_root))
                or doc.real_path.name != CONFIG_FILENAME):
            raise SaveError(doc.ref, outside)
    else:
        if not _inside(folder, doc.script_root):
            raise SaveError(doc.ref, outside)
        if not doc.real_path.name.endswith(SCRIPT_SUFFIX):
            raise SaveError(doc.ref, outside)
    target = folder / doc.real_path.name
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        raise SaveError(doc.ref, REASON_GONE) from None
    except OSError as exc:
        raise SaveError(doc.ref, _reason(exc)) from None
    if not stat.S_ISREG(st.st_mode) or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
        raise SaveError(doc.ref, outside)
    return target


# --- Retarget (F45 04 §7.5 Rename step 3) ---------------------------------------------------

def retarget(doc: ScriptDocument, paths: GamePaths, new_ref: str) -> None:
    """Point an open document at ``new_ref`` after Studio renamed its file in the same
    folder. The unsaved text and ``dirty`` stay; the next save writes the new file (and is
    checked as every save is). Raises ``UserFacingError`` when the new file can't be found
    inside the game folder."""
    paths.invalidate_listings()
    real = paths.resolve(new_ref)
    doc.ref = new_ref
    doc.real_path = real
    try:
        st = os.stat(real)
        doc.stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        doc.stamp = (0, -1)


def _temp_token() -> str:
    """8 random hex digits for the temp file's name (a seam: tests patch it)."""
    return safefile.temp_token()


def _write_all(fd: int, data: bytes) -> None:
    """Write every byte of ``data`` (a seam: tests patch it)."""
    safefile.write_all(fd, data)


def _reason(exc: OSError) -> str:
    if exc.errno == errno.ENOSPC:
        return REASON_DISK_FULL
    if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
        return REASON_LOCKED
    return REASON_SYSTEM
