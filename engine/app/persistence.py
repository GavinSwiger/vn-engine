"""Persistent data at launch and in the App: ``open_for_launch`` and ``install_persistence``
(F12 checklist step 6; ``04-technical.md`` §7.4, §7.7; SEC-F12-03, -06, -13; ``07`` I-1, I-7).

Why this module exists: the persistent file is read once per launch, after F02's load and
before the first ``define`` (invariant 10: everything is in the store before the first
line), and a damaged, newer, or unreachable file must never stop the game or be lost
(PR-F12-12..14). ``StoryLoadScreen`` (``app/loading.py``) drives it:

1. ``open_for_launch`` decides where the data lives and does the launch's few file-system
   calls: ``--no-persistent`` (INFO) or a release run without ``[game] id`` (W53) touch no
   file and run in MEMORY; otherwise the folder (``persistent_root``) must be a real
   directory (``safefile.ensure_real_dir``; else W52, MEMORY), old temp files are removed
   (``remove_stale_temps``: ≤ 1,000 entries examined, ≤ 16 removed), and
   ``persistent.json`` is read with ``safefile.read_regular`` (≤ 32 MiB + 1 bytes).
2. ``PersistentLaunch.run_for`` steps the ``ReadJob`` in the load screen's ≈ 50 ms slices.
   Then: OK → WRITABLE; NEWER → W51, fresh data, READ_ONLY (the file is never changed); BAD
   (not JSON, not persistent data, over the cap, not a regular file) → W50 and the entry is
   moved to ``persistent.bad.json`` (``safefile.quarantine``; one copy), or, if that move
   fails, READ_ONLY so the file is never overwritten; unreadable → W50, no rename, READ_ONLY
   (SEC-F12-03).
3. ``LaunchJob`` runs the defines and phase 2b on the same store (F12 step 3a).
4. ``install_persistence`` builds ``PersistentSync`` on ``App.writer``, starts the writer's
   thread when the data can be written (``Writer.start``: the first write's frame never
   pays the thread start), and sets ``App.persist``; the load screen warms its encoder in
   the same slices
   (``PersistentSync.warm``), so the first write never costs a full encode on a frame.

The App then calls ``App.persist.update`` once per frame (after dispatch, before audio),
``flush_now`` from ``show_fatal_error``, and ``close`` in ``run()``'s ``finally``
(``app/app.py``); ``StoryEnded`` calls ``flush_soon`` (``app/story.py``).

Messages give the file's display path and a fixed reason word only (SEC-F12-09). The
launch's W50–W52 also go to ``PersistentSync.take_notices`` (SEC-F12-12's later toast).
"""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from engine.core import safefile
from engine.core.logsetup import get_logger
from engine.core.safefile import ReadKind, Stamp
from engine.persist import limits
from engine.persist.fileformat import Outcome, ReadJob, ReadOutcome, outcome_of_read
from engine.persist.location import BAD_NAME, FILE_NAME, display_file, persistent_root
from engine.persist.sync import MEMORY, READ_ONLY, WRITABLE, Mode, PersistentSync
from engine.persist.texts import (NO_ID_TEXT, OFF_TEXT, bad_file_text, newer_file_text,
                                  save_failed_text)
from engine.persist.writer import NO_PERMISSION
from engine.persist.writer import _folder_reason as folder_reason   # F16 04 §5.3's one rule
from engine.runtime.persistent import IDENTITY_SCHEME, PersistentStore

if TYPE_CHECKING:
    from engine.app.app import App


@dataclass(frozen=True, slots=True)
class LaunchNotice:
    """A warning the launch logged: its once-per-session key (``PersistentSync``'s), code,
    and text."""

    key: str
    code: str
    text: str


class PersistentLaunch:
    """``open_for_launch``'s result: the session's store and, while ``done`` is False, the
    ``ReadJob`` still to step. Once done, ``mode``, ``folder``, and ``stamp`` are what
    ``install_persistence`` gives ``PersistentSync``."""

    def __init__(self, store: PersistentStore, program: object, *, mode: Mode,
                 folder: Path | None, release: bool, log: logging.Logger) -> None:
        self.store = store
        self.program = program
        self.mode = mode
        self.folder = folder
        self.release = release
        self.log = log
        self.stamp: Stamp | None = None
        self.job: ReadJob | None = None
        self.outcome: ReadOutcome | None = None
        self.notices: list[LaunchNotice] = []
        self.memory_only = False            # F32 --playthrough: read, then keep MEMORY

    @property
    def done(self) -> bool:
        return self.job is None

    @property
    def path(self) -> Path | None:
        return None if self.folder is None else self.folder / FILE_NAME

    def step(self) -> bool:
        """One ``ReadJob`` step; True when the read is over (its outcome decided)."""
        job = self.job
        if job is None:
            return True
        if job.step():
            self.job = None
            assert job.outcome is not None
            self._decide(job.outcome)
        return self.job is None

    def run_for(self, until: float, clock: Callable[[], float], *,
                at_least_one: bool = True) -> bool:
        """Steps until done or ``clock() >= until``; with ``at_least_one`` the first step
        runs even past ``until``. True when done."""
        while self.job is not None:
            if not at_least_one and clock() >= until:
                return False
            at_least_one = False
            self.step()
        return True

    def run(self) -> "PersistentLaunch":
        """Every step at once (tests, tools)."""
        self.run_for(math.inf, lambda: 0.0)
        return self

    # --- Outcomes (04 §7.4 steps 4, 6, 7) ---------------------------------------------------

    def _decide(self, outcome: ReadOutcome) -> None:
        self.outcome = outcome
        file = self.store.display
        if outcome.kind is Outcome.OK:
            self.mode = WRITABLE
        elif outcome.kind is Outcome.NEWER:
            self.stamp = None
            self._warn("W51", "W51", newer_file_text(file))
            self.mode = READ_ONLY
        elif outcome.kind is Outcome.UNREADABLE:
            self.stamp = None
            self._warn("W50-unchanged", "W50",
                       bad_file_text(file, outcome.reason or "", kept=False))
            self.mode = READ_ONLY
        else:                                    # BAD: kept as persistent.bad.json, one copy
            self.stamp = None
            path = self.path
            assert path is not None
            if safefile.quarantine(path, BAD_NAME):
                self._warn("W50", "W50", bad_file_text(file, outcome.reason or "", kept=True))
                self.mode = WRITABLE
            else:                                # never overwritten (SEC-F12-03b)
                self._warn("W50-unchanged", "W50",
                           bad_file_text(file, outcome.reason or "", kept=False))
                self.mode = READ_ONLY

    def _warn(self, key: str, code: str, text: str) -> None:
        self.log.warning("%s", text, extra={"code": code})
        self.notices.append(LaunchNotice(key, code, text))


def open_for_launch(program: object, *, game_root: Path | None, release: bool,
                    app_id: str | None, off: bool = False, memory_only: bool = False,
                    log: logging.Logger | None = None) -> PersistentLaunch:
    """§7.4 steps 1–4: the session's store, its mode, and the launch read (not yet stepped).

    ``off`` is ``--no-persistent`` (dev runs only). ``app_id`` is ``[game] id`` as
    configured (None when it isn't set; the log folder's fallback slug never counts).
    ``memory_only`` (F32's ``--playthrough N``) reads the file as usual but keeps the mode
    MEMORY, so nothing is written or created.
    Neither ``off`` nor a release run without an id touches the file system. Never raises
    ``OSError``."""
    log = log if log is not None else get_logger("persist")
    scheme = getattr(program, "identity_scheme", IDENTITY_SCHEME)
    store = PersistentStore(identity_scheme=scheme, log=log)
    launch = PersistentLaunch(store, program, mode=MEMORY, folder=None, release=release,
                              log=log)
    launch.memory_only = memory_only
    if off:
        log.info("%s", OFF_TEXT)
        return launch
    if release and app_id is None:
        log.warning("%s", NO_ID_TEXT, extra={"code": "W53"})
        return launch
    folder = None
    if game_root is not None or release:
        folder = persistent_root(game_root=game_root, release=release, app_id=app_id)
    if folder is None:
        launch._warn("W52", "W52", save_failed_text(store.display, NO_PERMISSION))
        return launch
    store.display = display_file(folder, game_root=game_root)
    if not safefile.ensure_real_dir(folder, release=release):
        launch._warn("W52", "W52", save_failed_text(store.display,
                                                    folder_reason(folder, release)))
        return launch
    launch.folder = folder
    safefile.remove_stale_temps(folder, FILE_NAME, max_age_s=limits.TEMP_STALE_S,
                                max_examined=limits.TEMP_SCAN_MAX,
                                max_removed=limits.TEMP_CLEANUP_MAX)
    result = safefile.read_regular(folder / FILE_NAME, limits.FILE_MAX_BYTES)
    if result.kind is ReadKind.MISSING:
        launch.mode = WRITABLE                 # fresh data; the first write creates it
        return launch
    if result.kind is ReadKind.OK:
        assert result.data is not None
        launch.stamp = result.stamp
        launch.job = ReadJob(result.data, store, program)
        return launch
    outcome = outcome_of_read(result)
    assert outcome is not None
    launch._decide(outcome)
    return launch


def install_persistence(app: "App", launch: PersistentLaunch) -> PersistentSync:
    """§7.4 step 9: ``App.persist`` becomes the session's ``PersistentSync`` on
    ``App.writer`` (owner ``persist``), with the launch's warnings counted for
    ``take_notices`` and the once-per-session rule. Once per launch, after the read."""
    assert launch.done, "install_persistence needs the finished launch read"
    mode = MEMORY if launch.memory_only else launch.mode
    sync = PersistentSync(launch.store, launch.program, mode=mode,
                          folder=launch.folder if mode is not MEMORY else None,
                          stamp=launch.stamp, log=launch.log,
                          writer=getattr(app, "writer", None), release=launch.release)
    for notice in launch.notices:
        sync.add_launch_notice(notice.key, notice.code, notice.text)
    writer = getattr(app, "writer", None)
    if mode is WRITABLE and writer is not None:
        writer.start()          # in the load slice, not on the first write's frame (AC-F12-45)
    app.persist = sync
    return sync


__all__ = ["LaunchNotice", "PersistentLaunch", "install_persistence", "open_for_launch"]
