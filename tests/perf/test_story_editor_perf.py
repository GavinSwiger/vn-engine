"""F46's Studio budgets, the scene index's rows (``06-acceptance.md`` AC-F46-46; ``04``
§6.1, §10): ``follow`` after editing one scene of an 800 KB file ≤ 30 ms, of a 16 MB file
≤ 250 ms, median of 5. ``follow`` here is the pure part: the Tk ``get`` is left out (step 1b
times it with the window). Step 6 adds the other rows: rows for a 2,000-statement scene,
plan + verify + apply, rename across 20 files, and one drag step among 1,500 boxes.

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


# --- Step 6: AC-F46-46's other rows ------------------------------------------------------------

def _median_ms(run, times: int = 5) -> float:
    found = []
    for _ in range(times):
        start = time.perf_counter()
        run()
        found.append((time.perf_counter() - start) * 1000)
    return statistics.median(found)


@pytest.mark.perf
def test_ac_f46_46_rows_for_a_2000_statement_scene():
    from engine.tools.editor import forms
    from engine.tools.editor.scenes import parse_chunk
    lines = ["label big:"] + [f'    "Line {k} of the long scene."' for k in range(1999)] \
        + ["    return"]
    chunk = "\n".join(lines)

    read = parse_chunk(REF, chunk)          # follow's part (the scene index parses it)
    assert read is not None and read.error is None
    parse = _median_ms(lambda: parse_chunk(REF, chunk))

    def run() -> None:
        assert len(forms.rows(read, lines)) >= 2000
    median = _median_ms(run)
    print(f"\nrows and probe, 2,000-statement scene: median {median:.1f} ms (budget 200 ms;"
          f" its parse, follow's part: {parse:.1f} ms)")
    assert median <= 200


@pytest.mark.perf
def test_ac_f46_46_plan_verify_apply_on_a_200_line_scene():
    from engine.tools.editor import scriptedit
    from engine.tools.editor.scenes import parse_chunk
    lines = ["label big:"] + [f'    "Line {k} of the scene."' for k in range(198)] \
        + ["    jump other", "", "label other:", "    return"]
    text = "\n".join(lines)
    chunk = "\n".join(lines[:201]) + "\n"

    def run() -> None:
        read = parse_chunk(REF, chunk)
        plan = scriptedit.plan_retarget(read, lines, 1, "other", "big", "jump")
        assert isinstance(plan, scriptedit.Plan)
        assert scriptedit.verify(plan, {REF: text})
        scriptedit.apply_lines(lines, plan.files[0].edits)
    median = _median_ms(run)
    print(f"\nguard + plan + verify + apply, 200-line scene: median {median:.1f} ms "
          "(budget 50 ms)")
    assert median <= 50


@pytest.mark.perf
def test_ac_f46_46_rename_across_20_files():
    from engine.tools.editor import scriptedit
    texts = {}
    for f in range(20):
        body = story(50 * KB).replace("label start:", f"label start{f}:")
        texts[f"script/f{f}.vns"] = body + "\nlabel tail%d:\n    call s3\n" % f
    assert sum(len(t) for t in texts.values()) >= MB

    def run() -> None:
        hits = {ref: found for ref, text in texts.items()
                if (found := scriptedit.rename_hits(ref, text, "s3"))}
        lines = {ref: text.split("\n") for ref, text in texts.items()}
        plan = scriptedit.plan_rename(hits, "s3", "third", texts=lines, confirm=True)
        assert isinstance(plan, scriptedit.Plan) and len(plan.files) == 20
        assert scriptedit.verify(plan, {ref: texts[ref] for ref in hits})
    median = _median_ms(run)
    print(f"\nrename, 20 files / 1 MB: median {median:.1f} ms (budget 1,000 ms)")
    assert median <= 1000


@pytest.mark.perf
@pytest.mark.tk
def test_ac_f46_46_one_drag_step_at_1500_boxes():
    import tkinter as tk

    from engine.script.labelgraph import LabelLink
    from engine.tools.editor.checker import NameEntry
    from engine.tools.editor.views import StoryMapView
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for Tk")
    try:
        root.geometry("1200x800")
        view = StoryMapView(root, background="#1e1e1e", family="Segoe UI", mod="Control",
                            on_open=lambda box: None)
        view.frame.pack(fill="both", expand=True)
        labels = [NameEntry(f"s{n}", REF, n + 1) for n in range(1500)]
        links = [LabelLink(f"s{n}", f"s{(n + 1) % 1500}", "jump", REF, n + 1)
                 for n in range(1500)]
        links += [LabelLink(f"s{n}", f"s{(n * 7) % 1500}", "menu", REF, n + 1, "Go on", False)
                  for n in range(0, 1500, 3)]
        view.set_data(labels, links, False)
        root.update()
        index = view.layout.index_of("s700")
        box = view.layout.boxes[index]
        steps = iter(range(1, 1000))

        def run() -> None:
            k = next(steps)
            view._show_at(index, (box.x + k * 3, box.y + k * 2))
            root.update_idletasks()
        median = _median_ms(run, 25)
    finally:
        root.destroy()
    print(f"\none drag step, 1,500 boxes: median {median:.2f} ms (budget 8 ms)")
    assert median <= 8
