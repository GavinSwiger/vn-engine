"""The live map's background watch of ``script/**`` (F58 ``04-technical.md`` §7.1; ``01``
PR-F58-01, 09, 18, 20, 24; ``07`` I-1 to I-3; ADR-0008 Amendment 6 §2).

A daemon thread lists the game's ``script/`` folder every ``WATCH_MS`` (``SLOW_WATCH_MS``
while a listing takes over ``SLOW_LISTING_MS``, PR-24), reads the ``.vns`` files whose
directory-entry stamp changed, and posts one ``FileNews`` per file to a ``Mailbox`` that
the Tk thread polls. It never touches Tk and never writes. ``stop()`` never waits for it.

- **Listing** (``scan``): ``os.scandir``, links and junctions skipped, F45's walk caps; the
  stamp is ``DirEntry.stat(follow_symlinks=False)`` (no system call on Windows, one
  ``lstat`` on POSIX; C3). Only ``.vns`` names under ``script/``: write temps
  (``.<name>.<tok>.tmp``) fail the suffix test.
- **Reads** go through ``document.open_document`` with the watch's own ``GamePaths``
  (I-1), whose listing cache is dropped whenever the listed names change. A directory-entry
  stamp only decides *whether* to read (I-2): "moved during the read" compares two
  ``os.stat`` stamps, taken before and after, and the news carries the after-stamp, which
  Tk compares with its own saves' ``doc.stamp`` (own writes are quiet, PR-20). A file that
  moved, or didn't decode, is read again next tick; ``ScriptError`` up to
  ``READ_TRIES`` times per stamp, then posted as ``unreadable``.
- **Budget** (I-3, R1): about ``TICK_READ_BYTES`` of reads per tick, at most one file over
  ``BIG_FILE_BYTES``; a file over ``BIG_FILE_BYTES`` with mixed line endings isn't decoded
  here (``check_only``: the map takes it from the check; main-session ruling on P0). The
  caps (``livemap.IndexBudget``: 16 MiB a file, 64 MiB or 2,000 files in all) post
  ``capped`` and never read. With ``lists_only`` (S4 pending) nothing is read.
- **News**: an open file's news carries the decoded ``ScriptDocument`` (Tk reloads from it,
  no second read); a closed file's carries its text, and its document too unless it has
  mixed line endings (no ``old_lines`` ever travels for a closed file, I-3), so Studio can
  open it later without reading it again (main-session ruling on R2). One mailbox entry per
  file, the newest winning (PR-09).
"""

import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from engine.core.errors import EngineError
from engine.core.paths import GamePaths
from engine.script.diagnostics import ScriptError
from engine.script.limits import (
    SCRIPT_FILE_MAX_BYTES, SCRIPT_WALK_MAX_DEPTH, SCRIPT_WALK_MAX_ENTRIES)
from engine.tools.editor.document import (
    SCRIPT_DIR, SCRIPT_SUFFIX, ScriptDocument, open_document)
from engine.tools.editor.livemap import IndexBudget

WATCH_MS: Final = 250
SLOW_WATCH_MS: Final = 2_000            # PR-24: while listings are slow
SLOW_LISTING_MS: Final = 200
TICK_READ_BYTES: Final = 8 * 1024 * 1024        # I-3: reads per tick (one file always goes)
BIG_FILE_BYTES: Final = 1024 * 1024     # R1: at most one such file a tick; mixed: check only
READ_TRIES: Final = 3

# News kinds.
CHANGED: Final = "changed"              # read: a new text (or a new file)
REMOVED: Final = "removed"
CAPPED: Final = "capped"                # over a cap (S6): never read
UNREADABLE: Final = "unreadable"        # failed READ_TRIES times at this stamp
CHECK_ONLY: Final = "check_only"        # big, mixed line endings: left to the check
LISTED: Final = "listed"                # a new stamp while ``lists_only``: not read

Stamp = tuple[int, int]                 # (st_mtime_ns, st_size)


@dataclass(frozen=True, slots=True)
class FileNews:
    """One file's news. ``stamp``: ``os.stat`` after the read (``CHANGED``), else the
    listing's. ``doc``: the decoded document (open files); ``text``: closed files'."""

    ref: str
    kind: str
    stamp: Stamp | None = None
    text: str | None = None
    doc: ScriptDocument | None = None
    error: str | None = None


class Mailbox:
    """One entry per ref, the newest winning; ``take()`` swaps the dict under the lock."""

    __slots__ = ("_lock", "_news")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._news: dict[str, FileNews] = {}

    def post(self, news: FileNews) -> None:
        with self._lock:
            self._news.pop(news.ref, None)
            self._news[news.ref] = news

    def take(self) -> dict[str, FileNews]:
        with self._lock:
            found, self._news = self._news, {}
        return found

    def __len__(self) -> int:
        return len(self._news)


def scan(root: Path, *, max_entries: int = SCRIPT_WALK_MAX_ENTRIES,
         max_depth: int = SCRIPT_WALK_MAX_DEPTH) -> dict[str, Stamp]:
    """``script/**``'s ``.vns`` refs → directory-entry stamps, breadth first in sorted
    order (links and junctions skipped, F45's caps). Never calls ``os.stat``."""
    found: dict[str, Stamp] = {}
    queue: list[tuple[str, str, int]] = [(SCRIPT_DIR, str(root / SCRIPT_DIR), 0)]
    counted = 0
    for prefix, folder, depth in queue:
        try:
            with os.scandir(folder) as listing:
                entries = sorted(listing, key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if counted >= max_entries:
                return found
            counted += 1
            try:
                if entry.is_symlink() or entry.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        queue.append((f"{prefix}/{entry.name}", entry.path, depth + 1))
                elif entry.name.endswith(SCRIPT_SUFFIX) and not entry.name.startswith("."):
                    st = entry.stat(follow_symlinks=False)
                    found[f"{prefix}/{entry.name}"] = (st.st_mtime_ns, st.st_size)
            except OSError:
                continue
    return found


def _mixed(data: bytes) -> bool:
    crlf = data.count(b"\r\n")
    return (data.count(b"\n") - crlf > 0 and crlf > 0) or (data.count(b"\r") - crlf > 0
                                                          and data.count(b"\n") > 0)


class ScriptWatch:
    """The watch (see the module doc). Tests inject ``lister(root) -> {ref: stamp}``,
    ``reader(ref) -> ScriptDocument | ScriptError``, ``stat(path) -> stamp`` and ``clock``
    (seconds), and call ``tick()`` themselves; ``start()`` runs ticks on a daemon thread."""

    def __init__(self, root: Path, *, mailbox: Mailbox | None = None,
                 lister: Callable[[Path], Mapping[str, Stamp]] | None = None,
                 reader: Callable[[str], "ScriptDocument | ScriptError"] | None = None,
                 stat: Callable[[Path], Stamp] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 peek: Callable[[str], bytes | None] | None = None) -> None:
        self.root = Path(root)
        self.mailbox = mailbox or Mailbox()
        self._paths: GamePaths | None = None
        self._lister = lister or scan
        self._reader = reader or self._read
        self._stat = stat or self._os_stat
        self._peek = peek or self._head
        self._clock = clock
        self.seen: dict[str, Stamp] = {}        # listing stamps read (or settled)
        self._names: frozenset[str] = frozenset()
        self._tries: dict[tuple[str, Stamp], int] = {}
        self._posted: dict[str, tuple[str, Stamp]] = {}      # capped / check-only notices
        self._open: frozenset[str] = frozenset()
        self.lists_only = False
        self.started = 0                        # ticks begun and finished (Q2, I-7)
        self.finished = 0
        self.interval = WATCH_MS
        self.listing_ms = 0.0
        self.failed: BaseException | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- Tk side -------------------------------------------------------------------------------

    def set_open(self, refs: Iterable[str]) -> None:
        """The refs open in Studio (their news carries the document)."""
        self._open = frozenset(refs)

    def baseline(self, stamps: Mapping[str, Stamp]) -> None:
        """Stamps already known (Studio's first listing): not news."""
        self.seen.update(stamps)

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="vn-map-watch",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Ask the thread to end; never waits for it."""
        self._stop.set()

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- The thread ----------------------------------------------------------------------------

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(self.interval / 1000)
        except BaseException as exc:            # Studio falls back to the focus listing
            self.failed = exc
            raise

    def _os_stat(self, path: Path) -> Stamp:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size

    def _read(self, ref: str) -> "ScriptDocument | ScriptError":
        if self._paths is None:
            self._paths = GamePaths.for_game(self.root)
        return open_document(self._paths, ref)

    def _head(self, ref: str) -> bytes | None:
        """The file's bytes through the watch's ``GamePaths`` (I-1), for the mixed-endings
        test of a big file; None when it can't be read (the reader then reports it)."""
        if self._paths is None:
            self._paths = GamePaths.for_game(self.root)
        try:
            return self._paths.read_file(ref, max_bytes=SCRIPT_FILE_MAX_BYTES)
        except (EngineError, OSError):
            return None

    def tick(self) -> None:
        """One listing and its reads."""
        if self._stop.is_set():
            return
        tick = self.started = self.started + 1
        try:
            self._tick()
        finally:
            self.finished = tick

    def _tick(self) -> None:
        start = self._clock()
        listed = self._lister(self.root)
        self.listing_ms = (self._clock() - start) * 1000
        self.interval = SLOW_WATCH_MS if self.listing_ms > SLOW_LISTING_MS else WATCH_MS
        names = frozenset(listed)
        if names != self._names:
            self._names = names
            if self._paths is not None:
                self._paths.invalidate_listings()
        for ref in [ref for ref in self.seen if ref not in names]:
            del self.seen[ref]
            self._posted.pop(ref, None)
            self.mailbox.post(FileNews(ref, REMOVED))
        budget = IndexBudget()
        spent, big = 0, False
        for ref, stamp in listed.items():
            if self._stop.is_set():
                return
            if not budget.admit(ref, stamp[1]):
                if self._posted.get(ref) != (CAPPED, stamp):
                    self._posted[ref] = (CAPPED, stamp)
                    self.seen[ref] = stamp
                    self.mailbox.post(FileNews(ref, CAPPED, stamp))
                continue
            if self.seen.get(ref) == stamp:
                continue
            if self.lists_only:
                self.seen[ref] = stamp
                self.mailbox.post(FileNews(ref, LISTED, stamp))
                continue
            size = stamp[1]
            if spent and (spent + size > TICK_READ_BYTES or (big and size > BIG_FILE_BYTES)):
                continue                        # next tick
            spent += size
            big = big or size > BIG_FILE_BYTES
            self._read_one(ref, stamp)

    def _read_one(self, ref: str, listed: Stamp) -> None:
        path = self.root / ref
        try:
            before = self._stat(path)
        except OSError:
            return                              # gone meanwhile: the next listing says so
        if listed[1] > BIG_FILE_BYTES:
            data = self._peek(ref)
            if data is not None and _mixed(data):
                self.seen[ref] = listed
                self.mailbox.post(FileNews(ref, CHECK_ONLY, listed))
                return
        result = self._reader(ref)
        try:
            after = self._stat(path)
        except OSError:
            return
        if after != before:
            return                              # moved during the read: next tick
        if isinstance(result, ScriptError):
            key = (ref, listed)
            tries = self._tries[key] = self._tries.get(key, 0) + 1
            if tries >= READ_TRIES:
                del self._tries[key]
                self.seen[ref] = listed
                self.mailbox.post(FileNews(ref, UNREADABLE, after, error=result.format()))
            return
        self._tries = {k: v for k, v in self._tries.items() if k[0] != ref}
        self.seen[ref] = listed
        self._posted.pop(ref, None)
        if ref in self._open:
            self.mailbox.post(FileNews(ref, CHANGED, after, doc=result))
        else:
            self.mailbox.post(FileNews(ref, CHANGED, after, text=result.text,
                                       doc=None if result.mixed else result))


__all__ = ["BIG_FILE_BYTES", "CAPPED", "CHANGED", "CHECK_ONLY", "FileNews", "LISTED",
           "Mailbox", "READ_TRIES", "REMOVED", "SLOW_LISTING_MS", "SLOW_WATCH_MS",
           "ScriptWatch", "Stamp", "TICK_READ_BYTES", "UNREADABLE", "WATCH_MS", "scan"]
