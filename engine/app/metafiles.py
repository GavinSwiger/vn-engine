"""F31 meta files on disk: the disk files port and its wiring (F31 ``04-technical.md`` §4.3,
§6.2–§6.4, §6.7; ``05`` SEC-F31-01, -02, -06, -07, -08; run warnings W196–W198).

Why this module exists: the runtime never touches disk, so a ``file`` line asks a files port
(``runtime/metafiles.py``). In the game that port is ``DiskFolder``, the only code that turns a
``file`` line into work on ``<game>/characters/``:

- **Checks** (``exists``, ``read``) run at once on the main thread through ``meta.files``'
  ``MetaFolder`` (the one sandbox helper): the folder is checked on every call (a link, a
  junction, or a file there is W196 once, and every later ``file`` line does nothing), names
  are only the script's literal names (``MetaFolder.require``), and no link is followed.
- **Changes** (``write``, ``delete``) become writer jobs of owner ``meta`` (``FileWrite``,
  ``FileRemove``), always with ``release=False`` (the dev folder rule in every run). The frame
  pays only a copy's original read (``GamePaths.read_file("files/<name>", regular=True)``, at
  most ``META_ORIGINAL_MAX_BYTES``) and a queue append. At most ``META_IN_FLIGHT_MAX`` jobs are
  in flight (then W198 ``busy``). A small **overlay** of pending changes answers checks of a
  name until its job's result comes back, so the story reads its own writes (PR-F31-06).
- **``pump``** takes the writer's results (the ``MetaWrite``/``MetaDelete`` handlers call it,
  and every port call does first). A failure drops the overlay entry (the next check reads the
  disk) and is classified by what is at the name (``entry_kind``, no follow; SEC-F31-06): a
  folder or link there is W198 ``folder_at_name``; W197 (once; changes off) only for a folder
  that is itself unwritable before anything worked; a lock is never W197. W198 is capped at
  ``META_W198_MAX`` lines (then DEBUG). ``pump`` never raises. A writer ``Failed.detail``
  holds paths and is never read here.
- **Quit** (SEC-F31-08): ``App._close_writers`` calls ``drop_queued`` first, so at most the
  running meta job is ahead of F11's quit save; a shutdown hook takes the last results.

``MetaFiles`` (``runtime/metafiles.py``) already does the 256-change cap (W199), W200, and
``decode_note``; this module adds W196–W198 and the overlay. Warnings name only
``<game>/characters/<name>`` and fixed words; nothing here logs a path, an OS reason, or note
text, and the ``repr`` of a ``DiskFolder`` holds neither (SEC-F31-07). File calls: none here
directly (TR-F31-02): checks go through ``MetaFolder``, originals through ``GamePaths``, changes
through the writer.
"""

from typing import TYPE_CHECKING, Final

from engine.core.constants import (
    META_DIRNAME,
    META_IN_FLIGHT_MAX,
    META_ORIGINAL_MAX_BYTES,
    META_ORIGINALS_DIR,
    META_READ_MAX_BYTES,
    META_SHOWN,
    META_W198_MAX,
)
from engine.core.errors import AssetMissing, AssetNotFile, AssetRefError, AssetTooLarge
from engine.core.paths import META_NAME_RE, GamePaths
from engine.core.safefile import IS_POSIX, EntryKind, ReadKind, RemoveKind
from engine.meta.files import MetaFolder, RootState
from engine.persist.writer import (
    DISK_FULL,
    FOLDER_IS_LINK,
    META,
    NO_PERMISSION,
    Failed,
    FileRemove,
    FileRemoved,
    FileWrite,
    FileWritten,
    WriterClient,
)
from engine.runtime.commands import MetaDelete, MetaWrite
from engine.runtime.errors import format_message
from engine.runtime.metafiles import MetaFiles, ReadAnswer, attach

if TYPE_CHECKING:
    from logging import Logger

    from engine.app.app import App
    from engine.runtime.interpreter import Interpreter

_WRITE: Final = "write"
_DELETE: Final = "delete"


class _TooBig:
    """The overlay's marker for a pending write over ``META_READ_MAX_BYTES`` (W200 ``large``)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "TOO_BIG"


TOO_BIG: Final = _TooBig()


class DiskFolder:
    """The game's files port over ``<game>/characters/`` (04 §4.3, §6.3, §6.4). Main thread
    only; every method is bounded and never raises for anything the folder holds."""

    __slots__ = ("folder", "client", "paths", "log", "files", "usable", "read_only",
                 "succeeded", "_closing", "_cleaned", "_w198", "_token", "_tokens", "_pending")

    def __init__(self, folder: MetaFolder, client: WriterClient, paths: GamePaths,
                 log: "Logger") -> None:
        self.folder = folder
        self.client = client
        self.paths = paths
        self.log = log
        self.files: MetaFiles | None = None      # the session's rules (install_metafiles)
        self.usable = True                       # False after W196: every file line is off
        self.read_only = False                   # True after W197: changes are off
        self.succeeded = False                   # a change proved the folder writable
        self._closing = False                    # quit: failures are quiet from now on
        self._cleaned = False                    # the session's one stale-temp cleanup
        self._w198 = 0
        self._token = 0
        # token -> (name, verb, the MetaFolder that submitted it: its allow-list holds the
        # name even after an F39 reload's ``set_folder``).
        self._tokens: dict[int, tuple[str, str, MetaFolder]] = {}
        # name -> (token, present, kept bytes or TOO_BIG): the pending changes (PR-F31-06).
        self._pending: dict[str, tuple[int, bool, bytes | _TooBig | None]] = {}

    def __repr__(self) -> str:
        return f"DiskFolder({META_SHOWN.rstrip('/')}, {len(self._pending)} pending)"

    # --- FilesPort: checks (04 §6.3) ---

    def exists(self, name: str) -> bool:
        name = self.folder.require(name)
        overlay = self._check(name)
        if overlay is None:
            return False
        if overlay is not True:
            return overlay[1]
        return self.folder.exists(name)

    def read(self, name: str) -> ReadAnswer:
        name = self.folder.require(name)
        overlay = self._check(name)
        if overlay is None:
            return ReadAnswer(None, None)
        if overlay is not True:
            _, present, kept = overlay
            if not present:
                return ReadAnswer(None, None)
            if kept is TOO_BIG:
                return ReadAnswer(None, "large")
            return ReadAnswer(kept, None)               # type: ignore[arg-type]
        result = self.folder.read(name)
        kind = result.kind
        if kind is ReadKind.OK:
            return ReadAnswer(result.data, None)
        if kind is ReadKind.NOT_REGULAR:
            return ReadAnswer(None, "not_file")
        if kind is ReadKind.TOO_LARGE:
            return ReadAnswer(None, "large")
        if kind is ReadKind.LINKED:
            return ReadAnswer(None, "hard_link")
        if kind is ReadKind.UNREADABLE:
            self.log.debug("file read %s%s: unreadable", META_SHOWN, name)
        return ReadAnswer(None, None)

    def _check(self, name: str) -> "tuple[int, bool, bytes | _TooBig | None] | bool | None":
        """Steps 1–4 of a check: None (no answer: False / no text), an overlay entry, or True
        (ask the folder)."""
        self.pump()
        if not self.usable:
            return None
        state = self.folder.root_state()
        if state is RootState.BAD:
            self._w196()
            return None
        if state is RootState.UNREADABLE:
            return None
        pending = self._pending.get(name)
        if pending is not None:          # a pending write may be about to make the folder
            return pending
        return None if state is RootState.MISSING else True

    # --- FilesPort: changes (04 §6.4) ---

    def write(self, name: str, text: bytes | None) -> None:
        self._change(_WRITE, name, text)

    def delete(self, name: str) -> None:
        self._change(_DELETE, name, None)

    def _change(self, verb: str, name: str, text: bytes | None) -> None:
        name = self.folder.require(name)
        self.pump()
        if not self.usable or self.read_only:
            return
        state = self.folder.root_state()
        if state is RootState.BAD:
            self._w196()
            return
        if state is RootState.UNREADABLE:
            self._w198_line("other", verb, name)
            return
        if self.client.in_flight >= META_IN_FLIGHT_MAX:
            self._w198_line("busy", verb, name)
            return
        if state is RootState.OK and not self._cleaned:
            self._cleaned = True
            self.folder.stale_cleanup()
        data = b""
        if verb == _WRITE:
            data = text if text is not None else self._original(name)
            if data is None:
                return
        self._token += 1
        token = self._token
        folder = self.folder
        self._tokens[token] = (name, verb, folder)
        if verb == _WRITE:
            kept = data if len(data) <= META_READ_MAX_BYTES else TOO_BIG
            self._pending[name] = (token, True, kept)
            job: FileWrite | FileRemove = FileWrite(folder.root, name, (data,), release=False,
                                                    token=token)
        else:
            self._pending[name] = (token, False, None)
            job = FileRemove(folder.root, name, release=False, token=token)
        try:
            self.client.submit(job)
        except Exception:                # the writer stopped (quit): nothing was queued
            self._tokens.pop(token, None)
            if self._pending.get(name, (None,))[0] == token:
                del self._pending[name]
            self.log.debug("file %s %s%s: the writer is closed", verb, META_SHOWN, name)

    def _original(self, name: str) -> bytes | None:
        """``files/<name>`` (04 §6.2), or None after its W198."""
        try:
            return self.paths.read_file(f"{META_ORIGINALS_DIR}/{name}",
                                        max_bytes=META_ORIGINAL_MAX_BYTES, regular=True)
        except (AssetMissing, AssetNotFile, AssetRefError):
            self._w198_line("original_missing", _WRITE, name)
        except AssetTooLarge:
            self._w198_line("original_large", _WRITE, name)
        except Exception:                        # AssetUnreadable or anything else
            self._w198_line("other", _WRITE, name)
        return None

    # --- Results (04 §6.4 ``pump``) ---

    def pump(self) -> None:
        """Take the writer's results, drop their overlay entries, and log what failed.
        Never raises."""
        try:
            results = self.client.take()
        except Exception:
            self.log.debug("file changes: the writer's results couldn't be taken")
            return
        for result in results:
            try:
                self._result(result)
            except Exception:            # a classification slip: never in the frame
                self.log.debug("file changes: a result couldn't be classified")
                entry = self._tokens.pop(getattr(result, "token", 0), None)
                if entry is not None:
                    self._w198_line("other", entry[1], entry[0])

    def _result(self, result: object) -> None:
        token = getattr(result, "token", 0)
        entry = self._tokens.get(token)
        if entry is None:
            return
        name, verb, folder = entry
        pending = self._pending.get(name)
        if pending is not None and pending[0] == token:
            del self._pending[name]          # a newer pending change of the name stays
        if isinstance(result, FileWritten) or (isinstance(result, FileRemoved)
                                               and result.kind.gone):
            del self._tokens[token]
            # Only a change that touched the folder proves it writable (W197's rule).
            if isinstance(result, FileWritten) or result.kind is RemoveKind.REMOVED:
                self.succeeded = True
            return
        if self._closing:                    # quit: dropped or abandoned jobs are quiet
            del self._tokens[token]
            self.log.debug("file %s %s%s: not done before quit", verb, META_SHOWN, name)
            return
        if isinstance(result, Failed) and result.reason == FOLDER_IS_LINK:
            del self._tokens[token]
            self._w196()
            return
        kind = folder.entry_kind(name)       # may raise only by a programmer slip
        del self._tokens[token]
        if kind is EntryKind.OTHER:          # security wins (06 G2, SEC-F31-06)
            self._w198_line("folder_at_name", verb, name)
            return
        if isinstance(result, Failed):
            permission = result.reason == NO_PERMISSION
            full = result.reason == DISK_FULL
        else:
            permission = result.kind is RemoveKind.NO_PERMISSION   # type: ignore[union-attr]
            full = False
        if permission and not self.succeeded and (
                kind is EntryKind.MISSING or (kind is EntryKind.REGULAR and IS_POSIX)):
            self._w197()
            return
        if permission and kind is EntryKind.REGULAR and not IS_POSIX:
            self._w198_line("other", verb, name)     # Windows: possibly a lock, never W197
            return
        self._w198_line("full" if full else "permission" if permission else "other",
                        verb, name)

    # --- Session ---

    def set_folder(self, folder: MetaFolder) -> None:
        """An F39 reload's new allow-list; pending tokens keep the folder that submitted
        them, and the session's counts and marks stay."""
        self.folder = folder

    def drop_queued(self) -> None:
        """Quit, before F11's quit save (SEC-F31-08): this owner's jobs not yet started never
        start; their results are quiet."""
        self._closing = True
        self.client.drop_queued()

    def close(self) -> None:
        """The shutdown hook, after the writer stopped: take the last results quietly."""
        self._closing = True
        self.pump()

    # --- Warnings (names and fixed words only, SEC-F31-07) ---

    def _w196(self) -> None:
        if self.usable:
            self.usable = False
            self.log.warning("%s", format_message("W196"), extra={"code": "W196"})

    def _w197(self) -> None:
        if not self.read_only:
            self.read_only = True
            self.log.warning("%s", format_message("W197"), extra={"code": "W197"})

    def _w198_line(self, form: str, verb: str, name: str) -> None:
        text = format_message("W198", (form, verb, name))
        if self._w198 < META_W198_MAX:
            self._w198 += 1
            self.log.warning("%s", text, extra={"code": "W198"})
        else:
            self.log.debug("%s", text)


def _pump_of(app: "App") -> None:
    disk = getattr(app, "metafiles", None)
    if disk is not None:
        disk.pump()


def install_metafiles(app: "App", interp: "Interpreter") -> DiskFolder | None:
    """Right after ``install_story`` (04 §4.3). Registers the ``MetaWrite``/``MetaDelete``
    handlers (each only pumps the disk port), then, when the story has ``file`` lines and the
    App has a writer, the ``meta`` writer client, ``app.metafiles`` (the ``DiskFolder``), the
    interpreter's ``MetaFiles`` over it, and the shutdown hook. A story without ``file`` lines
    keeps the memory port and registers no client. Called again (an F39-style reload), it
    keeps the client, the ``DiskFolder``, and its session (``set_folder`` swaps the names);
    a reload that brings the first ``file`` line keeps the memory port (one dev INFO line:
    meta files reach the disk after a restart). Makes no file-system call."""
    first = _register_handlers(app)
    names = frozenset(getattr(interp.program, "meta_files", frozenset()))
    paths: GamePaths = app.paths
    disk: DiskFolder | None = getattr(app, "metafiles", None)
    if disk is not None:
        if names:
            disk.set_folder(MetaFolder(paths.root / META_DIRNAME, names))
        if disk.files is not None:
            attach(interp, disk.files)
        return disk
    writer = getattr(app, "writer", None)
    if not names or writer is None:
        return None
    if not first:
        if getattr(app, "dev", False):
            interp.log.info("This story's file lines reach %s only after the game restarts.",
                            META_SHOWN)
        return None
    root = paths.root / META_DIRNAME
    client = writer.client(META, root=root, names=META_NAME_RE)
    disk = DiskFolder(MetaFolder(root, names), client, paths, interp.log)
    disk.files = MetaFiles(disk)
    attach(interp, disk.files)
    app.metafiles = disk                         # type: ignore[attr-defined]
    app.add_shutdown(disk.close)
    return disk


def _register_handlers(app: "App") -> bool:
    """The two command handlers, once per App; False when they were already there."""
    handler = lambda cmd: _pump_of(app)       # noqa: E731
    try:
        app.router.register(MetaWrite, handler)
    except ValueError:
        return False
    app.router.register(MetaDelete, handler)
    return True


__all__ = ["DiskFolder", "TOO_BIG", "install_metafiles"]
