"""The build's file walkers: copy the game folder, make and remove staging, test and replace
an earlier build (F42 ``04`` §7.2, §7.3; PR-F42-05, -12, -13, -22; SEC-F42-06, -07).

Why this module exists: a build reads a folder an author may have filled with links and odd
names, and creates, renames and deletes in *Save to*. Every such file-system walk is here, in
one no-follow, contained, capped form, beside ``core/safefile`` (ADR-0008 Amendment 3).

- **Copy** (``prescan``, ``copy_game``): an iterative walk over the game root's real path.
  Entries are classified from the listing without following (``paths.dir_entry_kind``; a
  reparse point that resolves to itself, such as a cloud placeholder, counts as real) and
  ``rules.classify`` leaves entries out (recorded once, top-most, never descended into).
  Folders: ``os.mkdir``, and each listed folder must still be its own real path before it is
  listed. Files: ``safefile.open_regular``, whose ``st_dev``/``st_ino`` must match this walk's
  ``lstat``; at most the ``fstat`` size is copied in 1 MiB chunks into an exclusive create; a
  short read or growth is ``B_COPY_FAILED``. The 50,000-entry, 32-level and 8 GB caps count
  during the walk (``B_TOO_BIG``). A shipped file whose path inside the build folder is over
  160 characters counts toward ``LONG_PATHS``.
- **Staging** (``make_staging``, ``Staging``): ``.<folder>.building-<8 hex>`` by ``os.mkdir``,
  with the staging marker written first and held open while the build runs (on Windows an
  open file can't be deleted, so ``sweep_stale`` can't remove a running build's staging).
- **Delete** (``remove_tree``): iterative post-order; links, junctions and other non-folder
  entries go through ``safefile.remove_file`` (the link, never its target); every folder
  listed must have its real path under the root's; no ``shutil.rmtree``; capped; on failure
  it stops and returns the entry it couldn't remove.
- **Earlier builds** (``is_earlier_build``, ``zip_is_earlier_build``, ``find_earlier_build``,
  ``install_build``, ``sweep_stale``): the strict marker test; rename aside
  (``.<name>.old-<8 hex>``), move in, delete the asides; stale staging and asides older
  than 60 s are swept.
- ``real_inside``: real-path containment (normcase) for ``B_OUT_INSIDE``.

Failures a build reports raise ``texts.BuildStopped``; its values name entries relative to the
game folder or *Save to*, never full paths. Other ``OSError``s (creating staging) propagate for
the step machine to map. Shared module (``tools/editor`` may import it): standard library,
``core``, ``script``.
"""

import json
import os
import re
import secrets
import stat
import struct
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from engine.core import safefile
from engine.core.paths import (ENTRY_DIR, ENTRY_FILE, ENTRY_LINK, dir_entry_kind,
                               is_listed_path)
from engine.tools.build import texts
from engine.tools.build.rules import LeftOut, classify

# --- Caps and names (01 §4 edge cases; SEC-F42-06 d, -07) ------------------------------------

MAX_ENTRIES = 50_000
MAX_DEPTH = 32
MAX_BYTES = 8 * 1024 ** 3
COPY_CHUNK = 1 << 20
LONG_PATH_CHARS = 160
REMOVE_MAX_ENTRIES = 200_000         # a build is at most 50,000 game entries plus the bundle
SWEEP_MAX_EXAMINED = 1000            # entries of *Save to* looked at by one sweep
STALE_AGE_S = 60.0
NAME_ATTEMPTS = 6                    # random names tried for staging and aside entries

MARKER_DIR = "_internal"
MARKER_NAME = "vn-build.json"
MARKER_MAX_BYTES = 4096
MARKER_FORMAT = 1
_MARKER_TEXT_KEYS = ("engine", "id", "version", "built")

STAGING_MARKER = "vn-build-staging"
STAGING_MARKER_BYTES = b"vn-engine build staging folder\n"
STAGING_RE = re.compile(r"\.(?P<folder>.+)\.building-[0-9a-f]{8}")
ASIDE_RE = re.compile(r"\.(?P<name>.+)\.old-[0-9a-f]{8}")

ZIP_MAX_ENTRIES = 200_000
ZIP_DIR_MAX_BYTES = 64 << 20
_EOCD = struct.Struct("<4s4H2LH")
_EOCD64_LOCATOR = struct.Struct("<4sLQL")
_EOCD64 = struct.Struct("<4sQ2H2L4Q")
_EOCD_SEARCH = _EOCD.size + 0xFFFF

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CREATE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)


# --- Small checks ----------------------------------------------------------------------------

def _real(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _within(child: str, parent: str) -> bool:
    """Both already ``_real``: ``child`` is ``parent`` or below it."""
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def real_inside(child: Path, parent: Path) -> bool:
    """Whether ``child``'s real path is ``parent``'s real path or inside it (normcase; links
    and junctions resolved, so neither can hide containment). Missing tails resolve
    lexically. ``B_OUT_INSIDE`` asks it both ways (SEC-F42-06 g)."""
    return _within(_real(child), _real(parent))


def is_real_dir(path: Path) -> bool:
    """A real folder by ``lstat``: not a link, junction or other reparse point."""
    try:
        st = os.lstat(path)
    except (OSError, ValueError):
        return False
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return False
    if getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
        return False
    return not os.path.isjunction(path)


def _age(path: Path, now: float) -> float:
    try:
        return now - os.lstat(path).st_mtime
    except OSError:
        return 0.0


def _create(path: Path) -> int:
    return os.open(path, _CREATE_FLAGS, 0o666)


# --- The copy walk (§7.2, SEC-F42-06) ---------------------------------------------------------

@dataclass
class CopyResult:
    """What a walk found or copied. ``left_out`` in walk order (names sorted per folder);
    ``long_paths`` counts shipped files over ``LONG_PATH_CHARS`` and ``long_path_example`` is
    the first one's game-relative ref."""
    files: int = 0
    folders: int = 0
    bytes: int = 0
    left_out: list[LeftOut] = field(default_factory=list)
    long_paths: int = 0
    long_path_example: str | None = None


def _too_big(reason: str) -> texts.BuildStopped:
    return texts.BuildStopped("B_TOO_BIG", reason=reason)


def _copy_failed(ref: str) -> texts.BuildStopped:
    return texts.BuildStopped("B_COPY_FAILED", ref=ref)


def _real_root(game_root: Path) -> Path:
    try:
        root = game_root.resolve(strict=True)
    except (OSError, RuntimeError):
        raise _copy_failed(game_root.name) from None
    if not is_real_dir(root):
        raise _copy_failed(game_root.name)
    return root


def _kind(entry: os.DirEntry, path: Path) -> int:
    """``dir_entry_kind``, except that a reparse point resolving to itself (a cloud
    placeholder) is classified by ``lstat`` as the folder or file it is."""
    kind = dir_entry_kind(entry)
    if kind != ENTRY_LINK or not is_listed_path(path):
        return kind
    try:
        st = os.lstat(path)
    except OSError:
        return kind
    if stat.S_ISDIR(st.st_mode) and not os.path.isjunction(path):
        return ENTRY_DIR
    return ENTRY_FILE if stat.S_ISREG(st.st_mode) else kind


def _still_listed_dir(folder: Path) -> bool:
    """Right before it is listed, a walked folder is still a folder by ``lstat`` and its own
    real path (not swapped for a link or junction since its parent was listed)."""
    try:
        st = os.lstat(folder)
    except (OSError, ValueError):
        return False
    return (stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)
            and not os.path.isjunction(folder) and is_listed_path(folder))


def _walk(root: Path, result: CopyResult) -> Iterator[tuple[tuple[str, ...], Path, int, int]]:
    """Kept entries in depth-first, name-sorted order as (parts, path, kind, listed size);
    a folder comes before its contents. Left-out entries go to ``result.left_out``. The
    entry and depth caps count here; ``B_COPY_FAILED`` if a folder can't be listed or is no
    longer its own real path."""
    stack: list[tuple[tuple[str, ...], Path]] = [((), root)]
    entries = 0
    while stack:
        parts, folder = stack.pop()
        if parts and not _still_listed_dir(folder):
            raise _copy_failed("/".join(parts))
        listed: list[os.DirEntry] = []
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    entries += 1
                    if entries > MAX_ENTRIES:
                        raise _too_big(texts.TOO_BIG_ENTRIES)
                    listed.append(entry)
        except OSError:
            raise _copy_failed("/".join(parts) or root.name) from None
        listed.sort(key=lambda e: e.name)
        folders: list[tuple[tuple[str, ...], Path]] = []
        for entry in listed:
            child = parts + (entry.name,)
            path = Path(entry.path)
            kind = _kind(entry, path)
            left = classify(child, kind)
            if left is not None:
                result.left_out.append(left)
                continue
            if kind == ENTRY_DIR:
                if len(child) > MAX_DEPTH:
                    raise _too_big(texts.TOO_BIG_DEPTH)
                yield child, path, kind, 0
                folders.append((child, path))
            else:
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    raise _copy_failed("/".join(child)) from None
                yield child, path, kind, size
        stack.extend(reversed(folders))


def _count_file(result: CopyResult, ref: str, size: int, long_prefix: str) -> None:
    result.files += 1
    result.bytes += size
    if result.bytes > MAX_BYTES:
        raise _too_big(texts.TOO_BIG_BYTES)
    if len(long_prefix) + len(ref) > LONG_PATH_CHARS:
        result.long_paths += 1
        if result.long_path_example is None:
            result.long_path_example = ref


def prescan(game_root: Path, *, long_prefix: str = "") -> CopyResult:
    """The copy walk without copying: counts, sizes (from the listing), left-out entries and
    long paths. Raises ``BuildStopped`` (``B_TOO_BIG``, ``B_COPY_FAILED``)."""
    result = CopyResult()
    for parts, _path, kind, size in _walk(_real_root(game_root), result):
        if kind == ENTRY_DIR:
            result.folders += 1
        else:
            _count_file(result, "/".join(parts), size, long_prefix)
    return result


def copy_game(game_root: Path, dest: Path, *, long_prefix: str = "",
              on_file: Callable[[CopyResult], None] | None = None) -> CopyResult:
    """Copy the game folder's shipped entries into ``dest`` (made here by ``os.mkdir``; its
    parent must exist). ``long_prefix`` is what precedes a game-relative ref inside the build
    (``<folder name>/game/``) for the ``LONG_PATHS`` count. ``on_file`` is called after each
    file. Raises ``BuildStopped`` (``B_TOO_BIG``, ``B_COPY_FAILED``); what was copied stays in
    ``dest`` for the caller's staging cleanup."""
    root = _real_root(game_root)
    try:
        os.mkdir(dest)
    except OSError:
        raise _copy_failed(game_root.name) from None
    result = CopyResult()
    for parts, path, kind, _size in _walk(root, result):
        ref = "/".join(parts)
        target = dest.joinpath(*parts)
        if kind == ENTRY_DIR:
            try:
                os.mkdir(target)
            except OSError:
                raise _copy_failed(ref) from None
            result.folders += 1
            continue
        copied = _copy_file(path, target, ref, MAX_BYTES - result.bytes)
        _count_file(result, ref, copied, long_prefix)
        if on_file is not None:
            on_file(result)
    return result


def _copy_file(source: Path, target: Path, ref: str, budget: int) -> int:
    """Copy one listed file by handle (SEC-F42-06 b, c); returns the bytes copied."""
    try:
        listed = os.lstat(source)
    except OSError:
        raise _copy_failed(ref) from None
    if not safefile.is_regular(listed):
        raise _copy_failed(ref)
    opened = safefile.open_regular(source)
    if isinstance(opened, safefile.ReadResult):
        raise _copy_failed(ref)
    fd, fst = opened
    try:
        if (fst.st_dev, fst.st_ino) != (listed.st_dev, listed.st_ino):
            raise _copy_failed(ref)
        if fst.st_size > budget:
            raise _too_big(texts.TOO_BIG_BYTES)
        try:
            out = _create(target)
        except OSError:
            raise _copy_failed(ref) from None
        try:
            remaining = fst.st_size
            while remaining:
                chunk = os.read(fd, min(COPY_CHUNK, remaining))
                if not chunk:                                   # shrank: a short read
                    raise _copy_failed(ref)
                safefile.write_all(out, chunk)
                remaining -= len(chunk)
            if os.read(fd, 1):                                  # grew while copying
                raise _copy_failed(ref)
        except OSError:
            raise _copy_failed(ref) from None
        finally:
            os.close(out)
    finally:
        os.close(fd)
    return fst.st_size


# --- Removing a tree (SEC-F42-07 d) -----------------------------------------------------------

def remove_tree(path: Path, *, max_entries: int = REMOVE_MAX_ENTRIES) -> Path | None:
    """Delete ``path`` and everything under it without following any link: None when nothing
    is left, else the first entry that couldn't be removed (the walk stops there). A link or
    junction at ``path`` itself is removed as a link. Every folder listed must have its real
    path under ``path``'s; at most ``max_entries`` entries are removed."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return path
    if not is_real_dir(path):
        return None if safefile.remove_file(path).gone else path
    root = _real(path)
    stack: list[tuple[Path, bool]] = [(path, False)]
    removed = 0
    while stack:
        folder, emptied = stack.pop()
        if emptied:
            try:
                os.rmdir(folder)
            except FileNotFoundError:
                pass
            except OSError:
                return folder
            continue
        if not is_real_dir(folder) or not _within(_real(folder), root):
            return folder
        stack.append((folder, True))
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    removed += 1
                    child = Path(entry.path)
                    if removed > max_entries:
                        return child
                    if dir_entry_kind(entry) == ENTRY_DIR:
                        stack.append((child, False))
                    elif not safefile.remove_file(child).gone:
                        return child
        except OSError:
            return folder
    return None


# --- Staging (PR-F42-12; SEC-F42-06 c, -07 e) -------------------------------------------------

class Staging:
    """This run's staging folder. The staging marker stays open until ``release`` (the end
    of the run), so on Windows no other build's ``sweep_stale`` can delete it meanwhile."""

    def __init__(self, path: Path, marker_fd: int | None) -> None:
        self.path = path
        self._fd = marker_fd

    @property
    def name(self) -> str:
        return self.path.name

    def release(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                os.close(fd)
            except OSError:
                pass

    def remove(self) -> Path | None:
        """Release the marker and delete the staging folder (``remove_tree``'s result)."""
        self.release()
        return remove_tree(self.path)


def staging_name(folder: str) -> str:
    return f".{folder}.building-{secrets.token_hex(4)}"


def make_staging(save_to: Path, folder: str) -> Staging:
    """Create ``<save_to>/.<folder>.building-<8 hex>`` (``os.mkdir``; a taken name is tried
    again with another) and write the staging marker in it first, by exclusive create.
    ``OSError`` propagates (the step machine reports ``B_CANT_WRITE``)."""
    for attempt in range(NAME_ATTEMPTS):
        path = save_to / staging_name(folder)
        try:
            os.mkdir(path)
            break
        except FileExistsError:
            if attempt == NAME_ATTEMPTS - 1:
                raise
    try:
        fd = _create(path / STAGING_MARKER)
        try:
            safefile.write_all(fd, STAGING_MARKER_BYTES)
        except OSError:
            os.close(fd)
            raise
    except OSError:
        remove_tree(path)
        raise
    return Staging(path, fd)


# --- Earlier builds (SEC-F42-07 a-c) ----------------------------------------------------------

def marker_bytes(*, engine: str, app_id: str, version: str, built: str) -> bytes:
    """The ``_internal/vn-build.json`` marker: format 1, engine version, Game ID, game
    version and build date. No paths (PR-F42-07)."""
    data = {"format": MARKER_FORMAT, "engine": engine, "id": app_id, "version": version,
            "built": built}
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def parse_marker(data: bytes) -> dict | None:
    """The marker as a dict if ``data`` is the marker format (UTF-8 JSON object, ``format``
    the int 1, ``engine``/``id``/``version``/``built`` strings; other keys ignored), else
    None."""
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or type(value.get("format")) is not int \
            or value["format"] != MARKER_FORMAT:
        return None
    if not all(type(value.get(key)) is str for key in _MARKER_TEXT_KEYS):
        return None
    return value


def is_earlier_build(folder: Path) -> bool:
    """By ``lstat``, ``folder`` and its ``_internal`` are real folders and
    ``_internal/vn-build.json`` is a regular file of at most 4 KiB in the marker format."""
    internal = folder / MARKER_DIR
    if not is_real_dir(folder) or not is_real_dir(internal):
        return False
    result = safefile.read_regular(internal / MARKER_NAME, MARKER_MAX_BYTES)
    return result.ok and result.data is not None and parse_marker(result.data) is not None


def _central_directory_ok(stream, size: int) -> bool:
    """The zip's end record names at most ``ZIP_MAX_ENTRIES`` entries in a central directory
    of at most ``ZIP_DIR_MAX_BYTES``, before ``zipfile`` reads any of it."""
    tail_size = min(size, _EOCD_SEARCH)
    stream.seek(size - tail_size)
    tail = stream.read(tail_size)
    at = tail.rfind(b"PK\x05\x06")
    if at < 0 or at + _EOCD.size > len(tail):
        return False
    _sig, _d, _dc, _ed, entries, dir_size, _off, _clen = _EOCD.unpack_from(tail, at)
    if entries == 0xFFFF or dir_size == 0xFFFFFFFF:
        start = size - tail_size + at - _EOCD64_LOCATOR.size
        if start < 0:
            return False
        stream.seek(start)
        sig, _disk, offset, _disks = _EOCD64_LOCATOR.unpack(stream.read(_EOCD64_LOCATOR.size))
        if sig != b"PK\x06\x07" or offset + _EOCD64.size > size:
            return False
        stream.seek(offset)
        record = _EOCD64.unpack(stream.read(_EOCD64.size))
        if record[0] != b"PK\x06\x06":
            return False
        entries, dir_size = record[7], record[8]
    return entries <= ZIP_MAX_ENTRIES and dir_size <= ZIP_DIR_MAX_BYTES


def zip_is_earlier_build(zip_path: Path, folder: str) -> bool:
    """``zip_path`` is a regular file (opened by handle, never through a link) whose capped
    central directory lists ``<folder>/_internal/vn-build.json``."""
    opened = safefile.open_regular(zip_path)
    if isinstance(opened, safefile.ReadResult):
        return False
    fd, fst = opened
    wanted = f"{folder}/{MARKER_DIR}/{MARKER_NAME}"
    try:
        with os.fdopen(fd, "rb") as stream:
            if not _central_directory_ok(stream, fst.st_size):
                return False
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                return any(info.filename == wanted for info in archive.infolist())
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError,
            struct.error, NotImplementedError, UnicodeDecodeError):
        return False


@dataclass(frozen=True)
class EarlierBuild:
    """Which earlier-build entries are at the computed names in *Save to*."""
    folder: bool
    zip: bool


def find_earlier_build(save_to: Path, folder: str, *, with_zip: bool) -> EarlierBuild | None:
    """The earlier build at ``<save_to>/<folder>`` (and ``<folder>.zip``), or None when
    neither name is taken. Raises ``B_NAME_TAKEN`` when the folder name holds anything but an
    earlier build, or (only ``with_zip``) the zip name holds anything but an earlier build's
    zip. A non-build at the zip name is left alone when this build makes no zip."""
    target = save_to / folder
    target_zip = save_to / f"{folder}.zip"
    has_folder = _exists(target)
    if has_folder and not is_earlier_build(target):
        raise texts.BuildStopped("B_NAME_TAKEN", folder=folder, save_to=save_to.name)
    has_zip = _exists(target_zip) and zip_is_earlier_build(target_zip, folder)
    if with_zip and _exists(target_zip) and not has_zip:
        raise texts.BuildStopped("B_NAME_TAKEN", folder=target_zip.name, save_to=save_to.name)
    if not has_folder and not has_zip:
        return None
    return EarlierBuild(has_folder, has_zip)


def _exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    return True


def _rename_aside(path: Path) -> Path:
    """Rename ``path`` to a hidden ``.<name>.old-<8 hex>`` beside it; OSError propagates."""
    for attempt in range(NAME_ATTEMPTS):
        aside = path.parent / f".{path.name}.old-{secrets.token_hex(4)}"
        if _exists(aside) and attempt < NAME_ATTEMPTS - 1:
            continue
        os.rename(path, aside)
        return aside
    raise FileExistsError(path)                                 # pragma: no cover


def _put_back(moves: list[tuple[Path, Path]]) -> None:
    """Undo renames (newest first), best effort."""
    for source, target in reversed(moves):
        try:
            os.rename(target, source)
        except OSError:
            pass


@dataclass(frozen=True)
class Installed:
    """``install_build``'s result: where the build is now, and any renamed-aside earlier
    build that couldn't be deleted (``sweep_stale`` removes it on a later build)."""
    folder: Path
    zip: Path | None
    left: tuple[Path, ...] = ()


def install_build(save_to: Path, folder: str, staged_folder: Path,
                  staged_zip: Path | None = None) -> Installed:
    """Move a finished build from staging to ``<save_to>/<folder>`` (and its zip beside it),
    replacing an earlier build there (SEC-F42-07 c). The caller has already decided that
    replacing is allowed (``--replace`` or ``REPLACE_ASK``); this re-checks with
    ``find_earlier_build`` that only an earlier build is replaced.

    The earlier folder and zip are renamed aside first (refused → ``B_IN_USE``, nothing
    changed), the new ones renamed in (refused → everything put back, ``B_CANT_WRITE``), then
    the asides are deleted. An earlier build's zip goes even when this build makes none."""
    target = save_to / folder
    target_zip = save_to / f"{folder}.zip"
    earlier = find_earlier_build(save_to, folder, with_zip=staged_zip is not None)
    moves: list[tuple[Path, Path]] = []
    asides: list[Path] = []
    for present, path in ((earlier is not None and earlier.folder, target),
                          (earlier is not None and earlier.zip, target_zip)):
        if not present:
            continue
        try:
            aside = _rename_aside(path)
        except OSError:
            _put_back(moves)
            raise texts.BuildStopped("B_IN_USE") from None
        moves.append((path, aside))
        asides.append(aside)
    for source, path in ((staged_folder, target), (staged_zip, target_zip)):
        if source is None:
            continue
        try:
            os.rename(source, path)
        except OSError:
            _put_back(moves)
            raise texts.BuildStopped("B_CANT_WRITE", save_to=save_to.name) from None
        moves.append((source, path))
    left = tuple(aside for aside in asides if remove_tree(aside) is not None)
    return Installed(target, target_zip if staged_zip is not None else None, left)


# --- Stale entries (SEC-F42-07 e) -------------------------------------------------------------

def sweep_stale(save_to: Path, *, now: float | None = None) -> list[str]:
    """Remove staging folders (``STAGING_RE`` name, a real folder holding the staging marker)
    and aside entries (``ASIDE_RE`` name, an earlier build or its zip) older than 60 s that
    a killed build left in ``save_to``. Looks at no more than ``SWEEP_MAX_EXAMINED`` entries.
    Returns the names removed. A staging folder whose marker can't be removed (a running
    build holds it open) is left alone. Never raises ``OSError``."""
    now = time.time() if now is None else now
    removed: list[str] = []
    try:
        with os.scandir(save_to) as it:
            names = [entry.name for _, entry in zip(range(SWEEP_MAX_EXAMINED), it)]
    except OSError:
        return removed
    for name in names:
        path = save_to / name
        if STAGING_RE.fullmatch(name):
            marker = path / STAGING_MARKER
            if not is_real_dir(path) or not safefile.is_regular_at(marker):
                continue
            if min(_age(path, now), _age(marker, now)) < STALE_AGE_S:
                continue
            if not safefile.remove_file(marker).gone:
                continue
        elif (match := ASIDE_RE.fullmatch(name)) is not None:
            inner = match.group("name")
            if inner.casefold().endswith(".zip"):
                if not zip_is_earlier_build(path, inner[:-4]):
                    continue
            elif not is_earlier_build(path):
                continue
            if _age(path, now) < STALE_AGE_S:
                continue
        else:
            continue
        if remove_tree(path) is None:
            removed.append(name)
    return removed
