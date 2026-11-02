"""``persist/fileformat.py``: AC-F12-20 (the file's shape), AC-F12-21 (the writer's output
always reads back, TR-F12-01/09), AC-F12-25 (eviction at launch), AC-F12-26 (fuzzing), and
the reader's units (pre-scan, parse hooks, step budgets)."""

import json
import random
import socket
import time
from pathlib import Path

import pytest

from engine.core.safefile import ReadKind, ReadResult
from engine.persist import fileformat, limits
from engine.persist.fileformat import (NOT_PERSISTENT, NOT_VALID_JSON, OVER_CAP, Outcome,
                                       PieceEncoder, ReadJob, count_structure, encode_bytes,
                                       json_string, outcome_of_read, prescan)
from engine.runtime import persistent as P
from engine.runtime.persistent import CHOSEN, SEEN, PersistentStore
from tests.persist import fuzz_persistent, gen_hostile
from tests.persist.helpers import FakeProgram, random_store, read, same_store, snapshot

FILES = Path(__file__).resolve().parents[1] / "fixtures" / "F12" / "files"
EXAMPLE = (FILES / "valid.json").read_bytes()
MIB = 1 << 20


def example_store() -> PersistentStore:
    return PersistentStore.with_data(
        values={"festivals": 2, "hana_remembers": True, "endings": ["sad"]},
        seen=["riverbank/3fa9c2d81b07", "riverbank/9c1d04e2aa31~2", "start/77aa01c2b3d4"],
        chosen=[("bridge/5e0c11aa9b02", "a1b2c3d4e5f6"), ("bridge/5e0c11aa9b02", "0f9e8d7c6b5a")],
        unlocks={"cg": ["river_night"], "ending": ["sad"]})


# --- AC-F12-20: the file's shape ---------------------------------------------------------------

def test_ac_f12_20_exact_bytes():
    assert EXAMPLE == (
        b'{"format":1,"identity_scheme":1,"values":{"festivals":2,"hana_remembers":true,'
        b'"endings":["sad"]},"seen":{"riverbank":"3fa9c2d81b07 9c1d04e2aa31~2","start":'
        b'"77aa01c2b3d4"},"chosen":{"bridge/5e0c11aa9b02":"a1b2c3d4e5f6 0f9e8d7c6b5a"},'
        b'"unlocks":{"cg":["river_night"],"ending":["sad"]}}')
    assert b"".join(PieceEncoder().encode(example_store())) == EXAMPLE


def test_ac_f12_20_ascii_escapes_and_no_identity(tmp_path, user_roots):
    store = PersistentStore.with_data(values={"flower": "\u82b1", "odd": "\ud800",
                                              "home": "ZZMARK"})
    data = encode_bytes(store)
    assert data.isascii()
    assert b'"flower":"\\u82b1"' in data and b'"odd":"\\ud800"' in data
    assert b"qauser7" not in data
    assert socket.gethostname().encode("utf-8", "replace") not in data
    for part in tmp_path.parts:
        if len(part) >= 4:
            assert part.encode("utf-8", "replace") not in data
    assert json.loads(data).keys() == {"format", "identity_scheme", "values", "seen", "chosen",
                                       "unlocks"}


def test_structural_bytes_escaped_in_strings_of_records():
    store = PersistentStore(identity_scheme=1)
    store.register_kind("k{[,:")
    store.unlock("k{[,:", 'n"\\{[,:\u2028')
    piece = json_string("a{[,:")
    assert piece == b'"a\\u007b\\u005b\\u002c\\u003a"' and count_structure(piece) == 0
    data = encode_bytes(store)
    assert count_structure(data) == count_structure(encode_bytes(PersistentStore(
        identity_scheme=1))) + 2                    # only the kind's ':' and '['
    outcome, again, _ = read(data)
    assert outcome.kind is Outcome.OK and again.unlocked("k{[,:") == ('n"\\{[,:\u2028',)


def test_encoder_caches_blocks_and_follows_changes():
    store = PersistentStore(identity_scheme=1)
    encoder = PieceEncoder()
    for i in range(3_000):
        store.mark_seen(f"big/{i:012x}")
    first = b"".join(encoder.encode(store))
    store.mark_seen("big/ffffffffffff")
    second = b"".join(encoder.encode(store))
    assert second == encode_bytes(store) and second != first
    store.drop_record(SEEN, "big")
    store.mark_seen("big/000000000001")          # same label, new epoch
    assert b"".join(encoder.encode(store)) == encode_bytes(store)
    assert b'"big":"000000000001"' in encode_bytes(store)


# --- AC-F12-21: the writer's output always reads back -------------------------------------------

@pytest.mark.parametrize("step", [1, 7, None], ids=["step1", "step7", "default"])
def test_ac_f12_21_random_round_trips(step, monkeypatch, warnings):
    if step is not None:
        monkeypatch.setattr(limits, "READ_STEP_NAMES", step)
        monkeypatch.setattr(limits, "READ_STEP_KEYS", step)
    for seed in range(200):
        _round_trip(random.Random(f"ac21:{step}:{seed}"), seed)
    assert warnings.of("W54") == []


def _round_trip(rng: random.Random, seed: int) -> None:
    store = random_store(rng)
    data = encode_bytes(store)
    assert data.isascii() and prescan(data) is None, seed
    outcome, again, job = read(data)
    assert outcome.kind is Outcome.OK and outcome.dropped == 0, (seed, outcome)
    assert same_store(store, again), seed
    assert encode_bytes(again) == data, seed
    assert job.max_step_items <= max(limits.READ_STEP_KEYS, limits.READ_STEP_NAMES), seed


def _store_of_size(size: int) -> PersistentStore:
    """100 labels × 10 keys plus a padding value, encoding to exactly ``size`` bytes."""
    store = PersistentStore(identity_scheme=1)
    for g in range(100):
        for i in range(10):
            store.mark_seen(f"l{g}/{i:012x}")
    store.set("pad", "")
    store.set("pad", "x" * (size - len(encode_bytes(store))))
    assert len(encode_bytes(store)) == size
    return store


def test_ac_f12_21_file_limit_trims_oldest_labels(monkeypatch, warnings):
    store = _store_of_size(65_537)
    monkeypatch.setattr(limits, "FILE_MAX_BYTES", 65_536)
    data = encode_bytes(store)
    assert len(data) <= 65_536
    assert "l0" not in store.records(SEEN) and "l99" in store.records(SEEN)
    assert len(store.records(SEEN)) == 99
    assert warnings.of("W57") == ["the seen-line record is full (1,000,000 lines), so the "
                                  "oldest lines from scenes no longer in the story were "
                                  "dropped."]
    assert count_structure(data) <= limits.PRESCAN_MAX
    outcome, again, _ = read(data)
    assert outcome.kind is Outcome.OK and same_store(store, again)


def test_trim_drops_labels_the_program_lacks_first(monkeypatch, warnings):
    store = PersistentStore(identity_scheme=1)
    for g in range(60):
        store.mark_seen(f"l{g}/000000000000")
    program = FakeProgram(labels=[f"l{g}" for g in range(0, 60, 2)])
    full = count_structure(encode_bytes(store))
    monkeypatch.setattr(limits, "PRESCAN_MAX", full - 20)  # 10 labels must go (2 counts each)
    data = b"".join(PieceEncoder(program).encode(store))
    assert count_structure(data) <= full - 20
    gone = [f"l{g}" for g in range(60) if f"l{g}" not in store.records(SEEN)]
    assert gone == [f"l{g}" for g in range(1, 21, 2)]      # the oldest unknown ones
    assert read(data)[0].kind is Outcome.OK


def test_trim_reaches_menus_then_unlocks(monkeypatch, warnings):
    store = PersistentStore(identity_scheme=1)
    store.mark_seen("l/000000000000")
    for m in range(20):
        store.mark_chosen(f"m{m}/000000000000", "111111111111")
    store.register_kind("cg")
    for i in range(50):
        store.unlock("cg", f"{i}" * 30)
    base = len(encode_bytes(PersistentStore(identity_scheme=1)))
    monkeypatch.setattr(limits, "FILE_MAX_BYTES", base + 200)
    data = encode_bytes(store)
    assert len(data) <= base + 200
    assert not store.records(SEEN) and not store.records(CHOSEN)
    assert len(store.unlocked("cg")) < 50
    assert warnings.codes() == ["W57", "W57", "W57"]
    assert read(data)[0].kind is Outcome.OK


@pytest.mark.slow
def test_ac_f12_21_store_at_every_cap(warnings):
    rng = random.Random(21)
    store = PersistentStore(identity_scheme=1)
    for i in range(P.PERSIST_MAX_NAMES - 1):
        store.load_value(f"n{i}", i, str(i).encode())
    room = P.PERSIST_MAX_BYTES - store.values_bytes - len(b',"pad":[]')
    store.set("pad", [0] * ((room + 1) // 2))
    assert P.PERSIST_MAX_BYTES - 4 <= store.values_bytes <= P.PERSIST_MAX_BYTES
    for i in range(P.SEEN_MAX):
        store.mark_seen(f"l{i // 3 if i < 600_000 else 200_000 + (i - 600_000) // 2}/"
                        f"{rng.getrandbits(48):012x}")
    for i in range(P.CHOSEN_MAX):
        store.mark_chosen(f"m{i // 5}/aaaaaaaaaaaa", f"{i:012x}")
    for k in range(P.UNLOCK_KINDS_MAX):
        store.register_kind(f"kind{k}")
        for i in range(P.UNLOCK_NAMES_MAX):
            store.unlock(f"kind{k}", f"u{i}")
    start = time.perf_counter()
    data = encode_bytes(store)
    encode_s = time.perf_counter() - start
    assert len(data) <= limits.FILE_MAX_BYTES
    assert count_structure(data) <= limits.PRESCAN_MAX
    assert warnings.of("W57")[:1] == [P.full_text(SEEN)]
    start = time.perf_counter()
    outcome, again, job = read(data)
    read_s = time.perf_counter() - start
    print(f"every cap: {len(data) / MIB:.1f} MiB, encode {encode_s:.2f} s, read {read_s:.2f} s "
          f"in {job.steps} steps")
    assert outcome.kind is Outcome.OK and outcome.dropped == 0
    assert again.values_snapshot().keys() == store.values_snapshot().keys()
    assert snapshot(again)[2] == snapshot(store)[2]


# --- Reader units ------------------------------------------------------------------------------

def test_prescan_rules(monkeypatch):
    assert prescan(EXAMPLE) is None
    monkeypatch.setattr(limits, "FILE_MAX_BYTES", len(EXAMPLE) - 1)
    assert prescan(EXAMPLE) == OVER_CAP
    monkeypatch.setattr(limits, "FILE_MAX_BYTES", 1 << 25)
    monkeypatch.setattr(limits, "NON_ASCII_MAX_BYTES", 10)
    assert prescan("\u00e9".encode() * 6) == NOT_PERSISTENT
    assert prescan("\u00e9".encode() * 5) is None
    assert prescan(b"x" * 100) is None


def test_parse_int_hook_holds_with_digits_unlimited(monkeypatch):
    import sys
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        assert fileformat.parse("1" * 4_300) == int("1" * 4_300)
        assert fileformat.parse("-" + "1" * 4_300) < 0
        with pytest.raises(ValueError):
            fileformat.parse("1" * 4_301)
    finally:
        sys.set_int_max_str_digits(old)


def test_outcome_of_read():
    assert outcome_of_read(ReadResult(ReadKind.MISSING)) is None
    assert outcome_of_read(ReadResult(ReadKind.OK, b"{}")) is None
    assert outcome_of_read(ReadResult(ReadKind.TOO_LARGE)).reason == "over 32 MB"
    assert outcome_of_read(ReadResult(ReadKind.NOT_REGULAR)).reason == "not a regular file"
    unreadable = outcome_of_read(ReadResult(ReadKind.UNREADABLE))
    assert (unreadable.kind, unreadable.reason) == (Outcome.UNREADABLE, "couldn't be read")


def test_fixture_files():
    assert read(EXAMPLE)[0].kind is Outcome.OK
    assert read((FILES / "bad_brace.json").read_bytes())[0].reason == NOT_VALID_JSON
    assert read((FILES / "newer.json").read_bytes())[0].kind is Outcome.NEWER
    assert read((FILES / "newer_extra.json").read_bytes())[0].kind is Outcome.NEWER
    outcome, store, _ = read((FILES / "scheme2.json").read_bytes())
    assert outcome.scheme_changed and not store.records(SEEN) and not store.records(CHOSEN)
    assert store.values_snapshot()["festivals"] == 2 and store.unlocked("cg") == ("river_night",)


def test_job_drops_the_bytes_once_decoded():
    job = ReadJob(EXAMPLE, PersistentStore(identity_scheme=1), None)
    job.step()
    assert job._data is not None                  # the pre-scan step keeps them
    job.step()
    assert job._data is None and not job.done
    job.run()
    assert job.outcome.kind is Outcome.OK and job.step() is True


def test_known_names_are_read_first(monkeypatch):
    names = {f"j{i}": i for i in range(P.PERSIST_MAX_NAMES)}
    names["flag"] = True
    data = gen_hostile.dumps({"format": 1, "identity_scheme": 1, "values": names, "seen": {},
                              "chosen": {}, "unlocks": {}})
    outcome, store, _ = read(data, FakeProgram(persistent={"flag"}))
    assert outcome.dropped == 1 and store.values_snapshot()["flag"] is True
    assert "j9999" not in store.names()


def test_seen_steps_are_bounded():
    """AC-F12-31's count part: ≤ 50,000 keys per step; 120,000 sids take ≥ 3 seen steps."""
    store = PersistentStore(identity_scheme=1)
    for i in range(120_000):
        store.mark_seen(f"{'ab'[i % 2]}/{i:012x}")
    data = encode_bytes(store)
    outcome, again, job = read(data)
    assert outcome.kind is Outcome.OK and job.max_step_items <= limits.READ_STEP_KEYS
    assert job.steps >= 2 + 3 and again.record_total(SEEN) == 120_000


# --- AC-F12-25: eviction at launch --------------------------------------------------------------

def _seen_file(labels: int, per: int, extra: int = 0) -> tuple[bytes, list[str]]:
    seen = {}
    sids = []
    for g in range(labels):
        keys = [f"{g:04x}{i:08x}" for i in range(per + (1 if g < extra else 0))]
        seen[f"l{g}"] = " ".join(keys)
        sids += [f"l{g}/{k}" for k in keys]
    data = gen_hostile.dumps({"format": 1, "identity_scheme": 1, "values": {}, "seen": seen,
                              "chosen": {}, "unlocks": {}})
    return data, sids


def test_ac_f12_25_unknown_labels_go_first(monkeypatch, warnings):
    monkeypatch.setattr(P, "SEEN_MAX", 1_000)
    data, sids = _seen_file(10, 100)
    outcome, store, _ = read(data, FakeProgram(sids[300:]))
    assert store.record_total(SEEN) == 700 and outcome.full == (SEEN,)
    assert list(store.records(SEEN)) == [f"l{g}" for g in range(3, 10)]
    assert warnings.of("W57") == [P.full_text(SEEN)]
    assert "1,000 lines" in warnings.of("W57")[0]


def test_ac_f12_25_unknown_sids_in_known_labels(monkeypatch, warnings):
    monkeypatch.setattr(P, "SEEN_MAX", 1_000)
    data, sids = _seen_file(10, 100)
    unknown = set(sids[::10][:100]) | set(sids[1:200:10])   # 120 scattered sids
    program = FakeProgram([s for s in sids if s not in unknown],
                          labels=[f"l{g}" for g in range(10)])
    outcome, store, _ = read(data, program)
    assert store.record_total(SEEN) == 880
    assert not any(store.is_seen(s) for s in unknown)
    assert outcome.full == (SEEN,)


def test_ac_f12_25_all_known_drops_oldest(monkeypatch, warnings):
    monkeypatch.setattr(P, "SEEN_MAX", 1_000)
    data, sids = _seen_file(10, 100)
    outcome, store, _ = read(data, FakeProgram(sids))
    assert store.record_total(SEEN) == 900 and "l0" not in store.records(SEEN)
    assert len(warnings.of("W57")) == 1


def test_ac_f12_25_below_target_nothing(monkeypatch, warnings):
    monkeypatch.setattr(P, "SEEN_MAX", 1_000)
    data, sids = _seen_file(9, 99, extra=8)                 # 899 sids
    assert len(sids) == 899
    outcome, store, _ = read(data, FakeProgram())
    assert store.record_total(SEEN) == 899 and outcome.full == () and warnings == []


def test_ac_f12_25_chosen(monkeypatch, warnings):
    monkeypatch.setattr(P, "CHOSEN_MAX", 100)
    chosen = {f"m{g}/aaaaaaaaaaaa": " ".join(f"{g:04x}{i:08x}" for i in range(10))
              for g in range(10)}
    data = gen_hostile.dumps({"format": 1, "identity_scheme": 1, "values": {}, "seen": {},
                              "chosen": chosen, "unlocks": {}})
    known = [f"m{g}/aaaaaaaaaaaa" for g in range(3, 10)]
    outcome, store, _ = read(data, FakeProgram(known))
    assert store.record_total(CHOSEN) == 70 and outcome.full == (CHOSEN,)
    outcome, store, _ = read(data, FakeProgram(list(chosen)))
    assert store.record_total(CHOSEN) == 90 and "m0/aaaaaaaaaaaa" not in store.records(CHOSEN)
    assert warnings.of("W57")[-1] == P.full_text(CHOSEN)


@pytest.mark.slow
def test_ac_f12_25_real_cap_lookups_per_step(warnings):
    keys = [f"{i:012x}" for i in range(P.SEEN_MAX)]
    data = gen_hostile.dumps({"format": 1, "identity_scheme": 1, "values": {},
                              "seen": {"a": " ".join(keys[:500_000]),
                                       "b": " ".join(keys[500_000:])},
                              "chosen": {}, "unlocks": {}})
    program = FakeProgram([f"a/{k}" for k in keys[:400_000]] + [f"b/{k}" for k in keys[500_000:]])
    start = time.perf_counter()
    outcome, store, job = read(data, program)
    print(f"1,000,000-sid eviction read: {time.perf_counter() - start:.2f} s, {job.steps} steps")
    assert store.record_total(SEEN) == 900_000 and outcome.full == (SEEN,)
    assert job.max_step_lookups <= limits.READ_STEP_KEYS
    assert job.max_step_items <= limits.READ_STEP_KEYS


# --- AC-F12-26: fuzzing --------------------------------------------------------------------------

def _fuzz_bases() -> list[bytes]:
    bases = [EXAMPLE, (FILES / "scheme2.json").read_bytes(), (FILES / "newer.json").read_bytes()]
    bases += [path.read_bytes() for path in sorted(gen_hostile.HOSTILE.glob("c_*.json"))][:8]
    bases += [encode_bytes(random_store(random.Random(f"fuzz-base:{i}"))) for i in range(4)]
    return bases


def _fuzz(count: int, seed: int, *, time_steps: bool) -> None:
    slowest = 0.0
    for i, data in enumerate(fuzz_persistent.mutations(_fuzz_bases(), count, seed)):
        store = PersistentStore(identity_scheme=1)
        job = ReadJob(data, store, None)
        while True:
            start = time.perf_counter()
            done = job.step()
            slowest = max(slowest, time.perf_counter() - start)
            if done:
                break
        outcome = job.outcome
        assert outcome.kind in (Outcome.OK, Outcome.BAD, Outcome.NEWER), (i, outcome)
        if outcome.kind is Outcome.OK:
            again_bytes = encode_bytes(store)
            again_outcome, again, _ = read(again_bytes)
            assert again_outcome.kind is Outcome.OK and again_outcome.dropped == 0, i
            assert same_store(store, again), i
            assert encode_bytes(again) == again_bytes, i
    if time_steps:
        assert slowest <= 2.0, slowest


@pytest.mark.parametrize("seed", [26])
def test_ac_f12_26_fuzz_default(seed):
    _fuzz(200, seed, time_steps=False)


@pytest.mark.slow
@pytest.mark.parametrize("seed", [2600])
def test_ac_f12_26_fuzz_slow(seed):
    _fuzz(10_000, seed, time_steps=True)
