"""The byte-budgeted LRU cache.

AC-F01-107 (LRU eviction, holds, over-budget warning, on_evict).
"""

import logging

import pytest

from engine.core.lru import SizedLru


@pytest.fixture
def evicted():
    return []


@pytest.fixture
def cache(evicted) -> SizedLru:
    return SizedLru(100, protect_frames=2, on_evict=lambda key, value: evicted.append(key))


def _over_budget_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records
            if r.levelno == logging.WARNING and "over its" in r.getMessage()]


def test_ac_107_sequence(cache, evicted, caplog):
    with caplog.at_level(logging.WARNING, logger="vn"):
        cache.put("a", "A", 40, frame=1)
        cache.put("b", "B", 40, frame=2)
        cache.put("c", "C", 40, frame=10)
        assert "a" not in cache and "b" in cache and "c" in cache
        assert cache.total_cost == 80
        assert evicted == ["a"]

        cache.hold("b")
        cache.put("d", "D", 40, frame=11)
        assert evicted == ["a"]                       # nothing evicted
        assert cache.over_budget is True
        assert len(_over_budget_warnings(caplog)) == 1
        assert _over_budget_warnings(caplog)[0].name == "vn.assets"

        cache.put("e", "E", 10, frame=20)
        assert evicted == ["a", "c"]
        assert cache.total_cost == 90
        assert cache.over_budget is False

        # A second over-budget event in the same session logs no second warning.
        cache.put("f", "F", 200, frame=21)
        assert cache.over_budget is True
        assert len(_over_budget_warnings(caplog)) == 1


def test_release_below_zero_is_an_assertion(cache):
    cache.hold("x")
    cache.release("x")
    with pytest.raises(AssertionError):
        cache.release("x")


def test_held_entry_becomes_evictable_after_release(cache, evicted):
    cache.put("a", 1, 60, frame=1)
    cache.hold("a")
    cache.hold("a")
    cache.put("b", 2, 60, frame=10)
    assert "a" in cache
    cache.release("a")
    cache.put("c", 3, 1, frame=11)
    assert "a" in cache                               # still held once
    cache.release("a")
    cache.put("d", 4, 1, frame=12)
    assert "a" not in cache and evicted == ["a"]


def test_get_marks_recent_use_and_protects(cache, evicted):
    cache.put("a", 1, 50, frame=1)
    cache.put("b", 2, 50, frame=2)
    assert cache.get("a", frame=9) == 1              # a used at frame 9
    cache.put("c", 3, 50, frame=10)
    assert evicted == ["b"]                           # b is now the LRU and unprotected
    assert cache.get("missing", frame=10) is None


def test_put_replaces_and_reports_the_old_value(evicted):
    values = []
    cache = SizedLru(100, on_evict=lambda key, value: values.append((key, value)))
    cache.put("a", "old", 30, frame=1)
    cache.put("a", "new", 50, frame=2)
    assert cache.total_cost == 50
    assert cache.get("a", frame=2) == "new"
    assert values == [("a", "old")]


def test_discard_calls_on_evict(cache, evicted):
    cache.put("a", 1, 10, frame=1)
    cache.discard("a")
    cache.discard("a")                                # absent: nothing happens
    assert evicted == ["a"] and cache.total_cost == 0 and len(cache) == 0


def test_hold_before_put_protects_the_entry(cache, evicted):
    cache.hold("font")
    cache.put("font", "F", 90, frame=1)
    cache.put("img", "I", 90, frame=10)
    assert "font" in cache and evicted == []


def test_warning_names_the_budget_in_mb(caplog):
    cache = SizedLru(64 * 1_048_576)
    with caplog.at_level(logging.WARNING, logger="vn"):
        cache.put("big", 1, 65 * 1_048_576, frame=1)
    assert [r.getMessage() for r in caplog.records] == [
        "Asset cache is over its 64 MB limit because all cached assets are in use"]
