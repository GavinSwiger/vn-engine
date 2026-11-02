"""The hostile save manifest (TR-F11-03): AC-F11-08 (group A), AC-F11-09 (group B),
AC-F11-10 (group D), AC-F11-11 (one strict parser), AC-F11-12 (the mutation corpus), and the
head path's byte half of group C (SEC-F11-01, -02).

Each row is written to ``tmp_path/game/saves/quick-1.vnsave`` beside a valid ``quick-2``,
then read by ``read_slot_head`` and ``read_slot_full``. Every row also asserts (06 §0.2): no
exception escapes, ``json.loads`` receives only ``str``, ``tmp_path/outside/`` and the other
slot are unchanged, nothing is created outside the saves root, and the two readers agree.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.core import safefile
from engine.persist import fileformat, limits, saves
from engine.persist.saves import SlotId, SlotStatus
from engine.runtime.interpreter import RestoreResult
from engine.runtime.state import GameState
from tests.persist import fuzz_saves, gen_hostile_saves
from tests.persist import save_support as ss
from tests.persist.gen_hostile_saves import Sparse

ROWS = gen_hostile_saves.load_manifest()
MIB = 1 << 20
REPO = Path(__file__).resolve().parents[2]
STATUS = {s.value: s for s in SlotStatus}


def _param(row: dict):
    marks = [pytest.mark.slow] if row["tier"] == "slow" else []
    return pytest.param(row, id=row["id"], marks=marks)


def _tree(root: Path) -> dict[str, str]:
    """Every entry under ``root`` → its SHA-256 (large files by size only)."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            out[path.relative_to(root).as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest() if size < 64 * MIB else str(size))
        else:
            out[path.relative_to(root).as_posix()] = "dir"
    return out


def _free_bytes(path: Path) -> int:
    import shutil
    return shutil.disk_usage(path).free


class Run:
    """One row on disk, read by both paths with the spies installed."""

    def __init__(self, row: dict, tmp_path: Path, monkeypatch) -> None:
        self.row = row
        self.folder = tmp_path / "game" / "saves"
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.vnsave").write_bytes(gen_hostile_saves.base(thumb=False))
        (outside / "notes.txt").write_bytes(b"ZZMARK qauser7")
        ss.write_slot(self.folder, gen_hostile_saves.base(), SlotId("quick", 2))
        content = gen_hostile_saves.build(row)
        target = self.folder / ss.QUICK_1.file_name()
        if isinstance(content, Sparse):
            if content.size > 1 << 30 and _free_bytes(tmp_path) < 2 * content.size:
                pytest.skip("not enough free disk for a 4 GiB file")
            with open(target, "wb") as f:
                f.truncate(content.size)
        else:
            target.write_bytes(content)
        del content
        self.target = target
        self.tmp_path = tmp_path
        self.before = _tree(tmp_path)
        self.reads = ss.ReadSpy().install(monkeypatch)
        self.loads = ss.LoadsSpy().install(monkeypatch)
        self.decodes = ss.DecodeSpy().install(monkeypatch)
        if row["gen"] == "grow":
            real_open = safefile._open_for_reading

            def grow_then_open(path):
                with open(path, "ab") as f:          # after lstat, before the read
                    f.write(b"\n")
                return real_open(path)

            monkeypatch.setattr(safefile, "_open_for_reading", grow_then_open)

    def head(self, *, thumb: bool = False) -> saves.SlotHead:
        self.reads.clear()
        return ss.head(self.folder, thumb=thumb)

    def full(self) -> saves.FullRead:
        self.reads.clear()
        self.loads.clear()
        return ss.full(self.folder)

    def check_common(self) -> None:
        assert all(kind is str for kind, _ in self.loads)
        after = _tree(self.tmp_path)
        if self.row["gen"] == "grow":                 # the row's own file grew by design
            after.pop("game/saves/quick-1.vnsave")
            self.before.pop("game/saves/quick-1.vnsave")
        assert after == self.before


def _expect(status: SlotStatus, expected: str) -> None:
    if expected == "any":
        assert status in (SlotStatus.OK, SlotStatus.DAMAGED), status
    else:
        assert status is STATUS[expected], status


def agree(head: SlotStatus, full: SlotStatus) -> bool:
    """AC-F11-11: equal, or an OK head that line 3 makes DAMAGED or NEWER."""
    return head is full or (head is SlotStatus.OK
                            and full in (SlotStatus.DAMAGED, SlotStatus.NEWER))


@pytest.mark.parametrize("row", [_param(r) for r in ROWS])
def test_manifest_row(row, tmp_path, monkeypatch):
    run = Run(row, tmp_path, monkeypatch)
    head = run.head()
    head_reads = list(run.reads)
    if row["gen"] == "grow":                              # grow only once more for the full read
        run.target.write_bytes(gen_hostile_saves.build(row))
        run.before = _tree(tmp_path)
    full = run.full()
    full_reads = list(run.reads)
    full_loads = len(run.loads)
    _expect(head.status, row["head"])
    _expect(full.status, row["full"])
    assert agree(head.status, full.status)
    assert head.jpeg is None                              # thumb=False never decodes
    assert sum(head_reads) <= limits.HEAD_MAX
    assert sum(full_reads) <= limits.SAVE_FILE_MAX + 1
    if row.get("size_first"):
        assert head_reads == [] and full_reads == []
        assert head.cause is saves.Cause.ENTRY and full.cause is saves.Cause.ENTRY
    if "loads" in row:
        assert full_loads == row["loads"]
    if head.status is SlotStatus.DAMAGED:
        assert head.cause is not None and head.reason
    if full.status is SlotStatus.OK:
        assert isinstance(full.state, GameState) and full.reason == ""
    else:
        assert full.state is None and full.reason
    if row["group"] == "C":
        run.decodes.clear()
        thumbed = run.head(thumb=True)
        assert thumbed.status is head.status
        if row["thumb"] == "jpeg":
            assert thumbed.jpeg == gen_hostile_saves.thumb_jpeg()
        else:
            assert thumbed.jpeg is None
        if "decodes" in row:
            assert len(run.decodes) == row["decodes"]
    run.check_common()


def test_prescan_bound_is_inclusive(tmp_path, monkeypatch):
    """``d_prescan_at``/``d_prescan_over`` at a bound lowered to 2,000 (the full-size
    ``d_prescan_at`` row is ``slow``): line 3 is parsed at the bound and refused one over it."""
    monkeypatch.setattr(limits, "SAVE_PRESCAN_MAX", 2_000)
    for count, loads in ((2_000, 2), (2_001, 1)):
        folder = tmp_path / str(count)
        row = {"id": f"prescan_{count}", "gen": "state_structure", "count": count}
        ss.write_slot(folder, gen_hostile_saves.build(row))
        spy = ss.LoadsSpy().install(monkeypatch)
        full = ss.full(folder)
        assert len(spy) == loads, (count, full)
        if loads == 1:
            assert full.status is SlotStatus.DAMAGED


def test_manifest_rows_are_complete():
    ids = [row["id"] for row in ROWS]
    assert len(ids) == len(set(ids))
    for row in ROWS:
        assert row["group"] in "ABCD" and row["tier"] in ("default", "slow")
        assert row["head"] in STATUS and (row["full"] in STATUS or row["full"] == "any")
    shapes = {row["shape"] for row in ROWS if row["gen"] == "shape"}
    assert shapes == set(gen_hostile_saves.SHAPES)


def test_both_paths_use_f12s_hooks(tmp_path, monkeypatch):
    """AC-F11-11: the same hook objects on both paths, shared with F12 (by ``is``)."""
    ss.write_slot(tmp_path, gen_hostile_saves.base())
    loads = ss.LoadsSpy().install(monkeypatch)
    assert ss.head(tmp_path).status is SlotStatus.OK
    assert ss.full(tmp_path).status is SlotStatus.OK
    assert len(loads) == 3                                # head line 1; full lines 1 and 3
    for kind, kwargs in loads:
        assert kind is str
        assert kwargs["object_pairs_hook"] is fileformat._no_duplicates
        assert kwargs["parse_constant"] is fileformat._refuse_constant
        assert kwargs["parse_int"] is fileformat._parse_int


@pytest.mark.parametrize("error", [RecursionError, ValueError, MemoryError,
                                   UnicodeDecodeError, OverflowError])
def test_parser_exceptions_are_damaged_on_both_paths(error, tmp_path, monkeypatch):
    """AC-F11-10 (last paragraph); SEC-F11-06's exception set."""
    ss.write_slot(tmp_path, ss.make_save())

    def boom(*args, **kwargs):
        if error is UnicodeDecodeError:
            raise UnicodeDecodeError("ascii", b"\xff", 0, 1, "patched")
        raise error("patched")

    monkeypatch.setattr(json, "loads", boom)
    head, full = ss.head(tmp_path), ss.full(tmp_path)
    assert (head.status, head.cause) == (SlotStatus.DAMAGED, saves.Cause.CONTENT)
    assert (full.status, full.cause) == (SlotStatus.DAMAGED, saves.Cause.CONTENT)


def test_other_exceptions_propagate(tmp_path, monkeypatch):
    """Anything outside the set is a programmer error, never DAMAGED."""
    ss.write_slot(tmp_path, ss.make_save())

    def boom(*args, **kwargs):
        raise KeyError("patched")

    monkeypatch.setattr(json, "loads", boom)
    with pytest.raises(KeyError):
        ss.head(tmp_path)


def test_parser_exceptions_in_line3_are_damaged(tmp_path, monkeypatch):
    """A failure only in line 3's parse: the head is OK, the full read DAMAGED."""
    ss.write_slot(tmp_path, ss.make_save())
    real = json.loads
    calls = []

    def second_fails(text, *args, **kwargs):
        calls.append(len(text))
        if len(calls) == 2:
            raise RecursionError("patched")
        return real(text, *args, **kwargs)

    monkeypatch.setattr(json, "loads", second_fails)
    full = ss.full(tmp_path)
    assert (full.status, full.reason) == (SlotStatus.DAMAGED, saves.REASON_JSON)


# --- AC-F11-10: each AC-F03-62 rejected row, and the digit run ---------------------------------

def _f03_rows():
    from tests.runtime.test_state_json import REJECTED
    return sorted(REJECTED.items())


@pytest.mark.parametrize("name, make", _f03_rows(), ids=[n for n, _ in _f03_rows()])
def test_f03_rejected_states_never_load(name, make, tmp_path):
    """Each F03 §9.1 rejected state as line 3: DAMAGED, or NEWER for F03's unknown_key and
    a later format; JSON-lossy rows (a tuple, a set, an int key) are what JSON makes them."""
    obj = make()
    try:
        line = ss.state_json_line(obj, allow_nan=True)
    except (TypeError, ValueError):                       # a set, a 4,301-digit int (the
        pytest.skip("not expressible as JSON here")      # manifest's d_int_4301_digits)
    ss.write_slot(tmp_path, ss.with_line3(ss.make_save(), line))
    full = ss.full(tmp_path)
    reread = json.loads(line)
    try:
        GameState.from_json(reread)
        expected = SlotStatus.OK                         # (1, 2) → [1, 2]; {1: 2} → {"1": 2}
    except Exception as error:
        reason = getattr(error, "reason", "")
        newer = reason == "unknown_key" or (type(reread) is dict
                                            and type(reread.get("format")) is int
                                            and reread["format"] > 1)
        expected = SlotStatus.NEWER if newer else SlotStatus.DAMAGED
    if any(token in line for token in (b"NaN", b"Infinity")):
        expected = SlotStatus.DAMAGED                     # the reader refuses the constants
    assert full.status is expected, (name, full)
    assert ss.head(tmp_path).status is SlotStatus.OK


@pytest.mark.parametrize("digits", [pytest.param(MIB, id="1MiB"),
                                    pytest.param(24 * MIB - 4096, id="24MiB",
                                                 marks=pytest.mark.slow)])
def test_digit_run_with_the_int_limit_lifted(digits, tmp_path):
    """AC-F11-10: the 4,300-digit hook holds when ``PYTHONINTMAXSTRDIGITS=0`` lifts
    Python's own limit (a subprocess, so this process keeps its setting)."""
    line = ss.state_line(b'{"v":' + b"7" * digits + b"}")
    ss.write_slot(tmp_path, ss.with_line3(ss.make_save(), line))
    code = ("import sys, time; from pathlib import Path; from engine.persist import saves; "
            "t = time.perf_counter(); r = saves.read_slot_full(Path(sys.argv[1]), "
            "saves.SlotId('quick', 1), game_id='f11-template'); "
            "print(r.status.value, r.reason, sys.get_int_max_str_digits(), "
            "round(time.perf_counter() - t, 3))")
    env = {**os.environ, "PYTHONINTMAXSTRDIGITS": "0"}
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    status, *reason, max_digits, seconds = done.stdout.split()
    assert (status, " ".join(reason), max_digits) == ("damaged", saves.REASON_JSON, "0")
    assert float(seconds) < 2.0


# --- AC-F11-12: the mutation corpus -------------------------------------------------------------

@pytest.fixture(scope="module")
def reduced_program(tmp_path_factory):
    from tests.runtime.story import load_files
    return load_files(tmp_path_factory.mktemp("template"), {"main.vns": ss.TEMPLATE_S_REDUCED})


def _valid_bases(program) -> list[bytes]:
    """Three valid saves of the reduced template: the first line, P8, and the last line."""
    from tests.fakes import jpegs
    from tests.runtime.story import checkpoints, start
    states = checkpoints(start(program))
    picks = (states[0], states[1], states[-1])
    thumbs = (jpegs.engine_jpeg("flat"), jpegs.engine_jpeg("bands"), None)
    return [ss.make_save(state, jpeg=jpeg, seq=i + 1) for i, (state, jpeg)
            in enumerate(zip(picks, thumbs))]


def _corpus_bases(program) -> list[bytes]:
    bases = _valid_bases(program)
    for row in ROWS:
        if row["tier"] == "default" and row["gen"] not in ("sparse", "shape", "grow",
                                                           "state_structure"):
            data = gen_hostile_saves.build(row)
            if isinstance(data, bytes) and len(data) < MIB:
                bases.append(data)
    return bases


def test_p8_state_is_the_real_checkpoint(reduced_program):
    from tests.runtime.story import checkpoints, start
    assert checkpoints(start(reduced_program))[1] == ss.p8_state()


def _corpus(program, count: int, seed: int, tmp_path: Path, *, max_read_s: float | None = None):
    from tests.runtime.story import launched
    bases = _corpus_bases(program)
    valid = _valid_bases(program)
    third_lines = [ss.lines(b)[2] for b in valid]
    folder = tmp_path / "saves"
    statuses: dict[str, int] = {}
    for i, data in enumerate(fuzz_saves.mutations(bases, count, seed)):
        ss.write_slot(folder, data)
        head = ss.head(folder)
        thumbed = ss.head(folder, thumb=True)
        start = time.perf_counter()
        full = ss.full(folder)
        if max_read_s is not None:
            assert time.perf_counter() - start < max_read_s, i
        assert head.status in SlotStatus and full.status in SlotStatus
        assert thumbed.status is head.status
        assert agree(head.status, full.status), (i, head, full)
        # A file whose line 3 is a valid base's, byte for byte and as declared, reads the
        # same on both paths (the mutation touched only lines 1-2).
        if (head.status is SlotStatus.OK and head.meta is not None
                and any(data.endswith(t) and head.meta.state_len == len(t)
                        for t in third_lines)):
            assert full.status is SlotStatus.OK, (i, full)
        if full.status is SlotStatus.OK:
            assert full.state is not None
            outcome = launched(program).restore(full.state)
            assert outcome.result in RestoreResult
        statuses[full.status.value] = statuses.get(full.status.value, 0) + 1
    return statuses


def test_mutation_corpus(reduced_program, tmp_path):
    statuses = _corpus(reduced_program, 200, seed=1, tmp_path=tmp_path)
    assert statuses.get("damaged", 0) > 0 and statuses.get("ok", 0) > 0, statuses


@pytest.mark.slow
def test_mutation_corpus_10000(reduced_program, tmp_path):
    _corpus(reduced_program, 10_000, seed=2, tmp_path=tmp_path, max_read_s=2.0)
