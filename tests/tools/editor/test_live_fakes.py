"""F58 P0: the CI-safe proxies themselves (``live_fakes``, ``canvas_counter``) behave as the
perf gates' unit tests rely on (04 §11, §16 P0)."""

import pytest

from tests.tools.editor.canvas_counter import CountingCanvas
from tests.tools.editor.live_fakes import FakeClock, count_calls


def test_fake_clock_runs_due_timers_in_order_and_counts_calls(monkeypatch):
    clock = FakeClock()
    fired: list[tuple[str, float]] = []
    clock.after(100, lambda: fired.append(("a", clock.now())))
    cancelled = clock.after(50, lambda: fired.append(("x", clock.now())))
    clock.after(50, lambda: clock.after(30, lambda: fired.append(("c", clock.now()))))
    clock.after_cancel(cancelled)
    clock.advance(99)
    assert fired == [("c", 80.0)] and clock.now() == 99
    clock.advance(1)
    assert fired[-1] == ("a", 100.0) and clock.pending == 0

    class Owner:
        @staticmethod
        def work(x):
            return x * 2

    counted = count_calls(monkeypatch, Owner, "work")
    assert Owner.work(3) == 6 and counted.n == 1 and counted.args == [(3,)]


@pytest.mark.tk
def test_counting_canvas_counts_and_spots_delete_all_and_shared_restyles():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk can't start here: {exc}")
    try:
        class View:
            canvas = tk.Canvas(root)

        view = View()
        counter = CountingCanvas.install(view)
        item = view.canvas.create_rectangle(0, 0, 5, 5, tags=("box", "box1"))
        view.canvas.itemconfigure(item, outline="red")
        view.canvas.itemconfigure("chip", width=2)
        view.canvas.delete("all")
        assert counter.calls["create_rectangle"] == 1 and counter.deleted_all == 1
        assert counter.shared_restyles({"chip", "box"}) == 1
        assert counter.total(ignore={"delete"}) == 3
        counter.reset()
        assert counter.total() == 0 and str(view.canvas) == str(counter.real)
    finally:
        root.destroy()
