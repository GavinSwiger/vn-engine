"""Safe file core: link-safe folders, bounded regular-file reads, atomic writes, and stale
temp-file cleanup (F12 ``04`` §3, §7.4, §7.5, §8; SEC-F12-03, -06, -13; F44 ``07`` I-2, I-17).

Lifted from the scene editor's save (``tools/editor/document.py``) so the editor and
persistent data share one atomic-write routine. Standard library only: ``tools/editor``
may import only ``core`` and ``script``, and ``persist`` must stay pygame-free.

- ``ensure_real_dir`` creates a data folder and requires it to be a real directory (not a
  link, junction, or other reparse point). Dev folders must also be their own real path;
  release folders may be reached through links at or above their root (ADR-0003 §5).
- ``read_regular`` reads a file only if ``lstat`` shows a regular file and the opened file
  is the same one (``fstat``); never more than ``max_bytes`` + 1 bytes. With
  ``single_link`` it also refuses a file whose open handle counts other than one link
  (``LINKED``; F31 SEC-F31-04). ``read_head`` makes
  the same checks (one shared open-and-``fstat`` helper) and reads only the first
  ``max_bytes`` bytes of a file of any size (F11 C15, save pages).
- ``write_atomic`` writes an exclusive, randomly named temp file beside the target, fsyncs
  it, optionally re-checks the target's stamp, and swaps it in with ``os.replace``. On an
  ``OSError`` only this attempt's temp file is removed and the error is re-raised, so the
  target holds exactly its old or its new bytes.
- ``remove_stale_temps`` removes old temp files a killed write left behind, looking at no
  more than ``STALE_MAX_EXAMINED`` folder entries; temp names are matched by
  ``temp_name_pattern`` for one exact target name or a ``target_pattern`` (F11 C15).
- ``remove_file`` removes one entry itself: a regular file or a link (a directory link or
  junction through ``os.rmdir`` on the entry), never a link's target, never recursively,
  never a real folder (F11 ``04`` §7.7, SEC-F11-08).
- ``list_regular`` lists the regular files whose names match a pattern, by one bounded
  ``os.scandir`` with no-follow stats, sliceable across frames (F20 ``07`` I-4).
- ``is_regular_at`` and ``entry_kind`` tell, by one ``lstat`` (no follow), whether an entry
  is a regular file, missing, or anything else (F31 ``04`` §6.1).
- ``quarantine`` renames a damaged file's entry (never its link target) to its ``.bad``
  name, shared by persistent data and settings (F16 ``07`` I-9).

Every system call goes through ``os.<name>`` so tests can inject faults by patching ``os``.
"""

import enum
import errno
import os
import re
import secrets
import stat
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

WRITE_JOIN_BYTES = 1 << 20          # pieces are joined into writes of about 1 MiB (§7.5)
READ_CHUNK_BYTES = 1 << 20          # reads past the stat size continue in 1 MiB chunks
TEMP_ATTEMPTS = 6                   # the first try and up to 5 retries on a taken name (I-2)
TEMP_MODE = 0o600
REPLACE_TRIES = 3                   # os.replace attempts on PermissionError (§7.5 step 3)
REPLACE_RETRY_S = 0.05
STALE_AGE_S = 60.0                  # SEC-F12-13 / §7.4 step 3
STALE_MAX_EXAMINED = 1000
STALE_MAX_REMOVED = 16

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_ATTR_DIRECTORY = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
# Windows reparse tags that are links: a symbolic link and a junction (mount point).
_LINK_TAGS = frozenset({getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
                        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)})
IS_POSIX = os.name == "posix"       # only folder permission refuses a replace or unlink there
_IS_POSIX = IS_POSIX


class Stamp(NamedTuple):
    """What identifies one version of a file: a replace gives a new file ID, and size and
    mtime catch in-place rewrites (F12 ``04`` Q5). Compared with ``==``."""

    ino: int
    size: int
    mtime_ns: int

    @classmethod
    def of(cls, st: os.stat_result) -> "Stamp":
        return cls(st.st_ino, st.st_size, st.st_mtime_ns)


class ReadKind(enum.Enum):
    OK = "ok"
    MISSING = "missing"                 # no entry at the path
    NOT_REGULAR = "not regular"         # link, junction, directory, FIFO, device, swapped
    TOO_LARGE = "too large"             # over ``max_bytes``
    UNREADABLE = "unreadable"           # an OSError on a regular file
    LINKED = "linked"                   # ``single_link``: the handle's link count isn't 1


@dataclass(frozen=True, slots=True)
class ReadResult:
    """``data`` only for OK. ``stamp`` for OK (from ``fstat``), and from ``lstat`` where
    one was taken for NOT_REGULAR and TOO_LARGE; None otherwise."""

    kind: ReadKind
    data: bytes | None = None
    stamp: Stamp | None = None

    @property
    def ok(self) -> bool:
        return self.kind is ReadKind.OK


class RemoveKind(enum.Enum):
    """``remove_file``'s outcome. The failure values are F11's W83 reason words."""

    REMOVED = "removed"
    MISSING = "missing"                         # no entry at the path (nothing to remove)
    NOT_FILE_OR_LINK = "not a file or link"     # a real folder, FIFO, device, other entry
    NO_PERMISSION = "no permission"
    FAILED = "couldn't remove"                  # any other OSError

    @property
    def gone(self) -> bool:
        """True when no entry is left at the path (removed, or there was none)."""
        return self in (RemoveKind.REMOVED, RemoveKind.MISSING)


class TargetChanged(Exception):
    """``write_atomic(check=True)``: the target's stamp wasn't ``expected`` right before the
    replace (SEC-F12-06c). The temp file was removed and the target left alone. ``stamp``
    is the target's current stamp (None if it is missing)."""

    def __init__(self, stamp: Stamp | None) -> None:
        super().__init__("the target changed before the replace")
        self.stamp = stamp


# --- Entry checks ---------------------------------------------------------------------------

def is_regular(st: os.stat_result) -> bool:
    """A regular file that is not a link, junction, or other reparse point (from ``lstat``)."""
    if not stat.S_ISREG(st.st_mode):
        return False
    return not (getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


class EntryKind(enum.Enum):
    """What ``lstat`` (no follow) finds at a path (F31 ``04`` §6.1)."""

    MISSING = "missing"                 # no entry
    REGULAR = "regular"                 # ``is_regular``
    OTHER = "other"                     # a folder, link, junction, reparse point, FIFO,
                                        # device, or an ``lstat`` error


def entry_kind(path: Path) -> EntryKind:
    """The kind of the entry at ``path`` by one ``lstat``; never follows a link and never
    raises ``OSError``."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return EntryKind.MISSING
    except (OSError, ValueError):
        return EntryKind.OTHER
    return EntryKind.REGULAR if is_regular(st) else EntryKind.OTHER


def is_regular_at(path: Path) -> bool:
    """Whether the entry at ``path`` is a regular file by ``lstat`` (a link, folder, other
    entry, or any error is False). Never raises ``OSError``."""
    return entry_kind(path) is EntryKind.REGULAR


def _is_real_dir(path: Path, st: os.stat_result) -> bool:
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
        return False
    if getattr(st, "st_file_attributes", 0) & _REPARSE_POINT:
        return False
    return not os.path.isjunction(path)


def current_stamp(path: Path) -> Stamp | None:
    """The stamp of the entry at ``path`` by ``lstat`` (links not followed); None if there
    is no entry. Other ``OSError``s propagate."""
    try:
        return Stamp.of(os.lstat(path))
    except FileNotFoundError:
        return None


# --- Folders ---------------------------------------------------------------------------------

def ensure_real_dir(folder: Path, *, release: bool = False, create: bool = True) -> bool:
    """Create ``folder`` if missing (``create``) and report whether it is usable.

    The folder itself must be a real directory by ``lstat``: not a link, junction, or
    reparse point. In a dev run (``release=False``) its real path must also be itself, so
    no link anywhere above it leads elsewhere, and only the last segment is created. In a
    release run, links at or above the per-user root only locate it and are followed, and
    missing parents are created (ADR-0003 §5). Never raises ``OSError``."""
    folder = Path(folder)
    try:
        try:
            st = os.lstat(folder)
        except FileNotFoundError:
            if not create:
                return False
            if release:
                os.makedirs(folder, exist_ok=True)
            else:
                os.mkdir(folder)
            st = os.lstat(folder)
        if not _is_real_dir(folder, st):
            return False
        if release:
            return True
        real = os.path.normcase(os.path.realpath(folder))
        return real == os.path.normcase(os.path.abspath(folder))
    except (OSError, ValueError):
        return False


# --- Reading ---------------------------------------------------------------------------------

def read_regular(path: Path, max_bytes: int, *, single_link: bool = False) -> ReadResult:
    """Read ``path`` whole if it is a regular file of at most ``max_bytes`` bytes.

    ``lstat`` must show a regular file (a link is refused without opening its target). The
    file is opened without following a link and without blocking on a FIFO (POSIX), and
    ``fstat`` must show the same regular file (``st_ino``, ``st_dev``). At most
    ``max_bytes`` + 1 bytes are read. Never raises ``OSError``.

    ``single_link`` (F31 SEC-F31-04): the open handle's ``fstat`` link count must be 1;
    any other value (a hard link elsewhere, or an unknown 0) is ``LINKED``, unread.
    ``lstat``'s count is never used (on Windows it may come from directory data)."""
    opened = _open_regular(path, max_bytes)
    if isinstance(opened, ReadResult):
        return opened
    fd, fst = opened
    try:
        if single_link and fst.st_nlink != 1:
            return ReadResult(ReadKind.LINKED, stamp=Stamp.of(fst))
        if fst.st_size > max_bytes:
            return ReadResult(ReadKind.TOO_LARGE, stamp=Stamp.of(fst))
        data = _read_bounded(fd, fst.st_size, max_bytes + 1)
        if len(data) > max_bytes:
            return ReadResult(ReadKind.TOO_LARGE, stamp=Stamp.of(fst))
        return ReadResult(ReadKind.OK, data=data, stamp=Stamp.of(fst))
    except OSError:
        return ReadResult(ReadKind.UNREADABLE)
    finally:
        _close_quietly(fd)


def read_head(path: Path, max_bytes: int) -> ReadResult:
    """The first ``max_bytes`` bytes of ``path`` if it is a regular file of any size (F11
    C15: a save page reads only lines 1 and 2).

    The entry checks are ``read_regular``'s, through the same helper: ``lstat`` regular,
    opened without following a link or blocking on a FIFO, ``fstat`` the same regular
    file. Never TOO_LARGE: OK carries at most ``max_bytes`` bytes (fewer for a shorter
    file) and the ``fstat`` stamp, whose ``size`` is the whole file's, so the caller can
    refuse a file over its own cap without reading more. Never raises ``OSError``."""
    opened = _open_regular(path, None)
    if isinstance(opened, ReadResult):
        return opened
    fd, fst = opened
    try:
        want = max(0, min(fst.st_size, max_bytes))
        data = _read_bounded(fd, want, max(0, max_bytes))
        return ReadResult(ReadKind.OK, data=data, stamp=Stamp.of(fst))
    except OSError:
        return ReadResult(ReadKind.UNREADABLE)
    finally:
        _close_quietly(fd)


def open_regular(path: Path) -> tuple[int, os.stat_result] | ReadResult:
    """Open ``path`` for reading, whatever its size, with ``read_regular``'s checks (``lstat``
    regular, a no-follow open, ``fstat`` the same regular file). Returns the open descriptor
    and its ``fstat`` (the caller reads at most ``st_size`` bytes and closes it), or the
    refusal as a ``ReadResult``. Never raises ``OSError``. F42's copy walk compares the
    ``fstat`` ``st_dev``/``st_ino`` with its own listing's (SEC-F42-06 b)."""
    return _open_regular(path, None)


def _open_regular(path: Path, max_bytes: int | None) -> tuple[int, os.stat_result] | ReadResult:
    """Open ``path`` for reading if it is a regular file: ``lstat`` regular (and, with
    ``max_bytes``, not over it), a no-follow open, and ``fstat`` the same regular file.
    Returns the open descriptor and its ``fstat`` (the caller closes it), or the refusal."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return ReadResult(ReadKind.MISSING)
    except (OSError, ValueError):
        return ReadResult(ReadKind.UNREADABLE)
    if not is_regular(st):
        return ReadResult(ReadKind.NOT_REGULAR, stamp=Stamp.of(st))
    if max_bytes is not None and st.st_size > max_bytes:
        return ReadResult(ReadKind.TOO_LARGE, stamp=Stamp.of(st))
    try:
        fd = _open_for_reading(path)
    except FileNotFoundError:
        return ReadResult(ReadKind.MISSING)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EMLINK):   # O_NOFOLLOW met a swapped-in link
            return ReadResult(ReadKind.NOT_REGULAR)
        return ReadResult(ReadKind.UNREADABLE)
    try:
        fst = os.fstat(fd)
    except OSError:
        _close_quietly(fd)
        return ReadResult(ReadKind.UNREADABLE)
    if (not is_regular(fst) or fst.st_ino != st.st_ino or fst.st_dev != st.st_dev):
        _close_quietly(fd)
        return ReadResult(ReadKind.NOT_REGULAR, stamp=Stamp.of(st))
    return fd, fst


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _open_for_reading(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if _IS_POSIX:
        flags |= os.O_NONBLOCK | os.O_NOFOLLOW
    return os.open(path, flags)


def _read_bounded(fd: int, expected: int, limit: int) -> bytes:
    """At most ``limit`` bytes: first the size ``fstat`` reported plus one byte (to notice
    growth) in one read, then 1 MiB chunks only while the file keeps giving more."""
    parts: list[bytes] = []
    total = 0
    want = min(expected + 1, limit)
    while total < limit:
        chunk = os.read(fd, want)
        if not chunk:
            break
        parts.append(chunk)
        total += len(chunk)
        want = min(READ_CHUNK_BYTES, limit - total)
    return parts[0] if len(parts) == 1 else b"".join(parts)


# --- Writing ---------------------------------------------------------------------------------

def temp_token() -> str:
    """8 random lowercase hex digits from ``secrets``."""
    return secrets.token_hex(4)


def temp_name(target_name: str, token: str) -> str:
    """``.<name>.<token>.tmp``, the temp file's name beside the target."""
    return f".{target_name}.{token}.tmp"


def write_all(fd: int, data: bytes) -> None:
    """``os.write`` until every byte of ``data`` is written."""
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def write_atomic(target: Path, pieces: Iterable[bytes], *,
                 check: bool = False, expected: Stamp | None = None,
                 mode: int | None = None,
                 replace_tries: int = REPLACE_TRIES,
                 sleep: Callable[[float], None] | None = None,
                 token: Callable[[], str] | None = None,
                 write: Callable[[int, bytes], None] | None = None) -> Stamp:
    """Replace ``target`` with the bytes of ``pieces`` and return the new file's stamp.

    1. Create ``.<name>.<8 hex>.tmp`` beside the target with ``O_CREAT | O_EXCL`` and mode
       0o600; an existing entry of that name (a planted link included) is never opened and
       another random name is tried, ``TEMP_ATTEMPTS`` in all (then ``FileExistsError``;
       Windows reports a directory or junction there as ``PermissionError`` at once).
    2. Write the pieces in joins of about 1 MiB, apply ``mode`` (POSIX, ``fchmod``), fsync
       (also ``F_FULLFSYNC`` on macOS), take the stamp by ``fstat``, and close.
    3. With ``check``, ``lstat`` the target right before each replace attempt: if its stamp
       isn't ``expected`` (None: the target must be missing), remove the temp file and
       raise ``TargetChanged`` (SEC-F12-06c).
    4. ``os.replace``, which swaps the folder entry and never writes through a link;
       ``PermissionError`` is retried up to ``replace_tries`` attempts in all,
       ``REPLACE_RETRY_S`` apart. On POSIX the folder is then fsynced (best effort: the new
       bytes are already in place).

    Any ``OSError`` (or other ``Exception``, such as a bug in a ``write`` seam) removes this
    attempt's temp file, if it was created, and propagates. A ``BaseException`` that isn't
    an ``Exception`` (a kill) leaves the temp file for ``remove_stale_temps``. ``token`` and
    ``write`` replace ``temp_token`` and ``write_all`` (seams); ``sleep`` defaults to
    ``time.sleep``. The caller checks the folder (``ensure_real_dir``) and the target."""
    target = Path(target)
    make_token = token if token is not None else temp_token
    write_bytes = write if write is not None else write_all
    pause = sleep if sleep is not None else time.sleep
    tmp, fd = _create_temp(target, make_token)
    try:
        try:
            _write_joined(fd, pieces, write_bytes)
            if mode is not None and hasattr(os, "fchmod"):
                os.fchmod(fd, mode)
            _fsync_file(fd)
            stamp = Stamp.of(os.fstat(fd))
        finally:
            os.close(fd)
        for attempt in range(max(1, replace_tries)):
            if check:
                now = current_stamp(target)
                if now != expected:
                    _remove_quietly(tmp)
                    raise TargetChanged(now)
            try:
                os.replace(tmp, target)
                break
            except PermissionError:
                if attempt + 1 >= max(1, replace_tries):
                    raise
                pause(REPLACE_RETRY_S)
    except Exception:                 # F12 AC-F12-34: no temp left after any failure
        _remove_quietly(tmp)
        raise
    _fsync_folder(target.parent)
    return stamp


def _create_temp(target: Path, make_token: Callable[[], str]) -> tuple[Path, int]:
    flags = (os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0))
    for _ in range(TEMP_ATTEMPTS):
        tmp = target.with_name(temp_name(target.name, make_token()))
        try:
            return tmp, os.open(tmp, flags, TEMP_MODE)
        except FileExistsError:
            continue
    raise FileExistsError(errno.EEXIST, "no free temp file name")


def _write_joined(fd: int, pieces: Iterable[bytes],
                  write_bytes: Callable[[int, bytes], None]) -> None:
    """Write ``pieces`` in joins of ``WRITE_JOIN_BYTES`` (the last one shorter)."""
    pending: list[bytes] = []
    size = 0
    for piece in pieces:
        while piece:
            take = piece[:WRITE_JOIN_BYTES - size]
            piece = piece[len(take):]
            pending.append(take)
            size += len(take)
            if size >= WRITE_JOIN_BYTES:
                write_bytes(fd, pending[0] if len(pending) == 1 else b"".join(pending))
                pending.clear()
                size = 0
    if pending:
        write_bytes(fd, pending[0] if len(pending) == 1 else b"".join(pending))


def _fsync_file(fd: int) -> None:
    os.fsync(fd)
    if sys.platform == "darwin":
        # macOS fsync doesn't flush the drive's cache; F_FULLFSYNC does where supported.
        try:
            import fcntl
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
        except (ImportError, AttributeError, OSError):
            pass


def _fsync_folder(folder: Path) -> None:
    """Make the rename durable (POSIX). Best effort: the replace has already happened."""
    if not _IS_POSIX:
        return
    try:
        fd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _remove_quietly(path: Path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# --- Removing one entry (F11 04 §7.7, SEC-F11-08a) -----------------------------------------

def remove_file(path: Path) -> RemoveKind:
    """Remove the entry at ``path`` itself, by ``lstat`` (links never followed):

    - a regular file, a file link, or (POSIX) any symlink → ``os.unlink``;
    - (Windows) a directory symlink or junction, a link reparse point with the directory
      flag → ``os.rmdir`` on the entry, which removes the link and never its target;
    - a real folder, a FIFO, a device, or any other entry → NOT_FILE_OR_LINK, untouched.

    Nothing is ever removed recursively (no ``shutil``). Returns the outcome; never raises
    ``OSError``."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return RemoveKind.MISSING
    except PermissionError:
        return RemoveKind.NO_PERMISSION
    except (OSError, ValueError):
        return RemoveKind.FAILED
    remove = _remover(st)
    if remove is None:
        return RemoveKind.NOT_FILE_OR_LINK
    try:
        remove(path)
    except FileNotFoundError:
        return RemoveKind.MISSING
    except PermissionError:
        return RemoveKind.NO_PERMISSION
    except OSError:
        return RemoveKind.FAILED
    return RemoveKind.REMOVED


def _remover(st: os.stat_result) -> Callable[[Path], None] | None:
    """``os.unlink``, ``os.rmdir``, or None (refused) for the entry ``st`` describes."""
    mode = st.st_mode
    attributes = getattr(st, "st_file_attributes", 0)
    is_link = stat.S_ISLNK(mode) or (
        bool(attributes & _REPARSE_POINT)
        and getattr(st, "st_reparse_tag", 0) in _LINK_TAGS)
    if is_link:
        if not _IS_POSIX and attributes & _ATTR_DIRECTORY:
            return os.rmdir
        return os.unlink
    if stat.S_ISREG(mode):
        return os.unlink
    return None


# --- Stale temp files ------------------------------------------------------------------------

def temp_name_pattern(target_name: str | None = None, *,
                      target_pattern: "str | re.Pattern[str] | None" = None) -> "re.Pattern[str]":
    """The pattern a temp name must ``fullmatch``: ``.<target>.<8 lowercase hex>.tmp``,
    where ``<target>`` is exactly ``target_name`` or, with ``target_pattern``, any name
    that pattern matches whole (F11: every slot name, ``SLOT_NAME_RE``; SEC-F11-08b).

    ``target_pattern``'s source is embedded in a group and compiled with ``re.ASCII`` (its
    own flags are not carried over), so it must not use anchors or global inline flags.
    Exactly one of the two arguments is given."""
    if (target_name is None) == (target_pattern is None):
        raise TypeError("give exactly one of target_name and target_pattern")
    if target_name is not None:
        target = re.escape(target_name)
    else:
        target = getattr(target_pattern, "pattern", target_pattern)
    return re.compile(rf"\.(?:{target})\.[0-9a-f]{{8}}\.tmp", re.ASCII)


def remove_stale_temps(folder: Path, target_name: str | None = None, *,
                       target_pattern: "str | re.Pattern[str] | None" = None,
                       now: float | None = None,
                       max_age_s: float = STALE_AGE_S,
                       max_examined: int = STALE_MAX_EXAMINED,
                       max_removed: int = STALE_MAX_REMOVED) -> int:
    """Remove up to ``max_removed`` regular files named ``.<target_name>.<8 hex>.tmp``
    (or, with ``target_pattern``, ``.<any name it matches>.<8 hex>.tmp``; see
    ``temp_name_pattern``) that are over ``max_age_s`` old, looking at no more than
    ``max_examined`` folder entries (SEC-F12-13). Links and other entries are never touched
    or read. Returns the number removed; never raises ``OSError``."""
    pattern = temp_name_pattern(target_name, target_pattern=target_pattern)
    when = time.time() if now is None else now
    removed = 0
    examined = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                examined += 1
                if pattern.fullmatch(entry.name):
                    try:
                        st = entry.stat(follow_symlinks=False)
                        if is_regular(st) and when - st.st_mtime > max_age_s:
                            os.unlink(entry.path)
                            removed += 1
                    except OSError:
                        pass
                if removed >= max_removed or examined >= max_examined:
                    break
    except OSError:
        pass
    return removed


# --- Listing regular files (F20 04 §7.5 "Launch", 07 I-4; SEC-F20-01(d)) ---------------------

class RegularFile(NamedTuple):
    """One listed entry: a regular file by a no-follow stat."""

    name: str
    size: int
    mtime_ns: int


class RegularListing:
    """``list_regular``'s iterator over one ``os.scandir`` of a folder.

    Iterating yields a ``RegularFile`` for each entry whose name fullmatches ``pattern`` and
    whose ``DirEntry.stat(follow_symlinks=False)`` is ``is_regular`` (links, junctions,
    reparse points, folders, FIFOs, and devices are skipped and never opened). At most
    ``max_examined`` entries are looked at; ``capped`` is set when more were left.
    ``batch(n)`` looks at no more than ``n`` further entries and returns their matches, so a
    caller can slice the listing across frames. ``examined`` counts the entries looked at;
    ``failed`` is set by an ``OSError`` (the listing then ends). The scandir closes when the
    listing ends, on ``close()``, on leaving a ``with`` block, or on garbage collection.
    Never raises ``OSError``."""

    def __init__(self, folder: Path, pattern: "re.Pattern[str]", max_examined: int) -> None:
        self.pattern = pattern
        self.max_examined = max_examined
        self.examined = 0
        self.capped = False
        self.failed = False
        self.done = False
        self._scan = None
        try:
            self._scan = os.scandir(folder)
        except (OSError, ValueError):
            self.failed = True
            self.done = True

    def __iter__(self) -> "RegularListing":
        return self

    def __next__(self) -> RegularFile:
        while True:
            found = self._advance()
            if found is not None:
                return found
            if self.done:
                raise StopIteration

    def batch(self, max_entries: int) -> list[RegularFile]:
        """The matches among at most ``max_entries`` further entries (fewer at the end)."""
        out: list[RegularFile] = []
        for _ in range(max_entries):
            if self.done:
                break
            found = self._advance()
            if found is not None:
                out.append(found)
        return out

    def _advance(self) -> RegularFile | None:
        """Look at one entry: its ``RegularFile`` if it matches, else None."""
        if self.done:
            return None
        try:
            entry = next(self._scan)                    # type: ignore[arg-type]
        except StopIteration:
            self.close()
            return None
        except OSError:
            self.failed = True
            self.close()
            return None
        if self.examined >= self.max_examined:
            self.capped = True
            self.close()
            return None
        self.examined += 1
        name = entry.name
        if not self.pattern.fullmatch(name):
            return None
        try:
            st = entry.stat(follow_symlinks=False)
        except OSError:
            return None
        if not is_regular(st):
            return None
        return RegularFile(name, st.st_size, st.st_mtime_ns)

    def close(self) -> None:
        self.done = True
        scan, self._scan = getattr(self, "_scan", None), None
        if scan is not None:
            try:
                scan.close()
            except OSError:
                pass

    def __enter__(self) -> "RegularListing":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


def list_regular(folder: Path, pattern: "re.Pattern[str]", *,
                 max_examined: int) -> RegularListing:
    """The regular files in ``folder`` whose names fullmatch ``pattern``, by one bounded,
    no-follow ``os.scandir`` (see ``RegularListing``). F20's node-file listing (``04``
    §7.5); the caller checks the folder first (``ensure_real_dir``)."""
    return RegularListing(Path(folder), pattern, max_examined)


# --- Quarantine (F16 07 I-9; ADR-0003 §9: one routine) --------------------------------------

def quarantine(target: Path, bad_name: str) -> bool:
    """Move the entry at ``target`` to ``bad_name`` in the same folder, replacing an older
    entry of that name; True if it moved. Used for a damaged data file (F12's
    ``persistent.bad.json``, F16's ``settings.bad.json``).

    ``os.replace`` moves the entry itself, so a link or junction is renamed and its target
    is never opened or touched. If the replace fails while a non-directory entry holds
    ``bad_name`` (some systems refuse to put a directory over a file), that entry is
    unlinked (a link itself, never its target) and the replace is tried once more. Never
    raises ``OSError``: on failure the entry stays where it was."""
    if not bad_name or bad_name in (".", "..") or any(ch in bad_name for ch in "/\\\0"):
        raise ValueError("bad_name must be a plain file name")
    target = Path(target)
    bad = target.with_name(bad_name)
    try:
        os.replace(target, bad)
        return True
    except (OSError, ValueError):
        pass
    try:
        st = os.lstat(bad)
        if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            return False
        os.lstat(target)                    # still there (not moved by someone else)
        os.unlink(bad)
        os.replace(target, bad)
        return True
    except (OSError, ValueError):
        return False
