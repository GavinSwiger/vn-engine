"""AC-F02-46: did-you-mean (SR-F02-70, SEC-F02-05), driven by ``suggest.csv``; and F04 step 9:
the pruned walk and ``SuggestPool`` give the same suggestion as measuring every candidate,
with bounded work per pause."""

import csv
import random
import time

import pytest

from engine.script import suggest as suggest_mod
from engine.script.limits import IDENTITY_YIELD_ITEMS, SCRIPT_SUGGEST_MAX_NAME
from engine.script.suggest import (SUGGEST_STEP_WORK, SuggestPool, max_distance, osa_distance,
                                   suggest)
from tests.script.helpers import FIXTURES


def _rows():
    with (FIXTURES / "suggest.csv").open(encoding="utf-8", newline="") as handle:
        return [(row["written"], row["candidates"].split("|"), row["suggestion"] or None)
                for row in csv.DictReader(handle)]


@pytest.mark.parametrize("written,candidates,expected", _rows(),
                         ids=lambda v: v[:12] if isinstance(v, str) else None)
def test_suggest_csv(written, candidates, expected):
    assert suggest(written, candidates) == expected


def test_csv_has_every_ac_row():
    assert len(_rows()) == 14


@pytest.mark.parametrize("a,b,distance", [
    ("jmup", "jump", 1), ("abc", "abc", 0), ("abc", "abd", 1), ("ab", "xy", 2),
    ("abcde", "abxye", 2), ("ca", "abc", 3), ("", "ab", 2), ("kitten", "sitting", 3),
])
def test_osa_distance(a, b, distance):
    assert osa_distance(a, b, 5) == distance


def test_osa_distance_stops_past_the_limit():
    assert osa_distance("aaaaaaaa", "bbbbbbbb", 2) == 3
    assert osa_distance("a", "abcdef", 2) == 3


def test_written_name_is_not_its_own_suggestion():
    assert suggest("start", ["start", "stark"]) == "stark"


def test_many_candidates_are_fast():
    candidates = [f"label_{i}" for i in range(20_000)]
    start = time.perf_counter()
    assert suggest("label_19999x", candidates) == "label_19999"
    assert time.perf_counter() - start < 1.0


# --- F04 step 9: many candidates (the pruned walk and SuggestPool) -----------------------------

def _exhaustive(written, candidates):
    """The rule as first written: every candidate measured (the reference)."""
    if len(written) > SCRIPT_SUGGEST_MAX_NAME:
        return None
    pool = sorted({c for c in candidates if len(c) <= SCRIPT_SUGGEST_MAX_NAME and c != written})
    for candidate in pool:
        if candidate.casefold() == written.casefold():
            return candidate
    limit = max_distance(written)
    best, best_distance = None, limit + 1
    for candidate in pool:
        distance = osa_distance(written, candidate, limit)
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best


def _mutated(rng, text, letters):
    chars = list(text)
    for _ in range(rng.randint(0, 3)):
        op = rng.randrange(4)
        if op == 0 and chars:
            chars[rng.randrange(len(chars))] = rng.choice(letters)
        elif op == 1:
            chars.insert(rng.randint(0, len(chars)), rng.choice(letters))
        elif op == 2 and chars:
            del chars[rng.randrange(len(chars))]
        elif op == 3 and len(chars) > 1:
            i = rng.randrange(len(chars) - 1)
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


@pytest.mark.parametrize("count", [500, pytest.param(3_000, marks=pytest.mark.slow)])
@pytest.mark.parametrize("letters", ["ab", "abc d", "aAbBßé_\U0010ffff"])
def test_the_walk_and_the_pool_give_the_exhaustive_suggestion(letters, count):
    """Random names against the exhaustive search: 500 per alphabet by default, 3,000 in
    ``slow`` (test-review-F03.md; the same seed, so the default cases are the first 500)."""
    rng = random.Random(letters)
    for _ in range(count):
        written = "".join(rng.choice(letters) for _ in range(rng.randrange(0, 10)))
        candidates = [_mutated(rng, written, letters) if rng.random() < 0.5
                      else "".join(rng.choice(letters) for _ in range(rng.randrange(0, 11)))
                      for _ in range(rng.randrange(0, 30))]
        expected = _exhaustive(written, candidates)
        assert suggest(written, candidates) == expected, (written, candidates)
        assert SuggestPool(candidates).suggest(written) == expected, (written, candidates)


def test_the_walk_skips_past_the_last_code_point():
    top = "\U0010ffff"
    names = [f"a{top}{top}x", f"a{top}{top}y", "b"]
    assert suggest(f"a{top}{top}zz", names) == _exhaustive(f"a{top}{top}zz", names)
    assert suggest("bxyz", names + ["bxy"]) == "bxy"


def test_a_pool_answers_many_questions_like_suggest():
    names = [f"set{f:02} pic{i:02}" for f in range(30) for i in range(30)] + ["Hana Happy"]
    pool = SuggestPool(names)
    for written in ["hana happy", "Hana Happy", "set0 pic00", "set05 pic1x", "x" * 101, ""]:
        assert pool.suggest(written) == suggest(written, names) == _exhaustive(written, names)


IMAGE_NAMES = [f"set{f:02} pic{i:02}" for f in range(100) for i in range(100)]   # the bench's


def _count_work(monkeypatch):
    """Counts the distances and the walk's table rows (one unit of work each)."""
    counts = {"distances": 0, "rows": 0}
    distance, row = suggest_mod.osa_distance, suggest_mod._osa_row

    def counted_distance(*args):
        counts["distances"] += 1
        return distance(*args)

    def counted_row(*args):
        counts["rows"] += 1
        return row(*args)

    monkeypatch.setattr(suggest_mod, "osa_distance", counted_distance)
    monkeypatch.setattr(suggest_mod, "_osa_row", counted_row)
    return counts


def test_ten_thousand_names_under_folders_cost_a_few_rows(monkeypatch):
    """F04 step 9: the bench's 10,000 image names took 10,000 distances for one W12."""
    counts = _count_work(monkeypatch)
    assert suggest("hana happy", IMAGE_NAMES) is None
    assert counts == {"distances": 0, "rows": 3}                   # "s", "se", "set": out
    counts.update(distances=0, rows=0)
    assert suggest("set0 pic00", IMAGE_NAMES) == "set00 pic00"
    assert counts["distances"] < 1_000 and counts["rows"] < 5_000


@pytest.mark.parametrize("written, expected", [
    ("hana happy", None), ("set0 pic00", "set00 pic00"), ("set05 pic1x", "set05 pic10")])
def test_iter_suggest_pauses_after_bounded_work(monkeypatch, written, expected):
    pool = SuggestPool(frozenset(IMAGE_NAMES))
    counts = _count_work(monkeypatch)
    steps = pool.iter_suggest(written)
    per_step = []
    while True:
        before = counts["distances"] + counts["rows"]
        try:
            next(steps)
        except StopIteration as stop:
            result = stop.value
            break
        finally:
            per_step.append(counts["distances"] + counts["rows"] - before)
    assert result == expected
    # One name's rows (at most its length) and its distance can follow the last check.
    assert max(per_step) <= SUGGEST_STEP_WORK + SCRIPT_SUGGEST_MAX_NAME + 1
    # The sort, then IDENTITY_YIELD_ITEMS names folded per step: no walk work in those.
    assert per_step[:1 + len(IMAGE_NAMES) // IDENTITY_YIELD_ITEMS] == [0] * 6
    assert pool.suggest(written) == expected                        # later: no preparing


def test_a_small_pool_does_not_pause():
    steps = SuggestPool(["start", "stark"]).iter_suggest("strat")
    with pytest.raises(StopIteration) as stop:
        next(steps)
    assert stop.value.value == "start"
