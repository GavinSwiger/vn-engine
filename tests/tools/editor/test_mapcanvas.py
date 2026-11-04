"""F58 P5: the map painter on a real canvas with fake diffs (``04-technical.md`` §7.8–7.10;
``07`` I-8, I-10). The window's use of it (AC-F58-14, 15, 21, 24, 27) is W1–W5's."""

import pytest

from engine.tools.editor import mapcanvas
from engine.tools.editor.livemap import FileRows, GlowSet, MapModel, preview_rows
from engine.tools.editor.mapcanvas import LINES_PER_PAINT, MapPainter
from engine.tools.editor.storymap import relayout
from tests.perf import gen_map_bench as gen
from tests.tools.editor.canvas_counter import CountingCanvas
from tests.tools.editor.live_fakes import FakeClock

tk = pytest.importorskip("tkinter")
pytestmark = pytest.mark.tk


@pytest.fixture
def canvas():
    from tests.tools.editor.test_window import new_root
    root = new_root()                                   # retries a flaky Tk start
    root.geometry("900x600")
    widget = tk.Canvas(root, width=900, height=600)
    widget.pack()
    root.update()
    yield widget
    root.destroy()


def _painter(canvas, idle=None):
    from tkinter import font as tkfont
    fonts = [tkfont.Font(root=canvas, family="Segoe UI", size=-px) for px in (13, 11, 12)]
    return MapPainter(canvas, name_font=fonts[0], detail_font=fonts[1], chip_font=fonts[2],
                      idle=idle or (lambda fn: None))


def _jump(n):
    return type(gen.links(2)[0])(f"s{n // 2}", f"s{(n // 2 + 7) % n}", "jump", gen.MAIN, 1)


def test_f58_p5_a_one_scene_change_touches_only_its_items(canvas):
    calls = {}
    for n in (300, 1000):
        labels, links = gen.labels(n, start=True), gen.links(n, start=True)
        first, diff = relayout(None, links, labels)
        painter = _painter(canvas)
        painter.draw(first)
        assert not any(t.startswith(("box", "edge", "chip", "rect")) and t[-1].isdigit()
                       for item in canvas.find_all() for t in canvas.gettags(item))   # I-10
        counter = CountingCanvas.install(painter)
        now, change = relayout(first, links + [_jump(n)], labels, pins=diff.placed)
        assert painter.apply(now, change)
        assert counter.deleted_all == 0
        assert counter.shared_restyles({"box", "edge", "chip", "edge-jump", "edge-menu"}) == 0
        calls[n] = counter.total(ignore={"itemconfigure"})
        assert set(painter.boxes) == {b.name for b in now.boxes}
        assert set(painter.edges) == set(now.edge_keys)
        painter.canvas = counter.real
        painter.clear()
        assert canvas.find_all() == ()
    assert calls[300] == calls[1000]


def test_f58_p5_registry_layers_glow_preview_and_line_texts(canvas):
    pending: list = []
    labels, links = gen.labels(40, start=True), gen.links(40, start=True)
    first, diff = relayout(None, links, labels)
    painter = _painter(canvas, idle=pending.append)
    painter.draw(first)
    pins = dict(diff.placed)
    x0, y0, x1, y1 = painter.box_rect("s1")
    assert painter.box_at((x0 + x1) / 2, (y0 + y1) / 2) == "s1"
    assert set(painter.items_of("s1")) <= set(canvas.find_all())

    # A new box and arrow, glowing; a ghost for a removed arrow; a card preview.
    more_labels = labels + [type(labels[0])("side", gen.MAIN, 999)]
    gone = links[3]
    more_links = [link for link in links if link is not gone] + \
        [type(links[0])("s1", "side", "jump", gen.MAIN, 5)]
    now, change = relayout(first, more_links, more_labels, pins=pins)
    assert painter.apply(now, change)
    clock = FakeClock()
    glow = GlowSet(clock.now)
    started = glow.start(["side"], [("s1", "side", "jump")],
                         ghost_edges=[(gone.src, gone.dst, gone.kind)])
    painter.glow(started.changes)
    box_glow = painter.glows[("box", "side")]
    ghost = painter.glows[("ghost_edge", (gone.src, gone.dst, gone.kind))]
    edge = painter.edges[("s1", "side", "jump")]
    assert canvas.itemcget(edge, "fill").upper() == mapcanvas.GLOW_COLOR.upper()
    clock.advance(1_550)
    painter.glow(glow.tick())
    assert canvas.itemcget(box_glow, "outline").upper() != mapcanvas.GLOW_COLOR.upper()
    model = MapModel.from_check(more_labels, more_links)
    rows = model.files[gen.MAIN]
    after = FileRows(rows.labels + (("ending", 1000),),
                     rows.edges + (("side", "ending", "menu", "To the end", False),))
    found = preview_rows(model, {gen.MAIN: after})
    trial = painter.preview(found, [*model.links(), (
        "side", "ending", "menu", gen.MAIN, 0, "To the end", False)],
        [*model.labels(), ("ending", gen.MAIN, 1000)], pins=pins, places={})
    assert trial is not None and trial.index_of("ending") is not None
    assert painter.preview_items and not any(i in painter.owner for i in painter.preview_items)
    px0, py0, px1, py1 = painter.rect_of(trial.boxes[trial.index_of("ending")])
    assert painter.box_at((px0 + px1) / 2, (py0 + py1) / 2) is None        # never hit
    order = {item: i for i, item in enumerate(canvas.find_all())}
    arrow, preview_item = order[edge], order[painter.preview_items[0]]
    box_item, glow_item = order[painter.boxes["side"].rect], order[box_glow]
    chip = order[painter.chips[now.edge_key(0)][0]] if painter.chips else None
    assert arrow < preview_item < box_item < glow_item
    assert chip is None or glow_item < chip
    assert order[ghost] > box_item
    clock.advance(500)
    painter.glow(glow.tick())
    assert ("box", "side") not in painter.glows
    painter.clear_preview()
    assert not painter.preview_items

    # A line inserted at the top shifts every box's line: at most 50 now, in view first,
    # the rest in idle slices.
    shifted = [type(e)(e.name, e.file, e.line + 1) for e in more_labels]
    moved, change = relayout(now, more_links, shifted, pins={**pins, **change.placed})
    assert len(change.lines) == len(shifted) and not change.moved
    painter.apply(moved, change)
    assert 0 < len(shifted) - len(painter.pending_lines) <= LINES_PER_PAINT
    assert painter.pending_lines                        # the boxes out of view wait
    while pending:
        pending.pop()()
    assert not painter.pending_lines
    where = painter.boxes["s39"].where
    assert canvas.itemcget(where, "text").endswith(f":{shifted[39].line}")
    # The scroll region never shrinks.
    extent = painter.extent
    small, change = relayout(moved, more_links[:2], shifted[:3], pins=pins)
    painter.apply(small, change) or painter.draw(small)
    assert painter.extent == extent
