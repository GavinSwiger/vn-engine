"""F58's budget measurements (``04-technical.md`` §11; ``07`` I-12, I-14; step P0).

Every row of 04 §11's two tables, timed on this machine at 300 and 1,000 scenes with one file
holding every scene (``gen_map_bench``), plus 07 I-14's extras. Rows whose code isn't built
yet are timed on the operations the design plans (a *proxy*: say which in ``how``):

- **relayout**: today's ``layout`` with chip slotting switched off (columns, marks, boxes and
  edges, the O(n+e) part 04 §7.6 keeps), plus four ``chip_slot`` probes on a built
  ``RectHash`` (the dirty chips of a one-scene change).
- **model + delta**: one file's label and edge rows rebuilt from its ``SceneIndex`` and
  compared with the shown rows (04 §7.5).
- **apply + paint**: on a canvas holding the whole map (drawn by today's view), the stored-id
  ops of a one-box change: its items deleted and drawn again, its four arrows' ``coords``,
  two chips moved, every visible box's ``file:line`` text changed (a line inserted above
  them), then ``update_idletasks``. Three cases: 100 % zoom; 50 % zoom on the ``start``
  layout (more boxes in view); and 250 texts, Q4's "boxes in view" bound.

Timer rows wait in ``mainloop`` as Studio does. 07 I-14's keystroke rows run an ``after(1)``
chain on Tk while a thread decodes 16 MiB or reads a 2,000-file checkout, and report how
late the chain's worst tick was (a key event waits as long).

``python -m tests.perf.map_budget`` prints the table (``--sizes 300 1000``; ``--quick`` for
fewer repeats; ``--only typing,other,extras``). The perf tests in ``test_live_map_perf.py``
import the same functions.
"""

import argparse
import gc
import os
import shutil
import statistics
import tempfile
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from engine.core.paths import GamePaths
from engine.tools.editor import document, scenes, storymap
from engine.tools.editor.checker import CheckEvent, CheckResult, CheckState
from tests.perf import gen_map_bench as gen

SIZES = (300, 1000)
REF = gen.MAIN

# 04 §11 (300, 1,000); None: not gated (no estimate, or a target for later steps).
EST: dict[str, tuple[float | None, float | None]] = {
    "debounce": (96, 96),
    "widget_get": (1, 3),
    "reindex": (1.2, 3.5),
    "model_delta": (0.5, 1.5),
    "relayout": (3, 8),
    "apply_paint": (4, 7),
    "typing_total": (106, 119),
    "throttle": (276, 289),
    "rebase": (2, 2),
    "record_for": (30, 30),
    "apply_plan": (5, 5),
    "apply_total": (49, 63),
    "map_undo": (12, 26),
    "listing": (1.4, 5),
    "read": (2, 2),
    "poll": (66, 66),
    "outside_closed": (334, 346),
    "set_text": (30, 30),
    "outside_open": (364, 376),
    "ac14": (5, 11),
    "full_redraw": (None, None),
}
MISS = 1.30                                 # a row misses when measured > 1.3 × its estimate


@dataclass
class Row:
    key: str
    label: str
    values: dict[int, float] = field(default_factory=dict)
    how: str = ""
    gated: bool = True

    def est(self, n: int) -> float | None:
        pair = EST.get(self.key)
        if pair is None:
            return None
        return pair[0] if n == 300 else pair[1] if n == 1000 else None

    def misses(self) -> list[int]:
        out = []
        for n, value in self.values.items():
            est = self.est(n)
            if self.gated and est is not None and value > est * MISS:
                out.append(n)
        return out


def median_ms(fn: Callable[[], object], k: int = 9, warm: int = 2) -> float:
    for _ in range(warm):
        fn()
    times = []
    for _ in range(k):
        gc.collect()
        a = time.perf_counter()
        fn()
        times.append((time.perf_counter() - a) * 1000)
    return statistics.median(times)


# --- Tk timers ---------------------------------------------------------------------------------

def timer_lateness(root: tk.Tk, delay: int, k: int = 15) -> tuple[float, float]:
    """Median and worst lateness (ms past ``delay``) of ``root.after(delay)``, waited for in
    ``mainloop`` as Studio waits."""
    late = []
    for _ in range(k):
        start = time.perf_counter()

        def fire() -> None:
            late.append((time.perf_counter() - start) * 1000 - delay)
            root.quit()

        root.after(delay, fire)
        root.mainloop()
    return statistics.median(late), max(late)


# --- Pure pieces -------------------------------------------------------------------------------

def edited(text: str, scene: int = 0) -> str:
    """``text`` with one dialogue line of ``scene`` changed (same line count)."""
    lines = text.split("\n")
    lines[gen.SCENE_LINES * scene + 1] = f'    "Scene {scene} line one, edited."'
    return "\n".join(lines)


def reindex_ms(n: int, k: int) -> float:
    text = gen.script(n)
    index = scenes.reindex(None, REF, text, 1, checked=None)
    text2 = edited(text, n // 2)
    return median_ms(lambda: scenes.reindex(index, REF, text2, 2, checked=index.checked), k)


def model_delta_ms(n: int, k: int) -> float:
    """04 §7.5's proxy: the changed file's rows rebuilt from its index and diffed."""
    text = gen.script(n)
    index = scenes.reindex(None, REF, text, 1, checked=None)
    index = scenes.reindex(index, REF, edited(text, n // 2), 2, checked=index.checked)
    by_src: dict[str, list[tuple]] = {}
    for link in gen.links(n):
        by_src.setdefault(link.src, []).append(
            (link.src, link.dst, link.kind, link.choice, link.conditional))

    def rows() -> tuple[dict, list]:
        labels = {name: line for (name, n_), line in index.starts.items() if n_ == 0}
        edges: list[tuple] = []
        for key in index.starts:
            read = index.reads.get(key) or index.good.get(key)
            if read is not None:
                edges.extend((ln.src, ln.dst, ln.kind, ln.choice, ln.conditional)
                             for ln in read.links)
            elif key[1] == 0:
                edges.extend(by_src.get(key[0], ()))
        return labels, edges

    shown = rows()

    def step() -> None:
        labels, edges = rows()
        old_labels, old_edges = shown
        moved = [name for name, line in labels.items() if old_labels.get(name) != line]
        gone = old_labels.keys() - labels.keys()
        new_edges, old_set = set(edges), set(old_edges)
        return moved, gone, new_edges - old_set, old_set - new_edges

    return median_ms(step, k)


def map_data_today_ms(n: int, k: int) -> float:
    """Today's ``scenes.map_data`` (its labels × starts loop) on one indexed file."""
    text = gen.script(n)
    index = scenes.reindex(None, REF, text, 1, checked=None)
    labels, links = gen.labels(n), gen.links(n)
    return median_ms(lambda: scenes.map_data(labels, links, {REF: index}), k)


def layout_ms(n: int, k: int) -> float:
    labels, links = gen.labels(n), gen.links(n)
    return median_ms(lambda: storymap.layout(links, labels), k)


def relayout_proxy_ms(n: int, k: int) -> tuple[float, float]:
    """(layout without chip slotting, four ``chip_slot`` probes)."""
    labels, links = gen.labels(n), gen.links(n)
    real = storymap._slot_chips
    storymap._slot_chips = lambda boxes, edges: edges
    try:
        base = median_ms(lambda: storymap.layout(links, labels), k)
    finally:
        storymap._slot_chips = real
    found = storymap.layout(links, labels)
    taken = storymap.RectHash(storymap.box_rect(b.x, b.y) for b in found.boxes)
    mid = len(found.edges) // 2
    picks = [i for i in range(mid, mid + 4)]
    curves = [storymap.edge_curve(found, i) for i in picks]
    size = storymap.chip_size("Go back")

    def probes() -> None:
        for line in curves:
            storymap.chip_slot(line, size, taken)

    return base, median_ms(probes, k)


# --- Tk pieces ---------------------------------------------------------------------------------

def new_root() -> tk.Tk:
    root = tk.Tk()
    root.geometry("1400x900+0+0")
    return root


def map_view(root: tk.Tk):
    from engine.tools.editor.views import StoryMapView
    view = StoryMapView(root, background="#1e1e1e", family="Segoe UI", mod="Control",
                        on_open=lambda b: None)
    view.frame.pack(fill="both", expand=True)
    root.update()
    return view


def full_draw_ms(root: tk.Tk, view, n: int, k: int) -> float:
    labels, links = gen.labels(n), gen.links(n)

    def draw() -> None:
        view.set_data(labels, links, False)
        root.update_idletasks()

    return median_ms(draw, k, warm=1)


def visible_boxes(view) -> list[int]:
    """The boxes in the canvas's visible part."""
    c = view.canvas
    x0, y0 = c.canvasx(0), c.canvasy(0)
    x1, y1 = c.canvasx(c.winfo_width()), c.canvasy(c.winfo_height())
    out = []
    for j in range(len(view.layout.boxes)):
        a0, b0, a1, b1 = view.box_rect(j)
        if a1 > x0 and a0 < x1 and b1 > y0 and b0 < y1:
            out.append(j)
    return out


def apply_paint_ms(root: tk.Tk, view, n: int, k: int, *, zoom: int = 100,
                   start: bool = False, lines_cap: int | None = None) -> dict[str, float]:
    """The stored-id canvas ops of a one-box change on a fully drawn map (see the module
    doc): every visible box's ``file:line`` text changes (a line inserted above them), or the
    first ``lines_cap`` boxes' when given. Returns each part, the total and the line count."""
    labels, links = gen.labels(n, start=start), gen.links(n, start=start)
    view.zoom = zoom
    view.set_data(labels, links, False)
    root.update()
    canvas = view.canvas
    lay = view.layout
    canvas.yview_moveto(0)
    canvas.xview_moveto(0)
    root.update()
    shown = visible_boxes(view)
    i = shown[min(len(shown) - 1, 3)]
    picked = shown if lines_cap is None else list(range(min(lines_cap, len(lay.boxes))))
    where = [canvas.find_withtag(f"where{j}")[0] for j in picked]
    edges = [e for e, edge in enumerate(lay.edges) if i in (edge.src, edge.dst)][:4]
    edge_ids = [view.edge_items[e][0] for e in edges]
    chip_ids = [canvas.find_withtag(f"chip{e}") for e in edges[:2]]
    counter = [0]
    ids = list(canvas.find_withtag(f"box{i}"))

    def redraw_box() -> None:
        x0, y0, x1, y1 = view.box_rect(i)
        for item in ids:
            canvas.delete(item)
        ids[:] = [
            canvas.create_rectangle(x0, y0, x1, y1, outline="#888", fill="#252526",
                                    tags=("box",)),
            canvas.create_text(x0 + 8, y0 + 4, anchor="nw", text=lay.boxes[i].name,
                               font=view.name_font, fill="#ccc", tags=("box",)),
            canvas.create_text(x0 + 8, y1 - 4, anchor="sw", text="script/main.vns:1",
                               font=view.detail_font, fill="#888", tags=("box",)),
            canvas.create_text(x1 - 8, y0 + 4, anchor="ne", text="not reached",
                               font=view.detail_font, fill="#888", tags=("box",))]

    def arrows() -> None:
        for item in edge_ids:
            canvas.coords(item, *canvas.coords(item))
        for items in chip_ids:
            for item in items:
                canvas.move(item, 0, 1 if counter[0] % 2 else -1)

    def lines() -> None:
        counter[0] += 1
        for j, item in enumerate(where):
            canvas.itemconfigure(item, text=f"script/main.vns:{9 * j + 1 + counter[0] % 2}")

    def paint() -> None:
        root.update_idletasks()

    out = {"box": median_ms(redraw_box, k), "arrows": median_ms(arrows, k),
           "lines": median_ms(lines, k)}

    def total() -> None:
        redraw_box()
        arrows()
        lines()
        paint()

    out["total"] = median_ms(total, k)
    out["count"] = len(where)
    view.zoom = 100
    return out


def shared_restyle_ms(root: tk.Tk, view, n: int, k: int) -> float:
    """04 §5's "shared-tag restyle": one ``itemconfigure`` on a tag every box shares."""
    view.set_data(gen.labels(n), gen.links(n), False)
    root.update()
    flip = [0]

    def restyle() -> None:
        flip[0] ^= 1
        view.canvas.itemconfigure("chip", width=1 + flip[0])
        root.update_idletasks()

    return median_ms(restyle, k)


def glow_step_ms(root: tk.Tk, view, n: int, k: int) -> float:
    """04 §5's glow: 50 outlines recoloured by stored id, one fade step."""
    view.set_data(gen.labels(n), gen.links(n), False)
    root.update()
    ids = [view.canvas.find_withtag(f"rect{j}")[0] for j in range(min(50, n))]
    flip = [0]

    def step() -> None:
        flip[0] ^= 1
        color = "#89D185" if flip[0] else "#6a9a66"
        for item in ids:
            view.canvas.itemconfigure(item, outline=color, width=3)
        root.update_idletasks()

    return median_ms(step, k)


# --- The Studio window -------------------------------------------------------------------------

class _Checks:
    def request(self, overlay, serial, *, launch):
        pass

    def poll(self):
        return []

    def stop(self):
        pass


def studio(root: tk.Tk, game: Path, n: int, files: int = 1):
    from engine.tools.editor import window
    win = window.EditorWindow(root, GamePaths.for_game(game), check_runner=_Checks())
    result = CheckResult(problems=(), problem_total=0, names={"label": tuple(gen.labels(n, files))},
                         links=tuple(gen.links(n, files)), loaded=True, serial=win.edit_serial,
                         seconds=0.1)
    win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    root.update()
    return win


def drop_window(root: tk.Tk, win) -> None:
    """Close a bench window: its timers cancelled first, so none fires in another root."""
    win.closed = True
    for token in root.tk.splitlist(root.tk.call("after", "info")):
        try:
            root.after_cancel(token)
        except tk.TclError:
            pass
    root.destroy()


def window_rows(root: tk.Tk, game: Path, n: int, k: int) -> dict[str, float]:
    """``record_for`` (a closed file, first open), ``_set_text``, ``apply_plan``, the text
    undo + reindex of map undo, and ``rebase``."""
    from engine.tools.assistant import edits
    from engine.tools.assistant.workspace import text_sha
    from engine.tools.editor.scriptedit import FilePlan, LineEdit, Plan
    win = studio(root, game, n)
    out: dict[str, float] = {}
    times = []
    for _ in range(max(3, k // 2)):
        win._drop_record(REF) if REF in win.files else None
        root.update()
        gc.collect()
        a = time.perf_counter()
        win.record_for(REF)
        times.append((time.perf_counter() - a) * 1000)
    out["record_for"] = statistics.median(times)
    record = win.files[REF]
    text = record.widget.get("1.0", "end-1c")
    out["widget_get"] = median_ms(lambda: record.widget.get("1.0", "end-1c"), k)
    out["set_text"] = median_ms(lambda: win._set_text(record, text), k)
    line = gen.SCENE_LINES * (n // 2) + 2
    plan = Plan("Bench", (FilePlan(REF, (), (LineEdit(line, line, ('    "Changed."',)),)),))

    def apply_then_undo() -> float:
        a = time.perf_counter()
        win.apply_plan(plan, lambda texts: True)
        spent = (time.perf_counter() - a) * 1000
        record.widget.edit_undo()
        return spent

    for _ in range(2):
        apply_then_undo()
    out["apply_plan"] = statistics.median(apply_then_undo() for _ in range(k))

    def undo_reindex() -> float:
        win.apply_plan(plan, lambda texts: True)
        win._reindex()
        a = time.perf_counter()
        record.widget.edit_undo()
        win._reindex()
        return (time.perf_counter() - a) * 1000

    out["undo_reindex"] = statistics.median(undo_reindex() for _ in range(k))
    # rebase on text that moved (the slow path: every chunk digested), as after typing.
    live = record.widget.get("1.0", "end-1c")
    marks = edits._chunk_marks(live, live.split("\n"))
    key = marks[n // 2][0]
    pfile = edits.ProposalFile(REF, text_sha(live + "x"), plan.files[0], False, False, 1, 1,
                               (), touched=((key,),),
                               marks=tuple((m[0], m[1], m[3]) for m in marks if m[0] == key))
    out["rebase"] = median_ms(lambda: edits.rebase(pfile, live), k)
    out["win"] = win
    return out


# --- The watch ---------------------------------------------------------------------------------

def listing_ms(script_dir: Path, k: int, *, stat_each: bool = False) -> float:
    """``scandir`` of ``script/**`` keeping ``(mtime_ns, size)`` per ``.vns`` (04 §7.1), or
    with an ``os.stat`` per file (§5's comparison)."""
    def walk() -> dict[str, tuple[int, int]]:
        found: dict[str, tuple[int, int]] = {}
        stack = [str(script_dir)]
        while stack:
            folder = stack.pop()
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_symlink() or entry.is_junction():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.name.endswith(".vns"):
                        st = os.stat(entry.path) if stat_each else entry.stat(
                            follow_symlinks=False)
                        found[entry.path] = (st.st_mtime_ns, st.st_size)
        return found

    return median_ms(walk, k)


def read_ms(game: Path, ref: str, k: int) -> float:
    paths = GamePaths.for_game(game)
    return median_ms(lambda: document.open_document(paths, ref), k)


def loop_delay_under(root: tk.Tk, work: Callable[[], object], *, seconds: float = 1.0,
                     tick: int = 1, burst: int = 50) -> dict[str, float]:
    """Tk's event-loop delay while ``work`` runs on a thread: an ``after(tick)`` chain records
    how late each tick fires (ms past ``tick``), and every tenth tick times ``burst`` canvas
    calls (a keystroke's handlers make dozens: each Tk call gives up the GIL and must get it
    back); the same with no thread first."""
    canvas = tk.Canvas(root)
    item = canvas.create_line(0, 0, 10, 10)

    def run(thread: threading.Thread | None) -> tuple[list[float], list[float]]:
        late: list[float] = []
        bursts: list[float] = []
        last = [time.perf_counter()]
        end = time.perf_counter() + seconds

        def step() -> None:
            now = time.perf_counter()
            late.append((now - last[0]) * 1000 - tick)
            if len(late) % 10 == 0:
                a = time.perf_counter()
                for _ in range(burst):
                    canvas.coords(item, 0, 0, 10, 10)
                bursts.append((time.perf_counter() - a) * 1000)
            last[0] = time.perf_counter()
            if now >= end and (thread is None or not thread.is_alive()):
                root.quit()
                return
            root.after(tick, step)

        if thread is not None:
            thread.start()
        root.after(tick, step)
        root.mainloop()
        if thread is not None:
            thread.join()
        return late, bursts or [0.0]

    idle, idle_bursts = run(None)
    took = [0.0]

    def timed() -> None:
        a = time.perf_counter()
        work()
        took[0] = (time.perf_counter() - a) * 1000

    busy, busy_bursts = run(threading.Thread(target=timed, daemon=True))
    canvas.destroy()
    q = statistics.quantiles
    return {"idle_p99": q(idle, n=100)[98], "idle_max": max(idle),
            "busy_p99": q(busy, n=100)[98], "busy_max": max(busy), "work_ms": took[0],
            "idle_burst": statistics.median(idle_bursts),
            "busy_burst": statistics.median(busy_bursts), "busy_burst_max": max(busy_bursts)}


# --- The table ---------------------------------------------------------------------------------

def measure(sizes=SIZES, *, quick: bool = False, only=("typing", "other", "extras"),
            say: Callable[[str], None] = print) -> list[Row]:
    k = 5 if quick else 11
    rows: dict[str, Row] = {}

    def put(key: str, label: str, n: int, value: float, how: str = "", gated: bool = True):
        row = rows.setdefault(key, Row(key, label, how=how, gated=gated))
        row.values[n] = value

    tmp = Path(tempfile.mkdtemp(prefix="f58bench-"))
    root = new_root()
    try:
        lat80 = timer_lateness(root, 80)
        lat250 = timer_lateness(root, 250, k=8)
        lat50 = timer_lateness(root, 50)
        say(f"timer lateness ms (median, worst): after(80) {lat80}, after(250) {lat250}, "
            f"after(50) {lat50}")
        view = map_view(root)
        for n in sizes:
            say(f"-- {n} scenes")
            game = gen.write_game(tmp / f"one{n}", n, 1)
            spread = gen.write_game(tmp / f"spread{n}", n, n)
            rx = reindex_ms(n, 3 * k)
            md = model_delta_ms(n, 3 * k)
            base, chips = relayout_proxy_ms(n, k)
            rl = base + chips
            ap = apply_paint_ms(root, view, n, k)
            wr_root = tk.Tk()
            wr_root.withdraw()
            wr = window_rows(wr_root, game, n, k)
            drop_window(wr_root, wr.pop("win"))
            update = md + rl + ap["total"]                # after reindex and the text read
            put("debounce", "Debounce 80 + timer lateness (median; worst)", n, 80 + lat80[0],
                f"after(80) in mainloop, worst {80 + lat80[1]:.0f}")
            put("widget_get", "`widget.get` (one file, whole text)", n, wr["widget_get"])
            put("reindex", "`reindex`, one scene", n, rx)
            put("model_delta", "Model + delta ~ (proxy)", n, md,
                f"rows from index + set diff; today's map_data {map_data_today_ms(n, k):.1f}")
            put("relayout", "`relayout` ~ (proxy)", n, rl,
                f"layout w/o chips {base:.1f} + 4 chip_slot {chips:.2f}")
            put("apply_paint", "`apply` + visible lines + paint ~ (proxy, 100 % zoom)", n,
                ap["total"], f"box {ap['box']:.2f}, arrows+chips {ap['arrows']:.2f}, "
                             f"{ap['count']} visible lines {ap['lines']:.2f}")
            ap50 = apply_paint_ms(root, view, n, k, zoom=50, start=True)
            ap250 = apply_paint_ms(root, view, n, k, zoom=50, start=True, lines_cap=250)
            rows.setdefault("apply_paint_50", Row(
                "apply_paint", "`apply` + visible lines + paint ~ (proxy, 50 % zoom, "
                               "start layout)")).values[n] = ap50["total"]
            rows["apply_paint_50"].how = (f"{ap50['count']} visible lines "
                                          f"{ap50['lines']:.2f}")
            rows.setdefault("apply_paint_250", Row(
                "apply_paint", "`apply` + 250 lines + paint ~ (proxy, Q4's cap)")
            ).values[n] = ap250["total"]
            rows["apply_paint_250"].how = f"250 lines {ap250['lines']:.2f}"
            typing = 80 + lat80[0] + wr["widget_get"] + rx + update
            put("typing_total", "**Typing total (target 150)**", n, typing)
            put("throttle", "Throttle: 250 + lateness + update (target 300)", n,
                250 + lat250[0] + wr["widget_get"] + rx + update)
            put("rebase", "`rebase` (moved text: every chunk digested)", n, wr["rebase"])
            put("record_for", "`record_for`, closed file (first open)", n, wr["record_for"])
            put("apply_plan", "`apply_plan` (one edit)", n, wr["apply_plan"])
            put("apply_total", "**Apply, one closed file (target 150)**", n,
                wr["rebase"] + wr["record_for"] + wr["apply_plan"] + rx + update)
            put("map_undo", "**Map undo (target 150)**", n, wr["undo_reindex"] + update,
                f"text undo + _reindex {wr['undo_reindex']:.1f} + update")
            lst_one = listing_ms(game / "script", 3 * k)
            lst = listing_ms(spread / "script", 3 * k)
            put("listing", "Watch listing (`scandir`, n files)", n, lst,
                f"one file {lst_one:.2f}; with os.stat each "
                f"{listing_ms(spread / 'script', k, stat_each=True):.1f}")
            rd = read_ms(game, REF, k)
            put("read", "Read + decode the changed file (`open_document`)", n, rd,
                f"{(game / 'script' / 'main.vns').stat().st_size // 1024} KiB")
            put("poll", "Mailbox poll 50 + lateness", n, 50 + lat50[0],
                f"worst {50 + lat50[1]:.0f}")
            tk_part = rx + update
            outside = 250 + lst + rd + 50 + lat50[0] + tk_part
            put("outside_closed", "**Outside edit, closed file (target 500)**", n, outside,
                "tick 250 + listing + read + poll + reindex + update")
            put("set_text", "`_set_text` (reload an open file)", n, wr["set_text"])
            put("outside_open", "**Outside edit, open clean file (target 500)**", n,
                outside + wr["set_text"])
            put("ac14", "**One-scene layout + draw, AC-14 (16 / 50)**", n, rl + ap["total"])
            if "extras" in only:
                fd = full_draw_ms(root, view, n, 3)
                put("full_redraw", "Full redraw today (`set_data` + draw)", n, fd,
                    "not gated", gated=False)
                put("layout_today", "`layout` today", n, layout_ms(n, k), gated=False)
                put("shared_restyle", "Shared-tag restyle (`chip`), today", n,
                    shared_restyle_ms(root, view, n, k), gated=False)
                put("glow_step", "Glow step: 50 outlines by id + paint", n,
                    glow_step_ms(root, view, n, k), gated=False)
            say("   done")
        if "extras" in only:
            for key, label, value, how in extras(root, tmp, k):
                put(key, label, 0, value, how, gated=False)
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    return list(rows.values())


def extras(root: tk.Tk, tmp: Path, k: int):
    """07 I-12 and I-14's rows: (key, label, ms, how)."""
    big = tmp / "big"
    gen.write_game(big, 10, 1)
    text16 = gen.big_text(16 * 1024 * 1024 - 64 * 1024)
    (big / "script" / "huge.vns").write_bytes(text16.encode())
    text1 = gen.big_text(1024 * 1024 - 4096)
    (big / "script" / "one_mib.vns").write_bytes(text1.encode())
    paths = GamePaths.for_game(big)
    out = []
    d16 = loop_delay_under(root, lambda: document.open_document(paths, "script/huge.vns"))
    out.append(("key_16mib", "Keystroke delay while the watch decodes 16 MiB (worst)",
                d16["busy_max"], f"p99 {d16['busy_p99']:.1f}, idle worst {d16['idle_max']:.1f}, "
                                 f"thread {d16['work_ms']:.0f} ms"))
    out.append(("burst_16mib", "50 Tk calls while the watch decodes 16 MiB (median)",
                d16["busy_burst"], f"worst {d16['busy_burst_max']:.1f}, idle "
                                   f"{d16['idle_burst']:.2f}"))
    many = tmp / "many"
    gen.write_game(many, 2000, 2000)
    mpaths = GamePaths.for_game(many)

    def checkout() -> None:
        refs = document.list_scripts(mpaths)
        for ref in refs:
            document.open_document(mpaths, ref)

    d2k = loop_delay_under(root, checkout)
    out.append(("key_2000", "Keystroke delay while the watch reads 2,000 files (worst)",
                d2k["busy_max"], f"p99 {d2k['busy_p99']:.1f}, idle worst {d2k['idle_max']:.1f}, "
                                 f"thread {d2k['work_ms']:.0f} ms"))
    out.append(("burst_2000", "50 Tk calls while the watch reads 2,000 files (median)",
                d2k["busy_burst"], f"worst {d2k['busy_burst_max']:.1f}"))

    def listings() -> None:                     # four ticks' listings, back to back
        for _ in range(4):
            listing_ms(many / "script", 1)

    dl = loop_delay_under(root, listings, seconds=0.3)
    out.append(("burst_list", "50 Tk calls while the watch lists 2,000 files (median)",
                dl["busy_burst"], f"worst {dl['busy_burst_max']:.1f}; keystroke worst "
                                  f"{dl['busy_max']:.1f}"))
    out.append(("read_1mib", "I-12: `open_document` of a 1 MiB file on Tk",
                read_ms(big, "script/one_mib.vns", k), ""))
    out.append(("read_16mib", "`open_document` of a 16 MiB file (thread time)",
                read_ms(big, "script/huge.vns", 3), ""))
    # Apply on a card touching 8 large closed files: record_for × 8 (R2).
    from engine.tools.editor import window
    for key, texts in (("apply_8", [gen.script(1000, first=f * 1000, count=1000, total=8000)
                                    for f in range(8)]),
                       ("apply_8_mib", [text1] * 8)):
        eight = tmp / key
        gen.write_game(eight, 10, 1)
        for f, text in enumerate(texts):
            (eight / "script" / f"big{f}.vns").write_bytes(text.encode())
        wroot = tk.Tk()
        wroot.withdraw()
        win = window.EditorWindow(wroot, GamePaths.for_game(eight), check_runner=_Checks())
        wroot.update()
        a = time.perf_counter()
        for f in range(8):
            win.record_for(f"script/big{f}.vns")
        spent = (time.perf_counter() - a) * 1000
        drop_window(wroot, win)
        size = (eight / "script" / "big0.vns").stat().st_size // 1024
        out.append((key, "Apply touching 8 large closed files: `record_for` × 8", spent,
                    f"8 × {size} KiB"))
    return out


def best_of(runs: list[list[Row]]) -> list[Row]:
    """Each row's lowest value per size over several runs of ``measure``."""
    out = runs[0]
    for rows in runs[1:]:
        for mine, other in zip(out, rows):
            for n, value in other.values.items():
                mine.values[n] = min(mine.values.get(n, value), value)
    return out


def table(rows: list[Row], sizes=SIZES) -> str:
    head = "| Row | " + " | ".join(f"est {n} | measured {n}" for n in sizes) + " | Misses | How |"
    rule = "|---|" + "---:|---:|" * len(sizes) + "---|---|"
    out = [head, rule]
    for row in rows:
        if 0 in row.values:
            cells = f"— | {row.values[0]:.1f} |" + " — | — |" * (len(sizes) - 1)
            out.append(f"| {row.label} | {cells} | {row.how} |")
            continue
        cells = []
        for n in sizes:
            est = row.est(n)
            value = row.values.get(n)
            shown = "—" if value is None else f"{value:.2f}" if value < 10 else f"{value:.1f}"
            cells.append(f"{'—' if est is None else f'{est:g}'} | {shown}")
        miss = ", ".join(str(n) for n in row.misses()) or ""
        out.append(f"| {row.label} | {' | '.join(cells)} | {miss} | {row.how} |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--sizes", type=int, nargs="*", default=list(SIZES))
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--only", default="typing,other,extras")
    parser.add_argument("--runs", type=int, default=1,
                        help="repeat the whole table and keep each row's lowest value "
                             "(other work on the machine only ever adds time)")
    args = parser.parse_args(argv)
    rows = best_of([measure(tuple(args.sizes), quick=args.quick,
                            only=tuple(args.only.split(","))) for _ in range(args.runs)])
    print(table(rows, tuple(args.sizes)))
    missed = [row.label for row in rows if row.misses()]
    print("\nMISSES (> 30 % over 04's estimate):", "; ".join(missed) if missed else "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
