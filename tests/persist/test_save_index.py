"""The slot index (F11 ``04`` §7.4; SEC-F11-13): the unit half of AC-F11-15 (one ``scandir``,
``META_MAX`` reads, slices, ``max_seq``, junk falling back to the fixed names) and the listing
rows of AC-F11-13 (look-alike names are never indexed). ``saves_root`` is in
``test_save_format``; install, W81, and stale temps come with ``SaveService`` (step 8)."""

import os

import pytest

from engine.persist import limits, saves
from engine.persist.saves import IndexJob, SlotId, SlotStatus
from tests.persist import save_support as ss


class HeadClock:
    """1 ms per head read (``read_slot_head`` patched to advance it)."""

    def __init__(self, monkeypatch) -> None:
        self.now = 0
        real = saves.read_slot_head

        def counted(*args, **kwargs):
            self.now += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(saves, "read_slot_head", counted)

    def __call__(self) -> int:
        return self.now


@pytest.fixture(scope="module")
def p8() -> bytes:
    return ss.make_save()


def fill(folder, p8: bytes, slots, *, seq=lambda i: i + 1) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for i, slot in enumerate(slots):
        (folder / slot.file_name()).write_bytes(ss.with_meta(p8, seq=seq(i)))


def test_612_slots_in_slices(tmp_path, p8, monkeypatch):
    folder = tmp_path / "saves"
    slots = saves.all_slots(100)
    fill(folder, p8, slots)
    scans = []
    real_scandir = os.scandir
    monkeypatch.setattr(saves.os, "scandir", lambda p: scans.append(p) or real_scandir(p))
    reads = ss.ReadSpy().install(monkeypatch)
    clock = HeadClock(monkeypatch)
    job = IndexJob(folder, game_id=ss.GAME_ID, pages=100)
    steps = 0
    while not job.step(clock() + 4, clock):
        steps += 1
    steps += 1
    assert len(scans) == 1 and steps == job.steps >= 153
    assert len(job.heads) == 612 and set(job.heads) == set(slots)
    assert max(reads) <= limits.META_MAX
    assert saves.next_seq(job.heads.values()) == 613
    assert all(h.status is SlotStatus.OK and h.jpeg is None for h in job.heads.values())


def test_seq_of_unreadable_newer_and_other_heads_is_ignored(tmp_path, p8):
    folder = tmp_path / "saves"
    fill(folder, p8, [SlotId("quick", 1)], seq=lambda i: 40)
    (folder / "quick-2.vnsave").write_bytes(ss.with_meta(p8, seq=900, game="other-game"))
    (folder / "quick-3.vnsave").write_bytes(ss.with_meta(p8, seq=901, state_format=2))
    (folder / "quick-4.vnsave").write_bytes(ss.with_meta(p8, seq=902)[:-5])
    (folder / "quick-5.vnsave").mkdir()
    job = IndexJob(folder, game_id=ss.GAME_ID, pages=10)
    heads = job.finish()
    assert {s.n: h.status for s, h in heads.items()} == {
        1: SlotStatus.OK, 2: SlotStatus.OTHER_GAME, 3: SlotStatus.NEWER,
        4: SlotStatus.DAMAGED, 5: SlotStatus.DAMAGED}
    assert heads[SlotId("quick", 5)].cause is saves.Cause.ENTRY
    assert saves.next_seq(heads.values()) == 41


def test_look_alike_names_are_never_indexed(tmp_path, p8):
    folder = tmp_path / "saves"
    folder.mkdir()
    for name in ("QUICK-1.vnsave", "quick-1.vnsave.bak", "page101-1.vnsave", "page0-1.vnsave",
                 "page03-1.vnsave", "notes.txt", ".quick-1.vnsave.0123abcd.tmp",
                 "page11-1.vnsave"):
        (folder / name).write_bytes(ss.with_meta(p8, seq=999))
    fill(folder, p8, [SlotId("auto", 3)], seq=lambda i: 5)
    assert len(os.listdir(folder)) == 9
    heads = IndexJob(folder, game_id=ss.GAME_ID, pages=10).finish()
    assert list(heads) == [SlotId("auto", 3)]               # page11 is past [saves] pages
    assert saves.next_seq(heads.values()) == 6


def test_a_missing_folder_indexes_nothing(tmp_path):
    job = IndexJob(tmp_path / "nope", game_id=None, pages=10)
    assert job.step(0, lambda: 1) is True and job.heads == {}


class _Entry:
    def __init__(self, name: str) -> None:
        self.name = name


class _Listing:
    def __init__(self, names) -> None:
        self.names = names

    def __enter__(self):
        return iter(_Entry(n) for n in self.names)

    def __exit__(self, *exc) -> None:
        return None


@pytest.mark.parametrize("cap, junk", [pytest.param(50, 60, id="patched"),
                                       pytest.param(6_000, 50_000, id="real",
                                                    marks=pytest.mark.slow)])
def test_junk_listed_first_falls_back_to_the_fixed_names(cap, junk, tmp_path, p8, monkeypatch):
    """SEC-F11-13: junk can't hide saves; Newest and the next ``seq`` equal a junk-free run."""
    folder = tmp_path / "saves"
    slots = [SlotId("auto", 2), SlotId("quick", 4), SlotId(3, 1), SlotId(10, 6)]
    fill(folder, p8, slots, seq=lambda i: [7, 3, 9, 4][i])
    clean = IndexJob(folder, game_id=ss.GAME_ID, pages=10).finish()
    monkeypatch.setattr(limits, "INDEX_MAX_EXAMINED", cap)
    names = [f"junk{i:05}.txt" for i in range(junk)] + [s.file_name() for s in slots]
    monkeypatch.setattr(saves.os, "scandir", lambda p: _Listing(names))
    job = IndexJob(folder, game_id=ss.GAME_ID, pages=10)
    heads = job.finish()
    assert job.fell_back and job.examined == cap
    assert heads.keys() == clean.keys() == set(slots)
    assert saves.newest(heads.values()) == saves.newest(clean.values()) == SlotId(3, 1)
    quick = [heads.get(s) or saves.SlotHead(s, SlotStatus.EMPTY, None, None, None, None, "")
             for s in saves.page_slots("quick")]
    assert saves.newest(quick) == SlotId("quick", 4)
    assert saves.next_seq(heads.values()) == saves.next_seq(clean.values()) == 10


def test_exactly_the_cap_does_not_fall_back(tmp_path, p8, monkeypatch):
    folder = tmp_path / "saves"
    fill(folder, p8, [SlotId("quick", 1)])
    monkeypatch.setattr(limits, "INDEX_MAX_EXAMINED", 3)
    monkeypatch.setattr(saves.os, "scandir",
                        lambda p: _Listing(["a.txt", "b.txt", "quick-1.vnsave"]))
    job = IndexJob(folder, game_id=ss.GAME_ID, pages=10)
    assert list(job.finish()) == [SlotId("quick", 1)] and not job.fell_back


# --- AC-F20-54: F11's scans fit the shared folder (F20 04 §18 A13; 07 I-4) --------------------

class _NodesFirst:
    """A real listing of the folder with ``node-…`` entries first (the worst order)."""

    def __init__(self, path, real) -> None:
        with real(path) as entries:
            self.entries = sorted(entries, key=lambda e: (not e.name.startswith("node-"),
                                                          e.name))

    def __enter__(self):
        return iter(self.entries)

    def __exit__(self, *exc) -> None:
        return None


def _shared_folder(folder, p8: bytes, *, nodes: int, pages: int) -> str:
    """``nodes`` node files, every slot of ``pages`` pages, and a 2-minute-old slot temp."""
    import time
    from engine.core import safefile
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(nodes):
        (folder / f"node-{i:016x}.vnnode").write_bytes(b"n")
    fill(folder, p8, saves.all_slots(pages))
    temp = safefile.temp_name("quick-2.vnsave", "0123abcd")
    (folder / temp).write_bytes(b"t")
    old = time.time() - 120
    os.utime(folder / temp, (old, old))
    return temp


def _scans(folder, temp: str, pages: int, monkeypatch, *, step_cap: int) -> None:
    """F11's index (sliced at ``step_cap`` entries a step) doesn't fall back, and the saves
    root's stale-temp scan, at ``SAVE_TEMP_SCAN_MAX``, removes the slot temp listed last."""
    from engine.core import safefile
    real = os.scandir
    monkeypatch.setattr(os, "scandir", lambda p: _NodesFirst(p, real))
    monkeypatch.setattr(limits, "INDEX_STEP_EXAMINED", step_cap)
    job = IndexJob(folder, game_id=ss.GAME_ID, pages=pages)
    listed, last = [], 0
    while not job.step(0.0, lambda: 1.0):               # one listing slice a step
        listed.append(job.examined - last)
        last = job.examined
    assert not job.fell_back and max(listed) <= step_cap
    assert len(job.heads) == 12 + 6 * pages
    # The install's stale scan of the saves root (app/saves.py passes SAVE_TEMP_SCAN_MAX).
    removed = safefile.remove_stale_temps(folder, target_pattern=saves.SLOT_NAME_RE,
                                          max_age_s=limits.TEMP_STALE_S,
                                          max_examined=limits.SAVE_TEMP_SCAN_MAX,
                                          max_removed=limits.TEMP_CLEANUP_MAX)
    assert removed == 1 and not (folder / temp).exists()


def test_ac_f20_54_f11s_scans_fit_the_shared_folder(tmp_path, p8, monkeypatch):
    """300 node files listed before the slots, the caps patched in proportion (6,000 ×
    300 / 4,000 = 450); the old caps (2,000 and 1,000, also in proportion) would fail."""
    assert limits.INDEX_MAX_EXAMINED == 6_000 and limits.SAVE_TEMP_SCAN_MAX == 6_000
    assert limits.TEMP_SCAN_MAX == 1_000                # other folders keep the shared cap
    folder = tmp_path / "saves"
    temp = _shared_folder(folder, p8, nodes=300, pages=10)
    with monkeypatch.context() as m:                    # the old caps: the index falls back
        m.setattr(limits, "INDEX_MAX_EXAMINED", 2_000 * 300 // 4_000)
        real = os.scandir
        m.setattr(os, "scandir", lambda p: _NodesFirst(p, real))
        old = IndexJob(folder, game_id=ss.GAME_ID, pages=10)
        old.finish()
        assert old.fell_back
    monkeypatch.setattr(limits, "INDEX_MAX_EXAMINED", 6_000 * 300 // 4_000)
    monkeypatch.setattr(limits, "SAVE_TEMP_SCAN_MAX", 6_000 * 300 // 4_000)
    _scans(folder, temp, 10, monkeypatch, step_cap=100)


@pytest.mark.slow
def test_ac_f20_54_real_caps_with_4000_node_files(tmp_path, p8, monkeypatch):
    folder = tmp_path / "saves"
    temp = _shared_folder(folder, p8, nodes=4_000, pages=100)
    _scans(folder, temp, 100, monkeypatch, step_cap=limits.INDEX_STEP_EXAMINED)


@pytest.mark.perf
def test_ac_f20_54_index_listing_step_fits_save_step_s(tmp_path, p8):
    """07 I-4's perf row (reference machine): with 4,612 entries, each ``IndexJob`` listing
    step (≤ ``INDEX_STEP_EXAMINED`` entries) takes ≤ ``SAVE_STEP_S``."""
    import time
    folder = tmp_path / "saves"
    _shared_folder(folder, p8, nodes=4_000, pages=100)
    worst = 0.0
    for _ in range(5):
        job = IndexJob(folder, game_id=ss.GAME_ID, pages=100)
        while job._todo is None:
            start = time.perf_counter()
            job.step(0.0, lambda: 1.0)
            worst = max(worst, time.perf_counter() - start)
        job.close()
    assert worst <= limits.SAVE_STEP_S, worst
