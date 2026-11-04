"""CI-safe proxies for F58's perf gates (``04-technical.md`` §11, §16 P0; PR-F58-19).

The perf tier (``tests/perf/test_live_map_perf.py``) times the real thing on a real display;
these stand-ins let unit tests check the same rules with no display and no wall clock.

- ``FakeClock``: a clock in milliseconds (``now()``, ``advance(ms)``) with Tk's ``after`` /
  ``after_cancel`` shape. ``advance`` runs every timer that falls due, in due order (ties in
  the order they were set), moving ``now`` to each one's time first, so a timer set from a
  timer runs in the same ``advance`` when it falls due inside it.
- ``count_calls(monkeypatch, owner, name)``: wraps ``owner.name`` so every call is counted
  (``Counted.n``) and its arguments kept (``Counted.args``); the original still runs. Used
  for ``scenes.parse_chunk`` (AC-F58-08), ``storymap.chip_slot`` (AC-F58-16), the watch's
  reader (AC-F58-06).
"""

import heapq
import itertools
from collections.abc import Callable


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)
        self._timers: list[tuple[float, int, str]] = []
        self._calls: dict[str, Callable[[], object]] = {}
        self._seq = itertools.count()

    def now(self) -> float:
        return self._now

    __call__ = now

    def after(self, ms: float, func: Callable[[], object]) -> str:
        seq = next(self._seq)
        token = f"after#{seq}"
        self._calls[token] = func
        heapq.heappush(self._timers, (self._now + max(0.0, ms), seq, token))
        return token

    def after_cancel(self, token: str) -> None:
        self._calls.pop(token, None)

    @property
    def pending(self) -> int:
        return len(self._calls)

    def advance(self, ms: float) -> None:
        end = self._now + ms
        while self._timers and self._timers[0][0] <= end:
            due, _seq, token = heapq.heappop(self._timers)
            func = self._calls.pop(token, None)
            if func is None:
                continue
            self._now = max(self._now, due)
            func()
        self._now = end


class Counted:
    def __init__(self, func: Callable) -> None:
        self.func = func
        self.n = 0
        self.args: list[tuple] = []

    def __call__(self, *args, **kwargs):
        self.n += 1
        self.args.append(args)
        return self.func(*args, **kwargs)


def count_calls(monkeypatch, owner, name: str) -> Counted:
    counted = Counted(getattr(owner, name))
    monkeypatch.setattr(owner, name, counted)
    return counted


__all__ = ["Counted", "FakeClock", "count_calls"]
