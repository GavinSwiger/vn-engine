"""Studio UX 4.1 and 4.2: the motion budget (``motion``) and milestone celebrations
(``celebrate``), and 9.2's rule that Reduce motion makes every motion an instant change.

The clock and the timer are fakes for ``Motion``; the window test makes an empty game in a
temporary folder (never the example game's ``.studio``) and applies the headless check's
real results, as ``test_studio_guide`` does."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from engine.tools.editor import celebrate, files, guide, motion, studiostate
from engine.tools.editor.celebrate import Celebration, Milestones
from engine.tools.editor.checker import CheckEvent, CheckState
from engine.tools.editor.guide import GuideFacts
from engine.tools.editor.motion import MAX_MS, Motion
from engine.tools.editor.preview import PreviewEvent, PreviewState
from engine.tools.editor.studiostate import StudioState, decode_state, encode_state
from tests.tools.f45_games import check


# --- motion: one clock, capped, and Reduce motion cuts ------------------------------------------

class FakeWidget:
    """``after``/``after_cancel`` that wait for ``run`` (time moves by the fake clock)."""

    def __init__(self) -> None:
        self.now = 0.0
        self.calls: dict[int, tuple[float, object]] = {}
        self.next = 0

    def after(self, ms, fn):
        self.next += 1
        self.calls[self.next] = (self.now + ms, fn)
        return self.next

    def after_cancel(self, after_id):
        self.calls.pop(after_id, None)

    def run(self, ms: float) -> None:
        end = self.now + ms
        while True:
            due = [(at, i) for i, (at, _fn) in self.calls.items() if at <= end]
            if not due:
                break
            at, i = min(due)
            self.now = at
            self.calls.pop(i)[1]()
        self.now = end


def make_motion(reduce=False):
    widget = FakeWidget()
    flags = {"reduce": reduce}
    return Motion(widget, reduce=lambda: flags["reduce"], now=lambda: widget.now), widget, flags


def test_a_tween_eases_from_0_to_1_on_one_timer_within_the_budget():
    found, widget, _ = make_motion()
    seen_a, seen_b, ended = [], [], []
    found.tween("a", 10_000, seen_a.append, done=lambda: ended.append("a"))   # capped
    found.tween("b", 100, seen_b.append)
    assert seen_a == [0.0] and seen_b == [0.0] and len(widget.calls) == 1   # one clock
    widget.run(120)
    assert seen_b[-1] == 1.0 and not found.running("b") and found.running("a")
    widget.run(MAX_MS)
    assert seen_a[-1] == 1.0 and ended == ["a"] and not found.running()
    assert seen_a == sorted(seen_a) and len(seen_a) > 5                     # eased, rising
    assert not widget.calls                                                 # no idle timer


def test_reduce_motion_hidden_widgets_and_stop_end_at_the_last_step():
    found, widget, flags = make_motion(reduce=True)
    seen = []
    found.tween("a", 200, seen.append)
    assert seen == [1.0] and not widget.calls                              # instant
    flags["reduce"] = False
    seen.clear()
    found.tween("b", 200, seen.append, visible=lambda: False)
    assert seen == [1.0]                                                    # no work hidden
    seen.clear()
    found.tween("c", 200, seen.append)
    found.tween("c", 200, seen.append)                                      # replaces: ends
    assert seen == [0.0, 1.0, 0.0]
    found.stop()
    assert seen[-1] == 1.0 and not widget.calls
    seen.clear()
    found.tween("d", 200, seen.append)
    assert seen == [1.0]                                                    # after close


def test_a_hold_shows_then_fades_back_or_cuts_under_reduce_motion():
    for reduce in (False, True):
        found, widget, _ = make_motion(reduce=reduce)
        log = []
        found.hold("k", motion.HOLD_MS, lambda: log.append("on"), log.append)
        assert log == ["on"]
        widget.run(motion.HOLD_MS - 1)
        assert log == ["on"]
        widget.run(motion.FADE_MS + 50)
        if reduce:
            assert log == ["on", 1.0]
        else:
            assert log[1] == 0.0 and log[-1] == 1.0 and len(log) > 4


# --- Milestones: once per game, only what changes while Studio is open ----------------------------

def facts(choices=0, endings=(), played=False):
    return GuideFacts(folder_name="g", title="G", characters=frozenset({"rin"}),
                      backgrounds=frozenset({"bg pier"}), endings=frozenset(endings),
                      start_rows=3, choices=choices, played=played)


def keys(found):
    return [c.key for c in found]


def test_milestones_start_from_the_first_check_and_show_once():
    found = Milestones()
    assert found.after_check(facts(), False) == []                          # the baseline
    assert keys(found.after_check(facts(choices=1), False)) == ["choice"]
    assert found.after_check(facts(choices=2), False) == []                 # once
    # An ending written is not one reached: only a Play's report counts.
    assert found.after_check(facts(choices=2, endings={"good"}), False) == []
    got = found.reached("Lantern End")
    assert got == [Celebration("ending", "Lantern End")]
    assert got[0].line() == "First ending reached: Lantern End."
    assert found.reached("Other End") == []                                 # once
    # Play finishing the Guide: only the Guide's line, both remembered.
    assert keys(found.played(True)) == ["guide"]
    assert found.celebrated == {"choice", "ending", "play", "guide"}
    assert keys(found.built()) == ["build"] and found.built() == []
    # An old game that already had a choice celebrates none.
    old = Milestones()
    old.after_check(facts(choices=1), True)
    assert old.after_check(facts(choices=2), True) == []
    # Remembered per game: nothing shown twice.
    again = Milestones({"choice", "ending"})
    again.after_check(facts(), False)
    assert again.after_check(facts(choices=1), False) == [] and again.reached("x") == []


def test_every_milestone_is_one_line_and_a_reported_title_is_cut_and_flattened():
    for key in celebrate.MILESTONES:
        line = Celebration(key, "Lantern End").line()
        assert "\n" not in line and line.endswith(".") and ":" in line
    long = Celebration("ending", "A\nvery " + "long " * 40).line()
    assert "\n" not in long and len(long) <= len("First ending reached: .") + 60


def test_a_sample_game_counts_its_own_choices():
    found = Milestones(sample=True)
    sample = sorted(guide.SAMPLE_BASELINE.endings)
    found.after_check(facts(choices=2, endings=sample), False)
    assert found.after_check(facts(choices=2, endings=sample), False) == []
    got = found.after_check(facts(choices=3, endings=[*sample, "harbor"]), False)
    assert got == [Celebration("choice")]
    assert found.reached("Lantern End") == [Celebration("ending", "Lantern End")]


def test_studio_json_keeps_celebrated_words_only():
    assert b"celebrated" not in encode_state(StudioState())
    data = encode_state(StudioState(played=True, celebrated=("play", "choice")))
    assert json.loads(data)["celebrated"] == ["choice", "play"]
    assert decode_state(data) == StudioState(played=True, celebrated=("choice", "play"))
    odd = json.dumps({"celebrated": ["play", 3, "../x", "", "play", "x" * 40]}).encode()
    assert decode_state(odd).celebrated == ("play",)
    assert decode_state(b'{"celebrated": "play"}').celebrated == ()
    assert "celebrated" not in studiostate.KEYS


# --- The budget's motions, without a window ---------------------------------------------------

def test_the_arrow_follows_tks_curve_and_draws_from_tail_to_head():
    points = [0.0, 0.0, 100.0, 0.0, 100.0, 100.0]
    path = motion.spline(points)
    assert path[:2] == [0.0, 0.0] and path[-2:] == [100.0, 100.0]
    assert motion.spline([0.0, 0.0, 5.0, 5.0]) == [0.0, 0.0, 5.0, 5.0]   # straight
    lengths = motion._lengths(path)
    half = motion._prefix(path, lengths, lengths[-1] / 2)
    assert half[:2] == [0.0, 0.0] and len(half) < len(path)
    assert abs(motion._lengths(half)[-1] - lengths[-1] / 2) < 1e-6


def test_the_count_ticks_through_the_numbers_and_ends_on_the_real_text():
    found, widget, flags = make_motion()
    shown = []
    motion.count_to(found, "counts", (9, 0), (0, 2), shown.append)
    widget.run(motion.COUNT_MS + 40)
    values = [v for v in shown if v is not None]
    assert values[0] == (9, 0) and shown[-1] is None
    assert len({v[0] for v in values}) > 3                                  # counting
    assert [v[0] for v in values] == sorted((v[0] for v in values), reverse=True)
    flags["reduce"] = True
    shown.clear()
    motion.count_to(found, "counts", (3, 0), (0, 0), shown.append)
    assert shown == [None]                                                  # a jump
    assert motion.COUNT_MS <= MAX_MS and motion.POP_MS <= MAX_MS
    assert motion.DRAW_MS <= MAX_MS and motion.ROW_FADE_MS <= MAX_MS


# --- On screen: the map, the Events list ---------------------------------------------------------

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)


def _width(canvas, item) -> float:
    x0, _y0, x1, _y1 = canvas.coords(item)
    return x1 - x0


@pytest.mark.tk
def test_a_new_map_box_pops_in_and_its_arrow_draws_and_reduce_motion_skips_both():
    from engine.script.labelgraph import LabelLink
    from engine.tools.editor.checker import NameEntry
    from engine.tools.editor.mapcanvas import BOX_FILL
    from tests.perf import gen_map_bench as gen
    from tests.tools.editor.test_live_map import map_view
    from tests.tools.editor.test_window import new_root

    root = new_root()
    try:
        view = map_view(root)
        fake = FakeWidget()
        view.motion = Motion(fake, reduce=lambda: view.reduce_motion, now=lambda: fake.now)
        labels, links = gen.labels(20), gen.links(20)
        view.set_data(labels, links, False)
        root.update()
        if not view.canvas.winfo_viewable():
            pytest.skip("the test window isn't shown here")
        ref = labels[0].file

        def add(name: str) -> None:
            labels.append(NameEntry(name, ref, 9000 + len(labels)))
            links.append(LabelLink(labels[0].name, name, "jump", ref, 9000 + len(labels)))
            view.set_data(labels, links, False)

        add("pond")
        canvas, painter = view.canvas, view.painter
        rect = painter.boxes["pond"].rect
        surface = str(canvas.cget("background")).lower()
        assert str(canvas.itemcget(rect, "fill")).lower() == surface        # p = 0
        full = _width(canvas, rect) / motion.POP_FROM
        edge = next(k for k in painter.edges if k[1] == "pond")
        arrow = painter.edges[edge]
        assert view.motion.running(("map-box", "pond"))
        assert view.motion.running(("map-edge", edge))
        assert str(canvas.itemcget(arrow, "smooth")) in ("0", "false")      # drawing
        fake.run(motion.DRAW_MS + 40)
        assert str(canvas.itemcget(rect, "fill")).lower() == BOX_FILL.lower()
        assert abs(_width(canvas, rect) - full) < 0.5                       # full size
        assert str(canvas.itemcget(arrow, "smooth")) in ("1", "true")
        assert canvas.coords(arrow) == pytest.approx(painter.edge_points(
            view.layout, view.layout.edge_keys[edge]))
        view.reduce_motion = True
        add("well")
        assert str(canvas.itemcget(painter.boxes["well"].rect, "fill")).lower() \
            == BOX_FILL.lower() and not view.motion.running()
    finally:
        root.destroy()


@pytest.mark.tk
def test_a_deleted_events_row_fades_in_place_then_the_gap_closes():
    from engine.tools.editor.eventsview import EventsView, ROW_FADE_KEY
    from engine.tools.editor.forms import Row
    from tests.tools.editor.test_window import new_root

    root = new_root()
    try:
        root.geometry("420x480")
        view = EventsView(root, fonts={})
        view.frame.pack(fill="both", expand=True)
        fake = FakeWidget()
        flags = {"reduce": False}
        view.motion = Motion(fake, reduce=lambda: flags["reduce"], now=lambda: fake.now)
        rows = [Row(i, 0, 0, "Say", f"line {i}", "say", {}) for i in range(5)]
        view.set_rows(rows, title="harbor")
        root.update()
        if not view.tree.winfo_viewable():
            pytest.skip("the test window isn't shown here")
        view.set_rows(rows[:2] + rows[3:], title="harbor", select=2)
        tree = view.tree
        assert view.texts() == ["Say  line 0", "Say  line 1", "Say  line 3", "Say  line 4"]
        ghosts = [w for w in tree.winfo_children() if isinstance(w, tk.Canvas)]
        assert len(ghosts) == 1 and view.motion.running(ROW_FADE_KEY)
        texts = [ghosts[0].itemcget(i, "text") for i in ghosts[0].find_all()]
        assert "".join(texts).replace("\t", "").startswith("Sayline 2")
        assert int(tree.tag_cget(motion.GAP_TAG, "spacing1")) > 0           # rows stay put
        assert tree.tag_ranges(motion.GAP_TAG)[0].string == "3.0"           # line 3's place
        fake.run(motion.ROW_FADE_MS + 40)
        assert not [w for w in tree.winfo_children() if isinstance(w, tk.Canvas)]
        assert motion.GAP_TAG not in tree.tag_names()
        # Another scene, or Reduce motion: the list just changes.
        view.set_rows(rows[:1], title="pier")
        assert not view.motion.running()
        flags["reduce"] = True
        view.set_rows(rows[:3], title="pier")
        view.set_rows(rows[:2], title="pier")
        assert not view.motion.running() and not [
            w for w in tree.winfo_children() if isinstance(w, tk.Canvas)]
    finally:
        root.destroy()


# --- The window: lanterns and one line, the count, the clean chip, Reduce motion -----------------

def apply_check(ed, game: Path) -> None:
    result = replace(check(game), serial=ed.win.edit_serial)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    ed.root.update()


def wait_toast(ed) -> None:
    ed.root.after(celebrate.TOAST_GAP_MS + 50, lambda: None)
    for _ in range(40):
        ed.root.update()
        if ed.win.toasts.toast is not None:
            return
        ed.root.after(25)


@pytest.mark.tk
def test_milestones_float_lanterns_with_one_line_once_per_game_and_reduce_motion_is_still(
        studio, tmp_path, monkeypatch):
    game = files.new_game(tmp_path / "ferry", template=files.TEMPLATE_EMPTY)
    assert isinstance(game, Path)
    ed = studio(game, mapped=True)
    win = ed.win
    monkeypatch.setattr(win, "_toast_ready", lambda: True)
    assert win.story_map.motion is win.motion                              # one clock
    assert win.events_view.motion is win.motion
    apply_check(ed, game)                                                   # the baseline
    assert win.toasts.toast is None

    # A choice of the author's own: lanterns and one line.
    widget = win.record_for("script/main.vns").widget
    widget.insert("end-1c", '\n    menu:\n        "Stay":\n            "I stayed."\n'
                            '        "Go":\n            "I went."\n'
                            'label last:\n    ending good "Good End"\n')
    win.save_all()
    apply_check(ed, game)
    toast = win.toasts.toast
    assert toast.line() == "First choice: players can take different paths now."
    assert toast.lanterns is not None and win.motion.running(("celebration", "lanterns"))
    sky = toast.lanterns.canvas                                             # map or sky
    assert sky.find_withtag(celebrate.Lanterns.TAG)
    assert str(win.root.focus_get()) != str(toast.canvas)                   # never focused
    state = json.loads((game / ".studio" / "studio.json").read_text(encoding="utf-8"))
    assert state["celebrated"] == ["choice"]                                # written, not reached
    toast.canvas.event_generate("<Button-1>", x=5, y=5)                     # click: gone
    ed.root.update()
    assert win.toasts.toast is None and toast.closed and toast.lanterns.done
    assert not sky.winfo_exists() or not sky.find_withtag(celebrate.Lanterns.TAG)

    # The first ending a Play reaches (the game's line reports, through on_game_event).
    from engine.tools.editor.preview import GameEvent
    reports = [GameEvent("at", {"file": "script/main.vns", "line": 2, "scene": "start"}),
               GameEvent("ending", {"id": "lantern", "title": "Lantern End"})]
    monkeypatch.setattr(win.runner, "game_events", lambda: reports, raising=False)
    win._poll_game_events()
    reports = []
    wait_toast(ed)
    assert win.toasts.toast.line() == "First ending reached: Lantern End."
    win.toasts.toast.close()
    win._game_event("ending", {"id": "other", "title": "Other End"})        # once
    wait_toast(ed)
    assert win.toasts.toast is None

    # Reduce motion: a still banner (no lanterns, no slide).
    win.reduce_motion.set(True)
    win.build_finished()
    ed.root.update()
    assert win.toasts.toast.line() == "First build: your game is ready to share."
    assert win.toasts.toast.lanterns is None and not win.motion.running()
    win.toasts.toast.close()

    # The count ticks to its new value; a clean check turns the chip green with a tick.
    win.reduce_motion.set(False)
    win._counts = (3, 1)
    win._celebration_check(replace(check(game), problems=()))              # a clean check
    item = win.check_counts
    label = item.label
    assert win.motion.running("counts") and item.passing is not None
    assert str(label.cget("foreground")).upper() == celebrate.SUCCESS.upper()
    assert str(label.cget("image"))
    win.motion.finish("counts")
    assert item.passing is None and str(label.cget("text")) == item.text
    win.motion.finish("clean")
    assert str(label.cget("foreground")) == win.status_bar.foreground
    assert not str(label.cget("image"))

    # Remembered for this game: a new window doesn't celebrate them again.
    again = studio(game)
    assert again.win.milestones.celebrated >= {"choice", "ending", "build"}
    win.apply_events([PreviewEvent(PreviewState.RUNNING)])
    ed.root.update()
    assert win.toasts.toast.line() == "First Play: your story ran in its own window."
