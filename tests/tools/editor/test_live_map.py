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


# --- W2: typing and actions (AC-F58-19, 20, 21, 32, 39) ------------------------------------------
# Studio L (F46's lanterns game) from test_studio_storyedit.py.

from tests.tools.editor.test_studio_storyedit import (  # noqa: E402
    CH2, MAIN, click_box, drag, draw_arrow, events_on, lanterns, places, point, studio_l)
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401
from tests.tools.editor.test_window import take_focus  # noqa: E402

assert lanterns                                          # a fixture, used by name


def follow(ed, source: str = "action") -> None:
    ed.win.follow_now(source)
    ed.root.update()


def names_of(view) -> set[str]:
    return {b.name for b in view.layout.boxes}


def add_pond(ed) -> None:
    """A new scene at the end of ch2 (as an outside change would bring it)."""
    ed.win.record_for(CH2).widget.insert("end", "\nlabel pond:\n    return\n")


def drop_pond(ed) -> None:
    widget = ed.win.record_for(CH2).widget
    start = widget.search("label pond:", "1.0")
    widget.delete(f"{start} -1c", "end")


def test_ac_f58_19_tidy_up_rearranges_pinned_boxes_and_its_undo_restores_them(studio,
                                                                              lanterns):
    from engine.tools.editor.storymap import layout, layout_places
    ed = studio_l(studio, lanterns)
    view, canvas, history = ed.story_map, ed.map_canvas, ed.win.map_history
    first = places(view)
    assert view.pins.of(None) == first and not view.places
    main = ed.win.files[MAIN].widget
    assert main.get("10.0", "10.end") == "    jump festival"
    main.delete("10.0", "11.0")                          # festival is no longer reached
    follow(ed)
    assert places(view) == first                         # pinned: nothing moved (PR-07)
    cells = layout_places(layout(view.links, view.labels))
    assert cells != first and view.can_tidy()
    steps = len(history)
    pins = view.pins.snapshot()
    view.tidy_button.invoke()
    assert places(view) == cells == view.pins.of(None) and len(history) == steps + 1
    assert history.undo_step().pins == (pins, view.pins.snapshot())
    take_focus(canvas)
    ed.press(canvas, "<Control-z>")
    assert places(view) == first and view.pins.snapshot() == pins
    ed.press(canvas, "<Control-y>")
    assert places(view) == cells


def test_ac_f58_20_a_change_during_a_gesture_waits_for_its_end(studio, lanterns):
    from engine.tools.editor.livemap import S3
    ed = studio_l(studio, lanterns)
    view, canvas = ed.story_map, ed.map_canvas
    done = []

    def check(start, held, end) -> None:
        before = names_of(view)
        start()
        add_pond(ed)
        follow(ed, "disk")
        assert held(), "the update cancelled the gesture"
        assert view.live_text == S3 and names_of(view) == before
        end()
        ed.root.update()
        assert "pond" in names_of(view) and view.live_text == ""
        drop_pond(ed)
        follow(ed)
        assert "pond" not in names_of(view)
        done.append(start)

    check(lambda: drag(ed, "river", (40, 20), release=False), lambda: view.drag is not None,
          lambda: ed.press(canvas, "<Escape>"))
    check(lambda: (view.focus_box(view.layout.index_of("river")), take_focus(canvas),
                   view.start_move(), ed.press(canvas, "<Right>")),
          lambda: view.moving is not None, lambda: ed.press(canvas, "<Escape>"))
    check(lambda: draw_arrow(ed, "festival", "river", release=False),
          lambda: view.link is not None and view.link.target is not None,
          lambda: ed.press(canvas, "<Escape>"))
    menu = view.edge_index("stall", "river", "menu")
    check(lambda: view.open_choice_field(menu), lambda: view.field is not None,
          lambda: view.field.entry.event_generate("<Escape>"))
    assert len(done) == 4


def test_ac_f58_21_selection_ring_hover_zoom_and_scroll_survive_an_update(studio, lanterns):
    ed = studio_l(studio, lanterns)
    view, canvas = ed.story_map, ed.map_canvas
    click_box(ed, "river")                               # selected and focused
    ed.win.close_side()
    view.select_box(view.layout.index_of("river"))
    view.select_edge(view.edge_index("stall", "river", "menu"))
    take_focus(canvas)
    ed.press(canvas, "<Control-equal>")                  # 125 %
    ed.win.files[MAIN].widget.insert("end", "\nlabel far:\n    return\n")
    follow(ed, "disk")
    x, y = point(ed, "festival")
    canvas.event_generate("<Motion>", x=x, y=y)
    canvas.xview_moveto(0.05)
    ed.root.update()
    seen = (canvas.xview(), canvas.yview())
    region = [float(v) for v in str(canvas.cget("scrollregion")).split()]
    ring = canvas.coords(view.ring)
    add_pond(ed)
    follow(ed, "disk")
    assert "pond" in names_of(view) and view.zoom == 125
    assert view.selected_name() == "river" and view.focused_name() == "river"
    assert view.selected_edge()[:3] == ("stall", "river", "menu")
    assert view.hovered is not None and view.layout.boxes[view.hovered].name == "festival"
    assert view._handle is not None and canvas.coords(view.ring) == ring
    assert (canvas.xview(), canvas.yview()) == seen     # Follow changes is off: no scroll
    now = [float(v) for v in str(canvas.cget("scrollregion")).split()]
    assert now[2] >= region[2] and now[3] >= region[3]
    widget = ed.win.files[MAIN].widget                   # far goes: the region stays
    widget.delete(f"{widget.search('label far:', '1.0')} -1c", "end")
    follow(ed, "disk")
    assert "far" not in names_of(view)
    assert [float(v) for v in str(canvas.cget("scrollregion")).split()] == now


def test_ac_f58_32_live_updates_add_no_map_step_and_a_reload_blocks_older_ones(
        studio, lanterns):
    from engine.tools.editor.storymap import undo_blocked_text
    ed = studio_l(studio, lanterns)
    win, view, history = ed.win, ed.story_map, ed.win.map_history
    view.select_edge(view.edge_index("stall", "river", "jump"))
    assert win.delete_arrow() is not None and len(history) == 1
    add_pond(ed)
    follow(ed, "disk")                                   # a live update: no step
    assert "pond" in names_of(view) and len(history) == 1
    assert win.save_record(win.files[CH2])
    (lanterns / CH2).write_bytes((lanterns / CH2).read_bytes() + b"\n# from outside\n")
    win.check_outside_changes()                          # reloaded from disk
    take_focus(ed.map_canvas)
    ed.press(ed.map_canvas, "<Control-z>")
    assert view.message == undo_blocked_text((CH2,)) and len(history) == 0


def test_ac_f58_39_a_throttle_tick_marks_nothing_out_of_date_and_skips_events(
        studio, lanterns, monkeypatch):
    from engine.tools.editor import livemap
    from tests.tools.editor.live_fakes import FakeClock
    ed = studio_l(studio, lanterns)
    win, view = ed.win, ed.story_map
    events_on(ed, "stall")
    ed.root.update()
    clock = FakeClock()
    win.follow_clock = livemap.FollowClock(win._follow_tick, after=clock.after,
                                           cancel=clock.after_cancel, now=clock.now)
    refreshed: list[int] = []
    real = win._follow_events
    monkeypatch.setattr(win, "_follow_events", lambda: (refreshed.append(1), real())[1])
    ch2 = win.files[CH2].widget
    ch2.delete("9.4", "9.end")
    ch2.insert("9.4", "jump")                            # stall doesn't parse now
    for _ in range(5):                                   # still typing, 50 ms apart
        clock.advance(50)
        ch2.insert("8.end", "x")
    ed.root.update()
    assert clock.now() >= 250 and not refreshed          # a throttle tick ran: no Events
    assert "stall" not in view.out_of_date               # and nothing newly out of date
    assert "out of date" not in view.layout.boxes[view.layout.index_of("stall")].marks
    clock.advance(livemap.FOLLOW_MS)                     # the pause tick
    ed.root.update()
    assert "stall" in view.out_of_date and refreshed
