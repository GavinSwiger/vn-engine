"""F46's Studio budgets, the scene index's rows (``06-acceptance.md`` AC-F46-46; ``04``
§6.1, §10): ``follow`` after editing one scene of an 800 KB file ≤ 30 ms, of a 16 MB file
≤ 250 ms, median of 5. ``follow`` here is the pure part: the Tk ``get`` is left out (step 1b
times it with the window). Later steps add AC-46's other rows to this file.

    set VN_PERF=1
    .venv/Scripts/python -m pytest tests/perf/test_story_editor_perf.py -m perf -s -v
"""

import statistics
import time

import pytest

import engine.script  # noqa: F401  registers every statement
from engine.tools.editor.scenes import reindex
from tests.perf.gen_story_bench import KB, MB, story

REF = "script/main.vns"


def _follow_ms(size: int) -> tuple[float, int]:
    text = story(size)
    base = reindex(None, REF, text, 0, checked=None)       # I-1: the open baseline
    marker = '    "The festival went on, line 1, and the river ran past."'
    at = text.index(marker, len(text) // 2)
    times, parsed = [], 0
    for n in range(5):
        edited = text[:at] + marker.replace("line 1", f"line {n + 100}") \
            + text[at + len(marker):]
        start = time.perf_counter()
        index = reindex(base, REF, edited, n + 1, checked=base.checked)
        times.append((time.perf_counter() - start) * 1000)
        parsed = len(index.reads)
    return statistics.median(times), parsed


@pytest.mark.perf
@pytest.mark.parametrize(("size", "budget_ms"), [(800 * KB, 30.0), (16 * MB, 250.0)],
                         ids=["800KB", "16MB"])
def test_ac_f46_46_follow_one_edited_scene(size, budget_ms):
    median, parsed = _follow_ms(size)
    print(f"\nfollow, {size // KB} KB, one scene edited: median {median:.1f} ms "
          f"(budget {budget_ms:.0f} ms)")
    assert parsed == 1                                       # only the edited chunk
    assert median <= budget_ms
