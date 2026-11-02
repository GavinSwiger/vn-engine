"""F20 node-state files (``persist/nodestates.py``; F20 ``04`` §4, §7.5 "One helper",
"Launch", "Reading"; ``05`` SEC-F20-01, -05(c), -07, -08): AC-F20-35 (the node file),
AC-F20-42 (group B: names), AC-F20-45 (group E: a node file is checked like a save, with F11's
mutation corpus), AC-F20-52 (the state belongs to its node), and the persist halves of
AC-F20-39 (``FlowListJob``) and AC-F20-41 (group A entries), whose service rows come with F20
s6 (``tests/app/test_flow_service.py``).

Rows come from ``hostile/nodes/manifest.toml`` (``gen_hostile_nodes.py``). Every group E row
also asserts (06 §0.4): no exception escapes; ``json.loads`` receives only ``str``; line 2 is
never base64-decoded; slot files, ``persistent.json``, ``settings.json``, and
``tmp_path/outside/`` keep their SHA-256; the reason holds neither the root path nor ``aiko``.
"""

import hashlib
import json
import os
import random
import re
import shutil
import time
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from engine.core import safefile
from engine.persist import limits, location, nodestates, saves, settings_file, writer
from engine.persist.nodestates import (NODE_NAME_RE, NODE_TEMP_RE, FlowListJob, NodeEncoder,
                                       NodeFolder, NodeStatus, node_file, parse_node, read_node)
from engine.runtime import limits as runtime_limits
from engine.runtime.flowchart import FlowState
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import GameState
from engine.script.flowgraph import node_key
from tests.persist import fuzz_saves, gen_hostile_nodes
from tests.persist import gen_hostile_saves
from tests.persist import save_support as ss
from tests.persist.gen_hostile_nodes import GAME_ID, NODE_ID, OTHER_ID
from tests.persist.gen_hostile_saves import Sparse

ROWS = gen_hostile_nodes.load_manifest()
MIB = 1 << 20
F20_TEMPLATE = Path(__file__).resolve().parents[1] / "fixtures" / "F20" / "template"
_DUMP = {"ensure_ascii": True, "separators": (",", ":"), "allow_nan": False}
_OS_CALLS = ("lstat", "stat", "open", "scandir", "listdir", "unlink", "remove", "rmdir",
             "replace", "rename", "mkdir", "makedirs")


def _rows(group: str, tier: str) -> list[dict]:
    on_os = {"any": True, "windows": os.name == "nt", "posix": os.name == "posix"}
    return [r for r in ROWS if r["group"] == group and r["tier"] == tier
            and on_os[r.get("os", "any")]]


def _tree(root: Path) -> dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            out[rel] = "entry"
        else:
            size = path.stat().st_size
            out[rel] = (hashlib.sha256(path.read_bytes()).hexdigest() if size < 64 * MIB
                        else str(size))
    return out


class OsSpy(list):
    """Every ``os`` file call (by name) while installed."""

    def install(self, monkeypatch) -> "OsSpy":
        for name in _OS_CALLS:
            real = getattr(os, name, None)
            if real is None:
                continue

            def spy(*args, _real=real, _name=name, **kwargs):
                self.append(_name)
                return _real(*args, **kwargs)

            monkeypatch.setattr(os, name, spy)
        return self


class Game:
    """``tmp_path/aiko/game/saves`` (the privacy sentinel home) with a slot,
    ``persistent.json``, ``settings.json``, and ``tmp_path/outside/``."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.root = tmp_path / "aiko" / "game" / "saves"
        self.root.mkdir(parents=True)
        ss.write_slot(self.root, ss.make_save())
        (self.root / location.FILE_NAME).write_bytes(b'{"format":1}')
        (self.root / settings_file.FILE_NAME).write_bytes(b"{}")
        self.outside = tmp_path / "outside"
        self.outside.mkdir()
        (self.outside / "notes.txt").write_bytes(b"ZZMARK qauser7")
        self.folder = NodeFolder(self.root, release=False)

    def snapshot(self, *, skip: str | None = None) -> dict[str, str]:
        tree = _tree(self.tmp_path)
        if skip is not None:
            tree.pop(f"aiko/game/saves/{skip}", None)
        return tree

    def clean_reason(self, reason: str) -> None:
        assert "aiko" not in reason and str(self.root) not in reason, reason


def _write(path: Path, data: bytes | Sparse) -> None:
    if isinstance(data, Sparse):
        with open(path, "wb") as f:
            f.truncate(data.size)
    else:
        path.write_bytes(data)


def _status_ok(status: NodeStatus, expected: str) -> bool:
    if expected == "any":
        return status in (NodeStatus.OK, NodeStatus.DAMAGED)
    return status.value == expected


@pytest.fixture(scope="module")
def reduced_program(tmp_path_factory):
    from tests.runtime.story import load_files
    return load_files(tmp_path_factory.mktemp("template_s"), {"main.vns": ss.TEMPLATE_S_REDUCED})


@pytest.fixture(scope="module")
def template_l_states(tmp_path_factory) -> list[GameState]:
    """Five Template L checkpoints (06 §5), each reached at ``scene:stall`` (its key last in
    ``flow.path``; s3's recorder writes it there in play)."""
    from engine.core.paths import GamePaths
    from engine.script import load_story
    from tests.runtime.story import checkpoints, start
    root = tmp_path_factory.mktemp("template_l")
    shutil.copytree(F20_TEMPLATE, root, dirs_exist_ok=True)
    result = load_story(GamePaths(root.resolve()))
    assert result.program is not None, [e.format() for e in result.errors]
    states = checkpoints(start(result.program))[:5]
    assert len(states) == 5
    key = node_key(NODE_ID)
    return [replace(s, flow=FlowState(s.flow.path + (key,))) for s in states]


def _fuzz_states(bases: list[GameState], count: int, seed: int) -> list[GameState]:
    """``count`` valid states from F03's ``fuzz_state`` mutations of ``bases``, each reached
    at ``scene:stall``."""
    from tests.runtime import fuzz_state
    key = node_key(NODE_ID)
    out: list[GameState] = []
    for obj in fuzz_state.mutations([b.to_json() for b in bases], 4_000, seed):
        try:
            state = GameState.from_json(obj)
        except Exception:
            continue
        state = replace(state, flow=FlowState(state.flow.path[-15:] + (key,)))
        if state.save_problem() is None:
            out.append(state)
            if len(out) == count:
                return out
    raise AssertionError(f"only {len(out)} valid fuzz states")


# --- AC-F20-35: the node file -------------------------------------------------------------------

def test_ac_f20_35_the_node_file(template_l_states, monkeypatch):
    # The name: node- + 16 hex + .vnnode.
    name = node_file("scene:stall")
    assert re.fullmatch(r"node-[0-9a-f]{16}\.vnnode", name)
    assert name == f"node-{node_key('scene:stall')}.vnnode" and NODE_NAME_RE.fullmatch(name)

    # The three lines, exactly.
    state = template_l_states[2]
    pieces = NodeEncoder(state, node_id="scene:stall", game="f20-template").run()
    assert isinstance(pieces, tuple)
    data = b"".join(pieces)
    first, second, third = ss.lines(data)
    one_dump = json.dumps(state.to_json(), **_DUMP).encode("ascii")
    assert third == one_dump + b"\n"                  # the pieces joined equal one dump
    assert second == b'{"jpeg":null}\n'
    assert first == (b'{"vnnode":1,"game":"f20-template","node":"scene:stall","state_format":1,'
                     b'"thumb":%d,"state":%d}\n' % (len(second), len(third)))

    # Slices give the same bytes (a 1 ms clock, F11's Encoder E).
    encoder = NodeEncoder(state, node_id="scene:stall", game="f20-template")
    clock = ss.FakeClock()
    while not encoder.step(clock() + 0.0005, clock):
        pass
    assert b"".join(encoder.result) == data

    # Every file it writes for 5 Template L and 50 seeded fuzz states parses OK, equal.
    states = list(template_l_states) + _fuzz_states(template_l_states + [
        gen_hostile_nodes.node_state()], 50, seed=20)
    for i, each in enumerate(states):
        written = b"".join(NodeEncoder(each, node_id=NODE_ID, game=GAME_ID).run())
        read = parse_node(written, node_id=NODE_ID, game_id=GAME_ID)
        assert read.status is NodeStatus.OK, (i, read.reason)
        assert read.state == each and read.state.to_json() == each.to_json(), i

    # A game id that isn't valid is written as null; a bad node id is a programmer error.
    assert ss.meta(b"".join(NodeEncoder(state, node_id=NODE_ID, game="../x").run()))["game"] is None
    for bad in ("", "a" * (limits.NODE_ID_MAX + 1), 7):
        with pytest.raises(ValueError):
            NodeEncoder(state, node_id=bad, game=GAME_ID)  # type: ignore[arg-type]

    # F11's state cap patched to 4 KiB: a larger state is TooLarge (no pieces). W154 and
    # flowchart_no_state are the service's (s6).
    big = replace(state, variables=MappingProxyType({**state.variables, "pad": "x" * 8_192}))
    monkeypatch.setattr(limits, "STATE_MAX_BYTES", 4_096)
    assert isinstance(NodeEncoder(big, node_id=NODE_ID, game=GAME_ID).run(), saves.TooLarge)
    monkeypatch.undo()

    # parse_node uses F11's own objects (by identity) and calls each of them.
    assert nodestates.split_lines is saves.split_lines
    assert nodestates.strict_loads is saves.strict_loads
    assert nodestates.parse_state_line is saves.parse_state_line
    assert nodestates.PARSE_ERRORS is saves.PARSE_ERRORS
    assert issubclass(NodeEncoder, saves.StateEncoder) and issubclass(saves.SaveEncoder,
                                                                         saves.StateEncoder)
    calls: list[str] = []
    for fn in ("split_lines", "strict_loads", "parse_state_line"):
        real = getattr(nodestates, fn)
        monkeypatch.setattr(nodestates, fn,
                            lambda *a, _real=real, _fn=fn, **k: calls.append(_fn) or _real(*a, **k))
    assert parse_node(data, node_id=NODE_ID, game_id=GAME_ID).status is NodeStatus.OK
    assert set(calls) == {"split_lines", "strict_loads", "parse_state_line"}
    # F11's parse_full goes through the same parse_state_line (no behaviour change: AC-F11-11's
    # tests stay green).
    monkeypatch.undo()
    shared: list[int] = []
    real_line = saves.parse_state_line
    monkeypatch.setattr(saves, "parse_state_line",
                        lambda *a, **k: shared.append(1) or real_line(*a, **k))
    assert saves.parse_full(ss.make_save(), game_id=ss.GAME_ID).status is saves.SlotStatus.OK
    assert shared == [1]


# --- AC-F20-42: group B, names --------------------------------------------------------------------

def _names_row(row: dict) -> str:
    key = node_key(NODE_ID)
    full_width = "".join(chr(0xFF10 + int(c, 16)) if c.isdigit() else c for c in key)
    return row["name"].format(k=key, K=key.upper(), k15=key[:15], k17=key + "0", fw=full_width)


def _owners() -> dict[str, list[re.Pattern[str]]]:
    def exact(*names: str) -> re.Pattern[str]:
        return re.compile("|".join(re.escape(n) for n in names), re.ASCII)
    return {
        "save": [saves.SLOT_NAME_RE, safefile.temp_name_pattern(target_pattern=saves.SLOT_NAME_RE)],
        "persist": [exact(location.FILE_NAME, location.BAD_NAME), location.TEMP_RE],
        "settings": [exact(settings_file.FILE_NAME, settings_file.BAD_NAME),
                     settings_file.TEMP_RE],
        "flow": [NODE_NAME_RE, NODE_TEMP_RE],
    }


def _generated_names(rng: random.Random) -> str:
    """A name of some owner (or its temp), maybe with a case variant."""
    hexes = "0123456789abcdef"
    kind = rng.randrange(5)
    if kind == 0:
        page = rng.choice(["auto", "quick", f"page{rng.randint(1, 100)}"])
        name = f"{page}-{rng.randint(1, 6)}.vnsave"
    elif kind == 1:
        name = "node-" + "".join(rng.choice(hexes) for _ in range(16)) + ".vnnode"
    elif kind == 2:
        name = rng.choice([location.FILE_NAME, location.BAD_NAME])
    elif kind == 3:
        name = rng.choice([settings_file.FILE_NAME, settings_file.BAD_NAME])
    else:
        name = rng.choice(["quick-1.vnsave", "node-" + "0" * 16 + ".vnnode", "persistent.json"])
    if rng.random() < 0.4 and not name.endswith(".bad.json"):
        name = safefile.temp_name(name, "".join(rng.choice(hexes) for _ in range(8)))
    variant = rng.randrange(4)
    if variant == 1:
        name = name.upper()
    elif variant == 2:
        name = "".join(c.swapcase() if rng.random() < 0.3 else c for c in name)
    return name


def _disjoint(count: int, seed: int) -> None:
    owners = _owners()
    folded = {o: [re.compile(p.pattern, re.ASCII | re.IGNORECASE) for p in ps]
              for o, ps in owners.items()}
    rng = random.Random(seed)
    for _ in range(count):
        name = _generated_names(rng)
        hits = [o for o, ps in owners.items() if any(p.fullmatch(name) for p in ps)]
        assert len(hits) <= 1, (name, hits)
        # A case-insensitive file system: no name is two owners' in any case.
        ci = [o for o, ps in folded.items() if any(p.fullmatch(name) for p in ps)]
        assert len(ci) <= 1, (name, ci)
    for fixed in (location.FILE_NAME, settings_file.FILE_NAME, location.BAD_NAME,
                  settings_file.BAD_NAME):
        assert not NODE_NAME_RE.fullmatch(fixed) and not NODE_TEMP_RE.fullmatch(fixed)


def test_ac_f20_42_names(tmp_path, monkeypatch):
    game = Game(tmp_path)
    good = node_file(NODE_ID)
    (game.root / good).write_bytes(gen_hostile_nodes.base())
    rows = _rows("B", "default")
    assert len(rows) >= 9
    planted = []
    for row in rows:
        name = _names_row(row)
        if name != "quick-1.vnsave":
            (game.root / name).write_bytes(b"planted " + row["id"].encode())
        planted.append(name)
    before = game.snapshot()

    # Never listed (so never indexed, counted, or removed by the service); the real one is.
    job = FlowListJob(game.folder, now=time.time() + 3_600)
    job.finish()
    assert job.root_ok and set(job.files) == {good} and job.stale_temps == []

    # The helper refuses another folder and any other name, with no os call.
    spy = OsSpy().install(monkeypatch)
    for name in planted:
        assert not game.folder.accepts(game.root, name), name
        for call in (game.folder.read, game.folder.remove,
                     lambda n: game.folder.job(n, (b"x",))):
            with pytest.raises(ValueError):
                call(name)
    for folder in (game.root.parent, game.root / "sub", tmp_path / "outside", str(game.root)):
        assert not game.folder.accepts(folder, good)
    with pytest.raises(ValueError):
        game.folder.read(".node-" + node_key(NODE_ID) + ".vnnode.0123abcd.tmp")  # temps: no read
    with pytest.raises(ValueError):
        game.folder.job(".node-" + node_key(NODE_ID) + ".vnnode.0123abcd.tmp", (b"x",))
    assert spy == []
    job = game.folder.job(good, (b"a", b"b"), token=3)
    assert (job.folder, job.name, job.pieces, job.release, job.token) == (
        game.root, good, (b"a", b"b"), False, 3)
    assert spy == []
    monkeypatch.undo()
    assert game.snapshot() == before

    # Property: no string fullmatches two owners' patterns (case variants included), and no
    # node pattern matches persistent.json or settings.json.
    _disjoint(1_000, seed=42)

    # Names come only from node_file: hostile ids still give a node name.
    for hostile in ("../x", "scene:a\x00", "‮", "Scene:a", "ｓｃｅｎｅ:a", "a" * 1_201,
                    "\ud800", "node-0000000000000000.vnnode"):
        assert NODE_NAME_RE.fullmatch(node_file(hostile)), hostile

    # A file whose meta names another id causes no other read.
    other = ss.with_meta(gen_hostile_nodes.base(), node=OTHER_ID)
    (game.root / good).write_bytes(other)
    reads = ss.ReadSpy().install(monkeypatch)
    opened: list[str] = []
    real_open = safefile._open_for_reading
    monkeypatch.setattr(safefile, "_open_for_reading",
                        lambda path: opened.append(Path(path).name) or real_open(path))
    result = read_node(game.folder, NODE_ID, game_id=GAME_ID)
    assert result.status is NodeStatus.DAMAGED and result.reason == nodestates.REASON_OTHER_NODE
    assert opened == [good] and len(reads) == 1


def test_ac_f20_42_a_slot_name_through_client_flow_fails(tmp_path):
    """AC-F20-42: a ``FileWrite`` for ``quick-1.vnsave`` through client ``flow`` → Failed."""
    game = Game(tmp_path)
    before = game.snapshot()
    w = writer.Writer(threaded=False)
    client = w.client("flow", root=game.root, names=NODE_NAME_RE)
    client.submit(writer.FileWrite(game.root, "quick-1.vnsave", (b"x",)))
    (result,) = client.take()
    assert isinstance(result, writer.Failed)
    assert game.snapshot() == before


@pytest.mark.slow
def test_ac_f20_42_names_property_100000():
    _disjoint(100_000, seed=7)


# --- AC-F20-45: group E, a node file is checked like a save ---------------------------------------

def _check_row(row: dict, game: Game, monkeypatch, program) -> NodeStatus:
    from tests.runtime.story import fingerprint, launched
    kwargs = gen_hostile_nodes.read_kwargs(row)
    name = node_file(kwargs["node_id"])
    target = game.root / name
    _write(target, gen_hostile_nodes.build(row))
    before = game.snapshot(skip=name)
    with monkeypatch.context() as m:
        reads = ss.ReadSpy().install(m)
        loads = ss.LoadsSpy().install(m)
        decodes = ss.DecodeSpy().install(m)
        if row.get("like") == "b_grows_during_read":
            real_open = safefile._open_for_reading

            def grow_then_open(path):
                with open(path, "ab") as f:            # after lstat, before the read
                    f.write(b"\n")
                return real_open(path)

            m.setattr(safefile, "_open_for_reading", grow_then_open)
        start = time.perf_counter()
        result = read_node(game.folder, kwargs["node_id"], game_id=kwargs["game_id"])
        seconds = time.perf_counter() - start
    assert _status_ok(result.status, row["status"]), (row["id"], result)
    if "like" in row:                                   # F11's status for that shape
        f11 = gen_hostile_nodes.save_rows()[row["like"]]["full"]
        assert f11 == "any" or result.status.value == f11, (row["id"], f11)
    assert all(kind is str for kind, _ in loads) and decodes == []
    assert sum(reads) <= limits.SAVE_FILE_MAX + 1 and seconds < 2.0, row["id"]
    if row.get("size_first"):
        assert reads == [], row["id"]
    if result.status is NodeStatus.OK:
        assert isinstance(result.state, GameState) and result.reason == ""
        # Then the restore checks: check_only changes nothing.
        interp = launched(program)
        print_before = fingerprint(interp)
        outcome = interp.restore(result.state, check_only=True)
        assert outcome.result in RestoreResult and fingerprint(interp) == print_before
    else:
        assert result.state is None and result.reason
    game.clean_reason(result.reason)
    target.unlink()
    assert game.snapshot() == before, row["id"]
    return result.status


def _node_corpus(count: int, seed: int, *, max_read_s: float) -> dict[str, int]:
    """F11's mutation corpus over 3 engine-written node files: a ``NodeRead`` each, in time."""
    bases = [gen_hostile_nodes.encode(gen_hostile_nodes.node_state()),
             gen_hostile_nodes.encode(gen_hostile_nodes.node_state(
                 path=(node_key(OTHER_ID), node_key(NODE_ID)), state=ss.p8_state(trust=3))),
             gen_hostile_nodes.encode(gen_hostile_nodes.node_state(
                 state=ss.state_with({"v": list(range(50)), "w": "lantern"})), game=None)]
    statuses: dict[str, int] = {}
    for i, data in enumerate(fuzz_saves.mutations(bases, count, seed)):
        start = time.perf_counter()
        read = parse_node(data, node_id=NODE_ID, game_id=GAME_ID)
        assert time.perf_counter() - start < max_read_s, i
        assert read.status in NodeStatus and (read.state is None) == (read.status is not
                                                                      NodeStatus.OK), i
        statuses[read.status.value] = statuses.get(read.status.value, 0) + 1
    return statuses


def test_ac_f20_45_node_file_checked_like_a_save(tmp_path, monkeypatch, reduced_program):
    game = Game(tmp_path)
    rows = _rows("E", "default")
    seen = {_check_row(row, game, monkeypatch, reduced_program) for row in rows}
    assert {NodeStatus.OK, NodeStatus.DAMAGED, NodeStatus.NEWER, NodeStatus.OTHER_GAME} <= seen
    # NEWER is checked first: vnnode 2 wins over every other fault (a row above); parse
    # errors of any kind are DAMAGED, anything else is a programmer error.
    data = gen_hostile_nodes.base()
    for error in (RecursionError, ValueError, MemoryError, OverflowError):
        def boom(*args, _error=error, **kwargs):
            raise _error("patched")
        with monkeypatch.context() as m:
            m.setattr(json, "loads", boom)
            assert parse_node(data, node_id=NODE_ID, game_id=GAME_ID).status is NodeStatus.DAMAGED
    # Entries: missing → MISSING; an OSError on the read → UNREADABLE; a failed root check →
    # UNREADABLE with no read.
    assert read_node(game.folder, NODE_ID, game_id=GAME_ID).status is NodeStatus.MISSING
    (game.root / node_file(NODE_ID)).write_bytes(data)
    with monkeypatch.context() as m:
        m.setattr(safefile, "_read_bounded",
                  lambda *a: (_ for _ in ()).throw(OSError(5, "aiko read")))
        result = read_node(game.folder, NODE_ID, game_id=GAME_ID)
    assert result.status is NodeStatus.UNREADABLE
    game.clean_reason(result.reason)
    gone = NodeFolder(tmp_path / "aiko" / "nope", release=False)
    assert read_node(gone, NODE_ID, game_id=GAME_ID).reason == nodestates.REASON_ROOT
    # Fuzz: F11's mutation corpus over 3 node files, 200 cases.
    statuses = _node_corpus(200, seed=1, max_read_s=2.0)
    assert statuses.get("damaged", 0) > 0, statuses


@pytest.mark.slow
def test_ac_f20_45_slow_rows_and_corpus(tmp_path, monkeypatch, reduced_program):
    game = Game(tmp_path)
    for row in _rows("E", "slow"):
        if isinstance(gen_hostile_nodes.build(row), Sparse) and row.get("like", "").endswith("4_gib"):
            if shutil.disk_usage(tmp_path).free < 2 * (4 << 30):
                continue
        _check_row(row, game, monkeypatch, reduced_program)
    _node_corpus(10_000, seed=2, max_read_s=2.0)


# --- AC-F20-52: the state belongs to its node -----------------------------------------------------

def test_ac_f20_52_the_state_belongs_to_its_node(tmp_path):
    game = Game(tmp_path)
    key = node_key(NODE_ID)
    check = runtime_limits.FLOW_STATE_PATH_CHECK
    assert check == 16
    filler = tuple(f"{i:016x}" for i in range(1, 40))

    def read_with(path: tuple[str, ...]) -> nodestates.NodeRead:
        data = gen_hostile_nodes.encode(gen_hostile_nodes.node_state(path=path))
        (game.root / node_file(NODE_ID)).write_bytes(data)
        return read_node(game.folder, NODE_ID, game_id=GAME_ID)

    assert read_with((key,) + filler[:15]).status is NodeStatus.OK          # at -16
    for path in ((key,) + filler[:16], filler, ()):                          # -17; absent; empty
        result = read_with(path)
        assert (result.status, result.reason) == (NodeStatus.DAMAGED, nodestates.REASON_OTHER_NODE)
    # stall's file copied to river's name with node edited to chapter:river.
    stall = gen_hostile_nodes.base()
    (game.root / node_file(OTHER_ID)).write_bytes(ss.with_meta(stall, node=OTHER_ID))
    result = read_node(game.folder, OTHER_ID, game_id=GAME_ID)
    assert (result.status, result.reason) == (NodeStatus.DAMAGED, nodestates.REASON_OTHER_NODE)
    # The same file under its own name, unedited, is OK.
    (game.root / node_file(NODE_ID)).write_bytes(stall)
    assert read_node(game.folder, NODE_ID, game_id=GAME_ID).status is NodeStatus.OK


# --- AC-F20-39 (persist half): FlowListJob ---------------------------------------------------------

def test_flow_list_job_persist_half_of_ac_f20_39(tmp_path, monkeypatch):
    """The listing indexes regular node files with ``(size, mtime_ns)``, lists node temps
    over 60 s old, touches no other name, steps ≤ ``FLOW_LIST_STEP`` entries, stops at
    ``FLOW_SCAN_MAX``, and never calls ``remove_stale_temps``. The service's split into
    current files and orphans, and the removals, are s6's rows."""
    game = Game(tmp_path)
    now = time.time()
    names = {node_file(i): i for i in (NODE_ID, OTHER_ID, "orphan:1", "orphan:2")}
    for i, name in enumerate(names):
        (game.root / name).write_bytes(b"x" * (i + 1))
        os.utime(game.root / name, ns=(i * 10**9, i * 10**9))
    old = safefile.temp_name(node_file(NODE_ID), "0123abcd")
    young = safefile.temp_name(node_file(OTHER_ID), "4567cdef")
    (game.root / old).write_bytes(b"t")
    (game.root / young).write_bytes(b"t")
    os.utime(game.root / old, (now - 120, now - 120))
    os.utime(game.root / young, (now - 30, now - 30))
    before = game.snapshot()
    monkeypatch.setattr(safefile, "remove_stale_temps",
                        lambda *a, **k: pytest.fail("F20 never calls remove_stale_temps"))
    monkeypatch.setattr(limits, "FLOW_LIST_STEP", 2)
    job = FlowListJob(game.folder, now=now)
    clock = ss.FakeClock()
    steps = 0
    while not job.step(clock() + 0.05, clock):
        steps += 1
    assert job.root_ok and job.done and steps >= 3
    assert job.most_in_a_step <= 2 and job.examined == len(os.listdir(game.root))
    assert job.files == {name: nodestates.FileInfo(i + 1, i * 10**9)
                         for i, name in enumerate(names)}
    assert job.stale_temps == [old] and job.max_order == 3 * 10**9
    assert game.snapshot() == before                  # listing removes nothing
    # The scan cap: at most FLOW_SCAN_MAX entries are looked at.
    monkeypatch.setattr(limits, "FLOW_SCAN_MAX", 3)
    capped = FlowListJob(game.folder, now=now)
    capped.finish()
    assert capped.examined == 3 and capped.capped
    # A root that fails its check lists nothing (the service then runs in memory mode).
    spy = OsSpy().install(monkeypatch)
    bad = FlowListJob(NodeFolder(tmp_path / "missing", release=False), now=now)
    assert bad.step(0.0, lambda: 1.0) and bad.root_ok is False and bad.files == {}
    assert "scandir" not in spy
    monkeypatch.undo()
    # An abandoned job closes its listing and never restarts.
    abandoned = FlowListJob(game.folder, now=now)
    monkeypatch.setattr(limits, "FLOW_LIST_STEP", 1)
    abandoned.step(float("inf"), lambda: 0.0)
    abandoned.close()
    assert abandoned.done and abandoned.step(float("inf"), lambda: 0.0)


# --- AC-F20-41 (persist half): group A entries ----------------------------------------------------

def _make_entry(kind: str, at: Path, game: Game) -> Path | None:
    """The entry ``kind`` at ``at``; the target whose bytes must stay (or None)."""
    target = game.outside / "target.txt"
    target.write_bytes(b"ZZMARK outside")
    try:
        if kind == "folder":
            at.mkdir()
            (at / "inner.txt").write_bytes(b"inner")
            return at / "inner.txt"
        if kind == "file_symlink":
            os.symlink(target, at)
            return target
        if kind == "dir_symlink":
            os.symlink(game.outside, at, target_is_directory=True)
            return target
        if kind == "junction":
            import _winapi
            _winapi.CreateJunction(str(game.outside), str(at))
            return target
        if kind == "fifo":
            os.mkfifo(at)
            return None
        if kind == "hardlink_slot":
            os.link(game.root / "quick-1.vnsave", at)
            return game.root / "quick-1.vnsave"
        if kind == "hardlink_outside":
            os.link(target, at)
            return target
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"{kind} not permitted here: {exc}")
    raise KeyError(kind)


@pytest.mark.parametrize("row", [pytest.param(r, id=r["id"]) for r in _rows("A", "default")])
def test_group_a_entries_persist_half_of_ac_f20_41(row, tmp_path):
    """An entry at a node name: a link, junction, folder, or FIFO is never listed and
    ``read_node`` never follows it (MISSING); a hard link is a regular file, so it is listed
    and read as one (DAMAGED, since it isn't a node file);
    ``NodeFolder.remove`` takes only the entry. The service's rows (Jump's notice, forget,
    reset, eviction, the linked root) are s6's."""
    game = Game(tmp_path)
    at = game.root / node_file(NODE_ID)
    kept = _make_entry(row["entry"], at, game)
    kept_bytes = kept.read_bytes() if kept is not None else None
    job = FlowListJob(game.folder, now=time.time() + 3_600)
    job.finish()
    hard_link = row["entry"].startswith("hardlink")   # a regular file: listed like any other
    assert set(job.files) == ({node_file(NODE_ID)} if hard_link else set())
    assert job.stale_temps == []
    result = read_node(game.folder, NODE_ID, game_id=GAME_ID)
    assert result.status.value == row["read"], result
    game.clean_reason(result.reason)
    outcome = game.folder.remove(node_file(NODE_ID))
    if row["entry"] == "folder" or row["entry"] == "fifo":
        assert outcome is safefile.RemoveKind.NOT_FILE_OR_LINK and os.path.lexists(at)
    else:
        assert outcome is safefile.RemoveKind.REMOVED and not os.path.lexists(at)
    if kept is not None:
        assert kept.read_bytes() == kept_bytes
    assert ss.full(game.root).status is saves.SlotStatus.OK     # quick-1 still loads
