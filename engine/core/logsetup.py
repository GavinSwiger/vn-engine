"""Engine logging: format, redaction, level filter, early buffer, log folder, rotation, cap.

Why this module exists: the session log is how authors and players report problems
(PR-F01-36..40), so it must always exist, always hold the header and the final shutdown
line, stay small, and never reveal who the player is (PR-F01-62, SEC-F01-09..15, 23). The
log folder is chosen only after ``config.toml`` is read (ADR-0003 §4), so records emitted
before that are held, already redacted, in a bounded memory buffer and written once the
file opens. Choosing, rotating, and creating the log file never follows a link and never
blocks (SEC-F01-13, 14).

This is the second of the two modules allowed to look up the home folder and the
environment variables that locate the ADR-0003 folders and the redaction roots
(SEC-F01-12, ADR-0003 §8). Their raw values only ever leave through the redactor or
``display_path``.

Nothing here touches the disk until ``LogSetup.open_file`` (SEC-F01-23 (c)).
"""

import collections
import logging
import os
import platform
import re
import stat
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from engine.core import redact as _redact
from engine.core.constants import (
    EARLY_LOG_MAX_BYTES,
    EARLY_LOG_MAX_RECORDS,
    LOG_CAP_BYTES,
    LOG_KEEP_ARCHIVED,
    LOG_KEEP_PID_LOGS,
    LOG_LIFECYCLE_RESERVE,
    LOG_TAIL_LINES,
    LOGS_DIRNAME,
    MB,
)
from engine.core.paths import display_path, exe_dir, home_dir
from engine.core.redact import RedactRoot, Redactor, escape_controls

LIFECYCLE = {"lifecycle": True}       # pass as extra=LIFECYCLE

ROOT_LOGGER = "vn"
LEVELS = {"debug": logging.DEBUG, "info": logging.INFO,
          "warning": logging.WARNING, "error": logging.ERROR}

DATEFMT = "%Y-%m-%d %H:%M:%S"
NOT_AVAILABLE = "not available (the log folder could not be written)"
FALLBACK_SUFFIX = " (fallback folder: [game] id is not set)"

MSG_GAME_LOGS_UNUSABLE = ("The logs folder in the game folder is a link or not a folder — "
                          "using another log location")
MSG_LATEST_NOT_REGULAR = "logs/latest.log is not a regular file — rotation skipped"
MSG_ROTATE_FAILED = "Could not rotate latest.log (it may be open in another copy of the game)"
MSG_LIMIT_REACHED = (f"Log size limit ({LOG_CAP_BYTES // MB} MB) reached — "
                     "further messages are dropped")
MSG_EARLY_DROPPED = "{n} early log records were dropped"

_AREA_RE = re.compile(r"[a-z]{1,7}", re.ASCII)

# Engine log names (§7.10.2). Only regular files with these exact names are ever read,
# renamed, or deleted.
_LATEST = "latest.log"
_PID_LOG_RE = re.compile(r"latest-(\d{1,10})\.log", re.ASCII)
_SESSION_RE = re.compile(r"session-(\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d)(?:-(\d{1,4}))?\.log",
                         re.ASCII)
_SESSION_STAMP = "%Y-%m-%d_%H-%M-%S"
_START_STAMP = "%Y-%m-%d %H:%M:%S.%f"
_START_BYTES = 23                    # len("2026-10-30 09:15:02.120")
_MAX_SESSION_SUFFIX = 9999

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


# --- Public helpers ----------------------------------------------------------------------

def get_logger(area: str) -> logging.Logger:
    """logging.getLogger(f"vn.{area}"). Area: ^[a-z]{1,7}$ (F01: app, config, assets,
    window, loop, input; later features add their own)."""
    if not _AREA_RE.fullmatch(area):
        raise ValueError(f"log area must be 1 to 7 lower-case letters: {area!r}")
    return logging.getLogger(f"{ROOT_LOGGER}.{area}")


def lifecycle(log: logging.Logger, msg: str, *args: object) -> None:
    """log.info(msg, *args, extra=LIFECYCLE): written at every level and past the cap."""
    log.info(msg, *args, extra=LIFECYCLE)


def is_lifecycle(record: logging.LogRecord) -> bool:
    return bool(getattr(record, "lifecycle", False))


def header_build_line(*, engine_version: str, pygame_version: str, sdl_version: str,
                      os_description: str, release: bool) -> str:
    """Header line 1 (§7.10.8): versions, OS, and build mode. No host or user names."""
    return (f"vn-engine {engine_version} | Python {platform.python_version()} | "
            f"pygame-ce {pygame_version} (SDL {sdl_version}) | {os_description} | "
            f"build {'release' if release else 'dev'}")


def header_log_line(session: "LogSession", *, fallback_id: bool) -> str:
    """Header line 2 (§7.10.8): ``Log: <display path>``, plus the fallback-folder note
    when the per-user folder was named by the fallback id (SEC-F01-16 (e))."""
    suffix = FALLBACK_SUFFIX if fallback_id and session.kind == "user" else ""
    return f"Log: {session.display_path}{suffix}"


# --- Data ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class LogDirCandidate:
    path: Path | None                 # None = location unavailable (e.g. no absolute base)
    kind: Literal["game", "user"]     # "game" = <root>/logs (link checks apply)


@dataclass(frozen=True)
class LogSession:
    file_path: Path | None            # None = console-only
    display_path: str                 # what the error screen and header show
    kind: Literal["game", "user"] | None = None   # the candidate used; None = console-only


# --- Redaction roots (§7.10.4) --------------------------------------------------------------

def _is_usable_root(value: str | os.PathLike | None) -> bool:
    """Set, absolute, and not just a drive or filesystem root."""
    if not value:
        return False
    path = Path(value)
    return path.is_absolute() and path.parent != path


def redaction_roots(*, game_root: Path | None, game_dir_as_given: Path | None,
                    engine_root: Path) -> list[RedactRoot]:
    """The (token, path) roots of §7.10.4, each only when set, absolute, and not a bare
    drive or filesystem root. Makes no OS call besides reading ``Path.home()``, ``sys``
    attributes, and environment values (SEC-F01-10 (d)), and, in a frozen build only,
    resolving the exe's path for the ``<app>`` root (F42 SEC-F42-09)."""
    candidates: list[tuple[str, str | os.PathLike | None]] = [
        ("<game>", game_root),
        ("<game>", game_dir_as_given),
        ("<engine>", engine_root),
        # F42 SEC-F42-09: the built game's exe folder. Longest-first matching keeps
        # <game> (<app>/game) and <engine> (<app>/_internal) for paths below them.
        ("<app>", exe_dir()),
        ("~", home_dir()),
        ("<python>", sys.prefix),
        ("<python>", sys.base_prefix),
        ("<python>", sys.exec_prefix),
        ("%APPDATA%", os.environ.get("APPDATA")),
        ("%LOCALAPPDATA%", os.environ.get("LOCALAPPDATA")),
        ("$XDG_DATA_HOME", os.environ.get("XDG_DATA_HOME")),
        ("<temp>", os.environ.get("TEMP")),
        ("<temp>", os.environ.get("TMP")),
    ]
    roots: list[RedactRoot] = []
    seen: set[tuple[str, str]] = set()
    for token, value in candidates:
        if _is_usable_root(value):
            item = (token, str(value))
            if item not in seen:
                seen.add(item)
                roots.append(RedactRoot(token, str(value)))
    return roots


def install_redactor(roots: list[RedactRoot]) -> None:
    """Install the process redactor for ``roots`` plus the home folder's name. The one place
    outside ``core/paths.py`` that looks up the home folder (privacy AST test)."""
    home = home_dir()
    _redact.install(Redactor(roots, home_name=home.name if home is not None else None,
                             case_insensitive=sys.platform in ("win32", "darwin")))


# --- Formatting and filtering ----------------------------------------------------------------

def _area(name: str) -> str:
    prefix = ROOT_LOGGER + "."
    if name.startswith(prefix):
        return name[len(prefix):].split(".", 1)[0]
    return "app"


BLOCK_PREFIX = "  "                   # SEC-F23-09: no record line starts with a space
BLOCK_MAX_LINES = 200
BLOCK_LINE_MAX_CHARS = 1_000
BLOCK_MORE = "…and {n} more lines."


def format_block(text: str) -> str:
    """A traceback or stack block as continuation lines (SEC-F23-09, F23 07 I-14).

    ``text`` is already escaped (newlines kept) and redacted. Every line gets
    ``BLOCK_PREFIX``, which no record starts with, so a message carrying
    ``\\n2026-… ERROR …`` can't forge a record. At most ``BLOCK_MAX_LINES`` lines of at most
    ``BLOCK_LINE_MAX_CHARS`` characters are kept, then one ``…and N more lines.`` line.
    Cutting after redaction means a cut can never leave half a private path behind."""
    lines = text.split("\n")
    kept = [BLOCK_PREFIX + _redact.truncate(line, BLOCK_LINE_MAX_CHARS)
            for line in lines[:BLOCK_MAX_LINES]]
    if len(lines) > BLOCK_MAX_LINES:
        kept.append(BLOCK_PREFIX + BLOCK_MORE.format(n=len(lines) - BLOCK_MAX_LINES))
    return "\n".join(kept)


class RedactingFormatter(logging.Formatter):
    """``%(asctime)s.%(msecs)03d %(levelname)-7s %(area)-7s %(message)s`` (§7.10.3).

    The message is escaped with ``allow_newline=False`` and the traceback and stack with
    ``allow_newline=True`` (SEC-F01-09); each is redacted with the redactor installed at
    that moment (SEC-F01-10, 11). The traceback and stack lines form one block, prefixed and
    capped by ``format_block`` (SEC-F23-09). The record is not modified.
    """

    def __init__(self) -> None:
        super().__init__(datefmt=DATEFMT)

    def format(self, record: logging.LogRecord) -> str:
        message = escape_controls(record.getMessage())
        level = "ERROR" if record.levelno >= logging.CRITICAL else record.levelname
        stamp = self.formatTime(record, self.datefmt)
        text = f"{stamp}.{int(record.msecs):03d} {level:<7} {_area(record.name):<7} {message}"
        parts: list[str] = []
        if record.exc_info:
            parts.append(self.formatException(record.exc_info).rstrip("\n"))
        elif record.exc_text:
            parts.append(record.exc_text.rstrip("\n"))
        if record.stack_info:
            parts.append(self.formatStack(record.stack_info).rstrip("\n"))
        if not parts:
            return _redact.redact(text)
        block = _redact.redact(escape_controls("\n".join(parts), allow_newline=True))
        return _redact.redact(text) + "\n" + format_block(block)

    def format_synthetic(self, message: str, *, levelno: int = logging.WARNING,
                         created: float | None = None) -> str:
        """Format an engine-made line (area ``app``) such as the cap or drop notice."""
        record = logging.LogRecord(f"{ROOT_LOGGER}.app", levelno, __file__, 0, message,
                                   None, None)
        if created is not None:
            record.created = created
            record.msecs = float(round(created * 1_000_000) % 1_000_000 // 1000)
        return self.format(record)


class LevelFilter(logging.Filter):
    """Pass records at or above the file level, and lifecycle records at any level."""

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.level or is_lifecycle(record)


class _ConsoleFilter(logging.Filter):
    """The console shows only WARNING and above; lifecycle INFO lines are file-only."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


class _TailHandler(logging.Handler):
    """The last ``LOG_TAIL_LINES`` formatted, redacted records (error screen copy)."""

    def __init__(self, maxlen: int = LOG_TAIL_LINES) -> None:
        super().__init__()
        self.lines: collections.deque[str] = collections.deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:
            self.handleError(record)


# --- Early buffer (§7.10.9, SEC-F01-23) ------------------------------------------------------

class EarlyBuffer(logging.Handler):
    """Holds records emitted before the log file opens, as redacted text only.

    At most ``max_records`` non-lifecycle records and ``max_bytes`` of their UTF-8 text;
    lifecycle records are always kept. The first dropped record leaves a marker in its
    place; later drops only count. Items are ``(lifecycle, text)`` pairs of ``bool`` and
    ``str``: no record, ``args``, or exception object is kept.
    """

    def __init__(self, *, max_records: int = EARLY_LOG_MAX_RECORDS,
                 max_bytes: int = EARLY_LOG_MAX_BYTES) -> None:
        super().__init__()
        self.max_records = max_records
        self.max_bytes = max_bytes
        self.items: list[tuple[bool, str]] = []
        self.records = 0                # non-lifecycle records kept
        self.bytes = 0                  # UTF-8 bytes of their text
        self.dropped = 0
        self._marker_index: int | None = None
        self._marker_created: float | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            lifecycle_record = is_lifecycle(record)
            if not lifecycle_record and self.dropped:
                self.dropped += 1
                return
            text = self.format(record)
            if lifecycle_record:
                self.items.append((True, text))
                return
            size = len(text.encode("utf-8", "backslashreplace"))
            if self.records + 1 > self.max_records or self.bytes + size > self.max_bytes:
                self.dropped = 1
                self._marker_index = len(self.items)
                self._marker_created = record.created
                return
            self.items.append((False, text))
            self.records += 1
            self.bytes += size
        except Exception:
            self.handleError(record)

    def drain(self, formatter: RedactingFormatter) -> list[tuple[bool, str]]:
        """All items in order, the drop marker rendered in place; the buffer is cleared."""
        items = list(self.items)
        if self.dropped and self._marker_index is not None:
            marker = formatter.format_synthetic(MSG_EARLY_DROPPED.format(n=self.dropped),
                                                created=self._marker_created)
            items.insert(self._marker_index, (False, marker))
        self.clear()
        return items

    def clear(self) -> None:
        self.items = []
        self.records = self.bytes = self.dropped = 0
        self._marker_index = self._marker_created = None


# --- The capped file handler (§7.10.7) -------------------------------------------------------

class CappedFileHandler(logging.Handler):
    """Writes formatted records to an open text stream, counting UTF-8 bytes.

    Non-lifecycle records are written only while they fit in ``cap - reserve``; the first
    one that doesn't triggers a single limit line (written from the reserve), and later
    non-lifecycle records are dropped. Lifecycle records are always written (they are
    small and bounded), so the header and the final ``Clean shutdown`` line are always
    present, and the file never exceeds ``cap``.
    """

    def __init__(self, stream: TextIO, *, cap: int = LOG_CAP_BYTES,
                 reserve: int = LOG_LIFECYCLE_RESERVE) -> None:
        super().__init__()
        self.stream = stream
        self.cap = cap
        self.reserve = reserve
        self.written = 0
        self.limit_reached = False
        self._broken = False

    def emit(self, record: logging.LogRecord) -> None:
        lifecycle_record = is_lifecycle(record)
        if self.limit_reached and not lifecycle_record:
            return                          # dropped anyway: skip the formatting cost
        try:
            text = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self.write_text(text, lifecycle=lifecycle_record)

    def write_text(self, text: str, *, lifecycle: bool) -> None:
        """Write one already formatted (and redacted) entry under the cap rules."""
        data = text + "\n"
        size = len(data.encode("utf-8", "backslashreplace"))
        if lifecycle:
            if self.written + size <= self.cap:
                self._write(data, size)
            return
        if self.limit_reached:
            return
        if self.written + size <= self.cap - self.reserve:
            self._write(data, size)
            return
        self.limit_reached = True
        notice = self._notice_text() + "\n"
        notice_size = len(notice.encode("utf-8", "backslashreplace"))
        if self.written + notice_size <= self.cap:
            self._write(notice, notice_size)

    def _notice_text(self) -> str:
        formatter = self.formatter if isinstance(self.formatter, RedactingFormatter) \
            else RedactingFormatter()
        return formatter.format_synthetic(MSG_LIMIT_REACHED)

    def _write(self, data: str, size: int) -> None:
        if self._broken:
            return
        try:
            self.stream.write(data)
            self.stream.flush()
            self.written += size
        except (OSError, ValueError):
            self._broken = True          # disk full, file closed: stop writing quietly

    def close(self) -> None:
        self.acquire()
        try:
            try:
                self.stream.close()
            except OSError:
                pass
        finally:
            self.release()
        super().close()


# --- Log folder, rotation, retention (§7.10.1–2) ---------------------------------------------

def _is_regular(st: os.stat_result) -> bool:
    if not stat.S_ISREG(st.st_mode):
        return False
    return not (getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _engine_entries(directory: Path) -> dict[str, os.stat_result]:
    """Regular files (not links, not reparse points) with engine log names."""
    found: dict[str, os.stat_result] = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            name = entry.name
            if not (name == _LATEST or _PID_LOG_RE.fullmatch(name)
                    or _SESSION_RE.fullmatch(name)):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if _is_regular(st):
                found[name] = st
    return found


def _read_start_time(path: Path) -> time.struct_time | None:
    """The start time from the first 23 bytes of a regular ``latest.log``, or None."""
    if os.name == "posix":
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    else:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        head = os.read(fd, _START_BYTES)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        return time.strptime(head.decode("utf-8", errors="strict"), _START_STAMP)
    except (UnicodeDecodeError, ValueError):
        return None


def _session_sort_key(name: str) -> tuple[str, int]:
    match = _SESSION_RE.fullmatch(name)
    assert match is not None
    return match.group(1), int(match.group(2) or 1)


class _Rotator:
    """Rotation and retention in one log directory (SEC-F01-14, SEC-F01-15)."""

    def __init__(self, directory: Path, log: logging.Logger) -> None:
        self.directory = directory
        self.log = log

    def run(self) -> None:
        try:
            self._rotate_latest()
        except OSError:
            self.log.debug("Log rotation failed", exc_info=True)
        try:
            self._retain_pid_logs()
        except OSError:
            self.log.debug("Log retention failed", exc_info=True)

    def _rotate_latest(self) -> None:
        latest = self.directory / _LATEST
        # Looked up by exact name in the listing: on a case-insensitive file system
        # os.lstat("latest.log") would also find a file named "latest.LOG".
        st = None
        with os.scandir(self.directory) as entries:
            for entry in entries:
                if entry.name == _LATEST:
                    st = entry.stat(follow_symlinks=False)
                    break
        if st is None:
            self._retain_archives()
            return
        if not _is_regular(st):
            self.log.warning(MSG_LATEST_NOT_REGULAR)
            return                                  # straight to step 4
        started = _read_start_time(latest) or time.localtime(st.st_mtime)
        base = f"session-{time.strftime(_SESSION_STAMP, started)}"
        target = None
        for n in range(1, _MAX_SESSION_SUFFIX + 1):
            name = f"{base}.log" if n == 1 else f"{base}-{n}.log"
            try:
                os.lstat(self.directory / name)
            except FileNotFoundError:
                target = self.directory / name
                break
        if target is None:
            self.log.warning(MSG_ROTATE_FAILED)
        else:
            try:
                os.rename(latest, target)
            except OSError:
                self.log.warning(MSG_ROTATE_FAILED)
        self._retain_archives()

    def _retain_archives(self) -> None:
        names = [name for name in _engine_entries(self.directory) if _SESSION_RE.fullmatch(name)]
        names.sort(key=_session_sort_key, reverse=True)
        for name in names[LOG_KEEP_ARCHIVED:]:
            self._delete(name)

    def _retain_pid_logs(self) -> None:
        entries = _engine_entries(self.directory)
        pid_logs = [(st.st_mtime, name) for name, st in entries.items()
                    if _PID_LOG_RE.fullmatch(name)]
        pid_logs.sort(reverse=True)
        for _, name in pid_logs[LOG_KEEP_PID_LOGS - 1:]:
            self._delete(name)

    def _delete(self, name: str) -> None:
        try:
            os.unlink(self.directory / name)
        except OSError:
            self.log.debug("Could not delete old log file %s", name)


def _prepare_game_dir(path: Path, log: logging.Logger) -> bool:
    """``<root>/logs`` is usable only if it is a real directory whose real path is itself
    (SEC-F01-13). Creates it if missing."""
    try:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            os.mkdir(path)
            st = os.lstat(path)
    except OSError:
        log.debug("The logs folder in the game folder could not be created", exc_info=True)
        return False
    usable = (stat.S_ISDIR(st.st_mode)
              and not stat.S_ISLNK(st.st_mode)
              and not os.path.isjunction(path)
              and not (getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)
              and os.path.normcase(os.path.realpath(path))
              == os.path.normcase(os.path.join(path.parent, LOGS_DIRNAME)))
    if not usable:
        log.warning(MSG_GAME_LOGS_UNUSABLE)
    return usable


def _prepare_user_dir(path: Path, log: logging.Logger) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path.is_dir()
    except OSError:
        log.debug("The per-user log folder could not be created", exc_info=True)
        return False


def _create_exclusive(path: Path) -> TextIO:
    return open(path, "x", encoding="utf-8", newline="\n", errors="backslashreplace")


def _create_log_file(directory: Path) -> tuple[Path, TextIO] | None:
    """Exclusive-create ``latest.log``, else ``latest-<pid>.log``; None if neither works."""
    latest = directory / _LATEST
    try:
        return latest, _create_exclusive(latest)
    except FileExistsError:
        pass
    except OSError:
        # Windows reports an existing directory (or a file being deleted) as access denied.
        if not os.path.lexists(latest):
            return None
    pid_log = directory / f"latest-{os.getpid()}.log"
    try:
        return pid_log, _create_exclusive(pid_log)
    except OSError:
        return None


# --- LogSetup ---------------------------------------------------------------------------------

class LogSetup:
    """The session's logging state, from ``begin()`` to ``close()``."""

    def __init__(self, *, level: str, engine_root: Path, console: bool,
                 cap: int = LOG_CAP_BYTES, reserve: int = LOG_LIFECYCLE_RESERVE) -> None:
        self._engine_root = engine_root
        self._game_root: Path | None = None
        self._game_dir_as_given: Path | None = None
        self._cap = cap
        self._reserve = reserve
        self._logger = logging.getLogger(ROOT_LOGGER)
        self._saved_level = self._logger.level
        self._formatter = RedactingFormatter()
        self._file_level = LEVELS[level]
        self._filter = LevelFilter(self._file_level)
        self._handlers: list[logging.Handler] = []
        self._session: LogSession | None = None
        self.file_handler: CappedFileHandler | None = None
        self._closed = False

        self._install()

        self._tail = _TailHandler()
        self._attach(self._tail, self._filter)
        self.console_handler: logging.StreamHandler | None = None
        if console and sys.stderr is not None:
            self.console_handler = logging.StreamHandler(sys.stderr)
            self._attach(self.console_handler, _ConsoleFilter())
        self.early_buffer: EarlyBuffer | None = EarlyBuffer()
        self._attach(self.early_buffer, self._filter)
        self._apply_level()

    # -- configuration --

    def add_game_root(self, root: Path, *, as_given: Path | None = None) -> None:
        """Re-install the redactor with ``<game>`` (the resolved root and the path as
        given), and use ``root`` for ``<game>/…`` display forms."""
        self._game_root = root
        if as_given is not None and as_given.is_absolute():
            self._game_dir_as_given = as_given
        self._install()

    def set_level(self, level: str) -> None:
        """The lowest level written to the file and tail (lifecycle records ignore it)."""
        self._file_level = LEVELS[level]
        self._filter.level = self._file_level
        self._apply_level()

    @property
    def level(self) -> int:
        return self._file_level

    # -- the file --

    def open_file(self, candidates: Sequence[LogDirCandidate]) -> LogSession:
        """First usable candidate (§7.10.1–3): safety checks, rotation, retention,
        exclusive create; flush the early buffer. None usable → console-only, buffer
        discarded. Idempotent: a second call returns the existing session."""
        if self._session is not None:
            return self._session
        app_log = get_logger("app")
        for candidate in candidates:
            if candidate.path is None:
                continue
            if candidate.kind == "game":
                usable = _prepare_game_dir(candidate.path, app_log)
            else:
                usable = _prepare_user_dir(candidate.path, app_log)
            if not usable:
                continue
            _Rotator(candidate.path, app_log).run()
            created = _create_log_file(candidate.path)
            if created is None:
                continue
            file_path, stream = created
            self._start_file(stream)
            self._session = LogSession(
                file_path, display_path(file_path, game_root=self._game_root), candidate.kind)
            return self._session
        self._discard_buffer()
        self._session = LogSession(None, NOT_AVAILABLE, None)
        return self._session

    @property
    def session(self) -> LogSession | None:
        return self._session

    @property
    def tail(self) -> "collections.deque[str]":
        """The last 50 formatted, redacted lines."""
        return self._tail.lines

    def close(self) -> None:
        """Detach and close every handler this setup attached; restore the ``vn`` level."""
        if self._closed:
            return
        self._closed = True
        self._discard_buffer()
        for handler in self._handlers:
            self._logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        self._handlers.clear()
        self._logger.setLevel(self._saved_level)
        global _active
        if _active is self:
            _active = None

    # -- internals --

    def _install(self) -> None:
        install_redactor(redaction_roots(game_root=self._game_root,
                                          game_dir_as_given=self._game_dir_as_given,
                                          engine_root=self._engine_root))

    def _attach(self, handler: logging.Handler, log_filter: logging.Filter) -> None:
        handler.setFormatter(self._formatter)
        handler.addFilter(log_filter)
        self._logger.addHandler(handler)
        self._handlers.append(handler)

    def _detach(self, handler: logging.Handler) -> None:
        self._logger.removeHandler(handler)
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _apply_level(self) -> None:
        # INFO lifecycle records must always reach the handlers (§7.10.7).
        self._logger.setLevel(min(self._file_level, logging.INFO))

    def _start_file(self, stream: TextIO) -> None:
        handler = CappedFileHandler(stream, cap=self._cap, reserve=self._reserve)
        handler.setFormatter(self._formatter)
        handler.addFilter(self._filter)
        buffer = self.early_buffer
        if buffer is not None:
            self._detach(buffer)
            for lifecycle_item, text in buffer.drain(self._formatter):
                handler.write_text(text, lifecycle=lifecycle_item)
            buffer.close()
            self.early_buffer = None
        self._logger.addHandler(handler)
        self._handlers.append(handler)
        self.file_handler = handler

    def _discard_buffer(self) -> None:
        buffer = self.early_buffer
        if buffer is not None:
            self._detach(buffer)
            buffer.clear()
            buffer.close()
            self.early_buffer = None


_active: LogSetup | None = None


def begin(*, level: str, engine_root: Path, console: bool = True) -> LogSetup:
    """Installs the redactor (base roots), the level filter, the console and tail
    handlers, and the EarlyBuffer. Writes nothing to disk.

    A setup still open from an earlier ``begin()`` in this process is closed first.
    """
    global _active
    if _active is not None:
        _active.close()
    _active = LogSetup(level=level, engine_root=engine_root, console=console)
    return _active
