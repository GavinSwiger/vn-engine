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
    got = found.after_check(facts(choices=2, endings={"good"}), False)
    assert got == [Celebration("ending", "good")]
    assert got[0].texts() == ("First ending: good", "Your story can finish now.")
    # Play finishing the Guide: only the Guide's toast, both remembered.
    assert keys(found.played(True)) == ["guide"]
    assert found.celebrated == {"choice", "ending", "play", "guide"}
    assert keys(found.built()) == ["build"] and found.built() == []
    # An old game that already had a choice and an ending celebrates neither.
    old = Milestones()
    old.after_check(facts(choices=1, endings={"good"}), True)
    assert old.after_check(facts(choices=2, endings={"good", "bad"}), True) == []
    # Remembered per game: nothing shown twice.
    again = Milestones({"choice", "ending"})
    again.after_check(facts(), False)
    assert again.after_check(facts(choices=1, endings={"x"}), False) == []


def test_a_sample_game_counts_its_own_choices_and_endings():
    found = Milestones(sample=True)
    sample = sorted(guide.SAMPLE_BASELINE.endings)
    found.after_check(facts(choices=2, endings=sample), False)
    assert found.after_check(facts(choices=2, endings=sample), False) == []
    got = found.after_check(facts(choices=3, endings=[*sample, "harbor"]), False)
    assert got == [Celebration("choice"), Celebration("ending", "harbor")]


def test_studio_json_keeps_celebrated_words_only():
    assert b"celebrated" not in encode_state(StudioState())
    data = encode_state(StudioState(played=True, celebrated=("play", "choice")))
    assert json.loads(data)["celebrated"] == ["choice", "play"]
    assert decode_state(data) == StudioState(played=True, celebrated=("choice", "play"))
    odd = json.dumps({"celebrated": ["play", 3, "../x", "", "play", "x" * 40]}).encode()
    assert decode_state(odd).celebrated == ("play",)
    assert decode_state(b'{"celebrated": "play"}').celebrated == ()
    assert "celebrated" not in studiostate.KEYS


# --- The window: toasts, the counts' flash, Reduce motion ----------------------------------------

tk = pytest.importorskip("tkinter")
from tests.tools.editor.test_studio_window import studio  # noqa: E402,F401  (fixture)


def apply_check(ed, game: Path) -> None:
    result = replace(check(game), serial=ed.win.edit_serial)
    ed.win.apply_check_events([CheckEvent(CheckState.DONE, result.serial, result)])
    ed.root.update()


def toast_texts(ed) -> list[str]:
    toast = ed.win.toasts.toast
    if toast is None:
        return []
    canvas = toast.canvas
    return [str(canvas.itemcget(i, "text")) for i in canvas.find_all()
            if canvas.type(i) == "text"]


@pytest.mark.tk
def test_milestones_show_a_toast_once_per_game_and_reduce_motion_keeps_it_still(
        studio, tmp_path, monkeypatch):
    game = files.new_game(tmp_path / "ferry", template=files.TEMPLATE_EMPTY)
    assert isinstance(game, Path)
    ed = studio(game, mapped=True)
    win = ed.win
    monkeypatch.setattr(win, "_toast_ready", lambda: True)
    assert win.story_map.motion is win.motion                              # one clock
    apply_check(ed, game)                                                   # the baseline
    assert win.toasts.toast is None

    # A choice and an ending of the author's own: two toasts, one after the other.
    widget = win.record_for("script/main.vns").widget
    widget.insert("end-1c", '\n    menu:\n        "Stay":\n            "I stayed."\n'
                            '        "Go":\n            "I went."\n'
                            'label last:\n    ending good "Good End"\n')
    win.save_all()
    apply_check(ed, game)
    assert toast_texts(ed)[:2] == ["First choice", "Players can now take different paths."]
    toast = win.toasts.toast
    assert toast.particles and win.motion.running(("toast", "confetti"))  # confetti
    assert str(win.root.focus_get()) != str(toast.canvas)                   # never focused
    state = json.loads((game / ".studio" / "studio.json").read_text(encoding="utf-8"))
    assert set(state["celebrated"]) == {"choice", "ending"}
    toast.canvas.event_generate("<Button-1>", x=5, y=5)                     # click: gone
    ed.root.update()
    assert win.toasts.toast is None and toast.closed
    ed.root.after(celebrate.TOAST_GAP_MS + 50, lambda: None)
    for _ in range(40):
        ed.root.update()
        if win.toasts.toast is not None:
            break
        ed.root.after(25)
    assert toast_texts(ed)[:1] == ["First ending: good"]
    win.toasts.toast.close()

    # Reduce motion: a plain toast (no slide, no confetti).
    win.reduce_motion.set(True)
    win.build_finished()
    ed.root.update()
    assert toast_texts(ed)[:1] == ["First build"]
    assert not win.toasts.toast.particles and not win.motion.running()
    win.toasts.toast.close()

    # A fixed problem: the counts turn green, then back (a cut under Reduce motion).
    win._problem_total = 2
    apply_check(ed, game)
    label = win.check_counts.label
    assert str(label.cget("foreground")).upper() == celebrate.SUCCESS.upper()
    win.motion.finish("counts")
    assert str(label.cget("foreground")) == win.status_bar.foreground

    # Remembered for this game: a new window doesn't celebrate them again.
    again = studio(game)
    assert again.win.milestones.celebrated >= {"choice", "ending", "build"}
    win.apply_events([PreviewEvent(PreviewState.RUNNING)])
    ed.root.update()
    assert toast_texts(ed)[:1] == ["First play"]


@pytest.mark.tk
def test_a_new_map_box_fades_in_from_the_surface_and_reduce_motion_skips_it():
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
        ref = labels[0].file

        def add(name: str) -> None:
            labels.append(NameEntry(name, ref, 9000 + len(labels)))
            view.set_data(labels, links, False)

        add("pond")
        rect = view.painter.boxes["pond"].rect
        surface = str(view.canvas.cget("background")).lower()
        if not view.canvas.winfo_viewable():
            pytest.skip("the test window isn't shown here")
        assert str(view.canvas.itemcget(rect, "fill")).lower() == surface      # p = 0
        assert view.motion.running(("map-box", "pond"))
        fake.run(motion.FADE_MS + 20)
        assert str(view.canvas.itemcget(rect, "fill")).lower() == BOX_FILL.lower()
        view.reduce_motion = True
        add("well")
        assert str(view.canvas.itemcget(view.painter.boxes["well"].rect, "fill")).lower() \
            == BOX_FILL.lower() and not view.motion.running()
    finally:
        root.destroy()
