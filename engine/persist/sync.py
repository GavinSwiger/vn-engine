"""Keeping ``persistent.json`` in step with the store: when to write, merging what another
copy of the game wrote, and orderly ends (F12 checklist step 5; ``04-technical.md`` §7.5–7.7;
SEC-F12-03(c), -06(c), -07, -08; ADR-0007 "one writer, several owners").

Why this module exists: persistent data changes about once per line, a write must never stall
a frame, and two copies of a game may share one file. ``PersistentSync`` (``App.persist``)
runs once per frame on the main thread, encodes the store from cached pieces, hands the bytes
to the one writer thread, and turns the writer's results into store bookkeeping, merges, and
warnings.

- **When:** ``update(now)`` writes when the mode is WRITABLE, nothing is in flight or merging,
  the store's ``version`` is neither the last written nor the last failed one, and a second
  has passed since the last write started (or ``flush_soon`` asked). A failure (W52, once per
  session) isn't retried until the store changes again.
- **Encoding** never blocks a frame on a full encode: the encoder is warmed up and kept up to
  date in ``ENCODE_SLICE_S`` slices (``warm`` takes longer slices at launch), and a write
  waits for it.
- **Merging** (``MergeJob``, ``04`` §7.6): a ``Changed`` result runs a ``ReadJob`` in merge
  mode in ``MERGE_SLICE_S`` slices, then writes. After ``MERGES_IN_A_ROW_MAX`` merges in a
  row the merge skips values and the next request goes without the stamp check (SEC-F12-08)
  — but only when one ``lstat`` on the main thread shows the file is still the one that
  merge classified; otherwise the request is checked, so a newer or damaged file planted in
  between is classified first and never overwritten.
- **Bad files found by a merge:** BAD → moved to ``persistent.bad.json`` (W50 once) and ours
  is written; if the move fails, READ_ONLY. Unreadable → W50 ``couldn't be read``, no rename,
  READ_ONLY (SEC-F12-03c). NEWER → W51, READ_ONLY, never overwritten.
- **Ends** (§7.7): ``flush_now`` (error screen, F30) and ``close`` (quit) never start a write
  while one is in flight and wait at most until their deadline (``CLOSE_WAIT_S``); a final
  write that can't finish in time is skipped with W52 (SEC-F12-07).
- **Replay sandbox** (F36 ``04`` §7.2): while ``store.in_sandbox``, ``update`` only drains
  unlocks (a write in flight or a merge waits until it ends), ``flush_now`` writes nothing,
  and ``close`` puts the store back first. A crash mid-replay writes nothing.
- **Unlocks** are drained from the store every frame and passed to the listeners (F34, F37),
  on the main thread. ``take_notices`` drains this session's W50–W52 for a later toast
  (SEC-F12-12, ``07`` I-9).

Main thread only. File-system calls are the writer's, except two cheap ones here: the
``lstat`` before a forced write and the quarantine rename (``safefile.quarantine``).
"""

import enum
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from engine.core import safefile
from engine.core.logsetup import get_logger
from engine.core.safefile import Stamp
from engine.persist import limits
from engine.persist.fileformat import (UNREADABLE, MergeRules, Outcome, PieceEncoder, ReadJob,
                                       ReadOutcome, outcome_of_read)
from engine.persist.location import BAD_NAME, FILE_NAME
from engine.persist.texts import (SAVED_AGAIN_TEXT, bad_file_text, final_write_skipped_text,
                                  newer_file_text, save_failed_text)
from engine.persist.writer import (PERSIST, Changed, Failed, Result, Writer, WriterClient,
                                   WriteRequest, Written)
from engine.runtime.persistent import PersistentStore, scheme_text


class Mode(enum.Enum):
    WRITABLE = "writable"        # read at launch (or missing); written as it changes
    READ_ONLY = "read only"      # a file we must not overwrite: newer, unreadable, unmovable
    MEMORY = "memory"            # no folder (--no-persistent, W53, W52 at launch)


WRITABLE = Mode.WRITABLE
READ_ONLY = Mode.READ_ONLY
MEMORY = Mode.MEMORY

FLUSH_ROUNDS = 2 * limits.MERGES_IN_A_ROW_MAX + 4   # write / merge rounds one flush may take
UNKNOWN_STAMP = Stamp(-1, -1, -1)    # matches no file: the next write is checked and reads it


@dataclass(frozen=True, slots=True)
class Notice:
    """A file warning shown to the player later (SEC-F12-12): its code and text."""

    code: str
    text: str


class MergeJob:
    """Merges the bytes of a ``Changed`` result into the store (``04`` §7.6), in slices.
    ``outcome`` is set once done. A read that gave no bytes (unreadable, not a regular file,
    over the cap) is decided at once."""

    def __init__(self, changed: Changed, store: PersistentStore, program: object, *,
                 values: bool = True) -> None:
        self.stamp: Stamp | None = changed.stamp
        self.outcome: ReadOutcome | None = outcome_of_read(changed.read)
        self.steps = 0
        self._job: ReadJob | None = None
        if self.outcome is None:
            if changed.data is None:
                self.outcome = ReadOutcome(Outcome.UNREADABLE, UNREADABLE)
            else:
                self._job = ReadJob(changed.data, store, program,
                                    merge=MergeRules(values=values))

    @property
    def done(self) -> bool:
        return self.outcome is not None

    def run_for(self, until: float, clock: Callable[[], float]) -> bool:
        """Steps until done or ``clock() >= until`` (at least one step); True when done."""
        while self.outcome is None:
            assert self._job is not None
            self.steps += 1
            if self._job.step():
                self.outcome = self._job.outcome
                self._job = None
                break
            if clock() >= until:
                break
        return self.outcome is not None

    def run(self) -> ReadOutcome:
        """Every step at once (``flush_now``, ``close``)."""
        self.run_for(math.inf, lambda: 0.0)
        assert self.outcome is not None
        return self.outcome


class PersistentSync:
    """``App.persist``: the store's file, written from the frame loop (``04`` §5.2).

    ``folder`` is the persistent folder (None in MEMORY) and ``stamp`` the file's stamp from
    the launch read (None: no file). ``clock`` measures the merge and warm-up slices
    (seconds). ``writer`` is the process's one ``Writer`` (``App.writer``); without one, the
    sync builds its own (``WRITER_THREADED`` decides) and stops it in ``close``. ``release``
    goes into each request (the writer's folder rule)."""

    def __init__(self, store: PersistentStore, program: object, *, mode: Mode,
                 folder: Path | None, stamp: Stamp | None,
                 clock: Callable[[], float] = time.monotonic,
                 log: logging.Logger | None = None, writer: Writer | None = None,
                 release: bool = False, encoder: PieceEncoder | None = None) -> None:
        if not isinstance(mode, Mode):
            raise TypeError("mode must be a Mode")
        if mode is WRITABLE and folder is None:
            raise ValueError("a writable sync needs its folder")
        self.store = store
        self.mode = mode
        self.folder = Path(folder) if folder is not None else None
        self.expected = stamp
        self.clock = clock
        self.log = log if log is not None else get_logger("persist")
        self.release = release
        self.encoder = encoder if encoder is not None else PieceEncoder(program)
        self._program = program
        self._own_writer = writer is None and mode is WRITABLE
        self._writer = Writer() if self._own_writer else writer
        self._client: WriterClient | None = None
        if mode is WRITABLE:
            assert self._writer is not None and self.folder is not None
            self._client = self._writer.client(PERSIST, root=self.folder,
                                               names=frozenset({FILE_NAME}))
        self.written = store.version         # what the file holds (as far as we know)
        self.failed_at: int | None = None
        self.last_start = -math.inf
        self.merges_in_row = 0
        self.merge: MergeJob | None = None
        self.last_request: WriteRequest | None = None
        self.requests = 0                    # requests submitted this session
        self.merges = 0                      # merges started this session
        self._in_flight: int | None = None   # the version of the request in flight
        self._soon = False
        self._now = -math.inf
        self._listeners: list[Callable[[str, str], None]] = []
        self._notices: list[Notice] = []
        self._warned: set[str] = set()
        self._closed = False

    # --- Seams ---------------------------------------------------------------------------

    @property
    def program(self) -> object:
        return self._program

    @program.setter
    def program(self, program: object) -> None:
        """A reloaded story (F39): later merges and trims use it."""
        self._program = program
        self.encoder.program = program

    @property
    def in_flight(self) -> bool:
        return self._in_flight is not None

    @property
    def closed(self) -> bool:
        return self._closed

    def add_unlock_listener(self, fn: Callable[[str, str], None]) -> None:
        """``fn(kind, name)`` once per new unlock, from ``update`` on the main thread (F34,
        F37)."""
        self._listeners.append(fn)

    def take_notices(self) -> tuple[Notice, ...]:
        """This session's W50–W52 since the last call, once each (SEC-F12-12's toast)."""
        notices = tuple(self._notices)
        self._notices.clear()
        return notices

    def add_launch_notice(self, key: str, code: str, text: str) -> None:
        """A warning the launch read already logged (``app/persistence.py``): kept for
        ``take_notices`` and counted under ``key`` for the once-per-session rule, so a
        merge doesn't log the same warning again. Not logged here."""
        if key in self._warned:
            return
        self._warned.add(key)
        self._notices.append(Notice(code, text))

    def warm(self, until: float) -> bool:
        """Build the encoder's caches until ``clock() >= until`` (launch slices); True when
        done. ``update`` goes on in ``ENCODE_SLICE_S`` slices."""
        if self.mode is not WRITABLE or self._closed:
            return True
        return self.encoder.warm(self.store, until, self.clock)

    # --- The frame slot (§7.5) ---------------------------------------------------------------

    def update(self, now: float) -> None:
        """Once per frame, after dispatch: unlocks to listeners, the writer's result, a merge
        slice, a warm-up slice, and a write when one is due."""
        if self._closed:
            return
        self._now = now
        self._drain_unlocks()
        if self.mode is not WRITABLE or self.store.in_sandbox:
            return          # F36: no result taken, no merge slice, no write in a replay
        self._take_results()
        if self.merge is not None:
            if self.merge.run_for(self.clock() + limits.MERGE_SLICE_S, self.clock):
                self._merged()
            if self.mode is not WRITABLE or self.merge is not None:
                return
        warm = self.encoder.warm(self.store, self.clock() + limits.ENCODE_SLICE_S, self.clock)
        if warm and self._due(now):
            self._submit(now)

    def flush_soon(self) -> None:
        """Write at the next ``update`` that may write, without waiting for the interval
        (story end)."""
        self._soon = True

    def flush_now(self, until: float | None = None) -> bool:
        """Write everything now (error screen, F30): wait for a write in flight, finish a
        merge, write, and merge again if another copy changed the file, until the file holds
        the store or the writer's clock reaches ``until`` (default: ``CLOSE_WAIT_S`` from
        now). Never two writes at once. True when the file holds the store. While the
        replay sandbox is open it writes nothing and returns False (F36 ``04`` §7.2: F30's
        fake crash calls it, and must neither write the replay nor end the sandbox)."""
        if self._closed or self.mode is not WRITABLE or self.store.in_sandbox:
            return False
        assert self._client is not None and self._writer is not None
        deadline = self._writer.quit_deadline() if until is None else until
        for _ in range(FLUSH_ROUNDS):
            if self._in_flight is not None:
                for result in self._client.wait(deadline):
                    self._handle(result)
                if self._in_flight is not None:
                    return False                      # still in flight at the deadline
            else:
                self._take_results()
            if self.mode is not WRITABLE:
                return False
            if self.merge is not None:
                self.merge.run()
                self._merged()
                if self.mode is not WRITABLE:
                    return False
            version = self.store.version
            if version == self.written:
                return True
            if version == self.failed_at or self._writer.now() >= deadline:
                return False
            self._submit(self._now)
        return False

    def close(self, until: float | None = None) -> None:
        """Quit (``App.run``'s ``finally``): wait for a write in flight, then write what is
        unwritten, all by ``until`` (default ``CLOSE_WAIT_S`` from now; the App passes the
        writer's shared quit deadline). A write that can't finish by then is skipped with
        W52. A writer the sync built is stopped (abandoned past the deadline). Runs once.
        An open replay sandbox is put back first (F36), so a quit mid-replay writes the old
        content plus the kept unlocks."""
        if self._closed:
            return
        deadline = until
        if deadline is None and self._writer is not None:
            deadline = self._writer.quit_deadline()
        try:
            self.store.end_sandbox()
            if self.mode is WRITABLE and self._unfinished() and not self.flush_now(deadline):
                if self.mode is WRITABLE and self._unfinished():
                    self._warn("W52-quit", "W52", final_write_skipped_text(self.store.display))
        finally:
            self._closed = True
            self.merge = None
            self.encoder.detach()
            if self._own_writer and self._writer is not None and deadline is not None:
                self._writer.stop(deadline)

    # --- Internals ---------------------------------------------------------------------------

    def _unfinished(self) -> bool:
        version = self.store.version
        return (self._in_flight is not None or self.merge is not None
                or version not in (self.written, self.failed_at))

    def _drain_unlocks(self) -> None:
        for kind, name in self.store.take_new_unlocks():
            for listener in tuple(self._listeners):
                listener(kind, name)

    def _due(self, now: float) -> bool:
        version = self.store.version
        return (self._in_flight is None and self.merge is None
                and version != self.written and version != self.failed_at
                and (self._soon or now - self.last_start >= limits.WRITE_MIN_INTERVAL_S))

    def _submit(self, now: float) -> None:
        assert self._client is not None and self.folder is not None
        pieces = self.encoder.encode(self.store)     # may trim (W57), which is a change too
        version = self.store.version
        check = True
        if self.merges_in_row >= limits.MERGES_IN_A_ROW_MAX:
            check = not self._target_unchanged()
        request = WriteRequest(self.folder, pieces, self.expected, check, version,
                               self.release)
        self._in_flight = version
        self.last_start = now
        self._soon = False
        self.last_request = request
        self.requests += 1
        self._client.submit(request)

    def _target_unchanged(self) -> bool:
        """SEC-F12-08: the file is still the one the last merge classified."""
        assert self.folder is not None
        try:
            return safefile.current_stamp(self.folder / FILE_NAME) == self.expected
        except OSError:
            return False

    def _take_results(self) -> None:
        assert self._client is not None
        for result in self._client.take():
            self._handle(result)

    def _handle(self, result: Result) -> None:
        version = self._in_flight
        self._in_flight = None
        if isinstance(result, Written):
            self.expected = result.stamp
            self.store.mark_synced(result.version)
            self.written = result.version
            self.failed_at = None
            self.merges_in_row = 0
            if "W52" in self._warned and "saved again" not in self._warned:
                self._warned.add("saved again")
                self.log.info("%s", SAVED_AGAIN_TEXT)
        elif isinstance(result, Changed):
            self.merges += 1
            self.merge = MergeJob(result, self.store, self._program,
                                  values=self.merges_in_row < limits.MERGES_IN_A_ROW_MAX)
        elif isinstance(result, Failed):
            self.failed_at = version
            if result.detail:
                self.log.debug("persistent data write failed (%s): %s", result.reason,
                               result.detail)
            self._warn("W52", "W52", save_failed_text(self.store.display, result.reason))

    def _merged(self) -> None:
        job = self.merge
        assert job is not None and job.outcome is not None
        self.merge = None
        outcome = job.outcome
        file = self.store.display
        if outcome.kind is Outcome.OK:
            self.expected = job.stamp
            self.merges_in_row += 1
            self._soon = True
            if outcome.dropped and "W54" not in self._warned:
                self._warned.add("W54")
                self.store.warn_dropped(outcome.dropped)
            if outcome.scheme_changed and "W55" not in self._warned:
                self._warned.add("W55")
                self.store.log.warning("%s", scheme_text(file), extra={"code": "W55"})
        elif outcome.kind is Outcome.NEWER:
            self._read_only("W51", "W51", newer_file_text(file, mid_session=True))
        elif outcome.kind is Outcome.UNREADABLE:
            self._read_only("W50-unchanged", "W50",
                            bad_file_text(file, outcome.reason or UNREADABLE, kept=False,
                                          mid_session=True))
        else:
            self._quarantine(job.stamp, outcome.reason or "")

    def _quarantine(self, stamp: Stamp | None, reason: str) -> None:
        """A BAD file another writer left: move it to ``persistent.bad.json`` and write ours
        (SEC-F12-03). If the file was replaced again since it was read, it is read again
        at the next (checked) write instead."""
        assert self.folder is not None
        target = self.folder / FILE_NAME
        self._soon = True
        self.merges_in_row += 1
        try:
            now = safefile.current_stamp(target)
        except OSError:                    # can't tell: the next write is checked and reads it
            self.expected = UNKNOWN_STAMP
            return
        if now is None:                    # gone already: ours is written as new
            self.expected = None
            return
        if now != stamp:                   # replaced again: the next write is checked and reads it
            self.expected = UNKNOWN_STAMP
            return
        if safefile.quarantine(target, BAD_NAME):
            self.expected = None
            self._warn("W50", "W50", bad_file_text(self.store.display, reason, kept=True,
                                                   mid_session=True))
            return
        self._read_only("W50-unchanged", "W50",
                        bad_file_text(self.store.display, reason, kept=False,
                                      mid_session=True))

    def _read_only(self, key: str, code: str, text: str) -> None:
        self.mode = READ_ONLY
        self.merge = None
        self.encoder.detach()
        self._warn(key, code, text)

    def _warn(self, key: str, code: str, text: str) -> None:
        """Log ``code`` once per session per ``key``; remember it for ``take_notices``."""
        if key in self._warned:
            return
        self._warned.add(key)
        self.log.warning("%s", text, extra={"code": code})
        self._notices.append(Notice(code, text))


__all__ = ["MEMORY", "MergeJob", "Mode", "Notice", "PersistentSync", "READ_ONLY", "WRITABLE"]
