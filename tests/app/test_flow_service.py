"""F20 step 6: ``FlowService`` on Service S (06 §0.3): no window, the saves root
``tmp_path/aiko/game/saves/`` (with a slot, ``persistent.json``, ``settings.json``, and
``tmp_path/outside/``), F11's Writer W (unthreaded unless a row says threaded), F12's FS faults
(patched ``core.safefile`` calls), a clock that advances 1 ms per call, a fake ``SaveService``,
and a fake ``free_bytes``. The recorder is the runtime's ``FlowRecorder`` (no graph; arrivals
go through its ``_keep``, forgets through its ``_forgotten``, as the runtime's do), except in
AC-47, which installs the service over Template L's graph.

ACs: AC-F20-22, 25, 36, 37, 38, 39, 40, 41, 43, 44, 46, 47, 53 (one test each). AC-31, 32
and the AC-27 scan are in ``test_flow_jump.py``.
"""

import errno
import logging
import os
import random
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine.app import flowchart as flow_mod
from engine.app.app import App
from engine.app.flowchart import CHANGED, NO_STATE, FlowService, install_flowchart
from engine.app.settings import SettingsService
from engine.core import safefile
from engine.core.config_schema import Config
from engine.persist import limits, nodestates
from engine.persist.nodestates import (NODE_NAME_RE, FileInfo, NodeFolder, NodeStatus, node_file,
                                       read_node)
from engine.persist.saves import SlotId
from engine.persist.settings_file import LoadedSettings, Outcome
from engine.persist.sync import MEMORY, READ_ONLY, WRITABLE
from engine.persist.writer import FileWrite, Writer
from engine.runtime.flowchart import FlowRecorder, FlowState, node_key
from engine.runtime.interpreter import RestoreResult
from engine.runtime.persistent import PersistentStore
from engine.ui.nav import InputKind
from tests.persist import save_support as ss
from tests.persist.gen_hostile_saves import Sparse
from tests.persist.test_nodestates import Game, _make_entry, _rows, _write

GAME_ID = "f20-template"
IDS = ("scene:stall", "menu:m21", "chapter:festival", "chapter:river", "chapter:shrine")
KEYS = InputKind.KEYS


@pytest.fixture
def threaded_writer():
    """A factory for threaded ``Writer``s; each is stopped at teardown, so no ``vn-writer``
    thread outlives the test (AC-F12-35 checks for none in the same worker)."""
    made: list[Writer] = []

    def make() -> Writer:
        made.append(Writer(threaded=True))
        return made[-1]

    yield make
    for writer in made:
        writer.stop(writer.now() + 5)


def state_for(node_id: str, n: int = 0, pad: int = 0):
    """A small valid state reached at ``node_id`` (its key last in ``flow.path``)."""
    variables = {"n": n, **({"pad": "x" * pad} if pad else {})}
    return replace(ss.p8_state(**variables), flow=FlowState((node_key(node_id),)))


class FakeSaves:
    """F11's seams the service uses: ``encoding``, ``can_save``, ``autosave_quit``,
    ``autosave_now``, ``load_state`` (records, then answers ``outcome``)."""

    def __init__(self) -> None:
        self.encoding = False
        self.autosave_quit = False
        self.loads: list = []
        self.autosaves: list = []
        self.outcome = RestoreResult.OK

    def can_save(self) -> bool:
        return True

    def autosave_now(self, reason: str) -> None:
        self.autosaves.append(reason)

    def load_state(self, state, *, origin, by, fresh_menu, before_commit, on_result, warn):
        self.loads.append((state, origin, fresh_menu))
        if before_commit is not None:
            before_commit()
        on_result(SimpleNamespace(result=self.outcome))


class S:
    """Service S over ``game`` (a fresh ``Game`` when None)."""

    def __init__(self, tmp_path: Path, *, game: Game | None = None, writer: Writer | None = None,
                 ids=IDS, free: int | None = 1 << 40, memory: bool = False,
                 store: PersistentStore | None = None) -> None:
        self.game = game if game is not None else Game(tmp_path)
        self.root = self.game.root
        self.store = store if store is not None else PersistentStore(identity_scheme=1)
        self.rec = FlowRecorder(None, self.store)
        self.writer = writer if writer is not None else Writer(threaded=False)
        self.saves = FakeSaves()
        self.notices: list[str] = []
        self.free = free
        self.free_asks: list[float] = []
        self.clock = ss.FakeClock(step=0.0001)        # 0.1 ms per read: ~20 encoder units
        self.now = 0.0
        folder = client = None
        if not memory:
            folder = NodeFolder(self.root, release=False)
            client = self.writer.client("flow", root=self.root, names=NODE_NAME_RE)
        self.svc = FlowService(recorder=lambda: self.rec, node_ids=ids, folder=folder,
                               client=client, writer=None if memory else self.writer,
                               saves=self.saves, notify=self.notices.append, game_id=GAME_ID,
                               release=False, clock=self.clock, free_bytes=self._free)

    def _free(self, root: Path) -> int | None:
        self.free_asks.append(self.now)
        return self.free

    def arrive(self, node_id: str, state=None):
        state = state if state is not None else state_for(node_id)
        self.rec._keep(node_id, state)
        return state

    def forget(self, *node_ids: str) -> None:
        """What ``FlowRecorder.forget`` does for these nodes' states and files."""
        for node_id in node_ids:
            self.rec.drop_state(node_id)
            self.rec._forgotten[node_id] = None

    def frames(self, n: int = 1) -> None:
        for _ in range(n):
            self.now += 1 / 60
            self.svc.update(self.now)

    def on_disk(self, node_id: str):
        read = read_node(NodeFolder(self.root, release=False), node_id, game_id=GAME_ID)
        return read.state if read.status is NodeStatus.OK else None

    def node_entries(self) -> list[str]:
        return sorted(n for n in os.listdir(self.root) if "node-" in n)

    def jump(self, node_id: str, origin: str = "title") -> None:
        self.svc.jump(node_id, origin=origin, by=KEYS)


def same(a, b) -> bool:
    return a is not None and b is not None and a.to_json() == b.to_json()


def submits(monkeypatch, writer: Writer) -> list:
    """Every job submitted to ``writer``: (owner, job, [save, persist, flow pending])."""
    seen: list = []
    real = writer._submit

    def spy(client, job):
        seen.append((client.owner, job, [writer.pending_of(o) for o in ("save", "persist",
                                                                       "flow")]))
        return real(client, job)

    monkeypatch.setattr(writer, "_submit", spy)
    return seen


def failing_writes(monkeypatch, code: int = errno.EIO) -> None:
    def fail(*args, **kwargs):
        raise OSError(code, "injected <game>/saves failure")
    monkeypatch.setattr(safefile, "write_atomic", fail)


# --- AC-F20-22: memory mode keeps states in memory ------------------------------------------------

def test_ac_f20_22_memory_mode_keeps_states_in_memory(tmp_path):
    s = S(tmp_path, memory=True)
    ids = [f"scene:n{i}" for i in range(257)]
    for i, node_id in enumerate(ids):
        s.arrive(node_id, state_for(node_id, i))
        s.frames()
    assert s.svc.mode == "memory" and len(s.rec.states) == 256
    assert s.svc.reason(ids[0]) == NO_STATE and not s.svc.can_jump(ids[0])
    assert all(s.svc.can_jump(i) and s.svc.reason(i) is None for i in ids[1:])
    s.jump(ids[-1])
    assert s.saves.loads == [(s.rec.state(ids[-1]), "title", True)]
    assert s.node_entries() == []


# --- AC-F20-25: when Jump is enabled --------------------------------------------------------------

def test_ac_f20_25_when_jump_is_enabled(tmp_path, monkeypatch, caplog):
    game = Game(tmp_path)
    (game.root / node_file("menu:m21")).write_bytes(b"not a node file\n")   # damaged
    s = S(tmp_path, game=game)
    for node_id in ("scene:stall", "chapter:festival"):
        s.arrive(node_id)
    s.frames(10)
    stall, festival, m21, river = "scene:stall", "chapter:festival", "menu:m21", "chapter:river"
    # Visited with a file indexed: enabled, memory state dropped once written.
    assert s.rec.states == {} and s.svc.can_jump(stall) and s.svc.reason(stall) is None
    # Damaged, not yet tried: enabled (D6); refused once tried.
    assert s.svc.can_jump(m21)
    s.jump(m21)
    assert s.notices == ["notice_load_damaged"] and s.svc.reason(m21) == NO_STATE
    # SCHEME_MISMATCH / POSITION_NOT_FOUND without a hint: changed. DEFAULT_FAILED: unchanged.
    s.saves.outcome = RestoreResult.DEFAULT_FAILED
    s.jump(festival)
    assert s.svc.can_jump(festival)
    for outcome in (RestoreResult.SCHEME_MISMATCH, RestoreResult.POSITION_NOT_FOUND):
        s.saves.outcome = outcome
        s.jump(festival)
        assert s.svc.reason(festival) == CHANGED and not s.svc.can_jump(festival)
    assert [fresh for _, _, fresh in s.saves.loads] == [True, True, True]
    # Visited only through F18's record (no state, no file): no state.
    assert s.svc.reason(river) == NO_STATE
    # TooLarge: W154 naming the node through echo(), no file, no state.
    caplog.set_level(logging.WARNING, logger="vn.save")
    monkeypatch.setattr(limits, "STATE_MAX_BYTES", 4_096)
    s.arrive("chapter:shrine", state_for("chapter:shrine", pad=8_000))
    s.frames(10)
    monkeypatch.undo()
    assert s.svc.reason("chapter:shrine") == NO_STATE
    assert node_file("chapter:shrine") not in s.node_entries()
    assert [r.getMessage() for r in caplog.records if getattr(r, "code", "") == "W154"] == [
        flow_mod.w154_text("chapter:shrine")]
    # A write that failed keeps the memory state: still enabled.
    failing_writes(monkeypatch)
    s.arrive(river)
    s.frames(10)
    monkeypatch.undo()
    assert s.svc.can_jump(river) and s.rec.state(river) is not None and not s.svc.stopped
    # A relaunch: reasons are per session.
    again = S(tmp_path, game=game)
    again.frames(3)
    assert again.svc.can_jump(m21) and again.svc.can_jump(festival)


# --- AC-F20-36: opening reads no node file --------------------------------------------------------

def test_ac_f20_36_opening_reads_no_node_file(tmp_path, monkeypatch):
    game = Game(tmp_path)
    for node_id in IDS[:3]:
        writer = S(tmp_path, game=game)
        writer.arrive(node_id)
        writer.frames(5)
    reads: list = []
    real_read = safefile.read_regular
    monkeypatch.setattr(safefile, "read_regular",
                        lambda path, n: reads.append(Path(path).name) or real_read(path, n))
    s = S(tmp_path, game=game)
    s.frames(5)                                        # the listing, prewarm-time updates
    for node_id in IDS:                                # the title entry's check, every panel
        s.svc.can_jump(node_id)
        s.svc.reason(node_id)
    assert reads == [] and all(s.svc.can_jump(i) for i in IDS[:3])
    s.jump(IDS[0])
    assert reads == [node_file(IDS[0])] and same(s.saves.loads[0][0], state_for(IDS[0]))


# --- AC-F20-37: writing node states ---------------------------------------------------------------

def test_ac_f20_37_writing_node_states(tmp_path, monkeypatch):
    s = S(tmp_path)
    jobs = submits(monkeypatch, s.writer)
    slices: list[float] = []
    real_step = nodestates.NodeEncoder.step

    def step(self, deadline, clock):
        start = s.clock.now
        try:
            return real_step(self, deadline, clock)
        finally:
            slices.append(s.clock.now - start)

    monkeypatch.setattr(nodestates.NodeEncoder, "step", step)
    # Three arrivals at stall before the write starts: one file, the newest state.
    for n in range(3):
        newest = s.arrive("scene:stall", state_for("scene:stall", n, pad=20_000))
    s.frames(30)
    assert len(jobs) == 1 and same(s.on_disk("scene:stall"), newest)
    assert len(slices) > 1 and max(slices) <= limits.FLOW_STEP_S + 0.0015    # sliced
    # Client flow, root = the saves root, a FileWrite named by node_file; indexed; dropped.
    owner, job, _ = jobs[0]
    assert owner == "flow" and isinstance(job, FileWrite)
    assert (job.folder, job.name) == (s.root, node_file("scene:stall"))
    assert node_file("scene:stall") in s.svc.files and s.rec.state("scene:stall") is None
    # No encode or submit while F11 encodes.
    s.saves.encoding = True
    s.arrive("menu:m21")
    before = len(slices)
    s.frames(5)
    assert len(slices) == before and len(jobs) == 1
    s.saves.encoding = False
    s.frames(5)
    assert len(jobs) == 2 and s.rec.state("menu:m21") is None
    # Re-reached while its write was in flight: the newer state stays and is written next.
    s.arrive("chapter:river")
    while s.svc._job is None or not s.svc._job.sent:
        s.frames()
    newer = s.arrive("chapter:river", state_for("chapter:river", 9))
    s.frames(10)
    assert same(s.on_disk("chapter:river"), newer) and s.rec.state("chapter:river") is None
    # Two services on one folder, B reaching stall after A: B's state.
    b = S(tmp_path, game=s.game)
    b_state = b.arrive("scene:stall", state_for("scene:stall", 77))
    b.frames(10)
    assert same(s.on_disk("scene:stall"), b_state)


# --- AC-F20-38: losing at most 2 s of arrivals ----------------------------------------------------

def test_ac_f20_38_losing_at_most_2_s(tmp_path):
    s = S(tmp_path)
    ids = IDS[:4]
    latest: dict[str, tuple[float, object]] = {}
    for second in range(30):
        node_id = ids[second % len(ids)]
        latest[node_id] = (second, s.arrive(node_id, state_for(node_id, second, pad=100_000)))
        s.frames(60)
        t = second + 1
        if t >= 2:
            for node_id, (at, state) in latest.items():
                if at <= t - 2:
                    assert same(s.on_disk(node_id), state), (t, node_id)


# --- AC-F20-39: the launch listing ----------------------------------------------------------------

def test_ac_f20_39_the_launch_listing(tmp_path, monkeypatch):
    game = Game(tmp_path)
    now = time.time()
    current = {node_file(i): i for i in IDS[:2]}
    orphans = [node_file("scene:gone1"), node_file("scene:gone2")]
    for k, name in enumerate([*current, *orphans]):
        (game.root / name).write_bytes(b"x" * (k + 1))
        os.utime(game.root / name, ns=((k + 1) * 10**9, (k + 1) * 10**9))
    old = safefile.temp_name(node_file(IDS[0]), "0123abcd")
    young = safefile.temp_name(node_file(IDS[1]), "4567cdef")
    for name, age in ((old, 120), (young, 30)):
        (game.root / name).write_bytes(b"t")
        os.utime(game.root / name, (now - age, now - age))
    others = {n: (game.root / n).read_bytes() for n in ("quick-1.vnsave", "persistent.json")}
    monkeypatch.setattr(safefile, "remove_stale_temps",
                        lambda *a, **k: pytest.fail("F20 never calls remove_stale_temps"))
    s = S(tmp_path, game=game)
    s.frames(3)
    assert s.svc.listed and set(s.svc.files) == {*current, *orphans}
    assert s.svc.orphans == set(orphans)
    assert s.svc.files[orphans[1]] == FileInfo(4, 4 * 10**9)
    assert not (game.root / old).exists() and (game.root / young).exists()
    assert {n: (game.root / n).read_bytes() for n in others} == others
    s.arrive(IDS[2])
    s.frames(5)
    assert s.svc.files[node_file(IDS[2])].order > 4 * 10**9     # above every listed mtime


# --- AC-F20-40: quit -----------------------------------------------------------------------------

def test_ac_f20_40_quit(tmp_path, monkeypatch):
    w = Writer(threaded=True)
    s = S(tmp_path, writer=w)
    persist_root = tmp_path / "aiko" / "game" / "persistent"
    save = w.client("save", root=s.root, names={"quick-2.vnsave", "quick-3.vnsave"})
    persist = w.client("persist", root=persist_root, names={"persistent.json"})
    save.submit(FileWrite(s.root, "quick-2.vnsave", (b"held",)))   # pending: F20 waits
    w._wait(save, w.now() + 2)
    for node_id in IDS[:3]:
        s.arrive(node_id)
    while s.svc._job is None or not s.svc._job.pieces:
        s.frames()
    assert s.node_entries() == []                     # encoded, not submitted (save pending)
    jobs = submits(monkeypatch, w)

    class Saves:
        def submit_final(self):
            save.submit(FileWrite(s.root, "quick-3.vnsave", (b"final",)))

        def wait_final(self, until):
            save.wait(until)

    class Persist:
        def close(self, until):
            persist.submit(FileWrite(persist_root, "persistent.json", (b"{}",)))
            persist.wait(until)

    App._close_writers(SimpleNamespace(writer=w, settings=None, saves=Saves(),
                                       persist=Persist(), flow=s.svc))
    assert [owner for owner, *_ in jobs] == ["save", "persist", "flow"]
    assert s.node_entries() == [node_file(IDS[0])] and s.svc._job is None
    assert (s.root / "quick-3.vnsave").read_bytes() == b"final"


# --- AC-F20-41: group A, only real entries in the real root ---------------------------------------

def _junction(at: Path, target: Path) -> None:
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(at))
    except (ImportError, OSError) as exc:
        pytest.skip(f"junctions not available: {exc}")


@pytest.mark.parametrize("row", [pytest.param(r, id=r["id"]) for r in _rows("A", "default")]
                         + [pytest.param({"entry": "root_junction"}, id="root_junction"),
                            pytest.param({"entry": "root_replaced"}, id="root_replaced")])
def test_ac_f20_41_group_a_only_real_entries(row, tmp_path):
    game = Game(tmp_path)
    stall = "scene:stall"
    if row["entry"] == "root_junction":               # dev <game>/saves → outside: memory
        real = game.root.rename(tmp_path / "real_saves")
        _junction(game.root, real)
        s = S(tmp_path, game=game)
        s.arrive(stall)
        s.frames(5)
        assert s.svc.mode == "memory" and not any("node-" in n for n in os.listdir(real))
        return
    if row["entry"] == "root_replaced":               # replaced by a link after launch
        s = S(tmp_path, game=game)
        s.arrive(stall)
        s.frames(5)
        assert s.node_entries() == [node_file(stall)]
        moved = game.root.rename(tmp_path / "moved")
        _junction(game.root, game.outside)
        s.forget(stall)
        s.frames(3)
        assert s.svc.mode == "memory" and (moved / node_file(stall)).exists()
        assert os.listdir(game.outside) == ["notes.txt"]          # no call followed the link
        return
    at = game.root / node_file(stall)
    kept = _make_entry(row["entry"], at, game)
    kept_bytes = kept.read_bytes() if kept is not None else None
    s = S(tmp_path, game=game)
    s.frames(3)
    hard_link = row["entry"].startswith("hardlink")
    assert set(s.svc.files) == ({node_file(stall)} if hard_link else set())
    s.jump(stall)
    assert s.notices == ["notice_load_damaged" if hard_link else "notice_load_failed"]
    s.rec._forgotten = "all"                           # forget everything, then a reset
    s.store.reset()
    s.frames(3)
    assert os.path.lexists(at) is not hard_link        # the hard link entry only is removed
    if kept is not None:
        assert kept.read_bytes() == kept_bytes
    assert ss.full(game.root, SlotId("quick", 1)).status.value == "ok"


# --- AC-F20-43: group C, caps without hangs -------------------------------------------------------

def test_ac_f20_43_group_c_caps_without_hangs(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "FLOW_FILES_MAX", 8)
    monkeypatch.setattr(limits, "FLOW_DISK_MAX", 64 * 1024)
    game = Game(tmp_path)
    for k in range(130):
        (game.root / node_file(f"scene:gone{k}")).write_bytes(b"o")
    _write(game.root / node_file("scene:sparse"), Sparse(2 * 64 * 1024))
    os.utime(game.root / node_file("scene:sparse"), ns=(1, 1))    # the oldest orphan
    stuck = node_file("scene:gone7")
    real_remove = NodeFolder.remove
    monkeypatch.setattr(NodeFolder, "remove", lambda self, name: (
        safefile.RemoveKind.NO_PERMISSION if name == stuck else real_remove(self, name)))
    reads: list = []
    monkeypatch.setattr(NodeFolder, "read", lambda self, name: reads.append(name))
    ids = [f"chapter:c{k}" for k in range(9)]
    s = S(tmp_path, game=game, ids=ids)
    removed = 0
    for _ in range(10):                               # the clock bounds a frame's removals too
        s.frames()
        assert s.svc.removed - removed <= limits.FLOW_REMOVES_PER_FRAME
        removed = s.svc.removed
    assert not (game.root / node_file("scene:sparse")).exists() and reads == []
    assert len(s.svc.files) <= 8 and s.svc.total <= 64 * 1024
    assert s.svc.removal_failures == 1 and (game.root / stuck).exists()
    assert stuck not in s.svc.files                    # dropped from the totals, not retried
    # Nine current files: the oldest is evicted, never the one just written.
    for k, node_id in enumerate(ids):
        s.arrive(node_id, state_for(node_id, k))
        s.frames(10)
    assert node_file(ids[-1]) in s.node_entries() and node_file(ids[0]) not in s.node_entries()
    assert s.svc.reason(ids[0]) == NO_STATE and len(s.svc.files) <= 8
    # 300 arrivals with every write failing: at most 256 states held, the oldest dropped.
    failing_writes(monkeypatch)
    for k in range(300):
        s.arrive(f"scene:a{k}")
    s.frames(5)
    assert len(s.rec.states) == 256 and "scene:a0" not in s.rec.states


# --- AC-F20-44: group D, deleted means deleted ----------------------------------------------------

def test_ac_f20_44_group_d_deleted_means_deleted(tmp_path, monkeypatch, threaded_writer):
    stall, m21, river = "scene:stall", "menu:m21", "chapter:river"
    # Forget while the write is queued (F11 encoding holds it), and mid-encoder.
    s = S(tmp_path)
    s.saves.encoding = True
    s.arrive(stall)
    s.frames()
    s.forget(stall)
    s.saves.encoding = False
    s.arrive(m21, state_for(m21, pad=300_000))
    s.frames()
    assert s.svc._job is not None and s.svc._job.pieces is None      # encoding m21
    s.forget(m21)
    s.frames(20)
    assert s.node_entries() == [] and s.svc._job is None
    # Forget while the write is in flight (threaded, fsync waiting): removed after it.
    gate = threading.Event()
    real_fsync = safefile._fsync_file
    monkeypatch.setattr(safefile, "_fsync_file", lambda fd: gate.wait(5) and real_fsync(fd))
    t = S(tmp_path / "t", writer=threaded_writer())
    t.arrive(river)
    while t.svc._job is None or not t.svc._job.sent:
        t.frames()
    t.forget(river)
    t.frames(3)
    gate.set()
    t.writer._wait(t.svc.client, t.writer.now() + 5)
    t.frames(3)
    assert t.node_entries() == []
    monkeypatch.undo()
    # A reset (F16's Delete progress) in flight: every file and orphan goes, no state stays,
    # and nothing later recreates one.
    (t.root / node_file("scene:orphan")).write_bytes(b"o")
    u = S(tmp_path / "u", game=t.game, writer=threaded_writer())
    settings = SettingsService(LoadedSettings({}, Outcome.MISSING), Config())
    settings.persist = SimpleNamespace(mode=WRITABLE, store=u.store)
    for node_id in (stall, m21):
        u.arrive(node_id)
        u.frames(4)
    u.writer._wait(u.svc.client, u.writer.now() + 5)
    u.arrive(river)
    u.frames(2)
    settings.delete_progress()                          # F16's button: store.reset()
    u.writer._wait(u.svc.client, u.writer.now() + 5)
    u.frames(5)
    assert u.node_entries() == [] and u.rec.states == {} and u.svc.files == {}
    u.frames(20)
    assert u.node_entries() == []
    # Two services on one folder, 50 random arrivals and forgets each: OK or absent.
    a, b = S(tmp_path / "ab"), None
    b = S(tmp_path / "ab", game=a.game)
    rng = random.Random(0)
    for _ in range(50):
        for svc in (a, b):
            node_id = rng.choice(IDS)
            if rng.random() < 0.3:
                svc.forget(node_id)
            else:
                svc.arrive(node_id, state_for(node_id, rng.randrange(1000)))
            svc.frames(2)
    for node_id in IDS:
        read = read_node(NodeFolder(a.root, release=False), node_id, game_id=GAME_ID)
        assert read.status in (NodeStatus.OK, NodeStatus.MISSING)


# --- AC-F20-46: group F, the shared writer --------------------------------------------------------

def test_ac_f20_46_group_f_the_shared_writer(tmp_path, monkeypatch):
    s = S(tmp_path)
    save = s.writer.client("save", root=s.root, names={"quick-1.vnsave"})
    jobs = submits(monkeypatch, s.writer)
    for k in range(30):
        s.arrive(f"scene:b{k}")
        if k == 15:                                   # F5 in the middle of the burst
            save.submit(FileWrite(s.root, "quick-1.vnsave", (ss.make_save(),)))
        s.frames()
        assert s.writer.pending_of("flow") <= 1
        if k == 17:
            save.take()                               # F11 takes its result two frames later
    s.frames(120)
    flow_jobs = [(job, pending) for owner, job, pending in jobs if owner == "flow"]
    assert len(flow_jobs) == 30
    assert all(pending[:2] == [0, 0] for _, pending in flow_jobs)   # none behind save/persist
    assert all(isinstance(job, FileWrite) and job.folder == save.root for job, _ in flow_jobs)
    [(_, _, at_save)] = [j for j in jobs if j[0] == "save"]
    assert at_save[2] <= 1                            # the quick save waits for <= 1 node write


# --- AC-F20-47: group G, memory mode makes no file call -----------------------------------------

@pytest.fixture(scope="module")
def template_l(tmp_path_factory):
    from tests.runtime.flow_story import load_l
    return load_l(tmp_path_factory.mktemp("l") / "game")


class RootSpy(list):
    """Every ``os`` call whose first argument is a path under ``root``."""

    def install(self, monkeypatch, root: Path) -> "RootSpy":
        prefix = os.path.normcase(str(root))
        for name in ("lstat", "stat", "open", "scandir", "listdir", "unlink", "remove",
                     "replace", "rename", "mkdir", "utime"):
            real = getattr(os, name)

            def spy(*args, _real=real, _name=name, **kwargs):
                if args and os.path.normcase(str(args[0])).startswith(prefix):
                    self.append(_name)
                return _real(*args, **kwargs)

            monkeypatch.setattr(os, name, spy)
        return self


@pytest.mark.parametrize("mode", ["read_only", "no_id_release", "no_persistent", "bad_root"])
def test_ac_f20_47_group_g_memory_mode_makes_no_file_call(mode, tmp_path, monkeypatch,
                                                          template_l):
    game = Game(tmp_path)
    for node_id in ("scene:stall", "chapter:river"):
        _write(game.root / node_file(node_id), b"x")
    if mode == "bad_root":
        real = game.root.rename(tmp_path / "real_saves")
        _junction(game.root, real)
    before = {n: os.stat(game.root / n).st_mtime_ns for n in os.listdir(game.root)}
    snapshot = game.snapshot()
    store = PersistentStore(identity_scheme=template_l.identity_scheme)
    interp = SimpleNamespace(flowchart=FlowRecorder(template_l.flowgraph, store))
    from engine.runtime.flowchart import register_kinds
    register_kinds(store, template_l.flowgraph)
    saves = FakeSaves()
    saves.available = mode != "no_id_release"
    saves.folder_ok, saves.folder = True, game.root
    persist = SimpleNamespace(mode={"read_only": READ_ONLY, "no_persistent": MEMORY}.get(
        mode, WRITABLE))
    app = SimpleNamespace(dev=mode != "no_id_release", writer=Writer(threaded=False),
                          saves=saves, persist=persist, story=None, shell=None,
                          config=Config(), flow_listing=None, clock=ss.FakeClock())
    spy = RootSpy().install(monkeypatch, game.root)
    service = install_flowchart(app, interp)
    rec = interp.flowchart
    for node_id in ("scene:stall", "menu:" + next(n.id.split(":", 1)[1] for n in
                                                  template_l.flowgraph.nodes
                                                  if n.kind == "choice"), "chapter:festival"):
        rec._keep(node_id, state_for(node_id))
        service.update(1.0)
    service.jump("scene:stall", origin="title", by=KEYS)
    rec.forget(None)
    store.reset()
    for k in range(5):
        service.update(2.0 + k)
    monkeypatch.undo()
    assert service.mode == "memory" and app.flow is service
    assert len(saves.loads) == 1 and saves.loads[0][2] is True     # the jump used memory
    assert spy == [] or (mode == "bad_root" and set(spy) <= {"lstat", "stat"})
    assert game.snapshot() == snapshot
    assert {n: os.stat(game.root / n).st_mtime_ns for n in os.listdir(game.root)} == before


# --- AC-F20-53: the free-space floor -------------------------------------------------------------

def test_ac_f20_53_the_free_space_floor(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    free = limits.FLOW_FREE_FLOOR + 100               # less than the floor plus any file
    s = S(tmp_path, free=free)
    jobs = submits(monkeypatch, s.writer)
    for k in range(40):                               # 40 arrivals over about 40 s
        s.arrive("scene:stall", state_for("scene:stall", k))
        s.frames(60)
    assert jobs == [] and s.node_entries() == [] and s.notices == []
    assert s.rec.state("scene:stall") is not None     # the memory state stays
    asks = s.free_asks
    assert 2 <= len(asks) <= 5 and all(b - a >= 10 for a, b in zip(asks, asks[1:]))
    assert str(free) not in caplog.text and f"{free:,}" not in caplog.text
    # After one Failed with disk full, no node write is submitted again this session.
    s.free = 1 << 40
    s.free_asks.clear()
    s.now += 20
    failing_writes(monkeypatch, errno.ENOSPC)
    s.arrive("menu:m21")
    s.frames(5)
    assert s.svc.stopped and len(jobs) == 1
    monkeypatch.undo()
    s.arrive("chapter:river")
    s.frames(10)
    assert len(jobs) == 1 and s.notices == []
