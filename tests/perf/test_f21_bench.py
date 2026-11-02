"""F21 step 5 — the codex's bounded cost (``04-technical.md`` §9 invariant 10, §11 and its
amendment, lazy body layout; ``06-acceptance.md`` AC-F21-38; TR-F21-05 as re-scoped).

The bench story is ``tests/fixtures/F21/gen_counts.py``'s, at the real limits: 1,000 tips
(``Tips``) and 1,000 items (``Items``), loaded once per module. The view rows use a port over
it (Port P's shape) and the real fonts (``TestShell``), in F10's 808×552 body slot. The long
entry is 32 paragraphs of 2,000 code points.

**Default tier (CI guards: counts and a ratio).**
- Count: with all 1,000 tips unlocked, the first ``Codex.tips()`` read after a store change
  makes ≤ 1,000 ``is_unlocked`` calls, and the next read none.
- Count: ``CodexView.build`` with 1,000 tips and 1,000 held items fits no row title; the first
  draw fits at most the visible rows + 1, and the second none.
- Count (lazy body): showing the long entry lays out only the paragraphs in view (1, at 100%
  and at 150%); each ``update`` lays out at most one more; after 31 updates all 32 are laid
  out and the row heights equal a full layout's; showing it again lays out nothing; a row
  above the view that gets its real height moves ``scroll`` by the difference.
- Ratio: the median of 5 cold full layouts (``_ensure`` on every paragraph) of 32 × 2,000
  code points is ≤ 20 × the median for 32 × 200.

**``perf``: the reference-machine run (owner).** ADR-0005: Intel Core i5-8250U, Windows 11,
mains power, "Balanced" plan; or a stand-in with a PassMark single-thread score of at most
2,000. No window opens (about 30 s). From the project root, in cmd::

    set VN_PERF=1
    .venv/Scripts/python -m pytest -m perf -s -p no:cacheprovider tests/perf/test_f21_bench.py

(In PowerShell: ``$env:VN_PERF = "1"``, then the same command.) Each row is the median of
21 runs after 3 warm-up runs, ``gc`` on; attach the printed ``AC-F21-38`` line and the
machine's PassMark single-thread score to the test report (06 §7):

- TR-F21-05: showing the long entry (a cold view's ``build``, which runs ``_show``) ≤ 50 ms,
  and the slowest of the 31 ``update`` calls that lay out a paragraph ≤ 25 ms, at 100% and
  at 150%. These rows run under the frame loop's collector setting (``App.run``: a full
  collection only after ``GC_FULL_AFTER`` younger ones), as the page does; the line also
  prints the slowest update of all 21 runs, where such a full collection can land;
- ``CodexView.build`` with 2,000 rows (1,000 tips, 1,000 items) < 2 ms;
- the ``Codex.state()`` a checkpoint takes after one ``give`` with 1,000 held names < 0.05 ms.
"""

import gc
import statistics
import time
from pathlib import Path

import pygame
import pytest

from engine.app.app import GC_FULL_AFTER
from engine.core.paths import GamePaths
from engine.render.textlayout import LineLayout
from engine.runtime.codex import READ_KIND, TIP_KIND, Codex, CodexIndex
from engine.runtime.persistent import PersistentStore
from engine.script import load_story
from engine.script.program import Program
from engine.ui.builtin import codex_page
from engine.ui.builtin.codex_page import CodexView
from engine.ui.focus import FocusScope
from engine.ui.layouts import CODEX_GAP
from tests.fakes.ui_shell import TestShell
from tests.fixtures.F21.gen_counts import counts_story
from tests.ui.test_codex_view import FESTIVAL, SLOT, PortP, draw, entry

LIMIT = 1_000                       # tips and items (E254)
PARAGRAPHS = 32                     # E252's limits: 32 paragraphs of 2,000 code points
_program: Program | None = None


def bench_program(root: Path) -> Program:
    """1,000 tips and 1,000 items (module docstring), loaded once."""
    global _program
    if _program is None:
        script = root / "script"
        script.mkdir(parents=True)
        (script / "main.vns").write_bytes(counts_story(LIMIT, LIMIT).encode("utf-8"))
        result = load_story(GamePaths(root.resolve()))
        assert result.program is not None, [e.format() for e in result.errors[:3]]
        _program = result.program
    return _program


def installed(program: Program, held: int = 0) -> tuple[Codex, PersistentStore]:
    """A ``Codex`` on a store holding every tip, with ``held`` items (the first ones)."""
    index = CodexIndex.build(program)
    store = PersistentStore.with_data(unlocks={TIP_KIND: [e.name for e in index.tips]})
    store.register_kind(TIP_KIND, known=index.is_tip, revocable=True)
    store.register_kind(READ_KIND, known=index.has)
    codex = Codex(index, store, lambda command: None)
    codex.install(tuple(e.name for e in index.items[:held]))
    return codex, store


def port_over(program: Program, codex: Codex) -> PortP:
    """Port P's shape over the bench story: every tip unlocked, every item held, all read."""
    port = PortP(codex.tips(), codex.items(), entries=program.codex,
                 read=[e.name for e in program.codex])
    port.categories = lambda: program.codex_categories                 # type: ignore[method-assign]
    return port


def long_entry(chars: int, name: str = "long"):
    """An entry of 32 paragraphs of ``chars`` code points each (words of 8)."""
    paragraph = ("lantern " * (chars // 8 + 1))[:chars]
    return entry(name, "tip", "Long", FESTIVAL, *([paragraph] * PARAGRAPHS))


def shown(shell: TestShell, port: PortP, scale: float = 1.0) -> CodexView:
    """A cold view (empty caches) built on ``port``: its first entry is shown."""
    view = CodexView(port, ui=shell, scope=FocusScope)
    view.build(SLOT, scale)
    return view


def cold_full_layout_s(shell: TestShell, port: PortP) -> float:
    """A cold view's ``_show`` and then ``_ensure`` on every paragraph: the whole body."""
    view = CodexView(port, ui=shell, scope=FocusScope)
    start = time.perf_counter()
    view.build(SLOT, 1.0)
    for index in range(PARAGRAPHS):
        view._ensure(index)
    elapsed = time.perf_counter() - start
    assert view.layouts_made == PARAGRAPHS
    return elapsed


def full_heights(view: CodexView) -> list[float]:
    """The row heights of a full layout of the shown body (each paragraph laid out here)."""
    body = view._detail.body
    heights = []
    for i, paragraph in enumerate(body.paragraphs):
        page = LineLayout(paragraph, body.ctx).page(0)
        heights.append(max(body.pitch, sum(line.pitch for line in page.lines))
                       + (CODEX_GAP if i < len(body.paragraphs) - 1 else 0))
    return heights


def test_ac38_ci_guards(tmp_path, monkeypatch):
    pygame.init()
    program = bench_program(tmp_path / "bench")
    codex, store = installed(program, held=LIMIT)
    assert (len(codex.index.tips), len(codex.index.items)) == (LIMIT, LIMIT)

    # The tips read: one lookup per tip after a change, none from the cache.
    calls = [0]
    is_unlocked = store.is_unlocked

    def counted(kind, name):
        calls[0] += 1
        return is_unlocked(kind, name)

    monkeypatch.setattr(store, "is_unlocked", counted)
    assert codex.relock_tip("t0") and codex.unlock_tip("t0")         # a change, all unlocked
    calls[0] = 0
    first = codex.tips()
    assert len(first) == LIMIT and calls[0] <= LIMIT, calls
    calls[0] = 0
    assert codex.tips() == first and calls[0] == 0

    # The view: no title fitted by build, the visible rows by the first draw, none after.
    shell = TestShell()
    fitted: list[str] = []
    titles = {e.title for e in program.codex}
    cut = codex_page.cut_to_width

    def counted_cut(text, *args, **kwargs):
        if text in titles:
            fitted.append(text)
        return cut(text, *args, **kwargs)

    monkeypatch.setattr(codex_page, "cut_to_width", counted_cut)
    scope = FocusScope()
    view = CodexView(port_over(program, codex), ui=shell, scope=lambda: scope)
    scope.set_groups(view.build(SLOT, 1.0))
    assert len(view.rows()) == LIMIT and fitted == []
    draw(view, shell, scope)
    visible = int(view.list.box.h // view.list.row_height) + 1
    assert 0 < len(fitted) <= visible + 1, (len(fitted), visible)
    fitted.clear()
    draw(view, shell, scope)
    assert fitted == []

    # The lazy body: only what is in view on showing, then one paragraph per update.
    large = PortP(("long", "short"), entries=(long_entry(2_000), long_entry(20, "short")))
    for scale in (1.0, 1.5):
        view = shown(shell, large, scale)
        assert view.selected == "long" and view.layouts_made == 1, scale
        for n in range(1, PARAGRAPHS):
            view.update(1 / 60)
            assert view.layouts_made == 1 + n, (scale, n)
        assert all(page is not None for page in view._detail.pages)
        assert view.body_heights == full_heights(view), scale
        view.update(1 / 60)
        assert view.layouts_made == PARAGRAPHS                       # nothing left to do
        view._select_row(1)
        made = view.layouts_made
        view._select_row(0)
        assert view.selected == "long" and view.layouts_made == made   # a re-show: the cache
    # A row above the view that gets its real height keeps the text in view where it was.
    view = shown(shell, large)
    body = view.body
    body.scroll = body.max_scroll()
    view.update(1 / 60)                                              # the rows now in view
    first = body.visible_range().start
    assert first > 1 and view._detail.pages[1] is None
    before = (body.scroll, view.body_heights[1], body.row_box(first).y)
    assert view._ensure(1)
    assert body.scroll == pytest.approx(before[0] + view.body_heights[1] - before[1])
    assert body.row_box(first).y == pytest.approx(before[2])

    # The ratio: 2,000 code points a paragraph against 200, whole bodies.
    large_port = PortP(("long",), entries=(long_entry(2_000),))
    small_port = PortP(("long",), entries=(long_entry(200),))
    cold_full_layout_s(shell, small_port)                               # fonts warm
    small = statistics.median(cold_full_layout_s(shell, small_port) for _ in range(5))
    large_s = statistics.median(cold_full_layout_s(shell, large_port) for _ in range(5))
    assert large_s <= 20 * small, (large_s, small)


def _median_ms(run, setup=lambda: None, *, warm: int = 3, runs: int = 21) -> float:
    times = []
    for i in range(warm + runs):
        state = setup()
        start = time.perf_counter()
        run(state)
        if i >= warm:
            times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def _show_and_fill_ms(shell: TestShell, port: PortP, scale: float) -> tuple[float, float]:
    """One cold run: the ``build`` that shows the long entry, and the slowest of the
    updates that lay out the rest (ms)."""
    view = CodexView(port, ui=shell, scope=FocusScope)
    start = time.perf_counter()
    view.build(SLOT, scale)
    show = time.perf_counter() - start
    slowest = 0.0
    while view._detail.body.unlaid() is not None:
        made = view.layouts_made
        start = time.perf_counter()
        view.update(1 / 60)
        slowest = max(slowest, time.perf_counter() - start)
        assert view.layouts_made == made + 1
    return show * 1000, slowest * 1000


@pytest.mark.perf
def test_ac38_reference_machine(tmp_path):
    pygame.init()
    shell = TestShell()
    port = PortP(("long",), entries=(long_entry(2_000),))
    show_ms, update_ms, worst_ms = {}, {}, {}
    thresholds = gc.get_threshold()
    gc.set_threshold(thresholds[0], thresholds[1], max(thresholds[2], GC_FULL_AFTER))
    try:
        for scale in (1.0, 1.5):
            runs = [_show_and_fill_ms(shell, port, scale) for _ in range(3 + 21)][3:]
            show_ms[scale] = statistics.median(r[0] for r in runs)
            update_ms[scale] = statistics.median(r[1] for r in runs)
            worst_ms[scale] = max(r[1] for r in runs)
    finally:
        gc.set_threshold(*thresholds)

    program = bench_program(tmp_path / "bench")
    codex, _ = installed(program, held=LIMIT)
    rows = port_over(program, codex)
    build_ms = _median_ms(lambda view: view.build(SLOT, 1.0),
                          lambda: CodexView(rows, ui=shell, scope=FocusScope))

    codex, _ = installed(program, held=LIMIT - 1)
    last = codex.index.items[-1].name

    def gave() -> Codex:
        codex.take(last)
        codex.state()
        codex.give(last)                       # the one give since the last checkpoint
        return codex

    state_ms = _median_ms(lambda c: c.state(), gave)
    assert len(codex.state().held) == LIMIT
    print(f"\nAC-F21-38: showing 32 x 2,000 code points {show_ms[1.0]:.1f} ms at 100%, "
          f"{show_ms[1.5]:.1f} ms at 150% (<= 50); slowest laying-out update "
          f"{update_ms[1.0]:.1f} ms at 100%, {update_ms[1.5]:.1f} ms at 150% (<= 25; worst of all "
          f"runs {worst_ms[1.0]:.1f} / {worst_ms[1.5]:.1f} ms); "
          f"CodexView.build with 2,000 rows {build_ms:.3f} ms (< 2); Codex.state() after one "
          f"give with 1,000 held {state_ms:.4f} ms (< 0.05)")
    assert show_ms[1.0] <= 50 and show_ms[1.5] <= 50
    assert update_ms[1.0] <= 25 and update_ms[1.5] <= 25
    assert build_ms < 2 and state_ms < 0.05
