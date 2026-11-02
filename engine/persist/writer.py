"""The one file writer: a daemon thread that writes bytes prepared on the main thread, for
several owners (F12 checklist step 4; ADR-0007 "one writer, several owners"; F16 ``07`` §3;
F12 ``04`` §7.5 writer, §18.1; SEC-F12-06, -07, -09(b); SEC-F11-10).

Why this module exists: an fsync can take 10–50 ms, so persistent data (F12), settings (F16),
and saves (F11) are written off the frame loop. There is exactly one such thread per process,
so two writes never overlap and quit has one deadline to honor.

- **One ``Writer``** per process (``App.writer``, added at F12 step 6). The launch starts
  its thread during the load screen's warm-up (``start``, from ``install_persistence``), so
  the first write's frame doesn't pay the 1–2 ms a thread start costs (AC-F12-45); a writer
  nobody started starts its thread on the first ``submit``, and a run that never writes
  starts none. ``WRITER_THREADED = False`` (read when a ``Writer`` is built) runs every job
  synchronously inside ``submit``.
- **Owners** register once: ``writer.client(owner, root=..., names=...)``. ``names`` is a
  fixed set of plain file names, or a full-match pattern for engine-generated names only.
  Owners: ``persist`` (``persistent.json``), ``settings`` (``settings.json``), ``save``,
  and ``flow`` (F20's node files ``node-<16 hex>.vnnode`` in the ``save`` owner's root; F20
  ``07`` I-5, SEC-F20-03: ``FileWrite`` only, one job pending, behind ``save`` and
  ``persist``, which F20 reads with ``Writer.pending_of``), and ``meta`` (F31's
  ``<game>/characters``, names ``META_NAME_RE``; its jobs always use the dev folder rule).
- **Jobs:** ``WriteRequest`` (F12's stamped write; owner ``persist`` only; the only job that
  may read, and only its own target after its stamp changed), ``FileWrite`` (a plain
  last-writer-wins atomic write), and ``FileRemove`` (owner ``meta`` only: ``remove_file``
  on the entry at a registered name, never a link's target, never recursive, never a real
  folder; it never creates the root). Before any file-system call a job's folder must equal
  its owner's root and its name must be registered; otherwise the result is
  ``Failed("couldn't write")`` and nothing is touched. The owner's root is the only folder
  the writer may create (``ensure_real_dir``).
- **Order:** one job at a time, first in first out across owners. Results go only to the
  submitting owner's client (``take``, ``pending``, ``in_flight``, ``wait``); "in flight"
  counts that owner's jobs only.
- **Quit:** ``WriterClient.drop_queued()`` (only ``meta`` calls it, first at quit) ends that
  owner's jobs not yet started as ``Failed(STOPPED_DETAIL)``. Then every owner waits
  against one deadline, ``quit_deadline()`` (``CLOSE_WAIT_S`` from the start of quit); ``stop(until)`` then lets the thread finish or abandons it. An
  abandoned write can leave only its temp file, never a partial target.
- **Never logs** (ADR-0007 as amended). A failure is a fixed reason word plus a redacted,
  truncated traceback text, which the owner logs on the main thread (DEBUG).

The thread receives only frozen jobs (``Path``, ``bytes``, a ``Stamp``), makes only
file-system calls through ``core/safefile.py`` inside the owner's root, and returns result
objects it created. It never touches the store, ``GamePaths``, or any other engine object.
"""

import errno
import os
import re
import stat
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine.core import safefile
from engine.core.redact import redact, truncate
from engine.core.safefile import ReadKind, ReadResult, RemoveKind, Stamp, TargetChanged
from engine.persist import limits
from engine.persist.location import FILE_NAME

WRITER_THREADED = True               # False: every job runs inside submit (ADR-0007 fallback)

PERSIST = "persist"                  # F12, {"persistent.json"}
SETTINGS = "settings"                # F16, {"settings.json"}
SAVE = "save"                        # F11, slot names (a pattern)
FLOW = "flow"                        # F20, node file names (a pattern; 07 I-5)
META = "meta"                        # F31, META_NAME_RE in <game>/characters (07 I-1)
OWNERS = (PERSIST, SETTINGS, SAVE, FLOW, META)   # new owners come only through review

# Failure reasons: fixed words, the only text of a failure that reaches a warning (SEC-F12-09).
DISK_FULL = "disk full"
NO_PERMISSION = "no permission"
COULDNT_WRITE = "couldn't write"
FOLDER_IS_LINK = "the folder is a link"
REASONS = (DISK_FULL, NO_PERMISSION, COULDNT_WRITE, FOLDER_IS_LINK)

FILE_MODE = 0o600
READ_RETRY_S = 0.05                  # between reads of a changed target (§7.5 step 2)
WAIT_SLICE_S = 0.05                  # longest single sleep of wait/stop (the clock may be fake)
DETAIL_MAX_CHARS = 4_000

OUTSIDE_DETAIL = "the job is outside its owner's folder or file names"
CHANGING_DETAIL = "the target kept changing"
STOPPED_DETAIL = "skipped: the writer stopped at quit"

_NO_PERMISSION_ERRNOS = frozenset({errno.EACCES, errno.EPERM, errno.EROFS})
_BAD_NAME_CHARS = frozenset("/\\:\0")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


# --- Jobs ------------------------------------------------------------------------------------

def _check_job_fields(folder: object, name: object, pieces: object, release: object) -> None:
    if not isinstance(folder, Path):
        raise TypeError("a job's folder must be a Path")
    if type(name) is not str:
        raise TypeError("a job's file name must be a str")
    if type(pieces) is not tuple or any(type(piece) is not bytes for piece in pieces):
        raise TypeError("a job's pieces must be a tuple of bytes")
    if type(release) is not bool:
        raise TypeError("a job's release flag must be a bool")


@dataclass(frozen=True, slots=True)
class WriteRequest:
    """F12's stamped write of ``persistent.json`` (owner ``persist`` only).

    With ``check``, the target must still have the stamp ``expected`` (None: missing) both
    before the write and right before the replace (SEC-F12-06c); otherwise the writer reads
    it and returns ``Changed``. A missing target is always written. ``version`` is the
    store's version the pieces encode; it comes back in ``Written``."""

    folder: Path
    pieces: tuple[bytes, ...]
    expected: Stamp | None
    check: bool
    version: int
    release: bool = False
    name: str = FILE_NAME

    def __post_init__(self) -> None:
        _check_job_fields(self.folder, self.name, self.pieces, self.release)
        if self.expected is not None and not isinstance(self.expected, Stamp):
            raise TypeError("expected must be a Stamp or None")
        if type(self.check) is not bool or type(self.version) is not int:
            raise TypeError("check must be a bool and version an int")


@dataclass(frozen=True, slots=True)
class FileWrite:
    """A plain atomic write, last writer wins (F16 settings, F11 saves). ``token`` comes
    back in the result so the owner can match it."""

    folder: Path
    name: str
    pieces: tuple[bytes, ...]
    release: bool = False
    token: int = 0

    def __post_init__(self) -> None:
        _check_job_fields(self.folder, self.name, self.pieces, self.release)
        if type(self.token) is not int:
            raise TypeError("token must be an int")


@dataclass(frozen=True, slots=True)
class FileRemove:
    """Remove the entry at ``folder / name`` itself (owner ``meta`` only; F31 ``04`` §6.4):
    ``safefile.remove_file``, so a link is removed and never its target, and a real folder
    is refused. A missing root is ``FileRemoved(MISSING)`` and is never created. The root
    check is always the dev rule (``release`` is carried for the record only). ``token``
    comes back in the result."""

    folder: Path
    name: str
    release: bool = False
    token: int = 0

    def __post_init__(self) -> None:
        _check_job_fields(self.folder, self.name, (), self.release)
        if type(self.token) is not int:
            raise TypeError("token must be an int")


Job = WriteRequest | FileWrite | FileRemove


# --- Results ---------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Written:
    """A ``WriteRequest`` replaced the target; ``stamp`` is the new file's."""

    stamp: Stamp
    version: int


@dataclass(frozen=True, slots=True)
class Changed:
    """A ``WriteRequest`` found the target changed by someone else and didn't write. The
    target was read (up to ``IO_TRIES`` reads, ``READ_RETRY_S`` apart): ``kind`` and
    ``data``/``stamp`` are that read's (``data`` only for OK). The main thread checks the
    bytes before using them (``fileformat.outcome_of_read``, ``ReadJob``)."""

    stamp: Stamp | None
    data: bytes | None
    kind: ReadKind = ReadKind.OK

    @property
    def read(self) -> ReadResult:
        return ReadResult(self.kind, self.data, self.stamp)


@dataclass(frozen=True, slots=True)
class FileWritten:
    """A ``FileWrite`` replaced its target; ``stamp`` is the new file's."""

    token: int
    stamp: Stamp


@dataclass(frozen=True, slots=True)
class FileRemoved:
    """A ``FileRemove`` ran: ``kind`` is ``remove_file``'s outcome (``MISSING`` too when
    the root itself was missing)."""

    token: int
    kind: RemoveKind


@dataclass(frozen=True, slots=True)
class Failed:
    """Nothing was written; the old target is untouched and no temp file remains.
    ``reason`` is one of ``REASONS``; ``detail`` is a redacted traceback or a fixed text,
    for the owner's DEBUG record only; ``token`` is the ``FileWrite``'s or ``FileRemove``'s
    (0 otherwise)."""

    reason: str
    detail: str = ""
    token: int = 0


Result = Written | Changed | FileWritten | FileRemoved | Failed


def reason_for(exc: BaseException) -> str:
    """F12's ``OSError`` mapping (§7.5 step 3): ``ENOSPC`` → ``disk full``; ``EACCES``,
    ``EPERM``, ``EROFS`` → ``no permission``; anything else → ``couldn't write``."""
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return DISK_FULL
        if exc.errno in _NO_PERMISSION_ERRNOS or isinstance(exc, PermissionError):
            return NO_PERMISSION
    return COULDNT_WRITE


def _detail(exc: BaseException) -> str:
    """The traceback, redacted (SEC-F12-09b), then cut."""
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return truncate(redact(text), DETAIL_MAX_CHARS)


def _plain_name(name: object) -> bool:
    return (type(name) is str and name not in ("", ".", "..")
            and not any(ch in _BAD_NAME_CHARS for ch in name))


# --- Owners ----------------------------------------------------------------------------------

class WriterClient:
    """One owner's handle on the writer. Main thread only."""

    __slots__ = ("owner", "root", "names", "_writer", "_results", "_in_flight")

    def __init__(self, writer: "Writer", owner: str, root: Path,
                 names: frozenset[str] | re.Pattern[str]) -> None:
        self._writer = writer
        self.owner = owner
        self.root = root
        self.names = names
        self._results: deque[Result] = deque()
        self._in_flight = 0

    def __repr__(self) -> str:
        return f"WriterClient({self.owner!r})"

    def accepts(self, folder: Path, name: str) -> bool:
        """Whether a job for ``folder / name`` belongs to this owner (no file-system call)."""
        if not isinstance(folder, Path) or folder != self.root or not _plain_name(name):
            return False
        if isinstance(self.names, re.Pattern):
            return self.names.fullmatch(name) is not None
        return name in self.names

    def submit(self, job: Job) -> None:
        """Queue ``job`` behind every job already queued, by any owner (synchronous when
        the writer isn't threaded). Raises ``TypeError`` for anything but a job and
        ``RuntimeError`` after ``Writer.stop``."""
        self._writer._submit(self, job)

    def take(self) -> list[Result]:
        """This owner's finished results, oldest first; each is returned once."""
        with self._writer._cond:
            out = list(self._results)
            self._results.clear()
        return out

    @property
    def in_flight(self) -> int:
        """This owner's jobs submitted and not yet finished."""
        with self._writer._cond:
            return self._in_flight

    @property
    def pending(self) -> int:
        """This owner's jobs submitted and not yet taken (in flight or finished)."""
        with self._writer._cond:
            return self._in_flight + len(self._results)

    def wait(self, until: float) -> list[Result]:
        """Wait until this owner has nothing in flight or the writer's clock reaches
        ``until``, then ``take()``. Jobs still in flight stay in flight."""
        self._writer._wait(self, until)
        return self.take()

    def drop_queued(self) -> None:
        """At quit (owner ``meta`` only, before F11's quit save; SEC-F31-08): this owner's
        jobs not yet started never start; each ends ``Failed(COULDNT_WRITE,
        STOPPED_DETAIL)``. The running job finishes; other owners' jobs stay queued.
        Returns at once."""
        self._writer._drop_queued(self)


# --- The writer ------------------------------------------------------------------------------

class Writer:
    """The one file writer of a process. ``clock`` (monotonic seconds) measures ``wait``
    and ``stop`` deadlines; ``sleep`` paces the replace and read retries. Both are seams."""

    def __init__(self, *, threaded: bool | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.threaded = WRITER_THREADED if threaded is None else bool(threaded)
        self._clock = clock
        self._sleep = sleep
        self._cond = threading.Condition()
        self._queue: deque[tuple[WriterClient, Job]] = deque()
        self._clients: dict[str, WriterClient] = {}
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._closed = False
        self.abandoned = False

    # --- Registration and state (main thread) ---

    def client(self, owner: str, *, root: Path,
               names: frozenset[str] | re.Pattern[str]) -> WriterClient:
        """Register ``owner`` with its folder and file names, once (a second registration,
        an unknown owner, a relative root, or a name that isn't a plain file name raises
        ``ValueError``)."""
        if owner not in OWNERS:
            raise ValueError(f"unknown writer owner {owner!r}")
        root = Path(root)
        if not root.is_absolute():
            raise ValueError("a writer owner's root must be an absolute path")
        if isinstance(names, re.Pattern):
            if not isinstance(names.pattern, str):
                raise ValueError("a writer name pattern must be a str pattern")
        else:
            names = frozenset(names)
            if not names or not all(_plain_name(n) for n in names):
                raise ValueError("writer names must be plain file names")
        with self._cond:
            if owner in self._clients:
                raise ValueError(f"writer owner {owner!r} is already registered")
            client = WriterClient(self, owner, root, names)
            self._clients[owner] = client
        return client

    def pending_of(self, owner: str) -> int:
        """``owner``'s jobs submitted and not yet taken (0 when it never registered).
        Read-only: F20 submits no ``flow`` job while ``save`` or ``persist`` has one
        pending (07 I-5, SEC-F20-03(b))."""
        with self._cond:
            client = self._clients.get(owner)
            return 0 if client is None else client._in_flight + len(client._results)

    def now(self) -> float:
        """The writer's clock: the time base of ``wait``, ``stop``, and ``quit_deadline``."""
        return self._clock()

    def quit_deadline(self) -> float:
        """The one quit deadline every owner shares: now + ``CLOSE_WAIT_S``."""
        return self._clock() + limits.CLOSE_WAIT_S

    @property
    def started(self) -> bool:
        """Whether the thread was ever started (by ``start`` or a threaded submit)."""
        return self._thread is not None

    def start(self) -> bool:
        """Start the thread now, off any frame that writes (the launch's warm-up), so the
        first ``submit`` only queues. Does nothing for a synchronous writer, after ``stop``,
        or when the thread already runs. True when the thread is running."""
        with self._cond:
            if not self.threaded or self._closed:
                return False
            self._start_thread()
            return True

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self, until: float) -> bool:
        """At quit, after every owner's ``wait(until)``: no more submits; the thread
        finishes what is queued and ends, waiting until ``until`` at most. Past it, the
        jobs not yet started are dropped (each owner gets ``Failed("couldn't write")``),
        the thread is abandoned (a daemon; it may leave only its temp file), and False
        is returned. True when no thread remains."""
        with self._cond:
            self._closed = True
            self._stopping = True
            self._cond.notify_all()
            thread = self._thread
        if thread is None:
            return True
        while thread.is_alive():
            left = until - self._clock()
            if left <= 0:
                break
            thread.join(min(left, WAIT_SLICE_S))
        if not thread.is_alive():
            return True
        with self._cond:
            self._drop_queued()
            self.abandoned = True
        return False

    # --- Main-thread internals ---

    def _submit(self, client: WriterClient, job: Job) -> None:
        if not isinstance(job, (WriteRequest, FileWrite, FileRemove)):
            raise TypeError("the writer takes only WriteRequest, FileWrite, and FileRemove jobs")
        with self._cond:
            if self._closed:
                raise RuntimeError("the writer has stopped")
            client._in_flight += 1
            if self.threaded:
                self._queue.append((client, job))
                self._start_thread()                 # lazy: when nobody called start()
                self._cond.notify_all()
                return
        result = self._run(client, job)
        self._finish(client, result)

    def _start_thread(self) -> None:
        """Under the lock: the thread, once."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="vn-writer", daemon=True)
            self._thread.start()

    def _wait(self, client: WriterClient, until: float) -> None:
        with self._cond:
            while client._in_flight:
                left = until - self._clock()
                if left <= 0:
                    return
                self._cond.wait(min(left, WAIT_SLICE_S))

    def _finish(self, client: WriterClient, result: Result) -> None:
        with self._cond:
            client._in_flight -= 1
            client._results.append(result)
            self._cond.notify_all()

    def _drop_queued(self, only: WriterClient | None = None) -> None:
        """Jobs not yet started never start (``only``: just that client's). Takes the lock
        (a re-entrant one, so ``stop`` may call it while holding it)."""
        with self._cond:
            kept: deque[tuple[WriterClient, Job]] = deque()
            while self._queue:
                client, job = self._queue.popleft()
                if only is not None and client is not only:
                    kept.append((client, job))
                    continue
                client._in_flight -= 1
                client._results.append(Failed(COULDNT_WRITE, STOPPED_DETAIL, _token(job)))
            self._queue = kept
            self._cond.notify_all()

    # --- The thread ---

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._stopping:
                    self._cond.wait()
                if not self._queue:
                    return
                client, job = self._queue.popleft()
            self._finish(client, self._run(client, job))

    def _run(self, client: WriterClient, job: Job) -> Result:
        """One job, start to end. Never raises (an ``Exception`` becomes ``Failed``)."""
        token = _token(job)
        try:
            if isinstance(job, WriteRequest) and client.owner != PERSIST:
                return Failed(COULDNT_WRITE, OUTSIDE_DETAIL, token)
            if isinstance(job, FileRemove) and client.owner != META:
                return Failed(COULDNT_WRITE, OUTSIDE_DETAIL, token)
            if not client.accepts(job.folder, job.name):
                return Failed(COULDNT_WRITE, OUTSIDE_DETAIL, token)
            root = client.root
            if isinstance(job, FileRemove):
                return self._remove(root, job)
            # Meta jobs use the dev rule in every run (F31 TR-F31-04, ADR-0003).
            release = job.release and client.owner != META
            if not safefile.ensure_real_dir(root, release=release, create=True):
                return Failed(_folder_reason(root, release), "", token)
            target = root / job.name
            if isinstance(job, FileWrite):
                stamp = safefile.write_atomic(target, job.pieces, mode=FILE_MODE,
                                              replace_tries=limits.IO_TRIES, sleep=self._sleep)
                return FileWritten(job.token, stamp)
            return self._stamped(target, job)
        except Exception as exc:          # the thread must survive anything a job raises
            return Failed(reason_for(exc), _detail(exc), token)

    def _remove(self, root: Path, job: FileRemove) -> Result:
        """F31 ``04`` §6.4: a missing root is MISSING (never created); a root that isn't a
        real folder by the dev rule fails with its reason; else ``remove_file``."""
        if safefile.current_stamp(root) is None:
            return FileRemoved(job.token, RemoveKind.MISSING)
        if not safefile.ensure_real_dir(root, release=False, create=False):
            return Failed(_folder_reason(root, False), "", job.token)
        return FileRemoved(job.token, safefile.remove_file(root / job.name))

    def _stamped(self, target: Path, req: WriteRequest) -> Result:
        """§7.5 steps 2–4 (SEC-F12-06c). A target deleted under us is written as missing;
        after ``IO_TRIES`` such rounds, ``couldn't write``."""
        for _ in range(limits.IO_TRIES):
            expected = req.expected
            if req.check:
                now = safefile.current_stamp(target)
                if now is not None and now != expected:
                    changed = self._read_changed(target)
                    if changed is not None:
                        return changed
                    continue
                expected = now
            try:
                stamp = safefile.write_atomic(target, req.pieces, check=req.check,
                                              expected=expected, mode=FILE_MODE,
                                              replace_tries=limits.IO_TRIES, sleep=self._sleep)
            except TargetChanged:
                changed = self._read_changed(target)
                if changed is not None:
                    return changed
                continue
            return Written(stamp, req.version)
        return Failed(COULDNT_WRITE, CHANGING_DETAIL)

    def _read_changed(self, target: Path) -> Changed | None:
        """Read the changed target (only this owner's own file); None if it is missing."""
        result = safefile.read_regular(target, limits.FILE_MAX_BYTES)
        for _ in range(limits.IO_TRIES - 1):
            if result.kind is not ReadKind.UNREADABLE:
                break
            self._sleep(READ_RETRY_S)
            result = safefile.read_regular(target, limits.FILE_MAX_BYTES)
        if result.kind is ReadKind.MISSING:
            return None
        return Changed(result.stamp, result.data, result.kind)


def _token(job: object) -> int:
    return job.token if isinstance(job, (FileWrite, FileRemove)) else 0


def _folder_reason(root: Path, release: bool) -> str:
    """Why ``ensure_real_dir`` refused the root (F16 ``04`` §5.3): an entry that isn't a
    real directory (a link, a junction, a file), or a dev root reached through a link,
    is ``the folder is a link``; anything else (it couldn't be created) ``no permission``."""
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        return NO_PERMISSION
    except OSError as exc:
        return reason_for(exc)
    if (not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode)
            or getattr(st, "st_file_attributes", 0) & _REPARSE_POINT or os.path.isjunction(root)):
        return FOLDER_IS_LINK
    if not release:
        try:
            if (os.path.normcase(os.path.realpath(root))
                    != os.path.normcase(os.path.abspath(root))):
                return FOLDER_IS_LINK
        except (OSError, ValueError):
            pass
    return NO_PERMISSION


__all__ = ["COULDNT_WRITE", "Changed", "DISK_FULL", "FLOW", "FOLDER_IS_LINK", "Failed",
           "FileRemove", "FileRemoved", "FileWrite", "FileWritten", "META", "NO_PERMISSION",
           "OWNERS", "PERSIST", "REASONS",
           "Result", "SAVE", "SETTINGS", "WRITER_THREADED", "WriteRequest", "Writer",
           "WriterClient", "Written", "reason_for"]
