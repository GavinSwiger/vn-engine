"""AC-F11-62 — CI guard: loads at the bounds (SEC-F11-06; invariant 10).

The read bounds equal ``04`` §13, so raising one fails here until AC-F11-64 is re-run on the
reference machine. Default tier: each of ``04`` §11's nine hostile shapes at 1/8 of both
bounds loads in ≤ 0.5 s with a ``tracemalloc`` peak ≤ 40 MiB. ``slow``: at the full bounds,
each ≤ 2 s with a traced peak ≤ 200 MiB (process-wide peak growth, AC-F11-64, is the ``perf``
test's)."""

import gc
import time
import tracemalloc

import pytest

from engine.persist import limits, saves
from engine.persist.saves import SlotStatus
from tests.persist import gen_hostile_saves
from tests.persist import save_support as ss

MIB = 1 << 20


def test_the_bounds_equal_the_design():
    assert limits.STATE_MAX_BYTES == 25_165_824 == 24 * MIB
    assert limits.SAVE_PRESCAN_MAX == 1_000_000
    assert limits.HEAD_MAX == 139_276 == limits.META_MAX + limits.THUMB_LINE_MAX
    assert limits.SAVE_FILE_MAX == 25_305_100 == (limits.META_MAX + limits.THUMB_LINE_MAX
                                                  + limits.STATE_MAX_BYTES)
    assert limits.THUMB_MAX_BYTES == 98_304
    assert limits.META_MAX == 8_192
    assert limits.THUMB_LINE_MAX == len(b'{"jpeg":""}\n') + 4 * limits.THUMB_MAX_BYTES // 3
    assert (limits.SEQ_MAX, limits.SAVED_AT_MAX) == (2**53, 253_402_300_799)
    assert (limits.DESCRIPTION_MAX, limits.VERSION_MAX) == (200, 64)
    # F20 A13 (AC-F20-54): the index and the saves root's stale-temp scan look at 6,000.
    assert (limits.SAVE_FORMAT, limits.SLOTS_PER_PAGE, limits.INDEX_MAX_EXAMINED) == (1, 6, 6_000)
    assert (limits.INDEX_STEP_EXAMINED, limits.SAVE_TEMP_SCAN_MAX) == (1_000, 6_000)
    assert (limits.SAVE_STEP_S, limits.MAX_REQUESTS) == (0.004, 64)


def _load(folder) -> tuple[saves.FullRead, float]:
    start = time.perf_counter()
    result = ss.full(folder)
    return result, time.perf_counter() - start


def _traced_peak(folder) -> int:
    gc.collect()
    tracemalloc.start()
    try:
        ss.full(folder)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _check_shape(shape: str, tmp_path, *, scale: int, max_s: float, max_peak: int) -> None:
    data = gen_hostile_saves.shape_save(shape, max_bytes=limits.STATE_MAX_BYTES // scale,
                                        max_structure=limits.SAVE_PRESCAN_MAX // scale)
    folder = tmp_path / "saves"
    ss.write_slot(folder, data)
    del data
    result, seconds = _load(folder)
    assert result.status in (SlotStatus.OK, SlotStatus.DAMAGED), result
    del result
    peak = _traced_peak(folder)
    print(f"{shape} 1/{scale}: {seconds * 1000:.0f} ms, traced peak {peak / MIB:.1f} MiB")
    assert seconds <= max_s
    assert peak <= max_peak


@pytest.mark.parametrize("shape", gen_hostile_saves.SHAPES)
def test_each_shape_at_an_eighth_of_the_bounds(shape, tmp_path):
    _check_shape(shape, tmp_path, scale=8, max_s=0.5, max_peak=40 * MIB)


@pytest.mark.slow
@pytest.mark.parametrize("shape", gen_hostile_saves.SHAPES)
def test_each_shape_at_the_full_bounds(shape, tmp_path):
    _check_shape(shape, tmp_path, scale=1, max_s=2.0, max_peak=200 * MIB)


@pytest.mark.parametrize("shape", gen_hostile_saves.SHAPES)
def test_shapes_fill_to_the_first_bound(shape):
    """The generator lands each shape on its byte cap or its pre-scan bound."""
    line = gen_hostile_saves.shape_line(shape, max_bytes=MIB, max_structure=20_000)
    near_bytes = len(line) + 1 > MIB - 4_400
    near_structure = saves.count_structure(line) > 20_000 - 3
    assert near_bytes or near_structure
