"""F58 Live story map, the wiring steps W1–W5 on a real Tk display (``01-design.md`` §4, AC
checklist; ``04-technical.md`` §7, §16; ``07`` I-4 to I-7, I-10, I-12).

The pure parts are tested in ``test_livemap.py``, ``test_mapwatch.py``, ``test_storymap_live.py``
and ``test_mapcanvas.py``; the timed gates in ``tests/perf/test_live_map_perf.py``. These
check what the window and the view do with them.
"""

import re

import pytest

from tests.perf import gen_map_bench as gen
from tests.tools.editor.canvas_counter import CountingCanvas

tk = pytest.importorskip("tkinter")
pytestmark = pytest.mark.tk

# Every index tag F45/F46 drew with (I-10): none may remain.
INDEX_TAG = re.compile(r"^(box|rect|edge|chip|chipbox|chiptext|chipif|name|where|marks|scene|"
                       r"inner|startbar|wipe|minigame|chapter)\d+$")


@pytest.fixture
def root():
    from tests.tools.editor.test_window import new_root
    made = new_root()
    made.geometry("1200x800")
    yield made
    made.destroy()


def map_view(root):
    from engine.tools.editor.views import StoryMapView
    view = StoryMapView(root, background="#1e1e1e", family="Segoe UI", mod="Control",
                        on_open=lambda box: None)
    view.frame.pack(fill="both", expand=True)
    root.update()
    return view


def count(view) -> CountingCanvas:
    """A counting canvas under both the view and its painter."""
    counter = CountingCanvas(view.canvas)
    view.canvas = counter
    view.painter.canvas = counter
    return counter


def jump(n: int):
    return type(gen.links(2)[0])(f"s{n // 2}", f"s{(n // 2 + 7) % n}", "jump", gen.MAIN, 1)


# --- W1: the view draws through MapPainter (AC-F58-15) ------------------------------------------

def test_ac_f58_15_a_one_scene_change_is_drawn_by_stored_id(root):
    calls = {}
    for n in (300, 1000):
        view = map_view(root)
        labels, links = gen.labels(n), gen.links(n)
        view.set_data(labels, links, False)
        root.update()
        canvas = view.canvas
        assert not any(INDEX_TAG.match(tag) for item in canvas.find_all()
                       for tag in canvas.gettags(item))                       # I-10
        view.focus_box(view.layout.index_of(f"s{n // 2}"))
        view.select_box(view.layout.index_of("s1"))
        counter = count(view)
        view.set_data(labels, links + [jump(n)], False)
        assert counter.deleted_all == 0
        assert counter.shared_restyles({"box", "edge", "chip", "edge-jump", "edge-call",
                                        "edge-menu", "ring", "handle"}) == 0
        calls[n] = counter.total()
        assert (f"s{n // 2}", f"s{(n // 2 + 7) % n}", "jump") in view.painter.edges
        assert view.focused_name() == f"s{n // 2}" and view.selected_name() == "s1"
        assert not any(INDEX_TAG.match(tag) for item in counter.real.find_all()
                       for tag in counter.real.gettags(item))
        view.frame.destroy()
    assert calls[300] == calls[1000]
