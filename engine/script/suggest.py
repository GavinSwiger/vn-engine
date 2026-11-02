"""Did-you-mean for names written in scripts (SR-F02-70).

The one suggestion mechanism for script names (labels, characters, statement words, later
script names); file references use ``GamePaths``' suggestion instead (07 §2.4).

Rule: a case-insensitive match wins; else the closest candidate by optimal-string-alignment
distance, if that distance is at most 1 (written name of 1–4 characters) or 2 (5 or more);
ties go to the smallest candidate by code point. Written and candidate names over
``SCRIPT_SUGGEST_MAX_NAME`` characters are skipped (SEC-F02-05). The distance is banded and
stops early, so the cost per candidate is O(len × k).

Many candidates (F04 step 9: the launch image check's W12 over up to 20,000 image names)
are walked in sorted order as a trie: names sharing a prefix share its table rows, and a
prefix already too far rules out every name starting with it at once, so 10,000 names under
a few folders cost a handful of rows, not 10,000 distances. Only a filter: each name left is
still measured with ``osa_distance``. Names close to the written one can still leave
thousands of rows, so ``SuggestPool.iter_suggest`` pauses every ``SUGGEST_STEP_WORK`` rows
and distances (a loading screen spreads them over frames); the answer is ``suggest``'s.
"""

from bisect import bisect_left
from collections.abc import Generator, Iterable

from engine.script.limits import IDENTITY_YIELD_ITEMS, SCRIPT_SUGGEST_MAX_NAME

SUGGEST_STEP_WORK = 250         # table rows and distances between pauses (about 1 ms)


def max_distance(written: str) -> int:
    """The largest distance a suggestion may have for ``written``."""
    return 1 if len(written) <= 4 else 2


def osa_distance(a: str, b: str, limit: int) -> int:
    """Optimal-string-alignment distance between ``a`` and ``b``, or ``limit + 1`` as soon
    as it is known to exceed ``limit``. Iterative, banded to ``limit`` around the diagonal."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    if a == b:
        return 0
    over = limit + 1
    n, m = len(a), len(b)
    prev2: list[int] | None = None
    prev = [j if j <= limit else over for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [over] * (m + 1)
        if i <= limit:
            cur[0] = i
        lo = max(1, i - limit)
        hi = min(m, i + limit)
        row_min = cur[0]
        ai = a[i - 1]
        for j in range(lo, hi + 1):
            cost = 0 if ai == b[j - 1] else 1
            value = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (prev2 is not None and i > 1 and j > 1 and ai == b[j - 2]
                    and a[i - 2] == b[j - 1]):
                value = min(value, prev2[j - 2] + 1)
            if value > over:
                value = over
            cur[j] = value
            if value < row_min:
                row_min = value
        if row_min > limit:
            return over
        prev2, prev = prev, cur
    return min(prev[m], over)


def _osa_row(rows: list[list[int]], name: str, i: int, written: str, limit: int) -> list[int]:
    """Row ``i`` of the banded OSA table of ``name`` (rows) against ``written`` (columns):
    the distance from ``name[:i]`` to each prefix of ``written``, capped at ``limit + 1``.
    ``rows`` holds rows ``0 … i - 1``, so ``osa_distance`` with its arguments swapped."""
    over = limit + 1
    m = len(written)
    prev = rows[i - 1]
    prev2 = rows[i - 2] if i > 1 else prev
    cur = [over] * (m + 1)
    if i <= limit:
        cur[0] = i
    bi = name[i - 1]
    before = name[i - 2] if i > 1 else ""
    for j in range(max(1, i - limit), min(m, i + limit) + 1):
        aj = written[j - 1]
        value = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if bi == aj else 1))
        if i > 1 and j > 1 and bi == written[j - 2] and before == aj:
            value = min(value, prev2[j - 2] + 1)
        cur[j] = value if value < over else over
    return cur


def _iter_closest(written: str, pool: list[str]) -> Generator[None, None, str | None]:
    """The rule's second half over the sorted, unique ``pool``: the nearest name other than
    ``written`` within ``max_distance``, the smallest on a tie; pauses (yields) after each
    ``SUGGEST_STEP_WORK`` rows and distances.

    The walk: once a row of a prefix is all over the limit, so is every later row (a
    transposition reaches back two rows, but the row between is then at most one more), so
    no name starting with that prefix can be within it and the walk skips them all."""
    limit = max_distance(written)
    best: str | None = None
    best_distance = limit + 1
    rows = [[j if j <= limit else limit + 1 for j in range(len(written) + 1)]]
    have = ""                                   # the prefix rows[1:] are for
    at, end, work = 0, len(pool), 0
    while at < end:
        if work >= SUGGEST_STEP_WORK:
            work = 0
            yield
        name = pool[at]
        keep = 0
        top = min(len(have), len(name))
        while keep < top and have[keep] == name[keep]:
            keep += 1
        del rows[keep + 1:]
        for i in range(keep + 1, len(name) + 1):
            row = _osa_row(rows, name, i, written, limit)
            rows.append(row)
            work += 1
            if min(row) > limit:
                have = name[:i]
                at = _past_prefix(pool, have, at)
                break
        else:
            have = name
            at += 1
            if name != written:
                work += 1
                distance = osa_distance(written, name, limit)
                if distance < best_distance:  # pool is sorted, so ties keep the smaller one
                    best, best_distance = name, distance
    return best


def _run(steps: Generator[None, None, str | None]) -> str | None:
    """A paused computation run to the end."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def _past_prefix(pool: list[str], prefix: str, at: int) -> int:
    """The index of the first name after ``pool[at]`` that doesn't start with ``prefix``
    (``pool`` is sorted and ``pool[at]`` starts with it)."""
    last = ord(prefix[-1])
    if last < 0x10FFFF:
        return bisect_left(pool, prefix[:-1] + chr(last + 1), at + 1)
    at += 1
    while at < len(pool) and pool[at].startswith(prefix):
        at += 1
    return at


def suggest(written: str, candidates: Iterable[str]) -> str | None:
    """The one suggestion for ``written`` among ``candidates`` (SR-F02-70), or None."""
    if len(written) > SCRIPT_SUGGEST_MAX_NAME:
        return None
    pool = sorted({c for c in candidates
                   if len(c) <= SCRIPT_SUGGEST_MAX_NAME and c != written})
    folded = written.casefold()
    for candidate in pool:
        if candidate.casefold() == folded:
            return candidate
    return _run(_iter_closest(written, pool))


class SuggestPool:
    """``suggest`` against one set of candidates asked many times, in steps: the first
    ``iter_suggest`` sorts the names (one C sort, a step of its own), then deduplicates and
    case-folds them ``IDENTITY_YIELD_ITEMS`` per step; later ones only walk."""

    __slots__ = ("_candidates", "_pool", "_folded")

    def __init__(self, candidates: Iterable[str]) -> None:
        self._candidates: Iterable[str] | None = candidates
        self._pool: list[str] = []
        self._folded: dict[str, list[str]] = {}          # casefold → names, smallest first

    def _iter_prepare(self) -> Generator[None, None, None]:
        candidates, self._candidates = self._candidates, None
        assert candidates is not None
        names = sorted(candidates)
        if len(names) > IDENTITY_YIELD_ITEMS:
            yield
        pool, folded = self._pool, self._folded
        for count, name in enumerate(names, 1):
            if len(name) <= SCRIPT_SUGGEST_MAX_NAME and (not pool or pool[-1] != name):
                pool.append(name)
                folded.setdefault(name.casefold(), []).append(name)
            if count % IDENTITY_YIELD_ITEMS == 0:
                yield

    def iter_suggest(self, written: str) -> Generator[None, None, str | None]:
        """``suggest(written, candidates)`` as its return value, pausing (yielding) between
        bounded pieces of work. Don't start a second one before this one has ended."""
        if self._candidates is not None:
            yield from self._iter_prepare()
        if len(written) > SCRIPT_SUGGEST_MAX_NAME:
            return None
        for candidate in self._folded.get(written.casefold(), ()):
            if candidate != written:
                return candidate
        return (yield from _iter_closest(written, self._pool))

    def suggest(self, written: str) -> str | None:
        """``suggest(written, candidates)`` in one go."""
        return _run(self.iter_suggest(written))
