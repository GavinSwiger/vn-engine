"""The hostile manifest (TR-F12-04): AC-F12-22 (group A), AC-F12-23 (group B), AC-F12-24
(group C).

Each row is written to ``tmp_path/game/persistent/persistent.json``, read through
``core.safefile.read_regular`` and ``ReadJob``, and checked against its expected outcome.
Every row also asserts (06 §0.2): no exception escapes, ``json.loads`` receives only
``str``, every file in ``tmp_path/outside/`` is unchanged, and nothing is created outside
``<game>/persistent/``.
"""

import hashlib
import json
import sys
import time
import tracemalloc
from pathlib import Path

import pytest

from engine.core.safefile import read_regular
from engine.persist import limits
from engine.persist.fileformat import Outcome, ReadJob, encode_bytes, outcome_of_read
from engine.runtime.persistent import CHOSEN, SEEN, PersistentStore
from tests.persist import gen_hostile
from tests.persist.gen_hostile import GOOD_MENU, HOSTILE, Sparse
from tests.persist.helpers import read

ROWS = gen_hostile.load_manifest()
MIB = 1 << 20


def _param(row: dict):
    marks = [pytest.mark.slow] if row["tier"] == "slow" else []
    return pytest.param(row, id=row["id"], marks=marks)


def _tree(root: Path) -> dict[str, str]:
    """Every file under ``root`` → its SHA-256 (sparse files by size only)."""
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            size = path.stat().st_size
            out[path.relative_to(root).as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest() if size < 64 * MIB else str(size))
        else:
            out[path.relative_to(root).as_posix()] = "dir"
    return out


class Run:
    """One row read end to end."""

    def __init__(self, row: dict, tmp_path: Path, monkeypatch) -> None:
        self.row = row
        folder = tmp_path / "game" / "persistent"
        folder.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.json").write_bytes(gen_hostile.dumps(gen_hostile.GOOD))
        (outside / "notes.txt").write_bytes(b"ZZMARK qauser7")
        target = folder / "persistent.json"
        content = (HOSTILE / row["file"]).read_bytes() if "file" in row else gen_hostile.build(row)
        if isinstance(content, Sparse):
            if content.size > 1 << 30 and _free_bytes(tmp_path) < 2 * content.size:
                pytest.skip("not enough free disk for a 4 GiB file")
            with open(target, "wb") as f:
                f.truncate(content.size)
        else:
            target.write_bytes(content)
        del content
        self.before = _tree(tmp_path)
        self.tmp_path = tmp_path
        self.loads_args: list[type] = []
        real_loads = json.loads

        def spy(text, *args, **kwargs):
            self.loads_args.append(type(text))
            return real_loads(text, *args, **kwargs)

        monkeypatch.setattr(json, "loads", spy)
        self.target = target
        self.store = PersistentStore(identity_scheme=1)
        self.step_times: list[float] = []
        self.peak = 0

    def go(self, *, trace: bool = False):
        old_digits = sys.get_int_max_str_digits()
        if "max_str_digits" in self.row:
            sys.set_int_max_str_digits(self.row["max_str_digits"])
        if trace:
            tracemalloc.start()
        try:
            start = time.perf_counter()
            result = read_regular(self.target, limits.FILE_MAX_BYTES)
            self.step_times.append(time.perf_counter() - start)
            outcome = outcome_of_read(result)
            if outcome is None:
                job = ReadJob(result.data, self.store, None)
                del result
                while True:
                    start = time.perf_counter()
                    done = job.step()
                    self.step_times.append(time.perf_counter() - start)
                    if done:
                        break
                outcome = job.outcome
            if trace:
                self.peak = tracemalloc.get_traced_memory()[1]
        finally:
            if trace:
                tracemalloc.stop()
            sys.set_int_max_str_digits(old_digits)
        return outcome

    def check_common(self) -> None:
        assert all(t is str for t in self.loads_args)
        assert _tree(self.tmp_path) == self.before


def _free_bytes(path: Path) -> int:
    import shutil
    return shutil.disk_usage(path).free


def _check_outcome(row: dict, outcome) -> None:
    expected = row["outcome"]
    if expected == "any":
        assert outcome.kind in (Outcome.OK, Outcome.BAD, Outcome.NEWER)
        return
    assert outcome.kind is Outcome(expected), outcome
    if expected == "bad":
        assert outcome.reason == row["reason"]
    if expected == "ok":
        if "dropped" in row:
            assert outcome.dropped == row["dropped"], outcome
        if "min_dropped" in row:
            assert outcome.dropped >= row["min_dropped"], outcome
        assert outcome.scheme_changed == row.get("scheme_changed", False)


@pytest.mark.parametrize("row", [_param(r) for r in ROWS if r["group"] in "AB"])
def test_groups_a_and_b(row, tmp_path, monkeypatch, warnings):
    run = Run(row, tmp_path, monkeypatch)
    start = time.perf_counter()
    outcome = run.go()
    elapsed = time.perf_counter() - start
    _check_outcome(row, outcome)
    run.check_common()
    if row.get("loads") == "never":
        assert run.loads_args == []
    if "max_seconds" in row:
        assert elapsed < row["max_seconds"]
    if outcome.kind is Outcome.OK and row["outcome"] == "ok":
        assert run.store.values_snapshot()["good"] == 1
        if outcome.scheme_changed:
            assert warnings.of("W55") == [
                "seen-line records in persistent.json come from a different engine version, so "
                "every line counts as unread once more. Your other persistent data is kept."]
            assert not run.store.records(SEEN) and not run.store.records(CHOSEN)
    if outcome.kind is not Outcome.OK:
        assert run.store.version == 0               # decided before any change


@pytest.mark.parametrize("row", [_param(r) for r in ROWS if r["group"] == "C"])
def test_group_c_bad_entries_are_dropped(row, tmp_path, monkeypatch, warnings):
    run = Run(row, tmp_path, monkeypatch)
    outcome = run.go()
    _check_outcome(row, outcome)
    run.check_common()
    store = run.store
    assert store.values_snapshot()["good"] == 1
    assert store.unlocked("good") == ("a",)
    if outcome.scheme_changed:
        assert not store.records(SEEN) and not store.records(CHOSEN)
        assert warnings.codes() == ["W55"]           # not counted in W54
    else:
        assert list(store.records(SEEN)) == ["good"]
        assert list(store.records(CHOSEN)) == [GOOD_MENU]
        assert store.is_seen("good/0123456789ab")
        assert store.was_chosen(GOOD_MENU, "0123456789ab")
    if outcome.dropped:
        assert warnings.codes()[:1] == ["W54"]
        assert any(f"had {outcome.dropped:,} entr" in m for m in warnings.of("W54"))
    if row["gen"] == "unlock_dup":
        assert store.unlocked("cg") == ("a",)
    if row["gen"] == "many_names":
        assert len(store.names()) == 10_000 and "good" in store.names()
    if row["id"] == "c_name_255":
        assert "a" * 255 in store.names()
    if row["id"] == "c_value_100_deep":
        assert "x" in store.names()
    # Nothing bad is ever written back: the re-encoding reads back with no drops.
    again, _, _ = read(encode_bytes(store))
    assert again.kind is Outcome.OK and again.dropped == 0


def test_committed_files_match_the_generator():
    for row in ROWS:
        if "file" in row:
            assert (HOSTILE / row["file"]).read_bytes() == gen_hostile.build(row), row["id"]


def test_manifest_rows_are_complete():
    ids = [row["id"] for row in ROWS]
    assert len(ids) == len(set(ids))
    for row in ROWS:
        assert row["group"] in "ABC" and row["tier"] in ("default", "slow")
        assert row["outcome"] in ("ok", "bad", "newer", "any")
        assert row["outcome"] != "bad" or row["reason"]


def test_prescan_bound_patched(monkeypatch):
    """AC-F12-23, every pre-scan shape (``values.a`` of ``{}``, ``[]``, ``0.5``; many names;
    many seen labels) at a patched bound: at the bound a file is parsed; one more counted
    byte is refused before ``json.loads``. The real bound runs by default for ``dicts``
    only (manifest ``b_dicts_over``); the other shapes' real rows are ``slow``. Exact
    counts need no separate check: ``gen_hostile.shape_file`` asserts each one."""
    monkeypatch.setattr(limits, "PRESCAN_MAX", 10_000)
    calls = []
    real_loads = json.loads
    monkeypatch.setattr(json, "loads", lambda *a, **k: calls.append(1) or real_loads(*a, **k))
    for shape in ("dicts", "lists", "floats", "names", "labels"):
        at, _, _ = read(gen_hostile.shape_file(shape, count=10_000))
        assert at.kind is Outcome.OK and calls, shape
        calls.clear()
        over, _, _ = read(gen_hostile.shape_file(shape, count=10_001))
        assert (over.kind, over.reason) == (Outcome.BAD, "not persistent data"), shape
        assert calls == [], shape


@pytest.mark.slow
@pytest.mark.parametrize("row", [_param(r) for r in ROWS if r["group"] == "B"
                                 and r["tier"] == "slow" and r["gen"] != "sparse"])
def test_group_b_memory_and_step_time(row, tmp_path, monkeypatch, record_property):
    """SEC-F12-02 property: peak tracemalloc ≤ 320 MiB during read and validation, and no
    step over 2 s (timed untraced)."""
    run = Run(row, tmp_path, monkeypatch)
    run.go()
    assert max(run.step_times) <= 2.0, run.step_times
    traced = Run.__new__(Run)
    traced.__dict__.update(run.__dict__)
    traced.store = PersistentStore(identity_scheme=1)
    traced.step_times = []
    traced.go(trace=True)
    record_property("peak_mib", traced.peak / MIB)
    record_property("max_step_s", max(run.step_times))
    print(f"{row['id']}: peak {traced.peak / MIB:.1f} MiB, slowest step "
          f"{max(run.step_times) * 1000:.0f} ms, total {sum(run.step_times) * 1000:.0f} ms")
    assert traced.peak <= 320 * MIB
