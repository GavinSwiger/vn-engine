"""``FlowService`` (``App.flow``) and ``install_flowchart``: the flowchart's node states on disk
and its jumps in the running game (F20 ``04-technical.md`` §5, §7.5, §7.6, §12, §18 A5–A8;
``05-security.md`` SEC-F20-01 to -08; ``07`` I-3, I-5, I-6, I-7, I-12, I-16).

Why this module exists: the runtime's ``FlowRecorder`` keeps the newest state of each node the
player reached (at most 256, in memory). So that a Jump still works after a relaunch, each
state is written to its own file ``node-<16 hex>.vnnode`` in F11's saves root, by the one
``App.writer`` as owner ``flow``. Those files sit beside the player's saves, so writing them
must never delay or endanger a save, fill the disk, or follow a planted link.

**Mode** (SEC-F20-01(a), -02). ``"disk"`` only when F12's data is WRITABLE, F11's saves are
available in a real folder, and ``NodeFolder.check_root()`` passes (at launch, and again before
each listing, jump read, and removal batch; a failure switches to ``"memory"`` for the
session). Memory mode (F12 MEMORY or READ_ONLY, ``--no-persistent``, a release run without
``[game] id``, a failed root) makes **no** file call: states live only in the recorder; forget
and Delete progress clear memory only; earlier files stay as they are. Headless runs have no
service (``App.flow`` None).

**Launch** (§7.5 "Launch", ``07`` A6). ``open_flow_listing`` builds the one ``FlowListJob``
that ``app/loading.py`` steps after F12's read and before F03's launch phase; the service
splits its files into current ones (``node_file`` of a graph node) and orphans, and queues the
node temps over 60 s old for removal. A listing the load screen didn't finish (or one that
ran before ``install_saves`` created the folder) is stepped here, in ``update``'s slice.

**Per frame** (``update``, after ``App.saves.update``; minimized wakes too, never error mode):
1. the ``flow`` client's results: ``FileWritten`` indexes the file and drops the memory state
   unless the node was reached again; ``Failed`` keeps it (disk full or no permission: no node
   write again this session);
2. forgets and a store reset (``take_forgotten``; F16's Delete progress bumps F12's
   ``reset_count``, which the recorder reports as ``"all"``): queued ids dropped, a running
   encoder cancelled, the files queued for removal (a name with a job in flight waits for its
   result), so nothing this session wrote stays and nothing recreates it;
3. eviction (SEC-F20-05(b)): over ``FLOW_DISK_MAX`` bytes or ``FLOW_FILES_MAX`` files, the
   oldest orphan, else the oldest current file but the one just written, is queued;
4. removals: at most ``FLOW_REMOVES_PER_FRAME`` or ``FLOW_STEP_S`` (at least one) through
   ``NodeFolder.remove``; a failure leaves the totals and is never retried (I-7);
5. writing (SEC-F20-03): ``take_dirty`` joins the queue (a re-dirtied id keeps its place);
   one state at a time is encoded in ``FLOW_STEP_S`` with ``NodeEncoder`` (not while
   ``App.saves.encoding``); ``TooLarge`` → W154 and no file; the job is submitted only when no
   other ``flow`` job is pending, neither ``save`` nor ``persist`` has one
   (``Writer.pending_of``), and the free-space floor holds (SEC-F20-06: ``free_bytes`` at most
   once per 10 s; ``FLOW_FREE_FLOOR`` plus the job's bytes must stay free, else the write is
   skipped and the memory state kept).

**Jump** (§7.6): the memory state if the recorder holds one, else (disk) ``read_node`` of the
node's file. A refused read shows F11's notice by status and the node's session reason
becomes ``flowchart_no_state``; otherwise ``App.saves.load_state(state, fresh_menu=True)``
with the jump's auto-save as ``before_commit`` (in game, ``[saves] autosave_quit`` and saving
possible). SCHEME_MISMATCH or a gone line with no nearby point → ``flowchart_changed``.
Reasons are per session. ``can_jump`` and ``reason`` read no file (TR-F20-09).

**Quit** (§7.5 "Quit", ``07`` A6): ``submit_final(until)`` after F12's ``persist.close``,
only with time left of the shared deadline, submits the job already encoded and nothing more;
``wait_final(until)`` after F11's takes the results. Arrivals not yet written are lost.

W154 and W155 are dev-only, area ``save``, naming the node id through ``echo()``; listing and
eviction log counts only; a write or removal failure's detail is the writer's redacted text
at DEBUG (I-16). No notice, record, or warning holds a path or file text (SEC-F20-14(d)).

This module imports ``engine.script`` only through ``runtime.flowchart`` and the
``runtime.errors`` re-export of ``format_message`` (W154, W155's texts; 07 I-1).
"""

import itertools
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from engine.app import platform
from engine.core.logsetup import get_logger
from engine.persist import limits
from engine.persist.location import saves_root
from engine.persist.nodestates import (NODE_NAME_RE, REASON_ROOT, FileInfo, FlowListJob,
                                       NodeEncoder, NodeFolder, NodeStatus, TooLarge, node_file,
                                       read_node)
from engine.persist.sync import WRITABLE
from engine.persist.writer import (DISK_FULL, FLOW, NO_PERMISSION, PERSIST, SAVE, Failed,
                                   FileWritten, Writer, WriterClient)
from engine.runtime.errors import format_message
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import GameState

if TYPE_CHECKING:
    from engine.app.app import App
    from engine.runtime.flowchart import FlowRecorder
    from engine.runtime.interpreter import Interpreter, RestoreOutcome

_log = get_logger("save")

Mode = Literal["disk", "memory"]
Origin = Literal["title", "game"]

# ``reason(id)``: the [words] key of a disabled Jump (04 §7.3).
NO_STATE = "flowchart_no_state"
CHANGED = "flowchart_changed"
FREE_CHECK_S = 10.0                  # SEC-F20-06: disk_usage at most this often

# F11's refused-load notice per node read status (04 §12).
_READ_NOTICES = {NodeStatus.MISSING: "notice_load_failed",
                 NodeStatus.UNREADABLE: "notice_load_failed",
                 NodeStatus.DAMAGED: "notice_load_damaged",
                 NodeStatus.NEWER: "save_newer",
                 NodeStatus.OTHER_GAME: "save_other_game"}
NO_STATE_HELD = "no state is kept for it"     # W155's reason in memory mode


def w154_text(node_id: str) -> str:
    """W154 (dev, area ``save``; the text is ``script/messages.py``'s)."""
    return format_message("W154", (node_id,))


def w155_text(node_id: str, reason: str) -> str:
    """W155 (dev, area ``save``): ``couldn't jump to <node>: <reason word>``."""
    return format_message("W155", (node_id, reason))


@dataclass(eq=False)
class _Job:
    """The one node write: encoding, encoded (``pieces``), or submitted (``sent``)."""

    node_id: str
    name: str
    state: GameState
    encoder: NodeEncoder
    pieces: tuple[bytes, ...] | None = None
    size: int = 0
    token: int = 0
    sent: bool = False


class FlowService:
    """``App.flow`` (module docstring). Main thread only. ``recorder()`` gives the live
    ``interp.flowchart``; ``node_ids`` are the graph's node ids (current file names);
    ``folder``, ``client``, and ``writer`` are None in memory mode. ``saves`` is F11's
    ``SaveService`` (``encoding``, ``load_state``, ``can_save``, ``autosave_now``);
    ``notify(key)`` shows a ``[words]`` problem notice."""

    def __init__(self, *, recorder: "Callable[[], FlowRecorder | None]",
                 node_ids: Iterable[str], folder: NodeFolder | None,
                 client: WriterClient | None, writer: Writer | None, saves: object | None,
                 notify: Callable[[str], None], game_id: str | None, release: bool,
                 listing: FlowListJob | None = None,
                 clock: Callable[[], float] = time.perf_counter,
                 wall: Callable[[], float] = time.time,
                 free_bytes: Callable[[Path], int | None] = platform.free_bytes) -> None:
        self._recorder = recorder
        self.current = frozenset(node_file(i) for i in node_ids)
        self.folder = folder
        self.client = client
        self.writer = writer
        self.saves = saves
        self._notify = notify
        self.game_id = game_id
        self.release = release
        self._clock = clock
        self._free_bytes = free_bytes
        self.mode: Mode = "disk" if folder is not None and client is not None else "memory"
        self.listing: FlowListJob | None = None
        if self.mode == "disk":
            assert folder is not None
            self.listing = listing if listing is not None else FlowListJob(folder, now=wall())
        elif listing is not None:
            listing.close()
        self.listed = False
        self.files: dict[str, FileInfo] = {}          # node files on disk F20 may remove
        self.orphans: set[str] = set()
        self.total = 0                                # bytes of ``files``
        self._removing: dict[str, None] = {}          # names to remove, in order
        self._queue: dict[str, None] = {}             # node ids to write, in order
        self._job: _Job | None = None
        self._tokens = itertools.count(1)
        self._order = 0                               # own writes order above every listing
        self._just_written: str | None = None
        self._reasons: dict[str, str] = {}            # this session's refused jumps
        self.stopped = False                          # disk full / no permission (SEC-F20-06)
        self._free: int | None = None
        self._free_at: float | None = None
        self.removed = 0                              # removals tried (tests, logs)
        self.removal_failures = 0

    # --- what the page asks (no file is read: TR-F20-09) ------------------------------------

    def recorder(self) -> "FlowRecorder | None":
        return self._recorder()

    def can_jump(self, node_id: str) -> bool:
        """A state is held for ``node_id`` (in memory, or as a listed or written file in disk
        mode) and no jump to it was refused this session (04 §7.3, D6, D7)."""
        if node_id in self._reasons:
            return False
        rec = self.recorder()
        if rec is not None and rec.state(node_id) is not None:
            return True
        if self.mode != "disk":
            return False
        name = node_file(node_id)
        return name in self.files and name not in self._removing

    def reason(self, node_id: str) -> str | None:
        """The ``[words]`` key of a disabled Jump (``flowchart_changed`` or
        ``flowchart_no_state``), or None when Jump is enabled."""
        found = self._reasons.get(node_id)
        if found is not None:
            return found
        return None if self.can_jump(node_id) else NO_STATE

    def jump_autosaves(self) -> bool:
        """A jump in game makes an Auto save first (``[saves] autosave_quit`` and saving is
        possible): the page's confirm then reads ``flowchart_confirm_autosave``."""
        saves = self.saves
        return bool(saves is not None and getattr(saves, "autosave_quit", False)
                    and saves.can_save())                        # type: ignore[attr-defined]

    # --- the frame slot ----------------------------------------------------------------------

    def update(self, now: float) -> None:
        """One frame's work (module docstring). ``now`` is the App clock (the free-space
        check's 10 s); the slices use the service's clock."""
        rec = self.recorder()
        if self.mode != "disk":
            if rec is not None:                       # memory only: nothing to write or delete
                rec.take_dirty()
                rec.take_forgotten()
            return
        clock = self._clock
        if not self.listed:
            listing = self.listing
            assert listing is not None
            if not listing.step(clock() + limits.FLOW_STEP_S, clock):
                return
            self._take_listing()
            if self.mode != "disk":
                return
        self._take_results()
        if rec is not None:
            self._deletes(rec.take_forgotten())
            for node_id in rec.take_dirty():
                self._queue.setdefault(node_id, None)
        self._evict()
        self._remove_some()
        if self.mode == "disk" and rec is not None:
            self._write_step(rec, now)

    def _take_listing(self) -> None:
        listing = self.listing
        assert listing is not None
        self.listed = True
        self.listing = None
        if not listing.root_ok:
            self._to_memory()
            return
        for name, info in listing.files.items():
            self._index(name, info)
            if name not in self.current:
                self.orphans.add(name)
        self._order = listing.max_order
        for name in listing.stale_temps:
            self._removing[name] = None
        _log.debug("Flowchart node files: %d current, %d orphans, %d old temps",
                   len(self.files) - len(self.orphans), len(self.orphans),
                   len(listing.stale_temps))

    def _to_memory(self) -> None:
        """The root failed its check (or was never usable): memory mode for the session, with
        no further file call. A job in flight still finishes in the writer."""
        self.mode = "memory"
        self.listed = True
        if self.listing is not None:
            self.listing.close()
            self.listing = None
        self._queue.clear()
        self._removing.clear()
        self._job = None

    def _index(self, name: str, info: FileInfo) -> None:
        old = self.files.get(name)
        if old is not None:
            self.total -= old.size
        self.files[name] = info
        self.total += info.size

    def _unindex(self, name: str) -> None:
        info = self.files.pop(name, None)
        if info is not None:
            self.total -= info.size
        self.orphans.discard(name)

    # --- results, deletes, eviction, removals ----------------------------------------------

    def _take_results(self) -> None:
        client = self.client
        if client is not None:
            for result in client.take():
                self._result(result)

    def _result(self, result: object) -> None:
        job = self._job
        if job is None or not job.sent or getattr(result, "token", None) != job.token:
            return
        self._job = None
        if isinstance(result, FileWritten):
            self._order += 1
            self._index(job.name, FileInfo(job.size, self._order))
            self.orphans.discard(job.name)
            self._just_written = job.name
            self._reasons.pop(job.node_id, None)
            rec = self.recorder()
            if rec is not None and rec.state(job.node_id) is job.state:
                rec.drop_state(job.node_id)           # not reached again since (04 §7.5 5)
        elif isinstance(result, Failed):
            if result.reason in (DISK_FULL, NO_PERMISSION):
                self.stopped = True                   # no node write again this session
            if result.detail:
                _log.debug("A flowchart node write failed: %s", result.detail)

    def _deletes(self, forgotten: "tuple[str, ...] | str") -> None:
        """§7.5 step 7 (SEC-F20-04): forgotten nodes' (or, for ``"all"`` and a reset, every)
        queued ids, running encoder, and files."""
        if not forgotten:
            return
        job = self._job
        if forgotten == "all":
            self._queue.clear()
            if job is not None and not job.sent:
                self._job = None
            names = list(self.files)
            if job is not None and job.sent:
                names.append(job.name)
        else:
            names = []
            for node_id in forgotten:
                self._queue.pop(node_id, None)
                if job is not None and job.node_id == node_id and not job.sent:
                    self._job = None
                name = node_file(node_id)
                if name in self.files or (job is not None and job.sent and job.name == name):
                    names.append(name)
        for name in names:
            self._removing[name] = None

    def _evict(self) -> None:
        """SEC-F20-05(b): queue the oldest orphans, then the oldest current files (never the
        one just written), until the files not queued fit both caps."""
        queued = [n for n in self._removing if n in self.files]
        count = len(self.files) - len(queued)
        size = self.total - sum(self.files[n].size for n in queued)
        if count <= limits.FLOW_FILES_MAX and size <= limits.FLOW_DISK_MAX:
            return
        files = self.files
        orphans = sorted((n for n in self.orphans if n not in self._removing),
                         key=lambda n: files[n].order)
        current = sorted((n for n in files if n not in self.orphans and n not in self._removing
                          and n != self._just_written), key=lambda n: files[n].order)
        evicted = 0
        for name in itertools.chain(orphans, current):
            if count <= limits.FLOW_FILES_MAX and size <= limits.FLOW_DISK_MAX:
                break
            self._removing[name] = None
            count -= 1
            size -= files[name].size
            evicted += 1
        _log.debug("Flowchart node files: %d queued for removal to stay within the caps",
                   evicted)

    def _remove_some(self) -> None:
        """At most ``FLOW_REMOVES_PER_FRAME`` removals, stopping after ``FLOW_STEP_S`` (at
        least one), each after the root's check passed (SEC-F20-05(b), I-7). A name with a
        job in flight waits for its result."""
        if not self._removing:
            return
        folder = self.folder
        assert folder is not None
        if not folder.check_root():
            self._to_memory()
            return
        clock = self._clock
        deadline = clock() + limits.FLOW_STEP_S
        job = self._job
        busy = job.name if job is not None and job.sent else None
        done = 0
        for name in list(self._removing):
            if done >= limits.FLOW_REMOVES_PER_FRAME or (done and clock() >= deadline):
                break
            if name == busy:
                continue
            del self._removing[name]
            outcome = folder.remove(name)
            done += 1
            self.removed += 1
            self._unindex(name)                       # gone, or failed: never retried
            if not outcome.gone:
                self.removal_failures += 1
        if done:
            _log.debug("Flowchart node files: %d removed", done)

    # --- writing (SEC-F20-03, -06) ------------------------------------------------------------

    def _write_step(self, rec: "FlowRecorder", now: float) -> None:
        if self.stopped:
            self._queue.clear()
            return
        saves = self.saves
        if saves is not None and getattr(saves, "encoding", False):
            return                                    # this frame's encoding is F11's
        job = self._job
        while job is None and self._queue:
            node_id = next(iter(self._queue))
            del self._queue[node_id]
            state = rec.state(node_id)
            if state is None:                         # dropped (the 256 cap, a forget)
                continue
            job = _Job(node_id, node_file(node_id), state,
                       NodeEncoder(state, node_id=node_id, game=self.game_id))
            self._job = job
        if job is None or job.sent:
            return
        if job.pieces is None:
            clock = self._clock
            if not job.encoder.step(clock() + limits.FLOW_STEP_S, clock):
                return
            result = job.encoder.result
            if isinstance(result, TooLarge) or result is None:
                self._job = None
                if rec.state(job.node_id) is job.state:
                    rec.drop_state(job.node_id)
                self._reasons[job.node_id] = NO_STATE
                if not self.release:
                    _log.warning("%s", w154_text(job.node_id), extra={"code": "W154"})
                return
            job.pieces = result
            job.size = sum(len(piece) for piece in result)
        self._submit(job, now)

    def _blocked(self) -> bool:
        writer = self.writer
        return writer is not None and (writer.pending_of(SAVE) > 0
                                       or writer.pending_of(PERSIST) > 0)

    def _submit(self, job: _Job, now: float) -> bool:
        """Submit the encoded ``job`` unless F11 or F12 has a write pending or its name
        waits for a removal; a job the free-space floor refuses is dropped (the memory state
        stays). True when submitted."""
        if self._blocked() or job.name in self._removing:
            return False
        if not self._room_for(job.size, now):
            self._job = None                          # skipped silently (SEC-F20-06)
            return False
        client, folder = self.client, self.folder
        assert client is not None and folder is not None and job.pieces is not None
        job.token = next(self._tokens)
        client.submit(folder.job(job.name, job.pieces, token=job.token))
        job.sent = True
        job.pieces = ()
        return True

    def _room_for(self, size: int, now: float) -> bool:
        """SEC-F20-06: the free space (asked at most once per ``FREE_CHECK_S``, never
        logged) must stay at least ``FLOW_FREE_FLOOR`` after ``size`` more bytes."""
        if self._free_at is None or now - self._free_at >= FREE_CHECK_S:
            folder = self.folder
            assert folder is not None
            self._free = self._free_bytes(folder.root)
            self._free_at = now
        free = self._free
        if free is None:
            return True
        if free - size < limits.FLOW_FREE_FLOOR:
            return False
        self._free = free - size
        return True

    # --- jumping (04 §7.6) ---------------------------------------------------------------------

    def jump(self, node_id: str, *, origin: Origin, by: object) -> None:
        """Load ``node_id``'s state through F11's load path with ``fresh_menu`` (the page
        asked first in game). A refused read or restore shows F11's notice and changes
        nothing."""
        saves = self.saves
        if saves is None:
            return
        rec = self.recorder()
        state = rec.state(node_id) if rec is not None else None
        if state is None:
            if self.mode != "disk":
                self._refuse_read(node_id, NodeStatus.MISSING, NO_STATE_HELD)
                return
            folder = self.folder
            assert folder is not None
            read = read_node(folder, node_id, game_id=self.game_id)
            if read.status is NodeStatus.UNREADABLE and read.reason == REASON_ROOT:
                self._to_memory()
            if read.status is not NodeStatus.OK or read.state is None:
                self._refuse_read(node_id, read.status, read.reason)
                return
            state = read.state
        before = None
        if origin == "game" and self.jump_autosaves():
            def before() -> None:
                saves.autosave_now("jump")           # type: ignore[attr-defined]
        saves.load_state(state, origin=origin, by=by,            # type: ignore[attr-defined]
                         fresh_menu=True, before_commit=before,
                         on_result=lambda outcome: self._jumped(node_id, outcome),
                         warn=lambda reason: self._w155(node_id, reason))

    def _refuse_read(self, node_id: str, status: NodeStatus, reason: str) -> None:
        self._reasons[node_id] = NO_STATE
        self._w155(node_id, reason)
        self._notify(_READ_NOTICES.get(status, "notice_load_failed"))

    def _jumped(self, node_id: str, outcome: "RestoreOutcome | None") -> None:
        result = getattr(outcome, "result", None)
        if result in (RestoreResult.SCHEME_MISMATCH, RestoreResult.POSITION_NOT_FOUND):
            self._reasons[node_id] = CHANGED

    def _w155(self, node_id: str, reason: str) -> None:
        if not self.release:
            _log.warning("%s", w155_text(node_id, reason), extra={"code": "W155"})

    # --- quit (04 §7.5 "Quit"; 07 A6) ----------------------------------------------------------

    def submit_final(self, until: float) -> None:
        """After F11's and F12's final submits: with time left of the shared deadline, the
        job already encoded (if any) is submitted; nothing is encoded or removed."""
        writer, client = self.writer, self.client
        if self.mode != "disk" or writer is None or client is None or self.stopped:
            return
        if writer.now() >= until:
            return
        self._take_results()
        job = self._job
        if job is None or job.sent or not job.pieces or job.name in self._removing:
            return
        folder = self.folder
        assert folder is not None
        if not self._room_for(job.size, float("inf")):
            return
        token = next(self._tokens)
        try:
            client.submit(folder.job(job.name, job.pieces, token=token))
        except RuntimeError:                           # the writer already stopped
            return
        job.token, job.sent, job.pieces = token, True, ()

    def wait_final(self, until: float) -> None:
        """After F11's ``wait_final``: wait on the shared deadline, then ``finish``."""
        client = self.client
        if self.mode != "disk" or client is None:
            return
        self.finish(client.wait(until))

    def finish(self, results: list) -> None:
        """Take the quit's results (no notice: the window is gone). States not written are
        lost (PR-F20-16), logged as a count only."""
        for result in results:
            self._result(result)
        left = len(self._queue) + (1 if self._job is not None else 0)
        if left:
            _log.debug("Flowchart: %d node states weren't written before the quit", left)


# --- Install (04 §7.5, 07 A6, I-12) -----------------------------------------------------------

def open_flow_listing(app: "App", persist_mode: object, program: object) -> FlowListJob | None:
    """The launch listing ``app/loading.py`` steps after F12's read (07 A6): only when the
    story has a graph, F12's data is WRITABLE, and the run has a saves root (a release run
    needs ``[game] id``); None otherwise (memory mode, no file call)."""
    if persist_mode is not WRITABLE or getattr(program, "flowgraph", None) is None:
        return None
    release = not app.dev
    app_id = app.config.game.id
    paths = getattr(app, "paths", None)
    if (release and app_id is None) or (paths is None and not release):
        return None
    root = saves_root(game_root=paths.root if paths is not None else None,  # type: ignore[arg-type]
                      release=release, app_id=app_id)
    if root is None:
        return None
    return FlowListJob(NodeFolder(root, release=release), now=time.time())


def install_flowchart(app: "App", interp: "Interpreter") -> FlowService | None:
    """Once per windowed launch, after ``install_minigames`` and before
    ``install_settings_ui`` (07 I-12): ``App.flow`` over the story's graph (None without
    one). Disk mode needs F12's WRITABLE data, F11's saves in a real folder, and the root's
    check; then the ``flow`` writer client is registered on the saves root."""
    listing: FlowListJob | None = getattr(app, "flow_listing", None)
    app.flow_listing = None

    def recorder() -> "FlowRecorder | None":
        live = getattr(getattr(app, "story", None), "interp", None)
        return getattr(live if live is not None else interp, "flowchart", None)

    rec = recorder()
    graph = getattr(rec, "graph", None)
    if graph is None:
        if listing is not None:
            listing.close()
        app.flow = None
        return None
    release = not app.dev
    saves = getattr(app, "saves", None)
    persist = getattr(app, "persist", None)
    folder: NodeFolder | None = None
    client: WriterClient | None = None
    writer = getattr(app, "writer", None)
    root = getattr(saves, "folder", None)
    if (writer is not None and root is not None and getattr(saves, "available", False)
            and getattr(saves, "folder_ok", False)
            and getattr(persist, "mode", None) is WRITABLE):
        folder = NodeFolder(root, release=release)
        if listing is not None and (listing.root_ok is False or listing.folder.root != root):
            listing.close()                           # e.g. listed before the folder existed
            listing = None
        if listing is not None or folder.check_root():
            client = writer.client(FLOW, root=root, names=NODE_NAME_RE)
        else:
            folder = None
    shell = getattr(app, "shell", None)

    def notify(key: str) -> None:
        if shell is not None:
            shell.notify(shell.words.get(key), kind="problem")

    service = FlowService(recorder=recorder, node_ids=(n.id for n in graph.nodes),
                          folder=folder if client is not None else None, client=client,
                          writer=writer if client is not None else None, saves=saves,
                          notify=notify, game_id=app.config.game.id, release=release,
                          listing=listing, clock=getattr(app, "clock", time.perf_counter))
    app.flow = service
    return service


__all__ = ["CHANGED", "FlowService", "NO_STATE", "install_flowchart", "open_flow_listing",
           "w154_text", "w155_text"]
