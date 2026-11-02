"""A byte-budgeted LRU cache with frame-recency protection and holds.

Why this module exists: images, scaled variants, text lines, font files, and font objects
share one memory budget (``[engine] cache_mb``, PR-F01-59, ADR-0001), and an entry drawn
this frame or last must never be evicted mid-draw. F08 reuses the same cache, so it is a
small pure-Python building block in ``core``.
"""

import logging
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

from engine.core.constants import MB

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

_log = logging.getLogger("vn.assets")


class _Entry(Generic[V]):
    __slots__ = ("value", "cost", "frame")

    def __init__(self, value: V, cost: int, frame: int) -> None:
        self.value = value
        self.cost = cost
        self.frame = frame


class SizedLru(Generic[K, V]):
    """LRU cache whose entries have a cost in bytes and whose total cost is kept within
    ``budget_bytes`` where possible (§7.11.4).

    ``put`` evicts from the least-recently-used end, skipping held entries and entries used
    at ``>= frame - protect_frames``. If those protected entries alone exceed the budget,
    ``over_budget`` is True and one WARNING is logged per cache (one per session).
    """

    def __init__(self, budget_bytes: int, *, protect_frames: int = 2,
                 on_evict: Callable[[K, V], None] | None = None) -> None:
        self.budget_bytes = budget_bytes
        self.protect_frames = protect_frames
        self._on_evict = on_evict
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()   # oldest first
        self._holds: dict[K, int] = {}
        self._total = 0
        self._warned = False

    def get(self, key: K, frame: int) -> V | None:
        """The value, marked as used at ``frame``; None if absent."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        entry.frame = max(entry.frame, frame)
        self._entries.move_to_end(key)
        return entry.value

    def put(self, key: K, value: V, cost: int, frame: int) -> None:
        """Store ``value`` (replacing any entry under ``key``), then evict down to the
        budget. A replaced value is passed to ``on_evict`` like an evicted one."""
        old = self._entries.pop(key, None)
        if old is not None:
            self._total -= old.cost
            self._notify(key, old.value)
        self._entries[key] = _Entry(value, cost, frame)
        self._total += cost
        self._evict(frame)

    def hold(self, key: K) -> None:
        """Pin ``key`` (count +1); it is never evicted while its count is above 0. A key
        may be held before it is stored."""
        self._holds[key] = self._holds.get(key, 0) + 1

    def release(self, key: K) -> None:
        """Undo one ``hold``. Releasing more often than holding is a programming error."""
        count = self._holds.get(key, 0)
        assert count > 0, f"release() without hold() for {key!r}"
        if count == 1:
            del self._holds[key]
        else:
            self._holds[key] = count - 1

    def discard(self, key: K) -> None:
        """Remove ``key`` if present, calling ``on_evict``."""
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total -= entry.cost
            self._notify(key, entry.value)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def keys(self) -> list[K]:
        """The stored keys, least recently used first (for tests and the overlay)."""
        return list(self._entries)

    def cost(self, key: K) -> int | None:
        """The cost ``key`` was stored with; None if absent."""
        entry = self._entries.get(key)
        return None if entry is None else entry.cost

    @property
    def total_cost(self) -> int:
        return self._total

    @property
    def over_budget(self) -> bool:
        return self._total > self.budget_bytes

    def _evict(self, frame: int) -> None:
        if self._total <= self.budget_bytes:
            return
        protected_from = frame - self.protect_frames
        for key in list(self._entries):
            if self._total <= self.budget_bytes:
                break
            entry = self._entries[key]
            if self._holds.get(key, 0) > 0 or entry.frame >= protected_from:
                continue
            del self._entries[key]
            self._total -= entry.cost
            self._notify(key, entry.value)
        if self._total > self.budget_bytes and not self._warned:
            self._warned = True
            _log.warning("Asset cache is over its %s limit because all cached assets are "
                         "in use", _budget_text(self.budget_bytes))

    def _notify(self, key: K, value: V) -> None:
        if self._on_evict is not None:
            self._on_evict(key, value)


def _budget_text(budget: int) -> str:
    if budget >= MB and budget % MB == 0:
        return f"{budget // MB} MB"
    return f"{budget:,} bytes"
