"""F58 Live story map: the perf gates (``01-design.md`` PR-F58-19; AC-F58-11 to AC-F58-14;
``04-technical.md`` §11, §16 P0).

**``perf``** (a real display; ``VN_PERF=1``). From the project root, in PowerShell::

    $env:VN_PERF = "1"
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_live_map_perf.py

Every test runs at 300 and 1,000 scenes with one file holding every scene (the worst case,
``gen_map_bench``); AC-13 also with the scenes spread one per file. Each is ``xfail`` until
the step that makes it pass (W1, W2, W4). ``test_budget_table`` prints 04 §11's rows as
measured here (``python -m tests.perf.map_budget`` prints the same table on its own).

The CI-safe proxies of the same gates are unit tests: the fake clock (AC-10,
``tests/tools/editor/live_fakes.FakeClock``), counted ``chip_slot`` and ``parse_chunk`` (AC-16,
AC-08, ``live_fakes.count_calls``) and the counting canvas (AC-15,
``tests/tools/editor/canvas_counter.CountingCanvas``).
"""

import statistics
import time

import pytest

from engine.core import safefile
from tests.perf import gen_map_bench as gen

tk = pytest.importorskip("tkinter")

pytestmark = [pytest.mark.perf, pytest.mark.tk]

SIZES = (300, 1000)
REF = gen.MAIN
TYPING_MS = 150
THROTTLE_MS = 300
ACTION_MS = 150
OUTSIDE_MS = 500
ONE_SCENE_MS = {300: 16, 1000: 50}


def _root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk can't start here: {exc}")
    root.geometry("1400x900+0+0")
    return root


@pytest.fixture
def bench(tmp_path):
    """``bench(n, files=1) -> win``: Studio on a bench game with the map tab shown after one
    check result; closed afterwards."""
    from tests.perf.map_budget import drop_window, studio
    made = []

    def build(n: int, files: int = 1):
        root = _root()
        game = gen.write_game(tmp_path / f"g{n}_{files}", n, files)
        win = studio(root, game, n, files)
        win.select_tab("map")
        root.update()
        made.append((root, win))
        return win

    yield build
    for root, win in made:
        try:
            drop_window(root, win)
        except tk.TclError:
            pass


def edge_names(win) -> set[tuple[str, str, str]]:
    layout = win.story_map.layout
    if layout is None:
        return set()
    boxes = layout.boxes
    return {(boxes[e.src].name, boxes[e.dst].name, e.kind) for e in layout.edges}


def wait_for(win, test, limit: float, start: float | None = None) -> float | None:
    """Run Tk until ``test()`` holds; ms since ``start`` (default: now), or None past
    ``limit`` seconds."""
    start = time.perf_counter() if start is None else start
    while time.perf_counter() - start < limit:
        win.root.update()
        if test():
            return (time.perf_counter() - start) * 1000
        time.sleep(0.001)
    return None


def jump_line(n: int) -> int:
    """The line after scene ``n // 2``'s second dialogue line (a new line of that scene)."""
    return gen.SCENE_LINES * (n // 2) + 4


# --- AC-F58-11: typing ------------------------------------------------------------------------

@pytest.mark.parametrize("n", SIZES)
def test_ac_f58_11_typed_jump_and_throttle(bench, n):
    win = bench(n)
    record = win.record_for(REF)
    widget = record.widget
    src, dst = f"s{n // 2}", f"s{(n // 2 + 7) % n}"
    goal = (src, dst, "jump")
    assert goal not in edge_names(win)
    line = jump_line(n)
    widget.insert(f"{line}.0", f"    jump {dst}\n")
    waited = wait_for(win, lambda: goal in edge_names(win), 3)
    print(f"\nAC-F58-11 {n}: typed jump on the map {waited} ms after the pause")
    assert waited is not None and waited <= TYPING_MS

    # 3 s of typing at 10 keys/s: map updates (reindex runs) at most 300 ms apart.
    from engine.tools.editor import scenes
    starts: list[float] = []
    real = scenes.reindex

    def counted(*args, **kwargs):
        starts.append(time.perf_counter())
        return real(*args, **kwargs)

    scenes.reindex = counted
    try:
        begin = time.perf_counter()
        keys = 0
        while time.perf_counter() - begin < 3.0:
            due = begin + keys * 0.1
            while time.perf_counter() < due:
                win.root.update()
                time.sleep(0.001)
            widget.insert(f"{line}.end", "x")
            keys += 1
        end = time.perf_counter()
    finally:
        scenes.reindex = real
    stamps = [begin, *[s for s in starts if s <= end], end]
    gaps = [(b - a) * 1000 for a, b in zip(stamps, stamps[1:])]
    print(f"AC-F58-11 {n}: {len(starts)} updates in 3 s of typing, longest gap "
          f"{max(gaps):.0f} ms")
    assert max(gaps) <= THROTTLE_MS


# --- AC-F58-12: pane Apply and map undo ----------------------------------------------------------

@pytest.mark.parametrize("n", SIZES)
def test_ac_f58_12_apply_and_map_undo(bench, n):
    from engine.tools.editor.scriptedit import FilePlan, LineEdit, Plan
    win = bench(n)
    src, dst = f"s{n // 2}", f"s{(n // 2 + 7) % n}"
    goal = (src, dst, "jump")
    line = jump_line(n)
    plan = Plan("Bench", (FilePlan(REF, (), (LineEdit(line, line - 1, (f"    jump {dst}",)),)),))
    start = time.perf_counter()
    assert win.apply_plan(plan, lambda texts: True)
    win.map_plan_done(plan)
    applied = wait_for(win, lambda: goal in edge_names(win), 3, start)
    print(f"\nAC-F58-12 {n}: Apply on the map after {applied} ms")
    start = time.perf_counter()
    win.map_undo()
    undone = wait_for(win, lambda: goal not in edge_names(win), 3, start)
    print(f"AC-F58-12 {n}: map undo on the map after {undone} ms")
    assert applied is not None and applied <= ACTION_MS
    assert undone is not None and undone <= ACTION_MS


# --- AC-F58-13: an outside edit (MCP apply_edit) --------------------------------------------------

@pytest.mark.xfail(reason="F58 W4 (the background watch)", strict=False)
@pytest.mark.parametrize("files", (1, 0), ids=("one-file", "file-per-scene"))
@pytest.mark.parametrize("focused", (False, True), ids=("unfocused", "focused"))
@pytest.mark.parametrize("n", SIZES)
def test_ac_f58_13_outside_edit(bench, n, focused, files):
    files = files or n
    win = bench(n, files)
    if REF in win.files and files == 1:
        win._drop_record(REF)               # a closed file: the watch reads it
    ref, k = gen.file_of(n // 2, n, files)
    path = win.paths.root / ref
    src, dst = f"s{n // 2}", f"s{(n // 2 + 7) % n}"
    goal = (src, dst, "jump")
    lines = path.read_text("utf-8").split("\n")
    lines.insert(gen.SCENE_LINES * k + 3, f"    jump {dst}")
    if focused:
        win.root.focus_force()
    else:
        win.root.iconify()
        win.root.update()
        win.root.deiconify()
        win.root.lower()
    start = time.perf_counter()
    safefile.write_atomic(path, ["\n".join(lines).encode()])
    waited = wait_for(win, lambda: goal in edge_names(win), 3, start)
    print(f"\nAC-F58-13 {n} {'focused' if focused else 'unfocused'} files={files}: on the "
          f"map after {waited} ms")
    assert waited is not None and waited <= OUTSIDE_MS


# --- AC-F58-14: one-scene layout + draw --------------------------------------------------------

@pytest.mark.parametrize("n", SIZES)
def test_ac_f58_14_one_scene_layout_and_draw(n):
    from tests.perf.map_budget import map_view
    root = _root()
    try:
        view = map_view(root)
        labels, links = gen.labels(n), gen.links(n)
        view.set_data(labels, links, False)
        root.update()
        src, dst = f"s{n // 2}", f"s{(n // 2 + 7) % n}"
        extra = type(links[0])(src, dst, "jump", REF, jump_line(n), None)
        times = []
        for i in range(6):
            now = links + [extra] if i % 2 == 0 else links
            a = time.perf_counter()
            view.set_data(labels, now, False)
            root.update_idletasks()
            times.append((time.perf_counter() - a) * 1000)
        med = statistics.median(times[1:])
        print(f"\nAC-F58-14 {n}: one-scene layout + draw, median of 5: {med:.1f} ms")
        assert med <= ONE_SCENE_MS[n]
    finally:
        root.destroy()


# --- 04 §11, as measured here ------------------------------------------------------------------

def test_budget_table():
    from tests.perf import map_budget
    rows = map_budget.measure()
    print("\n" + map_budget.table(rows))
    missed = [row.label for row in rows if row.misses()]
    print("MISSES (> 30 % over 04's estimate):", "; ".join(missed) if missed else "none")
