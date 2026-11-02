"""Story load time and memory (F02 checklist step 11; ``04-technical.md`` §10, §14):
AC-F02-69, AC-F02-70 (``perf``), and AC-F02-71 (every run; 1,000,000 words ``slow``).

The ``perf`` rows are for the ADR-0005 reference machine (Intel Core i5-8250U) or a stand-in
with a PassMark single-thread score of at most 2,000, never CI. Each measures the load time
of 06 §0.5: ``load_story()`` alone in a fresh process after imports, files already written,
the median of 5 processes after 1 discarded run (``tests/script/load_process.py``). Run::

    set VN_PERF=1
    .venv/Scripts/python -m pytest tests/perf/test_script_load.py tests/script/test_abuse.py -m perf -s

and attach the printed lines (CPU, times, peak memory) and the machine's PassMark
single-thread score to the test report (06 §0.3). AC-F02-64 (a long load is never "Not
Responding") is the manual step that goes with these: copy the ``--words 1000000 --files 100
--seed 1`` corpus's ``script/`` into ``game/script/`` and follow 06-acceptance.md AC-F02-64.
"""

import gc
import tracemalloc

import pytest

from engine.core.paths import GamePaths
from engine.script import StoryLoader
from tests.script.load_process import cpu_name, measure

MIB = 1 << 20
C50K = ("--words", "50000", "--files", "10", "--seed", "1")
C500K = ("--words", "500000", "--files", "50", "--seed", "1")
C1M = ("--words", "1000000", "--files", "100", "--seed", "1")


def _report(name: str, median: float, runs: list[dict]) -> None:
    times = ", ".join(f"{r['seconds']:.3f}" for r in runs)
    peak = max(r["peak_bytes"] for r in runs) / MIB
    print(f"\n{name} on {cpu_name()}: median {median:.3f} s ({times}); peak {peak:.0f} MiB")


def _clean(runs: list[dict], words: int) -> None:
    for run in runs:
        assert run["loaded"] and run["error_codes"] == [] and run["warning_codes"] == []
        assert run["words"] == words
        assert "Traceback" not in run["stderr"]


# --- AC-F02-69, AC-F02-70 (perf) ----------------------------------------------------------

@pytest.mark.perf
def test_ac69_fifty_thousand_words_in_half_a_second(corpus):
    median, runs = measure(corpus(*C50K))
    _report("AC-F02-69 50,000 words", median, runs)
    _clean(runs, 50_000)
    assert median <= 0.50


@pytest.mark.perf
def test_ac70_one_million_words_in_five_seconds_and_linear(corpus):
    half, half_runs = measure(corpus(*C500K))
    full, full_runs = measure(corpus(*C1M))
    _report("AC-F02-70 500,000 words", half, half_runs)
    _report("AC-F02-70 1,000,000 words", full, full_runs)
    print(f"ratio {full / half:.2f}")
    _clean(half_runs, 500_000)
    _clean(full_runs, 1_000_000)
    assert full <= 5.0
    assert full <= 2.2 * half


# --- AC-F02-71: retained memory -----------------------------------------------------------

def _retained(paths: GamePaths) -> tuple[int, object]:
    """The memory a load leaves behind (06 AC-F02-71): ``gc.collect()``, then the traced
    size before ``load_story`` and after it, with the result kept and the loader released."""
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        loader = StoryLoader(paths)
        while not loader.step(float("inf")):
            pass
        result = loader.result
        del loader
        gc.collect()
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    return after - before, result


def test_ac71_fifty_thousand_words_retain_at_most_8_mib(corpus):
    retained, result = _retained(GamePaths(corpus(*C50K).resolve()))
    assert result.program is not None and result.program.stats.words == 50_000
    assert retained <= 8 * MIB, retained / MIB


@pytest.mark.slow
def test_ac71_one_million_words_retain_at_most_100_mib(corpus):
    retained, result = _retained(GamePaths(corpus(*C1M).resolve()))
    assert result.program is not None and result.program.stats.words == 1_000_000
    print(f"\nAC-F02-71 1,000,000 words: {retained / MIB:.1f} MiB retained")
    assert retained <= 100 * MIB, retained / MIB
